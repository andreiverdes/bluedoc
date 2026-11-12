"""The stripes and their panes (1.0.41), in Chrome (BLUEDOC_BROWSER_TESTS=1).

A doc's left stripe holds Contents, its ring the tracker's progress; the right one Comments (its badge the pending
count), Revisions (the shown revision; an earlier one in the warning's colours) and, at its foot, the theme. A key opens
its pane and lights up; the lit key closes it; [ and ] toggle the left and the right pane, not while typing. Contents is
open by default where it docks beside a 640 px page (1440 px, not 1000 px), then as the reader leaves it, per doc. A
board's left key opens its Screens and its toolbar has no panel key. A phone (600 px and under) has no stripes: a
Contents key at the bar's left, a Comments key at its right opening the bottom sheet with its sections as tabs."""
from __future__ import annotations

import json
import time
import unittest

from test_page_state import CHROME, ChromePage, Tab

STATUS, FIT = "acme-status.bluedoc.json", "acme-fit-design.bluedoc.json"
KEYS = "[...document.querySelectorAll('.bd-stripe .bd-sk')].filter(k => !k.hidden).map(k => [k.getAttribute('aria-label'), k.getAttribute('aria-pressed')])"
LKEY, RKEY = "document.querySelector('.bd-stripe.l .bd-sk')", "(f => document.querySelector(`.bd-stripe.r .bd-sk[data-f=${f}]`))"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class Stripes(ChromePage):
    def page(self, doc: str, width: int = 1440, query: str = "") -> Tab:
        t = Tab(self.browser)
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width <= 600}, t.session)
        status, raw = self.server.req("POST", "/__bluedoc/unlock", b"{}", {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        t.go(f"{self.base}{self.server.url_for(self.docs / doc)}?key={json.loads(raw)['token']}{query}")
        t.wait_for("!!document.querySelector('.bd-anntb') || !!document.querySelector('.bd-revbar')", 20)
        return t

    def key(self, t: Tab, k: str, code: str, vk: int) -> None:
        for kind in ("rawKeyDown", "char", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": k, "code": code, "windowsVirtualKeyCode": vk, **({"text": k} if kind == "char" else {})}, t.session)

    def test_keys_open_their_panes_and_light_up(self) -> None:
        t = self.page(STATUS)
        # 1440 px: Contents and Comments open, both docked beside the page
        t.wait_for("BP.contents().as === 'dock' && BP.sidebar().as === 'dock'")
        self.assertEqual(t.ev(KEYS), [["Contents", "true"], ["Comments", "true"], ["Revisions (Rev 2 of 2)", "false"], ["Switch light or dark theme", None]])
        # the Revisions key opens its section in place of Comments, and lights up instead
        t.ev(f"{RKEY}('revisions').click()")
        t.wait_for("BP.sidebar().section === 'revisions' && BP.sidebar().open")
        self.assertEqual([k[1] for k in t.ev(KEYS)], ["true", "false", "true", None])
        self.assertEqual(t.ev("document.querySelector('.bd-sp-h h2').textContent"), "Revisions")
        # the lit key closes it, as does the pane's –
        t.ev(f"{RKEY}('revisions').click()")
        t.wait_for("!BP.sidebar().open")
        t.ev(f"{LKEY}.click()")
        t.wait_for("!BP.contents().open")
        t.ev(f"{LKEY}.click()")
        t.wait_for("BP.contents().open")
        t.ev("document.querySelector('.bp-side .bd-pane-x').click()")
        t.wait_for("!BP.contents().open && " + LKEY + ".getAttribute('aria-pressed') === 'false'")
        # [ and ] toggle the left pane and the right panel's last section
        self.key(t, "[", "BracketLeft", 219)
        t.wait_for("BP.contents().open")
        self.key(t, "]", "BracketRight", 221)
        t.wait_for("BP.sidebar().open && BP.sidebar().section === 'revisions'")
        self.key(t, "]", "BracketRight", 221)
        t.wait_for("!BP.sidebar().open")
        # not while typing
        t.ev("document.querySelector('.bd-gc textarea, .bd-anntb ~ * textarea, textarea').focus()")
        self.key(t, "[", "BracketLeft", 219)
        time.sleep(0.3)
        self.assertTrue(t.ev("BP.contents().open"))
        self.assertEqual(self.browser.errors, [])

    def test_contents_opens_where_it_docks_and_is_remembered(self) -> None:
        t = self.page(STATUS, 1000)
        t.wait_for("!!window.BP")
        self.assertEqual(t.ev("BP.contents()"), {"open": False, "as": None}, "1000 px: it wouldn't dock")
        t.ev(f"{LKEY}.click()")
        t.wait_for("BP.contents().as === 'drawer'")
        # a reload keeps it open (over the page)
        t.go(t.ev("location.href"))
        t.wait_for("BP.contents().open")
        t.ev(f"{LKEY}.click()")
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False}, t.session)
        t.go(t.ev("location.href"))
        self.assertFalse(t.ev("BP.contents().open"), "closed by the reader: closed at 1440 px too")
        self.assertEqual(self.browser.errors, [])

    def test_key_states_follow_the_page(self) -> None:
        t = self.page(STATUS)
        ring = "document.querySelector('.bd-stripe.l .bd-skr .fg').getAttribute('stroke-dasharray')"
        before = t.ev(ring)
        self.assertIn("Week 42 1/2", t.ev(f"{LKEY}._tip"))
        t.ev("[...document.querySelectorAll('.bp-cl input[type=checkbox]')].find(c => !c.checked && !c.disabled && c.offsetParent).click()")
        t.wait_for(f"{ring} !== {before!r}")
        # a new pending comment counts on the Comments key
        self.assertTrue(t.ev(f"{RKEY}('comments').querySelector('.n').hidden"))
        t.ev("BP.annotate({type: 'pin', key: 'tldr', note: 'Shorter'})")
        t.wait_for(f"{RKEY}('comments').querySelector('.n').textContent === '1' && !{RKEY}('comments').querySelector('.n').hidden")
        # the theme key switches the theme
        theme = t.ev("document.documentElement.dataset.theme || ''")
        t.ev("document.querySelector('.bd-stripe.r .bd-sk:last-of-type').click()")
        t.wait_for(f"(document.documentElement.dataset.theme || '') !== {theme!r}")
        # the Revisions key shows the revision; an earlier one in the warning's colours
        self.assertEqual(t.ev(f"[{RKEY}('revisions').querySelector('.n').textContent, {RKEY}('revisions').classList.contains('old')]"), ["2", False])
        old = self.page(STATUS, query="&rev=1")
        old.wait_for(f"!!{RKEY}('revisions')")
        self.assertEqual(old.ev(f"[{RKEY}('revisions').querySelector('.n').textContent, {RKEY}('revisions').classList.contains('old')]"), ["1", True])
        self.assertEqual(old.ev("BP.sidebar().section"), "revisions")
        self.assertEqual(self.browser.errors, [])

    def test_a_board_opens_its_screens_from_the_left_stripe(self) -> None:
        t = self.page(FIT)
        t.wait_for("!!BP.board()", 20)
        self.assertEqual(t.ev(f"{LKEY}.getAttribute('aria-label')"), "Screens")
        self.assertEqual(t.ev("document.querySelectorAll('.bd-btb [aria-label^=Screens], .bd-btb [aria-label^=Pages], .bd-btb [aria-label^=Slides]').length"), 0)
        t.ev("BP.board().panel && " + LKEY + ".click()")
        t.wait_for("!BP.board().panel")
        t.ev(f"{LKEY}.click()")
        t.wait_for(f"BP.board().panel && {LKEY}.getAttribute('aria-pressed') === 'true' && !document.querySelector('.bd-lp').inert")
        self.assertEqual([k[0] for k in t.ev(KEYS)][1:3], ["Brief", "Comments"])
        self.assertEqual(self.browser.errors, [])

    def test_a_phone_has_bar_keys_and_a_sheet(self) -> None:
        t = self.page(STATUS, 390)
        t.wait_for("!!window.BP")
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-stripe')].map(s => getComputedStyle(s).display)"), ["none", "none"])
        self.assertFalse(t.ev("BP.contents().open") or t.ev("BP.sidebar().open"))
        t.ev("document.querySelector('.bd-bar .bd-bk.r').click()")
        t.wait_for("BP.sidebar().as === 'sheet' && BP.sidebar().section === 'comments'")
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-sp-tabs [role=tab]')].filter(b => b.checkVisibility()).map(b => b.textContent)"), ["Comments", "Revisions"])
        t.ev("document.querySelector('.bd-bar .bd-bk.l').click()")
        t.wait_for("BP.contents().as === 'drawer' && !BP.sidebar().open", 5)
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
