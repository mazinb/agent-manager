# QUEUE — agents workspace (bot.getzoro.com)

Design: `docs/agents-workspace.md`. Seed: `agents_seed.json`. One item per tick.
Tick job: `agents-workspace-tick` (30m, deliver origin, attach_to_session).

Rules: read the design doc first; work only the next unchecked item; run the
repo tests; commit with `Mazin Biviji <5017609+mazinb@users.noreply.github.com>`
`--no-gpg-sign`, push origin main, verify HEAD == origin/main; restart
`agent-manager.service` and verify `https://bot.getzoro.com/api/ws/agents`
when routes or UI change; record the item, evidence and any deviation here;
never touch the GLM brain or docker containers.

- [x] 1. `agent_context/ws.py`: schema (ws_agents, ws_messages, ws_runs,
      ws_peers), idempotent seed from `agents_seed.json`, CRUD, chat via
      `agent_context/llm.py` + brain config, run records, peer bus, A2A card
      builder. Unit tests in `tests/test_ws.py`.
- [x] 2. Routes in `server.py` (token auth): list, detail (+messages/runs/chips),
      post message (JSON reply for P0), run now (`hermes cron run <job>`),
      runs, patch, peer send, peers list, agent card,
      `/.well-known/agent-card.json`, `POST /a2a` (JSON-RPC message/send).
- [x] 3. UI `/bot/`: agent rail, thread, composer with server chips + ghost,
      runs drawer, peer tab, 390 px mobile, no client-invented chips. Add Bot
      to the nav on home/agents/brain.
- [x] 4. Cron sync: map `source_job_ids` to `~/.hermes/cron/jobs.json`, show
      schedule/last status/next run; Run now verified against a real job.
- [ ] 5. HTTP e2e: script + evidence JSON under `docs/evidence/agents-workspace/`.
- [ ] 6. Browser e2e 390x844: screenshots, no overflow, no console errors,
      real brain reply.
- [ ] 7. README section, measured results, deploy proof, remove this tick.
- [ ] 8. Optional: fold the 04:00 health sweep into the 08:00 audit; then
      overnight LLM runs are zero.

## Tick log

- 2026-11-25 13:0x — queue created; cron audit done (16 -> 11 jobs, five stale
  annual feat jobs removed, ring tick converted to no-agent script, planner
  moved to daily 08:15). Build starts at item 1.
- 2026-11-25 — item 1 done: `agent_context/ws.py` (additive ws_* schema with
  idempotent column migration, seed via `ON CONFLICT(slug) DO NOTHING` so an
  edited prompt survives, list/get/patch, AG-UI-shaped chat through
  `llm.complete` + brain config, run start/finish/record, peer bus with
  `a2a-` task ids mirrored into the target thread, server chips/ghost, agent
  and workspace A2A cards). `tests/test_ws.py` 21 tests green; full suite 126
  green. Evidence: temp-DB smoke against the live brain returned "The default
  brain mode is GLM, served by the GLM TensorFold engine on port 8888" with
  RUN_STARTED/TEXT_MESSAGE_CONTENT/RUN_FINISHED. Deviations: AG-UI events use
  spec camelCase (`runId`, `threadId`); chat runs are recorded with
  `job_id='chat'`; no routes yet, so the service was not restarted.

- 2026-11-25 — item 2 done: `agent_context/ws_routes.py` holds the route logic
  (GET list/detail/messages/runs/card/peers, POST messages/run/to, POST
  peers/read, PATCH agent, A2A message/send, run_cron_job via
  `hermes cron run`) and `server.py` is a thin dispatch: public
  `/.well-known/agent-card.json` and `/api/ws/agents/<slug>/card` before the
  auth gate, every other ws route and `/a2a` after it; new `do_PATCH`; startup
  seeds ws_agents. `tests/test_ws_routes.py` 25 tests green; full suite 151
  green. Evidence: temp instance on :8099 with a temp DB and the repo admin
  token — unauth list 401, well-known card 200 with 8 skills, list 8 agents,
  real brain chat reply (RUN_STARTED/TEXT_MESSAGE_CONTENT/RUN_FINISHED),
  PATCH ok, peer task id `a2a-...`, A2A message/send completed with a real
  Ring Lab reply, bad method -32601, run now on daily-health-digest
  (`3fb498c29968`) succeeded in 6.7s and recorded status ok. Deviations:
  agent cards are unauthenticated for A2A discovery (design said token auth;
  everything else stays token-only); `POST /api/ws/peers/read` added to use
  the existing mark_peer_read; run now blocks until the job ends and returns
  502 with the run recorded as error when it fails; job_id must belong to the
  agent's `source_job_ids`; A2A target agent comes from
  `params.metadata.agent` and returns a Task (completed/failed).

- 2026-11-25 — item 3 done: `static/bot.html` served at `/bot/` (route in
  `server.py`, private no-cache), rail grouped Operations/Labs/On-demand with
  avatar/initial, status dot, schedule + last-run line, thread with grouped
  author labels, composer whose chips and ghost come only from
  `GET /api/ws/agents/<slug>` (`chips.chips` / `chips.ghost`; no hardcoded
  labels), drawer (schedule, source job ids, runs, prompt editor, pause),
  peer tab (list + send via existing `/to`), empty state with three recently
  active, in-page token gate. Mobile: rail-first list, chat-open thread with
  back, drawer as overlay sheet; 390 px is the acceptance width. Bot link
  added to nav on home/agents/inbox/brain. `tests/test_ws_ui.py` 11 tests
  (static contract + live `/bot/` route + unauth 401); full suite 162 green.
  Evidence: temp-config HTTP server served `/bot` and `/bot/` 200 with the
  rail/composer markup; live curl after restart in this tick. Deviation:
  agent groups are a client-side slug map (design groups are presentational;
  the roster API has no group column) — no new schema.

- 2026-11-25 14:5x — item 4 done: `agent_context/cron_sync.py` reads the Hermes
  cron registry read-only (`AGENT_MANAGER_CRON_JOBS` override for tests) and
  maps each agent's `source_job_ids` to schedule, state, last status/time,
  next run and a truncated last error; stale ids are reported as `missing`
  instead of silently dropped, and `count`/`live`/`missing` keep the totals
  honest. `ws.list_agents`/`get_agent` attach `cron`; the status dot goes
  `error` when the newest cron status is an error and newer than the last
  recorded ws run. `/bot/` rail line 2 is now live `next <t> · N jobs`
  (`untilTime`), the drawer Schedule section lists each job with name/id,
  schedule, state, last status, next run and error (no seed schedule text or
  duplicate Source jobs block). `tests/test_cron_sync.py` 17 tests +
  `tests/test_ws_ui.py` 2 new contract tests; full suite 182 green. Live
  evidence after restart: token `GET /api/ws/agents` returns 8 agents with
  cron (health-auditor 5/5 live, next 99eb38de9bb7, last ok), detail lists all
  5 jobs, `POST /api/ws/agents/health-auditor/run` on device-recon
  (99eb38de9bb7, no_agent, deliver local) returned 200, runner rc 0, run
  recorded ok at 14:56, next run advanced to 15:56; `/bot/` 200 serving the
  cron markers. Deviation: schedule strings come verbatim from
  `schedule_display` (some jobs store raw cron exprs, e.g. `0 */6 * * *`); no
  formatting layer added. Run now was verified on the script job rather than
  the LLM digest so no duplicate Telegram delivery was produced.

- 2026-11-25 08:3x — item 5 done: `scripts/ws_e2e.py` (stdlib, token from
  `.env`, never recorded; `--no-writes`/`--run --job-id` flags) runs 17
  acceptance checks and writes `docs/evidence/agents-workspace/
  http-e2e-<ts>.json` + `http-e2e-latest.json`. `tests/test_ws_e2e.py` 7 tests
  green against a stub HTTP server; full suite 189 green. Live run against
  `https://bot.getzoro.com` (token, real writes): 17/17 passed in 7.35s —
  unauth list 401, public well-known + agent cards 200, `/bot/` markers 200,
  list 8 agents, chat reply from the real brain (AG-UI RUN_STARTED/
  TEXT_MESSAGE_CONTENT/RUN_FINISHED), thread persisted, peer task
  `a2a-042d1146...`, A2A `message/send` completed, bad method -32601, run now
  on device-recon `99eb38de9bb7` rc ok. No route/UI change, so no restart;
  service confirmed active and public endpoint answered. Deviations: first
  public attempt hit Cloudflare error 1010 on urllib's default User-Agent, so
  the script sends an explicit UA; evidence from that failed attempt was
  removed. Chat/peer/A2A checks write to the prod thread/bus by design;
  `--no-writes` skips them.
