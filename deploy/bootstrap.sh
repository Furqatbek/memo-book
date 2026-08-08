#!/usr/bin/env bash
# One-command VPS deployment for RS Pixel.
#
#   curl -fsSL https://raw.githubusercontent.com/Furqatbek/memo-book/claude/memo-book-project-duulu7/deploy/bootstrap.sh \
#       | bash -s -- rspixel.uz
#
# Idempotent: safe to re-run — it pulls the latest code and restarts the
# stack; the generated .env (with its secrets) is created once and kept.
# Requires: Ubuntu/Debian VPS, root (or sudo), DNS A records already
# pointing at this server for DOMAIN, api.DOMAIN, storage.DOMAIN.
set -euo pipefail

DOMAIN="${1:-rspixel.uz}"
BRANCH="${BRANCH:-claude/memo-book-project-duulu7}"
REPO="${REPO:-https://github.com/Furqatbek/memo-book.git}"
DIR="${DIR:-/opt/memo-book}"

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m !! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m XX %s\033[0m\n' "$*"; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root (or with sudo)"

# ---------- DNS sanity (Caddy needs these to get TLS certificates) ----------
say "Checking DNS for $DOMAIN"
SERVER_IP=$(curl -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')
DNS_OK=1
for host in "$DOMAIN" "api.$DOMAIN" "storage.$DOMAIN"; do
  resolved=$(getent ahostsv4 "$host" 2>/dev/null | awk 'NR==1{print $1}' || true)
  if [ -z "$resolved" ]; then
    warn "$host does not resolve yet"
    DNS_OK=0
  elif [ "$resolved" != "$SERVER_IP" ]; then
    warn "$host resolves to $resolved, this server is $SERVER_IP"
    DNS_OK=0
  else
    echo "    $host -> $resolved  OK"
  fi
done
if [ "$DNS_OK" = 0 ]; then
  warn "Create/fix the A records ($DOMAIN, api.$DOMAIN, storage.$DOMAIN -> $SERVER_IP)."
  warn "Continuing anyway — HTTPS will start working once DNS is right."
fi

# ---------- swap (small VPSes: photo ingest spikes a few hundred MB) --------
TOTAL_MB=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
if [ "$TOTAL_MB" -lt 3500 ] && [ ! -f /swapfile ]; then
  say "RAM is ${TOTAL_MB}MB — adding 2GB swap"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---------- docker ----------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || die "docker compose plugin missing — install docker-compose-plugin"

# ---------- firewall (only if ufw exists and is already active) -------------
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q 'Status: active'; then
  ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
  say "ufw: allowed 22/80/443"
fi

# ---------- code -------------------------------------------------------------
if [ -d "$DIR/.git" ]; then
  say "Updating $DIR"
  git -C "$DIR" fetch origin "$BRANCH" && git -C "$DIR" checkout "$BRANCH" \
    && git -C "$DIR" pull --ff-only origin "$BRANCH"
else
  say "Cloning $REPO ($BRANCH) to $DIR"
  git clone --branch "$BRANCH" "$REPO" "$DIR"
fi

# ---------- .env (generated once; kept across re-runs) -----------------------
ENV="$DIR/deploy/.env"
if [ ! -f "$ENV" ]; then
  say "Generating deploy/.env with fresh secrets"
  PG_PW=$(openssl rand -hex 24)
  MINIO_PW=$(openssl rand -hex 24)
  DEV_PW=$(openssl rand -hex 24)
  sed -e "s/^DOMAIN=.*/DOMAIN=$DOMAIN/" \
      -e "s/CHANGE_ME_PG/$PG_PW/g" \
      -e "s/CHANGE_ME_MINIO/$MINIO_PW/g" \
      -e "s/CHANGE_ME_SECRET/$DEV_PW/g" \
      -e "s/rspixel\.uz/$DOMAIN/g" \
      "$DIR/deploy/.env.prod.example" > "$ENV"
  chmod 600 "$ENV"
else
  say "Keeping existing deploy/.env"
fi

# ---------- up ---------------------------------------------------------------
say "Building and starting the stack (first build takes a few minutes)"
cd "$DIR/deploy"
docker compose -f docker-compose.prod.yml --env-file .env up -d --build

say "Waiting for the API"
for i in $(seq 1 60); do
  if docker compose -f docker-compose.prod.yml exec -T api curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
docker compose -f docker-compose.prod.yml exec -T api curl -sf http://localhost:8000/health >/dev/null 2>&1 \
  || { docker compose -f docker-compose.prod.yml logs --tail 30 api; die "API did not become healthy — logs above"; }

say "Deployed."
cat <<DONE

  Site + editor:   https://$DOMAIN   (editor at /editor/)
  API health:      https://$DOMAIN/health     /ready
  Swagger:         https://$DOMAIN/docs

  Card-transfer payments (pilot):
    docker compose -f docker-compose.prod.yml exec api \\
        python scripts/confirm_payment.py --list      # orders awaiting payment
    docker compose -f docker-compose.prod.yml exec api \\
        python scripts/confirm_payment.py REF         # confirm a transfer

  Advance an order after printing/shipping:
    cd $DIR/deploy && docker compose -f docker-compose.prod.yml exec api \\
        python scripts/order_status.py REF sent_to_production|shipped|delivered

  Next steps (see $DIR/docs/deployment.md):
    - set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in deploy/.env, then:
        docker compose -f docker-compose.prod.yml up -d
        docker compose -f docker-compose.prod.yml exec api python scripts/telegram_check.py
    - set PAY_CARD_NUMBER / PAY_CARD_HOLDER (shown on the order page)
    - set real PRICE_MINOR_* and the printer's SPINE_MM_* the same way
    - set up the backup crontab from the deployment guide
DONE
if [ "$DNS_OK" = 0 ]; then
  warn "Reminder: DNS was not fully pointing here — HTTPS activates once it is."
fi
