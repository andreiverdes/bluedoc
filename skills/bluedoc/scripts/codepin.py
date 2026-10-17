#!/usr/bin/env python3
"""Evidence pinned to the code it checked: the `pin` of a step's or progress item's evidence entry.

`build.py patch` stamps each evidence entry it records (and every entry of the target with --pin) with:
  {"repo": "../..", "commit": "<full HEAD sha>", "dirty": false, "paths": ["src/carts"], "at": "<UTC ISO time>"}
  {"repo": "acme-shop", "commit": "…", "dirty": true, "tree": "<sha256>", "at": "…"}
  {"commit": null, "reason": "not in a git repository", "at": "…"}           (unpinned: no git, no repo, no commit)
`repo` is the repo root relative to the doc's folder when the doc is inside it (it starts with "."), else the root
folder's name: $BLUEDOC_HOME/repos.json maps a name to the folder it was stamped in, and a name also finds a repo of
that name beside the doc. `paths` (git pathspecs from the repo root) narrows what the check covers; without them it
covers the whole repo. `dirty` says whether the covered files differed from `commit` when the check ran, and `tree`
fingerprints how: sha256 over each such file (tracked or untracked, not ignored) and its content. bluedoc's own
files (*.bluedoc.json, their history, diff cache and snapshots) never count: recording evidence writes them.

Staleness (evaluate) compares a pin with the repo now. The covered files are compared with `commit` (committed and
working-tree changes together, untracked files included):
  current   HEAD is still `commit` and the covered files are as checked (both clean, or the same `tree`)
  moved     HEAD moved past `commit` but the covered files are as checked: still valid
  stale     the covered files differ from what was checked, or `commit` is no longer HEAD's ancestor (a rebase or a
            reset) or no longer in the repo
  unknown   no repo here (or no git)
Results are cached per (repo, HEAD, working-tree fingerprint), so a page render costs three git calls per repo.
Python 3.9+ standard library only. Never raises on a missing git or repo: those read as unpinned or unknown.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

# as diffref.GIT: a repo a doc names can come from anyone, so git must not open a bare repo by itself or start an
# fsmonitor hook; diffs never run an external diff or textconv driver
GIT = ("git", "-c", "safe.bareRepository=explicit", "-c", "core.fsmonitor=false")
SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
TREE_RE = re.compile(r"^[0-9a-f]{64}$")
# bluedoc's own files: recording evidence rewrites the doc and its history, so they never make a pin stale
OWN_FILES = tuple(f":(exclude,glob){g}" for g in (
    "**/*.bluedoc.json", "**/*.blueprint.json", "**/*.bluedoc.history.json", "**/*.blueprint.history.json",
    "**/*.diffcache.json", "**/*.bluedoc.snapshots/**", "**/*.blueprint.snapshots/**"))
MAX_FILES = 50   # changed files a result lists; `n` counts them all
STATES = ("current", "moved", "stale", "unknown")


class GitMissing(Exception):
    pass


def _git(root: Path | str, *args: str) -> tuple[int, bytes]:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    try:
        r = subprocess.run([*GIT, "-C", str(root), *args], capture_output=True, timeout=30, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        raise GitMissing(str(e)) from e
    return r.returncode, r.stdout


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_root(d: Path) -> Path | None:
    """The top folder of the git work tree d is in, or None. Raises GitMissing without git."""
    if not d.is_dir():
        return None
    code, out = _git(d, "rev-parse", "--show-toplevel")
    return Path(out.decode("utf-8", "replace").strip()).resolve() if code == 0 and out.strip() else None


def head_of(root: Path) -> str | None:
    code, out = _git(root, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    return out.decode().strip() if code == 0 and out.strip() else None


def pathspec(paths: list[str] | None) -> list[str]:
    """What a pin covers, as git pathspecs from the repo root: its paths (else the whole repo) minus bluedoc's files."""
    return [*([p.removeprefix("./") for p in paths or [] if p] or ["."]), *OWN_FILES]


def changed_files(root: Path, commit: str, spec: list[str]) -> list[str]:
    """The covered files whose working-tree content differs from commit: tracked ones (committed or not since, staged or
    not, deleted) and untracked ones that aren't ignored. Sorted, from the repo root."""
    code, out = _git(root, "diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", commit, "--", *spec)
    if code:
        raise ValueError(f"git diff {commit[:7]} failed")
    files = {f for f in out.decode("utf-8", "surrogateescape").split("\0") if f}
    code, out = _git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", *spec)
    if code == 0:
        files |= {f for f in out.decode("utf-8", "surrogateescape").split("\0") if f}
    return sorted(files)


def fingerprint(root: Path, files: list[str]) -> str:
    """sha256 over each file's path and content (a symlink: its target; a deleted file: a dash)."""
    h = hashlib.sha256()
    for f in sorted(files):
        p = root / f
        if p.is_symlink():
            what = "l:" + os.readlink(p)
        elif p.is_file():
            fh = hashlib.sha256()
            with open(p, "rb") as fp:
                for chunk in iter(lambda: fp.read(1 << 20), b""):
                    fh.update(chunk)
            what = fh.hexdigest()
        else:
            what = "-"
        h.update(f.encode("utf-8", "surrogateescape") + b"\0" + what.encode("utf-8", "surrogateescape") + b"\n")
    return h.hexdigest()


# ---------------------------------------------------------------- the repos a name points to

def _home() -> Path:
    return Path(os.environ.get("BLUEDOC_HOME") or "~/.bluedoc").expanduser()


def registry() -> dict[str, str]:
    try:
        x = json.loads((_home() / "repos.json").read_text(encoding="utf-8"))
        return {k: v for k, v in x.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(x, dict) else {}
    except (OSError, ValueError):
        return {}


def remember(name: str, root: Path) -> None:
    """$BLUEDOC_HOME/repos.json[name] = root, so a page finds a repo that holds no doc of its own (a plan gate's)."""
    reg = registry()
    if reg.get(name) == str(root):
        return
    reg[name] = str(root)
    p = _home() / "repos.json"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(reg, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def repo_ref(root: Path, doc_path: Path) -> str:
    """The repo root relative to the doc's folder when the doc is inside it, else the root's folder name."""
    doc_dir = Path(doc_path).resolve().parent
    if doc_dir == root or root in doc_dir.parents:
        return Path(os.path.relpath(root, doc_dir)).as_posix()
    return root.name


def resolve(ref, doc_path: Path) -> Path | None:
    """The repo root a pin's `repo` names, from the doc's folder: a relative path (".", "../.."), else a name
    (repos.json, then a folder of that name beside the doc). None when it isn't a work tree's top folder."""
    if not isinstance(ref, str) or not ref:
        return None
    doc_dir = Path(doc_path).resolve().parent
    cands = [doc_dir / ref] if ref.startswith(".") else [Path(p) for p in [registry().get(ref)] if p] + [doc_dir / ref]
    for c in cands:
        try:
            c = c.resolve()
            if c.is_dir() and repo_root(c) == c:
                return c
        except OSError:
            continue
    return None


# ---------------------------------------------------------------- stamping

def stamp(doc_path: Path, repo: Path | None = None, paths: list[str] | None = None, at: str | None = None) -> dict:
    """A pin for evidence recorded now: the repo is `repo`'s, else the doc's, else the current folder's. Never raises:
    without git, a repo or a commit, the pin is {commit: null, reason, at}."""
    at = at or now_iso()
    try:
        starts = [Path(repo)] if repo else [Path(doc_path).resolve().parent, Path.cwd()]
        root = next((r for r in map(repo_root, starts) if r), None)
        if root is None:
            return {"commit": None, "reason": f"'{Path(repo).name}' is not in a git repository" if repo else "not in a git repository", "at": at}
        head = head_of(root)
        if head is None:
            return {"commit": None, "reason": "the repository has no commits yet", "at": at}
        files = changed_files(root, head, pathspec(paths))
        tree = fingerprint(root, files) if files else None
    except GitMissing:
        return {"commit": None, "reason": "git is not installed", "at": at}
    except (OSError, ValueError) as e:
        return {"commit": None, "reason": f"git failed: {e}", "at": at}
    ref = repo_ref(root, doc_path)
    if not ref.startswith("."):
        remember(ref, root)
    pin = {"repo": ref, "commit": head, "dirty": bool(files)}
    if tree:
        pin["tree"] = tree
    if paths:
        pin["paths"] = [p.removeprefix("./") for p in paths]
    pin["at"] = at
    return pin


# ---------------------------------------------------------------- staleness

_cache: dict[tuple, dict] = {}


def repo_state(root: Path) -> tuple[str, str] | None:
    """(HEAD, fingerprint of the working tree's changes) or None without a commit: the cache key's moving parts."""
    head = head_of(root)
    if head is None:
        return None
    h = hashlib.sha256()
    _, diff = _git(root, "diff", "HEAD", "--binary", "--no-ext-diff", "--no-textconv")
    h.update(diff)
    _, others = _git(root, "ls-files", "-z", "--others", "--exclude-standard")
    for f in sorted(x for x in others.decode("utf-8", "surrogateescape").split("\0") if x):
        try:
            st = (root / f).lstat()
            h.update(f"{f}\0{st.st_size}\0{st.st_mtime_ns}\n".encode("utf-8", "surrogateescape"))
        except OSError:
            pass
    return head, h.hexdigest()


def check(root: Path, pin: dict, state: tuple[str, str] | None = None) -> dict:
    """{state, head, files, n, reason} of one pin against the repo at root (see the module doc)."""
    commit, paths = pin.get("commit"), pin.get("paths") or None
    state = state or repo_state(root)
    if state is None:
        return {"state": "unknown", "reason": "the repository has no commits"}
    head = state[0]
    key = (str(root), *state, json.dumps(pin, sort_keys=True))
    if key in _cache:
        return _cache[key]
    short = str(commit)[:7]
    out: dict
    if _git(root, "cat-file", "-e", f"{commit}^{{commit}}")[0]:
        out = {"state": "stale", "head": head, "files": [], "n": 0,
               "reason": f"commit {short} is no longer in the repository (rebased or reset)"}
    else:
        files = changed_files(root, commit, pathspec(paths))
        same = (fingerprint(root, files) == pin.get("tree")) if pin.get("dirty") else not files
        ancestor = commit == head or _git(root, "merge-base", "--is-ancestor", commit, head)[0] == 0
        if not ancestor:
            out = {"state": "stale", "reason": f"HEAD no longer contains {short} (rebased or reset)"}
        elif not same:
            out = {"state": "stale", "reason": f"code changed since {short}"}
        elif commit == head:
            out = {"state": "current", "reason": f"the code is as checked at {short}"}
        else:
            out = {"state": "moved", "reason": f"checked at {short}, code since doesn't touch it"}
        out.update(head=head, files=files[:MAX_FILES], n=len(files))
    if len(_cache) > 512:
        _cache.clear()
    _cache[key] = out
    return out


def _evidence_owners(doc: dict):
    """(owner id, patch key, title, evidence list) for every step and progress item, nested ones included: owner ids
    are the page's, `item:<checklist>/<item>` and `step:<steps id>/<step>`."""
    def blocks(blist, where):
        for i, b in enumerate(blist or []):
            if not isinstance(b, dict):
                continue
            bpath = f"{where}/{i}"
            items = [it for it in b.get("items") or [] if isinstance(it, dict)]
            if b.get("type") == "steps":
                for s in items:
                    yield f"step:{b.get('id') or 'steps'}/{s.get('id')}", f"step:{bpath}/{s.get('id')}", s.get("title") or "", s.get("evidence")
            elif b.get("type") == "checklist":
                for it in items:
                    if not it.get("choices"):
                        k = f"item:{b.get('id')}/{it.get('id')}"
                        yield k, k, it.get("text") or "", it.get("evidence")
                    yield from blocks(it.get("blocks"), f"{b.get('id')}/{it.get('id')}")
    for sec in doc.get("sections") or []:
        if isinstance(sec, dict):
            yield from blocks(sec.get("blocks"), str(sec.get("id")))


def is_pinned(e) -> bool:
    return isinstance(e, dict) and isinstance(e.get("pin"), dict) and isinstance(e["pin"].get("commit"), str)


def evaluate(doc: dict, doc_path: Path, repo: Path | None = None) -> dict | None:
    """The page's live staleness: {"file", "owners": {owner id: {"key", "label", "ev": [result or null per entry]}}},
    a result {state, reason, head?, files?, n?, label, run?} for each pinned entry (null: unpinned). None when no entry
    is pinned. repo overrides every pin's repo."""
    owners: dict[str, dict] = {}
    roots: dict[str, Path | None] = {}
    states: dict[Path, tuple | None] = {}
    for oid, key, title, ev in _evidence_owners(doc):
        if not isinstance(ev, list) or not any(map(is_pinned, ev)):
            continue
        out = []
        for e in ev:
            if not is_pinned(e):
                out.append(None)
                continue
            pin, base = e["pin"], {"label": str(e.get("label") or "")}
            if isinstance(e.get("code"), str) and e["code"].strip():
                base["run"] = e["code"].strip()
            ref = str(pin.get("repo") or "")
            try:
                if ref not in roots:
                    roots[ref] = repo_root(Path(repo)) if repo else resolve(ref, doc_path)
                root = roots[ref]
                if root is None:
                    out.append({**base, "state": "unknown", "reason": f"repository '{ref}' isn't here"})
                    continue
                if root not in states:
                    states[root] = repo_state(root)
                out.append({**base, **check(root, pin, states[root])})
            except GitMissing:
                out.append({**base, "state": "unknown", "reason": "git is not installed"})
            except (OSError, ValueError) as e2:
                out.append({**base, "state": "unknown", "reason": f"git failed: {e2}"})
        owners[oid] = {"key": key, "label": re.sub(r"[`*]", "", title), "ev": out}
    return {"file": Path(doc_path).name, "owners": owners} if owners else None


def stale_owners(result: dict | None) -> list[dict]:
    return [o for o in ((result or {}).get("owners") or {}).values() if any(r and r.get("state") == "stale" for r in o["ev"])]


def stale_md(result: dict | None, doc_cmd: str | None = None) -> str:
    """`## Stale evidence`: each check whose evidence is stale, what changed, its command, and the `build.py patch
    --pin` commands that re-record it (the first bumps the rev). Empty when nothing is stale."""
    owners = stale_owners(result)
    if not owners:
        return ""
    doc = doc_cmd or result["file"]
    lines = []
    for o in owners:
        lines.append(f"- **{o['label']}** `{o['key']}`")
        for r in o["ev"]:
            if r and r.get("state") == "stale":
                files = r.get("files") or []
                more = f", +{r['n'] - len(files)} more" if r.get("n", 0) > len(files) else ""
                lines.append(f"  - {r['label']}: {r['reason']}" + (f" ({', '.join(files)}{more})" if files else ""))
                if r.get("run"):
                    lines.append(f"    Re-run: `{r['run']}`")
    cmds = [f"build.py patch {doc} {o['key']} --pin" + (" --change 'Re-ran the checks after code changes'" if not i else " --no-bump")
            for i, o in enumerate(owners)]
    n = len(owners)
    return (f"## Stale evidence\n\n{n} check{' has' if n == 1 else 's have'} stale evidence: the code changed since "
            f"{'it' if n == 1 else 'they'} ran. Re-run {'it' if n == 1 else 'each'}, then re-record its evidence (update its "
            "`md` when the result changed):\n\n" + "\n".join(lines)
            + "\n\n```sh\n" + "\n".join(cmds) + "\n```\n")
