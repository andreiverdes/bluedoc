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
  gh gist create --desc D FILE…      a secret gist of the files in the working folder (a NUL byte: refused as a
                                     binary, as gh does); prints https://gist.github.com/<user>/<id>
  gh api gists/<id>                  the gist's JSON; 404 (gh: Not Found (HTTP 404), exit 1) when there is none
  gh api -X PATCH gists/<id> --input -   applies {description, files: {name: {content} | null}} from stdin; 404 for
                                     an account that doesn't own it, as GitHub answers
  gh api -X DELETE gists/<id>        deletes it; 404 when there is none or another account owns it
STANDIN_GH_FAIL: when the call's words contain it, gh fails with an HTTP 500."""
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
    if argv[:2] == ["gist", "create"]:
        if not me["gist"]:
            fail("gh: Not Found (HTTP 404)")
        args, desc, public = argv[2:], "", False
        names = []
        i = 0
        while i < len(args):
            if args[i] in ("--desc", "-d"):
                desc, i = args[i + 1], i + 2
            elif args[i] in ("--public", "-p"):
                public, i = True, i + 1
            else:
                names.append(args[i])
                i += 1
        gid = secrets.token_hex(16)
        d = gist_dir(gid)
        (d / "files").mkdir(parents=True)
        for n in names:
            raw = Path(n).read_bytes()
            if b"\0" in raw:
                shutil.rmtree(d)
                fail(f"failed to collect files for posting: binary file contents not supported: {n}")
            (d / "files" / Path(n).name).write_bytes(raw)
        (d / "meta.json").write_text(json.dumps({"description": desc, "public": public, "owner": who}), encoding="utf-8")
        sys.stderr.write(f"- Creating gist with multiple files\n✓ Created {'public' if public else 'secret'} gist {names[0]}\n")
        print(f"https://gist.github.com/{who}/{gid}")
        return
    if argv[:1] == ["api"]:
        method, path, rest, i = "GET", None, argv[1:], 0
        while i < len(rest):
            if rest[i] in ("-X", "--method"):
                method, i = rest[i + 1], i + 2
            elif rest[i] in ("--input", "--jq"):
                i += 2
            else:
                path, i = rest[i], i + 1
        if path and path.startswith("user/memberships/orgs/"):
            org = path.rsplit("/", 1)[1]
            orgs = [p.split("=", 1) for p in filter(None, (os.environ.get("STANDIN_GH_ORGS") or "").split(","))]
            if [who, org] not in [[lg, o] for lg, o in orgs]:
                fail("gh: Not Found (HTTP 404)")
            print("active" if "--jq" in argv else json.dumps({"state": "active", "organization": {"login": org}}))
            return
        if not path or not path.startswith("gists/"):
            fail(f"stand-in gh: no {method} {path}")
        gid = path.split("/", 1)[1]
        d = gist_dir(gid)
        if not d.is_dir():
            fail("gh: Not Found (HTTP 404)")
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if method in ("DELETE", "PATCH") and (meta["owner"] != who or not me["gist"]):
            fail("gh: Not Found (HTTP 404)")
        if method == "DELETE":
            shutil.rmtree(d)
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
        print(json.dumps(view(gid)))
        return
    fail(f"stand-in gh: unknown command {argv}")


if __name__ == "__main__":
    main(sys.argv[1:])
