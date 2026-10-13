# Agent manager

One product for Cursor agents and Hermes helpers:

- **Shared brain** — ingest project docs, rules, memories, and services into SQLite + FTS5; answer with citations over MCP
- **Dashboard** — chat with per-project Hermes helpers at **[bot.getzoro.com](https://bot.getzoro.com)**
- **Cursor plugin** — always-on recall/remember rules + MCP wiring for the marketplace

Self-hosted, stdlib-only Python. No separate `agent-context` service and no public `/space`.

## Install (Cursor Marketplace)

1. Install **agent-manager** from the Cursor plugin marketplace (or Team Marketplace).
2. **Plugins → Configure**:
   - **MCP URL** — `https://bot.getzoro.com/mcp` (or your self-hosted URL)
   - **Access token** — same token that unlocks the dashboard
3. Disable **Adapter** if it is also installed.
4. In Agent chat use `/recall` and `/remember`, or let the always-on rule call the tools.

### Manual MCP

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

## Self-host

```bash
cp .env.example .env                 # set AGENT_MANAGER_TOKEN
mkdir -p ~/.config/agent-manager
cp config.example.json ~/.config/agent-manager/config.json
# edit sources / llm as needed

pip install -e .
bash install.sh                      # Hermes helper profiles from staging/
agent-manager refresh                # ingest
agent-manager serve                  # http://127.0.0.1:8075
```

| Path | Purpose |
|---|---|
| `/` | Hermes helper chat |
| `/brain/` | Brain UI (ask / entities / packs) |
| `/mcp` | Streamable HTTP MCP |
| `/api/*` | Chat + brain JSON API |

Auth is one token: `AGENT_MANAGER_TOKEN` in `.env` (`X-Token` or `Bearer`).

### systemd (this host)

```bash
systemctl --user restart agent-manager.service
systemctl --user disable --now agent-context.service agent-context-public.service
```

Daily re-ingest: `agent-manager-refresh.timer` → `agent-manager refresh`.

## Plugin layout

```
.cursor-plugin/plugin.json   Cursor Plugin manifest + variables
mcp.json                     MCP → https://bot.getzoro.com/mcp
rules/agent-manager.mdc      always-on recall / remember
skills/agent-manager/        procedures
commands/                    /recall, /remember
assets/logo.svg
agent_context/               brain library (ingest / query / MCP)
server.py                    unified HTTP process
staging/ + install.sh        Hermes helper packs
```

MCP tools: `ask`, `search`, `entity`, `context_pack`, `projects`, `stats`, `note`.

## Marketplace submission

See [docs/MARKETPLACE.md](docs/MARKETPLACE.md). Submit at
[cursor.com/marketplace/publish](https://cursor.com/marketplace/publish).

## License

MIT
