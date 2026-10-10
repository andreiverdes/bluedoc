# Plan

**When:** whenever you would hand the user a plan before implementing (plan mode, "make a plan", "propose a plan", a design doc) and they can open a browser. Save it as `docs/plans/<topic>.bluedoc.json` unless the repo keeps plans elsewhere. `build.py new plan` sets `meta.kind: "Plan"`, so the page shows a status chip (Awaiting approval, Changes requested, Approved · rev X) and an **Approve plan** key. Plans have no Send answers: the reader's picks travel with **Approve plan** or **Request changes**.

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
| Open questions | A checklist (`numbered: false`) of decision items, one per choice the reader must make. `text` is the question; `sub` is "Recommend <option>: <reason>." |
| Risks | A table: Risk, Likelihood, Impact, Mitigation. |
| Verification | A checklist of plain steps, each with `verify` (and `code` when there's a command): how you'll show the plan worked. |

## Rules

- Keep each path identical in the step's `files` and the `files` block; the build warns on a mismatch.
- Leave every step `status: "todo"` until its work lands; then `build.py patch <doc> step:steps/0/<stepId> --set status=done`.
- Canvases: ≤ 9 nodes per level, never draw a proposed part as if it exists. The full canvas rules are under "Canvas rules" in `types/docs.md`.
- Every open question gets a `recommend`. Never set `choice` yourself.
- Draw SVG mockups that read on light and dark pages: a neutral palette, or a `prefers-color-scheme` style block inside the SVG.

## Approval loop

1. Validate, `serve.py open <doc> --to <your name>`, give the user the URL.
2. Run `serve.py wait <doc> --kind any` in the background.
3. **Approval** (`--- bluedoc approval … ---`): implement exactly the approved rev. Use the reader's picks; an open question with no pick means your recommendation. The notes sent with the approval are binding instructions.
4. **Change request**: revise the plan (`build.py patch`, which bumps `meta.rev` and writes `changes`; `--resolves <id>` per comment you addressed), send `<url>?diff=<previous rev>`, wait again. Picks sent with it are the reader's decisions so far: carry them over as `choice`.
5. Never start implementing before an approval of the current rev. A new rev, or any edit of the JSON after the approval, resets it.

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
    "recommend": "d180", "choices": [ { "id": "d90", "label": "90 days" }, { "id": "d180", "label": "180 days" }, { "id": "forever", "label": "Until deleted" } ] } ] }
```

Field details: grep `## Plan blocks`, `### Steps`, `### Files`, `### Compare`, `### Media` in `references/schema.md`.
