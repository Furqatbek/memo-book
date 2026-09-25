"""The funnel event vocabulary — Change 3.

A closed enum, deliberately. The whole point of this instrumentation is to
compute cost of acquisition per channel, and that arithmetic is only as
good as the denominators: one stray `"checkout_open"` beside
`"checkout_opened"` and a funnel step silently reads half its real value
for a month before anybody notices.

ONCE-ONLY vs REPEATABLE is the other half of the same worry. A customer who
refreshes the editor four times has not started four books, and a funnel
that counts them has quietly made every conversion rate wrong. Everything
here is once per book except the four below, which are genuinely repeatable
events about a session or a message rather than milestones in one book's
life.
"""
from enum import Enum


class EventType(str, Enum):
    SITE_VISIT = "site_visit"
    EDITOR_OPENED = "editor_opened"
    BOOK_STARTED = "book_started"                  # tier chosen, book row created
    FIRST_PHOTO_UPLOADED = "first_photo_uploaded"
    CONTACT_CAPTURED = "contact_captured"          # {channel: email|telegram}
    HALF_DESIGNED = "half_designed"                # >= 50% of pages placed
    DESIGN_COMPLETED = "design_completed"          # all placed, checkout-eligible
    PREVIEW_VIEWED = "preview_viewed"
    CHECKOUT_OPENED = "checkout_opened"
    CHECKOUT_SUBMITTED = "checkout_submitted"
    PAYMENT_SUCCEEDED = "payment_succeeded"
    PAYMENT_FAILED = "payment_failed"
    BOOK_ABANDONED = "book_abandoned"              # by job, 72h without activity
    REMINDER_SENT = "reminder_sent"                # {channel, day}
    REMINDER_CLICKED = "reminder_clicked"          # {day}
    # CR-003 growth mechanics.
    SHARE_LINK_CREATED = "share_link_created"
    SHARE_LINK_VIEWED = "share_link_viewed"        # {referrer}
    SHARE_CTA_CLICKED = "share_cta_clicked"
    GIFT_MODE_ENABLED = "gift_mode_enabled"
    FLIP_VIDEO_GENERATED = "flip_video_generated"
    FLIP_VIDEO_DOWNLOADED = "flip_video_downloaded"
    CONTRIBUTOR_LINK_CREATED = "contributor_link_created"
    CONTRIBUTOR_UPLOAD = "contributor_upload"       # {contributor}
    CONTRIBUTOR_CTA_CLICKED = "contributor_cta_clicked"


# Events that may legitimately happen more than once for the same book.
# Everything else is guarded by a unique index, so a refresh cannot inflate
# a metric even if the same call is made twice.
REPEATABLE = frozenset({
    EventType.SITE_VISIT,
    EventType.EDITOR_OPENED,
    EventType.REMINDER_SENT,
    EventType.REMINDER_CLICKED,
    # A share link is created once; it is then viewed by as many people as
    # the owner sends it to, and that count is the entire point of it.
    EventType.SHARE_LINK_VIEWED,
    EventType.SHARE_CTA_CLICKED,
    # One video per order, but the link is sent to a chat and opened by
    # whoever the customer forwards it to — which is the number worth
    # having (CR-003-5).
    EventType.FLIP_VIDEO_DOWNLOADED,
    # Several people upload to the same book; that is the entire feature
    # (CR-003-6). The link is created once, so that one stays once-only.
    EventType.CONTRIBUTOR_UPLOAD,
    EventType.CONTRIBUTOR_CTA_CLICKED,
})

ONCE_PER_BOOK = frozenset(EventType) - REPEATABLE

# The only events a browser may ask us to record. Everything else is
# emitted where the server already knows, because a client event can be
# blocked by an ad-blocker, lost on a bad connection or forged outright.
#
# These three are here because the server genuinely cannot see them: it is
# not told when somebody reads the marketing page, opens the editor, or
# moves to the checkout screen (that last one is a screen swap with no
# server call behind it). What the client can do is bounded — it names an
# event from this set and nothing else, the row is written and timestamped
# by the server with the session's own attribution, and CHECKOUT_OPENED is
# once-only per book, so a forged one cannot inflate anything.
CLIENT_REPORTABLE = frozenset({
    EventType.SITE_VISIT,
    EventType.EDITOR_OPENED,
    EventType.CHECKOUT_OPENED,
    EventType.REMINDER_CLICKED,
    # Pressed on a page that belongs to somebody else's book, by somebody
    # holding no token at all. The server cannot see a button being
    # pressed, and there is nothing here worth forging.
    EventType.SHARE_CTA_CLICKED,
    # The same, on the contributor page (CR-003-6).
    EventType.CONTRIBUTOR_CTA_CLICKED,
})

# The funnel, in order, for the report. Every step is server-observed
# except the two ends, which is why the report names them.
FUNNEL_ORDER = (
    EventType.SITE_VISIT,
    EventType.EDITOR_OPENED,
    EventType.BOOK_STARTED,
    EventType.FIRST_PHOTO_UPLOADED,
    EventType.HALF_DESIGNED,
    EventType.DESIGN_COMPLETED,
    EventType.PREVIEW_VIEWED,
    EventType.CHECKOUT_OPENED,
    EventType.CHECKOUT_SUBMITTED,
    EventType.PAYMENT_SUCCEEDED,
)
