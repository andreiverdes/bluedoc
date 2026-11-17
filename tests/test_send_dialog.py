"""The send dialog: one for Approve, Request changes, Send answers and a review's send key (sd/one).

Every kind lists what goes first, then the note (the one-line field), then Copy and the primary key (sd/order).
Request changes takes a note too: it goes under the title of its Markdown and as `note` in its JSON, the rest of the
request as before (sd/changes-note). A page no agent is connected to (an -o file over file://) has no send: the primary
copies (Copy approval on Approve, Copy elsewhere) and the grey Copy is hidden (sd/no-agent). A plan held for an answer
(Answer it, the primary off) is tested in test_page_state."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from _support import TempHome
from test_page_state import CHROME, GO, Browser, ChromePage, Tab

# what each kind's dialog shows, top to bottom: the sections, the note, the footer
ORDER = """(d => { const y = s => d.querySelector(s).getBoundingClientRect(), secs = [...d.querySelectorAll('.sd-body > .sd-sec')];
  return [secs.length > 0, secs.every(s => s.getBoundingClientRect().bottom <= y('.sd-note').top), y('.sd-note .ac-line').bottom <= y('.ft').top,
    !!d.querySelector('.sd-note .ac-line > textarea + .ac-att'), !d.querySelector('.ac-go'), d.querySelector('.ft').firstElementChild.classList.contains('cp'),
    d.querySelector('.ft').lastElementChild.classList.contains('pri')]; })"""


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class SendDialog(ChromePage):
    def order(self, tab: Tab, dlg: str) -> list:
        tab.wait_for(f"!!document.querySelector('{dlg}[open]')")
        return tab.ev(f"{ORDER}(document.querySelector('{dlg}[open]'))")

    def test_every_kind_lists_what_goes_then_the_note_then_its_keys(self) -> None:
        a = self.open(self.server.url_for(self.docs / "acme-fit-design.bluedoc.json"))
        a.ev("document.querySelector('.bd-key.approve').click()")
        self.assertEqual(self.order(a, ".bd-approve"), [True] * 7, "Approve")
        a.ev("document.querySelector('.bd-approve[open] .hd .x').click()")
        a.ev("BP.annotate({type: 'general', note: 'Acme: phone screens first.'})")
        a.ev(f"{GO}.click()")
        self.assertEqual(self.order(a, ".bd-chgs"), [True] * 7, "Request changes")
        self.assertEqual(a.ev("[...document.querySelectorAll('.bd-chgs[open] .sd-sec')].map(s => s.dataset.sec)"), ["comments", "picks"])
        for doc, key in (("acme-orders.bluedoc.json", "Send"), ("acme-review-findings.bluedoc.json", "Reply and fix")):
            with self.subTest(doc):
                t = self.open(self.server.url_for(self.docs / doc))
                t.wait_for("!!document.querySelector('.bd-anntb .bd-key.send')")
                t.ev("document.querySelector('.bd-anntb .bd-key.send').click()")
                self.assertEqual(self.order(t, ".bd-sendans"), [True] * 7)
                t.wait_for("!document.querySelector('.bd-sendans .ft .cp').hidden")
                self.assertEqual(t.ev("document.querySelector('.bd-sendans .ft .pri').textContent"), key)
        self.assertEqual(self.browser.errors, [])

    def test_request_changes_carries_the_note(self) -> None:
        a = self.open(self.server.url_for(self.plan))
        a.ev("BP.annotate({type: 'pin', key: 'tldr', note: 'Acme: say where carts live.'})")
        before = a.ev("BP.changesPayload()")
        self.assertNotIn("note", before)
        a.ev(f"{GO}.click()")
        a.wait_for("(d => !!d && !d.querySelector('.ft .cp').hidden)(document.querySelector('.bd-chgs[open]'))")
        a.ev("(t => { t.value = 'Acme: ship it behind a flag.'; t.dispatchEvent(new Event('input')); })(document.querySelector('.bd-chgs[open] .sd-note textarea'))")
        p = a.ev("BP.changesPayload()")
        self.assertEqual(p["note"], "Acme: ship it behind a flag.")
        self.assertEqual(p["markdown"].split("\n\n", 2)[1], "Acme: ship it behind a flag.", "the note sits under the title")
        self.assertEqual(p["markdown"].replace("Acme: ship it behind a flag.\n\n", "", 1), before["markdown"], "the rest of the request is as it was")
        self.assertEqual({k: v for k, v in p.items() if k not in ("note", "at", "markdown")}, {k: v for k, v in before.items() if k not in ("at", "markdown")})
        # ⌘↵ in the note presses Send; the note goes, and the field is empty again
        a.ev("document.querySelector('.bd-chgs[open] .sd-note textarea').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', metaKey: true, bubbles: true}))")
        self.toast(a, "change request sent")
        self.assertIn("Acme: ship it behind a flag.", self.reply(self.plan))
        self.assertEqual(a.ev("document.querySelector('.bd-chgs .sd-note textarea').value"), "")
        self.assertEqual(self.browser.errors, [])


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class NoAgent(unittest.TestCase):
    """An -o file over file://: no server, so no send."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = Path(tempfile.mkdtemp(prefix="bluedoc-chrome-"))
        cls.browser = Browser(cls.profile)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        shutil.rmtree(cls.profile, ignore_errors=True)

    def test_the_primary_copies_and_copy_hides(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        docs = tmp.copy_examples()
        f = tmp.dir / "design.html"
        r = tmp.run("build.py", docs / "acme-fit-design.bluedoc.json", "-o", f)
        self.assertEqual(r.returncode, 0, r.stderr)
        t = Tab(self.browser)
        self.browser.call("Page.navigate", {"url": f.as_uri()}, t.session)
        t.wait_for("document.readyState === 'complete' && !!window.BP", 20)
        keys = "(d => [d.querySelector('.ft .cp').hidden, d.querySelector('.ft .pri').textContent, d.querySelector('.ft .pri').disabled])"
        t.ev("document.querySelector('.bd-key.approve').click()")
        t.wait_for("!!document.querySelector('.bd-approve[open]')")
        self.assertEqual(t.ev(f"{keys}(document.querySelector('.bd-approve[open]'))"), [True, "Copy approval", False])
        t.ev("document.querySelector('.bd-approve[open] .hd .x').click()")
        t.ev("BP.annotate({type: 'general', note: 'Acme: phone screens first.'})")
        t.ev(f"{GO}.click()")
        t.wait_for("!!document.querySelector('.bd-chgs[open]')")
        self.assertEqual(t.ev(f"{keys}(document.querySelector('.bd-chgs[open]'))"), [True, "Copy", False])
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
