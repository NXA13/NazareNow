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

REPO="${REPO:-/opt/nazarenow}"
WEB_ROOT="${WEB_ROOT:-/var/www/nazarenow}"
ENV_FILE="${ENV_FILE:-/etc/nazarenow/nazarenow.env}"

cd "$REPO"

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
# Scheduler first: it opens the store writable and applies any migration a new version
# brings. The API opens read-only and cannot.
sudo systemctl restart nazarenow-scheduler.service
sleep 5
sudo systemctl restart nazarenow-api.service
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
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://www.nazarenow.com/api/conditions/current || true)"
if [[ "$code" == "401" ]]; then
  echo "Wall is up: unauthenticated /api returns 401."
else
  echo "WARNING: unauthenticated /api returned $code, expected 401." >&2
  exit 1
fi

echo
echo "Deployed."
