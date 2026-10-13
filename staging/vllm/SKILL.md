---
name: vllm-ops
description: 'Use when touching the vLLM model hub, weights, or running token-throughput load tests. Keep hub layout intact and benchmark honestly.'
---

# vllm — model hub + load testing (incl. vllm-loadtest)

## Purpose

`/home/mazin/projects/vllm/` is the local HuggingFace-style hub mounted into
the vllm Docker container as `/models` (`HF_HOME=/models`) so inference runs
with `HF_HUB_OFFLINE=1` and never re-downloads tens of GB.
`/home/mazin/projects/vllm-loadtest/` is the closed-loop token-output load
test harness against the local vLLM OpenAI server.

## Key paths

- `vllm/hub/` — cached snapshots (`models--…`); container path layout matters
- `vllm/bench/` — bench JSON + reports (e.g. `token_throughput_concurrency_20261010*.json`)
- `vllm/miaai-spark/` — MiaAI recipe patches
- `vllm-compile-cache/` (sibling) — compile / autotune caches belong here
- `vllm-loadtest/scripts/` — `check_health.sh`, `run_single_user.sh`, `run_concurrency_sweep.sh`, `run_vllm_official_bench.sh`
- `vllm-loadtest/config.yaml`, `prompts/default.json`, `results/`

## Current serving state

- Brain: **GLM-5.3-Flash-EXL3** via docker `glm53-flash-tf` on **:8888**
  (tensorfold, 4bpw EXL3 + DFlash2, TP=2, 1M ctx) — never stopped. Server-side
  thinking defaults ON; send `chat_template_kwargs: {"thinking": false}` for
  clean content.
- `vllm-text` is **retired**; `:8000` is free for experiments (loadtest, bench).
- Active hub models: `drowzeys/keys-Qwen3.8-flash-next-ablit-Mia-Single-Spark-only`
  (legacy Keys ABLIT), `Qwen/Qwen-Image` + Lightning, `Qwen/Qwen3-TTS-12Hz-1.7B-Base`.

## Common commands

```bash
curl -sf http://127.0.0.1:8888/health                       # brain
cd /home/mazin/projects/vllm-loadtest
./scripts/check_health.sh
./scripts/run_single_user.sh
./scripts/run_concurrency_sweep.sh                          # 1→5 users
./scripts/run_concurrency_sweep.sh --quick                  # smoke: 64 tok, 4 req/level
./scripts/run_concurrency_sweep.sh --max-tokens 512 --requests 20
./scripts/run_concurrency_sweep.sh --thinking               # production-like chat profile
./scripts/run_concurrency_sweep.sh --shared-prompt          # enable prefix-cache sharing
docker exec vllm ... run_vllm_official_bench.sh 2 12 256 256   # cross-check, in container
```

Env overrides: `VLLM_BASE_URL` (default `http://127.0.0.1:8000`),
`VLLM_MODEL`, `VLLM_MAX_TOKENS`.

## Workflows & invariants (HARD rules)

- **Do not reorganize `vllm/hub/` casually** — the container path layout matters.
- Compile/autotune caches go in `vllm-compile-cache/`, never inside the hub.
- Launch vLLM via `../services/` scripts (systemd), never a hand `docker run`
  (a helper crash-looped `vllm-text` with invented flags that way).
- After reboot: `services/enable-ple-swap.sh` first, then serve, then
  `services/warmup-vllm.sh` (must pong).
- Loadtest methodology invariants: baseline `c=1` first; change one variable at
  a time; closed-loop (`request-rate inf`), not open-loop QPS; stream every
  request; count **server tokens** (`stream_options.include_usage`), never
  words; `ignore_eos=true` + fixed `max_tokens`; discard warmup; report
  percentiles + SLO goodput, not means; unique prefixes by default;
  thinking off for token tests.
- Bench results append to `vllm/README.md` dated, JSON under `vllm/bench/`
  (global rule `keep-root-clean-and-readmes.mdc`).
- Never touch the brain container (`glm53-flash-tf`) for any bench/TTS/image job.

## Verification

- `check_health.sh` or `curl -sf http://127.0.0.1:8000/health` before a sweep.
- Each sweep writes `results/sweep-*.json|csv|md` + `latest.json` — confirm
  files landed before quoting numbers.
- Confirm live container args after any restart (spec-decode N, batched tokens).

## Pitfalls

- Default 64K×4 / long-context 262K×1 is a unit-file env change
  (`MAX_MODEL_LEN`, `MAX_NUM_SEQS`) + `daemon-reload`, not a script edit.
- `--max-num-seqs` below 6 makes c≥5 sweeps queue (TTFT p95 explodes while
  TPOT stays flat — decode isn't the bottleneck).
- PLE swapfile pages to NVMe under memory pressure; ~82% swapfile use during
  heavy runs is expected, not an error.
- GLM concurrency is compute-bound: aggregate plateaus ~120–140 tok/s from c=4;
  don't "diagnose" per-stream falloff as a bug.
