"""Phones (1.0.20): every example page fits 390, 360 and 320 px. The page is no wider than the window (a phone
would zoom it out), and the app bar and the bottom dock sit inside it: the app bar drops the wordmark and Share's and
Export's words and shortens its meter (under 381 px, its count alone, closer keys and Export without its chevron), the
dock's keys shrink, and a design page's dock drops the eye and an empty count.

A board's toolbar (design and website) is one row at 1440, 1180, 900, 600 and 390 px with both panels open: it stays
inside the board, beside a drawer over it where it fits there, no key sticks out of it, no groove doubles up or ends
it, and the keys it has no room for are in ⋯ More, where they still work (Sketch there turns the board to sketch).

Browser tests: BLUEDOC_BROWSER_TESTS=1 with Chrome (BLUEDOC_CHROME names it when it isn't in a usual place)."""
from __future__ import annotations

import time
import unittest

from test_page_state import CHROME, ChromePage, Tab

# the page's width, and each shown key of the app bar and the dock that runs past either edge of the window
FITS = """(() => {
  const out = [], shown = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
  for (const e of document.querySelectorAll('.bd-bar > *, .bd-bar-r > *, .bd-anntb:not(.bd-revtb) > *')) {
    if (!shown(e)) continue;
    const r = e.getBoundingClientRect();
    if (r.left < 0 || r.right > innerWidth) out.push((e.getAttribute('aria-label') || e.className) + ' ' + Math.round(r.left) + '–' + Math.round(r.right));
  }
  return {iw: innerWidth, sw: document.documentElement.scrollWidth, out};
})()"""

# the board's toolbar: its height against one key's, the board, the left drawer, the keys that stick out of it, and
# its shown children (| for a groove)
TOOLBAR = """(() => {
  const t = document.querySelector('.bd-btb'), r = t.getBoundingClientRect(), cs = getComputedStyle(t);
  const key = t.querySelector('.bd-tbtn').getBoundingClientRect(), board = t.parentElement.getBoundingClientRect();
  const lp = document.querySelector('.bd-lp'), drawer = innerWidth <= 900 && document.documentElement.classList.contains('bd-lp-open');
  const shown = [...t.children].filter(e => e.getClientRects().length);
  return {h: r.height, row: key.height + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom), left: r.left, right: r.right,
    board: [board.left, board.right], drawer: drawer ? lp.offsetLeft + lp.offsetWidth - board.left : 0,
    out: shown.filter(e => { const b = e.getBoundingClientRect(); return b.left < r.left - .5 || b.right > r.right + .5 || b.top < r.top - .5 || b.bottom > r.bottom + .5; })
      .map(e => e.getAttribute('aria-label') || e.className),
    keys: shown.map(e => e.matches('.bd-groove') ? '|' : e.getAttribute('aria-label') || e.className)};
})()"""


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class Narrow(ChromePage):
    def phone(self, t: Tab, w: int) -> None:
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 800, "deviceScaleFactor": 2, "mobile": True}, t.session)
        time.sleep(0.5)   # a page wider than the window widens the layout viewport a moment later

    def test_every_page_fits_a_phone(self) -> None:
        for doc in sorted(p.name for p in self.docs.glob("*.bluedoc.json")):
            t = self.open(self.server.url_for(self.docs / doc))
            t.wait_for("!!document.querySelector('.bd-anntb') && !!document.querySelector('.bd-bar-r')", 20)
            for w in (390, 360, 320):
                with self.subTest(doc=doc, width=w):
                    self.phone(t, w)
                    got = t.ev(FITS)
                    self.assertEqual((got["iw"], got["sw"]), (w, w), f"the page is wider than {w} px")
                    self.assertEqual(got["out"], [], "keys past the window's edge")
        self.assertEqual(self.browser.errors, [])

    def test_a_folded_question_with_a_reply_keeps_its_chevron_beside_the_title(self) -> None:
        """At 860 px (the narrow layout, where a question's head wraps), a folded question with a reply waiting shows
        the reply's icon and its chevron on the title's row, not the chevron on a line of its own."""
        t = self.open(self.server.url_for(self.docs / "acme-saved-carts-plan.bluedoc.json"))
        t.wait_for("!!window.BP && !!document.querySelector('#item-decisions-retention .pv-chev')", 20)
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": 860, "height": 900, "deviceScaleFactor": 1, "mobile": False}, t.session)
        t.ev("BP.setNote('decisions/retention', 'Acme: why not 90 days?')")
        li = "document.querySelector('#item-decisions-retention')"
        t.wait_for(f"{li}.classList.contains('has-note')")
        if t.ev(f"{li}.classList.contains('open')"):
            t.ev(f"{li}.querySelector('.bp-cl-head').click()")
        t.wait_for(f"!{li}.classList.contains('open')")
        top = "(s => Math.round(document.querySelector('#item-decisions-retention ' + s).getBoundingClientRect().top))"
        title, note, chev = (t.ev(f"{top}('{s}')") for s in (".bp-cl-text", ".bp-cl-noteic", ".pv-chev"))
        self.assertLess(abs(chev - title), 12, "the chevron sits on the title's row")
        self.assertLess(abs(note - title), 12, "the reply's icon sits on the title's row")
        self.assertEqual(self.browser.errors, [])

    def test_the_compact_share_key_centres_its_icon(self) -> None:
        """Between 601 and 900 px Share drops its word: its icon sits in the middle of the round key."""
        t = self.open(self.server.url_for(self.docs / "acme-status.bluedoc.json"))
        t.wait_for("!!document.querySelector('.bd-shtray > .bd-shk svg')", 20)
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": 860, "height": 800, "deviceScaleFactor": 1, "mobile": False}, t.session)
        off = t.wait_for("(k => { const b = k.getBoundingClientRect(), i = k.querySelector('svg').getBoundingClientRect(); "
                         "return b.width < 40 && [Math.round(i.left + i.width / 2 - b.left - b.width / 2)]; })(document.querySelector('.bd-shtray > .bd-shk'))")
        self.assertEqual(off, [0])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class BoardToolbar(ChromePage):
    def board(self, doc: str) -> Tab:
        t = self.open(self.server.url_for(self.docs / doc))
        t.wait_for("!!document.querySelector('.bd-btb') && !!window.BP && !!BP.board()", 20)
        return t

    def width(self, t: Tab, w: int) -> None:
        """The window at w px, both panels open (on a phone, the left one a drawer over the board)."""
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": w < 700}, t.session)
        t.wait_for(f"innerWidth === {w}")
        time.sleep(0.3)   # the page has laid itself out for the width (a pane over the board hides the other side's)
        t.ev("BP.sidebar({open: true}), BP.board().panel || document.querySelector('.bd-stripe.l .bd-sk, .bd-bk.l').click(), 1")
        time.sleep(0.6)   # the panels slide in

    def test_one_row_at_every_width_with_both_panels_open(self) -> None:
        for doc in ("acme-fit-design.bluedoc.json", "acme-site.bluedoc.json"):
            t = self.board(doc)
            for w in (1440, 1180, 900, 600, 390):
                with self.subTest(doc=doc, width=w):
                    self.width(t, w)
                    self.assertTrue(t.ev("BP.board().panel"))
                    got = t.ev(TOOLBAR)
                    self.assertAlmostEqual(got["h"], got["row"], delta=0.5, msg=f"more than one row: {got['keys']}")
                    self.assertEqual(got["out"], [], "keys stick out of the toolbar")
                    self.assertGreaterEqual(got["left"], got["board"][0] + max(got["drawer"], 0) - 0.5 if w > 390 else 0, "over the left panel")
                    self.assertLessEqual(got["right"], got["board"][1] + 0.5, "past the board")
                    keys = got["keys"]
                    self.assertNotIn("|", (keys[0], keys[-1]), keys)
                    self.assertNotIn("||", "".join("|" if k == "|" else "k" for k in keys), keys)
                    self.assertTrue(any(k.startswith("Zoom in") for k in keys) and any(k.startswith("Fit all") for k in keys), keys)
        self.assertEqual(self.browser.errors, [])

    def test_an_overflowed_key_works_from_more(self) -> None:
        t = self.board("acme-fit-design.bluedoc.json")
        self.width(t, 560)   # the left panel's drawer (240 px) leaves the row 320 px
        more = "document.querySelector('.bd-btb .bd-btb-more')"
        self.assertFalse(t.ev(f"{more}.hidden"), "a narrow board has ⋯ More")
        self.assertFalse(t.ev("document.querySelector('.bd-btb .fid').checkVisibility()"), "the fidelity went into ⋯")
        self.assertFalse(t.ev("BP.board().sketch"))
        t.ev(f"{more}.querySelector('button').click()")
        rows = t.ev(f"[...{more}.querySelectorAll('[role^=menuitem]')].map(r => [r.querySelector('.l').textContent, (r.querySelector('.m') || {{}}).textContent || ''])")
        self.assertIn(["Focus the selected screen", "F"], rows)
        self.assertIn(["Nothing to undo", t.ev("navigator.platform.startsWith('Mac') ? '⌘Z' : 'Ctrl+Z'")], rows)
        t.ev(f"[...{more}.querySelectorAll('[role=menuitemradio]')].find(r => r.textContent === 'Sketch').click()")
        self.assertTrue(t.ev("BP.board().sketch"), "Sketch from ⋯ turns the board to sketch")
        self.assertTrue(t.ev(f"{more}.querySelector('[role=menu]').hidden"), "a pick closes ⋯")
        t.ev(f"{more}.querySelector('button').click()")
        self.assertEqual(t.ev(f"{more}.querySelector('[role=menuitemradio][aria-checked=true]').textContent"), "Sketch")
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
