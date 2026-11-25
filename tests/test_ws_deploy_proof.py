"""Deploy proof script: report logic, evidence parsing, no token leakage."""
import importlib.util
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "ws_deploy_proof", os.path.join(ROOT, "scripts", "ws_deploy_proof.py"))
ws_deploy_proof = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws_deploy_proof)

TOKEN = "sekrit-deploy-token"
SLUGS = ["health-auditor", "ring-lab", "ship-watch", "coach-builder",
         "brain-ops", "dwm-lab", "voice-lab", "scout"]
BOT_HTML = ('<html><div id="rail"></div><form id="composer"></form>'
            '<div id="token-gate"></div></html>')


def agent(slug):
    return {"slug": slug, "name": slug.title()}


def stub_client(overrides=None):
    """Live-shaped stub. overrides: {path: (status, body)} for unauth GET."""
    overrides = overrides or {}

    def fetch(path, auth=True, timeout=30):
        if path in overrides:
            status, body = overrides[path]
            return status, body, 1, None
        if path == "/api/ws/agents":
            if not auth:
                return 401, {"error": "unauthorized"}, 1, None
            return 200, {"agents": [agent(s) for s in SLUGS]}, 1, None
        if path == "/bot/":
            return 200, BOT_HTML, 1, None
        if path == "/favicon.ico":
            return 204, "", 1, None
        if path == "/.well-known/agent-card.json":
            return 200, {"name": "Agent Manager", "skills": [{"id": "s"}]}, 1, None
        if path == "/api/ws/agents/health-auditor":
            return 200, {"slug": "health-auditor", "chips": {"chips": [], "ghost": "hi"}}, 1, None
        return 404, {"error": "not found"}, 1, None
    return fetch


GOOD_GIT = {"head": "a" * 40, "branch": "main", "origin_main": "a" * 40,
            "head_equals_origin": True, "dirty": False}
GOOD_EVIDENCE = {
    "http": {"present": True, "ok": True, "passed": 17, "failed": 0,
             "total": 17, "timestamp": "2026-11-25T08:33:40+00:00"},
    "browser": {"present": True, "ok": True, "passed": 13, "failed": 0,
                "total": 13, "timestamp": "20261125T091441"},
}


class DeployProof(unittest.TestCase):
    def report(self, client=None, service="active", git=None, evidence=None,
               tests=None):
        return ws_deploy_proof.build_report(
            client or stub_client(), service, git or dict(GOOD_GIT),
            json.loads(json.dumps(GOOD_EVIDENCE)) if evidence is None else evidence,
            tests=tests,
            agents=8)

    def test_green_proof_passes_all_checks(self):
        r = self.report(tests={"ran": 210, "ok": True, "rc": 0})
        self.assertTrue(r["ok"])
        self.assertEqual(r["summary"]["failed"], 0)
        self.assertEqual(r["summary"]["passed"], r["summary"]["total"])
        ids = [c["id"] for c in r["checks"]]
        for cid in ("service_active", "git_head", "unauth_list_401",
                    "bot_page_200", "favicon_204", "well_known_200",
                    "token_list", "agent_detail", "evidence_http",
                    "evidence_browser", "repo_tests"):
            self.assertIn(cid, ids)

    def test_unauth_leak_fails(self):
        r = self.report(stub_client({"/api/ws/agents": (200, {"agents": []})}))
        self.assertFalse(r["ok"])
        self.assertIn("unauth_list_401", r["summary"]["failed_ids"])

    def test_head_mismatch_fails(self):
        git = dict(GOOD_GIT, origin_main="b" * 40, head_equals_origin=False)
        r = self.report(git=git)
        self.assertFalse(r["ok"])
        self.assertIn("git_head", r["summary"]["failed_ids"])

    def test_dirty_tree_fails(self):
        r = self.report(git=dict(GOOD_GIT, dirty=True))
        self.assertIn("git_head", r["summary"]["failed_ids"])

    def test_inactive_service_fails(self):
        r = self.report(service="failed")
        self.assertIn("service_active", r["summary"]["failed_ids"])

    def test_missing_bot_marker_fails(self):
        r = self.report(stub_client({"/bot/": (200, "<html></html>")}))
        self.assertIn("bot_page_200", r["summary"]["failed_ids"])

    def test_wrong_roster_count_fails(self):
        r = self.report(stub_client(
            {"/api/ws/agents": (200, {"agents": [agent("scout")]})}))
        self.assertIn("token_list", r["summary"]["failed_ids"])

    def test_failed_e2e_evidence_fails(self):
        ev = json.loads(json.dumps(GOOD_EVIDENCE))
        ev["browser"]["ok"] = False
        ev["browser"]["failed"] = 2
        r = self.report(evidence=ev)
        self.assertIn("evidence_browser", r["summary"]["failed_ids"])

    def test_missing_evidence_fails(self):
        r = self.report(evidence={})
        self.assertIn("evidence_http", r["summary"]["failed_ids"])

    def test_token_not_recorded(self):
        r = self.report()
        self.assertNotIn(TOKEN, json.dumps(r))

    def test_parse_unittest_output(self):
        ok = ws_deploy_proof.parse_unittest_output(
            "....\n\n----------------------------------------------------------------------\n"
            "Ran 210 tests in 41.2s\n\nOK\n")
        self.assertEqual(ok, {"ran": 210, "ok": True})
        bad = ws_deploy_proof.parse_unittest_output(
            "Ran 210 tests in 41.2s\n\nFAILED (failures=2)\n")
        self.assertEqual(bad, {"ran": 210, "ok": False})

    def test_write_evidence(self):
        r = self.report()
        with tempfile.TemporaryDirectory() as d:
            stamped, latest = ws_deploy_proof.write_evidence(r, d)
            self.assertTrue(stamped.endswith("deploy-proof-%s.json" % r["timestamp"]))
            self.assertTrue(os.path.isfile(latest))
            with open(latest) as f:
                self.assertEqual(json.load(f)["kind"], r["kind"])

    def test_load_latest_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "http-e2e-latest.json"), "w") as f:
                json.dump({"ok": True, "started_at": "t1", "duration_s": 7.3,
                           "summary": {"total": 17, "passed": 17, "failed": 0}}, f)
            ev = ws_deploy_proof.load_latest_evidence(d)
            self.assertTrue(ev["http"]["present"])
            self.assertTrue(ev["http"]["ok"])
            self.assertEqual(ev["http"]["passed"], 17)
            self.assertFalse(ev["browser"]["present"])

    def test_browser_evidence_without_ok_flag(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "browser-e2e-latest.json"), "w") as f:
                json.dump({"timestamp": "t", "summary": {"total": 13, "passed": 13,
                                                        "failed": 0,
                                                        "failed_ids": []}}, f)
            ev = ws_deploy_proof.load_latest_evidence(d)
            self.assertTrue(ev["browser"]["ok"])
            self.assertEqual(ev["browser"]["passed"], 13)

    def test_browser_evidence_failure_without_ok_flag(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "browser-e2e-latest.json"), "w") as f:
                json.dump({"summary": {"total": 13, "passed": 11, "failed": 2,
                                       "failed_ids": ["a", "b"]}}, f)
            ev = ws_deploy_proof.load_latest_evidence(d)
            self.assertFalse(ev["browser"]["ok"])

    def test_expected_agents_from_seed(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "agents_seed.json"), "w") as f:
                json.dump({"agents": [{"slug": "a"}, {"slug": "b"}]}, f)
            self.assertEqual(ws_deploy_proof.expected_agents(d), 2)


if __name__ == "__main__":
    unittest.main()
