"""Require a content hash for every submission version.

Revision ID: c0516ad42f8e
Revises: a14d3e7c91b2
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c0516ad42f8e"
down_revision: Union[str, Sequence[str], None] = "a14d3e7c91b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("submission_versions", "source_hash", nullable=False)


def downgrade() -> None:
    op.alter_column("submission_versions", "source_hash", nullable=True)
