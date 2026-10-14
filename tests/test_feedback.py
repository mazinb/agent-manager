"""Regression tests for the r/mcp feedback plan (docs/FEEDBACK-PLAN-2026-10.md).

Run: python3 -m unittest discover -s tests -v
Stdlib only, in-memory DB — never touches the prod brain.db.
"""
import json
import sqlite3
import unittest

from agent_context import store


def fresh_con():
    con = store.connect(":memory:")
    return con


class Chunk0NotesSurviveRefresh(unittest.TestCase):
    def test_note_survives_prune_stale(self):
        """A note saved via the note tool must survive pipeline.refresh's
        prune_stale, which only knows about real on-disk paths."""
        con = fresh_con()
        store.upsert_source(
            con, "note:myproj/deploy-notes", "note", "myproj",
            123.0, 40, [("deploy-notes", "Deploy via script A.")])
        con.commit()
        # refresh() calls prune_stale(con, live) with live = real file paths
        removed = store.prune_stale(con, {"README.md": True})
        row = con.execute(
            "SELECT path, kind FROM sources WHERE kind='note'").fetchone()
        self.assertIsNotNone(row, "note was wiped by prune_stale")
        self.assertEqual(row["path"], "note:myproj/deploy-notes")
        self.assertEqual(removed, 0)

    def test_prune_still_removes_dead_files(self):
        con = fresh_con()
        store.upsert_source(
            con, "/tmp/gone.md", "project_readme", "proj",
            123.0, 10, [("gone", "body")])
        con.commit()
        removed = store.prune_stale(con, {})
        self.assertEqual(removed, 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)


class Chunk1TrustMetadata(unittest.TestCase):
    def test_migration_adds_columns_to_old_db(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(
            "CREATE TABLE sources(id INTEGER PRIMARY KEY, path TEXT UNIQUE,"
            " kind TEXT NOT NULL, project TEXT DEFAULT '', mtime REAL DEFAULT 0,"
            " size INTEGER DEFAULT 0, ingested_at REAL DEFAULT 0);")
        store._ensure_trust_columns(con)
        cols = {r[1] for r in con.execute("PRAGMA table_info(sources)")}
        for name, _ in store.TRUST_COLUMNS:
            self.assertIn(name, cols)
        # idempotent
        store._ensure_trust_columns(con)

    def test_upsert_stores_content_hash(self):
        con = fresh_con()
        store.upsert_source(con, "a.md", "project_readme", "p", 1, 10,
                            [("a", "hello world")])
        h1 = con.execute("SELECT content_hash FROM sources WHERE path='a.md'").fetchone()[0]
        self.assertTrue(h1)
        store.upsert_source(con, "a.md", "project_readme", "p", 1, 10,
                            [("a", "CHANGED")])
        h2 = con.execute("SELECT content_hash FROM sources WHERE path='a.md'").fetchone()[0]
        self.assertNotEqual(h1, h2)

    def test_note_meta_confidence_and_sources(self):
        con = fresh_con()
        sid = store.upsert_source(con, "note:p/t", "note", "p", 1, 10, [("t", "body")])
        store.set_note_meta(con, sid, confidence=0.8, based_on=["README.md"])
        row = con.execute("SELECT confidence, based_on, verified_at, stale FROM sources WHERE id=?",
                          (sid,)).fetchone()
        self.assertEqual(row["confidence"], 0.8)
        self.assertEqual(json.loads(row["based_on"]), ["README.md"])
        self.assertGreater(row["verified_at"], 0)
        self.assertEqual(row["stale"], 0)

    def test_note_tool_validates_confidence(self):
        import types
        import agent_context.mcp as mcp
        brain = types.SimpleNamespace(con=store.connect(":memory:"))
        with self.assertRaises(ValueError):
            mcp._note(brain, {"project": "p", "body": "b", "confidence": 1.5})
        out = mcp._note(brain, {"project": "p", "body": "b", "confidence": 0.5,
                                "sources": ["README.md"]})
        self.assertTrue(out["ok"])
        row = brain.con.execute(
            "SELECT confidence, based_on FROM sources WHERE kind='note'").fetchone()
        self.assertEqual(row["confidence"], 0.5)
        self.assertEqual(json.loads(row["based_on"]), ["README.md"])


if __name__ == "__main__":
    unittest.main()
