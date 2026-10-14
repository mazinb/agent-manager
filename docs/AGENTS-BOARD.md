# Agents board

Cross-project coordination for Hermes, Grok, Cursor, and friends.

## Why

Not “tasks for this repo.” A shared roster + queue every agent can see.

## Pieces

| Piece | What |
|-------|------|
| **Roster** | Named agents; each can mint its own API key (view once) |
| **Tasks** | Shared list: open → claimed → done |
| **Rules** | Substring match → assignee + parallel/serial |
| **UI** | `/agents/` (also `/connect/`) |

## Parallel

- **∥ parallel** — agent may claim several at once  
- **→ serial** — agent may hold only one claimed serial task

## Defaults

Agents: `hermes`, `cursor`, `grok-bot`  
Rules: `on-device`/`deploy` → hermes (serial); `code` → cursor; `review` → grok-bot

## MCP

`list_roster` · `list_tasks` · `add_task` · `claim_task` · `update_task`

Cursor plans → `add_task` → Hermes `claim_task` → `update_task(done)`.
