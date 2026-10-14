# bluedoc

Agent skill. The agent writes a doc as JSON (`*.bluedoc.json`); a local server renders it as a page the user comments on, decides on and approves. Types: docs, plan, review, design, presentation, website, other.

Beta: the doc format and commands may change between betas. Tested on macOS.

Entry point for agents: `skills/bluedoc/SKILL.md`.

## Install

| Agent | Command |
|---|---|
| Claude Code | `claude plugin marketplace add andreiverdes/bluedoc && claude plugin install bluedoc@bluedoc` |
| Codex | `codex plugin marketplace add andreiverdes/bluedoc && codex plugin add bluedoc@bluedoc` |
| pi | `pi install git:github.com/andreiverdes/bluedoc` |
| omp | `omp plugin marketplace add andreiverdes/bluedoc && omp plugin install bluedoc@bluedoc` |
| Other | `npx skills add andreiverdes/bluedoc` |

Restart the agent after installing.

## Requirements

- Python 3.9+ as `python3`. Standard library only.
- A browser. The server listens on 127.0.0.1, port 8740 or the next free one up to 8759; `BLUEDOC_PORT` pins one.
- `git`: code reviews. `gh`, signed in: GitHub review threads. Chrome: `serve.py snapshot`.

## Layout

```text
skills/bluedoc/SKILL.md      workflow; read first
skills/bluedoc/types/        one guide per doc type
skills/bluedoc/references/   schema.md (grep, don't read whole), kits.md
skills/bluedoc/scripts/      build.py, serve.py, gitdiff.py, diffref.py, ghthreads.py, migrate.py, statedb.py
skills/bluedoc/assets/       page runtime, home page, kits, skeletons, vendored UI and fonts
```

## Source, issues, licence

This repo holds releases only. Source, docs and issues: https://github.com/andreiverdes/bluedoc-src

MIT (`LICENSE`). Vendored: HorizonUI (Apache-2.0), HeroUI CSS and Tailwind browser build (MIT), fonts (OFL-1.1); licence files sit beside each under `skills/bluedoc/assets/vendor/`.
