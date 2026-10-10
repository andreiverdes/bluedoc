"""Design docs: the Acme Fit example, the board contract, screen-file lint, screen HTML in the history, the
presentation target, and the screen route's framework fallback.

The example builds clean and its history holds both revisions with one HTML entry per screen version. The contract
wants exactly one board with an artboard; the board's ids, devices, fidelity, variants, themes and frameworks are
checked. Each banned construct in a screen file is one ERROR. An edit to a screen file under the same rev is an edit
in place that changes the approval hash, and the old rev's HTML stays readable. `new design --target presentation`
writes a three-slide deck in one row that builds clean once filled in; speaker notes over 2 KB are an ERROR. The
bundled deck, acme-fit-deck, builds clean: five hi-fi plain-kit slides in one row with notes, one revision. The
server serves only screens and declared framework files, and wraps a screen whose framework is missing in the plain
kit with a notice."""
from __future__ import annotations

import copy
import json
import unittest

from _support import EXAMPLES, Server, TempHome, load_json

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
        self.assertEqual(ids, ["watch-face", "login", "login-b", "dashboard"])
        devices = {a["id"]: a["device"] for a in board["artboards"]}
        self.assertEqual(devices["watch-face"], "watch-round")
        self.assertEqual(devices["dashboard"], "browser")
        self.assertEqual([a["id"] for a in board["artboards"] if a.get("variantOf")], ["login-b"])
        # the example runs on what ships with bluedoc: the plain kit and HorizonUI, no reader framework
        used = {a.get("framework", board.get("framework", "plain")) for a in board["artboards"]}
        self.assertEqual(used, {"plain", "horizon"})
        self.assertFalse(board.get("frameworks"), "the example must need nothing the reader provides")
        for a in ids:
            self.assertTrue((SCREENS / f"{a}.html").is_file(), f"no screen file for {a}")

    def test_the_history_holds_two_revs_and_one_html_entry_per_screen_version(self) -> None:
        h = load_json(EXAMPLES / f"{STEM}.bluedoc.history.json")
        self.assertEqual([r["rev"] for r in h["revs"]], ["A", "B"])
        screens = [r["screens"] for r in h["revs"]]
        versions = {v for s in screens for v in s.values()}
        self.assertEqual(set(h["html"]), versions, "the html pool holds exactly the screen versions the revs name")
        a, b = screens
        self.assertEqual(sorted(a), ["dashboard", "login", "watch-face"], "rev A: three wireframes")
        self.assertEqual(sorted(b), ["dashboard", "login", "login-b", "watch-face"], "rev B adds the passkey-first variant")
        self.assertEqual(len(h["html"]), 7, "every rev A wireframe was redrawn hi-fi in rev B, plus the variant")
        self.assertTrue(all(a[k] != b[k] for k in a))
        self.assertIn("wf-box", h["html"][a["login"]], "rev A's sign-in is a wireframe")
        # the current rev's hashes are the files on disk
        self.assertEqual(b, build.screen_hashes(load_json(DOC), DOC))


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
    SCREEN = "login"

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
        login = self.screens / "login.html"
        old = login.read_text(encoding="utf-8")
        doc = load_json(self.doc_path)
        doc["meta"]["rev"], doc["meta"]["changes"] = "C", "Sign in: friendlier heading."
        self.write_doc(doc)
        login.write_text(old.replace("Welcome back", "Good to see you"), encoding="utf-8")
        self.build()
        self.assertEqual(build.screen_source(self.doc_path, "login", rev="B"), old)
        self.assertIn("Good to see you", build.screen_source(self.doc_path, "login"))
        h = build.load_history(build.history_path(self.doc_path))
        self.assertEqual([r["rev"] for r in h["revs"]], ["A", "B", "C"])
        self.assertNotEqual(h["revs"][1]["screens"]["login"], h["revs"][2]["screens"]["login"])
        self.assertEqual(h["revs"][1]["screens"]["watch-face"], h["revs"][2]["screens"]["watch-face"],
                         "an unchanged screen keeps its hash, so the pool stores it once")

    def test_other_types_keep_no_screens(self) -> None:
        plan = self.docs / "acme-saved-carts-plan.bluedoc.json"
        h = build.load_history(build.history_path(plan))
        self.assertTrue(all("screens" not in r for r in h["revs"]))
        self.assertFalse(h.get("html"))


class PresentationTarget(unittest.TestCase):
    """`build.py new design --target presentation`: the stub deck, filled in, and its speaker notes."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.doc_path = self.tmp.dir / "deck.bluedoc.json"
        r = self.tmp.run("build.py", "new", "design", self.doc_path, "--target", "presentation")
        self.assertEqual(r.returncode, 0, r.stderr)
        # every <<placeholder>> filled, as the agent would
        raw = build.PLACEHOLDER.sub("Acme Fit launch", self.doc_path.read_text(encoding="utf-8"))
        self.doc_path.write_text(raw, encoding="utf-8")
        self.doc = load_json(self.doc_path)

    def check(self, doc: dict):
        self.doc_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return self.tmp.run("build.py", self.doc_path, "--check")

    def test_the_stub_deck_is_three_slides_in_a_row_and_builds_clean(self) -> None:
        board = board_of(self.doc)
        self.assertEqual(board["targets"], ["presentation"])
        self.assertEqual([(a["id"], a["device"]) for a in board["artboards"]],
                         [("title", "slide"), ("content", "slide"), ("closing", "slide")])
        self.assertEqual(build.DEVICES["slide"], {"w": 1920, "h": 1080, "safe": [0, 0, 0, 0]})
        layout = build.board_layout(board)
        self.assertEqual([layout[k][:2] for k in ("title", "content", "closing")], [(0, 0), (2000, 0), (4000, 0)])
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


class DeckExample(unittest.TestCase):
    """The bundled deck, acme-fit-deck: five hi-fi plain-kit slides in one row, notes on some, one revision."""

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
        board = board_of(doc)
        self.assertEqual(board["targets"], ["presentation"])
        self.assertFalse(board.get("frameworks"), "the deck must need nothing the reader provides")
        arts = board["artboards"]
        self.assertEqual([a["id"] for a in arts], ["title", "shipped", "actives", "quote", "ask"])
        self.assertEqual({(a["device"], a["fidelity"], a.get("framework", board["framework"])) for a in arts},
                         {("slide", "hifi", "plain")})
        self.assertGreaterEqual(sum(bool(a.get("notes")) for a in arts), 2)
        layout = build.board_layout(board)
        self.assertEqual({layout[a["id"]][1] for a in arts}, {0}, "the deck lays out in one row")
        html = "".join((EXAMPLES / f"{self.STEM}.design" / f"{a['id']}.html").read_text(encoding="utf-8") for a in arts)
        for cls in ("slide-cols", "slide-big", "slide-quote"):
            self.assertIn(cls, html)
        h = load_json(EXAMPLES / f"{self.STEM}.bluedoc.history.json")
        self.assertEqual([r["rev"] for r in h["revs"]], ["A"])
        self.assertEqual(h["revs"][0]["screens"], build.screen_hashes(doc, doc_path))


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


if __name__ == "__main__":
    unittest.main()
