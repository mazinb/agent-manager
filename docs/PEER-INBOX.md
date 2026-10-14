# Peer inbox (simpler than A2A)

Cross-repo agent talk without JSON-RPC, agent cards, or peer Bearer tokens.
Inspired by A2A’s coordinator↔worker idea; implemented as notes you can see
in the Grok-style inbox.

## Protocol

| Piece | Value |
|-------|--------|
| Bus project | `peers` (default) |
| Send | MCP `message_peer` — or `note` with `agent` + `to_agent` |
| Read | MCP `peer_inbox` — or `GET /api/inbox/messages?to=you` |
| UI | `/setup/` → project **peers** → centered **Messaged ● peer** lines |

```
hermes  --message_peer-->  cursor
   \                         /
    \____ inbox thread _____/
         (Mazin can read)
```

1. Caller sets `agent` = self, `to_agent` = peer, `body` = plain text.
2. Peer later calls `peer_inbox(to_agent=<self>)` and replies the same way
   (roles swapped).
3. Nothing auto-runs. No streaming. Human sees every ping in the inbox.

## vs A2A

| | Peer inbox | A2A (`a2a_call` / :9900 / :9910) |
|--|------------|----------------------------------|
| Shape | note + Messaged line | JSON-RPC SendMessage |
| Auth | same brain token | per-peer Bearer |
| Sync reply | no — poll `peer_inbox` | yes — blocks for task result |
| Visible to you | yes (`/setup/`) | audit log only |
| Use for | “ask peer X / audit routines / hand off” | “run a long Cursor task now” |

**Default for coordination: peer inbox.** Keep A2A only when you need a
synchronous worker (e.g. Hermes → `cursor-agent -p`).

## Examples

```bash
# send (token from .env — never echo it)
TOK=$(grep -m1 '^AGENT_MANAGER_TOKEN=' .env | cut -d= -f2-)
curl -s -H "X-Token: $TOK" -H 'Content-Type: application/json' \
  -d '{"project":"peers","title":"ping","body":"audit Monday digests",
       "agent":"hermes","to_agent":"cursor"}' \
  http://127.0.0.1:8075/api/note

# read
curl -s -H "X-Token: $TOK" \
  'http://127.0.0.1:8075/api/inbox/messages?to=cursor'
```

MCP (any agent with agent-manager connected):

```json
{"name":"message_peer","arguments":{
  "agent":"hermes","to_agent":"cursor",
  "body":"pytest green; please commit + restart"
}}
{"name":"peer_inbox","arguments":{"to_agent":"hermes"}}
```
