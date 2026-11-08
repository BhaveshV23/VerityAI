"""Align analysis run, stage, and extracted claim states.

Revision ID: d2e6b5190c4a
Revises: c0516ad42f8e
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e6b5190c4a"
down_revision: Union[str, Sequence[str], None] = "517ba6c88ffe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE analysis_runs SET overall_state = 'Running' WHERE overall_state = 'Queued'")
    op.alter_column("analysis_runs", "overall_state", server_default="Running")
    op.alter_column("analysis_runs", "started_at", nullable=False)
    op.create_check_constraint(
        op.f("ck_analysis_runs_valid_overall_state"),
        "analysis_runs",
        "overall_state IN ('Running', 'Succeeded', 'Incomplete')",
    )

    op.add_column("analysis_stage_results", sa.Column("error_message", sa.String(length=500), nullable=True))
    op.create_check_constraint(
        op.f("ck_analysis_stage_results_valid_stage_state"),
        "analysis_stage_results",
        "state IN ('Not started', 'Running', 'Succeeded', 'Failed', 'Not run')",
    )

    op.alter_column("extracted_claims", "claim_text", new_column_name="text_span")
    op.alter_column("extracted_claims", "start_offset", nullable=False)
    op.alter_column("extracted_claims", "end_offset", nullable=False)
    op.alter_column("extracted_claims", "candidate_kind", nullable=False)
    op.create_check_constraint(
        op.f("ck_extracted_claims_valid_candidate_kind"),
        "extracted_claims",
        "candidate_kind IN ('factual', 'promotional')",
    )
    op.create_check_constraint(
        op.f("ck_extracted_claims_valid_claim_offsets"),
        "extracted_claims",
        "start_offset >= 0 AND end_offset > start_offset",
    )


def downgrade() -> None:
    op.drop_constraint("ck_extracted_claims_valid_claim_offsets", "extracted_claims", type_="check")
    op.drop_constraint("ck_extracted_claims_valid_candidate_kind", "extracted_claims", type_="check")
    op.alter_column("extracted_claims", "candidate_kind", nullable=True)
    op.alter_column("extracted_claims", "end_offset", nullable=True)
    op.alter_column("extracted_claims", "start_offset", nullable=True)
    op.alter_column("extracted_claims", "text_span", new_column_name="claim_text")

    op.drop_constraint("ck_analysis_stage_results_valid_stage_state", "analysis_stage_results", type_="check")
    op.drop_column("analysis_stage_results", "error_message")

    op.drop_constraint("ck_analysis_runs_valid_overall_state", "analysis_runs", type_="check")
    op.alter_column("analysis_runs", "started_at", nullable=True)
    op.alter_column("analysis_runs", "overall_state", server_default="Queued")
