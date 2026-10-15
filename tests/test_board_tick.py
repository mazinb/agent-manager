"""Tick-based board execution + reassign."""
import unittest
from unittest import mock

from agent_context import checks, mcp, roster, store


def fresh():
    return store.connect(":memory:")


class _Brain:
    def __init__(self, con):
        self.con = con


class BoardTick(unittest.TestCase):
    def test_tick_claim_continue_idle(self):
        con = fresh()
        roster.seed_if_needed(con)
        with mock.patch.object(checks, "agent_ready", return_value={
            "agent": "hermes", "ready": True, "blocked": False,
            "failed": [], "results": {}, "policy": {},
        }):
            idle = roster.board_tick(con, "hermes", chat="peers")
            self.assertEqual(idle["action"], "idle")

            t = roster.add_task(
                con, "on-device: tick-me", body="do it",
                assignee="hermes", created_by="cursor", chat="peers")
            offer = roster.board_tick(con, "hermes", chat="peers")
            self.assertEqual(offer["action"], "claim")
            self.assertEqual(offer["task"]["id"], t["id"])

            claimed = roster.board_tick(
                con, "hermes", chat="peers", claim=True)
            self.assertEqual(claimed["action"], "claimed")
            self.assertEqual(claimed["task"]["status"], "claimed")

            cont = roster.board_tick(con, "hermes", chat="peers")
            self.assertEqual(cont["action"], "continue")
            self.assertEqual(cont["task"]["id"], t["id"])

    def test_tick_blocks_when_gates_fail(self):
        con = fresh()
        roster.seed_if_needed(con)
        roster.add_task(
            con, "on-device: blocked-tick", assignee="hermes", chat="peers")
        with mock.patch.object(checks, "agent_ready", return_value={
            "agent": "hermes", "ready": False, "blocked": True,
            "failed": ["brain"], "results": {}, "policy": {},
        }):
            out = roster.board_tick(con, "hermes", claim=True)
        self.assertEqual(out["action"], "block")
        self.assertIsNone(out["task"])

    def test_reassign_reopens_claimed(self):
        con = fresh()
        roster.seed_if_needed(con)
        t = roster.add_task(
            con, "on-device: move-me", assignee="hermes", chat="peers")
        claimed = roster.claim_task(con, t["id"], "hermes")
        self.assertEqual(claimed["status"], "claimed")
        out = roster.reassign_task(
            con, t["id"], "cursor", by="mazin")
        self.assertEqual(out["to"], "cursor")
        self.assertTrue(out["reopened"])
        self.assertEqual(out["task"]["status"], "open")
        self.assertEqual(out["task"]["assignee"], "cursor")

    def test_mcp_board_tick_and_reassign(self):
        con = fresh()
        roster.seed_if_needed(con)
        t = roster.add_task(
            con, "on-device: mcp-tick", assignee="hermes", chat="peers")
        with mock.patch.object(checks, "agent_ready", return_value={
            "agent": "hermes", "ready": True, "blocked": False,
            "failed": [], "results": {}, "policy": {},
        }):
            tick = mcp._board_tick(_Brain(con), {
                "agent": "hermes", "claim": True})
        self.assertEqual(tick["action"], "claimed")
        moved = mcp._reassign_task(_Brain(con), {
            "id": t["id"], "to_agent": "grok-bot", "by": "cursor"})
        self.assertEqual(moved["task"]["assignee"], "grok-bot")
        self.assertTrue(moved["reopened"])

    def test_poll_includes_board_tick(self):
        con = fresh()
        roster.seed_if_needed(con)
        checks.set_policy(con, "hermes", {
            "gates": [],
            "poll": {"every_min": 5, "actions": ["peer_inbox", "board_tick"]},
            "on_fail": "warn",
        })
        roster.add_task(
            con, "on-device: poll-tick", assignee="hermes", chat="peers")
        out = checks.agent_poll(con, "hermes")
        self.assertIn("board_tick", out["actions"])
        self.assertEqual(out["actions"]["board_tick"]["action"], "claim")


if __name__ == "__main__":
    unittest.main()
