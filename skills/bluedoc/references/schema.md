# bluedoc JSON schema

One JSON file describes one HTML document. `scripts/build.py` validates it and inlines it into `assets/template.html`. Worked examples: `examples/acme-orders.bluedoc.json` (canvas, flows, checklists) and `examples/acme-review-findings.bluedoc.json` (review findings: decision items and diffs).

## Document

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | id | yes | Namespace for checklist progress in `localStorage`. Never change it after people start ticking. |
| `title` | string | yes | Page `<h1>` and browser title (`<title> · bluedoc`). |
| `subtitle` | inline md | no | One sentence under the title. |
| `meta` | object | no | `org`, `kind` (Architecture, Walkthrough, Runbook, Setup, Change), `dwg` (drawing number), `rev`, `date`. `org · kind · date` form the line above the title; `dwg` and `rev` appear under **Document** in the status rail and in the canvas title blocks. |
| `state` | `[{label, kind}]` | no | Provenance, listed under **Status** in the status rail as dots. `kind`: `ok` (green), `warn` (amber), `risk` (red), `info` (blue), `todo` (grey). Example: `{"label": "not live", "kind": "warn"}`. Keep each label under ~40 characters. |
| `links` | `[{label, href}]` | no | Related documents, listed under **Related** in the status rail. |
| `tldr` | md | no | The answer in 1–3 sentences. Required in practice for documents longer than 3 sections. |
| `sections` | `[section]` | yes | Rendered in order, numbered 01, 02, … |

`id` everywhere = lowercase letters, digits, hyphens; starts with a letter or digit.

## Section

`{ "id", "title", "lead"?, "blocks": [block] }`. `lead` is one line of inline md under the heading.

## Blocks

| `type` | Fields | Use for |
|---|---|---|
| `text` | `md` | Prose. Paragraphs split on blank lines; `- ` lists; `1. ` lists. |
| `callout` | `kind` (`note`, `caution`, `warning`, `risk`, `decision`), `md`, `title`? | `caution` = risk to equipment or data; `warning` = risk to people or production; `decision` = a choice and its reason. |
| `table` | `columns: [str]`, `rows: [[inline md]]`, `caption`? | 2+ items sharing 2+ attributes. Every row has `len(columns)` cells. |
| `code` | `code`, `lang`?, `title`? | Copyable commands or files. |
| `terms` | `items: [{term, md}]` | Define each term once; reuse it exactly. |
| `cards` | `items: [{title, md, tag?, kind?}]` | Options or components compared side by side. `tag` + `kind` render a chip. |
| `checklist` | `id`, `title`, `items`, `numbered`? (default true) | Procedures and task tracking. See below. |
| `canvas` | see below | Blueprint drawings. |
| `diff` | see [Diff](#diff) | A code change with line comments: file list, unified diff, comment cards. Generate it with `scripts/gitdiff.py`. |

### Inline markdown

`**bold**`, `*em*`, `` `code` ``, `[text](url)`. `[text](#node:<canvasId>/<nodeKey>)` scrolls to the canvas and opens that node. `[text](#code:<diffId>/<path>:<line>)` opens that file in a `diff` block and jumps to the line; `/<path>` and `:<line>` are optional. The same `#code:` URL works as a page link. No headings, images, or raw HTML (input is escaped).

## Checklist

Each item is a collapsed row: a tick, a one-line **title** (`text`), a one-line **subtitle** and an optional chip. Clicking the row opens everything else. Write the row so a reader can scan the list without opening anything.

```json
{ "type": "checklist", "id": "setup", "title": "Set up", "items": [
  { "id": "install", "text": "Install the CLI", "sub": "Needs Homebrew; takes 1 minute",
    "code": "brew install foo", "verify": "`foo --version` prints 2.x.",
    "detail": "md shown when the row is open", "refs": ["arch/api"],
    "state": "unverified", "stateKind": "warn", "done": false,
    "blocks": [ { "type": "table", "columns": ["OS", "Command"], "rows": [["macOS", "`brew install foo`"]] },
                { "type": "checklist", "id": "setup-install-steps", "title": "Steps", "items": [ … ] } ] }
] }
```

| Item field | Where it shows | Meaning |
|---|---|---|
| `id` | | Stable id. Progress key = `bp:<doc.id>:<checklist.id>:<item.id>`. Renaming resets that tick. |
| `text` | row, line 1 | The action, imperative, one line (≤ 90 characters; the build warns above that and the row truncates with …). Full text shows when the row is open. |
| `sub` | row, line 2 | One line of context: why, what it unblocks, who owns it (≤ 120 characters). If absent, `verify` takes this line with a ✓ icon. |
| `state`, `stateKind` | row, right | Chip such as `unverified` / `warn`. Keep it to 1–3 words. |
| `detail` | open | Extra md: lists, paragraphs, links. |
| `code`, `lang` | open | Command to run for this step, with a Copy button. |
| `blocks` | open | Any of `text`, `callout`, `table`, `code`, `terms`, `cards`, `checklist`. A nested checklist ticks on its own, counts in the page total and exports indented under its parent; nested checklists can't nest again. |
| `verify` | open (or row line 2) | Observable success check (output, state, file). Required for steps whose failure is silent. Shown as **Check** when the row is open, unless it already fills line 2. |
| `refs` | open | `"<canvasId>/<nodeKey>"`; renders buttons that open that node. Node keys nest with `/`: `arch/api/auth`. |
| `done` | | Initial tick before the reader touches it (e.g. steps the author already verified). Not for decision items. |
| `choices` | row, line 3 | Makes the item a **decision**: 2–6 options `{id, label, md?}` shown as pills instead of a tick. Label ≤ 28 characters; `md` is the tooltip. The reader picks one; picking it again clears it. A picked item counts as done. |
| `recommend` | row, line 3 | The id of the recommended option, starred. |
| `choice` | | The author's pre-picked option, like `done` for ticks. Leave it unset when the reader is meant to decide. |

```json
{ "id": "double-auth", "text": "A retry can authorize the card twice", "sub": "Recommend fix in PR: a timeout after PayCo accepted becomes a second charge.",
  "state": "blocker", "stateKind": "risk", "recommend": "fix",
  "choices": [ { "id": "fix", "label": "Fix in PR" }, { "id": "ticket", "label": "Ticket" }, { "id": "decline", "label": "Decline" } ] }
```

Use a decision item whenever the reader has to choose, instead of a step like "check if you agree". Its title states the finding or question, not an action. **Copy progress** writes the pick: `- [x] A retry can authorize the card twice → **Fix in PR**`, adds `(recommended: …)` when the pick differs, and `(no decision; recommended: …)` when there is none. In a `diff` block, the comment card for a decision item carries the same pills, kept in sync with the row.

A row with nothing to open has no chevron; clicking it ticks it. **Expand** in the checklist header opens or closes every row. Links to `#item-<checklist>-<item>` (from a canvas node, a table cell or a shared URL) open the row, and its parents, before scrolling to it. Print shows every row open.

Ticks persist per browser. The sidebar shows per-checklist progress; **Copy progress** exports all checklists as Markdown task lists (`- [x] …`) for PRs or issues.

A reader's tick is stored only when it differs from the item's `done`, together with the `done` it overrode. If the author later changes `done`, the author wins and the old tick is dropped, so marking a step done in a new revision shows as done for readers who unticked it earlier. Picks follow the same rule against `choice`, and a pick is dropped when its option no longer exists.

### Reader comments and replies

Every item has a comment box at the bottom of its open body (and on its diff card); the two stay in sync. A row with a comment shows a speech-bubble icon. Comments are stored per browser under `bp:<doc.id>:<checklist>:<item>:note`; **Reset** clears ticks and picks, not comments. The export quotes each comment under its item:

```md
- [x] `tierFor` gives no tier at exactly 10 or 50 units → **Ticket** (recommended: Fix in PR)
  > Ship it with the test first.
```

**Send to agent** (app bar, shown when the page has a checklist) opens a dialog: a count of decisions, ticks and comments, an overall message (stored under `bp:<doc.id>:__message`, printed after the page title in the export), a Markdown preview, **Copy**, and **Send**. Send appears only when the page is served by `scripts/serve.py`: the page probes `GET /__bluedoc/ping` and posts the reply to `/__bluedoc/reply`. `serve.py` prints the Markdown and writes `<name>.reply.md` and `<name>.reply.json` next to the page. The JSON:

```json
{ "doc": "<doc.id>", "title": "…", "path": "/<name>.html", "at": "<ISO time>", "message": "…",
  "items": [ { "checklist": "t412", "item": "tier-boundary", "text": "…", "choice": "ticket", "recommend": "fix", "note": "…" },
             { "checklist": "local", "item": "doctor", "text": "…", "done": true } ],
  "markdown": "<the Copy progress text>" }
```
Decision items carry `choice` (null when undecided) and `recommend`; plain items carry `done`; `note` appears only when the reader wrote one.

## Diff

A `diff` block shows one code change and the comments on it. Use it for PR reviews: each finding is a checklist item, and its comment sits on the lines it is about.

```json
{ "type": "diff", "id": "pr-412", "title": "acme-shop#412", "repo": "acme-shop",
  "base": "a1b2c3d", "head": "e4f5a6b", "url": "https://github.com/acme/acme-shop/pull/412/files",
  "note": "inline md under the header, e.g. which commits the reviewer read",
  "files": [ { "path": "src/pricing/tiers.ts", "status": "modified", "add": 3, "del": 1,
               "hunks": [ { "old": 10, "new": 10, "header": "export function tierFor", "lines": [" ctx", "-old", "+new"] } ] } ],
  "comments": [ { "file": "src/pricing/tiers.ts", "line": 11, "end": 12, "item": "findings/tier-boundary" },
                { "label": "PR description", "title": "Claims a test it does not add", "md": "…", "kind": "warn" } ] }
```

| Field | Meaning |
|---|---|
| `files[].status` | `added`, `modified`, `deleted`, `renamed` (with `from`), or `context`: a file the change does not touch, shown because a comment points at it. |
| `files[].hunks[]` | `old`/`new` = first line number on each side; `lines` = diff lines with their `+`/`-`/space prefix. `context: true` marks an excerpt of unchanged code. |
| `files[].omitted` | Reason the hunks are left out (binary, too large); the file still lists. |
| `comments[].file`, `line`, `end`, `side` | Anchor. `side: "old"` anchors to the removed side. No `line` = whole file; no `file` = whole change (listed as **Whole change**). |
| `comments[].item` | `"<checklistId>/<itemId>"`. The card takes the item's text, chip, detail and tick; ticking either one ticks both, and the item gets a code button that opens the comment. |
| `comments[].title`, `md`, `kind`, `state`, `label` | A comment with no `item`: its own title, body, colour (`ok`, `warn`, `risk`, `info`, `todo`) and chip. `label` names a whole-change anchor. |

The validator checks that every anchored line is shown in the diff, every `item` exists, and every `#code:` link resolves.

In the page, a file header shows how many comments the file has and, with 2+, ‹ › buttons and "n of N" for the comment in view. While a file's comments sit outside the visible part of the code, a floating pill says "N more comments above/below"; clicking it scrolls to the nearest one.

**Generate it from git**, never by hand:

```sh
python3 <skill>/scripts/gitdiff.py --repo ../acme-shop --base a1b2c3d --head e4f5a6b \
  --id pr-412 --title "acme-shop#412" --url https://github.com/acme/acme-shop/pull/412/files \
  --comments comments.json --into docs/reviews/pr-412.bluedoc.json --section review --after-block 1
```

`comments.json` is a list of `{"at": "path:12-20", "item": "checklist/item"}` (or the explicit fields above). The script:
- reads `git diff base head`;
- adds a context excerpt (±5 lines, `--excerpt`) for any comment on lines the diff does not show;
- turns a comment on a file missing at `head` into a whole-change comment;
- drops hunks of uncommented files over 800 changed lines (`--max-lines`);
- writes the block into the section, replacing a block with the same `id`.

Diff the commits the reviewer actually read. If the branch was rebased since, keep the reviewed range and say so in `note`: the line numbers in the findings belong to that range.

## Page layout

The template fixes the layout; documents don't set it.

- **App bar** (sticky): bluedoc mark, the document title (hidden ≤ 900 px), overall checklist progress, theme switch.
- **Wide screens (> 1240 px):** three columns. The content column (at most `--content-w`, 920 px) is centred on the page. The left rail (`--rail`, 204 px) holds Contents and Tracker; the right rail holds Status, Document and Related. Both rails stay in view while the page scrolls (`position: sticky`). Both margins are at least one rail wide, so the content column narrows before a rail can touch it.
- **Medium screens (901–1240 px):** Contents and Tracker stay in the left rail; Status, Document and Related become a card under the TL;DR.
- **Narrow screens (≤ 900 px):** one column: header, TL;DR, status card, a collapsible **Contents** card, then the sections.
- **Reader-chosen width (> 900 px):** a handle sits on each side of the content column. Dragging either one widens or narrows the column symmetrically, so it stays centred; arrow keys on a focused handle move it 40 px (Shift: 160 px). If both rails still fit beside the column they stay; if not, the column takes their space, Status/Document/Related move under the TL;DR and Contents opens from a button in the app bar. Double-click a handle (or press Home on it) to return to the default layout. The width is stored per browser for every bluedoc page (`localStorage` key `bluedoc:width`), so wide tables stay readable without changing the document.
- **Theme:** follows `prefers-color-scheme`; the app-bar button overrides it per browser (`localStorage` key `bluedoc:theme`). The blueprint canvas keeps its navy palette in both themes.
- **Print:** app bar and Contents rail are hidden, the status rail prints inline under the TL;DR, light theme.

## Canvas

```json
{ "type": "canvas", "id": "arch", "title": "Data path", "rootLabel": "System", "height": 540,
  "caption": "inline md under the drawing",
  "nodes": [node], "edges": [edge], "flows": [flow] }
```

### Node

| Field | Meaning |
|---|---|
| `id`, `label` | Required. Label ≤ 40 chars; put detail in `sub` or `md`. |
| `sub` | Second line (path, technology, one fact). |
| position | `x`,`y` = centre in canvas units, **or** `col`,`row` on a 250 × 160 grid. Nodes must not overlap (validator checks). |
| `w`, `h` | Size. Defaults 180 × 80; systems with `children` 240 × 140. |
| `kind` | Shape: `service` (default), `process`, `function`, `store`/`db`/`cache`/`stream` (cylinder), `queue`, `device`/`hardware` (chamfered), `actor`/`user`/`person` (pill), `client`/`app`/`ui` (window), `external`/`cloud` (dashed), `note`, `port`. |
| `state` | Outline + badge: `live` (green), `local` (cyan), `proposed`/`unverified` (amber dashed), `removed`/`replaced` (red dashed). |
| `md` | Shown in the detail panel when the node is clicked. |
| `refs` | Source anchors (inline md), e.g. `` "`src/orders/create.ts:46-84`" ``. |
| `children` | `{nodes, edges, flows}`: the node's inner architecture. Same schema, own coordinate space, nests to any depth (keep ≤ 3). |

### Semantic zoom

A node with `children` is a **system**. Collapsed, it shows its label and `⊕ OPEN`. When its inner drawing reaches about 40–72 % of its natural size on screen, the cover fades out, the system becomes a framed sub-sheet, and its children fade in with their own grid. Double-click (or double-tap, Enter, a crumb, a checklist ref) zooms to it. Escape or the crumbs go back up. Outer levels dim while you are inside a system.

Lay out children in their own space starting near `col: 0, row: 0`; the runtime scales them into the parent's box.

### Edge

| Field | Meaning |
|---|---|
| `from`, `to` | Node ids in the **same scope**. Inside `children`, `@left`, `@right`, `@top`, `@bottom` are ports on the parent's frame: use them to show data entering or leaving the system. |
| `id` | Defaults to `"<from>-><to>"`. Set it when two edges share endpoints. |
| `label` | ≤ 28 chars: the thing that moves or the call. |
| `kind` | `data` (cyan, animated), `control` (dashed), `async` (violet dotted, queues/events), `power` (amber), `dep` (dependency, dim), `replaced` (red). |
| `dir` | `none` or `both` (default: arrow at `to`). |
| `bend` | Perpendicular offset in units, to separate lines. |

### Flow

```json
{ "id": "request", "label": "One request", "loop": true, "color": "#5fd4ff",
  "steps": [ { "edge": "client->api", "label": "The client sends a JWT.", "payload": "JWT", "ms": 1200 },
             { "edges": ["api->db", "api->cache"], "label": "The API reads both in parallel." },
             { "edge": "api->client", "reverse": false, "label": "The API returns 200." } ] }
```

Each scope (root and every `children`) has its own flows. A token travels each step's edge(s); the caption bar shows step dots, `Step n of m` and the step `label`; `payload` floats next to the token. The toolbar controls the flows of the scope you are looking at; other open scopes loop their first flow. The ‹ / › buttons step through manually. A canvas with no flows at any level hides the caption bar. `prefers-reduced-motion` starts paused. Write step labels as one sentence each: actor, action, object.

## Automation API

The built page exposes `window.BP`:

| Call | Returns |
|---|---|
| `BP.zoomTo('arch', 'api/auth')` | Scrolls to the canvas and opens the node. |
| `BP.fit('arch')` | Fits the root drawing. |
| `BP.state('arch')` | `{k, focus, revealed, flow, step, tokens}` |
| `BP.progress()` | `[{id, done, total}]` per checklist. |
| `BP.progressMarkdown()` | The **Copy progress** Markdown, with the overall message and comments. |
| `BP.replyPayload()` | The reply JSON that **Send** posts. |
| `BP.choose('t412/tier-boundary', 'fix')` | Picks an option, as a click would (`null` clears). `false` if the item has no choices. |
| `BP.setNote('t412/tier-boundary', 'text')` | Sets the reader comment on an item (`''` clears). |
| `BP.openCode('pr-412', 'src/pricing/tiers.ts', 11)` | Scrolls to the diff, opens the file, jumps to the line. |
| `BP.openComment('pr-412', 0)` | Opens the n-th comment, in file-list order. |
| `BP.diffState('pr-412')` | `{file, comment, comments, cards, lines, ticked, linked}` |
