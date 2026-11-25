"""Agents workspace: per-agent chats, runs, peer bus, A2A cards.

Additive tables in the shared brain.db. Seeding from agents_seed.json is
idempotent and never overwrites an edited prompt. Chat replies come from the
local OpenAI-compatible brain; tools stay with scheduled Hermes runs.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid

from . import cron_sync, llm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_PATH = os.path.join(ROOT, "agents_seed.json")

MAX_BODY = 8000
MAX_SUMMARY = 400
HISTORY = 12
ROLES = ("user", "assistant", "system", "peer")
RUN_STATUSES = ("running", "ok", "error")
BRAIN_FALLBACK = (
    "The brain is unreachable right now. Try again, or trigger a run so the "
    "scheduled job does the work with its tools.")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ws_agents(
  id TEXT PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  purpose TEXT NOT NULL DEFAULT '',
  avatar TEXT NOT NULL DEFAULT '',
  color TEXT NOT NULL DEFAULT '',
  system_prompt TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  schedule TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  source_job_ids TEXT NOT NULL DEFAULT '[]',
  tools_json TEXT NOT NULL DEFAULT '[]',
  created_at REAL NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ws_messages(
  id INTEGER PRIMARY KEY,
  agent_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'user',
  body TEXT NOT NULL DEFAULT '',
  run_id TEXT NOT NULL DEFAULT '',
  task_id TEXT NOT NULL DEFAULT '',
  peer_from TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ws_runs(
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  job_id TEXT NOT NULL DEFAULT '',
  started_at REAL NOT NULL DEFAULT 0,
  ended_at REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'running',
  summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ws_peers(
  id INTEGER PRIMARY KEY,
  from_agent TEXT NOT NULL,
  to_agent TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  task_id TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL DEFAULT 0,
  read_at REAL
);
CREATE INDEX IF NOT EXISTS idx_ws_messages_agent ON ws_messages(agent_id, id);
CREATE INDEX IF NOT EXISTS idx_ws_runs_agent ON ws_runs(agent_id, started_at);
CREATE INDEX IF NOT EXISTS idx_ws_peers_to ON ws_peers(to_agent, id);
"""

AGENT_COLUMNS = {
    "id": "TEXT PRIMARY KEY",
    "slug": "TEXT UNIQUE NOT NULL",
    "name": "TEXT NOT NULL DEFAULT ''",
    "purpose": "TEXT NOT NULL DEFAULT ''",
    "avatar": "TEXT NOT NULL DEFAULT ''",
    "color": "TEXT NOT NULL DEFAULT ''",
    "system_prompt": "TEXT NOT NULL DEFAULT ''",
    "model": "TEXT NOT NULL DEFAULT ''",
    "schedule": "TEXT NOT NULL DEFAULT ''",
    "enabled": "INTEGER NOT NULL DEFAULT 1",
    "source_job_ids": "TEXT NOT NULL DEFAULT '[]'",
    "tools_json": "TEXT NOT NULL DEFAULT '[]'",
    "created_at": "REAL NOT NULL DEFAULT 0",
    "updated_at": "REAL NOT NULL DEFAULT 0",
}

PATCHABLE = ("name", "purpose", "avatar", "color", "system_prompt", "model",
             "schedule", "enabled", "source_job_ids", "tools_json")


def _cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _ensure(con):
    con.executescript(SCHEMA)
    have = _cols(con, "ws_agents")
    for name, decl in AGENT_COLUMNS.items():
        if name not in have:
            con.execute(f"ALTER TABLE ws_agents ADD COLUMN {name} {decl}")
    con.commit()


def _slug(value):
    s = re.sub(r"[^a-z0-9._-]+", "-", (value or "").lower()).strip("-.")[:48]
    if not s:
        raise ValueError("agent slug required")
    return s


def _json_list(raw):
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


def seed(con, path=None):
    """Insert seeded agents once. Existing rows (and edited prompts) stay."""
    _ensure(con)
    path = path or SEED_PATH
    with open(path) as f:
        rows = json.load(f)
    if not isinstance(rows, list):
        raise ValueError("agents_seed.json must be a list")
    now = time.time()
    inserted = 0
    for row in rows:
        slug = _slug(row.get("slug") or row.get("name") or "")
        cur = con.execute(
            "INSERT INTO ws_agents(id, slug, name, purpose, avatar, color,"
            " system_prompt, model, schedule, enabled, source_job_ids,"
            " tools_json, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(slug) DO NOTHING",
            (uuid.uuid4().hex, slug, (row.get("name") or slug)[:120],
             (row.get("purpose") or "")[:1000],
             (row.get("avatar") or "")[:8], (row.get("color") or "")[:32],
             (row.get("system_prompt") or "")[:4000],
             (row.get("model") or "")[:120], (row.get("schedule") or "")[:400],
             0 if row.get("enabled") is False else 1,
             json.dumps(row.get("source_job_ids") or []),
             json.dumps(row.get("tools_json") or []), now, now))
        inserted += cur.rowcount
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM ws_agents").fetchone()[0]
    return {"inserted": inserted, "total": total, "path": path}


def _agent_row(con, slug):
    r = con.execute(
        "SELECT id, slug, name, purpose, avatar, color, system_prompt, model,"
        " schedule, enabled, source_job_ids, tools_json, created_at,"
        " updated_at FROM ws_agents WHERE slug=?",
        (_slug(slug),)).fetchone()
    if not r:
        raise ValueError(f"unknown agent: {slug}")
    return {
        "id": r["id"], "slug": r["slug"], "name": r["name"],
        "purpose": r["purpose"], "avatar": r["avatar"],
        "color": r["color"], "system_prompt": r["system_prompt"],
        "model": r["model"], "schedule": r["schedule"],
        "enabled": bool(r["enabled"]),
        "source_job_ids": _json_list(r["source_job_ids"]),
        "tools": _json_list(r["tools_json"]),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def _last_run(con, agent_id):
    r = con.execute(
        "SELECT id, agent_id, job_id, started_at, ended_at, status, summary"
        " FROM ws_runs WHERE agent_id=?"
        " ORDER BY COALESCE(ended_at, started_at) DESC, rowid DESC LIMIT 1",
        (agent_id,)).fetchone()
    if not r:
        return None
    return {
        "id": r["id"], "agent_id": r["agent_id"], "job_id": r["job_id"],
        "started_at": r["started_at"], "ended_at": r["ended_at"],
        "status": r["status"], "summary": r["summary"],
    }


def _status(con, agent_id, last_run, cron=None):
    running = con.execute(
        "SELECT 1 FROM ws_runs WHERE agent_id=? AND status='running' LIMIT 1",
        (agent_id,)).fetchone()
    if running:
        return "running"
    if last_run and last_run["status"] == "error":
        return "error"
    if cron and cron.get("last_status") == "error":
        cron_ts = cron.get("last_run_ts") or 0
        run_ts = ((last_run["ended_at"] or last_run["started_at"])
                  if last_run else 0)
        if cron_ts >= run_ts:
            return "error"
    return "idle"


def list_agents(con, cron_path=None):
    _ensure(con)
    cron = cron_sync.load(cron_path)
    out = []
    for r in con.execute(
            "SELECT id, slug, name, purpose, avatar, color, schedule, enabled,"
            " source_job_ids, updated_at FROM ws_agents"
            " ORDER BY created_at, slug"):
        last = _last_run(con, r["id"])
        live = cron_sync.summarize(_json_list(r["source_job_ids"]), cron)
        out.append({
            "id": r["id"], "slug": r["slug"], "name": r["name"],
            "purpose": r["purpose"], "avatar": r["avatar"],
            "color": r["color"], "schedule": r["schedule"],
            "enabled": bool(r["enabled"]),
            "source_job_ids": _json_list(r["source_job_ids"]),
            "cron": live,
            "status": _status(con, r["id"], last, live),
            "last_run": last,
            "updated_at": r["updated_at"],
        })
    return out


def list_messages(con, slug, limit=50):
    _ensure(con)
    agent = _agent_row(con, slug)
    rows = con.execute(
        "SELECT id, role, body, run_id, task_id, peer_from, created_at"
        " FROM ws_messages WHERE agent_id=?"
        " ORDER BY id DESC LIMIT ?",
        (agent["id"], max(1, min(int(limit or 50), 200)))).fetchall()
    return [{
        "id": r["id"], "role": r["role"], "body": r["body"],
        "run_id": r["run_id"], "task_id": r["task_id"],
        "peer_from": r["peer_from"], "created_at": r["created_at"],
    } for r in reversed(rows)]


def _history(con, agent_id, limit=HISTORY):
    rows = con.execute(
        "SELECT role, body, peer_from FROM ws_messages WHERE agent_id=?"
        " ORDER BY id DESC LIMIT ?", (agent_id, limit)).fetchall()
    return list(reversed(rows))


def add_message(con, slug, role, body, run_id="", task_id="", peer_from=""):
    _ensure(con)
    agent = _agent_row(con, slug)
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    text = (body or "").strip()[:MAX_BODY]
    if not text:
        raise ValueError("body required")
    cur = con.execute(
        "INSERT INTO ws_messages(agent_id, role, body, run_id, task_id,"
        " peer_from, created_at) VALUES(?,?,?,?,?,?,?)",
        (agent["id"], role, text, run_id or "", task_id or "",
         peer_from or "", time.time()))
    con.commit()
    return {
        "id": cur.lastrowid, "role": role, "body": text,
        "run_id": run_id or "", "task_id": task_id or "",
        "peer_from": peer_from or "", "created_at": time.time(),
    }


def list_runs(con, slug, limit=20):
    _ensure(con)
    agent = _agent_row(con, slug)
    rows = con.execute(
        "SELECT id, agent_id, job_id, started_at, ended_at, status, summary"
        " FROM ws_runs WHERE agent_id=?"
        " ORDER BY COALESCE(ended_at, started_at) DESC, rowid DESC LIMIT ?",
        (agent["id"], max(1, min(int(limit or 20), 200)))).fetchall()
    return [{
        "id": r["id"], "agent_id": r["agent_id"], "job_id": r["job_id"],
        "started_at": r["started_at"], "ended_at": r["ended_at"],
        "status": r["status"], "summary": r["summary"],
    } for r in rows]


def start_run(con, slug, job_id=""):
    _ensure(con)
    agent = _agent_row(con, slug)
    now = time.time()
    rid = uuid.uuid4().hex
    con.execute(
        "INSERT INTO ws_runs(id, agent_id, job_id, started_at, ended_at,"
        " status, summary) VALUES(?,?,?,?,?,?,?)",
        (rid, agent["id"], (job_id or "")[:64], now, 0, "running", ""))
    con.commit()
    return {"id": rid, "agent_id": agent["id"], "job_id": job_id or "",
            "started_at": now, "ended_at": 0, "status": "running",
            "summary": ""}


def finish_run(con, run_id, status, summary=""):
    _ensure(con)
    if status not in RUN_STATUSES:
        raise ValueError(f"status must be one of {RUN_STATUSES}")
    row = con.execute("SELECT id FROM ws_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise ValueError(f"unknown run: {run_id}")
    con.execute(
        "UPDATE ws_runs SET ended_at=?, status=?, summary=? WHERE id=?",
        (time.time(), status, (summary or "")[:MAX_SUMMARY], run_id))
    con.commit()
    r = con.execute(
        "SELECT id, agent_id, job_id, started_at, ended_at, status, summary"
        " FROM ws_runs WHERE id=?", (run_id,)).fetchone()
    return {
        "id": r["id"], "agent_id": r["agent_id"], "job_id": r["job_id"],
        "started_at": r["started_at"], "ended_at": r["ended_at"],
        "status": r["status"], "summary": r["summary"],
    }


def record_run(con, slug, job_id="", status="ok", summary="",
               started_at=None, ended_at=None):
    _ensure(con)
    agent = _agent_row(con, slug)
    if status not in RUN_STATUSES:
        raise ValueError(f"status must be one of {RUN_STATUSES}")
    rid = uuid.uuid4().hex
    end = time.time() if ended_at is None else float(ended_at)
    start = (end if started_at is None else float(started_at))
    con.execute(
        "INSERT INTO ws_runs(id, agent_id, job_id, started_at, ended_at,"
        " status, summary) VALUES(?,?,?,?,?,?,?)",
        (rid, agent["id"], (job_id or "")[:64], start, end, status,
         (summary or "")[:MAX_SUMMARY]))
    con.commit()
    return {"id": rid, "agent_id": agent["id"], "job_id": job_id or "",
            "started_at": start, "ended_at": end, "status": status,
            "summary": summary or ""}


def _brain_messages(agent, history, body):
    msgs = []
    for r in history:
        if r["role"] == "peer":
            msgs.append({"role": "user",
                         "content": f"[peer {r['peer_from']}] {r['body']}"})
        elif r["role"] in ("user", "assistant"):
            msgs.append({"role": r["role"], "content": r["body"]})
    msgs.append({"role": "user", "content": body})
    return msgs


def _default_chat_fn(llm_cfg, timeout=180):
    base_url = (llm_cfg or {}).get("base_url") or ""
    model = (llm_cfg or {}).get("model") or ""
    api_key = (llm_cfg or {}).get("api_key") or ""

    def _fn(system, messages):
        return llm.complete(base_url, model,
                            [{"role": "system", "content": system}] + messages,
                            timeout=timeout, api_key=api_key)

    return _fn


def chat(con, slug, body, llm_cfg=None, chat_fn=None, timeout=180):
    """One chat turn against the agent's prompt + last 12 messages.

    Returns AG-UI-shaped events, the stored reply, and the run id. A brain
    failure is recorded as an error run, not raised.
    """
    _ensure(con)
    agent = _agent_row(con, slug)
    text = (body or "").strip()[:MAX_BODY]
    if not text:
        raise ValueError("body required")
    history = _history(con, agent["id"])
    add_message(con, slug, "user", text)
    run = start_run(con, slug, job_id="chat")
    messages = _brain_messages(agent, history, text)
    fn = chat_fn or _default_chat_fn(llm_cfg or {}, timeout=timeout)
    reply = None
    try:
        reply = fn(agent["system_prompt"] or "", messages)
    except Exception:
        reply = None
    events = [{
        "type": "RUN_STARTED",
        "threadId": agent["slug"],
        "runId": run["id"],
        "agent": agent["slug"],
    }]
    if reply is None:
        stored = add_message(con, slug, "assistant", BRAIN_FALLBACK,
                             run_id=run["id"])
        finish_run(con, run["id"], "error", "brain unreachable")
        events.append({"type": "RUN_ERROR", "message": BRAIN_FALLBACK,
                       "runId": run["id"]})
        return {"agent": agent["slug"], "run_id": run["id"], "reply": None,
                "message_id": stored["id"], "events": events}
    stored = add_message(con, slug, "assistant", reply, run_id=run["id"])
    finish_run(con, run["id"], "ok", reply)
    events.append({"type": "TEXT_MESSAGE_CONTENT",
                   "messageId": stored["id"], "delta": reply})
    events.append({"type": "RUN_FINISHED", "threadId": agent["slug"],
                   "runId": run["id"], "result": reply})
    return {"agent": agent["slug"], "run_id": run["id"], "reply": reply,
            "message_id": stored["id"], "events": events}


def chips(con, slug):
    """Server-composed composer chips + ghost prompt. No client invention."""
    agent = _agent_row(con, slug)
    last = _last_run(con, agent["id"])
    out = []
    if agent["source_job_ids"]:
        out.append({"label": "Run now", "kind": "run",
                    "payload": agent["source_job_ids"][0]})
    out.append({"label": "Schedule", "kind": "drawer",
                "payload": agent["schedule"] or "on demand"})
    out.append({"label": "Open inbox", "kind": "inbox", "payload": ""})
    out.append({"label": "Last run", "kind": "prompt",
                "payload": "What did the last run find?"})
    purpose = (agent["purpose"] or "").rstrip(".")
    ghost = (f"What is the latest on {purpose}?" if purpose
             else f"What does {agent['name']} own?")
    return {"chips": out, "ghost": ghost[:200],
            "has_runs": bool(last)}


def patch_agent(con, slug, **fields):
    _ensure(con)
    agent = _agent_row(con, slug)
    sets, args = ["updated_at=?"], [time.time()]
    for key, value in fields.items():
        if key not in PATCHABLE or value is None:
            continue
        if key == "enabled":
            sets.append("enabled=?")
            args.append(1 if value else 0)
        elif key == "source_job_ids":
            if not isinstance(value, list):
                raise ValueError("source_job_ids must be a list")
            sets.append("source_job_ids=?")
            args.append(json.dumps([str(v) for v in value]))
        elif key == "tools_json":
            sets.append("tools_json=?")
            args.append(json.dumps(value if isinstance(value, list) else []))
        elif key == "name":
            text = str(value).strip()[:120]
            if not text:
                raise ValueError("name required")
            sets.append("name=?")
            args.append(text)
        else:
            cap = 4000 if key == "system_prompt" else 1000
            sets.append(f"{key}=?")
            args.append(str(value).strip()[:cap])
    args.append(agent["id"])
    con.execute("UPDATE ws_agents SET " + ", ".join(sets) + " WHERE id=?",
                args)
    con.commit()
    return _agent_row(con, slug)


def get_agent(con, slug, cron_path=None):
    _ensure(con)
    agent = _agent_row(con, slug)
    last = _last_run(con, agent["id"])
    live = cron_sync.summarize(agent["source_job_ids"],
                               cron_sync.load(cron_path))
    agent["cron"] = live
    agent["status"] = _status(con, agent["id"], last, live)
    agent["last_run"] = last
    agent["messages"] = list_messages(con, slug, limit=50)
    agent["runs"] = list_runs(con, slug, limit=20)
    agent["chips"] = chips(con, slug)
    return agent


def send_peer(con, from_slug, to_slug, body):
    """Agent-to-agent message: peer bus row + A2A task id + mirror message."""
    _ensure(con)
    src = _agent_row(con, from_slug)
    dst = _agent_row(con, to_slug)
    if src["slug"] == dst["slug"]:
        raise ValueError("cannot message self")
    text = (body or "").strip()[:MAX_BODY]
    if not text:
        raise ValueError("body required")
    task_id = "a2a-" + uuid.uuid4().hex
    now = time.time()
    cur = con.execute(
        "INSERT INTO ws_peers(from_agent, to_agent, body, task_id, created_at)"
        " VALUES(?,?,?,?,?)",
        (src["slug"], dst["slug"], text, task_id, now))
    con.commit()
    add_message(con, dst["slug"], "peer", text, task_id=task_id,
                peer_from=src["slug"])
    return {"id": cur.lastrowid, "from": src["slug"], "to": dst["slug"],
            "body": text, "task_id": task_id, "created_at": now}


def list_peers(con, limit=50, unread_only=False, to_agent=None):
    _ensure(con)
    sql = ("SELECT id, from_agent, to_agent, body, task_id, created_at,"
           " read_at FROM ws_peers")
    args = []
    conds = []
    if to_agent:
        conds.append("to_agent=?")
        args.append(_slug(to_agent))
    if unread_only:
        conds.append("read_at IS NULL")
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(int(limit or 50), 200)))
    return [{
        "id": r["id"], "from": r["from_agent"], "to": r["to_agent"],
        "body": r["body"], "task_id": r["task_id"],
        "created_at": r["created_at"], "read_at": r["read_at"],
    } for r in con.execute(sql, args)]


def mark_peer_read(con, peer_id):
    _ensure(con)
    row = con.execute("SELECT id FROM ws_peers WHERE id=?",
                      (peer_id,)).fetchone()
    if not row:
        raise ValueError(f"unknown peer message: {peer_id}")
    now = time.time()
    con.execute("UPDATE ws_peers SET read_at=? WHERE id=?", (now, peer_id))
    con.commit()
    return {"id": peer_id, "read_at": now}


def _base(base_url):
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("base_url required")
    return base


def agent_card(con, slug, base_url):
    agent = _agent_row(con, slug)
    base = _base(base_url)
    return {
        "protocolVersion": "0.3.0",
        "name": agent["name"],
        "description": agent["purpose"] or f"{agent['name']} agent",
        "url": f"{base}/api/ws/agents/{agent['slug']}",
        "preferredTransport": "JSONRPC",
        "version": "1.0.0",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{
            "id": agent["slug"],
            "name": agent["name"],
            "description": agent["purpose"] or agent["name"],
            "tags": [agent["slug"], "agent-manager"],
        }],
    }


def workspace_card(con, base_url):
    _ensure(con)
    base = _base(base_url)
    skills = [{
        "id": a["slug"],
        "name": a["name"],
        "description": a["purpose"] or a["name"],
        "tags": [a["slug"], "agent-manager"],
    } for a in list_agents(con)]
    return {
        "protocolVersion": "0.3.0",
        "name": "Agent Manager",
        "description": "Personal agents workspace: chats, runs, peer bus.",
        "url": f"{base}/a2a",
        "preferredTransport": "JSONRPC",
        "version": "1.0.0",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": skills,
    }
