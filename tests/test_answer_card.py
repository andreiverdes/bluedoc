"""The answer card (approved design "One answer card for every question") in a real browser, and `patch --reply --on`.

A comment saved in an answer's field shows in the question's conversation at once, not sent, marked "On <answer>"
while that answer isn't the pick, and the field empties; it goes out with `about` in the JSON and `On **<answer>**:`
in the Markdown, and stays in the thread with its `about` (card/about). On a docs page a question's saved comment is a
change request: it counts on Request changes, not Send answers, which keeps the pick; Save again adds to it, the
message's Edit puts it back in the field (card/save); text typed and never saved counts on Request changes too, and a
send saves it first, so it goes, with Tell me more (card/typed). Tell me more is a pill in the answers' choice group: it clears
the pick and a pick clears it (card/more). Other is labelled Other and stored as `:custom` / `choice: "custom"`
(card/other). Accept recommended skips questions answered with Other or Tell me more (card/accept). The agent's
`--reply --on <option>` is checked against the item's options and shows its chip (card/on)."""
from __future__ import annotations

import json
import unittest

from _support import TempHome, load_json
from test_page_state import CHROME, GO, ChromePage, until

Q = "document.querySelector('#item-decisions-retention')"
# a docs page's tray: Request changes [disabled, its count], then Send answers' count
TRAY = ("[(b => [b.disabled, b.querySelector('.n').textContent])(document.querySelector('.bd-anntb .bd-key.go')),"
        " (b => b._n.hidden ? '0' : b._n.textContent)(document.querySelector('.bd-anntb .bd-key.send'))]")


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class AnswerCard(ChromePage):
    def test_a_comment_in_an_answer_field_shows_on_that_answer_and_carries_about(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        a.ev(f"{Q}.querySelector('.bp-opt[data-id=d90] .oh').click()")   # opened, not picked
        self.assertEqual(a.ev(f"[{Q}.querySelector('.bp-opt[data-id=d90]').className, {Q}.querySelector('.bp-opt[data-id=d90] .ac-hint').hidden]"),
                         ["bp-opt open peek", True], "an answer not picked: no hint under its field")
        field = f"{Q}.querySelector('.bp-opt[data-id=d90] textarea')"
        a.ev(f"(t => {{ t.focus(); t.value = 'Acme: why not 90 days?'; t.dispatchEvent(new InputEvent('input')); "
             f"t.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', bubbles: true }})); }})({field})")
        msgs = f"[...{Q}.querySelectorAll('.ac-convo .bp-msg')].map(m => [m.classList.contains('unsent'), m.querySelector('.ac-on')?.textContent || ''])"
        self.assertEqual(a.ev(msgs), [[True, "On 90 days"]], "Save puts the message in the conversation at once")
        self.assertEqual(a.ev(f"{field}.value"), "", "Save empties the field: the message shows once, in the conversation")
        self.assertIsNone(a.ev("BP.replyPayload().items.find(x => x.item === 'retention').choice"), "a comment on an answer picks nothing")
        p = a.ev("BP.changesPayload()")
        self.assertEqual([x.get("comments") for x in p["answers"] if x["item"] == "retention"], [[{"about": "d90", "md": "Acme: why not 90 days?"}]])
        self.assertIn("  > On **90 days**: Acme: why not 90 days?", p["markdown"])
        # picked, the same comment is about the answer now: unmarked, and the pick's field reads so
        a.ev(f"{Q}.querySelector('.bp-opt[data-id=d90] .pk').click()")
        self.assertEqual(a.ev(msgs), [[True, ""]])
        self.assertEqual(a.ev(f"{Q}.querySelector('.bp-opt[data-id=d90] .ac-hint').textContent"), "Goes with your response.")
        a.ev(f"{Q}.querySelector('.bp-opt[data-id=d180] .pk').click()")
        self.send_changes(a, "Comments · 1")
        thread = until(lambda: json.loads((self.state(url) or {}).get("decisions:retention:thread") or "[]"))
        self.assertEqual([(m["md"], m.get("about")) for m in thread], [("Acme: why not 90 days?", "d90")])
        self.assertEqual(a.ev(f"{field}.value"), "", "sending clears the field")
        self.assertEqual(a.ev(msgs), [[False, "On 90 days"]])

    def docs_page(self) -> tuple:
        """The example plan's questions on a docs page (Request changes and Send answers): (its JSON path, its URL)."""
        doc = load_json(self.plan)
        doc["id"], doc["meta"]["type"], doc["meta"]["kind"] = "acme-carts-proposal", "docs", "Change proposal"
        path = self.docs / "acme-carts-proposal.bluedoc.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        r = self.tmp.run("build.py", path)
        self.assertEqual(r.returncode, 0, r.stderr)
        return path, self.server.url_for(path)

    def test_a_saved_comment_on_a_docs_question_is_a_change_request(self) -> None:
        # a docs page has Request changes and Send answers: a question's comment (and Tell me more) goes with Request
        # changes, its pick with Send answers; Save empties the field and the comment shows once, not sent
        path, url = self.docs_page()
        a = self.open(url)
        reply = f"{Q}.querySelector(':scope > .ac-reply textarea')"
        tray = TRAY
        msgs = f"[...{Q}.querySelectorAll('.ac-convo .bp-msg')].map(m => [m.querySelector('.rv').textContent, m.querySelector('.mb').textContent])"
        save = lambda text: a.ev(f"(t => {{ t.focus(); t.value = {json.dumps(text)}; t.dispatchEvent(new InputEvent('input')); "
                                 f"t.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', bubbles: true }})); }})({reply})")
        self.assertEqual(a.ev(tray), [[True, "0"], "0"])
        save("Acme: how does the mobile app read it?")
        self.assertEqual(a.ev(f"{reply}.value"), "", "Save empties the field")
        self.assertEqual(a.ev(msgs), [["not sent", "Acme: how does the mobile app read it?"]], "the comment shows once, not sent")
        self.assertEqual(a.ev(tray), [[False, "1"], "0"], "a question's comment counts on Request changes, not Send answers")
        save("Acme: and the receipt?")   # Save again adds to it
        self.assertEqual(a.ev("BP.changesPayload().answers.map(x => [x.item, x.note])"),
                         [["retention", "Acme: how does the mobile app read it?\n\nAcme: and the receipt?"]])
        # Edit puts it back in the field (out of the conversation meanwhile); Save replaces it
        a.ev(f"{Q}.querySelector('.bp-msg.unsent [aria-label=\"Edit your comment\"]').click()")
        self.assertEqual(a.ev(f"[{reply}.value, {Q}.querySelectorAll('.bp-msg.unsent').length]"),
                         ["Acme: how does the mobile app read it?\n\nAcme: and the receipt?", 0])
        save("Acme: how does the mobile app read it?")
        self.assertEqual(a.ev(msgs), [["not sent", "Acme: how does the mobile app read it?"]])
        # Tell me more counts once with it; a pick (it clears Tell me more) counts on Send answers
        a.ev(f"{Q}.querySelector('.ac-tmm').click()")
        self.assertEqual(a.ev(tray), [[False, "1"], "0"])
        self.assertEqual(until(lambda: self.state(url).get("decisions:retention:more")), "1", "not sent yet")
        a.ev(f"{Q}.querySelector('.ac-tmm').click()")
        a.ev(f"{Q}.querySelector('.bp-opt[data-id=d90] .pk').click()")
        self.assertEqual(a.ev(tray), [[False, "1"], "1"])
        self.assertNotIn("how does the mobile app", a.ev("JSON.stringify(BP.replyPayload())"), "Send answers carries the pick alone")
        # Request changes sends the comment; the pick stays for Send answers
        self.send_changes(a, "Comments · 1")
        self.assertIn("  > Acme: how does the mobile app read it?", self.reply(path))
        thread = until(lambda: json.loads((self.state(url) or {}).get("decisions:retention:thread") or "[]"))
        self.assertEqual([m["md"] for m in thread], ["Acme: how does the mobile app read it?"])
        self.assertEqual(a.ev(tray), [[True, "0"], "1"])
        self.assertEqual(a.ev(msgs), [["rev 1", "Acme: how does the mobile app read it?"]])
        self.assertEqual(self.browser.errors, [])

    def test_text_typed_but_not_saved_goes_with_the_send(self) -> None:
        # Tell me more, then its question typed in "What do you need to know?" and never saved: Request changes counts
        # it, its dialog shows it, and it goes with Tell me more (card/typed)
        path, url = self.docs_page()
        a = self.open(url)
        type_in = lambda q, text: a.ev(f"(t => {{ t.focus(); t.value = {json.dumps(text)}; t.dispatchEvent(new InputEvent('input')); }})"
                                       f"({q}.querySelector(':scope > .ac-reply textarea'))")
        a.ev(f"{Q}.querySelector('.ac-tmm').click()")
        type_in(Q, "Acme: how does the mobile app read it?")
        prices = "document.querySelector('#item-decisions-prices')"
        type_in(prices, "Acme: which price shows first?")   # no Tell me more: the typed comment alone counts
        self.assertEqual(a.ev(TRAY), [[False, "2"], "0"])
        a.ev(f"{GO}.click()")   # the dialog shows both, then sends them
        a.wait_for("(d => !!d && !d.querySelector('.ft .cp').hidden)(document.querySelector('.bd-chgs[open]'))")
        said = a.ev("[...document.querySelectorAll('.bd-chgs[open] .sd-cm .mb')].map(m => m.textContent)")
        self.assertEqual([s.endswith(t) for s, t in zip(said, ["Acme: how does the mobile app read it?", "Acme: which price shows first?"])], [True, True], said)
        a.ev("document.querySelector('.bd-chgs[open] .ft .pri').click()")
        self.toast(a, "change request sent")
        md = self.reply(path)
        self.assertIn("`item:decisions/retention` → **Tell me more**\n  > Acme: how does the mobile app read it?", md)
        self.assertIn("  > Acme: which price shows first?", md)
        for iid, text in (("retention", "Acme: how does the mobile app read it?"), ("prices", "Acme: which price shows first?")):
            thread = until(lambda: json.loads((self.state(url) or {}).get(f"decisions:{iid}:thread") or "[]"))
            self.assertEqual([m["md"] for m in thread], [text])
        self.assertEqual(a.ev(f"[{Q}.querySelector(':scope > .ac-reply textarea').value, {prices}.querySelector(':scope > .ac-reply textarea').value]"), ["", ""])
        self.assertEqual(a.ev(TRAY), [[True, "0"], "0"])
        self.assertEqual(self.browser.errors, [])

    def test_tell_me_more_is_in_the_choice_group(self) -> None:
        a = self.open(self.server.url_for(self.plan))
        pill = f"{Q}.querySelector('.ac-more .ac-tmm')"
        a.ev(f"{Q}.querySelector('.bp-opt[data-id=d180] .pk').click()")
        a.ev(f"{pill}.click()")
        # Tell me more has no field of its own: the reply field under the conversation asks, and what is written there
        # is about the whole question
        reply = f"{Q}.querySelector(':scope > .ac-reply textarea')"
        self.assertEqual(a.ev(f"[{pill}.getAttribute('aria-checked'), {Q}.querySelector('.ac-more').classList.contains('on'), BP.thread && null, "
                              f"{Q}.querySelector('.bp-opt.on') === null, !!{Q}.querySelector('.ac-more textarea'), {reply}.placeholder, "
                              f"{Q}.querySelector('.bp-cl-head .ac-chip').hidden]"),
                         ["true", True, None, True, False, "What do you need to know? (optional)", False])
        self.assertIn("`item:decisions/retention` → **Tell me more**", a.ev("BP.changesPayload().markdown"))
        a.ev(f"(t => {{ t.focus(); t.value = 'Acme: what would 180 days cost?'; t.dispatchEvent(new InputEvent('input')); "
             f"t.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', bubbles: true }})); }})({reply})")
        msgs = f"[...{Q}.querySelectorAll('.ac-convo .bp-msg')].map(m => [m.classList.contains('unsent'), m.querySelector('.ac-on')?.textContent || ''])"
        self.assertEqual(a.ev(msgs), [[True, ""]], "no On Tell me more: it is about the whole question")
        self.assertNotIn("On **Tell me more**", a.ev("BP.changesPayload().markdown"))
        a.ev(f"{Q}.querySelector('.bp-opt[data-id=d90] .pk').click()")   # an answer clears it
        self.assertEqual(a.ev(f"[{pill}.getAttribute('aria-checked'), {Q}.querySelector('.bp-opt.on').dataset.id, {reply}.placeholder]"), ["false", "d90", "Reply…"])
        # several answers: a checkbox that clears the ticks and Other
        g = "document.querySelector('#item-decisions-guests')"
        a.ev(f"{g}.querySelector('.bp-opt[data-id=accounts] .pk').click(); BP.custom('decisions/guests', 'Support, for business buyers')")
        self.assertEqual(a.ev("BP.replyPayload().items.find(x => x.item === 'guests').choice"), ["accounts", "custom"], "Other is one more tick")
        a.ev(f"{g}.querySelector('.ac-tmm').click()")
        self.assertEqual(a.ev(f"[{g}.querySelector('.ac-tmm').getAttribute('role'), {g}.querySelectorAll('.bp-opt.on').length, BP.replyPayload().items.find(x => x.item === 'guests').choice]"),
                         ["checkbox", 0, []])

    def test_other_is_labelled_other_and_stored_as_custom(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        row = f"{Q}.querySelector('.bp-opt.cust')"
        self.assertEqual(a.ev(f"[{row}.querySelector('.ol').textContent, {row}.dataset.id, {Q}.querySelector('.bp-opts .bp-opt:last-child') === {row}]"),
                         ["Other", "custom", True])
        a.ev(f"(t => {{ t.focus(); t.value = '365 days for business accounts'; t.dispatchEvent(new InputEvent('input')); t.blur(); }})({row}.querySelector('textarea'))")
        self.assertEqual(a.ev(f"[{row}.querySelector('.pk').getAttribute('aria-checked'), {Q}.querySelector('.pv-ok').textContent]"), ["true", "Other"])
        self.assertEqual(until(lambda: (self.state(url) or {}).get("decisions:retention:custom")), "365 days for business accounts")
        item = a.ev("BP.changesPayload().answers.find(x => x.item === 'retention')")
        self.assertEqual([item["choice"], item["custom"]], ["custom", "365 days for business accounts"])
        self.assertIn("→ **Other**: 365 days for business accounts", a.ev("BP.changesPayload().markdown"))

    def test_accept_recommended_skips_other_and_tell_me_more(self) -> None:
        a = self.open(self.server.url_for(self.plan))
        a.ev("BP.custom('decisions/retention', 'Acme: a year'); BP.moreDetails('decisions/prices')")
        self.assertEqual(a.ev("BP.acceptRecommended('decisions')"), 1)
        picks = {x["item"]: x["choice"] for x in a.ev("BP.replyPayload().items") if x["checklist"] == "decisions"}
        self.assertEqual(picks, {"retention": "custom", "prices": None, "guests": ["accounts", "business"]})

    def test_an_agent_reply_on_an_answer_shows_its_chip(self) -> None:
        r = self.tmp.run("build.py", "patch", self.plan, "item:decisions/retention", "--reply", "90 days loses a third of reorders.", "--on", "d90")
        self.assertEqual(r.returncode, 0, r.stderr)
        a = self.open(self.server.url_for(self.plan))
        self.assertEqual(a.ev("BP.thread('decisions/retention').map(m => m.about || null)"), ["d90"])
        self.assertEqual(a.ev(f"[...{Q}.querySelectorAll('.ac-convo .bp-msg.agent .ac-on')].map(c => c.textContent)"), ["On 90 days"])

    def test_other_on_a_brief_framework_asks_for_more_until_picked(self) -> None:
        a = self.open(self.server.url_for(self.docs / "acme-fit-design.bluedoc.json"))
        li = "document.querySelector('#item-brief-framework')"
        head = f"[{li}.classList.contains('more'), {li}.classList.contains('done'), {li}.querySelector('.bp-cl-head .ac-chip').hidden, {li}.querySelector('.bp-cl-head .ac-chip').textContent, document.querySelector('.bd-key.approve').disabled]"
        self.assertTrue(a.ev("BP.custom('brief/framework', 'Svelte with our own tokens')"))
        self.assertEqual(a.ev(head), [True, False, False, "Asking for more", True], "a request is amber, not ✓, and holds Approve")
        self.assertIn("→ **Other**: Svelte with our own tokens (a request:", a.ev("BP.changesPayload().markdown"))
        self.send_changes(a, "Picks · 3")
        self.assertEqual(a.ev("document.querySelector('.bd-chgs .sd-dec[data-item=\"brief/framework\"] .sd-chip').className"), "sd-chip ask", "a request shows amber")
        self.assertEqual(a.ev(head)[3], "Asked · rev " + a.ev("BP.planState().rev"))
        a.ev("BP.choose('brief/framework', 'horizon')")   # picking the option it becomes takes the request back
        h = a.ev(head)
        self.assertEqual(h[:3] + h[4:], [False, True, True, False])

    def test_open_in_the_query_opens_questions_answers_and_details(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        a.go(f"{self.base}{url}?open=decisions:retention:d180,decisions:prices:details,decisions:nosuch,nosuch")
        q = lambda iid: f"document.querySelector('#item-decisions-{iid}')"
        a.wait_for(f"{q('prices')}.querySelector('.pv-more').getAttribute('aria-expanded') === 'true'")
        self.assertEqual(a.ev(f"[{q('retention')}.classList.contains('open'), [...{q('retention')}.querySelectorAll('.bp-opt.open')].map(r => r.dataset.id), "
                              f"{q('retention')}.querySelector('.pv-more').getAttribute('aria-expanded'), {q('prices')}.classList.contains('open'), "
                              f"{q('prices')}.querySelectorAll('.bp-opt.open').length, !{q('prices')}.querySelector('.bd-dets').hidden]"),
                         [True, ["d180"], "false", True, 0, True])
        self.assertEqual(self.browser.errors, [])


class PatchOn(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.plan = self.tmp.copy_examples() / "acme-saved-carts-plan.bluedoc.json"

    def patch(self, *args: str):
        return self.tmp.run("build.py", "patch", self.plan, *args)

    def test_on_names_one_of_the_items_answers(self) -> None:
        r = self.patch("item:decisions/retention", "--reply", "Acme: 90 days loses reorders.", "--on", "d90")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.patch("item:decisions/retention", "--reply", "Acme: noted.", "--on", "custom", "--no-bump")
        self.assertEqual(r.returncode, 0, r.stderr)
        items = {it["id"]: it for s in load_json(self.plan)["sections"] for b in s.get("blocks", []) if b.get("id") == "decisions" for it in b["items"]}
        self.assertEqual([(x["md"], x.get("about")) for x in items["retention"]["replies"]], [("Acme: 90 days loses reorders.", "d90"), ("Acme: noted.", "custom")])

    def test_an_unknown_answer_or_a_progress_item_is_refused(self) -> None:
        before = self.plan.read_text(encoding="utf-8")
        r = self.patch("item:decisions/retention", "--reply", "x", "--on", "d30")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--on d30: not an answer of item:decisions/retention; one of d90, d180, forever, or custom", r.stderr)
        r = self.patch("item:checks/unit", "--reply", "x", "--on", "d90")
        self.assertEqual(r.returncode, 2)
        self.assertIn("is not a question", r.stderr)
        r = self.patch("item:decisions/retention", "--on", "d90")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--on goes with --reply", r.stderr)
        self.assertEqual(self.plan.read_text(encoding="utf-8"), before)

    def test_help_documents_on(self) -> None:
        r = self.tmp.run("build.py", "patch", "--help")
        self.assertIn("--on ID", r.stdout)
        self.assertIn("about", r.stdout)


if __name__ == "__main__":
    unittest.main()
