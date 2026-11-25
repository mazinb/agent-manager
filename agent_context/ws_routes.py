"""HTTP route logic for the agents workspace.

Kept out of server.py so tests can exercise it without importing the module
level Brain (which opens the prod brain.db). server.py stays a thin shell.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid

from . import ws

MAX_JOB_OUTPUT = 2000
RUN_TIMEOUT = 600

_AGENT = r"(?P<slug>[A-Za-z0-9._-]{1,48})"
_GET_ROUTES = (
    (re.compile(r"^/api/ws/agents$"), "agents"),
    (re.compile(rf"^/api/ws/agents/{_AGENT}$"), "agent"),
    (re.compile(rf"^/api/ws/agents/{_AGENT}/messages$"), "messages"),
    (re.compile(rf"^/api/ws/agents/{_AGENT}/runs$"), "runs"),
    (re.compile(rf"^/api/ws/agents/{_AGENT}/card$"), "card"),
    (re.compile(r"^/api/ws/peers$"), "peers"),
)


def base_from_host(host):
    host = (host or "").strip() or "bot.getzoro.com"
    local = host.split(":")[0] in ("localhost", "127.0.0.1", "::1")
    return ("http://" if local else "https://") + host


def _q(query, key, default=None):
    value = (query or {}).get(key, default)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else default
    return value


def _int(value, default, low=1, high=200):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(low, min(n, high))


def _error(exc):
    msg = str(exc)
    code = 404 if msg.startswith("unknown") else 400
    return code, {"error": msg}


def match_get(path):
    for rx, kind in _GET_ROUTES:
        m = rx.match(path or "")
        if m:
            return kind, m.groupdict()
    return None, {}


def get(con, path, query=None, base_url=""):
    """Return (code, body) for a workspace GET, or None if not ours."""
    kind, groups = match_get(path)
    if kind is None:
        return None
    slug = groups.get("slug") or ""
    try:
        if kind == "agents":
            agents = ws.list_agents(con)
            return 200, {"agents": agents, "count": len(agents)}
        if kind == "agent":
            return 200, ws.get_agent(con, slug)
        if kind == "messages":
            limit = _int(_q(query, "limit"), 50)
            return 200, {"agent": ws._agent_row(con, slug)["slug"],
                         "messages": ws.list_messages(con, slug, limit)}
        if kind == "runs":
            limit = _int(_q(query, "limit"), 20)
            return 200, {"agent": ws._agent_row(con, slug)["slug"],
                         "runs": ws.list_runs(con, slug, limit)}
        if kind == "card":
            return 200, ws.agent_card(con, slug, base_url)
        if kind == "peers":
            to_agent = _q(query, "to") or _q(query, "to_agent")
            unread = (_q(query, "unread") or "") in ("1", "true", "yes")
            limit = _int(_q(query, "limit"), 50)
            peers = ws.list_peers(con, limit=limit, unread_only=unread,
                                  to_agent=to_agent)
            return 200, {"peers": peers, "count": len(peers)}
    except ValueError as e:
        return _error(e)
    return None


def well_known(con, base_url):
    return ws.workspace_card(con, base_url)


def run_cron_job(job_id, timeout=RUN_TIMEOUT):
    """Trigger a Hermes cron job by id. Blocking; returns a result dict."""
    exe = shutil.which("hermes") or os.path.expanduser("~/.local/bin/hermes")
    try:
        proc = subprocess.run([exe, "cron", "run", job_id],
                              capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": None,
                "output": f"timed out after {timeout}s"}
    except OSError as e:
        return {"ok": False, "returncode": None, "output": str(e)}
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return {"ok": proc.returncode == 0, "returncode": proc.returncode,
            "output": out[-MAX_JOB_OUTPUT:]}


def _job_for(con, slug, payload):
    agent = ws._agent_row(con, slug)
    job_id = str(payload.get("job_id") or "").strip()
    if job_id:
        if job_id not in agent["source_job_ids"]:
            raise ValueError(
                f"job_id {job_id} is not a source job of {agent['slug']}")
        return job_id
    if not agent["source_job_ids"]:
        raise ValueError(f"{agent['slug']} has no scheduled job")
    return agent["source_job_ids"][0]


def post(con, path, payload, base_url="", llm_cfg=None, chat_fn=None,
         runner=None):
    """Return (code, body) for a workspace POST, or None if not ours."""
    payload = payload if isinstance(payload, dict) else {}
    m = re.match(rf"^/api/ws/agents/{_AGENT}/(?P<action>messages|run|to)$", path or "")
    if m:
        slug, action = m.group("slug"), m.group("action")
        try:
            if action == "messages":
                out = ws.chat(con, slug, payload.get("body") or "",
                              llm_cfg=llm_cfg, chat_fn=chat_fn)
                return 200, out
            if action == "run":
                job_id = _job_for(con, slug, payload)
                run = ws.start_run(con, slug, job_id=job_id)
                result = (runner or run_cron_job)(job_id)
                status = "ok" if result.get("ok") else "error"
                run = ws.finish_run(con, run["id"], status,
                                    result.get("output") or "")
                body = {"agent": slug, "job_id": job_id, "run": run,
                        "runner": result}
                return (200 if result.get("ok") else 502), body
            if action == "to":
                return 200, ws.send_peer(con, slug, payload.get("to") or "",
                                         payload.get("body") or "")
        except ValueError as e:
            return _error(e)
        return None
    if path == "/api/ws/peers/read":
        try:
            return 200, ws.mark_peer_read(con, int(payload.get("id") or 0))
        except (ValueError, TypeError) as e:
            return _error(e)
    return None


def patch(con, path, payload):
    m = re.match(rf"^/api/ws/agents/{_AGENT}$", path or "")
    if not m:
        return None
    payload = payload if isinstance(payload, dict) else {}
    fields = {k: v for k, v in payload.items() if k in ws.PATCHABLE}
    if not fields:
        return 400, {"error": "no patchable fields",
                     "patchable": list(ws.PATCHABLE)}
    try:
        return 200, ws.patch_agent(con, m.group("slug"), **fields)
    except ValueError as e:
        return _error(e)


def _rpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def _parts_text(message):
    parts = (message or {}).get("parts") or []
    texts = [p.get("text") for p in parts
             if isinstance(p, dict) and p.get("kind") == "text" and p.get("text")]
    return "\n".join(t.strip() for t in texts).strip()


def a2a(con, payload, base_url="", llm_cfg=None, chat_fn=None):
    """A2A JSON-RPC message/send. Returns a JSON-RPC response dict."""
    if not isinstance(payload, dict):
        return _rpc_error(None, -32700, "parse error")
    req_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return _rpc_error(req_id, -32600, "invalid request: jsonrpc 2.0 required")
    if payload.get("method") != "message/send":
        return _rpc_error(req_id, -32601,
                          f"method not found: {payload.get('method')}")
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return _rpc_error(req_id, -32602, "invalid params")
    message = params.get("message") or {}
    text = _parts_text(message)
    if not text:
        return _rpc_error(req_id, -32602,
                          "invalid params: message.parts needs a text part")
    slug = ((params.get("metadata") or {}).get("agent")
            or params.get("agent")
            or (message.get("metadata") or {}).get("agent") or "")
    slug = str(slug).strip()
    if not slug:
        return _rpc_error(req_id, -32602,
                          "invalid params: params.metadata.agent required")
    try:
        ws._agent_row(con, slug)
    except ValueError:
        return _rpc_error(req_id, -32001, f"unknown agent: {slug}")
    try:
        out = ws.chat(con, slug, text, llm_cfg=llm_cfg, chat_fn=chat_fn)
    except ValueError as e:
        return _rpc_error(req_id, -32602, str(e))
    task_id = "a2a-" + uuid.uuid4().hex
    reply = out.get("reply")
    state = "completed" if reply else "failed"
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "kind": "task",
            "id": task_id,
            "contextId": slug,
            "status": {"state": state, "timestamp": time.time()},
            "artifacts": [{
                "artifactId": "artifact-" + uuid.uuid4().hex,
                "name": "reply",
                "parts": [{"kind": "text",
                           "text": reply or ws.BRAIN_FALLBACK}],
            }],
            "metadata": {"agent": slug, "runId": out.get("run_id"),
                         "events": out.get("events") or []},
        },
    }
