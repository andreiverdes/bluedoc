"""Copying a shared doc (importer.py): `serve.py import <link | gist URL | .zip> [--to DIR]`, the local import page
(GET /__bluedoc/import and /__bluedoc/import.json, POST /__bluedoc/import) and a copy's updates from its sharer
(/__bluedoc/upstream: the check, Compare's ?theirs=1, Pull's three-way merge, Review's Take theirs, Use these answers).

The sharer's gists live in the stand-in gh (fixtures/gh_standin.py): a share made there is read back with
`gh api -i gists/<id>` (its ETag, then 304) when gh is signed in, else through a local fake of GitHub's API
(BLUEDOC_GITHUB_API) without a token, whose rate limit and truncated files are played here. Nothing reaches GitHub,
and nothing writes a gist but the share each test makes in the stand-in.

A copy lands in the repo's docs/plans/ (docs/<type>/), --to to choose; it gets every media file back byte for byte
from the page's data: URIs, a design's screen sources from bluedoc-screens.json, meta.copiedFrom {by, rev, at} and a
history at the sharer's rev; the link stays in $BLUEDOC_HOME/copies.json (0600). Before anything is written: the doc
validates, every path is relative and inside the doc's folder (no `..`, no absolute path, no symlink), the caps hold
(500 files, 10 MB each, 30 MB in all), a name taken gets -2. The import page writes nothing on GET, refuses another
site's Referer, and saves only on a same-origin POST with the key."""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from _support import Server, TempHome, load_json
from test_page_state import CHROME, Browser, Tab
from test_share import DESIGN, PLAN, StandInGh, code

import build
import gistbudget
import importer
import share


class FakeApi:
    """GitHub's /gists/<id> without a token, read from the stand-in's gists: an ETag and 304, and what a test sets:
    refuse (status, headers), truncate (a file name: its content left out, raw_url at raw)."""

    def __init__(self, ghdir: Path) -> None:
        self.ghdir, self.refuse, self.truncate, self.raw, self.asked = ghdir, None, None, "https://gist.githubusercontent.com/x", []
        api = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                api.asked.append((self.path, self.headers.get("If-None-Match"), self.headers.get("Authorization")))
                if api.refuse:
                    code, headers = api.refuse
                    return self.reply(code, {"message": "API rate limit exceeded for 127.0.0.1"}, headers)
                gid = self.path.rsplit("/", 1)[1]
                d = api.ghdir / "gists" / gid
                if not d.is_dir():
                    return self.reply(404, {"message": "Not Found"})
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                files = {f.name: {"filename": f.name, "content": f.read_text(encoding="utf-8")} for f in sorted((d / "files").iterdir())}
                if api.truncate in files:
                    files[api.truncate] = {"filename": api.truncate, "truncated": True, "content": "", "raw_url": f"{api.raw}/{api.truncate}"}
                etag = '"' + str(abs(hash(json.dumps(files, sort_keys=True)))) + '"'
                if self.headers.get("If-None-Match") == etag:
                    return self.reply(304, None, {"ETag": etag})
                return self.reply(200, {"id": gid, "owner": {"login": meta["owner"]}, "files": files}, {"ETag": etag})

            def reply(self, code, body, headers=None):
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(code)
                for k, v in {"Content-Type": "application/json", "Content-Length": str(len(data)), **(headers or {})}.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class Copies(StandInGh):
    """The sharer's examples shared in the stand-in; the colleague's repo (a git folder) and home apart."""

    def setUp(self) -> None:
        self.gh_setup()
        gap = mock.patch.object(share, "WRITE_GAP", 0)
        gap.start()
        self.addCleanup(gap.stop)
        self.repo = self.tmp.dir / "colleague"
        (self.repo / ".git").mkdir(parents=True)   # the repo's root, as git reads it
        self.cwd = mock.patch.object(Path, "cwd", return_value=self.repo)

    def shared(self, stem: str, edit=None, answers: dict | None = None) -> dict:
        """The doc shared (edit(doc) first, written as a new rev), answers in its page's slot; its share record."""
        p = self.doc(stem)
        if edit:
            doc = load_json(p)
            edit(doc)
            build.write_doc(p, doc)
        gistbudget.budget_file().unlink(missing_ok=True)
        rec = share.share(p, self.docs, None)["share"]
        if answers is not None:
            f = self.ghdir / "gists" / rec["id"] / "files" / "bluedoc-page.json"
            page = json.loads(f.read_text(encoding="utf-8"))
            page["fill"][build.ANSWERS_SLOT] = build._script_json(answers)
            f.write_text(json.dumps(page), encoding="utf-8")
        return rec

    def colleague(self) -> Path:
        """The colleague's own BLUEDOC_HOME from here on (copies.json there)."""
        home = self.tmp.dir / "home-colleague"
        home.mkdir(exist_ok=True)
        os.environ["BLUEDOC_HOME"] = self.tmp.env["BLUEDOC_HOME"] = str(home)
        self.sharer_home, self.tmp.home = self.tmp.home, home   # the server's key is read from here
        return home

    def imported(self, link: str, folder: Path | None = None) -> dict:
        b = importer.load(link)
        return {"bundle": b, **importer.write(b, folder or importer.default_dir(b["doc"], self.repo))}


class Sources(unittest.TestCase):
    def test_links_gist_urls_and_codes(self) -> None:
        gid = "b21699001d737be2f6e6a242851a63da"
        for s in (f"https://bluedoc.ai/g/{code(gid)}", f"bluedoc.ai/g/{code(gid)}", f"https://bluedoc.ai/g/#acme-dev/{gid}",
                  f"https://gist.github.com/acme-dev/{gid}", f"https://gist.github.com/{gid}", code(gid), f"acme-dev/{gid}", gid):
            with self.subTest(s=s):
                self.assertEqual(importer.parse_source(s), {"kind": "gist", "id": gid})

    def test_anything_else_is_refused(self) -> None:
        for s in ("https://example.com/g/abc", "https://bluedoc.ai/g/!!", "", "/tmp/acme-missing.zip", "javascript:alert(1)"):
            with self.subTest(s=s), self.assertRaises(importer.ImportFailed):
                importer.parse_source(s)


class Importing(Copies, unittest.TestCase):
    def test_a_plan_lands_in_docs_plans_with_its_media_byte_for_byte(self) -> None:
        rec = self.shared(PLAN)
        self.colleague()
        with self.cwd:
            got = self.imported(rec["link"])
        copy = got["path"]
        self.assertEqual(copy, (self.repo / "docs" / "plans" / f"{PLAN}.bluedoc.json"))
        src = load_json(self.doc(PLAN))
        media = sorted(share._media_srcs(src, set()))
        self.assertTrue(media)
        for rel in media:
            self.assertEqual((copy.parent / rel).read_bytes(), (self.docs / rel).read_bytes(), rel)
        doc = load_json(copy)
        cf = doc["meta"].pop("copiedFrom")
        self.assertEqual((cf["by"], cf["rev"]), ("acme-dev", src["meta"]["rev"]))
        self.assertEqual(doc, src, "the doc as shared, with meta.copiedFrom")
        self.assertNotIn(rec["id"], copy.read_text(encoding="utf-8"), "no gist id or link in the doc")
        self.assertEqual([r["rev"] for r in load_json(build.history_path(copy))["revs"]], [src["meta"]["rev"]], "a fresh history at the sharer's rev")
        self.assertEqual(build.validate(load_json(copy), copy).blocking, [])
        c = importer.copies_file()
        self.assertEqual(stat.S_IMODE(c.stat().st_mode), 0o600)
        r = load_json(c)[str(copy.resolve())]
        self.assertEqual((r["id"], r["user"], r["link"], r["rev"]), (rec["id"], "acme-dev", rec["link"], src["meta"]["rev"]))
        self.assertEqual(r["base"], self.doc(PLAN).read_text(encoding="utf-8"), "the doc as imported is Pull's base")
        self.assertEqual([c["argv"][:3] for c in self.calls()][-1], ["api", "-i", f"gists/{rec['id']}"], "read with gh, signed in")

    def test_a_design_gets_its_screen_sources_back(self) -> None:
        rec = self.shared(DESIGN)
        self.colleague()
        got = self.imported(rec["link"], self.repo / "designs")
        src_doc = load_json(self.doc(DESIGN))
        for f in build.screen_paths(src_doc, self.doc(DESIGN)).values():
            rel = f.relative_to(self.docs).as_posix()
            self.assertEqual((got["path"].parent / rel).read_text(encoding="utf-8"), f.read_text(encoding="utf-8"), rel)
        self.assertEqual(got["warnings"], [])

    def test_a_design_shared_before_the_screens_file_gets_its_wrapped_screens_and_a_warning(self) -> None:
        rec = self.shared(DESIGN)
        (self.ghdir / "gists" / rec["id"] / "files" / "bluedoc-screens.json").unlink()
        self.colleague()
        got = self.imported(rec["link"], self.repo / "designs")
        self.assertTrue(any("older bluedoc" in w for w in got["warnings"]))
        doc = load_json(got["path"])
        a = next(a for a in build._artboards(doc) if not build.is_live(a) and not build.is_icons(a))
        self.assertIn("<", (got["path"].parent / build.screen_rel(got["path"], a)).read_text(encoding="utf-8"))

    def test_a_name_taken_gets_2_and_nothing_is_overwritten(self) -> None:
        rec = self.shared(PLAN)
        self.colleague()
        folder = self.repo / "docs" / "plans"
        first = self.imported(rec["link"], folder)
        media = sorted(share._media_srcs(load_json(self.doc(PLAN)), set()))[0]
        (folder / media).write_bytes(b"the colleague's own picture")
        second = self.imported(rec["link"], folder)
        self.assertEqual(second["path"].name, f"{PLAN}-2.bluedoc.json")
        self.assertEqual((folder / media).read_bytes(), b"the colleague's own picture", "never overwritten")
        bumped = importer._bumped(media, 2)
        self.assertEqual((folder / bumped).read_bytes(), (self.docs / media).read_bytes())
        self.assertIn(bumped, second["path"].read_text(encoding="utf-8"), "the copy points at its own file")
        self.assertTrue(first["path"].is_file())
        third = self.imported(rec["link"], folder)
        self.assertIn(bumped, third["same"], "a file already there with the same bytes is used as it is")

    def test_the_anonymous_api_without_gh(self) -> None:
        rec = self.shared(PLAN)
        self.colleague()
        api = FakeApi(self.ghdir)
        self.addCleanup(api.close)
        with mock.patch.dict(os.environ, {"BLUEDOC_GITHUB_API": api.url, "STANDIN_GH_AUTH": "signed-out"}):
            self.forget()
            got = self.imported(rec["link"], self.repo / "docs" / "plans")
            self.assertTrue(got["path"].is_file())
            self.assertEqual(api.asked[0][0], f"/gists/{rec['id']}")
            self.assertIsNone(api.asked[0][2], "no token")
            etag = load_json(importer.copies_file())[str(got["path"])]["etag"]
            self.assertEqual(importer.fetch(rec["id"], etag)["status"], 304)
            api.refuse = (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(time.time()) + 1800)})
            with self.assertRaises(importer.ImportFailed) as cm:
                importer.load(rec["link"])
            self.assertEqual(cm.exception.status, 429)
            self.assertRegex(str(cm.exception), r"60 requests an hour per IP address.*Try again after \d\d:\d\d.*gh auth login")
            api.refuse, api.truncate = None, f"{PLAN}.bluedoc.json"
            api.raw = "https://example.com/raw"
            with self.assertRaises(importer.ImportFailed) as cm:
                importer.load(rec["link"])
            self.assertIn("gist.githubusercontent.com", str(cm.exception), "a truncated file is read only from GitHub's raw host")

    def test_gh_reads_with_its_etag(self) -> None:
        rec = self.shared(PLAN)
        got = importer.fetch(rec["id"])
        self.assertEqual(got["status"], 200)
        self.assertEqual(importer.fetch(rec["id"], got["etag"]), {"status": 304, "etag": got["etag"], "data": None, "via": "gh"})
        with self.assertRaises(importer.ImportFailed) as cm:
            importer.fetch("0123456789abcdef0123")
        self.assertEqual(cm.exception.status, 404)

    def test_paths_that_leave_the_folder_are_refused_before_anything_is_written(self) -> None:
        rec = self.shared(PLAN)
        self.colleague()
        b = importer.load(rec["link"])
        folder = self.repo / "docs" / "plans"
        for bad in ("../evil.svg", "/etc/evil.svg", "media/../../evil.svg", "media\\evil.svg", "media//evil.svg", "C:/evil.svg"):
            with self.subTest(path=bad), self.assertRaises(importer.ImportFailed):
                importer.write({**b, "files": {**b["files"], bad: b"<svg/>"}}, folder)
        self.assertFalse(folder.exists() and any(folder.iterdir()), "nothing written")
        (self.repo / "elsewhere").mkdir()
        folder.mkdir(parents=True)
        (folder / "media").symlink_to(self.repo / "elsewhere")
        with self.assertRaises(importer.ImportFailed) as cm:
            importer.write(b, folder)
        self.assertIn("symlink", str(cm.exception))
        self.assertEqual(list((self.repo / "elsewhere").iterdir()), [])
        self.assertFalse((folder / f"{PLAN}.bluedoc.json").exists())
        with self.assertRaises(importer.ImportFailed):
            importer.write({**b, "stem": "../acme"}, self.repo / "other")

    def test_the_size_caps(self) -> None:
        rec = self.shared(PLAN)
        self.colleague()
        b = importer.load(rec["link"])
        folder = self.repo / "caps"
        with mock.patch.object(importer, "MAX_FILE", 100), self.assertRaises(importer.ImportFailed) as cm:
            importer.write(b, folder)
        self.assertEqual(cm.exception.status, 413)
        with mock.patch.object(importer, "MAX_FILES", 1), self.assertRaises(importer.ImportFailed):
            importer.write(b, folder)
        with mock.patch.object(importer, "MAX_TOTAL", 1000), self.assertRaises(importer.ImportFailed):
            importer.write(b, folder)
        with mock.patch.object(importer, "MAX_FILES", 2), self.assertRaises(importer.ImportFailed):
            importer.gist_texts({"files": {f"f{i}": {"content": "x"} for i in range(3)}})
        self.assertFalse(folder.exists())

    def test_a_doc_that_doesn_t_validate_names_the_share_s_version(self) -> None:
        rec = self.shared(PLAN)
        f = self.ghdir / "gists" / rec["id"] / "files" / f"{PLAN}.bluedoc.json"
        doc = json.loads(f.read_text(encoding="utf-8"))
        doc["sections"][0]["blocks"].append({"type": "hologram"})
        f.write_text(json.dumps(doc), encoding="utf-8")
        p = self.ghdir / "gists" / rec["id"] / "files" / "bluedoc-page.json"
        page = json.loads(p.read_text(encoding="utf-8"))
        page["version"] = "99.0.0"
        p.write_text(json.dumps(page), encoding="utf-8")
        with self.assertRaises(importer.ImportFailed) as cm:
            importer.write(importer.load(rec["link"]), self.repo / "x")
        self.assertIn("bluedoc 99.0.0", str(cm.exception))
        self.assertIn("update bluedoc", str(cm.exception))

    def test_a_zip_from_download_imports_and_still_pulls(self) -> None:
        rec = self.shared(PLAN)
        self.colleague()
        doc_text = self.doc(PLAN).read_text(encoding="utf-8")
        media = sorted(share._media_srcs(load_json(self.doc(PLAN)), set()))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:   # as the shared page writes it
            z.writestr(f"{PLAN}.bluedoc.json", doc_text)
            for m in media:
                z.writestr(m, (self.docs / m).read_bytes())
            z.writestr("bluedoc-share.json", json.dumps({"by": "acme-dev", "link": rec["link"]}))
        zp = self.tmp.dir / f"{PLAN}.zip"
        zp.write_bytes(buf.getvalue())
        got = self.imported(str(zp), self.repo / "docs" / "plans")
        self.assertEqual(load_json(got["path"])["meta"]["copiedFrom"]["by"], "acme-dev")
        self.assertEqual(load_json(importer.copies_file())[str(got["path"])]["id"], rec["id"], "the zip's link: the copy pulls")
        bad = self.tmp.dir / "evil.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr(f"{PLAN}.bluedoc.json", doc_text)
            z.writestr("../evil.svg", "<svg/>")
        with self.assertRaises(importer.ImportFailed):
            importer.write(importer.load(str(bad)), self.repo / "zips")
        self.assertFalse((self.repo / "zips").exists())


class Merge(unittest.TestCase):
    BASE = {"title": "Acme carts", "meta": {"type": "plan", "rev": "1"}, "sections": [
        {"id": "a", "title": "Context", "lead": "Carts last a day.", "blocks": [{"type": "text", "md": "One"}, {"type": "text", "md": "Two"}]},
        {"id": "b", "title": "Steps", "blocks": [{"type": "steps", "items": [{"id": "s1", "title": "API"}, {"id": "s2", "title": "UI"}]}]},
        {"id": "c", "title": "Risks", "blocks": [{"type": "text", "md": "None"}]}]}

    def edit(self, f) -> dict:
        d = json.loads(json.dumps(self.BASE))
        f(d)
        return d

    def test_only_theirs_takes_theirs_only_mine_keeps_mine(self) -> None:
        mine = self.edit(lambda d: d["sections"][0]["blocks"][0].update(md="One, mine"))
        theirs = self.edit(lambda d: d["sections"][0]["blocks"][1].update(md="Two, theirs") or d["sections"][0].update(lead="Carts last 180 days."))
        out, review = importer.merge3(self.BASE, mine, theirs)
        a = out["sections"][0]
        self.assertEqual([b["md"] for b in a["blocks"]], ["One, mine", "Two, theirs"])
        self.assertEqual(a["lead"], "Carts last 180 days.")
        self.assertEqual(review, [])

    def test_both_changed_keeps_mine_under_review(self) -> None:
        mine = self.edit(lambda d: d["sections"][0]["blocks"][0].update(md="Mine"))
        theirs = self.edit(lambda d: d["sections"][0]["blocks"][0].update(md="Theirs"))
        out, review = importer.merge3(self.BASE, mine, theirs)
        self.assertEqual(out["sections"][0]["blocks"][0]["md"], "Mine")
        self.assertEqual([(r["label"], r["theirs"]["md"]) for r in review], [("Context: text", "Theirs")])

    def test_items_by_id_and_sections_added_or_removed(self) -> None:
        def mine_f(d):
            d["sections"][1]["blocks"][0]["items"][0]["title"] = "API, mine"
            d["sections"] = [s for s in d["sections"] if s["id"] != "c"]
        def theirs_f(d):
            d["sections"][1]["blocks"][0]["items"].append({"id": "s3", "title": "Docs"})
            d["sections"][1]["blocks"][0]["items"][1]["title"] = "UI, theirs"
            d["sections"].insert(1, {"id": "n", "title": "New", "blocks": [{"type": "text", "md": "Added"}]})
        out, review = importer.merge3(self.BASE, self.edit(mine_f), self.edit(theirs_f))
        self.assertEqual([s["id"] for s in out["sections"]], ["a", "n", "b"], "theirs' new section after its neighbour; mine's removal stands")
        self.assertEqual([i["title"] for i in out["sections"][2]["blocks"][0]["items"]], ["API, mine", "UI, theirs", "Docs"])
        self.assertEqual(review, [])

    def test_a_removal_against_an_edit_is_reviewed(self) -> None:
        mine = self.edit(lambda d: d["sections"][2]["blocks"][0].update(md="Some"))
        theirs = self.edit(lambda d: d.update(sections=d["sections"][:2]))
        out, review = importer.merge3(self.BASE, mine, theirs)
        self.assertEqual([s["id"] for s in out["sections"]], ["a", "b", "c"], "kept, as mine changed it")
        self.assertTrue(review[0]["gone"] and "the sharer removed it" in review[0]["label"])
        doc = json.loads(json.dumps(out))
        importer._set_at(doc, review[0]["path"], None)
        self.assertEqual([s["id"] for s in doc["sections"]], ["a", "b"], "Take theirs removes it")


class Served(Copies):
    """The copy in the colleague's home, served; the sharer updates; the copy's page checks, compares and pulls."""

    def setUp(self) -> None:
        super().setUp()
        self.rec = self.shared(PLAN, answers={"by": "acme-dev", "at": "2026-11-16T10:00:00+00:00", "rev": "1",
                                              "state": {"decisions:retention": "=d180|", "decisions:retention:thread": "[]"}})
        self.colleague()
        self.copy = self.imported(self.rec["link"], self.repo / "docs" / "plans")["path"]
        self.assertEqual(self.tmp.run("serve.py", "add", self.repo / "docs").returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.url = self.server.url_for(self.copy)

    def up(self, method: str = "GET", key: bool = True, **body) -> tuple[int, dict]:
        h = {"X-Bluedoc": "1", "Content-Type": "application/json", **({} if key else {"X-Bluedoc-Key": "wrong"})}
        if method == "GET":
            s, raw = self.server.req("GET", f"/__bluedoc/upstream?path={quote(self.url)}&{'&'.join(f'{k}={v}' for k, v in body.items())}", headers=h)
        else:
            s, raw = self.server.req("POST", "/__bluedoc/upstream", json.dumps({"path": self.url, **body}).encode(), h)
        return s, json.loads(raw)

    def sharer_update(self) -> None:
        """acme-dev's rev 2: a new lead in Approach and in Steps."""
        def f(d):
            d["meta"]["rev"] = "2"
            d["changes"] = ["Said how long carts last"]
            d["sections"][1]["lead"] = "Carts last 180 days, then go."
            d["sections"][2]["lead"] = "The API first."
        os.environ["BLUEDOC_HOME"] = self.tmp.env["BLUEDOC_HOME"] = str(self.sharer_home)
        self.shared(PLAN, edit=f)
        self.colleague()



class Upstream(Served, unittest.TestCase):
    def test_the_page_shows_the_origin_and_the_sharer_s_answers(self) -> None:
        s, html = self.server.req("GET", self.url)
        self.assertEqual(s, 200)
        slot = html.decode().split('id="bp-answers">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(slot)["state"]["decisions:retention"], "=d180|", "copies.json's answers fill the slot")
        self.assertNotIn(self.rec["id"].encode(), html, "no gist id in the page")
        self.assertEqual(self.up(key=False)[0], 403, "the key, as copies.json holds the link")
        s, j = self.up()
        self.assertEqual((s, j["copy"]["by"], j["copy"]["newer"], j["copy"]["answers"]), (200, "acme-dev", None, True))

    def test_a_newer_rev_shows_compares_and_pulls_with_review(self) -> None:
        self.sharer_update()
        # the colleague's own rev 2: one lead both changed, the context's text only theirs
        doc = load_json(self.copy)
        doc["meta"]["rev"] = "2"
        doc["changes"] = ["Named the owner"]
        doc["sections"][1]["lead"] = "Acme's mobile team decides how long carts last."
        doc["sections"][0]["blocks"][0]["md"] += "\n\nAcme's mobile team owns this."
        build.write_doc(self.copy, doc)
        build.sync_history(self.copy, doc)
        calls = len(self.calls())
        s, j = self.up()
        self.assertEqual(j["copy"]["newer"], None, "checked at most every 15 minutes")
        self.assertEqual(len(self.calls()), calls)
        s, j = self.up(fresh="1")
        self.assertEqual(j["copy"]["newer"], {"rev": "2", "changed": 2})
        self.assertIn(["api", "-i", "-H"], [c["argv"][:3] for c in self.calls()][calls:], "a conditional read")
        s, html = self.server.req("GET", self.url + "?theirs=1&diff=2")
        self.assertEqual(s, 200)
        self.assertIn(b"Carts last 180 days, then go.", html, "Compare draws the sharer's rev")
        self.assertEqual(load_json(self.copy)["sections"][1]["lead"], "Acme's mobile team decides how long carts last.", "Compare writes nothing")
        self.assertEqual(self.up("POST", key=False, action="pull")[0], 403)
        s, j = self.up("POST", action="pull")
        self.assertEqual((s, j["rev"]), (200, "3"))
        out = load_json(self.copy)
        self.assertEqual(out["changes"], ["Pulled acme-dev's rev 2"])
        self.assertEqual(out["meta"]["copiedFrom"]["rev"], "2")
        self.assertEqual(out["sections"][2]["lead"], "The API first.", "only theirs changed it: theirs")
        self.assertTrue(out["sections"][0]["blocks"][0]["md"].endswith("Acme's mobile team owns this."), "only mine: mine")
        self.assertEqual(out["sections"][1]["lead"], "Acme's mobile team decides how long carts last.", "both: mine")
        self.assertEqual([r["label"] for r in j["review"]], ["Approach: its lead"])
        self.assertEqual([r["rev"] for r in load_json(build.history_path(self.copy))["revs"]], ["1", "2", "3"], "Pull is a new rev")
        s, j = self.up()
        self.assertEqual((j["copy"]["newer"], len(j["copy"]["review"])), (None, 1))
        s, j = self.up("POST", action="take", id=j["copy"]["review"][0]["id"])
        self.assertEqual((s, j["review"]), (200, []))
        self.assertEqual(load_json(self.copy)["sections"][1]["lead"], "Carts last 180 days, then go.", "Take theirs")

    def test_later_hides_the_rev_until_a_newer_one(self) -> None:
        self.sharer_update()
        self.up(fresh="1")
        self.assertEqual(self.up("POST", action="later"), (200, {"ok": True}))
        self.assertIsNone(self.up()[1]["copy"]["newer"])

    def test_use_these_answers_makes_the_picks_the_reader_s(self) -> None:
        self.assertEqual(self.up("POST", key=False, action="answers")[0], 403)
        s, j = self.up("POST", action="answers")
        self.assertEqual((s, j["used"]), (200, 1), "the pick; the sharer's thread stays theirs")
        st = json.loads(self.server.req("GET", f"/__bluedoc/state?path={quote(self.url)}", headers={"X-Bluedoc": "1"})[1])["state"]
        self.assertEqual({k: v for k, v in st.items() if "retention" in k}, {"decisions:retention": "=d180|"})


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class CopyPage(Served, unittest.TestCase):
    """The copy's page in Chrome: the origin line, the sharer's answer beside the reader's own, Use these answers, the
    update strip's Compare, Pull and Later, Review's Take theirs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = Path(tempfile.mkdtemp(prefix="bluedoc-chrome-"))
        cls.browser = Browser(cls.profile)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        shutil.rmtree(cls.profile, ignore_errors=True)

    def tab(self, path: str = "") -> Tab:
        token = json.loads(self.server.req("POST", "/__bluedoc/unlock", b"{}", {"X-Bluedoc": "1", "Content-Type": "application/json"})[1])["token"]
        t = Tab(self.browser)
        t.go(f"http://{self.server.host}{self.url}?key={token}")
        if path:
            t.go(f"http://{self.server.host}{path}")
        return t

    def test_the_origin_line_and_the_sharer_s_answers(self) -> None:
        self.browser.errors.clear()
        t = self.tab()
        line = t.wait_for("document.querySelector('.bd-head .bd-origin')?.textContent")
        self.assertIn("Copied from acme-dev's plan, rev 1", line)
        self.assertIn("acme-dev's answers show as theirs", line)
        self.assertEqual(t.ev("[...document.querySelectorAll('#item-decisions-retention .bd-ansby')].map(e => e.closest('[data-id]').dataset.id)"), ["d180"])
        self.assertEqual(t.ev("document.querySelectorAll('.bd-revbar.upd').length"), 0, "no newer rev")
        t.ev("[...document.querySelectorAll('.bd-origin .bp-btn')].find(b => b.textContent === 'Use these answers').click()")
        t.wait_for("document.getElementById('bp-toast')?.textContent.includes('now yours')")
        st = json.loads(self.server.req("GET", f"/__bluedoc/state?path={quote(self.url)}", headers={"X-Bluedoc": "1"})[1])["state"]
        self.assertEqual(st.get("decisions:retention"), "=d180|")
        self.assertEqual(self.browser.errors, [])

    def test_the_strip_compares_pulls_and_reviews(self) -> None:
        self.browser.errors.clear()
        self.sharer_update()
        doc = load_json(self.copy)
        doc["meta"]["rev"], doc["changes"] = "2", ["Named the owner"]
        doc["sections"][1]["lead"] = "Acme's mobile team decides how long carts last."
        build.write_doc(self.copy, doc)
        build.sync_history(self.copy, doc)
        importer.update(self.copy, checked=0)
        t = self.tab()
        strip = t.wait_for("document.querySelector('.bd-revbar.upd.new')?.textContent")
        self.assertIn("acme-dev updated this to rev 2", strip)
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-revbar.upd.new .bp-btn')].map(b => b.textContent)"), ["Compare", "Pull", "Later"])
        self.assertEqual(t.ev("new URL(document.querySelector('.bd-revbar.upd.new a.bp-btn').href).search"), "?theirs=1&diff=2")
        t2 = self.tab(self.url + "?theirs=1&diff=2")
        self.assertIn("The sharer's newer rev", t2.wait_for("document.querySelector('.bd-revbar.upd.cmp')?.textContent"))
        self.assertIn("Carts last 180 days", t2.ev("document.body.innerText"))
        t.ev("[...document.querySelectorAll('.bd-revbar.upd.new .bp-btn')].find(b => b.textContent === 'Pull').click()")
        t.wait_for("document.querySelector('.bd-revbar.upd.rv')?.textContent.includes('Review · 1')", 15)
        self.assertEqual(load_json(self.copy)["meta"]["rev"], "3")
        t.ev("document.querySelector('.bd-revbar.upd.rv .bp-btn').click()")
        self.assertEqual(t.wait_for("[...document.querySelectorAll('dialog.bd-rvw .rvr .l')].map(e => e.textContent)"), ["Approach: its lead"])
        t.ev("document.querySelector('dialog.bd-rvw .rvr .cp').click()")
        t.wait_for("document.querySelector('dialog.bd-rvw .rvl')?.textContent.includes('Nothing left')")
        self.assertEqual(load_json(self.copy)["sections"][1]["lead"], "Carts last 180 days, then go.")
        self.assertEqual(self.browser.errors, [])


class ImportBase(Copies):
    def setUp(self) -> None:
        super().setUp()
        self.rec = self.shared(PLAN)
        self.colleague()
        (self.repo / "docs").mkdir()
        self.assertEqual(self.tmp.run("serve.py", "add", self.repo / "docs").returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.src = code(self.rec["id"])

    def written(self) -> list:
        return sorted(p.relative_to(self.repo).as_posix() for p in self.repo.rglob("*") if p.is_file())


class ImportPage(ImportBase, unittest.TestCase):

    def test_the_page_opens_from_bluedoc_ai_or_no_referer_and_never_another_site(self) -> None:
        for ref, want in ((None, 200), ("https://bluedoc.ai/g/" + self.src, 200), (f"http://{self.server.host}/", 200),
                          ("https://evil.example/", 403), ("http://bluedoc.ai/", 403), ("https://bluedoc.ai.evil.example/", 403)):
            with self.subTest(ref=ref):
                s, h, body = self.server.exchange("GET", f"/__bluedoc/import?src={self.src}", headers={"Referer": ref} if ref else {})
                self.assertEqual(s, want)
                if want == 200:
                    self.assertIn(b"ImportPage", body)
                    self.assertEqual(h.get("referrer-policy"), "no-referrer")
        self.assertEqual(self.written(), [], "the page writes nothing")

    def test_the_preview_writes_nothing_and_lists_every_file(self) -> None:
        self.assertEqual(self.server.req("GET", f"/__bluedoc/import.json?src={self.src}")[0], 403, "our own page only")
        s, raw = self.server.req("GET", f"/__bluedoc/import.json?src={self.src}", headers={"X-Bluedoc": "1"})
        j = json.loads(raw)
        self.assertEqual(s, 200)
        self.assertEqual((j["by"], j["type"], j["name"]), ("acme-dev", "plan", f"{PLAN}.bluedoc.json"))
        media = sorted(share._media_srcs(load_json(self.doc(PLAN)), set()))
        self.assertEqual([f["path"] for f in j["files"]], [f"{PLAN}.bluedoc.json", *media])
        self.assertEqual(j["folders"][0]["dir"], str((self.repo / "docs" / "plans").resolve()))
        self.assertTrue(j["unlocked"])
        self.assertEqual(self.written(), [])

    def test_save_needs_the_key_and_this_page_s_origin(self) -> None:
        root = str((self.repo / "docs").resolve())
        body = json.dumps({"src": self.src, "root": root}).encode()
        for h in ({"X-Bluedoc-Key": "wrong"}, {"Origin": "https://bluedoc.ai"}, {"Sec-Fetch-Site": "cross-site"}, {"X-Bluedoc": "0"}):
            with self.subTest(h=h):
                s, _ = self.server.req("POST", "/__bluedoc/import", body, {"X-Bluedoc": "1", "Content-Type": "application/json", **h})
                self.assertEqual(s, 403)
        self.assertEqual(self.written(), [], "nothing written without Save")
        s, raw = self.server.req("POST", "/__bluedoc/import", json.dumps({"src": self.src, "root": str(self.tmp.dir)}).encode(),
                                 {"X-Bluedoc": "1", "Content-Type": "application/json"})
        self.assertEqual(s, 400, "a folder that isn't the home page's")
        s, raw = self.server.req("POST", "/__bluedoc/import", body, {"X-Bluedoc": "1", "Content-Type": "application/json", "Sec-Fetch-Site": "same-origin"})
        j = json.loads(raw)
        self.assertEqual(s, 200)
        self.assertEqual(j["path"], str((self.repo / "docs" / "plans" / f"{PLAN}.bluedoc.json").resolve()))
        self.assertEqual(self.server.req("GET", j["url"])[0], 200, "registered: the copy opens")
        self.assertIn(f"docs/plans/{PLAN}.bluedoc.json", self.written())


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ImportPageInChrome(ImportBase, unittest.TestCase):
    """The import page as bluedoc.ai's Make a copy opens it: the sharer, every file, the folder, Save and open."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = Path(tempfile.mkdtemp(prefix="bluedoc-chrome-"))
        cls.browser = Browser(cls.profile)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        shutil.rmtree(cls.profile, ignore_errors=True)

    def test_save_and_open(self) -> None:
        self.browser.errors.clear()
        t = Tab(self.browser)
        t.ev("window.__bdLeft = true")
        self.browser.call("Page.navigate", {"url": f"http://{self.server.host}/__bluedoc/import?src={self.src}", "referrer": "https://bluedoc.ai/"}, t.session)
        text = t.wait_for("document.querySelector('.bd-imp-card')?.innerText")
        self.assertIn("Save a copy of acme-dev's plan?", text)
        self.assertIn(f"{PLAN}.bluedoc.json", text)
        self.assertIn("This browser can't save yet.", text, "no key here yet")
        self.assertEqual(self.written(), [])
        token = json.loads(self.server.req("POST", "/__bluedoc/unlock", b"{}", {"X-Bluedoc": "1", "Content-Type": "application/json"})[1])["token"]
        self.browser.call("Page.navigate", {"url": f"http://{self.server.host}/?key={token}"}, t.session)
        t.wait_for("location.search === '' && document.readyState === 'complete' && !!document.querySelector('.bd-app')")
        self.browser.call("Page.navigate", {"url": f"http://{self.server.host}/__bluedoc/import?src={self.src}"}, t.session)
        t.wait_for("document.querySelector('.bd-imp-card') && !document.querySelector('.bd-imp-card').innerText.includes(\"can't save\")")
        self.assertEqual(t.ev("document.querySelector('.bd-imp-path').textContent").rstrip("/").split("/")[-2:], ["docs", "plans"])
        t.ev("[...document.querySelectorAll('.bd-imp-acts button')].find(b => b.textContent === 'Save and open').click()")
        t.wait_for(f"location.pathname.endsWith('/{PLAN}.bluedoc.json') && !!window.BP", 15)
        self.assertIn(f"docs/plans/{PLAN}.bluedoc.json", self.written())
        self.assertIn("Copied from acme-dev's plan", t.wait_for("document.querySelector('.bd-origin')?.textContent"))
        self.assertEqual(self.browser.errors, [])


class Cli(Copies, unittest.TestCase):
    def test_import_prints_what_it_wrote_and_the_copy_s_url(self) -> None:
        rec = self.shared(PLAN)
        home = self.colleague()
        self.cli_server()
        self.tmp.env["BLUEDOC_HOME"] = str(home)
        r = self.tmp.run("serve.py", "import", rec["link"], "--to", self.repo / "plans")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertRegex(lines[0], rf"^copied acme-dev's plan, rev 1 to .*/plans/{PLAN}\.bluedoc\.json \(2 files written\)$")
        self.assertIn("changes don't go back: to send them, share the copy", r.stdout)
        self.assertRegex(lines[-1], rf"^http://127\.0\.0\.1:\d+/.*{PLAN}\.bluedoc\.json\?key=")
        r = self.tmp.run("serve.py", "import", "https://bluedoc.ai/g/AAAAAAAAAAAAAAAAAAAAAA")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no such gist", r.stderr)


if __name__ == "__main__":
    unittest.main()
