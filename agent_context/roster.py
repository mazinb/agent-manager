"""Agent roster + chat-linked task boards.

Boards are tied to an inbox chat slug (`boards.chat`). Agents must be
members to claim work. Tasks and rules are scoped to a board.
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

DEFAULT_CHAT = "peers"
STATUSES = ("open", "claimed", "done", "blocked")
MEMBER_ROLES = ("member", "worker", "admin")

# Soft caps so session packs stay injectable without bloating context.
MAX_BRIEF_CHARS = 4000
MAX_SESSION_PACK_CHARS = 12000

DEFAULT_BRIEFS = {
    "hermes": (
        "---\n"
        "routes: on-device=serial, deploy=serial\n"
        "---\n\n"
        "# Hermes\n\n"
        "On-device worker. Cursor plans and supervises; you execute one job "
        "at a time, then reply on peers with `role: done|status|block`.\n"
        "Keep bodies short. No secrets. Prefer peer inbox over A2A.\n"
    ),
    "cursor": (
        "---\n"
        "routes: code=parallel, plan=parallel\n"
        "---\n\n"
        "# Cursor\n\n"
        "Planner / supervisor. Own complex design/UI work; hand on-device "
        "exec to Hermes; ask designer/grok-bot for punch lists. "
        "Short `role: plan|handoff` notes.\n"
    ),
    "grok-bot": (
        "---\n"
        "routes: review=parallel, design=parallel\n"
        "---\n\n"
        "# Grok Bot\n\n"
        "Design and review peer. Punch lists over essays. Reply on peers; "
        "do not dump long threads into briefs.\n"
    ),
    "designer": (
        "---\n"
        "routes: review=parallel, design=parallel\n"
        "---\n\n"
        "# Designer\n\n"
        "UI review peer. Short punch lists on /agents/ and /join/. "
        "Keep palette and flat sections; no cards/pills/emoji.\n"
    ),
    "hermes-connector": (
        "---\n"
        "routes: bridge=parallel\n"
        "---\n\n"
        "# Hermes Connector\n\n"
        "Bridge Hermes chats onto the peers bus. Use your own agent key "
        "(not admin). Prefer message_peer; keep feedback short.\n"
    ),
}


def _cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _ensure(con):
    con.execute(
        "CREATE TABLE IF NOT EXISTS agents ("
        "name TEXT PRIMARY KEY,"
        "label TEXT NOT NULL DEFAULT '',"
        "token_hash TEXT NOT NULL DEFAULT '',"
        "token_hint TEXT NOT NULL DEFAULT '',"
        "parallel_ok INTEGER NOT NULL DEFAULT 1,"
        "created_at REAL NOT NULL DEFAULT 0,"
        "last_seen_at REAL NOT NULL DEFAULT 0)"
    )
    if "last_seen_at" not in _cols(con, "agents"):
        con.execute(
            "ALTER TABLE agents ADD COLUMN last_seen_at "
            "REAL NOT NULL DEFAULT 0")
    if "is_admin" not in _cols(con, "agents"):
        con.execute(
            "ALTER TABLE agents ADD COLUMN is_admin "
            "INTEGER NOT NULL DEFAULT 0")
    con.execute(
        "CREATE TABLE IF NOT EXISTS boards ("
        "id INTEGER PRIMARY KEY,"
        "chat TEXT NOT NULL UNIQUE,"
        "title TEXT NOT NULL DEFAULT '',"
        "host_agent TEXT NOT NULL DEFAULT '',"
        "created_at REAL NOT NULL DEFAULT 0)"
    )
    if "host_agent" not in _cols(con, "boards"):
        con.execute(
            "ALTER TABLE boards ADD COLUMN host_agent "
            "TEXT NOT NULL DEFAULT ''")
    con.execute(
        "CREATE TABLE IF NOT EXISTS board_members ("
        "board_id INTEGER NOT NULL,"
        "agent TEXT NOT NULL,"
        "role TEXT NOT NULL DEFAULT 'member',"
        "added_at REAL NOT NULL DEFAULT 0,"
        "PRIMARY KEY (board_id, agent))"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS tasks ("
        "id INTEGER PRIMARY KEY,"
        "board_id INTEGER NOT NULL DEFAULT 0,"
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
        "board_id INTEGER NOT NULL DEFAULT 0,"
        "match TEXT NOT NULL,"
        "agent TEXT NOT NULL,"
        "parallel INTEGER NOT NULL DEFAULT 0,"
        "priority INTEGER NOT NULL DEFAULT 0,"
        "enabled INTEGER NOT NULL DEFAULT 1)"
    )
    if "board_id" not in _cols(con, "tasks"):
        con.execute(
            "ALTER TABLE tasks ADD COLUMN board_id INTEGER NOT NULL DEFAULT 0")
    if "board_id" not in _cols(con, "task_rules"):
        con.execute(
            "ALTER TABLE task_rules ADD COLUMN board_id "
            "INTEGER NOT NULL DEFAULT 0")
    if "enabled" not in _cols(con, "task_rules"):
        con.execute(
            "ALTER TABLE task_rules ADD COLUMN enabled "
            "INTEGER NOT NULL DEFAULT 1")
    con.execute(
        "CREATE TABLE IF NOT EXISTS agent_briefs ("
        "board_id INTEGER NOT NULL,"
        "agent TEXT NOT NULL,"
        "body TEXT NOT NULL DEFAULT '',"
        "content_hash TEXT NOT NULL DEFAULT '',"
        "updated_at REAL NOT NULL DEFAULT 0,"
        "PRIMARY KEY (board_id, agent))"
    )
    con.commit()

    n = con.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    if n == 0:
        now = time.time()
        for name, label, pok in DEFAULT_AGENTS:
            con.execute(
                "INSERT INTO agents(name, label, parallel_ok, created_at) "
                "VALUES(?,?,?,?)", (name, label, pok, now))
        con.commit()

    board = _get_or_create_board_raw(con, DEFAULT_CHAT, title="Peers")
    # Migrate legacy global is_admin → peers board host (once).
    if not (board.get("host_agent") or "").strip():
        row = con.execute(
            "SELECT name FROM agents WHERE is_admin=1 LIMIT 1").fetchone()
        host = row["name"] if row else "cursor"
        con.execute(
            "UPDATE boards SET host_agent=? WHERE id=?", (host, board["id"]))
        board["host_agent"] = host
        con.commit()
    _sync_is_admin(con)
    # Migrate legacy unscoped rows onto the default board.
    con.execute(
        "UPDATE tasks SET board_id=? WHERE board_id=0 OR board_id IS NULL",
        (board["id"],))
    con.execute(
        "UPDATE task_rules SET board_id=? WHERE board_id=0 OR board_id IS NULL",
        (board["id"],))
    con.commit()

    rule_n = con.execute(
        "SELECT COUNT(*) FROM task_rules WHERE board_id=?",
        (board["id"],)).fetchone()[0]
    if rule_n == 0:
        con.execute(
            "INSERT INTO task_rules(board_id, match, agent, parallel, priority) "
            "VALUES"
            f"({board['id']}, 'on-device', 'hermes', 0, 10),"
            f"({board['id']}, 'deploy', 'hermes', 0, 8),"
            f"({board['id']}, 'code', 'cursor', 1, 10),"
            f"({board['id']}, 'review', 'grok-bot', 1, 5)")
        con.commit()

    for name, _, _ in DEFAULT_AGENTS:
        _ensure_member(con, board["id"], name, role="worker")
    # Seed default briefs for any board member that has a template (incl.
    # late joiners like designer / hermes-connector).
    for name, body in DEFAULT_BRIEFS.items():
        mem = con.execute(
            "SELECT 1 FROM board_members WHERE board_id=? AND agent=?",
            (board["id"], name)).fetchone()
        if not mem:
            continue
        row = con.execute(
            "SELECT 1 FROM agent_briefs WHERE board_id=? AND agent=?",
            (board["id"], name)).fetchone()
        if not row:
            _write_brief_raw(con, board["id"], name, body)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", (name or "").lower()).strip("-.")[:48]
    if not s:
        raise ValueError("agent name required")
    return s


def _chat_slug(chat: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", (chat or "").lower()).strip("-.")[:64]
    if not s:
        raise ValueError("chat required")
    return s


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def seed_if_needed(con):
    _ensure(con)


def _board_row(con, board_id):
    r = con.execute(
        "SELECT id, chat, title, host_agent, created_at FROM boards WHERE id=?",
        (board_id,)).fetchone()
    if not r:
        return None
    members = list_members(con, r["id"])
    open_n = con.execute(
        "SELECT COUNT(*) FROM tasks WHERE board_id=? AND status IN "
        "('open','claimed','blocked')", (r["id"],)).fetchone()[0]
    return {
        "id": r["id"], "chat": r["chat"], "title": r["title"] or r["chat"],
        "host_agent": r["host_agent"] or "",
        "created_at": r["created_at"],
        "members": members, "open_tasks": open_n,
    }


def _get_or_create_board_raw(con, chat, title="", host_agent=""):
    chat = _chat_slug(chat)
    row = con.execute(
        "SELECT id, chat, title, host_agent, created_at FROM boards WHERE chat=?",
        (chat,)).fetchone()
    if row:
        return {"id": row["id"], "chat": row["chat"],
                "title": row["title"] or row["chat"],
                "host_agent": row["host_agent"] or "",
                "created_at": row["created_at"]}
    now = time.time()
    title = (title or chat).strip()[:80]
    host_agent = _slug(host_agent) if host_agent else ""
    cur = con.execute(
        "INSERT INTO boards(chat, title, host_agent, created_at) "
        "VALUES(?,?,?,?)",
        (chat, title, host_agent, now))
    con.commit()
    return {"id": cur.lastrowid, "chat": chat, "title": title,
            "host_agent": host_agent, "created_at": now}


def _sync_is_admin(con):
    """is_admin mirrors 'hosts at least one board' for UI/compat."""
    con.execute("UPDATE agents SET is_admin=0")
    con.execute(
        "UPDATE agents SET is_admin=1 WHERE name IN "
        "(SELECT DISTINCT host_agent FROM boards "
        "WHERE host_agent IS NOT NULL AND host_agent != '')")
    con.commit()


def _ensure_member(con, board_id, agent, role="member"):
    agent = _slug(agent)
    if role not in MEMBER_ROLES:
        role = "member"
    row = con.execute(
        "SELECT 1 FROM board_members WHERE board_id=? AND agent=?",
        (board_id, agent)).fetchone()
    if row:
        return
    if not con.execute("SELECT 1 FROM agents WHERE name=?", (agent,)).fetchone():
        # Inline insert — avoid upsert_agent → _ensure recursion.
        con.execute(
            "INSERT INTO agents(name, label, parallel_ok, created_at) "
            "VALUES(?,?,?,?)", (agent, agent, 1, time.time()))
    con.execute(
        "INSERT INTO board_members(board_id, agent, role, added_at) "
        "VALUES(?,?,?,?)", (board_id, agent, role, time.time()))
    con.commit()


def list_boards(con):
    _ensure(con)
    ids = [r["id"] for r in con.execute(
        "SELECT id FROM boards ORDER BY chat")]
    return [_board_row(con, i) for i in ids]


def get_board(con, chat=None, board_id=None):
    _ensure(con)
    if board_id is not None:
        row = _board_row(con, int(board_id))
        if not row:
            raise ValueError("unknown board")
        return row
    if not chat:
        chat = DEFAULT_CHAT
    return get_or_create_board(con, chat)


def get_or_create_board(con, chat, title=""):
    """Shared/legacy open: seed default workers. Prefer create_hosted_board
    for an agent's own board."""
    _ensure(con)
    raw = _get_or_create_board_raw(con, chat, title=title)
    # New boards get default agents so coordination can start immediately.
    for name, _, _ in DEFAULT_AGENTS:
        _ensure_member(con, raw["id"], name, role="worker")
    return _board_row(con, raw["id"])


def create_hosted_board(con, chat, host_agent, title=""):
    """Create a personal board. Caller becomes host (admin member).

    Each agent may host at most one board. Does not seed DEFAULT_AGENTS —
    host invites whom they want.
    """
    _ensure(con)
    host_agent = _slug(host_agent)
    chat = _chat_slug(chat)
    if not con.execute(
            "SELECT 1 FROM agents WHERE name=?", (host_agent,)).fetchone():
        upsert_agent(con, host_agent)
    existing = con.execute(
        "SELECT chat FROM boards WHERE host_agent=?", (host_agent,)).fetchone()
    if existing:
        raise ValueError(
            f"already host of '{existing['chat']}' — each agent hosts one board")
    row = con.execute(
        "SELECT id, host_agent FROM boards WHERE chat=?", (chat,)).fetchone()
    if row:
        raise ValueError(f"board '{chat}' already exists")
    raw = _get_or_create_board_raw(
        con, chat, title=title or chat, host_agent=host_agent)
    _ensure_member(con, raw["id"], host_agent, role="admin")
    _sync_is_admin(con)
    return _board_row(con, raw["id"])


def board_host(con, chat=None, board_id=None) -> str:
    """Host agent name for a board, or ''."""
    _ensure(con)
    b = get_board(con, chat=chat, board_id=board_id)
    return (b.get("host_agent") or "") if b else ""


def hosted_board(con, agent):
    """The one board this agent hosts, or None."""
    _ensure(con)
    agent = _slug(agent)
    row = con.execute(
        "SELECT id FROM boards WHERE host_agent=?", (agent,)).fetchone()
    return _board_row(con, row["id"]) if row else None


def can_manage_board(con, token: str, admin_token: str = "",
                     chat=None, board_id=None) -> bool:
    """Bootstrap admin, or the host agent's key for that board."""
    if not token:
        return False
    if admin_token and secrets.compare_digest(token, admin_token):
        return True
    name = agent_token_ok(con, token)
    if not name:
        return False
    host = board_host(con, chat=chat, board_id=board_id)
    return bool(host) and name == host


def list_members(con, board_id):
    rows = con.execute(
        "SELECT m.agent, m.role, m.added_at, a.label "
        "FROM board_members m LEFT JOIN agents a ON a.name=m.agent "
        "WHERE m.board_id=? ORDER BY m.agent", (board_id,)).fetchall()
    return [{
        "agent": r["agent"],
        "label": r["label"] or r["agent"],
        "role": r["role"],
        "added_at": r["added_at"],
    } for r in rows]


def is_member(con, board_id, agent):
    agent = _slug(agent)
    return bool(con.execute(
        "SELECT 1 FROM board_members WHERE board_id=? AND agent=?",
        (board_id, agent)).fetchone())


def add_member(con, board_id=None, chat=None, agent="", role="worker"):
    _ensure(con)
    board = get_board(con, chat=chat, board_id=board_id)
    agent = _slug(agent)
    if role not in MEMBER_ROLES:
        raise ValueError(f"role must be one of {MEMBER_ROLES}")
    if not con.execute("SELECT 1 FROM agents WHERE name=?", (agent,)).fetchone():
        upsert_agent(con, agent)
    row = con.execute(
        "SELECT role FROM board_members WHERE board_id=? AND agent=?",
        (board["id"], agent)).fetchone()
    if row:
        con.execute(
            "UPDATE board_members SET role=? WHERE board_id=? AND agent=?",
            (role, board["id"], agent))
    else:
        con.execute(
            "INSERT INTO board_members(board_id, agent, role, added_at) "
            "VALUES(?,?,?,?)",
            (board["id"], agent, role, time.time()))
        if agent in DEFAULT_BRIEFS:
            existing = con.execute(
                "SELECT 1 FROM agent_briefs WHERE board_id=? AND agent=?",
                (board["id"], agent)).fetchone()
            if not existing:
                _write_brief_raw(con, board["id"], agent, DEFAULT_BRIEFS[agent])
    con.commit()
    return get_board(con, board_id=board["id"])


def remove_member(con, board_id=None, chat=None, agent=""):
    _ensure(con)
    board = get_board(con, chat=chat, board_id=board_id)
    agent = _slug(agent)
    con.execute(
        "DELETE FROM board_members WHERE board_id=? AND agent=?",
        (board["id"], agent))
    con.commit()
    return get_board(con, board_id=board["id"])


def _resolve_board_id(con, board_id=None, chat=None):
    if board_id is not None and board_id != "":
        b = get_board(con, board_id=int(board_id))
        return b["id"]
    return get_or_create_board(con, chat or DEFAULT_CHAT)["id"]


def list_agents(con):
    _ensure(con)
    rows = con.execute(
        "SELECT name, label, token_hint, parallel_ok, created_at, last_seen_at,"
        " is_admin,"
        " CASE WHEN token_hash != '' THEN 1 ELSE 0 END AS has_key "
        "FROM agents ORDER BY name").fetchall()
    return [{
        "name": r["name"], "label": r["label"] or r["name"],
        "has_key": bool(r["has_key"]), "token_hint": r["token_hint"] or "",
        "parallel_ok": bool(r["parallel_ok"]),
        "is_admin": bool(r["is_admin"]),
        "created_at": r["created_at"],
        "last_seen_at": r["last_seen_at"] or 0,
    } for r in rows]


def touch_last_seen(con, agent: str):
    """Bump last_seen_at when that agent's private key authenticates.

    Do not call from note/message handlers based on the agent= label —
    admin (or another key) can label posts for anyone. Wire this from
    whoami and from HTTP auth that resolves an agent key.
    """
    _ensure(con)
    agent = _slug(agent)
    if not con.execute("SELECT 1 FROM agents WHERE name=?", (agent,)).fetchone():
        return
    con.execute(
        "UPDATE agents SET last_seen_at=? WHERE name=?", (time.time(), agent))
    con.commit()


def whoami(con, token: str, admin_token: str = "") -> dict:
    """Resolve a presented token to an identity + boards.

    Agent keys → {agent, key_ok, boards, …}. Admin token → {admin: true}.
    Raises ValueError if the token is missing/invalid.
    """
    _ensure(con)
    if not token:
        raise ValueError(
            "missing key — pass X-Token or Authorization: Bearer "
            "with an agent key (mint at /agents/) or admin token")
    if admin_token and secrets.compare_digest(token, admin_token):
        return {
            "admin": True, "key_ok": True, "agent": None,
            "boards": [b["chat"] for b in list_boards(con)],
            "message": "admin token",
        }
    name = agent_token_ok(con, token)
    if not name:
        raise ValueError(
            "invalid key — not an agent key or admin token. "
            "Mint a key at /agents/ (Team ··· → Mint key) or see /join/")
    touch_last_seen(con, name)
    boards = []
    for b in list_boards(con):
        if is_member(con, b["id"], name):
            role = next(
                (m["role"] for m in b["members"] if m["agent"] == name),
                "member")
            boards.append({"chat": b["chat"], "role": role})
    agent = next(a for a in list_agents(con) if a["name"] == name)
    mine = hosted_board(con, name)
    host = bool(mine)
    return {
        "admin": host,  # compat: host of any board
        "key_ok": True,
        "agent": name,
        "host": host,
        "hosted_chat": mine["chat"] if mine else None,
        "label": agent["label"],
        "boards": boards,
        "has_key": True,
        "last_seen_at": agent["last_seen_at"],
        "parallel_ok": agent["parallel_ok"],
    }


def join_agent(con, name, chat=None, role="worker", mint=True, label=None):
    """One-shot: ensure roster row, board membership, optional key mint.

    Removes the 'roster hassle' — agents (or Mazin) call this instead of
    add-agent then mint separately.
    """
    _ensure(con)
    chat = chat or DEFAULT_CHAT
    agent = upsert_agent(con, name, label=label)
    board = add_member(con, chat=chat, agent=agent["name"], role=role)
    out = {
        "agent": agent["name"],
        "label": agent["label"],
        "chat": board["chat"],
        "role": role,
        "board_id": board["id"],
    }
    if mint:
        key = mint_agent_key(con, agent["name"])
        out["token"] = key["token"]
        out["hint"] = key["hint"]
        out["message"] = key["message"]
    return out


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


def set_host(con, name, on=True, chat=None):
    """Set (or clear) the host of a board. Each agent hosts at most one.

    Bootstrap-admin endpoint. Host key can invite/mint on that board and
    posts stay attributed to the host agent.
    """
    _ensure(con)
    name = _slug(name)
    chat = _chat_slug(chat or DEFAULT_CHAT)
    if not con.execute("SELECT 1 FROM agents WHERE name=?", (name,)).fetchone():
        raise ValueError(f"unknown agent: {name}")
    board = get_or_create_board(con, chat)
    if on:
        other = con.execute(
            "SELECT chat FROM boards WHERE host_agent=? AND id!=?",
            (name, board["id"])).fetchone()
        if other:
            raise ValueError(
                f"{name} already hosts '{other['chat']}' — each agent "
                "hosts one board")
        con.execute(
            "UPDATE boards SET host_agent=? WHERE id=?", (name, board["id"]))
        _ensure_member(con, board["id"], name, role="admin")
    else:
        if (board.get("host_agent") or "") == name:
            con.execute(
                "UPDATE boards SET host_agent='' WHERE id=?", (board["id"],))
    con.commit()
    _sync_is_admin(con)
    return {
        "agent": name, "host": bool(on), "chat": chat,
        "board": _board_row(con, board["id"]),
    }


def host_agent(con, chat=None):
    """Host of a board (default peers). Prefer board_host()."""
    return board_host(con, chat=chat or DEFAULT_CHAT) or None


def resolve_admin(con, token: str, admin_token: str = "") -> bool:
    """True if token is bootstrap admin OR hosts any board.

    Prefer can_manage_board() for board-scoped actions. Self-mint does not
    need this.
    """
    if not token:
        return False
    if admin_token and secrets.compare_digest(token, admin_token):
        return True
    name = agent_token_ok(con, token)
    return bool(name) and hosted_board(con, name) is not None


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


def mint_for_caller(con, token: str, name: str = "",
                    admin_token: str = "", chat=None) -> dict:
    """Self-mint always; mint-for-other if bootstrap or board host.

    Connected agents remint their own key without asking the host. Hosts
    remint invitees on boards they own. Lost keys (disconnected agents)
    need a board host or bootstrap admin.
    """
    _ensure(con)
    caller = agent_token_ok(con, token)
    is_boot = bool(
        admin_token and token
        and secrets.compare_digest(token, admin_token))
    target = _slug(name) if name else (caller or "")
    if not target:
        raise ValueError("agent name required")
    if is_boot or (caller and caller == target):
        return mint_agent_key(con, target)
    if caller and can_manage_board(
            con, token, admin_token, chat=chat or DEFAULT_CHAT):
        return mint_agent_key(con, target)
    raise PermissionError(
        "forbidden — remint your own key, or ask the board host / admin "
        "to mint for another agent")


def agent_token_ok(con, token: str):
    """True if token matches any agent key."""
    if not token:
        return False
    _ensure(con)
    digest = _hash(token)
    row = con.execute(
        "SELECT name FROM agents WHERE token_hash=?", (digest,)).fetchone()
    return row["name"] if row else None


def list_rules(con, board_id=None, chat=None):
    _ensure(con)
    bid = _resolve_board_id(con, board_id=board_id, chat=chat)
    rows = con.execute(
        "SELECT id, board_id, match, agent, parallel, priority, enabled "
        "FROM task_rules "
        "WHERE board_id=? ORDER BY priority DESC, id", (bid,)).fetchall()
    return [{
        "id": r["id"], "board_id": r["board_id"],
        "match": r["match"], "agent": r["agent"],
        "parallel": bool(r["parallel"]), "priority": r["priority"],
        "enabled": bool(r["enabled"]),
    } for r in rows]


def set_rules(con, rules, board_id=None, chat=None):
    """Replace rules for one board. rules = [{match, agent, parallel?, priority?}]"""
    _ensure(con)
    if not isinstance(rules, list):
        raise ValueError("rules must be a list")
    bid = _resolve_board_id(con, board_id=board_id, chat=chat)
    con.execute("DELETE FROM task_rules WHERE board_id=?", (bid,))
    for i, rule in enumerate(rules):
        match = (rule.get("match") or "").strip()[:120]
        agent = _slug(rule.get("agent") or "")
        if not match or not agent:
            continue
        con.execute(
            "INSERT INTO task_rules(board_id, match, agent, parallel, "
            "priority, enabled) VALUES(?,?,?,?,?,?)",
            (bid, match, agent, 1 if rule.get("parallel") else 0,
             int(rule.get("priority", 10 - i)),
             0 if rule.get("enabled") is False else 1))
    con.commit()
    return list_rules(con, board_id=bid)


def _apply_rule(con, board_id, title, body):
    text = f"{title}\n{body}".lower()
    # Prefer routes declared in member briefs (fluid markdown rules).
    for brief in list_briefs(con, board_id=board_id):
        for route in brief.get("routes") or []:
            match = (route.get("match") or "").lower()
            if match and match in text:
                return brief["agent"], bool(route.get("parallel"))
    # Legacy substring table (kept for API compat / older boards).
    for rule in list_rules(con, board_id=board_id):
        if not rule.get("enabled", True):
            continue
        if rule["match"].lower() in text:
            return rule["agent"], rule["parallel"]
    return "", None


def _write_brief_raw(con, board_id, agent, body):
    agent = _slug(agent)
    body = (body or "")[:MAX_BRIEF_CHARS]
    digest = hashlib.sha256(body.encode()).hexdigest()
    now = time.time()
    con.execute(
        "INSERT INTO agent_briefs(board_id, agent, body, content_hash, updated_at) "
        "VALUES(?,?,?,?,?) "
        "ON CONFLICT(board_id, agent) DO UPDATE SET "
        "body=excluded.body, content_hash=excluded.content_hash, "
        "updated_at=excluded.updated_at",
        (board_id, agent, body, digest, now))
    con.commit()
    return digest


def parse_brief_frontmatter(body: str):
    """Parse optional --- frontmatter. Returns (meta_dict, prose).

    Supported keys (line-oriented, no YAML dependency):
      routes: on-device=serial, deploy=serial, code=parallel
      max_chars: 4000
    """
    body = body or ""
    if not body.startswith("---"):
        return {}, body
    nl = body.find("\n", 3)
    if nl < 0:
        return {}, body
    end = body.find("\n---", nl)
    if end < 0:
        return {}, body
    fm_text = body[nl + 1:end].strip()
    prose = body[end + 4:].lstrip("\n")
    meta = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip().lower()] = val.strip()
    routes = []
    for part in (meta.get("routes") or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            match, _, mode = part.partition("=")
            routes.append({
                "match": match.strip()[:80],
                "parallel": mode.strip().lower() == "parallel",
            })
        else:
            routes.append({"match": part[:80], "parallel": False})
    meta["routes"] = routes
    return meta, prose


def list_briefs(con, board_id=None, chat=None):
    """Member briefs for a board. Non-members omitted. Bodies capped."""
    _ensure(con)
    bid = _resolve_board_id(con, board_id=board_id, chat=chat)
    members = {m["agent"] for m in list_members(con, bid)}
    rows = con.execute(
        "SELECT agent, body, content_hash, updated_at FROM agent_briefs "
        "WHERE board_id=? ORDER BY agent", (bid,)).fetchall()
    out = []
    for r in rows:
        if r["agent"] not in members:
            continue
        body = r["body"] or ""
        truncated = len(body) > MAX_BRIEF_CHARS
        if truncated:
            body = body[:MAX_BRIEF_CHARS] + "\n…[truncated]"
        meta, prose = parse_brief_frontmatter(body)
        out.append({
            "agent": r["agent"],
            "body": body,
            "prose": prose,
            "routes": meta.get("routes") or [],
            "content_hash": r["content_hash"],
            "updated_at": r["updated_at"],
            "chars": len(body),
            "max_chars": MAX_BRIEF_CHARS,
            "truncated": truncated,
        })
    return out


def get_brief(con, agent, board_id=None, chat=None):
    _ensure(con)
    bid = _resolve_board_id(con, board_id=board_id, chat=chat)
    agent = _slug(agent)
    if not is_member(con, bid, agent):
        raise ValueError(f"{agent} is not on this board")
    row = con.execute(
        "SELECT agent, body, content_hash, updated_at FROM agent_briefs "
        "WHERE board_id=? AND agent=?", (bid, agent)).fetchone()
    if not row:
        return {
            "agent": agent, "body": "", "prose": "", "routes": [],
            "content_hash": "", "updated_at": 0, "chars": 0,
            "max_chars": MAX_BRIEF_CHARS, "truncated": False,
        }
    body = row["body"] or ""
    truncated = len(body) > MAX_BRIEF_CHARS
    if truncated:
        body = body[:MAX_BRIEF_CHARS] + "\n…[truncated]"
    meta, prose = parse_brief_frontmatter(body)
    return {
        "agent": agent, "body": body, "prose": prose,
        "routes": meta.get("routes") or [],
        "content_hash": row["content_hash"],
        "updated_at": row["updated_at"],
        "chars": len(body), "max_chars": MAX_BRIEF_CHARS,
        "truncated": truncated,
    }


def set_brief(con, agent, body, board_id=None, chat=None):
    """Upsert one agent's markdown brief. Enforces membership + size cap."""
    _ensure(con)
    bid = _resolve_board_id(con, board_id=board_id, chat=chat)
    agent = _slug(agent)
    if not is_member(con, bid, agent):
        raise ValueError(f"{agent} is not on this board")
    raw = body if isinstance(body, str) else ""
    if len(raw) > MAX_BRIEF_CHARS:
        raw = raw[:MAX_BRIEF_CHARS]
    digest = _write_brief_raw(con, bid, agent, raw)
    return get_brief(con, agent, board_id=bid)


def session_pack(con, board_id=None, chat=None, since_hashes=None):
    """Markdown pack of member briefs for chat/session start.

    Pass since_hashes={agent: hash} to skip unchanged briefs (anti-bloat).
    Combined pack hard-capped at MAX_SESSION_PACK_CHARS.
    """
    _ensure(con)
    bid = _resolve_board_id(con, board_id=board_id, chat=chat)
    board = _board_row(con, bid)
    since = since_hashes if isinstance(since_hashes, dict) else {}
    briefs = list_briefs(con, board_id=bid)
    included, skipped = [], []
    parts = [f"# Session briefs — {board['chat']}\n"]
    used = len(parts[0])
    for i, b in enumerate(briefs):
        if since.get(b["agent"]) and since[b["agent"]] == b["content_hash"]:
            skipped.append(b["agent"])
            continue
        block = f"\n## {b['agent']} ({b['chars']}/{b['max_chars']})\n\n{b['body']}\n"
        if used + len(block) > MAX_SESSION_PACK_CHARS:
            parts.append(
                f"\n…[pack truncated — skipped {b['agent']} and later]\n")
            for rest in briefs[i:]:
                if rest["agent"] not in skipped:
                    skipped.append(rest["agent"])
            break
        parts.append(block)
        included.append({
            "agent": b["agent"], "content_hash": b["content_hash"],
            "chars": b["chars"],
        })
        used += len(block)
    text = "".join(parts)
    return {
        "chat": board["chat"],
        "pack": text,
        "chars": len(text),
        "max_chars": MAX_SESSION_PACK_CHARS,
        "included": included,
        "skipped": skipped,
        "hashes": {b["agent"]: b["content_hash"] for b in briefs},
    }


def list_tasks(con, status=None, assignee=None, limit=100,
               board_id=None, chat=None):
    _ensure(con)
    bid = _resolve_board_id(con, board_id=board_id, chat=chat)
    sql = ("SELECT id, board_id, title, body, status, assignee, parallel,"
           " created_by, created_at, updated_at FROM tasks WHERE board_id=?")
    args = [bid]
    if status:
        sql += " AND status=?"
        args.append(status)
    if assignee:
        sql += " AND assignee=?"
        args.append(_slug(assignee))
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    args.append(max(1, min(int(limit or 100), 200)))
    return [{
        "id": r["id"], "board_id": r["board_id"],
        "title": r["title"], "body": r["body"],
        "status": r["status"], "assignee": r["assignee"],
        "parallel": bool(r["parallel"]), "created_by": r["created_by"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    } for r in con.execute(sql, args)]


def add_task(con, title, body="", assignee="", parallel=None,
             created_by="", auto_route=True, board_id=None, chat=None):
    _ensure(con)
    bid = _resolve_board_id(con, board_id=board_id, chat=chat)
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
        routed, p = _apply_rule(con, bid, title, body)
        if routed:
            assignee = routed
            if p is not None:
                parallel = 1 if p else 0
    if assignee and not is_member(con, bid, assignee):
        raise ValueError(f"{assignee} is not on this board")
    now = time.time()
    cur = con.execute(
        "INSERT INTO tasks(board_id, title, body, status, assignee, parallel,"
        " created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (bid, title, body, "open", assignee, parallel, created_by or "",
         now, now))
    con.commit()
    tid = cur.lastrowid
    return next(t for t in list_tasks(con, board_id=bid, limit=500)
                if t["id"] == tid)


def _busy_blocks(con, agent, parallel, board_id):
    """Can this agent claim a task with this parallel flag right now?"""
    claimed = con.execute(
        "SELECT id, parallel FROM tasks WHERE status='claimed' AND assignee=?"
        " AND board_id=?",
        (agent, board_id)).fetchall()
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
    if not is_member(con, row["board_id"], agent):
        raise ValueError(f"{agent} is not on this board")
    if row["status"] not in ("open", "blocked"):
        raise ValueError(f"task is {row['status']}")
    assignee = row["assignee"] or agent
    if row["assignee"] and row["assignee"] != agent:
        raise ValueError(f"task assigned to {row['assignee']}")
    block = _busy_blocks(con, agent, bool(row["parallel"]), row["board_id"])
    if block:
        raise ValueError(block)
    now = time.time()
    con.execute(
        "UPDATE tasks SET status='claimed', assignee=?, updated_at=? WHERE id=?",
        (assignee, now, task_id))
    con.commit()
    return next(t for t in list_tasks(con, board_id=row["board_id"], limit=500)
                if t["id"] == task_id)


def update_task(con, task_id, status=None, assignee=None, parallel=None,
                title=None, body=None):
    _ensure(con)
    row = con.execute(
        "SELECT id, board_id FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise ValueError("unknown task")
    sets, args = ["updated_at=?"], [time.time()]
    if status is not None:
        if status not in STATUSES:
            raise ValueError("bad status")
        sets.append("status=?")
        args.append(status)
    if assignee is not None:
        a = _slug(assignee) if assignee else ""
        if a and not is_member(con, row["board_id"], a):
            raise ValueError(f"{a} is not on this board")
        sets.append("assignee=?")
        args.append(a)
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
    return next(t for t in list_tasks(con, board_id=row["board_id"], limit=500)
                if t["id"] == task_id)


def reassign_task(con, task_id, to_agent, by="", reopen=True):
    """Move a task to another board member.

    Claimed work reopens so the new agent must claim (avoids silent steal).
    """
    _ensure(con)
    to_agent = _slug(to_agent)
    row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise ValueError("unknown task")
    if not to_agent:
        raise ValueError("to_agent required")
    if not is_member(con, row["board_id"], to_agent):
        raise ValueError(f"{to_agent} is not on this board")
    status = None
    if reopen and row["status"] == "claimed" and row["assignee"] != to_agent:
        status = "open"
    task = update_task(con, task_id, assignee=to_agent, status=status)
    return {
        "ok": True,
        "task": task,
        "from": row["assignee"] or "",
        "to": to_agent,
        "by": _slug(by) if by else "",
        "reopened": status == "open",
    }


def pick_tick_task(con, agent, chat=None, board_id=None):
    """Choose the one task this agent should work on this tick.

    Priority: already-claimed by agent → oldest open/blocked assigned to agent.
    Returns (task_or_None, action) where action is continue|claim|idle.
    """
    _ensure(con)
    agent = _slug(agent)
    bid = _resolve_board_id(con, board_id=board_id, chat=chat)
    claimed = [
        t for t in list_tasks(con, status="claimed", board_id=bid, limit=200)
        if t["assignee"] == agent
    ]
    if claimed:
        claimed.sort(key=lambda t: t["updated_at"] or t["created_at"])
        return claimed[0], "continue"
    mine = []
    for st in ("open", "blocked"):
        for t in list_tasks(con, status=st, board_id=bid, limit=200):
            if t["assignee"] == agent:
                mine.append(t)
    if not mine:
        return None, "idle"
    mine.sort(key=lambda t: t["created_at"])
    return mine[0], "claim"


def board_tick(con, agent, chat=None, board_id=None, claim=False):
    """One tick of board work for an agent (cron/skill friendly).

    Runs readiness, surfaces inbox titles, and either continues a claimed
    task, offers the next assigned open task (optionally claims it), or
    reports idle.
    """
    _ensure(con)
    from . import checks, store
    agent = _slug(agent)
    chat = chat or DEFAULT_CHAT
    ready = checks.agent_ready(con, agent)
    inbox = store.list_peer_messages(con, to_agent=agent, limit=8)
    inbox_titles = [m.get("title") for m in inbox[:5]]
    if ready.get("blocked"):
        return {
            "agent": agent,
            "chat": chat,
            "action": "block",
            "ready": ready,
            "task": None,
            "inbox_count": len(inbox),
            "inbox_titles": inbox_titles,
            "hint": "gates blocked — reply peers role:block; do not claim",
        }
    task, action = pick_tick_task(
        con, agent, chat=chat, board_id=board_id)
    if action == "claim" and claim and task:
        task = claim_task(con, task["id"], agent)
        action = "claimed"
    hints = {
        "continue": "finish claimed task, then update_task status=done + "
                    "message_peer role:done",
        "claim": "claim_task then do the body; one job this tick",
        "claimed": "task claimed — do the body this tick",
        "idle": "no assigned open tasks — check inbox / wait for handoff",
    }
    return {
        "agent": agent,
        "chat": chat,
        "action": action,
        "ready": ready,
        "task": task,
        "inbox_count": len(inbox),
        "inbox_titles": inbox_titles,
        "hint": hints.get(action, ""),
    }
