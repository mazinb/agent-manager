#!/usr/bin/env python3
"""Agent manager — web UI to chat with per-project Hermes helper agents.

Serves static/index.html and a small JSON API. Auth via X-Token header
matching AGENT_MANAGER_TOKEN from .env. Chat executes
`hermes -p <agent> chat -q <message>` per request.
"""
import json
import os
import re
import shlex
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
DATA = os.path.join(ROOT, "data")
PROFILES = os.path.expanduser("~/.hermes/profiles")
HERMES = os.path.expanduser("~/.local/bin/hermes")
CHAT_TIMEOUT = int(os.environ.get("CHAT_TIMEOUT", "420"))

# agent-context (shared brain) reverse proxy target
BRAIN_CONFIG_PATH = os.path.expanduser("~/.config/agent-context/config.json")
BRAIN_PORT = int(os.environ.get("AGENT_CONTEXT_PORT", "8076"))
SPACE_PORT = int(os.environ.get("AGENT_CONTEXT_PUBLIC_PORT", "8077"))  # free public shared space (no auth)


def brain_token():
    try:
        import json as _json
        with open(BRAIN_CONFIG_PATH) as f:
            return _json.load(f).get("token", "")
    except Exception:
        return ""

META_RE = re.compile(
    r"^(Session|Title|Duration|Messages|Cost|Model):.*$", re.MULTILINE)


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


ENV = load_env()
TOKEN = ENV.get("AGENT_MANAGER_TOKEN", "")


def list_agents():
    agents = []
    if os.path.isdir(PROFILES):
        for name in sorted(os.listdir(PROFILES)):
            soul = os.path.join(PROFILES, name, "SOUL.md")
            if not os.path.isfile(soul):
                continue
            desc = ""
            with open(soul) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        desc = line
                        break
            agents.append({"name": name, "blurb": desc})
    return agents


def valid_agent(name):
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name or "")) and \
        os.path.isfile(os.path.join(PROFILES, name, "SOUL.md"))


def chat(agent, message):
    cmd = [HERMES, "-p", agent, "chat", "-Q", "-q", message]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=CHAT_TIMEOUT, env={**os.environ})
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    lines = out.splitlines()
    # -Q prints just the reply; drop a trailing "session_id: ..." line.
    while lines and (META_RE.match(lines[-1]) or not lines[-1].strip()):
        lines.pop()
    reply = "\n".join(lines).strip() or err or "(empty reply)"
    return reply, proc.returncode


def append_history(agent, role, text):
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, f"history-{agent}.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps({"ts": time.time(), "role": role, "text": text}) + "\n")


def read_history(agent, limit=60):
    path = os.path.join(DATA, f"history-{agent}.jsonl")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        rows = [json.loads(l) for l in f if l.strip()]
    return rows[-limit:]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        return TOKEN and self.headers.get("X-Token") == TOKEN

    def _proxy_pass(self, port, rest, extra_token=None):
        """Forward the current request to a local service on `port`."""
        import urllib.request
        import urllib.error
        url = f"http://127.0.0.1:{port}{rest}"
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(url, data=body, method=self.command)
        for h in ("Content-Type",):
            if self.headers.get(h):
                req.add_header(h, self.headers[h])
        if extra_token:
            req.add_header("X-Token", extra_token)
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = resp.read()
                ctype = resp.headers.get("Content-Type", "application/json")
                code = resp.status
        except urllib.error.HTTPError as e:
            data = e.read()
            ctype = e.headers.get("Content-Type", "application/json")
            code = e.code
        except Exception:
            return self._json(502, {"error": "upstream unreachable"})
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _proxy_brain(self):
        """Forward /context/* to the local agent-context server, swapping auth.
        Client must present the agent-manager token; the brain receives its own.
        """
        if self.path.split("?")[0] == "/context/":
            shell = True  # static shell only — no data without token
        else:
            shell = False
        if not shell and not self._authed():
            return self._json(401, {"error": "unauthorized"})
        rest = self.path[len("/context"):] or "/"
        self._proxy_pass(BRAIN_PORT, rest, extra_token=brain_token())

    def do_GET(self):
        if self.path == "/context":
            self.send_response(301)
            self.send_header("Location", "/context/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/context/"):
            return self._proxy_brain()
        if self.path == "/space":
            self.send_response(301)
            self.send_header("Location", "/space/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/space/"):
            # free public shared space — no auth by design
            return self._proxy_pass(SPACE_PORT, self.path[len("/space"):] or "/")
        if self.path in ("/", "/index.html"):
            return self._static("index.html")
        if self.path.startswith("/api/agents"):
            if not self._authed():
                return self._json(401, {"error": "unauthorized"})
            return self._json(200, {"agents": list_agents()})
        m = re.fullmatch(r"/api/history\?agent=([\w-]+)", self.path)
        if m:
            if not self._authed():
                return self._json(401, {"error": "unauthorized"})
            if not valid_agent(m.group(1)):
                return self._json(400, {"error": "bad agent"})
            return self._json(200, {"history": read_history(m.group(1))})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.startswith("/context/"):
            return self._proxy_brain()
        if self.path.startswith("/space/"):
            # free public shared space — no auth by design
            return self._proxy_pass(SPACE_PORT, self.path[len("/space"):] or "/")
        if self.path != "/api/chat":
            return self._json(404, {"error": "not found"})
        if not self._authed():
            return self._json(401, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad json"})
        agent = payload.get("agent", "")
        message = (payload.get("message") or "").strip()
        if not valid_agent(agent):
            return self._json(400, {"error": "unknown agent"})
        if not message:
            return self._json(400, {"error": "empty message"})
        append_history(agent, "user", message)
        try:
            reply, rc = chat(agent, message)
        except subprocess.TimeoutExpired:
            reply, rc = f"(timed out after {CHAT_TIMEOUT}s)", 124
        except Exception as e:
            reply, rc = f"(error: {e})", 1
        append_history(agent, "assistant", reply)
        return self._json(200, {"reply": reply, "rc": rc})

    def _static(self, name):
        path = os.path.join(STATIC, name)
        if not os.path.isfile(path):
            return self._json(404, {"error": "not found"})
        body = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.environ.get("AGENT_MANAGER_PORT", "8075"))
    print(f"agent-manager on :{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
