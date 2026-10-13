---
name: jev-playground-ops
description: Use when running or debugging the Jev playground (TypeSafe SystemOne + local Laya) on port 8135. Operate jev-playground.
---

# jev-playground-ops

## Purpose

Jev playground — a FastAPI service (`serve.py`) exposing TypeSafe SystemOne
calls through `jev_client.py` (validation + gates) and a local Laya lane via
`laya_client.py` (english / typed-decisions lanes). Runs on
`127.0.0.1:8135` as the user unit `jev-playground.service`; the
`llm-playground` Cloudflare tunnel routes https://app.getzoro.com/jev to it.
Single-file UI at `ui/index.html` (no build step).

## Key paths

- `/home/mazin/projects/jev-playground/` — repo root
- `serve.py` — FastAPI app (routes under `/jev`, static UI, run log)
- `jev_client.py` — TypeSafe SystemOne call, validation, gates
- `laya_client.py` — local Laya lane client
- `models/laya/` — downloaded checkpoints (weights git-ignored)
- `scripts/fetch-laya.sh`, `scripts/bench-laya.py`
- `templates.json` — example library; `ui/index.html`; `systemd/jev-playground.service`
- `runs/` — `request.json`, `response.json`, `last_run.json`, `history.jsonl` (git-ignored)

## Common commands

```bash
# Service (user unit; runs uvicorn serve:app on 127.0.0.1:8135 from its own .venv)
ln -sf ~/projects/jev-playground/systemd/jev-playground.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now jev-playground
systemctl --user restart jev-playground
curl -s http://127.0.0.1:8135/jev/api/health | jq .

# Laya checkpoints + bench
bash scripts/fetch-laya.sh
.venv/bin/python scripts/bench-laya.py

# CLI clients (see --help for flags)
.venv/bin/python jev_client.py ...
.venv/bin/python laya_client.py ...
```

Health fields: key configured? templates; `laya_installed`; `laya` device
status (`cuda` expected — the unit sets `LAYA_DEVICE=cuda` and
`LAYA_PRELOAD=english` so CUDA is claimed before other GPU tenants at boot;
`USE_TF=0`). `/` and `/jev` redirect to `/jev/`.

## Workflows & invariants (HARD rules from README "Usage rules")

- **noul targets `[[label]]`** — bracket syntax for labels.
- **choice/score: one subject per call.**
- **No arithmetic in prompts** — compute in code, pass results in.
- **Label every fact** — attach source labels to statements.
- Gates: score **≥ 0.90** auto-approve, **0.60–0.90** human review,
  **< 0.60** escalate.

## Verification

- `systemctl --user status jev-playground` → active; unit runs from the
  project's own `.venv` (`Restart=on-failure`, `RestartSec=2`).
- `GET /jev/api/health` → `laya_installed: true`, `laya.device: cuda`.
- Public URL: https://app.getzoro.com/jev (via the `llm-playground` tunnel).
- Latest run artifacts under `runs/last_run.json`; append-only
  `runs/history.jsonl`.

## Pitfalls

- **CPU fallback sticks for the process lifetime**: if health shows
  `laya.device: cpu` (CUDA OOM at load), the fix is restarting the unit once
  CUDA is free — never by stopping the GLM brain.
- Laya needs ~2–3 GiB beside the GLM brain; it preloads `english` at startup
  to claim CUDA before other tenants boot.
- `models/laya/` weights and `runs/` are git-ignored — don't commit them.
- Keep `/home/mazin` and `/home/mazin/projects` directories-only; update the
  repo README in the same turn as any behavior change.
