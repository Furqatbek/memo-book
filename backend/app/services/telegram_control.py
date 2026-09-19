"""Driving orders from the Telegram chat (A96).

The bot could always talk; this is what lets it listen. The operator gets
buttons under the print notification — *Sent to printer*, *Shipped*,
*Delivered*, *Cancel* — and a `/orders` command for anything that has
scrolled away.

**Why this is guarded harder than it looks like it needs to be.** A76 treats
the Telegram chat as an unauthenticated surface: that is why the attention
alert deliberately carries no customer PII, "the operator opens the console
to see the rest, and unlike this chat the console is authenticated". Turning
that chat into a place where orders can be *moved* reverses the judgement,
so it is off by default and takes three independent things to switch on:

1. `TELEGRAM_WEBHOOK_SECRET`, checked against the header Telegram sends, so
   guessing the URL is not enough;
2. `TELEGRAM_CONTROL_USER_IDS`, an allowlist of Telegram user ids, so being
   in the chat is not enough — the chat holds seven-day signed links to
   every print file, and whoever can read it must not thereby be able to
   cancel someone's order;
3. the state machine, which is the same one the console goes through. There
   is no "set it to whatever I say" path here any more than there is in the
   console: `set_status` refuses anything illegal from where the order
   actually is.

Nothing here adds PII to the chat. The `/orders` listing is references,
statuses and amounts — the operator opens the console for a name.
"""
import structlog

from app.domain.errors import DomainError
from app.services import admin_orders, telegram, telegram_link

log = structlog.get_logger()

# Enough to act on what is live without turning the chat into a database
# browser. More than this and the answer is the console.
ORDERS_LIMIT = 8

HELP = (
    "RS Pixel order control\n\n"
    "/orders — the orders that still need something doing\n"
    "/help — this\n\n"
    "Buttons under a print notification move that order. "
    "Customer details stay in the admin console."
)

# What an account that has not been linked is told. It names the way in and
# nothing else: whoever is reading has not proved they are anybody yet.
NOT_LINKED = ("This account is not linked.\n\n"
              "Open the admin console → Telegram, press Link a Telegram "
              "account, and send me /link followed by the code.")

LINK_USAGE = "Send the code with it, like this:  /link 7K3M2QX4"

LINK_REPLIES = {
    telegram_link.LinkResult.OK:
        "Linked. You can now move orders from here — /orders to see what is "
        "open.",
    telegram_link.LinkResult.ALREADY:
        "This account was already linked. Nothing to do.",
    telegram_link.LinkResult.BAD:
        "That code is not valid. Codes last 10 minutes and work once — issue "
        "a fresh one in the admin console.",
    telegram_link.LinkResult.RATE_LIMITED:
        "Too many attempts. Wait a minute and try again.",
}


async def _is_allowed(session, user_id) -> bool:
    return await telegram_link.is_operator(session, user_id)


async def handle_update(session, update: dict) -> dict:
    """One Telegram update. Always returns a dict and never raises: Telegram
    retries anything that is not a 200, so a bug here would become an
    infinite redelivery loop rather than a single failure."""
    try:
        if "callback_query" in update:
            return await _handle_press(session, update["callback_query"])
        if "message" in update:
            return await _handle_message(session, update["message"])
        return {"ok": True, "ignored": "unsupported update type"}
    except Exception:
        log.exception("telegram_control_failed")
        return {"ok": True, "ignored": "error"}


async def _handle_press(session, query: dict) -> dict:
    query_id = query.get("id") or ""
    user_id = (query.get("from") or {}).get("id")
    message = query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")

    if not await _is_allowed(session, user_id):
        # Answered rather than ignored: an unauthorised press should stop
        # spinning and say so, and the refusal reveals nothing about the
        # order — it does not even look it up.
        log.warning("telegram_press_refused", user_id=user_id)
        if query_id:
            telegram.answer_callback(query_id, NOT_LINKED, alert=True)
        return {"ok": True, "ignored": "not allowed"}

    parsed = telegram.parse_callback_data(query.get("data") or "")
    if parsed is None:
        if query_id:
            telegram.answer_callback(query_id, "Unknown button.")
        return {"ok": True, "ignored": "unparseable callback"}
    human_ref, target = parsed

    # The status row is a button because a keyboard has no other kind of row.
    if target == "noop":
        detail = await _safe_detail(session, human_ref)
        label = telegram.STATUS_LABELS.get(
            (detail or {}).get("status", ""), "unknown")
        if query_id:
            telegram.answer_callback(query_id, f"{human_ref}: {label}")
        return {"ok": True, "ignored": "status row"}

    try:
        detail = await admin_orders.set_status(
            session, human_ref, target,
            note=f"telegram button by user {user_id}")
        await telegram_link.touch(session, user_id)
        await session.commit()
        answer = f"{human_ref} → {telegram.STATUS_LABELS.get(target, target)}"
        log.info("telegram_order_advanced", human_ref=human_ref,
                 target=target, user_id=user_id)
    except DomainError as exc:
        # Pressing the same button twice, or a stale keyboard from before
        # someone used the console: say where the order actually is rather
        # than reporting a failure for something already done.
        detail = await _safe_detail(session, human_ref)
        answer = _already_message(human_ref, target, detail, exc)
        log.info("telegram_order_press_refused", human_ref=human_ref,
                 target=target, reason=exc.code.value)

    if query_id:
        telegram.answer_callback(query_id, answer)
    # Rewrite the buttons either way — a refusal usually means the keyboard
    # on screen is out of date, which is the thing worth fixing.
    if detail and chat_id is not None and message_id is not None:
        _refresh(chat_id, message_id, human_ref, detail["status"])
    return {"ok": True, "human_ref": human_ref, "target": target}


def _already_message(human_ref: str, target: str, detail, exc) -> str:
    if not detail:
        return f"{human_ref}: {exc.message}"
    now = telegram.STATUS_LABELS.get(detail["status"], detail["status"])
    if detail["status"] == target:
        return f"{human_ref} is already {now}."
    return f"Cannot do that — {human_ref} is {now}."


def _refresh(chat_id, message_id: int, human_ref: str, status: str) -> None:
    """Best effort: the order moved whatever happens to the picture of it.
    Telegram rejects an edit that changes nothing, and that is not a failure
    worth surfacing to someone who just pressed a button."""
    try:
        telegram.edit_keyboard(
            chat_id, message_id,
            telegram.order_keyboard(human_ref, status,
                                    admin_orders.next_statuses_for(status)))
    except telegram.TelegramError:
        log.info("telegram_keyboard_refresh_failed", human_ref=human_ref)


async def _safe_detail(session, human_ref: str):
    try:
        return await admin_orders.order_detail(session, human_ref)
    except DomainError:
        return None


async def _handle_message(session, message: dict) -> dict:
    sender = message.get("from") or {}
    user_id = sender.get("id")
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()
    if not text.startswith("/"):
        return {"ok": True, "ignored": "not a command"}
    parts = text.split()
    # Group chats deliver "/orders@rspixelbot".
    command = parts[0].split("@")[0].lower()

    # `/link` is the ONE command an unlinked account may use — it is how an
    # account stops being unlinked. Everything past it needs the link.
    if command == "/link":
        return await _handle_link(session, chat_id, sender, parts[1:])

    if not await _is_allowed(session, user_id):
        log.warning("telegram_command_refused", user_id=user_id, command=command)
        if chat_id is not None:
            telegram.send_to(chat_id, NOT_LINKED)
        return {"ok": True, "ignored": "not allowed"}

    if command in ("/start", "/help"):
        telegram.send_to(chat_id, HELP)
        return {"ok": True, "command": command}
    if command == "/orders":
        await _send_open_orders(session, chat_id)
        return {"ok": True, "command": command}
    telegram.send_to(chat_id, f"Unknown command. {HELP}")
    return {"ok": True, "ignored": "unknown command"}


async def _handle_link(session, chat_id, sender: dict, args: list) -> dict:
    user_id = sender.get("id")
    if user_id is None:
        return {"ok": True, "ignored": "no sender"}
    if not args:
        telegram.send_to(chat_id, LINK_USAGE)
        return {"ok": True, "ignored": "no code"}
    result = await telegram_link.redeem(
        session, args[0], int(user_id),
        username=sender.get("username") or "",
        display_name=" ".join(
            p for p in (sender.get("first_name"), sender.get("last_name")) if p))
    telegram.send_to(chat_id, LINK_REPLIES[result])
    return {"ok": True, "command": "/link", "result": result}


async def _send_open_orders(session, chat_id) -> None:
    """One message per order, each carrying its own keyboard — the keyboard
    is the point, and Telegram attaches one per message.

    References, statuses and amounts only: this chat is not authenticated
    (A76), so a customer's name is not going into it to save a click.
    """
    rows = await admin_orders.list_orders(session, status="open",
                                          limit=ORDERS_LIMIT + 1)
    if not rows:
        telegram.send_to(chat_id, "Nothing open. Everything is delivered, "
                                  "cancelled or refunded.")
        return
    more = len(rows) > ORDERS_LIMIT
    shown = rows[:ORDERS_LIMIT]
    telegram.send_to(chat_id, f"{len(shown)} open order"
                              f"{'s' if len(shown) != 1 else ''}"
                     + (" (most recent; open the console for the rest)"
                        if more else ""))
    for row in shown:
        telegram.send_to(
            chat_id, _order_line(row),
            telegram.order_keyboard(row["human_ref"], row["status"],
                                    row["next_statuses"]))


def _order_line(row: dict) -> str:
    from app.domain.money import from_minor

    major, minor = from_minor(int(row["amount_minor"]))
    amount = f"{major:,}".replace(",", " ") + (f".{minor:02d}" if minor else "")
    pages = f"{row['page_count']} pages" if row.get("page_count") else "book"
    return (f"📖 {row['human_ref']}\n"
            f"{pages} · {amount} {row.get('currency', 'UZS')}")
