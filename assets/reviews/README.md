# Customer review photos

Real photographs only — of the customer, or of the book they received, with
their permission. One file per review, referenced from `assets/reviews.js`
as `reviews/<file>`.

**No generated or stock avatars.** A competitor in this category fills this
space with `i.pravatar.cc` portraits beside invented quotes, and it is
visible to anyone who looks. `scripts/launch_check.py` fails the release if
an avatar service appears anywhere on the site.

Square images crop best; anything from about 200×200 up is plenty at the
44px they are shown at.
