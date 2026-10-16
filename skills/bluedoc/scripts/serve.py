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
                                                   NAME alone fetches a pinned preset: daisyui
  serve.py snapshot DOC.json [--rev R] [--url URL] [--page ID] [--width PX]
                                                   record a website doc's live pages as revision R's snapshots
                                                   (default: the current rev; headless Chrome, BLUEDOC_CHROME)
  serve.py run [--port N]                          run in the foreground

One server per user, on 127.0.0.1 (default port 8740; when another program holds it, `open`, `start` and `unlock` take
the next free port up to 8759 and record it in server.json; env BLUEDOC_PORT or --port pins one, with no fallback). State lives in
~/.bluedoc (env BLUEDOC_HOME): roots.json (folders the home page scans), server.json (pid, port), key (mode 0600: the
secret that writes need) and state.db (SQLite, mode 0600: the reader's ticks, picks, comments and plan state per doc,
and every reply; statedb.py).
`open` registers the topmost ancestor folder named `docs`, else the doc's own folder, and restarts a running server
whose version or code differs from its own. A folder inside a registered one is not added; a wider one is added
next to the narrower ones, which keep their URLs (a doc's URL uses its deepest registered folder).

Writes need the key: in the X-Bluedoc-Key header (the CLI reads the key file; a page sends the copy it keeps in
localStorage) or in the bluedoc_key_<port> cookie (HttpOnly, SameSite=Strict). `open` and `unlock` print a link with
a ?key= token, good for an hour and any number of opens (a link preview or another browser opening it first doesn't
use it up); visiting it sets the cookie and redirects to the same URL without the token. A page with the cookie
fetches the key (GET /__bluedoc/key) and keeps it in localStorage, for browsers that drop cookies. ping and index.json
say whether the request carries the key (`unlocked`), so a page can tell the reader it can't save yet.

URLs: /                      home page: every doc under the registered folders, searchable, filtered by
                             project, folder, type and status
      /<root>/<path>.bluedoc.json      the doc, rendered from its JSON on each request
      /<root>/<path>.bluedoc.json?raw=1   the JSON itself
      /<root>/<path>.<png|jpg|jpeg|gif|webp|svg|mp4|webm>   media files under the folder, for `media` blocks
      /__bluedoc/index.json  what the home page shows about every doc
      /__bluedoc/ping?path=  server check (version, code hash, unlocked); with a doc's URL path, also who reads
                             replies and its saved approval
      /__bluedoc/key         the key, for a page with the key cookie (same origin, X-Bluedoc header); else 403
      /__bluedoc/state?path=<doc URL path>[&since=N]   GET the doc's reader state {version, state}; 204 when N is
                             the current version. PUT {path, import, ops: [[key, value or null]]} writes it: null
                             deletes, an import adds only keys the server lacks. Both need the X-Bluedoc header, the
                             PUT also the key. An `__ann:<id>` value the page can't draw is dropped from a PUT and
                             left out of a read.
      /__bluedoc/vendor/<path>  files under assets/vendor (HorizonUI, HeroUI, Tailwind's browser build, the Sketch font)
      /<root>/<dir>/<stem>.design/<artboard>.html[?rev=B&theme=T]   a design, presentation or website doc's screen: the
                             artboard's fragment (or revision B's, from the history) wrapped in kits/shell.html with
                             its framework, theme tokens and the inspector. Its own CSP: no network, `sandbox allow-scripts`,
                             framable by this server's pages only (no X-Frame-Options). An `icons` artboard's
                             screen is the icon sheet (kits/icon-sheet.html and .css) built from its layers in
                             <stem>.design/<artboard>/ (or rev B's, from the history), each layer a data: URI. A
                             website's live page at ?rev=B&w=<px> is its snapshot of rev B (the nearest width it has),
                             with the inspector and the same CSP, its images from the dev server allowed
      /__bluedoc/deck?path=<doc URL path>[&rev=B&theme=T&format=F]   a presentation (revision B's) exported, a read,
                             no key; 400 for any other doc type. format html (the default): one HTML file that plays
                             its slides offline (deck_html, assets/deck.html), sent as the attachment <stem>.html.
                             pdf: one 16:9 page per slide, no speaker notes (deck_pdf: headless Chrome prints the
                             file's print view), the attachment <stem>.pdf; 501 without Chrome (BLUEDOC_CHROME).
                             print: the HTML file shown in the tab, sandboxed (DECK_PRINT_CSP), which at #print
                             opens the print dialog: the page's PDF when the server has no Chrome. build.py --deck
                             writes the html and pdf files
      /__bluedoc/listing?path=<doc URL path>[&format=F&rev=B&platform=P&locale=L]   a storelisting (revision B's)
                             exported, a read, no key, nothing written beside the doc; 400 for any other doc type.
                             zip (the default): the fastlane layout of every shot and asset at its store size and
                             manifest.json (listing_zip, headless Chrome), the attachment <stem>.zip; platform and
                             locale narrow it. html: one file with both platform pages, offline (listing_html,
                             assets/listing.html). pdf: its print view (listing_pdf). print: that file in the tab, as
                             a deck's. zip and pdf: 501 without Chrome. X-Bluedoc-Warnings: a JSON list of what the
                             export should say (a font the PDF can't embed, store-rule errors). build.py --listing
                             writes the same files
      /__bluedoc/kit/<file>  the plain kit and inspector (assets/kits)
      /__bluedoc/fw/<name>/<path>   a framework add-framework copied
      /__bluedoc/fonts       the font families installed here (fonts.py: name and OS/2 of each TTF, OTF and TTC in
                             the font folders, rescanned when a folder changes), for a storelisting's caption font;
                             needs the X-Bluedoc header and the key
      /<root>/<path>.<css|js|mjs|font>   a project file a design board declares (frameworks[].files), and the
                             files its declared CSS names with url(); nothing else
      POST /__bluedoc/icons  {path, artboard, files: {name: base64}}: an icons artboard's PNG sets, which the page
                             draws, into <stem>.icons/<artboard>/ beside the doc. Only the export's own file names
                             (ios/AppIcon.appiconset/…, android/res/mipmap-*/…, play/icon-512.png), PNGs of their
                             exact size under 4 MB, Contents.json and the adaptive-icon XML; no link on the way.
      POST /__bluedoc/listing/upload  {path, platform, locale, set, slot, png: base64}: a storelisting shot's PNG,
                             checked against the set's rule (size, no alpha or tRNS, 8 MB, the slot range: 400 names
                             the rule and its source), into <stem>.listing/<platform>/<locale>/<set>/NN.png, a draft
                             until the agent records it; a file a revision records is never overwritten. {path,
                             discard: <file>} deletes a draft. No link on the way (save_listing_upload)
      POST /__bluedoc/listing/brand  {path, data: base64}: a storelisting's brand image (PNG, JPEG or WebP, 8 MB),
                             whose palette the page extracts, into <stem>.listing/brand/source.<ext> (save_brand_image)
      POST /__bluedoc/snapshot  {path, rev, page, w, html, external}: a live page as the reader sees it, as revision
                             rev's snapshot at w px (save_snapshot): rev must be the doc's current meta.rev, html at
                             most 8 MB; stored scriptless in <name>.snapshots/rev-<rev>/<page>@<w>.html beside the doc
Live pages (website docs): a page whose `url` names a dev server on a loopback host (build.live_url_problem refuses
any other) is shown through a proxy this server starts for that origin on first render: its own listener on
127.0.0.1:<free port>, so the site's root-relative URLs, modules and HMR WebSocket work unchanged. It answers only
requests whose Host is itself (DNS rebinding), forwards everything else to the dev server (Host and Origin rewritten
to it, this server's key cookie dropped, WebSocket upgrades tunnelled), and into each HTML response injects
<script src="/__bluedoc/inspector.js" data-parents="<this server's origins>" data-origin="<the dev server>">
(kits/inspector.js, served by the proxy) and a style hiding dev toolbars (astro-dev-toolbar, nextjs-portal). Its
responses lose X-Frame-Options and any frame-ancestors, and gain frame-ancestors for this server's origins. The page
frames it with `sandbox allow-scripts allow-same-origin`: the proxy's origin (another port) is not this server's, so
the site keeps its storage and modules and reaches nothing of bluedoc's. A doc page names its proxies in its bp-live
element ({dev server origin: proxy port}), and its CSP's frame-src allows exactly those. A dev server that isn't up
answers 502.
The proxy also pins viewport heights for the page's Full page view (pin_viewport_units): in HTML (<style> and style
attributes), CSS and a dev server's CSS-as-JS modules, N vh (svh, lvh, dvh, vb) becomes calc(N * var(--bd-vh, 1vh)),
which is the unit itself until the inspector sets --bd-vh.
Snapshots: a live page shows the site as it is now, so the page shows an earlier revision's live page from its
snapshot. The inspector serializes the page (kits/inspector.js snapshot(): no scripts, stylesheets inlined as text,
images and the fonts the page loaded as data: URIs up to 1 MB each and 4.5 MB in all, larger ones left on the dev
server); the page posts it for its current revision when the reader sends answers, changes or an approval, and when a
live page in Full page first settles at a width that revision has none of. `snapshot` takes the same through
headless Chrome and a proxy of its own, also for an earlier revision that has none (e.g. from a checkout of that
revision on another port, --url). An earlier revision's snapshot is never replaced.
Rendering validates the doc (errors show as a page), shows its meta.rev as the latest revision of the history file
without writing it (build.py records revisions), and fills each `diff` block that references a git range
(diffref.py: its cache, local git, then `gh pr diff`), so the page always shows the current JSON.
HTML pages carry a Content-Security-Policy (hashes of their inline scripts, no framing), and a doc page carries its
reader state and the hash of the JSON it shows in its bp-state element ({version, state, docHash}; null without
sqlite3).

Replies: Send answers posts to /__bluedoc/reply, Request changes to /__bluedoc/changes, Approve (plan, design,
presentation, website) to /__bluedoc/approve. Each becomes a row in state.db, queued for `wait`, which returns the oldest unread one
(GET /__bluedoc/wait needs the X-Bluedoc header and the key) and marks it delivered; a restart keeps the queue. The
first start with a new state.db imports the <name>.reply/.changes/.approval files of earlier versions and
inbox.json's delivered marks, and leaves the files. An approval posts the docHash and rev the page showed: the server
answers 409 when either differs from the doc's current JSON (and a design's screen files: build.approval_hash) and
meta.rev. It holds while the doc is unchanged, or changed only by progress since (build.approval_carries: steps
marked done, a pick carried over); the page, ping and index.json get it as {rev, at, carried}.
Python 3.9+ standard library only.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import http.client
import io
import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402
import fonts  # noqa: E402
import listing  # noqa: E402

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
PORT_PINNED = bool(os.environ.get("BLUEDOC_PORT"))   # a port the user chose: no fallback when it is taken
PORT_SPAN = 20   # without a pinned port, the server takes the first free one of DEFAULT_PORT … DEFAULT_PORT + 19
UNLOCK_TTL = 3600   # seconds a ?key= token stays good, for any number of opens
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
TOKENS: dict[str, float] = {}   # ?key= tokens: expiry (monotonic)
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
    """(build.approval_hash, doc.id, meta.rev as a string) of the doc, cached by the mtimes of the doc, its screen
    files and its icons artboards' layer folders (a layer added later changes its folder's); (None, None, '') if
    unreadable."""
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
        board = build.board_of(doc) if isinstance(doc, dict) else None
        screens += [build.icon_dir(p, a) for a in (board or {}).get("artboards") or []
                    if build.is_icons(a) and isinstance(a.get("id"), str) and build.ID_RE.match(a["id"])]
        if listing.listing_of(doc):   # a re-shoot changes a storelisting's revision (listing.file_hashes)
            screens.append(listing.listing_dir(p) / "captures" / "captures.json")
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
    """The mtimes doc_info's cache keys on: the doc's, its screen files' and its layer folders'."""
    doc_info(p)
    hit = _doc_info.get(str(p))
    return hit[0] if hit else ()


def doc_id(p: Path) -> str | None:
    return doc_info(p)[1]


_carried: dict[str, tuple[tuple, bool]] = {}


def approval_of(doc: Path, row: dict | None) -> dict | None:
    """The approval row as {rev, at, carried} (rev and at as the page posted them), or None. It holds while the doc's
    JSON and screen files are the ones approved (carried: false), or when every change since is progress
    (build.approval_carries: carried: true), so marking steps done keeps a plan approved. An approval of an earlier rev
    that no longer holds comes back with carried: false, so the page can say there are changes since; one of the
    current rev that an edit in place changed is None: the doc awaits approval again."""
    if not row or not row["doc_hash"]:
        return None
    try:
        posted = json.loads(row["payload"])
    except ValueError:
        posted = {}
    posted = posted if isinstance(posted, dict) else {}
    out = {"rev": str(posted.get("rev", row["rev"]) or ""), "at": posted.get("at", row["at"])}
    current, _, rev = doc_info(doc)
    if row["doc_hash"] == current:
        return {**out, "carried": False}
    if approval_carried(doc, row, out["rev"], posted):
        return {**out, "carried": True}
    return {**out, "carried": False} if out["rev"] != rev else None


def approval_carried(doc: Path, row: dict, rev: str, posted: dict) -> bool:
    """build.approval_carries for the doc on disk against its history, cached by the approval, the doc's hash and
    the history file's mtime."""
    hp = build.history_path(doc)
    key = (row["id"], doc_hash(doc), mtime(hp))
    hit = _carried.get(str(doc))
    if hit and hit[0] == key:
        return hit[1]
    # an item approved without a pick means its recommendation (types/plan.md), so recording that as `choice` is progress
    picks = {f"{a.get('checklist')}:{a.get('item')}": a.get("choice") or a.get("recommend") for a in posted.get("answers") or []
             if isinstance(a, dict) and isinstance(a.get("choice") or a.get("recommend"), str) and (a.get("choice") or a.get("recommend"))}
    try:
        d = json.loads(doc.read_text(encoding="utf-8"))
        ok = isinstance(d, dict) and build.approval_carries(build.load_history(hp), rev, row["doc_hash"], d, doc, picks)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        ok = False
    _carried[str(doc)] = (key, ok)
    return ok


def saved_approval(doc: Path) -> dict | None:
    """The doc's newest approval (approval_of), or None."""
    return approval_of(doc, DB.approval(str(doc.resolve())) if DB else None)


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
    """A ?key= token that sets the key cookie, good for UNLOCK_TTL seconds and any number of uses: an earlier fetch
    of the link (a link preview, an agent's fetch tool, another browser) doesn't use it up."""
    token, now = secrets.token_urlsafe(24), time.monotonic()
    with TOKENS_LOCK:
        for t in [t for t, end in TOKENS.items() if end < now]:
            del TOKENS[t]
        TOKENS[token] = now + UNLOCK_TTL
    return token


def unlock_token_live(token: str) -> bool:
    """Whether token is a live ?key= token."""
    with TOKENS_LOCK:
        end = TOKENS.get(token)
    return end is not None and end >= time.monotonic()


def is_key(given: str | None) -> bool:
    """Whether given is the server's key (constant-time)."""
    return bool(SECRET and given) and hmac.compare_digest(given.encode(), SECRET.encode())


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
    build.board_layout (with the board's links, for `layout: "flow"`) and shifted so the board's top-left is 0, 0;
    links = [i, j] by artboard index, one per pair of those 12 that a link joins (at most 24; none for `back`).
    presentation: count = slides, notes = slides with speaker notes, slides = the fidelity of the first 9 in deck
    order (as Present plays them: top to bottom, then left to right).
    website: count = pages, sections = their sections, live = pages shown from a dev server, pages = the first 4 as
    {sections (at most 8), live, fidelity}.
    storelisting: platforms = {platform: [{row, sets: [[set, shots]], level}]}: each platform page's text, Shared and
    device sections (listing.sections, default locale), how many shots each set has and the worst check on it (ok,
    warn, err: listing.store_checks); storeErrors = the store-rule errors, which the card shows as dots, not as a
    doc that doesn't build.
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
        links = build.board_links(doc, doc_path) if board else []
        layout = build.board_layout(board, links) if board else {}
        if layout:
            x0, y0 = min(v[0] for v in layout.values()), min(v[1] for v in layout.values())
            info = {a["id"]: a for a in board.get("artboards") or [] if isinstance(a, dict)}
            arts, at = [], {}
            for aid, (x, y, w, h) in list(layout.items())[:12]:
                a = info.get(aid) or {}
                at[aid] = len(arts)
                arts.append({"x": round(x - x0), "y": round(y - y0), "w": round(w), "h": round(h),
                             "device": str(a.get("device") or ""), "fidelity": str(a.get("fidelity") or "")})
            pairs: dict[frozenset, list[int]] = {}   # one line per pair of screens, whichever way and however many links
            for ln in links:
                i, j = at.get(ln.get("from")), at.get(ln.get("to"))
                if i is not None and j is not None and i != j:
                    pairs.setdefault(frozenset((i, j)), [i, j])
            out = {"count": len(layout), "artboards": arts}
            if pairs:
                out["links"] = list(pairs.values())[:24]
            return out
    elif dtype == "presentation":
        board = build.board_of(doc)
        layout = build.board_layout(board) if board else {}
        if layout:
            info = {a["id"]: a for a in board.get("artboards") or [] if isinstance(a, dict)}
            order = sorted(layout, key=lambda aid: (layout[aid][1], layout[aid][0]))
            return {"count": len(order), "notes": sum(bool((info.get(aid) or {}).get("notes")) for aid in order),
                    "slides": [str((info.get(aid) or {}).get("fidelity") or "") for aid in order[:9]]}
    elif dtype == "website":
        pages = build._artboards(doc)
        if pages:
            secs = [[s for s in p.get("sections") or [] if isinstance(s, dict)] if isinstance(p.get("sections"), list) else []
                    for p in pages]
            return {"count": len(pages), "sections": sum(map(len, secs)), "live": sum(map(build.is_live, pages)),
                    "pages": [{"sections": min(8, len(ss)), "live": build.is_live(p), "fidelity": str(p.get("fidelity") or "")}
                              for p, ss in list(zip(pages, secs))[:4]]}
    elif dtype == "storelisting":
        lb = listing.listing_of(doc)
        if lb:
            rules = listing.load_rules()
            loc = lb.get("defaultLocale") or next(iter(lb.get("locales") or []), None)
            known = {p["id"] for p in rules["platforms"]}
            plats = [p for p in lb.get("platforms") or [] if p in known]
            found = listing.store_checks(doc, doc_path, rules)

            def level(p: str, section: str) -> str:
                ls = {f["level"] for f in found if f["section"] == section and (not f["platforms"] or p in f["platforms"])}
                return "err" if "err" in ls else "warn" if ls else "ok"
            return {"platforms": {p: [{"row": r, "sets": [], "level": level(p, r)} for r in ("text", "shared")]
                                  + [{"row": s["row"], "sets": [[x["set"], len(x["shots"])] for x in s["sets"]], "level": level(p, s["row"])}
                                     for s in listing.sections(lb, listing.shots_of(doc), rules, p, loc)] for p in plats},
                    "storeErrors": sum(f["level"] == "err" for f in found)}
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
                # a storelisting's store-rule errors aren't "doesn't build": its card shows them (card()'s storeErrors)
                "items": items, "errors": len(rep.blocking), "firstError": rep.blocking[0] if rep.blocking else "",
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
            at = dt.datetime.fromisoformat(row["at"]).timestamp()
            if kind != "approval":
                info[kind] = {"at": at, "rev": row["rev"]}
            elif ap := approval_of(p, row):   # None: approved other content of this rev, awaiting again
                info[kind] = {"at": at, "rev": ap["rev"], "carried": ap["carried"]}
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
LIVE_BLOCK = re.compile(r'<script type="application/json" id="bp-live">(.*?)</script>', re.S)


def page_csp(html: str) -> str:
    """The page's Content-Security-Policy: its own inline scripts by hash (JSON data blocks don't run), same-origin
    files, data: images, media and fonts, and no framing. A website page may also frame its live pages' proxies (the
    ports in its bp-live element), on this machine only."""
    hashes = sorted({"'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"
                     for attrs, body in INLINE_SCRIPT.findall(html)
                     if "src=" not in attrs and "application/json" not in attrs})
    frames = ""
    m = LIVE_BLOCK.findall(html)
    try:
        live = json.loads(m[-1]) if m else None
    except ValueError:
        live = None
    ports = sorted({p for p in live.values() if isinstance(p, int) and 0 < p < 65536}) if isinstance(live, dict) else []
    if ports:
        frames = "frame-src 'self' " + " ".join(f"http://{h}:{p}" for p in ports for h in ("127.0.0.1", "localhost")) + "; "
    return ("default-src 'self'; script-src " + " ".join(["'self'", *hashes]) + "; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; media-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; "
            + frames + "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


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
    if rep.blocking:   # a storelisting's store-rule errors don't stop the page: its Checks tab lists them
        return 422, error_page(p, rep.blocking)
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
    # the seed: the reader state, the hash of what this page shows (Approve posts it) and the saved approval
    state = page_state(p)
    return 200, build.build(doc, build.TEMPLATE.read_text(encoding="utf-8"), history, diff_path=p, problems=[],
                            state=state and {**state, "docHash": shown, "approval": saved_approval(p)},
                            live=LIVE.for_doc(doc),
                            snaps=build.snapshot_index(p) if build.doc_type(doc.get("meta") or {}) == "website" else None)


# ---------- design screens ----------

# /<root>/<dir>/<stem>.design/<artboard id>.html: one artboard's screen fragment wrapped in its kit
SCREEN_URL = re.compile(r"^(/(?:[^/]+/)+)([^/]+)\.design/([a-z0-9][a-z0-9-]*)\.html$")
# what kits, declared framework files, their url() targets and store copies may be: nothing that renders as a page
ASSET_TYPES = {".css", ".js", ".mjs", ".woff", ".woff2", ".ttf", ".otf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
CORS_TYPES = {".mjs", ".woff", ".woff2", ".ttf", ".otf"}   # fetched in CORS mode: an opaque-origin frame needs ACAO *
CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""")
EXTERNAL_REF = re.compile(r"(?i)^(?:data:|[a-z][a-z0-9+.-]*:|//|#)")
PLAIN_KIT = ("base.css", "wireframe.css")
# the built-in frameworks under assets/vendor: the files a screen loads, in order. The Tailwind ones also compile
# the screen's Tailwind classes, in the frame, with Tailwind's browser build.
VENDOR_KITS = {"horizon": ("horizon-ui/horizon-ui.css", "horizon-ui/react.js", "horizon-ui/horizon-ui.js"),
               "heroui": ("heroui/heroui.min.css", "heroui/tailwind.js"), "tailwind": ("heroui/tailwind.js",)}
TAILWIND_KITS = ("heroui", "tailwind")
MOTION_VARS = {"fast": "--dur-fast", "base": "--dur-base", "slow": "--dur-slow", "ease": "--ease"}


def screen_csp(host: str, img_from: tuple[str, ...] = ()) -> str:
    """A screen's Content-Security-Policy: no network, no forms, framed only by this server's pages, and sandboxed
    even when opened on its own. The explicit origin backs 'self', which browsers read differently in an
    opaque-origin document; host is one guard() accepted. img_from: a live page snapshot's dev server, which keeps the
    images and fonts too large to inline."""
    o, ext = f"http://{host}", "".join(f" {x}" for x in img_from)
    return (f"default-src 'none'; script-src 'self' {o} 'unsafe-inline'; style-src 'self' {o} 'unsafe-inline'; "
            f"img-src 'self' {o} data: blob:{ext}; font-src 'self' {o} data:{ext}; connect-src 'none'; form-action 'none'; "
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
    plain, horizon, heroui and tailwind ship; a frameworks[] entry loads its declared files or its store copy, and a
    store named heroui or tailwind with no copy loads the shipped one. When any of that is missing, the screen gets
    the plain kit and the label for its notice."""
    kit = lambda name: (asset_kind(KITS / name), KITS / name, f"/__bluedoc/kit/{name}?v={kit_version()}")  # noqa: E731
    plain = [kit(n) for n in PLAIN_KIT]
    if fw_id == "plain":
        return plain, None, None
    wire = [kit("wireframe.css")] if fidelity in ("wireframe", "sketch") else []

    def vendored(name: str) -> tuple[list, list[Path] | None, None]:
        v = vendor_version()
        return ([(asset_kind(VENDOR / r), VENDOR / r, f"/__bluedoc/vendor/{r}?v={v}") for r in VENDOR_KITS[name]] + wire,
                [] if name in TAILWIND_KITS else None, None)
    entry = next((f for f in board.get("frameworks") or [] if isinstance(f, dict) and f.get("id") == fw_id), None)
    if fw_id in VENDOR_KITS and (entry is None or fw_id not in build.SHIPPED_PRESETS):
        return vendored(fw_id)
    label = str((entry or {}).get("label") or fw_id)
    if entry and isinstance(entry.get("store"), str):
        man = store_manifest(entry["store"])
        if man:
            d, v = build.frameworks_dir() / entry["store"], str(man.get("sha256") or "")[:12]
            assets = [(asset_kind(d / f), d / f, f"/__bluedoc/fw/{quote(entry['store'])}/{quote(f)}?v={v}") for f in man["load"]]
            sources = [d / f for f in man.get("sources") or []] if man.get("compiler") == "tailwind" else None
            return assets + wire, sources, None
        if entry["store"] in build.SHIPPED_PRESETS:
            return vendored(entry["store"])
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


INTER_FONT = VENDOR / "fonts" / "Inter-Variable.woff2"   # a shot's default caption font (OFL)
SHOT_KITS = ("shot.css", "shot-styles.css")


def shot_parts(doc: dict, a: dict, inline: bool) -> tuple[list[str], str, str]:
    """What a storelisting shot or asset adds to its screen document: (head tags: the shot kit after the plain kit and
    the Inter font face; :root declarations: the listing's brand tokens; the tail: its data (#bd-shot-data) and
    kits/shot.js, after the fragment). The data: the sets it fills with their frame and UI sizes from the store rules,
    every locale's caption strings, the default locale and the style (the shot's own, else the listing's)."""
    lb = listing.listing_of(doc) or {}
    rules = listing.load_rules()
    v = kit_version()
    head = [asset_tag("css", KITS / n, f"/__bluedoc/kit/{n}?v={v}", inline) for n in SHOT_KITS]
    font = data_uri(INTER_FONT) if inline else f"/__bluedoc/vendor/fonts/{INTER_FONT.name}?v={vendor_version()}"
    head.append('<style>@font-face { font-family: "Inter"; font-style: normal; font-weight: 100 900; font-display: block; '
                f'src: url("{font}") format("woff2"); }}</style>')
    brand = lb.get("brand") if isinstance(lb.get("brand"), dict) else {}
    pal = brand.get("palette") if isinstance(brand.get("palette"), dict) else {}
    out = {f"--brand-{k}": c for k, c in pal.items() if k in listing.PALETTE_ROLES and isinstance(c, str) and listing.HEX.match(c)}
    f = brand.get("font") if isinstance(brand.get("font"), dict) else {}
    if isinstance(f.get("family"), str) and listing.FONT_FAMILY.match(f["family"]):
        out["--bd-font-caption"] = f'"{f["family"]}", Inter, system-ui, sans-serif'
    if f.get("weight") in range(100, 1000, 100):
        out["--bd-weight-caption"] = str(f["weight"])
    sets = listing.by_id(rules, "sets")
    data: dict = {"id": a["id"], "kind": a.get("device"), "sets": {}, "asset": None,
                  "strings": {k: s for k, s in (lb.get("strings") or {}).items() if isinstance(s, dict)},
                  "defaultLocale": lb.get("defaultLocale") or next(iter(lb.get("locales") or []), None),
                  # the style each platform page shows the shot in (listing.style, its platform's, the shot's own)
                  "style": {**listing.effective_style(lb, "", a),
                            "platforms": {p["id"]: listing.effective_style(lb, p["id"], a) for p in rules["platforms"]}}}
    for s in a.get("sets") or [] if a.get("device") == "shot" else []:
        r = sets.get(s) if isinstance(s, str) else None
        if r and "author" in r:
            (w, h), (uw, uh) = listing.frame_size(r), listing.ui_size(r)
            data["sets"][s] = {"w": w, "h": h, "uiW": uw, "uiH": uh, "raw": bool(r.get("raw")), "platform": r["platform"], "row": r["row"]}
    asset = listing.by_id(rules, "assets").get(a.get("asset")) if a.get("device") == "asset" else None
    if asset and "author" in asset:
        w, h = listing.frame_size(asset)
        data["asset"] = {"w": w, "h": h, "platform": asset["platform"]}
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")   # no '</script' in a string reaches the parser
    tail = (f'<script type="application/json" id="bd-shot-data">{blob}</script>\n'
            + asset_tag("js", KITS / "shot.js", f"/__bluedoc/kit/shot.js?v={v}", inline) + "\n")
    return head, "".join(f" {k}: {val};" for k, val in out.items()), tail


def wrap_screen(doc: dict, doc_path: Path, artboard_id: str, fragment: str, *, inline: bool = False,
                theme: str | None = None, deck: bool = False) -> str:
    """A screen as a whole HTML document: kits/shell.html filled with the artboard's framework (or the plain kit and
    a notice when it's missing), its fidelity, the device's and theme's variables, the inspector, then the fragment.
    inline puts every file in the document (an -o file); else they load from this server. deck (a deck file's slide,
    deck_html, or an exported listing shot, listing_pages) inlines too, with DECK_FRAME_SCRIPT in the inspector's place
    and the hand font only on a sketch slide.
    KeyError: no such artboard."""
    inline = inline or deck
    board = build.board_of(doc) or {}
    a = next((x for x in board.get("artboards") or [] if isinstance(x, dict) and x.get("id") == artboard_id), None)
    if a is None:
        raise KeyError(artboard_id)
    fidelity = a.get("fidelity") if a.get("fidelity") in build.FIDELITIES else "hifi"
    if a.get("device") == "icons":   # an icon sheet (icon_fragment) brings its own kit
        sheet = KITS / "icon-sheet.css"
        assets, sources, missing = [("css", sheet, f"/__bluedoc/kit/{sheet.name}?v={kit_version()}")], None, None
    else:
        fw_id = str(a.get("framework") or board.get("framework") or "plain")
        assets, sources, missing = framework_assets(board, fw_id, Path(doc_path), fidelity)
    head = [asset_tag(kind, f, url, inline) for kind, f, url in assets]
    if sources is not None:
        text = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in sources)
        if '@import "tailwindcss"' not in text:
            text = '@import "tailwindcss";\n' + text
        head.append(f'<style type="text/tailwindcss">{raw_text(text, "style")}</style>')
    if a.get("device") == "page":   # a website's mockup page: its viewport units pinned, as the proxy pins a live page's
        fragment = pin_html_units(fragment)
    shot_head, shot_vars, shot_tail = shot_parts(doc, a, inline) if a.get("device") in ("shot", "asset") else ([], "", "")
    head += shot_head
    inspector = KITS / "inspector.js"
    slots = {
        "html_class": f"fid-{fidelity}" + (" shot-pending" if shot_tail else ""), "artboard": esc(artboard_id),
        "fallback": esc(missing or ""),
        "title": esc(str(a.get("title") or artboard_id)), "vars": screen_vars(doc, board, a, theme) + shot_vars,
        "hand_font": (data_uri(HAND_FONT) if not deck or fidelity == "sketch" else "data:,") if inline
        else f"/__bluedoc/vendor/fonts/{HAND_FONT.name}?v={vendor_version()}",
        "inspector": DECK_FRAME_SCRIPT if deck else asset_tag("js", inspector, f"/__bluedoc/kit/inspector.js?v={kit_version()}", inline),
        "head": "\n".join(head),
        "notice": f'<div id="bd-notice" role="status">{esc(missing)} not found: showing the plain kit</div>\n' if missing else "",
        "body": fragment, "shot": shot_tail,
    }
    shell = (KITS / "shell.html").read_text(encoding="utf-8")
    return re.sub(r"\{\{(\w+)\}\}", lambda m: slots[m[1]], shell)   # one pass: the fragment's own {{ }} stay as written


def current_screen_text(doc: dict, doc_path: Path, aid: str, roots: list[Path] | None) -> str | None:
    """An artboard's screen file's text as it is now; None without one. roots (the server's folders): the file must
    be in a <stem>.design folder inside one of them; None (the CLI): anywhere."""
    f = build.screen_paths(doc, doc_path).get(aid)
    if not f or (roots is not None and not (f.resolve().parent.name.endswith(".design") and under_roots(f.resolve(), roots))):
        return None
    try:
        return f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def screen_for_url(path: str, rev: str | None) -> tuple[Path, dict, str, str] | None:
    """(doc file, the doc as of rev, artboard id, fragment) for a screen URL; None unless the doc is a board doc (design,
    presentation or website) under a registered folder with that artboard and its screen file (or that revision's
    recorded HTML). A website's live page has no screen file, so no screen URL."""
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
        fragment = current_screen_text(doc, doc_path, aid, load_roots())
    if isinstance(doc, dict) and icon_artboard(doc, aid):   # no screen file: the sheet, built from the layers
        fragment = icon_fragment(doc, doc_path, aid, rev, None if rev else load_roots())
    board = build.board_of(doc) if isinstance(doc, dict) else None
    if fragment is None or not board or not any(isinstance(a, dict) and a.get("id") == aid for a in board.get("artboards") or []):
        return None
    return doc_path, doc, aid, fragment


# ---------- a presentation as one HTML file (GET /__bluedoc/deck, build.py --deck) ----------

DECK_PLAYER = HERE.parent / "assets" / "deck.html"
# a deck file's slide, in the inspector's place: a click on anything but a control, the player's keys and Ctrl/Cmd+P
# (the whole deck's print view) go to the player (assets/deck.html), which never hears a sandboxed frame's events
DECK_FRAME_SCRIPT = (
    "<script>(()=>{const K=['ArrowLeft','ArrowRight','ArrowUp','ArrowDown',' ','PageUp','PageDown','Home','End','n','N','f','F'],"
    "P=m=>parent.postMessage(m,'*'),C='a,button,input,select,textarea,label,summary,video,audio,[contenteditable],[role=button],[tabindex]';"
    "addEventListener('click',e=>{if(e.button===0&&!e.defaultPrevented&&!(e.target.closest&&e.target.closest(C)))P({deck:'click'})});"
    "addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&!e.altKey&&(e.key==='p'||e.key==='P')){e.preventDefault();P({deck:'print'});return}"
    "if(e.metaKey||e.ctrlKey||e.altKey||!K.includes(e.key)||(e.target.closest&&"
    "e.target.closest('input,select,textarea,[contenteditable]')))return;e.preventDefault();P({deck:'key',key:e.key,shift:e.shiftKey})})})()</script>")
# a <style> or <script> block at least this long that two slides carry (their kit, framework, shell) is stored once
DECK_SHARED_MIN = 512
DECK_BLOCK = re.compile(r"(?is)<(style|script)\b[^>]*>.*?</\1\s*>")
DECK_FORMATS = ("html", "pdf", "print")
# the deck file shown in a tab of this server (format=print): an opaque origin that reaches nothing of bluedoc's, and
# may open the print dialog; the file's own <meta> CSP (no network) holds too
DECK_PRINT_CSP = "sandbox allow-scripts allow-modals; frame-ancestors 'none'"
DECK_PDF_NEEDS = "a PDF needs Chrome or Chromium: set BLUEDOC_CHROME to its path"


class DeckError(ValueError):
    """Why a doc can't be a deck file."""


def safe_url(u: str) -> str:
    """template.html safeUrl: web and mail links, relative paths and #fragments; anything else becomes '#'."""
    m = re.match(r"(?i)^([a-z][a-z\d+.-]*):", re.sub(r"[\x00-\x20]", "", u))
    return u if not m or m[1].lower() in ("http", "https", "mailto") else "#"


def md_inline(src: str) -> str:
    """template.html inline(): `code`, **bold**, *italic* and [links](url), the rest escaped."""
    codes: list[str] = []

    def code(m: re.Match) -> str:
        codes.append(m[1])
        return f"\0{len(codes) - 1}\0"
    t = re.sub(r"`([^`]+)`", code, esc(src).replace("'", "&#39;"))
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(^|[\s(])\*([^*\s][^*]*)\*", r"\1<em>\2</em>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{safe_url(m[2])}" target="_blank" rel="noopener noreferrer">{m[1]}</a>', t)
    return re.sub(r"\0(\d+)\0", lambda m: f"<code>{codes[int(m[1])]}</code>", t)


MD_BULLET, MD_NUMBER = re.compile(r"^\s*[-*] "), re.compile(r"^\s*\d+[.)] ")


def md_html(src: str) -> str:
    """template.html md(): paragraphs and bulleted or numbered lists of md_inline text, as the page draws notes."""
    out = []
    for block in re.split(r"\n\s*\n", str(src or "").strip()):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        for tag, mark in (("ul", MD_BULLET), ("ol", MD_NUMBER)):
            if all(mark.match(ln) for ln in lines):
                out.append(f"<{tag}>" + "".join("<li>" + md_inline(mark.sub("", ln)) + "</li>" for ln in lines) + f"</{tag}>")
                break
        else:
            out.append("<p>" + md_inline(" ".join(lines)) + "</p>")
    return "".join(out)


def deck_slides(doc: dict) -> list[dict]:
    """A presentation's slides in the order Present plays them (template.html `deck`): by row on the board (top
    first), left to right in a row, ties in the doc's order."""
    at = build.board_layout(build.board_of(doc) or {})
    seen, out = set(), []
    for a in build._artboards(doc):
        if a.get("device") == "slide" and a["id"] in at and a["id"] not in seen:
            seen.add(a["id"])
            out.append(a)
    return sorted(out, key=lambda a: (at[a["id"]][1], at[a["id"]][0]))


def shared_parts(pages: list[str | None]) -> tuple[list[str], list[list | None]]:
    """(assets, parts): each page as text runs and indices into assets, the <style> and <script> blocks at least
    DECK_SHARED_MIN long that two pages carry, stored once (a kit, a framework, a font). None stays None."""
    found: dict[str, int] = {}   # each long block: how many pages carry it
    for p in pages:
        for t in {m[0] for m in DECK_BLOCK.finditer(p or "") if len(m[0]) >= DECK_SHARED_MIN}:
            found[t] = found.get(t, 0) + 1
    assets: list[str] = []
    index: dict[str, int] = {}

    def parts(page: str) -> list:
        out, last = [], 0
        for m in DECK_BLOCK.finditer(page):
            if found.get(m[0], 0) > 1:
                if m[0] not in index:
                    index[m[0]] = len(assets)
                    assets.append(m[0])
                out += [page[last:m.start()], index[m[0]]]
                last = m.end()
        return [x for x in out + [page[last:]] if x != ""]
    return assets, [parts(p) if p is not None else None for p in pages]


def deck_html(doc: dict, doc_path: Path, rev: str | None = None, theme: str | None = None,
              roots: list[Path] | None = None) -> str:
    """A presentation as one self-contained HTML file that plays its slides anywhere, offline (assets/deck.html): each
    slide wrapped as Present shows it (wrap_screen with deck: its kit or framework inline, the theme's tokens) behind
    build.STANDALONE_SCREEN_CSP, in deck_slides order, with its speaker notes as HTML. A <style> or <script> block two
    slides share is stored once; the player puts each slide's document back together for its sandboxed srcdoc frame.
    doc is the doc on disk; rev another revision of it (from the history), theme a theme id (else the brief's pick).
    roots: the server's folders, which a screen file must be in (None, the CLI: anywhere). A slide without its screen
    text plays as a placeholder. DeckError: not a presentation, an unknown revision, no slides."""
    kind = build.doc_type(doc.get("meta") if isinstance(doc.get("meta"), dict) else {})
    if kind != "presentation":
        raise DeckError(f"only a presentation exports as a deck, not a doc of type {kind}")
    if rev is not None and rev != str((doc.get("meta") or {}).get("rev") or ""):
        doc = doc_at(doc_path, doc, rev)
        if doc is None:
            raise DeckError(f"no revision {rev} in the doc's history")
    else:
        rev = None
    slides = deck_slides(doc)
    if not slides:
        raise DeckError("the deck has no slides")
    pages = []
    for a in slides:
        text = build.screen_source(doc_path, a["id"], rev) if rev else current_screen_text(doc, doc_path, a["id"], roots)
        pages.append(None if text is None else build.with_screen_csp(wrap_screen(doc, doc_path, a["id"], text, deck=True, theme=theme)))
    assets, parts = shared_parts(pages)
    shown = [{"id": a["id"], "title": str(a.get("title") or a["id"]),
              "notes": md_html(a["notes"]) if isinstance(a.get("notes"), str) else "",
              "parts": p} for a, p in zip(slides, parts)]
    data = {"w": build.DEVICES["slide"]["w"], "h": build.DEVICES["slide"]["h"], "assets": assets, "slides": shown}
    fill = {"__DECK_TITLE__": esc(str(doc.get("title") or build.doc_stem(Path(doc_path)))),
            "__DECK_CSP__": build.STANDALONE_SCREEN_CSP, "__DECK_DATA__": build._script_json(data)}
    return re.sub("|".join(fill), lambda m: fill[m[0]], DECK_PLAYER.read_text(encoding="utf-8"))


def deck_pdf(html: str, chrome: str) -> bytes:
    """A deck file (deck_html) as a PDF: one 16:9 page per slide in deck order, no speaker notes, each slide as the
    file draws it (kit, theme, fonts) with its motion settled and its backgrounds printed. Headless Chrome opens the
    file at #print, its print view (every slide a page of 1920 × 1080 CSS px, assets/deck.html), and prints it with
    Page.printToPDF. chrome: find_chrome's path. RuntimeError or OSError: Chrome failed."""
    with tempfile.TemporaryDirectory(prefix="bluedoc-deck-") as d:
        f = Path(d) / "deck.html"
        f.write_text(html, encoding="utf-8")
        with HeadlessChrome(chrome) as ch:
            return ch.print_pdf(f.as_uri() + "#print")


# ---------- a storelisting exported (GET /__bluedoc/listing, build.py --listing) ----------
# zip: the fastlane layout (listing.export_plan) of every shot and asset at its store size, rendered by headless Chrome
# from its screen file, each PNG made 24-bit RGB and read back before it goes in, with manifest.json. html: one file
# with both platform pages, offline (assets/listing.html). pdf: that file's print view, printed as a deck's is.

LISTING_PLAYER = HERE.parent / "assets" / "listing.html"
LISTING_FORMATS = ("zip", "pdf", "html", "print")
LISTING_NEEDS = "a listing's ZIP or PDF needs Chrome or Chromium: set BLUEDOC_CHROME to its path"


class ListingError(ValueError):
    """Why a doc can't be exported as a listing."""


def listing_doc(doc: dict, doc_path: Path, rev: str | None) -> tuple[dict, str | None, dict]:
    """(the doc as of rev, rev or None for the doc on disk, its captures): an earlier revision's captures are the PNGs
    its history entry hashes (listing.captures_at). ListingError: not a storelisting, an unknown revision."""
    kind = build.doc_type(doc.get("meta") if isinstance(doc.get("meta"), dict) else {})
    if kind != "storelisting":
        raise ListingError(f"only a storelisting exports as a listing, not a doc of type {kind}")
    if rev is None or rev == str((doc.get("meta") or {}).get("rev") or ""):
        return doc, None, listing.captures(doc, doc_path)
    try:
        h = build.load_history(build.history_path(doc_path))
        entry = next((e for e in h["revs"] if isinstance(e, dict) and e.get("rev") == rev), None)
        old = build.restore(h, entry) if entry else None
    except (OSError, ValueError, KeyError, TypeError):
        old = None
    if old is None:
        raise ListingError(f"no revision {rev} in the doc's history")
    return old, rev, listing.captures_at(old, doc_path, entry.get("screens") or {})


def listing_pages(doc: dict, doc_path: Path, rev: str | None, roots: list[Path] | None) -> dict[str, str]:
    """{artboard id: its whole document, inline, behind build.STANDALONE_SCREEN_CSP} for each shot and asset with a
    screen file (an upload is a PNG). Wrapped as a deck's slides are: no inspector."""
    out = {}
    for a in listing.shots_of(doc):
        if a.get("device") not in ("shot", "asset") or listing.is_image_shot(a):
            continue
        text = build.screen_source(doc_path, a["id"], rev) if rev else current_screen_text(doc, doc_path, a["id"], roots)
        if text is not None:
            out[a["id"]] = build.with_screen_csp(wrap_screen(doc, doc_path, a["id"], text, deck=True))
    return out


def icon_play_css(icon: dict) -> str:
    """The Play icon's CSS background, as the page's Shared section draws it: play.svg whole, else the foreground and
    background layers at 150% (an adaptive icon's 108 dp, 72 dp shown), on the icon's colour (white without one)."""
    lay, u = icon["layers"], lambda k: f'url("{icon["layers"][k]}")'  # noqa: E731
    if lay.get("play"):
        return f"{u('play')} center / 100% 100% no-repeat"
    return f"{u('fg')} center / 150% 150% no-repeat" + (f", {u('bg')} center / 150% 150% no-repeat" if lay.get("bg") else "") \
        + f", {icon.get('bg') or '#ffffff'}"


def listing_warnings(doc: dict, fmt: str) -> list[str]:
    """What an export of this listing should say: a caption font a PDF can't embed (OT-FSTYPE), an HTML file that
    names its fonts instead of carrying them, the store-rule errors still open."""
    lb, rules = listing.listing_of(doc) or {}, listing.load_rules()
    out = []
    for f in listing.export_fonts(lb, rules):
        if fmt == "pdf" and f["embedding"] not in ("allowed", "unknown"):
            out.append(f"{f['family']}: {f['embedding']} (fsType {f['fsType']}, OT-FSTYPE): the PDF can't embed it")
        if fmt == "html" and f["source"] != "vendored":
            out.append(f"{f['family']} is named, not embedded: install it to see the captions as drawn")
    errs = [x for x in listing.store_checks(doc, None, rules) if x["level"] == "err"]
    if errs:
        out.append(f"{len(errs)} store-rule error(s): {errs[0]['where']}: {errs[0]['msg']}")
    return out


def listing_zip(doc: dict, doc_path: Path, out: Path, chrome: str, *, rev: str | None = None, platform: str | None = None,
                locale: str | None = None, roots: list[Path] | None = None) -> dict:
    """Write the fastlane ZIP of the listing (revision rev's) to out, one file at a time, and return its manifest
    (manifest.json in the ZIP: every file's path, kind, platform, locale, set or asset, shot, size, sha256 and bytes,
    the MT strings, the fonts, the store-rule errors). Each shot and asset is its screen file in headless Chrome at its
    set's frame (CSS px) × scale, its UI the capture the page shows; an upload is its PNG; the Play icon is the icons
    artboard's exported play/icon-512.png, else its layers drawn at 512 px. ListingError: a PNG that isn't its size,
    or isn't RGB without alpha after listing.png_rgb24. RuntimeError, OSError: Chrome failed."""
    doc, rev, caps = listing_doc(doc, doc_path, rev)
    rules, lb = listing.load_rules(), listing.listing_of(doc) or {}
    try:
        plan = listing.export_plan(doc, doc_path, rules, platform, locale, caps=caps)
    except ValueError as e:
        raise ListingError(str(e)) from None
    pages = listing_pages(doc, doc_path, rev, roots)
    sets = listing.by_id(rules, "sets")
    keys = {aid: listing.l10n_keys(t) for aid, t in pages.items()}   # each shot's caption strings, for its MT marks
    mt = lb.get("mt") if isinstance(lb.get("mt"), dict) else {}
    stamp = (dt.date.today().year, dt.date.today().month, dt.date.today().day, 0, 0, 0)
    files: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="bluedoc-listing-") as d, zipfile.ZipFile(out, "w") as z:
        ch: HeadlessChrome | None = None
        urls: dict[str, str] = {}

        def url_of(aid: str, html: str) -> str:
            if aid not in urls:
                f = Path(d) / f"{len(urls)}.html"
                f.write_text(html, encoding="utf-8")
                urls[aid] = f.as_uri()
            return urls[aid]
        try:
            for e in plan:
                meta = {k: v for k, v in e.items() if k not in ("text", "fw", "fh", "scale")}
                if e["kind"] == "text":
                    data = e["text"].encode("utf-8")
                    z.writestr(zipfile.ZipInfo(e["path"], stamp), data, compress_type=zipfile.ZIP_DEFLATED)
                    files.append({**meta, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
                    continue
                exported = None
                if e["kind"] == "icon":
                    icon = listing.icon_of(doc, doc_path)
                    if icon is None:
                        continue
                    ref, _, aid = icon["from"].rpartition("#")
                    src = (doc_path.parent / ref).resolve() if ref else doc_path
                    exported = icons_dir(src, aid or icon["from"]) / "play" / "icon-512.png"
                if e["kind"] == "upload":
                    png = listing.png_rgb24((doc_path.parent / e["src"]).read_bytes())
                elif exported is not None and exported.is_file():
                    png = exported.read_bytes()   # the page's icon export: Play takes it as it is, alpha and all
                else:
                    ch = ch or HeadlessChrome(chrome)
                    if e["kind"] == "icon":
                        page = ('<!doctype html><meta charset="utf-8"><style>html,body{margin:0;width:512px;height:512px;overflow:hidden}'
                                f'body{{background:{icon_play_css(icon)}}}</style>')
                        png = ch.capture_png(url_of("\0icon", page), 512, 512, 1)
                    elif e["shot"] not in pages:
                        raise ListingError(f"{e['shot']}: no screen file to render")
                    else:
                        state = {"locale": e["locale"]} if e["kind"] == "asset" else {
                            "set": e["set"], "locale": e["locale"], "i": e["i"], "n": e["n"],
                            "ui": data_uri(doc_path.parent / e["capture"]) if e.get("capture") else None,
                            **{k: e[k] for k in ("message", "layout") if k in e}}
                        png = ch.capture_png(url_of(e["shot"], pages[e["shot"]]), e["fw"], e["fh"], e["scale"],
                                             name="bd-shot " + json.dumps(state), settle=0.2)
                    png = listing.png_rgb24(png)
                info = listing.png_info(png) or {}
                rule = sets.get(e.get("set")) or listing.by_id(rules, "assets").get(e.get("asset")) or {}
                why = listing.size_problem(rule, info.get("w", 0), info.get("h", 0)) if e["kind"] in ("upload", "icon") \
                    else None if (info.get("w"), info.get("h")) == (e["w"], e["h"]) else f"want {e['w']}×{e['h']}"
                if why or (exported is None and (info.get("colour") != 2 or info.get("trns"))):
                    raise ListingError(f"{e['path']}: {info.get('w')}×{info.get('h')} colour type {info.get('colour')}: "
                                       f"{why or 'want RGB without alpha'}")
                z.writestr(zipfile.ZipInfo(e["path"], stamp), png, compress_type=zipfile.ZIP_STORED)
                files.append({**meta, "w": info["w"], "h": info["h"], "bytes": len(png), "sha256": hashlib.sha256(png).hexdigest(),
                              "mt": [f"strings.{k}" for k in keys.get(e.get("shot"), []) if f"strings.{k}" in (mt.get(e["locale"]) or [])]})
        finally:
            if ch:
                ch.close()
        manifest = {"doc": doc_path.name, "title": str(doc.get("title") or ""), "rev": str((doc.get("meta") or {}).get("rev") or ""),
                    "exported": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "bluedoc": VERSION,
                    "layout": "fastlane: metadata/android (supply), metadata and screenshots (deliver)", "rules": rules["accessed"],
                    "platforms": sorted({f["platform"] for f in files}), "locales": sorted({f["locale"] for f in files}),
                    "mt": {k: v for k, v in (lb.get("mt") or {}).items() if not locale or k == locale},
                    "fonts": listing.export_fonts(lb, rules),
                    "errors": [f"{x['where']}: {x['msg']}" for x in listing.store_checks(doc, doc_path, rules) if x["level"] == "err"],
                    "notes": ["The App Store icon ships in the binary: it isn't in the ZIP.",
                              "A field a locale lacks isn't in its folder: the store shows the default locale's.",
                              "variants/<platform>-<kind>-<id>/ holds only what a variant changes: the rest is the default page's."],
                    "files": files}
        z.writestr(zipfile.ZipInfo("manifest.json", stamp), json.dumps(manifest, ensure_ascii=False, indent=1),
                   compress_type=zipfile.ZIP_DEFLATED)
    return manifest


def listing_html(doc: dict, doc_path: Path, rev: str | None = None, roots: list[Path] | None = None) -> str:
    """The listing as one HTML file that works offline (assets/listing.html): both platform pages with their text
    per locale (counts, MT marks, fallbacks), captions, Shared and device sections, each shot and asset in a sandboxed
    srcdoc frame wrapped as the page shows it, captures and uploads inline, the fonts it needs named. Its print view
    (#print) is the PDF: per platform a text page, then a page per locale and section. ListingError as listing_doc."""
    doc, rev, caps = listing_doc(doc, doc_path, rev)
    rules, lb = listing.load_rules(), listing.listing_of(doc) or {}
    pages = listing_pages(doc, doc_path, rev, roots)
    ids = list(pages)
    assets, parts = shared_parts([pages[i] for i in ids])
    imgs: list[str] = []
    at: dict[str, int] = {}

    def img(rel: str) -> int | None:
        if rel not in at:
            uri = listing._data_uri(doc_path.parent / rel, "image/png")
            if uri is None:
                return None
            at[rel] = len(imgs)
            imgs.append(uri)
        return at[rel]
    locs = [x for x in lb.get("locales") or [] if isinstance(x, str)]
    default = lb.get("defaultLocale") if lb.get("defaultLocale") in locs else (locs[0] if locs else None)
    arts = listing.shots_of(doc)
    by = {a["id"]: a for a in arts}
    keys = {aid: listing.l10n_keys(t) for aid, t in pages.items()}
    mt = lb.get("mt") if isinstance(lb.get("mt"), dict) else {}
    sets, rows = listing.by_id(rules, "sets"), {r["id"]: r for r in rules["rows"]}
    icon = listing.icon_of(doc, doc_path)
    text, strings = lb.get("text") or {}, lb.get("strings") or {}
    findings = listing.checks_page_data(doc, doc_path)
    plats = []
    for p in [x for x in rules["platforms"] if x["id"] in (lb.get("platforms") or [])]:
        fields = []
        for f, r in listing.text_rules(rules, p["id"]).items():
            vals = {}
            for loc in locs:
                v = ((text.get(loc) or {}).get(p["id"]) or {}).get(f)
                fb = v is None and loc != default
                v = v if v is not None else ((text.get(default) or {}).get(p["id"]) or {}).get(f)
                if v is None:
                    continue
                items = v if isinstance(v, list) else [v]
                vals[loc] = {"v": "\n".join(map(str, items)), "n": [listing.text_count(str(s), r["unit"]) for s in items],
                             "mt": f"{p['id']}.{f}" in (mt.get(loc) or []), "fb": fb}
            if vals:
                fields.append({"field": f, "label": r["label"], "limit": r["limit"], "unit": r["unit"], "values": vals})
        secs = {}
        for loc in locs:
            out = []
            for s in listing.sections(lb, arts, rules, p["id"], loc):
                out.append({"row": s["row"], "label": rows[s["row"]]["label"], "sets": [{
                    "set": x["set"], "label": sets[x["set"]]["label"], "size": "×".join(map(str, sets[x["set"]]["author"])),
                    "fw": listing.frame_size(sets[x["set"]])[0], "fh": listing.frame_size(sets[x["set"]])[1],
                    "max": (sets[x["set"]].get("count") or [0, 10])[1],
                    "shots": [{"id": sid, "title": str(by[sid].get("title") or sid),
                               **({"img": img(by[sid]["src"])} if listing.is_image_shot(by[sid]) else
                                  (lambda c: {"cap": img(c["file"]), "fb": c["locale"] != loc} if c else {})(
                                      listing.capture_for(caps, by[sid], sets[x["set"]], loc, default)))}
                              for sid in x["shots"]]} for x in s["sets"]]})
            secs[loc] = out
        shown = {sid for loc in secs for s in secs[loc] for x in s["sets"] for sid in (y["id"] for y in x["shots"])}
        art = [{"id": a["id"], "title": str(a.get("title") or a["id"]), "fw": listing.frame_size(r)[0], "fh": listing.frame_size(r)[1],
                "label": r["label"]} for a in arts for r in [listing.by_id(rules, "assets").get(a.get("asset"))]
               if a.get("device") == "asset" and r and r["platform"] == p["id"] and "author" in r]
        caption_keys = list(dict.fromkeys(k for sid in [*shown, *(x["id"] for x in art)] for k in keys.get(sid, [])))
        plats.append({"id": p["id"], "label": p["label"], "fields": fields, "sections": secs, "assets": art,
                      "captions": [{"key": k, "values": {loc: {"v": (strings.get(loc) or {}).get(k, (strings.get(default) or {}).get(k)),
                                                               "mt": f"strings.{k}" in (mt.get(loc) or []),
                                                               "fb": k not in (strings.get(loc) or {}) and loc != default} for loc in locs}}
                                   for k in caption_keys],
                      "icon": (icon_play_css(icon) if p["id"] == "play" else
                               f"url(\"{icon['layers']['fg']}\") center / 100% 100% no-repeat" + (f", url(\"{icon['layers']['bg']}\") center / 100% 100% no-repeat" if icon["layers"].get("bg") else "")
                               + f", {icon.get('bg') or '#ffffff'}") if icon else None,
                      "checks": [{"level": x["level"], "where": x["where"], "msg": x["msg"]} for x in findings
                                 if not x["platforms"] or p["id"] in x["platforms"]]})
    data = {"title": str(doc.get("title") or build.doc_stem(doc_path)), "rev": str((doc.get("meta") or {}).get("rev") or ""),
            "date": str((doc.get("meta") or {}).get("date") or ""), "rules": rules["accessed"], "locales": locs, "default": default,
            "platforms": plats, "assets": assets, "docs": dict(zip(ids, parts)), "imgs": imgs,
            "fonts": listing.export_fonts(lb, rules)}
    fill = {"__LISTING_TITLE__": esc(data["title"]), "__LISTING_CSP__": build.STANDALONE_SCREEN_CSP,
            "__LISTING_DATA__": build._script_json(data)}
    return re.sub("|".join(fill), lambda m: fill[m[0]], LISTING_PLAYER.read_text(encoding="utf-8"))


def listing_pdf(html: str, chrome: str) -> bytes:
    """A listing file (listing_html) as a PDF, its print view (#print) printed as deck_pdf prints a deck.
    RuntimeError or OSError: Chrome failed."""
    with tempfile.TemporaryDirectory(prefix="bluedoc-listing-") as d:
        f = Path(d) / "listing.html"
        f.write_text(html, encoding="utf-8")
        with HeadlessChrome(chrome) as ch:
            return ch.print_pdf(f.as_uri() + "#print")



# ---------- website live pages: one proxy per dev server ----------

HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
               "transfer-encoding", "upgrade", "content-length", "host", "accept-encoding"}
LIVE_INSPECTOR = "/__bluedoc/inspector.js"   # on a proxy's origin: kits/inspector.js, which it injects into each page
# what the proxy injects after <head>: the inspector (told which origins may hear it, and the dev server's origin, which
# a snapshot's images left on the dev server load from) and a style hiding framework dev toolbars, which aren't the page
# the reader judges
LIVE_INJECT = ('<script src="' + LIVE_INSPECTOR + '" data-parents="{parents}" data-origin="{origin}"></script>'
               '<style id="bd-live">astro-dev-toolbar, nextjs-portal {{ display: none !important; }}</style>')
HEAD_TAGS = (re.compile(rb"<head\b[^>]*>", re.I), re.compile(rb"<html\b[^>]*>", re.I))   # inject after the first found

# Full page: a website page's frame grows to its document, so a length that follows the viewport's height would grow
# with it. A viewport unit in a declaration (never in an at-rule's prelude, where var() can't go: the lookahead) becomes
# a multiple of --bd-vh, which the inspector sets to the design viewport's height / 100 in Full page and leaves unset in
# Viewport, where the fallback is the unit itself (never rewritten again: the lookbehinds, so pinning is idempotent).
# kits/inspector.js applies the same rewrite to what the proxy never sees (a screen's compiled Tailwind, styles set by
# script); keep the two alike. A number right after '/' or '+' is never a unit: that is base64 (a data: URI's font or
# image, which a snapshot inlines), where "/5vh+" would otherwise match.
VIEWPORT_UNIT = re.compile(r"(?<!--bd-vh)(?<!--bd-vh,)(^|[^\w./+-])(-?)(\d*\.?\d+(?:e[+-]?\d+)?)[sld]?(vh|vb|vmin|vmax)\b(?![^{};]*\{)", re.I)
STYLE_ELEMENT = re.compile(r"(<style\b[^>]*>)(.*?)(</style\s*>)", re.I | re.S)
STYLE_ATTR = re.compile(r"""(\sstyle\s*=\s*)("[^"]*"|'[^']*')""", re.I)
# a dev server's CSS served as a JS module (Vite: /src/x.css, an Astro component's ?astro&type=style&lang.css)
CSS_MODULE = re.compile(r"\.(css|scss|sass|less|styl|pcss|postcss)$|[?&]type=style\b|[?&]lang\.(css|scss|sass|less|styl)\b", re.I)


def pin_viewport_units(css: str) -> str:
    """css with each viewport-height unit as a multiple of --bd-vh: 100vh -> calc(100 * var(--bd-vh, 1vh)); vmin and
    vmax compare that with 1vw."""
    def sub(m: re.Match) -> str:
        unit = m[4].lower()
        v = "var(--bd-vh, 1vh)" if unit in ("vh", "vb") else f"{unit[1:]}(1vw, var(--bd-vh, 1vh))"
        return f"{m[1]}calc({m[2]}{m[3]} * {v})"
    return VIEWPORT_UNIT.sub(sub, css)


def pin_html_units(html: str) -> str:
    """html with pin_viewport_units applied to its <style> elements and style attributes."""
    html = STYLE_ELEMENT.sub(lambda m: m[1] + pin_viewport_units(m[2]) + m[3], html)
    return STYLE_ATTR.sub(lambda m: m[1] + m[2][0] + pin_viewport_units(m[2][1:-1]) + m[2][-1], html)


def live_origin(url: str) -> tuple[str, str, int] | None:
    """(scheme, host, port) of a live page's dev server, or None when build.live_url_problem refuses the URL."""
    if build.live_url_problem(url):
        return None
    u = urlsplit(url)
    return u.scheme, u.hostname.lower(), u.port or (443 if u.scheme == "https" else 80)


def origin_key(scheme: str, host: str, port: int) -> str:
    """The dev server's origin as the page writes it (template.html liveOrigin): scheme://host:port, IPv6 bracketed."""
    return f"{scheme}://{f'[{host}]' if ':' in host else host}:{port}"


class LiveProxies:
    """The proxies of this server's live pages, one per dev-server origin, started on first use and kept until the
    server stops. page_port is this server's port (its pages' origins may frame them and hear their inspector)."""
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.page_port: int | None = None
        self.ports: dict[str, int] = {}

    def port(self, scheme: str, host: str, port: int) -> int | None:
        if self.page_port is None:
            return None
        key = origin_key(scheme, host, port)
        with self.lock:
            if key not in self.ports:
                srv = ThreadingHTTPServer(("127.0.0.1", 0), make_live_handler(scheme, host, port, self.page_port))
                srv.daemon_threads = True
                threading.Thread(target=srv.serve_forever, name=f"live {key}", daemon=True).start()
                self.ports[key] = srv.server_address[1]
            return self.ports[key]

    def for_doc(self, doc: dict) -> dict[str, int] | None:
        """{dev server origin: its proxy's port} for a website doc's live pages; None for any other doc."""
        if not isinstance(doc, dict) or build.doc_type(doc.get("meta") or {}) != "website":
            return None
        out = {}
        for a in build._artboards(doc):
            o = live_origin(a["url"]) if build.is_live(a) else None
            if o and (port := self.port(*o)):
                out[origin_key(*o)] = port
        return out or None


LIVE = LiveProxies()


def strip_key_cookie(header: str) -> str:
    """A Cookie header without bluedoc's key cookies: cookies ignore ports, so the proxy's origin gets them too."""
    return "; ".join(c for c in (p.strip() for p in header.split(";")) if c and not c.startswith("bluedoc_key_"))


def make_live_handler(scheme: str, host: str, port: int, page_port: int):
    """The handler of one dev server's proxy (see Live pages in this module's docstring)."""
    target = origin_key(scheme, host, port)
    parents = f"http://127.0.0.1:{page_port} http://localhost:{page_port}"
    inject = LIVE_INJECT.format(parents=parents, origin=esc(target)).encode()
    ancestors = f"frame-ancestors {parents}"

    class P(BaseHTTPRequestHandler):
        server_version = "bluedoc-live"

        def log_message(self, *_):
            pass

        def own(self) -> str:
            return f"http://{self.headers.get('Host')}"

        def handle_any(self) -> None:
            me = self.server.server_address[1]
            if self.headers.get("Host") not in (f"127.0.0.1:{me}", f"localhost:{me}"):   # DNS rebinding
                return self.answer(403, b"bad host", "text/plain; charset=utf-8")
            if not self.path.startswith("/"):
                return self.answer(400, b"bad request", "text/plain; charset=utf-8")
            if urlsplit(self.path).path == LIVE_INSPECTOR:
                return self.answer(200, (KITS / "inspector.js").read_bytes(), "text/javascript; charset=utf-8")
            if "websocket" in (self.headers.get("Upgrade") or "").lower():
                return self.tunnel()
            self.forward()

        do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = handle_any

        def answer(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", ancestors)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def upstream_headers(self) -> dict[str, str]:
            out = {}
            for k, v in self.headers.items():
                lk = k.lower()
                if lk in HOP_HEADERS:
                    continue
                if lk == "cookie":
                    v = strip_key_cookie(v)
                    if not v:
                        continue
                elif lk in ("origin", "referer") and v.startswith(self.own()):
                    v = target + v[len(self.own()):]
                out[k] = v
            out["Host"] = target.split("://", 1)[1]
            out["Accept-Encoding"] = "identity"   # the proxy reads HTML to inject the inspector
            return out

        def connect(self):
            if scheme == "https":   # a local dev server's certificate is usually its own
                return http.client.HTTPSConnection(host, port, timeout=60, context=ssl._create_unverified_context())
            return http.client.HTTPConnection(host, port, timeout=60)

        def forward(self) -> None:
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if 0 < n <= MAX_BODY * 16 else None
            conn = self.connect()
            try:
                conn.request(self.command, self.path, body=body, headers=self.upstream_headers())
                resp = conn.getresponse()
            except OSError as e:
                conn.close()
                msg = (f"<!doctype html><meta charset=utf-8><title>Dev server not answering</title><body style='font: 15px/1.5 "
                       f"system-ui, sans-serif; margin: 48px; color: #334'><h1 style='font-size: 20px'>The dev server at "
                       f"{esc(target)} isn't answering</h1><p>Start it (for example <code>npm run dev</code>), then "
                       f"reload this page.</p><p style='color: #889'>{esc(type(e).__name__)}: {esc(str(e))}</p>")
                return self.answer(502, msg.encode(), "text/html; charset=utf-8")
            try:
                self.relay(resp)
            finally:
                conn.close()

        def relay(self, resp) -> None:
            # what the proxy rewrites (its body read whole): an HTML page (the inspector injected, viewport units pinned),
            # CSS and CSS served as a module (units pinned); never a body still encoded
            ctype, u = (resp.getheader("Content-Type") or "").lower(), urlsplit(self.path)
            kind = ("html" if ctype.startswith("text/html") else "css" if ctype.startswith("text/css") or (
                "javascript" in ctype and (CSS_MODULE.search(u.path) or CSS_MODULE.search("?" + u.query))) else None)
            if (resp.getheader("Content-Encoding") or "identity").strip().lower() != "identity":
                kind = None
            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                lk = k.lower()
                if lk in HOP_HEADERS or lk == "x-frame-options":
                    continue
                if lk == "content-security-policy":   # its framing rule is ours; the rest stays the site's
                    v = ";".join(d for d in v.split(";") if not d.strip().lower().startswith("frame-ancestors"))
                    if not v.strip(" ;"):
                        continue
                if lk == "location" and v.startswith(target):
                    v = self.own() + v[len(target):]
                self.send_header(k, v)
            self.send_header("Content-Security-Policy", ancestors)
            no_body = self.command == "HEAD" or resp.status in (204, 304) or 100 <= resp.status < 200
            if kind and not no_body:
                text = resp.read().decode("utf-8", "surrogateescape")   # any other bytes pass through as they came
                text = pin_html_units(text) if kind == "html" else pin_viewport_units(text)
                data = text.encode("utf-8", "surrogateescape")
                if kind == "html":
                    m = next((m for m in (t.search(data) for t in HEAD_TAGS) if m), None)
                    data = data[:m.end()] + inject + data[m.end():] if m else inject + data
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_header("Connection", "close")   # streamed to the end: the length is the upstream's to know
            self.end_headers()
            self.close_connection = True
            if no_body:
                return
            try:
                while chunk := resp.read1(65536):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except OSError:
                pass

        def tunnel(self) -> None:
            """A WebSocket (the dev server's hot reload): the upgrade request rewritten like any other, then the
            bytes both ways until either side closes."""
            try:
                up = socket.create_connection((host, port), timeout=10)
                if scheme == "https":
                    up = ssl._create_unverified_context().wrap_socket(up, server_hostname=host)
            except OSError:
                return self.answer(502, b"dev server not answering", "text/plain; charset=utf-8")
            heads = {k: v for k, v in self.upstream_headers().items() if k.lower() != "accept-encoding"}
            heads.update(Connection="Upgrade", Upgrade=self.headers.get("Upgrade") or "websocket")
            up.sendall((f"{self.command} {self.path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in heads.items())
                        + "\r\n").encode("latin-1", "replace"))
            up.settimeout(None)
            self.connection.settimeout(None)
            self.close_connection = True

            def pump(src, dst) -> None:
                try:
                    while data := src.recv(65536):
                        dst.sendall(data)
                except OSError:
                    pass
                for s in (src, dst):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
            back = threading.Thread(target=pump, args=(up, self.connection), daemon=True)
            back.start()
            pump(self.connection, up)
            back.join(5)
            up.close()

    return P


# ---------- website snapshots: a live page as an earlier revision showed it ----------

SNAPSHOT_MAX = 8 * 1024 * 1024   # a snapshot's HTML with its inlined images and fonts (the inspector inlines up to 4.5 MB)
SNAPSHOT_BODY = SNAPSHOT_MAX * 5 // 4 + 65536   # the POST's JSON: that HTML escaped, and the rest
# what a stored snapshot never holds, whoever posted it (the inspector drops them already), and our own meta tag
SNAP_STRIP = re.compile(r'(?is)<script\b.*?</script\s*>|<script\b[^>]*>|<base\b[^>]*>|<meta\b[^>]*\bhttp-equiv\b[^>]*>'
                        r'|<meta name="bluedoc-snapshot"[^>]*>')
HEAD_TAG, HTML_TAG = re.compile(r"(?i)<head\b[^>]*>"), re.compile(r"(?i)<html\b[^>]*>")


def after_head(html: str, tag: str) -> str:
    """html with tag right after its <head> (else <html>, else first)."""
    m = HEAD_TAG.search(html) or HTML_TAG.search(html)
    return html[:m.end()] + tag + html[m.end():] if m else tag + html


# a page's design viewport height at a width: board.viewport {"<width>": height}, else template.html's BP_H, else a
# ratio by device class (template.html pageDims: keep the two alike)
BP_H = {1920: 1080, 1440: 900, 1280: 800, 1024: 768, 768: 1024, 390: 844, 375: 812, 360: 780}
DEVICE_PAGE_W = 1440   # a page's default width (template.html DEVICES.page)


def design_viewport(w: int, vp) -> int:
    v = vp.get(str(w)) if isinstance(vp, dict) else None
    if isinstance(v, int) and not isinstance(v, bool) and 240 <= v <= 3840:
        return v
    return BP_H.get(w) or (round(w * 0.625) if w >= 1024 else round(w * 4 / 3) if w >= 600 else round(w * 2.164))


def doc_at(doc_path: Path, doc: dict, rev: str) -> dict | None:
    """The doc as of revision rev: doc itself when rev is its meta.rev, else the history's entry; None when unknown."""
    if rev == str((doc.get("meta") or {}).get("rev") or ""):
        return doc
    try:
        h = build.load_history(build.history_path(doc_path))
        entry = next((e for e in h["revs"] if isinstance(e, dict) and e.get("rev") == rev), None)
        return build.restore(h, entry) if entry else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def live_page(doc: dict | None, page) -> dict | None:
    """The website doc's live page (an artboard with `url`) by id, or None."""
    if not isinstance(doc, dict) or build.doc_type(doc.get("meta") or {}) != "website":
        return None
    return next((a for a in build._artboards(doc) if a["id"] == page and build.is_live(a)), None)


def snapshot_html(html: str, external: int) -> str:
    """A snapshot as it is stored: SNAP_STRIP dropped, then its meta tag (the images left on the dev server, when it was
    taken) first in <head>, which build.snapshot_index reads."""
    html = SNAP_STRIP.sub("", html)
    at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = f'<meta name="bluedoc-snapshot" content="external={external}; at={at}">'
    return after_head(html, meta)


def save_snapshot(doc_path: Path, rev, page, width, html, external, *, current_only: bool = True) -> tuple[int, dict]:
    """(status, answer) of storing a live page's snapshot at build.snapshot_path (POST /__bluedoc/snapshot; `snapshot`).
    rev is the doc's current meta.rev, whose snapshot it replaces; with current_only False (the CLI), also an earlier
    revision of the history that has none at that width: an earlier revision's snapshot is never replaced. page must
    be a live page of that revision, width 240..3840 px, html at most SNAPSHOT_MAX bytes (snapshot_html cleans it).
    Written atomically; no link on the way."""
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return 500, {"error": f"cannot read the doc: {e}"}
    if not isinstance(doc, dict) or build.doc_type(doc.get("meta") or {}) != "website":
        return 404, {"error": "not a website doc"}
    cur = str((doc.get("meta") or {}).get("rev") or "")
    if not isinstance(rev, str) or not rev:
        return 400, {"error": "rev: want the revision the page shows"}
    if rev != cur and current_only:
        return 409, {"error": f"rev {rev} is not the doc's current revision ({cur or 'none'}): an earlier revision keeps "
                              "its snapshot", "reload": True}
    if not live_page(doc_at(doc_path, doc, rev), page):
        return 404, {"error": f"no live page {page!r} in rev {rev}"}
    path = build.snapshot_path(doc_path, rev, page, width)
    if path is None:
        return 400, {"error": "width: want whole px, 240 to 3840"}
    if rev != cur and path.exists():
        return 409, {"error": f"rev {rev} has a snapshot of {page} at {width} px: an earlier revision's is never replaced"}
    if not isinstance(html, str) or not html.strip():
        return 400, {"error": "html: want the page's HTML"}
    if len(html.encode("utf-8")) > SNAPSHOT_MAX:
        return 413, {"error": f"the snapshot is over {SNAPSHOT_MAX // (1024 * 1024)} MB"}
    if not (isinstance(external, int) and not isinstance(external, bool) and 0 <= external <= 100000):
        return 400, {"error": "external: want the count of images left on the dev server"}
    data = snapshot_html(html, external).encode("utf-8")
    base = build.snapshots_dir(doc_path)
    want = doc_path.parent.resolve() / base.name / path.parent.name
    for p in (base, path.parent, path):
        if p.is_symlink():
            return 409, {"error": f"{p.name} is a link"}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.resolve() != want:
            return 409, {"error": f"a link on the way to {base.name}/{path.parent.name}"}
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".bd-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        finally:
            Path(tmp).unlink(missing_ok=True)
    except OSError as e:
        return 500, {"error": f"cannot write the snapshot: {e}"}
    return 200, {"ok": True, "file": f"{base.name}/{path.parent.name}/{path.name}", "bytes": len(data)}


def screen_doc(m: re.Match) -> tuple[Path, dict] | None:
    """(doc file, its JSON) a SCREEN_URL match names, under a registered folder; None otherwise."""
    doc_path = next((d for d in (doc_for_url(m[1] + m[2] + s) for s in build.DOC_SUFFIXES) if d), None)
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8")) if doc_path else None
    except (OSError, ValueError):
        return None
    return (doc_path, doc) if isinstance(doc, dict) else None


def snapshot_for_url(path: str, rev: str | None, width: str | None) -> tuple[str, str | None] | None:
    """(the snapshot's HTML, its dev server's origin) for a live page's screen URL at revision rev: the snapshot at
    width (px), else the nearest width it has (the wider on a tie); None without one."""
    m = SCREEN_URL.match(path)
    found = screen_doc(m) if m and rev else None
    if not found:
        return None
    doc_path, doc = found
    a = live_page(doc_at(doc_path, doc, rev), m[3])
    have = build.snapshot_index(doc_path).get(rev, {}).get(m[3]) if a else None
    if not have:
        return None
    want = int(width) if (width or "").isdigit() else DEVICE_PAGE_W
    w = min((int(k) for k in have), key=lambda k: (abs(k - want), -k))
    f = build.snapshot_path(doc_path, rev, a["id"], w)
    try:
        html = f.read_text(encoding="utf-8") if f and not f.is_symlink() else None
    except (OSError, UnicodeDecodeError):
        html = None
    o = live_origin(a["url"])
    return (html, origin_key(*o) if o else None) if html is not None else None


def snapshot_page(html: str) -> str:
    """A stored snapshot as its frame loads it: viewport heights pinned (as the proxy does), the inspector after
    <head>, naming elements from ids as on the live page."""
    tag = f'<script src="/__bluedoc/kit/inspector.js?v={kit_version()}" data-ids="1"></script>'
    return after_head(pin_html_units(html), tag)


def find_chrome() -> str | None:
    """Chrome or Chromium for `snapshot` and deck PDFs: BLUEDOC_CHROME (None when it names nothing there), else the
    usual places."""
    if os.environ.get("BLUEDOC_CHROME"):
        p = os.environ["BLUEDOC_CHROME"]
        return p if os.path.isfile(p) else shutil.which(p)
    for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
              "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = p if os.path.isfile(p) else shutil.which(p)
        if found:
            return found
    return None


class HeadlessChrome:
    """Headless Chrome with a throwaway profile, driven over its DevTools WebSocket (a flat session per page)."""

    def __init__(self, path: str) -> None:
        self.profile = Path(tempfile.mkdtemp(prefix="bluedoc-chrome-"))
        self.sock: socket.socket | None = None
        self.buf, self.seq = bytearray(), 0
        self.proc = subprocess.Popen([path, "--headless=new", f"--user-data-dir={self.profile}", "--remote-debugging-port=0",
                                      "--no-first-run", "--no-default-browser-check", "about:blank"],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            active, deadline = self.profile / "DevToolsActivePort", time.monotonic() + 30
            while not (active.is_file() and len(active.read_text().split()) >= 2):
                if self.proc.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Chrome did not start")
                time.sleep(0.05)
            port, ws = active.read_text().split()[:2]
            self.sock = socket.create_connection(("127.0.0.1", int(port)), timeout=120)
            key = base64.b64encode(os.urandom(16)).decode()
            self.sock.sendall(f"GET {ws} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                              f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
            while b"\r\n\r\n" not in self.buf:
                self._fill()
            end = self.buf.index(b"\r\n\r\n")
            head = bytes(self.buf[:end])
            del self.buf[:end + 4]
            if b" 101 " not in head.split(b"\r\n")[0]:
                raise RuntimeError("DevTools refused the WebSocket")
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> "HeadlessChrome":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        shutil.rmtree(self.profile, ignore_errors=True)

    def _fill(self) -> None:
        chunk = self.sock.recv(1 << 20)
        if not chunk:
            raise ConnectionError("DevTools closed the connection")
        self.buf += chunk

    def _take(self, n: int) -> bytes:
        while len(self.buf) < n:
            self._fill()
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def _send(self, data: bytes, opcode: int = 1) -> None:
        n, mask = len(data), os.urandom(4)   # a client masks every frame
        size = bytes([0x80 | n]) if n < 126 else bytes([0xFE]) + n.to_bytes(2, "big") if n < 65536 else bytes([0xFF]) + n.to_bytes(8, "big")
        masked = (int.from_bytes(data, "big") ^ int.from_bytes((mask * (n // 4 + 1))[:n], "big")).to_bytes(n, "big")
        self.sock.sendall(bytes([0x80 | opcode]) + size + mask + masked)

    def _message(self) -> dict:
        parts = []
        while True:
            b0, b1 = self._take(2)
            op, n = b0 & 0x0F, b1 & 0x7F
            if n >= 126:
                n = int.from_bytes(self._take(2 if n == 126 else 8), "big")
            data = self._take(n)
            if op == 8:
                raise ConnectionError("DevTools closed the WebSocket")
            if op == 9:
                self._send(data, 10)
            elif op in (0, 1, 2):
                parts.append(data)
                if b0 & 0x80:
                    return json.loads(b"".join(parts))

    def call(self, method: str, params: dict | None = None, session: str | None = None) -> dict:
        self.seq += 1
        self._send(json.dumps({"id": self.seq, "method": method, "params": params or {},
                               **({"sessionId": session} if session else {})}).encode())
        while True:
            m = self._message()
            if m.get("id") == self.seq:
                if "error" in m:
                    raise RuntimeError(f"{method}: {(m['error'] or {}).get('message')}")
                return m.get("result", {})

    def eval(self, session: str, expr: str):
        r = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True}, session)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise RuntimeError((d.get("exception") or {}).get("description") or d.get("text") or "script error")
        return r["result"].get("value")

    def capture(self, url: str, width: int, vh: int) -> tuple[str, int]:
        """(HTML, images left on the dev server) of the live page at url (its proxy, which brings the inspector) as the
        board's Full page shows it: width wide, viewport heights pinned to vh, the window grown to the page's height so
        whatever loads or reveals on scroll has."""
        target = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        s = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        metrics = lambda h: {"width": width, "height": h, "deviceScaleFactor": 1, "mobile": False}  # noqa: E731
        try:
            self.call("Runtime.enable", None, s)
            self.call("Page.enable", None, s)
            self.call("Emulation.setDeviceMetricsOverride", metrics(vh), s)
            self.call("Page.addScriptToEvaluateOnNewDocument", {"source": f"window.name = 'bd-page full {vh}';"}, s)
            self.call("Page.navigate", {"url": url}, s)
            deadline, loaded = time.monotonic() + 60, None
            while not self.eval(s, "typeof window.__bluedocSnapshot === 'function' && document.readyState === 'complete'"):
                if loaded is None and self.eval(s, "document.readyState === 'complete' && location.href !== 'about:blank'"):
                    loaded = time.monotonic()
                if time.monotonic() > deadline or (loaded and time.monotonic() - loaded > 5):
                    raise RuntimeError(f"{url} has no inspector: is the dev server up?")
                time.sleep(0.2)
            self.eval(s, "document.fonts ? document.fonts.ready.then(() => true) : true")
            for _ in range(3):   # lazy images and scroll reveals load as the window grows, which may grow the page
                h = self.eval(s, "Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)")
                self.call("Emulation.setDeviceMetricsOverride", metrics(max(vh, min(int(h or 0), 30000))), s)
                time.sleep(1)
            got = self.eval(s, "window.__bluedocSnapshot()")
        finally:
            self.call("Target.closeTarget", {"targetId": target})
        if not isinstance(got, dict) or not isinstance(got.get("html"), str):
            raise RuntimeError("the inspector returned no snapshot")
        return got["html"], int(got.get("external") or 0)

    def print_pdf(self, url: str) -> bytes:
        """The page at url (a deck file at #print) as a PDF once it says it is ready (html[data-print-ready]), at its
        CSS page size (@page), backgrounds printed, no margins. The page's own print() does nothing here, so the
        view it set up for printing stays up."""
        target = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        s = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        try:
            self.call("Runtime.enable", None, s)
            self.call("Page.enable", None, s)
            self.call("Emulation.setDeviceMetricsOverride", {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False}, s)
            self.call("Page.addScriptToEvaluateOnNewDocument", {"source": "window.print = () => {};"}, s)
            self.call("Page.navigate", {"url": url}, s)
            deadline = time.monotonic() + 60
            while not self.eval(s, "document.documentElement.dataset.printReady === '1'"):
                if time.monotonic() > deadline:
                    raise RuntimeError("the slides did not load")
                time.sleep(0.1)
            got = self.call("Page.printToPDF", {"printBackground": True, "preferCSSPageSize": True, "marginTop": 0,
                                                "marginBottom": 0, "marginLeft": 0, "marginRight": 0}, s)
        finally:
            self.call("Target.closeTarget", {"targetId": target})
        return base64.b64decode(got["data"])

    def capture_png(self, url: str, width: int, height: int, scale: int = 1, *, dark: bool = False,
                    locale: str | None = None, settle: float = 0, name: str | None = None) -> bytes:
        """A PNG of the page at url in a width × height CSS px viewport at scale device pixels per px (an opaque RGB
        image of width·scale × height·scale, on white where the page draws nothing): prefers-color-scheme dark or
        light, the locale (navigator.language, Intl and Accept-Language) when given, window.name set to name before the
        page's scripts run (a storelisting shot reads 'bd-shot <JSON>'), after the load, the fonts and settle seconds.
        capture.py's web target and the listing export."""
        target = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        s = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        try:
            self.call("Runtime.enable", None, s)
            self.call("Page.enable", None, s)
            self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": scale, "mobile": False}, s)
            self.call("Emulation.setDefaultBackgroundColorOverride", {"color": {"r": 255, "g": 255, "b": 255, "a": 1}}, s)
            self.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "dark" if dark else "light"}]}, s)
            if locale:
                self.call("Emulation.setLocaleOverride", {"locale": locale}, s)
                ua = self.call("Browser.getVersion").get("userAgent", "")
                self.call("Emulation.setUserAgentOverride", {"userAgent": ua, "acceptLanguage": locale}, s)
            if name is not None:
                self.call("Page.addScriptToEvaluateOnNewDocument", {"source": f"window.name = {json.dumps(name)};"}, s)
            self.call("Page.navigate", {"url": url}, s)
            deadline = time.monotonic() + 60
            while not self.eval(s, "document.readyState === 'complete' && location.href !== 'about:blank'"):
                if time.monotonic() > deadline:
                    raise RuntimeError(f"{url} did not load in 60 s")
                time.sleep(0.1)
            self.eval(s, "document.fonts ? document.fonts.ready.then(() => true) : true")
            self.eval(s, "Promise.all([...document.images].map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; }))).then(() => true)")
            time.sleep(max(0.0, settle))
            got = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}, s)
        finally:
            self.call("Target.closeTarget", {"targetId": target})
        return base64.b64decode(got["data"])


def cmd_snapshot(doc_arg: Path, rev: str | None, url: str | None, only: list[str], widths: list[int]) -> int:
    """`serve.py snapshot`: each live page of the doc's revision rev (default: current) at each width (default: the
    board's breakpoints), read through a proxy of this process by headless Chrome, saved as that revision's snapshot
    (save_snapshot with current_only False). url names another dev server to read the pages from."""
    doc_path = doc_arg.resolve()
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"cannot read {doc_arg}: {e}", file=sys.stderr)
        return 2
    if not isinstance(doc, dict) or build.doc_type(doc.get("meta") or {}) != "website":
        print(f"{doc_arg}: not a website doc", file=sys.stderr)
        return 2
    cur = str((doc.get("meta") or {}).get("rev") or "")
    rev = rev or cur
    src = doc_at(doc_path, doc, rev) if rev else None
    if src is None:
        print(f"{doc_arg}: no rev {rev or '(meta.rev is unset)'} in the doc or its history", file=sys.stderr)
        return 2
    pages = [a for a in build._artboards(src) if build.is_live(a) and (not only or a["id"] in only)]
    if not pages:
        print(f"rev {rev} has no live page{' ' + ', '.join(only) if only else ''}", file=sys.stderr)
        return 2
    board = build.board_of(src) or {}
    widths = widths or [w for w in board.get("breakpoints") or [] if isinstance(w, int) and 240 <= w <= 3840] or [1440, 768, 390]
    over = None
    if url:
        why = build.live_url_problem(url)
        if why:
            print(f"--url: {why}", file=sys.stderr)
            return 2
        over = live_origin(url)
    chrome = find_chrome()
    if not chrome:
        print("snapshot needs Chrome or Chromium: set BLUEDOC_CHROME to its path", file=sys.stderr)
        return 1
    with socket.socket() as sk:   # the proxies' parent origin: nothing listens there, nothing hears the inspector
        sk.bind(("127.0.0.1", 0))
        LIVE.page_port = sk.getsockname()[1]
    failed = 0
    with HeadlessChrome(chrome) as ch:
        for a in pages:
            o = over or live_origin(a["url"])
            u = urlsplit(a["url"])
            page_url = f"http://127.0.0.1:{LIVE.port(*o)}{u.path or '/'}{'?' + u.query if u.query else ''}"
            for w in widths:
                f = build.snapshot_path(doc_path, rev, a["id"], w)
                if f is None or (rev != cur and f.exists()):
                    print(f"{a['id']} @ {w} px: skipped ({'rev ' + rev + ' has one already' if f else 'not a width'})")
                    continue
                try:
                    html, ext = ch.capture(page_url, w, design_viewport(w, board.get("viewport")))
                except (RuntimeError, OSError, ValueError) as e:
                    print(f"{a['id']} @ {w} px: {e}", file=sys.stderr)
                    failed += 1
                    continue
                if over:   # what it left on the dev server loads from the page's own one, once that temporary one is gone
                    html = html.replace(origin_key(*over) + "/", origin_key(*live_origin(a["url"])) + "/")
                code, ans = save_snapshot(doc_path, rev, a["id"], w, html, ext, current_only=False)
                if code != 200:
                    print(f"{a['id']} @ {w} px: {ans.get('error')}", file=sys.stderr)
                    failed += 1
                    continue
                print(f"{a['id']} @ {w} px: {ans['file']} ({ans['bytes'] // 1024} KB"
                      + (f"; {ext} image{'s' if ext > 1 else ''} too large to keep, loaded from the dev server" if ext else "") + ")")
    return 1 if failed else 0


# ---------- app icons ----------

# what POST /__bluedoc/icons may write under <stem>.icons/<artboard>/: {path: a PNG's width and height in px, None for
# a text file}. iOS: one 1024 icon per appearance; Android: 48 dp launcher icons and 108 dp adaptive layers per density
# (mdpi 1x .. xxxhdpi 4x); Play: 512. The page builds them (template.html iconFiles).
ICON_IOS = "ios/AppIcon.appiconset/"
ICON_ANYDPI = "android/res/mipmap-anydpi-v26/"
ICON_DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}
ICON_FILES: dict[str, int | None] = {
    ICON_IOS + "Contents.json": None, ICON_IOS + "AppIcon.png": 1024, ICON_IOS + "AppIcon-dark.png": 1024,
    ICON_IOS + "AppIcon-tinted.png": 1024, ICON_ANYDPI + "ic_launcher.xml": None, ICON_ANYDPI + "ic_launcher_round.xml": None,
    **{f"android/res/mipmap-{d}/{name}.png": int(dp * s) for d, s in ICON_DENSITIES.items()
       for name, dp in (("ic_launcher", 48), ("ic_launcher_round", 48), ("ic_launcher_foreground", 108),
                        ("ic_launcher_background", 108), ("ic_launcher_monochrome", 108))},
    "play/icon-512.png": 512}
ICON_MAX_PNG, ICON_MAX_TEXT, ICON_MAX_BODY = 4 * 1024 * 1024, 64 * 1024, 48 * 1024 * 1024
PNG_SIG = b"\x89PNG\r\n\x1a\n"

ICON_BG = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


def icon_artboard(doc: dict, aid: str) -> dict | None:
    """The doc's `icons` artboard aid, or None."""
    board = build.board_of(doc) or {}
    return next((a for a in board.get("artboards") or [] if isinstance(a, dict) and a.get("id") == aid
                 and a.get("device") == "icons"), None)


def icon_layer_texts(doc: dict, doc_path: Path, aid: str, rev: str | None = None,
                     roots: list[Path] | None = None) -> dict[str, str] | None:
    """{layer file name: its SVG text} of an icons artboard: the files now, or what the history recorded for rev.
    None without a readable fg.svg. roots (the server's folders): a layer file must resolve inside one of them, in
    its own <stem>.design/<id>/ folder."""
    doc_path = Path(doc_path)
    out: dict[str, str] = {}
    if rev:
        try:
            h = build.load_history(build.history_path(doc_path))
        except (OSError, ValueError):
            return None
        entry = next((e for e in h["revs"] if isinstance(e, dict) and e.get("rev") == rev), None) or {}
        pool, keys = h.get("html") or {}, entry.get("screens") or {}
        for name in build.ICON_LAYERS:
            text = pool.get(keys.get(f"{aid}/{name}") or "")
            if isinstance(text, str):
                out[name] = text
    else:
        for name, f in build.icon_layers(doc, doc_path).get(aid, {}).items():
            r = f.resolve()
            if roots is not None and not (under_roots(r, roots) and r.parent.name == aid and r.parent.parent.name.endswith(".design")):
                continue
            try:
                if r.stat().st_size <= build.MAX_MEDIA_BYTES:
                    out[name] = r.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass
    return out if "fg.svg" in out else None


def icon_fragment(doc: dict, doc_path: Path, aid: str, rev: str | None = None, roots: list[Path] | None = None) -> str | None:
    """An icons artboard's screen fragment: kits/icon-sheet.html filled with its layers as data: URIs (they draw on
    a canvas without tainting it, from the server and in an -o file alike), which layers exist, and the checks that
    follow from that; the sheet's script adds the safe-circle pixel check. None: no such artboard, or no fg.svg."""
    a = icon_artboard(doc, aid)
    texts = icon_layer_texts(doc, doc_path, aid, rev, roots) if a else None
    if not texts:
        return None
    icon = a.get("icon") if isinstance(a.get("icon"), dict) else {}
    bg = icon["bg"] if isinstance(icon.get("bg"), str) and ICON_BG.match(icon["bg"]) else None
    uri = {n[:-4]: "data:image/svg+xml;base64," + base64.b64encode(t.encode("utf-8")).decode() for n, t in texts.items()}
    has = uri.keys()
    url = lambda n: f'url("{uri[n]}")'  # noqa: E731
    vars_ = {"--fg": url("fg"), "--bgl": url("bg") if "bg" in has else "none", "--bgc": bg or "transparent",
             "--dark": url("ios-dark") if "ios-dark" in has else "var(--fg)", "--mono": url("mono") if "mono" in has else "var(--fg)",
             "--tint": url("ios-tinted") if "ios-tinted" in has else "var(--fg)", "--play": url("play") if "play" in has else "none"}
    cls = [c for c, on in (("no-mono", "mono" not in has), ("tint-art", "ios-tinted" in has or "mono" not in has),
                           ("has-play", "play" in has)) if on]
    name = str(icon.get("name") or "")[:30]
    code = lambda s: f"<code>{esc(s)}</code>"  # noqa: E731
    files = [code(f"{aid}/{n}") for n in texts]
    built = ", ".join(files[:-1]) + (" and " if len(files) > 1 else "") + files[-1] + (f" and bg {code(bg)}" if bg else "")
    li = lambda ok, text: f'<li class="{"ok" if ok else "warn"}">{text}</li>'  # noqa: E731
    ios = [li(bool(bg or "bg" in has), "opaque light icon" if bg or "bg" in has
              else "no background (<code>icon.bg</code> or bg.svg): the light icon has alpha, which App Store Connect rejects"),
           li(True, f"dark (from {'ios-dark.svg' if 'ios-dark' in has else 'fg.svg'})"),
           li("ios-tinted" in has or "mono" in has, f"tinted (from {'ios-tinted.svg' if 'ios-tinted' in has else 'mono.svg'})"
              if "ios-tinted" in has or "mono" in has else "tinted: a grayscale of fg.svg (no mono.svg)")]
    android = [li("mono" in has, "monochrome" if "mono" in has else "no mono.svg: themed icons show the colour icon"),
               li(True, "Play icon (from play.svg)" if "play" in has else "Play icon (bg + fg)")]
    slots = {
        "vars": " ".join(f"{k}: {v};" for k, v in vars_.items()), "cls": " ".join(cls),
        "title": esc(" · ".join(x for x in (str(a.get("title") or "App icon"), name) if x)),
        "built": f"Built from {built}. Each tile is a comment target: {code(f'el:{aid}/ios-dark')}.",
        "layer_names": "bg + fg" if bg or "bg" in has else "fg", "name": esc(name or str(a.get("title") or aid)[:30]),
        "ios_checks": "".join(ios), "android_checks": "".join(android),
        "json": json.dumps({"bg": bg, "layers": uri}).replace("</", "<\\/"),
    }
    sheet = (KITS / "icon-sheet.html").read_text(encoding="utf-8")
    return re.sub(r"\{\{(\w+)\}\}", lambda m: slots[m[1]], sheet)



def icon_file_ok(rel: str, data: bytes) -> str | None:
    """Why data can't be the export file rel, or None: a PNG of its exact size under the cap, Contents.json as a JSON
    object with images, an adaptive-icon XML."""
    size = ICON_FILES[rel]
    if size is not None:
        if len(data) > ICON_MAX_PNG:
            return "over 4 MB"
        if data[:8] != PNG_SIG or data[12:16] != b"IHDR" or len(data) < 24:
            return "not a PNG"
        w, h = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        return None if (w, h) == (size, size) else f"{w} x {h}, want {size} x {size}"
    if len(data) > ICON_MAX_TEXT:
        return "over 64 KB"
    try:
        if rel.endswith(".json"):
            j = json.loads(data.decode("utf-8"))
            return None if isinstance(j, dict) and isinstance(j.get("images"), list) else "not an asset catalog Contents.json"
        import xml.etree.ElementTree as ET   # noqa: PLC0415 (only this route parses XML)
        root = ET.fromstring(data.decode("utf-8"))
    except (ValueError, SyntaxError) as e:   # ET.ParseError is a SyntaxError
        return f"unreadable: {e}"
    return None if root.tag == "adaptive-icon" else "not an <adaptive-icon>"


def icons_dir(doc: Path, aid: str) -> Path:
    """Where an icons artboard's export goes: <stem>.icons/<artboard>/ beside the doc."""
    return doc.parent / f"{build.doc_stem(doc)}.icons" / aid


def save_icons(doc: Path, aid, files) -> tuple[int, dict]:
    """(status, answer) of POST /__bluedoc/icons: files {path in ICON_FILES: base64} written into icons_dir(doc, aid)
    when aid is an `icons` artboard of the design doc. Every file is checked before any is written; each is replaced
    atomically. Nothing outside that folder: no other name, no symlink on the way."""
    try:
        doc_json = json.loads(doc.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return 500, {"error": f"cannot read the doc: {e}"}
    if not (isinstance(aid, str) and isinstance(doc_json, dict) and icon_artboard(doc_json, aid)):
        return 404, {"error": "no icons artboard by that id in the doc"}
    if not isinstance(files, dict) or not files:
        return 400, {"error": "files: want {path: base64}"}
    decoded: dict[str, bytes] = {}
    for rel, b64 in files.items():
        if rel not in ICON_FILES:
            return 400, {"error": f"{rel!r} is not a file of an icon export"}
        try:
            if not isinstance(b64, str) or len(b64) > ICON_MAX_PNG * 4 // 3 + 4:
                raise ValueError
            data = base64.b64decode(b64, validate=True)
        except ValueError:
            return 400, {"error": f"{rel}: not base64 under the cap"}
        why = icon_file_ok(rel, data)
        if why:
            return 400, {"error": f"{rel}: {why}"}
        decoded[rel] = data
    out = icons_dir(doc, aid)
    want = doc.parent.resolve() / out.parent.name / aid
    for rel in decoded:   # every folder on the way and the file itself: none a link, before anything is written
        p = out.parent
        for part in (aid, *rel.split("/")):
            p = p / part
            if p.is_symlink():
                return 409, {"error": f"{rel}: a link on the way out of {out.parent.name}/{aid}"}
    if out.parent.is_symlink():
        return 409, {"error": f"{out.parent.name} is a link"}
    try:
        for rel, data in decoded.items():
            target = out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.parent.resolve() != (want / rel).parent:
                return 409, {"error": f"{rel}: a link on the way out of {out.parent.name}/{aid}"}
            fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".bd-", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                os.chmod(tmp, 0o644)
                os.replace(tmp, target)
            finally:
                Path(tmp).unlink(missing_ok=True)
    except OSError as e:
        return 500, {"error": f"cannot write the export: {e}"}
    return 200, {"ok": True, "dir": f"{out.parent.name}/{aid}", "files": sorted(decoded)}


# ---------- store listing uploads ----------

LISTING_UPLOAD_BODY = listing.UPLOAD_MAX_BYTES * 4 // 3 + 65536   # the POST's JSON: a PNG at the limit in base64, and the rest
# each POST route's body limit (MAX_BODY for the rest)
POST_LIMITS = {"/__bluedoc/icons": ICON_MAX_BODY, "/__bluedoc/snapshot": SNAPSHOT_BODY, "/__bluedoc/listing/upload": LISTING_UPLOAD_BODY}


def save_listing_upload(doc: Path, data: dict) -> tuple[int, dict]:
    """(status, answer) of POST /__bluedoc/listing/upload {path, platform, locale, set, slot, png: base64}: the PNG,
    checked against the set's rule (size, RGB or indexed colour without tRNS, the byte limit, the slot range), written
    atomically to <stem>.listing/<platform>/<locale>/<set name>/NN.png. `set` may name an ads asset too (Google Ads
    images, the search results asset: listing.upload_rules). It is a draft until the agent records it as a shot's or
    asset's src. A file a revision records is never overwritten: the upload takes the next free name. {path, discard:
    <file>} deletes a draft instead. Nothing outside that folder, no link on the way. A failed check answers 400 with
    the rule and its source key."""
    try:
        d = json.loads(doc.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return 500, {"error": f"cannot read the doc: {e}"}
    lb = listing.listing_of(d) if isinstance(d, dict) and build.doc_type(d.get("meta") or {}) == "storelisting" else None
    if lb is None:
        return 404, {"error": "not a storelisting doc"}
    rules = listing.load_rules()
    if "discard" in data:
        if not any(u["file"] == data["discard"] for u in listing.uploads(d, doc, rules)):
            return 404, {"error": "no draft upload by that name: a recorded shot is changed by the agent"}
        f = doc.parent / data["discard"]
        if f.is_symlink():
            return 409, {"error": "a link"}
        f.unlink(missing_ok=True)
        return 200, {"ok": True, "discarded": data["discard"]}
    set_id, platform, locale, slot = data.get("set"), data.get("platform"), data.get("locale"), data.get("slot")
    rule = listing.upload_rules(rules).get(set_id) if isinstance(set_id, str) else None
    if rule is None or rule.get("platform") != platform or platform not in (lb.get("platforms") or []):
        return 400, {"error": "set: one of the listing's sets or ads assets, with its platform"}
    if not isinstance(locale, str) or locale not in (lb.get("locales") or []):
        return 400, {"error": f"locale: one of {', '.join(lb.get('locales') or [])}"}
    hi = (rule.get("count") or [0, 10])[1]
    if not (isinstance(slot, int) and not isinstance(slot, bool) and 1 <= slot <= hi):
        return 400, {"error": f"slot: 1 to {hi}: {rule['label']} takes at most {hi} shots", "rule": set_id, "source": rule["source"]}
    limit = rule.get("maxBytes", listing.UPLOAD_MAX_BYTES)
    try:
        b64 = data.get("png")
        if not isinstance(b64, str) or len(b64) > limit * 4 // 3 + 4:
            raise ValueError
        png = base64.b64decode(b64, validate=True)
    except ValueError:
        return 400, {"error": f"png: base64 of a PNG, at most {limit // 1048576} MB", "rule": set_id, "source": rule["source"]}
    why = listing.upload_problem(rule, png)
    if why:
        return 400, {"error": f"{rule['label']}: {why}", "rule": set_id, "source": rule["source"]}
    folder = listing.upload_folder(doc, set_id, locale)
    rel_dir = folder.relative_to(doc.parent)
    p = doc.parent
    for part in rel_dir.parts:   # <stem>.listing, the platform, the locale, the set: none a link
        p = p / part
        if p.is_symlink():
            return 409, {"error": f"{p.relative_to(doc.parent)} is a link"}
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if folder.resolve() != doc.parent.resolve() / rel_dir:
            return 409, {"error": f"a link on the way to {rel_dir.as_posix()}"}
        rel_of = lambda n: f"{rel_dir.as_posix()}/{n}"  # noqa: E731
        name = listing.next_upload_name(folder, slot, listing.recorded_srcs(d, doc), rel_of)
        if name is None:
            return 409, {"error": f"{rel_dir.as_posix()} has no free name left (99 files)"}
        target = folder / name
        if target.is_symlink():
            return 409, {"error": f"{rel_of(name)} is a link"}
        replaced = target.exists()
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".bd-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(png)
            os.chmod(tmp, 0o644)
            os.replace(tmp, target)
        finally:
            Path(tmp).unlink(missing_ok=True)
    except OSError as e:
        return 500, {"error": f"cannot write the upload: {e}"}
    info = listing.png_info(png) or {}
    return 200, {"ok": True, "file": rel_of(name), "slot": int(name[:2]), "w": info.get("w"), "h": info.get("h"),
                 "colour": info.get("colour"), "bytes": len(png), "replaced": replaced}


def listing_drafts_block(doc: Path) -> str | None:
    """Why a storelisting can't be approved yet, or None: an uploaded shot no revision records (the page disables
    Approve too; this backs it)."""
    try:
        d = json.loads(doc.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not (isinstance(d, dict) and build.doc_type(d.get("meta") or {}) == "storelisting"):
        return None
    n = len(listing.uploads(d, doc))
    return f"{n} uploaded shot{'s are' if n != 1 else ' is'} not recorded yet: send Request changes, wait for the agent's " \
           "revision, then approve" if n else None


# ---------- store listing brand: the brand image and the installed fonts ----------

BRAND_EXT = {"png": "png", "jpeg": "jpg", "webp": "webp"}   # the brand image's type -> its file's extension
BRAND_IMAGE_BODY = listing.load_rules()["brand"]["image"]["maxBytes"] * 4 // 3 + 4096   # the POST's JSON: the image in base64
POST_LIMITS["/__bluedoc/listing/brand"] = BRAND_IMAGE_BODY


def save_brand_image(doc: Path, data: dict) -> tuple[int, dict]:
    """(status, answer) of POST /__bluedoc/listing/brand {path, data: base64}: a storelisting's brand image (PNG, JPEG
    or WebP by its first bytes, at most the rules' brand.image.maxBytes) written atomically to
    <stem>.listing/brand/source.<png|jpg|webp>, replacing the source of another type. The page extracts the palette
    itself; the file is what listing.brand.image records. No link on the way out of the folder."""
    try:
        d = json.loads(doc.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return 500, {"error": f"cannot read the doc: {e}"}
    if not (isinstance(d, dict) and build.doc_type(d.get("meta") or {}) == "storelisting"):
        return 400, {"error": "a brand image is a storelisting's"}
    rule = listing.load_rules()["brand"]["image"]
    b64 = data.get("data")
    try:
        if not isinstance(b64, str) or len(b64) > rule["maxBytes"] * 4 // 3 + 4:
            raise ValueError
        raw = base64.b64decode(b64, validate=True)
    except ValueError:
        return 413 if isinstance(b64, str) and len(b64) > rule["maxBytes"] * 4 // 3 + 4 else 400, \
            {"error": f"data: the image in base64, at most {rule['maxBytes'] // 1048576} MB"}
    kind = listing.brand_image_type(raw)
    if kind not in rule["types"] or len(raw) > rule["maxBytes"]:
        return 400, {"error": f"a {', '.join(t.upper() for t in rule['types'])} image of at most {rule['maxBytes'] // 1048576} MB"}
    top = listing.listing_dir(doc)
    folder = top / "brand"
    for p in (top, folder):
        if p.is_symlink() or (p.exists() and not p.is_dir()):
            return 409, {"error": f"{p.name} is a link or a file"}
    target = folder / f"source.{BRAND_EXT[kind]}"
    if target.is_symlink():
        return 409, {"error": f"{target.name} is a link"}
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if folder.resolve() != doc.parent.resolve() / top.name / "brand":
            return 409, {"error": "a link on the way to the brand folder"}
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".bd-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            os.chmod(tmp, 0o644)
            os.replace(tmp, target)
        finally:
            Path(tmp).unlink(missing_ok=True)
        for ext in BRAND_EXT.values():   # one source image: the last one sent
            old = folder / f"source.{ext}"
            if old != target and old.is_file() and not old.is_symlink():
                old.unlink()
    except OSError as e:
        return 500, {"error": f"cannot write the image: {e}"}
    return 200, {"ok": True, "file": f"{top.name}/brand/{target.name}", "type": kind, "bytes": len(raw)}


# ---------- reader state ----------

# link, layout, listing, element: drafts (template.html); an element draft's text and base are at most 1,000 characters
ANN_TYPES = ("pin", "text", "draw", "general", "link", "layout", "listing", "element")
EL_TEXT_MAX = 1000
_skipped: set[tuple[str, str]] = set()   # (doc, key) of stored values page_state left out and logged


def _target_ok(t) -> bool:
    return (isinstance(t, dict) and isinstance(t.get("key"), str) and bool(t["key"]) and isinstance(t.get("label"), str)
            and (t.get("text") is None or isinstance(t["text"], str)))


def _element_ok(e) -> bool:
    """An `element` draft's payload: {op: text | delete, ab, sel, tag, base, text (op text)}, text and base capped."""
    def s(k: str, n: int) -> bool:
        return isinstance(e.get(k), str) and len(e[k]) <= n
    return (isinstance(e, dict) and e.get("op") in ("text", "delete") and s("ab", 200) and bool(e["ab"]) and s("sel", 200)
            and bool(e["sel"]) and s("tag", 20) and s("base", EL_TEXT_MAX)
            and (e.get("text") is None and e["op"] == "delete" or s("text", EL_TEXT_MAX) and bool(e["text"]))
            and (e.get("ord") is None or isinstance(e["ord"], int) and not isinstance(e["ord"], bool)))


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
            and (a.get("pos") is None or isinstance(a["pos"], dict))
            and (a.get("type") != "link" or isinstance(a.get("link"), dict)
                 and all(isinstance(a["link"].get(k), str) for k in ("op", "from", "el")))
            and (a.get("type") != "layout" or isinstance(a.get("layout"), dict) and isinstance(a["layout"].get("positions"), dict))
            and (a.get("type") != "listing" or isinstance(a.get("listing"), dict) and isinstance(a["listing"].get("op"), str))
            and (a.get("type") != "element" or _element_ok(a.get("element"))))


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
            """A design screen: its fragment wrapped in its kit, sandboxed by its CSP, framable by our pages only. A live
            page's at an earlier revision: its snapshot (?w= its width), in the same frame."""
            found = screen_for_url(path, q.get("rev") or None)
            host = self.headers.get("Host") or ""
            if not found:
                snap = snapshot_for_url(path, q.get("rev") or None, q.get("w"))
                if snap:
                    html, origin = snap
                    return self.send(200, snapshot_page(html), framed=True,
                                     headers={"Content-Security-Policy": screen_csp(host, (origin,) if origin else ())})
                return self.send(404, "<!doctype html><title>Not found</title><p>No screen at this address. <a href='/'>All docs</a></p>")
            doc_path, doc, aid, fragment = found
            html = wrap_screen(doc, doc_path, aid, fragment, theme=q.get("theme") or None)
            return self.send(200, html, headers={"Content-Security-Policy": screen_csp(host)}, framed=True)

        def deck(self, q: dict) -> None:
            """GET /__bluedoc/deck?path=<doc URL path>[&rev=R][&theme=T][&format=F]: the presentation exported (F: html,
            the default, deck_html; pdf, deck_pdf; as downloads named <stem>.html or .pdf) or, format=print, the HTML
            file shown in the tab under DECK_PRINT_CSP. A read: no key, as for the doc's page."""
            fmt = q.get("format") or "html"
            if fmt not in DECK_FORMATS:
                return self.json(400, {"error": f"format: one of {', '.join(DECK_FORMATS)}"})
            doc_path = doc_for_url(q.get("path", ""))
            if not doc_path:
                return self.json(404, {"error": "not a doc under a registered folder"})
            try:
                doc = json.loads(doc_path.read_text(encoding="utf-8"))
                if not isinstance(doc, dict):
                    raise DeckError("the doc is not a JSON object")
                html = deck_html(doc, doc_path, q.get("rev") or None, q.get("theme") or None, load_roots())
            except (OSError, ValueError) as e:   # DeckError is a ValueError
                return self.json(400, {"error": str(e)})
            if fmt == "print":
                return self.send(200, html, headers={"Content-Security-Policy": DECK_PRINT_CSP})
            body, ctype = html, "text/html; charset=utf-8"
            if fmt == "pdf":
                chrome = find_chrome()
                if not chrome:
                    return self.json(501, {"error": DECK_PDF_NEEDS})
                try:
                    body, ctype = deck_pdf(html, chrome), "application/pdf"
                except (OSError, RuntimeError) as e:
                    return self.json(500, {"error": f"Chrome couldn't print the deck: {e}"})
            name = f"{build.doc_stem(doc_path)}.{fmt}"
            plain = re.sub(r'[^A-Za-z0-9._ -]', "_", name)
            return self.send(200, body, ctype, headers={"Content-Disposition": f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name)}"})

        def listing_export(self, q: dict) -> None:
            """GET /__bluedoc/listing?path=<doc URL path>[&format=zip|html|pdf|print][&rev=R][&platform=P][&locale=L]:
            the storelisting exported, as the attachment <stem>[-<platform>][-<locale>].<format>; print: the HTML file
            shown in the tab (the PDF without Chrome). A read, no key; the ZIP is made in a temp file and streamed."""
            fmt = q.get("format") or "zip"
            if fmt not in LISTING_FORMATS:
                return self.json(400, {"error": f"format: one of {', '.join(LISTING_FORMATS)}"})
            doc_path = doc_for_url(q.get("path", ""))
            if not doc_path:
                return self.json(404, {"error": "not a doc under a registered folder"})
            try:
                doc = json.loads(doc_path.read_text(encoding="utf-8"))
                if not isinstance(doc, dict):
                    raise ListingError("the doc is not a JSON object")
                listing_doc(doc, doc_path, q.get("rev") or None)   # the type and the revision, before Chrome
            except (OSError, ValueError) as e:   # ListingError is a ValueError
                return self.json(400, {"error": str(e)})
            chrome = find_chrome() if fmt in ("zip", "pdf") else None
            if fmt in ("zip", "pdf") and not chrome:
                return self.json(501, {"error": LISTING_NEEDS})
            part = [x for x in (q.get("platform"), q.get("locale")) if x]
            name = "-".join([build.doc_stem(doc_path), *part]) + f".{'html' if fmt == 'print' else fmt}"
            plain = re.sub(r'[^A-Za-z0-9._ -]', "_", name)
            headers = {"Content-Disposition": f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name)}",
                       "X-Bluedoc-Warnings": json.dumps(listing_warnings(doc, "pdf" if fmt == "print" else fmt))}
            if fmt == "zip":
                with tempfile.TemporaryDirectory(prefix="bluedoc-listing-zip-") as d:
                    out = Path(d) / name
                    try:
                        listing_zip(doc, doc_path, out, chrome, rev=q.get("rev") or None, platform=q.get("platform") or None,
                                    locale=q.get("locale") or None, roots=load_roots())
                    except ListingError as e:
                        return self.json(400, {"error": str(e)})
                    except (OSError, RuntimeError) as e:
                        return self.json(500, {"error": f"Chrome couldn't render the listing: {e}"})
                    self.send_response(200)
                    for k, v in {"Content-Type": "application/zip", "Content-Length": str(out.stat().st_size),
                                 "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", **headers}.items():
                        self.send_header(k, v)
                    self.end_headers()
                    if self.command != "HEAD":
                        with open(out, "rb") as f:
                            shutil.copyfileobj(f, self.wfile, 1 << 20)
                    return
            if q.get("platform") or q.get("locale"):
                return self.json(400, {"error": "platform and locale narrow the ZIP only"})
            try:
                html = listing_html(doc, doc_path, q.get("rev") or None, load_roots())
            except (OSError, ValueError) as e:
                return self.json(400, {"error": str(e)})
            if fmt == "print":
                return self.send(200, html, headers={"Content-Security-Policy": DECK_PRINT_CSP})
            if fmt == "pdf":
                try:
                    return self.send(200, listing_pdf(html, chrome), "application/pdf", headers=headers)
                except (OSError, RuntimeError) as e:
                    return self.json(500, {"error": f"Chrome couldn't print the listing: {e}"})
            return self.send(200, html, headers=headers)

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
            """Whether the request carries the server's key: in X-Bluedoc-Key (the CLI, or a page's localStorage copy)
            or in the cookie (a browser that opened an `open`/`unlock` link). Either one is enough."""
            return is_key(self.headers.get("X-Bluedoc-Key")) or is_key(self.cookie_key())

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
            """A ?key= link: a live token sets the key cookie; either way, go to the URL without it."""
            ok = unlock_token_live(parse_qs(u.query).get("key", [""])[0])
            rest = urlencode([(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k != "key"])
            self.send_response(303)
            self.send_header("Location", u.path + ("?" + rest if rest else ""))
            if ok:
                self.send_header("Set-Cookie", set_cookie())
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def page_key(self) -> None:
            """GET /__bluedoc/key: the key, for the page to keep in localStorage and send as X-Bluedoc-Key, since some
            browsers drop cookies (Tern's WKWebView keeps localStorage but no cookie jar). Only to our own page: it
            needs the key cookie (SameSite=Strict), the X-Bluedoc header (a cross-origin fetch can't send it without
            a preflight this server never answers) and no foreign Origin or Sec-Fetch-Site."""
            origin, site = self.headers.get("Origin"), self.headers.get("Sec-Fetch-Site")
            if (self.headers.get("X-Bluedoc") != "1" or (origin and urlsplit(origin).netloc not in hosts)
                    or (site and site != "same-origin") or not is_key(self.cookie_key())):
                return self.json(403, {"error": "the key goes only to this server's own page, with the key cookie"})
            return self.json(200, {"key": SECRET})

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
            if u.path == "/__bluedoc/key":
                return self.page_key()
            if u.path == "/__bluedoc/url":
                return self.json(200, {"url": url_for(Path(q.get("doc", "")))})
            if u.path == "/__bluedoc/listing":
                return self.listing_export(q)
            if u.path == "/__bluedoc/deck":
                return self.deck(q)
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
            if u.path == "/__bluedoc/fonts":
                # the fonts installed here (fonts.py): the key, as for a write, since it lists this machine's files
                if self.headers.get("X-Bluedoc") != "1":
                    return self.json(403, {"error": "missing X-Bluedoc header"})
                if not self.has_key():
                    return self.no_key()
                return self.json(200, {"families": fonts.families()})
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
            data = self.body(POST_LIMITS.get(path, MAX_BODY))
            if data is None:
                return
            if path == "/__bluedoc/snapshot":
                doc = doc_for_url(str(data.get("path") or ""))
                if not doc:
                    return self.json(404, {"error": "the page's doc is not under a registered folder"})
                code, answer = save_snapshot(doc, data.get("rev"), data.get("page"), data.get("w"), data.get("html"), data.get("external", 0))
                if code == 200:
                    print(f"snapshot for {doc}: {answer['file']}", flush=True)
                return self.json(code, answer)
            if path == "/__bluedoc/listing/upload":
                doc = doc_for_url(str(data.get("path") or ""))
                if not doc:
                    return self.json(404, {"error": "the page's doc is not under a registered folder"})
                code, answer = save_listing_upload(doc, data)
                if code == 200:
                    print(f"upload for {doc}: {answer.get('file') or answer.get('discarded')}", flush=True)
                return self.json(code, answer)
            if path == "/__bluedoc/icons":
                doc = doc_for_url(str(data.get("path") or ""))
                if not doc:
                    return self.json(404, {"error": "the page's doc is not under a registered folder"})
                code, answer = save_icons(doc, data.get("artboard"), data.get("files"))
                if code == 200:
                    print(f"icons for {doc}: {len(answer['files'])} file(s) in {answer['dir']}", flush=True)
                return self.json(code, answer)
            if path == "/__bluedoc/listing/brand":
                doc = doc_for_url(str(data.get("path") or ""))
                if not doc:
                    return self.json(404, {"error": "the page's doc is not under a registered folder"})
                code, answer = save_brand_image(doc, data)
                if code == 200:
                    print(f"brand image for {doc}: {answer['file']}", flush=True)
                return self.json(code, answer)
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
                # an item still asking for more details blocks approval (the page disables Approve; this backs it)
                if ok and any(isinstance(a, dict) and a.get("more") for a in data.get("answers", [])):
                    return self.json(409, {"error": "an item asks for more details: send that request or withdraw it, then approve"})
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
                why = listing_drafts_block(doc)
                if why:
                    return self.json(409, {"error": why})
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
    LIVE.page_port = port   # its pages may frame the live pages' proxies
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


def port_free(port: int) -> bool:
    """Nothing listens on 127.0.0.1:port: a bind succeeds with SO_REUSEADDR, as the server's own does, so a port that
    only has closed connections lingering (TIME_WAIT) still counts as free."""
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def last_port() -> int | None:
    try:
        return int(json.loads(SERVER_FILE.read_text()).get("port"))
    except (OSError, ValueError, TypeError):
        return None


def ensure_started(port: int, pinned: bool = False) -> bool:
    """Start the server unless one runs this very code; one that runs another version or code is replaced. Unless the
    port is pinned (--port, BLUEDOC_PORT), a port another program holds is skipped for the next free one of PORT_SPAN,
    the port the last server used first, so open tabs and the key cookie carry over; server.json records the one used."""
    last = last_port()   # read before a restart: the stopping server removes server.json
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
    if pinned:
        if not port_free(port):
            print(f"port {port} is in use by another program: free it, or unset BLUEDOC_PORT (and drop --port) so bluedoc "
                  f"picks a free one", file=sys.stderr)
            return False
        tries = [port]
    else:
        span = range(port, port + PORT_SPAN)
        tries = [p for p in dict.fromkeys([*([last] if last in span else []), *span]) if port_free(p)]
        if not tries:
            print(f"ports {port}-{port + PORT_SPAN - 1} are all in use: set BLUEDOC_PORT to a free port", file=sys.stderr)
            return False
        if tries[0] != port and tries[0] != last:
            print(f"port {port} is in use by another program; the bluedoc server takes {tries[0]}", file=sys.stderr)
    STATE.mkdir(parents=True, exist_ok=True)
    log = open(STATE / "server.log", "a")
    for p in tries[:3]:   # a port taken between the check and the bind: the next one
        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "run", "--port", str(p)],
                                stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        for _ in range(50):
            time.sleep(0.1)
            if proc.poll() is not None:
                break
            try:
                if json.loads(SERVER_FILE.read_text()).get("port") == p and alive():
                    return True
            except (OSError, ValueError):
                pass
        if proc.poll() is None:
            break
    print(f"server did not start; see {STATE / 'server.log'}", file=sys.stderr)
    return False


# ---------- frameworks the reader adds ----------

MAX_FRAMEWORK_BYTES = 64 * 1024 * 1024
FRAMEWORK_LOAD_EXTS = (".css", ".js", ".mjs")
_TW = ("https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3/dist/index.global.js",
       "a60c785630a06196808cbe79e6f7bdb4abcc8f4421a47b56f29338fc84805e3b", "tailwind.js")
_TW_LICENSE = ("https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3/LICENSE",
               "60e0b68c0f35c078eef3a5d29419d0b03ff84ec1df9c3f9d6e39a519a5ae7985", "licenses/tailwindcss-LICENSE")
# `add-framework <preset>`: pinned files (url, sha256, saved as), fetched once on the reader's command. daisyUI's
# prebuilt component CSS, plus Tailwind's browser build to compile Tailwind classes in the frame. heroui and tailwind
# were presets too; they ship now (assets/vendor/heroui).
PRESETS = {
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
    if source is None and name in build.SHIPPED_PRESETS:
        print(f"{name} ships with bluedoc: boards use \"framework\": \"{name}\" with no add-framework")
        return 0
    if not build.ID_RE.match(name) or name in build.BUILTIN_FRAMEWORKS:
        print(f"add-framework: {name!r} must be lowercase letters, digits and dashes, and not "
              f"{', '.join(build.BUILTIN_FRAMEWORKS)} (they ship with bluedoc)", file=sys.stderr)
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
        p.add_argument("--port", type=int, default=None, help=f"default {DEFAULT_PORT} (BLUEDOC_PORT); start: a port in use is skipped "
                                                              f"for the next free one unless --port or BLUEDOC_PORT pins it")
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
    p = sub.add_parser("snapshot", help="record a website doc's live pages as its revision's snapshots (headless Chrome)")
    p.add_argument("doc", type=Path)
    p.add_argument("--rev", help="the revision to record (default: the doc's meta.rev); an earlier one only where it has none")
    p.add_argument("--url", help="read the pages from this dev server (scheme://host:port; each page keeps its path), "
                                 "e.g. a checkout of that revision on another port")
    p.add_argument("--page", action="append", default=[], metavar="ID", help="only this live page (repeatable)")
    p.add_argument("--width", action="append", default=[], type=int, metavar="PX",
                   help="only this width (repeatable; default: the board's breakpoints)")
    a = ap.parse_args()

    if a.cmd == "run":
        return run(a.port or DEFAULT_PORT, a.to)
    if a.cmd == "start":
        if not ensure_started(a.port or DEFAULT_PORT, pinned=a.port is not None or PORT_PINNED):
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
        if not ensure_started(DEFAULT_PORT, pinned=PORT_PINNED):
            return 1
        print(f"{base()}/?key={call('/__bluedoc/unlock', {})[1]['token']}")
        return 0
    if a.cmd == "snapshot":
        return cmd_snapshot(a.doc, a.rev, a.url, a.page, a.width)

    doc = a.doc.resolve()
    if not doc.is_file() or not is_doc(doc):
        print(f"{a.doc}: not a {DOC_FILES} file", file=sys.stderr)
        return 2
    if a.cmd == "open":
        add_root(a.root.resolve() if a.root else root_for(doc))
        if not ensure_started(DEFAULT_PORT, pinned=PORT_PINNED):
            return 1
        res = call("/__bluedoc/register", {"doc": str(doc), "to": a.to})[1]
        # the ?key= token (good for an hour) lets this browser save; visiting it redirects to the plain URL
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
