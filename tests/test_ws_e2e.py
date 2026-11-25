"""HTTP e2e script: runs every acceptance check against a stub server."""
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "ws_e2e", os.path.join(ROOT, "scripts", "ws_e2e.py"))
ws_e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws_e2e)

TOKEN = "test-token"
SLUGS = ["health-auditor", "ring-lab", "ship-watch", "coach-builder",
         "brain-ops", "dwm-lab", "voice-lab", "scout"]


class Stub:
    fail_list = False
    posts = []
    messages = []
    run_calls = []
    user_agents = []

    @classmethod
    def reset(cls):
        cls.fail_list = False
        cls.posts = []
        cls.messages = []
        cls.run_calls = []
        cls.user_agents = []


def agent(slug):
    return {"slug": slug, "name": slug.title(), "status": "idle",
            "cron": {"count": 0, "live": 0, "missing": 0}, "schedule": "on demand",
            "source_job_ids": [], "last_run": None}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, obj, ctype="application/json"):
        raw = obj.encode() if isinstance(obj, str) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authed(self):
        return self.headers.get("X-Token") == TOKEN

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw)
        except ValueError:
            return {}

    def do_GET(self):
        Stub.user_agents.append(self.headers.get("User-Agent") or "")
        path = urlparse(self.path).path
        host = self.headers.get("Host") or "127.0.0.1"
        base = "http://" + host
        if path == "/api/ws/agents":
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            if Stub.fail_list:
                return self._send(500, {"error": "boom"})
            return self._send(200, {"agents": [agent(s) for s in SLUGS],
                                    "count": len(SLUGS)})
        if path == "/.well-known/agent-card.json":
            return self._send(200, {
                "protocolVersion": "0.3.0", "name": "Agent Manager",
                "url": base + "/a2a",
                "skills": [{"id": s} for s in SLUGS]})
        if path in ("/bot", "/bot/"):
            return self._send(200, '<html><aside id="rail"></aside>'
                                    '<div id="token-gate"></div>'
                                    '<form class="composer" id="composer"></form>'
                                    '</html>', "text/html")
        if path.startswith("/api/ws/agents/"):
            parts = path.strip("/").split("/")
            slug = parts[3] if len(parts) > 3 else ""
            rest = parts[4] if len(parts) > 4 else ""
            if slug not in SLUGS:
                return self._send(404, {"error": f"unknown agent: {slug}"})
            if rest == "card":
                return self._send(200, {
                    "protocolVersion": "0.3.0", "name": slug.title(),
                    "url": base + f"/api/ws/agents/{slug}"})
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            if rest == "messages":
                return self._send(200, {"agent": slug, "messages": [
                    {"role": "user", "body": b} for b in Stub.messages]})
            if rest == "runs":
                return self._send(200, {"agent": slug, "runs": []})
            return self._send(200, {
                "slug": slug, "status": "idle", "last_run": None,
                "messages": [], "runs": [],
                "chips": {"chips": [{"label": "Run now"}],
                          "ghost": "What is the latest on health?"}})
        if path == "/api/ws/peers":
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            return self._send(200, {"peers": [], "count": 0})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        Stub.user_agents.append(self.headers.get("User-Agent") or "")
        path = urlparse(self.path).path
        payload = self._body()
        Stub.posts.append((path, payload))
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        if path == "/a2a":
            if payload.get("method") != "message/send":
                return self._send(200, {"jsonrpc": "2.0", "id": payload.get("id"),
                                        "error": {"code": -32601,
                                                  "message": "method not found"}})
            return self._send(200, {
                "jsonrpc": "2.0", "id": payload.get("id"),
                "result": {"kind": "task", "id": "a2a-stub",
                           "status": {"state": "completed"},
                           "artifacts": [{"parts": [{"kind": "text",
                                                     "text": "Stub A2A reply."}]}]}})
        if path.startswith("/api/ws/agents/"):
            parts = path.strip("/").split("/")
            slug, action = parts[3], parts[4] if len(parts) > 4 else ""
            if slug not in SLUGS:
                return self._send(404, {"error": f"unknown agent: {slug}"})
            if action == "messages":
                Stub.messages.append(payload.get("body") or "")
                return self._send(200, {
                    "agent": slug, "reply": "Stub brain reply.", "run_id": "run-1",
                    "events": [{"type": "RUN_STARTED"},
                               {"type": "TEXT_MESSAGE_CONTENT"},
                               {"type": "RUN_FINISHED"}]})
            if action == "to":
                return self._send(200, {"task_id": "a2a-deadbeef"})
            if action == "run":
                Stub.run_calls.append(payload.get("job_id") or "2d5f972a5570")
                return self._send(200, {
                    "agent": slug, "job_id": payload.get("job_id") or "2d5f972a5570",
                    "run": {"id": "run-2", "status": "ok"},
                    "runner": {"ok": True}})
        return self._send(404, {"error": "not found"})


class WsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Stub.reset()

    def test_all_checks_pass_with_writes(self):
        ev = ws_e2e.run_e2e(self.base, TOKEN, run_job=True)
        self.assertTrue(ev["ok"], [c for c in ev["checks"] if c["ok"] is False])
        self.assertEqual(ev["summary"]["failed"], 0)
        self.assertEqual(ev["summary"]["skipped"], 0)
        self.assertEqual(ev["summary"]["total"], len(ev["checks"]))
        self.assertGreaterEqual(ev["summary"]["total"], 17)
        by_id = {c["id"]: c for c in ev["checks"]}
        self.assertIn("Stub brain reply", by_id["chat_reply"]["detail"])
        self.assertIn("completed", by_id["a2a_message_send"]["detail"])
        self.assertTrue(by_id["run_now"]["ok"])
        self.assertEqual(Stub.run_calls, ["2d5f972a5570"])
        self.assertEqual(ws_e2e.exit_code(ev), 0)

    def test_no_writes_skips_side_effects(self):
        ev = ws_e2e.run_e2e(self.base, TOKEN, include_writes=False)
        self.assertTrue(ev["ok"])
        skipped = [c["id"] for c in ev["checks"] if c["skipped"]]
        self.assertEqual(sorted(skipped), sorted([
            "chat_reply", "chat_persisted", "peer_send", "a2a_message_send",
            "run_now"]))
        self.assertEqual([p for p, _ in Stub.posts], ["/a2a"])
        self.assertEqual(Stub.messages, [])
        self.assertEqual(Stub.run_calls, [])

    def test_explicit_user_agent(self):
        ws_e2e.run_e2e(self.base, TOKEN, include_writes=False)
        self.assertTrue(Stub.user_agents)
        self.assertTrue(all("agent-manager-e2e" in ua
                            for ua in Stub.user_agents))

    def test_token_never_in_evidence(self):
        ev = ws_e2e.run_e2e(self.base, TOKEN, run_job=True)
        self.assertTrue(ev["token_present"])
        self.assertNotIn(TOKEN, json.dumps(ev))

    def test_failure_is_reported(self):
        Stub.fail_list = True
        ev = ws_e2e.run_e2e(self.base, TOKEN, include_writes=False)
        self.assertFalse(ev["ok"])
        self.assertEqual(ev["summary"]["failed"], 1)
        by_id = {c["id"]: c for c in ev["checks"]}
        self.assertFalse(by_id["list_agents"]["ok"])
        self.assertEqual(by_id["list_agents"]["status"], 500)
        self.assertEqual(ws_e2e.exit_code(ev), 1)

    def test_write_evidence_files(self):
        ev = ws_e2e.run_e2e(self.base, TOKEN, include_writes=False)
        with tempfile.TemporaryDirectory() as tmp:
            path, latest = ws_e2e.write_evidence(ev, tmp)
            self.assertTrue(os.path.isfile(path))
            self.assertTrue(os.path.isfile(latest))
            self.assertRegex(os.path.basename(path),
                             r"^http-e2e-\d{8}T\d{6}\.json$")
            with open(latest) as f:
                loaded = json.load(f)
            self.assertEqual(loaded["summary"], ev["summary"])
            self.assertEqual(loaded["kind"], "agents-workspace-http-e2e")

    def test_load_token(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("# comment\nAGENT_MANAGER_TOKEN=secret-value\nOTHER=1\n")
            path = f.name
        try:
            self.assertEqual(ws_e2e.load_token(path), "secret-value")
        finally:
            os.unlink(path)
        self.assertEqual(ws_e2e.load_token("/nonexistent/.env"), "")


if __name__ == "__main__":
    unittest.main()
