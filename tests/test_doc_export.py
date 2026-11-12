"""Any doc but a presentation or a storelisting exported: GET /__bluedoc/export and the app bar's Export.

The route sends the file `build.py -o` writes, byte for byte, as the attachment <stem>.html for every example type
(docs, plan, review, other, design, website): a read with no key, a design's screens inline and nothing to fetch;
rev=B is that revision's file (its doc, the revisions up to it, its recorded screens), theme=dark the page's theme it
starts in. format=pdf is that file's print view through headless Chrome (a stand-in Chrome in process, started with
the flag that keeps sandboxed frames in the page's process; the real one with BLUEDOC_BROWSER_TESTS=1), 501 naming
BLUEDOC_CHROME without it; a design's or website's PDF has one page per artboard after its header and brief, and the
exported file's print sheet holds every artboard in board order. A presentation, a storelisting, an unknown path,
revision or format are a 400. In Chrome the served plan, review and design pages have Export in the app bar before
the ⋯ menu (HTML file, PDF), a deck and a listing don't, and neither does the exported file over file://; HTML saves
<stem>.html from the route at the revision shown; without Chrome on the server PDF opens the print dialog and says so.
At 390 px the key keeps its icon and chevron."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from _support import Server, TempHome, load_json
from test_design import EXPORT_SPY
from test_page_state import CHROME, Browser, ChromePage, Tab

import build
import serve

STEMS = {"acme-orders": "Acme order path: checkout to pick ticket", "acme-saved-carts-plan": "Acme Shop: saved carts",
         "acme-review-findings": "Review findings: acme-shop #412 and #415", "acme-status": "Acme shop status, week 41",
         "acme-fit-design": "Acme Fit: watch, phone and web mockups", "acme-site": "Acme Fit: marketing site, spring refresh"}
EXPORT_FETCHES = "__fetched.map(u => new URL(u, location.href)).filter(u => u.pathname === '/__bluedoc/export')"


def data_block(html: str, block_id: str):
    m = re.search(rf'<script type="application/json" id="{block_id}">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


class ExportRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)

    def export(self, stem: str, **q: str) -> tuple[int, dict, bytes]:
        url = self.server.url_for(self.docs / f"{stem}.bluedoc.json")
        query = "&".join(f"{k}={quote(v)}" for k, v in {"path": url, **q}.items())
        return self.server.exchange("GET", f"/__bluedoc/export?{query}", timeout=120)

    def test_every_doc_type_downloads_the_o_file(self) -> None:
        for stem, title in STEMS.items():
            with self.subTest(stem=stem):
                status, headers, body = self.export(stem)
                self.assertEqual(status, 200, body[:300])
                self.assertTrue(headers["content-disposition"].startswith(f'attachment; filename="{stem}.html"'), headers)
                self.assertTrue(headers["content-type"].startswith("text/html"))
                html = body.decode("utf-8")
                self.assertIn(f"<title>{title.replace('&', '&amp;')}</title>", html)
                self.assertIsNone(data_block(html, "bp-state"), "no reader state: the file keeps its own")
                self.assertIsNone(data_block(html, "bp-live"), "no live-page proxies: they need the server")
                self.assertEqual(re.findall(r'\b(?:src|href)="(?!data:|#|\$\{)[^"]+"', html), [], "nothing for the file to fetch")
        out = self.tmp.dir / "out.html"
        r = self.tmp.run("build.py", self.docs / "acme-fit-design.bluedoc.json", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        _, _, body = self.export("acme-fit-design")
        self.assertEqual(body, out.read_bytes(), "the route sends what `build.py -o` writes")
        screens = data_block(body.decode("utf-8"), "bp-screens")
        self.assertEqual(sorted(screens), sorted(a["id"] for a in build._artboards(load_json(self.docs / "acme-fit-design.bluedoc.json"))))
        # each screen carries the inspector inline (serve.raw_text escapes a comment opener there): none may be in it,
        # or its script doesn't parse and the screen never says it's ready (a print would wait on nothing)
        self.assertEqual([aid for aid, html in screens.items() if "<\\!--" in html], [])

    def test_an_earlier_revision_is_its_own_file(self) -> None:
        # a file of one revision carries no revision list (embed_history); rev B of the design, A and B
        for stem, rev, revs in (("acme-status", "1", []), ("acme-fit-design", "B", ["A", "B"])):
            with self.subTest(stem=stem):
                status, _, body = self.export(stem, rev=rev)
                self.assertEqual(status, 200, body[:300])
                html = body.decode("utf-8")
                self.assertEqual(data_block(html, "bp-doc")["meta"]["rev"], rev)
                self.assertEqual([e["rev"] for e in (data_block(html, "bp-hist") or {"revs": []})["revs"]], revs, "the revisions up to it")
        screens = data_block(self.export("acme-fit-design", rev="B")[2].decode("utf-8"), "bp-screens")
        for aid, html in screens.items():   # each is rev B's text from the history, wrapped in its kit
            source = build.screen_source(self.docs / "acme-fit-design.bluedoc.json", aid, "B")
            self.assertIsNotNone(source, aid)
            names = re.findall(r'data-bd="[^"]+"', source)
            self.assertTrue(names and all(n in html for n in names), aid)
        self.assertNotEqual(sorted(screens), sorted(data_block(self.export("acme-fit-design")[2].decode("utf-8"), "bp-screens")))
        self.assertEqual(self.export("acme-status", rev="2")[2], self.export("acme-status")[2], "the current rev is the doc")
        status, _, body = self.export("acme-status", rev="9")
        self.assertEqual(status, 400)
        self.assertIn("no revision 9", json.loads(body)["error"])

    def test_the_theme_it_starts_in(self) -> None:
        html = self.export("acme-orders", theme="dark")[2].decode("utf-8")
        self.assertTrue(html.startswith('<!doctype html>\n<html data-theme="dark" lang="en">'), html[:80])
        self.assertTrue(self.export("acme-orders", theme="sepia")[2].decode("utf-8").startswith('<!doctype html>\n<html lang="en">'))

    def test_decks_listings_unknown_paths_and_formats_are_refused(self) -> None:
        for stem, says in (("acme-fit-deck", "a presentation exports from its board's Export to…"),
                           ("acme-fit-listing", "a storelisting exports from its Export to…")):
            for fmt in ("html", "pdf"):
                status, _, body = self.export(stem, format=fmt)
                self.assertEqual(status, 400, (stem, fmt))
                self.assertIn(says, json.loads(body)["error"])
        status, _, _ = self.server.exchange("GET", "/__bluedoc/export?path=" + quote("/docs/acme-gone.bluedoc.json"))
        self.assertEqual(status, 400)
        self.assertEqual(self.export("acme-orders", format="docx")[0], 400)
        url = self.server.url_for(self.docs / "acme-orders.bluedoc.json")
        status, _, _ = self.server.exchange("GET", f"/__bluedoc/export?path={quote(url)}", headers={"Host": "evil.example:80"})
        self.assertEqual(status, 403)

    def test_a_pdf_without_chrome_is_a_501(self) -> None:
        self.server.stop()
        self.tmp.env["BLUEDOC_CHROME"] = str(self.tmp.dir / "no-chrome")
        self.server.start()
        status, _, body = self.export("acme-saved-carts-plan", format="pdf")
        self.assertEqual(status, 501, body[:300])
        self.assertIn("set BLUEDOC_CHROME to its path", json.loads(body)["error"])
        self.assertEqual(self.export("acme-saved-carts-plan")[0], 200, "HTML needs no Chrome")

    @unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
    def test_the_pdf_downloads_as_an_attachment(self) -> None:
        for stem in ("acme-saved-carts-plan", "acme-fit-design"):
            with self.subTest(stem=stem):
                status, headers, body = self.export(stem, format="pdf")
                self.assertEqual(status, 200, body[:300])
                self.assertEqual(headers["content-type"], "application/pdf")
                self.assertTrue(headers["content-disposition"].startswith(f'attachment; filename="{stem}.pdf"'), headers)
                self.assertTrue(body.startswith(b"%PDF-"))
                self.assertGreaterEqual(len(re.findall(rb"/Type\s*/Page\b", body)), 1)


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class BoardPdf(unittest.TestCase):
    """A design's or website's PDF prints every artboard on a page of its own, after the header and the brief: the
    doc with all its artboards takes exactly one page more per artboard than the same doc with its first alone."""

    def pages(self, doc: dict, doc_path: Path) -> int:
        doc_path.write_text(json.dumps(doc), encoding="utf-8")
        pdf = serve.doc_export_pdf(serve.doc_export_html(doc, doc_path), CHROME)
        return len(re.findall(rb"/Type\s*/Page\b", pdf))

    def test_one_page_per_artboard(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        docs = tmp.copy_examples()
        for stem in ("acme-fit-design", "acme-site"):
            with self.subTest(stem=stem):
                doc_path = docs / f"{stem}.bluedoc.json"
                doc = load_json(doc_path)
                board = next(b for b in build.all_blocks(doc) if b.get("type") == "board")
                n = len(board["artboards"])
                self.assertGreater(n, 1)
                every = self.pages(doc, doc_path)
                board["artboards"] = board["artboards"][:1]
                self.assertEqual(every - self.pages(doc, doc_path), n - 1, f"{stem}: {every} pages for {n} artboards")


class StandInChrome:
    """serve.HeadlessChrome for doc_export_pdf without Chrome: print_pdf keeps the file it was given and how."""
    printed: list = []

    def __init__(self, path: str, flags: tuple[str, ...] = ()) -> None:
        self.path, self.flags = path, flags

    def __enter__(self) -> "StandInChrome":
        return self

    def __exit__(self, *_) -> None:
        pass

    def print_pdf(self, url: str, ready: str = "", margin: float = 0) -> bytes:
        StandInChrome.printed.append({"url": url, "html": Path(url.removeprefix("file://")).read_text(encoding="utf-8"),
                                      "ready": ready, "margin": margin, "chrome": self.path, "flags": self.flags})
        return b"%PDF-1.7 stand-in"


class ExportPdf(unittest.TestCase):
    def test_chrome_prints_the_file_once_the_page_has_drawn(self) -> None:
        StandInChrome.printed = []
        real = serve.HeadlessChrome
        serve.HeadlessChrome = StandInChrome
        self.addCleanup(setattr, serve, "HeadlessChrome", real)
        doc_path = self.addTempCopy()
        html = serve.doc_export_html(load_json(doc_path), doc_path)
        self.assertEqual(serve.doc_export_pdf(html, "/opt/acme/chrome"), b"%PDF-1.7 stand-in")
        [p] = StandInChrome.printed
        self.assertEqual((p["html"], p["chrome"], p["ready"], p["margin"]), (html, "/opt/acme/chrome", serve.EXPORT_PRINT_READY, serve.EXPORT_PDF_MARGIN))
        self.assertEqual(p["flags"], ("--disable-features=IsolateSandboxedIframes",), "a design's screens print in the page's process")
        self.assertTrue(p["url"].startswith("file://") and "#" not in p["url"], "the file itself, its print view")
        self.assertFalse(Path(p["url"].removeprefix("file://")).exists(), "the temp file goes")

    def addTempCopy(self) -> Path:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        return tmp.copy_examples() / "acme-saved-carts-plan.bluedoc.json"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ExportKey(ChromePage):
    BTN, MENU = "document.querySelector('.bd-bar-r .bd-docx .bd-expb')", "document.querySelector('.bd-bar-r .bd-docx .bd-expm')"

    def page(self, stem: str, query: str = "") -> Tab:
        url = self.server.url_for(self.docs / f"{stem}.bluedoc.json")
        t = self.open(url)
        if query:
            t.go(f"{self.base}{url}?{query}")
        self.assertTrue(t.ev(EXPORT_SPY))
        return t

    def test_doc_pages_have_it_and_a_deck_or_listing_doesnt(self) -> None:
        for stem in ("acme-saved-carts-plan", "acme-review-findings", "acme-fit-design"):
            with self.subTest(stem=stem):
                t = self.page(stem)
                self.assertEqual(t.ev(f"[{self.BTN}.textContent, {self.BTN}.getAttribute('aria-haspopup'), (e => {{ while (e && !e.checkVisibility()) e = e.nextElementSibling; return !!e && e.matches('.bd-docm'); }})({self.BTN}.parentElement.nextElementSibling)]"),
                                 ["Export", "menu", True], "Export, a menu button right before the ⋯ menu (a phone's keys, hidden, between)")
                self.assertEqual(t.ev(f"[...{self.MENU}.querySelectorAll('[role=menuitem]')].map(b => [b.dataset.format, b.querySelector('b').textContent, b.querySelector('.t span').textContent])"),
                                 [["html", "HTML file", "One file that opens in any browser, no server"], ["pdf", "PDF", "Print-ready, one file"]])
                self.assertTrue(t.ev(f"{self.BTN}.parentElement.previousElementSibling.matches('.bd-shk')"), "Share, Export, ⋯")
        for stem in ("acme-fit-deck", "acme-fit-listing"):
            with self.subTest(stem=stem):
                t = self.page(stem)
                self.assertFalse(t.ev("!!document.querySelector('.bd-docx, .bd-shk')"), "a deck and a listing keep their Export to…, and no Share")
        self.assertEqual(self.browser.errors, [])

    def test_html_saves_the_file_of_the_revision_shown(self) -> None:
        t = self.page("acme-saved-carts-plan")
        t.ev(f"{self.BTN}.click()")
        self.assertFalse(t.ev(f"{self.MENU}.hidden"))
        t.ev(f"{self.MENU}.querySelector('[data-format=html]').click()")
        saved = t.wait_for("__saved.length && __saved[0].name && __saved")
        self.assertEqual([(s["type"].split(";")[0], s["name"]) for s in saved], [("text/html", "acme-saved-carts-plan.html")])
        self.assertGreater(saved[0]["size"], 100_000)
        self.assertEqual(t.ev(EXPORT_FETCHES + ".map(u => Object.fromEntries(u.searchParams))"), [{"path": t.ev("location.pathname"), "format": "html"}])
        t = self.page("acme-fit-design", "rev=B")
        t.ev("document.documentElement.dataset.theme = 'dark'")
        t.ev(f"{self.BTN}.click()")
        t.ev(f"{self.MENU}.querySelector('[data-format=html]').click()")
        t.wait_for("__saved.length && __saved[0].name")
        self.assertEqual(t.ev(EXPORT_FETCHES + ".map(u => Object.fromEntries(u.searchParams))"),
                         [{"path": t.ev("location.pathname"), "format": "html", "rev": "B", "theme": "dark"}])
        self.assertEqual(self.browser.errors, [])

    def test_the_pdf_item_says_it_works_and_saves(self) -> None:
        t = self.page("acme-status")
        t.ev(f"{self.BTN}.click()")
        t.ev(f"{self.MENU}.querySelector('[data-format=pdf]').click()")
        pdf = f"{self.MENU}.querySelector('[data-format=pdf]')"
        self.assertEqual(t.ev(f"[{pdf}.getAttribute('aria-busy'), {pdf}.querySelector('.t span').textContent]"), ["true", "Making the PDF…"])
        saved = t.wait_for("__saved.length && __saved[0].name && __saved", timeout=90)
        self.assertEqual([(s["type"], s["name"]) for s in saved], [("application/pdf", "acme-status.pdf")])
        t.wait_for(f"{pdf}.getAttribute('aria-busy') === 'false'")
        self.assertEqual(t.ev(f"{pdf}.querySelector('.t span').textContent"), "Print-ready, one file")
        self.assertEqual(self.browser.errors, [])

    def test_without_chrome_pdf_opens_the_print_dialog(self) -> None:
        self.server.stop()
        self.tmp.env["BLUEDOC_CHROME"] = str(self.tmp.dir / "no-chrome")
        self.server.start()
        t = self.page("acme-saved-carts-plan")
        t.ev("window.__printed = 0; window.print = () => { window.__printed++; }")
        t.ev(f"{self.BTN}.click()")
        t.ev(f"{self.MENU}.querySelector('[data-format=pdf]').click()")
        t.wait_for("window.__printed === 1")
        self.assertIn("no chrome here for a pdf", self.toast(t, "no chrome here").lower())
        t.ev(f"{self.BTN}.click()")   # known now: straight to the print dialog, no second try
        t.ev(f"{self.MENU}.querySelector('[data-format=pdf]').click()")
        t.wait_for("window.__printed === 2")
        self.assertEqual(t.ev(EXPORT_FETCHES + ".length"), 1)

    def test_ctrl_p_on_a_design_prints_once_every_screen_has_drawn(self) -> None:
        t = self.page("acme-fit-design")
        self.browser.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, t.session)
        t.ev("window.__printed = []; window.print = () => { __printed.push([document.querySelectorAll('.bd-psheet .bd-pab').length, BP.printReady()]); }")
        self.assertEqual(t.ev("document.querySelectorAll('.bd-psheet').length"), 0, "the sheet waits for a print")
        for typ in ("keyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": typ, "key": "p", "code": "KeyP", "windowsVirtualKeyCode": 80, "modifiers": 2}, t.session)
        n = len(next(b for b in build.all_blocks(load_json(self.docs / "acme-fit-design.bluedoc.json")) if b.get("type") == "board")["artboards"])
        self.assertEqual(t.wait_for("__printed.length && __printed", 30), [[n, True]], "the dialog opens on the sheet, its screens drawn")
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-psheet iframe')].every(f => new URL(f.src).pathname.includes('.design/'))"), True,
                         "a served page's screens come from the screen route")
        self.assertEqual(self.browser.errors, [])

    def test_a_phone_keeps_its_icon_and_chevron(self) -> None:
        t = self.page("acme-saved-carts-plan")
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 800, "deviceScaleFactor": 2, "mobile": True}, t.session)
        t.wait_for("innerWidth === 390")
        self.assertEqual(t.ev(f"[...{self.BTN}.children].map(e => getComputedStyle(e).display)"), ["block", "none", "block"])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ExportedFile(unittest.TestCase):
    """The exported file over file://: it draws, fetches nothing, and has no Export (no server)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = Path(tempfile.mkdtemp(prefix="bluedoc-chrome-"))
        cls.browser = Browser(cls.profile)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        shutil.rmtree(cls.profile, ignore_errors=True)

    def test_each_file_opens_without_the_server(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        docs = tmp.copy_examples()
        for stem, title in STEMS.items():
            with self.subTest(stem=stem):
                doc_path = docs / f"{stem}.bluedoc.json"
                f = tmp.dir / f"{stem}.html"
                f.write_text(serve.doc_export_html(load_json(doc_path), doc_path, theme="dark"), encoding="utf-8")
                self.browser.errors.clear()
                t = Tab(self.browser)
                self.browser.call("Page.navigate", {"url": f.as_uri()}, t.session)
                t.wait_for("document.readyState === 'complete' && !!window.BP", 20)
                self.assertEqual(t.ev("document.title"), f"{title} · bluedoc")
                self.assertEqual(t.ev("[document.documentElement.dataset.theme, !!document.querySelector('.bd-bar-r'), !!document.querySelector('.bd-docx, .bd-shk')]"),
                                 ["dark", True, False])
                self.assertEqual(t.ev("performance.getEntriesByType('resource').map(e => e.name).filter(u => !/^(data|blob|about):/.test(u))"), [])
                board = next((b for b in build.all_blocks(load_json(doc_path)) if b.get("type") == "board"), None)
                if board:   # its print: every artboard in board order, each screen drawn in the sheet's own frame
                    t.wait_for("BP.printReady()", 30)
                    self.assertEqual(t.ev("[...document.querySelectorAll('.bd-psheet .bd-pab')].map(s => s.dataset.ab)"), [a["id"] for a in board["artboards"]])
                    self.assertEqual(t.ev("document.querySelectorAll('.bd-psheet iframe').length"), sum(not a.get("url") for a in board["artboards"]),
                                     "a live page shows its placeholder in a file")
                self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
