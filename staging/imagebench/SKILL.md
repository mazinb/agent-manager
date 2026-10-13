---
name: imagebench-ops
description: Use when running ImageBench text-to-image evals, generating/scoring runs, or preparing a submission on GB10. Operates the imagebench CLI end to end.
---

# imagebench ops

## Purpose

**ImageBench** — a 50-prompt on-device text-to-image pass/fail benchmark,
judged by **Qwen 3.8 Flash**. Core suite = 40 prompts, adult pack = 10
(18+). Demo: `https://app.getzoro.com/imagebench`. Results are PR'd to
`submissions/<you>/<run-id>.json` — **no PNGs in git**.

## Key paths

- `/home/mazin/projects/imagebench/` — repo root (`pyproject.toml`, Apache-2.0)
- `src/imagebench/cli.py` — the CLI (`run`, `score`, `report`)
- `src/imagebench/data/core.jsonl` / `adult.jsonl` — prompt packs
- `prompts/` — prompt templates; `schema/` — result JSON schema
- `submissions/<you>/<run-id>.json` — where results land
- `examples/` — sample outputs; `./gen.sh` — the generation adapter contract

## Common commands

```bash
pip install -e .

# gen.sh writes a PNG to $OUT from $PROMPT ($SEED $WIDTH $HEIGHT)
imagebench run --cmd './gen.sh'                 # core 40
imagebench run --suite all --cmd './gen.sh'     # + adult 10
imagebench score --base-url http://127.0.0.1:8000/v1
imagebench report ./results/<run-id>

# OpenAI-compatible adapter instead of the local cmd:
imagebench run --adapter openai --base-url http://127.0.0.1:8001/v1 --model …
```

## Workflows & invariants (HARD rules)

- Results are **pass/fail per prompt** judged by Qwen 3.8 Flash via a VLM
  endpoint (`--base-url`); `score` writes the run JSON, `report` renders it.
- **No PNGs in git** — only the result JSON is committed under
  `submissions/<you>/<run-id>.json`; keep images out of the repo.
- The **adult pack is 18+** — run/commit it only intentionally via
  `--suite all`.
- `gen.sh` contract is fixed: reads `$PROMPT`, `$SEED`, `$WIDTH`, `$HEIGHT`,
  writes one PNG to `$OUT`.
- GB10 GPU rule applies: the GLM brain (`glm53-flash-tf`, :8888) is never
  stopped or paused by image/bench jobs; **`vllm-text` is retired** and
  `:8000` stays free for experiments — point scoring at whatever endpoint is
  actually serving your judge (e.g. an experiment on :8000, adapter on
  :8001), never at the brain.
- If a TTS/image job is in flight (book/TTS), don't arm comfy or start a
  real generate without checking the pause rules first.

## Verification

- `imagebench run` exits with a run-id under `./results/<run-id>/` containing
  per-prompt records.
- `imagebench score --base-url …` completes and prints the pass/fail summary.
- `imagebench report ./results/<run-id>` renders the final report.
- A submission file placed at `submissions/<you>/<run-id>.json` passes
  `schema/` validation and contains no image data.

## Pitfalls

- Scoring against the wrong port: :8000 is for experiments, the brain is
  :8888 — don't score against the brain.
- Forgetting `pip install -e .` after a fresh clone → `imagebench` not found.
- Committing PNGs or mixing adult-pack rows into a core-only submission.
