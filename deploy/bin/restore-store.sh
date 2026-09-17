#!/usr/bin/env bash
#
# Put a snapshot back, with the scheduler and API stopped around it.
#
# This exists to be *run*, not read. ADR 0007's criterion is that a restore has actually
# been performed at least once and documented, because an untested backup is a belief. The
# rehearsal in deploy/README.md uses this script against a scratch path, so the first real
# restore is not the first time anyone has run it.
#
#   restore-store.sh <snapshot.db.gz> [destination]
#
# With no destination it restores over $NAZARENOW_DB, which is the real thing and asks
# before proceeding. Give a destination to rehearse somewhere harmless.

set -euo pipefail

snapshot="${1:-}"
destination="${2:-${NAZARENOW_DB:-}}"

if [[ -z "$snapshot" || -z "$destination" ]]; then
  echo "usage: restore-store.sh <snapshot.db.gz> [destination]" >&2
  echo "       destination defaults to \$NAZARENOW_DB" >&2
  exit 2
fi

if [[ ! -f "$snapshot" ]]; then
  echo "No snapshot at $snapshot" >&2
  exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "Unpacking $snapshot"
gunzip -c "$snapshot" >"$work/restored.db"

# Check before touching anything live. A snapshot that cannot be read is not a restore
# candidate, and finding that out after overwriting the original would be the one
# unrecoverable mistake this whole file exists to prevent.
if ! sqlite3 "$work/restored.db" 'PRAGMA integrity_check;' | grep -qx 'ok'; then
  echo "Snapshot failed its integrity check. Refusing to restore it." >&2
  exit 1
fi

runs="$(sqlite3 "$work/restored.db" 'SELECT COUNT(*) FROM pipeline_run;')"
calls="$(sqlite3 "$work/restored.db" 'SELECT COUNT(*) FROM day_call;')"
latest="$(sqlite3 "$work/restored.db" 'SELECT COALESCE(MAX(started_at), "never") FROM pipeline_run;')"
echo "Snapshot holds $runs pipeline runs, $calls day calls, most recent run $latest"

live=false
if [[ -n "${NAZARENOW_DB:-}" && "$destination" == "$NAZARENOW_DB" ]]; then
  live=true
fi

if [[ "$live" == true ]]; then
  echo
  echo "This will replace the live store at $destination."
  read -r -p "Type the number of pipeline runs above to confirm: " confirmation
  if [[ "$confirmation" != "$runs" ]]; then
    echo "Not confirmed. Nothing changed." >&2
    exit 1
  fi

  # Stopped, not left running. The scheduler holds a write connection and would carry on
  # writing into a file being swapped underneath it.
  echo "Stopping services"
  sudo systemctl stop nazarenow-api.service nazarenow-scheduler.service
fi

if [[ -f "$destination" ]]; then
  aside="$destination.displaced-$(date -u +%Y%m%dT%H%M%SZ)"
  echo "Moving the existing database aside to $aside"
  mv "$destination" "$aside"
fi

mkdir -p "$(dirname "$destination")"
cp "$work/restored.db" "$destination"
echo "Restored to $destination"

if [[ "$live" == true ]]; then
  # Scheduler first: it opens the store writable and runs any migration the restored file
  # predates. The API opens read-only and cannot, so starting it first would fail until
  # the scheduler had been round once anyway.
  echo "Starting services"
  sudo systemctl start nazarenow-scheduler.service
  sleep 5
  sudo systemctl start nazarenow-api.service
  systemctl --no-pager --lines=0 status nazarenow-scheduler.service nazarenow-api.service
fi
