#!/usr/bin/env python3
"""A stand-in for the GitHub CLI's gist and account commands, for tests/test_share.py: put it on PATH as `gh`. It never
reaches GitHub. Each call is appended to $STANDIN_GH_DIR/calls.jsonl ({argv, stdin, as: the account its GH_TOKEN is
for, or null without one}: never the token); gists live in $STANDIN_GH_DIR/gists/<id>/ (meta.json with the owner, and
a files/ folder).

Accounts: $STANDIN_GH_ACCOUNTS, comma-separated `login[:flag…]`, gh's order, flags `active` (else the first is),
`nogist` (a token without the gist scope), `pat` (a fine-grained token: no scopes listed), `failed` (an invalid
token). Unset: $STANDIN_GH_USER (acme-dev) alone, without the gist scope when STANDIN_GH_AUTH=no-gist;
STANDIN_GH_AUTH=signed-out: no account. $STANDIN_GH_ORGS, comma-separated `login=org`: the orgs an account is an active
member of. Each account's token is `gho_standin_<login>`. A call runs as its GH_TOKEN's account, else the active one.
It answers as gh does:
  gh auth status [--hostname H]      a block per account (gh 2.40+); exit 1 when one has failed or none is signed in
  gh auth token [--hostname H] [--user L]   the account's token; exit 1 when gh has no such account
  gh api user [--jq .login]          the login
  gh api user/memberships/orgs/<org> [--jq .state]   active when the account is a member, else 404
  gh api gists/<id>                  the gist's JSON; 404 (gh: Not Found (HTTP 404), exit 1) when there is none
  gh api -X POST gists --input -     creates a gist from {description, public, files: {name: {content}}} on stdin
                                     (201 and its JSON)
  gh api -X PATCH gists/<id> --input -   applies {description, files: {name: {content} | null}} from stdin; 404 for
                                     an account that doesn't own it, as GitHub answers
  gh api -X DELETE gists/<id>        deletes it (204); 404 when there is none or another account owns it
`gh api -i` prints the status line and the headers, a blank line, then the body, as gh does, also when the call fails
(the error then on stderr, `gh: <message> (HTTP <status>)`, exit 1). Each answer carries x-ratelimit-limit 5000 and
x-ratelimit-remaining 4999.
STANDIN_GH_FAIL: when the call's words contain it, gh fails with an HTTP 500.
STANDIN_GH_REFUSE: `<status>[:<name>=<value>,…]`, e.g. `429:retry-after=300` or
`403:x-ratelimit-remaining=0,x-ratelimit-reset=<epoch>`: every gist create (POST) and update (PATCH) is refused with
that status and those headers (`message=<text>` sets the body's message; else "API rate limit exceeded for user"),
nothing written. Deletes and reads are never refused."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
from pathlib import Path

STATE = Path(os.environ["STANDIN_GH_DIR"])
TOKEN_PREFIX = "gho_standin_"


def fail(msg: str, code: int = 1) -> None:
    sys.stderr.write(msg + "\n")
    sys.exit(code)


def accounts() -> list[dict]:
    """[{login, active, gist, pat, failed}] in gh's order."""
    auth = os.environ.get("STANDIN_GH_AUTH") or "ok"
    if auth == "signed-out":
        return []
    spec = os.environ.get("STANDIN_GH_ACCOUNTS") or f"{os.environ.get('STANDIN_GH_USER') or 'acme-dev'}:active" + (
        ":nogist" if auth == "no-gist" else "")
    out = []
    for part in filter(None, spec.split(",")):
        login, *flags = part.split(":")
        out.append({"login": login, "active": "active" in flags, "gist": "nogist" not in flags, "pat": "pat" in flags,
                    "failed": "failed" in flags})
    if out and not any(a["active"] for a in out):
        out[0]["active"] = True
    return out


def acting(accts: list[dict]) -> str | None:
    """The account the call runs as: its GH_TOKEN's, else the active one."""
    token = os.environ.get("GH_TOKEN")
    if token:
        login = token[len(TOKEN_PREFIX):] if token.startswith(TOKEN_PREFIX) else None
        return login if any(a["login"] == login for a in accts) else None
    return next((a["login"] for a in accts if a["active"]), None)


def gist_dir(gid: str) -> Path:
    return STATE / "gists" / gid


def view(gid: str) -> dict:
    d = gist_dir(gid)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    files = {f.name: {"filename": f.name, "size": f.stat().st_size, "content": f.read_text(encoding="utf-8")}
             for f in sorted((d / "files").iterdir())}
    return {"id": gid, "html_url": f"https://gist.github.com/{meta['owner']}/{gid}", "public": meta["public"],
            "description": meta["description"], "owner": {"login": meta["owner"]}, "files": files}


def status(accts: list[dict]) -> None:
    if not accts:
        fail("You are not logged into any GitHub hosts. To log in, run: gh auth login")
    blocks = []
    for a in accts:
        active = f"  - Active account: {'true' if a['active'] else 'false'}\n"
        if a["failed"]:
            blocks.append(f"  X Failed to log in to github.com account {a['login']} (keyring)\n{active}"
                          "  - The token in keyring is invalid.\n  - To re-authenticate, run: gh auth login -h github.com\n"
                          f"  - To forget about this account, run: gh auth logout -h github.com -u {a['login']}\n")
            continue
        token = "github_pat_****" if a["pat"] else "gho_************************************"
        scopes = "" if a["pat"] else "  - Token scopes: " + ("'gist', " if a["gist"] else "") + "'read:org', 'repo'\n"
        blocks.append(f"  ✓ Logged in to github.com account {a['login']} (keyring)\n{active}"
                      f"  - Git operations protocol: https\n  - Token: {token}\n{scopes}")
    text = "github.com\n" + "\n".join(blocks)
    if any(a["failed"] for a in accts):
        fail(text.rstrip("\n"))
    print(text, end="")


REASONS = {200: "OK", 201: "Created", 204: "No Content", 403: "Forbidden", 404: "Not Found", 422: "Unprocessable Entity",
           429: "Too Many Requests", 500: "Internal Server Error"}


def answer(code: int, body: dict | None, include: bool, headers: dict | None = None) -> None:
    """GitHub's answer as gh prints it: with -i the status line and headers first; an error also on stderr, exit 1."""
    if include:
        hs = {"Content-Type": "application/json; charset=utf-8", "X-Ratelimit-Limit": "5000", "X-Ratelimit-Remaining": "4999",
              **(headers or {})}
        sys.stdout.write(f"HTTP/2.0 {code} {REASONS.get(code, '')}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in hs.items()) + "\r\n")
    if body is not None:
        sys.stdout.write(json.dumps(body) + "\n")
    sys.stdout.flush()
    if code >= 400:
        msg = (body or {}).get("message") or REASONS.get(code, "error")
        fail(f"gh: {msg} (HTTP {code})")


def refusal() -> tuple[int, dict, str] | None:
    """STANDIN_GH_REFUSE as (status, headers, message), or None."""
    spec = os.environ.get("STANDIN_GH_REFUSE")
    if not spec:
        return None
    code, _, rest = spec.partition(":")
    headers, message = {}, "API rate limit exceeded for user"
    for part in filter(None, rest.split(",")):
        k, _, v = part.partition("=")
        if k == "message":
            message = v
        else:
            headers[k] = v
    return int(code), headers, message


def main(argv: list[str]) -> None:
    data = sys.stdin.read() if "--input" in argv else None
    STATE.mkdir(parents=True, exist_ok=True)
    accts = accounts()
    who = acting(accts)
    with open(STATE / "calls.jsonl", "a", encoding="utf-8") as log:
        log.write(json.dumps({"argv": argv, "stdin": data,
                              "as": who if os.environ.get("GH_TOKEN") else None}) + "\n")
    if os.environ.get("STANDIN_GH_FAIL") and os.environ["STANDIN_GH_FAIL"] in " ".join(argv):
        fail("gh: Server Error (HTTP 500)")
    if argv[:2] == ["auth", "status"]:
        status(accts)
        return
    if argv[:2] == ["auth", "token"]:
        user = argv[argv.index("--user") + 1] if "--user" in argv else None
        a = next((a for a in accts if a["login"] == user), None) if user else next((a for a in accts if a["active"]), None)
        if a is None:
            fail(f"no oauth token found for github.com account {user}" if user else "no oauth token found for github.com")
        print(TOKEN_PREFIX + a["login"])
        return
    if who is None or next(a for a in accts if a["login"] == who)["failed"]:
        fail("To get started with GitHub CLI, please run:  gh auth login", 4)
    me = next(a for a in accts if a["login"] == who)
    if argv[:2] == ["api", "user"]:
        print(who)
        return
    if argv[:1] == ["api"]:
        method, path, rest, i, include = "GET", None, argv[1:], 0, False
        while i < len(rest):
            if rest[i] in ("-X", "--method"):
                method, i = rest[i + 1], i + 2
            elif rest[i] in ("--input", "--jq"):
                i += 2
            elif rest[i] in ("-i", "--include"):
                include, i = True, i + 1
            else:
                path, i = rest[i], i + 1
        if path and path.startswith("user/memberships/orgs/"):
            org = path.rsplit("/", 1)[1]
            orgs = [p.split("=", 1) for p in filter(None, (os.environ.get("STANDIN_GH_ORGS") or "").split(","))]
            if [who, org] not in [[lg, o] for lg, o in orgs]:
                fail("gh: Not Found (HTTP 404)")
            print("active" if "--jq" in argv else json.dumps({"state": "active", "organization": {"login": org}}))
            return
        not_found = {"message": "Not Found", "documentation_url": "https://docs.github.com/rest"}
        refuse = refusal() if method in ("POST", "PATCH") else None
        if refuse:
            code, headers, message = refuse
            answer(code, {"message": message, "documentation_url": "https://docs.github.com/rest/overview/rate-limits-for-the-rest-api"},
                   include, headers)
        if method == "POST" and path == "gists":
            if not me["gist"]:
                answer(404, not_found, include)
            body = json.loads(data or "{}")
            gid = secrets.token_hex(16)
            d = gist_dir(gid)
            (d / "files").mkdir(parents=True)
            for name, f in (body.get("files") or {}).items():
                (d / "files" / name).write_text(f["content"], encoding="utf-8")
            (d / "meta.json").write_text(json.dumps({"description": body.get("description", ""), "public": body.get("public") is True,
                                                     "owner": who}), encoding="utf-8")
            answer(201, view(gid), include, {"Location": f"https://api.github.com/gists/{gid}"})
            return
        if not path or not path.startswith("gists/"):
            fail(f"stand-in gh: no {method} {path}")
        gid = path.split("/", 1)[1]
        d = gist_dir(gid)
        if not d.is_dir():
            answer(404, not_found, include)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if method in ("DELETE", "PATCH") and (meta["owner"] != who or not me["gist"]):
            answer(404, not_found, include)
        if method == "DELETE":
            shutil.rmtree(d)
            answer(204, None, include)
            return
        if method == "PATCH":
            body = json.loads(data or "{}")
            if "description" in body:
                meta["description"] = body["description"]
            for name, f in (body.get("files") or {}).items():
                if f is None:
                    (d / "files" / name).unlink(missing_ok=True)
                else:
                    (d / "files" / name).write_text(f["content"], encoding="utf-8")
            (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        answer(200, view(gid), include)
        return
    fail(f"stand-in gh: unknown command {argv}")


if __name__ == "__main__":
    main(sys.argv[1:])
