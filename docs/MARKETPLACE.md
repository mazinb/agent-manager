# Cursor Marketplace submission

This repo is a **single Cursor Plugin** (manifest at `.cursor-plugin/plugin.json`).

## Checklist

- [x] `.cursor-plugin/plugin.json` with unique kebab-case `name`: `agent-manager`
- [x] Clear `description`, `author`, `homepage`, `repository`, `license`, `keywords`
- [x] `assets/logo.svg` referenced by relative path
- [x] `mcp.json` uses `${AGENT_CONTEXT_URL}` / `${AGENT_CONTEXT_TOKEN}` only (no secrets)
- [x] Variables declared in the manifest for every `${VAR}`
- [x] Rules / skills / commands have valid YAML frontmatter
- [x] `README.md` documents install + configuration
- [x] Paths are relative (no `..`, no absolute paths)
- [ ] Public GitHub repo: `https://github.com/mazinb/agent-manager`
- [ ] Local smoke test: install plugin, MCP tools list, `/recall` + `/remember`
- [ ] Submit at [cursor.com/marketplace/publish](https://cursor.com/marketplace/publish)

## What reviewers get

| Piece | Path | Role |
|---|---|---|
| Manifest | `.cursor-plugin/plugin.json` | Plugin identity + variables |
| MCP | `mcp.json` | HTTP brain → agent-context |
| Always-on rule | `rules/agent-manager.mdc` | Prefer this brain over Adapter |
| Skill | `skills/agent-manager/SKILL.md` | Recall / remember procedures |
| Commands | `commands/recall.md`, `commands/remember.md` | `/recall`, `/remember` |
| Dashboard (optional self-host) | `server.py`, `static/`, `install.sh` | https://bot.getzoro.com |

## Defaults for marketplace users

- **MCP URL default:** `https://bot.getzoro.com/space/mcp` (free shared space, no token)
- **Private brain:** set `AGENT_CONTEXT_URL` to `https://bot.getzoro.com/context/mcp` (or self-hosted) and set `AGENT_CONTEXT_TOKEN` in Plugins → Configure

## Team marketplace (private)

On Teams/Enterprise: Dashboard → Plugins → Team Marketplaces → Import from Repo → paste this repository URL. Set installation mode to **Default On** or **Required** if you want every developer on agent-manager instead of Adapter.
