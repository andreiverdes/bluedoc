#!/usr/bin/env python3
"""A stand-in for the GitHub CLI's gist commands, for tests/test_share.py: put it on PATH as `gh`. It never reaches
GitHub. Each call is appended to $STANDIN_GH_DIR/calls.jsonl ({argv, stdin}); gists live in $STANDIN_GH_DIR/gists/<id>/
(meta.json and a files/ folder). It answers as gh does:
  gh auth status [--hostname H]      signed in as $STANDIN_GH_USER (acme-dev) with the gist scope; STANDIN_GH_AUTH
                                     signed-out: exit 1 as gh does without a login; no-gist: a token without it
  gh api user --jq .login            the login
  gh gist create --desc D FILE…      a secret gist of the files in the working folder (a NUL byte: refused as a
                                     binary, as gh does); prints https://gist.github.com/<user>/<id>
  gh api gists/<id>                  the gist's JSON; 404 (gh: Not Found (HTTP 404), exit 1) when there is none
  gh api -X PATCH gists/<id> --input -   applies {description, files: {name: {content} | null}} from stdin
  gh api -X DELETE gists/<id>        deletes it; 404 when there is none
STANDIN_GH_FAIL: when the call's words contain it, gh fails with an HTTP 500."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
from pathlib import Path

STATE = Path(os.environ["STANDIN_GH_DIR"])
USER = os.environ.get("STANDIN_GH_USER") or "acme-dev"


def fail(msg: str, code: int = 1) -> None:
    sys.stderr.write(msg + "\n")
    sys.exit(code)


def gist_dir(gid: str) -> Path:
    return STATE / "gists" / gid


def view(gid: str) -> dict:
    d = gist_dir(gid)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    files = {f.name: {"filename": f.name, "size": f.stat().st_size, "content": f.read_text(encoding="utf-8")}
             for f in sorted((d / "files").iterdir())}
    return {"id": gid, "html_url": f"https://gist.github.com/{USER}/{gid}", "public": meta["public"],
            "description": meta["description"], "owner": {"login": USER}, "files": files}


def main(argv: list[str]) -> None:
    data = sys.stdin.read() if "--input" in argv else None
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / "calls.jsonl", "a", encoding="utf-8") as log:
        log.write(json.dumps({"argv": argv, "stdin": data}) + "\n")
    if os.environ.get("STANDIN_GH_FAIL") and os.environ["STANDIN_GH_FAIL"] in " ".join(argv):
        fail("gh: Server Error (HTTP 500)")
    auth = os.environ.get("STANDIN_GH_AUTH") or "ok"
    if argv[:2] == ["auth", "status"]:
        if auth == "signed-out":
            fail("You are not logged into any GitHub hosts. To log in, run: gh auth login")
        scopes = "'gist', 'read:org', 'repo'" if auth == "ok" else "'read:org', 'repo'"
        print(f"github.com\n  ✓ Logged in to github.com account {USER} (keyring)\n  - Active account: true\n"
              f"  - Git operations protocol: https\n  - Token: gho_************************************\n"
              f"  - Token scopes: {scopes}")
        return
    if auth == "signed-out":
        fail("To get started with GitHub CLI, please run:  gh auth login", 4)
    if argv[:2] == ["api", "user"]:
        print(USER)
        return
    if argv[:2] == ["gist", "create"]:
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
        (d / "meta.json").write_text(json.dumps({"description": desc, "public": public}), encoding="utf-8")
        sys.stderr.write(f"- Creating gist with multiple files\n✓ Created {'public' if public else 'secret'} gist {names[0]}\n")
        print(f"https://gist.github.com/{USER}/{gid}")
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
        if not path or not path.startswith("gists/"):
            fail(f"stand-in gh: no {method} {path}")
        gid = path.split("/", 1)[1]
        d = gist_dir(gid)
        if not d.is_dir():
            fail("gh: Not Found (HTTP 404)")
        if method == "DELETE":
            shutil.rmtree(d)
            return
        if method == "PATCH":
            body = json.loads(data or "{}")
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
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
