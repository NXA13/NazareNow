# Reach the host through a Cloudflare Tunnel, and terminate TLS at the edge

ADR 0007 chose a single small always-on host running three things: the scheduler, the API,
and "a reverse proxy serving the built frontend and terminating TLS". The first two are
unchanged. The third is not: on the host this actually deploys to, the reverse proxy does
not terminate TLS and cannot, so **NazaréNow is reached through a Cloudflare Tunnel and TLS
terminates at Cloudflare's edge.**

## What the host turned out to be

ADR 0007 was written before anyone had looked at the machine. The plan it implies — Let's
Encrypt, `certonly --webroot`, an nginx block listening on 443 — assumes the host is
reachable from the internet on ports 80 and 443. The Raspberry Pi it deploys to is not, and
never has been:

- nginx is bound to `:80` only. Nothing listens on `:443`.
- `/etc/letsencrypt` does not exist. No certificate has ever been issued on this machine.
- Two `cloudflared` processes are running, each with its own tunnel, its own config file
  and its own systemd unit. Both of the sites already on this Pi reach the internet through
  them.

The router forwards nothing. The only route in is a connection the host dials *outward*.

So the choice was not "tunnel or certbot" in the abstract. It was whether to change how
this machine is reachable — opening inbound ports on a home network to suit a config file —
or to write the config file to match the machine.

## The decision

NazaréNow gets its own tunnel, following the pattern the host already uses: one tunnel, one
`/etc/cloudflared/nazarenow.yml`, one `cloudflared-nazarenow.service`. Its ingress sends
`nazarenow.com` and `www.nazarenow.com` to `http://localhost:80`, where an nginx server
block matching those names serves the built frontend and proxies `/api/` to uvicorn exactly
as before.

Everything ADR 0007 asked for survives: one origin for the page and the API, the API behind
the same wall as the page, and TLS that renews without intervention. Only the mechanism of
the last one changes.

## Consequences

**nginx never sees a TLS connection, so `$scheme` is always `http`.** The proxy to uvicorn
therefore sets `X-Forwarded-Proto https` as a *constant* rather than passing `$scheme`
through. That header is now an assertion about a leg of the request nginx did not witness,
and it is only true because the tunnel is the sole route in. If the site were ever also
served some other way, the header would start lying before anything else broke.

**There is no certbot, no `:443` listener, no ACME location, and no bootstrap config.** The
chicken-and-egg that `nazarenow-bootstrap.conf` existed to break — nginx refusing to start
a TLS listener whose certificate does not exist yet — is gone with the listener, and the
file is deleted rather than kept for a path nobody will take.

**Renewal stops being ours.** ADR 0007's criterion was TLS that renews *without
intervention*; the failure mode it guards against is a certbot timer that quietly stops
working and is discovered months later by a browser warning. Moving that to Cloudflare's
edge does not weaken the criterion, it removes the component that could fail unattended.

**Cloudflare sees the plaintext, including the Basic Auth credentials.** This is the real
cost and it is accepted deliberately. The wall in ADR 0007 exists to stop a casual reader
acting on uncalibrated advice whose consequence is "fly to Portugal" — it is not a defence
against the CDN in the request path, and it was never load-bearing in that way. The same is
already true of both other sites on this Pi.

**DNS for `nazarenow.com` must live on Cloudflare.** A tunnel hostname is a CNAME to
`<tunnel-id>.cfargotunnel.com`, and only Cloudflare's own DNS will issue one. This is lock-in
to a set of nameservers, not to a registrar: the domain stays at Fasthosts and can be pointed
elsewhere by changing them back, at the cost of then needing the rejected option below.

**A third party is now in the availability path.** Accepted for the same reason ADR 0007
accepts a single host: the record accumulates because the *scheduler* runs, and whether
anyone can load the page is unrelated to whether the store is filling.

## Considered options

**Forward ports 80 and 443 at the router and use Let's Encrypt**, which is what ADR 0007
implied and what `deploy/README.md` originally described. Rejected for a specific reason
rather than a general preference: it would put inbound public traffic onto an nginx where
**no enabled server block is marked `default_server`**. Unmatched requests land in whichever
vhost loads first, so the neighbouring site would become reachable over plain HTTP from
outside Cloudflare — a change to a site this deployment was explicitly constrained not to
disturb. It also publishes a home IP address that is currently not published.

**Add the two hostnames to one of the existing tunnels' ingress lists.** Cheaper by two
files, and rejected because applying it means editing a config that is serving a live site
and restarting its `cloudflared`, which drops that site while it reconnects. A third tunnel
touches nothing that is already running.
