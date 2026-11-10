"""PayPal REST Orders v2 adapter for the explicitly configured Sandbox."""

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.modules.reports.config import PayPalSettings
from app.modules.reports.payments import PayPalCapture, PayPalOrder


class PayPalProviderError(RuntimeError):
    """Sanitized provider or transport failure safe to return to API callers."""


class PayPalGatewayClient:
    def __init__(self, settings: PayPalSettings, *, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(settings.timeout_seconds, connect=min(5.0, settings.timeout_seconds))
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(self, method: str, path: str, *, token: str | None = None,
                 request_id: str | None = None, json: dict | None = None,
                 form: dict | None = None, basic_auth: tuple[str, str] | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        try:
            response = self._client.request(
                method,
                f"{self.settings.base_url}{path}",
                headers=headers,
                json=json,
                data=form,
                auth=basic_auth,
            )
        except httpx.TimeoutException as exc:
            raise PayPalProviderError("PayPal did not respond before the request timed out.") from exc
        except httpx.HTTPError as exc:
            raise PayPalProviderError("PayPal could not be reached.") from exc
        if response.is_error:
            raise PayPalProviderError(f"PayPal rejected the request (HTTP {response.status_code}).")
        try:
            payload = response.json()
        except ValueError as exc:
            raise PayPalProviderError("PayPal returned an invalid response.") from exc
        if not isinstance(payload, dict):
            raise PayPalProviderError("PayPal returned an invalid response.")
        return payload

    def _access_token(self) -> str:
        payload = self._request(
            "POST", "/v1/oauth2/token", form={"grant_type": "client_credentials"},
            basic_auth=(self.settings.client_id, self.settings.client_secret),
        )
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise PayPalProviderError("PayPal authentication failed.")
        return token

    def create_order(self, *, request_id: str, amount: Decimal, currency: str,
                     report_reference: str, return_url: str, cancel_url: str) -> PayPalOrder:
        payload = self._request(
            "POST", "/v2/checkout/orders", token=self._access_token(), request_id=request_id,
            json={
                "intent": "CAPTURE",
                "purchase_units": [{
                    "custom_id": report_reference,
                    "amount": {"currency_code": currency, "value": format(amount, ".2f")},
                }],
                "application_context": {
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                    "user_action": "PAY_NOW",
                },
            },
        )
        try:
            units = payload["purchase_units"]
            if len(units) != 1:
                raise ValueError("unexpected purchase unit count")
            unit = units[0]
            amount_data = unit["amount"]
            approval_url = next(link["href"] for link in payload.get("links", []) if link.get("rel") == "approve")
            return PayPalOrder(
                order_id=_required_text(payload.get("id")),
                status=_required_text(payload.get("status")),
                approval_url=_required_text(approval_url),
                amount=_decimal(amount_data.get("value")),
                currency=_required_text(amount_data.get("currency_code")),
            )
        except (KeyError, IndexError, StopIteration, TypeError, ValueError) as exc:
            raise PayPalProviderError("PayPal returned an incomplete order response.") from exc

    def capture_order(self, *, order_id: str, request_id: str) -> PayPalCapture:
        payload = self._request(
            "POST", f"/v2/checkout/orders/{_path_segment(order_id)}/capture",
            token=self._access_token(), request_id=request_id, json={},
        )
        return _capture_from_order(payload, provider_verified=True)


def _capture_from_order(payload: dict[str, Any], *, provider_verified: bool) -> PayPalCapture:
    try:
        units = payload["purchase_units"]
        if len(units) != 1:
            raise ValueError("unexpected purchase unit count")
        unit = units[0]
        captures = unit["payments"]["captures"]
        if len(captures) != 1:
            raise ValueError("unexpected capture count")
        capture = captures[0]
        amount = capture["amount"]
        return PayPalCapture(
            order_id=_required_text(payload.get("id")),
            capture_id=_required_text(capture.get("id")),
            order_status=_required_text(payload.get("status")),
            capture_status=_required_text(capture.get("status")),
            amount=_decimal(amount.get("value")),
            currency=_required_text(amount.get("currency_code")),
            provider_verified=provider_verified,
            report_reference=_required_text(unit.get("custom_id")),
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise PayPalProviderError("PayPal returned an incomplete capture response.") from exc


def _required_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing text field")
    return value


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid amount") from exc
    if not result.is_finite():
        raise ValueError("invalid amount")
    return result


def _path_segment(value: str) -> str:
    from urllib.parse import quote

    if not value or len(value) > 128:
        raise PayPalProviderError("PayPal order reference is invalid.")
    return quote(value, safe="")
