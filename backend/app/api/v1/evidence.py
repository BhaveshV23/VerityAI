"""Tenant-scoped evidence upload and repository endpoints."""

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_permission
from app.documents.config import DocumentSettings
from app.documents.errors import DocumentInputError, DocumentProcessingError
from app.models import EvidenceConflict, EvidenceConflictSource, EvidenceRecord, EvidenceStateEvent, EvidenceVersion
from app.modules.evidence.ingestion import list_evidence, upload_evidence
from app.modules.evidence.lifecycle import revise_evidence_validity, set_evidence_inactive, transition_evidence
from app.modules.evidence.services import derive_evidence_eligibility
from app.modules.tenancy.schemas import TenantScope


router = APIRouter(tags=["evidence"])


class EvidenceItem(BaseModel):
    id: UUID
    version_id: UUID | None
    title: str | None
    primary_lifecycle_state: str
    is_inactive: bool
    valid_from: date | None
    valid_until: date | None
    freshness_unknown: bool
    is_expired: bool = False
    not_yet_valid: bool = False
    is_eligible: bool = False
    eligibility_reasons: list[str] = Field(default_factory=list)
    created_at: str
    version_created_at: str | None = None
    version_number: int | None = None
    is_current_version: bool = False
    pending_reapproval: bool = False
    has_open_manual_conflict: bool = False
    available_actions: list[str] = Field(default_factory=list)


class EvidenceEventItem(BaseModel):
    id: UUID
    version_id: UUID | None
    event_type: str
    old_value: str | None
    new_value: str | None
    reason: str | None
    actor_membership_id: UUID
    occurred_at: str


class EvidenceConflictItem(BaseModel):
    id: UUID
    state: str
    version_ids: list[UUID]
    rationale: str | None
    resolution_rationale: str | None
    created_at: str
    resolved_at: str | None


class EvidenceHistoryResult(BaseModel):
    evidence: EvidenceItem
    versions: list[EvidenceItem]
    lifecycle_events: list[EvidenceEventItem]
    conflicts: list[EvidenceConflictItem]


class EvidenceTransitionRequest(BaseModel):
    reason: str | None = None


class EvidenceValidityUpdate(BaseModel):
    valid_from: date | None = None
    valid_until: date | None = None


class EvidenceInactiveRequest(BaseModel):
    reason: str


class EvidenceUploadResult(EvidenceItem):
    extracted_text: str


def _item(
    record: EvidenceRecord,
    version: EvidenceVersion | None,
    scope: TenantScope | None = None,
) -> EvidenceItem:
    is_current_version = version is not None and version.id == record.current_version_id
    eligibility = derive_evidence_eligibility(record, version, datetime.now(timezone.utc)) if version else None
    reasons = _eligibility_reasons(record, version, eligibility)
    if version is not None and not is_current_version:
        reasons.append("Superseded versions are retained for history and excluded from new analyses.")
    can_manage = bool(scope and "evidence.manage" in scope.permissions)
    actions: list[str] = []
    if can_manage and version is not None:
        if record.primary_lifecycle_state == "Uploaded":
            actions.append("review")
        if record.primary_lifecycle_state == "Reviewed" or (
            record.primary_lifecycle_state == "Approved" and version.is_pending_reapproval
        ):
            actions.append("approve")
        if not record.is_inactive:
            actions.append("mark_inactive")
        actions.append("update_validity")
    return EvidenceItem(
        id=record.id,
        version_id=version.id if version else None,
        title=version.title if version else None,
        primary_lifecycle_state=record.primary_lifecycle_state,
        is_inactive=record.is_inactive,
        valid_from=version.valid_from if version else None,
        valid_until=version.valid_until if version else None,
        freshness_unknown=version is None or version.valid_from is None or version.valid_until is None,
        is_expired=bool(eligibility and eligibility["is_expired"]),
        not_yet_valid=bool(eligibility and eligibility["not_yet_valid"]),
        is_eligible=bool(eligibility and eligibility["is_eligible"] and is_current_version),
        eligibility_reasons=reasons,
        created_at=record.created_at.isoformat(),
        version_created_at=version.created_at.isoformat() if version else None,
        version_number=version.version_number if version else None,
        is_current_version=is_current_version,
        pending_reapproval=version.is_pending_reapproval if version else False,
        has_open_manual_conflict=version.has_open_manual_conflict if version else False,
        available_actions=actions,
    )


def _eligibility_reasons(
    record: EvidenceRecord,
    version: EvidenceVersion | None,
    eligibility: dict[str, Any] | None,
) -> list[str]:
    if version is None or eligibility is None:
        return ["No evidence version is available."]
    reasons: list[str] = []
    if record.primary_lifecycle_state != "Approved":
        reasons.append(f"Primary lifecycle state is {record.primary_lifecycle_state}; evidence must be Approved.")
    if record.is_inactive:
        reasons.append("Evidence is Inactive.")
    if eligibility["is_expired"]:
        reasons.append("The supplied validity end date has passed.")
    if eligibility["not_yet_valid"]:
        reasons.append("The supplied effective date is in the future.")
    if version.is_pending_reapproval:
        reasons.append("This exact version requires explicit re-approval.")
    if version.has_open_manual_conflict:
        reasons.append("An unresolved manual conflict is linked to this version.")
    return reasons


def _check_route_scope(org_id: UUID, workspace_id: UUID, scope: TenantScope) -> None:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        raise HTTPException(status_code=404, detail="Workspace not found.")


@router.post(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/evidence",
    response_model=EvidenceUploadResult,
    status_code=status.HTTP_201_CREATED,
)
async def create_evidence(
    org_id: UUID,
    workspace_id: UUID,
    file: UploadFile = File(...),
    title: str = Form(...),
    valid_from: date | None = Form(default=None),
    valid_until: date | None = Form(default=None),
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("evidence.manage")),
) -> EvidenceUploadResult:
    _check_route_scope(org_id, workspace_id, scope)
    try:
        settings = DocumentSettings.from_environment()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Evidence storage is not configured.") from exc
    try:
        content = bytearray()
        while block := await file.read(64 * 1024):
            content.extend(block)
            if len(content) > settings.max_upload_bytes:
                raise DocumentInputError("file_too_large", "The document exceeds the configured upload size limit.", 413)
        record, version = upload_evidence(
            db,
            scope,
            filename=file.filename,
            content=bytes(content),
            title=title,
            valid_from=valid_from,
            valid_until=valid_until,
            settings=settings,
        )
    except DocumentInputError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    except DocumentProcessingError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
    finally:
        await file.close()
    item = _item(record, version, scope)
    return EvidenceUploadResult(**item.model_dump(), extracted_text=version.extracted_text or "")


@router.get(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/evidence",
    response_model=list[EvidenceItem],
)
def read_evidence(
    org_id: UUID,
    workspace_id: UUID,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("evidence.read.workspace")),
) -> list[EvidenceItem]:
    _check_route_scope(org_id, workspace_id, scope)
    return [_item(record, version, scope) for record, version in list_evidence(db, scope)]


@router.get(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/evidence/{evidence_id}",
    response_model=EvidenceHistoryResult,
)
def read_evidence_history(
    org_id: UUID,
    workspace_id: UUID,
    evidence_id: UUID,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("evidence.read.workspace")),
) -> EvidenceHistoryResult:
    _check_route_scope(org_id, workspace_id, scope)
    record = db.scalar(
        select(EvidenceRecord).where(
            EvidenceRecord.id == evidence_id,
            EvidenceRecord.organization_id == scope.organization_id,
            EvidenceRecord.workspace_id == scope.workspace_id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Evidence not found.")
    versions = list(db.scalars(select(EvidenceVersion).where(
        EvidenceVersion.evidence_record_id == evidence_id,
        EvidenceVersion.organization_id == scope.organization_id,
        EvidenceVersion.workspace_id == scope.workspace_id,
    ).order_by(EvidenceVersion.version_number.desc())))
    current = next((version for version in versions if version.id == record.current_version_id), None)
    events = list(db.scalars(select(EvidenceStateEvent).where(
        EvidenceStateEvent.evidence_record_id == evidence_id,
        EvidenceStateEvent.organization_id == scope.organization_id,
        EvidenceStateEvent.workspace_id == scope.workspace_id,
    ).order_by(EvidenceStateEvent.occurred_at.desc(), EvidenceStateEvent.id)))
    conflict_rows = db.execute(
        select(EvidenceConflict, EvidenceConflictSource.evidence_version_id)
        .join(EvidenceConflictSource, EvidenceConflictSource.conflict_id == EvidenceConflict.id)
        .where(
            EvidenceConflict.organization_id == scope.organization_id,
            EvidenceConflict.workspace_id == scope.workspace_id,
            EvidenceConflictSource.evidence_record_id == evidence_id,
            EvidenceConflictSource.organization_id == scope.organization_id,
            EvidenceConflictSource.workspace_id == scope.workspace_id,
        )
        .order_by(EvidenceConflict.created_at.desc(), EvidenceConflict.id)
    ).all()
    conflicts_by_id: dict[UUID, dict] = {}
    for conflict, conflict_version_id in conflict_rows:
        item = conflicts_by_id.setdefault(conflict.id, {
            "id": conflict.id,
            "state": conflict.state,
            "version_ids": [],
            "rationale": conflict.rationale,
            "resolution_rationale": conflict.resolution_rationale,
            "created_at": conflict.created_at.isoformat(),
            "resolved_at": conflict.resolved_at.isoformat() if conflict.resolved_at else None,
        })
        item["version_ids"].append(conflict_version_id)
    return EvidenceHistoryResult(
        evidence=_item(record, current, scope),
        versions=[_item(record, version) for version in versions],
        lifecycle_events=[EvidenceEventItem(
            id=event.id,
            version_id=event.evidence_version_id,
            event_type=event.event_type,
            old_value=event.old_value,
            new_value=event.new_value,
            reason=event.reason,
            actor_membership_id=event.actor_membership_id,
            occurred_at=event.occurred_at.isoformat(),
        ) for event in events],
        conflicts=[EvidenceConflictItem(**item) for item in conflicts_by_id.values()],
    )


@router.post(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/evidence/{evidence_id}/review",
    response_model=EvidenceItem,
)
def review_evidence(
    org_id: UUID,
    workspace_id: UUID,
    evidence_id: UUID,
    payload: EvidenceTransitionRequest,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("evidence.manage")),
) -> EvidenceItem:
    _check_route_scope(org_id, workspace_id, scope)
    record = transition_evidence(db, scope, evidence_id, target_state="Reviewed", reason=payload.reason)
    version = db.get(EvidenceVersion, record.current_version_id)
    return _item(record, version, scope)


@router.post(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/evidence/{evidence_id}/approve",
    response_model=EvidenceItem,
)
def approve_evidence(
    org_id: UUID,
    workspace_id: UUID,
    evidence_id: UUID,
    payload: EvidenceTransitionRequest,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("evidence.manage")),
) -> EvidenceItem:
    _check_route_scope(org_id, workspace_id, scope)
    record = transition_evidence(db, scope, evidence_id, target_state="Approved", reason=payload.reason)
    version = db.get(EvidenceVersion, record.current_version_id)
    return _item(record, version, scope)


@router.post(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/evidence/{evidence_id}/validity",
    response_model=EvidenceItem,
)
def update_evidence_validity(
    org_id: UUID,
    workspace_id: UUID,
    evidence_id: UUID,
    payload: EvidenceValidityUpdate,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("evidence.manage")),
) -> EvidenceItem:
    _check_route_scope(org_id, workspace_id, scope)
    version = revise_evidence_validity(
        db, scope, evidence_id,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        update_from="valid_from" in payload.model_fields_set,
        update_until="valid_until" in payload.model_fields_set,
    )
    record = db.get(EvidenceRecord, evidence_id)
    assert record is not None
    return _item(record, version, scope)


@router.post(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/evidence/{evidence_id}/inactive",
    response_model=EvidenceItem,
)
def mark_evidence_inactive(
    org_id: UUID,
    workspace_id: UUID,
    evidence_id: UUID,
    payload: EvidenceInactiveRequest,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("evidence.manage")),
) -> EvidenceItem:
    _check_route_scope(org_id, workspace_id, scope)
    record = set_evidence_inactive(db, scope, evidence_id, reason=payload.reason)
    version = db.get(EvidenceVersion, record.current_version_id)
    return _item(record, version, scope)
