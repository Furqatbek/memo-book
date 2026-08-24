"""The occasions a book can be made for.

Picked first in the editor, before the size, and used for three things: a
starting cover title and colour, a line in the printer's Telegram message,
and — since cover designs exist — deciding which ready-made covers a
customer is shown (A71).

Kept here rather than inline in each caller so "what is a valid occasion"
has one answer. Unknown values are tolerated everywhere, never rejected: a
book saved with an occasion we later retire must still open and still
print.
"""

BOOK_TYPES: tuple[str, ...] = ("love", "travel", "birthday", "memory")

BOOK_TYPE_LABELS: dict[str, str] = {
    "love": "❤️ Love story",
    "travel": "✈️ Travel book",
    "birthday": "🎂 Birthday",
    "memory": "📸 Memory book",
}


def is_book_type(value: str | None) -> bool:
    return value in BOOK_TYPES


def normalize_book_type(value: str | None) -> str | None:
    """A recognised occasion, or None. Whitespace and case are the kind of
    thing a hand-typed admin command gets wrong, so absorb them here."""
    if not value:
        return None
    cleaned = value.strip().lower()
    return cleaned if cleaned in BOOK_TYPES else None
