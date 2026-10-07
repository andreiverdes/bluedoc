#!/usr/bin/env python3
"""Turn a git range plus line comments into a bluedoc `diff` block.

Usage:
  gitdiff.py --repo PATH --base REV --head REV --id ID --title TITLE [options] > block.json
  gitdiff.py ... --into doc.bluedoc.json --section SECTION_ID [--after-block N]

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
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
AT_RE = re.compile(r"^(?P<path>[^:\s][^:]*?)(?::~?(?P<line>\d+)(?:-(?P<end>\d+))?(?:[,;].*)?)?$")


def git(repo: str, *args: str) -> str:
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def parse_diff(text: str) -> list[dict]:
    files: list[dict] = []
    cur: dict | None = None
    hunk: dict | None = None
    for raw in text.split("\n"):
        if raw.startswith("diff --git "):
            m = re.match(r'^diff --git "?a/(.+?)"? "?b/(.+?)"?$', raw)
            cur = {"path": m.group(2) if m else raw[11:], "status": "modified", "add": 0, "del": 0, "hunks": []}
            if m and m.group(1) != m.group(2):
                cur["from"] = m.group(1)
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            continue
        if hunk is None:
            if raw.startswith("new file mode"):
                cur["status"] = "added"
            elif raw.startswith("deleted file mode"):
                cur["status"] = "deleted"
            elif raw.startswith("rename from "):
                cur["status"] = "renamed"
                cur["from"] = raw[12:]
            elif raw.startswith("rename to "):
                cur["path"] = raw[10:]
            elif raw.startswith("Binary files"):
                cur["omitted"] = "binary file"
        m = HUNK_RE.match(raw)
        if m:
            hunk = {"old": int(m.group(1)), "new": int(m.group(3)), "lines": []}
            if m.group(5):
                hunk["header"] = m.group(5).strip()
            cur["hunks"].append(hunk)
            continue
        if hunk is None or raw.startswith("\\"):
            continue
        if raw[:1] in ("+", "-", " "):
            hunk["lines"].append(raw)
            if raw[0] == "+":
                cur["add"] += 1
            elif raw[0] == "-":
                cur["del"] += 1
        elif raw == "":
            continue
    for f in files:
        if f["status"] == "renamed" or (f.get("from") and f["from"] != f["path"]):
            f["status"] = "renamed"
        else:
            f.pop("from", None)
    return files


def hunk_span(h: dict) -> tuple[int, int, int, int]:
    """(old_start, old_end, new_start, new_end), inclusive; an empty side ends before it starts."""
    o = sum(1 for l in h["lines"] if l[0] != "+")
    n = sum(1 for l in h["lines"] if l[0] != "-")
    return h["old"], h["old"] + o - 1, h["new"], h["new"] + n - 1


def new_covered(f: dict) -> set[int]:
    out: set[int] = set()
    for h in f["hunks"]:
        n = h["new"]
        for l in h["lines"]:
            if l[0] != "-":
                out.add(n)
                n += 1
    return out


def old_for_new(f: dict, line: int) -> int:
    """Old-side number of an unchanged line outside every hunk: shift by the net growth of the hunks above it."""
    delta = 0
    for h in f["hunks"]:
        os_, oe, ns, ne = hunk_span(h)
        if ne < line and ns <= line:
            delta += (ne - ns) - (oe - os_)
    return line - delta


def add_excerpt(f: dict, src: list[str], start: int, end: int) -> None:
    covered = new_covered(f)
    seg: list[int] = []
    segs: list[list[int]] = []
    for n in range(max(1, start), min(len(src), end) + 1):
        if n in covered:
            if seg:
                segs.append(seg)
                seg = []
        elif seg and n != seg[-1] + 1:
            segs.append(seg)
            seg = [n]
        else:
            seg.append(n)
    if seg:
        segs.append(seg)
    for s in segs:
        f["hunks"].append({"old": old_for_new(f, s[0]), "new": s[0], "context": True,
                           "lines": [" " + src[n - 1] for n in s]})
    merge_hunks(f)


def merge_hunks(f: dict) -> None:
    f["hunks"].sort(key=lambda h: (h["new"], h["old"]))
    out: list[dict] = []
    for h in f["hunks"]:
        if out:
            p = out[-1]
            _, poe, _, pne = hunk_span(p)
            if h["new"] == pne + 1 and h["old"] == poe + 1:
                p["lines"].extend(h["lines"])
                if not h.get("context"):
                    p.pop("context", None)
                continue
        out.append(h)
    f["hunks"] = out


def parse_comment(c: dict, strip: list[str]) -> dict:
    c = dict(c)
    at = c.pop("at", None)
    if at:
        m = AT_RE.match(at.strip())
        head = m.group("path") if m else ""
        if m and ("/" in head or "." in head) and " " not in head.split("/")[0]:
            c["file"] = head.strip()
            if m.group("line"):
                c["line"] = int(m.group("line"))
                if m.group("end"):
                    c["end"] = int(m.group("end"))
        else:
            c["label"] = at
    if c.get("file"):
        for p in strip:
            if c["file"].startswith(p):
                c["file"] = c["file"][len(p):]
    return c


def build_block(a: argparse.Namespace) -> dict:
    paths = a.paths or []
    text = git(a.repo, "diff", "--no-color", "--no-ext-diff", f"-U{a.context}", "--find-renames",
               a.base, a.head, "--", *paths)
    files = [f for f in parse_diff(text) if not any(fnmatch.fnmatch(f["path"], g) for g in a.exclude or [])]
    by_path = {f["path"]: f for f in files}
    raw = json.loads(Path(a.comments).read_text(encoding="utf-8")) if a.comments else []
    comments = []
    head_tree = set(git(a.repo, "ls-tree", "-r", "--name-only", a.head).split("\n"))
    sources: dict[str, list[str]] = {}

    def src(path: str) -> list[str]:
        if path not in sources:
            sources[path] = git(a.repo, "show", f"{a.head}:{path}").rstrip("\n").split("\n")
        return sources[path]

    for c in (parse_comment(x, a.strip_prefix or []) for x in raw):
        path = c.get("file")
        if path and path not in by_path and path not in head_tree:
            c["label"] = c.get("label") or (path + (f":{c['line']}" if c.get("line") else ""))
            for k in ("file", "line", "end", "side"):
                c.pop(k, None)
        elif path and path not in by_path:
            by_path[path] = {"path": path, "status": "context", "add": 0, "del": 0, "hunks": []}
            files.append(by_path[path])
        if c.get("file") and c.get("line") and c.get("side", "new") == "new":
            f = by_path[c["file"]]
            lo, hi = c["line"], c.get("end", c["line"])
            if any(n not in new_covered(f) for n in range(lo, hi + 1)):
                add_excerpt(f, src(c["file"]), lo - a.excerpt, hi + a.excerpt)
        comments.append(c)
    commented = {c.get("file") for c in comments}
    for f in files:
        changed = f["add"] + f["del"]
        if changed > a.max_lines and f["path"] not in commented:
            f["omitted"] = f"{changed} changed lines; open it in the repository"
            f["hunks"] = []
    files.sort(key=lambda f: f["path"])
    block = {"type": "diff", "id": a.id, "title": a.title, "repo": a.repo_name or Path(a.repo).resolve().name,
             "base": git(a.repo, "rev-parse", "--short", a.base).strip(),
             "head": git(a.repo, "rev-parse", "--short", a.head).strip()}
    if a.url:
        block["url"] = a.url
    if a.note:
        block["note"] = a.note
    block["files"] = files
    if comments:
        block["comments"] = comments
    return block


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--repo-name", help="name shown in the header (default: the folder name)")
    ap.add_argument("--url")
    ap.add_argument("--note", help="inline md under the header, e.g. which snapshot was reviewed")
    ap.add_argument("--comments", help="JSON list of comments (see above)")
    ap.add_argument("--strip-prefix", action="append", help="drop this prefix from comment paths (repeatable)")
    ap.add_argument("--paths", nargs="*", help="limit the diff to these pathspecs")
    ap.add_argument("--exclude", action="append", help="glob of files to leave out (repeatable)")
    ap.add_argument("--context", type=int, default=3, help="context lines per hunk (default 3)")
    ap.add_argument("--excerpt", type=int, default=5, help="lines around a comment outside the diff (default 5)")
    ap.add_argument("--max-lines", type=int, default=800,
                    help="drop the hunks of an uncommented file with more changed lines (default 800)")
    ap.add_argument("--into", help="insert or replace the block in this document")
    ap.add_argument("--section", help="section id for --into")
    ap.add_argument("--after-block", type=int, help="block index to insert after (default: end of section)")
    a = ap.parse_args()
    block = build_block(a)
    if not a.into:
        json.dump(block, sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
        return 0
    if not a.section:
        ap.error("--into needs --section")
    path = Path(a.into)
    raw_doc = path.read_text(encoding="utf-8")
    doc = json.loads(raw_doc)
    indent = next((n for n in (1, 2, 4) if raw_doc.startswith("{\n" + " " * n + '"') and not raw_doc.startswith("{\n" + " " * (n + 1))), 2)
    sec = next((s for s in doc.get("sections", []) if s.get("id") == a.section), None)
    if sec is None:
        raise SystemExit(f"no section '{a.section}' in {path}")
    blocks = sec.setdefault("blocks", [])
    idx = next((i for i, b in enumerate(blocks) if b.get("type") == "diff" and b.get("id") == a.id), None)
    if idx is not None:
        blocks[idx] = block
    elif a.after_block is not None:
        blocks.insert(a.after_block + 1, block)
    else:
        blocks.append(block)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=indent) + ("\n" if raw_doc.endswith("\n") else ""), encoding="utf-8")
    n = sum(len(h["lines"]) for f in block["files"] for h in f["hunks"])
    print(f"{'replaced' if idx is not None else 'inserted'} diff '{a.id}' in section '{a.section}': "
          f"{len(block['files'])} files, {n} lines, {len(block.get('comments', []))} comments", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
