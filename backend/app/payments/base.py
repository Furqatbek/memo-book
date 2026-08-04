"""Payment provider abstraction (spec Part 8).

Real acquirers (Payme, Click, Uzum) each implement this protocol with their
own method names, signature algorithms and amount units — verified against
current provider documentation at integration time. Amounts cross this
boundary as integers in tiyin; conversion to provider units happens inside
the provider only.
"""
from dataclasses import dataclass, field
from typing import Literal, Protocol

Method = Literal["pay", "cancel"]


@dataclass(frozen=True)
class ParsedEvent:
    event_id: str
    method: Method
    human_ref: str
    amount_minor: int | None  # None for events that carry no amount (cancel)
    raw: dict = field(default_factory=dict)


class PaymentProvider(Protocol):
    name: str

    def verify_webhook(self, headers: dict[str, str], body: dict) -> bool:
        """Signature check. Runs BEFORE any parsing; a False here must reject
        the callback with no state change of any kind."""
        ...

    def parse_event(self, body: dict) -> ParsedEvent:
        ...

    def build_checkout_payload(self, order) -> dict:
        """Provider-specific data the frontend needs to start the payment."""
        ...
