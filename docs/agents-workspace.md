# Agents workspace at bot.getzoro.com

2026-11-25. Status: shipped (queue items 1-7 done; optional item 8 open).

## 1. Why

There are 16 enabled Hermes cron jobs, several of them LLM runs overnight, and no
single place to see what ran, what it found, or to talk to the thing that owns a
domain of work. Telegram is the delivery channel, not a workspace.

The ask: an OpenBot-style workspace, on the domain we already own, with a
Grok-bot-like interface: organized agents, each with a chat, a schedule, run
history, and a way for agents to talk to each other. Web app only, no native app.

## 2. Decision

Build the workspace **inside agent-manager** (`~/projects/agent-manager`,
`bot.getzoro.com`, `agent-manager.service`). Do **not** deploy the OpenBot stack
(Next.js + Postgres + OAuth + Kubernetes-shaped runtime): this box already has
the rails we need — token auth, roster, boards, inbox, a shared `brain.db`, and
a local OpenAI-compatible brain at `127.0.0.1:8888/v1`.

Adopt the protocols OpenBot is built on instead of its deployment:

- **AG-UI** (MIT, CopilotKit) for the agent-to-user chat surface. Event-shaped
  stream: `RUN_STARTED`, `TEXT_MESSAGE_CONTENT`, `RUN_FINISHED`.
- **A2A** (Linux Foundation, production standard since 2026) for agent-to-agent
  messages: JSON-RPC 2.0 `message/send`, agent cards at
  `/.well-known/agent-card.json` and `/api/ws/agents/<slug>/card`.

Both are open standards, not a framework runtime. The existing peers bus stays
as the human-visible inbox; A2A is the wire shape for agent-to-agent calls.

## 3. UX

New page `/bot/`, linked from the top nav as **Bot**, and eventually the landing
page. Grok-bot layout, dark, mobile-first (390 px baseline):

- Left rail: agents with avatar/initial, name, status dot (idle/running/error),
  last-run time, schedule badge. Grouped: Operations, Labs, On-demand.
- Main: selected agent's thread. Composer with server-composed chips:
  `Run now`, `Schedule`, `Open inbox`, `Last run`, plus one suggested question.
  A ghost prompt shows the top suggestion; Enter sends, chips fill.
- Right drawer (collapsible on mobile): schedule, source cron job ids, last runs
  with status/summary, "Edit prompt" and "Pause".
- Peer bus tab inside the same page: agent-to-agent messages, each row showing
  from → to, body, and the A2A task id.
- Empty state: "Pick an agent" plus the three most recently active.

No client-invented chips: the server returns the chips and the ghost.

## 4. Data model (brain.db, additive)

```sql
ws_agents(id TEXT PK, slug TEXT UNIQUE, name TEXT, purpose TEXT,
          avatar TEXT, color TEXT, system_prompt TEXT, model TEXT,
          schedule TEXT, enabled INTEGER, source_job_ids TEXT,
          tools_json TEXT, created_at REAL, updated_at REAL)
ws_messages(id INTEGER PK, agent_id TEXT, role TEXT, body TEXT,
            run_id TEXT, task_id TEXT, peer_from TEXT, created_at REAL)
ws_runs(id TEXT PK, agent_id TEXT, job_id TEXT, started_at REAL,
        ended_at REAL, status TEXT, summary TEXT)
ws_peers(id INTEGER PK, from_agent TEXT, to_agent TEXT, body TEXT,
         task_id TEXT, created_at REAL, read_at REAL)
```

Seeded agents live in `agents_seed.json`; seeding is idempotent and never
overwrites an edited prompt. All rows are single-user (`mazin`), token-scoped.

## 5. Endpoints

All under the existing token auth (`X-Token` or `Authorization`), same as
`/api/roster/*`.

```
GET    /api/ws/agents                  list + status + last run + schedule
GET    /api/ws/agents/<slug>           agent + recent messages + runs + chips
POST   /api/ws/agents/<slug>/messages  {body} -> AG-UI events (SSE) or JSON
POST   /api/ws/agents/<slug>/run       trigger source cron job (hermes cron run)
GET    /api/ws/agents/<slug>/runs      run history
PATCH  /api/ws/agents/<slug>           name/purpose/prompt/schedule/enabled
POST   /api/ws/agents/<slug>/to        {to, body} -> peer bus + A2A task id
GET    /api/ws/peers                   peer bus, newest first
GET    /api/ws/agents/<slug>/card      A2A agent card
GET    /.well-known/agent-card.json    workspace card
POST   /a2a                            JSON-RPC message/send -> target agent
```

Chat replies come from the local brain with the agent's system prompt plus the
last 12 messages; tools stay with scheduled Hermes runs, so the chat is honest
about what it can and cannot do (a chip can trigger the real run).

## 6. Agents

| slug | name | owns | cron mapping |
|---|---|---|---|
| health-auditor | Health Auditor | overnight health-ops sweep, device audit, steps/digest, device recon | 2d5f972a5570, 8dc816b7ce57, b2d2e122e1af, 3fb498c29968, 99eb38de9bb7 |
| ring-lab | Ring Lab | ring field experiments, battery legs, cowear, evidence | 49658b15c04e, 389413c422fa, c0bd1d410103, 8d1cd6380719, 606d5b7aadb0 |
| ship-watch | Ship Watch | iOS/Mac builds, TestFlight, Xcode checks | 4bda9d296751 |
| coach-builder | Coach Builder | coach specs, builder, chip rail, decision rules | on-demand |
| brain-ops | Brain Ops | GLM/Hy4 modes, brain health, throughput | on-demand |
| dwm-lab | DWM Lab | DWM pipeline progress | dwm-progress-check (paused) |
| voice-lab | Voice Lab | TTS, kids story, voice tutor | on-demand |
| scout | Scout | research, competitor/news, grok-bot scout | on-demand |

System prompts are short and scoped: who you are, what you own, what you can
answer from memory, when to say "trigger a run", no em dashes, no secrets.

## 7. Cron audit outcome (2026-11-25)

Enabled jobs: 16 -> 11. Removed five stale annual `feat1..feat5` jobs (next run
2027-11-10). Converted `ring-experiment-tick` from an agent run that only
executed a script to a no-agent script job. Moved `ring-experiment-planner` from
every 6 h to daily 08:15. Overnight LLM runs drop from five to one (the 04:00
health sweep); remaining overnight jobs are scripts (00:05 steps, 03:30
TestFlight gate, 21:00 evidence, 21:30 digest, 23:51 cycle watch).

Open: fold the 04:00 sweep into the 08:00 audit after the workspace ships; then
overnight LLM runs are zero.

## 8. Acceptance (P0)

- `curl` against `127.0.0.1:8075` with a token: list agents, open one, post a
  message, get a real brain reply, trigger a run, fetch an A2A card.
- Browser at 390x844: rail renders 8 agents, chat sends and receives, chips
  render server-side, ghost fills without auto-send, no horizontal overflow,
  no console errors. Screenshots in `docs/evidence/agents-workspace/`.
- `agent-manager` full pytest suite green; service restarted; `/api/ws/agents`
  live on `https://bot.getzoro.com`.
- README section and this doc updated with the measured result.

## 9. Non-goals

No OpenBot deployment, no Postgres, no OAuth, no native app, no per-agent
vector memory, no autonomous tool use in chat (scheduled runs keep tools).

## 8. Measured results and deploy proof

Shipped 2026-11-25. The numbers below are from real runs against
`https://bot.getzoro.com`, not estimates; the raw records sit in
`docs/evidence/agents-workspace/` and never contain the token.

| Check | Result |
|---|---|
| Repo tests | 224 green (`python3 -m unittest tests.test_*`) |
| HTTP e2e | 17/17 checks in 7.35 s (`scripts/ws_e2e.py`) |
| Browser e2e | 13/13 checks in 48.6 s at 390x844 (`scripts/ws_browser_e2e.py`): 8-agent rail, live cron next-run lines, DOM chips == server payload, ghost fill without send, real brain reply persisted, peer tab, zero horizontal overflow, zero console errors |
| Deploy proof | `scripts/ws_deploy_proof.py` records service state, HEAD vs origin/main, endpoint codes, latest evidence and the test suite into `deploy-proof-latest.json` |

Deploy proof covers: `agent-manager.service` active; HEAD == origin/main with a
clean tree; `/api/ws/agents` 401 without a token and 200 with 8 agents; `/bot/`
200 with the rail/composer/token-gate markers; `/favicon.ico` 204 before the
auth gate; `/.well-known/agent-card.json` 200 with skills.

Screenshots: `browser-e2e-latest-rail.png`, `browser-e2e-latest-chat.png`.

The build tick (`agents-workspace-tick`, every 30 m) was removed after item 7
landed; item 8 stays optional and needs no scheduler — fold the 04:00 health
sweep into the 08:00 audit by editing the two cron jobs once.
