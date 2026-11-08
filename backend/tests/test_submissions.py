from hashlib import sha256
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.api.v1.submissions import router
from app.core.dependencies import get_db, get_tenant_scope
from app.models import (
    AnalysisRun,
    AnalysisStageResult,
    EvidenceRecord,
    EvidenceVersion,
    EvidenceMatchCandidate,
    Finding,
    Policy,
    PolicyVersion,
    Submission,
    SubmissionVersion,
)
from app.modules.submissions.services import create_submission_version
from app.modules.tenancy.schemas import TenantScope
from app.modules.analysis.orchestrator import REQUIRED_STAGE_ORDER


def _scope(tenant) -> TenantScope:
    return TenantScope(
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        user_id=tenant.user_id,
        permissions={"submission.create"},
    )


def test_create_text_submission_writes_submission_and_version(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    scope = _scope(tenant)
    source = "Synthetic English submission text."

    with session_factory() as session:
        version = create_submission_version(
            session,
            scope,
            submitter_id=tenant.user_id,
            source_type="text",
            submitted_text=source,
        )

        submission = session.get(Submission, version.submission_id)
        persisted_version = session.scalar(
            select(SubmissionVersion).where(SubmissionVersion.id == version.id)
        )

    assert submission is not None
    assert submission.current_status == "Submitted"
    assert persisted_version is not None
    assert persisted_version.version_number == 1
    assert persisted_version.submitted_text == source
    assert persisted_version.submitter_membership_id == tenant.membership_id


def test_text_source_hash_is_sha256_of_utf8_content(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    source = "Claim content for hashing."

    with session_factory() as session:
        version = create_submission_version(
            session,
            _scope(tenant),
            submitter_id=tenant.user_id,
            source_type="text",
            submitted_text=source,
        )

    assert version.source_hash == sha256(source.encode("utf-8")).hexdigest()


def test_submission_api_denies_missing_create_permission():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_scope] = lambda: TenantScope(
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        workspace_id=UUID("00000000-0000-0000-0000-000000000002"),
        user_id=UUID("00000000-0000-0000-0000-000000000003"),
        permissions=set(),
    )
    # Permission denial occurs before database access; keep this explicit so a
    # regression cannot accidentally turn the route into an unguarded API.
    app.dependency_overrides[get_db] = lambda: None

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/organizations/00000000-0000-0000-0000-000000000001/workspaces/00000000-0000-0000-0000-000000000002/submissions",
            json={"source_type": "text", "submitted_text": "Synthetic claim."},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["error"]["message"] == "Permission 'submission.create' required"


def _submission_api(session_factory, scope):
    app = FastAPI()
    app.include_router(router)

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_tenant_scope] = lambda: scope
    return app


def _post_submission(client, tenant, text="Our annual return is guaranteed at 12%."):
    return client.post(
        f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/submissions",
        json={"source_type": "text", "submitted_text": text},
    )


def test_submission_api_runs_all_four_stages_and_returns_persisted_findings(
    session_factory, tenant_pair, monkeypatch
):
    tenant, _ = tenant_pair
    monkeypatch.setenv("AI_ENABLED", "false")
    app = _submission_api(session_factory, _scope(tenant))
    with TestClient(app) as client:
        response = _post_submission(client, tenant)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["current_status"] == "Submitted"
    assert body["analysis_status"] == "Succeeded"
    assert body["analysis_run_id"]

    with session_factory() as session:
        version = session.get(SubmissionVersion, UUID(body["version_id"]))
        run = session.get(AnalysisRun, UUID(body["analysis_run_id"]))
        stages = list(
            session.scalars(
                select(AnalysisStageResult)
                .where(AnalysisStageResult.analysis_run_id == UUID(body["analysis_run_id"]))
            )
        )
        findings = list(
            session.scalars(
                select(Finding).where(Finding.analysis_run_id == UUID(body["analysis_run_id"]))
            )
        )

    assert version is not None
    assert run is not None and run.submission_version_id == version.id
    assert run.overall_state == "Succeeded"
    stages_by_key = {stage.stage_key: stage for stage in stages}
    assert set(stages_by_key) == set(REQUIRED_STAGE_ORDER)
    assert all(stages_by_key[key].state == "Succeeded" for key in REQUIRED_STAGE_ORDER)
    stage_start_times = [stages_by_key[key].started_at for key in REQUIRED_STAGE_ORDER]
    assert stage_start_times == sorted(stage_start_times)
    assert findings
    assert all(finding.submission_version_id == version.id for finding in findings)
    assert all(finding.analysis_run_id == run.id for finding in findings)


@pytest.mark.parametrize(
    ("failure_target", "failed_stage_key"),
    [
        ("extract_claims", "claim_extraction"),
        ("retrieve_evidence_for_claims", "evidence_retrieval"),
        ("evaluate_policies", "policy_evaluation"),
        ("compose_findings", "finding_composition"),
    ],
)
def test_submission_api_returns_incomplete_and_persists_failure_per_stage(
    session_factory, tenant_pair, monkeypatch, failure_target, failed_stage_key
):
    tenant, _ = tenant_pair

    def fail_stage(*_args, **_kwargs):
        raise RuntimeError("sensitive stage input must not be persisted")

    monkeypatch.setattr(f"app.modules.analysis.orchestrator.{failure_target}", fail_stage)
    app = _submission_api(session_factory, _scope(tenant))
    with TestClient(app) as client:
        response = _post_submission(client, tenant)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["analysis_status"] == "Incomplete"
    assert body["analysis_run_id"]

    with session_factory() as session:
        version = session.get(SubmissionVersion, UUID(body["version_id"]))
        run = session.get(AnalysisRun, UUID(body["analysis_run_id"]))
        stages = list(
            session.scalars(
                select(AnalysisStageResult).where(
                    AnalysisStageResult.analysis_run_id == UUID(body["analysis_run_id"])
                )
            )
        )
        findings = list(
            session.scalars(
                select(Finding).where(Finding.analysis_run_id == UUID(body["analysis_run_id"]))
            )
        )

    assert version is not None  # Submission remains durable after analysis failure.
    assert run is not None and run.overall_state == "Incomplete"
    by_key = {stage.stage_key: stage for stage in stages}
    assert by_key[failed_stage_key].state == "Failed"
    assert "sensitive stage input" not in (by_key[failed_stage_key].error_message or "")
    failed_index = REQUIRED_STAGE_ORDER.index(failed_stage_key)
    for stage_key in REQUIRED_STAGE_ORDER[failed_index + 1 :]:
        assert by_key[stage_key].state == "Not run"
    assert all(finding.analysis_run_id == run.id for finding in findings)


def test_submission_api_does_not_use_another_tenants_evidence_or_policies(
    session_factory, tenant_pair
):
    tenant, other_tenant = tenant_pair
    with session_factory() as session:
        foreign_record = session.get(EvidenceRecord, other_tenant.evidence_record_id)
        foreign_policy = session.get(Policy, other_tenant.policy_id)
        assert foreign_record is not None and foreign_policy is not None
        foreign_record.primary_lifecycle_state = "Approved"
        foreign_policy.status = "Active"
        policy_version = PolicyVersion(
            id=uuid4(),
            organization_id=other_tenant.organization_id,
            workspace_id=other_tenant.workspace_id,
            policy_id=foreign_policy.id,
            version_number=1,
            rule_text="Do not say guaranteed.",
            rule_type="prohibited_term",
            configuration={"term": "guaranteed"},
            status_snapshot="Active",
            created_by_membership_id=other_tenant.membership_id,
        )
        evidence_version = EvidenceVersion(
            id=uuid4(),
            organization_id=other_tenant.organization_id,
            workspace_id=other_tenant.workspace_id,
            evidence_record_id=foreign_record.id,
            version_number=1,
            title="Our annual return is guaranteed at 12%.",
            extracted_text="Our annual return is guaranteed at 12%.",
            created_by_membership_id=other_tenant.membership_id,
            pending_reapproval=False,
        )
        session.add_all([policy_version, evidence_version])
        session.flush()
        foreign_policy.current_version_id = policy_version.id
        foreign_record.current_version_id = evidence_version.id
        session.commit()

    app = _submission_api(session_factory, _scope(tenant))
    with TestClient(app) as client:
        response = _post_submission(client, tenant)

    assert response.status_code == 201, response.text
    with session_factory() as session:
        run_id = UUID(response.json()["analysis_run_id"])
        findings = list(session.scalars(select(Finding).where(Finding.analysis_run_id == run_id)))
        candidates = list(
            session.scalars(
                select(EvidenceMatchCandidate).where(EvidenceMatchCandidate.analysis_run_id == run_id)
            )
        )
    assert findings
    assert all(finding.category != "Policy finding" for finding in findings)
    assert all(finding.category.startswith("Unverified") for finding in findings)
    assert candidates == []


def test_invalid_submission_does_not_create_analysis_run(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    app = _submission_api(session_factory, _scope(tenant))
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/organizations/{tenant.organization_id}/workspaces/{tenant.workspace_id}/submissions",
            json={"source_type": "text", "submitted_text": ""},
        )
    assert response.status_code == 422
