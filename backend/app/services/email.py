"""Email transport seam. No provider is integrated yet: sending raises, which
makes reminder deliveries retry via the outbox and land in `failed` with a
clear reason until SMTP/API credentials exist. Tests monkeypatch `send_email`.
"""


class EmailError(Exception):
    pass


def send_email(to: str, subject: str, text: str) -> None:
    raise EmailError("email transport is not configured")


def build_reminder(payload: dict) -> tuple[str, str]:
    days = payload["days_since_edit"]
    ref = payload["book_id"][:8]
    subject = "Your photo book is waiting for you"
    text = (
        f"You started a photo book ({ref}…) and last edited it {days} days ago.\n"
        f"Drafts are kept for 30 days after the last change — after that the "
        f"photos are deleted.\n"
        f"Open your book to keep working on it: {payload['edit_url']}"
    )
    return subject, text
