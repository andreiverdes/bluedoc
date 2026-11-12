"""General comments and the Comments panel's sort, in a real browser (headless Chrome, `serve.py run`).

The composer at the panel's foot writes a general comment: Esc drops what was typed, Shift+Enter is a new line, Enter
(and ⌘/Ctrl+Enter) saves it as a pending general comment, a card in the list (the speech-bubble chip, General)
counted in Pending and All and on Request changes, the composer keeping the focus; files attach to it as to any
comment; a click on its text edits it and Esc restores it. Request changes sends it (Open); the agent's
`build.py patch … ann:<id> --reply` shows in its card. Empty, the list points at the composer (gc/composer).

Sort is a menu (Newest first, Oldest first, Page order, the current one ticked): page order lists general comments
first, then the page's by their place; the pick orders the cards, titles the key and holds over a reload (gc/sort)."""
from __future__ import annotations

import json
import time
import unittest

from test_page_state import CHROME, GO, ChromePage, Tab, until

TA = "document.querySelector('.bd-cs-ft .bd-gc .cp textarea')"
CP = "document.querySelector('.bd-cs-ft .bd-gc .cp')"
SORT = "document.querySelector('.bd-cs-f .bd-srt .bd-selb')"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class GeneralComments(ChromePage):
    def key(self, tab: Tab, key: str, code: int, modifiers: int = 0, text: str = "") -> None:
        down = {"type": "keyDown", "key": key, "code": key, "windowsVirtualKeyCode": code, "modifiers": modifiers, **({"text": text} if text else {})}
        self.browser.call("Input.dispatchKeyEvent", down, tab.session)
        self.browser.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": key, "windowsVirtualKeyCode": code, "modifiers": modifiers}, tab.session)

    def type(self, tab: Tab, text: str) -> None:
        tab.ev(f"{TA}.focus()")
        self.browser.call("Input.insertText", {"text": text}, tab.session)

    def cards(self, tab: Tab) -> list:
        """The comment cards: [chip, label, note]."""
        return tab.ev("[...document.querySelectorAll('.bd-cs-l li.bd-cs-c')].map(li => [li.querySelector('.bd-ann-num').classList.contains('gen') ? 'gen' :"
                      " li.querySelector('.bd-ann-num').textContent, li.querySelector('.lb').textContent, li.querySelector('.nt')?.textContent ?? ''])")

    def counts(self, tab: Tab) -> dict:
        return tab.ev("Object.fromEntries([...document.querySelectorAll('.bd-cs-f [role=radio]')].map(b => [b.dataset.f, +b.querySelector('i').textContent]))")

    def test_enter_saves_a_general_card_shift_enter_is_a_new_line_and_esc_drops(self) -> None:
        status, raw = self.server.req("POST", "/__bluedoc/register", json.dumps({"doc": str(self.plan), "to": "Claude"}).encode(),
                                      {"Content-Type": "application/json", "X-Bluedoc": "1"})
        self.assertEqual(status, 200, raw)
        url = self.server.url_for(self.plan)
        a = self.open(url)
        a.ev("BP.comments({open: true})")
        a.wait_for(f"{TA}.checkVisibility()")
        # empty: the composer, its hint, and the list pointing at it
        self.assertEqual(a.ev(f"[{TA}.placeholder, {CP}.querySelector('.hint').textContent, {CP}.querySelector('.go').disabled]"),
                         ["Message the agent about the whole doc…", "Goes with Request changes or Approve · ↵ saves", True])
        self.assertIn("in the box below", a.ev("document.querySelector('.bd-cs-e').textContent"))
        # Esc drops what was typed
        self.type(a, "Acme: not this one.")
        self.assertEqual(a.ev(f"[{CP}.querySelector('.go').disabled, {CP}.querySelector('.ghost').hidden]"), [False, False])
        self.key(a, "Escape", 27)
        self.assertEqual(a.ev(f"[{TA}.value, BP.annotations().length]"), ["", 0])
        # Shift+Enter is a new line; Enter saves: a General card, pending, counted; the composer keeps the focus
        self.type(a, "Acme: shorter steps.")
        self.key(a, "Enter", 13, 8, "\r")
        self.type(a, "And one screen.")
        self.assertEqual(a.ev(f"{TA}.value"), "Acme: shorter steps.\nAnd one screen.")
        self.key(a, "Enter", 13, 0, "\r")
        a.wait_for("document.querySelectorAll('.bd-cs-l li.bd-cs-c').length === 1")
        self.assertEqual(self.cards(a), [["gen", "General", "Acme: shorter steps.\nAnd one screen."]])
        self.assertEqual(a.ev(f"[{TA}.value, document.activeElement === {TA}, {GO}.querySelector('.n').textContent]"), ["", True, "1"])
        self.assertEqual(a.ev("document.querySelector('.bd-cs-l li.bd-cs-c').getAttribute('aria-label')"), "General comment")
        self.assertEqual((self.counts(a)["pending"], self.counts(a)["all"]), (1, 1))
        self.assertEqual([x["type"] for x in a.ev("BP.annotations()")], ["general"])
        gid = a.ev("BP.annotations()[0].id")
        # Enter on an empty composer saves nothing; ⌘/Ctrl+Enter saves too
        self.key(a, "Enter", 13, 0, "\r")
        self.assertEqual(a.ev("BP.annotations().length"), 1)
        self.type(a, "Acme: and the badge?")
        self.key(a, "Enter", 13, 2, "\r")
        a.wait_for("BP.annotations().length === 2")
        self.assertEqual(self.counts(a)["pending"], 2)
        # a click on a pending card's text edits it there; Esc restores it
        card = f"document.querySelector('li.bd-cs-c[data-id=\"{gid}\"]')"
        a.ev(f"{card}.querySelector('.nt').click()")
        ed = f"{card}.querySelector('.ed textarea')"
        a.wait_for(f"document.activeElement === {ed}")
        self.browser.call("Input.insertText", {"text": " Typo"}, a.session)
        self.key(a, "Escape", 27)
        self.assertEqual(a.ev(f"[!!{ed}, BP.annotations().find(x => x.id === '{gid}').note]"), [False, "Acme: shorter steps.\nAnd one screen."])
        # files attached in the composer go with the comment
        a.ev(f"(b => {{ const dt = new DataTransfer(); dt.items.add(new File(['data'], 'cart.png')); const i = b.querySelector('input[type=file]');"
             f" i.files = dt.files; i.dispatchEvent(new Event('change')); }})({CP})")
        a.wait_for(f"{CP}.querySelectorAll('.bp-file').length === 1 && !{CP}.querySelector('.bp-files-up')")
        a.ev(f"{CP}.querySelector('.go').click()")
        a.wait_for("BP.annotations().length === 3")
        self.assertEqual(a.ev(f"[{CP}.querySelectorAll('.bp-file').length, BP.annotations().at(-1).files.map(f => f.name)]"), [0, ["cart.png"]])
        # sent with Request changes: Open; the agent's reply shows in its card
        self.send_changes(a, "3 pending comments")
        self.assertEqual(self.counts(a), {"pending": 0, "open": 3, "resolved": 0, "all": 3})
        until(lambda: '"open"' in (self.state(url).get(f"__ann:{gid}") or ""))
        r = self.tmp.run("build.py", "patch", self.plan, f"ann:{gid}", "--reply", "Done: steps 2 and 3 are one now.")
        self.assertEqual(r.returncode, 0, r.stderr)
        a.go(self.base + url)
        a.ev("BP.comments({open: true})")
        a.ev("document.querySelector('.bd-cs-f [role=radio][data-f=\"open\"]').click()")
        a.wait_for(f"{card}?.querySelector('.bp-convo')?.textContent.includes('Done: steps 2 and 3 are one now.')")
        self.assertEqual(self.browser.errors, [])

    def test_the_sort_menu_orders_the_cards_and_is_remembered(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        a.ev("BP.comments({open: true})")
        ids = {}
        for name, spec in (("tldr", "{type: 'pin', key: 'tldr', note: 'Acme: the TL;DR.'}"), ("gen", "{type: 'general', note: 'Acme: the whole doc.'}"),
                           ("header", "{type: 'pin', key: 'header', note: 'Acme: the title.'}")):
            ids[name] = a.ev(f"BP.annotate({spec}).id")
            time.sleep(0.02)   # each its own time
        order = lambda: [next(k for k, v in ids.items() if v == i) for i in a.ev("[...document.querySelectorAll('.bd-cs-l li.bd-cs-c')].map(li => li.dataset.id)")]
        # page order (the default): general comments first, then the page's by their place
        self.assertEqual(order(), ["gen", "header", "tldr"])
        self.assertEqual(a.ev(f"{SORT}.title"), "Sort: Page order")
        menu = "document.querySelector('.bd-cs-f .bd-srt .bd-selm')"

        def pick(label: str) -> None:
            a.ev(f"{SORT}.click()")
            a.wait_for(f"!{menu}.hidden")
            self.assertEqual(a.ev(f"[...{menu}.children].map(r => [r.textContent, r.getAttribute('aria-selected')])"),
                             [[x, str(x == a.ev(f"{SORT}.title").removeprefix("Sort: ")).lower()] for x in ("Newest first", "Oldest first", "Page order")])
            a.ev(f"[...{menu}.children].find(r => r.textContent === {json.dumps(label)}).click()")
            self.assertTrue(a.ev(f"{menu}.hidden"))
            self.assertEqual(a.ev(f"{SORT}.title"), "Sort: " + label)

        pick("Newest first")
        self.assertEqual(order(), ["header", "gen", "tldr"])
        pick("Oldest first")
        self.assertEqual(order(), ["tldr", "gen", "header"])
        # remembered over a reload
        a.go(self.base + url)
        a.ev("BP.comments({open: true})")
        self.assertEqual(order(), ["tldr", "gen", "header"])
        self.assertEqual(a.ev(f"{SORT}.title"), "Sort: Oldest first")
        pick("Page order")
        self.assertEqual(order(), ["gen", "header", "tldr"])
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
