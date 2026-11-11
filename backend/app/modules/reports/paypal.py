"""PayPal REST Orders v2 adapter for the explicitly configured Sandbox."""

from decimal import Decimal, InvalidOperation
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.modules.reports.config import PayPalSettings
from app.modules.reports.payments import PayPalCapture, PayPalOrder


class PayPalProviderError(RuntimeError):
    """Sanitized provider or transport failure safe to return to API callers."""

    def __init__(self, message: str, *, provider_codes: set[str] | None = None) -> None:
        super().__init__(message)
        self.provider_codes = frozenset(provider_codes or ())


logger = logging.getLogger(__name__)
_SAFE_APPROVAL_HOSTS = {"www.sandbox.paypal.com", "sandbox.paypal.com"}


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
                 form: dict | None = None, basic_auth: tuple[str, str] | None = None,
                 prefer: str | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        if prefer:
            headers["Prefer"] = prefer
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
            sensitive = (token, *(basic_auth or ()))
            codes = _provider_error_codes(response, sensitive=sensitive)
            _log_provider_error(response, sensitive=sensitive, codes=codes)
            raise PayPalProviderError(
                f"PayPal rejected the request (HTTP {response.status_code}).", provider_codes=codes,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning("PayPal returned malformed JSON (HTTP %s).", response.status_code)
            raise PayPalProviderError("PayPal returned an invalid response.") from exc
        if not isinstance(payload, dict):
            logger.warning("PayPal returned a non-object JSON response (HTTP %s).", response.status_code)
            raise PayPalProviderError("PayPal returned an invalid response.")
        if path == "/v1/oauth2/token":
            operation = "OAuth"
        elif path == "/v2/checkout/orders":
            operation = "order creation"
        else:
            operation = "payment operation"
        logger.info("PayPal %s completed with HTTP %s.", operation, response.status_code)
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
            prefer="return=representation",
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
            approval_url = next(
                link["href"] for link in payload.get("links", [])
                if isinstance(link, dict) and link.get("rel") in {"approve", "payer-action"}
            )
            approval_url = _sandbox_approval_url(approval_url)
            return PayPalOrder(
                order_id=_required_text(payload.get("id")),
                status=_required_text(payload.get("status")),
                approval_url=_required_text(approval_url),
                amount=_decimal(amount_data.get("value")),
                currency=_required_text(amount_data.get("currency_code")),
            )
        except (KeyError, IndexError, StopIteration, TypeError, ValueError) as exc:
            logger.warning("PayPal order response is missing or invalid fields: %s.", _missing_order_fields(payload))
            raise PayPalProviderError("PayPal returned an incomplete order response.") from exc

    def capture_order(self, *, order_id: str, request_id: str) -> PayPalCapture:
        path = f"/v2/checkout/orders/{_path_segment(order_id)}"
        token = self._access_token()
        try:
            payload = self._request(
                "POST", f"{path}/capture", token=token, request_id=request_id,
                prefer="return=representation", json={},
            )
        except PayPalProviderError as exc:
            if "ORDER_ALREADY_CAPTURED" not in exc.provider_codes:
                raise
            logger.info("PayPal reports the order was already captured; retrieving order details for verification.")
            payload = self._request("GET", path, token=token, prefer="return=representation")
        # A prior capture attempt may have been cached under this idempotency
        # key with PayPal's default minimal representation. Never capture again
        # with a new key; read the already-completed order to verify its facts.
        if (
            not _has_capture_details(payload)
            and payload.get("id") == order_id
            and payload.get("status") == "COMPLETED"
        ):
            logger.info("PayPal returned a completed order without capture details; retrieving order details.")
            payload = self._request("GET", path, token=token, prefer="return=representation")
        return _capture_from_order(payload, provider_verified=True)


def _capture_from_order(payload: dict[str, Any], *, provider_verified: bool) -> PayPalCapture:
    _log_capture_response_shape(payload)
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
        unit_reference = _optional_text(unit.get("custom_id"))
        capture_reference = _optional_text(capture.get("custom_id"))
        if unit_reference and capture_reference and unit_reference != capture_reference:
            raise ValueError("conflicting report references")
        return PayPalCapture(
            order_id=_required_text(payload.get("id")),
            capture_id=_required_text(capture.get("id")),
            order_status=_required_text(payload.get("status")),
            capture_status=_required_text(capture.get("status")),
            amount=_decimal(amount.get("value")),
            currency=_required_text(amount.get("currency_code")),
            provider_verified=provider_verified,
            report_reference=unit_reference or capture_reference,
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        missing = _missing_capture_fields(payload)
        logger.warning(
            "PayPal capture response is missing or invalid fields: %s.",
            missing or ["invalid field value or conflicting report reference"],
        )
        raise PayPalProviderError("PayPal returned an incomplete capture response.") from exc


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _required_text(value)


def _has_capture_details(payload: dict[str, Any]) -> bool:
    units = payload.get("purchase_units")
    if not isinstance(units, list) or len(units) != 1 or not isinstance(units[0], dict):
        return False
    payments = units[0].get("payments")
    captures = payments.get("captures") if isinstance(payments, dict) else None
    return isinstance(captures, list) and len(captures) == 1 and isinstance(captures[0], dict)


_ORDER_STATUSES = {"CREATED", "SAVED", "APPROVED", "VOIDED", "COMPLETED", "PAYER_ACTION_REQUIRED"}
_CAPTURE_STATUSES = {"COMPLETED", "DECLINED", "PARTIALLY_REFUNDED", "PENDING", "REFUNDED", "FAILED"}
_SAFE_LINK_RELS = {"self", "up", "refund", "capture", "authorize", "approve", "payer-action"}


def _field_names(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return sorted(key for key in value if isinstance(key, str) and re.fullmatch(r"[a-z_]{1,64}", key))


def _safe_status(value: Any, allowed: set[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _safe_link_rels(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({
        link["rel"] for link in value
        if isinstance(link, dict) and link.get("rel") in _SAFE_LINK_RELS
    })


def _log_capture_response_shape(payload: dict[str, Any]) -> None:
    """Log schema/status diagnostics only; omit IDs, URLs, amounts and payer data."""
    units = payload.get("purchase_units")
    unit = units[0] if isinstance(units, list) and units and isinstance(units[0], dict) else {}
    payments = unit.get("payments")
    captures = payments.get("captures") if isinstance(payments, dict) else None
    capture = captures[0] if isinstance(captures, list) and captures and isinstance(captures[0], dict) else {}
    amount = capture.get("amount")
    logger.info(
        "PayPal capture response shape: order_status=%s capture_status=%s top_level_fields=%s "
        "purchase_unit_fields=%s capture_fields=%s capture_amount_fields=%s "
        "top_level_link_rels=%s capture_link_rels=%s",
        _safe_status(payload.get("status"), _ORDER_STATUSES),
        _safe_status(capture.get("status"), _CAPTURE_STATUSES),
        _field_names(payload), _field_names(unit), _field_names(capture), _field_names(amount),
        _safe_link_rels(payload.get("links")), _safe_link_rels(capture.get("links")),
    )


def _missing_capture_fields(payload: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not isinstance(payload.get("id"), str) or not payload.get("id", "").strip():
        missing.append("id")
    if not isinstance(payload.get("status"), str) or not payload.get("status", "").strip():
        missing.append("status")
    units = payload.get("purchase_units")
    if not isinstance(units, list) or len(units) != 1 or not isinstance(units[0], dict):
        missing.append("purchase_units[0]")
        return missing
    unit = units[0]
    payments = unit.get("payments")
    captures = payments.get("captures") if isinstance(payments, dict) else None
    if not isinstance(captures, list) or len(captures) != 1 or not isinstance(captures[0], dict):
        missing.append("purchase_units[0].payments.captures[0]")
        return missing
    capture = captures[0]
    for field in ("id", "status"):
        if not isinstance(capture.get(field), str) or not capture.get(field, "").strip():
            missing.append(f"purchase_units[0].payments.captures[0].{field}")
    amount = capture.get("amount")
    if not isinstance(amount, dict):
        missing.append("purchase_units[0].payments.captures[0].amount")
    else:
        if amount.get("value") is None:
            missing.append("purchase_units[0].payments.captures[0].amount.value")
        if not amount.get("currency_code"):
            missing.append("purchase_units[0].payments.captures[0].amount.currency_code")
    return missing


def _required_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing text field")
    return value


def _sandbox_approval_url(value: Any) -> str:
    url = _required_text(value)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _SAFE_APPROVAL_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.fragment
    ):
        raise ValueError("approval link is not a PayPal Sandbox URL")
    return url


def _missing_order_fields(payload: dict[str, Any]) -> list[str]:
    """Return field names only; never include response values in diagnostics."""
    missing: list[str] = []
    if not isinstance(payload.get("id"), str) or not payload.get("id", "").strip():
        missing.append("id")
    if not isinstance(payload.get("status"), str) or not payload.get("status", "").strip():
        missing.append("status")
    units = payload.get("purchase_units")
    if not isinstance(units, list) or len(units) != 1 or not isinstance(units[0], dict):
        missing.append("purchase_units[0]")
    else:
        amount = units[0].get("amount")
        if not isinstance(amount, dict):
            missing.append("purchase_units[0].amount")
        else:
            if not amount.get("value"):
                missing.append("purchase_units[0].amount.value")
            if not amount.get("currency_code"):
                missing.append("purchase_units[0].amount.currency_code")
    links = payload.get("links")
    approval_links = [
        link for link in links if isinstance(link, dict)
        and link.get("rel") in {"approve", "payer-action"}
    ] if isinstance(links, list) else []
    if not approval_links or not any(isinstance(link.get("href"), str) and link["href"].strip() for link in approval_links):
        missing.append("links[approve|payer-action].href")
    return missing


def _safe_error_code(value: Any, sensitive: tuple[str | None, ...] = ()) -> str | None:
    if not isinstance(value, str) or any(secret and secret in value for secret in sensitive):
        return None
    return value if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", value) else None


def _provider_error_codes(
    response: httpx.Response, *, sensitive: tuple[str | None, ...] = (),
) -> set[str]:
    try:
        payload = response.json()
    except ValueError:
        return set()
    if not isinstance(payload, dict):
        return set()
    codes: set[str] = set()
    name = _safe_error_code(payload.get("name"), sensitive)
    if name:
        codes.add(name)
    details = payload.get("details")
    if isinstance(details, list):
        codes.update(
            code for item in details if isinstance(item, dict)
            if (code := _safe_error_code(item.get("issue"), sensitive)) is not None
        )
    return codes


def _log_provider_error(
    response: httpx.Response, *, sensitive: tuple[str | None, ...] = (), codes: set[str] | None = None,
) -> None:
    """Log selected, sanitized PayPal error fields without retaining the response body."""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    details = payload.get("details")
    detail_items = details if isinstance(details, list) else []
    issues = sorted({
        code for item in detail_items if isinstance(item, dict)
        if (code := _safe_error_code(item.get("issue"), sensitive)) is not None
    })
    safe_codes = codes if codes is not None else _provider_error_codes(response, sensitive=sensitive)
    logger.warning(
        "PayPal returned HTTP %s error name=%r provider_codes=%s issue_codes=%s detail_count=%s",
        response.status_code,
        _safe_error_code(payload.get("name"), sensitive),
        sorted(safe_codes),
        issues,
        len(detail_items),
    )


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
