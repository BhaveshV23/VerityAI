"""Human review decision API."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_permission
from app.models import SubmissionVersion
from app.modules.reviews.schemas import (
    FindingDispositionRecordCreate,
    FindingResolutionResponse,
    HumanDispositionResponse,
    RecordFindingDispositionResponse,
    ReviewDecisionCreate,
    ReviewDecisionResponse,
    ReviewEligibilityResponse,
)
from app.modules.reviews.services import (
    get_finding_resolution,
    get_review_eligibility,
    record_finding_disposition,
    record_review_decision,
)
from app.modules.tenancy.schemas import TenantScope


router = APIRouter(tags=["reviews"])


@router.post(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/findings/{finding_id}/dispositions",
    response_model=RecordFindingDispositionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_finding_disposition(
    org_id: UUID,
    workspace_id: UUID,
    finding_id: UUID,
    payload: FindingDispositionRecordCreate,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("review.decide")),
) -> RecordFindingDispositionResponse:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        raise HTTPException(status_code=404, detail="Finding not found.")
    disposition = record_finding_disposition(db, scope, finding_id, payload)
    from app.models import Finding

    finding = db.scalar(
        select(Finding).where(
            Finding.id == finding_id,
            Finding.analysis_run_id == payload.analysis_run_id,
            Finding.submission_version_id == payload.submission_version_id,
            Finding.organization_id == scope.organization_id,
            Finding.workspace_id == scope.workspace_id,
        )
    )
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found.")
    return RecordFindingDispositionResponse(
        disposition=HumanDispositionResponse.model_validate(disposition),
        finding_resolution=FindingResolutionResponse(**get_finding_resolution(db, scope, finding)),
    )


@router.get(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/submission-versions/{version_id}/review-eligibility",
    response_model=ReviewEligibilityResponse,
)
def read_review_eligibility(
    org_id: UUID,
    workspace_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("submission.read.workspace")),
) -> ReviewEligibilityResponse:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        raise HTTPException(status_code=404, detail="Submission version not found.")
    submission_version = db.scalar(
        select(SubmissionVersion).where(
            SubmissionVersion.id == version_id,
            SubmissionVersion.organization_id == scope.organization_id,
            SubmissionVersion.workspace_id == scope.workspace_id,
        )
    )
    if submission_version is None:
        raise HTTPException(status_code=404, detail="Submission version not found.")
    return ReviewEligibilityResponse(**get_review_eligibility(db, scope, submission_version))


@router.post(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/submission-versions/{version_id}/review-decisions",
    response_model=ReviewDecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_review_decision(
    org_id: UUID,
    workspace_id: UUID,
    version_id: UUID,
    payload: ReviewDecisionCreate,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("review.decide")),
) -> ReviewDecisionResponse:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        raise HTTPException(status_code=403, detail="Tenant scope does not match the requested workspace.")
    submission_version = db.scalar(
        select(SubmissionVersion).where(
            SubmissionVersion.id == version_id,
            SubmissionVersion.organization_id == scope.organization_id,
            SubmissionVersion.workspace_id == scope.workspace_id,
        )
    )
    if submission_version is None:
        raise HTTPException(status_code=404, detail="Submission version not found.")
    decision = record_review_decision(db, scope, submission_version, payload)
    return ReviewDecisionResponse.model_validate(decision)
