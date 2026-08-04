"""Dev payment provider (founder decision, 5 Aug 2026): real acquirer
integration is deferred; in dev mode a correctly-signed webhook is treated as
a completed payment. Everything around it — signature gate, amount
verification, idempotency, effects — is the production machinery, so a real
provider later replaces only this file.
"""
import hmac

from app.config import get_settings
from app.domain.errors import DomainError, ErrorCode
from app.payments.base import ParsedEvent

SIGNATURE_HEADER = "x-dev-signature"


class DevPaymentProvider:
    name = "dev"

    def verify_webhook(self, headers: dict[str, str], body: dict) -> bool:
        secret = get_settings().dev_payment_secret
        provided = headers.get(SIGNATURE_HEADER, "")
        return bool(secret) and hmac.compare_digest(provided, secret)

    def parse_event(self, body: dict) -> ParsedEvent:
        try:
            event_id = str(body["event_id"])
            method = body["action"]
            human_ref = str(body["human_ref"])
        except (KeyError, TypeError) as exc:
            raise DomainError(
                ErrorCode.VALIDATION_ERROR,
                "webhook payload must contain event_id, action and human_ref",
            ) from exc
        if method not in ("pay", "cancel"):
            raise DomainError(ErrorCode.VALIDATION_ERROR,
                              f"unsupported action {method!r}")
        amount = body.get("amount_minor")
        if method == "pay":
            if not isinstance(amount, int) or isinstance(amount, bool):
                raise DomainError(ErrorCode.VALIDATION_ERROR,
                                  "pay events must carry integer amount_minor")
        else:
            amount = None
        return ParsedEvent(event_id=event_id, method=method,
                           human_ref=human_ref, amount_minor=amount, raw=body)

    def build_checkout_payload(self, order) -> dict:
        return {
            "provider": self.name,
            "human_ref": order.human_ref,
            "amount_minor": order.amount_minor,
            "currency": order.currency,
            "webhook": "/api/v1/payments/dev/webhook",
            "note": "dev mode: POST the webhook with the shared signature "
                    "header to mark this order paid",
        }
