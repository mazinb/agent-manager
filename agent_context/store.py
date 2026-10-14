"""SQLite store: sources, chunks (FTS5), entities, mentions, edges."""
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE,
  kind TEXT NOT NULL,
  project TEXT DEFAULT '',
  mtime REAL DEFAULT 0,
  size INTEGER DEFAULT 0,
  ingested_at REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  ord INTEGER DEFAULT 0,
  heading TEXT DEFAULT '',
  text TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, heading);
CREATE TABLE IF NOT EXISTS entities(
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  type TEXT NOT NULL,
  blurb TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS mentions(
  entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
  PRIMARY KEY(entity_id, chunk_id)
);
CREATE TABLE IF NOT EXISTS edges(
  src INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  dst INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  rel TEXT NOT NULL,
  PRIMARY KEY(src, dst, rel)
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_mentions_chunk ON mentions(chunk_id);
"""


def connect(db_path):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def upsert_source(con, path, kind, project, mtime, size, text_chunks):
    """Insert/replace a source and its chunks. text_chunks: [(heading, text)]"""
    cur = con.execute("SELECT id FROM sources WHERE path=?", (path,))
    row = cur.fetchone()
    now = time.time()
    if row:
        sid = row["id"]
        con.execute("DELETE FROM chunks WHERE source_id=?", (sid,))
        con.execute(
            "UPDATE sources SET kind=?, project=?, mtime=?, size=?, ingested_at=? "
            "WHERE id=?", (kind, project, mtime, size, now, sid))
    else:
        cur = con.execute(
            "INSERT INTO sources(path, kind, project, mtime, size, ingested_at) "
            "VALUES(?,?,?,?,?,?)", (path, kind, project, mtime, size, now))
        sid = cur.lastrowid
    for i, (heading, text) in enumerate(text_chunks):
        cur = con.execute(
            "INSERT INTO chunks(source_id, ord, heading, text) VALUES(?,?,?,?)",
            (sid, i, heading, text))
        cid = cur.lastrowid
        con.execute("INSERT INTO chunks_fts(rowid, text, heading) VALUES(?,?,?)",
                    (cid, text, heading))
    return sid


def prune_stale(con, live_paths):
    """Delete sources no longer on disk. Notes (kind='note') never live on
    disk — they are agent-written rows — so they are always protected."""
    rows = con.execute("SELECT id, path, kind FROM sources").fetchall()
    gone = [r["id"] for r in rows
            if r["kind"] != "note" and r["path"] not in live_paths]
    for sid in gone:
        con.execute("DELETE FROM chunks WHERE source_id=?", (sid,))
        con.execute("DELETE FROM sources WHERE id=?", (sid,))
    return len(gone)


def rebuild_fts(con):
    con.execute("DELETE FROM chunks_fts")
    for row in con.execute("SELECT id, text, heading FROM chunks"):
        con.execute("INSERT INTO chunks_fts(rowid, text, heading) VALUES(?,?,?)",
                    (row["id"], row["text"], row["heading"]))


def upsert_entity(con, name, etype, blurb=""):
    con.execute("INSERT INTO entities(name, type, blurb) VALUES(?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET type=excluded.type, "
                "blurb=CASE WHEN excluded.blurb != '' THEN excluded.blurb "
                "ELSE entities.blurb END", (name, etype, blurb))
    return con.execute("SELECT id FROM entities WHERE name=?", (name,)
                       ).fetchone()["id"]


def set_meta(con, key, value):
    con.execute("INSERT INTO meta(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def get_meta(con, key, default=None):
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default
