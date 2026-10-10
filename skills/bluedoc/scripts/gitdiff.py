#!/usr/bin/env python3
"""Turn a git range plus line comments into a bluedoc `diff` block.

Usage:
  gitdiff.py --repo PATH --base REV --head REV --id ID --title TITLE [options] > block.json
  gitdiff.py ... --into doc.bluedoc.json --section SECTION_ID [--after-block N]

By default the block is a reference: repo, base and head (resolved to short hashes), the --paths, --pr and the
comments; the page expands it from git when it renders (see diffref.py). With --into, --repo is stored relative
to the doc's folder and the expanded diff goes to <name>.diffcache.json next to it (commit that file, so the diff
survives a rebase or a deleted branch). --embed writes the hunks into the block instead.

Comments (--comments FILE) are a JSON list. Each entry anchors one comment:
  {"at": "path/to/file.sh:340-345", "item": "checklist-id/item-id"}
  {"file": "path/to/file.sh", "line": 340, "end": 345, "side": "new", "title": "...", "md": "..."}
  {"label": "PR description", "item": "checklist-id/item-id"}         (PR-level, no file)
`at` accepts `path`, `path:12`, `path:12-20`, `path:~12-20` and `path:12-20,31` (the first range wins).
A comment whose line is outside the diff gets a context excerpt of the file at --head, so it always has
code to sit on. A comment whose file is not in the tree at --head becomes a PR-level comment.

--into replaces the block with the same id in that section (or inserts it) and rewrites the document
with the indent (1, 2 or 4 spaces) and final newline it already had. Python 3.9+ standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diffref  # noqa: E402


def git(repo: str, *args: str) -> str:
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def dump_like(raw_doc: str, doc: dict) -> str:
    """`doc` serialised with the indent (1, 2 or 4 spaces) and final newline of `raw_doc`."""
    indent = next((n for n in (1, 2, 4) if raw_doc.startswith("{\n" + " " * n + '"')
                   and not raw_doc.startswith("{\n" + " " * (n + 1))), 2)
    return json.dumps(doc, ensure_ascii=False, indent=indent) + ("\n" if raw_doc.endswith("\n") else "")


def build_ref(a: argparse.Namespace) -> dict:
    """The reference block; `repo` relative to the --into doc's folder when there is one."""
    repo = a.repo
    if a.into:
        repo = os.path.relpath(Path(a.repo).resolve(), Path(a.into).resolve().parent)
    block = {"type": "diff", "id": a.id, "title": a.title, "repo": repo,
             "base": git(a.repo, "rev-parse", "--short", a.base).strip(),
             "head": git(a.repo, "rev-parse", "--short", a.head).strip()}
    for key, value, default in (("paths", a.paths, None), ("pr", a.pr, None), ("url", a.url, None),
                                ("note", a.note, None), ("exclude", a.exclude, None),
                                ("context", a.context, diffref.CONTEXT), ("excerpt", a.excerpt, diffref.EXCERPT),
                                ("max_lines", a.max_lines, diffref.MAX_LINES)):
        if value and value != default:
            block[key] = value
    raw = json.loads(Path(a.comments).read_text(encoding="utf-8")) if a.comments else []
    if raw:
        block["comments"] = [diffref.compact_comment(diffref.parse_comment(c, a.strip_prefix or [])) for c in raw]
    return block


def embed(ref: dict, a: argparse.Namespace) -> dict:
    """The old self-contained block: the expanded files and comments, no reference fields."""
    full = dict(ref, repo=a.repo)
    block = {"type": "diff", "id": ref["id"], "title": ref["title"], "repo": a.repo_name or Path(a.repo).resolve().name,
             "base": ref["base"], "head": ref["head"]}
    fail(diffref.expand_doc(full, None, use_cache=False, write_cache=False, allow_remote=False))
    for k in ("url", "note"):
        if k in ref:
            block[k] = ref[k]
    block["files"] = full["files"]
    if full.get("comments"):
        block["comments"] = full["comments"]
    return block


def fail(problems: list[str]) -> None:
    for p in problems:
        print(p, file=sys.stderr)
    if any(p.startswith("ERROR") for p in problems):
        raise SystemExit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--pr", help="owner/repo#N or the PR URL: lets the page fall back to `gh pr diff` without the repo")
    ap.add_argument("--embed", action="store_true", help="write the hunks into the block instead of a reference")
    ap.add_argument("--repo-name", help="with --embed: name shown in the header (default: the folder name)")
    ap.add_argument("--url")
    ap.add_argument("--note", help="inline md under the header, e.g. which snapshot was reviewed")
    ap.add_argument("--comments", help="JSON list of comments (see above)")
    ap.add_argument("--strip-prefix", action="append", help="drop this prefix from comment paths (repeatable)")
    ap.add_argument("--paths", nargs="*", help="limit the diff to these pathspecs")
    ap.add_argument("--exclude", action="append", help="glob of files to leave out (repeatable)")
    ap.add_argument("--context", type=int, default=diffref.CONTEXT, help="context lines per hunk (default 3)")
    ap.add_argument("--excerpt", type=int, default=diffref.EXCERPT, help="lines around a comment outside the diff (default 5)")
    ap.add_argument("--max-lines", type=int, default=diffref.MAX_LINES,
                    help="drop the hunks of an uncommented file with more changed lines (default 800)")
    ap.add_argument("--into", help="insert or replace the block in this document")
    ap.add_argument("--section", help="section id for --into")
    ap.add_argument("--after-block", type=int, help="block index to insert after (default: end of section)")
    a = ap.parse_args()
    if a.into and not a.section:
        ap.error("--into needs --section")
    if a.into:   # before expanding: a bad --section must leave the cache as it is
        path = Path(a.into)
        raw_doc = path.read_text(encoding="utf-8")
        doc = json.loads(raw_doc)
        sec = next((s for s in doc.get("sections", []) if s.get("id") == a.section), None)
        if sec is None:
            raise SystemExit(f"no section '{a.section}' in {path}")
    ref = build_ref(a)
    if a.embed:
        block = embed(ref, a)
        expanded = block
    elif a.into:
        expanded = dict(ref)
        fail(diffref.expand_doc(expanded, Path(a.into), use_cache=False, allow_remote=False))
        block = ref
    else:
        expanded, problems = diffref.expanded_copy(ref, None, use_cache=False, write_cache=False, allow_remote=False)
        fail(problems)
        block = ref
    if not a.into:
        json.dump(block, sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
        return 0
    blocks = sec.setdefault("blocks", [])
    idx = next((i for i, b in enumerate(blocks) if b.get("type") == "diff" and b.get("id") == a.id), None)
    if idx is not None:
        blocks[idx] = block
    elif a.after_block is not None:
        blocks.insert(a.after_block + 1, block)
    else:
        blocks.append(block)
    path.write_text(dump_like(raw_doc, doc), encoding="utf-8")
    n = sum(len(h["lines"]) for f in expanded["files"] for h in f["hunks"])
    print(f"{'replaced' if idx is not None else 'inserted'} diff '{a.id}' in section '{a.section}': "
          f"{len(expanded['files'])} files, {n} lines, {len(expanded.get('comments', []))} comments"
          + ("" if a.embed else f"; diff cached in {diffref.cache_path(path).name}"), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
