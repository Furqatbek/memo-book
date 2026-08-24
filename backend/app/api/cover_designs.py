"""Ready-made covers offered to the customer, filtered by occasion (A71).

Public and unauthenticated: this is a shop window, the same for everybody,
and it is read before a book exists. The filtering happens here rather than
in the editor so adding a design — or changing which occasions it suits —
never needs a frontend deploy.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.cover_designs import list_designs, serialize

router = APIRouter(prefix="/api/v1", tags=["cover-designs"])


@router.get("/cover-designs")
async def cover_designs(
    book_type: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    designs = await list_designs(session, book_type)
    return {"book_type": book_type, "designs": [serialize(d) for d in designs]}
