---
name: bluedoc
description: Generate self-contained HTML engineering docs (architecture pages, walkthroughs, runbooks, setup guides, change proposals, PR review findings) with zoomable blueprint canvases that open into each system's inner architecture and play animated data/control flows, checklists that persist as task trackers, and a code browser that pins review findings to the lines they are about. Use when asked for an HTML doc, architecture page, system walkthrough, runbook, onboarding guide, "peer review results", "review findings", "review comments in a bluedoc", "open threads", or "a bluedoc".
---

# bluedoc

Write one JSON document; the bluedoc server renders it with the template on every request. You write only the JSON: never write, copy, read or diff HTML, and never read `assets/template.html` or a rendered page (that is where the tokens go). The page is HorizonUI styled, light and dark, with blueprint canvases, checklists, code review, revisions, and an annotator for the reader.

Files, relative to this skill's directory (`<skill>` in the commands below):
- `scripts/build.py`: validates structure, lints CRISP slips, records the revision. `-o out.html` also writes a standalone file, only when someone needs a file to send. Python 3.9+, stdlib only.
- `scripts/serve.py`: the local server (`http://127.0.0.1:8740/`). Renders docs from their JSON, lists all of them on a searchable home page, and hands you the reader's answers and change requests (`serve.py wait`). Python 3.9+, stdlib only.
- `scripts/gitdiff.py`: turns a git range plus `path:line` comments into a `diff` block and writes it into the JSON.
- `scripts/ghthreads.py`: turns a GitHub PR's review threads into the `comments.json` list for `gitdiff.py` and checklist item stubs. Needs `gh` signed in.
- `assets/template.html`, `assets/home.html`: the runtime. Never edit them per document, never read them.
- `references/schema.md`: every field. Read it before writing the JSON.
- `examples/acme-orders.bluedoc.json`: architecture + runbook (3-level canvas, flows per level, checklist linked to the drawing, troubleshooting).
- `examples/acme-review-findings.bluedoc.json`: review findings for two PRs, in the layout below, with two revisions.

## Workflow

1. **Write in CRISP.** If the `crisp` skill is installed, read it and apply it at **CRISP 3** to every string you write: titles, tldr, leads, callouts, node `md`, flow step labels, checklist items. Otherwise apply the ten rules in "Writing" below.
2. **Gather facts from the source.** Read the code, configs, and runs the document describes. Every node, edge, and step must map to something real: a file, a symbol, a queue, a command. Record anchors (`path:line`) for `refs`. Mark what you did not observe as `unverified`.
3. **Plan the structure** (below) before writing JSON.
4. **Write the JSON**: `docs/<topic>/<name>.bluedoc.json`. Keep it in the repo; it is the source. Set `meta.rev` (start at `1` or `A`), `meta.date`, and `meta.kind`; set `meta.type` (`docs`, `review`, `other`) only when `kind` alone doesn't say it. No HTML file.
5. **Validate:**
   ```sh
   python3 <skill>/scripts/build.py docs/<topic>/<name>.bluedoc.json
   ```
   Fix every `ERROR`. Fix every `WARN` unless it is a false positive you can name (e.g. a quoted log line). This also records the revision.
6. **Open it:**
   ```sh
   python3 <skill>/scripts/serve.py open docs/<topic>/<name>.bluedoc.json --to <your name>
   ```
   Starts the server if it isn't running, adds the doc's `docs` folder to the home page, prints the doc's URL. Editing the JSON is enough to update the page: the reader reloads.
7. **Verify in a browser** at that URL, at 390 px, 1280 px and 1920 px, in light and dark (`prefers-color-scheme`). Check: no console errors; no horizontal scroll; at 1280 px and 1920 px the content column has equal left and right margins (centred on the page) and both rails (Contents/Tracker left, Status/Related right) stay in view beside it while the page scrolls; the root drawing has no overlapping labels; for each system, `BP.zoomTo(canvas, key)` reveals its children and `BP.state(canvas).tokens > 0` while flows play; ticking a checklist item survives a reload. For each `diff` block: `BP.openComment(diff, i)` shows the card on its lines, and ticking the card ticks its checklist item. Look at screenshots of the root and of each opened system, and fix layout before reporting. Judge the page by screenshots and `BP.*` calls, never by reading its HTML.
8. **Report** the URL, what you verified, and what stays unverified. When the doc is a new revision, add the compare link: `<url>?diff=<previous rev>`. The reader finds every doc at `http://127.0.0.1:8740/`.

## Revisions

Readers can switch between revisions of a doc and compare any two, so they see what changed instead of rereading it. The build keeps the history; you decide when a revision starts.

- **Bump `meta.rev` each time you hand the reader a changed doc** (after review comments, new findings, a rebase, a status change). Rebuilding with the same `rev` replaces that revision in place, which is right while you are still drafting it; once the reader has seen it, bump. The build prints `recorded rev C` or `rev C updated in place`.
- **Write `changes`** (top level, next to `tldr`) on every revision after the first: 1–4 inline-md lines saying what changed and why, e.g. `"#412 tier-boundary: now Fix in PR; the spec says \"10 or more\"."`. The page shows them in the revision list and above the marked diff. Replace them on each bump; they describe this revision only.
- `build.py` (and every server render) stores every revision in `<name>.bluedoc.history.json` next to the JSON (blocks are shared between revisions, so the file stays small). Keep it next to the JSON and commit it with it; deleting it deletes the history. `--no-history` skips it; `--show-rev B` prints revision B as JSON.
- The page: a **Rev** button in the app bar opens the revision list (view any revision, compare any two). `?rev=B` shows revision B read-only; `?diff=B` marks what changed since B on the current page: new, changed and removed sections, blocks, checklist items, table rows and canvas parts, each with a word-level **What changed** box, and ↑ ↓ to step through them. A reader who opens a newer revision than last time gets an "Updated since you last opened it" strip with a link to the diff.
- Keep section, block and item ids stable across revisions: the diff matches by id, so a renamed id shows as one removal plus one addition.

## Structure

Order sections by what the reader needs first:

| Doc kind | Sections, in order |
|---|---|
| Architecture | TL;DR → canvas (the system) → terms → components (cards or table) → decisions (callouts `decision`) → known issues/risks |
| Walkthrough ("how X works") | TL;DR → canvas with one flow per scenario → step-by-step explanation per flow → edge cases |
| Setup / runbook | TL;DR → prerequisites checklist → canvas (what you are building) → procedure checklists → verification → troubleshooting table → teardown checklist |
| Change / proposal | TL;DR → canvas with `state` (`proposed`, `removed`) → what changes (table) → rollout checklist → risks |
| Review findings (default whenever review results go in a bluedoc) | TL;DR → Summary (table + provenance note) → one section per PR: findings checklist, then a `diff` of the commented files. See "Review findings" below. |

Rules:
- **One canvas per system boundary.** Put depth in `children`, not in more canvases. Root ≤ 9 nodes; each level ≤ 9 nodes; nest ≤ 3 levels.
- **Children explain the parent.** A system's children are its real parts (modules, classes, threads, pins). Use `@left`/`@right`/`@top`/`@bottom` ports to show where the parent's outer edges enter and leave.
- **One flow per question.** "How does a request get served?" is a flow. Each step is one edge, one sentence (actor, action, object), and an optional `payload` naming what moves. Every scope that has edges should have at least one flow.
- **Kinds carry meaning.** `data` for payloads, `control` for calls/starts, `async` for queues and events, `power` for hardware supply, `dep` for build/runtime dependencies. Shapes follow the node `kind` table in the schema.
- **State is visible.** Use node `state` and doc `state` chips for anything not live or not verified. Never draw a proposed component as if it exists.
- **Checklists are the task tracker.** Every procedure is a checklist, not a numbered text list. Each item collapses to two lines, so write them for scanning: `text` is the action in one line (imperative verb first, ≤ 90 characters), `sub` is one line of why or what it unblocks. Everything else goes in the open row: `detail`, `code` for the command, `verify` for the observable result, and `blocks` for tables or a sub-checklist. Link items to the drawing with `refs` so readers jump from a step to the part it touches.
- **Findings sit on their code.** In a review, every finding with a `path:line` is a checklist item and a comment in that PR's `diff` block. Follow "Review findings" below.
- **Tables for comparisons, terms for vocabulary, callouts for risk.** `caution` before a step that can lose data or damage equipment; `warning` before a step that can hurt people or production; place it before the step it guards.

## Review findings

Use this layout, without being asked, whenever review results (peer review, agent review, open PR threads) go into a bluedoc. Each finding is a **decision item**: the reader picks one of its options (Fix in PR, Ticket, Decline, …), with your recommendation starred, can leave a comment on it, then sends the answers back to you (see "Reader replies"). The reply lists each pick (`→ **Ticket** (recommended: Fix in PR)`) and comment, and you act on them. `examples/acme-review-findings.bluedoc.json` is the reference.

**Document**
- `subtitle`: what the page holds, then "Pick what to do with each; my recommendation is starred."
- `state`: counts per verdict, e.g. "11 review comments", "6 fix in the PR", "2 follow-up tickets", "2 decline", "1 resolves when a fix lands".
- `links`: each PR, then related docs.
- `tldr`: how many to fix, ticket and decline, and which findings are real bugs the change introduces.

**Section 1, Summary**
- `lead`: "Each finding has its options under it, with my recommendation starred. Pick one per finding, comment where you disagree, then press **Send answers**."
- A `table`: **PR | Finding | Size | Recommendation**, one row per finding. Size is `blocker`, `major`, `minor` or `nit`. Link each finding to its item: `[text](#item-<checklist>-<item>)`.
- A `note` callout for provenance when it matters (who posted the comments, under which login, at which heads).

**One section per PR**
- `lead`: how many findings and of what kind, then the reviewed range: "Diff: `main` `<base>` → head `<head>`, limited to the commented files."
- A `checklist`, `numbered: false`, one decision item per finding:
  - `text`: the finding, stated as a fact in one line ("A retry can authorize the card twice"). Not an instruction: the options are the instructions.
  - `sub`: `Recommend <option>: <one-line reason>.`
  - `state` / `stateKind`: the size: `blocker` / `risk`, `major` / `warn`, `minor` / `info`, `nit` / `todo`.
  - `choices`: `[{"id": "fix", "label": "Fix in PR"}, {"id": "ticket", "label": "Ticket"}, {"id": "decline", "label": "Decline"}]` by default. Use other options when the real decision differs: a finding that resolves itself once another lands gets `[{"id": "after", "label": "Resolve after <x>"}, {"id": "fix", "label": "…"}]`; a design question gets its actual alternatives. 2–6 options, labels ≤ 28 characters.
  - `recommend`: the id of your recommended option. Never set `choice`: the reader decides.
  - `detail`, in this order: **Reviewer:** the finding, restated faithfully, with the reviewer's evidence. **My reasoning:** why this recommendation, citing `path:line` and what you checked. **Fix:** the concrete change. **Verify:** the observable check. **Reply I'd post:** for declines and tickets.
- A `diff` block right after the checklist, from `gitdiff.py`: `--paths` limited to the files that have findings; `--note` naming the head and the scope ("Only the commented files"); one comment per finding, `{"at": "path:line[-end]", "item": "<checklist>/<item>"}`. If a thread sits on a different line than the code that needs the fix, anchor it on the code and say so in `note`. Findings with no line become "Whole change" comments.

**Rules**
1. Every finding gets options, a recommendation and a reason. Never list a finding without a recommended option.
2. Recommend from the code, not from the review. Check the claim (read the file, run the grep or test) before you agree or decline.
3. Mark any assumption you did not verify as *unverified* in `detail`, and make its check required in **Verify**.
4. The diff shows only the commented files, at the head the findings refer to. After a rebase, regenerate it and check every anchor still lands on the code it describes.
5. Never answer a decision yourself. Set `choice` only to carry over the reader's own answer from an earlier round (a reply, or a pick they told you), and say so in `detail` (`**Status:** picked <option> on <date>`). Pre-tick (`done: true`) only plain checklist steps you finished and verified.

Decision items work anywhere, not only in reviews: whenever you need the reader to choose ("Which account should DEV-02 use?", "Keep or drop the flag?"), give the options as `choices` instead of writing steps like "check if you agree".

**From GitHub threads**
```sh
python3 <skill>/scripts/ghthreads.py --repo <owner>/<repo> --pr <n> --checklist t<n> \
  --comments-out /tmp/c<n>.json > /tmp/items<n>.json
python3 <skill>/scripts/gitdiff.py --repo <checkout> --base <base> --head <head> --id diff-<n> --title "<repo> #<n>" \
  --paths <commented files> --comments /tmp/c<n>.json --note "Only the commented files. Head <head>." \
  --into docs/<topic>/<name>.bluedoc.json --section pr-<n> --after-block 0
```
`ghthreads.py` prints the PR's base and head and one decision-item stub per open thread, with the standard options, the reviewer's text in `detail`, and `<<…>>` placeholders for the finding, size, recommendation and reasoning. The build fails while any `<<…>>` placeholder is left, so no finding ships without a recommendation.

## Reader replies: answers and change requests

The reader sends two different things back, from two different places:

| | **Answers** | **Change requests** |
|---|---|---|
| What | Picks on decision items, ticks, a comment per item, an overall message | Annotations on the page: a pin on an element, a selected passage, a drawing, each with the change they want |
| Where | **Send answers** in the app bar | The tray at the bottom (View, Point, Select, Draw) and the **Comments** sidebar on the right, then **Request changes** |
| Means | "Here are my decisions; go do the work" | "Edit this doc" |
| Files | `<name>.reply.md` / `.json` | `<name>.changes.md` / `.json` |

After `serve.py open`, wait for the reader in the background (no timeout, or a long one):
```sh
python3 <skill>/scripts/serve.py wait docs/<topic>/<name>.bluedoc.json            # either kind
python3 <skill>/scripts/serve.py wait docs/<topic>/<name>.bluedoc.json --kind changes
```
It prints `--- bluedoc answers (…json) ---` or `--- bluedoc change request (…json) ---`, the Markdown, `--- end ---`, and exits 0 (3 on `--timeout`). Replies sent while nobody waits are queued; the next `wait` gets the oldest. Then:

**Answers**
1. Act on each pick. A missing pick means "not decided": ask, don't assume your recommendation.
2. Treat each item comment as an instruction about that item; a comment can override the pick.
3. Update the JSON with what changed (`done: true` on finished steps, `choice` carrying the reader's picks, new findings as items), bump `meta.rev`, write `changes`, validate, and tell the reader the `?diff=` link.

**Change requests**
1. Each annotation names its target (`label`, and `key` such as `item:t412/tier-boundary`, `block:<section>/<n>`, `row:…`, `node:<canvas>/<key>`, `line:<diff>/<path>:<n>`), the quoted or covered text, and the requested change. Edit exactly those places in the JSON.
2. A request you can't or shouldn't do (it contradicts the source, or needs a decision): don't silently skip it; say so in `changes` or ask.
3. Bump `meta.rev`, write `changes` listing what you changed per request, validate, give the `?diff=` link, and `wait` again.

On `file://` (a standalone `-o` file) both dialogs offer **Copy** only; the reader pastes the text into the chat. `<name>.reply.*` and `<name>.changes.*` are the reader's messages: don't commit them unless asked.

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

- Every page is self-contained: no network access at view time beyond its own server, prints cleanly; a `-o` file also works from `file://`.
- Ticks, picks and comments live in the reader's browser (`localStorage`, keyed by `doc.id`, checklist id, item id). Keep ids stable across edits; rename an id only to reset that progress on purpose. Changing an item's `done` in a new revision overrides any earlier reader tick on it, so set `done: true` when you verified a step yourself. Earlier revisions (`?rev=`) show the reader's current progress but never store changes.
- Accessible: every canvas has a text outline (`<details>` under it) listing parts, connections, and flow steps; keyboard: focus a canvas, then `+`/`-`/arrows/`0`/`Esc`, Enter on a node; `prefers-reduced-motion` starts flows paused.
- Theme follows the reader's system setting; the moon/sun button in the app bar overrides it per browser (`localStorage` key `bluedoc:theme`).
- A drawing explains; it does not prove. Say so in `state` when the reader could mistake it for runtime evidence.
