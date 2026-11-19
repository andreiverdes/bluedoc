"""A doc shared as a secret GitHub gist: share.py, `serve.py share`/`unshare`, /__bluedoc/share, /__bluedoc/unshare
and Settings' sharing. A stand-in gh (fixtures/gh_standin.py, named by BLUEDOC_GH as TempHome sets it) records every
call with the account its GH_TOKEN is for, keeps the gists in a temp folder with their owners, and plays any set of
signed-in accounts: nothing reaches GitHub.

The gist holds the current revision only: <stem>.bluedoc.json, the doc verbatim, and bluedoc-page.json, the contract's
object whose fill, with board-geo.js put back at its slot, makes exactly the page `build.py -o` writes for the doc
without its history (no history file, no earlier revisions), a design's 11 screens inline; a design also gets
bluedoc-screens.json, its screen files' and icon layers' text by path, under the same 10 MB cap.

Accounts: the github.com accounts `gh auth status` lists, usable with the gist scope or a fine-grained token, else
off with `gh auth refresh -s gist -u <login>`. One usable account shares as itself; with two or more the share sheet
asks, preselecting the project's account, else the doc's gist's, else the account that owns the project's GitHub
remote or is a member of its org (asked once per account, cached), else gh's active one. A share as an account (`as`)
makes it the project's (settings.json shareAs). Every gist call runs with GH_TOKEN=$(gh auth token -u <login>), never
switching gh's active account; Share again, Update and Stop sharing run as the account the gist is on (an old record:
its user). A gist on another account than the project's is a 409 until move (a new gist on the project's account, the
old one deleted as its own) or keep (updated where it is, and recorded so it stays kept). Sharing is off, with its
reason and fix, when gh is missing, signed out, or has no usable account.

Sharing again PATCHes the same id with every file, a file the doc no longer has set to null, so the link stays; a gist
deleted on GitHub is created anew. The share is kept in $BLUEDOC_HOME/shares.json (0600) by the doc's path, never
beside the doc. unshare DELETEs the gist and forgets it, also when GitHub has it no more, and keeps it when gh fails.
A bluedoc-page.json over 10 MB is a 413 pointing to Export → HTML file, a deck a 400. The routes need the X-Bluedoc
header and the key, the GET too (it shows the link); its brief form is {share, rev, off}. No token reaches a route's
answer or the server's log. The link is https://bluedoc.ai/g/<code>, the gist id's bytes in base64url without padding
(32 hex: 22 characters, 20 hex: 14), any other id the long https://bluedoc.ai/g/#<user>/<id>; a share recorded with
the long link reads the short one. `serve.py share [--as L] [--move|--keep]` prints the notice, then the link and the
gist's URL."""
from __future__ import annotations

import base64
import http.client
import json
import os
import shutil
import stat
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote, urlsplit

from _support import Server, TempHome, free_port, load_json

import build
import gistbudget
import settings
import share

NO_GH = {"BLUEDOC_GH": "/nonexistent/gh"}   # no gh to run
PLAN, DESIGN, STATUS = "acme-saved-carts-plan", "acme-fit-design", "acme-status"
FILL_KEYS = {"__BLUEDOC_TITLE__", "__BLUEDOC_DOC__", "__BLUEDOC_HISTORY__", "__BLUEDOC_SCREENS__", "__BLUEDOC_LISTING__",
             "__BLUEDOC_STATE__", "__BLUEDOC_LIVE__", "__BLUEDOC_SNAPS__", "__BLUEDOC_PINS__", "__BLUEDOC_ANSWERS__"}
# acme-work: a member of acme-corp; acme-dev: gh's active one; acme-oss: no gist scope
THREE = "acme-work,acme-dev:active,acme-oss:nogist"
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def code(gist_id: str) -> str:
    """A gist id's short-link code, worked out here apart from share.link_for: its bytes in base64url, no padding."""
    return base64.urlsafe_b64encode(bytes.fromhex(gist_id)).rstrip(b"=").decode("ascii")


def acct(login: str, usable: bool = True, active: bool = False) -> dict:
    return {"login": login, "usable": usable, "active": active, "fix": None if usable else f"gh auth refresh -s gist -u {login}"}


def git_remote(folder: Path, url: str | None) -> None:
    """folder as a git repo with origin at url (None: no remote)."""
    run = lambda *a: subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(folder), *a],  # noqa: E731
                                    env={**os.environ, **GIT_ENV}, check=True, capture_output=True)
    run("init", "-q")
    if url:
        run("remote", "add", "origin", url)


class ShortLink(unittest.TestCase):
    def test_a_hex_id_is_its_bytes_in_base64url(self) -> None:
        cases = [("b21699001d737be2f6e6a242851a63da", "https://bluedoc.ai/g/shaZAB1ze-L25qJChRpj2g"),   # 32 hex: 22 characters
                 ("6cad326836d38bd3a7ae", "https://bluedoc.ai/g/bK0yaDbTi9Onrg"),   # 20 hex (an older gist): 14
                 ("ffff", "https://bluedoc.ai/g/__8")]
        for gist_id, link in cases:
            with self.subTest(gist_id=gist_id):
                self.assertEqual(share.link_for("acme-dev", gist_id), link)
                self.assertEqual(base64.urlsafe_b64decode(link.rsplit("/", 1)[1] + "==").hex(), gist_id, "it decodes back")

    def test_any_other_id_keeps_the_long_form(self) -> None:
        for gist_id in ("not-hex", "abc", "B21699001D737BE2F6E6A242851A63DA", ""):
            with self.subTest(gist_id=gist_id):
                self.assertEqual(share.link_for("acme-dev", gist_id), f"https://bluedoc.ai/g/#acme-dev/{gist_id}")

    def test_a_share_recorded_with_the_long_link_reads_the_short_one(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        gid, p = "b21699001d737be2f6e6a242851a63da", tmp.dir / "acme.bluedoc.json"
        with mock.patch.dict(os.environ, {"BLUEDOC_HOME": str(tmp.home)}):
            share._save({str(p.resolve()): {"id": gid, "user": "acme-dev", "link": f"https://bluedoc.ai/g/#acme-dev/{gid}",
                                            "url": f"https://gist.github.com/acme-dev/{gid}", "rev": "1", "at": "", "files": []}})
            self.assertEqual(share.record_of(p)["link"], "https://bluedoc.ai/g/shaZAB1ze-L25qJChRpj2g")


class StandInGh:
    """A TempHome with the examples, the stand-in gh as BLUEDOC_GH (TempHome's), and its env in os.environ while a test
    runs (for share.py called in process); share.py's account caches emptied."""

    def gh_setup(self, folder: str = "docs") -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples(folder)
        self.gh_env()

    def gh_env(self) -> None:
        """TempHome's stand-in gh (BLUEDOC_GH) in os.environ too, its gists in <tmp>/gh, one account (acme-dev); writes
        without share.py's second between them."""
        self.ghdir = Path(self.tmp.env["STANDIN_GH_DIR"])
        self.tmp.env.pop("GH_TOKEN", None)
        patch = mock.patch.dict(os.environ, {k: self.tmp.env[k] for k in ("BLUEDOC_GH", "STANDIN_GH_DIR", "BLUEDOC_HOME")})
        patch.start()
        self.addCleanup(patch.stop)
        for k in ("STANDIN_GH_ACCOUNTS", "STANDIN_GH_ORGS", "STANDIN_GH_AUTH", "STANDIN_GH_USER", "STANDIN_GH_FAIL",
                  "STANDIN_GH_REFUSE", "GH_TOKEN"):
            os.environ.pop(k, None)
        gap = mock.patch.object(share, "WRITE_GAP", 0)
        gap.start()
        self.addCleanup(gap.stop)
        self.forget()

    def forget_budget(self) -> None:
        """An empty gist-budget.json: the hour's updates and each doc's minute forgotten (the server reads it afresh)."""
        gistbudget.budget_file().unlink(missing_ok=True)

    def cli_server(self) -> None:
        """`serve.py share` starts a server as `open` does: on a free port of its own (BLUEDOC_PORT), stopped after."""
        self.tmp.env["BLUEDOC_PORT"] = str(free_port())
        self.addCleanup(lambda: self.tmp.run("serve.py", "stop"))

    def forget(self) -> None:
        """Empty share.py's caches of gh's accounts and of org memberships."""
        share._accounts_seen = None
        share._members.clear()

    def sign_in(self, spec: str, orgs: str = "") -> None:
        """The stand-in's accounts (STANDIN_GH_ACCOUNTS) and memberships (STANDIN_GH_ORGS), here and for subprocesses."""
        for k, v in (("STANDIN_GH_ACCOUNTS", spec), ("STANDIN_GH_ORGS", orgs)):
            os.environ[k] = self.tmp.env[k] = v
        self.forget()

    def doc(self, stem: str) -> Path:
        return (self.docs / f"{stem}.bluedoc.json").resolve()

    def calls(self) -> list[dict]:
        f = self.ghdir / "calls.jsonl"
        return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines()] if f.is_file() else []

    def gist(self, gist_id: str) -> tuple[dict, dict[str, str]]:
        d = self.ghdir / "gists" / gist_id
        return (json.loads((d / "meta.json").read_text(encoding="utf-8")),
                {f.name: f.read_text(encoding="utf-8") for f in sorted((d / "files").iterdir())})

    def shares(self) -> dict:
        f = share.shares_file()
        return load_json(f) if f.is_file() else {}

    def share_as(self, stem: str, budget: bool = False, **kw) -> dict:
        """share.share of the doc in the examples' project (self.docs); the budget forgotten first unless budget."""
        if not budget:
            self.forget_budget()
        return share.share(self.doc(stem), self.docs, kw.pop("remote", None), **kw)


class Bundle(StandInGh, unittest.TestCase):
    def setUp(self) -> None:
        self.gh_setup()

    def test_the_page_file_fills_the_template_as_build_o_does_without_history(self) -> None:
        template = build.TEMPLATE.read_text(encoding="utf-8")
        for stem, media, screens in ((PLAN, 1, 0), (DESIGN, 0, 11)):
            with self.subTest(stem=stem):
                p = self.doc(stem)
                files, doc, what = share.gist_files(p)
                screens_file = ["bluedoc-screens.json"] if screens else []
                self.assertEqual(sorted(files), sorted([f"{stem}.bluedoc.json", "bluedoc-page.json", *screens_file]), "no history file")
                self.assertEqual(files[f"{stem}.bluedoc.json"], p.read_text(encoding="utf-8"), "the doc, verbatim")
                page = json.loads(files["bluedoc-page.json"])
                self.assertEqual(sorted(page), ["bluedoc", "boardGeo", "fill", "name", "rev", "title", "version"])
                self.assertEqual((page["bluedoc"], page["version"], page["name"], page["title"], page["rev"]),
                                 ("share/1", build.skill_version(), stem, doc["title"], doc["meta"]["rev"]))
                self.assertEqual(set(page["fill"]), FILL_KEYS)
                hist = json.loads(page["fill"]["__BLUEDOC_HISTORY__"])
                self.assertIn([r["rev"] for r in (hist or {}).get("revs", [])], ([], [doc["meta"]["rev"]]), "the current revision only")
                self.assertTrue(page["boardGeo"], "a plan's canvas and a design's board need board-geo.js")
                filled = build.fill_page(template, {**page["fill"], build.BOARD_GEO_SLOT: build.board_geo_text()})
                self.assertEqual(filled, build.standalone(doc, p, None, template, problems=[]))
                self.assertEqual(len(json.loads(page["fill"]["__BLUEDOC_SCREENS__"]) or {}), screens)
                self.assertEqual(what, {"media": media, "screens": screens})
        status = self.doc(STATUS)
        page = json.loads(share.gist_files(status)[0]["bluedoc-page.json"])
        self.assertFalse(page["boardGeo"], "a doc without a board or a canvas")
        self.assertEqual(build.fill_page(template, {**page["fill"], build.BOARD_GEO_SLOT: ""}),
                         build.standalone(load_json(status), status, None, template, problems=[]))

    def test_a_design_s_screen_sources_go_in_bluedoc_screens_json(self) -> None:
        p = self.doc(DESIGN)
        doc = load_json(p)
        files = share.gist_files(p)[0]
        screens = json.loads(files["bluedoc-screens.json"])
        want = {f.relative_to(p.parent).as_posix(): f.read_text(encoding="utf-8") for f in build.screen_paths(doc, p).values() if f.is_file()}
        self.assertEqual(screens, want, "every screen file and icon layer, by its path from the doc's folder, as its text")
        self.assertTrue(any(k.endswith(".html") for k in screens) and all(not k.startswith(("/", "..")) for k in screens))
        self.assertNotIn("bluedoc-screens.json", share.gist_files(self.doc(PLAN))[0], "a doc without screen files has none")
        with mock.patch.object(share, "MAX_PAGE_BYTES", len(files["bluedoc-page.json"].encode()) + 10), \
                mock.patch.object(share, "screens_file", return_value="x" * (len(files["bluedoc-page.json"].encode()) + 11)), \
                self.assertRaises(share.ShareError) as cm:
            share.gist_files(p)
        self.assertEqual(cm.exception.status, 413, "the screens' file is held to the same 10 MB")

    def test_a_doc_without_a_rev(self) -> None:
        p = self.doc(PLAN)
        doc = load_json(p)
        del doc["meta"]["rev"]
        p.write_text(build.dump_doc(doc), encoding="utf-8")
        files, _, what = share.gist_files(p)
        self.assertEqual(sorted(files), [f"{PLAN}.bluedoc.json", "bluedoc-page.json"])
        self.assertIsNone(json.loads(files["bluedoc-page.json"])["rev"])

    def test_a_deck_or_a_listing_is_refused(self) -> None:
        for stem in ("acme-fit-deck", "acme-fit-listing"):
            with self.subTest(stem=stem):
                with self.assertRaises(share.ShareError) as cm:
                    self.share_as(stem)
                self.assertEqual(cm.exception.status, 400)
        self.assertEqual(self.calls(), [], "refused before gh runs")


class Accounts(StandInGh, unittest.TestCase):
    def setUp(self) -> None:
        self.gh_setup()

    def test_gh_auth_status_lists_each_account_with_its_scope(self) -> None:
        cases = [("acme-dev", [acct("acme-dev", active=True)]),
                 ("acme-work,acme-dev:active", [acct("acme-work"), acct("acme-dev", active=True)]),
                 (THREE, [acct("acme-work"), acct("acme-dev", active=True), acct("acme-oss", usable=False)]),
                 ("acme-pat:pat,acme-old:failed", [acct("acme-pat", active=True), acct("acme-old", usable=False)])]
        for spec, want in cases:
            with self.subTest(spec=spec):
                self.sign_in(spec)
                self.assertEqual(share.accounts(), want)
        self.assertTrue(all(c["argv"] == ["auth", "status", "--hostname", "github.com"] and c["as"] is None for c in self.calls()))

    def test_an_older_gh_with_one_account(self) -> None:
        text = ("github.com\n  ✓ Logged in to github.com as acme-dev (oauth_token)\n  ✓ Git operations for github.com "
                "configured to use https protocol.\n  ✓ Token: *******************\n  ✓ Token scopes: gist, repo\n")
        self.assertEqual(share.parse_status(text), [acct("acme-dev", active=True)])

    def test_sharing_is_off_without_gh_a_sign_in_or_a_usable_account(self) -> None:
        cases = [(NO_GH, {"reason": "gh, the GitHub CLI, isn't installed", "fix": "brew install gh"}, 501),
                 ({"STANDIN_GH_AUTH": "signed-out"}, {"reason": "gh, the GitHub CLI, isn't signed in to GitHub",
                                                      "fix": "gh auth login -s gist"}, 502),
                 ({"STANDIN_GH_AUTH": "no-gist"}, {"reason": "gh's GitHub account acme-dev lacks the gist scope",
                                                   "fix": "gh auth refresh -s gist -u acme-dev"}, 502),
                 ({"STANDIN_GH_ACCOUNTS": "acme-dev:nogist,acme-oss:nogist:active"},
                  {"reason": "none of gh's GitHub accounts has the gist scope", "fix": "gh auth refresh -s gist -u acme-oss"}, 502)]
        for env, off, status in cases:
            with self.subTest(env=env), mock.patch.dict(os.environ, env):
                self.forget()
                self.assertEqual(share.sharing_state()[1], off)
                self.assertEqual(share.view(self.doc(PLAN), self.docs)["off"], off)
                with self.assertRaises(share.ShareError) as cm:
                    self.share_as(PLAN)
                self.assertEqual(cm.exception.status, status)
                self.assertIn(f"`{off['fix']}`", str(cm.exception))
        self.forget()
        self.assertEqual(share.sharing_state(), ([acct("acme-dev", active=True)], None))
        self.assertEqual(self.shares(), {})

    def test_the_brief_answer_reads_gh_once_a_minute(self) -> None:
        p = self.doc(PLAN)
        self.assertEqual(share.view(p, brief=True), {"share": None, "rev": "1", "off": None, "queued": None})
        share.view(p, brief=True)
        self.assertEqual(len(self.calls()), 1, "cached")
        share.view(p)
        self.assertEqual(len(self.calls()), 2, "the sheet asks gh again")


class Preselect(StandInGh, unittest.TestCase):
    def setUp(self) -> None:
        self.gh_setup()

    def pick(self, remote: str | None, project: Path | None = None, rec: dict | None = None) -> dict | None:
        return share.choose(project or self.docs, remote, share.accounts(), rec)

    def test_one_usable_account_is_the_only_one(self) -> None:
        self.sign_in("acme-dev:active,acme-oss:nogist")
        self.assertEqual(self.pick("acme-corp/shop"), {"login": "acme-dev", "why": "only"})
        v = share.view(self.doc(PLAN), self.docs, "acme-corp/shop")
        self.assertEqual((v["ask"], v["account"]), (False, {"login": "acme-dev", "why": "only"}))
        self.assertEqual([c["argv"][:2] for c in self.calls()], [["auth", "status"]] * 2, "no lookups")

    def test_the_remote_owner_or_a_member_of_its_org(self) -> None:
        self.sign_in(THREE, orgs="acme-work=acme-corp")
        self.assertEqual(self.pick("acme-corp/shop"), {"login": "acme-work", "why": "remote"})
        member = [c for c in self.calls() if c["argv"][:2] == ["api", "user/memberships/orgs/acme-corp"]]
        self.assertEqual([c["as"] for c in member], ["acme-work"], "asked as that account, the first in gh's order")
        self.pick("acme-corp/shop")
        self.assertEqual(len([c for c in self.calls() if c["argv"][0] == "api"]), 1, "cached")
        self.assertEqual(self.pick("acme-dev/tools"), {"login": "acme-dev", "why": "remote"}, "the owner itself")
        self.assertEqual(self.pick("acme-labs/site"), {"login": "acme-dev", "why": "active"}, "no one's: gh's active one")
        self.assertEqual(self.pick(None), {"login": "acme-dev", "why": "active"})
        v = share.view(self.doc(PLAN), self.docs, "acme-corp/shop")
        self.assertEqual((v["ask"], v["account"], v["mismatch"], v["off"]), (True, {"login": "acme-work", "why": "remote"}, None, None))
        self.assertEqual(v["accounts"], [acct("acme-work"), acct("acme-dev", active=True), acct("acme-oss", usable=False)])

    def test_the_project_account_then_the_gist_account_win(self) -> None:
        self.sign_in(THREE, orgs="acme-work=acme-corp")
        share.set_project_account(self.docs, "acme-dev")
        self.assertEqual(self.pick("acme-corp/shop"), {"login": "acme-dev", "why": "project"})
        self.assertEqual(settings.load()["shareAs"], {str(self.docs): "acme-dev"})
        share.set_project_account(self.docs, None)
        self.assertNotIn("shareAs", settings.load())
        self.assertEqual(self.pick("acme-corp/shop", rec={"user": "acme-dev"}), {"login": "acme-dev", "why": "project"})
        share.set_project_account(self.docs, "acme-oss")
        self.assertEqual(self.pick(None)["why"], "active", "an account without the gist scope is no pick")

    def test_the_remote_comes_from_git(self) -> None:
        cases = [("git@github.com:acme-corp/shop.git", "acme-corp/shop"), ("https://github.com/acme-corp/shop", "acme-corp/shop"),
                 ("git@github.com-work:acme-corp/shop.git", "acme-corp/shop"), ("https://gitlab.com/acme-corp/shop.git", None),
                 (None, None)]
        for i, (url, want) in enumerate(cases):
            with self.subTest(url=url):
                d = self.tmp.dir / f"repo{i}" / "docs"
                d.mkdir(parents=True)
                git_remote(d.parent, url)
                self.assertEqual(share.remote_of(d), want)
        self.assertIsNone(share.remote_of(self.docs), "not a repo")


class Gists(StandInGh, unittest.TestCase):
    def setUp(self) -> None:
        self.gh_setup()

    def test_create_then_share_again_patches_the_same_gist(self) -> None:
        p = self.doc(PLAN)
        before = sorted(x.name for x in self.docs.iterdir())
        res = self.share_as(PLAN)
        rec, gid = res["share"], res["share"]["id"]
        self.assertTrue(res["created"])
        self.assertEqual([(c["argv"][:2], c["as"]) for c in self.calls()],
                         [(["auth", "status"], None), (["auth", "token"], None), (["api", "-i"], "acme-dev")])
        self.assertEqual(self.calls()[1]["argv"], ["auth", "token", "--hostname", "github.com", "--user", "acme-dev"])
        create = self.calls()[2]
        self.assertEqual(create["argv"], ["api", "-i", "-X", "POST", "gists", "--input", "-"], "GitHub's answer read, headers too")
        body = json.loads(create["stdin"])
        self.assertEqual((body["description"], body["public"], sorted(body["files"])),
                         ("bluedoc: Acme Shop: saved carts", False, [f"{PLAN}.bluedoc.json", "bluedoc-page.json"]))
        meta, files = self.gist(gid)
        self.assertFalse(meta["public"])
        self.assertEqual(sorted(files), rec["files"])
        self.assertEqual(rec["link"], f"https://bluedoc.ai/g/{code(gid)}")
        self.assertEqual(len(code(gid)), 22)
        self.assertEqual((rec["user"], rec["url"]), ("acme-dev", f"https://gist.github.com/acme-dev/{gid}"))
        self.assertEqual(rec["rev"], load_json(p)["meta"]["rev"])
        self.assertEqual(self.shares(), {str(p): rec})
        self.assertEqual(stat.S_IMODE(share.shares_file().stat().st_mode), 0o600)
        self.assertEqual(sorted(x.name for x in self.docs.iterdir()), before, "nothing about the share beside the doc")
        self.assertNotIn(gid, p.read_text(encoding="utf-8"))
        self.assertNotIn("shareAs", settings.load(), "one account: nothing to remember")
        # a new rev, then Update: the same gist, every file, the description kept
        r = self.tmp.run("build.py", "patch", p, "doc", "--set", "subtitle=Saved carts, rev two")
        self.assertEqual(r.returncode, 0, r.stderr)
        (self.ghdir / "gists" / gid / "files" / "stale.txt").write_text("from an earlier share", encoding="utf-8")
        res2 = self.share_as(PLAN)
        self.assertFalse(res2["created"])
        self.assertEqual(res2["share"]["id"], gid)
        self.assertEqual(res2["share"]["link"], rec["link"])
        self.assertEqual(res2["share"]["rev"], load_json(p)["meta"]["rev"])
        self.assertNotEqual(res2["share"]["rev"], rec["rev"])
        later = self.calls()[3:]
        self.assertEqual([(c["argv"], c["as"]) for c in later],
                         [(["auth", "status", "--hostname", "github.com"], None),
                          (["auth", "token", "--hostname", "github.com", "--user", "acme-dev"], None),
                          (["api", f"gists/{gid}"], "acme-dev"), (["api", "-i", "-X", "PATCH", f"gists/{gid}", "--input", "-"], "acme-dev")])
        body = json.loads(later[3]["stdin"])
        self.assertEqual(body["description"], "bluedoc: Acme Shop: saved carts")
        self.assertIsNone(body["files"]["stale.txt"], "a file the share no longer has goes")
        _, files = self.gist(gid)
        self.assertEqual(sorted(files), res2["share"]["files"])
        self.assertEqual(files[f"{PLAN}.bluedoc.json"], p.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(files["bluedoc-page.json"])["rev"], res2["share"]["rev"])

    def test_every_gist_call_runs_as_the_chosen_account(self) -> None:
        self.sign_in(THREE, orgs="acme-work=acme-corp")
        res = self.share_as(PLAN, remote="acme-corp/shop")
        gid = res["share"]["id"]
        self.assertEqual((res["as"], res["share"]["user"]), ("acme-work", "acme-work"), "not gh's active acme-dev")
        self.assertEqual(self.gist(gid)[0]["owner"], "acme-work")
        self.assertEqual(settings.load()["shareAs"], {str(self.docs): "acme-work"}, "the first share's pick is the project's")
        writes = [c for c in self.calls() if c["argv"][0] in ("gist", "api") and "memberships" not in c["argv"][1]]
        self.assertEqual([c["as"] for c in writes], ["acme-work"])
        self.assertFalse([c for c in self.calls() if c["argv"][:2] == ["auth", "switch"]], "gh's active account stays")
        # another doc in the project: its account, without a lookup
        n = len(self.calls())
        self.assertEqual(self.share_as(STATUS, remote="acme-corp/shop")["share"]["user"], "acme-work")
        self.assertFalse([c for c in self.calls()[n:] if "memberships" in " ".join(c["argv"])])
        # Stop sharing: as the account the gist is on
        rec = share.unshare(self.doc(PLAN))
        self.assertEqual(rec["id"], gid)
        self.assertEqual((self.calls()[-1]["argv"], self.calls()[-1]["as"]), (["api", "-i", "-X", "DELETE", f"gists/{gid}"], "acme-work"))
        self.assertFalse((self.ghdir / "gists" / gid).exists())

    def test_as_sets_the_project_account(self) -> None:
        self.sign_in(THREE)
        a = self.share_as(PLAN, as_="acme-work")
        self.assertEqual(a["share"]["user"], "acme-work")
        self.assertEqual(share.project_account(self.docs), "acme-work")
        self.assertEqual(self.share_as(STATUS)["share"]["user"], "acme-work", "remembered")
        b = self.share_as(DESIGN, as_="ACME-DEV")
        self.assertEqual((b["share"]["user"], share.project_account(self.docs)), ("acme-dev", "acme-dev"), "gh's spelling")
        for login, says in (("acme-oss", "acme-oss lacks the gist scope: run `gh auth refresh -s gist -u acme-oss`"),
                            ("acme-nobody", "gh isn't signed in as acme-nobody")):
            with self.subTest(login=login), self.assertRaises(share.ShareError) as cm:
                self.share_as(PLAN, as_=login)
            self.assertEqual(cm.exception.status, 400)
            self.assertIn(says, str(cm.exception))
        self.assertEqual(share.project_account(self.docs), "acme-dev", "a refused account isn't kept")

    def test_a_gist_on_another_account_waits_for_move_or_keep(self) -> None:
        self.sign_in(THREE)
        p = self.doc(PLAN)
        old = self.share_as(PLAN, as_="acme-dev")["share"]
        share.set_project_account(self.docs, "acme-work")
        v = share.view(p, self.docs)
        self.assertEqual((v["account"], v["mismatch"]), ({"login": "acme-work", "why": "project"}, {"gist": "acme-dev", "project": "acme-work"}))
        n = len(self.calls())
        with self.assertRaises(share.Mismatch) as cm:
            self.share_as(PLAN)
        self.assertEqual((cm.exception.status, cm.exception.mismatch), (409, {"gist": "acme-dev", "project": "acme-work"}))
        self.assertFalse([c for c in self.calls()[n:] if c["argv"][0] in ("gist", "api")], "nothing written")
        with self.assertRaises(share.ShareError) as cm:
            self.share_as(PLAN, move=True, keep=True)
        self.assertEqual(cm.exception.status, 400)
        # keep: updated as acme-dev, the link stays, and it stays kept
        n = len(self.calls())
        kept = self.share_as(PLAN, keep=True)
        self.assertEqual((kept["share"]["id"], kept["share"]["user"], kept["share"]["kept"], kept["moved"]),
                         (old["id"], "acme-dev", "acme-work", False))
        self.assertEqual({c["as"] for c in self.calls()[n:] if c["argv"][0] == "api"}, {"acme-dev"})
        self.assertIsNone(share.view(p, self.docs)["mismatch"])
        self.assertEqual(self.share_as(PLAN)["share"]["id"], old["id"], "no 409 once kept")
        # the project moves on to acme-dev and back: asked again
        share.set_project_account(self.docs, "acme-dev")
        self.share_as(PLAN)
        share.set_project_account(self.docs, "acme-work")
        self.assertIsNotNone(share.view(p, self.docs)["mismatch"])
        # move: a new gist on acme-work, the old one deleted as acme-dev
        n = len(self.calls())
        moved = self.share_as(PLAN, move=True)
        new = moved["share"]
        self.assertTrue(moved["moved"] and moved["relinked"] and moved["created"])
        self.assertNotIn("warning", moved)
        self.assertEqual(new["user"], "acme-work")
        self.assertNotEqual((new["id"], new["link"]), (old["id"], old["link"]))
        self.assertNotIn("kept", new)
        self.assertEqual([(c["argv"][:5], c["as"]) for c in self.calls()[n:] if c["argv"][0] in ("gist", "api") and "-i" in c["argv"]],
                         [(["api", "-i", "-X", "POST", "gists"], "acme-work"), (["api", "-i", "-X", "DELETE", f"gists/{old['id']}"], "acme-dev")])
        self.assertFalse((self.ghdir / "gists" / old["id"]).exists())
        self.assertEqual(self.gist(new["id"])[0]["owner"], "acme-work")
        self.assertIsNone(share.view(p, self.docs)["mismatch"])

    def test_a_move_that_cant_delete_the_old_gist_says_so(self) -> None:
        self.sign_in(THREE)
        old = self.share_as(PLAN, as_="acme-dev")["share"]
        share.set_project_account(self.docs, "acme-work")
        with mock.patch.dict(os.environ, {"STANDIN_GH_FAIL": "DELETE"}):
            res = self.share_as(PLAN, move=True)
        self.assertEqual(res["share"]["user"], "acme-work")
        self.assertIn(f"the old gist {old['id']} on acme-dev is still there", res["warning"])
        self.assertEqual(self.shares()[str(self.doc(PLAN))]["id"], res["share"]["id"])

    def test_an_old_record_shares_and_stops_as_its_user(self) -> None:
        # a share from before accounts: made as gh's active account then, acme-dev; acme-work is active now
        p = self.doc(PLAN)
        gid = self.share_as(PLAN)["share"]["id"]
        data = self.shares()
        self.assertEqual(set(data[str(p)]), {"id", "user", "link", "url", "rev", "at", "files", "answers", "answersHash"})
        for k in ("answers", "answersHash"):   # as a share made before accounts recorded it
            del data[str(p)][k]
        share._save(data)
        self.sign_in("acme-work:active,acme-dev")
        v = share.view(p, self.docs)
        self.assertEqual((v["account"], v["mismatch"]), ({"login": "acme-dev", "why": "project"}, None))
        n = len(self.calls())
        self.assertEqual(self.share_as(PLAN)["share"]["id"], gid)
        self.assertEqual({c["as"] for c in self.calls()[n:] if c["argv"][0] == "api"}, {"acme-dev"})
        share.unshare(p)
        self.assertEqual(self.calls()[-1]["as"], "acme-dev")
        self.assertEqual(self.shares(), {})

    def test_a_gist_deleted_on_github_is_created_anew(self) -> None:
        p = self.doc(PLAN)
        first = self.share_as(PLAN)["share"]["id"]
        shutil.rmtree(self.ghdir / "gists" / first)   # deleted on github.com
        res = self.share_as(PLAN)
        self.assertTrue(res["created"] and res["relinked"])
        self.assertFalse(res["moved"])
        self.assertNotEqual(res["share"]["id"], first)
        self.assertEqual(self.shares()[str(p)]["id"], res["share"]["id"])

    def test_unshare_deletes_the_gist_and_forgets_it(self) -> None:
        p = self.doc(PLAN)
        gid = self.share_as(PLAN)["share"]["id"]
        rec = share.unshare(p)
        self.assertEqual(rec["id"], gid)
        self.assertEqual((self.calls()[-1]["argv"], self.calls()[-1]["as"]), (["api", "-i", "-X", "DELETE", f"gists/{gid}"], "acme-dev"))
        self.assertFalse((self.ghdir / "gists" / gid).exists())
        self.assertEqual(self.shares(), {})
        self.assertIsNone(share.unshare(p), "not shared: nothing to do")
        # gone on GitHub already: the DELETE answers 404, and the share is forgotten all the same
        gid = self.share_as(PLAN)["share"]["id"]
        shutil.rmtree(self.ghdir / "gists" / gid)
        self.assertEqual(share.unshare(p)["id"], gid)
        self.assertEqual(self.shares(), {})
        # its account signed out of gh: the share is kept
        gid = self.share_as(PLAN)["share"]["id"]
        self.sign_in("acme-work")
        with self.assertRaises(share.ShareError) as cm:
            share.unshare(p)
        self.assertIn("gh isn't signed in as acme-dev", str(cm.exception))
        self.assertEqual(self.shares()[str(p)]["id"], gid)
        # the CLI
        self.sign_in("acme-dev")
        r = self.tmp.run("serve.py", "unshare", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"stopped sharing: gist {gid} deleted, https://bluedoc.ai/g/{code(gid)} no longer opens\n")
        self.assertEqual(self.shares(), {})

    def test_gh_failures_say_what_happened(self) -> None:
        p = self.doc(PLAN)
        with mock.patch.dict(os.environ, {"STANDIN_GH_FAIL": "POST"}), self.assertRaises(share.ShareError) as cm:
            self.share_as(PLAN)
        self.assertEqual(cm.exception.status, 502)
        self.assertIn("gh api -X failed: gh: Server Error (HTTP 500)", str(cm.exception))
        self.assertEqual(self.shares(), {})
        gid = self.share_as(PLAN)["share"]["id"]
        with mock.patch.dict(os.environ, {"STANDIN_GH_FAIL": "DELETE"}), self.assertRaises(share.ShareError):
            share.unshare(p)
        self.assertEqual(self.shares()[str(p)]["id"], gid, "a failed delete keeps the share")

    def test_a_page_over_10_mb_is_refused(self) -> None:
        with mock.patch.object(share, "MAX_PAGE_BYTES", 20_000), self.assertRaises(share.ShareError) as cm:
            self.share_as(PLAN)
        self.assertEqual(cm.exception.status, 413)
        self.assertRegex(str(cm.exception), r"would be 0\.0 MB, over the 10 MB .*Export → HTML file")
        self.assertEqual([c["argv"][:2] for c in self.calls()], [["auth", "status"]], "gh checked, nothing created")

    def test_the_cli_prints_the_notice_and_the_link(self) -> None:
        self.cli_server()
        p = self.doc(DESIGN)
        r = self.tmp.run("serve.py", "share", p, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        rec = self.shares()[str(p)]
        self.assertEqual(lines[0], share.NOTICE, "no colour when stdout isn't a terminal")
        self.assertEqual(lines[1], "secret gist created as acme-dev, rev C: 0 media files, 11 screens")
        self.assertEqual(lines[2:], [f"link: https://bluedoc.ai/g/{code(rec['id'])}", f"gist: https://gist.github.com/acme-dev/{rec['id']}",
                                     "budget: 1 of 90 used in the last hour on acme-dev; GitHub allows about 100 gist updates an hour"])
        self.assertIn(f"shared {p} as acme-dev: {rec['link']}", (self.tmp.home / "server.log").read_text(encoding="utf-8"),
                      "it went through the server, which counts the account's updates")
        tty = type("Tty", (), {"isatty": lambda self: True})()
        with mock.patch.dict(os.environ):
            os.environ.pop("NO_COLOR", None)
            self.assertEqual(share.red(share.NOTICE, tty), f"\x1b[1;31m{share.NOTICE}\x1b[0m", "red on a terminal")
            os.environ["NO_COLOR"] = "1"
            self.assertEqual(share.red(share.NOTICE, tty), share.NOTICE)
        self.forget_budget()
        r = self.tmp.run("serve.py", "share", p, timeout=120)
        self.assertIn("secret gist updated as acme-dev", r.stdout)
        # --as makes another account the project's: the gist on acme-dev waits for --move or --keep. The server shares
        # with the gh it started with: a new sign-in, a new server
        self.sign_in(THREE)
        self.tmp.run("serve.py", "stop")
        r = self.tmp.run("serve.py", "share", p, "--as", "acme-work", timeout=120)
        self.assertEqual(r.returncode, 1)
        self.assertIn("the gist is on acme-dev and this project shares as acme-work", r.stderr)
        self.assertIn("run again with --move or --keep", r.stderr)
        self.assertEqual(share.project_account(self.docs), "acme-work", "serve.py share finds the project: the doc's folder")
        self.forget_budget()
        r = self.tmp.run("serve.py", "share", p, "--keep", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("secret gist updated as acme-dev", r.stdout)
        self.forget_budget()
        r = self.tmp.run("serve.py", "share", p, "--as", "acme-work", "--move", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("secret gist moved (a new gist, the old one deleted: the link changed) as acme-work", r.stdout)
        self.assertEqual(self.tmp.run("serve.py", "share", p, "--move", "--keep").returncode, 2)
        self.assertEqual(self.tmp.run("serve.py", "share", p, "--answers", "picks,secrets").returncode, 2)
        self.tmp.env["STANDIN_GH_ACCOUNTS"] = "acme-dev:nogist"
        self.tmp.run("serve.py", "stop")
        r = self.tmp.run("serve.py", "share", p, timeout=120)
        self.assertEqual(r.returncode, 1)
        self.assertIn("gh auth refresh -s gist -u acme-dev", r.stderr)


class Budget(StandInGh, unittest.TestCase):
    """The budget around share.share, against a fake clock (gistbudget.clock) and the stand-in gh refusing
    (STANDIN_GH_REFUSE); send() is what the server's queue does when an update is due."""

    def setUp(self) -> None:
        self.gh_setup()
        self.now = float(int(time.time()))
        c = mock.patch.object(gistbudget, "clock", lambda: self.now)
        c.start()
        self.addCleanup(c.stop)

    def send(self, stem: str) -> dict:
        """The queue sending the doc's queued update (serve.send_queued without the server)."""
        q = share.queued_of(self.doc(stem))
        self.assertIsNotNone(q, "a queued update")
        return share.share(self.doc(stem), self.docs, None, q.get("as"), move=q.get("move") is True, keep=q.get("keep") is True,
                           answers=q.get("answers"), from_queue=True)

    def wait(self, res: dict) -> float | None:
        """Seconds until a queued answer's update goes out (None: paused)."""
        at = share._epoch(res["queued"]["at"])
        return None if at is None else at - self.now

    def writes(self) -> list:
        return [c["argv"] for c in self.calls() if c["argv"][:2] == ["api", "-i"]]

    def test_github_s_refusals_set_the_wait_and_the_fourth_pauses(self) -> None:
        p = self.doc(PLAN)
        gid = self.share_as(PLAN)["share"]["id"]
        rev_shared = self.shares()[str(p)]["rev"]
        # 429 with retry-after 300: the update waits 300 s, read with -i; the link keeps its rev
        self.now += 61
        os.environ["STANDIN_GH_REFUSE"] = "429:retry-after=300"
        res = share.share(p, self.docs)
        self.assertEqual((res["queued"]["why"], self.wait(res)), ("retry", 300))
        self.assertEqual(self.writes()[-1], ["api", "-i", "-X", "PATCH", f"gists/{gid}", "--input", "-"])
        self.assertEqual(json.loads(self.gist(gid)[1]["bluedoc-page.json"])["rev"], rev_shared)
        self.assertEqual(share.view(p, self.docs)["queued"]["why"], "retry")
        # a share while it waits makes no gh call
        n = len(self.calls())
        self.assertEqual(share.share(p, self.docs)["queued"]["why"], "retry")
        self.assertEqual(len(self.calls()), n)
        # at its time a 403 with x-ratelimit-remaining 0: it waits for the reset
        self.now += 300
        os.environ["STANDIN_GH_REFUSE"] = f"403:x-ratelimit-remaining=0,x-ratelimit-reset={int(self.now) + 900}"
        self.assertEqual(self.wait(self.send(PLAN)), 900)
        # then GitHub takes it: sent, the queue empty, the run of refusals over
        self.now += 900
        del os.environ["STANDIN_GH_REFUSE"]
        self.assertEqual(self.send(PLAN)["share"]["id"], gid)
        self.assertIsNone(share.queued_of(p))
        self.assertEqual(gistbudget.status("acme-dev")["refusals"], 0)
        # no header: 1 min, then 2, then 4; the 4th in a row pauses the account
        self.now += 3600
        os.environ["STANDIN_GH_REFUSE"] = "403"   # GitHub's secondary limit: "API rate limit exceeded" alone
        waits = [self.wait(share.share(p, self.docs))]
        for _ in range(3):
            self.now += waits[-1]
            waits.append(self.wait(self.send(PLAN)))
        self.assertEqual(waits, [60, 120, 240, None])
        v = share.view(p, self.docs)
        self.assertEqual((v["queued"]["why"], v["queued"]["at"], v["budget"]["paused"]), ("paused", None, True))
        # paused: time passes, shares make no gh call, nothing goes out (the server's queue skips a paused account)
        self.now += 7200
        n = len(self.calls())
        self.assertEqual(share.share(p, self.docs)["queued"]["why"], "paused")
        self.assertEqual(gistbudget.due("acme-dev", str(p)), (None, "paused"))
        self.assertEqual(len(self.calls()), n)
        # the reader resumes: it goes out
        del os.environ["STANDIN_GH_REFUSE"]
        self.assertEqual(share.resume(p), "acme-dev")
        self.assertNotIn("queued", self.send(PLAN))
        self.assertIsNone(share.queued_of(p))

    def test_another_403_stays_an_error(self) -> None:
        self.share_as(PLAN)
        self.now += 61
        os.environ["STANDIN_GH_REFUSE"] = "403:message=Resource not accessible by integration,x-ratelimit-remaining=4000"
        with self.assertRaises(share.ShareError) as cm:
            share.share(self.doc(PLAN), self.docs)
        self.assertEqual(cm.exception.status, 502)
        self.assertIn("gh api -X failed: gh: Resource not accessible by integration (HTTP 403)", str(cm.exception))
        self.assertIsNone(share.queued_of(self.doc(PLAN)))
        self.assertEqual(gistbudget.status("acme-dev")["refusals"], 0)

    def test_past_90_an_update_waits_and_goes_out_with_the_rev_it_was_asked_for(self) -> None:
        p = self.doc(PLAN)
        gid = self.share_as(PLAN)["share"]["id"]
        for i in range(89):   # with the share above: 90 in the hour, the oldest 1000 s ago
            gistbudget.sent("acme-dev", f"/elsewhere/{i}.bluedoc.json", now=self.now - 1000 + i)
        r = self.tmp.run("build.py", "patch", p, "doc", "--set", "subtitle=Saved carts, rev two")
        self.assertEqual(r.returncode, 0, r.stderr)
        asked = load_json(p)["meta"]["rev"]
        self.now += 120
        n = len(self.writes())
        res = share.share(p, self.docs)   # Update pressed at `asked`
        self.assertEqual((res["queued"]["why"], self.wait(res), res["budget"]["used"], res["queued"]["rev"]), ("hour", 3600 - 1000 - 120, 90, asked))
        self.assertEqual(stat.S_IMODE(share.pin_file(p).stat().st_mode), 0o600, "its files wait beside shares.json, private")
        for _ in range(4):   # more shares while it waits: no gh call
            self.assertEqual(share.share(p, self.docs)["queued"]["why"], "hour")
        self.assertEqual(len(self.writes()), n)
        # two patches meanwhile: each says the update waits without it; the link stays where the user put it
        for sub in ("rev three", "rev four"):
            r = self.tmp.run("build.py", "patch", p, "doc", "--set", f"subtitle=Saved carts, {sub}")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertRegex(r.stdout.splitlines()[-1], rf"^rev {asked} is queued for \d\d:\d\d; this patch waits for the user's next update "
                                                        r"\(90 of 90 used this hour\)$")
        rev = load_json(p)["meta"]["rev"]
        self.assertNotEqual(rev, asked)
        self.assertEqual(share.view(p, self.docs)["queued"]["rev"], asked)
        self.now += self.wait(share.view(p, self.docs))
        res = self.send(PLAN)
        self.assertEqual((res["share"]["id"], res["share"]["rev"]), (gid, asked))
        self.assertEqual(len(self.writes()), n + 1, "one update for five shares and two patches")
        page = json.loads(self.gist(gid)[1]["bluedoc-page.json"])
        self.assertEqual((page["rev"], json.loads(self.gist(gid)[1][f"{PLAN}.bluedoc.json"])["meta"]["rev"]), (asked, asked),
                         "the rev the user pressed Update at went out, not the patches since")
        self.assertFalse(share.pin_file(p).exists(), "sent: its files go")
        v = share.view(p, self.docs)
        self.assertEqual((v["share"]["rev"], v["rev"], v["queued"]), (asked, rev, None), "the doc is newer than its share again")
        # a doc's minute: the next share of it waits 60 s, another doc's goes at once (the hour has room again)
        self.now += 1
        self.assertEqual(self.wait(share.share(p, self.docs)), 59)
        self.assertNotIn("queued", share.share(self.doc(STATUS), self.docs))

    def test_a_share_while_one_waits_puts_the_doc_as_it_is_now_in_it(self) -> None:
        p = self.doc(PLAN)
        gid = self.share_as(PLAN)["share"]["id"]
        self.now += 10
        first = share.share(p, self.docs)["queued"]
        self.assertEqual((first["why"], first["rev"]), ("spacing", "1"))
        self.assertEqual(self.tmp.run("build.py", "patch", p, "doc", "--set", "subtitle=Saved carts, rev two").returncode, 0)
        rev = load_json(p)["meta"]["rev"]
        self.assertEqual(share.share(p, self.docs)["queued"]["rev"], rev, "asked again: the doc as it is now")
        self.now += 60
        self.assertEqual(self.send(PLAN)["share"]["rev"], rev)
        self.assertEqual(json.loads(self.gist(gid)[1]["bluedoc-page.json"])["rev"], rev)
        # dropped: unshare (and a queued update the queue couldn't send) leave no files behind
        self.now += 10
        share.share(p, self.docs)
        self.assertTrue(share.pin_file(p).exists())
        share.drop_failed(p, "gh failed")
        self.assertFalse(share.pin_file(p).exists())
        share.share(p, self.docs)
        share.unshare(p)
        self.assertFalse(share.pin_file(p).exists())

    def test_a_delete_never_waits(self) -> None:
        p = self.doc(PLAN)
        gid = self.share_as(PLAN)["share"]["id"]
        for i in range(89):
            gistbudget.sent("acme-dev", f"/elsewhere/{i}", now=self.now - i)
        self.assertEqual(share.unshare(p)["id"], gid)
        self.assertEqual(self.writes()[-1], ["api", "-i", "-X", "DELETE", f"gists/{gid}"])
        self.assertEqual(gistbudget.status("acme-dev")["used"], 91, "logged all the same")

    def test_unshare_forgets_a_first_share_that_waits(self) -> None:
        for i in range(90):
            gistbudget.sent("acme-dev", f"/elsewhere/{i}", now=self.now - i)
        res = share.share(self.doc(STATUS), self.docs)
        self.assertEqual((res["queued"]["why"], res["share"]), ("hour", None))
        self.assertIsNone(share.record_of(self.doc(STATUS)), "no gist yet")
        self.assertEqual(share.queued_lines(res)[-1], "link: made when it goes out; the Share sheet shows it then")
        self.assertIsNone(share.unshare(self.doc(STATUS)))
        self.assertEqual(self.shares(), {})

    def test_patch_says_the_link_s_rev_and_the_budget(self) -> None:
        p = self.doc(PLAN)
        self.share_as(PLAN)
        n = len(self.calls())
        r = self.tmp.run("build.py", "patch", p, "doc", "--set", "subtitle=Saved carts, rev two")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[-1], "shared as acme-dev at rev 1: the link stays there until the user updates it "
                                                    "(1 of 90 used this hour)", "never tells the agent to share")
        for _ in range(4):
            gistbudget.refused("acme-dev")
        r = self.tmp.run("build.py", "patch", p, "doc", "--set", "subtitle=Saved carts, rev three", "--no-bump")
        self.assertEqual(r.stdout.splitlines()[-1], "shared as acme-dev: updates are paused (GitHub refused 4 in a row): tell the user")
        r = self.tmp.run("build.py", "patch", self.doc(STATUS), "doc", "--set", "subtitle=Week 41", "--no-bump")
        self.assertFalse([x for x in r.stdout.splitlines() if "shared" in x or "queued" in x], "a doc that isn't shared: no line")
        self.assertEqual(len(self.calls()), n, "patch reads two files: no gh call")

    def test_the_cli_says_queued_with_exit_0_and_paused_with_exit_1(self) -> None:
        self.cli_server()
        p = self.doc(STATUS)
        self.assertEqual(self.tmp.run("serve.py", "share", p, timeout=120).returncode, 0)
        rec = self.shares()[str(p)]
        # within the doc's minute: queued with the rev asked for, exit 0, with what to do next
        r = self.tmp.run("serve.py", "share", p, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()[1:]
        self.assertRegex(lines[0], r"^queued: rev 2 goes out at \d\d:\d\d \(in 1 min\) as acme-dev \(one update a minute per doc\)$")
        self.assertEqual(lines[1:], ["budget: 1 of 90 used in the last hour on acme-dev; GitHub allows about 100 gist updates an hour",
                                     "done: it goes out by itself; later patches wait for the user's next update",
                                     f"link: {rec['link']} (shows rev 2 until then)"])
        # paused: tell the user, exit 1
        for _ in range(4):
            gistbudget.refused("acme-dev")
        r = self.tmp.run("serve.py", "share", p, timeout=120)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr.strip().splitlines()[-1], "not sent: GitHub refused 4 updates in a row on acme-dev; tell the user: "
                                                             "Resume updates in the Share sheet sends it")
        # --resume (the reader's): the queued update goes out now
        self.forget_budget()
        for _ in range(4):
            gistbudget.refused("acme-dev")
        r = self.tmp.run("serve.py", "share", p, "--resume", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("resumed: gist updates go out again on acme-dev", r.stdout)
        self.assertIn("secret gist updated as acme-dev, rev 2", r.stdout)
        self.assertFalse(gistbudget.status("acme-dev")["paused"])
        self.assertIsNone(share.queued_of(p))


ONE_PX_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
AT = "2026-11-18T10:00:00.000Z"


class Answers(StandInGh, unittest.TestCase):
    """What a share carries of the reader's answers: bluedoc-page.json's __BLUEDOC_ANSWERS__ in the stand-in's gist."""

    def setUp(self) -> None:
        self.gh_setup()
        # the reader's attachments where the server keeps them: under a .bluedoc folder
        att = self.tmp.dir / ".bluedoc" / "attachments" / "acme"
        att.mkdir(parents=True)
        (att / "1a2b3c4d-cart.png").write_bytes(ONE_PX_PNG)
        (att / "5e6f7a8b-terms.pdf").write_bytes(b"%PDF-1.4 acme")
        self.png = {"name": "cart.png", "path": str(att / "1a2b3c4d-cart.png"), "size": len(ONE_PX_PNG)}
        self.pdf = {"name": "terms.pdf", "path": str(att / "5e6f7a8b-terms.pdf"), "size": 13}
        pin = {"id": "c1", "type": "pin", "status": "open", "note": "This total looks wrong", "files": [self.png],
               "target": {"key": "item:decisions/prices", "label": "Prices"}, "rev": "1", "at": AT, "sentAt": AT,
               "thread": [{"md": "Still wrong", "rev": "1", "at": AT}], "draft": "And the tax line", "draftFiles": [self.pdf]}
        general = {"id": "c2", "type": "general", "status": "pending", "note": "Not sent yet", "target": {"key": "doc", "label": "Whole doc"},
                   "rev": "1", "at": AT}
        element = {"id": "c3", "type": "element", "status": "open", "target": {"key": "el:x", "label": "x"}, "rev": "1", "at": AT,
                   "element": {"op": "text", "ab": "a", "sel": "h1", "tag": "h1", "base": "Cart", "text": "Basket"}}
        self.state = {"decisions:retention": "=d180|", "decisions:prices:custom": "Ask finance first", "decisions:guests:more": "1",
                      "checks:unit": "10", "checks:limit": "01",
                      "decisions:retention:thread": json.dumps([{"md": "180 days matches finance", "rev": "1", "at": AT, "files": [self.png, self.pdf]}]),
                      "__ann:c1": json.dumps(pin), "__ann:c2": json.dumps(general), "__ann:c3": json.dumps(element),
                      "decisions:prices:note": "Check with legal", "decisions:prices:notes": json.dumps({"notice": {"md": "7 days?", "files": [self.png]}}),
                      "decisions:guests:files": json.dumps([self.pdf]), "__message": "Overall fine", "__message-files": json.dumps([self.png]),
                      "__title": "My carts", "__emoji": "🛒", "__planstate": "approved", "__seen": "1", "__hist": "{}"}

    def gist_answers(self, kinds) -> tuple[dict | None, dict]:
        """Share PLAN with these kinds: (the slot's object, the gist's files)."""
        res = self.share_as(PLAN, answers=kinds, state=self.state)
        _, files = self.gist(res["share"]["id"])
        return json.loads(json.loads(files["bluedoc-page.json"])["fill"]["__BLUEDOC_ANSWERS__"]), files

    def test_answers_by_default_picks_ticks_and_sent_comments(self) -> None:
        slot, files = self.gist_answers(None)
        self.assertEqual(sorted(slot), ["at", "by", "rev", "state"])
        self.assertEqual((slot["by"], slot["rev"]), ("acme-dev", "1"))
        self.assertEqual(sorted(slot["state"]), ["__ann:c1", "checks:unit", "decisions:guests:more", "decisions:prices:custom",
                                                 "decisions:retention", "decisions:retention:thread"])
        self.assertTrue(all(isinstance(v, str) for v in slot["state"].values()), "the state keys' own grammar: string values")
        pin = json.loads(slot["state"]["__ann:c1"])
        self.assertEqual((pin["note"], pin["thread"][0]["md"], pin["files"]), ("This total looks wrong", "Still wrong", [{"name": "cart.png", "size": len(ONE_PX_PNG)}]))
        self.assertNotIn("draft", pin, "a follow-up not sent stays")
        self.assertEqual(json.loads(slot["state"]["decisions:retention:thread"])[0]["files"],
                         [{"name": "cart.png", "size": len(ONE_PX_PNG)}, {"name": "terms.pdf", "size": 13}], "no path, no data")
        for text in files.values():
            for leak in ("/.bluedoc/", str(self.tmp.dir), "My carts", "Not sent yet", "Check with legal", "Overall fine", "Basket"):
                self.assertNotIn(leak, text)
        self.assertNotIn('"path"', json.dumps(slot), "no attachment carries its path")
        self.assertEqual(self.shares()[str(self.doc(PLAN))]["answers"], ["picks", "ticks", "comments"])

    def test_answers_each_switch_takes_its_kind(self) -> None:
        want = {"picks": {"decisions:retention", "decisions:prices:custom", "decisions:guests:more"}, "ticks": {"checks:unit"},
                "comments": {"decisions:retention:thread", "__ann:c1"},
                "pending": {"__ann:c2", "decisions:prices:note", "decisions:prices:notes", "decisions:guests:files", "__message", "__message-files"}}
        for kind, keys in want.items():
            with self.subTest(kind=kind):
                slot, _ = self.gist_answers([kind])
                self.assertEqual(set(slot["state"]), keys)
        # comments and pending: the sent comment carries its follow-up draft
        slot, _ = self.gist_answers(["comments", "pending"])
        pin = json.loads(slot["state"]["__ann:c1"])
        self.assertEqual((pin["draft"], pin["draftFiles"]), ("And the tax line", [{"name": "terms.pdf", "size": 13}]))
        self.assertIsNone(self.gist_answers(["images"])[0], "images alone carry nothing: they ride on the other kinds")

    def test_answers_images_go_as_data_within_the_cap(self) -> None:
        slot, files = self.gist_answers(["comments", "images"])
        msg = json.loads(slot["state"]["decisions:retention:thread"])[0]
        uri = "data:image/png;base64," + base64.b64encode(ONE_PX_PNG).decode("ascii")
        self.assertEqual(msg["files"], [{"name": "cart.png", "size": len(ONE_PX_PNG), "src": uri}, {"name": "terms.pdf", "size": 13}],
                         "a PDF isn't shared")
        self.assertNotIn("/.bluedoc/", files["bluedoc-page.json"])
        with mock.patch.object(share, "IMAGES_MAX", len(ONE_PX_PNG)):   # room for one copy: the pin's goes, the message's doesn't
            slot, _ = self.gist_answers(["comments", "images"])
        srcs = [f.get("src") for f in json.loads(slot["state"]["__ann:c1"])["files"] + json.loads(slot["state"]["decisions:retention:thread"])[0]["files"]]
        self.assertEqual(srcs, [uri, None, None])
        v = share.view(self.doc(PLAN), self.docs, state=self.state, kinds=["comments", "images"])
        self.assertEqual((v["answers"]["counts"], v["answers"]["notShared"]),
                         ({"picks": 3, "ticks": 1, "comments": 3, "pending": 5, "images": 1}, 1))

    def test_no_answers_leaves_the_slot_null_and_changes_show(self) -> None:
        res = self.share_as(PLAN, answers=[], state=self.state)
        page = json.loads(self.gist(res["share"]["id"])[1]["bluedoc-page.json"])
        self.assertEqual(page["fill"]["__BLUEDOC_ANSWERS__"], "null")
        v = share.view(self.doc(PLAN), self.docs, state=self.state, kinds=[])
        self.assertFalse(v["answers"]["changed"])
        self.assertTrue(share.view(self.doc(PLAN), self.docs, state=self.state)["answers"]["changed"], "the defaults would add them")
        self.share_as(PLAN, state=self.state)
        self.assertFalse(share.view(self.doc(PLAN), self.docs, state=self.state)["answers"]["changed"])
        later = {**self.state, "checks:cross-device": "10"}
        self.assertTrue(share.view(self.doc(PLAN), self.docs, state=later)["answers"]["changed"], "a new tick: Update answers")

    def test_answers_through_the_server_are_remembered_per_doc(self) -> None:
        self.cli_server()
        p = self.doc(PLAN)
        r = self.tmp.run("serve.py", "open", p)   # starts the server, registers the folder
        self.assertEqual(r.returncode, 0, r.stderr)
        url = urlsplit(r.stdout.strip()).path
        port = int(self.tmp.env["BLUEDOC_PORT"])
        key = (self.tmp.home / "key").read_text(encoding="utf-8").strip()
        ops = [[k, v] for k, v in self.state.items() if not k.startswith("__hist")]
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("PUT", "/__bluedoc/state", json.dumps({"path": url, "import": False, "ops": ops}),
                  {"Host": f"127.0.0.1:{port}", "X-Bluedoc": "1", "X-Bluedoc-Key": key, "Content-Type": "application/json"})
        self.assertEqual(c.getresponse().status, 200)
        c.close()
        r = self.tmp.run("serve.py", "share", p, "--answers", "ticks", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        gid = self.shares()[str(p)]["id"]
        slot = json.loads(json.loads(self.gist(gid)[1]["bluedoc-page.json"])["fill"]["__BLUEDOC_ANSWERS__"])
        self.assertEqual(set(slot["state"]), {"checks:unit"})
        # remembered: the next share without a flag carries ticks again; --no-answers, none
        self.forget_budget()
        self.tmp.run("serve.py", "share", p, timeout=120)
        self.assertEqual(self.shares()[str(p)]["answers"], ["ticks"])
        self.forget_budget()
        r = self.tmp.run("serve.py", "share", p, "--no-answers", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.gist(gid)[1]["bluedoc-page.json"])["fill"]["__BLUEDOC_ANSWERS__"], "null")
        self.assertNotIn("/.bluedoc/", "".join(self.gist(gid)[1].values()))


class Routes(StandInGh, unittest.TestCase):
    def setUp(self) -> None:
        self.gh_setup("acme-shop")   # the project acme-shop
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)

    def restart(self, **env: str) -> None:
        self.server.stop()
        self.tmp.env.update(env)
        self.server.start()

    def call(self, method: str, route: str, stem: str, key: bool = True, budget: bool = False, **body) -> tuple[int, dict]:
        """One share route on the doc; a share POST forgets the budget first (the minute per doc) unless budget."""
        url = self.server.url_for(self.doc(stem))
        h = {"X-Bluedoc": "1", "Content-Type": "application/json", **({} if key else {"X-Bluedoc-Key": "wrong"})}
        if method == "GET":
            status, raw = self.server.req("GET", f"{route}?path={quote(url)}", headers=h)
        else:
            if route == "/__bluedoc/share" and not budget:
                self.forget_budget()
            status, raw = self.server.req("POST", route, json.dumps({"path": url, **body}).encode(), h)
        self.assertNotIn(b"gho_standin_", raw, "no token in an answer")
        return status, json.loads(raw)

    def settings(self, body: dict | None = None) -> tuple[int, dict]:
        h = {"X-Bluedoc": "1", "Content-Type": "application/json"}
        status, raw = (self.server.req("GET", "/__bluedoc/settings") if body is None
                       else self.server.req("POST", "/__bluedoc/settings", json.dumps(body).encode(), h))
        self.assertNotIn(b"gho_standin_", raw)
        return status, json.loads(raw)

    def test_share_read_and_unshare_through_the_routes(self) -> None:
        project = {"slug": "acme-shop", "name": "acme-shop", "remote": None}
        status, j = self.call("GET", "/__bluedoc/share", DESIGN)
        self.assertEqual(status, 200, j)
        self.assertEqual(j, {"share": None, "rev": "C", "off": None, "queued": None, "contents": {"media": 0, "screens": 11}, "project": project,
                             "accounts": [acct("acme-dev", active=True)], "account": {"login": "acme-dev", "why": "only"},
                             "ask": False, "mismatch": None, "error": None,
                             "budget": {"login": "acme-dev", "used": 0, "limit": 90, "next": None, "retryAt": None, "paused": False},
                             "answers": {"kinds": ["picks", "ticks", "comments"], "notShared": 0, "changed": False,
                                         "counts": {"picks": 0, "ticks": 0, "comments": 0, "pending": 0, "images": 0}}})
        status, j = self.call("POST", "/__bluedoc/share", DESIGN)
        self.assertEqual(status, 200, j)
        rec = j["share"]
        self.assertEqual((j["created"], j["relinked"], j["moved"], j["rev"], rec["rev"], j["project"]), (True, False, False, "C", "C", project))
        self.assertEqual(self.call("GET", "/__bluedoc/share", DESIGN)[1]["share"], rec)
        url = self.server.url_for(self.doc(DESIGN))
        status, raw = self.server.req("GET", f"/__bluedoc/share?path={quote(url)}&brief=1", headers={"X-Bluedoc": "1"})
        self.assertEqual((status, json.loads(raw)), (200, {"share": rec, "rev": "C", "off": None, "queued": None}), "brief")
        status, j = self.call("POST", "/__bluedoc/share", DESIGN)
        self.assertEqual((status, j["share"]["id"], j["created"]), (200, rec["id"], False))
        status, j = self.call("POST", "/__bluedoc/unshare", DESIGN)
        self.assertEqual((status, j["removed"]["id"]), (200, rec["id"]))
        self.assertIsNone(self.call("GET", "/__bluedoc/share", DESIGN)[1]["share"])
        self.assertEqual(self.call("POST", "/__bluedoc/unshare", DESIGN)[1], {"ok": True, "removed": None})
        self.assertEqual(self.call("GET", "/__bluedoc/share", "acme-fit-deck")[0], 400)
        self.assertNotIn("gho_standin_", (self.tmp.dir / "server.log").read_text(encoding="utf-8"), "no token in the log")

    def test_accounts_preselect_and_the_mismatch_through_the_routes(self) -> None:
        git_remote(self.docs, "git@github.com:acme-corp/shop.git")
        self.sign_in(THREE, orgs="acme-work=acme-corp")
        self.restart()
        _, j = self.call("GET", "/__bluedoc/share", PLAN)
        self.assertEqual((j["project"], j["ask"], j["account"]),
                         ({"slug": "acme-shop", "name": "acme-shop", "remote": "acme-corp/shop"}, True, {"login": "acme-work", "why": "remote"}))
        self.assertEqual(j["accounts"][2], acct("acme-oss", usable=False))
        status, j = self.call("POST", "/__bluedoc/share", PLAN, **{"as": "acme-dev"})
        self.assertEqual((status, j["share"]["user"], j["account"], j["mismatch"]), (200, "acme-dev", {"login": "acme-dev", "why": "project"}, None))
        gid = j["share"]["id"]
        # the Share as chip picks acme-work: the gist on acme-dev now needs a pick
        status, j = self.call("POST", "/__bluedoc/share", PLAN, **{"as": "acme-work"})
        self.assertEqual((status, j["mismatch"]), (409, {"gist": "acme-dev", "project": "acme-work"}))
        self.assertIn("move it to acme-work", j["error"])
        _, j = self.call("GET", "/__bluedoc/share", PLAN)
        self.assertEqual(j["mismatch"], {"gist": "acme-dev", "project": "acme-work"})
        status, j = self.call("POST", "/__bluedoc/share", PLAN, keep=True)
        self.assertEqual((status, j["share"]["id"], j["share"]["user"], j["mismatch"]), (200, gid, "acme-dev", None))
        self.assertEqual(self.call("POST", "/__bluedoc/share", PLAN, **{"as": "acme"*20})[0], 400)
        self.assertEqual(self.call("POST", "/__bluedoc/share", PLAN, **{"as": "acme-oss"})[0], 400)
        # the Settings card: each project's account and gh's accounts
        status, v = self.settings()
        self.assertEqual(status, 200)
        self.assertEqual(v["sharing"], {"projects": [{"slug": "acme-shop", "name": "acme-shop", "path": str(self.docs), "account": "acme-work"}],
                                        "accounts": [acct("acme-work"), acct("acme-dev", active=True), acct("acme-oss", usable=False)],
                                        "off": None})
        status, v = self.settings({"sharing": {"slug": "acme-shop", "account": None}})
        self.assertEqual((status, v["sharing"]["projects"][0]["account"]), (200, None), "ask on the first share")
        self.assertEqual(self.settings({"sharing": {"slug": "acme-shop", "account": "Acme-Dev"}})[1]["sharing"]["projects"][0]["account"], "acme-dev")
        for body, error in (({"slug": "nope", "account": "acme-dev"}, "no project nope"),
                            ({"slug": "acme-shop", "account": "acme-oss"}, "acme-oss lacks the gist scope: run `gh auth refresh -s gist -u acme-oss`"),
                            ({"slug": "acme-shop", "account": "acme-nobody"}, "gh isn't signed in as acme-nobody: run `gh auth login -s gist`"),
                            ({"slug": "acme-shop"}, "sharing: {slug, account: a GitHub login or null}")):
            with self.subTest(body=body):
                self.assertEqual(self.settings({"sharing": body}), (400, {"error": error}))
        self.assertEqual(share.project_account(self.docs), "acme-dev")
        status, raw = self.server.req("POST", "/__bluedoc/settings", json.dumps({"sharing": {"slug": "acme-shop", "account": None}}).encode(),
                                      {"X-Bluedoc": "1", "Content-Type": "application/json", "X-Bluedoc-Key": "wrong"})
        self.assertEqual(status, 403)

    def test_sharing_off_through_the_routes(self) -> None:
        for env, off in (({"STANDIN_GH_AUTH": "signed-out"}, {"reason": "gh, the GitHub CLI, isn't signed in to GitHub", "fix": "gh auth login -s gist"}),
                         (NO_GH, {"reason": "gh, the GitHub CLI, isn't installed", "fix": "brew install gh"})):
            with self.subTest(env=env):
                self.restart(**env)
                url = self.server.url_for(self.doc(PLAN))
                status, raw = self.server.req("GET", f"/__bluedoc/share?path={quote(url)}&brief=1", headers={"X-Bluedoc": "1"})
                self.assertEqual((status, json.loads(raw)), (200, {"share": None, "rev": "1", "off": off, "queued": None}))
                _, j = self.call("GET", "/__bluedoc/share", PLAN)
                self.assertEqual((j["off"], j["accounts"], j["account"], j["ask"]), (off, [], None, False))
                self.assertEqual(self.settings()[1]["sharing"]["off"], off)
                self.assertEqual(self.call("POST", "/__bluedoc/share", PLAN)[0], 501 if env is NO_GH else 502)

    def test_every_share_route_needs_the_key(self) -> None:
        for method, route in (("GET", "/__bluedoc/share"), ("POST", "/__bluedoc/share"), ("POST", "/__bluedoc/unshare")):
            with self.subTest(method=method, route=route):
                status, j = self.call(method, route, PLAN, key=False)
                self.assertEqual((status, j.get("key")), (403, True))
        url = self.server.url_for(self.doc(PLAN))
        self.assertEqual(self.server.req("GET", f"/__bluedoc/share?path={quote(url)}")[0], 403, "the X-Bluedoc header too")
        self.assertEqual(self.calls(), [])

    def test_gh_errors_and_the_cap_answer_with_their_status(self) -> None:
        self.restart(STANDIN_GH_AUTH="no-gist")
        status, j = self.call("POST", "/__bluedoc/share", PLAN)
        self.assertEqual(status, 502)
        self.assertIn("`gh auth refresh -s gist -u acme-dev`", j["error"])
        self.tmp.env.pop("STANDIN_GH_AUTH")
        self.restart(**NO_GH)
        status, j = self.call("POST", "/__bluedoc/share", PLAN)
        self.assertEqual(status, 501)
        self.assertIn("isn't installed", j["error"])
        self.restart(BLUEDOC_GH=os.environ["BLUEDOC_GH"])
        # a media file that makes the page over 10 MB once inline
        p = self.doc(PLAN)
        (self.docs / "big.png").write_bytes(b"\x89PNG\r\n\x1a\n" + os.urandom(8 * 1024 * 1024))
        doc = load_json(p)
        doc["sections"][0]["blocks"].append({"type": "media", "src": "big.png", "alt": "Acme"})
        p.write_text(build.dump_doc(doc), encoding="utf-8")
        status, j = self.call("POST", "/__bluedoc/share", PLAN)
        self.assertEqual(status, 413)
        self.assertRegex(j["error"], r"would be 1\d\.\d MB, over the 10 MB a gist file can hold: send Export → HTML file instead")
        self.assertEqual(self.shares(), {})

    def wait_for(self, check, timeout: float = 15) -> None:
        end = time.monotonic() + timeout
        while not check():
            if time.monotonic() > end:
                self.fail(f"not within {timeout} s: {(self.tmp.dir / 'server.log').read_text(encoding='utf-8')[-2000:]}")
            time.sleep(0.2)

    def doc_minute_ends_in(self, stem: str, seconds: float) -> None:
        """The doc's last update as if it went out (60 - seconds) s ago."""
        f = gistbudget.budget_file()
        data = json.loads(f.read_text(encoding="utf-8"))
        data["acme-dev"]["docs"][str(self.doc(stem))] = time.time() - 60 + seconds
        f.write_text(json.dumps(data), encoding="utf-8")

    def test_the_server_s_queue_sends_an_update_when_it_is_due(self) -> None:
        p = self.doc(PLAN)
        status, j = self.call("POST", "/__bluedoc/share", PLAN)
        self.assertEqual(status, 200, j)
        gid = j["share"]["id"]
        self.doc_minute_ends_in(PLAN, 3)
        status, j = self.call("POST", "/__bluedoc/share", PLAN, budget=True)
        self.assertEqual((status, j["queued"]["why"], j["queued"]["login"], j["share"]["id"]), (202, "spacing", "acme-dev", gid))
        self.assertEqual(self.call("GET", "/__bluedoc/share", PLAN)[1]["queued"]["why"], "spacing")
        asked = load_json(p)["meta"]["rev"]
        self.assertEqual(self.call("GET", "/__bluedoc/share", PLAN)[1]["queued"]["rev"], asked)
        # a patch while it waits isn't in it: the server sends the rev the share was asked for
        r = self.tmp.run("build.py", "patch", p, "doc", "--set", "subtitle=Saved carts, rev two")
        self.assertEqual(r.returncode, 0, r.stderr)
        rev = load_json(p)["meta"]["rev"]
        self.assertNotEqual(rev, asked)
        self.wait_for(lambda: "queued" not in self.shares()[str(p)])
        self.assertEqual(self.shares()[str(p)]["rev"], asked)
        self.assertEqual(json.loads(self.gist(gid)[1]["bluedoc-page.json"])["rev"], asked, "the doc as it was when the share was asked for")
        self.assertIn(f"shared {p} as acme-dev (queued)", (self.tmp.dir / "server.log").read_text(encoding="utf-8"))
        _, v = self.call("GET", "/__bluedoc/share", PLAN)
        self.assertEqual((v["share"]["rev"], v["rev"]), (asked, rev), "the doc newer than its share: the key's Update")
        # a queued update a stopped server left: the next server sends it on start (one an older bluedoc queued, with no
        # files kept: the doc as it is)
        self.server.stop()
        data = self.shares()
        data[str(p)]["queued"] = {"login": "acme-dev", "at": time.time(), "why": "hour", "answers": ["picks", "ticks", "comments"]}
        share._save(data)
        self.forget_budget()
        self.tmp.run("build.py", "patch", p, "doc", "--set", "subtitle=Saved carts, rev three")
        rev = load_json(p)["meta"]["rev"]
        self.server.start()
        self.wait_for(lambda: self.shares()[str(p)].get("rev") == rev and "queued" not in self.shares()[str(p)])

    def test_resume_through_the_route_sends_the_queued_update(self) -> None:
        p = self.doc(PLAN)
        gid = self.call("POST", "/__bluedoc/share", PLAN)[1]["share"]["id"]
        self.forget_budget()
        for _ in range(4):
            gistbudget.refused("acme-dev")
        status, j = self.call("POST", "/__bluedoc/share", PLAN, budget=True)
        self.assertEqual((status, j["queued"]["why"], j["budget"]["paused"]), (202, "paused", True))
        _, raw = self.server.req("GET", f"/__bluedoc/share?path={quote(self.server.url_for(p))}&brief=1", headers={"X-Bluedoc": "1"})
        self.assertEqual(json.loads(raw)["queued"]["why"], "paused", "the key knows on load")
        status, j = self.call("POST", "/__bluedoc/share", PLAN, budget=True, resume=True)
        self.assertEqual((status, j["share"]["id"], j["queued"], j["budget"]["paused"]), (200, gid, None, False))
        self.assertEqual(self.call("POST", "/__bluedoc/share", PLAN, answers=["secrets"])[0], 400)
        self.assertEqual(self.call("POST", "/__bluedoc/unshare", PLAN)[0], 200)
        self.assertEqual(self.shares(), {})


if __name__ == "__main__":
    unittest.main()
