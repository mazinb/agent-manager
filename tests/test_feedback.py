"""Regression tests for the r/mcp feedback plan (docs/FEEDBACK-PLAN-2026-10.md).

Run: python3 -m unittest discover -s tests -v
Stdlib only, in-memory DB — never touches the prod brain.db.
"""
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


if __name__ == "__main__":
    unittest.main()
