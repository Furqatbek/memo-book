"""Email transport seam. No provider is integrated: `send_email` raises.

Everything in this product reaches customers through the Telegram bot. The
email field on the checkout form is still collected — an address costs
nothing to keep and becomes useful the day a transport exists — but nothing
may PRETEND to send to it in the meantime.

That is what `configured()` is for. Before this existed, every caller with an
address in hand queued a message, the outbox retried it, it failed with
"email transport is not configured", and an attention row appeared. Three
things were wrong with that and only the third is obvious:

  the operator got an alert about a channel that is off on purpose, and a
  panel full of expected failures is a panel nobody reads;

  the customer heard nothing, and nothing said how many customers that was;

  worst, `lifecycle` marked the book as reminded and emitted `reminder_sent`
  when the message was QUEUED. So a reminder that could never be delivered
  spent that book's day-3 slot for good and counted as sent in the funnel.

So the rule is now: ask before you queue. Callers that would use email check
`configured()` first and, when it answers no, behave exactly as they do for a
customer who left no contact details at all — nothing queued, nothing
recorded, nothing spent, so the message goes properly if mail is ever
switched on.

Tests monkeypatch `send_email`, and `configured` where they need the email
path to exist.
"""


class EmailError(Exception):
    pass


def configured() -> bool:
    """Whether mail can actually be delivered.

    False in every deployment there has ever been, because `send_email` below
    is a stub. It is a function rather than a constant so that the day
    somebody integrates a provider there is exactly one line to change and
    every caller is already asking the right question.

    Deliberately NOT a setting: a `EMAIL_ENABLED=true` in an `.env` would be
    able to claim a transport that does not exist, and code that can claim
    something untrue about itself is the bug class this codebase keeps
    finding. When there is a provider, this returns whether ITS credentials
    are present.
    """
    return False


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
