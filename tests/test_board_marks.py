"""Comment marks on a board stay on the screen and spot they were made on (BLUEDOC_BROWSER_TESTS=1). A Region or
drawing made on a board, over a screen's frame, beside the screens or across two, is the board's (`board:<id>`) with
`where` (board px, and its part on each screen); its box is kept in the px of the screen holding most of it, so it
follows that screen when the layout moves it, and in board px beside the screens; it is drawn in the board's marks
layer, so it pans and zooms with the board. A pin on an element in a screen sits on the element's spot (`spot`, the
screen's px), also when the frame isn't live, never on the screen's title; pins on one spot fan out. On a live page a
pin and a region keep their place in Full page and Viewport (where the frame scrolls, a region past it is cut, a pin
sits at its edge, away). Marks from before (on the board's block, a box in the board's view) lose their place: a card
saying so, no mark; ones on the board's old world take its board px."""
from __future__ import annotations

import json
import re
import time
import unittest

from test_page_state import CHROME, ChromePage, Tab, until
from test_website import SiteInChrome, site_doc, board_of

DESIGN = "acme-fit-design.bluedoc.json"
# an element's client rect [left, top, width, height]
RECT = "(e => e ? (r => [r.left, r.top, r.width, r.height])(e.getBoundingClientRect()) : null)(document.querySelector({}))"
# the screen under a point, below the comment tools' drawing layer (its frame, or its outline)
UNDER = "(e => e && e.closest('.bd-ab') ? e.closest('.bd-ab').dataset.ab : null)(document.elementsFromPoint({}, {}).find(e => !e.closest('.bd-ann-cap')))"
# a mark's pin: its tail (the spot it points at, by how its bubble opens), classes and its place in board px
PIN = """(p => { if (!p || p.hidden) return null; const r = p.getBoundingClientRect(), c = p.classList, m = /^(-?[\\d.]+)px (-?[\\d.]+)px$/.exec(p.style.translate);
  return { x: c.contains('fl') ? r.right : r.left, y: c.contains('fb') ? r.top : r.bottom, cls: p.className, n: p.textContent, at: m ? [+m[1], +m[2]] : null,
    world: !!p.closest('.bd-bmk') }; })(document.querySelector('.bd-ann-pin[data-ann="{}"]'))"""


def rgn(aid: str) -> str:
    """A region's box in the window, null while it doesn't show."""
    return f"(e => e && e.style.display !== 'none' && e.closest('.bd-bmk') ? (r => [r.left, r.top, r.width, r.height])(e.getBoundingClientRect()) : null)(document.querySelector('.bd-ann-rgn[data-ann=\"{aid}\"]'))"


class Marks:
    """Pointer and comment helpers for a ChromePage or a SiteInChrome."""

    def mouse(self, t: Tab, kind: str, x: float, y: float, buttons: int = 0) -> None:
        self.browser.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "buttons": buttons, "clickCount": 1}, t.session)

    def drag(self, t: Tab, x0: float, y0: float, x1: float, y1: float) -> None:
        self.mouse(t, "mousePressed", x0, y0, 1)
        for i in range(1, 9):
            self.mouse(t, "mouseMoved", x0 + (x1 - x0) * i / 8, y0 + (y1 - y0) * i / 8, 1)
        self.mouse(t, "mouseReleased", x1, y1)

    def tap(self, t: Tab, x: float, y: float) -> None:
        for kind, b in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
            self.mouse(t, kind, x, y, b)
            time.sleep(0.05)

    def save(self, t: Tab, note: str) -> dict:
        t.wait_for("!!document.querySelector('.bd-cmp:not([hidden]) textarea')")
        t.ev(f"(ta => {{ ta.value = {json.dumps(note)}; ta.dispatchEvent(new Event('input', {{bubbles: true}})); }})(document.querySelector('.bd-cmp textarea'))")
        t.ev("[...document.querySelectorAll('.bd-cmp .bp-btn.primary')].find(b => b.textContent === 'Save').click()")
        t.wait_for("document.querySelector('.bd-cmp').hidden")
        return t.wait_for(f"BP.annotations().find(a => a.note === {json.dumps(note)})")

    def settle(self, t: Tab) -> None:
        """Two animation frames: the board paints its view, then the marks their places."""
        t.ev("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(r)))).then(() => 1)")

    def ab(self, t: Tab, aid: str) -> dict:
        """A screen's frame in the window and on the board, and the board's scale on screen."""
        r = t.ev(RECT.format(json.dumps(f".bd-ab[data-ab={aid}]")))
        p = t.ev(f"(a => a && [a.x, a.y, a.w, a.h])(BP.board().artboards.find(a => a.id === {json.dumps(aid)}))")
        return {"r": r, "p": p, "s": r[2] / p[2]}

    def near(self, got, want, tol: float, msg=None) -> None:
        self.assertIsNotNone(got, msg)
        for g, w in zip(got, want):
            self.assertLessEqual(abs(g - w), tol, msg or (got, want))


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class BoardMarks(Marks, ChromePage):
    """Regions and pins on the Acme Fit board (phone screens, each in its frame)."""

    def board(self) -> Tab:
        t = self.open(self.server.url_for(self.docs / DESIGN))
        self.browser.call("Page.bringToFront", {}, t.session)
        t.wait_for("!!BP.board()", 20)
        t.ev("BP.sidebar({open: false}), 1")
        time.sleep(0.6)
        return t

    def patch(self, *args: str) -> None:
        r = self.tmp.run("build.py", "patch", self.docs / DESIGN, *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def expect(self, t: Tab, a: dict) -> list[float]:
        """Where a region shows: its box in the px of the screen holding most of it, else in board px (measured from a
        screen that stays put)."""
        on = a["where"]["on"]
        ref = self.ab(t, on[0]["artboard"] if on else "workout")
        o = ref["p"] if on else [0, 0]
        x, y, w, h = a["box"]
        return [ref["r"][0] + (x + o[0] - ref["p"][0]) * ref["s"], ref["r"][1] + (y + o[1] - ref["p"][1]) * ref["s"], w * ref["s"], h * ref["s"]]

    def test_regions_on_beside_and_across_screens_stay_where_they_were_made(self) -> None:
        t = self.board()
        t.ev("BP.board({focus: 'login'}), 1")
        self.settle(t)
        t.ev("BP.setMode('region')")
        L = self.ab(t, "login")
        lx, ly, s = L["r"][0], L["r"][1], L["s"]
        # over the screen's frame (an iframe): the board's, named by the screen, its box in the screen's px
        self.assertEqual(t.ev(UNDER.format(lx + 120, ly + 110)), "login")
        self.drag(t, lx + 40, ly + 60, lx + 200, ly + 160)
        over = self.save(t, "Acme: the brand block is cramped")
        self.assertEqual((over["target"]["key"], over["target"]["label"]), ("board:main", "Board › Sign in"))
        self.assertEqual([o["artboard"] for o in over["where"]["on"]], ["login"])
        self.near(over["box"], [40 / s, 60 / s, 160 / s, 100 / s], 1)
        self.assertEqual([x["key"] for x in over["targets"]], ["artboard:login"])
        self.near(t.wait_for(rgn(over["id"])), [lx + 40, ly + 60, 160, 100], 1.5)
        # beside the screens: board px
        x0, y0 = lx - 170, ly + 100
        self.assertFalse(t.ev(f"!!document.elementsFromPoint({x0 + 50}, {y0 + 40}).find(e => e.closest('.bd-ab'))"))
        self.drag(t, x0, y0, x0 + 100, y0 + 80)
        beside = self.save(t, "Acme: a hint for first-timers here")
        self.assertEqual((beside["target"]["key"], beside["where"]["on"]), ("board:main", []))
        self.near(beside["box"][:2], [(x0 - lx) / s + L["p"][0], (y0 - ly) / s + L["p"][1]], 1)
        # across two screens: both named, its box in the px of the one holding most of it
        t.ev("BP.board({fit: true}), 1")
        self.settle(t)
        L, LB = self.ab(t, "login"), self.ab(t, "login-b")
        self.drag(t, L["r"][0] + 4, L["r"][1] + L["r"][3] - 12, L["r"][0] + 44, LB["r"][1] + 30)
        across = self.save(t, "Acme: keep the two sign-ins alike")
        self.assertEqual(sorted(o["artboard"] for o in across["where"]["on"]), ["login", "login-b"])
        self.assertEqual(across["where"]["on"][0]["artboard"], "login-b", "the screen holding most of it")
        self.assertEqual({x["key"] for x in across["targets"]}, {"artboard:login", "artboard:login-b"})
        marks = [over, beside, across]

        def check(why: str) -> None:
            for a in marks:
                self.near(t.wait_for(rgn(a["id"])), self.expect(t, a), 1.5, (why, a["note"]))
        check("made")
        # a pan, then a zoom: the marks move and scale with the board, at once (the marks layer is the board's)
        b = t.ev("(r => [r.left, r.top, r.width, r.height])(document.querySelector('.bd-board').getBoundingClientRect())")
        self.browser.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": b[0] + 300, "y": b[1] + 300, "deltaX": 120, "deltaY": 160}, t.session)
        self.settle(t)
        check("panned")
        for _ in range(3):
            self.browser.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": b[0] + 300, "y": b[1] + 300, "deltaX": 0, "deltaY": -120, "modifiers": 2}, t.session)
        time.sleep(0.4)
        self.settle(t)
        check("zoomed")
        self.assertTrue(all(t.ev(f"!!document.querySelector('.bd-bmk .bd-ann-rgn[data-ann=\"{a['id']}\"]')") for a in marks))
        # the layout changes (login moves, a new screen in a row above) and the page loads again: the region on login
        # and the one across follow their screens, the one beside the screens stays at its board px
        was = self.ab(t, "login")["p"]
        self.patch("layout:main", "--json", '{"login": [-1200, 300]}')
        self.patch("frame:phone@-1200,-1200")
        t.go(t.ev("location.href"))
        t.wait_for("!!BP.board() && BP.board().requested !== undefined", 20)
        t.ev("BP.sidebar({open: false}), BP.board({fit: true}), 1")
        time.sleep(0.6)
        self.settle(t)
        self.assertNotEqual(self.ab(t, "login")["p"][:2], was[:2], "login didn't move")
        self.assertIn("frame-1", [a["id"] for a in t.ev("BP.board().artboards")])
        marks = [t.ev(f"BP.annotations().find(a => a.id === {json.dumps(a['id'])})") for a in marks]
        check("after the layout changed")
        # Full page and Viewport don't touch a phone's marks; Request changes says where each is
        md = t.ev("BP.changesPayload().markdown")
        self.assertIn("on `artboard:login` at x", md)
        self.assertIn("beside the screens", md)
        self.assertEqual(self.browser.errors, [])

    def hovered(self, t: Tab, aid: str, fx: float, fy: float) -> list[float]:
        """Element mode, the pointer over frame px (fx, fy) of a screen: the rect (frame px) its frame reports for the
        element there, as the board outlines it."""
        L = self.ab(t, aid)
        hov = f"(e => !e.hidden && [e.style.left, e.style.top, e.style.width, e.style.height].map(parseFloat))(document.querySelector('.bd-ab[data-ab={aid}] .bd-ab-hov'))"
        for i in range(20):   # the frame takes Element's mode a message later
            self.mouse(t, "mouseMoved", L["r"][0] + (fx + i % 2) * L["s"], L["r"][1] + fy * L["s"])
            time.sleep(0.15)
            if t.ev(hov):
                break
        return t.wait_for(hov)

    def test_a_pin_in_a_screen_keeps_its_elements_spot_and_pins_on_one_spot_fan_out(self) -> None:
        t = self.board()
        t.ev("BP.board({focus: 'login'}), 1")
        self.settle(t)
        t.wait_for("BP.board().artboards.find(a => a.id === 'login').ready", 15)
        t.ev("BP.setMode('point')")
        r = self.hovered(t, "login", 195, 415)   # "Use a passkey"
        self.assertTrue(r[2] > 100 and r[3] > 20, r)
        L = self.ab(t, "login")
        self.tap(t, L["r"][0] + (r[0] + r[2] / 2) * L["s"], L["r"][1] + (r[1] + r[3] / 2) * L["s"])
        a = self.save(t, "Acme: passkey first?")
        self.assertTrue(a["target"]["key"].startswith("el:login/"), a["target"])
        self.near([a["spot"]["x"], a["spot"]["y"]], [r[0] + r[2], r[1]], 4)   # the picked element's top right (the outline hugs the hovered one)
        pa = t.wait_for(PIN.replace("{}", a["id"]))
        self.assertTrue(pa["world"], "the pin is in the board's marks layer")
        self.near([pa["x"], pa["y"]], [L["r"][0] + a["spot"]["x"] * L["s"], L["r"][1] + a["spot"]["y"] * L["s"]], 1)
        # its bubble opens into the screen, away from its right edge
        self.assertIn(" fl", pa["cls"])
        # a second pin on the same element fans out beside the first, both numbers readable
        self.tap(t, L["r"][0] + (r[0] + r[2] / 2) * L["s"], L["r"][1] + (r[1] + r[3] / 2) * L["s"])
        b = self.save(t, "Acme: or a smaller key")
        self.settle(t)
        pa, pb = t.ev(PIN.replace("{}", a["id"])), t.ev(PIN.replace("{}", b["id"]))
        self.assertNotEqual(pa["n"], pb["n"])
        self.assertLessEqual(abs(pb["y"] - pa["y"]), 0.5)
        self.assertGreaterEqual(abs(pb["x"] - pa["x"]), 21.5, (pa, pb))
        self.assertLessEqual(abs(pb["x"] - pa["x"]), 22.5, (pa, pb))
        # the frame leaves the live set (the view is far from it): the pin stays on its spot, inside the screen
        t.ev("BP.board({focus: 'dashboard'}), 1")
        t.wait_for("!BP.board().artboards.find(a => a.id === 'login').live", 10)
        self.settle(t)
        p = t.ev("(a => [a.x, a.y, a.w, a.h])(BP.board().artboards.find(a => a.id === 'login'))")
        q = t.ev(PIN.replace("{}", a["id"]))
        self.near(q["at"], [p[0] + a["spot"]["x"], p[1] + a["spot"]["y"]], 0.01)
        self.assertNotIn("away", q["cls"])
        # again after a reload, the frame not live yet: the stored spot, never the screen's title or the board's corner.
        # The page sends its writes 300 ms after the last one: reload once the server holds both pins with their spots
        url = self.server.url_for(self.docs / DESIGN)
        self.assertTrue(until(lambda: all('"spot"' in self.state(url).get(f"__ann:{x['id']}", "") for x in (a, b)) and not t.ev(
            "Object.keys(localStorage).some(k => k.includes('__outbox') && localStorage.getItem(k) !== '{}')")), "the pins never reached the server")
        t.go(t.ev("location.href"))
        t.wait_for("!!BP.board()", 20)
        t.ev("BP.board({focus: 'dashboard'}), 1")
        t.wait_for("!BP.board().artboards.find(a => a.id === 'login').live", 10)   # the first fit may have mounted it: it leaves on the next relive
        self.settle(t)
        q = t.wait_for(PIN.replace("{}", a["id"]))
        self.near(q["at"], [p[0] + a["spot"]["x"], p[1] + a["spot"]["y"]], 0.01)
        self.assertTrue(p[0] <= q["at"][0] <= p[0] + p[2] and p[1] <= q["at"][1] <= p[1] + p[3], q)
        self.assertEqual(self.browser.errors, [])

    def seed(self, marks: list[dict]) -> str:
        """Comments stored by an earlier version, put in the reader state before the page loads."""
        url = self.server.url_for(self.docs / DESIGN)
        body = json.dumps({"path": url, "ops": [[f"__ann:{m['id']}", json.dumps(m)] for m in marks]}).encode()
        status, raw = self.server.req("PUT", "/__bluedoc/state", body, {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        return url

    def test_marks_from_before_board_px_are_migrated_and_none_floats(self) -> None:
        base = {"status": "open", "note": "", "rev": "3", "sentAt": "2026-11-01T10:00:00.000Z"}
        block = {"key": "block:screens/0", "label": "Board", "text": "Sign in · Today"}
        url = self.seed([
            # a Region and a pin on the board's block: fractions of the board's view, wherever it was panned
            {**base, "id": "cold1region", "type": "region", "note": "ref B", "target": block, "targets": [block], "up": [], "box": [0.4305, 0.478, 0.2571, 0.0185], "at": "2026-11-01T10:00:00.000Z"},
            {**base, "id": "cold2pin", "type": "pin", "note": "here", "target": block, "up": [], "pos": {"x": 0.5, "y": 0.5}, "at": "2026-11-01T10:01:00.000Z"},
            # a Region on the board's world (1.0.55: fractions of a 20 000 px square from -10 000) beside the screens
            {**base, "id": "cold3world", "type": "region", "note": "a card here", "target": {"key": "board", "label": "Board › Board", "text": ""},
             "targets": [{"key": "board", "label": "Board › Board", "text": ""}], "up": ["block:screens/0"], "box": [0.48, 0.5, 0.01, 0.005], "at": "2026-11-01T10:02:00.000Z"}])
        t = self.board()
        t.wait_for("BP.annotations().length === 3")
        got = {a["id"]: a for a in t.ev("BP.annotations()")}
        self.assertTrue(got["cold1region"]["lost"] and got["cold2pin"]["lost"])
        w = got["cold3world"]
        self.assertNotIn("lost", w)
        self.assertEqual(w["target"]["key"], "board:main")
        self.assertEqual(w["box"], [-400, 0, 200, 100])
        self.assertEqual(w["where"], {"board": {"x": -400, "y": 0, "w": 200, "h": 100}, "on": []})
        # the lost ones draw nothing on the board; the world one sits at its board px
        for aid in ("cold1region", "cold2pin"):
            self.assertTrue(t.ev(f"(p => !p || p.hidden)(document.querySelector('.bd-ann-pin[data-ann={aid}]'))"), aid)
        self.assertIsNone(t.ev(rgn("cold1region")))
        self.assertEqual(t.ev("document.querySelectorAll('.bd-ann-layer .bd-ann-pin:not([hidden])').length"), 0, "a mark on the page's layer over the board")
        t.ev("BP.board({focus: 'login'}), 1")
        self.settle(t)
        self.near(t.wait_for(rgn("cold3world")), self.expect(t, w), 1.5)
        # their cards: the lost ones say so, with no Show on the page; the readback too
        t.ev("BP.comments({open: true, filter: 'all'}), 1")
        lost = t.wait_for("[...document.querySelectorAll('.bd-cs-c')].filter(li => li.querySelector('.lost')).map(li => [li.dataset.id, li.querySelector('.lost').textContent, !!li.querySelector('[aria-label=\"Show on the page\"]')])")
        self.assertEqual(sorted(lost), [["cold1region", "Position lost; reply or re-pin", False], ["cold2pin", "Position lost; reply or re-pin", False]])
        # stored that way: the next load has nothing to migrate
        state = self.state(url)
        self.assertTrue(json.loads(state["__ann:cold1region"])["lost"])
        self.assertEqual(json.loads(state["__ann:cold3world"])["target"]["key"], "board:main")
        self.assertEqual(self.browser.errors, [])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class LivePageMarks(Marks, SiteInChrome):
    """A website board of live pages: the stub's tall page (3035 px in Full page, #hero-title at 100, 145 and #deep at
    200, 2535) and a second page far to the right, so focusing it takes the first out of the live set."""
    PATH = "/tall"
    TALL = 45 + 900 + 90 + 2000

    def site(self, url: str) -> dict:
        doc = site_doc(url)
        board_of(doc)["artboards"].append({"id": "far", "title": "Far", "device": "page", "fidelity": "hifi", "url": url.replace("/tall", "/about"), "x": 40000, "y": 0})
        return doc

    def setUp(self) -> None:
        super().setUp()
        self.tab.wait_for(f"BP.board().artboards[0].h === {self.TALL}", 15)
        self.tab.ev("BP.sidebar && BP.sidebar({open: false}), BP.board({focus: 'home'}), 1")
        time.sleep(0.5)
        self.settle(self.tab)

    def frame_ctx(self) -> int:
        tree = self.browser.call("Page.getFrameTree", session=self.tab.session)["frameTree"]
        fid = next(f["frame"]["id"] for f in tree.get("childFrames", []) if f["frame"]["url"].endswith("/tall"))
        return self.browser.call("Page.createIsolatedWorld", {"frameId": fid, "worldName": "marks-test"}, self.tab.session)["executionContextId"]

    def scroll_frame(self, y: int) -> None:
        self.browser.call("Runtime.evaluate", {"expression": f"scrollTo(0, {y}), 1", "contextId": self.frame_ctx(), "returnByValue": True}, self.tab.session)

    def home_frame(self) -> list[float]:
        return self.tab.ev(RECT.format(json.dumps(".bd-ab[data-ab=home] iframe.bd-ab-fr")))

    def test_a_pin_on_a_live_page_keeps_its_spot_in_full_page_viewport_and_off_the_live_set(self) -> None:
        t = self.tab
        a = self.pin_at(350, 2555, "Say when it renews")   # #deep: 300 × 40 at 200, 2535
        self.assertEqual(a["target"]["key"], "el:home/#deep")
        self.assertEqual(a["spot"], {"x": 500, "y": 2535})
        q = t.wait_for(PIN.replace("{}", a["id"]))
        self.assertTrue(q["world"])
        self.near([q["x"], q["y"]], self.on_frame(500, 2535), 2)
        # Viewport: the frame shows 900 px from the top; the pin stays on its page, at the frame's bottom edge, away
        t.ev("BP.board({pageView: 'viewport'}), 1")
        t.wait_for("(a => a.h === 900 && a.ready && a.page.frame[1] === 900)(BP.board().artboards[0])", 15)
        t.ev("BP.board({focus: 'home'}), 1")
        self.settle(t)
        f = self.home_frame()
        q = t.wait_for(f"(q => q && q.cls.includes('away') && q)({PIN.replace('{}', a['id'])})")
        self.assertTrue(f[1] <= q["y"] <= f[1] + f[3] + 0.5 and f[0] <= q["x"] <= f[0] + f[2], (q, f))
        # the frame scrolls #deep into view: the pin sits on it again
        self.scroll_frame(2000)
        t.wait_for(f"(q => q && !q.cls.includes('away'))({PIN.replace('{}', a['id'])})")
        self.near([t.ev(PIN.replace("{}", a["id"]))[k] for k in ("x", "y")], self.on_frame(500, 535), 2)
        # Full page again, then the page leaves the live set: its stored spot, in board px
        t.ev("BP.board({pageView: 'full'}), 1")
        t.wait_for(f"BP.board().artboards[0].h === {self.TALL}", 15)
        t.ev("BP.board({focus: 'far'}), 1")
        t.wait_for("!BP.board().artboards[0].live", 10)
        self.settle(t)
        p = t.ev("(a => [a.x, a.y])(BP.board().artboards[0])")
        q = t.ev(PIN.replace("{}", a["id"]))
        self.near(q["at"], [p[0] + 500, p[1] + 2535], 0.01)
        self.assertNotIn("away", q["cls"])
        self.assertEqual(self.browser.errors, [])

    def test_a_region_over_a_live_page_is_the_boards_and_viewport_cuts_it(self) -> None:
        t = self.tab
        t.ev("BP.setMode('region')")
        (x0, y0), (x1, y1) = self.on_frame(100, 145), self.on_frame(700, 225)   # #hero-title's box
        self.assertEqual(t.ev(UNDER.format((x0 + x1) / 2, (y0 + y1) / 2)), "home")
        self.drag(t, x0, y0, x1, y1)
        a = self.save(t, "Shorter headline")
        self.assertEqual((a["target"]["key"], [o["artboard"] for o in a["where"]["on"]]), ("board:site", ["home"]))
        k = (x1 - x0) / 600
        self.near(a["box"], [100, 145, 600, 80], 1 / k + 0.5)
        self.near(t.wait_for(rgn(a["id"])), [x0, y0, x1 - x0, y1 - y0], 1.5)
        # Viewport at the top: the same spot; the frame scrolls 100 px: it moves with the page; scrolled past: cut away
        t.ev("BP.board({pageView: 'viewport'}), 1")
        t.wait_for("(a => a.h === 900 && a.ready)(BP.board().artboards[0])", 15)
        t.ev("BP.board({focus: 'home'}), 1")
        self.settle(t)
        (x0, y0), (x1, y1) = self.on_frame(a["box"][0], a["box"][1]), self.on_frame(a["box"][0] + a["box"][2], a["box"][1] + a["box"][3])
        self.near(t.wait_for(rgn(a["id"])), [x0, y0, x1 - x0, y1 - y0], 1.5)
        self.scroll_frame(100)
        t.wait_for(f"(r => r && Math.abs(r[1] - {y0 - 100 * (y1 - y0) / 80}) <= 1.5)({rgn(a['id'])})")
        self.scroll_frame(2000)
        t.wait_for(f"!{rgn(a['id'])}")
        self.assertEqual(t.ev("document.querySelectorAll('.bd-ann-rgn:not([style*=\"display: none\"])').length"), 0)
        # Full page: back on the headline
        t.ev("BP.board({pageView: 'full'}), 1")
        t.wait_for(f"BP.board().artboards[0].h === {self.TALL}", 15)
        t.ev("BP.board({focus: 'home'}), 1")
        self.settle(t)
        (x0, y0), (x1, y1) = self.on_frame(a["box"][0], a["box"][1]), self.on_frame(a["box"][0] + a["box"][2], a["box"][1] + a["box"][3])
        self.near(t.wait_for(rgn(a["id"])), [x0, y0, x1 - x0, y1 - y0], 1.5)
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
