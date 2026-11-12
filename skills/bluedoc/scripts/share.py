#!/usr/bin/env python3
"""Share a doc as a secret GitHub gist, opened at https://bluedoc.ai/g/<code> (link_for; serve.py share/unshare,
GET/POST /__bluedoc/share and POST /__bluedoc/unshare).

A share holds the doc's current revision only, in two text files (gh gist create refuses binaries):
  <stem>.bluedoc.json           the doc, verbatim
  bluedoc-page.json             what the bluedoc.ai viewer fills the template with:
      {"bluedoc": "share/1", "version": <bluedoc version>, "name": <stem>, "title": <shown title>, "rev": <meta.rev or
       null>, "boardGeo": <whether the page needs assets/board-geo.js at /*__BOARD_GEO__*/>,
       "fill": {placeholder: text}}: exactly what build.py -o substitutes for the doc without its history
      (build.standalone_fill: diffs expanded, media and screens inline, no reader state, no earlier revisions) but the
      board-geo slot, which the viewer fills from its own copy.
A bluedoc-page.json over MAX_PAGE_BYTES (10 MB) is refused (413): Export → HTML file sends the doc instead.

Accounts: the github.com accounts `gh auth status` lists (accounts). One is usable when its token has the gist scope
(or is fine-grained); one without shows its fix, `gh auth refresh -s gist -u <login>`. Sharing is off (sharing_state)
when gh is missing, signed out, or has no usable account. Each project (a folder on the home page) shares as one
account, kept in settings.json's shareAs by the folder's path (project_account). Without one, a share preselects
(choose): the only usable account; the doc's gist's account; the account that is the project's GitHub remote's owner
or a member of the owner's org (`gh api user/memberships/orgs/<owner>` as each account, cached); else gh's active one.

Every gh call that writes or deletes a gist runs as one account: GH_TOKEN=$(gh auth token -u <login>) for that call
only, so gh's active account never changes. The first share runs `gh gist create` (secret, described
`bluedoc: <title>`); a later one `gh api -X PATCH gists/<id>` with every file (files it no longer has set to null), as
the account the gist is on, so the link stays; a gist gone from GitHub is created anew. When the project now shares
as another account than the gist's, a share is refused (409, Mismatch) until it says move (a new gist on the project's
account, the old one deleted as its own: the link changes) or keep (updated as the gist's account: the link stays;
recorded as kept, so later shares update it there until the project's account changes again). unshare runs
`gh api -X DELETE gists/<id>` as the gist's account and forgets the share, also when the gist is gone.

Shares are recorded in $BLUEDOC_HOME/shares.json (mode 0600), keyed by the doc's resolved path: {id, user (the account
the gist is on), link, url, rev, at, files, kept? (the project account it was kept from)}. Never in the doc or its
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
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import build  # noqa: E402
import codepin  # noqa: E402
import settings  # noqa: E402

FORMAT = "share/1"
PAGE_FILE = "bluedoc-page.json"
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
    """The doc's share ({id, user, link, url, rev, at, files, kept?}), or None when it isn't shared. user is the
    account the gist is on (a share made before accounts were picked: gh's active account then). Its link is
    link_for's now, so a share recorded with an older link form shows the current one."""
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


def bundle(doc: dict, doc_path: Path) -> dict:
    """bluedoc-page.json's object: build.standalone_fill's values for the doc alone (no history), with the board-geo
    slot as boardGeo."""
    fill = build.standalone_fill(doc, Path(doc_path), None, problems=[])
    geo = fill.pop(build.BOARD_GEO_SLOT)
    return {"bluedoc": FORMAT, "version": build.skill_version() or "unknown", "name": build.doc_stem(Path(doc_path)),
            "title": build.shown_title(doc, None), "rev": rev_of(doc), "boardGeo": bool(geo), "fill": fill}


def gist_files(doc_path: Path) -> tuple[dict[str, str], dict, dict]:
    """({file name: text} for the gist, the doc, contents()). ShareError: an unreadable doc, a deck or a listing
    (400), a bluedoc-page.json over MAX_PAGE_BYTES (413)."""
    doc_path = Path(doc_path).resolve()
    text, doc = read_doc(doc_path)
    page = json.dumps(bundle(doc, doc_path), ensure_ascii=False, separators=(",", ":")) + "\n"
    size = len(page.encode("utf-8"))
    if size > MAX_PAGE_BYTES:
        raise ShareError(f"the shared page would be {size / 1048576:.1f} MB, over the 10 MB a gist file can hold: "
                         "send Export → HTML file instead", 413)
    return {gist_name(doc_path): text, PAGE_FILE: page}, doc, contents(doc)


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
    """gh ran and failed: what it said (said: stdout then stderr), and whether GitHub answered 404 (the gist is
    gone)."""

    def __init__(self, args, out: str, err: str) -> None:
        said = (err.strip() or out.strip()).splitlines()
        super().__init__(f"gh {' '.join(args[:2])} failed: {said[-1] if said else 'no message'}")
        self.said = out + err
        self.not_found = bool(re.search(r"HTTP 404|Not Found", err + out))


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


def view(doc_path: Path, project: Path | None = None, remote: str | None = None, brief: bool = False,
         fresh: bool | None = None) -> dict:
    """What the share sheet shows: {share: record_of or null, rev, contents, accounts, account: choose's, ask: whether
    to show the picker (2+ usable accounts), mismatch: {gist, project} when the gist is on another account than the
    share would use, off: sharing_state's}. brief (the Share key on load): {share, rev, off}. fresh: ask gh again
    (default: unless brief) rather than take its accounts from the last minute. ShareError (400): a deck, a listing or
    an unreadable doc."""
    doc_path = Path(doc_path).resolve()
    _, doc = read_doc(doc_path)
    rec = record_of(doc_path)
    accts, off = sharing_state(not brief if fresh is None else fresh)
    out = {"share": rec, "rev": rev_of(doc), "off": off}
    if brief:
        return out
    acc = None if off else choose(project, remote, accts, rec)
    gist_user = (rec or {}).get("user")
    mismatch = ({"gist": gist_user, "project": acc["login"]}
                if gist_user and acc and not same(gist_user, acc["login"]) and not same(rec.get("kept"), acc["login"])
                else None)
    return {**out, "contents": contents(doc), "accounts": accts, "account": acc,
            "ask": sum(a["usable"] for a in accts) >= 2, "mismatch": mismatch}


# ---------- gists ----------

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


def _create(files: dict[str, str], desc: str, login: str, token: str) -> tuple[str, str, str]:
    """`gh gist create` (secret) as login: (id, user, gist URL)."""
    with tempfile.TemporaryDirectory(prefix="bluedoc-share-") as d:
        for name, text in files.items():
            (Path(d) / name).write_text(text, encoding="utf-8")
        out = gh("gist", "create", "--desc", desc, *files, cwd=Path(d), token=token)
    m = re.findall(r"https://gist\.github\.com/(?:([A-Za-z0-9-]+)/)?([0-9a-f]+)\b", out)
    if not m:
        raise ShareError(f"gh gist create gave no gist URL: {out.strip()[:200]}")
    user, gist_id = m[-1]
    user = user or login
    return gist_id, user, f"https://gist.github.com/{user}/{gist_id}"


def _patch(gist_id: str, files: dict[str, str], desc: str, old: dict, token: str) -> tuple[str, str]:
    """`gh api -X PATCH gists/<id>`: every file, and null for the gist's files that aren't one now. (user, URL)."""
    body = {"description": desc, "files": {**{n: None for n in (old.get("files") or {}) if n not in files},
                                           **{n: {"content": t} for n, t in files.items()}}}
    out = gh("api", "-X", "PATCH", f"gists/{gist_id}", "--input", "-", stdin=json.dumps(body, ensure_ascii=False), token=token)
    try:
        data = json.loads(out)
    except ValueError:
        data = {}
    owner = (data.get("owner") or old.get("owner") or {}).get("login") or ""
    return owner, data.get("html_url") or old.get("html_url") or ""


def _delete(gist_id: str, token: str | None) -> None:
    """`gh api -X DELETE gists/<id>`; a gist gone already is no error."""
    try:
        gh("api", "-X", "DELETE", f"gists/{gist_id}", token=token)
    except GhFailed as e:
        if not e.not_found:
            raise


def share(doc_path: Path, project: Path | None = None, remote: str | None = None, as_: str | None = None,
          move: bool = False, keep: bool = False) -> dict:
    """Put the doc in its secret gist: created on the first share, updated (same id, same link) after, as the account
    the gist is on. as_: share as this account, and make it the project's. Without it the project's account, else
    choose's pick, which becomes the project's when there was one to make (2+ usable accounts). A gist on another
    account than that: Mismatch (409) unless move or keep. Returns {share: the record, created: whether the gist is
    new, relinked: whether the link changed (a gist gone from GitHub, or moved), moved, as: the account it went out
    as, contents, files: {name: bytes}, warning?: an old gist a move couldn't delete}. A deck or a listing is refused
    first, then gh is checked, then the files are made (the size check). ShareError: see the module docstring."""
    doc_path = Path(doc_path).resolve()
    read_doc(doc_path)
    if move and keep:
        raise ShareError("move or keep, not both", 400)
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
    files, doc, what = gist_files(doc_path)
    desc = f"bluedoc: {build.shown_title(doc, None) or build.doc_stem(doc_path)}"
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
        token = token_for(login)
        gist = _gist(old["id"], token) if old and not moving else None
        if gist is not None:
            user, url = _patch(old["id"], files, desc, gist, token)
            gist_id, user = old["id"], user or owner or login
            url = url or f"https://gist.github.com/{user}/{gist_id}"
        else:
            gist_id, user, url = _create(files, desc, login, token)
        rec = {"id": gist_id, "user": user, "link": link_for(user, gist_id), "url": url, "rev": rev_of(doc),
               "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "files": sorted(files),
               **({"kept": kept_for} if kept_for else {})}
        data = _load()
        data[str(doc_path)] = rec
        _save(data)
        if moving:
            try:
                _delete(old["id"], token_for(owner))
            except ShareError as e:
                warning = f"the old gist {old['id']} on {owner} is still there ({e}): delete it on GitHub"
    res = {"share": rec, "created": gist is None, "relinked": bool(old) and gist is None, "moved": moving, "as": login,
           "contents": what, "files": {n: len(t.encode("utf-8")) for n, t in files.items()}}
    return {**res, "warning": warning} if warning else res


def unshare(doc_path: Path) -> dict | None:
    """Delete the doc's gist as the account it is on and forget it (also when GitHub has no such gist any more). The
    record it had, or None when it wasn't shared. ShareError: gh is missing, isn't signed in as that account, or
    failed otherwise, and the share is kept."""
    doc_path = Path(doc_path).resolve()
    with LOCK:
        rec = record_of(doc_path)
        if rec is None:
            return None
        login = str(rec.get("user") or "")
        _delete(rec["id"], token_for(login) if login else None)
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
