"""Website docs: `new website`, the page contract, live URLs, source hints, sections and variants, `patch` on a page,
the home card, the dev-server proxy, and a pin on a live page in a real browser.

`new website` writes a home page as a stub screen file, or with `--url` a live page and no file; a non-loopback
`--url` is refused. A website's board holds `page` artboards only. A live `url` must be http(s) on a loopback host
without credentials. Source hints are `path`, `path#symbol` or `path:line` inside the site's repo; with `board.root`, a
missing file, a symbol the file never names and a line past its end are warnings. Variants need a brief decision and
name its choices. The Acme example builds clean, and `patch` on its pages prints the page, the section and their
source hints. The server's proxy for a dev server answers only its own Host, injects the inspector after <head>, drops
X-Frame-Options and frame-ancestors for its own, strips bluedoc's key cookie, rewrites Host to the dev server, pins
viewport heights in CSS and HTML styles, and answers 502 when the dev server is down; the doc page's CSP frames exactly
that proxy. In headless Chrome (BLUEDOC_BROWSER_TESTS=1), a pin on a live page carries its section's source hints and
width into the change request, a variant pick edits the page in place from a picker in the gutter beside the page (clear
of every page; pointing at it outlines the section), a breakpoint resizes the page, Open in new tab opens the selected
page (a live page at its dev URL, a mockup at its screen route; a title bar's key its own page; none on a design), and
Full page frames a page at its whole height with a 100vh hero 900 px tall, pins in board space, zooms without a reload, a
re-layout or the page seeing a scroll, and falls back to Viewport for a page that grows with its frame."""
from __future__ import annotations

import copy
import http.client
import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from _support import EXAMPLES, SKILL, Server, TempHome, load_json

import build
import serve   # on sys.path through _support
from test_page_state import CHROME, Browser, Tab, until

STEM = "acme-site"


def errors(out: str) -> list[str]:
    return [l for l in out.splitlines() if l.startswith("ERROR")]


def warnings(out: str) -> list[str]:
    return [l for l in out.splitlines() if l.startswith("WARN")]


def board_of(doc: dict) -> dict:
    return next(b for b in build.all_blocks(doc) if b.get("type") == "board")


# the stub dev server's page: a nav, a hero whose title sits at a fixed place, and a FAQ
STUB_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Acme Fit</title>
<style>body { margin: 0; font: 16px sans-serif; } .hero { position: relative; height: 600px; }
#hero-title { position: absolute; left: 100px; top: 100px; width: 600px; height: 80px; margin: 0; }</style></head>
<body><header class="site-nav">Acme Fit</header><section class="hero"><h1 id="hero-title">Track everything</h1></section>
<section id="faq"><h2>Questions</h2></section></body></html>"""
# a long page whose hero is 100vh in its stylesheet: a 5svh nav (style attribute), the 900 px hero, a 10dvh band (style
# element; an at-rule's 50vh stays), a 2000 px FAQ with #deep 1500 px down it. At 1440 px in Full page: 3035 px tall.
# Its script notes in body[data-seen] what its IntersectionObservers see: the nav (in or out of view) and #deep, fully
# in view above the bottom 20 % of the viewport (180 px of the design viewport's 900).
TALL_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Acme Fit</title>
<link rel="stylesheet" href="/tall.css"><style>.band { height: 10dvh; } @media (min-height: 50vh) { .band { outline: 0; } }</style></head>
<body><header class="site-nav" style="height: 5svh">Acme Fit</header><section class="hero"><h1 id="hero-title">Track everything</h1></section>
<div class="band"></div><section id="faq"><h2 style="margin: 0">Questions</h2><p id="deep">Cancel any time</p></section>
<script>const seen = s => { document.body.dataset.seen = (document.body.dataset.seen || '') + s + ' '; };
new IntersectionObserver(([e]) => seen(e.isIntersecting ? 'nav' : 'nav-out')).observe(document.querySelector('.site-nav'));
new IntersectionObserver(([e]) => { if (e.isIntersecting) seen('deep'); }, { rootMargin: '0px 0px -20%', threshold: 1 }).observe(document.getElementById('deep'));</script>
</body></html>"""
TALL_CSS = """body { margin: 0; font: 16px sans-serif; } .hero { position: relative; height: 100vh; }
#hero-title { position: absolute; left: 100px; top: 100px; width: 600px; height: 80px; margin: 0; }
#faq { position: relative; height: 2000px; } #deep { position: absolute; left: 200px; top: 1500px; width: 300px; height: 40px; margin: 0; }"""
# a page that grows with its frame whatever the units: its hero is 100% of a 100% tall body, then 300 px more
GROW_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Acme Fit</title>
<style>html, body { height: 100%; margin: 0; } .hero { height: 100%; }</style></head>
<body><section class="hero">Track everything</section><section id="faq" style="height: 300px">Questions</section></body></html>"""
STUB_FILES = {"/": (STUB_PAGE, "text/html; charset=utf-8"), "/tall": (TALL_PAGE, "text/html; charset=utf-8"),
              "/tall.css": (TALL_CSS, "text/css; charset=utf-8"), "/grow": (GROW_PAGE, "text/html; charset=utf-8"),
              "/src/hero.css": ('const css = ".hero { min-height: 100vh; }";\nexport default css;\n', "text/javascript"),
              "/app.js": ('export const tall = "100vh";\n', "text/javascript")}


class StubDevServer:
    """A dev server on a free loopback port: STUB_FILES by path (any other path: STUB_PAGE), each sent with
    X-Frame-Options and a CSP that forbids framing; /echo answers the headers it got as JSON. seen holds each
    request's (path, headers)."""

    def __init__(self) -> None:
        seen = self.seen = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                seen.append((self.path, dict(self.headers.items())))
                if self.path == "/echo":
                    body, ctype = json.dumps(dict(self.headers.items())).encode(), "application/json"
                else:
                    text, ctype = STUB_FILES.get(self.path, STUB_FILES["/"])
                    body = text.encode()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


def site_doc(url: str) -> dict:
    """A website doc of one live page at url, its repo one folder up (root ".."), with a hero headline decision."""
    return {
        "id": "acme-live", "title": "Acme Fit: the live home page", "subtitle": "The home page from the dev server.",
        "meta": {"org": "Acme Corp", "kind": "Website", "type": "website", "rev": "1", "date": "2026-10-12"},
        "tldr": "One live page with two sections; pick the hero headline.",
        "sections": [
            {"id": "brief", "title": "Brief", "blocks": [
                {"type": "text", "md": "The home page turns a visitor into a trial."},
                {"type": "checklist", "id": "brief", "title": "Picks", "numbered": False, "items": [
                    {"id": "hero-headline", "text": "Which hero headline?", "recommend": "a",
                     "choices": [{"id": "a", "label": "Track everything", "md": "The current headline: nothing to change."},
                                 {"id": "b", "label": "Habit first", "md": "Leads with weekly goals, the feature this release adds."}]}]}]},
            {"id": "pages", "title": "Pages", "blocks": [
                {"type": "board", "id": "site", "targets": ["web"], "root": "..", "artboards": [
                    {"id": "home", "title": "Home", "device": "page", "fidelity": "hifi", "url": url,
                     "source": "src/pages/index.astro",
                     "sections": [
                         {"id": "hero", "title": "Hero", "sel": "section.hero", "source": ["src/content/site.ts#hero", "src/components/Hero.astro"],
                          "decision": "hero-headline",
                          "variants": {"a": [], "b": [{"sel": "#hero-title", "text": "Build the habit, one week at a time."}]}},
                         {"id": "faq", "title": "FAQ", "sel": "#faq", "source": "src/components/Faq.astro:3"}]}]}]}]}


def write_site(folder: Path, url: str, doc: dict | None = None) -> Path:
    """The site's repo in folder: src/ files the source hints name, and docs/site.bluedoc.json (doc, else site_doc(url))."""
    for rel, text in {"src/pages/index.astro": "<Hero />\n", "src/content/site.ts": "export const hero = { headline: 'Track everything' };\n",
                      "src/components/Hero.astro": "<section class=\"hero\"></section>\n",
                      "src/components/Faq.astro": "---\n---\n<section id=\"faq\"></section>\n"}.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text, encoding="utf-8")
    path = folder / "docs" / "site.bluedoc.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc or site_doc(url), indent=1) + "\n", encoding="utf-8")
    return path


class WebsiteCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.doc_path = write_site(self.tmp.dir / "site", "http://localhost:4321/")
        self.doc = load_json(self.doc_path)

    def check(self, doc: dict):
        self.doc_path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        return self.tmp.run("build.py", self.doc_path, "--check", "--no-history")

    def page(self, doc: dict) -> dict:
        return board_of(doc)["artboards"][0]


class Validation(WebsiteCase):
    def test_the_live_doc_builds_clean(self) -> None:
        r = self.check(self.doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 error(s), 0 warning(s)", r.stderr)

    def test_a_live_page_must_be_a_loopback_dev_server(self) -> None:
        for url in ("http://127.0.0.2:3000/", "http://[::1]:5173/blog/", "https://localhost:8443/"):
            d = copy.deepcopy(self.doc)
            self.page(d)["url"] = url
            self.assertEqual(errors(self.check(d).stderr), [], url)
        for url, says in (("http://example.com/", "not a loopback host"), ("http://10.0.0.5:4321/", "not a loopback host"),
                          ("http://localhost.example.com/", "not a loopback host"), ("http://user:pw@localhost:4321/", "no credentials"),
                          ("file:///etc/passwd", "http:// or https://"), ("ftp://localhost/", "http:// or https://"), (4321, "a URL as a string")):
            d = copy.deepcopy(self.doc)
            self.page(d)["url"] = url
            errs = errors(self.check(d).stderr)
            self.assertTrue(any(".url:" in e and says in e for e in errs), (url, errs))

    def test_a_website_holds_pages_only(self) -> None:
        d = copy.deepcopy(self.doc)
        self.page(d)["device"] = "phone"
        r = self.check(d)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(any("a website holds pages only" in e for e in errors(r.stderr)), r.stderr)

    def test_website_fields_belong_to_websites(self) -> None:
        d = copy.deepcopy(self.doc)
        d["meta"]["type"] = "design"
        board_of(d)["viewport"] = {"1440": 900}
        errs = errors(self.check(d).stderr)
        for field in ("breakpoints", "viewport", "root"):
            if field in board_of(d):
                self.assertTrue(any(f".{field}:" in e and "only a website's board" in e for e in errs), (field, errs))
        for field in ("url", "source", "sections"):
            self.assertTrue(any(f".{field}:" in e and "only a website's page" in e for e in errs), (field, errs))

    def test_breakpoints(self) -> None:
        for bad in ([], [1440, 1440], [100], [1440, "768"], list(range(400, 1100, 100))):
            d = copy.deepcopy(self.doc)
            board_of(d)["breakpoints"] = bad
            self.assertTrue(any(".breakpoints:" in e for e in errors(self.check(d).stderr)), bad)
        d = copy.deepcopy(self.doc)
        board_of(d)["breakpoints"] = [1920, 1024, 375]
        self.assertEqual(errors(self.check(d).stderr), [])

    def test_viewport_heights(self) -> None:
        for bad in ([900], {"1440": "900"}, {"wide": 900}, {"1440": 100}, {"100": 900}, {"1440": True}):
            d = copy.deepcopy(self.doc)
            board_of(d)["viewport"] = bad
            self.assertTrue(any(".viewport:" in e for e in errors(self.check(d).stderr)), bad)
        d = copy.deepcopy(self.doc)
        board_of(d)["viewport"] = {"1440": 1000, "390": 700}
        self.assertEqual(errors(self.check(d).stderr), [])

    def test_source_hints_are_checked_against_the_repo(self) -> None:
        def hint_warnings(src: str) -> list[str]:
            d = copy.deepcopy(self.doc)
            self.page(d)["sections"][1]["source"] = src
            r = self.check(d)
            self.assertEqual(errors(r.stderr), [], src)
            return warnings(r.stderr)
        self.assertEqual(hint_warnings("src/components/Faq.astro:3"), [])
        self.assertEqual(hint_warnings("src/content/site.ts#hero"), [])
        self.assertTrue(any("'src/missing.ts' not found" in w for w in hint_warnings("src/missing.ts")))
        self.assertTrue(any("never names 'faq'" in w for w in hint_warnings("src/content/site.ts#faq")))
        self.assertTrue(any("points past them" in w for w in hint_warnings("src/components/Faq.astro:40")))
        for bad in ("../secrets.txt", "/etc/passwd", "http://localhost/x.ts", "src/x.ts#", "a b.ts"):
            d = copy.deepcopy(self.doc)
            self.page(d)["source"] = bad
            self.assertTrue(any(".source:" in e for e in errors(self.check(d).stderr)), bad)
        d = copy.deepcopy(self.doc)
        self.page(d)["source"] = ["a.ts", "b.ts", "c.ts", "d.ts"]
        self.assertTrue(any("up to 3" in e for e in errors(self.check(d).stderr)))

    def test_without_root_hints_go_unchecked(self) -> None:
        d = copy.deepcopy(self.doc)
        del board_of(d)["root"]
        self.page(d)["source"] = "src/missing.ts#nothing"
        r = self.check(d)
        self.assertIn("0 error(s), 0 warning(s)", r.stderr)

    def test_sections_and_variants(self) -> None:
        cases = [
            (lambda s: s.pop("decision"), "variants need a `decision`"),
            (lambda s: s.update(decision="nope"), "no decision item of the checklist `brief`"),
            (lambda s: s["variants"].update(c=[]), "'c' is no choice of brief/hero-headline"),
            (lambda s: s["variants"].update(b=[{"text": "x", "html": "<b>x</b>"}]), "{sel?, text} or {sel?, html}"),
            (lambda s: s["variants"].update(b=[{"html": "<iframe src=x></iframe>"}]), "<iframe>"),
            (lambda s: s.update(sel="<script>"), "the section's CSS selector"),
        ]
        for change, says in cases:
            d = copy.deepcopy(self.doc)
            change(self.page(d)["sections"][0])
            errs = errors(self.check(d).stderr)
            self.assertTrue(any(says in e for e in errs), (says, errs))
        d = copy.deepcopy(self.doc)
        self.page(d)["sections"][1]["id"] = "hero"
        self.assertTrue(any("duplicate section id 'hero'" in e for e in errors(self.check(d).stderr)))

    def test_a_live_page_has_no_screen_file(self) -> None:
        d = copy.deepcopy(self.doc)
        self.page(d)["src"] = "site.design/home.html"
        self.assertTrue(any("a live page (url) has no screen file" in e for e in errors(self.check(d).stderr)))
        self.assertEqual(build.screen_paths(self.doc, self.doc_path), {})


class NewWebsite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)

    def filled(self, path: Path) -> subprocess.CompletedProcess:
        raw = build.PLACEHOLDER.sub("Acme Fit", path.read_text(encoding="utf-8"))
        doc = json.loads(raw)
        for s in board_of(doc)["artboards"][0]["sections"]:   # a source hint and a selector, as the agent writes them
            if "<<" in json.dumps(s) or s.get("source") == "Acme Fit":
                s["source"] = "src/pages/index.astro"
            if s.get("sel") == "Acme Fit":
                s["sel"] = "main"
        if board_of(doc)["artboards"][0].get("source") == "Acme Fit":
            board_of(doc)["artboards"][0]["source"] = "src/pages/index.astro"
        for edits in (board_of(doc)["artboards"][0]["sections"][0].get("variants") or {}).values():
            for e in edits:
                if e.get("sel") == "Acme Fit":
                    e["sel"] = "h1"
        doc["meta"]["date"] = "2026-10-12"
        path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        return self.tmp.run("build.py", path, "--check", "--no-history")

    def test_a_stub_page_with_a_screen_file(self) -> None:
        out = self.tmp.dir / "site.bluedoc.json"
        r = self.tmp.run("build.py", "new", "website", out, "--title", "Acme Fit site")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = load_json(out)
        self.assertEqual((doc["meta"]["type"], doc["meta"]["kind"]), ("website", "Website"))
        page = board_of(doc)["artboards"][0]
        self.assertEqual((page["id"], page["device"], page["fidelity"]), ("home", "page", "wireframe"))
        self.assertNotIn("url", page)
        self.assertTrue((self.tmp.dir / "site.design" / "home.html").is_file())
        self.assertEqual([s["sel"] for s in page["sections"]], ['[data-bd="hero"]', '[data-bd="features"]'])
        r = self.filled(out)
        self.assertEqual(errors(r.stderr), [], r.stderr)

    def test_a_live_page_from_url(self) -> None:
        out = self.tmp.dir / "live.bluedoc.json"
        r = self.tmp.run("build.py", "new", "website", out, "--url", "http://localhost:4321/")
        self.assertEqual(r.returncode, 0, r.stderr)
        page = board_of(load_json(out))["artboards"][0]
        self.assertEqual(page["url"], "http://localhost:4321/")
        self.assertFalse((self.tmp.dir / "live.design").exists(), "a live page got a screen file")
        r = self.filled(out)
        self.assertEqual(errors(r.stderr), [], r.stderr)

    def test_url_is_for_websites_on_loopback_only(self) -> None:
        for args, says in ((["website", "a.bluedoc.json", "--url", "https://example.com/"], "not a loopback host"),
                           (["design", "b.bluedoc.json", "--url", "http://localhost:4321/"], "--url is for website docs")):
            r = self.tmp.run("build.py", "new", *args)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn(says, r.stderr)
            self.assertFalse((self.tmp.dir / args[1]).exists())


class Example(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.doc_path = self.docs / f"{STEM}.bluedoc.json"

    def test_the_example_builds_clean(self) -> None:
        r = self.tmp.run("build.py", self.doc_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 error(s), 0 warning(s)", r.stderr)

    def test_example_shape(self) -> None:
        doc = load_json(EXAMPLES / f"{STEM}.bluedoc.json")
        self.assertEqual(doc["meta"]["type"], "website")
        pages = board_of(doc)["artboards"]
        self.assertEqual([(a["id"], a["device"], "url" in a) for a in pages], [("home", "page", False), ("blog", "page", True)])
        self.assertEqual(build.check_contract(doc), [])
        self.assertTrue((EXAMPLES / f"{STEM}.design" / "home.html").is_file())
        self.assertFalse((EXAMPLES / f"{STEM}.design" / "blog.html").exists(), "the live page has a screen file")

    def test_patch_names_the_page_section_and_source(self) -> None:
        r = self.tmp.run("build.py", "patch", self.doc_path, "el:home/headline")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('acme-site.design/home.html  [data-bd="headline"]', r.stdout)
        self.assertIn('section hero ([data-bd="hero"]): src/content/home.ts#hero, src/components/Hero.astro', r.stdout)
        self.assertNotIn("section pricing", r.stdout)
        src = self.doc_path.read_bytes()
        r = self.tmp.run("build.py", "patch", self.doc_path, "el:blog/#subscribe>h2:nth-of-type(1)")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("live page http://localhost:4321/blog/  #subscribe>h2:nth-of-type(1)", r.stdout)
        self.assertIn("section subscribe (#subscribe): src/components/Subscribe.astro", r.stdout)
        self.assertNotIn("section posts", r.stdout)
        self.assertEqual(self.doc_path.read_bytes(), src, "printing where to edit wrote the doc")
        r = self.tmp.run("build.py", "patch", self.doc_path, "artboard:blog", "--html", "-")
        self.assertEqual(r.returncode, 2)
        self.assertIn("a live page has no screen file", r.stderr)

    def test_the_home_card(self) -> None:
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        server = Server(self.tmp)
        server.start()
        self.addCleanup(server.stop)
        status, raw = server.req("GET", "/__bluedoc/index.json", headers={"X-Bluedoc": "1"})
        self.assertEqual(status, 200)
        doc = next(d for r in json.loads(raw)["roots"] for d in r["docs"] if d["path"].endswith(f"{STEM}.bluedoc.json"))
        self.assertEqual(doc["type"], "website")
        self.assertEqual(doc["card"], {"count": 2, "sections": 7, "live": 1,
                                       "pages": [{"sections": 5, "live": False, "fidelity": "hifi"},
                                                 {"sections": 2, "live": True, "fidelity": "hifi"}]})


class ViewportUnits(unittest.TestCase):
    """Full page pins viewport heights: serve.py rewrites a live page's CSS and HTML styles, the inspector the sheets
    the proxy never sees, with one regex."""

    def test_heights_become_multiples_of_the_pinned_height(self) -> None:
        pin = serve.pin_viewport_units
        self.assertEqual(pin(".a{height:100vh}"), ".a{height:calc(100 * var(--bd-vh, 1vh))}")
        self.assertEqual(pin(".b { min-height: 50svh; top: -30dvh; margin: 1.5lvh 0 .5VH }"),
                         ".b { min-height: calc(50 * var(--bd-vh, 1vh)); top: calc(-30 * var(--bd-vh, 1vh)); "
                         "margin: calc(1.5 * var(--bd-vh, 1vh)) 0 calc(.5 * var(--bd-vh, 1vh)) }")
        self.assertEqual(pin(".c{width:20vmin;height:10svmax;padding:2vb}"),
                         ".c{width:calc(20 * min(1vw, var(--bd-vh, 1vh)));height:calc(10 * max(1vw, var(--bd-vh, 1vh)));"
                         "padding:calc(2 * var(--bd-vh, 1vh))}")
        self.assertEqual(pin("@media (min-height: 50vh) { .d { height: 10vh } }"),
                         "@media (min-height: 50vh) { .d { height: calc(10 * var(--bd-vh, 1vh)) } }", "a prelude stays")
        same = ".e { --x-100vh: 1; background: url(a-100vh.png); width: 100vw; height: calc(100% - 2rem); }"
        self.assertEqual(pin(same), same)
        once = pin(".f{height:calc(100vh - 64px)}")
        self.assertEqual(once, ".f{height:calc(calc(100 * var(--bd-vh, 1vh)) - 64px)}")
        self.assertEqual(pin(once), once, "pinning twice changes nothing")

    def test_html_styles_only(self) -> None:
        html = '<style>.h { height: 100vh }</style><div style="height: 50vh" title="100vh"><p>100vh tall</p></div>'
        self.assertEqual(serve.pin_html_units(html), '<style>.h { height: calc(100 * var(--bd-vh, 1vh)) }</style>'
                         '<div style="height: calc(50 * var(--bd-vh, 1vh))" title="100vh"><p>100vh tall</p></div>')

    def test_the_inspector_pins_alike(self) -> None:
        js = (SKILL / "assets" / "kits" / "inspector.js").read_text(encoding="utf-8")
        self.assertIn("const VU = /" + serve.VIEWPORT_UNIT.pattern + "/gi", js)
        self.assertIn("'var(--bd-vh, 1vh)'", js)


class LiveProxy(unittest.TestCase):
    """serve.py's proxy for a website's dev server, on the doc page's render."""

    def setUp(self) -> None:
        self.dev = StubDevServer()
        self.addCleanup(self.dev.stop)
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.doc_path = write_site(self.tmp.dir / "site", self.dev.origin + "/")
        self.assertEqual(self.tmp.run("serve.py", "add", self.doc_path.parent).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        c = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        c.request("GET", self.server.url_for(self.doc_path), headers={"Host": self.server.host})
        r = c.getresponse()
        self.page_csp, html = r.getheader("Content-Security-Policy") or "", r.read().decode()
        c.close()
        live = json.loads(html.split('<script type="application/json" id="bp-live">', 1)[1].split("</script>", 1)[0])
        self.assertEqual(list(live), [self.dev.origin])
        self.proxy = live[self.dev.origin]

    def get(self, path: str, headers: dict | None = None) -> tuple[int, dict, str]:
        """One request to the proxy; a header sent more than once (the site's CSP and the proxy's) comes joined by ', '."""
        c = http.client.HTTPConnection("127.0.0.1", self.proxy, timeout=10)
        try:
            c.request("GET", path, headers={"Host": f"127.0.0.1:{self.proxy}", **(headers or {})})
            r = c.getresponse()
            got: dict[str, str] = {}
            for k, v in r.getheaders():
                got[k.lower()] = f"{got[k.lower()]}, {v}" if k.lower() in got else v
            return r.status, got, r.read().decode("utf-8", "replace")
        finally:
            c.close()

    def test_the_doc_page_frames_its_proxy_only(self) -> None:
        self.assertIn(f"frame-src 'self' http://127.0.0.1:{self.proxy} http://localhost:{self.proxy};", self.page_csp)
        self.assertIn("frame-ancestors 'none'", self.page_csp)

    def test_the_page_comes_with_the_inspector_and_framable_by_bluedoc(self) -> None:
        status, headers, body = self.get("/")
        self.assertEqual(status, 200, body[:300])
        self.assertNotIn("x-frame-options", headers)
        csp = headers["content-security-policy"]
        self.assertNotIn("frame-ancestors 'none'", csp)
        self.assertIn("default-src 'self' 'unsafe-inline'", csp, "the site's own policy stays")
        self.assertIn(f"frame-ancestors http://127.0.0.1:{self.server.port} http://localhost:{self.server.port}", csp)
        head = body.index("<head>") + len("<head>")
        self.assertTrue(body[head:].startswith(f'<script src="/__bluedoc/inspector.js" data-parents="http://127.0.0.1:{self.server.port} '
                                                f'http://localhost:{self.server.port}" data-origin="{self.dev.origin}"></script>'), body[:400])
        self.assertIn('<h1 id="hero-title">Track everything</h1>', body)
        status, headers, js = self.get("/__bluedoc/inspector.js")
        self.assertEqual((status, headers["content-type"]), (200, "text/javascript; charset=utf-8"))
        self.assertIn("bluedoc inspector", js)

    def test_a_foreign_host_is_refused(self) -> None:
        for host in ("evil.example:80", f"127.0.0.1:{self.server.port}", f"127.0.0.1.evil.example:{self.proxy}"):
            status, _, _ = self.get("/", {"Host": host})
            self.assertEqual(status, 403, host)
        self.assertFalse(any(p == "/" for p, _ in self.dev.seen), "a refused request reached the dev server")

    def test_the_dev_server_sees_itself_and_no_key_cookie(self) -> None:
        status, _, body = self.get("/echo", {"Cookie": f"bluedoc_key_{self.server.port}=secret; theme=dark",
                                            "Origin": f"http://127.0.0.1:{self.proxy}"})
        self.assertEqual(status, 200)
        got = json.loads(body)
        self.assertEqual(got.get("Host"), f"127.0.0.1:{self.dev.port}")
        self.assertEqual(got.get("Cookie"), "theme=dark")
        self.assertEqual(got.get("Origin"), self.dev.origin)
        status, _, body = self.get("/echo", {"Cookie": f"bluedoc_key_{self.server.port}=secret"})
        self.assertNotIn("Cookie", json.loads(body))

    def test_a_dev_server_that_is_down_is_a_502(self) -> None:
        self.dev.stop()
        status, _, body = self.get("/")
        self.assertEqual(status, 502)
        self.assertIn("isn't answering", body)

    def test_viewport_units_are_pinned_in_css_html_and_css_modules(self) -> None:
        _, headers, css = self.get("/tall.css")
        self.assertIn(".hero { position: relative; height: calc(100 * var(--bd-vh, 1vh)); }", css)
        self.assertEqual(int(headers["content-length"]), len(css.encode()))
        _, _, html = self.get("/tall")
        self.assertIn('<header class="site-nav" style="height: calc(5 * var(--bd-vh, 1vh))">', html)
        self.assertIn(".band { height: calc(10 * var(--bd-vh, 1vh)); } @media (min-height: 50vh) {", html)
        _, _, mod = self.get("/src/hero.css")
        self.assertIn('".hero { min-height: calc(100 * var(--bd-vh, 1vh)); }"', mod)
        _, _, js = self.get("/app.js")
        self.assertEqual(js, 'export const tall = "100vh";\n', "only CSS is rewritten")


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class SiteInChrome(unittest.TestCase):
    """A website doc of one live page, the stub dev server's PATH, open in headless Chrome (1440 × 900), unlocked."""
    PATH = "/"

    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = Path(tempfile.mkdtemp(prefix="bluedoc-chrome-"))
        cls.browser = Browser(cls.profile)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        shutil.rmtree(cls.profile, ignore_errors=True)

    def setUp(self) -> None:
        self.dev = StubDevServer()
        self.addCleanup(self.dev.stop)
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.doc_path = write_site(self.tmp.dir / "site", self.dev.origin + self.PATH, self.site(self.dev.origin + self.PATH))
        self.assertEqual(self.tmp.run("serve.py", "add", self.doc_path.parent).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.browser.errors.clear()
        status, raw = self.server.req("POST", "/__bluedoc/unlock", b"{}", {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        self.url = f"http://{self.server.host}{self.server.url_for(self.doc_path)}?key={json.loads(raw)['token']}"
        self.tab = Tab(self.browser)
        self.tab.go(self.url)
        self.tab.wait_for("(b => b && b.artboards[0].ready)(BP.board())", 20)

    def on_frame(self, fx: float, fy: float) -> list[float]:
        """The window point over frame px (fx, fy) of the page's frame, at the board's zoom."""
        return self.tab.ev(f"(f => {{ const r = f.getBoundingClientRect(), k = r.width / f.width; return [r.left + {fx} * k, r.top + {fy} * k]; }})"
                           "(document.querySelector('iframe.bd-ab-fr'))")

    def pin_at(self, fx: float, fy: float, note: str) -> dict:
        """Point mode, a click at frame px (fx, fy), the note saved: the new annotation."""
        t = self.tab
        t.ev("BP.setMode('point')")
        x, y = self.on_frame(fx, fy)
        for kind, buttons in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
            self.browser.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "buttons": buttons, "clickCount": 1},
                              t.session)
            time.sleep(0.05)
        t.wait_for("!document.querySelector('.bd-cmp').hidden")
        t.ev(f"(ta => {{ ta.value = {json.dumps(note)}; ta.dispatchEvent(new Event('input')); }})(document.querySelector('.bd-cmp textarea'))")
        t.ev("document.querySelector('.bd-cmp .bp-btn.primary').click()")
        return t.wait_for(f"BP.annotations().find(a => a.note === {json.dumps(note)})")

    def site(self, url: str) -> dict:
        """The doc to serve, its page at url."""
        return site_doc(url)

    def page(self) -> dict:
        return self.tab.ev("BP.board().artboards[0]")


class LivePageInChrome(SiteInChrome):
    """The live page in the board: a variant pick shows in place, a pin carries its section's source hints and width
    into Request changes, and a breakpoint resizes the page."""

    def pin_title(self, note: str) -> dict:
        return self.pin_at(400, 140, note)

    def test_the_page_is_proxied(self) -> None:
        page = self.tab.ev("BP.board().artboards[0].page")
        self.assertTrue(page["proxied"])
        self.assertRegex(page["src"], r"^http://127\.0\.0\.1:\d+/$")
        self.assertNotEqual(page["src"], self.dev.origin + "/")
        self.assertEqual(self.browser.errors, [])

    def test_a_pin_carries_its_section_source_and_width(self) -> None:
        a = self.pin_title("One line at 390 px")
        self.assertEqual(a["target"]["key"], "el:home/#hero-title")
        self.assertEqual((a["target"]["section"], a["target"]["bp"]), ("hero", 1440))
        self.assertEqual(a["target"]["source"], ["src/content/site.ts#hero", "src/components/Hero.astro"])
        md = self.tab.ev("BP.changesPayload().markdown")
        self.assertIn("`el:home/#hero-title`", md)
        self.assertIn("   At: 1440 px wide\n   Source: `src/content/site.ts#hero`, `src/components/Hero.astro`\n   Change: One line at 390 px", md)

    def test_a_variant_pick_shows_in_place(self) -> None:
        self.assertEqual(self.tab.ev("BP.board().artboards[0].page.variants.hero.shown"), "a")
        self.tab.wait_for("!document.querySelector('.bd-var').hidden")
        self.tab.ev("document.querySelector('.bd-var button[data-id=b]').click()")
        self.assertEqual(self.tab.ev("BP.board().artboards[0].page.variants.hero.shown"), "b")
        a = self.pin_title("Shorter")
        self.assertEqual(a["target"]["text"], "Build the habit, one week at a time.", "the frame doesn't show version B")
        md = self.tab.ev("BP.changesPayload().markdown")
        self.assertIn("  Shown in: Home › Hero · Source: `src/content/site.ts#hero`, `src/components/Hero.astro`", md)

    def test_a_breakpoint_resizes_the_page(self) -> None:
        # a page shorter than the 390 px viewport (844) takes the viewport's height
        self.tab.ev("BP.board({breakpoint: 390})")
        self.tab.wait_for("(a => a.w === 390 && a.h === 844 && a.ready)(BP.board().artboards[0])")
        self.assertEqual(self.tab.ev("document.querySelector('iframe.bd-ab-fr').width"), "390")


class VersionsGutterInChrome(SiteInChrome):
    """A section's versions are editor chrome in the gutter right of its page: the bracket along the hero and its picker
    at the bracket's top lie outside the page and clear of the next page; pointing at the picker outlines the hero on
    the page at any zoom, and a pick changes the page and outlines the hero for a moment."""

    def site(self, url: str) -> dict:
        doc = site_doc(url)
        board_of(doc)["artboards"].append({"id": "about", "title": "About", "device": "page", "fidelity": "hifi", "url": url + "about"})
        return doc

    def setUp(self) -> None:
        super().setUp()
        self.tab.wait_for("(b => b.artboards[1].ready && b.artboards[0].page.sections.hero)(BP.board())", 15)
        self.tab.ev("BP.board({focus: 'home'})")   # fit shows both pages too small for the picker: the bracket alone
        self.tab.wait_for("(e => e && !e.hidden && e.offsetWidth > 0)(document.querySelector('.bd-ab[data-ab=home] .bd-var'))")

    def box(self, sel: str) -> list[float]:
        return self.tab.ev(f"(r => [r.left, r.top, r.right, r.bottom])(document.querySelector({json.dumps(sel)}).getBoundingClientRect())")

    def mouse(self, x: float, y: float, kinds=("mouseMoved",)) -> None:
        for kind in kinds:
            self.browser.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "buttons": int(kind == "mousePressed"), "clickCount": 1},
                              self.tab.session)
            time.sleep(0.05)

    def section_box(self) -> list[float]:
        """The hero's rect in the window, from the rect its frame reports."""
        s = self.page()["page"]["sections"]["hero"]
        f = self.box(".bd-ab[data-ab=home] iframe.bd-ab-fr")
        k = (f[2] - f[0]) / 1440
        return [f[0] + s["x"] * k, f[1] + s["y"] * k, f[0] + (s["x"] + s["w"]) * k, f[1] + (s["y"] + s["h"]) * k]

    def test_the_bracket_and_picker_sit_outside_every_page(self) -> None:
        home, about = self.box(".bd-ab[data-ab=home] .bd-ab-scr"), self.box(".bd-ab[data-ab=about] .bd-ab-scr")
        about[1] -= 40 * (about[2] - about[0]) / 1440   # with its browser bar
        for sel in (".bd-ab[data-ab=home] .bd-var", ".bd-ab[data-ab=home] .bd-var-br"):
            b = self.box(sel)
            self.assertGreaterEqual(b[0], home[2], f"{sel} {b} overlaps the page {home}")
            self.assertFalse(b[0] < about[2] and about[0] < b[2] and b[1] < about[3] and about[1] < b[3], f"{sel} {b} overlaps the next page {about}")
        hero = self.section_box()
        bracket = self.box(".bd-ab[data-ab=home] .bd-var-br")
        self.assertLessEqual(abs(bracket[1] - hero[1]) + abs(bracket[3] - hero[3]), 3, (bracket, hero))
        self.assertEqual(self.tab.ev("document.querySelectorAll('.bd-ab[data-ab=about] :is(.bd-var, .bd-var-br)').length"), 0)

    def test_pointing_at_the_picker_outlines_the_section(self) -> None:
        hl = ".bd-ab[data-ab=home] .bd-var-hl"
        for zoom in ("focus", "+"):
            if zoom == "+":
                k = self.tab.ev("BP.board().k")
                self.tab.ev("document.body.dispatchEvent(new KeyboardEvent('keydown', { key: '+', bubbles: true }))")
                self.tab.wait_for(f"BP.board().k > {k} * 1.2")
                time.sleep(0.5)
            self.assertTrue(self.tab.ev(f"document.querySelector({json.dumps(hl)}).hidden"), f"outlined at rest ({zoom})")
            p = self.box(".bd-ab[data-ab=home] .bd-var")
            self.mouse((p[0] + p[2]) / 2, (p[1] + p[3]) / 2)
            self.tab.wait_for(f"!document.querySelector({json.dumps(hl)}).hidden")
            got, want = self.box(hl), self.section_box()
            self.assertLessEqual(max(abs(g - w) for g, w in zip(got, want)), 2, (zoom, got, want))
            self.mouse(5, 450)
            self.tab.wait_for(f"document.querySelector({json.dumps(hl)}).hidden")

    def test_a_pick_changes_the_page_and_shows_the_section(self) -> None:
        b = self.box(".bd-ab[data-ab=home] .bd-var button[data-id=b]")
        self.mouse((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, ("mouseMoved", "mousePressed", "mouseReleased"))
        self.mouse(5, 450)
        self.assertEqual(self.page()["page"]["variants"]["hero"]["shown"], "b")
        hl = json.dumps(".bd-ab[data-ab=home] .bd-var-hl")
        self.assertFalse(self.tab.ev(f"document.querySelector({hl}).hidden"), "no outline right after the pick")
        self.tab.wait_for(f"document.querySelector({hl}).hidden", 3)
        a = self.pin_at(400, 140, "Shorter")
        self.assertEqual(a["target"]["text"], "Build the habit, one week at a time.", "the frame doesn't show version B")


class TitleBarsInChrome(SiteInChrome):
    """Each page's title bar stays within its page's width at every zoom, so neighbours never overlap: a narrow page
    drops the description, then the width and new-tab keys, while a page wide on screen keeps them all."""

    def site(self, url: str) -> dict:
        doc = site_doc(url)
        for i, name in enumerate(("Presentations page", "Credits and privacy page", "Everything else page")):
            board_of(doc)["artboards"].append({"id": f"p{i}", "title": name, "device": "page", "fidelity": "hifi", "url": url + f"p{i}"})
        return doc

    BARS = """[...document.querySelectorAll('.bd-ab[data-ab]')].map(e => {
        const t = e.querySelector('.bd-ab-t'), s = e.querySelector('.bd-ab-scr').getBoundingClientRect();
        const r = getComputedStyle(t).display === 'none' ? null : t.getBoundingClientRect();
        return { id: e.dataset.ab, page: [s.left, s.right], bar: r && [r.left, r.right, r.top, r.bottom],
                 keys: !!r && [...t.querySelectorAll('.bps, .opn')].some(k => k.offsetWidth > 0) };
      })"""

    def test_title_bars_stay_within_their_pages_at_every_zoom(self) -> None:
        self.tab.wait_for("BP.board().artboards.every(a => a.ready)", 15)
        self.tab.ev("BP.board({focus: 'home'})")
        time.sleep(0.6)
        home = next(b for b in self.tab.ev(self.BARS) if b["id"] == "home")
        self.assertTrue(home["keys"], "a page wide on screen keeps its width keys")
        for _ in range(8):
            k = self.tab.ev("BP.board().k")
            self.tab.ev("document.body.dispatchEvent(new KeyboardEvent('keydown', { key: '-', bubbles: true }))")
            self.tab.wait_for(f"BP.board().k < {k}")
            time.sleep(0.4)
            bars = [b for b in self.tab.ev(self.BARS) if b["bar"]]
            for b in bars:
                self.assertGreaterEqual(b["bar"][0], b["page"][0] - 0.5, (k, b))
                self.assertLessEqual(b["bar"][1], b["page"][1] + 0.5, (k, b))
            for i, a in enumerate(bars):
                for c in bars[i + 1:]:
                    p, q = a["bar"], c["bar"]
                    self.assertFalse(p[0] < q[1] - 0.5 and q[0] < p[1] - 0.5 and p[2] < q[3] and q[2] < p[3], (k, a["id"], c["id"]))
        self.assertFalse(any(b["keys"] for b in self.tab.ev(self.BARS)), "narrow pages drop their keys")


class OpenInNewTabInChrome(SiteInChrome):
    """Open in new tab: the toolbar's key opens the selected page, a live page at its dev server's own URL (not the
    proxy) and a mockup at its screen route on this server; each page's title bar key opens that page."""
    TOOLBAR_KEY = ".bd-btb button[aria-label='Open page in a new tab']"

    def site(self, url: str) -> dict:
        doc = site_doc(url)
        board_of(doc)["artboards"].append({"id": "about", "title": "About", "device": "page", "fidelity": "hifi"})
        screen = self.tmp.dir / "site" / "docs" / "site.design" / "about.html"
        screen.parent.mkdir(parents=True, exist_ok=True)
        screen.write_text("<main><h1>About Acme Fit</h1></main>\n", encoding="utf-8")
        return doc

    def setUp(self) -> None:
        super().setUp()
        self.tab.ev("window.open = (...a) => { (window.opened ||= []).push(a); return null; }")

    def click(self, sel: str) -> list:
        """Click sel: what it passed window.open."""
        self.tab.ev(f"(window.opened = [], document.querySelector({json.dumps(sel)}).click())")
        return self.tab.ev("window.opened")

    def about_route(self) -> str:
        return self.tab.ev("location.origin + location.pathname.replace(/[^/]*$/, '')") + "site.design/about.html"

    def test_the_toolbar_key_opens_the_live_page_at_its_dev_url(self) -> None:
        self.tab.ev("BP.board({focus: 'home'})")
        self.assertFalse(self.tab.ev(f"document.querySelector({json.dumps(self.TOOLBAR_KEY)}).disabled"))
        self.assertEqual(self.click(self.TOOLBAR_KEY), [[self.dev.origin + "/", "_blank", "noopener"]])

    def test_the_toolbar_key_opens_the_selected_page(self) -> None:
        self.tab.ev("BP.board({focus: 'about'})")
        self.assertEqual(self.click(self.TOOLBAR_KEY), [[self.about_route(), "_blank", "noopener"]])
        self.tab.ev("BP.board({focus: 'home'})")
        self.assertEqual(self.click(self.TOOLBAR_KEY), [[self.dev.origin + "/", "_blank", "noopener"]])

    def test_a_title_bar_key_opens_its_own_page(self) -> None:
        self.tab.ev("BP.board({focus: 'home'})")
        self.assertEqual(self.click(".bd-ab[data-ab=about] .bd-ab-t button[aria-label='Open About in a new tab']"),
                         [[self.about_route(), "_blank", "noopener"]])
        self.assertEqual(self.click(".bd-ab[data-ab=home] .bd-ab-t button[aria-label='Open Home in a new tab']"),
                         [[self.dev.origin + "/", "_blank", "noopener"]])
        self.assertEqual(self.tab.ev("BP.board().selected"), "home", "the title bar key leaves the selection")


class DesignBoardInChrome(SiteInChrome):
    """A design doc's board has no Open in new tab key, in its toolbar or a title bar."""

    def site(self, url: str) -> dict:
        doc = site_doc(url)
        doc["meta"]["type"] = "design"
        b = board_of(doc)
        del b["root"]
        b["artboards"] = [{"id": "home", "title": "Home", "device": "browser", "fidelity": "hifi"}]
        screen = self.tmp.dir / "site" / "docs" / "site.design" / "home.html"
        screen.parent.mkdir(parents=True, exist_ok=True)
        screen.write_text("<main><h1>Acme Fit</h1></main>\n", encoding="utf-8")
        return doc

    def test_no_open_in_new_tab_key(self) -> None:
        self.assertTrue(self.tab.ev("!!document.querySelector('.bd-btb .bd-tbtn')"))
        self.assertEqual(self.tab.ev("document.querySelectorAll(\".bd-btb button[aria-label='Open page in a new tab'], .bd-ab-t .opn\").length"), 0)


class FullPageInChrome(SiteInChrome):
    """Full page: the frame grows to the document with its viewport heights pinned (a 100vh hero stays 900 px tall),
    stays that tall, carries pins in board space and pans the board to a section, and zooms without a reload, a
    re-layout or the page seeing a scroll; Viewport is the old scrolling frame, remembered per doc."""
    PATH = "/tall"
    TALL = 45 + 900 + 90 + 2000   # the 5svh nav, the 100vh hero, the 10dvh band, the FAQ

    def setUp(self) -> None:
        super().setUp()
        self.tab.wait_for(f"BP.board().artboards[0].h === {self.TALL}", 15)

    def test_the_frame_is_as_tall_as_the_page_and_stays(self) -> None:
        a = self.page()
        self.assertEqual((a["w"], a["h"], a["page"]["view"], a["page"]["vh"]), (1440, self.TALL, "full", 900))
        self.assertEqual(a["page"]["frame"], [1440, self.TALL])
        time.sleep(3)
        a = self.page()
        self.assertEqual((a["h"], a["page"]["frame"], a["page"]["view"]), (self.TALL, [1440, self.TALL], "full"), "the page kept growing")
        self.assertEqual(self.browser.errors, [])

    def test_a_pin_sits_on_its_element_in_board_space(self) -> None:
        a = self.pin_at(350, 2555, "Say when it renews")   # #deep: 300 × 40 at 200, 2535
        self.assertEqual((a["target"]["key"], a["target"]["section"]), ("el:home/#deep", "faq"))

        def off() -> list[float]:
            want = self.on_frame(500, 2535)   # the element's top right, where its pin points
            got = self.tab.ev("(r => [r.left, r.bottom])(document.querySelector('.bd-ann-pin:not([hidden])').getBoundingClientRect())")
            return [abs(got[0] - want[0]), abs(got[1] - want[1])]
        self.assertLessEqual(max(off()), 6, off())
        self.tab.ev("BP.board({focus: 'home'})")   # another zoom and place: the pin follows without the frame scrolling
        time.sleep(0.6)
        self.assertLessEqual(max(off()), 6, off())

    def test_a_section_pans_the_board_to_it(self) -> None:
        self.tab.ev("BP.board({section: ['home', 'faq']})")
        time.sleep(0.6)
        b = self.tab.ev("BP.board()")
        self.assertEqual((b["selected"], b["k"]), ("home", min(1, b["k"])))
        top = self.on_frame(0, 45 + 900 + 90)[1]
        stage = self.tab.ev("(r => [r.top, r.bottom])(document.querySelector('.bd-board').getBoundingClientRect())")
        self.assertTrue(stage[0] <= top <= stage[1], (top, stage))

    def test_viewport_mode_is_the_scrolling_frame_and_is_remembered(self) -> None:
        self.tab.ev("BP.board({pageView: 'viewport'})")
        self.tab.wait_for("(a => a.h === 900 && a.page.view === 'viewport' && a.page.frame[1] === 900)(BP.board().artboards[0])")
        self.tab.go(self.url)
        self.tab.wait_for("(b => b && b.artboards[0].ready)(BP.board())", 20)
        time.sleep(1)
        self.assertEqual((self.tab.ev("BP.board().pageView"), self.page()["h"]), ("viewport", 900))
        self.tab.ev("BP.board({pageView: 'full'})")
        self.tab.wait_for(f"BP.board().artboards[0].h === {self.TALL}", 15)

    def test_a_breakpoint_pins_its_own_viewport(self) -> None:
        self.tab.ev("BP.board({breakpoint: 390})")   # 844 px tall at 390: the nav 42.2, the hero 844, the band 84.4
        self.tab.wait_for("(a => a.w === 390 && a.page.vh === 844 && Math.abs(a.h - (42.2 + 844 + 84.4 + 2000)) <= 1)(BP.board().artboards[0])", 15)

    def test_a_zoom_keeps_the_frame_and_the_page_still(self) -> None:
        """Wheel zoom in and out, the + and − buttons and Fit: the frame never reloads or remounts, reports no height
        and the board lays nothing out again; the page's IntersectionObservers watch the whole page, not the part the
        board shows, so the nav never leaves their view (a nav turning to glass mid-zoom flashed the frame blank)."""
        t, b = self.tab, self.browser
        time.sleep(0.6)   # the fit after the page grew, and the frame's last report of its size
        t.ev("""(() => { const m = window.__zoom = { loads: 0, mounts: 0, drops: 0, heights: 0, lays: 0, fr: document.querySelector('iframe.bd-ab-fr') };
          document.addEventListener('load', e => { if (e.target.tagName === 'IFRAME') m.loads++; }, true);
          new MutationObserver(rs => { for (const r of rs) {
            for (const n of r.addedNodes) if (n.nodeName === 'IFRAME') m.mounts++;
            for (const n of r.removedNodes) if (n.nodeName === 'IFRAME') m.drops++;
            if (r.type === 'attributes' && r.target.classList.contains('bd-ab')) m.lays++; } })
            .observe(document.querySelector('.bd-board'), { subtree: true, childList: true, attributes: true, attributeFilter: ['style'] });
          addEventListener('message', e => { if (e.data && e.data.bd === 'ready') m.heights++; }); })()""")
        frame = b.call("Page.getFrameTree", session=t.session)["frameTree"]["childFrames"][0]["frame"]["id"]
        world = b.call("Page.createIsolatedWorld", {"frameId": frame, "worldName": "zoom-test"}, t.session)["executionContextId"]
        seen = lambda: b.call("Runtime.evaluate", {"expression": "document.body.dataset.seen", "contextId": world, "returnByValue": True},
                              t.session)["result"]["value"].split()
        self.assertEqual(sorted(seen()), ["deep", "nav"], "the page's observers see the whole page, the % margin in design px")
        x, y = self.on_frame(700, 400)
        for dy in [-40] * 8 + [40] * 8:   # in to 400 %, the nav far above the view, and out
            b.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": dy, "modifiers": 2}, t.session)
            time.sleep(0.03)
        for label in ("Zoom in", "Zoom in", "Zoom out", "Fit all"):
            t.ev(f"document.querySelector('[aria-label^=\"{label}\"]').click()")
            time.sleep(0.1)
        time.sleep(0.5)
        self.assertEqual(sorted(seen()), ["deep", "nav"], "the page saw the zoom as a scroll")
        z = t.ev("(m => ({ loads: m.loads, mounts: m.mounts, drops: m.drops, heights: m.heights, lays: m.lays, same: m.fr === document.querySelector('iframe.bd-ab-fr') }))(window.__zoom)")
        self.assertEqual(z, {"loads": 0, "mounts": 0, "drops": 0, "heights": 0, "lays": 0, "same": True})
        self.assertEqual((self.page()["h"], self.page()["page"]["frame"]), (self.TALL, [1440, self.TALL]))
        t.ev("BP.board({breakpoint: {home: 1440}})")   # a re-layout at the same width: the probe sees one
        self.assertGreater(t.ev("window.__zoom.lays"), 0, "the re-layout probe sees nothing")
        self.assertEqual(self.browser.errors, [])


class GrowingPageInChrome(SiteInChrome):
    """A page that grows with its frame whatever the units (a 100% tall hero in a 100% tall body) falls back to
    Viewport instead of growing to the cap."""
    PATH = "/grow"

    def test_it_falls_back_to_viewport(self) -> None:
        self.tab.wait_for("(a => a.page.view === 'viewport' && a.h === 900 && a.page.frame[1] === 900)(BP.board().artboards[0])", 15)
        self.assertEqual(self.tab.ev("BP.board().pageView"), "full", "the board's view stays Full page")
        self.assertIn("keeps growing", self.tab.ev("document.getElementById('bp-toast').textContent"))


# a stored snapshot of the stub page as rev 1 had it: another headline, the same FAQ
REV1_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Acme Fit</title>
<style>body { margin: 0; font: 16px sans-serif; } .hero { position: relative; height: 600px; }
#hero-title { position: absolute; left: 100px; top: 100px; width: 600px; height: 80px; margin: 0; }</style></head>
<body><header class="site-nav">Acme Fit</header><section class="hero"><h1 id="hero-title">Rev one headline</h1></section>
<section id="faq"><h2>Questions</h2></section></body></html>"""


def snap_body(url: str, **over) -> bytes:
    """A POST /__bluedoc/snapshot body for the doc at url: rev 1's home page at 1440 px."""
    return json.dumps({"path": url, "rev": "1", "page": "home", "w": 1440, "html": REV1_PAGE, "external": 0, **over}).encode()


def patch_rev2(tmp: TempHome, doc_path: Path) -> subprocess.CompletedProcess:
    """Rev 1 -> 2: the agent changed the site's source and records it on the page."""
    return tmp.run("build.py", "patch", doc_path, "artboard:home", "--change", "Hero: a new headline.")


class SnapshotStore(unittest.TestCase):
    """POST /__bluedoc/snapshot stores a live page's snapshot for the doc's current rev beside the doc, cleaned of
    scripts, behind the key and a size cap; the screen route serves it for that rev; patch warns when the rev it
    replaces has none."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.doc_path = write_site(self.tmp.dir / "site", "http://localhost:4321/")
        self.assertEqual(self.tmp.run("build.py", self.doc_path).returncode, 0)   # rev 1 recorded
        self.assertEqual(self.tmp.run("serve.py", "add", self.doc_path.parent).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.url = self.server.url_for(self.doc_path)
        self.file = self.doc_path.parent / "site.bluedoc.snapshots" / "rev-1" / "home@1440.html"

    def post(self, body: bytes, key: str | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json", "X-Bluedoc": "1", **({"X-Bluedoc-Key": key} if key is not None else {})}
        status, raw = self.server.req("POST", "/__bluedoc/snapshot", body, headers)
        return status, json.loads(raw or b"{}")

    def test_a_snapshot_is_stored_beside_the_doc_without_scripts(self) -> None:
        html = REV1_PAGE.replace("</body>", "<script>alert(1)</script><base href='http://evil.example/'></body>")
        status, ans = self.post(snap_body(self.url, html=html, external=2))
        self.assertEqual((status, ans.get("file")), (200, "site.bluedoc.snapshots/rev-1/home@1440.html"), ans)
        text = self.file.read_text(encoding="utf-8")
        self.assertIn('<h1 id="hero-title">Rev one headline</h1>', text)
        self.assertNotIn("<script", text)
        self.assertNotIn("<base", text)
        self.assertRegex(text, r'<head><meta name="bluedoc-snapshot" content="external=2; at=\d{4}-')
        self.assertEqual(build.snapshot_index(self.doc_path), {"1": {"home": {"1440": 2}}})
        _, page = self.server.req("GET", self.url)
        snaps = json.loads(page.decode().split('<script type="application/json" id="bp-snaps">', 1)[1].split("</script>", 1)[0])
        self.assertEqual(snaps, {"1": {"home": {"1440": 2}}})

    def test_a_write_without_the_key_is_refused(self) -> None:
        status, ans = self.post(snap_body(self.url), key="not-the-key")
        self.assertEqual(status, 403, ans)
        self.assertFalse(self.file.exists())

    def test_the_size_cap_and_what_a_snapshot_must_name(self) -> None:
        big = REV1_PAGE.replace("</body>", "<p>" + "x" * serve.SNAPSHOT_MAX + "</p></body>")
        self.assertEqual(self.post(snap_body(self.url, html=big))[0], 413)
        for over, code in (({"rev": "2"}, 409), ({"page": "nope"}, 404), ({"w": 100}, 400), ({"w": "1440"}, 400),
                           ({"html": ""}, 400), ({"external": -1}, 400), ({"page": "../x"}, 404)):
            self.assertEqual(self.post(snap_body(self.url, **over))[0], code, over)
        self.assertFalse(self.file.parent.exists(), "a refused snapshot left a file")

    def test_an_earlier_revision_keeps_its_snapshot(self) -> None:
        self.assertEqual(self.post(snap_body(self.url))[0], 200)
        self.assertEqual(patch_rev2(self.tmp, self.doc_path).returncode, 0)
        status, ans = self.post(snap_body(self.url, html=STUB_PAGE))
        self.assertEqual(status, 409, ans)
        self.assertIn("Rev one headline", self.file.read_text(encoding="utf-8"))
        code, _ = serve.save_snapshot(self.doc_path, "1", "home", 1440, STUB_PAGE, 0, current_only=False)
        self.assertEqual(code, 409, "the CLI writes an earlier revision only where it has none")

    def test_the_screen_route_serves_the_revision_snapshot(self) -> None:
        self.assertEqual(self.post(snap_body(self.url))[0], 200)
        self.assertEqual(patch_rev2(self.tmp, self.doc_path).returncode, 0)
        route = self.url.replace("site.bluedoc.json", "site.design/home.html")
        c = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        c.request("GET", route + "?rev=1&w=390", headers={"Host": self.server.host})
        r = c.getresponse()
        csp, body = r.getheader("Content-Security-Policy") or "", r.read().decode()
        c.close()
        self.assertEqual(r.status, 200, body[:300])
        self.assertIn("Rev one headline", body, "the nearest width it has")
        self.assertIn('data-ids="1"></script>', body)
        self.assertIn("sandbox allow-scripts", csp)
        self.assertIn("img-src 'self'", csp)
        self.assertIn("http://localhost:4321", csp, "images it left on the dev server")
        self.assertEqual(self.server.req("GET", route + "?rev=2")[0], 404, "rev 2 has no snapshot")
        self.assertEqual(self.server.req("GET", route)[0], 404, "the current rev is the live page")

    def test_patch_warns_when_the_rev_it_replaces_has_no_snapshot(self) -> None:
        r = patch_rev2(self.tmp, self.doc_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("WARN  rev 1 has no snapshot of live page home", r.stderr)
        self.assertEqual(self.post(snap_body(self.url, rev="2"))[0], 200)
        r = self.tmp.run("build.py", "patch", self.doc_path, "artboard:home", "--change", "FAQ: one more question.")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("no snapshot", r.stderr)


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class SnapshotOnSendInChrome(SiteInChrome):
    """Request changes records the live page as the current rev's snapshot before the request goes, scriptless."""

    def test_request_changes_stores_a_snapshot(self) -> None:
        snaps = self.doc_path.parent / "site.bluedoc.snapshots"
        self.pin_at(400, 140, "Shorter")
        f = snaps / "rev-1" / "home@1440.html"
        until(lambda: f.is_file(), 8)   # the page records itself once it settles; that done, it takes none on its own
        shutil.rmtree(snaps, ignore_errors=True)
        t = self.tab
        t.ev("document.querySelector('.bd-key.go').click()")
        t.wait_for("(d => !!d && !d.querySelector('.ft .bp-btn:last-child').hidden)(document.querySelector('.bd-chgs[open]'))")
        t.ev("document.querySelector('.bd-chgs[open] .ft .bp-btn:last-child').click()")
        t.wait_for("(t => t.classList.contains('on') && t.textContent.toLowerCase().includes('change request sent'))(document.querySelector('#bp-toast'))", 20)
        self.assertTrue(f.is_file(), "the snapshot was stored before the request went")
        text = f.read_text(encoding="utf-8")
        self.assertIn('<h1 id="hero-title">Track everything</h1>', text)
        self.assertNotIn("<script", text)
        self.assertNotIn('id="bd-live"', text)
        self.assertEqual(t.ev("BP.board().snapshots"), {"1": {"home": {"1440": 0}}})
        self.assertEqual(self.browser.errors, [])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class EarlierRevisionInChrome(SiteInChrome):
    """At rev 2, rev 1 of the live page shows its snapshot (never the live page), labelled Snapshot · rev 1; without
    one, a placeholder that says so; compare (?diff=1) shows rev 1 beside rev 2, the changed hero outlined on both."""

    def unlocked(self, query: str) -> None:
        status, raw = self.server.req("POST", "/__bluedoc/unlock", b"{}", {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        self.tab.go(f"http://{self.server.host}{self.server.url_for(self.doc_path)}?{query}&key={json.loads(raw)['token']}")

    def to_rev2(self, snapshot: bool) -> None:
        """Leave the page (so it takes no snapshot of its own), store REV1_PAGE as rev 1's (snapshot), patch to rev 2."""
        self.browser.call("Page.navigate", {"url": "about:blank"}, self.tab.session)
        time.sleep(0.5)
        shutil.rmtree(self.doc_path.parent / "site.bluedoc.snapshots", ignore_errors=True)
        if snapshot:
            status, raw = self.server.req("POST", "/__bluedoc/snapshot", snap_body(self.server.url_for(self.doc_path)),
                                          {"Content-Type": "application/json", "X-Bluedoc": "1"})
            self.assertEqual(status, 200, raw)
        r = patch_rev2(self.tmp, self.doc_path)
        self.assertEqual(r.returncode, 0, r.stderr)

    def frame_eval(self, url_has: str, expr: str):
        """expr evaluated in the board's frame whose URL has url_has: a sandboxed frame runs in a process of its own
        (an iframe target), else in an isolated world of the page's session."""
        b = self.browser
        target = next((t for t in b.call("Target.getTargets")["targetInfos"] if t["type"] == "iframe" and url_has in t["url"]), None)
        if target:
            s = b.call("Target.attachToTarget", {"targetId": target["targetId"], "flatten": True})["sessionId"]
            return b.call("Runtime.evaluate", {"expression": expr, "returnByValue": True}, s)["result"].get("value")
        tree = b.call("Page.getFrameTree", session=self.tab.session)["frameTree"].get("childFrames", [])
        frame = next(f["frame"]["id"] for f in tree if url_has in f["frame"]["url"])
        world = b.call("Page.createIsolatedWorld", {"frameId": frame, "worldName": "snap-test"}, self.tab.session)["executionContextId"]
        return b.call("Runtime.evaluate", {"expression": expr, "contextId": world, "returnByValue": True}, self.tab.session)["result"].get("value")

    def test_an_earlier_rev_shows_its_snapshot_not_the_live_page(self) -> None:
        self.to_rev2(snapshot=True)
        self.unlocked("rev=1")
        a = self.tab.wait_for("(a => a.ready && a)(BP.board().artboards[0])", 15)
        self.assertEqual(a["page"]["snapshot"], {"rev": "1", "w": 1440})
        self.assertFalse(a["page"]["proxied"])
        self.assertIn("site.design/home.html?rev=1&w=1440", a["page"]["src"])
        self.assertEqual(a["page"]["badge"], "Snapshot · rev 1")
        self.assertEqual(self.tab.ev("document.querySelector('iframe.bd-ab-fr').getAttribute('sandbox')"), "allow-scripts")
        self.assertEqual(self.frame_eval("home.html?rev=1", "document.getElementById('hero-title').textContent"), "Rev one headline")
        self.assertEqual(self.tab.ev("document.querySelectorAll('iframe.bd-ab-fr').length"), 1, "only the snapshot, no live frame")
        self.assertEqual((a["page"]["sections"]["hero"]["w"], a["page"]["sections"]["hero"]["h"]), (1440, 600), "sections and readback work on the snapshot")
        self.assertEqual(self.browser.errors, [])

    def test_an_earlier_rev_without_a_snapshot_says_so(self) -> None:
        self.to_rev2(snapshot=False)
        self.unlocked("rev=1")
        time.sleep(1)
        a = self.tab.ev("BP.board().artboards[0]")
        self.assertFalse(a["live"], "no frame: never the live page posing as rev 1")
        self.assertEqual(a["page"]["why"], "No snapshot of rev 1: live pages are recorded when you send feedback")
        self.assertEqual(a["page"]["badge"], "No snapshot · rev 1")

    def test_compare_shows_both_revs_side_by_side_with_the_change_marked(self) -> None:
        self.to_rev2(snapshot=True)
        self.unlocked("diff=1")
        b = self.tab.wait_for("(b => b.twins.length && b.twins[0].ready && b.artboards[0].ready && b.twins[0].changed.length && b)(BP.board())", 20)
        a, t = b["artboards"][0], b["twins"][0]
        self.assertTrue(b["twin"])
        self.assertEqual((a["page"]["label"], t["label"]), ("Rev 2", "Rev 1"))
        self.assertEqual((t["snapshot"], a["page"]["proxied"]), ({"rev": "1", "w": 1440}, True))
        self.assertEqual((t["w"], t["y"]), (a["w"], a["y"]), "the same width, top aligned")
        self.assertLess(t["x"] + t["w"], a["x"], "rev 1 at the left of rev 2")
        self.assertEqual((a["page"]["changed"], t["changed"]), (["hero"], ["hero"]))
        self.assertEqual(self.tab.ev("document.querySelectorAll('.bd-ab .bd-sec-chg:not([hidden])').length"), 2)
        self.assertEqual(self.tab.ev("[...document.querySelectorAll('.bd-sec-l button.chg')].map(b => b.dataset.sec)"), ["hero"])
        self.assertEqual(self.frame_eval("home.html?rev=1", "document.getElementById('hero-title').textContent"), "Rev one headline")
        # the same breakpoint and height mode on both; Single drops the twin
        self.tab.ev("BP.board({breakpoint: 390})")
        b = self.tab.wait_for("(b => b.twins[0].w === 390 && b.artboards[0].w === 390 && b)(BP.board())", 15)
        self.tab.ev("BP.board({twin: false})")
        b = self.tab.ev("BP.board()")
        self.assertEqual((b["twin"], b["twins"][0]["shown"], b["artboards"][0]["page"]["label"]), (False, False, None))
        self.assertEqual(self.browser.errors, [])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class SnapshotCommand(unittest.TestCase):
    """`serve.py snapshot` records the current rev's live pages through headless Chrome, and an earlier rev that has
    none from another dev server (--url), never replacing one it has."""

    def setUp(self) -> None:
        self.dev = StubDevServer()
        self.addCleanup(self.dev.stop)
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.tmp.env["BLUEDOC_CHROME"] = CHROME
        self.doc_path = write_site(self.tmp.dir / "site", "http://localhost:4321/")
        self.assertEqual(self.tmp.run("build.py", self.doc_path).returncode, 0)

    def test_it_backfills_an_earlier_rev_from_another_dev_server(self) -> None:
        self.assertEqual(patch_rev2(self.tmp, self.doc_path).returncode, 0)
        r = self.tmp.run("serve.py", "snapshot", self.doc_path, "--rev", "1", "--url", self.dev.origin, "--width", "1440", timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        f = self.doc_path.parent / "site.bluedoc.snapshots" / "rev-1" / "home@1440.html"
        text = f.read_text(encoding="utf-8")
        self.assertIn('<h1 id="hero-title">Track everything</h1>', text)
        self.assertNotIn("<script", text)
        r = self.tmp.run("serve.py", "snapshot", self.doc_path, "--rev", "1", "--url", self.dev.origin, "--width", "1440", timeout=120)
        self.assertIn("has one already", r.stdout)
        self.assertEqual(f.read_text(encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()
