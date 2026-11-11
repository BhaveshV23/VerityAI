"""Server-owned fixed report pricing configuration."""

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


SUPPORTED_REPORT_CURRENCIES = frozenset({"USD"})
DEFAULT_REPORT_PRICE_AMOUNT = Decimal("5.00")
DEFAULT_REPORT_CURRENCY = "USD"
DEFAULT_PAYPAL_BASE_URL = "https://api-m.sandbox.paypal.com"


@dataclass(frozen=True, slots=True)
class ReportPricing:
    amount: Decimal
    currency: str

    @classmethod
    def from_environment(cls) -> "ReportPricing":
        raw_amount = os.getenv("REPORT_PRICE_AMOUNT", str(DEFAULT_REPORT_PRICE_AMOUNT)).strip()
        currency = os.getenv("REPORT_CURRENCY", DEFAULT_REPORT_CURRENCY).strip().upper()
        try:
            amount = Decimal(raw_amount)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("REPORT_PRICE_AMOUNT must be a positive decimal amount with at most two fractional digits.") from exc

        if (
            not amount.is_finite()
            or amount <= 0
            or amount > Decimal("99999999.99")
            or amount.as_tuple().exponent < -2
            or amount != amount.quantize(Decimal("0.01"))
        ):
            raise ValueError("REPORT_PRICE_AMOUNT must be a positive decimal amount with at most two fractional digits.")
        if currency not in SUPPORTED_REPORT_CURRENCIES:
            raise ValueError("REPORT_CURRENCY is unsupported; only USD is currently supported.")
        return cls(amount=amount.quantize(Decimal("0.01")), currency=currency)


@dataclass(frozen=True, slots=True)
class PayPalSettings:
    client_id: str
    client_secret: str
    base_url: str = DEFAULT_PAYPAL_BASE_URL
    timeout_seconds: float = 10.0

    @classmethod
    def from_environment(cls) -> "PayPalSettings":
        client_id = os.getenv("PAYPAL_CLIENT_ID", "").strip()
        client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
        base_url = os.getenv("PAYPAL_BASE_URL", DEFAULT_PAYPAL_BASE_URL).strip().rstrip("/")
        if not client_id or not client_secret:
            raise ValueError("PayPal Sandbox credentials are not configured.")
        if not base_url:
            base_url = DEFAULT_PAYPAL_BASE_URL
        from urllib.parse import urlsplit

        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api-m.sandbox.paypal.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("PAYPAL_BASE_URL must point to the HTTPS PayPal Sandbox API host.")
        return cls(client_id=client_id, client_secret=client_secret, base_url=base_url)
