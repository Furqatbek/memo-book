"""A97: linking a Telegram account from the admin console.

The security claim being tested is narrow and worth stating exactly: a code
is only visible to someone holding `ADMIN_TOKEN`, and redeeming it is the
only way an account joins the operator list. So the tests that matter are
the ones about what a code is worth — how long, how many times, and whether
a wrong one can be worked out by trying.

This is not privilege escalation: whoever can read the code can already
cancel orders in the console. It gives an existing authority a second
handle, and these tests are about that handle not being loose.
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.telegram import TelegramLinkCode, TelegramOperator
from app.rate_limit import limiter
from app.services import telegram as telegram_svc
from app.services import telegram_link
from tests.api.test_admin_orders import AUTH
from tests.api.test_telegram_control import (
    HDRS,
    HOOK,
    SECRET,
    command,
    press,
    rendered_order,
    status_of,
)

LINKER = 777001
OTHER = 777002


@pytest.fixture
def bot(monkeypatch):
    """The webhook switched on, nobody linked, every Telegram call captured.

    Note the empty env allowlist: these tests are about the database path,
    so nothing may be working because of a leftover `.env` id.
    """
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_CONTROL_USER_IDS", "")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123")
    get_settings.cache_clear()
    # The redemption limiter is a process-global sliding window, so without
    # this the test that deliberately exhausts it silently rate-limits every
    # test that runs after it in the same minute.
    limiter.reset()
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(telegram_svc, "_call",
                        lambda method, body: calls.append((method, body)))
    yield calls
    get_settings.cache_clear()


def said(calls) -> str:
    return " ".join(b.get("text", "") for _, b in calls)


async def issue(client) -> str:
    resp = await client.post("/api/v1/admin/telegram/link-code", headers=AUTH)
    assert resp.status_code == 200, resp.text
    return resp.json()["code"]


async def link(client, code: str, user_id: int = LINKER) -> None:
    await client.post(HOOK, headers=HDRS,
                      json=command(f"/link {code}", user_id=user_id))


class TestTheRoundTrip:
    async def test_console_code_plus_bot_command_links_the_account(
            self, client, db, bot):
        code = await issue(client)
        await link(client, code)
        assert await db.get(TelegramOperator, LINKER) is not None
        assert "Linked" in said(bot)

    async def test_and_that_account_can_then_move_an_order(
            self, client, db, bot):
        """The whole point: before the link it cannot, after it can, and
        nothing in `.env` changed in between."""
        ref = await rendered_order(client, db)

        await client.post(HOOK, headers=HDRS,
                          json=press(ref, "sent_to_production", user_id=LINKER))
        assert await status_of(db, ref) == "rendered", "acted before linking"

        await link(client, await issue(client))
        await client.post(HOOK, headers=HDRS,
                          json=press(ref, "sent_to_production", user_id=LINKER))
        assert await status_of(db, ref) == "sent_to_production"

    async def test_the_console_lists_the_linked_account(self, client, db, bot):
        await link(client, await issue(client))
        resp = await client.get("/api/v1/admin/telegram/operators", headers=AUTH)
        assert [o["telegram_user_id"] for o in resp.json()["operators"]] == [LINKER]

    async def test_it_records_who_rather_than_only_a_number(
            self, client, db, bot):
        """A list of bare ids is unreadable six months later."""
        await client.post(HOOK, headers=HDRS, json={"message": {
            "message_id": 1,
            "from": {"id": LINKER, "username": "furqat",
                     "first_name": "Furqatbek", "last_name": "R"},
            "chat": {"id": -100123},
            "text": f"/link {await issue(client)}"}})
        row = await db.get(TelegramOperator, LINKER)
        assert row.username == "furqat"
        assert row.display_name == "Furqatbek R"


class TestWhatACodeIsWorth:
    async def test_it_works_once(self, client, db, bot):
        code = await issue(client)
        await link(client, code, user_id=LINKER)
        bot.clear()
        await link(client, code, user_id=OTHER)
        assert await db.get(TelegramOperator, OTHER) is None, (
            "a spent code linked a second account")
        assert "not valid" in said(bot)

    async def test_it_expires(self, client, db, bot):
        code = await issue(client)
        row = (await db.execute(select(TelegramLinkCode))).scalars().first()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
        await link(client, code)
        assert await db.get(TelegramOperator, LINKER) is None
        assert "not valid" in said(bot)

    async def test_issuing_a_new_one_kills_the_old(self, client, db, bot):
        """Otherwise a code read off a screen an hour ago is still live, and
        "press the button again" stops being a complete fix for losing one."""
        first = await issue(client)
        await issue(client)
        await link(client, first)
        assert await db.get(TelegramOperator, LINKER) is None
        assert "not valid" in said(bot)

    async def test_a_wrong_code_links_nothing(self, client, db, bot):
        await issue(client)
        await link(client, "AAAAAAAA")
        assert await db.get(TelegramOperator, LINKER) is None

    async def test_guessing_is_rate_limited(self, client, db, bot):
        """A ten-minute window is only safe if it cannot be swept."""
        await issue(client)
        for _ in range(telegram_link.REDEEM_ATTEMPTS_PER_MIN + 3):
            await link(client, "AAAAAAAA")
        assert "Too many attempts" in said(bot)

    async def test_a_bad_code_does_not_say_why(self, client, db, bot):
        """Wrong, expired and already-spent get one answer. Telling them
        apart confirms that a guessed code was once real."""
        spent = await issue(client)
        await link(client, spent, user_id=OTHER)
        bot.clear()
        await link(client, spent, user_id=LINKER)
        spent_reply = said(bot)
        bot.clear()
        await link(client, "ZZZZZZZZ", user_id=LINKER)
        assert spent_reply == said(bot)

    async def test_the_code_is_not_stored_in_the_clear(self, client, db, bot):
        """It is a live credential while it lasts, and one that can be read
        out of a database backup is one worth not writing down."""
        code = await issue(client)
        rows = (await db.execute(select(TelegramLinkCode))).scalars().all()
        assert rows and all(code not in r.code_hash for r in rows)
        assert all(len(r.code_hash) == 64 for r in rows)

    def test_codes_avoid_letters_people_mistype(self):
        """The code is read off a screen and typed into a phone."""
        for bad in "ILOU01":
            assert bad not in telegram_link.ALPHABET

    def test_a_code_is_long_enough_to_be_unguessable(self):
        assert len(telegram_link.ALPHABET) ** telegram_link.CODE_LEN > 2 ** 38

    @pytest.mark.parametrize("typed", ["7k3m2qx4", "7K3M-2QX4", " 7K3M 2QX4 "])
    def test_spacing_and_case_do_not_break_a_link(self, typed):
        assert telegram_link.normalize(typed) == "7K3M2QX4"


class TestRevoking:
    async def test_the_console_can_take_the_link_away(self, client, db, bot):
        await link(client, await issue(client))
        resp = await client.delete(
            f"/api/v1/admin/telegram/operators/{LINKER}", headers=AUTH)
        assert resp.status_code == 200
        assert await db.get(TelegramOperator, LINKER) is None

    async def test_and_then_that_account_cannot_act(self, client, db, bot):
        ref = await rendered_order(client, db)
        await link(client, await issue(client))
        await client.delete(f"/api/v1/admin/telegram/operators/{LINKER}",
                            headers=AUTH)
        await client.post(HOOK, headers=HDRS,
                          json=press(ref, "sent_to_production", user_id=LINKER))
        assert await status_of(db, ref) == "rendered", "a revoked account acted"

    async def test_revoking_nobody_is_a_404(self, client, db, bot):
        resp = await client.delete("/api/v1/admin/telegram/operators/1",
                                   headers=AUTH)
        assert resp.status_code == 404


class TestTheBreakGlassPath:
    async def test_an_env_id_still_works_with_nothing_linked(
            self, client, db, monkeypatch):
        """If the console is down, or the last operator revoked themselves by
        accident, the person who owns the server still has a way in."""
        monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
        monkeypatch.setenv("TELEGRAM_CONTROL_USER_IDS", str(OTHER))
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123")
        get_settings.cache_clear()
        monkeypatch.setattr(telegram_svc, "_call", lambda method, body: None)
        try:
            ref = await rendered_order(client, db)
            assert await db.get(TelegramOperator, OTHER) is None
            await client.post(
                HOOK, headers=HDRS,
                json=press(ref, "sent_to_production", user_id=OTHER))
            assert await status_of(db, ref) == "sent_to_production"
        finally:
            get_settings.cache_clear()

    async def test_the_console_shows_env_ids_it_cannot_revoke(
            self, client, db, monkeypatch):
        """An id that will not go away when you press Remove should be
        visible, not mysterious — it lives in `.env`, not the database."""
        monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
        monkeypatch.setenv("TELEGRAM_CONTROL_USER_IDS", str(OTHER))
        get_settings.cache_clear()
        try:
            resp = await client.get("/api/v1/admin/telegram/operators",
                                    headers=AUTH)
            assert resp.json()["env_user_ids"] == [OTHER]
        finally:
            get_settings.cache_clear()


class TestLinkingIsTheOnlyCommandAStrangerGets:
    async def test_an_unlinked_account_is_told_how_to_link(self, client, bot):
        await client.post(HOOK, headers=HDRS,
                          json=command("/orders", user_id=OTHER))
        assert "not linked" in said(bot).lower()
        assert "admin console" in said(bot)

    async def test_link_without_a_code_explains_itself(self, client, bot):
        await client.post(HOOK, headers=HDRS,
                          json=command("/link", user_id=OTHER))
        assert "/link" in said(bot)

    async def test_an_unlinked_account_cannot_reach_anything_else(
            self, client, db, bot):
        ref = await rendered_order(client, db)
        bot.clear()
        await client.post(HOOK, headers=HDRS,
                          json=command("/orders", user_id=OTHER))
        assert ref not in said(bot), "the refusal listed an order"
