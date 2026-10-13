---
name: llm-playground-ops
description: 'Use when editing the legacy playground, Cloudflare tunnel ingress, gorkbot A2A, brain-swap, or DWM experiments. Treat it as legacy; verify routes.'
---

# llm-playground — legacy playground + shared tunnel infra

## Purpose

**Legacy.** The live UI for app.getzoro.com is `../voice-lab` (Next.js,
:8090). This repo keeps the old Python server (`server.py`), static try-it
page, review inbox (`data/review_inbox.jsonl`), and — critically — the
**shared Cloudflare tunnel config** plus sub-experiments (gorkbot A2A,
brain-swap, DWM).

## Key paths

- `cloudflared/config.yml` — named tunnel ingress (used by
  `cloudflared-llm-playground.service`; tunnel ID `62a97d2f-59b8-43ca-afd8-c6f4f77829cf`)
- `gorkbot/` — Hermes A2A server: `INSTRUCTIONS.md`, `ACCESS-SETUP.md`,
  `verify_a2a.py`, `a2a-token.txt` (**secret** — never print its value), `models/`
- `brain-swap/` — GLM ⇄ mini brain scripts (`swap-to-glm.sh`, `swap-to-mini*.sh`,
  `agent-swap-to-{glm,mini}.sh`, `gpu-report.sh`) + logs
- `dwm/` — DWM experiment, **paused**; findings + restart checklist in
  `dwm/FINDINGS.md`; `scripts/context_benchmark.py`
- `start.sh` — *quick*-tunnel launcher (requires vLLM answering on :8000 —
  legacy; brain now lives on :8888)

## Ingress map (cloudflared/config.yml)

| Route | Origin |
|---|---|
| `app.getzoro.com` `^/photolab` | 127.0.0.1:8123 |
| `app.getzoro.com` `^/portfolio` | 127.0.0.1:8134 |
| `app.getzoro.com` `^/health` | 127.0.0.1:8136 |
| `app.getzoro.com` `^/jev` | 127.0.0.1:8135 |
| `app.getzoro.com` default | 127.0.0.1:8090 (voice-lab) |
| `portfolio.getzoro.com` | 127.0.0.1:8134 |
| `health.getzoro.com` | 127.0.0.1:8136 |
| `gorkbot.getzoro.com` | 127.0.0.1:9900 (Hermes A2A in hermes-gateway) |
| `ssh.getzoro.com` | ssh://localhost:22 |
| everything else | 404 |

Protocol is `http2` + `edge-ip-version: 4` — QUIC dropped ("no recent network
activity", 502s) while :8090 stayed 200. Unit has `OOMScoreAdjust=-500`.

## Common commands

```bash
systemctl --user status cloudflared-llm-playground
cloudflared --config /home/mazin/projects/llm-playground/cloudflared/config.yml ingress validate
curl -s http://127.0.0.1:9900/.well-known/agent.json       # A2A agent card
python3 /home/mazin/projects/llm-playground/gorkbot/verify_a2a.py
cat /home/mazin/projects/llm-playground/brain-swap/gpu-report.sh   # read before running
```

## Workflows & invariants (HARD rules)

- **Never point systemd back at the old Python server** unless deliberately
  rolling back.
- Tunnel edits: change `config.yml`, validate, restart the unit; append a
  dated `Updated **YYYY-MM-DD**:` row to README.md (2026-10-05 was the last).
- `config.yml.bak.*` files are deliberate — keep the latest backup before editing.
- gorkbot auth: A2A token lives in `gorkbot/a2a-token.txt`; reference the path,
  never echo the value. Without the token SendMessage must 401.
- A2A verified end-to-end on Hermes v0.21.6 (`~/.hermes/hermes-agent`):
  agent card 200 local+public, authenticated SendMessage PASS.
- DWM stays paused unless the user re-arms it — follow `dwm/FINDINGS.md`
  restart checklist; GLM brain must be restored on head :8888 afterward.
- brain-swap scripts touch GPU containers — read `gpu-report.sh` output and
  never swap while a job is in flight.

## Verification

- `cloudflared ingress validate` after any config.yml edit.
- After ingress change: curl each hostname/path through the public URL.
- A2A: agent card 200 via :9900 and via `gorkbot.getzoro.com`; 401 without token.

## Pitfalls

- `start.sh` hard-fails if nothing answers on :8000 — legacy assumption;
  :8000 is now free and the brain is on :8888.
- The named tunnel carries *everyone's* routes (portfolio, health, jev,
  photolab, gorkbot, ssh) — a bad edit takes down unrelated services.
