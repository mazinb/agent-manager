"""Browser e2e script: pure helpers, evidence and verdict logic.

The browser itself is exercised by scripts/ws_browser_e2e.py against the live
site; these tests pin the parts that decide pass/fail so a bad filter cannot
silently report green.
"""
import importlib.util
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "ws_browser_e2e", os.path.join(ROOT, "scripts", "ws_browser_e2e.py"))
ws_browser_e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws_browser_e2e)

TOKEN = "test-token-value"


class TokenAndChrome(unittest.TestCase):
    def test_load_token_strips_quotes(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("OTHER=1\nAGENT_MANAGER_TOKEN = \"%s\"\n" % TOKEN)
            path = f.name
        try:
            self.assertEqual(ws_browser_e2e.load_token(path), TOKEN)
        finally:
            os.unlink(path)

    def test_load_token_missing_file(self):
        self.assertEqual(ws_browser_e2e.load_token("/nonexistent/.env"), "")

    def test_find_chrome_prefers_explicit_then_env(self):
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "chrome")
            with open(good, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(good, 0o755)
            self.assertEqual(ws_browser_e2e.find_chrome(good), good)
            old = os.environ.get("HERMES_CHROME")
            os.environ["HERMES_CHROME"] = good
            try:
                self.assertEqual(ws_browser_e2e.find_chrome("/nope/chrome"), good)
            finally:
                if old is None:
                    os.environ.pop("HERMES_CHROME", None)
                else:
                    os.environ["HERMES_CHROME"] = old

    def test_parse_ws_url(self):
        line = ("[123:456:ERROR:devtools] DevTools listening on "
                "ws://127.0.0.1:41234/devtools/browser/abc-def\n")
        self.assertEqual(ws_browser_e2e.parse_ws_url(line),
                         "ws://127.0.0.1:41234/devtools/browser/abc-def")
        self.assertEqual(ws_browser_e2e.parse_ws_url("nothing here"), "")


class ConsoleFilter(unittest.TestCase):
    def test_exception_is_error(self):
        ev = {"method": "Runtime.exceptionThrown", "params": {
            "exceptionDetails": {"text": "Uncaught",
                                 "exception": {"description": "TypeError: x"}}}}
        kind, detail = ws_browser_e2e.console_error(ev)
        self.assertEqual(kind, "exception")
        self.assertIn("TypeError", detail)

    def test_log_error_is_error(self):
        ev = {"method": "Log.entryAdded", "params": {"entry": {
            "level": "error", "source": "network", "text": "Failed to load"}}}
        self.assertEqual(ws_browser_e2e.console_error(ev)[0], "log")

    def test_log_info_ignored(self):
        ev = {"method": "Log.entryAdded", "params": {"entry": {
            "level": "info", "source": "other", "text": "hi"}}}
        self.assertIsNone(ws_browser_e2e.console_error(ev))

    def test_console_error_type(self):
        ev = {"method": "Runtime.consoleAPICalled", "params": {
            "type": "error", "args": [{"value": "boom"}]}}
        self.assertEqual(ws_browser_e2e.console_error(ev)[0], "console")

    def test_console_log_ignored(self):
        ev = {"method": "Runtime.consoleAPICalled", "params": {
            "type": "log", "args": [{"value": "hello"}]}}
        self.assertIsNone(ws_browser_e2e.console_error(ev))

    def test_unrelated_event_ignored(self):
        self.assertIsNone(ws_browser_e2e.console_error({"method": "Network.loadingFinished"}))


class OverflowVerdict(unittest.TestCase):
    def metrics(self, doc=390, body=390, containers=None):
        return {"innerWidth": 390, "doc": doc, "body": body,
                "containers": containers or [], "offenders": []}

    def test_clean_layout_passes(self):
        ok, detail = ws_browser_e2e.overflow_verdict(self.metrics())
        self.assertTrue(ok, detail)
        self.assertIn("innerWidth=390", detail)

    def test_document_scroll_fails(self):
        ok, _ = ws_browser_e2e.overflow_verdict(self.metrics(doc=420))
        self.assertFalse(ok)

    def test_body_scroll_fails(self):
        ok, _ = ws_browser_e2e.overflow_verdict(self.metrics(body=402))
        self.assertFalse(ok)

    def test_container_scroll_fails(self):
        ok, detail = ws_browser_e2e.overflow_verdict(self.metrics(
            containers=[{"id": "thread", "sw": 500, "cw": 390}]))
        self.assertFalse(ok)
        self.assertIn("thread", detail)

    def test_one_pixel_tolerance(self):
        ok, _ = ws_browser_e2e.overflow_verdict(self.metrics(doc=391))
        self.assertTrue(ok)

    def test_missing_metrics_fails(self):
        self.assertFalse(ws_browser_e2e.overflow_verdict(None)[0])


class EvidenceAndExit(unittest.TestCase):
    def test_check_records_failure(self):
        checks = []
        ws_browser_e2e._check(checks, "x", "X", False, "bad")
        self.assertEqual(checks[0]["ok"], False)

    def test_skipped_does_not_fail(self):
        checks = []
        ws_browser_e2e._check(checks, "chat", "chat", False, "skipped", skipped=True)
        evidence = {"checks": checks}
        self.assertIsNone(checks[0]["ok"])
        self.assertEqual(ws_browser_e2e.exit_code(evidence), 0)

    def test_failure_exits_nonzero(self):
        checks = []
        ws_browser_e2e._check(checks, "a", "A", True)
        ws_browser_e2e._check(checks, "b", "B", False, "boom")
        evidence = {"checks": checks}
        self.assertEqual(ws_browser_e2e.exit_code(evidence), 1)
        self.assertEqual(ws_browser_e2e.summarize(checks)["failed_ids"], ["b"])

    def test_write_evidence_roundtrip_and_token_absent(self):
        evidence = {"timestamp": "20260101T000000", "checks": [],
                    "console_errors": [], "summary": {"total": 0}}
        with tempfile.TemporaryDirectory() as d:
            path, latest = ws_browser_e2e.write_evidence(evidence, d, "20260101T000000")
            self.assertTrue(os.path.isfile(path))
            self.assertTrue(os.path.isfile(latest))
            with open(latest, encoding="utf-8") as f:
                raw = f.read()
            self.assertEqual(json.loads(raw)["timestamp"], "20260101T000000")
            self.assertNotIn(TOKEN, raw)


if __name__ == "__main__":
    unittest.main()
