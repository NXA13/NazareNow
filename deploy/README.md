# Deploying NazaréNow

The host is a Raspberry Pi 5 running Raspberry Pi OS Lite from a 1TB SSD — the SSD is the
root filesystem, not a separate mount, so there is no SD card to keep writes off. It already
serves two other sites, each reached through its own Cloudflare Tunnel, with nginx bound to
port 80 only and nothing listening on 443. NazaréNow is added alongside them: its own tunnel,
its own nginx server block, its own systemd units, its own user, its own directory.

**The binding constraint is that those two sites are not disturbed.** nginx is the only
component genuinely shared with them. `sudo nginx -t` before every reload, `reload` and never
`restart`, and if `-t` fails, remove our symlink and nothing changes — the running nginx keeps
serving them from the config already in memory.

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
| nginx server block | Password, one origin | Serves the built page and proxies `/api` to uvicorn, on port 80. |
| `cloudflared-nazarenow.service` | The tunnel | The only route in. TLS terminates at Cloudflare's edge — [ADR 0019](../docs/adr/0019-reach-the-host-through-a-tunnel.md). |

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

`sqlite3` is the one worth calling out: both `backup-store.sh` and `restore-store.sh` depend
on it, and without it the first backup fails at 03:20 on a night nobody is watching.

**Install only what is actually missing, one package at a time, and never `apt upgrade`.** On
a host already serving other sites, `nodejs` and `npm` are the real hazard: if the neighbours
build against a node from nvm or NodeSource, the distro packages can shadow it and break them
silently. Check before installing anything:

```bash
for t in nginx sqlite3 rsync curl git node npm rclone htpasswd cloudflared; do
  printf '%-11s %s\n' "$t" "$(command -v $t || echo MISSING)"
done
python3 -m venv --help >/dev/null 2>&1 && echo "python3-venv: OK" || echo "python3-venv: MISSING"
```

The full set this deployment needs is `nginx sqlite3 rsync curl git python3-venv
apache2-utils nodejs npm rclone`, plus `cloudflared`. There is **no certbot**: ADR 0019 puts
TLS at Cloudflare's edge, so no certificate is ever issued on this machine.

### 1. Users and directories

Two identities, and the split matters — getting it wrong is the difference between a deploy
that runs and one that cannot read its own configuration.

- **`nazarenow`** is a system user with no login and no sudo. The three services run as it.
  It owns the store and nothing else.
- **You**, your ordinary login user, own the checkout and run the deploy. You need sudo for
  systemctl and nginx, which is exactly what a system user does not have.

So you are added to the `nazarenow` group, which is what lets you read the config the
services read and write the backup directory they write.

```bash
sudo adduser --system --group --home /opt/nazarenow nazarenow
sudo usermod -aG nazarenow "$USER"
# Group membership only applies to new sessions. Log out and back in, or `exec newgrp
# nazarenow`, before going further — otherwise step 7 fails on a file you can plainly see.

# /var/lib is the right home for state a service owns. On this host it is also already on
# the SSD, because the SSD *is* the root filesystem — confirm that with `lsblk` before
# trusting it on any other machine, since a Pipeline Run writes every three hours forever
# and an SD card's write endurance is finite.
sudo mkdir -p /var/lib/nazarenow/backups
sudo chown -R nazarenow:nazarenow /var/lib/nazarenow
# setgid, so anything created here keeps the group and both you and the services can write
# the backups directory.
sudo chmod -R 2775 /var/lib/nazarenow
```

If you ever move the store onto a *separate* disk, mount it by UUID in `/etc/fstab` — a
device name can move between reboots, and if the mount is missing at start-up the scheduler
will happily create a fresh empty database underneath the mount point. The real one then
reappears, apparently empty, the next time the disk mounts. On this host there is no separate
mount and the failure cannot occur.

### 2. The checkout and its virtualenv

Cloned as **you**, not as `nazarenow`. The services only ever read this directory; you are
the one who pulls, builds and installs into it, and a checkout owned by a user you cannot
become is a checkout you cannot deploy from.

```bash
sudo mkdir -p /opt/nazarenow
sudo chown "$USER":nazarenow /opt/nazarenow
git clone https://github.com/NXA13/NazareNow.git /opt/nazarenow
cd /opt/nazarenow
python3 -m venv venv
./venv/bin/pip install ./backend
```

Runtime dependencies are only FastAPI, uvicorn, httpx and pydantic — no numpy, scipy or
scikit-learn. All the fitting happens in `analysis/` on a development machine and ships as
JSON (`amplification.json`, `thresholds.json`, `forecast_error.json`, `track_record.json`),
which is what makes an ARM host with modest memory a perfectly reasonable place to run this.

Those four files are installed *into the package*, beside the modules that read them, so
confirm they arrived — an install that drops them imports perfectly and then dies on the first
Pipeline Run:

```bash
P=/opt/nazarenow/venv/lib/python3.13/site-packages/nazarenow
ls -l $P/*.json
```

Four files, or something is wrong with the build rather than with this host.
`test_runtime_data_files_are_packaged.py` is the guard that is supposed to make that
impossible, and it exists because this failure reached a host once.

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

If `NAZARENOW_DB` points anywhere other than `/var/lib/nazarenow`, edit the
`ReadWritePaths=` and `ReadOnlyPaths=` lines in the unit files to match — systemd will
otherwise deny the write and the failure reads as a permissions problem rather than a path
one.

The `*.service` glob above also copies `cloudflared-nazarenow.service` into place. It is not
enabled here; step 6 does that, once its config file exists.

### 5. The password

```bash
sudo apt install apache2-utils
sudo htpasswd -c /etc/nginx/nazarenow.htpasswd nick
sudo chown root:www-data /etc/nginx/nazarenow.htpasswd
sudo chmod 640 /etc/nginx/nazarenow.htpasswd
```

### 6. DNS, the tunnel, and nginx

**This is the step that differs most from what you would expect**, and
[ADR 0019](../docs/adr/0019-reach-the-host-through-a-tunnel.md) is the reason. There is no
certbot, no certificate and no port 443 anywhere on this host. Cloudflare terminates TLS at
its edge and `cloudflared` dials *outward* to reach it, so nothing inbound is ever opened.

#### 6a. Put the domain on Cloudflare

A tunnel hostname is a CNAME to `<tunnel-id>.cfargotunnel.com`, and only Cloudflare's own DNS
will issue one — so the zone has to live there. The domain stays registered at Fasthosts;
only the nameservers change.

1. **Create a new Cloudflare account for this site** (see 6b for why the separation is free
   at runtime and what it costs at the terminal), then add `nazarenow.com` to it and let the
   dashboard scan the existing records.
2. **Check the imported records before continuing, MX especially.** Anything the scan missed
   stops working the moment the nameservers change, and email is the usual casualty.
3. Change the nameservers at Fasthosts to the pair Cloudflare gives you.
4. Wait for the zone to read **Active**. Nothing below works until it does.

#### 6b. Create the tunnel

**NazaréNow gets its own Cloudflare account**, separate from the ones the neighbouring sites
use, matching how those are already kept apart from each other.

That separation is **invisible at runtime.** A tunnel authenticates with its credentials JSON,
which is self-contained, so `cloudflared tunnel run`, `nazarenow.yml` and the systemd unit
never know or care which account issued it. Three tunnels from three accounts coexist on this
host with no special handling.

It is *not* invisible to the management commands. `tunnel login`, `tunnel create` and
`tunnel route dns` authenticate with **`~/.cloudflared/cert.pem`, of which there is exactly
one**, and a login overwrites it with whichever account was just authorised. Overwriting it
does not disturb a running tunnel — nothing at runtime reads it. What it does mean is that the
account logged in last is the only one whose tunnels can be *managed* until someone logs in
again, which on a host with three accounts is a trap worth stepping around:

```bash
# Confirm the installed cloudflared supports pointing at a specific cert. This host runs an
# older build than current, and its update timer belongs to the other sites, not to us.
cloudflared tunnel --help | grep -i origincert
```

If it does, keep one cert per account and no login ever clobbers another. The environment
variable is used in preference to the flag only because it avoids any question of where the
flag sits relative to the subcommand:

```bash
export TUNNEL_ORIGIN_CERT=~/.cloudflared/cert-nazarenow.pem

# Authorises this machine for the new account's zone. Prints a URL to open in a browser —
# the Pi does not need one. Select nazarenow.com.
cloudflared tunnel login

# Prints the tunnel id and writes ~/.cloudflared/<tunnel-id>.json. That file is the secret.
cloudflared tunnel create nazarenow

# Match how the existing tunnels are stored: root-owned, unreadable by anyone else.
sudo install -m 400 -o root -g root ~/.cloudflared/<tunnel-id>.json /etc/cloudflared/

# The CNAMEs. This is what makes the names resolve to the tunnel. Same shell, so still
# under TUNNEL_ORIGIN_CERT above — in a new shell, export it again or these authenticate as
# whichever account owns the default cert.pem and fail to find the zone.
cloudflared tunnel route dns nazarenow nazarenow.com
cloudflared tunnel route dns nazarenow www.nazarenow.com
```

If `--origincert` turns out not to be supported, the fallback is simply to run the three
commands above without it and accept that `cert.pem` now belongs to the NazaréNow account.
Nothing breaks: the other two tunnels keep running untouched, and managing them again is
another `cloudflared tunnel login`.

Then the config, with both `<tunnel-id>` placeholders replaced:

```bash
sudo cp /opt/nazarenow/deploy/cloudflared/nazarenow.yml.example /etc/cloudflared/nazarenow.yml
sudo nano /etc/cloudflared/nazarenow.yml
```

#### 6c. nginx, before the tunnel comes up

nginx should already be answering on the two hostnames when the tunnel starts, or the first
requests through it get a 502.

```bash
# Where the built site is served from. No /var/www/certbot — there is no ACME challenge.
sudo mkdir -p /var/www/nazarenow
sudo chown -R www-data:www-data /var/www/nazarenow

# The headers snippet, included by the server block and by every location that sets a
# header of its own — see the comment at the top of the file for why that repetition is
# the fix rather than the problem.
sudo mkdir -p /etc/nginx/snippets
sudo cp /opt/nazarenow/deploy/nginx/nazarenow-headers.conf /etc/nginx/snippets/

sudo cp /opt/nazarenow/deploy/nginx/nazarenow.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/nazarenow.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

**`nginx -t` tests the whole config, not just this file.** A pre-existing error in a
neighbouring site fails *your* test. Do not fix it on impulse — it means something on this
host was already broken and reloading would have exposed it either way. If `-t` fails for any
reason, `sudo rm /etc/nginx/sites-enabled/nazarenow.conf` puts the host back exactly as it
was, because the running nginx is still serving from the config in memory.

#### 6d. Start the tunnel

```bash
sudo systemctl enable --now cloudflared-nazarenow.service
systemctl status cloudflared-nazarenow --no-pager
```

Two registered connections in the log means it is up. Renewal needs no timer and no dry run:
the certificate is Cloudflare's, at the edge, and there is nothing on this host that could
quietly stop renewing it. That is ADR 0007's "renews without intervention" criterion met by
removing the component that could fail, rather than by trusting one.

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
- [ ] **The two neighbouring sites still load.** They share nginx with this one and nothing
      else; this is the check that the shared component survived the change.

## Deploying again

```bash
cd /opt/nazarenow && sudo -u nazarenow git pull && ./deploy/bin/deploy.sh
```

`deploy.sh` backs the store up first, installs the backend, rebuilds the frontend, runs the
payload and same-origin checks against the actual artefact, publishes it, restarts the
services in the right order, and then verifies both that the API is serving and that an
unauthenticated `/api` request is refused. It exits non-zero if either is wrong.

That first verification waits rather than asking once. `systemctl restart` returns when
systemd has forked the process, not when uvicorn has bound its socket — about a second apart
on this host, which was enough for a deploy where everything worked to report the API as
down. It polls until `API_WAIT_SECONDS` (30 by default) has passed, so an API that is
genuinely failing to start still fails the deploy, just later.
`deploy/bin/test-api-wait.sh` covers both halves of that, with no server and no port.

## Backups, and the restore rehearsal

The timer snapshots daily with SQLite's online backup API — not `cp`, which on a live
database yields an archive that looks fine and restores to a corrupt one. Each snapshot is
integrity-checked before it counts, then gzipped, then copied off the host if
`NAZARENOW_BACKUP_REMOTE` is set.

### How big this gets

Measured, not guessed. A Pipeline Run appends about **180 kB** and there are eight a day, so
the store grows by roughly **half a gigabyte a year**. It compresses about ten to one, so
today's 1.2 MB store snapshots to 120 kB; a year from now expect tens of megabytes per
snapshot.

Retention is grandfather-father-son — 7 daily, 4 weekly, 12 monthly — which turns a year of
daily backups into **about twenty snapshots** reaching back twelve months, rather than thirty
near-identical copies of the last month. `deploy/bin/test-retention.sh` checks that policy
against fabricated snapshots, which is the only way to exercise it without waiting a year.

Note what that does and does not fix. It bounds what is *stored*, not what is *uploaded*:
each snapshot is an independent gzip of the whole store, so a full copy goes off the host
every night regardless. If that ever becomes the problem, the answer is a deduplicating
backup tool — restic or borg, which upload only changed blocks — and not a smaller retention
number.

### Set the remote

Without it, snapshots sit on the same SSD as the database they protect, which defends against
corruption but not against losing the machine — and losing the machine is the scenario ADR
0007 is written about. The script warns on every run until this is set.

**Cloudflare R2 or Backblaze B2** both fit inside a free tier at this scale (10 GB free
each, and ingress is free on both), and rclone speaks to either. Encryption is not worth the
key-management risk here: the store is derived public weather data, and losing a key is a
bigger threat to it than anyone reading it.

A second machine on your own LAN is fine as an *extra* sink and no good as the only one — it
burns in the same fire and gets stolen in the same burglary.

```bash
rclone config                      # once, interactively
sudo nano /etc/nazarenow/nazarenow.env   # set NAZARENOW_BACKUP_REMOTE
sudo systemctl start nazarenow-backup.service   # prove it works now, not at 03:20
journalctl -u nazarenow-backup -n 20
```

The remote is pruned on the same policy as the local directory, so it does not grow without
limit. A prune that fails on the network is reported and never fails the run — by that point
the new snapshot is already uploaded, which is the part that matters.

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

**Check whether the journal is persistent before assuming either way.** Pi OS Lite ships
`Storage=auto`, which keeps the journal in memory and empties it on every reboot *unless*
`/var/log/journal` exists. #28 asks that "logs from the scheduler are readable after the
fact, so a wrong prediction can be traced to the run that made it" — on the default
configuration, after a reboot, they are not.

```bash
ls -ld /var/log/journal && journalctl --disk-usage
```

If that directory exists and the usage is non-zero, the journal is already persistent and
**there is nothing to do here.** That is the case on the current host.

If it does not exist:

```bash
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald

# Prove it survives, rather than assuming — reboot, then look for entries from before it.
journalctl --list-boots
```

**Deliberately no `SystemMaxUse=` here.** An earlier version of this file wrote a 200M cap
into `/etc/systemd/journald.conf.d/`. That setting is global: on a host shared with other
sites it would shorten *their* retention too, to suit this one, which is a change to shared
state that nothing here justifies. At one Pipeline Run every three hours the journal grows
slowly enough to be a non-issue against a 1TB disk. Revisit it only if
`journalctl --disk-usage` says otherwise.

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

When the range is calibrated and the site should be public: delete the `auth_basic` and
`auth_basic_user_file` lines from the **server block** and from `location /api/` in
`/etc/nginx/sites-available/nazarenow.conf` — four lines in two places, not in `location /`,
which has none of its own — then `sudo nginx -t && sudo systemctl reload nginx`. Consider the `X-Robots-Tag` header in the same change, which is there because
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
