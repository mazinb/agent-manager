"""Session bootstrap — auto-load context_pack + session_pack when relevant.

Host hooks (MCP initialize instructions, connect CLI, first tools/call) call
`session_bootstrap` so packs fire without waiting for the model to remember.
Client-side hash persistence skips unchanged re-injects.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional


DEFAULT_CHAT = "peers"


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _normalize_since(since_hashes: Any) -> dict:
    if not isinstance(since_hashes, dict):
        return {}
    out = {}
    for k, v in since_hashes.items():
        if k is None or v is None:
            continue
        out[str(k)] = str(v)
    return out


def session_bootstrap(
    con,
    *,
    project: Optional[str] = None,
    chat: Optional[str] = None,
    since_hashes: Any = None,
    context_hash: Optional[str] = None,
    include_session: bool = True,
    include_context: bool = True,
    max_context_chars: int = 6000,
) -> dict:
    """Build an injectable bootstrap payload.

    - When ``include_session`` (default): pull board briefs via
      ``roster.session_pack`` (honors ``since_hashes`` skip).
    - When ``include_context`` and ``project`` is a known slug: pull
      ``query.context_pack``; skip when ``context_hash`` matches.

    Returns dict with ``instructions`` (markdown for MCP initialize /
    client inject), ``session``, ``context``, ``hashes``, ``changed``,
    and ``skipped`` reason flags.
    """
    from . import query, roster

    chat = (chat or DEFAULT_CHAT).strip() or DEFAULT_CHAT
    project = (project or "").strip() or None
    since = _normalize_since(since_hashes)
    prev_ctx = (context_hash or "").strip() or None

    session_out = None
    context_out = None
    parts: list[str] = []
    skipped: dict = {}
    changed = False

    if include_session:
        try:
            session_out = roster.session_pack(
                con, chat=chat, since_hashes=since or None)
            if session_out.get("included"):
                changed = True
                parts.append(session_out["pack"])
            else:
                skipped["session"] = "unchanged"
                # Still surface a one-liner so the host knows we checked.
                parts.append(
                    f"# Session briefs — {session_out.get('chat', chat)}\n\n"
                    f"_(unchanged; {len(session_out.get('skipped') or [])} "
                    f"briefs skipped via since_hashes)_\n")
        except Exception as e:  # board missing / empty install
            skipped["session"] = str(e)
            session_out = {"error": str(e), "chat": chat}

    if include_context and project:
        known = query.projects(con)
        if project not in known:
            skipped["context"] = f"unknown project: {project!r}"
            context_out = {"error": f"unknown project: {project!r}",
                           "project": project}
        else:
            pack = query.context_pack(
                con, project, max_chars=int(max_context_chars or 6000))
            digest = _sha(pack)
            context_out = {
                "project": project,
                "pack": pack,
                "chars": len(pack),
                "content_hash": digest,
            }
            if prev_ctx and prev_ctx == digest:
                skipped["context"] = "unchanged"
                context_out["skipped"] = True
            else:
                changed = True
                parts.append(f"# Context pack — {project}\n\n{pack}\n")
    elif include_context and not project:
        skipped["context"] = "no project pin"

    hashes = {
        "session": (session_out or {}).get("hashes") or {},
        "context": (context_out or {}).get("content_hash"),
        "chat": chat,
        "project": project,
    }

    header = (
        "# Agent-manager session bootstrap\n\n"
        "Auto-loaded on MCP connect / connect CLI / first tool use when a "
        "project pin (`?project=` / `--project`) and/or peers roster is "
        "configured. Re-inject with `session_bootstrap` + prior hashes to "
        "skip unchanged briefs.\n"
    )
    body = "\n".join(parts).strip()
    instructions = header + ("\n" + body + "\n" if body else
                             "\n_(no packs to inject)_\n")

    return {
        "ok": True,
        "chat": chat,
        "project": project,
        "instructions": instructions,
        "session": session_out,
        "context": context_out,
        "hashes": hashes,
        "changed": changed,
        "skipped": skipped,
        "chars": len(instructions),
    }


def hashes_from_state(state: Any) -> tuple[dict, Optional[str]]:
    """Extract (since_hashes, context_hash) from a client-persisted state dict."""
    if not isinstance(state, dict):
        return {}, None
    hashes = state.get("hashes") if isinstance(state.get("hashes"), dict) else state
    since = hashes.get("session") if isinstance(hashes, dict) else None
    ctx = None
    if isinstance(hashes, dict):
        ctx = hashes.get("context")
    return _normalize_since(since), (str(ctx) if ctx else None)


def merge_state(prev: Any, result: dict, *, url: str = "",
                agent: str = "") -> dict:
    """Merge a bootstrap result into client-side persisted state."""
    prev = dict(prev) if isinstance(prev, dict) else {}
    h = result.get("hashes") or {}
    prev_hashes = prev.get("hashes") if isinstance(prev.get("hashes"), dict) else {}
    session_hashes = dict(prev_hashes.get("session") or {})
    new_session = h.get("session") if isinstance(h.get("session"), dict) else {}
    session_hashes.update(new_session)
    context_hash = h.get("context") or prev_hashes.get("context")
    return {
        "url": url or prev.get("url") or "",
        "agent": agent or prev.get("agent") or "",
        "chat": h.get("chat") or result.get("chat") or prev.get("chat") or DEFAULT_CHAT,
        "project": h.get("project") if h.get("project") is not None
                   else prev.get("project"),
        "hashes": {
            "session": session_hashes,
            "context": context_hash,
        },
        "last_chars": result.get("chars"),
        "last_changed": bool(result.get("changed")),
    }


def format_inject_markdown(result: dict) -> str:
    """Cursor-rule / inject-file body from a bootstrap result."""
    return (result.get("instructions") or "").rstrip() + "\n"


def should_write_inject(result: dict, prev_state: Any = None) -> bool:
    """True when client should rewrite the local inject file."""
    if result.get("changed"):
        return True
    if not prev_state:
        return True
    return False
