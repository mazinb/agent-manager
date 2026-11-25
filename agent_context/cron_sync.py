"""Live cron sync for workspace agents.

Reads the Hermes cron registry (`~/.hermes/cron/jobs.json`, read-only) and
maps each agent's `source_job_ids` to its schedule, state, last status and
next run. Schedules stay owned by Hermes; this module only reports them.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

DEFAULT_PATH = os.path.expanduser("~/.hermes/cron/jobs.json")
ENV_PATH = "AGENT_MANAGER_CRON_JOBS"
MAX_ERROR = 240
RECORD_KEYS = ("id", "name", "schedule", "state", "enabled", "no_agent",
               "last_status", "last_run_ts", "next_run_ts", "last_error")


def path():
    return os.environ.get(ENV_PATH) or DEFAULT_PATH


def _ts(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError):
        return None


def _text(value, cap=200):
    text = str(value or "").strip()
    return text[:cap]


def _truncate(value):
    text = str(value or "").strip()
    if len(text) <= MAX_ERROR:
        return text
    return text[:MAX_ERROR - 1] + "…"


def _record(row):
    schedule = (row.get("schedule_display")
                or (row.get("schedule") or {}).get("display")
                or (row.get("schedule") or {}).get("expr")
                or "")
    enabled = bool(row.get("enabled"))
    return {
        "id": str(row.get("id") or ""),
        "name": _text(row.get("name"), 120),
        "schedule": _text(schedule, 120),
        "state": _text(row.get("state") or ("scheduled" if enabled
                                            else "paused"), 40),
        "enabled": enabled,
        "no_agent": bool(row.get("no_agent")),
        "last_status": _text(row.get("last_status"), 40),
        "last_run_ts": _ts(row.get("last_run_at")),
        "next_run_ts": _ts(row.get("next_run_at")),
        "last_error": _truncate(row.get("last_error")),
    }


def load(path_override=None):
    """Read the cron registry into {id: record}. Missing/bad file -> empty."""
    out = {"jobs": {}, "updated_at": ""}
    try:
        with open(path_override or path(), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return out
    if isinstance(raw, dict):
        rows = raw.get("jobs") or []
        out["updated_at"] = str(raw.get("updated_at") or "")
    elif isinstance(raw, list):
        rows = raw
    else:
        return out
    for row in rows:
        if isinstance(row, dict) and row.get("id"):
            rec = _record(row)
            out["jobs"][rec["id"]] = rec
    return out


def summarize(job_ids, snapshot=None):
    """Aggregate live cron state for one agent's source job ids."""
    ids = [str(j) for j in (job_ids or [])]
    snap = snapshot if snapshot is not None else load()
    records = []
    for job_id in ids:
        rec = snap["jobs"].get(job_id)
        records.append(dict(rec) if rec else {"id": job_id, "missing": True})
    live = [r for r in records if not r.get("missing")]
    enabled = [r for r in live if r["enabled"]]
    paused = [r for r in live if not r["enabled"]]
    missing = len(records) - len(live)

    dated = sorted((r for r in enabled if r["next_run_ts"]),
                   key=lambda r: r["next_run_ts"])
    next_job = dated[0] if dated else None

    if not ids:
        schedule = "on demand"
    elif not live:
        schedule = "no cron job"
    elif enabled:
        base = (next_job or enabled[0])["schedule"] or "scheduled"
        schedule = f"{base} +{len(enabled) - 1}" if len(enabled) > 1 else base
    else:
        schedule = "paused"

    last = None
    for rec in live:
        if rec["last_run_ts"] and (last is None
                                   or rec["last_run_ts"] > last["last_run_ts"]):
            last = rec
    return {
        "jobs": records,
        "count": len(records),
        "live": len(live),
        "missing": missing,
        "paused": len(paused),
        "schedule": schedule,
        "next_run_ts": next_job["next_run_ts"] if next_job else None,
        "next_job_id": next_job["id"] if next_job else None,
        "last_status": last["last_status"] if last else None,
        "last_run_ts": last["last_run_ts"] if last else None,
        "last_job_id": last["id"] if last else None,
    }
