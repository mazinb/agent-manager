#!/usr/bin/env python3
"""Browser end-to-end proof for the agents workspace at 390x844.

Drives headless Chromium over CDP against a live agent-manager instance,
exercises docs/agents-workspace.md section 8 (rail, server-composed chips,
ghost prompt, real brain chat reply, peer tab, no horizontal overflow, no
console errors) and writes screenshots plus an evidence JSON under
docs/evidence/agents-workspace/. The token is read from the repo .env and is
never written into evidence or printed.

Requires the `websockets` package (present in the Hermes python) and a
Chromium binary (found under ~/.hermes/tools/chromium-* by default).

Usage:
  python3 scripts/ws_browser_e2e.py                  # https://bot.getzoro.com
  python3 scripts/ws_browser_e2e.py --base http://127.0.0.1:8075
  python3 scripts/ws_browser_e2e.py --no-writes      # skip the chat send
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_EVIDENCE = os.path.join(ROOT, "docs", "evidence", "agents-workspace")
DEFAULT_BASE = "https://bot.getzoro.com"
TOKEN_ENV = "AGENT_MANAGER_TOKEN"
VIEWPORT = {"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True}
USER_AGENT = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/145.0.0.0 Mobile Safari/537.36")


def load_token(env_path=None):
    """Read AGENT_MANAGER_TOKEN from .env without logging the value."""
    path = env_path or os.path.join(ROOT, ".env")
    if not os.path.isfile(path):
        return ""
    with open(path) as f:
        for line in f:
            m = re.match(r"^\s*" + TOKEN_ENV + r"\s*=\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    return ""


def find_chrome(explicit=None):
    """Return a Chromium binary path or '' when none is installed."""
    candidates = []
    if explicit:
        candidates.append(explicit)
    env = os.environ.get("HERMES_CHROME")
    if env:
        candidates.append(env)
    candidates.extend(sorted(glob.glob(os.path.expanduser(
        "~/.hermes/tools/chromium-*/chrome-linux/chrome")), reverse=True))
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return ""


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def parse_ws_url(text):
    """Extract the DevTools websocket URL from chrome's stderr."""
    m = re.search(r"DevTools listening on (ws://\S+)", text or "")
    return m.group(1) if m else ""


def console_error(event):
    """Map a CDP event to (kind, detail) when it is a page error, else None."""
    method = event.get("method")
    params = event.get("params") or {}
    if method == "Runtime.exceptionThrown":
        det = params.get("exceptionDetails") or {}
        text = det.get("text") or ""
        exc = (det.get("exception") or {}).get("description") or ""
        return "exception", _excerpt((text + " " + exc).strip())
    if method == "Log.entryAdded":
        entry = params.get("entry") or {}
        if entry.get("level") == "error":
            url = entry.get("url") or ""
            return "log", _excerpt(
                f"{entry.get('source')}: {entry.get('text')}" + (f" @ {url}" if url else ""))
        return None
    if method == "Runtime.consoleAPICalled":
        if params.get("type") == "error":
            args = [a.get("value") if isinstance(a.get("value"), str)
                    else a.get("description") or "" for a in params.get("args") or []]
            return "console", _excerpt(" ".join(args))
        return None
    return None


def overflow_verdict(metrics):
    """Pass only when no horizontal scrolling exists at the measured width."""
    if not isinstance(metrics, dict):
        return False, "no metrics"
    width = metrics.get("innerWidth") or 0
    doc = metrics.get("doc") or 0
    body = metrics.get("body") or 0
    bad = []
    for c in metrics.get("containers") or []:
        if isinstance(c, dict) and (c.get("sw") or 0) > (c.get("cw") or 0) + 1:
            bad.append(f"{c.get('id')} {c.get('sw')}>{c.get('cw')}")
    ok = bool(width) and doc <= width + 1 and body <= width + 1 and not bad
    detail = (f"innerWidth={width} doc={doc} body={body} "
              f"offenders={metrics.get('offenders') or []}")
    if bad:
        detail += f" scroll={bad}"
    return ok, detail


def _excerpt(value, limit=200):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


def _check(checks, cid, name, ok, detail="", skipped=False):
    entry = {"id": cid, "name": name, "ok": bool(ok) if not skipped else None,
             "skipped": bool(skipped), "detail": detail}
    checks.append(entry)
    return entry


def summarize(checks):
    passed = sum(1 for c in checks if c.get("ok") is True)
    failed = [c for c in checks if c.get("ok") is False]
    skipped = sum(1 for c in checks if c.get("skipped"))
    return {"total": len(checks), "passed": passed, "failed": len(failed),
            "skipped": skipped, "failed_ids": [c["id"] for c in failed]}


def exit_code(evidence):
    return 0 if not summarize(evidence.get("checks") or []).get("failed") else 1


def write_evidence(evidence, out_dir=DEFAULT_EVIDENCE, stamp=None):
    """Write timestamped + latest evidence JSON; return both paths."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = os.path.join(out_dir, f"browser-e2e-{stamp}.json")
    latest = os.path.join(out_dir, "browser-e2e-latest.json")
    raw = json.dumps(evidence, indent=2, ensure_ascii=False) + "\n"
    for target in (path, latest):
        with open(target, "w", encoding="utf-8") as f:
            f.write(raw)
    return path, latest


class CDP:
    """Minimal synchronous Chrome DevTools Protocol client."""

    def __init__(self, ws_url, timeout=30):
        from websockets.sync.client import connect
        self.ws = connect(ws_url, max_size=64_000_000, open_timeout=timeout)
        self._id = 0
        self.events = []

    def send(self, method, params=None, timeout=60):
        self._id += 1
        cid = self._id
        self.ws.send(json.dumps({"id": cid, "method": method,
                                 "params": params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = json.loads(self.ws.recv(timeout=max(0.5, deadline - time.monotonic())))
            if msg.get("id") == cid:
                return msg
            if "method" in msg:
                self.events.append(msg)
        raise TimeoutError(f"CDP timeout: {method}")

    def eval(self, expression, await_promise=False, timeout=60):
        out = self.send("Runtime.evaluate", {
            "expression": expression, "returnByValue": True,
            "awaitPromise": await_promise}, timeout=timeout)
        res = out.get("result") or {}
        if res.get("exceptionDetails"):
            det = res["exceptionDetails"]
            raise RuntimeError(det.get("text") or json.dumps(det)[:300])
        return (res.get("result") or {}).get("value")

    def js(self, expression):
        return json.loads(self.eval(f"JSON.stringify(({expression}))"))

    def drain(self):
        self.eval("1")
        return list(self.events)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def _http_json(url, method="GET", timeout=5):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _api(base, token, path, timeout=60):
    req = urllib.request.Request(base.rstrip("/") + path, headers={
        "Accept": "application/json", "X-Token": token,
        "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read())


def _wait(cdp, expr, predicate, timeout, interval=0.5):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = cdp.js(expr)
        except Exception as e:
            last = {"error": str(e)}
        try:
            if predicate(last):
                return last
        except Exception:
            pass
        time.sleep(interval)
    return last


RAIL_EXPR = """(() => {
  const rows = [...document.querySelectorAll('#agent-groups .agent-row')];
  return {
    title: document.title, url: location.href,
    rows: rows.length,
    count: (document.querySelector('#rail-count') || {}).textContent || '',
    slugs: rows.map(b => b.dataset.slug),
    groups: [...document.querySelectorAll('#agent-groups .grp')].map(g => g.textContent),
    nextLines: [...document.querySelectorAll('#agent-groups .ar-sub')]
      .map(s => s.textContent).filter(t => /^next /.test(t)).length,
    gate: (document.querySelector('#token-gate') || {}).className || '',
    recent: document.querySelectorAll('#recent .agent-row').length
  };
})()"""

OVERFLOW_EXPR = """(() => {
  const ids = ['rail', 'agent-groups', 'thread', 'composer', 'chips', 'peers-view'];
  const containers = ids.map(id => {
    const e = document.getElementById(id);
    return e ? {id, sw: e.scrollWidth, cw: e.clientWidth} : null;
  }).filter(Boolean);
  const offenders = [...document.querySelectorAll('body *')].filter(e => {
    const r = e.getBoundingClientRect();
    const s = getComputedStyle(e);
    return r.width > 0 && r.left < innerWidth && r.right > innerWidth + 1 &&
           s.visibility !== 'hidden' && s.display !== 'none';
  }).slice(0, 12).map(e => e.tagName + '.' + (e.className || ''));
  return {
    innerWidth, doc: document.documentElement.scrollWidth,
    body: document.body.scrollWidth, containers, offenders
  };
})()"""

CHIPS_EXPR = """(() => ({
  chips: [...document.querySelectorAll('#chips button')].map(b => ({
    label: b.textContent, kind: b.dataset.kind, payload: b.dataset.payload
  })),
  ghost: (document.querySelector('#msg') || {}).placeholder || '',
  head: (document.querySelector('#head-name') || {}).textContent || '',
  view: (document.querySelector('#thread-view') || {}).className || '',
  bodyClass: document.body.className || '',
  tabs: [...document.querySelectorAll('.tabs button')].map(b => ({
    tab: b.dataset.tab, on: b.classList.contains('on')
  }))
}))()"""

GHOST_EXPR = """(() => {
  const btn = [...document.querySelectorAll('#chips button')]
    .find(b => b.dataset.kind === 'prompt');
  if (!btn) return {ok: false, reason: 'no prompt chip'};
  const before = document.querySelectorAll('#thread .msg').length;
  const payload = btn.dataset.payload || '';
  btn.click();
  const value = (document.querySelector('#msg') || {}).value || '';
  const after = document.querySelectorAll('#thread .msg').length;
  document.querySelector('#msg').value = '';
  return {ok: true, payload, value, before, after};
})()"""

THREAD_EXPR = """(() => {
  const msgs = [...document.querySelectorAll('#thread .msg')];
  const assistants = msgs.filter(m => m.classList.contains('assistant'));
  const typing = assistants.filter(m => m.classList.contains('typing')).length;
  const last = assistants.filter(m => !m.classList.contains('typing')).slice(-1)[0];
  return {
    total: msgs.length, assistants: assistants.length, typing,
    text: last ? last.innerText : '',
    notes: [...document.querySelectorAll('#thread .note')].map(n => n.textContent)
  };
})()"""

PEERS_EXPR = """(() => {
  const view = document.querySelector('#peers-view');
  const opts = document.querySelectorAll('#peer-to option').length;
  const rows = document.querySelectorAll('#peer-list .peer').length;
  const empty = document.querySelector('#peer-list .empty');
  return {
    visible: view ? view.classList.contains('on') : false,
    options: opts, rows, empty: empty ? empty.textContent : '',
    threadHidden: document.querySelector('#thread').classList.contains('hidden')
  };
})()"""


def run_browser_e2e(base=DEFAULT_BASE, token="", include_writes=True,
                    chrome="", chat_timeout=180, out_dir=DEFAULT_EVIDENCE,
                    keep_browser=False, stamp=None):
    checks = []
    errors = []
    shots = []
    metrics = {}
    started = time.monotonic()
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    chrome = chrome or find_chrome()
    if not chrome:
        _check(checks, "chrome", "Chromium binary found", False,
               "set --chrome or HERMES_CHROME")
        return {"checks": checks, "console_errors": [], "screenshots": [],
                "viewport": VIEWPORT, "base": base, "timestamp": stamp,
                "elapsed_ms": 0}

    prof = tempfile.mkdtemp(prefix="ws-browser-", dir=os.environ.get("TMPDIR") or None)
    port = free_port()
    proc = subprocess.Popen([
        chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
        "--disable-dev-shm-usage", "--disable-extensions", "--no-first-run",
        "--hide-scrollbars", "--force-device-scale-factor=2",
        f"--remote-debugging-port={port}", f"--user-data-dir={prof}",
        f"--window-size={VIEWPORT['width']},{VIEWPORT['height']}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cdp = None
    try:
        version = {}
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                version = _http_json(f"http://127.0.0.1:{port}/json/version")
                break
            except Exception:
                time.sleep(0.25)
        if not version:
            raise RuntimeError("chromium did not expose a DevTools endpoint")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/json/new?url=about:blank", method="PUT")
        with urllib.request.urlopen(req, timeout=5) as resp:
            target = json.loads(resp.read())
        cdp = CDP(target["webSocketDebuggerUrl"])
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Log.enable")
        cdp.send("Network.enable")
        cdp.send("Emulation.setDeviceMetricsOverride", VIEWPORT)
        cdp.send("Emulation.setUserAgentOverride", {"userAgent": USER_AGENT})
        if token:
            cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source":
                "try{localStorage.setItem('am_token',%s)}catch(e){}"
                % json.dumps(token)})
        cdp.send("Page.navigate", {"url": base.rstrip("/") + "/bot/"})

        rail = _wait(cdp, RAIL_EXPR,
                     lambda r: r.get("rows") == 8 and "8 agents" in (r.get("count") or ""),
                     40)
        page_ok = (rail.get("rows") == 8 and rail.get("gate") == ""
                   and "/bot/" in (rail.get("url") or ""))
        _check(checks, "page_load", "/bot/ loads with seeded token, gate closed",
               page_ok, f"title={rail.get('title')} url={rail.get('url')} gate={rail.get('gate')}")
        _check(checks, "rail_agents", "rail renders 8 agents",
               rail.get("rows") == 8 and rail.get("count") == "8 agents",
               f"rows={rail.get('rows')} count={rail.get('count')} slugs={rail.get('slugs')}")
        _check(checks, "rail_cron", "rail shows live cron next-run lines",
               (rail.get("nextLines") or 0) >= 1,
               f"next_lines={rail.get('nextLines')} groups={rail.get('groups')}")

        metrics["rail"] = cdp.js(OVERFLOW_EXPR)
        ok, detail = overflow_verdict(metrics["rail"])
        _check(checks, "overflow_rail", "no horizontal overflow at 390 px (rail)",
               ok, detail)
        shots.append(_shot(cdp, out_dir, stamp, "rail"))

        slug = (rail.get("slugs") or ["health-auditor"])[0]
        cdp.eval(f"document.querySelector('#agent-groups .agent-row[data-slug={json.dumps(slug)}]').click()")
        chips = _wait(cdp, CHIPS_EXPR,
                      lambda r: "chat-open" in (r.get("view") or "")
                      and len(r.get("chips") or []) > 0, 30)
        opened = ("chat-open" in (chips.get("bodyClass") or "")
                  and bool(chips.get("head"))
                  and "hidden" not in (chips.get("view") or ""))
        _check(checks, "open_agent", f"opening {slug} renders thread and chips",
               opened, f"slug={slug} head={chips.get('head')} chips={len(chips.get('chips') or [])}")

        api_status, detail_body = _api(base, token, f"/api/ws/agents/{slug}")
        api_chips = (detail_body or {}).get("chips") or {}
        dom_labels = [c.get("label") for c in chips.get("chips") or []]
        api_labels = [c.get("label") for c in api_chips.get("chips") or []]
        same = dom_labels == api_labels and chips.get("ghost") == (api_chips.get("ghost") or "")
        _check(checks, "chips_server", "chips and ghost match the server payload",
               api_status == 200 and same,
               f"api_status={api_status} dom={dom_labels} api={api_labels} "
               f"ghost_match={chips.get('ghost') == (api_chips.get('ghost') or '')}")

        ghost = cdp.js(GHOST_EXPR)
        ghost_ok = (ghost.get("ok") and ghost.get("value") == ghost.get("payload")
                    and ghost.get("before") == ghost.get("after"))
        _check(checks, "ghost_fill", "ghost chip fills the composer without sending",
               ghost_ok, f"payload={_excerpt(ghost.get('payload'), 80)} "
                         f"filled={ghost.get('value') == ghost.get('payload')} "
                         f"msg_delta={(ghost.get('after') or 0) - (ghost.get('before') or 0)}")

        metrics["chat"] = cdp.js(OVERFLOW_EXPR)
        ok, detail = overflow_verdict(metrics["chat"])
        _check(checks, "overflow_chat", "no horizontal overflow at 390 px (chat)",
               ok, detail)

        baseline = cdp.js(THREAD_EXPR)
        marker = f"Browser e2e {stamp}: reply with the single word READY."
        if include_writes:
            cdp.eval("(() => {const i = document.querySelector('#msg'); i.value = %s;"
                     "document.querySelector('#composer').requestSubmit();})()"
                     % json.dumps(marker))
            reply = _wait(cdp, THREAD_EXPR,
                          lambda r: (r.get("assistants") or 0) > (baseline.get("assistants") or 0)
                          and not r.get("typing")
                          and len((r.get("text") or "").strip()) > 0,
                          chat_timeout, interval=1.0)
            text = (reply.get("text") or "").strip()
            real = bool(text) and text not in ("(no reply)", "…")
            _check(checks, "chat_reply", "chat send returns a real brain reply",
                   real, f"reply={_excerpt(text, 200)} "
                         f"assistants={reply.get('assistants')} notes={reply.get('notes')}")
            status, thread = _api(base, token, f"/api/ws/agents/{slug}")
            bodies = [m.get("body") or "" for m in (thread or {}).get("messages") or []]
            _check(checks, "chat_persisted", "sent message persisted in the thread",
                   status == 200 and any(marker in b for b in bodies),
                   f"marker_present={any(marker in b for b in bodies)} scanned={len(bodies)}")
        else:
            _check(checks, "chat_reply", "chat send returns a real brain reply",
                   False, "skipped by --no-writes", skipped=True)
            _check(checks, "chat_persisted", "sent message persisted in the thread",
                   False, "skipped by --no-writes", skipped=True)

        cdp.eval("document.querySelector('.tabs button[data-tab=\"peers\"]').click()")
        peers = _wait(cdp, PEERS_EXPR, lambda r: r.get("visible") is True, 20)
        peers_ok = (peers.get("visible") and peers.get("threadHidden")
                    and peers.get("options", 0) >= 1)
        _check(checks, "peer_tab", "peer tab renders form and bus view",
               peers_ok, f"options={peers.get('options')} rows={peers.get('rows')} "
                         f"empty={_excerpt(peers.get('empty'), 80)}")
        metrics["peers"] = cdp.js(OVERFLOW_EXPR)
        ok, detail = overflow_verdict(metrics["peers"])
        _check(checks, "overflow_peers", "no horizontal overflow at 390 px (peers)",
               ok, detail)

        cdp.eval("document.querySelector('.tabs button[data-tab=\"chat\"]').click()")
        time.sleep(0.5)
        shots.append(_shot(cdp, out_dir, stamp, "chat"))

        events = cdp.drain()
        for ev in events:
            found = console_error(ev)
            if found:
                errors.append({"kind": found[0], "detail": found[1]})
            if ev.get("method") == "Network.responseReceived":
                resp = (ev.get("params") or {}).get("response") or {}
                if (resp.get("status") or 0) >= 400:
                    errors.append({"kind": "http", "detail":
                        f"HTTP {resp.get('status')} {resp.get('url')}"})
        _check(checks, "console_errors", "no console errors or uncaught exceptions",
               not errors, f"errors={len(errors)} {errors[:3]}")

        metrics["version"] = {"browser": version.get("Browser", ""),
                              "protocol": version.get("Protocol-Version", "")}
    finally:
        if cdp:
            cdp.close()
        if not keep_browser:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(prof, ignore_errors=True)

    summary = summarize(checks)
    evidence = {
        "timestamp": stamp, "base": base, "viewport": VIEWPORT,
        "browser": (metrics.get("version") or {}).get("browser", ""),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "summary": summary, "checks": checks, "console_errors": errors,
        "screenshots": [{"name": n, "path": os.path.relpath(p, ROOT),
                         "bytes": os.path.getsize(p)}
                        for n, p in shots if p and os.path.exists(p)],
        "metrics": {k: v for k, v in metrics.items() if k != "version"},
    }
    return evidence


def _shot(cdp, out_dir, stamp, name):
    """Capture a viewport PNG; return (name, absolute path)."""
    os.makedirs(out_dir, exist_ok=True)
    out = cdp.send("Page.captureScreenshot", {"format": "png",
                                             "captureBeyondViewport": False})
    data = base64.b64decode(out["result"]["data"])
    path = os.path.join(out_dir, f"browser-e2e-{stamp}-{name}.png")
    latest = os.path.join(out_dir, f"browser-e2e-latest-{name}.png")
    for target in (path, latest):
        with open(target, "wb") as f:
            f.write(data)
    return name, path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--out", default=DEFAULT_EVIDENCE)
    ap.add_argument("--chrome", default="")
    ap.add_argument("--chat-timeout", type=int, default=180)
    ap.add_argument("--no-writes", action="store_true")
    ap.add_argument("--keep-browser", action="store_true")
    args = ap.parse_args(argv)

    token = load_token()
    if not token:
        print("no AGENT_MANAGER_TOKEN in .env", file=sys.stderr)
        return 2
    evidence = run_browser_e2e(
        base=args.base, token=token, include_writes=not args.no_writes,
        chrome=args.chrome, chat_timeout=args.chat_timeout, out_dir=args.out,
        keep_browser=args.keep_browser)
    path, latest = write_evidence(evidence, args.out, evidence.get("timestamp"))
    s = evidence.get("summary") or summarize(evidence.get("checks") or [])
    print(f"browser e2e {s['passed']}/{s['total']} passed, "
          f"{s.get('failed')} failed, {s.get('skipped')} skipped, "
          f"{evidence.get('elapsed_ms')} ms")
    for c in evidence.get("checks") or []:
        flag = "SKIP" if c.get("skipped") else ("ok" if c.get("ok") else "FAIL")
        print(f"  [{flag}] {c['id']}: {c.get('detail', '')}")
    print(f"evidence: {path}")
    print(f"latest:   {latest}")
    return exit_code(evidence)


if __name__ == "__main__":
    sys.exit(main())
