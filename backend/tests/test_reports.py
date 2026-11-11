from datetime import date, datetime, timezone
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models import (
    AnalysisRun,
    AnalysisStageResult,
    AuditEvent,
    EvidenceMatchCandidate,
    EvidenceRecord,
    EvidenceVersion,
    ExtractedClaim,
    Finding,
    PayPalWebhookEvent,
    PaymentTransaction,
    Policy,
    PolicyVersion,
    Report,
    ReportEntitlement,
)
from app.modules.reports.payments import (
    InvalidWebhook,
    InvalidVerifiedPayment,
    PayPalCapture,
    PayPalOrder,
    PayPalWebhookVerification,
    attach_paypal_order,
    create_pending_payment,
    record_verified_capture_and_grant_entitlement,
    record_verified_webhook_event,
)
from app.modules.reports.snapshot import (
    ReportNotEligible,
    create_report_snapshot,
    project_report_preview,
)
from fakes.paypal import FakePayPalGateway
from app.modules.submissions.services import create_submission_version
from app.modules.tenancy.schemas import TenantScope


REQUIRED_STAGES = (
    "claim_extraction",
    "evidence_retrieval",
    "policy_evaluation",
    "finding_composition",
)


def _scope(tenant):
    return TenantScope(
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        user_id=tenant.user_id,
        permissions=set(),
    )


def _create_analysis(session, tenant, *, run_state="Succeeded", failing_stage=None):
    scope = _scope(tenant)
    source_text = "The service supports a 42 percent renewable energy claim. No evidence for the second assertion."
    version = create_submission_version(
        session,
        scope,
        submitter_id=tenant.user_id,
        source_type="text",
        submitted_text=source_text,
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
    )
    session.add(run)
    session.flush()
    for key in REQUIRED_STAGES:
        stage = AnalysisStageResult(
            id=uuid4(),
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            analysis_run_id=run.id,
            stage_key=key,
            attempt_number=1,
            state="Failed" if key == failing_stage else "Succeeded",
            is_required=True,
            started_at=now,
            completed_at=now,
        )
        session.add(stage)
    session.flush()

    supported_text = "42 percent renewable energy"
    unverified_text = "No evidence for the second assertion."
    supported_start = source_text.index(supported_text)
    unverified_start = source_text.index(unverified_text)
    supported_claim = ExtractedClaim(
        id=uuid4(),
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        analysis_run_id=run.id,
        submission_version_id=version.id,
        text_span=supported_text,
        start_offset=supported_start,
        end_offset=supported_start + len(supported_text),
        candidate_kind="factual",
    )
    unverified_claim = ExtractedClaim(
        id=uuid4(),
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        analysis_run_id=run.id,
        submission_version_id=version.id,
        text_span=unverified_text,
        start_offset=unverified_start,
        end_offset=unverified_start + len(unverified_text),
        candidate_kind="factual",
    )
    session.add_all([supported_claim, unverified_claim])
    session.flush()

    evidence = session.get(EvidenceRecord, tenant.evidence_record_id)
    assert evidence is not None
    evidence.primary_lifecycle_state = "Approved"
    evidence_version = EvidenceVersion(
        id=uuid4(),
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        evidence_record_id=evidence.id,
        version_number=1,
        title="Renewable Energy Report",
        extracted_text="Renewable energy represented 42 percent of usage.",
        valid_from=date(2026, 1, 1),
        valid_until=date(2026, 12, 31),
        created_by_membership_id=tenant.membership_id,
    )
    session.add(evidence_version)
    session.flush()
    evidence.current_version_id = evidence_version.id

    policy = Policy(
        id=uuid4(),
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        name="Promotional Claims Standard",
        category="promotional",
        status="Active",
        created_by_membership_id=tenant.membership_id,
    )
    session.add(policy)
    session.flush()
    policy_version = PolicyVersion(
        id=uuid4(),
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        policy_id=policy.id,
        version_number=1,
        rule_text="Avoid unsupported guarantees.",
        rule_type="prohibited_term",
        configuration={"term": "guaranteed"},
        status_snapshot="Active",
        created_by_membership_id=tenant.membership_id,
    )
    session.add(policy_version)
    session.flush()
    policy.current_version_id = policy_version.id

    match = EvidenceMatchCandidate(
        id=uuid4(),
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        analysis_run_id=run.id,
        submission_version_id=version.id,
        claim_id=supported_claim.id,
        evidence_record_id=evidence.id,
        evidence_version_id=evidence_version.id,
        eligibility_snapshot={"is_eligible": True, "freshness_unknown": False, "analysis_time": now.isoformat()},
        match_explanation="Synthetic fixture links the relevant claim and evidence version.",
        candidate_ordering=1,
    )
    session.add(match)
    supported_finding = Finding(
        id=uuid4(),
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        analysis_run_id=run.id,
        submission_version_id=version.id,
        claim_id=supported_claim.id,
        category="Supported match found",
        attention_label="supported",
        explanation="The evidence version contains the claim information.",
        evidence_record_id=evidence.id,
        evidence_version_id=evidence_version.id,
        is_unresolved=True,
    )
    unverified_finding = Finding(
        id=uuid4(),
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        analysis_run_id=run.id,
        submission_version_id=version.id,
        claim_id=unverified_claim.id,
        category="Unverified — no eligible approved evidence found",
        attention_label="unverified",
        explanation="No eligible approved evidence version matched this claim.",
        is_unresolved=True,
    )
    policy_finding = Finding(
        id=uuid4(),
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        analysis_run_id=run.id,
        submission_version_id=version.id,
        claim_id=None,
        category="Policy finding",
        attention_label="policy",
        explanation="The active policy rule was triggered.",
        policy_id=policy.id,
        policy_version_id=policy_version.id,
        is_unresolved=True,
    )
    session.add_all([supported_finding, unverified_finding, policy_finding])
    session.flush()
    return version, run, supported_claim, unverified_claim, supported_finding


def _make_report(session_factory, tenant, *, run_state="Succeeded", failing_stage=None):
    with session_factory() as session:
        version, run, supported_claim, unverified_claim, finding = _create_analysis(
            session, tenant, run_state=run_state, failing_stage=failing_stage
        )
        session.commit()
        report = None
        if run_state == "Succeeded" and failing_stage is None:
            report = create_report_snapshot(
                session,
                _scope(tenant),
                submission_version_id=version.id,
                analysis_run_id=run.id,
            )
        return version, run, supported_claim, unverified_claim, finding, report


def test_successful_snapshot_is_version_bound_idempotent_and_preview_is_limited(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    version, run, _, _, finding, report = _make_report(session_factory, tenant)

    with session_factory() as session:
        duplicate = create_report_snapshot(
            session,
            _scope(tenant),
            submission_version_id=version.id,
            analysis_run_id=run.id,
        )
        preview = project_report_preview(report)
        assert duplicate.id == report.id
        assert report.submission_version_id == version.id
        assert report.analysis_run_id == run.id
        assert report.content_snapshot["overall_analysis_status"] == "Succeeded"
        findings_by_category = {item["category"]: item for item in report.content_snapshot["findings"]}
        assert findings_by_category["Supported match found"]["finding_id"] == str(finding.id)
        assert report.content_snapshot["counts"]["unverified_findings"] == 1
        assert report.content_snapshot["counts"]["supported_findings"] == 1
        assert report.content_snapshot["counts"]["policy_findings"] == 1
        supporting_evidence = findings_by_category["Supported match found"]["supporting_evidence"][0]
        assert supporting_evidence["title"] == "Renewable Energy Report"
        assert supporting_evidence["eligibility_snapshot"]["is_eligible"] is True
        policy_result = findings_by_category["Policy finding"]["policy_result"]
        assert policy_result["policy_name"] == "Promotional Claims Standard"
        assert preview.is_limited_preview is True
        assert len(preview.finding_sample) == 2
        assert "findings" not in preview.model_dump()
        assert "supporting_evidence" not in preview.model_dump_json()


@pytest.mark.parametrize(
    "run_state,failing_stage",
    [("Incomplete", None), ("Succeeded", "policy_evaluation")],
)
def test_report_rejects_incomplete_or_failed_required_stage(
    session_factory, tenant_pair, run_state, failing_stage
):
    tenant, _ = tenant_pair
    version, run, _, _, _, _ = _make_report(
        session_factory, tenant, run_state=run_state, failing_stage=failing_stage
    )
    with session_factory() as session:
        with pytest.raises(ReportNotEligible):
            create_report_snapshot(
                session,
                _scope(tenant),
                submission_version_id=version.id,
                analysis_run_id=run.id,
            )


def test_report_snapshot_is_immutable_and_ignores_later_source_rows(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    version, run, supported_claim, _, finding, report = _make_report(session_factory, tenant)
    snapshot_before = report.content_snapshot.copy()
    with session_factory() as session:
        report = session.get(Report, report.id)
        assert report is not None
        session.add(Finding(
            id=uuid4(),
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            analysis_run_id=run.id,
            submission_version_id=version.id,
            claim_id=supported_claim.id,
            category="Policy finding",
            attention_label="policy",
            explanation="Later source row for immutability regression coverage.",
            is_unresolved=True,
        ))
        session.flush()
        preview = project_report_preview(report)
        assert report.content_snapshot == snapshot_before
        assert preview.counts.findings == 3

        report.content_snapshot = {"tampered": True}
        with pytest.raises(DBAPIError):
            session.flush()
        session.rollback()


def test_default_server_priced_pending_payment_has_no_entitlement(session_factory, tenant_pair, monkeypatch):
    tenant, _ = tenant_pair
    _, _, _, _, _, report = _make_report(session_factory, tenant)
    monkeypatch.delenv("REPORT_PRICE_AMOUNT", raising=False)
    monkeypatch.delenv("REPORT_CURRENCY", raising=False)
    with session_factory() as session:
        payment = create_pending_payment(
            session,
            _scope(tenant),
            report_id=report.id,
            idempotency_key="test-pay-1",
        )
        assert payment.expected_amount == Decimal("5.00")
        assert payment.currency == "USD"
        assert payment.status == "pending"
        assert "amount" not in __import__("inspect").signature(create_pending_payment).parameters
        assert session.scalar(select(func.count(ReportEntitlement.id))) == 0


def test_database_rejects_entitlement_from_pending_payment(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    _, _, _, _, _, report = _make_report(session_factory, tenant)
    with session_factory() as session:
        payment = create_pending_payment(
            session,
            _scope(tenant),
            report_id=report.id,
            idempotency_key="pending-cannot-entitle",
        )
        entitlement = ReportEntitlement(
            id=uuid4(),
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            report_id=report.id,
            purchaser_user_id=tenant.user_id,
            payment_transaction_id=payment.id,
            status="active",
        )
        nested = session.begin_nested()
        session.add(entitlement)
        with pytest.raises(DBAPIError):
            session.flush()
        nested.rollback()
        assert session.scalar(select(func.count(ReportEntitlement.id))) == 0


def test_only_matching_verified_capture_grants_one_idempotent_entitlement(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    _, _, _, _, _, report = _make_report(session_factory, tenant)
    with session_factory() as session:
        payment = create_pending_payment(
            session,
            _scope(tenant),
            report_id=report.id,
            idempotency_key="test-pay-capture",
        )
        order_id = "SANDBOX-ORDER-001"
        fake_paypal = FakePayPalGateway(
            order=PayPalOrder(
                order_id,
                "CREATED",
                "https://sandbox.invalid/approve",
                Decimal("5.00"),
                "USD",
            )
        )
        provider_order = fake_paypal.create_order(
            request_id="request-order-001",
            amount=payment.expected_amount,
            currency=payment.currency,
            report_reference=str(report.id),
            return_url="http://localhost:5173/report-return",
            cancel_url="http://localhost:5173/report-cancel",
        )
        attach_paypal_order(
            session,
            _scope(tenant),
            transaction_id=payment.id,
            order=provider_order,
        )
        payment_id = payment.id
        capture = PayPalCapture(
            order_id=order_id,
            capture_id="SANDBOX-CAPTURE-001",
            order_status="COMPLETED",
            capture_status="COMPLETED",
            amount=Decimal("5.00"),
            currency="USD",
            provider_verified=True,
            report_reference=None,
        )
        with pytest.raises(InvalidVerifiedPayment):
            record_verified_capture_and_grant_entitlement(
                session,
                _scope(tenant),
                transaction_id=payment.id,
                capture=replace(capture, provider_verified=False),
            )
        session.rollback()

    with session_factory() as session:
        payment = session.get(PaymentTransaction, payment_id)
        assert payment is not None and payment.status == "pending"
        capture = PayPalCapture(
            order_id=order_id,
            capture_id="SANDBOX-CAPTURE-001",
            order_status="COMPLETED",
            capture_status="COMPLETED",
            amount=Decimal("5.00"),
            currency="USD",
            provider_verified=True,
            report_reference=None,
        )
        fake_paypal = FakePayPalGateway(capture=capture)
        capture_result = fake_paypal.get_order(order_id=order_id)
        assert capture_result.provider_verified
        with pytest.raises(InvalidVerifiedPayment):
            record_verified_capture_and_grant_entitlement(
                session,
                _scope(tenant),
                transaction_id=payment.id,
                capture=replace(capture_result, report_reference="another-report"),
            )
        with pytest.raises(InvalidVerifiedPayment):
            record_verified_capture_and_grant_entitlement(
                session,
                _scope(tenant),
                transaction_id=payment.id,
                capture=replace(capture_result, capture_status="PENDING"),
            )
        entitlement = record_verified_capture_and_grant_entitlement(
            session,
            _scope(tenant),
            transaction_id=payment.id,
            capture=capture_result,
        )
        duplicate = record_verified_capture_and_grant_entitlement(
            session,
            _scope(tenant),
            transaction_id=payment.id,
            capture=capture,
        )
        assert entitlement.id == duplicate.id
        assert payment.status == "capture_verified"
        assert payment.verified_at is not None
        assert session.scalar(select(func.count(ReportEntitlement.id))) == 1
        assert session.scalar(
            select(func.count(AuditEvent.id)).where(AuditEvent.action_key == "report.entitlement.granted")
        ) == 1


def test_order_amount_currency_and_order_association_are_checked(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    _, _, _, _, _, report = _make_report(session_factory, tenant)
    with session_factory() as session:
        payment = create_pending_payment(session, _scope(tenant), report_id=report.id, idempotency_key="test-pay-invalid")
        with pytest.raises(InvalidVerifiedPayment):
            attach_paypal_order(
                session,
                _scope(tenant),
                transaction_id=payment.id,
                order=PayPalOrder("O-1", "CREATED", "https://sandbox.invalid", Decimal("4.99"), "USD"),
            )
        assert payment.paypal_order_id is None


def test_paypal_order_and_capture_ids_are_unique(session_factory, tenant_pair):
    first, second = tenant_pair
    _, _, _, _, _, report_a = _make_report(session_factory, first)
    _, _, _, _, _, report_b = _make_report(session_factory, second)
    with session_factory() as session:
        payment_a = create_pending_payment(session, _scope(first), report_id=report_a.id, idempotency_key="unique-a")
        payment_b = create_pending_payment(session, _scope(second), report_id=report_b.id, idempotency_key="unique-b")
        payment_a_id = payment_a.id
        payment_b_id = payment_b.id
        attach_paypal_order(
            session, _scope(first), transaction_id=payment_a.id,
            order=PayPalOrder("UNIQUE-ORDER", "CREATED", "https://sandbox.invalid", Decimal("5.00"), "USD"),
        )
        with pytest.raises(IntegrityError):
            attach_paypal_order(
                session, _scope(second), transaction_id=payment_b.id,
                order=PayPalOrder("UNIQUE-ORDER", "CREATED", "https://sandbox.invalid", Decimal("5.00"), "USD"),
            )
        session.rollback()

    with session_factory() as session:
        payment_a = session.scalar(select(PaymentTransaction).where(PaymentTransaction.id == payment_a_id))
        payment_b = session.scalar(select(PaymentTransaction).where(PaymentTransaction.id == payment_b_id))
        assert payment_a is not None and payment_b is not None
        payment_a.paypal_capture_id = "UNIQUE-CAPTURE"
        session.flush()
        payment_b.paypal_capture_id = "UNIQUE-CAPTURE"
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_verified_webhook_events_are_deduplicated_and_invalid_events_are_rejected(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    _, _, _, _, _, report = _make_report(session_factory, tenant)
    verified = PayPalWebhookVerification("EVT-1", "PAYMENT.CAPTURE.COMPLETED", "ORDER-1", "CAP-1", True)
    with session_factory() as session:
        create_pending_payment(
            session,
            _scope(tenant),
            report_id=report.id,
            idempotency_key="webhook-pending",
        )
        event = record_verified_webhook_event(session, verification=verified)
        duplicate = record_verified_webhook_event(session, verification=verified)
        assert event.id == duplicate.id
        assert session.scalar(select(func.count(PayPalWebhookEvent.id))) == 1
        with pytest.raises(InvalidWebhook):
            record_verified_webhook_event(
                session,
                verification=PayPalWebhookVerification("EVT-BAD", "PAYMENT.CAPTURE.COMPLETED", None, None, False),
            )
        assert session.scalar(select(func.count(PayPalWebhookEvent.id))) == 1
        assert session.scalar(select(func.count(ReportEntitlement.id))) == 0


def test_cross_tenant_report_reference_is_rejected_by_database(session_factory, tenant_pair):
    first, second = tenant_pair
    _, _, _, _, _, report = _make_report(session_factory, first)
    with session_factory() as session:
        payment = PaymentTransaction(
            id=uuid4(),
            organization_id=second.organization_id,
            workspace_id=second.workspace_id,
            report_id=report.id,
            purchaser_user_id=second.user_id,
            purchaser_membership_id=second.membership_id,
            provider="paypal_sandbox",
            expected_amount=Decimal("5.00"),
            currency="USD",
            status="pending",
            idempotency_key="cross-tenant",
        )
        nested = session.begin_nested()
        session.add(payment)
        with pytest.raises(IntegrityError):
            session.flush()
        nested.rollback()
