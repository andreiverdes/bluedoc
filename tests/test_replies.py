"""Conversations on items and comments, several answers, and option explanations, on the data side.

The agent answers a reader with `build.py patch <doc> item:<cl>/<item> --reply` (the item's `replies`) or
`ann:<id> --reply` (the doc's `threads`), each entry stamped with the rev the patch writes; replying is progress, so an
approval carries over it. A decision with `multi: true` takes a list of ids as `choice` / `recommend`. A doc created
from this release on (its history file says `created`, or it has none yet) needs an `md` explanation on every option; an
older doc builds as before. serve.py's value_ok holds the reader's side: `:thread` lists, multi picks, an annotation's
`thread` and `draft`."""
from __future__ import annotations

import json
import unittest

from _support import EXAMPLES, TempHome, load_json

import build
import serve

PLAN = "acme-saved-carts-plan.bluedoc.json"
REVIEW = "acme-review-findings.bluedoc.json"


def write_json(path, doc) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def item(doc: dict, cl: str, iid: str) -> dict:
    return build._item(doc, cl, iid).obj


class ReplyPatch(unittest.TestCase):
    """`--reply` appends {rev, md}: the bumped rev, or the current one with --no-bump; with --resolves too."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.plan = self.tmp.copy_examples() / PLAN

    def patch(self, *args: str):
        return self.tmp.run("build.py", "patch", self.plan, *args)

    def test_item_reply_bumps_stamps_and_keeps_the_previous_rev(self) -> None:
        r = self.patch("item:decisions/retention", "--reply", "180 days covers **70 %** of reorders.", "--resolves", "c1abc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("rev 1 → 2; item:decisions/retention replied", r.stdout)
        doc = load_json(self.plan)
        self.assertEqual(doc["meta"]["rev"], "2")
        self.assertEqual(item(doc, "decisions", "retention")["replies"], [{"rev": "2", "md": "180 days covers **70 %** of reorders."}])
        self.assertEqual(doc["resolves"], ["c1abc"])
        self.assertEqual(doc["changes"], ["Replied on `item:decisions/retention`."])
        h = build.load_history(build.history_path(self.plan))
        self.assertEqual([e["rev"] for e in h["revs"]], ["1", "2"])
        self.assertNotIn("replies", item(build.restore(h, h["revs"][0]), "decisions", "retention"))

        r = self.patch("item:decisions/retention", "--reply", "Row size checked on staging.", "--no-bump", "--resolves", "c2def")
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = load_json(self.plan)
        self.assertEqual(doc["meta"]["rev"], "2")
        self.assertEqual([x["rev"] for x in item(doc, "decisions", "retention")["replies"]], ["2", "2"])
        self.assertEqual(doc["resolves"], ["c1abc", "c2def"])
        self.assertEqual(self.tmp.run("build.py", self.plan, "--check").returncode, 0)

    def test_ann_reply_appends_to_the_comment_thread(self) -> None:
        for n, md in enumerate(("Moved the badge under the total.", "Fixed in the panel too.")):
            r = self.patch("ann:c1x2y3", "--reply", md)
            self.assertEqual(r.returncode, 0, r.stderr)
        doc = load_json(self.plan)
        self.assertEqual(doc["threads"], {"c1x2y3": [{"rev": "2", "md": "Moved the badge under the total."},
                                                     {"rev": "3", "md": "Fixed in the panel too."}]})

    def test_refused_without_writing(self) -> None:
        raw = self.plan.read_text(encoding="utf-8")
        for args, why in ((("ann:c1x2y3",), "ann: without --reply"),
                          (("ann:c1x2y3", "--reply", "x", "--set", "a=1"), "ann: with --set"),
                          (("ann:bad id", "--reply", "x"), "an id that isn't a comment id"),
                          (("tldr", "--reply", "x"), "--reply on a key that isn't item: or ann:"),
                          (("item:decisions/retention", "--reply", "x", "--delete"), "--reply with --delete"),
                          (("item:decisions/retention", "--reply", ""), "an empty reply"),
                          (("item:decisions/retention", "--reply", "x" * (build.MAX_REPLY_MD + 1)), "a reply over the limit")):
            with self.subTest(why):
                self.assertNotEqual(self.patch(*args).returncode, 0)
                self.assertEqual(self.plan.read_text(encoding="utf-8"), raw)


class ReplyShape(unittest.TestCase):
    """The build checks `replies` and `threads`, and warns about a reply whose rev the history lacks."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.path = self.tmp.copy_examples() / PLAN
        self.doc = load_json(self.path)

    def report(self, replies=None, threads=None) -> build.Report:
        d = json.loads(json.dumps(self.doc))
        if replies is not None:
            item(d, "decisions", "retention")["replies"] = replies
        if threads is not None:
            d["threads"] = threads
        return build.validate(d, self.path)

    def test_good_replies_and_threads_are_clean(self) -> None:
        rep = self.report([{"rev": "1", "md": "Checked on staging."}], {"c1abc": [{"rev": "1", "md": "Done."}]})
        self.assertEqual((rep.errors, rep.warnings), ([], []))

    def test_a_rev_the_history_lacks_warns(self) -> None:
        rep = self.report([{"rev": "9", "md": "Checked."}], {"c1abc": [{"rev": "8", "md": "Done."}]})
        self.assertEqual(rep.errors, [])
        self.assertEqual(len([w for w in rep.warnings if "not in the doc's history" in w]), 2, rep.warnings)

    def test_bad_shapes_are_errors(self) -> None:
        for name, replies, threads in (
                ("not a list", {"rev": "1", "md": "x"}, None),
                ("an empty list", [], None),
                ("no md", [{"rev": "1"}], None),
                ("blank md", [{"rev": "1", "md": "  "}], None),
                ("md over the limit", [{"rev": "1", "md": "x" * (build.MAX_REPLY_MD + 1)}], None),
                ("no rev", [{"md": "x"}], None),
                ("a field of its own", [{"rev": "1", "md": "x", "at": "now"}], None),
                ("threads not an object", None, [{"rev": "1", "md": "x"}]),
                ("a thread key that isn't a comment id", None, {"c 1": [{"rev": "1", "md": "x"}]}),
                ("an empty thread", None, {"c1abc": []})):
            with self.subTest(name):
                self.assertTrue(self.report(replies, threads).errors)


class SeveralAnswers(unittest.TestCase):
    """`multi: true` lets `choice` and `recommend` be lists of option ids; without it they stay one id."""

    def setUp(self) -> None:
        self.doc = load_json(EXAMPLES / PLAN)

    def errors(self, **fields) -> list[str]:
        d = json.loads(json.dumps(self.doc))
        it = item(d, "decisions", "guests")
        for k, v in fields.items():
            if v is None:
                it.pop(k, None)
            else:
                it[k] = v
        return build.validate(d, EXAMPLES / PLAN).errors

    def test_lists_need_multi_and_known_distinct_ids(self) -> None:
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.errors(choice=["support", "email"]), [])
        self.assertEqual(self.errors(choice="email"), [], "one id is fine with multi too")
        for name, fields in (("a list without multi", {"multi": None}),
                             ("an unknown id", {"choice": ["accounts", "staff"]}),
                             ("a repeated id", {"choice": ["email", "email"]}),
                             ("an empty list", {"choice": []}),
                             ("multi not true/false", {"multi": "yes"}),
                             ("a number for choice", {"choice": 3})):
            with self.subTest(name):
                self.assertTrue(self.errors(**fields))

    def test_multi_needs_choices(self) -> None:
        d = json.loads(json.dumps(self.doc))
        item(d, "checks", "unit")["multi"] = True
        self.assertTrue(any("'multi' need 'choices'" in e for e in build.validate(d, EXAMPLES / PLAN).errors))

    def test_a_brief_pick_the_screens_use_takes_one_answer(self) -> None:
        design = EXAMPLES / "acme-fit-design.bluedoc.json"
        d = load_json(design)
        item(d, "brief", "theme")["multi"] = True
        self.assertTrue(any("drop `multi`" in e for e in build.validate(d, design).errors))

    def test_the_index_and_the_approval_read_the_ids(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        path = tmp.copy_examples() / PLAN
        d = load_json(path)
        item(d, "decisions", "guests")["choice"] = ["accounts", "support"]
        write_json(path, d)
        row = next(x for x in serve.summarize(path)["items"] if x[:2] == ["decisions", "guests"])
        self.assertEqual(row[3:], ["accounts,support", ["accounts", "business", "support", "email"]])
        picks = serve.approved_picks({"answers": [{"checklist": "decisions", "item": "guests", "choice": ["email", "accounts"]},
                                                  {"checklist": "decisions", "item": "retention", "choice": None, "recommend": "d180"}]})
        self.assertEqual(picks, {"decisions/guests": ["email", "accounts"], "decisions/retention": "d180"})


class ApprovalCarriesOverReplies(unittest.TestCase):
    """An approval of rev 1 holds for a rev whose only changes are replies (and the usual progress)."""

    def test_reply_only_rev(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        path = tmp.copy_examples() / PLAN
        approved = build.approval_hash(load_json(path), path)
        for args in (("item:decisions/retention", "--reply", "Yes: 180 days."), ("ann:c1abc", "--reply", "Moved it.")):
            r = tmp.run("build.py", "patch", path, *args)
            self.assertEqual(r.returncode, 0, r.stderr)
        doc, h = load_json(path), build.load_history(build.history_path(path))
        self.assertEqual(doc["meta"]["rev"], "3")
        self.assertTrue(build.approval_carries(h, "1", approved, doc, path, {}))
        item(doc, "decisions", "retention")["text"] = "Acme: another question"
        self.assertFalse(build.approval_carries(h, "1", approved, doc, path, {}), "a reply that also changes the item")

    def test_a_multi_pick_carries_in_any_order(self) -> None:
        tmp = TempHome()
        self.addCleanup(tmp.cleanup)
        path = tmp.copy_examples() / PLAN
        approved = build.approval_hash(load_json(path), path)
        h = build.load_history(build.history_path(path))
        doc = load_json(path)
        item(doc, "decisions", "guests")["choice"] = ["business", "accounts"]
        doc["meta"]["rev"] = "2"
        self.assertTrue(build.approval_carries(h, "1", approved, doc, path, {"decisions:guests": ["accounts", "business"]}))
        self.assertFalse(build.approval_carries(h, "1", approved, doc, path, {"decisions:guests": ["accounts"]}))


class ExplanationRule(unittest.TestCase):
    """New docs need `md` on every option; docs whose history predates `created` build as before."""

    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)

    def test_a_new_doc_names_the_item_and_option(self) -> None:
        out = self.tmp.dir / "new" / "acme-plan.bluedoc.json"
        out.parent.mkdir()
        self.assertEqual(self.tmp.run("build.py", "new", "plan", out).returncode, 0)
        doc = load_json(out)
        self.assertTrue(all(c.get("md") for c in item(doc, "decisions", "question-1")["choices"]), "the skeleton explains its options")
        del item(doc, "decisions", "question-1")["choices"][1]["md"]
        write_json(out, doc)
        r = self.tmp.run("build.py", out)
        self.assertEqual(r.returncode, 1)
        self.assertIn("option 'option-b' of item 'decisions/question-1' has no explanation", r.stderr)

    def test_first_build_marks_the_history_and_the_rule_holds_after(self) -> None:
        path = self.tmp.copy_examples() / PLAN
        build.history_path(path).unlink()   # the doc alone: no history yet
        r = self.tmp.run("build.py", path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(load_json(build.history_path(path))["created"], build.skill_version() or "unknown")
        doc = load_json(path)
        del item(doc, "decisions", "retention")["choices"][0]["md"]
        write_json(path, doc)
        r = self.tmp.run("build.py", path)
        self.assertEqual(r.returncode, 1)
        self.assertIn("option 'd90' of item 'decisions/retention' has no explanation", r.stderr)

    def test_an_old_doc_builds_with_no_error_and_no_warning(self) -> None:
        path = self.tmp.copy_examples() / REVIEW
        self.assertNotIn("created", load_json(build.history_path(path)))
        doc = load_json(path)
        for b in build.all_blocks(doc):
            for it in b.get("items") or [] if b.get("type") == "checklist" else []:
                for c in it.get("choices") or []:
                    c.pop("md", None)
        write_json(path, doc)
        r = self.tmp.run("build.py", path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 error(s), 0 warning(s)", r.stderr)


class ReaderThreadState(unittest.TestCase):
    """value_ok and state_ops on the reader's side of a conversation (a bad value is a 400 on PUT)."""

    AT = "2026-10-20T09:30:00.000Z"

    def thread(self, *entries) -> str:
        return json.dumps(list(entries))

    def test_item_thread(self) -> None:
        good = {"md": "Why 180?", "rev": "1", "at": self.AT}
        key = "decisions:retention:thread"
        self.assertTrue(serve.value_ok(key, self.thread(good, {**good, "rev": None})))
        self.assertTrue(serve.value_ok(key, "[]"))
        self.assertTrue(serve.value_ok(key, self.thread(*[good] * serve.THREAD_MAX)))
        for name, value in (("not JSON", "[{"), ("not a list", json.dumps(good)),
                            ("too many", self.thread(*[good] * (serve.THREAD_MAX + 1))),
                            ("empty md", self.thread({**good, "md": ""})),
                            ("md over the limit", self.thread({**good, "md": "x" * (build.MAX_REPLY_MD + 1)})),
                            ("rev over 40", self.thread({**good, "rev": "r" * 41})),
                            ("rev a number", self.thread({**good, "rev": 2})),
                            ("no at", self.thread({"md": "x", "rev": "1"})),
                            ("at not a time", self.thread({**good, "at": "yesterday"})),
                            ("a field of its own", self.thread({**good, "who": "me"}))):
            with self.subTest(name):
                self.assertFalse(serve.value_ok(key, value))
                with self.assertRaises(ValueError):
                    serve.state_ops({"ops": [[key, value]]})
        self.assertEqual(serve.state_ops({"ops": [[key, None]]}), [(key, None)])

    def test_picks(self) -> None:
        key = "decisions:guests"
        for v in ("=d180|d180", "=accounts,email|accounts,business", "=|accounts,business", "=email|", "1", "01"):
            with self.subTest(v):
                self.assertTrue(serve.value_ok(key, v))
        for v in ("=a,,b|c", "=a,a|c", "=a|b|c", "=a|b,b", "=,a|"):
            with self.subTest(v):
                self.assertFalse(serve.value_ok(key, v))
                with self.assertRaises(ValueError):
                    serve.state_ops({"ops": [[key, v]]})

    def test_annotation_follow_ups(self) -> None:
        ann = {"id": "c1abc", "type": "general", "target": {"key": "doc", "label": "Doc"}, "note": "Shorter?"}
        ok = lambda a: serve.value_ok("__ann:c1abc", json.dumps(a))   # noqa: E731
        self.assertTrue(ok(ann))
        self.assertTrue(ok({**ann, "thread": [{"md": "And the badge?", "rev": "2", "at": self.AT}], "draft": "Also"}))
        self.assertTrue(ok({**ann, "thread": [], "draft": None}))
        self.assertFalse(ok({**ann, "thread": [{"md": "x", "rev": "2"}]}))
        self.assertFalse(ok({**ann, "thread": "x"}))
        self.assertFalse(ok({**ann, "draft": 3}))


if __name__ == "__main__":
    unittest.main()
