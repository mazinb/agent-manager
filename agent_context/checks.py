"""Per-agent readiness gates + periodic poll actions.

Configurable policy (JSON) per roster agent. Agents call `agent_ready`
before claiming work; a timer/skill can call `agent_poll` on an interval.
Results are stored for the human Team view.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


BRAIN_URL = os.environ.get("BRAIN_URL", "http://127.0.0.1:8888")
BRAIN_MODEL = os.environ.get("BRAIN_MODEL", "GLM-5.3-Flash-EXL3")
THERMAL_STATE = os.path.expanduser(
    os.environ.get("THERMAL_STATE", "~/brain/thermal.state"))
AM_URL = os.environ.get("AGENT_MANAGER_URL", "http://127.0.0.1:8075")

# Gates must pass before work when listed under policy.gates.
# Poll actions run on policy.poll.every_min (skill/timer driven).
KNOWN_GATES = ("brain", "thermal", "agent_manager")
KNOWN_POLL = ("peer_inbox", "board_tick")

DEFAULT_POLICIES = {
    "hermes": {
        "gates": ["brain", "thermal"],
        "poll": {"every_min": 5, "actions": ["peer_inbox", "board_tick"]},
        "on_fail": "block",
    },
    "cursor": {
        "gates": [],
        "poll": {"every_min": 10, "actions": ["peer_inbox"]},
        "on_fail": "warn",
    },
    "grok-bot": {
        "gates": [],
        "poll": {"every_min": 15, "actions": ["peer_inbox"]},
        "on_fail": "warn",
    },
    "designer": {
        "gates": [],
        "poll": {"every_min": 15, "actions": ["peer_inbox"]},
        "on_fail": "warn",
    },
}


def _ensure(con):
    from . import roster
    roster.seed_if_needed(con)
    con.execute(
        "CREATE TABLE IF NOT EXISTS agent_policies ("
        "agent TEXT PRIMARY KEY,"
        "policy TEXT NOT NULL DEFAULT '{}',"
        "updated_at REAL NOT NULL DEFAULT 0)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS agent_check_state ("
        "agent TEXT PRIMARY KEY,"
        "ready INTEGER NOT NULL DEFAULT 0,"
        "last_results TEXT NOT NULL DEFAULT '{}',"
        "last_run_at REAL NOT NULL DEFAULT 0,"
        "last_poll_at REAL NOT NULL DEFAULT 0)"
    )
    con.commit()
    # Seed defaults for known agents missing a row.
    for name, pol in DEFAULT_POLICIES.items():
        row = con.execute(
            "SELECT 1 FROM agent_policies WHERE agent=?", (name,)).fetchone()
        if not row:
            con.execute(
                "INSERT INTO agent_policies(agent, policy, updated_at) "
                "VALUES(?,?,?)",
                (name, json.dumps(pol), time.time()))
    con.commit()


def _slug(name: str) -> str:
    from . import roster
    return roster._slug(name)


def normalize_policy(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("policy must be an object")
    gates = []
    for g in raw.get("gates") or []:
        g = str(g).strip()
        if g and g not in gates:
            if g not in KNOWN_GATES:
                raise ValueError(f"unknown gate: {g} (known: {KNOWN_GATES})")
            gates.append(g)
    poll_in = raw.get("poll") if isinstance(raw.get("poll"), dict) else {}
    try:
        every = max(0, int(poll_in.get("every_min") or 0))
    except (TypeError, ValueError):
        every = 0
    actions = []
    for a in poll_in.get("actions") or []:
        a = str(a).strip()
        if a and a not in actions:
            if a not in KNOWN_POLL:
                raise ValueError(f"unknown poll action: {a}")
            actions.append(a)
    on_fail = (raw.get("on_fail") or "block").strip().lower()
    if on_fail not in ("block", "warn"):
        on_fail = "block"
    return {
        "gates": gates,
        "poll": {"every_min": every, "actions": actions},
        "on_fail": on_fail,
    }


def get_policy(con, agent: str) -> dict:
    _ensure(con)
    agent = _slug(agent)
    row = con.execute(
        "SELECT policy, updated_at FROM agent_policies WHERE agent=?",
        (agent,)).fetchone()
    if not row:
        pol = normalize_policy(DEFAULT_POLICIES.get(agent, {
            "gates": [], "poll": {"every_min": 0, "actions": []},
            "on_fail": "warn",
        }))
        return {"agent": agent, "policy": pol, "updated_at": 0}
    try:
        raw = json.loads(row["policy"] or "{}")
    except (ValueError, TypeError):
        raw = {}
    return {
        "agent": agent,
        "policy": normalize_policy(raw),
        "updated_at": row["updated_at"],
    }


def set_policy(con, agent: str, policy) -> dict:
    _ensure(con)
    agent = _slug(agent)
    from . import roster
    if not con.execute("SELECT 1 FROM agents WHERE name=?", (agent,)).fetchone():
        roster.upsert_agent(con, agent)
    pol = normalize_policy(policy)
    now = time.time()
    con.execute(
        "INSERT INTO agent_policies(agent, policy, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(agent) DO UPDATE SET policy=excluded.policy, "
        "updated_at=excluded.updated_at",
        (agent, json.dumps(pol), now))
    con.commit()
    return get_policy(con, agent)


def list_policies(con) -> list:
    _ensure(con)
    from . import roster
    agents = [a["name"] for a in roster.list_agents(con)]
    return [get_policy(con, a) for a in agents]


def _http_code(url: str, timeout=5) -> int:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status)
    except Exception:
        return 0


def _gate_brain() -> dict:
    code = _http_code(f"{BRAIN_URL.rstrip('/')}/v1/models", timeout=5)
    if code != 200:
        return {"ok": False, "detail": f"models HTTP {code or 'down'}"}
    body = json.dumps({
        "model": BRAIN_MODEL,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 4,
    }).encode()
    try:
        req = urllib.request.Request(
            f"{BRAIN_URL.rstrip('/')}/v1/chat/completions",
            data=body, method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode() or "{}")
        ok = bool(raw.get("choices"))
        return {"ok": ok, "detail": "completion ok" if ok else "no choices"}
    except Exception as e:
        return {"ok": False, "detail": f"completion fail: {e.__class__.__name__}"}


def _gate_thermal() -> dict:
    path = THERMAL_STATE
    if not os.path.isfile(path):
        return {"ok": True, "detail": "no thermal.state (assume cool)"}
    hot = False
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("hot_hold="):
                    hot = line.split("=", 1)[1].strip() == "1"
                    break
    except OSError as e:
        return {"ok": False, "detail": f"thermal read: {e}"}
    return {
        "ok": not hot,
        "detail": "hot_hold" if hot else "cool",
    }


def _gate_agent_manager() -> dict:
    code = _http_code(f"{AM_URL.rstrip('/')}/", timeout=5)
    # 200 landing or 401 on API both mean process is up; / returns 200.
    ok = code in (200, 401)
    return {"ok": ok, "detail": f"HTTP {code or 'down'}"}


GATE_FUNCS = {
    "brain": _gate_brain,
    "thermal": _gate_thermal,
    "agent_manager": _gate_agent_manager,
}


def _poll_peer_inbox(con, agent: str) -> dict:
    from . import store
    msgs = store.list_peer_messages(con, to_agent=agent, limit=50)
    return {
        "ok": True,
        "detail": f"{len(msgs)} message(s)",
        "count": len(msgs),
        "titles": [m.get("title") for m in msgs[:5]],
    }


def _poll_board_tick(con, agent: str) -> dict:
    """Surface the next board task without auto-claiming (skill decides)."""
    from . import roster
    tick = roster.board_tick(con, agent, claim=False)
    return {
        "ok": True,
        "detail": tick.get("action") or "idle",
        "action": tick.get("action"),
        "task_id": (tick.get("task") or {}).get("id") if tick.get("task") else None,
        "title": (tick.get("task") or {}).get("title") if tick.get("task") else None,
        "tick": tick,
    }


POLL_FUNCS = {
    "peer_inbox": _poll_peer_inbox,
    "board_tick": _poll_board_tick,
}


def _save_state(con, agent, ready, results, poll=False):
    now = time.time()
    row = con.execute(
        "SELECT last_poll_at FROM agent_check_state WHERE agent=?",
        (agent,)).fetchone()
    last_poll = row["last_poll_at"] if row else 0
    if poll:
        last_poll = now
    con.execute(
        "INSERT INTO agent_check_state(agent, ready, last_results, "
        "last_run_at, last_poll_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(agent) DO UPDATE SET ready=excluded.ready, "
        "last_results=excluded.last_results, last_run_at=excluded.last_run_at, "
        "last_poll_at=CASE WHEN ? THEN excluded.last_poll_at "
        "ELSE agent_check_state.last_poll_at END",
        (agent, 1 if ready else 0, json.dumps(results), now, last_poll,
         1 if poll else 0))
    con.commit()


def get_state(con, agent: str) -> dict:
    _ensure(con)
    agent = _slug(agent)
    row = con.execute(
        "SELECT ready, last_results, last_run_at, last_poll_at "
        "FROM agent_check_state WHERE agent=?", (agent,)).fetchone()
    if not row:
        return {
            "agent": agent, "ready": None, "results": {},
            "last_run_at": 0, "last_poll_at": 0,
        }
    try:
        results = json.loads(row["last_results"] or "{}")
    except (ValueError, TypeError):
        results = {}
    return {
        "agent": agent,
        "ready": bool(row["ready"]),
        "results": results,
        "last_run_at": row["last_run_at"],
        "last_poll_at": row["last_poll_at"],
    }


def list_states(con) -> list:
    _ensure(con)
    from . import roster
    return [get_state(con, a["name"]) for a in roster.list_agents(con)]


def agent_ready(con, agent: str, run_gates=True) -> dict:
    """Evaluate gates for an agent. Returns ready bool + per-gate results."""
    _ensure(con)
    agent = _slug(agent)
    pol = get_policy(con, agent)["policy"]
    results = {}
    failed = []
    for g in pol.get("gates") or []:
        fn = GATE_FUNCS.get(g)
        if not fn:
            results[g] = {"ok": False, "detail": "unknown gate"}
            failed.append(g)
            continue
        if run_gates:
            out = fn()
        else:
            out = {"ok": True, "detail": "skipped"}
        results[g] = out
        if not out.get("ok"):
            failed.append(g)
    ready = not failed
    on_fail = pol.get("on_fail") or "block"
    # warn: still report failed but ready=True for soft agents
    if on_fail == "warn" and failed:
        ready_flag = True
    else:
        ready_flag = ready
    _save_state(con, agent, ready_flag if on_fail == "warn" else ready, {
        "gates": results,
        "failed": failed,
        "on_fail": on_fail,
    })
    return {
        "agent": agent,
        "ready": ready if on_fail == "block" else True,
        "blocked": bool(failed) and on_fail == "block",
        "failed": failed,
        "results": results,
        "policy": pol,
        "checked_at": time.time(),
    }


def agent_poll(con, agent: str) -> dict:
    """Run configured poll actions (e.g. peer_inbox), then refresh gates."""
    _ensure(con)
    agent = _slug(agent)
    pol = get_policy(con, agent)["policy"]
    poll = pol.get("poll") or {}
    actions = poll.get("actions") or []
    out = {}
    for a in actions:
        fn = POLL_FUNCS.get(a)
        if not fn:
            out[a] = {"ok": False, "detail": "unknown action"}
            continue
        out[a] = fn(con, agent)
    ready = agent_ready(con, agent)
    # Stamp last_poll_at while keeping gate results from agent_ready.
    st = get_state(con, agent)
    _save_state(
        con, agent,
        ready["ready"] and not ready.get("blocked"),
        st.get("results") or {},
        poll=True,
    )
    return {
        "agent": agent,
        "every_min": poll.get("every_min") or 0,
        "actions": out,
        "ready": ready,
        "polled_at": time.time(),
    }
