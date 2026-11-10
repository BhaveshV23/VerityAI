"""Tenant-scoped report payment endpoints."""

from collections.abc import Iterator
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import AnyHttpUrl, BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_permission
from app.models import PaymentTransaction, ReportEntitlement
from app.modules.reports.config import PayPalSettings
from app.modules.reports.payments import (
    InvalidVerifiedPayment,
    PayPalGateway,
    attach_paypal_order,
    create_pending_payment,
    record_verified_capture_and_grant_entitlement,
)
from app.modules.reports.paypal import PayPalGatewayClient, PayPalProviderError
from app.modules.tenancy.schemas import TenantScope

router = APIRouter(tags=["report payments"])


class CreateReportPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_url: AnyHttpUrl
    cancel_url: AnyHttpUrl


class PaymentResponse(BaseModel):
    transaction_id: UUID
    report_id: UUID
    status: str
    amount: str
    currency: str
    paypal_order_id: str | None = None
    approval_url: str | None = None


class CaptureResponse(BaseModel):
    transaction_id: UUID
    report_id: UUID
    entitlement_id: UUID
    status: str


def get_paypal_gateway() -> Iterator[PayPalGateway]:
    try:
        gateway = PayPalGatewayClient(PayPalSettings.from_environment())
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        yield gateway
    finally:
        gateway.close()


def _provider_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PayPalProviderError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=502, detail="PayPal could not complete the payment request.")


@router.post(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/reports/{report_id}/payments",
    response_model=PaymentResponse,
)
def create_report_payment(
    org_id: UUID,
    workspace_id: UUID,
    report_id: UUID,
    body: CreateReportPaymentRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("submission.read.workspace")),
    gateway: PayPalGateway = Depends(get_paypal_gateway),
) -> PaymentResponse:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        raise HTTPException(status_code=404, detail="Report not found.")
    try:
        payment = create_pending_payment(db, scope, report_id=report_id, idempotency_key=idempotency_key)
        payment_id, expected_amount, currency = payment.id, payment.expected_amount, payment.currency
        order = gateway.create_order(
            request_id=str(uuid5(NAMESPACE_URL, f"verityai:paypal:create:{payment_id}")),
            amount=expected_amount,
            currency=currency,
            report_reference=str(report_id),
            return_url=str(body.return_url),
            cancel_url=str(body.cancel_url),
        )
        payment = attach_paypal_order(db, scope, transaction_id=payment_id, order=order)
    except (InvalidVerifiedPayment, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PayPalProviderError as exc:
        raise _provider_error(exc) from exc
    return PaymentResponse(
        transaction_id=payment.id,
        report_id=payment.report_id,
        status=payment.status,
        amount=format(payment.expected_amount, ".2f"),
        currency=payment.currency,
        paypal_order_id=payment.paypal_order_id,
        approval_url=order.approval_url,
    )


@router.post(
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}/report-payments/{transaction_id}/capture",
    response_model=CaptureResponse,
)
def capture_report_payment(
    org_id: UUID,
    workspace_id: UUID,
    transaction_id: UUID,
    db: Session = Depends(get_db),
    scope: TenantScope = Depends(require_permission("submission.read.workspace")),
    gateway: PayPalGateway = Depends(get_paypal_gateway),
) -> CaptureResponse:
    if org_id != scope.organization_id or workspace_id != scope.workspace_id:
        raise HTTPException(status_code=404, detail="Payment not found.")
    payment = db.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.id == transaction_id,
            PaymentTransaction.organization_id == scope.organization_id,
            PaymentTransaction.workspace_id == scope.workspace_id,
            PaymentTransaction.purchaser_user_id == scope.user_id,
        )
    )
    if payment is None or not payment.paypal_order_id:
        raise HTTPException(status_code=404, detail="Payment not found.")
    payment_id, order_id, report_id = payment.id, payment.paypal_order_id, payment.report_id
    if payment.status == "capture_verified":
        entitlement = db.scalar(
            select(ReportEntitlement).where(
                ReportEntitlement.payment_transaction_id == payment_id,
                ReportEntitlement.organization_id == scope.organization_id,
                ReportEntitlement.workspace_id == scope.workspace_id,
            )
        )
        if entitlement is not None:
            return CaptureResponse(
                transaction_id=payment_id, report_id=report_id,
                entitlement_id=entitlement.id, status="capture_verified",
            )
    request_id = str(uuid5(NAMESPACE_URL, f"verityai:paypal:capture:{payment_id}"))
    try:
        capture = gateway.capture_order(order_id=order_id, request_id=request_id)
        entitlement = record_verified_capture_and_grant_entitlement(
            db, scope, transaction_id=payment_id, capture=capture,
        )
    except (InvalidVerifiedPayment, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PayPalProviderError as exc:
        raise _provider_error(exc) from exc
    return CaptureResponse(
        transaction_id=payment_id,
        report_id=report_id,
        entitlement_id=entitlement.id,
        status="capture_verified",
    )
