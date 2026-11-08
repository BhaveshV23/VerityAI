"""Order finding dispositions and protect original findings.

Revision ID: a83f0d5c1b72
Revises: 9ca413bf0d67
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a83f0d5c1b72"
down_revision: Union[str, Sequence[str], None] = "9ca413bf0d67"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Preserve pre-existing dispositions and give them deterministic per-finding
    # order before requiring sequence numbers for new append-only entries.
    op.add_column("human_dispositions", sa.Column("sequence_number", sa.Integer(), nullable=True))
    op.execute("""
        UPDATE human_dispositions AS disposition
        SET sequence_number = ordered.sequence_number
        FROM (
            SELECT id, row_number() OVER (
                PARTITION BY finding_id ORDER BY created_at, id
            )::integer AS sequence_number
            FROM human_dispositions
        ) AS ordered
        WHERE disposition.id = ordered.id
    """)
    op.alter_column("human_dispositions", "sequence_number", nullable=False)
    op.create_unique_constraint(
        "uq_human_dispositions_finding_sequence",
        "human_dispositions",
        ["finding_id", "sequence_number"],
    )

    # The trigger function was installed by the initial relational migration.
    op.execute("""
        CREATE TRIGGER prevent_findings_mutation
        BEFORE UPDATE OR DELETE ON findings
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS prevent_findings_mutation ON findings")
    op.drop_constraint(
        "uq_human_dispositions_finding_sequence",
        "human_dispositions",
        type_="unique",
    )
    op.drop_column("human_dispositions", "sequence_number")
