"""Tenant-scoped upload and listing for private evidence files."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_event
from app.documents.config import DocumentSettings
from app.documents.errors import DocumentInputError, DocumentProcessingError
from app.documents.extraction import extract_text
from app.documents.storage import LocalDocumentStorage
from app.documents.text_processing import normalize_text
from app.documents.validation import validate_document
from app.models import EvidenceRecord, EvidenceStateEvent, EvidenceVersion, WorkspaceMembership
from app.modules.tenancy.schemas import TenantScope


def _private_storage(settings: DocumentSettings) -> LocalDocumentStorage:
    return LocalDocumentStorage(settings.storage_path / "evidence")


def upload_evidence(
    db: Session,
    scope: TenantScope,
    *,
    filename: str | None,
    content: bytes,
    title: str,
    valid_from: date | None,
    valid_until: date | None,
    settings: DocumentSettings,
) -> tuple[EvidenceRecord, EvidenceVersion]:
    """Extract, privately store, and register one uploaded evidence version."""
    document = validate_document(filename, content, settings.max_upload_bytes)
    if document.extension not in {".pdf", ".docx"}:
        raise DocumentInputError("unsupported_format", "Evidence uploads must be PDF or DOCX files.", 415)
    extracted_text = normalize_text(extract_text(document))
    if not extracted_text:
        raise DocumentProcessingError("empty_document", "No readable text was found in the document.")
    clean_title = title.strip()
    if not clean_title:
        raise DocumentInputError("invalid_title", "Provide a title for the evidence document.")
    if len(clean_title) > 300:
        raise DocumentInputError("invalid_title", "Evidence title must be 300 characters or fewer.")
    if valid_from and valid_until and valid_from > valid_until:
        raise DocumentInputError("invalid_validity_range", "The effective date must not be after the expiry date.")

    membership_id = db.scalar(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.organization_id == scope.organization_id,
            WorkspaceMembership.workspace_id == scope.workspace_id,
            WorkspaceMembership.user_id == scope.user_id,
            WorkspaceMembership.status == "active",
        )
    )
    if membership_id is None:
        raise PermissionError("The active workspace membership could not be resolved.")

    storage = _private_storage(settings)
    storage_key = storage.save(document.content, document.extension)
    try:
        record = EvidenceRecord(
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            owner_membership_id=membership_id,
            primary_lifecycle_state="Uploaded",
            is_inactive=False,
        )
        db.add(record)
        db.flush()
        version = EvidenceVersion(
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            evidence_record_id=record.id,
            version_number=1,
            title=clean_title,
            source_reference=document.original_filename,
            private_file_key=storage_key,
            extracted_text=extracted_text,
            valid_from=valid_from,
            valid_until=valid_until,
            owner_snapshot=None,
            created_by_membership_id=membership_id,
            pending_reapproval=False,
            checksum=sha256(document.content).hexdigest(),
        )
        db.add(version)
        db.flush()
        record.current_version_id = version.id
        db.add(EvidenceStateEvent(
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            evidence_record_id=record.id,
            evidence_version_id=version.id,
            actor_membership_id=membership_id,
            event_type="uploaded",
            old_value=None,
            new_value="Uploaded",
            reason=None,
        ))
        record_event(
            db,
            scope,
            actor_membership_id=membership_id,
            action_key="evidence.uploaded",
            target_type="evidence_record",
            target_id=record.id,
            safe_metadata={"version_id": str(version.id), "filename": document.original_filename},
        )
        db.commit()
        db.refresh(record)
        db.refresh(version)
        return record, version
    except Exception:
        db.rollback()
        storage.delete(storage_key)
        raise


def list_evidence(db: Session, scope: TenantScope) -> list[tuple[EvidenceRecord, EvidenceVersion | None]]:
    """List current evidence versions in the caller's workspace only."""
    return list(
        db.execute(
            select(EvidenceRecord, EvidenceVersion)
            .outerjoin(
                EvidenceVersion,
                (EvidenceVersion.id == EvidenceRecord.current_version_id)
                & (EvidenceVersion.evidence_record_id == EvidenceRecord.id)
                & (EvidenceVersion.organization_id == EvidenceRecord.organization_id)
                & (EvidenceVersion.workspace_id == EvidenceRecord.workspace_id),
            )
            .where(
                EvidenceRecord.organization_id == scope.organization_id,
                EvidenceRecord.workspace_id == scope.workspace_id,
            )
            .order_by(EvidenceRecord.created_at.desc(), EvidenceRecord.id)
        ).all()
    )
