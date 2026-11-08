"""Deterministic evidence eligibility rules."""

from datetime import date, datetime
from typing import Any

from app.models import EvidenceRecord, EvidenceVersion


def derive_evidence_eligibility(
    record: EvidenceRecord,
    version: EvidenceVersion,
    analysis_time: datetime,
) -> dict[str, Any]:
    """Evaluate an exact evidence version at a supplied analysis timestamp.

    Validity bounds are calendar dates in the data model, so a timestamp is
    evaluated against its calendar date. Missing bounds disclose unknown
    freshness without independently making approved evidence ineligible.
    """
    evaluated_date: date = analysis_time.date()
    valid_until = version.valid_until
    valid_from = version.valid_from
    is_expired = valid_until is not None and valid_until < evaluated_date
    not_yet_valid = valid_from is not None and valid_from > evaluated_date
    freshness_unknown = valid_from is None or valid_until is None
    conflict_flagged = version.has_open_manual_conflict

    is_eligible = (
        record.primary_lifecycle_state == "Approved"
        and (record.current_version_id is None or record.current_version_id == version.id)
        and not record.is_inactive
        and not conflict_flagged
        and not is_expired
        and not not_yet_valid
        and not version.is_pending_reapproval
    )
    return {
        "is_eligible": is_eligible,
        "freshness_unknown": freshness_unknown,
        "is_expired": is_expired,
        "not_yet_valid": not_yet_valid,
        "analysis_time": analysis_time,
    }
