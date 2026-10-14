"""Ingest + resolve pipeline driver."""
import os
import time

from . import ingest, resolve, store


def refresh(con, config, progress=None):
    old_hashes = {r["path"]: r["content_hash"] or ""
                  for r in con.execute("SELECT path, content_hash FROM sources")}
    live = {}
    changed = []
    n = 0
    for path, kind, project, chunks in ingest.collect(config):
        try:
            st = os.stat(path)
            mtime, size = st.st_mtime, st.st_size
        except OSError:
            mtime, size = 0, 0
        store.upsert_source(con, path, kind, project, mtime, size, chunks)
        live[path] = True
        new_hash = store.content_hash(chunks)
        prev = old_hashes.get(path)
        if prev and prev != new_hash:
            changed.append(path)
        n += 1
        if progress and n % 20 == 0:
            progress(n, None)
    removed = store.prune_stale(con, live)
    changed.extend(removed)  # deleted sources invalidate notes too
    stale_flagged = store.flag_stale_for_sources(con, changed)
    if config.get("rebuild_fts", True):
        store.rebuild_fts(con)
    resolved = resolve.build(con, config, progress=progress)
    store.set_meta(con, "refreshed_at", str(time.time()))
    con.commit()
    return {"sources": n, "removed": len(removed),
            "stale_flagged": stale_flagged, **resolved}
