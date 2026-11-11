"""Tenant-scoped report generation and entitlement-aware reads."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_permission
from app.models import Report, ReportEntitlement
from app.modules.reports.schemas import ReportPreview, ReportSnapshot
from app.modules.reports.snapshot import (
    ReportNotEligible,
    ReportNotFound,
    create_report_snapshot,
    project_report_preview,
)
from app.modules.tenancy.schemas import TenantScope

router = APIRouter(tags=["reports"])


class ReportCreatedResponse(BaseModel):
    report_id: UUID
    preview: ReportPreview


class ReportAccessResponse(BaseModel):
    preview: ReportPreview
    is_entitled: bool
    report: ReportSnapshot | None


@router.post(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/submission-versions/{version_id}/analysis-runs/{run_id}/reports",
    response_model=ReportCreatedResponse,
)
def generate_report(
    org_id: UUID,
    workspace_id: UUID,
    version_id: UUID,
    run_id: UUID,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("submission.read.workspace")),
) -> ReportCreatedResponse:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        raise HTTPException(status_code=404, detail="Report source not found.")
    try:
        report = create_report_snapshot(
            db,
            scope,
            submission_version_id=version_id,
            analysis_run_id=run_id,
        )
    except ReportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReportNotEligible as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ReportCreatedResponse(report_id=report.id, preview=project_report_preview(report))


@router.get(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/reports/{report_id}",
    response_model=ReportAccessResponse,
)
def read_report(
    org_id: UUID,
    workspace_id: UUID,
    report_id: UUID,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("submission.read.workspace")),
) -> ReportAccessResponse:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        raise HTTPException(status_code=404, detail="Report not found.")
    report = db.scalar(
        select(Report).where(
            Report.id == report_id,
            Report.organization_id == scope.organization_id,
            Report.workspace_id == scope.workspace_id,
        )
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    entitlement = db.scalar(
        select(ReportEntitlement.id).where(
            ReportEntitlement.report_id == report.id,
            ReportEntitlement.organization_id == scope.organization_id,
            ReportEntitlement.workspace_id == scope.workspace_id,
            ReportEntitlement.purchaser_user_id == scope.user_id,
            ReportEntitlement.status == "active",
        )
    )
    snapshot = ReportSnapshot.model_validate(report.content_snapshot)
    return ReportAccessResponse(
        preview=project_report_preview(report),
        is_entitled=entitlement is not None,
        report=snapshot if entitlement is not None else None,
    )
