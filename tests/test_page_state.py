"""The page's state sync in a real browser: headless Chrome over the DevTools protocol, on pages `serve.py run` serves.

Two docs with one doc.id each keep their own outbox (st/shared-outbox). A wider folder leaves a doc's URL as it was,
and a write the server answers with 404 stays in the outbox and reaches the server once the URL answers again
(st/url-move). Approve on a page whose doc was edited in place after it loaded is refused, and the page offers
Reload (st/approval-unseen). An approval holds through a rev that only marks a step done (Approved · rev 1 · progress
in rev 2) and not through a text edit (Changes since approved rev 1) (st/approval-carry). A doc that quotes an HTML
comment opener renders (bld/comment-escape). A plan's item comments and every page's "Need more details" items count
toward Request changes and go with it (rc/items). A design board's link edits and moved screens are drafts in reader
state that go with Request changes with a `patch` command each and are resolved once the doc has them, or marked stale
when a newer rev changed the link (bd/link-edit, bd/move). A review's findings section shows Merged (each finding's
full row under its lines, in code order), its checklist or its diff, as [Merged][Checklist][Diff] in a sticky bar under
its title picks and the browser remembers; picks sync across the three, Merged keeps item and line keys and item
links, and links into a hidden view show it; an open finding in Checklist shows its comment's file, lines and card,
whose pick and pins are the diff's. A browser that loses the key
cookie (Tern's WKWebView keeps none) still saves with the key the page kept in localStorage while it had the cookie.
The reader renames a doc and picks its emoji in its header or app bar: they hold through a reload and show in the tab
and the home index, never in a reply or the doc's JSON, and ?rev= shows them as text (rt/name). The reader archives a
doc from its page or a home card; the home page hides it from its views, counts and widgets and says when a search or
filter hides it; a new rev brings it back; an all-done plan offers Archive and Not now (rt/archive).

The browser tests run only with BLUEDOC_BROWSER_TESTS=1 and Chrome installed (BLUEDOC_CHROME names it when it isn't
in a usual place); each starts Chrome with a temp profile and the server on a free port. The URL check needs no browser."""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import quote

from _support import Server, TempHome

NOTE_ITEM, NOTE_KEY = "checks/unit", "checks:unit:note"   # a checklist item of the example plan, as the page and the server name it


def find_chrome() -> str | None:
    if os.environ.get("BLUEDOC_CHROME"):
        return os.environ["BLUEDOC_CHROME"]
    for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "google-chrome-stable",
              "chromium", "chromium-browser"):
        found = p if os.path.isfile(p) else shutil.which(p)
        if found:
            return found
    return None


CHROME = find_chrome() if os.environ.get("BLUEDOC_BROWSER_TESTS") == "1" else None


def until(fn, timeout: float = 8):
    """fn() once it is truthy, polling; its last value when the time runs out."""
    deadline = time.monotonic() + timeout
    while True:
        v = fn()
        if v or time.monotonic() > deadline:
            return v
        time.sleep(0.1)


class Browser:
    """Headless Chrome with its own profile, driven over one DevTools WebSocket (flat sessions, one per tab)."""

    def __init__(self, profile: Path) -> None:
        self.proc = subprocess.Popen([CHROME, "--headless=new", f"--user-data-dir={profile}", "--remote-debugging-port=0",
                                      "--no-first-run", "--no-default-browser-check", "about:blank"],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        active, deadline = profile / "DevToolsActivePort", time.monotonic() + 20
        while not (active.is_file() and len(active.read_text().split()) >= 2):
            if self.proc.poll() is not None or time.monotonic() > deadline:
                self.close()
                raise RuntimeError("Chrome did not start")
            time.sleep(0.05)
        port, path = active.read_text().split()[:2]
        self.sock = socket.create_connection(("127.0.0.1", int(port)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        self.buf, self.seq, self.errors = b"", 0, []
        while b"\r\n\r\n" not in self.buf:
            self.buf += self._recv()
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise RuntimeError(f"DevTools refused the WebSocket: {head[:200]!r}")

    def close(self) -> None:
        if getattr(self, "sock", None):
            self.sock.close()
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()

    def _recv(self) -> bytes:
        chunk = self.sock.recv(65536)
        if not chunk:
            raise ConnectionError("DevTools closed the connection")
        return chunk

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            self.buf += self._recv()
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send_frame(self, opcode: int, data: bytes) -> None:
        n, mask = len(data), os.urandom(4)   # a client masks every frame
        size = bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + n.to_bytes(2, "big") if n < 65536 else bytes([0x80 | 127]) + n.to_bytes(8, "big")
        masked = (int.from_bytes(data, "big") ^ int.from_bytes((mask * (n // 4 + 1))[:n], "big")).to_bytes(n, "big")
        self.sock.sendall(bytes([0x80 | opcode]) + size + mask + masked)

    def _message(self) -> dict:
        parts = []
        while True:
            b0, b1 = self._read(2)
            op, n = b0 & 0x0F, b1 & 0x7F
            if n >= 126:
                n = int.from_bytes(self._read(2 if n == 126 else 8), "big")
            data = self._read(n)
            if op == 8:
                raise ConnectionError("DevTools closed the WebSocket")
            if op == 9:
                self._send_frame(10, data)
            elif op in (0, 1, 2):
                parts.append(data)
                if b0 & 0x80:
                    return json.loads(b"".join(parts))

    def call(self, method: str, params: dict | None = None, session: str | None = None) -> dict:
        self.seq += 1
        self._send_frame(1, json.dumps({"id": self.seq, "method": method, "params": params or {},
                                        **({"sessionId": session} if session else {})}).encode())
        while True:
            m = self._message()
            if m.get("id") == self.seq:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
            if m.get("method") == "Runtime.exceptionThrown":
                d = m["params"]["exceptionDetails"]
                self.errors.append((d.get("exception") or {}).get("description") or d.get("text"))


class Tab:
    def __init__(self, browser: Browser) -> None:
        self.browser = browser
        target = browser.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.session = browser.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        browser.call("Runtime.enable", session=self.session)
        browser.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False},
                     session=self.session)

    def ev(self, expr: str):
        r = self.browser.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True}, self.session)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise AssertionError(f"{expr}: {(d.get('exception') or {}).get('description') or d.get('text')}")
        return r["result"].get("value")

    def wait_for(self, expr: str, timeout: float = 10):
        got = until(lambda: self.ev(expr), timeout)
        if not got:
            raise AssertionError(f"timed out waiting for {expr}; page errors: {self.browser.errors}")
        return got

    def go(self, url: str) -> None:
        """Load url (again, when it is the current one) and wait until the page script has run."""
        self.ev("window.__bdLeft = true")
        self.browser.call("Page.navigate", {"url": url}, self.session)
        self.wait_for("!window.__bdLeft && document.readyState === 'complete' && !!window.BP")


class ChromePage(unittest.TestCase):
    """Chrome for the class; for each test, the examples in a temp home and `serve.py run` on a free port."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = Path(tempfile.mkdtemp(prefix="bluedoc-chrome-"))
        cls.browser = Browser(cls.profile)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        shutil.rmtree(cls.profile, ignore_errors=True)

    def setUp(self) -> None:
        # each test has its own server port, so its own origin and localStorage in the shared profile
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples("w/docs")
        self.plan = self.docs / "acme-saved-carts-plan.bluedoc.json"
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.base = f"http://{self.server.host}"
        self.browser.errors.clear()

    def open(self, url: str) -> Tab:
        """A new tab on url, through a ?key= link (what `serve.py open` prints), so the page may save."""
        status, raw = self.server.req("POST", "/__bluedoc/unlock", b"{}", {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        t = Tab(self.browser)
        t.go(f"{self.base}{url}?key={json.loads(raw)['token']}")
        return t

    def state(self, url: str) -> dict:
        status, raw = self.server.req("GET", f"/__bluedoc/state?path={quote(url)}", headers={"X-Bluedoc": "1"})
        return json.loads(raw)["state"] if status == 200 else {}

    def toast(self, tab: Tab, has: str) -> str:
        return tab.wait_for(f"(t => t && t.classList.contains('on') && t.textContent.toLowerCase().includes({json.dumps(has)}) && t.textContent)"
                            "(document.querySelector('#bp-toast'))")

    def send_changes(self, tab: Tab, says: str) -> None:
        """Request changes through the dialog; its count line says `says`."""
        tab.ev(f"{GO}.click()")
        tab.wait_for("(d => !!d && !d.querySelector('.ft .bp-btn:last-child').hidden)(document.querySelector('.bd-chgs[open]'))")
        self.assertIn(says, tab.ev("document.querySelector('.bd-chgs[open] .cnt').textContent"))
        tab.ev("document.querySelector('.bd-chgs[open] .ft .bp-btn:last-child').click()")
        self.toast(tab, "change request sent")

    def reply(self, doc: Path, *flags: str) -> str:
        r = self.tmp.run("serve.py", "reply", doc, "--kind", "changes", *flags)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class PageSync(ChromePage):
    def test_two_paths_with_one_doc_id_keep_their_own_outbox(self) -> None:
        copy = self.docs / "acme-saved-carts-copy.bluedoc.json"
        shutil.copy(self.plan, copy)
        url_a, url_b = self.server.url_for(self.plan), self.server.url_for(copy)
        a, b = self.open(url_a), self.open(url_b)
        self.assertTrue(a.ev(f"BP.setNote('{NOTE_ITEM}', 'Written in tab A')"))
        b.ev("dispatchEvent(new Event('online'))")   # B flushes within A's 300 ms debounce, as a tab switch does
        self.assertEqual(until(lambda: self.state(url_a).get(NOTE_KEY)), "Written in tab A")
        time.sleep(0.5)
        self.assertNotIn(NOTE_KEY, self.state(url_b), "tab B sent tab A's note to its own doc")

    def test_a_write_the_server_answers_404_stays_until_it_is_sent(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        a.ev(f"BP.setNote('{NOTE_ITEM}', 'First')")
        self.assertEqual(until(lambda: self.state(url).get(NOTE_KEY)), "First")
        # a wider folder joins (what `open` on a doc above docs/ does): the doc keeps its URL, the open tab keeps syncing
        self.assertEqual(self.tmp.run("serve.py", "add", self.tmp.dir / "w").returncode, 0)
        self.assertEqual(self.server.url_for(self.plan), url)
        a.ev(f"BP.setNote('{NOTE_ITEM}', 'Second')")
        self.assertEqual(until(lambda: self.state(url).get(NOTE_KEY) == "Second" and "Second"), "Second")
        # the review's probe: roots.json loses the folder the URL names, so the next PUT gets 404
        roots = self.tmp.home / "roots.json"
        saved = roots.read_text(encoding="utf-8")
        roots.write_text(json.dumps([str(self.tmp.dir / "w")]), encoding="utf-8")
        self.assertEqual(self.server.req("GET", url)[0], 404)
        a.ev(f"BP.setNote('{NOTE_ITEM}', 'Third')")
        self.toast(a, "no longer serves this doc")   # the reader is told the edit waits in the browser
        roots.write_text(saved, encoding="utf-8")
        a.ev("dispatchEvent(new Event('online'))")
        self.assertEqual(until(lambda: self.state(url).get(NOTE_KEY) == "Third" and "Third"), "Third", "the 404 dropped the write")
        a.go(self.base + url)
        self.assertEqual(a.ev(f"localStorage.getItem('bp:' + BP.doc.id + ':{NOTE_KEY}')"), "Third")

    def test_approve_after_an_unseen_edit_is_refused(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        r = self.tmp.run("build.py", "patch", self.plan, "tldr", "--set", "tldr=Acme changed this after the page loaded.", "--no-bump")
        self.assertEqual(r.returncode, 0, r.stderr)
        a.ev("document.querySelector('.bd-key.approve').click()")
        a.wait_for("!!document.querySelector('.bd-approve[open] .bp-btn.ok')")
        a.ev("document.querySelector('.bd-approve[open] .bp-btn.ok').click()")
        self.toast(a, "reload")
        self.assertEqual(a.ev("document.querySelector('#bp-toast button')?.textContent"), "Reload")
        ping = json.loads(self.server.req("GET", f"/__bluedoc/ping?path={quote(url)}", headers={"X-Bluedoc": "1"})[1])
        self.assertIsNone(ping["approval"])

    def test_marking_steps_done_keeps_an_approval(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        a.ev("document.querySelector('.bd-key.approve').click()")
        a.wait_for("!!document.querySelector('.bd-approve[open] .bp-btn.ok')")
        a.ev("document.querySelector('.bd-approve[open] .bp-btn.ok').click()")
        self.toast(a, "approved")
        chip = "[document.querySelector('.bd-planchip').textContent, document.querySelector('.bd-key.approve').disabled, BP.planState().state]"
        self.assertEqual(a.ev(chip), ["Approved · rev 1", True, "approved"])
        # rev 2 only marks a step done: still approved; rev 3 changes a step's text: approve again
        for key, field, says, disabled, state in (
                ("step:steps/0/table", "status=done", "Approved · rev 1· progress in rev 2", True, "approved"),
                ("step:steps/0/repo", "title=Acme: a new repo step", "Changes since approved rev 1", False, "stale")):
            with self.subTest(key):
                r = self.tmp.run("build.py", "patch", self.plan, key, "--set", field, "--change", f"Acme: {key}.")
                self.assertEqual(r.returncode, 0, r.stderr)
                a.go(f"{self.base}{url}")
                a.wait_for(f"document.querySelector('.bd-planchip').textContent === {json.dumps(says)}")
                self.assertEqual(a.ev(chip), [says, disabled, state])

    def test_a_doc_quoting_a_comment_opener_renders(self) -> None:
        quoted = "<!-- Acme banner -->\n<h1>Acme</h1>"
        doc = json.loads(self.plan.read_text(encoding="utf-8"))
        doc["id"] = "acme-snippet"
        doc["sections"].append({"id": "snippet", "title": "Snippet", "blocks": [{"type": "code", "lang": "html", "code": quoted}]})
        path = self.docs / "acme-snippet.bluedoc.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        a = self.open(self.server.url_for(path))
        self.assertEqual(a.ev("BP.doc.sections.at(-1).blocks[0].code"), quoted)

    def test_a_browser_without_cookies_saves_with_the_key_it_kept(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        key = (self.tmp.home / "key").read_text(encoding="utf-8").strip()
        self.assertEqual(a.wait_for("localStorage.getItem('bluedoc:key:' + location.port)"), key)
        self.browser.call("Network.enable", session=a.session)
        self.browser.call("Network.clearBrowserCookies", session=a.session)
        cookies = lambda: self.browser.call("Network.getCookies", {"urls": [self.base]}, a.session)["cookies"]  # noqa: E731
        self.assertEqual(cookies(), [])
        # what the reloaded page's fetches get: the ping's `unlocked`, each state PUT's status
        self.browser.call("Page.enable", session=a.session)
        self.browser.call("Page.addScriptToEvaluateOnNewDocument", {"source": (
            "(() => { window.__pings = []; window.__puts = []; const f = window.fetch;"
            " window.fetch = (u, o) => f(u, o).then(r => { const s = String(u);"
            " if (s.startsWith('/__bluedoc/ping')) r.clone().json().then(j => __pings.push(j.unlocked));"
            " else if (s === '/__bluedoc/state' && o && o.method === 'PUT') __puts.push(r.status);"
            " return r; }); })();")}, session=a.session)
        a.go(self.base + url)
        self.assertEqual(a.wait_for("__pings.length && __pings"), [True])
        a.ev(f"BP.setNote('{NOTE_ITEM}', 'Acme: saved without the cookie')")
        self.assertEqual(until(lambda: self.state(url).get(NOTE_KEY)), "Acme: saved without the cookie")
        self.assertEqual(set(a.wait_for("__puts.length && __puts")), {200})
        self.assertFalse(a.ev("!!document.querySelector('.bd-lockbar')"), "the page says it can't save")
        self.assertEqual(cookies(), [], "the save came with the cookie, not the stored key")


GO = "document.querySelector('.bd-key.go')"   # the tray's Request changes key


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ItemRequests(ChromePage):
    """Request changes counts what goes with it beside the pending annotations (rc/items): on a plan, a comment on an
    item written or changed since the last send; on every page, a decision item marked "Need more details", which shows
    "Details requested" once sent and resets on a newer rev."""

    def count(self, tab: Tab) -> list:
        """[disabled, the number on the key]"""
        return tab.ev(f"(b => [b.disabled, b.querySelector('.n').textContent])({GO})")

    def test_a_comment_on_a_plan_item_is_a_change_request(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        self.assertEqual(self.count(a), [True, "0"])
        a.ev("BP.setNote('decisions/retention', 'Say what 180 days costs in storage.')")
        self.assertEqual(self.count(a), [False, "1"])
        self.send_changes(a, "1 comment on items")
        self.assertEqual(self.count(a), [True, "0"])
        decisions = self.reply(self.plan).split("## Decisions", 1)[1]
        self.assertIn("`item:decisions/retention`", decisions)
        self.assertIn("  > Say what 180 days costs in storage.", decisions)
        # sent stays sent across a reload; an edited comment is pending again
        until(lambda: self.state(url).get("decisions:retention:note-sent"))
        a.go(self.base + url)
        self.assertEqual(self.count(a), [True, "0"])
        a.ev("BP.setNote('decisions/retention', 'Say what 180 days costs a month.')")
        self.assertEqual(self.count(a), [False, "1"])

    def test_need_more_details_on_a_plan(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        row = "document.querySelector('#item-decisions-prices')"
        a.ev(f"BP.choose('decisions/prices', 'notice'); {row}.querySelector('.bp-more').click()")
        approve = "document.querySelector('.bd-key.approve').disabled"
        self.assertEqual(self.count(a), [False, "1"])
        self.assertTrue(a.ev(approve), "Approve stays enabled while an item asks for more details")
        self.assertEqual(a.ev(f"[{row}.classList.contains('more'), {row}.querySelector('.bp-more').getAttribute('aria-pressed'),"
                              f" document.activeElement === {row}.querySelector(':scope > .bp-note textarea')]"), [True, "true", True])
        self.send_changes(a, "1 request for more details")
        self.assertIn("`item:decisions/prices` → **Need more details**; picked **", self.reply(self.plan))
        answers = json.loads(self.reply(self.plan, "--json"))["answers"]
        self.assertEqual([(x["item"], x["choice"]) for x in answers if x.get("more")], [("prices", "notice")], "the toggle cleared the pick")
        self.assertEqual(self.count(a), [True, "0"])
        self.assertEqual(a.ev(f"{row}.querySelector('.bp-more').textContent"), "Details requested")
        # sent: Approve still waits on it; withdrawing it is the reader's way out
        self.assertTrue(a.ev(approve), "Approve enabled while a sent details request is unanswered")
        self.assertTrue(a.ev("BP.moreDetails('decisions/prices', false)"))
        self.assertFalse(a.ev(approve), "withdrawing the request left Approve disabled")
        a.ev(f"{row}.querySelector('.bp-more').click()")
        self.send_changes(a, "1 request for more details")
        # the agent answers with a new rev: the toggle is back to off
        self.assertTrue(until(lambda: self.state(url).get("decisions:prices:more", "").startswith("sent@")))
        r = self.tmp.run("build.py", "patch", self.plan, "item:decisions/prices", "--set", "detail=Acme shows the saved price and the current one.")
        self.assertEqual(r.returncode, 0, r.stderr)
        a.go(self.base + url)
        self.assertEqual(a.ev(f"[{row}.classList.contains('more'), {row}.querySelector('.bp-more').textContent]"), [False, "Need more details"])
        self.assertEqual(self.count(a), [True, "0"])
        self.assertFalse(a.ev(approve), "Approve still disabled after the agent's new rev answered the request")

    def test_need_more_details_on_a_review(self) -> None:
        url = self.server.url_for(self.docs / "acme-review-findings.bluedoc.json")
        a = self.open(url)
        a.ev("BP.setNote('t412/float-cents', 'Fine as a ticket.')")   # a review's item comments go with Send answers
        self.assertEqual(self.count(a), [True, "0"])
        a.ev("document.querySelector('#item-t412-tier-boundary .bp-more').click()")
        self.assertEqual(self.count(a), [False, "1"])
        p = a.ev("BP.changesPayload()")
        self.assertEqual([(x["item"], x.get("more")) for x in p["answers"]], [("tier-boundary", True)])
        self.assertIn("`item:t412/tier-boundary` → **Need more details**", p["markdown"])
        self.assertNotIn("float-cents", p["markdown"])
        self.send_changes(a, "1 request for more details")
        self.assertIn("→ **Need more details**", self.reply(self.docs / "acme-review-findings.bluedoc.json"))
        self.assertEqual(self.count(a), [True, "0"])


REVIEW = "acme-review-findings.bluedoc.json"   # sections pr-412 and pr-415: checklist t412 + diff diff-412, t415 + diff-415
TIER_ROW = "document.querySelector('#item-t412-tier-boundary')"   # its comment (index 0) sits on src/pricing/tiers.ts:17


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class FindingsView(ChromePage):
    """A findings section (a checklist and the diff whose comments are its items) shows them as Merged (the default:
    each commented range's lines with the full finding row under them, in code order), as its checklist or as its
    diff, picked by [Merged][Checklist][Diff] in a bar under its title, sticky while the section is on screen, and
    remembered per browser; a link into a hidden view shows it, and an item link stays in Merged. Picks sync across
    the three. An open finding in Checklist shows its comment's file, lines and card, whose pick, annotation keys and
    pins are the diff's."""

    def setUp(self) -> None:
        super().setUp()
        self.url = self.server.url_for(self.docs / REVIEW)

    def shows(self, tab: Tab, *sels: str) -> list:
        return tab.ev(f"{json.dumps(sels)}.map(s => !!document.querySelector(s)?.checkVisibility())")

    def test_the_toggle_swaps_the_views_and_survives_a_reload(self) -> None:
        a = self.open(self.url)
        self.assertEqual(a.ev("[BP.findingsView('pr-412'), BP.findingsView('pr-415'), BP.findingsView('summary')]"), ["merged", "merged", None])
        self.assertEqual(self.shows(a, "#pr-412 .bd-mv", "#cl-t412", "#diff-diff-412", "#pr-412 > .bd-fvbar"), [True, False, False, True])
        self.assertTrue(a.ev("document.querySelector('#pr-412 > .bp-lead').nextElementSibling.matches('.bd-fvbar')"), "the bar is not right under the lead")
        self.assertFalse(a.ev("!!document.querySelector('#summary .bd-fvbar')"), "a section without both got the bar")
        self.assertEqual(a.ev("[...document.querySelectorAll('#pr-412 .bd-fvbar button')].map(b => [b.textContent, !!b.querySelector('.bd-ic'), b.offsetHeight])"),
                         [["Merged", True, 38], ["Checklist", True, 38], ["Diff", True, 38]])
        a.ev("document.querySelector('#pr-412 .bd-fvbar [data-v=diff]').click()")
        self.assertEqual(self.shows(a, "#cl-t412", "#diff-diff-412", "#pr-415 .bd-mv", "#diff-diff-415"), [False, True, False, True])
        self.assertEqual(a.ev("[...document.querySelectorAll('#pr-412 .bd-fvbar button')].map(b => b.getAttribute('aria-pressed'))"), ["false", "false", "true"])
        self.assertEqual(a.ev("BP.progress().map(c => c.total)"), [7, 4], "the tracker lost the hidden checklists")
        a.go(self.base + self.url)
        self.assertEqual(a.ev("[BP.findingsView('pr-412'), BP.findingsView('pr-415')]"), ["diff", "diff"])
        self.assertGreater(a.ev("BP.diffState('diff-412').lines"), 0)
        a.ev("localStorage.setItem('bluedoc:findings-view', 'checklist')")   # a value saved before Merged existed
        a.go(self.base + self.url)
        self.assertEqual(self.shows(a, "#cl-t412", "#diff-diff-412", "#pr-412 .bd-mv"), [True, False, False])
        a.ev("localStorage.removeItem('bluedoc:findings-view')")
        a.go(self.base + self.url)
        self.assertEqual(a.ev("BP.findingsView('pr-412')"), "merged")

    def test_the_new_view_hint_shows_once(self) -> None:
        a = self.open(self.url)
        self.assertEqual(a.ev("[...document.querySelectorAll('.bd-fvhint')].map(e => e.textContent)"), ["New: findings and code together"] * 2)
        a.ev("document.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}))")
        self.assertEqual(a.ev("document.querySelectorAll('.bd-fvhint').length"), 0)
        a.go(self.base + self.url)
        self.assertEqual(a.ev("document.querySelectorAll('.bd-fvhint').length"), 0, "the hint came back after it was dismissed")

    def test_merged_orders_the_findings_by_code(self) -> None:
        a = self.open(self.url)
        mx = "[...document.querySelectorAll('#pr-412 .bd-mx')]"
        self.assertEqual(a.ev(f"{mx}.map(e => [e.closest('.bd-xf')?.dataset.file || null, +(e.querySelector('.bd-ln.hit')?.dataset.n || 0), e.querySelector('.bd-mrow').dataset.item])"), [
            [None, 0, "t412/pr-claims"],   # the whole change first, then the diff's files in its order, by line
            ["src/orders/createOrder.ts", 16, "t412/savings-coupon"],
            ["src/pricing/tiers.ts", 10, "t412/tiers-map"],
            ["src/pricing/tiers.ts", 17, "t412/tier-boundary"],
            ["src/pricing/tiers.ts", 25, "t412/float-cents"],
            ["test/tiers.test.ts", 5, "t412/boundary-tests"],
            ["docs/pricing.md", 11, "t412/docs-stale"]])
        tier = "document.querySelector('#pr-412 .bd-mx[data-ci=\"0\"]')"
        self.assertEqual(a.ev(f"[...{tier}.querySelectorAll('.bd-ln')].map(l => +l.dataset.n)"), list(range(14, 21)), "not ±3 lines around line 17")
        self.assertEqual(a.ev(f"[...{tier}.querySelectorAll('.bd-ln.hit')].map(l => +l.dataset.n)"), [17])
        # the full finding row: title, size, the options with the starred recommendation, Need more details, the
        # comment box, and Details with the reviewer's point, the reasoning, the fix and its check
        row = f"{tier}.querySelector('.bd-mrow')"
        self.assertEqual(a.ev("(r => [r.querySelector('.bp-cl-text').textContent, r.querySelector('.bp-chip').textContent, [...r.querySelectorAll('.bp-choice')].map(b => b.dataset.id),"
                              f" r.querySelector('.bp-choice.rec').dataset.id, !!r.querySelector('.bp-more'), !!r.querySelector('.bp-note textarea')])({row})"),
                         ["tierFor gives no tier at exactly 10 or 50 units", "blocker", ["fix", "ticket", "decline"], "fix", True, True])
        self.assertFalse(a.ev(f"{row}.querySelector('.bd-mbody').checkVisibility()"))
        a.ev(f"{row}.querySelector('.bd-mdet').click()")
        body = a.ev(f"{row}.querySelector('.bd-mbody').checkVisibility() && {row}.querySelector('.bd-mbody').textContent")
        for part in ("Reviewer:", "My reasoning:", "Fix:", "Verify:"):
            self.assertIn(part, body or "")
        self.assertEqual(a.ev("document.querySelectorAll('#pr-412 .bd-mv .bd-cm').length"), 0, "Merged shows the reduced card, not the row")
        self.assertEqual(a.ev("[...document.querySelectorAll('#pr-415 .bd-mx .bd-mrow')].map(r => r.dataset.item)"),
                         ["t415/double-auth", "t415/retry-4xx", "t415/backoff-const", "t415/latency"])

    def test_a_finding_with_no_comment_is_listed_last_as_not_tied_to_code(self) -> None:
        doc = self.docs / REVIEW
        d = json.loads(doc.read_text(encoding="utf-8"))
        diff = next(b for s in d["sections"] if s["id"] == "pr-412" for b in s["blocks"] if b["type"] == "diff")
        diff["comments"] = [c for c in diff["comments"] if c.get("item") != "t412/pr-claims"]
        doc.write_text(json.dumps(d), encoding="utf-8")
        a = self.open(self.url)
        self.assertEqual(a.ev("(g => [g.querySelector('.bd-fh').textContent.startsWith('Not tied to code'), [...g.querySelectorAll('.bd-mrow')].map(r => r.dataset.item)])"
                              "([...document.querySelectorAll('#pr-412 .bd-mv > .bd-mg')].at(-1))"), [True, ["t412/pr-claims"]])
        self.assertEqual(a.ev("document.querySelector('#pr-412 .bd-mv > .bd-mg .bd-fh .p').textContent"), "src/orders/createOrder.ts", "a whole-change group with nothing in it")

    def test_a_pick_in_merged_shows_in_checklist_and_diff(self) -> None:
        a = self.open(self.url)
        row = "document.querySelector('#pr-412 .bd-mx[data-ci=\"0\"] .bd-mrow')"
        a.ev(f"{row}.querySelector('.bp-choice[data-id=ticket]').click()")
        self.assertEqual(a.ev(f"{TIER_ROW}.querySelector(':scope > .bp-cl-choices [aria-checked=true]')?.dataset.id"), "ticket")
        self.assertEqual(a.ev("[BP.progress()[0].done, document.querySelector('#pr-412 .bd-mv-top .bp-cl-count').textContent]"), [1, "1 of 7"])
        self.assertTrue(a.ev(f"{row}.classList.contains('done')"))
        self.assertEqual(a.ev("BP.findingsView('pr-412', 'diff')"), "diff")
        self.assertEqual(a.ev("document.querySelector('#diff-diff-412 .bd-cm[data-ci=\"0\"] [aria-checked=true]')?.dataset.id"), "ticket")
        # the other way: a pick in the checklist, Need more details and a comment show on the Merged row
        a.ev("BP.findingsView('pr-412', 'checklist')")
        a.ev(f"{TIER_ROW}.querySelector(':scope > .bp-cl-choices .bp-choice[data-id=decline]').click()")
        a.ev("BP.moreDetails('t412/tier-boundary')")
        a.ev("BP.setNote('t412/tier-boundary', 'Acme: the spec owner agrees')")
        a.ev("BP.findingsView('pr-412', 'merged')")
        self.assertEqual(a.ev(f"[{row}.querySelector('[aria-checked=true]')?.dataset.id, {row}.classList.contains('more'), {row}.querySelector('.bp-note textarea').value]"),
                         ["decline", True, "Acme: the spec owner agrees"])
        # Accept recommended in Merged picks the starred option on the open decisions there
        acc = "document.querySelector('#pr-412 .bd-mv-top .tools .bp-btn')"
        self.assertEqual(a.ev(f"{acc}.textContent"), "Accept recommended (6)")
        a.ev(f"{acc}.click()")
        self.assertEqual(a.ev(f"[BP.progress()[0].done, {acc}.hidden]"), [7, True])

    def test_show_more_lines_grows_the_excerpt(self) -> None:
        a = self.open(self.url)
        ex = "document.querySelector('#pr-412 .bd-mx[data-ci=\"0\"]')"
        lines = f"[...{ex}.querySelectorAll('.bd-ln')].map(l => +l.dataset.n)"
        self.assertEqual(a.ev(lines), list(range(14, 21)))
        a.ev(f"{ex}.querySelector('.bd-mmore').click()")
        self.assertEqual(a.ev(lines), list(range(6, 27)), "not 8 more lines either side (the hunk ends at 26)")
        a.ev(f"{ex}.querySelector('.bd-mmore').click()")
        self.assertEqual(a.ev(f"[{lines}, {ex}.querySelector('.bd-mmore').hidden]"), [list(range(1, 27)), True], "the whole hunk shows, and the control goes")
        self.assertEqual(a.ev(f"[...{ex}.querySelectorAll('.bd-ln.hit')].map(l => +l.dataset.n)"), [17])

    def test_item_and_line_keys_resolve_in_merged(self) -> None:
        a = self.open(self.url)
        pin = "(p => !!p && !p.hidden && !p.classList.contains('away'))(document.querySelector('.bd-ann-pin'))"
        on = "(r => { const p = document.querySelector('.bd-ann-pin').getBoundingClientRect(); return p.top >= r.top - 40 && p.top <= r.bottom; })"
        made = a.ev("BP.annotate({type: 'pin', key: 'item:t412/tier-boundary', note: 'Acme: inclusive bound'})")
        self.assertEqual(made["target"]["key"], "item:t412/tier-boundary")
        self.assertEqual(a.ev("BP.findingsView('pr-412')"), "merged", "an item key left Merged")
        a.wait_for(f"{pin} && {on}(document.querySelector('#pr-412 .bd-mx[data-ci=\"0\"] .bd-mrow').getBoundingClientRect())")
        key = "line:diff-412/src/pricing/tiers.ts:17"
        made = a.ev(f"BP.annotate({{type: 'pin', key: {json.dumps(key)}, note: 'Acme: inclusive bound'}})")
        self.assertEqual(made["target"]["key"], key)
        self.assertIn("comment:diff-412/0", made["up"], "pinned on a line outside its Merged range")
        self.assertEqual(a.ev("BP.findingsView('pr-412')"), "merged", "a line key left Merged")
        last = "[...document.querySelectorAll('.bd-ann-pin')].at(-1)"
        a.wait_for(f"(p => !!p && !p.hidden && (r => {{ const q = p.getBoundingClientRect(); return q.top >= r.top - 40 && q.top <= r.bottom; }})"
                   f"(document.querySelector('#pr-412 .bd-mx[data-ci=\"0\"] .bd-ln[data-n=\"17\"]').getBoundingClientRect()))({last})")

    def test_the_bar_is_sticky_and_visible(self) -> None:
        a = self.open(self.url)
        bar = "document.querySelector('#pr-412 > .bd-fvbar')"
        a.ev("scrollTo({top: document.querySelector('#pr-412 .bd-mx[data-ci=\"3\"]').getBoundingClientRect().top + scrollY - 400, behavior: 'instant'})")
        a.wait_for(f"{bar}.classList.contains('stuck')")
        top_h = a.ev("Math.round(parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--bar-h')))")
        self.assertEqual(a.ev(f"(r => [Math.round(r.top), document.elementFromPoint(r.left + 40, r.top + r.height / 2)?.closest('.bd-fvbar') === {bar}])"
                              f"({bar}.getBoundingClientRect())"), [top_h, True])
        self.assertTrue(a.ev(f"{bar}.checkVisibility()"))
        # a pick from the stuck bar keeps it there and starts the new view right under it
        a.ev(f"{bar}.querySelector('[data-v=checklist]').click()")
        self.assertEqual(a.ev(f"(r => [Math.round(r.top), document.querySelector('#cl-t412').getBoundingClientRect().top - r.bottom <= 14])({bar}.getBoundingClientRect())"), [top_h, True])
        # past the section, its bar leaves with it
        a.ev("document.querySelector('#pr-415').scrollIntoView({behavior: 'instant'})")
        self.assertLess(a.ev(f"{bar}.getBoundingClientRect().bottom"), a.ev("document.querySelector('#pr-415').getBoundingClientRect().top + 1"))

    def test_an_open_finding_shows_its_code_and_card(self) -> None:
        a = self.open(self.url)
        a.ev("BP.findingsView('pr-412', 'checklist')")
        self.assertEqual(a.ev(f"{TIER_ROW}.querySelectorAll('.bd-xf').length"), 0, "drawn before the row opened")
        a.ev(f"{TIER_ROW}.querySelector('.bp-cl-head').click()")
        xf = f"{TIER_ROW}.querySelector('.bd-xf')"
        self.assertEqual(a.ev(f"{xf}.querySelector('.bd-fh .p').textContent"), "src/pricing/tiers.ts")
        self.assertTrue(a.ev(f"{xf}.querySelector('.bd-ln.hit[data-n=\"17\"]').checkVisibility()"))
        self.assertEqual(a.ev(f"[...{xf}.querySelectorAll('.bd-ln')].map(l => +l.dataset.n)"), list(range(14, 21)), "not ±3 lines around line 17")
        self.assertEqual(a.ev(f"{xf}.querySelector('.bd-ln[data-n=\"17\"] + .bd-cmw > .bd-cm').dataset.ci"), "0")
        self.assertEqual(a.ev(f"{xf}.querySelector('.bd-fh .bd-xgo').textContent"), "Open in Diff view")
        self.assertEqual(a.ev("document.querySelector('#item-t412-pr-claims').querySelectorAll('.bd-xf').length"), 0)
        # a finding with no line: its whole-change card, no lines
        a.ev("document.querySelector('#item-t412-pr-claims .bp-cl-head').click()")
        self.assertEqual(a.ev("(x => [x.querySelectorAll('.bd-ln').length, x.querySelectorAll('.bd-cm').length])(document.querySelector('#item-t412-pr-claims .bd-xf'))"), [0, 1])
        # a pick in the card: on the row and on the Diff view's card
        a.ev(f"{xf}.querySelector('.bd-cm .bp-choice[data-id=ticket]').click()")
        self.assertEqual(a.ev(f"{TIER_ROW}.querySelector(':scope > .bp-cl-choices [aria-checked=true]')?.dataset.id"), "ticket")
        self.assertEqual(a.ev("BP.findingsView('pr-412', 'diff')"), "diff")
        self.assertEqual(a.ev("document.querySelector('#diff-diff-412 .bd-cm[data-ci=\"0\"] [aria-checked=true]')?.dataset.id"), "ticket")
        # Open in Diff view: Diff, that comment focused in the diff's pane
        a.ev("BP.findingsView('pr-412', 'checklist')")
        a.ev(f"{xf}.querySelector('.bd-xgo').click()")
        self.assertEqual(a.ev("[BP.findingsView('pr-412'), BP.diffState('diff-412').file]"), ["diff", "src/pricing/tiers.ts"])
        a.wait_for("(e => e.matches('#diff-diff-412 .bd-pane .bd-cm[data-ci=\"0\"]'))(document.activeElement)")

    def test_a_pin_in_the_finding_code_has_the_diff_key_and_shows_in_both(self) -> None:
        a = self.open(self.url)
        a.ev("BP.findingsView('pr-412', 'checklist')")
        a.ev(f"{TIER_ROW}.querySelector('.bp-cl-head').click()")
        key = "line:diff-412/src/pricing/tiers.ts:17"
        made = a.ev(f"BP.annotate({{type: 'pin', key: {json.dumps(key)}, note: 'Acme: inclusive bound'}})")
        self.assertEqual(made["target"]["key"], key)
        self.assertIn("item:t412/tier-boundary", made["up"], "pinned on the diff's line, not the one under the finding")
        pin = "(p => !!p && !p.hidden && !p.classList.contains('away'))(document.querySelector('.bd-ann-pin'))"
        a.wait_for(pin)
        a.ev("BP.findingsView('pr-412', 'diff')")
        self.assertTrue(a.ev("BP.openCode('diff-412', 'src/pricing/tiers.ts', 17)"))   # the line may sit below the pane's fold
        on = "(r => { const p = document.querySelector('.bd-ann-pin').getBoundingClientRect(); return p.top >= r.top - 40 && p.top <= r.bottom; })"
        a.wait_for(f"{pin} && {on}(document.querySelector('#diff-diff-412 .bd-ln[data-n=\"17\"]').getBoundingClientRect())")
        a.ev("BP.findingsView('pr-412', 'checklist')")   # back: on the line under the open finding
        a.wait_for(f"{pin} && {on}({TIER_ROW}.querySelector('.bd-xf .bd-ln[data-n=\"17\"]').getBoundingClientRect())")
        a.ev("BP.findingsView('pr-412', 'merged')")   # and on the same line in Merged
        a.wait_for(f"{pin} && {on}(document.querySelector('#pr-412 .bd-mx[data-ci=\"0\"] .bd-ln[data-n=\"17\"]').getBoundingClientRect())")

    def test_links_into_the_hidden_view_show_it(self) -> None:
        a = self.open(self.url)
        # in Merged, an item link scrolls to its row there and the view stays
        a.ev("location.hash = '#item-t412-float-cents'")
        a.wait_for("(r => r.top > 0 && r.bottom < innerHeight)(document.querySelector('#pr-412 .bd-mrow[data-item=\"t412/float-cents\"]').getBoundingClientRect())")
        self.assertEqual(a.ev("BP.findingsView('pr-412')"), "merged")
        self.assertTrue(a.ev("BP.openComment('diff-412', 0)"))
        self.assertEqual(a.ev("[BP.findingsView('pr-412'), BP.findingsView('pr-415')]"), ["diff", "merged"])
        self.assertEqual(self.shows(a, "#diff-diff-412 .bd-pane .bd-cm"), [True])
        a.ev("location.hash = '#item-t412-tier-boundary'")
        a.wait_for("BP.findingsView('pr-412') === 'checklist' && document.querySelector('#item-t412-tier-boundary').classList.contains('open')")
        self.assertTrue(a.ev("BP.openCode('diff-415', 'src/orders/charge.ts', 17)"))
        self.assertEqual(a.ev("BP.findingsView('pr-415')"), "diff")
        self.assertIsNone(a.ev("localStorage.getItem('bluedoc:findings-view')"), "a link changed the remembered pick")


FIT = "acme-fit-design.bluedoc.json"   # the design example: a phone flow with links, board id `main`


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class BoardDrafts(ChromePage):
    """A design board's edits are drafts in reader state (bd/link-edit, bd/move): a link edit or a moved screen shows at
    once, stays in state.db (a reload, cleared site data, another browser profile), goes with Request changes as a
    `link:` or `layout:main` item with a ready `build.py patch` command, and is resolved once the doc has it. A draft
    whose link a newer rev changed some other way is stale, and the board follows the rev."""

    def setUp(self) -> None:
        super().setUp()
        self.doc = self.docs / FIT
        self.url = self.server.url_for(self.doc)

    def edits(self, tab: Tab, opts: dict | None = None) -> dict:
        tab.wait_for("!!BP.boardEdit()")
        return tab.ev(f"BP.boardEdit({json.dumps(opts) if opts else ''})")

    def stored_drafts(self) -> list:
        out = [json.loads(v) for k, v in self.state(self.url).items() if k.startswith("__ann:")]
        return [a for a in out if a.get("type") in ("link", "layout")]

    def drag(self, tab: Tab, sel: str, dx: float, dy: float) -> None:
        """A mouse drag from the left of sel's box, dx, dy CSS px, in 8 moves, once the board stops moving that box (it
        fits itself again while the screens load, until the reader touches it)."""
        at = f"(r => [r.left + 12, r.top + r.height / 2])(document.querySelector({json.dumps(sel)}).getBoundingClientRect())"
        def still() -> list | None:
            p = tab.ev(at)
            time.sleep(0.25)
            return p if tab.ev(at) == p else None
        x, y = until(still)
        def mouse(kind: str, mx: float, my: float, buttons: int) -> None:
            tab.browser.call("Input.dispatchMouseEvent", {"type": kind, "x": mx, "y": my, "button": "left", "buttons": buttons, "clickCount": 1},
                             tab.session)
        mouse("mousePressed", x, y, 1)
        for i in range(1, 9):
            mouse("mouseMoved", x + dx * i / 8, y + dy * i / 8, 1)
            time.sleep(0.03)
        mouse("mouseReleased", x + dx, y + dy, 0)

    def test_a_moved_screen_is_a_layout_draft_until_the_doc_has_it(self) -> None:
        a = self.open(self.url)
        was, src = self.edits(a)["positions"]["login"], self.doc.read_bytes()
        a.ev("BP.board({fit: true})")
        self.drag(a, ".bd-ab[data-ab=login] .bd-ab-t", 40, 30)
        now = a.wait_for(f"(p => (p[0] !== {was[0]} || p[1] !== {was[1]}) && p)(BP.boardEdit().positions.login)")
        drafts = self.edits(a)["drafts"]
        self.assertEqual([(d["key"], d["status"], d["positions"]) for d in drafts], [("layout:main", "pending", {"login": now})])
        # reader state, not the doc: kept across a reload, cleared site data and another browser profile
        self.assertTrue(until(self.stored_drafts), "the move never reached state.db")
        self.assertEqual(self.doc.read_bytes(), src, "a move wrote the doc")
        a.go(self.base + self.url)
        self.assertEqual(self.edits(a)["positions"]["login"], now)
        a.ev("localStorage.clear()")
        a.go(self.base + self.url)
        self.assertEqual(self.edits(a)["positions"]["login"], now)
        profile = Path(tempfile.mkdtemp(prefix="bluedoc-chrome-"))
        other = Browser(profile)
        try:
            b = Tab(other)
            b.go(self.base + self.url)
            self.assertEqual(self.edits(b)["positions"]["login"], now)
        finally:
            other.close()
            shutil.rmtree(profile, ignore_errors=True)
        # Request changes: one `layout:main` item with the command that writes it
        self.send_changes(a, "1 pending comment")
        md = self.reply(self.doc)
        self.assertIn(f"- ({drafts[0]['id']}) `layout:main` Move 1 screen: ", md)
        self.assertIn(f"build.py patch {FIT} layout:main --json '{json.dumps({'login': now}, separators=(',', ':'))}'", md)
        # the agent writes the place: on the next load the draft is resolved, applied in the new rev, and nothing moves
        r = self.tmp.run("build.py", "patch", self.doc, "layout:main", "--json", json.dumps({"login": now}))
        self.assertEqual(r.returncode, 0, r.stderr)
        a.go(self.base + self.url)
        st = self.edits(a)
        self.assertEqual(st["positions"]["login"], now)
        mine = [x for x in a.ev("BP.annotations()") if x["id"] == drafts[0]["id"]]
        self.assertEqual([(x["status"], x.get("resolvedBy")) for x in mine], [("resolved", "rev")])

    def test_a_link_draft_shows_in_present_and_clears_once_a_rev_has_it(self) -> None:
        a = self.open(self.url)
        self.edits(a)
        link = a.ev("BP.board().links.find(l => l.from === 'today' && l.kind === 'push' && l.to !== 'settings')")
        key = f"link:today/{link['el']}"
        drafts = self.edits(a, {"link": {"key": key, "to": "settings", "kind": "modal"}})["drafts"]
        self.assertEqual([(d["key"], d["link"]["op"], d["link"]["to"], d["link"]["kind"], d["link"]["base"]["to"]) for d in drafts],
                         [(key, "set", "settings", "modal", link["to"])])
        shown = a.ev(f"BP.board().links.find(l => l.key === {json.dumps(key)})")
        self.assertEqual((shown["to"], shown["kind"], shown["draft"]), ("settings", "modal", drafts[0]["id"]))
        # Present follows the draft at once
        a.ev("BP.board({present: 'today'})")
        a.ev(f"BP.board({{tap: {json.dumps(link['el'])}}})")
        self.assertEqual(a.wait_for("(p => p && p.screen !== 'today' && p.screen)(BP.board().presented)"), "settings")
        a.ev("BP.board({present: false})")
        # kept across a reload; the reply's command makes it
        self.assertTrue(until(self.stored_drafts), "the link draft never reached state.db")
        a.go(self.base + self.url)
        self.assertEqual(a.ev(f"BP.board().links.find(l => l.key === {json.dumps(key)}).draft"), drafts[0]["id"])
        md = a.ev("BP.changesPayload().markdown")
        self.assertIn(f"- ({drafts[0]['id']}) `{key}` Change link Today › ", md)
        self.assertIn(f"build.py patch {FIT} {key} --set to=settings --set kind=modal", md)
        # the agent's rev has the link: the draft is resolved and the board shows the rev's link
        r = self.tmp.run("build.py", "patch", self.doc, key, "--set", "to=settings", "--set", "kind=modal")
        self.assertEqual(r.returncode, 0, r.stderr)
        a.go(self.base + self.url)
        shown = a.ev(f"BP.board().links.find(l => l.key === {json.dumps(key)})")
        self.assertEqual((shown["to"], shown["kind"], shown["draft"]), ("settings", "modal", None))
        mine = [x for x in a.ev("BP.annotations()") if x["id"] == drafts[0]["id"]]
        self.assertEqual([(x["status"], x.get("resolvedBy")) for x in mine], [("resolved", "rev")])

    def test_a_draft_whose_link_a_newer_rev_changed_is_stale(self) -> None:
        a = self.open(self.url)
        self.edits(a)
        link = a.ev("BP.board().links.find(l => l.from === 'today' && l.kind === 'push' && l.to !== 'settings' && l.to !== 'profile')")
        key = f"link:today/{link['el']}"
        did = self.edits(a, {"link": {"key": key, "to": "settings"}})["drafts"][0]["id"]
        self.assertTrue(until(self.stored_drafts))
        r = self.tmp.run("build.py", "patch", self.doc, key, "--set", "to=profile")
        self.assertEqual(r.returncode, 0, r.stderr)
        a.go(self.base + self.url)
        self.assertEqual([(d["id"], d["status"], d["stale"]) for d in self.edits(a)["drafts"]], [(did, "pending", True)])
        shown = a.ev(f"BP.board().links.find(l => l.key === {json.dumps(key)})")
        self.assertEqual((shown["to"], shown["draft"]), ("profile", None), "the board follows the rev, not the stale draft")
        a.ev(f"BP.comments({{open: true}})")
        self.assertIn("Stale", a.wait_for(f"document.querySelector('.bd-cs-c[data-id={did}]')?.textContent"))


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ReaderName(ChromePage):
    """The reader renames a doc and picks its emoji on the page (rt/name): the h1 on a doc page, the app bar's crumb on a
    board. Enter saves `__title`, Esc restores; the picker's search and Enter save `__emoji`; both hold through a reload,
    show in the tab and the home index, and never in a reply or the doc's JSON. The picker's reset items bring the doc's
    own back. ?rev= shows them as text."""

    def keys(self, t: Tab, key: str, code: int) -> None:
        for kind in ("keyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": key, "windowsVirtualKeyCode": code,
                                                         **({"text": "\r"} if key == "Enter" and kind == "keyDown" else {})}, t.session)

    def rename(self, t: Tab, sel: str, title: str, emoji_search: str) -> None:
        t.ev(f"document.querySelector({json.dumps(sel + ' .bd-tt')}).click()")
        self.assertTrue(t.ev(f"document.querySelector({json.dumps(sel + ' .bd-tt')}).isContentEditable"))
        self.browser.call("Input.insertText", {"text": title}, t.session)
        self.keys(t, "Enter", 13)
        t.ev(f"document.querySelector({json.dumps(sel + ' button.bd-emo')}).click()")
        self.assertEqual(t.ev("document.activeElement === document.querySelector('.bd-emop input')"), True)
        self.browser.call("Input.insertText", {"text": emoji_search}, t.session)
        self.keys(t, "Enter", 13)

    def card(self, doc: Path) -> dict:
        index = json.loads(self.server.req("GET", "/__bluedoc/index.json")[1])
        return next(d for r in index["roots"] for d in r["docs"] if d["path"] == doc.name)

    def stored(self, url: str) -> dict:
        return {k: v for k, v in self.state(url).items() if k in ("__title", "__emoji")}

    def test_a_plan_renamed_in_its_header(self) -> None:
        url, raw = self.server.url_for(self.plan), self.plan.read_bytes()
        t = self.open(url)
        self.assertEqual(t.ev("document.querySelector('.bd-head h1').textContent"), "📋Acme Shop: saved carts")
        self.rename(t, ".bd-head h1", "Acme carts", "cart")
        self.assertEqual(until(lambda: self.stored(url) if len(self.stored(url)) == 2 else None), {"__title": "Acme carts", "__emoji": "🛒"})
        # Esc restores what was there
        t.ev("document.querySelector('.bd-head h1 .bd-tt').click()")
        self.browser.call("Input.insertText", {"text": "Not kept"}, t.session)
        self.keys(t, "Escape", 27)
        t.go(self.base + url)
        self.assertEqual(t.ev("[document.title, document.querySelector('.bd-head h1').textContent, document.querySelector('.bd-crumb').textContent]"),
                         ["Acme carts · bluedoc", "🛒Acme carts", "/🛒Acme carts"])
        self.assertEqual(t.ev("document.querySelector('.bd-head h1 .bd-tt').title"), "Rename (F2). Doc title: Acme Shop: saved carts")
        card = self.card(self.plan)
        self.assertEqual((card["title"], card["docTitle"], card["emoji"]), ("Acme carts", "Acme Shop: saved carts", "🛒"))
        replies = t.ev("[BP.progressMarkdown(), JSON.stringify(BP.approvePayload()), JSON.stringify(BP.changesPayload())]")
        self.assertEqual([r for r in replies if "Acme carts" in r], [], "a reply names the reader's title")
        self.assertEqual(self.plan.read_bytes(), raw)
        # ?rev= shows them as text
        t.go(f"{self.base}{url}?rev=1")
        self.assertEqual(t.ev("[document.querySelector('.bd-head h1').textContent, document.querySelectorAll('button.bd-emo, .bd-tt[tabindex]').length]"),
                         ["🛒Acme carts", 0])
        # the picker's reset items bring the doc's own back
        t.go(self.base + url)
        for _ in range(2):
            t.ev("document.querySelector('.bd-head h1 button.bd-emo').click()")
            t.ev("document.querySelector('.bd-emop .rs button').click()")
        self.assertEqual(t.ev("document.querySelector('.bd-head h1').textContent"), "📋Acme Shop: saved carts")
        self.assertEqual(until(lambda: not self.stored(url) and "reset"), "reset")
        self.assertEqual(self.browser.errors, [])

    def test_a_board_renamed_in_its_app_bar(self) -> None:
        doc = self.docs / FIT
        url = self.server.url_for(doc)
        t = self.open(url)
        self.rename(t, ".bd-crumb", "Acme Fit: onboarding", "rocket")
        self.assertEqual(until(lambda: self.stored(url) if len(self.stored(url)) == 2 else None), {"__title": "Acme Fit: onboarding", "__emoji": "🚀"})
        t.go(self.base + url)
        self.assertEqual(t.ev("[document.title, document.querySelector('.bd-crumb').textContent]"), ["Acme Fit: onboarding · bluedoc", "/🚀Acme Fit: onboarding"])
        self.assertEqual(self.card(doc)["emoji"], "🚀")
        self.assertEqual(self.browser.errors, [])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class Archive(ChromePage):
    """The reader archives a doc from its page's ⋯ menu or a home card's (rt/archive): reader state `__archived` {at, rev},
    never in a reply or the doc's JSON. The page shows a banner with Unarchive and an Archived chip; the home page leaves
    the doc out of its views, counts and widgets, an Archived chip lists it, and a search or filter that hides it says so
    (Show them). A rev the agent writes brings it back, said once on the page. An approved plan with every step done and
    every check ticked offers "All done · Archive it?" on its page and card; Not now holds until the next rev."""

    MENU = "document.querySelector('.bd-docm')"

    def home(self, query: str = "") -> Tab:
        status, raw = self.server.req("POST", "/__bluedoc/unlock", b"{}", {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        t = Tab(self.browser)
        self.browser.call("Page.navigate", {"url": f"{self.base}/?key={json.loads(raw)['token']}" + (f"&{query}" if query else "")}, t.session)
        t.wait_for("document.readyState === 'complete' && !!document.querySelector('.bd-fc')")
        return t

    def chips(self, t: Tab) -> dict:
        return t.ev("Object.fromEntries([...document.querySelectorAll('.bd-fc')].map(c => [c.childNodes[c.childNodes.length - 2].textContent, +c.querySelector('.c').textContent]))")

    def archived(self, url: str) -> dict | None:
        v = self.state(url).get("__archived")
        return json.loads(v) if v else None

    def test_archive_from_the_page_and_back_with_a_new_rev(self) -> None:
        url, raw = self.server.url_for(self.plan), self.plan.read_bytes()
        t = self.open(url)
        t.ev(f"{self.MENU}.querySelector('.bd-ibtn').click()")
        self.assertEqual(t.ev(f"{self.MENU}.querySelector('[role=menuitem]').textContent"), "Archive")
        t.ev(f"{self.MENU}.querySelector('[role=menuitem]').click()")
        self.toast(t, "archived")
        self.assertEqual(until(lambda: (self.archived(url) or {}).get("rev")), "1")
        t.go(self.base + url)
        self.assertRegex(t.ev("document.querySelector('.bd-revbar.arc').textContent"), r"^Archived on \d+ \w+ · it's hidden from the home page's views\.Unarchive$")
        self.assertEqual(t.ev("document.querySelector('.bd-planchip.arc').hidden"), False)
        replies = t.ev("[BP.progressMarkdown(), JSON.stringify(BP.approvePayload()), JSON.stringify(BP.changesPayload())]")
        self.assertEqual([r for r in replies if "rchive" in r], [], "a reply mentions the archive")
        self.assertEqual(self.plan.read_bytes(), raw)
        # Unarchive in the banner
        t.ev("document.querySelector('.bd-revbar.arc .bp-btn').click()")
        self.assertEqual(until(lambda: self.archived(url) is None and "gone"), "gone")
        self.assertEqual(t.ev("[document.querySelectorAll('.bd-revbar.arc').length, document.querySelector('.bd-planchip.arc').hidden]"), [0, True])
        # archived again, then the agent writes rev 2: back, said once
        t.ev(f"{self.MENU}.querySelector('[role=menuitem]').click()")
        self.assertEqual(until(lambda: (self.archived(url) or {}).get("rev")), "1")
        r = self.tmp.run("build.py", "patch", self.plan, "step:steps/0/table", "--set", "status=done", "--change", "Acme: the table is in.")
        self.assertEqual(r.returncode, 0, r.stderr)
        t.go(self.base + url)
        self.assertEqual(t.ev("document.querySelector('.bd-revbar.arc').textContent"), "Back from the archive: rev 2 changed it.")
        self.assertEqual(until(lambda: self.archived(url) is None and "dropped"), "dropped")
        t.go(self.base + url)
        self.assertEqual(t.ev("document.querySelectorAll('.bd-revbar.arc').length"), 0)
        # an earlier revision has no menu
        t.go(f"{self.base}{url}?rev=1")
        self.assertEqual(t.ev(f"!!{self.MENU}"), False)
        self.assertEqual(self.browser.errors, [])

    def test_the_home_page_hides_archived_docs_and_says_so(self) -> None:
        url = self.server.url_for(self.plan)
        t = self.home()
        before = self.chips(t)
        by_type = "document.querySelectorAll('.bd-w-head .r')[2].textContent"
        docs = t.ev(by_type)
        # archive from the plan's card menu
        card = f"[...document.querySelectorAll('.bd-cw')].find(w => w.querySelector('a').getAttribute('href') === {json.dumps(url)})"
        t.ev(f"{card}.querySelector('.bd-cm-b').click()")
        self.assertEqual(t.wait_for("document.querySelector('.bd-cm-m [role=menuitem]')?.textContent"), "Archive")
        t.ev("document.querySelector('.bd-cm-m [role=menuitem]').click()")
        t.wait_for(f"!{card}")
        self.assertEqual((self.archived(url) or {}).get("rev"), "1")
        after = self.chips(t)
        self.assertEqual(after.pop("Archived"), 1)
        self.assertEqual((after["All"], after.get("Plans", 0)), (before["All"] - 1, 0))
        self.assertEqual(t.ev(by_type), f"{int(docs.split()[0]) - 1} docs")
        self.assertIn("Undo", t.ev("document.querySelector('.bd-toast').textContent"))
        # a search and a type filter that would show it say so; Show them lists it, dimmed, with an Archived badge
        t = self.home("q=saved+carts&t=plan")
        self.assertEqual(t.wait_for("document.querySelector('.bd-empty .bd-ahint-x')?.textContent"), "1 archived doc does · Show them")
        t.ev("document.querySelector('.bd-empty .bd-ahint-x button').click()")
        t.wait_for(f"!!{card}")
        self.assertEqual(t.ev(f"[{card}.classList.contains('arch'), {card}.querySelector('.bd-pill.st').textContent, location.search]"),
                         [True, "Archived", "?q=saved+carts&t=plan&s=archived"])
        # the Archived chip off goes back to the search as it was
        t.ev("[...document.querySelectorAll('.bd-fc')].find(c => c.textContent.startsWith('Archived')).click()")
        t.wait_for("location.search === '?q=saved+carts&t=plan'")
        # under the results when other docs match: a search for Acme
        t = self.home("q=acme")
        self.assertEqual(t.wait_for("document.querySelector('.bd-ahint').textContent"), "1 archived doc matches·Show them")
        # unarchive from the card in the Archived view: back in every count, the line gone
        t = self.home("s=archived")
        t.wait_for(f"!!{card}")
        t.ev(f"{card}.querySelector('.bd-cm-b').click()")
        self.assertEqual(t.wait_for("document.querySelector('.bd-cm-m [role=menuitem]')?.textContent"), "Unarchive")
        t.ev("document.querySelector('.bd-cm-m [role=menuitem]').click()")
        self.assertEqual(until(lambda: self.archived(url) is None and "gone"), "gone")
        t = self.home("q=acme")
        self.assertEqual(t.ev("document.querySelector('.bd-ahint').textContent"), "")
        t = self.home()
        self.assertEqual(self.chips(t), before)
        self.assertEqual(self.browser.errors, [])

    def test_a_plan_all_done_offers_archive(self) -> None:
        url = self.server.url_for(self.plan)
        html = self.server.req("GET", url)[1].decode()
        seed = json.loads(html.split('id="bp-state">', 1)[1].split("</script>", 1)[0])
        body = {"path": url, "rev": "1", "docHash": seed["docHash"], "decision": "approved", "answers": [], "annotations": [],
                "at": "2026-01-01T00:00:00Z", "markdown": "# Plan approved: Acme\n"}
        self.assertEqual(self.server.req("POST", "/__bluedoc/approve", json.dumps(body).encode(), {"Content-Type": "application/json", "X-Bluedoc": "1"})[0], 200)
        doc = json.loads(self.plan.read_text(encoding="utf-8"))
        steps = next(b for s in doc["sections"] for b in s.get("blocks") or [] if b.get("type") == "steps")
        for i, s in enumerate(steps["items"]):
            r = self.tmp.run("build.py", "patch", self.plan, f"step:steps/0/{s['id']}", "--set", "status=done", *(["--no-bump"] if i else ["--change", "Acme: all steps in."]))
            self.assertEqual(r.returncode, 0, r.stderr)
        t = self.open(url)
        self.assertEqual(t.ev("document.querySelectorAll('.bd-revbar.arc.sug').length"), 0, "offered before every check is ticked")
        checks = next(b for s in doc["sections"] for b in s.get("blocks") or [] if b.get("type") == "checklist" and b["id"] == "checks")
        for it in checks["items"]:
            t.ev(f"document.querySelector('#item-checks-{it['id']} input[type=checkbox]').click()")
        self.assertEqual(t.wait_for("document.querySelector('.bd-revbar.arc.sug')?.textContent"), "All done · Archive it?ArchiveNot now")
        # Not now holds for this rev, on the page and the card
        t.ev("document.querySelector('.bd-revbar.arc.sug .bp-btn:last-child').click()")
        self.assertEqual(until(lambda: self.state(url).get("__archive-later")), "2")
        t.go(self.base + url)
        self.assertEqual(t.ev("document.querySelectorAll('.bd-revbar.arc.sug').length"), 0)
        h = self.home()
        self.assertEqual(h.ev("document.querySelectorAll('.bd-sug').length"), 0)
        # without it the card offers it too; Archive there archives
        body = json.dumps({"path": url, "import": False, "ops": [["__archive-later", None]]}).encode()
        self.assertEqual(self.server.req("PUT", "/__bluedoc/state", body, {"Content-Type": "application/json", "X-Bluedoc": "1", "Origin": self.base})[0], 200)
        h = self.home()
        self.assertEqual(h.wait_for("document.querySelector('.bd-sug')?.textContent"), "All done · Archive it?ArchiveNot now")
        h.ev("document.querySelector('.bd-sug button').click()")
        self.assertEqual(until(lambda: (self.archived(url) or {}).get("rev")), "2")
        h.wait_for("!document.querySelector('.bd-sug')")
        self.assertEqual(self.browser.errors, [])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class NarrowWindow(ChromePage):
    """A doc page in a window too narrow for a readable centred column goes wide: the column fills the window between the
    page paddings, whatever width the reader stored, and the width handles hide; a wide window keeps the stored width."""

    COL = "Math.round(document.querySelector('.bd-shell > main').getBoundingClientRect().width)"

    def size(self, t: Tab, w: int) -> None:
        self.browser.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, t.session)
        t.wait_for(f"innerWidth === {w}")

    def test_a_narrow_window_reads_edge_to_edge_and_a_wide_one_keeps_the_stored_width(self) -> None:
        t = self.open(self.server.url_for(self.plan))
        t.ev("localStorage.setItem('bluedoc:width', '560')")
        t.go(t.ev("location.href"))
        # 1060 px: the rail and an empty right column would leave the stored 560 px: wide, edge to edge
        self.size(t, 1060)
        t.wait_for("document.documentElement.dataset.layout === 'wide'")
        self.assertEqual(t.ev(self.COL), t.ev("document.documentElement.clientWidth") - 40)
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-rh-col')].map(h => getComputedStyle(h).display)"), ["none", "none"])
        # 1180 px: a centred column would get 540 px, under the 640 px it takes to read: still wide
        self.size(t, 1180)
        t.wait_for(f"document.documentElement.dataset.layout === 'wide' && {self.COL} === document.documentElement.clientWidth - 40")
        # 1600 px: centred, at the stored width, with its handles
        self.size(t, 1600)
        t.wait_for(f"document.documentElement.dataset.layout === 'centred' && {self.COL} === 560")
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-rh-col')].map(h => getComputedStyle(h).display)"), ["block", "block"])
        self.assertEqual(self.browser.errors, [])

    def drag(self, t: Tab, handle: int, to: int) -> None:
        """Press the column's handle (0 left, 1 right), move the mouse to x = to, release: real pointer events. Waits first,
        so two drags in a row aren't a double press (which resets the width)."""
        time.sleep(0.4)
        x = t.ev(f"(r => Math.round(r.left + r.width / 2))(document.querySelectorAll('.bd-rh-col')[{handle}].getBoundingClientRect())")
        for kind, at in (("mousePressed", x), ("mouseMoved", (x + to) // 2), ("mouseMoved", to), ("mouseReleased", to)):
            self.browser.call("Input.dispatchMouseEvent", {"type": kind, "x": at, "y": 450, "button": "left", "buttons": 0 if kind == "mouseReleased" else 1,
                                                           "clickCount": 1}, t.session)
            time.sleep(0.05)

    def test_the_right_handle_reaches_into_the_empty_right_side_and_the_left_one_stays_off_the_rail(self) -> None:
        t = self.open(self.server.url_for(self.plan))
        self.size(t, 1420)
        t.ev("BP.sidebar({open: false})")   # no right panel docked: its room is the empty right side the column may take
        t.wait_for("!document.documentElement.classList.contains('bd-sp-dock')")
        edges = "(r => [Math.round(r.left), Math.round(r.right)])(document.querySelector('.bd-shell > main').getBoundingClientRect())"
        vw = t.ev("document.documentElement.clientWidth")
        left, right = t.wait_for(f"document.documentElement.dataset.layout === 'centred' && {edges}")
        self.assertLessEqual(abs(left - (vw - right)), 1, "no stored width: centred")
        rail = 20 + 248 + 32   # the page padding, the rail and the gap: the left edge while the column reaches right
        # past the centred room, the right edge follows the pointer (the handle sits half a gap, 16 px, right of the
        # edge, and stays under the pointer) and the left edge stays beside the rail
        self.drag(t, 1, 1300)
        t.wait_for(f"(e => e[0] === {rail} && Math.abs(e[1] - 1284) <= 1)({edges})")
        self.assertLessEqual(abs(t.ev("+localStorage.getItem('bluedoc:width')") - (1284 - rail)), 1)
        # up to the window's padding and the gap, no further
        self.drag(t, 1, vw)
        t.wait_for(f"(e => e[0] === {rail} && e[1] === {vw - 20 - 32})({edges})")
        # a reload keeps it
        t.go(t.ev("location.href"))
        self.size(t, 1420)
        t.wait_for(f"(e => e[0] === {rail} && e[1] === {vw - 20 - 32})({edges})")
        # the left handle never pushes the edge over the rail: dragged outward it changes nothing
        self.drag(t, 0, 100)
        t.wait_for(f"(e => e[0] === {rail} && e[1] === {vw - 20 - 32})({edges})")
        # back under the centred room, both edges move again: centred
        self.drag(t, 1, 1100)
        left, right = t.wait_for(f"(e => e[0] > {rail} && e)({edges})")
        self.assertLessEqual(abs(left - (vw - right)), 1)
        self.assertEqual(self.browser.errors, [])


class UrlKeptByAWiderFolder(unittest.TestCase):
    """st/url-move without a browser: registering a folder above a registered docs/ leaves its docs' URLs working."""

    def test_old_url_still_answers(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        docs = tmp.copy_examples("w/docs")
        plan = docs / "acme-saved-carts-plan.bluedoc.json"
        self.assertEqual(tmp.run("serve.py", "add", docs).returncode, 0)
        server = Server(tmp)
        server.start()
        self.addCleanup(server.stop)
        url = server.url_for(plan)
        self.assertEqual(tmp.run("serve.py", "add", tmp.dir / "w").returncode, 0)
        self.assertEqual(server.url_for(plan), url)
        self.assertEqual(server.req("GET", url)[0], 200)
        body = json.dumps({"path": url, "import": False, "ops": [[NOTE_KEY, "kept"]]}).encode()
        headers = {"Content-Type": "application/json", "X-Bluedoc": "1", "Origin": f"http://{server.host}"}
        self.assertEqual(server.req("PUT", "/__bluedoc/state", body, headers)[0], 200)
        index = json.loads(server.req("GET", "/__bluedoc/index.json")[1])
        self.assertEqual(sum(d["path"].endswith(plan.name) for r in index["roots"] for d in r["docs"]), 1, "the plan is listed twice")


if __name__ == "__main__":
    unittest.main()
