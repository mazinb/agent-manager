"""Agents workspace: schema, seed, CRUD, chat, runs, peer bus, A2A cards."""
import unittest

from agent_context import store, ws


def fresh():
    return store.connect(":memory:")


def fake_chat(reply="Brain reply."):
    calls = []

    def _fn(system, messages):
        calls.append({"system": system, "messages": messages})
        return reply

    _fn.calls = calls
    return _fn


class WsSeed(unittest.TestCase):
    def test_seed_is_idempotent_and_keeps_edited_prompt(self):
        con = fresh()
        first = ws.seed(con)
        self.assertEqual(first["inserted"], 8)
        self.assertEqual(len(ws.list_agents(con)), 8)
        ws.patch_agent(con, "ring-lab", system_prompt="edited prompt")
        second = ws.seed(con)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(len(ws.list_agents(con)), 8)
        self.assertEqual(ws.get_agent(con, "ring-lab")["system_prompt"],
                         "edited prompt")

    def test_seed_rows_carry_schedule_and_job_ids(self):
        con = fresh()
        ws.seed(con)
        a = ws.get_agent(con, "health-auditor")
        self.assertEqual(a["name"], "Health Auditor")
        self.assertEqual(a["avatar"], "HA")
        self.assertEqual(len(a["source_job_ids"]), 5)
        self.assertIn("04:00", a["schedule"])
        self.assertTrue(a["enabled"])


class WsAgents(unittest.TestCase):
    def setUp(self):
        self.con = fresh()
        ws.seed(self.con)

    def test_list_shape_status_idle(self):
        agents = ws.list_agents(self.con)
        self.assertEqual(len(agents), 8)
        a = next(x for x in agents if x["slug"] == "scout")
        self.assertEqual(a["status"], "idle")
        self.assertIsNone(a["last_run"])
        self.assertIn("purpose", a)
        self.assertIsInstance(a["source_job_ids"], list)

    def test_get_unknown_raises(self):
        with self.assertRaises(ValueError):
            ws.get_agent(self.con, "nope")

    def test_get_includes_messages_runs_chips(self):
        a = ws.get_agent(self.con, "health-auditor")
        self.assertIn("messages", a)
        self.assertIn("runs", a)
        chips = a["chips"]
        labels = [c["label"] for c in chips["chips"]]
        self.assertIn("Run now", labels)
        self.assertIn("Last run", labels)
        self.assertTrue(chips["ghost"])
        for c in chips["chips"]:
            self.assertIn("kind", c)
            self.assertIn(c["kind"], ("run", "prompt", "drawer", "inbox"))

    def test_on_demand_agent_has_no_run_now(self):
        a = ws.get_agent(self.con, "scout")
        labels = [c["label"] for c in a["chips"]["chips"]]
        self.assertNotIn("Run now", labels)

    def test_patch_agent(self):
        a = ws.patch_agent(self.con, "scout", name="Scout X",
                           purpose="new purpose", schedule="daily",
                           enabled=False)
        self.assertEqual(a["name"], "Scout X")
        self.assertEqual(a["purpose"], "new purpose")
        self.assertFalse(a["enabled"])
        self.assertEqual(a["system_prompt"],
                         ws.get_agent(self.con, "scout")["system_prompt"])
        with self.assertRaises(ValueError):
            ws.patch_agent(self.con, "nope", name="x")


class WsChat(unittest.TestCase):
    def setUp(self):
        self.con = fresh()
        ws.seed(self.con)
        self.cfg = {"base_url": "http://127.0.0.1:8888/v1",
                    "model": "test-model"}

    def test_chat_stores_messages_and_emits_agui(self):
        fn = fake_chat("Measured 82% last night.")
        out = ws.chat(self.con, "health-auditor", "How was sleep?",
                      llm_cfg=self.cfg, chat_fn=fn)
        self.assertEqual(out["reply"], "Measured 82% last night.")
        self.assertEqual([e["type"] for e in out["events"]],
                         ["RUN_STARTED", "TEXT_MESSAGE_CONTENT",
                          "RUN_FINISHED"])
        self.assertEqual(out["events"][0]["runId"], out["run_id"])
        self.assertIn("Health Auditor", fn.calls[0]["system"])
        self.assertEqual(fn.calls[0]["messages"][-1],
                         {"role": "user", "content": "How was sleep?"})
        msgs = ws.list_messages(self.con, "health-auditor")
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        runs = ws.list_runs(self.con, "health-auditor")
        self.assertEqual(runs[0]["status"], "ok")
        self.assertEqual(runs[0]["job_id"], "chat")
        agents = {a["slug"]: a for a in ws.list_agents(self.con)}
        self.assertEqual(agents["health-auditor"]["status"], "idle")
        self.assertIsNotNone(agents["health-auditor"]["last_run"])

    def test_chat_caps_history_at_12(self):
        for i in range(8):
            ws.add_message(self.con, "scout", "user", f"q{i}")
            ws.add_message(self.con, "scout", "assistant", f"a{i}")
        fn = fake_chat()
        ws.chat(self.con, "scout", "latest", llm_cfg=self.cfg, chat_fn=fn)
        # 12 history + the new question.
        self.assertEqual(len(fn.calls[0]["messages"]), 13)

    def test_chat_brain_failure_is_recorded_not_raised(self):
        out = ws.chat(self.con, "scout", "hello", llm_cfg=self.cfg,
                      chat_fn=lambda s, m: None)
        self.assertIsNone(out["reply"])
        self.assertEqual(out["events"][-1]["type"], "RUN_ERROR")
        runs = ws.list_runs(self.con, "scout")
        self.assertEqual(runs[0]["status"], "error")
        msgs = ws.list_messages(self.con, "scout")
        self.assertEqual(msgs[-1]["role"], "assistant")
        self.assertIn("unreachable", msgs[-1]["body"].lower())

    def test_empty_body_rejected(self):
        with self.assertRaises(ValueError):
            ws.chat(self.con, "scout", "   ", llm_cfg=self.cfg,
                    chat_fn=fake_chat())

    def test_unknown_agent_rejected(self):
        with self.assertRaises(ValueError):
            ws.chat(self.con, "nope", "hi", llm_cfg=self.cfg,
                    chat_fn=fake_chat())


class WsRuns(unittest.TestCase):
    def setUp(self):
        self.con = fresh()
        ws.seed(self.con)

    def test_run_lifecycle_and_status(self):
        run = ws.start_run(self.con, "ship-watch", job_id="4bda9d296751")
        self.assertEqual(run["status"], "running")
        agents = {a["slug"]: a for a in ws.list_agents(self.con)}
        self.assertEqual(agents["ship-watch"]["status"], "running")
        done = ws.finish_run(self.con, run["id"], "error", "build 152 failed")
        self.assertEqual(done["status"], "error")
        self.assertGreater(done["ended_at"], 0)
        agents = {a["slug"]: a for a in ws.list_agents(self.con)}
        self.assertEqual(agents["ship-watch"]["status"], "error")
        self.assertEqual(agents["ship-watch"]["last_run"]["summary"],
                         "build 152 failed")
        runs = ws.list_runs(self.con, "ship-watch")
        self.assertEqual(len(runs), 1)

    def test_record_run_and_newest_first(self):
        ws.record_run(self.con, "scout", job_id="j1", status="ok",
                      summary="first", ended_at=100)
        ws.record_run(self.con, "scout", job_id="j2", status="ok",
                      summary="second", ended_at=200)
        runs = ws.list_runs(self.con, "scout")
        self.assertEqual([r["summary"] for r in runs], ["second", "first"])

    def test_finish_unknown_run_raises(self):
        with self.assertRaises(ValueError):
            ws.finish_run(self.con, "nope", "ok", "")


class WsPeers(unittest.TestCase):
    def setUp(self):
        self.con = fresh()
        ws.seed(self.con)

    def test_send_creates_task_id_and_mirror(self):
        out = ws.send_peer(self.con, "health-auditor", "ring-lab",
                           "share the battery curve")
        self.assertTrue(out["task_id"].startswith("a2a-"))
        self.assertEqual(out["from"], "health-auditor")
        self.assertEqual(out["to"], "ring-lab")
        peers = ws.list_peers(self.con)
        self.assertEqual(len(peers), 1)
        self.assertEqual(peers[0]["task_id"], out["task_id"])
        msgs = ws.list_messages(self.con, "ring-lab")
        self.assertEqual(msgs[-1]["role"], "peer")
        self.assertEqual(msgs[-1]["peer_from"], "health-auditor")
        self.assertEqual(msgs[-1]["task_id"], out["task_id"])

    def test_unknown_peer_rejected(self):
        with self.assertRaises(ValueError):
            ws.send_peer(self.con, "scout", "ghost", "hi")
        with self.assertRaises(ValueError):
            ws.send_peer(self.con, "ghost", "scout", "hi")
        with self.assertRaises(ValueError):
            ws.send_peer(self.con, "scout", "scout", "")

    def test_peers_newest_first_and_read(self):
        a = ws.send_peer(self.con, "scout", "ring-lab", "one")
        ws.send_peer(self.con, "scout", "ring-lab", "two")
        peers = ws.list_peers(self.con, limit=10)
        self.assertEqual([p["body"] for p in peers], ["two", "one"])
        self.assertIsNone(peers[0]["read_at"])
        ws.mark_peer_read(self.con, a["id"])
        unread = ws.list_peers(self.con, unread_only=True)
        self.assertEqual([p["body"] for p in unread], ["two"])


class WsCards(unittest.TestCase):
    def setUp(self):
        self.con = fresh()
        ws.seed(self.con)

    def test_agent_card(self):
        card = ws.agent_card(self.con, "ring-lab",
                             base_url="https://bot.getzoro.com")
        self.assertEqual(card["name"], "Ring Lab")
        self.assertEqual(card["url"],
                         "https://bot.getzoro.com/api/ws/agents/ring-lab")
        self.assertEqual(card["preferredTransport"], "JSONRPC")
        self.assertEqual(card["defaultInputModes"], ["text/plain"])
        self.assertTrue(card["skills"])
        skill = card["skills"][0]
        for k in ("id", "name", "description", "tags"):
            self.assertIn(k, skill)

    def test_workspace_card_lists_all_agents(self):
        card = ws.workspace_card(self.con, base_url="https://bot.getzoro.com")
        self.assertEqual(card["url"], "https://bot.getzoro.com/a2a")
        self.assertEqual(len(card["skills"]), 8)
        ids = {s["id"] for s in card["skills"]}
        self.assertIn("health-auditor", ids)

    def test_card_unknown_raises(self):
        with self.assertRaises(ValueError):
            ws.agent_card(self.con, "nope", base_url="https://x")


if __name__ == "__main__":
    unittest.main()
