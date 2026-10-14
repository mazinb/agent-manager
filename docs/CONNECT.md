# Connect any coding agent

Base URL examples:

- Hosted: `https://bot.getzoro.com`
- Local: `http://127.0.0.1:8075`

MCP endpoint: `{BASE}/mcp`  
Auth header: `X-Token: YOUR_TOKEN` (or `Authorization: Bearer YOUR_TOKEN`)

Fastest path: open **`{BASE}/connect/`**, paste your token, pick a platform, **Copy**.

---

## One-click CLI

```bash
npx --yes agent-manager-brain connect \
  --url https://bot.getzoro.com \
  --token YOUR_TOKEN \
  --agent <platform>
```

| `--agent` | What it writes / runs |
|---|---|
| `cursor` | `~/.cursor/mcp.json` |
| `claude` | `claude mcp add …` |
| `vscode` / `copilot` | `.vscode/mcp.json` in the current directory |
| `windsurf` | `~/.codeium/windsurf/mcp_config.json` |
| `cline` | Cline MCP settings file if found, else prints JSON |
| `continue` | Appends to `~/.continue/config.yaml` |
| `zed` | Prints a `context_servers` block for `settings.json` |
| `codex` / `gemini` / `generic` | Prints portable MCP JSON |

---

## Cursor

1. Run the one-click command with `--agent cursor`, **or** edit `~/.cursor/mcp.json`.
2. Paste:

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

3. Restart Cursor. In Agent chat, confirm tools like `ask` / `search` / `note`.

---

## Claude Code

```bash
claude mcp add --transport http agent-manager https://bot.getzoro.com/mcp \
  --header "X-Token: YOUR_TOKEN"
```

Start a new session and ask: “search the brain for X”.

---

## VS Code / GitHub Copilot

1. Create `.vscode/mcp.json` in the project (or use user-level MCP settings).
2. Paste:

```json
{
  "servers": {
    "agent-manager": {
      "type": "http",
      "url": "https://bot.getzoro.com/mcp",
      "headers": { "X-Token": "YOUR_TOKEN" }
    }
  }
}
```

3. Reload VS Code and enable the server in Copilot Chat / MCP.

---

## Windsurf

1. Open Cascade → MCP servers, or edit `~/.codeium/windsurf/mcp_config.json`.
2. Merge the standard `mcpServers` JSON (same shape as Cursor).
3. Reload Windsurf.

---

## Cline

1. Open Cline → MCP Servers → Configure.
2. Paste the standard `mcpServers` JSON.
3. Enable **agent-manager** and start a new task.

---

## Continue.dev

Add to `~/.continue/config.yaml`:

```yaml
mcpServers:
  - name: agent-manager
    url: https://bot.getzoro.com/mcp
    headers:
      X-Token: YOUR_TOKEN
```

Reload the Continue extension.

---

## Zed

Merge into Zed `settings.json`:

```json
{
  "context_servers": {
    "agent-manager": {
      "url": "https://bot.getzoro.com/mcp",
      "headers": { "X-Token": "YOUR_TOKEN" }
    }
  }
}
```

---

## OpenAI Codex CLI / Gemini CLI

Use the generic MCP JSON in whichever MCP config file your CLI version reads,
or bridge with:

```bash
npx --yes agent-manager-brain connect --url https://bot.getzoro.com --token YOUR_TOKEN --agent generic
```

---

## REST / curl (no MCP client)

```bash
export BASE=https://bot.getzoro.com
export TOK=YOUR_TOKEN

curl -s "$BASE/api/search?q=tutor" -H "X-Token: $TOK" | jq
curl -s -X POST "$BASE/api/ask" -H "Content-Type: application/json" -H "X-Token: $TOK" \
  -d '{"q":"what ports are live?","use_llm":true}' | jq
curl -s -X POST "$BASE/api/note" -H "Content-Type: application/json" -H "X-Token: $TOK" \
  -d '{"project":"my-agent","title":"setup","body":"…"}' | jq
```

---

## System prompt fallback

When MCP wiring is awkward, paste this into custom instructions:

```
You have a shared context brain at https://bot.getzoro.com.
Auth header: X-Token: YOUR_TOKEN
- Search:   GET  /api/search?q=
- Ask:      POST /api/ask     {"q":"...","use_llm":true}
- Pack:     GET  /api/context?project=NAME
- Remember: POST /api/note    {"project":"your-slug","title":"...","body":"..."}
Before guessing about prior decisions, search or ask. After durable work, save a note.
```

---

## Tools

| Tool | Use |
|---|---|
| `ask` | Grounded question with citations |
| `search` | Full-text + entity search |
| `entity` | Card for a named thing |
| `context_pack` | Injectable pack for a project slug |
| `projects` / `stats` | What’s in the brain |
| `note` | Persist a decision / outcome / fact |
