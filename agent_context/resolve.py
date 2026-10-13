"""Resolve: entity extraction and graph edges.

V1 is deterministic — no LLM required:
  * entities from config aliases (name -> type)
  * discovered: projects (source tags), services (snapshot lines),
    ports (:8xxx), model names, hosts
  * mentions: case-insensitive occurrence in each chunk
  * edges: co-occurrence within a chunk ("related") + project->port
"""
import re
import time

PORT_RE = re.compile(r":(8\d{3})\b|port[ ](8\d{3})\b", re.IGNORECASE)
MODEL_RE = re.compile(
    r"\b((?:GLM|Qwen|MiniMax|Klein|Krea|Whisper|faster-whisper|edge-tts|"
    r"tensorfold|vLLM|EXL)[\w.-]*)", re.IGNORECASE)


def _known_entities(config):
    """name -> (type, blurb) from config['entities']."""
    out = {}
    for name, info in (config.get("entities") or {}).items():
        if isinstance(info, str):
            out[name] = (info, "")
        else:
            out[name] = (info.get("type", "concept"), info.get("blurb", ""))
    return out


def discover(con, config):
    """Return dict name -> (type, blurb) of all entities we can see."""
    ents = _known_entities(config)

    for row in con.execute(
            "SELECT DISTINCT project FROM sources WHERE project != ''"):
        p = row["project"]
        if p and p != "(system)":
            ents.setdefault(p, ("project", ""))

    for row in con.execute("SELECT text FROM chunks c "
                           "JOIN sources s ON c.source_id=s.id "
                           "WHERE s.kind='services'"):
        for line in row["text"].splitlines():
            m = re.match(r"(?:service|container): ([\w.@-]+)", line)
            if m:
                ents.setdefault(m.group(1), ("service", line.strip()))

    for (text,) in con.execute("SELECT text FROM chunks"):
        for m in PORT_RE.finditer(text):
            ents.setdefault(m.group(1) or m.group(2), ("port", ""))
        for m in MODEL_RE.finditer(text):
            ents.setdefault(m.group(1), ("model", ""))

    for host in (config.get("hosts") or []):
        ents.setdefault(host, ("host", ""))
    return ents


def build(con, config, progress=None):
    """Full resolve pass: entities, mentions, edges. Returns counts."""
    ents = discover(con, config)
    # name -> id; also map lowercase alias -> canonical name
    ids = {}
    for name, (etype, blurb) in ents.items():
        ids[name.lower()] = name

    from . import store
    eid = {}
    for name, (etype, blurb) in ents.items():
        eid[name] = store.upsert_entity(con, name, etype, blurb)

    # mentions: scan every chunk for entity occurrences (longest names first)
    names = sorted(ents.keys(), key=len, reverse=True)
    lowered = [n.lower() for n in names]

    con.execute("DELETE FROM mentions")
    con.execute("DELETE FROM edges")

    rows = con.execute("SELECT c.id, c.text, s.project, s.kind FROM chunks c "
                       "JOIN sources s ON c.source_id=s.id").fetchall()
    total = len(rows)
    n_ment = 0
    cooccur = {}
    for i, row in enumerate(rows):
        text = row["text"].lower()
        hit = set()
        for name, low in zip(names, lowered):
            if low in text:
                hit.add(name)
        for name in hit:
            con.execute("INSERT OR IGNORE INTO mentions(entity_id, chunk_id) "
                        "VALUES(?,?)", (eid[name], row["id"]))
            n_ment += 1
        # co-occurrence edges within a chunk (cap 6 per chunk)
        hit_l = sorted(hit, key=len, reverse=True)[:6]
        for a in range(len(hit_l)):
            for b in range(a + 1, len(hit_l)):
                key = tuple(sorted((hit_l[a], hit_l[b])))
                cooccur[key] = cooccur.get(key, 0) + 1
        if progress and i % 200 == 0:
            progress(i, total)

    for (a, b), weight in cooccur.items():
        if weight >= 1:
            con.execute("INSERT OR IGNORE INTO edges(src, dst, rel) "
                        "VALUES(?,?,?)", (eid[a], eid[b], f"related x{weight}"))

    # project -> port edges from the project's own chunks
    rows = con.execute(
        "SELECT s.project, c.text FROM chunks c JOIN sources s "
        "ON c.source_id=s.id WHERE s.project NOT IN ('', '(system)')").fetchall()
    for row in rows:
        proj = row["project"]
        if proj not in eid:
            continue
        for m in PORT_RE.finditer(row["text"]):
            port = m.group(1) or m.group(2)
            con.execute("INSERT OR IGNORE INTO edges(src, dst, rel) "
                        "VALUES(?,?,?)", (eid[proj], eid[port], "serves"))
        for m in MODEL_RE.finditer(row["text"]):
            con.execute("INSERT OR IGNORE INTO edges(src, dst, rel) "
                        "VALUES(?,?,?)", (eid[proj], eid[m.group(1)], "uses"))

    store.set_meta(con, "resolved_at", str(time.time()))
    return {"entities": len(eid), "mentions": n_ment, "cooccurs": len(cooccur)}
