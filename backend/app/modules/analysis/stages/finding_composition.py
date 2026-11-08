"""Compose human-review findings from claims, evidence matches, and policies."""

from uuid import uuid4

from app.models import AnalysisRun, EvidenceMatchCandidate, ExtractedClaim, Finding
from app.modules.tenancy.schemas import TenantScope


def compose_findings(
    db,
    tenant_scope: TenantScope,
    analysis_run: AnalysisRun,
    claims: list[ExtractedClaim],
    match_candidates: list[EvidenceMatchCandidate],
    policy_violations: list[dict],
) -> list[Finding]:
    """Build unsaved finding rows; the orchestrator persists them transactionally."""
    if (
        analysis_run.organization_id != tenant_scope.organization_id
        or analysis_run.workspace_id != tenant_scope.workspace_id
    ):
        raise ValueError("Analysis run is outside the requested tenant scope.")

    by_claim: dict[object, list[EvidenceMatchCandidate]] = {}
    for candidate in match_candidates:
        if (
            candidate.analysis_run_id != analysis_run.id
            or candidate.submission_version_id != analysis_run.submission_version_id
            or candidate.organization_id != tenant_scope.organization_id
            or candidate.workspace_id != tenant_scope.workspace_id
        ):
            raise ValueError("Evidence candidate is outside the requested analysis run or tenant scope.")
        by_claim.setdefault(candidate.claim_id, []).append(candidate)

    findings: list[Finding] = []
    for claim in claims:
        if (
            claim.analysis_run_id != analysis_run.id
            or claim.submission_version_id != analysis_run.submission_version_id
            or claim.organization_id != tenant_scope.organization_id
            or claim.workspace_id != tenant_scope.workspace_id
        ):
            raise ValueError("Claim is outside the requested analysis run or tenant scope.")
        matches = by_claim.get(claim.id, [])
        if not matches:
            findings.append(
                Finding(
                    id=uuid4(),
                    organization_id=tenant_scope.organization_id,
                    workspace_id=tenant_scope.workspace_id,
                    analysis_run_id=analysis_run.id,
                    submission_version_id=analysis_run.submission_version_id,
                    claim_id=claim.id,
                    category="Unverified — no eligible approved evidence found",
                    attention_label="unverified",
                    explanation="No eligible approved evidence version matched this claim.",
                    is_unresolved=True,
                )
            )
            continue

        for match in matches:
            findings.append(
                Finding(
                    id=uuid4(),
                    organization_id=tenant_scope.organization_id,
                    workspace_id=tenant_scope.workspace_id,
                    analysis_run_id=analysis_run.id,
                    submission_version_id=analysis_run.submission_version_id,
                    claim_id=claim.id,
                    category="Supported match found",
                    attention_label="supported",
                    explanation=match.match_explanation or "An eligible approved evidence version matched this claim.",
                    evidence_record_id=match.evidence_record_id,
                    evidence_version_id=match.evidence_version_id,
                    is_unresolved=True,
                )
            )

    for violation in policy_violations:
        policy_version_id = violation["policy_version_id"]
        policy_id = violation["policy_id"]
        findings.append(
            Finding(
                id=uuid4(),
                organization_id=tenant_scope.organization_id,
                workspace_id=tenant_scope.workspace_id,
                analysis_run_id=analysis_run.id,
                submission_version_id=analysis_run.submission_version_id,
                claim_id=None,
                category="Policy finding",
                attention_label="policy",
                explanation=violation["explanation"],
                policy_id=policy_id,
                policy_version_id=policy_version_id,
                is_unresolved=True,
            )
        )
    return findings
