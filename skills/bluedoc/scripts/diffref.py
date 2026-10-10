#!/usr/bin/env python3
"""Expand `diff` blocks that reference a git range into the files and comments the page draws.

A diff block is a reference when it has `base` and `head` and no `files`:
  {"type": "diff", "id": "diff-412", "title": "acme-shop #412", "repo": "../acme-shop",
   "base": "89efd8e", "head": "62ccc86", "paths": ["src/pricing/tiers.ts"], "pr": "acme/acme-shop#412",
   "comments": [{"at": "src/pricing/tiers.ts:17-21", "item": "t412/tier-boundary"}]}
`repo` is relative to the doc's folder (or absolute); `paths` limits the diff; `pr` (`owner/repo#N` or a PR
URL; a github.com pull `url` also works) enables the `gh pr diff` fallback. Optional, only when not the
default: `exclude` (globs), `context` (3), `excerpt` (5), `max_lines` (800), as in gitdiff.py.

Sources, in order: `<stem>.diffcache.json` next to the doc (keyed by repo|base|head|paths, with a branch or tag
name resolved to its commit; commit the file, so the diff survives a rebase or a deleted branch), local git, then
`gh pr diff` when the repo or commits are missing (refused when the PR head is no longer `head`). The cache keeps
each diff and, per file, only the source lines its comment excerpts show. Blocks with `files` are left as they are.

The example review's repo: git clone skills/bluedoc/examples/acme-shop.bundle skills/bluedoc/examples/acme-shop
Python 3.9+ standard library only. Never prints; problems come back as "ERROR …" / "WARN  …" strings.
"""
from __future__ import annotations

import copy
import fnmatch
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
AT_RE = re.compile(r"^(?P<path>[^:\s][^:]*?)(?::~?(?P<line>\d+)(?:-(?P<end>\d+))?(?:[,;].*)?)?$")
GIT_RE = re.compile(r'^diff --git "?a/(.+?)"? "?b/(.+?)"?$')
PR_URL_RE = re.compile(r"^https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
CACHE_VERSION = 2
CONTEXT = 3
EXCERPT = 5
MAX_LINES = 800

Source = Callable[[str, int, int], Optional[dict]]


# ---------------------------------------------------------------- unified diff -> files

def parse_diff(text: str) -> list[dict]:
    files: list[dict] = []
    cur: dict | None = None
    hunk: dict | None = None
    for raw in text.split("\n"):
        if raw.startswith("diff --git "):
            m = GIT_RE.match(raw)
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


def add_excerpt(f: dict, src: dict[int, str], start: int, end: int) -> None:
    covered = new_covered(f)
    seg: list[int] = []
    segs: list[list[int]] = []
    for n in range(max(1, start), end + 1):
        if n not in src:   # past the end of the file
            continue
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
                           "lines": [" " + src[n] for n in s]})
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


# ---------------------------------------------------------------- comments

def parse_comment(c: dict, strip: list[str] | tuple = ()) -> dict:
    """`at` -> file/line/end (or a PR-level label); drop `strip` prefixes from the file path."""
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


def compact_comment(c: dict) -> dict:
    """The shortest stored form of a normalised comment: file/line/end as `at` when that round-trips."""
    if not c.get("file") or c.get("side", "new") != "new" or "at" in c:
        return dict(c)
    at = c["file"] + (f":{c['line']}" if c.get("line") else "") + (f"-{c['end']}" if c.get("line") and c.get("end") else "")
    rest = {k: v for k, v in c.items() if k not in ("file", "line", "end", "side")}
    out = {"at": at, **rest}
    back = parse_comment(out)
    if any(back.get(k) != c.get(k) for k in ("file", "line", "end")) or back.get("label"):
        return dict(c)
    return out


def assemble(diff_text: str, raw_comments: list[dict], source: Source, *, exclude: list[str] | tuple = (),
             strip: list[str] | tuple = (), excerpt: int = EXCERPT, max_lines: int = MAX_LINES
             ) -> tuple[list[dict], list[dict], list[str]]:
    """Files and normalised comments of one diff block. `source(path, lo, hi)` is lines lo..hi of the file at
    head as {number: text}, cut at the end of the file (lo > hi only asks whether it exists), or None when the
    file is not there. Returns (files, comments, paths whose text could not be read)."""
    files = [f for f in parse_diff(diff_text) if not any(fnmatch.fnmatch(f["path"], g) for g in exclude)]
    by_path = {f["path"]: f for f in files}
    unread: list[str] = []

    comments = []
    for c in (parse_comment(x, strip) for x in raw_comments):
        path = c.get("file")
        if path and path not in by_path and source(path, 1, 0) is None:
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
                lines = source(c["file"], lo - excerpt, hi + excerpt)
                if lines is None:
                    unread.append(c["file"])
                else:
                    add_excerpt(f, lines, lo - excerpt, hi + excerpt)
        comments.append(c)
    commented = {c.get("file") for c in comments}
    for f in files:
        changed = f["add"] + f["del"]
        if changed > max_lines and f["path"] not in commented:
            f["omitted"] = f"{changed} changed lines; open it in the repository"
            f["hunks"] = []
    files.sort(key=lambda f: f["path"])
    return files, comments, unread


# ---------------------------------------------------------------- where a range comes from

def _run(cmd: list[str], cwd: str | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, encoding="utf-8", errors="replace")
    except OSError as e:
        return 127, str(e)
    return r.returncode, r.stdout if r.returncode == 0 else r.stderr.strip()


def git_diff_args(base: str, head: str, paths: list[str], context: int = CONTEXT) -> list[str]:
    return ["diff", "--no-color", "--no-ext-diff", f"-U{context}", "--find-renames", base, head, "--", *paths]


def path_matches(path: str, specs: list[str]) -> bool:
    """git pathspec, as far as `paths` uses it: the file, a folder above it, or a glob."""
    return not specs or any(path == s or path.startswith(s.rstrip("/") + "/") or fnmatch.fnmatch(path, s) for s in specs)


def filter_diff(text: str, specs: list[str]) -> str:
    """Keep the per-file sections of a unified diff whose old or new path matches `specs`."""
    if not specs:
        return text
    out: list[str] = []
    keep = False
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            m = GIT_RE.match(line)
            keep = bool(m) and (path_matches(m.group(1), specs) or path_matches(m.group(2), specs))
        if keep:
            out.append(line)
    return "\n".join(out) + ("\n" if out else "")


class LocalGit:
    via = "git"

    def __init__(self, repo: Path, base: str, head: str) -> None:
        self.repo, self.base, self.head = str(repo), base, head

    def diff(self, paths: list[str], context: int) -> tuple[str | None, str]:
        code, out = _run(["git", "-C", self.repo, *git_diff_args(self.base, self.head, paths, context)])
        return (out, "") if code == 0 else (None, f"git diff failed: {out}")

    def source(self, path: str) -> str | None:
        code, out = _run(["git", "-C", self.repo, "cat-file", "blob", f"{self.head}:{path}"])
        return out if code == 0 else None


class GhPull:
    via = "gh"

    def __init__(self, repo: str | None, number: str, head_oid: str) -> None:
        self.repo, self.number, self.head_oid = repo, number, head_oid

    def _r(self) -> list[str]:
        return ["-R", self.repo] if self.repo else []

    def diff(self, paths: list[str], context: int) -> tuple[str | None, str]:
        code, out = _run(["gh", "pr", "diff", self.number, *self._r()])
        return (filter_diff(out, paths), "") if code == 0 else (None, f"gh pr diff failed: {out}")

    def source(self, path: str) -> str | None:
        if not self.repo:
            return None
        code, out = _run(["gh", "api", "-H", "Accept: application/vnd.github.raw",
                          f"repos/{self.repo}/contents/{path}?ref={self.head_oid}"])
        return out if code == 0 else None


def has_commits(repo: Path, *revs: str) -> bool:
    return repo.is_dir() and all(_run(["git", "-C", str(repo), "cat-file", "-e", f"{r}^{{commit}}"])[0] == 0 for r in revs)


def pr_spec(block: dict) -> tuple[str | None, str] | None:
    """(owner/repo, number) of the block's PR, from `pr` or a github.com pull `url`."""
    pr = str(block.get("pr") or "").strip()
    m = PR_URL_RE.match(pr) or PR_URL_RE.match(str(block.get("url") or ""))
    if m:
        return m.group(1), m.group(2)
    if "#" in pr:
        repo, _, num = pr.rpartition("#")
        return repo or None, num
    return (None, pr) if pr else None


def open_gh(block: dict) -> tuple[GhPull | None, str]:
    spec = pr_spec(block)
    if not spec:
        return None, "no `pr` for the gh fallback"
    repo, num = spec
    code, out = _run(["gh", "pr", "view", num, *(["-R", repo] if repo else []), "--json", "headRefOid", "-q", ".headRefOid"])
    if code:
        return None, f"gh pr view {block.get('pr') or num} failed: {out}"
    oid, head = out.strip().lower(), str(block["head"]).lower()
    if not oid or not (oid.startswith(head) or head.startswith(oid)):
        return None, f"refused gh pr diff: PR head is {oid[:9] or '?'}, not {block['head']} (the PR moved since the review)"
    return GhPull(repo, num, oid), ""


def resolve_repo(block: dict, doc_dir: Path) -> Path:
    p = Path(os.path.expanduser(str(block.get("repo") or "")))
    return p if p.is_absolute() else doc_dir / p


def open_source(block: dict, doc_dir: Path, allow_remote: bool) -> tuple[LocalGit | GhPull | None, str]:
    """Local git when the repo has both commits; else `gh` (if allowed). (None, why) when neither works."""
    repo = resolve_repo(block, doc_dir)
    if block.get("repo") and has_commits(repo, block["base"], block["head"]):
        return LocalGit(repo, block["base"], block["head"]), ""
    why = f"repo '{block.get('repo')}' not found" if not repo.is_dir() or not block.get("repo") else \
        f"commits {block['base']}..{block['head']} not in '{block.get('repo')}'"
    if not allow_remote:
        return None, why
    gh, err = open_gh(block)
    return (gh, "") if gh else (None, f"{why}; {err}")


# ---------------------------------------------------------------- cache

def cache_path(doc_path: Path) -> Path:
    name = doc_path.name
    for suffix in (".bluedoc.json", ".blueprint.json", ".json"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return doc_path.with_name(name + ".diffcache.json")


def resolve_rev(block: dict, doc_dir: Path, rev: str) -> str:
    """rev as a full commit hash when it is a branch or tag the block's local repo knows; else as written."""
    if SHA_RE.match(rev) or not block.get("repo"):
        return rev
    repo = resolve_repo(block, doc_dir)
    if not repo.is_dir():
        return rev
    code, out = _run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", f"{rev}^{{commit}}"])
    return out.strip() if code == 0 and out.strip() else rev


def cache_key(block: dict, doc_dir: Path) -> str:
    """repo|base|head|paths[|U<context>], with a branch or tag name in base or head resolved to its commit, so
    a branch that moves misses the cache instead of showing the diff it had when first cached."""
    base, head = (resolve_rev(block, doc_dir, str(block[k])) for k in ("base", "head"))
    key = f"{block.get('repo', '')}|{base}|{head}|{','.join(block.get('paths') or [])}"
    ctx = block.get("context", CONTEXT)
    return key if ctx == CONTEXT else f"{key}|U{ctx}"


# A cached source file: {"lines": its line count, "at": {"<first line number>": "text\ntext", ...}}, the runs of
# lines comment excerpts show; null when the file is not there at head.

def _runs(s: dict) -> dict[int, str]:
    return {int(start) + i: t for start, text in s["at"].items() for i, t in enumerate(text.split("\n"))}


def _stored(count: int, lines: dict[int, str]) -> dict:
    runs: list[list] = []
    for n in sorted(lines):
        if runs and n == runs[-1][0] + len(runs[-1][1]):
            runs[-1][1].append(lines[n])
        else:
            runs.append([n, [lines[n]]])
    return {"lines": count, "at": {str(start): "\n".join(texts) for start, texts in runs}}


def _window(s: dict, lo: int, hi: int) -> dict[int, str] | None:
    """Lines lo..hi of a cached file, cut at its end; None when one of them is not cached."""
    lo, hi = max(1, lo), min(s["lines"], hi)
    have = _runs(s)
    out = {n: have[n] for n in range(lo, hi + 1) if n in have}
    return out if len(out) == max(0, hi - lo + 1) else None


def merge_src(a: dict, b: dict) -> dict:
    """Two entries' cached sources of the same range as one: the lines of both, per file."""
    out = dict(a)
    for p, s in b.items():
        out[p] = s if s is None or not out.get(p) else _stored(s["lines"], {**_runs(out[p]), **_runs(s)})
    return out


def _pruned(entry: dict, used: dict[str, set[int]]) -> dict:
    """entry with only the files and lines in `used` (path -> line numbers read)."""
    src = {}
    for p, ns in used.items():
        s = entry["src"].get(p)
        src[p] = None if s is None else _stored(s["lines"], {n: t for n, t in _runs(s).items() if n in ns})
    return {**entry, "src": src}


def load_cache(path: Path | None) -> tuple[dict, list[str]]:
    """The cache's entries. A version 1 file, which held whole files, reads as runs of every line."""
    if path is None or not path.exists():
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = dict(data["entries"])
        for e in entries.values():
            for p, s in e["src"].items():
                if isinstance(s, str):
                    lines = s.rstrip("\n").split("\n")
                    e["src"][p] = {"lines": len(lines), "at": {"1": "\n".join(lines)}}
        return entries, []
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        return {}, [f"WARN  diffcache {path.name}: unreadable, ignored ({e})"]


def save_cache(path: Path, entries: dict) -> None:
    text = json.dumps({"bluedoc_diffcache": CACHE_VERSION, "entries": entries}, ensure_ascii=False, indent=1) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, path.stat().st_mode & 0o777 if path.exists() else 0o644)  # mkstemp makes it 0600
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------- expansion

def is_ref(block) -> bool:
    return isinstance(block, dict) and block.get("type") == "diff" and "base" in block and "head" in block and "files" not in block


def iter_refs(node):
    if isinstance(node, dict):
        if is_ref(node):
            yield node
            return
        for v in node.values():
            yield from iter_refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_refs(v)


def expand_block(block: dict, doc_dir: Path, entries: dict, *, use_cache: bool = True,
                 allow_remote: bool = True, used: dict | None = None) -> tuple[bool, list[str]]:
    """Fill one ref block in place. `entries` is the cache (read and updated); `used`, when given, collects
    the cache key and source lines this block read (key -> path -> line numbers). Returns (entries changed,
    problems)."""
    where = f"diff '{block.get('id', '?')}'"
    key = cache_key(block, doc_dir)
    entry = entries.get(key) if use_cache else None
    paths = list(block.get("paths") or [])
    origin: list = []  # resolved once, on first need: [source or None, why]

    def live():
        if not origin:
            origin.extend(open_source(block, doc_dir, allow_remote))
        return origin[0]

    raw_comments = block.get("comments") or []
    changed = False
    if entry is None:
        src = live()
        text, err = src.diff(paths, int(block.get("context", CONTEXT))) if src else (None, origin[1])
        if text is None:
            block["files"] = []
            if "comments" in block:
                block["comments"] = [parse_comment(c) for c in raw_comments]
            return False, [f"ERROR {where}: can't expand {block.get('base')}..{block.get('head')}: {err}"]
        entry = {"via": src.via, "diff": text, "src": {}}
        entries[key] = entry
        changed = True
    reads = used.setdefault(key, {}) if used is not None else None
    unavailable: list[str] = []
    texts: dict[str, list[str] | None] = {}   # whole files read from git or gh by this call

    def source(path: str, lo: int, hi: int) -> dict[int, str] | None:
        nonlocal changed
        s = entry["src"].get(path, False)
        got = None if not s else _window(s, lo, hi)
        if s is not None and got is None:
            src = live()
            if src is None:
                unavailable.append(path)
                if reads is not None and s:   # keep what the cache has; nothing can refill it
                    reads.setdefault(path, set()).update(_runs(s))
                return None
            if path not in texts:
                t = src.source(path)
                texts[path] = None if t is None else t.rstrip("\n").split("\n")
            lines = texts[path]
            if lines is None:
                s = entry["src"][path] = None
            else:
                got = {n: lines[n - 1] for n in range(max(1, lo), min(len(lines), hi) + 1)}
                entry["src"][path] = _stored(len(lines), {**(_runs(s) if s else {}), **got})
            changed = True
        if reads is not None:
            reads.setdefault(path, set()).update(got or ())
        return None if s is None else got

    files, comments, unread = assemble(
        entry["diff"], raw_comments, source, exclude=block.get("exclude") or (),
        excerpt=int(block.get("excerpt", EXCERPT)), max_lines=int(block.get("max_lines", MAX_LINES)))
    block["files"] = files
    if "comments" in block:
        block["comments"] = comments
    problems = [f"WARN  {where}: can't read '{p}' at {block['head']} ({origin[1]}); its comment has no code excerpt"
                for p in dict.fromkeys(unavailable)]
    problems += [f"WARN  {where}: '{p}' has no text at {block['head']}; its comment has no code excerpt"
                 for p in dict.fromkeys(unread) if p not in unavailable]
    return changed, problems


def expand_doc(doc: dict, doc_path: Path | None, *, use_cache: bool = True, write_cache: bool = True,
               allow_remote: bool = True, prune: bool = False) -> list[str]:
    """Fill every ref diff block of `doc` in place with `files` and normalised `comments`. With prune, `doc`
    holds every ref the cache serves (the doc and its history): the cache keeps only the entries and source
    lines they read, and is deleted when they read none."""
    refs = list(iter_refs(doc))
    if not refs and not prune:
        return []
    doc_dir = doc_path.resolve().parent if doc_path else Path.cwd()
    cpath = cache_path(doc_path) if doc_path else None
    entries, problems = load_cache(cpath) if use_cache or write_cache else ({}, [])
    used: dict | None = {} if prune else None
    dirty = False
    for b in refs:
        changed, p = expand_block(b, doc_dir, entries, use_cache=use_cache, allow_remote=allow_remote, used=used)
        dirty |= changed
        problems += p
    if used is not None:
        kept = {k: _pruned(entries[k], used[k]) for k in used if k in entries}
        dirty |= json.dumps(kept, sort_keys=True) != json.dumps(entries, sort_keys=True)
        entries = kept
    if dirty and write_cache and cpath is not None:
        try:
            if entries or not prune:
                save_cache(cpath, entries)
            else:
                cpath.unlink(missing_ok=True)
        except OSError as e:
            problems.append(f"WARN  diffcache {cpath.name}: not written ({e})")
    return problems


def expanded_copy(doc: dict, doc_path: Path | None, **kw) -> tuple[dict, list[str]]:
    out = copy.deepcopy(doc)
    return out, expand_doc(out, doc_path, **kw)
