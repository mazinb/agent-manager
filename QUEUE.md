# QUEUE — agents workspace (bot.getzoro.com)

Design: `docs/agents-workspace.md`. Seed: `agents_seed.json`. One item per tick.
Tick job: `agents-workspace-tick` (30m, deliver origin, attach_to_session).

Rules: read the design doc first; work only the next unchecked item; run the
repo tests; commit with `Mazin Biviji <5017609+mazinb@users.noreply.github.com>`
`--no-gpg-sign`, push origin main, verify HEAD == origin/main; restart
`agent-manager.service` and verify `https://bot.getzoro.com/api/ws/agents`
when routes or UI change; record the item, evidence and any deviation here;
never touch the GLM brain or docker containers.

- [ ] 1. `agent_context/ws.py`: schema (ws_agents, ws_messages, ws_runs,
      ws_peers), idempotent seed from `agents_seed.json`, CRUD, chat via
      `agent_context/llm.py` + brain config, run records, peer bus, A2A card
      builder. Unit tests in `tests/test_ws.py`.
- [ ] 2. Routes in `server.py` (token auth): list, detail (+messages/runs/chips),
      post message (JSON reply for P0), run now (`hermes cron run <job>`),
      runs, patch, peer send, peers list, agent card,
      `/.well-known/agent-card.json`, `POST /a2a` (JSON-RPC message/send).
- [ ] 3. UI `/bot/`: agent rail, thread, composer with server chips + ghost,
      runs drawer, peer tab, 390 px mobile, no client-invented chips. Add Bot
      to the nav on home/agents/brain.
- [ ] 4. Cron sync: map `source_job_ids` to `~/.hermes/cron/jobs.json`, show
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
