"""Remote phone-control registration (request_phone MCP stub)."""
import unittest

from agent_context import mcp, roster, store


def fresh():
    return store.connect(":memory:")


class _Brain:
    def __init__(self, con):
        self.con = con


class RequestPhone(unittest.TestCase):
    def test_queues_on_device_task_for_hermes(self):
        con = fresh()
        roster.seed_if_needed(con)
        out = mcp._request_phone(_Brain(con), {
            "do": "open Messages and read latest OTP on screen",
            "done_when": "OTP digits reported to requester (not stored)",
            "title": "read-otp",
            "from_agent": "cursor",
            "notify": False,
        })
        self.assertTrue(out["ok"])
        self.assertEqual(out["executes_on"], "mac-mini-hermes")
        task = out["task"]
        self.assertEqual(task["assignee"], "hermes")
        self.assertEqual(task["status"], "open")
        self.assertTrue(task["title"].lower().startswith("on-device"))
        self.assertIn("do:", task["body"])
        self.assertNotIn("handoff", out)

    def test_notify_sends_peer_handoff(self):
        con = fresh()
        roster.seed_if_needed(con)
        out = mcp._request_phone(_Brain(con), {
            "do": "toggle airplane mode off",
            "from_agent": "grok-bot",
            "notify": True,
        })
        self.assertIn("handoff", out)
        self.assertEqual(out["task"]["assignee"], "hermes")

    def test_mcp_tool_wired(self):
        self.assertIn("request_phone", mcp.TOOL_FUNCS)
        self.assertEqual(len(mcp.TOOLS), len(mcp.TOOL_FUNCS))


if __name__ == "__main__":
    unittest.main()
