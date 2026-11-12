"""Add entitlement-gated detailed report artifacts.

Revision ID: 3c820a5fd194
Revises: 7ad3a10c8421
Create Date: 2026-11-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3c820a5fd194"
down_revision: Union[str, Sequence[str], None] = "7ad3a10c8421"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_narrative_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("report_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("content", sa.JSON(), nullable=True),
        sa.Column("pdf_storage_key", sa.String(length=64), nullable=True),
        sa.Column("generation_error", sa.String(length=500), nullable=True),
        sa.Column("generation_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'generating', 'completed', 'failed')",
            name="ck_report_narrative_artifacts_valid_status",
        ),
        sa.CheckConstraint("report_version > 0", name="ck_report_narrative_artifacts_positive_report_version"),
        sa.CheckConstraint("generation_attempts >= 0", name="ck_report_narrative_artifacts_nonnegative_generation_attempts"),
        sa.CheckConstraint(
            "status != 'completed' OR (content IS NOT NULL AND pdf_storage_key IS NOT NULL AND generated_at IS NOT NULL)",
            name="ck_report_narrative_artifacts_completed_artifact_has_report_and_pdf",
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "organization_id", "workspace_id"],
            ["reports.id", "reports.organization_id", "reports.workspace_id"],
            name="fk_report_narrative_artifact_report",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_report_narrative_artifacts"),
        sa.UniqueConstraint("report_id", name="uq_report_narrative_artifacts_report"),
    )
    op.create_index(
        "ix_report_narrative_artifacts_tenant_status",
        "report_narrative_artifacts",
        ["organization_id", "workspace_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_report_narrative_artifacts_tenant_status", table_name="report_narrative_artifacts")
    op.drop_table("report_narrative_artifacts")
