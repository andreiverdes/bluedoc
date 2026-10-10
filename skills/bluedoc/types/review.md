# Review

**When:** whenever review results (peer review, agent review, open PR threads) go into a bluedoc, without being asked. Each finding is a **decision item**: the reader picks an option (Fix in PR, Ticket, Decline, …) next to your starred recommendation, comments where they disagree, and presses **Send answers**. The reply lists each pick (`→ **Ticket** (recommended: Fix in PR)`) and comment; act on them.

**Home card:** `+N / −N` lines in large type, the file and PR count, and one dot per finding coloured by size.
**Required** (an error on a new rev, a warning on older ones): at least one `diff` block, and every item with `choices` has `state` set to `blocker`, `major`, `minor` or `nit`.

## Layout

**Document**
- `subtitle`: what the page holds, then "Pick what to do with each; my recommendation is starred."
- `state`: counts per verdict, e.g. "11 review comments", "6 fix in the PR", "2 follow-up tickets", "2 decline", "1 resolves when a fix lands".
- `links`: each PR, then related docs.
- `tldr`: how many to fix, ticket and decline, and which findings are real bugs the change introduces.

**Section 1, Summary**
- `lead`: "Each finding has its options under it, with my recommendation starred. Pick one per finding, comment where you disagree, then press **Send answers**."
- A `table`: **PR | Finding | Size | Recommendation**, one row per finding, each finding linked to its item: `[text](#item-<checklist>-<item>)`.
- A `note` callout for provenance when it matters (who posted the comments, under which login, at which heads).

**One section per PR** (`id` `pr-<n>`)
- `lead`: how many findings and of what kind, then the range: "Diff: `main` `<base>` → head `<head>`, limited to the commented files."
- A `checklist` (`id` `t<n>`, `numbered: false`), one decision item per finding:
  - `text`: the finding as a fact in one line ("A retry can authorize the card twice"), not an instruction: the options are the instructions.
  - `sub`: `Recommend <option>: <one-line reason>.`
  - `state` / `stateKind`: the size: `blocker` / `risk`, `major` / `warn`, `minor` / `info`, `nit` / `todo`.
  - `choices`: `fix` "Fix in PR", `ticket` "Ticket", `decline` "Decline" by default. Use the real decision when it differs: a finding that resolves once another lands gets `after` "Resolve after <x>" plus a fix option; a design question gets its actual alternatives. 2–6 options, labels ≤ 28 characters.
  - `recommend`: your option's id. Never set `choice`.
  - `detail`, in this order: **Reviewer:** the finding restated faithfully, with the reviewer's evidence. **My reasoning:** why this recommendation, citing `path:line` and what you checked. **Fix:** the concrete change. **Verify:** the observable check. **Reply I'd post:** for declines and tickets.
- A `diff` block right after the checklist, from `gitdiff.py` (below): only the files with findings, a `note` naming the head and scope ("Only the commented files. Head `<head>`."), one comment per finding.

## Rules

1. Every finding gets options, a recommendation and a reason.
2. Recommend from the code, not the review: read the file, run the grep or test before you agree or decline.
3. Mark any assumption you did not verify *unverified* in `detail`, and make its check required in **Verify**.
4. Diff the commits the reviewer read. After a rebase, keep the reviewed range and say so in `note`, or regenerate the block and check every anchor still lands on the code it describes.
5. A thread on a different line than the code that needs the fix: anchor the comment on the code and say so in `note`. A finding with no line becomes a "Whole change" comment (`{"label": "PR description", "item": …}`).
6. Never answer a decision yourself. Set `choice` only to carry over the reader's answer from an earlier round, and say so in `detail` (`**Status:** picked <option> on <date>`).

## Diff blocks from git

The `diff` block is a **reference**: `repo`, `base`, `head`, optional `paths` and the comments. The server runs `git diff` when the page renders and caches the result in `<name>.diffcache.json` next to the doc; commit that file (it keeps the diff after a rebase or a deleted branch) and never read it. Without the repo or commits it falls back to `gh pr diff <pr>`, and refuses a PR whose head moved. Never write hunks by hand.

From GitHub threads:

```sh
python3 <skill>/scripts/ghthreads.py --repo <owner>/<repo> --pr <n> --checklist t<n> \
  --comments-out /tmp/c<n>.json > /tmp/items<n>.json
python3 <skill>/scripts/gitdiff.py --repo <checkout> --base <base> --head <head> --id diff-<n> \
  --title "<repo> #<n>" --pr <owner>/<repo>#<n> --paths <commented files> --comments /tmp/c<n>.json \
  --note "Only the commented files. Head <head>." --into <doc> --section pr-<n> --after-block 0
```

`ghthreads.py` prints the PR's base and head and one item stub per open thread (`--all` adds resolved ones): the default options, the reviewer's text in `detail`, and `<<…>>` for the finding, size, recommendation and reasoning, which the build rejects until filled. Paste the stubs into the `t<n>` checklist. For your own review, write `/tmp/c<n>.json` yourself: a list of `{"at": "path:12-20", "item": "t<n>/<item>"}`. `gitdiff.py` stores `base`/`head` as short SHAs and `repo` relative to the doc, and replaces a block with the same `id`; `--embed` writes the old inline hunks instead.

## Fragment

```json
{ "id": "pr-412", "title": "#412 · bulk discount tiers", "lead": "1 bug this PR introduces, 1 nit. Diff: `main` `89efd8e` → head `62ccc86`, limited to the commented files.",
  "blocks": [
  { "type": "checklist", "id": "t412", "title": "Findings · #412", "numbered": false, "items": [
    { "id": "tier-boundary", "text": "`tierFor` gives no tier at exactly 10 units", "sub": "Recommend Fix in PR: the spec says \"10 or more\".",
      "state": "major", "stateKind": "warn", "recommend": "fix",
      "choices": [ { "id": "fix", "label": "Fix in PR" }, { "id": "ticket", "label": "Ticket" }, { "id": "decline", "label": "Decline" } ],
      "detail": "**Reviewer:** … **My reasoning:** `src/pricing/tiers.ts:17` uses `>`. **Fix:** use `>=`. **Verify:** `tierFor(10)` returns `bulk`." } ] },
  { "type": "diff", "id": "diff-412", "title": "acme-shop #412", "repo": "../acme-shop", "base": "89efd8e", "head": "62ccc86",
    "paths": ["src/pricing/tiers.ts"], "pr": "acme/acme-shop#412", "note": "Only the commented files. Head `62ccc86`.",
    "comments": [ { "at": "src/pricing/tiers.ts:17-21", "item": "t412/tier-boundary" } ] } ] }
```

Field details: grep `## Diff` and `## Checklist` in `references/schema.md`.
