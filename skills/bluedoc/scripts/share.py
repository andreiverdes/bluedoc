#!/usr/bin/env python3
"""Share a doc as a secret GitHub gist, opened at https://bluedoc.ai/g/<code> (link_for; serve.py share/unshare,
POST /__bluedoc/share and /__bluedoc/unshare).

The gist holds three text files (gh gist create refuses binaries), made from the doc as it is now:
  <stem>.bluedoc.json           the doc, verbatim
  <stem>.bluedoc.history.json   its revisions with the current one recorded (build.history_now), when it has meta.rev
  bluedoc-page.json             what the bluedoc.ai viewer fills the template with:
      {"bluedoc": "share/1", "version": <bluedoc version>, "name": <stem>, "title": <shown title>, "rev": <meta.rev or
       null>, "boardGeo": <whether the page needs assets/board-geo.js at /*__BOARD_GEO__*/>,
       "fill": {placeholder: text}}: exactly what build.py -o substitutes (build.standalone_fill: diffs expanded,
      media and screens inline, no reader state) but the board-geo slot, which the viewer fills from its own copy.
A bluedoc-page.json over MAX_PAGE_BYTES (10 MB) is refused (413): Export → HTML file sends the doc instead.

gh does the GitHub side, as the user it is signed in as: `gh auth status` first (gh missing: 501; signed out or a
token without the gist scope: 502, naming `gh auth login` or `gh auth refresh -s gist`). The first share runs
`gh gist create` (secret, described `bluedoc: <title>`); a later one `gh api -X PATCH gists/<id>` with every file
(files it no longer has set to null), so the link stays; a gist gone from GitHub is created anew. unshare runs
`gh api -X DELETE gists/<id>` and forgets the share, also when the gist is gone already.

Shares are recorded in $BLUEDOC_HOME/shares.json (mode 0600), keyed by the doc's resolved path: {id, user, link,
url, rev, at, files}. Never in the doc or its folder, so a committed doc doesn't carry its link.

The link (link_for): https://bluedoc.ai/g/<code>, code the gist id's bytes in base64url without padding (a 32-hex id
is 22 characters, a 20-hex one 14); an id that isn't even-length lowercase hex keeps the long form
https://bluedoc.ai/g/#<user>/<id>. The viewer decodes the code back to the id.

Every share shows NOTICE: bluedoc isn't responsible for this share method or for secrets leaked through GitHub
gists; a secret gist is unlisted and not searchable, but anyone with the link can read it.
Python 3.9+ standard library only.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import build  # noqa: E402

FORMAT = "share/1"
PAGE_FILE = "bluedoc-page.json"
MAX_PAGE_BYTES = 10 * 1024 * 1024   # a gist file's raw limit
VIEWER = "https://bluedoc.ai/g/"
# the notice every share shows (template.html's share dialog says the same; tests/test_share.py holds them equal)
NOTICE_LEAD = "bluedoc isn't responsible for this share method or for secrets leaked through GitHub gists."
NOTICE_REST = ("A secret gist is unlisted and not searchable, but anyone with the link can read it. "
               "Check the doc for secrets before you share.")
NOTICE = f"{NOTICE_LEAD} {NOTICE_REST}"
# a doc type whose page isn't the one -o writes: it has exports of its own (serve.py EXPORT_OWN)
NOT_SHARED = {"presentation": "a presentation isn't shared as a gist: export it from its board's Export to…",
              "storelisting": "a storelisting isn't shared as a gist: export it from its Export to…"}
GH_TIMEOUT = 180
LOCK = threading.Lock()   # one share or unshare at a time in this process: they read and write shares.json


class ShareError(Exception):
    """Why a share or unshare didn't happen; status is the HTTP status the routes answer with."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def shares_file() -> Path:
    return Path(os.environ.get("BLUEDOC_HOME") or "~/.bluedoc").expanduser() / "shares.json"


def _load() -> dict:
    try:
        data = json.loads(shares_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    f = shares_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    tmp.replace(f)


def record_of(doc_path: Path) -> dict | None:
    """The doc's share ({id, user, link, url, rev, at, files}), or None when it isn't shared. Its link is link_for's
    now, so a share recorded with an older link form shows the current one."""
    r = _load().get(str(Path(doc_path).resolve()))
    if not (isinstance(r, dict) and isinstance(r.get("id"), str)):
        return None
    return {**r, "link": link_for(str(r.get("user") or ""), r["id"])}


def link_for(user: str, gist_id: str) -> str:
    """The doc's bluedoc.ai link: https://bluedoc.ai/g/<base64url of the id's bytes, no padding> for an even-length
    lowercase hex id (every GitHub gist id), else https://bluedoc.ai/g/#<user>/<id>."""
    if re.fullmatch(r"(?:[0-9a-f]{2})+", gist_id):
        return VIEWER + base64.urlsafe_b64encode(bytes.fromhex(gist_id)).rstrip(b"=").decode("ascii")
    return f"{VIEWER}#{user}/{gist_id}"


def gist_name(doc_path: Path) -> str:
    """The doc's file name in the gist: <stem>.bluedoc.json (a .blueprint.json doc too)."""
    return build.doc_stem(Path(doc_path)) + ".bluedoc.json"


def read_doc(doc_path: Path) -> tuple[str, dict]:
    """(the doc's text, its JSON). ShareError (400): unreadable, not an object, or a type that isn't shared."""
    try:
        text = Path(doc_path).read_text(encoding="utf-8")
        doc = json.loads(text)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ShareError(f"cannot read {Path(doc_path).name}: {e}", 400) from e
    if not isinstance(doc, dict):
        raise ShareError(f"{Path(doc_path).name} is not a JSON object", 400)
    kind = build.doc_type(doc.get("meta") if isinstance(doc.get("meta"), dict) else {})
    if kind in NOT_SHARED:
        raise ShareError(NOT_SHARED[kind], 400)
    return text, doc


def _media_srcs(x, out: set[str]) -> set[str]:
    """The relative media srcs build.inline_media puts inline: media blocks', compare sides', evidence entries'."""
    rel = lambda s: isinstance(s, str) and s and not s.startswith("data:") and not re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:|/", s)  # noqa: E731
    if isinstance(x, list):
        for v in x:
            _media_srcs(v, out)
    elif isinstance(x, dict):
        srcs = [x.get("src")] if x.get("type") == "media" else []
        if x.get("type") == "compare":
            srcs += [s.get("src") for s in (x.get("before"), x.get("after")) if isinstance(s, dict)]
        if isinstance(x.get("evidence"), list):
            srcs += [e.get("src") for e in x["evidence"] if isinstance(e, dict)]
        out.update(s.split("?", 1)[0].split("#", 1)[0] for s in srcs if rel(s))
        for v in x.values():
            _media_srcs(v, out)
    return out


def contents(doc: dict, history: dict | None) -> dict:
    """What goes in, for the confirm: {revisions, diffs (diff blocks: refs go in expanded, with their code), media
    (files inlined), screens (a board's artboards with a screen file)}, counted over the current doc and, for media
    and diffs, the earlier revisions the page carries too."""
    pool = list(((history or {}).get("blocks") or {}).values())
    blocks = list(build.all_blocks(doc)) + [b for b in pool if isinstance(b, dict)]
    diffs = {build._canon(b) for b in blocks if b.get("type") == "diff"}
    return {"revisions": len((history or {}).get("revs") or []) or 1,
            "diffs": len(diffs), "media": len(_media_srcs([doc, pool], set())),
            "screens": len([a for a in build._artboards(doc) if not build.is_live(a)])}


def bundle(doc: dict, doc_path: Path, history: dict | None) -> dict:
    """bluedoc-page.json's object: build.standalone_fill's values, with the board-geo slot as boardGeo."""
    fill = build.standalone_fill(doc, Path(doc_path), history, problems=[])
    geo = fill.pop(build.BOARD_GEO_SLOT)
    rev = (doc.get("meta") or {}).get("rev")
    return {"bluedoc": FORMAT, "version": build.skill_version() or "unknown", "name": build.doc_stem(Path(doc_path)),
            "title": build.shown_title(doc, None), "rev": str(rev) if rev not in (None, "") else None,
            "boardGeo": bool(geo), "fill": fill}


def gist_files(doc_path: Path) -> tuple[dict[str, str], dict, dict]:
    """({file name: text} for the gist, the doc, contents()). ShareError: an unreadable doc or history, a deck or a
    listing (400), a bluedoc-page.json over MAX_PAGE_BYTES (413)."""
    doc_path = Path(doc_path).resolve()
    text, doc = read_doc(doc_path)
    try:
        history = build.history_now(doc_path, doc)
    except build.HistoryError as e:
        raise ShareError(str(e), 400) from e
    page = json.dumps(bundle(doc, doc_path, history), ensure_ascii=False, separators=(",", ":")) + "\n"
    size = len(page.encode("utf-8"))
    if size > MAX_PAGE_BYTES:
        raise ShareError(f"the shared page would be {size / 1048576:.1f} MB, over the 10 MB a gist file can hold: "
                         "send Export → HTML file instead", 413)
    files = {gist_name(doc_path): text}
    if history is not None:
        files[build.history_path(Path(gist_name(doc_path))).name] = json.dumps(history, ensure_ascii=False, indent=1) + "\n"
    files[PAGE_FILE] = page
    return files, doc, contents(doc, history)


# ---------- gh ----------

def gh(*args: str, stdin: str | None = None, cwd: Path | None = None, both: bool = False) -> str:
    """Run gh with args; its stdout (both: stdout then stderr, as `gh auth status` writes to either). ShareError: gh
    is missing (501), or failed (GhFailed, 502, with what it said)."""
    exe = shutil.which("gh")
    if not exe:
        raise ShareError("gh, the GitHub CLI, isn't installed: install it (https://cli.github.com), then run "
                         "`gh auth login -s gist`", 501)
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1", "GH_SPINNER_DISABLED": "1"}
    try:
        p = subprocess.run([exe, *args], input=stdin, capture_output=True, text=True, encoding="utf-8", env=env,
                           cwd=cwd, timeout=GH_TIMEOUT, stdin=None if stdin is not None else subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise ShareError(f"gh {args[0]} didn't answer within {GH_TIMEOUT} s") from e
    except OSError as e:
        raise ShareError(f"cannot run gh: {e}") from e
    if p.returncode != 0:
        raise GhFailed(args, p.stdout, p.stderr)
    return p.stdout + (p.stderr if both else "")


class GhFailed(ShareError):
    """gh ran and failed: what it said, and whether GitHub answered 404 (the gist is gone)."""

    def __init__(self, args, out: str, err: str) -> None:
        said = (err.strip() or out.strip()).splitlines()
        super().__init__(f"gh {' '.join(args[:2])} failed: {said[-1] if said else 'no message'}")
        self.not_found = bool(re.search(r"HTTP 404|Not Found", err + out))


def gh_login() -> str:
    """The GitHub login gh uses, after checking it can write gists. ShareError naming the gh command that fixes it."""
    try:
        text = gh("auth", "status", "--hostname", "github.com", both=True)
    except GhFailed as e:
        raise ShareError("gh isn't signed in to GitHub: run `gh auth login -s gist`") from e
    # gh 2.40+ lists each account ("Logged in to github.com account <login> (…)", "Active account: true"); older
    # ones "Logged in to github.com as <login>"; the active account's block holds its token scopes
    blocks = re.split(r"(?=^\s*[✓X!-]?\s*Logged in to )", text, flags=re.M)
    blocks = [b for b in blocks if "Logged in to" in b] or [text]
    block = next((b for b in blocks if re.search(r"Active account:\s*true", b)), blocks[0])
    m = re.search(r"Logged in to \S+ (?:account|as) ([A-Za-z0-9-]+)", block)
    login = m.group(1) if m else ""
    # a classic token lists its scopes; a fine-grained one (github_pat_…) has none, its permissions are GitHub's to check
    sm = re.search(r"Token scopes:\s*(.*)", block)
    if sm is not None and not re.search(r"Token:\s*github_pat_", block):
        if "gist" not in re.findall(r"[\w:]+", sm.group(1)):
            raise ShareError("gh's GitHub token lacks the gist scope: run `gh auth refresh -s gist`")
    if not login:
        try:
            login = gh("api", "user", "--jq", ".login").strip()
        except GhFailed as e:
            raise ShareError("gh isn't signed in to GitHub: run `gh auth login -s gist`") from e
    return login


def _gist(gist_id: str) -> dict | None:
    """The gist's JSON from GitHub, None when it's gone (404)."""
    try:
        data = json.loads(gh("api", f"gists/{gist_id}"))
    except GhFailed as e:
        if e.not_found:
            return None
        raise
    except ValueError as e:
        raise ShareError(f"gh api gists/{gist_id} answered something other than JSON: {e}") from e
    return data if isinstance(data, dict) else None


def _create(files: dict[str, str], desc: str, login: str) -> tuple[str, str, str]:
    """`gh gist create` (secret): (id, user, gist URL)."""
    with tempfile.TemporaryDirectory(prefix="bluedoc-share-") as d:
        for name, text in files.items():
            (Path(d) / name).write_text(text, encoding="utf-8")
        out = gh("gist", "create", "--desc", desc, *files, cwd=Path(d))
    m = re.findall(r"https://gist\.github\.com/(?:([A-Za-z0-9-]+)/)?([0-9a-f]+)\b", out)
    if not m:
        raise ShareError(f"gh gist create gave no gist URL: {out.strip()[:200]}")
    user, gist_id = m[-1]
    user = user or login
    return gist_id, user, f"https://gist.github.com/{user}/{gist_id}"


def _patch(gist_id: str, files: dict[str, str], desc: str, old: dict) -> tuple[str, str]:
    """`gh api -X PATCH gists/<id>`: every file, and null for the gist's files that aren't one now. (user, URL)."""
    body = {"description": desc, "files": {**{n: None for n in (old.get("files") or {}) if n not in files},
                                           **{n: {"content": t} for n, t in files.items()}}}
    out = gh("api", "-X", "PATCH", f"gists/{gist_id}", "--input", "-", stdin=json.dumps(body, ensure_ascii=False))
    try:
        data = json.loads(out)
    except ValueError:
        data = {}
    owner = (data.get("owner") or old.get("owner") or {}).get("login") or ""
    return owner, data.get("html_url") or old.get("html_url") or ""


def share(doc_path: Path) -> dict:
    """Put the doc in its secret gist: created on the first share, updated (same id, same link) after. Returns
    {share: the record, created: whether the gist is new, relinked: whether a gist gone from GitHub was created anew
    (a new link), contents, files: {name: bytes}}. A deck or a listing is refused first, then gh is checked, then the
    files are made (the size check). ShareError: see the module docstring."""
    doc_path = Path(doc_path).resolve()
    read_doc(doc_path)
    login = gh_login()
    files, doc, what = gist_files(doc_path)
    desc = f"bluedoc: {build.shown_title(doc, None) or build.doc_stem(doc_path)}"
    with LOCK:
        old = record_of(doc_path)
        gist = _gist(old["id"]) if old else None
        if gist is not None:
            user, url = _patch(old["id"], files, desc, gist)
            gist_id, user = old["id"], user or old.get("user") or login
            url = url or f"https://gist.github.com/{user}/{gist_id}"
        else:
            gist_id, user, url = _create(files, desc, login)
        rev = (doc.get("meta") or {}).get("rev")
        rec = {"id": gist_id, "user": user, "link": link_for(user, gist_id), "url": url,
               "rev": str(rev) if rev not in (None, "") else None,
               "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "files": sorted(files)}
        data = _load()
        data[str(doc_path)] = rec
        _save(data)
    return {"share": rec, "created": gist is None, "relinked": bool(old) and gist is None, "contents": what,
            "files": {n: len(t.encode("utf-8")) for n, t in files.items()}}


def unshare(doc_path: Path) -> dict | None:
    """Delete the doc's gist and forget it (also when GitHub has no such gist any more). The record it had, or None
    when it wasn't shared. ShareError: gh is missing or failed otherwise, and the share is kept."""
    doc_path = Path(doc_path).resolve()
    with LOCK:
        rec = record_of(doc_path)
        if rec is None:
            return None
        try:
            gh("api", "-X", "DELETE", f"gists/{rec['id']}")
        except GhFailed as e:
            if not e.not_found:
                raise
        data = _load()
        data.pop(str(doc_path), None)
        _save(data)
    return rec


def red(text: str, stream) -> str:
    """text in ANSI red (bold) when stream is a terminal."""
    return f"\x1b[1;31m{text}\x1b[0m" if getattr(stream, "isatty", lambda: False)() and not os.environ.get("NO_COLOR") else text


def contents_line(what: dict) -> str:
    n = lambda k, one, many: f"{what[k]} {one if what[k] == 1 else many}"  # noqa: E731
    return ", ".join([n("revisions", "revision", "revisions"), n("diffs", "diff with its code", "diffs with their code"),
                      n("media", "media file", "media files"), n("screens", "screen", "screens")])
