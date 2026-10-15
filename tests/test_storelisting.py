"""The storelisting doc type: the store rules file, listing.py's checks, the contract, `new storelisting`, `patch
field:`, the page's device sections against listing.py's (under node), the home card and the shot screen route.
The browser tests (BLUEDOC_BROWSER_TESTS=1) drive the platform pages: platform and locale switch, fallbacks, counters,
the order and section drafts and the pins on a shot and on a field."""
from __future__ import annotations

import copy
import json
import shutil
import struct
import subprocess
import unittest
import zlib

from _support import SKILL, Server, TempHome, load_json
from test_page_state import CHROME, ChromePage

import build
import listing

NODE = shutil.which("node")
GEO = SKILL / "assets" / "board-geo.js"
STEM = "acme-fit-listing"


def png(w: int, h: int) -> bytes:
    """A w × h RGB PNG (one IDAT of zero rows)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\0" + b"\0" * 3 * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def report(doc: dict, doc_path=None) -> build.Report:
    rep = build.Report()
    listing.validate_listing(rep, doc, doc_path)
    return rep


class StoreRules(unittest.TestCase):
    """assets/store-rules.json: every rule sourced, every size consistent with how the page draws it."""

    def setUp(self) -> None:
        self.rules = listing.load_rules()

    def test_the_rules_file_checks_clean(self) -> None:
        self.assertEqual(listing.rules_problems(self.rules), [])

    def test_every_rule_names_a_known_source(self) -> None:
        known = set(self.rules["sources"])
        for kind in ("sets", "assets", "text", "video", "variants", "styles"):
            for r in self.rules.get(kind) or []:
                with self.subTest(kind=kind, rule=r.get("id") or r.get("kind")):
                    srcs = r.get("sources") or [r.get("source")]
                    self.assertTrue(srcs and all(s in known for s in srcs), srcs)

    def test_every_drawn_set_is_an_accepted_size_and_a_multiple_of_its_scale(self) -> None:
        for kind in ("sets", "assets"):
            for r in self.rules[kind]:
                if "author" not in r:
                    continue
                with self.subTest(rule=r["id"]):
                    w, h = r["author"]
                    self.assertIsNone(listing.size_problem(r, w, h))
                    self.assertEqual((w % r["scale"], h % r["scale"]), (0, 0))
                    fw, fh = listing.frame_size(r)
                    self.assertEqual((fw * r["scale"], fh * r["scale"]), (w, h))

    def test_a_ui_viewport_keeps_its_frame_proportions_portrait_or_landscape(self) -> None:
        for r in self.rules["sets"]:
            if "ui" in r:
                with self.subTest(rule=r["id"]):
                    fw, fh = listing.frame_size(r)
                    uw, uh = r["ui"]
                    self.assertEqual(fw > fh, uw > uh)

    def test_a_broken_rule_is_reported(self) -> None:
        bad = copy.deepcopy(self.rules)
        bad["text"][0]["limit"] = 0
        bad["sets"][0].pop("source", None)
        bad["sets"][0].pop("sources", None)
        self.assertGreaterEqual(len(listing.rules_problems(bad)), 2)

    def test_play_needs_two_shots_and_apple_one_of_the_two_iphone_sets(self) -> None:
        plats = {p["id"]: p for p in self.rules["platforms"]}
        self.assertEqual(plats["play"]["minShots"], 2)
        sets = listing.by_id(self.rules, "sets")
        self.assertEqual(sets["appstore/iphone-69"]["required"], "either:appstore/iphone-69|appstore/iphone-65")
        self.assertEqual(sets["appstore/ipad"]["required"], "if:ipad")


class Measures(unittest.TestCase):
    def test_size_problem(self) -> None:
        rules = listing.load_rules()
        sets, assets = listing.by_id(rules, "sets"), listing.by_id(rules, "assets")
        self.assertIsNone(listing.size_problem(sets["appstore/iphone-69"], 1320, 2868))
        self.assertIsNotNone(listing.size_problem(sets["appstore/iphone-69"], 1000, 2000))
        self.assertIsNone(listing.size_problem(assets["play/feature"], 1024, 500))
        self.assertIsNotNone(listing.size_problem(assets["play/feature"], 1024, 512))
        phone = sets["play/phone"]
        self.assertIsNone(listing.size_problem(phone, 1080, 1920))
        self.assertIsNotNone(listing.size_problem(phone, 300, 600), "under Play's 320 px side")
        self.assertIsNotNone(listing.size_problem(phone, 1080, 2500), "past Play's 2:1 aspect")

    def test_text_counts_code_points_or_utf8_bytes(self) -> None:
        self.assertEqual(listing.text_count("fútbol,ñ", "chars"), 8)
        self.assertEqual(listing.text_count("fútbol,ñ", "bytes"), 10)
        self.assertEqual(listing.text_count("🏃", "chars"), 1)

    def test_png_info_reads_the_header(self) -> None:
        self.assertEqual(listing.png_info(png(4, 3))["w"], 4)
        self.assertEqual(listing.png_info(png(4, 3))["h"], 3)
        self.assertFalse(listing.png_info(png(4, 3))["trns"])
        self.assertIsNone(listing.png_info(b"GIF89a" + b"\0" * 40))

    def test_youtube_one_video_only(self) -> None:
        for ok in ("https://www.youtube.com/watch?v=abcdefghijk", "https://youtu.be/abcdefghijk"):
            self.assertIsNone(listing.youtube_problem(ok), ok)
        for bad in ("https://www.youtube.com/watch?v=abcdefghijk&list=PL1", "https://youtu.be/abcdefghijk?t=30",
                    "https://www.youtube.com/@acme", "https://vimeo.com/123456", "ftp://youtu.be/abcdefghijk"):
            self.assertIsNotNone(listing.youtube_problem(bad), bad)


class Listing(unittest.TestCase):
    """validate_listing and the contract on the example and its breakages."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.path = self.docs / f"{STEM}.bluedoc.json"
        self.doc = load_json(self.path)
        self.lb = listing.listing_of(self.doc)

    def errors(self, doc: dict | None = None) -> list[str]:
        return report(doc or self.doc, self.path).errors

    def test_the_example_builds_clean(self) -> None:
        r = self.tmp.run("build.py", self.path, "--check")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("WARN", r.stdout + r.stderr)
        self.assertEqual(build.check_contract(self.doc), [])

    def test_the_contract_wants_one_listing_and_a_board_of_shots(self) -> None:
        d = copy.deepcopy(self.doc)
        listing.listing_of(d)["type"] = "text"
        self.assertTrue(listing.contract(d))
        d = copy.deepcopy(self.doc)
        listing.shots_of(d)[0]["device"] = "phone"
        self.assertTrue(listing.contract(d))
        d = copy.deepcopy(self.doc)
        d["meta"]["type"] = "storelisting"
        self.assertEqual(build.check_contract(d), [])

    def test_unknown_ids_are_errors(self) -> None:
        cases = {
            "platform": lambda lb, arts: lb.__setitem__("platforms", ["play", "itunes"]),
            "row": lambda lb, arts: lb.__setitem__("rows", ["phone", "fridge"]),
            "set": lambda lb, arts: arts[0].__setitem__("sets", ["play/phone", "play/fridge"]),
            "asset": lambda lb, arts: next(a for a in arts if a["device"] == "asset").__setitem__("asset", "play/poster"),
            "style": lambda lb, arts: lb.__setitem__("style", {"message": "l1", "layout": "l1"}),
            "text field": lambda lb, arts: lb["text"]["en-US"]["play"].__setitem__("tagline", "x"),
            "locale": lambda lb, arts: lb["strings"].__setitem__("fr-FR", {"today.title": "x"}),
            "palette role": lambda lb, arts: lb["brand"]["palette"].__setitem__("glow", "#fff"),
            "palette colour": lambda lb, arts: lb["brand"]["palette"].__setitem__("bg", "blue"),
            "mt key": lambda lb, arts: lb["mt"].__setitem__("es-ES", ["strings.nope"]),
            "youtube": lambda lb, arts: lb["video"].__setitem__("play", "https://youtu.be/abcdefghijk?t=4"),
            "order": lambda lb, arts: lb.__setitem__("order", {"play/phone": ["watch-rings"]}),
            "platform not listed": lambda lb, arts: lb.__setitem__("platforms", ["appstore"]),
        }
        for name, f in cases.items():
            with self.subTest(case=name):
                d = copy.deepcopy(self.doc)
                f(listing.listing_of(d), listing.shots_of(d))
                self.assertTrue(self.errors(d), name)

    def test_more_than_three_previews_per_row_is_an_error(self) -> None:
        (self.docs / "media").mkdir(exist_ok=True)
        (self.docs / "media" / "p.mp4").write_bytes(b"\0")
        d = copy.deepcopy(self.doc)
        listing.listing_of(d)["video"]["appstore"] = [{"src": "media/p.mp4", "row": "phone"}] * 3
        self.assertEqual(self.errors(d), [])
        listing.listing_of(d)["video"]["appstore"] = [{"src": "media/p.mp4", "row": "phone"}] * 4
        self.assertTrue(self.errors(d))

    def test_an_image_shot_is_a_png_inside_the_listing_folder(self) -> None:
        folder = listing.listing_dir(self.path)
        folder.mkdir(exist_ok=True)   # the example has its captures there
        (folder / "up.png").write_bytes(png(1320, 2868))
        (folder / "up.jpg.png").write_bytes(b"not a png at all, just bytes")
        (self.docs / "out.png").write_bytes(png(1320, 2868))
        for src, ok in ((f"{folder.name}/up.png", True), ("out.png", False), (f"{folder.name}/../out.png", False),
                        (f"{folder.name}/up.jpg.png", False), (f"{folder.name}/gone.png", False)):
            with self.subTest(src=src):
                d = copy.deepcopy(self.doc)
                build.board_of(d)["artboards"].append({"id": "up", "title": "Upload", "device": "shot", "sets": ["appstore/iphone-69"],
                                            "src": src})
                self.assertEqual(not self.errors(d), ok, self.errors(d))

    def test_a_required_text_missing_in_the_default_locale_warns(self) -> None:
        d = copy.deepcopy(self.doc)
        del listing.listing_of(d)["text"]["en-US"]["play"]["short"]
        rep = report(d, self.path)
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("short" in w for w in rep.warnings), rep.warnings)

    def test_a_caption_key_without_a_default_string_warns(self) -> None:
        d = copy.deepcopy(self.doc)
        listing.listing_of(d)["strings"]["en-US"].pop("today.title")
        listing.listing_of(d)["mt"] = {}
        rep = report(d, self.path)
        self.assertTrue(any("today.title" in w for w in rep.warnings), rep.warnings)

    def test_stale_rules_warn(self) -> None:
        rules = copy.deepcopy(listing.load_rules())
        rules["accessed"] = "2000-01-01"
        rep = build.Report()
        listing.validate_listing(rep, self.doc, self.path, rules)
        self.assertTrue(rep.warnings)

    def test_captures_are_fresh_only_with_their_recipes_hash(self) -> None:
        folder = listing.listing_dir(self.path) / "captures"
        folder.mkdir(parents=True, exist_ok=True)
        shot = next(a for a in listing.shots_of(self.doc) if a["device"] == "shot")
        base = f"{folder.parent.name}/captures/"
        rows = [{"shot": shot["id"], "target": "android-phone", "locale": "en-US", "file": base + "a.png",
                 "recipe": listing.recipe_hash(shot.get("recipe"))},
                {"shot": shot["id"], "target": "iphone-69", "locale": "en-US", "file": base + "b.png", "recipe": "0" * 16},
                {"shot": shot["id"], "target": "iphone", "locale": "en-US", "file": "../x.png", "recipe": "0" * 16},
                {"shot": "nope", "target": "iphone", "locale": "en-US", "file": base + "c.png"}]
        (folder / "captures.json").write_text(json.dumps({"captures": rows}), encoding="utf-8")
        got = listing.captures(self.doc, self.path)
        self.assertEqual(set(got), {shot["id"]})
        self.assertTrue(got[shot["id"]]["android-phone"]["en-US"]["fresh"])
        self.assertFalse(got[shot["id"]]["iphone-69"]["en-US"]["fresh"])
        self.assertNotIn("iphone", got[shot["id"]])


class Sections(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = listing.load_rules()
        self.doc = load_json(SKILL / "examples" / f"{STEM}.bluedoc.json")
        self.lb = listing.listing_of(self.doc)
        self.arts = listing.shots_of(self.doc)

    def test_rows_follow_the_rules_order_and_order_puts_its_ids_first(self) -> None:
        lb = {**self.lb, "rows": ["tablet", "phone"], "order": {"appstore/iphone-69": ["workout"]}}
        out = listing.sections(lb, self.arts, self.rules, "appstore", "en-US")
        self.assertEqual([r["row"] for r in out], ["phone", "tablet"])
        s = next(s for r in out for s in r["sets"] if s["set"] == "appstore/iphone-69")
        self.assertEqual(s["shots"][0], "workout")

    def test_an_upload_of_another_locale_is_left_out(self) -> None:
        arts = self.arts + [{"id": "up", "device": "shot", "sets": ["play/phone"], "locale": "es-ES", "src": "x.listing/a.png"}]
        def shots(loc):
            return next(s for r in listing.sections(self.lb, arts, self.rules, "play", loc) for s in r["sets"]
                        if s["set"] == "play/phone")["shots"]
        self.assertIn("up", shots("es-ES"))
        self.assertNotIn("up", shots("en-US"))

    @unittest.skipUnless(NODE, "node not installed")
    def test_the_page_lays_out_the_same_sections(self) -> None:
        cases = []
        for plat in ("play", "appstore"):
            for loc in ("en-US", "es-ES"):
                for lb in (self.lb, {**self.lb, "rows": ["phone"]}, {**self.lb, "watchFace": True, "rows": ["watch", "phone", "tablet", "tv"]},
                           {**self.lb, "order": {"play/phone": ["streak", "today"], "appstore/iphone-69": ["nope", "workout"]}}):
                    cases.append([lb, self.arts, plat, loc])
        js = ("const {geo, rules, cases} = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
              "const G = new Function(geo + '\\nreturn BoardGeo;')();"
              "process.stdout.write(JSON.stringify(cases.map(([lb, a, p, l]) => G.listingSections(lb, a, rules, p, l))));")
        r = subprocess.run([NODE, "-e", js], input=json.dumps({"geo": GEO.read_text(encoding="utf-8"), "rules": self.rules, "cases": cases}),
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        want = [listing.sections(lb, a, self.rules, p, l) for lb, a, p, l in cases]
        self.assertEqual(json.loads(r.stdout), want)


class Commands(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.path = self.docs / f"{STEM}.bluedoc.json"

    def test_new_storelisting_scaffolds_a_doc_that_only_lacks_its_placeholders(self) -> None:
        out = self.tmp.dir / "store" / "acme.bluedoc.json"
        r = self.tmp.run("build.py", "new", "storelisting", out, "--title", "Acme Fit listing")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = load_json(out)
        self.assertEqual(doc["meta"]["type"], "storelisting")
        self.assertEqual(build.check_contract(doc), [])
        for a in listing.shots_of(doc):
            if a["device"] == "shot":
                self.assertTrue((out.parent / "acme.design" / f"{a['id']}.html").is_file())
            elif a["device"] == "icons":
                self.assertTrue((out.parent / "acme.design" / a["id"] / "fg.svg").is_file())
        r = self.tmp.run("build.py", out, "--check")
        self.assertNotEqual(r.returncode, 0)
        errs = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith("ERROR")]
        self.assertTrue(errs and all("<<" in l or "placeholder" in l.lower() for l in errs), errs)

    def test_patch_field_sets_prints_and_deletes(self) -> None:
        key = "field:es-ES/play/short"
        r = self.tmp.run("build.py", "patch", self.path, key, "--set", "short=Tu semana, en un vistazo", "--no-bump")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(listing.listing_of(load_json(self.path))["text"]["es-ES"]["play"]["short"], "Tu semana, en un vistazo")
        r = self.tmp.run("build.py", "patch", self.path, key)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("24", r.stdout)   # its count
        self.assertIn("80", r.stdout)   # Play's short description limit
        r = self.tmp.run("build.py", "patch", self.path, "field:es-ES/strings/today.title", "--delete", "--no-bump")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("today.title", listing.listing_of(load_json(self.path))["strings"]["es-ES"])
        r = self.tmp.run("build.py", "patch", self.path, "field:es-ES/strings/today.title", "--delete", "--no-bump")
        self.assertNotEqual(r.returncode, 0, "deleting a missing field")

    def test_patch_field_refuses_unknown_names(self) -> None:
        for key in ("field:fr-FR/play/short", "field:es-ES/itunes/name", "field:es-ES/play/tagline", "field:es-ES/strings/a b"):
            with self.subTest(key=key):
                r = self.tmp.run("build.py", "patch", self.path, key, "--set", "x=y", "--no-bump")
                self.assertEqual(r.returncode, 2, r.stderr)
        doc = load_json(self.docs / "acme-orders.bluedoc.json")
        with self.assertRaises(build.PatchError):
            build.resolve_key(doc, "field:en-US/play/name")


class Served(unittest.TestCase):
    """The home card and the shot screen route."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = TempHome()
        cls.docs = cls.tmp.copy_examples()
        assert cls.tmp.run("serve.py", "add", cls.docs).returncode == 0
        cls.server = Server(cls.tmp)
        cls.server.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls.tmp.cleanup()

    def test_the_home_card_counts_each_sets_shots(self) -> None:
        status, raw = self.server.req("GET", "/__bluedoc/index.json", headers={"X-Bluedoc": "1"})
        self.assertEqual(status, 200)
        d = next(d for r in json.loads(raw)["roots"] for d in r["docs"] if d["path"].endswith(f"{STEM}.bluedoc.json"))
        self.assertEqual(d["type"], "storelisting")
        doc = load_json(self.docs / f"{STEM}.bluedoc.json")
        lb, rules = listing.listing_of(doc), listing.load_rules()
        want = {p: [{"row": r["row"], "sets": [[s["set"], len(s["shots"])] for s in r["sets"]]}
                    for r in listing.sections(lb, listing.shots_of(doc), rules, p, lb["locales"][0])] for p in lb["platforms"]}
        self.assertEqual(d["card"], {"platforms": want})

    def test_a_shot_is_served_in_the_shot_kit_with_its_data(self) -> None:
        base = self.server.url_for(self.docs / f"{STEM}.bluedoc.json").rsplit("/", 1)[0]
        status, raw = self.server.req("GET", f"{base}/{STEM}.design/today.html")
        self.assertEqual(status, 200, raw[:300])
        page = raw.decode()
        self.assertIn('id="bd-shot-data"', page)
        self.assertIn("shot.js", page)
        start = page.index('id="bd-shot-data"')
        data = json.loads(page[page.index(">", start) + 1:page.index("</script>", start)])
        self.assertIn("es-ES", data["strings"])
        rules = listing.by_id(listing.load_rules(), "sets")
        for sid, s in data["sets"].items():
            self.assertEqual((s["w"], s["h"]), listing.frame_size(rules[sid]))
            self.assertEqual((s["uiW"], s["uiH"]), listing.ui_size(rules[sid]))


LST = "BP.listing()"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class PlatformPages(ChromePage):
    def setUp(self) -> None:
        super().setUp()
        self.doc_path = self.docs / f"{STEM}.bluedoc.json"
        self.url = self.server.url_for(self.doc_path)

    def page(self):
        t = self.open(self.url)
        t.wait_for("!!document.querySelector('.bd-lst-sec')")
        return t

    def save(self, doc: dict) -> None:
        self.doc_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    def test_platform_and_locale_switch_and_survive_in_the_hash(self) -> None:
        t = self.page()
        self.assertEqual(t.ev(LST)["platform"], "play")
        t.ev("BP.listing({platform: 'appstore', locale: 'es-ES'})")
        t.wait_for("location.hash === '#appstore/es-ES'")
        t.ev("window.__bdLeft = true; location.reload()")   # the hash alone: same URL, so reload
        t.wait_for("!window.__bdLeft && document.readyState === 'complete' && !!window.BP")
        t.wait_for("!!document.querySelector('.bd-lst-sec')")
        got = t.ev(LST)
        self.assertEqual((got["platform"], got["locale"]), ("appstore", "es-ES"))
        sets = [s["set"] for r in got["sections"] for s in r["sets"]]
        self.assertTrue(sets and all(s.startswith("appstore/") for s in sets), sets)
        doc = load_json(self.doc_path)
        want = listing.sections(listing.listing_of(doc), listing.shots_of(doc), listing.load_rules(), "appstore", "es-ES")
        self.assertEqual([{"row": r["row"], "sets": [{"set": s["set"], "shots": s["shots"]} for s in r["sets"]]} for r in got["sections"]
                          if r["row"] != "shared"],
                         want)

    def test_counters_mt_and_fallbacks(self) -> None:
        t = self.page()
        t.ev("BP.listing({platform: 'appstore', locale: 'es-ES'})")
        lb = listing.listing_of(load_json(self.doc_path))
        fields = {f["field"]: f for f in t.ev(LST)["fields"]}
        rules = listing.text_rules(listing.load_rules(), "appstore")
        for f, v in lb["text"]["es-ES"]["appstore"].items():
            k = f"es-ES/appstore/{f}"
            self.assertIn(str(listing.text_count(v, rules[f]["unit"])), fields[k]["count"], k)
            self.assertFalse(fields[k]["fallback"], k)
        for m in lb["mt"]["es-ES"]:
            plat, _, f = m.partition(".")
            if plat == "appstore":
                self.assertTrue(fields[f"es-ES/appstore/{f}"]["mt"], m)
        for f in lb["text"]["en-US"]["appstore"]:
            if f not in lb["text"]["es-ES"]["appstore"]:
                self.assertTrue(fields[f"es-ES/appstore/{f}"]["fallback"], f)

    def test_an_over_limit_text_is_flagged_and_counted_in_checks(self) -> None:
        doc = load_json(self.doc_path)
        listing.listing_of(doc)["text"]["en-US"]["play"]["short"] = "x" * 81
        self.save(doc)
        t = self.page()
        got = t.ev(LST)
        self.assertTrue(next(f for f in got["fields"] if f["field"] == "en-US/play/short")["over"])
        self.assertFalse(next(f for f in got["fields"] if f["field"] == "en-US/play/name")["over"])
        self.assertTrue(any(k == "err" for k, _ in got["checks"]), got["checks"])

    def test_turning_on_a_section_is_a_draft_sent_with_its_patch_command(self) -> None:
        doc = load_json(self.doc_path)
        listing.listing_of(doc)["rows"] = ["phone", "tablet"]
        self.save(doc)
        t = self.page()
        off = [o["row"] for o in t.ev(LST)["off"]]
        self.assertIn("watch", off)
        self.assertNotIn("phone", off)
        t.ev("document.querySelector('.bd-lst-off[data-row=\"watch\"] button').click()")
        t.wait_for("BP.listing().sections.some(s => s.row === 'watch')")
        self.send_changes(t, "1")
        out = self.reply(self.doc_path)
        self.assertIn("block:", out)
        self.assertIn('"rows"', out)
        self.assertIn("watch", out)


if __name__ == "__main__":
    unittest.main()
