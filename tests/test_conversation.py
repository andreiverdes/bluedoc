"""Item conversations, option rows and several answers in a real browser (headless Chrome, `serve.py run`).

A reply sent with Request changes leaves the item's box and becomes the reader's message, stamped with the rev it went
on; the box is empty after a reload (conv/send). The agent's `build.py patch … --reply` lands between the reader's
messages by rev, marked New, and opens its item; `?rev=` shows the thread as it stood then, read-only (conv/order).
A comment sent before threads (`:note` with a matching `:note-sent`) becomes the first message, "earlier"
(conv/migrate). Answers are Accordion rows: a click on the row or → opens the explanation and its field, the radio
picks and opens, ↑ ↓ move, Space picks; an option without `md` is its label (opt/rows). Tell me more is a pill under
the answers: it clears the pick (with `multi`, the ticks) and an answer turns it off (opt/more). The reply field saves
with Enter into the conversation; a question's detail sits behind More details (card/reply, card/details). A `multi`
decision stores its ticks and sends them as
`choice: [ids]` and `→ **A**, **B**` (opt/multi). A pin's follow-up goes out under its id with the agent's reply quoted
and reopens a resolved comment (conv/pin)."""
from __future__ import annotations

import json
import unittest

from _support import load_json
from test_page_state import CHROME, GO, ChromePage, Tab, until

PLAN = "acme-saved-carts-plan.bluedoc.json"
KEYS = {" ": ("Space", 32), "ArrowDown": ("ArrowDown", 40), "ArrowUp": ("ArrowUp", 38), "ArrowRight": ("ArrowRight", 39), "ArrowLeft": ("ArrowLeft", 37)}
# the visible elements in a card past its right edge
OVERFLOW = ("(li => { const R = li.getBoundingClientRect().right + 0.5; return [...li.querySelectorAll('*')]"
            ".filter(e => e.checkVisibility() && e.getBoundingClientRect().right > R).map(e => e.tagName + '.' + e.getAttribute('class')); })")


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
        box = "document.querySelector('#item-decisions-retention .ac-reply textarea')"
        a.ev("BP.setNote('decisions/retention', 'Acme: what does 180 days cost in storage?')")
        self.assertEqual(self.count(a), [False, "1"])
        self.send_changes(a, "Comments · 1")
        self.assertEqual(self.thread(a, "decisions/retention"), [("you", "1", "Acme: what does 180 days cost in storage?")])
        self.assertEqual([a.ev(f"{box}.value"), self.count(a)], ["", [True, "0"]])
        reply = self.reply(self.plan)
        self.assertIn("  > Acme: what does 180 days cost in storage?", reply)
        self.assertIn("  → item:decisions/retention", reply)
        self.assertIn(f'build.py patch {PLAN} <key> --reply "…" --resolves <id> --no-bump', reply)
        # the thread is stored and the draft is gone; a reload shows the message and an empty box
        sent = until(lambda: (s := self.state(url)) and "decisions:retention:note" not in s and s.get("decisions:retention:thread"))
        self.assertEqual([(m["md"], m["rev"]) for m in json.loads(sent)], [("Acme: what does 180 days cost in storage?", "1")])
        a.go(self.base + url)
        self.assertEqual(self.thread(a, "decisions/retention"), [("you", "1", "Acme: what does 180 days cost in storage?")])
        self.assertEqual([a.ev(f"{box}.value"), self.count(a)], ["", [True, "0"]])
        self.assertEqual(a.ev("document.querySelectorAll('#item-decisions-retention .ac-convo .bp-msg').length"), 1)

    def test_an_agent_reply_sits_between_two_messages_and_rev_shows_the_thread_then(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        a.ev("BP.setNote('decisions/retention', 'Acme: what does 180 days cost?')")
        self.send_changes(a, "Comments · 1")
        # the sent message reaches the server's reader state before the reload reads it back
        until(lambda: len(json.loads(self.state(url).get("decisions:retention:thread") or "[]")) == 1)
        self.patch("item:decisions/retention", "--reply", "About **2 GB** a month at Acme's volume.")
        a.go(self.base + url)
        row = "document.querySelector('#item-decisions-retention')"
        # the new reply: marked New, its item open on load, a box for the next message
        self.assertEqual(a.ev("BP.thread('decisions/retention').map(m => [m.who, m.rev, m.new])"), [["you", "1", False], ["agent", "2", True]])
        self.assertTrue(a.ev(f"{row}.classList.contains('open')"), "an item with a new reply opens on load")
        self.assertEqual(a.ev(f"{row}.querySelector('.bp-msg.agent .mb strong')?.textContent"), "2 GB")
        a.ev("BP.setNote('decisions/retention', 'Acme: fine, keep 180 days.')")
        self.assertIn("  > Agent, rev 2: About **2 GB** a month at Acme's volume.", a.ev("BP.changesPayload().markdown"))
        self.send_changes(a, "Comments · 1")
        until(lambda: len(json.loads(self.state(url).get("decisions:retention:thread") or "[]")) == 2)
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
                self.assertEqual(a.ev(f"[!!{row}.querySelector('textarea'), !!{row}.querySelector('.ac-more')]"), [False, False])

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
        # a comment changed after it went is still a draft: a message not sent yet, and it counts as pending
        self.assertEqual(self.thread(a, "decisions/prices"), [])
        self.assertEqual(a.ev("[...document.querySelectorAll('#item-decisions-prices .bp-msg.unsent .mb')].map(m => m.textContent)"), [draft])
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
        # a click on the row opens its explanation and its field (one row at a time); it doesn't pick
        a.ev(f"{opt('d90')}.querySelector('.oh').click()")
        self.assertEqual(a.ev(f"[{opt('d90')}.querySelector('.ob').checkVisibility(), {opt('d90')}.querySelector('.one').checkVisibility(), {pick}, !!{opt('d90')}.querySelector('.ob .ac-line')]"),
                         [True, False, None, True])
        a.ev(f"{opt('d180')}.querySelector('.oh').click()")
        self.assertEqual(a.ev(f"[{opt('d90')}.classList.contains('open'), {opt('d180')}.classList.contains('open')]"), [False, True])
        # the radio picks and opens the answer: tint, Your pick
        a.ev(f"{opt('d90')}.querySelector('.pk').click()")
        self.assertEqual(a.ev(f"[{pick}, {opt('d90')}.classList.contains('on'), {opt('d90')}.classList.contains('open'), {opt('d90')}.querySelector('.yp').textContent, {row}.classList.contains('done')]"),
                         ["d90", True, True, "Your pick", True])
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
        # without md: the label alone, no one-line explanation; its chevron opens its field, the radio picks
        self.assertEqual(a.ev(f"[{opt('forever')}.classList.contains('plain'), !!{opt('forever')}.querySelector('.one'), !!{opt('forever')}.querySelector('.cv')]"), [True, False, True])
        a.ev(f"{opt('forever')}.querySelector('.pk').click()")
        self.assertEqual(a.ev(pick), "forever")

    def test_tell_me_more_clears_the_pick_and_the_ticks(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        row = "document.querySelector('#item-decisions-prices')"
        more = f"{row}.querySelector('.ac-more')"
        item = lambda i: f"BP.replyPayload().items.find(x => x.item === '{i}')"  # noqa: E731
        a.ev("BP.choose('decisions/prices', 'notice')")
        a.ev(f"{more}.querySelector('.ac-tmm').click()")
        self.assertEqual(a.ev(f"[{item('prices')}.choice, {item('prices')}.more, {more}.querySelector('.ac-tmm').getAttribute('aria-checked'), {row}.classList.contains('more'),"
                              f" {row}.classList.contains('open'), document.activeElement === {row}.querySelector(':scope > .ac-reply textarea')]"), [None, True, "true", True, True, True])
        approve = "document.querySelector('.bd-key.approve').disabled"
        self.assertTrue(a.ev(approve))
        a.ev(f"{row}.querySelector('.bp-opt[data-id=silent] .pk').click()")
        self.assertEqual(a.ev(f"[{item('prices')}.choice, !!{item('prices')}.more, {row}.classList.contains('more')]"), ["silent", False, False])
        a.ev(f"{more}.querySelector('.ac-tmm').click()")
        self.send_changes(a, "1 Tell me more")
        self.assertIn("`item:decisions/prices` → **Tell me more**", self.reply(self.plan))
        self.assertEqual(a.ev(f"[{more}.querySelector('.ac-chip').textContent, {approve}]"), ["Asked · rev 1", True])
        # several answers: a checkbox that clears the ticks; a tick turns it off
        g = "document.querySelector('#item-decisions-guests')"
        head = f"[{g}.querySelector('.bp-cl-picked').textContent, {g}.querySelector('.bp-cl-head .ac-chip').hidden]"
        for i in ("accounts", "business"):
            a.ev(f"{g}.querySelector('.bp-opt[data-id={i}] .pk').click()")
        self.assertEqual(a.ev(f"[{head}, {item('guests')}.choice, {g}.querySelector('.ac-tmm').getAttribute('role')]"), [["2 picked", True], ["accounts", "business"], "checkbox"])
        a.ev(f"{g}.querySelector('.ac-tmm').click()")
        self.assertEqual(a.ev(f"[{head}, {item('guests')}.choice, {item('guests')}.more, {g}.querySelectorAll('.bp-opt.on').length]"), [["", False], [], True, 0])
        a.ev(f"{g}.querySelector('.bp-opt[data-id=support] .pk').click()")
        self.assertEqual(a.ev(f"[{head}, {item('guests')}.choice, !!{item('guests')}.more]"), [["1 picked", True], ["support"], False])

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
        a.ev("BP.acceptRecommended('decisions')")   # the other questions: a plan is approved with every one answered
        a.ev("document.querySelector('.bd-key.approve').click()")
        a.wait_for("!!document.querySelector('.bd-approve[open] .ft .pri')")
        a.ev("document.querySelector('.bd-approve[open] .ft .pri').click()")
        self.toast(a, "approved")
        a.ev(f"{g}.querySelector('.bp-opt[data-id=support] .pk').click()")
        self.assertIn("Pick changed since approval", a.ev("document.querySelector('.bd-planchip').textContent"))
        a.ev(f"{g}.querySelector('.bp-opt[data-id=support] .pk').click()")
        self.assertEqual(a.ev("document.querySelector('.bd-planchip').textContent"), "Approved · rev 1")

    def test_a_pin_follow_up_reopens_a_resolved_comment(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        cid = a.ev("BP.annotate({type: 'pin', key: 'tldr', note: 'Acme: who owns the nightly sweep?'}).id")
        self.send_changes(a, "Comments · 1")
        # the sent comment reaches the server's reader state before the reload reads it back
        until(lambda: bool(self.state(url).get(f"__ann:{cid}")))
        self.patch(f"ann:{cid}", "--reply", "The platform team; step 3 says so now.")
        a.go(self.base + url)
        a.ev("BP.comments({open: true, filter: 'all'})")
        card = f"document.querySelector('.bd-cs-c[data-id={cid}]')"
        a.wait_for(f"!!{card}")
        self.assertEqual(a.ev(f"[{card}.querySelector('.sago').textContent, [...{card}.querySelectorAll('.bp-msg')].map(m => m.querySelector('.mb').textContent.trim())]"),
                         ["Answered in rev 2", ["The platform team; step 3 says so now."]])
        a.ev(f"{card}.querySelector('[aria-label=Resolve]').click()")
        self.assertEqual(a.ev(f"BP.annotations().find(x => x.id === '{cid}').status"), "resolved")
        # a follow-up: unsaved while typed (it counts nowhere), pending once saved; it goes under the same id with the agent's reply quoted
        a.ev(f"(t => {{ t.value = 'Acme: and who gets paged?'; t.dispatchEvent(new Event('input')); }})({card}.querySelector('.rp textarea'))")
        self.assertEqual(self.count(a), [True, "0"])
        a.ev(f"{card}.querySelector('.rp .ft .bp-btn.primary').click()")
        self.assertEqual(self.count(a), [False, "1"])
        p = a.ev("BP.changesPayload()")
        self.assertEqual([(x["id"], x["note"]) for x in p["annotations"]], [(cid, "Acme: and who gets paged?")])
        self.assertIn("Follow-up: Acme: and who gets paged?", p["markdown"])
        self.assertIn("> Agent, rev 2: The platform team; step 3 says so now.", p["markdown"])
        self.assertIn(f"→ ann:{cid} · {cid}", p["markdown"])
        self.assertIn(f'build.py patch {PLAN} <key> --reply "…"', p["markdown"])
        self.send_changes(a, "Comments · 1")
        ann = a.ev(f"BP.annotations().find(x => x.id === '{cid}')")
        self.assertEqual([ann["status"], [(m["md"], m["rev"]) for m in ann["thread"]], "draft" in ann], ["open", [("Acme: and who gets paged?", "2")], False])
        until(lambda: "Acme: and who gets paged?" in (self.state(url).get(f"__ann:{cid}") or ""))
        a.go(self.base + url)
        a.ev("BP.comments({open: true, filter: 'open'})")
        a.wait_for(f"!!{card}")
        self.assertEqual(a.ev(f"[...{card}.querySelectorAll('.bp-msg')].map(m => m.querySelector('.who').textContent + ' ' + m.querySelector('.rv').textContent)"),
                         ["Agent rev 2", "You rev 2"])
        self.assertEqual(self.count(a), [True, "0"])

    def test_a_reply_saves_with_its_foot_and_counts_once_saved(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        cid = a.ev("BP.annotate({type: 'pin', key: 'tldr', note: 'Acme: who signs off the rollout?'}).id")
        self.send_changes(a, "Comments · 1")
        a.ev("BP.comments({open: true, filter: 'open'})")
        card = f"document.querySelector('.bd-cs-c[data-id={cid}]')"
        a.wait_for(f"!!{card}")
        rp, ta = f"{card}.querySelector('.rp')", f"{card}.querySelector('.rp textarea')"
        foot = f"(f => f.checkVisibility() ? [...f.querySelectorAll('.bp-btn')].map(b => b.textContent) : null)({rp}.querySelector('.ft'))"
        # the header, the Pending filter and Request changes: one number
        counts = ("[document.querySelector('.bd-sp-h .n').hidden ? '' : document.querySelector('.bd-sp-h .n').textContent,"
                  " document.querySelector('.bd-cs [data-f=pending] i, [data-f=pending] i').textContent,"
                  f" {GO}.querySelector('.n').textContent]")
        type_ = lambda s: a.ev(f"(t => {{ t.focus(); t.value = {json.dumps(s)}; t.dispatchEvent(new Event('input')); }})({ta})")
        self.assertIsNone(a.ev(foot))
        # typed: Save and Cancel show with Unsaved; nothing counts it yet
        type_("Acme: and the backup?")
        self.assertEqual(a.ev(foot), ["Cancel", "Save"])
        self.assertEqual(a.ev(f"{rp}.querySelector('.ft .un').textContent"), "Unsaved")
        self.assertEqual(a.ev(counts), ["", "0", "0"])
        # Cancel puts the field back, empty
        a.ev(f"{rp}.querySelector('.ft .bp-btn.ghost').click()")
        self.assertEqual([a.ev(f"{ta}.value"), a.ev(foot)], ["", None])
        # Enter saves: the comment is pending, in the Pending filter, and every count agrees
        type_("Acme: and the backup?")
        self.press_enter(a)
        a.wait_for(f"{card}?.checkVisibility() && document.querySelector('[data-f=pending][aria-checked=true]') !== null")
        self.assertEqual(a.ev(counts), ["1 pending", "1", "1"])
        # saved, it is the thread's last message, You · not sent yet, and the field is empty for more
        pend = f"(m => m && m.checkVisibility() ? [m.querySelector('.who').textContent, m.querySelector('.rv').textContent, m.querySelector('.mb').textContent.trim()] : null)({card}?.querySelector('.rp-pend .bp-msg'))"
        self.assertEqual([a.ev(f"{ta}.value"), a.ev(foot), a.ev(pend)], ["", None, ["You", "not sent yet", "Acme: and the backup?"]])
        self.assertEqual(a.ev(f"BP.annotations().find(x => x.id === '{cid}').draft"), "Acme: and the backup?")
        # Edit puts it back in the field with Cancel and Save; Cancel leaves it as it was
        a.ev(f"{card}.querySelector('.rp-pend [aria-label=\"Edit your reply\"]').click()")
        self.assertEqual([a.ev(f"{ta}.value"), a.ev(foot), a.ev(pend)], ["Acme: and the backup?", ["Cancel", "Save"], None])
        for w in (280, 320):   # the reply's foot stays inside the card at the panel's narrowest width too
            a.ev(f"document.documentElement.style.setProperty('--sp-w', '{w}px')")
            self.assertEqual(a.ev(f"{OVERFLOW}({card})"), [], w)
        a.ev(f"{rp}.querySelector('.ft .bp-btn.ghost').click()")
        self.assertEqual([a.ev(f"{ta}.value"), a.ev(foot), a.ev(pend)], ["", None, ["You", "not sent yet", "Acme: and the backup?"]])
        # edited and saved, it changes; deleted, nothing is pending
        a.ev(f"{card}.querySelector('.rp-pend [aria-label=\"Edit your reply\"]').click()")
        type_("Acme: and the backup site?")
        self.press_enter(a)
        self.assertEqual([a.ev(pend), a.ev(counts)], [["You", "not sent yet", "Acme: and the backup site?"], ["1 pending", "1", "1"]])
        # deleted, nothing is pending: the card leaves the Pending filter
        a.ev(f"{card}.querySelector('.rp-pend [aria-label=\"Delete your reply\"]').click()")
        self.assertEqual([a.ev(f"!!{card}"), a.ev(counts), a.ev(f"'draft' in BP.annotations().find(x => x.id === '{cid}')")], [False, ["", "0", "0"], False])
        self.assertEqual(self.browser.errors, [])

    def test_a_pending_card_s_editor_stays_inside_its_card(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        ids = [a.ev(f"BP.annotate({spec})?.id") for spec in (
            "{type: 'pin', key: 'tldr', note: 'Acme: name the uptime target beside the figure, so the gap reads at once.'}",
            "{type: 'region', key: 'tldr', box: [0.1, 0.1, 0.5, 0.5], note: 'Acme: this box reads crowded on a phone.'}",
            "{type: 'text', key: 'tldr', quote: document.querySelector('.bd-tldr p, .bd-tldr').textContent.trim().split(/\\s+/).slice(0, 4).join(' '), note: 'Acme: shorter, please.'}",
            "{type: 'general', note: 'Acme: a supercalifragilisticexpialidocious_word_that_will_not_wrap_anywhere_at_all.'}")]
        self.assertNotIn(None, ids)
        a.ev("BP.comments({open: true, filter: 'pending'})")
        for w in (280, 320):
            a.ev(f"document.documentElement.style.setProperty('--sp-w', '{w}px')")
            for cid in ids:
                with self.subTest(width=w, card=cid):
                    card = f"document.querySelector('.bd-cs-c[data-id={cid}]')"
                    a.ev(f"{card}.scrollIntoView({{block: 'center', behavior: 'instant'}}); {card}.querySelector('[aria-label=Edit]').click()")
                    a.wait_for(f"{card}.classList.contains('edit') && !!{card}.querySelector('.ed textarea')")
                    # the field, the quote and Attach | hint | Cancel | Save: within the card's right edge; Save shows whole
                    self.assertEqual(a.ev(f"{OVERFLOW}({card})"), [])
                    self.assertTrue(a.ev(f"(b => b.checkVisibility() && b.getBoundingClientRect().right <= {card}.getBoundingClientRect().right)({card}.querySelector('.ef .bp-btn.primary'))"))
                    a.ev(f"{card}.querySelector('.ef .bp-btn.ghost:not(.bp-attach)').click()")
        self.assertEqual(self.browser.errors, [])

    def test_an_agent_reply_highlights_its_card_until_seen(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        cid = a.ev("BP.annotate({type: 'pin', key: 'tldr', note: 'Acme: which team runs the sweep?'}).id")
        self.send_changes(a, "Comments · 1")
        until(lambda: bool(self.state(url).get(f"__ann:{cid}")))
        a.ev("BP.comments({open: false})")
        self.patch(f"ann:{cid}", "--reply", "The platform team.")
        a.go(self.base + url)
        card = f"document.querySelector('.bd-cs-c[data-id={cid}]')"
        a.wait_for(f"!!{card}")
        dots = "[...document.querySelectorAll('.bd-sg [data-f]')].filter(b => b.querySelector('.fdot')).map(b => b.dataset.f)"
        # new since the last visit: the card and the reply highlighted, a dot on Open (the tab holding it); not Pending
        self.assertEqual(a.ev(f"[{card}.classList.contains('fresh'), {card}.querySelector('.bp-msg.agent').classList.contains('fresh'), {dots}]"), [True, True, ["open"]])
        self.assertEqual(a.ev("document.querySelector('[data-f=pending] i').textContent"), "0")
        # the panel closed: unseen still, after a reload too
        until(lambda: '"seen":"1"' in (self.state(url).get(f"__ann:{cid}") or ""))
        a.go(self.base + url)
        a.wait_for(f"!!{card} && {card}.classList.contains('fresh')")
        # a second in view in the panel: seen, for good
        a.ev("BP.comments({open: true, filter: 'open'})")
        a.wait_for(f"!{card}.classList.contains('fresh') && {dots}.length === 0", 6)
        until(lambda: '"seen":"2"' in (self.state(url).get(f"__ann:{cid}") or ""))
        a.go(self.base + url)
        a.wait_for(f"!!{card}")
        self.assertFalse(a.ev(f"{card}.classList.contains('fresh')"))
        self.assertEqual(self.browser.errors, [])

    def press_enter(self, tab: Tab) -> None:
        for kind in ("keyDown", "keyUp"):
            self.browser.call("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, **({"text": "\r"} if kind == "keyDown" else {})}, tab.session)

    def test_the_reply_field_saves_with_enter_into_the_conversation(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        row = "document.querySelector('#item-decisions-retention')"
        box = f"{row}.querySelector(':scope > .ac-reply')"
        state = f"(b => [b.querySelector('.ac-go').disabled, !b.querySelector('.ac-hint')])({box})"
        self.assertEqual(a.ev(state), [True, True], "Save is dimmed while empty; the reply field has no hint")
        a.ev(f"{box}.querySelector('textarea').focus()")
        self.browser.call("Input.insertText", {"text": "Acme: how big is it?"}, a.session)
        self.assertEqual(a.ev(state)[0], False)
        self.press_enter(a)
        self.assertEqual(a.ev(state)[0], True)
        self.assertEqual(a.ev(f"[...{row}.querySelectorAll('.ac-convo .bp-msg')].map(m => [m.classList.contains('unsent'), m.querySelector('.mb').textContent])"),
                         [[True, "Acme: how big is it?"]])
        self.assertEqual(until(lambda: (self.state(url) or {}).get("decisions:retention:note")), "Acme: how big is it?")
        self.assertEqual(a.ev(f"{box}.querySelector('textarea').value"), "", "saved, the field is empty")
        # Esc drops what was typed; the saved reply stays as it was
        self.browser.call("Input.insertText", {"text": "Twice?"}, a.session)
        a.ev(f"{box}.querySelector('textarea').dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Escape', bubbles: true }}))")
        self.assertEqual(a.ev(f"[{box}.querySelector('textarea').value, BP.changesPayload().answers.find(x => x.item === 'retention').note]"), ["", "Acme: how big is it?"])

    def test_a_question_s_detail_is_behind_more_details(self) -> None:
        a = self.open(self.server.url_for(self.plan))
        row = "document.querySelector('#item-decisions-retention')"
        parts = f"[...{row}.children].filter(e => e.checkVisibility()).map(e => e.classList[0])"
        self.assertEqual(a.ev(parts), ["bp-cl-row", "ac-detrow", "bp-opts", "ac-more", "ac-reply"], "an unanswered question opens on load")
        # More details: a row (no keyboard hint); pressed, the details show inside it
        card = f"[...{row}.querySelector('.ac-detrow').children].filter(e => e.checkVisibility()).map(e => e.classList[0])"
        self.assertEqual(a.ev(f"[{row}.querySelector('.ac-detrow .pv-more').textContent, !!{row}.querySelector('.ac-keys'), {card}]"), ["More details", False, ["bp-btn"]])
        a.ev(f"{row}.querySelector('.pv-more').click()")
        self.assertEqual([a.ev(parts), a.ev(card)], [["bp-cl-row", "ac-detrow", "bp-opts", "ac-more", "ac-reply"], ["bp-btn", "bd-dets"]])
        # answered, it folds to its head with ✓ and the pick (All: the list's Open filter would hide an answer picked by script)
        a.ev("BP.findingsFilter('cl-decisions', 'all')")
        a.ev("BP.choose('decisions/retention', 'd180')")
        a.ev(f"{row}.querySelector('.bp-cl-head').click()")
        self.assertEqual([a.ev(parts), a.ev(f"{row}.querySelector('.pv-ok').textContent")], [["bp-cl-row"], "180 days"])


if __name__ == "__main__":
    unittest.main()
