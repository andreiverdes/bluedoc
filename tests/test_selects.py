"""No native select anywhere bluedoc draws (1.0.4): every pick is selectMenu's key over its listbox on a doc page, and
its match in listing.html. A rendered page has no <select> in its DOM: each example, a compare view (?diff=), an
earlier revision (?rev=), a code review at 390 px, a design board's new-screen dialog (Frame) and an arrow's editor,
the home page and the listing file. The menus in the Revisions tab, a code review, the dialog and the arrow's editor
float: open, each sits inside the window and on top (no clipping box, no dialog over it), above its key when there is
no room under it; a pick by mouse or keyboard does what the select did.

Browser tests: BLUEDOC_BROWSER_TESTS=1 with Chrome (BLUEDOC_CHROME names it when it isn't in a usual place)."""
from __future__ import annotations

import json
import time
import unittest
from urllib.parse import quote

from _support import load_json
from test_page_state import CHROME, ChromePage, Tab, until

FIT = "acme-fit-design.bluedoc.json"
REVIEW = "acme-review-findings.bluedoc.json"
LISTING = "acme-fit-listing.bluedoc.json"
NO_SELECT = "document.querySelectorAll('select').length"
KEYS = {"Enter": ("Enter", 13, "\r"), "Escape": ("Escape", 27, None), "ArrowDown": ("ArrowDown", 40, None), "ArrowUp": ("ArrowUp", 38, None),
        "Home": ("Home", 36, None), "End": ("End", 35, None), "e": ("KeyE", 69, "e")}
# a menu (the expression's element) open, inside the window, and on top: each option it shows is what the window
# hits at that option's centre
ON_TOP = """(m => { const r = m.getBoundingClientRect(), seen = [...m.querySelectorAll('[role=option]')].filter(o => {
  const b = o.getBoundingClientRect(); return b.top >= r.top - 1 && b.bottom <= r.bottom + 1; });
  return !m.hidden && r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight && seen.length > 0
    && seen.every(o => { const b = o.getBoundingClientRect(); return o.contains(document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2)); }); })"""
# a menu above its key: its bottom over the key's top
ABOVE = "((w => w.querySelector('[role=listbox]').getBoundingClientRect().bottom <= w.querySelector('.bd-selb').getBoundingClientRect().top))"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class NoNativeSelect(ChromePage):
    def press(self, t: Tab, key: str) -> None:
        code, vk, text = KEYS[key]
        for typ in ("keyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": typ, "key": key, "code": code, "windowsVirtualKeyCode": vk,
                                                         **({"text": text} if typ == "keyDown" and text else {})}, t.session)

    def mouse(self, t: Tab, x: float, y: float) -> None:
        for kind, buttons in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
            self.browser.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "buttons": buttons, "clickCount": 1}, t.session)

    def width(self, t: Tab, w: int) -> None:
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, t.session)
        t.wait_for(f"innerWidth === {w}")

    def page(self, doc: str, w: int = 1440) -> Tab:
        t = self.open(self.server.url_for(self.docs / doc))
        self.browser.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, t.session)
        if w != 1440:
            self.width(t, w)
        return t

    def settled(self, t: Tab, el: str) -> None:
        """Wait until el (an expression) stops moving: a panel sliding in, a sheet rising."""
        at = f"JSON.stringify({el}.getBoundingClientRect())"
        def still() -> bool:
            p = t.ev(at)
            time.sleep(0.25)
            return t.ev(at) == p
        self.assertTrue(until(still), f"{el} kept moving")

    def rev2(self) -> str:
        """The plan at rev 2 (a step done), so it has a Compare picker; its URL."""
        r = self.tmp.run("build.py", "patch", self.plan, "step:steps/0/table", "--set", "status=done", "--change", "Acme: the table is in.")
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.server.url_for(self.plan)

    def test_no_page_has_a_native_select(self) -> None:
        t: Tab | None = None
        for doc in sorted(p.name for p in self.docs.glob("*.bluedoc.json")):
            with self.subTest(doc=doc):
                url = self.server.url_for(self.docs / doc)
                if t is None:
                    t = self.open(url)
                else:
                    t.go(self.base + url)
                self.assertEqual(t.ev(NO_SELECT), 0)
                if t.ev("BP.revisionsRail({open: true}).open"):
                    self.assertEqual(t.ev(NO_SELECT), 0, "the Revisions tab")
        # an earlier revision and a compare view, of a plan and of a design board
        first = load_json(self.docs / FIT.replace(".json", ".history.json"))["revs"][0]["rev"]
        for url, query in ((self.rev2(), "rev=1"), (self.server.url_for(self.plan), "diff=1"), (self.server.url_for(self.docs / FIT), f"rev={first}"),
                           (self.server.url_for(self.docs / FIT), f"diff={first}")):
            with self.subTest(url=url, query=query):
                t.go(f"{self.base}{url}?{query}")
                t.ev("BP.revisionsRail({open: true})")
                self.assertEqual(t.ev("document.querySelectorAll('.bd-rvr .rv-sel > .bd-selb[aria-haspopup=listbox]').length"), 2, "the Compare pickers")
                self.assertEqual(t.ev(NO_SELECT), 0)
        # a code review at 390 px, with its File menu in place of the file list
        self.width(t, 390)
        t.go(self.base + self.server.url_for(self.docs / REVIEW))
        t.ev("document.querySelector('#pr-412 .bd-fvbar [data-v=diff]').click()")
        self.assertTrue(t.wait_for("document.querySelector('#diff-diff-412 .bd-fsel .bd-selb').checkVisibility()"))
        self.assertEqual(t.ev(NO_SELECT), 0)
        self.width(t, 1440)
        # a design board's new-screen dialog and an arrow's editor
        t.go(self.base + self.server.url_for(self.docs / FIT))
        self.frame_dialog(t)
        self.assertEqual(t.ev(NO_SELECT), 0, "the new-screen dialog")
        t.ev("BP.setMode('view')")
        self.link_editor(t)
        self.assertEqual(t.ev(NO_SELECT), 0, "the arrow's editor")
        # the home page and the listing file
        self.browser.call("Page.navigate", {"url": f"{self.base}/"}, t.session)
        t.wait_for("document.readyState === 'complete' && !!document.querySelector('.bd-fc')")
        self.assertEqual(t.ev(NO_SELECT), 0, "the home page")
        self.listing(t)
        self.assertEqual(t.ev(NO_SELECT), 0, "listing.html")
        self.assertEqual(self.browser.errors, [])

    def frame_dialog(self, t: Tab) -> str:
        """Frame mode, a click on the empty board low in the window: the new-screen dialog; its Device menu."""
        t.wait_for("!!BP.boardEdit()", 20)
        t.ev("BP.setMode('frame')")
        at = t.ev("""(() => { const s = document.querySelector('.bd-board'), r = s.getBoundingClientRect();
          for (let y = r.bottom - 40; y > r.top + 80; y -= 23) for (let x = r.left + 40; x < r.right - 40; x += 29) if (document.elementFromPoint(x, y) === s) return [x, y];
          return null; })()""")
        self.assertTrue(at, "no empty spot on the board")
        self.mouse(t, *at)
        t.wait_for("!!document.querySelector('.bd-rqe .bd-selw')")
        return "document.querySelector('.bd-rqe .bd-selw')"

    def link_editor(self, t: Tab, key: str | None = None) -> tuple[str, str]:
        """A press on a push arrow (or key's), low and right in the window: its editor with the Kind menu; (Kind, the
        link's key)."""
        key = key or t.wait_for("BP.board().links.find(l => l.kind === 'push' && !l.del && l.to)?.key", 20)
        t.ev(f"document.querySelector('.bd-lnk[data-link={json.dumps(key)}] .hit').dispatchEvent(new PointerEvent('pointerdown', "
             "{bubbles: true, clientX: innerWidth - 40, clientY: innerHeight - 30, pointerType: 'mouse', button: 0}))")
        t.wait_for("!!document.querySelector('.bd-lpop:not([hidden]) .bd-selw')")
        return "document.querySelector('.bd-lpop .bd-selw')", key

    def listing(self, t: Tab) -> None:
        url = self.server.url_for(self.docs / LISTING)
        self.browser.call("Page.navigate", {"url": f"{self.base}/__bluedoc/listing?path={quote(url)}&format=print"}, t.session)
        t.wait_for("document.readyState === 'complete' && document.querySelector('#loc .v')?.textContent === 'en-US'", 20)

    def test_the_compare_pickers_pick_by_mouse_and_keyboard_and_compare(self) -> None:
        self.rev2()
        for w in (1440, 390):
            with self.subTest(width=w):
                t = self.page("acme-saved-carts-plan.bluedoc.json", w)
                t.ev("BP.revisionsRail({open: true})")
                pick = "[...document.querySelectorAll('.bd-rvr .rv-sel')]"
                self.assertEqual(t.ev(f"{pick}.map(s => [s.btn.getAttribute('aria-label'), s.value])"), [["Compare from", "1"], ["Compare with", "2"]])
                self.assertRegex(t.ev(f"{pick}[0].btn.textContent"), r"^Rev 1 · \d\d-\d\d$")
                # each option names its revision with month and day, its title the full date
                self.assertTrue(t.ev(f"[...{pick}[0].querySelectorAll('[role=option]')].every(o => /^\\d{{4}}-\\d\\d-\\d\\d$/.test(o.title) && o.textContent.endsWith(o.title.slice(5)))"))
                to = f"{pick}[1]"
                self.settled(t, f"{to}.btn")   # the panel (a sheet at 390 px) slides in
                # a click opens it on the current revision, over the panel and inside the window; a click picks
                t.ev(f"{to}.btn.click()")
                self.assertTrue(t.ev(f"{ON_TOP}({to}.querySelector('[role=listbox]'))"))
                self.assertEqual(t.ev("document.activeElement.dataset.v"), "2")
                t.ev(f"{to}.querySelector('[data-v=\"1\"]').click()")
                self.assertEqual(t.ev(f"[{to}.value, {to}.querySelector('[role=listbox]').hidden, document.activeElement === {to}.btn]"), ["1", True, True])
                t.ev("document.querySelector('.bd-rv-ft .bp-btn.primary').click()")
                self.toast(t, "pick two different revisions")
                # ↓ opens it on rev 1, ↓ moves to rev 2, Enter picks it; Compare goes to ?diff=1
                self.press(t, "ArrowDown")
                self.assertEqual(t.ev("document.activeElement.dataset.v"), "1")
                self.press(t, "ArrowDown")
                self.press(t, "Enter")
                self.assertEqual(t.ev(f"{to}.value"), "2")
                t.ev("window.__bdLeft = true; document.querySelector('.bd-rv-ft .bp-btn.primary').click()")
                t.wait_for("!window.__bdLeft && location.search === '?diff=1' && !!window.BP")
                self.assertEqual(self.browser.errors, [])

    def test_the_code_review_file_menu_switches_the_file_at_390(self) -> None:
        t = self.page(REVIEW, 390)
        t.ev("document.querySelector('#pr-412 .bd-fvbar [data-v=diff]').click()")
        fsel = "document.querySelector('#diff-diff-412 .bd-fsel')"
        shown = "[...document.querySelectorAll('#diff-diff-412 .bd-file')].find(b => b.getAttribute('aria-current') === 'true')?.dataset.key"
        t.wait_for(f"{fsel}.btn.checkVisibility()")
        first = t.ev(shown)
        self.assertEqual(t.ev(f"[{fsel}.value, {fsel}.btn.getAttribute('aria-label')]"), [first, "File"])
        keys = t.ev(f"[...{fsel}.querySelectorAll('[role=option]')].map(o => o.dataset.v)")
        other = next(k for k in keys if k != first)
        self.assertGreater(len(keys), 2)
        t.ev(f"{fsel}.scrollIntoView({{block: 'center', behavior: 'instant'}})")
        t.ev(f"{fsel}.btn.click()")
        self.assertTrue(t.ev(f"{ON_TOP}({fsel}.querySelector('[role=listbox]'))"))
        t.ev(f"[...{fsel}.querySelectorAll('[role=option]')].find(o => o.dataset.v === {json.dumps(other)}).click()")
        self.assertEqual(t.wait_for(f"(k => k === {json.dumps(other)} && k)({shown})"), other)
        self.assertEqual(t.ev(f"[{fsel}.value, {fsel}.btn.textContent === {fsel}.querySelector('[aria-selected=true] .l').textContent]"), [other, True])
        # ↓ opens it on the file shown, End goes to the last, Enter shows it
        self.press(t, "ArrowDown")
        self.assertEqual(t.ev("document.activeElement.dataset.v"), other)
        self.press(t, "End")
        self.press(t, "Enter")
        self.assertEqual(t.wait_for(f"(k => k === {json.dumps(keys[-1])} && k)({shown})"), keys[-1])
        self.assertEqual(self.browser.errors, [])

    def test_the_new_screen_dialog_device_menu_changes_the_request(self) -> None:
        t = self.page(FIT)
        dev = self.frame_dialog(t)
        title = "document.querySelector('.bd-rq.draft .bd-rq-t').textContent"
        self.assertEqual((t.ev(f"[{dev}.value, {dev}.btn.getAttribute('aria-label')]"), t.ev(title)), (["phone", "Device"], "Requested · Phone"))
        # low in the window it opens above its key, over the dialog
        t.ev(f"{dev}.btn.click()")
        self.assertTrue(t.ev(f"{ON_TOP}({dev}.querySelector('[role=listbox]'))"))
        self.assertTrue(t.ev(f"{ABOVE}({dev})"), "no room under the key: the menu opens above it")
        t.ev(f"{dev}.querySelector('[data-v=tablet]').click()")
        self.assertEqual((t.ev(title), t.ev("document.querySelector('.bd-rq.draft').style.width")), ("Requested · Tablet", "820px"))
        # ↓ opens it on Tablet, Home goes to the first device, Enter picks it
        self.press(t, "ArrowDown")
        self.assertEqual(t.ev("document.activeElement.dataset.v"), "tablet")
        self.press(t, "Home")
        self.press(t, "Enter")
        self.assertEqual(t.ev(title), "Requested · Round watch")
        # Esc in the open menu closes the menu, not the dialog
        self.press(t, "ArrowDown")
        self.press(t, "Escape")
        self.assertEqual(t.ev(f"[{dev}.querySelector('[role=listbox]').hidden, !!document.querySelector('.bd-rqe')]"), [True, True])
        self.assertEqual(self.browser.errors, [])

    def test_an_arrows_kind_menu_changes_the_link(self) -> None:
        t = self.page(FIT)
        kind, key = self.link_editor(t)
        link = f"BP.board().links.find(l => l.key === {json.dumps(key)})"
        self.assertEqual(t.ev(f"[{kind}.value, {kind}.btn.getAttribute('aria-label')]"), ["push", "Kind"])
        t.ev(f"{kind}.btn.click()")
        self.assertTrue(t.ev(f"{ON_TOP}({kind}.querySelector('[role=listbox]'))"))
        self.assertTrue(t.ev(f"{ABOVE}({kind})"), "no room under the key: the menu opens above it")
        t.ev(f"{kind}.querySelector('[data-v=modal]').click()")
        self.assertEqual(t.wait_for(f"{link}.kind === 'modal' && {link}.kind"), "modal")
        self.assertTrue(t.ev("document.querySelector('.bd-lpop').hidden"), "a pick closes the editor")
        # again, by keyboard (a press after the double-click time): ↓ opens it on modal, ↓ moves to tab, Enter picks it
        time.sleep(0.4)
        kind, _ = self.link_editor(t, key)
        t.ev(f"{kind}.btn.focus()")
        self.press(t, "ArrowDown")
        self.assertEqual(t.ev("document.activeElement.dataset.v"), "modal")
        self.press(t, "ArrowDown")
        self.press(t, "Enter")
        self.assertEqual(t.wait_for(f"{link}.kind === 'tab' && {link}.kind"), "tab")
        self.assertEqual(self.browser.errors, [])

    def test_the_listing_files_locale_menu_repaints(self) -> None:
        t = Tab(self.browser)
        self.browser.call("Emulation.setFocusEmulationEnabled", {"enabled": True}, t.session)
        self.listing(t)
        btn, menu = "document.querySelector('#loc button')", "document.querySelector('#loc [role=listbox]')"
        head = "document.querySelector('#text h3').textContent"
        self.assertEqual(t.ev(f"[{btn}.getAttribute('aria-haspopup'), {btn}.getAttribute('aria-label'), [...{menu}.children].map(o => [o.dataset.v, o.getAttribute('aria-selected')])]"),
                         ["listbox", "Locale", [["en-US", "true"], ["es-ES", "false"]]])
        self.assertTrue(t.ev(head).endswith("· en-US"))
        # a click opens it on en-US; a click on es-ES repaints the page in it
        t.ev(f"{btn}.click()")
        self.assertEqual(t.ev(f"[{btn}.getAttribute('aria-expanded'), document.activeElement.dataset.v]"), ["true", "en-US"])
        self.assertTrue(t.ev(f"{ON_TOP}({menu})"))
        t.ev(f"{menu}.querySelector('[data-v=es-ES]').click()")
        self.assertTrue(t.ev(head).endswith("· es-ES"))
        self.assertEqual(t.ev(f"[{btn}.textContent, {btn}.getAttribute('aria-expanded'), document.activeElement === {btn}]"), ["es-ES", "false", True])
        # ↓ opens it on es-ES, a typed e goes to en-US, Enter picks it; Esc closes it back to its key
        self.press(t, "ArrowDown")
        self.assertEqual(t.ev("document.activeElement.dataset.v"), "es-ES")
        self.press(t, "e")
        self.assertEqual(t.ev("document.activeElement.dataset.v"), "en-US")
        self.press(t, "Enter")
        self.assertTrue(t.ev(head).endswith("· en-US"))
        self.press(t, "ArrowUp")
        self.press(t, "Escape")
        self.assertEqual(t.ev(f"[{menu}.hidden, document.activeElement === {btn}]"), [True, True])
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
