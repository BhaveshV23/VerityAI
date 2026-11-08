from datetime import date, timedelta
from sqlalchemy import select
from uuid import uuid4

from app.models import (
    AnalysisStageResult,
    EvidenceMatchCandidate,
    EvidenceRecord,
    EvidenceVersion,
    Finding,
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


def _create_version(
    session, tenant, record_id, version_number, *, title, extracted_text=None,
    valid_from=None, valid_until=None,
):
    version = EvidenceVersion(
        id=uuid4(),
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
        evidence_record_id=record_id,
        version_number=version_number,
        title=title,
        extracted_text=extracted_text,
        valid_from=valid_from,
        valid_until=valid_until,
        created_by_membership_id=tenant.membership_id,
        pending_reapproval=False,
    )
    session.add(version)
    session.flush()
    record = session.get(EvidenceRecord, record_id)
    assert record is not None
    record.current_version_id = version.id
    return version


def _submit_and_analyze(session, tenant, source):
    scope = _scope(tenant)
    submission_version = create_submission_version(
        session,
        scope,
        submitter_id=tenant.user_id,
        source_type="text",
        submitted_text=source,
    )
    return run_analysis_pipeline(session, submission_version, scope)


def test_empty_claims_complete_retrieval_stage_without_search(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    with session_factory() as session:
        run = _submit_and_analyze(session, tenant, "Plain narrative with no claim-like content.")
        retrieval_stage = session.scalar(
            select(AnalysisStageResult).where(
                AnalysisStageResult.analysis_run_id == run.id,
                AnalysisStageResult.stage_key == "evidence_retrieval",
            )
        )

    assert run.overall_state == "Succeeded"
    assert retrieval_stage is not None
    assert retrieval_stage.state == "Succeeded"
    assert retrieval_stage.output_reference == "no_claims_no_search"


def test_matching_approved_evidence_persists_candidate_and_eligibility_snapshot(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    source = "The annual fee is 2%."
    with session_factory() as session:
        record = session.get(EvidenceRecord, tenant.evidence_record_id)
        assert record is not None
        record.primary_lifecycle_state = "Approved"
        _create_version(
            session,
            tenant,
            record.id,
            1,
            title="Annual fee: 2%",
            extracted_text="The annual fee is 2%.",
        )
        session.flush()

        run = _submit_and_analyze(session, tenant, source)
        candidate = session.scalar(
            select(EvidenceMatchCandidate).where(EvidenceMatchCandidate.analysis_run_id == run.id)
        )

    assert run.overall_state == "Succeeded"
    assert candidate is not None
    assert candidate.eligibility_snapshot["is_eligible"] is True
    assert candidate.eligibility_snapshot["freshness_unknown"] is True
    assert isinstance(candidate.eligibility_snapshot["analysis_time"], str)
    assert candidate.candidate_ordering == 1
    assert "ordered claim word sequence" in candidate.match_explanation


def test_relevant_approved_evidence_matches_across_pdf_punctuation_and_line_breaks(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    source = (
        "Generated and validated 259,589 synthetic records across 9 datasets, "
        "checking data integrity and cross-dataset consistency."
    )
    extracted = (
        "Professional experience\nGenerated and validated 259,589 synthetic records across 9 datasets;\n"
        "checking data integrity and cross-dataset consistency."
    )
    with session_factory() as session:
        record = session.get(EvidenceRecord, tenant.evidence_record_id)
        assert record is not None
        record.primary_lifecycle_state = "Approved"
        _create_version(
            session, tenant, record.id, 1,
            title="Resume",
            extracted_text=extracted,
            valid_from=date.today() - timedelta(days=1),
            valid_until=date.today() + timedelta(days=1),
        )
        run = _submit_and_analyze(session, tenant, source)
        candidate = session.scalar(
            select(EvidenceMatchCandidate).where(EvidenceMatchCandidate.analysis_run_id == run.id)
        )
        finding = session.scalar(select(Finding).where(Finding.analysis_run_id == run.id))

    assert run.overall_state == "Succeeded"
    assert candidate is not None and candidate.eligibility_snapshot["is_eligible"] is True
    assert finding is not None
    assert finding.category == "Supported match found"
    assert finding.evidence_version_id == candidate.evidence_version_id
    assert finding.claim_id == candidate.claim_id
    assert finding.is_unresolved is True


def test_unrelated_approved_evidence_does_not_match_claim(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    source = "Generated and validated 259,589 synthetic records across 9 datasets, checking data integrity and cross-dataset consistency."
    with session_factory() as session:
        record = session.get(EvidenceRecord, tenant.evidence_record_id)
        assert record is not None
        record.primary_lifecycle_state = "Approved"
        _create_version(
            session, tenant, record.id, 1,
            title="Resume",
            extracted_text="Managed customer relationships and prepared monthly reports for a retail team.",
            valid_from=date.today() - timedelta(days=1),
            valid_until=date.today() + timedelta(days=1),
        )
        run = _submit_and_analyze(session, tenant, source)
        candidates = list(session.scalars(
            select(EvidenceMatchCandidate).where(EvidenceMatchCandidate.analysis_run_id == run.id)
        ))
        finding = session.scalar(select(Finding).where(Finding.analysis_run_id == run.id))
    assert candidates == []
    assert finding is not None and finding.category.startswith("Unverified")


def test_uploaded_evidence_with_matching_text_remains_ineligible(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    source = "The annual fee is 2%."
    with session_factory() as session:
        record = session.get(EvidenceRecord, tenant.evidence_record_id)
        assert record is not None
        record.primary_lifecycle_state = "Uploaded"
        _create_version(session, tenant, record.id, 1, title="Fee schedule", extracted_text=source)
        run = _submit_and_analyze(session, tenant, source)
        candidates = list(session.scalars(
            select(EvidenceMatchCandidate).where(EvidenceMatchCandidate.analysis_run_id == run.id)
        ))
    assert candidates == []


def test_expired_and_inactive_evidence_with_matching_text_remain_ineligible(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    source = "The annual fee is 2%."
    with session_factory() as session:
        for expired, inactive in ((True, False), (False, True)):
            record = EvidenceRecord(
                id=uuid4(),
                organization_id=tenant.organization_id,
                workspace_id=tenant.workspace_id,
                owner_membership_id=tenant.membership_id,
                primary_lifecycle_state="Approved",
                is_inactive=inactive,
            )
            session.add(record)
            session.flush()
            _create_version(
                session, tenant, record.id, 1,
                title="Fee schedule",
                extracted_text=source,
                valid_from=date.today() - timedelta(days=30),
                valid_until=date.today() - timedelta(days=1) if expired else date.today() + timedelta(days=30),
            )
        run = _submit_and_analyze(session, tenant, source)
        candidates = list(session.scalars(
            select(EvidenceMatchCandidate).where(EvidenceMatchCandidate.analysis_run_id == run.id)
        ))
    assert candidates == []


def test_extraction_failure_with_no_text_is_not_retrieved(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    source = "The annual fee is 2%."
    with session_factory() as session:
        record = session.get(EvidenceRecord, tenant.evidence_record_id)
        assert record is not None
        record.primary_lifecycle_state = "Approved"
        _create_version(session, tenant, record.id, 1, title="Fee schedule", extracted_text=None)
        run = _submit_and_analyze(session, tenant, source)
        candidates = list(session.scalars(
            select(EvidenceMatchCandidate).where(EvidenceMatchCandidate.analysis_run_id == run.id)
        ))
    assert candidates == []


def test_matching_foreign_tenant_evidence_is_not_retrieved(session_factory, tenant_pair):
    tenant, other_tenant = tenant_pair
    source = "The annual fee is 2%."
    with session_factory() as session:
        foreign_record = session.get(EvidenceRecord, other_tenant.evidence_record_id)
        assert foreign_record is not None
        foreign_record.primary_lifecycle_state = "Approved"
        _create_version(
            session, other_tenant, foreign_record.id, 1,
            title="Fee schedule", extracted_text=source,
        )
        run = _submit_and_analyze(session, tenant, source)
        candidates = list(session.scalars(
            select(EvidenceMatchCandidate).where(EvidenceMatchCandidate.analysis_run_id == run.id)
        ))
    assert candidates == []


def test_new_analysis_only_considers_current_evidence_version(session_factory, tenant_pair):
    tenant, _ = tenant_pair
    source = "The annual fee is 2%."
    with session_factory() as session:
        record = session.get(EvidenceRecord, tenant.evidence_record_id)
        assert record is not None
        record.primary_lifecycle_state = "Approved"
        old_version = _create_version(
            session, tenant, record.id, 1,
            title="Annual fee: 2%", extracted_text="The annual fee is 2%.",
        )
        current_version = _create_version(
            session, tenant, record.id, 2,
            title="Updated schedule", extracted_text="Current values are listed separately.",
        )
        session.flush()
        assert record.current_version_id == current_version.id

        run = _submit_and_analyze(session, tenant, source)
        candidates = list(session.scalars(
            select(EvidenceMatchCandidate).where(EvidenceMatchCandidate.analysis_run_id == run.id)
        ))

    assert old_version.id != current_version.id
    assert candidates == []


def test_uploaded_and_reviewed_evidence_are_excluded_from_search_results(
    session_factory, tenant_pair
):
    tenant, _ = tenant_pair
    source = "The annual fee is 2%."
    with session_factory() as session:
        for state in ("Uploaded", "Reviewed"):
            record = EvidenceRecord(
                id=uuid4(),
                organization_id=tenant.organization_id,
                workspace_id=tenant.workspace_id,
                owner_membership_id=tenant.membership_id,
                primary_lifecycle_state=state,
                is_inactive=False,
            )
            session.add(record)
            session.flush()
            _create_version(
                session,
                tenant,
                record.id,
                1,
                title="Annual fee: 2%",
                extracted_text="The annual fee is 2%.",
            )
        session.flush()

        run = _submit_and_analyze(session, tenant, source)
        candidates = list(
            session.scalars(
                select(EvidenceMatchCandidate).where(EvidenceMatchCandidate.analysis_run_id == run.id)
            )
        )

    assert run.overall_state == "Succeeded"
    assert candidates == []


def test_retrieval_failure_marks_stage_failed_and_run_incomplete(
    session_factory, tenant_pair, monkeypatch
):
    tenant, _ = tenant_pair
    with session_factory() as session:
        submission_version = create_submission_version(
            session,
            _scope(tenant),
            submitter_id=tenant.user_id,
            source_type="text",
            submitted_text="The annual fee is 2%.",
        )

        def fail_retrieval(*_args, **_kwargs):
            raise RuntimeError("database details must not be exposed")

        monkeypatch.setattr(
            "app.modules.analysis.orchestrator.retrieve_evidence_for_claims", fail_retrieval
        )
        run = run_analysis_pipeline(session, submission_version, _scope(tenant))
        retrieval_stage = session.scalar(
            select(AnalysisStageResult).where(
                AnalysisStageResult.analysis_run_id == run.id,
                AnalysisStageResult.stage_key == "evidence_retrieval",
            )
        )

    assert run.overall_state == "Incomplete"
    assert retrieval_stage is not None
    assert retrieval_stage.state == "Failed"
    assert retrieval_stage.error_message == "Evidence retrieval failed."
    assert "database details" not in retrieval_stage.error_message
