"""Telegram delivery (R9): the production notification carries the order
reference, customer contact, page count, amount, and TIME-LIMITED SIGNED
DOWNLOAD URLS for the interior and cover PDFs — never the file itself
(the bot upload cap is ~50MB; a 96-page book exceeds it).

The payload contains PII (name, phone): it is never logged (spec Part 11);
only the order reference appears in log events.
"""
import httpx

from app import storage
from app.config import get_settings
from app.domain.money import from_minor

ARTIFACT_URL_EXPIRY_S = 7 * 24 * 3600  # spec Part 11: 7 days for artifacts

BOOK_TYPE_LABELS = {
    "love": "❤️ Love story",
    "travel": "✈️ Travel book",
    "birthday": "🎂 Birthday",
    "memory": "📸 Memory book",
}

# What each status is called on a button and in a status line (A96). Labels,
# not the raw enum: the operator is reading a phone, not a state machine.
STATUS_LABELS = {
    "draft_order": "Draft",
    "pending_payment": "Awaiting payment",
    "cancelled": "Cancelled",
    "paid": "Paid",
    "rendering": "Rendering",
    "render_failed": "Render failed",
    "rendered": "Ready for print",
    "sent_to_production": "At the printer",
    "printing": "On the press",
    "binding": "Being bound",
    "quality_check": "Quality check",
    "shipped": "Shipped",
    "delivered": "Delivered",
    "refunded": "Refunded",
}

# The verb on the button, which is not the same as the name of the state it
# leads to: "Shipped" as a destination reads as a fact, but as a button it
# has to read as something you are about to do.
ACTION_LABELS = {
    "sent_to_production": "📦 Sent to printer",
    "shipped": "🚚 Shipped",
    "delivered": "✅ Delivered",
    "cancelled": "✖️ Cancel order",
    "refunded": "↩️ Refunded",
    "rendering": "🔄 Retry render",
}

CALLBACK_PREFIX = "o"
# Telegram rejects callback_data over 64 bytes. "o:UB-ABC12:sent_to_production"
# is 29, and the check below is what stops a future longer status from
# silently producing a button that does nothing when pressed.
CALLBACK_MAX_BYTES = 64


class TelegramError(Exception):
    pass


def callback_data(human_ref: str, target: str) -> str:
    data = f"{CALLBACK_PREFIX}:{human_ref}:{target}"
    if len(data.encode()) > CALLBACK_MAX_BYTES:
        raise TelegramError(f"callback_data too long for Telegram: {data!r}")
    return data


def parse_callback_data(data: str) -> tuple[str, str] | None:
    """`o:<ref>:<target>` -> (ref, target), or None for anything else.

    Deliberately strict and total: this parses a string that arrived over the
    internet, and every shape that is not exactly ours is simply not ours.
    """
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        return None
    ref, target = parts[1].strip(), parts[2].strip()
    if not ref or not target:
        return None
    return ref, target


def order_keyboard(human_ref: str, status: str,
                   next_statuses: list[str]) -> dict:
    """The inline keyboard under an order's message.

    The first row is the order's current state. It is a button because a
    Telegram keyboard has no other kind of row, but it does nothing except
    say where the order is — which is the part that has to survive on screen
    after the toast from a press has faded.
    """
    rows = [[{"text": f"● {STATUS_LABELS.get(status, status)}",
              "callback_data": callback_data(human_ref, "noop")}]]
    row: list[dict] = []
    for target in next_statuses:
        label = ACTION_LABELS.get(target)
        if not label:
            continue
        row.append({"text": label, "callback_data": callback_data(human_ref, target)})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}


def format_amount(amount_minor) -> str:
    """Money the way an operator reads it: thin spaces between thousands, and
    the fractional part only when there is one."""
    major, minor_part = from_minor(int(amount_minor))
    return f"{major:,}".replace(",", " ") + (f".{minor_part:02d}" if minor_part else "")


def build_production_message(payload: dict) -> str:
    """Presigning happens at DELIVERY time, so retried messages carry fresh
    links rather than expired ones."""
    interior_url = storage.presign_get(payload["interior_key"],
                                       expires_in=ARTIFACT_URL_EXPIRY_S)
    cover_url = storage.presign_get(payload["cover_key"],
                                    expires_in=ARTIFACT_URL_EXPIRY_S)
    amount = format_amount(payload["amount_minor"])
    lines = [f"📖 New order {payload['human_ref']}"]
    book_type = BOOK_TYPE_LABELS.get(payload.get("book_type") or "")
    if book_type:
        lines.append(f"Type: {book_type}")
    lines.append(f"Pages: {payload['page_count']}")
    lines.append(f"Customer: {payload['customer_name']}, {payload['customer_phone']}")
    if payload.get("customer_address"):
        lines.append(f"Address: {payload['customer_address']}")
    if payload.get("customer_email"):
        lines.append(f"Email: {payload['customer_email']}")
    lines.append(f"Amount: {amount} {payload.get('currency', 'UZS')}")
    # A GIFT (CR-003-3). Loud, and above the files, because every line of
    # it changes what the person packing the box does: a different address,
    # a card to write by hand, a date not to ship before, and no price in
    # the box.
    gift = payload.get("gift")
    if gift:
        lines.append("")
        lines.append("🎁 THIS IS A GIFT — do not contact the recipient")
        lines.append(f"Deliver to: {gift['recipient_name']}, "
                     f"{gift['recipient_phone']}")
        lines.append(f"Recipient address: {gift['recipient_address']}")
        if gift.get("deliver_after"):
            lines.append(f"⏳ NOT before: {gift['deliver_after']}")
        if gift.get("gift_message"):
            lines.append(f"Card to write: “{gift['gift_message']}”")
        if gift.get("hide_price", True):
            lines.append("No price anywhere in the box.")
        lines.append("")
    soft = payload.get("soft_pages") or []
    if soft:
        # Above the links on purpose: it is the one thing worth reading
        # before the files are opened, and the last cheap moment to stop a
        # reprint. The customer was warned twice and chose to go ahead, so
        # this is a heads-up, not a hold (A79).
        worst = "will print BLURRY" if any(s["status"] == "block" for s in soft) \
            else "will print soft"
        where = ", ".join(str(s["where"]) for s in soft[:8])
        if len(soft) > 8:
            where += f" (+{len(soft) - 8} more)"
        lines.append(f"⚠️ Low resolution — {where} {worst}. "
                     "The customer saw this warning and confirmed.")
    lines.append(f"Interior PDF (7-day link):\n{interior_url}")
    lines.append(f"Cover PDF (7-day link):\n{cover_url}")
    return "\n".join(lines)


def _call(method: str, body: dict) -> None:
    """One Telegram Bot API call. Raising is how a delivery attempt fails and
    gets retried with backoff by the outbox worker."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise TelegramError("telegram credentials are not configured")
    resp = httpx.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}",
        json=body, timeout=15,
    )
    if resp.status_code != 200:
        raise TelegramError(f"telegram {method} failed: {resp.status_code} "
                            f"{resp.text[:200]}")


def _post_telegram(text: str, reply_markup: dict | None = None) -> None:
    """Synchronous send to the operator chat."""
    settings = get_settings()
    if not settings.telegram_chat_id:
        raise TelegramError("telegram credentials are not configured")
    body = {"chat_id": settings.telegram_chat_id, "text": text,
            "disable_web_page_preview": True}
    if reply_markup is not None:
        body["reply_markup"] = reply_markup
    _call("sendMessage", body)


def send_production_notification(payload: dict) -> None:
    """The print job, and — when inbound control is switched on — the buttons
    that move it the rest of the way (A96).

    The keyboard is built from the status in the payload rather than from the
    database, because this runs in the outbox worker at delivery time and the
    message must not depend on a second query that could fail. It can
    therefore be out of date by the time a thumb reaches it, which is fine:
    the press is re-checked against the live order, and the keyboard is
    rewritten with whatever was actually true.
    """
    from app.services.admin_orders import next_statuses_for

    text = build_production_message(payload)
    markup = None
    if control_enabled():
        status = payload.get("status") or "rendered"
        markup = order_keyboard(payload["human_ref"], status,
                                next_statuses_for(status))
    _post_telegram(text, markup)


def control_enabled() -> bool:
    """Whether the bot listens at all.

    One setting, read synchronously, because two callers need the answer
    where a database is not available: the webhook's own lock, and the
    outbox worker deciding whether to draw buttons on a message it is about
    to send from a thread.

    It deliberately says nothing about WHO may act. That list lives in the
    database now (A97) and is checked per press. With a secret set but
    nobody linked, the buttons appear and every press is refused with
    instructions — which is a better place to arrive than a webhook that
    answers 404 to a person who has done everything but the last step.
    """
    return bool(get_settings().telegram_webhook_secret)


def control_user_ids(settings=None) -> frozenset[int]:
    """The break-glass allowlist from `.env` (A97).

    Linking through the console is the ordinary way in; this is the door for
    whoever owns the server, for when the console is down or the last
    operator revoked themselves by accident. Anything unparseable is dropped
    rather than guessed at — a typo must narrow this set, never widen it.
    """
    raw = (settings or get_settings()).telegram_control_user_ids or ""
    out = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return frozenset(out)


def answer_callback(callback_id: str, text: str,
                    alert: bool = False) -> None:
    """Telegram shows a spinner on a pressed button until this is sent, so it
    goes out on every path including the refusals."""
    _call("answerCallbackQuery",
          {"callback_query_id": callback_id, "text": text[:200],
           "show_alert": alert})


def edit_keyboard(chat_id, message_id: int, reply_markup: dict) -> None:
    """Rewrite the buttons under a message that is already on screen, so the
    order's state on the phone matches the database after a press."""
    _call("editMessageReplyMarkup",
          {"chat_id": chat_id, "message_id": message_id,
           "reply_markup": reply_markup})


def send_to(chat_id, text: str, reply_markup: dict | None = None) -> None:
    """Reply into the chat an update came from, rather than the configured
    operator chat."""
    body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_markup is not None:
        body["reply_markup"] = reply_markup
    _call("sendMessage", body)


def send_photo_to(chat_id, photo_url: str, caption: str) -> None:
    """A reminder with the customer's own photograph on it (Change 4).

    Telegram fetches the URL from its own servers, so it has to be a
    publicly reachable link — a presigned one, minted at delivery time like
    every other link that leaves the building, so a message that waited out
    an outage and three backoffs still opens.
    """
    _call("sendPhoto", {"chat_id": chat_id, "photo": photo_url,
                        "caption": caption})


def send_video_to(chat_id, video_url: str, caption: str) -> None:
    """The flip video, playing in the chat (CR-003-5).

    `supports_streaming` matters more than it looks: without it Telegram
    offers a download button instead of a player, and a video nobody
    watches in place is a video nobody forwards.
    """
    _call("sendVideo", {"chat_id": chat_id, "video": video_url,
                        "caption": caption, "supports_streaming": True})


# What to call the file in a sentence. The bytes already said which of the
# three it is (A100); this is just the word for it.
RECEIPT_TYPE_LABELS = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "application/pdf": "PDF",
}


def build_receipt_message(payload: dict) -> str:
    """The customer attached proof of their transfer (A102).

    Presigned at DELIVERY time like the print files, for the same reason: a
    message that waited out a Telegram outage and three backoffs must arrive
    with a link that still opens.

    Reference, money and the link — no name, no phone. A76's rule for this
    chat holds: what the operator needs in order to go and look at the bank
    is the amount and the picture, and everything else is a click away in a
    console that asks who they are.
    """
    url = storage.presign_get(payload["receipt_key"],
                              expires_in=ARTIFACT_URL_EXPIRY_S)
    kind = RECEIPT_TYPE_LABELS.get(payload.get("receipt_content_type") or "",
                                   "file")
    size = int(payload.get("receipt_bytes") or 0)
    lines = [f"🧾 Payment receipt for {payload['human_ref']}",
             f"Status: {STATUS_LABELS.get(payload.get('status') or '', 'unknown')}",
             f"Amount: {format_amount(payload['amount_minor'])} "
             f"{payload.get('currency', 'UZS')}",
             f"{kind}, {max(1, size // 1024)} KB (7-day link):",
             url,
             "Check it against the bank, then confirm the payment in the "
             "admin console → Orders."]
    return "\n".join(lines)


def send_receipt_notification(payload: dict) -> None:
    """Sent with NO buttons, deliberately.

    The one action this message calls for is "the money arrived" — and that
    is not a Telegram action. Confirming a payment is not a status flip: it
    stamps `paid_at` and starts the render, so it lives in the console, which
    is why `paid` is absent from `OPERATOR_TARGETS`. The keyboard a
    `pending_payment` order would get here is therefore a single *Cancel
    order* button, sitting directly under a receipt, one fat thumb away from
    killing the order it is evidence for. A message with no buttons and a
    sentence saying where to go is the better object.
    """
    _post_telegram(build_receipt_message(payload))


def build_attention_message(payload: dict) -> str:
    """Short, and free of customer PII: the operator opens the console to see
    the rest, and unlike this chat the console is authenticated (A76)."""
    lines = [f"⚠️ Order {payload['human_ref']} needs you",
             f"Status: {payload.get('status', 'unknown')}",
             f"What happened: {payload.get('reason', 'unknown')}"]
    if payload.get("detail"):
        lines.append(f"Detail: {payload['detail']}")
    lines.append("Open the admin console → Orders to retry or cancel.")
    return "\n".join(lines)


def send_attention_alert(payload: dict) -> None:
    _post_telegram(build_attention_message(payload))
