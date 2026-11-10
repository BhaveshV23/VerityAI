from decimal import Decimal

import httpx
import pytest

from app.modules.reports.config import DEFAULT_PAYPAL_BASE_URL, PayPalSettings
from app.modules.reports.paypal import PayPalGatewayClient, PayPalProviderError


def _settings():
    return PayPalSettings("sandbox-client", "sandbox-secret", DEFAULT_PAYPAL_BASE_URL)


def test_oauth_order_creation_and_capture_use_sandbox_orders_v2():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "test-access-token", "token_type": "Bearer"})
        if request.url.path == "/v2/checkout/orders":
            return httpx.Response(201, json={
                "id": "ORDER-1", "status": "CREATED",
                "purchase_units": [{"amount": {"currency_code": "USD", "value": "5.00"}}],
                "links": [{"rel": "approve", "href": "https://sandbox.paypal.test/approve"}],
            })
        return httpx.Response(201, json={
            "id": "ORDER-1", "status": "COMPLETED",
            "purchase_units": [{
                "custom_id": "report-1",
                "payments": {"captures": [{
                    "id": "CAPTURE-1", "status": "COMPLETED",
                    "amount": {"currency_code": "USD", "value": "5.00"},
                }]},
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gateway = PayPalGatewayClient(_settings(), client=client)
    order = gateway.create_order(
        request_id="create-request-1", amount=Decimal("5.00"), currency="USD",
        report_reference="report-1", return_url="https://verity.example/return",
        cancel_url="https://verity.example/cancel",
    )
    capture = gateway.capture_order(order_id="ORDER-1", request_id="capture-request-1")
    duplicate_capture = gateway.capture_order(order_id="ORDER-1", request_id="capture-request-1")

    assert order.order_id == "ORDER-1"
    assert order.approval_url.endswith("/approve")
    assert json_body(requests[1])["intent"] == "CAPTURE"
    assert json_body(requests[1])["purchase_units"][0]["custom_id"] == "report-1"
    assert requests[1].headers["PayPal-Request-Id"] == "create-request-1"
    assert requests[3].headers["PayPal-Request-Id"] == requests[5].headers["PayPal-Request-Id"]
    assert requests[3].headers["PayPal-Request-Id"] == "capture-request-1"
    assert requests[3].headers["Authorization"] == "Bearer test-access-token"
    assert capture.provider_verified is True
    assert capture.report_reference == "report-1"
    assert capture.capture_id == "CAPTURE-1"
    assert duplicate_capture.capture_id == capture.capture_id


def json_body(request):
    import json

    return json.loads(request.content) if request.content else {}


def test_oauth_failure_is_sanitized():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(401, json={"error": "invalid_client", "secret": "do-not-return"})
    ))
    gateway = PayPalGatewayClient(_settings(), client=client)
    with pytest.raises(PayPalProviderError) as error:
        gateway.create_order(
            request_id="id", amount=Decimal("5.00"), currency="USD", report_reference="r",
            return_url="https://verity.example/return", cancel_url="https://verity.example/cancel",
        )
    assert "401" in str(error.value)
    assert "do-not-return" not in str(error.value)
    assert "sandbox-secret" not in str(error.value)


def test_production_paypal_url_is_rejected(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "sandbox-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "sandbox-secret")
    monkeypatch.setenv("PAYPAL_BASE_URL", "https://api-m.paypal.com")
    with pytest.raises(ValueError, match="Sandbox API host"):
        PayPalSettings.from_environment()


def test_paypal_http_error_and_timeout_are_sanitized():
    error_client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(503, json={"message": "sensitive provider details"})
    ))
    with pytest.raises(PayPalProviderError, match="HTTP 503"):
        PayPalGatewayClient(_settings(), client=error_client)._access_token()

    def timeout(request):
        raise httpx.ReadTimeout("sensitive request details")

    timeout_client = httpx.Client(transport=httpx.MockTransport(timeout))
    with pytest.raises(PayPalProviderError, match="timed out") as error:
        PayPalGatewayClient(_settings(), client=timeout_client)._access_token()
    assert "sensitive request details" not in str(error.value)


def test_incomplete_or_mismatched_capture_response_is_not_accepted():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200,
        json={
            "access_token": "token", "id": "ORDER-1", "status": "COMPLETED",
            "purchase_units": [{"custom_id": "different-report", "payments": {"captures": [{
                "id": "CAPTURE-1", "status": "COMPLETED",
                "amount": {"currency_code": "USD", "value": "5.00"},
            }]}}],
        },
    )))
    gateway = PayPalGatewayClient(_settings(), client=client)
    capture = gateway.capture_order(order_id="ORDER-1", request_id="capture-id")
    assert capture.report_reference == "different-report"
    assert capture.provider_verified

    def invalid_handler(request):
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(200, json={"id": "ORDER-1", "status": "COMPLETED", "purchase_units": []})

    invalid_client = httpx.Client(transport=httpx.MockTransport(invalid_handler))
    with pytest.raises(PayPalProviderError, match="incomplete capture"):
        PayPalGatewayClient(_settings(), client=invalid_client).capture_order(
            order_id="ORDER-1", request_id="capture-id",
        )
