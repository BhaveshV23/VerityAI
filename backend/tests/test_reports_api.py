from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.core.dependencies import get_db, get_tenant_scope
from app.api.v1.report_payments import get_paypal_gateway
from app.main import app
from app.models import (
    AnalysisRun,
    AnalysisStageResult,
    Report,
    ReportEntitlement,
    PaymentTransaction,
    User,
    WorkspaceMembership,
)
from app.modules.analysis.orchestrator import REQUIRED_STAGE_ORDER
from app.modules.reports.payments import (
    PayPalCapture,
    PayPalOrder,
    attach_paypal_order,
    create_pending_payment,
    record_verified_capture_and_grant_entitlement,
)
from app.modules.reports.paypal import PayPalProviderError
from app.modules.submissions.services import create_submission_version
from app.modules.tenancy.schemas import TenantScope


def _scope(tenant, *, user_id=None):
    return TenantScope(
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        user_id=user_id or tenant.user_id,
        permissions={"submission.read.workspace"},
    )


@contextmanager
def _authenticated_client(session_factory, scope, paypal_gateway=None):
    previous_overrides = app.dependency_overrides.copy()

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_tenant_scope] = lambda: scope
    if paypal_gateway is not None:
        app.dependency_overrides[get_paypal_gateway] = lambda: paypal_gateway
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def _create_analysis(session, tenant, *, run_state="Succeeded", failed_stage=None):
    scope = _scope(tenant)
    version = create_submission_version(
        session,
        scope,
        submitter_id=tenant.user_id,
        source_type="text",
        submitted_text="A synthetic analysis input for report API coverage.",
    )
    now = datetime.now(timezone.utc)
    run = AnalysisRun(
        id=uuid4(),
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        submission_version_id=version.id,
        run_number=1,
        overall_state=run_state,
        started_at=now,
        completed_at=now,
        triggered_by_membership_id=tenant.membership_id,
    )
    session.add(run)
    session.flush()
    session.add_all([
        AnalysisStageResult(
            id=uuid4(),
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            analysis_run_id=run.id,
            stage_key=stage_key,
            attempt_number=1,
            state="Failed" if stage_key == failed_stage else "Succeeded",
            is_required=True,
            started_at=now,
            completed_at=now,
        )
        for stage_key in REQUIRED_STAGE_ORDER
    ])
    session.flush()
    session.commit()
    return version.id, run.id


def _paths(tenant, *, version_id=None, run_id=None, report_id=None):
    base = f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}"
    if report_id is not None:
        return f"{base}/reports/{report_id}"
    return f"{base}/submission-versions/{version_id}/analysis-runs/{run_id}/reports"


def _create_report(client, tenant, version_id, run_id):
    return client.post(_paths(tenant, version_id=version_id, run_id=run_id))


def _grant_entitlement(session_factory, tenant, report_id):
    with session_factory() as session:
        payment = create_pending_payment(
            session,
            _scope(tenant),
            report_id=report_id,
            idempotency_key=f"report-api-{uuid4()}",
        )
        transaction_id = payment.id
        order_id = f"ORDER-{uuid4()}"
        order = PayPalOrder(
            order_id,
            "CREATED",
            "https://www.sandbox.paypal.com/checkoutnow",
            payment.expected_amount,
            payment.currency,
        )
        attach_paypal_order(session, _scope(tenant), transaction_id=transaction_id, order=order)
        entitlement = record_verified_capture_and_grant_entitlement(
            session,
            _scope(tenant),
            transaction_id=transaction_id,
            capture=PayPalCapture(
                order_id=order_id,
                capture_id=f"CAPTURE-{uuid4()}",
                order_status="COMPLETED",
                capture_status="COMPLETED",
                amount=payment.expected_amount,
                currency=payment.currency,
                provider_verified=True,
                report_reference=str(report_id),
            ),
        )
        return entitlement.id


def _add_member(session_factory, tenant):
    user_id = uuid4()
    membership_id = uuid4()
    with session_factory() as session:
        session.add(User(id=user_id, display_name="Second report reader"))
        session.flush()
        session.add(WorkspaceMembership(
            id=membership_id,
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            user_id=user_id,
            status="active",
        ))
        session.commit()
    return user_id


def test_report_api_creates_and_reuses_snapshot_for_exact_analysis(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        version_id, run_id = _create_analysis(session, tenant)

    with _authenticated_client(session_factory, _scope(tenant)) as client:
        first = _create_report(client, tenant, version_id, run_id)
        second = _create_report(client, tenant, version_id, run_id)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["report_id"] == second.json()["report_id"]
    assert first.json()["preview"]["is_limited_preview"] is True
    assert "findings" not in first.json()["preview"]

    report_id = first.json()["report_id"]
    with session_factory() as session:
        report = session.get(Report, UUID(report_id))
        report_count = session.scalar(select(func.count(Report.id)).where(
            Report.submission_version_id == version_id,
            Report.analysis_run_id == run_id,
        ))
        assert report is not None
        assert report.submission_version_id == version_id
        assert report.analysis_run_id == run_id
        assert report.content_snapshot["submission_version_id"] == str(version_id)
        assert report.content_snapshot["analysis_run_id"] == str(run_id)
        assert report_count == 1


@pytest.mark.parametrize(
    ("run_state", "failed_stage"),
    [("Incomplete", None), ("Succeeded", "policy_evaluation")],
    ids=["incomplete-run", "failed-required-stage"],
)
def test_report_api_rejects_incomplete_or_failed_analysis(
    session_factory, tenant_pair, run_state, failed_stage
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        version_id, run_id = _create_analysis(
            session,
            tenant,
            run_state=run_state,
            failed_stage=failed_stage,
        )

    with _authenticated_client(session_factory, _scope(tenant)) as client:
        response = _create_report(client, tenant, version_id, run_id)

    assert response.status_code == 409
    with session_factory() as session:
        assert session.scalar(select(func.count(Report.id)).where(
            Report.submission_version_id == version_id,
            Report.analysis_run_id == run_id,
        )) == 0


def test_failed_paypal_order_creation_never_marks_payment_paid_or_grants_entitlement(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        version_id, run_id = _create_analysis(session, tenant)
    with _authenticated_client(session_factory, _scope(tenant)) as client:
        report_response = _create_report(client, tenant, version_id, run_id)
    assert report_response.status_code == 200
    report_id = report_response.json()["report_id"]

    class FailingGateway:
        def create_order(self, **kwargs):
            raise PayPalProviderError("PayPal rejected the request (HTTP 422).")

        def capture_order(self, **kwargs):
            raise AssertionError("Capture must not run after order creation failed")

    with _authenticated_client(session_factory, _scope(tenant), FailingGateway()) as client:
        response = client.post(
            f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/reports/{report_id}/payments",
            headers={"Idempotency-Key": f"failed-order-{uuid4()}"},
            json={"return_url": "https://verity.example/return", "cancel_url": "https://verity.example/cancel"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "PayPal rejected the request (HTTP 422)."
    with session_factory() as session:
        payment = session.scalar(select(PaymentTransaction).where(PaymentTransaction.report_id == UUID(report_id)))
        assert payment is not None
        assert payment.status == "pending"
        assert payment.paypal_order_id is None
        assert session.scalar(select(func.count(ReportEntitlement.id)).where(
            ReportEntitlement.report_id == UUID(report_id),
        )) == 0


def test_report_read_without_entitlement_returns_only_limited_preview(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        version_id, run_id = _create_analysis(session, tenant)
    with _authenticated_client(session_factory, _scope(tenant)) as client:
        created = _create_report(client, tenant, version_id, run_id)
        report_id = created.json()["report_id"]
        response = client.get(_paths(tenant, report_id=report_id))

    assert created.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_entitled"] is False
    assert payload["report"] is None
    assert payload["preview"]["is_limited_preview"] is True
    assert "findings" not in payload["preview"]


def test_report_read_with_active_user_entitlement_returns_full_snapshot(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        version_id, run_id = _create_analysis(session, tenant)
    with _authenticated_client(session_factory, _scope(tenant)) as client:
        created = _create_report(client, tenant, version_id, run_id)
        assert created.status_code == 200, created.text
        report_id = created.json()["report_id"]
        entitlement_id = _grant_entitlement(session_factory, tenant, report_id)
        response = client.get(_paths(tenant, report_id=report_id))

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_entitled"] is True
    assert payload["report"]["report_id"] == report_id
    assert payload["report"]["submission_version_id"] == str(version_id)
    assert payload["report"]["analysis_run_id"] == str(run_id)
    with session_factory() as session:
        entitlement = session.get(ReportEntitlement, entitlement_id)
        assert entitlement is not None and entitlement.status == "active"


def test_another_user_in_same_tenant_only_receives_preview(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        version_id, run_id = _create_analysis(session, tenant)
    owner_scope = _scope(tenant)
    with _authenticated_client(session_factory, owner_scope) as client:
        created = _create_report(client, tenant, version_id, run_id)
        assert created.status_code == 200, created.text
        report_id = created.json()["report_id"]
        _grant_entitlement(session_factory, tenant, report_id)

    second_user_id = _add_member(session_factory, tenant)
    with _authenticated_client(session_factory, _scope(tenant, user_id=second_user_id)) as client:
        response = client.get(_paths(tenant, report_id=report_id))

    assert response.status_code == 200
    assert response.json()["is_entitled"] is False
    assert response.json()["report"] is None
    assert response.json()["preview"]["is_limited_preview"] is True


def test_user_from_another_tenant_cannot_read_report(
    session_factory, tenant_pair
):
    tenant, other_tenant = tenant_pair
    with session_factory() as session:
        version_id, run_id = _create_analysis(session, tenant)
    with _authenticated_client(session_factory, _scope(tenant)) as client:
        created = _create_report(client, tenant, version_id, run_id)
    assert created.status_code == 200, created.text

    with _authenticated_client(session_factory, _scope(other_tenant)) as client:
        response = client.get(_paths(other_tenant, report_id=created.json()["report_id"]))

    assert response.status_code == 404


def test_nonexistent_report_returns_not_found(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with _authenticated_client(session_factory, _scope(tenant)) as client:
        response = client.get(_paths(tenant, report_id=uuid4()))

    assert response.status_code == 404


def test_revoked_entitlement_does_not_return_full_report(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        version_id, run_id = _create_analysis(session, tenant)
    with _authenticated_client(session_factory, _scope(tenant)) as client:
        created = _create_report(client, tenant, version_id, run_id)
        assert created.status_code == 200, created.text
        report_id = created.json()["report_id"]
        entitlement_id = _grant_entitlement(session_factory, tenant, report_id)
        with session_factory() as session:
            entitlement = session.get(ReportEntitlement, entitlement_id)
            assert entitlement is not None
            entitlement.status = "revoked"
            session.commit()
        response = client.get(_paths(tenant, report_id=report_id))

    assert response.status_code == 200
    assert response.json()["is_entitled"] is False
    assert response.json()["report"] is None
    assert response.json()["preview"]["is_limited_preview"] is True
