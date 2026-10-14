#!/usr/bin/env bash
# npm-sync-check — answers "does agent-manager-brain on npm need republishing?"
#
# The npm package is a thin wrapper: serve/init/setup clone THIS repo at
# runtime, so brain logic can never go stale on npm. Only npm/cli.js,
# npm/README.md and the API endpoints the CLI calls are frozen at publish
# time. This script diffs the PUBLISHED TARBALL against the repo — the
# definitive test, immune to version-number games.
#
# Usage: scripts/npm-sync-check.sh
# Exit 0 = in sync · 1 = publish needed / broken · 2 = cannot check (offline)
set -uo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

fail=0

REG=$(npm view agent-manager-brain version 2>/dev/null) || true
if [ -z "${REG:-}" ]; then
  echo "?  cannot reach npm registry — run again when online"; exit 2
fi
LOC=$(python3 -c "import json;print(json.load(open('npm/package.json'))['version'])")
PYV=$(python3 - <<'EOF' 2>/dev/null || true
import tomllib
print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])
EOF
)
echo "npm/package.json : $LOC"
echo "npm registry     : $REG"
echo "pyproject.toml   : ${PYV:-?}  (keep aligned with npm when bumping)"
[ -n "${PYV:-}" ] && [ "$PYV" != "$LOC" ] && \
  echo "NOTE: pyproject $PYV != npm $LOC"

# 1) definitive content check: published tarball vs repo npm/
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
(cd "$TMP" && npm pack "agent-manager-brain@$REG" >/dev/null 2>&1 && tar xzf *.tgz) || {
  echo "?  could not download tarball"; exit 2; }
for f in cli.js README.md; do
  if diff -q "$TMP/package/$f" "npm/$f" >/dev/null 2>&1; then
    echo "OK  published $f == repo npm/$f"
  else
    echo "NEEDS PUBLISH: published $f differs from repo npm/$f"
    fail=1
  fi
done

# 2) CLI-relied endpoints still present in server.py (catches breakage
#    even when content matches — a renamed route would strand npx users)
for ep in /api/ask /api/search /api/context /api/note /api/stats /api/setup/status /api/refresh /mcp; do
  grep -q "\"$ep\"" server.py || { echo "BROKEN: $ep missing from server.py (npm CLI calls it)"; fail=1; }
done
[ $fail -eq 0 ] && echo "OK  all CLI-called endpoints present in server.py"

# 3) how to publish
if [ $fail -ne 0 ]; then
  echo
  echo "To publish: bump \"version\" in npm/package.json, commit, then:"
  echo "  cd npm && npm publish"
fi
exit $fail
