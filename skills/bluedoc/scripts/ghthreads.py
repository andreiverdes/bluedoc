#!/usr/bin/env python3
"""Turn a GitHub PR's review threads into bluedoc review-findings inputs.

Usage:
  ghthreads.py --repo OWNER/NAME --pr N --checklist ID [--comments-out FILE] [--all] > items.json

Prints one JSON object:
  {"pr": N, "url": ..., "base": <sha>, "head": <sha>, "checklist": ID, "items": [item stub, ...]}
Each open thread becomes one decision item stub, id "c<first comment's databaseId>" (stable across
runs), with the standard options Fix in PR / Ticket / Decline. The stub carries the reviewer's text in
`detail` and `<<...>>` placeholders for the finding, size, recommendation, reasoning, fix and check;
build.py fails while any placeholder is left.

--comments-out writes the matching comment list for gitdiff.py --comments: one
{"file", "line", "end"?, "side"?, "item"} per thread. Outdated threads use the line they were written
on; re-anchor them on the code that needs the fix. Resolved threads are skipped unless --all.

Needs `gh` signed in with read access to the repository. Python 3.9+ standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

QUERY = """
query($owner: String!, $name: String!, $pr: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $pr) {
      url baseRefOid headRefOid
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved isOutdated path line startLine originalLine originalStartLine diffSide
          comments(first: 50) { nodes { databaseId author { login } body url } }
        }
      }
    }
  }
}"""


def gh_graphql(owner: str, name: str, pr: int, after: str | None) -> dict:
    args = ["gh", "api", "graphql", "-f", f"query={QUERY}", "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"pr={pr}"]
    if after:
        args += ["-F", f"after={after}"]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"gh api graphql failed: {r.stderr.strip()}")
    data = json.loads(r.stdout)
    pr_node = (data.get("data") or {}).get("repository", {}).get("pullRequest")
    if not pr_node:
        raise SystemExit(f"no pull request {owner}/{name}#{pr}: {json.dumps(data.get('errors'))}")
    return pr_node


def first_line(body: str, limit: int = 60) -> str:
    plain = (re.sub(r"[*_`]{1,3}", "", l).strip(" #>-") for l in body.splitlines())
    line = next((l for l in plain if l), "finding")
    return line if len(line) <= limit else line[: limit - 1] + "…"


def quote(body: str) -> str:
    return body.strip().replace("\r\n", "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="OWNER/NAME")
    ap.add_argument("--pr", required=True, type=int)
    ap.add_argument("--checklist", required=True, help="checklist id the items will live in, e.g. t412")
    ap.add_argument("--comments-out", help="write the gitdiff.py comment list here")
    ap.add_argument("--all", action="store_true", help="include resolved threads")
    a = ap.parse_args()
    owner, _, name = a.repo.partition("/")
    if not name:
        ap.error("--repo must be OWNER/NAME")

    threads, after, pr_node = [], None, None
    while True:
        pr_node = gh_graphql(owner, name, a.pr, after)
        page = pr_node["reviewThreads"]
        threads += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    items, comments, skipped = [], [], 0
    for t in threads:
        if t["isResolved"] and not a.all:
            skipped += 1
            continue
        posts = [c for c in t["comments"]["nodes"] if c.get("body")]
        if not posts:
            continue
        head = posts[0]
        iid = f"c{head['databaseId']}"
        outdated = t["isOutdated"] or t["line"] is None
        line = t["originalLine"] if outdated else t["line"]
        start = (t["originalStartLine"] if outdated else t["startLine"]) or line
        where = f"`{t['path']}:{start}{'-' + str(line) if line and start != line else ''}`" if line else f"`{t['path']}`"
        who = (head.get("author") or {}).get("login", "unknown")
        replies = "".join(f"\n\n**Reply** (@{(c.get('author') or {}).get('login', 'unknown')}): {quote(c['body'])}" for c in posts[1:])
        note = " Outdated: this line is from the commit the comment was written on; re-anchor it on the code to fix." if outdated else ""
        items.append({
            "id": iid,
            "text": f"<<the finding in one line: {first_line(head['body'])}>>",
            "sub": "Recommend <<option>>: <<one-line reason>>.",
            "state": "<<blocker | major | minor | nit>>",
            "choices": [{"id": "fix", "label": "Fix in PR"}, {"id": "ticket", "label": "Ticket"}, {"id": "decline", "label": "Decline"}],
            "recommend": "<<fix | ticket | decline>>",
            "detail": (f"**Reviewer** ([@{who}]({head['url']}), {where}):{note} {quote(head['body'])}{replies}\n\n"
                       "**My reasoning:** <<what you checked, with path:line>>\n\n"
                       "**Fix:** <<the change; for a decline, delete this and write Reply I'd post>>\n\n"
                       "**Verify:** <<the observable check>>"),
        })
        c = {"file": t["path"], "item": f"{a.checklist}/{iid}"}
        if line:
            c["line"] = start
            if line != start:
                c["end"] = line
        if t.get("diffSide") == "LEFT":
            c["side"] = "old"
        comments.append(c)

    out = {"pr": a.pr, "url": pr_node["url"], "base": pr_node["baseRefOid"], "head": pr_node["headRefOid"],
           "checklist": a.checklist, "items": items}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")
    if a.comments_out:
        Path(a.comments_out).write_text(json.dumps(comments, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(items)} open thread(s), {skipped} resolved skipped; base {pr_node['baseRefOid'][:9]} head {pr_node['headRefOid'][:9]}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
