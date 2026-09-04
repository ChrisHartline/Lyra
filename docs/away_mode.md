# Device Handoff and Away Mode

W5.2 keeps web and Telegram on the same local session store. A handoff changes
which named session a configured Telegram private chat points to; it does not
copy, merge, or delete messages. New messages record their source channel as
metadata while the stored message text remains unchanged.

All management endpoints are available only through Lyra's loopback-bound web
service. Telegram cannot invoke them.

## Handoff

The workstation must have exactly one chat ID in
`LYRA_TELEGRAM_ALLOWED_CHAT_IDS`. Bind that private chat to an existing session:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8765/api/sessions/<session-id>/handoff/telegram"
```

Inspect a session's bindings:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8765/api/sessions/<session-id>/channels"
```

## Presentation preferences

`standard` preserves the normal response presentation. `concise` asks Lyra to
keep replies brief and scannable without changing her identity, memory rules,
or stored conversation content.

```powershell
Invoke-RestMethod -Method Patch `
  -Uri "http://127.0.0.1:8765/api/preferences/telegram" `
  -ContentType "application/json" `
  -Body '{"presentation_mode":"concise"}'
```

## Away Mode

Away Mode makes replies concise on every channel and governs proactive
notification delivery. Quiet hours use an IANA timezone. Non-urgent categories
(`digest`, `commitment`, `research`, `social`, and `status`) are batched during
quiet hours and suppressed after the daily budget is exhausted. Explicit urgent
categories (`security`, `safety`, `service_failure`, and `user_requested`)
bypass quiet hours and the budget.

```powershell
Invoke-RestMethod -Method Put `
  -Uri "http://127.0.0.1:8765/api/away" `
  -ContentType "application/json" `
  -Body '{"enabled":true,"quiet_start":"22:00:00","quiet_end":"07:00:00","timezone":"America/Chicago","daily_notification_budget":4}'
```

Read the current policy or queued batch:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/away"
Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/away/batched"
```

The delivery policy is local infrastructure for later digest, commitment, and
research producers. It records every send, batch, or suppression decision in
PostgreSQL so the behavior is testable and auditable.
