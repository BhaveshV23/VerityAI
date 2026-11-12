"""Contracts for generated report narratives and their deterministic facts."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.modules.reports.schemas import ReportCounts


class NarrativeClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    analysis: str
    limitations: list[str]


class DetailedNarrativeDraft(BaseModel):
    """Only prose is supplied by Gemini; all facts are added from the snapshot."""

    model_config = ConfigDict(extra="forbid")

    executive_summary: str
    verification_overview: str
    claim_analyses: list[NarrativeClaim]
    risk_assessment: list[str]
    recommendations: list[str]


class DetailedClaimAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    claim_description: str
    verification_status: str
    deterministic_explanation: str
    ai_analysis: str
    ai_limitations: list[str]
    supporting_evidence: list[dict[str, Any]]
    policy_result: dict[str, Any] | None


class DetailedReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    report_id: str
    report_version: int
    submission_version_id: str
    analysis_run_id: str
    snapshot_generated_at: datetime
    generated_at: datetime
    organization_name: str
    workspace_name: str
    submission_id: str
    executive_summary: str
    verification_overview: str
    counts: ReportCounts
    policy_evaluation: dict[str, Any]
    coverage_limitations: list[str]
    claim_analyses: list[DetailedClaimAnalysis]
    risk_assessment: list[str]
    recommendation_label: Literal["AI-generated guidance"] = "AI-generated guidance"
    recommendations: list[str]
    methodology: str
    evidence_appendix: list[dict[str, Any]]


class DetailedReportStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    report_version: int
    status: Literal["not_started", "pending", "generating", "completed", "failed"]
    detailed_report: DetailedReport | None = None
    error: str | None = None
    retryable: bool = False
