---
name: awesome-ai-benchmarks-evaluation-ops
description: Use when editing or publishing the awesome-ai-benchmarks-evaluation curated list. Covers fork workflow, lint/link checks, and CONTRIBUTING acceptance rules.
---

# Awesome AI Benchmarks & Evaluation — curated list maintenance

## Purpose

`/home/mazin/projects/awesome-ai-benchmarks-evaluation/` is Mazin's fork of
`brandonhimpfen/awesome-ai-benchmarks-evaluation` (remotes: `origin` =
`mazinb/awesome-ai-benchmarks-evaluation`, `upstream` = brandonhimpfen's).
A curated list of eval tools, benchmark datasets, leaderboards, and
frameworks: LLM benchmarks, reasoning/math, multimodal, RAG, safety,
eval frameworks, datasets. It is content curation, not code development —
the deliverable is always a clean README.md.

## Key paths

| Path | What |
|---|---|
| `README.md` | The list itself — all content lives here |
| `CONTRIBUTING.md` | Acceptance rules; PRs that violate it get closed |
| `check_readme_links.py` | Stdlib-only link checker: `python3 check_readme_links.py README.md [--timeout 20]` (HEAD→GET fallback; exits non-zero on broken links) |
| `.github/scripts/awesome_list_lint.py`, `detect_duplicate_links.py` | CI lint + duplicate-link detection |
| `.github/workflows/` | `awesome-lint.yml`, `duplicate-links.yml`, `links-pr.yml`, `links-scheduled-issue.yml`, `repo-health.yml` — run on every PR |
| `awesome-lists.json` | Cross-list metadata |
| `lychee.toml` | Lychee link-checker config |

## Common commands

```bash
python3 check_readme_links.py README.md          # local link check
python3 .github/scripts/awesome_list_lint.py     # CI-equivalent lint
python3 .github/scripts/detect_duplicate_links.py
git -C . remote -v && git status --short         # fork state
```

## Workflows & invariants

- **Branch → PR, never direct push to main.** The fork workflow: edit on a
  feature branch, push to `origin`, open a PR. Current state: branch
  `add-imagebench` with the ImageBench entry (commit 67c5888) — an unmerged
  PR; check `gh pr list` before assuming it landed.
- **Every entry must satisfy the PR checklist**: active legitimate link;
  valuable/trustworthy and in-scope for the category; clear objective
  description; list stays alphabetically sorted where applicable; no
  multiple links promoting a single source.
- **Not accepted**: broken links, duplicates, spam/self-promotion,
  entire frameworks with no documentation, out-of-scope items. Inclusion is
  selective — conceptual frameworks, early-stage projects, and
  promotion-driven additions get declined even if popular.
- Descriptions are short and informative, matching the existing
  `- [Name](url) – description` style; edits stay within the existing
  category taxonomy.
- Sync from `upstream` when brandonhimpfen updates the list.

## Verification

- `python3 check_readme_links.py README.md` exits 0 before pushing.
- Duplicate-link and lint scripts pass (CI will run the same on the PR).
- New entries render correctly in place, in the right category, sorted.

## Pitfalls

- The repo has two remotes — push to `origin` (mazinb), pull from
  `upstream` (brandonhimpfen); never force-push a rewritten history.
- CI posts scheduled link-check issues on `links-scheduled-issue.yml`; a
  broken external link may not be your PR's fault — check the issue body.
- License badge/README footer belongs to upstream — leave attribution
  intact.
- README is ~8 KB markdown with many badges; keep edits minimal and
  surgical, do not reformat.
