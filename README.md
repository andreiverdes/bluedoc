# bluedoc

![Zooming into the orders-api system, then into pricing inside it, then into fulfilment-worker, each level playing its own flow](docs/tour.gif)

An agent skill that writes engineering docs as one self-contained HTML page: a zoomable blueprint of the system, checklists that remember your ticks, and a code browser that pins review findings to their lines. Works with Claude Code, Codex, pi and omp.

## What you get

- **Blueprint canvas.** Open a system to see its parts; each level plays its own animated flow (request, event, data). Nests 3 levels deep.
- **Checklists as task trackers.** Every procedure is a checklist. Each item is a two-line row (the action, then why it matters) that opens to show details, commands, checks, tables or a sub-checklist. Ticks persist in the reader's browser; **Copy progress** exports Markdown for a PR or issue.
- **Decisions, not "tick if you agree".** When the agent needs you to choose, an item shows its options as pills with the agent's recommendation starred. You pick one; the export says what you picked and what was recommended.
- **Answers back to the agent.** Every item takes a comment. **Send answers** collects your picks, ticks and comments, plus an overall message, and sends them to the agent (or copies them for you to paste).
- **Change requests on the page.** A tray of keys at the bottom (View, Point, Select, Draw) lets you pin a comment on any element, comment on a selected passage, or draw on the page; each becomes a card in the Comments sidebar on the right, and **Request changes** sends them to the agent as edits to make. Answers and change requests are separate messages.
- **Code review.** A `diff` block shows a change with each finding as a comment on its lines, and its options on the card. A file with several comments says how many, steps between them, and tells you how many sit above or below what you can see. Generated from git by `gitdiff.py`; GitHub review threads come in through `ghthreads.py`.
- **Revisions you can compare.** Each build keeps the doc's revision history. Switch to any earlier revision, or compare two: new, changed and removed sections, items, table rows and drawing parts are marked in place with a word-level diff, next to the author's note on what changed. Readers who come back to a newer revision get a link to what changed since their last visit.
- **A local server, a home page, JSON only.** `serve.py` renders each doc from its JSON on every request, so agents write only the JSON, never the HTML. `http://127.0.0.1:8740/` is a HorizonUI dashboard: a search-first hero, a sidebar of projects with their folder trees, doc types and status, activity and decision charts, and every doc as a card with a generated preview, in a grid (2–6 columns), a list or a board. `build.py -o` still writes a standalone HTML file when you need to send one.
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
- A browser tool in your agent is optional. With one, the agent checks the page at three widths before it reports.

## Use

Ask in plain words. The skill triggers on requests for HTML docs, architecture pages, walkthroughs, runbooks and browsable reviews.

- "Write a bluedoc of how a request flows through this service."
- "Make a runbook for setting up the local stack, as a bluedoc with checklists."
- "Review PR 412 and give me a bluedoc where each finding sits on its code."
- "Put the open review threads on PR 412 in a bluedoc so I can decide what to do with each."

The agent writes `docs/<topic>/<name>.bluedoc.json` (the only file it writes), validates it, and opens it on the local server:

```sh
python3 <skill>/scripts/build.py docs/<topic>/<name>.bluedoc.json        # validate, record the revision
python3 <skill>/scripts/serve.py open docs/<topic>/<name>.bluedoc.json   # start the server, print the URL
```

Every doc the server knows is listed at `http://127.0.0.1:8740/`. Edit the JSON and reload; there is no build output to keep in sync. For a file you can send to someone, add `-o <name>.html` to the build command.

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
  SKILL.md               instructions the agent follows
  references/schema.md   every JSON field
  scripts/build.py       validate, lint, build the HTML
  scripts/gitdiff.py     git range + findings -> diff block
  scripts/ghthreads.py   GitHub review threads -> findings + diff comments
  scripts/serve.py       local server: renders docs, home page, answers and change requests
  assets/template.html   the page runtime (styling, canvas, checklists, diff browser, annotator)
  assets/home.html       the home page (HorizonUI)
  assets/vendor/         HorizonUI browser build (Apache-2.0, see its NOTICE)
  examples/              Acme examples (JSON and history; built HTML for GitHub readers)
.claude-plugin/          Claude Code plugin and marketplace (omp reads it too)
.agents/plugins/         Codex marketplace
plugin.json              Agent Plugins manifest (Codex, omp)
package.json             pi package manifest
```

The examples describe Acme Corp, a fictional company.

## License

MIT
