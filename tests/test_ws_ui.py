"""Workspace UI: /bot/ page served, nav wired, server-composed chips.

The page is a static shell; these tests pin the contract the shell must keep:
server-composed chips (no client-invented labels), the 390 px layout hooks,
the peer tab, and the /bot/ route in server.py.
"""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class BotPageShell(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read("static/bot.html")

    def test_regions_present(self):
        for marker in ('id="rail"', 'id="agent-groups"', 'id="thread"',
                       'id="composer"', 'id="chips"', 'id="drawer"',
                       'id="peers-view"', 'id="empty"', 'id="token-gate"'):
            self.assertIn(marker, self.html, marker)

    def test_chips_come_from_server(self):
        # The server composes chips and the ghost; the page must not hardcode
        # chip labels of its own.
        self.assertIn("chips.chips", self.html)
        self.assertIn("chips.ghost", self.html)
        # The chip row starts empty; labels only arrive from the server.
        self.assertIn('<div class="chips" id="chips"></div>', self.html)
        for label in ("Run now", "Open inbox", "Last run"):
            self.assertNotIn(label, self.html, label)

    def test_ghost_fills_without_send(self):
        # Ghost prompt becomes the composer placeholder; filling a chip puts
        # text in the input, it never submits on its own.
        self.assertIn("placeholder = ghost", self.html)
        self.assertIn("kind === 'prompt'", self.html)

    def test_mobile_390_layout(self):
        self.assertIn("@media (max-width:879px)", self.html)
        self.assertIn("chat-open", self.html)
        self.assertIn("min-width:0", self.html)

    def test_peer_tab(self):
        self.assertIn("/api/ws/peers", self.html)
        self.assertIn("task_id", self.html)
        self.assertIn("data-tab=\"peers\"", self.html)

    def test_drawer_controls(self):
        self.assertIn("/api/ws/agents/", self.html)
        self.assertIn("method:'PATCH'", self.html.replace(" ", ""))
        self.assertIn("system_prompt", self.html)
        self.assertIn("CURRENT.cron", self.html)

    def test_rail_shows_live_cron_next_run(self):
        # The rail line is derived from the live cron registry (next run +
        # job count), not from the seed's static schedule string.
        self.assertIn("a.cron", self.html)
        self.assertIn("next_run_ts", self.html)
        self.assertIn("function untilTime", self.html)
        self.assertIn("function cronNext", self.html)

    def test_drawer_lists_live_cron_jobs(self):
        self.assertIn("function cronRow", self.html)
        self.assertIn("not in the cron registry", self.html)
        self.assertIn("j.last_status", self.html)
        self.assertIn("j.next_run_ts", self.html)

    def test_select_agent_resets_to_chat_tab(self):
        # Picking an agent while the Peers tab is open must switch the pane
        # back to chat, not leave the peer list over a chat-labelled header.
        self.assertIn("setTab('chat');", self.html)

    def test_agui_events_consumed(self):
        self.assertIn("RUN_STARTED", self.html)
        self.assertIn("TEXT_MESSAGE_CONTENT", self.html)
        self.assertIn("RUN_FINISHED", self.html)

    def test_nav_links_bot(self):
        for page in ("static/home.html", "static/agents.html",
                     "static/setup.html",
                     "agent_context/static/index.html"):
            body = read(page)
            self.assertIn('href="/bot/"', body, page)
            self.assertIn(">Bot<", body, page)


class BotRoute(unittest.TestCase):
    """Serve /bot/ from a temp-config server (never the prod brain.db)."""

    @classmethod
    def setUpClass(cls):
        cfg = {"db_path": os.path.join(tempfile.mkdtemp(), "t.db"),
               "sources": [], "llm": {}}
        cfg_path = os.path.join(tempfile.mkdtemp(), "cfg.json")
        with open(cfg_path, "w") as f:
            json.dump(cfg, f)
        os.environ.setdefault("AGENT_MANAGER_CONFIG", cfg_path)
        import server  # noqa: PLC0415 — needs the env override above
        cls.server = server
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def fetch(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def test_bot_page_served(self):
        for path in ("/bot", "/bot/"):
            code, body = self.fetch(path)
            self.assertEqual(code, 200, path)
            self.assertIn('id="rail"', body)
            self.assertIn('id="composer"', body)

    def test_favicon_not_gated(self):
        # Chrome requests /favicon.ico without a token on every page; it must
        # not fall through to the 401 auth gate and spam the console.
        code, body = self.fetch("/favicon.ico")
        self.assertEqual(code, 204)
        self.assertEqual(body, "")

    def test_ws_api_still_gated(self):
        code, body = self.fetch("/api/ws/agents")
        self.assertEqual(code, 401)
        self.assertIn("unauthorized", body)

    def test_nav_on_home(self):
        code, body = self.fetch("/")
        self.assertEqual(code, 200)
        self.assertIn('href="/bot/"', body)


if __name__ == "__main__":
    unittest.main()
