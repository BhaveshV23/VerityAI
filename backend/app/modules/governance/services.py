"""Tenant-scoped aggregation for the five workspace governance metrics."""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    EvidenceConflict,
    EvidenceConflictSource,
    EvidenceRecord,
    EvidenceVersion,
    Finding,
    ReviewDecision,
    SubmissionVersion,
)
from app.modules.tenancy.schemas import TenantScope


REVIEW_DECISIONS = (
    "Approved",
    "Approved with documented exceptions",
    "Changes requested",
    "Rejected",
)
UNVERIFIED_CATEGORY = "Unverified — no eligible approved evidence found"


def get_workspace_metrics(
    db: Session,
    tenant_scope: TenantScope,
    days: int = 30,
) -> dict[str, Any]:
    """Aggregate workspace governance counts for the requested recent period."""
    if days < 1:
        raise ValueError("days must be at least 1")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    organization_id = tenant_scope.organization_id
    workspace_id = tenant_scope.workspace_id

    submissions_count = db.scalar(
        select(func.count(func.distinct(SubmissionVersion.id))).where(
            SubmissionVersion.organization_id == organization_id,
            SubmissionVersion.workspace_id == workspace_id,
            SubmissionVersion.submitted_at > cutoff,
        )
    ) or 0
    review_decisions_count = db.scalar(
        select(func.count(func.distinct(ReviewDecision.id))).where(
            ReviewDecision.organization_id == organization_id,
            ReviewDecision.workspace_id == workspace_id,
            ReviewDecision.created_at > cutoff,
        )
    ) or 0
    unverified_claims_count = db.scalar(
        select(func.count(Finding.id)).where(
            Finding.organization_id == organization_id,
            Finding.workspace_id == workspace_id,
            Finding.category == UNVERIFIED_CATEGORY,
            Finding.created_at > cutoff,
        )
    ) or 0

    recurring_rows = db.execute(
        select(Finding.policy_version_id, func.count(Finding.id).label("finding_count"))
        .where(
            Finding.organization_id == organization_id,
            Finding.workspace_id == workspace_id,
            Finding.category == "Policy finding",
            Finding.policy_version_id.is_not(None),
            Finding.created_at > cutoff,
        )
        .group_by(Finding.policy_version_id)
        .having(func.count(Finding.id) >= 2)
        .order_by(Finding.policy_version_id)
    ).all()
    recurring_policy_findings = [
        {"policy_version_id": str(policy_version_id), "count": int(finding_count)}
        for policy_version_id, finding_count in recurring_rows
    ]

    decision_counts = dict(
        db.execute(
            select(ReviewDecision.decision, func.count(ReviewDecision.id))
            .where(
                ReviewDecision.organization_id == organization_id,
                ReviewDecision.workspace_id == workspace_id,
                ReviewDecision.created_at > cutoff,
            )
            .group_by(ReviewDecision.decision)
        ).all()
    )
    review_decision_trends = {
        decision: int(decision_counts.get(decision, 0)) for decision in REVIEW_DECISIONS
    }

    awaiting_review_count = db.scalar(
        select(func.count(EvidenceRecord.id)).where(
            EvidenceRecord.organization_id == organization_id,
            EvidenceRecord.workspace_id == workspace_id,
            EvidenceRecord.primary_lifecycle_state.in_(("Uploaded", "Reviewed")),
        )
    ) or 0
    inactive_count = db.scalar(
        select(func.count(EvidenceRecord.id)).where(
            EvidenceRecord.organization_id == organization_id,
            EvidenceRecord.workspace_id == workspace_id,
            EvidenceRecord.is_inactive.is_(True),
        )
    ) or 0
    # Evidence validity bounds are calendar dates in the persisted model.
    expired_count = db.scalar(
        select(func.count(EvidenceVersion.id)).where(
            EvidenceVersion.organization_id == organization_id,
            EvidenceVersion.workspace_id == workspace_id,
            EvidenceVersion.valid_until < datetime.now(timezone.utc).date(),
        )
    ) or 0
    conflict_flagged_count = db.scalar(
        select(func.count(func.distinct(EvidenceVersion.id)))
        .select_from(EvidenceVersion)
        .join(
            EvidenceConflictSource,
            (EvidenceConflictSource.evidence_version_id == EvidenceVersion.id)
            & (EvidenceConflictSource.evidence_record_id == EvidenceVersion.evidence_record_id)
            & (EvidenceConflictSource.organization_id == EvidenceVersion.organization_id)
            & (EvidenceConflictSource.workspace_id == EvidenceVersion.workspace_id),
        )
        .join(
            EvidenceConflict,
            (EvidenceConflict.id == EvidenceConflictSource.conflict_id)
            & (EvidenceConflict.organization_id == EvidenceConflictSource.organization_id)
            & (EvidenceConflict.workspace_id == EvidenceConflictSource.workspace_id),
        )
        .where(
            EvidenceVersion.organization_id == organization_id,
            EvidenceVersion.workspace_id == workspace_id,
            EvidenceConflict.state == "open",
        )
    ) or 0

    return {
        "period_days": days,
        "submissions_count": int(submissions_count),
        "review_decisions_count": int(review_decisions_count),
        "unverified_claims_count": int(unverified_claims_count),
        "recurring_policy_findings": recurring_policy_findings,
        "review_decision_trends": review_decision_trends,
        "evidence_attention": {
            "awaiting_review": int(awaiting_review_count),
            "inactive": int(inactive_count),
            "expired_versions": int(expired_count),
            "conflict_flagged_versions": int(conflict_flagged_count),
        },
    }
