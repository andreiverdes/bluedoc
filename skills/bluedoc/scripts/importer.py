#!/usr/bin/env python3
"""Copy a shared doc into this machine's bluedoc: `serve.py import <link | gist URL | .zip> [--to DIR]`, the local
import page (GET /__bluedoc/import, POST /__bluedoc/import) and, later, the sharer's updates (check, merge3, pull).

Sources (parse_source): https://bluedoc.ai/g/<code> (the gist id's bytes in base64url, share.link_for), the long
https://bluedoc.ai/g/#<user>/<id>, a gist URL (https://gist.github.com/<user>/<id>), a bare code or gist id, and a
"bluedoc file (.zip)" from the shared page's Download menu (the doc, its media and screen files at their paths, and
bluedoc-share.json {by, link, version}: who shared it and where, and bluedoc-answers.json, their answers slot).

Fetching (fetch): with gh signed in, `gh api -i gists/<id>` as gh's active account (a 304 for an unchanged gist is
free); else GitHub's API without a token at $BLUEDOC_GITHUB_API (default https://api.github.com), 60 requests an hour
per IP address, a refusal saying when it resets. A file the API truncates is read from its raw_url, only on
gist.githubusercontent.com.

What a gist gives back (bundle_of): the doc (<stem>.bluedoc.json, verbatim); its media from bluedoc-page.json's inline
data: URIs, matched to the doc's relative srcs by position; a design's screen files from bluedoc-screens.json
({path from the doc's folder: text}), or, from a share made before that file, the wrapped screens with a warning; the
sharer's answers (__BLUEDOC_ANSWERS__) and the bluedoc version that shared it.

Checks before anything is written (plan_write): the doc validates with this bluedoc's build.py; every path is
relative, has no `..`, no backslash or NUL, and resolves inside the doc's folder through no symlink; at most
MAX_FILES files, MAX_FILE bytes each, MAX_TOTAL in all. A name already there gets -2 (-3, …), never an overwrite: the
doc's stem (its <stem>.design/ and other <stem>.* folders move with it) and any other file whose bytes differ (the
doc's references follow); a file already there with the same bytes is used as it is.

After writing: the copy carries meta.copiedFrom {by, rev, at} (who shared it, their rev, when it was copied) and its
history starts at the sharer's rev. $BLUEDOC_HOME/copies.json (0600), by the copy's resolved path, keeps what the doc
doesn't: {id, user, link, etag, rev, at, base (the sharer's doc text as imported: the merge base), answers (the
sharer's answers slot or null), checked (epoch of the last update check), latest ({rev, doc, etag}: a newer rev the
check found, or null), later (a rev the reader put off), review ([{id, label, path, theirs}]: parts a Pull kept as
the reader's where both changed)}.

Updates (check): at most every CHECK_EVERY seconds per copy, with If-None-Match. merge3 merges three-way against the
base: the head's fields, sections by id, blocks by position in their section, a block's items (checklist, steps,
cards, terms, files) by id when each has one; a part only the sharer changed takes theirs, one only the reader changed keeps theirs,
one both changed keeps the reader's and goes under review. pull writes that as a new rev ("Pulled <by>'s rev <r>").
Python 3.9+ standard library only."""
from __future__ import annotations

import base64
import binascii
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import build  # noqa: E402
import share  # noqa: E402

MAX_FILES = 500
MAX_FILE = 10 * 1024 * 1024
MAX_TOTAL = 30 * 1024 * 1024
CHECK_EVERY = 900.0
SCREENS_FILE = "bluedoc-screens.json"
RAW_HOST = "gist.githubusercontent.com"
TIMEOUT = 30
LOCK = threading.Lock()   # copies.json: one writer at a time in this process
ITEM_LISTS = ("checklist", "steps", "cards", "terms", "files")   # blocks whose items merge by id (when every item has one)
GIST_ID = re.compile(r"[0-9A-Za-z]{1,64}")


class ImportFailed(Exception):
    """Why an import, check or pull didn't happen; status is the HTTP status the routes answer with."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ---------- sources ----------

def gist_of_code(code: str) -> str | None:
    """A /g/<code>'s gist id: the code's base64url bytes as hex (share.link_for's inverse); None when it isn't one."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,64}", code):
        return None
    try:
        raw = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
    except (binascii.Error, ValueError):
        return None
    return raw.hex() if raw and share.link_for("", raw.hex()).endswith("/" + code) else None


def parse_source(src: str) -> dict:
    """{kind: "gist", id} or {kind: "zip", path}. ImportFailed (400) for anything else."""
    s = str(src or "").strip()
    if s.lower().endswith(".zip"):
        p = Path(s).expanduser()
        if not p.is_file():
            raise ImportFailed(f"{s}: no such file")
        return {"kind": "zip", "path": p.resolve()}
    m = re.fullmatch(r"(?:https?://)?(?:www\.)?bluedoc\.ai/g/(?:#|%23)([A-Za-z0-9-]{1,39})/([0-9A-Za-z]{1,64})/?", s)
    if m:
        return {"kind": "gist", "id": m[2]}
    m = re.fullmatch(r"(?:https?://)?(?:www\.)?bluedoc\.ai/g/([A-Za-z0-9_-]+)/?(?:[?#].*)?", s)
    if m:
        gid = gist_of_code(m[1])
        if gid:
            return {"kind": "gist", "id": gid}
    m = re.fullmatch(r"(?:https?://)?gist\.github\.com/(?:[A-Za-z0-9-]{1,39}/)?([0-9a-f]{20,64})/?(?:[?#].*)?", s)
    if m:
        return {"kind": "gist", "id": m[1]}
    m = re.fullmatch(r"([A-Za-z0-9-]{1,39})/([0-9A-Za-z]{1,64})", s)   # the long link's fragment, as the page passes it
    if m:
        return {"kind": "gist", "id": m[2]}
    if re.fullmatch(r"[0-9a-f]{20,64}", s):
        return {"kind": "gist", "id": s}
    gid = gist_of_code(s)
    if gid:
        return {"kind": "gist", "id": gid}
    raise ImportFailed(f"{s[:200]!r} isn't a bluedoc.ai/g/ link, a gist URL or a .zip from a shared page's Download")


# ---------- fetching ----------

def api_base() -> str:
    return (os.environ.get("BLUEDOC_GITHUB_API") or "https://api.github.com").rstrip("/")


def gh_signed_in() -> bool:
    """Whether gh is there with a signed-in github.com account (its active one reads the gist)."""
    try:
        return any(a.get("active") or a.get("usable") for a in share.accounts(fresh=False))
    except share.ShareError:
        return False


def _reset_text(headers: dict) -> str:
    try:
        at = dt.datetime.fromtimestamp(int(headers.get("x-ratelimit-reset") or 0)).strftime("%H:%M")
    except (ValueError, OSError, OverflowError):
        at = ""
    return f"after {at}" if at and at != "01:00" else "in an hour or less"


def rate_text(headers: dict) -> str:
    return ("GitHub refused: without gh signed in, it allows 60 requests an hour per IP address, and this one has used "
            f"them. Try again {_reset_text(headers)}, or sign in with `gh auth login`")


def fetch(gist_id: str, etag: str | None = None) -> dict:
    """The gist from GitHub: {status: 200 | 304, etag, data (the gist's JSON, None on 304), via: gh | anonymous}.
    ImportFailed: 404 (no such gist), 429 (GitHub's limit, with when it resets), 502 (anything else)."""
    if not GIST_ID.fullmatch(gist_id):
        raise ImportFailed("not a gist id", 400)
    if gh_signed_in():
        args = ["api", "-i", *(["-H", f"If-None-Match: {etag}"] if etag else []), f"gists/{gist_id}"]
        try:
            status, headers, body = share.parse_http(share.gh(*args))
        except share.GhFailed as e:
            status, headers, _ = share.parse_http(e.out)
            if e.not_found:
                raise ImportFailed("no such gist: it was deleted, or the link has a typo", 404) from None
            if status == 304:
                return {"status": 304, "etag": headers.get("etag") or etag, "data": None, "via": "gh"}
            raise ImportFailed(str(e), 502) from None
        except share.ShareError as e:
            raise ImportFailed(str(e), 502) from None
        if status == 304:
            return {"status": 304, "etag": headers.get("etag") or etag, "data": None, "via": "gh"}
        return {"status": 200, "etag": headers.get("etag"), "data": _gist_json(body), "via": "gh"}
    req = urllib.request.Request(f"{api_base()}/gists/{gist_id}", headers={
        "Accept": "application/vnd.github+json", "User-Agent": "bluedoc", **({"If-None-Match": etag} if etag else {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read(MAX_TOTAL + 1)
            if len(body) > MAX_TOTAL:
                raise ImportFailed("the gist is over 30 MB", 413)
            return {"status": 200, "etag": r.headers.get("ETag"), "data": _gist_json(body.decode("utf-8", "replace")), "via": "anonymous"}
    except urllib.error.HTTPError as e:
        headers = {k.lower(): v for k, v in e.headers.items()}
        e.close()
        if e.code == 304:
            return {"status": 304, "etag": headers.get("etag") or etag, "data": None, "via": "anonymous"}
        if e.code == 404:
            raise ImportFailed("no such gist: it was deleted, or the link has a typo", 404) from None
        if e.code in (403, 429) and (headers.get("x-ratelimit-remaining") == "0" or e.code == 429):
            raise ImportFailed(rate_text(headers), 429) from None
        raise ImportFailed(f"GitHub answered {e.code}", 502) from None
    except (urllib.error.URLError, OSError) as e:
        raise ImportFailed(f"couldn't reach GitHub: {getattr(e, 'reason', e)}", 502) from None


def _gist_json(body: str) -> dict:
    try:
        data = json.loads(body)
    except ValueError:
        raise ImportFailed("GitHub answered something other than JSON", 502) from None
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise ImportFailed("GitHub's answer has no files", 502)
    return data


def _raw(url: str) -> str:
    """A truncated file's text from its raw_url, only on gist.githubusercontent.com over https."""
    u = urlsplit(url or "")
    if u.scheme != "https" or u.hostname != RAW_HOST:
        raise ImportFailed(f"a gist file's raw URL isn't on {RAW_HOST}", 502)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bluedoc"}), timeout=TIMEOUT) as r:
            data = r.read(MAX_FILE + 1)
    except (urllib.error.URLError, OSError) as e:
        raise ImportFailed(f"couldn't read a gist file: {getattr(e, 'reason', e)}", 502) from None
    if len(data) > MAX_FILE:
        raise ImportFailed("a gist file is over 10 MB", 413)
    return data.decode("utf-8", "replace")


def gist_texts(data: dict) -> dict[str, str]:
    """{file name: text} of the gist's files, a truncated one read from its raw_url; the size caps apply."""
    files = data.get("files") or {}
    if len(files) > MAX_FILES:
        raise ImportFailed(f"the gist has {len(files)} files, over {MAX_FILES}", 413)
    out, total = {}, 0
    for name, f in files.items():
        if not isinstance(f, dict):
            continue
        text = _raw(f.get("raw_url")) if f.get("truncated") or not isinstance(f.get("content"), str) else f["content"]
        size = len(text.encode("utf-8"))
        if size > MAX_FILE:
            raise ImportFailed(f"{name} is over 10 MB", 413)
        total += size
        if total > MAX_TOTAL:
            raise ImportFailed("the gist is over 30 MB", 413)
        out[str(name)] = text
    return out


# ---------- the bundle: what a source gives ----------

def _rel(s) -> bool:
    return isinstance(s, str) and bool(s) and not s.startswith("data:") and not re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:|/", s)


def _media_pairs(doc, page, out: dict[str, str]) -> None:
    """{relative src: data: URI}: the doc's relative media srcs (media, compare sides, evidence) beside the page doc's
    inline data at the same place."""
    if isinstance(doc, list) and isinstance(page, list):
        for a, b in zip(doc, page):
            _media_pairs(a, b, out)
        return
    if not (isinstance(doc, dict) and isinstance(page, dict)):
        return
    pairs = [(doc.get("src"), page.get("src"))] if doc.get("type") == "media" else []
    if doc.get("type") == "compare":
        pairs += [((doc.get(s) or {}).get("src"), (page.get(s) or {}).get("src")) for s in ("before", "after")
                  if isinstance(doc.get(s), dict) and isinstance(page.get(s), dict)]
    if isinstance(doc.get("evidence"), list) and isinstance(page.get("evidence"), list):
        pairs += [(a.get("src"), b.get("src")) for a, b in zip(doc["evidence"], page["evidence"]) if isinstance(a, dict) and isinstance(b, dict)]
    for src, uri in pairs:
        if _rel(src) and isinstance(uri, str) and uri.startswith("data:"):
            out[src.split("?", 1)[0].split("#", 1)[0]] = uri
    for k, v in doc.items():
        if k in page:
            _media_pairs(v, page[k], out)


def _data_bytes(uri: str) -> bytes | None:
    m = re.match(r"data:[^;,]*;base64,(.*)", uri, re.S)
    if not m:
        return None
    try:
        return base64.b64decode(m[1], validate=True)
    except (binascii.Error, ValueError):
        return None


def _doc_of(text: str, name: str) -> dict:
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise ImportFailed(f"{name} isn't JSON: {e}") from None
    if not isinstance(doc, dict):
        raise ImportFailed(f"{name} isn't a JSON object")
    return doc


def bundle_of_gist(data: dict, texts: dict[str, str]) -> dict:
    """{stem, doc, files: {path from the doc's folder: bytes}, answers, by, rev, version, at, warnings} from a gist."""
    docs = [n for n in texts if n.endswith(".bluedoc.json") and "/" not in n]
    if len(docs) != 1 or share.PAGE_FILE not in texts:
        raise ImportFailed("this gist isn't a shared bluedoc doc: it needs one <name>.bluedoc.json and bluedoc-page.json", 422)
    name = docs[0]
    doc = _doc_of(texts[name], name)
    try:
        page = json.loads(texts[share.PAGE_FILE])
        fill = page["fill"]
        assert isinstance(fill, dict)
    except (ValueError, KeyError, AssertionError, TypeError):
        raise ImportFailed("bluedoc-page.json isn't one this bluedoc reads", 422) from None
    warnings: list[str] = []
    files: dict[str, bytes] = {}
    try:
        page_doc = json.loads(fill.get("__BLUEDOC_DOC__") or "null")
    except ValueError:
        page_doc = None
    pairs: dict[str, str] = {}
    _media_pairs(doc, page_doc, pairs)
    for src, uri in pairs.items():
        b = _data_bytes(uri)
        if b is not None:
            files[src] = b
    stem = name[:-len(".bluedoc.json")]
    screens = None
    if SCREENS_FILE in texts:
        try:
            screens = json.loads(texts[SCREENS_FILE])
        except ValueError:
            screens = None
        if not (isinstance(screens, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in screens.items())):
            raise ImportFailed(f"{SCREENS_FILE} isn't {{path: text}}", 422)
        files.update({k: v.encode("utf-8") for k, v in screens.items()})
    else:
        try:
            wrapped = json.loads(fill.get("__BLUEDOC_SCREENS__") or "null")
        except ValueError:
            wrapped = None
        if isinstance(wrapped, dict) and wrapped:
            arts = {a["id"]: a for a in build._artboards(doc)}
            for aid, html in wrapped.items():
                if aid in arts and isinstance(html, str):
                    files[build.screen_rel(Path(name), arts[aid])] = html.encode("utf-8")
            warnings.append("shared by an older bluedoc: the screens are the shared page's, with their kit inlined; "
                            "ask the sharer to share again for their source files")
    answers = None
    try:
        a = json.loads(fill.get(build.ANSWERS_SLOT) or "null")
        if isinstance(a, dict) and isinstance(a.get("state"), dict) and isinstance(a.get("by"), str):
            answers = a
    except ValueError:
        pass
    owner = (data.get("owner") or {}).get("login") if isinstance(data.get("owner"), dict) else None
    by = owner or (answers or {}).get("by") or "someone"
    return {"stem": stem, "doc": doc, "text": texts[name], "files": files, "answers": answers, "by": by,
            "rev": share.rev_of(doc), "version": str(page.get("version") or ""), "at": data.get("updated_at"),
            "warnings": warnings}


def bundle_of_zip(path: Path) -> dict:
    """The same from a Download → bluedoc file (.zip): one <name>.bluedoc.json at the top, its files at their paths,
    bluedoc-share.json ({by, link, version}) and bluedoc-answers.json (the sharer's answers slot) when the page had
    them. With the link, the copy pulls the sharer's updates like one imported from it."""
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise ImportFailed(f"{path.name} isn't a zip: {e}") from None
    with z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if len(infos) > MAX_FILES:
            raise ImportFailed(f"the zip has {len(infos)} files, over {MAX_FILES}", 413)
        if sum(i.file_size for i in infos) > MAX_TOTAL:
            raise ImportFailed("the zip is over 30 MB unpacked", 413)
        files: dict[str, bytes] = {}
        for i in infos:
            if i.file_size > MAX_FILE:
                raise ImportFailed(f"{i.filename} is over 10 MB", 413)
            data = z.read(i)
            if len(data) > MAX_FILE:
                raise ImportFailed(f"{i.filename} is over 10 MB", 413)
            files[i.filename] = data
    docs = [n for n in files if n.endswith(".bluedoc.json") and "/" not in n]
    if len(docs) != 1:
        raise ImportFailed(f"{path.name} isn't a bluedoc file: it needs one <name>.bluedoc.json at its top", 422)
    name = docs[0]
    text = files.pop(name).decode("utf-8", "replace")
    doc = _doc_of(text, name)
    answers = None
    if "bluedoc-answers.json" in files:
        try:
            a = json.loads(files.pop("bluedoc-answers.json"))
            answers = a if isinstance(a, dict) and isinstance(a.get("state"), dict) and isinstance(a.get("by"), str) else None
        except ValueError:
            pass
    origin = {}
    if "bluedoc-share.json" in files:
        try:
            o = json.loads(files.pop("bluedoc-share.json"))
            origin = o if isinstance(o, dict) else {}
        except ValueError:
            pass
    by = origin.get("by") if isinstance(origin.get("by"), str) and build.LOGIN.fullmatch(origin["by"]) else None
    out = {"stem": name[:-len(".bluedoc.json")], "doc": doc, "text": text, "files": files, "answers": answers,
           "by": by or (answers or {}).get("by") or "someone", "rev": share.rev_of(doc),
           "version": str(origin.get("version") or "")[:40], "at": None, "warnings": []}
    # the shared page's link: the copy can pull the sharer's updates as one imported from the link does
    try:
        s = parse_source(str(origin.get("link") or ""))
        out["gist"] = s["id"] if s["kind"] == "gist" else None
    except ImportFailed:
        out["gist"] = None
    return out


def load(src: str) -> dict:
    """The bundle a source gives, with {source: {kind, id?, link?, etag?, via?}}."""
    s = parse_source(src)
    if s["kind"] == "zip":
        b = bundle_of_zip(s["path"])
        gid = b.pop("gist")
        b["source"] = {"kind": "gist", "id": gid, "link": share.link_for(b["by"], gid), "etag": None, "via": "zip"} if gid else {"kind": "zip"}
        return b
    got = fetch(s["id"])
    b = bundle_of_gist(got["data"], gist_texts(got["data"]))
    b["source"] = {"kind": "gist", "id": s["id"], "link": share.link_for(b["by"], s["id"]), "etag": got["etag"], "via": got["via"]}
    return b


# ---------- checks and writing ----------

def safe_rel(p: str) -> str:
    """p as a clean relative POSIX path; ImportFailed for an absolute one, `..`, a backslash, NUL or an empty part."""
    if not isinstance(p, str) or not p or "\\" in p or "\x00" in p or p.startswith("/") or re.match(r"[A-Za-z]:", p):
        raise ImportFailed(f"refused a file path: {str(p)[:200]!r} isn't relative")
    parts = p.split("/")
    if any(x in ("", ".", "..") for x in parts):
        raise ImportFailed(f"refused a file path: {p[:200]!r} leaves the doc's folder or has an empty part")
    return str(PurePosixPath(*parts))


def inside(folder: Path, rel: str) -> Path:
    """folder/rel, refused when it resolves outside folder or passes through a symlink."""
    f = folder / rel
    cur = folder
    for part in PurePosixPath(rel).parts:
        cur = cur / part
        if cur.is_symlink():
            raise ImportFailed(f"refused {rel}: {cur.name} is a symlink")
    if folder.resolve() not in f.resolve().parents:
        raise ImportFailed(f"refused {rel}: it resolves outside {folder}")
    return f


def _bumped(rel: str, n: int) -> str:
    p = PurePosixPath(rel)
    return str(p.with_name(f"{p.stem}-{n}{p.suffix}"))


def _replace_strings(x, old: str, new: str):
    if isinstance(x, list):
        return [_replace_strings(v, old, new) for v in x]
    if isinstance(x, dict):
        return {k: _replace_strings(v, old, new) for k, v in x.items()}
    if isinstance(x, str) and (x == old or x.startswith(old + "?") or x.startswith(old + "#")):
        return new + x[len(old):]
    return x


def default_dir(doc: dict, cwd: Path | None = None) -> Path:
    """docs/plans/ for a plan, else docs/<type>/, under the repo cwd is in (git's top level), else under cwd."""
    cwd = (cwd or Path.cwd()).resolve()
    try:
        top = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
        root = Path(top.stdout.strip()) if top.returncode == 0 and top.stdout.strip() else cwd
    except (OSError, subprocess.TimeoutExpired):
        root = cwd
    t = build.doc_type(doc.get("meta") if isinstance(doc.get("meta"), dict) else {})
    return root / "docs" / ("plans" if t == "plan" else t)


def plan_write(b: dict, folder: Path) -> dict:
    """What writing b into folder means, nothing written: {path (the doc), doc (as it will be written), files: [(rel,
    bytes)] to write, same: [rel] already there with these bytes, warnings}. ImportFailed: a bad path, the caps, or a
    doc this bluedoc doesn't validate."""
    folder = Path(folder)
    if folder.exists() and not folder.is_dir():
        raise ImportFailed(f"{folder} isn't a folder")
    files = {safe_rel(k): v for k, v in b["files"].items()}
    if len(files) + 1 > MAX_FILES:
        raise ImportFailed(f"{len(files) + 1} files, over {MAX_FILES}", 413)
    total = len(b["text"].encode("utf-8"))
    for rel, data in files.items():
        if len(data) > MAX_FILE:
            raise ImportFailed(f"{rel} is over 10 MB", 413)
        total += len(data)
    if total > MAX_TOTAL:
        raise ImportFailed("over 30 MB in all", 413)
    stem = b["stem"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", stem):
        raise ImportFailed(f"refused the doc's name {stem[:120]!r}")
    # the doc's stem: <stem>.bluedoc.json and its <stem>.* folders must all be free
    new, n = stem, 1
    while (folder / f"{new}.bluedoc.json").exists() or any(folder.glob(f"{new}.*")):
        n += 1
        new = f"{stem}-{n}"
    doc = json.loads(json.dumps(b["doc"]))
    if new != stem:
        files = {(new + rel[len(stem):] if rel.startswith(stem + ".") else rel): v for rel, v in files.items()}
        for a in build._artboards(doc):
            if isinstance(a.get("src"), str) and a["src"].startswith(stem + "."):
                a["src"] = new + a["src"][len(stem):]
    out, same = [], []
    for rel in sorted(files):
        data, final, k = files[rel], rel, 1
        while True:
            f = inside(folder, final)
            if not f.exists():
                break
            if f.is_file() and f.read_bytes() == data:
                same.append(final)
                break
            k += 1
            final = _bumped(rel, k)
        if final != rel:
            doc = _replace_strings(doc, rel, final)
        if final not in same:
            out.append((final, data))
    path = inside(folder, f"{new}.bluedoc.json")
    rep = build.validate(doc, None)
    if rep.blocking:
        ver = f" (shared with bluedoc {b['version']}, newer than {build.skill_version()}: update bluedoc)" if b.get("version") and _older(build.skill_version() or "0", b["version"]) else ""
        raise ImportFailed(f"the doc doesn't validate{ver}: {rep.blocking[0]}", 422)
    return {"path": path, "doc": doc, "files": out, "same": same, "warnings": list(b.get("warnings") or [])}


def _older(a: str, b: str) -> bool:
    pa, pb = [int(x) if x.isdigit() else 0 for x in a.split(".")], [int(x) if x.isdigit() else 0 for x in b.split(".")]
    return pa < pb


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def write(b: dict, folder: Path) -> dict:
    """Check, then write b into folder: the files, then the doc with meta.copiedFrom, its history at the sharer's rev,
    and the copy's record. {path, files: [rel], same, warnings}."""
    plan = plan_write(b, folder)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for rel, data in plan["files"]:
        f = inside(folder, rel)
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "xb") as out:
            out.write(data)
        written.append(rel)
    doc = plan["doc"]
    meta = doc.setdefault("meta", {})
    meta["copiedFrom"] = {"by": b["by"], "rev": b["rev"], "at": now_iso()}
    path = plan["path"]
    with open(path, "x", encoding="utf-8") as out:
        out.write(build.dump_doc(doc))
    try:
        build.sync_history(path, doc)
    except build.HistoryError as e:
        plan["warnings"].append(str(e))
    src = b.get("source") or {}
    if src.get("kind") == "gist":
        record(path, {"id": src["id"], "user": b["by"], "link": src["link"], "etag": src.get("etag"), "rev": b["rev"],
                      "at": meta["copiedFrom"]["at"], "base": b["text"], "answers": b.get("answers"), "checked": time.time(),
                      "latest": None, "later": None, "review": []})
    elif b.get("answers"):
        record(path, {"id": None, "user": b["by"], "link": None, "etag": None, "rev": b["rev"], "at": meta["copiedFrom"]["at"],
                      "base": b["text"], "answers": b["answers"], "checked": None, "latest": None, "later": None, "review": []})
    return {"path": path, "files": [path.name, *written], "same": plan["same"], "warnings": plan["warnings"]}


def preview(b: dict, folder: Path) -> dict:
    """What the import page shows, nothing written: the doc's names, the files with sizes, the answers' counts."""
    plan = plan_write(b, folder)
    doc = b["doc"]
    counts = {}
    st = (b.get("answers") or {}).get("state") or {}
    counts["picks"] = sum(1 for k, v in st.items() if k.count(":") == 1 and not k.startswith("__") and str(v).startswith("="))
    counts["comments"] = sum(1 for k in st if k.endswith(":thread") or k.startswith("__ann:"))
    return {"by": b["by"], "title": build.shown_title(doc, None), "emoji": build.shown_emoji(doc, None),
            "type": build.doc_type(doc.get("meta") or {}), "rev": b["rev"], "at": b.get("at"), "version": b.get("version"),
            "name": plan["path"].name, "files": [{"path": plan["path"].name, "size": len(build.dump_doc(plan["doc"]).encode())},
                                                 *({"path": r, "size": len(d)} for r, d in plan["files"])],
            "same": plan["same"], "answers": counts if b.get("answers") else None, "warnings": plan["warnings"]}


# ---------- copies.json ----------

def copies_file() -> Path:
    return Path(os.environ.get("BLUEDOC_HOME") or "~/.bluedoc").expanduser() / "copies.json"


def _load() -> dict:
    try:
        data = json.loads(copies_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    f = copies_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    tmp.replace(f)


def record(path: Path, rec: dict) -> None:
    with LOCK:
        data = _load()
        data[str(Path(path).resolve())] = rec
        _save(data)


def copy_of(path: Path) -> dict | None:
    r = _load().get(str(Path(path).resolve()))
    return r if isinstance(r, dict) else None


def update(path: Path, **kw) -> dict | None:
    with LOCK:
        data = _load()
        r = data.get(str(Path(path).resolve()))
        if not isinstance(r, dict):
            return None
        r.update(kw)
        _save(data)
        return r


# ---------- updates ----------

def changed_parts(a: dict, b: dict) -> int:
    """How many parts differ between two docs: the head's fields (not meta), each section's own fields, and its blocks
    by position; a section added or gone counts once."""
    n = sum(1 for k in set(a) | set(b) if k not in ("sections", "meta", "changes", "resolves") and not _same(a.get(k), b.get(k)))
    sa = {s.get("id"): s for s in a.get("sections") or [] if isinstance(s, dict)}
    sb = {s.get("id"): s for s in b.get("sections") or [] if isinstance(s, dict)}
    for sid in set(sa) | set(sb):
        if sid not in sa or sid not in sb:
            n += 1
            continue
        x, y = sa[sid], sb[sid]
        n += sum(1 for k in set(x) | set(y) if k != "blocks" and not _same(x.get(k), y.get(k)))
        xb, yb = x.get("blocks") or [], y.get("blocks") or []
        n += sum(1 for i in range(max(len(xb), len(yb))) if not _same(xb[i] if i < len(xb) else None, yb[i] if i < len(yb) else None))
    return n


def status(path: Path, fresh: bool = False) -> dict | None:
    """The copy's upstream for its page: {by, rev, at, link?: false, newer: {rev, changed} | null, review, checked,
    error?}; checks the gist when CHECK_EVERY has passed (fresh: now). None for a doc that isn't a copy here."""
    r = copy_of(path)
    if r is None:
        return None
    err = None
    if r.get("id") and (fresh or time.time() - float(r.get("checked") or 0) >= CHECK_EVERY):
        try:
            got = fetch(r["id"], r.get("etag"))
            if got["status"] == 200:
                texts = gist_texts(got["data"])
                b = bundle_of_gist(got["data"], texts)
                latest = None if b["text"] == r.get("base") else {"rev": b["rev"], "doc": b["text"], "answers": b.get("answers")}
                r = update(path, etag=got["etag"], checked=time.time(), latest=latest) or r
            else:
                r = update(path, checked=time.time()) or r
        except ImportFailed as e:
            err = str(e)
            r = update(path, checked=time.time()) or r
    out = {"by": r.get("user"), "rev": r.get("rev"), "at": r.get("at"), "pullable": bool(r.get("id")), "newer": None,
           "review": [{k: v for k, v in x.items() if k != "theirs"} for x in r.get("review") or []], "checked": r.get("checked"),
           "answers": bool(r.get("answers"))}
    lt = r.get("latest")
    if isinstance(lt, dict) and lt.get("rev") != r.get("later"):
        try:
            out["newer"] = {"rev": lt.get("rev"), "changed": changed_parts(json.loads(r["base"]), json.loads(lt["doc"]))}
        except (ValueError, KeyError, TypeError):
            out["newer"] = {"rev": lt.get("rev"), "changed": None}
    if err:
        out["error"] = err
    return out


# ---------- the merge ----------

def _same(a, b) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _label(x, fallback: str) -> str:
    if isinstance(x, dict):
        for k in ("title", "text", "term", "label", "path", "id"):
            if isinstance(x.get(k), str) and x[k].strip():
                return x[k].strip()[:120]
    return fallback


MISSING = object()


class _Merge:
    def __init__(self) -> None:
        self.review: list[dict] = []

    def three(self, base, mine, theirs, path: list, label: str):
        """mine, theirs or (both changed) mine with a review entry; MISSING for a part gone."""
        if _same(mine, theirs) or _same(base, theirs):
            return mine
        if _same(base, mine):
            return theirs
        self.review.append({"id": f"r{len(self.review) + 1}", "label": label, "path": path,
                            "theirs": None if theirs is MISSING else theirs, "gone": theirs is MISSING})
        return mine

    def by_id(self, base: list, mine: list, theirs: list, path: list, what: str, deep=None) -> list:
        """Lists of objects with ids, merged by id: mine's order, theirs' new ones after their predecessor."""
        idx = lambda xs: {x.get("id"): x for x in xs if isinstance(x, dict) and x.get("id") is not None}  # noqa: E731
        B, M, T = idx(base), idx(mine), idx(theirs)
        order = [x.get("id") for x in mine if isinstance(x, dict)]
        for i, x in enumerate(theirs):
            xid = x.get("id") if isinstance(x, dict) else None
            if xid is None or xid in order or xid in B:
                continue
            prev = next((theirs[j].get("id") for j in range(i - 1, -1, -1) if isinstance(theirs[j], dict) and theirs[j].get("id") in order), None)
            order.insert(order.index(prev) + 1 if prev is not None else 0, xid)
        for xid in B:   # gone in mine: back only when theirs changed it (a conflict, under review)
            if xid not in M and xid in T and not _same(B[xid], T[xid]):
                self.review.append({"id": f"r{len(self.review) + 1}", "label": f"{what} {_label(T[xid], str(xid))} (you removed it)".strip(),
                                    "path": path + [xid], "theirs": T[xid], "gone": False})
        out = []
        for xid in order:
            b, m, t = B.get(xid, MISSING), M.get(xid, MISSING), T.get(xid, MISSING)
            if m is MISSING:
                if b is MISSING and t is not MISSING:
                    out.append(t)
                continue
            if t is MISSING and b is not MISSING:
                if _same(b, m):
                    continue   # theirs removed it, mine didn't touch it
                self.review.append({"id": f"r{len(self.review) + 1}", "label": f"{what} {_label(m, str(xid))} (the sharer removed it)".strip(),
                                    "path": path + [xid], "theirs": None, "gone": True})
                out.append(m)
                continue
            if b is MISSING or t is MISSING:
                out.append(m)
                continue
            out.append(deep(b, m, t, path + [xid]) if deep else self.three(b, m, t, path + [xid], f"{what} {_label(m, str(xid))}".strip()))
        return out

    def block(self, b: dict, m: dict, t: dict, path: list, where: str) -> dict:
        if (isinstance(b, dict) and isinstance(m, dict) and isinstance(t, dict) and b.get("type") == m.get("type") == t.get("type")
                and b.get("type") in ITEM_LISTS and all(isinstance(x.get("items"), list) for x in (b, m, t))
                and all(isinstance(i, dict) and isinstance(i.get("id"), str) for x in (b, m, t) for i in x["items"])):
            rest = {k for k in set(b) | set(m) | set(t) if k != "items"}
            out = {}
            for k in sorted(rest, key=lambda k: list(m).index(k) if k in m else 999):
                v = self.three(b.get(k, MISSING), m.get(k, MISSING), t.get(k, MISSING), path + ["@" + k], f"{where}: {_label(m, m.get('type', 'block'))}, {k}")
                if v is not MISSING:
                    out[k] = v
            out["items"] = self.by_id(b["items"], m["items"], t["items"], path + ["items"], f"{where}:")
            return {k: out[k] for k in [*m, *[k for k in out if k not in m]] if k in out}
        return self.three(b, m, t, path, f"{where}: {_label(m, str(m.get('type', 'block')) if isinstance(m, dict) else 'block')}")

    def section(self, b: dict, m: dict, t: dict, path: list) -> dict:
        where, out = _label(m, str(path[-1])), {}
        for k in [*m, *[k for k in t if k not in m]]:
            if k == "blocks":
                continue
            v = self.three(b.get(k, MISSING), m.get(k, MISSING), t.get(k, MISSING), path + ["@" + k], f"{where}: its {k}")
            if v is not MISSING:
                out[k] = v
        bb, mb, tb = b.get("blocks") or [], m.get("blocks") or [], t.get("blocks") or []
        if len(bb) == len(mb) == len(tb):
            out["blocks"] = [self.block(bb[i], mb[i], tb[i], path + ["blocks", i], where) for i in range(len(mb))]
        else:
            out["blocks"] = self.three(bb, mb, tb, path + ["@blocks"], f"{where}: its blocks")
        return {k: out[k] for k in [*m, *[k for k in out if k not in m]] if k in out}


HEAD_SKIP = ("sections", "changes", "resolves")
META_KEEP = ("rev", "date", "copiedFrom")


def merge3(base: dict, mine: dict, theirs: dict) -> tuple[dict, list[dict]]:
    """(the merged doc, the review list) of mine and theirs against base."""
    m = _Merge()
    out = {}
    for k in [*mine, *[k for k in theirs if k not in mine]]:
        if k in HEAD_SKIP:
            continue
        if k == "meta":
            bm, mm, tm = (x.get("meta") if isinstance(x.get("meta"), dict) else {} for x in (base, mine, theirs))
            meta = {}
            for mk in [*mm, *[k for k in tm if k not in mm]]:
                if mk in META_KEEP:
                    if mk in mm:
                        meta[mk] = mm[mk]
                    continue
                v = m.three(bm.get(mk, MISSING), mm.get(mk, MISSING), tm.get(mk, MISSING), ["meta", mk], f"meta.{mk}")
                if v is not MISSING:
                    meta[mk] = v
            out["meta"] = meta
            continue
        v = m.three(base.get(k, MISSING), mine.get(k, MISSING), theirs.get(k, MISSING), ["head", k], k)
        if v is not MISSING:
            out[k] = v
    out["sections"] = m.by_id(base.get("sections") or [], mine.get("sections") or [], theirs.get("sections") or [],
                              ["sections"], "section", deep=m.section)
    return out, m.review


def _next_rev(rev) -> str:
    s = str(rev or "")
    m = re.fullmatch(r"(.*?)(\d+)", s)
    return f"{m[1]}{int(m[2]) + 1}" if m else (s + ".1" if s else "2")


def pull(path: Path) -> dict:
    """Merge the sharer's newest rev into the copy as a new rev; {rev, review, written}. The gist is read again."""
    path = Path(path).resolve()
    r = copy_of(path)
    if not r or not r.get("id"):
        raise ImportFailed("this doc isn't a copy of a shared link on this machine", 404)
    got = fetch(r["id"])
    b = bundle_of_gist(got["data"], gist_texts(got["data"]))
    try:
        mine = json.loads(path.read_text(encoding="utf-8"))
        base = json.loads(r["base"])
    except (OSError, ValueError, KeyError) as e:
        raise ImportFailed(f"cannot read the copy: {e}", 500) from None
    merged, review = merge3(base, mine, b["doc"])
    meta = merged.setdefault("meta", {})
    meta["rev"] = _next_rev((mine.get("meta") or {}).get("rev"))
    meta["date"] = dt.date.today().isoformat()
    meta["copiedFrom"] = {**(meta.get("copiedFrom") or {}), "by": b["by"], "rev": b["rev"]}
    merged["changes"] = [f"Pulled {b['by']}'s rev {b['rev'] or '–'}"]
    merged.pop("resolves", None)
    rep = build.validate(merged, path)
    if rep.blocking:
        raise ImportFailed(f"the merged doc doesn't validate: {rep.blocking[0]}", 422)
    # the sharer's new files: written where nothing is yet; one already there stays as it is
    folder, written = path.parent, []
    for rel, data in b["files"].items():
        try:
            f = inside(folder, safe_rel(rel))
        except ImportFailed:
            continue
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            with open(f, "xb") as out:
                out.write(data)
            written.append(rel)
    build.write_doc(path, merged)
    build.sync_history(path, merged)
    update(path, base=b["text"], rev=b["rev"], etag=got["etag"], checked=time.time(), latest=None, later=None,
           review=review, answers=b.get("answers") or r.get("answers"))
    return {"rev": meta["rev"], "review": [{k: v for k, v in x.items() if k != "theirs"} for x in review], "written": written}


def _set_at(doc: dict, path: list, value) -> None:
    """Put value (None: remove) at a review path in doc."""
    if path[0] == "head":
        if value is None:
            doc.pop(path[1], None)
        else:
            doc[path[1]] = value
        return
    if path[0] == "meta":
        doc.setdefault("meta", {})[path[1]] = value
        return
    cur = doc
    i = 0
    while i < len(path):
        k = path[i]
        if k in ("sections", "items"):
            lst = cur.setdefault(k, [])
            xid = path[i + 1]
            pos = next((j for j, x in enumerate(lst) if isinstance(x, dict) and x.get("id") == xid), None)
            if i + 1 == len(path) - 1:
                if value is None:
                    if pos is not None:
                        lst.pop(pos)
                elif pos is None:
                    lst.append(value)
                else:
                    lst[pos] = value
                return
            cur = lst[pos]
            i += 2
            continue
        if k == "blocks":
            j = path[i + 1]
            if i + 1 == len(path) - 1:
                cur["blocks"][j] = value
                return
            cur = cur["blocks"][j]
            i += 2
            continue
        if isinstance(k, str) and k.startswith("@"):
            if value is None:
                cur.pop(k[1:], None)
            else:
                cur[k[1:]] = value
            return
        raise ImportFailed("a review entry's place isn't in the doc any more", 409)


def take_theirs(path: Path, rid: str) -> dict:
    """Review's Take theirs: the sharer's version of that part into the copy (its current rev), the entry gone."""
    path = Path(path).resolve()
    r = copy_of(path)
    entry = next((x for x in (r or {}).get("review") or [] if x.get("id") == rid), None)
    if entry is None:
        raise ImportFailed("no such review entry", 404)
    doc = json.loads(path.read_text(encoding="utf-8"))
    try:
        _set_at(doc, entry["path"], None if entry.get("gone") else entry.get("theirs"))
    except (KeyError, IndexError, TypeError):
        raise ImportFailed("that part isn't in the doc any more", 409) from None
    rep = build.validate(doc, path)
    if rep.blocking:
        raise ImportFailed(f"the doc wouldn't validate: {rep.blocking[0]}", 422)
    build.write_doc(path, doc)
    build.sync_history(path, doc)
    left = [x for x in r["review"] if x.get("id") != rid]
    update(path, review=left)
    return {"review": [{k: v for k, v in x.items() if k != "theirs"} for x in left]}


def theirs_doc(path: Path) -> dict | None:
    """The sharer's newer rev the check found, for Compare; None without one."""
    r = copy_of(path)
    lt = (r or {}).get("latest")
    try:
        return json.loads(lt["doc"]) if isinstance(lt, dict) else None
    except (ValueError, KeyError, TypeError):
        return None


def answer_ops(path: Path) -> list[tuple[str, str]]:
    """Use these answers: the sharer's picks, Other, Tell me more and ticks, as reader-state writes (key without the
    bp:<id>: prefix, value). Comments stay theirs."""
    a = (copy_of(path) or {}).get("answers") or {}
    st = a.get("state") if isinstance(a, dict) else None
    if not isinstance(st, dict):
        return []
    out = []
    for k, v in st.items():
        if not isinstance(v, str) or k.startswith("__"):
            continue
        parts = k.split(":")
        if len(parts) == 2 or len(parts) == 3 and parts[2] in ("custom", "more"):
            out.append((k, v))
    return out
