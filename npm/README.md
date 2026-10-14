# agent-manager-brain

npm entrypoint for [agent-manager](https://github.com/mazinb/agent-manager) —
connect any coding agent to a shared brain, or self-host one locally.

## Connect (hosted or remote)

```bash
npx agent-manager-brain connect \
  --url https://bot.getzoro.com \
  --token YOUR_TOKEN \
  --agent cursor
```

Agents: `cursor` · `claude` · `vscode` · `windsurf` · `cline` · `continue` ·
`zed` · `codex` · `gemini` · `generic`

One-click UI: https://bot.getzoro.com/connect/

## Self-host (npm + Python runtime)

The HTTP/MCP server is Python (stdlib only). npm clones and runs it:

```bash
npx agent-manager-brain init          # clone + .env + config
npx agent-manager-brain serve         # http://127.0.0.1:8075
npx agent-manager-brain connect \
  --url http://127.0.0.1:8075 \
  --token "$(grep AGENT_MANAGER_TOKEN ~/.agent-manager/app/.env | cut -d= -f2)" \
  --agent cursor
```

Requires `python3` and `git` on the PATH.

## Query

```bash
npx agent-manager-brain ask "what ports are live?" --url http://127.0.0.1:8075 --token TOK
npx agent-manager-brain search "voice tutor" --url … --token …
npx agent-manager-brain note --project my-agent --title setup --body "…" --url … --token …
```
