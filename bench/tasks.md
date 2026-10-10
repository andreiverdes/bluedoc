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
