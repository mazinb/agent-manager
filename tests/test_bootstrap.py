"""Session bootstrap: auto-load packs + hash skip."""
import json
import unittest

from agent_context import bootstrap, mcp, query, roster, store


def fresh():
    return store.connect(":memory:")


def seed_brain(con):
    """Minimal project + peers board so both pack paths work."""
    store.upsert_source(
        con, "readme:demo", "project_readme", "demo",
        1.0, 40, [("Demo", "DEMO-PACK-MARKER hello world")])
    roster.set_brief(con, "cursor", "# Cursor\n\nPlan things.\n", chat="peers")
    con.commit()
    return con


class BootstrapTests(unittest.TestCase):
    def test_session_and_context_pack(self):
        con = seed_brain(fresh())
        out = bootstrap.session_bootstrap(con, project="demo", chat="peers")
        self.assertTrue(out["ok"])
        self.assertTrue(out["changed"])
        self.assertIn("DEMO-PACK-MARKER", out["instructions"])
        self.assertIn("Session briefs", out["instructions"])
        self.assertIn("cursor", out["hashes"]["session"])
        self.assertTrue(out["hashes"]["context"])
        self.assertEqual(out["project"], "demo")

    def test_hash_skip_unchanged(self):
        con = seed_brain(fresh())
        first = bootstrap.session_bootstrap(con, project="demo", chat="peers")
        second = bootstrap.session_bootstrap(
            con, project="demo", chat="peers",
            since_hashes=first["hashes"]["session"],
            context_hash=first["hashes"]["context"])
        self.assertFalse(second["changed"])
        self.assertEqual(second["skipped"].get("session"), "unchanged")
        self.assertEqual(second["skipped"].get("context"), "unchanged")
        self.assertEqual(second["session"]["included"], [])

    def test_unknown_project_skips_context(self):
        con = seed_brain(fresh())
        out = bootstrap.session_bootstrap(
            con, project="no-such-slug", chat="peers")
        self.assertIn("unknown project", out["skipped"].get("context", ""))
        # Session briefs still load.
        self.assertTrue(out["session"]["included"] or out["session"].get("pack"))

    def test_no_project_skips_context_only(self):
        con = seed_brain(fresh())
        out = bootstrap.session_bootstrap(con, project=None, chat="peers")
        self.assertEqual(out["skipped"].get("context"), "no project pin")
        self.assertTrue(out["changed"])  # session briefs still new

    def test_merge_state_persists_hashes(self):
        con = seed_brain(fresh())
        first = bootstrap.session_bootstrap(con, project="demo")
        state = bootstrap.merge_state({}, first, url="http://x", agent="cursor")
        self.assertEqual(state["project"], "demo")
        self.assertIn("cursor", state["hashes"]["session"])
        self.assertTrue(state["hashes"]["context"])
        since, ctx = bootstrap.hashes_from_state(state)
        self.assertIn("cursor", since)
        self.assertEqual(ctx, first["hashes"]["context"])

    def test_mcp_tool_wired(self):
        self.assertIn("session_bootstrap", mcp.TOOL_FUNCS)
        self.assertEqual(
            len(mcp.TOOLS), len(mcp.TOOL_FUNCS),
            "TOOLS and TOOL_FUNCS must stay aligned")

    def test_mcp_initialize_includes_instructions(self):
        con = seed_brain(fresh())
        brain = type("B", (), {"con": con, "config": {}})()
        resp = mcp.handle(
            brain,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            project="demo")
        self.assertIn("instructions", resp["result"])
        self.assertIn("DEMO-PACK-MARKER", resp["result"]["instructions"])
        self.assertIn("_bootstrap_hashes", resp["result"])

    def test_mcp_session_bootstrap_tool(self):
        con = seed_brain(fresh())
        brain = type("B", (), {"con": con, "config": {}})()
        resp = mcp.handle(brain, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "session_bootstrap",
                       "arguments": {"project": "demo", "chat": "peers"}},
        }, project="demo")
        body = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(body["ok"])
        self.assertIn("DEMO-PACK-MARKER", body["instructions"])

    def test_should_write_inject(self):
        self.assertTrue(bootstrap.should_write_inject({"changed": True}, {}))
        self.assertFalse(bootstrap.should_write_inject(
            {"changed": False}, {"hashes": {"session": {}}}))
        self.assertTrue(bootstrap.should_write_inject({"changed": False}, None))


if __name__ == "__main__":
    unittest.main()
