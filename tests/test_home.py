"""The home page in a real browser: the sidebar's projects, pinned and hidden through the ⋯ menu and kept in
settings.json (home) across a reload, the pinned ones first under a Pinned caption; a project's own name and emoji
(Edit name and icon…) kept the same way and shown in the sidebar and the docs table, Reset clearing both; the Hidden
chip lists the projects home leaves out with the reason: temporary folders (under /tmp) and registered folders that
are gone, besides the ones the reader hid. A table row opens in place under itself (an inset card) and only its title
opens the doc; ?doc= opens that row on load. Statistics shows a project and a range from its URL (/__bluedoc/stats).
Search asks the server (index.json?q=) and shows its snippet; there is no search-text request. The list comes a slice
at a time: scrolling to its end loads the next slice under the same date group, the counts are the server's full
ones, the end says so, and Back restores the slices loaded and the scroll. A new `code` in index.json reloads the home.

Browser tests: BLUEDOC_BROWSER_TESTS=1 with Chrome (BLUEDOC_CHROME names it when it isn't in a usual place)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from _support import EXAMPLES, Server, TempHome
from test_home_settings import typed
from test_page_state import CHROME, ChromePage, Tab, until

PROJECTS = "[...document.querySelectorAll('.bd-side .bd-pr > .bd-ni .n')].map(n => n.textContent)"
ALL = "+document.querySelector('.bd-side .bd-ni[aria-current] .c')?.textContent"
REQUESTS = "performance.getEntriesByType('resource').map(r => r.name).filter(n => n.includes('/__bluedoc/'))"
ROWS = "document.querySelectorAll('.bd-tb .bd-r').length"


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
        """A doc's <slug>/<path>, as ?doc= names it: its URL without the leading /."""
        return self.server.url_for(self.shop / "docs" / name).lstrip("/")

    def test_pin_hide_and_show_hold_through_a_reload(self) -> None:
        t = self.home()
        self.assertEqual(sorted(t.wait_for(PROJECTS)), ["acme-fit", "acme-shop"], "the temporary and missing folders show")
        self.assertEqual(t.ev(ALL), 3)
        self.menu(t, "acme-fit", "Pin to top")
        t.wait_for(f"{PROJECTS}[0] === 'acme-fit' && document.querySelector('.bd-side .bd-pcap')?.textContent === 'Pinned'")
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

    def test_the_pinned_caption_shows_only_with_pins(self) -> None:
        t = self.home()
        t.wait_for(f"{PROJECTS}.length === 2")
        caps = "[...document.querySelectorAll('.bd-side .bd-pcap, .bd-side .bd-psep')].map(x => x.tagName)"
        self.assertEqual(t.ev(caps), [], "no pins: no caption, no line")
        self.menu(t, "acme-shop", "Pin to top")
        t.wait_for(f"{caps}.length === 2")
        groups = "[...document.querySelectorAll('.bd-side .bd-plist ul')].map(u => [...u.querySelectorAll(':scope > .bd-pr > .bd-ni .n')].map(n => n.textContent))"
        self.assertEqual(t.ev(f"[{caps}, {groups}]"), [["DIV", "HR"], [["acme-shop"], ["acme-fit"]]])
        # the Pinned chip lists the pinned ones alone, without the caption
        t.ev(f"{self.chip(t, 'Pinned')}.click()")
        t.wait_for(f"{PROJECTS}.length === 1")
        self.assertEqual(t.ev(f"[{caps}, {PROJECTS}]"), [[], ["acme-shop"]])
        self.assertEqual(self.browser.errors, [])

    def test_a_name_and_an_emoji_hold_through_a_reload_and_reset_clears_them(self) -> None:
        t = self.home()
        self.menu(t, "acme-shop", "Edit name and icon…")
        name = ".bd-ped input[placeholder='acme-shop']"
        self.assertEqual(t.wait_for(f"document.activeElement === document.querySelector({json.dumps(name)}) && document.activeElement.value"), "acme-shop")
        t.ev(typed(name, "Acme Store"))
        t.ev("[...document.querySelectorAll('.bd-ped-tabs button')].find(b => b.textContent === 'Emoji').click()")
        t.wait_for("!!document.querySelector('.bd-ped-grid.emo')")
        t.ev("document.querySelector('.bd-ped-grid button[aria-label=\"🛒\"]').click()")
        # the pick shows at once on the row; Enter in Name saves
        row = "document.querySelector('.bd-side .bd-pr:has(.bd-ped-pop, .bd-pa)')"
        self.assertEqual(t.wait_for(f"(r => r && r.querySelector('.bd-pe')?.textContent === '🛒' && r.querySelector('.n').textContent)({row})"), "Acme Store")
        t.ev(f"document.querySelector({json.dumps(name)}).focus()")
        for kind in ("rawKeyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13}, t.session)
        t.wait_for("!document.querySelector('.bd-ped')")
        path = str(self.shop / "docs")
        h = until(lambda: self.lists().get("names") and self.lists())
        self.assertEqual((h["names"], h["icons"]), ({path: "Acme Store"}, {path: {"emoji": "🛒"}}))
        # a reload keeps both: the sidebar, the table's project column, and Find a project by either name
        t = self.home()
        side = "[...document.querySelectorAll('.bd-side .bd-pr > .bd-ni')].map(b => (b.querySelector('.bd-pe')?.textContent || '') + b.querySelector('.n').textContent)"
        self.assertEqual(sorted(t.wait_for(f"(x => x.length === 2 && x)({side})")), ["acme-fit", "🛒Acme Store"])
        cells = "[...document.querySelectorAll('.bd-tb .bd-r .c-f')].map(c => c.textContent).sort()"
        self.assertEqual(t.wait_for(f"(x => x.length === 3 && x)({cells})"), ["acme-fit", "🛒Acme Store", "🛒Acme Store"])
        for q in ("store", "shop"):
            t.ev(typed(".bd-psq input", q))
            self.assertEqual(t.wait_for(f"(x => x.length === 1 && x)({PROJECTS})"), ["Acme Store"])
        t.ev(typed(".bd-psq input", ""))
        # Reset: the folder's own name and the box again, in the file too
        self.menu(t, "Acme Store", "Edit name and icon…")
        t.wait_for("!!document.querySelector('.bd-ped')")
        t.ev("[...document.querySelectorAll('.bd-ped-ft button')].find(b => b.textContent === 'Reset').click()")
        self.assertEqual(sorted(t.wait_for(f"(x => !document.querySelector('.bd-side .bd-pe') && x)({PROJECTS})")), ["acme-fit", "acme-shop"])
        self.assertEqual(until(lambda: "names" not in self.lists() and "icons" not in self.lists()), True)
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
        self.assertEqual(t.wait_for("(s => s !== 'Loading…' && s)(document.querySelector('.bd-stats-h .sub').textContent)"), "3 docs in 2 projects")
        self.assertTrue(any("/__bluedoc/stats?" in n for n in t.ev(REQUESTS)))
        self.assertEqual(t.wait_for(heads)[0], ["Activity", "14 days"])
        self.assertEqual(sorted(t.ev("[...document.querySelectorAll('.bd-eb .n')].map(n => n.textContent)")), ["acme-fit", "acme-shop"])
        # the range: 30 days, in the URL
        t.ev("[...document.querySelectorAll('.bd-stats-h [role=radiogroup] button')].find(b => b.textContent === '30 d').click()")
        t.wait_for("location.search === '?range=30'")
        self.assertEqual(t.wait_for("document.querySelectorAll('.bd-bars i').length === 30 && document.querySelectorAll('.bd-bars i').length"), 30)
        self.assertEqual(t.ev(heads)[0], ["Activity", "30 days"])
        # one project from the URL
        self.browser.call("Page.navigate", {"url": f"{self.base}/stats?p=acme-fit&range=7"}, t.session)
        t.wait_for("document.querySelector('.bd-stats-h .sub')?.textContent === '1 doc in acme-fit'")
        self.assertEqual(t.ev(heads)[0], ["Activity", "7 days"])
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-eb .n')].map(n => n.textContent)"), ["acme-fit"])
        self.assertEqual(t.ev(f"{heads}.find(h => h[0] === 'By type')[1]"), "1 doc")
        self.assertEqual(self.browser.errors, [])

    def test_search_asks_the_server_and_shows_its_snippet(self) -> None:
        t = self.home()
        t.wait_for(f"{ROWS} === 3")
        t.ev(typed(".bd-composer input", "cold cache"))   # only in acme-status's Incidents table
        hits = "[...document.querySelectorAll('.bd-tb .bd-r')].map(r => [r.querySelector('a.t').textContent, r.querySelector('small mark')?.textContent])"
        found = t.wait_for(f"(x => x.length === 1 && x[0][1] && x)({hits})")
        self.assertTrue(found[0][0].endswith("Acme shop status, week 41"), found)
        self.assertEqual(found[0][1].lower(), "cold")
        reqs = t.ev(REQUESTS)
        self.assertFalse(any("search-text" in n for n in reqs), reqs)
        self.assertTrue(any("q=cold+cache" in n for n in reqs), reqs)
        # q= on load asks at once
        t = self.home("q=cold+cache")
        self.assertEqual(t.wait_for(f"(x => x.length === 1 && x)({hits})")[0][0].endswith("Acme shop status, week 41"), True)
        self.assertEqual(self.browser.errors, [])

    def test_a_new_code_reloads_the_home(self) -> None:
        # the page's first index.json answer says other code, as one from before an upgrade would; the next answer
        # (the 4 s poll) has the server's own, and the home reloads itself
        t = Tab(self.browser)
        self.browser.call("Page.enable", {}, t.session)
        self.browser.call("Page.addScriptToEvaluateOnNewDocument", {"source": """
          if (!sessionStorage.getItem('bd-test-old')) { sessionStorage.setItem('bd-test-old', '1'); const f = window.fetch; let n = 0;
            window.fetch = (u, o) => f(u, o).then(r => String(u).includes('/index.json') && !n++ ? r.json().then(j => new Response(JSON.stringify({ ...j, code: 'old' }), { status: 200, headers: r.headers })) : r); }
          else window.__bdReloaded = true;"""}, t.session)
        self.browser.call("Page.navigate", {"url": f"{self.base}/"}, t.session)
        t.wait_for("window.__bdReloaded === true && document.querySelectorAll('.bd-tb .bd-r').length === 3", timeout=15)
        self.assertEqual(self.browser.errors, [])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class HomeSlices(ChromePage):
    """60 docs in one project, all edited in the last hour: one date group (Today) across three slices of rows, two of cards."""
    N = 60

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.dir / "w" / "many" / "docs"
        self.docs.mkdir(parents=True)
        src = json.loads((EXAMPLES / "acme-orders.bluedoc.json").read_text(encoding="utf-8"))
        now = time.time()
        for i in range(self.N):
            p = self.docs / f"doc-{i:02}.bluedoc.json"
            p.write_text(json.dumps({**src, "id": f"doc-{i:02}", "title": f"Doc {i:02}"}), encoding="utf-8")
            os.utime(p, (now - 30 * (i + 1),) * 2)   # doc-00 newest
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.server.indexed()
        self.base = f"http://{self.server.host}"
        self.browser.errors.clear()

    def tab(self, url: str = "/") -> Tab:
        t = Tab(self.browser)
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False}, t.session)
        self.browser.call("Page.navigate", {"url": self.base + url}, t.session)
        t.wait_for("document.readyState === 'complete' && !!document.querySelector('.bd-fc')")
        return t

    def titles(self, t: Tab) -> list:
        return t.ev("[...document.querySelectorAll('.bd-tb .bd-r a.t, .bd-grid .bd-card-t')].map(a => a.textContent)")

    def test_scrolling_to_the_end_loads_the_next_slice_under_one_group(self) -> None:
        t = self.tab()
        # the first answer is one slice of 25; the next follows once the list's end is within a viewport
        self.assertGreaterEqual(t.wait_for(f"{ROWS} >= 25 && {ROWS}"), 25)
        # the group's header has the full count from the server, not the rows loaded
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-gh')].map(g => g.textContent)"), [f"Today· {self.N}"])
        self.assertEqual(t.ev("document.querySelector('.bd-sec-head .sub').textContent"), f"{self.N} docs")
        self.assertEqual(t.ev("document.querySelector('.bd-end')"), None)
        self.assertLess(t.ev(ROWS), self.N)
        for _ in range(4):
            t.ev("scrollTo(0, document.documentElement.scrollHeight)")
            if until(lambda: t.ev(ROWS) == self.N, 2):
                break
        self.assertEqual(t.ev(ROWS), self.N)
        # newest first across slices, each doc once, still one group, and the end line
        self.assertEqual(self.titles(t), [f"Doc {i:02}" for i in range(self.N)])
        self.assertEqual(t.ev("document.querySelectorAll('.bd-gh').length"), 1)
        self.assertEqual(t.wait_for("document.querySelector('.bd-end')?.textContent"), f"All {self.N} docs shown")
        slices = [n for n in t.ev(REQUESTS) if "/index.json?" in n and ("offset=25&" in n or "offset=50&" in n)]
        self.assertEqual(len(slices), 2, slices)
        self.assertEqual(self.browser.errors, [])

    def test_cards_load_48_then_the_rest(self) -> None:
        t = self.tab()
        t.ev("[...document.querySelectorAll('.bd-sec-head [role=radiogroup] button')].find(b => b.textContent === 'Cards').click()")
        cards = "document.querySelectorAll('.bd-grid .bd-card').length"
        t.wait_for(f"{cards} === 48")
        t.ev("scrollTo(0, document.documentElement.scrollHeight)")
        t.wait_for(f"{cards} === {self.N}")
        self.assertEqual(len(set(self.titles(t))), self.N)
        self.assertEqual(self.browser.errors, [])

    def test_back_restores_the_slices_and_the_scroll(self) -> None:
        t = self.tab()
        t.wait_for(f"{ROWS} >= 50")
        t.ev("document.querySelectorAll('.bd-tb .bd-r')[45].scrollIntoView({ block: 'center' })")
        time.sleep(1)   # the next slice lands; the position saves 150 ms after the scroll ends
        n, y = t.ev(ROWS), t.ev("scrollY")
        self.assertGreater(y, 1200)
        t.ev("document.querySelectorAll('.bd-tb .bd-r')[45].querySelector('a.t').click()")
        t.wait_for("location.pathname.endsWith('.bluedoc.json') && document.readyState === 'complete'")
        t.ev("history.back()")
        t.wait_for(f"location.pathname === '/' && {ROWS} >= {n}", timeout=15)
        self.assertLess(abs(t.wait_for(f"(y => Math.abs(y - {y}) < 4 && y)(scrollY)") - y), 4)
        # a reload asks for the rows loaded in one request (offset 0, as many as were loaded) and scrolls back too
        t.ev("location.reload()")
        t.wait_for(f"performance.getEntriesByType('resource').some(r => r.name.includes('offset=0&limit={n}')) && {ROWS} === {n}", timeout=15)
        self.assertLess(abs(t.wait_for(f"(y => Math.abs(y - {y}) < 4 && y)(scrollY)") - y), 4)
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
