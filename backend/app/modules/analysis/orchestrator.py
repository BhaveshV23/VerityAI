"""Synchronous, stage-tracked analysis pipeline skeleton."""

from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisRun,
    AnalysisStageResult,
    ExtractedClaim,
    SubmissionVersion,
    SubmissionVersionArtifact,
)
from app.modules.analysis.adapters.ai_adapter import extract_claims
from app.modules.analysis.stages.finding_composition import compose_findings
from app.modules.analysis.stages.policy_evaluation import evaluate_policies
from app.modules.analysis.stages.retrieval import retrieve_evidence_for_claims
from app.modules.tenancy.schemas import TenantScope


CLAIM_EXTRACTION_STAGE = "claim_extraction"
EVIDENCE_RETRIEVAL_STAGE = "evidence_retrieval"
POLICY_EVALUATION_STAGE = "policy_evaluation"
FINDING_COMPOSITION_STAGE = "finding_composition"
REQUIRED_STAGE_ORDER = (
    CLAIM_EXTRACTION_STAGE,
    EVIDENCE_RETRIEVAL_STAGE,
    POLICY_EVALUATION_STAGE,
    FINDING_COMPOSITION_STAGE,
)


def _commit(db: Session) -> None:
    """Commit one durable orchestration boundary."""
    db.commit()


def _mark_stage_failed(
    db: Session,
    *,
    run_id: UUID,
    stage_id: UUID,
    safe_message: str,
    error_code: str,
) -> AnalysisRun:
    """Persist the failed stage, dependent skipped stages, and incomplete run."""
    db.rollback()
    failed_stage = db.get(AnalysisStageResult, stage_id)
    if failed_stage is None:
        raise RuntimeError("Analysis stage disappeared while recording its failure.")
    incomplete_run = db.get(AnalysisRun, run_id)
    if incomplete_run is None:
        raise RuntimeError("Analysis run disappeared while recording its failure.")

    now = datetime.now(timezone.utc)
    failed_stage.state = "Failed"
    failed_stage.completed_at = now
    failed_stage.error_message = safe_message
    failed_stage.safe_error_code = error_code
    failed_stage.safe_error_message = safe_message
    incomplete_run.overall_state = "Incomplete"
    incomplete_run.completed_at = now

    stage_index = REQUIRED_STAGE_ORDER.index(failed_stage.stage_key)
    for skipped_stage_key in REQUIRED_STAGE_ORDER[stage_index + 1 :]:
        db.add(
            AnalysisStageResult(
                id=uuid4(),
                organization_id=incomplete_run.organization_id,
                workspace_id=incomplete_run.workspace_id,
                analysis_run_id=incomplete_run.id,
                stage_key=skipped_stage_key,
                attempt_number=1,
                state="Not run",
                is_required=True,
                dependency_reason=f"Not run because required stage '{failed_stage.stage_key}' failed.",
            )
        )
    _commit(db)
    return incomplete_run


def run_analysis_pipeline(
    db: Session,
    submission_version: SubmissionVersion,
    tenant_scope: TenantScope,
    *,
    analysis_text: str | None = None,
) -> AnalysisRun:
    """Run the four required analysis stages as durable, ordered stages."""
    if (
        submission_version.organization_id != tenant_scope.organization_id
        or submission_version.workspace_id != tenant_scope.workspace_id
    ):
        raise ValueError("Submission version is outside the requested tenant scope.")

    source_text = submission_version.submitted_text if submission_version.submitted_text is not None else analysis_text

    now = datetime.now(timezone.utc)
    prior_run_number = db.scalar(
        select(func.max(AnalysisRun.run_number)).where(
            AnalysisRun.submission_version_id == submission_version.id,
            AnalysisRun.organization_id == tenant_scope.organization_id,
            AnalysisRun.workspace_id == tenant_scope.workspace_id,
        )
    )
    run = AnalysisRun(
        id=uuid4(),
        organization_id=tenant_scope.organization_id,
        workspace_id=tenant_scope.workspace_id,
        submission_version_id=submission_version.id,
        run_number=(prior_run_number or 0) + 1,
        overall_state="Running",
        started_at=now,
    )
    db.add(run)
    db.flush()
    if submission_version.source_type in {"pdf", "docx"} and source_text is not None:
        db.add(SubmissionVersionArtifact(
            organization_id=tenant_scope.organization_id,
            workspace_id=tenant_scope.workspace_id,
            submission_version_id=submission_version.id,
            analysis_run_id=run.id,
            artifact_kind="document_extracted_text",
            normalized_text=source_text,
            checksum=sha256(source_text.encode("utf-8")).hexdigest(),
        ))
    _commit(db)

    extraction_stage = AnalysisStageResult(
        id=uuid4(),
        organization_id=tenant_scope.organization_id,
        workspace_id=tenant_scope.workspace_id,
        analysis_run_id=run.id,
        stage_key=CLAIM_EXTRACTION_STAGE,
        attempt_number=1,
        state="Running",
        started_at=datetime.now(timezone.utc),
        input_reference=f"submission_version:{submission_version.id}",
    )
    db.add(extraction_stage)
    db.flush()
    extraction_stage_id = extraction_stage.id
    _commit(db)

    claim_rows: list[ExtractedClaim] = []
    try:
        if source_text is None:
            raise ValueError("Text extraction is unavailable for this submission source.")
        results = extract_claims(source_text)
        for claim in results:
            claim_row = ExtractedClaim(
                id=uuid4(),
                organization_id=tenant_scope.organization_id,
                workspace_id=tenant_scope.workspace_id,
                analysis_run_id=run.id,
                submission_version_id=submission_version.id,
                stage_result_id=extraction_stage_id,
                text_span=claim["text"],
                start_offset=claim["start_offset"],
                end_offset=claim["end_offset"],
                candidate_kind=claim["candidate_kind"],
            )
            claim_rows.append(claim_row)
            db.add(claim_row)
        db.flush()
        active_stage = db.get(AnalysisStageResult, extraction_stage_id)
        assert active_stage is not None
        active_stage.state = "Succeeded"
        active_stage.completed_at = datetime.now(timezone.utc)
        active_stage.output_reference = f"extracted_claim_count:{len(claim_rows)}"
        _commit(db)
    except Exception:
        return _mark_stage_failed(
            db,
            run_id=run.id,
            stage_id=extraction_stage_id,
            safe_message="Claim extraction failed.",
            error_code="CLAIM_EXTRACTION_FAILED",
        )

    retrieval_stage = AnalysisStageResult(
        id=uuid4(),
        organization_id=tenant_scope.organization_id,
        workspace_id=tenant_scope.workspace_id,
        analysis_run_id=run.id,
        stage_key=EVIDENCE_RETRIEVAL_STAGE,
        attempt_number=1,
        state="Running",
        started_at=datetime.now(timezone.utc),
        input_reference=f"extracted_claim_count:{len(claim_rows)}",
    )
    db.add(retrieval_stage)
    db.flush()
    retrieval_stage_id = retrieval_stage.id
    _commit(db)

    try:
        candidates = retrieve_evidence_for_claims(db, tenant_scope, run, claim_rows)
        db.add_all(candidates)
        db.flush()
        active_stage = db.get(AnalysisStageResult, retrieval_stage_id)
        assert active_stage is not None
        active_stage.state = "Succeeded"
        active_stage.completed_at = datetime.now(timezone.utc)
        active_stage.output_reference = (
            "no_claims_no_search" if not claim_rows else f"candidate_count:{len(candidates)}"
        )
        _commit(db)
    except Exception:
        return _mark_stage_failed(
            db,
            run_id=run.id,
            stage_id=retrieval_stage_id,
            safe_message="Evidence retrieval failed.",
            error_code="EVIDENCE_RETRIEVAL_FAILED",
        )

    policy_stage = AnalysisStageResult(
        id=uuid4(),
        organization_id=tenant_scope.organization_id,
        workspace_id=tenant_scope.workspace_id,
        analysis_run_id=run.id,
        stage_key=POLICY_EVALUATION_STAGE,
        attempt_number=1,
        state="Running",
        started_at=datetime.now(timezone.utc),
        input_reference=f"submission_version:{submission_version.id}",
    )
    db.add(policy_stage)
    db.flush()
    policy_stage_id = policy_stage.id
    _commit(db)

    try:
        policy_violations = evaluate_policies(
            db,
            tenant_scope,
            run,
            source_text or "",
        )
        active_stage = db.get(AnalysisStageResult, policy_stage_id)
        assert active_stage is not None
        active_stage.state = "Succeeded"
        active_stage.completed_at = datetime.now(timezone.utc)
        active_stage.output_reference = f"policy_violation_count:{len(policy_violations)}"
        _commit(db)
    except Exception:
        return _mark_stage_failed(
            db,
            run_id=run.id,
            stage_id=policy_stage_id,
            safe_message="Policy evaluation failed.",
            error_code="POLICY_EVALUATION_FAILED",
        )

    finding_stage = AnalysisStageResult(
        id=uuid4(),
        organization_id=tenant_scope.organization_id,
        workspace_id=tenant_scope.workspace_id,
        analysis_run_id=run.id,
        stage_key=FINDING_COMPOSITION_STAGE,
        attempt_number=1,
        state="Running",
        started_at=datetime.now(timezone.utc),
        input_reference=f"claim_count:{len(claim_rows)}",
    )
    db.add(finding_stage)
    db.flush()
    finding_stage_id = finding_stage.id
    _commit(db)

    try:
        findings = compose_findings(
            db,
            tenant_scope,
            run,
            claim_rows,
            candidates,
            policy_violations,
        )
        db.add_all(findings)
        db.flush()
        active_stage = db.get(AnalysisStageResult, finding_stage_id)
        assert active_stage is not None
        active_stage.state = "Succeeded"
        active_stage.completed_at = datetime.now(timezone.utc)
        active_stage.output_reference = f"finding_count:{len(findings)}"
        _commit(db)
    except Exception:
        return _mark_stage_failed(
            db,
            run_id=run.id,
            stage_id=finding_stage_id,
            safe_message="Finding composition failed.",
            error_code="FINDING_COMPOSITION_FAILED",
        )

    succeeded_run = db.get(AnalysisRun, run.id)
    assert succeeded_run is not None
    succeeded_run.overall_state = "Succeeded"
    succeeded_run.completed_at = datetime.now(timezone.utc)
    _commit(db)
    return succeeded_run
