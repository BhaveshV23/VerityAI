"""Enforce rationale requirements for review decisions and dispositions.

Revision ID: 9ca413bf0d67
Revises: f37a9d68c241
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op


revision: str = "9ca413bf0d67"
down_revision: Union[str, Sequence[str], None] = "f37a9d68c241"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("human_dispositions", "rationale", nullable=False)
    op.create_check_constraint(
        op.f("ck_human_dispositions_nonempty_rationale"),
        "human_dispositions",
        "length(trim(rationale)) > 0",
    )
    op.create_check_constraint(
        op.f("ck_review_decisions_required_rationale_unless_clean_approval"),
        "review_decisions",
        "decision = 'Approved' OR (rationale IS NOT NULL AND length(trim(rationale)) > 0)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_review_decisions_required_rationale_unless_clean_approval",
        "review_decisions",
        type_="check",
    )
    op.drop_constraint(
        "ck_human_dispositions_nonempty_rationale",
        "human_dispositions",
        type_="check",
    )
    op.alter_column("human_dispositions", "rationale", nullable=True)
