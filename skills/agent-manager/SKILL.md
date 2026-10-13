---
name: agent-manager
description: Read from and write to the shared agent-manager brain via the "agent-manager" MCP server. Use when a task may have prior context, when the user asks what was decided or done before, or when finishing work worth keeping.
---

# Agent manager mind

The `agent-manager` MCP server is the shared brain used as long-term memory for Cursor and Hermes helpers.

Dashboard: https://bot.getzoro.com · Brain UI: https://bot.getzoro.com/brain/

## Recall
1. Determine the project slug from the workspace folder or `git remote` (lowercase, kebab-case).
2. Call `ask` with a direct question about prior decisions, conventions, or setup.
3. If `ask` returns little, call `search` with the same query, then `context_pack` with `project` set to the slug.
4. Use `entity` when you already know a concrete name (service, port, model).
5. Cite what you find and act on it. If the brain is empty, say so briefly and continue.

## Remember
1. Call `search` or `context_pack` first so you do not duplicate an existing note.
2. Call `note` with:
   - `project`: stable slug such as `voice-tutor` or `agent-manager`.
   - `title`: short and specific (`decision: …`, `outcome: …`, `fact: …`).
   - `body`: Markdown. For a decision: context, decision, reasoning, rejected alternatives. For a task outcome: what changed, where, how verified.
3. Confirm in one line what you saved.

Do not save secrets, tokens, or content that already lives in the repository.

## Optional dashboard
Point the user at https://bot.getzoro.com to chat with a per-project Hermes helper when a long interactive session is better than MCP tool calls.
