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
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    REFUNDED = "refunded"


ORDER_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.DRAFT_ORDER: frozenset({OrderStatus.PENDING_PAYMENT}),
    OrderStatus.PENDING_PAYMENT: frozenset({OrderStatus.PAID, OrderStatus.CANCELLED}),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.PAID: frozenset({OrderStatus.RENDERING}),
    # render_failed -> rendering is the operator retry path (assumption A5).
    OrderStatus.RENDERING: frozenset({OrderStatus.RENDERED, OrderStatus.RENDER_FAILED}),
    OrderStatus.RENDER_FAILED: frozenset({OrderStatus.RENDERING}),
    OrderStatus.RENDERED: frozenset({OrderStatus.SENT_TO_PRODUCTION}),
    OrderStatus.SENT_TO_PRODUCTION: frozenset({OrderStatus.SHIPPED}),
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


EFFECTS_ON_ENTER: dict[OrderStatus, tuple[Effect, ...]] = {
    OrderStatus.PAID: (Effect.ENQUEUE_RENDER,),          # R8: the only render trigger
    OrderStatus.RENDER_FAILED: (Effect.ALERT_OPERATOR,),
    OrderStatus.RENDERED: (Effect.NOTIFY_PRODUCTION,),
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
    BookStatus.ORDERED: frozenset(),   # ordered books are never expired (R6)
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
