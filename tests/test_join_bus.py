"""Join-the-bus feedback: whoami, join, broadcast, combined errors."""
import unittest

from agent_context import mcp, roster, store


def fresh():
    return store.connect(":memory:")


class _Brain:
    def __init__(self, con):
        self.con = con


class WhoamiJoin(unittest.TestCase):
    def test_whoami_agent_key(self):
        con = fresh()
        key = roster.mint_agent_key(con, "hermes")
        roster.add_member(con, chat="peers", agent="hermes", role="worker")
        out = roster.whoami(con, key["token"])
        self.assertTrue(out["key_ok"])
        self.assertEqual(out["agent"], "hermes")
        self.assertTrue(any(b["chat"] == "peers" for b in out["boards"]))
        self.assertGreater(out["last_seen_at"], 0)

    def test_whoami_missing_key_message(self):
        con = fresh()
        with self.assertRaises(ValueError) as cm:
            roster.whoami(con, "")
        self.assertIn("missing key", str(cm.exception).lower())

    def test_whoami_bad_key_message(self):
        con = fresh()
        with self.assertRaises(ValueError) as cm:
            roster.whoami(con, "not-a-real-key")
        self.assertIn("invalid key", str(cm.exception).lower())

    def test_join_agent_mints_and_membership(self):
        con = fresh()
        out = roster.join_agent(con, "newbot", chat="peers", mint=True)
        self.assertEqual(out["agent"], "newbot")
        self.assertTrue(out.get("token"))
        self.assertTrue(roster.is_member(
            con, roster.get_board(con, chat="peers")["id"], "newbot"))


class MessagePeerFeedback(unittest.TestCase):
    def test_combined_required_error(self):
        con = fresh()
        with self.assertRaises(ValueError) as cm:
            mcp._message_peer(_Brain(con), {})
        msg = str(cm.exception)
        self.assertIn("agent", msg)
        self.assertIn("to_agent", msg)
        self.assertIn("body", msg)

    def test_broadcast_all(self):
        con = fresh()
        roster.seed_if_needed(con)
        out = mcp._message_peer(_Brain(con), {
            "agent": "cursor", "to_agent": "all",
            "title": "bus-ping", "body": "hello everyone",
        })
        self.assertTrue(out["broadcast"])
        self.assertGreaterEqual(out["count"], 2)
        self.assertNotIn("cursor", out["to_agents"])
        hermes = mcp._peer_inbox(_Brain(con), {"to_agent": "hermes"})
        titles = [m["title"] for m in hermes["messages"]]
        self.assertTrue(any("bus-ping" in t for t in titles))


if __name__ == "__main__":
    unittest.main()
