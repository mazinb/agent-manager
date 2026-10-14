"""Agent roster + shared task board (cross-project)."""
import unittest

from agent_context import roster, store


def fresh():
    return store.connect(":memory:")


class RosterAgents(unittest.TestCase):
    def test_seeds_default_agents(self):
        con = fresh()
        names = {a["name"] for a in roster.list_agents(con)}
        self.assertTrue({"hermes", "cursor", "grok-bot"} <= names)

    def test_mint_key_view_once_and_auth(self):
        con = fresh()
        out = roster.mint_agent_key(con, "hermes")
        self.assertIn("token", out)
        self.assertEqual(roster.agent_token_ok(con, out["token"]), "hermes")
        self.assertIsNone(roster.agent_token_ok(con, "nope"))
        agents = {a["name"]: a for a in roster.list_agents(con)}
        self.assertTrue(agents["hermes"]["has_key"])
        self.assertEqual(agents["hermes"]["token_hint"], out["hint"])


class RosterTasks(unittest.TestCase):
    def test_auto_route_by_rule(self):
        con = fresh()
        t = roster.add_task(con, "on-device: restart gateway", created_by="cursor")
        self.assertEqual(t["assignee"], "hermes")
        self.assertFalse(t["parallel"])

    def test_serial_claim_blocks_second(self):
        con = fresh()
        a = roster.add_task(con, "on-device one", parallel=False, assignee="hermes",
                            auto_route=False)
        b = roster.add_task(con, "on-device two", parallel=False, assignee="hermes",
                            auto_route=False)
        roster.claim_task(con, a["id"], "hermes")
        with self.assertRaises(ValueError):
            roster.claim_task(con, b["id"], "hermes")

    def test_parallel_claims_ok(self):
        con = fresh()
        a = roster.add_task(con, "code a", parallel=True, assignee="cursor",
                            auto_route=False)
        b = roster.add_task(con, "code b", parallel=True, assignee="cursor",
                            auto_route=False)
        roster.claim_task(con, a["id"], "cursor")
        roster.claim_task(con, b["id"], "cursor")
        open_n = len(roster.list_tasks(con, status="claimed", assignee="cursor"))
        self.assertEqual(open_n, 2)

    def test_set_rules_replace(self):
        con = fresh()
        roster.set_rules(con, [{"match": "tax", "agent": "grok-bot",
                                "parallel": True, "priority": 20}])
        t = roster.add_task(con, "tax filing question")
        self.assertEqual(t["assignee"], "grok-bot")
        self.assertTrue(t["parallel"])


if __name__ == "__main__":
    unittest.main()
