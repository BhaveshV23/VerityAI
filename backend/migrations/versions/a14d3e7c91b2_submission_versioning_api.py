"""Allow pending artifacts and constrain submission status values.

Revision ID: a14d3e7c91b2
Revises: 8b9f20d671ad
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a14d3e7c91b2"
down_revision: Union[str, Sequence[str], None] = "8b9f20d671ad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("submission_version_artifacts", "analysis_run_id", nullable=True)
    op.create_check_constraint(
        op.f("ck_submissions_valid_current_status"),
        "submissions",
        "current_status IN ('Draft', 'Submitted', 'Analysis blocked', 'In review', "
        "'Changes requested', 'Approved', 'Approved with documented exceptions', 'Rejected')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_submissions_valid_current_status", "submissions", type_="check")
    op.alter_column("submission_version_artifacts", "analysis_run_id", nullable=False)
