"""Links that are meant to be sent to somebody else.

A share link, a contributor link, a review link and a flip-video link all
have one thing in common that separates them from every other URL in this
system: their whole purpose is to leave the building. They are copied to a
clipboard and pasted into a group chat, or put into a Telegram message by
the outbox.

`/s/abc123` is not a link in a chat window. It is a piece of text. So a
relative one is not a degraded link, it is a broken feature, and the
failure is silent in the worst possible place — in a customer's clipboard,
discovered by their family, after they have already sent it.

Hence one helper, and it REFUSES rather than falls back. `PUBLIC_BASE_URL`
is one line in an env file; a share link that lands nowhere costs the
share, and the customer's belief that the product works.

The reminder path made the same decision years earlier and for the same
reason (`lifecycle._reminder_url`: "Telegram gets nothing rather than a
relative path"). This is that rule, named, so the next feature that mints
a link inherits it instead of re-deciding it.
"""
from app.config import get_settings
from app.domain.errors import DomainError, ErrorCode


def base_url() -> str:
    """The configured origin with no trailing slash, or "" if unset."""
    return (get_settings().public_base_url or "").rstrip("/")


def configured() -> bool:
    return bool(base_url())


def absolute(path: str) -> str:
    """An absolute URL for a path like `/s/abc`, or a refusal.

    The message is written for an operator reading a log, not a customer:
    a customer cannot fix this, and the only useful thing to say is which
    setting is missing.
    """
    root = base_url()
    if not root:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            "this deployment cannot make links that work outside it — "
            "PUBLIC_BASE_URL is not set",
            {"setting": "PUBLIC_BASE_URL"})
    return f"{root}{path if path.startswith('/') else '/' + path}"
