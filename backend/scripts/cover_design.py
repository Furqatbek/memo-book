"""Manage the ready-made cover catalogue (A71).

    # add or replace a design
    python scripts/cover_design.py add romance-gold artwork.png \
        --name "Gold hearts" --types love,birthday \
        --photo-rect 19,24,110,110 --title 74,158,24 \
        --title-color '#ffffff' --bg '#7a2740' --order 10

    python scripts/cover_design.py list [--all]
    python scripts/cover_design.py retire romance-gold
    python scripts/cover_design.py restore romance-gold
    python scripts/cover_design.py spec        # what to draw

Artwork covers the FRONT PANEL plus its turn-in — 164 x 242 mm, i.e.
1937 x 2858 px at 300 dpi. One file serves every page tier, because only the
spine width changes between tiers and the spine is not part of the artwork;
the back panel and spine take --bg.

Re-running `add` with the same slug replaces that design in place, so
correcting one never leaves a second copy in the gallery.
"""
import argparse
import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageOps  # noqa: E402

from app.db.session import _get_sessionmaker  # noqa: E402
from app.services.cover_designs import (  # noqa: E402
    ARTWORK_H_MM,
    ARTWORK_H_PX,
    ARTWORK_W_MM,
    ARTWORK_W_PX,
    DISPLAY_W_PX,
    MIN_ARTWORK_H_PX,
    MIN_ARTWORK_W_PX,
    THUMB_W_PX,
    list_designs,
    parse_book_types,
    upsert_design,
)

JPEG_Q = 92


def _rect(raw: str | None) -> dict | None:
    """--photo-rect x,y,w,h in front-panel trim mm; omitted = no photo
    window, i.e. the artwork is the whole cover."""
    if not raw or raw.lower() in ("none", "no", ""):
        return None
    try:
        x, y, w, h = (float(p) for p in raw.split(","))
    except ValueError:
        raise SystemExit("--photo-rect wants x,y,w,h in mm, e.g. 19,24,110,110") from None
    if w <= 0 or h <= 0:
        raise SystemExit("--photo-rect width and height must be positive")
    return {"x_mm": x, "y_mm": y, "w_mm": w, "h_mm": h}


def _title(raw: str | None) -> dict | None:
    if not raw or raw.lower() in ("none", "no", ""):
        return None
    try:
        parts = [float(p) for p in raw.split(",")]
    except ValueError:
        raise SystemExit("--title wants x,y[,size_pt], e.g. 74,158,24") from None
    if len(parts) not in (2, 3):
        raise SystemExit("--title wants x,y[,size_pt]")
    out = {"x_mm": parts[0], "y_mm": parts[1]}
    if len(parts) == 3:
        out["size_pt"] = parts[2]
    return out


def _hex(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if not (len(v) == 7 and v.startswith("#")):
        raise SystemExit(f"{field} wants a #rrggbb colour, got {value!r}")
    return v.lower()


def _renditions(path: Path) -> tuple[bytes, bytes, bytes, int, int]:
    img = Image.open(path)
    img.load()
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    if img.width < MIN_ARTWORK_W_PX or img.height < MIN_ARTWORK_H_PX:
        raise SystemExit(
            f"artwork is {img.width}x{img.height}px; the minimum is "
            f"{MIN_ARTWORK_W_PX}x{MIN_ARTWORK_H_PX} and the target is "
            f"{ARTWORK_W_PX}x{ARTWORK_H_PX}. Below that it prints soft.")

    want = ARTWORK_W_PX / ARTWORK_H_PX
    got = img.width / img.height
    if abs(got - want) / want > 0.02:
        print(f"  ! aspect {got:.3f} differs from {want:.3f} — the artwork "
              f"will be centre-cropped to fit. Draw at {ARTWORK_W_PX}x"
              f"{ARTWORK_H_PX} to control exactly what is kept.")

    def jpeg(im: Image.Image) -> bytes:
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=JPEG_Q, optimize=True)
        return buf.getvalue()

    def scaled(width: int) -> Image.Image:
        height = max(1, round(img.height * width / img.width))
        return img.resize((width, height), Image.LANCZOS)

    return (jpeg(img), jpeg(scaled(DISPLAY_W_PX)), jpeg(scaled(THUMB_W_PX)),
            img.width, img.height)


async def cmd_add(args) -> None:
    path = Path(args.artwork)
    if not path.exists():
        raise SystemExit(f"no such file: {path}")
    types = parse_book_types(args.types)
    if args.types and not types:
        raise SystemExit(f"--types {args.types!r} named no known occasion")

    artwork, display, thumb, w, h = _renditions(path)
    async with _get_sessionmaker()() as session:
        design = await upsert_design(
            session, slug=args.slug, name=args.name or args.slug,
            book_types=args.types or "", artwork=artwork, display=display,
            thumb=thumb, width=w, height=h,
            photo_rect=_rect(args.photo_rect), title=_title(args.title),
            title_color=_hex(args.title_color, "--title-color"),
            bg_color=_hex(args.bg, "--bg") or "#ffffff",
            sort_order=args.order)
    print(f"saved {design.slug}  {w}x{h}px  "
          f"occasions={types or 'any'}  "
          f"photo={'yes' if design.photo_rect else 'no'}")


async def cmd_list(args) -> None:
    async with _get_sessionmaker()() as session:
        designs = await list_designs(session, args.type,
                                     include_inactive=args.all)
        if not designs:
            print("no designs" + (f" for {args.type}" if args.type else ""))
            return
        for d in designs:
            state = "" if d.active else "  [retired]"
            print(f"{d.sort_order:>4}  {d.slug:<24} {d.name:<24} "
                  f"{parse_book_types(d.book_types) or 'any'}"
                  f"  photo={'yes' if d.photo_rect else 'no'}{state}")


async def _set_active(slug: str, active: bool) -> None:
    from sqlalchemy import select

    from app.models.cover_design import CoverDesign

    async with _get_sessionmaker()() as session:
        design = (await session.execute(
            select(CoverDesign).where(CoverDesign.slug == slug)
        )).scalar_one_or_none()
        if design is None:
            raise SystemExit(f"no design with slug {slug!r}")
        design.active = active
        await session.commit()
    print(f"{slug} is now {'visible' if active else 'retired'}")


def cmd_spec(_args) -> None:
    print(f"""Cover artwork specification

  Size      {ARTWORK_W_PX} x {ARTWORK_H_PX} px  ({ARTWORK_W_MM} x {ARTWORK_H_MM} mm at 300 dpi)
  Minimum   {MIN_ARTWORK_W_PX} x {MIN_ARTWORK_H_PX} px
  Format    PNG or JPEG, sRGB

  The artwork is the FRONT of the book plus the turn-in that folds around
  the board. Only the middle 148 x 210 mm is seen on the closed book:

    - keep the design's edges quiet: 16 mm all round folds out of sight
    - keep text and faces 21 mm inside every edge (turn-in + 5 mm safe)
    - the back panel and the spine are NOT in this file; they print in the
      flat colour you pass as --bg, so pick one that belongs with the art

  One file works for every page tier. Only the spine width changes between
  tiers, and the spine is not part of the artwork.

  If the design leaves room for the customer's photo, say where with
  --photo-rect x,y,w,h in mm measured from the top-left of the 148 x 210
  front panel. Omit it for a complete artwork cover.""")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="add or replace a design")
    add.add_argument("slug")
    add.add_argument("artwork")
    add.add_argument("--name", default="")
    add.add_argument("--types", default="",
                     help="occasions, e.g. love,birthday (blank = all)")
    add.add_argument("--photo-rect", default=None,
                     help="x,y,w,h in mm for the customer's photo")
    add.add_argument("--title", default=None, help="x,y[,size_pt] in mm/pt")
    add.add_argument("--title-color", default=None)
    add.add_argument("--bg", default=None, help="back panel + spine colour")
    add.add_argument("--order", type=int, default=100)

    ls = sub.add_parser("list", help="list designs")
    ls.add_argument("--type", default=None)
    ls.add_argument("--all", action="store_true", help="include retired")

    for name, active in (("retire", False), ("restore", True)):
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.set_defaults(_active=active)

    sub.add_parser("spec", help="what to draw")

    args = ap.parse_args()
    if args.cmd == "add":
        asyncio.run(cmd_add(args))
    elif args.cmd == "list":
        asyncio.run(cmd_list(args))
    elif args.cmd in ("retire", "restore"):
        asyncio.run(_set_active(args.slug, args._active))
    else:
        cmd_spec(args)


if __name__ == "__main__":
    main()
