# Phone harness (self-hosted Mac)

On-device phone control for agents that run on **zoro's Mac mini**.

| Piece | Detail |
|-------|--------|
| Install | `uv tool install --python 3.12 phone-harness` → `~/.local/bin/phone-harness` |
| Bridge | CLI: `phone-harness <<'PY' … PY` (wrapper: `phone-exec`) |
| Skill | [`skills/phone-harness/SKILL.md`](../skills/phone-harness/SKILL.md) |
| Upstream | https://github.com/ShawnPana/phone-harness |

The hosted brain (`bot.getzoro.com`) does **not** proxy taps. Hermes (or Cursor on the Mac) executes the CLI after claiming board work. Register the skill with `phone-harness skill` into your agent's skills dir after upgrades.

## Remote agents (register, don't execute)

Agents elsewhere (Cloud Cursor, other Hermes hosts, Grok, …) request phone work through the **peers board**. They never call `phone-harness` on their own machine.

| Path | Call |
|------|------|
| Preferred stub | MCP `request_phone(do=…, done_when=…, from_agent=<you>)` |
| Board equivalent | `add_task(title="on-device: …", body=…, chat=peers)` — brief routes `on-device` → hermes |
| Explicit | `add_task(…, assignee="hermes")` |
| Ad-hoc | `message_peer` handoff to `hermes` (`role: handoff`) |

Mac Hermes picks up via `board_tick` / `agent_poll` (skill `agent-manager-tick`), runs the local CLI, then `update_task(done)` + peers `role: done`. No OTPs or credentials in the brain.
