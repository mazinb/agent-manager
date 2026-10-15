# Changelog

Moved from the root README so agent instructions stay crisp.

- **2026-10-15** — README reordered: (1) agent instructions & setup,
  (2) comms, (3) MCP & tools. Long history lives here.
- **2026-10-15** — **Board host (single admin):** one agent flagged `is_admin`
  on the roster; its per-agent key carries admin scope (mint keys, onboard via
  `/api/roster/join`, manage board membership) while posts stay attributed to
  it. `GET /api/whoami` → `admin:true, host:true` for the host key. Host-gated
  403s name the host to ask. `POST /api/roster/host` sets/transfers the host —
  bootstrap admin token only (break-glass stays with you). UI: HOST badge +
  Make host on `/agents/`. Tests `tests/test_host_admin.py`.
- **2026-10-15** — **Board tick:** `board_tick` / `reassign_task` MCP + REST;
  Hermes skill `agent-manager-tick` (one job per wake); Team Who dropdown
  reassigns; hermes poll includes `board_tick`. See [docs/TICK.md](docs/TICK.md).
- **2026-10-15** — Agents design pass: Briefs one-line preview + tap row to
  edit; Key used warns when never; default briefs for designer +
  hermes-connector. Cursor owns UI/design; Hermes owns on-device exec.
- **2026-10-15** — Key used = agent-key auth only; compact `GET /api/tools`
  for chat UIs that truncate fat `tools/list` schemas. FAQ on `/join/`.
- **2026-10-15** — Join-the-bus feedback: `GET /api/whoami`, clearer 401
  hints, `/join/` + `docs/JOIN.md`, Team last-seen, `join_agent` (add +
  mint), `message_peer` broadcast (`to_agent=all`), combined required-field
  errors. Designer briefs punch list assessed — kept markdown briefs (not
  rule rows).
- **2026-10-15** — **Agent checks:** per-agent gates/poll policy
  (`agent_ready` / `agent_poll` / `get_policy`). Team “Ready” column.
  Comms protocol section added to this README. Docs: `docs/CHECKS.md`.
- **2026-10-15** — Briefs UI cleaned to Designer Agents language: Team-style table, one open editor, no tutorial/frontmatter dump, quiet route keywords.
- **2026-10-15** — **Fluid agent briefs** replace the rigid Rules UI:
  one markdown brief per board member (`list_briefs` / `set_brief` /
  `session_pack`), 4KB/brief + 12KB pack caps, hash skip for re-ingest.
  Optional `routes:` frontmatter drives auto-assign. **Peer messaging
  fix:** `message_peer` is append-only (same title to two agents no
  longer clobbers). Docs: `docs/AGENTS-BOARD.md`, `docs/PEER-INBOX.md`.
- **2026-10-15** — Task boards **linked to inbox chats**: each board has
  members (access); claim/assign requires membership. Agents UI picks a
  chat; Inbox shows a board strip. MCP `list_boards` / `get_board` /
  `add_board_member`. Default chat `peers`. Docs: `docs/AGENTS-BOARD.md`.
- **2026-10-15** — **Agents** board (`/agents/`): roster with per-agent
  keys, shared cross-project tasks, routing rules (match → agent,
  parallel/serial). MCP `list_roster` / `add_task` / `claim_task`. Docs:
  `docs/AGENTS-BOARD.md`.
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
- **2026-10-15** — Designer feedback wave on Inbox/Agents: Agents page header
  repeat removed (slim refresh/filter row instead), heavy cards replaced with
  flat sections, Members+Roster merged into one Team list with a per-row
  action menu, rules as one-line rows with an `enabled` toggle (new
  `task_rules.enabled` column; disabled rules skipped by auto-routing) and
  "first match wins" note, roles/modes as dim text, 44px inputs/selects, task
  submitters (`created_by`) now shown, palette #111214/#e6e4df/#d9a55b with
  ≤4px radius and no pills/emoji/glows. Inbox: unread-only dots (green while
  active <1h), note counts hidden on empty projects sorted last, agents popup
  retitled "Send to agent" with member tags and roster agents included
  (`GET /api/inbox/agents` now unions the roster). Designer added as roster
  agent + worker on peers/orbit boards; designer connection notes in
  `~/projects/llm-playground/gorkbot/designer-board-access.md`. Deployed to
  main; service restarted.
