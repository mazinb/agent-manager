---
name: dwm-eval-ops
description: Use when comparing base Qwen3.6-35B-A3B vs DWM edits on GB10, running a record window, scoring results, or queueing custom prompts. Operates the dwm-eval harness end to end.
---

# dwm-eval ops

## Purpose

Side-by-side comparison of base **Qwen3.6-35B-A3B** against DWM edits built in
`~/dwm-output/` (built 2026-10-11, strength 0.1, plus custom spec edits). A
record window switches the GB10 brain down, serves base + every edit
sequentially on the worker, runs a fixed prompt set + queued customs, scores,
and **always** restores GLM. This is the measurement harness only — it never
decides what happens to the checkpoints.

## Key paths

- `/home/mazin/projects/dwm-eval/record.sh` — orchestrator (run on head)
- `/home/mazin/projects/dwm-eval/eval_client.py` — runs on the worker next to the served model; hits `127.0.0.1:8899/v1/chat/completions`
- `/home/mazin/projects/dwm-eval/score.py` — final-answer-only scoring; writes `<results-dir>/score.json`
- `/home/mazin/projects/dwm-eval/prompts.jsonl` — fixed set, 42 prompts (12 refusal / 12 format / 12 tone / 6 neutral)
- `/home/mazin/projects/dwm-eval/queue.jsonl` — custom prompts queued for the next run (archived into the run dir as `queue-used.jsonl`)
- `/home/mazin/projects/dwm-eval/edits/<name>.json` — custom spec edits `{name, description, positive[], negative[], strength, layer, modules}`
- `/home/mazin/dwm-output/<name>/` — edit outputs; only dirs with a `DONE` marker (plus `edit_meta.json`) get recorded
- `/home/mazin/projects/dwm-eval/results/<run-id>/` — `manifest.json`, one JSON per model, `record.log`, `queue-used.jsonl`
- `/home/mazin/brain/brain-switch.sh`, `/home/mazin/brain/queue_cli.py`, `/home/mazin/brain/queue-run.sh` — brain switch + unified job queue (see `~/brain/README.md`)
- Web page: `https://app.getzoro.com/dwm` (route in `~/projects/voice-lab`, llm-playground :8090; display only)

## Common commands

```bash
DRY_RUN=1 bash ~/projects/dwm-eval/record.sh        # no-op check, no switching/serving
bash ~/projects/dwm-eval/record.sh                  # full window (~45–60 min for 42 prompts x models)
python3 ~/projects/dwm-eval/score.py results/<run-id> [more-dirs...]
# queue a custom prompt set through the unified brain queue (canonical runner):
python3 ~/brain/queue_cli.py add --type custom-prompt-set --by hermes --prompts-file <file>
#   or --type record-prompts for a plain run; then launch the single runner:
setsid nohup bash ~/brain/queue-run.sh &
bash ~/projects/dwm-eval/sweep_s05s10.sh            # strength sweep (s05/s10) — uses ONLY= filter
```

## Workflows & invariants (HARD rules)

- **Mazin approves a window.** The agent goes dark while the mini brain / GLM
  is down; never start a record run without that approval.
- `record.sh` does **NO mini brain**: `brain-switch.sh stop` (GLM fully down)
  and `brain-switch.sh glm` restore in an **EXIT trap — even on failure**. Any
  manual variant must preserve that guarantee; never leave GLM down.
- Model mounts on the worker are **read-only**; served with
  `vllm/vllm-openai:v0.28.0` on the worker, models in turn.
- Model set is **dynamic**: base + EVERY `/home/mazin/dwm-output/*` dir with a
  `DONE` marker; custom edits are recorded automatically.
- **Never deploy, serve, upload, or publish** anything the pipeline produced —
  that decision belongs to the operator alone. The /dwm page only *displays*.
- `queue.jsonl` is fed by the unified brain queue since 2026-10-11;
  custom-prompt-set jobs write it from `~/brain/queue_prompts/<id>.jsonl`,
  record-prompts jobs clear it. `queue_run.sh` here is a **legacy** helper.
- `vllm-text` is retired; :8000 stays free for experiments (GB10 GPU rule).

## Verification

- `DRY_RUN=1` first; it must run to completion without switching brains.
- After a window: `manifest.json` present, one JSON per served model
  (incl. `done-<model>.json` snapshots and per-model `strengths`),
  `record.log` shows the EXIT-trap restore to GLM, `brain-switch.sh status` = glm.
- `score.py <run-dir>` prints per-tag final-answer stats and writes `score.json`.
- The /dwm page reflects the latest `results/<run>/`.

## Pitfalls

- Edits without a `DONE` marker are skipped silently — a 2026-10-12 sweep log
  shows `brief_answer_style_s05/s10` and others skipped for exactly this.
- `record.sh.bak-2315` is a stale backup; do not run or edit it.
- `eval_client.py` hardcodes worker paths `/tmp/dwm-eval/{prompts,custom}.jsonl` —
  it is staged on the worker by `record.sh`, not run from the repo directly.
- A window is 45–60+ min of GLM downtime; do not schedule other GPU work
  inside it.
