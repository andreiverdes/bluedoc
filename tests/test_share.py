"""A doc shared as a secret GitHub gist: share.py, `serve.py share`/`unshare`, /__bluedoc/share, /__bluedoc/unshare
and Settings' sharing. A stand-in gh (fixtures/gh_standin.py, named by BLUEDOC_GH as TempHome sets it) records every
call with the account its GH_TOKEN is for, keeps the gists in a temp folder with their owners, and plays any set of
signed-in accounts: nothing reaches GitHub.

The gist holds the current revision only: <stem>.bluedoc.json, the doc verbatim, and bluedoc-page.json, the contract's
object whose fill, with board-geo.js put back at its slot, makes exactly the page `build.py -o` writes for the doc
without its history (no history file, no earlier revisions), a design's 11 screens inline.

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
import json
import os
import shutil
import stat
import subprocess
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from _support import Server, TempHome, load_json

import build
import settings
import share

NO_GH = {"BLUEDOC_GH": "/nonexistent/gh"}   # no gh to run
PLAN, DESIGN, STATUS = "acme-saved-carts-plan", "acme-fit-design", "acme-status"
FILL_KEYS = {"__BLUEDOC_TITLE__", "__BLUEDOC_DOC__", "__BLUEDOC_HISTORY__", "__BLUEDOC_SCREENS__", "__BLUEDOC_LISTING__",
             "__BLUEDOC_STATE__", "__BLUEDOC_LIVE__", "__BLUEDOC_SNAPS__", "__BLUEDOC_PINS__"}
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
        """TempHome's stand-in gh (BLUEDOC_GH) in os.environ too, its gists in <tmp>/gh, one account (acme-dev)."""
        self.ghdir = Path(self.tmp.env["STANDIN_GH_DIR"])
        self.tmp.env.pop("GH_TOKEN", None)
        patch = mock.patch.dict(os.environ, {k: self.tmp.env[k] for k in ("BLUEDOC_GH", "STANDIN_GH_DIR", "BLUEDOC_HOME")})
        patch.start()
        self.addCleanup(patch.stop)
        for k in ("STANDIN_GH_ACCOUNTS", "STANDIN_GH_ORGS", "STANDIN_GH_AUTH", "STANDIN_GH_USER", "STANDIN_GH_FAIL", "GH_TOKEN"):
            os.environ.pop(k, None)
        self.forget()

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

    def share_as(self, stem: str, **kw) -> dict:
        """share.share of the doc in the examples' project (self.docs)."""
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
                self.assertEqual(sorted(files), sorted([f"{stem}.bluedoc.json", "bluedoc-page.json"]), "no history file")
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
        self.assertEqual(share.view(p, brief=True), {"share": None, "rev": "1", "off": None})
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
                         [(["auth", "status"], None), (["auth", "token"], None), (["gist", "create"], "acme-dev")])
        self.assertEqual(self.calls()[1]["argv"], ["auth", "token", "--hostname", "github.com", "--user", "acme-dev"])
        create = self.calls()[2]["argv"]
        self.assertNotIn("--public", create)
        self.assertEqual(create[2:4], ["--desc", "bluedoc: Acme Shop: saved carts"])
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
                          (["api", f"gists/{gid}"], "acme-dev"), (["api", "-X", "PATCH", f"gists/{gid}", "--input", "-"], "acme-dev")])
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
        self.assertEqual((self.calls()[-1]["argv"], self.calls()[-1]["as"]), (["api", "-X", "DELETE", f"gists/{gid}"], "acme-work"))
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
        self.assertEqual([(c["argv"][:3], c["as"]) for c in self.calls()[n:] if c["argv"][0] in ("gist", "api")],
                         [(["gist", "create", "--desc"], "acme-work"), (["api", "-X", "DELETE"], "acme-dev")])
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
        self.assertEqual(set(data[str(p)]), {"id", "user", "link", "url", "rev", "at", "files"})
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
        self.assertEqual((self.calls()[-1]["argv"], self.calls()[-1]["as"]), (["api", "-X", "DELETE", f"gists/{gid}"], "acme-dev"))
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
        with mock.patch.dict(os.environ, {"STANDIN_GH_FAIL": "gist create"}), self.assertRaises(share.ShareError) as cm:
            self.share_as(PLAN)
        self.assertEqual(cm.exception.status, 502)
        self.assertIn("gh gist create failed: gh: Server Error (HTTP 500)", str(cm.exception))
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
        p = self.doc(DESIGN)
        r = self.tmp.run("serve.py", "share", p, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        rec = self.shares()[str(p)]
        self.assertEqual(lines[0], share.NOTICE, "no colour when stdout isn't a terminal")
        self.assertEqual(lines[1], "secret gist created as acme-dev, rev C: 0 media files, 11 screens")
        self.assertEqual(lines[2:], [f"link: https://bluedoc.ai/g/{code(rec['id'])}", f"gist: https://gist.github.com/acme-dev/{rec['id']}"])
        tty = type("Tty", (), {"isatty": lambda self: True})()
        with mock.patch.dict(os.environ):
            os.environ.pop("NO_COLOR", None)
            self.assertEqual(share.red(share.NOTICE, tty), f"\x1b[1;31m{share.NOTICE}\x1b[0m", "red on a terminal")
            os.environ["NO_COLOR"] = "1"
            self.assertEqual(share.red(share.NOTICE, tty), share.NOTICE)
        r = self.tmp.run("serve.py", "share", p, timeout=120)
        self.assertIn("secret gist updated as acme-dev", r.stdout)
        # --as makes another account the project's: the gist on acme-dev waits for --move or --keep
        self.sign_in(THREE)
        r = self.tmp.run("serve.py", "share", p, "--as", "acme-work", timeout=120)
        self.assertEqual(r.returncode, 1)
        self.assertIn("the gist is on acme-dev and this project shares as acme-work", r.stderr)
        self.assertIn("run again with --move or --keep", r.stderr)
        self.assertEqual(share.project_account(self.docs), "acme-work", "serve.py share finds the project: the doc's folder")
        r = self.tmp.run("serve.py", "share", p, "--keep", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("secret gist updated as acme-dev", r.stdout)
        r = self.tmp.run("serve.py", "share", p, "--as", "acme-work", "--move", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("secret gist moved (a new gist, the old one deleted: the link changed) as acme-work", r.stdout)
        self.assertEqual(self.tmp.run("serve.py", "share", p, "--move", "--keep").returncode, 2)
        self.tmp.env["STANDIN_GH_ACCOUNTS"] = "acme-dev:nogist"
        r = self.tmp.run("serve.py", "share", p, timeout=120)
        self.assertEqual(r.returncode, 1)
        self.assertIn("gh auth refresh -s gist -u acme-dev", r.stderr)


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

    def call(self, method: str, route: str, stem: str, key: bool = True, **body) -> tuple[int, dict]:
        url = self.server.url_for(self.doc(stem))
        h = {"X-Bluedoc": "1", "Content-Type": "application/json", **({} if key else {"X-Bluedoc-Key": "wrong"})}
        if method == "GET":
            status, raw = self.server.req("GET", f"{route}?path={quote(url)}", headers=h)
        else:
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
        self.assertEqual(j, {"share": None, "rev": "C", "off": None, "contents": {"media": 0, "screens": 11}, "project": project,
                             "accounts": [acct("acme-dev", active=True)], "account": {"login": "acme-dev", "why": "only"},
                             "ask": False, "mismatch": None})
        status, j = self.call("POST", "/__bluedoc/share", DESIGN)
        self.assertEqual(status, 200, j)
        rec = j["share"]
        self.assertEqual((j["created"], j["relinked"], j["moved"], j["rev"], rec["rev"], j["project"]), (True, False, False, "C", "C", project))
        self.assertEqual(self.call("GET", "/__bluedoc/share", DESIGN)[1]["share"], rec)
        url = self.server.url_for(self.doc(DESIGN))
        status, raw = self.server.req("GET", f"/__bluedoc/share?path={quote(url)}&brief=1", headers={"X-Bluedoc": "1"})
        self.assertEqual((status, json.loads(raw)), (200, {"share": rec, "rev": "C", "off": None}), "brief")
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
                self.assertEqual((status, json.loads(raw)), (200, {"share": None, "rev": "1", "off": off}))
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


if __name__ == "__main__":
    unittest.main()
