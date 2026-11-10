"""Explicitly injected PayPal fake for unit tests; it performs no I/O."""

from app.modules.reports.payments import PayPalCapture, PayPalOrder, PayPalWebhookVerification


class FakePayPalGateway:
    def __init__(self, *, order: PayPalOrder | None = None, capture: PayPalCapture | None = None,
                 webhook: PayPalWebhookVerification | None = None):
        self.order = order
        self.capture = capture
        self.webhook = webhook
        self.calls: list[tuple[str, str | None]] = []

    def create_order(self, *, request_id, amount, currency, report_reference, return_url, cancel_url):
        self.calls.append(("create_order", request_id))
        if self.order is None:
            raise RuntimeError("No fake PayPal order response was configured.")
        return self.order

    def capture_order(self, *, order_id, request_id):
        self.calls.append(("capture_order", request_id))
        if self.capture is None:
            raise RuntimeError("No fake PayPal capture response was configured.")
        return self.capture

    def get_order(self, *, order_id):
        self.calls.append(("get_order", order_id))
        if self.capture is None:
            raise RuntimeError("No fake PayPal order verification response was configured.")
        return self.capture

    def verify_webhook(self, *, headers, event_body):
        self.calls.append(("verify_webhook", None))
        if self.webhook is None:
            raise RuntimeError("No fake PayPal webhook verification response was configured.")
        return self.webhook
