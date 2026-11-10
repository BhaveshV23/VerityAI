from decimal import Decimal

import pytest

from app.modules.reports.config import ReportPricing
from fakes.paypal import FakePayPalGateway


def test_report_price_defaults_to_exactly_five_usd(monkeypatch):
    monkeypatch.delenv("REPORT_PRICE_AMOUNT", raising=False)
    monkeypatch.delenv("REPORT_CURRENCY", raising=False)

    pricing = ReportPricing.from_environment()

    assert pricing.amount == Decimal("5.00")
    assert pricing.currency == "USD"
    assert isinstance(pricing.amount, Decimal)


@pytest.mark.parametrize("raw", ["0", "-1", "NaN", "Infinity", "5.001", "5.000", "100000000.00", "not-a-price"])
def test_report_price_rejects_invalid_amounts(monkeypatch, raw):
    monkeypatch.setenv("REPORT_PRICE_AMOUNT", raw)
    with pytest.raises(ValueError):
        ReportPricing.from_environment()


def test_report_price_rejects_unsupported_currency(monkeypatch):
    monkeypatch.setenv("REPORT_CURRENCY", "EUR")
    with pytest.raises(ValueError, match="unsupported"):
        ReportPricing.from_environment()


def test_test_only_paypal_fake_fails_closed_without_configured_responses():
    fake = FakePayPalGateway()
    with pytest.raises(RuntimeError, match="No fake PayPal order response"):
        fake.create_order(
            request_id="test-request",
            amount=Decimal("5.00"),
            currency="USD",
            report_reference="test-report",
            return_url="http://localhost/report-return",
            cancel_url="http://localhost/report-cancel",
        )
