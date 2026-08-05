# Deploying to a single VPS (fully self-hosted)

Everything runs on your own machine — nothing external:

| Piece | What runs it | Where the data lives |
|---|---|---|
| API + editor | FastAPI container (editor at `/editor`) | — |
| Database | Postgres 16 container | `pg_data` volume on the VPS disk |
| **Photo/PDF storage** | **MinIO container — an S3-compatible server, self-hosted** | `minio_data` volume on the VPS disk |
| Job queue | Redis 7 container + RQ worker | `redis_data` volume |
| Notifications | outbox worker container | Postgres |
| Expiry/reminders | daily lifecycle container | Postgres |
| HTTPS | Caddy (automatic Let's Encrypt) | `caddy_data` volume |

MinIO is "S3" in protocol only — the backend already speaks that protocol,
and the bytes sit in a plain directory on your VPS. No cloud account, no
external provider, no per-GB bills.

## Prerequisites

- A VPS (2 vCPU / 4GB RAM is comfortable; renders are the heavy part),
  Ubuntu 22.04+ or similar, with Docker and the compose plugin:
  `curl -fsSL https://get.docker.com | sh`
- A domain with two DNS **A records → your VPS IP**, created *before* first
  start (Caddy gets certificates on boot):
  - `api.YOUR_DOMAIN`
  - `storage.YOUR_DOMAIN`

Why the storage hostname must be public: photo bytes never pass through the
API — the browser uploads straight to storage with presigned URLs, so the
URL the backend signs has to be reachable from customers' browsers.

## Steps

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

Open **`https://api.YOUR_DOMAIN/editor/`** — the editor is served by the API
itself (same origin, zero CORS setup) and should let you create a book,
upload photos and order end to end. Test a payment with:

```bash
curl -X POST https://api.YOUR_DOMAIN/api/v1/payments/dev/webhook \
     -H "X-Dev-Signature: <DEV_PAYMENT_SECRET>" -H 'Content-Type: application/json' \
     -d '{"event_id":"t1","action":"pay","human_ref":"<ORDER_REF>","amount_minor":<AMOUNT>}'
```

## Connecting the GitHub Pages site

The site's "Create your book" buttons open the Pages copy of the editor. To
point it at your VPS, set in `editor/config.js`:

```js
apiBase: 'https://api.YOUR_DOMAIN',
```

commit, push — the Pages workflow redeploys. (`CORS_ORIGINS` and
`STORAGE_CORS_ORIGINS` in `.env` already allow the Pages origin.)
Alternatively skip Pages for the editor entirely and link the site's
buttons to `https://api.YOUR_DOMAIN/editor/`.

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
