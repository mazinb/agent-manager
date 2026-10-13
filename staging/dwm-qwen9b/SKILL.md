---
name: dwm-qwen9b-ops
description: Use when running or monitoring a DWM pipeline run for Qwen 9B on the GB10/worker pair, operating the orchestrator, or reading run state. Treats the three dwm-qwen9b dirs as one project.
---

# dwm-qwen9b ops (runbook + ops + run = one project)

## Purpose

Build a DWM (Domain Weight Modification, Blackfrost_AI) candidate for the
**Qwen3.5-9B** checkpoint: soften over-tightened guardrails via a frozen
32-pair bank + norm-preserving rank-1 edits — **not** ablation, never
deploying anything. The pipeline is fail-stop; the orchestrator runs the
whole creative stack in one go (brains down → mini brain → tunnel → run →
restore), while Telegram gets every stage event.

## Key paths

- `/home/mazin/projects/dwm-qwen9b/` — the runbook package: `START-HERE.md` (orientation + hard rules), `RUNBOOK.md` (stages 0–8), `METHOD-OVERVIEW.md`, `REPORT-TEMPLATE.md`, `run_dwm.py` (fail-stop pipeline), `lib/dwm_core.py` (pure math, `--self-test`), `pairs/dwm-32pair-bank.jsonl` (SHA-pinned), `config/pinned-parameters.json`
- `/home/mazin/projects/dwm-qwen9b-ops/` — `orchestrator.sh` (fail-forward stack), `cron_monitor.sh`, `watcher.sh`, `event_fmt.py`, `notify.py` (Telegram, token read from `~/.hermes/`-style env file — never echoed), `orchestrator.log`, `failed-attempt-1/2/`
- `/home/mazin/projects/dwm-qwen9b-run/` — the pipeline workdir: `preflight.json`, `events.jsonl`; end markers `REPORT.md` (success) / `FAILURE.json` (fail). Must be **empty** before a run
- Source checkpoint: `/home/mazin/projects/dwm-qwen9b-ckpts/Qwen3.5-9B`; pre-staged on worker at `/home/mazin/models/Qwen3.5-9B-exl3-4bpw`
- Worker: `mazin@192.168.10.2` (BatchMode ssh); Hermes endpoint stays `192.168.100.1:8888`

## Common commands

```bash
# runbook package (can run on either GPU node)
python3 run_dwm.py --self-test    # must print PASS (8 checks, no GPU)
python3 run_dwm.py --source /home/mazin/projects/dwm-qwen9b-ckpts/Qwen3.5-9B \
  --workdir /path/to/EMPTY/output_dir

# whole stack (head)
nohup bash /home/mazin/projects/dwm-qwen9b-ops/orchestrator.sh >> orchestrator.log 2>&1 &
bash /home/mazin/projects/dwm-qwen9b-ops/cron_monitor.sh    # deterministic state read
tmux attach -t dwm-run                                      # live pipeline
python3 /home/mazin/projects/dwm-qwen9b-ops/notify.py "msg"
```

## Workflows & invariants (HARD rules)

- **7 hard rules** live in `START-HERE.md` — read it first, then `RUNBOOK.md`;
  an agent can run end-to-end from those two alone. Pipeline is fail-stop:
  any gate failure halts and writes `FAILURE.json`; frozen inputs are
  SHA-pinned and a run refuses to start on drifted inputs; every edited
  matrix is restored to its pre-edit Frobenius norm (tol 0.2%), verified
  tensor-by-tensor; **the pipeline never deploys** — serving/publishing is
  explicitly out of scope.
- **The orchestrator's brain stop is a user-approved exception.** It stops
  `glm53-flash-tf` on head AND worker (graceful, `-t 60`), aborting — brains
  left UP — if the worker checkpoint is incomplete or the workdir is not
  empty. On REPORT/FAILURE/exit/14h timeout it tears down the mini brain +
  tunnel and restarts the brain on both nodes, then verifies `/health`.
- Mini brain: `glm-mini-brain` docker (tensorfold-glm53:v0.6.0,
  `Qwen3.5-9B-exl3-4bpw`, worker :8899) + ssh tunnel
  `192.168.100.1:8888 → worker:8899` so Hermes notices nothing.
- `dwm-qwen9b-run/` must stay empty between runs; `events.jsonl` lines are
  pushed to Telegram by the LLM-free `watcher.sh` (`.watcher_stop` sentinel).
- `cron_monitor.sh` is deterministic: identical output between ticks skips
  the LLM run entirely (no timestamps).
- Outside an approved DWM window the GB10 rule holds: the GLM brain is never
  stopped; `vllm-text` is retired; :8000 stays free.

## Verification

- `run_dwm.py --self-test` → `PASS` (8 checks) before any run.
- `cron_monitor.sh` prints STATE=NOT_STARTED/RUNNING/FAILED/COMPLETE;
  completion = `REPORT.md` per `REPORT-TEMPLATE.md`.
- After a window: `docker ps` shows `glm53-flash-tf` on both nodes and
  `/health` 200 on :8888; no leftover `glm-mini-brain` or tunnel ssh.
- Norm checks pass per round in `events.jsonl` (`gate-pass` events).

## Pitfalls

- Workdir not empty → ABORT (brains left up). Check before relaunching.
- `failed-attempt-1/` and `failed-attempt-2/` hold post-mortems — read before
  re-running after a failure.
- If the mini brain fails to boot, Hermes is offline for the run; the raw
  Telegram watcher still works. Don't "fix" by keeping GLM down.
- The pipeline runs with `CUDA_VISIBLE_DEVICES=0` from
  jev-playground's venv in tmux session `dwm-run`.
