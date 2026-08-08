"""Verify the Telegram bot credentials and send a test message.

    python scripts/telegram_check.py

On the VPS:  docker compose -f docker-compose.prod.yml exec api \
                 python scripts/telegram_check.py

Checks TELEGRAM_BOT_TOKEN against the Bot API (getMe), then sends a test
message to TELEGRAM_CHAT_ID — the exact call the order notification uses.
If no chat id is configured yet, it lists the chats the bot can currently
see (message the bot first, then re-run) so you can copy the right id.
"""
import sys

import httpx

from app.config import get_settings


def api(token: str, method: str, **payload):
    resp = httpx.post(f"https://api.telegram.org/bot{token}/{method}",
                      json=payload or None, timeout=15)
    body = resp.json()
    if not body.get("ok"):
        sys.exit(f"{method} failed: {body.get('description', resp.text[:200])}")
    return body["result"]


def main() -> None:
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN is empty — create a bot with @BotFather "
                 "and put the token in .env")

    me = api(token, "getMe")
    print(f"bot ok: @{me['username']} ({me['first_name']})")

    chat_id = settings.telegram_chat_id
    if not chat_id:
        updates = api(token, "getUpdates")
        chats = {}
        for u in updates:
            msg = u.get("message") or u.get("channel_post") or {}
            chat = msg.get("chat")
            if chat:
                chats[chat["id"]] = chat.get("title") or chat.get("username") \
                    or chat.get("first_name") or "?"
        if not chats:
            sys.exit("TELEGRAM_CHAT_ID is empty and the bot has seen no "
                     "messages yet.\nSend the bot any message (or add it to "
                     "your operators group and write there), then re-run.")
        print("TELEGRAM_CHAT_ID is empty. Chats the bot can see:")
        for cid, name in chats.items():
            print(f"  {cid}    {name}")
        sys.exit("Put the right id in .env as TELEGRAM_CHAT_ID and re-run.")

    api(token, "sendMessage", chat_id=chat_id,
        text="RS Pixel: test message — order notifications will arrive here.")
    print(f"test message sent to chat {chat_id} — check Telegram")


if __name__ == "__main__":
    main()
