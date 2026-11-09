"""The Annotate key and its bar in Chrome (BLUEDOC_BROWSER_TESTS=1): A opens the bar on Element, C M T D pick Element,
Region, Text and Pen, Esc and V close it back to View, and A opens it again on the tool used last. Pen shows its colours
and widths in a pill beside the tools; the pick survives a reload, a stroke is drawn in it and the drawing records it,
and the custom colour comes from the picker. A Region drag becomes a note on the smallest element holding it (a click
makes none). Text selected in View gets a Comment button that makes the note Text makes. At 390 px the bar is centred
over the tray with a colour key and a width key, each opening a menu that Esc closes first."""
from __future__ import annotations

import json
import time
import unittest

from test_page_state import CHROME, ChromePage, Tab, until

# the dock's mode, the Annotate key's state, whether the bar shows and its pressed tool
STATE = """(() => { const k = document.querySelector('.bd-key.ann'), row = document.querySelector('.bd-annrow');
  return [document.querySelector('.bd-anntb').dataset.m, k.getAttribute('aria-expanded'), !row.hidden,
    [...row.querySelectorAll('.bd-annb.tail [data-m]')].filter(b => b.getAttribute('aria-pressed') === 'true').map(b => b.getAttribute('aria-label')).join()]; })()"""
CENTRE = "(r => [r.left + r.width / 2, r.top + r.height / 2])(document.querySelector({}).getBoundingClientRect())"
SHOWN = "(e => !!e && e.getClientRects().length > 0)(document.querySelector({}))"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class AnnotateBar(ChromePage):
    def key(self, tab: Tab, k: str) -> None:
        code = {"Escape": (27, "Escape", ""), "Enter": (13, "Enter", "\r")}.get(k) or (ord(k.upper()), "Key" + k.upper(), k)
        for kind in ("keyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": k, "code": code[1], "windowsVirtualKeyCode": code[0],
                                                         **({"text": code[2]} if kind == "keyDown" and code[2] else {})}, tab.session)

    def mouse(self, tab: Tab, kind: str, x: float, y: float, buttons: int = 0) -> None:
        self.browser.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "buttons": buttons, "clickCount": 1}, tab.session)

    def click(self, tab: Tab, sel: str) -> None:
        x, y = tab.ev(CENTRE.format(json.dumps(sel)))
        self.mouse(tab, "mousePressed", x, y, 1)
        self.mouse(tab, "mouseReleased", x, y)

    def drag(self, tab: Tab, x0: float, y0: float, x1: float, y1: float) -> None:
        self.mouse(tab, "mousePressed", x0, y0, 1)
        for i in range(1, 9):
            self.mouse(tab, "mouseMoved", x0 + (x1 - x0) * i / 8, y0 + (y1 - y0) * i / 8, 1)
        self.mouse(tab, "mouseReleased", x1, y1)

    def save_note(self, tab: Tab, note: str) -> None:
        tab.wait_for("!!document.querySelector('.bd-cmp:not([hidden]) textarea')")
        tab.ev(f"(ta => {{ ta.value = {json.dumps(note)}; ta.dispatchEvent(new Event('input', {{bubbles: true}})); }})(document.querySelector('.bd-cmp textarea'))")
        tab.ev("[...document.querySelectorAll('.bd-cmp .bp-btn.primary')].find(b => b.textContent === 'Save').click()")
        tab.wait_for("document.querySelector('.bd-cmp').hidden")

    def page(self, width: int = 1440) -> Tab:
        t = self.open(self.server.url_for(self.plan))
        self.browser.call("Page.bringToFront", {}, t.session)   # the earlier tests' tabs stay open: this one must paint (rAF)
        if width != 1440:
            self.browser.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": 844, "deviceScaleFactor": 1, "mobile": False}, t.session)
        t.ev("BP.sidebar({open: false}), scrollTo(0, 0)")
        return t

    def test_a_opens_the_bar_on_element_the_tool_keys_switch_and_esc_returns_to_view(self) -> None:
        t = self.page()
        self.assertEqual(t.ev(STATE), ["view", "false", False, ""])
        self.key(t, "a")
        self.assertEqual(t.ev(STATE), ["point", "true", True, "Element"])
        for k, mode, name in (("m", "region", "Region"), ("t", "select", "Text"), ("d", "draw", "Pen"), ("c", "point", "Element"), ("d", "draw", "Pen")):
            self.key(t, k)
            self.assertEqual(t.ev(STATE), [mode, "true", True, name], k)
        self.key(t, "Escape")
        self.assertEqual(t.ev(STATE), ["view", "false", False, ""])
        self.key(t, "a")   # the tool used last
        self.assertEqual(t.ev(STATE), ["draw", "true", True, "Pen"])
        self.key(t, "v")
        self.assertEqual(t.ev(STATE), ["view", "false", False, ""])
        self.key(t, "t")   # a tool key opens the bar from View
        self.assertEqual(t.ev(STATE), ["select", "true", True, "Text"])
        self.click(t, ".bd-key.ann")   # the Annotate key closes it
        self.assertEqual(t.ev(STATE), ["view", "false", False, ""])
        self.click(t, ".bd-key.ann")
        self.assertEqual(t.ev(STATE), ["select", "true", True, "Text"])
        self.click(t, ".bd-anntb [data-m=view]")
        self.assertEqual(t.ev(STATE), ["view", "false", False, ""])
        # the old dock keys and swatches are gone: Element, Region, Text and Pen live in the bar only
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-anntb > .bd-key')].map(b => b.getAttribute('aria-label')).slice(0, 2)"), ["View", "Annotate"])
        self.assertEqual(t.ev("document.querySelectorAll('.bd-anntb > .sw').length"), 0)
        self.assertEqual(self.browser.errors, [])

    def test_pen_colour_and_width_persist_and_a_drawing_records_them(self) -> None:
        t = self.page()
        self.key(t, "c")
        self.assertFalse(t.ev(SHOWN.format(json.dumps(".bd-annb.opt"))), "the pen's pill shows with Pen only")
        self.key(t, "d")
        self.assertTrue(t.ev(SHOWN.format(json.dumps(".bd-annb.opt"))))
        self.click(t, ".bd-annb.opt [data-pen=violet]")
        self.click(t, ".bd-annb.opt [data-w='7']")
        self.assertEqual(t.ev("[localStorage.getItem('bluedoc:pen'), localStorage.getItem('bluedoc:pen-width')]"), ["violet", "7"])
        t.go(t.ev("location.href"))
        t.ev("BP.sidebar({open: false}), scrollTo(0, 0)")
        self.key(t, "d")
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-annb.opt [aria-pressed=true]')].map(b => b.dataset.pen || b.dataset.w)"), ["violet", "7"])
        x, y = t.ev("(r => [r.left + 40, r.bottom + 60])(document.querySelector('h1').getBoundingClientRect())")
        self.drag(t, x, y, x + 240, y + 50)
        t.wait_for("!!document.querySelector('.bd-cmp:not([hidden])') && !!document.querySelector('.bd-ann-ink path')")
        # the drawing being written shows in its pen, 2 px wider while it is on
        ink = "getComputedStyle(document.querySelector('.bd-ann-ink path'))"
        self.assertEqual(t.ev(f"{ink}.strokeWidth"), "9px")
        self.assertEqual(t.ev(f"{ink}.stroke"), t.ev("getComputedStyle(document.querySelector('.bd-annb.opt [data-pen=violet]')).backgroundColor"))
        self.save_note(t, "Acme: circle the title")
        a = t.ev("BP.annotations()")[0]
        self.assertEqual([a["type"], a["color"], a["width"]], ["draw", "violet", 7])
        # the custom colour: the picker's hex, then Use (Enter); the swatch shows it, the next drawing records it
        self.click(t, ".bd-annb.opt .cust")
        t.wait_for("document.activeElement === document.querySelector('.bd-cpick .f')")
        t.ev("(f => { f.value = '#12ab34'; f.dispatchEvent(new Event('input', {bubbles: true})); })(document.querySelector('.bd-cpick .f'))")
        self.key(t, "Enter")
        t.wait_for("document.querySelector('.bd-annpop').hidden")
        self.assertEqual(t.ev("[localStorage.getItem('bluedoc:pen'), localStorage.getItem('bluedoc:pen-custom')]"), ["#12ab34", "#12ab34"])
        self.assertEqual(t.ev("(b => [b.getAttribute('aria-pressed'), b.classList.contains('set')])(document.querySelector('.bd-annb.opt .cust'))"), ["true", True])
        self.drag(t, x, y + 120, x + 200, y + 150)
        self.save_note(t, "Acme: and this")
        self.assertEqual(t.ev("BP.annotations().map(a => a.color)"), ["violet", "#12ab34"])
        self.assertEqual(self.browser.errors, [])

    def test_a_region_drag_makes_a_note_on_the_smallest_element_holding_it(self) -> None:
        t = self.page()
        self.key(t, "m")
        l, top = t.ev("(r => [r.left, r.top])(document.querySelector('.bd-tldr-card').getBoundingClientRect())")
        self.drag(t, l + 100, top + 30, l + 104, top + 33)   # under 8 px: nothing
        time.sleep(0.3)
        self.assertIsNone(t.ev("BP.comments().draft"))
        self.drag(t, l + 100, top + 30, l + 400, top + 90)
        t.wait_for("!!document.querySelector('.bd-cmp:not([hidden])')")
        self.assertEqual(t.ev("document.querySelector('.bd-cmp .lb').textContent"), "Region on TL;DR")
        t.wait_for(SHOWN.format(json.dumps(".bd-ann-rgn")))
        self.save_note(t, "Acme: say which step comes first")
        a = t.ev("BP.annotations()")[0]
        self.assertEqual([a["type"], a["target"]["key"]], ["region", "tldr"])
        self.assertEqual(len(a["box"]), 4)
        self.assertTrue(all(-0.1 <= v <= 1.1 for v in a["box"]), a["box"])
        self.assertTrue(t.ev(SHOWN.format(json.dumps(".bd-ann-rgn"))), "a saved region keeps its box")
        md = t.ev("BP.changesPayload().markdown")
        self.assertIn("**Region on TL;DR** (region) `tldr`", md)
        self.assertEqual(t.ev("BP.changesPayload().annotations[0].type"), "region")
        # the server keeps it (state.db): a reload draws it again
        key = "__ann:" + a["id"]
        self.assertTrue(until(lambda: key in self.state(self.server.url_for(self.plan))), "the server dropped the region")
        t.go(t.ev("location.href"))
        t.wait_for(SHOWN.format(json.dumps(".bd-ann-rgn")))
        self.assertEqual(self.browser.errors, [])

    def test_text_selected_in_view_gets_a_comment_button(self) -> None:
        t = self.page()
        # the TL;DR's first line of text
        x0, y, x1 = t.ev("""(() => { const w = document.createTreeWalker(document.querySelector('.bd-tldr-card'), NodeFilter.SHOW_TEXT); let n;
          while ((n = w.nextNode()) && n.data.trim().length < 20); const r = document.createRange(); r.selectNodeContents(n);
          const b = r.getClientRects()[0]; return [b.left + 2, b.top + b.height / 2, b.left + Math.min(220, b.width - 2)]; })()""")
        self.drag(t, x0, y, x1, y)
        t.wait_for(SHOWN.format(json.dumps(".bd-selc")))
        quote = t.ev("getSelection().toString().trim()")
        self.assertTrue(quote)
        self.key(t, "Escape")   # Esc hides it and leaves the selection
        self.assertFalse(t.ev(SHOWN.format(json.dumps(".bd-selc"))))
        self.assertEqual(t.ev("getSelection().toString().trim()"), quote)
        t.ev("getSelection().removeAllRanges()")   # a press on selected text would drag it, not select
        self.drag(t, x0, y, x1, y)
        t.wait_for(SHOWN.format(json.dumps(".bd-selc")))
        self.click(t, ".bd-selc")
        t.wait_for("!!document.querySelector('.bd-cmp:not([hidden])')")
        self.assertEqual(t.ev("document.querySelector('.bd-anntb').dataset.m"), "view", "the page stays in View")
        self.save_note(t, "Acme: shorter, please")
        a = t.ev("BP.annotations()")[0]
        self.assertEqual([a["type"], a["target"]["key"], a["quote"]], ["text", "tldr", quote])
        self.assertFalse(t.ev(SHOWN.format(json.dumps(".bd-selc"))))
        self.assertEqual(self.browser.errors, [])

    def test_at_390_px_the_bar_is_centred_with_colour_and_width_menus(self) -> None:
        t = self.page(390)
        self.key(t, "a")
        mid = "(r => r.left + r.width / 2)(document.querySelector({}).getBoundingClientRect())"
        self.assertLessEqual(abs(t.ev(mid.format(json.dumps(".bd-annrow"))) - t.ev(mid.format(json.dumps(".bd-anntb")))), 1)
        self.assertFalse(t.ev(SHOWN.format(json.dumps(".bd-annb.opt"))))
        self.assertEqual(t.ev("getComputedStyle(document.querySelector('.bd-annb.tail'), '::after').display"), "none", "no tail")
        self.assertFalse(t.ev(SHOWN.format(json.dumps(".bd-key.ann .t"))), "the Annotate key keeps its icon and caret")
        keys = "[...document.querySelectorAll('.bd-annb .bd-key.sty')].map(k => [k.getClientRects().length > 0, k.disabled])"
        self.assertEqual(t.ev(keys), [[True, True], [True, True]], "the colour and width keys wait for Pen")
        self.key(t, "d")
        self.assertEqual(t.ev(keys), [[True, False], [True, False]])
        self.click(t, ".bd-key.sty[aria-label='Pen colour']")
        t.wait_for(SHOWN.format(json.dumps(".bd-annpop")))
        self.assertEqual(t.ev("document.querySelectorAll('.bd-annpop .sw button').length"), 7)
        self.click(t, ".bd-annpop [data-pen=warn]")
        t.wait_for("document.querySelector('.bd-annpop').hidden")
        self.assertEqual(t.ev("[localStorage.getItem('bluedoc:pen'), document.querySelector('.bd-key.sty .dot').classList.contains('bd-pen-warn')]"), ["warn", True])
        self.click(t, ".bd-key.sty[aria-label='Stroke width']")
        t.wait_for(SHOWN.format(json.dumps(".bd-annpop")))
        self.assertEqual(t.ev("document.querySelectorAll('.bd-annpop .bd-wt button').length"), 3)
        self.key(t, "Escape")   # the menu first, the tool stays
        t.wait_for("document.querySelector('.bd-annpop').hidden")
        self.assertEqual(t.ev(STATE)[:3], ["draw", "true", True])
        self.click(t, ".bd-key.sty[aria-label='Stroke width']")
        self.click(t, ".bd-annpop [data-w='2']")
        self.assertEqual(t.ev("localStorage.getItem('bluedoc:pen-width')"), "2")
        self.assertEqual(t.ev("document.querySelector('.bd-key.sty svg.w line').getAttribute('stroke-width')"), "2")
        self.key(t, "Escape")
        self.assertEqual(t.ev(STATE), ["view", "false", False, ""])
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
