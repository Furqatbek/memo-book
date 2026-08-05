"""Layout colour fields: round-trip, defaults on old layouts, validation."""


async def make_book(client):
    resp = await client.post("/api/v1/books", json={"page_count": 16})
    body = resp.json()
    return body, {"X-Edit-Token": body["edit_token"]}


async def test_colors_round_trip(client):
    book, headers = await make_book(client)
    layout = book["layout"]
    layout["pages"][0]["bg_color"] = "#1A2B3C"
    layout["cover"]["bg_color"] = "#334455"
    layout["cover"]["title_color"] = "#ffee00"

    resp = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                              json=layout, headers={**headers, "If-Match": "1"})
    assert resp.status_code == 200
    saved = resp.json()["layout"]
    assert saved["pages"][0]["bg_color"] == "#1A2B3C"
    assert saved["cover"]["bg_color"] == "#334455"
    assert saved["cover"]["title_color"] == "#ffee00"


async def test_colors_default_when_absent(client):
    book, _headers = await make_book(client)
    assert book["layout"]["pages"][0]["bg_color"] == "#ffffff"
    assert book["layout"]["cover"]["bg_color"] == "#ffffff"
    assert book["layout"]["cover"]["title_color"] is None


async def test_invalid_color_rejected(client):
    book, headers = await make_book(client)
    layout = book["layout"]
    layout["pages"][0]["bg_color"] = "red"
    resp = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                              json=layout, headers={**headers, "If-Match": "1"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
