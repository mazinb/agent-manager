---
name: agent-manager-tick
description: "One board job per wake via board_tick; reassign freely."
version: 0.1.0
author: Mazin Biviji
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [agent-manager, peers, tick, zoro]
    related_skills: [peer-inbox, agent-manager-ops]
---

# Agent-manager tick

Cron / wake loop for the Zoro peers board. **One job per tick.** Cursor
plans and reassigns; you execute on-device work.

## When to Use

- Hermes cron `peers-board-tick` (or Mazin says “tick the board”)
- After `agent_poll` shows a `board_tick` action of `claim` / `continue`
- Don’t use for ad-hoc chat — that’s peer-inbox handoffs

## Tick procedure

1. **Tick**: MCP `board_tick(agent=hermes, chat=peers)` — or
   `board_tick(..., claim=true)` to claim in one call.
2. **Branch on `action`**:
   - `block` → `message_peer` to cursor `role: block` with failed gates; stop
   - `idle` → skim `inbox_titles`; if a fresh handoff is there, do that one
     job; else stop (short “idle” is fine)
   - `claim` → `claim_task` (or re-call with `claim=true`), then do the body
   - `continue` / `claimed` → do the claimed task body
3. **Work** the single task. Keep it small enough for one tick.
4. **Finish**: `update_task(id, status=done)` then
   `message_peer(agent=hermes, to_agent=cursor, body=role: done\ntask: <slug>\nresult: …)`
5. **Stop**. Do not start a second board task this wake.

## Reassign

Anyone (Cursor / UI / you with cause) can move work:

```
reassign_task(id=<N>, to_agent=cursor|hermes|designer|grok-bot, by=hermes)
```

Claimed tasks reopen. After a reassign **away** from you, do not keep
working that id — pick up the next tick’s task instead.

UI: `/agents/?chat=peers` → change the **Who** select.

## Policy

Prefer `agent_poll(agent=hermes)` on interval — hermes policy should include
`poll.actions: ["peer_inbox", "board_tick"]`. Before heavy work still call
`agent_ready` (board_tick already does).

## Reply shape

```
role: done
task: <slug>
result: <one line>
```

No secrets. Prefer peers over A2A. Docs: `~/projects/agent-manager/docs/TICK.md`.
