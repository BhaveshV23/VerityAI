"""Transactional review decisions and append-only finding dispositions."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import record_event
from app.models import (
    AnalysisRun,
    AnalysisStageResult,
    Finding,
    HumanDisposition,
    ReviewDecision,
    Submission,
    SubmissionVersion,
    WorkspaceMembership,
)
from app.modules.analysis.orchestrator import REQUIRED_STAGE_ORDER
from app.modules.reviews.schemas import (
    FindingDispositionCreate,
    FindingDispositionRecordCreate,
    FindingDispositionType,
    ReviewDecisionCreate,
)
from app.modules.tenancy.schemas import TenantScope
from app.tenancy.context import TenantScope as AuditTenantScope


ALLOWABLE_PARENT_STATES = {"Submitted", "In review"}
DISPOSITION_VALUES = frozenset({"resolved", "not_applicable", "acknowledged", "disputed"})
CLEAN_APPROVAL_DISPOSITIONS = frozenset({"resolved", "not_applicable"})
DISPOSITION_STATUS = {
    "resolved": "resolved",
    "not_applicable": "resolved",
    "acknowledged": "acknowledged",
    "disputed": "disputed",
}


@dataclass(frozen=True, slots=True)
class ReviewEligibility:
    latest_run: AnalysisRun | None
    analysis_ready: bool
    reason: str | None
    reason_code: str | None
    findings: tuple[Finding, ...]
    blocking_findings: tuple[Finding, ...]

    @property
    def can_clean_approve(self) -> bool:
        return self.analysis_ready and not self.blocking_findings

    @property
    def can_approve_with_exceptions(self) -> bool:
        return self.analysis_ready


def _bad_request(message: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"error": {"code": "INVALID_REVIEW_DECISION", "message": message}},
    )


def _approval_blocked(reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"error": {"code": "INVALID_REVIEW_DECISION", "reason": reason, "message": message}},
    )


def _active_membership_id(db: Session, tenant_scope: TenantScope) -> UUID:
    membership_id = db.scalar(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.organization_id == tenant_scope.organization_id,
            WorkspaceMembership.workspace_id == tenant_scope.workspace_id,
            WorkspaceMembership.user_id == tenant_scope.user_id,
            WorkspaceMembership.status == "active",
        )
    )
    if membership_id is None:
        raise HTTPException(status_code=403, detail="Reviewer is not an active workspace member.")
    return membership_id


def _lock_submission_for_version(
    db: Session,
    tenant_scope: TenantScope,
    submission_version: SubmissionVersion,
) -> Submission:
    """Serialize disposition writes and terminal decisions on the parent submission."""
    if (
        submission_version.organization_id != tenant_scope.organization_id
        or submission_version.workspace_id != tenant_scope.workspace_id
    ):
        raise HTTPException(status_code=404, detail="Submission version not found.")
    submission = db.scalar(
        select(Submission)
        .join(
            SubmissionVersion,
            (SubmissionVersion.submission_id == Submission.id)
            & (SubmissionVersion.organization_id == Submission.organization_id)
            & (SubmissionVersion.workspace_id == Submission.workspace_id),
        )
        .where(
            SubmissionVersion.id == submission_version.id,
            SubmissionVersion.organization_id == tenant_scope.organization_id,
            SubmissionVersion.workspace_id == tenant_scope.workspace_id,
            Submission.organization_id == tenant_scope.organization_id,
            Submission.workspace_id == tenant_scope.workspace_id,
        )
        .with_for_update(of=Submission)
    )
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission version not found.")
    if submission.current_status not in ALLOWABLE_PARENT_STATES:
        raise _bad_request("The parent submission is not in a reviewable state.")
    return submission


def _latest_run(db: Session, tenant_scope: TenantScope, version_id: UUID) -> AnalysisRun | None:
    return db.scalar(
        select(AnalysisRun)
        .where(
            AnalysisRun.submission_version_id == version_id,
            AnalysisRun.organization_id == tenant_scope.organization_id,
            AnalysisRun.workspace_id == tenant_scope.workspace_id,
        )
        .order_by(AnalysisRun.run_number.desc())
        .limit(1)
    )


def _analysis_readiness_reason(
    db: Session,
    tenant_scope: TenantScope,
    run: AnalysisRun | None,
) -> tuple[str | None, str | None]:
    if run is None:
        return "analysis_run_missing", "Approval is blocked because this submission version has no analysis run."
    stages = list(
        db.scalars(
            select(AnalysisStageResult).where(
                AnalysisStageResult.analysis_run_id == run.id,
                AnalysisStageResult.organization_id == tenant_scope.organization_id,
                AnalysisStageResult.workspace_id == tenant_scope.workspace_id,
            )
        )
    )
    stages_by_key = {stage.stage_key: stage for stage in stages}
    for stage_key in REQUIRED_STAGE_ORDER:
        stage = stages_by_key.get(stage_key)
        if stage is None or not stage.is_required:
            return "required_stage_missing", f"Approval is blocked because required analysis stage '{stage_key}' is missing."
        if stage.state == "Failed":
            return "required_stage_failed", f"Approval is blocked because required analysis stage '{stage_key}' failed."
        if stage.state == "Not run":
            return "required_stage_not_run", f"Approval is blocked because required analysis stage '{stage_key}' has not run."
        if stage.state != "Succeeded":
            return "analysis_incomplete", f"Approval is blocked because required analysis stage '{stage_key}' is incomplete."
    for stage in stages:
        if stage.is_required and stage.state != "Succeeded":
            reason = "required_stage_failed" if stage.state == "Failed" else (
                "required_stage_not_run" if stage.state == "Not run" else "analysis_incomplete"
            )
            return reason, f"Approval is blocked because required analysis stage '{stage.stage_key}' is not successful."
    if run.overall_state != "Succeeded":
        return "analysis_incomplete", "Approval is blocked because the latest analysis run is not successful."
    return None, None


def _dispositions_by_finding(
    db: Session,
    tenant_scope: TenantScope,
    finding_ids: Iterable[UUID],
) -> dict[UUID, list[HumanDisposition]]:
    ids = tuple(finding_ids)
    if not ids:
        return {}
    rows = db.scalars(
        select(HumanDisposition)
        .where(
            HumanDisposition.finding_id.in_(ids),
            HumanDisposition.organization_id == tenant_scope.organization_id,
            HumanDisposition.workspace_id == tenant_scope.workspace_id,
        )
        .order_by(HumanDisposition.finding_id, HumanDisposition.sequence_number)
    )
    result: dict[UUID, list[HumanDisposition]] = {}
    for row in rows:
        result.setdefault(row.finding_id, []).append(row)
    return result


def _resolution_status(
    finding: Finding,
    history: list[HumanDisposition],
) -> tuple[str | None, str, bool]:
    effective = history[-1].disposition if history else None
    if effective is None:
        return None, "open" if finding.is_unresolved else "resolved", finding.is_unresolved
    if effective not in DISPOSITION_STATUS:
        return effective, "legacy_unrecognized", finding.is_unresolved
    status = DISPOSITION_STATUS[effective]
    blocks = finding.is_unresolved and effective not in CLEAN_APPROVAL_DISPOSITIONS
    return effective, status, blocks


def get_finding_resolution(
    db: Session,
    tenant_scope: TenantScope,
    finding: Finding,
) -> dict:
    history = _dispositions_by_finding(db, tenant_scope, [finding.id]).get(finding.id, [])
    effective, status, blocks = _resolution_status(finding, history)
    return {
        "finding_id": finding.id,
        "original_is_unresolved": finding.is_unresolved,
        "effective_disposition": effective,
        "resolution_status": status,
        "blocks_clean_approval": blocks,
        "disposition_history": history,
    }


def get_finding_resolutions(
    db: Session,
    tenant_scope: TenantScope,
    findings: Iterable[Finding],
) -> dict[UUID, dict]:
    finding_rows = list(findings)
    histories = _dispositions_by_finding(db, tenant_scope, [row.id for row in finding_rows])
    result: dict[UUID, dict] = {}
    for finding in finding_rows:
        history = histories.get(finding.id, [])
        effective, status, blocks = _resolution_status(finding, history)
        result[finding.id] = {
            "finding_id": finding.id,
            "original_is_unresolved": finding.is_unresolved,
            "effective_disposition": effective,
            "resolution_status": status,
            "blocks_clean_approval": blocks,
            "disposition_history": history,
        }
    return result


def calculate_review_eligibility(
    db: Session,
    tenant_scope: TenantScope,
    submission_version: SubmissionVersion,
    *,
    lock_findings: bool = False,
) -> ReviewEligibility:
    """Single source for read-time and transaction-time approval eligibility."""
    if (
        submission_version.organization_id != tenant_scope.organization_id
        or submission_version.workspace_id != tenant_scope.workspace_id
    ):
        raise HTTPException(status_code=404, detail="Submission version not found.")
    run = _latest_run(db, tenant_scope, submission_version.id)
    reason_code, reason = _analysis_readiness_reason(db, tenant_scope, run)
    statement = select(Finding).where(
        Finding.analysis_run_id == run.id if run is not None else Finding.id == UUID(int=0),
        Finding.submission_version_id == submission_version.id,
        Finding.organization_id == tenant_scope.organization_id,
        Finding.workspace_id == tenant_scope.workspace_id,
    ).order_by(Finding.created_at, Finding.id)
    if lock_findings:
        statement = statement.with_for_update()
    findings = tuple(db.scalars(statement))
    resolutions = get_finding_resolutions(db, tenant_scope, findings)
    blocking = tuple(
        finding for finding in findings
        if resolutions[finding.id]["blocks_clean_approval"]
    )
    return ReviewEligibility(run, reason is None, reason, reason_code, findings, blocking)


def _append_disposition(
    db: Session,
    tenant_scope: TenantScope,
    *,
    finding: Finding,
    membership_id: UUID,
    disposition: FindingDispositionType,
    rationale: str,
    sequence_number: int | None = None,
) -> HumanDisposition:
    if disposition not in DISPOSITION_VALUES:
        raise _bad_request("The finding disposition is not supported.")
    if not rationale.strip():
        raise _bad_request("A non-empty rationale is required for every finding disposition.")
    if sequence_number is None:
        previous = db.scalar(
            select(func.max(HumanDisposition.sequence_number)).where(
                HumanDisposition.finding_id == finding.id,
                HumanDisposition.organization_id == tenant_scope.organization_id,
                HumanDisposition.workspace_id == tenant_scope.workspace_id,
            )
        )
        sequence_number = (previous or 0) + 1
    row = HumanDisposition(
        id=uuid4(),
        organization_id=tenant_scope.organization_id,
        workspace_id=tenant_scope.workspace_id,
        finding_id=finding.id,
        sequence_number=sequence_number,
        analysis_run_id=finding.analysis_run_id,
        submission_version_id=finding.submission_version_id,
        reviewer_membership_id=membership_id,
        disposition=disposition,
        rationale=rationale.strip(),
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    record_event(
        db,
        AuditTenantScope(
            organization_id=tenant_scope.organization_id,
            workspace_id=tenant_scope.workspace_id,
            membership_id=membership_id,
        ),
        actor_membership_id=membership_id,
        action_key="review.finding_disposition.recorded",
        target_type="human_disposition",
        target_id=row.id,
        safe_metadata={
            "finding_id": str(finding.id),
            "submission_version_id": str(finding.submission_version_id),
            "analysis_run_id": str(finding.analysis_run_id),
            "disposition": disposition,
            "rationale": rationale.strip(),
            "sequence_number": sequence_number,
        },
    )
    return row


def record_finding_disposition(
    db: Session,
    tenant_scope: TenantScope,
    finding_id: UUID,
    payload: FindingDispositionRecordCreate,
) -> HumanDisposition:
    """Append one reviewer disposition without mutating its automated finding."""
    try:
        if "review.decide" not in tenant_scope.permissions:
            raise HTTPException(status_code=403, detail="Permission 'review.decide' required")
        membership_id = _active_membership_id(db, tenant_scope)
        version = db.scalar(
            select(SubmissionVersion).where(
                SubmissionVersion.id == payload.submission_version_id,
                SubmissionVersion.organization_id == tenant_scope.organization_id,
                SubmissionVersion.workspace_id == tenant_scope.workspace_id,
            )
        )
        if version is None:
            raise HTTPException(status_code=404, detail="Finding not found.")
        _lock_submission_for_version(db, tenant_scope, version)
        latest_run = _latest_run(db, tenant_scope, version.id)
        if latest_run is None or latest_run.id != payload.analysis_run_id:
            raise HTTPException(status_code=409, detail="The finding must belong to the latest analysis run for this version.")
        finding = db.scalar(
            select(Finding)
            .where(
                Finding.id == finding_id,
                Finding.analysis_run_id == payload.analysis_run_id,
                Finding.submission_version_id == payload.submission_version_id,
                Finding.organization_id == tenant_scope.organization_id,
                Finding.workspace_id == tenant_scope.workspace_id,
            )
            .with_for_update()
        )
        if finding is None:
            raise HTTPException(status_code=404, detail="Finding not found.")
        row = _append_disposition(
            db,
            tenant_scope,
            finding=finding,
            membership_id=membership_id,
            disposition=payload.disposition,
            rationale=payload.rationale,
        )
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        raise


def get_review_eligibility(
    db: Session,
    tenant_scope: TenantScope,
    submission_version: SubmissionVersion,
) -> dict:
    eligibility = calculate_review_eligibility(db, tenant_scope, submission_version)
    clean_reason = eligibility.reason
    if clean_reason is None and eligibility.blocking_findings:
        clean_reason = (
            f"Clean approval is blocked by {len(eligibility.blocking_findings)} finding(s) without "
            "an effective resolved or not_applicable disposition."
        )
    return {
        "submission_version_id": submission_version.id,
        "analysis_run_id": eligibility.latest_run.id if eligibility.latest_run else None,
        "analysis_status": eligibility.latest_run.overall_state if eligibility.latest_run else None,
        "can_clean_approve": eligibility.can_clean_approve,
        "can_approve_with_exceptions": eligibility.can_approve_with_exceptions,
        "clean_approval_reason": clean_reason,
        "exception_approval_reason": eligibility.reason,
        "blocking_finding_ids": [row.id for row in eligibility.blocking_findings],
    }


def record_review_decision(
    db: Session,
    tenant_scope: TenantScope,
    submission_version: SubmissionVersion,
    payload: ReviewDecisionCreate,
) -> ReviewDecision:
    """Revalidate eligibility and persist dispositions/decision atomically."""
    try:
        if "review.decide" not in tenant_scope.permissions:
            raise HTTPException(status_code=403, detail="Permission 'review.decide' required")
        membership_id = _active_membership_id(db, tenant_scope)
        submission = _lock_submission_for_version(db, tenant_scope, submission_version)
        latest_run = _latest_run(db, tenant_scope, submission_version.id)

        eligibility: ReviewEligibility | None = None
        if payload.decision in {"Approved", "Approved with documented exceptions"}:
            eligibility = calculate_review_eligibility(
                db,
                tenant_scope,
                submission_version,
                lock_findings=True,
            )
            if not eligibility.analysis_ready:
                raise _approval_blocked(eligibility.reason_code or "analysis_incomplete", eligibility.reason or "Analysis is incomplete.")
            latest_run = eligibility.latest_run

        if payload.decision == "Approved" and eligibility and eligibility.blocking_findings:
            raise _approval_blocked(
                "unresolved_findings",
                "Clean approval is blocked while unresolved findings lack a resolved or not_applicable disposition.",
            )

        if payload.decision == "Approved with documented exceptions":
            if not payload.rationale:
                raise _bad_request("A rationale is required for approval with documented exceptions.")
            assert eligibility is not None and latest_run is not None
            blocking_ids = {finding.id for finding in eligibility.blocking_findings}
            dispositions_by_finding: dict[UUID, FindingDispositionCreate] = {}
            for disposition in payload.dispositions:
                if disposition.finding_id in dispositions_by_finding:
                    raise _bad_request("Each unresolved finding may have only one disposition.")
                dispositions_by_finding[disposition.finding_id] = disposition
            if set(dispositions_by_finding) != blocking_ids:
                raise _bad_request("Every unresolved finding must have exactly one disposition and rationale.")
            histories = _dispositions_by_finding(db, tenant_scope, blocking_ids)
            findings_by_id = {finding.id: finding for finding in eligibility.blocking_findings}
            for finding_id in sorted(blocking_ids, key=str):
                disposition = dispositions_by_finding[finding_id]
                prior_count = len(histories.get(finding_id, []))
                _append_disposition(
                    db,
                    tenant_scope,
                    finding=findings_by_id[finding_id],
                    membership_id=membership_id,
                    disposition=disposition.disposition,
                    rationale=disposition.rationale,
                    sequence_number=prior_count + 1,
                )
        elif payload.decision in {"Rejected", "Changes requested"} and not payload.rationale:
            raise _bad_request("A non-empty rationale is required for this decision.")

        decision = ReviewDecision(
            id=uuid4(),
            organization_id=tenant_scope.organization_id,
            workspace_id=tenant_scope.workspace_id,
            submission_version_id=submission_version.id,
            reviewer_membership_id=membership_id,
            decision=payload.decision,
            rationale=payload.rationale,
        )
        db.add(decision)
        submission.current_status = payload.decision
        db.flush()
        record_event(
            db,
            AuditTenantScope(
                organization_id=tenant_scope.organization_id,
                workspace_id=tenant_scope.workspace_id,
                membership_id=membership_id,
            ),
            actor_membership_id=membership_id,
            action_key="review.decision.recorded",
            target_type="review_decision",
            target_id=decision.id,
            safe_metadata={"decision": payload.decision, "submission_version_id": str(submission_version.id)},
        )
        db.commit()
        return decision
    except Exception:
        db.rollback()
        raise
