# tg-slack-alerts

Mirrors flight alerts from a private Telegram channel into Slack.

A Telegram *bot* cannot read a channel unless the channel owner adds it as an admin.
This channel is invite-only and the owner won't do that, so the only way in is a
logged-in **user** session (MTProto, via Telethon). That session token can read
everything on the account it belongs to, so it belongs in a secret store, never in Slack.

## Setup

1. Get `api_id` / `api_hash` from https://my.telegram.org → API development tools.
2. `.venv/bin/python login.py` → enter them, then the code Telegram sends, then your
   2FA password if you have one. Copy the session string and the channel id it prints.
3. `cp .env.example .env` and fill it in.
4. Create a Slack incoming webhook for the destination channel, put it in `.env`.

## Run

    .venv/bin/python run.py --backfill 20          # dry run, prints only
    .venv/bin/python run.py --backfill 20 --send   # sends to Slack
    .venv/bin/python run.py                        # live

## Files

| File | Does |
|---|---|
| `login.py` | one-time login, prints session string + channel ids |
| `alerts.py` | parses an alert into fields, renders the Slack card |
| `run.py` | connects, filters, de-dupes, posts |
| `state.db` | sqlite, remembers which message ids were already posted |

## Notes

- Never send a Telegram login code through Telegram. Telegram detects codes shared in
  chats and invalidates them.
- Host the live process in the same region as the account's phone number. A user session
  connecting from a datacenter in another country is what Telegram's anti-fraud looks for.
- Access can be revoked any time from Telegram → Settings → Devices.
