# Silkbound — Travel Photo Books, Designed by You

Landing page for a travel photo-book service: customers design their own book
in an online editor (upload photos, lay out pages, add text, design the
cover), pay online in Uzbek so'm, and receive a printed lay-flat hardcover —
printed in Uzbekistan, delivered in about 30 days.

> **Note:** this self-serve editor model was set by the owner in Aug 2026 and
> supersedes the design-service model described in
> [`memory-book-project-brief.md`](memory-book-project-brief.md). The brief
> remains useful for production specs (lay-flat binding, paper, printer
> vetting) and market history.

> **"Silkbound" is a working name.** A global find-and-replace of `Silkbound`
> across `index.html` and `ru/index.html` renames the site.

## What's here

| Path | What it is |
|---|---|
| `index.html` | Landing page, English |
| `ru/index.html` | Landing page, Russian |
| `assets/style.css` | Shared stylesheet (no frameworks, no build step, no external requests) |
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

The site is live on GitHub Pages, served from the `gh-pages` branch.
`.github/workflows/deploy-pages.yml` republishes it automatically on every
push to `main` or `claude/memo-book-project-duulu7` — edit, push, done.
When a custom domain is chosen, uncomment and fill the `canonical`/`hreflang`
tags in the `<head>` of both HTML files.

## Before going live for real customers

These placeholders appear in **both** `index.html` and `ru/index.html`:

| Placeholder | Replace with |
|---|---|
| `href="#"` on every **Create your book** button (marked with `TODO` comments) | The real editor URL |
| `hello@example.com` | Real email address |
| `https://t.me/XXXXXXXXX` | Real Telegram username |
| `Silkbound` | Final brand name, when chosen |

And two content gates:

1. **Reviews:** a testimonials section exists in both pages as a commented-out
   block. Fill it with real customer quotes when real orders exist —
   **never publish invented reviews.**
2. **Payment:** the FAQ promises online payment in so'm via local payment
   systems — have the acquirer integration (Payme/Click/etc.) working before
   the editor goes live.
