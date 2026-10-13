# Cursor Marketplace submission

Single Cursor Plugin. Manifest: `.cursor-plugin/plugin.json`.

## Checklist

- [x] Unique kebab-case `name`: `agent-manager`
- [x] Clear `description`, `author`, `homepage`, `repository`, `license`, `keywords`
- [x] `assets/logo.svg` referenced by relative path
- [x] `mcp.json` uses only `${AGENT_MANAGER_URL}` / `${AGENT_MANAGER_TOKEN}` (no secrets)
- [x] Variables declared for every `${VAR}`
- [x] Rules / skills / commands have valid YAML frontmatter
- [x] Brain + dashboard live in this same repo (no `agent-context` dependency)
- [x] Public `/space` removed — token-gated `/mcp` only
- [x] `README.md` documents install + configuration
- [x] Public GitHub repo: `https://github.com/mazinb/agent-manager`
- [x] `python3 scripts/validate-plugin.py` passes
- [ ] Cursor UI smoke test: enable plugin, tools/list, `/recall`, `/remember`
- [ ] Submit at [cursor.com/marketplace/publish](https://cursor.com/marketplace/publish)

## Defaults

| Variable | Default |
|---|---|
| `AGENT_MANAGER_URL` | `https://bot.getzoro.com/mcp` |
| `AGENT_MANAGER_TOKEN` | *(required — set in Plugins → Configure)* |

## Team marketplace

Dashboard → Plugins → Team Marketplaces → Import from Repo →
`https://github.com/mazinb/agent-manager`. Prefer **Default On** or **Required**
so Adapter is not competing for always-on memory.
