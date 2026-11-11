"""Payment persistence boundary and post-verification entitlement service."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_event
from app.models import (
    PayPalWebhookEvent,
    PaymentTransaction,
    Report,
    ReportEntitlement,
    WorkspaceMembership,
)
from app.modules.reports.config import ReportPricing
from app.modules.tenancy.schemas import TenantScope
from app.tenancy.context import TenantScope as AuditTenantScope


class InvalidVerifiedPayment(ValueError):
    """Provider evidence did not verify against the stored purchase attempt."""


class InvalidWebhook(ValueError):
    """Webhook verification failed; unverified events are never persisted/processed."""


@dataclass(frozen=True, slots=True)
class PayPalOrder:
    order_id: str
    status: str
    approval_url: str
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class PayPalCapture:
    order_id: str
    capture_id: str
    order_status: str
    capture_status: str
    amount: Decimal
    currency: str
    provider_verified: bool
    report_reference: str | None = None


@dataclass(frozen=True, slots=True)
class PayPalWebhookVerification:
    event_id: str
    event_type: str
    order_id: str | None
    capture_id: str | None
    provider_verified: bool


class PayPalGateway(Protocol):
    """Orders v2 operations used by the report payment API."""

    def create_order(
        self, *, request_id: str, amount: Decimal, currency: str, report_reference: str,
        return_url: str, cancel_url: str,
    ) -> PayPalOrder: ...

    def capture_order(self, *, order_id: str, request_id: str) -> PayPalCapture: ...


def _active_membership(db: Session, scope: TenantScope) -> WorkspaceMembership:
    membership = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.organization_id == scope.organization_id,
            WorkspaceMembership.workspace_id == scope.workspace_id,
            WorkspaceMembership.user_id == scope.user_id,
            WorkspaceMembership.status == "active",
        )
    )
    if membership is None:
        raise ValueError("An active workspace membership is required for this payment.")
    return membership


def create_pending_payment(
    db: Session,
    tenant_scope: TenantScope,
    *,
    report_id: UUID,
    idempotency_key: str,
) -> PaymentTransaction:
    """Persist a server-priced pending attempt; no client amount is accepted."""
    key = idempotency_key.strip()
    if not key or len(key) > 128:
        raise ValueError("A non-empty idempotency key of at most 128 characters is required.")
    membership = _active_membership(db, tenant_scope)
    report = db.scalar(
        select(Report).where(
            Report.id == report_id,
            Report.organization_id == tenant_scope.organization_id,
            Report.workspace_id == tenant_scope.workspace_id,
        )
    )
    if report is None:
        raise ValueError("Report is not available in the current workspace.")

    existing = db.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.organization_id == tenant_scope.organization_id,
            PaymentTransaction.workspace_id == tenant_scope.workspace_id,
            PaymentTransaction.purchaser_user_id == tenant_scope.user_id,
            PaymentTransaction.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.report_id != report.id:
            raise ValueError("The idempotency key is already associated with another report.")
        return existing
    entitlement = db.scalar(
        select(ReportEntitlement.id).where(
            ReportEntitlement.report_id == report.id,
            ReportEntitlement.purchaser_user_id == tenant_scope.user_id,
            ReportEntitlement.status == "active",
        )
    )
    if entitlement is not None:
        raise ValueError("The current user already has access to this report.")

    configured_price = ReportPricing.from_environment()
    payment = PaymentTransaction(
        id=uuid4(),
        organization_id=tenant_scope.organization_id,
        workspace_id=tenant_scope.workspace_id,
        report_id=report.id,
        purchaser_user_id=tenant_scope.user_id,
        purchaser_membership_id=membership.id,
        provider="paypal_sandbox",
        expected_amount=configured_price.amount,
        currency=configured_price.currency,
        status="pending",
        idempotency_key=key,
    )
    try:
        db.add(payment)
        db.flush()
        record_event(
            db,
            AuditTenantScope(tenant_scope.organization_id, tenant_scope.workspace_id, membership.id),
            actor_membership_id=membership.id,
            action_key="report.payment.pending",
            target_type="payment_transaction",
            target_id=payment.id,
            safe_metadata={
                "report_id": str(report.id),
                "provider": payment.provider,
                "expected_amount": format(configured_price.amount, ".2f"),
                "currency": configured_price.currency,
            },
        )
        db.commit()
        return payment
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(PaymentTransaction).where(
                PaymentTransaction.organization_id == tenant_scope.organization_id,
                PaymentTransaction.workspace_id == tenant_scope.workspace_id,
                PaymentTransaction.purchaser_user_id == tenant_scope.user_id,
                PaymentTransaction.idempotency_key == key,
            )
        )
        if existing is not None and existing.report_id == report.id:
            return existing
        raise
    except Exception:
        db.rollback()
        raise


def attach_paypal_order(
    db: Session,
    tenant_scope: TenantScope,
    *,
    transaction_id: UUID,
    order: PayPalOrder,
) -> PaymentTransaction:
    """Bind the provider order to its local purchase attempt."""
    payment = db.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.id == transaction_id,
            PaymentTransaction.organization_id == tenant_scope.organization_id,
            PaymentTransaction.workspace_id == tenant_scope.workspace_id,
            PaymentTransaction.purchaser_user_id == tenant_scope.user_id,
        ).with_for_update()
    )
    if payment is None or not order.order_id.strip():
        raise ValueError("Payment transaction or PayPal order is invalid in this workspace.")
    if payment.paypal_order_id is not None:
        if payment.paypal_order_id != order.order_id:
            raise ValueError("A different PayPal order is already attached to this transaction.")
        return payment
    if payment.status != "pending":
        raise ValueError("Only a pending transaction can receive its PayPal order ID.")
    if order.status not in {"CREATED", "APPROVED"}:
        raise ValueError("PayPal order is not in a valid approval state.")
    if order.amount != payment.expected_amount or order.currency != payment.currency:
        raise InvalidVerifiedPayment("PayPal order amount or currency does not match the purchase attempt.")
    try:
        payment.paypal_order_id = order.order_id
        if order.status == "APPROVED":
            payment.status = "provider_approved"
        db.commit()
        return payment
    except Exception:
        db.rollback()
        raise


def record_verified_capture_and_grant_entitlement(
    db: Session,
    tenant_scope: TenantScope,
    *,
    transaction_id: UUID,
    capture: PayPalCapture,
) -> ReportEntitlement:
    """Atomically persist an independently verified capture and user entitlement."""
    payment = db.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.id == transaction_id,
            PaymentTransaction.organization_id == tenant_scope.organization_id,
            PaymentTransaction.workspace_id == tenant_scope.workspace_id,
            PaymentTransaction.purchaser_user_id == tenant_scope.user_id,
        ).with_for_update()
    )
    if payment is None:
        raise ValueError("Payment transaction is not available in the current workspace.")

    expected_order_id = payment.paypal_order_id
    if (
        not capture.provider_verified
        or not isinstance(capture.amount, Decimal)
        or not capture.amount.is_finite()
        or not expected_order_id
        or capture.order_id != expected_order_id
        or capture.order_status != "COMPLETED"
        or capture.capture_status != "COMPLETED"
        or capture.amount != payment.expected_amount
        or capture.currency != payment.currency
        # PayPal may omit optional custom_id from its capture representation.
        # The stored order ID is already bound to this report; reject a
        # provider reference when present if it contradicts that binding.
        or (capture.report_reference is not None and capture.report_reference != str(payment.report_id))
        or not capture.capture_id.strip()
    ):
        raise InvalidVerifiedPayment("PayPal capture did not match the verified purchase attempt.")

    existing_for_transaction = db.scalar(
        select(ReportEntitlement).where(
            ReportEntitlement.payment_transaction_id == payment.id,
            ReportEntitlement.organization_id == tenant_scope.organization_id,
            ReportEntitlement.workspace_id == tenant_scope.workspace_id,
        )
    )
    if existing_for_transaction is not None:
        if payment.paypal_capture_id == capture.capture_id and payment.status == "capture_verified":
            return existing_for_transaction
        raise InvalidVerifiedPayment("A different capture was already recorded for this transaction.")
    if payment.status not in {"pending", "provider_approved"}:
        raise InvalidVerifiedPayment("Payment transaction is not awaiting capture verification.")

    membership = _active_membership(db, tenant_scope)
    if membership.id != payment.purchaser_membership_id:
        raise ValueError("Purchaser membership no longer matches the payment transaction.")
    report = db.scalar(
        select(Report).where(
            Report.id == payment.report_id,
            Report.organization_id == tenant_scope.organization_id,
            Report.workspace_id == tenant_scope.workspace_id,
        )
    )
    if report is None:
        raise ValueError("Payment transaction references an unavailable report.")

    now = datetime.now(timezone.utc)
    payment.paypal_capture_id = capture.capture_id
    payment.status = "capture_verified"
    payment.captured_at = now
    payment.verified_at = now
    db.flush()
    entitlement = ReportEntitlement(
        id=uuid4(),
        organization_id=tenant_scope.organization_id,
        workspace_id=tenant_scope.workspace_id,
        report_id=report.id,
        purchaser_user_id=tenant_scope.user_id,
        payment_transaction_id=payment.id,
        status="active",
        granted_at=now,
    )
    try:
        db.add(entitlement)
        db.flush()
        record_event(
            db,
            AuditTenantScope(tenant_scope.organization_id, tenant_scope.workspace_id, membership.id),
            actor_membership_id=membership.id,
            action_key="report.entitlement.granted",
            target_type="report_entitlement",
            target_id=entitlement.id,
            safe_metadata={
                "report_id": str(report.id),
                "payment_transaction_id": str(payment.id),
                "provider": payment.provider,
                "currency": payment.currency,
            },
        )
        db.commit()
        return entitlement
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(ReportEntitlement).where(
                ReportEntitlement.payment_transaction_id == transaction_id,
                ReportEntitlement.organization_id == tenant_scope.organization_id,
                ReportEntitlement.workspace_id == tenant_scope.workspace_id,
            )
        )
        if existing is not None:
            return existing
        raise
    except Exception:
        db.rollback()
        raise


def record_verified_webhook_event(
    db: Session,
    *,
    verification: PayPalWebhookVerification,
) -> PayPalWebhookEvent:
    """Persist a verified, minimal event receipt idempotently.

    Invalid webhook deliveries are rejected before persistence so an attacker
    cannot reserve a legitimate provider event ID.
    """
    if not verification.provider_verified:
        raise InvalidWebhook("PayPal webhook signature verification failed.")
    if not verification.event_id.strip() or not verification.event_type.strip():
        raise InvalidWebhook("Verified webhook is missing its provider event identifier or type.")

    def same_event(existing: PayPalWebhookEvent) -> bool:
        return (
            existing.signature_verified
            and existing.event_type == verification.event_type
            and existing.paypal_order_id == verification.order_id
            and existing.paypal_capture_id == verification.capture_id
        )

    existing = db.scalar(
        select(PayPalWebhookEvent).where(PayPalWebhookEvent.paypal_event_id == verification.event_id)
    )
    if existing is not None:
        if not same_event(existing):
            raise InvalidWebhook("PayPal event ID was previously recorded with different event data.")
        return existing
    event = PayPalWebhookEvent(
        id=uuid4(),
        paypal_event_id=verification.event_id,
        event_type=verification.event_type,
        paypal_order_id=verification.order_id,
        paypal_capture_id=verification.capture_id,
        signature_verified=True,
        processing_state="received",
    )
    try:
        db.add(event)
        db.commit()
        return event
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(PayPalWebhookEvent).where(PayPalWebhookEvent.paypal_event_id == verification.event_id)
        )
        if existing is not None:
            if not same_event(existing):
                raise InvalidWebhook("PayPal event ID was previously recorded with different event data.")
            return existing
        raise
    except Exception:
        db.rollback()
        raise
