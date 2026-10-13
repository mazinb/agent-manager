# Agent pack: connect to agent-manager

`URL` is the brain base (`https://bot.getzoro.com` or `http://localhost:8075`).

## Claude Code

```bash
claude mcp add --transport http agent-manager https://bot.getzoro.com/mcp \
  --header "X-Token: $AGENT_MANAGER_TOKEN"
```

## Cursor

Plugin install is preferred. Manual `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "agent-manager": {
      "url": "https://bot.getzoro.com/mcp",
      "headers": { "X-Token": "YOUR_TOKEN" }
    }
  }
}
```

## MCP

- Endpoint: `URL/mcp` — stateless JSON-RPC 2.0 over POST
- Auth: `X-Token` or `Authorization: Bearer`

## Tools

`ask`, `search`, `entity`, `context_pack`, `projects`, `stats`, `note`
