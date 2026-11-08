from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError

from app.api.v1.reviews import router
from app.core.dependencies import get_db, get_tenant_scope
from app.models import AnalysisRun, AuditEvent, Finding, HumanDisposition, Submission
from app.modules.analysis.orchestrator import run_analysis_pipeline
from app.modules.reviews.schemas import (
    FindingDispositionRecordCreate,
    ReviewDecisionCreate,
)
from app.modules.reviews.services import (
    calculate_review_eligibility,
    record_finding_disposition,
    record_review_decision,
)
from app.modules.submissions.services import create_submission_version
from app.modules.tenancy.schemas import TenantScope


def _scope(tenant, *permissions: str) -> TenantScope:
    return TenantScope(
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        user_id=tenant.user_id,
        permissions=set(permissions),
    )


def _case(session, tenant, text="The annual yield is guaranteed at 4%."):
    scope = _scope(tenant, "review.decide", "submission.read.workspace")
    version = create_submission_version(
        session,
        scope,
        submitter_id=tenant.user_id,
        source_type="text",
        submitted_text=text,
    )
    run = run_analysis_pipeline(session, version, scope)
    submission = session.get(Submission, version.submission_id)
    assert submission is not None
    submission.current_status = "In review"
    session.commit()
    findings = list(
        session.query(Finding)
        .filter(Finding.analysis_run_id == run.id, Finding.is_unresolved.is_(True))
        .order_by(Finding.created_at, Finding.id)
    )
    return scope, version, run, submission, findings


def _record(session, scope, version, run, finding, disposition, rationale="Reviewer assessed this finding."):
    return record_finding_disposition(
        session,
        scope,
        finding.id,
        FindingDispositionRecordCreate(
            analysis_run_id=run.id,
            submission_version_id=version.id,
            disposition=disposition,
            rationale=rationale,
        ),
    )


@pytest.mark.parametrize("disposition", ["resolved", "not_applicable"])
def test_resolved_dispositions_clear_clean_approval_blocker(session_factory, tenant_pair, disposition):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, version, run, submission, findings = _case(session, tenant)
        assert findings
        for finding in findings:
            _record(session, scope, version, run, finding, disposition)
        eligibility = calculate_review_eligibility(session, scope, version)
        assert findings[0].is_unresolved is True
        assert findings[0].id not in {row.id for row in eligibility.blocking_findings}
        assert eligibility.can_clean_approve
        decision = record_review_decision(session, scope, version, ReviewDecisionCreate(decision="Approved"))
        assert decision.decision == "Approved"
        assert submission.current_status == "Approved"


@pytest.mark.parametrize("disposition", ["acknowledged", "disputed"])
def test_acknowledged_and_disputed_dispositions_still_block_clean_approval(
    session_factory, tenant_pair, disposition
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, version, run, _, findings = _case(session, tenant)
        _record(session, scope, version, run, findings[0], disposition)
        eligibility = calculate_review_eligibility(session, scope, version)
        assert findings[0].is_unresolved is True
        assert findings[0].id in {row.id for row in eligibility.blocking_findings}
        assert not eligibility.can_clean_approve
        with pytest.raises(HTTPException) as error:
            record_review_decision(session, scope, version, ReviewDecisionCreate(decision="Approved"))
        assert error.value.status_code == 400


def test_disposition_history_is_append_only_and_latest_entry_is_effective(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, version, run, _, findings = _case(session, tenant)
        finding = findings[0]
        first = _record(session, scope, version, run, finding, "resolved", "Addressed in source.")
        second = _record(session, scope, version, run, finding, "disputed", "The reviewer contests this result.")
        third = _record(session, scope, version, run, finding, "not_applicable", "Claim does not apply.")
        history = list(
            session.scalars(
                select(HumanDisposition)
                .where(HumanDisposition.finding_id == finding.id)
                .order_by(HumanDisposition.sequence_number)
            )
        )
        eligibility = calculate_review_eligibility(session, scope, version)
        events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action_key == "review.finding_disposition.recorded",
                    AuditEvent.target_id.in_([first.id, second.id, third.id]),
                )
            )
        )
        assert [row.sequence_number for row in history] == [1, 2, 3]
        assert [row.disposition for row in history] == ["resolved", "disputed", "not_applicable"]
        assert finding.is_unresolved is True
        assert finding.id not in {row.id for row in eligibility.blocking_findings}
        assert len(events) == 3
        assert all(event.safe_metadata["rationale"] for event in events)


def test_exception_approval_keeps_original_findings_immutable_and_records_dispositions(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, version, run, submission, findings = _case(session, tenant)
        decision = record_review_decision(
            session,
            scope,
            version,
            ReviewDecisionCreate(
                decision="Approved with documented exceptions",
                rationale="Proceeding with the limitations documented below.",
                dispositions=[
                    {
                        "finding_id": finding.id,
                        "disposition": "acknowledged",
                        "rationale": "Reviewer accepts the documented exception.",
                    }
                    for finding in findings
                ],
            ),
        )
        stored = list(
            session.scalars(
                select(HumanDisposition).where(HumanDisposition.submission_version_id == version.id)
            )
        )
        assert decision.decision == "Approved with documented exceptions"
        assert submission.current_status == decision.decision
        assert len(stored) == len(findings)
        assert all(finding.is_unresolved is True for finding in findings)
        assert all(row.disposition == "acknowledged" and row.rationale for row in stored)


@pytest.mark.parametrize(
    ("disposition", "rationale"),
    [("dismissed", "Not supported by the contract."), ("resolved", "   ")],
)
def test_invalid_disposition_or_blank_rationale_rejected_by_request_schema(disposition, rationale):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FindingDispositionRecordCreate(
            analysis_run_id=uuid4(),
            submission_version_id=uuid4(),
            disposition=disposition,
            rationale=rationale,
        )


def test_disposition_api_returns_resolution_and_rejects_cross_tenant_path(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, version, run, _, findings = _case(session, tenant)
        finding = findings[0]
        app = FastAPI()
        app.include_router(router)

        def override_db():
            yield session

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_tenant_scope] = lambda: scope
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/findings/{finding.id}/dispositions",
                json={
                    "analysis_run_id": str(run.id),
                    "submission_version_id": str(version.id),
                    "disposition": "resolved",
                    "rationale": "The reviewer checked the source and resolved it.",
                },
            )
            other_org = uuid4()
            cross_tenant = client.post(
                f"/api/v1/organizations/{other_org}/workspaces/{tenant.workspace_id}/findings/{finding.id}/dispositions",
                json={
                    "analysis_run_id": str(run.id),
                    "submission_version_id": str(version.id),
                    "disposition": "resolved",
                    "rationale": "This must not be recorded.",
                },
            )
            cross_workspace = client.post(
                f"/api/v1/organizations/{tenant.organization_id}/workspaces/{uuid4()}/findings/{finding.id}/dispositions",
                json={
                    "analysis_run_id": str(run.id),
                    "submission_version_id": str(version.id),
                    "disposition": "resolved",
                    "rationale": "This must also be rejected.",
                },
            )
        assert response.status_code == 201
        assert response.json()["finding_resolution"]["blocks_clean_approval"] is False
        assert len(response.json()["finding_resolution"]["disposition_history"]) == 1
        assert cross_tenant.status_code == 404
        assert cross_workspace.status_code == 404


def test_disposition_rejects_stale_run_version_and_missing_permission(session_factory, tenant_pair):
    tenant, other = tenant_pair
    with session_factory() as session:
        scope, version, run, _, findings = _case(session, tenant)
        finding = findings[0]
        payload = FindingDispositionRecordCreate(
            analysis_run_id=run.id,
            submission_version_id=version.id,
            disposition="resolved",
            rationale="Reviewed.",
        )
        unauthorized_scope = _scope(tenant)
        with pytest.raises(HTTPException) as denied:
            record_finding_disposition(session, unauthorized_scope, finding.id, payload)
        assert denied.value.status_code == 403
        foreign_scope = _scope(other, "review.decide")
        with pytest.raises(HTTPException) as hidden:
            record_finding_disposition(session, foreign_scope, finding.id, payload)
        assert hidden.value.status_code == 404


def test_disposition_requires_latest_analysis_run(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, version, run, _, findings = _case(session, tenant)
        # A newer empty run makes findings from the prior run stale for new dispositions.
        newer = AnalysisRun(
            id=uuid4(), organization_id=tenant.organization_id, workspace_id=tenant.workspace_id,
            submission_version_id=version.id, run_number=run.run_number + 1,
            overall_state="Succeeded", started_at=datetime.now(timezone.utc),
        )
        session.add(newer)
        session.commit()
        with pytest.raises(HTTPException) as stale:
            _record(session, scope, version, run, findings[0], "resolved")
        assert stale.value.status_code == 409
        assert session.scalar(
            select(func.count()).select_from(HumanDisposition).where(HumanDisposition.finding_id == findings[0].id)
        ) == 0


def test_original_finding_is_database_append_only(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        _, _, _, _, findings = _case(session, tenant)
        finding = findings[0]
        original_explanation = finding.explanation
        with pytest.raises(DBAPIError):
            session.execute(
                update(Finding)
                .where(Finding.id == finding.id)
                .values(explanation="Attempted mutation")
            )
        session.rollback()
        persisted = session.get(Finding, finding.id)
        assert persisted is not None
        assert persisted.explanation == original_explanation
