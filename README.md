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
| [`/connect/`](https://bot.getzoro.com/connect/) | One-click MCP setup |
| `/brain/` | Ask / entities / context packs |
| `/mcp` | Streamable HTTP MCP |
| `/api/*` | JSON API |

## First-time setup

**Self-hosting? Jump to [AGENT-SETUP.md](AGENT-SETUP.md) — one command.**

1. Open **[/setup/](https://bot.getzoro.com/setup/)** → get a free token  
2. Open **[/connect/](https://bot.getzoro.com/connect/)** → pick your agent → Copy  

Auth is the token (`X-Token` / `Bearer`). Details: [docs/AUTH.md](docs/AUTH.md).

## Connect (npm)

Package: **[`agent-manager-brain`](https://www.npmjs.com/package/agent-manager-brain)**

```bash
npx --yes agent-manager-brain connect \
  --url https://bot.getzoro.com \
  --token YOUR_TOKEN \
  --agent vscode
```

Self-host:

```bash
npx --yes agent-manager-brain init
npx --yes agent-manager-brain serve
# open http://127.0.0.1:8075/setup/
```

Full platform steps: **[docs/CONNECT.md](docs/CONNECT.md)**.

## Self-host (Python)

```bash
cp .env.example .env
mkdir -p ~/.config/agent-manager
cp config.example.json ~/.config/agent-manager/config.json
pip install -e .
agent-manager refresh
agent-manager serve
```

`ALLOW_PUBLIC_SIGNUP=1` lets visitors mint tokens on a running brain.

## License

MIT
