"""Discover Telegram sender/chat IDs after messaging a new Lyra bot."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from lyra.telegram import BotAPI, TelegramError


ROOT = Path(__file__).resolve().parents[1]


async def discover(timeout: int) -> list[tuple[str, str]]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not configured")
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout + 10.0)) as client:
        updates = await BotAPI(token, client).get_updates(None, timeout)
    identities = set()
    for update in updates:
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        sender = message.get("from")
        chat = message.get("chat")
        if isinstance(sender, dict) and isinstance(chat, dict):
            identities.add((str(sender.get("id")), str(chat.get("id"))))
    return sorted(identities)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=5)
    args = parser.parse_args(argv)
    if args.timeout < 0 or args.timeout > 30:
        parser.error("--timeout must be between 0 and 30 seconds")
    load_dotenv(ROOT / ".env", override=False)
    try:
        identities = asyncio.run(discover(args.timeout))
    except TelegramError as exc:
        print(f"ERROR: {exc}")
        return 1
    if not identities:
        print("No messages found. Send /start to the bot, then run this helper again.")
        return 1
    for user_id, chat_id in identities:
        print(f"LYRA_TELEGRAM_ALLOWED_USER_IDS={user_id}")
        print(f"LYRA_TELEGRAM_ALLOWED_CHAT_IDS={chat_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
