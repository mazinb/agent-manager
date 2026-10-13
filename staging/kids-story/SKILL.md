---
name: kids-story-ops
description: Use when producing kids story episodes, drafts, or TTS benchmarks in projects/kids-story. Run the draft pipeline and benches.
---

# kids-story-ops

## Purpose

Live media runtime for the story lab: wav/m4a/png/mp4 episode assets and job
state (gitignored). Scripts and drafts are versioned in
`voice-lab/kids-story/`; this directory holds the outputs. Editable working
copies live in `drafts/`, one finished episode overwrites `output/`.

## Key paths

- `/home/mazin/projects/kids-story/` — repo root
- `drafts/current.json`, `drafts/current.md` — editable working copy
- `output/` — latest finished Fish/Hermes episode (overwrite)
- `episodes/` — keepers (Alice, Oliver Twist, Goldilocks); `books/` — source text
- `benchmarks/` — dated speed-test JSON; `scripts/narrate_book.py`
- `quality/` — voice-lab sessions + GPU job state: `story-images/`,
  `story-videos/`, `video-clones/`, `.lab-queue/`, `.story-jobs/`,
  `.book-jobs/`, `.tts-out/` (TTS scratch, safe to TTL)
- `library/stories/<jobId>/` — packs (script.md, script.json, audio/, images/, videos/)
- `~/.hermes/fish-speech/references/<voice>/` — clone refs (app archives old takes here)
- `projects/voice-lab/models/minimax-h3/` — MiniMax H3 weights

## Common commands

```bash
# Hermes draft pipeline (optional; writes drafts/current.*)
/home/mazin/.hermes/voice-cloning-venv/bin/python \
  /home/mazin/.hermes/skills/kids-story-pipeline/scripts/run_pipeline.py \
  --idea "..." --lesson "..." --age-range 4-8 --voice mazin

# Book narration
python3 projects/kids-story/scripts/narrate_book.py

# Fish bench (historical path) — shared eager won: 8.5 min / 8.16 tok/s
bench_fish.py --no-compile   # compile lost on iterative multi-block stories (19.1 min)
```

Prefer the story lab UI for new picture/video stories. Speak/book/story audio
is Qwen3-TTS on `:8002`, not Fish decode.

## Workflows & invariants (HARD rules from README "Rules" + gb10 rule)

- **Edit in `drafts/`; ship via `output/` or `episodes/`.** Promote to
  `episodes/<name>/` only to keep a title.
- **No loose files at `/home/mazin` or `/home/mazin/projects`** — both stay
  directories-only.
- **Do not recreate `kids-story-output` or old comparison folders.**
- After a layout or timed run, **append a dated note to `README.md` the same
  turn**; benchmarks append a dated row to the README and a JSON file under
  `benchmarks/`.
- **Never stop the GLM brain** (tensorfold `:8888`): `bench_fish.py` no longer
  pauses the text brain around TTS runs — old `systemctl stop vllm-text` +
  `docker rm` is now a no-op; `:8000` stays free for experiments.
- MiniMax H3 stays cold; real Comfy generate stays gated in
  `voice-lab/TASKS.md`.

## Verification

- Pipeline run: `drafts/current.json` + `drafts/current.md` updated, then
  episode assets under `output/` or `episodes/<name>/`.
- Bench: new dated JSON in `benchmarks/` and a dated row in `README.md`.
- Library packs land in `library/stories/<jobId>/` (`ref.wav` + `ref.txt`
  under the device folder's `voices/<id>/`); leftover clip-only runs still
  show from `quality/story-images/` and `quality/story-videos/` until packed.

## Pitfalls

- `quality/.tts-out/` is scratch — safe to TTL-prune, don't treat as keepers.
- Fish on GB10: use `--no-compile` and shared GPU if you still run Fish.
- MiniMax H3 reference numbers: 5s ~960×544 8-step ≈ 7.5 min wall (Comfy
  ~428–470 s/clip), `benchmarks/2026-08-22-minimax-h3-smoke.json`.
- `samples/` holds Mac-friendly scp copies; `examples/` holds dialogue demos.
