# Token benchmark

Three tasks an agent does with bluedoc. The cost counted is what the skill makes the agent read or produce, at about 4 bytes per token, plus 1.5k tokens per screenshot. Content the agent must read anyway (the code under review, the plan's source files) is not counted.

| Task | What the skill makes the agent read or produce |
|---|---|
| New plan | the skill's instructions, a structure to copy, the doc it writes, the checks it runs |
| New review of one PR | the same, plus the diff block in the JSON |
| One-finding revision of a large review | the instructions it re-reads, the doc it re-reads to edit, the checks |

## Baseline: bluedoc 2.6.0

| Task | Instructions | Structure | Doc read back | Checks | Total |
|---|---|---|---|---|---|
| New plan | SKILL.md 23 KB + schema.md 35 KB = ~14.6k | plan example 21 KB = ~5.3k | — | 6 screenshots = ~9k | **~29k** |
| New review | ~14.6k | review example 28 KB = ~7.1k | its diff blocks: 5.6 KB (example) to 125 KB (real review) = ~1.4–31k | ~9k | **~32–62k** |
| One-finding revision | SKILL.md = ~5.8k | — | a real review: 81 KB = ~20k; the largest: 564 KB = ~141k | ~9k | **~35–156k** |

Sizes measured on 2026-10-10: the skill files in this repo, and 15 real docs in a work repo. Embedded diffs in four real reviews total 46–317 KB each.

## After the token diet: bluedoc 3.0.0

Measured with a fresh agent that followed only SKILL.md (task 1 and 2), and with the migration report for the real reviews.

| Task | Instructions | Structure | Doc read back | Checks | Total | Before |
|---|---|---|---|---|---|---|
| New plan | SKILL.md 5.9 KB + `types/plan.md` 4.4 KB = ~2.6k; optional greps the agent chose: ~1.3k | the scaffold it fills, 6.7 KB = ~1.7k | — | `build.py` output, ~0.1k | **~4.3k (5.6k with the optional greps)** | ~29k |
| New review | SKILL.md + `types/review.md` 6.6 KB = ~3.1k | review scaffold ~1.7k | diff refs: ~0.5 KB per PR, ~0.1k | ~0.1k | **~5k** | ~32–62k |
| One-finding revision | SKILL.md = ~1.5k | — | none: `build.py patch <doc> <key>` | patch output, ~0.1k | **~1.6k** | ~35–156k |

The four real reviews that embedded diffs went from 82–564 KB to 24–116 KB each (1.44 MB → 0.71 MB for the whole folder); 18 of 18 diff blocks converted, each verified to reproduce the embedded hunks.

## Design docs: bluedoc 3.6.0

Three more tasks: a new design (a sign-in screen for phone and web), revising one screen after a change request on one element, and a 3-slide deck (the presentation target). Here the agent also writes HTML: the screen files it produces count, as the scaffold does.

Measured on 2026-10-10 with a fresh agent per task: Claude Code 2.1.296 (claude-opus-5-5) in print mode, `claude -p "<task>" --safe-mode --output-format stream-json`, in an empty temp folder, told to read a read-only copy of SKILL.md by absolute path and not to run `serve.py`. Task 2 is a new session on task 1's output; its prompt is the change request on `el:mobile/submit` (the phone screen's submit button) as `serve.py wait` prints it. Tokens are the API's usage report. Billed is input + cache writes + output; with cache reads adds the cached input each request re-reads. Claude Code's own prefix is ~15.6k tokens per request (a one-word prompt: 4.1k billed, 15.6k with cache reads). Added context is the last request's input minus that prefix: what the task put in front of the agent, before its closing answer. Turns are the API's `num_turns`.

| Task | Read | Wrote | Build | Turns | Billed | With cache reads | Added context |
|---|---|---|---|---|---|---|---|
| New design: sign-in, phone + web | SKILL.md 7.0 KB, `types/design.md` 7.6 KB, `build.py --help`, the skill's file list, the scaffold (JSON + 2 stubs), `references/kits.md` lines 1–30: 30 KB of tool output | 2 screens 3.6 KB, the doc 5.6 KB | 0 errors, 1 warning: HeroUI not installed, the guide's default for phone and web; the agent named it and put `serve.py add-framework heroui` in the pick's detail | 8 | **25.6k** (21.4k in, 4.2k out) | 210k | **~16.2k** |
| Revise one screen | SKILL.md, the skill's file list, a `grep` of `types/design.md` 3.2 KB, `build.py patch -h`, patch's file and selector, `mobile.html` 1.8 KB, `references/kits.md` lines 55–80: 15.5 KB | the edit to `mobile.html` 1.0 KB, then `build.py patch … el:mobile/submit --change …` (rev 1 → 2) | 0 errors, the same 1 warning | 9 | **13.7k** (12.1k in, 1.6k out) | 193k | **~8.0k** |
| New deck, 3 slides | SKILL.md, `types/design.md`, `build.py --help`, the skill's file list, the presentation scaffold (JSON + 3 stubs): 27 KB | 3 slides 1.6 KB, the doc with speaker notes 4.7 KB | 0 errors, 0 warnings | 6 | **20.5k** (17.6k in, 3.0k out) | 145k | **~13.5k** |

The walk-through these replace estimated ~7.6k for a new design (4 screens) and ~2.2k for the revision, at 4 bytes per token. The fresh agent's added context is 2.1× and 3.6× that. In every task it listed the skill folder and ran `build.py --help` or `patch -h`, which the steps don't prescribe, and this JSON, HTML and tool output runs ~2.4 bytes per token (39.5 KB of transcript for 16.2k tokens in task 1), not 4.

Screens are body fragments in kit classes, so the agent never writes a `<head>`, framework links or tokens; the largest screen in the Acme Fit example, its hi-fi HorizonUI dashboard, is 3.4 KB, under the 24 KB lint warning. A revision reads and edits one screen file, not the doc: `el:` keys name the file and the `data-bd` selector.
