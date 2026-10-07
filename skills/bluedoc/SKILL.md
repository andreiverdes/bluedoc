---
name: bluedoc
description: Generate self-contained HTML engineering docs (architecture pages, walkthroughs, runbooks, setup guides, change proposals, PR reviews) with zoomable blueprint canvases that open into each system's inner architecture and play animated data/control flows, checklists that persist as task trackers, and a code browser that pins review findings to the lines they are about. Use when asked for an HTML doc, architecture page, system walkthrough, runbook, onboarding guide, browsable PR review, or "a bluedoc".
---

# bluedoc

Write one JSON document, build it with `scripts/build.py`, verify it in a browser. The output is one self-contained HTML page: HorizonUI styling, light and dark themes, blueprint canvases, checklists, code review. The template does the rendering; your job is the content and its structure.

Files, relative to this skill's directory (`<skill>` in the commands below):
- `scripts/build.py`: validates structure, lints CRISP slips, inlines the JSON into the template. Python 3.9+, stdlib only.
- `scripts/gitdiff.py`: turns a git range plus `path:line` comments into a `diff` block and writes it into the JSON. Python 3.9+, stdlib only.
- `assets/template.html`: the runtime (canvas engine, checklists, layout, HorizonUI tokens). Never edit it per document.
- `references/schema.md`: every field. Read it before writing the JSON.
- `examples/acme-orders.bluedoc.json`: architecture + runbook (3-level canvas, flows per level, checklist linked to the drawing, troubleshooting). Built page: `examples/acme-orders.html`.
- `examples/acme-pr-review.bluedoc.json`: PR review (verdicts, findings checklist, `diff` block with every finding on its lines). Built page: `examples/acme-pr-review.html`.

## Workflow

1. **Write in CRISP.** If the `crisp` skill is installed, read it and apply it at **CRISP 3** to every string you write: titles, tldr, leads, callouts, node `md`, flow step labels, checklist items. Otherwise apply the ten rules in "Writing" below.
2. **Gather facts from the source.** Read the code, configs, and runs the document describes. Every node, edge, and step must map to something real: a file, a symbol, a queue, a command. Record anchors (`path:line`) for `refs`. Mark what you did not observe as `unverified`.
3. **Plan the structure** (below) before writing JSON.
4. **Write the JSON** next to its output: `docs/<topic>/<name>.bluedoc.json`. Keep the JSON in the repo; it is the source.
5. **Build:**
   ```sh
   python3 <skill>/scripts/build.py docs/<topic>/<name>.bluedoc.json -o docs/<topic>/<name>.html
   ```
   Fix every `ERROR`. Fix every `WARN` unless it is a false positive you can name (e.g. a quoted log line).
6. **Verify in a browser** at 390 px, 1280 px and 1920 px, in light and dark (`prefers-color-scheme`). Check: no console errors; no horizontal scroll; at 1280 px and 1920 px the content column has equal left and right margins (centred on the page) and both rails (Contents/Tracker left, Status/Related right) stay in view beside it while the page scrolls; the root drawing has no overlapping labels; for each system, `BP.zoomTo(canvas, key)` reveals its children and `BP.state(canvas).tokens > 0` while flows play; ticking a checklist item survives a reload. For each `diff` block: `BP.openComment(diff, i)` shows the card on its lines, and ticking the card ticks its checklist item. Look at screenshots of the root and of each opened system, and fix layout before reporting. If the browser cannot open `file://`, serve the folder with `python3 -m http.server` and open it over `http://127.0.0.1`.
7. **Report** the file paths, what you verified, and what stays unverified.

## Structure

Order sections by what the reader needs first:

| Doc kind | Sections, in order |
|---|---|
| Architecture | TL;DR → canvas (the system) → terms → components (cards or table) → decisions (callouts `decision`) → known issues/risks |
| Walkthrough ("how X works") | TL;DR → canvas with one flow per scenario → step-by-step explanation per flow → edge cases |
| Setup / runbook | TL;DR → prerequisites checklist → canvas (what you are building) → procedure checklists → verification → troubleshooting table → teardown checklist |
| Change / proposal | TL;DR → canvas with `state` (`proposed`, `removed`) → what changes (table) → rollout checklist → risks |
| Code review | TL;DR → verdicts (table) → per PR: summary → findings checklist → `diff` block with each finding as a comment → checks run (table) |

Rules:
- **One canvas per system boundary.** Put depth in `children`, not in more canvases. Root ≤ 9 nodes; each level ≤ 9 nodes; nest ≤ 3 levels.
- **Children explain the parent.** A system's children are its real parts (modules, classes, threads, pins). Use `@left`/`@right`/`@top`/`@bottom` ports to show where the parent's outer edges enter and leave.
- **One flow per question.** "How does a request get served?" is a flow. Each step is one edge, one sentence (actor, action, object), and an optional `payload` naming what moves. Every scope that has edges should have at least one flow.
- **Kinds carry meaning.** `data` for payloads, `control` for calls/starts, `async` for queues and events, `power` for hardware supply, `dep` for build/runtime dependencies. Shapes follow the node `kind` table in the schema.
- **State is visible.** Use node `state` and doc `state` chips for anything not live or not verified. Never draw a proposed component as if it exists.
- **Checklists are the task tracker.** Every procedure is a checklist, not a numbered text list. One action per item, imperative verb first, `code` for the command, `verify` for the observable result. Link items to the drawing with `refs` so readers jump from a step to the part it touches.
- **Findings sit on their code.** In a review, every finding with a `path:line` is a checklist item and a comment in that PR's `diff` block (`gitdiff.py --comments`). Diff the commits the reviewer read, not the current tip, and say which in `note`.
- **Tables for comparisons, terms for vocabulary, callouts for risk.** `caution` before a step that can lose data or damage equipment; `warning` before a step that can hurt people or production; place it before the step it guards.

## Writing (CRISP 3)

1. Answer first: `tldr` and each `lead` state the conclusion, not the topic.
2. Say it once: no section repeats another; prose never repeats a table.
3. Keep what changes action: cut sentences whose removal breaks nothing.
4. Plain words, same words: define terms once in a `terms` block; reuse them exactly in labels, steps, and checklists.
5. Name the actor, state the condition: "If the token expired, the server closes the socket."
6. Checkable, not vague: numbers, names, conditions, or "unknown".
7. Structure is earned: the block type matches the content shape.
8. Short is not cryptic: keep commands, risks, real uncertainty.
9. Sound like a colleague: no ceremony, flattery, or hedges.
10. Stop: no closing summary section.

The linter flags filler words, vague words, sentences over 32 words, and checklist items that do not start with a verb. Passing the linter is necessary, not sufficient: still run the CRISP pass yourself.

## Output contract

- One self-contained `.html` file: no network access at view time, works from `file://`, prints cleanly.
- Ticks live in the reader's browser (`localStorage`, keyed by `doc.id`, checklist id, item id). Keep ids stable across edits; rename an id only to reset that progress on purpose. Changing an item's `done` in a new revision overrides any earlier reader tick on it, so set `done: true` when you verified a step yourself.
- Accessible: every canvas has a text outline (`<details>` under it) listing parts, connections, and flow steps; keyboard: focus a canvas, then `+`/`-`/arrows/`0`/`Esc`, Enter on a node; `prefers-reduced-motion` starts flows paused.
- Theme follows the reader's system setting; the moon/sun button in the app bar overrides it per browser (`localStorage` key `bluedoc:theme`).
- A drawing explains; it does not prove. Say so in `state` when the reader could mistake it for runtime evidence.
