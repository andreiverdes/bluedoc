# bluedoc JSON schema

Lookup reference for every field and command. Grep for a heading, never read the file whole: `grep -n -A25 '^## Diff' references/schema.md`. How to lay out each doc type lives in `types/<type>.md`.

Headings: `## Document` (incl. `hero`, `emoji`; `### Reader title and emoji`) · `## Contracts` · `## Section` · `## Blocks` (`### Markdown`) · `## Checklist` (`### Evidence`, `#### Pinned evidence`, `### Reader comments and replies`) · `## Diff` (`### Diff reference`, `### Embedded diff`, `### gitdiff.py`) · `## Plan blocks` (`### Steps`, `### Files`, `### Media`, `### Compare`) · `## Board` (`### Artboard`, `### Devices`, `### Screen files`, `### Links`, `### Icons`, `### Website`) · `## Listing` (`### Style and brand`, `### Shots`, `### Uploads and captures`, `### Text and locales`, `### Checks`, `### Export`) · `## Revisions` · `## Page layout` · `## Canvas` (`### Node`, `### Semantic zoom`, `### Edge`, `### Flow`) · `## Annotations` (the key grammar; `### Bottom tray`, `### Navigation`) · `## Plans` (its approval Markdown has `## Decisions` and `## Notes with the approval`) · `## build.py` (`### patch`) · `## serve.py` (`### Reader state`) · `## Automation API`

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
| `threads` | `{<comment id>: [{rev, md}]}` | no | The agent's replies to the reader's pins and general comments, by the comment's id (`c…`, as the reply Markdown prints it), oldest first. `build.py patch <doc> ann:<id> --reply "…"` appends one. See [Annotations](#annotations). |
| `sections` | `[section]` | yes | Rendered in order, numbered 01, 02, … |

`id` everywhere = lowercase letters, digits, hyphens; starts with a letter or digit.

### Reader title and emoji

On a served page of the current revision the reader renames the doc and picks its emoji in place, in the `<h1>` (a board page's `<h1>` sits in its Brief pane; the app bar shows them as the doc menu's key): a click on the title (Enter or F2 on it) makes it a field, Enter or leaving it saves, Esc or an empty title restores; the emoji opens a picker (search, about 250 emoji by category, a line for any emoji). They save as reader state `__title` and `__emoji` ([serve.py](#servepy)), never through the agent: no reply carries them and the JSON stays as it is. The page, the tab and the home page show the reader's over the doc's own until the reader resets them with the picker's **Use the doc's emoji** / **Use the doc's title**, also after a rev that changes `title` or `emoji`; a renamed doc's home title has its own as the tooltip. `?rev=`, `?diff=` and an `-o` file show them as text (an `-o` file the doc's own).

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
| `files` | `items`, `title`? | The files a plan touches as a folder tree, each with its action letter. |
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
| **Decision list** | Every item has `choices`. | A question icon, **Needs your answer** and `N open` (then **All answered**) instead of a bar. A chip under the doc's title, "N questions need your answer", goes to the first open one; it hides once the doc is approved. |
| **Progress list** | No item has `choices`. | Its bar and `n of m`. A section-level one gets a caption: on a plan, design or website, "The agent marks these as the work lands. Your ticks stay on this page and don't change the approval."; on a presentation or storelisting the same without the approval; elsewhere "Your own tracker: ticks are saved for you and go with Send answers." |

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
| `choices` | row, line 3 | Makes the item a **decision**: 2–6 options `{id, label, md}` drawn as option rows instead of a tick (see [Options](#options)). Label ≤ 28 characters. `md` is the option's explanation: 1–3 sentences of block md on what picking it means and what it costs; required on new docs (see [Options](#options)). The reader picks one (with `multi`, ticks several); picking it again clears it. A picked item counts as answered. Every item of a decision list has `choices`; no item of a progress list has. |
| `multi` | | `true`: the question takes several answers (checkboxes instead of radios). See [Options](#options). |
| `recommend` | row, line 3 | The id of the recommended option, starred; with `multi`, an id or a list of ids. |
| `choice` | | A pre-picked option, like `done` for ticks (with `multi`, an id or a list of ids). Use it only to carry over the reader's answer from an earlier round; leave it unset when the reader has not decided. Changing it in a new revision overrides the reader's stored pick. |
| `replies` | open | The agent's answers to the reader's comments on this item, `[{rev, md}]`, oldest first: see [Conversations](#conversations). Any checklist item, decision or progress, a review finding too. |

```json
{ "id": "double-auth", "text": "A retry can authorize the card twice", "sub": "Recommend fix in PR: a timeout after PayCo accepted becomes a second charge.",
  "state": "blocker", "stateKind": "risk", "recommend": "fix",
  "choices": [ { "id": "fix", "label": "Fix in PR", "md": "Send an `Idempotency-Key` with each charge before #415 merges." },
               { "id": "ticket", "label": "Ticket", "md": "#415 merges with the risk; a ticket tracks the key." },
               { "id": "decline", "label": "Decline", "md": "Keep retrying without a key: double authorizations stay possible." } ] }
```

A decision item's title states the finding or question, not an action. **Copy progress** writes the pick: `- [x] A retry can authorize the card twice → **Fix in PR**` (several answers: `→ **Lyon**, **Porto**`), adds `(recommended: …)` when the pick differs, and `(no decision; recommended: …)` when there is none. In a `diff` block, the comment card for a decision item carries the same option rows, tighter, kept in sync with the row. On a review, a section's findings show as **Merged** (each finding's full row under its lines), as the checklist or as the diff (**[Merged][Checklist][Diff]** in a bar under the section's title), and in Checklist an open finding shows its lines and that card: see [Diff](#diff).

Every decision item also gets **Need more details** as its last option row; the doc never declares it. Its explanation is fixed: *None of these yet: say what's missing in your reply, and the agent answers before you pick.* With one answer it is a radio in the option group: picking it clears the pick, and picking an option turns it off. With several answers it is a checkbox: ticking it clears the ticks, ticking an option clears it, and the item's header reads *Asking for more* (else *N picked*). On, the item's dot turns amber and its reply box takes focus to say what is missing (optional). It counts toward **Request changes** on every page with the tray, and the Markdown reads `- <text> \`item:<checklist>/<item>\` → **Need more details**`, then the comment as a quote; the item's JSON entry carries `more: true`. Once sent (with Request changes or Send answers) it reads **Details requested** until a newer `meta.rev`, which resets it; clicking it then withdraws the request. On a plan or design, **Approve** is disabled while any item asks for more details, sent or not, and the server refuses (409) an approval whose `answers` carry `more`. Stored under `bp:<doc.id>:<checklist>:<item>:more` as `1`, then `sent@<rev>`; not on `?rev=` or `?diff=`.

A row with nothing to open has no chevron; clicking it ticks it. **Expand** in the checklist header opens or closes every row. Links to `#item-<checklist>-<item>` (from a canvas node, a table cell or a shared URL) open the row, and its parents, before scrolling to it. Print shows every row open.

Ticks persist across browsers and reloads: see [Reader state](#reader-state). The sidebar shows per-checklist progress (`n/m`, or `N open` for a decision list) and the top bar the page's progress items; **Copy progress** exports all checklists as Markdown task lists (`- [x] …`) for PRs or issues, decision lists first.

A reader's tick is stored only when it differs from the item's `done`, together with the `done` it overrode. If the author later changes `done`, the author wins and the old tick is dropped, so marking a step done in a new revision shows as done for readers who unticked it earlier. Picks follow the same rule against `choice`, and a pick is dropped when its option no longer exists.

### Options

A decision's `choices` are one bordered list with hairline dividers, one HorizonUI Accordion row per option: a radio (a checkbox with `multi`), the label, a muted *★ Recommended* on the recommended option, the explanation (`md`) cut to one line, and a chevron. A click on the row, or → on it, opens it to the full explanation in Markdown (paragraphs, lists); the radio or checkbox picks. The pick gets a faint tint and *Your pick*. ↑ ↓ move between rows, Space picks, → opens; the hints sit under the list. **Need more details** is the last row (above). An option without `md` shows its label and no chevron. A diff card and the Brief draw the same rows, tighter. The rows use the page's HorizonUI tokens, dark and light. No item, option, finding, comment or list row carries a vertical bar: a state shows as a fill, an icon, a chip or a word.

**Explanations.** On a doc created from this release on, every option needs `md`: 1–3 sentences on what picking it means and what it costs. A missing one is a build error naming the item and the option (`option 'd90' of item 'decisions/retention' has no explanation`), on every rev. A doc counts as new when its history file records `created` (the bluedoc version that wrote the file; the build writes it into every new history file) or when it has no history yet. A doc whose history predates `created` gets no error and no warning: its options show their label alone. A doc without `meta.rev` keeps no history and is not held to it.

**Several answers.** `multi: true` makes a decision take ticks. `choice` and `recommend` may then each be one id or a list of ids; a list without `multi`, an id that is no option, a repeated id or an empty list is a build error. One or more ticks count as answered (the row's dot, the counts, the home page). The reader's ticks go in the item's pick key as `=<id>,<id>…|<the author's choice ids, comma-joined>` (none ticked: `=|…`). The answers and approval JSON carry `"choice": [ids]`, and the Markdown reads `→ **Lyon**, **Porto**`. A brief's `framework` and `theme`, and a decision whose versions a website section shows, take one answer: `multi` there is a build error.

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

A chip's tooltip has the full sha, the repo, the paths, the time and the state's reason; "+ changes" follows the sha when the check ran on uncommitted changes. An entry without a pin shows *unpinned*. A done progress item with stale evidence needs a recheck: its tick turns amber with **Needs recheck**, it doesn't count in the checklist's `n of m` (which adds `· N to recheck`), the sidebar tracker or the top bar, and Copy progress leaves it unticked. A done step with stale evidence shows **Needs recheck** and an amber dot. Approve warns ("2 checks have stale evidence") without blocking, and the approval, Request changes and Copy progress Markdown end with `## Stale evidence`: each such check, its changed files, its command to re-run, and the `build.py patch <doc> <key> --pin` commands that re-record its evidence (the first bumps the rev, the rest `--no-bump`). The plan-mode hook (`hook.py`) adds the same section to what it tells Claude. Earlier revisions (`?rev=`) show the pins alone.

The static build (`-o`, and so the goldens in `docs/examples/`) has no repo state: it shows each pin's commit chip without a state. `build.py doc.json --check-code [-o out.html]` prints each pin's state and the stale ones' section, and gives an `-o` page the live states.

### Conversations

Every item is a conversation: the reader's messages and the agent's replies, then a reply box. An open row runs: title and subtitle, the options, the question's details (`detail`, `code`, `blocks`, Check, refs: shown only while the row is open), **Conversation**, then the reply box. The conversation is a HorizonUI Timeline: each message has a small avatar node, the name (*You*, or the agent: the model family `serve.py open --to` gave (a value matching the user's own name is ignored), else the detected harness's, else *Agent*), the rev and the time, then its text through the page's Markdown and its files as chips. Every message shows, oldest first, nothing folded; the agent's replies of rev N come before the reader's messages sent on rev N. The reply box is a field that grows as you type, last, empty after each send; **Attach** sits at its bottom-left (see [Attachments](#attachments)) and its **Cancel** and **Save** at the bottom-right, always shown, disabled until its text or files differ from the saved comment. A closed row shows one summary line under its options (*3 messages · omp replied in rev 3 · New*), and a row with a reply new since the reader's last visit opens on load. A decision's reply box shows while its row is closed too, under the summary line: a click into it, or typing in it, opens the row, and the page scrolls so the box stays under the pointer (a Tab into it leaves the row closed). A decision with no details and no conversation has nothing to open: no chevron, and a click on it or into its box leaves it closed. A diff card and the Merged view show the same thread, compact and in sync. `?rev=` shows the thread as it stood at that rev, read-only. Sending (Request changes, Approve, Send answers) closes every answered question left open, on any doc; one still waiting for the reader (no answer, **Need more details**, an agent reply not answered) stays open.

| Part | Written by | Stored |
|---|---|---|
| The reader's messages | the page, when sent | `bp:<doc.id>:<checklist>:<item>:thread`: `[{md, rev, at, files?}]` |
| The reader's draft | the reader, in the reply box (Save, Cancel, ⌘/Ctrl+Enter) | `bp:<doc.id>:<checklist>:<item>:note`, its files `:files` |
| The agent's replies | `build.py patch <doc> item:<checklist>/<item> --reply "…"` | the item's `replies`: `[{rev, md}]` |

A reply's `rev` is the `meta.rev` it was written in (`--reply` stamps the rev the patch writes) and its `md` block Markdown of 1 to 8,192 characters; a rev the doc's history lacks is a warning. A draft goes out with Approve, Request changes or Send answers: the page appends `{md, rev: <the rev shown>, at, files?}` to `:thread` (at most 200 messages) and deletes `:note`, `:note-sent` and `:files`, in one state write. On load, a `:note` whose `:note-sent` hash matches (sent before conversations existed) moves into `:thread` with `rev: null` and shows as *earlier*; an unsent one stays in the box. **Reset** clears ticks and picks, not conversations. The export quotes each comment under its item:

```md
- [x] `tierFor` gives no tier at exactly 10 or 50 units → **Ticket** (recommended: Fix in PR)
  > Ship it with the test first.
```

In every reply Markdown (Send answers, Request changes, Approve), each sent comment is followed by the agent's latest reply on that item as context, one line of its first 300 characters (`> <agent>, rev 2: …`; the agent is named as in its conversation) when there is one, and ends with the command that answers it, naming the doc file as its URL's last segment:

```md
- [x] How long does a saved cart stay after its last use? → **180 days**
  > Why not 90?

  > omp, rev 2: 180 days covers 70 % of business reorders.
  Reply: `build.py patch acme-saved-carts-plan.bluedoc.json item:decisions/retention --reply "…"`
```

A pin's entry reads `Change: <note>` (a follow-up: `Follow-up: <text>`), a general comment `- (<id>) <text>`, each followed by its files, the same quote and `` Reply: `build.py patch <file> ann:<id> --reply "…"` ``. Answer there, short and direct; change the item itself only when the answer changes the question or its options.

#### Attachments

Every comment field has **Attach** (a paperclip, bottom-left; icon-only in the narrow ones): an item's reply box, a new pin's composer, a pending comment's editor, a sent comment's reply box, the general comment, and the messages in Send answers and Approve. It opens the browser's file picker; dropping files on the field, or pasting a screenshot into it, attaches them too. Each file goes to `POST /__bluedoc/attach` (the key, at most 50 MB), which keeps a copy as `~/.bluedoc/attachments/<doc.id>/<8 hex>-<name>` and answers `{name, path, size}`; the field shows it as a chip (icon, name, size; a click copies the path) with **×** to remove it. Up to 10 files a comment; a comment may be files alone. Attaching needs the page served by `serve.py`.

Files are part of the draft where the field has Save and Cancel (an item's box, the composer, the editor, the general comment): Save keeps them with the text, Cancel deletes the copies added since. A chip removed from a saved comment loses its copy on Save; one added and removed before Save loses it at once. The reply box of a sent comment and the dialogs' messages keep their files as they change. Deleting a comment before it is sent deletes its copies; once sent, copies stay. When sent, the files move into the message: the conversation shows them as chips under its text.

In the reply Markdown each comment's files follow its text, by full path:

```md
- How long does a saved cart stay after its last use? `item:decisions/retention` → **180 days** (`180`)
  > Here's the reorder log.
  Files:
  - `/home/acme/.bluedoc/attachments/acme-saved-carts-plan/3f9a12c0-reorders.csv` (18 KB)

  Reply: `build.py patch acme-saved-carts-plan.bluedoc.json item:decisions/retention --reply "…"`
```

In the JSON, `files: [{name, path, size}]` sits beside `note` on an item and on an annotation, `messageFiles` beside Send answers' `message`, and `noteFiles` beside an approval's `note`. Read every attached file before answering the comment it came with.

**Send answers** (the last key of the bottom tray, on pages with a checklist other than a plan, design, presentation, website or storelisting) opens a dialog: a count of decisions, ticks and comments, an overall message (stored under `bp:<doc.id>:__message`, its files under `__message-files`, printed after the page title in the export), a Markdown preview, **Copy**, and **Send**. The key is neutral with nothing to send; once the reader picks, ticks or comments on something it turns green with a count of the items whose pick, tick or comment hasn't gone (a sent answer is kept in `<checklist>:<item>:sent` while it differs from the author's). On a review, `meta.review` names the key and the dialog: `local` **Apply decisions**, `threads` **Reply and fix**, `post` **Post review** ("Post review to the PR", or "Post reviews to the PRs" with several, with a **Post as** choice per PR, its `pr-<n>` sections, or one for a page without them: Comment, Request changes or Approve, sent as `reviewEvents` `[{section, title, event}]` with `event` `COMMENT`, `REQUEST_CHANGES` or `APPROVE`, and as `Post as: …` under the Markdown's title, a line per PR when there are several; `wait` prints them in its header as `review events pr-412 REQUEST_CHANGES, pr-415 APPROVE`); see `types/review.md`. A review's send key carries the picks and ticks only: its count leaves comments out, its `items` have no `note`, `files` or `more`, its Markdown no quoted comments and no **Need more details**, and its dialog says "N comments on findings go with Request changes"; the comments on findings and **Need more details** go with **Request changes** (see [Annotations](#annotations)). Send appears only when the page is served by `scripts/serve.py` (the page probes `GET /__bluedoc/ping?path=…`); it posts to `/__bluedoc/reply`, and the server stores it in `state.db` and queues it for `serve.py wait`. The JSON:

```json
{ "kind": "answers", "doc": "<doc.id>", "rev": "<meta.rev>", "title": "…", "path": "/<root>/<path>.bluedoc.json", "at": "<ISO time>", "message": "…",
  "items": [ { "checklist": "choices", "item": "cache", "text": "…", "choice": "redis", "recommend": "valkey", "note": "…", "files": [ { "name": "repro.log", "path": "/…/.bluedoc/attachments/<doc.id>/1c2d3e4f-repro.log", "size": 2048 } ] },
             { "checklist": "stores", "item": "cities", "text": "…", "choice": ["lyon", "porto"], "recommend": ["lyon"] },
             { "checklist": "local", "item": "doctor", "text": "…", "done": true } ],
  "markdown": "<the Copy progress text>" }
```
Decision items carry `choice` (null when undecided; with `multi`, a list of ids, `[]` when none is ticked), `recommend` as written, and `more: true` when the reader asked for more details; plain items carry `done`; `note` appears only when the reader wrote a new message, and is that message alone; `files` only when it carries files (see [Attachments](#attachments)). On a review `note`, `files` and `more` never appear here: they go with Request changes. Change requests from the annotator are a separate message: see "Annotations" below. On a plan, design, presentation, website or storelisting the picks travel with **Request changes** (and **Approve**) instead: see [Plans](#plans).

## Diff

A `diff` block shows one code change and the comments on it: each finding's card sits on the lines it is about. It has two forms. A **reference** (`base` and `head`, no `files`) is what `gitdiff.py` writes; the server and the build expand it from git. The **embedded** form (`files` with hunks) is what a reference expands to, what `gitdiff.py --embed` writes and what `build.py -o` inlines; blocks written that way keep working.

### Diff reference

```json
{ "type": "diff", "id": "diff-412", "title": "acme-shop #412", "repo": "../acme-shop", "base": "89efd8e", "head": "62ccc86",
  "paths": ["src/pricing/tiers.ts"], "pr": "acme/acme-shop#412", "headRef": "bulk-discount-tiers", "baseRef": "main", "url": "https://github.com/acme/acme-shop/pull/412/files",
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
| `headRef`, `baseRef` | The PR's branch names, which `gitdiff.py --pr` stores from `gh pr view <n> --repo <owner/repo> --json headRefName,baseRefName` (a warning and none when `gh` fails). A findings section's header shows them as `head → base`; without them it shows `base` and `head`. 1–255 characters, no spaces. Also kept by `--embed`. |
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

A section holding a checklist and a `diff` whose comments are that checklist's items is a **findings section**, drawn as one card (a PR's, in a review). Its header: the title row (the number with the fold chevron under it, the title, an answered meter **n of m** and a status: **N replies** waiting, else **Answered**), then the lead under the title and, on the right under the meter, the PR's branches (**head → base**: the diff's `headRef` and `baseRef`, each cut to 32 characters with the whole name on hover; without them its `head` and `base` commits) with chips for the findings' sizes under them (count per `state`, blockers first); 600 px and narrower they stack under the lead. Under it **one toolbar**: the filter **All n · Open n · Done n** (it opens on Open), **Accept recommended (N)**, **Expand all** / **Collapse all**, **⋯** (Copy, Reset) and **[Checklist][Diff][Merged]**; every action works in every view, and a toolbar too narrow for one row drops its views' words, then its actions'. The findings checklist has no header of its own. While the findings scroll, the title row and the toolbar stick under the app bar; the lead, branches and sizes scroll away under them. Each findings section has its own view, kept per doc in reader state (`__findings-view:<section id>`: `merged`, `checklist` or `diff`); a section never switched follows the view last picked anywhere (`bluedoc:findings-view`, per browser), else Merged. Nothing folds by itself: the chevron or a click on the title folds the section to its title row, branches and sizes. Print shows Merged, every finding.

- **A finding opens and closes whole** (Checklist and Merged, one state for all its rows): a click on its title or chevron, answered or not. Closed: its head (title, subtitle, size) and, once answered, a green ✓ with the pick. Open: **More details** under the title (it becomes **Hide details**; the details, the text then the code, show below it), in Merged the code excerpt, then the options, the conversation and the reply box. **Expand all** opens every finding the filter shows. Sending (Request changes, Approve, or the send key: Send answers, Reply and fix) closes the answered findings left open; one still waiting for the reader stays open. On load the findings that need the reader open (those the filter counts as Open: no answer, a **Need more details** not sent, a reply from the agent waiting); answered ones stay closed.
- **Filter.** **Open**: no answer, a **Need more details** not sent, or a reply from the agent the reader hasn't answered (the agent's message is the thread's newest and no comment is saved). **Done**: the rest. **All**. Each section has its own, for its every view, kept per doc in reader state (`__findings-filter:<section id>`); a first visit opens on Open. A finding the reader answers stays shown until they move on (open, pick in or write in another). Each list ends with "N findings you answered are hidden · **Show**" (Show: that section's All). In Diff, a hidden finding's comment card goes and its code stays. A link, the Tracker or the header chip to a hidden finding switches its section to All.
- **Custom.** A single-answer finding has **Custom** above **Need more details**: a field whose typing picks it, stored as `<checklist>:<item>:custom`. It counts as an answer; the reply has `choice: "custom"` and `custom: "<text>"`, and the Markdown `→ **Custom**: <text>`. A pick replaces it; Accept recommended skips it.
- **Comments.** A finding's comment field opens once it has an answer (a pick, Custom or **Need more details**); until then it is dimmed and reads "Pick an answer to comment on it". A saved comment not yet sent says under its field: "<agent> will read it once changes are requested."
- **Tracker.** A decision list's tracker row reads **N replies · M open** (replies the reader hasn't read; findings with neither an answer nor a reply), else **answered**; a findings list's reads **M open**, counted as its filter counts Open, and so does the header's "N questions need your answer". A click goes to the first finding in page order that needs the reader: it opens it, scrolls to it and flashes it. With none left, it scrolls to the section.
- **Merged** shows the findings with their code in one column, ordered by the code: the findings on the whole change first, then per file (in the diff's file order: header with path, +/− and **Open in Diff view**) each commented range in line order, as the finding's row: tick or decision dot, title, subtitle, size chip, chevron; open, **More details** (the comment's text, the item's `detail`, `code` and check), the hunk lines ±3 around the range with the commented lines marked and **Show more lines** (8 more either side, up to the hunk), the options, the conversation and the reply box. A finding with several comments has a row at each place; the checklist's findings no comment points at come last under **Not tied to code**. Picks, ticks, comments, Need more details, **Accept recommended**, the tracker and progress are the item's own, in sync with Checklist and Diff. Under 700 px the column stays single and the lines scroll sideways inside their box.
- **Links.** A link into a view that is not shown shows it in that section only. `#item-…` links, a card's **Checklist item** link and `item:` annotations stay in Merged, where every finding has a row, and open and scroll to it; from Diff they switch to Checklist. A progress list's tracker row leads to Merged while it shows, else to Checklist. `#code:` links, `BP.openCode`, `BP.openComment` and revealing a `line:` or `comment:` annotation switch to Diff, except that an annotation on a line or range Merged holds stays there and opens its finding. Merged's rows, ranges and lines carry the same keys (`item:<checklist>/<item>`, `comment:<diff>/<i>`, `line:<diff>/<path>:<n>`), so a pin shows on the one that is visible.
- **Checklist.** A finding's details end with its code: for each comment on it with a line, the file header and the hunk lines around the commented range (±3), with **Open in Diff view**. It is drawn when the details first show, and its lines carry the diff's annotation keys, so a pin shows in every view.

`BP.findingsFilter(sectionId, f?)` reads or sets a section's filter; `BP.custom('<checklist>/<item>', text)` sets a Custom answer.

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
| `items[].action` | Required. `add` (A, green), `edit` (M, blue), `delete` (D, red), `rename` or `move` (R, amber). |
| `items[].from` | The old path; only for `rename` and `move`. |
| `items[].why` | Required. One line on what changes in the file. |
| `items[].step` | A step id. The row's step link jumps to that step; the build warns when no steps block has it. |

The page draws a tree of the paths: folders in the order of their first file, a folder holding only one folder sharing its row (`services/orders-api/`), files under them in the doc's order. A file's row is its action letter, its name, `from` and `why` on one line and its step's chip; the title holds the whole `why`, and clicking the row shows `from` and `why` wrapped under the name (on a phone only then). The header counts each action, over a bar of them. `title` defaults to *Changed files*.

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

A design doc (`meta.type: "design"`) has a brief section and one `board` block. The page shows the board full width, its brief (the doc's header, TL;DR, sections and status) and its screens in the left pane, one at a time: **Brief** and **Screens** are the left stripe's keys, Brief first and ringed with the decisions picked; `[` toggles the pane on the last one. A first visit on a wide window opens the Brief; the pane, open or not and on which section, is kept per doc (`bluedoc:left:<doc.id>`). The right stripe holds **Comments** and **Revisions**, as on any doc. A presentation (`meta.type: "presentation"`) is the same page whose board holds slides only: it says slides and deck where a design says screens, its toolbar's primary key is **Present**, and it is approved with **Approve presentation**. A design may still hold an occasional `slide`. A website (`meta.type: "website"`) is the same page whose board holds web pages only: see [Website](#website).

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
| `themes[]` | `{id, label, tokens}`. Each token `k` (`^[a-z][a-z0-9-]*$`) becomes the CSS variable `--k` in every frame; values are CSS strings without `; { } < > \` or `url()`. `scheme` (`dark` or `light`) also picks HorizonUI's and HeroUI's palette (`references/kits.md`). |
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

**On the page.** The toolbar switches every page to one of `breakpoints` or a typed width; each page's title bar switches that page. Its **Full page** / **Viewport** keys (kept per doc in the browser) set how tall the pages are. **Full page** (default): each page's frame is as tall as its document, at most 30 000 px, and never scrolls, so pins sit on the board; the viewport's height stays the width's design viewport (`viewport`): the proxy writes `vh`, `svh`, `lvh`, `dvh`, `vb`, `vmin` and `vmax` in the site's CSS, `<style>` and `style` attributes (and a dev server's CSS modules) as `calc(N * var(--bd-vh, 1vh))`, the inspector does the same to styles the page adds later and sets `--bd-vh`, and `innerHeight`, `visualViewport.height` and the root's `clientHeight` answer that height. Sticky and fixed elements sit at the top of the page. A page that still grows with its frame (a height set by script from something else) falls back to Viewport, with a warning. **Viewport**: each frame is the design viewport, for sticky bars and scroll effects; on the board the wheel over it pans the board, and **Present** shows Viewport and scrolls it. Pins on a page carry `bp` (its width), `section` (the section's id) and `source` (the section's hints, else the page's) in their target; the Markdown adds `At: <bp> px wide` and `Source: …` lines. A decision whose versions a section shows adds `Shown in: <page> › <section> · Source: …`. `build.py patch <doc> el:<page>/<sel>` prints the live URL (or the screen file), the selector and source hints: the section's when the selector names it (or, on a mockup, an ancestor in the screen file matches it), else every section's.

**Snapshots.** A live page shows the dev server as it is now, so an earlier revision shows the page's **snapshot** at that revision: a static copy per width in `<name>.bluedoc.snapshots/rev-<rev>/<page>@<width>.html` beside the doc (the history's neighbour; commit it with the doc). The inspector writes it: the DOM with the versions shown in place put back, no scripts, event attributes, frames or dev toolbars, every stylesheet inlined as text, and the images and fonts the page loaded as `data:` URIs (up to 1 MB each, 4.5 MB in all; a larger one stays a URL on the dev server, which may show the current site, and the page's title bar warns). The page records the current revision's live pages when the reader sends answers, changes or an approval, and when a page in Full page first settles at a width that revision has none of; `POST /__bluedoc/snapshot` takes them (the key, the current `meta.rev` only, at most 8 MB). `serve.py snapshot` records them through headless Chrome, also for an earlier revision that has none. An earlier revision's snapshot is never replaced. On `?rev=B` a live page shows B's snapshot (the nearest width it has) in the same sandboxed frame as a mockup, its page bar reads **Snapshot · rev B**; without one, a placeholder says **No snapshot of rev B** and nothing live shows. `patch` warns when the revision it replaces has no snapshot.

**Compare.** On `?diff=B` each page that both revisions have shows B's page to its left, **Rev B** beside **Rev C**, at the same width and height (Full page or Viewport, where the two scroll together); zoom and pan move both. A section whose content differs (the two frames' hash of its tags and text, else its JSON) is outlined on both and marked **changed** in the Pages list, and its page is **Changed**. The compare tray's **Side by side** / **Single** keys (kept per doc) show or hide the earlier page.

## Listing

A storelisting (`meta.type: "storelisting"`) is one app's store listing on Google Play and the App Store. It has a `listing` block and one `board` of shots (`device: "shot"`), assets (`device: "asset"`: feature graphic, banners, ad images) and an icon (`device: "icons"`, or another design doc's). The page shows the board as two **platform pages**, one per store (`#play`, `#appstore`, with `/<locale>` when it isn't the default, `@<variant>` for a variant tab). A floating toolbar at the top of the listing, like a design board's, holds, left to right: **Undo** and **Redo** with the drafts count (it opens Comments on Pending); **Google Play | App Store** and the locale menu; **Sections | Store preview | Ads** and **Jump to** a section; the Checks count (it opens the Checks tab); **Export to…**. Where its words don't fit (1440 px with both panels open, 1100 px), the view keys keep their icons, Export to… its icon and the platforms their short names, then Jump to and the counts go. The app bar keeps the breadcrumb, **Rev** and the theme. Every size, count, limit and rule comes from `assets/store-rules.json`, each with its source and access date; a rule marked `unverified` only warns. `scripts/listing.py` loads and checks it.

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

The left panel has four tabs: **Text**, **Style**, **Colors** and **Checks**; the browser keeps the last one picked (`localStorage` key `bluedoc:listing-tab`). It opens from the left stripe's **Listing** key. The brief is the left pane's **Brief**, its key above Listing's, as on every design page. **Text** lists the shown platform's fields for the shown locale, then the captions, then the captions' Typography (see [Style and brand](#style-and-brand)). Every field is editable, with a counter (code points; UTF-8 bytes for Apple keywords), red past the limit; text only a variant sets is read-only there. An edit stays unsaved (a dot on the field and on the tab; leaving the page asks first; **Approve** waits) until **Save** (⌘S; Esc reverts the field) makes each changed field a draft, `listing` op `field` `{locale, group, field, value, base}` (`group` is the platform or `strings`), keyed `field:<locale>/<group>/<field>`. Each Save is one step of the doc's undo history (the toolbar's **Undo** and **Redo**, ⌘Z and ⇧⌘Z). Request changes sends the drafts under `## Text edits`, a line each with the old and new text, then `build.py patch <doc> field:… --set <field>=<text> --change … --resolves <id>` per field (`--no-bump` after the first; this also clears an MT mark). A text over its limit saves, in red, but `patch` refuses it. Approve waits until the doc has each value. **Checks** lists the build's findings for the platform on screen (see [Checks](#checks)); its tab counts the errors, else the warnings. Point and Select pin a comment inside a shot (`el:<shot>/…`, with `platform`, `locale` and `set` in the target) or on a field (`field:`). Dragging a shot in View reorders its set; turning on a section changes `rows`. Both are drafts: Request changes sends them under **Board drafts** with one `build.py patch <doc> block:<listing path> --json '{"order": …, "rows": …}'` command.

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

A storelisting isn't approved: its style picks and drafts go with **Request changes**, and the server refuses an approval (400). Export it when the reader says so.

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
| `<url>?rev=B` | Revision B, read-only: ticks, picks and comments made there are not stored; the bottom tray (annotations, **Request changes**, the send key, **Approve**) is hidden. |
| `<url>?diff=B` | The current revision with everything that changed since B marked; `?rev=C&diff=B` compares B with C. A bottom tray steps through the changes (↑/↓, `j`/`k`) and **Done** (`Esc`) leaves compare view. |

The diff matches sections, checklist items and canvas nodes by `id`, blocks by type and `id` (or position), and table rows by content then first cell. Each change gets a **New** / **Changed** / **Removed** tag; changed things get a **What changed** box with a word-level diff of each changed field (title, subtitle, details, options, recommendation, cells, node labels, flow steps). Removed sections, blocks, items and rows are shown struck through where they were. Canvas parts that are new or changed glow in the drawing. A `diff` block reports range, files and comments that changed.

## Page layout

The template fixes the layout; documents don't set it.

- **App bar** (sticky): the home key (a house and the wordmark, flat; served, it opens the home page, else the page's top; ≤ 600 px the house alone), then the doc's emoji and title. Served, they are the **doc menu**'s key: it opens the docs of the page's folder (`/__bluedoc/index.json?root=<slug>`, loaded on the first open and again after 30 s), newest first, each with its type's icon, title, a status line (`Plan · approved, 4 of 7 steps done`, `Review · 3 to decide`) and date, this doc ticked, archived docs left out as on the home page; the search field has the focus and filters by title (case and accents aside), ↑ ↓ move, Enter opens, Esc closes, and **All projects** opens the home page; ≤ 600 px the menu spans the window under the bar. A shared page and an `-o` file show the title as text. Then **Share** and **Export**, ghost keys with their words (served pages of any type but a presentation or a storelisting, before the ⋯ menu; ≤ 900 px their icons, Export's with its chevron, which goes ≤ 380 px; see [serve.py](#servepy)), and **⋯** (Archive).
- **Stripes:** a stripe of keys runs down each side under the app bar, as an IDE's tool window bars. The left one opens the left pane: a doc's **Contents** (Sections, Tracker, Status and Related), its key ringed with the tracker's progress items done (no ring when nothing is tracked; its tooltip says it, *Contents · Week 42 1/2*); on a board **Brief** (the doc's header, TL;DR, sections and status; its ring the decisions picked, its tooltip *Brief · 2 of 7 picked*) and **Screens** (**Pages** on a website, **Slides** on a presentation, **Listing** on a storelisting: its Text, Style, Colors and Checks), one at a time in the pane, its key lit. The right one opens each section of the right panel: **Comments** (its badge the pending count) and **Revisions** (its badge the revision shown; an earlier one in the warning's colours), then, at its foot, the theme. A key opens its pane and lights up; the lit key, or the pane's **–**, hides it; one pane per side, its header its title. **[** and **]** toggle the left pane and the right panel on their last section on every page, not while typing. A shared page has no Comments key unless the doc carries threads, and no Revisions key.
- **Panes:** a pane docks beside the page where the page keeps 640 px (a board's left pane above 900 px, its right one from 1101 px), else it lies over the page, and then the other side's pane hides (the one opened last stays). A doc's Contents opens by default where it docks beside what is open, then as the reader leaves it, per doc (`bluedoc:contents:<doc.id>`); the right panel opens by default where it docks, then as the reader leaves it (`bluedoc:comments`, its section `bluedoc:sp-tab`). The content column (at most `--content-w`, 920 px) is centred in the room between the stripes and the docked panes. From 601 to 900 px the stripes stay and the panes lie over the page.
- **Phone (≤ 600 px):** no stripes. A Contents key (a board's left pane) at the app bar's left opens the left pane as a drawer (a board's with Brief and Screens as tabs); a Comments key at its right (a dot while comments wait) opens the right panel as a bottom sheet with its sections as tabs (Comments, Revisions); the theme switch is in **⋯** (a page without ⋯: a key of its own there).
- **Reader-chosen width (> 900 px):** a handle sits on each side of the content column. Dragging either one widens or narrows the column symmetrically, so it stays centred in its room; arrow keys on a focused handle move it 40 px (Shift: 160 px). A room narrower than the chosen width shows the column at the room's width. Double-click a handle (or press Home on it) to return to the default width. The width is stored per browser for every bluedoc page (`localStorage` key `bluedoc:width`), so wide tables stay readable without changing the document.
- **Theme:** follows `prefers-color-scheme`; the theme key at the foot of the right stripe overrides it per browser (`localStorage` key `bluedoc:theme`). The blueprint canvas keeps its navy palette in both themes.
- **Print:** the app bar, the stripes and the panes are hidden (a doc's Status and Related print inline under the TL;DR), light theme. A design or website prints its brief (its header first; questions and picks as on any doc), then every artboard in board order on a page of its own: its title, its device and size, and its screen scaled to fit the page (a web page at its whole height, the picked versions shown); the board, its panes' lists and the right panel's other sections don't print. The screens draw in frames of the print's own: an `-o` file's inline screens, else the screen route at the revision shown; a live page shows its snapshot, else (current revision) the live page, else a note. ⌘P / Ctrl+P (and **Export**'s print fallback) waits until every screen has drawn, then opens the print dialog; a print from the browser's menu starts before they can draw. Chrome draws only a few process-isolated sandboxed frames into a print, so a PDF of many screens needs it started with `--disable-features=IsolateSandboxedIframes`, as the **Export** PDF's Chrome is.

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
| position | `x`,`y` = centre in canvas units, **or** `col`,`row` on the grid (below). Nodes must not overlap (validator error) and should sit at least 80 apart (validator warning). |
| `w`, `h` | Size. Defaults 180 × 80; systems with `children` 240 × 140. |
| `kind` | Shape: `service` (default), `process`, `function`, `store`/`db`/`cache`/`stream` (cylinder), `queue`, `device`/`hardware` (chamfered), `actor`/`user`/`person` (pill), `client`/`app`/`ui` (window), `external`/`cloud` (dashed), `note`, `port`. |
| `state` | Outline + badge: `live` (green), `local` (cyan), `proposed`/`unverified` (amber dashed), `removed`/`replaced` (red dashed). |
| `md` | Shown in the detail panel when the node is clicked. |
| `refs` | Source anchors (inline md), e.g. `` "`src/orders/create.ts:46-84`" ``. |
| `children` | `{nodes, edges, flows}`: the node's inner architecture. Same schema, own coordinate space, nests to any depth (keep ≤ 3). |

### Semantic zoom

A node with `children` is a **system**. Collapsed, it shows its label and `⊕ OPEN`. When its inner drawing reaches about 40–72 % of its natural size on screen, the cover fades out, the system becomes a framed sub-sheet, and its children fade in with their own grid. Double-click (or double-tap, Enter, a crumb, a checklist ref) zooms to it. Escape or the crumbs go back up. Outer levels dim while you are inside a system.

Lay out children in their own space starting near `col: 0, row: 0`; the runtime scales them into the parent's box.

### Grid

`col` and `row` are places, not distances: the drawing spaces them from what it draws. Each column is as wide as its widest node and each row as tall as its tallest, and neighbouring columns (rows) sit at least 80 apart: room for the clearance edges keep round both nodes, a label's height and two lanes. A gap grows for what crosses it: 12 more per edge beyond the third, and for an edge between neighbours on one row (column), the room its label needs on the line between them (its width, or its height down a column, plus the clearance and an arrowhead at each end). Column (row) 0 is centred on 0, so a node placed with `x` (`y`) keeps its place beside the grid; the grid sizes its gaps from its own nodes only, so keep placed nodes clear of it (the validator warns under 80). A skipped `col` (`row`) number leaves room for a default node. Inside a system, the room between its children and its frame is half a gap, more on a side whose port carries edges, and a labelled port edge's label run.

### Edge

| Field | Meaning |
|---|---|
| `from`, `to` | Node ids in the **same scope**. Inside `children`, `@left`, `@right`, `@top`, `@bottom` are ports on the parent's frame: use them to show data entering or leaving the system. |
| `id` | Defaults to `"<from>-><to>"`. Set it when two edges share endpoints. |
| `label` | ≤ 28 chars: the thing that moves or the call. |
| `kind` | `data` (cyan, animated), `control` (dashed), `async` (violet dotted, queues/events), `power` (amber), `dep` (dependency, dim), `replaced` (red). |
| `dir` | `none` or `both` (default: arrow at `to`). |

Edges route themselves, as a design board's links do: right angles with rounded corners, round the scope's other nodes, leaving each node on the side facing the other end. Parallel lines are spaced apart. An edge with no way round goes through as little of the nodes in its way (their clearance before the node itself) as it can. Each label sits on its line, or beside it (touching, then up to 24 px off), clear of nodes, other labels and other edges' lines wherever such a spot exists. A frame port is a stretch of the frame's edge that edges cross square. `bend` is gone (the build warns that it is ignored).

### Flow

```json
{ "id": "request", "label": "One request", "loop": true, "color": "#5fd4ff",
  "steps": [ { "edge": "client->api", "label": "The client sends a JWT.", "payload": "JWT", "ms": 1200 },
             { "edges": ["api->db", "api->cache"], "label": "The API reads both in parallel." },
             { "edge": "api->client", "reverse": false, "label": "The API returns 200." } ] }
```

Each scope (root and every `children`) has its own flows. A token travels each step's edge(s); the caption bar shows step dots, `Step n of m` and the step `label`; `payload` floats next to the token. The toolbar controls the flows of the scope you are looking at; other open scopes loop their first flow. The ‹ / › buttons step through manually. A canvas with no flows at any level hides the caption bar. `prefers-reduced-motion` starts paused.

## Annotations

The tray of keys at the bottom of the current revision starts with **View** (`V`, default), a separator and the four comment tools, the same on every page: **Element** (`C`: pin a note on the element under the cursor; its icon and cursor are a comment pin with a plus, the cursor filled in the accent, its sharp top-left corner the point clicked, inside a board's or listing's screens too), **Region** (`M`: drag a box), **Text** (`T`: note on a selected passage), **Pen** (`D`: freehand drawing with a note). Their keys pick a tool from any mode. `Esc` closes an open menu or the picker first, then ends the tool and returns to View; `V` and the View key do the same. At 600 px and narrower the four tools fold into one key showing the current tool (Element's icon in View) with a caret; it opens them in a menu above it, and a pick, a tap outside or `Esc` closes it. In View, selecting text on the page (not in a field, the tray, a panel or a dialog) shows a **Comment** button by it, which makes the note Text makes; it hides when the selection goes, on a scroll or on `Esc`.

A **region** under 8 px is ignored; otherwise it becomes a note on the smallest element holding it, always drawn as a thin accent box and listed as "Region on …" (`type: "region"`, stored with `box`, its `[x, y, w, h]` as fractions of the target's box; like a drawing it sends `targets`, the parts it covers). While **Pen** is on, its colours and widths show in a pill above the tray, its left edge over Element: red, amber, green, blue, violet, ink and a custom colour (a picker: a colour square, a hue strip, the hex value, **Use**), then three widths, thin, medium and bold (2, 4, 7 px). Each drawing records its `color` (a pen's name or `#rrggbb`) and `width`; the browser keeps the pen (`bluedoc:pen`, `bluedoc:pen-width`, `bluedoc:pen-custom`). At 600 px and narrower a strip above the tray holds a colour key (the current colour) and a width key (the current line) instead, each opening its menu above the strip; the colour menu's Custom opens the picker.

A new note is written in a small composer next to its mark; once saved it becomes a card in the **Comments** pane on the right (open by default and docked beside the content on wide screens, over it or a bottom sheet on narrow ones; its key on the right stripe, a phone's in the app bar, or `]` shows and hides it). A saved drawing leaves its numbered pin on the page; its strokes show again while its pin or card is hovered, or it is selected or edited. Comments are **Pending** (saved, not sent), **Open** (sent with Request changes) or **Resolved** (marked by the reader, or by a revision's `resolves`: see below); the sidebar filters Pending · Open · Resolved · All. Each is stored under its own key, `bp:<doc.id>:__ann:<id>`, so two browsers adding notes don't overwrite each other. The sidebar footer has a **General comment** field for notes about the whole doc (`type: "general"`, `target.key: "doc"`, no page mark); they follow the same states. **Request changes · N** in the bottom tray sends the pending ones, through a dialog with a preview, **Copy** and **Send**; `message` repeats the general notes joined with blank lines, and the Markdown lists them first under `## General`. N also counts what goes with them besides annotations: on a plan, design or review, each item comment written or changed since the last Request changes or Approve (the page keeps a hash of the comment it sent under `<checklist>:<item>:note-sent`), and on every page, each decision item marked **Need more details** and not yet sent (see [Checklist](#checklist)). Either alone enables the key, and the dialog counts them ("1 comment on items", on a review "1 comment on findings", "2 requests for more details"; a comment on an item marked Need more details counts once, as the request). On other pages `answers` holds only those items (on a review: the findings with a comment or Need more details, each with its pick as context; the pick itself goes with the send key), and the Markdown ends with them, comments quoted, under `## Decisions`. Send posts to `/__bluedoc/changes`; the server stores it in `state.db` and queues it for `serve.py wait`. Sent notes stay dimmed until the reader clears them. The toolbar is absent on `?rev=` and `?diff=`.

```json
{ "kind": "changes", "doc": "<doc.id>", "rev": "B", "title": "…", "path": "/<root>/<path>.bluedoc.json", "at": "<ISO time>", "message": "…",
  "annotations": [ { "id": "c…", "type": "pin", "note": "Say which rounding mode.", "rev": "B", "at": "…",
                     "target": { "key": "item:t412/float-cents", "label": "02 #412 · bulk discount tiers › Findings · #412 › 2. Tiered line totals…", "text": "Tiered line totals are fractional cents …" } },
                   { "type": "text", "quote": "one-line fixes", "target": { "key": "tldr", … }, … },
                   { "type": "draw", "target": { "key": "block:trouble/0", … }, "targets": [ { "key": "row:trouble/0/0", … }, { "key": "row:trouble/0/1", … } ], … } ],
  "markdown": "# Change requests: <title> (rev B), <date>\n\n1. **<label>** (pin) `<key>` (<id>)\n   > <text>\n   Change: <note>\n" }
```

Each comment in the Markdown carries its `id` after its key (a general one: `- (<id>) <note>`). Once a revision addresses it, list the id in that revision's `resolves` (`build.py patch … --resolves <id>`). When the page loads, each **Open** comment whose id is in the `resolves` of a revision newer than the comment's `rev` (up to the current one) becomes **Resolved** with `resolvedBy: "agent"`, `resolvedRev` (the newest such revision) and `resolvedAt`, saved like any reader change; its card reads "Resolved by the agent in rev X" and keeps **Reopen**. A reopened comment keeps `resolvedRev`, so only a revision after that one resolves it again. Pending comments are never resolved this way, and ids that match no comment are ignored. The revision list shows "Resolves N comments" under a revision that has `resolves`.

**Follow-ups.** A comment card is a conversation too: the reader's note (and its files: the annotation's `files`), then the agent's replies (the doc's `threads[<id>]`, written by `build.py patch <doc> ann:<id> --reply "…"`) and the reader's follow-ups, by rev, then a reply box. A follow-up is pending (the annotation's `draft`, its files `draftFiles`) until Request changes or Approve sends it: it moves into the annotation's `thread` (`[{md, rev, at, files?}]`, as an item's) and goes out under the same comment id, with the agent's latest reply quoted, and the comment turns **Open** again, a **Resolved** one included. `resolves` still resolves; a reply without it leaves the comment Open, marked *Answered in rev N*. The Pending, Open and Resolved filters count conversations, not messages. See [Attachments](#attachments).

**General.** Comments about the whole doc (type `general`, key `doc`) are a chat at the foot of the Comments panel, under the list, not cards in it: a header (*General · about the whole doc, not one spot*), then each general comment as a bubble on the right (*You · rev N*) followed by the agent's replies to it (`threads[<id>]`) on the left with the agent's initial (*<agent> · rev N*), oldest first; it scrolls within a max height and opens at the end. Under it the composer (*Message the agent about the whole doc…*, Attach, a round Save): what is typed is a draft until Save or ⌘/Ctrl+Enter makes it a new general comment, Cancel or `Esc` drops it. A saved one is *not sent yet* (a dashed bubble, counted on Request changes) and edits in place (a click on its text, or Edit) or deletes until Request changes or Approve sends it. The Pending · Open · Resolved · All filters and **Clear resolved** cover the list, not the chat. A shared view-only page has no chat.

**Items in the Comments panel.** On every page with checklists the panel lists the items' threads with the page's comments, in the same tabs: a card per item (a review's finding, a plan's or design's question, a progress item) with a conversation, a comment saved in its reply box and not sent, or a **Need more details**. An item is **Pending** while its comment or Need more details isn't sent, **Resolved** once the doc carries its answer (a decision's `choice`: the agent recorded the reader's pick from an earlier round, see `types/review.md`; a progress item's `done: true`), and **Open** otherwise. Each tab lists them in groups, in page order: **<agent> replied** (the agent's reply is the newest message and the reader has no comment waiting: *Waiting for you*), **Not sent yet**, **You answered** (*Answered*, *sent in rev N*) and **Resolved** (*→ the doc's pick*, or *done*), then the page's comments under **On the page**. A card shows where the item lives (in a findings section its PR, `#415` for a `pr-415` section, else the section's number; elsewhere its checklist's title, cut at 24 characters), the item's text, the last message (who: text, two lines) and its state; answered and resolved cards are dimmer. A Not sent yet card names the key that carries the comment on that page: *Goes with Request changes* on a review, a presentation or a storelisting, *Goes with Request changes or Approve* on a plan, design or website, else *Goes with Send answers* (a Need more details there: *Goes with Request changes or Send answers*). A click (or Enter) on one opens the item and every item holding it (a finding in its view, shown if the findings filter hides it; a design's brief item in the Brief section), scrolls to it and rings it for a moment. The tab counts and the Comments key's badge include the items; **Clear resolved** clears the page's comments only. On load a page with checklists opens the panel by itself when something waits for the reader: an item the agent answered last (on **Open**, even over another section left open) or, while the panel is closed, a comment not sent yet, on an item or the page (on **Pending**; a design's board drafts don't count); otherwise it stays as the reader left it, and a phone's sheet stays closed. `BP.comments()` adds `groups` (the headings in order: `wait`, `unsent`, `answered`, `resolved`, `page`) and `items` (`[{item, group, status}]` as listed, `item` the `<checklist>/<item>` key); `cards` lists the page's comments only.

**Board drafts** (design, presentation and website pages): a link edit (Link mode, `L`, or an arrow's menu) is an annotation of type `link` with `link: {op: add|set|move|delete, from, el, to, kind, label?, edge?, base}` (`base`: the link as the rev has it, or null), keyed `link:<screen>/<el>`; moving screens or **Tidy up** is one annotation of type `layout` with `layout: {positions: {"<artboard>": [x, y]}}`, keyed `layout:<board>`. A double-click on a screen's text in View, Element or Link changes its one text run in place (plain text, at most 1,000 characters; Enter or a click away keeps it, `Esc` puts it back; a double-click where there is no such text focuses the screen); with Element (`C`), Delete or Backspace hides the picked element, as does **Delete element** in its comment box (not the screen itself). Each is one annotation of type `element` per element, keyed `el:<artboard>/<sel>`, with `element: {op: text|delete, ab, sel, tag, base, text, ord}` (`base`: its text as the rev had it; `ord`: its place in document order), at most 300; the frame shows it only where the element still has that tag and text, and a deletion's card has **Restore**. Drafts live in reader state, so they survive reloads, and the board and **Present** follow them at once. The reply Markdown lists them under `## Board drafts`, then one `sh` block with a ready `build.py patch` command each (the first bumps, the rest `--no-bump`; a moved link is a `--delete` on the old key, then `--set` on the new). Run them as they are. An element draft's line adds `File:` (its screen file), or on a live page `Live page:`, `At:` and `Source:`: edit the source there, then run its `--change` command. Run them as they are. On load, a draft the current rev's links or positions already match becomes **Resolved** ("Applied in rev X"), as does one a rev lists in `resolves`; one a newer rev changed some other way is **Stale**.

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
| `ann:<id>` | a reader's pin or general comment, by the id the reply Markdown prints (`c…`): its conversation, the doc's `threads[<id>]`. `patch` takes only `--reply` (with `--resolves`, `--change`, `--no-bump`) |
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
| Plan page | View · Element · Region · Text · Pen │ eye (hide or show comment marks) │ **Request changes · N** · **Approve** (green; the tooltip and dialog name the plan) |
| Other page with a checklist | View · Element · Region · Text · Pen │ eye │ **Request changes · N** · **Send answers** (a review: **Apply decisions**, **Post review** or **Reply and fix** by `meta.review`): neutral with nothing to send, green with the count of picks, ticks and comments not sent yet (on a review, picks and ticks: its comments count in Request changes) |
| Page without a checklist | View · Element · Region · Text · Pen │ eye │ **Request changes · N** |
| Design, presentation or website page | View · Element · Region · Text · Pen │ Link (`L`) · Frame (`R`) │ eye │ **Request changes · N** · **Approve** (design, website) or **Present** (a presentation, green: from the selected slide; its board toolbar's blue key is **Export to…**). A storelisting has no Link or Frame and ends with **Request changes** alone. Each decision list keeps **Accept recommended (N)** in its header, a findings section in its view bar. |

A screen on the board never runs its clicks, typing or scrolling, whatever the tray's tool: **Present**, in the board's toolbar, is where the screens are clicked through (a tap follows the screen's link).

On a phone the page fits 320 px: at 600 px and below the stripes give way to keys in the app bar (see [Page layout](#page-layout)), the home key shows the house alone, the tray's keys lose their labels and the four tools fold into one key; at 420 px the tray's keys shrink; at 380 px an empty **Request changes** count goes.

### Navigation

Every tool scrolls, pans and zooms alike, as View does; a tool takes only the primary press, and switching tools keeps the view.

| Input | Design board | Doc page and its diagrams |
|---|---|---|
| Wheel, two-finger scroll | pans; Shift + wheel pans sideways | scrolls the page (a diagram you clicked zooms) |
| Pinch, ⌃ or ⌘ + wheel | zooms at the pointer | zooms the diagram under the pointer; elsewhere the browser zooms |
| Space + drag, middle-button drag | pans | pans the diagram under the pointer, else scrolls the page |
| Keys | `0` or `Shift+1` fits, `Shift+2` zooms to the selected screen, `Shift+0` 100 %, `+` `−` zoom, `F` focuses | — |

Over a screen the board's rules hold in every tool: the screen keeps no wheel, pinch or middle-button drag, so a page in Viewport doesn't scroll on the board. Space pans outside fields (a tap still pages a doc down); on touch, a second finger ends a drawing's stroke and pinches what is under it.

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

An approval of rev X carries to a later rev Y when every change between them is progress: a step's `status` and `evidence`, a progress item's `done` and `evidence`, a decision's `choice` set to the pick the reader approved (with `multi`, the same ids in any order), the agent's replies (items' `replies`, the doc's `threads`), `meta.rev`, `meta.date`, `changes`, `resolves` and the doc's `state` labels. Any other change (text, options, sections, blocks, a screen file or icon layer) does not carry. The server decides from the history file (rev X's snapshot and screen hashes, which must match the approval's `docHash`), so `--no-bump` on rev X itself, which rewrites its snapshot, ends the approval.

**Approve** (plan, design and website pages) opens a dialog titled "Approve this plan (rev X)" (design, website): an optional note, a summary ("N pending comments go with it as notes", and "M open questions have no pick; the agent will use its recommendation" when some decision items are unpicked on a design or website), a preview of the decisions, **Copy**, and a green **Approve**. On a plan every question needs an answer first: the key stays on, but the dialog holds **Approve**, says how many questions have no answer, and each unanswered one is a button that opens it; the server answers 409 to an approval that leaves one open. A presentation or storelisting has no approval: the server answers 400 to one. Approve posts `POST /__bluedoc/approve` with the header `X-Bluedoc: 1`:

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
- <item text> → **<pick label>**, **<pick label>**   (several answers)
- <item text> → **<pick label>** (recommended: <label>)
- <item text> (no pick; recommended: <label>)
  > <the reader's comment on the item>

## Notes with the approval
1. **<label>** (pin|text|drawing|region|general) `<key>` (<id>)   (a region's label reads "Region on <label>")
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

- **Request changes** on a plan, design, presentation, website or storelisting page also carries `answers` (the decision picks) when there are any, and its Markdown ends with the same `## Decisions` section, item comments included, then `## Stale evidence` when a check's pinned evidence is stale (see [Pinned evidence](#pinned-evidence)). An item comment counts toward it until sent with Request changes or Approve, and again once edited; on an approved plan, so does each pick changed since the approval (**Pick changed since approval**, above); on a presentation or storelisting, each pick that differs from the author's until sent. These pages have no Send answers.
- `GET /__bluedoc/ping?path=<doc URL path>` returns `{bluedoc, home, version, code, unlocked, to, approval}`. `version` is the plugin's, `code` a hash of the server, build and template code; `serve.py open` restarts a server whose `version` or `code` differs and prints one line saying so. `unlocked` says whether the request carries the key: the cookie, or the copy the page keeps in `localStorage` (see [serve.py](#servepy)); while it doesn't, doc pages and the home page show "This browser can't save yet" with a **Copy unlock command** button. `approval` is the doc's newest approval as `{rev, at, carried, picks}`: `carried: false` with `rev === meta.rev` while the doc's JSON still matches its `docHash`; `carried: true` when every change since is progress (above); `carried: false` with an older `rev` when other changes followed; `null` when there is none, or the approved rev was edited in place. `picks` is `{"<checklist>/<item>": option}` for each decision the approval carried, its recommendation when it had no pick. The page's seed (`bp-state`) carries the same, and `index.json` each doc's as `{rev, at, carried}` with `at` in epoch seconds. The page and the home cards (and the home page's Awaiting approval and Approved filters) count the plan approved when `approval.rev === meta.rev` or `approval.carried`, and show **Changes since approved rev X** for an older one that isn't carried.
- `serve.py wait DOC --kind answers|changes|approval|any` (default `any`) returns the oldest queued message of that kind. An approval prints `--- bluedoc approval (reply <id>, rev <rev>, <time>) ---`, the Markdown, then `--- end ---`.

## build.py

`python3 <skill>/scripts/build.py …`. Exit codes: 0 ok, 1 validation errors (or warnings with `--strict`), 2 usage or I/O error.

**Layout.** bluedoc writes every doc as minified JSON on one line (`new`, `patch`, `from-md`, `l10n`, `gitdiff.py`, `migrate.py`). Don't read or hand-edit the file: `get` prints the outline and one object, `patch` changes one. An older pretty-printed doc is rewritten minified, content unchanged and no rev bump, when `build.py <doc>` (not `--check`), `patch` or `serve.py open` touches it, or by `migrate`. The history hashes content, so a layout-only rewrite records no revision.

| Command | Does |
|---|---|
| `new <type> <out.bluedoc.json> [--title "…"] [--kind "…"] [--shape pr\|area] [--target T,…] [--framework F] [--url URL]` | Copies `assets/skeletons/<type>.json`; sets `id` from the file name, `meta.rev` `1`, `meta.date` today, `meta.type`, and the title and kind when given. `--shape area` (reviews only) copies `review-area.json`: a review by area of a codebase, diffed from the last release you reviewed to head. `design` only: `--target watch,mobile,tablet,desktop,web` (default `mobile`) writes one wireframe artboard and stub screen file per target (`--target presentation` is an error: a deck is `new presentation`); `--framework plain\|horizon\|<store name>\|auto` sets the board's framework and the brief's recommendation (`auto`, the default, leaves the pick to you: see `types/design.md`). `presentation` writes three wireframe slides (`title`, `content`, `closing`) and their stub files: see `types/presentation.md`. `website` writes a home page: live from `--url` (a loopback dev server; any other is an error), else a wireframe stub screen file; `board.root` is the git repo the doc sits in. Refuses to overwrite; prints the next steps. The build fails until every `<<…>>` is filled; shell shifts and heredocs (`<<EOF`) in code don't count, and inside backticks only a span that is exactly `<<x>>` does. |
| `get <doc> [<key>]` | With a key (any [patch key](#annotations)): prints that object as one line of minified JSON (`ann:`: its thread; `field:`: the value). Without: the outline, one line per section, block, item, step, row, card, file, node, comment and artboard: its patch key, type (a block's `#id` when it has one) and label (~60 characters), indented under its parent. `new` prints `fill with: build.py get <doc>`: fill the placeholders with one `patch` per key, or rewrite the file once. |
| `migrate <doc\|folder> … [--dry-run]` | Rewrites each doc not yet minified (a folder: every `*.bluedoc.json` under it), content unchanged, no rev bump, no new revision; `--dry-run` lists them (`would rewrite <doc>`) and writes nothing. |
| `schema [<block>\|<part>\|<type>]` | Prints a field card, about 50–300 tokens, instead of this file's section: a block type (`schema checklist`) or a part (`item`, `evidence`, `node`, `edge`, `flow`, `artboard`, `doc`) as its purpose, one `field  type  req\|opt  notes` row per field (allowed values from the validator's own sets) and one minified `e.g.` line that validates; a doc type (`schema plan`) as its [contract](#contracts) and the sections `new` writes. No name: the block types, parts and doc types. The cards come from `SCHEMA_CARDS` in `build.py`, which the validator also reads its required fields from. |
| `<doc>` | Validates (structure, field types, ids, refs, links, media, diff anchors against the expanded diff, the [contract](#contracts), the option [explanations](#options)), lints the writing, records the revision; a new history file gets `created`, the bluedoc version that wrote it. A field of the wrong JSON type is an error naming its path (`ERROR sections[0].blocks[2].items[1].text: 404 is a number: must be a string`), never a traceback. |
| `<doc> -o out.html` | Also writes a standalone page with expanded diffs and media inlined; a design's screens become `srcdoc` frames with their kit inlined (warns above 10 MB); a website's live pages show as placeholders (they need the server). It works from `file://`, where the reply dialogs offer **Copy** only. The server sends the same file, or its print view as a PDF, from `GET /__bluedoc/export` (see [serve.py](#servepy)), which the app bar's **Export** downloads. |
| `<deck> --deck out.html` | Presentations only (any other type: exit 2). Also writes the deck as one HTML file that plays offline: every slide in its kit with the theme's tokens, in deck order, with its notes; ← → Space, Home/End, a click step, `N` notes, `F` full screen, `#3` in the URL; Ctrl/Cmd+P prints every slide as a 16:9 page. `--deck out.pdf` (or `--format pdf`) writes a PDF instead: one 16:9 page per slide in deck order, no notes, printed by headless Chrome or Chromium (`BLUEDOC_CHROME` names it, as for `serve.py snapshot`; without one: exit 1). The server sends the same files from `GET /__bluedoc/deck?path=<doc URL path>[&rev=B&theme=T&format=html\|pdf]` (a read, no key; 400 for another type; PDF without Chrome: 501), which **Export to…** downloads (served pages only: an `-o` page has no server); with no Chrome there, its PDF opens the deck's print view in a new tab for the browser's Save as PDF. The menu's **Include unapplied edits** (off by default; current revision only) sends the export as `POST /__bluedoc/deck` `{path, format, theme, drafts: {"<slide>": [{sel, tag, base, text} or {sel, tag, base, del: true}]}}` (the key; at most 300): the reader's element drafts go into the slides' text as the frames show them, plain text, only where the element still has its tag and base text; drafts with `rev` are a 400. Without Chrome a PDF with edits isn't made: export HTML and print it. `--deck` has no reader state, so it always writes the revision's text. |
| `<listing> --listing out.zip\|pdf\|html [--format folders] [--platform P] [--locale L]` | Storelistings only (any other type: exit 2). Also writes the fastlane ZIP (`--format folders`: the same files in plain folders), the review PDF or the one-file HTML: see [Export](#export). |
| `export <doc> [html\|pdf\|zip\|folders]` | Writes the doc's shareable file next to it as `<stem>.<html\|pdf\|zip>` and prints its path: a presentation's deck (`--deck`, default html), a storelisting's listing (`--listing`, default zip), any other doc's standalone page (`-o`, html only; another format exits 2). `/bluedoc-export` runs it. |
| `l10n <listing> --export L \| --import L FILE [--mt] \| --accept L KEY …` | A storelisting's translations: see [Text and locales](#text-and-locales). |
| `<doc> --check` | Validates and lints only; writes nothing (no history, no diff cache). `--strict` fails on warnings; `--no-history` doesn't read or write the history file. |
| `<doc> --show-rev B` | Prints revision B, rebuilt from the history, as JSON. |
| `<doc> --check-code [--repo DIR]` | Also compares each pinned evidence entry with its repo now (current, moved, stale, unknown; `--repo` names the repo for every pin), prints one line each and the `## Stale evidence` section, and gives an `-o` page the states: see [Pinned evidence](#pinned-evidence). Stale evidence warns; the exit code doesn't change. |
| `patch <doc> <key> …` | Changes one object by key, bumps the rev, validates, records. See below. |
| `from-md <plan.md> <out.bluedoc.json> [--org O] [--project DIR] [--change "…"]` | Imports a Markdown plan as a `plan` doc (`scripts/mdplan.py`) and builds it. The first `#` heading is the title, the first paragraph the `tldr`, each `##` a section; the numbered list under a heading like Steps or Implementation (else the first one outside context, questions, risks and verification) becomes the `steps` block, else each other `##` becomes a step; backticked paths become the `files` block (`edit` if they exist under `--project`, else `add`). Everything else stays text, tables and code. An existing out keeps its `id` and takes the next `meta.rev`, with `--change` lines as `changes`. The plan-mode hook (`scripts/hook.py`) runs it. |

The linter warns on: filler and ceremony words; vague words; sentences over 32 words; a `tldr` or `lead` opening with "This section/doc/document/page" or "In this …"; a last section (of 2+) titled Summary, Conclusion(s), Wrap-up, Recap or Closing thoughts; a text block with 3+ numbered lines (make it a checklist); checklist text or sub with "if you agree", "do you agree", "confirm whether"; checklist and step titles that don't start with a verb or end in `?`; titles over 90 characters, subtitles over 120, option labels over 28. In md it skips fenced code and reads each table cell on its own.

### patch

`build.py patch <doc> <key> [--set field=value …] [--json '{…}'] [--append '{…}' [--at N]] [--move N] [--delete] [--html FILE|-] [--reply "md"] [--change "line" …] [--resolves ID …] [--no-bump] [--pin] [--repo DIR] [--paths PATH …]`

| Option | Effect |
|---|---|
| `--set field=value` | Sets one field of the target; `value` is parsed as JSON when it parses, else used as a string. `null` deletes the field. A text that parses as JSON (`404`, `true`) needs JSON quotes: `--set 'text="404"'`. A nested path `a/b/field=value` walks `/`-separated segments first: an object's key, or in a list the element whose `id` is the segment, else its index (`--set choices/d90/md=…`, `--set choices/1/label=…`); a last segment in a list replaces that element (`null` removes it). An unknown segment exits 2 naming the keys or ids there. |
| `--json '{…}'` | Merges the object into the target (`null` deletes). |
| `--append '{…}'` | Appends to the target's list: doc → `sections`; section or item → `blocks`; table → `rows`; canvas or node → `nodes`; diff → `comments`; board → `artboards`; other blocks → `items`. `--at N` inserts at position N instead (0 = first). |
| `--move N` | Moves the target to position N of the list it sits in (a section, block, item, step, row, card, node, artboard…). Goes alone. |
| `--delete` | Removes the target. An artboard's screen file stays (the history keeps its text); delete it yourself. |
| `--html FILE` | `artboard:` and `el:` keys: replaces the screen file with FILE's text (`-` reads stdin). The build lints it first; on an error the file is put back. |
| `--change "line"` | One `changes` line; repeatable. |
| `--resolves ID` | One comment id for `resolves` (the id after the key in the reply Markdown, with or without its parentheses); repeatable. |
| `--reply "md"` | `item:<checklist>/<item>` and `ann:<id>` keys: answers the reader's comment in its [conversation](#conversations). Appends `{rev, md}` to the item's `replies` (`ann:`: to the doc's `threads[<id>]`), `rev` being the rev this patch writes (the bumped one; with `--no-bump`, the current one). One reply per call; goes with `--resolves`, `--change` and `--no-bump`, and on an `item:` key with `--set` and `--json`. |
| `--no-bump` | Keeps `meta.rev`: only while the reader hasn't seen this rev. |
| `--repo DIR` | Pins the evidence this patch records to DIR's git repo (default: the doc's repo, else the current folder's). |
| `--paths PATH …` | What that evidence covers: paths or globs from the repo root (default: the whole repo). |
| `--pin` | `step:` and `item:` keys: re-pins every evidence entry of the target to the code now, keeping each entry's `paths` unless `--paths` is given. Run it after re-running the checks; it alone is a change (`Re-recorded the evidence of <key>.`). |

Evidence the patch adds or changes (with `--set`, `--json` or `--append`, on any key) is pinned to the code revision of the moment: see [Pinned evidence](#pinned-evidence). The patch prints `pinned N evidence entries to <repo> at abc1234` (`+ uncommitted changes` when dirty), or why they are unpinned (no git, not in a repo); it never fails for want of git.

By default the rev bumps (1→2, A→B, v1→v2), `meta.date` becomes today, `changes` becomes the `--change` lines (default "Updated `<key>`.", or "Replied on `<key>`." for a reply alone) and `resolves` the `--resolves` ids (removed when there are none); with `--no-bump` both are appended. Patch refuses to write when validation fails, writes the doc minified, records the history, and prints `rev X → Y; <key> updated` (`replied` for a reply alone, `moved`, `deleted`).

`<key>` is any key in the table under [Annotations](#annotations), so a change request's `key` works as is, with or without the backticks the reply Markdown puts around it.

`el:<id>/<path>` takes `--set 'text="<text>"'` (the element's one text run, HTML-escaped; every other byte stays) or `--delete` (the element, with its line when alone on it); the artboard stays. Other options on `el:` are errors; a live page or an icons artboard refuses both and prints the source hints. Screen keys: `artboard:<id>` or `el:<id>/<path>` with no `--set`, `--json` or `--html` prints the screen file and the element's selector and writes nothing. After you edit that file, the same key with only `--change` records it as the next rev; the history keeps the old text under the old rev. `frame:` needs no option.

Link keys: `link:<id>/<element>` takes `--set to=<artboard>`, `--set kind=push|modal|tab|replace|back` and `--set label="<text>"` (empty or `null` removes the label), or `--delete`. Each rewrites only that element's start tag (located by `html.parser` offsets): every other byte of the file stays. A new link needs `to=` (or `kind=back`); an element without `data-bd` is named first, from the label, else its text; a name no element has appends `<i hidden data-bd=… data-nav=… data-nav-label=…></i>` inside the screen's root; `--delete` on such a hidden, empty element removes it. The build lints the result and puts the file back on an error.

```sh
build.py patch doc.json item:t412/tier-boundary --set choice=fix --change "#412 tier-boundary: Fix in PR, as picked."
build.py patch doc.json item:decisions/retention --reply "180 days covers 70 % of reorders; the table stays under 2 GB." --resolves c3k9
build.py patch doc.json ann:c8a4 --reply "Moved the badge under the total." --resolves c8a4
build.py patch doc.json step:steps/0/table --set status=done --no-bump
build.py patch doc.json item:decisions/retention --set choices/d90/md="About half the rows of 180 days."
build.py patch doc.json section:context --append '{"type": "text", "md": "Read this first."}' --at 0
build.py patch doc.json item:decisions/guests --move 0
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

`python3 <skill>/scripts/serve.py …`. One server per user on `127.0.0.1` (port 8740, env `BLUEDOC_PORT`); state in `~/.bluedoc` (env `BLUEDOC_HOME`): `roots.json`, `server.json`, `key` (mode 0600), `state.db` (see [Reader state](#reader-state)), `settings.json` (see [Settings](#settings)) and `app/<version>-<code>/`, the copy of the skill's scripts and assets the server runs from: removing or updating the install `open` ran from leaves a running server whole, and the copies of other versions go once a new server is up. HTML pages carry a Content-Security-Policy (hashes of their inline scripts, `frame-ancestors 'none'`) and `X-Frame-Options: DENY`. A bad `Content-Length` or a request body that times out is a 400.

**The key.** Writes (`PUT /__bluedoc/state`, the answers, change-request and approve POSTs) and `GET /__bluedoc/wait` need the header `X-Bluedoc: 1` and the server's secret from the `key` file: the CLI sends it as `X-Bluedoc-Key`, a browser as the `bluedoc_key_<port>` cookie (HttpOnly, SameSite=Strict, 400 days, renewed on each page view) or as `X-Bluedoc-Key` from `localStorage`; either one is enough. Without it the server answers 403 `{"key": true}`. A browser gets the cookie from a link with a `?key=<token>`, good for an hour and any number of opens (a link preview or an agent's fetch opening it first doesn't use it up): visiting it sets the cookie and redirects (303) to the same URL without the token. A page whose browser has the cookie fetches `GET /__bluedoc/key` (it answers `{key}`, `Cache-Control: no-store`, only with the cookie, the `X-Bluedoc` header and no foreign `Origin`, else 403) and keeps the key in `localStorage` `bluedoc:key:<port>`, which the ping, `index.json` and every write then send, for browsers that drop cookies (Tern's WKWebView); a 403 `{"key": true}` to a request that sent it drops it. Other origins can't read that storage, and a local process could as well read the `key` file; the key never goes in a URL. `ping` and `index.json` carry `unlocked`.

| Command | Does |
|---|---|
| `open <doc> [--to FAMILY] [--root DIR] [--browser]` | Starts the server if needed, registers the topmost ancestor folder named `docs` (else the doc's folder, or `--root`) on the home page, prints the doc's URL with a `?key=` token good for an hour. Give the reader that exact link. `--to` is the agent's model family (Claude, Codex, Copilot, Gemini, GLM…), shown on its replies; never the user's name: one matching it is ignored, with a warning. A folder inside a registered one is not added; a wider one is added next to the narrower ones, which keep their URLs: a doc's URL uses its deepest registered folder, and the home page lists it once. |
| `unlock [--browser]` | Prints a home-page link with a `?key=` token good for an hour, for a browser that can't save yet (another browser, an expired cookie). `--browser` also opens it in the default browser; `/bluedoc-home` runs that. |
| `snapshot <doc> [--rev R] [--url URL] [--page ID] [--width PX]` | A website doc's live pages as revision `R`'s [snapshots](#website) (default: the current `meta.rev`, every page, the board's breakpoints), taken in headless Chrome (the `chrome` [setting](#settings), else Chrome or Chromium in the usual places) through a proxy of its own. `--url scheme://host:port` reads them from another dev server, each page keeping its path: a checkout of revision `R` on another port, to back-fill it. An earlier revision's existing snapshot is skipped, never replaced. |
| `wait <doc> [--kind answers\|changes\|approval\|any] [--timeout SEC]` | Blocks until the reader sends that kind (default `any`). Prints `--- bluedoc answers (reply <id>, rev <rev>, <time>) ---` (or `change request`, `approval`), the Markdown, `--- end ---`; exits 0, or 3 on timeout (`0` waits forever). Replies sent while nobody waits are queued, across restarts; each `wait` returns the oldest unread one. |
| `reply [<id> \| <doc>] [--kind K] [--json]` | Prints a stored reply as `wait` did: by the id `wait` printed, the doc's newest (of kind `K`), or with no target the newest of any doc. `--json` prints the JSON the page posted. Exits 1 when there is none. |
| `share <doc>` | Puts the doc in a secret GitHub gist and prints the red notice, its link `https://bluedoc.ai/g/<code>` and the gist's URL; again: updates the same gist, so the link stays. See **Share** below. |
| `unshare <doc>` | Deletes the doc's gist and forgets it (also when it is gone from GitHub already). |
| `start`, `stop`, `status`, `add DIR`, `roots`, `run [--port N]` | Manage the background server and the home page's folders. |

Each render validates the doc (errors show as a page), shows its rev as the latest without writing the history (only `build.py` records), expands diff references, and puts the doc's reader state in the page.

**Export.** `GET /__bluedoc/export?path=<doc URL path>[&rev=B&theme=light|dark&format=html|pdf]` (a read, no key) sends any doc but a presentation or a storelisting (they keep their own **Export to…**: a 400 here, as is a path that is no doc, an unknown revision or format). `html` (the default): the file `build.py -o` writes, as the attachment `<stem>.html`; `rev=B` is the file as of revision B (its doc, the revisions up to it, its screens as recorded); `theme` is the page's theme it opens in until its reader picks one (else the system's). `pdf`: that file's [print view](#page-layout) (a design or website: its header and brief, then one page per artboard), printed by headless Chrome or Chromium (`BLUEDOC_CHROME`, as for `serve.py snapshot`) once `BP.printReady()` says every screen has drawn, the attachment `<stem>.pdf`; without one: 501. The app bar's **Export** (served pages only: an `-o` page or a page on `file://` has no server, so no key) is a menu of **HTML file** (*One file that opens in any browser, no server*) and **PDF** (*Print-ready, one file*) for the revision shown, in the theme the reader picked; while a PDF is made its item says *Making the PDF…*, and when the server has no Chrome it opens the browser's print dialog for the page instead (a design's once its screens have drawn), with a toast saying so.

**Share.** The app bar's **Share** key (right before **Export**: Share · Export · ⋯; on the pages that have Export, not a presentation's or a storelisting's, nor an `-o` file or a page in the viewer) and `serve.py share <doc>` put the doc, as it is now, in a secret gist on the GitHub account `gh` is signed in to (`scripts/share.py`). The gist holds three text files: `<stem>.bluedoc.json` (the doc, verbatim), `<stem>.bluedoc.history.json` (its revisions with the current one recorded; only with a `meta.rev`) and `bluedoc-page.json`, `{"bluedoc": "share/1", "version", "name": <stem>, "title", "rev", "boardGeo", "fill"}`: `fill` is exactly what `build.py -o` puts at each `__BLUEDOC_*__` placeholder (diffs expanded, media and a board's screens inline, no reader state), and `boardGeo` says whether the page needs `assets/board-geo.js` at `/*__BOARD_GEO__*/`, which the viewer fills from its own copy. The link is `https://bluedoc.ai/g/<code>`, `<code>` the gist id's bytes in base64url without padding (`share.link_for`: a 32-hex id is 22 characters, `b21699001d737be2f6e6a242851a63da` → `shaZAB1ze-L25qJChRpj2g`; a 20-hex one 14); an id that isn't even-length lowercase hex keeps the long form `https://bluedoc.ai/g/#<user>/<gist id>`, which the viewer also opens. The server makes the link (the page never does), and a share recorded with the long link reads the short one. The viewer draws the page with the latest release's template, in its no-server mode, **view-only**: no dock or bottom bar (no comment tools, **Request changes**, **Approve** or **Send**), nothing to pick, tick, comment on, annotate or edit (no Need more details or Custom answer, no reply box or general comment, no Accept recommended, Reset or Copy progress, no board edits, no rename, emoji or archive); a `choice` or `done` the doc records shows as it is, and the Comments section (its key) shows only when the doc carries threads (an item's `replies`), read-only. It shows the current revision only: no Revisions key, and `?rev=` and `?diff=` show the current revision. Navigation, the Contents pane, the theme, print and a board's pan, zoom, focus, theme pills, **Present** and **Compare** stay; the app bar says *Shared · view only*. It stores only the view prefs (theme, content and panel widths, panel open and section) in bluedoc.ai's localStorage; everything else lasts the visit. The first share runs `gh gist create` (secret, described `bluedoc: <title>`); **Share again** runs `gh api -X PATCH gists/<id>` with every file (a file the share no longer has is removed), so the link stays; nothing updates the gist but a share, and a gist deleted on GitHub is created anew (a new link). A `bluedoc-page.json` over 10 MB is refused (413), pointing to **Export → HTML file**. `gh` is checked first: missing (501), signed out (502, *run `gh auth login -s gist`*) or a token without the `gist` scope (502, *run `gh auth refresh -s gist`*). The share (gist id, user, link, rev shared, when) is kept in `~/.bluedoc/shares.json` (mode 0600) by the doc's path, never in the doc or its folder. Every share shows a red notice: ***bluedoc isn't responsible for this share method or for secrets leaked through GitHub gists.** A secret gist is unlisted and not searchable, but anyone with the link can read it. Check the doc for secrets before you share.* The key (its icon and *Share*; ≤ 900 px its icon) opens the share dialog: unshared, the notice with what goes in (revisions, diffs with their code, media files, screens) and **Share** / **Cancel**; once shared, the link with **Copy** (copied on sharing), *Shared · rev B · when*, the notice again, **Share again** (the accent while the doc is at a newer rev) and **Stop sharing** (a second press deletes the gist). A shared doc's key carries a dot in the accent, in the warning colour while the doc's rev is newer than the share's (its title says which revs; the page reads it on load). Routes, all with the `X-Bluedoc` header and the key: `GET /__bluedoc/share?path=<doc URL path>[&brief=1]` → `{share: {id, user, link, url, rev, at, files} or null, rev, contents}` (`brief`: without `contents`, the key's mark); `POST /__bluedoc/share {path}` → `{share, created, relinked, contents, files}`; `POST /__bluedoc/unshare {path}` → `{ok, removed}`. Errors are `{error}` with the status above, 400 for a presentation or a storelisting.

### Settings

`~/.bluedoc/settings.json` holds what the home page's Settings (`/settings`, the gear at the foot of its sidebar) changes; `scripts/settings.py` reads it, and a missing key is the default. An environment variable that is set (not empty) wins over the file, and Settings shows that row locked.

| Key | Value | Environment | Used by |
|---|---|---|---|
| `planHook` | `true` (default) or `false` | `BLUEDOC_PLAN_HOOK` (`0`, `false`, `no`, `off`: off) | the plan-mode hook (`hook.py`): off, every agent shows its own plan dialog |
| `patchOnly` | `true` (default) or `false` | `BLUEDOC_PATCH_ONLY` (`0`, `false`, `no`, `off`: off) | patch-only edits (`hook.py`): on, agents' edit and write tools can't change a built doc, which takes `build.py patch` instead |
| `chrome` | Chrome's path, or `null` for the usual places | `BLUEDOC_CHROME` | PDFs, decks, listing exports, `snapshot`, `capture.py` |
| `fontDirs` | a list of folders, or `null` for this system's | `BLUEDOC_FONT_DIRS` (separated by `:`, `;` on Windows) | `fonts.py` (a listing's caption fonts) |

Routes (GETs need the right `Host`, as `index.json` does; POSTs need the key, as every write does):

- `GET /settings` is the home page, which opens on Settings.
- `GET /__bluedoc/settings` returns `{folders: [{path, display, docs, exists}], repos: [{name, path, display, exists}], frameworks: [{name, label, version, files, bytes, source}], presets, agents: {planHook, patchOnly}, tools: {chrome: {…, found, version}, fontDirs: {…, system}}, server: {version, code, url, port, portEnv, home, homeDisplay, homeEnv, started, pid}}`. Each setting is `{value, source: env|file|default, env: "NAME=value" or null}`; `presets` are the `add-framework` presets not added yet.
- `POST /__bluedoc/settings` with any of `{planHook, patchOnly, chrome, fontDirs}` writes them (`null` removes the key) and returns the view above; 409 `{error: "set by BLUEDOC_X in the environment"}` when that variable is set, 400 for a bad value (a switch that isn't `true` or `false`, a Chrome path that isn't there or can't run, a font folder that isn't one).
- `POST /__bluedoc/folders` `{add: "~/path"}` or `{remove: "/abs"}` changes `roots.json` (as `add` does: a folder inside a listed one is refused) and returns `{folders}`; 400 `{error: "No folder at ~/path"}`.
- `POST /__bluedoc/repos` `{remove: "name"}` drops a code-link name from `repos.json` (a build in that repo adds it again) and returns `{repos}`.
- `POST /__bluedoc/frameworks` `{remove: "name"}` or `{add: "<preset>"}` (fetched as `add-framework <preset>` does) returns `{frameworks, presets}`; 502 when the preset can't be fetched.
- `POST /__bluedoc/chrome-test` `{path}` (`null`: the current setting) runs `<path> --version`: `{ok: true, path, version}` or `{ok: false, error}`.
- `POST /__bluedoc/restart` answers `{ok: true}`, then runs the server again in the same process, on the same port and home, from the same app copy. The ping's `started` (ISO time) changes and its `pid` stays.

### Reader state

The reader's ticks, picks, item comments, annotations with their statuses, the general comment, the Send answers message, the plan state and the last-seen rev live in `~/.bluedoc/state.db` (SQLite, mode 0600), so clearing browsing data or opening another browser loses nothing. The page keeps a copy in `localStorage` and writes through to the server; unsent writes wait in `bp:<doc.id>:__outbox:<URL path>` until the server answers, so two docs with one `id` (a copy, a git worktree) each send only their own (the older per-id `__outbox` is taken over by the first page of that id). A write the server refuses with 403 `{"key": true}` (browser not unlocked) or 404 (no doc at that address now) stays queued and goes on the next focus or write; the reader sees one toast. A standalone `-o` file or a page without a server uses `localStorage` alone. Theme, content width, the Comments panel and its filter, and the pen colour (`bluedoc:*`) stay in each browser. Replies are rows in the same file, every one kept. A doc's state follows its path. A doc moved with its folder keeps it: the first write from the new path takes over the row of the one other path with the same `id` whose folder is gone; a read never moves a row, and a doc whose file alone is gone (a branch switch) keeps its row. The first start with a new `state.db` imports the `<name>.reply/.changes/.approval` files and `inbox.json` of earlier versions and leaves them in place. Copying `state.db` with the server stopped is a full backup.

Keys are the page's `bp:<doc.id>:` keys without that prefix: `<checklist>:<item>` (a tick, or a pick `=<id>|<the author's choice>`; with `multi`, `=<id>,<id>…|<the author's ids>`, each list comma-joined, `=|…` when none is ticked), `<checklist>:<item>:note` (the reply box's draft), `<checklist>:<item>:files` (its files: a JSON list of at most 10 `{"name": <1–255 characters>, "path": <an absolute path>, "size": <bytes>}`, see [Attachments](#attachments)), `<checklist>:<item>:note-sent`, `<checklist>:<item>:thread` (the reader's sent messages: a JSON list of at most 200 `{"md": <0–8,192 characters, at least 1 without files>, "rev": <1–40 characters, or null>, "at": <ISO 8601 time>, "files"?: <as :files, at least 1>}`, see [Conversations](#conversations)), `<checklist>:<item>:more`, `<checklist>:<item>:pick-sent`, `__ann:<id>` (with its follow-ups: `thread`, the same list, `draft`, a string or null, and `files` and `draftFiles`, as `:files` or null), `__message`, `__message-files` (as `:files`), `__planstate`, `__seen`, the reader's `__title` (1–200 characters after trimming, one line) and `__emoji` (as the doc's `emoji`), the reader's [archive](#archive) `__archived` (exactly `{"at": <ISO 8601 time>, "rev": <1–40 characters>}`; the index lists it as `archived`, the time, while `meta.rev` is that rev, else `archived: null` and `unarchivedBy: <meta.rev>` until the next PUT drops it) and `__archive-later` (a rev, 1–40 characters), and a board's undo history: `__hist` `{rev, steps: [<step id>], cursor, sealed}` (at most 200 steps; `cursor`: the steps before it are done; `sealed`: undo stops there) and `__hist:<step>` `{label, ops: [{id, before, after}]}` (each a copy of the draft, or null for none), written in the same PUT as its drafts; a step over 64 KB isn't kept. Both routes need `X-Bluedoc: 1`, the server's own `Host`, and no foreign `Origin`, else 403; the PUT also needs [the key](#servepy). `path` must be a doc under a registered folder, else 404. A `__title`, `__emoji`, `__archived` or `__archive-later` out of bounds, and a `:thread`, `:files`, `__message-files` or pick of another shape, is refused (400) and left out of reads. An `__ann:<id>` value the page can't draw (no `target.label`, an unknown `type`, a `thread`, `draft`, `files` or `draftFiles` of another shape, …) is dropped from a PUT (listed in the response's `dropped`) and left out of reads, as is an `__hist` or `__hist:<step>` value that isn't that shape; the page likewise skips and logs such a stored comment and keeps working.

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
| `BP.annotate({type, key, note, quote?, pos?, strokes?, color?, width?, box?})` | Adds an annotation, as the toolbar would: `type` `pin`, `text` (`quote`), `draw` (`strokes`, `color`, `width`: 2, 4 or 7) or `region` (`box`). `null` on `?rev=` / `?diff=`. |
| `BP.setMode('view'|'point'|'region'|'select'|'draw')` | Switches the tray's tool: View, Element, Region, Text or Pen (board pages also `'link'`, `'frame'`). |
| `BP.acceptRecommended(checklistId?)` | Picks the recommended option on every open decision (in that checklist and its nested ones, or the whole doc); returns how many. |
| `BP.sidebar({open, section})` | Opens/closes the right panel, or opens it on `section` (`'comments'` or `'revisions'`; `'brief'` opens a board's left pane on its Brief); returns `{available, open, section, as}`. `available` lists its sections in their keys' order on the right stripe: `['comments', 'revisions']` on the current revision of a doc with a `meta.rev`, `['revisions']` on an earlier revision or in compare view (which open on it), `['comments']` without a `meta.rev` or on a shared page. `as` is `'dock'` (beside the page), `'drawer'` (over it), `'sheet'` (bottom sheet, ≤ 600 px) or `null` when closed. The page remembers the reader's last section and whether the panel was open; `]`, the section's key and a phone's Comments key toggle it. |
| `BP.contents({open})` | A doc's Contents pane (the left one; `null` on a board, whose left panel `BP.board().panel` reports): `open` shows or hides it, remembered per doc; returns `{open, as}`, `as` `'dock'`, `'drawer'` or `null`. `[` and the Contents key toggle it. |
| `BP.revisionsRail({open})` | The panel's Revisions section (every doc with a `meta.rev`, one revision included, but a shared page; Compare appears from the second revision): `open: true` opens the panel on it, `open: false` closes the panel when it shows it; returns `{available, open, as}`, `as` as in `BP.sidebar` while it shows, else `null`. The Revisions key does the same as a toggle. |
| `BP.docType` | Property: the page's type, `'docs'`, `'review'`, `'plan'`, `'design'`, `'presentation'`, `'website'` or `'other'`. |
| `BP.printReady()` | Whether the page's print has drawn: on a design or website it builds the print sheet first (every artboard's screen in a frame of its own) and is true once each screen has said it's ready (or 4 s after its load); elsewhere always true. The **Export** PDF's Chrome waits for it. |
| `BP.planState()` | `{type, state, rev, approvedRev, carried, picks}`. `state` is `'awaiting'`, `'stale'` (an earlier rev's approval that changes since don't carry: **Changes since approved rev X**), `'changes'` or `'approved'` on plan, design, presentation and website pages, `null` elsewhere; `approvedRev` is the rev of the approval the page knows (from the server's seed and ping, or this browser), else `null`; `carried` is true when the server carried an earlier rev's approval to this one; `picks` the decisions that approval carried (as the ping's), else `null`. |
| `BP.approvePayload(note?)` | The body **Approve** posts to `/__bluedoc/approve`. |
