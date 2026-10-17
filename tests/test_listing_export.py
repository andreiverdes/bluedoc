"""A storelisting checked, translated and exported (M4): the broken fixture fails each store rule once; `build.py
l10n` exports, imports (refusing an over-limit string) and accepts; the fastlane layout; the ZIP's PNGs against its
manifest.json; GET /__bluedoc/listing's guards; setKids. The browser tests (BLUEDOC_BROWSER_TESTS=1): the Checks tab
lists the build's findings; Accept MT is a draft whose readback runs; Export to… downloads a ZIP; Approve listing waits
for an upload or brand draft."""
from __future__ import annotations

import io
import json
import shlex
import shutil
import subprocess
import unittest
import zipfile

from _support import REPO, Server, TempHome, load_json, template_slice
from test_page_state import CHROME, ChromePage

import build
import listing

STEM = "acme-fit-listing"
BROKEN = REPO / "tests" / "fixtures" / "storelisting-broken.bluedoc.json"
NODE = shutil.which("node")
LST = "BP.listing()"


def copy_broken(dest: Path) -> Path:
    """The broken fixture with its screen files and upload, in dest."""
    for p in (BROKEN, BROKEN.with_name("storelisting-broken.design"), BROKEN.with_name("storelisting-broken.listing")):
        (shutil.copytree if p.is_dir() else shutil.copy2)(p, dest / p.name)
    return dest / BROKEN.name


def tree(*roots: Path) -> dict[str, tuple[int, int]]:
    """Every file under roots with its size and mtime: what a read must leave as it is."""
    return {str(f): (f.stat().st_size, f.stat().st_mtime_ns) for r in roots for f in r.rglob("*") if f.is_file()}


class BrokenFixture(unittest.TestCase):
    """tests/fixtures/storelisting-broken: each broken rule fails once, naming its platform, set, locale and source."""

    def test_each_broken_rule_fails_once(self) -> None:
        found = listing.store_checks(load_json(BROKEN), BROKEN)
        errs = [f for f in found if f["level"] == "err"]
        got = sorted(((tuple(f["platforms"]), f["set"], tuple(f["locales"]), f["source"], f["key"]) for f in errs), key=repr)
        self.assertEqual(got, sorted([
            (("appstore",), None, ("en-US",), "A-PVI", "field:en-US/appstore/keywords"),           # keywords at 101 bytes
            (("play",), "play/phone", ("en-US",), "G-PA", "section:play/phone"),                    # 9 phone shots
            (("appstore",), "appstore/ipad", ("en-US",), "A-SS", "section:appstore/tablet"),       # no iPad set
            (("appstore",), "appstore/iphone-69", ("en-US",), "A-SS", "artboard:alpha"),           # an alpha PNG
            (("play",), "play/wear", ("en-US",), "G-PA", "artboard:wear"),                          # a framed Wear shot
            (("appstore",), None, (), "A-PPO", None),                                               # 4 PPO treatments
        ], key=repr))

    def test_the_build_fails_on_them_and_still_draws_the_doc(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        r = tmp.run("build.py", BROKEN, "--check")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(sum(l.startswith("ERROR") for l in r.stderr.splitlines()), 6, r.stderr)
        rep = build.validate(load_json(BROKEN), BROKEN)
        self.assertEqual(rep.blocking, [], "store-rule errors don't keep the page from drawing")

    def test_fixing_one_rule_clears_only_its_error(self) -> None:
        doc = load_json(BROKEN)
        lb = listing.listing_of(doc)
        lb["text"]["en-US"]["appstore"]["keywords"] = "heart,rate,sleep"
        lb["variants"] = lb["variants"][:3]
        errs = [f for f in listing.store_checks(doc, BROKEN) if f["level"] == "err"]
        self.assertEqual(len(errs), 4)
        self.assertFalse(any(f["source"] in ("A-PVI", "A-PPO") for f in errs))


class L10n(unittest.TestCase):
    """`build.py l10n`: --export, --import --mt (whole-file refusal past a limit), --accept."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.path = self.tmp.copy_examples() / f"{STEM}.bluedoc.json"

    def l10n(self, *args: str) -> subprocess.CompletedProcess:
        return self.tmp.run("build.py", "l10n", self.path, *args)

    def lb(self) -> dict:
        return listing.listing_of(load_json(self.path))

    def test_export_lists_what_the_locale_lacks_with_its_limit(self) -> None:
        doc = load_json(self.path)
        del listing.listing_of(doc)["text"]["es-ES"]["play"]["full"]
        self.path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        r = self.l10n("--export", "es-ES")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        keys = {s["key"]: s for s in out["strings"]}
        self.assertIn("play.full", keys)
        self.assertEqual(keys["play.full"]["limit"], listing.text_rules(listing.load_rules(), "play")["full"]["limit"])
        self.assertNotIn("play.name", keys, "a string es-ES has, unchanged, isn't asked for")
        self.assertNotEqual(self.l10n("--export", "en-US").returncode, 0, "the default locale has nothing to translate")

    def test_import_marks_mt_and_bumps_the_rev(self) -> None:
        rev0 = load_json(self.path)["meta"]["rev"]
        f = self.tmp.dir / "es.json"
        f.write_text(json.dumps({"play.full": "Acme Fit muestra tu semana.", "appstore.promo": "Tu semana en una pantalla."}), encoding="utf-8")
        r = self.l10n("--import", "es-ES", str(f), "--mt")
        self.assertEqual(r.returncode, 0, r.stderr)
        lb = self.lb()
        self.assertEqual(lb["text"]["es-ES"]["play"]["full"], "Acme Fit muestra tu semana.")
        self.assertTrue({"play.full", "appstore.promo"} <= set(lb["mt"]["es-ES"]))
        self.assertNotEqual(load_json(self.path)["meta"]["rev"], rev0)

    def test_an_over_limit_string_refuses_the_whole_file(self) -> None:
        raw = self.path.read_bytes()
        limit = listing.text_rules(listing.load_rules(), "play")["short"]["limit"]
        f = self.tmp.dir / "es.json"
        f.write_text(json.dumps({"play.full": "Corto.", "play.short": "x" * (limit + 1)}), encoding="utf-8")
        r = self.l10n("--import", "es-ES", str(f), "--mt")
        self.assertEqual(r.returncode, 1)
        self.assertIn(str(limit + 1), r.stderr, "the refusal gives the string's count")
        self.assertEqual(self.path.read_bytes(), raw, "nothing is written")

    def test_accept_clears_the_mark_once(self) -> None:
        self.assertIn("play.short", self.lb()["mt"]["es-ES"])
        r = self.l10n("--accept", "es-ES", "play.short")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("play.short", self.lb().get("mt", {}).get("es-ES", []))
        raw = self.path.read_bytes()
        self.assertEqual(self.l10n("--accept", "es-ES", "play.short").returncode, 1, "a key that isn't marked")
        self.assertEqual(self.path.read_bytes(), raw)


class Layout(unittest.TestCase):
    """listing.export_plan: fastlane's supply and deliver folders (names from fastlane's source)."""

    def test_the_fastlane_layout(self) -> None:
        path = REPO / "skills" / "bluedoc" / "examples" / f"{STEM}.bluedoc.json"
        plan = listing.export_plan(load_json(path), path)
        paths = {f["path"] for f in plan}
        for loc in ("en-US", "es-ES"):
            for name in ("title.txt", "short_description.txt", "images/icon.png", "images/featureGraphic.png",
                         "images/phoneScreenshots/01-today.png", "images/tenInchScreenshots/01-today.png",
                         "images/wearScreenshots/01-watch-rings.png"):
                self.assertIn(f"fastlane/metadata/android/{loc}/{name}", paths)
            for name in ("name.txt", "subtitle.txt", "keywords.txt"):
                self.assertIn(f"fastlane/metadata/{loc}/{name}", paths)
            for name in ("01-iphone-69-today.png", "01-iphone-today.png", "01-ipad-today.png", "01-watch-watch-rings.png"):
                self.assertIn(f"fastlane/screenshots/{loc}/{name}", paths)
        self.assertIn("fastlane/metadata/android/en-US/changelogs/default.txt", paths)
        self.assertIn("fastlane/metadata/en-US/promotional_text.txt", paths)
        self.assertTrue(all(p.startswith(("fastlane/metadata/android/", "fastlane/metadata/", "fastlane/screenshots/", "extra/", "ads/", "variants/"))
                            for p in paths), paths)
        rules = listing.load_rules()
        sets = listing.by_id(rules, "sets")
        for f in plan:
            if f["kind"] == "shot":
                self.assertIsNone(listing.size_problem(sets[f["set"]], f["w"], f["h"]), f["path"])

    def test_png_rgb24_drops_alpha_and_keeps_the_size(self) -> None:
        data = (BROKEN.parent / "storelisting-broken.listing/appstore/en-US/iphone-69/01.png").read_bytes()
        self.assertEqual(listing.png_info(data)["colour"], 6)
        out = listing.png_info(listing.png_rgb24(data))
        self.assertEqual((out["w"], out["h"], out["colour"], out["trns"]), (1320, 2868, 2, False))


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the Chrome exports (BLUEDOC_CHROME: Chrome's path)")
class Zip(unittest.TestCase):
    """build.py --listing out.zip: every PNG is 24-bit RGB at its manifest's size, and the paths match it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = TempHome()
        path = cls.tmp.copy_examples() / f"{STEM}.bluedoc.json"
        cls.out = cls.tmp.dir / "out.zip"
        cls.r = cls.tmp.run("build.py", path, "--listing", cls.out, timeout=300)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_png_headers_match_the_manifest(self) -> None:
        self.assertEqual(self.r.returncode, 0, self.r.stderr)
        with zipfile.ZipFile(self.out) as z:
            man = json.loads(z.read("manifest.json"))
            names = set(z.namelist()) - {"manifest.json"}
            self.assertEqual(names, {f["path"] for f in man["files"]})
            pngs = [f for f in man["files"] if f["path"].endswith(".png")]
            self.assertGreater(len(pngs), 30)
            for f in pngs:
                info = listing.png_info(z.read(f["path"]))
                self.assertEqual((info["w"], info["h"], info["colour"], info["trns"]), (f["w"], f["h"], 2, False), f["path"])
            self.assertEqual(set(man["locales"]), {"en-US", "es-ES"})
            self.assertIn("es-ES", man["mt"])


class Route(unittest.TestCase):
    """GET /__bluedoc/listing: 400 on bad input, 501 without Chrome, and a read that writes nothing."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = TempHome()
        cls.docs = cls.tmp.copy_examples()
        assert cls.tmp.run("serve.py", "add", cls.docs).returncode == 0
        cls.tmp.env["BLUEDOC_CHROME"] = str(cls.tmp.dir / "no-chrome")
        cls.server = Server(cls.tmp)
        cls.server.start()
        cls.url = cls.server.url_for(cls.docs / f"{STEM}.bluedoc.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls.tmp.cleanup()

    def get(self, **q: str) -> tuple[int, bytes]:
        from urllib.parse import urlencode
        return self.server.req("GET", "/__bluedoc/listing?" + urlencode(q))

    def test_bad_input_is_400(self) -> None:
        plan = self.server.url_for(self.docs / "acme-saved-carts-plan.bluedoc.json")
        for q in ({"path": self.url, "format": "docx"}, {"path": plan, "format": "html"}, {"path": self.url, "format": "html", "rev": "ZZ"},
                  {"path": self.url, "format": "html", "platform": "play"}):
            with self.subTest(q=q):
                self.assertEqual(self.get(**q)[0], 400)
        self.assertEqual(self.get(path="/nowhere/x.bluedoc.json", format="html")[0], 404)

    def test_zip_and_pdf_need_chrome(self) -> None:
        for fmt in ("zip", "pdf"):
            self.assertEqual(self.get(path=self.url, format=fmt)[0], 501)

    def test_html_is_one_file_and_nothing_is_written(self) -> None:
        before = tree(self.docs, self.tmp.home)
        status, body = self.get(path=self.url, format="html")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body[:2000].lower())
        for fmt in ("zip", "pdf", "print"):
            self.get(path=self.url, format=fmt)
        after = tree(self.docs, self.tmp.home)
        self.assertEqual({k: v for k, v in after.items() if not k.endswith(("state.db", "state.db-wal", "state.db-shm", "server.log"))},
                         {k: v for k, v in before.items() if not k.endswith(("state.db", "state.db-wal", "state.db-shm", "server.log"))})


@unittest.skipUnless(NODE, "node not installed")
class SetKids(unittest.TestCase):
    def test_false_and_null_children_add_nothing(self) -> None:
        src = template_slice("// el's children as h() takes them", "function sv(tag")
        js = src + ("const el = { replaceChildren(...k) { this.kids = k; } };"
                    "setKids(el, 'a', false, null, ['b', false, [undefined, 'c']], 0);"
                    "process.stdout.write(JSON.stringify(el.kids));")
        r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ["a", "b", "c", 0])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ListingPage(ChromePage):
    def setUp(self) -> None:
        super().setUp()
        self.doc_path = self.docs / f"{STEM}.bluedoc.json"
        self.url = self.server.url_for(self.doc_path)

    def page(self, url: str, frag: str = "#play", side: str | None = None):
        t = self.open(url)
        t.ev(f"location.hash = {json.dumps(frag)}; location.reload()")
        t.wait_for("document.readyState === 'complete' && !!window.BP && !!document.querySelector('.bd-lst-sec') && !!BP.listing()")
        if side:
            t.ev("document.documentElement.classList.contains('bd-lp-open') || document.dispatchEvent(new KeyboardEvent('keydown', {key: '['}))")
            t.ev(f"document.querySelector('.bd-lp-tabs [data-v=\"{side}\"]').click()")
            t.wait_for(f"!document.getElementById('bd-lp-{side}').hidden && document.documentElement.classList.contains('bd-lp-open')")
        return t

    def approve_disabled(self, t) -> bool:
        return t.ev("document.querySelector('.bd-key.approve').disabled")

    def test_the_checks_tab_lists_the_builds_findings(self) -> None:
        path = copy_broken(self.docs)
        t = self.page(self.server.url_for(path), "#appstore", "checks")
        found = [f for f in listing.checks_page_data(load_json(path), path) if not f["platforms"] or "appstore" in f["platforms"]]
        got = t.ev("[...document.querySelectorAll('#bd-lp-checks .bd-lst-checks li')].map(li => [li.className, li.dataset.key || null])")
        self.assertEqual(sorted(got, key=repr), sorted([[f["level"], f["key"]] for f in found], key=repr))
        self.assertTrue(any(k == "err" for k, _ in got))
        for pane in (".bd-lst-clp", ".bd-lst-fsec"):
            texts = t.ev(f"(() => {{ const w = document.createTreeWalker(document.querySelector('{pane}'), NodeFilter.SHOW_TEXT), out = [];"
                         " while (w.nextNode()) out.push(w.currentNode.data.trim()); return out; })()")
            self.assertNotIn("false", texts, f"a `cond && h(…)` child drew as text in {pane}")
        # the tab is the left panel's, with its count of errors; the right panel holds Brief, Comments and Revisions
        ne = sum(f["level"] == "err" for f in found)
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-lp-tabs [data-v]')].map(b => b.dataset.v)"), ["text", "style", "colors", "checks"])
        self.assertEqual(t.ev("(n => [n.hidden, n.textContent, n.classList.contains('warn')])(document.querySelector('.bd-lp-tabs [data-v=checks] .n'))"), [False, str(ne), False])
        self.assertEqual(t.ev("document.querySelector('.bd-lp-tabs').getBoundingClientRect().height < 50"), True, "the four tabs keep one row")
        side = t.ev("BP.sidebar().available")
        self.assertTrue(side and side[0] == "brief" and set(side) <= {"brief", "comments", "revisions"}, side)
        self.assertEqual(t.ev("document.querySelectorAll('#bd-sp .bd-lst-pane, #bd-sp-style, #bd-sp-colors, #bd-sp-checks, #bd-sp-text').length"), 0)
        # a finding with a key shows its shot
        t.ev("document.querySelector('#bd-lp-checks li[data-key=\"artboard:alpha\"] button').click()")
        t.wait_for("!!document.querySelector('.bd-lst-shot[data-ab=\"alpha\"].flash')")
        # a reload keeps the tab
        t.ev("window.__before = 1; location.reload()")
        t.wait_for("!window.__before && document.readyState === 'complete' && !!window.BP && !!document.querySelector('.bd-lst-sec') && !!BP.listing()")
        self.assertEqual(t.ev("[document.getElementById('bd-lp-checks').hidden, document.querySelector('.bd-lp-tabs [data-v=checks]').getAttribute('aria-checked')]"), [False, "true"])

    def test_accept_mt_is_a_draft_whose_command_clears_the_badge(self) -> None:
        t = self.page(self.url, "#play/es-ES")
        t.wait_for("!!document.querySelector('[data-accept=\"play.short\"]')")
        self.assertTrue(next(f for f in t.ev(LST)["fields"] if f["field"] == "es-ES/play/short")["mt"])
        t.ev("document.querySelector('[data-accept=\"play.short\"]').click()")
        t.wait_for("!document.querySelector('[data-accept=\"play.short\"]')")
        self.assertFalse(self.approve_disabled(t), "an MT string only warns")
        self.send_changes(t, "1")
        out = self.reply(self.doc_path)
        cmd = next(l for l in out.splitlines() if l.startswith("build.py l10n"))
        args = shlex.split(cmd)[3:]
        self.assertEqual(args[:3], ["--accept", "es-ES", "play.short"])
        r = self.tmp.run("build.py", "l10n", self.doc_path, *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        t2 = self.page(self.url, "#play/es-ES")
        self.assertFalse(next(f for f in t2.ev(LST)["fields"] if f["field"] == "es-ES/play/short")["mt"])
        self.assertTrue(t2.ev("!!document.querySelector('[data-accept=\"appstore.subtitle\"]') || !!document.querySelector('[data-accept=\"strings.workout.title\"]')"))

    def test_export_to_downloads_a_zip(self) -> None:
        t = self.page(self.url)
        t.ev("window.__blobs = []; (o => { URL.createObjectURL = b => { __blobs.push(b); return o.call(URL, b); }; })(URL.createObjectURL)")
        t.ev("document.querySelector('.bd-lst-btb .bd-expb').click()")
        t.wait_for("!document.querySelector('.bd-lst-btb .bd-expm').hidden")
        t.ev("document.querySelector('.bd-lst-btb .bd-expm [data-format=\"zip\"]').click()")
        t.wait_for("__blobs.length > 0", 240)
        head = t.ev("__blobs[0].slice(0, 4).arrayBuffer().then(b => [...new Uint8Array(b)])")
        self.assertEqual(bytes(head), b"PK\x03\x04")
        b64 = t.ev("__blobs[0].arrayBuffer().then(b => { let s = ''; const u = new Uint8Array(b); for (let i = 0; i < u.length; i += 32768) s += String.fromCharCode(...u.subarray(i, i + 32768)); return btoa(s); })")
        import base64
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(b64))) as z:
            self.assertIn("manifest.json", z.namelist())
        self.assertEqual(t.ev(f"{LST}.approveBlocks"), [])

    def test_approve_waits_for_an_upload_or_brand_draft(self) -> None:
        from test_listing_capture import free_a_slot
        free_a_slot(self.doc_path, "appstore/iphone-69")
        t = self.page(self.url, "#appstore/es-ES", "colors")
        t.wait_for("!!document.querySelector('.bd-key.approve')")
        self.assertFalse(self.approve_disabled(t))
        # a brand draft
        t.ev("(i => { i.value = '#7c3aed'; i.dispatchEvent(new Event('input')); })(document.querySelector('.bd-lst-role[data-role=\"bg\"] .hx'))")
        t.wait_for(f"{LST}.brand.draft && {LST}.approveBlocks.length > 0")
        self.assertTrue(self.approve_disabled(t))
        t.ev("[...document.querySelectorAll('.bd-lst-clp .bp-btn.ghost')].find(b => b.closest('.on')).click()")
        t.wait_for(f"{LST}.approveBlocks.length === 0")
        self.assertFalse(self.approve_disabled(t))
        # an upload
        from test_storelisting import png
        (self.docs / "media").mkdir(exist_ok=True)
        (self.docs / "media" / "good.png").write_bytes(png(1320, 2868))
        media = self.url.rsplit("/", 1)[0] + "/media/good.png"
        t.wait_for(f"{LST}.slots.some(s => s.set === 'appstore/iphone-69')")
        from test_listing_capture import DROP
        t.ev(f"{DROP}({json.dumps(media)}, 'appstore/iphone-69')")
        t.wait_for(f"{LST}.drafts.length === 1")
        self.assertTrue(self.approve_disabled(t))
        # the dialog counts MT strings and mock-UI shots when it can open
        t.ev("document.querySelector('.bd-lst-uptile[data-file] .bd-lst-x, .bd-lst-uptile[data-file] button').click()")
        t.wait_for(f"{LST}.drafts.length === 0", 15)
        self.assertFalse(self.approve_disabled(t))
        t.ev("document.querySelector('.bd-key.approve').click()")
        t.wait_for("!!document.querySelector('.bd-approve[open]')")
        # 15 es-ES MT strings; 21 shots show a mock-up somewhere: every watch shot, the lifestyle shot, and every phone
        # shot in the tablet sets, which no phone capture fits
        self.assertEqual({k: t.ev(LST)["approveSummary"][k] for k in ("mt", "mock")}, {"mt": 15, "mock": 21})
        self.assertGreaterEqual(t.ev("document.querySelectorAll('.bd-approve[open] .bd-ap-sum li.warn').length"), 2)


if __name__ == "__main__":
    unittest.main()
