"""A shared doc as the bluedoc.ai viewer (/g/#<user>/<gist id>) draws it: the -o file's page, written into a frame of
the viewer's page on an http(s) origin with window.bluedocShare = {name, hash} set first (share/page). It is an -o file
in all but its URL: it asks no /__bluedoc/ route and has no Export key although its origin is http, keeps a pick in
localStorage over a reload, and names the doc <name>.bluedoc.json in what Request changes copies. ?diff= in the
viewer's URL compares, and Done loads the viewer's URL in the top window with the link's fragment (share/rev-links).

Here a stand-in viewer page on a local http server writes the page as the site's viewer does
(bluedoc-site/src/scripts/viewer.ts); the server records every path asked. Runs with BLUEDOC_BROWSER_TESTS=1."""
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
FRAME = "document.getElementById('doc')"
IN = "(w => {})(" + FRAME + " && " + FRAME + ".contentWindow)"
# the stand-in viewer: the page into a frame, window.bluedocShare set between open() and write(), as viewer.ts does
VIEWER = """<!doctype html><meta charset="utf-8"><body style="margin:0"><script>
fetch('page.html').then(r => r.text()).then(html => {
  const fr = document.createElement('iframe');
  fr.id = 'doc'; fr.style.cssText = 'display:block;width:100vw;height:100vh;border:0';
  document.body.append(fr);
  const d = fr.contentDocument;
  d.open(); fr.contentWindow.bluedocShare = { name: %s, hash: location.hash }; d.write(html); d.close();
});
</script>"""


class Recorder(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:
        self.server.paths.append(self.path)
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

    def test_a_plan_is_an_o_file_on_the_viewers_origin(self) -> None:
        url = self.viewer("acme-saved-carts-plan")
        t = Tab(self.browser)
        self.open(t, url + HASH)
        self.assertEqual(t.ev(IN.format("[w.document.title, !!w.document.querySelector('.bd-bar-r'), !!w.document.querySelector('.bd-docx')]")),
                         ["Acme Shop: saved carts · bluedoc", True, False])
        # a pick, kept in localStorage over a reload
        picked = IN.format("w.BP.replyPayload().items.find(x => x.checklist === 'decisions' && x.item === 'retention').choice")
        t.ev(IN.format("w.BP.choose('decisions/retention', 'd180')"))
        self.open(t, url + HASH, reload=True)
        self.assertEqual(t.ev(picked), "d180")
        # Request changes copies Markdown naming the doc by the bundle's name, not the viewer's URL
        t.ev(IN.format("w.BP.annotate({type: 'general', note: 'Acme: shorter steps.'}) && 1"))
        md = t.ev(IN.format("w.BP.changesPayload().markdown"))
        self.assertIn("acme-saved-carts-plan.bluedoc.json", md)
        self.assertNotIn("viewer", md)
        self.assertEqual(self.asked_routes(), [])
        self.assertEqual(self.browser.errors, [])

    def test_revision_links_load_the_viewer_with_the_fragment(self) -> None:
        url = self.viewer("acme-fit-design")
        t = Tab(self.browser)
        self.open(t, url + "?diff=B" + HASH)
        self.assertEqual(t.ev(IN.format("(c => c && c.from)(w.BP.compare())")), "B")
        # the revisions panel's links open in the top window and keep the fragment
        t.ev(IN.format("w.BP.revisionsRail({open: true}) && 1"))
        hrefs = t.ev(IN.format("[...w.document.querySelectorAll('a[href*=\"?\"]')].filter(a => /[?&](rev|diff)=/.test(a.getAttribute('href')))"
                               ".map(a => [a.getAttribute('href'), a.target])"))
        self.assertTrue(hrefs, "no revision links")
        for href, target in hrefs:
            self.assertEqual((href.split("?")[0], href.endswith(HASH), target), ("/viewer.html", True, "_top"), href)
        # Done leaves compare: the viewer's URL without the query, in the top window
        t.ev("window.__left = true")
        t.ev(IN.format("w.document.querySelector('.bd-key[aria-label=\"Done\"]').click()"))
        t.wait_for(f"!window.__left && document.readyState === 'complete' && !!{IN.format('w && w.BP')}", 20)
        self.assertEqual(t.ev("location.pathname + location.search + location.hash"), "/viewer.html" + HASH)
        self.assertIsNone(t.ev(IN.format("w.BP.compare()")))
        self.assertEqual(self.asked_routes(), [])
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
