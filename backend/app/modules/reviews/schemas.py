"""Schemas for human review decisions and finding dispositions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


ReviewDecisionType = Literal[
    "Approved",
    "Approved with documented exceptions",
    "Changes requested",
    "Rejected",
]
FindingDispositionType = Literal["resolved", "not_applicable", "acknowledged", "disputed"]


class FindingDispositionCreate(BaseModel):
    finding_id: UUID
    disposition: str
    rationale: str

    @field_validator("disposition", "rationale")
    @classmethod
    def require_nonempty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must not be empty.")
        return normalized

    @field_validator("disposition")
    @classmethod
    def validate_disposition(cls, value: str) -> FindingDispositionType:
        # Historical exception-decision clients used this exact label. Preserve
        # that one contract through a narrow mapping; arbitrary free text remains
        # rejected and new clients use the four explicit semantic values.
        if value == "Accepted for this version":
            return "acknowledged"
        if value not in {"resolved", "not_applicable", "acknowledged", "disputed"}:
            raise ValueError("Unsupported finding disposition.")
        return value  # type: ignore[return-value]


class FindingDispositionRecordCreate(BaseModel):
    analysis_run_id: UUID
    submission_version_id: UUID
    disposition: FindingDispositionType
    rationale: str

    @field_validator("rationale")
    @classmethod
    def require_meaningful_rationale(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("A non-empty rationale is required.")
        return normalized


class ReviewDecisionCreate(BaseModel):
    decision: ReviewDecisionType
    rationale: str | None = None
    dispositions: list[FindingDispositionCreate] = Field(default_factory=list)

    @field_validator("rationale")
    @classmethod
    def normalize_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ReviewDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    workspace_id: UUID
    submission_version_id: UUID
    reviewer_membership_id: UUID
    decision: ReviewDecisionType
    rationale: str | None
    created_at: datetime


class HumanDispositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    workspace_id: UUID
    finding_id: UUID
    sequence_number: int
    analysis_run_id: UUID
    submission_version_id: UUID
    reviewer_membership_id: UUID
    disposition: str
    rationale: str
    created_at: datetime


class FindingResolutionResponse(BaseModel):
    finding_id: UUID
    original_is_unresolved: bool
    effective_disposition: str | None
    resolution_status: Literal["open", "resolved", "acknowledged", "disputed", "legacy_unrecognized"]
    blocks_clean_approval: bool
    disposition_history: list[HumanDispositionResponse]


class RecordFindingDispositionResponse(BaseModel):
    disposition: HumanDispositionResponse
    finding_resolution: FindingResolutionResponse


class ReviewEligibilityResponse(BaseModel):
    submission_version_id: UUID
    analysis_run_id: UUID | None
    analysis_status: str | None
    can_clean_approve: bool
    can_approve_with_exceptions: bool
    clean_approval_reason: str | None
    exception_approval_reason: str | None
    blocking_finding_ids: list[UUID]
