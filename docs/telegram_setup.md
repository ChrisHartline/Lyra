# Telegram Setup

Lyra uses outbound Bot API long polling. It does not expose a webhook, open an
inbound port, or move session storage off the workstation.

## BotFather and allowlists

1. Create a bot with Telegram's BotFather and place the token in `.env` as
   `TELEGRAM_BOT_TOKEN`. Do not paste it into chat, source, or a committed file.
2. Send `/start` to the new bot from the private Telegram account/chat that
   will be allowed.
3. Stop any running Lyra Telegram poller, then discover the numeric IDs:

   ```powershell
   .\venv\Scripts\python.exe scripts\telegram_discover.py
   ```

4. Copy the two emitted assignments into `.env`:

   ```dotenv
   LYRA_TELEGRAM_ALLOWED_USER_IDS=<numeric user id>
   LYRA_TELEGRAM_ALLOWED_CHAT_IDS=<numeric chat id>
   ```

Both checks must match. Updates from every other sender or chat are silently
ignored and receive no confirmation that the bot exists.

## Start and verify

Restart the Lyra workstation service, then run:

```powershell
.\venv\Scripts\python.exe scripts\lyra_doctor.py
```

The report should show `[READY] telegram`. In Telegram:

- send a normal message and confirm Lyra replies;
- send the same conversation another message in the local web UI and confirm
  both appear in the bound named session;
- send a URL, supported document, photo, and voice note and confirm each is
  acknowledged as a local inbox item;
- send `/approve`, `/code`, or `/publish` and confirm the action is refused.

Downloaded artifacts live under `data/telegram/` by default and are gitignored.
They never become durable memories or KG observations directly. Photos, voice
notes, ambiguous inputs, and unsupported files remain pending manual review.
