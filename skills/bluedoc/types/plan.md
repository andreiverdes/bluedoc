# Plan

**When:** whenever you would hand the user a plan before implementing (plan mode, "make a plan", "propose a plan", a design doc) and they can open a browser. Save it as `docs/plans/<topic>.bluedoc.json` unless the repo keeps plans elsewhere. `build.py new plan` sets `meta.kind: "Plan"`, so the page shows a status chip (Awaiting approval, Changes requested, Approved · rev X, Changes since approved rev X) and an **Approve plan** key. Plans have no Send answers: the reader's picks travel with **Approve plan** or **Request changes**.

**Home card:** a step timeline (a status dot and an effort bar per step) and the A/M/D/R file counts.
**Required** (an error on a new rev, a warning on older ones): a `steps` block and a `files` block.

## Layout

| Section | Holds |
|---|---|
| Goal (`tldr`) | What ships, for whom, in how many steps, and how many questions need a pick. |
| Context | The current state and why it has to change: a canvas of today's system, or short text with `path:line` anchors. |
| Approach | The proposal: a canvas with new parts `state: "proposed"` and removed ones `removed`; a `compare` block for before/after (API response, schema, UI); `media` blocks for mockups or wireframes. |
| Steps | One `steps` block in implementation order. Each step is one reviewable change: imperative title, `effort` S/M/L, `md` with the detail, the `files` it touches, `refs` to the canvas. |
| Files | One `files` block: every path the plan adds, edits, deletes, renames or moves, with `why` and the `step` that touches it. |
| Open questions | A decision list (`numbered: false`): one item per choice the reader must make, each with `choices`. `text` is the question; `sub` is "Recommend <option>: <reason>."; each option's `md` explains it. |
| Risks | A table: Risk, Likelihood, Impact, Mitigation. |
| Verification | A progress list: plain steps, each with `verify` (and `code` when there's a command): how you'll show the plan worked. |

## Rules

- Keep each path identical in the step's `files` and the `files` block; the build warns on a mismatch.
- Leave every step `status: "todo"` until its work lands; then `build.py patch <doc> step:steps/0/<stepId> --set status=done`, with `--json '{"evidence": […]}'` when you have proof: the test command and its result, a screenshot beside the doc, a link to a log or review doc (`references/schema.md` `### Evidence`). Evidence is optional; never invent it. Tick verification checks the same way: `item:<checklist>/<item> --set done=true`.
- Record evidence right after running its check, through `patch`, so it is pinned to the commit (and any uncommitted changes) it checked; add `--paths` for what the check covers, so later commits elsewhere leave it valid. When you change code a check covers, run the check again and re-record: `build.py patch <doc> <key> --pin` (update its `md` if the result changed). The page marks evidence the code has moved past as stale and doesn't count that check as done; an approval or change request lists such checks under `## Stale evidence` with these commands (`#### Pinned evidence` in `references/schema.md`).
- Never mix questions and work in one checklist: the build rejects a list where some items have `choices` and others don't.
- Canvases: ≤ 9 nodes per level, never draw a proposed part as if it exists. The full canvas rules are under "Canvas rules" in `types/docs.md`.
- Every open question gets a `recommend`. Never set `choice` yourself.
- Every option gets an `md` explanation, 1–3 sentences: what picking it means and what it costs (time, risk, what it rules out). The page shows it on the option's row; the build fails without it. Keep the evidence for the recommendation in `detail`.
- A question where several answers make sense (which stores, which platforms) gets `multi: true`; `recommend` may then be a list of ids.
- Answer a reader's comment on an item with `build.py patch <doc> item:<checklist>/<item> --reply "…"` (a pin or general comment: `ann:<id>`), not by rewriting the item; change the item only when the answer changes the question or its options.
- Draw SVG mockups that read on light and dark pages: a neutral palette, or a `prefers-color-scheme` style block inside the SVG.

## Approval loop

1. Validate, `serve.py open <doc> --to <your name>`, give the user the URL.
2. Run `serve.py wait <doc> --kind any` in the background.
3. **Approval** (`--- bluedoc approval … ---`): implement exactly the approved rev. Use the reader's picks; an open question with no pick means your recommendation. The notes sent with the approval are binding instructions.
4. **Change request**: revise the plan (`build.py patch`, which bumps `meta.rev` and writes `changes`; `--resolves <id>` per comment you addressed), send `<url>?diff=<previous rev>`, wait again. Picks sent with it are the reader's decisions so far: carry them over as `choice`. A question marked **Need more details** gets a `--reply` and sharper options with fuller explanations, and stays unpicked. A change request on an approved plan that carries a different pick ("Pick changed since approval") is a change like any other: record the new `choice`, and the plan needs approval again.
5. Never start implementing before an approval of the current rev. Marking progress after the approval keeps it approved: steps' `status` and `evidence`, checklist `done` and `evidence`, the approved picks as `choice`, and `--reply` answers, each in a patch that bumps past the approved rev (bump on the first, `--no-bump` on the rest). Any other edit needs approval again, and so does `--no-bump` on the approved rev itself, which rewrites what was approved.

## Fragment

```json
{ "type": "steps", "id": "plan", "title": "Implementation order", "items": [
  { "id": "table", "title": "Add the `saved_carts` table", "status": "todo", "effort": "S",
    "md": "New table only, so the migration takes no lock on `carts`.",
    "files": ["services/orders-api/migrations/0012_saved_carts.sql"], "refs": ["arch/savedtbl"] } ] },
{ "type": "files", "title": "Changed files", "items": [
  { "path": "services/orders-api/migrations/0012_saved_carts.sql", "action": "add", "why": "Creates `saved_carts`.", "step": "table" },
  { "path": "web/src/cart/sessionCartStorage.ts", "action": "rename", "from": "web/src/cart/cartStorage.ts", "why": "Holds only the session cart now.", "step": "table" } ] },
{ "type": "checklist", "id": "decisions", "title": "Open questions", "numbered": false, "items": [
  { "id": "retention", "text": "How long do saved carts live?", "sub": "Recommend 180 days: covers a seasonal reorder.",
    "recommend": "d180", "choices": [
      { "id": "d90", "label": "90 days", "md": "About half the rows. A customer who reorders every half year finds the cart gone." },
      { "id": "d180", "label": "180 days", "md": "Covers 70 % of business reorders; about 1.8 GB." },
      { "id": "forever", "label": "Until deleted", "md": "No sweeper; the 20-cart limit is the only cap." } ] },
  { "id": "guests", "text": "Who can save a cart?", "sub": "Recommend personal and business accounts: both have an account.",
    "multi": true, "recommend": ["accounts", "business"], "choices": [
      { "id": "accounts", "label": "Personal accounts", "md": "Shoppers signed in to their own account; no extra work." },
      { "id": "business", "label": "Business accounts", "md": "Each buyer saves their own carts; no extra work." },
      { "id": "email", "label": "Guests, by email link", "md": "An email token flow and a mail template, about 3 more days." } ] } ] }
```

Field details: grep `## Plan blocks`, `### Steps`, `### Files`, `### Compare`, `### Media` in `references/schema.md`.
