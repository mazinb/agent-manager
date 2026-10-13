---
name: photo-lab-ops
description: Use when editing photos with the GIMP/Script-Fu pipeline or running the photo-lab web app. Plan, apply, and verify edits.
---

# photo-lab-ops

## Purpose

GB10 photo-editing lab: a GIMP/Script-Fu batch pipeline (crop, stack,
inpaint, relight) plus a FastAPI web editor served at
https://app.getzoro.com/photolab by the user unit `photo-lab-web.service`
(port 8091). Edits are planned as a step plan, applied deterministically, and
verified with a vision model before/after check.

## Key paths

- `/home/mazin/projects/photo-lab/` — repo root
- `webapp.py` — FastAPI UI/server; `editor.py`; `photo_ops.py`; `apply_ops.py`;
  `stack_plan` — plan format for multi-step edits
- `pipeline/` — `crop.py`, `stack.py`, `inpaint.py`, `relight.py`, `gpu.py`,
  `vram.py`, `jsx.py`
- `gimp_batch`, `scriptfu/` — GIMP AppImage + Script-Fu batch helpers
- `scripts/e2e_vision_check.py`, `scripts/smoke_logging.py`
- `runs/<stamp>/` — per-edit outputs: `result.json`, `step*.png`, `final.png`
- `samples/before_after_demo.jpg`, `tests/`, `PLAN.md`

## Common commands

```bash
# Unit tests (use the Hermes venv python)
/home/mazin/.hermes/venv/bin/python -m unittest \
  tests.test_ops tests.test_parser tests.test_planner tests.test_vram

# After editing the systemd unit
systemctl --user daemon-reload

# Restart / check the web service
systemctl --user restart photo-lab-web.service
curl -s http://127.0.0.1:8091/api/state | jq .

# End-to-end vision check
python3 scripts/e2e_vision_check.py
```

UI: https://app.getzoro.com/photolab (or `:8091` locally).

## Workflows & invariants (HARD rules from README)

- **Never touch the GLM brain** (tensorfold docker `glm53-flash-tf`, `:8888`):
  no stop/pause/docker-rm from any photo job. GPU work fits in the ~40 GB
  left beside the brain (see `pipeline/vram.py`).
- **GIMP AppImage batch can segfault** — `gimp_batch` falls back to Pillow
  automatically; the fallback result is acceptable.
- **GIMP must open on DISPLAY `:1`** (the GUI session) — not headless.
- **TTS/MiniMax stays cold**: do not auto-start `qwen-tts` or `minimax-h3`
  from a photo job (GB10 exclusive-GPU rule; resume never cold-starts TTS).
- Keep `/home/mazin` and `/home/mazin/projects` directories-only; update the
  repo README in the same turn as any behavior or measured-number change.

## Verification

- `tests.test_ops`, `tests.test_parser`, `tests.test_planner`,
  `tests.test_vram` all pass.
- `curl http://127.0.0.1:8091/api/state` returns JSON with current plan/run
  state after a `photo-lab-web.service` restart.
- Every run leaves `runs/<stamp>/result.json` + `final.png`; visual proof via
  `scripts/e2e_vision_check.py` or the before/after demo in `samples/`.

## Pitfalls

- Pillow fallback after a GIMP segfault is expected behavior, not a failure.
- Relight/inpaint are GPU tenants — check free VRAM (`pipeline/vram.py`)
  before launching; never evict the brain.
- `runs/` outputs are per-stamp; don't overwrite a previous stamp's results.
