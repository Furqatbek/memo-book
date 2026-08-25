#!/usr/bin/env bash
# Restore from a backup made by backup.sh.
#
#   ./restore.sh --list                    # what snapshots exist
#   ./restore.sh --drill                   # rehearse: restore to a temp dir,
#                                          #   check the dump, change nothing
#   ./restore.sh --db      latest          # put the database back
#   ./restore.sh --objects latest          # put the photos back
#
# Run --drill after setting backups up, and once a quarter after that. A
# backup that has never been restored is a hope, not a backup: the failure
# modes (wrong password, half-configured repository, a dump nothing can
# read) all look exactly like success until the day you need it.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$HERE/.env}"
COMPOSE_FILE="${COMPOSE_FILE:-$HERE/docker-compose.prod.yml}"
PG_CONTAINER="${PG_CONTAINER:-postgres}"
MINIO_DATA_DIR="${MINIO_DATA_DIR:-/var/lib/docker/volumes/memobook_minio_data/_data}"

log() { printf '%s  %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }
die() { printf '\033[1;31m XX %s\033[0m\n' "$*" >&2; exit 1; }

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
command -v restic >/dev/null 2>&1 || die "restic is not installed"
[ -n "${RESTIC_REPOSITORY:-}" ] || die "RESTIC_REPOSITORY is not set in $ENV_FILE"
export RESTIC_REPOSITORY

usage() { sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

MODE="${1:-}"
SNAP="${2:-latest}"

case "$MODE" in
  --list)
    restic snapshots --tag memobook
    ;;

  --drill)
    # Everything a real restore does, except touching anything real.
    WORK="$(mktemp -d)"
    trap 'rm -rf "$WORK"' EXIT
    log "restoring the newest database dump into $WORK"
    restic restore latest --tag db --target "$WORK" \
      || die "could not restore the dump — wrong password, or an empty repository"
    DUMP="$(find "$WORK" -name db.dump -print -quit)"
    [ -n "$DUMP" ] || die "the snapshot contains no db.dump"
    SIZE=$(stat -c%s "$DUMP")
    log "dump restored: $SIZE bytes"
    [ "$SIZE" -gt 1024 ] || die "the dump is $SIZE bytes — that is not a database"
    # Two different questions, and both matter. --list reads the table of
    # contents, which says the dump contains tables with data in them. -f
    # /dev/null decodes every block, which says the dump is not truncated —
    # --list alone passes a file cut off halfway, because the contents live
    # at the front. Neither needs a running server.
    if command -v pg_restore >/dev/null 2>&1; then
      TABLES=$(pg_restore --list "$DUMP" | grep -c 'TABLE DATA' || true)
      log "the archive lists $TABLES tables with data"
      [ "$TABLES" -gt 0 ] || die "the dump has no table data in it"
      pg_restore -f /dev/null "$DUMP" >/dev/null 2>&1 \
        || die "the dump does not decode cleanly — it is truncated or corrupt"
      log "and it decodes cleanly from end to end"
    else
      log "(pg_restore not on this host — skipped the archive check)"
    fi
    log "checking the object-store side of the newest snapshot"
    restic restore latest --tag objects --target "$WORK/objects" \
      --include "$MINIO_DATA_DIR/memobook" 2>/dev/null \
      || log "(no objects restored — fine if no photos have been uploaded yet)"
    log "DRILL PASSED — this repository can be restored from."
    ;;

  --db)
    log "This REPLACES the live database with snapshot $SNAP."
    read -r -p "Type the word restore to continue: " ok
    [ "$ok" = "restore" ] || die "cancelled"
    WORK="$(mktemp -d)"
    trap 'rm -rf "$WORK"' EXIT
    restic restore "$SNAP" --tag db --target "$WORK" || die "restore failed"
    DUMP="$(find "$WORK" -name db.dump -print -quit)"
    [ -n "$DUMP" ] || die "the snapshot contains no db.dump"
    # Stop everything that writes before replacing what it writes to.
    log "stopping the writers"
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
      stop api worker outbox lifecycle
    log "restoring into postgres (--clean drops what it replaces)"
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
      exec -T "$PG_CONTAINER" pg_restore -U memobook -d memobook --clean --if-exists \
      < "$DUMP" || log "WARNING: pg_restore reported errors — read them before starting up"
    log "starting back up"
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
      start api worker outbox lifecycle
    log "done"
    ;;

  --objects)
    log "This writes snapshot $SNAP over $MINIO_DATA_DIR."
    read -r -p "Type the word restore to continue: " ok
    [ "$ok" = "restore" ] || die "cancelled"
    log "stopping minio"
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" stop minio
    # Restores to / because the snapshot holds absolute paths; existing
    # files are overwritten, files added since the snapshot are left alone.
    restic restore "$SNAP" --tag objects --target / || die "restore failed"
    log "starting minio"
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" start minio
    log "done"
    ;;

  ""|-h|--help) usage 0 ;;
  *) die "unknown option: $MODE  (try --help)" ;;
esac
