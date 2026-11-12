"""The app bar's left side (rt/app-bar): the home key (a house and the wordmark) links to the home page when served and
to the page's top elsewhere, and the doc's name is the doc menu's key on a served page. The menu lists the docs of the
page's folder only (index.json?root=), newest first, archived ones left out, this doc ticked and lit; its search field
takes the focus, typing filters by title (case and accents aside), ↑ ↓ move, Enter opens the lit doc, Esc closes back to
the key and a press outside closes it. An -o file has no menu: its title is plain text. Runs with BLUEDOC_BROWSER_TESTS=1."""
from __future__ import annotations

import json
import os
import shutil
import time
import unittest
from pathlib import Path

from _support import Server, TempHome, load_json
from test_page_state import CHROME, ChromePage, Tab

import build

# the shop folder's docs, newest first (setUp dates them so); the deck goes to a folder of its own
NEWEST_FIRST = ["acme-status", "acme-saved-carts-plan", "acme-orders", "acme-review-findings", "acme-site", "acme-fit-design", "acme-fit-listing"]
ARCHIVED = "acme-orders"
MENU = "document.querySelector('.bd-dsm')"
OPTIONS = "[...document.querySelectorAll('.bd-dsm [role=option]')]"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class DocMenu(ChromePage):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples("w/acme-shop/docs")
        other = self.tmp.dir / "w" / "acme-fit"
        other.mkdir()
        for p in self.docs.glob("acme-fit-deck.*"):
            shutil.move(str(p), str(other / p.name))
        now = time.time()
        for i, stem in enumerate(NEWEST_FIRST):
            os.utime(self.doc(stem), (now - 3600 * (i + 1),) * 2)
        for folder in (self.docs, other):
            self.assertEqual(self.tmp.run("serve.py", "add", folder).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.base = f"http://{self.server.host}"
        self.browser.errors.clear()
        # an archived doc is out of the list, as on the home page
        url = self.server.url_for(self.doc(ARCHIVED))
        body = json.dumps({"path": url, "import": False, "ops": [["__archived", json.dumps({"at": "2026-11-01T10:00:00Z", "rev": str(load_json(self.doc(ARCHIVED))["meta"]["rev"])})]]})
        self.assertEqual(self.server.req("PUT", "/__bluedoc/state", body.encode(), {"Content-Type": "application/json", "X-Bluedoc": "1", "Origin": self.base})[0], 200)

    def doc(self, stem: str) -> Path:
        return self.docs / f"{stem}.bluedoc.json"

    def title(self, stem: str) -> str:
        return load_json(self.doc(stem))["title"]

    def keys(self, t: Tab, key: str, code: int) -> None:
        for kind in ("keyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": key, "windowsVirtualKeyCode": code,
                                                         **({"text": "\r"} if key == "Enter" and kind == "keyDown" else {})}, t.session)

    def open_menu(self, t: Tab) -> None:
        t.ev("document.querySelector('.bd-dsw').click()")
        t.wait_for(f"{OPTIONS}.length > 1")

    def lit(self, t: Tab) -> str:
        return t.ev("document.querySelector('.bd-dsm [aria-selected=true] .l')?.textContent")

    def test_the_menu_lists_this_folders_docs_newest_first(self) -> None:
        t = self.open(self.server.url_for(self.doc("acme-status")))
        self.assertEqual(t.ev("[document.querySelector('.bd-home').getAttribute('href'), document.querySelector('.bd-home').title]"), ["/", "All docs"])
        self.assertEqual(t.ev("document.querySelector('.bd-dsw').getAttribute('aria-expanded')"), "false")
        self.open_menu(t)
        shown = [s for s in NEWEST_FIRST if s != ARCHIVED]
        self.assertEqual(t.ev(f"{OPTIONS}.map(o => o.querySelector('.l').textContent)"), [self.title(s) for s in shown])
        # this doc: ticked, marked as the page and lit; the search field has the focus
        self.assertEqual(t.ev(f"{OPTIONS}.filter(o => o.getAttribute('aria-current') === 'page').map(o => [o.querySelector('.l').textContent, !!o.querySelector('.ck')])"),
                         [[self.title("acme-status"), True]])
        self.assertEqual(self.lit(t), self.title("acme-status"))
        self.assertEqual(t.ev("document.activeElement === document.querySelector('.bd-dsm input')"), True)
        self.assertEqual(t.ev("[document.querySelector('.bd-dsm .q .n').textContent, document.querySelector('.bd-dsm .gh').textContent, document.querySelector('.bd-dsm input').placeholder]"),
                         [f"{len(shown)} docs", "acme-shop", "Search acme-shop"])
        self.assertEqual(t.ev(f"{OPTIONS}.find(o => o.getAttribute('href').endsWith('acme-saved-carts-plan.bluedoc.json')).querySelector('small').textContent"),
                         "Plan · awaiting approval")
        self.assertEqual(t.ev("document.querySelector('.bd-dsm .ft .all').getAttribute('href')"), "/")
        # ↓ and ↑ move the light
        self.keys(t, "ArrowDown", 40)
        self.assertEqual(self.lit(t), self.title(shown[1]))
        self.keys(t, "ArrowUp", 38)
        self.keys(t, "ArrowUp", 38)
        self.assertEqual(self.lit(t), self.title(shown[-1]))
        self.assertEqual(self.browser.errors, [])

    def test_typing_filters_and_enter_opens_the_lit_doc(self) -> None:
        t = self.open(self.server.url_for(self.doc("acme-status")))
        self.open_menu(t)
        self.browser.call("Input.insertText", {"text": "SAVED cárts"}, t.session)
        self.assertEqual(t.ev(f"{OPTIONS}.map(o => o.querySelector('.l').textContent)"), [self.title("acme-saved-carts-plan")])
        self.assertEqual(t.ev("document.querySelector('.bd-dsm .q .n').textContent"), f"1 of {len(NEWEST_FIRST) - 1}")
        self.assertEqual(self.lit(t), self.title("acme-saved-carts-plan"))
        t.ev("window.__bdLeft = true")
        self.keys(t, "Enter", 13)
        t.wait_for("!window.__bdLeft && document.readyState === 'complete' && !!window.BP")
        self.assertTrue(t.ev("location.pathname").endswith("/acme-saved-carts-plan.bluedoc.json"))
        self.assertEqual(self.browser.errors, [])

    def test_esc_and_a_press_outside_close_it(self) -> None:
        t = self.open(self.server.url_for(self.doc("acme-saved-carts-plan")))
        self.open_menu(t)
        self.keys(t, "Escape", 27)
        self.assertEqual(t.ev(f"[{MENU}.hidden, document.activeElement === document.querySelector('.bd-dsw'), document.querySelector('.bd-dsw').getAttribute('aria-expanded')]"),
                         [True, True, "false"])
        self.open_menu(t)
        self.assertEqual(self.lit(t), self.title("acme-saved-carts-plan"))
        self.browser.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 1000, "y": 600, "button": "left", "clickCount": 1}, t.session)
        self.browser.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": 1000, "y": 600, "button": "left", "clickCount": 1}, t.session)
        self.assertEqual(t.ev(f"{MENU}.hidden"), True)
        self.assertEqual(self.browser.errors, [])

    def test_an_exported_page_has_no_menu(self) -> None:
        path = self.doc("acme-status")
        doc = load_json(path)
        out = self.tmp.dir / "acme-status.html"
        out.write_text(build.standalone(doc, path, build.history_now(path, doc), build.TEMPLATE.read_text(encoding="utf-8")), encoding="utf-8")
        t = Tab(self.browser)
        t.go(out.as_uri())
        self.assertEqual(t.ev("[!!document.querySelector('.bd-dsw, .bd-dsm'), document.querySelector('.bd-crumb').textContent, "
                              "document.querySelectorAll('.bd-crumb button, .bd-crumb [tabindex]').length, document.querySelector('.bd-home').getAttribute('href')]"),
                         [False, "/📄" + doc["title"], 0, "#top"])
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
