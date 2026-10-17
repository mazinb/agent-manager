---
name: phone-harness
description: Drive the user's real iPhone on the Mac mini via phone-harness (iPhone Mirroring). Use when a task needs taps, screenshots, OCR, app navigation, or reading on-screen OTPs/SMS. Not available on the hosted brain server — only on the self-hosted Mac.
---

# phone-harness (Mac mini)

Phone control is **machine-local**. The shared `agent-manager` MCP brain does not execute device ops. On **zoro's Mac mini**, agents shell out to the CLI (same pattern as Hermes `phone_exec`).

## Preconditions

```bash
export PATH="$HOME/.local/bin:$PATH"
phone-harness doctor ios    # all capture checks PASS; session state ready
```

If `session.state` is `blocked`, clear the iPhone Mirroring interstitial on the Mac (often iCloud / Connect / phone unlocked). Never type a PIN.

## Call pattern

```bash
phone-harness <<'PY'
ensure_device()
print(connection_state())
print([o["text"] for o in screen()][:20])
# open_app("Messages"); wait_for_text("code"); …
PY
```

`phone-exec` is a thin PATH wrapper around the same CLI.

Helpers (full list: `phone-harness skill`): `ensure_device`, `screen`, `screenshot`, `find_text` / `tap_text`, `tap`, `type_text`, `open_app`, `swipe` / `scroll`, `home`, `wait_for_text`.

## Agent-manager usage

1. Claim or receive an on-device task that needs the phone (Hermes ticks, or any agent on this Mac).
2. Run the CLI above in the Mac mini environment (Cursor self-hosted worker, Terminal, or Hermes with the phone-harness plugin).
3. Save outcomes with MCP `note` (`project: phone-control` or the task's project). Do not store OTPs, passwords, or Apple credentials in the brain.

## Limits

- Personal iPhone path uses **iPhone Mirroring** (no Xcode app install, no Developer portal UDID for the harness itself).
- Unlock / Face ID / iCloud prompts need the human.
- Never type passwords, PINs, or 2FA codes — read them from the screen and hand control back when the user must enter secrets.
