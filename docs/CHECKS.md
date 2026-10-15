# Agent checks

Per-agent policy for **gates** (before work) and **poll** (periodic).

## Policy shape

```json
{
  "gates": ["brain", "thermal"],
  "poll": { "every_min": 5, "actions": ["peer_inbox"] },
  "on_fail": "block"
}
```

| Field | Meaning |
|-------|---------|
| `gates` | Must pass before claiming / starting work (`agent_ready`) |
| `poll.every_min` | How often the agent should call `agent_poll` |
| `poll.actions` | What to do on each poll (`peer_inbox`, `board_tick`) |
| `on_fail` | `block` = not ready; `warn` = ready but failed listed |

### Built-in gates

| Gate | Passes when |
|------|-------------|
| `brain` | `:8888/v1/models` 200 + tiny completion |
| `thermal` | `~/brain/thermal.state` `hot_hold` ≠ 1 |
| `agent_manager` | this process responds on `:8075` |

Defaults: **hermes** gates `brain`+`thermal`, poll `peer_inbox`+`board_tick`
every 5m; **cursor** / **grok-bot** / **designer** poll inbox only (warn).

## MCP / HTTP

```
get_policy   agent
set_policy   agent  policy
agent_ready  agent
agent_poll   agent
board_tick   agent  [claim]
reassign_task id  to_agent

GET  /api/roster/policies[?agent=]
POST /api/roster/policies  {agent, policy}
POST /api/roster/ready     {agent}
POST /api/roster/poll      {agent}
POST /api/roster/tick      {agent, claim?}
POST /api/roster/tasks/reassign  {id, to_agent}
GET  /api/roster/ready     → last states (Team “Ready” column)
```

Hermes tick skill: `board_tick` → one job → `role:done`. See [TICK.md](TICK.md).
`agent_ready` → if blocked, `role:block` → else work → `agent_poll` on interval.
