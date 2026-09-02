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

`tg-alert-health.timer` runs `run.py --health --notify` every 6 hours. It
posts to `SLACK_OPS_WEBHOOK_URL` (or the alert webhook if that is unset) only
when something is broken, and stays quiet for `NOTIFY_COOLDOWN_HOURS` after
it has complained once, so a long outage is one message rather than four a day.

It catches the failures that are otherwise silent: a revoked Telegram session,
a deleted Slack webhook, an image URL that stopped resolving, and a feed that
has gone quiet for more than `STALE_HOURS`.

```bash
sudo tg-alert --health                 # run it by hand, prints a line per check
sudo systemctl list-timers tg-alert-health.timer
sudo journalctl -u tg-alert-health -n 20
```

The unit files live in `systemd/` in this repo but are installed by hand, on
purpose: the deploy script does not touch systemd units, so push access to
this repo cannot turn into root on the box.

```bash
scp systemd/*.service systemd/*.timer deploy@tg-alert.phantomstay.com:/tmp/
ssh deploy@tg-alert.phantomstay.com \
  'sudo install -m 644 -o root -g root /tmp/tg-alert-health.* /etc/systemd/system/ &&
   sudo systemctl daemon-reload && sudo systemctl restart tg-alert-health.timer'
```

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
