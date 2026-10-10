# bluedoc

![Zooming into the orders-api system, then into pricing inside it, then into fulfilment-worker, each level playing its own flow](docs/tour.gif)

An agent skill for engineering docs, plans, code reviews and UI mockups. The agent writes one JSON file (plus small HTML fragments for mockups); a local server renders it as a page with a zoomable blueprint of the system, checklists that remember your ticks, plans and designs you approve or send back, and review findings pinned to their lines from git. Your picks, comments and approvals go back to the agent, and each revision can be compared with the last. Works with Claude Code, Codex, pi and omp.

## What you get

- **Blueprint canvas.** Open a system to see its parts; each level plays its own animated flow (request, event, data). Nests 3 levels deep.
- **Checklists as task trackers.** Every procedure is a checklist. Each item is a two-line row (the action, then why it matters) that opens to show details, commands, checks, tables or a sub-checklist. Ticks persist on the local server, so another browser or cleared site data keeps them; **Copy progress** exports Markdown for a PR or issue.
- **Decisions, not "tick if you agree".** When the agent needs you to choose, an item shows its options as pills with the agent's recommendation starred. You pick one, or press **Accept recommended** (for the whole doc in the bottom toolbar, or per checklist) to take every starred option at once; the export says what you picked and what was recommended.
- **Answers back to the agent.** Every item takes a comment. **Send answers**, the last key in the bottom tray, collects your picks, ticks and comments, plus an overall message, and sends them to the agent (or copies them for you to paste). It turns green once there is something to send.
- **Change requests on the page.** A tray of keys at the bottom (View, Point, Select, Draw) lets you pin a comment on any element, comment on a selected passage, or draw on the page; you write the note right next to the mark, and saved notes become cards in the Comments sidebar on the right (Pending, Open once sent, Resolved); a General comment field takes notes about the whole doc. **Request changes** sends the pending ones to the agent as edits to make. Answers and change requests are separate messages.
- **Plans you approve on the page.** Instead of a Markdown plan, the agent writes a plan page: the goal, the proposed design on a canvas, before/after panes, mockups, a numbered timeline of steps, the files each step touches, open questions with its recommendation starred, risks and checks. Comment on any part, then **Request changes** or **Approve plan**; your picks and notes go with it, and the agent waits for your approval before it writes code.
- **Design mockups on a board.** A design doc is a brief plus a board of screens: a round watch, a phone, a tablet, a desktop window, a browser or presentation slides, side by side on a pan-and-zoom board. Each screen is a small HTML fragment the agent writes, rendered in bluedoc's plain kit, the bundled HorizonUI or your project's own CSS, at sketch, wireframe or hi-fi fidelity. Pick a theme in the brief and every screen re-skins at once. Point at a button to comment on it, draw a box to ask for a new screen, compare a screen with an earlier revision side by side or as an onion skin, then **Request changes** or **Approve design**. Screens run sandboxed: they can't reach the page, your input or the network. See [Design mockups](#design-mockups).
- **Code review.** A `diff` block shows a change with each finding as a comment on its lines, and its options on the card. A file with several comments says how many, steps between them, and tells you how many sit above or below what you can see. The doc stores only the git range (`gitdiff.py` writes it); the server expands it from git on each render and caches the result next to the doc, falling back to `gh pr diff`. GitHub review threads come in through `ghthreads.py`.
- **Revisions you can compare.** Each build keeps the doc's revision history. From the Revisions rail beside the content (shown on every doc), switch to any earlier revision or compare two: new, changed and removed sections, items, table rows and drawing parts are marked in place with a word-level diff, next to the author's note on what changed. Readers who come back to a newer revision get a link to what changed since their last visit.
- **A local server, a home page, JSON only.** `serve.py` renders each doc from its JSON on every request, so agents write only the JSON, never the HTML. `http://127.0.0.1:8740/` is a HorizonUI dashboard: a search-first hero, a sidebar of projects with their folder trees, doc types and status, activity and decision charts, and every doc as a card whose hero is shared by its type and shows the type's own element (a review's +/− lines, a plan's step timeline, a doc's drawing), in a grid (2–6 columns), a list or a board. `build.py -o` still writes a standalone HTML file when you need to send one.
- **Your input stays on your machine.** Ticks, picks, comments, annotations, the plan's state and every reply you send live in `~/.bluedoc/state.db`, a SQLite file the server owns, never in the repo. Only a browser that opened a link from `serve.py open` or `serve.py unlock` (a one-time key that sets a cookie) can save, so a web page you visit can't write your answers. Each browser keeps a copy and catches up when the server is back; a standalone `-o` file keeps its input in the browser. Theme and width stay per browser.
- **Self-contained pages.** No network at view time beyond the local server, prints cleanly, light and dark theme, keyboard and screen-reader outline.
- **Adjustable width.** Drag the handle on either side of the text to widen or narrow it; it stays centred and every bluedoc page in that browser remembers the width. Wide tables stop wrapping. Double-click a handle to reset.
- **Linted writing.** The build flags filler, vague words, long sentences and checklist items that don't start with a verb.

| The page | A review finding on its code |
|---|---|
| ![A bluedoc page: header, status rail, contents and the blueprint canvas](docs/header.png) | ![A diff block with a blocker comment under line 17](docs/review.png) |

Open the examples in a browser to try them: [`acme-orders.html`](docs/examples/acme-orders.html) (architecture and runbook), [`acme-review-findings.html`](docs/examples/acme-review-findings.html) (review findings for two PRs) and [`acme-saved-carts-plan.html`](docs/examples/acme-saved-carts-plan.html) (a plan to approve). Download the file, then open it; GitHub shows HTML as source. Their JSON sources sit in `skills/bluedoc/examples/`; `build.py <json> -o <name>.html` rebuilds them. The design example, `acme-fit-design.bluedoc.json` (a watch face, a phone sign-in with a variant, and a web dashboard, over two revisions), opens with `serve.py open skills/bluedoc/examples/acme-fit-design.bluedoc.json`; the deck example, `acme-fit-deck.bluedoc.json` (a five-slide Q3 launch review with speaker notes), opens the same way.

## Install

Pick your agent. Each one installs the same skill from this repository.

### Claude Code

```sh
claude plugin marketplace add andreiverdes/bluedoc
claude plugin install bluedoc@bluedoc
```

Inside a session the same commands are `/plugin marketplace add andreiverdes/bluedoc` and `/plugin install bluedoc@bluedoc`. Start a new session to load the skill.

### Codex

```sh
codex plugin marketplace add andreiverdes/bluedoc
codex plugin add bluedoc@bluedoc
```

Restart Codex. The skill is listed as `bluedoc:bluedoc`; mention it with `$bluedoc` or let Codex pick it from your request.

### pi

```sh
pi install git:github.com/andreiverdes/bluedoc
```

Restart pi. Run it as `/skill:bluedoc` or let pi pick it from your request.

### omp

```sh
omp plugin marketplace add andreiverdes/bluedoc
omp plugin install bluedoc@bluedoc
```

Run `/reload-plugins` in an open session, or start a new one.

### Any other agent

With the [skills CLI](https://skills.sh):

```sh
npx skills add andreiverdes/bluedoc
```

Or copy the skill folder by hand. Codex, pi and omp read `~/.agents/skills`; Claude Code reads `~/.claude/skills`.

```sh
git clone https://github.com/andreiverdes/bluedoc.git
ln -s "$PWD/bluedoc/skills/bluedoc" ~/.agents/skills/bluedoc
```

### Requirements

- Python 3.9 or later on `PATH` (the build and diff scripts use the standard library only).
- `git`, for code reviews.
- `gh`, signed in, only for importing GitHub review threads or diffing a PR whose repo isn't checked out.

## Use

Ask in plain words. The skill triggers on requests for HTML docs, architecture pages, walkthroughs, runbooks, plans, browsable reviews and UI mockups.

- "Write a bluedoc of how a request flows through this service."
- "Make a runbook for setting up the local stack, as a bluedoc with checklists."
- "Review PR 412 and give me a bluedoc where each finding sits on its code."
- "Put the open review threads on PR 412 in a bluedoc so I can decide what to do with each."
- "Plan saved carts as a bluedoc and wait for my approval."
- "Mock up the sign-in screen for the phone and the web as a bluedoc design."

The agent scaffolds `docs/<topic>/<name>.bluedoc.json` from the type's skeleton (the only file it edits, plus any images the doc shows and a design's screen files; the revision history `<name>.bluedoc.history.json` and a review's diff cache `<name>.diffcache.json` sit next to it), fills it in, validates it and opens it on the local server:

```sh
python3 <skill>/scripts/build.py new plan docs/plans/saved-carts.bluedoc.json --title "Saved carts"   # skeleton with <<…>> to fill
python3 <skill>/scripts/build.py docs/plans/saved-carts.bluedoc.json        # validate, record the revision
python3 <skill>/scripts/serve.py open docs/plans/saved-carts.bluedoc.json   # start the server, print the URL (with a one-time key)
```

When you send comments back, the agent revises one object at a time, and the revision bumps itself:

```sh
python3 <skill>/scripts/build.py patch docs/plans/saved-carts.bluedoc.json item:decisions/retention \
  --set recommend=d90 --change "Retention: recommend 90 days, as asked."
```

Every doc the server knows is listed at `http://127.0.0.1:8740/`. Edit the JSON and reload; there is no build output to keep in sync. For a file you can send to someone, add `-o <name>.html` to the build command.

Per doc, the agent reads about 1.5k tokens of instructions (`SKILL.md`) plus one type guide (`types/<type>.md`), and greps the schema only for the fields it needs.

`<skill>` is the installed skill folder, for example `~/.agents/skills/bluedoc`.

## Design mockups

A design doc (`meta.type: "design"`) is a brief and one board. The brief holds the decisions the reader picks: framework, theme, motion. The board lists the artboards, one per screen, each with a device, a fidelity (`sketch`, `wireframe` or `hifi`) and an optional framework. Each screen is a body fragment in `<name>.design/<artboard id>.html` beside the JSON; the server wraps it in the kit, so the agent never writes `<head>`, framework links or tokens.

```sh
python3 <skill>/scripts/build.py new design docs/design/sign-in.bluedoc.json --title "Sign in" --target mobile,web
python3 <skill>/scripts/build.py docs/design/sign-in.bluedoc.json         # validate, lint the screens, record the revision
python3 <skill>/scripts/serve.py open docs/design/sign-in.bluedoc.json    # the board
```

- **Frameworks.** Built in, offline, with nothing to add: the plain kit (tokens, layout, type, buttons, fields, wireframe boxes, a hand font for sketches), HorizonUI, HeroUI (`heroui`: HeroUI's CSS with Tailwind's browser build) and Tailwind alone (`tailwind`). Your project's own CSS and JS: name the files in `board.frameworks[].files`, relative to the doc. A framework your project doesn't have: `serve.py add-framework daisyui` fetches a pinned preset, and `serve.py add-framework <name> <path|url>` copies your own files; either lands once in `~/.bluedoc/frameworks/<name>/` with a manifest of sizes and sha256, and boards name it with `store`. It is the only network fetch, and only on your command. When a framework's files are missing, its screens fall back to the plain kit with a notice, and the build warns. A doc that names the old `heroui` or `tailwind` store loads the shipped copy.
- **When the project has none,** the agent recommends HeroUI for web, desktop and mobile screens, and the plain kit for watches and slides. HeroUI runs as its CSS classes plus Tailwind utilities compiled inside the frame; Konsta UI, the usual mobile kit, ships only framework components that a static screen can't load.
- **Presentations.** `--target presentation` scaffolds a deck: 16:9 `slide` artboards (1920×1080) built from the kit's slide classes, each with optional speaker `notes`. **Present** plays the slides full-window in board order (top to bottom, left to right): ← → to step, `N` for notes, Esc to leave. The bundled deck, `skills/bluedoc/examples/acme-fit-deck.bluedoc.json`, has a title, two columns, a big number, a quote and the ask, with speaker notes.
- **The board.** The toolbar stays centred over the board. Drag the inner edge of the Screens/Brief panel or the Comments/Revisions panel to resize it; every design page in that browser remembers the widths. Double-click a handle to reset.
- **Revisions.** Each build records the screens' HTML in the doc's history file, stored once per version. An edit to a screen file counts as an edit to the doc: it voids an approval, as a JSON edit does. The Revisions tab beside Comments compares a screen with an earlier revision side by side or as an onion skin.
- **Comments on a screen.** Point at an element to comment on it: the key is `el:<artboard>/<name>`, from the element's `data-bd` name, so the agent edits that element in that file. `artboard:<id>` keys a whole screen; a box drawn in Frame mode asks for a new screen (`frame:`).
- **Sandbox.** Each screen runs in an `<iframe sandbox="allow-scripts">` from its own route, whose CSP allows no network connections. A screen can't read the page, your cookies or stored input, post an approval, or navigate the tab. The build rejects network URLs, `<base>`, `<meta http-equiv>`, `<iframe>`, `<object>`, `<embed>` and `<form action>` in screen files.

## Update and remove

| Agent | Update | Remove |
|---|---|---|
| Claude Code | `claude plugin marketplace update bluedoc` then `claude plugin update bluedoc@bluedoc` | `claude plugin uninstall bluedoc@bluedoc` |
| Codex | `codex plugin marketplace upgrade bluedoc` | `codex plugin remove bluedoc@bluedoc` |
| pi | `pi update` | `pi remove git:github.com/andreiverdes/bluedoc` |
| omp | `omp plugin upgrade bluedoc@bluedoc` | `omp plugin uninstall bluedoc@bluedoc` |
| skills CLI | `npx skills update` | `npx skills remove bluedoc` |

## What's in the repo

```text
skills/bluedoc/
  SKILL.md               the workflow card the agent reads first
  types/<type>.md        one guide per doc type: plan, review, docs, design, other
  references/schema.md   every JSON field and command, for lookup
  references/kits.md     the plain kit's classes, HorizonUI in a screen, bringing your own framework
  assets/skeletons/      fill-in skeleton per doc type (build.py new), plus review-area.json (--shape area)
  scripts/build.py       new, validate, lint, patch, build the HTML
  scripts/gitdiff.py     git range + findings -> diff block (a git reference)
  scripts/diffref.py     expands diff references from the cache, git or gh
  scripts/migrate.py     one-off: embedded diffs -> references, reports contract gaps
  scripts/ghthreads.py   GitHub review threads -> findings + diff comments
  scripts/serve.py       local server: renders docs and design screens, home page, answers and change requests
  scripts/statedb.py     the reader's input and replies in ~/.bluedoc/state.db (SQLite)
  assets/template.html   the page runtime (styling, canvas, checklists, diff browser, design board, annotator)
  assets/home.html       the home page (HorizonUI)
  assets/kits/           what a design screen is wrapped in: shell, plain kit CSS, wireframe CSS, inspector
  assets/vendor/         HorizonUI browser build (Apache-2.0, see its NOTICE); fonts/: the sketch hand font (OFL-1.1)
  examples/              Acme examples (JSON, history, diff cache, the review's git bundle)
  examples/*.design/     the design example's screen files
  examples/media/        images the examples show (media blocks)
docs/examples/           the examples built to HTML, for GitHub readers
.claude-plugin/          Claude Code plugin and marketplace (omp reads it too)
.agents/plugins/         Codex marketplace
plugin.json              Agent Plugins manifest (Codex, omp)
package.json             pi package manifest
```

The examples describe Acme Corp, a fictional company.

## License

bluedoc's own code: MIT (`LICENSE`). The vendored HorizonUI build under `skills/bluedoc/assets/vendor/horizon-ui/` is Apache-2.0 (its `LICENSE` and `NOTICE`), and the Inter and JetBrains Mono fonts it ships are OFL-1.1 (its `THIRD_PARTY_NOTICES.md`). Under `skills/bluedoc/assets/vendor/heroui/`, Tailwind's browser build (`@tailwindcss/browser` 4.3.3) is MIT, and HeroUI's CSS (`@heroui/styles` 3.2.6) declares MIT in its `package.json` while its `LICENSE` file is the Apache-2.0 text; both licence files sit in `licenses/` there, unchanged. The Architects Daughter hand font under `skills/bluedoc/assets/vendor/fonts/` is OFL-1.1 (its licence file sits beside it). The manifests declare `MIT AND Apache-2.0 AND OFL-1.1`, which covers both readings.
