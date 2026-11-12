"""Combine Gemini prose with facts copied from the immutable report snapshot."""

from dataclasses import dataclass
from datetime import datetime, timezone

from app.modules.reports.detailed_schemas import DetailedClaimAnalysis, DetailedNarrativeDraft, DetailedReport
from app.modules.reports.narrative import _validate_draft, _validate_snapshot
from app.modules.reports.schemas import ReportSnapshot


METHODOLOGY = (
    "VerityAI extracts claims with AI assistance, retrieves evidence using deterministic eligibility rules, "
    "and evaluates configured policies in backend analysis stages. Finding statuses, counts, evidence references, "
    "and policy results in this report come from the saved verification snapshot. Gemini adds explanatory prose "
    "and recommendations only; it does not determine or change verification outcomes. Automated analysis is not "
    "a human approval, certification, or guarantee."
)


@dataclass(frozen=True, slots=True)
class ReportContext:
    organization_name: str
    workspace_name: str
    submission_id: str


def compose_detailed_report(
    snapshot: ReportSnapshot,
    draft: DetailedNarrativeDraft,
    context: ReportContext,
    *,
    generated_at: datetime | None = None,
) -> DetailedReport:
    _validate_snapshot(snapshot)
    _validate_draft(snapshot, draft)
    narrative_by_finding = {item.finding_id: item for item in draft.claim_analyses}
    claims: list[DetailedClaimAnalysis] = []
    appendix = []
    for finding in snapshot.findings:
        claim = finding.claim or {}
        claim_description = claim.get("text") or "No extracted claim was linked to this finding."
        narrative = narrative_by_finding[finding.finding_id]
        claims.append(DetailedClaimAnalysis(
            finding_id=finding.finding_id,
            claim_description=claim_description,
            verification_status=finding.category,
            deterministic_explanation=finding.explanation,
            ai_analysis=narrative.analysis,
            ai_limitations=narrative.limitations,
            supporting_evidence=finding.supporting_evidence,
            policy_result=finding.policy_result,
        ))
        appendix.append({
            "finding_id": finding.finding_id,
            "claim_description": claim_description,
            "verification_status": finding.category,
            "evidence_references": finding.supporting_evidence,
        })
    return DetailedReport(
        schema_version="1.0",
        report_id=snapshot.report_id,
        report_version=snapshot.report_version,
        submission_version_id=snapshot.submission_version_id,
        analysis_run_id=snapshot.analysis_run_id,
        snapshot_generated_at=snapshot.generated_at,
        generated_at=generated_at or datetime.now(timezone.utc),
        organization_name=context.organization_name,
        workspace_name=context.workspace_name,
        submission_id=context.submission_id,
        executive_summary=draft.executive_summary,
        verification_overview=draft.verification_overview,
        counts=snapshot.counts,
        policy_evaluation=snapshot.policy_evaluation,
        coverage_limitations=snapshot.limitations,
        claim_analyses=claims,
        risk_assessment=draft.risk_assessment,
        recommendations=draft.recommendations,
        methodology=METHODOLOGY,
        evidence_appendix=appendix,
    )


def validate_detailed_report_against_snapshot(detailed: DetailedReport, snapshot: ReportSnapshot) -> None:
    """Reject persisted output whose deterministic facts differ from its source snapshot."""
    if (
        detailed.report_id != snapshot.report_id
        or detailed.report_version != snapshot.report_version
        or detailed.submission_version_id != snapshot.submission_version_id
        or detailed.analysis_run_id != snapshot.analysis_run_id
        or detailed.snapshot_generated_at != snapshot.generated_at
        or detailed.counts != snapshot.counts
        or detailed.policy_evaluation != snapshot.policy_evaluation
        or detailed.coverage_limitations != snapshot.limitations
        or detailed.methodology != METHODOLOGY
        or len(detailed.claim_analyses) != len(snapshot.findings)
        or len(detailed.evidence_appendix) != len(snapshot.findings)
    ):
        raise ValueError("Detailed report does not match the immutable verification snapshot.")
    for report_claim, finding, appendix in zip(
        detailed.claim_analyses, snapshot.findings, detailed.evidence_appendix, strict=True,
    ):
        expected_claim = (finding.claim or {}).get("text") or "No extracted claim was linked to this finding."
        if (
            report_claim.finding_id != finding.finding_id
            or report_claim.claim_description != expected_claim
            or report_claim.verification_status != finding.category
            or report_claim.deterministic_explanation != finding.explanation
            or report_claim.supporting_evidence != finding.supporting_evidence
            or report_claim.policy_result != finding.policy_result
            or appendix != {
                "finding_id": finding.finding_id,
                "claim_description": expected_claim,
                "verification_status": finding.category,
                "evidence_references": finding.supporting_evidence,
            }
        ):
            raise ValueError("Detailed report facts do not match the immutable verification snapshot.")
