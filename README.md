# RS Pixel — Travel Photo Books, Designed by You

Landing page for a travel photo-book service: customers design their own book
in an online editor (upload photos, lay out pages, add text, design the
cover), pay online in Uzbek so'm, and receive a printed lay-flat hardcover —
printed in Uzbekistan, delivered in about 30 days.

> **Note:** this self-serve editor model was set by the owner in Aug 2026 and
> supersedes the design-service model described in
> [`memory-book-project-brief.md`](memory-book-project-brief.md). The brief
> remains useful for production specs (lay-flat binding, paper, printer
> vetting) and market history.

> **Brand:** RS Pixel — "Remember Smiles in Pixel" (chosen by the owner,
> Aug 2026).

## What's here

| Path | What it is |
|---|---|
| `index.html` | Landing page, English |
| `ru/index.html` | Landing page, Russian |
| `uz/index.html` | Landing page, Uzbek (Latin) |
| `uz-cyrl/index.html` | Landing page, Uzbek (Cyrillic) |
| `kaa/index.html` | Landing page, Karakalpak |
| `assets/style.css` | Shared stylesheet (no frameworks, no build step, no external requests) |
| `assets/lang.js` | Device-language detection: first visit to the root page redirects to the matching language version; an explicit pick in the language menu is stored and always wins; runs once per session so the back button works. No JS → the site just stays on the opened page. |
| `editor/` | **The book editor** — static five-language app; every "Create your book" button opens it ([`editor/README.md`](editor/README.md)) |
| `backend/` | **The API** — books, uploads, print-PDF rendering, orders, payments ([`backend/README.md`](backend/README.md), [`backend/API.md`](backend/API.md)) |
| `deploy/` | **Single-VPS deployment files**, fully self-hosted incl. photo storage |
| `docs/deployment.md` | **The deployment guide** — empty server to taking orders, step by step |
| `docs/printer-questions.md` | Technical questions for the printer (EN + RU), keyed to config values |
| `docs/printer-rfq.md` | Written lay-flat spec + RU quote-request letter for Tashkent printers |
| `docs/operator-pitch.md` | Archive of the earlier tour-operator channel plan (not reflected on the site) |
| `memory-book-project-brief.md` | Original project brief (see note above) |

## Preview locally

Open `index.html` in a browser, or:

```bash
python3 -m http.server 8000
# → http://localhost:8000  (EN)  ·  http://localhost:8000/ru/  (RU)
```

## Deployment

The site **and the editor** are live on GitHub Pages, served from the
`gh-pages` branch. `.github/workflows/deploy-pages.yml` republishes them
automatically on every push to `main` or `claude/memo-book-project-duulu7` —
edit, push, done. When a custom domain is chosen, uncomment and fill the
`canonical`/`hreflang` tags in the `<head>` of the HTML files.

The backend (which the editor needs to function) deploys to a single VPS
with everything self-hosted — Postgres, Redis, and MinIO file storage on the
same machine. Full walkthrough: [`docs/deployment.md`](docs/deployment.md);
the compose/Caddy files live in [`deploy/`](deploy/README.md).

## Before going live for real customers

These placeholders appear in **all five** language pages (`index.html`,
`ru/`, `uz/`, `uz-cyrl/`, `kaa/`):

| Placeholder | Replace with |
|---|---|
| `apiBase: ''` in `editor/config.js` | The deployed backend URL (until then the editor shows "not connected yet") |
| `hello@example.com` | Real email address |
| `+998 XX XXX-XX-XX` (and its `tel:` link) | Real phone number |
| `https://t.me/XXXXXXXXX` | Real Telegram username |

And two content gates:

1. **Reviews:** a testimonials section exists in both pages as a commented-out
   block. Fill it with real customer quotes when real orders exist —
   **never publish invented reviews.**
2. **Payment:** the FAQ promises online payment in so'm via local payment
   systems — have the acquirer integration (Payme/Click/etc.) working before
   the editor goes live.
