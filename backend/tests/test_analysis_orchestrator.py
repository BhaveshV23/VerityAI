from sqlalchemy import select

from app.models import AnalysisRun, AnalysisStageResult, ExtractedClaim
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


def _make_submission(session, tenant, source: str):
    return create_submission_version(
        session,
        _scope(tenant),
        submitter_id=tenant.user_id,
        source_type="text",
        submitted_text=source,
    )


def test_pipeline_runs_deterministic_claim_extraction(session_factory, tenant_pair, monkeypatch):
    monkeypatch.setenv("AI_ENABLED", "false")
    tenant, _ = tenant_pair
    source = "Our plan is guaranteed to save 20%. The annual fee is $30. Ordinary description."

    with session_factory() as session:
        submission_version = _make_submission(session, tenant, source)
        run = run_analysis_pipeline(session, submission_version, _scope(tenant))
        stage = session.scalar(
            select(AnalysisStageResult).where(
                AnalysisStageResult.analysis_run_id == run.id,
                AnalysisStageResult.stage_key == "claim_extraction",
            )
        )
        claims = list(
            session.scalars(
                select(ExtractedClaim)
                .where(ExtractedClaim.analysis_run_id == run.id)
                .order_by(ExtractedClaim.start_offset)
            )
        )

    assert run.overall_state == "Succeeded"
    assert run.started_at is not None and run.completed_at is not None
    assert stage is not None
    assert stage.stage_key == "claim_extraction"
    assert stage.state == "Succeeded"
    assert len(claims) == 2
    assert [claim.text_span for claim in claims] == [
        "Our plan is guaranteed to save 20%.",
        "The annual fee is $30.",
    ]
    assert claims[0].candidate_kind == "promotional"
    assert source[claims[0].start_offset : claims[0].end_offset] == claims[0].text_span


def test_failed_claim_stage_is_safely_recorded_and_run_is_incomplete(
    session_factory, tenant_pair, monkeypatch
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        submission_version = _make_submission(session, tenant, "A claim with 12 units.")

        def fail_extraction(_text: str):
            raise RuntimeError("sensitive input should not be stored")

        monkeypatch.setattr("app.modules.analysis.orchestrator.extract_claims", fail_extraction)
        run = run_analysis_pipeline(session, submission_version, _scope(tenant))
        stage = session.scalar(
            select(AnalysisStageResult).where(AnalysisStageResult.analysis_run_id == run.id)
        )

    assert run.overall_state == "Incomplete"
    assert run.completed_at is not None
    assert stage is not None
    assert stage.state == "Failed"
    assert stage.error_message == "Claim extraction failed."
    assert "sensitive input" not in stage.error_message
