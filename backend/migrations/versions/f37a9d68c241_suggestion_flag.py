"""Add explicit suggestion marker to generated suggestions.

Revision ID: f37a9d68c241
Revises: e85a3c4b71d0
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f37a9d68c241"
down_revision: Union[str, Sequence[str], None] = "e85a3c4b71d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generated_suggestions",
        sa.Column("is_suggestion", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("generated_suggestions", "is_suggestion")
