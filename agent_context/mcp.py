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
        brain.con, args.get("q", ""), int(args.get("limit", 12)),
        include_stale=bool(args.get("include_stale", False)),
        project=args.get("project"))}


def _ask(brain, args):
    from . import llm, query
    q = (args.get("q") or "").strip()
    if not q:
        raise ValueError("q is required")
    chunks = query.search(brain.con, q,
                          include_stale=bool(args.get("include_stale", False)),
                          project=args.get("project"))
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
    project = re.sub(r"[^a-z0-9._-]", "-", (args.get("project") or "").lower()).strip("-")[:64]
    title = (args.get("title") or "untitled").strip()[:200]
    body = (args.get("body") or "").strip()[:65536]
    if not project:
        raise ValueError("project is required (lowercase slug, e.g. 'my-agent')")
    if not body:
        raise ValueError("body is required")
    confidence = args.get("confidence")
    if confidence is not None:
        confidence = float(confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
    based_on = args.get("sources")
    if based_on is not None:
        if not isinstance(based_on, list) or not all(isinstance(s, str) for s in based_on):
            raise ValueError("sources must be a list of paths (e.g. the repo files the note is based on)")
        based_on = [s[:512] for s in based_on[:32]]
    origin = args.get("origin") or "ai"
    if origin not in ("ai", "human"):
        raise ValueError("origin must be 'ai' or 'human'")
    agent = (args.get("agent") or "").strip()
    to_agent = (args.get("to_agent") or "").strip()
    sid = store.upsert_source(
        brain.con, f"note:{project}/{title}", "note", project,
        time.time(), len(body), _chunk_markdown(f"# {title}\n\n{body}"))
    store.set_note_meta(brain.con, sid, confidence=confidence,
                        based_on=based_on, origin=origin,
                        agent=agent or None, to_agent=to_agent or None)
    brain.con.commit()
    out = {"ok": True, "project": project, "title": title}
    if agent:
        out["agent"] = store._slug_agent(agent)
    if to_agent:
        out["to_agent"] = store._slug_agent(to_agent)
    return out


def _list_projects(brain, args):
    """Inbox rows: per-project latest activity, preview, note count."""
    from . import store
    return {"projects": store.list_projects(brain.con)}


def _get_project_summary(brain, args):
    from . import store
    project = re.sub(r"[^a-z0-9._-]", "-", (args.get("project") or "").lower())[:64]
    if not project:
        raise ValueError("project is required")
    return store.get_summary(brain.con, project) or {"error": "no summary yet",
                                                     "project": project}


def _refresh_project_summary(brain, args):
    from . import autonote
    return autonote.refresh(brain, args.get("project") or "",
                            force=bool(args.get("force")))


def _get_autonote_config(brain, args):
    from . import autonote
    project = (args.get("project") or "").strip()
    if not project:
        raise ValueError("project is required")
    return autonote.resolve_config(brain.con, project)


def _set_autonote_config(brain, args):
    from . import autonote, store
    project = (args.get("project") or "").strip()
    if not project:
        raise ValueError("project is required")
    cfg = autonote.normalize_config(args.get("config"))
    store.set_autonote_config(brain.con, project, cfg)
    return {"ok": True, "project": project, "config": cfg}


def _add_note(brain, args):
    """Thin alias for note(): text only, title derived from the first line."""
    text = (args.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")
    title = (text.splitlines()[0].strip() or "note")
    if len(title) > 60:
        title = title[:57] + "..."
    args = dict(args)
    args["title"] = args.get("title") or title
    args["body"] = text
    return _note(brain, args)


TOOLS = [
    {"name": "search", "description": "Full-text + entity search over the shared brain. "
     "Stale notes (based-on source changed) are excluded unless include_stale.",
     "inputSchema": {"type": "object", "properties": {
         "q": {"type": "string"}, "limit": {"type": "integer", "default": 12},
         "include_stale": {"type": "boolean", "default": False},
         "project": {"type": "string",
                     "description": "Scope to one project (space); omit for all."}},
         "required": ["q"]}},
    {"name": "ask", "description": "Grounded question answering over the brain; "
     "returns a cited answer when an LLM backend is configured.",
     "inputSchema": {"type": "object", "properties": {
         "q": {"type": "string"}, "use_llm": {"type": "boolean", "default": True},
         "include_stale": {"type": "boolean", "default": False},
         "project": {"type": "string",
                     "description": "Scope to one project (space); omit for all."}},
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
     "project (space). Upserted by title within the project. Optionally give a "
     "confidence (0-1) and the source paths the note is based on — when those "
     "sources change later, the note is flagged stale until re-saved.",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}, "title": {"type": "string"},
         "body": {"type": "string"},
         "confidence": {"type": "number", "minimum": 0, "maximum": 1,
                        "description": "How sure you are the note is still accurate (0-1)."},
         "sources": {"type": "array", "items": {"type": "string"},
                     "description": "Repo paths the note is derived from, e.g. [\"README.md\"]."}},
         "required": ["project", "body"]}},
    {"name": "add_note", "description": "Write a quick note into a project's "
     "thread (title is taken from the first line of text). Same as note() "
     "but simpler.",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}, "text": {"type": "string"},
         "confidence": {"type": "number", "minimum": 0, "maximum": 1},
         "sources": {"type": "array", "items": {"type": "string"}}},
         "required": ["project", "text"]}},
    {"name": "list_projects", "description": "Inbox-style rows: one per "
     "project with its latest activity, a one-line preview and note count.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_project_summary", "description": "The pinned auto-summary "
     "note for a project (or an error when none exists yet).",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}}, "required": ["project"]}},
    {"name": "refresh_project_summary", "description": "Regenerate the "
     "project summary from its sources, notes and local repo. Set force=true "
     "to replace a human-edited summary; otherwise returns "
     "status=human_edited with old and new versions for a diff prompt.",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}, "force": {"type": "boolean",
                                                  "default": False}},
         "required": ["project"]}},
    {"name": "get_autonote_config", "description": "The auto-note config for "
     "a project (sections, instruction, sources, trigger, max length).",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}}, "required": ["project"]}},
    {"name": "set_autonote_config", "description": "Store the auto-note "
     "config for a project. Same config the Setup UI edits.",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"},
         "config": {"type": "object", "properties": {
             "enabled": {"type": "boolean"},
             "sections": {"type": "array", "items": {"type": "string"}},
             "instruction": {"type": "string"},
             "sources": {"description": "'auto' or a list of paths"},
             "trigger": {"type": "string",
                         "enum": ["on_push", "daily", "manual"]},
             "max_words": {"type": "integer"}}},
         },
         "required": ["project", "config"]}},
]

TOOL_FUNCS = {t["name"]: f for t, f in zip(
    TOOLS, [_search, _ask, _entity, _context_pack, _projects, _stats, _note,
            _add_note, _list_projects, _get_project_summary,
            _refresh_project_summary, _get_autonote_config,
            _set_autonote_config])}


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
