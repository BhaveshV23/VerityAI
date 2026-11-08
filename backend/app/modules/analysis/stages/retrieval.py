"""Tenant-scoped retrieval of eligible evidence versions for extracted claims."""

from datetime import datetime, timezone
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AnalysisRun,
    EvidenceConflictSource,
    EvidenceMatchCandidate,
    EvidenceRecord,
    EvidenceVersion,
    ExtractedClaim,
)
from app.modules.evidence.services import derive_evidence_eligibility
from app.modules.tenancy.schemas import TenantScope


def _normalize_match_text(value: str) -> str:
    """Normalize punctuation and whitespace while preserving token order."""
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def retrieve_evidence_for_claims(
    db: Session,
    tenant_scope: TenantScope,
    analysis_run: AnalysisRun,
    claims: list[ExtractedClaim],
) -> list[EvidenceMatchCandidate]:
    """Return unsaved match-candidate rows for eligible matching evidence.

    Empty claim lists are a successful no-search outcome. Callers own the
    transaction that persists returned candidates with their stage result.
    """
    if not claims:
        return []
    if (
        analysis_run.organization_id != tenant_scope.organization_id
        or analysis_run.workspace_id != tenant_scope.workspace_id
    ):
        raise ValueError("Analysis run is outside the requested tenant scope.")

    candidates: list[EvidenceMatchCandidate] = []
    analysis_time = datetime.now(timezone.utc)
    for claim in claims:
        if (
            claim.analysis_run_id != analysis_run.id
            or claim.submission_version_id != analysis_run.submission_version_id
            or claim.organization_id != tenant_scope.organization_id
            or claim.workspace_id != tenant_scope.workspace_id
        ):
            raise ValueError("Claim is outside the requested analysis run or tenant scope.")
        search_text = _normalize_match_text(claim.text_span)
        if not search_text:
            continue
        # Require the full ordered claim token sequence, while ignoring
        # punctuation and line-wrap differences introduced by document extraction.
        # This does not match isolated keywords or inferred synonyms.
        normalized_phrase = f"% {search_text} %"
        normalized_title = func.concat(
            " ",
            func.regexp_replace(
                func.lower(func.coalesce(EvidenceVersion.title, "")),
                "[^[:alnum:]]+",
                " ",
                "g",
            ),
            " ",
        )
        normalized_extracted_text = func.concat(
            " ",
            func.regexp_replace(
                func.lower(func.coalesce(EvidenceVersion.extracted_text, "")),
                "[^[:alnum:]]+",
                " ",
                "g",
            ),
            " ",
        )
        statement = (
            select(EvidenceRecord, EvidenceVersion)
            .join(
                EvidenceVersion,
                (EvidenceVersion.evidence_record_id == EvidenceRecord.id)
                & (EvidenceVersion.organization_id == EvidenceRecord.organization_id)
                & (EvidenceVersion.workspace_id == EvidenceRecord.workspace_id),
            )
            .options(
                selectinload(EvidenceVersion.conflict_sources).joinedload(
                    EvidenceConflictSource.conflict
                )
            )
            .where(
                EvidenceRecord.organization_id == tenant_scope.organization_id,
                EvidenceRecord.workspace_id == tenant_scope.workspace_id,
                EvidenceRecord.primary_lifecycle_state == "Approved",
                EvidenceRecord.current_version_id == EvidenceVersion.id,
                EvidenceVersion.organization_id == tenant_scope.organization_id,
                EvidenceVersion.workspace_id == tenant_scope.workspace_id,
                or_(
                    normalized_title.like(normalized_phrase),
                    normalized_extracted_text.like(normalized_phrase),
                ),
            )
            .order_by(EvidenceVersion.title, EvidenceVersion.id)
        )
        rows = db.execute(statement).all()
        ordering = 0
        for record, version in rows:
            eligibility = derive_evidence_eligibility(record, version, analysis_time)
            if not eligibility["is_eligible"]:
                continue
            ordering += 1
            snapshot: dict[str, Any] = dict(eligibility)
            snapshot["analysis_time"] = analysis_time.isoformat()
            candidates.append(
                EvidenceMatchCandidate(
                    id=uuid4(),
                    organization_id=tenant_scope.organization_id,
                    workspace_id=tenant_scope.workspace_id,
                    analysis_run_id=analysis_run.id,
                    submission_version_id=analysis_run.submission_version_id,
                    claim_id=claim.id,
                    evidence_record_id=record.id,
                    evidence_version_id=version.id,
                    eligibility_snapshot=snapshot,
                    match_explanation=(
                        "Matched the ordered claim word sequence against evidence title or extracted text, "
                        "ignoring punctuation and line breaks."
                    ),
                    candidate_ordering=ordering,
                )
            )
    return candidates
