"""Cover design presets — where the photo and the title sit on the front.

The point is that a customer who uploads one photo gets a finished cover
without designing anything. A template names a composition: a rectangle for
the photo and a place for the title. It is deliberately silent about colour
and content — which photo, what the title reads, what the cover colour is —
so applying one never destroys anything, trying all five costs nothing, and
every field it does write stays editable afterwards (A70).

Geometry is front-panel TRIM mm — the same origin as `title_x_mm`, so the
templates read like the printed page: (0,0) is the top-left corner of the
148x210 front panel, before bleed and before the turn-in wrap.

A rectangle that reaches a trim edge means "bleed off that edge"; each
renderer extends it to its own canvas edge, because the overhang differs
(3mm of bleed in the preview, a 16mm turn-in on the cover sheet, and never
on the left, where the spine is rather than a turn-in). That keeps one set
of numbers honest in both places.

Generated for the editor by scripts/gen_cover_templates.py;
tests/domain/test_cover_templates.py fails if the two copies drift.
"""
from app.domain.geometry import TRIM_H_MM, TRIM_W_MM

# The whole front panel — what a cover photo has always filled.
FULL_RECT = {"x_mm": 0.0, "y_mm": 0.0, "w_mm": TRIM_W_MM, "h_mm": TRIM_H_MM}

DEFAULT_COVER_TEMPLATE = "full"


def _rect(x: float, y: float, w: float, h: float) -> dict:
    return {"x_mm": round(x, 2), "y_mm": round(y, 2),
            "w_mm": round(w, 2), "h_mm": round(h, 2)}


def _title(x: float, y: float, size_pt: float) -> dict:
    return {"x_mm": round(x, 2), "y_mm": round(y, 2), "size_pt": size_pt}


_MID = TRIM_W_MM / 2          # 74 — every template centres its title

COVER_TEMPLATES: dict[str, dict] = {
    # The photo is the cover; the title sits on it, low, out of the way of
    # faces. This is what every existing cover already looks like.
    "full": {
        "photo_rect": FULL_RECT,
        "title": _title(_MID, 168, 30),
    },
    # A mat all round, deeper at the foot to carry the title — the framed
    # print look, and the safest with a busy photo.
    "window": {
        "photo_rect": _rect(16, 16, TRIM_W_MM - 32, 145),
        "title": _title(_MID, 180, 26),
    },
    # Photo across the top two thirds, bleeding off three edges; a solid
    # band at the foot holds the title.
    "band": {
        "photo_rect": _rect(0, 0, TRIM_W_MM, 138),
        "title": _title(_MID, 172, 26),
    },
    # The same idea inverted: title in a band at the head, photo below.
    "banner": {
        "photo_rect": _rect(0, 72, TRIM_W_MM, TRIM_H_MM - 72),
        "title": _title(_MID, 38, 26),
    },
    # A square photo held high with a wide border, title beneath it.
    "polaroid": {
        "photo_rect": _rect(19, 24, 110, 110),
        "title": _title(_MID, 158, 24),
    },
}

COVER_TEMPLATE_IDS: tuple[str, ...] = tuple(COVER_TEMPLATES)


def cover_template(template_id: str | None) -> dict:
    """The named template, falling back to the default for anything unknown
    — an old or hand-edited document must still open."""
    return COVER_TEMPLATES.get(template_id or "", COVER_TEMPLATES[DEFAULT_COVER_TEMPLATE])


def photo_rect_for(cover: dict) -> dict:
    """Where this cover's photo goes. Covers written before templates have
    no rectangle at all and mean the whole front panel, which is exactly
    what the renderer drew for them."""
    rect = cover.get("photo_rect")
    return rect if rect else FULL_RECT


def apply_cover_template(cover: dict, template_id: str) -> dict:
    """Write a template's composition onto a cover, in place.

    Geometry only. The photo, the words, the fonts and every colour the
    customer picked survive, so trying all five designs costs nothing and
    an occasion's cover colour is never quietly swapped out from under it.
    """
    tpl = cover_template(template_id)
    cover["template"] = template_id if template_id in COVER_TEMPLATES \
        else DEFAULT_COVER_TEMPLATE
    cover["photo_rect"] = dict(tpl["photo_rect"])
    cover["title_x_mm"] = tpl["title"]["x_mm"]
    cover["title_y_mm"] = tpl["title"]["y_mm"]
    cover["title_size_pt"] = tpl["title"]["size_pt"]
    return cover


def title_on_photo(cover: dict, cx_mm: float, cy_mm: float) -> bool:
    """Does the title block's centre fall inside the photo rectangle?

    Both renderers ask this to decide whether the title needs white-on-photo
    treatment or ink that contrasts with the background. Pure geometry, so
    it stays right when the customer drags the title off the picture.
    """
    rect = photo_rect_for(cover)
    return (rect["x_mm"] <= cx_mm <= rect["x_mm"] + rect["w_mm"]
            and rect["y_mm"] <= cy_mm <= rect["y_mm"] + rect["h_mm"])
