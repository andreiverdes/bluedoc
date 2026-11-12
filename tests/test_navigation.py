"""One navigation in every tool, in Chrome (BLUEDOC_BROWSER_TESTS=1): a tool takes only the primary press; the wheel,
a pinch (⌃ + wheel), Space + drag and a middle-button drag stay with the board or the diagram under the pointer.

On the Acme Fit design board, in each tool (view, point, select, draw, link, frame), over a screen: the wheel pans the
board, ⌃ + wheel zooms it at the pointer, Space + drag and a middle-button drag pan it, and the tool, the comments and
the screens' places stay as they were (nav/board); in Draw the wheel over the empty board pans it (nav/draw-board);
Shift + 0, 1, 2 show 100 %, fit, and focus the selected screen (nav/keys). On the Acme orders doc, ⌃ + wheel over its
diagram zooms the diagram in Point, Select and Draw, Space + drag over it pans it in Draw without a stroke, and the
wheel above it on the Draw layer scrolls the page (nav/doc)."""
from __future__ import annotations

import time
import unittest

from test_page_state import CHROME, ChromePage, Tab

FIT = "acme-fit-design.bluedoc.json"
ORDERS = "acme-orders.bluedoc.json"
BOARD_MODES = ["view", "point", "select", "draw", "link", "frame"]
CTRL, SHIFT = 2, 8
FRAME = "document.querySelector('iframe.bd-ab-fr[data-ab=\"today\"]')"
VIEW = "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(document.querySelector('.bd-bvp').style.transform.match(/-?\\d*\\.?\\d+(e-?\\d+)?/g).map(Number)))))"


class Input:
    """Mouse, wheel and keys through DevTools, as a reader's."""
    tab: Tab

    def call(self, method: str, params: dict) -> None:
        self.tab.browser.call(method, params, self.tab.session)

    def wheel(self, x: float, y: float, dy: float, dx: float = 0, mods: int = 0) -> None:
        self.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": dx, "deltaY": dy, "modifiers": mods})
        time.sleep(0.15)   # a screen forwards it by postMessage

    def drag(self, x: float, y: float, dx: float, dy: float, button: str = "left") -> None:
        held = {"left": 1, "middle": 4}[button]
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        self.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": button, "buttons": held, "clickCount": 1})
        for f in (0.25, 0.5, 0.75, 1):
            self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x + dx * f, "y": y + dy * f, "button": button, "buttons": held})
            time.sleep(0.03)
        self.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x + dx, "y": y + dy, "button": button, "buttons": 0, "clickCount": 1})
        time.sleep(0.15)

    def space(self, down: bool) -> None:
        self.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": " ", "code": "Space", "windowsVirtualKeyCode": 32, "text": " "} if down
                  else {"type": "keyUp", "key": " ", "code": "Space", "windowsVirtualKeyCode": 32})

    def space_drag(self, x: float, y: float, dx: float, dy: float) -> None:
        self.space(True)
        assert self.tab.ev("document.documentElement.classList.contains('bd-space')"), "Space held shows no hand"
        self.drag(x, y, dx, dy)
        self.space(False)

    def shift_digit(self, d: int) -> None:
        for typ in ("rawKeyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", {"type": typ, "key": ")!@"[d], "code": f"Digit{d}", "windowsVirtualKeyCode": 48 + d, "modifiers": SHIFT})
        time.sleep(0.5)   # a fit or a focus animates


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class BoardNavigation(ChromePage, Input):
    def setUp(self) -> None:
        super().setUp()
        self.tab = self.open(self.server.url_for(self.docs / FIT))
        self.tab.wait_for("!!BP.boardEdit()")
        self.tab.ev("BP.board({focus: 'today'})")
        self.tab.wait_for("BP.board().artboards.find(a => a.id === 'today').ready", 15)
        time.sleep(0.5)

    def screen_point(self) -> list:
        """The middle of the Today screen's frame, on the window."""
        return self.tab.ev(f"(r => [r.left + r.width / 2, r.top + r.height / 2])({FRAME}.getBoundingClientRect())")

    def test_wheel_pinch_and_pans_over_a_screen_in_every_tool(self) -> None:
        t = self.tab
        for mode in BOARD_MODES:
            with self.subTest(mode=mode):
                t.ev("BP.setMode('view'); BP.board({focus: 'today'})")   # each tool from the same view, whatever the last one left
                time.sleep(0.4)
                t.ev(f"BP.setMode('{mode}')")
                time.sleep(0.3)
                notes, places = t.ev("BP.annotations().length"), t.ev("JSON.stringify(BP.boardEdit().positions)")
                x, y = self.screen_point()
                tx, ty, k = t.ev(VIEW)
                self.wheel(x, y, 120)
                tx1, ty1, k1 = t.ev(VIEW)
                self.assertEqual((round(tx1 - tx), round(ty1 - ty), k1), (0, -120, k), "the wheel didn't pan the board")
                self.wheel(x, y, 60, dx=0, mods=SHIFT)
                tx2, ty2, _ = t.ev(VIEW)
                self.assertEqual((round(tx2 - tx1), round(ty2 - ty1)), (-60, 0), "Shift + wheel didn't pan sideways")
                x, y = self.screen_point()
                self.wheel(x, y, -40, mods=CTRL)
                tx3, ty3, k3 = t.ev(VIEW)
                self.assertGreater(k3, k1 * 1.3, "⌃ + wheel didn't zoom the board")
                at = t.ev("(r => [r.left, r.top])(document.querySelector('.bd-board').getBoundingClientRect())")
                before, after = [(x - at[0] - tx2) / k1, (y - at[1] - ty2) / k1], [(x - at[0] - tx3) / k3, (y - at[1] - ty3) / k3]
                self.assertAlmostEqual(before[0], after[0], delta=2, msg="the zoom isn't at the pointer")
                self.assertAlmostEqual(before[1], after[1], delta=2, msg="the zoom isn't at the pointer")
                x, y = self.screen_point()
                self.space_drag(x, y, 70, 40)
                tx4, ty4, _ = t.ev(VIEW)
                self.assertEqual((round(tx4 - tx3), round(ty4 - ty3)), (70, 40), "Space + drag didn't pan the board")
                self.assertFalse(t.ev("document.documentElement.classList.contains('bd-space')"))
                x, y = self.screen_point()
                self.drag(x, y, -50, 30, "middle")
                tx5, ty5, _ = t.ev(VIEW)
                for got, want in ((tx5 - tx4, -50), (ty5 - ty4, 30)):   # from a screen: its moves come by postMessage, in frame px
                    self.assertAlmostEqual(got, want, delta=2, msg="a middle-button drag didn't pan the board")
                self.assertEqual((t.ev("BP.board().mode"), t.ev("BP.annotations().length"), t.ev("JSON.stringify(BP.boardEdit().positions)")),
                                 (mode, notes, places), "the tool changed, or a press made a comment or moved a screen")
        self.assertEqual(self.browser.errors, [])

    def test_in_draw_the_wheel_over_the_empty_board_pans(self) -> None:
        t = self.tab
        t.ev("BP.setMode('draw')")
        x, y = t.ev("""(() => { const b = document.querySelector('.bd-board'), r = b.getBoundingClientRect();
          for (let y = r.top + 120; y < r.bottom - 120; y += 20) for (let x = r.left + 40; x < r.right - 40; x += 20) {
            const el = document.elementsFromPoint(x, y).find(n => !n.closest('.bd-ann-cap'));
            if (el === b) return [x, y]; } })()""")
        tx, ty, k = t.ev(VIEW)
        self.wheel(x, y, -90, dx=30)
        tx1, ty1, k1 = t.ev(VIEW)
        self.assertEqual((round(tx1 - tx), round(ty1 - ty), k1), (-30, 90, k))
        self.assertEqual(t.ev("BP.annotations().length"), 0)

    def test_shift_0_1_2(self) -> None:
        t = self.tab
        focused = t.ev("BP.board().k")
        t.ev("BP.board({fit: true})")
        time.sleep(0.4)
        fit = t.ev("BP.board().k")
        t.ev("BP.board({focus: 'today'})")
        time.sleep(0.5)
        self.shift_digit(0)
        self.assertAlmostEqual(t.ev("BP.board().k"), 1, places=6)   # zoomBy(1 / k): k × (1 / k) may miss 1 by a float step
        self.shift_digit(1)
        self.assertAlmostEqual(t.ev("BP.board().k"), fit, places=3)
        self.shift_digit(2)
        self.assertAlmostEqual(t.ev("BP.board().k"), focused, places=3)


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class DocNavigation(ChromePage, Input):
    CV = "Object.values(BP.canvases)[0]"

    def setUp(self) -> None:
        super().setUp()
        self.tab = self.open(self.server.url_for(self.docs / ORDERS))
        self.tab.ev(f"{self.CV}.stage.scrollIntoView({{block: 'center'}})")
        time.sleep(0.5)

    def middle(self) -> list:
        return self.tab.ev(f"(r => [r.left + r.width / 2, r.top + r.height / 2])({self.CV}.stage.getBoundingClientRect())")

    def test_the_diagram_zooms_and_pans_under_the_tools(self) -> None:
        t = self.tab
        for mode in ("point", "select", "draw"):
            with self.subTest(mode=mode):
                t.ev(f"BP.setMode('{mode}')")
                x, y = self.middle()
                k = t.ev(f"{self.CV}.k")
                self.wheel(x, y, -40, mods=CTRL)
                self.assertGreater(t.ev(f"{self.CV}.k"), k * 1.3, "⌃ + wheel over the diagram didn't zoom it")
                t.ev(f"BP.setMode('view'); {self.CV}.fit(false)")
        t.ev("BP.setMode('draw')")
        x, y = self.middle()
        tx, ty = t.ev(f"[{self.CV}.tx, {self.CV}.ty]")
        self.space_drag(x, y, 60, -30)
        tx1, ty1 = t.ev(f"[{self.CV}.tx, {self.CV}.ty]")
        self.assertEqual((round(tx1 - tx), round(ty1 - ty)), (60, -30), "Space + drag over the diagram didn't pan it")
        self.assertEqual(t.ev("BP.annotations().length"), 0, "Space + drag drew a stroke")
        # above the diagram the Draw layer lets the page scroll
        y0, top = t.ev("scrollY"), t.ev(f"{self.CV}.stage.getBoundingClientRect().top")
        self.wheel(x, top - 30, 200)
        self.assertGreater(t.ev("scrollY"), y0, "the wheel on the Draw layer didn't scroll the page")
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
