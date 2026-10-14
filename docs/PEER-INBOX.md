# Peer inbox

Agents talk on project `peers`. Mazin sees it in `/inbox/`.

## Roles

| Who | Does |
|-----|------|
| **Cursor** | Plan → hand off → supervise |
| **Hermes** | On-device work → status / done on the bus |
| **Mazin** | Reads `/inbox/`; overrides anytime |

Prefer this over A2A. A2A only for a sync `cursor-agent` worker.

## Message shape (keep short)

```
role: handoff
task: <slug>
do: <one job>
done when: <check>
```

Roles: `plan` · `handoff` · `status` · `done` · `block`

## Loop

1. **Plan** (Cursor) — decide the job; optional `role: plan` note.
2. **Hand off** — `message_peer(agent=cursor, to_agent=hermes, body=…)`.
3. **Work** (Hermes) — run it; `role: status` if long; finish with `role: done`.
4. **Supervise** (Cursor) — `peer_inbox(to_agent=cursor)`; reply or re-hand-off.

Wake Hermes if quiet: Telegram `telegram:8675509877` — “check peer inbox”.

## Tools

```
message_peer  agent  to_agent  body  [title]  [project=peers]
peer_inbox    to_agent=you  [agent=sender]  [limit]
GET /api/inbox/messages?to=hermes
```

Names: `cursor` · `hermes` · `grok-bot` · …

## vs A2A

| | Peer inbox | A2A |
|--|------------|-----|
| Coord / hand-off | **yes** | no |
| Sync long Cursor task | no | yes |
| Visible in UI | `/inbox/` | audit log |
