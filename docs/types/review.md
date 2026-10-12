# Review

Code review findings, each pinned to its lines in the diff, with options to pick from and the agent's recommendation starred.

![The acme-review-findings page: section #412 in its Diff view (the Checklist and Diff toggle in its title bar), tiers.ts open, with the findings on lines 10–13 and 17 as cards carrying their options](../media/review-hero.webp)

## Features

- **Findings pinned to diff lines.** A `diff` block shows the change file by file; each finding is a card under the lines it is about, with its size (blocker, major, minor, nit). A file with several findings counts them and steps between them; a pill says how many sit above or below the view.
- **Checklist or Diff.** A **[Checklist][Diff]** toggle in each PR's section bar shows the findings as a checklist or as the diff, one at a time; the browser remembers the pick, and a link to a finding or to a line opens the view it needs. Print shows both.
- **The code under each finding.** Expanding a finding in the checklist shows its file, the lines around the comment and the comment card with the same options, plus **Open in Diff view**. Comments pinned on those lines are the diff's own.
- **Diffs come from git.** The doc stores only the repo and the commit range. The server runs `git diff` on each render and caches the result next to the doc, falling back to `gh pr diff`. Agents never write hunks by hand.
- **GitHub threads.** `ghthreads.py` turns a PR's open review threads into findings and diff comments.
- **One decision per finding.** Each finding offers options (Fix in PR, Ticket, Decline, or the real alternatives) with the recommendation starred and a reason. The same pills show on the card and in the checklist, kept in sync.
- **Accept recommended.** One key in the bottom tray (or per checklist) picks every starred option at once.
- **Need more details.** A toggle on each finding asks the agent for fuller evidence and options in the next revision.
- **Send answers.** Sends your picks, item comments and an overall message to the agent. The export shows each pick next to the recommendation when they differ.
- **Comments and revisions.** The **Comments** tab collects notes pinned to any element; **Request changes** sends them. A comment the agent lists in a revision's `resolves` turns Resolved. The **Revisions** tab compares two rounds of the review, including changed ranges, files and comments.

## How an agent makes one

```sh
python3 <skill>/scripts/build.py new review docs/reviews/pr-412.bluedoc.json --title "Review: #412"
python3 <skill>/scripts/gitdiff.py --repo . --base <base> --head <head> --id diff-412 --title "acme-shop #412" \
  --paths <files> --comments /tmp/c412.json --into docs/reviews/pr-412.bluedoc.json --section pr-412 --after-block 0
python3 <skill>/scripts/build.py docs/reviews/pr-412.bluedoc.json        # validate, record the revision
python3 <skill>/scripts/serve.py open docs/reviews/pr-412.bluedoc.json   # print the URL
```

`--shape area` scaffolds a review grouped by area instead of by PR.

## Example and guide

- Example: [`acme-review-findings.bluedoc.json`](../../skills/bluedoc/examples/acme-review-findings.bluedoc.json), 11 findings on two acme-shop PRs over two revisions. Its git history ships as [`acme-shop.bundle`](../../skills/bluedoc/examples/acme-shop.bundle). Built page: [`acme-review-findings.html`](../examples/acme-review-findings.html) (download it, then open it).
- Agent guide: [`skills/bluedoc/types/review.md`](../../skills/bluedoc/types/review.md).
