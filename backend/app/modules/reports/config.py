"""Server-owned fixed report pricing configuration."""

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


SUPPORTED_REPORT_CURRENCIES = frozenset({"USD"})
DEFAULT_REPORT_PRICE_AMOUNT = Decimal("5.00")
DEFAULT_REPORT_CURRENCY = "USD"


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
