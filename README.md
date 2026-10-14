# Agent manager

A **shared brain for coding agents** — any platform that speaks MCP or HTTP.

Ingest project docs, rules, memories, and live services into a local knowledge
graph. Agents can **search**, **ask** (cited answers), pull **context packs**,
and **save notes** so the next session starts with memory.

Self-hosted. Stdlib-only Python. One process.

**Live demo / host UI:** [bot.getzoro.com](https://bot.getzoro.com)

| Path | Purpose |
|---|---|
| [`/connect/`](https://bot.getzoro.com/connect/) | One-click copy setup for every major agent |
| `/` | Optional helper chat UI |
| `/brain/` | Ask / entities / context packs |
| `/mcp` | Streamable HTTP MCP |
| `/api/*` | JSON API |

## Connect in 30 seconds

Open **[/connect/](https://bot.getzoro.com/connect/)**, paste your access token,
pick your agent, hit **Copy**.

Or run a one-liner:

```bash
# Cursor
npx --yes agent-manager-brain connect --url https://bot.getzoro.com --token YOUR_TOKEN --agent cursor

# Claude Code
npx --yes agent-manager-brain connect --url https://bot.getzoro.com --token YOUR_TOKEN --agent claude

# VS Code / Copilot, Windsurf, Cline, Continue, Zed, …
npx --yes agent-manager-brain connect --url https://bot.getzoro.com --token YOUR_TOKEN --agent vscode
```

Supported `--agent` values: `cursor`, `claude`, `vscode`, `copilot`, `windsurf`,
`cline`, `continue`, `zed`, `codex`, `gemini`, `generic`.

Full step-by-step for each platform: **[docs/CONNECT.md](docs/CONNECT.md)**.

### Generic MCP JSON

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

Auth: `X-Token` or `Authorization: Bearer`.  
Tools: `ask`, `search`, `entity`, `context_pack`, `projects`, `stats`, `note`.

## Self-host

```bash
cp .env.example .env                 # set AGENT_MANAGER_TOKEN
mkdir -p ~/.config/agent-manager
cp config.example.json ~/.config/agent-manager/config.json
# edit sources / llm as needed

pip install -e .
agent-manager refresh                # ingest
agent-manager serve                  # http://127.0.0.1:8075
```

Then open `http://127.0.0.1:8075/connect/` and point agents at
`http://127.0.0.1:8075/mcp`.

Optional: `bash install.sh` installs local helper chat profiles from `staging/`
if you use that workflow.

## How the brain works

```
ingest ──▶ resolve ──▶ query
files     entities    search / ask
memories  graph       context packs
services              notes (agent → agent)
```

- **SQLite + FTS5** — one file, WAL
- **Local LLM optional** — any OpenAI-compatible endpoint for cited answers
- **MCP + REST** — same auth, same tools

## Layout

```
static/connect.html          one-click setup UI
static/index.html            helper chat UI
agent_context/               brain library (ingest / query / MCP)
server.py                    unified HTTP process
docs/CONNECT.md              per-platform instructions
npm/                         npx agent-manager-brain CLI
config.example.json          brain sources / llm
```

## License

MIT
