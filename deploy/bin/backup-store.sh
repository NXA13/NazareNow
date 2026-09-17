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

# shellcheck source=deploy/bin/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

: "${NAZARENOW_DB:?NAZARENOW_DB is not set — refusing to guess which database to back up}"
: "${NAZARENOW_BACKUP_DIR:?NAZARENOW_BACKUP_DIR is not set}"
REMOTE="${NAZARENOW_BACKUP_REMOTE:-}"

# Grandfather-father-son, not a flat count of the most recent N.
#
# A Pipeline Run appends about 180 kB and there are eight a day, so the store grows by
# roughly half a gigabyte a year. Thirty flat daily copies of that is thirty near-identical
# full snapshots — about 1.5 GB on the SSD by next autumn, and a fresh upload every night of
# a file that changed by one percent. These three buckets cost a third of that and reach
# back a year instead of a month, which matters for a record measured in Big-Wave Seasons.
KEEP_DAILY="${NAZARENOW_KEEP_DAILY:-7}"
KEEP_WEEKLY="${NAZARENOW_KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${NAZARENOW_KEEP_MONTHLY:-12}"

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
if ! store_is_intact "$snapshot"; then
  # Renamed rather than left as-is. The rotation below globs *.db.gz, so a bare .db would
  # sit there forever, invisible to the count that decides what to delete.
  mv "$snapshot" "$snapshot.corrupt"
  echo "Snapshot failed its integrity check. Kept for inspection as $snapshot.corrupt" >&2
  exit 1
fi

summary="$(store_summary "$snapshot")"

gzip -f "$snapshot"
echo "Backed up $NAZARENOW_DB -> $snapshot.gz"
echo "  $summary"

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
# new bad one. The policy itself lives in lib.sh, where it can be tested against a directory
# of fabricated snapshots without a database or a network anywhere near it.
prune_snapshots "$NAZARENOW_BACKUP_DIR" "$KEEP_DAILY" "$KEEP_WEEKLY" "$KEEP_MONTHLY" "$REMOTE"
