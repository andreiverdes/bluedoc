"""A doc shared as a secret GitHub gist: share.py, `serve.py share`/`unshare`, /__bluedoc/share and /__bluedoc/unshare,
and the app bar's Share key. A stand-in gh (fixtures/gh_standin.py, on PATH as `gh`) records every call and
keeps the gists in a temp folder: nothing reaches GitHub.

The gist's three files: <stem>.bluedoc.json is the doc verbatim, <stem>.bluedoc.history.json its history with the
current rev recorded (a plan and a design), bluedoc-page.json the contract's object whose fill, with board-geo.js put
back at its slot, makes exactly the page `build.py -o` writes (build.standalone), a design's 11 screens inline. The
first share runs `gh auth status` then `gh gist create` (no --public) described `bluedoc: <title>`; sharing again
reads the gist and PATCHes the same id with every file, a file the doc no longer has set to null, so the link stays;
a gist deleted on GitHub is created anew. The share is kept in $BLUEDOC_HOME/shares.json (0600) by the doc's path,
never beside the doc. unshare DELETEs the gist and forgets it, also when GitHub has it no more, and keeps it when gh
fails. gh missing is a 501 naming `gh auth login`, signed out or without the gist scope a 502 naming `gh auth login`
or `gh auth refresh -s gist`, a bluedoc-page.json over 10 MB a 413 pointing to Export → HTML file, a deck a 400.
The routes need the X-Bluedoc header and the key, the GET too (it shows the link); its brief form leaves out what goes
in. The link is https://bluedoc.ai/g/<code>, the gist id's bytes in base64url without padding (32 hex: 22 characters,
20 hex: 14), any other id the long https://bluedoc.ai/g/#<user>/<id>; a share recorded with the long link reads the
short one. `serve.py share` prints the notice, then the link and the gist's URL. In Chrome, the app bar has Share,
Export, ⋯ in that order (the key: its icon alone under 900 px); a shared doc marks the key with a dot in the accent, a
doc newer than its share in the warning colour, also on load. The key opens the dialog: the red notice (the risk
colours, the same words as share.NOTICE) and what goes in, Share puts the link in the dialog, copied, with
Shared · rev · just now; after a patch the dialog says the doc is newer and Share again (the accent) keeps the link;
Stop sharing asks once more, then deletes the gist and unmarks the key."""
from __future__ import annotations

import base64
import json
import os
import shutil
import stat
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from _support import REPO, Server, TempHome, load_json
from test_page_state import CHROME, ChromePage, Tab

import build
import share

STANDIN = REPO / "tests" / "fixtures" / "gh_standin.py"
PLAN, DESIGN = "acme-saved-carts-plan", "acme-fit-design"
FILL_KEYS = {"__BLUEDOC_TITLE__", "__BLUEDOC_DOC__", "__BLUEDOC_HISTORY__", "__BLUEDOC_SCREENS__", "__BLUEDOC_LISTING__",
             "__BLUEDOC_STATE__", "__BLUEDOC_LIVE__", "__BLUEDOC_SNAPS__", "__BLUEDOC_PINS__"}


def code(gist_id: str) -> str:
    """A gist id's short-link code, worked out here apart from share.link_for: its bytes in base64url, no padding."""
    return base64.urlsafe_b64encode(bytes.fromhex(gist_id)).rstrip(b"=").decode("ascii")


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
    """A TempHome with the examples, the stand-in gh on its PATH, and its env in os.environ while a test runs (for
    share.py called in process)."""

    def gh_setup(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.gh_env()

    def gh_env(self) -> None:
        """The stand-in gh on self.tmp's PATH (and os.environ's), its gists in <tmp>/gh."""
        self.bin, self.ghdir = self.tmp.dir / "bin", self.tmp.dir / "gh"
        self.bin.mkdir()
        (self.bin / "gh").symlink_to(STANDIN)
        self.tmp.env.update({"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}", "STANDIN_GH_DIR": str(self.ghdir)})
        patch = mock.patch.dict(os.environ, {k: self.tmp.env[k] for k in ("PATH", "STANDIN_GH_DIR", "BLUEDOC_HOME")})
        patch.start()
        self.addCleanup(patch.stop)

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


class Bundle(StandInGh, unittest.TestCase):
    def setUp(self) -> None:
        self.gh_setup()

    def test_the_page_file_fills_the_template_as_build_o_does(self) -> None:
        template = build.TEMPLATE.read_text(encoding="utf-8")
        for stem, screens in ((PLAN, 0), (DESIGN, 11)):
            with self.subTest(stem=stem):
                p = self.doc(stem)
                files, doc, what = share.gist_files(p)
                self.assertEqual(sorted(files), sorted([f"{stem}.bluedoc.json", f"{stem}.bluedoc.history.json", "bluedoc-page.json"]))
                self.assertEqual(files[f"{stem}.bluedoc.json"], p.read_text(encoding="utf-8"), "the doc, verbatim")
                history = build.history_now(p, doc)
                self.assertEqual(json.loads(files[f"{stem}.bluedoc.history.json"]), history)
                page = json.loads(files["bluedoc-page.json"])
                self.assertEqual(sorted(page), ["bluedoc", "boardGeo", "fill", "name", "rev", "title", "version"])
                self.assertEqual((page["bluedoc"], page["version"], page["name"], page["title"], page["rev"]),
                                 ("share/1", build.skill_version(), stem, doc["title"], doc["meta"]["rev"]))
                self.assertEqual(set(page["fill"]), FILL_KEYS)
                self.assertTrue(page["boardGeo"], "a plan's canvas and a design's board need board-geo.js")
                filled = build.fill_page(template, {**page["fill"], build.BOARD_GEO_SLOT: build.board_geo_text()})
                self.assertEqual(filled, build.standalone(doc, p, history, template, problems=[]))
                self.assertEqual(len(json.loads(page["fill"]["__BLUEDOC_SCREENS__"]) or {}), screens)
                self.assertEqual(what["screens"], screens)
        status = self.doc("acme-status")
        page = json.loads(share.gist_files(status)[0]["bluedoc-page.json"])
        self.assertFalse(page["boardGeo"], "a doc without a board or a canvas")
        self.assertEqual(build.fill_page(template, {**page["fill"], build.BOARD_GEO_SLOT: ""}),
                         build.standalone(load_json(status), status, build.history_now(status, load_json(status)), template, problems=[]))

    def test_a_doc_without_a_rev_has_no_history_file(self) -> None:
        p = self.doc(PLAN)
        doc = load_json(p)
        del doc["meta"]["rev"]
        p.write_text(build.dump_doc(doc), encoding="utf-8")
        files, _, what = share.gist_files(p)
        self.assertEqual(sorted(files), [f"{PLAN}.bluedoc.json", "bluedoc-page.json"])
        self.assertIsNone(json.loads(files["bluedoc-page.json"])["rev"])
        self.assertEqual(what["revisions"], 1)

    def test_a_deck_or_a_listing_is_refused(self) -> None:
        for stem in ("acme-fit-deck", "acme-fit-listing"):
            with self.subTest(stem=stem):
                with self.assertRaises(share.ShareError) as cm:
                    share.share(self.doc(stem))
                self.assertEqual(cm.exception.status, 400)
        self.assertEqual(self.calls(), [], "refused before gh runs")


class Gists(StandInGh, unittest.TestCase):
    def setUp(self) -> None:
        self.gh_setup()

    def test_create_then_share_again_patches_the_same_gist(self) -> None:
        p = self.doc(PLAN)
        before = sorted(x.name for x in self.docs.iterdir())
        res = share.share(p)
        rec, gid = res["share"], res["share"]["id"]
        self.assertTrue(res["created"])
        self.assertEqual([c["argv"][:2] for c in self.calls()], [["auth", "status"], ["gist", "create"]])
        create = self.calls()[1]["argv"]
        self.assertNotIn("--public", create)
        self.assertEqual(create[2:4], ["--desc", "bluedoc: Acme Shop: saved carts"])
        meta, files = self.gist(gid)
        self.assertFalse(meta["public"])
        self.assertEqual(sorted(files), rec["files"])
        self.assertEqual(rec["link"], f"https://bluedoc.ai/g/{code(gid)}")
        self.assertEqual(len(code(gid)), 22)
        self.assertEqual(rec["url"], f"https://gist.github.com/acme-dev/{gid}")
        self.assertEqual(rec["rev"], load_json(p)["meta"]["rev"])
        self.assertEqual(self.shares(), {str(p): rec})
        self.assertEqual(stat.S_IMODE(share.shares_file().stat().st_mode), 0o600)
        self.assertEqual(sorted(x.name for x in self.docs.iterdir()), before, "nothing about the share beside the doc")
        self.assertNotIn(gid, p.read_text(encoding="utf-8"))
        # a new rev, then Share again: the same gist, every file, the description kept
        r = self.tmp.run("build.py", "patch", p, "doc", "--set", "subtitle=Saved carts, rev two")
        self.assertEqual(r.returncode, 0, r.stderr)
        (self.ghdir / "gists" / gid / "files" / "stale.txt").write_text("from an earlier share", encoding="utf-8")
        res2 = share.share(p)
        self.assertFalse(res2["created"])
        self.assertEqual(res2["share"]["id"], gid)
        self.assertEqual(res2["share"]["link"], rec["link"])
        self.assertEqual(res2["share"]["rev"], load_json(p)["meta"]["rev"])
        self.assertNotEqual(res2["share"]["rev"], rec["rev"])
        later = [c for c in self.calls()[2:]]
        self.assertEqual([c["argv"] for c in later], [["auth", "status", "--hostname", "github.com"], ["api", f"gists/{gid}"],
                                                      ["api", "-X", "PATCH", f"gists/{gid}", "--input", "-"]])
        body = json.loads(later[2]["stdin"])
        self.assertEqual(body["description"], "bluedoc: Acme Shop: saved carts")
        self.assertIsNone(body["files"]["stale.txt"], "a file the share no longer has goes")
        _, files = self.gist(gid)
        self.assertEqual(sorted(files), res2["share"]["files"])
        self.assertEqual(files[f"{PLAN}.bluedoc.json"], p.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(files["bluedoc-page.json"])["rev"], res2["share"]["rev"])

    def test_a_gist_deleted_on_github_is_created_anew(self) -> None:
        p = self.doc(PLAN)
        first = share.share(p)["share"]["id"]
        shutil.rmtree(self.ghdir / "gists" / first)   # deleted on github.com
        res = share.share(p)
        self.assertTrue(res["created"] and res["relinked"])
        self.assertNotEqual(res["share"]["id"], first)
        self.assertEqual(self.shares()[str(p)]["id"], res["share"]["id"])

    def test_unshare_deletes_the_gist_and_forgets_it(self) -> None:
        p = self.doc(PLAN)
        gid = share.share(p)["share"]["id"]
        rec = share.unshare(p)
        self.assertEqual(rec["id"], gid)
        self.assertEqual(self.calls()[-1]["argv"], ["api", "-X", "DELETE", f"gists/{gid}"])
        self.assertFalse((self.ghdir / "gists" / gid).exists())
        self.assertEqual(self.shares(), {})
        self.assertIsNone(share.unshare(p), "not shared: nothing to do")
        # gone on GitHub already: the DELETE answers 404, and the share is forgotten all the same
        gid = share.share(p)["share"]["id"]
        shutil.rmtree(self.ghdir / "gists" / gid)
        self.assertEqual(share.unshare(p)["id"], gid)
        self.assertEqual(self.shares(), {})
        # the CLI
        gid = share.share(p)["share"]["id"]
        r = self.tmp.run("serve.py", "unshare", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"stopped sharing: gist {gid} deleted, https://bluedoc.ai/g/{code(gid)} no longer opens\n")
        self.assertEqual(self.shares(), {})

    def test_gh_problems_say_what_to_run(self) -> None:
        p = self.doc(PLAN)
        cases = [({"PATH": str(self.tmp.dir / "empty")}, 501, "`gh auth login -s gist`"),
                 ({"STANDIN_GH_AUTH": "signed-out"}, 502, "`gh auth login -s gist`"),
                 ({"STANDIN_GH_AUTH": "no-gist"}, 502, "`gh auth refresh -s gist`"),
                 ({"STANDIN_GH_FAIL": "gist create"}, 502, "gh gist create failed: gh: Server Error (HTTP 500)")]
        for env, status, says in cases:
            with self.subTest(env=env), mock.patch.dict(os.environ, env):
                with self.assertRaises(share.ShareError) as cm:
                    share.share(p)
                self.assertEqual(cm.exception.status, status)
                self.assertIn(says, str(cm.exception))
        self.assertEqual(self.shares(), {})
        gid = share.share(p)["share"]["id"]
        with mock.patch.dict(os.environ, {"STANDIN_GH_FAIL": "DELETE"}), self.assertRaises(share.ShareError):
            share.unshare(p)
        self.assertEqual(self.shares()[str(p)]["id"], gid, "a failed delete keeps the share")

    def test_a_page_over_10_mb_is_refused(self) -> None:
        p = self.doc(PLAN)
        with mock.patch.object(share, "MAX_PAGE_BYTES", 20_000), self.assertRaises(share.ShareError) as cm:
            share.share(p)
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
        self.assertEqual(lines[1], "secret gist created, rev C: 3 revisions, 0 diffs with their code, 0 media files, 11 screens")
        self.assertEqual(lines[2:], [f"link: https://bluedoc.ai/g/{code(rec['id'])}", f"gist: https://gist.github.com/acme-dev/{rec['id']}"])
        tty = type("Tty", (), {"isatty": lambda self: True})()
        with mock.patch.dict(os.environ):
            os.environ.pop("NO_COLOR", None)
            self.assertEqual(share.red(share.NOTICE, tty), f"\x1b[1;31m{share.NOTICE}\x1b[0m", "red on a terminal")
            os.environ["NO_COLOR"] = "1"
            self.assertEqual(share.red(share.NOTICE, tty), share.NOTICE)
        r = self.tmp.run("serve.py", "share", p, timeout=120)
        self.assertIn("secret gist updated", r.stdout)
        self.tmp.env["STANDIN_GH_AUTH"] = "no-gist"
        r = self.tmp.run("serve.py", "share", p, timeout=120)
        self.assertEqual(r.returncode, 1)
        self.assertIn("gh auth refresh -s gist", r.stderr)


class Routes(StandInGh, unittest.TestCase):
    def setUp(self) -> None:
        self.gh_setup()
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)

    def call(self, method: str, route: str, stem: str, key: bool = True) -> tuple[int, dict]:
        url = self.server.url_for(self.doc(stem))
        h = {"X-Bluedoc": "1", "Content-Type": "application/json", **({} if key else {"X-Bluedoc-Key": "wrong"})}
        if method == "GET":
            status, raw = self.server.req("GET", f"{route}?path={quote(url)}", headers=h)
        else:
            status, raw = self.server.req("POST", route, json.dumps({"path": url}).encode(), h)
        return status, json.loads(raw)

    def test_share_read_and_unshare_through_the_routes(self) -> None:
        status, j = self.call("GET", "/__bluedoc/share", DESIGN)
        self.assertEqual(status, 200, j)
        self.assertEqual(j, {"share": None, "rev": "C", "contents": {"revisions": 3, "diffs": 0, "media": 0, "screens": 11}})
        status, j = self.call("POST", "/__bluedoc/share", DESIGN)
        self.assertEqual(status, 200, j)
        rec = j["share"]
        self.assertEqual((j["created"], j["rev"], rec["rev"]), (True, "C", "C"))
        self.assertEqual(self.call("GET", "/__bluedoc/share", DESIGN)[1]["share"], rec)
        url = self.server.url_for(self.doc(DESIGN))
        status, raw = self.server.req("GET", f"/__bluedoc/share?path={quote(url)}&brief=1", headers={"X-Bluedoc": "1"})
        self.assertEqual((status, json.loads(raw)), (200, {"share": rec, "rev": "C"}), "brief: no contents")
        status, j = self.call("POST", "/__bluedoc/share", DESIGN)
        self.assertEqual((status, j["share"]["id"], j["created"]), (200, rec["id"], False))
        status, j = self.call("POST", "/__bluedoc/unshare", DESIGN)
        self.assertEqual((status, j["removed"]["id"]), (200, rec["id"]))
        self.assertIsNone(self.call("GET", "/__bluedoc/share", DESIGN)[1]["share"])
        self.assertEqual(self.call("POST", "/__bluedoc/unshare", DESIGN)[1], {"ok": True, "removed": None})
        self.assertEqual(self.call("GET", "/__bluedoc/share", "acme-fit-deck")[0], 400)

    def test_every_share_route_needs_the_key(self) -> None:
        for method, route in (("GET", "/__bluedoc/share"), ("POST", "/__bluedoc/share"), ("POST", "/__bluedoc/unshare")):
            with self.subTest(method=method, route=route):
                status, j = self.call(method, route, PLAN, key=False)
                self.assertEqual((status, j.get("key")), (403, True))
        url = self.server.url_for(self.doc(PLAN))
        self.assertEqual(self.server.req("GET", f"/__bluedoc/share?path={quote(url)}")[0], 403, "the X-Bluedoc header too")
        self.assertEqual(self.calls(), [])

    def test_gh_errors_and_the_cap_answer_with_their_status(self) -> None:
        self.server.stop()
        self.tmp.env["STANDIN_GH_AUTH"] = "no-gist"
        self.server.start()
        status, j = self.call("POST", "/__bluedoc/share", PLAN)
        self.assertEqual(status, 502)
        self.assertIn("`gh auth refresh -s gist`", j["error"])
        self.server.stop()
        self.tmp.env["PATH"] = str(self.tmp.dir / "empty")
        self.tmp.env.pop("STANDIN_GH_AUTH")
        self.server.start()
        status, j = self.call("POST", "/__bluedoc/share", PLAN)
        self.assertEqual(status, 501)
        self.assertIn("isn't installed", j["error"])
        self.server.stop()
        self.tmp.env["PATH"] = os.environ["PATH"]
        self.server.start()
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


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ShareDialog(StandInGh, ChromePage):
    KEY, DLG = "document.querySelector('.bd-bar-r .bd-shk')", "document.querySelector('dialog.bd-share')"

    def setUp(self) -> None:
        super().setUp()
        self.server.stop()
        self.gh_env()
        self.server.start()

    def page(self, stem: str) -> Tab:
        t = self.open(self.server.url_for(self.doc(stem)))
        t.ev("window.__copied = []; navigator.clipboard.writeText = s => { __copied.push(s); return Promise.resolve(); }; true")
        return t

    def dialog(self, stem: str) -> Tab:
        t = self.page(stem)
        self.reopen(t)
        return t

    def reopen(self, t: Tab) -> None:
        t.ev(f"{self.DLG} && {self.DLG}.open && {self.DLG}.close(); {self.KEY}.click()")
        t.wait_for(f"(d => d && d.open && /What goes in/.test(d.textContent))({self.DLG})")

    def mark(self, t: Tab) -> list:
        """The key's data-share and whether its dot shows."""
        return t.ev(f"[{self.KEY}.dataset.share || null, getComputedStyle({self.KEY}.querySelector('.dot')).display !== 'none']")

    def keys(self, t: Tab) -> list:
        return t.ev(f"[...{self.DLG}.querySelectorAll('.ft .bp-btn')].map(b => [b.textContent, b.classList.contains('primary')])")

    def test_the_key_sits_before_export_and_marks_a_share(self) -> None:
        t = self.page(PLAN)
        self.assertEqual(t.ev("[...document.querySelector('.bd-bar-r').children].filter(e => e.matches('.bd-shk, .bd-docx, .bd-docm')).map(e => e.className.split(' ').find(c => /^bd-(shk|docx|docm)$/.test(c)))"),
                         ["bd-shk", "bd-docx", "bd-docm"], "Share · Export · ⋯")
        self.assertEqual(t.ev(f"[{self.KEY}.textContent, {self.KEY}.hasAttribute('aria-haspopup'), {self.KEY}.getAttribute('aria-label')]"), ["Share", False, "Share"])
        self.assertEqual(self.mark(t), [None, False])
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 800, "deviceScaleFactor": 2, "mobile": True}, t.session)
        t.wait_for("innerWidth === 390")
        self.assertEqual(t.ev(f"[...{self.KEY}.children].map(e => getComputedStyle(e).display)"), ["block", "none", "none"], "narrow: the icon alone")
        # shared from the CLI: the page marks the key on load; a newer rev marks it in the warning colour
        self.assertEqual(self.tmp.run("serve.py", "share", self.doc(PLAN)).returncode, 0)
        t.go(t.ev("location.href"))
        t.wait_for(f"{self.KEY}.dataset.share === 'shared'")
        self.assertEqual(self.mark(t), ["shared", True])
        self.assertIn("Shared as a secret gist at rev 1", t.ev(f"{self.KEY}.title"))
        r = self.tmp.run("build.py", "patch", self.doc(PLAN), "doc", "--set", "subtitle=Saved carts, rev two")
        self.assertEqual(r.returncode, 0, r.stderr)
        t.go(t.ev("location.href"))
        t.wait_for(f"{self.KEY}.dataset.share === 'newer'")
        accent, warn = (t.ev(f"(e => {{ e.style.color = 'var(--{v})'; document.body.append(e); const c = getComputedStyle(e).color; e.remove(); return c; }})(document.createElement('i'))")
                        for v in ("accent", "warn"))
        self.assertEqual(t.ev(f"getComputedStyle({self.KEY}.querySelector('.dot')).backgroundColor"), warn)
        self.assertNotEqual(accent, warn)
        self.assertIn("the doc is at rev 2 now", t.ev(f"{self.KEY}.title"))
        self.assertEqual(self.browser.errors, [])

    def test_share_from_the_key(self) -> None:
        t = self.dialog(PLAN)
        notice = f"{self.DLG}.querySelector('.bd-shn')"
        self.assertEqual(t.ev(f"[{notice}.querySelector('b').textContent, {notice}.textContent]"), [share.NOTICE_LEAD, share.NOTICE])
        risk = t.ev("(e => { e.style.color = 'var(--risk-fg)'; document.body.append(e); const c = getComputedStyle(e).color; e.remove(); return c; })(document.createElement('i'))")
        self.assertEqual(t.ev(f"getComputedStyle({notice}).color"), risk, "the notice is in the design system's risk red")
        self.assertIn("What goes in, at rev 1: 1 revision, 0 diffs with their code, 1 media file, 0 screens.", t.ev(f"{self.DLG}.textContent"))
        self.assertEqual(self.keys(t), [["Cancel", False], ["Share", True]])
        self.assertEqual(self.calls(), [], "nothing goes before Share")
        t.ev(f"{self.DLG}.querySelector('.ft .bp-btn.primary').click()")
        link = t.wait_for(f"(i => i && i.value)({self.DLG}.querySelector('.lnk input'))", 30)
        rec = self.shares()[str(self.doc(PLAN))]
        self.assertEqual(link, rec["link"])
        self.assertRegex(link, r"^https://bluedoc\.ai/g/[A-Za-z0-9_-]{22}$")
        self.assertEqual(link, f"https://bluedoc.ai/g/{code(rec['id'])}")
        self.assertEqual(self.mark(t), ["shared", True], "the key marks the share at once")
        self.assertIn("link is copied", self.toast(t, "shared"))
        self.assertEqual(t.ev("__copied"), [link])
        self.assertTrue(t.ev(f"{self.DLG}.querySelector('.meta').textContent.startsWith('Shared · rev 1 · just now · Gist on GitHub')"))
        self.assertEqual(t.ev(f"{self.DLG}.querySelector('.meta a').href"), rec["url"])
        self.assertTrue(t.ev(f"!!{self.DLG}.querySelector('.bd-shn')"), "the notice stays for Share again")
        self.assertEqual(self.keys(t), [["Stop sharing", False], ["Close", False], ["Share again", False]])
        # a new rev: the dialog says so and Share again takes the accent; the link stays
        r = self.tmp.run("build.py", "patch", self.doc(PLAN), "doc", "--set", "subtitle=Saved carts, rev two")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.reopen(t)
        self.assertEqual(self.mark(t), ["newer", True])
        t.wait_for(f"/the doc is at rev 2 now/.test({self.DLG}.querySelector('.meta')?.textContent || '')")
        self.assertEqual(self.keys(t), [["Stop sharing", False], ["Close", False], ["Share again", True]])
        t.ev(f"{self.DLG}.querySelector('.ft .bp-btn.primary').click()")
        t.wait_for(f"/^Shared · rev 2 /.test({self.DLG}.querySelector('.meta')?.textContent || '')", 30)
        self.assertEqual(t.ev(f"{self.DLG}.querySelector('.lnk input').value"), link)
        self.assertEqual(self.shares()[str(self.doc(PLAN))]["id"], rec["id"])
        self.assertEqual(self.mark(t), ["shared", True], "shared again: the doc's rev is the share's")
        # Stop sharing asks once more
        t.ev(f"{self.DLG}.querySelector('.ft .stop').click()")
        self.assertEqual(t.ev(f"{self.DLG}.querySelector('.ft .stop').textContent"), "Delete the gist")
        self.assertTrue((self.ghdir / "gists" / rec["id"]).is_dir())
        t.ev(f"{self.DLG}.querySelector('.ft .stop').click()")
        self.assertIn("gist is deleted", self.toast(t, "stopped sharing"))
        self.assertFalse(t.ev(f"{self.DLG}.open"))
        self.assertFalse((self.ghdir / "gists" / rec["id"]).exists())
        self.assertEqual(self.mark(t), [None, False])
        self.assertEqual(self.shares(), {})
        self.assertEqual(self.browser.errors, [])

    def test_an_error_stays_in_the_dialog(self) -> None:
        self.server.stop()
        self.tmp.env["STANDIN_GH_AUTH"] = "signed-out"
        self.server.start()
        t = self.dialog(DESIGN)
        self.assertIn("What goes in, at rev C: 3 revisions, 0 diffs with their code, 0 media files, 11 screens.", t.ev(f"{self.DLG}.textContent"))
        t.ev(f"{self.DLG}.querySelector('.ft .bp-btn.primary').click()")
        err = t.wait_for(f"{self.DLG}.querySelector('.err')?.textContent", 30)
        self.assertEqual(err, "Couldn't share: gh isn't signed in to GitHub: run `gh auth login -s gist`")
        self.assertTrue(t.ev(f"{self.DLG}.open"))
        self.assertEqual(self.shares(), {})

    def test_a_phone_fits_the_dialog(self) -> None:
        t = self.dialog(PLAN)
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 800, "deviceScaleFactor": 2, "mobile": True}, t.session)
        t.wait_for("innerWidth === 390")
        t.ev(f"{self.DLG}.querySelector('.ft .bp-btn.primary').click()")
        t.wait_for(f"!!{self.DLG}.querySelector('.lnk input')", 30)
        box = t.ev(f"(r => [r.left, r.right])({self.DLG}.getBoundingClientRect())")
        self.assertGreaterEqual(box[0], 0)
        self.assertLessEqual(box[1], 390)
        self.assertEqual(t.ev(f"[...{self.DLG}.querySelectorAll('.lnk *, .ft .bp-btn')].filter(e => e.getBoundingClientRect().right > {box[1]} + 0.5).length"), 0)


if __name__ == "__main__":
    unittest.main()
