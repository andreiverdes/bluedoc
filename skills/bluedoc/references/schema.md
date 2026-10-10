# bluedoc JSON schema

Lookup reference for every field and command. Grep for a heading, never read the file whole: `grep -n -A25 '^## Diff' references/schema.md`. How to lay out each doc type lives in `types/<type>.md`.

Headings: `## Document` (incl. `hero`) · `## Contracts` · `## Section` · `## Blocks` (`### Inline markdown`) · `## Checklist` (`### Reader comments and replies`) · `## Diff` (`### Diff reference`, `### Embedded diff`, `### gitdiff.py`) · `## Plan blocks` (`### Steps`, `### Files`, `### Media`, `### Compare`) · `## Board` (`### Artboard`, `### Devices`, `### Screen files`) · `## Revisions` · `## Page layout` · `## Canvas` (`### Node`, `### Semantic zoom`, `### Edge`, `### Flow`) · `## Annotations` (the key grammar; `### Bottom tray`) · `## Plans` (its approval Markdown has `## Decisions` and `## Notes with the approval`) · `## build.py` (`### patch`) · `## serve.py` (`### Reader state`) · `## Automation API`

## Document

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | id | yes | Namespace for the reader's ticks, picks and comments (`bp:<id>:…` keys). Never change it after people start ticking. |
| `title` | string | yes | Page `<h1>` and browser title (`<title> · bluedoc`). |
| `subtitle` | inline md | no | One sentence under the title. |
| `meta` | object | no | `org`, `kind` (Architecture, Walkthrough, Runbook, Setup, Change, Plan, Review, or a free label), `dwg` (drawing number), `rev`, `date`, `type`. `org · kind · date` form the line above the title; `dwg` and `rev` appear under **Document** in the status rail and in the canvas title blocks. `rev` names the revision: the build keeps one history entry per `rev` (see Revisions). `type` (`docs`, `review`, `plan`, `design`, `other`) picks the doc's [contract](#contracts), its home-page group and card, and the page's tray; `build.py new` sets it. Unset, it is derived from `kind`, case-insensitive: starts with `plan` or is `implementation plan` → `plan`; contains `review` → `review`; names a docs kind (Architecture, Walkthrough, Runbook, Setup, Reference, Proposal, Change, Status, Guide, Design, Spec, RFC, ADR, …) → `docs`; anything else → `other`. `design` is never derived: only `"type": "design"` makes a [board](#board) page. A `plan` doc is a **plan page**: see [Plans](#plans). |
| `state` | `[{label, kind}]` | no | Provenance, listed under **Status** in the status rail as dots. `kind`: `ok` (green), `warn` (amber), `risk` (red), `info` (blue), `todo` (grey). Example: `{"label": "not live", "kind": "warn"}`. Keep each label under ~40 characters. |
| `links` | `[{label, href}]` | no | Related documents, listed under **Related** in the status rail. |
| `hero` | `{icon, value, label}` | no | The home card's stat, for `other` docs and for `docs` without a canvas. `icon`: `chart`, `doc`, `flag`, `bolt`, `clock`, `users`, `bug`, `box`, `check`, `globe`, `lock` or `list`. `value` ≤ 8 characters (`"99.95%"`); `label` ≤ 28 (`"uptime, last 30 days"`). Without it an `other` card shows the `doc` icon and the section count. |
| `tldr` | md | no | The answer in 1–3 sentences. Required in practice for documents longer than 3 sections. |
| `changes` | `[inline md]` | no | What changed in this revision and why, 1–4 lines. Shown in the revision list and above the marked diff. Rewrite it on each new `rev`. |
| `resolves` | `[comment id]` | no | The reader's comments this revision addresses, by the id the reply Markdown shows after each key (`c…`). On load, an **Open** comment listed by a revision newer than its own becomes **Resolved** ("Resolved by the agent in rev X"); see [Annotations](#annotations). Rewrite it on each new `rev`, like `changes`. |
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
| `design` | exactly one `board` block with ≥ 1 artboard | the board's outline: each artboard's device frame at its place |

A missing requirement is an **error** on the doc being built: a new `meta.rev` (not yet in its history file), or a recorded rev whose content changed (an edit in place). It is a **warning** only while the doc is exactly the revision its history recorded, so recorded revisions keep rendering. `build.py` and every server render apply the same rule. `build.py new <type>` writes a skeleton that meets the contract.

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
| `board` | see [Board](#board) | A design doc's UI mockups: artboards on a pan/zoom board, each an HTML screen file. Design docs only; not inside checklist items. |

### Inline markdown

`**bold**`, `*em*`, `` `code` ``, `[text](url)`. `[text](#node:<canvasId>/<nodeKey>)` scrolls to the canvas and opens that node. `[text](#code:<diffId>/<path>:<line>)` opens that file in a `diff` block and jumps to the line; `/<path>` and `:<line>` are optional. The same `#code:` URL works as a page link. No headings, images, or raw HTML (input is escaped). A URL with a scheme other than `http`, `https` or `mailto` (checked after stripping control characters and spaces) is a build error, here and in `links[].href` and a diff's `url`; `#…` and relative URLs are fine.

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

Every decision item also gets a **Need more details** toggle after its pills; the doc never declares it. It is not an option: it leaves the pick alone. On, the item's dot turns amber and its comment box takes focus to say what is missing (optional). It counts toward **Request changes** on every page with the tray, and the Markdown reads `- <text> \`item:<checklist>/<item>\` → **Need more details**`, then `; picked **<label>** (\`<id>\`)` when there is a pick, then the comment as a quote; the item's JSON entry carries `more: true`. Once sent (with Request changes or Send answers) it reads **Details requested** until a newer `meta.rev`, which resets it; clicking it then withdraws the request. On a plan or design, **Approve** is disabled while any item asks for more details, sent or not, and the server refuses (409) an approval whose `answers` carry `more`. Stored under `bp:<doc.id>:<checklist>:<item>:more` as `1`, then `sent@<rev>`; not on `?rev=` or `?diff=`.

A row with nothing to open has no chevron; clicking it ticks it. **Expand** in the checklist header opens or closes every row. Links to `#item-<checklist>-<item>` (from a canvas node, a table cell or a shared URL) open the row, and its parents, before scrolling to it. Print shows every row open.

Ticks persist across browsers and reloads: see [Reader state](#reader-state). The sidebar shows per-checklist progress; **Copy progress** exports all checklists as Markdown task lists (`- [x] …`) for PRs or issues.

A reader's tick is stored only when it differs from the item's `done`, together with the `done` it overrode. If the author later changes `done`, the author wins and the old tick is dropped, so marking a step done in a new revision shows as done for readers who unticked it earlier. Picks follow the same rule against `choice`, and a pick is dropped when its option no longer exists.

### Reader comments and replies

Every item has a comment box at the bottom of its open body (and on its diff card); the two stay in sync. A row with a comment shows a speech-bubble icon. Comments are stored under `bp:<doc.id>:<checklist>:<item>:note`; **Reset** clears ticks and picks, not comments. The export quotes each comment under its item:

```md
- [x] `tierFor` gives no tier at exactly 10 or 50 units → **Ticket** (recommended: Fix in PR)
  > Ship it with the test first.
```

**Send answers** (the last key of the bottom tray, on pages with a checklist; plan pages don't have it) opens a dialog: a count of decisions, ticks and comments, an overall message (stored under `bp:<doc.id>:__message`, printed after the page title in the export), a Markdown preview, **Copy**, and **Send**. The key is neutral until the reader picks, ticks or comments on something, then turns green. Send appears only when the page is served by `scripts/serve.py` (the page probes `GET /__bluedoc/ping?path=…`); it posts to `/__bluedoc/reply`, and the server stores it in `state.db` and queues it for `serve.py wait`. The JSON:

```json
{ "kind": "answers", "doc": "<doc.id>", "rev": "<meta.rev>", "title": "…", "path": "/<root>/<path>.bluedoc.json", "at": "<ISO time>", "message": "…",
  "items": [ { "checklist": "t412", "item": "tier-boundary", "text": "…", "choice": "ticket", "recommend": "fix", "note": "…" },
             { "checklist": "local", "item": "doctor", "text": "…", "done": true } ],
  "markdown": "<the Copy progress text>" }
```
Decision items carry `choice` (null when undecided), `recommend`, and `more: true` when the reader asked for more details; plain items carry `done`; `note` appears only when the reader wrote one. Change requests from the annotator are a separate message: see "Annotations" below. On plan pages the picks travel with **Approve plan** or **Request changes** instead: see [Plans](#plans).

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
| `base`, `head` | Required. The reviewed range; `gitdiff.py` stores short SHAs. A branch or tag name is resolved to its commit for the cache key. |
| `paths` | Pathspecs that limit the diff. |
| `pr` | `owner/repo#N` or the PR URL, for the `gh pr diff` fallback. Without it, a `github.com/…/pull/N` `url` is used. |
| `url`, `note` | As in the embedded form. |
| `exclude`, `context`, `excerpt`, `max_lines` | `gitdiff.py` options, stored only when not the default (3 context lines, ±5 excerpt lines, 800 max lines). |
| `comments[]` | `{"at": "path:line[-end]", "item": "<checklist>/<item>"}`; `{"label": "…", "item": …}` for a whole-change comment; or the explicit fields of the embedded form. |

Expansion, in order: the cache `<name>.diffcache.json` next to the doc (one entry per `repo|base|head|paths`, holding the diff and only the source lines that comment excerpts show), then `git -C <repo> diff <base> <head> -- <paths>`, then `gh pr diff <pr>` when the repo or the commits are missing (refused when the PR's head isn't `head`). When none works, the block renders empty and the build reports an error. A build (not `--check`) and `patch` drop the cache entries and lines that no ref in the doc or its history reads. Diff line numbers must be integers. Commit the cache with the doc: it keeps the diff after a rebase or a deleted branch. Agents never read it. Every git call (`diffref.py`, `gitdiff.py`) runs as `git -c safe.bareRepository=explicit -c core.fsmonitor=false`, and diffs add `--no-ext-diff --no-textconv`, so a scanned repo's own config can't run a program. While expanding:
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
- `--into DOC --section ID [--after-block N]` writes the block into that section, replacing a block with the same `id`; without `--into` it prints the block. A missing `--section` fails before anything is written.
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

## Board

A design doc (`meta.type: "design"`) has a brief section and one `board` block. The page shows the board full width, the brief in its left panel.

```json
{ "type": "board", "id": "main", "targets": ["watch", "mobile", "web"], "framework": "plain",
  "frameworks": [ { "id": "acme-web", "label": "Acme web CSS", "files": ["../../web/dist/app.css"] },
                  { "id": "tailwind-heroui", "label": "Tailwind + HeroUI", "store": "tailwind-heroui" } ],
  "themes": [ { "id": "indigo", "label": "Indigo", "tokens": { "accent": "#4f46e5", "bg": "#f8fafc", "fg": "#0f172a" } } ],
  "motion": { "fast": "160ms", "base": "240ms", "slow": "400ms", "ease": "cubic-bezier(.2,0,0,1)" },
  "artboards": [ { "id": "login", "title": "Sign in", "device": "phone", "fidelity": "hifi" },
                 { "id": "login-b", "title": "Sign in, passkey first", "device": "phone", "fidelity": "wireframe", "variantOf": "login" } ] }
```

| Field | Meaning |
|---|---|
| `id`, `artboards` | Required. |
| `targets` | `watch`, `mobile`, `tablet`, `desktop`, `web`, `presentation`: what the design is for. |
| `framework` | The default for every artboard: `plain` (the kit that ships), `horizon` (HorizonUI, ships) or a `frameworks[].id`. Default `plain`. |
| `frameworks[]` | The reader's own: `{id, label, files}` with `.css`/`.js`/`.mjs` paths relative to the doc's folder (no URLs), or `{id, label, store}` naming a copy made by `serve.py add-framework <store> <path\|url>` in `~/.bluedoc/frameworks/<store>/`. A missing file or store is a build warning: those screens show the plain kit with a notice. |
| `themes[]` | `{id, label, tokens}`. Each token `k` (`^[a-z][a-z0-9-]*$`) becomes the CSS variable `--k` in every frame; values are CSS strings without `; { } < > \` or `url()`. |
| `motion` | `fast`, `base`, `slow`, `ease`: the CSS variables `--dur-fast`, `--dur-base`, `--dur-slow`, `--ease`. |

**The brief** is a section with the checklist `brief`. Its decision item `framework` offers framework ids (`plain`, `horizon`, `frameworks[].id`); its item `theme` offers exactly the `themes[].id`s. The build checks both. Other items (targets, motion, scope) are free.

### Artboard

| Field | Meaning |
|---|---|
| `id` | Required. Unique in the board; names the screen file and the keys `artboard:<id>`, `el:<id>/…`. |
| `title` | Required. Shown above the frame. |
| `fidelity` | Required. `sketch`, `wireframe` or `hifi`. |
| `device` | One of the [devices](#devices); or leave it out and give `w` and `h` (CSS px, no frame). |
| `x`, `y` | Board px, both or neither. Without them the board places it: a `slide` goes 280 px below the previous unplaced slide, in one column (x 0 on a board of only slides, else 80 px right of every other artboard); any other artboard's row is its `variantOf` source's `y` (if listed before it), else 0, and it goes 80 px right of the rightmost artboard already in that row. |
| `variantOf` | Another artboard's id: a variant of that screen. |
| `framework` | Overrides the board's `framework`. |
| `src` | The screen file, relative to the doc: an `.html` file in a `<name>.design/` folder. Default `<stem>.design/<id>.html`; leave it out. |
| `notes` | md, at most 2 KB (an error above): the speaker notes of a slide. **Present** shows them under it (`N` toggles). |

### Devices

| `device` | Size (CSS px) | Safe area (top, right, bottom, left) |
|---|---|---|
| `watch-round` | 240 × 240 | the inscribed square (`--safe-inset`) |
| `watch-square` | 198 × 242 | 8, 8, 8, 8 |
| `phone` | 390 × 844 | 47, 0, 34, 0 |
| `tablet` | 820 × 1180 | 24, 0, 20, 0 |
| `desktop` | 1280 × 800 | 32, 0, 0, 0 (title bar) |
| `browser` | 1440 × 900 | 72, 0, 0, 0 (tab strip, address bar) |
| `slide` | 1920 × 1080 | none; a thin frame, no device chrome. Other aspect ratios: `w` and `h` |

A board with `slide` artboards is a deck: **Present** shows them full-window, scaled to fit, in reading order (rows top to bottom, each left to right, as the board places them); ← → step, `Esc` leaves. Kit slide classes: `references/kits.md` `## Slides`.

### Screen files

Each artboard's HTML is a **body fragment** in `<stem>.design/<id>.html` beside the doc (`acme-fit-design.bluedoc.json` → `acme-fit-design.design/login.html`). The server wraps it in the kit (doctype, viewport, safe areas, framework files, theme and motion tokens, inspector) and serves it in a sandboxed frame with no network. Put `data-bd="<name>"` on every element a reader may point at; the annotator names elements by them. Kit classes: `references/kits.md`.

The build checks every screen file. **Errors:** a missing file; a network URL (`http:`, `https:`, `ws:`, `ftp:` or `//host` in a URL attribute, a `style`, an `on…` handler, a `<style>` or a `<script>`); `<base>`, `<iframe>`, `<frame>`, `<object>`, `<embed>`, `<meta http-equiv>`, `<form action>`; a whole document (`<!doctype>`, `<html>`, `<head>`, `<body>`). **Warnings:** a file over 24 KB; a file without any `data-bd`. Text content and `placeholder`s may show URLs.

An approval covers the screen files too: editing one changes the doc's hash, so the page asks for approval again.

## Revisions

Every `build.py doc.bluedoc.json` run records the document in `doc.bluedoc.history.json` under its `meta.rev`: a new `rev` appends a revision, the same `rev` replaces the last one. A server render shows the doc as the latest revision without writing the history file. A `rev` that is already an earlier revision fails the build (and shows as an error page). No `meta.rev`: no history. The history file stores each revision's header and section fields once per revision and each block once across all revisions (by content hash); the page embeds the revisions other than the current one, with blocks the current one still has as references, so a page with ten small edits grows by roughly the edited blocks. A design doc's revision also maps each artboard to its screen file's hash (`screens`), and the file's text sits once in the history's `html` pool; editing a screen under the same `rev` is an edit in place. The page gets only the hashes and loads an old screen from the server with `?rev=`.

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

The tray of keys at the bottom of the current revision has four modes: **View** (`V`, default), **Point** (`C`: pin a note on the element under the cursor), **Select** (`T`: note on a selected passage), **Draw** (`D`: freehand drawing with a note). `Esc` returns to View. A new note is written in a small composer next to its mark; once saved it becomes a card in the **Comments** sidebar on the right (open by default and docked beside the content on wide screens, a drawer or bottom sheet on narrow ones; the sidebar button in the app bar or `]` shows and hides it). Comments are **Pending** (saved, not sent), **Open** (sent with Request changes) or **Resolved** (marked by the reader, or by a revision's `resolves`: see below); the sidebar filters Pending · Open · Resolved · All. Each is stored under its own key, `bp:<doc.id>:__ann:<id>`, so two browsers adding notes don't overwrite each other. The sidebar footer has a **General comment** field for notes about the whole doc (`type: "general"`, `target.key: "doc"`, no page mark); they follow the same states. **Request changes · N** in the bottom tray sends the pending ones, through a dialog with a preview, **Copy** and **Send**; `message` repeats the general notes joined with blank lines, and the Markdown lists them first under `## General`. N also counts what goes with them besides annotations: on a plan or design, each item comment written or changed since the last Request changes or Approve (the page keeps a hash of the comment it sent under `<checklist>:<item>:note-sent`), and on every page, each decision item marked **Need more details** and not yet sent (see [Checklist](#checklist)). Either alone enables the key, and the dialog counts them ("1 comment on items", "2 requests for more details"). On other pages `answers` holds only the Need more details items, and the Markdown ends with them under `## Decisions`. Send posts to `/__bluedoc/changes`; the server stores it in `state.db` and queues it for `serve.py wait`. Sent notes stay dimmed until the reader clears them. The toolbar is absent on `?rev=` and `?diff=`.

```json
{ "kind": "changes", "doc": "<doc.id>", "rev": "B", "title": "…", "path": "/<root>/<path>.bluedoc.json", "at": "<ISO time>", "message": "…",
  "annotations": [ { "id": "c…", "type": "pin", "note": "Say which rounding mode.", "rev": "B", "at": "…",
                     "target": { "key": "item:t412/float-cents", "label": "02 #412 · bulk discount tiers › Findings · #412 › 2. Tiered line totals…", "text": "Tiered line totals are fractional cents …" } },
                   { "type": "text", "quote": "one-line fixes", "target": { "key": "tldr", … }, … },
                   { "type": "draw", "target": { "key": "block:trouble/0", … }, "targets": [ { "key": "row:trouble/0/0", … }, { "key": "row:trouble/0/1", … } ], … } ],
  "markdown": "# Change requests: <title> (rev B), <date>\n\n1. **<label>** (pin) `<key>` (<id>)\n   > <text>\n   Change: <note>\n" }
```

Each comment in the Markdown carries its `id` after its key (a general one: `- (<id>) <note>`). Once a revision addresses it, list the id in that revision's `resolves` (`build.py patch … --resolves <id>`). When the page loads, each **Open** comment whose id is in the `resolves` of a revision newer than the comment's `rev` (up to the current one) becomes **Resolved** with `resolvedBy: "agent"`, `resolvedRev` (the newest such revision) and `resolvedAt`, saved like any reader change; its card reads "Resolved by the agent in rev X" and keeps **Reopen**. A reopened comment keeps `resolvedRev`, so only a revision after that one resolves it again. Pending comments are never resolved this way, and ids that match no comment are ignored. The revision list shows "Resolves N comments" under a revision that has `resolves`.

The key grammar. This table is the one list of keys: the annotator writes them into change requests and `build.py patch` takes them as is.

| Key | Points at (JSON) |
|---|---|
| `doc` | the whole doc (general comments; `patch` targets the top level) |
| `meta` | `meta` (`patch` only; the annotator never writes it) |
| `header`, `tldr`, `status` | `title`/`subtitle`, `tldr`, `state`/`links` |
| `section:<id>`, `heading:<id>`, `lead:<id>` | a section, its `title`, its `lead` |
| `block:<sectionId>/<i>` | `sections[id].blocks[i]` |
| `block:<checklist>/<item>/<k>` | `blocks[k]` inside that checklist item |
| `item:<checklist>/<item>` | a checklist item |
| `row:<blockPath>/<r>`, `card:<blockPath>/<i>`, `para:<blockPath>/<i>` | a table row, a card, a paragraph or list item of that block |
| `node:<canvasId>/<nodeKey>` | a canvas node (`nodeKey` nests with `/`) |
| `comment:<diffId>/<i>` | a review comment of a `diff` block |
| `line:<diffId>/<path>:<n>` (`o<n>` = removed line) | a diff line. The code comes from git, so `patch` resolves it to the diff's comment on `<path>` whose range covers that line (same target as `comment:`); with none it exits 2: change the code, patch the finding (`item:`), or add a comment (`block:<blockPath> --append '{"at": "<path>:<n>", …}'`) |
| `step:<blockPath>/<stepId>` | a step of a `steps` block |
| `file:<blockPath>/<path>` | a row of a `files` block (`path` as written) |
| `media:<blockPath>` | a `media` block |
| `compare:<blockPath>/before`, `compare:<blockPath>/after` | one pane of a `compare` block |
| `artboard:<id>` | an artboard of the `board` (its screen file is `<stem>.design/<id>.html`) |
| `el:<id>/<path>` | an element in that artboard's screen file: `<path>` is `data-bd` names joined by `/` (`el:login/form/submit`), else a CSS path (`el:login/[data-bd="login"]>h1:nth-of-type(1)`). `patch` prints the file and the selector |
| `frame:<device>@<x>,<y>` | a requested empty frame at board px `x`,`y`; `<device>` is a device or `<w>x<h>`. `patch` appends an artboard there (`frame-<n>`, or `--set id=…`) and writes a wireframe stub screen file |

`<blockPath>` is `<sectionId>/<i>`, or `<checklist>/<item>/<k>` for a block inside a checklist item, as in `block:` and `row:`. `<i>`, `<k>` and `<r>` are 0-based.

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
| **Changes requested** (blue) | The reader sent Request changes on the current `meta.rev`. Stored under `bp:<doc.id>:__planstate` as `{rev, state, at}`. |
| **Approved · rev X** (green) | The saved approval is for the current `meta.rev`. |

**Approve plan** opens a dialog titled "Approve this plan (rev X)": an optional note, a summary ("N pending comments go with it as notes", and "M open questions have no pick; the agent will use its recommendation" when some decision items are unpicked), a preview of the decisions, **Copy**, and a green **Approve**. Approve posts `POST /__bluedoc/approve` with the header `X-Bluedoc: 1`:

```json
{ "kind": "approval", "decision": "approved", "doc": "<doc.id>", "rev": "1", "docHash": "<sha256>", "title": "…", "path": "/<root>/<path>.bluedoc.json",
  "at": "<ISO time>", "note": "Ship the API first.",
  "answers": [ { "checklist": "decisions", "item": "retention", "text": "…", "choice": "d180", "recommend": "d180" } ],
  "annotations": [ { "id": "c…", "type": "pin", "note": "…", "target": { "key": "step:steps/0/cutover", "label": "…", "text": "…" } } ],
  "markdown": "…" }
```

`answers` holds the same item objects as the `items` of Send answers (`checklist`, `item`, `text`, `choice`, `recommend`, `more`, `done`, `note`). `annotations` holds the pending annotations, in the change-request shape; once sent they turn **Open**, as after Request changes. The Markdown, leaving out any section that would be empty:

```md
# Plan approved: <title> (rev <rev>), <YYYY-MM-DD>

<note>

## Decisions
- <item text> → **<pick label>**
- <item text> → **<pick label>** (recommended: <label>)
- <item text> (no pick; recommended: <label>)
  > <the reader's comment on the item>

## Notes with the approval
1. **<label>** (pin|text|drawing|general) `<key>` (<id>)
   > <excerpt>
   Note: <note>
```

A pick carries `(recommended: …)` only when it differs from the recommendation; an item with no `recommend` and no pick reads `(no pick)`. Plain items the reader commented on are listed too. General comments come first in the notes; `> <excerpt>` is left out when there is none, and `(rev <rev>)` when the doc has no `meta.rev`.

The server stores the approval in `state.db` with `docHash`, the sha256 of the doc's canonical JSON, queues it with kind `approval` for `serve.py wait`, and answers `{ok, id}`. The page posts the `docHash` its seed carried (the JSON it rendered) and its `rev`; when either differs from the file's current JSON or `meta.rev`, the server answers 409 `{"reload": true}` and the page offers **Reload** instead, so an approval never covers text the reader hasn't seen. The key then reads **Approved · rev X** with a check, disabled. A new `meta.rev`, or any edit of the doc's JSON in place, resets it: the plan awaits approval again.

- **Request changes** on a plan page also carries `answers` (the decision picks) when there are any, and its Markdown ends with the same `## Decisions` section, item comments included. An item comment counts toward it until sent with Request changes or Approve, and again once edited. Plan pages have no Send answers.
- `GET /__bluedoc/ping?path=<doc URL path>` returns `{bluedoc, home, version, code, unlocked, to, approval}`. `version` is the plugin's, `code` a hash of the server, build and template code; `serve.py open` restarts a server whose `version` or `code` differs and prints one line saying so. `unlocked` says whether this browser holds the key cookie (see [serve.py](#servepy)); while it doesn't, doc pages and the home page show "This browser can't save yet" with the commands that fix it. `approval` is the doc's newest approval as `{rev, at}` while the doc's JSON still matches its `docHash`, else `null`. The page counts the plan approved only when `approval.rev === meta.rev`.
- `serve.py wait DOC --kind answers|changes|approval|any` (default `any`) returns the oldest queued message of that kind. An approval prints `--- bluedoc approval (reply <id>, rev <rev>, <time>) ---`, the Markdown, then `--- end ---`.

## build.py

`python3 <skill>/scripts/build.py …`. Exit codes: 0 ok, 1 validation errors (or warnings with `--strict`), 2 usage or I/O error.

| Command | Does |
|---|---|
| `new <type> <out.bluedoc.json> [--title "…"] [--kind "…"] [--shape pr\|area] [--target T,…] [--framework F]` | Copies `assets/skeletons/<type>.json`; sets `id` from the file name, `meta.rev` `1`, `meta.date` today, `meta.type`, and the title and kind when given. `--shape area` (reviews only) copies `review-area.json`: a review by area of a codebase, diffed from the last release you reviewed to head. `design` only: `--target watch,mobile,tablet,desktop,web` (default `mobile`) writes one wireframe artboard and stub screen file per target; `--framework plain\|horizon\|<store name>\|auto` sets the board's framework and the brief's recommendation (`auto`, the default, leaves the pick to you: see `types/design.md`). Refuses to overwrite; prints the next steps. The build fails until every `<<…>>` is filled; shell shifts and heredocs (`<<EOF`) in code don't count, and inside backticks only a span that is exactly `<<x>>` does. |
| `<doc>` | Validates (structure, field types, ids, refs, links, media, diff anchors against the expanded diff, the [contract](#contracts)), lints the writing, records the revision. A field of the wrong JSON type is an error naming its path (`ERROR sections[0].blocks[2].items[1].text: 404 is a number: must be a string`), never a traceback. |
| `<doc> -o out.html` | Also writes a standalone page with expanded diffs and media inlined; a design's screens become `srcdoc` frames with their kit inlined (warns above 10 MB). It works from `file://`, where the reply dialogs offer **Copy** only. |
| `<doc> --check` | Validates and lints only; writes nothing (no history, no diff cache). `--strict` fails on warnings; `--no-history` doesn't read or write the history file. |
| `<doc> --show-rev B` | Prints revision B, rebuilt from the history, as JSON. |
| `patch <doc> <key> …` | Changes one object by key, bumps the rev, validates, records. See below. |

The linter warns on: filler and ceremony words; vague words; sentences over 32 words; a `tldr` or `lead` opening with "This section/doc/document/page" or "In this …"; a last section (of 2+) titled Summary, Conclusion(s), Wrap-up, Recap or Closing thoughts; a text block with 3+ numbered lines (make it a checklist); checklist text or sub with "if you agree", "do you agree", "confirm whether"; checklist and step titles that don't start with a verb or end in `?`; titles over 90 characters, subtitles over 120, option labels over 28.

### patch

`build.py patch <doc> <key> [--set field=value …] [--json '{…}'] [--append '{…}'] [--delete] [--html FILE|-] [--change "line" …] [--resolves ID …] [--no-bump]`

| Option | Effect |
|---|---|
| `--set field=value` | Sets one field of the target; `value` is parsed as JSON when it parses, else used as a string. `null` deletes the field. A text that parses as JSON (`404`, `true`) needs JSON quotes: `--set 'text="404"'`. |
| `--json '{…}'` | Merges the object into the target (`null` deletes). |
| `--append '{…}'` | Appends to the target's list: doc → `sections`; section or item → `blocks`; table → `rows`; canvas → `nodes`; diff → `comments`; board → `artboards`; other blocks → `items`. |
| `--delete` | Removes the target. An artboard's screen file stays (the history keeps its text); delete it yourself. |
| `--html FILE` | `artboard:` and `el:` keys: replaces the screen file with FILE's text (`-` reads stdin). The build lints it first; on an error the file is put back. |
| `--change "line"` | One `changes` line; repeatable. |
| `--resolves ID` | One comment id for `resolves` (the id after the key in the reply Markdown, with or without its parentheses); repeatable. |
| `--no-bump` | Keeps `meta.rev`: only while the reader hasn't seen this rev. |

By default the rev bumps (1→2, A→B, v1→v2), `meta.date` becomes today, `changes` becomes the `--change` lines (default "Updated `<key>`.") and `resolves` the `--resolves` ids (removed when there are none); with `--no-bump` both are appended. Patch refuses to write when validation fails, keeps the file's indent, records the history, and prints `rev X → Y; <key> updated`.

`<key>` is any key in the table under [Annotations](#annotations), so a change request's `key` works as is, with or without the backticks the reply Markdown puts around it.

Screen keys: `artboard:<id>` or `el:<id>/<path>` with no `--set`, `--json` or `--html` prints the screen file and the element's selector and writes nothing. After you edit that file, the same key with only `--change` records it as the next rev; the history keeps the old text under the old rev. `frame:` needs no option.

```sh
build.py patch doc.json item:t412/tier-boundary --set choice=fix --change "#412 tier-boundary: Fix in PR, as picked."
build.py patch doc.json step:steps/0/table --set status=done --no-bump
build.py patch doc.json block:risks/0 --append '["Cache stampede", "Low", "High", "Jittered TTL"]'
build.py patch doc.json el:login/submit                                  # prints acme-fit-design.design/login.html  [data-bd="submit"]
build.py patch doc.json el:login/submit --change "Sign in: the button says Continue."
build.py patch doc.json 'frame:phone@2400,0' --set id=settings --set title=Settings
```

## serve.py

`python3 <skill>/scripts/serve.py …`. One server per user on `127.0.0.1` (port 8740, env `BLUEDOC_PORT`); state in `~/.bluedoc` (env `BLUEDOC_HOME`): `roots.json`, `server.json`, `key` (mode 0600) and `state.db` (see [Reader state](#reader-state)). HTML pages carry a Content-Security-Policy (hashes of their inline scripts, `frame-ancestors 'none'`) and `X-Frame-Options: DENY`. A bad `Content-Length` or a request body that times out is a 400.

**The key.** Writes (`PUT /__bluedoc/state`, the answers, change-request and approve POSTs) and `GET /__bluedoc/wait` need the header `X-Bluedoc: 1` and the server's secret from the `key` file: the CLI sends it as `X-Bluedoc-Key`, a browser as the `bluedoc_key_<port>` cookie (HttpOnly, SameSite=Strict, 400 days, renewed on each page view). Without it the server answers 403 `{"key": true}`. A browser gets the cookie from a link with a one-time `?key=<token>` (good for 24 hours, used once): visiting it sets the cookie and redirects (303) to the same URL without the token. `ping` and `index.json` carry `unlocked`.

| Command | Does |
|---|---|
| `open <doc> [--to NAME] [--root DIR] [--browser]` | Starts the server if needed, registers the topmost ancestor folder named `docs` (else the doc's folder, or `--root`) on the home page, prints the doc's URL with a one-time `?key=` token. Give the reader that exact link. `--to` names who reads the replies. A folder inside a registered one is not added; a wider one is added next to the narrower ones, which keep their URLs: a doc's URL uses its deepest registered folder, and the home page lists it once. |
| `unlock` | Prints a home-page link with a one-time `?key=` token, for a browser that can't save yet (another browser, an expired cookie). |
| `wait <doc> [--kind answers\|changes\|approval\|any] [--timeout SEC]` | Blocks until the reader sends that kind (default `any`). Prints `--- bluedoc answers (reply <id>, rev <rev>, <time>) ---` (or `change request`, `approval`), the Markdown, `--- end ---`; exits 0, or 3 on timeout (`0` waits forever). Replies sent while nobody waits are queued, across restarts; each `wait` returns the oldest unread one. |
| `reply <id> \| <doc> [--kind K] [--json]` | Prints a stored reply as `wait` did: by the id `wait` printed, or the doc's newest (of kind `K`). `--json` prints the JSON the page posted. Exits 1 when there is none. |
| `start`, `stop`, `status`, `add DIR`, `roots`, `run [--port N]` | Manage the background server and the home page's folders. |

Each render validates the doc (errors show as a page), shows its rev as the latest without writing the history (only `build.py` records), expands diff references, and puts the doc's reader state in the page.

### Reader state

The reader's ticks, picks, item comments, annotations with their statuses, the general comment, the Send answers message, the plan state and the last-seen rev live in `~/.bluedoc/state.db` (SQLite, mode 0600), so clearing browsing data or opening another browser loses nothing. The page keeps a copy in `localStorage` and writes through to the server; unsent writes wait in `bp:<doc.id>:__outbox:<URL path>` until the server answers, so two docs with one `id` (a copy, a git worktree) each send only their own (the older per-id `__outbox` is taken over by the first page of that id). A write the server refuses with 403 `{"key": true}` (browser not unlocked) or 404 (no doc at that address now) stays queued and goes on the next focus or write; the reader sees one toast. A standalone `-o` file or a page without a server uses `localStorage` alone. Theme, content width, the Comments panel and its filter, and the pen colour (`bluedoc:*`) stay in each browser. Replies are rows in the same file, every one kept. A doc's state follows its path. A doc moved with its folder keeps it: the first write from the new path takes over the row of the one other path with the same `id` whose folder is gone; a read never moves a row, and a doc whose file alone is gone (a branch switch) keeps its row. The first start with a new `state.db` imports the `<name>.reply/.changes/.approval` files and `inbox.json` of earlier versions and leaves them in place. Copying `state.db` with the server stopped is a full backup.

Keys are the page's `bp:<doc.id>:` keys without that prefix: `<checklist>:<item>`, `<checklist>:<item>:note`, `<checklist>:<item>:note-sent`, `<checklist>:<item>:more`, `__ann:<id>`, `__message`, `__planstate`, `__seen`. Both routes need `X-Bluedoc: 1`, the server's own `Host`, and no foreign `Origin`, else 403; the PUT also needs [the key](#servepy). `path` must be a doc under a registered folder, else 404. An `__ann:<id>` value the page can't draw (no `target.label`, an unknown `type`, …) is dropped from a PUT (listed in the response's `dropped`) and left out of reads; the page likewise skips and logs such a stored comment and keeps working.

- `GET /__bluedoc/state?path=<doc URL path>[&since=<n>]` returns `{version, state: {key: value}}`, or 204 when `n` is the current version. The version rises by one with each PUT that changes a row. A served page seeds the same in its `bp-state` element, plus `docHash` (the sha256 of the JSON it rendered, which Approve posts).
- `PUT /__bluedoc/state` with `{path, import, ops: [[key, value], …]}` applies the ops in one transaction and returns `{ok, version}`. A `null` value deletes the key. `import: true` (each browser's one-time migration of its older `localStorage`) adds only keys the server lacks and drops item keys the doc doesn't have. Limits: 1 MB body (413), 2,000 ops, keys matching `^[a-z0-9_][a-z0-9:_-]*$`, string values up to 64 KB (400).
- A Python without `sqlite3`: the server prints one warning, pages carry no state, the state routes and reply POSTs answer 503, and Copy still works.

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
| `BP.moreDetails('t412/tier-boundary', on?)` | Turns **Need more details** on (default) or off, as its toggle would. `false` if the item has no choices, on `?rev=` / `?diff=`, or turning on one already sent; off withdraws a sent request. |
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
| `BP.sidebar({open, section})` | Opens/closes the right panel at the window edge, or opens it on `section` (`'comments'` or `'revisions'`); returns `{available, open, section, as}`. `available` lists the panel's tabs in order: `['comments', 'revisions']` on the current revision of a doc with a `meta.rev`, `['revisions']` on an earlier revision or in compare view (which open on it), `['comments']` without a `meta.rev`. `as` is `'dock'` (beside the page, > 1100 px), `'drawer'` (over it, 901–1100 px), `'sheet'` (bottom sheet, ≤ 900 px) or `null` when closed. The page remembers the reader's last tab and whether the panel was open; `]` and the app-bar key toggle it. |
| `BP.revisionsRail({open})` | The panel's Revisions tab (every doc with a `meta.rev`, one revision included; Compare appears from the second revision): `open: true` opens the panel on it, `open: false` closes the panel when it shows it; returns `{available, open, as}`, `as` as in `BP.sidebar` while the tab shows, else `null`. **Rev** in the app bar and the **Revision** link under Document do the same as a toggle. |
| `BP.docType` | Property: the page's type, `'docs'`, `'review'`, `'plan'` or `'other'`. |
| `BP.planState()` | `{type, state, rev, approvedRev}`. `state` is `'awaiting'`, `'changes'` or `'approved'` on plan pages, `null` elsewhere; `approvedRev` is the rev of the approval the page knows (from the server's ping or this browser), else `null`. |
| `BP.approvePayload(note?)` | The body **Approve** posts to `/__bluedoc/approve`. |
