#!/usr/bin/env python3
"""Agent manager — shared brain dashboard + MCP.

One process on :8075:
  /                 Public landing
  /setup/           Token onboarding
  /connect/         One-click MCP connect docs
  /brain/           Shared brain UI
  /api/*            JSON API (token)
  /mcp              Streamable HTTP MCP (token on POST)

Auth: AGENT_MANAGER_TOKEN (.env) and/or hashed tokens in data/tokens.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from agent_context import llm, mcp, query, store  # noqa: E402
from agent_context.server import Brain  # noqa: E402

STATIC = os.path.join(ROOT, "static")
BRAIN_STATIC = os.path.join(ROOT, "agent_context", "static")
DATA = os.path.join(ROOT, "data")
TOKENS_PATH = os.path.join(DATA, "tokens.json")
CONFIG_PATH = os.environ.get(
    "AGENT_MANAGER_CONFIG",
    os.path.expanduser("~/.config/agent-manager/config.json"),
)
LEGACY_CONFIG = os.path.expanduser("~/.config/agent-context/config.json")
_TOKEN_LOCK = threading.Lock()


def load_env():
    env = {}
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def load_brain_config():
    path = CONFIG_PATH if os.path.isfile(CONFIG_PATH) else LEGACY_CONFIG
    if not os.path.isfile(path):
        return {
            "db_path": os.path.expanduser(
                "~/.local/share/agent-manager/brain.db"),
            "sources": [],
            "llm": {},
        }
    with open(path) as f:
        cfg = json.load(f)
    cfg["db_path"] = os.path.expanduser(cfg.get(
        "db_path", "~/.local/share/agent-manager/brain.db"))
    return cfg


ENV = load_env()
ADMIN_TOKEN = ENV.get("AGENT_MANAGER_TOKEN", "") or os.environ.get(
    "AGENT_MANAGER_TOKEN", "")


def _flag(name: str, default: str = "") -> bool:
    raw = (ENV.get(name) or os.environ.get(name) or default).strip().lower()
    return raw in ("1", "true", "yes", "on")


ALLOW_PUBLIC_SIGNUP = _flag("ALLOW_PUBLIC_SIGNUP")
SETUP_INVITE_CODE = (
    ENV.get("SETUP_INVITE_CODE") or os.environ.get("SETUP_INVITE_CODE") or ""
).strip()
BRAIN_CFG = load_brain_config()
BRAIN = Brain(BRAIN_CFG)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_tokens():
    if not os.path.isfile(TOKENS_PATH):
        return []
    try:
        with open(TOKENS_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_tokens(rows):
    os.makedirs(DATA, exist_ok=True)
    tmp = TOKENS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rows, f, indent=2)
        f.write("\n")
    os.replace(tmp, TOKENS_PATH)


def configured() -> bool:
    return bool(ADMIN_TOKEN) or bool(load_tokens())


def setup_status():
    return {
        "bootstrap": not configured(),
        "signup_open": bool(ALLOW_PUBLIC_SIGNUP) and configured(),
        "invite_required": bool(SETUP_INVITE_CODE) and ALLOW_PUBLIC_SIGNUP,
        "auth": "token",
        "oauth": {"github": False, "google": False},
    }


def create_token(label: str, role: str = "user"):
    raw = secrets.token_urlsafe(24)
    row = {
        "id": secrets.token_hex(8),
        "hash": hash_token(raw),
        "label": (label or role)[:64],
        "role": role,
        "created": time.time(),
    }
    with _TOKEN_LOCK:
        rows = load_tokens()
        rows.append(row)
        save_tokens(rows)
    return raw, row


def write_env_token(token: str):
    path = os.path.join(ROOT, ".env")
    lines = []
    if os.path.isfile(path):
        lines = open(path).read().splitlines()
    out, seen = [], False
    for line in lines:
        if line.startswith("AGENT_MANAGER_TOKEN="):
            out.append(f"AGENT_MANAGER_TOKEN={token}")
            seen = True
        else:
            out.append(line)
    if not seen:
        out.append(f"AGENT_MANAGER_TOKEN={token}")
    with open(path, "w") as f:
        f.write("\n".join(out).rstrip() + "\n")


def presented_token(handler) -> str:
    tok = handler.headers.get("X-Token", "") or ""
    if tok:
        return tok.strip()
    auth = handler.headers.get("Authorization", "") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def token_ok(token: str) -> bool:
    if not token:
        return False
    if ADMIN_TOKEN and secrets.compare_digest(token, ADMIN_TOKEN):
        return True
    digest = hash_token(token)
    for row in load_tokens():
        if secrets.compare_digest(row.get("hash", ""), digest):
            return True
    return False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        return token_ok(presented_token(self))

    def _file(self, path, ctype):
        if not os.path.isfile(path):
            return self._json(404, {"error": "not found"})
        body = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        q = parse_qs(u.query)

        if path == "/context" or path.startswith("/context/"):
            rest = path[len("/context"):] or "/"
            self.send_response(301)
            self.send_header("Location", "/brain" + (
                rest if path.startswith("/context/") else "/"))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path in ("/agents", "/agents/") or path.startswith("/agents/"):
            self.send_response(301)
            self.send_header("Location", "/brain/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path in ("/space", "/space/") or path.startswith("/space/"):
            return self._json(410, {"error": "gone"})

        if path == "/static/app.css":
            return self._file(os.path.join(STATIC, "app.css"), "text/css")
        if path in ("/", "/index.html", "/home"):
            return self._file(os.path.join(STATIC, "home.html"),
                              "text/html; charset=utf-8")
        if path in ("/setup", "/setup/"):
            return self._file(os.path.join(STATIC, "setup.html"),
                              "text/html; charset=utf-8")
        if path in ("/connect", "/connect/"):
            return self._file(os.path.join(STATIC, "connect.html"),
                              "text/html; charset=utf-8")
        if path in ("/brain", "/brain/"):
            return self._file(os.path.join(BRAIN_STATIC, "index.html"),
                              "text/html; charset=utf-8")

        if path == "/api/setup/status":
            return self._json(200, setup_status())
        if path == "/mcp":
            return self._json(200, {
                "server": "agent-manager",
                "version": "0.3.3",
                "transport": "streamable-http (POST JSON-RPC to /mcp)",
                "tools": [t["name"] for t in mcp.TOOLS],
                "auth": "X-Token or Authorization: Bearer",
            })

        if not self._authed():
            return self._json(401, {"error": "unauthorized"})

        if path == "/api/stats":
            return self._json(200, query.stats(BRAIN.con))
        if path == "/api/search":
            return self._json(200, {"results": query.search(
                BRAIN.con, (q.get("q") or [""])[0])})
        if path == "/api/entity":
            card = query.entity_card(BRAIN.con, (q.get("name") or [""])[0])
            return self._json(200, card or {"error": "unknown"})
        if path == "/api/entities":
            rows = BRAIN.con.execute(
                "SELECT name, type, blurb FROM entities ORDER BY type, name"
            ).fetchall()
            return self._json(200, {"entities": [dict(r) for r in rows]})
        if path == "/api/projects":
            return self._json(200, {"projects": query.projects(BRAIN.con)})
        if path == "/api/context":
            project = (q.get("project") or [""])[0]
            if project not in query.projects(BRAIN.con):
                return self._json(404, {"error": "unknown project"})
            pack = query.context_pack(
                BRAIN.con, project,
                int((q.get("max_chars") or ["6000"])[0]))
            return self._json(200, {"project": project, "pack": pack})

        return self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path

        if path.startswith("/space"):
            return self._json(410, {"error": "gone"})

        if path == "/api/setup/bootstrap":
            try:
                payload = self._read_json()
            except Exception:
                return self._json(400, {"error": "bad json"})
            if configured():
                return self._json(409, {
                    "error": "already_configured",
                    "message": "This brain already has a token.",
                })
            raw, row = create_token(payload.get("label") or "owner",
                                    role="owner")
            global ADMIN_TOKEN
            if not ADMIN_TOKEN:
                try:
                    write_env_token(raw)
                    ADMIN_TOKEN = raw
                except Exception:
                    pass
            return self._json(201, {
                "token": raw,
                "id": row["id"],
                "label": row["label"],
                "message": "Save this token now — it will not be shown again.",
            })

        if path == "/api/setup/signup":
            try:
                payload = self._read_json()
            except Exception:
                return self._json(400, {"error": "bad json"})
            if not configured():
                return self._json(400, {"error": "bootstrap_required"})
            if not ALLOW_PUBLIC_SIGNUP:
                return self._json(403, {"error": "signup_closed"})
            if SETUP_INVITE_CODE:
                if (payload.get("invite") or "").strip() != SETUP_INVITE_CODE:
                    return self._json(403, {"error": "invalid_invite"})
            raw, row = create_token(payload.get("label") or "user", role="user")
            return self._json(201, {
                "token": raw,
                "id": row["id"],
                "label": row["label"],
                "message": "Save this token now — it will not be shown again.",
            })

        if path == "/api/auth/verify":
            try:
                payload = self._read_json()
            except Exception:
                return self._json(400, {"error": "bad json"})
            tok = (payload.get("token") or "").strip()
            if token_ok(tok):
                return self._json(200, {"ok": True})
            return self._json(401, {"ok": False, "error": "unauthorized"})

        if path not in ("/api/ask", "/api/refresh", "/api/note", "/mcp"):
            return self._json(404, {"error": "not found"})
        if not self._authed():
            return self._json(401, {"error": "unauthorized"})

        try:
            payload = self._read_json()
        except Exception:
            return self._json(400, {"error": "bad json"})

        if path == "/mcp":
            resp = mcp.handle(BRAIN, payload)
            if resp is None:
                return self._json(202, {})
            return self._json(200, resp)

        if path == "/api/note":
            try:
                return self._json(200, mcp.TOOL_FUNCS["note"](BRAIN, payload))
            except ValueError as e:
                return self._json(400, {"error": str(e)})

        if path == "/api/refresh":
            return self._json(200, BRAIN.refresh())

        qs = (payload.get("q") or "").strip()
        if not qs:
            return self._json(400, {"error": "empty q"})
        chunks = query.search(BRAIN.con, qs)
        answer = None
        if payload.get("use_llm", True):
            lc = BRAIN.config.get("llm") or {}
            if lc.get("base_url"):
                answer = llm.ask(lc["base_url"], lc.get("model", ""),
                                 qs, chunks)
        return self._json(200, {"answer": answer, "results": chunks})


if __name__ == "__main__":
    store.connect(BRAIN_CFG["db_path"]).close()
    port = int(os.environ.get("AGENT_MANAGER_PORT", "8075"))
    print(f"agent-manager on :{port} (setup + brain + mcp)", flush=True)
    print(f"  bootstrap={not configured()} signup_open={ALLOW_PUBLIC_SIGNUP}",
          flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
