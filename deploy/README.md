# Deploying NazaréNow

The host is a Raspberry Pi 5 with a 1TB SSD, running Raspberry Pi OS Lite, already serving
another site on ports 80 and 443. NazaréNow is added alongside it: its own nginx server
block, its own systemd units, its own user, its own directory on the SSD.

Read [ADR 0007](../docs/adr/0007-single-host-deployment-with-the-store-as-the-asset.md)
first. It explains why this shape and not another, and — more importantly — what the
deployment is actually for. It is not for showing people the site. **It is for the store,**
which begins accumulating a record of what this system predicted, at what Lead Time, on
days it turned out to be wrong about. That record cannot be backfilled, and the Gold Days
in `analysis/gold_days/` can only ever measure recall, so it is the only unbiased evidence
any precision figure will ever have.

Everything else here is in service of that file staying alive.

## What runs

| Piece | What it is | Why |
|---|---|---|
| `nazarenow-scheduler.service` | `python -m nazarenow schedule` | A Pipeline Run every three hours, forever. The unit that matters. |
| `nazarenow-api.service` | uvicorn on `127.0.0.1:8000` | Read-only API. Never exposed directly. |
| `nazarenow-backup.timer` | Daily at 03:20 | Snapshots the store and copies it off the host. |
| nginx server block | TLS, password, one origin | Serves the built page and proxies `/api` to uvicorn. |

Three facts that explain most of the configuration:

- **The scheduler creates and migrates the store; the API only reads it.** `api.py` opens
  the store with `create=False` on purpose — creating one there would turn a misconfigured
  path into an empty database and answer "no conditions yet", a config fault dressed as a
  data gap. So on a fresh host the API fails until the scheduler has run once. `Restart=`
  makes that resolve itself within a minute rather than needing anyone to intervene.
- **The page and the API are one origin.** `frontend/src/api.ts` calls relative paths, and
  both `src/api.test.ts` and `scripts/check-same-origin.mjs` fail if that stops being true.
  There is no CORS in the deployed configuration.
- **Both the page and `/api` are behind the same password.** A private page in front of a
  public `/api/conditions/forecast` is not private — that endpoint *is* the store.

## First-time setup

### 0. Packages

Pi OS Lite has none of these. `sqlite3` is the one worth calling out: both `backup-store.sh`
and `restore-store.sh` depend on it, and without it the first backup fails at 03:20 on a
night nobody is watching.

```bash
sudo apt update
sudo apt install -y nginx sqlite3 rsync curl git python3-venv apache2-utils certbot \
  python3-certbot-nginx nodejs npm rclone
```

### 1. User, directories, SSD

```bash
sudo adduser --system --group --home /opt/nazarenow nazarenow

# The store lives on the SSD, never the SD card. A Pipeline Run writes every three hours
# forever, and an SD card's write endurance is finite.
sudo mkdir -p /mnt/ssd/nazarenow/backups
sudo chown -R nazarenow:nazarenow /mnt/ssd/nazarenow
```

Confirm the SSD is actually mounted at boot (`/etc/fstab`, by UUID — a device name can move
between reboots). If the mount is missing at start-up the scheduler will happily create a
fresh empty database on the SD card underneath the mount point, and the real one will
reappear, apparently empty, the next time the SSD mounts.

### 2. The checkout and its virtualenv

```bash
sudo -u nazarenow git clone https://github.com/NXA13/NazareNow.git /opt/nazarenow
cd /opt/nazarenow
sudo -u nazarenow python3 -m venv venv
sudo -u nazarenow ./venv/bin/pip install ./backend
```

Runtime dependencies are only FastAPI, uvicorn, httpx and pydantic — no numpy, scipy or
scikit-learn. All the fitting happens in `analysis/` on a development machine and ships as
JSON (`amplification.json`, `thresholds.json`, `forecast_error.json`, `track_record.json`),
which is what makes an ARM host with modest memory a perfectly reasonable place to run this.

Node is needed only to build the frontend. Building on the Pi is fine; building elsewhere
and copying `dist/` across is also fine.

### 3. Configuration

```bash
sudo install -d -m 750 -o nazarenow -g nazarenow /etc/nazarenow
sudo install -m 640 -o root -g nazarenow \
  /opt/nazarenow/deploy/nazarenow.env.example /etc/nazarenow/nazarenow.env
sudo nano /etc/nazarenow/nazarenow.env
```

Every unit reads this one file, so the API, the scheduler and the backup cannot disagree
about where the store is. **`NAZARENOW_DB` must be set** — `store.py` anchors its default
to the repository, which is right for a source checkout and wrong for an installed package.

This file never enters the repository.

### 4. Services

```bash
sudo cp /opt/nazarenow/deploy/systemd/*.service /opt/nazarenow/deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nazarenow-scheduler.service
sudo systemctl enable --now nazarenow-backup.timer

# Wait for the scheduler's first run to create the store, then start the API.
sleep 30
sudo systemctl enable --now nazarenow-api.service
```

If the SSD is mounted somewhere other than `/mnt/ssd`, edit the `ReadWritePaths=` and
`ReadOnlyPaths=` lines in the unit files to match — systemd will otherwise deny the write
and the failure reads as a permissions problem rather than a path one.

### 5. The password

```bash
sudo apt install apache2-utils
sudo htpasswd -c /etc/nginx/nazarenow.htpasswd nick
sudo chown root:www-data /etc/nginx/nazarenow.htpasswd
sudo chmod 640 /etc/nginx/nazarenow.htpasswd
```

### 6. nginx and TLS

```bash
sudo cp /opt/nazarenow/deploy/nginx/nazarenow.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/nazarenow.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d www.nazarenow.com -d nazarenow.com
```

Point both `nazarenow.com` and `www.nazarenow.com` at the Pi's public address before
running certbot — it proves control of the name over port 80, so DNS has to be live first.
On a home connection that means the router forwards 80 and 443 to the Pi, and a dynamic
address needs a DDNS updater or the certificate renewal will fail one night months from now.

certbot installs its own renewal timer. Confirm it, rather than assuming:

```bash
sudo certbot renew --dry-run
systemctl list-timers | grep certbot
```

### 7. Build and publish the site

```bash
cd /opt/nazarenow && ./deploy/bin/deploy.sh
```

### 8. Check it by hand

The last acceptance criterion in #28 is a human one, because these are claims the page
makes about its own honesty and no test can confirm they survived the journey:

- [ ] `https://www.nazarenow.com` prompts for the password
- [ ] `https://nazarenow.com` redirects to the `www` form
- [ ] `curl -s -o /dev/null -w '%{http_code}' https://www.nazarenow.com/api/conditions/forecast` returns **401**
- [ ] The staleness banner appears when it should — stop the scheduler for seven hours, or
      check after a deliberate outage. `STALE_AFTER_SECONDS` is two cycles, so six hours.
- [ ] The modelled-not-measured statement renders on the forecast
- [ ] The measured-range-runs-wide statement renders in the track record's limitations
- [ ] The page is usable on a phone — story 26 of #1, which is intrinsically responsive and
      has no automated check because jsdom cannot do layout

## Deploying again

```bash
cd /opt/nazarenow && sudo -u nazarenow git pull && ./deploy/bin/deploy.sh
```

`deploy.sh` backs the store up first, installs the backend, rebuilds the frontend, runs the
payload and same-origin checks against the actual artefact, publishes it, restarts the
services in the right order, and then verifies both that the API is serving and that an
unauthenticated `/api` request is refused. It exits non-zero if either is wrong.

## Backups, and the restore rehearsal

The timer snapshots daily with SQLite's online backup API — not `cp`, which on a live
database yields an archive that looks fine and restores to a corrupt one. Each snapshot is
integrity-checked before it counts, then gzipped, then copied off the host if
`NAZARENOW_BACKUP_REMOTE` is set.

**Set that remote.** Without it, snapshots sit on the same SSD as the database they protect,
which defends against corruption but not against losing the machine — and losing the machine
is the scenario ADR 0007 is written about.

```bash
rclone config                      # once, interactively
sudo nano /etc/nazarenow/nazarenow.env   # set NAZARENOW_BACKUP_REMOTE
sudo systemctl start nazarenow-backup.service   # prove it works now, not at 03:20
journalctl -u nazarenow-backup -n 20
```

### The rehearsal

#28 requires a restore to have actually been performed and documented, because an untested
backup is a belief rather than a backup. Do this once, to a scratch path, where it is
harmless:

```bash
cd /opt/nazarenow
set -a && source /etc/nazarenow/nazarenow.env && set +a

ls -1t "$NAZARENOW_BACKUP_DIR"/nazarenow-*.db.gz | head -1
./deploy/bin/restore-store.sh "$(ls -1t "$NAZARENOW_BACKUP_DIR"/nazarenow-*.db.gz | head -1)" /tmp/rehearsal.db

sqlite3 /tmp/rehearsal.db 'SELECT COUNT(*) FROM pipeline_run;'
sqlite3 /tmp/rehearsal.db 'SELECT MAX(started_at) FROM pipeline_run;'
rm /tmp/rehearsal.db
```

Record the date you did it and the run count you saw, in a comment on #28. That is what
turns the criterion from a belief into a fact.

A real restore is the same script with no destination — it asks for confirmation, stops
both services, moves the existing file aside rather than deleting it, and brings the
scheduler up before the API.

## Rebuilding the host from nothing

Assume the SD card has failed and the Pi is being set up again from a blank image. In
order: steps 1 through 7 above, then restore the most recent snapshot **before** the
scheduler's first run has time to matter:

```bash
# Fetch the newest snapshot from the offsite remote
rclone copy "$NAZARENOW_BACKUP_REMOTE" /tmp/restore --include 'nazarenow-*.db.gz' --max-age 48h

sudo systemctl stop nazarenow-scheduler nazarenow-api
sudo -u nazarenow /opt/nazarenow/deploy/bin/restore-store.sh /tmp/restore/nazarenow-<stamp>.db.gz
```

What is lost is the window between the last snapshot and the failure — at most a day, at
most eight Pipeline Runs. What is not lost is the record, which is the point.

Things that are *not* in the repository and have to exist again: `/etc/nazarenow/nazarenow.env`,
the htpasswd file, the rclone config, the Let's Encrypt account, and the router's port
forwarding. None are secret enough to be interesting and all are quick — but all are
invisible until something needs them.

## Logs

```bash
journalctl -u nazarenow-scheduler -f          # runs as they happen
journalctl -u nazarenow-scheduler --since '7 days ago' | grep -i fail
journalctl -u nazarenow-backup --since '30 days ago'
sudo tail -f /var/log/nginx/nazarenow.access.log
```

A failed Pipeline Run is recorded in the store as well as the journal — `pipeline_run` keeps
the attempt, its `failure_kind` and its `failure_detail`, because a gap in the record with
no explanation beside it cannot be told apart from a host nobody switched on.

## Taking the wall down

When the range is calibrated and the site should be public: delete the two `auth_basic`
lines from the `/` block and the two from the `/api/` block in
`/etc/nginx/sites-available/nazarenow.conf`, then `sudo nginx -t && sudo systemctl reload
nginx`. Consider the `X-Robots-Tag` header in the same change, which is there because
nothing unauthenticated can currently reach the site to crawl it.

Open-Meteo's free tier is non-commercial. A freely accessible site is within it; advertising,
subscriptions or referral revenue would not be, and that is a decision to make deliberately
rather than discover.

## Known rough edge

If the scheduler is killed mid-transaction, SQLite leaves a hot journal that only a
*writable* connection can recover. The API opens read-only, so it will report the store as
unavailable until the scheduler restarts and recovers it — which it does automatically
within a minute. The page shows an honest error in the meantime rather than stale data
presented as fresh, which is the behaviour #7 established and the right trade.
