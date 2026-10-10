---
name: bluedoc
description: Generate self-contained HTML engineering docs (architecture pages, walkthroughs, runbooks, setup guides, change proposals, implementation plans, PR review findings, UI mockups) with zoomable blueprint canvases that open into each system's inner architecture and play animated data/control flows, checklists that persist as task trackers, plans and designs the reader approves or sends back from the page, a board of sandboxed HTML screens for watch, phone, desktop, web and presentation slides, and a code browser that pins review findings to the lines they are about. Use when asked for an HTML doc, architecture page, system walkthrough, runbook, onboarding guide, a plan, an implementation plan, a design doc, UI mockups, wireframes, screen designs, slide decks, "plan mode", "make a plan", "propose a plan", "peer review results", "review findings", "review comments in a bluedoc", "open threads", or "a bluedoc".
---

# bluedoc

You write one `*.bluedoc.json`; the local server renders it as a page (blueprint canvases, checklists, plans to approve, code review, revisions) and hands the reader's replies back to you. `<skill>` is this folder; scripts need Python 3.9+, stdlib only.

## Workflow

1. **Gather facts from the source.** Read the code, configs and runs the doc describes. Every node, step and finding maps to a file, symbol, queue or command; keep `path:line` anchors for `refs`. Mark what you did not observe `unverified`.
2. **Scaffold:** `python3 <skill>/scripts/build.py new <type> docs/<topic>/<name>.bluedoc.json --title "…" [--kind Runbook]`. Plans go in `docs/plans/<topic>.bluedoc.json`; a codebase review by area, not by PR, adds `--shape area`; a design adds `--target watch,mobile,desktop,web --framework …`. Then read the type's guide (table below), once.
3. **Fill every `<<…>>`**; add or drop blocks as the guide says. Images and videos go next to the JSON (`media/…`), referenced by relative path.
4. **Validate:** `python3 <skill>/scripts/build.py <doc>`. Fix every `ERROR`; fix every `WARN` unless it is a false positive you can name. This records the revision. A passing build is the whole verification: no browser check.
5. **Open:** `python3 <skill>/scripts/serve.py open <doc> --to <your name>` starts the server if needed and prints the URL with a one-time `?key=` token; later edits show on reload. Give the reader that exact link (it lets their browser save) and what stays unverified. A page that says "This browser can't save yet": run `serve.py unlock` and send its link.
6. **Wait** in the background, no timeout: `python3 <skill>/scripts/serve.py wait <doc> --kind any`. It prints `--- bluedoc <kind> (reply <id>, …) ---`, the reader's Markdown, `--- end ---`. Replies sent while nobody waits are queued; `serve.py reply <id>` reprints one.

| Type | Guide | When |
|---|---|---|
| `plan` | `types/plan.md` | Anything you'd hand over before implementing: plan mode, "make/propose a plan", a technical design doc. |
| `design` | `types/design.md` | UI mockups: screens for watch, phone, tablet, desktop or web, or presentation slides, as HTML on a board. |
| `review` | `types/review.md` | Review results (peer, agent, open PR threads), always, without being asked. |
| `docs` | `types/docs.md` | Architecture, walkthrough, runbook, setup guide, change proposal. |
| `other` | `types/other.md` | Anything else: status page, report, inventory. |

## Replies

- **Answers** (picks, ticks, comments): act on each pick; no pick means undecided, so ask. An item comment is an instruction about that item and can override its pick.
- **Change requests**: each annotation names a `key`; pass it to `patch` as is. The annotator writes `doc` (general notes: apply across the doc), `header`, `tldr`, `status`, `section:`, `heading:`, `lead:`, `block:`, `item:`, `row:`, `card:`, `para:`, `step:`, `file:`, `media:`, `compare:`, `node:`, `comment:` and `line:` keys, and on design pages `artboard:`, `el:` and `frame:`; their grammar is the table under `## Annotations` in `references/schema.md`. A `line:` key patches the review comment covering that line; with none, change the code or patch the finding. An `el:` key: `patch` prints the screen file and selector; edit there. One you can't or shouldn't do: say so in `changes` or ask, never skip it silently.
- **Approval** (plans, designs): implement exactly the approved rev, as `types/plan.md` and `types/design.md` say.
- **Revise** per target: `build.py patch <doc> <key> --set field=value --change "what changed and why"` (`--json`, `--append`, `--delete` for more). It validates, bumps `meta.rev`, replaces `changes`, records history and prints the `?diff=` link to send. Several patches for one reply: bump on the first, `--no-bump` on the rest. Once you have sent the reader a rev's URL, never edit it in place. Hand edits: bump `meta.rev` and rewrite `changes` (1–4 lines) yourself, then run `build.py <doc>`: only the build records the revision.
- Record the reader's picks as `choice` and finished, verified steps as `done: true`. Send the `?diff=` link, then `wait` again.
- Commit `<name>.bluedoc.history.json` with the JSON.

## Writing

1. Answer first: `tldr` and each `lead` state the conclusion, not the topic.
2. Say it once: no section repeats another; prose never repeats a table.
3. Cut every sentence whose removal breaks nothing; no closing summary.
4. Same words: define terms once in a `terms` block and reuse them exactly.
5. Name the actor and the condition: "If the token expired, the server closes the socket."
6. Checkable, not vague: numbers, names, conditions, or "unknown".
7. Shape fits content: procedures are checklists (`text` an imperative action ≤ 90 chars, `sub` why); comparisons are tables; a `caution` (data, equipment) or `warning` (people, production) callout sits before the step it guards.
8. The reader chooses through decision items (`choices` + `recommend`), never "check if you agree". Set `choice` only to carry over the reader's own pick.
9. Short is not cryptic: keep commands, risks and real uncertainty.
10. Sound like a colleague: no ceremony, flattery or hedges.

The linter warns on filler, vague words, sentences over 32 words, titles over 90 and `sub`s over 120 characters, option labels over 28, topic-first leads, a closing summary section, numbered-list procedures, checklist items that don't start with a verb, and "check if you agree" items; the rules still apply beyond it.

## Never

- Read or write HTML, `assets/` (template, home page, kits) or `examples/`; a design's own screen files (`<name>.design/*.html`) are the one exception. `build.py <doc> -o out.html` writes a file only when someone needs one to send.
- Read `references/schema.md` whole: grep it for a heading, e.g. `grep -n -A25 '^## Diff' <skill>/references/schema.md`. Its first lines list the headings.
- Rename ids across revisions: they key the reader's ticks and the revision diff.
