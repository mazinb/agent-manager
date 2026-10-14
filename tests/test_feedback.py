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
        self.assertEqual(removed, [])

    def test_prune_still_removes_dead_files(self):
        con = fresh_con()
        store.upsert_source(
            con, "/tmp/gone.md", "project_readme", "proj",
            123.0, 10, [("gone", "body")])
        con.commit()
        removed = store.prune_stale(con, {})
        self.assertEqual(removed, ["/tmp/gone.md"])
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


class Chunk2SourceChangeInvalidation(unittest.TestCase):
    def _seed(self, con):
        # a source doc + a note derived from it
        store.upsert_source(con, "docs/README.md", "project_readme", "p",
                            1, 10, [("README", "deploy with script A")])
        sid = store.upsert_source(con, "note:p/deploy", "note", "p", 1, 20,
                                  [("deploy", "NOTE-ONLY-MARKER alpha 7")])
        store.set_note_meta(con, sid, confidence=0.9, based_on=["docs/README.md"])
        con.commit()

    def test_changed_source_flags_note_stale(self):
        con = fresh_con()
        self._seed(con)
        n = store.flag_stale_for_sources(con, ["docs/README.md"])
        self.assertEqual(n, 1)
        self.assertEqual(con.execute(
            "SELECT stale FROM sources WHERE path='note:p/deploy'"
        ).fetchone()["stale"], 1)

    def test_deleted_source_flags_note_stale(self):
        con = fresh_con()
        self._seed(con)
        gone = store.prune_stale(con, {"note:p/deploy": True})  # README not live
        self.assertEqual(gone, ["docs/README.md"])
        self.assertEqual(store.flag_stale_for_sources(con, gone), 1)
        self.assertEqual(con.execute(
            "SELECT stale FROM sources WHERE path='note:p/deploy'"
        ).fetchone()["stale"], 1)

    def test_resave_clears_stale(self):
        con = fresh_con()
        self._seed(con)
        store.flag_stale_for_sources(con, ["docs/README.md"])
        sid = con.execute(
            "SELECT id FROM sources WHERE path='note:p/deploy'").fetchone()[0]
        store.set_note_meta(con, sid, confidence=0.9, based_on=["docs/README.md"])
        self.assertEqual(con.execute(
            "SELECT stale FROM sources WHERE id=?", (sid,)).fetchone()["stale"], 0)

    def test_stale_note_excluded_from_search_and_pack(self):
        from agent_context import query
        con = fresh_con()
        self._seed(con)
        sid = con.execute(
            "SELECT id FROM sources WHERE path='note:p/deploy'").fetchone()[0]
        con.execute("UPDATE sources SET stale=1 WHERE id=?", (sid,))
        con.commit()
        # visible with include_stale
        self.assertTrue(any(r["path"] == "note:p/deploy"
                            for r in query.search(con, "deploy", include_stale=True)))
        # hidden by default
        self.assertEqual(
            [r for r in query.search(con, "deploy") if r["path"] == "note:p/deploy"],
            [])
        pack = query.context_pack(con, "p")
        self.assertNotIn("NOTE-ONLY-MARKER", pack)

    def test_unrelated_change_does_not_flag(self):
        con = fresh_con()
        self._seed(con)
        self.assertEqual(store.flag_stale_for_sources(con, ["other/file.md"]), 0)
        self.assertEqual(con.execute(
            "SELECT stale FROM sources WHERE path='note:p/deploy'"
        ).fetchone()["stale"], 0)


class Chunk3PerProjectScoping(unittest.TestCase):
    def _seed_two_projects(self, con):
        # same keyword in both projects — the cross-contamination trap
        store.upsert_source(con, "docs/a.md", "project_readme", "alpha",
                            1, 10, [("dep", "alpha uses build system ONE")])
        store.upsert_source(con, "docs/b.md", "project_readme", "beta",
                            1, 20, [("dep", "beta uses build system TWO")])

    def test_search_without_project_returns_both(self):
        from agent_context import query
        con = fresh_con()
        self._seed_two_projects(con)
        hits = query.search(con, "dep")
        self.assertEqual({r["project"] for r in hits}, {"alpha", "beta"})

    def test_search_scoped_to_project_no_contamination(self):
        from agent_context import query
        con = fresh_con()
        self._seed_two_projects(con)
        hits = query.search(con, "dep", project="alpha")
        self.assertNotEqual(hits, [])
        self.assertEqual({r["project"] for r in hits}, {"alpha"})

    def test_mcp_search_scoped(self):
        from agent_context import mcp

        class FakeBrain:
            pass
        con = fresh_con()
        self._seed_two_projects(con)
        brain = FakeBrain()
        brain.con = con
        brain.config = {"llm": {}}  # no LLM -> extractive fallback path
        out = mcp.handle(brain, {"method": "tools/call",
                                 "params": {"name": "search", "arguments": {
                                     "q": "dep", "project": "beta"}}})
        self.assertIsNotNone(out)
        payload = json.loads(out["result"]["content"][0]["text"])
        self.assertEqual({r["project"] for r in payload["results"]}, {"beta"})


class Chunk4ProvenanceInResults(unittest.TestCase):
    def test_search_results_carry_trust_fields(self):
        from agent_context import query
        con = fresh_con()
        store.upsert_source(con, "docs/README.md", "project_readme", "p",
                            1, 10, [("README", "deploy with script A")])
        sid = store.upsert_source(con, "note:p/deploy", "note", "p", 1, 20,
                                  [("deploy", "NOTE-ONLY-MARKER alpha 7")])
        store.set_note_meta(con, sid, confidence=0.9, based_on=["docs/README.md"])
        con.commit()
        hits = query.search(con, "deploy", include_stale=False)
        note = [r for r in hits if r["path"] == "note:p/deploy"]
        self.assertEqual(len(note), 1)
        self.assertEqual(note[0]["confidence"], 0.9)
        self.assertGreater(note[0]["verified_at"], 0)
        self.assertEqual(note[0]["stale"], 0)
        # source-doc hits ride the same shape with NULL trust fields
        doc = [r for r in hits if r["path"] == "docs/README.md"]
        self.assertEqual(len(doc), 1)
        self.assertIsNone(doc[0]["confidence"])

    def test_entity_card_chunks_show_provenance(self):
        from agent_context import query
        con = fresh_con()
        store.upsert_source(con, "docs/README.md", "project_readme", "p",
                            1, 10, [("README", "the deployd tool builds things")])
        con.commit()
        eid = store.upsert_entity(con, "deployd", "tool")
        cid = con.execute("SELECT id FROM chunks LIMIT 1").fetchone()["id"]
        con.execute("INSERT INTO mentions(chunk_id, entity_id) VALUES(?,?)",
                    (cid, eid))
        con.commit()
        card = query.entity_card(con, "deployd")
        self.assertIsNotNone(card)
        self.assertEqual(len(card["chunks"]), 1)
        c = card["chunks"][0]
        self.assertEqual(c["kind"], "project_readme")
        self.assertEqual(c["path"], "docs/README.md")
        self.assertIn("stale", c)
        self.assertIn("confidence", c)


class Chunk5ProjectVisibility(unittest.TestCase):
    def _seed_three(self):
        con = fresh_con()
        store.upsert_source(con, "a.md", "project_readme", "alpha", 1, 10,
                            [("A", "alpha secret keyword zebra")])
        store.upsert_source(con, "b.md", "project_readme", "beta", 1, 10,
                            [("B", "beta shared keyword zebra")])
        store.upsert_source(con, "g.md", "project_readme", "gamma", 1, 10,
                            [("G", "gamma hidden keyword zebra")])
        con.commit()
        return con

    def test_default_private_no_leak(self):
        from agent_context import query
        con = self._seed_three()
        hits = query.search(con, "zebra", project="alpha")
        self.assertEqual({r["project"] for r in hits}, {"alpha"})

    def test_public_project_rides_along(self):
        from agent_context import query
        con = self._seed_three()
        store.set_project_visibility(con, "beta", "public")
        hits = query.search(con, "zebra", project="alpha")
        self.assertEqual({r["project"] for r in hits}, {"alpha", "beta"})

    def test_private_stays_hidden_after_other_toggle(self):
        from agent_context import query
        con = self._seed_three()
        store.set_project_visibility(con, "beta", "public")
        hits = query.search(con, "zebra", project="alpha")
        self.assertNotIn("gamma", {r["project"] for r in hits})

    def test_toggle_back_to_private(self):
        from agent_context import query
        con = self._seed_three()
        store.set_project_visibility(con, "beta", "public")
        store.set_project_visibility(con, "beta", "private")
        hits = query.search(con, "zebra", project="alpha")
        self.assertEqual({r["project"] for r in hits}, {"alpha"})

    def test_invalid_visibility_rejected(self):
        con = self._seed_three()
        with self.assertRaises(ValueError):
            store.set_project_visibility(con, "beta", "internal")

    def test_pack_includes_public_not_private(self):
        from agent_context import query
        con = self._seed_three()
        store.set_project_visibility(con, "beta", "public")
        pack = query.context_pack(con, "alpha")
        self.assertIn("beta shared keyword", pack)
        self.assertNotIn("gamma hidden", pack)
        self.assertIn("alpha secret", pack)


if __name__ == "__main__":
    unittest.main()
