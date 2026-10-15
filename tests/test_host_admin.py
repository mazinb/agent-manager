"""Host-agent admin: one flagged agent's key carries admin scope."""
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


class HostFlag(unittest.TestCase):
    def test_set_host_flags_one_agent_only(self):
        con = fresh()
        roster.set_host(con, "cursor")
        roster.set_host(con, "hermes")
        self.assertEqual(roster.host_agent(con), "hermes")
        agents = {a["name"]: a for a in roster.list_agents(con)}
        self.assertTrue(agents["hermes"]["is_admin"])
        self.assertFalse(agents["cursor"]["is_admin"])

    def test_set_host_requires_existing_agent(self):
        con = fresh()
        with self.assertRaises(ValueError):
            roster.set_host(con, "ghost")
        self.assertIsNone(roster.host_agent(con))

    def test_set_host_off(self):
        con = fresh()
        roster.set_host(con, "cursor")
        roster.set_host(con, "cursor", on=False)
        self.assertIsNone(roster.host_agent(con))


class WhoamiHost(unittest.TestCase):
    def test_host_key_gets_admin_true_with_agent(self):
        con = fresh()
        roster.set_host(con, "cursor")
        key = roster.mint_agent_key(con, "cursor")
        out = roster.whoami(con, key["token"])
        self.assertTrue(out["admin"])
        self.assertTrue(out["key_ok"])
        self.assertEqual(out["agent"], "cursor")
        self.assertTrue(out["host"])

    def test_plain_agent_key_stays_not_admin(self):
        con = fresh()
        roster.set_host(con, "cursor")
        key = roster.mint_agent_key(con, "grok-bot")
        out = roster.whoami(con, key["token"])
        self.assertFalse(out["admin"])
        self.assertEqual(out["agent"], "grok-bot")
        self.assertFalse(out.get("host", False))


class ResolveAdmin(unittest.TestCase):
    def test_admin_token_resolves(self):
        con = fresh()
        self.assertTrue(roster.resolve_admin(con, "boot-token", "boot-token"))

    def test_host_key_resolves_admin(self):
        con = fresh()
        roster.set_host(con, "cursor")
        key = roster.mint_agent_key(con, "cursor")
        self.assertTrue(roster.resolve_admin(con, key["token"], "boot-token"))

    def test_plain_key_and_garbage_do_not(self):
        con = fresh()
        roster.set_host(con, "cursor")
        key = roster.mint_agent_key(con, "grok-bot")
        self.assertFalse(roster.resolve_admin(con, key["token"], "boot-token"))
        self.assertFalse(roster.resolve_admin(con, "", "boot-token"))
        self.assertFalse(roster.resolve_admin(con, "garbage", "boot-token"))

    def test_stale_host_key_after_transfer(self):
        con = fresh()
        roster.set_host(con, "cursor")
        key = roster.mint_agent_key(con, "cursor")
        roster.set_host(con, "hermes")
        self.assertFalse(roster.resolve_admin(con, key["token"], "boot-token"))


class ServerGate(unittest.TestCase):
    """server.Handler._is_host / _is_bootstrap_admin against a sandbox DB."""

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
        roster.set_host(con, "cursor")
        key = roster.mint_agent_key(con, "cursor")["token"]
        plain = roster.mint_agent_key(con, "grok-bot")["token"]
        h = self.server.Handler.__new__(self.server.Handler)
        srv = self.server
        cases = [
            (key, True, False),      # host key → host yes, bootstrap no
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
