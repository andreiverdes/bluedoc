# Plan

A plan the agent writes before it writes code; you approve it or send it back on the page.

![The acme-saved-carts-plan page: three open questions with the recommended options starred, one picked, an item comment, and Request changes and Approve plan in the bottom tray](../media/plan-hero.webp)

## Features

- **One page per plan.** The goal, the current state, the proposed design on a canvas, before/after panes, mockups, a numbered timeline of steps with effort, the files each step touches, open questions, risks and checks.
- **Status chip.** The header shows **Awaiting approval**, **Changes requested** or **Approved · rev X**.
- **Open questions with a recommendation.** Each question shows its options as pills with the agent's recommendation starred. Pick one, or press **Accept recommended** to take every starred option.
- **Need more details.** A toggle after each question's pills asks the agent to explain it further; the comment box says what is missing. Approval waits until no question asks for more details.
- **Item comments.** Each step and question takes a comment. An item comment counts toward **Request changes**, so a comment alone is enough to send the plan back.
- **Comments on any part.** Point at an element, select a passage or draw on the page. Notes collect in the **Comments** tab as Pending, then Open once sent. When the agent lists a comment's id in a revision's `resolves`, the comment turns Resolved.
- **Request changes or Approve plan.** Both send your picks and notes to the agent. The agent revises on a change request and starts coding only after **Approve plan** on the current revision; any edit to the plan resets the approval.
- **Revisions.** The **Revisions** tab shows each revision with the agent's note on what changed. Compare two to see new, changed and removed steps, questions and rows marked in place.

## How an agent makes one

```sh
python3 <skill>/scripts/build.py new plan docs/plans/saved-carts.bluedoc.json --title "Saved carts"
python3 <skill>/scripts/build.py docs/plans/saved-carts.bluedoc.json                     # validate, record the revision
python3 <skill>/scripts/serve.py open docs/plans/saved-carts.bluedoc.json --to <agent>   # print the URL
python3 <skill>/scripts/serve.py wait docs/plans/saved-carts.bluedoc.json --kind any     # wait for approval or changes
```

On a change request the agent edits one object at a time with `build.py patch <doc> <key> … --resolves <comment id>`, which bumps the revision.

## Example and guide

- Example: [`acme-saved-carts-plan.bluedoc.json`](../../skills/bluedoc/examples/acme-saved-carts-plan.bluedoc.json), a 7-step plan for saved carts in the Acme shop. Built page: [`acme-saved-carts-plan.html`](../examples/acme-saved-carts-plan.html) (download it, then open it).
- Agent guide: [`skills/bluedoc/types/plan.md`](../../skills/bluedoc/types/plan.md).
