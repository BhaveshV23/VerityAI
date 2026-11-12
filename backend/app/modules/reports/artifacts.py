"""Entitlement-gated, idempotent detailed report generation and private storage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.documents.storage import LocalDocumentStorage
from app.models import Organization, Report, ReportNarrativeArtifact, SubmissionVersion, Workspace
from app.modules.reports.detailed_report import (
    ReportContext,
    compose_detailed_report,
    validate_detailed_report_against_snapshot,
)
from app.modules.reports.detailed_schemas import DetailedNarrativeDraft, DetailedReport, DetailedReportStatusResponse
from app.modules.reports.narrative import (
    DetailedReportGenerationError,
    gemini_failure_diagnostics,
    generate_report_narrative,
)
from app.modules.reports.pdf import build_detailed_report_pdf
from app.modules.reports.schemas import ReportSnapshot
from app.modules.tenancy.schemas import TenantScope


SAFE_GENERATION_ERROR = "Detailed report generation failed. Please retry."
STALE_GENERATION_AFTER = timedelta(minutes=5)
logger = logging.getLogger(__name__)


def report_pdf_storage() -> LocalDocumentStorage:
    """Use the existing private local document store under its own subdirectory."""
    root = Path(os.getenv("DOCUMENT_STORAGE_PATH", "var/knowledge-documents")).expanduser()
    return LocalDocumentStorage(root / "reports")


def _snapshot(report: Report) -> ReportSnapshot:
    snapshot = ReportSnapshot.model_validate(report.content_snapshot)
    if snapshot.report_id != str(report.id) or snapshot.report_version != report.report_version:
        raise DetailedReportGenerationError("The saved report snapshot could not be verified.")
    return snapshot


def _artifact_query(db: Session, scope: TenantScope, report: Report, *, lock: bool = False):
    query = select(ReportNarrativeArtifact).where(
        ReportNarrativeArtifact.report_id == report.id,
        ReportNarrativeArtifact.organization_id == scope.organization_id,
        ReportNarrativeArtifact.workspace_id == scope.workspace_id,
    )
    return db.scalar(query.with_for_update() if lock else query)


def _status_response(
    report: Report,
    artifact: ReportNarrativeArtifact | None,
    snapshot: ReportSnapshot,
) -> DetailedReportStatusResponse:
    if artifact is None:
        return DetailedReportStatusResponse(
            report_id=str(report.id), report_version=report.report_version, status="not_started",
        )
    if artifact.report_version != report.report_version:
        raise DetailedReportGenerationError("The detailed report is not bound to this report snapshot.")
    if artifact.status == "completed":
        if artifact.content is None or not artifact.pdf_storage_key or artifact.generated_at is None:
            raise DetailedReportGenerationError("The completed report artifact is incomplete.")
        detailed = DetailedReport.model_validate(artifact.content)
        validate_detailed_report_against_snapshot(detailed, snapshot)
        if detailed.report_id != str(report.id):
            raise DetailedReportGenerationError("The detailed report is not bound to this report snapshot.")
        return DetailedReportStatusResponse(
            report_id=str(report.id), report_version=report.report_version,
            status="completed", detailed_report=detailed,
        )
    if artifact.status == "failed":
        return DetailedReportStatusResponse(
            report_id=str(report.id), report_version=report.report_version,
            status="failed", error=SAFE_GENERATION_ERROR, retryable=True,
        )
    return DetailedReportStatusResponse(
        report_id=str(report.id), report_version=report.report_version, status=artifact.status,
        retryable=False,
    )


def read_detailed_report_status(
    db: Session, scope: TenantScope, report: Report,
) -> DetailedReportStatusResponse:
    snapshot = _snapshot(report)
    return _status_response(report, _artifact_query(db, scope, report), snapshot)


def _report_context(db: Session, report: Report) -> ReportContext:
    organization = db.scalar(select(Organization).where(Organization.id == report.organization_id))
    workspace = db.scalar(select(Workspace).where(
        Workspace.id == report.workspace_id,
        Workspace.organization_id == report.organization_id,
    ))
    version = db.scalar(select(SubmissionVersion).where(
        SubmissionVersion.id == report.submission_version_id,
        SubmissionVersion.organization_id == report.organization_id,
        SubmissionVersion.workspace_id == report.workspace_id,
    ))
    if organization is None or workspace is None or version is None:
        raise DetailedReportGenerationError("The report context could not be verified.")
    return ReportContext(
        organization_name=organization.name,
        workspace_name=workspace.name,
        submission_id=str(version.submission_id),
    )


def _claim_generation(db: Session, scope: TenantScope, report: Report) -> tuple[ReportNarrativeArtifact, bool]:
    artifact = _artifact_query(db, scope, report, lock=True)
    now = datetime.now(timezone.utc)
    if artifact is None:
        artifact = ReportNarrativeArtifact(
            report_id=report.id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            report_version=report.report_version,
            status="generating",
            generation_attempts=1,
            updated_at=now,
        )
        try:
            db.add(artifact)
            db.commit()
            return artifact, True
        except IntegrityError:
            db.rollback()
            artifact = _artifact_query(db, scope, report, lock=True)
            if artifact is None:
                raise
            return artifact, False

    if artifact.report_version != report.report_version:
        raise DetailedReportGenerationError("The detailed report is not bound to this report snapshot.")
    if artifact.status == "completed":
        return artifact, False
    stale = (
        artifact.status == "generating"
        and artifact.updated_at is not None
        and artifact.updated_at < now - STALE_GENERATION_AFTER
    )
    if artifact.status == "generating" and not stale:
        return artifact, False
    if artifact.status not in {"pending", "failed", "generating"}:
        raise DetailedReportGenerationError("The report generation state is invalid.")
    artifact.status = "generating"
    artifact.content = None
    artifact.pdf_storage_key = None
    artifact.generation_error = None
    artifact.generation_attempts += 1
    artifact.updated_at = now
    db.commit()
    return artifact, True


def _mark_failed(db: Session, artifact_id: UUID, storage: LocalDocumentStorage, saved_key: str | None) -> None:
    if saved_key:
        try:
            storage.delete(saved_key)
        except OSError:
            # Keep the artifact inaccessible even if private-file cleanup fails.
            pass
    db.rollback()
    artifact = db.get(ReportNarrativeArtifact, artifact_id)
    if artifact is None:
        return
    artifact.status = "failed"
    artifact.content = None
    artifact.pdf_storage_key = None
    artifact.generated_at = None
    artifact.generation_error = SAFE_GENERATION_ERROR
    artifact.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except Exception:
        db.rollback()


def generate_or_retrieve_detailed_report(
    db: Session,
    scope: TenantScope,
    report: Report,
    storage: LocalDocumentStorage,
) -> DetailedReportStatusResponse:
    """Create once per report snapshot; retry only when the stored attempt failed."""
    snapshot = _snapshot(report)
    artifact, claimed = _claim_generation(db, scope, report)
    if not claimed:
        return _status_response(report, artifact, snapshot)

    saved_key: str | None = None
    generation_stage = "gemini"
    try:
        draft: DetailedNarrativeDraft = generate_report_narrative(snapshot)
        generation_stage = "composition"
        detailed = compose_detailed_report(snapshot, draft, _report_context(db, report))
        generation_stage = "pdf"
        pdf_content = build_detailed_report_pdf(detailed)
        saved_key = storage.save(pdf_content, ".pdf")
        generation_stage = "persistence"
        artifact.content = detailed.model_dump(mode="json")
        artifact.pdf_storage_key = saved_key
        artifact.status = "completed"
        artifact.generation_error = None
        artifact.generated_at = detailed.generated_at
        artifact.updated_at = datetime.now(timezone.utc)
        db.commit()
        validate_detailed_report_against_snapshot(detailed, snapshot)
        return DetailedReportStatusResponse(
            report_id=str(report.id), report_version=report.report_version,
            status="completed", detailed_report=detailed,
        )
    except Exception as exc:
        provider_error = exc.__cause__ or exc
        diagnostics = gemini_failure_diagnostics(provider_error)
        logger.error(
            "Detailed report generation failed "
            "(stage=%s, exception_class=%s, cause_class=%s, http_status=%s, "
            "provider_status=%s, provider_error_type=%s, retryable=%s).",
            generation_stage,
            type(exc).__name__,
            type(exc.__cause__).__name__ if exc.__cause__ is not None else "none",
            diagnostics.http_status,
            diagnostics.provider_status,
            diagnostics.provider_error_type,
            diagnostics.retryable,
        )
        artifact_id = artifact.id
        _mark_failed(db, artifact_id, storage, saved_key)
        return DetailedReportStatusResponse(
            report_id=str(report.id), report_version=report.report_version,
            status="failed", error=SAFE_GENERATION_ERROR, retryable=True,
        )


def read_detailed_report_pdf(
    db: Session,
    scope: TenantScope,
    report: Report,
    storage: LocalDocumentStorage,
) -> bytes:
    snapshot = _snapshot(report)
    artifact = _artifact_query(db, scope, report)
    response = _status_response(report, artifact, snapshot)
    if response.status != "completed" or artifact is None or not artifact.pdf_storage_key:
        raise FileNotFoundError("The detailed report PDF is not available.")
    try:
        return storage.read(artifact.pdf_storage_key)
    except (OSError, ValueError) as exc:
        raise FileNotFoundError("The detailed report PDF is not available.") from exc
