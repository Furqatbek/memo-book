# Silkbound — Premium Travel Memory Books (Uzbekistan)

Landing page and Phase-0 working documents for the business described in
[`memory-book-project-brief.md`](memory-book-project-brief.md): a hand-designed,
A5 lay-flat hardcover travel book sold in USD to foreign tourists leaving
Uzbekistan, distributed through Uzbek tour operators, printed in Tashkent.

> **"Silkbound" is a working name.** Open Question #1 in the brief (brand name +
> domain) is unresolved. The name appears only as plain text — a global
> find-and-replace of `Silkbound` across `index.html` and `ru/index.html`
> renames the site.

## What's here

| Path | What it is |
|---|---|
| `index.html` | Landing page, English (primary — foreign tourists) |
| `ru/index.html` | Landing page, Russian |
| `assets/style.css` | Shared stylesheet (no frameworks, no build step, no external requests) |
| `docs/printer-rfq.md` | Written A5 lay-flat spec + RU quote-request letter for the three Tashkent printer quotes (Open Question #4, Risk 3) |
| `docs/operator-pitch.md` | Pitch script, terms guardrails and discovery questions for the five operator meetings (Open Question #5, Risk 5) |
| `memory-book-project-brief.md` | The source of truth. Read it before changing copy. |

## Preview locally

Open `index.html` in a browser, or:

```bash
python3 -m http.server 8000
# → http://localhost:8000  (EN)  ·  http://localhost:8000/ru/  (RU)
```

## Deploy (GitHub Pages)

The site is static with relative paths — it works from a subpath out of the box.
Repo → **Settings → Pages** → deploy from branch, root folder. When a custom
domain is chosen, uncomment and fill the `canonical`/`hreflang` tags in the
`<head>` of both HTML files.

## Before going live — placeholders to replace

These appear in **both** `index.html` and `ru/index.html` (and the footer):

| Placeholder | Replace with |
|---|---|
| `https://wa.me/998XXXXXXXXX` | Real WhatsApp number (digits only, no `+`) |
| `https://t.me/XXXXXXXXX` | Real Telegram username |
| `hello@example.com` | Real email address |
| `Silkbound` | Final brand name, when chosen |

Also review the **price**: the pages show the brief's provisional **$149**.
Brief §6 flags $89–119 as the likely A5 range — decide after showing the
physical sample to operators, then update the hero meta line and the pricing
card in both languages.

Two more gates before publishing (the pages promise both):

1. **The Phase-0 sample book must physically exist** — the FAQ offers to show
   it in person and to send close-up photos and a page-turn video.
2. **A working USD card payment path must be verified** (Open Question #7 —
   Payme/Click are domestic-only). The copy hedges with "we confirm the
   payment method when you order", but don't go live without an answer for
   the first customer who asks.

## Copy rules (from brief §8 — do not undo these)

- Never use "preserve your memories" / "beautiful moments of life as a book" /
  "photobooks tell stories" phrasing — it's category wallpaper all three
  competitors use.
- No invented testimonials, review counts or customer numbers. The category's
  copycats fake social proof (brief §7); we don't. Add real reviews only once
  they exist (Phase 1 collects them).
- The page sells the four real differentiators: hand design, made-in-Uzbekistan,
  lay-flat/materials quality, and delivery before departure.
