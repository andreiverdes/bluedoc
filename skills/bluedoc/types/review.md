# Review

**When:** whenever review results (peer review, agent review, open PR threads) go into a bluedoc, without being asked. Each finding is a **decision item**: the reader picks an option next to your starred recommendation and presses the send key ([Whose PR](#whose-pr-metareview)); the reply lists each pick (`→ **Ticket** (recommended: Fix in PR)`): act on them. Their comments on findings and **Need more details** go with **Request changes** instead (`kind: changes`, each finding under `## Decisions` with its comment quoted and its `item:` key): answer each with `--reply` (rule 7). A finding sent with **Need more details** gets a fuller `detail` and options in the next rev, still unpicked. The page's Comments panel lists every finding thread; one whose newest message is yours waits for the reader, and one whose `choice` you set (rule 6) reads as resolved.

**Home card:** `+N / −N` lines in large type, the file and PR count, and one dot per finding coloured by size.
**Required** (an error on a new rev, a warning on older ones): at least one `diff` block; every item with `choices` has `state` set to `blocker`, `major`, `minor` or `nit`; a review of a PR (a `diff` block with `pr`) has `meta.review`; a `post` review's findings offer only `post` and `skip`.

## Whose PR: `meta.review`

Who owns the change decides what the reader can do with a finding. Check it before you write anything: `gh pr view <n> --repo <owner>/<repo> --json author --jq .author.login` against `gh api user --jq .login`.

- **Someone else's PR:** the reader can't change their code. Every finding is a comment to **post or not**: never Fix, Ticket or Decline. `post`.
- **The reader's own PR:** the reader can fix it. Your job is the peers' comments: gather the open threads (`ghthreads.py`), check each against the code, and the reader decides **Fix in PR, Ticket or Decline**. `threads`.
- **A review of the reader's own PR, only when they ask for one:** you review the code yourself, and each finding is a comment to post or not. `post`.
- **The reader's change before any PR:** you reviewed their working tree; they fix, ticket or decline. `local`.

PRs of different owners go in separate docs, one `meta.review` each. Scaffold with `build.py new review <doc> --of post|threads|local`: `--of post` writes the Post / Don't post options.

| `meta.review` | Options per finding | Send key | When the reply comes |
|---|---|---|---|
| `post` | `post` **Post**, `skip` **Don't post** | **Post review** | Post ONE GitHub review per PR (`gh api -X POST repos/<owner>/<repo>/pulls/<n>/reviews --input <file>`, `{event, body, comments: [{path, line, side, body}]}`): a comment per finding picked Post, on its line, with its **Comment I'd post** or the reader's comment in its place; nothing for Don't post. Each PR's `event` is its own **Post as** in the reply: Comment `COMMENT`, Request changes `REQUEST_CHANGES`, Approve `APPROVE` (`wait`'s header says `review events pr-412 REQUEST_CHANGES, pr-415 APPROVE`; the Markdown lists `Post as:` per PR). |
| `threads` | `fix` **Fix in PR**, `ticket` **Ticket**, `decline` **Decline** | **Reply and fix** | Fix the findings marked to fix on the PR's branch and push, then reply on each thread with the finding's **Reply I'd post** and resolve the fixed ones (`gh api graphql`, `resolveReviewThread`). |
| `local` | **Fix now**, **Ticket**, **Decline** | **Apply decisions** | Fix the findings marked to fix in the working tree, file a ticket for each one marked Ticket, drop the declines, then report what you did. |

Without `meta.review` (a codebase review by area) the key reads **Send answers**. Each key shows the count of picks and ticks not sent yet; comments on findings count in **Request changes**.

## Layout

**Document**
- `subtitle`: what the page holds, then "Pick what to do with each; my recommendation is starred."
- `state`: counts per verdict, e.g. "11 review comments", "6 fix in the PR", "2 follow-up tickets", "2 decline", "1 resolves when a fix lands"; on a `post` review "9 review comments", "7 to post", "2 not to post".
- `links`: each PR, then related docs.
- `tldr`: how many to fix, ticket and decline (on a `post` review: how many to post), and which findings are real bugs the change introduces.

**Section 1, Summary**
- `lead`: "Each finding has its options under it, with my recommendation starred. Pick one per finding, comment where you disagree, then press **Post review**." Name the page's send key: **Apply decisions**, **Post review**, **Reply and fix**, or **Send answers** without `meta.review`.
- A `table`: **PR | Finding | Size | Recommendation**, one row per finding, each finding linked to its item: `[text](#item-<checklist>-<item>)`.
- A `note` callout for provenance when it matters (who posted the comments, under which login, at which heads).

**One section per PR** (`id` `pr-<n>`)
- `lead`: how many findings and of what kind, then the range: "Diff: `main` `<base>` → head `<head>`, limited to the commented files."
- A `checklist` (`id` `t<n>`, `numbered: false`), one decision item per finding:
  - `text`: the finding as a fact in one line ("A retry can authorize the card twice"), not an instruction: the options are the instructions.
  - `sub`: `Recommend <option>: <one-line reason>.`
  - `state` / `stateKind`: the size: `blocker` / `risk`, `major` / `warn`, `minor` / `info`, `nit` / `todo`.
  - `choices`: by `meta.review` (the table above). On `threads` and `local` reviews, use the real decision when it differs: a finding that resolves once another lands gets `after` "Resolve after <x>" plus a fix option; a design question gets its actual alternatives. A `post` review offers only `post` "Post" and `skip` "Don't post". 2–6 options, labels ≤ 28 characters. Each option's `md` says what it means for this finding and what it costs, 1–3 sentences ("Change `>` to `>=` before #412 merges: one character."); the build fails without it.
  - `recommend`: your option's id. Never set `choice`.
  - `detail`, in this order: **Reviewer:** the finding restated faithfully, with the reviewer's evidence (on a `post` review: **Evidence:**, what you read or ran). **My reasoning:** why this recommendation, citing `path:line` and what you checked. On `threads`: **Fix:** the concrete change, **Verify:** the observable check, **Reply I'd post:** for declines and tickets. On `post`: **Comment I'd post:** the comment as the author will read it, plain and specific.
- A `diff` block right after the checklist, from `gitdiff.py` (below): only the files with findings, a `note` naming the head and scope ("Only the commented files. Head `<head>`."), one comment per finding.

**Your own review, by area** (no PR, or findings grouped by area or concern): scaffold it with `build.py new review <doc> --shape area`, which writes the changes below; fill its `<<…>>` and copy the area section per area. For a codebase review, diff from the last release you reviewed to head.
- One section per area (`id` the area, e.g. `pricing`, or keep `area-1`); its checklist `id` a short form of it (`pri`), titled "Findings · <area>". The `lead` gives the count and the range you read.
- The summary table is **Area | Finding | Size | Recommendation**; `links` the repo or range, no PRs.
- `detail` opens with **Evidence:** (what you read or ran, with `path:line`) in place of **Reviewer:**; no **Reply I'd post**. Option labels name the real target ("Fix now", "Fix in 3.0.1").
- One `diff` block per section, right after its checklist: `paths` only that area's files, `--title "<repo> · <area>"`, no `--pr`. Its comments point at that section's items only.
- A finding with no code line gets a label comment on the area: `{"label": "<area> (no line)", "item": "pri/<item>"}`.

## Rules

1. Every finding gets options, a recommendation and a reason.
2. Recommend from the code, not the review: read the file, run the grep or test before you agree or decline.
3. Mark any assumption you did not verify *unverified* in `detail`, and make its check required in **Verify**.
4. Diff the commits the reviewer read. After a rebase, keep the reviewed range and say so in `note`, or regenerate the block and check every anchor still lands on the code it describes.
5. A thread on a different line than the code that needs the fix: anchor the comment on the code and say so in `note`. A finding with no line becomes a "Whole change" comment (`{"label": "PR description", "item": …}`).
6. Never answer a decision yourself. Set `choice` only to carry over the reader's answer from an earlier round, and say so in `detail` (`**Status:** picked <option> on <date>`).
7. Answer a reader's comment on a finding with `build.py patch <doc> item:t<n>/<item> --reply "…"`, short and direct; rewrite the finding only when the answer changes it or its options.
8. A reader may answer a finding with **Custom** instead of an option: the reply carries `choice: "custom"` and their words in `custom` (Markdown `→ **Custom**: <text>`). Treat it as their decision; if it doesn't say what to do, ask with `--reply`.

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

`ghthreads.py` prints the PR's base and head and one item stub per open thread (`--all` adds resolved ones): the default options, the reviewer's text in `detail`, and `<<…>>` for the finding, size, recommendation and reasoning, which the build rejects until filled. Paste the stubs into the `t<n>` checklist. For your own review, write `/tmp/c<n>.json` yourself: a list of `{"at": "path:12-20", "item": "t<n>/<item>"}`. `gitdiff.py` stores `base`/`head` as short SHAs and `repo` relative to the doc, and replaces a block with the same `id`; with `--pr` it also stores the PR's branch names, `headRef` and `baseRef` (`gh pr view <n> --repo <owner>/<repo> --json headRefName,baseRefName`), which the PR's header shows as `head → base`. `--embed` writes the old inline hunks instead.

## Fragment

```json
{ "id": "pr-412", "title": "#412 · bulk discount tiers", "lead": "1 bug this PR introduces, 1 nit. Diff: `main` `89efd8e` → head `62ccc86`, limited to the commented files.",
  "blocks": [
  { "type": "checklist", "id": "t412", "title": "Findings · #412", "numbered": false, "items": [
    { "id": "tier-boundary", "text": "`tierFor` gives no tier at exactly 10 units", "sub": "Recommend Fix in PR: the spec says \"10 or more\".",
      "state": "major", "stateKind": "warn", "recommend": "fix",
      "choices": [ { "id": "fix", "label": "Fix in PR", "md": "Change `>` to `>=` before #412 merges: one character." },
                   { "id": "ticket", "label": "Ticket", "md": "#412 merges with the bug; 10 units get no discount until the ticket lands." },
                   { "id": "decline", "label": "Decline", "md": "Keep `>`: the code then contradicts the spec's \"10 or more\"." } ],
      "detail": "**Reviewer:** … **My reasoning:** `src/pricing/tiers.ts:17` uses `>`. **Fix:** use `>=`. **Verify:** `tierFor(10)` returns `bulk`." } ] },
  { "type": "diff", "id": "diff-412", "title": "acme-shop #412", "repo": "../acme-shop", "base": "89efd8e", "head": "62ccc86",
    "paths": ["src/pricing/tiers.ts"], "pr": "acme/acme-shop#412", "headRef": "bulk-discount-tiers", "baseRef": "main", "note": "Only the commented files. Head `62ccc86`.",
    "comments": [ { "at": "src/pricing/tiers.ts:17-21", "item": "t412/tier-boundary" } ] } ] }
```

Field cards: `build.py schema diff`, `build.py schema checklist`, `build.py schema item`.
