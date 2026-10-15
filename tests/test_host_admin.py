"""Per-board host: each agent hosts at most one board; self-mint allowed."""
import json
import os
import tempfile
import unittest
from unittest import mock

from agent_context import roster, store


def fresh():
    return store.connect(":memory:")


class _Brain:
    def __init__(self, con):
        self.con = con


class HostedBoard(unittest.TestCase):
    def test_peers_migrates_global_admin_to_host(self):
        con = fresh()
        # Pre-set legacy flag then re-ensure via set_host path
        roster.set_host(con, "cursor", chat="peers")
        b = roster.get_board(con, chat="peers")
        self.assertEqual(b["host_agent"], "cursor")
        agents = {a["name"]: a for a in roster.list_agents(con)}
        self.assertTrue(agents["cursor"]["is_admin"])

    def test_each_agent_hosts_one_board(self):
        con = fresh()
        roster.create_hosted_board(con, "hermes-lab", "hermes")
        with self.assertRaises(ValueError) as cm:
            roster.create_hosted_board(con, "hermes-lab-2", "hermes")
        self.assertIn("already host", str(cm.exception))
        mine = roster.hosted_board(con, "hermes")
        self.assertEqual(mine["chat"], "hermes-lab")
        self.assertEqual(mine["host_agent"], "hermes")
        members = {m["agent"]: m["role"] for m in mine["members"]}
        self.assertEqual(members["hermes"], "admin")
        # personal boards do not seed default workers
        self.assertNotIn("cursor", members)

    def test_cannot_steal_existing_chat(self):
        con = fresh()
        roster.create_hosted_board(con, "orbit", "hermes")
        with self.assertRaises(ValueError):
            roster.create_hosted_board(con, "orbit", "cursor")

    def test_transfer_host_enforces_one(self):
        con = fresh()
        roster.create_hosted_board(con, "hermes-lab", "hermes")
        with self.assertRaises(ValueError):
            roster.set_host(con, "hermes", chat="peers")


class WhoamiHost(unittest.TestCase):
    def test_host_key_gets_admin_true_with_agent(self):
        con = fresh()
        roster.set_host(con, "cursor", chat="peers")
        key = roster.mint_agent_key(con, "cursor")
        out = roster.whoami(con, key["token"])
        self.assertTrue(out["admin"])
        self.assertTrue(out["key_ok"])
        self.assertEqual(out["agent"], "cursor")
        self.assertTrue(out["host"])
        self.assertEqual(out["hosted_chat"], "peers")

    def test_plain_agent_key_stays_not_admin(self):
        con = fresh()
        roster.set_host(con, "cursor", chat="peers")
        key = roster.mint_agent_key(con, "grok-bot")
        out = roster.whoami(con, key["token"])
        self.assertFalse(out["admin"])
        self.assertEqual(out["agent"], "grok-bot")
        self.assertFalse(out.get("host", False))
        self.assertIsNone(out.get("hosted_chat"))


class SelfMint(unittest.TestCase):
    def test_connected_agent_remints_self(self):
        con = fresh()
        first = roster.mint_agent_key(con, "hermes-connector")
        second = roster.mint_for_caller(
            con, first["token"], name="hermes-connector")
        self.assertNotEqual(first["token"], second["token"])
        self.assertIsNone(roster.agent_token_ok(con, first["token"]))
        self.assertEqual(
            roster.agent_token_ok(con, second["token"]), "hermes-connector")

    def test_plain_agent_cannot_mint_other(self):
        con = fresh()
        roster.set_host(con, "cursor", chat="peers")
        key = roster.mint_agent_key(con, "grok-bot")
        with self.assertRaises(PermissionError):
            roster.mint_for_caller(
                con, key["token"], name="hermes-connector", chat="peers")

    def test_board_host_mints_invitee(self):
        con = fresh()
        roster.create_hosted_board(con, "lab", "hermes")
        host_key = roster.mint_agent_key(con, "hermes")
        out = roster.mint_for_caller(
            con, host_key["token"], name="helper", chat="lab")
        self.assertEqual(out["agent"], "helper")
        self.assertEqual(roster.agent_token_ok(con, out["token"]), "helper")


class ResolveAdmin(unittest.TestCase):
    def test_admin_token_resolves(self):
        con = fresh()
        self.assertTrue(roster.resolve_admin(con, "boot-token", "boot-token"))

    def test_host_key_resolves_admin(self):
        con = fresh()
        roster.set_host(con, "cursor", chat="peers")
        key = roster.mint_agent_key(con, "cursor")
        self.assertTrue(roster.resolve_admin(con, key["token"], "boot-token"))

    def test_plain_key_and_garbage_do_not(self):
        con = fresh()
        roster.set_host(con, "cursor", chat="peers")
        key = roster.mint_agent_key(con, "grok-bot")
        self.assertFalse(roster.resolve_admin(con, key["token"], "boot-token"))
        self.assertFalse(roster.resolve_admin(con, "", "boot-token"))
        self.assertFalse(roster.resolve_admin(con, "garbage", "boot-token"))

    def test_can_manage_board_scoped(self):
        con = fresh()
        roster.create_hosted_board(con, "lab", "hermes")
        roster.set_host(con, "cursor", chat="peers")
        h = roster.mint_agent_key(con, "hermes")["token"]
        c = roster.mint_agent_key(con, "cursor")["token"]
        self.assertTrue(roster.can_manage_board(con, h, chat="lab"))
        self.assertFalse(roster.can_manage_board(con, h, chat="peers"))
        self.assertTrue(roster.can_manage_board(con, c, chat="peers"))
        self.assertFalse(roster.can_manage_board(con, c, chat="lab"))


class ServerGate(unittest.TestCase):
    """server.Handler helpers against a sandbox DB."""

    @classmethod
    def setUpClass(cls):
        cfg = {"db_path": os.path.join(tempfile.mkdtemp(), "t.db"),
               "sources": [], "llm": {}}
        cfg_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        with open(cfg_path, "w") as f:
            json.dump(cfg, f)
        os.environ["AGENT_MANAGER_CONFIG"] = cfg_path
        import server  # noqa: PLC0415 — needs the env override above
        cls.server = server

    def test_handler_admin_helpers(self):
        con = fresh()
        roster.set_host(con, "cursor", chat="peers")
        key = roster.mint_agent_key(con, "cursor")["token"]
        plain = roster.mint_agent_key(con, "grok-bot")["token"]
        h = self.server.Handler.__new__(self.server.Handler)
        srv = self.server
        cases = [
            (key, True, False),      # board host → host yes, bootstrap no
            (plain, False, False),   # plain agent key → neither
            ("boot-token", True, True),
            ("", False, False),
        ]
        with mock.patch.object(srv, "BRAIN", _Brain(con)), \
                mock.patch.object(srv, "ADMIN_TOKEN", "boot-token"):
            for tok, is_host, is_boot in cases:
                with mock.patch.object(
                        srv, "presented_token",
                        lambda _h, t=tok: t):  # noqa: B008 — deliberate bind
                    self.assertEqual(h._is_host(), is_host, tok)
                    self.assertEqual(h._is_bootstrap_admin(), is_boot, tok)
