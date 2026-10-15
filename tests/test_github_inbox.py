"""Inbox + optional GitHub sign-in tests (2026-10-14 feature).

Run: python3 -m unittest tests.test_github_inbox -v
Stdlib only, in-memory DB — never touches the prod brain.db.
"""
import json
import tempfile
import time
import unittest
import urllib.parse

from agent_context import github_login, mcp, store


def fresh_con():
    return store.connect(":memory:")


class FakeHttp:
    """Stand-in for urllib.request: canned responses per URL substring."""

    def __init__(self, responses):
        self.responses = responses  # {substring: bytes}

    def urlopen(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        for sub, payload in self.responses.items():
            if sub in url:
                return _Resp(payload)
        raise AssertionError("unexpected url: " + url)


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._p


class NoteOrigin(unittest.TestCase):
    def test_note_defaults_to_ai_origin(self):
        con = fresh_con()
        mcp._note(_Brain(con), {"project": "p", "title": "t", "body": "b"})
        self.assertEqual(
            con.execute("SELECT origin FROM sources WHERE kind='note'"
                        ).fetchone()["origin"], "ai")

    def test_human_origin_round_trips(self):
        con = fresh_con()
        mcp._note(_Brain(con), {"project": "p", "title": "t", "body": "b",
                                "origin": "human"})
        self.assertEqual(
            con.execute("SELECT origin FROM sources WHERE kind='note'"
                        ).fetchone()["origin"], "human")

    def test_bad_origin_rejected(self):
        con = fresh_con()
        with self.assertRaises(ValueError):
            mcp._note(_Brain(con), {"project": "p", "title": "t",
                                    "body": "b", "origin": "robot"})


class _Brain:
    def __init__(self, con):
        self.con = con


class InboxListing(unittest.TestCase):
    def test_list_notes_returns_body_and_badges(self):
        con = fresh_con()
        mcp._note(_Brain(con), {"project": "demo", "title": "Deploy",
                                "body": "Step one.", "confidence": 0.92,
                                "sources": ["scripts/deploy.sh"],
                                "origin": "ai"})
        notes = store.list_notes(con)
        self.assertEqual(len(notes), 1)
        n = notes[0]
        self.assertEqual(n["title"], "Deploy")
        self.assertEqual(n["project"], "demo")
        self.assertEqual(n["body"], "Step one.")
        self.assertEqual(n["origin"], "ai")
        self.assertEqual(n["confidence"], 0.92)
        self.assertEqual(n["based_on"], ["scripts/deploy.sh"])
        self.assertFalse(n["stale"])

    def test_list_notes_filters_by_project_and_orders_newest_first(self):
        con = fresh_con()
        mcp._note(_Brain(con), {"project": "a", "title": "old", "body": "x"})
        time.sleep(0.01)
        mcp._note(_Brain(con), {"project": "b", "title": "new", "body": "y"})
        titles = [n["title"] for n in store.list_notes(con, "a")]
        self.assertEqual(titles, ["old"])

    def test_editing_note_clears_stale_and_sets_human(self):
        con = fresh_con()
        mcp._note(_Brain(con), {"project": "p", "title": "t", "body": "v1"})
        con.execute("UPDATE sources SET stale=1 WHERE kind='note'")
        con.commit()
        # The inbox edit path re-saves through the note tool as human.
        mcp._note(_Brain(con), {"project": "p", "title": "t", "body": "v2",
                                "origin": "human"})
        row = con.execute("SELECT stale, origin FROM sources WHERE kind='note'"
                          ).fetchone()
        self.assertEqual(row["stale"], 0)
        self.assertEqual(row["origin"], "human")
        self.assertEqual(store.list_notes(con)[0]["body"], "v2")

    def test_list_notes_exposes_id_and_sources_alias(self):
        con = fresh_con()
        mcp._note(_Brain(con), {"project": "demo", "title": "t", "body": "b",
                                "sources": ["a.md"]})
        n = store.list_notes(con)[0]
        self.assertIsInstance(n["id"], int)
        self.assertEqual(n["sources"], ["a.md"])
        self.assertEqual(n["based_on"], n["sources"])


class GrokAgentPeers(unittest.TestCase):
    """Grok-spec: agent → to_agent powers Messaged ● peer lines + agents menu."""

    def test_note_stores_agent_and_to_agent(self):
        con = fresh_con()
        out = mcp._note(_Brain(con), {
            "project": "orbit", "title": "ask-dr-eggbot",
            "body": "Please set up Orbit Mentees.",
            "agent": "Grok Bot", "to_agent": "dr eggbot",
        })
        self.assertEqual(out["agent"], "grok-bot")
        self.assertEqual(out["to_agent"], "dr-eggbot")
        n = store.list_notes(con, "orbit")[0]
        self.assertEqual(n["agent"], "grok-bot")
        self.assertEqual(n["to_agent"], "dr-eggbot")

    def test_list_agents_aggregates_writers_and_peers(self):
        con = fresh_con()
        mcp._note(_Brain(con), {
            "project": "orbit", "title": "a", "body": "hi",
            "agent": "grok-bot", "to_agent": "dr-eggbot"})
        mcp._note(_Brain(con), {
            "project": "orbit", "title": "b", "body": "reply",
            "agent": "dr-eggbot", "to_agent": "grok-bot"})
        mcp._note(_Brain(con), {
            "project": "travel", "title": "c", "body": "audit",
            "agent": "grok-bot", "to_agent": "travel-helper"})
        agents = store.list_agents(con)
        by = {a["agent"]: a["notes"] for a in agents}
        self.assertEqual(by["grok-bot"], 3)  # 2 as agent + 1 as to_agent
        self.assertEqual(by["dr-eggbot"], 2)
        self.assertEqual(by["travel-helper"], 1)
        # Sorted by note count desc
        self.assertEqual(agents[0]["agent"], "grok-bot")

    def test_list_projects_preview_and_ordering(self):
        con = fresh_con()
        mcp._note(_Brain(con), {"project": "older", "title": "t",
                                "body": "first line\nmore"})
        time.sleep(0.01)
        mcp._note(_Brain(con), {"project": "newer", "title": "t",
                                "body": "# ignore\npreview here"})
        rows = store.list_projects(con)
        self.assertEqual([r["project"] for r in rows], ["newer", "older"])
        self.assertEqual(rows[0]["preview"], "preview here")
        self.assertEqual(rows[0]["note_count"], 1)
        self.assertEqual(rows[1]["preview"], "first line")


class PeerInbox(unittest.TestCase):
    """Simpler than A2A: message_peer + peer_inbox on the shared peers bus."""

    def test_message_peer_defaults_to_peers_project(self):
        con = fresh_con()
        out = mcp._message_peer(_Brain(con), {
            "agent": "hermes", "to_agent": "cursor",
            "body": "pytest green; please commit",
        })
        self.assertTrue(out["ok"])
        self.assertEqual(out["project"], "peers")
        self.assertEqual(out["agent"], "hermes")
        self.assertEqual(out["to_agent"], "cursor")
        n = store.list_notes(con, "peers")[0]
        self.assertEqual(n["body"], "pytest green; please commit")

    def test_peer_inbox_filters_by_to_agent(self):
        con = fresh_con()
        mcp._message_peer(_Brain(con), {
            "agent": "hermes", "to_agent": "cursor", "body": "for cursor"})
        mcp._message_peer(_Brain(con), {
            "agent": "cursor", "to_agent": "hermes", "body": "for hermes",
            "title": "reply"})
        mcp._note(_Brain(con), {
            "project": "peers", "title": "solo", "body": "no peer",
            "agent": "hermes"})
        mine = mcp._peer_inbox(_Brain(con), {"to_agent": "hermes"})
        self.assertEqual(len(mine["messages"]), 1)
        self.assertEqual(mine["messages"][0]["body"], "for hermes")
        self.assertEqual(mine["messages"][0]["agent"], "cursor")

    def test_message_peer_requires_both_sides(self):
        con = fresh_con()
        with self.assertRaises(ValueError):
            mcp._message_peer(_Brain(con), {"to_agent": "x", "body": "hi"})
        with self.assertRaises(ValueError):
            mcp._message_peer(_Brain(con), {"agent": "x", "body": "hi"})

    def test_message_peer_same_title_does_not_clobber(self):
        """Two peer pings with the same title must both survive (append-only)."""
        con = fresh_con()
        mcp._message_peer(_Brain(con), {
            "agent": "cursor", "to_agent": "hermes",
            "title": "plan-fluid", "body": "for hermes"})
        mcp._message_peer(_Brain(con), {
            "agent": "cursor", "to_agent": "grok-bot",
            "title": "plan-fluid", "body": "for grok"})
        hermes = mcp._peer_inbox(_Brain(con), {"to_agent": "hermes"})
        grok = mcp._peer_inbox(_Brain(con), {"to_agent": "grok-bot"})
        self.assertEqual(len(hermes["messages"]), 1)
        self.assertEqual(hermes["messages"][0]["body"], "for hermes")
        self.assertEqual(hermes["messages"][0]["title"], "plan-fluid")
        self.assertEqual(len(grok["messages"]), 1)
        self.assertEqual(grok["messages"][0]["body"], "for grok")
        self.assertEqual(grok["messages"][0]["to_agent"], "grok-bot")


class GithubSignIn(unittest.TestCase):
    def test_scope_is_read_only_minimal(self):
        url = github_login.build_authorize_url("cid", "https://x/cb", "st")
        q = urllib.parse.parse_qs(url.split("?")[1])
        self.assertEqual(q["scope"], ["read:user"])

    def test_state_is_one_shot(self):
        s = github_login.new_state()
        self.assertTrue(github_login.pop_state(s))
        self.assertFalse(github_login.pop_state(s), "state must not reuse")

    def test_complete_rejects_bad_state(self):
        with self.assertRaises(github_login.GitHubError):
            github_login.complete("code", "forged", {})

    def test_complete_exchanges_and_discards_token(self):
        s = github_login.new_state()
        fake = FakeHttp({
            "access_token": json.dumps(
                {"access_token": "gho_secret"}).encode(),
            "api.github.com": json.dumps({"login": "octocat"}).encode(),
        })
        login = github_login.complete("code", s, {
            "GITHUB_CLIENT_ID": "cid", "GITHUB_CLIENT_SECRET": "sec"},
            http=fake)
        self.assertEqual(login, "octocat")

    def test_github_error_when_github_rejects_code(self):
        s = github_login.new_state()
        fake = FakeHttp({"access_token": b"{}"})
        with self.assertRaises(github_login.GitHubError):
            github_login.complete("code", s, {}, http=fake)


if __name__ == "__main__":
    unittest.main()
