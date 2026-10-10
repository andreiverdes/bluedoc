# bluedoc JSON schema

Lookup reference for every field and command. Grep for a heading, never read the file whole: `grep -n -A25 '^## Diff' references/schema.md`. How to lay out each doc type lives in `types/<type>.md`.

Headings: `## Document` (incl. `hero`) · `## Contracts` · `## Section` · `## Blocks` (`### Inline markdown`) · `## Checklist` (`### Reader comments and replies`) · `## Diff` (`### Diff reference`, `### Embedded diff`, `### gitdiff.py`) · `## Plan blocks` (`### Steps`, `### Files`, `### Media`, `### Compare`) · `## Revisions` · `## Page layout` · `## Canvas` (`### Node`, `### Semantic zoom`, `### Edge`, `### Flow`) · `## Annotations` (`### Bottom tray`) · `## Plans` · `## build.py` (`### patch`) · `## serve.py` · `## Automation API`

## Document

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | id | yes | Namespace for checklist progress in `localStorage`. Never change it after people start ticking. |
| `title` | string | yes | Page `<h1>` and browser title (`<title> · bluedoc`). |
| `subtitle` | inline md | no | One sentence under the title. |
| `meta` | object | no | `org`, `kind` (Architecture, Walkthrough, Runbook, Setup, Change, Plan, Review, or a free label), `dwg` (drawing number), `rev`, `date`, `type`. `org · kind · date` form the line above the title; `dwg` and `rev` appear under **Document** in the status rail and in the canvas title blocks. `rev` names the revision: the build keeps one history entry per `rev` (see Revisions). `type` (`docs`, `review`, `plan`, `other`) picks the doc's [contract](#contracts), its home-page group and card, and the page's tray; `build.py new` sets it. Unset, it is derived from `kind`, case-insensitive: starts with `plan` or is `implementation plan` → `plan`; contains `review` → `review`; names a docs kind (Architecture, Walkthrough, Runbook, Setup, Reference, Proposal, Change, Status, Guide, Design, Spec, RFC, ADR, …) → `docs`; anything else → `other`. A `plan` doc is a **plan page**: see [Plans](#plans). |
| `state` | `[{label, kind}]` | no | Provenance, listed under **Status** in the status rail as dots. `kind`: `ok` (green), `warn` (amber), `risk` (red), `info` (blue), `todo` (grey). Example: `{"label": "not live", "kind": "warn"}`. Keep each label under ~40 characters. |
| `links` | `[{label, href}]` | no | Related documents, listed under **Related** in the status rail. |
| `hero` | `{icon, value, label}` | no | The home card's stat, for `other` docs and for `docs` without a canvas. `icon`: `chart`, `doc`, `flag`, `bolt`, `clock`, `users`, `bug`, `box`, `check`, `globe`, `lock` or `list`. `value` ≤ 8 characters (`"99.95%"`); `label` ≤ 28 (`"uptime, last 30 days"`). Without it an `other` card shows the `doc` icon and the section count. |
| `tldr` | md | no | The answer in 1–3 sentences. Required in practice for documents longer than 3 sections. |
| `changes` | `[inline md]` | no | What changed in this revision and why, 1–4 lines. Shown in the revision list and above the marked diff. Rewrite it on each new `rev`. |
| `sections` | `[section]` | yes | Rendered in order, numbered 01, 02, … |

`id` everywhere = lowercase letters, digits, hyphens; starts with a letter or digit.

## Contracts

Each type's home card draws one element, so the build requires that element's data:

| `meta.type` | Required | Home card element |
|---|---|---|
| `review` | ≥ 1 `diff` block (reference or embedded); every checklist item with `choices` has `state` `blocker`, `major`, `minor` or `nit` | `+N / −N` lines, file and PR count, one dot per finding coloured by size |
| `plan` | a `steps` block and a `files` block | step timeline (status dot, effort bar), A/M/D/R file counts |
| `docs` | a `canvas` block, or `hero` | the root drawing with a flow on hover, the kind, the level count |
| `other` | nothing | `hero`; else the `doc` icon and the section count |

A missing requirement is an **error** when the doc's `meta.rev` is new (not yet in its history file) and a **warning** on a rev the history already has, so recorded revisions keep rendering. `build.py` and every server render apply the same rule. `build.py new <type>` writes a skeleton that meets the contract.

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
| `steps` | `id`, `items`, `title`? | A plan's implementation order, as a numbered timeline. See [Plan blocks](#plan-blocks). |
| `files` | `items`, `title`? | The files a plan touches, grouped by folder, each with an action badge. |
| `media` | `src`, `alt`, `caption`?, `width`? | An image (opens full size on click) or a video, from a file next to the doc. |
| `compare` | `before`, `after`, `title`? | Two panes side by side: before and after code, text or images. |

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
| `blocks` | open | Any of `text`, `callout`, `table`, `code`, `terms`, `cards`, `files`, `media`, `compare`, `checklist`. A nested checklist ticks on its own, counts in the page total and exports indented under its parent; nested checklists can't nest again. |
| `verify` | open (or row line 2) | Observable success check (output, state, file). Required for steps whose failure is silent. Shown as **Check** when the row is open, unless it already fills line 2. |
| `refs` | open | `"<canvasId>/<nodeKey>"`; renders buttons that open that node. Node keys nest with `/`: `arch/api/auth`. |
| `done` | | Initial tick before the reader touches it (e.g. steps the author already verified). Not for decision items. |
| `choices` | row, line 3 | Makes the item a **decision**: 2–6 options `{id, label, md?}` shown as pills instead of a tick. Label ≤ 28 characters; `md` is the tooltip. The reader picks one; picking it again clears it. A picked item counts as done. |
| `recommend` | row, line 3 | The id of the recommended option, starred. |
| `choice` | | A pre-picked option, like `done` for ticks. Use it only to carry over the reader's answer from an earlier round; leave it unset when the reader has not decided. Changing it in a new revision overrides the reader's stored pick. |

```json
{ "id": "double-auth", "text": "A retry can authorize the card twice", "sub": "Recommend fix in PR: a timeout after PayCo accepted becomes a second charge.",
  "state": "blocker", "stateKind": "risk", "recommend": "fix",
  "choices": [ { "id": "fix", "label": "Fix in PR" }, { "id": "ticket", "label": "Ticket" }, { "id": "decline", "label": "Decline" } ] }
```

A decision item's title states the finding or question, not an action. **Copy progress** writes the pick: `- [x] A retry can authorize the card twice → **Fix in PR**`, adds `(recommended: …)` when the pick differs, and `(no decision; recommended: …)` when there is none. In a `diff` block, the comment card for a decision item carries the same pills, kept in sync with the row.

A row with nothing to open has no chevron; clicking it ticks it. **Expand** in the checklist header opens or closes every row. Links to `#item-<checklist>-<item>` (from a canvas node, a table cell or a shared URL) open the row, and its parents, before scrolling to it. Print shows every row open.

Ticks persist per browser. The sidebar shows per-checklist progress; **Copy progress** exports all checklists as Markdown task lists (`- [x] …`) for PRs or issues.

A reader's tick is stored only when it differs from the item's `done`, together with the `done` it overrode. If the author later changes `done`, the author wins and the old tick is dropped, so marking a step done in a new revision shows as done for readers who unticked it earlier. Picks follow the same rule against `choice`, and a pick is dropped when its option no longer exists.

### Reader comments and replies

Every item has a comment box at the bottom of its open body (and on its diff card); the two stay in sync. A row with a comment shows a speech-bubble icon. Comments are stored per browser under `bp:<doc.id>:<checklist>:<item>:note`; **Reset** clears ticks and picks, not comments. The export quotes each comment under its item:

```md
- [x] `tierFor` gives no tier at exactly 10 or 50 units → **Ticket** (recommended: Fix in PR)
  > Ship it with the test first.
```

**Send answers** (the last key of the bottom tray, on pages with a checklist; plan pages don't have it) opens a dialog: a count of decisions, ticks and comments, an overall message (stored under `bp:<doc.id>:__message`, printed after the page title in the export), a Markdown preview, **Copy**, and **Send**. The key is neutral until the reader picks, ticks or comments on something, then turns green. Send appears only when the page is served by `scripts/serve.py` (the page probes `GET /__bluedoc/ping?path=…`); it posts to `/__bluedoc/reply`, and the server writes `<name>.reply.md` and `<name>.reply.json` next to the doc's JSON and queues it for `serve.py wait`. The JSON:

```json
{ "kind": "answers", "doc": "<doc.id>", "rev": "<meta.rev>", "title": "…", "path": "/<root>/<path>.bluedoc.json", "at": "<ISO time>", "message": "…",
  "items": [ { "checklist": "t412", "item": "tier-boundary", "text": "…", "choice": "ticket", "recommend": "fix", "note": "…" },
             { "checklist": "local", "item": "doctor", "text": "…", "done": true } ],
  "markdown": "<the Copy progress text>" }
```
Decision items carry `choice` (null when undecided) and `recommend`; plain items carry `done`; `note` appears only when the reader wrote one. Change requests from the annotator are a separate message: see "Annotations" below. On plan pages the picks travel with **Approve plan** or **Request changes** instead: see [Plans](#plans).

## Diff

A `diff` block shows one code change and the comments on it: each finding's card sits on the lines it is about. It has two forms. A **reference** (`base` and `head`, no `files`) is what `gitdiff.py` writes; the server and the build expand it from git. The **embedded** form (`files` with hunks) is what a reference expands to, what `gitdiff.py --embed` writes and what `build.py -o` inlines; blocks written that way keep working.

### Diff reference

```json
{ "type": "diff", "id": "diff-412", "title": "acme-shop #412", "repo": "../acme-shop", "base": "89efd8e", "head": "62ccc86",
  "paths": ["src/pricing/tiers.ts"], "pr": "acme/acme-shop#412", "url": "https://github.com/acme/acme-shop/pull/412/files",
  "note": "Only the commented files. Head `62ccc86`.",
  "comments": [ { "at": "src/pricing/tiers.ts:17-21", "item": "t412/tier-boundary" },
                { "label": "PR description", "item": "t412/pr-claims" } ] }
```

| Field | Meaning |
|---|---|
| `repo` | Required. The git checkout, relative to the doc's folder or absolute. |
| `base`, `head` | Required. The reviewed range; `gitdiff.py` stores short SHAs. |
| `paths` | Pathspecs that limit the diff. |
| `pr` | `owner/repo#N` or the PR URL, for the `gh pr diff` fallback. Without it, a `github.com/…/pull/N` `url` is used. |
| `url`, `note` | As in the embedded form. |
| `exclude`, `context`, `excerpt`, `max_lines` | `gitdiff.py` options, stored only when not the default (3 context lines, ±5 excerpt lines, 800 max lines). |
| `comments[]` | `{"at": "path:line[-end]", "item": "<checklist>/<item>"}`; `{"label": "…", "item": …}` for a whole-change comment; or the explicit fields of the embedded form. |

Expansion, in order: the cache `<name>.diffcache.json` next to the doc (one entry per `repo|base|head|paths`), then `git -C <repo> diff <base> <head> -- <paths>`, then `gh pr diff <pr>` when the repo or the commits are missing (refused when the PR's head isn't `head`). When none works, the block renders empty and the build reports an error. Commit the cache with the doc: it keeps the diff after a rebase or a deleted branch. Agents never read it. While expanding:
- a comment on lines the diff doesn't show gets a context excerpt (± `excerpt` lines);
- a comment on a file missing at `head` becomes a whole-change comment;
- an uncommented file with more than `max_lines` changed lines lists without its hunks.

### Embedded diff

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

The validator checks, on the expanded diff, that every anchored line is shown, every `item` exists, and every `#code:` link resolves.

In the page, a file header shows how many comments the file has and, with 2+, ‹ › buttons and "n of N" for the comment in view. While a file's comments sit outside the visible part of the code, a floating pill says "N more comments above/below"; clicking it scrolls to the nearest one.

### gitdiff.py

Generate diff blocks from git, never by hand:

```sh
python3 <skill>/scripts/gitdiff.py --repo ../acme-shop --base 89efd8e --head 62ccc86 --id diff-412 \
  --title "acme-shop #412" --pr acme/acme-shop#412 --paths src/pricing/tiers.ts --comments comments.json \
  --note "Only the commented files. Head 62ccc86." --into docs/reviews/acme-shop-412.bluedoc.json --section pr-412 --after-block 0
```

- `--comments` is a JSON list of `{"at": "path:12-20", "item": "checklist/item"}` (or the explicit fields above).
- `--into DOC --section ID [--after-block N]` writes the block into that section, replacing a block with the same `id`; without `--into` it prints the block.
- `--embed` writes the embedded form instead of a reference.
- Also: `--repo-name`, `--url`, `--strip-prefix` (repeatable), `--exclude` (repeatable glob), `--context` (3), `--excerpt` (5), `--max-lines` (800).

`ghthreads.py --repo OWNER/NAME --pr N --checklist ID [--comments-out FILE] [--all]` reads a PR's review threads (needs `gh` signed in) and prints its base and head, one decision-item stub per open thread (`--all`: resolved ones too) with `<<…>>` placeholders, and writes the `--comments` list for `gitdiff.py`.

## Plan blocks

Four block types made for plans. They work in any doc. Text fields are inline md unless marked md.

### Steps

```json
{ "type": "steps", "id": "plan", "title": "Implementation order", "items": [
  { "id": "table", "title": "Add the `saved_carts` table", "status": "todo", "effort": "S",
    "md": "New table only, so the migration takes no lock on `carts`.",
    "files": ["services/orders-api/migrations/0012_saved_carts.sql"], "refs": ["arch/savedtbl"] } ] }
```

| Field | Meaning |
|---|---|
| `id` | Required. Unique among the doc's steps blocks. |
| `title` | The block's heading. |
| `items[].id` | Required. Unique across the doc: `files` rows point to it. |
| `items[].title` | Required. The step, imperative, one line (≤ 90 characters). Linted like a checklist item. |
| `items[].md` | md, shown when the step is open. |
| `items[].files` | Paths, shown as chips when the step is open. A chip scrolls to and flashes the matching row of a `files` block; when the doc has a `files` block, the build warns about a path it doesn't list. |
| `items[].status` | `todo` (default), `doing`, `done`, `blocked`. |
| `items[].effort` | `S`, `M` or `L`. |
| `items[].refs` | `"<canvasId>/<nodeKey>"`: buttons that open that node. |

The page draws a numbered vertical timeline. Steps are the proposal, not a tracker: the reader can't tick them. Change `status` in a new revision as work lands.

### Files

```json
{ "type": "files", "title": "Changed files", "items": [
  { "path": "services/orders-api/src/carts/savedCartRepo.ts", "action": "add", "why": "Reads and writes saved carts.", "step": "repo" },
  { "path": "web/src/cart/sessionCartStorage.ts", "action": "rename", "from": "web/src/cart/cartStorage.ts", "why": "Holds only the session cart now.", "step": "cutover" } ] }
```

| Field | Meaning |
|---|---|
| `items[].path` | Required. Path from the repo root; a step's `files` chip matches it exactly. |
| `items[].action` | Required. `add` (badge A, green), `edit` (M, blue), `delete` (D, red), `rename` or `move` (R, amber). |
| `items[].from` | The old path; only for `rename` and `move`. |
| `items[].why` | Required. One line on what changes in the file. |
| `items[].step` | A step id. The row's step link jumps to that step; the build warns when no steps block has it. |

Rows are grouped by folder, each with a file-type icon, the badge, the path and `why`.

### Media

```json
{ "type": "media", "src": "media/acme-saved-carts.svg", "alt": "Wireframe of the cart page with the Saved carts panel.",
  "caption": "Dashed blue parts are new.", "width": 960 }
```

| Field | Meaning |
|---|---|
| `src` | Required. A path relative to the folder of the doc's JSON (`media/mockup.svg`), or a `data:` URI. |
| `alt` | Required. What the image or video shows. |
| `caption` | Inline md under it. |
| `width` | The most pixels wide it shows. |

- `png`, `jpg`, `jpeg`, `gif`, `webp` and `svg` render as an image; clicking opens it full size in a lightbox. `mp4` and `webm` render as a video with controls, muted, `playsinline`.
- `http(s)` and other URLs with a scheme, and absolute paths, are build errors: pages make no network calls. Save the file next to the doc.
- The build checks that the file exists and warns above 2 MB.
- On the server the page uses `src` as written. It resolves against the doc's URL `/<root>/<dir>/<name>.bluedoc.json`, and the server serves media files under its registered roots.
- `build.py -o` inlines every media file as a `data:` URI, so the standalone file works offline.
- Draw SVGs that read on light and dark pages: a neutral palette, or a `@media (prefers-color-scheme: dark)` style block inside the SVG.

### Compare

```json
{ "type": "compare", "title": "What the web app gets back",
  "before": { "label": "Today: `GET /v1/cart`", "lang": "json", "code": "{ \"items\": [] }" },
  "after": { "label": "Proposed: `GET /v1/saved-carts`", "lang": "json", "code": "{ \"carts\": [], \"limit\": 20 }" } }
```

| Side field | Meaning |
|---|---|
| `label` | The pane's heading. Default `Before` / `After`. |
| `md` | md text. |
| `code`, `lang` | Code. |
| `src`, `alt` | An image, with the same path rules as `media`. Give `alt` with every `src`; the build warns without it. |

Each side needs one of `md`, `code` or `src` and shows whichever is present. The panes sit side by side and stack at ≤ 900 px.

## Revisions

Every `build.py doc.bluedoc.json` run and every server render records the document in `doc.bluedoc.history.json` under its `meta.rev`: a new `rev` appends a revision, the same `rev` replaces the last one. A `rev` that is already an earlier revision fails the build (and shows as an error page). No `meta.rev`: no history. The history file stores each revision's header and section fields once per revision and each block once across all revisions (by content hash); the page embeds the revisions other than the current one, with blocks the current one still has as references, so a page with ten small edits grows by roughly the edited blocks.

| URL (the doc's server URL, or a `-o` file) | Shows |
|---|---|
| `<url>` | The current revision. |
| `<url>?rev=B` | Revision B, read-only: ticks, picks and comments made there are not stored; the bottom tray (annotations, **Request changes**, **Send answers**, **Approve plan**) is hidden. |
| `<url>?diff=B` | The current revision with everything that changed since B marked; `?rev=C&diff=B` compares B with C. A bottom tray steps through the changes (↑/↓, `j`/`k`) and **Done** (`Esc`) leaves compare view. |

The diff matches sections, checklist items and canvas nodes by `id`, blocks by type and `id` (or position), and table rows by content then first cell. Each change gets a **New** / **Changed** / **Removed** tag; changed things get a **What changed** box with a word-level diff of each changed field (title, subtitle, details, options, recommendation, cells, node labels, flow steps). Removed sections, blocks, items and rows are shown struck through where they were. Canvas parts that are new or changed glow in the drawing. A `diff` block reports range, files and comments that changed.

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

Each scope (root and every `children`) has its own flows. A token travels each step's edge(s); the caption bar shows step dots, `Step n of m` and the step `label`; `payload` floats next to the token. The toolbar controls the flows of the scope you are looking at; other open scopes loop their first flow. The ‹ / › buttons step through manually. A canvas with no flows at any level hides the caption bar. `prefers-reduced-motion` starts paused.

## Annotations

The tray of keys at the bottom of the current revision has four modes: **View** (`V`, default), **Point** (`C`: pin a note on the element under the cursor), **Select** (`T`: note on a selected passage), **Draw** (`D`: freehand drawing with a note). `Esc` returns to View. A new note is written in a small composer next to its mark; once saved it becomes a card in the **Comments** sidebar on the right (open by default and docked beside the content on wide screens, a drawer or bottom sheet on narrow ones; the sidebar button in the app bar or `]` shows and hides it). Comments are **Pending** (saved, not sent), **Open** (sent with Request changes) or **Resolved** (marked by the reader); the sidebar filters Pending · Open · Resolved · All. They are stored per browser (`bp:<doc.id>:__ann`). The sidebar footer has a **General comment** field for notes about the whole doc (`type: "general"`, `target.key: "doc"`, no page mark); they follow the same states. **Request changes · N** in the bottom tray sends the pending ones, through a dialog with a preview, **Copy** and **Send**; `message` repeats the general notes joined with blank lines, and the Markdown lists them first under `## General`. Send posts to `/__bluedoc/changes`; the server writes `<name>.changes.md` / `.json` next to the doc and queues it for `serve.py wait`. Sent notes stay dimmed until the reader clears them. The toolbar is absent on `?rev=` and `?diff=`.

```json
{ "kind": "changes", "doc": "<doc.id>", "rev": "B", "title": "…", "path": "/<root>/<path>.bluedoc.json", "at": "<ISO time>", "message": "…",
  "annotations": [ { "id": "c…", "type": "pin", "note": "Say which rounding mode.", "rev": "B", "at": "…",
                     "target": { "key": "item:t412/float-cents", "label": "02 #412 · bulk discount tiers › Findings · #412 › 2. Tiered line totals…", "text": "Tiered line totals are fractional cents …" } },
                   { "type": "text", "quote": "one-line fixes", "target": { "key": "tldr", … }, … },
                   { "type": "draw", "target": { "key": "block:trouble/0", … }, "targets": [ { "key": "row:trouble/0/0", … }, { "key": "row:trouble/0/1", … } ], … } ],
  "markdown": "# Change requests: <title> (rev B), <date>\n\n1. **<label>** (pin)\n   > <text>\n   Change: <note>\n" }
```

| Key | Points at (JSON) |
|---|---|
| `header`, `tldr`, `status` | `title`/`subtitle`, `tldr`, `state`/`links` |
| `section:<id>`, `heading:<id>`, `lead:<id>` | a section, its `title`, its `lead` |
| `block:<sectionId>/<i>` | `sections[id].blocks[i]` |
| `block:<checklist>/<item>/<k>` | `blocks[k]` inside that checklist item |
| `item:<checklist>/<item>` | a checklist item |
| `row:<blockPath>/<r>`, `card:<blockPath>/<i>`, `para:<blockPath>/<i>` | a table row, a card, a paragraph or list item of that block |
| `node:<canvasId>/<nodeKey>` | a canvas node (`nodeKey` nests with `/`) |
| `line:<diffId>/<path>:<n>` (`o<n>` = removed line), `comment:<diffId>/<i>` | a diff line, a review comment |
| `step:<blockPath>/<stepId>` | a step of a `steps` block |
| `file:<blockPath>/<path>` | a row of a `files` block (`path` as written) |
| `media:<blockPath>` | a `media` block |
| `compare:<blockPath>/before`, `compare:<blockPath>/after` | one pane of a `compare` block |

`<blockPath>` is `<sectionId>/<i>`, or `<checklist>/<item>/<k>` for a block inside a checklist item, as in `block:` and `row:`.

### Bottom tray

On the current revision the tray's last keys depend on the page. The `?diff=` tray (compare view) and `?rev=` (no tray) don't change.

| Page | Tray |
|---|---|
| Plan page | View · Point · Select · Draw │ eye (hide or show comment marks) │ **Request changes · N** · **Approve plan** (green) |
| Other page with a checklist | View · Point · Select · Draw │ eye │ **Request changes · N** · **Send answers**: neutral with nothing to send, filled green once the reader picks, ticks or comments on something |
| Page without a checklist | View · Point · Select · Draw │ eye │ **Request changes · N** |

## Plans

A doc whose type is `plan` (`meta.type`, or derived from `meta.kind`) is a **plan page**: a proposal the reader approves or sends back. `types/plan.md` gives the layout and the approval loop.

A status chip sits next to the eyebrow:

| Chip | When |
|---|---|
| **Plan · Awaiting approval** (amber) | No approval for the current `meta.rev`. |
| **Changes requested** (blue) | The reader sent Request changes on the current `meta.rev`. Stored in the browser under `bp:<doc.id>:__planstate` as `{rev, state, at}`. |
| **Approved · rev X** (green) | The saved approval is for the current `meta.rev`. |

**Approve plan** opens a dialog titled "Approve this plan (rev X)": an optional note, a summary ("N pending comments go with it as notes", and "M open questions have no pick; the agent will use its recommendation" when some decision items are unpicked), a preview of the decisions, **Copy**, and a green **Approve**. Approve posts `POST /__bluedoc/approve` with the header `X-Bluedoc: 1`:

```json
{ "kind": "approval", "decision": "approved", "doc": "<doc.id>", "rev": "1", "title": "…", "path": "/<root>/<path>.bluedoc.json",
  "at": "<ISO time>", "note": "Ship the API first.",
  "answers": [ { "checklist": "decisions", "item": "retention", "text": "…", "choice": "d180", "recommend": "d180" } ],
  "annotations": [ { "id": "c…", "type": "pin", "note": "…", "target": { "key": "step:steps/0/cutover", "label": "…", "text": "…" } } ],
  "markdown": "…" }
```

`answers` holds the same item objects as the `items` of Send answers (`checklist`, `item`, `text`, `choice`, `recommend`, `done`, `note`). `annotations` holds the pending annotations, in the change-request shape; once sent they turn **Open**, as after Request changes. The Markdown, leaving out any section that would be empty:

```md
# Plan approved: <title> (rev <rev>), <YYYY-MM-DD>

<note>

## Decisions
- <item text> → **<pick label>**
- <item text> → **<pick label>** (recommended: <label>)
- <item text> (no pick; recommended: <label>)
  > <the reader's comment on the item>

## Notes with the approval
1. **<label>** (pin|text|drawing|general)
   > <excerpt>
   Note: <note>
```

A pick carries `(recommended: …)` only when it differs from the recommendation; an item with no `recommend` and no pick reads `(no pick)`. Plain items the reader commented on are listed too. General comments come first in the notes; `> <excerpt>` is left out when there is none, and `(rev <rev>)` when the doc has no `meta.rev`.

The server writes `<name>.approval.md` and `<name>.approval.json` next to the doc (overwriting the last ones), queues the message with kind `approval` for `serve.py wait`, and answers `{ok, saved}`. The key then reads **Approved · rev X** with a check, disabled. A new `meta.rev` resets it: the plan awaits approval again.

- **Request changes** on a plan page also carries `answers` (the decision picks) when there are any, and its Markdown ends with the same `## Decisions` section. Plan pages have no Send answers.
- `GET /__bluedoc/ping?path=<doc URL path>` returns `{bluedoc, to, home, approval}`. `approval` is the doc's saved approval as `{rev, at}`, or `null`. The page counts the plan approved only when `approval.rev === meta.rev`.
- `serve.py wait DOC --kind answers|changes|approval|any` (default `any`) returns the oldest queued message of that kind. An approval prints `--- bluedoc approval (…json) ---`, the Markdown, then `--- end ---`.

## build.py

`python3 <skill>/scripts/build.py …`. Exit codes: 0 ok, 1 validation errors (or warnings with `--strict`), 2 usage or I/O error.

| Command | Does |
|---|---|
| `new <type> <out.bluedoc.json> [--title "…"] [--kind "…"]` | Copies `assets/skeletons/<type>.json`; sets `id` from the file name, `meta.rev` `1`, `meta.date` today, `meta.type`, and the title and kind when given. Refuses to overwrite; prints the next steps. The build fails until every `<<…>>` is filled. |
| `<doc>` | Validates (structure, ids, refs, links, media, diff anchors against the expanded diff, the [contract](#contracts)), lints the writing, records the revision. |
| `<doc> -o out.html` | Also writes a standalone page with expanded diffs and media inlined. It works from `file://`, where the reply dialogs offer **Copy** only. |
| `<doc> --check` | Validates and lints only. `--strict` fails on warnings; `--no-history` doesn't read or write the history file. |
| `<doc> --show-rev B` | Prints revision B, rebuilt from the history, as JSON. |
| `patch <doc> <key> …` | Changes one object by key, bumps the rev, validates, records. See below. |

The linter warns on: filler and ceremony words; vague words; sentences over 32 words; a `tldr` or `lead` opening with "This section/doc/document/page" or "In this …"; a last section (of 2+) titled Summary, Conclusion(s), Wrap-up, Recap or Closing thoughts; a text block with 3+ numbered lines (make it a checklist); checklist text or sub with "if you agree", "do you agree", "confirm whether"; checklist and step titles that don't start with a verb or end in `?`; titles over 90 characters, subtitles over 120, option labels over 28.

### patch

`build.py patch <doc> <key> [--set field=value …] [--json '{…}'] [--append '{…}'] [--delete] [--change "line" …] [--no-bump]`

| Option | Effect |
|---|---|
| `--set field=value` | Sets one field of the target; `value` is parsed as JSON when it parses, else used as a string. `null` deletes the field. |
| `--json '{…}'` | Merges the object into the target (`null` deletes). |
| `--append '{…}'` | Appends to the target's list: doc → `sections`; section or item → `blocks`; table → `rows`; canvas → `nodes`; diff → `comments`; other blocks → `items`. |
| `--delete` | Removes the target. |
| `--change "line"` | One `changes` line; repeatable. |
| `--no-bump` | Keeps `meta.rev`: only while the reader hasn't seen this rev. |

By default the rev bumps (1→2, A→B, v1→v2), `meta.date` becomes today, and `changes` becomes the `--change` lines (default "Updated `<key>`."); with `--no-bump` the lines are appended. Patch refuses to write when validation fails, keeps the file's indent, records the history, and prints `rev X → Y; <key> updated`.

Keys are the annotator's (see [Annotations](#annotations)), so a change request's `key` works as is: `doc`, `meta`, `header`, `tldr`, `status` (the last three address the top level), `section:<id>` (`heading:`, `lead:` too), `block:<blockPath>`, `item:<checklist>/<item>`, `row:<blockPath>/<r>`, `card:<blockPath>/<i>`, `para:<blockPath>/<i>`, `media:<blockPath>`, `compare:<blockPath>/<before|after>`, `step:<blockPath>/<stepId>`, `file:<blockPath>/<path>`, `node:<canvasId>/<nodeKey>`, `comment:<diffId>/<i>`. `<blockPath>` is `<sectionId>/<index>`, or `<checklist>/<item>/<index>` inside a checklist item.

```sh
build.py patch doc.json item:t412/tier-boundary --set choice=fix --change "#412 tier-boundary: Fix in PR, as picked."
build.py patch doc.json step:steps/0/table --set status=done --no-bump
build.py patch doc.json block:risks/0 --append '["Cache stampede", "Low", "High", "Jittered TTL"]'
```

## serve.py

`python3 <skill>/scripts/serve.py …`. One server per user on `127.0.0.1` (port 8740, env `BLUEDOC_PORT`); state in `~/.bluedoc` (env `BLUEDOC_HOME`).

| Command | Does |
|---|---|
| `open <doc> [--to NAME] [--root DIR] [--browser]` | Starts the server if needed, registers the topmost ancestor folder named `docs` (else the doc's folder, or `--root`) on the home page, prints the doc's URL. `--to` names who reads the replies. |
| `wait <doc> [--kind answers\|changes\|approval\|any] [--timeout SEC]` | Blocks until the reader sends that kind (default `any`). Prints `--- bluedoc answers (…json) ---`, `--- bluedoc change request (…json) ---` or `--- bluedoc approval (…json) ---`, the Markdown, `--- end ---`; exits 0, or 3 on timeout (`0` waits forever). Replies sent while nobody waits are queued; each `wait` returns the oldest unread one. |
| `start`, `stop`, `status`, `add DIR`, `roots`, `run [--port N]` | Manage the background server and the home page's folders. |

Each render validates the doc (errors show as a page), records its rev like `build.py`, and expands diff references. Replies are saved next to the doc, overwritten each time: `<name>.reply.md/.json` (answers), `<name>.changes.md/.json`, `<name>.approval.md/.json`. They are the reader's messages: don't commit them.

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
| `BP.revisions()` | `[{rev, date, current, shown, changes}]`, oldest first. |
| `BP.compare()` | With `?diff=`: `{from, to, changes: [{kind: 'add'|'mod'|'del', label}]}` in page order; else `null`. |
| `BP.annotations()` | The reader's annotations, sent and unsent. |
| `BP.changesPayload()` | The change-request JSON that **Request changes → Send** posts (unsent annotations). |
| `BP.annotate({type, key, note, quote?})` | Adds an annotation, as the toolbar would. `null` on `?rev=` / `?diff=`. |
| `BP.setMode('view'|'point'|'select'|'draw')` | Switches the toolbar mode. |
| `BP.acceptRecommended(checklistId?)` | Picks the recommended option on every open decision (in that checklist and its nested ones, or the whole doc); returns how many. |
| `BP.sidebar({open})` | Opens/closes the Comments panel at the window edge; returns `{available, open, section, as}`. |
| `BP.revisionsRail({open})` | The Revisions rail beside the content (docs with 2+ revisions): rail, drawer or card; returns `{available, as, open}`. |
| `BP.docType` | Property: the page's type, `'docs'`, `'review'`, `'plan'` or `'other'`. |
| `BP.planState()` | `{type, state, rev, approvedRev}`. `state` is `'awaiting'`, `'changes'` or `'approved'` on plan pages, `null` elsewhere; `approvedRev` is the rev of the approval the page knows (from the server's ping or this browser), else `null`. |
| `BP.approvePayload(note?)` | The body **Approve** posts to `/__bluedoc/approve`. |
