"""Auto summary notes per project — the pinned note at the top of a thread.

One summary per project, stored as kind='summary' (path summary:<project>).
Generated from the brain's own source docs and notes for the project, plus
— when the project folder exists on this machine — its README and recent
git log. Config comes from project_config (set via UI or MCP), shared by
both. If a human edited the summary by hand, auto refresh does NOT
overwrite it: the caller gets status 'human_edited' with both versions and
decides (view diff / replace).
"""
import os
import subprocess

from . import llm, store

DEFAULT_SECTIONS = ["What it is", "How to run", "Ports and services",
                    "Status", "Open todos"]
DEFAULT_CONFIG = {
    "enabled": True,
    "sections": list(DEFAULT_SECTIONS),
    "instruction": "",
    "sources": "auto",   # 'auto' or list of extra paths
    "trigger": "daily",  # on_push | daily | manual
    "max_words": 220,
}
_TRIGGERS = ("on_push", "daily", "manual")
_PROJECTS_ROOT = os.path.expanduser("~/projects")


def normalize_config(raw):
    """Fill defaults and validate; unknown keys are dropped, bad values
    raise ValueError so the UI/MCP caller gets a clear error."""
    if raw is None:
        return dict(DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        raise ValueError("config must be an object")
    cfg = dict(DEFAULT_CONFIG)
    if "enabled" in raw:
        cfg["enabled"] = bool(raw["enabled"])
    if "sections" in raw:
        if not isinstance(raw["sections"], list) or \
                not all(isinstance(s, str) for s in raw["sections"]):
            raise ValueError("sections must be a list of strings")
        cfg["sections"] = [s[:64] for s in raw["sections"][:12]]
    if "instruction" in raw:
        if not isinstance(raw["instruction"], str):
            raise ValueError("instruction must be a string")
        cfg["instruction"] = raw["instruction"][:2000]
    if "sources" in raw:
        if raw["sources"] == "auto":
            cfg["sources"] = "auto"
        elif isinstance(raw["sources"], list) and \
                all(isinstance(s, str) for s in raw["sources"]):
            cfg["sources"] = [s[:512] for s in raw["sources"][:32]]
        else:
            raise ValueError("sources must be 'auto' or a list of paths")
    if "trigger" in raw:
        if raw["trigger"] not in _TRIGGERS:
            raise ValueError("trigger must be one of " + ", ".join(_TRIGGERS))
        cfg["trigger"] = raw["trigger"]
    if "max_words" in raw:
        try:
            cfg["max_words"] = max(60, min(2000, int(raw["max_words"])))
        except (TypeError, ValueError):
            raise ValueError("max_words must be an integer")
    return cfg


def resolve_config(con, project):
    return normalize_config(store.get_autonote_config(con, project))


def _git(repo_dir, args):
    try:
        out = subprocess.run(
            ["git"] + args, cwd=repo_dir, capture_output=True, text=True,
            timeout=8)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _local_repo_context(project, budget=3000):
    """README head + git log when the project folder exists on this box."""
    repo_dir = os.path.join(_PROJECTS_ROOT, project)
    if not os.path.isdir(repo_dir):
        return "", []
    parts, used = [], []
    readme = ""
    for name in ("README.md", "readme.md", "README"):
        p = os.path.join(repo_dir, name)
        if os.path.isfile(p):
            try:
                readme = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                readme = ""
            if readme:
                used.append(f"{name} (local)")
                break
    if readme:
        parts.append("### README\n" + readme[:1500])
    log = _git(repo_dir, ["log", "--oneline", "-10"])
    if log:
        used.append("git log (local)")
        parts.append("### Recent git log\n" + log)
    if not parts:
        return "", []
    ctx = "\n\n".join(parts)
    return ctx[:budget], used


def collect_context(con, project, cfg):
    """Everything the generator may use. Returns (context_text, based_on)."""
    parts, based_on = [], []
    # 1) Source docs already in the brain for this project
    rows = con.execute(
        "SELECT id, path, kind FROM sources WHERE project=? "
        "AND kind NOT IN ('note','summary')", (project,)).fetchall()
    used = 0
    for r in rows[:20]:
        texts = con.execute(
            "SELECT text FROM chunks WHERE source_id=? ORDER BY ord",
            (r["id"],)).fetchall()
        body = "\n".join(t["text"] for t in texts)[:1200]
        if not body.strip():
            continue
        parts.append(f"### {r['path']} ({r['kind']})\n{body}")
        based_on.append(r["path"])
        used += len(body)
        if used > 9000:
            break
    # 2) Local repo (README + git log)
    local_ctx, local_used = _local_repo_context(project)
    if local_ctx:
        parts.append("### Local repository\n" + local_ctx)
        based_on.extend(local_used)
    # 3) Recent notes in the thread
    notes = store.list_notes(con, project)[:8]
    if notes:
        block = "\n".join(
            f"- [{n['origin']}] {n['title']}: "
            f"{n['body'][:300].replace(chr(10), ' ')}"
            for n in notes)
        parts.append("### Recent notes in this thread\n" + block)
    # 4) Extra paths pinned in config
    if isinstance(cfg.get("sources"), list):
        based_on.extend(cfg["sources"])
    return "\n\n".join(parts)[:16000], based_on


def _entities(con, project, limit=15):
    rows = con.execute(
        "SELECT DISTINCT e.name FROM entities e JOIN mentions m "
        "ON m.entity_id = e.id JOIN chunks c ON c.id = m.chunk_id "
        "JOIN sources s ON s.id = c.source_id "
        "WHERE s.project=? LIMIT ?", (project, limit)).fetchall()
    return [r["name"] for r in rows]


def _fallback_summary(context, sections):
    """Deterministic extractive summary when no LLM is available."""
    lines = []
    for section in sections:
        lines.append(f"## {section}")
        grabbed = 0
        for line in context.splitlines():
            line = line.strip()
            if line.startswith(("#", "###")) or not line:
                continue
            lines.append(f"- {line[:200]}")
            grabbed += 1
            if grabbed >= 3:
                break
        lines.append("")
    return "\n".join(lines).strip()


def generate_text(con, project, cfg, llm_cfg=None):
    """Build the summary body (LLM when configured, extractive fallback
    otherwise) without writing anything."""
    context, _ = collect_context(con, project, cfg)
    sections = cfg["sections"] or DEFAULT_SECTIONS
    entities = _entities(con, project)
    if entities:
        context += "\n\n### Known entities\n" + ", ".join(entities)
    llm_cfg = llm_cfg or {}
    text = None
    if llm_cfg.get("base_url"):
        system = (
            "You maintain the auto-summary note pinned at the top of a "
            "project's memory thread. Write short, scannable sections with "
            "exact section headings. Facts only, from the given context. "
            "If a section has nothing, write 'Unknown'.")
        user = (
            f"Project: {project}\n"
            f"Sections to include (in order): {', '.join(sections)}\n"
            f"Maximum length: about {cfg['max_words']} words.\n"
            + (f"Extra instruction from the owner: {cfg['instruction']}\n"
               if cfg["instruction"] else "")
            + "\n### Context\n" + context
            + "\n\nReturn markdown with the requested sections.")
        text = llm.chat(llm_cfg["base_url"], llm_cfg.get("model", ""),
                        system, user, max_tokens=cfg["max_words"] * 3)
    if not text:
        text = _fallback_summary(context, sections)
    return text.strip(), context


def refresh(brain, project, force=False, cfg=None):
    """Generate (and store unless blocked) the project summary.

    Returns a dict:
      status 'disabled'      — config off; nothing done
      status 'ok'            — stored, 'summary' holds the row
      status 'human_edited'  — a human edited the pinned summary; nothing
                               overwritten. 'old' is the human version,
                               'new' the fresh candidate for a view-diff /
                               replace prompt. Pass force=True to replace.
    """
    con = brain.con
    cfg = cfg or resolve_config(con, project)
    if not cfg["enabled"]:
        return {"status": "disabled", "project": project}
    body, _ = generate_text(con, project, cfg,
                            (brain.config or {}).get("llm") or {})
    _, based_on = collect_context(con, project, cfg)
    existing = store.get_summary(con, project)
    if existing and existing["origin"] == "human" and not force:
        return {"status": "human_edited", "project": project,
                "old": existing,
                "new": {"project": project, "body": body,
                        "based_on": based_on}}
    store.set_summary(con, project, body, based_on=based_on, origin="ai")
    return {"status": "ok", "project": project,
            "summary": store.get_summary(con, project)}
