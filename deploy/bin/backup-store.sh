#!/usr/bin/env bash
#
# Snapshot the store, keep a rolling window of snapshots, and copy each one off the host.
#
# ADR 0007: "Backups are therefore not operational hygiene here. They are the reason the
# deployment matters." The Gold Days can only ever measure recall; the only unbiased source
# of negatives is this system running forward and recording what it called on every ordinary
# day nobody wrote about. A forecast archive can be re-fetched. That record cannot.
#
# Run by nazarenow-backup.timer. Safe to run by hand at any time.

set -euo pipefail

: "${NAZARENOW_DB:?NAZARENOW_DB is not set — refusing to guess which database to back up}"
: "${NAZARENOW_BACKUP_DIR:?NAZARENOW_BACKUP_DIR is not set}"
KEEP="${NAZARENOW_BACKUP_KEEP:-30}"
REMOTE="${NAZARENOW_BACKUP_REMOTE:-}"

if [[ ! -f "$NAZARENOW_DB" ]]; then
  echo "No database at $NAZARENOW_DB. Nothing to back up." >&2
  exit 1
fi

mkdir -p "$NAZARENOW_BACKUP_DIR"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
snapshot="$NAZARENOW_BACKUP_DIR/nazarenow-$stamp.db"

# `.backup` and not `cp`. The scheduler writes every three hours, and copying a file while
# SQLite is mid-transaction yields an archive that looks fine and restores to a corrupt
# database — the worst possible failure for the one asset here worth protecting. `.backup`
# uses SQLite's online backup API, which takes a consistent snapshot of a live database.
sqlite3 "$NAZARENOW_DB" ".backup '$snapshot'"

# Prove the snapshot is readable before it is allowed to count as a backup. An unverified
# copy is the same belief ADR 0007 refuses to accept.
if ! sqlite3 "$snapshot" 'PRAGMA integrity_check;' | grep -qx 'ok'; then
  echo "Snapshot $snapshot failed its integrity check. Keeping it for inspection." >&2
  exit 1
fi

# Report what was actually captured, so the journal answers "was the record still growing?"
# without anyone opening the database.
runs="$(sqlite3 "$snapshot" 'SELECT COUNT(*) FROM pipeline_run;')"
calls="$(sqlite3 "$snapshot" 'SELECT COUNT(*) FROM day_call;')"
latest="$(sqlite3 "$snapshot" 'SELECT COALESCE(MAX(started_at), "never") FROM pipeline_run;')"

gzip -f "$snapshot"
echo "Backed up $NAZARENOW_DB -> $snapshot.gz"
echo "  pipeline runs: $runs, day calls: $calls, most recent run: $latest"

# Off the host. Without this the snapshot sits on the same SSD as the original and dies
# with it — which is a defence against corruption, not against losing the machine, and
# #28's criterion asks for the second.
if [[ -n "$REMOTE" ]]; then
  rclone copy "$snapshot.gz" "$REMOTE" --no-traverse
  echo "  copied off host to $REMOTE"
else
  echo "  WARNING: NAZARENOW_BACKUP_REMOTE is unset, so this snapshot is on the same" >&2
  echo "  machine as the database it protects. Set it in /etc/nazarenow/nazarenow.env." >&2
fi

# Rotate last, so a failure above never deletes an old good snapshot to make room for a
# new bad one.
mapfile -t stale < <(ls -1t "$NAZARENOW_BACKUP_DIR"/nazarenow-*.db.gz 2>/dev/null | tail -n "+$((KEEP + 1))")
for old in "${stale[@]:-}"; do
  [[ -n "$old" ]] || continue
  rm -f -- "$old"
  echo "  rotated out $(basename "$old")"
done
