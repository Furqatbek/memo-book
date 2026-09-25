"""Order and book state machines (spec Part 3).

Legal transitions only: an explicit map, raising on anything else. Arbitrary
code must never assign `order.status` directly. Transitions carry declared
side effects (e.g. entering `paid` enqueues exactly one render job) so the
rule "render is triggered only by payment" (R8) lives here, not in handlers.
"""
from enum import StrEnum

from app.domain.errors import IllegalTransition


class OrderStatus(StrEnum):
    DRAFT_ORDER = "draft_order"
    PENDING_PAYMENT = "pending_payment"
    CANCELLED = "cancelled"
    PAID = "paid"
    RENDERING = "rendering"
    RENDER_FAILED = "render_failed"
    RENDERED = "rendered"
    SENT_TO_PRODUCTION = "sent_to_production"
    # The three stages the customer actually hears about (CR-003-2). The
    # 30-day wait was silent, and silence produces support messages,
    # anxiety and cancellation requests; these turn dead time into
    # anticipation, and cost the operator three taps.
    PRINTING = "printing"
    BINDING = "binding"
    QUALITY_CHECK = "quality_check"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    REFUNDED = "refunded"


ORDER_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.DRAFT_ORDER: frozenset({OrderStatus.PENDING_PAYMENT}),
    OrderStatus.PENDING_PAYMENT: frozenset({OrderStatus.PAID, OrderStatus.CANCELLED}),
    # cancelled -> pending_payment: re-checkout of the same book reuses its
    # one order row (unique book_id) with a fresh audit event (assumption A33).
    OrderStatus.CANCELLED: frozenset({OrderStatus.PENDING_PAYMENT}),
    # paid/rendering/render_failed/rendered -> cancelled: in the trust-first
    # card pilot orders confirm automatically, so the operator (who verifies
    # the bank transfer by hand) must be able to cancel any time before the
    # book physically goes to production (A56).
    OrderStatus.PAID: frozenset({OrderStatus.RENDERING, OrderStatus.CANCELLED}),
    # render_failed -> rendering is the operator retry path (assumption A5).
    OrderStatus.RENDERING: frozenset({OrderStatus.RENDERED,
                                      OrderStatus.RENDER_FAILED,
                                      OrderStatus.CANCELLED}),
    OrderStatus.RENDER_FAILED: frozenset({OrderStatus.RENDERING,
                                          OrderStatus.CANCELLED}),
    OrderStatus.RENDERED: frozenset({OrderStatus.SENT_TO_PRODUCTION,
                                     OrderStatus.CANCELLED}),
    # Forward skips are allowed on purpose. An operator who has to click
    # through every stage to record reality will stop recording it, and a
    # status nobody updates is worse than one with gaps.
    OrderStatus.SENT_TO_PRODUCTION: frozenset({OrderStatus.PRINTING,
                                               OrderStatus.BINDING,
                                               OrderStatus.QUALITY_CHECK,
                                               OrderStatus.SHIPPED}),
    OrderStatus.PRINTING: frozenset({OrderStatus.BINDING,
                                     OrderStatus.QUALITY_CHECK,
                                     OrderStatus.SHIPPED}),
    OrderStatus.BINDING: frozenset({OrderStatus.QUALITY_CHECK,
                                    OrderStatus.SHIPPED}),
    OrderStatus.QUALITY_CHECK: frozenset({OrderStatus.SHIPPED}),
    OrderStatus.SHIPPED: frozenset({OrderStatus.DELIVERED, OrderStatus.REFUNDED}),
    OrderStatus.DELIVERED: frozenset({OrderStatus.REFUNDED}),
    OrderStatus.REFUNDED: frozenset(),
}


class Effect(StrEnum):
    """Side effects a transition mandates. The service layer executes these;
    the domain only declares them."""

    ENQUEUE_RENDER = "enqueue_render"
    ALERT_OPERATOR = "alert_operator"
    NOTIFY_PRODUCTION = "notify_production"
    # CR-003-5. Declared here so it is visible in the same place as every
    # other consequence of a status — but it is the only effect in this
    # file whose failure is allowed to be invisible, because a missing
    # video must never touch an order.
    MAKE_FLIP_VIDEO = "make_flip_video"


EFFECTS_ON_ENTER: dict[OrderStatus, tuple[Effect, ...]] = {
    OrderStatus.PAID: (Effect.ENQUEUE_RENDER,),          # R8: the only render trigger
    OrderStatus.RENDER_FAILED: (Effect.ALERT_OPERATOR,),
    OrderStatus.RENDERED: (Effect.NOTIFY_PRODUCTION, Effect.MAKE_FLIP_VIDEO),
}


def transition_order(current: OrderStatus, target: OrderStatus) -> tuple[Effect, ...]:
    """Validate a transition and return the effects entering `target` mandates.
    Raises IllegalTransition for anything not in the map."""
    allowed = ORDER_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise IllegalTransition(
            f"illegal order transition {current} -> {target}",
            {"from": current, "to": target, "allowed": sorted(allowed)},
        )
    return EFFECTS_ON_ENTER.get(target, ())


class BookStatus(StrEnum):
    DRAFT = "draft"
    LOCKED = "locked"
    ORDERED = "ordered"
    EXPIRED = "expired"


BOOK_TRANSITIONS: dict[BookStatus, frozenset[BookStatus]] = {
    BookStatus.DRAFT: frozenset({BookStatus.LOCKED, BookStatus.EXPIRED}),
    # locked -> draft unlocks the book when payment is cancelled (assumption A6).
    BookStatus.LOCKED: frozenset({BookStatus.ORDERED, BookStatus.DRAFT}),
    # ordered -> draft: an operator cancel of an auto-confirmed order (A56)
    # returns the book to editing. Ordered books still never expire (R6).
    BookStatus.ORDERED: frozenset({BookStatus.DRAFT}),
    BookStatus.EXPIRED: frozenset(),
}

# Book statuses in which layout mutation endpoints must return 423 Locked.
LAYOUT_IMMUTABLE_STATUSES = frozenset({BookStatus.LOCKED, BookStatus.ORDERED,
                                       BookStatus.EXPIRED})


def transition_book(current: BookStatus, target: BookStatus) -> None:
    allowed = BOOK_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise IllegalTransition(
            f"illegal book transition {current} -> {target}",
            {"from": current, "to": target, "allowed": sorted(allowed)},
        )


def layout_mutable(status: BookStatus) -> bool:
    return status not in LAYOUT_IMMUTABLE_STATUSES
