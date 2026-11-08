from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import (
    AnalysisRun,
    AnalysisStageResult,
    AuditEvent,
    Finding,
    HumanDisposition,
    ReviewDecision,
    Submission,
    SubmissionVersion,
)
from app.api.v1.reviews import router
from app.core.dependencies import get_db, get_tenant_scope
from app.modules.analysis.orchestrator import run_analysis_pipeline
from app.modules.reviews.schemas import FindingDispositionCreate, ReviewDecisionCreate
from app.modules.reviews.services import record_review_decision
from app.modules.submissions.services import create_submission_version
from app.modules.tenancy.schemas import TenantScope


def _scope(tenant) -> TenantScope:
    return TenantScope(
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        user_id=tenant.user_id,
        permissions={"review.decide"},
    )


def _create_review_case(session, tenant, text="Our annual fee is 4%."):
    scope = _scope(tenant)
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
        session.scalars(
            select(Finding).where(
                Finding.analysis_run_id == run.id,
                Finding.is_unresolved.is_(True),
            )
        )
    )
    return scope, version, submission, run, findings


def test_clean_approval_fails_when_latest_run_has_unresolved_findings(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, version, submission, run, findings = _create_review_case(session, tenant)
        assert findings

        with pytest.raises(HTTPException) as error:
            record_review_decision(
                session,
                scope,
                version,
                ReviewDecisionCreate(decision="Approved"),
            )

        assert error.value.status_code == 400
        assert submission.current_status == "In review"
        assert session.scalar(
            select(func.count()).select_from(ReviewDecision).where(
                ReviewDecision.submission_version_id == version.id
            )
        ) == 0
        assert session.get(AnalysisRun, run.id) is not None


def test_clean_approval_succeeds_after_complete_analysis_with_no_unresolved_findings(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, version, submission, run, findings = _create_review_case(
            session, tenant, text="Ordinary narrative without a claim."
        )
        assert not findings
        assert run.overall_state == "Succeeded"
        decision = record_review_decision(
            session, scope, version, ReviewDecisionCreate(decision="Approved")
        )
        audit = session.scalar(select(AuditEvent).where(AuditEvent.target_id == decision.id))

        assert decision.decision == "Approved"
        assert submission.current_status == "Approved"
        assert audit is not None and audit.action_key == "review.decision.recorded"


def test_exception_approval_fails_when_any_finding_lacks_disposition(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, version, _, _, findings = _create_review_case(session, tenant)
        assert findings

        with pytest.raises(HTTPException) as error:
            record_review_decision(
                session,
                scope,
                version,
                ReviewDecisionCreate(
                    decision="Approved with documented exceptions",
                    rationale="Approval is limited to the documented exceptions.",
                    dispositions=[],
                ),
            )

        assert error.value.status_code == 400
        assert session.scalar(
            select(func.count()).select_from(HumanDisposition).where(
                HumanDisposition.submission_version_id == version.id
            )
        ) == 0


def test_exception_approval_persists_decision_and_all_dispositions(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, version, submission, _, findings = _create_review_case(session, tenant)
        payload = ReviewDecisionCreate(
            decision="Approved with documented exceptions",
            rationale="Proceeding with the listed limitations.",
            dispositions=[
                FindingDispositionCreate(
                    finding_id=finding.id,
                    disposition="Accepted for this version",
                    rationale="The reviewer accepts this unresolved finding for this version.",
                )
                for finding in findings
            ],
        )

        decision = record_review_decision(session, scope, version, payload)
        dispositions = list(
            session.scalars(
                select(HumanDisposition).where(
                    HumanDisposition.submission_version_id == version.id
                )
            )
        )
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.target_id == decision.id)
        )

    assert decision.decision == "Approved with documented exceptions"
    assert len(dispositions) == len(findings)
    assert all(disposition.rationale.strip() for disposition in dispositions)
    assert all(finding.is_unresolved for finding in findings)
    assert submission.current_status == "Approved with documented exceptions"
    assert audit is not None and audit.action_key == "review.decision.recorded"


def test_changes_requested_requires_rationale_and_updates_parent_status(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, version, submission, _, _ = _create_review_case(
            session, tenant, text="This is ordinary narrative."
        )
        decision = record_review_decision(
            session,
            scope,
            version,
            ReviewDecisionCreate(
                decision="Changes requested",
                rationale="Please provide supporting evidence.",
            ),
        )

    assert decision.decision == "Changes requested"
    assert submission.current_status == "Changes requested"


def test_approval_requires_an_analysis_run_for_the_exact_version(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope = _scope(tenant)
        version = create_submission_version(
            session, scope, submitter_id=tenant.user_id, source_type="text",
            submitted_text="Ordinary narrative with no claims.",
        )
        submission = session.get(Submission, version.submission_id)
        assert submission is not None
        submission.current_status = "In review"
        session.commit()

        with pytest.raises(HTTPException) as error:
            record_review_decision(session, scope, version, ReviewDecisionCreate(decision="Approved"))

        assert error.value.status_code == 400
        assert error.value.detail["error"]["reason"] == "analysis_run_missing"
        assert session.scalar(select(func.count()).select_from(ReviewDecision).where(
            ReviewDecision.submission_version_id == version.id
        )) == 0
        assert submission.current_status == "In review"


def test_approval_requires_all_four_required_stage_records(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope = _scope(tenant)
        version = create_submission_version(
            session, scope, submitter_id=tenant.user_id, source_type="text",
            submitted_text="Ordinary narrative with no claims.",
        )
        run = AnalysisRun(
            id=uuid4(), organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id, submission_version_id=version.id,
            run_number=1, overall_state="Succeeded",
            started_at=datetime.now(timezone.utc),
        )
        session.add(run)
        session.flush()
        for stage_key in ("claim_extraction", "evidence_retrieval", "policy_evaluation"):
            session.add(AnalysisStageResult(
                id=uuid4(), organization_id=tenant.organization_id,
                workspace_id=tenant.workspace_id, analysis_run_id=run.id,
                stage_key=stage_key, attempt_number=1, state="Succeeded", is_required=True,
            ))
        submission = session.get(Submission, version.submission_id)
        assert submission is not None
        submission.current_status = "In review"
        session.commit()

        with pytest.raises(HTTPException) as error:
            record_review_decision(session, scope, version, ReviewDecisionCreate(decision="Approved"))

        assert error.value.detail["error"]["reason"] == "required_stage_missing"
        assert session.scalar(select(func.count()).select_from(ReviewDecision).where(
            ReviewDecision.submission_version_id == version.id
        )) == 0


@pytest.mark.parametrize("decision", ["Approved", "Approved with documented exceptions"])
def test_approval_requires_successful_overall_run(session_factory, tenant_pair, decision):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, version, _, run, _ = _create_review_case(session, tenant, text="Ordinary narrative.")
        run.overall_state = "Incomplete"
        session.commit()
        payload = ReviewDecisionCreate(
            decision=decision,
            rationale="Documented limited approval." if decision != "Approved" else None,
        )

        with pytest.raises(HTTPException) as error:
            record_review_decision(session, scope, version, payload)

        assert error.value.status_code == 400
        assert error.value.detail["error"]["reason"] == "analysis_incomplete"
        assert session.scalar(select(func.count()).select_from(ReviewDecision).where(
            ReviewDecision.submission_version_id == version.id
        )) == 0


@pytest.mark.parametrize(
    ("stage_key", "stage_state", "reason"),
    [
        ("claim_extraction", "Failed", "required_stage_failed"),
        ("evidence_retrieval", "Failed", "required_stage_failed"),
        ("policy_evaluation", "Failed", "required_stage_failed"),
        ("finding_composition", "Failed", "required_stage_failed"),
        ("policy_evaluation", "Not run", "required_stage_not_run"),
        ("policy_evaluation", "Running", "analysis_incomplete"),
    ],
)
def test_approval_requires_every_required_stage_to_succeed(
    session_factory, tenant_pair, stage_key, stage_state, reason
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, version, _, run, _ = _create_review_case(session, tenant, text="Ordinary narrative.")
        stage = session.scalar(
            select(AnalysisStageResult).where(
                AnalysisStageResult.analysis_run_id == run.id,
                AnalysisStageResult.stage_key == stage_key,
            )
        )
        assert stage is not None
        stage.state = stage_state
        if stage_state != "Succeeded":
            run.overall_state = "Incomplete"
        session.commit()

        with pytest.raises(HTTPException) as error:
            record_review_decision(session, scope, version, ReviewDecisionCreate(decision="Approved"))

        assert error.value.detail["error"]["reason"] == reason
        assert session.scalar(select(func.count()).select_from(ReviewDecision).where(
            ReviewDecision.submission_version_id == version.id
        )) == 0


def test_approval_does_not_reuse_analysis_from_an_older_version(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope, prior, submission, _, _ = _create_review_case(session, tenant, text="Older version.")
        current = SubmissionVersion(
            id=uuid4(),
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            submission_id=submission.id,
            version_number=2,
            source_type="text",
            submitted_text="New current version.",
            source_hash=sha256(b"New current version.").hexdigest(),
            submitter_membership_id=tenant.membership_id,
            prior_version_id=prior.id,
        )
        session.add(current)
        session.commit()

        with pytest.raises(HTTPException) as error:
            record_review_decision(session, scope, current, ReviewDecisionCreate(decision="Approved"))

        assert error.value.detail["error"]["reason"] == "analysis_run_missing"
        assert session.scalar(select(func.count()).select_from(ReviewDecision).where(
            ReviewDecision.submission_version_id == current.id
        )) == 0


@pytest.mark.parametrize("other_tenant", [False, True])
def test_approval_does_not_reuse_run_from_another_submission_or_tenant(
    session_factory, tenant_pair, other_tenant
):
    tenant, second_tenant = tenant_pair
    with session_factory() as session:
        scope = _scope(tenant)
        target = create_submission_version(
            session, scope, submitter_id=tenant.user_id, source_type="text",
            submitted_text="Target version has not been analyzed.",
        )
        target_submission = session.get(Submission, target.submission_id)
        assert target_submission is not None
        target_submission.current_status = "In review"
        foreign_tenant = second_tenant if other_tenant else tenant
        _, other_version, _, _, _ = _create_review_case(
            session, foreign_tenant, text="This other version has successful analysis."
        )
        assert (foreign_tenant.organization_id != scope.organization_id) is other_tenant
        session.commit()

        with pytest.raises(HTTPException) as error:
            record_review_decision(session, scope, target, ReviewDecisionCreate(decision="Approved"))

        assert error.value.detail["error"]["reason"] == "analysis_run_missing"
        assert session.scalar(select(func.count()).select_from(ReviewDecision).where(
            ReviewDecision.submission_version_id == target.id
        )) == 0
        assert other_version.id != target.id


@pytest.mark.parametrize("decision", ["Rejected", "Changes requested"])
def test_non_approval_decisions_remain_available_without_analysis(session_factory, tenant_pair, decision):
    tenant, _ = tenant_pair
    with session_factory() as session:
        scope = _scope(tenant)
        version = create_submission_version(
            session, scope, submitter_id=tenant.user_id, source_type="text", submitted_text="Needs review.",
        )
        submission = session.get(Submission, version.submission_id)
        assert submission is not None
        submission.current_status = "In review"
        session.commit()

        result = record_review_decision(
            session, scope, version,
            ReviewDecisionCreate(decision=decision, rationale="The reviewer documented this decision."),
        )

        assert result.decision == decision
        assert submission.current_status == decision


def test_review_api_requires_review_decide_permission():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_scope] = lambda: TenantScope(
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        workspace_id=UUID("00000000-0000-0000-0000-000000000002"),
        user_id=UUID("00000000-0000-0000-0000-000000000003"),
        permissions=set(),
    )
    app.dependency_overrides[get_db] = lambda: None

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/organizations/00000000-0000-0000-0000-000000000001/workspaces/00000000-0000-0000-0000-000000000002/submission-versions/00000000-0000-0000-0000-000000000004/review-decisions",
            json={"decision": "Approved"},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["error"]["message"] == "Permission 'review.decide' required"
