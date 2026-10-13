"""Minimal MCP (Model Context Protocol) server — no SDK, no dependencies.

Two transports:
  stdio   `agent-context mcp` (newline-delimited JSON-RPC on stdin/stdout)
  http    POST /mcp on the main server (stateless JSON-RPC)

Tools: search, ask, entity, context_pack, projects, stats, note.
"""
import json
import re
import sys

from . import __version__

PROTOCOL_VERSION = "2024-11-05"


def _search(brain, args):
    from . import query
    return {"results": query.search(
        brain.con, args.get("q", ""), int(args.get("limit", 12)))}


def _ask(brain, args):
    from . import llm, query
    q = (args.get("q") or "").strip()
    if not q:
        raise ValueError("q is required")
    chunks = query.search(brain.con, q)
    answer = None
    if args.get("use_llm", True):
        lc = brain.config.get("llm") or {}
        if lc.get("base_url"):
            answer = llm.ask(lc["base_url"], lc.get("model", ""), q, chunks)
    return {"answer": answer, "results": chunks}


def _entity(brain, args):
    from . import query
    return query.entity_card(brain.con, args.get("name", "")) or {"error": "unknown entity"}


def _context_pack(brain, args):
    from . import query
    project = args.get("project", "")
    if project not in query.projects(brain.con):
        raise ValueError(f"unknown project: {project!r}")
    return {"pack": query.context_pack(
        brain.con, project, int(args.get("max_chars", 6000)))}


def _projects(brain, args):
    from . import query
    return {"projects": query.projects(brain.con)}


def _stats(brain, args):
    from . import query
    return query.stats(brain.con)


def _note(brain, args):
    """Agents share context: write a note into the brain (upsert by title)."""
    from . import store
    from .ingest import _chunk_markdown
    import time
    project = re.sub(r"[^a-z0-9._-]", "-",
                     (args.get("project") or "").lower()).strip("-")[:64]
    title = (args.get("title") or "untitled").strip()[:200]
    body = (args.get("body") or "").strip()[:65536]
    if not project:
        raise ValueError("project is required (lowercase slug, e.g. 'my-agent')")
    if not body:
        raise ValueError("body is required")
    store.upsert_source(
        brain.con, f"note:{project}/{title}", "note", project,
        time.time(), len(body), _chunk_markdown(f"# {title}\n\n{body}"))
    brain.con.commit()
    return {"ok": True, "project": project, "title": title}


TOOLS = [
    {"name": "search", "description": "Full-text + entity search over the shared brain.",
     "inputSchema": {"type": "object", "properties": {
         "q": {"type": "string"}, "limit": {"type": "integer", "default": 12}},
         "required": ["q"]}},
    {"name": "ask", "description": "Grounded question answering over the brain; "
     "returns a cited answer when an LLM backend is configured.",
     "inputSchema": {"type": "object", "properties": {
         "q": {"type": "string"}, "use_llm": {"type": "boolean", "default": True}},
         "required": ["q"]}},
    {"name": "entity", "description": "Entity card: mentions, linked chunks, graph neighbors.",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string"}}, "required": ["name"]}},
    {"name": "context_pack", "description": "Compact, injectable context pack for a project.",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}, "max_chars": {"type": "integer", "default": 6000}},
         "required": ["project"]}},
    {"name": "projects", "description": "List projects (spaces) present in the brain.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "stats", "description": "Brain statistics.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "note", "description": "Share context: write a note into the brain under a "
     "project (space). Upserted by title within the project.",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}, "title": {"type": "string"},
         "body": {"type": "string"}}, "required": ["project", "body"]}},
]

TOOL_FUNCS = {t["name"]: f for t, f in zip(
    TOOLS, [_search, _ask, _entity, _context_pack, _projects, _stats, _note])}


def handle(brain, msg):
    """Handle one JSON-RPC message. Returns a response dict, or None for notifications."""
    method = msg.get("method", "")
    rid = msg.get("id")

    def err(code, message):
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": code, "message": message}}

    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "agent-context", "version": __version__}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name", "")
        fn = TOOL_FUNCS.get(name)
        if not fn:
            return err(-32602, f"unknown tool: {name}")
        try:
            out = fn(brain, params.get("arguments") or {})
        except Exception as e:  # surface tool errors inside the result
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"error: {e}"}],
                "isError": True}}
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text",
                         "text": json.dumps(out, default=str, indent=2)}]}}
    return err(-32601, f"method not found: {method}")


def serve_stdio(brain):
    """Newline-delimited JSON-RPC over stdin/stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        resp = handle(brain, msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
