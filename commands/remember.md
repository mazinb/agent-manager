---
name: remember
description: Save the durable result of the current work to the agent-manager shared brain.
---

Save what should outlive this conversation with the `note` tool:

1. Choose a clear `title` prefix: `decision:`, `outcome:`, `fact:`, or `summary:`. Usually one or two notes, not one per message.
2. Call `search` first so you do not duplicate an existing note.
3. Set `project` to the repo/agent slug.
4. Write `body` as Markdown: what was decided or done, why, and how it was verified.
5. Confirm in one or two lines what you saved.

Do not save secrets, transient discussion, or content already in the repository.
