#!/usr/bin/env bash
#
# Deploy the current checkout to this host.
#
# Run ON the Pi, from /opt/nazarenow, after a `git pull`. #28 asks that deploying again be
# "a documented, repeatable operation rather than a sequence someone remembers" — this is
# that operation. First-time setup is deploy/README.md; this is every time after.
#
# It deliberately backs up before it changes anything. A deploy is the most likely moment
# for the store to be damaged, and it is the one thing here that cannot be rebuilt.

set -euo pipefail

# shellcheck source=deploy/bin/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

REPO="${REPO:-/opt/nazarenow}"
WEB_ROOT="${WEB_ROOT:-/var/www/nazarenow}"
ENV_FILE="${ENV_FILE:-/etc/nazarenow/nazarenow.env}"

# The public name, so the check at the end is not pinned to one spelling in code. The repo's
# own record has disagreed with itself about this — #28's body resolves it to
# `www.nazarenow.com` while the v3 milestone title says `.co.uk` — and a deployment that
# hardcodes the wrong one fails at TLS rather than at a setting.
SITE_URL="${SITE_URL:-https://www.nazarenow.com}"

cd "$REPO"

# --- Preflight ---------------------------------------------------------------------
#
# Run as your ordinary login user, not as `nazarenow`. That user is a system account with
# no sudo, so it cannot restart a service; you are in the `nazarenow` group, which is what
# lets you read the config below. Both halves fail confusingly if they are wrong, so they
# are checked here where the message can say what to do about it.

if [[ ! -r "$ENV_FILE" ]]; then
  echo "Cannot read $ENV_FILE." >&2
  echo "It is mode 640 root:nazarenow. Are you in the nazarenow group?" >&2
  echo "  sudo usermod -aG nazarenow \"\$USER\"   # then log out and back in" >&2
  exit 1
fi

if ! sudo -n true 2>/dev/null; then
  echo "This needs sudo for systemctl, nginx and the web root." >&2
  echo "Run it as your login user — not as 'nazarenow', which has no sudo." >&2
  exit 1
fi

echo "==> Deploying $(git rev-parse --short HEAD) — $(git log -1 --format=%s)"

# shellcheck disable=SC1090
set -a && source "$ENV_FILE" && set +a

echo
echo "==> Backing up the store first"
"$REPO/deploy/bin/backup-store.sh"

echo
echo "==> Backend dependencies"
# Not editable. An editable install leaves the running service pointing at the checkout,
# so a half-finished `git pull` becomes a half-deployed service.
"$REPO/venv/bin/pip" install --upgrade "$REPO/backend"

echo
echo "==> Building the frontend"
cd "$REPO/frontend"
npm ci
npm run build

# Both checks run here as well as in CI, because this is the artefact actually being
# served. An absolute URL in the bundle would reach a second origin the password does not
# cover, and it is cheaper to fail here than to discover it in a browser.
npm run check:same-origin
npm run check:payload

echo
echo "==> Publishing the built site to $WEB_ROOT"
sudo mkdir -p "$WEB_ROOT"
# --delete so a removed asset actually disappears; without it the web root accretes every
# bundle ever built and the hashed filenames make that invisible.
sudo rsync -a --delete "$REPO/frontend/dist/" "$WEB_ROOT/"
sudo chown -R www-data:www-data "$WEB_ROOT"

echo
echo "==> Restarting services"
cd "$REPO"
sudo systemctl daemon-reload
restart_services
sudo nginx -t && sudo systemctl reload nginx

echo
echo "==> Checking it came back"
systemctl --no-pager --lines=0 status \
  nazarenow-scheduler.service nazarenow-api.service nazarenow-backup.timer || true

# Straight at uvicorn, past nginx, so this proves the API is alive rather than that the
# password prompt is.
if curl -fsS --max-time 10 http://127.0.0.1:8000/api/conditions/current >/dev/null; then
  echo "API is serving."
else
  echo "API is NOT serving. journalctl -u nazarenow-api -n 50" >&2
  exit 1
fi

# And through nginx, to prove the wall is up. A 401 here is the pass condition: anything
# else means /api is reachable without the password, and that endpoint is the store.
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$SITE_URL/api/conditions/current" || true)"
if [[ "$code" == "401" ]]; then
  echo "Wall is up: unauthenticated /api returns 401 at $SITE_URL."
else
  echo "Unauthenticated /api at $SITE_URL returned $code, expected 401." >&2
  echo "That endpoint is the store. Do not leave it reachable." >&2
  exit 1
fi

echo
echo "Deployed."
