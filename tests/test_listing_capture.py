"""Storelisting M2: uploads, capture recipes and re-shoots.

capture.py's commands per target (--dry-run), its skip lines with the tools hidden, its PNG checks; the upload route's
guards (key, size, alpha, slot, links, recorded files) and Approve refused while an upload is unrecorded; recipes in
the build; a capture's hash in the revision; and what `patch el:<shot>/ui` prints to re-shoot. A real run against the
simulators' and the emulator's Settings app (tests/fixtures/capture-system-apps.bluedoc.json) runs with
BLUEDOC_DEVICE_TESTS=1 when Xcode or the Android SDK is there (it boots devices, a minute or more); the web capture
and the page's upload slot, readback and pins run with BLUEDOC_BROWSER_TESTS=1."""
from __future__ import annotations

import base64
import copy
import json
import os
import shlex
import shutil
import struct
import subprocess
import sys
import time
import unittest
import zlib
from pathlib import Path

from _support import REPO, SCRIPTS, Server, TempHome, load_json
from test_page_state import CHROME, ChromePage
from test_storelisting import STEM, png, report

import build
import capture
import listing

FIXTURE = REPO / "tests" / "fixtures" / "capture-system-apps.bluedoc.json"
DEVICES = os.environ.get("BLUEDOC_DEVICE_TESTS") == "1"


def png_rgba(w: int, h: int) -> bytes:
    """A w × h RGBA PNG (colour type 6), all transparent."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\0" + b"\0" * 4 * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def fixture_in(tmp: TempHome) -> Path:
    d = tmp.dir / "cap"
    d.mkdir()
    shutil.copy(FIXTURE, d / FIXTURE.name)
    return d / FIXTURE.name


class CaptureCommands(unittest.TestCase):
    """--dry-run prints each target's commands; hidden tools give skip lines and exit 3."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.doc = fixture_in(self.tmp)
        self.bin = self.tmp.dir / "bin"
        self.bin.mkdir()

    def run_capture(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPTS / "capture.py"), str(self.doc), *args], capture_output=True,
                              text=True, env={**self.tmp.env, **(env or {})}, timeout=60)

    def fake(self, name: str) -> None:
        f = self.bin / name
        f.write_text("#!/bin/sh\nexit 0\n")
        f.chmod(0o755)

    def test_dry_run_prints_each_targets_commands(self) -> None:
        for name in ("xcrun", "adb", "emulator"):
            self.fake(name)
        r = self.run_capture("--dry-run", "--locale", "es-ES", env={"PATH": f"{self.bin}:/usr/bin:/bin", "ANDROID_HOME": str(self.bin)})
        self.assertEqual(r.returncode, 3, r.stderr)   # wearos has no AVD named: skipped
        out = r.stdout
        # iOS: status bar, appearance, launch in the locale, an opaque screenshot
        self.assertIn("simctl status_bar 'iPhone 17 Pro Max' override --time 9:41", out)
        self.assertIn("simctl ui 'iPhone 17 Pro Max' appearance dark", out)
        self.assertIn("com.apple.Preferences -AppleLanguages '(es-ES)' -AppleLocale es_ES", out)
        self.assertIn("simctl io 'iPhone 17 Pro Max' screenshot --type=png --mask=black", out)
        # watchOS: no status bar or appearance (the runtime refuses them)
        watch = out[out.index("# watchos"):]
        self.assertNotIn("status_bar", watch)
        self.assertNotIn("appearance", watch)
        self.assertIn("com.apple.NanoSettings", watch)
        # Android: headless boot, demo mode, night mode, per-app locale, a raw screencap
        self.assertIn("-avd Acme_Pixel_9 -no-window -no-audio", out)
        self.assertIn("com.android.systemui.demo -e command clock -e hhmm 0941", out)
        self.assertIn("cmd uimode night yes", out)
        self.assertIn("cmd locale set-app-locales com.android.settings --locales es-ES", out)
        self.assertIn("exec-out screencap", out)
        self.assertIn("skip  watch-settings wearos", out)
        # nothing written
        self.assertFalse(listing.listing_dir(self.doc).exists())

    def test_filters_narrow_the_run(self) -> None:
        self.fake("xcrun")
        r = self.run_capture("--dry-run", "--shot", "settings", "--target", "ios-phone-63", "--locale", "en-US",
                             env={"PATH": f"{self.bin}:/usr/bin:/bin"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count("screenshot --type=png"), 1)
        self.assertIn("'iPhone 17 Pro'", r.stdout)
        self.assertEqual(self.run_capture("--shot", "nope").returncode, 2)
        self.assertEqual(self.run_capture("--target", "fridge").returncode, 2)

    def test_missing_tools_skip_with_exit_3(self) -> None:
        home = self.tmp.dir / "nohome"
        home.mkdir()
        r = self.run_capture(env={"PATH": str(self.bin), "ANDROID_HOME": str(self.bin), "ANDROID_SDK_ROOT": "",
                                  "HOME": str(home), "BLUEDOC_CHROME": str(self.bin / "nochrome")})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        self.assertTrue(lines and all(ln.startswith("skip") for ln in lines), r.stdout)
        self.assertTrue(any("xcrun" in ln for ln in lines))
        self.assertTrue(any("adb" in ln for ln in lines))
        self.assertFalse(listing.listing_dir(self.doc).exists())

    def test_a_web_target_without_chrome_skips(self) -> None:
        doc = load_json(self.doc)
        lb = listing.listing_of(doc)
        lb["capture"]["apps"]["web"] = {"url": "http://localhost:5173/"}
        listing.shots_of(doc)[0]["recipe"]["targets"] = ["web"]
        self.doc.write_text(json.dumps(doc), encoding="utf-8")
        r = self.run_capture("--shot", "settings", env={"BLUEDOC_CHROME": str(self.bin / "nochrome")})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("BLUEDOC_CHROME", r.stdout)

    def test_a_web_url_off_loopback_is_refused(self) -> None:
        doc = load_json(self.doc)
        listing.listing_of(doc)["capture"]["apps"]["web"] = {"url": "https://example.com/"}
        rep = report(doc, self.doc)
        self.assertTrue(any(".apps.web" in e for e in rep.errors), rep.errors)


class CaptureChecks(unittest.TestCase):
    """What capture.py keeps: an opaque PNG, and a raw set's capture at the set's size."""

    def test_raw_screencap_becomes_an_rgb_png(self) -> None:
        w, h = 3, 2
        px = bytes([10, 20, 30, 255]) * (w * h)
        for head in (struct.pack("<III", w, h, 1), struct.pack("<IIII", w, h, 1, 0)):
            out = capture.raw_screencap_png(head + px)
            info = listing.png_info(out)
            self.assertEqual((info["w"], info["h"], info["colour"]), (3, 2, 2))
            self.assertIn(zlib.compress(b"".join(b"\0" + bytes([10, 20, 30]) * w for _ in range(h)), 6), out)
        with self.assertRaises(capture.Fail):
            capture.raw_screencap_png(struct.pack("<III", w, h, 1) + bytes([0, 0, 0, 0]) * (w * h))
        with self.assertRaises(capture.Fail):
            capture.raw_screencap_png(struct.pack("<III", w, h, 4) + px)

    def test_alpha_and_a_wrong_raw_size_fail(self) -> None:
        rules = listing.load_rules()
        watch = listing.by_id(rules, "sets")["appstore/watch"]
        self.assertIsNone(capture.check_png(png(422, 514), watch, rules)[1])
        why = capture.check_png(png(410, 500), watch, rules)[1]
        self.assertIn("Apple Watch Ultra 3", why)
        self.assertIn("alpha", capture.check_png(png_rgba(422, 514), watch, rules)[1])
        self.assertIsNone(capture.check_png(png(1080, 2400), None, rules)[1])   # a UI slot capture: any size

    def test_a_raw_set_is_found_for_its_target_only(self) -> None:
        rules = listing.load_rules()
        a = {"id": "w", "device": "shot", "sets": ["play/wear", "appstore/watch"], "recipe": {}}
        self.assertEqual(capture.raw_rule(a, "watchos", rules)["id"], "appstore/watch")
        self.assertEqual(capture.raw_rule(a, "wearos", rules)["id"], "play/wear")
        self.assertIsNone(capture.raw_rule(a, "web", rules))

    def test_a_replaced_capture_moves_to_old(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        doc = tmp.dir / "x.bluedoc.json"
        rel = "x.listing/captures/web/en-US/a.png"
        capture.write_capture(doc, rel, png(4, 4))
        capture.write_capture(doc, rel, png(4, 4))
        self.assertFalse((tmp.dir / "x.listing/captures/old").exists())
        old = png(4, 4)
        capture.write_capture(doc, rel, png(5, 5))
        kept = list((tmp.dir / "x.listing/captures/old").iterdir())
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].read_bytes(), old)
        self.assertEqual(listing.png_info((tmp.dir / rel).read_bytes())["w"], 5)

    def test_rows_merge_by_shot_target_and_locale(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        doc = tmp.dir / "x.bluedoc.json"
        capture.save_rows(doc, [{"shot": "a", "target": "web", "locale": "en-US", "file": "1"},
                                {"shot": "b", "target": "web", "locale": "en-US", "file": "2"}])
        capture.save_rows(doc, [{"shot": "a", "target": "web", "locale": "en-US", "file": "3"}])
        rows = load_json(tmp.dir / "x.listing/captures/captures.json")["captures"]
        self.assertEqual(sorted((r["shot"], r["file"]) for r in rows), [("a", "3"), ("b", "2")])


class Recipes(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = load_json(FIXTURE)

    def test_the_fixture_is_clean_apart_from_its_screens(self) -> None:
        rep = report(self.doc)
        self.assertEqual(rep.errors, [])

    def test_bad_recipes_and_capture_settings_are_errors(self) -> None:
        cases = {
            "appearance": lambda lb, a: a["recipe"].__setitem__("appearance", "dim"),
            "targets": lambda lb, a: a["recipe"].__setitem__("targets", ["fridge"]),
            "locales": lambda lb, a: a["recipe"].__setitem__("locales", ["fr-FR"]),
            "settle": lambda lb, a: a["recipe"].__setitem__("settle", 90),
            "key": lambda lb, a: a["recipe"].__setitem__("tap", "x"),
            "route": lambda lb, a: a["recipe"].__setitem__("route", "acme fit://x"),
            "device": lambda lb, a: lb["capture"]["devices"].__setitem__("fridge", "x"),
            "app": lambda lb, a: lb["capture"]["apps"].__setitem__("ios", {"bundle": "not a bundle"}),
            "kind": lambda lb, a: lb["capture"]["apps"].__setitem__("tvos", {"bundle": "com.acme.tv"}),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                d = copy.deepcopy(self.doc)
                change(listing.listing_of(d), listing.shots_of(d)[0])
                self.assertTrue(report(d).errors, name)

    def test_a_recipe_runs_on_its_sets_targets_unless_it_names_them(self) -> None:
        rules, lb = listing.load_rules(), listing.listing_of(self.doc)
        a = listing.shots_of(self.doc)[0]
        self.assertEqual(listing.recipe_targets(a, rules), ["android-phone", "ios-phone", "ios-phone-63", "ios-tablet"])
        self.assertEqual(listing.recipe_locales(a, lb), ["en-US", "es-ES"])
        b = listing.shots_of(self.doc)[1]
        self.assertEqual(listing.recipe_locales(b, lb), ["es-ES"])


class Revisions(unittest.TestCase):
    """A capture joins the revision by hash; a stale or missing capture warns; patch prints how to re-shoot."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.path = self.docs / f"{STEM}.bluedoc.json"

    def capture_file(self) -> Path:
        return self.docs / f"{STEM}.listing/captures/web/en-US/today.png"

    def test_the_example_records_its_captures_in_the_revision(self) -> None:
        hashes = build.screen_hashes(load_json(self.path), self.path)
        self.assertIn("today/capture/web/en-US", hashes)
        h = load_json(build.history_path(self.path))
        self.assertEqual(h["revs"][-1]["screens"]["today/capture/web/en-US"], hashes["today/capture/web/en-US"])

    def test_a_reshoot_changes_the_revision_and_the_approval_hash(self) -> None:
        doc = load_json(self.path)
        before = build.approval_hash(doc, self.path)
        capture.write_capture(self.path, f"{STEM}.listing/captures/web/en-US/today.png", png(1236, 2745))
        rows = load_json(listing.listing_dir(self.path) / "captures/captures.json")
        for r in rows["captures"]:
            r.pop("sha256", None)   # the hash is read from the file then
        (listing.listing_dir(self.path) / "captures/captures.json").write_text(json.dumps(rows), encoding="utf-8")
        self.assertNotEqual(build.approval_hash(doc, self.path), before)
        r = self.tmp.run("build.py", self.path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("today/capture/web/en-US", r.stderr + r.stdout)

    def test_a_changed_recipe_makes_the_capture_stale_and_patch_prints_the_reshoot(self) -> None:
        r = self.tmp.run("build.py", "patch", self.path, "el:today/ui")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"{STEM}.listing/captures/web/en-US/today.png", r.stdout)
        self.assertIn("--shot today --target web --locale en-US", r.stdout)
        self.assertNotIn("stale", r.stdout)
        doc = load_json(self.path)
        next(a for a in listing.shots_of(doc) if a["id"] == "today")["recipe"]["settle"] = 4
        self.path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        r = self.tmp.run("build.py", self.path, "--check")
        self.assertIn("stale", r.stderr + r.stdout)
        r = self.tmp.run("build.py", "patch", self.path, "el:today/ui")
        self.assertIn("stale", r.stdout)
        self.assertIn("capture.py", r.stdout)

    def test_a_mock_shot_says_it_has_no_recipe(self) -> None:
        r = self.tmp.run("build.py", "patch", self.path, "el:streak/cap")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no recipe", r.stdout)

    def test_a_missing_capture_warns(self) -> None:
        self.capture_file().unlink()
        r = self.tmp.run("build.py", self.path, "--check")
        self.assertIn("missing", r.stderr + r.stdout)
        self.assertIn("--shot today", r.stderr + r.stdout)


class Uploads(unittest.TestCase):
    """POST /__bluedoc/listing/upload and the drafts it makes."""

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

    def setUp(self) -> None:
        self.folder = listing.listing_dir(self.path) / "appstore"
        for p in ("appstore", "play"):
            shutil.rmtree(listing.listing_dir(self.path) / p, ignore_errors=True)
            self.addCleanup(shutil.rmtree, listing.listing_dir(self.path) / p, True)
        self.raw = self.path.read_text(encoding="utf-8")
        self.addCleanup(self.path.write_text, self.raw, "utf-8")
        hist = build.history_path(self.path)
        self.addCleanup(hist.write_text, hist.read_text(encoding="utf-8"), "utf-8")

    def post(self, body: dict, **headers) -> tuple[int, dict]:
        hs = {"Content-Type": "application/json", "X-Bluedoc": "1", **headers}
        status, raw = self.server.req("POST", "/__bluedoc/listing/upload", json.dumps(body).encode(), hs)
        return status, json.loads(raw)

    def upload(self, data: bytes, **kw) -> tuple[int, dict]:
        return self.post({"path": self.url, "platform": "appstore", "locale": "es-ES", "set": "appstore/iphone-69",
                          "slot": 4, "png": base64.b64encode(data).decode(), **kw})

    def test_a_good_png_is_written_into_its_set_and_listed_as_a_draft(self) -> None:
        status, ans = self.upload(png(1320, 2868))
        self.assertEqual(status, 200, ans)
        f = self.docs / ans["file"]
        self.assertEqual(f.parent, self.folder / "es-ES" / "iphone-69")
        self.assertEqual(f.name, "04.png")
        drafts = listing.uploads(load_json(self.path), self.path)
        self.assertEqual([(u["set"], u["locale"], u["slot"]) for u in drafts], [("appstore/iphone-69", "es-ES", 4)])
        r = self.tmp.run("build.py", self.path, "--check")
        self.assertIn(ans["file"], r.stderr)

    def test_no_key_no_write(self) -> None:
        body = {"path": self.url, "platform": "appstore", "locale": "es-ES", "set": "appstore/iphone-69", "slot": 4,
                "png": base64.b64encode(png(1320, 2868)).decode()}
        status, _ = self.post(body, **{"X-Bluedoc-Key": "nope"})
        self.assertEqual(status, 403)
        status, _ = self.server.req("POST", "/__bluedoc/listing/upload", json.dumps(body).encode(), {"Content-Type": "application/json"})
        self.assertEqual(status, 403)
        self.assertFalse(self.folder.exists())

    def test_a_wrong_size_alpha_or_slot_is_refused_with_its_rule(self) -> None:
        for data, kw in ((png(1000, 2000), {}), (png_rgba(1320, 2868), {}), (png(1320, 2868), {"slot": 11}),
                         (png(1320, 2868), {"slot": 0}), (b"GIF89a", {}), (png(1320, 2868), {"set": "play/phone"}),
                         (png(1320, 2868), {"locale": "fr-FR"})):
            with self.subTest(kw=kw, size=len(data)):
                status, ans = self.upload(data, **kw)
                self.assertEqual(status, 400, ans)
                if "set" not in kw and "locale" not in kw and data[:4] == b"\x89PNG":
                    self.assertEqual((ans["rule"], ans["source"]), ("appstore/iphone-69", "A-SS"))
        self.assertFalse(self.folder.exists())

    def test_a_play_set_takes_its_side_range_and_ratio(self) -> None:
        status, ans = self.upload(png(1080, 1920), platform="play", set="play/phone")
        self.assertEqual(status, 200, ans)
        status, ans = self.upload(png(1080, 2400), platform="play", set="play/phone")
        self.assertEqual(status, 400, ans)   # a phone's full screen is over 2:1: it goes in a shot's UI slot instead

    def test_a_link_on_the_way_is_refused(self) -> None:
        outside = self.tmp.dir / "outside"
        outside.mkdir(exist_ok=True)
        self.folder.mkdir(parents=True)
        (self.folder / "es-ES").symlink_to(outside, target_is_directory=True)
        status, ans = self.upload(png(1320, 2868))
        self.assertEqual(status, 409, ans)
        self.assertEqual(list(outside.iterdir()), [])

    def test_a_recorded_file_is_never_overwritten(self) -> None:
        status, ans = self.upload(png(1320, 2868))
        self.assertEqual(status, 200, ans)
        art = {"id": "upl-04", "title": "Upload 04", "device": "shot", "fidelity": "hifi", "sets": ["appstore/iphone-69"],
               "locale": "es-ES", "src": ans["file"]}
        r = self.tmp.run("build.py", "patch", self.path, "block:listing/1", "--append", json.dumps(art), "--no-bump")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(listing.uploads(load_json(self.path), self.path), [])
        kept = (self.docs / ans["file"]).read_bytes()
        status, again = self.upload(png(1290, 2796))
        self.assertEqual(status, 200, again)
        self.assertNotEqual(again["file"], ans["file"])
        self.assertEqual((self.docs / ans["file"]).read_bytes(), kept)
        status, gone = self.post({"path": self.url, "discard": ans["file"]})
        self.assertEqual(status, 404, gone)   # a recorded shot isn't a draft to discard
        status, gone = self.post({"path": self.url, "discard": again["file"]})
        self.assertEqual(status, 200, gone)
        self.assertFalse((self.docs / again["file"]).exists())

    def test_approve_is_refused_while_an_upload_is_unrecorded(self) -> None:
        status, ans = self.upload(png(1320, 2868))
        self.assertEqual(status, 200, ans)
        status, raw = self.server.req("GET", f"/__bluedoc/ping?path={self.url}", headers={"X-Bluedoc": "1"})
        doc_hash = build.approval_hash(load_json(self.path), self.path)
        body = {"decision": "approved", "path": self.url, "docHash": doc_hash, "rev": load_json(self.path)["meta"]["rev"],
                "answers": [], "annotations": [], "markdown": "ok"}
        status, raw = self.server.req("POST", "/__bluedoc/approve", json.dumps(body).encode(),
                                      {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 409, raw)
        self.assertIn(b"not recorded", raw)


@unittest.skipUnless(DEVICES and (shutil.which("xcrun") or capture.android_tool("adb")),
                     "set BLUEDOC_DEVICE_TESTS=1 with Xcode or the Android SDK to boot devices")
class RealDevices(unittest.TestCase):
    """capture.py against the Settings app: the iPhone 17 Pro Max and the watch, and the first AVD when there is one."""

    def test_settings_on_the_simulators_and_the_emulator(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        doc = fixture_in(tmp)
        args = ["--locale", "es-ES", "--shot", "settings", "--shot", "watch-settings"]
        targets = []
        if shutil.which("xcrun"):
            targets += ["--target", "ios-phone", "--target", "watchos"]
        emu = capture.android_tool("emulator")
        avds = subprocess.run([emu, "-list-avds"], capture_output=True, text=True).stdout.split() if emu else []
        if avds:
            targets += ["--target", "android-phone", "--device", f"android-phone={avds[0]}"]
        if not targets:
            self.skipTest("no simulator or AVD")
        r = subprocess.run([sys.executable, str(SCRIPTS / "capture.py"), str(doc), *args, *targets], capture_output=True,
                           text=True, env=tmp.env, timeout=900)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = load_json(listing.listing_dir(doc) / "captures/captures.json")["captures"]
        for row in rows:
            info = listing.png_info((doc.parent / row["file"]).read_bytes())
            self.assertEqual(info["colour"], 2, row)
            if row["target"] == "watchos":
                self.assertEqual((info["w"], info["h"]), (422, 514))
            if row["target"] == "ios-phone":
                self.assertEqual((info["w"], info["h"]), (1320, 2868))


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class WebCapture(unittest.TestCase):
    def test_the_examples_web_recipes_capture_the_design_screens(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        docs = tmp.copy_examples()
        path = docs / f"{STEM}.bluedoc.json"
        shutil.rmtree(listing.listing_dir(path) / "captures")
        r = tmp.run("capture.py", path, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = load_json(listing.listing_dir(path) / "captures/captures.json")["captures"]
        doc = load_json(path)
        self.assertEqual(sorted(r["shot"] for r in rows), sorted(a["id"] for a in listing.shots_of(doc) if a.get("recipe")))
        rules = listing.load_rules()
        for row in rows:
            a = next(x for x in listing.shots_of(doc) if x["id"] == row["shot"])
            w, h, k = capture.web_size(a, rules)
            info = listing.png_info((docs / row["file"]).read_bytes())
            self.assertEqual((info["w"], info["h"], info["colour"]), (w * k, h * k, 2))
            self.assertEqual(row["recipe"], listing.recipe_hash(a["recipe"]))
        self.assertTrue(all(c["fresh"] for per in listing.captures(doc, path).values() for t in per.values() for c in t.values()))


LST = "BP.listing()"
DROP = """(async (url, set) => {
  const f = new File([await (await fetch(url)).blob()], url.split('/').pop(), { type: 'image/png' }), dt = new DataTransfer();
  dt.items.add(f);
  document.querySelector(`.bd-lst-upslot[data-set="${set}"]`).dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
  return true; })"""


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class UploadAndPinInChrome(ChromePage):
    """The page: a PNG dropped on a set's slot is a draft sent with its patch command; a pin on a capture says how to
    re-shoot it."""

    def setUp(self) -> None:
        super().setUp()
        self.doc_path = self.docs / f"{STEM}.bluedoc.json"
        self.url = self.server.url_for(self.doc_path)
        (self.docs / "media").mkdir(exist_ok=True)
        (self.docs / "media" / "good.png").write_bytes(png(1320, 2868))
        (self.docs / "media" / "alpha.png").write_bytes(png_rgba(1320, 2868))
        self.media = self.url.rsplit("/", 1)[0] + "/media/"

    def page(self, frag: str = "#appstore"):
        t = self.open(self.url)
        t.ev(f"location.hash = {json.dumps(frag)}; location.reload()")
        t.wait_for("document.readyState === 'complete' && !!window.BP && !!document.querySelector('.bd-lst-sec')")
        return t

    def test_a_dropped_png_is_a_draft_sent_with_its_patch_command(self) -> None:
        t = self.page("#appstore/es-ES")
        t.wait_for(f"{LST}.slots.some(s => s.set === 'appstore/iphone-69')")
        t.ev(f"{DROP}({json.dumps(self.media + 'alpha.png')}, 'appstore/iphone-69')")
        self.toast(t, "transparency")
        self.assertEqual(t.ev(f"{LST}.drafts"), [])
        self.assertFalse(listing.listing_dir(self.doc_path).joinpath("appstore").exists())
        t.ev(f"{DROP}({json.dumps(self.media + 'good.png')}, 'appstore/iphone-69')")
        t.wait_for(f"{LST}.drafts.length === 1")
        got = t.ev(LST)
        self.assertEqual(got["uploads"][0]["set"], "appstore/iphone-69")
        self.assertTrue(got["approveBlocks"])
        self.assertTrue((self.docs / got["uploads"][0]["file"]).is_file())
        self.send_changes(t, "1")
        out = self.reply(self.doc_path)
        self.assertIn("## Uploaded shots", out)
        cmd = next(ln for ln in out.splitlines() if ln.startswith("build.py patch") and "--append" in ln)
        # the agent runs it as given: the shot records the file, and the draft clears on reload
        args = shlex.split(cmd)[2:]
        r = self.tmp.run("build.py", "patch", self.doc_path, *args[1:])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(listing.uploads(load_json(self.doc_path), self.doc_path), [])
        t = self.page("#appstore/es-ES")
        t.wait_for(f"{LST}.approveBlocks.length === 0")
        self.assertEqual(t.ev(f"{LST}.drafts"), [])
        self.assertIn("upload", [tag for x in t.ev(LST)["tiles"] if x["set"] == "appstore/iphone-69" for tag in x["tags"]])

    def test_a_pin_on_a_capture_reads_back_its_recipe_and_reshoot(self) -> None:
        t = self.page()
        sel = ".bd-lst-shot[data-ab=\"today\"][data-set=\"appstore/iphone-69\"]"
        t.wait_for(f"{LST}.tiles.some(x => x.id === 'today' && x.set === 'appstore/iphone-69' && x.ready)", 20)
        self.assertIn("capture", next(x for x in t.ev(LST)["tiles"] if x["id"] == "today")["tags"])
        t.ev(f"document.querySelector('{sel}').scrollIntoView({{block: 'center'}})")
        t.ev("BP.setMode('point')")
        x, y = t.ev(f"(e => {{ const r = e.getBoundingClientRect(); return [r.left + r.width * 0.5, r.top + r.height * 0.6]; }})(document.querySelector('{sel}'))")
        time.sleep(0.3)
        for kind, buttons in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
            self.browser.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "buttons": buttons, "clickCount": 1}, t.session)
            time.sleep(0.05)
        t.wait_for("!document.querySelector('.bd-cmp').hidden")
        t.ev("(ta => { ta.value = 'Show 5 km'; ta.dispatchEvent(new Event('input')); })(document.querySelector('.bd-cmp textarea'))")
        t.ev("document.querySelector('.bd-cmp .bp-btn.primary').click()")
        a = t.wait_for("BP.annotations().find(a => a.note === 'Show 5 km')")
        self.assertEqual(a["target"]["key"], "el:today/ui")
        self.assertTrue(all(0 <= v <= 1 for v in a["target"]["at"]))
        md = t.ev("BP.changesPayload().markdown")
        self.assertIn(f"{STEM}.listing/captures/web/en-US/today.png", md)
        self.assertIn("--shot today --target web --locale en-US", md)
        self.assertIn("% of the UI", md)


if __name__ == "__main__":
    unittest.main()
