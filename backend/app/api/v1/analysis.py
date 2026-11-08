"""Tenant-scoped analysis run and finding read APIs."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_permission
from app.models import AnalysisRun, AnalysisStageResult, Finding, SubmissionVersion
from app.modules.reviews.schemas import HumanDispositionResponse
from app.modules.reviews.services import get_finding_resolutions
from app.modules.tenancy.schemas import TenantScope


router = APIRouter(tags=["analysis"])


class AnalysisStageRead(BaseModel):
    stage_key: str
    state: str
    is_required: bool
    safe_error_code: str | None
    safe_error_message: str | None
    dependency_reason: str | None


class AnalysisRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    submission_version_id: UUID
    run_number: int
    overall_state: str
    started_at: datetime
    completed_at: datetime | None
    stage_results: list[AnalysisStageRead]


class FindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    analysis_run_id: UUID
    submission_version_id: UUID
    claim_id: UUID | None
    category: str
    attention_label: str | None
    explanation: str
    policy_id: UUID | None
    policy_version_id: UUID | None
    evidence_record_id: UUID | None
    evidence_version_id: UUID | None
    is_unresolved: bool
    resolution_status: str
    effective_disposition: str | None
    blocks_clean_approval: bool
    disposition_history: list[HumanDispositionResponse]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Analysis record not found.")


@router.get(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/submission-versions/{version_id}/analysis-runs",
    response_model=list[AnalysisRunRead],
)
def list_analysis_runs(
    org_id: UUID,
    workspace_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("submission.read.workspace")),
) -> list[AnalysisRunRead]:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        raise _not_found()
    version_exists = db.scalar(
        select(SubmissionVersion.id).where(
            SubmissionVersion.id == version_id,
            SubmissionVersion.organization_id == scope.organization_id,
            SubmissionVersion.workspace_id == scope.workspace_id,
        )
    )
    if version_exists is None:
        raise _not_found()
    rows = db.scalars(
        select(AnalysisRun)
        .where(
            AnalysisRun.submission_version_id == version_id,
            AnalysisRun.organization_id == scope.organization_id,
            AnalysisRun.workspace_id == scope.workspace_id,
        )
        .order_by(AnalysisRun.run_number.desc())
    ).all()
    if not rows:
        return []
    stage_rows = db.scalars(
        select(AnalysisStageResult)
        .where(
            AnalysisStageResult.analysis_run_id.in_([row.id for row in rows]),
            AnalysisStageResult.organization_id == scope.organization_id,
            AnalysisStageResult.workspace_id == scope.workspace_id,
        )
        .order_by(AnalysisStageResult.stage_key, AnalysisStageResult.attempt_number)
    ).all()
    stages_by_run: dict[UUID, list[AnalysisStageRead]] = {}
    for stage in stage_rows:
        stages_by_run.setdefault(stage.analysis_run_id, []).append(
            AnalysisStageRead(
                stage_key=stage.stage_key,
                state=stage.state,
                is_required=stage.is_required,
                safe_error_code=stage.safe_error_code,
                safe_error_message=stage.safe_error_message,
                dependency_reason=stage.dependency_reason,
            )
        )
    return [
        AnalysisRunRead(
            id=row.id,
            submission_version_id=row.submission_version_id,
            run_number=row.run_number,
            overall_state=row.overall_state,
            started_at=row.started_at,
            completed_at=row.completed_at,
            stage_results=stages_by_run.get(row.id, []),
        )
        for row in rows
    ]


@router.get(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/analysis-runs/{run_id}/findings",
    response_model=list[FindingRead],
)
def list_analysis_findings(
    org_id: UUID,
    workspace_id: UUID,
    run_id: UUID,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("submission.read.workspace")),
) -> list[FindingRead]:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        raise _not_found()
    run_exists = db.scalar(
        select(AnalysisRun.id).where(
            AnalysisRun.id == run_id,
            AnalysisRun.organization_id == scope.organization_id,
            AnalysisRun.workspace_id == scope.workspace_id,
        )
    )
    if run_exists is None:
        raise _not_found()
    rows = db.scalars(
        select(Finding)
        .where(
            Finding.analysis_run_id == run_id,
            Finding.organization_id == scope.organization_id,
            Finding.workspace_id == scope.workspace_id,
        )
        .order_by(Finding.created_at, Finding.id)
    ).all()
    resolutions = get_finding_resolutions(db, scope, rows)
    return [
        FindingRead(
            id=row.id,
            analysis_run_id=row.analysis_run_id,
            submission_version_id=row.submission_version_id,
            claim_id=row.claim_id,
            category=row.category,
            attention_label=row.attention_label,
            explanation=row.explanation,
            policy_id=row.policy_id,
            policy_version_id=row.policy_version_id,
            evidence_record_id=row.evidence_record_id,
            evidence_version_id=row.evidence_version_id,
            is_unresolved=row.is_unresolved,
            resolution_status=resolutions[row.id]["resolution_status"],
            effective_disposition=resolutions[row.id]["effective_disposition"],
            blocks_clean_approval=resolutions[row.id]["blocks_clean_approval"],
            disposition_history=[
                HumanDispositionResponse.model_validate(item)
                for item in resolutions[row.id]["disposition_history"]
            ],
        )
        for row in rows
    ]
