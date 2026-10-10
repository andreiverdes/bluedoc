"""Security corpus, from the reviews' probes (sec/hunk-xss, sec/c0-href, bld/comment-escape, sec/textconv) and the
design type's screen sandbox.

`build.validate` must reject the payloads; the template must not turn them into markup when a doc
skips validation (build.build doesn't validate). The page's JSON blocks parse as served when a doc quotes
`<!--` or `</script`. A diff ref never runs a command the repo's git config names (textconv), in a work tree or
in a bare repo inside the docs folder. The template's pure functions (safeUrl, inline, md and the diff
renderer's num) run under node when it is installed; the page-level checks need no node.

Design screens: the template frames them with sandbox="allow-scripts" only (never allow-same-origin) and the screen
route sends the sandbox CSP. With BLUEDOC_BROWSER_TESTS=1, an escape screen tries the parent page, storage, cookies,
fetch/XHR/WebSocket, top navigation, popups, an approval POST, a network image, a beacon and a form, framed and
opened on its own: every try fails and the server stores nothing."""
from __future__ import annotations

import copy
import http.client
import json
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import quote

from _support import Server, TempHome, template_slice, template_text
from test_page_state import CHROME, Browser, Tab, until

import build
import diffref

HUNK_PAYLOAD = "<img src=x onerror=document.title+='|PWNED'>"
C0_HREF = "\u0001javascript:document.title+='|PWNED';undefined"

# a minimal valid doc with an embedded (not ref) diff and links
BASE_DOC = {
    "id": "acme-probe", "title": "Acme probe", "meta": {"type": "other", "rev": "A"}, "tldr": "Acme probe doc.",
    "links": [{"label": "Acme site", "href": "https://acme.test/x"}, {"label": "Acme orders", "href": "acme-orders.bluedoc.json"},
              {"label": "Acme ops", "href": "mailto:ops@acme.test"}, {"label": "Code", "href": "#code"}],
    "sections": [{"id": "code", "title": "Code", "blocks": [{
        "type": "diff", "id": "d1", "title": "Acme change",
        "files": [{"path": "src/cart.ts", "status": "modified", "hunks": [{"old": 1, "new": 1, "lines": [" a", "-b", "+c"]}]},
                  {"path": "src/new.ts", "status": "added", "hunks": [{"old": 0, "new": 1, "lines": ["+x"]}]}]}]}],
}


def probe(**changes) -> dict:
    d = copy.deepcopy(BASE_DOC)
    hunk = d["sections"][0]["blocks"][0]["files"][0]["hunks"][0]
    for k, v in changes.items():
        if k == "href":
            d["links"][0]["href"] = v
        else:
            hunk[k] = v
            hunk["lines"] = []   # as in the probe: no lines, so nothing does arithmetic on the bad number
    return d


class ValidateRejects(unittest.TestCase):
    def test_probe_base_is_valid(self) -> None:
        rep = build.validate(copy.deepcopy(BASE_DOC))
        self.assertEqual(rep.errors, [])

    def test_non_integer_hunk_numbers(self) -> None:
        for field in ("old", "new"):
            for bad in (HUNK_PAYLOAD, "3", 1.5, True):
                with self.subTest(field=field, value=bad):
                    rep = build.validate(probe(**{field: bad}))
                    self.assertTrue(any("hunks[0]" in e for e in rep.errors), f"no hunk error in {rep.errors}")

    def test_control_prefixed_javascript_href(self) -> None:
        for bad in (C0_HREF, "\u0000javascript:x", "\u001fjavascript:x", " javascript:x", "\tjavascript:x", "JavaScript:x"):
            with self.subTest(href=bad):
                rep = build.validate(probe(href=bad))
                self.assertTrue(any("links" in e for e in rep.errors), f"no links error in {rep.errors}")


class PageDoesNotInject(unittest.TestCase):
    """build.build skips validation, so these hold even for a doc that never went through build.py."""

    def test_hunk_payload_stays_inside_the_json_data_block(self) -> None:
        html = build.build(probe(old=HUNK_PAYLOAD, new=HUNK_PAYLOAD), template_text())
        m = re.search(r'<script type="application/json" id="bp-doc">(.*?)</script>', html, re.S)
        self.assertIsNotNone(m)
        self.assertEqual(json.loads(m.group(1))["sections"][0]["blocks"][0]["files"][0]["hunks"][0]["old"], HUNK_PAYLOAD)
        self.assertNotRegex(m.group(1), r"(?i)</script")
        outside = html[:m.start(1)] + html[m.end(1):]
        self.assertNotIn("onerror=", outside)

    def test_diff_renderer_coerces_hunk_numbers(self) -> None:
        # the renderer builds an HTML string from the hunk header: every read of hk.old / hk.new goes through num()
        t = template_text()
        reads = [m.start() for m in re.finditer(r"\bhk\.(old|new)\b", t)]
        self.assertTrue(reads, "the diff renderer no longer reads hk.old / hk.new: update this test")
        for i in reads:
            self.assertEqual(t[i - 4:i], "num(", f"uncoerced hunk number at template offset {i}: {t[i - 40:i + 20]!r}")

    def test_doc_urls_go_through_safeUrl(self) -> None:
        # every href built from doc data (links[].href, a diff's url) is filtered by safeUrl
        t = template_text()
        sinks = re.findall(r"\bhref:\s*([^,}]+)", t)
        data = [s.strip() for s in sinks if re.search(r"\.(href|url)\b", s) and "location" not in s]
        self.assertTrue(data, "no doc-data href sinks found: update this test")
        for s in data:
            self.assertTrue(s.startswith("safeUrl("), f"href sink {s!r} doesn't go through safeUrl")

    def test_json_blocks_parse_as_served_when_a_doc_quotes_a_comment_opener(self) -> None:
        # a doc that shows HTML: the comment opener and a script close must stay text, and the block valid JSON
        quoted = "<!-- Acme banner -->\n<h1>Acme</h1>\n</script><script>document.title+='|PWNED'</script>"
        doc = copy.deepcopy(BASE_DOC)
        doc["sections"].append({"id": "snippet", "title": "Snippet", "blocks": [{"type": "code", "lang": "html", "code": quoted}]})
        state = {"version": 1, "state": {"code:d1:note": quoted}}
        html = build.build(doc, template_text(), state=state)
        for block_id in ("bp-doc", "bp-state"):
            with self.subTest(block=block_id):
                m = re.search(rf'<script type="application/json" id="{block_id}">(.*?)</script>', html, re.S)
                self.assertIsNotNone(m)
                self.assertNotIn("<!--", m.group(1))
                self.assertNotRegex(m.group(1), r"(?i)</script")
                got = json.loads(m.group(1))   # as the page's JSON.parse reads it: no unescaping first
                text = got["state"]["code:d1:note"] if block_id == "bp-state" else got["sections"][-1]["blocks"][0]["code"]
                self.assertEqual(text, quoted)


CSP_MUST = ("default-src 'none'", "connect-src 'none'", "form-action 'none'", "base-uri 'none'", "frame-ancestors 'self'",
            "sandbox allow-scripts")
GRANTS = ("allow-same-origin", "allow-top-navigation", "allow-popups", "allow-forms", "allow-modals")


class ScreenSandbox(unittest.TestCase):
    """Design screens are LLM HTML: the page frames them with sandbox="allow-scripts" only, and the screen route
    repeats the sandbox in its CSP, so a screen opened on its own runs with the same opaque origin."""

    def test_every_screen_frame_is_sandboxed_with_scripts_only(self) -> None:
        t = template_text()
        sandboxes = re.findall(r"sandbox['\"]?\s*[=:,]\s*['\"`]([^'\"`]*)['\"`]", t)
        self.assertTrue(sandboxes, "the template sets no sandbox on its screen frames")
        self.assertEqual(set(sandboxes), {"allow-scripts"})

    def test_the_screen_route_sends_the_sandbox_csp(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        docs = tmp.copy_examples()
        self.assertEqual(tmp.run("serve.py", "add", docs).returncode, 0)
        server = Server(tmp)
        server.start()
        self.addCleanup(server.stop)
        url = server.url_for(docs / "acme-fit-design.bluedoc.json")
        base = url.rsplit("/", 1)[0]
        for screen in ("watch-face", "login", "dashboard"):
            with self.subTest(screen=screen):
                c = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
                c.request("GET", f"{base}/acme-fit-design.design/{screen}.html", headers={"Host": server.host})
                r = c.getresponse()
                r.read()
                c.close()
                self.assertEqual(r.status, 200)
                csp = r.getheader("Content-Security-Policy") or ""
                for part in CSP_MUST:
                    self.assertIn(part, csp)
                for grant in GRANTS:
                    self.assertNotIn(grant, csp)
                self.assertNotIn("connect-src 'self'", csp)


# A screen that tries every way out the plan's risks name. Each attempt records 'blocked: <error>' or 'reached: …';
# the results go to the page by postMessage (and to window.__escape when the screen is the top document). The
# fire-and-forget tries (an image, a beacon, a form) come after the report: only the server and the CSP see them.
ESCAPE_SCREEN = """<main class="screen safe stack gap-4" data-bd="escape"><h1 class="title">Acme escape probe</h1></main>
<script>
(async () => {
  const out = {}, violations = [], framed = window !== top;
  document.addEventListener('securitypolicyviolation', e => violations.push(e.effectiveDirective || e.violatedDirective));
  const scheme = s => s + ':';   // literal network URLs fail the build's lint, so the probe assembles them
  const net = [scheme('https'), '', 'example.com', 'beacon.png'].join('/');
  const reach = v => 'reached: ' + String(v).slice(0, 80);
  const one = async (name, fn) => { try { out[name] = reach(await fn()); } catch (e) { out[name] = 'blocked: ' + (e && e.name); } };
  if (framed) {
    await one('parent.document', () => parent.document.title);
    await one('parent.localStorage', () => parent.localStorage.length);
    await one('top.location', () => { top.location.href = '/'; return 'navigated'; });
    await one('window.open', () => { if (!window.open('/')) throw new TypeError('no window'); return 'opened'; });
  }
  await one('localStorage', () => localStorage.length);
  await one('document.cookie', () => document.cookie);
  await one('fetch the server', () => fetch('/__bluedoc/ping').then(r => r.status));
  await one('fetch the network', () => fetch(net, { mode: 'no-cors' }).then(r => r.type));
  await one('post an approval', () => fetch('/__bluedoc/approve', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Bluedoc': '1' },
    body: JSON.stringify({ path: location.pathname, decision: 'approved', answers: [], annotations: [] }) }).then(r => r.status));
  await one('XMLHttpRequest', () => new Promise((ok, no) => { const x = new XMLHttpRequest(); x.open('GET', '/__bluedoc/ping');
    x.onload = () => ok(x.status); x.onerror = () => no(new TypeError('xhr failed')); x.send(); }));
  await one('WebSocket', () => new Promise((ok, no) => { const w = new WebSocket([scheme('ws'), '', location.host, ''].join('/')); w.onopen = () => ok('open');
    w.onerror = () => no(new TypeError('ws failed')); }));
  window.__escape = out;
  if (framed) parent.postMessage({ bdEscape: out }, '*');
  new Image().src = net;
  try { navigator.sendBeacon('/__bluedoc/changes', JSON.stringify({ annotations: [], message: 'Acme escape' })); } catch (e) {}
  const f = document.createElement('form');
  f.method = 'post'; f.action = '/__bluedoc/approve';
  document.body.append(f);
  try { f.submit(); } catch (e) {}
  setTimeout(() => { window.__violations = violations; if (framed) parent.postMessage({ bdViolations: violations }, '*'); }, 500);
})();
</script>
"""


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ScreenEscape(unittest.TestCase):
    """The escape screen in headless Chrome, framed by the design page and opened on its own: every attempt fails,
    the page stays where it was and the server stores nothing."""

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
        self.doc = docs / "acme-fit-design.bluedoc.json"
        doc = json.loads(self.doc.read_text(encoding="utf-8"))
        board = next(b for b in build.all_blocks(doc) if b.get("type") == "board")
        board["artboards"].insert(0, {"id": "escape", "title": "Escape probe", "device": "phone", "fidelity": "wireframe"})
        self.doc.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        (docs / "acme-fit-design.design" / "escape.html").write_text(ESCAPE_SCREEN, encoding="utf-8")
        self.assertEqual(self.tmp.run("serve.py", "add", docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.base = f"http://{self.server.host}"
        self.url = self.server.url_for(self.doc)
        self.browser.errors.clear()

    def tab(self) -> Tab:
        status, raw = self.server.req("POST", "/__bluedoc/unlock", b"{}", {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        t = Tab(self.browser)
        self.browser.call("Page.enable", session=t.session)
        self.browser.call("Page.addScriptToEvaluateOnNewDocument", {"source": (
            "addEventListener('message', e => { const d = e.data || {};"
            " if (d.bdEscape) window.__escape = d.bdEscape; if (d.bdViolations) window.__violations = d.bdViolations; });")},
            session=t.session)
        self.key = json.loads(raw)["token"]
        return t

    def assert_all_blocked(self, results: dict, names: set) -> None:
        self.assertEqual(set(results), names)
        reached = {k: v for k, v in results.items() if not v.startswith("blocked")}
        # document.cookie in an opaque origin throws; were it readable, it must at least not hold the server's key cookie
        if "document.cookie" in reached and reached["document.cookie"] == "reached: ":
            del reached["document.cookie"]
        self.assertEqual(reached, {}, "the screen got out")

    def assert_server_stored_nothing(self) -> None:
        ping = json.loads(self.server.req("GET", f"/__bluedoc/ping?path={quote(self.url)}", headers={"X-Bluedoc": "1"})[1])
        self.assertIsNone(ping["approval"])
        r = self.tmp.run("serve.py", "reply", self.doc)
        self.assertNotEqual(r.returncode, 0, f"the server stored a reply from the screen: {r.stdout}")

    def test_a_framed_screen_cannot_reach_the_page_the_server_or_the_network(self) -> None:
        t = self.tab()
        t.go(f"{self.base}{self.url}?key={self.key}")
        frames = t.wait_for("(f => f.length && f)([...document.querySelectorAll('iframe')].map(f => f.getAttribute('sandbox')))", 15)
        self.assertEqual(set(frames), {"allow-scripts"})
        results = t.wait_for("window.__escape", 15)
        self.assert_all_blocked(results, {"parent.document", "parent.localStorage", "top.location", "window.open", "localStorage",
                                          "document.cookie", "fetch the server", "fetch the network", "post an approval",
                                          "XMLHttpRequest", "WebSocket"})
        violations = set(t.wait_for("window.__violations", 10))
        self.assertIn("connect-src", violations)
        self.assertIn("img-src", violations, "the network image was not refused by the CSP")
        time.sleep(0.5)
        self.assertEqual(t.ev("location.pathname"), self.url, "the screen navigated the page")
        self.assertTrue(t.ev("!!window.BP"))
        self.assert_server_stored_nothing()

    def test_a_screen_opened_on_its_own_is_still_sandboxed(self) -> None:
        t = self.tab()
        t.go(f"{self.base}{self.url}?key={self.key}")   # sets the key cookie the screen must not read
        screen = f"{self.base}{self.url.rsplit('/', 1)[0]}/acme-fit-design.design/escape.html"
        self.browser.call("Page.navigate", {"url": screen}, t.session)
        results = until(lambda: settled(t, "location.href === %s && window.__escape" % json.dumps(screen)), 15)
        self.assertTrue(results, f"the screen never reported; page errors: {self.browser.errors}")
        self.assertEqual(t.ev("self.origin"), "null", "the CSP sandbox must give the screen an opaque origin")
        self.assert_all_blocked(results, {"localStorage", "document.cookie", "fetch the server", "fetch the network",
                                          "post an approval", "XMLHttpRequest", "WebSocket"})
        self.assertIn("connect-src", set(t.wait_for("window.__violations", 10)))
        self.assertEqual(t.ev("location.href"), screen, "the screen's form left the page")
        self.assert_server_stored_nothing()


def settled(t: Tab, expr: str):
    """expr in the tab, or None while a navigation has no document to evaluate it in yet."""
    try:
        return t.ev(expr)
    except (AssertionError, RuntimeError):
        return None


GIT = shutil.which("git")


@unittest.skipUnless(GIT, "git not installed")
class DiffRefRunsNoRepoCommand(unittest.TestCase):
    """A repo's config can name a textconv driver: a doc's diff ref must not run it (sec/textconv)."""

    def git(self, *args: str) -> str:
        return subprocess.run([GIT, "-c", "user.name=Acme", "-c", "user.email=dev@acme.test", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def test_textconv_driver_does_not_run(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="bluedoc-test-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        work, docs = tmp / "acme-src", tmp / "docs"
        docs.mkdir()
        self.git("init", "-q", str(work))
        (work / ".gitattributes").write_text("*.txt diff=acme\n", encoding="utf-8")
        for text in ("one\n", "two\n"):
            (work / "a.txt").write_text(text, encoding="utf-8")
            self.git("-C", str(work), "add", "-A")
            self.git("-C", str(work), "commit", "-qm", text.strip())
        base, head = self.git("-C", str(work), "rev-parse", "HEAD~1"), self.git("-C", str(work), "rev-parse", "HEAD")
        # the review's probe: a bare repo shipped as plain files inside the docs folder, and a work tree
        bare = docs / "vendored.git"
        self.git("clone", "-q", "--bare", str(work), str(bare))
        (bare / "info").mkdir(exist_ok=True)
        (bare / "info" / "attributes").write_text("*.txt diff=acme\n", encoding="utf-8")
        markers = {"work": tmp / "ran-work", "bare": tmp / "ran-bare"}
        for name, config in (("work", work / ".git" / "config"), ("bare", bare / "config")):
            self.git("config", "--file", str(config), "diff.acme.textconv", f"touch '{markers[name]}'; cat")
        ref = {"type": "diff", "base": base, "head": head}
        doc = {"id": "acme-textconv", "title": "Acme textconv probe", "meta": {"type": "review", "rev": "1"}, "tldr": "Probe.",
               "sections": [{"id": "code", "title": "Code", "blocks": [
                   {**ref, "id": "d-work", "title": "Work tree", "repo": str(work)},
                   {**ref, "id": "d-bare", "title": "Bare repo", "repo": "vendored.git"}]}]}
        doc_path = docs / "acme-textconv.bluedoc.json"
        doc_path.write_text(json.dumps(doc), encoding="utf-8")
        out, _ = diffref.expanded_copy(doc, doc_path, use_cache=False, write_cache=False, allow_remote=False)
        self.assertEqual([n for n, m in markers.items() if m.exists()], [], "git ran the repo's textconv command")
        lines = [ln for f in out["sections"][0]["blocks"][0]["files"] for hk in f["hunks"] for ln in hk["lines"]]
        self.assertEqual(lines, ["-one", "+two"], "the work tree's diff is no longer the plain one")


NODE = shutil.which("node")


def run_node(cases: list) -> list:
    """Evaluate the template's markdown-lite helpers and the diff renderer's num() over cases ([fn, arg])."""
    helpers = template_slice("/* ---------- markdown-lite ---------- */", "/* ---------- storage ---------- */")
    num = re.search(r"const num = x => [^\n]*;", template_text())
    assert num, "the diff renderer's `const num = x => …;` is gone: update this test"
    js = ("const src = require('fs').readFileSync(0, 'utf8'); const {code, cases} = JSON.parse(src);"
          "const fns = new Function(code + '\\nreturn { esc, safeUrl, inline, md, num };')();"
          "process.stdout.write(JSON.stringify(cases.map(([f, a]) => fns[f](a))));")
    r = subprocess.run([NODE, "-e", js], input=json.dumps({"code": helpers + "\n" + num.group(0), "cases": cases}),
                       capture_output=True, text=True, timeout=20)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node not installed")
class TemplateFunctions(unittest.TestCase):
    BAD = [C0_HREF, "\u0000javascript:x", "\u001fjavascript:alert(1)", " javascript:x", "\tjavascript:x", "java\tscript:x",
           "java\nscript:x", "JAVASCRIPT:x", "data:text/html,x", "vbscript:x", "file:///etc/passwd"]
    GOOD = ["https://acme.test/a?b=1", "http://acme.test", "mailto:ops@acme.test", "#item-t412-tier-boundary",
            "#node:acme-orders/api", "acme-orders.bluedoc.json", "../runbooks/acme.md", "/acme/x"]

    def test_safeUrl_allow_list(self) -> None:
        out = run_node([["safeUrl", u] for u in self.BAD + self.GOOD])
        for u, got in zip(self.BAD, out):
            self.assertEqual(got, "#", f"safeUrl({u!r})")
        for u, got in zip(self.GOOD, out[len(self.BAD):]):
            self.assertEqual(got, u, f"safeUrl({u!r})")

    def test_markdown_links_with_bad_schemes_become_hash(self) -> None:
        srcs = [f"[go]({u})" for u in self.BAD if not any(c.isspace() for c in u)]   # a markdown url has no whitespace
        out = run_node([["inline", s] for s in srcs] + [["md", "Read [the runbook](" + C0_HREF + ") first."]])
        for s, got in zip(srcs, out):
            self.assertEqual(got, '<a href="#">go</a>', f"inline({s!r})")
        self.assertIn('<a href="#">the runbook</a>', out[-1])
        self.assertNotIn("javascript", out[-1])

    def test_inline_escapes_markup(self) -> None:
        out = run_node([["inline", HUNK_PAYLOAD], ["inline", '[x](https://acme.test/"onmouseover="alert(1))']])
        self.assertNotIn("<img", out[0])
        self.assertNotRegex(out[1], r'href="[^"]*"onmouseover')

    def test_num_makes_hunk_numbers_integers(self) -> None:
        vals = [HUNK_PAYLOAD, "12", 3.7, None, {}, "1e3", -2]
        out = run_node([["num", v] for v in vals])
        for v, got in zip(vals, out):
            self.assertIsInstance(got, int, f"num({v!r}) = {got!r}")
        self.assertEqual(out[:2], [0, 12])


if __name__ == "__main__":
    unittest.main()
