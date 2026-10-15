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


def _message_peer(brain, args):
    """Grok-style peer ping: write a note with agent → to_agent on the bus.

    Default project is `peers` (shared inbox thread). Visible as
    Messaged ● peer in /setup/. Prefer this over A2A for coordination.

    Peer messages are append-only: path is note:<project>/peer/<nonce>/<title>
    so two sends with the same title never clobber each other (unlike note())."""
    import secrets
    import time as _time
    from . import store
    from .ingest import _chunk_markdown

    agent = (args.get("agent") or "").strip()
    to_agent = (args.get("to_agent") or "").strip()
    body = (args.get("body") or args.get("message") or "").strip()
    if not agent:
        raise ValueError("agent is required (your name, e.g. hermes)")
    if not to_agent:
        raise ValueError("to_agent is required (peer name, e.g. cursor)")
    if not body:
        raise ValueError("body is required")
    project = re.sub(r"[^a-z0-9._-]", "-",
                     (args.get("project") or "peers").lower()).strip("-")[:64] or "peers"
    title = (args.get("title") or "").strip()[:200]
    if not title:
        title = f"to-{store._slug_agent(to_agent)}-{int(_time.time())}"
    # Sanitize title for path segment (no slashes); display title stays clean.
    safe = re.sub(r"[/\\]+", "-", title).strip("-")[:160] or "msg"
    nonce = f"{int(_time.time())}-{secrets.token_hex(3)}"
    path = f"note:{project}/peer/{nonce}/{safe}"
    sid = store.upsert_source(
        brain.con, path, "note", project,
        _time.time(), len(body), _chunk_markdown(f"# {safe}\n\n{body}"))
    store.set_note_meta(
        brain.con, sid, confidence=args.get("confidence"),
        based_on=args.get("sources") if isinstance(args.get("sources"), list) else None,
        origin="ai", agent=agent, to_agent=to_agent)
    brain.con.commit()
    return {
        "ok": True, "project": project, "title": safe,
        "agent": store._slug_agent(agent),
        "to_agent": store._slug_agent(to_agent),
        "id": sid,
    }


def _peer_inbox(brain, args):
    """Messages addressed to you (or sent by you) on the peer bus."""
    from . import store
    to_agent = (args.get("to_agent") or args.get("for") or "").strip() or None
    agent = (args.get("agent") or args.get("from") or "").strip() or None
    project = (args.get("project") or "").strip() or None
    if not to_agent and not agent:
        raise ValueError("pass to_agent (your name) and/or agent (sender)")
    msgs = store.list_peer_messages(
        brain.con, to_agent=to_agent, agent=agent,
        project=project, limit=args.get("limit", 50))
    return {"messages": msgs, "count": len(msgs)}


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
     "sources change later, the note is flagged stale until re-saved. "
     "Pass agent / to_agent for Grok-style Messaged ● peer lines in the inbox.",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}, "title": {"type": "string"},
         "body": {"type": "string"},
         "confidence": {"type": "number", "minimum": 0, "maximum": 1,
                        "description": "How sure you are the note is still accurate (0-1)."},
         "sources": {"type": "array", "items": {"type": "string"},
                     "description": "Repo paths the note is derived from, e.g. [\"README.md\"]."},
         "origin": {"type": "string", "enum": ["ai", "human"],
                    "description": "ai (default) or human."},
         "agent": {"type": "string",
                   "description": "Who wrote this (e.g. hermes, grok-bot)."},
         "to_agent": {"type": "string",
                     "description": "Peer messaged — renders a Messaged ● line."}},
         "required": ["project", "body"]}},
    {"name": "add_note", "description": "Write a quick note into a project's "
     "thread (title is taken from the first line of text). Same as note() "
     "but simpler.",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}, "text": {"type": "string"},
         "confidence": {"type": "number", "minimum": 0, "maximum": 1},
         "sources": {"type": "array", "items": {"type": "string"}},
         "origin": {"type": "string", "enum": ["ai", "human"]},
         "agent": {"type": "string"}, "to_agent": {"type": "string"}},
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
    {"name": "message_peer", "description": "Message another agent on the "
     "shared peers bus (Grok-style). Writes a note with agent → to_agent; "
     "shows as Messaged ● peer in the inbox. Prefer this over A2A for "
     "coordination — no JSON-RPC, no agent card.",
     "inputSchema": {"type": "object", "properties": {
         "agent": {"type": "string",
                   "description": "Your name (e.g. hermes, grok-bot)."},
         "to_agent": {"type": "string",
                     "description": "Peer to message (e.g. cursor, dr-eggbot)."},
         "body": {"type": "string",
                  "description": "Message text (alias: message)."},
         "message": {"type": "string"},
         "title": {"type": "string"},
         "project": {"type": "string", "default": "peers",
                     "description": "Thread; default peers."}},
         "required": ["agent", "to_agent", "body"]}},
    {"name": "peer_inbox", "description": "Read peer-bus messages for you "
     "(to_agent=you) and/or from a sender. Newest first.",
     "inputSchema": {"type": "object", "properties": {
         "to_agent": {"type": "string",
                     "description": "Recipient filter (your name)."},
         "agent": {"type": "string",
                   "description": "Sender filter."},
         "project": {"type": "string"},
         "limit": {"type": "integer", "default": 50}},
         "required": []}},
    {"name": "list_roster", "description": "Cross-project agent table "
     "(hermes, cursor, grok-bot, …) with key + parallel flags.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_boards", "description": "Task boards linked to inbox chats. "
     "Each board has members who may claim work.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_board", "description": "Get (or create) the board for an "
     "inbox chat slug. Defaults to chat=peers.",
     "inputSchema": {"type": "object", "properties": {
         "chat": {"type": "string"}, "board_id": {"type": "integer"}}}},
    {"name": "add_board_member", "description": "Give an agent access to a "
     "board (role: member|worker|admin). Required before they can claim.",
     "inputSchema": {"type": "object", "properties": {
         "chat": {"type": "string"}, "board_id": {"type": "integer"},
         "agent": {"type": "string"},
         "role": {"type": "string", "default": "worker"}},
         "required": ["agent"]}},
    {"name": "remove_board_member", "description": "Remove an agent's access "
     "from a board.",
     "inputSchema": {"type": "object", "properties": {
         "chat": {"type": "string"}, "board_id": {"type": "integer"},
         "agent": {"type": "string"}},
         "required": ["agent"]}},
    {"name": "list_tasks", "description": "Tasks on a chat-linked board. "
     "Filter by status / assignee / chat (default peers).",
     "inputSchema": {"type": "object", "properties": {
         "status": {"type": "string"}, "assignee": {"type": "string"},
         "chat": {"type": "string"}, "board_id": {"type": "integer"},
         "limit": {"type": "integer", "default": 50}}}},
    {"name": "add_task", "description": "Add a task on a board (chat slug). "
     "Rules auto-route assignee when omitted. Assignee must be a member.",
     "inputSchema": {"type": "object", "properties": {
         "title": {"type": "string"}, "body": {"type": "string"},
         "assignee": {"type": "string"},
         "parallel": {"type": "boolean"},
         "chat": {"type": "string"},
         "board_id": {"type": "integer"},
         "created_by": {"type": "string"}},
         "required": ["title"]}},
    {"name": "claim_task", "description": "Claim an open task. Agent must be "
     "a board member. Fails if they already hold a serial task.",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "integer"}, "agent": {"type": "string"}},
         "required": ["id", "agent"]}},
    {"name": "update_task", "description": "Update task status/assignee "
     "(status: open|claimed|done|blocked).",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "integer"}, "status": {"type": "string"},
         "assignee": {"type": "string"}, "parallel": {"type": "boolean"}},
         "required": ["id"]}},
    {"name": "list_briefs", "description": "Per-agent markdown briefs for a "
     "chat board (fluid rules). Members only; each capped at 4KB.",
     "inputSchema": {"type": "object", "properties": {
         "chat": {"type": "string"}, "board_id": {"type": "integer"}}}},
    {"name": "get_brief", "description": "One agent's markdown brief.",
     "inputSchema": {"type": "object", "properties": {
         "agent": {"type": "string"}, "chat": {"type": "string"},
         "board_id": {"type": "integer"}},
         "required": ["agent"]}},
    {"name": "set_brief", "description": "Write/replace an agent's markdown "
     "brief (max 4KB). Optional frontmatter: routes: on-device=serial, code=parallel",
     "inputSchema": {"type": "object", "properties": {
         "agent": {"type": "string"}, "body": {"type": "string"},
         "chat": {"type": "string"}, "board_id": {"type": "integer"}},
         "required": ["agent", "body"]}},
    {"name": "session_pack", "description": "Ingest member briefs at chat/"
     "session start. Pass since_hashes to skip unchanged briefs (anti-bloat). "
     "Pack hard-capped at 12KB.",
     "inputSchema": {"type": "object", "properties": {
         "chat": {"type": "string"}, "board_id": {"type": "integer"},
         "since_hashes": {"type": "object",
                          "description": "{agent: content_hash} from last pack"}}}},
]


def _list_roster(brain, args):
    from . import roster
    return {"agents": roster.list_agents(brain.con)}


def _list_boards(brain, args):
    from . import roster
    return {"boards": roster.list_boards(brain.con)}


def _get_board(brain, args):
    from . import roster
    bid = args.get("board_id")
    return roster.get_board(
        brain.con, chat=args.get("chat"),
        board_id=int(bid) if bid not in (None, "") else None)


def _add_board_member(brain, args):
    from . import roster
    bid = args.get("board_id")
    return roster.add_member(
        brain.con,
        board_id=int(bid) if bid not in (None, "") else None,
        chat=args.get("chat"),
        agent=args.get("agent") or "",
        role=args.get("role") or "worker")


def _remove_board_member(brain, args):
    from . import roster
    bid = args.get("board_id")
    return roster.remove_member(
        brain.con,
        board_id=int(bid) if bid not in (None, "") else None,
        chat=args.get("chat"),
        agent=args.get("agent") or "")


def _list_tasks(brain, args):
    from . import roster
    bid = args.get("board_id")
    return {"tasks": roster.list_tasks(
        brain.con, status=args.get("status"),
        assignee=args.get("assignee"),
        chat=args.get("chat"),
        board_id=int(bid) if bid not in (None, "") else None,
        limit=args.get("limit", 50))}


def _add_task(brain, args):
    from . import roster
    bid = args.get("board_id")
    return roster.add_task(
        brain.con, title=args.get("title") or "",
        body=args.get("body") or "",
        assignee=args.get("assignee") or "",
        parallel=args.get("parallel"),
        created_by=args.get("created_by") or "mcp",
        chat=args.get("chat"),
        board_id=int(bid) if bid not in (None, "") else None)


def _claim_task(brain, args):
    from . import roster
    return roster.claim_task(brain.con, int(args.get("id") or 0),
                             args.get("agent") or "")


def _update_task(brain, args):
    from . import roster
    return roster.update_task(
        brain.con, int(args.get("id") or 0),
        status=args.get("status"), assignee=args.get("assignee"),
        parallel=args.get("parallel"))


def _list_briefs(brain, args):
    from . import roster
    bid = args.get("board_id")
    return {"briefs": roster.list_briefs(
        brain.con, chat=args.get("chat"),
        board_id=int(bid) if bid not in (None, "") else None)}


def _get_brief(brain, args):
    from . import roster
    bid = args.get("board_id")
    return roster.get_brief(
        brain.con, args.get("agent") or "",
        chat=args.get("chat"),
        board_id=int(bid) if bid not in (None, "") else None)


def _set_brief(brain, args):
    from . import roster
    bid = args.get("board_id")
    return roster.set_brief(
        brain.con, args.get("agent") or "", args.get("body") or "",
        chat=args.get("chat"),
        board_id=int(bid) if bid not in (None, "") else None)


def _session_pack(brain, args):
    from . import roster
    bid = args.get("board_id")
    return roster.session_pack(
        brain.con, chat=args.get("chat"),
        board_id=int(bid) if bid not in (None, "") else None,
        since_hashes=args.get("since_hashes"))


TOOL_FUNCS = {t["name"]: f for t, f in zip(
    TOOLS, [_search, _ask, _entity, _context_pack, _projects, _stats, _note,
            _add_note, _list_projects, _get_project_summary,
            _refresh_project_summary, _get_autonote_config,
            _set_autonote_config, _message_peer, _peer_inbox,
            _list_roster, _list_boards, _get_board, _add_board_member,
            _remove_board_member, _list_tasks, _add_task, _claim_task,
            _update_task, _list_briefs, _get_brief, _set_brief,
            _session_pack])}


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
