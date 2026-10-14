"""Agent roster + chat-linked task boards."""
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


class RosterBoards(unittest.TestCase):
    def test_default_peers_board_linked_to_chat(self):
        con = fresh()
        b = roster.get_board(con)
        self.assertEqual(b["chat"], "peers")
        members = {m["agent"] for m in b["members"]}
        self.assertTrue({"hermes", "cursor", "grok-bot"} <= members)

    def test_board_per_chat(self):
        con = fresh()
        a = roster.get_or_create_board(con, "travel", title="Travel")
        b = roster.get_or_create_board(con, "tax")
        self.assertEqual(a["chat"], "travel")
        self.assertEqual(b["chat"], "tax")
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(len(roster.list_boards(con)), 3)  # peers + 2

    def test_add_remove_member(self):
        con = fresh()
        roster.upsert_agent(con, "travel-helper")
        board = roster.add_member(con, chat="peers", agent="travel-helper",
                                  role="worker")
        self.assertIn("travel-helper", {m["agent"] for m in board["members"]})
        board = roster.remove_member(con, chat="peers", agent="travel-helper")
        self.assertNotIn("travel-helper",
                         {m["agent"] for m in board["members"]})

    def test_claim_requires_membership(self):
        con = fresh()
        roster.upsert_agent(con, "outsider")
        t = roster.add_task(con, "code: fix", assignee="cursor",
                            auto_route=False, chat="peers")
        with self.assertRaises(ValueError) as cm:
            roster.claim_task(con, t["id"], "outsider")
        self.assertIn("not on this board", str(cm.exception))

    def test_tasks_scoped_to_board(self):
        con = fresh()
        roster.add_task(con, "peers work", chat="peers", auto_route=False)
        roster.add_task(con, "travel work", chat="travel", auto_route=False)
        peers = roster.list_tasks(con, chat="peers")
        travel = roster.list_tasks(con, chat="travel")
        self.assertEqual([t["title"] for t in peers], ["peers work"])
        self.assertEqual([t["title"] for t in travel], ["travel work"])


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
