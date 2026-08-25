"""A74: the shop will not sell at a price nobody has confirmed.

`PRICE_MINOR_*` ships with placeholder numbers, and a placeholder is a
perfectly valid integer — nothing downstream can tell it apart from a real
price. `PRICES_CONFIRMED` is the switch that says somebody looked. It is off
by default, so the failure mode of forgetting it is "no orders", not "every
order underpriced until someone notices on a bank statement".
"""
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.order import Order
from tests.api.test_checkout import do_checkout, ready_book


@pytest.fixture
def unconfirmed(monkeypatch):
    """Put the shop back in its shipped state: prices not confirmed."""
    monkeypatch.setenv("PRICES_CONFIRMED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestTheDefaultIsClosed:
    def test_a_fresh_install_has_not_confirmed_its_prices(self, monkeypatch):
        """The whole point: nobody has to remember to turn this ON to be
        safe. They have to remember to turn it OFF to be sorry."""
        monkeypatch.delenv("PRICES_CONFIRMED", raising=False)
        get_settings.cache_clear()
        try:
            assert get_settings().prices_confirmed is False
        finally:
            get_settings.cache_clear()


class TestCheckoutRefuses:
    async def test_checkout_is_refused_while_prices_are_placeholders(
            self, client, db, unconfirmed):
        book_id, headers = await ready_book(client, db)
        resp = await do_checkout(client, book_id, headers)
        assert resp.status_code == 503, resp.text
        assert resp.json()["error"]["code"] == "PRICES_NOT_CONFIRMED"

    async def test_no_order_row_is_left_behind(self, client, db, unconfirmed):
        """A refusal that still created a draft order would be worse than
        no refusal — the operator would see an order they cannot honour."""
        book_id, headers = await ready_book(client, db)
        await do_checkout(client, book_id, headers)
        assert (await db.execute(select(Order))).scalars().all() == []

    async def test_the_book_is_not_locked_by_a_refused_checkout(
            self, client, db, unconfirmed):
        """The customer's work survives. They can keep editing and order
        the moment the prices are confirmed."""
        book_id, headers = await ready_book(client, db)
        await do_checkout(client, book_id, headers)
        book = (await client.get(f"/api/v1/books/{book_id}",
                                 headers=headers)).json()
        assert book["status"] == "draft"

    async def test_the_message_says_nothing_was_charged(
            self, client, db, unconfirmed):
        book_id, headers = await ready_book(client, db)
        message = (await do_checkout(client, book_id, headers)
                   ).json()["error"]["message"]
        assert "charged" in message.lower()

    async def test_confirming_the_prices_opens_the_shop(
            self, client, db, monkeypatch):
        """Same book, same request — the only thing that changed is the
        flag, which is what makes it a switch and not a code change."""
        book_id, headers = await ready_book(client, db)

        monkeypatch.setenv("PRICES_CONFIRMED", "false")
        get_settings.cache_clear()
        assert (await do_checkout(client, book_id, headers)).status_code == 503

        monkeypatch.setenv("PRICES_CONFIRMED", "true")
        get_settings.cache_clear()
        resp = await do_checkout(client, book_id, headers)
        assert resp.status_code == 201, resp.text
        assert resp.json()["amount_minor"] == get_settings().price_minor_16


class TestPricesAreStillQuoted:
    async def test_the_price_list_still_answers(self, client, unconfirmed):
        """Hiding the numbers would leave the tier picker blank and tell the
        customer nothing. Quote them, and say they are not final."""
        body = (await client.get("/api/v1/prices")).json()
        assert body["confirmed"] is False
        assert body["prices"]["16"] == get_settings().price_minor_16

    async def test_confirmed_is_true_when_it_is(self, client):
        assert (await client.get("/api/v1/prices")).json()["confirmed"] is True
