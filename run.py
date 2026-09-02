"""
Watch a Telegram channel and mirror flight alerts into Slack.

  .venv/bin/python run.py --backfill 20   # parse the last 20 posts, print, don't send
  .venv/bin/python run.py --backfill 20 --send
  .venv/bin/python run.py                 # live, runs until you stop it
"""
import argparse
import os
import sqlite3
import sys

import requests
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

import alerts

load_dotenv()

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ["TG_SESSION"]
CHANNEL = int(os.environ["TG_CHANNEL_ID"])
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL")
MAX_PRICE = int(os.getenv("MAX_PRICE") or 0) or None
MIN_SEATS = int(os.getenv("MIN_SEATS") or 0) or None
# absolute under systemd, relative when run by hand from the repo
STATE_DB = os.getenv("STATE_DB", "state.db")
# on start, re-read the last N posts so a restart or crash does not lose alerts
CATCHUP = int(os.getenv("CATCHUP") or 20)

db = sqlite3.connect(STATE_DB)
db.execute("CREATE TABLE IF NOT EXISTS seen (chat_id INT, msg_id INT, PRIMARY KEY (chat_id, msg_id))")
db.commit()


def already_sent(msg_id):
    return db.execute(
        "SELECT 1 FROM seen WHERE chat_id=? AND msg_id=?", (CHANNEL, msg_id)
    ).fetchone() is not None


def mark_sent(msg_id):
    db.execute("INSERT OR IGNORE INTO seen VALUES (?, ?)", (CHANNEL, msg_id))
    db.commit()


def post_to_slack(payload):
    if not SLACK_WEBHOOK:
        print("  (no SLACK_WEBHOOK_URL set, not sending)")
        return False
    r = requests.post(SLACK_WEBHOOK, json=payload, timeout=10)
    if r.status_code != 200:
        print(f"  slack error {r.status_code}: {r.text}", file=sys.stderr)
        return False
    return True


def handle(msg_id, text, send):
    alert = alerts.parse(text)
    if not alert:
        return
    if not alerts.passes_filters(alert, MAX_PRICE, MIN_SEATS):
        print(f"[{msg_id}] filtered out: {alert['route']} ${alert['price']}")
        return
    if already_sent(msg_id):
        print(f"[{msg_id}] already sent, skipping")
        return

    payload = alerts.to_slack(alert)
    print(f"[{msg_id}] {payload['text']}")
    if send and post_to_slack(payload):
        mark_sent(msg_id)


def health(client):
    """Print a status line per dependency. Returns a process exit code."""
    ok = True

    # run.py uses the async client, so these have to go through the loop.
    async def probe():
        me = await client.get_me()
        entity = await client.get_entity(CHANNEL)
        last = None
        async for m in client.iter_messages(CHANNEL, limit=1):
            last = m
        return me, entity, last

    try:
        with client:
            me, entity, last = client.loop.run_until_complete(probe())
            print(f"  telegram session  OK    logged in as {me.first_name} (id {me.id})")
            print(f"  channel access    OK    {entity.title!r}, latest post id {last.id if last else 'none'}")
    except Exception as e:
        print(f"  telegram          FAIL  {type(e).__name__}: {e}")
        print("        the session was probably revoked. Re-run login.py and update /etc/tg-alert/env")
        return 1

    if not SLACK_WEBHOOK:
        print("  slack webhook     FAIL  SLACK_WEBHOOK_URL is not set")
        ok = False
    else:
        # An empty payload is rejected with invalid_payload, which still proves
        # the webhook exists. A dead webhook answers 404 no_service instead.
        r = requests.post(SLACK_WEBHOOK, json={}, timeout=10)
        if "no_service" in r.text or r.status_code == 404:
            print(f"  slack webhook     FAIL  {r.status_code} {r.text.strip()}, the webhook was deleted")
            ok = False
        else:
            print(f"  slack webhook     OK    reachable ({r.status_code} {r.text.strip()})")

    image = alerts.image_for({"aircraft": None})
    if not image:
        print("  alert image       none  no ALERT_IMAGE_URL set, cards will post without a photo")
    else:
        try:
            r = requests.head(image, timeout=10, allow_redirects=True)
            ctype = r.headers.get("content-type", "?")
            good = r.status_code == 200 and ctype.startswith("image/")
            print(f"  alert image       {'OK   ' if good else 'FAIL '} {r.status_code} {ctype} {image}")
            ok = ok and good
        except Exception as e:
            print(f"  alert image       FAIL  {type(e).__name__}: {e}")
            ok = False

    n = db.execute("SELECT COUNT(*) FROM seen WHERE chat_id=?", (CHANNEL,)).fetchone()[0]
    print(f"  dedupe db         OK    {STATE_DB}, {n} alerts recorded for this channel")

    print("\nall good" if ok else "\nsomething is broken, see FAIL above")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, metavar="N", help="parse the last N posts and exit")
    ap.add_argument("--send", action="store_true", help="actually post to Slack")
    ap.add_argument("--health", action="store_true",
                    help="check the telegram session, channel access and slack webhook, then exit")
    ap.add_argument("--test-post", action="store_true",
                    help="post one clearly-marked test card to slack to prove the chain works")
    ap.add_argument("--mark-seen", type=int, metavar="N",
                    help="mark the last N posts as already sent without posting them; "
                         "use once on a fresh install so startup catch-up stays quiet")
    args = ap.parse_args()

    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

    if args.health:
        sys.exit(health(client))

    if args.test_post:
        alert = alerts.parse(
            "Route: TEST ORIGIN (TST) to TEST DESTINATION (TST)\n"
            "Date: pipeline test\n"
            "Aircraft Type: Global 6000\n"
            "Available Seats: 1\n"
            "Discounted Rate: $1"
        )
        payload = alerts.to_slack(alert)
        payload["blocks"].insert(0, {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": ":wrench: *test post, not a real flight*"}],
        })
        print("posting test card to slack...")
        print("sent" if post_to_slack(payload) else "FAILED, see error above")
        return

    if args.mark_seen:
        n = 0
        with client:
            for m in client.iter_messages(CHANNEL, limit=args.mark_seen):
                if alerts.parse(m.message):
                    mark_sent(m.id)
                    n += 1
        print(f"marked {n} existing alerts as seen in {STATE_DB}")
        return

    if args.backfill:
        with client:
            for m in client.iter_messages(CHANNEL, limit=args.backfill):
                handle(m.id, m.message, args.send)
        return

    @client.on(events.NewMessage(chats=CHANNEL))
    async def _(event):
        handle(event.message.id, event.message.message, True)

    with client:
        # Anything posted while we were down. Dedupe makes this safe to repeat,
        # and it covers the race where a post lands mid-catchup.
        if CATCHUP:
            print(f"Catching up on the last {CATCHUP} posts...", flush=True)
            for m in reversed(list(client.iter_messages(CHANNEL, limit=CATCHUP))):
                handle(m.id, m.message, True)

        print(f"Listening to channel {CHANNEL}. Ctrl+C to stop.", flush=True)
        client.run_until_disconnected()


if __name__ == "__main__":
    main()
