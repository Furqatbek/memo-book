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

from app import storage
from app.config import get_settings
from app.db.session import get_session
from app.domain.book_types import BOOK_TYPES
from app.domain.states import OrderStatus
from app.models.cover_design import CoverDesign
from app.rate_limit import rate_limit
from app.services import admin_orders as admin_orders_svc
from app.services.attention import needs_attention
from app.services.cover_designs import (
    ARTWORK_H_MM,
    ARTWORK_H_PX,
    ARTWORK_W_MM,
    ARTWORK_W_PX,
    MIN_ARTWORK_H_PX,
    MIN_ARTWORK_W_PX,
    back_artwork_key,
    back_display_key,
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
            "artwork_height": design.artwork_height,
            "back_artwork_width": design.back_artwork_width,
            "back_artwork_height": design.back_artwork_height}


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
    back_artwork: UploadFile | None = File(None),
    clear_back: bool = Form(False),
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

    # The back panel is optional and held to the same standard as the front —
    # it prints at the same size, so art that would print soft there prints
    # soft here too (A95).
    back = None
    if back_artwork is not None:
        back_raw = await back_artwork.read()
        if back_raw:
            try:
                b_full, b_display, _b_thumb, b_w, b_h = build_renditions(back_raw)
            except ValueError as exc:
                raise HTTPException(status_code=422,
                                    detail=f"back artwork: {exc}") from exc
            back = (b_full, b_display, b_w, b_h)

    design = await upsert_design(
        session, slug=_slug(slug), name=name.strip(), book_types=book_types,
        artwork=full, display=display, thumb=thumb, width=width, height=height,
        photo_rect=_json_field(photo_rect, "photo_rect"),
        title=_json_field(title, "title"),
        title_color=_hex(title_color, "title_color"),
        bg_color=_hex(bg_color, "bg_color", "#ffffff"),
        sort_order=sort_order, back=back, clear_back=clear_back)
    return _admin_view(design)


@router.post("/cover-designs/{design_id}/back-artwork", dependencies=[Admin])
async def admin_back_artwork(design_id: uuid.UUID,
                             artwork: UploadFile = File(...),
                             session: AsyncSession = Session) -> dict:
    """Put back artwork on a design that already exists (A95).

    Its own endpoint because the upsert above demands a front artwork file:
    adding a back to a finished design would otherwise mean re-uploading a
    front that has not changed, and a re-upload that is only a formality is
    exactly the kind of step that eventually gets done with the wrong file.
    """
    design = await _load(session, design_id)
    raw = await artwork.read()
    if not raw:
        raise HTTPException(status_code=422, detail="back artwork file is empty")
    try:
        full, display, _thumb, width, height = build_renditions(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422,
                            detail=f"back artwork: {exc}") from exc

    storage.put_bytes(back_artwork_key(design.slug), full, "image/jpeg")
    storage.put_bytes(back_display_key(design.slug), display, "image/jpeg")
    design.back_artwork_key = back_artwork_key(design.slug)
    design.back_display_key = back_display_key(design.slug)
    design.back_artwork_width = width
    design.back_artwork_height = height
    await session.commit()
    await session.refresh(design)
    return _admin_view(design)


# ---------------------------------------------------------------- telegram
#
# Linking an operator's Telegram account (A97). The code is issued HERE, in
# the authenticated console, and redeemed in the bot — that is what makes
# the link two-sided. A code issued by the bot itself would be visible to
# everyone in the chat, which is precisely the surface we do not trust.


@router.post("/telegram/link-code", dependencies=[Admin])
async def admin_link_code(session: AsyncSession = Session) -> dict:
    from app.services.telegram import control_enabled
    from app.services.telegram_link import CODE_TTL, issue_code

    code, expires_at = await issue_code(session)
    return {"code": code, "expires_at": expires_at,
            "ttl_seconds": int(CODE_TTL.total_seconds()),
            # So the console can say the webhook still needs registering
            # rather than leaving the operator wondering why nothing happens.
            "webhook_configured": control_enabled()}


@router.get("/telegram/operators", dependencies=[Admin])
async def admin_list_operators(session: AsyncSession = Session) -> dict:
    from app.services.telegram import control_enabled, control_user_ids
    from app.services.telegram_link import list_operators

    return {"operators": await list_operators(session),
            "webhook_configured": control_enabled(),
            # Shown so an id that cannot be revoked from here is visible
            # rather than mysterious — it lives in .env, not the database.
            "env_user_ids": sorted(control_user_ids())}


@router.delete("/telegram/operators/{user_id}", dependencies=[Admin])
async def admin_revoke_operator(user_id: int,
                                session: AsyncSession = Session) -> dict:
    from app.services.telegram_link import revoke

    if not await revoke(session, user_id):
        raise HTTPException(status_code=404, detail="no such linked account")
    return {"revoked": user_id}


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
    # Removing the back artwork is a settings change, not an upload, so it
    # belongs here too — otherwise the only way to take a back off a design
    # would be to re-upload its front (A95). The stored objects are left in
    # place: nothing reads them once the keys are gone, and a design being
    # corrected twice in a minute should not race its own deletes.
    if body.get("clear_back"):
        design.back_artwork_key = None
        design.back_display_key = None
        design.back_artwork_width = None
        design.back_artwork_height = None
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


@router.get("/attention", dependencies=[Admin])
async def admin_attention(session: AsyncSession = Session) -> dict:
    """Everything stuck, including the alerts that never arrived (A76).

    Deliberately not derivable from the orders list: a message that failed to
    reach the printer leaves the order looking perfectly healthy.
    """
    return await needs_attention(session)


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
