import pytest

from app.domain.errors import IllegalTransition
from app.domain.states import (
    ORDER_TRANSITIONS,
    BookStatus,
    Effect,
    OrderStatus,
    layout_mutable,
    transition_book,
    transition_order,
)


def test_every_legal_transition_succeeds():
    for source, targets in ORDER_TRANSITIONS.items():
        for target in targets:
            transition_order(source, target)  # must not raise


@pytest.mark.parametrize("source,target", [
    (OrderStatus.DRAFT_ORDER, OrderStatus.RENDERED),
    (OrderStatus.PAID, OrderStatus.PENDING_PAYMENT),
    (OrderStatus.DELIVERED, OrderStatus.PAID),
    (OrderStatus.CANCELLED, OrderStatus.PAID),
    (OrderStatus.REFUNDED, OrderStatus.SHIPPED),
    (OrderStatus.PENDING_PAYMENT, OrderStatus.RENDERING),
])
def test_illegal_transitions_raise(source, target):
    with pytest.raises(IllegalTransition):
        transition_order(source, target)


def test_entering_paid_enqueues_exactly_one_render_job():
    for source, targets in ORDER_TRANSITIONS.items():
        if OrderStatus.PAID in targets:
            effects = transition_order(source, OrderStatus.PAID)
            assert effects.count(Effect.ENQUEUE_RENDER) == 1


def test_no_other_transition_enqueues_render():
    for source, targets in ORDER_TRANSITIONS.items():
        for target in targets:
            if target is not OrderStatus.PAID:
                assert Effect.ENQUEUE_RENDER not in transition_order(source, target)


def test_render_failed_alerts_operator():
    effects = transition_order(OrderStatus.RENDERING, OrderStatus.RENDER_FAILED)
    assert Effect.ALERT_OPERATOR in effects


@pytest.mark.parametrize("source", [
    OrderStatus.PENDING_PAYMENT, OrderStatus.PAID, OrderStatus.RENDERING,
    OrderStatus.RENDER_FAILED, OrderStatus.RENDERED,
])
def test_operator_can_cancel_before_production(source):
    # Trust-first pilot (A56): auto-confirmed orders skip pending_payment,
    # so cancellation must stay possible until the book physically prints.
    transition_order(source, OrderStatus.CANCELLED)  # must not raise


def test_no_cancel_once_in_production():
    for source in (OrderStatus.SENT_TO_PRODUCTION, OrderStatus.SHIPPED,
                   OrderStatus.DELIVERED):
        with pytest.raises(IllegalTransition):
            transition_order(source, OrderStatus.CANCELLED)


class TestBookStates:
    def test_locking_makes_layout_immutable(self):
        transition_book(BookStatus.DRAFT, BookStatus.LOCKED)
        assert layout_mutable(BookStatus.DRAFT)
        assert not layout_mutable(BookStatus.LOCKED)
        assert not layout_mutable(BookStatus.ORDERED)
        assert not layout_mutable(BookStatus.EXPIRED)

    def test_ordered_books_are_terminal(self):
        with pytest.raises(IllegalTransition):
            transition_book(BookStatus.ORDERED, BookStatus.EXPIRED)

    def test_cancelled_payment_unlocks_book(self):
        transition_book(BookStatus.LOCKED, BookStatus.DRAFT)  # must not raise

    def test_expired_cannot_revive(self):
        with pytest.raises(IllegalTransition):
            transition_book(BookStatus.EXPIRED, BookStatus.DRAFT)
