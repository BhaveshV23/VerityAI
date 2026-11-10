"""Versioned report snapshot and deliberately limited preview contracts."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ReportCounts(BaseModel):
    claims_analyzed: int
    findings: int
    supported_findings: int
    unverified_findings: int
    policy_findings: int


class ReportFinding(BaseModel):
    finding_id: str
    category: str
    attention_label: str | None
    explanation: str
    claim: dict[str, Any] | None
    supporting_evidence: list[dict[str, Any]]
    policy_result: dict[str, Any] | None


class ReportSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    report_id: str
    report_version: int
    submission_version_id: str
    analysis_run_id: str
    generated_at: datetime
    overall_analysis_status: Literal["Succeeded"]
    executive_summary: str
    counts: ReportCounts
    findings: list[ReportFinding]
    policy_evaluation: dict[str, Any]
    limitations: list[str]


class ReportFindingPreview(BaseModel):
    category: str
    attention_label: str | None
    explanation_preview: str


class ReportPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    report_version: int
    submission_version_id: str
    analysis_run_id: str
    generated_at: datetime
    overall_analysis_status: Literal["Succeeded"]
    executive_summary: str
    counts: ReportCounts
    finding_sample: list[ReportFindingPreview]
    is_limited_preview: Literal[True] = True
