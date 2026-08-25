#!/usr/bin/env bash
# Nightly off-box backup of everything a customer would notice losing:
# the database (orders, books, layouts, the audit trail) and the object
# store (their photos and the print PDFs).
#
#   ./backup.sh              # what cron runs
#   ./backup.sh --check      # verify the repository, then exit
#
# Install it with install-backup.sh, or by hand:
#   17 3 * * * /opt/memo-book/deploy/backup.sh >> /var/log/memobook-backup.log 2>&1
#
# WHY restic rather than tar + scp: the photos are the bulk of the data and
# they barely change between nights. restic stores each night as a snapshot
# but only uploads blocks it has never seen, so the second backup of a 20 GB
# store costs megabytes. It also encrypts before anything leaves the machine,
# which matters because the destination is somebody else's disk and the
# contents are strangers' family photographs.
#
# WHAT THIS DOES NOT PROTECT AGAINST: an object written by MinIO at the exact
# moment the file tree is read can land in the snapshot half-written. That is
# one photo, in one snapshot, on one night — recoverable from any other
# snapshot. Stopping the stack nightly to avoid it would cost more than it
# saves.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$HERE/.env}"
COMPOSE_FILE="${COMPOSE_FILE:-$HERE/docker-compose.prod.yml}"

# Overridable so this is testable, and so a differently-named stack or a
# relocated Docker root does not require editing the script.
PG_CONTAINER="${PG_CONTAINER:-postgres}"
MINIO_DATA_DIR="${MINIO_DATA_DIR:-/var/lib/docker/volumes/memobook_minio_data/_data}"

RETENTION_DAILY="${RETENTION_DAILY:-7}"
RETENTION_WEEKLY="${RETENTION_WEEKLY:-5}"
RETENTION_MONTHLY="${RETENTION_MONTHLY:-6}"

log()  { printf '%s  %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }
die()  { log "FAILED: $*"; notify "Backup failed on $(hostname): $*"; exit 1; }

# The founder already gets order notifications on Telegram, so a backup that
# stops working can say so in the same place. A backup nobody is told about
# failing is the same as no backup — you find out on the day you need it.
notify() {
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ] || return 0
  curl -fsS --max-time 20 -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" --data-urlencode "text=$1" \
    >/dev/null 2>&1 || log "(could not reach Telegram to report this)"
}

# ---------------------------------------------------------------- config ----
# The .env holds the database password, the Telegram credentials and the
# backup destination. Sourced rather than parsed: it is already a shell
# fragment that docker compose reads, and duplicating a parser for it would
# be a second thing to get wrong.
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090  # path is configurable by design
  . "$ENV_FILE"
  set +a
fi

command -v restic >/dev/null 2>&1 \
  || die "restic is not installed — run deploy/install-backup.sh"

# Fail loudly on an unconfigured destination. The alternative is a job that
# runs every night, reports success and backs up nothing, which is strictly
# worse than no job at all: it buys false confidence.
[ -n "${RESTIC_REPOSITORY:-}" ] \
  || die "RESTIC_REPOSITORY is not set in $ENV_FILE — backups are NOT running"
[ -n "${RESTIC_PASSWORD:-}${RESTIC_PASSWORD_FILE:-}" ] \
  || die "no RESTIC_PASSWORD or RESTIC_PASSWORD_FILE — backups are NOT running"
export RESTIC_REPOSITORY

case "$RESTIC_REPOSITORY" in
  /*|local:*)
    log "WARNING: $RESTIC_REPOSITORY is a path on this machine. That survives"
    log "         a bad deploy but not a dead VPS. Point it off-box." ;;
esac

if [ ! -d "$MINIO_DATA_DIR" ]; then
  die "no object store at $MINIO_DATA_DIR (set MINIO_DATA_DIR if the volume moved)"
fi

# restic init is safe to repeat; on an existing repository it exits non-zero
# and says so, which is not an error here.
restic snapshots >/dev/null 2>&1 || {
  log "initialising the repository at $RESTIC_REPOSITORY"
  restic init || die "could not initialise the repository — check credentials"
}

# ----------------------------------------------------------------- check ----
if [ "${1:-}" = "--check" ]; then
  log "verifying repository structure and 5% of the data"
  restic check --read-data-subset=5% || die "repository check failed"
  log "repository OK"
  exit 0
fi

# ------------------------------------------------------------- database ----
# -Fc is the custom format: compressed, and pg_restore can read it
# selectively.
#
# Written to a file and checked BEFORE it goes into the repository, rather
# than piped straight in. If pg_dump dies halfway through a pipe, restic sees
# a clean EOF and stores the truncated result as a perfectly good snapshot —
# the pipeline reports the failure, but by then the repository contains a
# dump that looks fine and restores to half a database. The photos are what
# make this dataset large; the dump is orders and layouts, so the disk space
# this costs is megabytes.
log "backing up the database"
DUMP_CMD=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
          exec -T "$PG_CONTAINER" pg_dump -U memobook -Fc memobook)
[ -n "${PGDUMP_CMD:-}" ] && read -r -a DUMP_CMD <<< "$PGDUMP_CMD"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
DUMP="$WORK/db.dump"

"${DUMP_CMD[@]}" > "$DUMP" \
  || die "the database dump did not complete — nothing was written"

DUMP_SIZE=$(stat -c%s "$DUMP" 2>/dev/null || echo 0)
[ "$DUMP_SIZE" -gt 1024 ] \
  || die "the dump is $DUMP_SIZE bytes — that is not a database"

# Decode the whole archive to nothing. `pg_restore --list` would be faster
# but only reads the table of contents, which lives at the START of the file
# — it happily passes a dump that was cut off halfway through the data. This
# reads every block, so a truncated or corrupt dump fails here instead of on
# the day it is needed. It needs no server, and on a 1 MB dump it costs
# about 50 ms.
if command -v pg_restore >/dev/null 2>&1; then
  pg_restore -f /dev/null "$DUMP" >/dev/null 2>&1 \
    || die "the dump does not decode cleanly — refusing to store it"
else
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
    exec -T "$PG_CONTAINER" pg_restore -f /dev/null < "$DUMP" >/dev/null 2>&1 \
    || die "the dump does not decode cleanly — refusing to store it"
fi
log "dump verified: $DUMP_SIZE bytes"

restic backup --stdin --stdin-filename db.dump --tag db --tag memobook < "$DUMP" \
  || die "could not store the dump"
rm -f "$DUMP"

# --------------------------------------------------------------- photos ----
# Customer photos and rendered PDFs. Deduplicated against every previous
# night, so this is cheap after the first run.
log "backing up the object store"
restic backup "$MINIO_DATA_DIR" --tag objects --tag memobook \
  || die "the object store backup did not complete"

# ------------------------------------------------------------ retention ----
# Keeping every night forever would eventually cost more than the business
# earns. Six months of monthlies is long enough to notice a corruption that
# happened before the last daily.
log "pruning old snapshots"
restic forget --tag memobook \
  --keep-daily "$RETENTION_DAILY" \
  --keep-weekly "$RETENTION_WEEKLY" \
  --keep-monthly "$RETENTION_MONTHLY" \
  --prune || log "WARNING: pruning failed; the backups above are still good"

# The whole JSON array is one line, so count occurrences rather than lines —
# `grep -c` here would report 1 no matter how many snapshots exist.
KEPT=$(restic snapshots --tag memobook --json 2>/dev/null \
       | grep -o '"short_id"' | wc -l | tr -d ' ')
log "done — ${KEPT:-?} snapshots in the repository"
