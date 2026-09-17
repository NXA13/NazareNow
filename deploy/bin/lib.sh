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
