#!/usr/bin/env python3
"""The bluedoc server: renders JSON docs with the template on every request, lists them on a
searchable home page, and passes the reader's answers and change requests back to the agent.

Usage:
  serve.py open DOC.json [--to NAME] [--browser]   start the server if needed, register the doc's
                                                   folder, print the doc's URL
  serve.py wait DOC.json [--kind answers|changes|approval|any] [--timeout SEC]
                                                   block until the reader sends answers, a change
                                                   request or a plan approval for DOC; print it as Markdown
  serve.py start | stop | status                   manage the background server
  serve.py add DIR | roots                         add a folder to the home page / list folders
  serve.py run [--port N]                          run in the foreground

One server per user, on 127.0.0.1 (default port 8740, env BLUEDOC_PORT). State lives in
~/.bluedoc (env BLUEDOC_HOME): roots.json (folders the home page scans), server.json (pid, port) and inbox.json
(which reply files `wait` has delivered). `open` registers the topmost ancestor folder named `docs`, else the doc's
own folder, and restarts a running server whose version or code differs from its own.

URLs: /                      home page: every doc under the registered folders, searchable, filtered by
                             project, folder, type and status
      /<root>/<path>.bluedoc.json      the doc, rendered from its JSON on each request
      /<root>/<path>.bluedoc.json?raw=1   the JSON itself
      /<root>/<path>.<png|jpg|jpeg|gif|webp|svg|mp4|webm>   media files under the folder, for `media` blocks
      /__bluedoc/index.json  what the home page shows about every doc
      /__bluedoc/ping?path=  server check (version, code hash); with a doc's URL path, also who reads replies and
                             its saved approval
      /__bluedoc/vendor/<path>  files under assets/vendor (HorizonUI for the home page)
Rendering validates the doc (errors show as a page), shows its meta.rev as the latest revision of the history file
without writing it (build.py records revisions), and fills each `diff` block that references a git range
(diffref.py: its cache, local git, then `gh pr diff`), so the page always shows the current JSON.
HTML pages carry a Content-Security-Policy (hashes of their inline scripts, no framing).

Replies: Send answers posts to /__bluedoc/reply, Request changes to /__bluedoc/changes, Approve plan to
/__bluedoc/approve. Each is saved next to the doc (<name>.reply.md/.json, <name>.changes.md/.json,
<name>.approval.md/.json, overwritten each time) and queued for `wait`, which returns the oldest unread
one (GET /__bluedoc/wait needs the X-Bluedoc header). Replies `wait` has not returned are queued again when the
server starts. An approval holds a hash of the doc's JSON and counts only while the doc is unchanged.
Python 3.9+ standard library only.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402

HOME_HTML = HERE.parent / "assets" / "home.html"
VENDOR = HERE.parent / "assets" / "vendor"
STATE = Path(os.environ.get("BLUEDOC_HOME") or "~/.bluedoc").expanduser()
ROOTS_FILE, SERVER_FILE, INBOX_FILE = STATE / "roots.json", STATE / "server.json", STATE / "inbox.json"
DEFAULT_PORT = int(os.environ.get("BLUEDOC_PORT") or 8740)
SUFFIXES = (".bluedoc.json", ".blueprint.json")
SKIP_DIRS = {"node_modules", "build", "dist", "target", "out", "vendor", "Pods", "DerivedData", "__pycache__"}
MAX_DEPTH, MAX_BODY, SEARCH_CHARS = 8, 4 * 1024 * 1024, 8000   # SEARCH_CHARS keeps index.json small (~10 KB a doc)
KINDS = ("answers", "changes", "approval")
REPLY_SUFFIX = {"answers": "reply", "changes": "changes", "approval": "approval"}   # <stem>.<suffix>.md/.json
REPLY_ROUTES = {"/__bluedoc/reply": "answers", "/__bluedoc/changes": "changes", "/__bluedoc/approve": "approval"}


# ---------- docs on disk ----------

def is_doc(p: Path) -> bool:
    return p.name.endswith(SUFFIXES)


def stem(p: Path) -> str:
    for s in SUFFIXES:
        if p.name.endswith(s):
            return p.name[: -len(s)]
    return p.stem


def reply_file(doc: Path, kind: str, ext: str) -> Path:
    return doc.with_name(f"{stem(doc)}.{REPLY_SUFFIX[kind]}.{ext}")


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
    """Changes whenever the code a server renders with does: serve.py, build.py and the template."""
    h = hashlib.sha256()
    for f in (Path(__file__).resolve(), HERE / "build.py", build.TEMPLATE):
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


VERSION, CODE_HASH = skill_version(), code_hash()
_doc_hashes: dict[str, tuple[float, str | None]] = {}


def doc_hash(p: Path) -> str | None:
    """sha256 of the doc's canonical JSON (sorted keys, no spaces), cached by mtime; None if unreadable."""
    try:
        m = p.stat().st_mtime
    except OSError:
        return None
    hit = _doc_hashes.get(str(p))
    if hit and hit[0] == m:
        return hit[1]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        h = hashlib.sha256(json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    except (OSError, ValueError):
        h = None
    _doc_hashes[str(p)] = (m, h)
    return h


def saved_approval(doc: Path) -> dict | None:
    """The doc's saved plan approval as {rev, at} (both as the page posted them), or None. It counts only while the
    doc's JSON is the one approved: an edit in place, even under the same meta.rev, asks for approval again."""
    try:
        data = json.loads(reply_file(doc, "approval", "json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("docHash") or data["docHash"] != doc_hash(doc):
        return None
    return {"rev": data.get("rev"), "at": data.get("at")}


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
    d = d.resolve()
    roots = load_roots()
    if not any(d == r or r in d.parents for r in roots):
        roots = [r for r in roots if d not in r.parents] + [d]   # a wider root replaces narrower ones
        save_roots(roots)
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


def walk_docs(root: Path):
    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
                             and len(Path(dirpath, d).parts) - root_depth <= MAX_DEPTH)
        for f in sorted(filenames):
            if f.endswith(SUFFIXES):
                yield Path(dirpath, f)


def url_for(doc: Path) -> str | None:
    doc = doc.resolve()
    for slug, r in slugs(load_roots()).items():
        if r == doc.parent or r in doc.parents:
            return f"/{quote(slug)}/{quote(doc.relative_to(r).as_posix())}"
    return None


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
    hero = doc.get("hero")
    if isinstance(hero, dict) and hero.get("value") is not None:
        return {"hero": {k: str(hero[k]) for k in ("icon", "value", "label") if hero.get(k) is not None}}
    return {"icon": "doc", "sections": len(doc.get("sections") or [])}


_cache: dict[str, tuple[tuple[float, float, float], dict]] = {}
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
    """What the home page needs about one doc, cached by the mtimes of the doc, its history (a contract problem is
    an error only while meta.rev is new) and its diff cache (a review card's line counts)."""
    import diffref   # noqa: PLC0415
    st = p.stat()
    keyed = lambda: (st.st_mtime, mtime(build.history_path(p)), mtime(diffref.cache_path(p)))  # noqa: E731
    key = keyed()
    hit = _cache.get(str(p))
    if hit and hit[0] == key:
        info = dict(hit[1])
    else:
        info = {"title": stem(p), "errors": 0}
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
                "id": doc.get("id"), "title": doc.get("title") or stem(p), "subtitle": doc.get("subtitle") or "",
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
    for kind in KINDS:
        f = reply_file(p, kind, "json")
        if f.exists():
            if kind == "approval" and saved_approval(p) is None:   # approved other content of this doc: awaiting again
                continue
            try:
                rev = json.loads(f.read_text(encoding="utf-8")).get("rev")
            except (OSError, ValueError):
                rev = None
            info[kind] = {"at": f.stat().st_mtime, "rev": rev}
    return info


def index() -> dict:
    out = []
    for slug, r in slugs(load_roots()).items():
        docs = []
        for p in walk_docs(r):
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
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return 500, error_page(p, [f"cannot read: {e}"])
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
        log = build.record(history, doc)
        if log.startswith("ERROR"):
            return 422, error_page(p, [log])
    # the history keeps refs; build expands them in the page's doc and in older revisions. validate already showed
    # the doc's own expansion errors; an older revision whose range is gone shows an empty diff
    return 200, build.build(doc, build.TEMPLATE.read_text(encoding="utf-8"), history, diff_path=p, problems=[])


# ---------- inbox: replies the agent waits for ----------

def reply_message(doc: Path, kind: str) -> dict:
    """What `wait` returns for the reply of this kind saved next to doc; `at` is its JSON file's mtime."""
    md_path, json_path = reply_file(doc, kind, "md"), reply_file(doc, kind, "json")
    md = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    return {"kind": kind, "doc": str(doc), "markdown": md, "md_file": str(md_path), "json_file": str(json_path),
            "at": json_path.stat().st_mtime}


class Inbox:
    """Replies queued per doc until `wait` takes them. inbox.json keeps {reply JSON file: mtime `wait` delivered}, so
    the replies nobody took are queued again when the server starts."""
    def __init__(self) -> None:
        self.cv = threading.Condition()
        self.queue: dict[str, list[dict]] = {}
        self.names: dict[str, str] = {}
        self.delivered: dict[str, float] = {}

    def save(self) -> None:
        STATE.mkdir(parents=True, exist_ok=True)
        tmp = INBOX_FILE.with_name(INBOX_FILE.name + ".tmp")
        tmp.write_text(json.dumps(self.delivered, indent=1) + "\n", encoding="utf-8")
        tmp.replace(INBOX_FILE)

    def load(self, roots: list[Path]) -> int:
        """Queue every reply under roots that `wait` has not returned; the count. The first start (no inbox.json)
        takes every reply already on disk as delivered."""
        found = []
        for r in roots:
            for doc in walk_docs(r):
                for kind in KINDS:
                    f = reply_file(doc, kind, "json")
                    if f.is_file():
                        found.append((f.stat().st_mtime, doc.resolve(), kind, str(f)))
        try:
            seen = json.loads(INBOX_FILE.read_text(encoding="utf-8"))
            first = not isinstance(seen, dict)
        except (OSError, ValueError):
            seen, first = {}, True
        with self.cv:
            if first:
                self.delivered = {f: m for m, _, _, f in found}
                self.save()
                return 0
            self.delivered = {f: m for f, m in seen.items() if Path(f).is_file()}
            n = 0
            for m, doc, kind, f in sorted(found):
                if self.delivered.get(f, -1.0) < m:
                    self.queue.setdefault(str(doc), []).append(reply_message(doc, kind))
                    n += 1
            return n

    def put(self, doc: Path, msg: dict) -> None:
        with self.cv:
            self.queue.setdefault(str(doc), []).append(msg)
            self.cv.notify_all()

    def take(self, doc: str, kind: str, timeout: float) -> dict | None:
        end = time.monotonic() + timeout
        with self.cv:
            while True:
                q = self.queue.get(doc, [])
                for i, m in enumerate(q):
                    if kind == "any" or m["kind"] == kind:
                        msg = q.pop(i)
                        self.delivered[msg["json_file"]] = max(self.delivered.get(msg["json_file"], 0.0), msg["at"])
                        self.save()
                        return msg
                left = end - time.monotonic()
                if left <= 0:
                    return None
                self.cv.wait(left)


INBOX = Inbox()


# ---------- HTTP ----------

def make_handler(port: int, default_to: str):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        server_version = "bluedoc"

        def log_message(self, *_):
            pass

        def send(self, code: int, body: str | bytes, ctype: str = "text/html; charset=utf-8", cache: str = "no-store",
                 headers: dict[str, str] | None = None) -> None:
            data = body.encode() if isinstance(body, str) else body
            if ctype.startswith("text/html"):
                headers = {"Content-Security-Policy": page_csp(data.decode("utf-8", "replace")), "X-Frame-Options": "DENY", **(headers or {})}
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

        def guard(self) -> bool:
            # DNS rebinding: only our own host names; writes also need our header and origin
            if self.headers.get("Host") not in hosts:
                self.json(403, {"error": "bad host"})
                return False
            if self.command == "POST":
                origin = self.headers.get("Origin")
                if self.headers.get("X-Bluedoc") != "1" or (origin and urlsplit(origin).netloc not in hosts):
                    self.json(403, {"error": "missing X-Bluedoc header or cross-origin"})
                    return False
            return True

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self.guard():
                return
            u = urlsplit(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/":
                html = HOME_HTML.read_text(encoding="utf-8").replace("__BLUEDOC_VENDOR_V__", vendor_version())
                return self.send(200, html)
            if u.path.startswith("/__bluedoc/vendor/"):
                f = vendor_file(u.path[len("/__bluedoc/vendor/"):])
                if not f:
                    return self.json(404, {"error": "not found"})
                # versioned URLs (?v=) are immutable: home.html changes v when the vendored files change
                return self.send(200, f.read_bytes(), vendor_type(f), "public, max-age=31536000, immutable" if q.get("v") else "no-cache")
            if u.path == "/__bluedoc/index.json":
                return self.json(200, index())
            if u.path == "/__bluedoc/ping":
                doc = doc_for_url(q.get("path", ""))
                return self.json(200, {"bluedoc": True, "home": "/", "version": VERSION, "code": CODE_HASH,
                                       "to": INBOX.names.get(str(doc), default_to) if doc else default_to,
                                       "approval": saved_approval(doc) if doc else None})
            if u.path == "/__bluedoc/url":
                return self.json(200, {"url": url_for(Path(q.get("doc", "")))})
            if u.path == "/__bluedoc/wait":
                # it consumes a reply: like the POSTs, only our own clients (a cross-site <img> or fetch can't set it)
                if self.headers.get("X-Bluedoc") != "1":
                    return self.json(403, {"error": "missing X-Bluedoc header"})
                m = INBOX.take(str(Path(q.get("doc", "")).resolve()), q.get("kind", "any"), min(float(q.get("timeout", 25)), 60))
                return self.json(200, {"message": m}) if m else self.send(204, b"")
            if u.path.startswith("/__bluedoc/"):
                return self.json(404, {"error": "not found"})
            doc = doc_for_url(u.path)
            if not doc:
                media = media_for_url(u.path)
                if media:
                    return self.send_media(media)
                # an old link to a rendered <stem>.html: send it to the doc that replaced it
                if u.path.endswith(".html"):
                    for suffix in SUFFIXES:
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

        def do_POST(self):
            if not self.guard():
                return
            path = urlsplit(self.path).path
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= MAX_BODY:
                return self.json(413, {"error": "empty or too large"})
            try:
                data = json.loads(self.rfile.read(n))
                if not isinstance(data, dict):
                    raise ValueError("not an object")
            except ValueError as e:
                return self.json(400, {"error": str(e)})
            if path == "/__bluedoc/register":
                doc = Path(str(data.get("doc") or "")).resolve()
                INBOX.names[str(doc)] = str(data.get("to") or "")
                return self.json(200, {"ok": True, "url": url_for(doc)})
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
            data["kind"] = kind
            if kind == "approval":
                data["docHash"] = doc_hash(doc)   # the approval counts only while the doc's JSON is this one
            md = str(data.get("markdown") or "").rstrip() + "\n"
            md_path, json_path = reply_file(doc, kind, "md"), reply_file(doc, kind, "json")
            md_path.write_text(md, encoding="utf-8")
            json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            INBOX.put(doc, reply_message(doc, kind))
            print(f"{kind} for {doc}: {json_path}", flush=True)
            return self.json(200, {"ok": True, "saved": str(json_path)})

    return H


def run(port: int, to: str) -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(port, to))
    STATE.mkdir(parents=True, exist_ok=True)
    SERVER_FILE.write_text(json.dumps({"pid": os.getpid(), "port": port}) + "\n", encoding="utf-8")
    queued = INBOX.load(load_roots())
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
    req = urllib.request.Request(base() + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"X-Bluedoc": "1", "Content-Type": "application/json"}, method="GET" if body is None else "POST")
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


def ensure_started(port: int) -> bool:
    """Start the server unless one runs this very code; one that runs another version or code is replaced."""
    info = server_info()
    if info and (info.get("version"), info.get("code")) == (VERSION, CODE_HASH):
        return True
    if info:
        print(f"restarting the bluedoc server: it ran {info.get('version') or 'an unknown version'} (code {info.get('code') or '?'}), "
              f"this is {VERSION or 'an unknown version'} (code {CODE_HASH})", file=sys.stderr)
        call("/__bluedoc/stop", {})
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
    for name in ("start", "run"):
        p = sub.add_parser(name)
        p.add_argument("--port", type=int, default=DEFAULT_PORT)
        if name == "run":
            p.add_argument("--to", default="", help="default reader-facing agent name")
    sub.add_parser("stop")
    sub.add_parser("status")
    p = sub.add_parser("add", help="add a folder to the home page")
    p.add_argument("dir", type=Path)
    sub.add_parser("roots")
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
        call("/__bluedoc/stop", {})
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

    doc = a.doc.resolve()
    if not doc.is_file() or not is_doc(doc):
        print(f"{a.doc}: not a *.bluedoc.json / *.blueprint.json file", file=sys.stderr)
        return 2
    if a.cmd == "open":
        add_root(a.root.resolve() if a.root else root_for(doc))
        if not ensure_started(DEFAULT_PORT):
            return 1
        url = base() + call("/__bluedoc/register", {"doc": str(doc), "to": a.to})[1]["url"]
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
        except (urllib.error.URLError, OSError):
            # `open` may be replacing the server with a newer one, which queues the reply again: give it 10 s
            if not any(time.sleep(0.5) or alive() for _ in range(20)):
                print("lost the bluedoc server", file=sys.stderr)
                return 1
            continue
        if code == 200 and body and body.get("message"):
            m = body["message"]
            label = {"answers": "answers", "changes": "change request", "approval": "approval"}[m["kind"]]
            print(f"--- bluedoc {label} ({m['json_file']}) ---")
            print(m["markdown"], end="")
            print("--- end ---", flush=True)
            return 0


if __name__ == "__main__":
    sys.exit(main())
