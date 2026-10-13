---
name: recipe-loop-ops
description: Use when touching the spark-recipe-loop archive, its nightly eval history, voice-lab eval branches, or VLLM reboot playbooks. Read-only archive guidance; do not re-enable the timer.
---

# recipe-loop ops

## Purpose

Archive of **spark-recipe-loop** — the nightly scoreboard for the Flash coding
recipe (snapshot knobs → measure tok/s → 5-task coding eval on **voice-lab**
against local vLLM). **Retired 2026-09-13**: the 04:00 Asia/Bangkok timer is
now host-cleanup (`projects/scripts/nightly-cleanup`, `host-cleanup.timer`).
The tree is an archive; GitHub `mazinb/spark-recipe-loop` (private) stays.
**Do not re-enable `recipe-loop.timer`.**

## Key paths

- `/home/mazin/projects/recipe-loop/README.md` — authoritative history: branches, tasks 01–05, updates
- `MEMORIES.md` — beliefs, default recipe, Next (the loop **reads**, never overwrites)
- `KNOBS.md` — how to flip each knob · `RESULTS.md` — scoreboard · `VLLM.md` — vLLM reboot playbook (local + `POST https://app.getzoro.com/api/vllm/reset`)
- `docs/REMOTE_ACCESS_SETUP.md` — Cloud Agent SSH (WAN :2222 still blocked; phone/cloud agents use the `cursor-agent-worker.service` My Machines worker in `projects/services`)
- Code: `run.py`, `sweep.py`, `coding.py`, `learn.py`, `verify_ready.py`, `run_nightly.sh`; `eval.yaml`, `config.yaml`, `grid.yaml`; `tasks/*/TASK.md` + `tasks/*/meta.yaml`; `results/`, `sweeps/`, `logs/`, `systemd/`

## Common commands

```bash
python3 verify_ready.py                    # pre-flight
python3 run.py --task 01_clock --no-toks   # smoke, single task, no tok/s
bash run_nightly.sh                        # historical; the timer is retired
python3 sweep.py                           # sweep only tasks with sweep: true (01, 02)
```

## Workflows & invariants (HARD rules)

- **This is an archive.** No new nightly runs; do not re-enable
  `recipe-loop.timer`; the 04:00 slot belongs to `host-cleanup` now.
- Eval **never** leaves voice-lab `main` dirty. Baseline = `main` with a live
  src/tests overlay copied on top; gold for task 05 is branch
  `story-on-device-images` (not an eval start point).
- Per task a fresh worktree/branch `recipe-eval/<stamp>/<task>` is created,
  `check.py` runs, then **worktree + branch are deleted** (1–4 always; 05 too
  unless `keep_branch` is set).
- **Do not `git checkout` an eval branch onto the playground working tree.**
  To try gold on https://app.getzoro.com: checkout `story-on-device-images`
  in voice-lab, `npm run build`, restart `llm-playground`.
- Tasks run easy→hard: `01_clock` (12t, sweep), `02_feedback_area` (16t,
  sweep), `03_page_prompt` (20t), `04_pack_images` (24t), `05_story_images`
  (48t, scored `SCORE n/11`, deadline 600s). 1–4 binary pass/fail; 05 is
  time+quality, not tok/s. **No GPU in any check**; existing
  `npm run test:node` must stay green. `/imagebench` is out of scope for 05.
- Historical gotchas recorded in README: harness caps `eval_parallel` to the
  live `--max-num-seqs`; records `TOOLS:` in transcripts; nudges a write at
  ⅓ turns; 05 gold is **stories only** (Klein default + Krea regenerate).

## Verification

- `verify_ready.py` passes before any eval; smoke run above completes green.
- `RESULTS.md` rows match `results/` artifacts; last recorded nightlies:
  2026-09-12 redo 3/5 @ 34.81 tok/s; live engine 262K×4, MTP 3, accept 2.45.
- If vLLM was left stopped (e.g. by an image bench) follow `VLLM.md` — the
  Sep-3 nightly was skipped exactly because of that.

## Pitfalls

- README's "Updated" sections are history, not active config — the timer is
  dead even though `run_nightly.sh` still exists.
- Don't treat `recipe-eval/*` branches as features to keep; they're
  ephemeral by design.
- Cloud Agent secrets live only in cloud-agent chats; the local chat never
  receives those env vars, and inbound :2222 from Cursor Cloud still cannot
  reach this NAT host.
