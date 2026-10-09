#!/usr/bin/env python3
"""The bluedoc server: renders JSON docs with the template on every request, lists them on a
searchable home page, and passes the reader's answers and change requests back to the agent.

Usage:
  serve.py open DOC.json [--to NAME] [--browser]   start the server if needed, register the doc's
                                                   folder, print the doc's URL
  serve.py wait DOC.json [--kind answers|changes|any] [--timeout SEC]
                                                   block until the reader sends answers or a change
                                                   request for DOC; print it as Markdown
  serve.py start | stop | status                   manage the background server
  serve.py add DIR | roots                         add a folder to the home page / list folders
  serve.py run [--port N]                          run in the foreground

One server per user, on 127.0.0.1 (default port 8740, env BLUEDOC_PORT). State lives in
~/.bluedoc (env BLUEDOC_HOME): roots.json (folders the home page scans) and server.json (pid, port).
`open` registers the topmost ancestor folder named `docs`, else the doc's own folder.

URLs: /                      home page: every doc under the registered folders, searchable, filtered by
                             project, folder, type and status
      /<root>/<path>.bluedoc.json      the doc, rendered from its JSON on each request
      /<root>/<path>.bluedoc.json?raw=1   the JSON itself
      /__bluedoc/index.json  what the home page shows about every doc
      /__bluedoc/vendor/<path>  files under assets/vendor (HorizonUI for the home page)
Rendering validates the doc (errors show as a page) and records its meta.rev in the history file,
exactly as build.py does, so the page always shows the current JSON and its revisions.

Replies: Send answers posts to /__bluedoc/reply, Request changes to /__bluedoc/changes. Each is
saved next to the doc (<name>.reply.md/.json, <name>.changes.md/.json, overwritten each time) and
queued for `wait`, which returns the oldest unread one. Python 3.9+ standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
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
ROOTS_FILE, SERVER_FILE = STATE / "roots.json", STATE / "server.json"
DEFAULT_PORT = int(os.environ.get("BLUEDOC_PORT") or 8740)
SUFFIXES = (".bluedoc.json", ".blueprint.json")
SKIP_DIRS = {"node_modules", "build", "dist", "target", "out", "vendor", "Pods", "DerivedData", "__pycache__"}
MAX_DEPTH, MAX_BODY, SEARCH_CHARS = 8, 4 * 1024 * 1024, 8000   # SEARCH_CHARS keeps index.json small (~10 KB a doc)
KINDS = ("answers", "changes")
# meta.kind words that make a doc type "docs" when meta.type is unset; a kind with "review" is a "review"
DOCS_KINDS = {"architecture", "walkthrough", "runbook", "setup", "reference", "proposal", "change", "changes", "plan",
              "status", "guide", "design", "spec", "rfc", "adr", "overview", "tutorial", "onboarding", "explainer", "playbook"}
FINDING_SIZES = ("blocker", "major", "minor", "nit")


# ---------- docs on disk ----------

def is_doc(p: Path) -> bool:
    return p.name.endswith(SUFFIXES)


def stem(p: Path) -> str:
    for s in SUFFIXES:
        if p.name.endswith(s):
            return p.name[: -len(s)]
    return p.stem


def reply_file(doc: Path, kind: str, ext: str) -> Path:
    return doc.with_name(f"{stem(doc)}.{'reply' if kind == 'answers' else 'changes'}.{ext}")


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


def doc_for_url(path: str) -> Path | None:
    parts = unquote(path).lstrip("/").split("/", 1)
    if len(parts) != 2:
        return None
    r = slugs(load_roots()).get(parts[0])
    if not r:
        return None
    p = (r / parts[1]).resolve()
    if (r not in p.parents) or not is_doc(p) or not p.is_file():
        return None
    return p


def text_of(x, out: list[str], skip=("files", "code", "id", "href", "x", "y", "w", "h", "col", "row")) -> None:
    if isinstance(x, dict):
        for k, v in x.items():
            if k not in skip:
                text_of(v, out)
    elif isinstance(x, list):
        for v in x:
            text_of(v, out)
    elif isinstance(x, str):
        out.append(x)


def doc_type(meta: dict) -> str:
    """docs | review | other: meta.type when set, else read from meta.kind."""
    if meta.get("type") in build.DOC_TYPES:
        return meta["type"]
    words = set(re.findall(r"[a-z]+", str(meta.get("kind") or "").lower()))
    if "review" in words:
        return "review"
    return "docs" if words & DOCS_KINDS else "other"


def all_blocks(doc: dict):
    """Every block, depth-first, including the blocks inside checklist items."""
    def walk(blocks):
        for b in blocks or []:
            if isinstance(b, dict):
                yield b
                if b.get("type") == "checklist":
                    for it in b.get("items") or []:
                        if isinstance(it, dict):
                            yield from walk(it.get("blocks"))
    for s in doc.get("sections") or []:
        yield from walk(s.get("blocks"))


def preview(doc: dict, dtype: str) -> dict:
    """The card picture's data: the root drawing of the first canvas, the size of a review's diff, or block counts.
    Canvas nodes: x, y = top-left in canvas units, placed as the template does (centre = x/y, else col*250, row*160;
    size w/h, else 180x80, or 240x140 for a node with children); c = child count; edges = [from, to, kind] by node index."""
    blocks = list(all_blocks(doc))
    canvas = next((b for b in blocks if b.get("type") == "canvas" and b.get("nodes")), None)
    diffs = [b for b in blocks if b.get("type") == "diff"]
    findings = {k: 0 for k in FINDING_SIZES}
    for b in blocks:
        if b.get("type") == "checklist":
            for it in b.get("items") or []:
                if isinstance(it, dict) and it.get("state") in findings:
                    findings[it["state"]] += 1
    out: dict = {"findings": findings} if any(findings.values()) else {}
    if diffs and (dtype == "review" or not canvas):
        files = [f for d in diffs for f in d.get("files") or [] if isinstance(f, dict) and f.get("status") != "context"]
        bars = []
        for f in files:
            add, dele = f.get("add"), f.get("del")
            if add is None or dele is None:
                lines = [ln for hk in f.get("hunks") or [] if not hk.get("context") for ln in hk.get("lines") or []]
                add, dele = sum(ln.startswith("+") for ln in lines), sum(ln.startswith("-") for ln in lines)
            bars.append([int(add), int(dele)])
        out.update(kind="diff", files=len(files), add=sum(a for a, _ in bars), dele=sum(d for _, d in bars),
                   bars=sorted(bars, key=lambda x: -(x[0] + x[1]))[:12])
    elif canvas:
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
        edges = [[at[e["from"]], at[e["to"]], e.get("kind") or ""] for e in canvas.get("edges") or []
                 if isinstance(e, dict) and e.get("from") in at and e.get("to") in at]
        out.update(kind="canvas", nodes=nodes, edges=edges)
    else:
        count = lambda t: sum(b.get("type") == t for b in blocks)  # noqa: E731
        out.update(kind="counts", sections=len(doc.get("sections") or []), checklists=count("checklist"),
                   tables=count("table"), code=count("code"), cards=count("cards"))
    return out


_cache: dict[str, tuple[float, dict]] = {}
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


def summarize(p: Path) -> dict:
    """What the home page needs about one doc, cached by mtime."""
    st = p.stat()
    hit = _cache.get(str(p))
    if hit and hit[0] == st.st_mtime:
        info = dict(hit[1])
    else:
        info = {"title": stem(p), "errors": 0}
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            rep = build.validate(doc)
            meta = doc.get("meta") or {}
            dtype = doc_type(meta)
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
                "text": " ".join(words)[:SEARCH_CHARS], "preview": preview(doc, dtype),
            })
        except (OSError, ValueError, TypeError, AttributeError) as e:
            info.update({"errors": 1, "firstError": f"cannot read: {e}", "type": "other"})
        _cache[str(p)] = (st.st_mtime, info)
        info = dict(info)
    info["mtime"] = st.st_mtime
    info["revs"], info["built"] = history_info(p)
    for kind in KINDS:
        f = reply_file(p, kind, "json")
        if f.exists():
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

HISTORY_LOCK = threading.Lock()


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


def render(p: Path) -> tuple[int, str]:
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return 500, error_page(p, [f"cannot read: {e}"])
    rep = build.validate(doc)
    if rep.errors:
        return 422, error_page(p, rep.errors)
    try:
        with HISTORY_LOCK:
            history, _ = build.sync_history(p, doc)
    except build.HistoryError as e:
        return 422, error_page(p, [str(e)])
    return 200, build.build(doc, build.TEMPLATE.read_text(encoding="utf-8"), history)


# ---------- inbox: replies the agent waits for ----------

class Inbox:
    def __init__(self) -> None:
        self.cv = threading.Condition()
        self.queue: dict[str, list[dict]] = {}
        self.names: dict[str, str] = {}

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
                        return q.pop(i)
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

        def send(self, code: int, body: str | bytes, ctype: str = "text/html; charset=utf-8", cache: str = "no-store") -> None:
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

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
                return self.json(200, {"bluedoc": True, "home": "/", "to": INBOX.names.get(str(doc), default_to) if doc else default_to})
            if u.path == "/__bluedoc/url":
                return self.json(200, {"url": url_for(Path(q.get("doc", "")))})
            if u.path == "/__bluedoc/wait":
                m = INBOX.take(str(Path(q.get("doc", "")).resolve()), q.get("kind", "any"), min(float(q.get("timeout", 25)), 60))
                return self.json(200, {"message": m}) if m else self.send(204, b"")
            if u.path.startswith("/__bluedoc/"):
                return self.json(404, {"error": "not found"})
            doc = doc_for_url(u.path)
            if not doc:
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
            if path not in ("/__bluedoc/reply", "/__bluedoc/changes"):
                return self.json(404, {"error": "not found"})
            kind = "answers" if path.endswith("reply") else "changes"
            field = "items" if kind == "answers" else "annotations"
            if not isinstance(data.get(field), list):
                return self.json(400, {"error": f"not a bluedoc {kind} payload"})
            doc = doc_for_url(str(data.get("path") or ""))
            if not doc:
                return self.json(404, {"error": "the page's doc is not under a registered folder"})
            data["kind"] = kind
            md = str(data.get("markdown") or "").rstrip() + "\n"
            md_path, json_path = reply_file(doc, kind, "md"), reply_file(doc, kind, "json")
            md_path.write_text(md, encoding="utf-8")
            json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            INBOX.put(doc, {"kind": kind, "doc": str(doc), "markdown": md, "md_file": str(md_path), "json_file": str(json_path), "at": time.time()})
            print(f"{kind} for {doc}: {json_path}", flush=True)
            return self.json(200, {"ok": True, "saved": str(json_path)})

    return H


def run(port: int, to: str) -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(port, to))
    STATE.mkdir(parents=True, exist_ok=True)
    SERVER_FILE.write_text(json.dumps({"pid": os.getpid(), "port": port}) + "\n", encoding="utf-8")
    print(f"bluedoc server on http://127.0.0.1:{port}/ (folders: {', '.join(map(str, load_roots())) or 'none yet'})", flush=True)
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


def alive() -> bool:
    try:
        return call("/__bluedoc/ping")[1].get("bluedoc") is True
    except (OSError, ValueError, AttributeError):
        return False


def ensure_started(port: int) -> bool:
    if alive():
        return True
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
    p = sub.add_parser("wait", help="block until the reader sends answers or a change request for DOC")
    p.add_argument("doc", type=Path)
    p.add_argument("--kind", choices=("answers", "changes", "any"), default="any")
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
            print("lost the bluedoc server", file=sys.stderr)
            return 1
        if code == 200 and body and body.get("message"):
            m = body["message"]
            label = "answers" if m["kind"] == "answers" else "change request"
            print(f"--- bluedoc {label} ({m['json_file']}) ---")
            print(m["markdown"], end="")
            print("--- end ---", flush=True)
            return 0


if __name__ == "__main__":
    sys.exit(main())
