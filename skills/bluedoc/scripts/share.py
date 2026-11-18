#!/usr/bin/env python3
"""Share a doc as a secret GitHub gist, opened at https://bluedoc.ai/g/<code> (link_for; serve.py share/unshare,
GET/POST /__bluedoc/share and POST /__bluedoc/unshare).

A share holds the doc's current revision only, in two or three text files:
  <stem>.bluedoc.json           the doc, verbatim
  bluedoc-page.json             what the bluedoc.ai viewer fills the template with:
      {"bluedoc": "share/1", "version": <bluedoc version>, "name": <stem>, "title": <shown title>, "rev": <meta.rev or
       null>, "boardGeo": <whether the page needs assets/board-geo.js at /*__BOARD_GEO__*/>,
       "fill": {placeholder: text}}: exactly what build.py -o substitutes for the doc without its history
      (build.standalone_fill: diffs expanded, media and screens inline, no earlier revisions) but the board-geo slot,
      which the viewer fills from its own copy, and the answers slot (__BLUEDOC_ANSWERS__, answers_slot): the
      reader's answers the share carries, {by: the share's login, at, rev, state: {reader state key: value}}, or
      null. The shared page shows them read-only as <by>'s.
  bluedoc-screens.json          a doc with screen files (a design's screens, icon layers): {path from the doc's
      folder: the file's text} (screens_file), so `serve.py import` writes their sources back; none without them
A bluedoc-page.json or bluedoc-screens.json over MAX_PAGE_BYTES (10 MB) is refused (413): Export → HTML file sends the doc instead.

Answers (answers_of): by kind, ANSWER_KINDS: picks (a question's pick, Other's words, Tell me more), ticks (done
marks), comments (item threads, and the pins, regions and general comment that are sent, with their threads), pending
(saved comments not sent, drafts, the Send answers message) and images (attachments that are images, inlined as data:
URIs within IMAGES_MAX in all). DEFAULT_ANSWERS (picks, ticks, comments) go until the reader picks; the pick is the
doc's reader state ANSWERS_KEY (`__share-answers`, the Share sheet's switches, `serve.py share --answers/--no-answers`).
No attachment keeps its path: an image that doesn't go, and every other file, is {name, size} ("not shared").

Accounts: the github.com accounts `gh auth status` lists (accounts). One is usable when its token has the gist scope
(or is fine-grained); one without shows its fix, `gh auth refresh -s gist -u <login>`. Sharing is off (sharing_state)
when gh is missing, signed out, or has no usable account. Each project (a folder on the home page) shares as one
account, kept in settings.json's shareAs by the folder's path (project_account). Without one, a share preselects
(choose): the only usable account; the doc's gist's account; the account that is the project's GitHub remote's owner
or a member of the owner's org (`gh api user/memberships/orgs/<owner>` as each account, cached); else gh's active one.

Every gh call that writes or deletes a gist runs as one account: GH_TOKEN=$(gh auth token -u <login>) for that call
only, so gh's active account never changes. Writes go through `gh api -i`, so GitHub's status and headers are read on
refused ones too, one at a time and at least WRITE_GAP apart. The first share runs `gh api -i -X POST gists` (secret,
described `bluedoc: <title>`); a later one `gh api -i -X PATCH gists/<id>` with every file (files it no longer has set
to null), as the account the gist is on, so the link stays; a gist gone from GitHub is created anew. When the project
now shares as another account than the gist's, a share is refused (409, Mismatch) until it says move (a new gist on
the project's account, the old one deleted as its own: the link changes) or keep (updated as the gist's account: the
link stays; recorded as kept, so later shares update it there until the project's account changes again). unshare
runs `gh api -i -X DELETE gists/<id>` as the gist's account and forgets the share, also when the gist is gone.

The budget (gistbudget.py): GitHub allows about 100 gist updates an hour per account; bluedoc sends at most 90, one a
minute per doc. A create or update that doesn't fit, or that GitHub refuses for its rate limit (a 403 or 429 naming
it, retry-after, x-ratelimit-remaining: 0), waits: the doc's shares.json entry is marked `queued` and serve.py's queue
sends it when it is due, with the doc as it is then. A share while one waits makes no gh call. GitHub's retry time
wins; 4 refusals in a row pause the account until the reader resumes (resume). Deletes are counted but never wait.

Shares are recorded in $BLUEDOC_HOME/shares.json (mode 0600), keyed by the doc's resolved path: {id, user (the account
the gist is on), link, url, rev, at, files, answers (the kinds it carries), answersHash, kept? (the project account it
was kept from), queued? (an update that waits), error? (why the queue couldn't send it)}. Never in the doc or its
folder, so a committed doc doesn't carry its link.

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
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import build  # noqa: E402
import codepin  # noqa: E402
import gistbudget  # noqa: E402
import settings  # noqa: E402

FORMAT = "share/1"
PAGE_FILE = "bluedoc-page.json"
SCREENS_FILE = "bluedoc-screens.json"   # a design's screen sources, for a copy (screens_file)
MAX_PAGE_BYTES = 10 * 1024 * 1024   # a gist file's raw limit
VIEWER = "https://bluedoc.ai/g/"
# the notice every share shows (template.html's share sheet says the same; tests/test_share_sheet.py holds them equal)
NOTICE_LEAD = "bluedoc isn't responsible for this share method or for secrets leaked through GitHub gists."
NOTICE_REST = ("A secret gist is unlisted and not searchable, but anyone with the link can read it. "
               "Check the doc for secrets before you share.")
NOTICE = f"{NOTICE_LEAD} {NOTICE_REST}"
# a doc type whose page isn't the one -o writes: it has exports of its own (serve.py EXPORT_OWN)
NOT_SHARED = {"presentation": "a presentation isn't shared as a gist: export it from its board's Export to…",
              "storelisting": "a storelisting isn't shared as a gist: export it from its Export to…"}
GH_TIMEOUT = 180
LOCK = threading.Lock()   # one share or unshare at a time in this process: they read and write shares.json
LOGIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
ACCOUNTS_TTL = 60.0     # how old an accounts(fresh=False) answer may be (the Share key's state on each page load)
MEMBER_TTL = 3600.0     # how long an account's membership of a remote's owner is kept
_CACHE = threading.Lock()
_accounts_seen: tuple[float, list[dict]] | None = None
_members: dict[tuple[str, str], tuple[float, bool]] = {}


class ShareError(Exception):
    """Why a share or unshare didn't happen; status is the HTTP status the routes answer with."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


class Mismatch(ShareError):
    """The doc's gist is on another account than the one its project shares as: the share needs move or keep."""

    def __init__(self, gist: str, project: str) -> None:
        super().__init__(f"the gist is on {gist} and this project shares as {project}: move it to {project} (a new "
                         f"gist, so a new link) or keep it on {gist} (the link stays)", 409)
        self.mismatch = {"gist": gist, "project": project}


def same(a: str | None, b: str | None) -> bool:
    """Whether two GitHub logins name one account (GitHub ignores case)."""
    return bool(a) and bool(b) and a.lower() == b.lower()


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
    """The doc's share ({id, user, link, url, rev, at, files, answers?, answersHash?, kept?}), or None when it isn't
    shared (a first share still queued isn't). user is the account the gist is on (a share made before accounts were
    picked: gh's active account then). Its link is link_for's now, so a share recorded with an older link form shows
    the current one. Its queued update and error are view's, not the record's."""
    r = _load().get(str(Path(doc_path).resolve()))
    if not (isinstance(r, dict) and isinstance(r.get("id"), str)):
        return None
    return {**{k: v for k, v in r.items() if k not in ("queued", "error")}, "link": link_for(str(r.get("user") or ""), r["id"])}


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


def rev_of(doc: dict) -> str | None:
    rev = (doc.get("meta") or {}).get("rev")
    return str(rev) if rev not in (None, "") else None


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


def contents(doc: dict) -> dict:
    """What goes in, for the sheet: {media (files inlined), screens (a board's artboards with a screen file)}."""
    return {"media": len(_media_srcs(doc, set())),
            "screens": len([a for a in build._artboards(doc) if not build.is_live(a)])}


def bundle(doc: dict, doc_path: Path, answers: dict | None = None) -> dict:
    """bluedoc-page.json's object: build.standalone_fill's values for the doc alone (no history), with the board-geo
    slot as boardGeo, and the reader's answers (answers_slot) at __BLUEDOC_ANSWERS__ (null without)."""
    fill = build.standalone_fill(doc, Path(doc_path), None, problems=[])
    geo = fill.pop(build.BOARD_GEO_SLOT)
    fill[build.ANSWERS_SLOT] = build._script_json(answers) if answers else "null"
    return {"bluedoc": FORMAT, "version": build.skill_version() or "unknown", "name": build.doc_stem(Path(doc_path)),
            "title": build.shown_title(doc, None), "rev": rev_of(doc), "boardGeo": bool(geo), "fill": fill}


def gist_files(doc_path: Path, answers: dict | None = None) -> tuple[dict[str, str], dict, dict]:
    """({file name: text} for the gist, the doc, contents()). answers: the answers slot (answers_slot), or None.
    ShareError: an unreadable doc, a deck or a listing (400), a bluedoc-page.json over MAX_PAGE_BYTES (413)."""
    doc_path = Path(doc_path).resolve()
    text, doc = read_doc(doc_path)
    page = json.dumps(bundle(doc, doc_path, answers), ensure_ascii=False, separators=(",", ":")) + "\n"
    size = len(page.encode("utf-8"))
    if size > MAX_PAGE_BYTES:
        raise ShareError(f"the shared page would be {size / 1048576:.1f} MB, over the 10 MB a gist file can hold: "
                         "send Export → HTML file instead", 413)
    files = {gist_name(doc_path): text, PAGE_FILE: page}
    screens = screens_file(doc, doc_path)
    if screens is not None:
        size = len(screens.encode("utf-8"))
        if size > MAX_PAGE_BYTES:
            raise ShareError(f"the screens' sources would be {size / 1048576:.1f} MB, over the 10 MB a gist file can hold: "
                             "send Export → HTML file instead", 413)
        files[SCREENS_FILE] = screens
    return files, doc, contents(doc)


def screens_file(doc: dict, doc_path: Path) -> str | None:
    """bluedoc-screens.json's text, {path from the doc's folder: the file's text} for each screen file and icon layer
    (build.screen_paths) that reads as text, so a copy (importer.py) gets their sources back; None without any."""
    folder, out = Path(doc_path).parent, {}
    for f in build.screen_paths(doc, doc_path).values():
        text = build._read_text(f)
        try:
            rel = f.resolve().relative_to(folder.resolve()).as_posix()
        except ValueError:
            continue
        if text is not None:
            out[rel] = text
    return json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" if out else None


# ---------- the reader's answers ----------
# What a share carries of the reader's state.db rows on the doc (answers_of), by kind, each a switch in the Share sheet
# (Include my answers), remembered per doc in reader state as ANSWERS_KEY (the kinds comma-joined, "" for none):
#   picks     a question's pick (`<checklist>:<item>` =…), Other's words (`:custom`) and Tell me more (`:more`)
#   ticks     a progress item's tick (`<checklist>:<item>` 1… or 0…)
#   comments  the messages sent: an item's `:thread`, and the pins, text notes, drawings, regions and general comments
#             (`__ann:<id>`) that are Open or Resolved, with their `thread`
#   pending   what is saved and not sent: `:note`, `:notes`, `:files`, `__message`, `__message-files`, Pending comments
#             and a sent comment's follow-up draft (`draft`, `draftFiles`)
#   images    the attached images (PNG, JPEG, GIF, WebP) of what the other kinds carry, as data: URIs, at most
#             IMAGES_MAX bytes in all
# Every attachment loses its path: {name, size}, plus src (a data: URI) for an image that goes; the page says "N files
# not shared" for the rest. Nothing else of the reader goes: not the title, emoji, archive, plan state, undo history or
# a board's drafts. Picks, ticks and sent comments go by default.
ANSWER_KINDS = ("picks", "ticks", "comments", "pending", "images")
DEFAULT_ANSWERS = ("picks", "ticks", "comments")
ANSWERS_KEY = "__share-answers"
IMAGES_MAX = 1_500_000
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
ANN_SENT_TYPES = ("pin", "text", "draw", "region", "general")   # the comments a shared page shows (not a board's drafts)


def parse_kinds(value) -> list[str] | None:
    """A list of kinds, or their comma-joined string ("" none), in ANSWER_KINDS' order; None when it names another."""
    if isinstance(value, str):
        value = [k.strip() for k in value.split(",") if k.strip()]
    if not isinstance(value, list) or not all(isinstance(k, str) and k in ANSWER_KINDS for k in value):
        return None
    return [k for k in ANSWER_KINDS if k in value]


def kinds_of(state: dict | None) -> list[str]:
    """The kinds the doc's reader state remembers (ANSWERS_KEY), else DEFAULT_ANSWERS."""
    got = parse_kinds((state or {}).get(ANSWERS_KEY)) if isinstance((state or {}).get(ANSWERS_KEY), str) else None
    return list(DEFAULT_ANSWERS) if got is None else got


def _is_file(f) -> bool:
    return isinstance(f, dict) and isinstance(f.get("name"), str) and isinstance(f.get("size"), int)


def answers_of(state: dict | None, doc: dict, kinds, embed: bool = False) -> dict:
    """What a share carries of the reader's state (the kinds above): {state: {key: value as a string}, counts: {kind:
    how many of it the doc has}, notShared: attachments that don't go, hash: of what goes}. embed: images as data:
    URIs (read from their paths); without, an image that would go is {name, size, src: ""}, which is what the hash
    covers (with its path), so the hash says whether the answers changed without reading a file."""
    kinds = set(parse_kinds(list(kinds)) or [])
    items = {f"{b.get('id')}:{it.get('id')}": bool(it.get("choices"))
             for b in build.all_blocks(doc) if b.get("type") == "checklist" for it in b.get("items") or [] if isinstance(it, dict)}
    counts = dict.fromkeys(ANSWER_KINDS, 0)
    room, not_shared, seen, picked = [IMAGES_MAX], [0], [], set()

    def files(lst) -> list[dict]:
        """Attachments as they go: no path; an image's data (images on, room left), else counted as not shared."""
        out = []
        for f in lst if isinstance(lst, list) else []:
            if not _is_file(f):
                continue
            path = str(f.get("path") or "")
            mime = IMAGE_TYPES.get(Path(path or f["name"]).suffix.lower())
            g = {"name": f["name"][:255], "size": f["size"]}
            if mime and path:
                seen.append((path, f["size"]))
            if mime and path and "images" in kinds and 0 <= f["size"] <= room[0]:
                data = None
                if embed:
                    try:
                        raw = Path(path).read_bytes()
                        data = raw if len(raw) <= room[0] else None
                    except OSError:
                        data = None
                if data is not None or not embed:
                    room[0] -= len(data) if data is not None else f["size"]
                    g["src"] = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}" if data is not None else ""
            if "src" not in g:
                not_shared[0] += 1
            out.append(g)
        return out

    def thread(lst) -> list[dict]:
        out = []
        for m in lst if isinstance(lst, list) else []:
            if isinstance(m, dict) and isinstance(m.get("md"), str):
                m = {k: m[k] for k in ("md", "rev", "at", "about") if k in m} | ({"files": files(m["files"])} if m.get("files") else {})
                out.append(m)
        return out

    out: dict[str, str] = {}
    for key in sorted(state or {}):
        value = (state or {})[key]
        if not isinstance(value, str):
            continue
        if key.startswith("__ann:"):
            try:
                a = json.loads(value)
            except ValueError:
                continue
            if not (isinstance(a, dict) and a.get("type") in ANN_SENT_TYPES and isinstance(a.get("target"), dict)):
                continue
            status = a.get("status") if a.get("status") in ("pending", "open", "resolved") else "open" if a.get("sent") else "pending"
            draft = isinstance(a.get("draft"), str) and bool(a["draft"].strip()) or bool(a.get("draftFiles"))
            if status == "pending":
                counts["pending"] += 1
                if "pending" not in kinds:
                    continue
            else:
                counts["comments"] += 1 + len(a.get("thread") or [])
                counts["pending"] += draft
                if "comments" not in kinds:
                    continue
            keep = {k: a[k] for k in ("id", "type", "target", "targets", "quote", "note", "status", "rev", "at", "sentAt",
                                      "resolvedBy", "resolvedRev", "color") if k in a}
            keep["thread"] = thread(a.get("thread"))
            if a.get("files"):
                keep["files"] = files(a["files"])
            if status != "pending" and draft and "pending" in kinds:
                keep["draft"] = a.get("draft") or ""
                if a.get("draftFiles"):
                    keep["draftFiles"] = files(a["draftFiles"])
            out[key] = json.dumps(keep, ensure_ascii=False, separators=(",", ":"))
            continue
        if key in ("__message", "__message-files"):
            counts["pending"] += key == "__message" and bool(value.strip())
            if "pending" in kinds:
                if key == "__message":
                    out[key] = value
                else:
                    try:
                        out[key] = json.dumps(files(json.loads(value)), ensure_ascii=False, separators=(",", ":"))
                    except ValueError:
                        pass
            continue
        parts = key.split(":")
        base = ":".join(parts[:2])
        if key.startswith("__") or len(parts) not in (2, 3) or base not in items:
            continue
        card = items[base]
        if len(parts) == 2:
            # a pick; a tick (1…; an untick of the author's done, 0…, says nothing on a shared page)
            if card and value.startswith("="):
                picked.add(base)
                if "picks" in kinds:
                    out[key] = value
            elif not card and value.startswith("1"):
                counts["ticks"] += 1
                if "ticks" in kinds:
                    out[key] = value
            continue
        what = parts[2]
        if card and what in ("custom", "more") and value.strip():
            picked.add(base)
            if "picks" in kinds:
                out[key] = value
        elif what == "thread":
            try:
                msgs = thread(json.loads(value))
            except ValueError:
                continue
            counts["comments"] += len(msgs)
            if "comments" in kinds and msgs:
                out[key] = json.dumps(msgs, ensure_ascii=False, separators=(",", ":"))
        elif what in ("note", "notes", "files"):
            counts["pending"] += what != "files"
            if "pending" not in kinds:
                continue
            if what == "note":
                out[key] = value
                continue
            try:
                v = json.loads(value)
            except ValueError:
                continue
            if what == "files":
                out[key] = json.dumps(files(v), ensure_ascii=False, separators=(",", ":"))
            elif isinstance(v, dict):
                out[key] = json.dumps({k: {"md": e.get("md", ""), **({"files": files(e["files"])} if e.get("files") else {})}
                                       for k, e in v.items() if isinstance(e, dict)}, ensure_ascii=False, separators=(",", ":"))
    counts["picks"], counts["images"] = len(picked), len({p for p, _ in seen})
    digest = hashlib.sha256(json.dumps([out if not embed else None, sorted(seen) if "images" in kinds else []],
                                       sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return {"state": out, "counts": counts, "notShared": not_shared[0], "hash": None if embed else digest}


def answers_slot(state: dict | None, doc: dict, kinds, by: str) -> tuple[dict | None, str]:
    """(__BLUEDOC_ANSWERS__'s object {by: the share's login, at, rev, state}, or None when nothing goes; the answers'
    hash, answers_of's)."""
    h = answers_of(state, doc, kinds)["hash"]
    a = answers_of(state, doc, kinds, embed=True)
    if not a["state"]:
        return None, h
    return {"by": by, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "rev": rev_of(doc), "state": a["state"]}, h


# ---------- gh ----------

GH_MISSING = "gh, the GitHub CLI, isn't installed"


def gh(*args: str, stdin: str | None = None, cwd: Path | None = None, both: bool = False, token: str | None = None) -> str:
    """Run gh with args, as the account token is for (GH_TOKEN for this call only; None: gh's own choice); its stdout
    (both: stdout then stderr, as `gh auth status` writes to either). gh is the program env BLUEDOC_GH names (a path
    or a name on PATH), else `gh` on PATH. ShareError: gh is missing (501), or failed (GhFailed, 502, with what it
    said)."""
    exe = shutil.which(os.environ.get("BLUEDOC_GH") or "gh")
    if not exe:
        raise ShareError(f"{GH_MISSING}: run `brew install gh` (or see https://cli.github.com), then "
                         "`gh auth login -s gist`", 501)
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1", "GH_SPINNER_DISABLED": "1"}
    if token:
        env["GH_TOKEN"] = token
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
    """gh ran and failed: what it said (said: stdout then stderr; out: stdout alone), whether GitHub answered 404 (the
    gist is gone), and with `gh api -i` the HTTP status and response headers (lower-case names; else None and {})."""

    def __init__(self, args, out: str, err: str, status: int | None = None, headers: dict | None = None) -> None:
        said = (err.strip() or out.strip()).splitlines()
        super().__init__(f"gh {' '.join([a for a in args if a != '-i'][:2])} failed: {said[-1] if said else 'no message'}")
        self.said, self.out, self.err = out + err, out, err
        self.http, self.headers = status, headers or {}
        self.not_found = status == 404 or bool(re.search(r"HTTP 404|Not Found", err + out))


class RateLimited(GhFailed):
    """GitHub refused a gist write for its rate limit (gistbudget.rate_limited): the share waits; it isn't an error."""


HTTP_LINE = re.compile(r"HTTP/[\d.]+ (\d{3})")


def parse_http(out: str) -> tuple[int | None, dict, str]:
    """`gh api -i`'s stdout as (status, {header name in lower case: value}, body); (None, {}, out) without a status
    line."""
    m = HTTP_LINE.match(out)
    if not m:
        return None, {}, out
    head, _, body = out.replace("\r\n", "\n").partition("\n\n")
    headers = {}
    for line in head.split("\n")[1:]:
        k, colon, v = line.partition(":")
        if colon:
            headers[k.strip().lower()] = v.strip()
    return int(m.group(1)), headers, body


def gh_api(*args: str, stdin: str | None = None, token: str | None = None) -> tuple[int | None, dict, str]:
    """`gh api -i <args>`, a gist write: (status, headers, body). Every answer is read, refused ones too: a rate-limit
    refusal raises RateLimited, any other failure GhFailed with its status and headers."""
    try:
        return parse_http(gh("api", "-i", *args, stdin=stdin, token=token))
    except GhFailed as e:
        status, headers, body = parse_http(e.out)
        cls = RateLimited if gistbudget.rate_limited(status, headers, body) else GhFailed
        raise cls(("api", *args), e.out, e.err, status, headers) from None


def parse_status(text: str) -> list[dict]:
    """`gh auth status`'s github.com accounts in its order: [{login, usable, active, fix}]. gh 2.40+ writes a block
    per account ("✓ Logged in to github.com account <login> (…)" or "X Failed to log in to github.com account <login>",
    "- Active account: true|false", "- Token: …", "- Token scopes: …"); older ones one "Logged in to github.com as
    <login>" block. A classic token lists its scopes and is usable with gist; a fine-grained one (github_pat_…) lists
    none, its permissions are GitHub's to check."""
    blocks: list[dict] = []
    for line in text.splitlines():
        m = re.search(r"(Logged in to|Failed to log in to) (\S+) (?:account|as) ([A-Za-z0-9-]+)", line)
        if m:
            blocks.append({"ok": m.group(1) == "Logged in to", "host": m.group(2), "login": m.group(3), "lines": []})
        elif blocks:
            blocks[-1]["lines"].append(line)
    out: list[dict] = []
    for b in blocks:
        if b["host"] != "github.com" or any(same(a["login"], b["login"]) for a in out):
            continue
        body = "\n".join(b["lines"])
        sm = re.search(r"Token scopes:\s*(.*)", body)
        scoped = sm is None or bool(re.search(r"Token:\s*github_pat_", body)) or "gist" in re.findall(r"[\w:]+", sm.group(1))
        usable = b["ok"] and scoped
        out.append({"login": b["login"], "usable": usable, "active": bool(re.search(r"Active account:\s*true", body)),
                    "fix": None if usable else f"gh auth refresh -s gist -u {b['login']}"})
    if out and not any(a["active"] for a in out):
        out[0]["active"] = True   # an older gh: its one account
    return out


def accounts(fresh: bool = True) -> list[dict]:
    """The github.com accounts gh is signed in to (parse_status), [] when signed out. fresh=False takes an answer up to
    ACCOUNTS_TTL old (the Share key's state on each page load). ShareError: gh is missing (501) or doesn't answer."""
    global _accounts_seen
    with _CACHE:
        if not fresh and _accounts_seen and time.monotonic() - _accounts_seen[0] < ACCOUNTS_TTL:
            return [dict(a) for a in _accounts_seen[1]]
    try:
        text = gh("auth", "status", "--hostname", "github.com", both=True)
    except GhFailed as e:
        text = e.said   # gh exits 1 when any account has a problem, and when none is signed in
    found = parse_status(text)
    with _CACHE:
        _accounts_seen = (time.monotonic(), found)
    return [dict(a) for a in found]


def sharing_state(fresh: bool = True) -> tuple[list[dict], dict | None]:
    """(accounts, off): off is None when an account can share, else {reason, fix: the command that turns it on}."""
    try:
        accts = accounts(fresh)
    except ShareError as e:
        if e.status == 501:
            return [], {"reason": GH_MISSING, "fix": "brew install gh"}
        return [], {"reason": str(e), "fix": "gh auth status"}
    if not accts:
        return [], {"reason": "gh, the GitHub CLI, isn't signed in to GitHub", "fix": "gh auth login -s gist"}
    if not any(a["usable"] for a in accts):
        first = next((a for a in accts if a["active"]), accts[0])
        reason = (f"gh's GitHub account {first['login']} lacks the gist scope" if len(accts) == 1
                  else "none of gh's GitHub accounts has the gist scope")
        return accts, {"reason": reason, "fix": first["fix"]}
    return accts, None


def off_error(off: dict) -> ShareError:
    if off["reason"] == GH_MISSING:
        return ShareError(f"{GH_MISSING}: run `brew install gh` (or see https://cli.github.com), then "
                          "`gh auth login -s gist`", 501)
    return ShareError(f"{off['reason']}: run `{off['fix']}`")


def token_for(login: str) -> str:
    """The login's token from gh's store (`gh auth token -u`), for one call's GH_TOKEN; never logged or returned.
    ShareError when gh isn't signed in as login."""
    try:
        token = gh("auth", "token", "--hostname", "github.com", "--user", login).strip()
    except GhFailed as e:
        raise ShareError(f"gh isn't signed in as {login}: run `gh auth login -s gist` and sign in as {login}") from e
    if not token:
        raise ShareError(f"gh has no token for {login}: run `gh auth login -s gist` and sign in as {login}")
    return token


def member(login: str, owner: str) -> bool:
    """Whether login is the GitHub owner owner or an active member of that org, as login's token sees it
    (`gh api user/memberships/orgs/<owner>`); kept MEMBER_TTL. Any failure is no."""
    if same(login, owner):
        return True
    key = (login.lower(), owner.lower())
    with _CACHE:
        hit = _members.get(key)
        if hit and time.monotonic() - hit[0] < MEMBER_TTL:
            return hit[1]
    try:
        yes = gh("api", f"user/memberships/orgs/{owner}", "--jq", ".state", token=token_for(login)).strip() == "active"
    except ShareError:
        yes = False
    with _CACHE:
        _members[key] = (time.monotonic(), yes)
    return yes


# ---------- projects ----------

def remote_of(project: Path | None) -> str | None:
    """The project folder's GitHub repo as owner/name, from its git remote (origin first; a host alias such as
    github.com-work counts); None outside a repo or without a GitHub remote."""
    if project is None or not Path(project).is_dir():
        return None
    try:
        code, out = codepin._git(project, "remote")
        if code:
            return None
        for name in sorted(out.decode("utf-8", "replace").split(), key=lambda n: n != "origin"):
            code, url = codepin._git(project, "remote", "get-url", name)
            m = re.search(r"github[\w.-]*[:/]+([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$", url.decode("utf-8", "replace").strip())
            if code == 0 and m:
                return f"{m.group(1)}/{m.group(2)}"
    except codepin.GitMissing:
        return None
    return None


def project_account(project: Path | None) -> str | None:
    """The account the project shares as (settings.json shareAs, by the folder's resolved path), None when unset."""
    if project is None:
        return None
    return (settings.load().get("shareAs") or {}).get(str(Path(project).resolve()))


def set_project_account(project: Path, login: str | None) -> None:
    """Make login the project's account (None: ask again on the first share)."""
    chosen = dict(settings.load().get("shareAs") or {})
    key = str(Path(project).resolve())
    if login:
        chosen[key] = login
    else:
        chosen.pop(key, None)
    settings.save({"shareAs": chosen or None})


def choose(project: Path | None, remote: str | None, accts: list[dict], rec: dict | None) -> dict | None:
    """The account a share in project goes out as, {login, why}: why "only" (the one usable account), "project" (the
    project's account, else the account the doc's gist is on), "remote" (the remote's owner or a member of the
    owner's org, in gh's order) or "active" (gh's active account). None without a usable account."""
    usable = [a for a in accts if a["usable"]]
    if not usable:
        return None
    if len(usable) == 1:
        return {"login": usable[0]["login"], "why": "only"}
    for want in (project_account(project), (rec or {}).get("user")):
        found = next((a["login"] for a in usable if same(a["login"], want)), None)
        if found:
            return {"login": found, "why": "project"}
    owner = remote.split("/", 1)[0] if remote else None
    if owner:
        found = next((a["login"] for a in usable if member(a["login"], owner)), None)
        if found:
            return {"login": found, "why": "remote"}
    return {"login": next((a for a in usable if a["active"]), usable[0])["login"], "why": "active"}


def _iso(t: float | None) -> str | None:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(timespec="seconds") if t is not None else None


def budget_of(login: str | None) -> dict | None:
    """gistbudget.status for the account, its times as ISO 8601 (UTC): {login, used, limit, next, retryAt, paused}."""
    if not login:
        return None
    s = gistbudget.status(login)
    return {"login": login, "used": s["used"], "limit": s["limit"], "next": _iso(s["next"]), "retryAt": _iso(s["retryAt"]),
            "paused": s["paused"]}


def queued_view(q: dict | None, doc_path: Path) -> dict | None:
    """A queued update as the routes give it: {at: when it goes out (ISO 8601, null while paused), why: hour | spacing |
    retry | paused, login: the account it goes out as}, from the budget as it is now (gistbudget.due)."""
    if not q:
        return None
    at, why = gistbudget.due(q["login"], str(doc_path)) if q.get("login") else (q.get("at"), q.get("why"))
    return {"at": _iso(at), "why": why or q.get("why"), "login": q.get("login")}


def view(doc_path: Path, project: Path | None = None, remote: str | None = None, brief: bool = False,
         fresh: bool | None = None, state: dict | None = None, kinds: list[str] | None = None) -> dict:
    """What the share sheet shows: {share: record_of or null, rev, queued: queued_view, contents, accounts, account:
    choose's, ask: whether to show the picker (2+ usable accounts), mismatch: {gist, project} when the gist is on
    another account than the share would use, off: sharing_state's, budget: budget_of the account it goes out as,
    error: why the last queued update didn't go, or null, answers: {kinds (kinds, else the reader state's, else the
    defaults), counts, notShared, changed: whether they differ from the shared ones}}. state: the doc's reader state.
    brief (the Share key on load): {share, rev, off, queued}. fresh: ask gh again (default: unless brief) rather than
    take its accounts from the last minute. ShareError (400): a deck, a listing or an unreadable doc."""
    doc_path = Path(doc_path).resolve()
    _, doc = read_doc(doc_path)
    rec, raw = record_of(doc_path), _load().get(str(doc_path)) or {}
    accts, off = sharing_state(not brief if fresh is None else fresh)
    out = {"share": rec, "rev": rev_of(doc), "off": off, "queued": queued_view(raw.get("queued"), doc_path)}
    if brief:
        return out
    acc = None if off else choose(project, remote, accts, rec)
    gist_user = (rec or {}).get("user")
    mismatch = ({"gist": gist_user, "project": acc["login"]}
                if gist_user and acc and not same(gist_user, acc["login"]) and not same(rec.get("kept"), acc["login"])
                else None)
    kinds = kinds_of(state) if kinds is None else kinds
    ans = answers_of(state, doc, kinds)
    login = (out["queued"] or {}).get("login") or gist_user or (acc or {}).get("login")
    return {**out, "contents": contents(doc), "accounts": accts, "account": acc,
            "ask": sum(a["usable"] for a in accts) >= 2, "mismatch": mismatch, "budget": budget_of(login),
            "error": raw.get("error") if isinstance(raw.get("error"), str) else None,
            "answers": {"kinds": kinds, "counts": ans["counts"], "notShared": ans["notShared"],
                        "changed": bool(rec) and (rec.get("answersHash") != ans["hash"] or rec.get("answers") != kinds)
                        and bool(ans["state"] or rec.get("answersHash"))}}


# ---------- gists ----------
# Every write goes through gh api -i, so its status and headers are read, refused ones too (gh_api), one at a time
# and at least WRITE_GAP apart; gistbudget logs it. A create or update that doesn't fit the budget is queued.
WRITE_GAP = 1.0
_last_write = [0.0]


def _write(*args: str, stdin: str | None = None, token: str | None = None) -> tuple[int | None, dict, str]:
    wait = _last_write[0] + WRITE_GAP - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        return gh_api(*args, stdin=stdin, token=token)
    finally:
        _last_write[0] = time.monotonic()


def _gist(gist_id: str, token: str) -> dict | None:
    """The gist's JSON from GitHub, None when it's gone (404)."""
    try:
        data = json.loads(gh("api", f"gists/{gist_id}", token=token))
    except GhFailed as e:
        if e.not_found:
            return None
        raise
    except ValueError as e:
        raise ShareError(f"gh api gists/{gist_id} answered something other than JSON: {e}") from e
    return data if isinstance(data, dict) else None


def _json(body: str) -> dict:
    try:
        data = json.loads(body)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _create(files: dict[str, str], desc: str, login: str, token: str) -> tuple[str, str, str]:
    """`gh api -i -X POST gists` (secret) as login: (id, user, gist URL)."""
    body = {"description": desc, "public": False, "files": {n: {"content": t} for n, t in files.items()}}
    _, _, out = _write("-X", "POST", "gists", "--input", "-", stdin=json.dumps(body, ensure_ascii=False), token=token)
    data = _json(out)
    gist_id = data.get("id")
    if not (isinstance(gist_id, str) and re.fullmatch(r"[0-9A-Za-z]+", gist_id)):
        raise ShareError(f"gh api -X POST gists gave no gist id: {out.strip()[:200]}")
    user = (data.get("owner") or {}).get("login") or login
    return gist_id, user, data.get("html_url") or f"https://gist.github.com/{user}/{gist_id}"


def _patch(gist_id: str, files: dict[str, str], desc: str, old: dict, token: str) -> tuple[str, str]:
    """`gh api -i -X PATCH gists/<id>`: every file, and null for the gist's files that aren't one now. (user, URL)."""
    body = {"description": desc, "files": {**{n: None for n in (old.get("files") or {}) if n not in files},
                                           **{n: {"content": t} for n, t in files.items()}}}
    _, _, out = _write("-X", "PATCH", f"gists/{gist_id}", "--input", "-", stdin=json.dumps(body, ensure_ascii=False), token=token)
    data = _json(out)
    owner = (data.get("owner") or old.get("owner") or {}).get("login") or ""
    return owner, data.get("html_url") or old.get("html_url") or ""


def _delete(gist_id: str, token: str | None, login: str | None) -> None:
    """`gh api -i -X DELETE gists/<id>`, logged in login's budget (a delete never waits); a gist gone already is no
    error."""
    try:
        _write("-X", "DELETE", f"gists/{gist_id}", token=token)
    except GhFailed as e:
        if not e.not_found:
            raise
    if login:
        gistbudget.deleted(login)


# ---------- the queue ----------
# A share that doesn't fit the budget waits in its shares.json entry as `queued`: {at: when it may go (epoch; null while
# paused), why, login, as, move, keep, answers: the kinds}. A first share's entry is that alone, with no gist id yet.
# A share while queued makes no gh call: it updates what the queued one carries and how. serve.py's queue sends it
# when it is due (share(…, from_queue=True)), reading the doc as it is then; an error there is kept as `error`.

def queued_of(doc_path: Path) -> dict | None:
    q = (_load().get(str(Path(doc_path).resolve())) or {}).get("queued")
    return q if isinstance(q, dict) else None


def queued_docs() -> list[tuple[Path, dict]]:
    """[(doc, its queued update)] for every doc that waits."""
    return [(Path(k), r["queued"]) for k, r in _load().items() if isinstance(r, dict) and isinstance(r.get("queued"), dict)]


def _set_entry(doc_path: Path, **kw) -> None:
    """Change the doc's shares.json entry: each kw set (None removes it); an entry left with neither a gist nor a
    queued update goes."""
    data = _load()
    e = dict(data.get(str(doc_path)) or {})
    for k, v in kw.items():
        if v is None:
            e.pop(k, None)
        else:
            e[k] = v
    if isinstance(e.get("id"), str) or isinstance(e.get("queued"), dict):
        data[str(doc_path)] = e
    else:
        data.pop(str(doc_path), None)
    _save(data)


def drop_failed(doc_path: Path, error: str) -> None:
    """The queue couldn't send the doc's update: it waits no more, and the sheet says why."""
    with LOCK:
        _set_entry(Path(doc_path).resolve(), queued=None, error=error)


def _queued(doc_path: Path, doc: dict, rec: dict | None, q: dict) -> dict:
    return {"queued": queued_view(q, doc_path), "share": rec, "as": q.get("login"), "budget": budget_of(q.get("login")),
            "contents": contents(doc), "rev": rev_of(doc)}


def share(doc_path: Path, project: Path | None = None, remote: str | None = None, as_: str | None = None,
          move: bool = False, keep: bool = False, *, answers: list[str] | None = None, state: dict | None = None,
          from_queue: bool = False) -> dict:
    """Put the doc in its secret gist: created on the first share, updated (same id, same link) after, as the account
    the gist is on. as_: share as this account, and make it the project's. Without it the project's account, else
    choose's pick, which becomes the project's when there was one to make (2+ usable accounts). A gist on another
    account than that: Mismatch (409) unless move or keep. answers: the kinds of the reader's answers that go
    (answers_of; None: DEFAULT_ANSWERS), from state, the doc's reader state. Returns {share: the record, created:
    whether the gist is new, relinked: whether the link changed (a gist gone from GitHub, or moved), moved, as: the
    account it went out as, contents, files: {name: bytes}, answers: answers_of's counts, warning?: an old gist a move
    couldn't delete}; or, when the update doesn't fit the budget (or GitHub refused it for its rate limit), it waits:
    {queued: queued_view, share: the record as it was, as, budget, contents, rev}. A share while one waits makes no gh
    call. A deck or a listing is refused first, then gh is checked, then the files are made (the size check).
    from_queue: serve.py's queue sending a queued update. ShareError: see the module docstring."""
    doc_path = Path(doc_path).resolve()
    _, doc = read_doc(doc_path)
    if move and keep:
        raise ShareError("move or keep, not both", 400)
    kinds = list(DEFAULT_ANSWERS) if answers is None else (parse_kinds(list(answers)) or [])
    if not from_queue:
        with LOCK:
            q = queued_of(doc_path)
            if q is not None:   # one waits already: it goes out with the doc as it is then, carrying what this one asks
                q = {**q, "answers": kinds, **({"as": as_} if as_ else {}), **({"move": True, "keep": False} if move else {}),
                     **({"keep": True, "move": False} if keep else {})}
                _set_entry(doc_path, queued=q)
                return _queued(doc_path, doc, record_of(doc_path), q)
    accts, off = sharing_state()
    if off:
        raise off_error(off)
    if as_ is not None:
        a = next((x for x in accts if same(x["login"], as_)), None)
        if a is None:
            raise ShareError(f"gh isn't signed in as {as_}: run `gh auth login -s gist` and sign in as {as_}", 400)
        if not a["usable"]:
            raise ShareError(f"{a['login']} lacks the gist scope: run `{a['fix']}`", 400)
        login = a["login"]
        if project is not None:
            set_project_account(project, login)
    else:
        acc = choose(project, remote, accts, record_of(doc_path))
        login = acc["login"]
        if acc["why"] != "only" and project is not None and not same(project_account(project), login):
            set_project_account(project, login)
    warning = None
    with LOCK:
        old = record_of(doc_path)
        owner = str((old or {}).get("user") or "")
        moving, kept_for = False, None
        if old and owner and not same(owner, login):
            if not (move or keep or same(old.get("kept"), login)):
                raise Mismatch(owner, login)
            if move:
                moving = True
            else:   # kept: the gist stays on its account, which updates it, until the project's account changes again
                kept_for, login = login, owner
                kept = next((a for a in accts if same(a["login"], owner)), None)
                if kept is not None and not kept["usable"]:
                    raise ShareError(f"{kept['login']}, the account the gist is on, lacks the gist scope: run `{kept['fix']}`")
        wait = {"as": as_, "move": move, "keep": keep, "answers": kinds, "login": login}
        at, why = gistbudget.due(login, str(doc_path))
        if at is None or at > gistbudget.clock():
            q = {**wait, "at": at, "why": why}
            _set_entry(doc_path, queued=q, error=None, **({} if old else {"user": login}))
            return _queued(doc_path, doc, old, q)
        slot, ahash = answers_slot(state, doc, kinds, login)
        files, doc, what = gist_files(doc_path, slot)
        desc = f"bluedoc: {build.shown_title(doc, None) or build.doc_stem(doc_path)}"
        token = token_for(login)
        gist = _gist(old["id"], token) if old and not moving else None
        try:
            if gist is not None:
                user, url = _patch(old["id"], files, desc, gist, token)
                gist_id, user = old["id"], user or owner or login
                url = url or f"https://gist.github.com/{user}/{gist_id}"
            else:
                gist_id, user, url = _create(files, desc, login, token)
        except RateLimited as e:
            b = gistbudget.refused(login, e.headers)
            q = {**wait, "at": None if b["paused"] else b["retryAt"], "why": "paused" if b["paused"] else "retry"}
            _set_entry(doc_path, queued=q, error=None, **({} if old else {"user": login}))
            return _queued(doc_path, doc, old, q)
        gistbudget.sent(login, str(doc_path))
        rec = {"id": gist_id, "user": user, "link": link_for(user, gist_id), "url": url, "rev": rev_of(doc),
               "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "files": sorted(files),
               "answers": kinds, "answersHash": ahash, **({"kept": kept_for} if kept_for else {})}
        data = _load()
        data[str(doc_path)] = rec
        _save(data)
        if moving:
            try:
                _delete(old["id"], token_for(owner), owner)
            except ShareError as e:
                warning = f"the old gist {old['id']} on {owner} is still there ({e}): delete it on GitHub"
    res = {"share": rec, "created": gist is None, "relinked": bool(old) and gist is None, "moved": moving, "as": login,
           "contents": what, "files": {n: len(t.encode("utf-8")) for n, t in files.items()},
           "answers": answers_of(state, doc, kinds)["counts"] if slot else None}
    return {**res, "warning": warning} if warning else res


def resume(doc_path: Path, login: str | None = None) -> str | None:
    """Lift the pause on the account the doc's update goes out as (its queued one's, else its gist's, else login):
    the account resumed, or None when there is none to name."""
    raw = _load().get(str(Path(doc_path).resolve())) or {}
    who = (raw.get("queued") or {}).get("login") or raw.get("user") or login
    if not who:
        return None
    gistbudget.resume(who)
    return who


def unshare(doc_path: Path) -> dict | None:
    """Delete the doc's gist as the account it is on and forget it (also when GitHub has no such gist any more); a
    queued update goes with it. The record it had, or None when it wasn't shared. ShareError: gh is missing, isn't
    signed in as that account, or failed otherwise, and the share is kept."""
    doc_path = Path(doc_path).resolve()
    with LOCK:
        rec = record_of(doc_path)
        if rec is None:
            _set_entry(doc_path, queued=None, error=None, user=None)   # a first share that waited: forgotten
            return None
        login = str(rec.get("user") or "")
        _delete(rec["id"], token_for(login) if login else None, login)
        data = _load()
        data.pop(str(doc_path), None)
        _save(data)
    return rec


def red(text: str, stream) -> str:
    """text in ANSI red (bold) when stream is a terminal."""
    return f"\x1b[1;31m{text}\x1b[0m" if getattr(stream, "isatty", lambda: False)() and not os.environ.get("NO_COLOR") else text


def contents_line(what: dict) -> str:
    n = lambda k, one, many: f"{what[k]} {one if what[k] == 1 else many}"  # noqa: E731
    return ", ".join([n("media", "media file", "media files"), n("screens", "screen", "screens")])


# ---------- what the CLI says (serve.py share, build.py patch) ----------

def _epoch(iso: str | None) -> float | None:
    try:
        return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp() if iso else None
    except ValueError:
        return None


def at_text(iso: str | None) -> str:
    """A queued update's time as the CLI says it: "15:42 (in 6 min)", local time."""
    t = _epoch(iso)
    if t is None:
        return "when the updates resume"
    mins = max(1, round((t - gistbudget.clock()) / 60))
    return f"{dt.datetime.fromtimestamp(t).strftime('%H:%M')} (in {mins} min)"


def budget_line(b: dict | None) -> str:
    if not b:
        return ""
    return (f"budget: {b['used']} of {b['limit']} used in the last hour on {b['login']}; GitHub allows about "
            f"{gistbudget.GITHUB_LIMIT} gist updates an hour")


def paused_text(login: str) -> str:
    return (f"GitHub refused {gistbudget.PAUSE_AFTER} updates in a row on {login}; tell the user: Resume updates in "
            "the Share sheet sends it")


def queued_lines(res: dict) -> list[str]:
    """`serve.py share`'s lines for an update that waits (share's queued answer); paused: none (the CLI says
    paused_text and exits 1)."""
    q, rec = res["queued"], res.get("share")
    why = {"retry": "GitHub asked to wait", "spacing": "one update a minute per doc",
           "hour": f"{gistbudget.BUDGET} updates an hour per account"}.get(q.get("why") or "", "")
    lines = [f"queued: rev {res.get('rev') or '-'} goes out at {at_text(q.get('at'))} as {q.get('login')}, with the doc as it "
             f"is then" + (f" ({why})" if why else ""),
             budget_line(res.get("budget")),
             "done: don't share again for this round; later patches go out with it"]
    lines.append(f"link: {rec['link']} (shows rev {rec.get('rev') or '-'} until then)" if rec
                 else "link: made when it goes out; the Share sheet shows it then")
    return [x for x in lines if x]


def patch_line(doc_path: Path, rev: str | None) -> str | None:
    """build.py patch's line on a shared doc (shares.json and gist-budget.json only, no gh call): the link's rev and the
    hour's count, or the queued update this patch goes out with, or the pause; None when the doc isn't shared."""
    raw = _load().get(str(Path(doc_path).resolve()))
    if not isinstance(raw, dict):
        return None
    q = raw.get("queued") if isinstance(raw.get("queued"), dict) else None
    login = (q or {}).get("login") or raw.get("user")
    if not login:
        return None
    b = gistbudget.status(login)
    count = f"{b['used']} of {b['limit']} used this hour"
    if b["paused"]:
        return f"shared as {login}: updates are paused (GitHub refused {gistbudget.PAUSE_AFTER} in a row): tell the user"
    if q:
        at = gistbudget.due(login, str(Path(doc_path).resolve()))[0]
        return f"rev {rev or '-'} is queued for {at_text(_iso(at)).split(' ')[0]} and carries this patch ({count})"
    return (f"shared as {login} at rev {raw.get('rev') or '-'}: run serve.py share {shlex.quote(str(doc_path))} once "
            f"this round is done ({count})")
