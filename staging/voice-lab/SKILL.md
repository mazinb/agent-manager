---
name: voice-lab-ops
description: Use when working on the story lab, its TTS/GPU juggling, or /dwm pages. Deploy, test, and operate the voice-lab app.
---

# voice-lab-ops

## Purpose

Story lab — Next.js app at https://app.getzoro.com (served by
`llm-playground.service`, UI `:8090`): bedtime stories with Qwen3-TTS voice
clones (`mazin2`, `sarah2`), Klein/Krea story stills, `/pbn` paint-by-numbers,
`/imagebench`, and the token-gated `/dwm` control panel. Stories, pictures, and
voice samples save in-browser (OPFS).

## Key paths

- `/home/mazin/projects/voice-lab/` — repo root (`main` is the live app branch)
- `src/app/api/` — generate/images APIs; `src/lib/paths.ts` — backend defaults
- `scripts/gb10_siblings.py` — GPU sibling helpers (TTS/pause logic)
- `scripts/klein_smoke_test.py`, `scripts/krea_story_generate.py`
- `testdata/pbn-qa/` — image→SVG QA set; `public-data/Anime2Sketch/netG.pth`
- `~/brain/` (`queue_cli.py`, `queue-run.sh`, `status.json`) + `~/projects/dwm-eval/` — /dwm backend
- `.env.systemd` — systemd env for the app

## Common commands

```bash
cd /home/mazin/projects/voice-lab
npm run test:node          # node --test tests/*.test.ts (109/114 pass; 5 pre-existing failures: image weights, PBN)
npm run build              # next build --webpack
npm run test:pbn-qa        # .venv-qwen/bin/python scripts/pbn_qa_vectorize.py --strict
.venv-h3/bin/python scripts/klein_smoke_test.py --prompt "cartoon fox" --out logs/klein_smoke/out.png
.venv-h3/bin/python scripts/krea_story_generate.py --prompt "cartoon fox" --out logs/krea_lab/out.png

# Deploy a branch to getzoro
git checkout story-klein-krea-tiers
npm run test:node && npm run build
systemctl --user restart llm-playground.service
```

Verify: `GET /api/health` → `vllm: up`, `ttsPhase: cold`; then hard-refresh
https://app.getzoro.com. `/dwm` entry URL is `/dwm?k=<VOICE_LAB_TOKEN>` (sets
httpOnly cookie); `/api/dwm/status` polls brain state; mutating /dwm routes are
token-gated. Klein / Qwen / Krea share one GPU FIFO — busy → 503 with queue
place, timeout → 504.

## Workflows & invariants (HARD rules from .cursor/rules/gb10-exclusive-gpu.mdc)

- **Brain first**: `GLM-5.3-Flash-EXL3` via docker `glm53-flash-tf` (tensorfold)
  on `:8888` is **never** stopped, paused, or `docker rm`'d by any TTS/image/
  bench job. Server-side thinking is ON by default; send
  `chat_template_kwargs: {"thinking": false}` per request (tensorfold knob, not
  vLLM's `enable_thinking`).
- **`vllm-text` is retired.** Old start scripts and `Before=vllm-text` orderings
  are dead references. Port `:8000` stays free for experiments.
- TTS default is **exclusive**: `VLLM_PROFILE=fat`, `TTS_COEXIST_VLLM=0` — fat
  + TTS OOMs, so narration stops vLLM and text needs ~10–15 min to come back;
  the UI confirms first and shows the swap countdown chip.
- Default: **image** pauses `qwen-tts` only; **video** pauses `qwen-tts` +
  `qwen-image`. The brain is never in the pause set.
- `gb10_siblings` never auto-starts cold TTS (`qwen-tts`, `minimax-h3`) on
  resume. Unit tests inject a fake `runner` — never real `systemctl stop`.
- Default `MINIMAX_H3_BACKEND=off`. Do not arm `comfy` or run a real generate
  while a book/TTS job is in flight. After video: unload; do not auto-start TTS.
- Do not restart `qwen-tts` to pick up unrelated code. TTS unit is HF-offline
  (`local_files_only`); `ExecStopPost` → `revive-vllm-after-tts.sh`.
- Branches: `story-on-device-images` is gold for story stills; `recipe-eval/*`
  are legacy — **never deploy**, prune.

## Pitfalls

- Image stack is Klein + Krea only; ~44G retired weights sit in `models/_retired/`.
- `POST /api/images` = `{prompt, width, height, model?: "klein"|"krea"}` (default klein).
  Krea dumps Klein, pins Comfy `--gpu-only`, pauses TTS.
- Colored PBN prompts must require fully colored flat fills (ban "coloring book"
  → B&W bias); leave hues to the image model — no named colors in the prompt.
- PBN QA runner always overwrites `testdata/pbn-qa/out/latest/`.
- Old `vllm-text.service` references anywhere (units, orderings) are stale.
- Keep `/home/mazin` and `projects/` directories-only; update this README in the
  same turn as any behavior/measured-number change.
