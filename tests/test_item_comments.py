"""Every item's thread in the Comments panel, on every page type (headless Chrome, `serve.py run`).

A comment saved in an item's reply box, a plan's question or a docs page's progress item, shows as a card in the
Comments panel: Pending under "Not sent yet", its chip naming the key that carries it on that page (a plan's Request
changes or Approve, a docs page's Send answers); sent, it moves to Open under "You answered"; the agent's `--reply` puts
it under "<agent> replied", Waiting for you, and the panel opens on it on load. A card names where its item lives (the
checklist's title) and its click opens the item, and the item holding it, scrolls to it and rings it. A progress item
the doc marks done is Resolved."""
from __future__ import annotations

import json
import unittest

from test_page_state import CHROME, ChromePage, Tab

PLAN = "acme-saved-carts-plan.bluedoc.json"   # decisions: retention, prices, guests; Approve and Request changes
DOCS = "acme-orders.bluedoc.json"             # progress list `local` (Local stack); `seed` holds `local-seed-checks`
SEND = "document.querySelector('.bd-anntb .bd-key.send')"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class ItemComments(ChromePage):
    def panel(self, tab: Tab, f: str) -> dict:
        return tab.ev(f"BP.comments({{filter: {json.dumps(f)}}})")

    def card(self, key: str) -> str:
        return f"document.querySelector('.bd-cs-ic[data-item=\"{key}\"]')"

    def face(self, tab: Tab, key: str) -> list:
        """[where, the item's text, the message line, the state chip]"""
        return tab.ev(f"(c => [c.querySelector('.pr').textContent, c.querySelector('.tt').textContent, c.querySelector('.m').textContent,"
                      f" c.querySelector('.st').textContent])({self.card(key)})")

    def patch(self, doc, *args: str) -> None:
        r = self.tmp.run("build.py", "patch", doc, *args)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_plan_question_comment_is_pending_then_answered_then_waits_for_the_reader(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        a.ev("BP.setNote('decisions/retention', 'Why not 90 days?')")
        p = self.panel(a, "pending")
        self.assertEqual((p["groups"], p["items"]), (["unsent"], [{"item": "decisions/retention", "group": "unsent", "status": "pending"}]))
        where, text, msg, chip = self.face(a, "decisions/retention")
        self.assertEqual((where, msg, chip), ("Decisions", "You: Why not 90 days?", "Goes with Request changes or Approve"))
        self.assertIn("saved cart", text.lower())
        self.assertEqual(a.ev("[...document.querySelectorAll('.bd-cs-f [data-f]')].map(b => b.textContent)"), ["Pending1", "Open0", "Resolved0", "All1"])
        # sent with Request changes: Open, You answered
        self.send_changes(a, "1 comment on items")
        p = self.panel(a, "open")
        self.assertEqual(p["items"], [{"item": "decisions/retention", "group": "answered", "status": "open"}])
        self.assertEqual(self.face(a, "decisions/retention")[2:], ["You: Why not 90 days?", "Answered"])
        self.assertTrue(a.ev(f"{self.card('decisions/retention')}.classList.contains('done')"))
        # the agent answers: Waiting for you, and the panel opens on it although the reader closed it
        self.patch(self.plan, "item:decisions/retention", "--reply", "180 days covers 70 % of reorders.")
        a.ev("BP.sidebar({open: false})")
        a = self.open(url)
        self.assertEqual([a.ev("BP.comments().open"), a.ev("BP.comments().filter")], [True, "open"])
        p = self.panel(a, "open")
        self.assertEqual((p["groups"], p["items"]), (["wait"], [{"item": "decisions/retention", "group": "wait", "status": "open"}]))
        self.assertTrue(a.ev("document.querySelector('.bd-cs-h[data-g=wait]').textContent.endsWith(' replied1')"))
        self.assertEqual(self.face(a, "decisions/retention")[3], "Waiting for you")
        self.assertTrue(self.face(a, "decisions/retention")[2].endswith(": 180 days covers 70 % of reorders."))
        # a reply in its box: Not sent yet again
        a.ev("BP.setNote('decisions/retention', 'Fine, 180.')")
        self.assertEqual(self.panel(a, "pending")["items"], [{"item": "decisions/retention", "group": "unsent", "status": "pending"}])
        self.assertEqual(self.browser.errors, [])

    def test_a_docs_page_progress_item_comment_shows_and_its_card_opens_it(self) -> None:
        doc = self.docs / DOCS
        url = self.server.url_for(doc)
        a = self.open(url)
        a.wait_for(f"!!{SEND}")
        a.ev("BP.setNote('local-seed-checks/brokers', 'Our laptops use 29092.')")
        p = self.panel(a, "pending")
        self.assertEqual(p["items"], [{"item": "local-seed-checks/brokers", "group": "unsent", "status": "pending"}])
        self.assertEqual(self.face(a, "local-seed-checks/brokers")[0::3], ["Before you seed", "Goes with Send answers"])
        # the card opens the item and the one holding it, scrolls to it and rings it
        self.assertEqual(a.ev("[document.querySelector('#item-local-seed').classList.contains('open'), document.querySelector('#item-local-seed-checks-brokers').classList.contains('open')]"), [False, False])
        a.ev("scrollTo(0, 0)")
        a.ev(f"{self.card('local-seed-checks/brokers')}.click()")
        ring = "document.querySelector('.bd-ring')"
        a.wait_for(f"!!{ring}")
        self.assertEqual(a.ev(f"{ring}.id"), "item-local-seed-checks-brokers")
        self.assertEqual(a.ev("[document.querySelector('#item-local-seed').classList.contains('open'), document.querySelector('#item-local-seed-checks-brokers').classList.contains('open')]"), [True, True])
        a.wait_for(f"(r => r.top >= 0 && r.bottom <= innerHeight)({ring}.getBoundingClientRect())")
        # on load, a comment not sent opens the panel on Pending
        a.ev("BP.comments({filter: 'resolved'}); BP.sidebar({open: false})")
        a = self.open(url)
        self.assertEqual([a.ev("BP.comments().open"), a.ev("BP.comments().filter")], [True, "pending"])
        # Send answers sends it: Open; a rev that marks the item done resolves it
        a.ev(f"{SEND}.click()")
        a.wait_for("!document.querySelector('.bd-send[open] .ft .primary').hidden")
        a.ev("document.querySelector('.bd-send[open] .ft .bp-btn.primary').click()")
        self.toast(a, "sent to")
        self.assertEqual(self.panel(a, "open")["items"], [{"item": "local-seed-checks/brokers", "group": "answered", "status": "open"}])
        self.patch(doc, "item:local-seed-checks/brokers", "--json", '{"done": true}')
        a = self.open(url)
        p = self.panel(a, "resolved")
        self.assertEqual(p["items"], [{"item": "local-seed-checks/brokers", "group": "resolved", "status": "resolved"}])
        self.assertEqual(self.face(a, "local-seed-checks/brokers")[3], "Resolved")
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
