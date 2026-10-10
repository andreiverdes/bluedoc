"""The page's state sync in a real browser: headless Chrome over the DevTools protocol, on pages `serve.py run` serves.

Two docs with one doc.id each keep their own outbox (st/shared-outbox). A wider folder leaves a doc's URL as it was,
and a write the server answers with 404 stays in the outbox and reaches the server once the URL answers again
(st/url-move). Approve on a page whose doc was edited in place after it loaded is refused, and the page offers
Reload (st/approval-unseen). A doc that quotes an HTML comment opener renders (bld/comment-escape). A plan's item
comments and every page's "Need more details" items count toward Request changes and go with it (rc/items).

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
        """A new tab on url, through a one-time ?key= link (what `serve.py open` prints), so the page may save."""
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

    def test_a_doc_quoting_a_comment_opener_renders(self) -> None:
        quoted = "<!-- Acme banner -->\n<h1>Acme</h1>"
        doc = json.loads(self.plan.read_text(encoding="utf-8"))
        doc["id"] = "acme-snippet"
        doc["sections"].append({"id": "snippet", "title": "Snippet", "blocks": [{"type": "code", "lang": "html", "code": quoted}]})
        path = self.docs / "acme-snippet.bluedoc.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        a = self.open(self.server.url_for(path))
        self.assertEqual(a.ev("BP.doc.sections.at(-1).blocks[0].code"), quoted)


GO = "document.querySelector('.bd-key.go')"   # the tray's Request changes key


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ItemRequests(ChromePage):
    """Request changes counts what goes with it beside the pending annotations (rc/items): on a plan, a comment on an
    item written or changed since the last send; on every page, a decision item marked "Need more details", which shows
    "Details requested" once sent and resets on a newer rev."""

    def count(self, tab: Tab) -> list:
        """[disabled, the number on the key]"""
        return tab.ev(f"(b => [b.disabled, b.querySelector('.n').textContent])({GO})")

    def send_changes(self, tab: Tab, says: str) -> None:
        tab.ev(f"{GO}.click()")
        tab.wait_for("(d => !!d && !d.querySelector('.ft .bp-btn:last-child').hidden)(document.querySelector('.bd-chgs[open]'))")
        self.assertIn(says, tab.ev("document.querySelector('.bd-chgs[open] .cnt').textContent"))
        tab.ev("document.querySelector('.bd-chgs[open] .ft .bp-btn:last-child').click()")
        self.toast(tab, "change request sent")

    def reply(self, doc: Path, *flags: str) -> str:
        r = self.tmp.run("serve.py", "reply", doc, "--kind", "changes", *flags)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

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
