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

Two more tasks: a new design with 4 screens (the Acme Fit example: a watch face, a phone sign-in, its variant and a web dashboard), and revising one screen after a change request on one element. Here the agent also writes HTML: the screen files it produces count, as the scaffold does.

Measured on 2026-10-10 by walking the steps SKILL.md and `types/design.md` prescribe, on a temp copy: `build.py new design … --target mobile,web`, one `grep -A30` of a `references/kits.md` section, the example's files as the written result, then a change request on `el:login/submit` (the reply as `serve.py wait` prints it), `build.py patch <doc> el:login/submit`, an in-place edit of `login.html` and `build.py patch <doc> artboard:login --change …`. Not yet re-run with a fresh agent.

| Task | Instructions | Structure | Written | Checks | Total | Plan estimate |
|---|---|---|---|---|---|---|
| New design, 4 screens | SKILL.md 6.9 KB + `types/design.md` 7.2 KB = ~3.5k; one kit section, 1.6–2.0 KB = ~0.5k | the scaffold it fills: JSON 3.7 KB + 2 stub screens 0.9 KB = ~1.1k | the doc 4.0 KB + 4 screens 5.4 KB (0.5–3.4 KB each) = ~2.4k | `build.py` output, ~0.1k | **~7.6k** (~8k with a second kit section) | ~9–13k |
| Revise one screen | SKILL.md = ~1.7k (~3.5k if it re-reads `types/design.md`) | — | the reply 0.2 KB, patch's file and selector 0.2 KB, `login.html` 0.8 KB, the edit 0.3 KB = ~0.4k | patch output, ~0.1k | **~2.2k** (~4k with the guide) | ~2–4k |

Screens are body fragments in kit classes, so the agent never writes a `<head>`, framework links or tokens; the hi-fi HorizonUI dashboard is the largest at 3.4 KB, under the 24 KB lint warning. A revision reads and edits one screen file, not the doc: `el:` keys name the file and the `data-bd` selector.
