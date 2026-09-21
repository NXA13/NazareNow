# Shared by the three scripts beside it. Sourced, never executed.
#
# Two things lived in more than one script before this existed: the summary of what a
# database actually holds, and the order the services are restarted in. The second is the
# one that mattered — the ordering is a real constraint (the scheduler opens the store
# writable and migrates it; the API opens it read-only and cannot), so having it written out
# twice meant a change to it had to be remembered twice.

# What a store holds, in one line, so the journal answers "was the record still growing?"
# without anyone opening the database. Takes a path to a database, not a snapshot archive.
store_summary() {
  local db="$1"
  local runs calls latest
  runs="$(sqlite3 "$db" 'SELECT COUNT(*) FROM pipeline_run;')"
  calls="$(sqlite3 "$db" 'SELECT COUNT(*) FROM day_call;')"
  latest="$(sqlite3 "$db" 'SELECT COALESCE(MAX(started_at), "never") FROM pipeline_run;')"
  echo "pipeline runs: $runs, day calls: $calls, most recent run: $latest"
}

# Just the run count, which restore-store.sh uses as its confirmation token.
store_run_count() {
  sqlite3 "$1" 'SELECT COUNT(*) FROM pipeline_run;'
}

# Readable, or not a backup. An archive that cannot be opened is the failure this whole
# directory exists to prevent, and it is cheap to rule out.
store_is_intact() {
  sqlite3 "$1" 'PRAGMA integrity_check;' 2>/dev/null | grep -qx 'ok'
}

# Scheduler first, then the API, in that order and never the other way.
#
# The scheduler opens the store writable and applies any migration the running version
# brings; the API opens it read-only with `create=False` and can do neither. Starting the
# API first on a fresh or freshly-restored store means it exits until the scheduler has been
# round once — which `Restart=` recovers from, but noisily and for no reason.
restart_services() {
  sudo systemctl restart nazarenow-scheduler.service
  sleep 5
  sudo systemctl restart nazarenow-api.service
}

# Grandfather-father-son retention over a directory of snapshots.
#
#   prune_snapshots <dir> <keep_daily> <keep_weekly> <keep_monthly> [rclone_remote]
#
# Walks newest first and keeps each snapshot that is the most recent one in a day, a week or
# a month still within that bucket's budget. A snapshot kept as today's daily also occupies
# this week's and this month's slot, which is what makes the buckets nest rather than
# multiply. Everything else is deleted, locally and — if a remote is given — from the remote
# too, because an archive nobody prunes is a storage bill that eventually ends the backups.
#
# The date arithmetic reads the stamp out of the filename rather than the filesystem. A copy,
# a restore or an rsync rewrites mtime, and a retention policy that quietly re-ages its own
# archive when someone moves a directory is worse than no policy at all.
prune_snapshots() {
  local dir="$1" keep_daily="$2" keep_weekly="$3" keep_monthly="$4" remote="${5:-}"

  local -A day_taken week_taken month_taken
  local daily=0 weekly=0 monthly=0 pruned=0 kept=0
  local path stamp day week month keep

  local snapshots=()
  mapfile -t snapshots < <(ls -1 "$dir"/nazarenow-*.db.gz 2>/dev/null | sort -r)

  for path in "${snapshots[@]:-}"; do
    [[ -n "$path" ]] || continue

    # nazarenow-20260917T032000Z.db.gz -> 20260917T032000Z
    stamp="$(basename "$path")"
    stamp="${stamp#nazarenow-}"
    stamp="${stamp%.db.gz}"
    day="${stamp:0:8}"

    # An unparseable name is kept, never deleted. A stray file is a mystery worth looking
    # at, not a reason for a backup script to start removing things it cannot read.
    if ! week="$(date -u -d "$day" +%G-%V 2>/dev/null)"; then
      echo "  keeping $(basename "$path"): cannot read a date from its name" >&2
      continue
    fi
    month="${stamp:0:6}"

    keep=false
    if [[ -z "${day_taken[$day]:-}" && "$daily" -lt "$keep_daily" ]]; then
      day_taken[$day]=1
      daily=$((daily + 1))
      keep=true
    fi
    if [[ -z "${week_taken[$week]:-}" && "$weekly" -lt "$keep_weekly" ]]; then
      week_taken[$week]=1
      weekly=$((weekly + 1))
      keep=true
    fi
    if [[ -z "${month_taken[$month]:-}" && "$monthly" -lt "$keep_monthly" ]]; then
      month_taken[$month]=1
      monthly=$((monthly + 1))
      keep=true
    fi

    if [[ "$keep" == true ]]; then
      kept=$((kept + 1))
      continue
    fi

    rm -f -- "$path"
    pruned=$((pruned + 1))

    # Failure here is reported, never fatal: the local snapshot is already gone and the new
    # one is already uploaded, so a network problem at this point must not fail the run.
    if [[ -n "$remote" ]]; then
      if ! rclone deletefile "$remote/$(basename "$path")" 2>/dev/null; then
        echo "  could not prune $(basename "$path") from $remote" >&2
      fi
    fi
  done

  echo "  retention: $kept kept ($daily daily, $weekly weekly, $monthly monthly), $pruned pruned"
}
