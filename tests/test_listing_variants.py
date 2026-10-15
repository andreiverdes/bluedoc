"""A storelisting's variants, store preview and ads (M5): each kind's limit and what it may change (PPO text and a
watch swap refused, an SLE's text only in its locale), the variant's sections in Python and the page alike, the
export's variants/ and ads/ folders, the ads checks and an ads asset uploaded. The browser tests
(BLUEDOC_BROWSER_TESTS=1): the variant tabs, Compare to default, the store preview, the Ads view, and Approve with
the variants' picks."""
from __future__ import annotations

import base64
import copy
import json
import shutil
import subprocess
import unittest

from _support import Server, SKILL, TempHome, load_json
from test_page_state import CHROME, ChromePage
from test_storelisting import png

import listing

STEM = "acme-fit-listing"
GEO = SKILL / "assets" / "board-geo.js"
NODE = shutil.which("node")
LST = "BP.listing()"


def example() -> dict:
    return load_json(SKILL / "examples" / f"{STEM}.bluedoc.json")


def errors(doc: dict, path=None) -> list[dict]:
    return [f for f in listing.store_checks(doc, path) if f["level"] == "err"]


def artboards(doc: dict) -> list[dict]:
    """The board's artboards list itself (listing.shots_of returns a copy)."""
    return next(b for s in doc["sections"] for b in s["blocks"] if b["type"] == "board")["artboards"]


class Report:
    def __init__(self) -> None:
        self.errs: list[tuple[str, str]] = []
        self.warns: list[tuple[str, str]] = []

    def err(self, where: str, msg: str) -> None:
        self.errs.append((where, msg))

    def warn(self, where: str, msg: str) -> None:
        self.warns.append((where, msg))


def shape_errors(doc: dict) -> list[tuple[str, str]]:
    """validate_listing's errors on the doc's shape (store_checks' findings left out)."""
    rep = Report()
    lb = listing.listing_of(doc)
    rules = listing.load_rules()
    listing.validate_variants(rep, "listing", lb, listing.shots_of(doc), rules, lb["platforms"], lb["locales"], lambda *_: None)
    return rep.errs


class Limits(unittest.TestCase):
    """Each kind's count and what it may change, from store-rules.json."""

    def setUp(self) -> None:
        self.doc = example()
        self.lb = listing.listing_of(self.doc)
        self.rules = listing.load_rules()

    def variant(self, vid: str) -> dict:
        return next(v for v in self.lb["variants"] if v["id"] == vid)

    def test_the_example_has_no_variant_errors(self) -> None:
        self.assertEqual(shape_errors(self.doc), [])
        self.assertEqual([f for f in errors(self.doc) if f["section"] in ("variants", "ads")], [])

    def test_each_kind_stops_at_its_store_maximum(self) -> None:
        for kind, platform in (("ppo", "appstore"), ("sle", "play"), ("cpp", "appstore"), ("csl", "play")):
            r = next(x for x in self.rules["variants"] if x["kind"] == kind)
            with self.subTest(kind=kind):
                doc = copy.deepcopy(self.doc)
                lb = listing.listing_of(doc)
                lb["variants"] = [{"id": f"{kind}-{i}", "platform": platform, "kind": kind, "style": {"layout": "l4"}} for i in range(r["max"])]
                self.assertFalse([f for f in errors(doc) if f["section"] == "variants"])
                lb["variants"].append({"id": f"{kind}-x", "platform": platform, "kind": kind, "style": {"layout": "l4"}})
                found = [f for f in errors(doc) if f["section"] == "variants"]
                self.assertEqual([f["source"] for f in found], [r["source"]])

    def test_a_ppo_cant_change_text(self) -> None:
        self.variant("lifestyle")["text"] = {"en-US": {"promo": "x"}}
        found = errors(self.doc)
        self.assertEqual([(f["source"], f["key"]) for f in found], [("A-PPO", "variant:lifestyle")])

    def test_a_cpp_changes_promo_and_keywords_only(self) -> None:
        v = self.variant("runners")
        v["text"]["en-US"]["keywords"] = "running,route"
        self.assertEqual(errors(self.doc), [])
        v["text"]["en-US"]["name"] = "Acme Run"
        self.assertEqual([(f["source"], f["key"]) for f in errors(self.doc)], [("A-CPP", "variant:runners")])

    def test_an_sle_changes_text_only_in_its_own_locale(self) -> None:
        v = self.variant("lifestyle-copy")
        v["text"]["es-ES"] = {"short": "Tu semana"}
        self.assertEqual([f["key"] for f in errors(self.doc)], ["variant:lifestyle-copy"])
        del v["text"]["es-ES"]
        del v["locale"]
        self.assertEqual([f["key"] for f in errors(self.doc)], ["variant:lifestyle-copy"])

    def test_a_ppo_never_touches_the_watch(self) -> None:
        arts = artboards(self.doc)
        arts.append({"id": "rings-b", "title": "Rings B", "device": "shot", "fidelity": "hifi", "variantOf": "watch-rings", "sets": ["appstore/watch"]})
        self.variant("lifestyle")["swap"]["watch-rings"] = "rings-b"
        self.assertEqual([(f["source"], f["key"]) for f in errors(self.doc)], [("A-PPO", "variant:lifestyle")])
        del self.variant("lifestyle")["swap"]["watch-rings"]
        self.variant("lifestyle")["order"] = {"appstore/watch": ["watch-rings"]}
        self.assertEqual([(f["source"], f["key"]) for f in errors(self.doc)], [("A-PPO", "variant:lifestyle")])

    def test_one_custom_product_page_per_ad_group(self) -> None:
        self.lb["variants"].append({"id": "riders", "platform": "appstore", "kind": "cpp", "adGroup": "Runners", "style": {"layout": "l4"}})
        found = errors(self.doc)
        self.assertEqual([(f["source"], f["section"]) for f in found], [("AA-VAR", "ads")])

    def test_a_malformed_variant_is_a_doc_error(self) -> None:
        cases = {
            "kind": lambda v: v.update(kind="abc"),
            "swap from": lambda v: v.update(swap={"nope": "today-lifestyle"}),
            "swap to": lambda v: v.update(swap={"today": "nope"}),
            "swap sets": lambda v: v.update(swap={"streak": "today-lifestyle"}) or next(
                a for a in listing.shots_of(doc) if a["id"] == "today-lifestyle").update(sets=["appstore/iphone"]),
            "order": lambda v: v.update(order={"play/phone": ["today"]}),
            "text": lambda v: v.update(text={"en-US": {"tagline": "x"}}),
            "locale": lambda v: v.update(locale="en-US"),
            "adGroup": lambda v: v.update(adGroup=""),
            "key": lambda v: v.update(url="x"),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                doc = copy.deepcopy(self.doc)
                change(next(v for v in listing.listing_of(doc)["variants"] if v["id"] == "runners"))
                self.assertTrue(shape_errors(doc))


class Sections(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = listing.load_rules()
        self.doc = example()
        self.lb = listing.listing_of(self.doc)
        self.arts = listing.shots_of(self.doc)

    def shots(self, platform: str, variant: dict | None, set_id: str) -> list[str]:
        return next(x["shots"] for r in listing.sections(self.lb, self.arts, self.rules, platform, "en-US", variant) for x in r["sets"] if x["set"] == set_id)

    def test_a_variant_shot_shows_only_where_a_swap_puts_it(self) -> None:
        v = {v["id"]: v for v in self.lb["variants"]}
        self.assertNotIn("today-lifestyle", self.shots("appstore", None, "appstore/iphone-69"))
        self.assertEqual(self.shots("appstore", v["lifestyle"], "appstore/iphone-69")[0], "today-lifestyle")
        self.assertEqual(self.shots("appstore", v["runners"], "appstore/iphone-69")[:2], ["workout", "today"])
        self.assertEqual(self.shots("play", v["lifestyle-copy"], "play/phone")[0], "today-lifestyle")

    def test_an_ab_treatment_is_l5_unless_it_names_a_layout(self) -> None:
        v = {v["id"]: v for v in self.lb["variants"]}
        self.assertEqual(listing.variant_style(self.rules, v["lifestyle"])["layout"], "l5")
        self.assertNotIn("layout", listing.variant_style(self.rules, v["runners"]))
        self.assertEqual(listing.variant_style(self.rules, {**v["lifestyle"], "style": {"layout": "l2"}})["layout"], "l2")

    def test_changes_count_swaps_orders_style_and_text(self) -> None:
        v = {v["id"]: v for v in self.lb["variants"]}
        self.assertEqual(len(listing.variant_changes(self.lb, self.arts, self.rules, v["lifestyle"], "en-US")), 2)
        self.assertEqual(len(listing.variant_changes(self.lb, self.arts, self.rules, v["lifestyle-copy"], "en-US")), 3)
        self.assertEqual(listing.variant_changes(self.lb, self.arts, self.rules, {"id": "x", "platform": "appstore", "kind": "cpp"}, "en-US"), [])

    @unittest.skipUnless(NODE, "node not installed")
    def test_the_page_lays_out_the_same_variant_sections(self) -> None:
        cases = []
        for v in [None, *self.lb["variants"], {"swap": {"today": "streak"}, "order": {"play/phone": ["streak", "nope"]}}, {"swap": {"today": "ghost"}}]:
            for plat in ("play", "appstore"):
                for loc in ("en-US", "es-ES"):
                    cases.append([self.lb, self.arts, plat, loc, v])
        js = ("const {geo, rules, cases} = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
              "const G = new Function(geo + '\\nreturn BoardGeo;')();"
              "process.stdout.write(JSON.stringify(cases.map(([lb, a, p, l, v]) => G.listingSections(lb, a, rules, p, l, v))));")
        r = subprocess.run([NODE, "-e", js], input=json.dumps({"geo": GEO.read_text(encoding="utf-8"), "rules": self.rules, "cases": cases}),
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), [listing.sections(lb, a, self.rules, p, l, v) for lb, a, p, l, v in cases])


class Export(unittest.TestCase):
    """export_plan: variants/<platform>-<kind>-<id>/ holds what each changes; ads/google and ads/apple."""

    def setUp(self) -> None:
        self.path = SKILL / "examples" / f"{STEM}.bluedoc.json"
        self.plan = listing.export_plan(load_json(self.path), self.path)

    def under(self, prefix: str) -> list[dict]:
        return [f for f in self.plan if f["path"].startswith(prefix)]

    def test_each_variant_has_its_folder_with_only_its_changes(self) -> None:
        ppo = self.under("variants/appstore-ppo-lifestyle/")
        self.assertTrue(ppo)
        self.assertTrue(all(f["variant"] == "lifestyle" and f["kind"] == "shot" and f["layout"] == "l5" for f in ppo))
        self.assertFalse([f for f in ppo if f.get("set") == "appstore/watch"], "a PPO never carries the watch")
        self.assertIn("variants/appstore-ppo-lifestyle/fastlane/screenshots/en-US/01-iphone-69-today-lifestyle.png", {f["path"] for f in ppo})
        cpp = self.under("variants/appstore-cpp-runners/")
        self.assertEqual({f["path"] for f in cpp if f["kind"] == "text"}, {"variants/appstore-cpp-runners/fastlane/metadata/en-US/promotional_text.txt"})
        self.assertFalse([f for f in cpp if f.get("set") == "appstore/watch"], "the watch set is the default page's")
        sle = self.under("variants/play-sle-lifestyle-copy/")
        self.assertEqual({f["locale"] for f in sle}, {"en-US"}, "a localized experiment exports its language only")
        self.assertIn("variants/play-sle-lifestyle-copy/fastlane/metadata/android/en-US/short_description.txt", {f["path"] for f in sle})
        for f in self.plan:
            if f["path"].startswith("variants/"):
                self.assertTrue(f["path"].split("/", 2)[2].startswith("fastlane/"), f["path"])

    def test_ads_go_to_their_folders(self) -> None:
        self.assertIn("ads/google/en-US/headlines.txt", {f["path"] for f in self.plan})
        self.assertEqual([f["asset"] for f in self.under("ads/google/en-US/") if f["kind"] == "asset"], ["play/ad-landscape"])
        self.assertEqual([f["asset"] for f in self.under("ads/apple/en-US/")], ["appstore/search"])
        self.assertFalse(self.under("ads/google/es-ES/1200x628"), "an en-US ad image stays in en-US")


class AdsChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.path = self.tmp.copy_examples() / f"{STEM}.bluedoc.json"
        self.doc = load_json(self.path)
        self.arts = artboards(self.doc)

    def test_ad_images_stop_at_twenty_per_locale(self) -> None:
        ad = next(a for a in self.arts if a["id"] == "ad-wide")
        self.arts.extend({**ad, "id": f"ad-{i}"} for i in range(19))
        self.assertFalse([f for f in errors(self.doc, self.path) if f["section"] == "ads"])
        self.arts.append({**ad, "id": "ad-20"})
        self.assertEqual([(f["source"], f["locales"]) for f in errors(self.doc, self.path) if f["section"] == "ads"], [("GA-APP", ["en-US"])])

    def test_an_apple_ads_creative_asset_only_warns(self) -> None:
        self.arts.append({"id": "ad-apple", "title": "Apple ad", "device": "asset", "asset": "appstore/ad", "fidelity": "hifi"})
        found = [f for f in listing.store_checks(self.doc, self.path) if f["key"] == "artboard:ad-apple"]
        self.assertEqual([(f["level"], f["source"]) for f in found], [("warn", "AA-CA")])

    def test_an_uploaded_ad_image_is_checked_like_a_shot(self) -> None:
        f = self.path.parent / f"{STEM}.listing/play/en-US/ad-landscape/01.png"
        f.parent.mkdir(parents=True)
        f.write_bytes(png(1200, 600))
        self.arts.append({"id": "ad-up", "title": "Ad upload", "device": "asset", "asset": "play/ad-landscape", "fidelity": "hifi",
                          "locale": "en-US", "src": f"{STEM}.listing/play/en-US/ad-landscape/01.png"})
        rep = Report()
        listing.validate_listing(rep, self.doc, self.path)
        self.assertEqual([e for e in rep.errs if ".src" in e[0]], [], "an ads asset may be a PNG beside the doc")
        self.assertEqual([(x["source"], x["key"]) for x in errors(self.doc, self.path)], [("GA-APP", "artboard:ad-up")])
        f.write_bytes(png(1200, 628))
        self.assertEqual(errors(self.doc, self.path), [])
        self.assertIn(f"{STEM}.listing/play/en-US/ad-landscape/01.png", {e.get("src") for e in listing.export_plan(self.doc, self.path)})


class AdsUpload(unittest.TestCase):
    """POST /__bluedoc/listing/upload takes an ads asset's id as its set."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = TempHome()
        cls.docs = cls.tmp.copy_examples()
        assert cls.tmp.run("serve.py", "add", cls.docs).returncode == 0
        cls.server = Server(cls.tmp)
        cls.server.start()
        cls.path = cls.docs / f"{STEM}.bluedoc.json"
        cls.url = cls.server.url_for(cls.path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls.tmp.cleanup()

    def upload(self, data: bytes, set_id: str, platform: str) -> tuple[int, dict]:
        body = {"path": self.url, "platform": platform, "locale": "en-US", "set": set_id, "slot": 1, "png": base64.b64encode(data).decode()}
        status, raw = self.server.req("POST", "/__bluedoc/listing/upload", json.dumps(body).encode(), {"Content-Type": "application/json", "X-Bluedoc": "1"})
        return status, json.loads(raw)

    def test_an_ad_image_is_checked_written_and_listed(self) -> None:
        status, ans = self.upload(png(1200, 600), "play/ad-landscape", "play")
        self.assertEqual((status, ans.get("source")), (400, "GA-APP"))
        self.assertFalse((listing.listing_dir(self.path) / "play/en-US/ad-landscape").exists())
        self.assertEqual(self.upload(png(1200, 628), "play/feature", "play")[0], 400, "only the ads' assets take uploads")
        status, ans = self.upload(png(1200, 628), "play/ad-landscape", "play")
        self.assertEqual(status, 200, ans)
        self.assertEqual(ans["file"], f"{STEM}.listing/play/en-US/ad-landscape/01.png")
        drafts = listing.uploads(load_json(self.path), self.path)
        self.assertEqual([(u["set"], u["asset"]) for u in drafts], [("play/ad-landscape", True)])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class VariantsInChrome(ChromePage):
    def setUp(self) -> None:
        super().setUp()
        self.doc_path = self.docs / f"{STEM}.bluedoc.json"
        self.url = self.server.url_for(self.doc_path)

    def page(self, frag: str):
        t = self.open(self.url)
        t.ev(f"window.__old = true; location.hash = {json.dumps(frag)}; location.reload()")
        t.wait_for("!window.__old && document.readyState === 'complete' && !!window.BP && !!document.querySelector('.bd-lst-main') && !!BP.listing()")
        return t

    def phone_shots(self, t) -> list[str]:
        return next(x["shots"] for s in t.ev(LST)["sections"] for x in s["sets"] if x["set"] == "appstore/iphone-69")

    def test_tabs_switch_the_page_to_the_variant(self) -> None:
        t = self.page("#appstore")
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-lst-vtab')].map(b => b.dataset.variant)"), ["default", "runners", "lifestyle"])
        self.assertEqual(self.phone_shots(t)[0], "today")
        t.ev("document.querySelector('.bd-lst-vtab[data-variant=lifestyle]').click()")
        t.wait_for(f"{LST}.variant === 'lifestyle'")
        self.assertEqual(self.phone_shots(t)[0], "today-lifestyle")
        self.assertTrue(t.ev(LST)["hash"].endswith("@lifestyle"))
        # the tiles mount lazily after the switch: wait until the 6.9" set's frames are named, then read them
        t.wait_for(f"{LST}.tiles.some(x => x.name && x.set === 'appstore/iphone-69')")
        names = [json.loads(x["name"][8:]) for x in t.ev(LST)["tiles"] if x["name"] and x["set"] == "appstore/iphone-69"]
        self.assertTrue(names and all(n["layout"] == "l5" for n in names), "a B treatment renders in L5")
        self.assertEqual(len(next(v for v in t.ev(LST)["variants"] if v["id"] == "lifestyle")["changes"]), 2)
        t2 = self.page("#appstore@lifestyle")
        self.assertEqual(t2.ev(LST)["variant"], "lifestyle", "the URL keeps the tab")
        t2.ev("document.querySelector('.bd-lst-tb [data-p=play]').click()")
        t2.wait_for(f"{LST}.platform === 'play'")
        self.assertIsNone(t2.ev(LST)["variant"], "another platform's page opens on its default")

    def test_compare_puts_the_default_beside_the_variant(self) -> None:
        t = self.page("#appstore@runners")
        t.ev("document.querySelector('.bd-lst-cmpbtn').click()")
        t.wait_for(f"{LST}.compare")
        rows = next(x["rows"] for s in t.ev(LST)["sections"] for x in s["sets"] if x["set"] == "appstore/iphone-69")
        self.assertEqual([(r["variant"], r["shots"][:2]) for r in rows], [("default", ["today", "workout"]), ("runners", ["workout", "today"])])
        watch = next(x["rows"] for s in t.ev(LST)["sections"] for x in s["sets"] if x["set"] == "appstore/watch")
        self.assertEqual(len(watch), 1, "a set the variant leaves alone shows once")
        promo = next(f for f in t.ev(LST)["fields"] if f["field"] == "en-US/appstore/promo")
        self.assertIn("Every run mapped", promo["value"])

    def test_store_preview_shows_each_platform_from_the_listing(self) -> None:
        t = self.page("#appstore")
        t.ev("document.querySelector('.bd-lst-tb [data-view=preview]').click()")
        t.wait_for(f"{LST}.preview.length === 2")
        pv = {p["kind"]: p for p in t.ev(LST)["preview"]}
        self.assertIn("Runs, rides and rest", pv["page"]["text"])
        self.assertEqual(pv["page"]["shots"][:3], ["today", "workout", "streak"])
        self.assertEqual(pv["search"]["shots"], ["search"], "the search results asset stands in for the shots")
        self.assertTrue(t.ev("document.querySelector('.bd-lst-pvnote').textContent.length > 0"))
        t.ev(f"BP.listing({{variant: 'lifestyle'}})")
        self.assertEqual(t.ev(LST)["preview"][0]["shots"][0], "today-lifestyle")
        t.ev("BP.listing({platform: 'play'})")
        pv = {p["kind"]: p for p in t.ev(LST)["preview"]}
        self.assertEqual(pv["page"]["shots"][0], "feature", "Play's video plays over the feature graphic first")
        self.assertIn("Acme Fit: Run, Ride, Rest", pv["search"]["text"])

    def test_the_ads_view_lists_campaign_text_images_and_ad_variations(self) -> None:
        t = self.page("#play")
        t.ev("BP.listing({view: 'ads'})")
        sets = {x["set"]: x for s in t.ev(LST)["sections"] for x in s["sets"]}
        self.assertEqual(sets["play/ad-landscape"]["shots"], ["ad-wide"])
        self.assertEqual(t.ev("document.querySelectorAll('[data-field=\"en-US/play/adHeadlines\"] li').length"), 3)
        self.assertEqual(sorted(s for s in sets if s), ["play/ad-landscape", "play/ad-portrait", "play/ad-square"])
        self.assertTrue(t.ev("!!document.querySelector('.bd-lst-upslot[data-set=\"play/ad-portrait\"]')"), "an empty ads asset takes a PNG")
        t.ev("BP.listing({platform: 'appstore'})")
        ads = t.ev("[...document.querySelectorAll('[data-ad]')].map(e => [e.dataset.ad, [...e.querySelectorAll('.bd-lst-shot')].map(s => s.dataset.ab)])")
        self.assertEqual(ads, [["default", ["today", "workout", "streak"]], ["runners", ["workout", "today", "streak"]]])

    def test_approve_carries_every_variants_picks(self) -> None:
        t = self.page("#appstore")
        dec = t.ev(LST)["decisions"]
        for v in ("runners", "lifestyle", "lifestyle-copy"):
            self.assertIn(f"style-{'play' if v == 'lifestyle-copy' else 'appstore'}-{v}-layout", dec)
        self.assertIn("`style-appstore-lifestyle-layout` → L5", dec)
        self.assertEqual(t.ev(LST)["approveSummary"]["variants"], 3)
        t.ev("document.querySelector('.bd-key.approve').click()")
        t.wait_for("!!document.querySelector('.bd-approve[open] .bp-btn.ok')")
        self.assertIn("lifestyle-copy", t.ev("document.querySelector('.bd-approve[open]').textContent"))
        t.ev("document.querySelector('.bd-approve[open] .bp-btn.ok').click()")
        self.toast(t, "approved")
        r = self.tmp.run("serve.py", "reply", self.doc_path, "--kind", "approval")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("style-play-lifestyle-copy-layout", r.stdout)
