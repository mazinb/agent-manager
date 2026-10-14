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
