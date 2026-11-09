"""The keys that end the bottom tray, and a review's meta.review.

The build: meta.review is post, threads or local, on a review doc only (an ERROR otherwise; 1.0.19's theirs and mine
name their new words); a review of a PR needs one, and a post review's findings offer only Post and Don't post (the
type's contract); `build.py new review --of` writes it, --of post with Post / Don't post options, and the doc card
lists it. The server: an approval for a presentation or storelisting is refused (400); an
answers reply's reviewEvents give each PR COMMENT, REQUEST_CHANGES or APPROVE (else 400) and `reply`/`wait` print them in the
header. The browser tests (BLUEDOC_BROWSER_TESTS=1): each page type's dock ends as types/review.md and schema.md's
tray table say (Approve on a plan, design and website; Present on a deck, whose toolbar's last key is a blue Export
to…; nothing on a listing; the send key named by meta.review; Send answers elsewhere with a checklist; Request changes
alone without one); the send key counts what hasn't gone; a `post` review's dialog posts each PR as the reader picked."""
from __future__ import annotations

import json
import shutil
import unittest

from _support import EXAMPLES, TempHome, load_json
from test_page_state import CHROME, ChromePage

import build

REVIEW = "acme-review-findings"
JSON = {"Content-Type": "application/json", "X-Bluedoc": "1"}
# the dock after Request changes: [class, label] of each key
END = """[...document.querySelector('.bd-anntb .bd-key.go').parentElement.children]
  .slice([...document.querySelector('.bd-anntb .bd-key.go').parentElement.children].indexOf(document.querySelector('.bd-anntb .bd-key.go')) + 1)
  .map(k => [k.className.replace('bd-key txt ', ''), k.querySelector('.t').textContent])"""


def review_of(docs, kind: str):
    """A copy of the example review with meta.review set, under its own id; a `post` copy's findings offer only Post
    and Don't post, as the contract asks."""
    d = load_json(docs / f"{REVIEW}.bluedoc.json")
    d["id"], d["meta"] = f"acme-review-{kind}", {**d["meta"], "review": kind}
    if kind == "post":
        for b in build.all_blocks(d):
            for it in b.get("items") or [] if b.get("type") == "checklist" else []:
                if it.get("choices"):
                    it["recommend"], it["choices"] = "post", [{"id": "post", "label": "Post", "md": "Posted on its line."},
                                                              {"id": "skip", "label": "Don't post", "md": "Not posted."}]
    path = docs / f"acme-review-{kind}.bluedoc.json"
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    shutil.copy(docs / f"{REVIEW}.diffcache.json", docs / f"acme-review-{kind}.diffcache.json")
    return path


class MetaReview(unittest.TestCase):
    def errors(self, doc: dict) -> list[str]:
        return [e for e in build.validate(doc, None, write_cache=False).errors if "meta.review" in e]

    def test_review_takes_post_threads_or_local_and_nothing_else(self) -> None:
        doc = load_json(EXAMPLES / f"{REVIEW}.bluedoc.json")
        for kind in build.REVIEW_OF:
            self.assertEqual(self.errors({**doc, "meta": {**doc["meta"], "review": kind}}), [], kind)
        self.assertIn("not in ['local', 'threads', 'post']", self.errors({**doc, "meta": {**doc["meta"], "review": "ours"}})[0])
        self.assertIn("'theirs' is now 'post'", self.errors({**doc, "meta": {**doc["meta"], "review": "theirs"}})[0])
        plan = load_json(EXAMPLES / "acme-saved-carts-plan.bluedoc.json")
        self.assertIn("only a review doc has it", self.errors({**plan, "meta": {**plan["meta"], "review": "local"}})[0])

    def test_new_review_of_writes_it_and_the_cards_list_it(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        out = tmp.dir / "r.bluedoc.json"
        r = tmp.run("build.py", "new", "review", out, "--of", "post")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = load_json(out)
        self.assertEqual(doc["meta"]["review"], "post")
        items = [it for b in build.all_blocks(doc) if b.get("type") == "checklist" for it in b.get("items") or [] if it.get("choices")]
        self.assertTrue(items)
        self.assertEqual({tuple(c["id"] for c in it["choices"]) for it in items}, {("post", "skip")})
        self.assertNotIn("Send answers", json.dumps(doc), "the scaffold names Post review, not Send answers")
        r = tmp.run("build.py", "new", "review", tmp.dir / "s.bluedoc.json")
        self.assertNotIn("review", load_json(tmp.dir / "s.bluedoc.json")["meta"])
        r = tmp.run("build.py", "new", "plan", tmp.dir / "p.bluedoc.json", "--of", "local")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--of is for review docs", r.stderr)
        self.assertIn("meta.review  str  opt  local|threads|post", build.schema_card("doc"))
        self.assertIn("meta.review local|threads|post", build.schema_card("review"))


class WhosePR(unittest.TestCase):
    """The contract: a review of a PR says whose it is, and someone else's PR gets only Post and Don't post."""
    def test_a_pr_review_needs_meta_review(self) -> None:
        doc = load_json(EXAMPLES / f"{REVIEW}.bluedoc.json")
        self.assertEqual(build.check_contract(doc), [])
        meta = {k: v for k, v in doc["meta"].items() if k != "review"}
        self.assertTrue(any("a review of a PR needs meta.review" in g for g in build.check_contract({**doc, "meta": meta})))

    def test_a_post_review_offers_only_post_and_skip(self) -> None:
        doc = load_json(EXAMPLES / f"{REVIEW}.bluedoc.json")
        gaps = build.check_contract({**doc, "meta": {**doc["meta"], "review": "post"}})
        self.assertTrue(gaps and all("a post review's findings are only posted or not" in g for g in gaps), gaps)
        self.assertIn("offers fix, ticket, decline", gaps[0])


class Server(unittest.TestCase):
    def setUp(self) -> None:
        from _support import Server as Srv
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples("w/docs")
        self.assertEqual(self.tmp.run("serve.py", "add", self.docs).returncode, 0)
        self.server = Srv(self.tmp)
        self.server.start()
        self.addCleanup(self.server.stop)

    def post(self, route: str, body: dict) -> tuple[int, bytes]:
        return self.server.req("POST", route, json.dumps(body).encode(), JSON)

    def test_a_deck_or_listing_approval_is_refused(self) -> None:
        for stem, says in (("acme-fit-deck", b"a presentation isn't approved"), ("acme-fit-listing", b"a storelisting isn't approved")):
            path = self.docs / f"{stem}.bluedoc.json"
            doc = load_json(path)
            body = {"decision": "approved", "path": self.server.url_for(path), "docHash": build.approval_hash(doc, path),
                    "rev": doc["meta"]["rev"], "answers": [], "annotations": [], "markdown": "ok"}
            status, raw = self.post("/__bluedoc/approve", body)
            self.assertEqual(status, 400, raw)
            self.assertIn(says, raw)

    def test_review_event_is_checked_and_printed(self) -> None:
        path = review_of(self.docs, "post")
        body = {"path": self.server.url_for(path), "rev": "1", "items": [], "markdown": "# R\n\nPost as:\n- #412: Request changes\n- #415: Approve\n"}
        evs = [{"section": "pr-412", "title": "#412", "event": "REQUEST_CHANGES"}, {"section": "pr-415", "title": "#415", "event": "APPROVE"}]
        for bad in ([{**evs[0], "event": "MERGE"}], [{**evs[0], "section": "412"}], [], "APPROVE"):
            self.assertEqual(self.post("/__bluedoc/reply", {**body, "reviewEvents": bad})[0], 400, bad)
        self.assertEqual(self.post("/__bluedoc/changes", {**body, "annotations": [], "reviewEvents": evs})[0], 400)
        status, raw = self.post("/__bluedoc/reply", {**body, "reviewEvents": evs})
        self.assertEqual(status, 200, raw)
        r = self.tmp.run("serve.py", "wait", path, "--timeout", "5")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout.splitlines()[0], r"^--- bluedoc answers \(reply \d+, rev 1, .*, review events pr-412 REQUEST_CHANGES, pr-415 APPROVE\) ---$")
        self.assertIn("- #415: Approve", r.stdout)


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class Dock(ChromePage):
    def test_each_page_type_ends_its_dock_with_its_key(self) -> None:
        for kind in ("local", "threads", "post"):
            review_of(self.docs, kind)
        (self.docs / "acme-note.bluedoc.json").write_text(json.dumps(
            {"id": "acme-note", "title": "Acme note", "meta": {"type": "other"},
             "sections": [{"id": "s", "title": "Note", "blocks": [{"type": "text", "md": "No checklist here."}]}]}), encoding="utf-8")
        want = {"acme-saved-carts-plan": [["approve", "Approve"]], "acme-fit-design": [["approve", "Approve"]],
                "acme-site": [["approve", "Approve"]], "acme-fit-deck": [["present", "Present"]], "acme-fit-listing": [],
                "acme-review-local": [["send", "Apply decisions"]], "acme-review-post": [["send", "Post review"]],
                "acme-review-threads": [["send", "Reply and fix"]], REVIEW: [["send", "Reply and fix"]],
                "acme-orders": [["send", "Send answers"]], "acme-note": []}
        for stem, keys in want.items():
            t = self.open(self.server.url_for(self.docs / f"{stem}.bluedoc.json"))
            t.wait_for("!!document.querySelector('.bd-anntb .bd-key.go')")
            self.assertEqual(t.ev(END), keys, stem)
            self.assertEqual(t.ev("document.querySelectorAll('.bd-anntb .bd-key.acc').length"), 0, stem)
        self.assertEqual(self.browser.errors, [])

    def test_the_deck_presents_from_its_dock_and_exports_from_its_toolbar(self) -> None:
        t = self.open(self.server.url_for(self.docs / "acme-fit-deck.bluedoc.json"))
        t.wait_for("!!document.querySelector('.bd-btb .bd-expb')")
        self.assertEqual(t.ev("(b => [b.matches('.pri'), !b.parentElement.nextElementSibling])(document.querySelector('.bd-btb .bd-expb'))"), [True, True])
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-btb button')].filter(b => /^Present/.test(b.textContent + (b.title || ''))).length"), 0)
        self.assertIsNone(t.ev("document.querySelector('.bd-planchip:not(.arc)')"))
        t.ev("BP.board({focus: 'title'})")
        t.ev("document.querySelector('.bd-anntb .bd-key.present').click()")
        t.wait_for("BP.board().present")

    def test_the_send_key_counts_and_a_post_review_posts_as_picked(self) -> None:
        path = review_of(self.docs, "post")
        t = self.open(self.server.url_for(path))
        key = "document.querySelector('.bd-anntb .bd-key.send')"
        t.wait_for(f"!!{key}")
        self.assertEqual(t.ev(f"[{key}.classList.contains('has'), {key}.querySelector('.n').hidden]"), [False, True])
        n = t.ev("BP.acceptRecommended('t412')")
        self.assertGreater(n, 0)
        t.ev("BP.setNote('t412/float-cents', 'Fine as a ticket.')")
        self.assertEqual(t.ev(f"[{key}.classList.contains('has'), {key}.querySelector('.n').textContent]"), [True, str(n)])
        t.ev(f"{key}.click()")
        t.wait_for("!!document.querySelector('.bd-send[open] .bd-postas')")
        self.assertEqual(t.ev("document.querySelector('.bd-send[open] h3').textContent"), "Post reviews to the PRs")
        # one Post as per PR, each starting at Comment: request changes on #412, approve #415
        self.assertEqual(t.ev("[...document.querySelectorAll('.bd-send[open] .bd-postas [aria-checked=true]')].map(b => b.dataset.v)"), ["COMMENT", "COMMENT"])
        t.ev("document.querySelector('.bd-send[open] .bd-postas [data-pr=pr-412] [data-v=REQUEST_CHANGES]').click()")
        t.ev("document.querySelector('.bd-send[open] .bd-postas [data-pr=pr-415] [data-v=APPROVE]').click()")
        pre = t.ev("document.querySelector('.bd-send[open] pre').textContent")
        self.assertIn("Post as:\n- #412 · bulk discount tiers: Request changes\n- #415 · retry PayCo authorization: Approve", pre)
        self.assertEqual(t.ev("BP.replyPayload().reviewEvents.map(e => [e.section, e.event])"), [["pr-412", "REQUEST_CHANGES"], ["pr-415", "APPROVE"]])
        t.wait_for("!document.querySelector('.bd-send[open] .ft .primary').hidden")
        t.ev("document.querySelector('.bd-send[open] .ft .bp-btn.primary').click()")
        self.toast(t, "sent to")
        r = self.tmp.run("serve.py", "reply", path, "--kind", "answers")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("review events pr-412 REQUEST_CHANGES, pr-415 APPROVE) ---", r.stdout.splitlines()[0])
        self.assertIn("- #412 · bulk discount tiers: Request changes", r.stdout)
        self.assertEqual([e["event"] for e in json.loads(self.tmp.run("serve.py", "reply", path, "--kind", "answers", "--json").stdout)["reviewEvents"]],
                         ["REQUEST_CHANGES", "APPROVE"])
        # sent: nothing left to count, also after a reload
        t.wait_for(f"!{key}.classList.contains('has') && {key}.querySelector('.n').hidden")
        t = self.open(self.server.url_for(path))
        t.wait_for(f"!!{key}")
        self.assertFalse(t.ev(f"{key}.classList.contains('has')"))
        self.assertEqual(self.browser.errors, [])


if __name__ == "__main__":
    unittest.main()
