# Agent setup steps — self-host

> Agent reading this: run commands verbatim, in order. Don't invent flags.
> Full docs, API, and architecture: [README.md](README.md) — read it first if
> anything here is unclear.

## 1. Prerequisites (check, don't install blindly)

```bash
git --version && python3 --version   # python3 >= 3.9, stdlib only — no pip install needed
node --version                       # >= 18, only if using the npm CLI below
```

## 2. One command (recommended)

**Via npm** (needs node 18+):

```bash
npx --yes agent-manager-brain setup --agent cursor
```

**Or from a clone:**

```bash
git clone https://github.com/mazinb/agent-manager && cd agent-manager
node npm/cli.js setup --agent cursor
```

Replace `cursor` with your platform: `claude` `vscode` `windsurf` `cline`
`continue` `zed` `codex` `gemini` `generic` — or omit `--agent` to just print
the MCP config.

`setup` does everything: clones the app to `~/.agent-manager/app` (if needed),
generates a token in `.env`, starts the server on **127.0.0.1:8075** in the
background, ingests your sources, and writes the MCP config for your platform.

## 3. Verify

```bash
curl -s -H "X-Token: $(grep AGENT_MANAGER_TOKEN ~/.agent-manager/app/.env | cut -d= -f2)" \
  http://127.0.0.1:8075/api/stats
```

Expect JSON with `sources` > 0. Also check:

- UI: `http://127.0.0.1:8075/`
- MCP: `http://127.0.0.1:8075/mcp` (auth: `X-Token`, value from the `.env` above)

## 4. Manage

| Action | Command |
|---|---|
| Stop | `npx --yes agent-manager-brain stop` |
| Logs | `tail -20 ~/.agent-manager/agent-manager.log` |
| Re-ingest after editing docs | `curl -X POST -H "X-Token: $TOKEN" http://127.0.0.1:8075/api/refresh` |
| Query from CLI | `npx --yes agent-manager-brain ask "question" --url http://127.0.0.1:8075 --token $TOKEN` |
| Different port | add `--port 8090` to `setup` |

## Troubleshooting

- **Port busy** → another brain is running; pass `--port 8090`.
- **`python3` missing** → install Python 3.9+, re-run `setup`.
- **0 sources ingested** → the default config reads `~/projects/*/README.md`;
  put markdown there or edit `~/.config/agent-manager/config.json` (`sources`),
  then POST `/api/refresh`.
- **`ask` returns no answer, only sources** → no LLM configured; add
  `"llm": {"base_url": "http://127.0.0.1:8888/v1", "model": "..."}` to the
  config (OpenAI-compatible), or use `--no-llm` semantics: search works fine
  without one.
