---
name: research-ops
description: Use when working in projects/research — topic scouting, article pipeline, or IBKR portfolio ops (portfolio-getzoro). Covers real commands, state files, and the hard merge-to-main + portfolio-web restart rule.
---

# Research — topic scout, article pipeline, IBKR portfolio ops

## Purpose

`/home/mazin/projects/research` is two workspaces in one:

1. **Topic scout / article drafting** — Hermes research skills plus local scripts
   that share topic queues, seen-URL stores, and daily logs. Articles are
   published to getzoro.com reports (Vercel).
2. **IBKR portfolio ops** (`ibkr-portfolio-ops/`, git remote
   `mazinb/portfolio-getzoro`) — covered-call desk at
   [portfolio.getzoro.com](https://portfolio.getzoro.com): trade history via
   IBKR Flex, advisor picks, roll coaching, local-LLM chat, Telegram/WhatsApp
   reminders, multi-tenant IBKR OAuth.

## Key paths

| Path | What |
|---|---|
| `scout_run.py` | Main scout / recommendation runner |
| `topic-queue.json`, `topics-*.md` | Active topic queue / per-vertical queues |
| `.seen_urls*.json` | Scout dedup state — never delete |
| `articles/<slug>/` | Drafts: `article.md`, `review.md`, `draft_v2.md`, `review_v2.md` |
| `templates/` | `report.md`, `report.json`, `report-iteration.json` |
| `daily-logs/` | Per-day run logs |
| `ibkr-statement-20260916/` | IBKR statement extract + `OPTIONS.md` (NAV 946k, options MTM +13,687) |
| `ibkr-portfolio-ops/serve.py` | portfolio-web app, `:8134`, pipx hermes-agent venv |
| `ibkr-portfolio-ops/data/`, `logs/`, `.env`, `.ibkr_client.json` | **Not in git**; nightly backup of `data/` → `~/backups/portfolio/` (keep 14) |
| `ibkr-portfolio-ops/ledger/CHANGES.md` | Changelog |
| `ibkr-portfolio-ops/docs/API.md` | Routes and data layout |

## Common commands

```bash
# Portfolio service
cd ~/projects/research/ibkr-portfolio-ops
systemctl --user restart portfolio-web      # serves :8134
journalctl --user -u portfolio-web -f
curl -sS http://127.0.0.1:8134/api/ibkr/status

# Tests & scheduler
python3 -m unittest discover -s tests -v
python3 scheduler.py status
PORTFOLIO_USER=<uid> python3 advisor/advisor.py digest
tail -f logs/portfolio.log

# Link check for README drafts
python3 check_draft.py            # (research root)
```

## Workflows & invariants

**HARD rule (`.cursor/rules/merge-main-and-build.mdc`, mirrored in the global
`ibkr-portfolio-merge-main.mdc`):** when work in `ibkr-portfolio-ops` /
`portfolio-getzoro` is finished — or the user says merge/build/ship — **merge
the feature branch into `main`, push `origin/main`, then
`systemctl --user restart portfolio-web.service`.** Never stop at a
feature-branch-only push. No PR unless the user asks for PR review. After
merge or any go-live change, confirm `:8134` is up. The production checkout is
this repo's `main` working tree (the service's `WorkingDirectory`).

**Article quality gates (all must pass before publishing):** ≥ 2000 words;
≥ 3 cited sources; a counterargument/negative section; a call-to-action; no
hallucinated claims (every stat sourced or attributed).

**Article publish steps:** draft at `articles/<slug>/article.md` → review →
`draft_v2.md` → review_v2 → if PASS (score ≥ 7.0) copy to the web repo's
`public/reports/<slug>.md` + `<slug>.json` + `<slug>-iteration.json`, mirror to
`src/reports/`, commit + push main; Vercel auto-deploys. Start new articles
from `templates/`.

**Keep-root-clean rule:** new drafts go under `articles/` or `daily-logs/`,
never the projects root. Update `README.md` (dated) after any layout,
default, behavior, or measured-number change.

## Verification

- After a portfolio restart: `curl -sS http://127.0.0.1:8134/api/ibkr/status`
  returns healthy and `journalctl --user -u portfolio-web` shows no errors.
- `python3 -m unittest discover -s tests -v` passes before merging.
- Published articles: all five quality gates checked off.

## Pitfalls

- Do not delete `.seen_urls*.json` — that is scout dedup state.
- `data/`, `logs/`, `.env`, `.ibkr_client.json` are untracked; never commit
  them and never assume they exist in a fresh clone.
- `x-pipeline` was trashed 2026-09-13 (`projects/.trash/20260913/`); do not
  recreate it.
- Chat LLM goes to local vLLM only; secrets (Flex token, OAuth refresh) stay
  on this box.
- Prior Telegram VUWS/~1000% option figures were wrong; trust
  `ibkr-statement-20260916/OPTIONS.md` numbers.
