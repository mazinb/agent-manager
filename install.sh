#!/usr/bin/env bash
# Install per-project helper agents: one Hermes profile per project.
# Each profile gets SOUL.md (persistent identity/context) and a <project>-ops
# skill (operating manual). Idempotent — re-runs refresh SOUL + skill in place.
#
# Usage: bash install.sh [project ...]    # default: every staged project
set -euo pipefail

AG=/home/mazin/projects/agent-manager
STAGING=$AG/staging
HERMES=/home/mazin/.local/bin/hermes
PROFILES=/home/mazin/.hermes/profiles

projects=("$@")
if [ ${#projects[@]} -eq 0 ]; then
  projects=($(cd "$STAGING" && ls -d */ 2>/dev/null | tr -d /))
fi

for p in "${projects[@]}"; do
  sdir="$STAGING/$p"
  if [ ! -f "$sdir/SOUL.md" ] || [ ! -f "$sdir/SKILL.md" ]; then
    echo "skip $p (staging incomplete: need SOUL.md + SKILL.md)"
    continue
  fi
  if [ ! -d "$PROFILES/$p" ]; then
    "$HERMES" profile create "$p" --no-alias \
      --description "Helper agent for the $p project on the GB10 box." >/dev/null
    echo "created profile $p"
  fi
  cp "$sdir/SOUL.md" "$PROFILES/$p/SOUL.md"
  mkdir -p "$PROFILES/$p/skills/${p}-ops"
  cp "$sdir/SKILL.md" "$PROFILES/$p/skills/${p}-ops/SKILL.md"
  echo "installed $p: SOUL.md + ${p}-ops skill"
done

echo "done. chat with a helper: hermes -p <project> chat"
