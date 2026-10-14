# Auth model

Agent Manager is **token-first**. OAuth can come later; first-time users should
not need a Cursor account or a password form.

## What ships today

| Surface | Auth |
|---|---|
| `/`, `/setup/`, `/connect/` | Public |
| `/brain/` | Public HTML; APIs require token |
| `/api/*`, `POST /mcp` | `X-Token` or `Authorization: Bearer` |

### Token sources

1. **`AGENT_MANAGER_TOKEN` in `.env`** — owner/admin token  
2. **`data/tokens.json`** — hashed tokens created via setup

### First-time flows

**Fresh self-host (no token yet)**  
1. Open `/setup/`  
2. Click **Create token**  
3. Copy it once (also saved to browser localStorage + `.env` when possible)  
4. Use it in the UI and in MCP clients  

**Already configured / hosted**  
- Paste a token you were given, **or**  
- Self-host and bootstrap your own brain  
- Optional: set `ALLOW_PUBLIC_SIGNUP=1` (and maybe `SETUP_INVITE_CODE`) to mint more tokens without sharing the admin secret  

No password wall on the marketing/setup pages. The secret *is* the token —
same pattern as many MCP servers and bot dashboards.

## GitHub / Google login — feasibility

**Feasible**, but it’s a product step up from “shared token”:

| | GitHub OAuth | Google OAuth |
|---|---|---|
| Effort | Medium | Medium–high |
| Console setup | GitHub OAuth App (callback URL) | Google Cloud OAuth client + consent screen |
| Best for | Devtools users | Broader consumers |
| What you still need | Per-user session cookie **and** either per-user brain isolation or a mapping from identity → token/tenant | Same |

Recommended path if you add it:

1. Keep tokens for MCP (agents can’t do browser OAuth cleanly).  
2. Use GitHub/Google only for the **web dashboard** session.  
3. On first login, mint a personal API token the user can copy into MCP.  
4. Later: per-user SQLite DBs or `project` namespaces so tenants don’t share one brain.

**GitHub is the easier first OAuth** for this audience. Google is fine second.
Neither is required for a good first-time experience if `/setup/` issues a
token and asks the user to save it.

## Env knobs

```bash
AGENT_MANAGER_TOKEN=…        # admin token
ALLOW_PUBLIC_SIGNUP=1        # extra people can mint tokens
SETUP_INVITE_CODE=…          # optional gate when signup is open
```
