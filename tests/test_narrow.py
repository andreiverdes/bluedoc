"""Phones (1.0.20): every example page fits 390, 360 and 320 px. The page is no wider than the window (a phone
would zoom it out), and the app bar and the bottom dock sit inside it: the app bar drops the wordmark and Share's and
Export's words and shortens its meter (under 381 px, its count alone, closer keys and Export without its chevron), the
dock's keys shrink, and a design page's dock drops the eye and an empty count.

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


if __name__ == "__main__":
    unittest.main()
