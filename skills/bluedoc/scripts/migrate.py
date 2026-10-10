#!/usr/bin/env python3
"""One-off: convert embedded `diff` blocks to git references and report docs missing their type's data.

Usage:
  migrate.py <docs-folder> [--dry-run] [--repo-root DIR ...]

For every *.bluedoc.json / *.blueprint.json under the folder, each diff block with `files`, `base` and `head`
is converted to a reference (see diffref.py) when its repo is found with both commits: the block's `repo`
relative to the doc, then a folder named after it under each --repo-root, then under the doc's ancestors.
The reference is expanded from that repo and kept only when the expansion shows the same files and line
numbers as the embedded hunks; the expansion goes to <name>.diffcache.json. Otherwise the block stays
embedded and the reason is printed. `repo` is stored relative to the doc when the repo sits beside one of
the doc's ancestors, else as written. `meta.rev` is not bumped; files keep their indent.
Python 3.9+ standard library only.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diffref  # noqa: E402
from gitdiff import dump_like  # noqa: E402


def embedded_blocks(node):
    if isinstance(node, dict):
        if node.get("type") == "diff" and "files" in node:
            yield node
            return
        for v in node.values():
            yield from embedded_blocks(v)
    elif isinstance(node, list):
        for v in node:
            yield from embedded_blocks(v)


def find_repo(block: dict, doc_dir: Path, roots: list[Path]) -> Path | None:
    written = str(block.get("repo") or "")
    if not written:
        return None
    name = Path(written).name
    cands = [diffref.resolve_repo(block, doc_dir)]
    for d in [*roots, doc_dir, *doc_dir.parents]:
        cands += [d / name] + ([d] if d.name == name else [])
    seen: set[Path] = set()
    for c in cands:
        c = c.resolve()
        if c in seen:
            continue
        seen.add(c)
        if diffref.has_commits(c, block["base"], block["head"]):
            return c
    return None


def stored_repo(block: dict, found: Path, doc_dir: Path) -> str:
    """Relative to the doc when the repo is an ancestor of it or beside one; else the name as written."""
    if diffref.resolve_repo(block, doc_dir).resolve() == found:
        return block["repo"]
    if any(found in (a, a / found.name) for a in [doc_dir, *doc_dir.parents][:-1]):
        return os.path.relpath(found, doc_dir)
    return block["repo"]


def in_diff(files: list[dict]) -> list[str]:
    return sorted({p for f in files if f.get("status") != "context" for p in (f["path"], f.get("from")) if p})


def shape(files: list[dict]) -> dict:
    return {f["path"]: (f.get("status", "modified"), f.get("from"), bool(f.get("omitted")),
                        [(h.get("old"), h.get("new"), len(h.get("lines") or [])) for h in f.get("hunks") or []])
            for f in files}


def comment_shape(comments: list[dict]) -> list[tuple]:
    return [(c.get("file"), c.get("line"), c.get("end"), c.get("side", "new") if c.get("file") else None,
             c.get("label"), c.get("item")) for c in comments]


def mismatch(block: dict, got: dict) -> str:
    want, have = shape(block["files"]), shape(got["files"])
    if set(want) != set(have):
        miss, extra = sorted(set(want) - set(have)), sorted(set(have) - set(want))
        return "files differ" + (f"; missing {', '.join(miss[:3])}" if miss else "") + (f"; extra {', '.join(extra[:3])}" if extra else "")
    bad = [p for p in want if want[p] != have[p]]
    if bad:
        return f"hunks differ in {', '.join(bad[:3])}"
    if comment_shape(block.get("comments") or []) != comment_shape(got.get("comments") or []):
        return "comments differ"
    return ""


def to_ref(block: dict, repo: str, paths: list[str] | None) -> dict:
    out: dict = {}
    for k, v in block.items():
        if k == "files":
            continue
        out[k] = [diffref.compact_comment(c) for c in v] if k == "comments" else (repo if k == "repo" else v)
        if k == "head" and paths:
            out["paths"] = paths
    return out


def convert(block: dict, doc_dir: Path, roots: list[Path], cache: dict) -> tuple[dict | None, str]:
    """(ref to store, '') after the expansion matched, else (None, why); fills `cache` with its entry."""
    if not block.get("base") or not block.get("head"):
        return None, "no base/head"
    found = find_repo(block, doc_dir, roots)
    if found is None:
        return None, f"repo '{block.get('repo')}' with {block['base']}..{block['head']} not found"
    why = ""
    for paths in (None, in_diff(block["files"])):
        probe = to_ref(block, str(found), paths)
        entries: dict = {}
        _, problems = diffref.expand_block(probe, doc_dir, entries, use_cache=False, allow_remote=False)
        errors = [p for p in problems if p.startswith("ERROR")]
        why = errors[0].split(": ", 1)[-1] if errors else mismatch(block, probe)
        if not why:
            ref = to_ref(block, stored_repo(block, found, doc_dir), paths)
            entry = entries[diffref.cache_key(probe)]
            if diffref.cache_key(ref) in cache:  # another block of this doc reads the same range
                entry["src"] = {**cache[diffref.cache_key(ref)].get("src", {}), **entry["src"]}
            cache[diffref.cache_key(ref)] = entry
            return ref, ""
        if errors or not why.startswith("files differ"):
            break
    return None, why


def contract_gaps(doc: dict) -> list[str] | None:
    try:
        import build
    except ImportError:
        return None
    check = getattr(build, "check_contract", None)
    return check(doc) if check else None


def migrate(path: Path, roots: list[Path], dry_run: bool) -> dict:
    raw = path.read_text(encoding="utf-8")
    row = {"doc": path, "converted": 0, "kept": [], "before": len(raw.encode()), "after": len(raw.encode()), "gaps": None}
    try:
        doc = json.loads(raw)
    except ValueError as e:
        row["kept"].append(f"unreadable JSON: {e}")
        return row
    if not isinstance(doc, dict):
        return row
    cpath = diffref.cache_path(path)
    cache, _ = diffref.load_cache(cpath)
    doc_dir = path.resolve().parent
    for block in list(embedded_blocks(doc)):
        ref, why = convert(block, doc_dir, roots, cache)
        if ref is None:
            row["kept"].append(f"{block.get('id', '?')}: {why}")
            continue
        block.clear()
        block.update(ref)
        row["converted"] += 1
    gaps = contract_gaps(copy.deepcopy(doc))
    row["gaps"] = gaps
    if row["converted"]:
        text = dump_like(raw, doc)
        row["after"] = len(text.encode())
        if not dry_run:
            diffref.save_cache(cpath, cache)
            path.write_text(text, encoding="utf-8")
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    ap.add_argument("--repo-root", type=Path, action="append", default=[], help="folder holding repos (repeatable)")
    a = ap.parse_args()
    roots = [r.resolve() for r in a.repo_root]
    docs = sorted(p for pat in ("*.bluedoc.json", "*.blueprint.json") for p in a.folder.rglob(pat))
    rows = [migrate(p, roots, a.dry_run) for p in docs]
    names = [str(r["doc"].relative_to(a.folder)) for r in rows]
    w = max([len("doc"), *map(len, names)])
    print(f"{'doc':<{w}}  conv  kept  {'bytes before → after':>24}  contract gaps")
    for name, r in zip(names, rows):
        size = f"{r['before']:,} → {r['after']:,}"
        gaps = "n/a" if r["gaps"] is None else str(len(r["gaps"]))
        print(f"{name:<{w}}  {r['converted']:>4}  {len(r['kept']):>4}  {size:>24}  {gaps}")
    before, after = sum(r["before"] for r in rows), sum(r["after"] for r in rows)
    print(f"{'total':<{w}}  {sum(r['converted'] for r in rows):>4}  {sum(len(r['kept']) for r in rows):>4}  "
          f"{f'{before:,} → {after:,}':>24}")
    for name, r in zip(names, rows):
        for k in r["kept"]:
            print(f"kept  {name}: {k}")
        for g in r["gaps"] or []:
            print(f"gap   {name}: {g}")
    if a.dry_run:
        print("dry run: nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
