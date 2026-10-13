---
name: scripts-ops
description: 'Use when running host-level utilities on the GB10: vram_monitor, nightly-cleanup, token-throughput-test. Run them safely and read results.'
---

# scripts — host-level utilities

## Purpose

Small utilities that belong on the machine but are not a product project.
Service launchers for vLLM live in `../services` — do not duplicate them here.

## Key paths

- `/home/mazin/projects/scripts/` — this repo
- `nightly-cleanup/` — 04:00 Asia/Bangkok scanner (systemd user timer `host-cleanup.timer`)
- `nightly-cleanup/approved-purge.txt` — purge whitelist (absolute paths, one per line)
- `nightly-cleanup/keep.txt` / `medium.txt` — never-purge / ask-first lists
- `nightly-cleanup/reports/` — scan reports
- `vram_monitor.sh` — GPU / unified-memory usage on the GB10
- `token-throughput-test.py`, `warranty_info.md`

## Common commands

```bash
/home/mazin/projects/scripts/vram_monitor.sh
python3 /home/mazin/projects/scripts/nightly-cleanup/run.py --dry-run
python3 /home/mazin/projects/scripts/nightly-cleanup/run.py --nightly
systemctl --user list-timers host-cleanup.timer
```

Nightly notifications go to Telegram via `hermes send --to telegram`.

## Workflows & invariants (HARD rules)

- The nightly job **suggests** unused directories; it moves to
  `projects/.trash/YYYYMMDD/` only after a **second scan** AND a line in
  `approved-purge.txt`. Never purge on a first sighting.
- Skip trash moves if `lab-queue` has a running or queued job — scan +
  Telegram still happen.
- Root-owned leftovers (e.g. `/home/mazin/vllm`) are reported and **never moved**.
- Purge approvals are the user's call: add the absolute path to
  `approved-purge.txt`; the next 04:00 run after it has been seen once does the `mv`.
- Keep `/home/mazin` and `/home/mazin/projects` directories-only (global rule
  `keep-root-clean-and-readmes.mdc`); new work belongs in an existing project.
- After any behavior or measured-number change, update this README.md the same
  turn with the date and result.

## Verification

- `run.py --dry-run` before any real `--nightly` pass; confirm the report only
  lists expected paths.
- `systemctl --user list-timers host-cleanup.timer` shows the next 04:00 run.
- After a purge, verify targets exist under `projects/.trash/YYYYMMDD/`.

## Pitfalls

- `recipe-loop.timer` is disabled — this scanner replaced it (2026-09-13).
- `nightly-cleanup` keeps state in `seen.json`; deleting it resets the
  two-scan safety and can cause premature purges.
- `run.py` and `scan.py` are separate: run `run.py`, not the scanner directly.
