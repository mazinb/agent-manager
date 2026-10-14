# Agent manager

A **shared brain for coding agents** — any platform that speaks MCP or HTTP.

Ingest project docs, rules, memories, and live services into a local knowledge
graph. Agents can **search**, **ask** (cited answers), pull **context packs**,
and **save notes** so the next session starts with memory.

Self-hosted. Stdlib-only Python. One process.

**Live:** [bot.getzoro.com](https://bot.getzoro.com)

| Path | Purpose |
|---|---|
| [`/`](https://bot.getzoro.com/) | Public landing |
| [`/setup/`](https://bot.getzoro.com/setup/) | Create or save an access token |
| [`/connect/`](https://bot.getzoro.com/connect/) | One-click copy setup for every major agent |
| `/brain/` | Ask / entities / context packs |
| `/agents/` | Optional helper chat UI |
| `/mcp` | Streamable HTTP MCP |
| `/api/*` | JSON API |

## First-time setup

1. Open **[/setup/](https://bot.getzoro.com/setup/)**  
2. On a fresh brain: **Create token** (shown once — save it)  
3. On a private hosted brain: paste a token you were given, or self-host  
4. Open **[/connect/](https://bot.getzoro.com/connect/)**, pick your agent, **Copy**

Auth is the token itself (no password page). Same value goes in the browser and
as `X-Token` / `Bearer` for MCP. Details: [docs/AUTH.md](docs/AUTH.md).

## Connect agents (npm)

Package: **[`agent-manager-brain`](https://www.npmjs.com/package/agent-manager-brain)**

```bash
npx --yes agent-manager-brain connect \
  --url https://bot.getzoro.com \
  --token YOUR_TOKEN \
  --agent vscode
```

`--agent`: `claude` · `vscode` · `copilot` · `cursor` · `windsurf` · `cline` ·
`continue` · `zed` · `codex` · `gemini` · `generic`

### Self-host via npm

```bash
npx --yes agent-manager-brain init
npx --yes agent-manager-brain serve
# open http://127.0.0.1:8075/setup/  → create token
npx --yes agent-manager-brain connect \
  --url http://127.0.0.1:8075 \
  --token YOUR_TOKEN \
  --agent generic
```

Full platform steps: **[docs/CONNECT.md](docs/CONNECT.md)**.

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

Tools: `ask`, `search`, `entity`, `context_pack`, `projects`, `stats`, `note`.

## Self-host (Python)

```bash
cp .env.example .env                 # or create token via /setup/
mkdir -p ~/.config/agent-manager
cp config.example.json ~/.config/agent-manager/config.json

pip install -e .
agent-manager refresh
agent-manager serve                  # http://127.0.0.1:8075
```

Optional open signup for extra tokens: `ALLOW_PUBLIC_SIGNUP=1`  
Optional invite gate: `SETUP_INVITE_CODE=…`

## Layout

```
static/home.html             public landing
static/setup.html            token onboarding
static/connect.html          one-click setup UI
static/agents.html           helper chat UI
agent_context/               brain library
server.py                    unified HTTP process
docs/CONNECT.md              per-platform instructions
docs/AUTH.md                 token model + OAuth notes
npm/                         npx agent-manager-brain CLI
```

## License

MIT
