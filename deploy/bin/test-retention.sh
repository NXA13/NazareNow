#!/usr/bin/env bash
#
# Exercise prune_snapshots against fabricated snapshots.
#
# The backup is the one part of this deployment with no test suite behind it and the worst
# failure mode — a retention bug deletes the thing ADR 0007 calls the only asset worth
# protecting, and does it silently, months before anyone looks. So the policy is checked
# here against empty files with the right names, which needs no database, no network and no
# Raspberry Pi.
#
#   deploy/bin/test-retention.sh
#
# Exits non-zero on the first failure.

set -euo pipefail

# shellcheck source=deploy/bin/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

failures=0

check() {
  local what="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "  ok   $what"
  else
    echo "  FAIL $what: expected $expected, got $actual" >&2
    failures=$((failures + 1))
  fi
}

# A directory holding one snapshot a day, counting back from a fixed date. Fixed rather
# than `today`, so the expected counts below do not change depending on when this is run.
fabricate() {
  local dir="$1" days="$2" from="$3" i stamp
  rm -rf "$dir" && mkdir -p "$dir"
  for ((i = 0; i < days; i++)); do
    stamp="$(date -u -d "$from - $i days" +%Y%m%dT032000Z)"
    : >"$dir/nazarenow-$stamp.db.gz"
  done
}

surviving() {
  find "$1" -name 'nazarenow-*.db.gz' | wc -l | tr -d ' '
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "One year of daily snapshots, kept 7 daily / 4 weekly / 12 monthly"
fabricate "$work/year" 365 2026-09-17
prune_snapshots "$work/year" 7 4 12 >/dev/null
# 7 distinct days, then 4 distinct weeks, then 12 distinct months. The daily ones sit inside
# the first week or two and the weeklies inside the first months, so the buckets overlap and
# the total is below 23.
check "a year collapses to under 23 snapshots" "true" \
  "$([[ "$(surviving "$work/year")" -le 23 ]] && echo true || echo false)"
check "and keeps more than the 7 dailies alone" "true" \
  "$([[ "$(surviving "$work/year")" -gt 7 ]] && echo true || echo false)"

echo
echo "The newest snapshot is never deleted"
newest="$(find "$work/year" -name 'nazarenow-*.db.gz' | sort -r | head -1)"
check "newest survived" "nazarenow-20260917T032000Z.db.gz" "$(basename "$newest")"

echo
echo "Fewer snapshots than the budget: nothing is pruned"
fabricate "$work/few" 3 2026-09-17
prune_snapshots "$work/few" 7 4 12 >/dev/null
check "all three kept" "3" "$(surviving "$work/few")"

echo
echo "An empty directory does not error"
mkdir -p "$work/empty"
prune_snapshots "$work/empty" 7 4 12 >/dev/null
check "still empty, still exit 0" "0" "$(surviving "$work/empty")"

echo
echo "A file with an unreadable name is kept, not deleted"
fabricate "$work/odd" 30 2026-09-17
: >"$work/odd/nazarenow-notadate.db.gz"
prune_snapshots "$work/odd" 1 0 0 2>/dev/null >/dev/null
check "the stray file survived" "true" \
  "$([[ -f "$work/odd/nazarenow-notadate.db.gz" ]] && echo true || echo false)"

echo
echo "Several snapshots in one day collapse to one"
rm -rf "$work/sameday" && mkdir -p "$work/sameday"
for hour in 01 05 09 13 17 21; do
  : >"$work/sameday/nazarenow-20260917T${hour}0000Z.db.gz"
done
prune_snapshots "$work/sameday" 7 4 12 >/dev/null
check "one survivor for the day" "1" "$(surviving "$work/sameday")"
check "and it is the latest of them" "nazarenow-20260917T210000Z.db.gz" \
  "$(basename "$(find "$work/sameday" -name 'nazarenow-*.db.gz' | head -1)")"

echo
if [[ "$failures" -gt 0 ]]; then
  echo "$failures check(s) failed." >&2
  exit 1
fi
echo "All retention checks passed."
