"""Email transport seam. No provider is integrated yet: sending raises, which
makes reminder deliveries retry via the outbox and land in `failed` with a
clear reason until SMTP/API credentials exist. Tests monkeypatch `send_email`.
"""


class EmailError(Exception):
    pass


def send_email(to: str, subject: str, text: str) -> None:
    raise EmailError("email transport is not configured")


SUBJECTS = {
    3: "Your photo book is waiting for you",
    14: "Your photo book is still saved",
    25: "Your photo book expires soon",
}


def build_reminder(payload: dict) -> tuple[str, str]:
    """Both channels say the same thing (Change 4).

    The body is composed once in `lifecycle` — including the day's wording,
    the days actually left and any seasonal line — so email and Telegram
    cannot drift into telling the same customer two different stories.
    """
    days = payload["days_since_edit"]
    subject = SUBJECTS.get(days, "Your photo book is waiting for you")
    body = payload.get("text")
    if body:
        return subject, body
    # A message queued by an older build, still in the outbox across a
    # deploy. Delivered rather than dropped.
    ref = payload["book_id"][:8]
    return subject, (
        f"You started a photo book ({ref}…) and last edited it {days} days ago.\n"
        f"Open your book to keep working on it: {payload['edit_url']}"
    )
