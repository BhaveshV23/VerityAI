"""Name evidence candidate ordering explicitly.

Revision ID: e85a3c4b71d0
Revises: d2e6b5190c4a
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e85a3c4b71d0"
down_revision: Union[str, Sequence[str], None] = "d2e6b5190c4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("evidence_match_candidates", "candidate_order", new_column_name="candidate_ordering")


def downgrade() -> None:
    op.alter_column("evidence_match_candidates", "candidate_ordering", new_column_name="candidate_order")
