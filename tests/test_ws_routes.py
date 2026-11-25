"""Workspace HTTP route logic: GET/POST/PATCH dispatch, run now, A2A."""
import unittest

from agent_context import store, ws, ws_routes


def fresh():
    con = store.connect(":memory:")
    ws.seed(con)
    return con


def fake_chat(reply="Brain reply."):
    calls = []

    def _fn(system, messages):
        calls.append({"system": system, "messages": messages})
        return reply

    _fn.calls = calls
    return _fn


CFG = {"base_url": "http://127.0.0.1:8888/v1", "model": "test-model"}


class WsRouteGet(unittest.TestCase):
    def setUp(self):
        self.con = fresh()

    def test_unknown_path_is_not_ours(self):
        self.assertIsNone(ws_routes.get(self.con, "/api/roster/agents"))
        self.assertIsNone(ws_routes.get(self.con, "/api/ws/agents/ring-lab/x"))

    def test_list_agents(self):
        code, body = ws_routes.get(self.con, "/api/ws/agents")
        self.assertEqual(code, 200)
        self.assertEqual(body["count"], 8)
        self.assertEqual(len(body["agents"]), 8)

    def test_agent_detail_has_thread_runs_chips(self):
        code, body = ws_routes.get(self.con, "/api/ws/agents/ring-lab",
                                   base_url="https://bot.getzoro.com")
        self.assertEqual(code, 200)
        self.assertEqual(body["slug"], "ring-lab")
        for key in ("messages", "runs", "chips", "status", "last_run"):
            self.assertIn(key, body)
        self.assertTrue(body["chips"]["ghost"])

    def test_messages_and_runs_limits(self):
        for i in range(5):
            ws.add_message(self.con, "scout", "user", f"m{i}")
        code, body = ws_routes.get(self.con, "/api/ws/agents/scout/messages",
                                   {"limit": ["2"]})
        self.assertEqual(code, 200)
        self.assertEqual(len(body["messages"]), 2)
        ws.record_run(self.con, "scout", job_id="j", status="ok", summary="x")
        code, body = ws_routes.get(self.con, "/api/ws/agents/scout/runs")
        self.assertEqual(code, 200)
        self.assertEqual(len(body["runs"]), 1)

    def test_unknown_agent_is_404(self):
        for path in ("/api/ws/agents/nope", "/api/ws/agents/nope/messages",
                     "/api/ws/agents/nope/runs", "/api/ws/agents/nope/card"):
            code, body = ws_routes.get(self.con, path)
            self.assertEqual(code, 404, path)
            self.assertIn("unknown agent", body["error"])

    def test_agent_card(self):
        code, body = ws_routes.get(self.con, "/api/ws/agents/ring-lab/card",
                                   base_url="https://bot.getzoro.com")
        self.assertEqual(code, 200)
        self.assertEqual(body["url"],
                         "https://bot.getzoro.com/api/ws/agents/ring-lab")
        self.assertEqual(body["protocolVersion"], "0.3.0")

    def test_well_known_card(self):
        card = ws_routes.well_known(self.con, "https://bot.getzoro.com")
        self.assertEqual(card["url"], "https://bot.getzoro.com/a2a")
        self.assertEqual(len(card["skills"]), 8)

    def test_peers_filters(self):
        a = ws.send_peer(self.con, "scout", "ring-lab", "one")
        ws.send_peer(self.con, "scout", "ring-lab", "two")
        ws.mark_peer_read(self.con, a["id"])
        code, body = ws_routes.get(self.con, "/api/ws/peers",
                                   {"unread": ["1"], "to": ["ring-lab"]})
        self.assertEqual(code, 200)
        self.assertEqual([p["body"] for p in body["peers"]], ["two"])

    def test_base_from_host(self):
        self.assertEqual(ws_routes.base_from_host("bot.getzoro.com"),
                         "https://bot.getzoro.com")
        self.assertEqual(ws_routes.base_from_host("127.0.0.1:8075"),
                         "http://127.0.0.1:8075")


class WsRouteChat(unittest.TestCase):
    def setUp(self):
        self.con = fresh()

    def test_post_message_returns_agui_json(self):
        fn = fake_chat("82 percent.")
        code, body = ws_routes.post(
            self.con, "/api/ws/agents/health-auditor/messages",
            {"body": "How was sleep?"}, llm_cfg=CFG, chat_fn=fn)
        self.assertEqual(code, 200)
        self.assertEqual(body["reply"], "82 percent.")
        self.assertEqual([e["type"] for e in body["events"]],
                         ["RUN_STARTED", "TEXT_MESSAGE_CONTENT",
                          "RUN_FINISHED"])
        self.assertEqual(len(ws.list_messages(self.con, "health-auditor")), 2)

    def test_post_message_empty_and_unknown(self):
        code, body = ws_routes.post(self.con, "/api/ws/agents/scout/messages",
                                    {"body": "  "}, llm_cfg=CFG,
                                    chat_fn=fake_chat())
        self.assertEqual(code, 400)
        code, body = ws_routes.post(self.con, "/api/ws/agents/nope/messages",
                                    {"body": "hi"}, llm_cfg=CFG,
                                    chat_fn=fake_chat())
        self.assertEqual(code, 404)

    def test_other_post_paths_not_ours(self):
        self.assertIsNone(ws_routes.post(self.con, "/api/note", {}))


class WsRouteRun(unittest.TestCase):
    def setUp(self):
        self.con = fresh()

    def test_run_now_records_ok(self):
        calls = []

        def runner(job_id):
            calls.append(job_id)
            return {"ok": True, "returncode": 0, "output": "sweep finished"}

        code, body = ws_routes.post(
            self.con, "/api/ws/agents/health-auditor/run", {}, runner=runner)
        self.assertEqual(code, 200)
        self.assertEqual(calls, ["2d5f972a5570"])
        self.assertEqual(body["run"]["status"], "ok")
        self.assertEqual(body["run"]["job_id"], "2d5f972a5570")
        runs = ws.list_runs(self.con, "health-auditor")
        self.assertEqual(runs[0]["status"], "ok")
        self.assertIn("sweep finished", runs[0]["summary"])

    def test_run_now_failure_is_recorded_and_502(self):
        def runner(job_id):
            return {"ok": False, "returncode": 1, "output": "boom"}

        code, body = ws_routes.post(
            self.con, "/api/ws/agents/ship-watch/run", {}, runner=runner)
        self.assertEqual(code, 502)
        self.assertEqual(body["run"]["status"], "error")
        runs = ws.list_runs(self.con, "ship-watch")
        self.assertEqual(runs[0]["status"], "error")

    def test_run_now_job_must_be_source(self):
        code, body = ws_routes.post(
            self.con, "/api/ws/agents/ship-watch/run",
            {"job_id": "deadbeef"}, runner=lambda j: {"ok": True})
        self.assertEqual(code, 400)
        self.assertIn("not a source job", body["error"])

    def test_run_now_on_demand_agent_rejected(self):
        code, body = ws_routes.post(
            self.con, "/api/ws/agents/scout/run", {},
            runner=lambda j: {"ok": True})
        self.assertEqual(code, 400)
        self.assertIn("no scheduled job", body["error"])


class WsRoutePatch(unittest.TestCase):
    def setUp(self):
        self.con = fresh()

    def test_patch_prompt_and_enabled(self):
        code, body = ws_routes.patch(
            self.con, "/api/ws/agents/scout",
            {"system_prompt": "new prompt", "enabled": False, "junk": 1})
        self.assertEqual(code, 200)
        self.assertEqual(body["system_prompt"], "new prompt")
        self.assertFalse(body["enabled"])

    def test_patch_no_fields_and_unknown(self):
        code, body = ws_routes.patch(self.con, "/api/ws/agents/scout", {})
        self.assertEqual(code, 400)
        self.assertIn("patchable", body)
        code, body = ws_routes.patch(self.con, "/api/ws/agents/nope",
                                     {"name": "x"})
        self.assertEqual(code, 404)

    def test_patch_ignores_non_agent_paths(self):
        self.assertIsNone(ws_routes.patch(self.con, "/api/ws/agents", {}))


class WsRoutePeers(unittest.TestCase):
    def setUp(self):
        self.con = fresh()

    def test_post_peer(self):
        code, body = ws_routes.post(
            self.con, "/api/ws/agents/health-auditor/to",
            {"to": "ring-lab", "body": "share the curve"})
        self.assertEqual(code, 200)
        self.assertTrue(body["task_id"].startswith("a2a-"))
        code, peers = ws_routes.get(self.con, "/api/ws/peers")
        self.assertEqual(peers["count"], 1)

    def test_mark_read(self):
        out = ws.send_peer(self.con, "scout", "ring-lab", "one")
        code, body = ws_routes.post(self.con, "/api/ws/peers/read",
                                    {"id": out["id"]})
        self.assertEqual(code, 200)
        self.assertIsNotNone(body["read_at"])

    def test_peer_unknown_agent_404(self):
        code, body = ws_routes.post(self.con, "/api/ws/agents/nope/to",
                                    {"to": "scout", "body": "hi"})
        self.assertEqual(code, 404)


class WsA2A(unittest.TestCase):
    def setUp(self):
        self.con = fresh()

    def req(self, **over):
        payload = {
            "jsonrpc": "2.0", "id": "req-1", "method": "message/send",
            "params": {"metadata": {"agent": "ring-lab"},
                       "message": {"messageId": "m-1", "role": "user",
                                   "parts": [{"kind": "text",
                                              "text": "battery trend?"}]}},
        }
        payload.update(over)
        return payload

    def test_message_send_returns_completed_task(self):
        fn = fake_chat("Drain is 0.4/h.")
        out = ws_routes.a2a(self.con, self.req(), llm_cfg=CFG, chat_fn=fn)
        self.assertEqual(out["jsonrpc"], "2.0")
        self.assertEqual(out["id"], "req-1")
        task = out["result"]
        self.assertEqual(task["kind"], "task")
        self.assertEqual(task["status"]["state"], "completed")
        self.assertEqual(task["metadata"]["agent"], "ring-lab")
        self.assertEqual(task["artifacts"][0]["parts"][0]["text"],
                         "Drain is 0.4/h.")
        self.assertIn("Ring Lab", fn.calls[0]["system"])

    def test_message_send_brain_failure_is_failed_task(self):
        out = ws_routes.a2a(self.con, self.req(), llm_cfg=CFG,
                            chat_fn=lambda s, m: None)
        self.assertEqual(out["result"]["status"]["state"], "failed")
        self.assertIn("unreachable",
                      out["result"]["artifacts"][0]["parts"][0]["text"].lower())

    def test_errors(self):
        out = ws_routes.a2a(self.con, {"jsonrpc": "1.0", "id": 7,
                                       "method": "message/send"})
        self.assertEqual(out["error"]["code"], -32600)
        out = ws_routes.a2a(self.con, self.req(method="tasks/get"))
        self.assertEqual(out["error"]["code"], -32601)
        out = ws_routes.a2a(self.con, self.req(
            params={"message": {"parts": [{"kind": "text", "text": "x"}]}}))
        self.assertEqual(out["error"]["code"], -32602)
        out = ws_routes.a2a(self.con, self.req(
            params={"metadata": {"agent": "ghost"},
                    "message": {"parts": [{"kind": "text", "text": "x"}]}}))
        self.assertEqual(out["error"]["code"], -32001)


if __name__ == "__main__":
    unittest.main()
