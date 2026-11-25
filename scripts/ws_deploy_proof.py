#!/usr/bin/env python3
"""Deploy proof for the agents workspace (bot.getzoro.com).

Collects the live facts that docs/agents-workspace.md section 8 cites: service
state, HEAD vs origin/main, the public and token endpoint codes, the latest HTTP
and browser e2e evidence, and optionally the repo test suite. Writes
deploy-proof-<ts>.json plus deploy-proof-latest.json under
docs/evidence/agents-workspace/. The token is read from the repo .env and is
never recorded or printed.

Usage:
  python3 scripts/ws_deploy_proof.py
  python3 scripts/ws_deploy_proof.py --base http://127.0.0.1:8075 --tests
  python3 scripts/ws_deploy_proof.py --no-service --no-git
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import ws_e2e  # noqa: E402  (shared token loader + HTTP client)

DEFAULT_BASE = "https://bot.getzoro.com"
EVIDENCE_DIR = os.path.join(ROOT, "docs", "evidence", "agents-workspace")
SERVICE = "agent-manager.service"
BOT_MARKERS = ('id="rail"', 'id="composer"', 'id="token-gate"')
EVIDENCE_FILES = {"http": "http-e2e-latest.json",
                  "browser": "browser-e2e-latest.json"}


def expected_agents(root=ROOT):
    """Seeded roster size, so the proof checks a real count, not 'non-empty'."""
    path = os.path.join(root, "agents_seed.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return 8
    agents = data.get("agents") if isinstance(data, dict) else data
    return len(agents or []) or 8


def git_info(root=ROOT):
    def _git(*args):
        try:
            out = subprocess.run(["git", *args], cwd=root, capture_output=True,
                                 text=True, timeout=30)
            return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    head = _git("rev-parse", "HEAD")
    origin = _git("rev-parse", "origin/main")
    return {
        "head": head,
        "branch": _git("branch", "--show-current"),
        "origin_main": origin,
        "head_equals_origin": bool(head) and head == origin,
        "dirty": bool(_git("status", "--porcelain")),
    }


def service_state(name=SERVICE):
    try:
        out = subprocess.run(["systemctl", "--user", "is-active", name],
                             capture_output=True, text=True, timeout=15)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def http_client(base, token):
    def fetch(path, auth=True, timeout=30):
        return ws_e2e._request(base, token, "GET", path, auth=auth,
                               timeout=timeout)
    return fetch


def load_latest_evidence(out_dir=EVIDENCE_DIR):
    """Read the newest e2e evidence; missing files are reported, not fatal."""
    found = {}
    for kind, name in EVIDENCE_FILES.items():
        path = os.path.join(out_dir, name)
        entry = {"kind": kind, "file": name, "present": False}
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            found[kind] = entry
            continue
        summary = data.get("summary") or {}
        total = summary.get("total") or 0
        passed = summary.get("passed") or 0
        failed = summary.get("failed")
        explicit = data.get("ok")
        if isinstance(explicit, bool):
            ok = explicit
        else:
            # browser e2e records summary only; green means every check passed
            ok = bool(total) and passed == total and failed == 0
        entry.update({
            "present": True,
            "ok": ok,
            "timestamp": data.get("timestamp") or data.get("started_at"),
            "total": total,
            "passed": passed,
            "failed": failed,
            "duration_s": data.get("duration_s")
            or round((data.get("elapsed_ms") or 0) / 1000.0, 1),
        })
        found[kind] = entry
    return found


def parse_unittest_output(text):
    """Extract (ran, ok) from unittest stderr."""
    m = re.search(r"^Ran (\d+) tests?", text, re.M)
    ran = int(m.group(1)) if m else 0
    ok = bool(re.search(r"^OK\b", text, re.M)) and ran > 0
    return {"ran": ran, "ok": ok}


def test_modules(root=ROOT):
    """tests/ is not a package here, so discovery needs explicit modules."""
    tdir = os.path.join(root, "tests")
    names = sorted(f[:-3] for f in os.listdir(tdir)
                   if f.startswith("test_") and f.endswith(".py"))
    return ["tests." + n for n in names]


def run_tests(root=ROOT, timeout=900):
    mods = test_modules(root)
    if not mods:
        return {"ran": 0, "ok": False, "rc": None, "error": "no test modules"}
    try:
        out = subprocess.run([sys.executable, "-m", "unittest", *mods],
                             cwd=root, capture_output=True, text=True,
                             timeout=timeout)
        result = parse_unittest_output(out.stderr)
        result["rc"] = out.returncode
        return result
    except (OSError, subprocess.SubprocessError) as e:
        return {"ran": 0, "ok": False, "rc": None, "error": str(e)}


def _add(checks, cid, name, ok, detail, expected=None):
    checks.append({"id": cid, "name": name, "ok": bool(ok),
                   "expected": expected, "detail": detail})


def _status_of(result):
    return result[0] if result else None


def build_report(client, service, git, evidence, tests=None,
                 base=DEFAULT_BASE, agents=None, now=None):
    """Build the proof report from injected facts (testable without network)."""
    agents = agents if agents is not None else 8
    checks = []

    _add(checks, "service_active", "agent-manager.service is active",
         service == "active", "state=%s" % service, "active")

    head_ok = bool(git.get("head_equals_origin")) and not git.get("dirty")
    _add(checks, "git_head", "HEAD equals origin/main with a clean tree",
         head_ok,
         "head=%s origin=%s branch=%s dirty=%s" % (
             git.get("head", "")[:12], git.get("origin_main", "")[:12],
             git.get("branch", ""), bool(git.get("dirty"))),
         "HEAD == origin/main, clean")

    unauth = client("/api/ws/agents", auth=False)
    _add(checks, "unauth_list_401", "workspace list requires a token",
         _status_of(unauth) == 401, "status=%s" % _status_of(unauth), 401)

    page = client("/bot/", auth=False)
    body = page[1] if page and len(page) > 1 else ""
    text = body if isinstance(body, str) else json.dumps(body)
    missing = [m for m in BOT_MARKERS if m not in text]
    _add(checks, "bot_page_200", "/bot/ serves the workspace shell",
         _status_of(page) == 200 and not missing,
         "status=%s missing=%s" % (_status_of(page), missing), 200)

    favicon = client("/favicon.ico", auth=False)
    _add(checks, "favicon_204", "favicon answers before the auth gate",
         _status_of(favicon) == 204, "status=%s" % _status_of(favicon), 204)

    wk = client("/.well-known/agent-card.json", auth=False)
    wk_body = wk[1] if wk and len(wk) > 1 else None
    skills = len(wk_body.get("skills", [])) if isinstance(wk_body, dict) else 0
    _add(checks, "well_known_200", "A2A workspace card is public",
         _status_of(wk) == 200 and skills > 0,
         "status=%s skills=%s" % (_status_of(wk), skills), 200)

    lst = client("/api/ws/agents", auth=True)
    lst_body = lst[1] if lst and len(lst) > 1 else None
    listed = lst_body.get("agents") if isinstance(lst_body, dict) else lst_body
    count = len(listed) if isinstance(listed, list) else 0
    _add(checks, "token_list", "token list returns the seeded roster",
         _status_of(lst) == 200 and count == agents,
         "status=%s count=%s" % (_status_of(lst), count), "200, %s agents" % agents)

    detail = client("/api/ws/agents/health-auditor", auth=True)
    detail_body = detail[1] if detail and len(detail) > 1 else None
    has_chips = isinstance(detail_body, dict) and isinstance(
        detail_body.get("chips"), dict) and "ghost" in detail_body["chips"]
    _add(checks, "agent_detail", "agent detail returns thread, runs, chips",
         _status_of(detail) == 200 and has_chips,
         "status=%s chips=%s" % (_status_of(detail), has_chips), 200)

    for kind in ("http", "browser"):
        e = evidence.get(kind) or {}
        ok = bool(e.get("present") and e.get("ok") and not e.get("failed"))
        _add(checks, "evidence_%s" % kind, "latest %s e2e evidence is green" % kind,
             ok, "present=%s ok=%s passed=%s failed=%s" % (
                 e.get("present"), e.get("ok"), e.get("passed"), e.get("failed")),
             "present, ok, 0 failed")

    if tests is not None:
        _add(checks, "repo_tests", "repo test suite is green",
             bool(tests.get("ok")) and tests.get("ran", 0) > 0,
             "ran=%s rc=%s" % (tests.get("ran"), tests.get("rc")), "OK")

    failed = [c["id"] for c in checks if not c["ok"]]
    ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    return {
        "kind": "agents-workspace-deploy-proof",
        "timestamp": ts,
        "base_url": base,
        "git": git,
        "service": service,
        "evidence": evidence,
        "tests": tests,
        "ok": not failed,
        "summary": {"total": len(checks), "passed": len(checks) - len(failed),
                    "failed": len(failed), "failed_ids": failed},
        "checks": checks,
    }


def write_evidence(report, out_dir=EVIDENCE_DIR):
    os.makedirs(out_dir, exist_ok=True)
    stamped = os.path.join(out_dir, "deploy-proof-%s.json" % report["timestamp"])
    latest = os.path.join(out_dir, "deploy-proof-latest.json")
    payload = json.dumps(report, indent=1, sort_keys=True)
    for path in (stamped, latest):
        with open(path, "w") as f:
            f.write(payload + "\n")
    return stamped, latest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--out-dir", default=EVIDENCE_DIR)
    ap.add_argument("--tests", action="store_true", help="run the repo suite")
    ap.add_argument("--no-service", action="store_true")
    ap.add_argument("--no-git", action="store_true")
    args = ap.parse_args(argv)

    token = ws_e2e.load_token()
    if not token:
        print("missing AGENT_MANAGER_TOKEN in .env", file=sys.stderr)
        return 2

    git = {"head": "", "branch": "", "origin_main": "",
           "head_equals_origin": False, "dirty": None}
    if not args.no_git:
        git = git_info()
    service = "skipped" if args.no_service else service_state()
    evidence = load_latest_evidence(args.out_dir)
    tests = run_tests() if args.tests else None

    report = build_report(http_client(args.base, token), service, git,
                          evidence, tests=tests, base=args.base,
                          agents=expected_agents())
    stamped, latest = write_evidence(report, args.out_dir)

    for c in report["checks"]:
        print("%s %s %s" % ("ok  " if c["ok"] else "FAIL", c["id"], c["detail"]))
    print("summary: %s/%s passed, ok=%s" % (report["summary"]["passed"],
                                            report["summary"]["total"],
                                            report["ok"]))
    print("evidence: %s" % stamped)
    print("latest:   %s" % latest)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
