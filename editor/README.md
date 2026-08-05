# Silkbound book editor

The self-serve editor: start a blank book, upload photos (single or bulk),
place them on pages or auto-fill chronologically, then edit freely — drag
and corner-resize photos, double-click anywhere to type, drag text boxes
around, pick page/cover/title/text colours — preview every page, check out,
track the order. Talks to the backend API
(contract: [`../backend/API.md`](../backend/API.md)).

Static and build-free — plain HTML/CSS + ES modules, same stack as the
marketing site, deployed to GitHub Pages by the same workflow. Five
languages (en / ru / uz / uz-Cyrl / kaa), sharing the site's `sb-lang`
choice with device-language fallback.

## Files

| File | What it is |
|---|---|
| `index.html` | App shell: start / editor / preview / checkout / order screens |
| `config.js` | Deploy-time config: `apiBase`, dev-only `devPaymentSecret` |
| `editor.css` | Styles, mobile-first breakpoints at 860px / 560px |
| `js/api.js` | Fetch wrapper: `X-Edit-Token`, `If-Match`, error envelope |
| `js/i18n.js` | The five-language string table |
| `js/upload.js` | presign → PUT → complete pipeline, 3 files at a time |
| `js/app.js` | Screens, page canvas, autosave, ordering |

## Running locally

```bash
cd ../backend
python scripts/devserver.py --fresh   # SQLite + in-process S3 + inline jobs
# → http://127.0.0.1:8000/editor/
```

No Docker needed. The devserver serves this directory at `/editor` (same
origin, no CORS) and runs a moto S3 with bucket CORS so browser uploads work.

## Deploying

The Pages workflow publishes `editor/` next to the site; every "Create your
book" button on the site points here. The backend deploys to a single VPS,
fully self-hosted — see [`../deploy/README.md`](../deploy/README.md); the
API also serves this editor same-origin at `/editor`, which needs no CORS
at all. For an editor hosted on another origin (like Pages) to function:

1. Deploy the backend somewhere reachable.
2. Set `apiBase` in `config.js` to that URL (or open with `?api=https://…`
   once — it persists per browser).
3. Set `CORS_ORIGINS=https://<pages-origin>` on the backend.
4. Add a CORS rule on the storage bucket allowing `PUT`/`GET` from the same
   origin (uploads go browser → storage directly).

Until then the editor shows a "not connected yet" notice and disables
starting a book.

## Design decisions

- **Anonymous drafts**: `book_id` + `edit_token` live in `localStorage`
  (`mb-book`); the start screen offers resume. Losing the device loses the
  draft — the optional email field exists for recovery reminders.
- **Autosave**: every mutation schedules a whole-document layout `PATCH`
  (700ms debounce) with `If-Match`; the server's clamped/validated document
  is adopted back. On version conflict the server wins.
- **Placement MVP**: one photo per page — full-page or with-margin, fill or
  fit — matching the backend's ≤1-placement rule (see `ASSUMPTIONS.md`
  A45–A48).
- **Payments**: checkout shows the amount the backend computed; the dev
  "simulate payment" button posts the standard dev webhook and never embeds
  a secret in deployed code.
