# Deployment guide — RS Pixel on a single VPS

Complete walkthrough, from an empty server to taking orders. Everything is
self-hosted on your own VPS — including the photo/PDF storage (MinIO, an
S3-compatible server whose bytes live in a local volume on your disk). No
external cloud services, no per-GB storage bills.

The compose/Caddy/env files themselves live in [`../deploy/`](../deploy/)
with a quick reference in [`../deploy/README.md`](../deploy/README.md);
this document is the full step-by-step.

## What ends up running

| Container | Purpose |
|---|---|
| `caddy` | HTTPS (automatic Let's Encrypt), routes the three hostnames |
| `api` | FastAPI: the API **and** the whole frontend (site at `/`, editor at `/editor`) |
| `worker` | RQ workers: photo ingest, previews, print-PDF rendering |
| `outbox` | Delivers Telegram notifications with retry/backoff |
| `lifecycle` | Daily: 30-day draft expiry + reminder queue |
| `postgres` | Database (volume `pg_data`) |
| `redis` | Job queue (volume `redis_data`) |
| `minio` | File storage (volume `minio_data`) |

## Step 0 — What you need

- A VPS: 2 vCPU / 4 GB RAM / 40 GB disk is comfortable. Ubuntu 22.04+.
- A domain you control.
- A Telegram bot (free): talk to [@BotFather](https://t.me/BotFather) →
  `/newbot` → keep the token. Add the bot to a private group (or use your
  own chat) and get the chat id (e.g. via @userinfobot or
  `getUpdates`). Orders will arrive there.

## Step 1 — DNS (before anything else)

Create **A records → your VPS IP**. Caddy requests TLS certificates on
first boot, so these must resolve *before* you start the stack:

| Record | Purpose |
|---|---|
| `rspixel.uz` | The product: site, editor, API — one origin |
| `api.rspixel.uz` | Same backend, stable name for external editors |
| `storage.rspixel.uz` | MinIO — browsers upload photos directly here |
| `www.rspixel.uz` | Optional; redirects to the root |

## Step 2 — Server preparation

```bash
ssh root@YOUR_VPS_IP

# Docker + compose plugin
curl -fsSL https://get.docker.com | sh

# Firewall: SSH + web only
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable
```

## Step 3 — Configure

**Shortcut:** steps 3 and 4 collapse into one command that installs
Docker, clones the repo, generates every secret, and starts the stack
(safe to re-run later — that's also how you deploy updates):

```bash
curl -fsSL https://raw.githubusercontent.com/Furqatbek/memo-book/claude/memo-book-project-duulu7/deploy/bootstrap.sh \
    | bash -s -- rspixel.uz
```

Afterwards edit `/opt/memo-book/deploy/.env` for Telegram credentials and
real prices, then `docker compose -f docker-compose.prod.yml up -d`.
The manual route:

```bash
git clone https://github.com/Furqatbek/memo-book.git
cd memo-book/deploy
cp .env.prod.example .env
nano .env
```

Fill in (generate secrets with `openssl rand -hex 32`):

- `DOMAIN` — your domain
- `POSTGRES_PASSWORD` — and the same value inside `DATABASE_URL`
- `MINIO_ROOT_PASSWORD` — and the same value in `S3_SECRET_KEY`
- `S3_PUBLIC_URL` / `STORAGE_CORS_ORIGINS` — replace `rspixel.uz` if you
  ever deploy under a different domain
- `DEV_PAYMENT_SECRET` — strong and private; whoever holds it can mark
  orders paid (see Step 6)
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — from Step 0
- `PRICE_MINOR_*` — your real prices, in tiyin (1 soʼm = 100 tiyin)
- `SPINE_MM_*` — the printer's real spine widths
  (see [`printer-questions.md`](printer-questions.md); the defaults are
  placeholders and **must not** be used for a real cover)

## Step 4 — Start

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

First boot: builds the image, gets TLS certificates, runs the database
migrations, creates the storage bucket. Then verify:

```bash
curl https://rspixel.uz/health     # {"status":"ok"}
curl https://rspixel.uz/ready      # 200 with db/redis/storage checks
```

Open `https://rspixel.uz` — the site; every "Create your book" button
opens the editor at `/editor/`. Make a full test order: create a book,
upload phone photos (include one iPhone HEIC), auto-fill, preview, check
out.

## Step 5 — How a paid order reaches you (the print handoff)

**One-time setup — create the Telegram bot (5 minutes):**

1. In Telegram, open **@BotFather** → `/newbot` → pick a name and a
   username. Copy the token into `.env` as `TELEGRAM_BOT_TOKEN`.
2. Send your new bot any message (or add it to your operators group and
   write something there — for a group, also give it permission to read
   messages, or just mention it).
3. Find the chat id and verify the wiring:

   ```bash
   docker compose -f docker-compose.prod.yml exec api \
       python scripts/telegram_check.py
   ```

   With `TELEGRAM_CHAT_ID` still empty it prints the chat ids the bot can
   see — put the right one in `.env`, `docker compose -f
   docker-compose.prod.yml up -d`, and run the check again. A test message
   in Telegram means order notifications will arrive.

After that, nothing manual happens between payment and print files:

1. Payment confirmation arrives (webhook) → order becomes **paid**.
2. The render worker builds the two print files: `interior.pdf` (all
   pages, 300 dpi, 3 mm bleed) and `cover.pdf` (one hardcover wrap sheet —
   back, spine, front, with turn-in margins).
3. A Telegram message arrives in your group: order reference, customer
   name + phone, page count, amount, and **7-day download links** for both
   PDFs. Download, print, ship.

As the order physically progresses, update its status (the customer sees
it on the public tracking page):

```bash
docker compose -f docker-compose.prod.yml exec api \
    python scripts/order_status.py UB-7K3M2 sent_to_production
# later: shipped, then: delivered
```

If Telegram credentials are missing or wrong, deliveries retry with
backoff — fix `.env`, restart (`up -d`), and queued notifications go out.

## Step 6 — Payments during the pilot (card transfer, trust-first)

Until a real acquirer (Payme/Click/Uzum) is integrated, payment is a card
transfer and the flow does **not** wait for it. In `.env`:

```
PAY_CARD_NUMBER=8600 xxxx xxxx xxxx
PAY_CARD_HOLDER=FIRSTNAME LASTNAME
AUTO_CONFIRM_ORDERS=true
```

The flow:

1. The customer checks out. The order confirms immediately: print PDFs
   render and the Telegram notification reaches your printer chat within
   a minute — no simulate button, no waiting.
2. The order page shows your card (bank-card design, copy button, the
   exact amount) with a highlighted note asking the customer to transfer
   now. The card stays visible until you send the order to production.
3. **You are the payment gate.** Before printing, match the incoming
   transfer in your bank app against the order:

   ```bash
   docker compose -f docker-compose.prod.yml exec api \
       python scripts/confirm_payment.py --list
   # UB-7K3M2  rendered   299,000 UZS  07.08 14:12  Aziza R, +99890...
   ```

   Amount + timing + the customer's phone from checkout are enough to
   match; call them if unsure. Money arrived → proceed as usual:

   ```bash
   docker compose -f docker-compose.prod.yml exec api \
       python scripts/order_status.py UB-7K3M2 sent_to_production
   ```

   No transfer after a reasonable wait → don't print, call the customer.

When a real acquirer is integrated: set `AUTO_CONFIRM_ORDERS=false` and
`DEV_PAYMENTS_ENABLED=false`, clear `PAY_CARD_NUMBER` — checkout then
waits for the acquirer's webhook again.

## Step 7 — Point the public site here

The GitHub Pages copy (`furqatbek.github.io/memo-book`) is now optional:

- **Simplest:** use `https://rspixel.uz` as the only address.
- To keep Pages as a mirror whose editor talks to your VPS: set
  `apiBase: 'https://api.rspixel.uz'` in `editor/config.js`, commit,
  push (the Pages workflow redeploys automatically).

## Day-2 operations

```bash
cd memo-book/deploy
docker compose -f docker-compose.prod.yml ps                  # health
docker compose -f docker-compose.prod.yml logs -f api worker  # logs
git pull && docker compose -f docker-compose.prod.yml up -d --build   # update
docker compose -f docker-compose.prod.yml up -d --scale worker=3      # more render throughput
```

**Backups** (nightly crontab; database + photos/PDFs are the two things
that matter):

```bash
0 3 * * * docker exec memobook-postgres-1 pg_dump -U memobook memobook | gzip > /backup/db-$(date +\%F).sql.gz
30 3 * * * tar czf /backup/minio-$(date +\%F).tar.gz -C /var/lib/docker/volumes/memobook_minio_data/_data .
```

Copy `/backup` somewhere off the VPS regularly.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Browser shows certificate error | DNS records missing/not propagated when Caddy started — fix DNS, `docker compose restart caddy` |
| `/ready` returns 503 | A dependency is down — `docker compose ps`, check the failing container's logs |
| Photo upload stalls at "Processing" | `worker` container down, or `storage.` hostname unreachable from the browser |
| Upload fails instantly in the browser | Storage CORS: the editor's origin must be listed in `STORAGE_CORS_ORIGINS` |
| Order paid but no Telegram message | Wrong bot token/chat id — `docker compose logs outbox`; retries resume once fixed |
| Webhook returns 403 | `X-Dev-Signature` doesn't match `DEV_PAYMENT_SECRET` |
| Webhook returns 400 AMOUNT_MISMATCH | `amount_minor` differs from the order total |
