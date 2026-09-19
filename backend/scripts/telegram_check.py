"""Verify the Telegram bot credentials, and set up inbound control.

    python scripts/telegram_check.py                 # credentials + test message
    python scripts/telegram_check.py --who           # ids, for the allowlist
    python scripts/telegram_check.py --set-webhook https://rspixel.uz
    python scripts/telegram_check.py --webhook-info
    python scripts/telegram_check.py --delete-webhook

On the VPS:  docker compose -f docker-compose.prod.yml exec api \
                 python scripts/telegram_check.py

Checks TELEGRAM_BOT_TOKEN against the Bot API (getMe), then sends a test
message to TELEGRAM_CHAT_ID — the exact call the order notification uses.
If no chat id is configured yet, it lists the chats the bot can currently
see (message the bot first, then re-run) so you can copy the right id.

Switching on inbound control (A96/A97):

    1. TELEGRAM_WEBHOOK_SECRET in .env, then restart
    2. --set-webhook https://YOURDOMAIN
    3. admin console -> Telegram -> Link a Telegram account, and send the
       bot `/link <code>`

`--who` is only needed for the break-glass path: putting an id straight in
TELEGRAM_CONTROL_USER_IDS, for when the console is unavailable. It reads
getUpdates, which Telegram refuses while a webhook is registered, so run it
BEFORE step 2 (or --delete-webhook first).
"""
import argparse
import sys

import httpx

from app.config import get_settings

WEBHOOK_PATH = "/api/v1/telegram/webhook"


def api(token: str, method: str, **payload):
    resp = httpx.post(f"https://api.telegram.org/bot{token}/{method}",
                      json=payload or None, timeout=15)
    body = resp.json()
    if not body.get("ok"):
        sys.exit(f"{method} failed: {body.get('description', resp.text[:200])}")
    return body["result"]


def cmd_who(token: str) -> None:
    """Who the bot has heard from, chat id and USER id side by side.

    They are different things and the difference matters: the chat id says
    where notifications go, the user id says who may press a button. Being in
    the chat is not authority to act (A96).
    """
    updates = api(token, "getUpdates")
    seen = {}
    for u in updates:
        msg = (u.get("message") or u.get("channel_post")
               or (u.get("callback_query") or {}).get("message") or {})
        sender = (u.get("message") or {}).get("from") \
            or (u.get("callback_query") or {}).get("from") or {}
        chat = msg.get("chat") or {}
        if sender.get("id"):
            seen[sender["id"]] = (
                sender.get("username") or sender.get("first_name") or "?",
                chat.get("id"))
    if not seen:
        sys.exit("The bot has seen no messages.\nWrite to it (or in your "
                 "operators group), then re-run. If a webhook is already set, "
                 "Telegram will not answer getUpdates — run --delete-webhook "
                 "first.")
    print("user id      name                 chat id")
    for uid, (name, cid) in seen.items():
        print(f"{uid:<12} {name:<20} {cid}")
    print("\nThe ordinary way to allow an account is the admin console "
          "-> Telegram -> Link a Telegram account.\n"
          "TELEGRAM_CONTROL_USER_IDS (comma-separated USER ids) is the "
          "break-glass path for when the console is unavailable.")


def cmd_set_webhook(token: str, base: str) -> None:
    settings = get_settings()
    secret = settings.telegram_webhook_secret
    if not secret:
        sys.exit("TELEGRAM_WEBHOOK_SECRET is empty. Generate one "
                 "(openssl rand -hex 32), put it in .env, restart, re-run.\n"
                 "Without it the webhook route answers 404 by design.")
    if not base.startswith("https://"):
        sys.exit("Telegram only delivers webhooks over HTTPS — the URL must "
                 "start with https://")
    url = base.rstrip("/")
    if not url.endswith(WEBHOOK_PATH):
        url += WEBHOOK_PATH
    api(token, "setWebhook", url=url, secret_token=secret,
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True)
    print(f"webhook set: {url}")
    print("\nNow link your Telegram account (A97):")
    print("  admin console -> Telegram -> Link a Telegram account")
    print("  then send the bot:  /link <the code>")
    print("\nUntil an account is linked nobody can move orders — the bot "
          "will answer every press by saying so.")


def cmd_webhook_info(token: str) -> None:
    info = api(token, "getWebhookInfo")
    url = info.get("url") or "(none)"
    print(f"url:            {url}")
    print(f"pending:        {info.get('pending_update_count', 0)}")
    # Telegram never reports the secret back, so there is nothing truthful to
    # print about it here. A wrong one shows up as 404s in last_error_message.
    if info.get("last_error_message"):
        print(f"last error:     {info['last_error_message']}")
        print("A 404 here is the route refusing: check "
              "TELEGRAM_WEBHOOK_SECRET is set and the API was restarted "
              "after setting it.")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--who", action="store_true",
                    help="list user ids the bot has heard from")
    ap.add_argument("--set-webhook", metavar="BASE_URL", default=None,
                    help="register the inbound webhook, e.g. https://rspixel.uz")
    ap.add_argument("--webhook-info", action="store_true")
    ap.add_argument("--delete-webhook", action="store_true")
    args = ap.parse_args()

    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN is empty — create a bot with @BotFather "
                 "and put the token in .env")

    me = api(token, "getMe")
    print(f"bot ok: @{me['username']} ({me['first_name']})")

    if args.who:
        return cmd_who(token)
    if args.set_webhook:
        return cmd_set_webhook(token, args.set_webhook)
    if args.webhook_info:
        return cmd_webhook_info(token)
    if args.delete_webhook:
        api(token, "deleteWebhook")
        print("webhook deleted — the bot no longer accepts button presses")
        return

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
