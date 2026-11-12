"""The dock with the comment tools in it and text edits at all times (1.0.25), and a board that never runs a screen's
clicks (1.0.26), in Chrome (BLUEDOC_BROWSER_TESTS=1).

Every page's dock is View │ Element · Region · Text · Pen, on a board then │ Link · Frame, then │ the eye │ Request
changes and the page's last key; at 390 px the four tools fold into one key between View and Link. On the Acme Fit
board a double-click on a screen's text in View edits it (a draft: the toolbar's count rises), a double-click where
there is no text focuses the screen, the toolbar has no Interact key and I does nothing: a click on a screen's link
on the board follows nothing, while in Present the same click follows it.

The dock and the top toolbars share one look (1.0.44): the dock, the board's toolbar, a compare view's keys and a
drawing's toolbar are each one pill 52 px tall, their keys round and 38 px, Request changes and Approve as tall as
the keys, and the pressed key stands out from the others in the light theme and the dark one."""
from __future__ import annotations

import time
import unittest

from test_inline_edit import EditOnBoard, frame_eval, mouse
from test_page_state import CHROME, ChromePage, Tab, until

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
        tools = ["View", "|", "Element", "Region", "Text", "Pen"]
        self.assertEqual(self.keys("acme-saved-carts-plan.bluedoc.json"), [*tools, "|", "Hide comment marks", "|", "Request changes", "Approve this plan"])
        review = self.keys("acme-review-findings.bluedoc.json")
        self.assertEqual(review[:10], [*tools, "|", "Hide comment marks", "|", "Request changes"])
        self.assertEqual(len(review), 11, "the review ends with its send key")
        self.assertEqual(self.keys(FIT), [*tools, "|", "Link", "Frame", "|", "Hide comment marks", "|", "Request changes", "Approve this design"])
        self.assertEqual(self.keys("acme-fit-deck.bluedoc.json")[:12], [*tools, "|", "Link", "Frame", "|", "Hide comment marks", "|"])

    def test_at_390_px_the_tools_fold_between_view_and_link(self) -> None:
        self.assertEqual(self.keys(FIT, 390), ["View", "|", "Comment tools", "Link", "Frame", "|", "Hide comment marks", "|", "Request changes", "Approve this design"])
        self.assertEqual(self.keys("acme-review-findings.bluedoc.json", 390)[:6], ["View", "|", "Comment tools", "|", "Hide comment marks", "|"])


# the dock's box and its room: the window between the stripes, less the panes open beside or over the page (over 900 px):
# the left one (a doc's Contents, a board's left panel) and the right one
ROOM = """(() => { const t = document.querySelector('.bd-anntb').getBoundingClientRect(), r = document.documentElement, side = innerWidth > 900;
  const st = innerWidth > 600 ? 40 : 0;
  const lp = side && r.classList.contains('bd-lp-open') ? document.querySelector(BP.board() ? '.bd-lp' : '.bp-side').offsetWidth : 0;
  const sp = side && r.classList.contains('bd-sp-open') ? document.querySelector('.bd-sp').offsetWidth : 0;
  return { left: t.left, right: t.right, h: t.height, lo: st + lp, hi: r.clientWidth - st - sp,
    words: [...document.querySelectorAll('.bd-anntb .bd-key .t')].some(e => e.checkVisibility()) }; })()"""


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class DockFitsItsRoom(ChromePage):
    def test_a_resized_window_keeps_the_dock_in_one_row_inside_its_room(self) -> None:
        """Narrowed with the panels open: the words go before the dock runs off the window or under a panel (1.0.40)."""
        for doc in (FIT, "acme-review-findings.bluedoc.json"):
            t = self.open(self.server.url_for(self.docs / doc))
            t.wait_for("!!document.querySelector('.bd-anntb') && !!window.BP", 20)
            t.ev("BP.sidebar({open: true}), document.querySelector('.bd-btb') ? BP.board().panel || document.querySelector('.bd-stripe.l .bd-sk').click() : BP.contents({open: true}), 1")
            for w in (1440, 1180, 1100, 860, 700, 640, 610, 390):
                with self.subTest(doc=doc, width=w):
                    self.browser.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, t.session)
                    t.wait_for(f"innerWidth === {w}")
                    time.sleep(0.4)   # the dock slides to its place
                    got = t.ev(ROOM)
                    self.assertLess(got["h"], 60, "one row")
                    self.assertGreaterEqual(got["left"], got["lo"] - 0.5, got)
                    self.assertLessEqual(got["right"], got["hi"] + 0.5, got)
                    if w == 1440:
                        self.assertTrue(got["words"], "a wide window keeps the words")
        self.assertEqual(self.browser.errors, [])


# each shown box's [width, height, corner radius] for a selector, and a selector's first box's height
BOXES = """(sel => [...document.querySelectorAll(sel)].filter(e => e.getClientRects().length)
  .map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height), parseFloat(getComputedStyle(e).borderTopLeftRadius)]; }))"""
HEIGHT = "(sel => Math.round(document.querySelector(sel).getBoundingClientRect().height))"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class BarsLook(ChromePage):
    def round_keys(self, t: Tab, sel: str) -> None:
        keys = t.ev(f"{BOXES}({sel!r})")
        self.assertTrue(keys, sel)
        for w, h, rad in keys:
            self.assertEqual((w, h), (38, 38), sel)
            self.assertGreaterEqual(rad, 19, f"{sel}: round")

    def test_the_dock_and_the_board_toolbar_are_one_size_and_the_pressed_key_shows(self) -> None:
        t = self.open(self.server.url_for(self.docs / FIT))
        t.wait_for("!!document.querySelector('.bd-anntb') && !!document.querySelector('.bd-btb')", 20)
        self.assertEqual((t.ev(f"{HEIGHT}('.bd-anntb')"), t.ev(f"{HEIGHT}('.bd-btb')")), (52, 52))
        self.round_keys(t, ".bd-anntb > .bd-key:not(.txt, .go, .fold)")
        self.round_keys(t, ".bd-btb > .bd-tbtn:not(.txt)")
        self.assertEqual({h for _, h, _ in t.ev(f"{BOXES}('.bd-anntb > :is(.bd-key.go, .bd-key.approve)')")}, {38}, "the action pills are as tall as the keys")
        bg = "(s => getComputedStyle(document.querySelector(s)).backgroundColor)"
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                t.ev(f"document.documentElement.dataset.theme = {theme!r}")
                time.sleep(0.3)   # the keys' colours ease
                on, off = t.ev(f"{bg}('.bd-anntb .bd-key[aria-pressed=true]')"), t.ev(f"{bg}('.bd-anntb .bd-key[data-m=region]')")
                self.assertNotEqual(on, off, "the pressed key stands out")
                self.assertNotEqual(on, "rgba(0, 0, 0, 0)")
        self.assertEqual(self.browser.errors, [])

    def test_a_compare_view_and_a_drawing_have_the_same_pill(self) -> None:
        t = self.open(self.server.url_for(self.docs / "acme-status.bluedoc.json"))
        t.go(f"{self.base}{self.server.url_for(self.docs / 'acme-status.bluedoc.json')}?diff=1")
        t.wait_for("!!document.querySelector('.bd-revbar .bd-revtb')")
        self.assertEqual(t.ev(f"{HEIGHT}('.bd-revbar .bd-revtb')"), 52)
        self.round_keys(t, ".bd-revbar .bd-revtb > .bd-key:not(.txt)")
        t = self.open(self.server.url_for(self.docs / "acme-orders.bluedoc.json"))
        t.wait_for("!!document.querySelector('.bp-tb .grp')")
        self.assertEqual(t.ev(f"{HEIGHT}('.bp-tb .grp')"), 52)
        self.round_keys(t, ".bp-tb .grp > button")
        self.assertEqual(self.browser.errors, [])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class BoardTextAndPresent(ChromePage, EditOnBoard):
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

    def test_the_board_runs_no_tap_and_present_follows_one(self) -> None:
        t, today = self.tab, self.scr("today.html")
        link = t.ev("BP.board().links.find(l => l.from === 'today' && l.el === 'start-workout')")
        # no Interact key in the toolbar, none in BP.board(); I leaves the tool as it is
        self.assertEqual(t.ev("""[...document.querySelectorAll('.bd-btb button')].filter(b => b.getAttribute('aria-keyshortcuts') === 'I'
          || /interact/i.test([b.textContent, b.title, b.getAttribute('aria-label')].join(' '))).length"""), 0)
        self.assertNotIn("interact", t.ev("Object.keys(BP.board())"))
        t.ev("document.activeElement && document.activeElement.blur(), 1")
        for mode in ("point", "view"):
            t.ev(f"BP.setMode('{mode}')")
            self.key("i", 73)
            self.assertEqual(t.ev("BP.board().mode"), mode)
        # in View a click on the screen's link on the board follows nothing
        x, y = self.at("today", today, '[data-bd="start-workout"]')
        mouse(t, x, y)
        time.sleep(0.6)
        self.assertEqual(t.ev("[BP.board().mode, BP.board().selected, BP.board().present]"), ["view", "today", False])
        # in Present the same click follows the link
        self.assertEqual(t.ev("BP.board({present: 'today'}).presented.screen"), "today")
        fr = "document.querySelector('.bd-pres iframe.bd-ab-fr')"
        t.wait_for(f"!!{fr}")
        r = until(lambda: frame_eval(t, today, """(e => e && (r => [r.left + r.width / 2, r.top + r.height / 2])(e.getBoundingClientRect()))(document.querySelector('[data-bd="start-workout"]'))"""))
        self.assertTrue(r, "no start-workout in the today screen")
        where = f"(f => {{ const b = f.getBoundingClientRect(), k = b.width / f.width; return [b.left + {r[0]} * k, b.top + {r[1]} * k]; }})({fr})"

        def tap():   # until the presented frame has loaded and been told its mode, a click there follows nothing
            mouse(t, *t.ev(where))
            return until(lambda: t.ev("BP.board().presented.screen") == link["to"], 1.5)
        self.assertTrue(until(tap, 12), "Present didn't follow the tap")
        self.assertEqual(t.ev("BP.annotations().length"), 0)
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
