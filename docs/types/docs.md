# Docs

A page that explains a system that exists: an architecture page, a walkthrough, a runbook, a setup guide or a change proposal.

![The acme-orders page: the order path canvas zoomed into the orders-api system, playing step 3 of the Create one order flow](../media/docs-hero.webp)

## Features

- **Blueprint canvas.** The system is a zoomable drawing. Edges run at right angles, routed around the nodes, and their labels don't overlap.
- **Nested systems.** A node with children is a system: double-click it, or zoom in, to see its parts on their own sheet. Systems nest 3 levels deep; crumbs and Esc go back up.
- **Flows.** Each level plays its own animated flows (a request, an event, a data path), one step per edge, with a line of text per step. Pick a flow from the canvas header, step through it with ‹ ›, or pause it.
- **Edge kinds and states.** Edges show what moves: data, control, async events, power, dependencies. Nodes marked `proposed` or `removed` look different from live parts.
- **Checklists as task trackers.** Each procedure is a checklist; each row is the action and why it matters, and opens to show the command, the check, tables or a sub-checklist. Ticks are kept by the local server. **Copy progress** exports Markdown for a PR or an issue.
- **Links from text to the drawing.** A checklist item or a table cell can open a node on the canvas.
- **Comments.** Point at any element, select a passage or draw on the page to leave a note; notes collect in the **Comments** tab (Pending, Open, Resolved). **Request changes** sends them to the agent. When the agent lists a comment's id in a revision's `resolves`, the comment turns Resolved on the next load.
- **Decisions and answers.** Items that need a choice show options as pills with the agent's pick starred. **Accept recommended** takes every starred option. **Send answers** sends picks, ticks and item comments to the agent.
- **Revisions.** The **Revisions** tab lists every build of the doc. Compare any two: new, changed and removed sections, items, rows and canvas parts are marked in place, with a word-level diff.

## How an agent makes one

```sh
python3 <skill>/scripts/build.py new docs docs/orders/order-path.bluedoc.json --title "Order path" --kind Architecture
python3 <skill>/scripts/build.py docs/orders/order-path.bluedoc.json        # validate, lint, record the revision
python3 <skill>/scripts/serve.py open docs/orders/order-path.bluedoc.json   # print the URL with a one-time key
```

The agent fills the skeleton's `<<…>>` fields between the first two commands. `--kind` is `Architecture`, `Walkthrough`, `Runbook`, `Setup` or `Change`.

## Example and guide

- Example: [`acme-orders.bluedoc.json`](../../skills/bluedoc/examples/acme-orders.bluedoc.json), the Acme order path from checkout to pick ticket, with a runbook for the local stack. Built page: [`acme-orders.html`](../examples/acme-orders.html) (download it, then open it).
- Agent guide: [`skills/bluedoc/types/docs.md`](../../skills/bluedoc/types/docs.md).
