"""Transactional submission creation and immutable source versioning."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.config import DocumentSettings
from app.documents.errors import DocumentInputError, DocumentProcessingError
from app.documents.extraction import extract_text
from app.documents.storage import LocalDocumentStorage
from app.documents.text_processing import normalize_text
from app.documents.validation import validate_document
from app.models import AnalysisRun, Submission, SubmissionVersion, WorkspaceMembership
from app.modules.analysis.orchestrator import run_analysis_pipeline
from app.modules.tenancy.schemas import TenantScope


@dataclass(frozen=True, slots=True)
class SubmissionAnalysisResult:
    submission: Submission
    version: SubmissionVersion
    analysis_run: AnalysisRun
    extraction_status: str = "Not required"
    extracted_text: str | None = None


def create_submission_version(
    db: Session,
    tenant_scope: TenantScope,
    submitter_id: UUID,
    source_type: Literal["text", "pdf", "docx"],
    submitted_text: str | None = None,
    file_reference: bytes | None = None,
    original_file_key: str | None = None,
) -> SubmissionVersion:
    """Create a submission and immutable first version in one transaction.

    ``submitter_id`` is the user's ID. File based sources accept the source
    bytes here so their digest is computed from content; storage/upload remains
    a separate concern and no file is written by this service.
    """
    if source_type == "text":
        if submitted_text is None or file_reference is not None:
            raise ValueError("Text submissions require submitted_text only.")
        source_bytes = submitted_text.encode("utf-8")
    else:
        if file_reference is None or submitted_text is not None:
            raise ValueError("File submissions require file_reference bytes only.")
        source_bytes = file_reference

    membership_id = db.scalar(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.organization_id == tenant_scope.organization_id,
            WorkspaceMembership.workspace_id == tenant_scope.workspace_id,
            WorkspaceMembership.user_id == submitter_id,
            WorkspaceMembership.status == "active",
        )
    )
    if membership_id is None:
        raise ValueError("Submitter is not an active member of the tenant workspace.")

    submission_id = uuid4()
    version = SubmissionVersion(
        id=uuid4(),
        organization_id=tenant_scope.organization_id,
        workspace_id=tenant_scope.workspace_id,
        submission_id=submission_id,
        version_number=1,
        source_type=source_type,
        submitted_text=submitted_text,
        original_file_key=original_file_key,
        source_hash=sha256(source_bytes).hexdigest(),
        submitter_membership_id=membership_id,
        prior_version_id=None,
    )
    submission = Submission(
        id=submission_id,
        organization_id=tenant_scope.organization_id,
        workspace_id=tenant_scope.workspace_id,
        created_by_membership_id=membership_id,
        current_status="Submitted",
    )

    try:
        db.add_all([submission, version])
        db.flush()
        # The request may already have opened a transaction while resolving
        # its tenant scope. Committing here commits that transaction and both
        # new rows atomically.
        db.commit()
    except Exception:
        db.rollback()
        raise
    return version


def create_submission_with_analysis(
    db: Session,
    tenant_scope: TenantScope,
    submitter_id: UUID,
    source_type: Literal["text", "pdf", "docx"],
    submitted_text: str | None = None,
    file_reference: bytes | None = None,
    original_file_key: str | None = None,
    analysis_text: str | None = None,
) -> SubmissionAnalysisResult:
    """Persist a source version, then analyze that exact durable version.

    Submission persistence intentionally commits before analysis. The
    orchestrator persists each stage independently, so a failed required stage
    leaves the source durable and returns a traceable Incomplete analysis run.
    """
    version = create_submission_version(
        db,
        tenant_scope,
        submitter_id=submitter_id,
        source_type=source_type,
        submitted_text=submitted_text,
        file_reference=file_reference,
        original_file_key=original_file_key,
    )
    analysis_run = run_analysis_pipeline(db, version, tenant_scope, analysis_text=analysis_text)
    submission = db.get(Submission, version.submission_id)
    if submission is None:
        raise RuntimeError("The newly persisted submission could not be reloaded.")
    return SubmissionAnalysisResult(submission, version, analysis_run)


def create_document_submission_with_analysis(
    db: Session,
    tenant_scope: TenantScope,
    submitter_id: UUID,
    *,
    filename: str | None,
    content: bytes,
    settings: DocumentSettings,
) -> SubmissionAnalysisResult:
    """Validate and extract a PDF/DOCX, store its source, then analyze it.

    Extraction happens before any database rows or storage objects are created.
    The original file is deleted if source-version persistence fails. Once the
    immutable version commits, analysis-stage failures retain both source and
    extracted artifact and are reported as an Incomplete run by the orchestrator.
    """
    document = validate_document(filename, content, settings.max_upload_bytes)
    if document.extension not in {".pdf", ".docx"}:
        raise DocumentInputError(
            "unsupported_submission_format",
            "Submission uploads must be PDF or DOCX files. Paste plain text in the intake form.",
            415,
        )
    extracted_text = normalize_text(extract_text(document))
    if not extracted_text:
        raise DocumentProcessingError(
            "no_extractable_text",
            "No readable text was found. Scanned-image OCR is not supported.",
        )

    storage = LocalDocumentStorage(settings.storage_path / "submissions")
    original_file_key = storage.save(document.content, document.extension)
    try:
        version = create_submission_version(
            db,
            tenant_scope,
            submitter_id=submitter_id,
            source_type=document.extension[1:],
            file_reference=document.content,
            original_file_key=original_file_key,
        )
    except Exception:
        storage.delete(original_file_key)
        raise

    # The version is durable at this point. Do not remove the original file if
    # an unexpected analysis error occurs after the version has committed.
    analysis_run = run_analysis_pipeline(db, version, tenant_scope, analysis_text=extracted_text)
    submission = db.get(Submission, version.submission_id)
    if submission is None:
        raise RuntimeError("The newly persisted submission could not be reloaded.")
    return SubmissionAnalysisResult(
        submission,
        version,
        analysis_run,
        extraction_status="Succeeded",
        extracted_text=extracted_text,
    )
