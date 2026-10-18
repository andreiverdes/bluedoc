# bluedoc JSON schema

Lookup reference for every field and command. Grep for a heading, never read the file whole: `grep -n -A25 '^## Diff' references/schema.md`. How to lay out each doc type lives in `types/<type>.md`.

Headings: `## Document` (incl. `hero`, `emoji`; `### Reader title and emoji`) · `## Contracts` · `## Section` · `## Blocks` (`### Markdown`) · `## Checklist` (`### Evidence`, `#### Pinned evidence`, `### Reader comments and replies`) · `## Diff` (`### Diff reference`, `### Embedded diff`, `### gitdiff.py`) · `## Plan blocks` (`### Steps`, `### Files`, `### Media`, `### Compare`) · `## Board` (`### Artboard`, `### Devices`, `### Screen files`, `### Links`, `### Icons`, `### Website`) · `## Listing` (`### Style and brand`, `### Shots`, `### Uploads and captures`, `### Text and locales`, `### Checks`, `### Export`) · `## Revisions` · `## Page layout` · `## Canvas` (`### Node`, `### Semantic zoom`, `### Edge`, `### Flow`) · `## Annotations` (the key grammar; `### Bottom tray`) · `## Plans` (its approval Markdown has `## Decisions` and `## Notes with the approval`) · `## build.py` (`### patch`) · `## serve.py` (`### Reader state`) · `## Automation API`

## Document

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | id | yes | Namespace for the reader's ticks, picks and comments (`bp:<id>:…` keys). Never change it after people start ticking. |
| `title` | string | yes | Page `<h1>` and browser title (`<title> · bluedoc`). The reader may rename the doc on the page (see [Reader title and emoji](#reader-title-and-emoji)). |
| `emoji` | string | no | One emoji (`"🛒"`; ZWJ sequences, skin tones and flags included: at most 16 characters, no letters, digits or spaces) before the title in the header, the app bar and every home view. Unset, the type's: 📋 plan, 🔎 review, 📘 docs, 🎨 design, 🖥️ presentation, 🌐 website, 🛍️ storelisting, 📄 other. Set it with `build.py patch <doc> doc --set emoji=🛒`. |
| `subtitle` | inline md | no | One sentence under the title. |
| `meta` | object | no | `org`, `kind` (Architecture, Walkthrough, Runbook, Setup, Change, Plan, Review, or a free label), `dwg` (drawing number), `rev`, `date`, `type`. `org · kind · date` form the line above the title; `dwg` and `rev` appear under **Document** in the status rail and in the canvas title blocks. `rev` names the revision: the build keeps one history entry per `rev` (see Revisions). `type` (`docs`, `review`, `plan`, `design`, `presentation`, `website`, `storelisting`, `other`) picks the doc's [contract](#contracts), its home-page group and card, and the page's tray; `build.py new` sets it. Unset, it is derived from `kind`, case-insensitive: starts with `plan` or is `implementation plan` → `plan`; contains `review` → `review`; names a docs kind (Architecture, Walkthrough, Runbook, Setup, Reference, Proposal, Change, Status, Guide, Design, Spec, RFC, ADR, …) → `docs`; anything else → `other`. `design`, `presentation` and `website` are never derived: only `"type"` set to one of them makes a [board](#board) page. A `plan` doc is a **plan page**: see [Plans](#plans). |
| `state` | `[{label, kind}]` | no | Provenance, listed under **Status** in the status rail as dots. `kind`: `ok` (green), `warn` (amber), `risk` (red), `info` (blue), `todo` (grey). Example: `{"label": "not live", "kind": "warn"}`. Keep each label under ~40 characters. |
| `links` | `[{label, href}]` | no | Related documents, listed under **Related** in the status rail. |
| `hero` | `{icon, value, label}` | no | The home card's stat, for `other` docs and for `docs` without a canvas. `icon`: `chart`, `doc`, `flag`, `bolt`, `clock`, `users`, `bug`, `box`, `check`, `globe`, `lock` or `list`. `value` ≤ 8 characters (`"99.95%"`); `label` ≤ 28 (`"uptime, last 30 days"`). Without it an `other` card shows the `doc` icon and the section count. |
| `tldr` | md | no | The answer in 1–3 sentences. Required in practice for documents longer than 3 sections. |
| `changes` | `[inline md]` | no | What changed in this revision and why, 1–4 lines. Shown in the revision list and above the marked diff. Rewrite it on each new `rev`. |
| `resolves` | `[comment id]` | no | The reader's comments this revision addresses, by the id the reply Markdown shows after each key (`c…`). On load, an **Open** comment listed by a revision newer than its own becomes **Resolved** ("Resolved by the agent in rev X"); see [Annotations](#annotations). Rewrite it on each new `rev`, like `changes`. |
| `sections` | `[section]` | yes | Rendered in order, numbered 01, 02, … |

`id` everywhere = lowercase letters, digits, hyphens; starts with a letter or digit.

### Reader title and emoji

On a served page of the current revision the reader renames the doc and picks its emoji in place, in the `<h1>` and in the app bar's crumb (a board page's `<h1>` sits in its left panel): a click on the title (Enter or F2 on it) makes it a field, Enter or leaving it saves, Esc or an empty title restores; the emoji opens a picker (search, about 250 emoji by category, a line for any emoji). They save as reader state `__title` and `__emoji` ([serve.py](#servepy)), never through the agent: no reply carries them and the JSON stays as it is. The page, the tab and the home page show the reader's over the doc's own until the reader resets them with the picker's **Use the doc's emoji** / **Use the doc's title**, also after a rev that changes `title` or `emoji`; a renamed doc's home title has its own as the tooltip. `?rev=`, `?diff=` and an `-o` file show them as text (an `-o` file the doc's own).

### Archive

The reader archives a doc that's done from the app bar's ⋯ menu (**Archive**, no confirm; the toast offers **Undo**) or a home card's ⋯ menu. It saves as reader state `__archived` `{"at": <ISO time>, "rev": <meta.rev then>}` ([serve.py](#servepy)), never through the agent: the doc stays where it is, the JSON stays byte for byte, no reply mentions it, and replies still reach the agent. While archived, the page shows a banner under the app bar (*Archived on 18 Oct · it's hidden from the home page's views*, with **Unarchive**) and an **Archived** chip by the eyebrow; `?rev=`, `?diff=` and an `-o` export show none of it, and a doc without `meta.rev` can't be archived. An archive holds for the rev archived: when the agent writes a later rev the doc is back, the page says once *Back from the archive: rev N changed it.*, and the next state write drops the record. A plan, design, presentation, website or store listing that is all done (approved, every step done, every check ticked) offers *All done · Archive it?* on its page and home card, with **Archive** and **Not now**; **Not now** (`__archive-later`: the rev) holds until the next rev. bluedoc never archives by itself.

On the home page an archived doc leaves the default list, the board, the Type and Status chips' counts, the folder counts and the Overview widgets. The **Archived** status chip lists only archived docs (dimmed, with an **Archived** badge, and no Overview); the other filters still narrow it, and turning it off goes back to the status it replaced. When the search, type, status and folder would show archived docs, a line under the results says *N archived docs match · Show them* (in the empty state: *Nothing matches "x" · N archived docs do · Show them*); **Show them** turns on the Archived chip with the same search.

## Contracts

Each type's home card draws one element, so the build requires that element's data:

| `meta.type` | Required | Home card element |
|---|---|---|
| `review` | ≥ 1 `diff` block (reference or embedded); every checklist item with `choices` has `state` `blocker`, `major`, `minor` or `nit` | `+N / −N` lines, file and PR count, one dot per finding coloured by size |
| `plan` | a `steps` block and a `files` block | step timeline (status dot, effort bar), A/M/D/R file counts |
| `docs` | a `canvas` block, or `hero` | the root drawing with a flow on hover, the kind, the level count |
| `other` | nothing | `hero`; else the `doc` icon and the section count |
| `design` | exactly one `board` block with ≥ 1 artboard | the board's outline: each artboard's device frame at its place |
| `presentation` | exactly one `board` block with ≥ 1 artboard, every one `device: "slide"` (any other device is an error: use a design doc for screens) | the first 9 slides as 16:9 frames in deck order, the slide count and how many have notes |
| `website` | exactly one `board` block with ≥ 1 artboard, every one `device: "page"` (any other device is an error) | the first 4 pages as browser windows with their sections as bands, a green dot on live ones; the page, section and live counts |
| `storelisting` | exactly one `listing` block and one `board` block with ≥ 1 artboard, every one `device` `shot`, `asset` or `icons` | a column per platform (Google Play, App Store) with a dot per section (text, Shared, each device row) coloured by its worst check; the platform, shot and store-error counts |

A missing requirement is an **error** on the doc being built: a new `meta.rev` (not yet in its history file), or a recorded rev whose content changed (an edit in place). It is a **warning** only while the doc is exactly the revision its history recorded, so recorded revisions keep rendering. `build.py` and every server render apply the same rule. `build.py new <type>` writes a skeleton that meets the contract.

## Section

`{ "id", "title", "lead"?, "blocks": [block] }`. `lead` is one line of inline md under the heading.

## Blocks

| `type` | Fields | Use for |
|---|---|---|
| `text` | `md` | Prose in [Markdown](#markdown): paragraphs, lists, tables, code, quotes. |
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
| `listing` | see [Listing](#listing) | A storelisting's store text, locales, captions, brand and style. Storelisting docs only; not inside checklist items. |

### Markdown

Fields marked **md** (`tldr`, `text`, `callout`, `terms`, `cards`, item `detail`, step and evidence `md`, compare sides, canvas node `md`, comment `md`, a diff's `note`, speaker `notes`) take block Markdown; fields marked **inline md** (titles, subtitles, `lead`, cells, captions, labels) take the inline part only. One renderer draws both, the page's and `serve.py`'s alike (`tests/fixtures/markdown-cases.json`).

- **Blocks**, with or without a blank line between them (a list or a table may start right under a paragraph line): paragraphs (a single newline stays inside one); `-`, `*` or `+` bullets and `1.` or `1)` numbered lists, nested by indenting 2+ spaces under the item, a line indented under an item continuing it; task items `- [ ]` / `- [x]` (read-only boxes); GFM tables (header row, a `---` / `:---` / `:---:` / `---:` delimiter row, body rows; outer pipes optional, `\|` for a pipe in a cell, short rows padded, cells take inline md) in the `table` block's look, scrolling sideways when wide; fenced code (` ``` ` or `~~~`, optional language) in the `code` block's look with Copy; `>` quotes, nestable; `---`, `***` or `___` alone on a line as a rule (never a heading: no setext headings).
- **Headings** stay under the section and block titles: `#` draws as `h4`, `##` as `h5`, `###` to `######` as `h6`.
- **Inline**: `` `code` ``, `**bold**` / `__bold__`, `*em*` / `_em_` (`_` only at word edges, so `snake_case` stays), `~~strike~~`, `[text](url)`, `<https://…>` autolinks, bare `https://…` URLs, `\` escapes, and a line break from two trailing spaces or a trailing `\`. Web links open in a new tab. `[text](#node:<canvasId>/<nodeKey>)` scrolls to the canvas and opens that node. `[text](#code:<diffId>/<path>:<line>)` opens that file in a `diff` block and jumps to the line; `/<path>` and `:<line>` are optional. The same `#code:` URL works as a page link.
- **Not rendered**: images, indented code blocks, setext headings, raw HTML (input is escaped). A URL with a scheme other than `http`, `https` or `mailto` (checked after stripping control characters and spaces) is a build error, here and in `links[].href` and a diff's `url`; `#…` and relative URLs are fine. Fenced code is never linted or link-checked.

## Checklist

Each item is a collapsed row: a tick, a one-line **title** (`text`), a one-line **subtitle** and an optional chip. Clicking the row opens everything else. Write the row so a reader can scan the list without opening anything.

A checklist is one of two kinds, read from its items:

| Kind | Items | On the page |
|---|---|---|
| **Decision list** | Every item has `choices`. | A question icon, an accent edge, **Needs your answer** and `N open` (then **All answered**) instead of a bar. A chip under the doc's title, "N questions need your answer", goes to the first open one; it hides once the doc is approved. |
| **Progress list** | No item has `choices`. | Its bar and `n of m`. A section-level one gets a caption: on a plan, design, presentation or website, "The agent marks these as the work lands. Your ticks stay on this page and don't change the approval."; elsewhere "Your own tracker: ticks are saved for you and go with Send answers." |

A checklist with both kinds of item is a build error on a new rev (a warning on revisions recorded before the rule): split it in two. A nested checklist is classified on its own. The build warns when a section-level decision list comes after a progress list: put what needs the reader's answer first.

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
| `detail` | open | Extra md: paragraphs, lists, tables, code, links. |
| `code`, `lang` | open | Command to run for this step, with a Copy button. |
| `blocks` | open | Any of `text`, `callout`, `table`, `code`, `terms`, `cards`, `files`, `media`, `compare`, `checklist`. A nested checklist ticks on its own, counts in the page total when it is a progress list, and exports indented under its parent; nested checklists can't nest again. |
| `verify` | open (or row line 2) | Observable success check (output, state, file). Required for steps whose failure is silent. Shown as **Check** when the row is open, unless it already fills line 2. |
| `refs` | open | `"<canvasId>/<nodeKey>"`; renders buttons that open that node. Node keys nest with `/`: `arch/api/auth`. |
| `done` | | Initial tick before the reader touches it (e.g. steps the author already verified). Not for decision items. |
| `evidence` | open | Optional proof the item landed: see [Evidence](#evidence). Progress items only. |
| `choices` | row, line 3 | Makes the item a **decision**: 2–6 options `{id, label, md?}` shown as pills instead of a tick. Label ≤ 28 characters; `md` is the tooltip. The reader picks one; picking it again clears it. A picked item counts as answered. Every item of a decision list has `choices`; no item of a progress list has. |
| `recommend` | row, line 3 | The id of the recommended option, starred. |
| `choice` | | A pre-picked option, like `done` for ticks. Use it only to carry over the reader's answer from an earlier round; leave it unset when the reader has not decided. Changing it in a new revision overrides the reader's stored pick. |

```json
{ "id": "double-auth", "text": "A retry can authorize the card twice", "sub": "Recommend fix in PR: a timeout after PayCo accepted becomes a second charge.",
  "state": "blocker", "stateKind": "risk", "recommend": "fix",
  "choices": [ { "id": "fix", "label": "Fix in PR" }, { "id": "ticket", "label": "Ticket" }, { "id": "decline", "label": "Decline" } ] }
```

A decision item's title states the finding or question, not an action. **Copy progress** writes the pick: `- [x] A retry can authorize the card twice → **Fix in PR**`, adds `(recommended: …)` when the pick differs, and `(no decision; recommended: …)` when there is none. In a `diff` block, the comment card for a decision item carries the same pills, kept in sync with the row. On a review, a section's findings show as **Merged** (each finding's full row under its lines), as the checklist or as the diff (**[Merged][Checklist][Diff]** in a bar under the section's title), and in Checklist an open finding shows its lines and that card: see [Diff](#diff).

Every decision item also gets a **Need more details** toggle after its pills; the doc never declares it. It is not an option: it leaves the pick alone. On, the item's dot turns amber and its comment box takes focus to say what is missing (optional). It counts toward **Request changes** on every page with the tray, and the Markdown reads `- <text> \`item:<checklist>/<item>\` → **Need more details**`, then `; picked **<label>** (\`<id>\`)` when there is a pick, then the comment as a quote; the item's JSON entry carries `more: true`. Once sent (with Request changes or Send answers) it reads **Details requested** until a newer `meta.rev`, which resets it; clicking it then withdraws the request. On a plan or design, **Approve** is disabled while any item asks for more details, sent or not, and the server refuses (409) an approval whose `answers` carry `more`. Stored under `bp:<doc.id>:<checklist>:<item>:more` as `1`, then `sent@<rev>`; not on `?rev=` or `?diff=`.

A row with nothing to open has no chevron; clicking it ticks it. **Expand** in the checklist header opens or closes every row. Links to `#item-<checklist>-<item>` (from a canvas node, a table cell or a shared URL) open the row, and its parents, before scrolling to it. Print shows every row open.

Ticks persist across browsers and reloads: see [Reader state](#reader-state). The sidebar shows per-checklist progress (`n/m`, or `N open` for a decision list) and the top bar the page's progress items; **Copy progress** exports all checklists as Markdown task lists (`- [x] …`) for PRs or issues, decision lists first.

A reader's tick is stored only when it differs from the item's `done`, together with the `done` it overrode. If the author later changes `done`, the author wins and the old tick is dropped, so marking a step done in a new revision shows as done for readers who unticked it earlier. Picks follow the same rule against `choice`, and a pick is dropped when its option no longer exists.

### Evidence

A step or progress item may carry `evidence`: what shows the work landed. It is optional; `done` never needs it.

```json
"evidence": [
  { "label": "Migration test", "code": "pytest tests/test_migrations.py", "md": "`4 passed in 1.2s`",
    "pin": { "repo": "..", "commit": "0a46a97f3dfbb4636547ea05323edb3c19b052bf", "dirty": false, "paths": ["src/carts"], "at": "2026-10-17T09:30:00Z" } },
  { "label": "Cart page at 390 px", "src": "media/cart-390.png" },
  { "label": "Review findings", "href": "../reviews/saved-carts.bluedoc.json" }
]
```

| Field | Meaning |
|---|---|
| `label` | Required. What the entry shows, inline md. |
| `md` | Embedded: output, a note, a result. |
| `code`, `lang` | Embedded: the command that produced it, with Copy. |
| `src` | Embedded: an image or video beside the doc, checked like a [media](#media) `src`; `-o` inlines it. |
| `href` | Linked: a path relative to the doc's folder or an `http(s)` URL. The build warns when a local path doesn't exist. |
| `pin` | The code revision the check ran on: `build.py patch` stamps it (see [Pinned evidence](#pinned-evidence)); never write it by hand. |

Each entry needs `label` and at least one of `md`, `code`, `src`, `href`. The page shows an **Evidence** group in the open row or step, each entry tagged *embedded* or *linked*; a step's meta row counts them. A linked target is a pointer: nothing records its content, so it can change after the step is marked done. Embedded entries are part of the revision. Evidence on a decision item is a build error. Adding or changing evidence after an approval keeps it, like `status` and `done` (see [Plans](#plans)). **Copy progress** lists each entry as `- Evidence: <label> (<href or src>) @ <short sha>` under its item.

#### Pinned evidence

A passing check proves something about the code it ran on, not the code after it. So `build.py patch` pins each evidence entry it adds or changes to the code revision of the moment (`scripts/codepin.py`), and the page tells an older pass from a check of the current code.

| `pin` field | Meaning |
|---|---|
| `repo` | The git repo root: relative to the doc's folder when the doc is inside it (`.`, `../..`), else the root folder's name (`acme-shop`). A name is found through `$BLUEDOC_HOME/repos.json` (the stamp records it there), then as a folder of that name beside the doc. `patch --repo DIR` picks the repo; the default is the doc's, else the current folder's. |
| `commit` | The full HEAD sha when the check ran; `null` when there was none (no git, not in a repo, no commit yet), with `reason` saying why. |
| `dirty` | Whether the covered files differed from `commit` (uncommitted, staged or untracked changes). |
| `tree` | When dirty: sha256 over each such file's path and content, so the same uncommitted state reads as current and any other as stale. |
| `paths` | Optional: what the check covers, as paths or globs from the repo root (`patch --paths src/carts 'test/**/*.ts'`). Without it the check covers the whole repo. |
| `at` | When the evidence was recorded, UTC ISO time. |

bluedoc's own files (`*.bluedoc.json`, their history, diff cache and snapshots) never count as changes: recording evidence writes them. Old evidence without `pin` stays valid and shows as unpinned. The build checks a `pin`'s shape (a full sha or `null` with a reason, a relative or named repo, `tree` when dirty).

**Staleness.** Served pages (`serve.py`, cached per repo, HEAD and working-tree fingerprint) and `build.py --check-code` compare each pin with its repo now; the covered files are compared with `commit`, committed and uncommitted changes together:

| State | When | On the page |
|---|---|---|
| current | HEAD is still `commit`; the covered files are as checked (both clean, or the same `tree`). | A green chip: ✓ `abc1234` · its time. |
| moved | HEAD moved past `commit`, but no covered file changed. Still valid. | A plain chip, and "Checked at abc1234, code since doesn't touch it". |
| stale | A covered file changed since `commit` (in later commits or uncommitted), `commit` is no longer an ancestor of HEAD (a rebase or reset) or no longer in the repo, or the uncommitted changes differ from `tree`. | An amber chip and "Stale: code changed since abc1234 (3 files)", the files listed when opened. |
| unknown | The repo isn't here, or git isn't installed. | A plain chip. |

A chip's tooltip has the full sha, the repo, the paths, the time and the state's reason; "+ changes" follows the sha when the check ran on uncommitted changes. An entry without a pin shows *unpinned*. A done progress item with stale evidence needs a recheck: its tick turns amber with **Needs recheck**, it doesn't count in the checklist's `n of m` (which adds `· N to recheck`), the sidebar tracker or the top bar, and Copy progress leaves it unticked. A done step with stale evidence shows **Needs recheck** and an amber dot. Approve warns ("2 checks have stale evidence") without blocking, and the approval, Request changes and Copy progress Markdown end with `## Stale evidence`: each such check, its changed files, its command to re-run, and the `build.py patch <doc> <key> --pin` commands that re-record its evidence (the first bumps the rev, the rest `--no-bump`). The plan gate (`hook.py`) adds the same section to what it tells Claude. Earlier revisions (`?rev=`) show the pins alone.

The static build (`-o`, and so the goldens in `docs/examples/`) has no repo state: it shows each pin's commit chip without a state. `build.py doc.json --check-code [-o out.html]` prints each pin's state and the stale ones' section, and gives an `-o` page the live states.

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
| `comments[].item` | `"<checklistId>/<itemId>"`. The card takes the item's text, chip, detail and tick; ticking either one ticks both. In a findings section (below) Merged shows the item's full row under the comment's lines and the open item in Checklist shows the comment's code; elsewhere the item gets a code button that opens the comment. |
| `comments[].title`, `md`, `kind`, `state`, `label` | A comment with no `item`: its own title, body, colour (`ok`, `warn`, `risk`, `info`, `todo`) and chip. `label` names a whole-change anchor. |

The validator checks, on the expanded diff, that every anchored line is shown, every `item` exists, and every `#code:` link resolves.

In the page, a file header shows how many comments the file has and, with 2+, ‹ › buttons and "n of N" for the comment in view. While a file's comments sit outside the visible part of the code, a floating pill says "N more comments above/below"; clicking it scrolls to the nearest one.

A section holding a checklist and a `diff` whose comments are that checklist's items is a **findings section**. A bar under its title and lead, sticky under the app bar while the section is on screen, holds **[Merged][Checklist][Diff]**, and one of the three shows. The pick is stored per browser under `bluedoc:findings-view` (`merged`, `checklist` or `diff`) and applies to every findings section; with nothing stored it is Merged. On the first visit the bar says "New: findings and code together" until the reader's first click or key press (remembered under `bluedoc:findings-hint`). Print shows Merged.

- **Merged** shows the findings with their code in one column, ordered by the code: the findings on the whole change first, then per file (in the diff's file order: header with path, +/− and **Open in Diff view**) each commented range in line order, as the hunk lines ±3 around it with the commented lines marked, **Show more lines** (8 more either side, up to the hunk), and directly under them the finding's full row: tick or decision dot, title, subtitle, size chip, the options with the starred recommendation, **Need more details**, the comment box, and **Details** (the item's `detail`, `code` and check). A finding with several comments has a row at each place; the checklist's findings no comment points at come last under **Not tied to code**. Picks, ticks, comments, Need more details, **Accept recommended** (in Merged's header and the tray), the tracker and progress are the item's own, in sync with Checklist and Diff. Under 700 px the column stays single and the lines scroll sideways inside their box.
- **Links.** A link into a view that is not shown shows it in that section only. `#item-…` links, a card's **Checklist item** link and `item:` annotations stay in Merged, where every finding has a row, and scroll to it; from Diff they switch to Checklist. The tracker's rows lead to Merged while it shows, else to Checklist. `#code:` links, `BP.openCode`, `BP.openComment` and revealing a `line:` or `comment:` annotation switch to Diff, except that an annotation on a line or range Merged shows stays there. Merged's rows, ranges and lines carry the same keys (`item:<checklist>/<item>`, `comment:<diff>/<i>`, `line:<diff>/<path>:<n>`), so a pin shows on the one that is visible.
- **Checklist.** An open finding shows its code: for each comment on it, the file header, the hunk lines around the commented range (±3) and the comment card under them (same pills, tick and comment box as the row), with **Open in Diff view**. It is drawn on first open, and its lines and card carry the diff's annotation keys, so a pin shows in every view.

Nothing in the JSON changes.

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
| `items[].evidence` | Optional proof the step landed, embedded or linked: see [Evidence](#evidence). |

The page draws a numbered vertical timeline. Steps are the proposal, not a tracker: the reader can't tick them. Change `status` in a new revision as work lands, with `evidence` when there is some.

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

A design doc (`meta.type: "design"`) has a brief section and one `board` block. The page shows the board full width, its screens in the left panel and the brief in the right panel's **Brief** tab, before **Comments** and **Revisions**. A presentation (`meta.type: "presentation"`) is the same page whose board holds slides only: it says slides and deck where a design says screens, its toolbar's primary key is **Present**, and it is approved with **Approve presentation**. A design may still hold an occasional `slide`. A website (`meta.type: "website"`) is the same page whose board holds web pages only: see [Website](#website).

```json
{ "type": "board", "id": "main", "targets": ["watch", "mobile", "web"], "framework": "plain", "entry": ["login"], "layout": "flow",
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
| `targets` | `watch`, `mobile`, `tablet`, `desktop`, `web`, `presentation`: what the board is for (`presentation` on a presentation's board). |
| `framework` | The default for every artboard: `plain` (the kit that ships), `horizon` (HorizonUI, ships) or a `frameworks[].id`. Default `plain`. |
| `frameworks[]` | The reader's own: `{id, label, files}` with `.css`/`.js`/`.mjs` paths relative to the doc's folder (no URLs), or `{id, label, store}` naming a copy made by `serve.py add-framework <store> <path\|url>` in `~/.bluedoc/frameworks/<store>/`. A missing file or store is a build warning: those screens show the plain kit with a notice. |
| `themes[]` | `{id, label, tokens}`. Each token `k` (`^[a-z][a-z0-9-]*$`) becomes the CSS variable `--k` in every frame; values are CSS strings without `; { } < > \` or `url()`. |
| `motion` | `fast`, `base`, `slow`, `ease`: the CSS variables `--dur-fast`, `--dur-base`, `--dur-slow`, `--ease`. |
| `entry` | Artboard ids a flow starts from: where **Present** starts with nothing selected, and what [reach](#links) is counted from. |
| `layout` | `rows` (default) or `flow`: unplaced screens the entries reach go in columns by link depth (see `x`, `y`). |
| `breakpoints` | Website only. 1 to 6 distinct widths in CSS px, 240 to 3840 (default `[1440, 768, 390]`): the widths the toolbar and each page's title bar switch to. |
| `viewport` | Website only. `{"<width>": <height>}` in CSS px, both 240 to 3840: the design viewport height a page gets at that width (default 900 at 1440, 1024 at 768, 844 at 390; others by the width's device). In Full page, `vh`, `innerHeight` and the like answer it, so a `100vh` hero is as tall as in a browser window of that size. |
| `root` | Website only. The site's repo folder, relative to the doc (e.g. `".."`). Source hints are checked against it; a folder that isn't there is a warning. |

**The brief** is a section with the checklist `brief`. Its decision item `framework` offers framework ids (`plain`, `horizon`, `frameworks[].id`); its item `theme` offers exactly the `themes[].id`s. The build checks both. Other items (targets, motion, scope) are free.

### Artboard

| Field | Meaning |
|---|---|
| `id` | Required. Unique in the board; names the screen file and the keys `artboard:<id>`, `el:<id>/…`. |
| `title` | Required. Shown above the frame. |
| `fidelity` | Required. `sketch`, `wireframe` or `hifi`. |
| `device` | One of the [devices](#devices); or leave it out and give `w` and `h` (CSS px, no frame). |
| `x`, `y` | Board px, both or neither. Without them the board places it: a `slide` goes 280 px below the previous unplaced slide, in one column (x 0 on a board of only slides, else 80 px right of every other artboard); any other artboard's row is its `variantOf` source's `y` (if listed before it), else 0, and it goes 80 px right of the rightmost artboard already in that row. With `layout: "flow"`, the unplaced screens the entries reach come first: breadth-first from `entry` over every link but `back` (a variant joins its source, right under it), in columns by depth 200 px apart, stacked 120 px apart from y 0; row 0 of the rest moves 120 px below the lowest of them. |
| `variantOf` | Another artboard's id: a variant of that screen. |
| `framework` | Overrides the board's `framework`. |
| `src` | The screen file, relative to the doc: an `.html` file in a `<name>.design/` folder. Default `<stem>.design/<id>.html`; leave it out. |
| `notes` | md, at most 2 KB (an error above): the speaker notes of a slide. **Present** shows them under it (`N` toggles). |
| `url`, `source`, `sections` | Website pages only: see [Website](#website). |
| `icon` | `device: "icons"` only: `{bg, name}`. `bg`: the background colour, `#rgb` or `#rrggbb` (else a `bg.svg` layer); `name`: the label under the icon on the home screens, ≤ 30 characters. See [Icons](#icons). |

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
| `page` | 1440 × 900 at first, then the width the reader picks (height: that width's viewport) | none; a browser bar sits above the page, not over it. Website docs only |
| `icons` | 1280 × 860 | none; the [icon sheet](#icons), built from layers instead of a screen file |
| `shot`, `asset` | per set or asset: store px ÷ scale (see [Listing](#listing)) | storelisting docs only |

A board with `slide` artboards is a deck: **Present** shows them full-window, scaled to fit, in reading order (rows top to bottom, each left to right, as the board places them); ← → step, `Esc` leaves. Kit slide classes: `references/kits.md` `## Slides`.

### Screen files

Each artboard's HTML is a **body fragment** in `<stem>.design/<id>.html` beside the doc (`acme-fit-design.bluedoc.json` → `acme-fit-design.design/login.html`). The server wraps it in the kit (doctype, viewport, safe areas, framework files, theme and motion tokens, inspector) and serves it in a sandboxed frame with no network. Put `data-bd="<name>"` on every element a reader may point at; the annotator names elements by them. Kit classes: `references/kits.md`.

The build checks every screen file. **Errors:** a missing file; a network URL (`http:`, `https:`, `ws:`, `ftp:` or `//host` in a URL attribute, a `style`, an `on…` handler, a `<style>` or a `<script>`); `<base>`, `<iframe>`, `<frame>`, `<object>`, `<embed>`, `<meta http-equiv>`, `<form action>`; a whole document (`<!doctype>`, `<html>`, `<head>`, `<body>`). **Warnings:** a file over 24 KB; a file without any `data-bd`. Text content and `placeholder`s may show URLs.

An approval covers the screen files and icon layers too: editing one changes the doc's hash, so the page asks for approval again.

### Links

A link is an element's `data-nav`: tapping it leads to another artboard. The build reads every screen's links into one list, `[{from, el, to, kind, label?, edge?}]` (`el`: the element's `data-bd`; `to`: null for `back`; `edge`: a gesture link), in board then document order. Each revision records it; the board draws its arrows, **Present** follows its taps, compare marks its changes.

```html
<button data-bd="tab-activity" data-nav="tab:activity">Activity</button>
<button data-bd="start" data-nav="workout" data-nav-label="Tap Start workout">Start workout</button>
<i hidden data-bd="swipe-left" data-nav="tab:activity" data-nav-label="Swipe left"></i>
```

| `data-nav` | Arrow | In Present, a tap… |
|---|---|---|
| `workout` or `push:workout` | solid | slides the target in; Back returns |
| `modal:settings` | dashed | raises the target from the bottom; Back closes it |
| `tab:activity` | dotted | swaps in place; the back stack restarts at that tab |
| `replace:today` | solid, a bar at its start | swaps in place and clears the stack (sign-in, onboarding) |
| `back` | thin, the selected screen's only | pops the stack |

`data-nav-label` names the action ("Tap Start workout", "After 2 s"): a pill on the arrow, a hint in Present. A **gesture link** has nothing to tap: a `hidden` named element with a label; its arrow starts at the screen's border. A tab bar's current tab has no `data-nav`.

**Errors:** a `data-nav` that names no artboard; an unknown kind or `back:<target>`; `data-nav` on an element without a `data-bd` unique in its file; `data-nav-label` without `data-nav`; an `entry` that names no artboard; a `layout` other than `rows` or `flow`. **Warnings:** a link to its own screen; a hidden link without a label; a label over 40 characters; links but no `entry`; a screen no entry reaches (breadth-first over every kind but `back`). Reach skips entries, variants, slides, icons and devices with no links.

### Icons

An artboard with `device: "icons"` is an app icon: SVG layers in `<stem>.design/<id>/` instead of a screen file. The server composes them into the icon sheet (every platform's mask, variant and real size); the page exports the iOS and Android PNG sets to `<stem>.icons/<id>/`. `build.py new design --icons` scaffolds one.

| Layer | Meaning |
|---|---|
| `fg.svg` | Required. The logo on a transparent 108 × 108 layer (`viewBox="0 0 108 108"`; any square works); keep it inside the middle 66 dp circle. |
| `bg.svg` | The background, when `icon.bg` (one colour) isn't enough. |
| `mono.svg` | The mark in one colour: Android 13 themed and iOS tinted icons. |
| `ios-dark.svg`, `ios-tinted.svg`, `play.svg` | Optional overrides of the iOS dark and tinted icons and the Play Store icon. |

**Errors:** no `fg.svg`; a layer that isn't XML, has a DOCTYPE, or has no square `viewBox`; `<script>`, `<foreignObject>`, an `on…` attribute or a network URL in a layer; `icon` on another device; an `icon.bg` that isn't a hex colour. **Warnings:** `fg.svg` drawn outside the 66 dp safe circle (checked on shape extremes and path points, transforms applied; keep a margin); no `mono.svg`; no background (`icon.bg` or `bg.svg`); `<text>` (fonts don't load in an image: convert to paths). Each layer joins the revision as `<id>/<file>`, so editing one marks the icon Changed and asks for approval again. `patch el:<id>/<tile>` (a sheet tile, e.g. `ios-dark`) and `artboard:<id>` print the layer folder and its layers.

### Website

A website's board holds `page` artboards. Each page is either **live** (`url`) or a mockup (a screen file, as on a design).

```json
{ "id": "home", "title": "Home", "device": "page", "fidelity": "hifi", "url": "http://localhost:4321/",
  "source": "src/pages/index.astro",
  "sections": [ { "id": "hero", "title": "Hero", "sel": "section.hero", "source": ["src/content/site.ts#hero", "src/components/Hero.astro"],
                  "decision": "hero-headline", "variants": { "a": [], "b": [ { "sel": "h1", "text": "Build the habit, one week at a time." } ] } } ] }
```

| Field | Meaning |
|---|---|
| `url` | A live page: an `http(s)` URL on a loopback host (`localhost`, `127.x.y.z`, `::1`), no credentials; any other is an error. No screen file (`src` with `url` is an error). |
| `source` | Where the page lives in the site's repo: `path`, `path#symbol` or `path:line[-end]`, or a list of up to 3. No `..`, no leading `/`. With `board.root`: a missing file, a symbol the file never names, or a line past its end is a warning. |
| `sections[]` | Up to 40 `{id, title, sel, source?, decision?, variants?}`, in page order. `sel`: a CSS selector that finds the section in the page (≤ 200 characters). The **Pages** panel lists them with their source; a click takes the board (in Full page) or the page (in Viewport) to it. |
| `decision` | The id of a decision item in the checklist `brief`: the section shows its choices in place. More than 3 choices is a warning. |
| `variants` | `{<choice id>: [{sel?, text \| html}]}`, up to 20 edits each: the page shows the picked (else recommended) choice by setting the text or inner HTML of the element `sel` finds inside the section (the section itself without `sel`). `html` is linted like a screen file, ≤ 8 KB. Needs `decision`. |

**Live pages.** On the first render of a doc with a live page, `serve.py` starts a proxy for that dev server: its own listener on `127.0.0.1:<free port>`, so the site's root-relative URLs, modules and hot-reload WebSocket work. It answers only its own `Host`, rewrites `Host`, `Origin` and `Referer` to the dev server, drops the `bluedoc_key_*` cookie, injects the inspector after `<head>` and a style that hides framework dev toolbars, and replaces the site's `X-Frame-Options` and `frame-ancestors` with this server's origins. The page frames it with `sandbox="allow-scripts allow-same-origin"` (the proxy's origin is another port, never the page's); the page's CSP `frame-src` names exactly its proxies. A dev server that isn't up shows a 502 page in the frame. A static export (`build.py -o`) shows live pages as placeholders.

**On the page.** The toolbar switches every page to one of `breakpoints` or a typed width; each page's title bar switches that page. Its **Full page** / **Viewport** keys (kept per doc in the browser) set how tall the pages are. **Full page** (default): each page's frame is as tall as its document, at most 30 000 px, and never scrolls, so pins sit on the board; the viewport's height stays the width's design viewport (`viewport`): the proxy writes `vh`, `svh`, `lvh`, `dvh`, `vb`, `vmin` and `vmax` in the site's CSS, `<style>` and `style` attributes (and a dev server's CSS modules) as `calc(N * var(--bd-vh, 1vh))`, the inspector does the same to styles the page adds later and sets `--bd-vh`, and `innerHeight`, `visualViewport.height` and the root's `clientHeight` answer that height. Sticky and fixed elements sit at the top of the page. A page that still grows with its frame (a height set by script from something else) falls back to Viewport, with a warning. **Viewport**: each frame is the design viewport and scrolls, for sticky bars and scroll effects. Present shows Viewport. Pins on a page carry `bp` (its width), `section` (the section's id) and `source` (the section's hints, else the page's) in their target; the Markdown adds `At: <bp> px wide` and `Source: …` lines. A decision whose versions a section shows adds `Shown in: <page> › <section> · Source: …`. `build.py patch <doc> el:<page>/<sel>` prints the live URL (or the screen file), the selector and source hints: the section's when the selector names it (or, on a mockup, an ancestor in the screen file matches it), else every section's.

**Snapshots.** A live page shows the dev server as it is now, so an earlier revision shows the page's **snapshot** at that revision: a static copy per width in `<name>.bluedoc.snapshots/rev-<rev>/<page>@<width>.html` beside the doc (the history's neighbour; commit it with the doc). The inspector writes it: the DOM with the versions shown in place put back, no scripts, event attributes, frames or dev toolbars, every stylesheet inlined as text, and the images and fonts the page loaded as `data:` URIs (up to 1 MB each, 4.5 MB in all; a larger one stays a URL on the dev server, which may show the current site, and the page's title bar warns). The page records the current revision's live pages when the reader sends answers, changes or an approval, and when a page in Full page first settles at a width that revision has none of; `POST /__bluedoc/snapshot` takes them (the key, the current `meta.rev` only, at most 8 MB). `serve.py snapshot` records them through headless Chrome, also for an earlier revision that has none. An earlier revision's snapshot is never replaced. On `?rev=B` a live page shows B's snapshot (the nearest width it has) in the same sandboxed frame as a mockup, its page bar reads **Snapshot · rev B**; without one, a placeholder says **No snapshot of rev B** and nothing live shows. `patch` warns when the revision it replaces has no snapshot.

**Compare.** On `?diff=B` each page that both revisions have shows B's page to its left, **Rev B** beside **Rev C**, at the same width and height (Full page or Viewport, where the two scroll together); zoom and pan move both. A section whose content differs (the two frames' hash of its tags and text, else its JSON) is outlined on both and marked **changed** in the Pages list, and its page is **Changed**. The compare tray's **Side by side** / **Single** keys (kept per doc) show or hide the earlier page.

## Listing

A storelisting (`meta.type: "storelisting"`) is one app's store listing on Google Play and the App Store. It has a `listing` block and one `board` of shots (`device: "shot"`), assets (`device: "asset"`: feature graphic, banners, ad images) and an icon (`device: "icons"`, or another design doc's). The page shows the board as two **platform pages**, one per store (`#play`, `#appstore`, with `/<locale>` when it isn't the default, `@<variant>` for a variant tab). A floating toolbar at the top of the listing, like a design board's, holds, left to right: the left panel's key (`[`, kept per browser under `bluedoc:listing-panel`); **Undo** and **Redo** with the drafts count (it opens Comments on Pending); **Google Play | App Store** and the locale menu; **Sections | Store preview | Ads** and **Jump to** a section; the Checks count (it opens the Checks tab); **Export to…**. Where its words don't fit (1440 px with both panels open, 1100 px), the view keys keep their icons, Export to… its icon and the platforms their short names, then Jump to and the counts go. The app bar keeps the breadcrumb, **Rev** and the theme. Every size, count, limit and rule comes from `assets/store-rules.json`, each with its source and access date; a rule marked `unverified` only warns. `scripts/listing.py` loads and checks it.

Every listing draft is a step of the doc's one undo history (the board's `__hist`, kept across reloads): a Save of text edits, an Accept MT, a style pick, a brand or colour edit, an order or Device sections change, an upload, and a Discard of any of them. Undo and Redo in the toolbar name the step ("Undo: Short description · en-US") and are off at either end; ⌘Z and ⇧⌘Z (Ctrl+Z, Ctrl+Y) do the same on the page and in a shot's frame, while a text field keeps its own undo. Undoing an upload sets its PNG aside (`.discarded-NN.png` beside it), and Redo brings it back. Request changes seals the history: undo stops at what was sent.

```json
{ "type": "listing", "id": "main", "app": { "name": "Acme Fit", "company": "Acme" },
  "platforms": ["play", "appstore"], "rows": ["watch", "phone", "tablet"], "locales": ["en-US", "es-ES"], "defaultLocale": "en-US",
  "ipad": true, "icon": "acme-fit-design.bluedoc.json#app-icon", "style": { "message": "m1", "layout": "l1" },
  "brand": { "font": { "family": "Inter", "weight": 800 }, "palette": { "bg": "#1d4ed8", "surface": "#e0e7ff", "accent": "#f59e0b", "text": "#ffffff", "caption": "#ffffff" } },
  "video": { "play": "https://www.youtube.com/watch?v=…", "appstore": [{ "src": "media/preview.mp4", "row": "phone", "poster": 5 }] },
  "text": { "en-US": { "play": { "name": "…", "short": "…", "full": "…" }, "appstore": { "name": "…", "subtitle": "…", "keywords": "…" } } },
  "strings": { "en-US": { "today.title": "See your week at a glance" }, "es-ES": { "today.title": "Tu semana de un vistazo" } },
  "mt": { "es-ES": ["appstore.subtitle", "strings.today.title"] },
  "order": { "appstore/iphone-69": ["workout", "today"] } }
```

| Field | Meaning |
|---|---|
| `app` | Required: `{name, company}`. |
| `platforms` | `play`, `appstore`: the platform pages, in that order. |
| `rows` | The device sections: `watch`, `phone`, `tablet` (the default) and the optional `tv`, `desktop`, `xr`, `chromebook`, `car` (a warning: their capture and export come later). A section off shows as a strip; **Turn on** is a draft. |
| `locales`, `defaultLocale` | Locale codes (default: the first). A code a store doesn't list is a warning. A missing text or caption shows the default locale's, flagged *falls back*. |
| `ipad`, `watchFace` | `true` makes the iPad 13" set, or Wear's watch-face set, required. |
| `icon` | An icons artboard: its id on this board, or `<design doc>.bluedoc.json#<id>` beside it. The Shared section shows it under Play's 30 % mask and as the App Store's 1024 icon (in the binary). |
| `style` | The default screenshot style: `message` `m1`…`m5`, `layout` `l1`…`l5` (`store-rules.json` `styles`), and a platform page's own, `{message, layout, play: {…}, appstore: {…}}`; a shot may override it with its own `style`. Default M1 + L1. See [Style and brand](#style-and-brand). |
| `brand` | `font` (the caption font; default Inter, vendored, OFL; see the next row), `palette` roles `bg`, `surface`, `accent`, `text`, `caption` as hex, and `image` (`<stem>.listing/brand/source.<png\|jpg\|webp>`, the palette's source): the CSS variables `--brand-<role>` and the caption's `--bd-*-caption` in every shot. |
| `brand.font` | `{family, weight, italic, source: system\|vendored, fsType, size, lineHeight, letterSpacing, align, valign}`. `weight` 100–900 by 100 (default 800), `italic` a boolean. `size`: a unitless scale of each style's caption size, 0.5–1.6 (default 1), so it holds in every store size. `lineHeight`: a multiple of the size, 0.8–2 (absent: the style's own, 1.06). `letterSpacing`: % of the size, −20–50 (default −2). `align`: `left` `center` `right` (default `center`). `valign`, where the caption block sits: `top` `middle` `bottom` (default `top`); a layout draws only the places its `store-rules.json` `styles[].valign` lists (L1, L2, L4: top, bottom; L3: all three; L5: top), else top, a warning. Bounds: `store-rules.json` `brand.font`. Tokens: `--bd-font-caption`, `--bd-weight-caption`, `--bd-style-caption`, `--bd-size-caption` (unitless), `--bd-leading-caption` (unitless), `--bd-tracking-caption` (em), `--bd-align-caption`, `--bd-valign-caption`. |
| `video` | `play`: one YouTube video URL (no playlist, channel or timecode). `appstore`: up to 3 previews per row, each `{src, row, poster}` (an `.mp4` beside the doc; poster frame in seconds, default 5). |
| `text` | `{locale: {platform: {field: text}}}`. Fields per platform: `store-rules.json` `text` (Play `name` `short` `full` `releaseNotes` `featureAlt`; App Store `name` `subtitle` `promo` `description` `keywords` `whatsNew`). |
| `strings` | `{locale: {key: text}}`: the captions shots name with `data-l10n="key"`. A key a shot uses with no string in the default locale is a warning. |
| `mt` | `{locale: ["<platform>.<field>" \| "strings.<key>"]}`: machine-translated strings, badged **MT** until accepted. Each must name a string that exists. |
| `order` | `{set: [shot ids]}`: a set's upload order (default: board order); the page's drag makes this a draft. |
| `capture` | The capture recipes' devices and apps: `{devices: {<target>: <simulator name or UDID, or AVD name>}, apps: {ios\|watchos: {bundle, app?}, android\|wearos: {package, apk?}, web: {url} \| {design}}}`. `app`/`apk`: a build beside the doc, installed first. `web.url`: a loopback dev server; `web.design`: a design doc beside it, whose screens the web target captures. See [Uploads and captures](#uploads-and-captures). |
| `variants` | Custom pages and A/B tests: see [Variants, preview and ads](#variants-preview-and-ads). |

The left panel has four tabs: **Text**, **Style**, **Colors** and **Checks**; the browser keeps the last one picked (`localStorage` key `bluedoc:listing-tab`). The brief is the right panel's **Brief** tab, before Comments and Revisions, as on every design page. **Text** lists the shown platform's fields for the shown locale, then the captions, then the captions' Typography (see [Style and brand](#style-and-brand)). Every field is editable, with a counter (code points; UTF-8 bytes for Apple keywords), red past the limit; text only a variant sets is read-only there. An edit stays unsaved (a dot on the field and on the tab; leaving the page asks first; **Approve** waits) until **Save** (⌘S; Esc reverts the field) makes each changed field a draft, `listing` op `field` `{locale, group, field, value, base}` (`group` is the platform or `strings`), keyed `field:<locale>/<group>/<field>`. Each Save is one step of the doc's undo history (the toolbar's **Undo** and **Redo**, ⌘Z and ⇧⌘Z). Request changes sends the drafts under `## Text edits`, a line each with the old and new text, then `build.py patch <doc> field:… --set <field>=<text> --change … --resolves <id>` per field (`--no-bump` after the first; this also clears an MT mark). A text over its limit saves, in red, but `patch` refuses it. Approve waits until the doc has each value. **Checks** lists the build's findings for the platform on screen (see [Checks](#checks)); its tab counts the errors, else the warnings. Point and Select pin a comment inside a shot (`el:<shot>/…`, with `platform`, `locale` and `set` in the target) or on a field (`field:`). Dragging a shot in View reorders its set; turning on a section changes `rows`. Both are drafts: Request changes sends them under **Board drafts** with one `build.py patch <doc> block:<listing path> --json '{"order": …, "rows": …}'` command.

### Style and brand

**Style.** The **Style** tab shows the 5 message and 5 layout styles for the platform page on screen (and its variant), each with its thumbnail (`kits/style-thumbs.svg`, in the brand's colours), evidence grade and store form. A pick is a draft: every shot restyles at once (`{bd:'shot', message, layout}`), with no new HTML. A style whose hook is missing shows *needs the agent*: M3 a `data-callout` element, M4 (App Store) the string `<shot>.proof` for shot 1, M5 a video, L5 a photo (`img.shot-photo`, its rights in the shot's `credits`). Request changes sends the picks under `## Decisions` as `style-<platform>-<variant>-message` and `-layout` (variant `default`), and under `## Style picks` the command that records them: `build.py patch <doc> block:<listing path> --json '{"style": {…, "<platform>": {"message": …, "layout": …}}}'`.

**Typography and Colors.** **Typography**, at the top of **Text** above the fields, sets the caption font as Figma does. The family is a dropdown: its popover has a search (↑ ↓ Enter Esc; typing on the closed button opens it), the families installed here, each in its own face with its style count (`GET /__bluedoc/fonts`: `scripts/fonts.py` reads `name` and `OS/2` from each TTF, OTF and TTC in the font folders), and **↻ Refresh fonts** (a font installed since shows). The style dropdown lists the family's real faces (weight and italic). Then the size (% of the style's size, typed or from a menu), line height (Auto or a multiple), letter spacing (%), and alignment: left, centre, right, and the caption block at the top, middle or bottom (disabled, with why, where the layout doesn't draw it). The ⓘ by the family holds its licence note (`fsType`); a font a PDF can't embed shows a warning line. Each change is one step of the undo history. The **Colors** tab holds the palette: drop or choose an image (PNG, JPEG or WebP, 8 MB; `POST /__bluedoc/listing/brand` writes `<stem>.listing/brand/source.<ext>`), and the page extracts 6 swatches (k-means in Lab on a 128 px copy) by share and gives them roles (darkest `bg`, lightest `surface`, most saturated `accent`, best contrast on `bg` `text` and `caption`); drag a swatch onto a role, or type a colour or hex. Every change restyles the shots (`{bd:'brand', palette, font}`). The contrast pairs are `store-rules.json` `brand.contrast`: the pairs the shot kit draws text in, each named by what it draws (caption and subtitle on background, L1–L3; caption on the light ground, L5; the step chip, M2), at least 4.5:1. A font, typography or palette edit is a brand draft (`serve.py` keeps one only with valid values): Request changes sends it under `## Brand drafts` with `build.py patch <doc> brand:<listing id> --json '{"font": …, "palette": …, "image": …}'`, and Approve waits until the agent records it. **Warnings:** a contrast pair under 4.5:1 (named by what it draws), a font whose `fsType` a PDF can't embed (restricted or bitmap only), a caption place the layout doesn't draw, a style whose hook is missing, M4 on Play (use-case first: Play bans awards and testimonials in shots), an L5 photo without `credits`.

### Shots

| Artboard field | Meaning |
|---|---|
| `device` | `shot`, `asset` or `icons`; nothing else on a storelisting's board. |
| `sets` | A shot's sets, e.g. `["play/phone", "appstore/iphone-69", "appstore/iphone"]`: one screen file renders at each set's frame (its store size ÷ scale: 360×640 for `play/phone`, 440×956 for `appstore/iphone-69`). A set of a platform the listing lacks is an error. |
| `asset` | An asset's rule id, e.g. `play/feature` (1024×500, with the cut-off guide), `play/ad-landscape`, `appstore/search`. |
| `locale` | A shot or asset that belongs to one locale only (an upload, an ad image). |
| `src` | A `.png` inside `<stem>.listing/`: an uploaded shot or ads asset, shown as the image. |
| `variantOf` | A variant's own shot (the default shot it stands in for): only a variant's `swap` shows it, in that shot's place. Its `sets` cover the source's. |
| `style`, `recipe` | The shot's own style; its capture recipe `{route, appearance: light\|dark, settle: s, targets: [target], locales: [locale], size: [w, h]}`: see [Uploads and captures](#uploads-and-captures). |
| `credits` | The rights to a lifestyle photo in the shot (L5): who took it, the model release. |

A shot's screen file is a layout in the shot kit (`references/kits.md` `## Store shots`): `.shot` > `.shot-cap` (the caption, `data-l10n`) and `.shot-frame` > `.shot-ui` (the app's UI at the set's UI viewport, scaled into the frame). Raw sets (Wear, Apple Watch) show the UI alone. The UI slot shows a capture from `<stem>.listing/captures/captures.json` (fresh when its recipe hash matches) over the mock-up; the section tags each shot **mock UI**, **capture**, **stale** or **upload**, plus **MT** and *falls back*.

### Uploads and captures

**Uploads.** Each set ends in a **Drop PNG** slot until it is full; an uploaded shot has **Replace with PNG…**. The page checks the PNG's header against the set's rule, then `POST /__bluedoc/listing/upload` (the key, `X-Bluedoc`) checks it again (exact sizes on Apple; side range and ratio on Play; colour type 2 or 3 without `tRNS`; 8 MB or the set's `maxBytes`; the slot range) and writes `<stem>.listing/<platform>/<locale>/<set name>/NN.png`. A file a revision records is never overwritten: the upload takes the next free name. It is a **Draft** tile until the agent records it as a shot's `src`: Request changes lists it under `## Uploaded shots` with a `build.py patch <doc> block:<board path> --append '{…"src": "<file>"}'` command (a replacement: `artboard:<id> --set src=<file>`). While a draft is unrecorded the build warns, Approve stays disabled and the server refuses an approval.

**Captures.** `python3 <skill>/scripts/capture.py <doc> [--shot ID] [--target T] [--locale L] [--device T=NAME] [--dry-run]` runs each shot's `recipe` on its targets (default: the targets of its sets, `store-rules.json` `targets`) in each of its locales (default: `listing.locales`):

| Target | Runs | Fills |
|---|---|---|
| `ios-phone`, `ios-phone-63`, `ios-tablet` | `xcrun simctl`: boot, status bar 9:41, appearance, launch with `-AppleLanguages (<locale>) -AppleLocale <ll_CC>`, `openurl <route>`, `io screenshot --mask=black` | `appstore/iphone-69`, `appstore/iphone`, `appstore/ipad` (UI slot) |
| `watchos` | the same, without status bar or appearance (watchOS has neither) | `appstore/watch` (the shot itself: 422×514 on Apple Watch Ultra 3 (49mm)) |
| `android-phone`, `android-tablet`, `wearos` | `emulator -avd <avd> -no-window` (an AVD already running is used), SystemUI demo mode, `cmd uimode night`, `cmd locale set-app-locales` (Android 13+), `am start`, raw `screencap` saved as RGB | `play/phone`, `play/tablet*` (UI slot), `play/wear*` (the shot itself) |
| `web` | headless Chrome at the shot's first set's UI size × its scale (or `size`): `apps.web.url` + `route`, or `apps.web.design`'s screen `route` | the UI slot of any set whose UI viewport has the capture's aspect (within 5%): a phone capture fills the phone sets, and the tablet sets keep the mock-up |

Each PNG is read back: no alpha, and a raw set's capture must be its size. It writes `<stem>.listing/captures/<target>/<locale>/<shot>.png` (the one it replaces moves to `captures/old/<sha256 16>.png`) and a row in `captures/captures.json`: `{shot, target, locale, file, w, h, sha256, recipe, device, tools, at}`. Lines read `ok`, `skip` or `fail`; exit 0 all taken, 1 one failed, 3 a target skipped (a missing tool or device). A capture whose `recipe` hash differs from the shot's recipe is **stale** (a warning, with the re-shoot command). Each capture joins the revision as `<shot>/capture/<target>/<locale>` (its PNG's hash), so `?diff=` marks the shot Changed and shows the capture it replaced beside it.

**Re-shoot.** A pin on a capture records where it fell on the UI image (`target.at`, fractions) and the capture shown (`target.cap`); the key stays `el:<shot>/ui`. The readback of any pin on a shot adds its sets, locale and page, its screen file and element, its capture with the time it was taken, its recipe and the `capture.py` command for that target and locale. `build.py patch <doc> el:<shot>/…` prints the same for each target and locale.

### Text and locales

Each set's chip shows its shot count against its range, its accepted sizes and whether it is required (`always`, `row`, `either:<set>|<set>`, `if:ipad`, `if:watchFace`, `dated` from a date). The locale menu shows each locale's MT and missing counts. **Errors:** an unknown platform, row, set, asset, style, text field, locale or palette role; an `mt` key that names no string; a bad YouTube URL; more than 3 previews per row; an image shot outside `<stem>.listing/` or not a PNG; an `order` entry that isn't one of the set's shots. **Warnings:** a required text field missing in the default locale; a caption key without a default string; a locale a store doesn't list; an optional row; the rules file over 180 days old.

**Machine translation.** `build.py l10n <doc> --export <locale>` prints, as JSON, the strings the locale lacks or whose default-locale text changed since its translation (`listing.translatedFrom` keeps a hash per string), each with its label, limit, unit and the shots that show it. `--import <locale> <file.json> --mt` merges `{"<platform>.<field>" | "strings.<key>": text}` and marks them in `listing.mt`; one string over its store limit refuses the whole file with its count, and nothing is written. `--accept <locale> <key> …` clears marks. Both bump the rev (`--no-bump`, `--change`, `--resolves` as for `patch`); `patch field:` clears a string's mark too. On the page each MT field has **Accept MT**: a draft that Request changes sends under `## Accepted MT` with the `build.py l10n <doc> --accept <locale> <keys>` command. An unaccepted MT string warns; it doesn't block approval.

### Checks

`build.py <doc>` runs every store check (`listing.store_checks`). Each finding names its platforms, set, locales, section, key and source (the rules file's `sources`); a rule marked `unverified` only warns. Store-rule errors fail the build (exit 1) but leave the page, its history and its exports working: the **Checks** tab lists the build's findings for the platform on screen (click one to show its field or shot; one on the style opens Style, one on the caption font opens Text, and one on the palette, such as a contrast pair, opens Colors), and the home card colours each section by its worst one.

| Check | Error | Warning |
|---|---|---|
| Text | over a limit in any locale (code points; UTF-8 bytes for Apple keywords), MT or not; Google Ads item counts; keywords of ≤ 2 characters, repeated, or naming the app or company | Play's banned words and calls to action, emoji, words in capitals, repeated punctuation, a price, another platform, HTML tags |
| Sets | over a set's maximum; under its minimum; a required set empty (`always`, `row`, `either:`, `if:ipad`, `if:watchFace`); fewer shots than a platform's `minShots`; a `dated` set past its date | under a set's `recommend`; a `dated` set before its date |
| Assets | a required asset missing (the feature graphic); no icon, or one without `fg.svg` | |
| Files | an upload of the wrong size, with alpha or `tRNS`, or over the byte limit; a capture with alpha; a raw set's capture of the wrong size; a Wear OS shot that draws a caption, a device frame, a mask or a see-through background; Apple Watch shots of more than one size across locales | |
| Locales | | text, captions or captures that fall back to the default locale; unaccepted MT strings |
| Content | | shots with mock-up UI (no capture or upload), and sets no capture fits (another aspect); social proof in a Play graphic; a caption font not installed here |
| Variants | a bad id, kind, swap, order or text field; text a kind can't change (PPO: none; CPP: promotional text and keywords; SLE: short and full description, only in its own `locale`); a PPO that swaps or reorders a watch shot; more of a kind than the store allows; two CPPs in one Apple Ads ad group | a variant that changes nothing; a variant's shot no swap shows |
| Ads | more of an ads asset per locale than its `count`; an uploaded one of the wrong size, with alpha or over its bytes | an Apple Ads creative asset (coming soon: `unverified`) |

### Export

`build.py <doc> --listing out.zip` writes the fastlane ZIP: `fastlane/metadata/android/<locale>/` for `supply` (`title.txt`, `short_description.txt`, `full_description.txt`, `changelogs/default.txt`, `video.txt`, `images/icon.png`, `images/featureGraphic.png`, `images/<type>Screenshots/NN-<shot>.png`), and `fastlane/metadata/<locale>/*.txt` and `fastlane/screenshots/<locale>/NN-<set>-<shot>.png` for `deliver` (it reads the display type from the size). Sets fastlane has no folder for go to `extra/`, Google Ads text and images to `ads/google/<locale>/`, the search results and Apple Ads assets to `ads/apple/<locale>/`. Each variant's files go to `variants/<platform>-<kind>-<id>/` at their default paths: its own text and each set whose shots or style differ, nothing else. Every PNG is at its store size, 24-bit RGB without `tRNS`; a field a locale lacks isn't written (the store shows the default locale's). `manifest.json` lists every file (kind, platform, locale, set, shot, variant, size, sha256, bytes), the MT strings, the fonts and the store-rule errors still open. The App Store icon ships in the binary. `--listing out.pdf` writes the listing for review (both platform pages, text with counts, MT and fallback tags, the checks); `--listing out.html` writes it as one file that works offline. `--platform` and `--locale` narrow the ZIP. ZIP and PDF render through headless Chrome (`BLUEDOC_CHROME`; without one: exit 1). Upload the ZIP's folders with fastlane yourself; nothing here talks to the stores.

`--listing out.zip --format folders` writes the same files (same renders and bytes) as plain folders under one `<stem>/` folder, for a person or another tool: `google-play/<locale>/` and `app-store/<locale>/` each hold `text/<field>.txt` (the field's store label, slugged: `app-name.txt`, `short-description.txt`, `full-description.txt`, `release-notes.txt`, `video-url.txt`; `name.txt`, `subtitle.txt`, `promotional-text.txt`, `description.txt`, `keywords.txt`, `whats-new.txt`), Play's `icon.png`, `feature-graphic.png` and `tv-banner.png`, and a folder per device named from its set's label (`phone/`, `tablet-7in/`, `tablet-10in/`, `wear-os/`; `iphone-6.9in/`, `ipad-13in/`, `apple-watch/`) of `NN-<shot>.png` in store order; other assets are `<asset label>-<shot>.png` beside them. Ads go to `ads/google/<locale>/` and `ads/apple/<locale>/` (their text under `text/`), each variant to `variants/<platform>-<kind>-<id>/<locale>/` with only what it changes. `README.txt` maps each folder and file to its store field or slot, with its limit or size; `manifest.json` is the fastlane ZIP's, its paths this ZIP's.

The server sends the same files from `GET /__bluedoc/listing?path=<doc URL path>[&format=zip|folders|pdf|html|print][&rev=B][&platform=P][&locale=L][&job=J]` (the attachment `<stem>[-<platform>][-<locale>].zip`, or `…-folders.zip` for `folders`): a read, no key; 400 for another type, an unknown rev or format, or a filter on anything but a ZIP; 501 for a ZIP or PDF without Chrome. `X-Bluedoc-Warnings` is a JSON list of what the export should say (a font a PDF can't embed, store-rule errors still open). The ZIP renders in up to 6 headless Chromes side by side and draws each distinct shot (its page, state, frame and scale) once: files that are the same render (Play's 7- and 10-inch tablets, a variant's unchanged shots) carry the same bytes, and `manifest.json` still lists each. A ZIP or PDF with `job=J` (8-64 of `A-Z a-z 0-9 - _`) is followed by `GET /__bluedoc/listing/progress?job=J`: `{job, format, stage: plan|render|zip|done|error|cancelled, done, total, file?, error?}` (`total` is the ZIP's file count; a PDF has none), kept 10 minutes after its last change, else 404; a read, no key. `DELETE` on it (with the `X-Bluedoc` header), or `POST …&cancel=1` (the key), cancels the export: its Chromes are killed, its temp files go and the export answers 409. Closing the export's connection stops it too. The page's **Export to…** menu (ZIP (fastlane), ZIP (folders), PDF, HTML) uses it at the revision shown: while one runs, the key is its progress (a spinner and `ZIP…` until the total is known, then `ZIP 120/294` and a bar along its foot; icon and bar when the toolbar is narrow), a click on it, its ×, or Esc cancels, and a second export waits until it ends; then `Exported` with a tick (or `Failed`, and the server's error in a toast) and the key as it was. It shows those warnings; without Chrome its PDF opens the print view in a tab.

**Approve listing** sends the approval with the style picks of every page and variant under `## Decisions`. It is disabled while a text edit is unsaved or an upload, brand or text draft is unrecorded (the server refuses it too while an upload is); its dialog counts the unaccepted MT strings and the shots with mock-up UI, and names the variants it covers.

### Variants, preview and ads

`listing.variants[]`: `{id, platform, kind, title, swap, order, style, text, locale, adGroup}`. `kind`: `cpp` (custom product page, ≤ 70) and `ppo` (product page optimization, ≤ 3 treatments) on the App Store, `csl` (custom store listing, ≤ 50) and `sle` (store listing experiment, ≤ 2 variants) on Play (`store-rules.json` `variants`). `swap`: `{<default shot>: <shot>}`, a shot (usually a `variantOf` one) in another's place in every set. `order`: `{<set>: [shot ids]}`, first in that order. `style`: `{message, layout}`; an A/B treatment (`ppo`, `sle`) is L5 lifestyle unless it names a layout. `text`: `{<locale>: {<field>: text}}`, the fields its kind varies. `locale`: an SLE's language (a localized experiment, the only kind that tests text). `adGroup`: a CPP's Apple Ads ad group. Keys: `variant:<id>`.

The page shows a tab per variant of the platform above its sections (**Default page**, then e.g. *CPP: Runners*, *PPO: B: Lifestyle*), each with its count of changes against the default page (swaps, reordered sets, style, text) and **Compare to default** (each set's default shots beside the variant's). On a variant tab the Text tab shows its own text, the Style tab picks its style (`style-<platform>-<variant>-*`), and dragging a shot makes an order draft whose readback command is `build.py patch <doc> variant:<id> --json '{"order": …}'`. The URL keeps the tab: `#appstore@runners`.

**Store preview** (beside **Sections**): the platform's product page and a search result at phone width, for the locale and variant on screen, from the listing's text, icon, shots, previews and feature graphic. It is a mock, not pixel-exact: App Store previews come before the shots and search shows 3 portrait shots (or the iOS 27 search results asset); Play's video plays over the feature graphic, and search shows it and 2 large shots.

**Ads**: on Play, the Google App campaign's headlines (≤ 30, 1–5) and descriptions (≤ 90, 1–5) per locale (`text.<locale>.play.adHeadlines`, `adDescriptions`) and its images at 1.91:1, 4:5 and 1:1 (`play/ad-*` assets, ≤ 20 each). On the App Store, Apple Ads' default ad (the default page's shots in upload order), an ad variation per CPP with its ad group, the search results asset (`appstore/search`, 3:2) and Apple Ads creative assets (`appstore/ad`, `unverified` until Apple launches them). Each ads asset is an asset artboard or a PNG dropped on its slot (the upload route takes its id as `set`; the readback appends an asset artboard with its `src`). The 21:9 product page header and the 16:9 universal asset stay plain assets until v2.

## Revisions

Every `build.py doc.bluedoc.json` run records the document in `doc.bluedoc.history.json` under its `meta.rev`: a new `rev` appends a revision, the same `rev` replaces the last one. A server render shows the doc as the latest revision without writing the history file. A `rev` that is already an earlier revision fails the build (and shows as an error page). No `meta.rev`: no history. The history file stores each revision's header and section fields once per revision and each block once across all revisions (by content hash); the page embeds the revisions other than the current one, with blocks the current one still has as references, so a page with ten small edits grows by roughly the edited blocks. A design doc's revision also maps each artboard to its screen file's hash (`screens`), and the file's text sits once in the history's `html` pool; editing a screen under the same `rev` is an edit in place. The page gets only the hashes and loads an old screen from the server with `?rev=`.

A design revision also lists the board's links (`links`, see [Links](#links); none: no key) and holds each icon layer in `screens` as `<id>/<file>`. The page gets every revision's links, the current one's read fresh from the files, so an old revision draws its arrows without its HTML and `?diff=` marks links New, Removed or Changed.

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
- **Reader-chosen width (> 900 px):** a handle sits on each side of the content column. Dragging either one widens or narrows the column symmetrically, so it stays centred; arrow keys on a focused handle move it 40 px (Shift: 160 px). The column is always centred on the window, the Comments/Revisions panel docked or not: it narrows to keep a rail's width free on both sides (a docked panel's width on the right). When even 520 px doesn't fit that way, the panel opens over the page instead of docking, and below that the column takes the rails' space: Status/Document/Related move under the TL;DR and Contents opens from a button in the app bar. Double-click a handle (or press Home on it) to return to the default layout. The width is stored per browser for every bluedoc page (`localStorage` key `bluedoc:width`), so wide tables stay readable without changing the document.
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

Edges route themselves, as a design board's links do: right angles with rounded corners, round the scope's other nodes, leaving each node on the side facing the other end. Parallel lines are spaced apart, and each label sits on its line clear of nodes and other labels. A frame port is a stretch of the frame's edge that edges cross square. `bend` is gone (the build warns that it is ignored).

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

**Board drafts** (design pages): a link edit (Link mode, `L`, or an arrow's menu) is an annotation of type `link` with `link: {op: add|set|move|delete, from, el, to, kind, label?, edge?, base}` (`base`: the link as the rev has it, or null), keyed `link:<screen>/<el>`; moving screens or **Tidy up** is one annotation of type `layout` with `layout: {positions: {"<artboard>": [x, y]}}`, keyed `layout:<board>`; in **Edit** (`E`, design, presentation and website pages) a double-click changes an element's one text run in place (plain text, at most 1,000 characters) and Delete hides the selected element: one annotation of type `element` per element, keyed `el:<artboard>/<sel>`, with `element: {op: text|delete, ab, sel, tag, base, text, ord}` (`base`: its text as the rev had it; `ord`: its place in document order), at most 300; the frame shows it only where the element still has that tag and text, and a deletion's card has **Restore**. Drafts live in reader state, so they survive reloads, and the board and **Present** follow them at once. The reply Markdown lists them under `## Board drafts`, then one `sh` block with a ready `build.py patch` command each (the first bumps, the rest `--no-bump`; a moved link is a `--delete` on the old key, then `--set` on the new). Run them as they are. An element draft's line adds `File:` (its screen file), or on a live page `Live page:`, `At:` and `Source:`: edit the source there, then run its `--change` command. Run them as they are. On load, a draft the current rev's links or positions already match becomes **Resolved** ("Applied in rev X"), as does one a rev lists in `resolves`; one a newer rev changed some other way is **Stale**.

**Undo and redo** (design, presentation and website pages, current revision only): one history per doc covers every board draft change, one step per reader action: a text edit, a delete, **Restore**, **Discard** or Delete on a draft's card, **Re-apply**, a link edit, a drag or nudge of screens, **Tidy up**. Cmd/Ctrl+Z undoes; Shift+Cmd/Ctrl+Z and Ctrl+Y redo, on the page or in a screen's frame (the inspector forwards them); in a text field or an element being edited the browser's own undo runs. The board toolbar's **Undo** and **Redo** keys sit beside the drafts count, disabled at either end, their tooltips naming the step ("Undo: Text in Today › start-workout"). A new step after an undo drops the steps undone. **Request changes** (and Approve) seals the history: undo stops at what was sent ("Already sent: discard the draft in the panel"). It is kept in reader state (`__hist`, `__hist:<step>`, see [Reader state](#reader-state)), so a reload keeps it; at most 200 steps (the oldest go); it starts empty when the page loads another rev than the one it was made on. Comments (pins, text, drawings) stay outside it.

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
| `el:<id>/<path>` | an element in that artboard's screen file: `<path>` is `data-bd` names joined by `/` (`el:login/form/submit`), else a CSS path (`el:login/[data-bd="login"]>h1:nth-of-type(1)`; on a website's live page also from the nearest unique id, `el:home/#faq>details:nth-of-type(2)`). `patch` prints the file (a live page: its URL) and the selector, and on a website the source hints |
| `frame:<device>@<x>,<y>` | a requested empty frame at board px `x`,`y`; `<device>` is a device or `<w>x<h>`. `patch` appends an artboard there (`frame-<n>`, or `--set id=…`) and writes a wireframe stub screen file |
| `link:<id>/<element>` | the link on an element of that artboard's screen file: `<element>` is its `data-bd` name (the link list's `el`) or a CSS path as for `el:`; a name no element has (or none: `link:<id>/`) is a new gesture link. Without an option `patch` prints the file, the selector and the current `data-nav` and label; `--set to=… kind=… label=…` or `--delete` rewrite that start tag in place |
| `layout:<boardId>` | the board's artboard positions: `patch layout:main --json '{"<artboard>": [x, y], …}'` sets `x`, `y` (`null` unsets: the board places it). The page sends moves and **Tidy up** as one `layout:` draft with this command |
| `field:<locale>/<platform>/<field>`, `field:<locale>/strings/<key>` | a storelisting's store text (`listing.text[locale][platform][field]`) or caption string (`listing.strings[locale][key]`), from the Text panel. `patch` with no option prints it with its count and limit; `--set <field>=<text>` writes it, `--delete` drops it. A pin inside a shot is an `el:` key; its comment adds `platform`, `locale` and `set` to the target |
| `brand:<listing id>` | a storelisting's `listing.brand` (`brand:main`): `patch --json '{"font": …, "palette": …, "image": …}'` merges it, `null` deletes one. The Colors tab's and the caption font's drafts come with this command |
| `section:<platform>/<row>` | a storelisting's device section (`section:play/phone`, also `text` and `shared`): `patch` prints its sets, shots and findings and the keys that change them. Check findings name it |
| `variant:<id>` | an entry of a storelisting's `listing.variants` (`variant:ppo-a`): `patch --set`/`--json` changes it, `--delete` drops it |

`<blockPath>` is `<sectionId>/<i>`, or `<checklist>/<item>/<k>` for a block inside a checklist item, as in `block:` and `row:`. `<i>`, `<k>` and `<r>` are 0-based.

### Bottom tray

On the current revision the tray's last keys depend on the page. The `?diff=` tray (compare view) and `?rev=` (no tray) don't change.

| Page | Tray |
|---|---|
| Plan page | View · Point · Select · Draw │ eye (hide or show comment marks) │ **Request changes · N** · **Approve plan** (green) |
| Other page with a checklist | View · Point · Select · Draw │ eye │ **Request changes · N** · **Send answers**: neutral with nothing to send, filled green once the reader picks, ticks or comments on something |
| Page without a checklist | View · Point · Select · Draw │ eye │ **Request changes · N** |
| Design, presentation or website page | View · Interact · Point · Select · Draw · **Edit** (`E`: select an element, double-click its text to change it, Delete to remove it; see Board drafts) · Link · Frame │ eye │ **Request changes · N** · **Approve** |

## Plans

A doc whose type is `plan` (`meta.type`, or derived from `meta.kind`) is a **plan page**: a proposal the reader approves or sends back. `types/plan.md` gives the layout and the approval loop.

A status chip sits next to the eyebrow:

| Chip | When |
|---|---|
| **Plan · Awaiting approval** (amber) | No approval of this doc, or one of the current `meta.rev` whose JSON was then edited in place. |
| **Changes since approved rev X** (amber) | The reader approved an earlier rev X, and something besides progress changed since (see below): it needs approval again. |
| **Changes requested** (blue) | The reader sent Request changes on the current `meta.rev`. Stored under `bp:<doc.id>:__planstate` as `{rev, state, at}`. |
| **Approved · rev X** (green) | The saved approval is for the current `meta.rev`, or for an earlier rev X carried to this one, shown as **Approved · rev X · progress in rev Y**. |
| **Pick changed since approval** (amber) | Approved, but the reader has since picked another option on a decision the approval carried (an item approved without a pick counts as its recommendation). Each changed pick counts toward **Request changes** until sent (`<checklist>:<item>:pick-sent` holds the pick sent), then the chip adds **· sent**. Picking the approved option again clears it. |

An approval of rev X carries to a later rev Y when every change between them is progress: a step's `status` and `evidence`, a progress item's `done` and `evidence`, a decision's `choice` set to the pick the reader approved, `meta.rev`, `meta.date`, `changes`, `resolves` and the doc's `state` labels. Any other change (text, options, sections, blocks, a screen file or icon layer) does not carry. The server decides from the history file (rev X's snapshot and screen hashes, which must match the approval's `docHash`), so `--no-bump` on rev X itself, which rewrites its snapshot, ends the approval.

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

## Stale evidence
N checks have stale evidence: the code changed since they ran. Re-run each, then re-record its evidence …
- **<check title>** `<key>`
  - <evidence label>: code changed since abc1234 (<changed files>)
    Re-run: `<its command>`

(a sh block of `build.py patch <doc> <key> --pin` commands)
```

A pick carries `(recommended: …)` only when it differs from the recommendation; an item with no `recommend` and no pick reads `(no pick)`. Plain items the reader commented on are listed too. General comments come first in the notes; `> <excerpt>` is left out when there is none, and `(rev <rev>)` when the doc has no `meta.rev`.

The server stores the approval in `state.db` with `docHash`, the sha256 of the doc's canonical JSON, queues it with kind `approval` for `serve.py wait`, and answers `{ok, id}`. The page posts the `docHash` its seed carried (the JSON it rendered) and its `rev`; when either differs from the file's current JSON or `meta.rev`, the server answers 409 `{"reload": true}` and the page offers **Reload** instead, so an approval never covers text the reader hasn't seen. The key then reads **Approved · rev X** with a check, disabled, and stays so while the approval holds or carries. A new `meta.rev` with more than progress, or any edit of the doc's JSON in place, resets it: the plan awaits approval again.

- **Request changes** on a plan page also carries `answers` (the decision picks) when there are any, and its Markdown ends with the same `## Decisions` section, item comments included, then `## Stale evidence` when a check's pinned evidence is stale (see [Pinned evidence](#pinned-evidence)). An item comment counts toward it until sent with Request changes or Approve, and again once edited; on an approved plan, so does each pick changed since the approval (**Pick changed since approval**, above). Plan pages have no Send answers.
- `GET /__bluedoc/ping?path=<doc URL path>` returns `{bluedoc, home, version, code, unlocked, to, approval}`. `version` is the plugin's, `code` a hash of the server, build and template code; `serve.py open` restarts a server whose `version` or `code` differs and prints one line saying so. `unlocked` says whether the request carries the key: the cookie, or the copy the page keeps in `localStorage` (see [serve.py](#servepy)); while it doesn't, doc pages and the home page show "This browser can't save yet" with a **Copy unlock command** button. `approval` is the doc's newest approval as `{rev, at, carried, picks}`: `carried: false` with `rev === meta.rev` while the doc's JSON still matches its `docHash`; `carried: true` when every change since is progress (above); `carried: false` with an older `rev` when other changes followed; `null` when there is none, or the approved rev was edited in place. `picks` is `{"<checklist>/<item>": option}` for each decision the approval carried, its recommendation when it had no pick. The page's seed (`bp-state`) carries the same, and `index.json` each doc's as `{rev, at, carried}` with `at` in epoch seconds. The page and the home cards (and the home page's Awaiting approval and Approved filters) count the plan approved when `approval.rev === meta.rev` or `approval.carried`, and show **Changes since approved rev X** for an older one that isn't carried.
- `serve.py wait DOC --kind answers|changes|approval|any` (default `any`) returns the oldest queued message of that kind. An approval prints `--- bluedoc approval (reply <id>, rev <rev>, <time>) ---`, the Markdown, then `--- end ---`.

## build.py

`python3 <skill>/scripts/build.py …`. Exit codes: 0 ok, 1 validation errors (or warnings with `--strict`), 2 usage or I/O error.

| Command | Does |
|---|---|
| `new <type> <out.bluedoc.json> [--title "…"] [--kind "…"] [--shape pr\|area] [--target T,…] [--framework F] [--url URL]` | Copies `assets/skeletons/<type>.json`; sets `id` from the file name, `meta.rev` `1`, `meta.date` today, `meta.type`, and the title and kind when given. `--shape area` (reviews only) copies `review-area.json`: a review by area of a codebase, diffed from the last release you reviewed to head. `design` only: `--target watch,mobile,tablet,desktop,web` (default `mobile`) writes one wireframe artboard and stub screen file per target (`--target presentation` is an error: a deck is `new presentation`); `--framework plain\|horizon\|<store name>\|auto` sets the board's framework and the brief's recommendation (`auto`, the default, leaves the pick to you: see `types/design.md`). `presentation` writes three wireframe slides (`title`, `content`, `closing`) and their stub files: see `types/presentation.md`. `website` writes a home page: live from `--url` (a loopback dev server; any other is an error), else a wireframe stub screen file; `board.root` is the git repo the doc sits in. Refuses to overwrite; prints the next steps. The build fails until every `<<…>>` is filled; shell shifts and heredocs (`<<EOF`) in code don't count, and inside backticks only a span that is exactly `<<x>>` does. |
| `<doc>` | Validates (structure, field types, ids, refs, links, media, diff anchors against the expanded diff, the [contract](#contracts)), lints the writing, records the revision. A field of the wrong JSON type is an error naming its path (`ERROR sections[0].blocks[2].items[1].text: 404 is a number: must be a string`), never a traceback. |
| `<doc> -o out.html` | Also writes a standalone page with expanded diffs and media inlined; a design's screens become `srcdoc` frames with their kit inlined (warns above 10 MB). It works from `file://`, where the reply dialogs offer **Copy** only. |
| `<deck> --deck out.html` | Presentations only (any other type: exit 2). Also writes the deck as one HTML file that plays offline: every slide in its kit with the theme's tokens, in deck order, with its notes; ← → Space, Home/End, a click step, `N` notes, `F` full screen, `#3` in the URL; Ctrl/Cmd+P prints every slide as a 16:9 page. `--deck out.pdf` (or `--format pdf`) writes a PDF instead: one 16:9 page per slide in deck order, no notes, printed by headless Chrome or Chromium (`BLUEDOC_CHROME` names it, as for `serve.py snapshot`; without one: exit 1). The server sends the same files from `GET /__bluedoc/deck?path=<doc URL path>[&rev=B&theme=T&format=html\|pdf]` (a read, no key; 400 for another type; PDF without Chrome: 501), which **Export to…** downloads (served pages only: an `-o` page has no server); with no Chrome there, its PDF opens the deck's print view in a new tab for the browser's Save as PDF. The menu's **Include unapplied edits** (off by default; current revision only) sends the export as `POST /__bluedoc/deck` `{path, format, theme, drafts: {"<slide>": [{sel, tag, base, text} or {sel, tag, base, del: true}]}}` (the key; at most 300): the reader's element drafts go into the slides' text as the frames show them, plain text, only where the element still has its tag and base text; drafts with `rev` are a 400. Without Chrome a PDF with edits isn't made: export HTML and print it. `--deck` has no reader state, so it always writes the revision's text. |
| `<listing> --listing out.zip\|pdf\|html [--format folders] [--platform P] [--locale L]` | Storelistings only (any other type: exit 2). Also writes the fastlane ZIP (`--format folders`: the same files in plain folders), the review PDF or the one-file HTML: see [Export](#export). |
| `export <doc> [html\|pdf\|zip\|folders]` | Writes the doc's shareable file next to it as `<stem>.<html\|pdf\|zip>` and prints its path: a presentation's deck (`--deck`, default html), a storelisting's listing (`--listing`, default zip), any other doc's standalone page (`-o`, html only; another format exits 2). `/bluedoc-export` runs it. |
| `l10n <listing> --export L \| --import L FILE [--mt] \| --accept L KEY …` | A storelisting's translations: see [Text and locales](#text-and-locales). |
| `<doc> --check` | Validates and lints only; writes nothing (no history, no diff cache). `--strict` fails on warnings; `--no-history` doesn't read or write the history file. |
| `<doc> --show-rev B` | Prints revision B, rebuilt from the history, as JSON. |
| `<doc> --check-code [--repo DIR]` | Also compares each pinned evidence entry with its repo now (current, moved, stale, unknown; `--repo` names the repo for every pin), prints one line each and the `## Stale evidence` section, and gives an `-o` page the states: see [Pinned evidence](#pinned-evidence). Stale evidence warns; the exit code doesn't change. |
| `patch <doc> <key> …` | Changes one object by key, bumps the rev, validates, records. See below. |
| `from-md <plan.md> <out.bluedoc.json> [--org O] [--project DIR] [--change "…"]` | Imports a Markdown plan as a `plan` doc (`scripts/mdplan.py`) and builds it. The first `#` heading is the title, the first paragraph the `tldr`, each `##` a section; the numbered list under a heading like Steps or Implementation (else the first one outside context, questions, risks and verification) becomes the `steps` block, else each other `##` becomes a step; backticked paths become the `files` block (`edit` if they exist under `--project`, else `add`). Everything else stays text, tables and code. An existing out keeps its `id` and takes the next `meta.rev`, with `--change` lines as `changes`. Claude Code's plan gate (`scripts/hook.py`) runs it. |

The linter warns on: filler and ceremony words; vague words; sentences over 32 words; a `tldr` or `lead` opening with "This section/doc/document/page" or "In this …"; a last section (of 2+) titled Summary, Conclusion(s), Wrap-up, Recap or Closing thoughts; a text block with 3+ numbered lines (make it a checklist); checklist text or sub with "if you agree", "do you agree", "confirm whether"; checklist and step titles that don't start with a verb or end in `?`; titles over 90 characters, subtitles over 120, option labels over 28. In md it skips fenced code and reads each table cell on its own.

### patch

`build.py patch <doc> <key> [--set field=value …] [--json '{…}'] [--append '{…}'] [--delete] [--html FILE|-] [--change "line" …] [--resolves ID …] [--no-bump] [--pin] [--repo DIR] [--paths PATH …]`

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
| `--repo DIR` | Pins the evidence this patch records to DIR's git repo (default: the doc's repo, else the current folder's). |
| `--paths PATH …` | What that evidence covers: paths or globs from the repo root (default: the whole repo). |
| `--pin` | `step:` and `item:` keys: re-pins every evidence entry of the target to the code now, keeping each entry's `paths` unless `--paths` is given. Run it after re-running the checks; it alone is a change (`Re-recorded the evidence of <key>.`). |

Evidence the patch adds or changes (with `--set`, `--json` or `--append`, on any key) is pinned to the code revision of the moment: see [Pinned evidence](#pinned-evidence). The patch prints `pinned N evidence entries to <repo> at abc1234` (`+ uncommitted changes` when dirty), or why they are unpinned (no git, not in a repo); it never fails for want of git.

By default the rev bumps (1→2, A→B, v1→v2), `meta.date` becomes today, `changes` becomes the `--change` lines (default "Updated `<key>`.") and `resolves` the `--resolves` ids (removed when there are none); with `--no-bump` both are appended. Patch refuses to write when validation fails, keeps the file's indent, records the history, and prints `rev X → Y; <key> updated`.

`<key>` is any key in the table under [Annotations](#annotations), so a change request's `key` works as is, with or without the backticks the reply Markdown puts around it.

`el:<id>/<path>` takes `--set 'text="<text>"'` (the element's one text run, HTML-escaped; every other byte stays) or `--delete` (the element, with its line when alone on it); the artboard stays. Other options on `el:` are errors; a live page or an icons artboard refuses both and prints the source hints. Screen keys: `artboard:<id>` or `el:<id>/<path>` with no `--set`, `--json` or `--html` prints the screen file and the element's selector and writes nothing. After you edit that file, the same key with only `--change` records it as the next rev; the history keeps the old text under the old rev. `frame:` needs no option.

Link keys: `link:<id>/<element>` takes `--set to=<artboard>`, `--set kind=push|modal|tab|replace|back` and `--set label="<text>"` (empty or `null` removes the label), or `--delete`. Each rewrites only that element's start tag (located by `html.parser` offsets): every other byte of the file stays. A new link needs `to=` (or `kind=back`); an element without `data-bd` is named first, from the label, else its text; a name no element has appends `<i hidden data-bd=… data-nav=… data-nav-label=…></i>` inside the screen's root; `--delete` on such a hidden, empty element removes it. The build lints the result and puts the file back on an error.

```sh
build.py patch doc.json item:t412/tier-boundary --set choice=fix --change "#412 tier-boundary: Fix in PR, as picked."
build.py patch doc.json step:steps/0/table --set status=done --no-bump
build.py patch doc.json item:checks/unit --set done=true --json '{"evidence": [{"label": "Unit tests", "code": "pnpm test", "md": "`48 passed`"}]}' --paths services/orders-api
build.py patch doc.json item:checks/unit --pin --change "Re-ran the unit tests after the reprice fix."
build.py patch doc.json block:risks/0 --append '["Cache stampede", "Low", "High", "Jittered TTL"]'
build.py patch doc.json el:login/submit                                  # prints acme-fit-design.design/login.html  [data-bd="submit"]
build.py patch doc.json el:login/submit --change "Sign in: the button says Continue."
build.py patch doc.json 'frame:phone@2400,0' --set id=settings --set title=Settings
build.py patch doc.json link:today/tab-workouts                          # prints today.html  [data-bd="tab-workouts"]  data-nav="tab:workouts"
build.py patch doc.json link:workout/gear --set to=settings --set kind=modal --set label="Tap the gear" --resolves c8a1 --change "Settings opens from the gear."
build.py patch doc.json link:profile/settings --delete --resolves c8a2 --no-bump
build.py patch doc.json layout:main --json '{"settings": [1800, 0], "app-icon": [1180, 1100]}' --resolves c8a3 --no-bump
```

## serve.py

`python3 <skill>/scripts/serve.py …`. One server per user on `127.0.0.1` (port 8740, env `BLUEDOC_PORT`); state in `~/.bluedoc` (env `BLUEDOC_HOME`): `roots.json`, `server.json`, `key` (mode 0600) and `state.db` (see [Reader state](#reader-state)). HTML pages carry a Content-Security-Policy (hashes of their inline scripts, `frame-ancestors 'none'`) and `X-Frame-Options: DENY`. A bad `Content-Length` or a request body that times out is a 400.

**The key.** Writes (`PUT /__bluedoc/state`, the answers, change-request and approve POSTs) and `GET /__bluedoc/wait` need the header `X-Bluedoc: 1` and the server's secret from the `key` file: the CLI sends it as `X-Bluedoc-Key`, a browser as the `bluedoc_key_<port>` cookie (HttpOnly, SameSite=Strict, 400 days, renewed on each page view) or as `X-Bluedoc-Key` from `localStorage`; either one is enough. Without it the server answers 403 `{"key": true}`. A browser gets the cookie from a link with a `?key=<token>`, good for an hour and any number of opens (a link preview or an agent's fetch opening it first doesn't use it up): visiting it sets the cookie and redirects (303) to the same URL without the token. A page whose browser has the cookie fetches `GET /__bluedoc/key` (it answers `{key}`, `Cache-Control: no-store`, only with the cookie, the `X-Bluedoc` header and no foreign `Origin`, else 403) and keeps the key in `localStorage` `bluedoc:key:<port>`, which the ping, `index.json` and every write then send, for browsers that drop cookies (Tern's WKWebView); a 403 `{"key": true}` to a request that sent it drops it. Other origins can't read that storage, and a local process could as well read the `key` file; the key never goes in a URL. `ping` and `index.json` carry `unlocked`.

| Command | Does |
|---|---|
| `open <doc> [--to NAME] [--root DIR] [--browser]` | Starts the server if needed, registers the topmost ancestor folder named `docs` (else the doc's folder, or `--root`) on the home page, prints the doc's URL with a `?key=` token good for an hour. Give the reader that exact link. `--to` names who reads the replies. A folder inside a registered one is not added; a wider one is added next to the narrower ones, which keep their URLs: a doc's URL uses its deepest registered folder, and the home page lists it once. |
| `unlock [--browser]` | Prints a home-page link with a `?key=` token good for an hour, for a browser that can't save yet (another browser, an expired cookie). `--browser` also opens it in the default browser; `/bluedoc-home` runs that. |
| `snapshot <doc> [--rev R] [--url URL] [--page ID] [--width PX]` | A website doc's live pages as revision `R`'s [snapshots](#website) (default: the current `meta.rev`, every page, the board's breakpoints), taken in headless Chrome (`BLUEDOC_CHROME`, else Chrome or Chromium in the usual places) through a proxy of its own. `--url scheme://host:port` reads them from another dev server, each page keeping its path: a checkout of revision `R` on another port, to back-fill it. An earlier revision's existing snapshot is skipped, never replaced. |
| `wait <doc> [--kind answers\|changes\|approval\|any] [--timeout SEC]` | Blocks until the reader sends that kind (default `any`). Prints `--- bluedoc answers (reply <id>, rev <rev>, <time>) ---` (or `change request`, `approval`), the Markdown, `--- end ---`; exits 0, or 3 on timeout (`0` waits forever). Replies sent while nobody waits are queued, across restarts; each `wait` returns the oldest unread one. |
| `reply [<id> \| <doc>] [--kind K] [--json]` | Prints a stored reply as `wait` did: by the id `wait` printed, the doc's newest (of kind `K`), or with no target the newest of any doc. `--json` prints the JSON the page posted. Exits 1 when there is none. |
| `start`, `stop`, `status`, `add DIR`, `roots`, `run [--port N]` | Manage the background server and the home page's folders. |

Each render validates the doc (errors show as a page), shows its rev as the latest without writing the history (only `build.py` records), expands diff references, and puts the doc's reader state in the page.

### Reader state

The reader's ticks, picks, item comments, annotations with their statuses, the general comment, the Send answers message, the plan state and the last-seen rev live in `~/.bluedoc/state.db` (SQLite, mode 0600), so clearing browsing data or opening another browser loses nothing. The page keeps a copy in `localStorage` and writes through to the server; unsent writes wait in `bp:<doc.id>:__outbox:<URL path>` until the server answers, so two docs with one `id` (a copy, a git worktree) each send only their own (the older per-id `__outbox` is taken over by the first page of that id). A write the server refuses with 403 `{"key": true}` (browser not unlocked) or 404 (no doc at that address now) stays queued and goes on the next focus or write; the reader sees one toast. A standalone `-o` file or a page without a server uses `localStorage` alone. Theme, content width, the Comments panel and its filter, and the pen colour (`bluedoc:*`) stay in each browser. Replies are rows in the same file, every one kept. A doc's state follows its path. A doc moved with its folder keeps it: the first write from the new path takes over the row of the one other path with the same `id` whose folder is gone; a read never moves a row, and a doc whose file alone is gone (a branch switch) keeps its row. The first start with a new `state.db` imports the `<name>.reply/.changes/.approval` files and `inbox.json` of earlier versions and leaves them in place. Copying `state.db` with the server stopped is a full backup.

Keys are the page's `bp:<doc.id>:` keys without that prefix: `<checklist>:<item>`, `<checklist>:<item>:note`, `<checklist>:<item>:note-sent`, `<checklist>:<item>:more`, `<checklist>:<item>:pick-sent`, `__ann:<id>`, `__message`, `__planstate`, `__seen`, the reader's `__title` (1–200 characters after trimming, one line) and `__emoji` (as the doc's `emoji`), the reader's [archive](#archive) `__archived` (exactly `{"at": <ISO 8601 time>, "rev": <1–40 characters>}`; the index lists it as `archived`, the time, while `meta.rev` is that rev, else `archived: null` and `unarchivedBy: <meta.rev>` until the next PUT drops it) and `__archive-later` (a rev, 1–40 characters), and a board's undo history: `__hist` `{rev, steps: [<step id>], cursor, sealed}` (at most 200 steps; `cursor`: the steps before it are done; `sealed`: undo stops there) and `__hist:<step>` `{label, ops: [{id, before, after}]}` (each a copy of the draft, or null for none), written in the same PUT as its drafts; a step over 64 KB isn't kept. Both routes need `X-Bluedoc: 1`, the server's own `Host`, and no foreign `Origin`, else 403; the PUT also needs [the key](#servepy). `path` must be a doc under a registered folder, else 404. A `__title`, `__emoji`, `__archived` or `__archive-later` out of bounds is refused (400). An `__ann:<id>` value the page can't draw (no `target.label`, an unknown `type`, …) is dropped from a PUT (listed in the response's `dropped`) and left out of reads, as is an `__hist` or `__hist:<step>` value that isn't that shape; the page likewise skips and logs such a stored comment and keeps working.

- `GET /__bluedoc/state?path=<doc URL path>[&since=<n>]` returns `{version, state: {key: value}}`, or 204 when `n` is the current version. The version rises by one with each PUT that changes a row. A served page seeds the same in its `bp-state` element, plus `docHash` (the sha256 of the JSON it rendered, which Approve posts) and `approval` (as the ping's, see [Plans](#plans)).
- `PUT /__bluedoc/state` with `{path, import, ops: [[key, value], …]}` applies the ops in one transaction and returns `{ok, version}`. A `null` value deletes the key. `import: true` (each browser's one-time migration of its older `localStorage`) adds only keys the server lacks and drops item keys the doc doesn't have. Limits: 1 MB body (413), 2,000 ops, keys matching `^[a-z0-9_][a-z0-9:_-]*$`, string values up to 64 KB (400).
- A Python without `sqlite3`: the server prints one warning, pages carry no state, the state routes and reply POSTs answer 503, and Copy still works.

## Automation API

The built page exposes `window.BP`:

| Call | Returns |
|---|---|
| `BP.zoomTo('arch', 'api/auth')` | Scrolls to the canvas and opens the node. |
| `BP.fit('arch')` | Fits the root drawing. |
| `BP.state('arch')` | `{k, focus, revealed, flow, step, tokens}` |
| `BP.progress()` | `[{id, done, total}]` per checklist; `done` leaves out items whose evidence is stale. |
| `BP.evidence()` | `{live, stale, markdown}`: whether the page has the pins' live states (served, or `--check-code`), the keys of the checks with stale evidence, and their `## Stale evidence` Markdown. |
| `BP.progressMarkdown()` | The **Copy progress** Markdown, with the overall message and comments. |
| `BP.replyPayload()` | The reply JSON that **Send** posts. |
| `BP.choose('t412/tier-boundary', 'fix')` | Picks an option, as a click would (`null` clears). `false` if the item has no choices. |
| `BP.setNote('t412/tier-boundary', 'text')` | Sets the reader comment on an item (`''` clears). |
| `BP.moreDetails('t412/tier-boundary', on?)` | Turns **Need more details** on (default) or off, as its toggle would. `false` if the item has no choices, on `?rev=` / `?diff=`, or turning on one already sent; off withdraws a sent request. |
| `BP.openCode('pr-412', 'src/pricing/tiers.ts', 11)` | Scrolls to the diff, opens the file, jumps to the line. |
| `BP.openComment('pr-412', 0)` | Opens the n-th comment, in file-list order. |
| `BP.diffState('pr-412')` | `{file, comment, comments, cards, lines, ticked, linked}` |
| `BP.findingsView('pr-412', view?)` | A findings section's view, `'merged'`, `'checklist'` or `'diff'` (`null`: not a findings section); with `view`, picks it as its toggle would. |
| `BP.revisions()` | `[{rev, date, current, shown, changes}]`, oldest first. |
| `BP.compare()` | With `?diff=`: `{from, to, changes: [{kind: 'add'|'mod'|'del', label}]}` in page order; else `null`. |
| `BP.annotations()` | The reader's annotations, sent and unsent. |
| `BP.changesPayload()` | The change-request JSON that **Request changes → Send** posts (unsent annotations). |
| `BP.annotate({type, key, note, quote?})` | Adds an annotation, as the toolbar would. `null` on `?rev=` / `?diff=`. |
| `BP.setMode('view'|'point'|'select'|'draw')` | Switches the toolbar mode. |
| `BP.acceptRecommended(checklistId?)` | Picks the recommended option on every open decision (in that checklist and its nested ones, or the whole doc); returns how many. |
| `BP.sidebar({open, section})` | Opens/closes the right panel at the window edge, or opens it on `section` (`'comments'` or `'revisions'`); returns `{available, open, section, as}`. `available` lists the panel's tabs in order: `['comments', 'revisions']` on the current revision of a doc with a `meta.rev`, `['revisions']` on an earlier revision or in compare view (which open on it), `['comments']` without a `meta.rev`. `as` is `'dock'` (beside the page, > 1100 px), `'drawer'` (over it, 901–1100 px), `'sheet'` (bottom sheet, ≤ 900 px) or `null` when closed. The page remembers the reader's last tab and whether the panel was open; `]` and the app-bar key toggle it. |
| `BP.revisionsRail({open})` | The panel's Revisions tab (every doc with a `meta.rev`, one revision included; Compare appears from the second revision): `open: true` opens the panel on it, `open: false` closes the panel when it shows it; returns `{available, open, as}`, `as` as in `BP.sidebar` while the tab shows, else `null`. **Rev** in the app bar and the **Revision** link under Document do the same as a toggle. |
| `BP.docType` | Property: the page's type, `'docs'`, `'review'`, `'plan'`, `'design'`, `'presentation'`, `'website'` or `'other'`. |
| `BP.planState()` | `{type, state, rev, approvedRev, carried, picks}`. `state` is `'awaiting'`, `'stale'` (an earlier rev's approval that changes since don't carry: **Changes since approved rev X**), `'changes'` or `'approved'` on plan, design, presentation and website pages, `null` elsewhere; `approvedRev` is the rev of the approval the page knows (from the server's seed and ping, or this browser), else `null`; `carried` is true when the server carried an earlier rev's approval to this one; `picks` the decisions that approval carried (as the ping's), else `null`. |
| `BP.approvePayload(note?)` | The body **Approve** posts to `/__bluedoc/approve`. |
