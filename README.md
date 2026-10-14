# Zoro (agent-manager)

Shared brain for coding agents — MCP + HTTP. UI brand: **Zoro**.

Ingest project docs, rules, memories, and live services into a local knowledge
graph. Agents can **search**, **ask** (cited answers), pull **context packs**,
and **save notes** so the next session starts with memory.

Self-hosted. Stdlib-only Python. One process.

**Live:** [bot.getzoro.com](https://bot.getzoro.com)

| Path | Purpose |
|---|---|
| [`/`](https://bot.getzoro.com/) | Public landing |
| [`/inbox/`](https://bot.getzoro.com/inbox/) | Inbox (token onboarding if needed; `/setup/` still works) |
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
  --agent vscode \
  --project my-repo
```

`--project` pins a default project: the written MCP URL carries `?project=`,
so `search`/`ask` are scoped to that repo's slice. Cross-project lookups are an
explicit opt-in (omit the pin or pass `project: null`), never the default —
one agent never leaks context into another repo.

### Trust model (memory you can check)

Agent-written notes are not facts — they carry provenance:

- **confidence** (0–1) and **based_on** source paths, set when the agent writes
  a note (`note --confidence 0.9 --sources docs/README.md`).
- **Stale**: if a based-on source changes or is deleted, dependent notes are
  flagged and excluded from search, answers, and context packs by default
  (`include_stale: true` opts back in). The MCP `search`/`ask` tools and the
  Brain page expose `stale`, `confidence`, and last-verified time on every
  result, so stale memory can't quietly influence decisions.
- Notes live only in the DB — refresh never wipes them, and a refresh that
  changes sources marks derived notes stale instead of silently keeping them.

Self-host:

```bash
npx --yes agent-manager-brain init
npx --yes agent-manager-brain serve
# open http://127.0.0.1:8075/setup/
```

Full platform steps: **[docs/CONNECT.md](docs/CONNECT.md)**.

### npm ↔ repo sync

The npm package is a thin wrapper — `serve`/`init`/`setup` clone this repo at
runtime, so brain features always come from GitHub and can't go stale. Only
`npm/cli.js`, `npm/README.md` and the API routes the CLI calls are frozen at
publish time. Check drift any time with:

```bash
scripts/npm-sync-check.sh   # exit 0 = in sync, 1 = republish needed
```

It diffs the published tarball against `npm/` and verifies every CLI-called
endpoint still exists in `server.py`. Republish only when it says so:

```bash
# bump "version" in npm/package.json, commit, then:
cd npm && npm publish
```

## Changelog

- **2026-10-15** — Connect UX: fixed (non-editable) brain URL, create /
  view-once token, agent grid + custom add. Commands redact the token on
  screen; copy/deeplink still carry it. Shorter edge cache so phones update.
- **2026-10-15** — Cursor↔Hermes loop on peers bus: plan → handoff →
  supervise (`docs/PEER-INBOX.md`, `scripts/peer.sh`). Hermes skill updated.
- **2026-10-15** — UI rebrand **Zoro**: one shared 48px header on Home /
  Inbox / Connect / Brain (no chrome hop). Minimal copy.
- **2026-10-15** — Nav/URL say **Inbox** after login (`/inbox/` alias;
  `/setup/` still serves the same page and rewrites the path once a token
  is present).
- **2026-10-15** — Peer inbox (simpler than A2A): MCP `message_peer` /
  `peer_inbox` + `GET /api/inbox/messages` on the shared `peers` bus. Prefer
  this for agent coordination; keep A2A only for sync workers. Docs:
  [`docs/PEER-INBOX.md`](docs/PEER-INBOX.md). 3 new tests (43 total).
- **2026-10-15** — Grok-style multi-agent inbox: `/setup/` is a per-project
  chat (project list → thread). Notes carry `agent` / `to_agent` (MCP `note`
  tool + columns); threads render centered **Messaged ● peer** lines between
  bubbles. `GET /api/inbox/projects` + `GET /api/inbox/agents` feed the list
  and the agents overlay menu. Mockup at `docs/mockups/inbox-chat.html`.
  4 new tests (40 total).
- **2026-10-14** — One-click connect: `/connect/` now carries real Cursor
  (`cursor://anysphere.cursor-deeplink/mcp/install`) and VS Code
  (`vscode:mcp/install`) install links built client-side from the saved
  token — no terminal. Links fall back to `/setup/` until a token exists.
- **2026-10-14** — Setup tab becomes the Inbox once a token is saved: notes
  list with project / AI-vs-Human / confidence / stale / ✓-age badges, tap to
  edit inline (human edits badged `origin: human`), New-note form. New
  `GET /api/inbox` (token-auth), `origin` column + `store.list_notes()`,
  `origin` param on the note tool. Optional GitHub sign-in (`read:user` only,
  read-only — public profile, token discarded after login, mints the same API
  token; enable with `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET` in `.env`,
  callback `/api/auth/github/callback`). 11 new tests (36 total).
- **2026-10-14** — Connect page is edge-static: inlined CSS (no second
  Spark hop for `/static/app.css`), `Cache-Control` so Cloudflare can
  serve `/connect/` without the tunnel, one-click Cursor CTA + secondary
  agents under a details panel. Setup/home/css get the same edge cache.
- **2026-10-14** — Brain chrome snappy pass: sticky header+tabs+per-tab
  controls (no layout hop on load), parallel boot, Packs auto-load on
  select, plain private/public toggle (no emoji). **Bugfix:** POST
  `/api/project/visibility` was unreachable (404) because the do_POST
  allowlist omitted it — toggle is live again. 25 tests green.
- **2026-10-14** — Reddit feedback wave 1 (r/mcp): trust metadata on notes
  (confidence, based_on, verified_at, content_hash), source-change
  invalidation (stale notes excluded from search/ask/packs, opt-in
  `include_stale`), per-project scoping (`connect --project` pins `?project=`
  on the MCP URL; `project=` accepted by search/ask + REST), provenance badges
  in the Brain page UI. npm 0.3.4 (CLI: `--project`, `--include-stale`,
  note `--confidence`/`--sources`). Tests: 16 green. Deployed; service restarted.
- **2026-10-14** — Brain page visual restyle: plain list rows with dividers, no
  emoji, monospace identifiers, markdown rendering in Mentions/Ask, additive
  `mentions` count in `GET /api/entities`. Deployed to main; service restarted.

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
