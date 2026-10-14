"""Query: FTS search + entity expansion + context packs + optional LLM answer."""
import re

_HEADING_LINE = re.compile(r"^#{1,6}\s+(.*)$")


def _fts_expr(q):
    terms = re.findall(r"[\w.-]+", q)
    return " OR ".join('"%s"' % t for t in terms if t)


def _body_without_heading(text, heading):
    """Drop a leading markdown heading that duplicates the stored heading.

    Older ingest kept `# Title` inside chunk text while also storing
    heading='Title'; packs then prefixed `## Title` again.
    """
    if not text or not heading:
        return text or ""
    lines = text.splitlines()
    m = _HEADING_LINE.match(lines[0])
    if m and m.group(1).strip().casefold() == heading.strip().casefold():
        return "\n".join(lines[1:]).lstrip("\n")
    return text


def search(con, q, limit=12):
    """Hybrid: FTS hits + chunks mentioning entities named in the query."""
    expr = _fts_expr(q)
    results = {}
    if expr:
        rows = con.execute(
            "SELECT c.id, c.heading, c.text, s.path, s.project, s.kind "
            "FROM chunks_fts f JOIN chunks c ON c.id=f.rowid "
            "JOIN sources s ON c.source_id=s.id "
            "WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?", (expr, limit * 2))
        for r in rows:
            results[r["id"]] = dict(r)
    # entity expansion: query names an entity -> its mentioned chunks
    for m in re.findall(r"[\w.-]+", q):
        erow = con.execute("SELECT id FROM entities WHERE name=? COLLATE NOCASE",
                           (m,)).fetchone()
        if erow:
            rows = con.execute(
                "SELECT c.id, c.heading, c.text, s.path, s.project, s.kind "
                "FROM mentions mn JOIN chunks c ON c.id=mn.chunk_id "
                "JOIN sources s ON c.source_id=s.id "
                "WHERE mn.entity_id=? LIMIT ?", (erow["id"], limit))
            for r in rows:
                results.setdefault(r["id"], dict(r))
    # rank: project matches + shorter chunks first as a cheap relevance proxy
    out = sorted(results.values(),
                 key=lambda r: (q.lower() not in r["text"].lower(),
                                len(r["text"])))[:limit]
    return out


def entity_card(con, name):
    erow = con.execute("SELECT * FROM entities WHERE name=? COLLATE NOCASE",
                       (name,)).fetchone()
    if not erow:
        return None
    chunks = con.execute(
        "SELECT c.heading, c.text, s.path, s.project FROM mentions mn "
        "JOIN chunks c ON c.id=mn.chunk_id JOIN sources s ON c.source_id=s.id "
        "WHERE mn.entity_id=? ORDER BY s.kind LIMIT 20",
        (erow["id"],)).fetchall()
    neighbors = con.execute(
        "SELECT e2.name, e2.type, ed.rel FROM edges ed "
        "JOIN entities e2 ON e2.id=ed.dst WHERE ed.src=? "
        "UNION SELECT e3.name, e3.type, ed.rel FROM edges ed "
        "JOIN entities e3 ON e3.id=ed.src WHERE ed.dst=? LIMIT 30",
        (erow["id"], erow["id"])).fetchall()
    return {"entity": dict(erow),
            "chunks": [dict(c) for c in chunks],
            "neighbors": [dict(n) for n in neighbors]}


def context_pack(con, project, max_chars=6000):
    """Compact injectable pack for an agent prompt."""
    parts = []
    rows = con.execute(
        "SELECT s.kind, c.heading, c.text FROM chunks c "
        "JOIN sources s ON c.source_id=s.id WHERE s.project=? "
        "ORDER BY CASE s.kind WHEN 'project_readme' THEN 0 "
        "WHEN 'rule' THEN 1 WHEN 'soul' THEN 2 WHEN 'skill' THEN 3 "
        "WHEN 'memory' THEN 4 WHEN 'services' THEN 5 WHEN 'git' THEN 6 "
        "ELSE 7 END, s.path, c.ord", (project,)).fetchall()
    budget = max_chars
    for r in rows:
        text = _body_without_heading(r["text"] or "", r["heading"] or "")
        if r["heading"]:
            block = f"## {r['heading']}\n{text}\n" if text else f"## {r['heading']}\n"
        else:
            block = text + "\n"
        if len(block) > budget:
            block = block[:budget] + "\n…\n"
        if budget <= 0:
            break
        parts.append(block)
        budget -= len(block)
    return f"# Context pack: {project}\n\n" + "\n".join(parts)


def projects(con):
    return [r["project"] for r in con.execute(
        "SELECT DISTINCT project FROM sources "
        "WHERE project NOT IN ('', '(system)') ORDER BY project")]


def stats(con):
    return {
        "sources": con.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
        "chunks": con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "entities": con.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
        "edges": con.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        "last_refresh": (con.execute(
            "SELECT value FROM meta WHERE key='refreshed_at'").fetchone() or [None])[0],
    }
