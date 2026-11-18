"""A shared doc as the bluedoc.ai viewer (/g/<code>, or the first links' /g/#<user>/<gist id>) draws it: the -o file's
page, written into a frame of the viewer's page on an http(s) origin with window.bluedocShare = {name, hash} set first
(share/page). It asks no /__bluedoc/ route and has no Share or Export key although its origin is http: its Download
key saves the page itself as <name>.html (it opens anywhere and draws the doc), opens the print dialog for a PDF, and
saves the doc as <name>.md. It is view-only
(share/view-only): no dock, tray or bottom bar, no enabled field in the doc, no comment composer, a click on an option,
a tick or a board's controls changes nothing and stores no key but the view prefs, and the app bar says "Shared · view
only". The doc's own `choice` shows as chosen, and its threads (an item's `replies`) are the Comments section,
read-only. It carries its current revision only (share/current): no Revisions key, and ?rev= and ?diff= in the viewer's
URL show the current revision, with no strip or compare. With the gist's link and files, Make a copy (beside Download)
opens its sheet, and Download has a bluedoc file (.zip) that `serve.py import` takes.

A share may carry the reader's answers (share.answers_slot, the page's __BLUEDOC_ANSWERS__ slot): they show read-only
as the share account's, apart from the doc's own: "<login>'s answer" beside the picked option, Other's words in a row
of their own, "Asked for more", "Done · <login>" on a tick (the box stays the doc's), their messages in the item's
conversation with an image the share carried and "N files not shared", and their sent pins and comments as cards in
the Comments tab. No attachment's path is in the page; a bundle without the slot shows none.

Here a stand-in viewer page on a local http server writes the page as the site's viewer does
(bluedoc-site/src/scripts/viewer.ts), and answers every /g/<code> as GitHub Pages does with its 404.html; the server
records every path asked and sends nothing the browser may cache (a reload reads the page written since). Runs with
BLUEDOC_BROWSER_TESTS=1."""
from __future__ import annotations

import base64
import json
import shutil
import tempfile
import threading
import unittest
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from _support import TempHome, load_json
from test_design import EXPORT_SPY
from test_doc_export import TEXT_SPY, data_block
from test_page_state import CHROME, Browser, Tab

import build
import importer
import share

HASH = "#acme-dev/0123456789abcdef0123"
CODE_PATH = "/g/shaZAB1ze-L25qJChRpj2g"   # the gist b21699001d737be2f6e6a242851a63da
FRAME = "document.getElementById('doc')"
IN = "(w => {})(" + FRAME + " && " + FRAME + ".contentWindow)"
# what a shared page may store: the view prefs (the template's VIEW_PREFS), never reader state
VIEW_PREFS = {"bluedoc:theme", "bluedoc:doc-left-w", "bluedoc:doc-right-w", "bluedoc:design-left-w", "bluedoc:design-right-w", "bluedoc:comments", "bluedoc:sp-tab",
              "bluedoc:design-panel", "bluedoc:listing-panel", "bluedoc:listing-tab"}
# the stand-in viewer: the page into a frame, window.bluedocShare set between open() and write(), as viewer.ts does
# (hash: an old link's fragment; a /g/<code> link's path is enough)
VIEWER = """<!doctype html><meta charset="utf-8"><body style="margin:0"><script>
fetch('/page.html').then(r => r.text()).then(html => {
  const fr = document.createElement('iframe');
  fr.id = 'doc'; fr.style.cssText = 'display:block;width:100vw;height:100vh;border:0';
  document.body.append(fr);
  const d = fr.contentDocument;
  d.open(); fr.contentWindow.bluedocShare = { name: %s, hash: location.pathname.startsWith('/g/') ? '' : location.hash };
  d.write(html); d.close();
});
</script>"""


class Recorder(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def end_headers(self) -> None:
        # never cached: page.html is rewritten within a test, often in the same second, and the handler's
        # Last-Modified has whole seconds, so a reload would get 304 and the page before
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        self.server.paths.append(self.path)
        if self.path.startswith("/g/"):   # GitHub Pages' 404.html, the viewer
            self.path = "/viewer.html"
        super().do_GET()


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class SharedPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = Path(tempfile.mkdtemp(prefix="bluedoc-chrome-"))
        cls.browser = Browser(cls.profile)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        shutil.rmtree(cls.profile, ignore_errors=True)

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.site = self.tmp.dir / "site"
        self.site.mkdir()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(Recorder, directory=str(self.site)))
        self.httpd.paths = []
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.browser.errors.clear()

    def viewer(self, stem: str, answers: dict | None = None, edit=None) -> str:
        """The stand-in viewer for the doc's -o page, with answers (share.answers_slot's object) in its
        __BLUEDOC_ANSWERS__ slot as a share's bluedoc-page.json carries them; edit(doc) changes the doc first. Its URL
        without the fragment."""
        doc_path = self.docs / f"{stem}.bluedoc.json"
        doc = load_json(doc_path)
        if edit:
            edit(doc)
            doc_path.write_text(build.dump_doc(doc), encoding="utf-8")
        fill = build.standalone_fill(doc, doc_path, build.history_now(doc_path, doc), problems=[])
        fill[build.ANSWERS_SLOT] = build._script_json(answers) if answers else "null"
        page = build.fill_page(build.TEMPLATE.read_text(encoding="utf-8"), fill)
        (self.site / "page.html").write_text(page, encoding="utf-8")
        (self.site / "viewer.html").write_text(VIEWER % json.dumps(stem), encoding="utf-8")
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/viewer.html"

    def open(self, t: Tab, url: str, reload: bool = False) -> None:
        """Load url, or reload the tab (a URL that differs only in its fragment would not load again)."""
        t.ev("window.__left = true")
        self.browser.call("Page.reload" if reload else "Page.navigate", {} if reload else {"url": url}, t.session)
        t.wait_for(f"!window.__left && document.readyState === 'complete' && !!{IN.format('w && w.BP')}", 20)

    def asked_routes(self) -> list:
        return [p for p in self.httpd.paths if p.startswith("/__bluedoc/")]

    def q(self, t: Tab, expr: str):
        """expr, with w the doc's window (the viewer's frame)."""
        return t.ev(IN.format(expr))

    def click(self, t: Tab, sel: str) -> bool:
        """A real click (the mouse, through the viewer's page) at the centre of the doc's first sel, scrolled into view;
        False when the doc has none."""
        at = self.q(t, "(e => { if (!e) return null; e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); "
                       f"return [r.x + r.width / 2, r.y + r.height / 2]; }})(w.document.querySelector({json.dumps(sel)}))")
        if not at:
            return False
        for kind in ("mousePressed", "mouseReleased"):
            self.browser.call("Input.dispatchMouseEvent", {"type": kind, "x": at[0], "y": at[1], "button": "left", "clickCount": 1}, t.session)
        return True

    def assert_view_only(self, t: Tab) -> None:
        """No dock or tray, the chip, no enabled field or composer in the doc, nothing stored but the view prefs."""
        self.assertEqual(self.q(t, "[!!w.document.querySelector('.bd-anntb'), w.document.documentElement.classList.contains('bd-tray-on'), "
                                   "!!w.document.querySelector('.bd-cmp, .bd-gc, .bp-note, .bd-selc'), w.BP.setMode('point')]"),
                         [False, False, False, False])
        self.assertEqual(self.q(t, "(c => !!c && c.getClientRects().length > 0 && c.textContent)(w.document.querySelector('.bd-bar .bd-vo'))"),
                         "Shared · view onlyView only")
        fields = self.q(t, "[...w.document.querySelectorAll('input, textarea, select, [contenteditable]:not([contenteditable=\"false\"])')]"
                           ".filter(e => !e.disabled && e.type !== 'hidden' && !e.closest('.bd-btb')).map(e => e.outerHTML.slice(0, 160))")
        self.assertEqual(fields, [])
        self.assertEqual(self.stored(t) - VIEW_PREFS, set())

    def stored(self, t: Tab) -> set:
        return set(self.q(t, "Object.keys(w.localStorage)"))

    def test_a_plan_is_view_only(self) -> None:
        url = self.viewer("acme-saved-carts-plan")
        t = Tab(self.browser)
        self.open(t, url + HASH)
        self.assertEqual(self.q(t, "[w.document.title, !!w.document.querySelector('.bd-bar-r'), !!w.document.querySelector('.bd-shk'), w.document.querySelector('.bd-docx .bd-expb').textContent]"),
                         ["Acme Shop: saved carts · bluedoc", True, False, "Download"])
        # no doc menu: the title is plain text, and the home key leads to the page's top
        self.assertEqual(self.q(t, "[!!w.document.querySelector('.bd-dsw'), w.document.querySelector('.bd-crumb').textContent, w.document.querySelector('.bd-home').getAttribute('href')]"),
                         [False, "/📋Acme Shop: saved carts", "#top"])
        self.assert_view_only(t)
        before = self.q(t, "JSON.stringify(w.BP.replyPayload().items)")
        # a click on an option's radio, on an option's row and on a progress item's tick: nothing picks or ticks
        self.assertTrue(self.click(t, "#item-decisions-retention .bp-opt:not(.on) .pk"))
        self.assertTrue(self.click(t, "#item-decisions-prices .bp-opt:not(.on) .oh"))
        self.assertTrue(self.click(t, ".bp-cl-item:not(.has-choices) > .bp-cl-row > input[type=checkbox]"))
        self.assertEqual(self.q(t, "[w.BP.choose('decisions/retention', 'd180'), w.BP.acceptRecommended(), w.BP.setNote('checks/unit', 'Acme'), "
                                   "w.BP.moreDetails('decisions/retention'), w.BP.annotate({type: 'general', note: 'Acme'})]"),
                         [False, 0, False, False, None])
        self.assertEqual(self.q(t, "JSON.stringify(w.BP.replyPayload().items)"), before)
        self.assertEqual(self.q(t, "[...w.document.querySelectorAll('.bp-cl-item input[type=checkbox]')].filter(e => e.checked).length"), 0)
        # no Need more details, Custom, Accept recommended or Reset (the decision list's ⋯ holds Copy alone); no
        # Comments tab: the doc has no threads
        self.assertEqual(self.q(t, "[w.document.querySelectorAll('.bp-opt.more, .bp-opt.cust').length, "
                                   "[...w.document.querySelectorAll('button')].filter(b => /^(Reset|Accept recommended)/.test(b.textContent.trim())).length, "
                                   "w.document.querySelector('#cl-decisions .bd-ftb [aria-haspopup=menu]').getAttribute('aria-label'), "
                                   "w.BP.sidebar().available.includes('comments')]"), [0, 0, "More: Copy", False])
        # the app bar's right side holds the theme switch alone: no groove after it
        self.assertEqual(self.q(t, "[...w.document.querySelectorAll('.bd-bar-r .bd-groove')].filter(g => g.checkVisibility()).length"), 0)
        self.assert_view_only(t)
        # a reload shows the doc as it is: the clicks above left nothing behind
        self.open(t, url + HASH, reload=True)
        self.assertEqual(self.q(t, "JSON.stringify(w.BP.replyPayload().items)"), before)
        self.assertEqual(self.asked_routes(), [])
        self.assertEqual(self.browser.errors, [])

    def test_download_saves_the_page_its_pdf_and_its_markdown(self) -> None:
        url = self.viewer("acme-saved-carts-plan")
        t = Tab(self.browser)
        self.open(t, url + HASH)
        self.assertTrue(self.q(t, f"w.eval({json.dumps(EXPORT_SPY)}) && w.eval({json.dumps(TEXT_SPY)})"))
        self.q(t, "(w.__printed = 0, w.print = () => { w.__printed++; }, 1)")
        key = "w.document.querySelector('.bd-bar-r .bd-docx')"
        self.assertEqual(self.q(t, f"[...{key}.querySelectorAll('[role=menuitem]')].map(b => b.dataset.format)"), ["html", "pdf", "md"])
        for fmt in ("html", "pdf", "md"):
            self.assertTrue(self.click(t, ".bd-bar-r .bd-docx .bd-expb"))
            t.wait_for(IN.format(f"!{key}.querySelector('.bd-expm').hidden"))
            self.assertTrue(self.click(t, f".bd-bar-r .bd-docx [data-format={fmt}]"))
        saved = t.wait_for(IN.format("w.__printed === 1 && w.__saved.length === 2 && w.__saved.every(s => s.name) && w.__texts.length === 2 && w.__saved"))
        self.assertEqual([(s["type"], s["name"]) for s in saved], [("text/html", "acme-saved-carts-plan.html"), ("text/markdown", "acme-saved-carts-plan.md")])
        html, md = self.q(t, "[w.__texts.find(x => x.startsWith('<!doctype html>')), w.__texts.find(x => x.startsWith('# '))]")
        self.assertEqual(data_block(html, "bp-doc"), data_block((self.site / "page.html").read_text(encoding="utf-8"), "bp-doc"))
        self.assertEqual(md.split("\n")[0], "# 📋 Acme Shop: saved carts")
        self.assertIn("## Open questions", md)
        self.assertEqual(self.asked_routes(), [])
        # the page it saved opens anywhere and draws the doc: here a file, with Download
        f = self.tmp.dir / "acme-saved-carts-plan.html"
        f.write_text(html, encoding="utf-8")
        t2 = Tab(self.browser)
        self.browser.call("Page.navigate", {"url": f.as_uri()}, t2.session)
        t2.wait_for("document.readyState === 'complete' && !!window.BP", 20)
        self.assertEqual(t2.ev("[document.title, document.querySelector('h1').textContent.includes('Acme Shop: saved carts'), document.querySelector('.bd-bar-r .bd-docx .bd-expb').textContent]"),
                         ["Acme Shop: saved carts · bluedoc", True, "Download"])
        self.assertEqual(self.browser.errors, [])

    def test_make_a_copy_and_the_bluedoc_file(self) -> None:
        """With the gist's link and files (viewer.ts hands them over), Make a copy beside Download opens its sheet: Open in
        my bluedoc links to the local import page in a new tab, then the agent's line and the command; Download's
        bluedoc file (.zip) holds the doc verbatim and its media byte for byte, and `serve.py import` takes it."""
        stem = "acme-saved-carts-plan"
        self.viewer(stem)
        link = "https://bluedoc.ai/g/shaZAB1ze-L25qJChRpj2g"
        files = {f"{stem}.bluedoc.json": (self.docs / f"{stem}.bluedoc.json").read_text(encoding="utf-8")}
        (self.site / "viewer.html").write_text(VIEWER.replace("hash: location.pathname", "link: %s, by: 'acme-dev', files: %s, hash: location.pathname")
                                               % (json.dumps(stem), json.dumps(link), json.dumps(files)), encoding="utf-8")
        t = Tab(self.browser)
        self.open(t, f"http://127.0.0.1:{self.httpd.server_address[1]}/viewer.html")
        self.assertEqual(self.q(t, "[...w.document.querySelector('.bd-bar-r').children].map(e => e.className).filter(c => /bd-mkc|bd-docx/.test(c))"),
                         ["bd-tbtn bd-mkc", "bd-exp bd-docx"], "Make a copy, then Download")
        self.assertTrue(self.click(t, ".bd-bar-r .bd-mkc"))
        sheet = t.wait_for(IN.format("(d => d && d.open && {href: d.querySelector('a.go').href, target: d.querySelector('a.go').target, "
                                     "lines: [...d.querySelectorAll('.lnk input')].map(i => i.value), text: d.innerText})(w.document.querySelector('dialog.bd-mkcs'))"))
        self.assertEqual((sheet["href"], sheet["target"]), ("http://127.0.0.1:8740/__bluedoc/import?src=shaZAB1ze-L25qJChRpj2g", "_blank"))
        self.assertEqual(sheet["lines"], [f"import this bluedoc: {link}", f"python3 <skill>/scripts/serve.py import {link}"])
        self.assertIn("acme-dev's plan", sheet["text"])
        self.assertIn("changes don't go back to acme-dev", sheet["text"])
        self.q(t, "w.document.querySelector('dialog.bd-mkcs').close()")
        self.assertTrue(self.q(t, "(w.__zip = null, (mk => { w.URL.createObjectURL = b => { w.__zip = b; return mk.call(w.URL, b); }; })(w.URL.createObjectURL), "
                                  "w.HTMLAnchorElement.prototype.click = function () { w.__zipName = this.download; }, true)"))
        self.assertTrue(self.click(t, ".bd-bar-r .bd-docx .bd-expb"))
        self.assertEqual(self.q(t, "[...w.document.querySelectorAll('.bd-docx [role=menuitem]')].map(b => b.dataset.format)"), ["html", "pdf", "md", "zip"])
        self.assertTrue(self.click(t, ".bd-bar-r .bd-docx [data-format=zip]"))
        name, data = t.wait_for(IN.format("w.__zip && new Promise(ok => { const r = new FileReader(); r.onload = () => ok([w.__zipName, r.result.split(',')[1]]); r.readAsDataURL(w.__zip); })"))
        self.assertEqual(name, f"{stem}.zip")
        zp = self.tmp.dir / name
        zp.write_bytes(base64.b64decode(data))
        with zipfile.ZipFile(zp) as z:
            self.assertIsNone(z.testzip(), "every CRC holds")
            got = {i.filename: z.read(i) for i in z.infolist()}
        media = sorted(share._media_srcs(load_json(self.docs / f"{stem}.bluedoc.json"), set()))
        self.assertEqual(sorted(got), sorted([f"{stem}.bluedoc.json", "bluedoc-share.json", *media]))
        self.assertEqual(got[f"{stem}.bluedoc.json"].decode(), files[f"{stem}.bluedoc.json"])
        for m in media:
            self.assertEqual(got[m], (self.docs / m).read_bytes(), m)
        self.assertEqual(json.loads(got["bluedoc-share.json"]), {"by": "acme-dev", "link": link})
        out = importer.write(importer.load(str(zp)), self.tmp.dir / "copy")
        self.assertEqual(load_json(out["path"])["meta"]["copiedFrom"]["by"], "acme-dev")
        self.assertEqual(self.asked_routes(), [])
        self.assertEqual(self.browser.errors, [])

    def test_a_review_is_view_only_and_its_threads_read_only(self) -> None:
        t = Tab(self.browser)
        self.open(t, self.viewer("acme-review-findings") + HASH)
        self.assert_view_only(t)
        before = self.q(t, "JSON.stringify(w.BP.replyPayload().items)")
        self.assertTrue(self.click(t, ".bp-opt:not(.on) .pk"))
        self.assertEqual(self.q(t, "[w.BP.custom('t412/tier-boundary', 'Acme'), w.BP.choose('t412/tier-boundary', 'fix')]"), [False, False])
        self.assertEqual(self.q(t, "JSON.stringify(w.BP.replyPayload().items)"), before)
        # the doc's thread on docs-stale is the Comments tab's one card; a click opens the item, its conversation shows
        # and it has no reply box
        self.assertEqual(self.q(t, "[w.BP.comments().available, [...w.document.querySelectorAll('#bd-sp-comments [data-item]')].map(e => e.dataset.item)]"),
                         [True, ["t412/docs-stale"]])
        self.q(t, "w.BP.sidebar({section: 'comments'}) && 1")
        self.assertTrue(self.click(t, "#bd-sp-comments [data-item='t412/docs-stale']"))
        t.wait_for(IN.format("(li => !!li && li.classList.contains('open') && !!li.querySelector('.bp-convo .bp-msg, .bp-convo li, .bp-convo > *'))"
                             "(w.document.getElementById('item-t412-docs-stale'))"))
        self.assertEqual(self.q(t, "w.document.getElementById('item-t412-docs-stale').querySelectorAll('textarea, .bp-note').length"), 0)
        self.assert_view_only(t)
        self.assertEqual(self.asked_routes(), [])
        self.assertEqual(self.browser.errors, [])

    def test_a_design_is_view_only(self) -> None:
        t = Tab(self.browser)
        self.open(t, self.viewer("acme-fit-design") + HASH)
        t.wait_for(IN.format("w.BP.board() && w.BP.board().artboards.some(a => a.ready)"), 20)
        self.assert_view_only(t)
        # the doc's pick shows as chosen; nothing on the board edits, and its versions take no pick
        self.assertEqual(self.q(t, "[w.BP.replyPayload().items.find(x => x.item === 'framework').choice, "
                                   "w.document.querySelector('#item-brief-framework .bp-opt.on')?.dataset.id, "
                                   "w.BP.boardEdit({}), w.BP.board().mode, w.document.querySelectorAll('.bd-var button:not(:disabled)').length]"),
                         ["horizon", "horizon", None, "view", 0])
        before = self.q(t, "JSON.stringify(w.BP.replyPayload().items)")
        # the board still pans, zooms and focuses a screen; the stored keys stay the view prefs
        first = self.q(t, "w.BP.board().artboards[0].id")
        self.assertEqual(self.q(t, f"(w.BP.board({{focus: {json.dumps(first)}}}), w.BP.board().selected)"), first)
        self.assertEqual(self.q(t, "JSON.stringify(w.BP.replyPayload().items)"), before)
        # narrow, the toolbar keeps one row the same way (test_narrow.BoardToolbar); ⋯ More has no edit keys
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 900, "deviceScaleFactor": 1, "mobile": False}, t.session)
        t.wait_for(IN.format("w.innerWidth === 390"))
        tb = "w.document.querySelector('.bd-btb')"
        t.wait_for(IN.format(f"!{tb}.querySelector('.bd-btb-more').hidden"))
        self.assertAlmostEqual(*self.q(t, f"(t => [t.getBoundingClientRect().height, t.querySelector('.bd-tbtn').getBoundingClientRect().height + 8])({tb})"), delta=0.5)
        self.q(t, f"{tb}.querySelector('.bd-btb-more > button').click()")
        rows = self.q(t, f"[...{tb}.querySelectorAll('.bd-btb-more [role^=menuitem]')].map(r => r.textContent)")
        self.assertTrue(rows)
        self.assertEqual([r for r in rows if r.startswith(("Tidy up", "Nothing to", "Undo", "Redo"))], [])
        self.assert_view_only(t)
        self.assertEqual(self.asked_routes(), [])
        self.assertEqual(self.browser.errors, [])

    def test_only_the_current_revision(self) -> None:
        url = self.viewer("acme-fit-design")
        origin = url.rsplit("/", 1)[0]
        for query in ("", "?rev=B", "?diff=B"):
            with self.subTest(query=query):
                t = Tab(self.browser)
                self.open(t, origin + CODE_PATH + query)
                t.wait_for(IN.format("w.BP.board() && w.BP.board().artboards.some(a => a.ready)"), 20)
                self.assertEqual(self.q(t, "[w.BP.compare(), w.BP.revisions().find(r => r.shown).current, w.BP.sidebar().available.includes('revisions'), "
                                           "w.document.querySelectorAll('.bd-revbar, .bd-stripe [data-f=revisions]').length]"), [None, True, False, 0])
                self.assert_view_only(t)
        self.assertEqual(self.asked_routes(), [])
        self.assertEqual(self.browser.errors, [])

    def test_the_reader_s_answers_show_read_only_as_theirs(self) -> None:
        # the reader's state.db rows as a share carries them (share.answers_slot): picks, ticks, sent comments, an image
        att = self.tmp.dir / ".bluedoc" / "attachments" / "acme"
        att.mkdir(parents=True)
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        (att / "1a2b-cart.png").write_bytes(png)
        (att / "3c4d-terms.pdf").write_bytes(b"%PDF-1.4")
        files = [{"name": "cart.png", "path": str(att / "1a2b-cart.png"), "size": len(png)}, {"name": "terms.pdf", "path": str(att / "3c4d-terms.pdf"), "size": 8}]
        at = "2026-11-18T10:00:00.000Z"
        pin = {"id": "c1", "type": "pin", "status": "open", "note": "This total looks wrong", "target": {"key": "item:decisions/prices", "label": "Open questions › Prices"},
               "rev": "1", "at": at, "sentAt": at, "thread": [{"md": "Still wrong after the fix", "rev": "1", "at": at}]}
        state = {"decisions:retention": "=d180|d90", "decisions:prices:custom": "Ask finance first", "decisions:guests:more": "1", "checks:unit": "10",
                 "decisions:retention:thread": json.dumps([{"md": "180 days matches finance", "rev": "1", "at": at, "files": files}]),
                 "__ann:c1": json.dumps(pin), "decisions:prices:note": "Not sent yet"}

        def choose_d90(doc: dict) -> None:   # the doc records its own choice: shown apart from the reader's
            next(it for b in build.all_blocks(doc) if b.get("id") == "decisions" for it in b["items"] if it["id"] == "retention")["choice"] = "d90"
        choose_d90(doc := load_json(self.docs / "acme-saved-carts-plan.bluedoc.json"))
        slot, _ = share.answers_slot(state, doc, ["picks", "ticks", "comments", "images"], "acme-dev")
        t = Tab(self.browser)
        self.open(t, self.viewer("acme-saved-carts-plan", slot, choose_d90) + HASH)
        self.assert_view_only(t)
        # the pick: beside its option, apart from the doc's choice, which stays chosen
        self.assertEqual(self.q(t, "[...w.document.querySelectorAll('#item-decisions-retention .bp-opt')].map(o => [o.dataset.id, o.classList.contains('on'), "
                                   "o.querySelector('.yp').textContent, o.querySelector('.bd-ansby')?.textContent || null])"),
                         [["d90", True, "Chosen", None], ["d180", False, "", "Aacme-dev's answer"], ["forever", False, "", None]])
        self.assertEqual(self.q(t, "w.BP.replyPayload().items.find(x => x.item === 'retention').choice"), "d90", "the doc's, not the reader's")
        # Other's words, Tell me more, the tick
        self.assertEqual(self.q(t, "(o => [o.querySelector('.ol').textContent, o.querySelector('.one').textContent, o.querySelector('.pk').disabled])"
                                   "(w.document.querySelector('#item-decisions-prices .bd-ansother'))"), ["Other", "Ask finance first", True])
        self.assertEqual(self.q(t, "w.document.querySelector('#item-decisions-guests .bd-ansmore').textContent"), "Asked for moreAacme-dev")
        self.assertEqual(self.q(t, "[w.document.querySelector('#item-checks-unit .bd-ansc').textContent, w.document.querySelector('#cb-checks-unit').checked]"),
                         ["Done · acme-dev", False], "the tick is theirs; the box stays the doc's")
        # their message in the item's conversation, as theirs, with the image and the file that wasn't shared
        convo = "w.document.querySelector('#item-decisions-retention .bp-convo')"
        self.assertEqual(self.q(t, f"[...{convo}.querySelectorAll('.bp-msg .who')].map(e => e.textContent)"), ["acme-dev"])
        self.assertEqual(self.q(t, f"[{convo}.querySelector('.bd-shimgs img').getAttribute('src').slice(0, 22), {convo}.querySelector('.bp-file.off .t').textContent, "
                                   f"{convo}.querySelector('.bd-shfn').textContent]"), ["data:image/png;base64,", "terms.pdf", "1 file not shared"])
        self.assertEqual(self.q(t, "w.document.querySelectorAll('#item-decisions-prices .bp-msg.unsent').length"), 0, "pending stays out")
        # the Comments tab: the item and the pin, read-only
        self.q(t, "w.BP.sidebar({section: 'comments'}) && 1")
        cards = self.q(t, "[...w.document.querySelectorAll('#bd-sp-comments .bd-cs-l > ol > li')].map(li => li.dataset.item || li.querySelector('.lb').textContent)")
        self.assertEqual(cards, ["decisions/retention", "Prices"])
        pin = "w.document.querySelector('#bd-sp-comments .bd-cs-ro')"
        self.assertEqual(self.q(t, f"[{pin}.querySelector('.mt').textContent.startsWith('acme-dev · Sent'), {pin}.querySelector('.nt').textContent, "
                                   f"{pin}.querySelector('.bp-msg .who').textContent, {pin}.querySelectorAll('textarea, button:not(:disabled)').length]"),
                         [True, "This total looks wrong", "acme-dev", 0])
        page = (self.site / "page.html").read_text(encoding="utf-8")
        self.assertNotIn("/.bluedoc/", json.dumps(data_block(page, "bp-answers")), "no attachment's path")
        self.assertNotIn(str(self.tmp.dir), page)
        self.assert_view_only(t)
        self.assertEqual(self.asked_routes(), [])
        self.assertEqual(self.browser.errors, [])
        # an older bundle without answers: none show
        self.open(t, self.viewer("acme-saved-carts-plan") + HASH, reload=True)
        self.assertEqual(self.q(t, "w.document.querySelectorAll('.bd-ansby, .bd-ansc, .bd-ansother, .bd-ansmore').length"), 0)
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
