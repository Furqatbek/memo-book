"""The customer's proof of transfer (A100).

In the card-transfer pilot nobody tells us a payment arrived — the operator
matches transfers against the bank by hand. A screenshot of the transfer is
the one piece of evidence only the customer has, so this lets them attach it
to their own order, and puts it in front of the operator at the moment they
decide whether the money came: stored, shown in the console, and announced
in the Telegram chat with a link to open it (A102).

**The declared content type is ignored.** A browser will happily send
`image/png` for a file of HTML, and these objects are served from our own
storage hostname — so a stored HTML file would be a script running on that
origin. The type is therefore determined from the BYTES, and a file whose
first few bytes are not one of the three we accept is refused whatever it
claims and whatever it is called.
"""
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.domain.errors import DomainError, ErrorCode
from app.models.order import Order

log = structlog.get_logger()

RECEIPT_MAX_BYTES = 2 * 1024 * 1024        # 2 MB

# Magic bytes -> (what we will call it, what we will name it). JPEG's third
# byte varies by encoder, so only the first three are fixed.
RECEIPT_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"%PDF-", "application/pdf", ".pdf"),
)

ACCEPTED_TYPES = tuple(t for _sig, t, _ext in RECEIPT_SIGNATURES)


def sniff(raw: bytes) -> tuple[str, str] | None:
    """(content_type, extension) read out of the file itself, or None.

    Total and strict: anything that is not recognisably one of the three is
    not one of the three. There is no "probably fine" branch here, because
    the whole point is that we are not taking the uploader's word for it.
    """
    for signature, content_type, ext in RECEIPT_SIGNATURES:
        if raw.startswith(signature):
            return content_type, ext
    return None


def receipt_key(order_id, ext: str) -> str:
    return f"orders/{order_id}/receipt{ext}"


async def attach_receipt(session: AsyncSession, order: Order,
                         raw: bytes) -> Order:
    """Store `raw` as this order's receipt, replacing any previous one.

    Raises DomainError for anything a person could reasonably do wrong, with
    a message meant to be read by the person who did it.
    """
    if not raw:
        raise DomainError(ErrorCode.VALIDATION_ERROR, "that file is empty")
    if len(raw) > RECEIPT_MAX_BYTES:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            f"that file is {len(raw) // 1024} KB; the limit is "
            f"{RECEIPT_MAX_BYTES // 1024} KB",
            {"max_bytes": RECEIPT_MAX_BYTES, "bytes": len(raw)})

    sniffed = sniff(raw)
    if sniffed is None:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            "that file is not a PNG, JPEG or PDF",
            {"accepted": list(ACCEPTED_TYPES)})
    content_type, ext = sniffed

    key = receipt_key(order.id, ext)
    storage.put_bytes(key, raw, content_type)
    # A second upload with a different format leaves the first object behind
    # under its own name, and an orphan nobody can reach is still a receipt
    # sitting in a bucket.
    if order.receipt_key and order.receipt_key != key:
        try:
            storage.delete_keys([order.receipt_key])
        except Exception:  # noqa: BLE001 — a stranded object must not fail the upload
            log.warning("receipt_old_object_not_deleted", order=order.human_ref)

    order.receipt_key = key
    order.receipt_content_type = content_type
    order.receipt_bytes = len(raw)
    order.receipt_uploaded_at = datetime.now(UTC)

    # Telling the operator is the POINT of the upload, so it is enqueued in
    # the same transaction that records the receipt: one commit, and either
    # both are true or neither is (A102). A receipt filed in a bucket that
    # nobody is told about is a customer waiting for a book while their proof
    # of payment sits where nobody thought to look.
    #
    # Every upload sends, including a replacement — a corrected receipt is
    # precisely the thing worth a second message, and the outbox is
    # at-least-once anyway.
    from app.services import outbox

    outbox.enqueue(session, outbox.TOPIC_ORDER_RECEIPT,
                   outbox.receipt_payload(order))
    await session.commit()
    await session.refresh(order)
    log.info("receipt_attached", order=order.human_ref,
             content_type=content_type, bytes=len(raw))

    # Same arrangement as a finished render: where there is no worker to
    # deliver the outbox, deliver it here. Where there is one, it is already
    # doing it on its own cadence and this request has no business waiting on
    # Telegram.
    from app import queue

    if queue.eager():
        await outbox.deliver_pending(session)
    return order
