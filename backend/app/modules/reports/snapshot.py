"""Build immutable report snapshots from persisted analysis records."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_event
from app.models import (
    AnalysisRun,
    AnalysisStageResult,
    EvidenceMatchCandidate,
    EvidenceVersion,
    ExtractedClaim,
    Finding,
    Policy,
    PolicyVersion,
    Report,
    SubmissionVersion,
    WorkspaceMembership,
)
from app.modules.analysis.orchestrator import REQUIRED_STAGE_ORDER
from app.modules.reports.schemas import ReportPreview, ReportSnapshot
from app.modules.tenancy.schemas import TenantScope
from app.tenancy.context import TenantScope as AuditTenantScope


class ReportNotFound(ValueError):
    """No report source exists in the current tenant scope."""


class ReportNotEligible(ValueError):
    """The submission version has no complete successful analysis run."""


def _report_snapshot(
    db: Session,
    *,
    report_id: UUID,
    version: SubmissionVersion,
    run: AnalysisRun,
    generated_at: datetime,
) -> ReportSnapshot:
    claims = db.scalars(
        select(ExtractedClaim)
        .where(
            ExtractedClaim.analysis_run_id == run.id,
            ExtractedClaim.submission_version_id == version.id,
            ExtractedClaim.organization_id == version.organization_id,
            ExtractedClaim.workspace_id == version.workspace_id,
        )
        .order_by(ExtractedClaim.start_offset, ExtractedClaim.id)
    ).all()
    findings = db.scalars(
        select(Finding)
        .where(
            Finding.analysis_run_id == run.id,
            Finding.submission_version_id == version.id,
            Finding.organization_id == version.organization_id,
            Finding.workspace_id == version.workspace_id,
        )
        .order_by(Finding.created_at, Finding.id)
    ).all()

    evidence_ids = {finding.evidence_version_id for finding in findings if finding.evidence_version_id}
    evidence_versions = {
        row.id: row
        for row in db.scalars(
            select(EvidenceVersion).where(
                EvidenceVersion.id.in_(evidence_ids or {UUID(int=0)}),
                EvidenceVersion.organization_id == version.organization_id,
                EvidenceVersion.workspace_id == version.workspace_id,
            )
        ).all()
    }
    policy_ids = {finding.policy_version_id for finding in findings if finding.policy_version_id}
    policy_versions = {
        row.id: row
        for row in db.scalars(
            select(PolicyVersion).where(
                PolicyVersion.id.in_(policy_ids or {UUID(int=0)}),
                PolicyVersion.organization_id == version.organization_id,
                PolicyVersion.workspace_id == version.workspace_id,
            )
        ).all()
    }
    policy_names = {}
    if policy_versions:
        policy_names = {
            row.id: row.name
            for row in db.scalars(
                select(Policy).where(
                    Policy.id.in_({item.policy_id for item in policy_versions.values()}),
                    Policy.organization_id == version.organization_id,
                    Policy.workspace_id == version.workspace_id,
                )
            ).all()
        }

    match_rows = db.scalars(
        select(EvidenceMatchCandidate).where(
            EvidenceMatchCandidate.analysis_run_id == run.id,
            EvidenceMatchCandidate.submission_version_id == version.id,
            EvidenceMatchCandidate.organization_id == version.organization_id,
            EvidenceMatchCandidate.workspace_id == version.workspace_id,
        )
    ).all()
    eligibility_by_pair = {
        (row.claim_id, row.evidence_version_id): row.eligibility_snapshot for row in match_rows
    }
    claims_by_id = {claim.id: claim for claim in claims}

    report_findings = []
    for finding in findings:
        claim = claims_by_id.get(finding.claim_id)
        evidence = evidence_versions.get(finding.evidence_version_id)
        policy_version = policy_versions.get(finding.policy_version_id)
        evidence_reference = []
        if evidence is not None:
            evidence_reference.append({
                "evidence_record_id": str(evidence.evidence_record_id),
                "evidence_version_id": str(evidence.id),
                "title": evidence.title,
                "version_number": evidence.version_number,
                "valid_from": evidence.valid_from.isoformat() if evidence.valid_from else None,
                "valid_until": evidence.valid_until.isoformat() if evidence.valid_until else None,
                "eligibility_snapshot": eligibility_by_pair.get((finding.claim_id, evidence.id)),
            })
        policy_result = None
        if policy_version is not None:
            policy_result = {
                "policy_id": str(policy_version.policy_id),
                "policy_version_id": str(policy_version.id),
                "policy_name": policy_names.get(policy_version.policy_id),
                "rule_type": policy_version.rule_type,
                "rule_text": policy_version.rule_text,
                "status_snapshot": policy_version.status_snapshot,
            }
        report_findings.append({
            "finding_id": str(finding.id),
            "category": finding.category,
            "attention_label": finding.attention_label,
            "explanation": finding.explanation,
            "claim": ({
                "claim_id": str(claim.id),
                "text": claim.text_span,
                "start_offset": claim.start_offset,
                "end_offset": claim.end_offset,
                "candidate_kind": claim.candidate_kind,
            } if claim else None),
            "supporting_evidence": evidence_reference,
            "policy_result": policy_result,
        })

    supported_count = sum(f.category == "Supported match found" for f in findings)
    unverified_count = sum(f.category.startswith("Unverified") for f in findings)
    policy_count = sum(f.category == "Policy finding" for f in findings)
    counts = {
        "claims_analyzed": len(claims),
        "findings": len(findings),
        "supported_findings": supported_count,
        "unverified_findings": unverified_count,
        "policy_findings": policy_count,
    }
    summary = (
        f"Analysis completed for {len(claims)} extracted claims, producing "
        f"{len(findings)} findings: {supported_count} supported matches, "
        f"{unverified_count} unverified findings, and {policy_count} policy findings."
    )
    policy_stage = db.scalars(
        select(AnalysisStageResult).where(
            AnalysisStageResult.analysis_run_id == run.id,
            AnalysisStageResult.stage_key == "policy_evaluation",
            AnalysisStageResult.organization_id == version.organization_id,
            AnalysisStageResult.workspace_id == version.workspace_id,
        ).order_by(AnalysisStageResult.attempt_number.desc())
    ).first()
    limitations = [
        "The analysis does not emit calibrated confidence scores.",
        "The current finding taxonomy does not distinguish contradictory findings; no contradiction count is reported.",
        "The policy section records composed findings and stage status, not every non-triggered rule evaluation.",
        "This report summarizes automated analysis and does not represent a human approval, certification, or guarantee.",
    ]
    return ReportSnapshot(
        schema_version="1.0",
        report_id=str(report_id),
        report_version=1,
        submission_version_id=str(version.id),
        analysis_run_id=str(run.id),
        generated_at=generated_at,
        overall_analysis_status="Succeeded",
        executive_summary=summary,
        counts=counts,
        findings=report_findings,
        policy_evaluation={
            "stage_state": policy_stage.state if policy_stage else None,
            "policy_finding_count": policy_count,
        },
        limitations=limitations,
    )


def create_report_snapshot(
    db: Session,
    tenant_scope: TenantScope,
    *,
    submission_version_id: UUID,
    analysis_run_id: UUID,
) -> Report:
    """Create or return the immutable snapshot for one successful exact run."""
    version = db.scalar(
        select(SubmissionVersion).where(
            SubmissionVersion.id == submission_version_id,
            SubmissionVersion.organization_id == tenant_scope.organization_id,
            SubmissionVersion.workspace_id == tenant_scope.workspace_id,
        )
    )
    run = db.scalar(
        select(AnalysisRun).where(
            AnalysisRun.id == analysis_run_id,
            AnalysisRun.submission_version_id == submission_version_id,
            AnalysisRun.organization_id == tenant_scope.organization_id,
            AnalysisRun.workspace_id == tenant_scope.workspace_id,
        )
    )
    if version is None or run is None:
        raise ReportNotFound("Report source is not available in this workspace.")
    if run.overall_state != "Succeeded" or run.completed_at is None:
        raise ReportNotEligible("A report requires a completed, successful analysis run.")

    stages = db.scalars(
        select(AnalysisStageResult).where(
            AnalysisStageResult.analysis_run_id == run.id,
            AnalysisStageResult.organization_id == tenant_scope.organization_id,
            AnalysisStageResult.workspace_id == tenant_scope.workspace_id,
        )
    ).all()
    successful_stage_keys = {stage.stage_key for stage in stages if stage.is_required and stage.state == "Succeeded"}
    if not set(REQUIRED_STAGE_ORDER).issubset(successful_stage_keys):
        raise ReportNotEligible("Every required analysis stage must succeed before report generation.")

    existing = db.scalar(
        select(Report).where(
            Report.submission_version_id == version.id,
            Report.analysis_run_id == run.id,
            Report.organization_id == tenant_scope.organization_id,
            Report.workspace_id == tenant_scope.workspace_id,
        )
    )
    if existing is not None:
        return existing

    membership_id = db.scalar(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.organization_id == tenant_scope.organization_id,
            WorkspaceMembership.workspace_id == tenant_scope.workspace_id,
            WorkspaceMembership.user_id == tenant_scope.user_id,
            WorkspaceMembership.status == "active",
        )
    )
    if membership_id is None:
        raise ReportNotFound("An active workspace membership is required to create a report.")

    report_id = uuid4()
    generated_at = datetime.now(timezone.utc)
    snapshot = _report_snapshot(
        db,
        report_id=report_id,
        version=version,
        run=run,
        generated_at=generated_at,
    )
    report = Report(
        id=report_id,
        organization_id=tenant_scope.organization_id,
        workspace_id=tenant_scope.workspace_id,
        submission_version_id=version.id,
        analysis_run_id=run.id,
        report_version=1,
        content_snapshot=snapshot.model_dump(mode="json"),
        generated_at=generated_at,
    )
    try:
        db.add(report)
        db.flush()
        record_event(
            db,
            AuditTenantScope(tenant_scope.organization_id, tenant_scope.workspace_id, membership_id),
            actor_membership_id=membership_id,
            action_key="report.snapshot.created",
            target_type="report",
            target_id=report.id,
            safe_metadata={
                "submission_version_id": str(version.id),
                "analysis_run_id": str(run.id),
                "report_version": 1,
            },
        )
        db.commit()
        return report
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(Report).where(
                Report.submission_version_id == version.id,
                Report.analysis_run_id == run.id,
                Report.organization_id == tenant_scope.organization_id,
                Report.workspace_id == tenant_scope.workspace_id,
            )
        )
        if existing is not None:
            return existing
        raise
    except Exception:
        db.rollback()
        raise


def project_report_preview(report: Report, *, sample_size: int = 2) -> ReportPreview:
    """Project a limited preview solely from the persisted immutable snapshot."""
    if sample_size < 0 or sample_size > 2:
        raise ValueError("Preview sample size must be between zero and two findings.")
    snapshot = ReportSnapshot.model_validate(report.content_snapshot)
    finding_sample = [
        {
            "category": finding.category,
            "attention_label": finding.attention_label,
            "explanation_preview": (
                finding.explanation if len(finding.explanation) <= 160 else finding.explanation[:157] + "..."
            ),
        }
        for finding in snapshot.findings[:sample_size]
    ]
    return ReportPreview(
        report_id=snapshot.report_id,
        report_version=snapshot.report_version,
        submission_version_id=snapshot.submission_version_id,
        analysis_run_id=snapshot.analysis_run_id,
        generated_at=snapshot.generated_at,
        overall_analysis_status=snapshot.overall_analysis_status,
        executive_summary=snapshot.executive_summary,
        counts=snapshot.counts,
        finding_sample=finding_sample,
    )
