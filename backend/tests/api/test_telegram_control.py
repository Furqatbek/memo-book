"""A96: driving orders from the Telegram chat.

Two very different things are being tested here, and the first matters more.

**The lock.** This is the only inbound route in the system that is neither
the customer API nor the admin console, and it can cancel a paid order. A76
already decided the Telegram chat is untrusted — it is why the attention
alert withholds customer PII — so the tests that prove this surface does not
exist until it is deliberately switched on, and refuses anyone not on the
allowlist, are the load-bearing ones.

**The behaviour.** A press goes through `admin_orders.set_status`, which is
the console's own path, so the state machine and the audit trail apply
unchanged. What is specific here is that a keyboard on a phone is a cache of
the order's state, can be stale or pressed twice, and must not turn either
into a wrong write.
"""
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.order import Order, OrderEvent
from app.services import telegram as telegram_svc
from app.services import telegram_control
from tests.api.test_admin_orders import AUTH, an_order

SECRET = "test-webhook-secret"
ALLOWED = 424242
STRANGER = 999999
HOOK = "/api/v1/telegram/webhook"
HDRS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


@pytest.fixture
def control(monkeypatch):
    """Inbound control switched on, and every Telegram API call captured
    instead of made."""
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_CONTROL_USER_IDS", f"{ALLOWED}")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123")
    get_settings.cache_clear()
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(telegram_svc, "_call",
                        lambda method, body: calls.append((method, body)))
    yield calls
    get_settings.cache_clear()


def press(ref: str, target: str, user_id: int = ALLOWED) -> dict:
    return {"callback_query": {
        "id": "cb1", "from": {"id": user_id},
        "message": {"message_id": 7, "chat": {"id": -100123}},
        "data": f"o:{ref}:{target}"}}


def command(text: str, user_id: int = ALLOWED) -> dict:
    return {"message": {"message_id": 3, "from": {"id": user_id},
                        "chat": {"id": -100123}, "text": text}}


def answers(calls) -> list[str]:
    return [b.get("text", "") for m, b in calls if m == "answerCallbackQuery"]


async def rendered_order(client, db) -> str:
    ref = await an_order(client, db)
    await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                      headers=AUTH)
    return ref


async def status_of(db, ref: str) -> str:
    db.expire_all()
    return (await db.execute(
        select(Order).where(Order.human_ref == ref))).scalar_one().status


class TestTheLock:
    """Not configured means the route does not exist — the same property the
    admin API has, for the same reason."""

    async def test_no_secret_means_no_webhook(self, client, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "")
        monkeypatch.setenv("TELEGRAM_CONTROL_USER_IDS", f"{ALLOWED}")
        get_settings.cache_clear()
        try:
            resp = await client.post(HOOK, headers=HDRS, json=press("UB-X", "shipped"))
            assert resp.status_code == 404
        finally:
            get_settings.cache_clear()

    async def test_no_allowlist_means_no_webhook(self, client, monkeypatch):
        """A secret with nobody allowed to act would be an open door with a
        sign on it: updates accepted, every one of them refused."""
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
        monkeypatch.setenv("TELEGRAM_CONTROL_USER_IDS", "")
        get_settings.cache_clear()
        try:
            resp = await client.post(HOOK, headers=HDRS, json=press("UB-X", "shipped"))
            assert resp.status_code == 404
        finally:
            get_settings.cache_clear()

    async def test_a_wrong_secret_is_404_not_403(self, client, control):
        """404, never 401 or 403: this endpoint is not an oracle for whether
        an RS Pixel bot lives here."""
        resp = await client.post(
            HOOK, headers={"X-Telegram-Bot-Api-Secret-Token": "nope"},
            json=press("UB-X", "shipped"))
        assert resp.status_code == 404

    async def test_no_secret_header_at_all_is_404(self, client, control):
        assert (await client.post(HOOK, json=press("UB-X", "shipped"))
                ).status_code == 404

    async def test_the_right_secret_gets_in(self, client, control):
        resp = await client.post(HOOK, headers=HDRS, json={"update_id": 1})
        assert resp.status_code == 200


class TestWhoMayAct:
    async def test_a_stranger_in_the_chat_cannot_move_an_order(
            self, client, db, control):
        """The whole point of the allowlist. The chat holds seven-day signed
        links to every print file, so its readers are already a wider circle
        than its operators — reading must not imply cancelling."""
        ref = await rendered_order(client, db)
        resp = await client.post(
            HOOK, headers=HDRS,
            json=press(ref, "sent_to_production", user_id=STRANGER))
        assert resp.status_code == 200
        assert await status_of(db, ref) == "rendered", "a stranger moved an order"
        assert any("Not authorised" in a for a in answers(control))

    async def test_a_stranger_is_told_nothing_about_the_order(
            self, client, db, control):
        ref = await rendered_order(client, db)
        # Only what the REFUSAL said. Making the order also sends the print
        # notification, which carries the customer's name and phone on
        # purpose — it is the job sheet — so judging every message ever sent
        # would be asserting the opposite of what this is about.
        control.clear()
        await client.post(HOOK, headers=HDRS,
                          json=press(ref, "cancelled", user_id=STRANGER))
        said = " ".join(b.get("text", "") for _, b in control)
        assert ref not in said, "the refusal leaked the order reference"

    async def test_a_stranger_cannot_list_orders(self, client, db, control):
        await rendered_order(client, db)
        await client.post(HOOK, headers=HDRS,
                          json=command("/orders", user_id=STRANGER))
        said = " ".join(b.get("text", "") for _, b in control)
        assert "Not authorised" in said
        assert "open order" not in said

    async def test_the_allowlist_drops_rubbish_rather_than_guessing(
            self, monkeypatch):
        """A typo must narrow who can act, never widen it."""
        monkeypatch.setenv("TELEGRAM_CONTROL_USER_IDS", "123, oops,,456;789")
        get_settings.cache_clear()
        try:
            assert telegram_svc.control_user_ids() == frozenset({123, 456, 789})
        finally:
            get_settings.cache_clear()


class TestMovingAnOrder:
    async def test_a_press_advances_the_order(self, client, db, control):
        ref = await rendered_order(client, db)
        resp = await client.post(HOOK, headers=HDRS,
                                 json=press(ref, "sent_to_production"))
        assert resp.status_code == 200
        assert await status_of(db, ref) == "sent_to_production"
        assert any("At the printer" in a for a in answers(control))

    async def test_it_writes_the_same_audit_row_the_console_would(
            self, client, db, control):
        """Every status change is a row in the order's history, whoever drove
        it — the trail must say a button on a phone did this."""
        ref = await rendered_order(client, db)
        await client.post(HOOK, headers=HDRS, json=press(ref, "sent_to_production"))
        order = (await db.execute(
            select(Order).where(Order.human_ref == ref))).scalar_one()
        notes = [e.note for e in (await db.execute(
            select(OrderEvent).where(OrderEvent.order_id == order.id))).scalars()]
        assert any(n and "telegram" in n.lower() for n in notes), notes

    async def test_the_whole_fulfilment_path_from_the_phone(
            self, client, db, control):
        ref = await rendered_order(client, db)
        for target in ("sent_to_production", "shipped", "delivered"):
            await client.post(HOOK, headers=HDRS, json=press(ref, target))
            assert await status_of(db, ref) == target

    async def test_pressing_twice_says_already_rather_than_failing(
            self, client, db, control):
        """Thumbs slip and Telegram redelivers. The second press must be a
        statement of fact, not an error and not a second write."""
        ref = await rendered_order(client, db)
        await client.post(HOOK, headers=HDRS, json=press(ref, "sent_to_production"))
        control.clear()
        resp = await client.post(HOOK, headers=HDRS,
                                 json=press(ref, "sent_to_production"))
        assert resp.status_code == 200
        assert await status_of(db, ref) == "sent_to_production"
        assert any("already" in a.lower() for a in answers(control))

    async def test_a_stale_keyboard_cannot_skip_a_step(self, client, db, control):
        """The keyboard on a phone is a cache. If the order moved elsewhere
        since, the old buttons must not be able to write a state the machine
        forbids from where it actually is."""
        ref = await rendered_order(client, db)
        resp = await client.post(HOOK, headers=HDRS, json=press(ref, "delivered"))
        assert resp.status_code == 200
        assert await status_of(db, ref) == "rendered"
        assert any("Cannot do that" in a for a in answers(control))

    async def test_a_target_that_is_not_an_operator_action_is_refused(
            self, client, db, control):
        """`paid` enqueues a render; it must not be reachable by a button
        that only writes a row."""
        ref = await rendered_order(client, db)
        for target in ("paid", "rendered", "draft_order", "nonsense"):
            await client.post(HOOK, headers=HDRS, json=press(ref, target))
            assert await status_of(db, ref) == "rendered", target

    async def test_a_refusal_still_refreshes_the_buttons(
            self, client, db, control):
        """A refusal usually means the picture on the phone is out of date,
        which is the thing worth correcting."""
        ref = await rendered_order(client, db)
        await client.post(HOOK, headers=HDRS, json=press(ref, "delivered"))
        assert any(m == "editMessageReplyMarkup" for m, _ in control)

    async def test_the_status_row_reports_without_changing_anything(
            self, client, db, control):
        ref = await rendered_order(client, db)
        await client.post(HOOK, headers=HDRS, json=press(ref, "noop"))
        assert await status_of(db, ref) == "rendered"
        assert any("Ready for print" in a for a in answers(control))


class TestJunkFromTheInternet:
    """Past the secret it is Telegram, but Telegram sends update types we do
    not handle, and a body we cannot use must not become a retry loop."""

    @pytest.mark.parametrize("body", [
        {"update_id": 1},
        {"message": {"from": {"id": ALLOWED}, "chat": {"id": -100123},
                     "text": "just chatting"}},
        {"callback_query": {"id": "x", "from": {"id": ALLOWED},
                            "message": {"message_id": 1, "chat": {"id": 1}},
                            "data": "garbage"}},
        {"callback_query": {"id": "x", "from": {"id": ALLOWED},
                            "message": {"message_id": 1, "chat": {"id": 1}},
                            "data": "o:UB-NOSUCH:shipped"}},
    ])
    async def test_it_answers_200_and_carries_on(self, client, control, body):
        assert (await client.post(HOOK, headers=HDRS, json=body)).status_code == 200

    async def test_a_body_that_is_not_json_is_not_retried_forever(
            self, client, control):
        resp = await client.post(
            HOOK, headers={**HDRS, "Content-Type": "application/json"},
            content=b"not json")
        assert resp.status_code == 200

    async def test_a_handler_that_blows_up_still_answers_200(
            self, client, db, control, monkeypatch):
        """Telegram retries anything that is not a 200, so an exception here
        would become an infinite redelivery loop rather than one failure."""
        async def boom(*a, **k):
            raise RuntimeError("kaboom")
        monkeypatch.setattr(telegram_control.admin_orders, "set_status", boom)
        ref = await rendered_order(client, db)
        resp = await client.post(HOOK, headers=HDRS,
                                 json=press(ref, "sent_to_production"))
        assert resp.status_code == 200
        assert await status_of(db, ref) == "rendered"


class TestTheOrdersCommand:
    async def test_it_lists_open_orders_with_buttons(self, client, db, control):
        ref = await rendered_order(client, db)
        await client.post(HOOK, headers=HDRS, json=command("/orders"))
        sends = [b for m, b in control if m == "sendMessage"]
        assert any(ref in b.get("text", "") for b in sends)
        assert any("reply_markup" in b for b in sends), "no keyboard to press"

    async def test_it_carries_no_customer_pii(self, client, db, control):
        """A76: this chat is not authenticated. The operator opens the
        console for a name."""
        ref = await rendered_order(client, db)
        order = (await db.execute(
            select(Order).where(Order.human_ref == ref))).scalar_one()
        # Only what /orders itself said — the print notification sent while
        # making the order carries PII deliberately (it is the job sheet).
        control.clear()
        await client.post(HOOK, headers=HDRS, json=command("/orders"))
        said = " ".join(b.get("text", "") for _, b in control)
        assert ref in said, "the listing did not mention the order at all"
        assert order.customer_name not in said
        assert order.customer_phone not in said

    async def test_help_explains_itself(self, client, control):
        await client.post(HOOK, headers=HDRS, json=command("/help"))
        said = " ".join(b.get("text", "") for _, b in control)
        assert "/orders" in said

    async def test_a_group_chat_suffix_is_understood(self, client, control):
        """Telegram delivers "/orders@rspixelbot" in a group."""
        await client.post(HOOK, headers=HDRS, json=command("/orders@rspixelbot"))
        said = " ".join(b.get("text", "") for _, b in control)
        assert "Unknown command" not in said


class TestTheKeyboard:
    def test_it_offers_exactly_what_the_state_machine_allows(self):
        from app.services.admin_orders import next_statuses_for

        kb = telegram_svc.order_keyboard("UB-ABC12", "rendered",
                                         next_statuses_for("rendered"))
        targets = {b["callback_data"].split(":")[2]
                   for row in kb["inline_keyboard"] for b in row}
        assert targets == {"noop", "sent_to_production", "cancelled"}

    def test_the_first_row_says_where_the_order_is(self):
        kb = telegram_svc.order_keyboard("UB-ABC12", "shipped", [])
        assert kb["inline_keyboard"][0][0]["text"] == "● Shipped"

    def test_a_finished_order_offers_nothing_to_press(self):
        from app.services.admin_orders import next_statuses_for

        kb = telegram_svc.order_keyboard("UB-ABC12", "refunded",
                                         next_statuses_for("refunded"))
        assert len(kb["inline_keyboard"]) == 1, "only the status row"

    def test_callback_data_stays_inside_telegrams_limit(self):
        """Telegram silently rejects callback_data over 64 bytes, which would
        ship a button that does nothing when pressed."""
        from app.domain.states import OrderStatus

        for status in OrderStatus:
            data = telegram_svc.callback_data("UB-ABC12", status.value)
            assert len(data.encode()) <= telegram_svc.CALLBACK_MAX_BYTES, data

    def test_an_over_long_reference_is_caught_rather_than_shipped(self):
        with pytest.raises(telegram_svc.TelegramError, match="too long"):
            telegram_svc.callback_data("UB-" + "X" * 80, "sent_to_production")

    @pytest.mark.parametrize("data", ["", "garbage", "o:only-two",
                                      "x:UB-A:shipped", "o::shipped",
                                      "o:UB-A:", "o:a:b:c"])
    def test_anything_that_is_not_ours_parses_to_nothing(self, data):
        assert telegram_svc.parse_callback_data(data) is None

    def test_ours_parses(self):
        assert telegram_svc.parse_callback_data("o:UB-ABC12:shipped") == \
            ("UB-ABC12", "shipped")


class TestItStaysOffByDefault:
    def test_control_is_off_with_no_configuration(self, monkeypatch):
        """Every deployment that has never heard of this feature."""
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "")
        monkeypatch.setenv("TELEGRAM_CONTROL_USER_IDS", "")
        get_settings.cache_clear()
        try:
            assert telegram_svc.control_enabled() is False
        finally:
            get_settings.cache_clear()

    def test_the_print_notification_has_no_buttons_when_off(self, monkeypatch):
        """The message every existing deployment already gets must be
        unchanged, keyboard included."""
        sent: list[tuple] = []
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "")
        monkeypatch.setenv("TELEGRAM_CONTROL_USER_IDS", "")
        get_settings.cache_clear()
        monkeypatch.setattr(telegram_svc, "_post_telegram",
                            lambda text, markup=None: sent.append((text, markup)))
        monkeypatch.setattr(telegram_svc, "build_production_message",
                            lambda payload: "message")
        try:
            telegram_svc.send_production_notification(
                {"human_ref": "UB-ABC12", "status": "rendered"})
            assert sent == [("message", None)]
        finally:
            get_settings.cache_clear()

    def test_and_has_them_when_on(self, monkeypatch):
        sent: list[tuple] = []
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
        monkeypatch.setenv("TELEGRAM_CONTROL_USER_IDS", f"{ALLOWED}")
        get_settings.cache_clear()
        monkeypatch.setattr(telegram_svc, "_post_telegram",
                            lambda text, markup=None: sent.append((text, markup)))
        monkeypatch.setattr(telegram_svc, "build_production_message",
                            lambda payload: "message")
        try:
            telegram_svc.send_production_notification(
                {"human_ref": "UB-ABC12", "status": "rendered"})
            assert sent[0][1] is not None and sent[0][1]["inline_keyboard"]
        finally:
            get_settings.cache_clear()
