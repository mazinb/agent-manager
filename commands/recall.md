---
name: recall
description: Pull context relevant to the current task from the agent-manager shared brain.
---

Query the agent-manager brain for context relevant to the current task:

1. Determine the project slug and topic from the open files and the conversation.
2. Call `ask` with a focused question.
3. If the answer is thin, call `search`, then `context_pack` with `project` set to the slug.
4. Summarize what the brain holds: prior decisions, outcomes, open follow-ups, and stated preferences. Say plainly if it holds nothing yet.
