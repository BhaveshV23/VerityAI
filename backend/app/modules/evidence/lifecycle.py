"""Audited evidence lifecycle and validity-version operations."""

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_event
from app.models import (
    EvidenceConflict,
    EvidenceConflictSource,
    EvidenceRecord,
    EvidenceStateEvent,
    EvidenceVersion,
    WorkspaceMembership,
)
from app.modules.tenancy.schemas import TenantScope


def _failure(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": {"code": code, "message": message}})


def _context(db: Session, scope: TenantScope, evidence_id: UUID) -> tuple[EvidenceRecord, EvidenceVersion, UUID]:
    if "evidence.manage" not in scope.permissions:
        raise _failure(403, "FORBIDDEN", "Permission 'evidence.manage' required")
    membership_id = db.scalar(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.organization_id == scope.organization_id,
            WorkspaceMembership.workspace_id == scope.workspace_id,
            WorkspaceMembership.user_id == scope.user_id,
            WorkspaceMembership.status == "active",
        )
    )
    if membership_id is None:
        raise _failure(403, "FORBIDDEN", "An active workspace membership is required.")
    record = db.scalar(
        select(EvidenceRecord).where(
            EvidenceRecord.id == evidence_id,
            EvidenceRecord.organization_id == scope.organization_id,
            EvidenceRecord.workspace_id == scope.workspace_id,
        )
    )
    if record is None or record.current_version_id is None:
        raise _failure(404, "EVIDENCE_NOT_FOUND", "Evidence record not found.")
    version = db.scalar(
        select(EvidenceVersion).where(
            EvidenceVersion.id == record.current_version_id,
            EvidenceVersion.evidence_record_id == record.id,
            EvidenceVersion.organization_id == scope.organization_id,
            EvidenceVersion.workspace_id == scope.workspace_id,
        )
    )
    if version is None:
        raise _failure(404, "EVIDENCE_NOT_FOUND", "Evidence record not found.")
    return record, version, membership_id


def _append_state_event(
    db: Session,
    scope: TenantScope,
    record: EvidenceRecord,
    version: EvidenceVersion,
    membership_id: UUID,
    *,
    event_type: str,
    old_value: str | None,
    new_value: str | None,
    reason: str | None,
) -> EvidenceStateEvent:
    event = EvidenceStateEvent(
        id=uuid4(),
        organization_id=scope.organization_id,
        workspace_id=scope.workspace_id,
        evidence_record_id=record.id,
        evidence_version_id=version.id,
        actor_membership_id=membership_id,
        event_type=event_type,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event)
    return event


def _commit_audited(
    db: Session,
    scope: TenantScope,
    record: EvidenceRecord,
    membership_id: UUID,
    *,
    action: str,
    metadata: dict[str, str],
) -> None:
    record_event(
        db,
        scope,
        actor_membership_id=membership_id,
        action_key=action,
        target_type="evidence_record",
        target_id=record.id,
        safe_metadata=metadata,
    )
    db.commit()


def transition_evidence(
    db: Session,
    scope: TenantScope,
    evidence_id: UUID,
    *,
    target_state: str,
    reason: str | None = None,
) -> EvidenceRecord:
    """Move Uploaded→Reviewed→Approved, or re-approve the exact revised version."""
    try:
        record, version, membership_id = _context(db, scope, evidence_id)
        clears_gate = False
        if target_state == "Reviewed":
            if record.primary_lifecycle_state != "Uploaded":
                raise _failure(409, "INVALID_EVIDENCE_TRANSITION", "Only Uploaded evidence can be marked Reviewed.")
            old_state = record.primary_lifecycle_state
            record.primary_lifecycle_state = "Reviewed"
            event_type = "lifecycle_transition"
            action = "evidence.reviewed"
            new_state = "Reviewed"
        elif target_state == "Approved":
            if record.primary_lifecycle_state == "Reviewed":
                old_state = "Reviewed"
                record.primary_lifecycle_state = "Approved"
                event_type = "lifecycle_transition"
                action = "evidence.approved"
                new_state = "Approved"
                clears_gate = version.is_pending_reapproval
            elif record.primary_lifecycle_state == "Approved" and version.is_pending_reapproval:
                old_state = "pending_reapproval:true"
                event_type = "version_reapproved"
                action = "evidence.version_reapproved"
                new_state = "pending_reapproval:false"
                clears_gate = False
            else:
                raise _failure(
                    409,
                    "INVALID_EVIDENCE_TRANSITION",
                    "Evidence must be Reviewed, or have a revised current version awaiting re-approval.",
                )
        else:
            raise _failure(422, "INVALID_EVIDENCE_STATE", "The requested evidence state is not supported.")

        _append_state_event(
            db, scope, record, version, membership_id,
            event_type=event_type, old_value=old_state, new_value=new_state, reason=reason,
        )
        if clears_gate:
            _append_state_event(
                db, scope, record, version, membership_id,
                event_type="version_reapproved",
                old_value="pending_reapproval:true",
                new_value="pending_reapproval:false",
                reason=reason,
            )
        record_event(
            db,
            scope,
            actor_membership_id=membership_id,
            action_key=action,
            target_type="evidence_record",
            target_id=record.id,
            safe_metadata={"version_id": str(version.id), "new_state": target_state},
        )
        if clears_gate:
            record_event(
                db, scope,
                actor_membership_id=membership_id,
                action_key="evidence.version_reapproved",
                target_type="evidence_record",
                target_id=record.id,
                safe_metadata={"version_id": str(version.id), "reapproval_gate": "cleared"},
            )
        db.commit()
        db.refresh(record)
        return record
    except Exception:
        db.rollback()
        raise


def set_evidence_inactive(
    db: Session,
    scope: TenantScope,
    evidence_id: UUID,
    *,
    reason: str,
) -> EvidenceRecord:
    """Set the independent Inactive condition; clearing remains product-gated."""
    try:
        record, version, membership_id = _context(db, scope, evidence_id)
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise _failure(422, "REASON_REQUIRED", "A reason is required to mark evidence Inactive.")
        if record.is_inactive:
            raise _failure(409, "ALREADY_INACTIVE", "Evidence is already Inactive.")
        record.is_inactive = True
        _append_state_event(
            db, scope, record, version, membership_id,
            event_type="condition_set", old_value="inactive:false", new_value="inactive:true",
            reason=normalized_reason,
        )
        _commit_audited(
            db, scope, record, membership_id, action="evidence.inactivated",
            metadata={"version_id": str(version.id), "condition": "inactive"},
        )
        db.refresh(record)
        return record
    except Exception:
        db.rollback()
        raise


def revise_evidence_validity(
    db: Session,
    scope: TenantScope,
    evidence_id: UUID,
    *,
    valid_from: date | None,
    valid_until: date | None,
    update_from: bool,
    update_until: bool,
) -> EvidenceVersion:
    """Create an immutable validity revision with an exact-version approval gate."""
    try:
        record, current, membership_id = _context(db, scope, evidence_id)
        if not update_from and not update_until:
            raise _failure(422, "NO_VALIDITY_CHANGE", "Provide at least one validity date to update.")
        next_from = valid_from if update_from else current.valid_from
        next_until = valid_until if update_until else current.valid_until
        if next_from and next_until and next_from > next_until:
            raise _failure(422, "INVALID_VALIDITY_RANGE", "The effective date must not be after the expiry date.")
        if next_from == current.valid_from and next_until == current.valid_until:
            raise _failure(422, "NO_VALIDITY_CHANGE", "The supplied validity dates do not change this version.")
        revised = EvidenceVersion(
            id=uuid4(),
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            evidence_record_id=record.id,
            version_number=current.version_number + 1,
            title=current.title,
            source_reference=current.source_reference,
            private_file_key=current.private_file_key,
            extracted_text=current.extracted_text,
            valid_from=next_from,
            valid_until=next_until,
            owner_snapshot=current.owner_snapshot,
            created_by_membership_id=membership_id,
            pending_reapproval=True,
            checksum=current.checksum,
            created_at=datetime.now(timezone.utc),
        )
        db.add(revised)
        db.flush()
        open_conflicts = db.execute(
            select(EvidenceConflict, EvidenceConflictSource).join(
                EvidenceConflictSource,
                (EvidenceConflictSource.conflict_id == EvidenceConflict.id)
                & (EvidenceConflictSource.organization_id == EvidenceConflict.organization_id)
                & (EvidenceConflictSource.workspace_id == EvidenceConflict.workspace_id),
            ).where(
                EvidenceConflict.state == "open",
                EvidenceConflictSource.evidence_version_id == current.id,
                EvidenceConflictSource.evidence_record_id == record.id,
                EvidenceConflict.organization_id == scope.organization_id,
                EvidenceConflict.workspace_id == scope.workspace_id,
            )
        ).all()
        for conflict, _source in open_conflicts:
            db.add(EvidenceConflictSource(
                organization_id=scope.organization_id,
                workspace_id=scope.workspace_id,
                conflict_id=conflict.id,
                evidence_record_id=record.id,
                evidence_version_id=revised.id,
            ))
        record.current_version_id = revised.id
        _append_state_event(
            db, scope, record, revised, membership_id,
            event_type="validity_version_created",
            old_value=f"{current.valid_from or 'unknown'}..{current.valid_until or 'unknown'}",
            new_value=f"{next_from or 'unknown'}..{next_until or 'unknown'}",
            reason="Validity change requires explicit approval of this exact version.",
        )
        _commit_audited(
            db, scope, record, membership_id, action="evidence.validity_version_created",
            metadata={
                "prior_version_id": str(current.id),
                "version_id": str(revised.id),
                "pending_reapproval": "true",
                "open_conflicts_preserved": str(len(open_conflicts)),
            },
        )
        db.refresh(revised)
        return revised
    except Exception:
        db.rollback()
        raise
