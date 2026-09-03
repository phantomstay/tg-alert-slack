# Deployment

Runs on the DigitalOcean droplet at `159.89.92.61` (`tg-alert.phantomstay.com`),
Ubuntu 24.04.

## Layout

| Path | Owner | What |
|---|---|---|
| `/opt/tg-alert` | `deploy` | code + virtualenv, no secrets |
| `/etc/tg-alert/env` | `root` 600 | Telegram session, Slack webhook |
| `/var/lib/tg-alert/state.db` | `tgalert` 600 | dedupe, which alerts were already posted |
| `/var/www/tg-alert/assets` | `root` | images Slack fetches over https |
| `/etc/systemd/system/tg-alert.service` | `root` | the service |
| `/etc/caddy/Caddyfile` | `root` | serves `/assets/*` only, everything else 404s |

The app runs as `tgalert`, a system account with no shell and no sudo. systemd
sandboxing means the only directory the process can write to is
`/var/lib/tg-alert`. It cannot read `/etc/tg-alert/env` itself; systemd reads it
as root and passes the values in as environment variables.

## Accounts

SSH is `deploy` only, key-based. Root login and password auth are both off,
enforced in `/etc/ssh/sshd_config.d/10-hardening.conf`.

## Day to day

```bash
ssh deploy@tg-alert.phantomstay.com

sudo systemctl status tg-alert
sudo journalctl -u tg-alert -f          # live
sudo journalctl -u tg-alert --since today
sudo systemctl restart tg-alert
```

Restarts are safe. On start the service re-reads the last `CATCHUP` (default 20)
posts, so anything published while it was down still gets delivered, and the
dedupe table stops it repeating what already went out.

## Monitoring

`tg-alert-health.timer` runs every 6 hours and checks the Telegram session,
channel access, how long since the last channel post, the Slack webhook, the
image host and the dedupe DB.

Failures go to **email**, never to the flight alert channel. Ops noise in a
deals channel just teaches people to scroll past it. Set in `/etc/tg-alert/env`:

    OPS_EMAIL_TO=sudipta.just@gmail.com
    RESEND_API_KEY=<key from resend.com>
    OPS_EMAIL_FROM=onboarding@resend.dev

**Do not try to use SMTP on this droplet.** DigitalOcean blocks outbound 25,
465 and 587 by default, so every SMTP provider times out. Verified:

    smtp.gmail.com:587        TimeoutError
    smtp.resend.com:587       TimeoutError
    smtp-relay.brevo.com:587  TimeoutError
    api.resend.com:443        OK

The failure surfaces as `[Errno 101] Network is unreachable`, which is
misleading. The droplet has no IPv6 route, Python tries IPv6 last, and that
error hides the real IPv4 timeout. Mail therefore goes over HTTPS via the
Resend API. The `SMTP_*` keys still work if this ever moves to a host that
permits SMTP.

`onboarding@resend.dev` sends without verifying a domain but only delivers to
the address that owns the Resend account. To send anywhere else, verify
phantomstay.com in Resend and set `OPS_EMAIL_FROM=alerts@phantomstay.com`.

`SLACK_OPS_WEBHOOK_URL` still works as an alternative if you would rather have a
separate ops channel. Email wins if both are set. With neither, failures are
only written to the journal.

Repeat notifications are suppressed for `NOTIFY_COOLDOWN_HOURS` (default 12), so
a week-long outage is one message rather than twenty-eight.

`STALE_HOURS` (default 48) is how long the channel can go quiet before that
counts as a failure. Production runs 96, because PJ Flight Alerts routinely goes
two days without posting.

Check by hand:

    sudo tg-alert --health

## Changing the Slack channel

Create a new Incoming Webhook pointed at the channel you want, then:

```bash
ssh deploy@tg-alert.phantomstay.com
sudo nano /etc/tg-alert/env      # edit SLACK_WEBHOOK_URL
sudo systemctl restart tg-alert
sudo tg-alert --test-post        # confirm it lands in the new channel
```

Alerts and health warnings can go to different channels: put the ops one in
`SLACK_OPS_WEBHOOK_URL`.

## Shipping a change

```bash
rsync -az --delete \
  --exclude '.venv/' --exclude '.env' --exclude '.env.*' --exclude 'state.db*' \
  --exclude '__pycache__/' --exclude '.git/' \
  ./ deploy@tg-alert.phantomstay.com:/opt/tg-alert/
ssh deploy@tg-alert.phantomstay.com sudo systemctl restart tg-alert
```

## Adding an aircraft photo

Put the file in `assets/`, then:

```bash
scp assets/challenger.png deploy@tg-alert.phantomstay.com:/tmp/
ssh deploy@tg-alert.phantomstay.com \
  'sudo install -m 644 -o root -g root /tmp/challenger.png /var/www/tg-alert/assets/'
```

Add the mapping to `aircraft_images.json` (key is a lowercase fragment matched
against the alert's Aircraft Type, longest match wins), rsync, restart.
Anything unmatched falls back to `ALERT_IMAGE_URL`.

## Fresh install on a new box

After the code and `/etc/tg-alert/env` are in place, adopt the channel's current
state before starting, or the first catch-up will post the backlog to Slack:

```bash
run.py --mark-seen 40
```
