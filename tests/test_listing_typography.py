"""A storelisting's Typography (the Text tab's caption font, as Figma's Typography panel): the caption's family, style,
size, line height, letter spacing and alignment are listing.brand.font, checked by listing.caption_font_problems
(build.py) and serve.py value_ok against store-rules.json brand.font, and drawn by the shot kit as the --bd-*-caption
tokens. The browser tests (BLUEDOC_BROWSER_TESTS=1): the family popover filters and takes ↑ ↓ Enter Esc; the style
list holds only the family's real faces; each control restyles the shot frames live; a change is a brand draft whose
`build.py patch … brand:main` command records it; undo reverts it, one step per change."""
from __future__ import annotations

import json
import shlex
import unittest

from _support import Server, TempHome, load_json
from test_listing_brand import sfnt, ttc
from test_page_state import CHROME, ChromePage

import listing
import serve

STEM = "acme-fit-listing"
LST = "BP.listing()"
TY = "document.querySelector('#bd-lp-text .bd-typo')"
POP = TY + ".querySelector('.bd-ty-pop[data-menu=\"{}\"]')"
KEYS = {"ArrowDown": 40, "ArrowUp": 38, "Enter": 13, "Escape": 27}


def brand_draft(**font) -> str:
    f = {"family": "Acme Sans", "weight": 700, "source": "system", **font}
    return json.dumps({"id": "c1", "type": "listing", "status": "pending", "note": "", "target": {"key": "brand:main", "label": "Brand"},
                       "listing": {"op": "brand", "font": {k: v for k, v in f.items() if v is not None}, "palette": {"bg": "#1d4ed8"}, "image": None, "swatches": []}})


class CaptionFont(unittest.TestCase):
    """The caption font's typography: the build's check, its tokens, and the server keeping a brand draft only in bounds."""

    def setUp(self) -> None:
        self.rules = listing.load_rules()

    def test_the_build_checks_the_typography_against_the_rules(self) -> None:
        ok = {"family": "Acme Sans", "weight": 700, "italic": True, "size": 1.2, "lineHeight": 1.1, "letterSpacing": -20, "align": "left", "valign": "bottom"}
        self.assertEqual(listing.caption_font_problems(ok, self.rules), [])
        self.assertEqual(listing.caption_font_problems(None, self.rules), [])
        for bad, key in (({"size": 1.7}, "size"), ({"size": "1"}, "size"), ({"lineHeight": 0.5}, "lineHeight"), ({"letterSpacing": 51}, "letterSpacing"),
                         ({"letterSpacing": -21}, "letterSpacing"), ({"align": "justify"}, "align"), ({"valign": "left"}, "valign"),
                         ({"weight": 750}, "weight"), ({"italic": "yes"}, "italic"), ({"tracking": 2}, "tracking"), ({"size": True}, "size")):
            self.assertEqual([k for k, _ in listing.caption_font_problems({**ok, **bad}, self.rules)], [key], bad)
        self.assertEqual([k for k, _ in listing.caption_font_problems({"family": "a;b"}, self.rules)], [""])

    def test_the_tokens_are_a_scale_unitless_line_height_and_em_tracking(self) -> None:
        tok = listing.caption_tokens({"family": "Acme Sans", "weight": 700, "italic": True, "size": 1.25, "lineHeight": 1.1, "letterSpacing": 5,
                                      "align": "right", "valign": "middle"}, self.rules)
        self.assertEqual(tok, {"--bd-font-caption": '"Acme Sans", Inter, system-ui, sans-serif', "--bd-weight-caption": "700", "--bd-style-caption": "italic",
                               "--bd-size-caption": "1.25", "--bd-leading-caption": "1.1", "--bd-tracking-caption": "0.05em",
                               "--bd-align-caption": "right", "--bd-valign-caption": "middle"})
        self.assertEqual(listing.caption_tokens({"family": "Acme Sans", "size": 9}, self.rules), {}, "an invalid font sets none")
        # each layout draws the top, and only places the rules name
        for s in self.rules["styles"]:
            if s["axis"] == "layout":
                self.assertIn("top", s["valign"], s["id"])

    def test_the_server_keeps_a_brand_draft_only_in_bounds(self) -> None:
        self.assertTrue(serve.value_ok("__ann:c1", brand_draft()))
        self.assertTrue(serve.value_ok("__ann:c1", brand_draft(size=1.2, lineHeight=1.3, letterSpacing=-20, align="right", valign="bottom", italic=True)))
        self.assertTrue(serve.value_ok("__ann:c1", json.dumps({**json.loads(brand_draft()), "listing": {"op": "brand", "font": None}})), "the default font")
        for bad in ({"size": 2}, {"size": 0.4}, {"lineHeight": 3}, {"letterSpacing": 50.5}, {"letterSpacing": -30}, {"align": "justify"},
                    {"valign": "center"}, {"weight": 450}, {"italic": 1}, {"family": "x}"}, {"kerning": 1}):
            self.assertFalse(serve.value_ok("__ann:c1", brand_draft(**bad)), bad)
        self.assertFalse(serve.value_ok("__ann:c1", json.dumps({**json.loads(brand_draft()), "listing": {"op": "brand", "font": None, "palette": {"bg": "blue"}}})))

    def test_the_server_refuses_an_out_of_bounds_draft_over_http(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        docs = tmp.copy_examples()
        self.assertEqual(tmp.run("serve.py", "add", docs).returncode, 0)
        server = Server(tmp)
        server.start()
        self.addCleanup(server.stop)
        url = server.url_for(docs / f"{STEM}.bluedoc.json")
        good, bad = brand_draft(size=1.2), brand_draft(letterSpacing=80)
        body = json.dumps({"path": url, "ops": [["__ann:c1", good], ["__ann:c2", bad.replace('"c1"', '"c2"')]]}).encode()
        status, raw = server.req("PUT", "/__bluedoc/state", body, {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw).get("dropped"), ["__ann:c2"])

    def test_a_valign_the_layout_does_not_draw_warns(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        doc = tmp.copy_examples() / f"{STEM}.bluedoc.json"
        d = load_json(doc)
        lb = listing.listing_of(d)
        lb["brand"]["font"] = {"family": "Inter", "weight": 800, "valign": "middle"}
        doc.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        r = tmp.run("build.py", doc, "--check", "--no-history")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("L1 on play puts the caption at the top, not middle", r.stdout + r.stderr)
        lb["brand"]["font"]["size"] = 3
        doc.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        r = tmp.run("build.py", doc, "--check", "--no-history")
        self.assertEqual(r.returncode, 1)
        self.assertIn("brand.font.size", r.stdout + r.stderr)


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class TypographyPanel(ChromePage):
    def setUp(self) -> None:
        super().setUp()
        fdir = self.tmp.dir / "fonts"
        fdir.mkdir()
        (fdir / "AcmeSans.ttc").write_bytes(ttc(("Acme Sans", "Regular", 400, 0), ("Acme Sans", "Bold", 700, 0), ("Acme Sans", "Bold Italic", 700, 0, True)))
        (fdir / "AcmeSerif-Black.ttf").write_bytes(sfnt("Acme Serif", "Black", 900, 0))
        self.server.stop()
        self.tmp.env.update(BLUEDOC_FONT_DIRS=str(fdir))
        self.server.start()
        self.base = f"http://{self.server.host}"
        self.doc_path = self.docs / f"{STEM}.bluedoc.json"
        self.url = self.server.url_for(self.doc_path)

    def page(self):
        t = self.open(self.url)
        t.wait_for("!!document.querySelector('.bd-lst-sec') && !!BP.listing()")
        t.ev("document.documentElement.classList.contains('bd-lp-open') || document.dispatchEvent(new KeyboardEvent('keydown', {key: '['}))")
        t.ev("document.querySelector('.bd-lp-tabs [data-v=\"text\"]').click()")
        t.wait_for("!document.getElementById('bd-lp-text').hidden && document.documentElement.classList.contains('bd-lp-open')")
        t.ev(f"{TY}.scrollIntoView({{block: 'center'}})")
        return t

    def key(self, t, k: str) -> None:
        for kind in ("keyDown", "keyUp"):
            t.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": k, "code": k, "windowsVirtualKeyCode": KEYS[k],
                                                      **({"text": "\r"} if k == "Enter" and kind == "keyDown" else {})}, t.session)

    def shown(self, t, menu: str) -> list[str]:
        return t.ev(f"[...{POP.format(menu)}.querySelectorAll('.o')].map(o => o.querySelector('.l').textContent)")

    def frame(self, t, expr: str):
        """expr in the first play/phone shot's frame (sandboxed, so out of process: its own DevTools target); None while
        it loads."""
        t.browser.call("DOM.enable", {}, t.session)
        doc = t.browser.call("DOM.getDocument", {"depth": 0}, t.session)["root"]["nodeId"]
        node = t.browser.call("DOM.querySelector", {"nodeId": doc, "selector": ".bd-lst-shot[data-set=\"play/phone\"] iframe"}, t.session)["nodeId"]
        fid = t.browser.call("DOM.describeNode", {"nodeId": node}, t.session)["node"]["frameId"]
        sessions = self.__dict__.setdefault("frame_sessions", {})
        if fid not in sessions:
            t.browser.call("Target.getTargets")   # the browser learns the frame's target
            try:
                sessions[fid] = t.browser.call("Target.attachToTarget", {"targetId": fid, "flatten": True})["sessionId"]
            except RuntimeError:
                return None
        r = t.browser.call("Runtime.evaluate", {"expression": expr, "returnByValue": True}, sessions[fid])
        if "exceptionDetails" in r:
            return None
        return r["result"].get("value")

    def cap(self, t) -> dict:
        """The first play/phone shot's caption as drawn; its tile in view first (the page loads frames in view only)."""
        self.ready(t)
        for _ in range(100):
            c = self.frame(t, "(c => { if (!c || document.documentElement.classList.contains('shot-pending')) return null;"
                              " const s = getComputedStyle(c), r = c.getBoundingClientRect(), f = document.querySelector('.shot-frame').getBoundingClientRect();"
                              " return {size: parseFloat(s.fontSize), lh: parseFloat(s.lineHeight), ls: parseFloat(s.letterSpacing) || 0, align: s.textAlign,"
                              " style: s.fontStyle, weight: s.fontWeight, family: s.fontFamily, below: r.top >= f.bottom - 1, cls: document.documentElement.className}; })"
                              "(document.querySelector('.shot-cap'))")
            if c:
                return c
            t.ev("new Promise(r => setTimeout(r, 100))")
        self.fail("the shot's frame never loaded")

    def ready(self, t) -> None:
        t.ev("document.querySelector('.bd-lst-shot[data-set=\"play/phone\"]').scrollIntoView({block: 'center'})")
        t.wait_for("BP.listing().tiles.some(x => x.set === 'play/phone' && x.ready)", 20)

    def until_cap(self, t, test, what: str) -> dict:
        for _ in range(50):
            c = self.cap(t)
            if test(c):
                return c
            t.ev("new Promise(r => setTimeout(r, 100))")
        self.fail(f"the shot never showed {what}: {self.cap(t)}")

    def type_in(self, t, key: str, text: str, commit: bool = True) -> None:
        inp = f"{TY}.querySelector('.bd-ty-num[data-key={key}] .n')"
        t.ev(f"(i => {{ i.focus(); i.select(); }})({inp})")
        t.browser.call("Input.insertText", {"text": text}, t.session)
        if commit:
            self.key(t, "Enter")

    def test_the_family_popover_filters_and_the_keys_pick_a_family(self) -> None:
        t = self.page()
        fam = f"{TY}.querySelector('.bd-ty-dd.fam')"
        self.assertFalse(t.ev(f"{POP.format('family')}.matches(':popover-open')"), "closed until asked")
        t.ev(f"{fam}.focus()")
        self.key(t, "ArrowDown")
        t.wait_for(f"{POP.format('family')}.matches(':popover-open') && BP.listing().brand.fonts === 2")
        self.assertTrue(t.ev(f"document.activeElement === {POP.format('family')}.querySelector('.q')"), "the search has the focus")
        self.assertEqual(self.shown(t, "family"), ["Inter", "Acme Sans", "Acme Serif"])
        self.assertEqual(t.ev(f"[...{POP.format('family')}.querySelectorAll('.o .m')].map(m => m.textContent)"), ["Default", "3 styles", "1 style"])
        self.assertEqual(t.ev(f"{POP.format('family')}.querySelector('.o[data-v=\"Acme Serif\"] .l').style.fontFamily"), '"Acme Serif", system-ui', "each in its face")
        t.browser.call("Input.insertText", {"text": "acme"}, t.session)
        t.wait_for(f"{POP.format('family')}.querySelectorAll('.o').length === 2")
        self.assertEqual(self.shown(t, "family"), ["Acme Sans", "Acme Serif"])
        self.key(t, "ArrowDown")
        self.assertEqual(t.ev(f"{POP.format('family')}.querySelector('.o.act .l').textContent"), "Acme Serif")
        self.key(t, "Enter")
        t.wait_for("BP.listing().brand.font && BP.listing().brand.font.family === 'Acme Serif'")
        self.assertFalse(t.ev(f"{POP.format('family')}.matches(':popover-open')"))
        self.assertTrue(t.ev(f"document.activeElement === {fam}"), "the focus is back on the button")
        self.assertEqual(t.ev(f"{fam}.querySelector('.v').textContent"), "Acme Serif")
        self.assertEqual(t.ev(LST)["brand"]["font"]["weight"], 900, "its one style")
        # a letter on the closed button opens the search with it; Esc closes and keeps the pick
        t.browser.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "z", "code": "KeyZ", "text": "z", "windowsVirtualKeyCode": 90}, t.session)
        t.wait_for(f"{POP.format('family')}.matches(':popover-open') && {POP.format('family')}.querySelector('.q').value === 'z'")
        self.assertIn("No installed font matches", t.ev(f"{POP.format('family')}.textContent"))
        self.key(t, "Escape")
        t.wait_for(f"!{POP.format('family')}.matches(':popover-open')")
        self.assertEqual(t.ev(LST)["brand"]["font"]["family"], "Acme Serif")

    def test_the_style_list_holds_only_the_familys_faces(self) -> None:
        t = self.page()
        sty = f"{TY}.querySelector('.bd-ty-dd.sty')"
        t.ev(f"{sty}.click()")
        t.wait_for(f"{POP.format('style')}.matches(':popover-open')")
        self.assertEqual(self.shown(t, "style"), ["Thin", "ExtraLight", "Light", "Regular", "Medium", "SemiBold", "Bold", "ExtraBold", "Black"], "the vendored Inter's weights")
        self.assertEqual(t.ev(f"{POP.format('style')}.querySelector('.o[aria-selected=true] .l').textContent"), "ExtraBold")
        self.key(t, "Escape")
        t.ev(f"{TY}.querySelector('.bd-ty-dd.fam').click()")
        t.wait_for(f"!!{POP.format('family')}.querySelector('.o[data-v=\"Acme Sans\"]')")
        t.ev(f"{POP.format('family')}.querySelector('.o[data-v=\"Acme Sans\"]').click()")
        t.wait_for("BP.listing().brand.font.family === 'Acme Sans'")
        self.assertEqual(t.ev(f"{sty}.querySelector('.v').textContent"), "Bold", "the nearest face to ExtraBold")
        self.ready(t)
        t.ev(f"{sty}.click()")
        t.wait_for(f"{POP.format('style')}.matches(':popover-open')")
        self.assertEqual(self.shown(t, "style"), ["Regular", "Bold", "Bold Italic"])
        t.ev(f"{POP.format('style')}.querySelector('.o[data-v=\"700i\"]').click()")
        t.wait_for("BP.listing().brand.font.italic === true && BP.listing().brand.font.weight === 700")
        c = self.until_cap(t, lambda c: c["style"] == "italic", "italic")
        self.assertEqual(c["weight"], "700")
        self.assertTrue(c["family"].startswith('"Acme Sans"'), c["family"])

    def test_size_line_height_letter_spacing_and_alignment_restyle_the_shot_live(self) -> None:
        t = self.page()
        c0 = self.cap(t)
        self.assertEqual((c0["align"], c0["style"], round(c0["lh"] / c0["size"], 2), round(c0["ls"] / c0["size"], 3)), ("center", "normal", 1.06, -0.02), "today's look")
        self.type_in(t, "size", "120", commit=False)   # typing shows at once
        c = self.until_cap(t, lambda c: abs(c["size"] - c0["size"] * 1.2) < 0.6, "size 120%")
        self.key(t, "Enter")
        self.type_in(t, "lineHeight", "1.3")
        c = self.until_cap(t, lambda c: abs(c["lh"] - c["size"] * 1.3) < 0.6, "line height 1.3")
        self.type_in(t, "letterSpacing", "5")
        c = self.until_cap(t, lambda c: abs(c["ls"] - c["size"] * 0.05) < 0.3, "letter spacing 5%")
        t.ev(f"{TY}.querySelector('.seg [data-v=left]').click()")
        self.until_cap(t, lambda c: c["align"] == "left", "left alignment")
        # L1 draws the caption at the top or bottom: middle is off and says why; bottom puts it under the UI
        mid = f"{TY}.querySelector('.seg [data-v=middle]')"
        self.assertEqual(t.ev(f"{mid}.getAttribute('aria-disabled')"), "true")
        self.assertIn("draws the caption at the top or bottom", t.ev(f"{mid}.title"))
        t.ev(f"{mid}.click()")
        self.assertNotIn("valign", t.ev(LST)["brand"]["font"])
        t.ev(f"{TY}.querySelector('.seg [data-v=bottom]').click()")
        c = self.until_cap(t, lambda c: "cap--bottom" in c["cls"] and c["below"], "the caption under the UI")
        f = t.ev(LST)["brand"]["font"]
        self.assertEqual({k: f.get(k) for k in ("size", "lineHeight", "letterSpacing", "align", "valign")},
                         {"size": 1.2, "lineHeight": 1.3, "letterSpacing": 5, "align": "left", "valign": "bottom"})
        # out of bounds: typing doesn't take it, Enter clamps it
        self.type_in(t, "size", "500")
        t.wait_for("BP.listing().brand.font.size === 1.6")

    def test_a_change_is_a_brand_draft_whose_patch_command_records_it(self) -> None:
        t = self.page()
        t.ev(f"{TY}.querySelector('.bd-ty-num[data-key=size] .dd').click()")
        t.wait_for(f"{POP.format('size')}.matches(':popover-open')")
        t.ev(f"{POP.format('size')}.querySelector('.o[data-v=\"120\"]').click()")
        t.ev(f"{TY}.querySelector('.seg [data-v=right]').click()")
        t.wait_for("!!BP.listing().brand.draft && BP.listing().brand.font.align === 'right' && BP.listing().brand.font.size === 1.2")
        self.assertTrue(t.ev(LST)["approveBlocks"], "Approve waits for it")
        self.send_changes(t, "1")
        out = self.reply(self.doc_path)
        self.assertIn("## Brand drafts", out)
        self.assertIn("size 120%, align right", out)
        cmd = next(l for l in out.splitlines() if l.startswith("build.py patch") and "brand:main" in l)
        r = self.tmp.run("build.py", "patch", self.doc_path, *shlex.split(cmd)[3:])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        font = listing.listing_of(load_json(self.doc_path))["brand"]["font"]
        self.assertEqual((font["family"], font["size"], font["align"]), ("Inter", 1.2, "right"))
        t2 = self.page()
        self.assertFalse(t2.ev(LST)["brand"]["draft"], "recorded: no draft")
        self.assertEqual(t2.ev(f"{TY}.querySelector('.bd-ty-num[data-key=size] .n').value"), "120")
        self.assertEqual(t2.ev(f"{TY}.querySelector('.seg [data-v=right]').getAttribute('aria-pressed')"), "true")
        c = self.cap(t2)
        self.assertEqual(c["align"], "right", "the shot draws the recorded tokens")

    def test_undo_reverts_one_change_at_a_time(self) -> None:
        t = self.page()
        c0 = self.cap(t)
        self.type_in(t, "size", "130")
        t.wait_for("BP.listing().brand.font.size === 1.3 && !!BP.listing().brand.draft")
        t.ev(f"{TY}.querySelector('.seg [data-v=left]').click()")
        t.wait_for("BP.listing().brand.font.align === 'left'")
        self.assertEqual(t.ev(LST)["toolbar"]["undo"], "Caption align · left")
        t.ev("BP.listing({undo: true})")
        t.wait_for("!BP.listing().brand.font.align && BP.listing().brand.font.size === 1.3")
        self.assertEqual(t.ev(f"{TY}.querySelector('.seg [data-v=center]').getAttribute('aria-pressed')"), "true", "the panel repaints")
        self.until_cap(t, lambda c: c["align"] == "center", "centre again")
        t.ev("BP.listing({undo: true})")
        t.wait_for("!BP.listing().brand.draft && !(BP.listing().brand.font || {}).size")
        self.assertEqual(t.ev(f"{TY}.querySelector('.bd-ty-num[data-key=size] .n').value"), "100")
        self.until_cap(t, lambda c: abs(c["size"] - c0["size"]) < 0.3, "the size it had")
        t.ev("BP.listing({redo: true})")
        t.wait_for("BP.listing().brand.font.size === 1.3")


if __name__ == "__main__":
    unittest.main()
