#!/usr/bin/env python3
"""The bluedoc server: renders JSON docs with the template on every request, lists them on a
searchable home page, and passes the reader's answers and change requests back to the agent.

Usage:
  serve.py open DOC.json [--to NAME] [--browser]   start the server if needed, register the doc's
                                                   folder, print the doc's URL
  serve.py wait DOC.json [--kind answers|changes|approval|any] [--timeout SEC]
                                                   block until the reader sends answers, a change
                                                   request or a plan approval for DOC; print it as Markdown
  serve.py reply ID | DOC.json [--kind K] [--json] print a stored reply: by the id `wait` printed, or DOC's
                                                   newest (of kind K); --json prints what the page posted
  serve.py unlock                                  print a home page link that lets a browser save here
  serve.py start | stop | status                   manage the background server
  serve.py add DIR | roots                         add a folder to the home page / list folders
  serve.py add-framework NAME [PATH|URL] [--load F] [--source F] [--tailwind]
                                                   copy a framework for design boards (`store: NAME`) into
                                                   ~/.bluedoc/frameworks/NAME with a manifest (sizes, sha256);
                                                   NAME alone fetches a pinned preset: tailwind, heroui, daisyui
  serve.py run [--port N]                          run in the foreground

One server per user, on 127.0.0.1 (default port 8740, env BLUEDOC_PORT). State lives in
~/.bluedoc (env BLUEDOC_HOME): roots.json (folders the home page scans), server.json (pid, port), key (mode 0600: the
secret that writes need) and state.db (SQLite, mode 0600: the reader's ticks, picks, comments and plan state per doc,
and every reply; statedb.py).
`open` registers the topmost ancestor folder named `docs`, else the doc's own folder, and restarts a running server
whose version or code differs from its own. A folder inside a registered one is not added; a wider one is added
next to the narrower ones, which keep their URLs (a doc's URL uses its deepest registered folder).

Writes need the key: in the X-Bluedoc-Key header (the CLI reads the key file) or in the bluedoc_key_<port> cookie
(HttpOnly, SameSite=Strict). `open` and `unlock` print a link with a one-time ?key= token (good for a day); visiting
it sets the cookie and redirects to the same URL without the token. ping and index.json say whether the browser
has the cookie (`unlocked`), so a page can tell the reader it can't save yet.

URLs: /                      home page: every doc under the registered folders, searchable, filtered by
                             project, folder, type and status
      /<root>/<path>.bluedoc.json      the doc, rendered from its JSON on each request
      /<root>/<path>.bluedoc.json?raw=1   the JSON itself
      /<root>/<path>.<png|jpg|jpeg|gif|webp|svg|mp4|webm>   media files under the folder, for `media` blocks
      /__bluedoc/index.json  what the home page shows about every doc
      /__bluedoc/ping?path=  server check (version, code hash, unlocked); with a doc's URL path, also who reads
                             replies and its saved approval
      /__bluedoc/state?path=<doc URL path>[&since=N]   GET the doc's reader state {version, state}; 204 when N is
                             the current version. PUT {path, import, ops: [[key, value or null]]} writes it: null
                             deletes, an import adds only keys the server lacks. Both need the X-Bluedoc header, the
                             PUT also the key. An `__ann:<id>` value the page can't draw is dropped from a PUT and
                             left out of a read.
      /__bluedoc/vendor/<path>  files under assets/vendor (HorizonUI, the Sketch font)
      /<root>/<dir>/<stem>.design/<artboard>.html[?rev=B&theme=T]   a design doc's screen: the artboard's fragment
                             (or revision B's, from the history) wrapped in kits/shell.html with its framework,
                             theme tokens and the inspector. Its own CSP: no network, `sandbox allow-scripts`,
                             framable by this server's pages only (no X-Frame-Options)
      /__bluedoc/kit/<file>  the plain kit and inspector (assets/kits)
      /__bluedoc/fw/<name>/<path>   a framework add-framework copied
      /<root>/<path>.<css|js|mjs|font>   a project file a design board declares (frameworks[].files), and the
                             files its declared CSS names with url(); nothing else
Rendering validates the doc (errors show as a page), shows its meta.rev as the latest revision of the history file
without writing it (build.py records revisions), and fills each `diff` block that references a git range
(diffref.py: its cache, local git, then `gh pr diff`), so the page always shows the current JSON.
HTML pages carry a Content-Security-Policy (hashes of their inline scripts, no framing), and a doc page carries its
reader state and the hash of the JSON it shows in its bp-state element ({version, state, docHash}; null without
sqlite3).

Replies: Send answers posts to /__bluedoc/reply, Request changes to /__bluedoc/changes, Approve plan to
/__bluedoc/approve. Each becomes a row in state.db, queued for `wait`, which returns the oldest unread one
(GET /__bluedoc/wait needs the X-Bluedoc header and the key) and marks it delivered; a restart keeps the queue. The
first start with a new state.db imports the <name>.reply/.changes/.approval files of earlier versions and
inbox.json's delivered marks, and leaves the files. An approval posts the docHash and rev the page showed: the server
answers 409 when either differs from the doc's current JSON (and a design's screen files: build.approval_hash) and
meta.rev. It counts only while the doc is unchanged.
Python 3.9+ standard library only.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import io
import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402

try:
    import statedb  # noqa: E402
except ImportError:   # a Python built without sqlite3: pages render without reader state, replies are refused
    statedb = None

HOME_HTML = HERE.parent / "assets" / "home.html"
VENDOR = HERE.parent / "assets" / "vendor"
KITS = HERE.parent / "assets" / "kits"   # what a design screen is wrapped in: shell, plain kit, inspector
HAND_FONT = VENDOR / "fonts" / "ArchitectsDaughter-Regular.woff2"   # Sketch's font (OFL)
STATE = Path(os.environ.get("BLUEDOC_HOME") or "~/.bluedoc").expanduser()
ROOTS_FILE, SERVER_FILE, STATE_DB, KEY_FILE = STATE / "roots.json", STATE / "server.json", STATE / "state.db", STATE / "key"
INBOX_FILE = STATE / "inbox.json"   # before state.db: which reply files `wait` delivered; read once, by the import
DEFAULT_PORT = int(os.environ.get("BLUEDOC_PORT") or 8740)
UNLOCK_TTL = 24 * 3600   # seconds a one-time ?key= token stays good
COOKIE_AGE = 400 * 86400   # the key cookie's Max-Age: the most browsers keep; each page view renews it
SKIP_DIRS = {"node_modules", "build", "dist", "target", "out", "vendor", "Pods", "DerivedData", "__pycache__"}
MAX_DEPTH, MAX_BODY, SEARCH_CHARS = 8, 4 * 1024 * 1024, 8000   # SEARCH_CHARS keeps index.json small (~10 KB a doc)
KINDS = ("answers", "changes", "approval")
REPLY_SUFFIX = {"answers": "reply", "changes": "changes", "approval": "approval"}   # pre-state.db <stem>.<suffix>.md/.json
REPLY_ROUTES = {"/__bluedoc/reply": "answers", "/__bluedoc/changes": "changes", "/__bluedoc/approve": "approval"}
STATE_MAX_BODY, STATE_MAX_OPS, STATE_MAX_VALUE = 1024 * 1024, 2000, 64 * 1024
STATE_KEY = re.compile(r"^[a-z0-9_][a-z0-9:_-]*$")
LOCAL_KEYS = {"__outbox", "__imported"}   # the page's own bookkeeping: never sent, refused if it is
DB: "statedb.StateDB | None" = None   # opened by run()
SECRET = ""   # the key writes need, read by run()
TOKENS: dict[str, float] = {}   # one-time ?key= tokens: expiry (monotonic)
TOKENS_LOCK = threading.Lock()


# ---------- docs on disk ----------

def is_doc(p: Path) -> bool:
    return p.name.endswith(build.DOC_SUFFIXES)


DOC_FILES = " / ".join("*" + s for s in build.DOC_SUFFIXES)   # for messages


def reply_file(doc: Path, kind: str, ext: str) -> Path:
    return doc.with_name(f"{build.doc_stem(doc)}.{REPLY_SUFFIX[kind]}.{ext}")


def skill_version() -> str:
    """The plugin's version from its plugin.json, or '' for a skill installed without one."""
    root = HERE.parent.parent.parent
    for f in (root / ".claude-plugin" / "plugin.json", root / "plugin.json"):
        try:
            return str(json.loads(f.read_text(encoding="utf-8")).get("version") or "")
        except (OSError, ValueError, AttributeError):
            continue
    return ""


def code_hash() -> str:
    """Changes whenever the code a server renders with does: serve.py, statedb.py, build.py and the template."""
    h = hashlib.sha256()
    for f in (Path(__file__).resolve(), HERE / "statedb.py", HERE / "build.py", build.TEMPLATE):
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


VERSION, CODE_HASH = skill_version(), code_hash()
_doc_info: dict[str, tuple[tuple, list[Path], str | None, str | None, str]] = {}


def doc_info(p: Path) -> tuple[str | None, str | None, str]:
    """(build.approval_hash, doc.id, meta.rev as a string) of the doc, cached by the mtimes of the doc and its screen
    files; (None, None, '') if unreadable."""
    m = mtime(p)
    if not m:
        return None, None, ""
    hit = _doc_info.get(str(p))
    if hit and hit[0] == (m, *map(mtime, hit[1])):
        return hit[2:]
    screens: list[Path] = []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        screens = list(build.screen_paths(doc, p).values()) if isinstance(doc, dict) else []
        h = build.approval_hash(doc, p)
        did = (str(doc.get("id") or "") or None) if isinstance(doc, dict) else None
        rev = str(((doc.get("meta") or {}) if isinstance(doc, dict) else {}).get("rev") or "")
    except (OSError, ValueError, AttributeError):
        h, did, rev = None, None, ""
    _doc_info[str(p)] = ((m, *map(mtime, screens)), screens, h, did, rev)
    return h, did, rev


def doc_hash(p: Path) -> str | None:
    return doc_info(p)[0]


def info_key(p: Path) -> tuple:
    """The mtimes doc_info's cache keys on: the doc's and its screen files'."""
    doc_info(p)
    hit = _doc_info.get(str(p))
    return hit[0] if hit else ()


def doc_id(p: Path) -> str | None:
    return doc_info(p)[1]


def saved_approval(doc: Path) -> dict | None:
    """The doc's newest plan approval as {rev, at} (both as the page posted them), or None. It counts only while the
    doc's JSON is the one approved: an edit in place, even under the same meta.rev, asks for approval again."""
    row = DB.approval(str(doc.resolve())) if DB else None
    if not row or not row["doc_hash"] or row["doc_hash"] != doc_hash(doc):
        return None
    try:
        posted = json.loads(row["payload"])
    except ValueError:
        posted = {}
    return {"rev": posted.get("rev", row["rev"]), "at": posted.get("at", row["at"])}


# ---------- the key writes need ----------

def load_key(create: bool = False) -> str:
    """The server's key from KEY_FILE ('' without one); create makes it (mode 0600) when missing."""
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        if not create:
            return ""
    STATE.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(32)
    try:
        fd = os.open(KEY_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:   # another process made it first
        return KEY_FILE.read_text(encoding="utf-8").strip()
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key + "\n")
    return key


def mint_token() -> str:
    """A one-time ?key= token that sets the key cookie, good for UNLOCK_TTL seconds."""
    token, now = secrets.token_urlsafe(24), time.monotonic()
    with TOKENS_LOCK:
        for t in [t for t, end in TOKENS.items() if end < now]:
            del TOKENS[t]
        TOKENS[token] = now + UNLOCK_TTL
    return token


def take_token(token: str) -> bool:
    """Whether token is a live one-time token; it is used up either way."""
    with TOKENS_LOCK:
        end = TOKENS.pop(token, None)
    return end is not None and end >= time.monotonic()


def load_roots() -> list[Path]:
    try:
        roots = json.loads(ROOTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [Path(r) for r in roots if Path(r).is_dir()]


def save_roots(roots: list[Path]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    ROOTS_FILE.write_text(json.dumps([str(r) for r in roots], indent=1) + "\n", encoding="utf-8")


def add_root(d: Path) -> Path:
    """Register d unless it is, or is inside, a registered folder. A wider folder is added next to the narrower ones,
    which keep their slugs and so their URLs."""
    d = d.resolve()
    roots = load_roots()
    if not any(d == r or r in d.parents for r in roots):
        save_roots(roots + [d])
    return d


def root_for(doc: Path) -> Path:
    """The folder `open` registers: the topmost ancestor named docs, else the doc's folder."""
    doc = doc.resolve()
    named = [p for p in doc.parents if p.name in ("docs", "doc")]
    return named[-1] if named else doc.parent


def slugs(roots: list[Path]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for r in roots:
        base = r.parent.name if r.name in ("docs", "doc") and r.parent.name else r.name
        base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-") or "docs"
        s, n = base, 2
        while s in out:
            s, n = f"{base}-{n}", n + 1
        out[s] = r
    return out


def walk_docs(root: Path, skip: set[Path] | frozenset = frozenset()):
    """The docs under root, but not under the folders in skip (registered folders inside root, which list their own)."""
    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
                             and len(Path(dirpath, d).parts) - root_depth <= MAX_DEPTH and Path(dirpath, d) not in skip)
        for f in sorted(filenames):
            if f.endswith(build.DOC_SUFFIXES):
                yield Path(dirpath, f)


def inner_roots(r: Path, roots) -> set[Path]:
    """The registered folders inside r."""
    return {o for o in roots if r in o.parents}


def url_for(doc: Path) -> str | None:
    """The doc's URL under the deepest registered folder that holds it."""
    doc = doc.resolve()
    found = [(len(r.parts), slug, r) for slug, r in slugs(load_roots()).items() if r in doc.parents]
    if not found:
        return None
    _, slug, r = max(found)
    return f"/{quote(slug)}/{quote(doc.relative_to(r).as_posix())}"


def file_for_url(path: str) -> Path | None:
    """The file a /<root>/<path> URL names, if it exists inside that registered folder (after resolving
    .. and symlinks)."""
    parts = unquote(path).lstrip("/").split("/", 1)
    if len(parts) != 2 or "\0" in parts[1]:
        return None
    r = slugs(load_roots()).get(parts[0])
    if not r:
        return None
    p = (r / parts[1]).resolve()
    return p if r in p.parents and p.is_file() else None


def doc_for_url(path: str) -> Path | None:
    p = file_for_url(path)
    return p if p and is_doc(p) else None


def media_for_url(path: str) -> Path | None:
    """A media file under a registered folder, for a doc's relative `media` src."""
    p = file_for_url(path)
    return p if p and p.suffix.lower() in build.MEDIA_TYPES else None


def text_of(x, out: list[str], skip=("files", "code", "id", "href", "x", "y", "w", "h", "col", "row", "src")) -> None:
    if isinstance(x, dict):
        for k, v in x.items():
            if k not in skip:
                text_of(v, out)
    elif isinstance(x, list):
        for v in x:
            text_of(v, out)
    elif isinstance(x, str):
        out.append(x)


def scope_depth(scope: dict) -> int:
    """Levels of a canvas scope: 1, plus the deepest `children` below it."""
    kids = [n["children"] for n in scope.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("children"), dict)]
    return 1 + max((scope_depth(k) for k in kids), default=0)


def scope_flows(scope: dict) -> int:
    """Flows in a canvas scope and every scope nested in it."""
    kids = [n["children"] for n in scope.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("children"), dict)]
    return len(scope.get("flows") or []) + sum(scope_flows(k) for k in kids)


def canvas_card(canvas: dict) -> dict:
    nodes, at = [], {}
    for n in canvas["nodes"]:
        if not isinstance(n, dict) or "id" not in n:
            continue
        kids = len((n.get("children") or {}).get("nodes") or [])
        w, h = n.get("w") or (240 if kids else 180), n.get("h") or (140 if kids else 80)
        cx = n["x"] if n.get("x") is not None else (n.get("col") or 0) * 250
        cy = n["y"] if n.get("y") is not None else (n.get("row") or 0) * 160
        at[n["id"]] = len(nodes)
        node = {"x": round(cx - w / 2), "y": round(cy - h / 2), "w": round(w), "h": round(h), "label": str(n.get("label") or "")[:40]}
        node.update({k: n[k] for k in ("kind", "state") if n.get(k)})
        if kids:
            node["c"] = kids
        nodes.append(node)
    edges, edge_at = [], {}
    for e in canvas.get("edges") or []:
        if isinstance(e, dict) and e.get("from") in at and e.get("to") in at:
            edge_at[str(e.get("id") or f"{e['from']}->{e['to']}")] = len(edges)
            edges.append([at[e["from"]], at[e["to"]], e.get("kind") or ""])
    play: list[int] = []
    flow = next((f for f in canvas.get("flows") or [] if isinstance(f, dict)), None)
    for step in (flow or {}).get("steps") or []:
        if isinstance(step, dict):
            for eid in ([step["edge"]] if step.get("edge") else []) + list(step.get("edges") or []):
                i = edge_at.get(str(eid))
                if i is not None and i not in play:
                    play.append(i)
    out = {"nodes": nodes, "edges": edges, "levels": scope_depth(canvas), "flows": scope_flows(canvas)}
    if play:
        out["play"] = play
    return out


def card(doc: dict, dtype: str, doc_path: Path) -> dict:
    """What the home card's hero draws, and nothing else, so the index stays small.
    review: add, del, files, prs, findings = {blocker, major, minor, nit}, from the expanded diffs (cache and local
    git only, never gh). plan: steps = [status, effort] per step (first 24); files = counts per action (move counts
    as rename); decisions = {total, decided} over decision items, decided only when the author carried picks over.
    docs: kind, levels, flows and the first canvas's root drawing: nodes with x, y = top-left in canvas units, placed
    as the template does (centre = x/y, else col*250, row*160; size w/h, else 180x80, or 240x140 for a node with
    children), c = child count; edges = [from, to, kind] by node index; play = the edges the first root flow walks.
    design: count = artboards, artboards = the first 12 as {x, y, w, h, device, fidelity}, placed by
    build.board_layout and shifted so the board's top-left is 0, 0.
    A doc whose type has none of that: its `hero`, else {icon: 'doc', sections: N}."""
    blocks = list(build.all_blocks(doc))
    if dtype == "review":
        diffs = [b for b in blocks if b.get("type") == "diff"]
        if diffs:
            import diffref   # noqa: PLC0415 (lazy: the index only needs it for reviews)
            if any(diffref.is_ref(b) for b in diffs):
                expanded, _ = diffref.expanded_copy(doc, doc_path, allow_remote=False)
                diffs = [b for b in build.all_blocks(expanded) if b.get("type") == "diff"]
            add = dele = files = 0
            for f in (f for b in diffs for f in b.get("files") or [] if isinstance(f, dict) and f.get("status") != "context"):
                n_add, n_del = f.get("add"), f.get("del")
                if n_add is None or n_del is None:
                    lines = [ln for hk in f.get("hunks") or [] if not hk.get("context") for ln in hk.get("lines") or []]
                    n_add, n_del = sum(ln.startswith("+") for ln in lines), sum(ln.startswith("-") for ln in lines)
                add, dele, files = add + int(n_add), dele + int(n_del), files + 1
            findings = {k: 0 for k in build.FINDING_SIZES}
            for b in blocks:
                if b.get("type") == "checklist":
                    for it in b.get("items") or []:
                        if isinstance(it, dict) and it.get("state") in findings:
                            findings[it["state"]] += 1
            prs = len({str(d.get("pr") or d.get("id") or i) for i, d in enumerate(diffs)})
            return {"add": add, "del": dele, "files": files, "prs": prs, "findings": findings}
    elif dtype == "plan":
        steps = [[str(it.get("status") or "todo"), str(it.get("effort") or "")]
                 for b in blocks if b.get("type") == "steps" for it in b.get("items") or [] if isinstance(it, dict)]
        actions: dict[str, str] = {}
        for b in blocks:
            if b.get("type") == "files":
                for f in b.get("items") or []:
                    if isinstance(f, dict) and f.get("path"):
                        actions[str(f["path"])] = "rename" if f.get("action") == "move" else str(f.get("action") or "")
        if steps or actions:
            decisions = [it for b in blocks if b.get("type") == "checklist" for it in b.get("items") or []
                         if isinstance(it, dict) and it.get("choices")]
            dec: dict = {"total": len(decisions)}
            decided = sum(1 for it in decisions if it.get("choice"))
            if decided:
                dec["decided"] = decided
            return {"steps": steps[:24], "files": {k: sum(a == k for a in actions.values()) for k in ("add", "edit", "delete", "rename")},
                    "decisions": dec}
    elif dtype == "docs":
        canvas = next((b for b in blocks if b.get("type") == "canvas" and b.get("nodes")), None)
        if canvas:
            return {"kind": str((doc.get("meta") or {}).get("kind") or ""), **canvas_card(canvas)}
    elif dtype == "design":
        board = build.board_of(doc)
        layout = build.board_layout(board) if board else {}
        if layout:
            x0, y0 = min(v[0] for v in layout.values()), min(v[1] for v in layout.values())
            info = {a["id"]: a for a in board.get("artboards") or [] if isinstance(a, dict)}
            arts = []
            for aid, (x, y, w, h) in list(layout.items())[:12]:
                a = info.get(aid) or {}
                arts.append({"x": round(x - x0), "y": round(y - y0), "w": round(w), "h": round(h),
                             "device": str(a.get("device") or ""), "fidelity": str(a.get("fidelity") or "")})
            return {"count": len(layout), "artboards": arts}
    hero = doc.get("hero")
    if isinstance(hero, dict) and hero.get("value") is not None:
        return {"hero": {k: str(hero[k]) for k in ("icon", "value", "label") if hero.get(k) is not None}}
    return {"icon": "doc", "sections": len(doc.get("sections") or [])}


_cache: dict[str, tuple[tuple, dict]] = {}
_hist_cache: dict[str, tuple[float, tuple[int, list[int]]]] = {}


def history_info(p: Path) -> tuple[int, list[int]]:
    """(revision count, when each revision was built as epoch seconds) from the doc's history file."""
    hp = build.history_path(p)
    try:
        m = hp.stat().st_mtime
    except OSError:
        return 0, []
    hit = _hist_cache.get(str(hp))
    if hit and hit[0] == m:
        return hit[1]
    try:
        revs = json.loads(hp.read_text(encoding="utf-8")).get("revs") or []
        built = []
        for r in revs:
            try:
                built.append(int(dt.datetime.fromisoformat(r["built"]).timestamp()))
            except (KeyError, TypeError, ValueError):
                pass
        res = (len(revs), built)
    except (OSError, ValueError, AttributeError):
        res = (0, [])
    _hist_cache[str(hp)] = (m, res)
    return res


def mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def summarize(p: Path) -> dict:
    """What the home page needs about one doc, cached by the mtimes of the doc, its screen files (a design's lint and
    card), its history (a contract problem is an error only while meta.rev is new) and its diff cache (a review
    card's line counts)."""
    import diffref   # noqa: PLC0415
    st = p.stat()
    keyed = lambda: (st.st_mtime, info_key(p), mtime(build.history_path(p)), mtime(diffref.cache_path(p)))  # noqa: E731
    key = keyed()
    hit = _cache.get(str(p))
    if hit and hit[0] == key:
        info = dict(hit[1])
    else:
        info = {"title": build.doc_stem(p), "errors": 0}
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            rep = build.validate(doc, p)
            meta = doc.get("meta") or {}
            dtype = build.doc_type(meta)
            items = []

            def scan(blocks):
                for b in blocks or []:
                    if b.get("type") == "checklist":
                        for it in b.get("items") or []:
                            dec = bool(it.get("choices"))
                            items.append([b.get("id"), it.get("id"), 1 if dec else 0,
                                          (it.get("choice") or "") if dec else ("1" if it.get("done") else "0"),
                                          [c.get("id") for c in it.get("choices") or []] if dec else None])
                            scan(it.get("blocks"))
            for s in doc.get("sections") or []:
                scan(s.get("blocks"))
            words: list[str] = []
            text_of(doc, words)
            info.update({
                "id": doc.get("id"), "title": doc.get("title") or build.doc_stem(p), "subtitle": doc.get("subtitle") or "",
                "tldr": doc.get("tldr") or "", "kind": meta.get("kind") or "", "type": dtype, "org": meta.get("org") or "",
                "rev": str(meta.get("rev") or ""), "date": meta.get("date") or "",
                "sections": [s.get("title") or "" for s in doc.get("sections") or []],
                "items": items, "errors": len(rep.errors), "firstError": rep.errors[0] if rep.errors else "",
                "text": " ".join(words)[:SEARCH_CHARS], "card": card(doc, dtype, p),
            })
        except (OSError, ValueError, TypeError, AttributeError) as e:
            info.update({"errors": 1, "firstError": f"cannot read: {e}", "type": "other"})
        # the card may just have written the diff cache: key on the files as they are now
        _cache[str(p)] = (keyed(), info)
        info = dict(info)
    info["mtime"] = st.st_mtime
    info["revs"], info["built"] = history_info(p)
    if DB:
        path = str(p.resolve())
        for kind, row in DB.latest(path).items():
            if kind == "approval" and saved_approval(p) is None:   # approved other content of this doc: awaiting again
                continue
            info[kind] = {"at": dt.datetime.fromisoformat(row["at"]).timestamp(), "rev": row["rev"]}
        # the home card's progress: the reader's tick and pick values (<checklist>:<item>), {} when there are none
        info["state"] = {k: v for k, v in DB.state(path)[1].items() if k.count(":") == 1 and not k.startswith("__")}
    return info


def index() -> dict:
    out = []
    roots = slugs(load_roots())
    for slug, r in roots.items():
        docs = []
        for p in walk_docs(r, inner_roots(r, roots.values())):
            try:
                d = summarize(p)
            except OSError:
                continue
            d["path"] = p.relative_to(r).as_posix()
            d["url"] = f"/{quote(slug)}/{quote(d['path'])}"
            docs.append(d)
        name = r.parent.name if r.name in ("docs", "doc") and r.parent.name else r.name
        out.append({"slug": slug, "name": name, "path": str(r), "docs": docs})
    return {"roots": out}


# ---------- rendering ----------

def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def template_css() -> str:
    t = build.TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"<style>(.*?)</style>", t, re.S)
    return m.group(1) if m else ""


def vendor_file(rel: str) -> Path | None:
    base = VENDOR.resolve()
    f = (base / unquote(rel)).resolve()
    return f if base in f.parents and f.is_file() else None


def vendor_type(f: Path) -> str:
    ext = f.suffix.lower()
    if ext in (".js", ".mjs"):
        return "text/javascript; charset=utf-8"
    if ext == ".css":
        return "text/css; charset=utf-8"
    if ext in ("", ".md", ".txt"):
        return "text/plain; charset=utf-8"   # LICENSE, NOTICE, VERSION
    return mimetypes.guess_type(f.name)[0] or "application/octet-stream"


def vendor_version() -> str:
    """Changes whenever a vendored file does, so the home page can cache them forever."""
    try:
        return str(int(max(f.stat().st_mtime for f in VENDOR.rglob("*") if f.is_file())))
    except (OSError, ValueError):
        return "0"


def error_page(p: Path, lines: list[str]) -> str:
    items = "".join(f"<li><code>{esc(x)}</code></li>" for x in lines)
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><title>Errors · {esc(p.name)}</title>"
            f"<style>{template_css()}</style></head><body><main style='max-width:860px;margin:64px auto;padding:0 20px'>"
            f"<p><a href='/'>← All docs</a></p><h1 style='font:650 24px var(--sans)'>{esc(p.name)} doesn't build</h1>"
            f"<p style='color:var(--fg-muted)'>{esc(str(p))}</p><div class='bp-callout risk'><span class='lbl'>Fix these in the JSON, then reload</span>"
            f"<ul>{items}</ul></div></main></body></html>")


INLINE_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S | re.I)


def page_csp(html: str) -> str:
    """The page's Content-Security-Policy: its own inline scripts by hash (JSON data blocks don't run), same-origin
    files, data: images, media and fonts, and no framing."""
    hashes = sorted({"'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"
                     for attrs, body in INLINE_SCRIPT.findall(html)
                     if "src=" not in attrs and "application/json" not in attrs})
    return ("default-src 'self'; script-src " + " ".join(["'self'", *hashes]) + "; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; media-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def render(p: Path) -> tuple[int, str]:
    """(status, HTML) of the doc's page; any failure, even on JSON of the wrong shape, comes back as an error page."""
    try:
        return _render(p)
    except Exception as e:   # noqa: BLE001 — the page names the problem instead of the connection dropping
        return 422, error_page(p, [f"cannot render: {type(e).__name__}: {e}"])


def _render(p: Path) -> tuple[int, str]:
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return 500, error_page(p, [f"cannot read: {e}"])
    shown = build.approval_hash(doc, p)   # the JSON (and screen files) this page shows, which an approval must match
    # validate expands diff refs on a copy (cache, local git, then gh) and so warms the cache build.build reads;
    # it also applies the type contract, as errors only while meta.rev is new
    rep = build.validate(doc, p, allow_remote=True)
    if rep.errors:
        return 422, error_page(p, rep.errors)
    history = None
    if (doc.get("meta") or {}).get("rev"):
        # the page shows the doc as the history's latest revision, in memory: only build.py writes the history file
        try:
            history = build.load_history(build.history_path(p))
        except (OSError, ValueError) as e:
            return 422, error_page(p, [f"cannot read {build.history_path(p)}: {e}"])
        log = build.record(history, doc, p)
        if log.startswith("ERROR"):
            return 422, error_page(p, [log])
    # the history keeps refs; build expands them in the page's doc and in older revisions. validate already showed
    # the doc's own expansion errors; an older revision whose range is gone shows an empty diff
    state = page_state(p)
    return 200, build.build(doc, build.TEMPLATE.read_text(encoding="utf-8"), history, diff_path=p, problems=[],
                            state=state and {**state, "docHash": shown})


# ---------- design screens ----------

# /<root>/<dir>/<stem>.design/<artboard id>.html: one artboard's screen fragment wrapped in its kit
SCREEN_URL = re.compile(r"^(/(?:[^/]+/)+)([^/]+)\.design/([a-z0-9][a-z0-9-]*)\.html$")
# what kits, declared framework files, their url() targets and store copies may be: nothing that renders as a page
ASSET_TYPES = {".css", ".js", ".mjs", ".woff", ".woff2", ".ttf", ".otf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
CORS_TYPES = {".mjs", ".woff", ".woff2", ".ttf", ".otf"}   # fetched in CORS mode: an opaque-origin frame needs ACAO *
CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""")
EXTERNAL_REF = re.compile(r"(?i)^(?:data:|[a-z][a-z0-9+.-]*:|//|#)")
PLAIN_KIT = ("base.css", "wireframe.css")
HORIZON_KIT = ("horizon-ui/horizon-ui.css", "horizon-ui/react.js", "horizon-ui/horizon-ui.js")
MOTION_VARS = {"fast": "--dur-fast", "base": "--dur-base", "slow": "--dur-slow", "ease": "--ease"}


def screen_csp(host: str) -> str:
    """A screen's Content-Security-Policy: no network, no forms, framed only by this server's pages, and sandboxed
    even when opened on its own. The explicit origin backs 'self', which browsers read differently in an
    opaque-origin document; host is one guard() accepted."""
    o = f"http://{host}"
    return (f"default-src 'none'; script-src 'self' {o} 'unsafe-inline'; style-src 'self' {o} 'unsafe-inline'; "
            f"img-src 'self' {o} data: blob:; font-src 'self' {o} data:; connect-src 'none'; form-action 'none'; "
            f"base-uri 'none'; frame-ancestors 'self' {o}; sandbox allow-scripts")


def kit_version() -> str:
    """Changes whenever a kit file does, so screens can cache kits forever."""
    try:
        return str(int(max(f.stat().st_mtime for f in KITS.iterdir() if f.is_file())))
    except (OSError, ValueError):
        return "0"


def asset_kind(f: Path) -> str:
    return {".css": "css", ".mjs": "mjs"}.get(f.suffix.lower(), "js")


def kit_file(rel: str) -> Path | None:
    """A kit file (CSS or JS) under assets/kits, for /__bluedoc/kit/."""
    base = KITS.resolve()
    f = (base / unquote(rel)).resolve()
    return f if base in f.parents and f.is_file() and f.suffix.lower() in ASSET_TYPES else None


def store_file(rel: str) -> Path | None:
    """A file of a framework `add-framework` copied, for /__bluedoc/fw/<name>/<path>."""
    base = build.frameworks_dir().resolve()
    f = (base / unquote(rel)).resolve()
    return (f if base in f.parents and len(f.relative_to(base).parts) > 1 and f.is_file() and f.suffix.lower() in ASSET_TYPES
            else None)


def store_manifest(name: str) -> dict | None:
    """The store copy's manifest when every file it loads is there, else None (the screen falls back)."""
    if not isinstance(name, str) or not build.ID_RE.match(name):
        return None
    d = build.frameworks_dir() / name
    try:
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    files = [*(m.get("load") or []), *(m.get("sources") or [])] if isinstance(m, dict) else None
    if not files or not all(isinstance(f, str) and store_file(f"{name}/{f}") for f in files):
        return None
    return m


def under_roots(p: Path, roots: list[Path]) -> bool:
    return any(r in p.parents for r in roots)


def css_refs(css: Path, roots: list[Path]) -> set[Path]:
    """The files a CSS file's relative url()s name, under a registered folder and of an asset type."""
    try:
        text = css.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    out = set()
    for m in CSS_URL.finditer(text):
        ref = m[2].strip()
        if EXTERNAL_REF.match(ref):
            continue
        p = (css.parent / unquote(ref.split("#")[0].split("?")[0])).resolve()
        if p.suffix.lower() in ASSET_TYPES and under_roots(p, roots) and p.is_file():
            out.add(p)
    return out


_declared: dict[str, tuple[tuple, list[Path], set[Path]]] = {}


def declared_files(doc_path: Path) -> set[Path]:
    """The project files a design doc's board declares (frameworks[].files) and the url() targets of its declared
    CSS: what the server may send to its screens. Cached by the mtimes of the doc and of that CSS."""
    m = mtime(doc_path)
    hit = _declared.get(str(doc_path))
    if hit and hit[0] == (m, *map(mtime, hit[1])):
        return hit[2]
    files: set[Path] = set()
    css: list[Path] = []
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = None
    board = build.board_of(doc) if isinstance(doc, dict) else None
    roots = load_roots()
    for fw in (board or {}).get("frameworks") or []:
        for f in (fw.get("files") or []) if isinstance(fw, dict) else []:
            if not isinstance(f, str):
                continue
            p = (doc_path.parent / f).resolve()
            if p.suffix.lower() in build.FRAMEWORK_EXTS and under_roots(p, roots) and p.is_file():
                files.add(p)
                if p.suffix.lower() == ".css":
                    css.append(p)
                    files |= css_refs(p, roots)
    _declared[str(doc_path)] = ((m, *map(mtime, css)), css, files)
    return files


def declared_for_url(path: str) -> Path | None:
    """A file under a registered folder that some design doc's board declares, for that doc's screens. Docs seen
    before are checked first; a miss scans every doc under the registered folders."""
    p = file_for_url(path)
    if not p or p.suffix.lower() not in ASSET_TYPES:
        return None
    if any(p in declared_files(Path(d)) for d in list(_declared)):
        return p
    roots = slugs(load_roots())
    for r in roots.values():
        for d in walk_docs(r, inner_roots(r, roots.values())):
            if str(d) not in _declared and p in declared_files(d):
                return p
    return None


def framework_assets(board: dict, fw_id: str, doc_path: Path, fidelity: str) -> tuple[list, list[Path] | None, str | None]:
    """(assets in load order, the Tailwind sources the frame compiles (None without the Tailwind compiler), the label
    of a framework that's missing).
    plain and horizon ship; a frameworks[] entry loads its declared files or its store copy. When any of that is
    missing, the screen gets the plain kit and the label for its notice."""
    kit = lambda name: (asset_kind(KITS / name), KITS / name, f"/__bluedoc/kit/{name}?v={kit_version()}")  # noqa: E731
    plain = [kit(n) for n in PLAIN_KIT]
    if fw_id == "plain":
        return plain, None, None
    wire = [kit("wireframe.css")] if fidelity in ("wireframe", "sketch") else []
    if fw_id == "horizon":
        v = vendor_version()
        return [(asset_kind(VENDOR / r), VENDOR / r, f"/__bluedoc/vendor/{r}?v={v}") for r in HORIZON_KIT] + wire, None, None
    entry = next((f for f in board.get("frameworks") or [] if isinstance(f, dict) and f.get("id") == fw_id), None)
    label = str((entry or {}).get("label") or fw_id)
    if entry and isinstance(entry.get("store"), str):
        man = store_manifest(entry["store"])
        if man:
            d, v = build.frameworks_dir() / entry["store"], str(man.get("sha256") or "")[:12]
            assets = [(asset_kind(d / f), d / f, f"/__bluedoc/fw/{quote(entry['store'])}/{quote(f)}?v={v}") for f in man["load"]]
            sources = [d / f for f in man.get("sources") or []] if man.get("compiler") == "tailwind" else None
            return assets + wire, sources, None
    elif entry and isinstance(entry.get("files"), list) and entry["files"]:
        roots, assets = load_roots(), []
        for f in entry["files"]:
            p = (doc_path.parent / f).resolve() if isinstance(f, str) else None
            url = url_for(p) if p and p.suffix.lower() in build.FRAMEWORK_EXTS and under_roots(p, roots) and p.is_file() else None
            if not url:
                break
            assets.append((asset_kind(p), p, f"{url}?v={int(mtime(p))}"))
        else:
            return assets + wire, None, None
    return plain, None, label


def token_ok(k, v) -> bool:
    return (isinstance(k, str) and bool(build.TOKEN_KEY.match(k)) and isinstance(v, str) and len(v) <= 200
            and bool(build.TOKEN_VALUE.match(v)) and "url(" not in v.lower())


def brief_pick(doc: dict, item_id: str) -> str | None:
    """The brief's pick for a decision item: its choice, else its recommendation."""
    for b in build.all_blocks(doc):
        if b.get("type") == "checklist":
            for it in b.get("items") or []:
                if isinstance(it, dict) and it.get("id") == item_id and it.get("choices"):
                    return it.get("choice") or it.get("recommend")
    return None


def screen_vars(doc: dict, board: dict, a: dict, theme: str | None) -> str:
    """The :root declarations a screen starts with: the device's size and safe area, the theme's tokens (theme, else
    the brief's pick, else the first theme) and the board's motion tokens."""
    dev = build.DEVICES.get(a.get("device")) if isinstance(a.get("device"), str) else None
    w, h = build.artboard_size(a) or (0, 0)
    top, right, bottom, left = dev["safe"] if dev else (0, 0, 0, 0)
    out = {"--screen-w": f"{w:g}px", "--screen-h": f"{h:g}px", "--safe-top": f"{top}px", "--safe-right": f"{right}px",
           "--safe-bottom": f"{bottom}px", "--safe-left": f"{left}px"}
    if a.get("device") == "watch-round":   # the inscribed square's inset from the edge: d * (1 - 1/sqrt(2)) / 2
        out["--safe-inset"] = f"{round(w * (1 - 0.5 ** 0.5) / 2)}px"
    themes = {t["id"]: t for t in board.get("themes") or [] if isinstance(t, dict) and isinstance(t.get("id"), str)}
    t = themes.get(theme or "") or themes.get(brief_pick(doc, "theme") or "") or next(iter(themes.values()), None)
    tokens = (t or {}).get("tokens")
    for k, v in (tokens.items() if isinstance(tokens, dict) else ()):
        if token_ok(k, v):
            out["--" + k] = v
    motion = board.get("motion")
    for k, v in (motion.items() if isinstance(motion, dict) else ()):
        if k in MOTION_VARS and token_ok("x", v):
            out[MOTION_VARS[k]] = v
    return " ".join(f"{k}: {v};" for k, v in out.items())


def data_uri(f: Path) -> str:
    return f"data:{vendor_type(f).split(';')[0]};base64,{base64.b64encode(f.read_bytes()).decode()}"


def inline_css(f: Path) -> str:
    """A CSS file's text with its relative url()s as data: URIs, for a screen with its kit inlined."""
    def sub(m):
        ref = m[2].strip()
        if EXTERNAL_REF.match(ref):
            return m[0]
        t = (f.parent / unquote(ref.split("#")[0].split("?")[0])).resolve()
        ok = t.suffix.lower() in ASSET_TYPES and t.is_file() and t.stat().st_size <= build.MAX_MEDIA_BYTES
        return f'url("{data_uri(t)}")' if ok else m[0]
    return CSS_URL.sub(sub, f.read_text(encoding="utf-8", errors="replace"))


def raw_text(text: str, tag: str) -> str:
    """text made safe inside <style> or <script>: it can't close the element or open a comment there."""
    return re.sub(rf"(?i)</({tag})", r"<\\/\1", text).replace("<!--", "<\\!--")


def asset_tag(kind: str, f: Path, url: str, inline: bool) -> str:
    if kind == "css":
        return f"<style>{raw_text(inline_css(f), 'style')}</style>" if inline else f'<link rel="stylesheet" href="{esc(url)}">'
    typ = ' type="module"' if kind == "mjs" else ""
    if inline:
        return f"<script{typ}>{raw_text(f.read_text(encoding='utf-8', errors='replace'), 'script')}</script>"
    return f'<script{typ} src="{esc(url)}"></script>'


def wrap_screen(doc: dict, doc_path: Path, artboard_id: str, fragment: str, *, inline: bool = False,
                theme: str | None = None) -> str:
    """A screen as a whole HTML document: kits/shell.html filled with the artboard's framework (or the plain kit and
    a notice when it's missing), its fidelity, the device's and theme's variables, the inspector, then the fragment.
    inline puts every file in the document (an -o file); else they load from this server. KeyError: no such artboard."""
    board = build.board_of(doc) or {}
    a = next((x for x in board.get("artboards") or [] if isinstance(x, dict) and x.get("id") == artboard_id), None)
    if a is None:
        raise KeyError(artboard_id)
    fidelity = a.get("fidelity") if a.get("fidelity") in build.FIDELITIES else "hifi"
    fw_id = str(a.get("framework") or board.get("framework") or "plain")
    assets, sources, missing = framework_assets(board, fw_id, Path(doc_path), fidelity)
    head = [asset_tag(kind, f, url, inline) for kind, f, url in assets]
    if sources is not None:
        text = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in sources)
        if '@import "tailwindcss"' not in text:
            text = '@import "tailwindcss";\n' + text
        head.append(f'<style type="text/tailwindcss">{raw_text(text, "style")}</style>')
    inspector = KITS / "inspector.js"
    slots = {
        "html_class": f"fid-{fidelity}", "artboard": esc(artboard_id), "fallback": esc(missing or ""),
        "title": esc(str(a.get("title") or artboard_id)), "vars": screen_vars(doc, board, a, theme),
        "hand_font": data_uri(HAND_FONT) if inline else f"/__bluedoc/vendor/fonts/{HAND_FONT.name}?v={vendor_version()}",
        "inspector": asset_tag("js", inspector, f"/__bluedoc/kit/inspector.js?v={kit_version()}", inline),
        "head": "\n".join(head),
        "notice": f'<div id="bd-notice" role="status">{esc(missing)} not found: showing the plain kit</div>\n' if missing else "",
        "body": fragment,
    }
    shell = (KITS / "shell.html").read_text(encoding="utf-8")
    return re.sub(r"\{\{(\w+)\}\}", lambda m: slots[m[1]], shell)   # one pass: the fragment's own {{ }} stay as written


def screen_for_url(path: str, rev: str | None) -> tuple[Path, dict, str, str] | None:
    """(doc file, the doc as of rev, artboard id, fragment) for a screen URL; None unless the doc is a design doc
    under a registered folder with that artboard and its screen file (or that revision's recorded HTML)."""
    m = SCREEN_URL.match(path)
    if not m:
        return None
    doc_path = next((d for d in (doc_for_url(m[1] + m[2] + s) for s in build.DOC_SUFFIXES) if d), None)
    if not doc_path:
        return None
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    aid = m[3]
    if not isinstance(doc, dict):
        return None
    if rev:
        try:
            h = build.load_history(build.history_path(doc_path))
            entry = next((e for e in h["revs"] if isinstance(e, dict) and e.get("rev") == rev), None)
            doc = build.restore(h, entry) if entry else None
        except (OSError, ValueError, KeyError, TypeError):
            return None
        fragment = build.screen_source(doc_path, aid, rev) if doc else None
    else:
        f = build.screen_paths(doc, doc_path).get(aid)
        fragment = None
        if f and f.resolve().parent.name.endswith(".design") and under_roots(f.resolve(), load_roots()):
            try:
                fragment = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass
    board = build.board_of(doc) if isinstance(doc, dict) else None
    if fragment is None or not board or not any(isinstance(a, dict) and a.get("id") == aid for a in board.get("artboards") or []):
        return None
    return doc_path, doc, aid, fragment



# ---------- reader state ----------

ANN_TYPES = ("pin", "text", "draw", "general")
_skipped: set[tuple[str, str]] = set()   # (doc, key) of stored values page_state left out and logged


def _target_ok(t) -> bool:
    return (isinstance(t, dict) and isinstance(t.get("key"), str) and bool(t["key"]) and isinstance(t.get("label"), str)
            and (t.get("text") is None or isinstance(t["text"], str)))


def value_ok(key: str, value: str) -> bool:
    """False for an `__ann:<id>` value the page can't draw (template.html's MARKUP `valid`); True for any other key."""
    if not key.startswith("__ann:"):
        return True
    try:
        a = json.loads(value)
    except ValueError:
        return False
    return (isinstance(a, dict) and a.get("id") == key[len("__ann:"):] and a.get("type") in ANN_TYPES
            and _target_ok(a.get("target"))
            and (a.get("targets") is None or isinstance(a["targets"], list) and all(map(_target_ok, a["targets"])))
            and (a.get("type") != "text" or isinstance(a.get("quote"), str))
            and (a.get("note") is None or isinstance(a["note"], str)) and (a.get("up") is None or isinstance(a["up"], list))
            and (a.get("strokes") is None or isinstance(a["strokes"], list))
            and (a.get("pos") is None or isinstance(a["pos"], dict)))


def page_state(p: Path) -> dict | None:
    """The doc's reader state {version, state}, or None without sqlite3. A stored value the page can't use (one an
    earlier version let in) is left out, and logged once, so it can't stop the page on every load."""
    if not DB:
        return None
    path = str(p.resolve())
    version, state = DB.state(path)
    for k in [k for k, v in state.items() if not value_ok(k, v)]:
        del state[k]
        if (path, k) not in _skipped:
            _skipped.add((path, k))
            print(f"left out the stored value {k} of {p}: the page can't use it", flush=True)
    return {"version": version, "state": state}


def checklist_items(doc: dict) -> set[str]:
    """'<checklist>:<item>' for every checklist item in the doc: the keys an import may keep."""
    return {f"{b.get('id')}:{it.get('id')}" for b in build.all_blocks(doc) if b.get("type") == "checklist"
            for it in b.get("items") or [] if isinstance(it, dict)}


def state_ops(data: dict) -> list[tuple[str, str | None]]:
    """The PUT body's ops as [(key, value or None)]; ValueError names the first bad one."""
    ops = data.get("ops")
    if not isinstance(ops, list) or len(ops) > STATE_MAX_OPS:
        raise ValueError(f"ops must be a list of at most {STATE_MAX_OPS} [key, value] pairs")
    out = []
    for op in ops:
        if not (isinstance(op, list) and len(op) == 2 and isinstance(op[0], str)):
            raise ValueError(f"bad op {str(op)[:80]!r}: want [key, value]")
        key, value = op
        if not STATE_KEY.match(key) or key in LOCAL_KEYS:
            raise ValueError(f"bad key {key[:80]!r}")
        if value is not None and (not isinstance(value, str) or len(value.encode("utf-8")) > STATE_MAX_VALUE):
            raise ValueError(f"the value of {key!r} must be a string of at most {STATE_MAX_VALUE // 1024} KB, or null")
        out.append((key, value))
    return out


# ---------- inbox: replies the agent waits for ----------

def reply_message(row: dict) -> dict:
    """What `wait` returns for a replies row."""
    return {k: row[k] for k in ("id", "kind", "doc", "rev", "at", "markdown")}


def import_reply_files(roots: list[Path]) -> int:
    """A new state.db takes in the reply files earlier versions wrote next to docs under roots, oldest first, and
    leaves them in place; the count. inbox.json's marks say which ones `wait` delivered; without inbox.json every
    one counts as delivered, as the first start of those versions took them."""
    try:
        seen = json.loads(INBOX_FILE.read_text(encoding="utf-8"))
        seen = seen if isinstance(seen, dict) else None
    except (OSError, ValueError):
        seen = None
    found = []
    for r in roots:
        for doc in walk_docs(r, inner_roots(r, roots)):
            for kind in KINDS:
                f = reply_file(doc, kind, "json")
                if f.is_file():
                    found.append((f.stat().st_mtime, str(doc), kind, f))
    n = 0
    for m, doc, kind, f in sorted(found):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            md_file = reply_file(Path(doc), kind, "md")
            md = md_file.read_text(encoding="utf-8") if md_file.is_file() else ""
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        at = dt.datetime.fromtimestamp(m).astimezone().isoformat(timespec="seconds")
        mark = None if seen is None else seen.get(str(f), seen.get(str(f.resolve())))
        delivered = at if seen is None or (isinstance(mark, (int, float)) and mark >= m) else None
        DB.add_reply(str(Path(doc).resolve()), doc_id(Path(doc)), kind, str(data.get("rev") or ""),
                     json.dumps(data, ensure_ascii=False), md or str(data.get("markdown") or ""),
                     doc_hash=data.get("docHash") if kind == "approval" else None, at=at, delivered=delivered)
        n += 1
    return n


class Inbox:
    """Replies `wait` takes: rows in state.db, queued until `wait` returns them, so a restart keeps the queue."""
    def __init__(self) -> None:
        self.cv = threading.Condition()
        self.names: dict[str, str] = {}

    def put(self, doc: Path, kind: str, data: dict, markdown: str) -> int:
        """Store a reply for doc; its id."""
        with self.cv:
            rid = DB.add_reply(str(doc), doc_id(doc), kind, str(data.get("rev") or ""), json.dumps(data, ensure_ascii=False),
                               markdown, doc_hash=data.get("docHash") if kind == "approval" else None)
            self.cv.notify_all()
            return rid

    def take(self, doc: str, kind: str, timeout: float) -> dict | None:
        end = time.monotonic() + timeout
        with self.cv:
            while True:
                queued = DB.undelivered(doc, kind) if DB else []
                if queued:
                    DB.mark_delivered(queued[0]["id"])
                    return reply_message(queued[0])
                left = end - time.monotonic()
                if left <= 0:
                    return None
                self.cv.wait(left)


INBOX = Inbox()


# ---------- HTTP ----------

def make_handler(port: int, default_to: str):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    cookie = f"bluedoc_key_{port}"   # cookies ignore the port: name it so servers on other ports keep their own
    set_cookie = lambda: f"{cookie}={SECRET}; Path=/; Max-Age={COOKIE_AGE}; HttpOnly; SameSite=Strict"  # noqa: E731

    class H(BaseHTTPRequestHandler):
        server_version = "bluedoc"

        def log_message(self, *_):
            pass

        def send(self, code: int, body: str | bytes, ctype: str = "text/html; charset=utf-8", cache: str = "no-store",
                 headers: dict[str, str] | None = None, framed: bool = False) -> None:
            """framed: a design screen, which brings its own CSP in headers and may be framed by our pages."""
            data = body.encode() if isinstance(body, str) else body
            if ctype.startswith("text/html") and not framed:
                headers = {"Content-Security-Policy": page_csp(data.decode("utf-8", "replace")), "X-Frame-Options": "DENY", **(headers or {})}
                if self.cookie_key() and self.has_key():   # each page view keeps the cookie alive another COOKIE_AGE
                    headers["Set-Cookie"] = set_cookie()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def asset(self, f: Path, q: dict) -> None:
            """A vendored, kit, store or declared framework file. Versioned URLs (?v=) are immutable: their v changes
            with the files. Fonts and modules are CORS fetches, which a screen's opaque origin makes cross-origin."""
            ext = f.suffix.lower()
            extra = {"Access-Control-Allow-Origin": "*"} if ext in CORS_TYPES else {}
            if ext == ".svg":   # opened on its own, it must not run script on this origin
                extra["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
            self.send(200, f.read_bytes(), vendor_type(f), "public, max-age=31536000, immutable" if q.get("v") else "no-cache", extra)

        def screen(self, path: str, q: dict) -> None:
            """A design screen: its fragment wrapped in its kit, sandboxed by its CSP, framable by our pages only."""
            found = screen_for_url(path, q.get("rev") or None)
            if not found:
                return self.send(404, "<!doctype html><title>Not found</title><p>No screen at this address. <a href='/'>All docs</a></p>")
            doc_path, doc, aid, fragment = found
            html = wrap_screen(doc, doc_path, aid, fragment, theme=q.get("theme") or None)
            return self.send(200, html, headers={"Content-Security-Policy": screen_csp(self.headers.get("Host") or "")}, framed=True)

        def send_media(self, f: Path) -> None:
            # one byte range at most: enough for <video> seeking (Safari won't play video without it)
            data, ctype = f.read_bytes(), build.MEDIA_TYPES[f.suffix.lower()]
            # an SVG opened on its own must not run script on this origin
            extra = {"Accept-Ranges": "bytes", "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"}
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
            if not m or not (m[1] or m[2]):
                return self.send(200, data, ctype, headers=extra)
            size = len(data)
            start, end = (int(m[1]), min(int(m[2]), size - 1) if m[2] else size - 1) if m[1] else (max(0, size - int(m[2])), size - 1)
            if start > end:
                return self.send(416, b"", ctype, headers={**extra, "Content-Range": f"bytes */{size}"})
            return self.send(206, data[start:end + 1], ctype, headers={**extra, "Content-Range": f"bytes {start}-{end}/{size}"})

        def json(self, code: int, obj) -> None:
            self.send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

        def cookie_key(self) -> str:
            try:
                c = SimpleCookie(self.headers.get("Cookie") or "")
            except CookieError:
                return ""
            return c[cookie].value if cookie in c else ""

        def has_key(self) -> bool:
            """Whether the request carries the server's key: in X-Bluedoc-Key (the CLI) or in the cookie (a browser
            that opened an `open`/`unlock` link)."""
            given = self.headers.get("X-Bluedoc-Key") or self.cookie_key()
            return bool(SECRET and given) and hmac.compare_digest(given.encode(), SECRET.encode())

        def guard(self) -> bool:
            # DNS rebinding: only our own host names; writes also need our header and origin, and the key
            if self.headers.get("Host") not in hosts:
                self.json(403, {"error": "bad host"})
                return False
            # the state routes carry the reader's input: the GET is guarded like the writes, as /wait is
            if self.command in ("POST", "PUT") or urlsplit(self.path).path == "/__bluedoc/state":
                origin = self.headers.get("Origin")
                if self.headers.get("X-Bluedoc") != "1" or (origin and urlsplit(origin).netloc not in hosts):
                    self.json(403, {"error": "missing X-Bluedoc header or cross-origin"})
                    return False
            if self.command in ("POST", "PUT") and not self.has_key():
                self.no_key()
                return False
            return True

        def no_key(self) -> None:
            self.json(403, {"error": "this browser can't save here yet: run `serve.py unlock` (or `serve.py open DOC`) "
                                     "and open the link it prints", "key": True})

        def unlock(self, u) -> None:
            """A ?key= link: a live one-time token sets the key cookie; either way, go to the URL without it."""
            ok = take_token(parse_qs(u.query).get("key", [""])[0])
            rest = urlencode([(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k != "key"])
            self.send_response(303)
            self.send_header("Location", u.path + ("?" + rest if rest else ""))
            if ok:
                self.send_header("Set-Cookie", set_cookie())
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def body(self, limit: int) -> dict | None:
            """The request's JSON object, or None after answering 413 or 400."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n < 0:
                    raise ValueError
            except ValueError:
                self.json(400, {"error": "bad Content-Length"})
                return None
            if not 0 < n <= limit:
                self.json(413, {"error": "empty or too large"})
                return None
            try:
                data = json.loads(self.rfile.read(n))
                if not isinstance(data, dict):
                    raise ValueError("not an object")
            except ValueError as e:
                self.json(400, {"error": str(e)})
                return None
            return data

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self.guard():
                return
            u = urlsplit(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if "key" in q and not u.path.startswith("/__bluedoc/"):
                return self.unlock(u)
            if u.path == "/":
                html = HOME_HTML.read_text(encoding="utf-8").replace("__BLUEDOC_VENDOR_V__", vendor_version())
                return self.send(200, html)
            if u.path.startswith("/__bluedoc/vendor/"):
                f = vendor_file(u.path[len("/__bluedoc/vendor/"):])
                return self.asset(f, q) if f else self.json(404, {"error": "not found"})
            if u.path.startswith("/__bluedoc/kit/"):
                f = kit_file(u.path[len("/__bluedoc/kit/"):])
                return self.asset(f, q) if f else self.json(404, {"error": "not found"})
            if u.path.startswith("/__bluedoc/fw/"):
                f = store_file(u.path[len("/__bluedoc/fw/"):])
                return self.asset(f, q) if f else self.json(404, {"error": "not found"})
            if u.path == "/__bluedoc/index.json":
                return self.json(200, {**index(), "unlocked": self.has_key()})
            if u.path == "/__bluedoc/ping":
                doc = doc_for_url(q.get("path", ""))
                return self.json(200, {"bluedoc": True, "home": "/", "version": VERSION, "code": CODE_HASH,
                                       "unlocked": self.has_key(),
                                       "to": INBOX.names.get(str(doc), default_to) if doc else default_to,
                                       "approval": saved_approval(doc) if doc else None})
            if u.path == "/__bluedoc/url":
                return self.json(200, {"url": url_for(Path(q.get("doc", "")))})
            if u.path == "/__bluedoc/state":
                doc = doc_for_url(q.get("path", ""))
                if not doc:
                    return self.json(404, {"error": "not a doc under a registered folder"})
                seed = page_state(doc)
                if seed is None:
                    return self.json(503, {"error": "this server's Python has no sqlite3: reader state stays in the browser"})
                if q.get("since") == str(seed["version"]):
                    return self.send(204, b"")
                return self.json(200, seed)
            if u.path == "/__bluedoc/wait":
                # it consumes a reply: like the POSTs, only our own clients (a cross-site <img> or fetch can't set it)
                if self.headers.get("X-Bluedoc") != "1":
                    return self.json(403, {"error": "missing X-Bluedoc header"})
                if not self.has_key():
                    return self.no_key()
                try:
                    timeout = float(q.get("timeout", 25))
                    if not (math.isfinite(timeout) and timeout >= 0):
                        raise ValueError
                except ValueError:
                    return self.json(400, {"error": "bad timeout: want seconds, 0 or more"})
                m = INBOX.take(str(Path(q.get("doc", "")).resolve()), q.get("kind", "any"), min(timeout, 60))
                return self.json(200, {"message": m}) if m else self.send(204, b"")
            if u.path.startswith("/__bluedoc/"):
                return self.json(404, {"error": "not found"})
            if SCREEN_URL.match(u.path):   # before the old .html redirect below
                return self.screen(u.path, q)
            doc = doc_for_url(u.path)
            if not doc:
                media = media_for_url(u.path)
                if media:
                    return self.send_media(media)
                declared = declared_for_url(u.path)
                if declared:
                    return self.asset(declared, q)
                # an old link to a rendered <stem>.html: send it to the doc that replaced it
                if u.path.endswith(".html"):
                    for suffix in build.DOC_SUFFIXES:
                        target = u.path[: -len(".html")] + suffix
                        if doc_for_url(target):
                            self.send_response(302)
                            self.send_header("Location", target + (("#" + u.fragment) if u.fragment else ""))
                            self.send_header("Content-Length", "0")
                            self.end_headers()
                            return
                return self.send(404, "<!doctype html><title>Not found</title><p>No bluedoc at this address. <a href='/'>All docs</a></p>")
            if q.get("raw"):
                return self.send(200, doc.read_bytes(), "application/json; charset=utf-8")
            code, html = render(doc)
            return self.send(code, html)

        def do_PUT(self):
            if not self.guard():
                return
            if urlsplit(self.path).path != "/__bluedoc/state":
                return self.json(404, {"error": "not found"})
            data = self.body(STATE_MAX_BODY)
            if data is None:
                return
            doc = doc_for_url(str(data.get("path") or ""))
            if not doc:
                return self.json(404, {"error": "the page's doc is not under a registered folder"})
            try:
                ops = state_ops(data)
            except ValueError as e:
                return self.json(400, {"error": str(e)})
            if not DB:
                return self.json(503, {"error": "this server's Python has no sqlite3: reader state stays in the browser"})
            imported = data.get("import") is True
            if imported:   # another doc's ticks under a shared doc.id: keep item keys this doc has
                try:
                    items = checklist_items(json.loads(doc.read_text(encoding="utf-8")))
                except (OSError, ValueError, AttributeError) as e:
                    return self.json(500, {"error": f"cannot read the doc: {e}"})
                ops = [(k, v) for k, v in ops if k.startswith("__") or ":".join(k.split(":")[:2]) in items]
            dropped = [k for k, v in ops if v is not None and not value_ok(k, v)]   # values the page could not draw
            ops = [(k, v) for k, v in ops if v is None or value_ok(k, v)]
            version = DB.apply(str(doc), doc_id(doc), ops, imported)
            return self.json(200, {"ok": True, "version": version, **({"dropped": dropped} if dropped else {})})

        def do_POST(self):
            if not self.guard():
                return
            path = urlsplit(self.path).path
            data = self.body(MAX_BODY)
            if data is None:
                return
            if path == "/__bluedoc/register":
                doc = Path(str(data.get("doc") or "")).resolve()
                INBOX.names[str(doc)] = str(data.get("to") or "")
                return self.json(200, {"ok": True, "url": url_for(doc), "token": mint_token()})
            if path == "/__bluedoc/unlock":
                return self.json(200, {"ok": True, "token": mint_token()})
            if path == "/__bluedoc/stop":
                self.json(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            kind = REPLY_ROUTES.get(path)
            if not kind:
                return self.json(404, {"error": "not found"})
            if kind == "approval":
                ok = data.get("decision") == "approved" and all(isinstance(data.get(k, []), list) for k in ("answers", "annotations"))
            else:
                ok = isinstance(data.get("items" if kind == "answers" else "annotations"), list)
            if not ok:
                return self.json(400, {"error": f"not a bluedoc {kind} payload"})
            doc = doc_for_url(str(data.get("path") or ""))
            if not doc:
                return self.json(404, {"error": "the page's doc is not under a registered folder"})
            if not DB:
                return self.json(503, {"error": "this server's Python has no sqlite3, so it can't keep replies: use Copy"})
            data["kind"] = kind
            if kind == "approval":
                # the approval covers the JSON the page showed: refuse it when the doc changed since, or the rev isn't its
                current, _, rev = doc_info(doc)
                if not current or data.get("docHash") != current or str(data.get("rev") or "") != rev:
                    return self.json(409, {"error": "the doc changed since this page loaded it: reload it and approve again",
                                           "reload": True})
            rid = INBOX.put(doc, kind, data, str(data.get("markdown") or "").rstrip() + "\n")
            print(f"{kind} for {doc}: reply {rid}", flush=True)
            return self.json(200, {"ok": True, "id": rid})

    return H


def open_db() -> int:
    """Open state.db into DB; a new one first takes in the reply files of earlier versions. The queued reply count."""
    global DB
    if statedb is None:
        print("warning: this Python has no sqlite3 module: pages render without reader state (it stays in each browser) "
              "and replies are refused (Copy still works)", file=sys.stderr, flush=True)
        return 0
    DB = statedb.StateDB(STATE_DB)
    if DB.created:
        imported = import_reply_files(load_roots())
        if imported:
            print(f"imported {imported} reply file{'' if imported == 1 else 's'} into {STATE_DB} (the files stay)", flush=True)
    return len(DB.undelivered())


def run(port: int, to: str) -> int:
    global SECRET
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(port, to))
    STATE.mkdir(parents=True, exist_ok=True)
    SECRET = load_key(create=True)   # kept across restarts, so a browser's cookie outlives an upgrade
    queued = open_db()
    SERVER_FILE.write_text(json.dumps({"pid": os.getpid(), "port": port}) + "\n", encoding="utf-8")
    print(f"bluedoc {VERSION or '(no version)'} (code {CODE_HASH}) on http://127.0.0.1:{port}/ "
          f"(folders: {', '.join(map(str, load_roots())) or 'none yet'}; {queued} undelivered repl{'y' if queued == 1 else 'ies'} queued)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        try:
            if json.loads(SERVER_FILE.read_text()).get("pid") == os.getpid():
                SERVER_FILE.unlink()
        except (OSError, ValueError):
            pass
    return 0


# ---------- CLI ----------

def base(port: int | None = None) -> str:
    if port is None:
        try:
            port = int(json.loads(SERVER_FILE.read_text()).get("port"))
        except (OSError, ValueError, TypeError):
            port = DEFAULT_PORT
    return f"http://127.0.0.1:{port}"


def call(path: str, body: dict | None = None, timeout: float = 5):
    """GET path (POST body when given) on the running server, with the X-Bluedoc header and the key."""
    headers = {"X-Bluedoc": "1", "Content-Type": "application/json"}
    key = load_key()
    if key:
        headers["X-Bluedoc-Key"] = key
    req = urllib.request.Request(base() + path, data=None if body is None else json.dumps(body).encode(),
                                 headers=headers, method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)


def server_info() -> dict | None:
    """The running server's ping, or None."""
    try:
        info = call("/__bluedoc/ping")[1]
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) and info.get("bluedoc") is True else None


def alive() -> bool:
    return server_info() is not None


def stop_server() -> bool:
    """Ask the running server to stop; False (and why) when it refuses, as one whose key file was replaced does."""
    try:
        call("/__bluedoc/stop", {})
    except urllib.error.HTTPError as e:
        print(f"the bluedoc server refused to stop: {e.read().decode(errors='replace')} (its key isn't {KEY_FILE}; "
              f"stop its process, pid in {SERVER_FILE})", file=sys.stderr)
        return False
    return True


def ensure_started(port: int) -> bool:
    """Start the server unless one runs this very code; one that runs another version or code is replaced."""
    info = server_info()
    if info and (info.get("version"), info.get("code")) == (VERSION, CODE_HASH):
        return True
    if info:
        print(f"restarting the bluedoc server: it ran {info.get('version') or 'an unknown version'} (code {info.get('code') or '?'}), "
              f"this is {VERSION or 'an unknown version'} (code {CODE_HASH})", file=sys.stderr)
        if not stop_server():
            return False
        for _ in range(50):
            time.sleep(0.1)
            if not alive():
                break
        else:
            print("the old bluedoc server did not stop", file=sys.stderr)
            return False
    STATE.mkdir(parents=True, exist_ok=True)
    log = open(STATE / "server.log", "a")
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "run", "--port", str(port)],
                     stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(50):
        time.sleep(0.1)
        try:
            if json.loads(SERVER_FILE.read_text()).get("port") == port and alive():
                return True
        except (OSError, ValueError):
            pass
    print(f"server did not start; see {STATE / 'server.log'}", file=sys.stderr)
    return False


# ---------- frameworks the reader adds ----------

MAX_FRAMEWORK_BYTES = 64 * 1024 * 1024
FRAMEWORK_LOAD_EXTS = (".css", ".js", ".mjs")
_TW = ("https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3/dist/index.global.js",
       "a60c785630a06196808cbe79e6f7bdb4abcc8f4421a47b56f29338fc84805e3b", "tailwind.js")
_TW_LICENSE = ("https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3/LICENSE",
               "60e0b68c0f35c078eef3a5d29419d0b03ff84ec1df9c3f9d6e39a519a5ae7985", "licenses/tailwindcss-LICENSE")
# `add-framework <preset>`: pinned files (url, sha256, saved as), fetched once on the reader's command. Each compiles
# Tailwind classes in the frame with Tailwind's browser build; HeroUI and daisyUI add their prebuilt component CSS.
PRESETS = {
    "tailwind": {"label": "Tailwind CSS", "fetch": (_TW, _TW_LICENSE), "load": ("tailwind.js",)},
    "heroui": {"label": "Tailwind + HeroUI", "load": ("heroui.min.css", "tailwind.js"), "fetch": (
        _TW, _TW_LICENSE,
        ("https://cdn.jsdelivr.net/npm/@heroui/styles@3.2.6/dist/heroui.min.css",
         "95ac190a78f5f7c2126f365096fdf08326cf206cd0c8fdf0e8532e7185f32a2e", "heroui.min.css"),
        ("https://cdn.jsdelivr.net/npm/@heroui/styles@3.2.6/LICENSE",
         "bd087c1ebd511adbab74705ec2b31d63d175e8d422f58c1af54754da02b1d329", "licenses/heroui-LICENSE"))},
    "daisyui": {"label": "Tailwind + daisyUI", "load": ("daisyui.css", "tailwind.js"), "fetch": (
        _TW, _TW_LICENSE,
        ("https://cdn.jsdelivr.net/npm/daisyui@5.7.47/daisyui.css",
         "d057842b420556c5f98a5a3c362b7a1eff194125bdce03e654835db1956e3d0c", "daisyui.css"),
        ("https://cdn.jsdelivr.net/npm/daisyui@5.7.47/LICENSE",
         "8709e3ac65c84637c422dc8082b893d9997fce093751c77b2f1983bf29dbf9ea", "licenses/daisyui-LICENSE"))},
}


def fetch_url(url: str, sha256: str | None = None) -> bytes:
    """One GET of url, at most MAX_FRAMEWORK_BYTES; with sha256, the bytes must match it."""
    req = urllib.request.Request(url, headers={"User-Agent": f"bluedoc/{VERSION or 'dev'}"})
    with urllib.request.urlopen(req, timeout=60) as r:   # noqa: S310 (the reader's own command and URL)
        data = r.read(MAX_FRAMEWORK_BYTES + 1)
    if len(data) > MAX_FRAMEWORK_BYTES:
        raise ValueError(f"{url}: larger than {MAX_FRAMEWORK_BYTES >> 20} MB")
    if sha256 and hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError(f"{url}: its sha256 isn't the pinned one, so nothing was added")
    return data


def unpack_tgz(data: bytes, dest: Path) -> None:
    """A .tgz's regular files into dest, without a top folder all of them share (npm's package/). Links, devices and
    paths that would leave dest are skipped."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as t:
        members = [m for m in t.getmembers() if m.isfile()]
        parts = [[x for x in m.name.split("/") if x not in ("", ".")] for m in members]
        strip = 1 if parts and all(len(p) > 1 and p[0] == parts[0][0] for p in parts) else 0
        for m, p in zip(members, parts):
            rel = p[strip:]
            if not rel or ".." in rel or m.name.startswith("/"):
                continue
            out = dest.joinpath(*rel)
            out.parent.mkdir(parents=True, exist_ok=True)
            src = t.extractfile(m)
            if src:
                out.write_bytes(src.read())


def default_load(d: Path) -> list[str]:
    """The files a copy loads when --load names none: its only file, else package.json's style/unpkg/jsdelivr/browser
    files, else the CSS then JS files at its top level."""
    files = sorted(f for f in d.rglob("*") if f.is_file())
    if len(files) == 1 and files[0].suffix.lower() in FRAMEWORK_LOAD_EXTS:
        return [files[0].relative_to(d).as_posix()]
    try:
        pkg = json.loads((d / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pkg = None
    out: list[str] = []
    for key in ("style", "unpkg", "jsdelivr", "browser"):
        v = pkg.get(key) if isinstance(pkg, dict) else None
        f = (d / v).resolve() if isinstance(v, str) else None
        if f and d.resolve() in f.parents and f.is_file() and f.suffix.lower() in FRAMEWORK_LOAD_EXTS:
            rel = f.relative_to(d.resolve()).as_posix()
            if rel not in out:
                out.append(rel)
    if not out:
        out = [f.name for f in files if f.parent == d and f.suffix.lower() in FRAMEWORK_LOAD_EXTS]
    return sorted(out, key=lambda r: not r.endswith(".css"))


def add_framework(name: str, source: str | None, load: list[str], sources: list[str], tailwind: bool,
                  label: str | None) -> int:
    """`serve.py add-framework`: copy a preset, a file, a folder or one URL (a file or .tgz) into
    frameworks_dir()/<name>/ with a manifest of each file's size and sha256, and print it."""
    if not build.ID_RE.match(name) or name in build.BUILTIN_FRAMEWORKS:
        print(f"add-framework: {name!r} must be lowercase letters, digits and dashes, and not "
              f"{' or '.join(build.BUILTIN_FRAMEWORKS)}", file=sys.stderr)
        return 2
    preset = PRESETS.get(name) if source is None else None
    if source is None and not preset:
        print(f"add-framework: no preset named {name}: give a path or URL (presets: {', '.join(PRESETS)})", file=sys.stderr)
        return 2
    base = build.frameworks_dir()
    base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=base))
    try:
        if preset:
            for url, sha, save in preset["fetch"]:
                print(f"fetching {url}", flush=True)
                out = tmp / save
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(fetch_url(url, sha))
            load, tailwind, label, origin = load or list(preset["load"]), True, label or preset["label"], f"preset {name}"
        elif re.match(r"(?i)^https?://", source):
            print(f"fetching {source}", flush=True)
            data, fname = fetch_url(source), unquote(urlsplit(source).path.rsplit("/", 1)[-1])
            if fname.endswith((".tgz", ".tar.gz")):
                unpack_tgz(data, tmp)
            else:
                (tmp / (re.sub(r"[^\w.-]", "_", fname) or "file")).write_bytes(data)
            origin = source
        else:
            src = Path(source).expanduser().resolve()
            if src.is_dir():
                shutil.copytree(src, tmp, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
            elif src.is_file() and src.name.endswith((".tgz", ".tar.gz")):
                unpack_tgz(src.read_bytes(), tmp)
            elif src.is_file():
                shutil.copy2(src, tmp / src.name)
            else:
                raise ValueError(f"{source}: no such file or folder")
            origin = str(src)
        files = sorted(f for f in tmp.rglob("*") if f.is_file())
        if sum(f.stat().st_size for f in files) > MAX_FRAMEWORK_BYTES:
            raise ValueError(f"more than {MAX_FRAMEWORK_BYTES >> 20} MB: name the dist folder, not the package")
        load = [Path(x).as_posix() for x in load] or default_load(tmp)
        sources = [Path(x).as_posix() for x in sources]
        if not load:
            raise ValueError("no CSS or JS file to load at the top level: name them with --load")
        for rel in load + sources:
            f = (tmp / rel).resolve()
            if tmp.resolve() not in f.parents or not f.is_file() or f.suffix.lower() not in FRAMEWORK_LOAD_EXTS:
                raise ValueError(f"{rel}: not a .css, .js or .mjs file in the copy")
        listed = [{"path": f.relative_to(tmp).as_posix(), "size": f.stat().st_size,
                   "sha256": hashlib.sha256(f.read_bytes()).hexdigest()} for f in files]
        manifest = {"name": name, "label": label or name, "source": origin,
                    "added": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    "load": load, "sources": sources, "compiler": "tailwind" if tailwind or sources else None,
                    "files": listed, "sha256": hashlib.sha256(json.dumps(listed, sort_keys=True).encode()).hexdigest()}
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
        dest = base / name
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
    except (OSError, ValueError, urllib.error.URLError, tarfile.TarError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"add-framework: {e}", file=sys.stderr)
        return 1
    total = sum(f["size"] for f in listed)
    print(f"added {manifest['label']} as {name} in {dest} ({len(listed)} files, {total / 1024:.0f} KB)")
    for f in listed:
        print(f"  {f['path']}  {f['size']} B  sha256 {f['sha256']}")
    print(f"loads: {', '.join(load)}" + ("; compiles Tailwind classes in each screen" if manifest["compiler"] else ""))
    print("board: " + json.dumps({"id": name, "label": manifest["label"], "store": name}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("open", help="register the doc's folder, start the server if needed, print the URL")
    p.add_argument("doc", type=Path)
    p.add_argument("--to", default="", help="who reads the replies (shown in the page), e.g. your agent name")
    p.add_argument("--root", type=Path, help="folder to register instead of the default")
    p.add_argument("--browser", action="store_true", help="also open the URL in the default browser")
    p = sub.add_parser("wait", help="block until the reader sends answers, a change request or a plan approval for DOC")
    p.add_argument("doc", type=Path)
    p.add_argument("--kind", choices=(*KINDS, "any"), default="any")
    p.add_argument("--timeout", type=float, default=0, help="seconds; 0 waits forever. Exit 3 on timeout")
    p = sub.add_parser("reply", help="print a stored reply: by the id `wait` printed, or DOC's newest")
    p.add_argument("target", help="a reply id, or a doc's JSON file")
    p.add_argument("--kind", choices=(*KINDS, "any"), default="any", help="with DOC: the newest reply of this kind")
    p.add_argument("--json", action="store_true", help="print the JSON the page posted instead of the Markdown")
    for name in ("start", "run"):
        p = sub.add_parser(name)
        p.add_argument("--port", type=int, default=DEFAULT_PORT)
        if name == "run":
            p.add_argument("--to", default="", help="default reader-facing agent name")
    sub.add_parser("stop")
    sub.add_parser("unlock", help="print a home page link that lets a browser save here")
    sub.add_parser("status")
    p = sub.add_parser("add", help="add a folder to the home page")
    p.add_argument("dir", type=Path)
    sub.add_parser("roots")
    p = sub.add_parser("add-framework", help="copy a framework (a preset, a file, a folder or one URL) for design boards")
    p.add_argument("name", help=f"the store name boards use (store: NAME); alone, a preset: {', '.join(PRESETS)}")
    p.add_argument("source", nargs="?", help="a file, a folder, or one http(s) URL of a file or .tgz")
    p.add_argument("--load", action="append", default=[], metavar="FILE", help="a CSS/JS file screens load, in order (repeatable)")
    p.add_argument("--source", dest="sources", action="append", default=[], metavar="FILE",
                   help="a Tailwind source CSS file the frame compiles (repeatable; implies --tailwind)")
    p.add_argument("--tailwind", action="store_true", help="the copy holds Tailwind's browser build: compile classes in each screen")
    p.add_argument("--label", help="the name the notice and the board show")
    a = ap.parse_args()

    if a.cmd == "run":
        return run(a.port, a.to)
    if a.cmd == "start":
        if not ensure_started(a.port):
            return 1
        print(base() + "/")
        return 0
    if a.cmd == "stop":
        if not alive():
            print("not running")
            return 0
        if not stop_server():
            return 1
        print("stopped")
        return 0
    if a.cmd == "status":
        print(f"running at {base()}/" if alive() else "not running")
        for r in load_roots():
            print(f"  {r}")
        return 0
    if a.cmd == "add":
        if not a.dir.is_dir():
            print(f"{a.dir} is not a folder", file=sys.stderr)
            return 2
        print(f"added {add_root(a.dir)}")
        return 0
    if a.cmd == "roots":
        for slug, r in slugs(load_roots()).items():
            print(f"/{slug}/  {r}")
        return 0
    if a.cmd == "reply":
        return cmd_reply(a.target, a.kind, a.json)
    if a.cmd == "add-framework":
        return add_framework(a.name, a.source, a.load, a.sources, a.tailwind, a.label)
    if a.cmd == "unlock":
        if not ensure_started(DEFAULT_PORT):
            return 1
        print(f"{base()}/?key={call('/__bluedoc/unlock', {})[1]['token']}")
        return 0

    doc = a.doc.resolve()
    if not doc.is_file() or not is_doc(doc):
        print(f"{a.doc}: not a {DOC_FILES} file", file=sys.stderr)
        return 2
    if a.cmd == "open":
        add_root(a.root.resolve() if a.root else root_for(doc))
        if not ensure_started(DEFAULT_PORT):
            return 1
        res = call("/__bluedoc/register", {"doc": str(doc), "to": a.to})[1]
        # the one-time key lets this browser save; visiting it redirects to the plain URL
        url = base() + res["url"] + (f"?key={res['token']}" if res.get("token") else "")
        print(url)
        if a.browser:
            webbrowser.open(url)
        return 0

    # wait
    if not alive():
        print("bluedoc server is not running; run `serve.py open DOC` first", file=sys.stderr)
        return 1
    end = time.monotonic() + a.timeout if a.timeout else None
    while True:
        left = 25 if end is None else min(25, end - time.monotonic())
        if left <= 0:
            print(f"no {a.kind if a.kind != 'any' else 'reply'} within {a.timeout:g} s", file=sys.stderr)
            return 3
        try:
            code, body = call(f"/__bluedoc/wait?doc={quote(str(doc))}&kind={a.kind}&timeout={left:.0f}", timeout=left + 10)
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise
            print(f"the bluedoc server refused {KEY_FILE}: {e.read().decode(errors='replace')}", file=sys.stderr)
            return 1
        except (urllib.error.URLError, OSError):
            # `open` may be replacing the server with a newer one, which queues the reply again: give it 10 s
            if not any(time.sleep(0.5) or alive() for _ in range(20)):
                print("lost the bluedoc server", file=sys.stderr)
                return 1
            continue
        if code == 200 and body and body.get("message"):
            print_reply(body["message"])
            return 0


def print_reply(m: dict) -> None:
    """A reply as `wait` and `reply` print it: a header with its id, rev and time, then its Markdown."""
    label = {"answers": "answers", "changes": "change request", "approval": "approval"}[m["kind"]]
    at = dt.datetime.fromisoformat(m["at"]).isoformat(timespec="seconds")
    print(f"--- bluedoc {label} (reply {m['id']}{', rev ' + m['rev'] if m.get('rev') else ''}, {at}) ---")
    print(m["markdown"], end="")
    print("--- end ---", flush=True)


def cmd_reply(target: str, kind: str, as_json: bool) -> int:
    if statedb is None:
        print("this Python has no sqlite3 module, so no replies are stored", file=sys.stderr)
        return 1
    try:
        db = statedb.StateDB(STATE_DB, create=False)
    except FileNotFoundError:
        print(f"no replies stored yet ({STATE_DB} doesn't exist)", file=sys.stderr)
        return 1
    if target.isdigit():
        m = db.reply(int(target))
        missing = f"no reply {target}"
    else:
        doc = Path(target).resolve()
        if not doc.is_file() or not is_doc(doc):
            print(f"{target}: not a reply id or a {DOC_FILES} file", file=sys.stderr)
            return 2
        rows = db.latest(str(doc))
        m = rows.get(kind) if kind != "any" else max(rows.values(), key=lambda r: r["id"], default=None)
        missing = f"no {kind if kind != 'any' else 'reply'} stored for {doc}"
    db.close()
    if not m:
        print(missing, file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(json.loads(m["payload"]), indent=2, ensure_ascii=False))
    else:
        print_reply(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
