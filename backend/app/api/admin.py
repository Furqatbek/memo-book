"""The admin console's API (A72).

Everything here is gated on one shared secret, `ADMIN_TOKEN`. Two rules make
that safe enough for a pilot run by one person:

* **Empty token disables the whole surface.** A deploy that forgets to set it
  fails closed — the routes answer 404, exactly as if they did not exist —
  rather than shipping an open door. This is the single most important
  property in the file.
* **404, never 401, when the token is missing or wrong.** The console is not
  an oracle for whether an admin API exists here, and a wrong guess learns
  nothing a right one would not.

Comparison is constant-time. Attempts are rate-limited per IP, low, because
the only legitimate caller is one person clicking.
"""
import json
import secrets
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.domain.book_types import BOOK_TYPES
from app.domain.states import OrderStatus
from app.models.cover_design import CoverDesign
from app.rate_limit import rate_limit
from app.services import admin_orders as admin_orders_svc
from app.services.cover_designs import (
    ARTWORK_H_MM,
    ARTWORK_H_PX,
    ARTWORK_W_MM,
    ARTWORK_W_PX,
    MIN_ARTWORK_H_PX,
    MIN_ARTWORK_W_PX,
    build_renditions,
    list_designs,
    parse_book_types,
    serialize,
    upsert_design,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"],
                   dependencies=[rate_limit("admin",
                                            lambda s: s.rate_limit_admin_per_min)])

# Indistinguishable from a route that was never registered.
_GONE = HTTPException(status_code=404, detail="Not Found")


async def require_admin(request: Request) -> None:
    token = get_settings().admin_token
    if not token:
        raise _GONE
    supplied = request.headers.get("x-admin-token") or ""
    if not secrets.compare_digest(supplied, token):
        raise _GONE


Admin = Depends(require_admin)
Session = Depends(get_session)


@router.get("/ping", dependencies=[Admin])
async def ping() -> dict:
    """What the sign-in form calls: the token is either good or it is 404."""
    return {
        "ok": True,
        "book_types": list(BOOK_TYPES),
        "artwork": {
            "w_px": ARTWORK_W_PX, "h_px": ARTWORK_H_PX,
            "w_mm": ARTWORK_W_MM, "h_mm": ARTWORK_H_MM,
            "min_w_px": MIN_ARTWORK_W_PX, "min_h_px": MIN_ARTWORK_H_PX,
        },
    }


def _admin_view(design: CoverDesign) -> dict:
    """Everything the console needs, including what the shop window hides:
    whether a design is retired, and where it sorts."""
    return {**serialize(design),
            "active": design.active,
            "sort_order": design.sort_order,
            "artwork_width": design.artwork_width,
            "artwork_height": design.artwork_height}


@router.get("/cover-designs", dependencies=[Admin])
async def admin_list(session: AsyncSession = Session) -> dict:
    designs = await list_designs(session, None, include_inactive=True)
    return {"designs": [_admin_view(d) for d in designs]}


def _json_field(raw: str | None, field: str):
    if raw is None or raw == "":
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422,
                            detail=f"{field} is not valid JSON") from None


def _slug(raw: str) -> str:
    cleaned = "".join(c for c in raw.strip().lower()
                      if c.isalnum() or c in "-_")
    if not cleaned:
        raise HTTPException(status_code=422,
                            detail="slug must contain letters or digits")
    return cleaned[:64]


def _hex(raw: str | None, field: str, default: str | None = None) -> str | None:
    value = (raw or "").strip().lower()
    if not value:
        return default
    if len(value) != 7 or not value.startswith("#"):
        raise HTTPException(status_code=422,
                            detail=f"{field} must look like #rrggbb")
    return value


@router.post("/cover-designs", dependencies=[Admin], status_code=201)
async def admin_upsert(
    slug: str = Form(...),
    name: str = Form(""),
    book_types: str = Form(""),
    photo_rect: str | None = Form(None),
    title: str | None = Form(None),
    title_color: str | None = Form(None),
    bg_color: str | None = Form(None),
    sort_order: int = Form(100),
    artwork: UploadFile = File(...),
    session: AsyncSession = Session,
) -> dict:
    """Add a design, or replace one that already has this slug — the same
    upsert the CLI does, so the two cannot drift."""
    raw = await artwork.read()
    if not raw:
        raise HTTPException(status_code=422, detail="artwork file is empty")
    try:
        full, display, thumb, width, height = build_renditions(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    design = await upsert_design(
        session, slug=_slug(slug), name=name.strip(), book_types=book_types,
        artwork=full, display=display, thumb=thumb, width=width, height=height,
        photo_rect=_json_field(photo_rect, "photo_rect"),
        title=_json_field(title, "title"),
        title_color=_hex(title_color, "title_color"),
        bg_color=_hex(bg_color, "bg_color", "#ffffff"),
        sort_order=sort_order)
    return _admin_view(design)


async def _load(session: AsyncSession, design_id: uuid.UUID) -> CoverDesign:
    design = (await session.execute(
        select(CoverDesign).where(CoverDesign.id == design_id)
    )).scalar_one_or_none()
    if design is None:
        raise HTTPException(status_code=404, detail="no such design")
    return design


@router.patch("/cover-designs/{design_id}", dependencies=[Admin])
async def admin_patch(design_id: uuid.UUID, body: dict,
                      session: AsyncSession = Session) -> dict:
    """Change a design's settings without re-uploading its artwork — which is
    most edits: a name, an occasion, nudging the photo window."""
    design = await _load(session, design_id)
    if "name" in body:
        design.name = str(body["name"]).strip()[:120]
    if "book_types" in body:
        raw = body["book_types"]
        design.book_types = ",".join(parse_book_types(
            ",".join(raw) if isinstance(raw, list) else raw))
    if "photo_rect" in body:
        design.photo_rect = body["photo_rect"] or None
    if "title" in body:
        title = body["title"] or None
        design.title_x_mm = title["x_mm"] if title else None
        design.title_y_mm = title["y_mm"] if title else None
        design.title_size_pt = (title or {}).get("size_pt")
    if "title_color" in body:
        design.title_color = _hex(body["title_color"], "title_color")
    if "bg_color" in body:
        design.bg_color = _hex(body["bg_color"], "bg_color", "#ffffff")
    if "sort_order" in body:
        design.sort_order = int(body["sort_order"])
    if "active" in body:
        design.active = bool(body["active"])
    await session.commit()
    await session.refresh(design)
    return _admin_view(design)


# ---------------------------------------------------------------- orders
#
# The daily job: see what came in, confirm the transfer, hand the printer the
# files, move the order along. Every status change goes through the state
# machine, so the console can only offer what the order can actually do next
# — the page never decides that.


@router.get("/orders", dependencies=[Admin])
async def admin_orders(status: str | None = Query(default="open"),
                       q: str | None = Query(default=None),
                       limit: int = Query(default=100, ge=1, le=500),
                       session: AsyncSession = Session) -> dict:
    orders = await admin_orders_svc.list_orders(session, status=status,
                                                query=q, limit=limit)
    return {"orders": orders, "statuses": [s.value for s in OrderStatus]}


@router.get("/orders/{human_ref}", dependencies=[Admin])
async def admin_order(human_ref: str,
                      session: AsyncSession = Session) -> dict:
    return await admin_orders_svc.order_detail(session, human_ref)


@router.post("/orders/{human_ref}/confirm-payment", dependencies=[Admin])
async def admin_confirm_payment(human_ref: str, body: dict | None = None,
                                session: AsyncSession = Session) -> dict:
    return await admin_orders_svc.confirm_payment(
        session, human_ref, (body or {}).get("note"))


@router.post("/orders/{human_ref}/status", dependencies=[Admin])
async def admin_set_status(human_ref: str, body: dict,
                           session: AsyncSession = Session) -> dict:
    target = str(body.get("target") or "")
    return await admin_orders_svc.set_status(session, human_ref, target,
                                             body.get("note"))


@router.post("/orders/{human_ref}/resend", dependencies=[Admin])
async def admin_resend(human_ref: str,
                       session: AsyncSession = Session) -> dict:
    return await admin_orders_svc.resend_to_printer(session, human_ref)


@router.delete("/cover-designs/{design_id}", dependencies=[Admin])
async def admin_retire(design_id: uuid.UUID,
                       session: AsyncSession = Session) -> dict:
    """Retire, never delete. Books already using this design have been paid
    for and must keep printing exactly as their owners confirmed (A71)."""
    design = await _load(session, design_id)
    design.active = False
    await session.commit()
    await session.refresh(design)
    return _admin_view(design)
