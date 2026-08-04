"""Auto-place ordering — business rule R2, the most important rule in the product.

Sort by `taken_at` ascending. Photos with null `taken_at` go AFTER all dated
photos, in `uploaded_at` order. Ties broken by `uploaded_at`, then by id so the
result is fully deterministic. Never random.
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PhotoForOrdering:
    """The minimal projection of a Photo the ordering rule needs."""

    id: str
    taken_at: datetime | None
    uploaded_at: datetime


def auto_place_order(photos: list[PhotoForOrdering]) -> list[str]:
    """Return photo ids in the order they should fill the pages."""
    def key(p: PhotoForOrdering):
        return (
            p.taken_at is None,          # dated photos first
            p.taken_at or p.uploaded_at,  # dated: by taken_at; undated: uploaded_at
            p.uploaded_at,                # tie-break
            p.id,                         # final deterministic tie-break
        )

    return [p.id for p in sorted(photos, key=key)]
