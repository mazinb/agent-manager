"""Ingest + resolve pipeline driver."""
import os
import time

from . import ingest, resolve, store


def refresh(con, config, progress=None):
    live = {}
    n = 0
    for path, kind, project, chunks in ingest.collect(config):
        try:
            st = os.stat(path)
            mtime, size = st.st_mtime, st.st_size
        except OSError:
            mtime, size = 0, 0
        store.upsert_source(con, path, kind, project, mtime, size, chunks)
        live[path] = True
        n += 1
        if progress and n % 20 == 0:
            progress(n, None)
    removed = store.prune_stale(con, live)
    if config.get("rebuild_fts", True):
        store.rebuild_fts(con)
    resolved = resolve.build(con, config, progress=progress)
    store.set_meta(con, "refreshed_at", str(time.time()))
    con.commit()
    return {"sources": n, "removed": removed, **resolved}
