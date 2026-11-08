from uuid import uuid4

from sqlalchemy import select

from app.models import (
    AnalysisRun,
    AnalysisStageResult,
    EvidenceRecord,
    EvidenceVersion,
    Finding,
    Policy,
    PolicyVersion,
)
from app.modules.analysis.orchestrator import run_analysis_pipeline
from app.modules.submissions.services import create_submission_version
from app.modules.tenancy.schemas import TenantScope


def _scope(tenant) -> TenantScope:
    return TenantScope(
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        user_id=tenant.user_id,
        permissions=set(),
    )


def _run(session, tenant, text):
    scope = _scope(tenant)
    submission_version = create_submission_version(
        session,
        scope,
        submitter_id=tenant.user_id,
        source_type="text",
        submitted_text=text,
    )
    run = run_analysis_pipeline(session, submission_version, scope)
    findings = list(
        session.scalars(
            select(Finding)
            .where(Finding.analysis_run_id == run.id)
            .order_by(Finding.category, Finding.id)
        )
    )
    return run, findings


def test_claim_without_evidence_creates_unverified_finding(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        run, findings = _run(session, tenant, "Our annual fee is 9%.")

    unverified = [finding for finding in findings if finding.category.startswith("Unverified")]
    assert run.overall_state == "Succeeded"
    assert len(unverified) == 1
    assert unverified[0].is_unresolved is True
    assert unverified[0].claim_id is not None


def test_claim_with_eligible_evidence_creates_supported_finding(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    source = "The annual fee is 2%."
    with session_factory() as session:
        record = session.get(EvidenceRecord, tenant.evidence_record_id)
        assert record is not None
        record.primary_lifecycle_state = "Approved"
        evidence_version = EvidenceVersion(
            id=uuid4(),
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            evidence_record_id=record.id,
            version_number=1,
            title=source,
            extracted_text=source,
            created_by_membership_id=tenant.membership_id,
            pending_reapproval=False,
        )
        session.add(evidence_version)
        session.flush()
        record.current_version_id = evidence_version.id
        session.flush()
        run, findings = _run(session, tenant, source)

    supported = [finding for finding in findings if finding.category == "Supported match found"]
    assert run.overall_state == "Succeeded"
    assert len(supported) == 1
    assert supported[0].claim_id is not None
    assert supported[0].evidence_version_id is not None


def test_active_prohibited_term_policy_creates_policy_finding(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        policy = Policy(
            id=uuid4(),
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
            name="Prohibited guarantee wording",
            category="claims",
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
            rule_text="guaranteed",
            rule_type="prohibited_term",
            configuration={"term": "guaranteed"},
            status_snapshot="Active",
            created_by_membership_id=tenant.membership_id,
        )
        session.add(policy_version)
        session.flush()

        run, findings = _run(session, tenant, "Returns are guaranteed.")

    policy_findings = [finding for finding in findings if finding.category == "Policy finding"]
    assert run.overall_state == "Succeeded"
    assert len(policy_findings) == 1
    assert policy_findings[0].policy_version_id == policy_version.id
    assert "guaranteed" in policy_findings[0].explanation


def test_completed_pipeline_has_all_successful_stages_and_succeeded_run(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        run, _ = _run(session, tenant, "Our annual fee is 9%.")
        stages = list(
            session.scalars(
                select(AnalysisStageResult).where(AnalysisStageResult.analysis_run_id == run.id)
            )
        )
        persisted_run = session.get(AnalysisRun, run.id)

    assert persisted_run is not None
    assert persisted_run.overall_state == "Succeeded"
    assert {stage.stage_key for stage in stages} == {
        "claim_extraction",
        "evidence_retrieval",
        "policy_evaluation",
        "finding_composition",
    }
    assert all(stage.state == "Succeeded" for stage in stages)
