#!/usr/bin/env python3
"""HTTP end-to-end proof for the agents workspace (bot.getzoro.com).

Exercises the acceptance calls from docs/agents-workspace.md section 8 against
a live agent-manager instance and writes an evidence JSON under
docs/evidence/agents-workspace/. The token is read from the repo .env and is
never written into the evidence or printed.

Usage:
  python3 scripts/ws_e2e.py                       # https://bot.getzoro.com
  python3 scripts/ws_e2e.py --base http://127.0.0.1:8075
  python3 scripts/ws_e2e.py --no-writes           # read-only checks
  python3 scripts/ws_e2e.py --run --job-id 99eb38de9bb7
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_EVIDENCE = os.path.join(ROOT, "docs", "evidence", "agents-workspace")
DEFAULT_BASE = "https://bot.getzoro.com"
TOKEN_ENV = "AGENT_MANAGER_TOKEN"
USER_AGENT = "agent-manager-e2e/1.0 (+https://bot.getzoro.com)"


def load_token(env_path=None):
    """Read AGENT_MANAGER_TOKEN from .env without logging the value."""
    path = env_path or os.path.join(ROOT, ".env")
    if not os.path.isfile(path):
        return ""
    with open(path) as f:
        for line in f:
            m = re.match(r"^\s*" + TOKEN_ENV + r"\s*=\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    return ""


def _request(base, token, method, path, payload=None, auth=True, timeout=180):
    """Return (status, body, elapsed_ms, error). body is dict/list/str/None."""
    url = base.rstrip("/") + path
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if auth and token:
        headers["X-Token"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw = resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read()
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        return None, None, int((time.monotonic() - started) * 1000), str(reason)
    ms = int((time.monotonic() - started) * 1000)
    text = raw.decode("utf-8", "replace")
    try:
        body = json.loads(text)
    except ValueError:
        body = text
    return status, body, ms, None


def _excerpt(value, limit=200):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


def _run_check(checks, cid, name, method, path, expected, client, auth=True,
               payload=None, validate=None, write=False, skip_reason=None,
               timeout=180):
    entry = {
        "id": cid, "name": name, "method": method, "path": path,
        "auth": bool(auth), "expected": list(expected), "write": bool(write),
        "status": None, "ok": None, "skipped": False, "detail": "",
    }
    if skip_reason:
        entry["skipped"] = True
        entry["detail"] = skip_reason
        checks.append(entry)
        return entry
    status, body, ms, err = _request(
        client["base"], client["token"], method, path, payload=payload,
        auth=auth, timeout=timeout)
    entry["status"] = status
    entry["elapsed_ms"] = ms
    if err:
        entry["ok"] = False
        entry["detail"] = "transport error: " + err
    elif status not in expected:
        entry["ok"] = False
        entry["detail"] = _excerpt(body)
    elif validate:
        ok, detail = validate(body)
        entry["ok"] = bool(ok)
        entry["detail"] = detail
    else:
        entry["ok"] = True
        entry["detail"] = _excerpt(body)
    checks.append(entry)
    return entry


def _v_agents(body):
    if not isinstance(body, dict) or not isinstance(body.get("agents"), list):
        return False, "no agents list"
    agents = body["agents"]
    slugs = [a.get("slug") for a in agents]
    missing = [a.get("slug") for a in agents
               if not all(k in a for k in ("slug", "status", "cron"))]
    ok = len(agents) >= 8 and not missing
    detail = f"count={len(agents)} slugs={slugs}"
    if missing:
        detail += f" missing_keys={missing}"
    return ok, detail


def _v_detail(body):
    keys = ("messages", "runs", "chips", "status", "last_run")
    if not isinstance(body, dict):
        return False, "not an object"
    missing = [k for k in keys if k not in body]
    chips = body.get("chips") or {}
    ghost = (chips.get("ghost") or "") if isinstance(chips, dict) else ""
    ok = not missing and bool(ghost)
    detail = f"slug={body.get('slug')} missing={missing} ghost={_excerpt(ghost, 80)}"
    return ok, detail


def _v_messages(body):
    return (isinstance(body, dict) and isinstance(body.get("messages"), list),
            f"messages={len(body.get('messages') or []) if isinstance(body, dict) else 0}")


def _v_runs(body):
    return (isinstance(body, dict) and isinstance(body.get("runs"), list),
            f"runs={len(body.get('runs') or []) if isinstance(body, dict) else 0}")


def _v_card(body):
    if not isinstance(body, dict):
        return False, "not an object"
    url = str(body.get("url", ""))
    ok = body.get("protocolVersion") == "0.3.0" and "/api/ws/agents/" in url
    return ok, f"name={body.get('name')} url={url}"


def _v_well_known(body):
    if not isinstance(body, dict):
        return False, "not an object"
    skills = body.get("skills") or []
    return (len(skills) >= 8, f"name={body.get('name')} skills={len(skills)}")


def _v_bot_page(body):
    text = body if isinstance(body, str) else ""
    markers = ('id="composer"', 'id="token-gate"', 'id="rail"')
    found = [m for m in markers if m in text]
    return (len(found) == len(markers), f"markers={found}")


def _v_chat(body):
    if not isinstance(body, dict):
        return False, "not an object"
    reply = body.get("reply") or ""
    types = [e.get("type") for e in body.get("events") or [] if isinstance(e, dict)]
    ok = bool(reply.strip()) and types == ["RUN_STARTED", "TEXT_MESSAGE_CONTENT",
                                           "RUN_FINISHED"]
    return ok, f"reply={_excerpt(reply, 160)} events={types}"


def _v_chat_persisted(marker):
    def _fn(body):
        msgs = body.get("messages") if isinstance(body, dict) else None
        bodies = [m.get("body") or "" for m in msgs or [] if isinstance(m, dict)]
        hit = any(marker in b for b in bodies)
        return hit, f"marker_present={hit} scanned={len(bodies)}"
    return _fn


def _v_peer(body):
    if not isinstance(body, dict):
        return False, "not an object"
    task = body.get("task_id") or ""
    return (task.startswith("a2a-"), f"task_id={task}")


def _v_a2a(body):
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return False, "not a JSON-RPC 2.0 response"
    result = body.get("result") or {}
    status = (result.get("status") or {}).get("state")
    parts = ((result.get("artifacts") or [{}])[0].get("parts") or [{}])
    text = parts[0].get("text") if parts else ""
    ok = result.get("kind") == "task" and status == "completed" and bool(text)
    return ok, f"task={result.get('id')} state={status} text={_excerpt(text or '', 120)}"


def _v_a2a_error(body):
    err = body.get("error") if isinstance(body, dict) else None
    code = err.get("code") if isinstance(err, dict) else None
    return (code == -32601, f"error_code={code}")


def _v_run(body):
    if not isinstance(body, dict):
        return False, "not an object"
    run = body.get("run") or {}
    ok = run.get("status") == "ok"
    return ok, f"job_id={body.get('job_id')} run_status={run.get('status')} run_id={run.get('id')}"


def run_e2e(base, token, agent="health-auditor", include_writes=True,
            run_job=False, job_id=None, timeout=180):
    """Run every acceptance check. Returns the evidence dict."""
    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    marker = f"e2e probe {stamp}"
    peer_marker = f"e2e peer {stamp}"
    client = {"base": base.rstrip("/"), "token": token}
    checks = []
    skip = None if include_writes else "skipped: --no-writes"

    _run_check(checks, "unauth_list_401", "workspace list requires a token",
               "GET", "/api/ws/agents", (401,), client, auth=False)
    _run_check(checks, "unauth_well_known", "A2A workspace card is public",
               "GET", "/.well-known/agent-card.json", (200,), client,
               auth=False, validate=_v_well_known)
    _run_check(checks, "unauth_bot_page", "/bot/ renders publicly",
               "GET", "/bot/", (200,), client, auth=False,
               validate=_v_bot_page)
    _run_check(checks, "list_agents", "token list returns seeded agents",
               "GET", "/api/ws/agents", (200,), client, validate=_v_agents)
    _run_check(checks, "agent_detail", "agent detail has thread, runs, chips",
               "GET", f"/api/ws/agents/{agent}", (200,), client,
               validate=_v_detail)
    _run_check(checks, "agent_messages", "agent message history",
               "GET", f"/api/ws/agents/{agent}/messages?limit=5", (200,),
               client, validate=_v_messages)
    _run_check(checks, "agent_runs", "agent run history",
               "GET", f"/api/ws/agents/{agent}/runs?limit=5", (200,),
               client, validate=_v_runs)
    _run_check(checks, "agent_card", "A2A agent card",
               "GET", f"/api/ws/agents/{agent}/card", (200,), client,
               validate=_v_card)
    _run_check(checks, "agent_card_unauth", "A2A agent card is public",
               "GET", f"/api/ws/agents/{agent}/card", (200,), client,
               auth=False, validate=_v_card)
    _run_check(checks, "unknown_agent_404", "unknown agent is a designed 404",
               "GET", "/api/ws/agents/__e2e_missing__", (404,), client)
    _run_check(checks, "chat_reply", "chat gets a real brain reply (AG-UI)",
               "POST", f"/api/ws/agents/{agent}/messages", (200,), client,
               payload={"body": marker + ": what do you own?"},
               validate=_v_chat, write=True, skip_reason=skip,
               timeout=max(timeout, 240))
    _run_check(checks, "chat_persisted", "chat turn is stored in the thread",
               "GET", f"/api/ws/agents/{agent}/messages?limit=10", (200,),
               client, validate=_v_chat_persisted(marker), write=True,
               skip_reason=skip)
    _run_check(checks, "peers_list", "peer bus list",
               "GET", "/api/ws/peers?limit=5", (200,), client)
    _run_check(checks, "peer_send", "peer send returns an A2A task id",
               "POST", f"/api/ws/agents/{agent}/to", (200,), client,
               payload={"to": "ring-lab", "body": peer_marker},
               validate=_v_peer, write=True, skip_reason=skip)
    _run_check(checks, "a2a_message_send", "A2A message/send completes a task",
               "POST", "/a2a", (200,), client,
               payload={
                   "jsonrpc": "2.0", "id": "e2e-" + stamp,
                   "method": "message/send",
                   "params": {"metadata": {"agent": agent},
                              "message": {"messageId": "m-" + stamp,
                                          "role": "user",
                                          "parts": [{"kind": "text",
                                                     "text": marker + ": status?"}]}},
               }, validate=_v_a2a, write=True, skip_reason=skip,
               timeout=max(timeout, 240))
    _run_check(checks, "a2a_bad_method", "unknown A2A method is -32601",
               "POST", "/a2a", (200,), client,
               payload={"jsonrpc": "2.0", "id": "e2e-bad", "method": "tasks/get",
                        "params": {}}, validate=_v_a2a_error)
    _run_check(checks, "run_now", "run now triggers the source cron job",
               "POST", f"/api/ws/agents/{agent}/run", (200,), client,
               payload=({"job_id": job_id} if job_id else {}),
               validate=_v_run, write=True,
               skip_reason=None if run_job else "skipped: --run not set",
               timeout=660)

    finished = datetime.now(timezone.utc)
    passed = sum(1 for c in checks if c["ok"] is True)
    failed = sum(1 for c in checks if c["ok"] is False)
    skipped = sum(1 for c in checks if c["skipped"])
    return {
        "kind": "agents-workspace-http-e2e",
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 2),
        "base_url": client["base"],
        "agent": agent,
        "writes": bool(include_writes),
        "run_now": bool(run_job),
        "job_id": job_id or "",
        "python": sys.version.split()[0],
        "token_present": bool(token),
        "ok": failed == 0 and passed > 0,
        "summary": {"total": len(checks), "passed": passed,
                    "failed": failed, "skipped": skipped},
        "checks": checks,
    }


def write_evidence(evidence, out_dir=DEFAULT_EVIDENCE):
    os.makedirs(out_dir, exist_ok=True)
    stamp = evidence["started_at"].replace("-", "").replace(":", "")[:15]
    path = os.path.join(out_dir, f"http-e2e-{stamp}.json")
    with open(path, "w") as f:
        json.dump(evidence, f, indent=2)
        f.write("\n")
    latest = os.path.join(out_dir, "http-e2e-latest.json")
    with open(latest, "w") as f:
        json.dump(evidence, f, indent=2)
        f.write("\n")
    return path, latest


def exit_code(evidence):
    return 0 if evidence.get("ok") else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--token", default="", help="override .env token")
    ap.add_argument("--agent", default="health-auditor")
    ap.add_argument("--no-writes", action="store_true",
                    help="read-only checks (skip chat, peer send, A2A, run)")
    ap.add_argument("--run", action="store_true",
                    help="also trigger the agent's source cron job")
    ap.add_argument("--job-id", default="",
                    help="source job id for --run (default: agent's first)")
    ap.add_argument("--out-dir", default=DEFAULT_EVIDENCE)
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args(argv)

    token = args.token or load_token()
    if not token:
        print("no token: set AGENT_MANAGER_TOKEN in .env or pass --token")
        return 2
    evidence = run_e2e(args.base, token, agent=args.agent,
                       include_writes=not args.no_writes,
                       run_job=args.run, job_id=args.job_id,
                       timeout=args.timeout)
    path, latest = write_evidence(evidence, args.out_dir)
    s = evidence["summary"]
    print(f"e2e {evidence['base_url']}: {s['passed']} passed, "
          f"{s['failed']} failed, {s['skipped']} skipped "
          f"({evidence['duration_s']}s)")
    for c in evidence["checks"]:
        if c["ok"] is False:
            print(f"FAIL {c['id']}: {c['detail']}")
    print("evidence: " + path)
    print("latest:   " + latest)
    return exit_code(evidence)


if __name__ == "__main__":
    sys.exit(main())
