from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.api.v1.detailed_reports import get_report_storage
from app.core.dependencies import get_db, get_tenant_scope
from app.documents.storage import LocalDocumentStorage
from app.main import app
from app.models import (
    AnalysisRun,
    AnalysisStageResult,
    ReportEntitlement,
    ReportNarrativeArtifact,
)
from app.modules.analysis.orchestrator import REQUIRED_STAGE_ORDER
from app.modules.reports.detailed_schemas import DetailedNarrativeDraft
from app.modules.reports.narrative import DetailedReportGenerationError
from app.modules.reports.payments import (
    PayPalCapture,
    PayPalOrder,
    attach_paypal_order,
    create_pending_payment,
    record_verified_capture_and_grant_entitlement,
)
from app.modules.submissions.services import create_submission_version
from app.modules.tenancy.schemas import TenantScope


def _empty_draft():
    return DetailedNarrativeDraft(
        executive_summary="The saved analysis contains no findings.",
        verification_overview="No findings were persisted for this successful run.",
        claim_analyses=[],
        risk_assessment=[],
        recommendations=[],
    )


@contextmanager
def _client(session_factory, scope, storage):
    previous = app.dependency_overrides.copy()

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_tenant_scope] = lambda: scope
    app.dependency_overrides[get_report_storage] = lambda: storage
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def _scope(tenant, user_id=None):
    return TenantScope(
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        user_id=user_id or tenant.user_id,
        permissions={"submission.read.workspace"},
    )


def _report(session_factory, tenant):
    scope = _scope(tenant)
    with session_factory() as session:
        version = create_submission_version(
            session, scope, submitter_id=tenant.user_id,
            source_type="text", submitted_text="A successful analysis with no claims.",
        )
        now = datetime.now(timezone.utc)
        run = AnalysisRun(
            id=uuid4(), organization_id=tenant.organization_id, workspace_id=tenant.workspace_id,
            submission_version_id=version.id, run_number=1, overall_state="Succeeded",
            started_at=now, completed_at=now, triggered_by_membership_id=tenant.membership_id,
        )
        session.add(run)
        session.flush()
        session.add_all([
            AnalysisStageResult(
                id=uuid4(), organization_id=tenant.organization_id, workspace_id=tenant.workspace_id,
                analysis_run_id=run.id, stage_key=stage, attempt_number=1, state="Succeeded",
                is_required=True, started_at=now, completed_at=now,
            ) for stage in REQUIRED_STAGE_ORDER
        ])
        session.commit()
        from app.modules.reports.snapshot import create_report_snapshot
        report = create_report_snapshot(
            session, scope, submission_version_id=version.id, analysis_run_id=run.id,
        )
        return report.id


def _grant_entitlement(session_factory, tenant, report_id):
    scope = _scope(tenant)
    with session_factory() as session:
        payment = create_pending_payment(
            session, scope, report_id=report_id, idempotency_key=f"detailed-report-{uuid4()}",
        )
        transaction_id = payment.id
        order_id = f"ORDER-{uuid4()}"
        attach_paypal_order(session, scope, transaction_id=transaction_id, order=PayPalOrder(
            order_id, "CREATED", "https://www.sandbox.paypal.com/checkoutnow",
            payment.expected_amount, payment.currency,
        ))
        record_verified_capture_and_grant_entitlement(
            session, scope, transaction_id=transaction_id,
            capture=PayPalCapture(
                order_id=order_id, capture_id=f"CAPTURE-{uuid4()}",
                order_status="COMPLETED", capture_status="COMPLETED",
                amount=payment.expected_amount, currency=payment.currency,
                provider_verified=True, report_reference=str(report_id),
            ),
        )


def _base_path(tenant, report_id):
    return f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/reports/{report_id}/detailed-report"


def test_entitlement_is_required_for_generation_narrative_and_pdf(
    session_factory, tenant_pair, tmp_path, monkeypatch,
):
    tenant, _ = tenant_pair
    report_id = _report(session_factory, tenant)
    calls = []

    def fake_generation(snapshot):
        calls.append(snapshot.report_id)
        return _empty_draft()

    monkeypatch.setattr("app.modules.reports.artifacts.generate_report_narrative", fake_generation)
    storage = LocalDocumentStorage(tmp_path / "private-reports")
    with _client(session_factory, _scope(tenant), storage) as client:
        started = client.post(_base_path(tenant, report_id))
        read = client.get(_base_path(tenant, report_id))
        pdf = client.get(_base_path(tenant, report_id) + "/pdf")

    assert started.status_code == read.status_code == pdf.status_code == 403
    assert calls == []
    with session_factory() as session:
        assert session.scalar(select(func.count(ReportNarrativeArtifact.id)).where(
            ReportNarrativeArtifact.report_id == report_id,
        )) == 0


def test_active_entitlement_generates_once_and_allows_private_pdf_download(
    session_factory, tenant_pair, tmp_path, monkeypatch,
):
    tenant, _ = tenant_pair
    report_id = _report(session_factory, tenant)
    _grant_entitlement(session_factory, tenant, report_id)
    calls = []

    def fake_generation(snapshot):
        calls.append(snapshot.report_id)
        return _empty_draft()

    monkeypatch.setattr("app.modules.reports.artifacts.generate_report_narrative", fake_generation)
    storage = LocalDocumentStorage(tmp_path / "private-reports")
    with _client(session_factory, _scope(tenant), storage) as client:
        first = client.post(_base_path(tenant, report_id))
        second = client.post(_base_path(tenant, report_id))
        read = client.get(_base_path(tenant, report_id))
        pdf = client.get(_base_path(tenant, report_id) + "/pdf")

    assert first.status_code == second.status_code == read.status_code == 200
    assert first.json()["status"] == second.json()["status"] == read.json()["status"] == "completed"
    assert first.json()["detailed_report"] == second.json()["detailed_report"]
    assert calls == [str(report_id)]
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["cache-control"] == "private, no-store"
    assert str(tmp_path) not in pdf.headers.get("content-disposition", "")
    assert pdf.content.startswith(b"%PDF-")
    with session_factory() as session:
        assert session.scalar(select(func.count(ReportNarrativeArtifact.id))) == 1
        assert session.scalar(select(func.count(ReportEntitlement.id)).where(
            ReportEntitlement.report_id == report_id, ReportEntitlement.status == "active",
        )) == 1


def test_failed_generation_exposes_no_pdf_and_can_be_retried_without_duplicate_artifacts(
    session_factory, tenant_pair, tmp_path, monkeypatch,
):
    tenant, _ = tenant_pair
    report_id = _report(session_factory, tenant)
    _grant_entitlement(session_factory, tenant, report_id)
    calls = []

    def fail_once(snapshot):
        calls.append(snapshot.report_id)
        if len(calls) == 1:
            raise DetailedReportGenerationError("provider details must not escape")
        return _empty_draft()

    monkeypatch.setattr("app.modules.reports.artifacts.generate_report_narrative", fail_once)
    storage = LocalDocumentStorage(tmp_path / "private-reports")
    with _client(session_factory, _scope(tenant), storage) as client:
        failed = client.post(_base_path(tenant, report_id))
        hidden_pdf = client.get(_base_path(tenant, report_id) + "/pdf")
        retried = client.post(_base_path(tenant, report_id))
        available_pdf = client.get(_base_path(tenant, report_id) + "/pdf")

    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert "provider details" not in failed.text
    assert hidden_pdf.status_code == 404
    assert retried.status_code == 200 and retried.json()["status"] == "completed"
    assert available_pdf.status_code == 200
    assert calls == [str(report_id), str(report_id)]
    with session_factory() as session:
        artifact = session.scalar(select(ReportNarrativeArtifact).where(ReportNarrativeArtifact.report_id == report_id))
        assert artifact is not None
        assert artifact.status == "completed" and artifact.generation_attempts == 2
        assert session.scalar(select(func.count(ReportNarrativeArtifact.id)).where(
            ReportNarrativeArtifact.report_id == report_id,
        )) == 1


def test_other_tenant_cannot_read_entitled_detailed_report_or_pdf(
    session_factory, tenant_pair, tmp_path, monkeypatch,
):
    tenant, other_tenant = tenant_pair
    report_id = _report(session_factory, tenant)
    _grant_entitlement(session_factory, tenant, report_id)
    monkeypatch.setattr(
        "app.modules.reports.artifacts.generate_report_narrative",
        lambda snapshot: _empty_draft(),
    )
    storage = LocalDocumentStorage(tmp_path / "private-reports")
    with _client(session_factory, _scope(tenant), storage) as client:
        assert client.post(_base_path(tenant, report_id)).status_code == 200
    with _client(session_factory, _scope(other_tenant), storage) as client:
        read = client.get(_base_path(other_tenant, report_id))
        pdf = client.get(_base_path(other_tenant, report_id) + "/pdf")
    assert read.status_code == pdf.status_code == 404


def test_entitlement_is_scoped_to_the_purchasing_user(session_factory, tenant_pair, tmp_path, monkeypatch):
    tenant, _ = tenant_pair
    report_id = _report(session_factory, tenant)
    _grant_entitlement(session_factory, tenant, report_id)
    monkeypatch.setattr(
        "app.modules.reports.artifacts.generate_report_narrative",
        lambda snapshot: _empty_draft(),
    )
    storage = LocalDocumentStorage(tmp_path / "private-reports")
    with _client(session_factory, _scope(tenant), storage) as client:
        assert client.post(_base_path(tenant, report_id)).status_code == 200
    different_user_scope = _scope(tenant, user_id=uuid4())
    with _client(session_factory, different_user_scope, storage) as client:
        response = client.get(_base_path(tenant, report_id))
        pdf = client.get(_base_path(tenant, report_id) + "/pdf")
    assert response.status_code == pdf.status_code == 403
