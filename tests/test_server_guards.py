"""Server guards: `serve.py run` on a free port with a temp BLUEDOC_HOME; the probes the review ran with curl.

Path traversal is 404, a foreign or empty Host is 403, a POST without X-Bluedoc or from another origin is 403,
a preflight is 501, GET /__bluedoc/wait without X-Bluedoc is 403 and leaves the reply for the agent, and a
Content-Length or wait timeout that isn't a finite number 0 or more is 400 at once, with no traceback.

The design screen route serves only a board's artboards (any rev the history holds), with the sandbox CSP and
without X-Frame-Options; anything else under it, traversal included, is 404, and doc pages stay unframable. An
`icons` artboard's screen is the icon sheet, built from its layers inside the registered folder.

POST /__bluedoc/icons writes an icon export only as the page's own (header, origin, key), only the export's file
names, only PNGs of their size under 4 MB (and the two kinds of text file), only into <stem>.icons/<artboard>/:
a bad file in a set writes none of it."""
from __future__ import annotations

import base64
import http.client
import json
import os
import shutil
import struct
import time
import unittest
import zlib
from urllib.parse import quote

from _support import Server, TempHome


class ServerGuards(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.docs = self.tmp.copy_examples()
        self.doc = self.docs / "acme-saved-carts-plan.bluedoc.json"
        # a doc outside the registered folder: what a traversal would try to reach
        self.secret = self.tmp.dir / "secret.bluedoc.json"
        shutil.copy(self.docs / "acme-orders.bluedoc.json", self.secret)
        r = self.tmp.run("serve.py", "add", self.docs)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.server = Server(self.tmp)
        self.server.start()
        self.port, self.host, self.req = self.server.port, self.server.host, self.server.req
        self.url = self.server.url_for(self.doc)
        self.assertTrue(self.url and self.url.endswith("/acme-saved-carts-plan.bluedoc.json"), self.url)
        self.slug = self.url.split("/")[1]

    def tearDown(self) -> None:
        self.server.stop()
        self.tmp.cleanup()

    def test_doc_renders(self) -> None:
        self.assertEqual(self.req("GET", self.url)[0], 200)

    def test_path_traversal_is_404(self) -> None:
        s = self.slug
        paths = [f"/{s}/../secret.bluedoc.json", f"/{s}/%2e%2e/secret.bluedoc.json", f"/{s}/..%2fsecret.bluedoc.json",
                 f"/{s}/%2e%2e%2fsecret.bluedoc.json?raw=1", f"/{s}/../home/roots.json",
                 "/__bluedoc/vendor/../../scripts/serve.py", "/__bluedoc/vendor/%2e%2e/%2e%2e/scripts/serve.py",
                 "/__bluedoc/vendor/..%2f..%2fscripts%2fserve.py"]
        for p in paths:
            with self.subTest(path=p):
                status, body = self.req("GET", p)
                self.assertEqual(status, 404, body[:200])

    def test_host_header(self) -> None:
        for host, want in ((f"evil.com:{self.port}", 403), ("", 403), (f"localhost:{self.port}", 200)):
            with self.subTest(host=host):
                self.assertEqual(self.req("GET", "/", headers={"Host": host})[0], want)

    def changes(self) -> bytes:
        return json.dumps({"path": self.url, "rev": "1", "annotations": [], "message": "Acme test",
                           "markdown": "# Change requests: Acme test\n"}).encode()

    def test_cross_site_posts_are_refused(self) -> None:
        own = f"http://{self.host}"
        for name, headers, want in (("no header", {}, 403),
                                    ("foreign origin", {"X-Bluedoc": "1", "Origin": "http://evil.com"}, 403),
                                    ("null origin", {"X-Bluedoc": "1", "Origin": "null"}, 403)):
            with self.subTest(name):
                status, _ = self.req("POST", "/__bluedoc/changes", self.changes(), {"Content-Type": "application/json", **headers})
                self.assertEqual(status, want)
        self.assertEqual(self.req("OPTIONS", "/__bluedoc/changes", headers={"Origin": "http://evil.com",
                                  "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-bluedoc"})[0], 501)
        wait = f"/__bluedoc/wait?doc={quote(str(self.doc))}&kind=any&timeout=0"
        self.assertEqual(self.req("GET", wait, headers={"X-Bluedoc": "1"})[0], 204, "a refused POST stored a reply")
        status, _ = self.req("POST", "/__bluedoc/changes", self.changes(), {"Content-Type": "application/json", "X-Bluedoc": "1", "Origin": own})
        self.assertEqual(status, 200)

    def test_wait_needs_the_header_and_keeps_the_reply(self) -> None:
        status, _ = self.req("POST", "/__bluedoc/changes", self.changes(), {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200)
        wait = f"/__bluedoc/wait?doc={quote(str(self.doc))}&kind=any&timeout=1"
        self.assertEqual(self.req("GET", wait)[0], 403)
        status, body = self.req("GET", wait, headers={"X-Bluedoc": "1"})
        self.assertEqual(status, 200, "the refused wait consumed the reply")
        self.assertEqual(json.loads(body)["message"]["kind"], "changes")

    def test_bad_numbers_are_400(self) -> None:
        own = f"http://{self.host}"
        status, _ = self.req("PUT", "/__bluedoc/state", b"{}", {"Content-Type": "application/json", "X-Bluedoc": "1",
                                                                "Origin": own, "Content-Length": "abc"})
        self.assertEqual(status, 400, "Content-Length: abc")
        for timeout in ("abc", "nan", "inf", "-1"):
            with self.subTest(timeout=timeout):
                t0 = time.monotonic()
                status, _ = self.req("GET", f"/__bluedoc/wait?doc={quote(str(self.doc))}&kind=any&timeout={timeout}",
                                     headers={"X-Bluedoc": "1"})
                self.assertEqual(status, 400)
                self.assertLess(time.monotonic() - t0, 2, "a bad timeout held the connection")
        self.assertNotIn("Traceback", (self.tmp.dir / "server.log").read_text(encoding="utf-8"))


class ScreenRouteGuards(unittest.TestCase):
    """The design screen route (/<slug>/…/<stem>.design/<artboard>.html): only a board's artboards, framable by
    bluedoc pages only and sandboxed by its CSP; doc pages stay unframable."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.doc = self.docs / "acme-fit-design.bluedoc.json"
        # a screen-shaped file outside the registered folder, and one inside that no board names
        (self.tmp.dir / "secret.design").mkdir()
        (self.tmp.dir / "secret.design" / "x.html").write_text("<p>secret</p>", encoding="utf-8")
        (self.docs / "acme-fit-design.design" / "stray.html").write_text("<p>stray</p>", encoding="utf-8")
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.url = self.server.url_for(self.doc)
        self.base = self.url.rsplit("/", 1)[0]
        self.slug = self.url.split("/")[1]

    def get(self, path: str) -> tuple[int, dict, str]:
        c = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        try:
            c.request("GET", path, headers={"Host": self.server.host})
            r = c.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read().decode("utf-8", "replace")
        finally:
            c.close()

    def test_a_screen_is_framable_by_bluedoc_only_and_sandboxed(self) -> None:
        status, headers, body = self.get(f"{self.base}/acme-fit-design.design/login.html")
        self.assertEqual(status, 200, body[:200])
        self.assertNotIn("x-frame-options", headers)
        csp = headers.get("content-security-policy", "")
        for part in ("connect-src 'none'", "sandbox allow-scripts", "frame-ancestors 'self'", "form-action 'none'", "base-uri 'none'"):
            self.assertIn(part, csp)
        self.assertIn('data-bd="submit"', body)

    def test_a_doc_page_stays_unframable(self) -> None:
        status, headers, _ = self.get(self.url)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("x-frame-options"), "DENY")
        self.assertIn("frame-ancestors 'none'", headers.get("content-security-policy", ""))

    def test_an_old_rev_serves_its_own_html(self) -> None:
        status, _, body = self.get(f"{self.base}/acme-fit-design.design/login.html?rev=A")
        self.assertEqual(status, 200)
        self.assertIn('data-bd="submit"', body)
        self.assertNotIn('data-bd="passkey"', body, "rev A's sign-in had no passkey button")
        self.assertIn('data-bd="passkey"', self.get(f"{self.base}/acme-fit-design.design/login.html")[2])

    def test_anything_else_is_404(self) -> None:
        s = self.slug
        paths = [f"/{s}/../secret.design/x.html", f"/{s}/%2e%2e/secret.design/x.html",
                 f"/{s}/acme-fit-design.design/..%2f..%2fsecret.design%2fx.html",
                 f"/{s}/acme-fit-design.design/%2e%2e/%2e%2e/secret.design/x.html",
                 f"{self.base}/acme-fit-design.design/stray.html", f"{self.base}/acme-fit-design.design/nope.html",
                 f"{self.base}/acme-fit-design.design/login.html?rev=Z", f"{self.base}/other.design/login.html",
                 f"{self.base}/acme-fit-design.design/app-icon.html?rev=A",
                 "/__bluedoc/kit/../../scripts/serve.py", "/__bluedoc/kit/%2e%2e/%2e%2e/scripts/serve.py"]
        for p in paths:
            with self.subTest(path=p):
                status, _, body = self.get(p)
                self.assertEqual(status, 404, body[:200])

    def test_the_icon_sheet_is_built_from_the_layers(self) -> None:
        status, headers, body = self.get(f"{self.base}/acme-fit-design.design/app-icon.html")
        self.assertEqual(status, 200, body[:200])
        self.assertIn("sandbox allow-scripts", headers.get("content-security-policy", ""))
        self.assertNotIn("x-frame-options", headers)
        for tile in ("ios-master", "ios-light", "ios-dark", "ios-tinted", "android-layers", "android-circle", "play", "home-android-dark"):
            self.assertIn(f'data-bd="{tile}"', body)
        self.assertIn("/__bluedoc/kit/icon-sheet.css", body)
        self.assertNotIn("/__bluedoc/kit/base.css", body, "the sheet brings its own kit")
        icon = json.loads(body.split('id="bd-icon">', 1)[1].split("</script>", 1)[0])
        self.assertEqual(icon["bg"], "#0f766e")
        self.assertEqual(sorted(icon["layers"]), ["fg", "mono"])
        fg = (self.docs / "acme-fit-design.design" / "app-icon" / "fg.svg").read_bytes()
        self.assertEqual(icon["layers"]["fg"], "data:image/svg+xml;base64," + base64.b64encode(fg).decode())

    def test_a_layer_linked_from_outside_is_not_read(self) -> None:
        fg = self.docs / "acme-fit-design.design" / "app-icon" / "fg.svg"
        (self.tmp.dir / "secret.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 108 108"/>', encoding="utf-8")
        fg.unlink()
        fg.symlink_to(self.tmp.dir / "secret.svg")
        status, _, body = self.get(f"{self.base}/acme-fit-design.design/app-icon.html")
        self.assertEqual(status, 404, body[:200])

    def test_the_home_card_draws_links(self) -> None:
        status, raw = self.server.req("GET", "/__bluedoc/index.json", headers={"X-Bluedoc": "1"})
        self.assertEqual(status, 200)
        doc = next(d for r in json.loads(raw)["roots"] for d in r["docs"] if d["path"].endswith("acme-fit-design.bluedoc.json"))
        card = doc["card"]
        self.assertTrue(card.get("links"), card)
        n = len(card["artboards"])
        self.assertLessEqual(len(card["links"]), 24)
        self.assertEqual(len({frozenset(p) for p in card["links"]}), len(card["links"]), "one line per pair")
        for i, j in card["links"]:
            self.assertTrue(0 <= i < n and 0 <= j < n and i != j, (i, j))

    def test_board_drafts_are_kept_and_broken_ones_dropped(self) -> None:
        """A link or layout draft is reader state the page draws (template.html MARKUP `valid`); one it can't is dropped."""
        t = {"key": "link:today/tab-workouts", "label": "Workouts tab"}
        anns = {"d1": {"type": "link", "target": t, "link": {"op": "set", "from": "today", "el": "tab-workouts", "to": "workout"}},
                "d2": {"type": "layout", "target": {"key": "layout:main", "label": "Board"}, "layout": {"positions": {"today": [0, 960]}}},
                "d3": {"type": "link", "target": t, "link": {"op": "set", "from": "today"}},
                "d4": {"type": "layout", "target": {"key": "layout:main", "label": "Board"}, "layout": {}}}
        ops = [[f"__ann:{i}", json.dumps({"id": i, **a})] for i, a in anns.items()]
        status, raw = self.server.req("PUT", "/__bluedoc/state", json.dumps({"path": self.url, "ops": ops}).encode(),
                                      {"Content-Type": "application/json", "X-Bluedoc": "1", "Origin": f"http://{self.server.host}"})
        self.assertEqual(status, 200, raw)
        self.assertEqual(sorted(json.loads(raw)["dropped"]), ["__ann:d3", "__ann:d4"])
        status, raw = self.server.req("GET", f"/__bluedoc/state?path={quote(self.url)}", headers={"X-Bluedoc": "1"})
        self.assertEqual(sorted(k for k in json.loads(raw)["state"] if k.startswith("__ann:")), ["__ann:d1", "__ann:d2"])


def png(size: int, *, width: int | None = None) -> bytes:
    """A real RGBA PNG, size x size (width overrides the IHDR's width)."""
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
    rows = b"".join(b"\x00" + b"\x0f\x76\x6e\xff" * size for _ in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width or size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


IOS = "ios/AppIcon.appiconset/"
CONTENTS = json.dumps({"images": [{"filename": "AppIcon.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"}],
                       "info": {"author": "xcode", "version": 1}}).encode()
ADAPTIVE = (b'<?xml version="1.0" encoding="utf-8"?>\n<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">'
            b'<background android:drawable="@mipmap/ic_launcher_background"/><foreground android:drawable="@mipmap/ic_launcher_foreground"/>'
            b'</adaptive-icon>\n')


class IconSaveGuards(unittest.TestCase):
    """POST /__bluedoc/icons: the page's PNG sets into <stem>.icons/<artboard>/ beside the doc, and nowhere else."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.url = self.server.url_for(self.docs / "acme-fit-design.bluedoc.json")
        self.out = self.docs / "acme-fit-design.icons"
        self.own = {"Content-Type": "application/json", "X-Bluedoc": "1", "Origin": f"http://{self.server.host}"}

    def post(self, files: dict, artboard="app-icon", headers: dict | None = None, path: str | None = None) -> tuple[int, dict]:
        body = json.dumps({"path": self.url if path is None else path, "artboard": artboard,
                           "files": {k: base64.b64encode(v).decode() if isinstance(v, bytes) else v for k, v in files.items()}})
        status, raw = self.server.req("POST", "/__bluedoc/icons", body.encode(), self.own if headers is None else headers)
        return status, json.loads(raw or b"{}")

    def written(self) -> list[str]:
        return sorted(p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file()) if self.out.exists() else []

    def test_a_set_is_written_beside_the_doc(self) -> None:
        files = {IOS + "AppIcon.png": png(1024), IOS + "Contents.json": CONTENTS,
                 "android/res/mipmap-anydpi-v26/ic_launcher.xml": ADAPTIVE,
                 "android/res/mipmap-hdpi/ic_launcher_foreground.png": png(162),
                 "android/res/mipmap-xxxhdpi/ic_launcher_round.png": png(192), "play/icon-512.png": png(512)}
        status, answer = self.post(files)
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["dir"], "acme-fit-design.icons/app-icon")
        self.assertEqual(self.written(), sorted(f"app-icon/{k}" for k in files))
        for k, v in files.items():
            self.assertEqual((self.out / "app-icon" / k).read_bytes(), v, k)
        status, _ = self.post({IOS + "AppIcon.png": png(1024)})   # a second export replaces the file
        self.assertEqual(status, 200)

    def test_writes_need_the_page_s_header_origin_and_key(self) -> None:
        files = {"play/icon-512.png": png(512)}
        for name, headers in (("no header", {"Content-Type": "application/json", "Origin": self.own["Origin"]}),
                              ("foreign origin", {**self.own, "Origin": "http://evil.com"}),
                              ("null origin", {**self.own, "Origin": "null"}),
                              ("wrong key", {**self.own, "X-Bluedoc-Key": "nope"})):
            with self.subTest(name):
                self.assertEqual(self.post(files, headers=headers)[0], 403)
        self.assertEqual(self.written(), [])

    def test_only_the_export_s_files_as_they_should_be(self) -> None:
        big = png(1024)[:33] + b"\x00" * (4 * 1024 * 1024)
        cases = {"traversal": {"../../../evil.png": png(512)}, "traversal in a name": {IOS + "../../../../evil.png": png(1024)},
                 "absolute": {"/tmp/evil.png": png(512)}, "another name": {IOS + "Other.png": png(1024)},
                 "not a PNG": {IOS + "AppIcon.png": b"GIF89a" + b"\x00" * 64}, "wrong size": {IOS + "AppIcon.png": png(512)},
                 "not square": {"play/icon-512.png": png(512, width=511)}, "over 4 MB": {IOS + "AppIcon.png": big},
                 "not base64": {"play/icon-512.png": "%%%"}, "not a catalog": {IOS + "Contents.json": b"[1]"},
                 "not an adaptive icon": {"android/res/mipmap-anydpi-v26/ic_launcher.xml": b"<svg/>"},
                 "a bad file in a good set": {"play/icon-512.png": png(512), IOS + "AppIcon.png": png(48)}, "nothing": {}}
        for name, files in cases.items():
            with self.subTest(name):
                status, answer = self.post(files)
                self.assertEqual(status, 400, answer)
        self.assertEqual(self.written(), [])
        self.assertFalse((self.tmp.dir / "evil.png").exists() or (self.docs / "evil.png").exists())

    def test_only_an_icons_artboard_of_a_registered_doc(self) -> None:
        files = {"play/icon-512.png": png(512)}
        outside = self.tmp.dir / "secret.bluedoc.json"
        shutil.copy(self.docs / "acme-fit-design.bluedoc.json", outside)
        for name, kw in (("a screen", {"artboard": "login"}), ("traversal", {"artboard": "../app-icon"}), ("no artboard", {"artboard": None}),
                         ("not a doc", {"path": self.url.replace(".bluedoc.json", ".design/login.html")}),
                         ("outside the folders", {"path": f"/{self.url.split('/')[1]}/../secret.bluedoc.json"})):
            with self.subTest(name):
                self.assertEqual(self.post(files, **kw)[0], 404)
        self.assertEqual(self.written(), [])
        self.assertFalse((self.tmp.dir / "secret.icons").exists())

    def test_a_link_on_the_way_out_is_refused(self) -> None:
        elsewhere = self.tmp.dir / "elsewhere"
        elsewhere.mkdir()
        files = {"play/icon-512.png": png(512)}
        self.out.symlink_to(elsewhere, target_is_directory=True)
        self.assertEqual(self.post(files)[0], 409)
        self.out.unlink()
        (self.out / "app-icon").mkdir(parents=True)
        os.symlink(elsewhere, self.out / "app-icon" / "play", target_is_directory=True)
        self.assertEqual(self.post(files)[0], 409)
        self.assertEqual(list(elsewhere.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
