"""book_type: accepted at creation, validated, persisted."""
import uuid

from sqlalchemy import select

from app.models.book import Book


async def test_create_with_type_persists(client, db):
    r = await client.post("/api/v1/books",
                          json={"page_count": 16, "book_type": "birthday"})
    assert r.status_code == 201, r.text
    book = (await db.execute(
        select(Book).where(Book.id == uuid.UUID(r.json()["book_id"]))
    )).scalar_one()
    assert book.book_type == "birthday"


async def test_create_without_type_is_fine(client, db):
    r = await client.post("/api/v1/books", json={"page_count": 16})
    assert r.status_code == 201
    book = (await db.execute(
        select(Book).where(Book.id == uuid.UUID(r.json()["book_id"]))
    )).scalar_one()
    assert book.book_type is None


async def test_unknown_type_rejected(client):
    r = await client.post("/api/v1/books",
                          json={"page_count": 16, "book_type": "wedding"})
    assert r.status_code == 422
