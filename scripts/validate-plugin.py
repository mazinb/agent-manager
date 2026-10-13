#!/usr/bin/env python3
"""Validate Cursor plugin packaging for marketplace submission."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errs: list[str] = []
    for rel in (".cursor-plugin/plugin.json", "mcp.json"):
        try:
            json.loads((ROOT / rel).read_text())
        except Exception as exc:  # noqa: BLE001
            errs.append(f"{rel}: {exc}")

    manifest = json.loads((ROOT / ".cursor-plugin/plugin.json").read_text())
    for key in (
        "name",
        "version",
        "description",
        "author",
        "logo",
        "rules",
        "skills",
        "commands",
        "mcpServers",
        "variables",
    ):
        if key not in manifest:
            errs.append(f"missing manifest field: {key}")

    name = manifest.get("name", "")
    if not re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?", name or ""):
        errs.append(f"invalid plugin name: {name!r}")

    logo = ROOT / manifest.get("logo", "")
    if not logo.is_file():
        errs.append(f"missing logo: {logo}")

    for path in (
        list((ROOT / "rules").glob("*.mdc"))
        + list((ROOT / "commands").glob("*.md"))
        + list((ROOT / "skills").rglob("SKILL.md"))
    ):
        text = path.read_text()
        if not text.startswith("---") or text.find("\n---", 3) < 0:
            errs.append(f"bad frontmatter: {path.relative_to(ROOT)}")

    mcp = json.loads((ROOT / "mcp.json").read_text())
    used = set(re.findall(r"\$\{([A-Z0-9_]+)\}", json.dumps(mcp)))
    declared = set(manifest.get("variables", {}).get("properties", {}))
    missing = used - declared
    if missing:
        errs.append(f"undeclared variables: {sorted(missing)}")

    if errs:
        print("FAIL")
        for err in errs:
            print(f"- {err}")
        return 1

    print("PASS")
    print(f"name={name} version={manifest.get('version')} vars={sorted(declared)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
