"""A shared doc as the bluedoc.ai viewer (/g/<code>, or the first links' /g/#<user>/<gist id>) draws it: the -o file's
page, written into a frame of the viewer's page on an http(s) origin with window.bluedocShare = {name, hash} set first
(share/page). It asks no /__bluedoc/ route and has no Export key although its origin is http, and it is view-only
(share/view-only): no dock, tray or bottom bar, no enabled field in the doc, no comment composer, a click on an option,
a tick or a board's controls changes nothing and stores no key but the view prefs, and the app bar says "Shared · view
only". The doc's own `choice` shows as chosen, and its threads (an item's `replies`) are the Comments tab, read-only.
?diff= in the viewer's URL compares; the revision links and Done load the viewer's path in the top window, /g/<code> as
it is and an old link with its fragment (share/rev-links); an earlier revision's keys sit in its strip, not a tray.

Here a stand-in viewer page on a local http server writes the page as the site's viewer does
(bluedoc-site/src/scripts/viewer.ts), and answers every /g/<code> as GitHub Pages does with its 404.html; the server
records every path asked. Runs with BLUEDOC_BROWSER_TESTS=1."""
from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from _support import TempHome, load_json
from test_page_state import CHROME, Browser, Tab

import build

HASH = "#acme-dev/0123456789abcdef0123"
CODE_PATH = "/g/shaZAB1ze-L25qJChRpj2g"   # the gist b21699001d737be2f6e6a242851a63da
FRAME = "document.getElementById('doc')"
IN = "(w => {})(" + FRAME + " && " + FRAME + ".contentWindow)"
# what a shared page may store: the view prefs (the template's VIEW_PREFS), never reader state
VIEW_PREFS = {"bluedoc:theme", "bluedoc:width", "bluedoc:design-left-w", "bluedoc:design-right-w", "bluedoc:comments", "bluedoc:sp-tab",
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

    def viewer(self, stem: str) -> str:
        """The stand-in viewer for the doc's -o page; its URL without the fragment."""
        doc_path = self.docs / f"{stem}.bluedoc.json"
        doc = load_json(doc_path)
        page = build.standalone(doc, doc_path, build.history_now(doc_path, doc), build.TEMPLATE.read_text(encoding="utf-8"))
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
        self.assertEqual(self.q(t, "[w.document.title, !!w.document.querySelector('.bd-bar-r'), !!w.document.querySelector('.bd-docx')]"),
                         ["Acme Shop: saved carts · bluedoc", True, False])
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
        # no Need more details, Custom, Accept recommended, Reset or Copy progress; no Comments tab: the doc has no threads
        self.assertEqual(self.q(t, "[w.document.querySelectorAll('.bp-opt.more, .bp-opt.cust, .bp-side-tools').length, "
                                   "[...w.document.querySelectorAll('button')].filter(b => /^(Reset|Accept recommended)/.test(b.textContent.trim())).length, "
                                   "w.BP.sidebar().available.includes('comments')]"), [0, 0, False])
        self.assert_view_only(t)
        # a reload shows the doc as it is: the clicks above left nothing behind
        self.open(t, url + HASH, reload=True)
        self.assertEqual(self.q(t, "JSON.stringify(w.BP.replyPayload().items)"), before)
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
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": 600, "height": 900, "deviceScaleFactor": 1, "mobile": False}, t.session)
        t.wait_for(IN.format("w.innerWidth === 600"))
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

    def test_revision_links_load_the_viewer_at_its_path(self) -> None:
        url = self.viewer("acme-fit-design")
        origin = url.rsplit("/", 1)[0]
        for path, frag in ((CODE_PATH, ""), ("/viewer.html", HASH)):
            with self.subTest(link=path + frag):
                t = Tab(self.browser)
                self.open(t, origin + path + "?diff=B" + frag)
                self.assertEqual(t.ev(IN.format("(c => c && c.from)(w.BP.compare())")), "B")
                # the revisions panel's links open in the top window, at the viewer's path, an old link's fragment kept
                t.ev(IN.format("w.BP.revisionsRail({open: true}) && 1"))
                hrefs = t.ev(IN.format("[...w.document.querySelectorAll('a[href*=\"?\"]')].filter(a => /[?&](rev|diff)=/.test(a.getAttribute('href')))"
                                       ".map(a => [a.getAttribute('href'), a.target])"))
                self.assertTrue(hrefs, "no revision links")
                for href, target in hrefs:
                    self.assertEqual((href.split("?")[0], "#" in href, href.endswith(frag), target), (path, bool(frag), True, "_top"), href)
                # Done leaves compare: the viewer's path without the query, in the top window
                t.ev("window.__left = true")
                t.ev(IN.format("w.document.querySelector('.bd-key[aria-label=\"Done\"]').click()"))
                t.wait_for(f"!window.__left && document.readyState === 'complete' && !!{IN.format('w && w.BP')}", 20)
                self.assertEqual(t.ev("location.pathname + location.search + location.hash"), path + frag)
                self.assertIsNone(t.ev(IN.format("w.BP.compare()")))
        # an earlier revision: no tray; Go to current sits in its strip and loads /g/<code> in the top window
        t = Tab(self.browser)
        self.open(t, origin + CODE_PATH + "?rev=B")
        self.assertEqual(self.q(t, "[!!w.document.querySelector('.bd-anntb'), w.document.querySelectorAll('.bd-revbar.old .bd-key').length]"), [False, 2])
        self.assert_view_only(t)
        t.ev("window.__left = true")
        self.q(t, "w.document.querySelector('.bd-revbar.old .bd-key[aria-label=\"Go to current\"]').click()")
        t.wait_for(f"!window.__left && document.readyState === 'complete' && !!{IN.format('w && w.BP')}", 20)
        self.assertEqual(t.ev("location.pathname + location.search"), CODE_PATH)
        self.assertEqual(self.asked_routes(), [])
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
