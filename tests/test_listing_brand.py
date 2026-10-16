"""A storelisting's style and brand (plan steps style-picker, fonts, palette): fonts.py reads family, style, weight and
fsType from TTF and TTC files and rescans a folder that changed; the contrast pairs and their minimum come from
store-rules.json `brand` and match a reference WCAG 2.2 calculation; the build warns on a low pair, a font a PDF can't
embed and a style whose hook is missing, and checks listing.style.<platform>; `patch brand:` records a brand draft;
GET /__bluedoc/fonts and POST /__bluedoc/listing/brand need the key, and the brand image lands in
<stem>.listing/brand/. Under node, the page's k-means finds an image's colours by share and gives them roles.
The browser tests (BLUEDOC_BROWSER_TESTS=1), on the left panel's Style, Brand and Checks tabs: a style pick restyles
the shots in place and goes as decisions with its patch command; a style finding in Checks opens Style; an image's
palette, the role editor and the contrast pairs; a brand draft blocks Approve; the font menu lists the folder's fonts
and ↻ Fonts finds a new one; an installed font renders in a shot."""
from __future__ import annotations

import base64
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from xml.etree import ElementTree

from _support import SKILL, Server, TempHome, load_json, template_slice
from test_page_state import CHROME, ChromePage, Tab

import build
import fonts
import listing

NODE = shutil.which("node")
STEM = "acme-fit-listing"
LST = "BP.listing()"


def sfnt(family: str, style: str, weight: int, fs_type: int, italic: bool = False, typo: str | None = None, base: int = 0) -> bytes:
    """A font file with a `name` (Windows, US English) and an `OS/2` table only: what fonts.py reads. base: where it
    starts in a collection (table offsets are from the file's start)."""
    names = {1: family, 2: style, 0: "Copyright Acme"}
    if typo:
        names[16] = typo
    recs, strs = b"", b""
    for nid, text in sorted(names.items()):
        s = text.encode("utf-16-be")
        recs += struct.pack(">HHHHHH", 3, 1, 0x409, nid, len(s), len(strs))
        strs += s
    name = struct.pack(">HHH", 0, len(names), 6 + len(recs)) + recs + strs
    os2 = bytearray(78)
    struct.pack_into(">HHHH", os2, 0, 4, 0, weight, 0)
    struct.pack_into(">H", os2, 8, fs_type)
    struct.pack_into(">H", os2, 62, 1 if italic else 0)
    tables = [(b"OS/2", bytes(os2)), (b"name", name)]
    head = struct.pack(">IHHHH", 0x00010000, len(tables), 0, 0, 0)
    off, dirs, body = base + 12 + 16 * len(tables), b"", b""
    for tag, data in tables:
        dirs += struct.pack(">4sIII", tag, 0, off + len(body), len(data))
        body += data + b"\0" * (-len(data) % 4)
    return head + dirs + body


def ttc(*faces: tuple) -> bytes:
    n = len(faces)
    out, at = b"", 12 + 4 * n
    offs = []
    for f in faces:
        offs.append(at + len(out))
        out += sfnt(*f, base=at + len(out))
    return b"ttcf" + struct.pack(">II", 0x00010000, n) + struct.pack(f">{n}I", *offs) + out


def png_bands(bands: list[tuple[str, int]], w: int = 40) -> bytes:
    """An RGB PNG of horizontal bands: (#rrggbb, rows) each."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\0" + bytes.fromhex(c[1:]) * w for c, n in bands for _ in range(n))
    h = sum(n for _, n in bands)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


BANDS = [("#0b1220", 30), ("#f8fafc", 24), ("#2563eb", 18), ("#fbbf24", 14), ("#64748b", 9), ("#16a34a", 5)]


def wcag(a: str, b: str) -> float:
    """WCAG 2.2's contrast ratio, written out from the spec (relative luminance, 0.03928 threshold as published)."""
    def lum(c: str) -> float:
        out = []
        for i in (1, 3, 5):
            s = int(c[i:i + 2], 16) / 255
            out.append(s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]
    l1, l2 = sorted((lum(a), lum(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


class Rep:
    """validate_listing's findings as (where, message) pairs."""

    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []
        self.warnings: list[tuple[str, str]] = []

    def err(self, where: str, msg: str) -> None:
        self.errors.append((where, msg))

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append((where, msg))


def report(doc: dict, doc_path=None) -> Rep:
    rep = Rep()
    listing.validate_listing(rep, doc, doc_path)
    return rep


class Fonts(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="bd-fonts-"))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_a_ttf_gives_its_family_style_weight_and_fstype(self) -> None:
        f = self.dir / "AcmeTest-Regular.ttf"
        f.write_bytes(sfnt("Acme Test", "Regular", 400, 8))
        self.assertEqual(fonts.read_font(f), [{"family": "Acme Test", "style": "Regular", "weight": 400, "italic": False,
                                               "fsType": 8, "copyright": "Copyright Acme"}])

    def test_a_collection_gives_each_face_and_typographic_names_win(self) -> None:
        f = self.dir / "AcmeTest.ttc"
        f.write_bytes(ttc(("Acme Test", "Bold", 700, 2), ("Acme Test Cond", "Italic", 400, 0, True, "Acme Test")))
        faces = fonts.read_font(f)
        self.assertEqual([(x["family"], x["style"], x["weight"], x["italic"], x["fsType"]) for x in faces],
                         [("Acme Test", "Bold", 700, False, 2), ("Acme Test", "Italic", 400, True, 0)])

    def test_families_group_faces_and_take_the_regular_faces_fstype(self) -> None:
        (self.dir / "a.ttf").write_bytes(sfnt("Acme Test", "Regular", 400, 4))
        (self.dir / "b.ttc").write_bytes(ttc(("Acme Test", "Bold", 700, 2), (".Acme Hidden", "Regular", 400, 0)))
        (self.dir / "notes.txt").write_text("not a font")
        (self.dir / "broken.otf").write_bytes(b"OTTO\0\0")
        got = fonts.families([self.dir], fonts.FontCache())
        self.assertEqual([x["family"] for x in got], ["Acme Test"])
        self.assertEqual(got[0]["fsType"], 4)
        self.assertEqual([f["weight"] for f in got[0]["faces"]], [400, 700])

    def test_a_folder_is_read_again_only_when_it_changes(self) -> None:
        cache = fonts.FontCache()
        (self.dir / "a.ttf").write_bytes(sfnt("Acme One", "Regular", 400, 0))
        self.assertEqual([x["family"] for x in fonts.families([self.dir], cache)], ["Acme One"])
        sub = self.dir / "more"
        sub.mkdir()
        time.sleep(0.01)
        (sub / "b.otf").write_bytes(sfnt("Acme Two", "Regular", 400, 0))
        self.assertEqual([x["family"] for x in fonts.families([self.dir], cache)], ["Acme One", "Acme Two"])

    def test_bluedoc_font_dirs_replaces_the_system_folders(self) -> None:
        old = os.environ.get("BLUEDOC_FONT_DIRS")
        os.environ["BLUEDOC_FONT_DIRS"] = str(self.dir)
        try:
            self.assertEqual(fonts.font_dirs(), [self.dir])
        finally:
            if old is None:
                os.environ.pop("BLUEDOC_FONT_DIRS")
            else:
                os.environ["BLUEDOC_FONT_DIRS"] = old

    def test_embedding_bits(self) -> None:
        self.assertIsNone(listing.font_embedding(0))
        self.assertIsNone(listing.font_embedding(4))
        self.assertIsNone(listing.font_embedding(8))
        self.assertEqual(listing.font_embedding(2), "restricted embedding")
        self.assertEqual(listing.font_embedding(0x200), "bitmap only")


class Contrast(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = listing.load_rules()
        self.doc = load_json(SKILL / "examples" / f"{STEM}.bluedoc.json")
        self.lb = listing.listing_of(self.doc)

    def test_ratios_match_a_reference_wcag_calculation(self) -> None:
        for a, b in [("#000000", "#ffffff"), ("#767676", "#ffffff"), ("#2457d6", "#eef2ff"), ("#fbbf24", "#0b1220"), ("#fff", "#f59e0b")]:
            full = lambda c: "#" + "".join(x * 2 for x in c[1:]) if len(c) == 4 else c  # noqa: E731
            self.assertAlmostEqual(listing.contrast_ratio(a, b), wcag(full(a), full(b)), places=2)
        self.assertAlmostEqual(listing.contrast_ratio("#000", "#fff"), 21.0, places=6)

    def test_each_pair_of_the_example_palette_against_the_reference(self) -> None:
        pal = listing.brand_palette(self.lb, self.rules)
        got = listing.contrast_report(pal, self.rules)
        self.assertEqual([(p["fg"], p["bg"]) for p in got], [(p["fg"], p["bg"]) for p in self.rules["brand"]["contrast"]["pairs"]])
        for p in got:
            self.assertAlmostEqual(p["ratio"], wcag(pal[p["fg"]], pal[p["bg"]]), places=1)
            self.assertEqual(p["ok"], p["ratio"] >= self.rules["brand"]["contrast"]["min"])

    def test_the_kits_defaults_are_the_rules(self) -> None:
        css = (SKILL / "assets" / "kits" / "shot.css").read_text(encoding="utf-8")
        got = dict(re.findall(r"--brand-([a-z]+):\s*(#[0-9a-fA-F]{3,6})", css[css.index(":root"):css.index("}", css.index(":root"))]))
        self.assertEqual(got, self.rules["brand"]["defaults"])

    def test_the_pairs_are_the_rules_and_name_what_they_draw(self) -> None:
        c = self.rules["brand"]["contrast"]
        self.assertEqual(c["min"], 4.5)
        self.assertTrue(all(p["label"] and p["styles"] for p in c["pairs"]))
        self.assertEqual(sorted(self.rules["brand"]["defaults"]), sorted(listing.PALETTE_ROLES))
        broken = json.loads(json.dumps(self.rules))
        broken["brand"]["contrast"]["pairs"].append({"fg": "ink", "bg": "bg", "label": "x", "styles": "y"})
        self.assertTrue(any("brand.contrast.pairs" in x for x in listing.rules_problems(broken)))

    def test_a_low_pair_warns_with_its_label_and_the_example_passes(self) -> None:
        self.assertFalse([w for w in report(self.doc).warnings if ".brand." in w[0]])
        doc = json.loads(json.dumps(self.doc))
        listing.listing_of(doc)["brand"]["palette"]["caption"] = "#3b6ff0"
        warns = [m for w, m in report(doc).warnings if w.endswith(".brand.palette")]
        self.assertTrue(any(m.startswith("Caption on background") and "4.5:1" in m for m in warns), warns)
        self.assertTrue(any(m.startswith("Step chip") for m in warns), warns)

    def test_a_font_a_pdf_cant_embed_warns(self) -> None:
        doc = json.loads(json.dumps(self.doc))
        listing.listing_of(doc)["brand"]["font"] = {"family": "Acme Sans", "weight": 700, "source": "system", "fsType": 2}
        self.assertTrue(any(w.endswith(".brand.font") and "restricted" in m for w, m in report(doc).warnings))
        listing.listing_of(doc)["brand"]["font"]["source"] = "cloud"
        self.assertTrue(any(w.endswith(".brand.font.source") for w, _ in report(doc).errors))


class Styles(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.path = self.docs / f"{STEM}.bluedoc.json"
        self.doc = load_json(self.path)
        self.lb = listing.listing_of(self.doc)

    def warns(self, style: dict) -> list[str]:
        self.lb["style"] = style
        return [f"{w}: {m}" for w, m in report(self.doc, self.path).warnings]

    def test_a_platform_style_is_checked_and_wins_on_its_page(self) -> None:
        self.lb["style"] = {"message": "m1", "layout": "l1", "play": {"layout": "l4"}}
        self.assertEqual(report(self.doc, self.path).errors, [])
        self.assertEqual(listing.effective_style(self.lb, "play"), {"message": "m1", "layout": "l4"})
        self.assertEqual(listing.effective_style(self.lb, "appstore"), {"message": "m1", "layout": "l1"})
        self.lb["style"] = {"play": {"layout": "l9"}, "itunes": {"message": "m1"}}
        errs = [w for w, _ in report(self.doc, self.path).errors]
        self.assertIn(next(w for w in errs if w.endswith(".style.play.layout")), errs)
        self.assertTrue(any(w.endswith(".style.itunes") for w in errs), errs)

    def test_a_style_whose_hook_is_missing_warns(self) -> None:
        self.assertFalse([w for w in self.warns({"message": "m3"}) if "M3" in w], "the example marks data-callout")
        self.assertTrue([w for w in self.warns({"message": "m4"}) if ".style.play" in w and "use-case first" in w])
        self.assertTrue([w for w in self.warns({"message": "m4"}) if ".style.appstore" in w and ".proof" in w])
        self.assertTrue([w for w in self.warns({"layout": "l5"}) if "L5" in w and "photo" in w])
        self.assertFalse([w for w in self.warns({"message": "m1", "layout": "l1"}) if ".style." in w])

    def test_a_lifestyle_photo_needs_its_credits(self) -> None:
        f = self.docs / f"{STEM}.design" / "today.html"
        f.write_text(f.read_text(encoding="utf-8").replace('<h1 class="shot-cap"', '<img class="shot-photo" alt="" src="data:image/png;base64,iVBORw0KGgo=">\n  <h1 class="shot-cap"', 1), encoding="utf-8")
        self.assertTrue([w for w in self.warns({"layout": "l5"}) if "today.credits" in w])
        next(a for a in listing.shots_of(self.doc) if a["id"] == "today")["credits"] = "Photo: Acme, model release on file"
        self.assertFalse([w for w in self.warns({"layout": "l5"}) if "credits" in w])

    def test_the_page_gets_each_shots_hooks_and_the_thumbnails(self) -> None:
        d = listing.page_data(self.doc, self.path)
        self.assertIn("callout", d["hooks"]["today"])
        for s in listing.load_rules()["styles"]:
            sid = s["id"]
            self.assertTrue(f'id="st-{sid}"' in d["thumbs"] or f'id="st-{sid}-appstore"' in d["thumbs"] and f'id="st-{sid}-play"' in d["thumbs"], sid)
        self.assertNotIn("<script", d["thumbs"])
        ElementTree.fromstring(d["thumbs"])   # the page parses it as XML: one error and no thumbnail shows

    def test_patch_brand_records_a_brand_draft(self) -> None:
        brand = {"font": {"family": "Avenir Next", "weight": 600, "source": "system", "fsType": 0},
                 "palette": {"bg": "#0b1220", "surface": "#f8fafc", "accent": "#2563eb", "text": "#f8fafc", "caption": "#fbbf24"},
                 "image": f"{STEM}.listing/brand/source.png"}
        (self.docs / f"{STEM}.listing" / "brand").mkdir(parents=True, exist_ok=True)
        (self.docs / f"{STEM}.listing" / "brand" / "source.png").write_bytes(png_bands(BANDS))
        r = self.tmp.run("build.py", "patch", self.path, "brand:main", "--json", json.dumps(brand), "--change", "Brand", "--no-bump")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(listing.listing_of(load_json(self.path))["brand"], brand)
        r = self.tmp.run("build.py", "patch", self.path, "brand:main", "--json", '{"font": null}', "--no-bump")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("font", listing.listing_of(load_json(self.path))["brand"])
        with self.assertRaises(build.PatchError):
            build.resolve_key(load_json(self.path), "brand:other")


@unittest.skipUnless(NODE, "node not installed")
class Extract(unittest.TestCase):
    """The page's palette extractor (lstLab, lstKmeans, lstRoles, lstContrast in template.html) under node."""

    def run_js(self, body: str, data) -> object:
        src = template_slice("// a colour in CIE Lab (D65)", "// a text's length as its store counts it")
        js = src + "\nconst data = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n" + body
        r = subprocess.run([NODE, "-e", js], input=json.dumps(data), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_six_swatches_by_share_with_roles(self) -> None:
        px = [[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c, n in BANDS for _ in range(n * 40)]
        got = self.run_js("const sw = lstKmeans(data.map(p => lstLab(...p)));"
                          "process.stdout.write(JSON.stringify({sw: sw.map(s => ({hex: s.hex, share: s.share})), roles: lstRoles(sw),"
                          " ratio: lstContrast('#fbbf24', '#0b1220')}));", px)
        self.assertEqual([s["hex"] for s in got["sw"]], [c for c, _ in BANDS])
        total = sum(n for _, n in BANDS)
        self.assertEqual([s["share"] for s in got["sw"]], [round(n / total * 1000) / 10 for _, n in BANDS])
        self.assertEqual(got["roles"]["bg"], "#0b1220")
        self.assertEqual(got["roles"]["surface"], "#f8fafc")
        self.assertEqual(got["roles"]["accent"], "#2563eb")
        self.assertEqual(got["roles"]["caption"], "#f8fafc")
        self.assertAlmostEqual(got["ratio"], listing.contrast_ratio("#fbbf24", "#0b1220"), places=6)

    def test_a_flat_image_gives_one_swatch(self) -> None:
        got = self.run_js("process.stdout.write(JSON.stringify(lstKmeans(data.map(p => lstLab(...p))).map(s => [s.hex, s.share])));", [[36, 87, 214]] * 500)
        self.assertEqual(got, [["#2457d6", 100]])


class Routes(unittest.TestCase):
    """GET /__bluedoc/fonts and POST /__bluedoc/listing/brand on `serve.py run`."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.fonts = self.tmp.dir / "fonts"
        self.fonts.mkdir()
        (self.fonts / "AcmeTest-Regular.ttf").write_bytes(sfnt("Acme Test", "Regular", 400, 0))
        self.tmp.env["BLUEDOC_FONT_DIRS"] = str(self.fonts)
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.url = self.server.url_for(self.docs / f"{STEM}.bluedoc.json")

    def post(self, body: dict, key: str | None = None) -> tuple[int, dict]:
        h = {"Content-Type": "application/json", "X-Bluedoc": "1", **({"X-Bluedoc-Key": key} if key is not None else {})}
        status, raw = self.server.req("POST", "/__bluedoc/listing/brand", json.dumps(body).encode(), h)
        return status, json.loads(raw)

    def test_fonts_need_the_key_and_a_new_font_shows_up(self) -> None:
        self.assertEqual(self.server.req("GET", "/__bluedoc/fonts")[0], 403)
        self.assertEqual(self.server.req("GET", "/__bluedoc/fonts", headers={"X-Bluedoc": "1", "X-Bluedoc-Key": "nope"})[0], 403)
        status, raw = self.server.req("GET", "/__bluedoc/fonts", headers={"X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        self.assertEqual([f["family"] for f in json.loads(raw)["families"]], ["Acme Test"])
        time.sleep(0.01)
        (self.fonts / "AcmeTest.ttc").write_bytes(ttc(("Acme Serif", "Regular", 400, 2), ("Acme Serif", "Bold", 700, 2)))
        fams = json.loads(self.server.req("GET", "/__bluedoc/fonts", headers={"X-Bluedoc": "1"})[1])["families"]
        self.assertEqual([(f["family"], len(f["faces"]), f["fsType"]) for f in fams], [("Acme Serif", 2, 2), ("Acme Test", 1, 0)])

    def test_the_brand_image_is_checked_and_written_beside_the_doc(self) -> None:
        img = png_bands(BANDS)
        brand = self.docs / f"{STEM}.listing" / "brand"
        self.assertEqual(self.post({"path": self.url, "data": base64.b64encode(img).decode()}, key="nope")[0], 403)
        self.assertFalse(brand.exists())
        self.assertEqual(self.post({"path": self.url, "data": base64.b64encode(b"GIF89a....").decode()})[0], 400)
        self.assertEqual(self.post({"path": self.url, "data": "not base64!"})[0], 400)
        other = self.server.url_for(self.docs / "acme-orders.bluedoc.json")
        self.assertEqual(self.post({"path": other, "data": base64.b64encode(img).decode()})[0], 400)
        status, ans = self.post({"path": self.url, "data": base64.b64encode(img).decode()})
        self.assertEqual(status, 200, ans)
        self.assertEqual(ans["file"], f"{STEM}.listing/brand/source.png")
        self.assertEqual((brand / "source.png").read_bytes(), img)
        jpeg = b"\xff\xd8\xff\xe0" + b"\0" * 64
        status, ans = self.post({"path": self.url, "data": base64.b64encode(jpeg).decode()})
        self.assertEqual((status, ans["file"]), (200, f"{STEM}.listing/brand/source.jpg"))
        self.assertEqual(sorted(p.name for p in brand.iterdir()), ["source.jpg"])

    def test_a_link_on_the_way_is_refused(self) -> None:
        out = self.tmp.dir / "elsewhere"
        out.mkdir()
        top = self.docs / f"{STEM}.listing"
        top.mkdir(exist_ok=True)
        shutil.rmtree(top / "brand", ignore_errors=True)
        (top / "brand").symlink_to(out, target_is_directory=True)
        status, _ = self.post({"path": self.url, "data": base64.b64encode(png_bands(BANDS)).decode()})
        self.assertEqual(status, 409)
        self.assertEqual(list(out.iterdir()), [])


def pixel(tab, x: float, y: float) -> list[int]:
    """The screen's RGB at (x, y) CSS px of the tab's viewport, from a screenshot."""
    shot = tab.browser.call("Page.captureScreenshot", {"format": "png", "clip": {"x": x, "y": y, "width": 1, "height": 1, "scale": 1}}, tab.session)["data"]
    return tab.ev("new Promise(ok => { const i = new Image(); i.onload = () => { const c = document.createElement('canvas'); c.width = c.height = 1;"
                  " const g = c.getContext('2d'); g.drawImage(i, 0, 0); ok([...g.getImageData(0, 0, 1, 1).data].slice(0, 3)); };"
                  f" i.src = 'data:image/png;base64,{shot}'; }})")


def near(rgb: list[int], hexc: str, tol: int = 6) -> bool:
    return all(abs(a - int(hexc[i:i + 2], 16)) <= tol for a, i in zip(rgb, (1, 3, 5)))


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class BrandPage(ChromePage):
    def setUp(self) -> None:
        super().setUp()
        self.doc_path = self.docs / f"{STEM}.bluedoc.json"
        self.url = self.server.url_for(self.doc_path)

    def restart(self, **env: str) -> None:
        self.server.stop()
        self.tmp.env.update(env)
        self.server.start()
        self.base = f"http://{self.server.host}"

    def page(self, side: str):
        """The listing's page with the left panel open on `side` (style or brand)."""
        t = self.open(self.url)
        t.wait_for("!!document.querySelector('.bd-lst-sec') && !!BP.listing()")
        t.ev("document.documentElement.classList.contains('bd-lp-open') || document.dispatchEvent(new KeyboardEvent('keydown', {key: '['}))")
        t.ev(f"document.querySelector('.bd-lp-tabs [data-v=\"{side}\"]').click()")
        t.wait_for(f"!document.getElementById('bd-lp-{side}').hidden && document.documentElement.classList.contains('bd-lp-open')")
        return t

    def first_tile(self, t, s: str = "play/phone") -> dict:
        t.ev(f"document.querySelector('.bd-lst-shot[data-set=\"{s}\"]').scrollIntoView({{block: 'center'}})")
        t.wait_for(f"BP.listing().tiles.some(x => x.set === '{s}' && x.ready)", 20)
        time.sleep(0.4)
        return t.ev(f"(r => ({{x: r.left, y: r.top, w: r.width, h: r.height}}))(document.querySelector('.bd-lst-shot[data-set=\"{s}\"]').getBoundingClientRect())")

    def test_a_style_pick_restyles_the_shots_in_place_and_goes_as_decisions(self) -> None:
        t = self.page("style")
        r = self.first_tile(t)
        edge = (r["x"] + 3, r["y"] + r["h"] * 0.97)
        self.assertTrue(near(pixel(t, *edge), "#1d4ed8"), pixel(t, *edge))   # L1 on the listing's bg
        t.ev("document.querySelectorAll('.bd-lst-shot iframe').forEach(f => f.__kept = 1)")
        n = t.ev("document.querySelectorAll('.bd-lst-shot iframe').length")
        t.ev("document.querySelector('.bd-lst-stp [data-style=\"l4\"]').click()")
        t.wait_for("BP.listing().style.layout === 'l4'")
        t.ev("document.querySelector('.bd-lst-stp [data-style=\"m3\"]').click()")
        t.wait_for("BP.listing().style.message === 'm3'")
        time.sleep(0.5)
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-lst-shot iframe')].filter(f => f.__kept).length"), n, "no frame reloaded")
        dark = pixel(t, *edge)
        self.assertTrue(max(dark) < 40, dark)   # L4: the dark ground
        self.assertIn("style-play-default-layout", t.ev(LST)["decisions"])
        t.ev("BP.listing({platform: 'appstore'})")
        self.assertEqual(t.ev(LST)["style"], {"message": "m1", "layout": "l1"}, "a pick is per platform page")
        self.send_changes(t, "1")
        out = self.reply(self.doc_path)
        self.assertIn("`style-play-default-layout` → L4 Dark hero (recommended: L1", out)
        self.assertIn("`style-play-default-message` → M3 Zoomed feature callout", out)
        self.assertIn("## Style picks", out)
        cmd = next(l for l in out.splitlines() if l.startswith("build.py patch") and '"style"' in l)
        args = shlex.split(cmd)[2:]
        r2 = self.tmp.run("build.py", "patch", self.doc_path, *args[1:])
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        lb = listing.listing_of(load_json(self.doc_path))
        self.assertEqual(lb["style"]["play"], {"message": "m3", "layout": "l4"})
        t2 = self.page("style")
        self.assertEqual(t2.ev(LST)["style"], {"message": "m3", "layout": "l4"})
        self.assertNotIn("Your pick", t2.ev("document.querySelector('.bd-lst-pick').textContent"))

    def test_a_style_finding_in_checks_opens_the_style_tab(self) -> None:
        doc = load_json(self.doc_path)
        lb = listing.listing_of(doc)
        lb["style"] = {**(lb.get("style") or {}), "play": {"message": "m4", "layout": "l1"}}   # M4 on Play warns: use-case first
        self.doc_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        t = self.page("checks")
        t.ev("BP.listing({platform: 'play'})")
        open_style = "[...document.querySelectorAll('#bd-lp-checks li.warn button')].find(b => b.title === 'Open Style')"
        t.wait_for(f"!!{open_style}")
        t.ev(f"{open_style}.click()")
        t.wait_for("!document.getElementById('bd-lp-style').hidden && document.querySelector('.bd-lp-tabs [data-v=style]').getAttribute('aria-checked') === 'true'")

    def test_a_palette_from_an_image_with_roles_contrast_and_a_draft_that_blocks_approve(self) -> None:
        t = self.page("brand")
        img = self.tmp.dir / "brand.png"
        img.write_bytes(png_bands(BANDS, 128))
        doc = t.browser.call("DOM.getDocument", {}, t.session)["root"]["nodeId"]
        node = t.browser.call("DOM.querySelector", {"nodeId": doc, "selector": ".bd-lst-brp .bd-lst-file"}, t.session)["nodeId"]
        t.browser.call("DOM.setFileInputFiles", {"nodeId": node, "files": [str(img)]}, t.session)
        t.wait_for("BP.listing().brand.swatches.length === 6", 15)
        b = t.ev(LST)["brand"]
        self.assertEqual([s["hex"] for s in b["swatches"]], [c for c, _ in BANDS])
        self.assertEqual((b["palette"]["bg"], b["palette"]["surface"], b["palette"]["accent"]), ("#0b1220", "#f8fafc", "#2563eb"))
        self.assertEqual(b["image"], f"{STEM}.listing/brand/source.png")
        self.assertEqual((self.docs / f"{STEM}.listing" / "brand" / "source.png").read_bytes(), img.read_bytes())
        pairs = self.listing_rules()["brand"]["contrast"]["pairs"]
        self.assertEqual([c["label"] for c in b["contrast"]], [p["label"] for p in pairs])
        for c in b["contrast"]:
            self.assertAlmostEqual(c["ratio"], wcag(b["palette"][c["fg"]], b["palette"][c["bg"]]), places=1)
        self.assertTrue(b["draft"])
        self.assertTrue(t.ev(LST)["approveBlocks"])
        # the hex field of a role restyles the shots live
        t.ev("(i => { i.value = '#7c3aed'; i.dispatchEvent(new Event('input')); })(document.querySelector('.bd-lst-role[data-role=\"bg\"] .hx'))")
        t.wait_for("BP.listing().brand.palette.bg === '#7c3aed'")
        r = self.first_tile(t)
        time.sleep(0.6)
        self.assertTrue(near(pixel(t, r["x"] + 3, r["y"] + r["h"] * 0.97), "#7c3aed"), pixel(t, r["x"] + 3, r["y"] + r["h"] * 0.97))
        self.send_changes(t, "1")
        out = self.reply(self.doc_path)
        self.assertIn("## Brand drafts", out)
        cmd = next(l for l in out.splitlines() if l.startswith("build.py patch") and "brand:main" in l)
        r2 = self.tmp.run("build.py", "patch", self.doc_path, *shlex.split(cmd)[3:])
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        rec = listing.listing_of(load_json(self.doc_path))["brand"]
        self.assertEqual(rec["palette"]["bg"], "#7c3aed")
        self.assertEqual(rec["image"], f"{STEM}.listing/brand/source.png")
        t2 = self.page("brand")
        self.assertFalse(t2.ev(LST)["brand"]["draft"])
        self.assertEqual(t2.ev(LST)["approveBlocks"], [])

    def listing_rules(self) -> dict:
        return listing.load_rules()

    def test_the_font_menu_lists_the_folders_fonts_and_refresh_finds_a_new_one(self) -> None:
        fdir = self.tmp.dir / "fonts"
        fdir.mkdir()
        (fdir / "AcmeTest-Regular.ttf").write_bytes(sfnt("Acme Test", "Regular", 400, 0))
        self.restart(BLUEDOC_FONT_DIRS=str(fdir))
        self.url = self.server.url_for(self.doc_path)
        t = self.page("brand")
        t.ev("document.querySelector('.bd-lst-fonts .bp-btn').click()")
        t.wait_for("BP.listing().brand.fonts === 1")
        time.sleep(0.01)
        (fdir / "AcmeSerif.ttc").write_bytes(ttc(("Acme Serif", "Regular", 400, 2), ("Acme Serif", "Bold", 700, 2)))
        t.ev("[...document.querySelectorAll('.bd-lst-frow .bp-btn')].pop().click()")
        t.wait_for("BP.listing().brand.fonts === 2")
        t.ev("[...document.querySelectorAll('.bd-lst-font')].find(b => b.textContent.startsWith('Acme Serif')).click()")
        t.wait_for("BP.listing().brand.font && BP.listing().brand.font.family === 'Acme Serif'")
        f = t.ev(LST)["brand"]["font"]
        self.assertEqual((f["weight"], f["fsType"], f["source"]), (700, 2, "system"))
        self.assertIn("restricted", t.ev("document.querySelector('.bd-lst-fcur').textContent"))
        self.send_changes(t, "1")
        out = self.reply(self.doc_path)
        self.assertIn('"family":"Acme Serif"', out)
        self.assertIn("fsType 2", out)

    def test_an_installed_font_renders_in_a_shot(self) -> None:
        fams = {f["family"] for f in fonts.families()}
        fam = next((f for f in ("Georgia", "Times New Roman", "Courier New", "DejaVu Serif") if f in fams), None)
        if not fam:
            self.skipTest("no known serif font installed")
        # the shot on its own in a tab, under its screen CSP; the brand message as the page sends it (here the tab is
        # its own parent)
        t = Tab(self.browser)
        t.browser.call("Page.navigate", {"url": f"{self.base}{self.url.rsplit('/', 1)[0]}/{STEM}.design/today.html?set=play/phone"}, t.session)
        t.wait_for("document.readyState === 'complete' && !!document.querySelector('.shot-cap') && !document.documentElement.classList.contains('shot-pending')")
        t.ev(f"window.postMessage({{bd: 'brand', font: {{family: {json.dumps(fam)}, weight: 700}}}}, '*')")
        t.wait_for(f"getComputedStyle(document.querySelector('.shot-cap')).fontFamily.split(',')[0].replace(/\"/g, '').trim() === {json.dumps(fam)}")
        t.browser.call("DOM.enable", {}, t.session)
        t.browser.call("CSS.enable", {}, t.session)
        root = t.browser.call("DOM.getDocument", {}, t.session)["root"]["nodeId"]
        node = t.browser.call("DOM.querySelector", {"nodeId": root, "selector": ".shot-cap"}, t.session)["nodeId"]
        used = [f["familyName"] for f in t.browser.call("CSS.getPlatformFontsForNode", {"nodeId": node}, t.session)["fonts"]]
        self.assertEqual(used[:1], [fam], used)


if __name__ == "__main__":
    unittest.main()
