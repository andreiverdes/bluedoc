"""Edit mode (inline-edit E1): a reader changes a screen's text in place and deletes elements, as `element` drafts.

`build.py patch el:<artboard>/<sel>` with --set text= or --delete rewrites one element in its screen file, byte for byte
elsewhere, and leaves the artboard alone; anything else on an el: key is refused. The server keeps an `element` draft and
drops a malformed or oversized one. In Chrome (BLUEDOC_BROWSER_TESTS=1): a double-click edits a design screen's or a
slide's text in place, Delete hides an element, both are drafts that stay across a reload and go with Request changes as
`patch` commands, which applied make the drafts resolved; Restore shows a deleted element again; markup typed as text
stays text; a live page's draft comes back after its DOM is swapped (hot reload); an earlier revision has no Edit key and
ignores forged edits."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import quote

from _support import Server, TempHome

import build
import serve   # on sys.path through _support
from test_page_state import CHROME, Browser, ChromePage, Tab, until
from test_website import StubDevServer, site_doc, write_site

FIT = "acme-fit-design.bluedoc.json"
DECK = "acme-fit-deck.bluedoc.json"


class PatchElement(unittest.TestCase):
    """`patch el:` changes one element in the screen file; the artboard stays."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.doc = self.docs / FIT
        self.today = self.docs / "acme-fit-design.design" / "today.html"
        self.before = self.today.read_text(encoding="utf-8")

    def patch(self, *args: str) -> subprocess.CompletedProcess:
        return self.tmp.run("build.py", "patch", self.doc, *args)

    def artboards(self) -> list[str]:
        return [a["id"] for a in build.board_of(json.loads(self.doc.read_text(encoding="utf-8")))["artboards"]]

    def test_set_text_rewrites_only_the_text_run(self) -> None:
        ids = self.artboards()
        r = self.patch("el:today/start-workout", "--set", 'text="Start run"', "--resolves", "c1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.today.read_text(encoding="utf-8"),
                         self.before.replace('data-nav-label="Tap Start workout">Start workout</button>', 'data-nav-label="Tap Start workout">Start run</button>'))
        self.assertEqual(self.artboards(), ids)
        self.assertEqual(json.loads(self.doc.read_text(encoding="utf-8"))["resolves"], ["c1"])

    def test_set_text_is_html_escaped(self) -> None:
        r = self.patch("el:today/start-workout", "--set", 'text="<img src=x onerror=alert(1)> & go"')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(">&lt;img src=x onerror=alert(1)&gt; &amp; go</button>", self.today.read_text(encoding="utf-8"))

    def test_a_css_path_and_a_text_run_beside_an_icon(self) -> None:
        self.today.write_text(self.before.replace('<h1 class="title">Today</h1>', '<h1 class="title"><svg class="i"></svg>\n  Today </h1>'), encoding="utf-8")
        start = self.today.read_text(encoding="utf-8")
        r = self.patch('el:today/[data-bd="greeting"]>div:nth-of-type(1)>h1:nth-of-type(1)', "--set", 'text="Your day"')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.today.read_text(encoding="utf-8"), start.replace("</svg>\n  Today </h1>", "</svg>\n  Your day </h1>"))

    def test_delete_removes_the_element_and_its_line(self) -> None:
        ids = self.artboards()
        r = self.patch("el:today/heart", "--delete")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [l for l in self.before.splitlines(keepends=True) if 'data-bd="heart"' not in l]
        self.assertEqual(self.today.read_text(encoding="utf-8"), "".join(lines))
        self.assertEqual(self.artboards(), ids, "--delete on an el: key removed the artboard")

    def test_other_options_and_unknown_elements_are_refused(self) -> None:
        src = self.doc.read_bytes()
        for args in (["--set", "label=Go"], ["--json", '{"text": "Go"}'], ["--append", "1"],
                     ["--set", 'text=""'], ["--set", 'text="Hi"', "--set", "kind=push"]):
            r = self.patch("el:today/start-workout", *args)
            self.assertEqual(r.returncode, 2, (args, r.stdout, r.stderr))
        self.assertEqual(self.patch("el:today/nothing-here", "--delete").returncode, 2)
        # several text runs: the reader edits the inner element
        self.today.write_text(self.before.replace(">Start workout</button>", ">Start <b>your</b> workout</button>"), encoding="utf-8")
        r = self.patch("el:today/start-workout", "--set", 'text="Go"')
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("start-workout", r.stderr)
        self.assertEqual(self.doc.read_bytes(), src)

    def test_a_live_page_refuses_and_names_its_source(self) -> None:
        doc_path = write_site(self.tmp.dir / "site", "http://localhost:4321/")
        r = self.tmp.run("build.py", "patch", doc_path, "el:home/#hero-title", "--set", 'text="Hi"')
        self.assertEqual(r.returncode, 2)
        self.assertIn("src/content/site.ts#hero", r.stderr)
        r = self.tmp.run("build.py", "patch", doc_path, "el:home/#hero-title", "--change", "Home: hero shortened.")
        self.assertEqual(r.returncode, 0, r.stderr)


class ElementDraftValue(unittest.TestCase):
    """value_ok keeps an `element` draft and drops a malformed or oversized one."""

    def ann(self, **element) -> str:
        e = {"op": "text", "ab": "today", "sel": "start-workout", "tag": "button", "base": "Start workout", "text": "Start run", "ord": 14, **element}
        return json.dumps({"id": "c1", "type": "element", "status": "pending", "note": "", "target": {"key": "el:today/start-workout", "label": "Today", "text": ""},
                           "element": {k: v for k, v in e.items() if v is not None}})

    def test_kept_and_dropped(self) -> None:
        self.assertTrue(serve.value_ok("__ann:c1", self.ann()))
        self.assertTrue(serve.value_ok("__ann:c1", self.ann(op="delete", text=None)))
        for bad in ({"op": "move"}, {"text": "x" * 1001}, {"base": "x" * 1001}, {"sel": ""}, {"sel": 5}, {"text": None}, {"ord": "3"}, {"tag": "t" * 21}):
            self.assertFalse(serve.value_ok("__ann:c1", self.ann(**bad)), bad)
        self.assertFalse(serve.value_ok("__ann:c1", json.dumps({"id": "c1", "type": "element", "target": {"key": "k", "label": ""}})))

    def test_history_values_kept_and_dropped(self) -> None:
        draft = json.loads(self.ann())
        self.assertTrue(serve.value_ok("__hist", json.dumps({"rev": "C", "steps": ["h1", "h2"], "cursor": 1, "sealed": 0})))
        self.assertTrue(serve.value_ok("__hist:h1", json.dumps({"label": "Text", "ops": [{"id": "c1", "before": None, "after": draft}]})))
        for bad in ({"rev": "C", "steps": ["h1"], "cursor": 2, "sealed": 0}, {"rev": "C", "steps": ["H 1"], "cursor": 0, "sealed": 0},
                    {"rev": "C", "steps": ["h"] * 201, "cursor": 0, "sealed": 0}, {"rev": "C", "steps": [], "cursor": 0, "sealed": 1}, []):
            self.assertFalse(serve.value_ok("__hist", json.dumps(bad)), bad)
        for bad in ({"label": "Text", "ops": []}, {"label": "Text", "ops": [{"id": "c2", "before": None, "after": draft}]},
                    {"label": "Text", "ops": [{"id": "c1", "before": {**draft, "type": "nope"}, "after": None}]}):
            self.assertFalse(serve.value_ok("__hist:h1", json.dumps(bad)), bad)


class DeckDrafts(unittest.TestCase):
    """A deck export with Include unapplied edits: the slides' element drafts go into their text as the frames show them."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.doc = self.docs / DECK
        self.title = (self.docs / "acme-fit-deck.design" / "title.html").read_text(encoding="utf-8")

    def test_drafts_apply_where_the_element_still_has_its_base(self) -> None:
        out = build.apply_element_drafts(self.title, [
            {"sel": "headline", "tag": "h1", "base": "Q3 launch review", "text": "Q3 <b>launch</b> & review"},
            {"sel": "presenter", "tag": "p", "base": "Product team · 14 October 2026", "del": True},
            {"sel": "kicker", "tag": "p", "base": "Not the kicker's text", "text": "Skipped"},
            {"sel": "nothing-here", "tag": "p", "base": "", "text": "Skipped"}])
        self.assertIn(">Q3 &lt;b&gt;launch&lt;/b&gt; &amp; review</h1>", out)
        self.assertNotIn('data-bd="presenter"', out)
        self.assertNotIn("Skipped", out)
        self.assertIn(">Acme Fit · Q3 2026</p>", out)
        # a text edit inside a deleted element goes with it
        out = build.apply_element_drafts(self.title, [{"sel": "headline", "tag": "h1", "base": "Q3 launch review", "text": "Gone"},
                                                      {"sel": "title", "tag": "section", "base": build._plain(build._ScreenTree(self.title).els[0]["text"]), "del": True}])
        self.assertEqual(out.strip(), "")

    def test_the_export_route_with_and_without_drafts(self) -> None:
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        server = Server(self.tmp)
        server.start()
        self.addCleanup(server.stop)
        url = server.url_for(self.doc)
        edit = {"title": [{"sel": "headline", "tag": "h1", "base": "Q3 launch review", "text": "Q3 launch, reviewed"}]}
        post = lambda body, **h: server.req("POST", "/__bluedoc/deck", json.dumps(body).encode(), {"Content-Type": "application/json", "X-Bluedoc": "1", **h})   # noqa: E731
        status, html = post({"path": url, "format": "html", "drafts": edit})
        self.assertEqual(status, 200, html[:300])
        self.assertIn(b"Q3 launch, reviewed", html)
        status, html = server.req("GET", f"/__bluedoc/deck?path={quote(url)}&format=html")
        self.assertEqual(status, 200)
        self.assertNotIn(b"Q3 launch, reviewed", html)
        self.assertIn(b"Q3 launch review", html)
        # malformed drafts, drafts on an earlier revision and a POST without the key are refused
        self.assertEqual(post({"path": url, "drafts": {"title": [{"sel": "headline", "tag": "h1", "base": "x", "text": "a\nb"}]}})[0], 400)
        self.assertEqual(post({"path": url, "rev": "A", "drafts": edit})[0], 400)
        self.assertEqual(post({"path": url, "drafts": edit}, **{"X-Bluedoc-Key": "wrong"})[0], 403)
        # the CLI's --deck has no reader drafts: the revision's text
        r = self.tmp.run("build.py", self.doc, "--deck", self.tmp.dir / "deck.html")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Q3 launch review", (self.tmp.dir / "deck.html").read_text(encoding="utf-8"))


def frame_eval(tab: Tab, part: str, expr: str):
    """expr in the frame whose URL holds part (pieces split by '*', each in it: the server's host and the screen file,
    so an earlier test's tab never answers): an out-of-process frame (a sandboxed screen) through its own target, else a
    frame of the tab through an isolated world (the frame's DOM, not its scripts)."""
    b, pieces = tab.browser, part.split("*")
    hit = lambda url: all(p in url for p in pieces)   # noqa: E731
    for info in b.call("Target.getTargets")["targetInfos"]:
        if info["type"] == "iframe" and hit(info["url"]):
            sessions = b.__dict__.setdefault("frame_sessions", {})
            if info["targetId"] not in sessions:
                sessions[info["targetId"]] = b.call("Target.attachToTarget", {"targetId": info["targetId"], "flatten": True})["sessionId"]
            try:
                r = b.call("Runtime.evaluate", {"expression": expr, "returnByValue": True}, sessions[info["targetId"]])
            except RuntimeError:
                sessions.pop(info["targetId"], None)
                continue
            return r["result"].get("value")

    def frames(f):
        yield f["frame"]
        for c in f.get("childFrames", []):
            yield from frames(c)
    fr = next((f for f in frames(b.call("Page.getFrameTree", session=tab.session)["frameTree"]) if hit(f.get("url", ""))), None)
    if fr is None:
        return None
    ctx = b.call("Page.createIsolatedWorld", {"frameId": fr["id"], "worldName": "bd-test"}, tab.session)["executionContextId"]
    r = b.call("Runtime.evaluate", {"expression": expr, "contextId": ctx, "returnByValue": True}, tab.session)
    return r["result"].get("value")


def mouse(tab: Tab, x: float, y: float, clicks: int = 1) -> None:
    for n in range(1, clicks + 1):
        for kind, buttons in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
            tab.browser.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "buttons": buttons, "clickCount": n}, tab.session)
        time.sleep(0.05)


def key(tab: Tab, k: str, code: int) -> None:
    for kind in ("rawKeyDown", "keyUp"):
        tab.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": k, "code": k, "windowsVirtualKeyCode": code}, tab.session)


class EditOnBoard:
    """Helpers for a board in Edit mode: where an element of a frame is on the window, a click or double-click on it."""
    tab: Tab

    def at(self, ab: str, part: str, css: str, fx: float = .5, fy: float = .5) -> list[float]:
        """The window point at (fx, fy) of css's box in artboard ab's frame (its URL holds part), once the board stops
        moving the frame (a focus animates)."""
        r = until(lambda: frame_eval(self.tab, part, f"(e => e && (r => [r.left + r.width * {fx}, r.top + r.height * {fy}])(e.getBoundingClientRect()))(document.querySelector({json.dumps(css)}))"))
        self.assertTrue(r, f"no {css} in {part}")
        where = (f"(f => {{ const b = f.getBoundingClientRect(), k = b.width / f.width; return [b.left + {r[0]} * k, b.top + {r[1]} * k]; }})"
                 f"(document.querySelector('iframe.bd-ab-fr[data-ab=\"{ab}\"]'))")

        def still():
            p = self.tab.ev(where)
            time.sleep(0.25)
            return p if self.tab.ev(where) == p else None
        return until(still)

    def frame_text(self, part: str, css: str):
        return frame_eval(self.tab, part, f"(e => e && [e.textContent.replace(/\\s+/g, ' ').trim(), getComputedStyle(e).display])(document.querySelector({json.dumps(css)}))")

    def edit_text(self, ab: str, part: str, css: str, text: str) -> None:
        """Click css and wait until the page holds it as the selection (the frame is in Edit), then double-click it,
        type text over its selected text, Enter."""
        self.tab.ev("BP.setMode('edit')")
        x, y = self.at(ab, part, css)
        mouse(self.tab, x, y)
        self.tab.wait_for(f"(s => s && s.ab === {json.dumps(ab)})(BP.board().editSel)")
        x, y = self.at(ab, part, css)
        mouse(self.tab, x, y, 2)
        self.assertTrue(until(lambda: frame_eval(self.tab, part, "!!document.querySelector('[contenteditable]')")), "the double-click didn't start editing")
        self.tab.browser.call("Input.insertText", {"text": text}, self.tab.session)
        key(self.tab, "Enter", 13)

    def scr(self, name: str) -> str:
        """A frame_eval part for this test's screen file name."""
        return f"{self.server.host}/*/{name}"

    def element_drafts(self) -> list[dict]:
        return [d for d in self.tab.ev("BP.boardEdit()")["drafts"] if d["type"] == "element"]


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class EditDesign(ChromePage, EditOnBoard):
    def setUp(self) -> None:
        super().setUp()
        self.doc = self.docs / FIT
        self.url = self.server.url_for(self.doc)
        self.tab = self.open(self.url)
        self.tab.wait_for("!!BP.boardEdit()")
        self.tab.ev("BP.board({focus: 'today'})")
        self.tab.wait_for("BP.board().artboards.find(a => a.id === 'today').ready", 15)

    def stored(self) -> list[dict]:
        return [a for a in (json.loads(v) for k, v in self.state(self.url).items() if k.startswith("__ann:")) if a.get("type") == "element"]

    def test_a_text_edit_is_a_draft_kept_across_a_reload_and_applied_by_its_command(self) -> None:
        t = self.tab
        self.edit_text("today", self.scr("today.html"), '[data-bd="start-workout"]', "Start run")
        ds = until(self.element_drafts)
        self.assertEqual([(d["key"], d["element"]["op"], d["element"]["base"], d["element"]["text"]) for d in ds],
                         [("el:today/start-workout", "text", "Start workout", "Start run")])
        self.assertEqual(self.frame_text(self.scr("today.html"), '[data-bd="start-workout"]')[0], "Start run")
        self.assertTrue(until(self.stored), "the draft never reached state.db")
        # a reload: the frame shows the draft again
        t.go(self.base + self.url)
        t.ev("BP.board({focus: 'today'})")
        self.assertTrue(until(lambda: (self.frame_text(self.scr("today.html"), '[data-bd="start-workout"]') or [""])[0] == "Start run", 15))
        self.assertEqual(t.wait_for("(a => a && a.drafts && a.drafts['start-workout'])(BP.board().artboards.find(a => a.id === 'today'))"), "shown")
        # a second edit folds in, keeping the first base; back to the base drops it
        self.edit_text("today", self.scr("today.html"), '[data-bd="start-workout"]', "Go")
        self.assertTrue(until(lambda: [d["element"]["text"] for d in self.element_drafts()] == ["Go"]))
        self.assertEqual(self.element_drafts()[0]["element"]["base"], "Start workout")
        self.edit_text("today", self.scr("today.html"), '[data-bd="start-workout"]', "Start workout")
        self.assertTrue(until(lambda: self.element_drafts() == []))
        self.edit_text("today", self.scr("today.html"), '[data-bd="start-workout"]', "Start run")
        did = until(self.element_drafts)[0]["id"]
        # readback: the draft's line, its file and the command
        md = t.ev("BP.changesPayload().markdown")
        self.assertIn(f'- ({did}) `el:today/start-workout` Text in Today › start-workout: "Start workout" → "Start run"\n  File: acme-fit-design.design/today.html', md)
        cmd = f"build.py patch {FIT} el:today/start-workout --set 'text=\"Start run\"' --change 'Today: Start workout → Start run.' --resolves {did}"
        self.assertIn(cmd, md)
        self.assertEqual([a["element"]["text"] for a in t.ev("BP.changesPayload().annotations") if a["type"] == "element"], ["Start run"])
        r = self.tmp.run("build.py", "patch", self.doc, "el:today/start-workout", "--set", 'text="Start run"', "--resolves", did)
        self.assertEqual(r.returncode, 0, r.stderr)
        t.go(self.base + self.url)
        t.ev("BP.board({focus: 'today'})")
        self.assertTrue(until(lambda: [(d["status"]) for d in self.element_drafts()] == ["resolved"], 15))
        t.ev("BP.comments({open: true})")
        t.ev("document.querySelector('.bd-cs-f [data-f=all]').click()")
        self.assertIn("Applied in rev", t.wait_for(f"document.querySelector('.bd-cs-c[data-id={did}]')?.textContent"))
        self.assertEqual(self.browser.errors, [])

    def test_delete_hides_the_element_and_restore_shows_it(self) -> None:
        t = self.tab
        t.ev("BP.setMode('edit')")
        x, y = self.at("today", self.scr("today.html"), '[data-bd="heart"]', .06, .1)   # the card's padding, not its text
        mouse(t, x, y)
        self.assertEqual(t.wait_for("BP.board().editSel && BP.board().editSel.sel"), "heart")
        key(t, "Delete", 46)
        ds = until(self.element_drafts)
        self.assertEqual([(d["key"], d["element"]["op"], d["element"]["tag"]) for d in ds], [("el:today/heart", "delete", "div")])
        self.assertTrue(until(lambda: (self.frame_text(self.scr("today.html"), '[data-bd="heart"]') or [0, ""])[1] == "none"))
        md = t.ev("BP.changesPayload().markdown")
        self.assertIn(f"build.py patch {FIT} el:today/heart --delete --change 'Today: heart removed.' --resolves {ds[0]['id']}", md)
        # the screen itself can't be deleted
        x, y = self.at("today", self.scr("today.html"), '[data-bd="today"]', .01, .5)
        mouse(t, x, y)
        self.assertEqual(t.wait_for("BP.board().editSel && BP.board().editSel.sel"), "today")
        key(t, "Delete", 46)
        self.toast(t, "can't be deleted")
        self.assertEqual(len(self.element_drafts()), 1)
        # Restore on the draft's card
        t.ev("BP.comments({open: true})")
        btn = f"[...document.querySelectorAll('.bd-cs-c[data-id={ds[0]['id']}] .mt button')].find(b => b.textContent === 'Restore')"
        t.wait_for(f"!!{btn}")
        t.ev(f"{btn}.click()")
        self.assertTrue(until(lambda: self.element_drafts() == []))
        self.assertTrue(until(lambda: (self.frame_text(self.scr("today.html"), '[data-bd="heart"]') or [0, ""])[1] != "none"))
        self.assertEqual(self.browser.errors, [])

    def test_markup_typed_as_text_stays_text(self) -> None:
        t = self.tab
        evil = "<img src=x onerror=alert(1)>"
        self.edit_text("today", self.scr("today.html"), '[data-bd="start-workout"]', evil)
        ds = until(self.element_drafts)
        self.assertEqual(ds[0]["element"]["text"], evil)
        self.assertEqual(frame_eval(t, self.scr("today.html"), "[document.querySelector('[data-bd=\"start-workout\"]').textContent.trim(), document.querySelectorAll('img[src=x]').length]"), [evil, 0])
        t.ev("BP.comments({open: true})")
        card = f".bd-cs-c[data-id={ds[0]['id']}]"
        self.assertIn(evil, t.wait_for(f"document.querySelector('{card} .eld')?.textContent"))
        self.assertEqual(t.ev(f"document.querySelectorAll('{card} img, .bd-sp img[src=x]').length"), 0)
        self.assertIn(f'"{evil}"', t.ev("BP.changesPayload().markdown"))
        self.assertEqual(self.browser.errors, [])

    def test_an_earlier_revision_has_no_edit_key_and_ignores_forged_edits(self) -> None:
        t = self.tab
        self.edit_text("today", self.scr("today.html"), '[data-bd="start-workout"]', "Start run")
        until(self.element_drafts)
        # a new rev: the one before it (which has Today) is an earlier revision
        rev = json.loads(self.doc.read_text(encoding="utf-8"))["meta"]["rev"]
        r = self.tmp.run("build.py", "patch", self.doc, "el:today/greeting", "--change", "Today: a hand edit.")
        self.assertEqual(r.returncode, 0, r.stderr)
        t.go(f"{self.base}{self.url}?rev={rev}")
        self.assertEqual(t.ev("document.querySelectorAll('.bd-anntb [data-m=edit]').length"), 0)
        self.assertIsNone(t.ev("BP.boardEdit()"))
        t.ev("BP.board({focus: 'today'})")
        t.wait_for("BP.board().artboards.find(a => a.id === 'today').ready", 15)
        self.assertEqual(self.frame_text(self.scr("today.html"), '[data-bd="start-workout"]')[0], "Start workout", "a draft showed on an earlier revision")
        # a screen that posts edit and key messages changes nothing
        frame_eval(t, self.scr("today.html"), "parent.postMessage({bd: 'edit', sel: 'start-workout', tag: 'button', base: 'Start workout', text: 'Forged'}, '*'), "
                                    "parent.postMessage({bd: 'key', k: 'delete'}, '*'), 1")
        time.sleep(0.5)
        self.assertEqual([a["type"] for a in t.ev("BP.annotations()") if a.get("element", {}).get("text") == "Forged"], [])


def combo(tab: Tab, k: str, code: int, mods: int) -> None:
    """A key with modifiers (CDP: 2 Ctrl, 8 Shift) to the focused frame."""
    for kind in ("rawKeyDown", "keyUp"):
        tab.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": k, "code": "Key" + k.upper(), "windowsVirtualKeyCode": code, "modifiers": mods}, tab.session)


CTRL, SHIFT = 2, 8


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class History(ChromePage, EditOnBoard):
    """One undo/redo history per doc: every draft kind, kept across a reload, 200 steps, empty on a new rev."""

    def setUp(self) -> None:
        super().setUp()
        self.doc = self.docs / FIT
        self.url = self.server.url_for(self.doc)
        self.tab = self.open(self.url)
        self.load()

    def load(self) -> None:
        self.tab.wait_for("!!BP.boardEdit()")
        self.tab.ev("BP.board({focus: 'today'})")
        self.tab.wait_for("BP.board().artboards.find(a => a.id === 'today').ready", 15)

    def board(self) -> dict:
        return self.tab.ev("BP.boardEdit()")

    def kinds(self) -> list[tuple]:
        return sorted((d["type"], d.get("element", {}).get("op")) for d in self.board()["drafts"])

    def page_key(self, k: str, code: int, mods: int) -> None:
        """The key on the page itself, not in a screen's frame."""
        self.tab.ev("document.activeElement && document.activeElement.blur(), 1")
        combo(self.tab, k, code, mods)

    def hist_keys(self) -> list[str]:
        return [k for k in self.state(self.url) if k.startswith("__hist:")]

    def test_undo_and_redo_across_kinds_and_a_reload(self) -> None:
        t, today = self.tab, self.scr("today.html")
        undo_btn, redo_btn = "document.querySelector('.bd-btb [aria-keyshortcuts^=\"Meta+Z\"]')", "document.querySelector('.bd-btb [aria-keyshortcuts^=\"Shift+Meta+Z\"]')"
        self.assertEqual(t.ev(f"[{undo_btn}.disabled, {redo_btn}.disabled]"), [True, True])
        home = self.board()["positions"]["today"]
        self.edit_text("today", today, '[data-bd="start-workout"]', "Start run")
        until(self.element_drafts)
        x, y = self.at("today", today, '[data-bd="heart"]', .06, .1)
        mouse(t, x, y)
        self.assertEqual(t.wait_for("BP.board().editSel && BP.board().editSel.sel"), "heart")
        key(t, "Delete", 46)
        until(lambda: len(self.element_drafts()) == 2)
        t.ev(f"BP.setMode('view'), BP.boardEdit({{move: {{today: [{home[0] + 480}, {home[1]}]}}}}), 1")
        done = [("element", "delete"), ("element", "text"), ("layout", None)]
        self.assertEqual(self.kinds(), done)
        self.assertEqual((self.board()["undo"], self.board()["redo"]), (3, 0))
        self.assertEqual(t.ev(f"[{undo_btn}.disabled, {redo_btn}.disabled]"), [False, True])
        # Ctrl+Z on the page: the move, then the delete
        self.page_key("z", 90, CTRL)
        self.assertTrue(until(lambda: self.board()["positions"]["today"] == home))
        self.page_key("z", 90, CTRL)
        self.assertTrue(until(lambda: self.kinds() == [("element", "text")]))
        self.assertTrue(until(lambda: (self.frame_text(today, '[data-bd="heart"]') or [0, "none"])[1] != "none"))
        # a reload keeps the history
        self.assertTrue(until(lambda: len(self.hist_keys()) == 3), "the history never reached state.db")
        t.go(self.base + self.url)
        self.load()
        self.assertEqual((self.board()["undo"], self.board()["redo"]), (1, 2))
        t.ev(f"{undo_btn}.click()")
        self.assertTrue(until(lambda: self.kinds() == []))
        self.assertTrue(until(lambda: (self.frame_text(today, '[data-bd="start-workout"]') or [""])[0] == "Start workout"))
        self.assertEqual(t.ev(f"[{undo_btn}.disabled, {redo_btn}.disabled]"), [True, False])
        # redo: Shift+Ctrl+Z, Ctrl+Y and the toolbar's Redo bring them back in order
        self.page_key("z", 90, CTRL | SHIFT)
        self.assertTrue(until(lambda: self.kinds() == [("element", "text")]))
        self.page_key("y", 89, CTRL)
        self.assertTrue(until(lambda: self.kinds() == done[:2]))
        t.ev(f"{redo_btn}.click()")
        self.assertTrue(until(lambda: self.kinds() == done))
        self.assertTrue(until(lambda: self.board()["positions"]["today"] == [home[0] + 480, home[1]]))
        self.assertEqual((self.board()["undo"], self.board()["redo"]), (3, 0))
        # a new step after an undo drops the steps undone; Tidy up (here: every screen back home) is one step
        t.ev(f"BP.boardEdit({{undo: true}}), BP.boardEdit({{move: {{today: [{home[0] + 960}, {home[1]}]}}}}), 1")
        self.assertEqual((self.board()["undo"], self.board()["redo"]), (3, 0))
        t.ev("BP.boardEdit({tidy: true}), 1")
        self.assertTrue(until(lambda: self.board()["undo"] == 4 and self.board()["positions"]["today"] == home))
        self.assertEqual(self.kinds(), done[:2])
        t.ev("BP.boardEdit({undo: true}), 1")
        self.assertTrue(until(lambda: self.board()["positions"]["today"] == [home[0] + 960, home[1]]))
        self.assertEqual(self.browser.errors, [])

    def test_capped_at_200_steps_and_empty_on_a_new_rev(self) -> None:
        t = self.tab
        home = self.board()["positions"]["today"]
        t.ev(f"for (let i = 1; i <= 205; i++) BP.boardEdit({{move: {{today: [{home[0]} + i * 24, {home[1]}]}}}}); 1")
        self.assertEqual((self.board()["undo"], self.board()["redo"]), (200, 0))
        self.assertTrue(until(lambda: len(self.hist_keys()) == 200, 20), "the stored history isn't 200 steps")
        for _ in range(200):
            t.ev("BP.boardEdit({undo: true}), 1")
        self.assertEqual(self.board()["undo"], 0)
        self.assertEqual(self.board()["positions"]["today"], [home[0] + 5 * 24, home[1]], "undo went past the oldest step kept")
        # a new rev: the stack starts empty, the draft stays
        t.ev("BP.boardEdit({redo: true}), 1")
        r = self.tmp.run("build.py", "patch", self.doc, "el:today/greeting", "--change", "Today: a hand edit.")
        self.assertEqual(r.returncode, 0, r.stderr)
        until(lambda: len(self.hist_keys()) == 200)
        t.go(self.base + self.url)
        self.load()
        self.assertEqual((self.board()["undo"], self.board()["redo"]), (0, 0))
        self.assertEqual([d["type"] for d in self.board()["drafts"]], ["layout"])
        self.assertTrue(until(lambda: self.hist_keys() == [] and "__hist" not in self.state(self.url)), "the old rev's history stayed in state.db")
        self.assertEqual(self.browser.errors, [])

    def test_a_text_field_keeps_its_own_undo(self) -> None:
        t, today = self.tab, self.scr("today.html")
        home = self.board()["positions"]["today"]
        t.ev(f"BP.boardEdit({{move: {{today: [{home[0] + 240}, {home[1]}]}}}}), 1")
        self.assertEqual(self.board()["undo"], 1)
        # a field on the page
        t.ev("BP.comments({open: true}), 1")
        t.wait_for("!!document.querySelector('.bd-sp textarea')")
        t.ev("document.querySelector('.bd-sp textarea').focus(), 1")
        t.browser.call("Input.insertText", {"text": "Looks good"}, t.session)
        combo(t, "z", 90, CTRL)
        combo(t, "z", 90, CTRL | SHIFT)
        time.sleep(0.3)
        self.assertEqual((self.board()["undo"], self.board()["redo"]), (1, 0))
        self.assertEqual(self.board()["positions"]["today"], [home[0] + 240, home[1]])
        # an element being edited in a screen
        t.ev("BP.setMode('edit')")
        x, y = self.at("today", today, '[data-bd="start-workout"]')
        mouse(t, x, y)
        t.wait_for("(s => s && s.sel === 'start-workout')(BP.board().editSel)")
        mouse(t, x, y, 2)
        self.assertTrue(until(lambda: frame_eval(t, today, "!!document.querySelector('[contenteditable]')")))
        t.browser.call("Input.insertText", {"text": "Go"}, t.session)
        combo(t, "z", 90, CTRL)
        time.sleep(0.3)
        self.assertEqual((self.board()["undo"], self.board()["redo"]), (1, 0))
        self.assertTrue(frame_eval(t, today, "!!document.querySelector('[contenteditable]')"), "the undo key ended the edit")
        key(t, "Escape", 27)
        self.assertEqual(self.element_drafts(), [])
        self.assertEqual(self.browser.errors, [])

    def test_undo_and_redo_keys_from_a_screen(self) -> None:
        t, today = self.tab, self.scr("today.html")
        self.edit_text("today", today, '[data-bd="start-workout"]', "Start run")
        until(self.element_drafts)
        press = "document.body.dispatchEvent(new KeyboardEvent('keydown', {{key: '{}', ctrlKey: true, shiftKey: {}, bubbles: true, cancelable: true}})), 1"
        frame_eval(t, today, press.format("z", "false"))
        self.assertTrue(until(lambda: self.element_drafts() == []))
        frame_eval(t, today, press.format("Z", "true"))
        self.assertTrue(until(lambda: [d["element"]["text"] for d in self.element_drafts()] == ["Start run"]))
        t.ev("BP.boardEdit({undo: true}), 1")
        frame_eval(t, today, press.format("y", "false"))
        self.assertTrue(until(lambda: len(self.element_drafts()) == 1))
        self.assertEqual((self.board()["undo"], self.board()["redo"]), (1, 0))
        self.assertEqual(self.browser.errors, [])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class EditDeck(ChromePage, EditOnBoard):
    def test_a_slide_takes_a_text_edit(self) -> None:
        doc = self.docs / DECK
        self.tab = self.open(self.server.url_for(doc))
        self.tab.wait_for("!!BP.boardEdit()")
        self.tab.ev("BP.board({focus: 'title'})")
        self.tab.wait_for("BP.board().artboards.find(a => a.id === 'title').ready", 15)
        self.edit_text("title", self.scr("title.html"), '[data-bd="headline"]', "Q3 launch, reviewed")
        ds = until(self.element_drafts)
        self.assertEqual([(d["key"], d["element"]["text"]) for d in ds], [("el:title/headline", "Q3 launch, reviewed")])
        self.assertIn("File: acme-fit-deck.design/title.html", self.tab.ev("BP.changesPayload().markdown"))
        self.assertEqual(self.browser.errors, [])

    def test_export_includes_unapplied_edits_only_when_asked(self) -> None:
        t = self.tab = self.open(self.server.url_for(self.docs / DECK))
        t.wait_for("!!BP.boardEdit()")
        t.ev("BP.board({focus: 'title'})")
        t.wait_for("BP.board().artboards.find(a => a.id === 'title').ready", 15)
        self.edit_text("title", self.scr("title.html"), '[data-bd="headline"]', "Q3 launch, reviewed")
        until(self.element_drafts)
        # the downloads, as the blobs the page saves
        t.ev("window.__blobs = []; (o => { URL.createObjectURL = b => (window.__blobs.push(b), o(b)); })(URL.createObjectURL.bind(URL)); 1")
        box = "document.querySelector('.bd-btb .bd-expm [role=menuitemcheckbox]')"

        def export(edits: bool) -> str:
            n = t.ev("window.__blobs.length")
            t.ev("document.querySelector('.bd-btb .bd-expb').click()")
            t.wait_for("!document.querySelector('.bd-btb .bd-expm').hidden")
            if t.ev(f"{box}.getAttribute('aria-checked')") != json.dumps(edits):
                t.ev(f"{box}.click()")
            self.assertEqual(t.ev(f"{box}.getAttribute('aria-checked')"), json.dumps(edits))
            t.ev("document.querySelector('.bd-btb .bd-expm [data-format=html]').click()")
            t.wait_for(f"window.__blobs.length > {n}", 20)
            return t.ev(f"window.__blobs[{n}].text()")
        self.assertEqual(t.ev(f"{box}.getAttribute('aria-checked')"), "false", "Include unapplied edits starts off")
        off = export(False)
        self.assertNotIn("Q3 launch, reviewed", off)
        self.assertIn("Q3 launch review", off)
        self.assertIn("Q3 launch, reviewed", export(True))
        self.assertEqual(self.browser.errors, [])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class EditLivePage(unittest.TestCase, EditOnBoard):
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
        self.doc_path = write_site(self.tmp.dir / "site", self.dev.origin + "/", site_doc(self.dev.origin + "/"))
        self.assertEqual(self.tmp.run("serve.py", "add", self.doc_path.parent).returncode, 0)
        self.server = Server(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.browser.errors.clear()
        status, raw = self.server.req("POST", "/__bluedoc/unlock", b"{}", {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        self.tab = Tab(self.browser)
        self.tab.go(f"http://{self.server.host}{self.server.url_for(self.doc_path)}?key={json.loads(raw)['token']}")
        self.tab.wait_for("(b => b && b.artboards[0].ready)(BP.board())", 20)

    def live_part(self) -> str:
        return self.tab.ev("new URL(document.querySelector('iframe.bd-ab-fr').src).host")

    def test_a_delete_comes_back_after_a_hot_reload(self) -> None:
        t, part = self.tab, self.live_part()
        t.ev("BP.setMode('edit')")
        x, y = self.at("home", part, "#faq h2")
        mouse(t, x, y)
        self.assertEqual(t.wait_for("BP.board().editSel && BP.board().editSel.sel"), "#faq>h2:nth-of-type(1)")
        key(t, "Delete", 46)
        ds = until(self.element_drafts)
        self.assertEqual([(d["key"], d["element"]["op"]) for d in ds], [("el:home/#faq>h2:nth-of-type(1)", "delete")])
        self.assertTrue(until(lambda: (self.frame_text(part, "#faq h2") or [0, ""])[1] == "none"))
        # hot reload: the section's nodes are replaced; within a frame the new heading is hidden again
        frame_eval(t, part, "document.querySelector('#faq').innerHTML = '<h2>Questions</h2>', 1")
        self.assertTrue(until(lambda: (self.frame_text(part, "#faq h2") or [0, ""])[1] == "none", 2))
        self.assertEqual(t.ev("BP.board().artboards[0].drafts['#faq>h2:nth-of-type(1)']"), "shown")
        md = t.ev("BP.changesPayload().markdown")
        self.assertIn(f"  Live page: {self.dev.origin}/  At: 1440 px wide\n  Source: `src/components/Faq.astro:3`", md)
        self.assertIn(f"# ({ds[0]['id']}) a live page: edit the source, then record it\nbuild.py patch site.bluedoc.json 'el:home/#faq>h2:nth-of-type(1)' --change", md)
        self.assertEqual(self.browser.errors, [])

    def test_a_text_edit_on_a_live_page(self) -> None:
        part = self.live_part()
        self.edit_text("home", part, "#hero-title", "Track it all")
        ds = until(self.element_drafts)
        self.assertEqual([(d["key"], d["element"]["base"], d["element"]["text"]) for d in ds], [("el:home/#hero-title", "Track everything", "Track it all")])
        self.assertEqual(self.frame_text(part, "#hero-title")[0], "Track it all")
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
