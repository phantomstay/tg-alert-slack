"""
One-time login. Produces a session string.

Usage:  .venv/bin/python login.py
        .venv/bin/python login.py flight      # only show chats matching "flight"

Telegram will ask for your phone number, then a login code, then your
2FA password if you have one set. Nothing is written to disk.
"""
import sys
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("api_id: ").strip())
api_hash = input("api_hash: ").strip()
needle = (sys.argv[1] if len(sys.argv) > 1 else "").lower()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    me = client.get_me()
    print(f"\nLogged in as {me.first_name} (@{me.username})\n")

    print("Channels and groups this account can read:")
    for d in client.iter_dialogs():
        if not (d.is_channel or d.is_group):
            continue
        if needle and needle not in (d.name or "").lower():
            continue
        print(f"  {d.id:>16}  {d.name}")

    print("\n===== SESSION STRING (keep this secret) =====")
    print(client.session.save())
    print("=============================================")
