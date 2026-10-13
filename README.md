# Agent manager

A mind for Cursor — and a small dashboard for per-project Hermes helpers.

Cursor recalls context from a shared brain before working and saves durable
notes as it goes. The same brain backs the web UI at
**[bot.getzoro.com](https://bot.getzoro.com)**.

Built on [agent-context](https://github.com/mazinb/agent-context) (SQLite + FTS5,
stdlib Python, MCP over HTTP).

## Install (Cursor Marketplace)

1. Install **agent-manager** from the Cursor plugin marketplace (or Team Marketplace).
2. Open **Plugins → Configure** and confirm:
   - **Brain MCP URL** — default `https://bot.getzoro.com/space/mcp` (free shared space)
   - **Brain access token** — leave empty for the free space; set for a private brain
3. Disable or uninstall **Adapter** if both are installed so they do not compete.
4. In Agent chat, use `/recall` and `/remember`, or let the always-on rule call the MCP tools.

### Manual MCP (without the plugin)

```json
{
  "mcpServers": {
    "agent-manager": {
      "url": "https://bot.getzoro.com/space/mcp"
    }
  }
}
```

Private self-hosted brain:

```json
{
  "mcpServers": {
    "agent-manager": {
      "url": "http://localhost:8076/mcp",
      "headers": { "X-Token": "YOUR_TOKEN" }
    }
  }
}
```

## What the plugin ships

```
.cursor-plugin/plugin.json   Cursor Plugin manifest + variables
mcp.json                     agent-manager MCP → shared brain
rules/agent-manager.mdc      always-on recall / remember guidance
skills/agent-manager/        procedures for the MCP tools
commands/                    /recall, /remember
assets/logo.svg              marketplace logo
```

MCP tools (from agent-context): `ask`, `search`, `entity`, `context_pack`,
`projects`, `stats`, `note`.

## Dashboard (self-host)

`server.py` — stdlib web UI to chat with Hermes helper profiles.

```bash
cp .env.example .env          # set AGENT_MANAGER_TOKEN
bash install.sh               # install staged profiles → ~/.hermes/profiles/
python3 server.py             # http://127.0.0.1:8075
```

Production on this host:

- URL: **https://bot.getzoro.com** (cloudflared ingress → `:8075`)
- Service: `systemctl --user status agent-manager.service`
- Auth: `X-Token` vs `AGENT_MANAGER_TOKEN` (token prompt stored in localStorage)
- `/context/*` → private brain (`agent-context` on `:8076`, token swapped server-side)
- `/space/*` → free public brain (`:8077`, no auth by design)

### Helpers

`staging/<project>/{SOUL.md,SKILL.md}` → `install.sh` → Hermes profile +
`<project>-ops` skill. Chat from the UI or:

```bash
hermes -p voice-lab chat -q "status of the last run?"
```

## Layout

| Path | Purpose |
|---|---|
| `.cursor-plugin/` | Marketplace manifest |
| `rules/`, `skills/`, `commands/`, `mcp.json` | Cursor plugin components |
| `server.py`, `static/` | Dashboard |
| `install.sh`, `staging/` | Hermes helper packs |
| `docs/MARKETPLACE.md` | Submission checklist |
| `data/` | Local chat history (gitignored) |
| `.env` | Local token (gitignored) |

## Marketplace submission

See [docs/MARKETPLACE.md](docs/MARKETPLACE.md). Submit the public repo at
[cursor.com/marketplace/publish](https://cursor.com/marketplace/publish).

## License

MIT
