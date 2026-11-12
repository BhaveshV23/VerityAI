"""Tenant- and entitlement-scoped detailed report and PDF endpoints."""

from collections.abc import Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_permission
from app.documents.storage import LocalDocumentStorage
from app.models import Report, ReportEntitlement
from app.modules.reports.artifacts import (
    generate_or_retrieve_detailed_report,
    read_detailed_report_pdf,
    read_detailed_report_status,
    report_pdf_storage,
)
from app.modules.reports.detailed_schemas import DetailedReportStatusResponse
from app.modules.reports.narrative import DetailedReportGenerationError
from app.modules.tenancy.schemas import TenantScope


router = APIRouter(tags=["detailed reports"])


def get_report_storage() -> Iterator[LocalDocumentStorage]:
    yield report_pdf_storage()


def _authorized_report(
    db: Session, scope: TenantScope, org_id: UUID, workspace_id: UUID, report_id: UUID,
) -> Report:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        raise HTTPException(status_code=404, detail="Report not found.")
    report = db.scalar(select(Report).where(
        Report.id == report_id,
        Report.organization_id == scope.organization_id,
        Report.workspace_id == scope.workspace_id,
    ))
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    entitlement_id = db.scalar(select(ReportEntitlement.id).where(
        ReportEntitlement.report_id == report.id,
        ReportEntitlement.organization_id == scope.organization_id,
        ReportEntitlement.workspace_id == scope.workspace_id,
        ReportEntitlement.purchaser_user_id == scope.user_id,
        ReportEntitlement.status == "active",
    ))
    if entitlement_id is None:
        raise HTTPException(status_code=403, detail="An active report entitlement is required.")
    return report


@router.post(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/reports/{report_id}/detailed-report",
    response_model=DetailedReportStatusResponse,
)
def start_detailed_report(
    org_id: UUID,
    workspace_id: UUID,
    report_id: UUID,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("submission.read.workspace")),
    storage: LocalDocumentStorage = Depends(get_report_storage),
) -> DetailedReportStatusResponse:
    report = _authorized_report(db, scope, org_id, workspace_id, report_id)
    try:
        return generate_or_retrieve_detailed_report(db, scope, report, storage)
    except DetailedReportGenerationError as exc:
        raise HTTPException(status_code=409, detail="The saved verification snapshot could not be used.") from exc


@router.get(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/reports/{report_id}/detailed-report",
    response_model=DetailedReportStatusResponse,
)
def read_detailed_report(
    org_id: UUID,
    workspace_id: UUID,
    report_id: UUID,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("submission.read.workspace")),
) -> DetailedReportStatusResponse:
    report = _authorized_report(db, scope, org_id, workspace_id, report_id)
    try:
        return read_detailed_report_status(db, scope, report)
    except (DetailedReportGenerationError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="The detailed report is temporarily unavailable.") from exc


@router.get(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/reports/{report_id}/detailed-report/pdf",
)
def download_detailed_report_pdf(
    org_id: UUID,
    workspace_id: UUID,
    report_id: UUID,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("submission.read.workspace")),
    storage: LocalDocumentStorage = Depends(get_report_storage),
) -> Response:
    report = _authorized_report(db, scope, org_id, workspace_id, report_id)
    try:
        content = read_detailed_report_pdf(db, scope, report, storage)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="The detailed report PDF is not available.") from exc
    except (DetailedReportGenerationError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="The detailed report PDF is temporarily unavailable.") from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="verityai-detailed-report.pdf"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
