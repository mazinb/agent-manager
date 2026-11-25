"""Docs + evidence contract for the shipped agents workspace (queue item 7)."""
import importlib.util
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE = os.path.join(ROOT, "docs", "evidence", "agents-workspace")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ws_e2e = _load("ws_e2e_docs", os.path.join(ROOT, "scripts", "ws_e2e.py"))
ws_deploy_proof = _load("ws_deploy_proof_docs",
                        os.path.join(ROOT, "scripts", "ws_deploy_proof.py"))


def read(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


class DocsContract(unittest.TestCase):
    def test_readme_has_workspace_section(self):
        text = read("README.md")
        self.assertIn("## 4. Agents workspace (`/bot/`)", text)
        self.assertIn("https://bot.getzoro.com/bot/", text)
        self.assertIn("docs/agents-workspace.md", text)
        for marker in ("AG-UI", "A2A", "X-Token", "390 px"):
            self.assertIn(marker, text)

    def test_readme_has_measured_results(self):
        text = read("README.md")
        self.assertIn("Measured results", text)
        for marker in ("17/17", "13/13", "7.35 s", "48.6 s",
                       "scripts/ws_e2e.py", "scripts/ws_browser_e2e.py",
                       "scripts/ws_deploy_proof.py",
                       "docs/evidence/agents-workspace/"):
            self.assertIn(marker, text)

    def test_design_doc_records_results_and_deploy_proof(self):
        text = read("docs", "agents-workspace.md")
        self.assertIn("Status: shipped", text)
        self.assertIn("## 8. Measured results and deploy proof", text)
        for marker in ("17/17", "13/13", "deploy-proof-latest.json",
                       "scripts/ws_deploy_proof.py", "origin/main"):
            self.assertIn(marker, text)

    def test_latest_http_evidence_is_green(self):
        with open(os.path.join(EVIDENCE, "http-e2e-latest.json")) as f:
            data = json.load(f)
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["total"], 17)
        self.assertEqual(data["summary"]["passed"], 17)
        self.assertEqual(data["summary"]["failed"], 0)

    def test_latest_browser_evidence_is_green(self):
        with open(os.path.join(EVIDENCE, "browser-e2e-latest.json")) as f:
            data = json.load(f)
        self.assertEqual(data["summary"]["failed"], 0)
        self.assertEqual(data["summary"]["failed_ids"], [])
        self.assertEqual(data["summary"]["total"], 13)
        self.assertEqual(data["summary"]["passed"], 13)
        self.assertEqual(data["summary"]["failed"], 0)
        self.assertEqual(data["viewport"]["width"], 390)
        self.assertEqual(data["viewport"]["height"], 844)

    def test_deploy_proof_json_valid_when_present(self):
        path = os.path.join(EVIDENCE, "deploy-proof-latest.json")
        if not os.path.isfile(path):
            self.skipTest("deploy proof not generated yet")
        with open(path) as f:
            data = json.load(f)
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["failed"], 0)
        self.assertTrue(data["git"]["head_equals_origin"])
        self.assertFalse(data["git"]["dirty"])
        self.assertEqual(data["service"], "active")

    def test_token_never_in_evidence(self):
        token = ws_e2e.load_token()
        if not token:
            self.skipTest("no token in .env")
        for name in os.listdir(EVIDENCE):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(EVIDENCE, name)) as f:
                self.assertNotIn(token, f.read(), name)

    def test_queue_item_checked(self):
        text = read("QUEUE.md")
        self.assertIn("- [x] 7.", text)

    def test_all_test_modules_are_run_by_the_proof(self):
        mods = ws_deploy_proof.test_modules()
        files = sorted(f for f in os.listdir(os.path.join(ROOT, "tests"))
                       if f.startswith("test_") and f.endswith(".py"))
        self.assertEqual(mods, ["tests." + f[:-3] for f in files])
        self.assertIn("tests.test_ws_docs", mods)


if __name__ == "__main__":
    unittest.main()
