#!/usr/bin/env bash
# Cursor ↔ Hermes peer bus helpers (no token echo).
#   peer.sh handoff <task-slug> <body...>
#   peer.sh status              # messages to cursor
#   peer.sh for hermes|cursor
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENVF="$ROOT/.env"
TOK=$(grep -m1 '^AGENT_MANAGER_TOKEN=' "$ENVF" | cut -d= -f2-)
[[ -n "$TOK" ]] || { echo "no token" >&2; exit 1; }
API="${PEER_API:-http://127.0.0.1:8075}"

mcp() {
  local name="$1" args="$2"
  curl -sS -H "X-Token: $TOK" -H 'Content-Type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"$name\",\"arguments\":$args}}" \
    "$API/mcp" | python3 -c '
import json,sys
o=json.load(sys.stdin)
t=o["result"]["content"][0]["text"]
if o["result"].get("isError"):
  sys.exit(t)
print(t)
'
}

cmd="${1:-status}"
shift || true
case "$cmd" in
  handoff)
    task="${1:?task slug}"; shift
    body="${*:?body}"
    text="role: handoff
task: $task
do: $body
done when: you reply role: done on peers"
    mcp message_peer "$(python3 -c 'import json,sys; print(json.dumps({"agent":"cursor","to_agent":"hermes","title":"handoff-"+sys.argv[1],"body":sys.argv[2]}))' "$task" "$text")"
    ;;
  plan)
    task="${1:?task slug}"; shift
    body="${*:?body}"
    text="role: plan
task: $task
$body"
    mcp message_peer "$(python3 -c 'import json,sys; print(json.dumps({"agent":"cursor","to_agent":"hermes","title":"plan-"+sys.argv[1],"body":sys.argv[2]}))' "$task" "$text")"
    ;;
  status|inbox)
    mcp peer_inbox '{"to_agent":"cursor","limit":20}'
    ;;
  for)
    who="${1:?hermes|cursor}"
    mcp peer_inbox "$(python3 -c 'import json,sys; print(json.dumps({"to_agent":sys.argv[1],"limit":20}))' "$who")"
    ;;
  *)
    echo "usage: peer.sh handoff|plan|status|for …" >&2
    exit 2
    ;;
esac
