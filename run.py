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

db = sqlite3.connect("state.db")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, metavar="N", help="parse the last N posts and exit")
    ap.add_argument("--send", action="store_true", help="actually post to Slack")
    args = ap.parse_args()

    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

    if args.backfill:
        with client:
            for m in client.iter_messages(CHANNEL, limit=args.backfill):
                handle(m.id, m.message, args.send)
        return

    @client.on(events.NewMessage(chats=CHANNEL))
    async def _(event):
        handle(event.message.id, event.message.message, True)

    print(f"Listening to channel {CHANNEL}. Ctrl+C to stop.")
    with client:
        client.run_until_disconnected()


if __name__ == "__main__":
    main()
