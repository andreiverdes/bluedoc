"""The home page (1.0.51) in a real browser: the sidebar's projects, pinned and hidden through the ⋯ menu and kept in
settings.json (home) across a reload; the Hidden chip lists the projects home leaves out with the reason: temporary
folders (under /tmp) and registered folders that are gone, besides the ones the reader hid. A table row opens in place
under itself (an inset card) and only its title opens the doc; ?doc= opens that row on load. Statistics shows a
project and a range from its URL. Search finds a doc by its body text, which the page fetches from
/__bluedoc/search-text on the first search only.

Browser tests: BLUEDOC_BROWSER_TESTS=1 with Chrome (BLUEDOC_CHROME names it when it isn't in a usual place)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from _support import EXAMPLES, Server, TempHome
from test_home_settings import typed
from test_page_state import CHROME, ChromePage, Tab, until

PROJECTS = "[...document.querySelectorAll('.bd-side .bd-pr > .bd-ni .n')].map(n => n.textContent)"
ALL = "+document.querySelector('.bd-side .bd-ni[aria-current] .c')?.textContent"
SEARCHED = "performance.getEntriesByType('resource').filter(r => r.name.includes('/__bluedoc/search-text')).length"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class Home(ChromePage):
    def setUp(self) -> None:
        # acme-shop (two docs) and acme-fit (one), a temporary folder under /tmp and a registered folder that is gone
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.shop, self.fit = self.tmp.dir / "w" / "acme-shop", self.tmp.dir / "w" / "acme-fit"
        scratch = Path(tempfile.mkdtemp(prefix="acme-scratch-", dir="/tmp")).resolve()
        self.addCleanup(shutil.rmtree, scratch, True)
        self.scratch, self.gone = scratch / "docs", self.tmp.dir / "w" / "acme-old" / "docs"
        for folder, stems in ((self.shop, ("acme-orders", "acme-saved-carts-plan")), (self.fit, ("acme-status",)),
                              (scratch, ("acme-orders",)), (self.gone.parent, ())):
            (folder / "docs").mkdir(parents=True)
            for stem in stems:
                shutil.copy(EXAMPLES / f"{stem}.bluedoc.json", folder / "docs")
            self.assertEqual(self.tmp.run("serve.py", "add", folder / "docs").returncode, 0)
        shutil.rmtree(self.gone.parent)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.base = f"http://{self.server.host}"
        self.browser.errors.clear()

    def home(self, query: str = "", width: int = 1440) -> Tab:
        """A tab on the home page through a ?key= link, so it may save."""
        status, raw = self.server.req("POST", "/__bluedoc/unlock", b"{}", {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        t = Tab(self.browser)
        if width != 1440:
            self.browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 800, "deviceScaleFactor": 1, "mobile": width < 600}, t.session)
        self.browser.call("Page.navigate", {"url": f"{self.base}/?key={json.loads(raw)['token']}" + (f"&{query}" if query else "")}, t.session)
        t.wait_for("document.readyState === 'complete' && !!document.querySelector('.bd-fc')")
        return t

    def menu(self, t: Tab, project: str, item: str) -> None:
        """A project's ⋯ menu in the sidebar, reached as a keyboard does (its row, then ⋯) and opened with Enter, then
        one of its items (from this menu: another one may still be fading out)."""
        mk = f"document.querySelector('.bd-side .bd-mk[aria-label=\"More: {project}\"]')"
        t.ev(f"{mk}.closest('.bd-pr').querySelector('.bd-ni').focus(); {mk}.focus()")
        self.assertEqual(t.ev(f"document.activeElement === {mk}"), True, "⋯ takes the focus")
        for kind in ("rawKeyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13}, t.session)
        it = f"[...(document.querySelector(`[role=menu][aria-labelledby=\"${{{mk}.id}}\"]`)?.querySelectorAll('[role=menuitem]') || [])].find(i => i.textContent === {json.dumps(item)})"
        t.wait_for(f"!!{it}")
        t.ev(f"{it}.click()")

    def chip(self, t: Tab, label: str) -> str:
        return f"[...document.querySelectorAll('.bd-side .bd-pc')].find(c => c.firstChild.textContent === {json.dumps(label)})"

    def lists(self) -> dict:
        p = self.tmp.home / "settings.json"
        return (json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}).get("home") or {}

    def key_of(self, name: str) -> str:
        """A doc's <slug>/<path>, as ?doc= names it."""
        index = json.loads(self.server.req("GET", "/__bluedoc/index.json", headers={"X-Bluedoc": "1"})[1])
        return next(f"{r['slug']}/{d['path']}" for r in index["roots"] for d in r["docs"] if d["path"].endswith(name) and r["path"] == str(self.shop / "docs"))

    def test_pin_hide_and_show_hold_through_a_reload(self) -> None:
        t = self.home()
        self.assertEqual(sorted(t.wait_for(PROJECTS)), ["acme-fit", "acme-shop"], "the temporary and missing folders show")
        self.assertEqual(t.ev(ALL), 3)
        self.menu(t, "acme-fit", "Pin to top")
        t.wait_for(f"{PROJECTS}[0] === 'acme-fit' && !!document.querySelector('.bd-side .bd-pr .pn')")
        self.assertEqual(self.lists().get("pinned"), [str(self.fit / "docs")])
        self.menu(t, "acme-shop", "Hide from home")
        t.wait_for(f"{PROJECTS}.length === 1")
        self.assertEqual(t.wait_for("document.querySelector('.bd-toast')?.textContent"), "Hid acme-shop from homeUndo")
        self.assertEqual(self.lists().get("hidden"), [str(self.shop / "docs")])
        # a reload keeps both: acme-fit first with its pin, acme-shop out of the list and its docs out of All docs
        t = self.home()
        self.assertEqual(t.wait_for(PROJECTS), ["acme-fit"])
        self.assertEqual(t.ev(f"[{self.chip(t, 'Pinned')}.querySelector('i').textContent, {self.chip(t, 'Hidden')}.querySelector('i').textContent]"), ["1", "3"])
        self.assertEqual(t.ev(ALL), 1)
        # Show from the Hidden list brings it back, for good
        t.ev(f"{self.chip(t, 'Hidden')}.click()")
        row = "[...document.querySelectorAll('.bd-side .bd-hp')].find(r => r.querySelector('b').textContent === 'acme-shop')"
        self.assertEqual(t.wait_for(f"{row}?.querySelector('small').textContent"), "Hidden by you")
        t.ev(f"{row}.querySelector('button:last-child').click()")
        t.wait_for(f"!{row}")
        self.assertEqual(self.lists().get("hidden"), None)
        t = self.home()
        self.assertEqual(t.wait_for(PROJECTS), ["acme-fit", "acme-shop"])
        self.assertEqual(t.ev(ALL), 3)
        self.assertEqual(self.browser.errors, [])

    def test_hidden_lists_temporary_and_missing_folders_with_the_reason(self) -> None:
        t = self.home()
        self.assertEqual(t.wait_for(f"{self.chip(t, 'Hidden')}.querySelector('i').textContent"), "2")
        t.ev(f"{self.chip(t, 'Hidden')}.click()")
        t.wait_for("new URLSearchParams(location.search).get('hidden') === '1'")
        rows = "[...document.querySelectorAll('.bd-side .bd-hp')].map(r => [r.querySelector('b').textContent, r.querySelector('small').textContent, r.querySelector('button:last-child').textContent])"
        got = t.wait_for(f"(x => x.length === 2 && x)({rows})")
        self.assertEqual([(why, act) for _, why, act in got], [("Temporary folder", "Show"), ("Folder missing", "Remove")])
        self.assertTrue(got[0][0].endswith(f"{self.scratch.parent.name}/docs"), got[0][0])
        self.assertTrue(got[1][0].endswith("acme-old/docs"), got[1][0])
        # the docs table shows the hidden projects' docs: the temporary folder's one
        self.assertEqual(t.wait_for("document.querySelectorAll('.bd-tb .bd-r').length"), 1)
        self.assertEqual(t.ev("document.querySelector('.bd-nb b').textContent"), "Showing hidden projects")
        # Show puts the temporary folder on home (settings.json's shown)
        t.ev("document.querySelector('.bd-side .bd-hp button:last-child').click()")
        self.assertEqual(until(lambda: self.lists().get("shown")), [str(self.scratch)])
        t = self.home()
        self.assertEqual(len(t.wait_for(f"(x => x.length === 3 && x)({PROJECTS})")), 3)
        self.assertEqual(self.browser.errors, [])

    def test_a_row_opens_in_place_and_only_its_title_opens_the_doc(self) -> None:
        t = self.home()
        url = self.server.url_for(self.shop / "docs" / "acme-orders.bluedoc.json")
        row = f"document.querySelector('.bd-r[data-href=\"{url}\"]')"
        t.wait_for(f"!!{row}")
        self.assertEqual(t.ev(f"{row}.getAttribute('aria-expanded')"), "false")
        t.ev(f"{row}.querySelector('.c-ty').click()")
        detail = f"(r => r.nextElementSibling?.classList.contains('bd-rx') && r.nextElementSibling)({row})"
        t.wait_for(f"!!{detail}")
        self.assertEqual(t.ev(f"[{row}.getAttribute('aria-expanded'), {row}.getAttribute('aria-controls') === {detail}.id, {detail}.getAttribute('role'), location.pathname]"),
                         ["true", True, "region", "/"])
        self.assertEqual(t.ev("new URLSearchParams(location.search).get('doc')"), self.key_of("acme-orders.bluedoc.json"))
        self.assertEqual(t.ev(f"[...{detail}.querySelectorAll('.bd-acts button')].map(b => b.textContent)"), ["Open", "Open in new tab", "Archive"])
        # a second click closes it; Enter on the focused row opens it again
        t.ev(f"{row}.click()")
        t.wait_for(f"!{detail} && !new URLSearchParams(location.search).get('doc')")
        t.ev(f"{row}.focus()")
        for kind in ("rawKeyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13}, t.session)
        t.wait_for(f"!!{detail}")
        # the title is the link
        self.assertEqual(t.ev(f"{row}.querySelector('a.t').getAttribute('href')"), url)
        t.ev(f"{row}.querySelector('a.t').click()")
        self.assertEqual(t.wait_for(f"location.pathname === {json.dumps(url)} && location.pathname"), url)
        self.assertEqual(self.browser.errors, [])

    def test_doc_in_the_url_opens_its_row(self) -> None:
        key = self.key_of("acme-saved-carts-plan.bluedoc.json")
        t = self.home()
        t.ev("[...document.querySelectorAll('.bd-sec-head [role=radiogroup] button')].find(b => b.textContent === 'Cards').click()")
        t.wait_for("!!document.querySelector('.bd-grid')")
        # a ?doc= link shows Rows with that row open, even after the reader picked Cards
        t = self.home("doc=" + key)
        open_ = "document.querySelector('.bd-r.open')"
        self.assertEqual(t.wait_for(f"{open_}?.dataset.key"), key)
        self.assertEqual(t.ev(f"[{open_}.nextElementSibling.getAttribute('aria-label'), document.querySelectorAll('.bd-rx').length]"),
                         ["Acme Shop: saved carts", 1])
        self.assertEqual(t.ev("document.querySelector('.bd-rx .x-meter').textContent"), "0 of 3 decided3 open")
        self.assertEqual(self.browser.errors, [])

    def test_statistics_for_a_project_and_a_range(self) -> None:
        t = self.home()
        t.ev("[...document.querySelectorAll('.bd-side .bd-ni')].find(b => b.textContent === 'Statistics').click()")
        t.wait_for("location.pathname === '/stats' && !!document.querySelector('.bd-stats-h')")
        heads = "[...document.querySelectorAll('.bd-w-head')].map(h => [h.childNodes[1].textContent, h.querySelector('.r').textContent])"
        self.assertEqual(t.ev("document.querySelector('.bd-stats-h .sub').textContent"), "3 docs in 2 projects")
        self.assertEqual(t.wait_for(heads)[0], ["Activity", "14 days"])
        self.assertEqual(sorted(t.ev("[...document.querySelectorAll('.bd-eb .n')].map(n => n.textContent)")), ["acme-fit", "acme-shop"])
        # the range: 30 days, in the URL
        t.ev("[...document.querySelectorAll('.bd-stats-h [role=radiogroup] button')].find(b => b.textContent === '30 d').click()")
        t.wait_for("location.search === '?range=30'")
        self.assertEqual(t.ev(heads)[0], ["Activity", "30 days"])
        self.assertEqual(t.ev("document.querySelectorAll('.bd-bars i').length"), 30)
        # one project from the URL
        self.browser.call("Page.navigate", {"url": f"{self.base}/stats?p=acme-fit&range=7"}, t.session)
        t.wait_for("document.querySelector('.bd-stats-h .sub')?.textContent === '1 doc in acme-fit'")
        self.assertEqual(t.ev(heads)[0], ["Activity", "7 days"])
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-eb .n')].map(n => n.textContent)"), ["acme-fit"])
        self.assertEqual(t.ev(f"{heads}.find(h => h[0] === 'By type')[1]"), "1 doc")
        self.assertEqual(self.browser.errors, [])

    def test_search_finds_a_doc_by_its_body_text(self) -> None:
        t = self.home()
        t.wait_for("document.querySelectorAll('.bd-tb .bd-r').length === 3")
        self.assertEqual(t.ev(SEARCHED), 0, "search-text before any search")
        t.ev(typed(".bd-composer input", "cold cache"))   # only in acme-status's Incidents table
        hits = "[...document.querySelectorAll('.bd-tb .bd-r')].map(r => [r.querySelector('a.t').textContent, r.querySelector('small mark')?.textContent])"
        found = t.wait_for(f"(x => x.length === 1 && x[0][1] && x)({hits})")
        self.assertTrue(found[0][0].endswith("Acme shop status, week 41"), found)
        self.assertEqual(found[0][1].lower(), "cold")
        self.assertEqual(t.ev(SEARCHED), 1)
        # q= on load fetches it at once
        t = self.home("q=cold+cache")
        self.assertEqual(t.wait_for(f"(x => x.length === 1 && x)({hits})")[0][0].endswith("Acme shop status, week 41"), True)
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
