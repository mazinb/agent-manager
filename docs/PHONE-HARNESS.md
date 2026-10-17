# Phone harness (self-hosted Mac)

On-device phone control for agents that run on **zoro's Mac mini**.

| Piece | Detail |
|-------|--------|
| Install | `uv tool install --python 3.12 phone-harness` → `~/.local/bin/phone-harness` |
| Bridge | CLI: `phone-harness <<'PY' … PY` (wrapper: `phone-exec`) |
| Skill | [`skills/phone-harness/SKILL.md`](../skills/phone-harness/SKILL.md) |
| Upstream | https://github.com/ShawnPana/phone-harness |

The hosted brain (`bot.getzoro.com`) does **not** proxy taps. Hermes (or Cursor on the Mac) executes the CLI after claiming board work. Register the skill with `phone-harness skill` into your agent's skills dir after upgrades.
