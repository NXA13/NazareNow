#!/usr/bin/env bash
#
# Exercise wait_for_api against a stubbed request.
#
# The deploy's final check is the only thing standing between a broken API and a deploy that
# reports success, so it has to fail when the API is down — and it has to stop failing when
# the API is merely a second behind the restart that started it. Those two requirements pull
# in opposite directions, which is exactly the kind of thing worth pinning down.
#
# `api_responds` is redefined below, so nothing here binds a port, waits on uvicorn or needs
# a Raspberry Pi.
#
#   deploy/bin/test-api-wait.sh
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

# Stands in for the one request lib.sh makes. `answer_from` is the attempt number it starts
# succeeding on, so a case can say "the API binds its socket on the third ask"; 0 means it
# never comes up at all.
attempts=0
answer_from=0
api_responds() {
  attempts=$((attempts + 1))
  [[ "$answer_from" -gt 0 && "$attempts" -ge "$answer_from" ]]
}

# Sets `result` rather than printing it: a command substitution would run wait_for_api in a
# subshell, and the attempt counter the cases below assert on would never come back.
run() {
  attempts=0
  answer_from="$1"
  API_WAIT_SECONDS="$2"
  if wait_for_api; then result=0; else result=1; fi
}

echo "An API that is already up is not waited for"
run 1 30
check "returns success" "0" "$result"
check "and asks exactly once" "1" "$attempts"

echo
echo "An API that binds a moment after the restart is waited for"
run 3 5
check "returns success" "0" "$result"

echo
echo "An API that never comes up fails, rather than waiting forever"
start=$SECONDS
run 0 2
elapsed=$((SECONDS - start))
check "returns failure" "1" "$result"
check "gave up inside a sensible window" "true" \
  "$([[ "$elapsed" -ge 2 && "$elapsed" -le 6 ]] && echo true || echo false)"

echo
echo "The deadline is what fixes the race, not the retry"
# With no deadline at all the helper collapses to the single request the deploy script used
# to make — which is the bug this file exists for, reproduced deliberately. If this case ever
# starts passing, wait_for_api has stopped honouring API_WAIT_SECONDS and the cases above
# would go green whatever it did.
run 3 0
check "a zero-second deadline reproduces the original failure" "1" "$result"

echo
if [[ "$failures" -gt 0 ]]; then
  echo "$failures check(s) failed." >&2
  exit 1
fi
echo "All API wait checks passed."
