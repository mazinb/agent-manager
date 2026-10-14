"""SQLite store: sources, chunks (FTS5), entities, mentions, edges."""
import hashlib
import json
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

# Trust/provenance columns (added idempotently — old DBs migrate in place).
TRUST_COLUMNS = (
    ("content_hash", "TEXT DEFAULT ''"),
    ("verified_at", "REAL DEFAULT 0"),
    ("confidence", "REAL"),
    ("stale", "INTEGER DEFAULT 0"),
    ("based_on", "TEXT"),
    ("origin", "TEXT DEFAULT 'ai'"),
)


def _ensure_trust_columns(con):
    have = {r[1] for r in con.execute("PRAGMA table_info(sources)")}
    for name, decl in TRUST_COLUMNS:
        if name not in have:
            con.execute(f"ALTER TABLE sources ADD COLUMN {name} {decl}")
    con.execute(
        "CREATE TABLE IF NOT EXISTS project_visibility ("
        "project TEXT PRIMARY KEY, visibility TEXT NOT NULL DEFAULT 'private')")
    con.commit()


def set_project_visibility(con, project, visibility):
    """Toggle a project public/private. Private (default): other projects'
    agents never see its content. Public: its chunks ride along in other
    projects' searches and packs."""
    if visibility not in ("public", "private"):
        raise ValueError("visibility must be 'public' or 'private'")
    con.execute(
        "INSERT INTO project_visibility(project, visibility) VALUES(?,?) "
        "ON CONFLICT(project) DO UPDATE SET visibility=excluded.visibility",
        (project, visibility))
    con.commit()


def public_projects(con):
    return [r["project"] for r in con.execute(
        "SELECT project FROM project_visibility WHERE visibility='public' "
        "ORDER BY project")]


def connect(db_path):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    _ensure_trust_columns(con)
    return con


def content_hash(text_chunks):
    """Stable sha256 over a source's chunk texts."""
    h = hashlib.sha256()
    for _heading, text in text_chunks:
        h.update(text.encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


def upsert_source(con, path, kind, project, mtime, size, text_chunks):
    """Insert/replace a source and its chunks. text_chunks: [(heading, text)]"""
    chash = content_hash(text_chunks)
    cur = con.execute("SELECT id FROM sources WHERE path=?", (path,))
    row = cur.fetchone()
    now = time.time()
    if row:
        sid = row["id"]
        con.execute("DELETE FROM chunks_fts WHERE rowid IN "
                    "(SELECT id FROM chunks WHERE source_id=?)", (sid,))
        con.execute("DELETE FROM chunks WHERE source_id=?", (sid,))
        con.execute(
            "UPDATE sources SET kind=?, project=?, mtime=?, size=?, ingested_at=?, "
            "content_hash=? WHERE id=?",
            (kind, project, mtime, size, now, chash, sid))
    else:
        cur = con.execute(
            "INSERT INTO sources(path, kind, project, mtime, size, ingested_at, content_hash) "
            "VALUES(?,?,?,?,?,?,?)", (path, kind, project, mtime, size, now, chash))
        sid = cur.lastrowid
    for i, (heading, text) in enumerate(text_chunks):
        cur = con.execute(
            "INSERT INTO chunks(source_id, ord, heading, text) VALUES(?,?,?,?)",
            (sid, i, heading, text))
        cid = cur.lastrowid
        con.execute("INSERT INTO chunks_fts(rowid, text, heading) VALUES(?,?,?)",
                    (cid, text, heading))
    return sid


def set_note_meta(con, sid, confidence=None, based_on=None, origin=None):
    """Trust metadata for a note: (re)saving refreshes verified_at and clears
    the stale flag. based_on: list of source paths the note was derived from.
    origin: 'ai' (agent-written, default) or 'human' (edited by a person)."""
    if origin is not None and origin not in ("ai", "human"):
        raise ValueError("origin must be 'ai' or 'human'")
    con.execute(
        "UPDATE sources SET verified_at=?, stale=0, confidence=?, based_on=?"
        + (", origin=?" if origin is not None else "") + " WHERE id=?",
        ((time.time(), confidence,
          json.dumps(based_on) if based_on else None,
          origin, sid) if origin is not None else
         (time.time(), confidence,
          json.dumps(based_on) if based_on else None, sid)))


def flag_stale_for_sources(con, changed_paths):
    """Mark notes stale when a source they are based on changed or vanished.

    Returns the number of notes flagged. Stale notes are excluded from packs
    and search until re-saved (set_note_meta clears the flag)."""
    changed = set(changed_paths)
    if not changed:
        return 0
    rows = con.execute(
        "SELECT id, based_on FROM sources WHERE kind='note' "
        "AND based_on IS NOT NULL AND stale=0").fetchall()
    n = 0
    for r in rows:
        try:
            deps = json.loads(r["based_on"])
        except (ValueError, TypeError):
            continue
        if changed & set(deps):
            con.execute("UPDATE sources SET stale=1 WHERE id=?", (r["id"],))
            n += 1
    return n


def list_notes(con, project=None):
    """Inbox rows: every kind='note' source with title, body and trust
    badges. Title is parsed from the path (note:project/title); the body is
    reassembled from chunks (long notes are chunked, so this is a faithful
    rejoin, not a copy). Ordered newest-verified first."""
    sql = ("SELECT id, path, project, size, verified_at, confidence,"
           " stale, based_on, origin FROM sources WHERE kind='note'")
    args = ()
    if project:
        sql += " AND project=?"
        args = (project,)
    sql += " ORDER BY verified_at DESC, id DESC"
    notes = []
    for r in con.execute(sql, args):
        _, _, rest = r["path"].partition(":")
        _, _, title = rest.partition("/")
        chunks = con.execute(
            "SELECT text FROM chunks WHERE source_id=? ORDER BY ord",
            (r["id"],)).fetchall()
        body = "\n\n".join(c["text"] for c in chunks)
        prefix = f"# {title}\n\n"
        if body.startswith(prefix):
            body = body[len(prefix):]
        try:
            based_on = json.loads(r["based_on"]) if r["based_on"] else []
        except (ValueError, TypeError):
            based_on = []
        notes.append({
            "project": r["project"], "title": title, "body": body,
            "confidence": r["confidence"], "verified_at": r["verified_at"],
            "stale": r["stale"], "based_on": based_on,
            "origin": r["origin"] or "ai",
        })
    return notes


def prune_stale(con, live_paths):
    """Delete sources no longer on disk. Notes (kind='note') never live on
    disk — they are agent-written rows — so they are always protected.

    Returns the list of removed paths (empty list if none)."""
    rows = con.execute("SELECT id, path, kind FROM sources").fetchall()
    gone = [r["path"] for r in rows
            if r["kind"] != "note" and r["path"] not in live_paths]
    for path in gone:
        sid = con.execute("SELECT id FROM sources WHERE path=?", (path,)).fetchone()[0]
        con.execute("DELETE FROM chunks_fts WHERE rowid IN "
                    "(SELECT id FROM chunks WHERE source_id=?)", (sid,))
        con.execute("DELETE FROM chunks WHERE source_id=?", (sid,))
        con.execute("DELETE FROM sources WHERE id=?", (sid,))
    return gone


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
