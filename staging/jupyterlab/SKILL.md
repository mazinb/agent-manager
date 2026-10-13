---
name: jupyterlab-ops
description: 'Use when running or extending the local JupyterLab notebooks env on the GB10. Use its .venv and keep weights/audio out.'
---

# jupyterlab — local notebooks

## Purpose

Ad-hoc notebook environment on the GB10. Small by design — analysis and
experimentation, not serving.

## Key paths

- `/home/mazin/projects/jupyterlab/` — project root
- `.venv/` — isolated Python env for JupyterLab (activate before running)
- `requirements.txt` — package pins used to build `.venv`
- `environment.log` / `jupyterlab.log` — install / run logs

## Common commands

```bash
cd /home/mazin/projects/jupyterlab
source .venv/bin/activate
jupyter lab
pip install -r requirements.txt     # only to rebuild .venv pins
```

## Workflows & invariants (HARD rules)

- Always use **this** `.venv` — not the system python, not a project venv —
  for notebooks started here.
- Model weights belong in `../vllm/`; story/audio outputs in
  `../kids-story/`. Never store either in this repo.
- Keep `/home/mazin` and `/home/mazin/projects` directories-only (global rule
  `keep-root-clean-and-readmes.mdc`).
- After any behavior or measured-number change, update `README.md` the same
  turn with date and result.
- GPU notebooks must respect the exclusive-GPU rule
  (`~/.cursor/rules/gb10-exclusive-gpu.mdc`): the brain (`glm53-flash-tf`,
  :8888) is never stopped, and :8000 is free for experiments.

## Typical workflows

- Start the server, open a notebook, verify kernel uses `.venv/bin/python`.
- Add a dependency: `pip install <pkg>` inside `.venv`, then pin it in
  `requirements.txt` so the env is reproducible.

## Verification

- `jupyter lab` serves its URL (default :8888 conflicts — note the printed
  token/URL; Jupyter will pick a free port if 8888 is taken by the brain).
- `python -c "import <pkg>"` inside `.venv` after any requirements change.
- `pip freeze` diffed against `requirements.txt` after adding packages.

## Pitfalls

- The brain container occupies :8888; Jupyter auto-picking a port is fine but
  do not hardcode 8888 in notebook tooling.
- `environment.log` / `jupyterlab.log` are logs, not docs — README.md is the
  source of truth.
