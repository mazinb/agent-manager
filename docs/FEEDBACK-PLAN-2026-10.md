# Feedback plan — r/mcp thread (2026-10-14)

From https://www.reddit.com/r/mcp/comments/1x5pdup/ (13 comments). Each chunk is a
small, independently shippable commit with a test. Work on `feedback-trust`
branch; merge to main per chunk-group.

## Feedback → features

| # | Who | Said | Feature |
|---|-----|------|---------|
| F1 | u/Content-Parking-621 | timestamps + confidence scores; "last verified" flag so stale memories don't quietly influence decisions | Chunks 1, 2, 4 |
| F2 | u/Comfortable_Run8053 | keep it per repo — cross-contamination drives me nuts | Chunk 3 |
| F3 | u/MiserableFlatworm337 | track whether a note comes from a source doc or a generated note; repeated summaries of the same claim aren't independent evidence | Chunk 1 (lineage), deferred: dedup weighting |
| F4 | u/No_Product_5759 | source-change invalidation (README changed at commit Y → note flagged until rechecked); default namespace per repo w/ opt-in cross-project search; test that deleting a source doc removes derived notes from packs | Chunks 2, 3 |
| F5 | u/Poildek | (dismissive) compare against the 20 most-starred GitHub alternatives | Chunk 6 optional |

## Design decisions

- **Notes live in `sources`** (`path = note:project/title`, kind `note`) and
  flow through the same chunk/FTS pipeline — all trust metadata goes on
  `sources`, one table, no new schema surface.
- **stdlib only**: `hashlib.sha256` for content hashes, `ALTER TABLE ... ADD
  COLUMN` guarded by a column-exists check (idempotent migration, works on
  existing DBs).
- **Stale = excluded, not deleted.** A note whose referenced source changed or
  vanished is flagged `stale=1` and dropped from context packs, ask results
  and search unless `include_stale: true`. The note text survives so the agent
  can re-verify and re-save (which clears the flag and bumps `verified_at`).
- **Confidence is display-only in v1.** No retrieval weighting yet — that
  silently changes answer quality; revisit after lineage data accumulates.
  Same for F3's "repeated summaries aren't independent evidence": we record
  `based_on` lineage now, do citation dedup later.
- **Scoping is opt-in per client, not a global default.** `connect --project X`
  writes `?project=X` into the MCP URL; the server injects that as the default
  `project` for `search`. Unscoped MCP clients keep today's behaviour.

## Chunks

### Chunk 0 — CRITICAL: notes are wiped on every refresh
`prune_stale()` deletes any source not seen on disk; `note:` sources are never
on disk → **every refresh destroys all notes** (confirmed: 0 notes in prod DB).
- [ ] 0.1 Failing test: save note → refresh → note still queryable
- [ ] 0.2 Fix: `prune_stale` skips `kind='note'`
- [ ] 0.3 Verify against prod :8075 (save note, refresh, still there)

### Chunk 1 — Trust metadata on notes
- [ ] 1.1 `store._ensure_columns()`: `sources.content_hash TEXT`,
      `verified_at REAL`, `confidence REAL`, `stale INTEGER DEFAULT 0`,
      `based_on TEXT` (JSON array of source paths)
- [ ] 1.2 `upsert_source` stores sha256 of chunk text; sets `verified_at`
- [ ] 1.3 `note` tool + `/api/note`: accept `confidence` (0–1) and `sources`
      (paths the note is based on) → `based_on`; re-save refreshes
      `verified_at`, clears `stale`

### Chunk 2 — Source-change invalidation (F1, F4)
- [ ] 2.1 `pipeline.refresh`: hash-diff each source vs stored `content_hash`;
      changed/deleted → `stale=1` on notes whose `based_on` includes it
- [ ] 2.2 `query.context_pack` + `_ask` + `search` exclude stale notes unless
      `include_stale`
- [ ] 2.3 Test: note based on README → edit README → refresh → stale &
      excluded; delete README → same

### Chunk 3 — Per-project scoping (F2, F4)
- [ ] 3.1 `query.search(con, q, limit, project=None)` filter
- [ ] 3.2 MCP `search` schema + `/api/search`: optional `project`;
      `/mcp?project=X` injects default project for unscoped searches
- [ ] 3.3 npm `connect --project X` → URL query param (CLI change → npm
      republish required in chunk 5)
- [ ] 3.4 Test: identical service name in two projects, scoped search returns
      only the right one

### Chunk 4 — Provenance in results + UI (visual only)
- [ ] 4.1 `entity_card`/search results expose `origin` (note|doc),
      `verified_at`, `confidence`, `stale`
- [ ] 4.2 Brain page: stale badge, confidence, "verified Nd ago" — additive
      fields only, no behaviour change

### Chunk 5 — Docs, release, deploy
- [ ] 5.1 README: trust-model section + changelog entry
- [ ] 5.2 Bump npm + pyproject to 0.4.0 (CLI args changed), `cd npm && npm publish`
- [ ] 5.3 Merge to main, restart agent-manager.service, `npm-sync-check.sh` → 0
- [ ] 5.4 Post-deploy smoke: save note w/ confidence+sources, refresh, ask

### Chunk 6 — Close the loop
- [ ] 6.1 Reply on the Reddit thread: what shipped, crediting each commenter
- [ ] 6.2 (optional) Star-count comparison vs top GitHub agent-memory projects
