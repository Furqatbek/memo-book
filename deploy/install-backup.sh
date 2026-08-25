#!/usr/bin/env bash
# Install the nightly backup: restic, a crontab entry, log rotation for its
# log, and a first run to prove it works.
#
#   ./install-backup.sh
#
# Reads the destination from deploy/.env (RESTIC_REPOSITORY and the
# credentials for it). Refuses to install a job that would silently do
# nothing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$HERE/.env}"
LOG="/var/log/memobook-backup.log"

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m XX %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root (or with sudo)"
[ -f "$ENV_FILE" ] || die "no $ENV_FILE — run bootstrap.sh first"

# shellcheck disable=SC1090
. "$ENV_FILE"

if [ -z "${RESTIC_REPOSITORY:-}" ]; then
  cat <<'HELP'
RESTIC_REPOSITORY is not set in deploy/.env, so there is nowhere to put the
backups. Pick a destination that is NOT this VPS — the point is surviving
the loss of this machine — and add it to deploy/.env:

  # Any S3-compatible bucket (Backblaze B2, Wasabi, Hetzner, AWS…):
  RESTIC_REPOSITORY=s3:https://s3.eu-central-003.backblazeb2.com/my-bucket/rspixel
  AWS_ACCESS_KEY_ID=...
  AWS_SECRET_ACCESS_KEY=...

  # Or another machine you can ssh into with a key:
  RESTIC_REPOSITORY=sftp:backup@other-host:/srv/rspixel

  # And a long random password. WRITE IT DOWN SOMEWHERE THAT IS NOT THIS
  # SERVER — without it the backups are unreadable, by you as well as by
  # anyone who steals them.
  RESTIC_PASSWORD=...

Then run this script again.
HELP
  exit 1
fi

say "Installing restic"
if ! command -v restic >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y restic
  else
    die "install restic by hand: https://restic.readthedocs.io"
  fi
fi
restic version

say "Log rotation for $LOG"
# Without this the backup log grows without bound and is the sort of file
# that fills a small VPS a year after anyone last thought about it.
cat > /etc/logrotate.d/memobook-backup <<'ROT'
/var/log/memobook-backup.log {
  weekly
  rotate 8
  compress
  missingok
  notifempty
  copytruncate
}
ROT

say "Crontab entry"
# 03:17 rather than 03:00: every cron job in the world runs on the hour, and
# an off-box destination is happier when we are not one of them.
CRON_LINE="17 3 * * * $HERE/backup.sh >> $LOG 2>&1"
CHECK_LINE="41 4 * * 0 $HERE/backup.sh --check >> $LOG 2>&1"
TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'memo-book/deploy/backup.sh' > "$TMP" || true
printf '%s\n%s\n' "$CRON_LINE" "$CHECK_LINE" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
crontab -l | grep backup.sh

say "First run — this one is not a test, it is a real backup"
"$HERE/backup.sh" 2>&1 | tee -a "$LOG"

say "Rehearsing a restore"
"$HERE/restore.sh" --drill

cat <<DONE

Backups are running nightly at 03:17, with a repository check on Sundays.

  Watch:    tail -f $LOG
  List:     $HERE/restore.sh --list
  Rehearse: $HERE/restore.sh --drill

Do this now, once, and you are done: put RESTIC_PASSWORD somewhere that is
not this server. Everything above is unreadable without it.
DONE
