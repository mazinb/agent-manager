#!/usr/bin/env python3
"""agent-manager CLI: refresh the brain, serve the unified app, ask questions."""
import argparse
import json
import os
import runpy
import sys

DEFAULT_CONFIG = os.path.expanduser("~/.config/agent-manager/config.json")
LEGACY_CONFIG = os.path.expanduser("~/.config/agent-context/config.json")


def resolve_config(path):
    if path and os.path.isfile(path):
        return path
    if os.path.isfile(DEFAULT_CONFIG):
        return DEFAULT_CONFIG
    if os.path.isfile(LEGACY_CONFIG):
        return LEGACY_CONFIG
    return path or DEFAULT_CONFIG


def load(path):
    with open(path) as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(prog="agent-manager")
    ap.add_argument("--config", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("refresh")
    sp = sub.add_parser("serve", help="unified chat + brain + mcp server")
    sp.add_argument("--port", type=int, default=None)
    qp = sub.add_parser("query")
    qp.add_argument("q")
    kp = sub.add_parser("ask")
    kp.add_argument("q")
    kp.add_argument("--no-llm", action="store_true")
    cp = sub.add_parser("pack")
    cp.add_argument("project")
    sub.add_parser("mcp", help="run the MCP server on stdio")
    np = sub.add_parser("note", help="write a note into the brain")
    np.add_argument("--project", required=True)
    np.add_argument("--title", default="untitled")
    np.add_argument("--body", required=True)
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    from agent_context import pipeline, query, store  # noqa: E402
    from agent_context import llm as llm_mod  # noqa: E402

    cfg_path = resolve_config(args.config)
    if args.cmd == "serve":
        if args.port:
            os.environ["AGENT_MANAGER_PORT"] = str(args.port)
        os.environ["AGENT_MANAGER_CONFIG"] = cfg_path
        runpy.run_path(os.path.join(root, "server.py"), run_name="__main__")
        return

    config = load(cfg_path)
    config["db_path"] = os.path.expanduser(config.get(
        "db_path", "~/.local/share/agent-manager/brain.db"))
    con = store.connect(config["db_path"])

    if args.cmd == "refresh":
        def progress(i, total):
            print(f"\r  {i}/{total or '?'}", end="", flush=True)
        result = pipeline.refresh(con, config, progress=progress)
        print("\n", json.dumps(result))
    elif args.cmd == "query":
        print(json.dumps(query.search(con, args.q), indent=2))
    elif args.cmd == "ask":
        chunks = query.search(con, args.q)
        answer = None
        if not args.no_llm:
            lc = config.get("llm") or {}
            if lc.get("base_url"):
                answer = llm_mod.ask(lc["base_url"], lc.get("model", ""),
                                     args.q, chunks)
        if answer:
            print(answer + "\n\n--- sources ---")
        for c in chunks:
            print(f"[{c['project']}/{c['kind']}] {c['path']}"
                  f" :: {(c['heading'] or '')[:60]}")
    elif args.cmd == "pack":
        print(query.context_pack(con, args.project))
    elif args.cmd == "mcp":
        from agent_context.server import Brain
        from agent_context.mcp import serve_stdio
        serve_stdio(Brain(config))
    elif args.cmd == "note":
        from agent_context.mcp import TOOL_FUNCS
        from agent_context.server import Brain
        print(json.dumps(TOOL_FUNCS["note"](
            Brain(config), {"project": args.project,
                            "title": args.title, "body": args.body})))


if __name__ == "__main__":
    main()
