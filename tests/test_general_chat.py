"""General: the chat about the whole doc at the foot of the Comments panel, in a real browser (headless Chrome,
`serve.py run`).

Empty, it is its header and the composer. What is typed is a draft: Esc drops it, ⌘/Ctrl+Enter saves it as a general
comment, a bubble on the right marked not sent yet and counted on Request changes; files attach to it as to any comment.
A pending bubble edits in place (a click on its text) and Esc restores it. Request changes sends it; the agent's
`build.py patch … ann:<id> --reply` shows under it as a bubble on the left with the agent's initial (gc/chat)."""
from __future__ import annotations

import json
import unittest

from test_page_state import CHROME, GO, ChromePage, Tab, until

CHAT = "document.querySelector('.bd-gc')"
TA = f"{CHAT}.querySelector('.cp textarea')"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class GeneralChat(ChromePage):
    def key(self, tab: Tab, key: str, code: int, modifiers: int = 0) -> None:
        for kind in ("keyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": key, "windowsVirtualKeyCode": code, "modifiers": modifiers},
                              tab.session)

    def type(self, tab: Tab, text: str) -> None:
        tab.ev(f"{TA}.focus()")
        self.browser.call("Input.insertText", {"text": text}, tab.session)

    def bubbles(self, tab: Tab) -> list:
        """The chat's bubbles: [side, text, meta]."""
        return tab.ev(f"[...{CHAT}.querySelectorAll('.bd-gc-l > li')].map(li => [li.classList.contains('ag') ? 'agent' : 'you',"
                      " (li.querySelector('.bb') || li).textContent.trim(), li.querySelector('.mt').textContent.replace(/\\s+/g, ' ').trim()])")

    def test_the_chat_saves_restores_attaches_sends_and_shows_the_agents_reply(self) -> None:
        status, raw = self.server.req("POST", "/__bluedoc/register", json.dumps({"doc": str(self.plan), "to": "Claude"}).encode(),
                                      {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        url = self.server.url_for(self.plan)
        a = self.open(url)
        a.ev("BP.comments({open: true})")
        a.wait_for(f"{TA}.checkVisibility()")
        # empty: the header and the composer
        self.assertEqual(a.ev(f"[{CHAT}.querySelector('.gh').textContent, {CHAT}.querySelectorAll('.bd-gc-l > li').length, {TA}.placeholder]"),
                         ["Generalabout the whole doc, not one spot", 0, "Message the agent about the whole doc…"])
        # Esc drops what was typed
        self.type(a, "Acme: not this one.")
        self.assertFalse(a.ev(f"{CHAT}.querySelector('.go').disabled"))
        self.key(a, "Escape", 27)
        self.assertEqual(a.ev(f"[{TA}.value, BP.annotations().length]"), ["", 0])
        # ⌘/Ctrl+Enter saves: a bubble on the right, not sent yet, counted; the composer keeps the focus
        self.type(a, "Acme: shorter steps.")
        self.key(a, "Enter", 13, 2)
        a.wait_for(f"{CHAT}.querySelectorAll('.bd-gc-l > li').length === 1")
        self.assertEqual(self.bubbles(a), [["you", "Acme: shorter steps.", "You · rev 1 · not sent yet"]])
        self.assertEqual(a.ev(f"[{TA}.value, document.activeElement === {TA}, {GO}.querySelector('.n').textContent]"), ["", True, "1"])
        gid = a.ev("BP.annotations().find(x => x.type === 'general').id")
        # a click on its text edits it in place; Esc restores it
        a.ev(f"{CHAT}.querySelector('.bd-gm.pend .bb .tx').click()")
        ed = f"{CHAT}.querySelector('.bd-gm.edit textarea')"
        a.wait_for(f"document.activeElement === {ed}")
        self.browser.call("Input.insertText", {"text": " And the badge?"}, a.session)
        self.key(a, "Escape", 27)
        self.assertEqual(a.ev(f"[!!{ed}, BP.annotations().find(x => x.id === '{gid}').note]"), [False, "Acme: shorter steps."])
        # files attach in the composer and go with the comment
        cp = f"{CHAT}.querySelector('.cp')"
        a.ev(f"(b => {{ const dt = new DataTransfer(); dt.items.add(new File(['data'], 'cart.png')); const i = b.querySelector('input[type=file]');"
             f" i.files = dt.files; i.dispatchEvent(new Event('change')); }})({cp})")
        a.wait_for(f"{cp}.querySelectorAll('.bp-file').length === 1 && !{cp}.querySelector('.bp-files-up')")
        a.ev(f"{CHAT}.querySelector('.go').click()")
        a.wait_for(f"{CHAT}.querySelectorAll('.bd-gc-l > li').length === 2")
        self.assertEqual(a.ev(f"[...{CHAT}.querySelectorAll('.bd-gc-l > li:last-child .bp-file .t')].map(t => t.textContent)"), ["cart.png"])
        self.assertEqual(a.ev(f"[{cp}.querySelectorAll('.bp-file').length, BP.annotations().filter(x => x.type === 'general').at(-1).files.map(f => f.name)]"),
                         [0, ["cart.png"]])
        # sent with Request changes: no longer pending; the agent's reply shows under it, on the left, with its initial
        self.send_changes(a, "2 pending comments")
        self.assertEqual(a.ev(f"{CHAT}.querySelectorAll('.bd-gm.pend').length"), 0)
        until(lambda: '"open"' in (self.state(url).get(f"__ann:{gid}") or ""))
        r = self.tmp.run("build.py", "patch", self.plan, f"ann:{gid}", "--reply", "Done: steps 2 and 3 are one now.")
        self.assertEqual(r.returncode, 0, r.stderr)
        a.go(self.base + url)
        a.ev("BP.comments({open: true})")
        a.wait_for(f"{CHAT}.querySelectorAll('.bd-gc-l > li').length === 3")
        self.assertEqual(self.bubbles(a)[:2], [["you", "Acme: shorter steps.", "You · rev 1"], ["agent", "Done: steps 2 and 3 are one now.", "Claude · rev 2 · New"]])
        self.assertEqual(a.ev(f"{CHAT}.querySelector('.bd-gm.ag .av').textContent"), "C")
        # it opens scrolled to the end
        self.assertTrue(a.ev(f"(l => l.scrollHeight - l.scrollTop - l.clientHeight < 2)({CHAT}.querySelector('.bd-gc-l'))"))
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
