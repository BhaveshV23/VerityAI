from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.models import EvidenceRecord, EvidenceVersion
from app.modules.evidence.services import derive_evidence_eligibility


ANALYSIS_TIME = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def make_record(state: str = "Approved", *, inactive: bool = False) -> EvidenceRecord:
    return EvidenceRecord(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        owner_membership_id=uuid4(),
        primary_lifecycle_state=state,
        is_inactive=inactive,
    )


def make_version(**overrides) -> EvidenceVersion:
    values = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "workspace_id": uuid4(),
        "evidence_record_id": uuid4(),
        "version_number": 1,
        "title": "Synthetic evidence",
        "created_by_membership_id": uuid4(),
        "valid_from": None,
        "valid_until": None,
        "pending_reapproval": False,
    }
    values.update(overrides)
    return EvidenceVersion(**values)


def test_approved_evidence_with_missing_dates_is_eligible_but_unknown():
    result = derive_evidence_eligibility(make_record(), make_version(), ANALYSIS_TIME)

    assert result["is_eligible"] is True
    assert result["freshness_unknown"] is True
    assert result["is_expired"] is False
    assert result["not_yet_valid"] is False
    assert result["analysis_time"] == ANALYSIS_TIME


def test_approved_evidence_is_ineligible_after_expiry():
    version = make_version(valid_from=date(2026, 1, 1), valid_until=date(2026, 11, 6))

    result = derive_evidence_eligibility(make_record(), version, ANALYSIS_TIME)

    assert result["is_eligible"] is False
    assert result["is_expired"] is True


def test_approved_evidence_pending_reapproval_is_ineligible():
    result = derive_evidence_eligibility(
        make_record(), make_version(pending_reapproval=True), ANALYSIS_TIME
    )

    assert result["is_eligible"] is False


def test_superseded_versions_are_not_eligible_for_new_analysis():
    current = make_version()
    prior = make_version(evidence_record_id=current.evidence_record_id)
    record = make_record()
    record.current_version_id = current.id

    assert derive_evidence_eligibility(record, prior, ANALYSIS_TIME)["is_eligible"] is False
    assert derive_evidence_eligibility(record, current, ANALYSIS_TIME)["is_eligible"] is True


@pytest.mark.parametrize("state", ["Uploaded", "Reviewed"])
def test_unapproved_primary_states_are_ineligible(state: str):
    result = derive_evidence_eligibility(make_record(state), make_version(), ANALYSIS_TIME)

    assert result["is_eligible"] is False


def test_open_manual_conflict_blocks_eligibility():
    from app.models import EvidenceConflict, EvidenceConflictSource

    record_id = uuid4()
    version = make_version(evidence_record_id=record_id)
    conflict = EvidenceConflict(
        id=uuid4(),
        organization_id=version.organization_id,
        workspace_id=version.workspace_id,
        reported_by_membership_id=uuid4(),
        state="open",
    )
    source = EvidenceConflictSource(
        id=uuid4(),
        organization_id=version.organization_id,
        workspace_id=version.workspace_id,
        conflict_id=conflict.id,
        evidence_record_id=record_id,
        evidence_version_id=version.id,
        conflict=conflict,
    )
    version.conflict_sources = [source]

    result = derive_evidence_eligibility(make_record(), version, ANALYSIS_TIME)

    assert result["is_eligible"] is False
