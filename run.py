"""
Watch a Telegram channel and mirror flight alerts into Slack.

  .venv/bin/python run.py --backfill 20   # parse the last 20 posts, print, don't send
  .venv/bin/python run.py --backfill 20 --send
  .venv/bin/python run.py                 # live, runs until you stop it
"""
import argparse
import os
import queue
import smtplib
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

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
# Where health failures go: email first if SMTP is set up, otherwise a separate
# ops webhook. Deliberately no fallback to SLACK_WEBHOOK. The alert channel is
# for flights, and ops noise in there just teaches people to scroll past it.
OPS_WEBHOOK = os.getenv("SLACK_OPS_WEBHOOK_URL")
OPS_EMAIL_TO = os.getenv("OPS_EMAIL_TO")
# DigitalOcean blocks outbound 25/465/587, so on that host mail has to go over
# HTTPS. Set RESEND_API_KEY and SMTP is not used at all.
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT") or 587)
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
OPS_EMAIL_FROM = os.getenv("OPS_EMAIL_FROM") or SMTP_USER
MAX_PRICE = int(os.getenv("MAX_PRICE") or 0) or None
MIN_SEATS = int(os.getenv("MIN_SEATS") or 0) or None
# absolute under systemd, relative when run by hand from the repo
STATE_DB = os.getenv("STATE_DB", "state.db")
# on start, re-read the last N posts so a restart or crash does not lose alerts.
# Only used the first time; after that we catch up from the last id we posted.
CATCHUP = int(os.getenv("CATCHUP") or 20)
# ceiling on that, so a long outage cannot dump thousands of cards at once
CATCHUP_MAX = int(os.getenv("CATCHUP_MAX") or 200)
# --health complains if the channel has posted nothing in this long
STALE_HOURS = float(os.getenv("STALE_HOURS") or 48)
# do not re-notify the ops channel more often than this while still broken
NOTIFY_COOLDOWN_HOURS = float(os.getenv("NOTIFY_COOLDOWN_HOURS") or 12)

db = sqlite3.connect(STATE_DB, check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS seen (chat_id INT, msg_id INT, PRIMARY KEY (chat_id, msg_id))")
db.commit()


def already_sent(msg_id):
    return db.execute(
        "SELECT 1 FROM seen WHERE chat_id=? AND msg_id=?", (CHANNEL, msg_id)
    ).fetchone() is not None


def mark_sent(msg_id):
    db.execute("INSERT OR IGNORE INTO seen VALUES (?, ?)", (CHANNEL, msg_id))
    db.commit()


_last_post = 0.0


def post_to_slack(payload, webhook=None):
    global _last_post
    webhook = webhook or SLACK_WEBHOOK
    if not webhook:
        print("  (no SLACK_WEBHOOK_URL set, not sending)")
        return False

    for attempt in range(3):
        # incoming webhooks allow roughly one message a second, and a backfill
        # sends twenty in a row
        wait = 1.2 - (time.monotonic() - _last_post)
        if wait > 0:
            time.sleep(wait)
        r = requests.post(webhook, json=payload, timeout=10)
        _last_post = time.monotonic()

        if r.status_code == 200:
            return True
        if r.status_code == 429 and attempt < 2:
            retry = float(r.headers.get("Retry-After") or 1)
            print(f"  rate limited, waiting {retry}s")
            time.sleep(retry)
            continue
        print(f"  slack error {r.status_code}: {r.text}", file=sys.stderr)
        return False
    return False


def handle(msg_id, text, send, force=False):
    alert = alerts.parse(text)
    if not alert:
        return
    if not alerts.passes_filters(alert, MAX_PRICE, MIN_SEATS):
        print(f"[{msg_id}] filtered out: {alert['route']} ${alert['price']}")
        return
    if already_sent(msg_id) and not force:
        print(f"[{msg_id}] already sent, skipping")
        return

    payload = alerts.to_slack(alert)
    print(f"[{msg_id}] {payload['text']}")
    if send and post_to_slack(payload):
        mark_sent(msg_id)


def send_ops_email(subject, body):
    """Mail the ops address. Returns True if it actually went out."""
    if not OPS_EMAIL_TO:
        return False

    if RESEND_API_KEY:
        try:
            r = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json={
                    "from": OPS_EMAIL_FROM or "onboarding@resend.dev",
                    "to": [OPS_EMAIL_TO],
                    "subject": subject,
                    "text": body,
                },
                timeout=15,
            )
            if r.status_code < 300:
                return True
            print(f"  resend error {r.status_code}: {r.text}")
        except Exception as e:
            print(f"  resend failed: {e}")
        return False

    if not (SMTP_HOST and SMTP_USER and SMTP_PASS):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = OPS_EMAIL_FROM
    msg["To"] = OPS_EMAIL_TO
    msg.set_content(body)
    try:
        # 465 is implicit TLS, 587 upgrades with STARTTLS
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
                smtp.login(SMTP_USER, SMTP_PASS)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
                smtp.starttls()
                smtp.login(SMTP_USER, SMTP_PASS)
                smtp.send_message(msg)
        return True
    except Exception as e:
        # a broken mailbox must not turn a warning into a crash
        print(f"  email failed: {e}")
        return False


def notify_ops(failures):
    """Send the failure list wherever ops alerts are configured to go."""
    plain = "\n".join(f"- {label}: {detail}" for label, detail in failures)
    if send_ops_email("Flight alert bridge is unhealthy", (
        "The Telegram to Slack flight alert bridge failed its health check.\n\n"
        f"{plain}\n\n"
        "To look into it:\n"
        "  ssh deploy@tg-alert.phantomstay.com\n"
        "  sudo tg-alert --health\n"
    )):
        print(f"emailed {OPS_EMAIL_TO}")
        return True

    if OPS_WEBHOOK:
        lines = "\n".join(f"\u2022 *{label}* {detail}" for label, detail in failures)
        if post_to_slack({
            "text": "Flight alert bridge is unhealthy",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn",
                 "text": f":rotating_light: *Flight alert bridge is unhealthy*\n{lines}"}},
                {"type": "context", "elements": [{"type": "mrkdwn",
                 "text": "`ssh deploy@tg-alert.phantomstay.com` then `sudo tg-alert --health`"}]},
            ],
        }, OPS_WEBHOOK):
            print("ops channel notified")
            return True

    # say which piece is actually missing, not just "something"
    if not OPS_EMAIL_TO:
        print("nowhere to send this: set OPS_EMAIL_TO or SLACK_OPS_WEBHOOK_URL")
    elif not (RESEND_API_KEY or (SMTP_HOST and SMTP_USER and SMTP_PASS)):
        print(f"OPS_EMAIL_TO is {OPS_EMAIL_TO} but there is no way to send mail: "
              "set RESEND_API_KEY, or SMTP_HOST/SMTP_USER/SMTP_PASS on a host "
              "that allows outbound SMTP")
    else:
        print("the mail attempt failed, see the error above")
    return False


def _notified_recently(path, cooldown_hours):
    """True if we already sent an ops alert inside the cooldown window."""
    try:
        age = time.time() - os.path.getmtime(path)
    except FileNotFoundError:
        return False
    return age < cooldown_hours * 3600


def health(client, notify=False):
    """Print a status line per dependency. Returns a process exit code."""
    checks = []   # (label, "OK" | "FAIL" | "WARN", detail)

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
        checks.append(("telegram session", "OK", f"logged in as {me.first_name} (id {me.id})"))
        checks.append(("channel access", "OK", f"{entity.title!r}, latest post id {last.id if last else 'none'}"))

        # The quiet failure this exists to catch: the session is alive and the
        # channel readable, but nothing has arrived in far too long.
        if last and last.date:
            hours = (datetime.now(timezone.utc) - last.date).total_seconds() / 3600
            stale = hours > STALE_HOURS
            checks.append((
                "feed activity",
                "FAIL" if stale else "OK",
                f"last post {hours:.1f}h ago"
                + (f", nothing for over {STALE_HOURS}h" if stale else ""),
            ))
    except Exception as e:
        checks.append(("telegram", "FAIL", f"{type(e).__name__}: {e}"))
        checks.append(("", "", "the session was probably revoked. Re-run login.py "
                               "and update /etc/tg-alert/env"))

    if not SLACK_WEBHOOK:
        checks.append(("slack webhook", "FAIL", "SLACK_WEBHOOK_URL is not set"))
    else:
        # An empty payload is rejected with invalid_payload, which still proves
        # the webhook exists. A dead webhook answers 404 no_service instead.
        try:
            r = requests.post(SLACK_WEBHOOK, json={}, timeout=10)
            dead = r.status_code == 404 or "no_service" in r.text
            checks.append(("slack webhook", "FAIL" if dead else "OK",
                           f"{r.status_code} {r.text.strip()}"
                           + (", the webhook was deleted" if dead else " (reachable)")))
        except Exception as e:
            checks.append(("slack webhook", "FAIL", f"{type(e).__name__}: {e}"))

    image = alerts.image_for({"aircraft": None})
    if not image:
        checks.append(("alert image", "WARN", "no ALERT_IMAGE_URL set, cards post without a photo"))
    else:
        try:
            r = requests.head(image, timeout=10, allow_redirects=True)
            ctype = r.headers.get("content-type", "?")
            good = r.status_code == 200 and ctype.startswith("image/")
            checks.append(("alert image", "OK" if good else "FAIL",
                           f"{r.status_code} {ctype} {image}"))
        except Exception as e:
            checks.append(("alert image", "FAIL", f"{type(e).__name__}: {e}"))

    n = db.execute("SELECT COUNT(*) FROM seen WHERE chat_id=?", (CHANNEL,)).fetchone()[0]
    checks.append(("dedupe db", "OK", f"{STATE_DB}, {n} alerts recorded for this channel"))

    for label, status, detail in checks:
        print(f"  {label:<17} {status:<5} {detail}" if label else f"        {detail}")

    failures = [(l, d) for l, st, d in checks if st == "FAIL"]
    print("\nall good" if not failures else "\nsomething is broken, see FAIL above")

    if failures and notify:
        stamp = os.path.join(os.path.dirname(os.path.abspath(STATE_DB)), "last-alert-notice")
        if _notified_recently(stamp, NOTIFY_COOLDOWN_HOURS):
            print(f"(ops already notified within {NOTIFY_COOLDOWN_HOURS}h, staying quiet)")
        else:
            if notify_ops(failures):
                open(stamp, "w").close()

    return 0 if not failures else 1


def replay(client, day, send):
    """Repost one day's alerts, each marked as a replay.

    For proving a change end to end from the server without waiting for the
    channel to post something. Every card carries a banner saying it is not
    bookable, because the flights are by definition in the past.
    """
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    rows = []
    with client:
        # iter_messages walks backwards from offset_date, so start at midnight
        # after the day we want and stop once we fall off the front of it
        for m in client.iter_messages(CHANNEL, offset_date=end):
            if not m.date or m.date.astimezone(timezone.utc) < start:
                break
            alert = alerts.parse(m.message)
            if alert:
                rows.append((m.id, alert))
    rows.reverse()   # oldest first, so the channel reads in real order

    print(f"{len(rows)} alerts on {day}" + ("" if send else ", dry run, add --send"))
    for msg_id, alert in rows:
        payload = alerts.to_slack(alert)
        payload["blocks"].insert(0, {"type": "context", "elements": [{"type": "mrkdwn",
            "text": f":wrench: *replay of {day}, not a bookable flight*"}]})
        image = alerts.image_for(alert) or "no photo"
        print(f"[{msg_id}] {(alert['aircraft'] or '?'):6} "
              f"{alert['route'][:48]:50} -> {image.rsplit('/', 1)[-1]}")
        if send:
            print("      sent" if post_to_slack(payload) else "      FAILED")
    return 0


def check_images(client=None, scan=0):
    """HEAD every image in aircraft_images.json and report what is missing.

    With --scan N it also reads the last N channel posts and lists aircraft
    types that have no entry at all, which is how a new type in the feed gets
    noticed before it quietly posts the fallback photo for weeks.
    """
    rc = 0
    print("images in aircraft_images.json:")
    for url, types in sorted(alerts.mapped_images().items(), key=lambda kv: kv[0]):
        label = ", ".join(sorted(types))
        try:
            r = requests.head(url, timeout=10, allow_redirects=True)
            ctype = r.headers.get("content-type", "?")
            ok = r.status_code == 200 and ctype.startswith("image/")
        except Exception as e:
            r, ctype, ok = None, f"{type(e).__name__}: {e}", False
        status = "OK   " if ok else "MISS "
        code = r.status_code if r is not None else "---"
        print(f"  {status} {code} {url}\n        used by: {label}")
        if not ok:
            rc = 1

    fallback = os.getenv("ALERT_IMAGE_URL")
    print(f"\nfallback ALERT_IMAGE_URL: {fallback or 'not set, unmatched types post with no photo'}")

    if scan and client:
        seen = {}
        with client:
            for m in client.iter_messages(CHANNEL, limit=scan):
                alert = alerts.parse(m.message)
                if alert and alert["aircraft"]:
                    seen[alert["aircraft"]] = seen.get(alert["aircraft"], 0) + 1
        unmapped = {
            t: n for t, n in seen.items()
            if alerts.image_for({"aircraft": t}) in (None, fallback)
        }
        print(f"\naircraft types in the last {scan} posts: {len(seen)}")
        for t, n in sorted(seen.items(), key=lambda kv: -kv[1]):
            mark = "  no image" if t in unmapped else ""
            print(f"  {n:4}  {t}{mark}")
        if unmapped:
            print(f"\n{len(unmapped)} type(s) have no photo and fall back")
            rc = 1
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, metavar="N", help="parse the last N posts and exit")
    ap.add_argument("--send", action="store_true", help="actually post to Slack")
    ap.add_argument("--force", action="store_true",
                    help="with --backfill --send, repost alerts already in the dedupe db")
    ap.add_argument("--health", action="store_true",
                    help="check the telegram session, channel access and slack webhook, then exit")
    ap.add_argument("--notify", action="store_true",
                    help="with --health, email or post the failures to ops; used by the timer")
    ap.add_argument("--test-notify", action="store_true",
                    help="send a fake health failure to the ops destination to prove it works")
    ap.add_argument("--test-post", action="store_true",
                    help="post one clearly-marked test card to slack to prove the chain works")
    ap.add_argument("--replay", metavar="YYYY-MM-DD",
                    help="repost one day's alerts, each marked as a replay; "
                         "prints only unless --send is given too")
    ap.add_argument("--check-images", action="store_true",
                    help="check every photo in aircraft_images.json is actually reachable")
    ap.add_argument("--scan", type=int, default=0, metavar="N",
                    help="with --check-images, also list aircraft types in the last N posts "
                         "that have no photo mapped")
    ap.add_argument("--mark-seen", type=int, metavar="N",
                    help="mark the last N posts as already sent without posting them; "
                         "use once on a fresh install so startup catch-up stays quiet")
    args = ap.parse_args()

    if args.test_notify:
        # ignores the cooldown on purpose, this is for proving delivery
        ok = notify_ops([("test", "this is a test, nothing is actually wrong")])
        sys.exit(0 if ok else 1)

    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

    if args.replay:
        try:
            day = datetime.strptime(args.replay, "%Y-%m-%d").date()
        except ValueError:
            sys.exit(f"--replay wants YYYY-MM-DD, got {args.replay!r}")
        sys.exit(replay(client, day, args.send))

    if args.check_images:
        sys.exit(check_images(client, args.scan))

    if args.health:
        sys.exit(health(client, notify=args.notify))

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
            # oldest first, so the channel reads top to bottom in real order
            for m in reversed(list(client.iter_messages(CHANNEL, limit=args.backfill))):
                handle(m.id, m.message, args.send, force=args.force)
        return

    # Posting to Slack is blocking and paced at about one a second. Doing that
    # inline would stall Telethon's event loop for the length of a bulk drop and
    # cost us the connection, so the handler only enqueues.
    work = queue.Queue()

    def worker():
        while True:
            msg_id, text = work.get()
            try:
                handle(msg_id, text, True)
            except Exception as e:
                print(f"[{msg_id}] failed to post: {e}", file=sys.stderr)
            finally:
                work.task_done()

    threading.Thread(target=worker, daemon=True).start()

    @client.on(events.NewMessage(chats=CHANNEL))
    async def _(event):
        work.put((event.message.id, event.message.message))

    with client:
        # Anything posted while we were down. Dedupe makes this safe to repeat,
        # and it covers the race where a post lands mid-catchup.
        last_seen = db.execute(
            "SELECT MAX(msg_id) FROM seen WHERE chat_id=?", (CHANNEL,)
        ).fetchone()[0]
        if last_seen:
            # everything since the last alert we actually sent, not a fixed
            # window, so a burst bigger than CATCHUP cannot fall through the gap
            missed = list(client.iter_messages(CHANNEL, min_id=last_seen, limit=CATCHUP_MAX))
        else:
            missed = list(client.iter_messages(CHANNEL, limit=CATCHUP))
        if missed:
            print(f"Catching up on {len(missed)} posts...", flush=True)
            for m in reversed(missed):
                handle(m.id, m.message, True)

        print(f"Listening to channel {CHANNEL}. Ctrl+C to stop.", flush=True)
        client.run_until_disconnected()


if __name__ == "__main__":
    main()
