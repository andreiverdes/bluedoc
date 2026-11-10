"""The dock with the comment tools in it, text edits at all times and Interact in the board's toolbar (1.0.25), in Chrome
(BLUEDOC_BROWSER_TESTS=1).

Every page's dock is View · Element · Region · Text · Pen, on a board then │ Link · Frame, then │ the eye │ Request
changes and the page's last key; at 390 px the four tools fold into one key between View and Link. On the Acme Fit
board a double-click on a screen's text in View edits it (a draft: the toolbar's count rises), a double-click where
there is no text focuses the screen, and Interact (after Present, or I) gives the screens their clicks, so a tap follows
its link and makes no comment, while the dock's tools pause until Esc ends it."""
from __future__ import annotations

import json
import time
import unittest

from test_inline_edit import EditOnBoard, frame_eval, mouse
from test_page_state import CHROME, ChromePage, Tab

FIT = "acme-fit-design.bluedoc.json"
# the dock's shown children, each as its key's label or the kind of what it is
DOCK = """[...document.querySelector('.bd-anntb').children].filter(e => e.getClientRects().length)
  .map(e => e.classList.contains('bd-groove') ? '|' : e.getAttribute('aria-label') || e.className)"""


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class DockKeys(ChromePage):
    def keys(self, doc: str, width: int = 1440) -> list[str]:
        t = self.open(self.server.url_for(self.docs / doc))
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False}, t.session)
        t.wait_for(f"innerWidth === {width} && !!document.querySelector('.bd-anntb')")
        got = [k.split(":")[0] for k in t.ev(DOCK)]   # Request changes: N pending
        self.assertEqual(self.browser.errors, [])
        return got

    def test_the_same_four_tools_on_every_page_and_the_board_keys_on_boards(self) -> None:
        tools = ["View", "Element", "Region", "Text", "Pen"]
        self.assertEqual(self.keys("acme-saved-carts-plan.bluedoc.json"), [*tools, "|", "Hide comment marks", "|", "Request changes", "Approve this plan"])
        review = self.keys("acme-review-findings.bluedoc.json")
        self.assertEqual(review[:9], [*tools, "|", "Hide comment marks", "|", "Request changes"])
        self.assertEqual(len(review), 10, "the review ends with its send key")
        self.assertEqual(self.keys(FIT), [*tools, "|", "Link", "Frame", "|", "Hide comment marks", "|", "Request changes", "Approve this design"])
        self.assertEqual(self.keys("acme-fit-deck.bluedoc.json")[:11], [*tools, "|", "Link", "Frame", "|", "Hide comment marks", "|"])

    def test_at_390_px_the_tools_fold_between_view_and_link(self) -> None:
        self.assertEqual(self.keys(FIT, 390), ["View", "Comment tools", "Link", "Frame", "|", "Hide comment marks", "|", "Request changes", "Approve this design"])
        self.assertEqual(self.keys("acme-review-findings.bluedoc.json", 390)[:5], ["View", "Comment tools", "|", "Hide comment marks", "|"])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class BoardTextAndInteract(ChromePage, EditOnBoard):
    def setUp(self) -> None:
        super().setUp()
        self.doc = self.docs / FIT
        self.tab = self.open(self.server.url_for(self.doc))
        self.tab.wait_for("!!BP.boardEdit()")
        self.tab.ev("BP.board({focus: 'today'})")
        self.tab.wait_for("BP.board().artboards.find(a => a.id === 'today').ready", 15)

    def key(self, k: str, code: int) -> None:
        for kind in ("rawKeyDown", "char", "keyUp"):
            if kind == "char" and len(k) != 1:
                continue
            self.tab.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": k, "code": "Key" + k.upper() if len(k) == 1 else k, "windowsVirtualKeyCode": code,
                                                            **({"text": k} if kind == "char" else {})}, self.tab.session)

    def test_a_double_click_on_text_in_view_is_a_draft_the_count_shows(self) -> None:
        t, today = self.tab, self.scr("today.html")
        count = "(b => b.hidden ? '' : b.textContent)(document.querySelector('.bd-btb .bd-dcount'))"
        self.assertEqual(t.ev(count), "")
        self.assertEqual(t.ev("BP.board().mode"), "view")
        # while the edit is open, a tip under the screen says its keys; it goes when the edit ends
        tip = "document.querySelector('.bd-edtip')"
        self.assertTrue(t.ev(f"{tip}.hidden"))
        self.start_edit("today", today, '[data-bd="greeting"] h1')
        t.wait_for(f"!{tip}.hidden")
        self.assertEqual(t.ev(f"{tip}.textContent"), "Enter keeps it · Esc undoes · a click away keeps it")
        self.assertEqual(t.ev(f"[...{tip}.querySelectorAll('b')].map(b => b.textContent)"), ["Enter", "Esc"])
        r, f = t.ev(f"(r => [r.left, r.top, r.right, r.bottom])({tip}.getBoundingClientRect())"), t.ev("(r => [r.left, r.bottom])(document.querySelector('iframe.bd-ab-fr[data-ab=\"today\"]').getBoundingClientRect())")
        self.assertTrue(r[0] >= 8 and r[2] <= t.ev("innerWidth") - 8 and r[3] <= t.ev("innerHeight") - 8, r)
        self.assertTrue(r[1] >= f[1] or r[3] >= t.ev("innerHeight") - 9, "the tip isn't under the screen")
        self.tab.browser.call("Input.insertText", {"text": "Your day"}, t.session)
        self.key("Enter", 13)
        t.wait_for(f"{tip}.hidden")
        t.wait_for(f"{count} === '1 draft'")
        d = self.element_drafts()
        self.assertEqual([(x["element"]["op"], x["element"]["base"], x["element"]["text"]) for x in d], [("text", "Today", "Your day")])
        self.assertEqual(t.ev("BP.board().mode"), "view", "the double-click left View")
        self.assertIsNone(t.ev("BP.boardEdit().editing"))
        # Esc undoes an edit: no draft
        self.start_edit("today", today, '[data-bd="start-workout"]')
        self.tab.browser.call("Input.insertText", {"text": "Go"}, t.session)
        self.key("Escape", 27)
        time.sleep(0.3)
        self.assertEqual(len(self.element_drafts()), 1)
        self.assertEqual(self.frame_text(today, '[data-bd="start-workout"]')[0], "Start workout")
        self.assertEqual(self.browser.errors, [])

    def test_a_double_click_where_there_is_no_text_focuses_the_screen(self) -> None:
        t, today = self.tab, self.scr("today.html")
        t.ev("BP.board({fit: true})")
        time.sleep(0.6)
        k = t.ev("BP.board().k")
        x, y = self.at("today", today, '[data-bd="heart"]', .06, .1)   # the card's padding
        time.sleep(0.4)
        mouse(t, x, y, 2)
        t.wait_for(f"BP.board().k > {k} * 1.2 && BP.board().selected === 'today'")
        self.assertFalse(frame_eval(t, today, "!!document.querySelector('[contenteditable]')"))
        self.assertEqual(self.element_drafts(), [])
        self.assertEqual(self.browser.errors, [])

    def test_interact_takes_a_tap_in_a_screen_and_pauses_the_tools(self) -> None:
        t, today = self.tab, self.scr("today.html")
        btn = "document.querySelector('.bd-btb .bd-tbtn.play')"
        self.assertEqual(t.ev(f"[{btn}.textContent, {btn}.getAttribute('aria-pressed'), {btn}.getAttribute('aria-keyshortcuts')]"), ["Interact", "false", "I"])
        self.assertTrue(t.ev(f"{btn}.previousElementSibling.getAttribute('aria-label').startsWith('Present')"), "Interact sits after Present")
        link = t.ev("BP.board().links.find(l => l.from === 'today' && l.el === 'start-workout')")
        # Element on, then I: the screens take the clicks; the tool waits, its keys dim
        t.ev("BP.setMode('point')")
        t.ev("document.activeElement && document.activeElement.blur(), 1")
        self.key("i", 73)
        self.assertEqual(t.ev(f"[{btn}.getAttribute('aria-pressed'), BP.board().mode, BP.board().tool, BP.board().interact]"), ["true", "interact", "point", True])
        self.assertTrue(t.ev("document.querySelector('.bd-anntb').classList.contains('paused')"))
        self.assertEqual(t.ev("getComputedStyle(document.querySelector('.bd-anntb > [data-m=point]')).opacity"), "0.45")
        x, y = self.at("today", today, '[data-bd="start-workout"]')
        mouse(t, x, y)
        t.wait_for(f"BP.board().selected === {json.dumps(link['to'])}")
        self.assertTrue(t.ev("document.querySelector('.bd-cmp').hidden"), "a tap in Interact opened a comment box")
        self.assertEqual(t.ev("BP.annotations().length"), 0)
        # Esc ends it: the tool takes the screens again
        self.key("Escape", 27)
        self.assertEqual(t.ev(f"[{btn}.getAttribute('aria-pressed'), BP.board().mode]"), ["false", "point"])
        self.assertFalse(t.ev("document.querySelector('.bd-anntb').classList.contains('paused')"))
        # the button toggles it too
        t.ev(f"{btn}.click()")
        self.assertEqual(t.ev("BP.board().mode"), "interact")
        t.ev(f"{btn}.click()")
        self.assertEqual(t.ev("BP.board().mode"), "point")
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
