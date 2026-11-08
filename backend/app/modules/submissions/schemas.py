"""Request and response schemas for submission intake."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CreateTextSubmissionRequest(BaseModel):
    source_type: Literal["text"] = "text"
    submitted_text: str = Field(min_length=1)


class CreateSubmissionResponse(BaseModel):
    submission_id: UUID
    version_id: UUID
    current_status: str
    analysis_run_id: UUID
    analysis_status: Literal["Running", "Succeeded", "Incomplete"]
    extraction_status: Literal["Not required", "Succeeded"] = "Not required"
    extracted_text: str | None = None
