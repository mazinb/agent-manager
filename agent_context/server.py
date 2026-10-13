"""HTTP API + static UI + MCP endpoint. All JSON, auth via X-Token or Bearer:
  GET  /api/stats
  GET  /api/search?q=
  POST /api/ask           {q, use_llm}
  GET  /api/entity?name=
  GET  /api/entities
  GET  /api/projects
  GET  /api/context?project=
  POST /api/refresh
  POST /api/note          {project, title, body}   (agents share context)
  POST /mcp               stateless MCP (JSON-RPC); GET /mcp for discovery
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import __version__, llm, mcp, pipeline, query, store


class Brain:
    def __init__(self, config):
        self.config = config
        self.lock = threading.Lock()
        self._local = threading.local()
        self.refreshing = False

    @property
    def con(self):
        if getattr(self._local, "con", None) is None:
            self._local.con = store.connect(self.config["db_path"])
        return self._local.con

    def refresh(self):
        with self.lock:
            self.refreshing = True
        try:
            return pipeline.refresh(self.con, self.config)
        finally:
            with self.lock:
                self.refreshing = False


def load_config(path):
    import json as _json
    with open(path) as f:
        return _json.load(f)


def make_handler(brain, token, static_dir):
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
            if not token:
                return True
            if self.headers.get("X-Token") == token:
                return True
            return self.headers.get("Authorization", "") == f"Bearer {token}"

        def _static(self, name):
            path = os.path.join(static_dir, name)
            if not os.path.isfile(path):
                return self._json(404, {"error": "not found"})
            ctype = "text/html; charset=utf-8" if name.endswith(".html") \
                else "application/javascript" if name.endswith(".js") \
                else "text/css"
            body = open(path, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/":
                return self._static("index.html")
            if u.path == "/mcp":
                return self._json(200, {
                    "server": "agent-manager", "version": __version__,
                    "transport": "streamable-http (POST JSON-RPC to /mcp)",
                    "tools": [t["name"] for t in mcp.TOOLS]})
            if u.path == "/index.html":
                return self._static("index.html")
            if not self._authed():
                return self._json(401, {"error": "unauthorized"})
            if u.path == "/api/stats":
                return self._json(200, query.stats(brain.con))
            if u.path == "/api/search":
                return self._json(200, {"results": query.search(
                    brain.con, (q.get("q") or [""])[0])})
            if u.path == "/api/entity":
                card = query.entity_card(brain.con, (q.get("name") or [""])[0])
                return self._json(200, card or {"error": "unknown"})
            if u.path == "/api/entities":
                rows = brain.con.execute(
                    "SELECT name, type, blurb FROM entities ORDER BY type, name"
                ).fetchall()
                return self._json(200, {"entities": [dict(r) for r in rows]})
            if u.path == "/api/projects":
                return self._json(200, {"projects": query.projects(brain.con)})
            if u.path == "/api/context":
                project = (q.get("project") or [""])[0]
                if project not in query.projects(brain.con):
                    return self._json(404, {"error": "unknown project"})
                pack = query.context_pack(
                    brain.con, project,
                    int((q.get("max_chars") or ["6000"])[0]))
                return self._json(200, {"project": project, "pack": pack})
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            path = urlparse(self.path).path
            if path not in ("/api/ask", "/api/refresh", "/api/note", "/mcp"):
                return self._json(404, {"error": "not found"})
            if not self._authed():
                return self._json(401, {"error": "unauthorized"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._json(400, {"error": "bad json"})
            if path == "/mcp":
                resp = mcp.handle(brain, payload)
                if resp is None:
                    return self._json(202, {})
                return self._json(200, resp)
            if path == "/api/note":
                try:
                    return self._json(200, mcp.TOOL_FUNCS["note"](brain, payload))
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
            if path == "/api/refresh":
                result = brain.refresh()
                return self._json(200, result)
            qs = (payload.get("q") or "").strip()
            if not qs:
                return self._json(400, {"error": "empty q"})
            chunks = query.search(brain.con, qs)
            answer = None
            if payload.get("use_llm", True):
                lc = brain.config.get("llm") or {}
                if lc.get("base_url"):
                    answer = llm.ask(lc["base_url"], lc.get("model", ""),
                                     qs, chunks)
            return self._json(200, {"answer": answer, "results": chunks})

    return Handler


def serve(config, host="127.0.0.1"):
    brain = Brain(config)
    token = config.get("token", "")
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    handler = make_handler(brain, token, static_dir)
    port = int(config.get("port", 8076))
    print(f"agent-context on :{port}", flush=True)
    ThreadingHTTPServer((host, port), handler).serve_forever()
