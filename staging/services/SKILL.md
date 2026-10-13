---
name: services-ops
description: 'Use when managing GB10 host services: systemd units, launch scripts, vLLM/TTS/Comfy/lab-queue ports. Operate the launchers and unit files safely.'
---

# services — GB10 host service launchers

## Purpose

Launchers and systemd user units for long-running host services on the GB10
(EdgeXpert, 121 GiB unified memory). This project owns the scripts and unit
files; it does not host code. One GPU, exclusive scheduling — see the global
rule `~/.cursor/rules/gb10-exclusive-gpu.mdc`.

## Key paths

- `/home/mazin/projects/services/` — this repo (scripts + `*.service` files)
- `~/.config/systemd/user/` — deployed unit files (copy here, then `daemon-reload`)
- `/home/mazin/projects/vllm/` — model hub mounted as `/models` in the vllm container
- `~/.config/cursor-agent/worker.env` — cursor worker auth (mode 600, not in git)

## Current service map (ports)

- **Brain: `glm53-flash-tf` docker container, :8888** — GLM-5.3-Flash-EXL3
  (tensorfold, TP=2, 1M ctx). **NEVER stop, pause, or `docker rm` it.**
- `vllm-text` — **retired**; `:8000` stays free for experiments (loadtest, bench).
- `comfy-images` — :8188 warm ComfyUI, `Restart=no`, unpinned Klein/Krea
- `qwen-tts` — :8002 TTS clone server (stays cold)
- `qwen-image` — :8001 (pauses TTS while generating)
- `minimax-h3` — :8003, default `MINIMAX_H3_BACKEND=off` (safe to start; health only)
- `lab-queue` — exclusive speak/book/video worker; serializes TTS vs video
- `cursor-agent-worker` — keeps Cursor phone chats alive; waits on IDE lock

## Common commands

```bash
systemctl --user daemon-reload                      # after editing a unit file
systemctl --user restart vllm-text                  # daily coding serve (legacy recipe)
/home/mazin/projects/services/warmup-vllm.sh        # wait /health + 8-token generate
/home/mazin/projects/services/enable-ple-swap.sh    # after reboot, BEFORE vLLM (sudo TTY)
systemctl --user start lab-queue.service
systemctl --user list-timers --all
curl -sf http://127.0.0.1:8000/health               # vLLM (legacy)
curl -sf http://127.0.0.1:8003/health               # minimax-h3
curl -sf http://127.0.0.1:8888/health               # brain
```

## Workflows & invariants (HARD rules)

- TTS start stops `vllm-text`; TTS stop/`revive-vllm-after-tts.sh` starts it
  again + background warmup. `TTS_COEXIST_VLLM` probed → CUDA OOM at GMU 0.70;
  **keep TTS exclusive** (`pre-start-qwen-tts.sh`).
- `gb10_siblings` resume **never auto-starts cold units** (`qwen-tts`,
  `minimax-h3`). After video: unload, no auto-start TTS.
- Unit tests inject a fake `runner` — **never real `systemctl stop`** in tests.
- Default image pauses `qwen-tts` only; video pauses `qwen-tts` + `qwen-image`.
  The brain is **never** in the pause set.
- Do **not** enable the video unit with `MINIMAX_H3_BACKEND=comfy` while TTS is
  speaking — `lab-queue` serializes them. `off` is safe (health only).
- Do **not** `docker stop` the vllm container by hand — `Restart=always`
  relaunches the unit script (this is how a helper got stuck on 256K vs 65K).
- Start `comfy-images` **before** vLLM: Klein dies if Comfy inits CUDA after
  vLLM is loaded (MemFree ~2–4 GiB).
- TTS unit uses `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1` (local cache only).
- After reboot: `enable-ple-swap.sh` first, then start vLLM, then warmup.
- Long-context opt-in: unit env `MAX_MODEL_LEN=262144 MAX_NUM_SEQS=1`
  (same KV budget as default 64K×4).
- After any layout/behavior/measured change, update this repo's README.md the
  same turn (global rule `keep-root-clean-and-readmes.mdc`).

## Verification

- `warmup-vllm.sh` must print `pong` after any serve restart.
- `systemctl --user status <unit>` + the port health curls above.
- Live args check: inspect container args after restart (MTP N, batched tokens).

## Pitfalls

- Old `Before=vllm-text` orderings and `start-vllm-text.sh` are dead references.
- `swapon` busy is expected — PLE swapfile already active; just set swappiness 10.
- `comfy-images` and `qwen-tts` are `Restart=no` — they stay down unless started.
- Do not restart `qwen-tts` to pick up unrelated code.
