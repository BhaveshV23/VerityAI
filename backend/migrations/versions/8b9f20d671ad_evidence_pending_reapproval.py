"""Track explicit re-approval requirement per evidence version.

Revision ID: 8b9f20d671ad
Revises: 47283f392f32
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8b9f20d671ad"
down_revision: Union[str, Sequence[str], None] = "47283f392f32"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evidence_versions",
        sa.Column("pending_reapproval", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("evidence_versions", "pending_reapproval")
