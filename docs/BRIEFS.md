# Agent briefs

Fluid, agent-friendly rules for a chat board. Replaces the old match→agent
Rules form on `/agents/`.

## Shape

One markdown document per **board member**:

```markdown
---
routes: on-device=serial, deploy=serial
---

# Hermes

You execute on-device work. Cursor plans. Keep peer replies short.
```

- **Prose** — how the agent should behave on this chat.
- **`routes:`** — optional auto-assign hints (`keyword=serial|parallel`).
  First brief match wins, then legacy `task_rules` if any remain.

## Bloat guards

| Guard | Limit |
|-------|-------|
| Per brief | 4 000 chars (hard truncate) |
| Session pack | 12 000 chars |
| Who | Board members only |
| Re-inject | Skip when `content_hash` unchanged (`since_hashes`) |

Do not paste thread history into briefs — link a peer note title instead.

## MCP / HTTP

```
list_briefs        [chat=peers]
get_brief          agent  [chat]
set_brief          agent  body  [chat]
session_pack       [chat]  [since_hashes]
session_bootstrap  [project]  [chat]  [since_hashes]  [context_hash]

GET  /api/roster/briefs?chat=peers
GET  /api/roster/briefs?chat=peers&agent=hermes
POST /api/roster/briefs  {agent, body, chat}
GET  /api/roster/session-pack?chat=peers
GET|POST /api/session/bootstrap  ?project=&chat=peers
```

## Loop

1. Open `/agents/?chat=peers` → edit Briefs → Save.
2. Agent connects → host auto-loads packs via MCP `initialize` instructions,
   `session_bootstrap`, or `npx agent-manager-brain connect|bootstrap --project X`.
3. Later turns → pass prior `hashes` (`since_hashes` + `context_hash`) → unchanged
   briefs/context are skipped (client persists hashes under
   `~/.agent-manager/bootstrap-state.json`).
