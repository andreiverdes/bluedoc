"""The answer card (approved design "One answer card for every question") in a real browser, and `patch --reply --on`.

A comment saved in an answer's field shows in the question's conversation at once, not sent, marked "On <answer>"
while that answer isn't the pick; it goes out with `about` in the JSON and `On **<answer>**:` in the Markdown, and
stays in the thread with its `about` (card/about). Tell me more is a pill in the answers' choice group: it clears
the pick and a pick clears it (card/more). Other is labelled Other and stored as `:custom` / `choice: "custom"`
(card/other). Accept recommended skips questions answered with Other or Tell me more (card/accept). The agent's
`--reply --on <option>` is checked against the item's options and shows its chip (card/on)."""
from __future__ import annotations

import json
import unittest

from _support import TempHome, load_json
from test_page_state import CHROME, GO, ChromePage, until

Q = "document.querySelector('#item-decisions-retention')"


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class AnswerCard(ChromePage):
    def test_a_comment_in_an_answer_field_shows_on_that_answer_and_carries_about(self) -> None:
        url = self.server.url_for(self.plan)
        a = self.open(url)
        a.ev(f"{Q}.querySelector('.bp-opt[data-id=d90] .oh').click()")   # opened, not picked
        self.assertEqual(a.ev(f"[{Q}.querySelector('.bp-opt[data-id=d90]').className, {Q}.querySelector('.bp-opt[data-id=d90] .ac-hint').textContent]"),
                         ["bp-opt open peek", "Shows in the conversation as On 90 days; it picks nothing."])
        field = f"{Q}.querySelector('.bp-opt[data-id=d90] textarea')"
        a.ev(f"(t => {{ t.focus(); t.value = 'Acme: why not 90 days?'; t.dispatchEvent(new InputEvent('input')); "
             f"t.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', bubbles: true }})); }})({field})")
        msgs = f"[...{Q}.querySelectorAll('.ac-convo .bp-msg')].map(m => [m.classList.contains('unsent'), m.querySelector('.ac-on')?.textContent || ''])"
        self.assertEqual(a.ev(msgs), [[True, "On 90 days"]], "Save puts the message in the conversation at once")
        self.assertEqual(a.ev(f"{field}.value"), "Acme: why not 90 days?", "it stays in its field until sent")
        self.assertIsNone(a.ev("BP.replyPayload().items.find(x => x.item === 'retention').choice"), "a comment on an answer picks nothing")
        p = a.ev("BP.changesPayload()")
        self.assertEqual([x.get("comments") for x in p["answers"] if x["item"] == "retention"], [[{"about": "d90", "md": "Acme: why not 90 days?"}]])
        self.assertIn("  > On **90 days**: Acme: why not 90 days?", p["markdown"])
        # picked, the same comment is about the answer now: unmarked, and the pick's field reads so
        a.ev(f"{Q}.querySelector('.bp-opt[data-id=d90] .pk').click()")
        self.assertEqual(a.ev(msgs), [[True, ""]])
        self.assertEqual(a.ev(f"{Q}.querySelector('.bp-opt[data-id=d90] .ac-hint').textContent"), "Goes with your response.")
        a.ev(f"{Q}.querySelector('.bp-opt[data-id=d180] .pk').click()")
        self.send_changes(a, "1 comment on items")
        thread = until(lambda: json.loads((self.state(url) or {}).get("decisions:retention:thread") or "[]"))
        self.assertEqual([(m["md"], m.get("about")) for m in thread], [("Acme: why not 90 days?", "d90")])
        self.assertEqual(a.ev(f"{field}.value"), "", "sending clears the field")
        self.assertEqual(a.ev(msgs), [[False, "On 90 days"]])

    def test_tell_me_more_is_in_the_choice_group(self) -> None:
        a = self.open(self.server.url_for(self.plan))
        pill = f"{Q}.querySelector('.ac-more .ac-tmm')"
        a.ev(f"{Q}.querySelector('.bp-opt[data-id=d180] .pk').click()")
        a.ev(f"{pill}.click()")
        self.assertEqual(a.ev(f"[{pill}.getAttribute('aria-checked'), {Q}.querySelector('.ac-more').classList.contains('on'), BP.thread && null, "
                              f"{Q}.querySelector('.bp-opt.on') === null, {Q}.querySelector('.ac-more textarea').placeholder, "
                              f"{Q}.querySelector('.bp-cl-head .ac-chip').hidden]"),
                         ["true", True, None, True, "What do you need to know?", False])
        self.assertIn("`item:decisions/retention` → **Tell me more**", a.ev("BP.changesPayload().markdown"))
        a.ev(f"{Q}.querySelector('.bp-opt[data-id=d90] .pk').click()")   # an answer clears it
        self.assertEqual(a.ev(f"[{pill}.getAttribute('aria-checked'), {Q}.querySelector('.bp-opt.on').dataset.id]"), ["false", "d90"])
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
        self.send_changes(a, "question asking for more")
        self.assertEqual(a.ev(head)[3], "Asked · rev " + a.ev("BP.planState().rev"))
        a.ev("BP.choose('brief/framework', 'horizon')")   # picking the option it becomes takes the request back
        h = a.ev(head)
        self.assertEqual(h[:3] + h[4:], [False, True, True, False])


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
