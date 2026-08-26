# Deploying to a single VPS (fully self-hosted)

> **Full step-by-step walkthrough** (server prep, Telegram bot, pilot
> payment flow, order-status updates, troubleshooting):
> [`../docs/deployment.md`](../docs/deployment.md). This file is the quick
> reference living next to the compose/Caddy/env files.

Everything runs on your own machine — nothing external:

| Piece | What runs it | Where the data lives |
|---|---|---|
| Site + editor + API | one FastAPI container (site at `/`, editor at `/editor`) | — |
| Database | Postgres 16 container | `pg_data` volume on the VPS disk |
| **Photo/PDF storage** | **MinIO container — an S3-compatible server, self-hosted** | `minio_data` volume on the VPS disk |
| Job queue | Redis 7 container + RQ worker | `redis_data` volume |
| Notifications | outbox worker container | Postgres |
| Expiry/reminders | daily lifecycle container | Postgres |
| HTTPS | Caddy (automatic Let's Encrypt) | `caddy_data` volume |

MinIO is "S3" in protocol only — the backend already speaks that protocol,
and the bytes sit in a plain directory on your VPS. No cloud account, no
external provider, no per-GB bills.

## Running on your own machine (no domain, no TLS)

The production compose needs a domain for HTTPS. For a laptop/desktop with
Docker, use the local variant — no configuration at all:

```bash
git clone -b claude/memo-book-project-duulu7 https://github.com/Furqatbek/memo-book.git
cd memo-book/deploy
docker compose -f docker-compose.local.yml up -d --build
# → http://localhost:8000  (site; editor at /editor/)
```

Common pitfall: cloning without `-b claude/memo-book-project-duulu7` checks
out `main`, which does not contain the editor or this deploy directory —
the image build then fails at `COPY editor`.

### Showing local mode over the internet (jprq, ngrok, any tunnel)

Photo bytes go browser → storage directly, so ONE tunnel to :8000 is not
enough — uploads will hit `localhost:9000` on the visitor's device and
fail with `ERR_CONNECTION_REFUSED`. Run TWO tunnels — app (:8000) and
storage (:9000) — and tell the stack its public storage address:

```bash
# jprq (two terminals):          # or ngrok (config with two tunnels):
jprq http 8000                   #   tunnels:
jprq http 9000                   #     app:     { proto: http, addr: 8000 }
                                 #     storage: { proto: http, addr: 9000 }
                                 #   then: ngrok start --all

S3_PUBLIC_URL=https://<the-9000-tunnel-url> \
    docker compose -f docker-compose.local.yml up -d
# share https://<the-8000-tunnel-url>/editor/
```

Windows PowerShell has no `VAR=value command` prefix — set the variable
first (`$env:S3_PUBLIC_URL = "https://…"`) and then run the compose
command; or put `S3_PUBLIC_URL=https://…` in a `deploy/.env` file
(git-ignored), which works in every shell.

Upload URLs are signed against `S3_PUBLIC_URL`, so restart after setting
it (photos that failed before the restart need re-uploading). Tunnels are
fine for a quick demo; for anything real, the VPS path below exists
precisely because storage needs a stable public hostname.

## Prerequisites

- A VPS (2 vCPU / 4GB RAM is comfortable; renders are the heavy part),
  Ubuntu 22.04+ or similar, with Docker and the compose plugin:
  `curl -fsSL https://get.docker.com | sh`
- A domain with DNS **A records → your VPS IP**, created *before* first
  start (Caddy gets certificates on boot):
  - `YOUR_DOMAIN` (site + editor + API + admin console, one origin)
  - `api.YOUR_DOMAIN`
  - `admin.YOUR_DOMAIN` (the operator console on a name of its own)
  - `storage.YOUR_DOMAIN`
  - `www.YOUR_DOMAIN` (optional; redirects to the root)

A name in that list with no A record does not fail loudly — Caddy simply
never gets a certificate for it and that one hostname stays unreachable
while everything else works. If you do not want the admin subdomain, delete
its block from the `Caddyfile` rather than leaving the record unmade; the
console is always reachable at `https://YOUR_DOMAIN/admin/` regardless.

Why the storage hostname must be public: photo bytes never pass through the
API — the browser uploads straight to storage with presigned URLs, so the
URL the backend signs has to be reachable from customers' browsers.

## Steps

**One command** (installs Docker, clones, generates secrets, starts,
verifies — safe to re-run for updates):

```bash
curl -fsSL https://raw.githubusercontent.com/Furqatbek/memo-book/claude/memo-book-project-duulu7/deploy/bootstrap.sh \
    | bash -s -- yourdomain.uz
```

Or manually:

```bash
git clone https://github.com/Furqatbek/memo-book.git && cd memo-book/deploy
cp .env.prod.example .env
nano .env          # DOMAIN + every CHANGE_ME (openssl rand -hex 32)

docker compose -f docker-compose.prod.yml up -d --build
```

First boot builds the image, runs migrations, creates the bucket. Verify:

```bash
curl https://api.YOUR_DOMAIN/health   # {"status":"ok"}
curl https://api.YOUR_DOMAIN/ready    # checks db/redis/storage; expect 200
```

Open **`https://YOUR_DOMAIN`** — the whole frontend ships in the image: the
marketing site (all five languages) at `/`, the editor at `/editor/`, both
same-origin with the API, zero CORS setup. Every "Create your book" button
works immediately: create a book, upload photos, order end to end. Test a
payment with:

```bash
curl -X POST https://api.YOUR_DOMAIN/api/v1/payments/dev/webhook \
     -H "X-Dev-Signature: <DEV_PAYMENT_SECRET>" -H 'Content-Type: application/json' \
     -d '{"event_id":"t1","action":"pay","human_ref":"<ORDER_REF>","amount_minor":<AMOUNT>}'
```

## GitHub Pages (now optional)

The VPS serves the complete product, so the Pages copy at
`furqatbek.github.io/memo-book` is optional — keep it as a mirror, or
retire it and use `https://YOUR_DOMAIN` as the only address. To make the
Pages copy's editor work against the VPS, set in `editor/config.js`:

```js
apiBase: 'https://api.YOUR_DOMAIN',
```

commit, push — the Pages workflow redeploys. (`CORS_ORIGINS` and
`STORAGE_CORS_ORIGINS` in `.env` already allow the Pages origin.)

Frontend updates reach the VPS with a redeploy:
`git pull && docker compose -f docker-compose.prod.yml up -d --build`.

## Operations

```bash
docker compose -f docker-compose.prod.yml logs -f api worker   # watch
docker compose -f docker-compose.prod.yml up -d --build        # deploy update
docker compose -f docker-compose.prod.yml ps                   # health
```

**Firewall** (only SSH + web):

```bash
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable
```

**Backups** — the two volumes that matter are Postgres and MinIO:

```bash
# nightly crontab example
docker exec memobook-postgres-1 pg_dump -U memobook memobook | gzip > /backup/db-$(date +%F).sql.gz
tar czf /backup/minio-$(date +%F).tar.gz -C /var/lib/docker/volumes/memobook_minio_data/_data .
```

**Scaling later**: more render throughput = more `worker` replicas
(`docker compose up -d --scale worker=3`); Postgres/MinIO stay put.

## Before real customers

Work through "Go-live blockers" in [`../backend/README.md`](../backend/README.md):
real prices, printer-confirmed spine widths, a real payment acquirer
(`DEV_PAYMENTS_ENABLED=false`), Telegram credentials, and real contact
details on the site.
