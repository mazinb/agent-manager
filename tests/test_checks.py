"""Per-agent gates / poll policy tests."""
import unittest
from unittest import mock

from agent_context import checks, mcp, store


def fresh():
    return store.connect(":memory:")


class _Brain:
    def __init__(self, con):
        self.con = con


class AgentPolicies(unittest.TestCase):
    def test_default_hermes_gates(self):
        con = fresh()
        pol = checks.get_policy(con, "hermes")
        self.assertEqual(pol["agent"], "hermes")
        self.assertIn("brain", pol["policy"]["gates"])
        self.assertIn("thermal", pol["policy"]["gates"])
        self.assertEqual(pol["policy"]["poll"]["every_min"], 5)

    def test_set_policy_rejects_unknown_gate(self):
        con = fresh()
        with self.assertRaises(ValueError):
            checks.set_policy(con, "cursor", {"gates": ["warp_drive"]})

    def test_set_policy_round_trip(self):
        con = fresh()
        out = checks.set_policy(con, "cursor", {
            "gates": ["agent_manager"],
            "poll": {"every_min": 7, "actions": ["peer_inbox"]},
            "on_fail": "warn",
        })
        self.assertEqual(out["policy"]["gates"], ["agent_manager"])
        self.assertEqual(out["policy"]["poll"]["every_min"], 7)
        again = checks.get_policy(con, "cursor")
        self.assertEqual(again["policy"], out["policy"])


class AgentReady(unittest.TestCase):
    def test_ready_blocks_when_gate_fails(self):
        con = fresh()
        checks.set_policy(con, "hermes", {
            "gates": ["brain"],
            "poll": {"every_min": 5, "actions": []},
            "on_fail": "block",
        })
        with mock.patch.object(checks, "_gate_brain",
                               return_value={"ok": False, "detail": "down"}):
            out = checks.agent_ready(con, "hermes")
        self.assertFalse(out["ready"])
        self.assertTrue(out["blocked"])
        self.assertEqual(out["failed"], ["brain"])
        st = checks.get_state(con, "hermes")
        self.assertFalse(st["ready"])

    def test_warn_on_fail_still_ready(self):
        con = fresh()
        checks.set_policy(con, "cursor", {
            "gates": ["brain"],
            "poll": {"every_min": 0, "actions": []},
            "on_fail": "warn",
        })
        with mock.patch.object(checks, "_gate_brain",
                               return_value={"ok": False, "detail": "down"}):
            out = checks.agent_ready(con, "cursor")
        self.assertTrue(out["ready"])
        self.assertFalse(out["blocked"])
        self.assertEqual(out["failed"], ["brain"])

    def test_poll_reads_peer_inbox(self):
        con = fresh()
        checks.set_policy(con, "hermes", {
            "gates": [],
            "poll": {"every_min": 5, "actions": ["peer_inbox"]},
            "on_fail": "block",
        })
        mcp._message_peer(_Brain(con), {
            "agent": "cursor", "to_agent": "hermes",
            "title": "hi", "body": "role: handoff\ntask: x\ndo: y"})
        with mock.patch.object(checks, "_gate_brain",
                               return_value={"ok": True, "detail": "ok"}):
            out = checks.agent_poll(con, "hermes")
        self.assertEqual(out["actions"]["peer_inbox"]["count"], 1)
        self.assertIn("hi", out["actions"]["peer_inbox"]["titles"])


class McpChecks(unittest.TestCase):
    def test_mcp_agent_ready(self):
        con = fresh()
        checks.set_policy(con, "hermes", {
            "gates": ["thermal"], "poll": {"every_min": 0, "actions": []},
            "on_fail": "block",
        })
        with mock.patch.object(checks, "_gate_thermal",
                               return_value={"ok": True, "detail": "cool"}):
            out = mcp._agent_ready(_Brain(con), {"agent": "hermes"})
        self.assertTrue(out["ready"])


if __name__ == "__main__":
    unittest.main()
