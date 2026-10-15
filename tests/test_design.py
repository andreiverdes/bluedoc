"""Design and presentation docs: the Acme Fit example, the board contract, screen-file lint, screen HTML in the
history, links, the flow layout, app icons, `new presentation`, and the screen route's framework fallback.

The example builds clean and its history holds its three revisions with one HTML entry per screen version. The contract
wants exactly one board with an artboard; the board's ids, devices, fidelity, variants, themes and frameworks are
checked. Each banned construct in a screen file is one ERROR. An edit to a screen file under the same rev is an edit
in place that changes the approval hash, and the old rev's HTML stays readable. Each link lint row (data-nav targets,
kinds, names, labels, entry, layout, reach) fires on a scratch board; `layout: "flow"` puts reached screens in depth
columns; each icon layer lint row fires, and layers join the revision and the approval hash. Every revision records
its links and the page gets them, with board-geo.js inlined only into design pages. `new design --target mobile
--icons` builds clean once filled in, and `new design --target presentation` is refused with a pointer to `new
presentation`. `new presentation` writes a three-slide deck in one column that builds clean once filled in; speaker
notes over 2 KB are an ERROR, and so is a phone artboard in a presentation, while a design may hold a slide. The bundled
deck, acme-fit-deck, is a presentation that builds clean: five hi-fi plain-kit slides in one column with notes, one
revision; `--deck` and GET /__bluedoc/deck make it one HTML file that plays offline (in headless Chrome over file://
with BLUEDOC_BROWSER_TESTS=1), and refuse other doc types. The server serves only screens and declared framework files,
and wraps a screen whose framework is missing in the plain kit with a notice."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from _support import EXAMPLES, Server, TempHome, load_json
from test_page_state import CHROME, Browser, Tab, until

import build

STEM = "acme-fit-design"
DOC = EXAMPLES / f"{STEM}.bluedoc.json"
SCREENS = EXAMPLES / f"{STEM}.design"


def errors(out: str) -> list[str]:
    return [l for l in out.splitlines() if l.startswith("ERROR")]


def warnings(out: str) -> list[str]:
    return [l for l in out.splitlines() if l.startswith("WARN")]


def board_of(doc: dict) -> dict:
    return next(b for b in build.all_blocks(doc) if b.get("type") == "board")


class DesignCase(unittest.TestCase):
    """A temp copy of the examples; check() validates the design example (or a changed copy of it) without history."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.doc_path = self.docs / f"{STEM}.bluedoc.json"
        self.screens = self.docs / f"{STEM}.design"
        self.doc = load_json(self.doc_path)

    def write_doc(self, doc: dict) -> None:
        self.doc_path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    def check(self, doc: dict | None = None):
        if doc is not None:
            self.write_doc(doc)
        return self.tmp.run("build.py", self.doc_path, "--check")


class Example(unittest.TestCase):
    def test_the_example_builds_clean(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        docs = tmp.copy_examples()
        r = tmp.run("build.py", docs / f"{STEM}.bluedoc.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 error(s), 0 warning(s)", r.stderr)

    def test_example_shape(self) -> None:
        doc = load_json(DOC)
        self.assertEqual(doc["meta"]["type"], "design")
        board = board_of(doc)
        ids = [a["id"] for a in board["artboards"]]
        self.assertEqual(ids, ["watch-face", "login", "login-b", "today", "activity", "workouts", "workout", "profile",
                               "settings", "app-icon", "dashboard"])
        devices = {a["id"]: a["device"] for a in board["artboards"]}
        self.assertEqual(devices["watch-face"], "watch-round")
        self.assertEqual(devices["dashboard"], "browser")
        self.assertEqual(devices["app-icon"], "icons")
        self.assertEqual(board["entry"], ["login"])
        self.assertEqual([a["id"] for a in board["artboards"] if a.get("variantOf")], ["login-b"])
        # the example runs on what ships with bluedoc: the plain kit and HorizonUI, no reader framework
        used = {a.get("framework", board.get("framework", "plain")) for a in board["artboards"]}
        self.assertEqual(used, {"plain", "horizon"})
        self.assertFalse(board.get("frameworks"), "the example must need nothing the reader provides")
        for a in ids:
            if devices[a] == "icons":
                for layer in ("fg.svg", "mono.svg"):
                    self.assertTrue((SCREENS / a / layer).is_file(), f"no {layer} for {a}")
            else:
                self.assertTrue((SCREENS / f"{a}.html").is_file(), f"no screen file for {a}")

    def test_the_history_holds_three_revs_and_one_html_entry_per_screen_version(self) -> None:
        h = load_json(EXAMPLES / f"{STEM}.bluedoc.history.json")
        self.assertEqual([r["rev"] for r in h["revs"]], ["A", "B", "C"])
        screens = [r["screens"] for r in h["revs"]]
        versions = {v for s in screens for v in s.values()}
        self.assertEqual(set(h["html"]), versions, "the html pool holds exactly the screen versions the revs name")
        a, b, c = screens
        self.assertEqual(sorted(a), ["dashboard", "login", "watch-face"], "rev A: three wireframes")
        self.assertEqual(sorted(b), ["dashboard", "login", "login-b", "watch-face"], "rev B adds the passkey-first variant")
        self.assertEqual(set(c) - set(b), {"today", "activity", "workouts", "workout", "profile", "settings",
                                           "app-icon/fg.svg", "app-icon/mono.svg"}, "rev C: the phone flow and the icon")
        self.assertTrue(all(a[k] != b[k] for k in a), "every rev A wireframe was redrawn hi-fi in rev B")
        self.assertIn("wf-box", h["html"][a["login"]], "rev A's sign-in is a wireframe")
        # the current rev's hashes are the files on disk, its links the files' links
        self.assertEqual(c, build.screen_hashes(load_json(DOC), DOC))
        self.assertEqual(h["revs"][2]["links"], build.board_links(load_json(DOC), DOC))
        self.assertFalse(h["revs"][0].get("links") or h["revs"][1].get("links"), "revs A and B had no links")


class Contract(DesignCase):
    def assert_error(self, doc: dict, *needles: str) -> None:
        r = self.check(doc)
        self.assertEqual(r.returncode, 1, r.stderr)
        errs = "\n".join(errors(r.stderr))
        for n in needles:
            self.assertIn(n, errs)

    def test_the_example_checks_clean(self) -> None:
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(errors(r.stderr) + warnings(r.stderr), [])

    def test_a_design_needs_exactly_one_board_with_an_artboard(self) -> None:
        none = copy.deepcopy(self.doc)
        none["sections"] = [s for s in none["sections"] if s["id"] != "screens"]
        self.assertTrue(any("board" in e for e in build.check_contract(none)), "no board must break the contract")
        two = copy.deepcopy(self.doc)
        extra = copy.deepcopy(board_of(two))
        extra["id"] = "second"
        two["sections"][-1]["blocks"].append(extra)
        self.assertTrue(any("board" in e for e in build.check_contract(two)), "two boards must break the contract")
        empty = copy.deepcopy(self.doc)
        board_of(empty)["artboards"] = []
        self.assertTrue(build.check_contract(empty) or errors(self.check(empty).stderr), "an empty board must fail")

    def test_kind_design_alone_stays_docs(self) -> None:
        self.assertEqual(build.doc_type({"kind": "Design"}), "docs")
        self.assertEqual(build.doc_type({"kind": "Design", "type": "design"}), "design")

    def test_board_fields_are_checked(self) -> None:
        cases = {
            "duplicate id": lambda b: b["artboards"].append({**b["artboards"][0]}),
            "unknown device": lambda b: b["artboards"][0].update(device="toaster"),
            "fidelity": lambda b: b["artboards"][0].update(fidelity="glossy"),
            "variantOf": lambda b: b["artboards"][2].update(variantOf="nowhere"),
            "framework": lambda b: b["artboards"][3].update(framework="bootstrap"),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                d = copy.deepcopy(self.doc)
                change(board_of(d))
                r = self.check(d)
                self.assertEqual(r.returncode, 1, f"{name}: {r.stderr}")

    def test_a_board_without_a_device_takes_w_and_h(self) -> None:
        d = copy.deepcopy(self.doc)
        a = board_of(d)["artboards"][1]
        del a["device"]
        a.update(w=375, h=812)
        r = self.check(d)
        self.assertEqual(errors(r.stderr), [], r.stderr)

    def test_theme_choices_match_the_board_themes(self) -> None:
        d = copy.deepcopy(self.doc)
        board_of(d)["themes"].pop()
        r = self.check(d)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue(any("forest" in e for e in errors(r.stderr)), r.stderr)


class ScreenLint(DesignCase):
    SCREEN = "dashboard"   # outside the phone flow: its links don't decide what the entry reaches

    def lint(self, html: str):
        (self.screens / f"{self.SCREEN}.html").write_text(html, encoding="utf-8")
        return self.check()

    def test_each_network_url_base_and_refresh_is_one_error(self) -> None:
        r = self.lint('<main data-bd="x"><img src="https://cdn.example.com/a.png">'
                      '<base href="/">\n<meta http-equiv="refresh" content="0;url=/x"></main>')
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(len(errors(r.stderr)), 3, r.stderr)

    def test_banned_constructs_are_errors(self) -> None:
        cases = {
            "http attribute": '<main data-bd="x"><a href="http://example.com">x</a></main>',
            "protocol-relative": '<main data-bd="x"><img src="//example.com/a.png"></main>',
            "css url": '<main data-bd="x" style="background:url(https://example.com/a.png)"></main>',
            "style block url": '<style>.a{background:url("//example.com/a.png")}</style><main data-bd="x"></main>',
            "iframe": '<main data-bd="x"><iframe src="about:blank"></iframe></main>',
            "object": '<main data-bd="x"><object data="a.swf"></object></main>',
            "embed": '<main data-bd="x"><embed src="a.swf"></main>',
            "form action": '<main data-bd="x"><form action="/__bluedoc/approve"></form></main>',
            "whole document": '<html><head><title>x</title></head><body><main data-bd="x"></main></body></html>',
            "base": '<base href="/"><main data-bd="x"></main>',
        }
        for name, html in cases.items():
            with self.subTest(case=name):
                r = self.lint(html)
                self.assertEqual(r.returncode, 1, f"{name}: {r.stderr}")
                self.assertTrue(errors(r.stderr), f"{name}: no ERROR line")

    def test_a_missing_screen_file_is_an_error(self) -> None:
        (self.screens / f"{self.SCREEN}.html").unlink()
        r = self.check()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue(any(f"{self.SCREEN}.html" in e for e in errors(r.stderr)), r.stderr)

    def test_size_and_data_bd_are_warnings(self) -> None:
        big = '<main data-bd="x">' + "<p>Acme Fit keeps you moving.</p>\n" * 900 + "</main>"
        self.assertGreater(len(big.encode()), 24 * 1024)
        r = self.lint(big)
        self.assertEqual(errors(r.stderr), [], r.stderr)
        self.assertTrue(warnings(r.stderr), "a screen over 24 KB must warn")
        r = self.lint("<main><p>No names to point at.</p></main>")
        self.assertEqual(errors(r.stderr), [], r.stderr)
        self.assertTrue(any("data-bd" in w for w in warnings(r.stderr)), r.stderr)

    def test_a_fragment_with_local_links_and_scripts_is_clean(self) -> None:
        r = self.lint('<main data-bd="x"><a href="#top">Top</a><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">'
                      "<script>document.title = 'Acme';</script></main>")
        self.assertEqual(errors(r.stderr) + warnings(r.stderr), [], r.stderr)


class ScreenHistory(DesignCase):
    def build(self):
        r = self.tmp.run("build.py", self.doc_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stderr

    def test_an_edit_to_a_screen_is_an_edit_in_place_and_voids_the_approval(self) -> None:
        self.build()
        before = build.approval_hash(load_json(self.doc_path), self.doc_path)
        login = self.screens / "login.html"
        old = login.read_text(encoding="utf-8")
        login.write_text(old.replace("Welcome back", "Good to see you"), encoding="utf-8")
        out = self.build()
        self.assertIn("in place", out)
        self.assertNotEqual(build.approval_hash(load_json(self.doc_path), self.doc_path), before,
                            "an HTML edit must change the hash an approval names")

    def test_old_revs_keep_their_html(self) -> None:
        self.build()   # the example's current rev, recorded
        login = self.screens / "login.html"
        old = login.read_text(encoding="utf-8")
        doc = load_json(self.doc_path)
        cur = doc["meta"]["rev"]
        nxt = build.next_rev(cur)
        doc["meta"]["rev"], doc["changes"] = nxt, ["Sign in: friendlier heading."]
        self.write_doc(doc)
        login.write_text(old.replace("Welcome back", "Good to see you"), encoding="utf-8")
        self.build()
        self.assertEqual(build.screen_source(self.doc_path, "login", rev=cur), old)
        self.assertIn("Good to see you", build.screen_source(self.doc_path, "login"))
        h = build.load_history(build.history_path(self.doc_path))
        self.assertEqual([r["rev"] for r in h["revs"]][-2:], [cur, nxt])
        self.assertNotEqual(h["revs"][-2]["screens"]["login"], h["revs"][-1]["screens"]["login"])
        self.assertEqual(h["revs"][-2]["screens"]["watch-face"], h["revs"][-1]["screens"]["watch-face"],
                         "an unchanged screen keeps its hash, so the pool stores it once")

    def test_other_types_keep_no_screens(self) -> None:
        plan = self.docs / "acme-saved-carts-plan.bluedoc.json"
        h = build.load_history(build.history_path(plan))
        self.assertTrue(all("screens" not in r for r in h["revs"]))
        self.assertFalse(h.get("html"))


def scratch_doc(artboards: list[dict], **board) -> dict:
    return {"id": "scratch", "title": "Scratch board", "meta": {"type": "design", "rev": "A"},
            "sections": [{"id": "screens", "title": "Screens",
                          "blocks": [{"type": "board", "id": "main", **board, "artboards": artboards}]}]}


def phone(aid: str, **kw) -> dict:
    return {"id": aid, "title": aid.capitalize(), "device": "phone", "fidelity": "wireframe", **kw}


class Scratch(unittest.TestCase):
    """A design doc written into a temp folder: scratch.bluedoc.json, its screens and icon layers."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.doc_path = self.tmp.dir / "scratch.bluedoc.json"
        self.design = self.tmp.dir / "scratch.design"

    def write(self, doc: dict, screens: dict[str, str], layers: dict[str, str] | None = None):
        self.design.mkdir(parents=True, exist_ok=True)
        self.doc_path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        for aid, html in screens.items():
            (self.design / f"{aid}.html").write_text(html, encoding="utf-8")
        for name, svg in (layers or {}).items():
            (self.design / "app-icon").mkdir(exist_ok=True)
            (self.design / "app-icon" / name).write_text(svg, encoding="utf-8")

    def check(self, doc: dict, screens: dict[str, str], layers: dict[str, str] | None = None) -> tuple[list, list]:
        self.write(doc, screens, layers)
        r = self.tmp.run("build.py", self.doc_path, "--check")
        return errors(r.stderr), warnings(r.stderr)


SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 108 108">\n{}\n</svg>\n'


class Links(Scratch):
    def test_the_example_link_list(self) -> None:
        links = build.board_links(load_json(DOC), DOC)
        self.assertEqual(links[0], {"from": "login", "el": "submit", "to": "today", "kind": "replace", "label": "Tap Sign in"})
        self.assertIn({"from": "today", "el": "tab-workouts", "to": "workouts", "kind": "tab"}, links)
        self.assertIn({"from": "profile", "el": "open-settings", "to": "settings", "kind": "modal",
                       "label": "Tap the gear"}, links)
        edge = next(l for l in links if l.get("edge"))
        self.assertEqual((edge["from"], edge["kind"], edge["to"]), ("workout", "back", None))
        order = [a["id"] for a in board_of(load_json(DOC))["artboards"]]
        self.assertEqual([l["from"] for l in links], sorted([l["from"] for l in links], key=order.index),
                         "board order, then document order")

    def test_each_link_lint_row(self) -> None:
        ok = '<main data-bd="b"><a data-bd="home" data-nav="a">Home</a></main>'
        cases = {   # a.html -> (ERROR or WARN, a needle of the message)
            '<main data-bd="a"><a data-bd="x" data-nav="nowhere">X</a><a data-bd="y" data-nav="b">Y</a></main>':
                ("ERROR", "no artboard 'nowhere'"),
            '<main data-bd="a"><a data-bd="x" data-nav="jump:b">X</a><a data-bd="y" data-nav="b">Y</a></main>':
                ("ERROR", "kinds push, modal, tab, replace"),
            '<main data-bd="a"><a data-bd="x" data-nav="back:b">X</a><a data-bd="y" data-nav="b">Y</a></main>':
                ("ERROR", "takes no target"),
            '<main data-bd="a"><a data-nav="b">X</a></main>': ("ERROR", "has no data-bd"),
            '<main data-bd="a"><a data-bd="x" data-nav="b">X</a><b data-bd="x"></b></main>': ("ERROR", "not unique"),
            '<main data-bd="a"><a data-bd="x" data-nav-label="Tap X">X</a><a data-bd="y" data-nav="b">Y</a></main>':
                ("ERROR", "data-nav-label without data-nav"),
            '<main data-bd="a"><a data-bd="x" data-nav="a">X</a><a data-bd="y" data-nav="b">Y</a></main>':
                ("WARN", "its own screen"),
            '<main data-bd="a"><i hidden data-bd="swipe" data-nav="b"></i></main>': ("WARN", "no data-nav-label"),
            f'<main data-bd="a"><a data-bd="x" data-nav="b" data-nav-label="{"Tap " * 11}">X</a></main>':
                ("WARN", "characters (> 40)"),
        }
        doc = scratch_doc([phone("a"), phone("b")], entry=["a"])
        for html, (level, needle) in cases.items():
            with self.subTest(html=html):
                errs, warns = self.check(doc, {"a": html, "b": ok})
                got = errs if level == "ERROR" else warns
                self.assertTrue(any(needle in l and "a.html:1" in l for l in got), f"{level} {needle!r}: {errs + warns}")
                if level == "WARN":
                    self.assertEqual(errs, [])
        self.assertEqual(self.check(doc, {"a": '<main data-bd="a"><a data-bd="go" data-nav="b">Go</a></main>', "b": ok}),
                         ([], []))

    def test_entry_layout_and_reach(self) -> None:
        screens = {"a": '<main data-bd="a"><a data-bd="go" data-nav="b">Go</a></main>',
                   "b": '<main data-bd="b"><a data-bd="back" data-nav="back">Back</a></main>',
                   "orphan": '<main data-bd="o"></main>', "a2": '<main data-bd="a2"></main>',
                   "web": '<main data-bd="w"></main>', "deck": '<section data-bd="d"></section>'}
        arts = [phone("a"), phone("b"), phone("orphan"), phone("a2", variantOf="a"),
                {"id": "web", "title": "Web", "device": "browser", "fidelity": "wireframe"},
                {"id": "deck", "title": "Deck", "device": "slide", "fidelity": "wireframe"}]
        errs, warns = self.check(scratch_doc(arts, entry=["a"], layout="flow"), screens)
        self.assertEqual(errs, [])
        self.assertEqual(len(warns), 1, warns)
        self.assertIn("'orphan': no entry reaches it", warns[0])
        errs, warns = self.check(scratch_doc(arts), screens)
        self.assertTrue(any("no entry" in w for w in warns), warns)
        errs, _ = self.check(scratch_doc(arts, entry=["nope"], layout="grid"), screens)
        self.assertTrue(any("entry[0]" in e and "'nope'" in e for e in errs), errs)
        self.assertTrue(any(".layout" in e and "'grid'" in e for e in errs), errs)
        errs, _ = self.check(scratch_doc(arts, entry="a"), screens)
        self.assertTrue(any("entry" in e and "a list" in e for e in errs), errs)


class FlowLayout(unittest.TestCase):
    BOARD = {"layout": "flow", "entry": ["a"], "artboards": [
        {"id": "w", "device": "browser"}, {"id": "a", "device": "phone"}, {"id": "b", "device": "phone"},
        {"id": "c", "device": "phone"}, {"id": "d", "device": "phone"}, {"id": "v", "device": "phone", "variantOf": "a"},
        {"id": "p", "device": "phone", "x": 5000, "y": 0}, {"id": "s", "device": "slide"}]}
    LINKS = [{"from": "a", "el": "x", "to": "b", "kind": "push"}, {"from": "a", "el": "y", "to": "c", "kind": "tab"},
             {"from": "b", "el": "z", "to": "d", "kind": "modal"}, {"from": "d", "el": "q", "to": "p", "kind": "push"},
             {"from": "c", "el": "back", "to": None, "kind": "back"}, {"from": "v", "el": "r", "to": "a", "kind": "replace"}]

    def test_columns_by_depth_variants_under_their_source_and_the_rest_below(self) -> None:
        at = {k: v[:2] for k, v in build.board_layout(self.BOARD, self.LINKS).items()}
        self.assertEqual(at["a"], (0, 0))
        self.assertEqual(at["v"], (0, 964), "a variant sits right under its source")
        self.assertEqual((at["b"], at["c"]), ((590, 0), (590, 964)))
        self.assertEqual(at["d"], (1180, 0))
        self.assertEqual(at["p"], (5000, 0), "a placed screen keeps its place")
        self.assertEqual(at["w"], (0, 1928), "unreached screens go in rows below the flow")
        self.assertEqual(at["s"], (5390 + 80, 0), "the slide column stays right of everything")

    def test_rows_without_flow_or_entry_are_unchanged(self) -> None:
        rows = {**self.BOARD, "layout": "rows"}
        no_entry = {**self.BOARD, "entry": []}
        plain = {k: v for k, v in self.BOARD.items() if k not in ("layout", "entry")}
        for b in (rows, no_entry):
            self.assertEqual(build.board_layout(b, self.LINKS), build.board_layout(plain))
        self.assertEqual(build.board_layout(plain)["a"][:2], (1520, 0))

    def test_without_links_the_entries_and_their_variants_flow(self) -> None:
        at = build.board_layout(self.BOARD)
        self.assertEqual((at["a"][:2], at["v"][:2]), ((0, 0), (0, 964)))
        self.assertEqual(at["b"][:2], (1520, 1928), "unreached: row 0 below the flow, right of w")


class Icons(Scratch):
    DOC = scratch_doc([{"id": "app-icon", "title": "App icon", "device": "icons", "fidelity": "hifi",
                        "icon": {"bg": "#0f766e", "name": "Acme Fit"}}])
    FG = SVG.format('<circle cx="54" cy="54" r="24" fill="#fff"/>')
    MONO = SVG.format('<path d="M40 54 L54 40 L68 54 Z"/>')

    def test_clean_layers(self) -> None:
        self.assertEqual(self.check(self.DOC, {}, {"fg.svg": self.FG, "mono.svg": self.MONO}), ([], []))
        self.assertEqual(build.DEVICES["icons"], {"w": 1280, "h": 860, "safe": [0, 0, 0, 0]})

    def test_each_icon_lint_row(self) -> None:
        cases = {   # fg.svg -> (ERROR or WARN, needle)
            "<svg": ("ERROR", "not XML"),
            '<svg xmlns="http://www.w3.org/2000/svg"><circle r="1"/></svg>': ("ERROR", "no viewBox"),
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 108 100"/>': ("ERROR", "not square"),
            SVG.format("<script>alert(1)</script>"): ("ERROR", "<script>"),
            SVG.format("<foreignObject/>"): ("ERROR", "<foreignObject>"),
            SVG.format('<circle cx="54" cy="54" r="9" onclick="x()"/>'): ("ERROR", "onclick"),
            SVG.format('<image href="https://cdn.example.com/a.png" width="9" height="9"/>'): ("ERROR", "network URL"),
            '<!DOCTYPE svg [<!ENTITY x "y">]><svg viewBox="0 0 108 108"/>': ("ERROR", "DOCTYPE"),
            SVG.format('<circle cx="54" cy="54" r="40"/>'): ("WARN", "outside the 66 dp safe circle"),
            SVG.format('<g transform="translate(30 0)"><rect x="40" y="44" width="20" height="20"/></g>'):
                ("WARN", "outside the 66 dp safe circle"),
            SVG.format('<path d="M54 30 C 100 30, 100 78, 54 78 Z"/>'): ("WARN", "outside the 66 dp safe circle"),
            SVG.format('<text x="40" y="54">A</text>'): ("WARN", "<text>"),
        }
        for fg, (level, needle) in cases.items():
            with self.subTest(fg=fg):
                errs, warns = self.check(self.DOC, {}, {"fg.svg": fg, "mono.svg": self.MONO})
                got = errs if level == "ERROR" else warns
                self.assertTrue(any(needle in l and "fg.svg" in l for l in got), f"{needle!r}: {errs + warns}")
        # inside the circle at another viewBox scale: clean
        big = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><circle cx="512" cy="512" r="300"/></svg>'
        self.assertEqual(self.check(self.DOC, {}, {"fg.svg": big, "mono.svg": self.MONO}), ([], []))

    def test_missing_layers_and_fields(self) -> None:
        (self.design / "app-icon").mkdir(parents=True)
        errs, warns = self.check(self.DOC, {})
        self.assertTrue(any("fg.svg is missing" in e for e in errs), errs)
        no_bg = copy.deepcopy(self.DOC)
        del board_of(no_bg)["artboards"][0]["icon"]
        errs, warns = self.check(no_bg, {}, {"fg.svg": self.FG})
        self.assertEqual(errs, [])
        self.assertTrue(any("mono.svg" in w for w in warns), warns)
        self.assertTrue(any("no background" in w for w in warns), warns)
        self.assertEqual(self.check(no_bg, {}, {"fg.svg": self.FG, "mono.svg": self.MONO, "bg.svg": SVG.format(
            '<rect width="108" height="108" fill="#0f766e"/>')}), ([], []))
        bad = copy.deepcopy(self.DOC)
        board_of(bad)["artboards"][0]["icon"]["bg"] = "teal"
        board_of(bad)["artboards"].append(phone("a", icon={"bg": "#fff"}))
        errs, _ = self.check(bad, {"a": '<main data-bd="a"></main>'})
        self.assertTrue(any("icon.bg" in e and "hex colour" in e for e in errs), errs)
        self.assertTrue(any("artboards[1].icon" in e and "only an artboard" in e for e in errs), errs)

    def test_layers_join_the_revision_and_the_approval(self) -> None:
        self.write(self.DOC, {}, {"fg.svg": self.FG, "mono.svg": self.MONO})
        r = self.tmp.run("build.py", self.doc_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = load_json(self.doc_path)
        self.assertEqual(sorted(build.screen_hashes(doc, self.doc_path)), ["app-icon/fg.svg", "app-icon/mono.svg"])
        self.assertEqual(list(build.icon_layers(doc, self.doc_path)["app-icon"]), ["fg.svg", "mono.svg"])
        before = build.approval_hash(doc, self.doc_path)
        (self.design / "app-icon" / "fg.svg").write_text(self.FG.replace("24", "20"), encoding="utf-8")
        self.assertNotEqual(build.approval_hash(doc, self.doc_path), before, "a layer edit asks for approval again")
        doc["meta"]["rev"], doc["changes"] = "B", ["A smaller mark."]
        self.doc_path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(self.tmp.run("build.py", self.doc_path).returncode, 0)
        self.assertEqual(build.screen_source(self.doc_path, "app-icon/fg.svg", rev="A"), self.FG)
        self.assertIn('r="20"', build.screen_source(self.doc_path, "app-icon/fg.svg"))


class LinksInTheHistoryAndThePage(Scratch):
    A = '<main data-bd="a"><a data-bd="go" data-nav="b" data-nav-label="Tap Go">Go</a></main>'
    B = '<main data-bd="b"><a data-bd="back" data-nav="back">Back</a></main>'

    def test_each_rev_records_its_links_and_the_page_gets_them(self) -> None:
        doc = scratch_doc([phone("a"), phone("b")], entry=["a"])
        self.write(doc, {"a": self.A, "b": self.B})
        self.assertEqual(self.tmp.run("build.py", self.doc_path).returncode, 0)
        links = build.board_links(doc, self.doc_path)
        self.assertEqual(links, [{"from": "a", "el": "go", "to": "b", "kind": "push", "label": "Tap Go"},
                                 {"from": "b", "el": "back", "to": None, "kind": "back"}])
        h = build.load_history(build.history_path(self.doc_path))
        self.assertEqual(h["revs"][0]["links"], links)
        self.assertEqual(build.embed_history(h, doc), {"revs": [{"rev": "A", "links": links}], "blocks": {}},
                         "one rev: its links alone")
        (self.design / "a.html").write_text(self.A.replace('data-nav="b"', 'data-nav="modal:b"'), encoding="utf-8")
        doc["meta"]["rev"], doc["changes"] = "B", ["Go opens B as a sheet."]
        self.write(doc, {})
        self.assertEqual(self.tmp.run("build.py", self.doc_path).returncode, 0)
        h = build.load_history(build.history_path(self.doc_path))
        page = build.embed_history(h, doc)
        self.assertEqual([r["links"][0]["kind"] for r in page["revs"]], ["push", "modal"])
        self.assertNotIn("head", page["revs"][-1], "the current rev is the page's own doc")
        fresh = build.embed_history(h, doc, [{"from": "a", "el": "go", "to": "b", "kind": "tab"}])
        self.assertEqual(fresh["revs"][-1]["links"][0]["kind"], "tab", "the current rev's links come from the files")

    def test_design_pages_inline_board_geo_and_pages_without_a_board_or_canvas_do_not(self) -> None:
        doc = scratch_doc([phone("a"), phone("b")], entry=["a"])
        self.write(doc, {"a": self.A, "b": self.B})
        template = ("<script>/*__BOARD_GEO__*/</script><script type=\"application/json\">__BLUEDOC_DOC__</script>"
                    "<script type=\"application/json\">__BLUEDOC_HISTORY__</script>")
        page = build.build(doc, template, None, diff_path=self.doc_path, problems=[])
        geo = build.BOARD_GEO.read_text(encoding="utf-8")
        self.assertIn(geo.strip().splitlines()[0], page)
        self.assertNotIn("/*__BOARD_GEO__*/", page)
        self.assertNotIn("</script", page.split("<script>", 1)[1][:-len(page.split("</script>", 1)[1]) - 9])
        self.assertIn('"links":[{"from":"a"', page, "bp-hist carries the current links")
        other = build.build(load_json(EXAMPLES / "acme-review-findings.bluedoc.json"), template, None, problems=[])
        self.assertIn("<script></script>", other)

    def test_the_flow_layout_of_a_scratch_board(self) -> None:
        doc = scratch_doc([phone("b"), phone("a")], entry=["a"], layout="flow")
        self.write(doc, {"a": self.A, "b": self.B})
        at = build.board_layout(board_of(doc), build.board_links(doc, self.doc_path))
        self.assertEqual((at["a"][:2], at["b"][:2]), ((0, 0), (590, 0)))


class IconsAndFlowScaffold(unittest.TestCase):
    def test_new_design_mobile_icons(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        p = tmp.dir / "fit.bluedoc.json"
        r = tmp.run("build.py", "new", "design", p, "--target", "mobile,web", "--icons")
        self.assertEqual(r.returncode, 0, r.stderr)
        board = board_of(load_json(p))
        self.assertEqual((board["entry"], board["layout"]), (["mobile"], "flow"))
        icon = board["artboards"][-1]
        self.assertEqual((icon["id"], icon["device"], icon["icon"]["bg"]), ("app-icon", "icons", "#2563eb"))
        for layer in ("fg.svg", "mono.svg"):
            self.assertTrue((tmp.dir / "fit.design" / "app-icon" / layer).is_file())
        p.write_text(build.PLACEHOLDER.sub("Acme Fit", p.read_text(encoding="utf-8")), encoding="utf-8")
        r = tmp.run("build.py", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 error(s), 0 warning(s)", r.stderr)
        self.assertEqual(tmp.run("build.py", "new", "docs", tmp.dir / "x.bluedoc.json", "--icons").returncode, 2)


class NewPresentation(unittest.TestCase):
    """`build.py new presentation`: the stub deck, filled in, its speaker notes, and slides-only."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.doc_path = self.tmp.dir / "deck.bluedoc.json"
        r = self.tmp.run("build.py", "new", "presentation", self.doc_path, "--title", "Acme Fit launch")
        self.assertEqual(r.returncode, 0, r.stderr)
        # every <<placeholder>> filled, as the agent would
        raw = build.PLACEHOLDER.sub("Acme Fit launch", self.doc_path.read_text(encoding="utf-8"))
        self.doc_path.write_text(raw, encoding="utf-8")
        self.doc = load_json(self.doc_path)

    def check(self, doc: dict):
        self.doc_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return self.tmp.run("build.py", self.doc_path, "--check")

    def test_the_stub_deck_is_three_slides_in_a_column_and_builds_clean(self) -> None:
        self.assertEqual((self.doc["meta"]["type"], self.doc["meta"]["kind"]), ("presentation", "Presentation"))
        board = board_of(self.doc)
        self.assertEqual(board["targets"], ["presentation"])
        self.assertEqual([(a["id"], a["device"]) for a in board["artboards"]],
                         [("title", "slide"), ("content", "slide"), ("closing", "slide")])
        self.assertEqual(build.DEVICES["slide"], {"w": 1920, "h": 1080, "safe": [0, 0, 0, 0]})
        layout = build.board_layout(board)
        self.assertEqual([layout[k][:2] for k in ("title", "content", "closing")], [(0, 0), (0, 1360), (0, 2720)])
        for a in board["artboards"]:
            html = (self.tmp.dir / "deck.design" / f"{a['id']}.html").read_text(encoding="utf-8")
            self.assertIn('class="slide', html)
        r = self.tmp.run("build.py", self.doc_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 error(s), 0 warning(s)", r.stderr)

    def test_notes_over_2_kb_are_an_error(self) -> None:
        d = copy.deepcopy(self.doc)
        board_of(d)["artboards"][1]["notes"] = "Acme Fit doubled weekly actives. " * 70
        r = self.check(d)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue(any("artboards[1].notes" in e and "2048" in e for e in errors(r.stderr)), r.stderr)
        board_of(d)["artboards"][1]["notes"] = "Acme Fit doubled weekly actives."
        self.assertEqual(errors(self.check(d).stderr), [])

    def test_a_phone_artboard_in_a_presentation_is_an_error(self) -> None:
        d = copy.deepcopy(self.doc)
        board_of(d)["artboards"][1]["device"] = "phone"
        r = self.check(d)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue(any("a presentation holds slides only; use a design doc for screens" in e for e in errors(r.stderr)), r.stderr)

    def test_a_design_may_hold_a_slide(self) -> None:
        d = copy.deepcopy(self.doc)
        d["meta"]["type"] = "design"
        self.assertEqual(errors(self.check(d).stderr), [])
        board_of(d)["artboards"][1]["device"] = "phone"
        self.assertEqual(build.check_contract(d), [])

    def test_new_design_refuses_the_presentation_target(self) -> None:
        r = self.tmp.run("build.py", "new", "design", self.tmp.dir / "old.bluedoc.json", "--target", "presentation")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("build.py new presentation", r.stderr)
        self.assertFalse((self.tmp.dir / "old.bluedoc.json").exists())

    def test_on_a_mixed_board_the_slide_column_sits_right_of_the_other_artboards(self) -> None:
        board = {"artboards": [{"id": "title", "device": "slide"}, {"id": "home", "device": "phone"},
                               {"id": "home-b", "device": "phone", "variantOf": "home"},
                               {"id": "web", "device": "browser", "x": 0, "y": 1000}, {"id": "ask", "device": "slide"}]}
        layout = build.board_layout(board)
        self.assertEqual(list(layout), ["title", "home", "home-b", "web", "ask"])
        self.assertEqual([layout[k][:2] for k in ("home", "home-b", "web")], [(0, 0), (470, 0), (0, 1000)])
        self.assertEqual([layout[k][:2] for k in ("title", "ask")], [(1520, 0), (1520, 1360)])


class DeckExample(unittest.TestCase):
    """The bundled deck, acme-fit-deck: a presentation of five hi-fi plain-kit slides in one column, notes on some, one
    revision."""

    STEM = "acme-fit-deck"

    def test_the_deck_builds_clean(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        docs = tmp.copy_examples()
        r = tmp.run("build.py", docs / f"{self.STEM}.bluedoc.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 error(s), 0 warning(s)", r.stderr)

    def test_deck_shape(self) -> None:
        doc_path = EXAMPLES / f"{self.STEM}.bluedoc.json"
        doc = load_json(doc_path)
        self.assertEqual(doc["meta"]["type"], "presentation")
        board = board_of(doc)
        self.assertEqual(board["targets"], ["presentation"])
        self.assertFalse(board.get("frameworks"), "the deck must need nothing the reader provides")
        arts = board["artboards"]
        self.assertEqual([a["id"] for a in arts], ["title", "shipped", "actives", "quote", "ask"])
        self.assertEqual({(a["device"], a["fidelity"], a.get("framework", board["framework"])) for a in arts},
                         {("slide", "hifi", "plain")})
        self.assertGreaterEqual(sum(bool(a.get("notes")) for a in arts), 2)
        layout = build.board_layout(board)
        self.assertEqual({layout[a["id"]][0] for a in arts}, {0}, "the deck lays out in one column")
        ys = [layout[a["id"]][1] for a in arts]
        self.assertEqual(ys, sorted(set(ys)), "slides stack top to bottom in deck order")
        html = "".join((EXAMPLES / f"{self.STEM}.design" / f"{a['id']}.html").read_text(encoding="utf-8") for a in arts)
        for cls in ("slide-cols", "slide-big", "slide-quote"):
            self.assertIn(cls, html)
        h = load_json(EXAMPLES / f"{self.STEM}.bluedoc.history.json")
        self.assertEqual([r["rev"] for r in h["revs"]], ["A"])
        self.assertEqual(h["revs"][0]["screens"], build.screen_hashes(doc, doc_path))


DECK_IDS = ["title", "shipped", "actives", "quote", "ask"]


def deck_data(html: str) -> dict:
    """The deck file's JSON: {w, h, assets, slides}."""
    return json.loads(re.search(r'<script type="application/json" id="deck">(.*?)</script>', html, re.S)[1])


def slide_page(data: dict, slide: dict) -> str:
    """A slide's whole document, as the player puts it back together."""
    return "".join(p if isinstance(p, str) else data["assets"][p] for p in slide["parts"])


class DeckFile(unittest.TestCase):
    """`build.py <deck> --deck out.html`: acme-fit-deck as one HTML file that plays offline, every slide in deck order
    wrapped in its kit with the brief's theme, its notes as HTML, nothing from the network; other doc types refused."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.doc_path = self.docs / "acme-fit-deck.bluedoc.json"
        self.out = self.tmp.dir / "out" / "acme-fit-deck.html"

    def test_every_slide_in_order_with_notes_and_nothing_external(self) -> None:
        r = self.tmp.run("build.py", self.doc_path, "--deck", self.out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("5 slides", r.stderr)
        html = self.out.read_text(encoding="utf-8")
        data = deck_data(html)
        self.assertEqual((data["w"], data["h"]), (1920, 1080))
        self.assertEqual([s["id"] for s in data["slides"]], DECK_IDS)
        doc = load_json(self.doc_path)
        self.assertIn(f"<title>{doc['title']}</title>", html)
        for a, s in zip(board_of(doc)["artboards"], data["slides"]):
            page = slide_page(data, s)
            fragment = (self.docs / "acme-fit-deck.design" / f"{a['id']}.html").read_text(encoding="utf-8")
            self.assertIn(fragment, page, a["id"])
            self.assertIn("--accent: #4f46e5;", page, "the brief's pick, Indigo")
            self.assertIn(build.STANDALONE_SCREEN_CSP, page)
            self.assertEqual(s["title"], a["title"])
            self.assertEqual(bool(s["notes"]), bool(a.get("notes")), a["id"])
        self.assertIn("<strong>41,800</strong>", data["slides"][2]["notes"])
        self.assertIn("<li>Passkeys halved the time to sign in.</li>", data["slides"][1]["notes"])
        self.assertIsNone(re.search(r"(?i)\b(?:https?:)?//[a-z0-9]", html), "the file must not reach the network")
        self.assertNotIn("/__bluedoc/", html)
        self.assertNotIn("bluedoc inspector", html, "no editor code in the slides")
        self.assertEqual(html.count("bluedoc wireframe kit"), 1, "the kit the slides share is stored once")
        self.assertLess(len(html.encode()), 100_000)

    def test_other_doc_types_are_refused(self) -> None:
        for stem in ("acme-fit-design", "acme-status"):
            r = self.tmp.run("build.py", self.docs / f"{stem}.bluedoc.json", "--deck", self.out)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("only a presentation exports as a deck", r.stderr)
            self.assertFalse(self.out.exists())


class DeckRoute(unittest.TestCase):
    """GET /__bluedoc/deck?path=…&rev=…&theme=…: the same file as an attachment, a read with no key; the revision and
    theme asked for; 400 for another doc type or an unknown revision."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.doc_path = self.docs / "acme-fit-deck.bluedoc.json"
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.url = self.server.url_for(self.doc_path)

    def deck(self, url: str, **q: str) -> tuple[int, dict, bytes]:
        query = "&".join(f"{k}={quote(v)}" for k, v in {"path": url, **q}.items())
        return self.server.exchange("GET", f"/__bluedoc/deck?{query}")

    def test_the_deck_downloads_as_an_attachment(self) -> None:
        status, headers, body = self.deck(self.url)
        self.assertEqual(status, 200, body[:300])
        self.assertTrue(headers["content-disposition"].startswith('attachment; filename="acme-fit-deck.html"'), headers)
        self.assertTrue(headers["content-type"].startswith("text/html"))
        data = deck_data(body.decode("utf-8"))
        self.assertEqual([s["id"] for s in data["slides"]], DECK_IDS)
        self.assertIn("--accent: #4f46e5;", slide_page(data, data["slides"][0]))
        _, _, forest = self.deck(self.url, theme="forest")
        self.assertIn("--accent: #15803d;", slide_page(deck_data(forest.decode("utf-8")), deck_data(forest.decode("utf-8"))["slides"][0]))

    def test_an_earlier_revision_is_the_one_asked_for(self) -> None:
        title = self.docs / "acme-fit-deck.design" / "title.html"
        title.write_text(title.read_text(encoding="utf-8").replace("Q3 launch review", "Q3 launch recap"), encoding="utf-8")
        doc = load_json(self.doc_path)
        doc["meta"]["rev"] = "B"
        self.doc_path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        self.assertEqual(self.tmp.run("build.py", self.doc_path).returncode, 0)
        pages = {}
        for rev in ("A", "B", None):
            status, _, body = self.deck(self.url, **({"rev": rev} if rev else {}))
            self.assertEqual(status, 200, body[:300])
            data = deck_data(body.decode("utf-8"))
            pages[rev] = slide_page(data, data["slides"][0])
        self.assertIn(">Q3 launch review</h1>", pages["A"])
        self.assertNotIn(">Q3 launch review</h1>", pages["B"])
        self.assertIn(">Q3 launch recap</h1>", pages["B"])
        self.assertEqual(pages[None], pages["B"])
        status, _, body = self.deck(self.url, rev="Z")
        self.assertEqual(status, 400)
        self.assertIn("no revision Z", json.loads(body)["error"])

    def test_other_doc_types_unknown_docs_and_foreign_hosts_are_refused(self) -> None:
        status, _, body = self.deck(self.server.url_for(self.docs / f"{STEM}.bluedoc.json"))
        self.assertEqual(status, 400)
        self.assertIn("only a presentation exports as a deck", json.loads(body)["error"])
        self.assertEqual(self.deck(self.url.replace("acme-fit-deck", "acme-gone"))[0], 404)
        status, _, _ = self.server.exchange("GET", f"/__bluedoc/deck?path={quote(self.url)}", headers={"Host": "evil.example:80"})
        self.assertEqual(status, 403)


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class DeckPlayer(unittest.TestCase):
    """The deck file over file:// in headless Chrome: the first slide renders in its sandboxed frame, → steps to #2,
    N shows the notes, a click on the slide steps to #3."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = Path(tempfile.mkdtemp(prefix="bluedoc-chrome-"))
        cls.browser = Browser(cls.profile)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        shutil.rmtree(cls.profile, ignore_errors=True)

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        docs = self.tmp.copy_examples()
        self.out = self.tmp.dir / "acme-fit-deck.html"
        r = self.tmp.run("build.py", docs / "acme-fit-deck.bluedoc.json", "--deck", self.out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.browser.errors.clear()

    def key(self, tab: Tab, key: str, code: str, vk: int) -> None:
        for typ in ("keyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": typ, "key": key, "code": code, "windowsVirtualKeyCode": vk,
                                                         **({"text": key} if typ == "keyDown" and len(key) == 1 else {})}, tab.session)

    def slide_text(self, slide: str) -> str | None:
        """The headline of the frame showing slide (sandboxed frames are targets of their own), once it has loaded."""
        for t in self.browser.call("Target.getTargets")["targetInfos"]:
            if t["type"] != "iframe" or t["url"] != "about:srcdoc":
                continue
            s = self.browser.call("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True})["sessionId"]
            r = self.browser.call("Runtime.evaluate", {"expression": "[document.documentElement.dataset.bdArtboard, "
                                  "(document.querySelector('.slide-title') || {}).textContent, getComputedStyle(document.querySelector('.slide-kicker') || document.body).color]",
                                  "returnByValue": True}, s)
            self.browser.call("Target.detachFromTarget", {"sessionId": s})
            aid, text, kicker = (r.get("result") or {}).get("value") or [None, None, None]
            if aid == slide and text:
                return f"{text} {kicker}"
        return None

    def test_the_deck_plays_from_a_file(self) -> None:
        tab = Tab(self.browser)
        self.browser.call("Page.navigate", {"url": self.out.as_uri()}, tab.session)
        tab.wait_for("document.readyState === 'complete' && location.hash === '#1' && !!document.querySelector('iframe.fr.on')")
        self.assertEqual(tab.ev("document.title"), "Acme Fit: Q3 launch review deck")
        self.assertEqual(until(lambda: self.slide_text("title")), "Q3 launch review rgb(79, 70, 229)", "the title slide in Indigo")
        self.assertTrue(tab.ev("document.getElementById('notes').hidden"))
        self.key(tab, "ArrowRight", "ArrowRight", 39)
        tab.wait_for("location.hash === '#2'")
        self.assertTrue(tab.ev("document.getElementById('cap').textContent.startsWith('2 / 5')"))
        self.key(tab, "n", "KeyN", 78)
        tab.wait_for("!document.getElementById('notes').hidden")
        self.assertIn("Three launches this quarter", tab.ev("document.getElementById('notes').textContent"))
        self.assertTrue(until(lambda: self.slide_text("shipped")), "the second slide's frame loaded")
        tab.ev("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")   # the slide laid out above the notes
        for typ in ("mousePressed", "mouseReleased"):   # on the slide, inside its frame
            self.browser.call("Input.dispatchMouseEvent", {"type": typ, "x": 720, "y": 300, "button": "left", "clickCount": 1}, tab.session)
        tab.wait_for("location.hash === '#3'")
        self.assertEqual(self.browser.errors, [])


class FrameworkFallback(unittest.TestCase):
    """The screen route: declared framework files are served, undeclared ones are not, a missing one falls back."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.doc_path = self.docs / f"{STEM}.bluedoc.json"
        vendor = self.docs / "vendor"
        vendor.mkdir()
        (vendor / "acme-web.css").write_text(".btn{border-radius:2px}\n", encoding="utf-8")
        (vendor / "private.css").write_text(".secret{}\n", encoding="utf-8")
        doc = load_json(self.doc_path)
        board = board_of(doc)
        board["frameworks"] = [{"id": "acme-web", "label": "Acme web CSS", "files": ["vendor/acme-web.css"]},
                               {"id": "acme-gone", "label": "Acme gone CSS", "files": ["vendor/gone.css"]}]
        board["artboards"][1]["framework"] = "acme-web"
        board["artboards"][2]["framework"] = "acme-gone"
        self.doc_path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.url = self.server.url_for(self.doc_path)
        self.base = self.url.rsplit("/", 1)[0]

    def screen(self, artboard: str) -> tuple[int, str]:
        status, body = self.server.req("GET", f"{self.base}/{STEM}.design/{artboard}.html")
        return status, body.decode("utf-8", "replace")

    def test_the_build_warns_with_the_missing_path(self) -> None:
        r = self.tmp.run("build.py", self.doc_path, "--check")
        self.assertTrue(any("vendor/gone.css" in w for w in warnings(r.stderr)), r.stderr)

    def test_a_declared_file_is_linked_and_served(self) -> None:
        status, html = self.screen("login")
        self.assertEqual(status, 200)
        self.assertIn("vendor/acme-web.css", html)
        self.assertEqual(self.server.req("GET", f"{self.base}/vendor/acme-web.css")[0], 200)

    def test_an_undeclared_file_is_404(self) -> None:
        self.assertEqual(self.server.req("GET", f"{self.base}/vendor/private.css")[0], 404)

    def test_a_missing_framework_shows_the_plain_kit_with_a_notice(self) -> None:
        status, html = self.screen("login-b")
        self.assertEqual(status, 200)
        self.assertIn('id="bd-notice"', html)
        self.assertIn("Acme gone CSS not found: showing the plain kit", html)
        self.assertIn("/__bluedoc/kit/base.css", html, "the fallback must load the plain kit")
        self.assertNotIn("vendor/gone.css", html)


class ShippedFrameworks(unittest.TestCase):
    """heroui and tailwind ship in assets/vendor/heroui: `new design --framework heroui` builds with no warning in a
    BLUEDOC_HOME with no frameworks folder, a doc naming the old heroui store still builds clean and loads the shipped
    copy, and the screen route links the vendored files and Tailwind's compile step."""

    PINNED = {"heroui/heroui.min.css": "95ac190a78f5f7c2126f365096fdf08326cf206cd0c8fdf0e8532e7185f32a2e",
              "heroui/tailwind.js": "a60c785630a06196808cbe79e6f7bdb4abcc8f4421a47b56f29338fc84805e3b"}

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)

    def test_new_design_with_heroui_builds_with_no_warning(self) -> None:
        doc_path = self.tmp.dir / "s.bluedoc.json"
        r = self.tmp.run("build.py", "new", "design", doc_path, "--target", "mobile,web", "--framework", "heroui")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc_path.write_text(build.PLACEHOLDER.sub("Acme Fit", doc_path.read_text(encoding="utf-8")), encoding="utf-8")
        doc = load_json(doc_path)
        board = board_of(doc)
        self.assertEqual(board["framework"], "heroui")
        self.assertFalse(board.get("frameworks"), "a shipped framework needs no frameworks[] entry")
        item = next(it for b in build.all_blocks(doc) if b.get("id") == "brief" and b.get("type") == "checklist"
                    for it in b["items"] if it["id"] == "framework")
        self.assertEqual((item["recommend"], item["choices"][0]), ("heroui", {"id": "heroui", "label": "Tailwind + HeroUI"}))
        r = self.tmp.run("build.py", doc_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 error(s), 0 warning(s)", r.stderr)
        self.assertFalse((self.tmp.home / "frameworks").exists())

    def test_a_doc_naming_the_heroui_store_checks_clean(self) -> None:
        docs = self.tmp.copy_examples()
        doc_path = docs / f"{STEM}.bluedoc.json"
        doc = load_json(doc_path)
        board = board_of(doc)
        legacy = {"id": "heroui", "label": "Tailwind + HeroUI", "store": "heroui"}
        cases = {"legacy store": ([legacy], None), "builtin id": ([{**legacy, "id": "plain"}], "is built in"),
                 "duplicate": ([legacy, legacy], "is a duplicate")}
        for name, (fws, err) in cases.items():
            with self.subTest(case=name):
                board["frameworks"] = fws
                board["artboards"][1]["framework"] = "heroui"
                doc_path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
                r = self.tmp.run("build.py", doc_path, "--check")
                if err is None:
                    self.assertEqual(errors(r.stderr) + warnings(r.stderr), [], r.stderr)
                else:
                    self.assertTrue(any(err in e for e in errors(r.stderr)), r.stderr)

    def test_add_framework_heroui_needs_nothing(self) -> None:
        r = self.tmp.run("serve.py", "add-framework", "heroui")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ships with bluedoc", r.stdout)
        self.assertFalse((self.tmp.home / "frameworks").exists())
        self.assertEqual(self.tmp.run("serve.py", "add-framework", "plain").returncode, 2)

    def test_the_screen_route_loads_the_vendored_files(self) -> None:
        docs = self.tmp.copy_examples()
        doc_path = docs / f"{STEM}.bluedoc.json"
        doc = load_json(doc_path)
        board = board_of(doc)
        board["frameworks"] = [{"id": "hero-old", "label": "Tailwind + HeroUI", "store": "heroui"}]
        arts = board["artboards"]
        arts[0]["framework"], arts[1]["framework"], arts[2]["framework"] = "heroui", "tailwind", "hero-old"
        doc_path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        self.assertEqual(self.tmp.run("serve.py", "add", docs).returncode, 0)
        server = Server(self.tmp)
        server.start()
        self.addCleanup(server.stop)
        base = server.url_for(doc_path).rsplit("/", 1)[0]
        for a, files in ((arts[0], self.PINNED), (arts[1], ["heroui/tailwind.js"]), (arts[2], self.PINNED)):
            with self.subTest(artboard=a["id"]):
                status, body = server.req("GET", f"{base}/{STEM}.design/{a['id']}.html")
                html = body.decode("utf-8", "replace")
                self.assertEqual(status, 200)
                self.assertNotIn('id="bd-notice"', html)
                self.assertIn('<style type="text/tailwindcss">@import "tailwindcss";', html)
                self.assertEqual(sorted(re.findall(r'/__bluedoc/vendor/(heroui/[^"?]+)', html)), sorted(files))
        for rel, sha in self.PINNED.items():
            status, body = server.req("GET", f"/__bluedoc/vendor/{rel}")
            self.assertEqual((status, hashlib.sha256(body).hexdigest()), (200, sha), rel)


if __name__ == "__main__":
    unittest.main()
