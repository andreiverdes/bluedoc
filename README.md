# bluedoc

![Zooming into the orders-api system, then into pricing inside it, then into fulfilment-worker, each level playing its own flow](docs/tour.gif)

An agent skill that writes engineering docs as one self-contained HTML page: a zoomable blueprint of the system, checklists that remember your ticks, and a code browser that pins review findings to their lines. Works with Claude Code, Codex, pi and omp.

## What you get

- **Blueprint canvas.** Open a system to see its parts; each level plays its own animated flow (request, event, data). Nests 3 levels deep.
- **Checklists as task trackers.** Every procedure is a checklist. Each item is a two-line row (the action, then why it matters) that opens to show details, commands, checks, tables or a sub-checklist. Ticks persist in the reader's browser; **Copy progress** exports Markdown for a PR or issue.
- **Decisions, not "tick if you agree".** When the agent needs you to choose, an item shows its options as pills with the agent's recommendation starred. You pick one, or press **Accept recommended** (for the whole doc in the bottom toolbar, or per checklist) to take every starred option at once; the export says what you picked and what was recommended.
- **Answers back to the agent.** Every item takes a comment. **Send answers**, the last key in the bottom tray, collects your picks, ticks and comments, plus an overall message, and sends them to the agent (or copies them for you to paste). It turns green once there is something to send.
- **Change requests on the page.** A tray of keys at the bottom (View, Point, Select, Draw) lets you pin a comment on any element, comment on a selected passage, or draw on the page; you write the note right next to the mark, and saved notes become cards in the Comments sidebar on the right (Pending, Open once sent, Resolved); a General comment field takes notes about the whole doc. **Request changes** sends the pending ones to the agent as edits to make. Answers and change requests are separate messages.
- **Plans you approve on the page.** Instead of a Markdown plan, the agent writes a plan page: the goal, the proposed design on a canvas, before/after panes, mockups, a numbered timeline of steps, the files each step touches, open questions with its recommendation starred, risks and checks. Comment on any part, then **Request changes** or **Approve plan**; your picks and notes go with it, and the agent waits for your approval before it writes code.
- **Code review.** A `diff` block shows a change with each finding as a comment on its lines, and its options on the card. A file with several comments says how many, steps between them, and tells you how many sit above or below what you can see. The doc stores only the git range (`gitdiff.py` writes it); the server expands it from git on each render and caches the result next to the doc, falling back to `gh pr diff`. GitHub review threads come in through `ghthreads.py`.
- **Revisions you can compare.** Each build keeps the doc's revision history. From the Revisions rail beside the content, switch to any earlier revision or compare two: new, changed and removed sections, items, table rows and drawing parts are marked in place with a word-level diff, next to the author's note on what changed. Readers who come back to a newer revision get a link to what changed since their last visit.
- **A local server, a home page, JSON only.** `serve.py` renders each doc from its JSON on every request, so agents write only the JSON, never the HTML. `http://127.0.0.1:8740/` is a HorizonUI dashboard: a search-first hero, a sidebar of projects with their folder trees, doc types and status, activity and decision charts, and every doc as a card whose hero is shared by its type and shows the type's own element (a review's +/− lines, a plan's step timeline, a doc's drawing), in a grid (2–6 columns), a list or a board. `build.py -o` still writes a standalone HTML file when you need to send one.
- **Self-contained pages.** No network at view time beyond the local server, prints cleanly, light and dark theme, keyboard and screen-reader outline.
- **Adjustable width.** Drag the handle on either side of the text to widen or narrow it; it stays centred and every bluedoc page in that browser remembers the width. Wide tables stop wrapping. Double-click a handle to reset.
- **Linted writing.** The build flags filler, vague words, long sentences and checklist items that don't start with a verb.

| The page | A review finding on its code |
|---|---|
| ![A bluedoc page: header, status rail, contents and the blueprint canvas](docs/header.png) | ![A diff block with a blocker comment under line 17](docs/review.png) |

Open the examples in a browser to try them: [`acme-orders.html`](skills/bluedoc/examples/acme-orders.html) (architecture and runbook) and [`acme-review-findings.html`](skills/bluedoc/examples/acme-review-findings.html) (review findings for two PRs). Download the file, then open it; GitHub shows HTML as source.

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

Ask in plain words. The skill triggers on requests for HTML docs, architecture pages, walkthroughs, runbooks, plans and browsable reviews.

- "Write a bluedoc of how a request flows through this service."
- "Make a runbook for setting up the local stack, as a bluedoc with checklists."
- "Review PR 412 and give me a bluedoc where each finding sits on its code."
- "Put the open review threads on PR 412 in a bluedoc so I can decide what to do with each."
- "Plan saved carts as a bluedoc and wait for my approval."

The agent scaffolds `docs/<topic>/<name>.bluedoc.json` from the type's skeleton (the only file it writes, plus any images the doc shows), fills it in, validates it and opens it on the local server:

```sh
python3 <skill>/scripts/build.py new plan docs/plans/saved-carts.bluedoc.json --title "Saved carts"   # skeleton with <<…>> to fill
python3 <skill>/scripts/build.py docs/plans/saved-carts.bluedoc.json        # validate, record the revision
python3 <skill>/scripts/serve.py open docs/plans/saved-carts.bluedoc.json   # start the server, print the URL
```

When you send comments back, the agent revises one object at a time, and the revision bumps itself:

```sh
python3 <skill>/scripts/build.py patch docs/plans/saved-carts.bluedoc.json item:decisions/retention \
  --set recommend=d90 --change "Retention: recommend 90 days, as asked."
```

Every doc the server knows is listed at `http://127.0.0.1:8740/`. Edit the JSON and reload; there is no build output to keep in sync. For a file you can send to someone, add `-o <name>.html` to the build command.

Per doc, the agent reads about 1.5k tokens of instructions (`SKILL.md`) plus one type guide (`types/<type>.md`), and greps the schema only for the fields it needs.

`<skill>` is the installed skill folder, for example `~/.agents/skills/bluedoc`.

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
  types/<type>.md        one guide per doc type: plan, review, docs, other
  references/schema.md   every JSON field and command, for lookup
  assets/skeletons/      fill-in skeleton per doc type (build.py new)
  scripts/build.py       new, validate, lint, patch, build the HTML
  scripts/gitdiff.py     git range + findings -> diff block (a git reference)
  scripts/diffref.py     expands diff references from the cache, git or gh
  scripts/migrate.py     one-off: embedded diffs -> references, reports contract gaps
  scripts/ghthreads.py   GitHub review threads -> findings + diff comments
  scripts/serve.py       local server: renders docs, home page, answers and change requests
  assets/template.html   the page runtime (styling, canvas, checklists, diff browser, annotator)
  assets/home.html       the home page (HorizonUI)
  assets/vendor/         HorizonUI browser build (Apache-2.0, see its NOTICE)
  examples/              Acme examples (JSON and history; built HTML for GitHub readers)
  examples/media/        images the examples show (media blocks)
.claude-plugin/          Claude Code plugin and marketplace (omp reads it too)
.agents/plugins/         Codex marketplace
plugin.json              Agent Plugins manifest (Codex, omp)
package.json             pi package manifest
```

The examples describe Acme Corp, a fictional company.

## License

MIT
