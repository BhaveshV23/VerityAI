from decimal import Decimal
import logging

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
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-1"}],
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
    assert order.approval_url.startswith("https://www.sandbox.paypal.com/checkoutnow")
    assert json_body(requests[1])["intent"] == "CAPTURE"
    assert json_body(requests[1])["purchase_units"][0] == {
        "custom_id": "report-1", "amount": {"currency_code": "USD", "value": "5.00"},
    }
    assert requests[1].headers["PayPal-Request-Id"] == "create-request-1"
    assert requests[1].headers["Prefer"] == "return=representation"
    assert requests[3].headers["PayPal-Request-Id"] == requests[5].headers["PayPal-Request-Id"]
    assert requests[3].headers["PayPal-Request-Id"] == "capture-request-1"
    assert requests[3].headers["Prefer"] == "return=representation"
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


def test_paypal_sandbox_url_rejects_unexpected_port(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "sandbox-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "sandbox-secret")
    monkeypatch.setenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com:8443")
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


@pytest.mark.parametrize("relation", ["approve", "payer-action"])
def test_order_creation_parses_supported_sandbox_approval_links(relation):
    def handler(request):
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "token"})
        assert request.headers["Prefer"] == "return=representation"
        return httpx.Response(201, json={
            "id": "ORDER-2", "status": "CREATED",
            "purchase_units": [{"amount": {"currency_code": "USD", "value": "5.00"}}],
            "links": [{"rel": relation, "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-2"}],
        })

    gateway = PayPalGatewayClient(_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    order = gateway.create_order(
        request_id="id", amount=Decimal("5.00"), currency="USD", report_reference="r",
        return_url="https://verity.example/return", cancel_url="https://verity.example/cancel",
    )
    assert order.order_id == "ORDER-2"


@pytest.mark.parametrize("response_body", [
    {"status": "CREATED", "purchase_units": [{"amount": {"currency_code": "USD", "value": "5.00"}}],
     "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow"}]},
    {"id": "ORDER-3", "status": "CREATED", "purchase_units": [{"amount": {"currency_code": "USD", "value": "5.00"}}]},
])
def test_order_creation_reports_missing_id_or_approval_link(response_body, caplog):
    def handler(request):
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(201, json=response_body)

    gateway = PayPalGatewayClient(_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    with caplog.at_level(logging.WARNING, logger="app.modules.reports.paypal"):
        with pytest.raises(PayPalProviderError, match="incomplete order"):
            gateway.create_order(
                request_id="id", amount=Decimal("5.00"), currency="USD", report_reference="r",
                return_url="https://verity.example/return", cancel_url="https://verity.example/cancel",
            )
    assert "id" in caplog.text or "links[approve|payer-action].href" in caplog.text
    assert "ORDER-3" not in caplog.text


@pytest.mark.parametrize("href", [
    "https://paypal.com/checkoutnow", "https://www.sandbox.paypal.com.evil.test/checkoutnow",
    "http://www.sandbox.paypal.com/checkoutnow", "https://user@www.sandbox.paypal.com/checkoutnow",
])
def test_order_creation_rejects_non_sandbox_approval_url(href):
    def handler(request):
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(201, json={
            "id": "ORDER-4", "status": "CREATED",
            "purchase_units": [{"amount": {"currency_code": "USD", "value": "5.00"}}],
            "links": [{"rel": "approve", "href": href}],
        })

    gateway = PayPalGatewayClient(_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(PayPalProviderError, match="incomplete order"):
        gateway.create_order(
            request_id="id", amount=Decimal("5.00"), currency="USD", report_reference="r",
            return_url="https://verity.example/return", cancel_url="https://verity.example/cancel",
        )


def test_order_creation_reports_malformed_json_and_safe_paypal_error_details(caplog):
    def malformed(request):
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(201, text="not-json")

    gateway = PayPalGatewayClient(_settings(), client=httpx.Client(transport=httpx.MockTransport(malformed)))
    with pytest.raises(PayPalProviderError, match="invalid response"):
        gateway.create_order(
            request_id="id", amount=Decimal("5.00"), currency="USD", report_reference="r",
            return_url="https://verity.example/return", cancel_url="https://verity.example/cancel",
        )

    def provider_error(request):
        return httpx.Response(422, json={
            "name": "UNPROCESSABLE_ENTITY", "message": "Invalid request", "details": [
                {"issue": "INVALID_REQUEST", "description": "sandbox-secret is invalid"},
            ],
        })

    error_gateway = PayPalGatewayClient(_settings(), client=httpx.Client(transport=httpx.MockTransport(provider_error)))
    with caplog.at_level(logging.WARNING, logger="app.modules.reports.paypal"):
        with pytest.raises(PayPalProviderError, match="HTTP 422"):
            error_gateway._access_token()
    assert "UNPROCESSABLE_ENTITY" in caplog.text
    assert "sandbox-secret" not in caplog.text


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


def test_capture_parses_paypal_orders_v2_response_without_optional_custom_id(caplog):
    responses = []

    def handler(request):
        responses.append(request)
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "test-token"})
        assert request.headers["Prefer"] == "return=representation"
        return httpx.Response(201, json={
            "id": "ORDER-5", "status": "COMPLETED",
            "payment_source": {"paypal": {"email_address": "synthetic-buyer@example.test"}},
            "purchase_units": [{
                "reference_id": "default",
                "shipping": {"address": {"country_code": "US"}},
                "payments": {"captures": [{
                    "id": "CAPTURE-5", "status": "COMPLETED",
                    "amount": {"currency_code": "USD", "value": "5.00"},
                    "final_capture": True,
                    "links": [
                        {"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/CAPTURE-5"},
                        {"rel": "refund", "href": "https://api-m.sandbox.paypal.com/v2/payments/captures/CAPTURE-5/refund"},
                        {"rel": "up", "href": "https://api-m.sandbox.paypal.com/v2/checkout/orders/ORDER-5"},
                    ],
                }]},
            }],
            "payer": {"email_address": "synthetic-buyer@example.test"},
            "links": [{"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/checkout/orders/ORDER-5"}],
        })

    gateway = PayPalGatewayClient(_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    with caplog.at_level(logging.INFO, logger="app.modules.reports.paypal"):
        first = gateway.capture_order(order_id="ORDER-5", request_id="capture-retry-stable")
        repeated = gateway.capture_order(order_id="ORDER-5", request_id="capture-retry-stable")

    assert first.order_id == "ORDER-5"
    assert first.order_status == "COMPLETED"
    assert first.capture_id == "CAPTURE-5"
    assert first.capture_status == "COMPLETED"
    assert first.amount == Decimal("5.00") and first.currency == "USD"
    assert first.report_reference is None
    assert repeated.capture_id == first.capture_id
    assert [request.headers["PayPal-Request-Id"] for request in responses if request.url.path.endswith("/capture")] == [
        "capture-retry-stable", "capture-retry-stable",
    ]
    assert "order_status=COMPLETED capture_status=COMPLETED" in caplog.text
    assert "reference_id" in caplog.text and "purchase_units" in caplog.text
    assert "self" in caplog.text and "refund" in caplog.text and "up" in caplog.text
    assert "synthetic-buyer@example.test" not in caplog.text
    assert "CAPTURE-5" not in caplog.text


def test_declined_capture_response_is_parsed_as_declined_not_as_incomplete():
    def handler(request):
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "test-token"})
        return httpx.Response(201, json={
            "id": "ORDER-6", "status": "COMPLETED",
            "purchase_units": [{"payments": {"captures": [{
                "id": "CAPTURE-6", "status": "DECLINED",
                "amount": {"currency_code": "USD", "value": "5.00"},
            }]}}],
        })

    gateway = PayPalGatewayClient(_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = gateway.capture_order(order_id="ORDER-6", request_id="declined-capture")
    assert result.capture_status == "DECLINED"


def test_completed_minimal_capture_retrieves_order_details_without_recapturing(caplog):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "test-token"})
        if request.method == "POST":
            assert request.headers["Prefer"] == "return=representation"
            return httpx.Response(200, json={
                "id": "ORDER-7", "status": "COMPLETED",
                "links": [{"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/checkout/orders/ORDER-7"}],
            })
        assert request.method == "GET"
        assert request.headers["Prefer"] == "return=representation"
        return httpx.Response(200, json={
            "id": "ORDER-7", "status": "COMPLETED",
            "purchase_units": [{"reference_id": "default", "payments": {"captures": [{
                "id": "CAPTURE-7", "status": "COMPLETED",
                "amount": {"currency_code": "USD", "value": "5.00"},
            }]}}],
            "links": [{"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/checkout/orders/ORDER-7"}],
        })

    gateway = PayPalGatewayClient(_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    with caplog.at_level(logging.INFO, logger="app.modules.reports.paypal"):
        capture = gateway.capture_order(order_id="ORDER-7", request_id="minimal-response")
    assert capture.capture_id == "CAPTURE-7"
    assert capture.capture_status == "COMPLETED"
    assert [request.method for request in requests if (
        request.url.path.endswith("ORDER-7") or request.url.path.endswith("ORDER-7/capture")
    )] == ["POST", "GET"]
    assert "retrieving order details" in caplog.text


def test_minimal_capture_and_minimal_order_lookup_remain_unverified(caplog):
    def handler(request):
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "test-token"})
        return httpx.Response(200, json={
            "id": "ORDER-8", "status": "COMPLETED",
            "links": [{"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/checkout/orders/ORDER-8"}],
        })

    gateway = PayPalGatewayClient(_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    with caplog.at_level(logging.WARNING, logger="app.modules.reports.paypal"):
        with pytest.raises(PayPalProviderError, match="incomplete capture"):
            gateway.capture_order(order_id="ORDER-8", request_id="minimal-response")
    assert "purchase_units[0]" in caplog.text
    assert "ORDER-8" not in caplog.text


def test_already_captured_error_is_reconciled_by_reading_order_details(caplog):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "test-token"})
        if request.method == "POST":
            return httpx.Response(422, json={
                "name": "UNPROCESSABLE_ENTITY",
                "details": [{"issue": "ORDER_ALREADY_CAPTURED", "description": "Synthetic payer detail"}],
            })
        return httpx.Response(200, json={
            "id": "ORDER-9", "status": "COMPLETED",
            "purchase_units": [{"reference_id": "default", "payments": {"captures": [{
                "id": "CAPTURE-9", "status": "COMPLETED",
                "amount": {"currency_code": "USD", "value": "5.00"},
            }]}}],
        })

    gateway = PayPalGatewayClient(_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    with caplog.at_level(logging.INFO, logger="app.modules.reports.paypal"):
        capture = gateway.capture_order(order_id="ORDER-9", request_id="stable-capture-key")
    assert capture.capture_id == "CAPTURE-9"
    assert capture.capture_status == "COMPLETED"
    assert [request.method for request in requests if not request.url.path.endswith("/v1/oauth2/token")] == ["POST", "GET"]
    assert "ORDER_ALREADY_CAPTURED" in caplog.text
    assert "Synthetic payer detail" not in caplog.text
    assert "ORDER-9" not in caplog.text and "CAPTURE-9" not in caplog.text
