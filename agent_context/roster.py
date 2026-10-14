"""Cross-project agent roster + shared task board.

Agents (hermes, cursor, grok-bot, …) each get an optional API key.
Tasks are shared — not tied to a repo. Rules route open tasks to agents
and mark whether they may run in parallel.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import time


DEFAULT_AGENTS = (
    ("hermes", "Hermes", 1),
    ("cursor", "Cursor", 1),
    ("grok-bot", "Grok Bot", 1),
)

STATUSES = ("open", "claimed", "done", "blocked")


def _ensure(con):
    con.execute(
        "CREATE TABLE IF NOT EXISTS agents ("
        "name TEXT PRIMARY KEY,"
        "label TEXT NOT NULL DEFAULT '',"
        "token_hash TEXT NOT NULL DEFAULT '',"
        "token_hint TEXT NOT NULL DEFAULT '',"
        "parallel_ok INTEGER NOT NULL DEFAULT 1,"
        "created_at REAL NOT NULL DEFAULT 0)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS tasks ("
        "id INTEGER PRIMARY KEY,"
        "title TEXT NOT NULL,"
        "body TEXT NOT NULL DEFAULT '',"
        "status TEXT NOT NULL DEFAULT 'open',"
        "assignee TEXT NOT NULL DEFAULT '',"
        "parallel INTEGER NOT NULL DEFAULT 0,"
        "created_by TEXT NOT NULL DEFAULT '',"
        "created_at REAL NOT NULL DEFAULT 0,"
        "updated_at REAL NOT NULL DEFAULT 0)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS task_rules ("
        "id INTEGER PRIMARY KEY,"
        "match TEXT NOT NULL,"
        "agent TEXT NOT NULL,"
        "parallel INTEGER NOT NULL DEFAULT 0,"
        "priority INTEGER NOT NULL DEFAULT 0)"
    )
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    if n == 0:
        now = time.time()
        for name, label, pok in DEFAULT_AGENTS:
            con.execute(
                "INSERT INTO agents(name, label, parallel_ok, created_at) "
                "VALUES(?,?,?,?)", (name, label, pok, now))
        # starter rules — hermes does on-device, cursor does code
        con.execute(
            "INSERT INTO task_rules(match, agent, parallel, priority) VALUES"
            "('on-device', 'hermes', 0, 10),"
            "('deploy', 'hermes', 0, 8),"
            "('code', 'cursor', 1, 10),"
            "('review', 'grok-bot', 1, 5)")
        con.commit()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", (name or "").lower()).strip("-.")[:48]
    if not s:
        raise ValueError("agent name required")
    return s


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def seed_if_needed(con):
    _ensure(con)


def list_agents(con):
    _ensure(con)
    rows = con.execute(
        "SELECT name, label, token_hint, parallel_ok, created_at,"
        " CASE WHEN token_hash != '' THEN 1 ELSE 0 END AS has_key "
        "FROM agents ORDER BY name").fetchall()
    return [{
        "name": r["name"], "label": r["label"] or r["name"],
        "has_key": bool(r["has_key"]), "token_hint": r["token_hint"] or "",
        "parallel_ok": bool(r["parallel_ok"]),
        "created_at": r["created_at"],
    } for r in rows]


def upsert_agent(con, name, label=None, parallel_ok=None):
    _ensure(con)
    name = _slug(name)
    label = (label or name).strip()[:64]
    row = con.execute("SELECT name FROM agents WHERE name=?", (name,)).fetchone()
    if row:
        if parallel_ok is not None:
            con.execute("UPDATE agents SET parallel_ok=? WHERE name=?",
                        (1 if parallel_ok else 0, name))
        if label:
            con.execute("UPDATE agents SET label=? WHERE name=?", (label, name))
    else:
        con.execute(
            "INSERT INTO agents(name, label, parallel_ok, created_at) "
            "VALUES(?,?,?,?)",
            (name, label, 1 if parallel_ok is None or parallel_ok else 0,
             time.time()))
    con.commit()
    return next(a for a in list_agents(con) if a["name"] == name)


def mint_agent_key(con, name):
    """Issue a view-once API key for an agent. Returns raw token once."""
    _ensure(con)
    name = _slug(name)
    if not con.execute("SELECT 1 FROM agents WHERE name=?", (name,)).fetchone():
        upsert_agent(con, name)
    raw = secrets.token_urlsafe(24)
    con.execute(
        "UPDATE agents SET token_hash=?, token_hint=? WHERE name=?",
        (_hash(raw), raw[-4:], name))
    con.commit()
    return {"agent": name, "token": raw, "hint": raw[-4:],
            "message": "Copy now — shown once."}


def agent_token_ok(con, token: str):
    """True if token matches any agent key."""
    if not token:
        return False
    _ensure(con)
    digest = _hash(token)
    row = con.execute(
        "SELECT name FROM agents WHERE token_hash=?", (digest,)).fetchone()
    return row["name"] if row else None


def list_rules(con):
    _ensure(con)
    rows = con.execute(
        "SELECT id, match, agent, parallel, priority FROM task_rules "
        "ORDER BY priority DESC, id").fetchall()
    return [{
        "id": r["id"], "match": r["match"], "agent": r["agent"],
        "parallel": bool(r["parallel"]), "priority": r["priority"],
    } for r in rows]


def set_rules(con, rules):
    """Replace all rules. rules = [{match, agent, parallel?, priority?}]"""
    _ensure(con)
    if not isinstance(rules, list):
        raise ValueError("rules must be a list")
    con.execute("DELETE FROM task_rules")
    for i, rule in enumerate(rules):
        match = (rule.get("match") or "").strip()[:120]
        agent = _slug(rule.get("agent") or "")
        if not match or not agent:
            continue
        con.execute(
            "INSERT INTO task_rules(match, agent, parallel, priority) "
            "VALUES(?,?,?,?)",
            (match, agent, 1 if rule.get("parallel") else 0,
             int(rule.get("priority", 10 - i))))
    con.commit()
    return list_rules(con)


def _apply_rule(con, title, body):
    text = f"{title}\n{body}".lower()
    for rule in list_rules(con):
        if rule["match"].lower() in text:
            return rule["agent"], rule["parallel"]
    return "", None


def list_tasks(con, status=None, assignee=None, limit=100):
    _ensure(con)
    sql = ("SELECT id, title, body, status, assignee, parallel, created_by,"
           " created_at, updated_at FROM tasks WHERE 1=1")
    args = []
    if status:
        sql += " AND status=?"
        args.append(status)
    if assignee:
        sql += " AND assignee=?"
        args.append(_slug(assignee))
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    args.append(max(1, min(int(limit or 100), 200)))
    return [{
        "id": r["id"], "title": r["title"], "body": r["body"],
        "status": r["status"], "assignee": r["assignee"],
        "parallel": bool(r["parallel"]), "created_by": r["created_by"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    } for r in con.execute(sql, args)]


def add_task(con, title, body="", assignee="", parallel=None,
             created_by="", auto_route=True):
    _ensure(con)
    title = (title or "").strip()[:200]
    body = (body or "").strip()[:8000]
    if not title:
        raise ValueError("title required")
    assignee = _slug(assignee) if assignee else ""
    if parallel is None:
        parallel = 0
    else:
        parallel = 1 if parallel else 0
    if auto_route and not assignee:
        routed, p = _apply_rule(con, title, body)
        if routed:
            assignee = routed
            if p is not None:
                parallel = 1 if p else 0
    now = time.time()
    cur = con.execute(
        "INSERT INTO tasks(title, body, status, assignee, parallel,"
        " created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (title, body, "open", assignee, parallel, created_by or "", now, now))
    con.commit()
    tid = cur.lastrowid
    return next(t for t in list_tasks(con, limit=500) if t["id"] == tid)


def _busy_blocks(con, agent, parallel):
    """Can this agent claim a task with this parallel flag right now?"""
    claimed = con.execute(
        "SELECT id, parallel FROM tasks WHERE status='claimed' AND assignee=?",
        (agent,)).fetchall()
    if not claimed:
        return None
    if any(not r["parallel"] for r in claimed):
        return "agent has a serial task claimed"
    if not parallel:
        return "serial task but agent already has claimed work"
    return None


def claim_task(con, task_id, agent):
    _ensure(con)
    agent = _slug(agent)
    row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise ValueError("unknown task")
    if row["status"] not in ("open", "blocked"):
        raise ValueError(f"task is {row['status']}")
    assignee = row["assignee"] or agent
    if row["assignee"] and row["assignee"] != agent:
        raise ValueError(f"task assigned to {row['assignee']}")
    block = _busy_blocks(con, agent, bool(row["parallel"]))
    if block:
        raise ValueError(block)
    now = time.time()
    con.execute(
        "UPDATE tasks SET status='claimed', assignee=?, updated_at=? WHERE id=?",
        (assignee, now, task_id))
    con.commit()
    return next(t for t in list_tasks(con, limit=500) if t["id"] == task_id)


def update_task(con, task_id, status=None, assignee=None, parallel=None,
                title=None, body=None):
    _ensure(con)
    row = con.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise ValueError("unknown task")
    sets, args = ["updated_at=?"], [time.time()]
    if status is not None:
        if status not in STATUSES:
            raise ValueError("bad status")
        sets.append("status=?")
        args.append(status)
    if assignee is not None:
        sets.append("assignee=?")
        args.append(_slug(assignee) if assignee else "")
    if parallel is not None:
        sets.append("parallel=?")
        args.append(1 if parallel else 0)
    if title is not None:
        sets.append("title=?")
        args.append(title.strip()[:200])
    if body is not None:
        sets.append("body=?")
        args.append(body.strip()[:8000])
    args.append(task_id)
    con.execute("UPDATE tasks SET " + ", ".join(sets) + " WHERE id=?", args)
    con.commit()
    return next(t for t in list_tasks(con, limit=500) if t["id"] == task_id)
