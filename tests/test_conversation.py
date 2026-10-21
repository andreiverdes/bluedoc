"""Item conversations, option rows and several answers in a real browser (headless Chrome, `serve.py run`).

A reply sent with Request changes leaves the item's box and becomes the reader's message, stamped with the rev it went
on; the box is empty after a reload (conv/send). The agent's `build.py patch … --reply` lands between the reader's
messages by rev, marked New, and opens its item; `?rev=` shows the thread as it stood then, read-only (conv/order).
A comment sent before threads (`:note` with a matching `:note-sent`) becomes the first message, "earlier"
(conv/migrate). Options are Accordion rows: a click on the row or → opens the explanation, the radio picks, ↑ ↓ move,
Space picks; an option without `md` is its label (opt/rows). Need more details is the last row: it clears the pick
(with `multi`, the ticks) and an option turns it off (opt/more). A `multi` decision stores its ticks and sends them as
`choice: [ids]` and `→ **A**, **B**` (opt/multi). A pin's follow-up goes out under its id with the agent's reply quoted
and reopens a resolved comment (conv/pin)."""
from __future__ import annotations

import json
import unittest

from _support import load_json
from test_page_state import CHROME, GO, ChromePage, Tab, until

PLAN = "acme-saved-carts-plan.bluedoc.json"
KEYS = {" ": ("Space", 32), "ArrowDown": ("ArrowDown", 40), "ArrowUp": ("ArrowUp", 38), "ArrowRight": ("ArrowRight", 39), "ArrowLeft": ("ArrowLeft", 37)}


def note_hash(s: str) -> str:
    """template.html's noteHash (FNV-1a over UTF-16 code units, base 36): what `:note-sent` kept before threads."""
    n = 0x811C9DC5
    for unit in s.encode("utf-16-le")[::2]:
        n = ((n ^ unit) * 0x01000193) & 0xFFFFFFFF
    digits, out = "0123456789abcdefghijklmnopqrstuvwxyz", ""
    while True:
        n, r = divmod(n, 36)
        out = digits[r] + out
        if not n:
            return out


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class Conversation(ChromePage):
    def count(self, tab: Tab) -> list:
        """Request changes: [disabled, the number on the key]"""
        return tab.ev(f"(b => [b.disabled, b.querySelector('.n').textContent])({GO})")

    def press(self, tab: Tab, key: str) -> None:
        code, vk = KEYS[key]
        for kind in ("keyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": code, "windowsVirtualKeyCode": vk,
                                                         **({"text": key} if key == " " and kind == "keyDown" else {})}, tab.session)

    def patch(self, *args: str) -> None:
        r = self.tmp.run("build.py", "patch", self.plan, *args)
        self.assertEqual(r.returncode, 0, r.stderr)

    def thread(self, tab: Tab, key: str) -> list:
        return [(m["who"], m["rev"], m["md"]) for m in tab.ev(f"BP.thread({json.dumps(key)})")]

    def test_a_sent_reply_becomes_a_message_and_the_box_empties(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        box = "document.querySelector('#item-decisions-retention .bp-note textarea')"
        a.ev("BP.setNote('decisions/retention', 'Acme: what does 180 days cost in storage?')")
        self.assertEqual(self.count(a), [False, "1"])
        self.send_changes(a, "1 comment on items")
        self.assertEqual(self.thread(a, "decisions/retention"), [("you", "1", "Acme: what does 180 days cost in storage?")])
        self.assertEqual([a.ev(f"{box}.value"), self.count(a)], ["", [True, "0"]])
        reply = self.reply(self.plan)
        self.assertIn("  > Acme: what does 180 days cost in storage?", reply)
        self.assertIn(f'  Reply: `build.py patch {PLAN} item:decisions/retention --reply "…"`', reply)
        # the thread is stored and the draft is gone; a reload shows the message and an empty box
        sent = until(lambda: (s := self.state(url)) and "decisions:retention:note" not in s and s.get("decisions:retention:thread"))
        self.assertEqual([(m["md"], m["rev"]) for m in json.loads(sent)], [("Acme: what does 180 days cost in storage?", "1")])
        a.go(self.base + url)
        self.assertEqual(self.thread(a, "decisions/retention"), [("you", "1", "Acme: what does 180 days cost in storage?")])
        self.assertEqual([a.ev(f"{box}.value"), self.count(a)], ["", [True, "0"]])
        self.assertEqual(a.ev("document.querySelector('#item-decisions-retention .bp-cl-sum').textContent"), "1 message")

    def test_an_agent_reply_sits_between_two_messages_and_rev_shows_the_thread_then(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        a.ev("BP.setNote('decisions/retention', 'Acme: what does 180 days cost?')")
        self.send_changes(a, "1 comment on items")
        self.patch("item:decisions/retention", "--reply", "About **2 GB** a month at Acme's volume.")
        a.go(self.base + url)
        row = "document.querySelector('#item-decisions-retention')"
        # the new reply: marked New, its item open on load, a box for the next message
        self.assertEqual(a.ev("BP.thread('decisions/retention').map(m => [m.who, m.rev, m.new])"), [["you", "1", False], ["agent", "2", True]])
        self.assertTrue(a.ev(f"{row}.classList.contains('open')"), "an item with a new reply opens on load")
        self.assertEqual(a.ev(f"{row}.querySelector('.bp-msg.agent .mb strong')?.textContent"), "2 GB")
        a.ev("BP.setNote('decisions/retention', 'Acme: fine, keep 180 days.')")
        self.assertIn("  > Agent, rev 2: About **2 GB** a month at Acme's volume.", a.ev("BP.changesPayload().markdown"))
        self.send_changes(a, "1 comment on items")
        self.patch("item:decisions/retention", "--reply", "Done: 180 days.")
        a.go(self.base + url)
        self.assertEqual(self.thread(a, "decisions/retention"), [
            ("you", "1", "Acme: what does 180 days cost?"), ("agent", "2", "About **2 GB** a month at Acme's volume."),
            ("you", "2", "Acme: fine, keep 180 days."), ("agent", "3", "Done: 180 days.")])
        self.assertEqual(a.ev(f"[...{row}.querySelectorAll('.bp-msg')].map(m => m.querySelector('.who').textContent + ' ' + m.querySelector('.rv').textContent)"),
                         ["You rev 1", "Agent rev 2", "You rev 2", "Agent rev 3"])
        # an earlier rev: the thread as it stood then, and no box to write in
        for rev, n in (("2", 3), ("1", 1)):
            with self.subTest(rev=rev):
                a.go(f"{self.base}{url}?rev={rev}")
                self.assertEqual(len(self.thread(a, "decisions/retention")), n)
                self.assertEqual(a.ev(f"[!!{row}.querySelector('textarea'), !!{row}.querySelector('.bp-opt.more')]"), [False, False])

    def test_an_old_sent_comment_becomes_the_first_message(self) -> None:
        url = self.server.url_for(self.plan)
        old, draft = "Acme: why not 90 days?", "Acme: a draft not sent yet"
        ops = [["decisions:retention:note", old], ["decisions:retention:note-sent", note_hash(old)], ["decisions:prices:note", draft],
               ["decisions:prices:note-sent", note_hash("an older text")]]
        body = json.dumps({"path": url, "import": False, "ops": ops}).encode()
        self.assertEqual(self.server.req("PUT", "/__bluedoc/state", body, {"Content-Type": "application/json", "X-Bluedoc": "1", "Origin": self.base})[0], 200)
        a = self.open(url)
        self.assertEqual(self.thread(a, "decisions/retention"), [("you", None, old)])
        self.assertEqual(a.ev("document.querySelector('#item-decisions-retention .bp-msg .rv').textContent"), "earlier")
        # a comment changed after it went is still a draft: it stays in the box and counts as pending
        self.assertEqual(self.thread(a, "decisions/prices"), [])
        self.assertEqual(a.ev("document.querySelector('#item-decisions-prices .bp-note textarea').value"), draft)
        self.assertEqual(self.count(a), [False, "1"])
        s = until(lambda: (s := self.state(url)) and "decisions:retention:note" not in s and s)
        self.assertNotIn("decisions:retention:note-sent", s)
        self.assertEqual([(m["md"], m["rev"]) for m in json.loads(s["decisions:retention:thread"])], [(old, None)])

    def test_option_rows_open_and_pick_by_mouse_and_keys(self) -> None:
        doc = load_json(self.plan)
        dec = next(b for s in doc["sections"] for b in s.get("blocks", []) if b.get("id") == "decisions")
        del next(i for i in dec["items"] if i["id"] == "retention")["choices"][2]["md"]   # an older doc: an option without an explanation
        self.plan.write_text(json.dumps(doc), encoding="utf-8")
        a = self.open(self.server.url_for(self.plan))
        row = "document.querySelector('#item-decisions-retention')"
        opt = lambda i: f"{row}.querySelector('.bp-opt[data-id={i}]')"  # noqa: E731
        pick = "BP.replyPayload().items.find(i => i.item === 'retention').choice"
        # a click on the row opens its explanation (one row at a time); it doesn't pick
        a.ev(f"{opt('d90')}.querySelector('.oh').click()")
        self.assertEqual(a.ev(f"[{opt('d90')}.querySelector('.ob').checkVisibility(), {opt('d90')}.querySelector('.one').checkVisibility(), {pick}]"), [True, False, None])
        a.ev(f"{opt('d180')}.querySelector('.oh').click()")
        self.assertEqual(a.ev(f"[{opt('d90')}.classList.contains('open'), {opt('d180')}.classList.contains('open')]"), [False, True])
        # the radio picks: tint, Your pick
        a.ev(f"{opt('d90')}.querySelector('.pk').click()")
        self.assertEqual(a.ev(f"[{pick}, {opt('d90')}.classList.contains('on'), {opt('d90')}.querySelector('.yp').textContent, {row}.classList.contains('done')]"),
                         ["d90", True, "Your pick", True])
        # keys: ↓ moves, Space picks, → opens, ← closes
        a.ev(f"{opt('d90')}.querySelector('.pk').focus()")
        self.press(a, "ArrowDown")
        self.assertEqual(a.ev("document.activeElement.dataset.id"), "d180")
        self.press(a, " ")
        self.assertEqual(a.ev(pick), "d180")
        self.press(a, "ArrowLeft")
        self.assertFalse(a.ev(f"{opt('d180')}.querySelector('.ob').checkVisibility()"))
        self.press(a, "ArrowRight")
        self.assertTrue(a.ev(f"{opt('d180')}.querySelector('.ob').checkVisibility()"))
        # without md: the label alone, and a click on it picks
        self.assertEqual(a.ev(f"[{opt('forever')}.classList.contains('plain'), !!{opt('forever')}.querySelector('.cv, .one, .ob')]"), [True, False])
        a.ev(f"{opt('forever')}.querySelector('.oh').click()")
        self.assertEqual(a.ev(pick), "forever")

    def test_need_more_details_clears_the_pick_and_the_ticks(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        row = "document.querySelector('#item-decisions-prices')"
        more = f"{row}.querySelector('.bp-opt.more')"
        item = lambda i: f"BP.replyPayload().items.find(x => x.item === '{i}')"  # noqa: E731
        a.ev("BP.choose('decisions/prices', 'notice')")
        a.ev(f"{more}.querySelector('.pk').click()")
        self.assertEqual(a.ev(f"[{item('prices')}.choice, {item('prices')}.more, {more}.querySelector('.pk').getAttribute('aria-checked'), {row}.classList.contains('more'),"
                              f" {row}.classList.contains('open'), document.activeElement === {row}.querySelector('.bp-note textarea')]"), [None, True, "true", True, True, True])
        approve = "document.querySelector('.bd-key.approve').disabled"
        self.assertTrue(a.ev(approve))
        a.ev(f"{row}.querySelector('.bp-opt[data-id=silent] .pk').click()")
        self.assertEqual(a.ev(f"[{item('prices')}.choice, !!{item('prices')}.more, {row}.classList.contains('more')]"), ["silent", False, False])
        a.ev(f"{more}.querySelector('.pk').click()")
        self.send_changes(a, "1 request for more details")
        self.assertIn("`item:decisions/prices` → **Need more details**", self.reply(self.plan))
        self.assertEqual(a.ev(f"[{more}.querySelector('.ol').textContent, {approve}]"), ["Details requested", True])
        # several answers: a checkbox that clears the ticks; a tick turns it off
        g = "document.querySelector('#item-decisions-guests')"
        head = f"{g}.querySelector('.bp-cl-picked').textContent"
        for i in ("accounts", "business"):
            a.ev(f"{g}.querySelector('.bp-opt[data-id={i}] .pk').click()")
        self.assertEqual(a.ev(f"[{head}, {item('guests')}.choice, {g}.querySelector('.bp-opt.more .pk').getAttribute('role')]"), ["2 picked", ["accounts", "business"], "checkbox"])
        a.ev(f"{g}.querySelector('.bp-opt.more .pk').click()")
        self.assertEqual(a.ev(f"[{head}, {item('guests')}.choice, {item('guests')}.more, {g}.querySelectorAll('.bp-opt.on').length]"), ["Asking for more", [], True, 1])
        a.ev(f"{g}.querySelector('.bp-opt[data-id=support] .pk').click()")
        self.assertEqual(a.ev(f"[{head}, {item('guests')}.choice, !!{item('guests')}.more]"), ["1 picked", ["support"], False])

    def test_several_answers_are_stored_and_sent_as_a_list(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        g = "document.querySelector('#item-decisions-guests')"
        a.ev(f"{g}.querySelector('.bp-opt[data-id=business] .pk').click(); {g}.querySelector('.bp-opt[data-id=accounts] .pk').click()")
        self.assertEqual(until(lambda: self.state(url).get("decisions:guests")), "=accounts,business|")
        self.assertIn("`item:decisions/guests` → **Personal accounts**, **Business accounts**", a.ev("BP.progressMarkdown()"))
        a.go(self.base + url)
        self.assertEqual(a.ev(f"[...{g}.querySelectorAll('.pk[aria-checked=true]')].map(b => b.dataset.id)"), ["accounts", "business"])
        self.assertTrue(a.ev(f"{g}.classList.contains('done')"))
        # approved with the two ticks; one more is a pick changed since the approval
        p = a.ev("BP.approvePayload('')")
        self.assertEqual([x["choice"] for x in p["answers"] if x["item"] == "guests"], [["accounts", "business"]])
        a.ev("document.querySelector('.bd-key.approve').click()")
        a.wait_for("!!document.querySelector('.bd-approve[open] .bp-btn.ok')")
        a.ev("document.querySelector('.bd-approve[open] .bp-btn.ok').click()")
        self.toast(a, "approved")
        a.ev(f"{g}.querySelector('.bp-opt[data-id=support] .pk').click()")
        self.assertIn("Pick changed since approval", a.ev("document.querySelector('.bd-planchip').textContent"))
        a.ev(f"{g}.querySelector('.bp-opt[data-id=support] .pk').click()")
        self.assertEqual(a.ev("document.querySelector('.bd-planchip').textContent"), "Approved · rev 1")

    def test_a_pin_follow_up_reopens_a_resolved_comment(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        cid = a.ev("BP.annotate({type: 'pin', key: 'tldr', note: 'Acme: who owns the nightly sweep?'}).id")
        self.send_changes(a, "1 pending comment")
        self.patch(f"ann:{cid}", "--reply", "The platform team; step 3 says so now.")
        a.go(self.base + url)
        a.ev("BP.comments({open: true, filter: 'all'})")
        card = f"document.querySelector('.bd-cs-c[data-id={cid}]')"
        a.wait_for(f"!!{card}")
        self.assertEqual(a.ev(f"[{card}.querySelector('.sago').textContent, [...{card}.querySelectorAll('.bp-msg')].map(m => m.querySelector('.mb').textContent.trim())]"),
                         ["Answered in rev 2", ["The platform team; step 3 says so now."]])
        a.ev(f"{card}.querySelector('[aria-label=Resolve]').click()")
        self.assertEqual(a.ev(f"BP.annotations().find(x => x.id === '{cid}').status"), "resolved")
        # a follow-up: pending until sent; it goes under the same id with the agent's reply quoted
        a.ev(f"(t => {{ t.value = 'Acme: and who gets paged?'; t.dispatchEvent(new Event('input')); }})({card}.querySelector('.rp textarea'))")
        self.assertEqual(self.count(a), [False, "1"])
        p = a.ev("BP.changesPayload()")
        self.assertEqual([(x["id"], x["note"]) for x in p["annotations"]], [(cid, "Acme: and who gets paged?")])
        self.assertIn("Follow-up: Acme: and who gets paged?", p["markdown"])
        self.assertIn("> Agent, rev 2: The platform team; step 3 says so now.", p["markdown"])
        self.assertIn(f'Reply: `build.py patch {PLAN} ann:{cid} --reply "…"`', p["markdown"])
        self.send_changes(a, "1 pending comment")
        ann = a.ev(f"BP.annotations().find(x => x.id === '{cid}')")
        self.assertEqual([ann["status"], [(m["md"], m["rev"]) for m in ann["thread"]], "draft" in ann], ["open", [("Acme: and who gets paged?", "2")], False])
        a.go(self.base + url)
        a.ev("BP.comments({open: true, filter: 'open'})")
        a.wait_for(f"!!{card}")
        self.assertEqual(a.ev(f"[...{card}.querySelectorAll('.bp-msg')].map(m => m.querySelector('.who').textContent + ' ' + m.querySelector('.rv').textContent)"),
                         ["Agent rev 2", "You rev 2"])
        self.assertEqual(self.count(a), [True, "0"])

    def test_a_closed_decision_shows_its_box_and_a_click_into_it_opens_the_row(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        row = "document.querySelector('#item-decisions-retention')"
        box = f"{row}.querySelector(':scope > .bp-note')"
        state = f"(b => [{row}.classList.contains('open'), b.checkVisibility(), [...b.querySelectorAll('.acts button')].map(x => x.disabled)])({box})"
        self.assertEqual(a.ev(state), [False, True, [True, True]])
        # a Tab into the field leaves the row closed
        a.ev(f"{box}.querySelector('textarea').focus()")
        self.assertFalse(a.ev(f"{row}.classList.contains('open')"))
        a.ev("document.activeElement.blur()")
        # a click opens it; the details grow above the box, which stays under the pointer
        x, y = a.ev(f"(t => {{ t.scrollIntoView({{block: 'center', behavior: 'instant'}}); const r = t.getBoundingClientRect(); return [r.x + 30, r.y + r.height / 2]; }})({box}.querySelector('textarea'))")
        for kind, buttons in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
            self.browser.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "buttons": buttons, "clickCount": 1}, a.session)
        a.wait_for(f"{row}.classList.contains('open')")
        self.assertLess(abs(a.ev(f"{box}.querySelector('textarea').getBoundingClientRect().top + {box}.querySelector('textarea').getBoundingClientRect().height / 2") - y), 3)
        self.assertTrue(a.ev(f"document.activeElement === {box}.querySelector('textarea')"))
        # Cancel and Save are enabled while the text differs from the saved comment
        self.browser.call("Input.insertText", {"text": "Acme: how big is it?"}, a.session)
        self.assertEqual(a.ev(state)[2], [False, False])
        a.ev(f"{box}.querySelector('.acts .primary').click()")
        self.assertEqual(a.ev(state)[2], [True, True])
        self.assertEqual(until(lambda: (self.state(url) or {}).get("decisions:retention:note")), "Acme: how big is it?")

    def test_a_decision_with_no_details_has_nothing_to_open_until_its_first_message(self) -> None:
        doc = load_json(self.plan)
        guests = next(it for s in doc["sections"] for b in s.get("blocks", []) if b.get("type") == "checklist"
                      for it in b.get("items", []) if it["id"] == "guests")
        del guests["detail"]
        self.plan.write_text(json.dumps(doc))
        url = self.server.url_for(self.plan)
        a = self.open(url)
        row, other = "document.querySelector('#item-decisions-guests')", "document.querySelector('#item-decisions-retention')"
        look = "(r => [r.classList.contains('empty'), r.classList.contains('open'), r.querySelector('.bp-cl-body').textContent])"
        self.assertEqual(a.ev(f"{look}({row})"), [True, False, ""])
        # a click on the question or into the box opens nothing
        a.ev(f"{row}.querySelector('.bp-cl-head').click(); {row}.querySelector(':scope > .bp-note textarea').dispatchEvent(new InputEvent('input'))")
        self.assertEqual(a.ev(f"{look}({row})"), [True, False, ""])
        # a decision with details still opens to them, under their caption
        a.ev(f"{other}.querySelector('.bp-cl-head').click()")
        self.assertEqual(a.ev(f"[{other}.classList.contains('open'), {other}.querySelector('.bp-cl-body > .bp-cap').textContent]"), [True, "Details"])
        # its first message gives it a conversation to open
        a.ev("BP.setNote('decisions/guests', 'Acme: guests too?')")
        self.send_changes(a, "1 comment on items")
        self.assertFalse(a.ev(f"{row}.classList.contains('empty')"))
        a.ev(f"{row}.querySelector('.bp-cl-head').click()")
        self.assertEqual(a.ev(f"[{row}.classList.contains('open'), {row}.querySelector('.bp-convo').checkVisibility()]"), [True, True])


if __name__ == "__main__":
    unittest.main()
