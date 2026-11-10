"""Add immutable report snapshots and payment entitlement foundations.

Revision ID: 7ad3a10c8421
Revises: f37a9d68c241
Create Date: 2026-11-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7ad3a10c8421"
down_revision: Union[str, Sequence[str], None] = ("f37a9d68c241", "a83f0d5c1b72")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_memberships_user_tenant_ref",
        "workspace_memberships",
        ["id", "user_id", "organization_id", "workspace_id"],
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("submission_version_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("report_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("content_snapshot", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("report_version > 0", name="ck_reports_positive_report_version"),
        sa.ForeignKeyConstraint(
            ["analysis_run_id", "submission_version_id", "organization_id", "workspace_id"],
            ["analysis_runs.id", "analysis_runs.submission_version_id", "analysis_runs.organization_id", "analysis_runs.workspace_id"],
            name="fk_report_analysis_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submission_version_id", "organization_id", "workspace_id"],
            ["submission_versions.id", "submission_versions.organization_id", "submission_versions.workspace_id"],
            name="fk_report_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reports"),
        sa.UniqueConstraint("id", "organization_id", "workspace_id", name="uq_reports_id_tenant"),
        sa.UniqueConstraint(
            "id", "submission_version_id", "analysis_run_id", "organization_id", "workspace_id",
            name="uq_reports_analysis_ref",
        ),
        sa.UniqueConstraint(
            "submission_version_id", "analysis_run_id", name="uq_reports_version_analysis_run"
        ),
    )
    op.create_index(
        "ix_reports_tenant_generated",
        "reports",
        ["organization_id", "workspace_id", "generated_at"],
        unique=False,
    )

    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("purchaser_user_id", sa.Uuid(), nullable=False),
        sa.Column("purchaser_membership_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), server_default="paypal_sandbox", nullable=False),
        sa.Column("paypal_order_id", sa.String(length=128), nullable=True),
        sa.Column("paypal_capture_id", sa.String(length=128), nullable=True),
        sa.Column("expected_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("provider = 'paypal_sandbox'", name="ck_payment_transactions_valid_provider"),
        sa.CheckConstraint(
            "status IN ('pending', 'provider_approved', 'capture_verified', 'failed', 'cancelled')",
            name="ck_payment_transactions_valid_status",
        ),
        sa.CheckConstraint("expected_amount > 0", name="ck_payment_transactions_positive_expected_amount"),
        sa.CheckConstraint("currency = 'USD'", name="ck_payment_transactions_supported_currency"),
        sa.CheckConstraint(
            "status != 'capture_verified' OR (paypal_order_id IS NOT NULL AND paypal_capture_id IS NOT NULL AND captured_at IS NOT NULL AND verified_at IS NOT NULL)",
            name="ck_payment_transactions_verified_capture_has_provider_reference",
        ),
        sa.ForeignKeyConstraint(
            ["purchaser_membership_id", "purchaser_user_id", "organization_id", "workspace_id"],
            ["workspace_memberships.id", "workspace_memberships.user_id", "workspace_memberships.organization_id", "workspace_memberships.workspace_id"],
            name="fk_pay_tx_purchaser_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["purchaser_user_id"], ["users.id"],
            name="fk_pay_tx_purchaser_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "organization_id", "workspace_id"],
            ["reports.id", "reports.organization_id", "reports.workspace_id"],
            name="fk_pay_tx_report",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_transactions"),
        sa.UniqueConstraint("id", "organization_id", "workspace_id", name="uq_payment_transactions_id_tenant"),
        sa.UniqueConstraint(
            "id", "report_id", "organization_id", "workspace_id", "purchaser_user_id",
            name="uq_payment_transactions_entitlement_ref",
        ),
        sa.UniqueConstraint("paypal_order_id", name="uq_payment_transactions_paypal_order"),
        sa.UniqueConstraint("paypal_capture_id", name="uq_payment_transactions_paypal_capture"),
        sa.UniqueConstraint(
            "organization_id", "workspace_id", "purchaser_user_id", "idempotency_key",
            name="uq_payment_transactions_idempotency",
        ),
    )
    op.create_index(
        "uq_payment_transactions_active_report_user",
        "payment_transactions",
        ["report_id", "purchaser_user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'provider_approved')"),
    )
    op.create_index(
        "ix_payment_transactions_tenant_report",
        "payment_transactions",
        ["organization_id", "workspace_id", "report_id"],
        unique=False,
    )

    op.create_table(
        "report_entitlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("purchaser_user_id", sa.Uuid(), nullable=False),
        sa.Column("payment_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_report_entitlements_valid_status"),
        sa.ForeignKeyConstraint(
            ["payment_transaction_id", "report_id", "organization_id", "workspace_id", "purchaser_user_id"],
            ["payment_transactions.id", "payment_transactions.report_id", "payment_transactions.organization_id", "payment_transactions.workspace_id", "payment_transactions.purchaser_user_id"],
            name="fk_entitlement_payment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "organization_id", "workspace_id"],
            ["reports.id", "reports.organization_id", "reports.workspace_id"],
            name="fk_entitlement_report",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["purchaser_user_id"], ["users.id"],
            name="fk_entitlement_purchaser_user",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_report_entitlements"),
        sa.UniqueConstraint("id", "organization_id", "workspace_id", name="uq_report_entitlements_id_tenant"),
        sa.UniqueConstraint("report_id", "purchaser_user_id", name="uq_report_entitlements_report_user"),
        sa.UniqueConstraint("payment_transaction_id", name="uq_report_entitlements_transaction"),
    )
    op.create_index(
        "ix_report_entitlements_tenant_user",
        "report_entitlements",
        ["organization_id", "workspace_id", "purchaser_user_id"],
        unique=False,
    )

    op.create_table(
        "paypal_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("paypal_event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("paypal_order_id", sa.String(length=128), nullable=True),
        sa.Column("paypal_capture_id", sa.String(length=128), nullable=True),
        sa.Column("signature_verified", sa.Boolean(), nullable=False),
        sa.Column("processing_state", sa.String(length=20), server_default="received", nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "processing_state IN ('received', 'processed', 'failed')",
            name="ck_paypal_webhook_events_valid_processing_state",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_paypal_webhook_events"),
        sa.UniqueConstraint("paypal_event_id", name="uq_paypal_webhook_events_event_id"),
    )
    op.create_index(
        "ix_paypal_webhook_events_received", "paypal_webhook_events", ["received_at"], unique=False
    )

    op.execute("""
        CREATE TRIGGER prevent_reports_mutation
        BEFORE UPDATE OR DELETE ON reports
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
    """)
    op.execute("""
        CREATE FUNCTION require_successful_report_analysis() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            successful_required_stage_count integer;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM analysis_runs r
                WHERE r.id = NEW.analysis_run_id
                  AND r.submission_version_id = NEW.submission_version_id
                  AND r.organization_id = NEW.organization_id
                  AND r.workspace_id = NEW.workspace_id
                  AND r.overall_state = 'Succeeded'
                  AND r.completed_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'report requires a completed successful analysis run'
                    USING ERRCODE = '23514';
            END IF;
            SELECT count(DISTINCT s.stage_key) INTO successful_required_stage_count
            FROM analysis_stage_results s
            WHERE s.analysis_run_id = NEW.analysis_run_id
              AND s.organization_id = NEW.organization_id
              AND s.workspace_id = NEW.workspace_id
              AND s.is_required
              AND s.state = 'Succeeded'
              AND s.stage_key IN (
                  'claim_extraction', 'evidence_retrieval',
                  'policy_evaluation', 'finding_composition'
              );
            IF successful_required_stage_count <> 4 THEN
                RAISE EXCEPTION 'report requires all required analysis stages to succeed'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER require_successful_report_analysis_before_insert
        BEFORE INSERT ON reports
        FOR EACH ROW EXECUTE FUNCTION require_successful_report_analysis();
    """)
    op.execute("""
        CREATE FUNCTION require_verified_report_payment() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM payment_transactions p
                WHERE p.id = NEW.payment_transaction_id
                  AND p.report_id = NEW.report_id
                  AND p.organization_id = NEW.organization_id
                  AND p.workspace_id = NEW.workspace_id
                  AND p.purchaser_user_id = NEW.purchaser_user_id
                  AND p.status = 'capture_verified'
                  AND p.paypal_capture_id IS NOT NULL
                  AND p.verified_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'report entitlement requires a verified payment capture'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER require_verified_report_payment_before_insert
        BEFORE INSERT ON report_entitlements
        FOR EACH ROW EXECUTE FUNCTION require_verified_report_payment();
    """)
    op.execute("""
        CREATE FUNCTION prevent_verified_payment_downgrade() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status = 'capture_verified' AND (
                NEW.status <> OLD.status OR
                NEW.paypal_order_id IS DISTINCT FROM OLD.paypal_order_id OR
                NEW.paypal_capture_id IS DISTINCT FROM OLD.paypal_capture_id OR
                NEW.expected_amount IS DISTINCT FROM OLD.expected_amount OR
                NEW.currency IS DISTINCT FROM OLD.currency OR
                NEW.report_id IS DISTINCT FROM OLD.report_id OR
                NEW.purchaser_user_id IS DISTINCT FROM OLD.purchaser_user_id OR
                NEW.organization_id IS DISTINCT FROM OLD.organization_id OR
                NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
            ) THEN
                RAISE EXCEPTION 'verified payment facts are immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER prevent_verified_payment_downgrade_before_update
        BEFORE UPDATE ON payment_transactions
        FOR EACH ROW EXECUTE FUNCTION prevent_verified_payment_downgrade();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS require_successful_report_analysis_before_insert ON reports")
    op.execute("DROP FUNCTION IF EXISTS require_successful_report_analysis()")
    op.execute("DROP TRIGGER IF EXISTS prevent_verified_payment_downgrade_before_update ON payment_transactions")
    op.execute("DROP FUNCTION IF EXISTS prevent_verified_payment_downgrade()")
    op.execute("DROP TRIGGER IF EXISTS require_verified_report_payment_before_insert ON report_entitlements")
    op.execute("DROP FUNCTION IF EXISTS require_verified_report_payment()")
    op.execute("DROP TRIGGER IF EXISTS prevent_reports_mutation ON reports")
    op.drop_index("ix_paypal_webhook_events_received", table_name="paypal_webhook_events")
    op.drop_table("paypal_webhook_events")
    op.drop_index("ix_report_entitlements_tenant_user", table_name="report_entitlements")
    op.drop_table("report_entitlements")
    op.drop_index("ix_payment_transactions_tenant_report", table_name="payment_transactions")
    op.drop_index("uq_payment_transactions_active_report_user", table_name="payment_transactions")
    op.drop_table("payment_transactions")
    op.drop_index("ix_reports_tenant_generated", table_name="reports")
    op.drop_table("reports")
    op.drop_constraint("uq_memberships_user_tenant_ref", "workspace_memberships", type_="unique")
