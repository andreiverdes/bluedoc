"""Checklist kinds and evidence in the build (kinds/*).

A checklist is a decision list (every item has choices) or a progress list (none has); one that mixes them is an
error on a new revision and a warning on a doc that keeps no history, and a decision list after a progress list
warns. Steps and progress items may carry `evidence` (label plus md, code, src or href); evidence on a decision item,
an entry with nothing to show and a link with another scheme or an absolute path are errors, a dead local link a
warning."""
from __future__ import annotations

import json
import unittest

from _support import TempHome, load_json


class ChecklistKinds(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.plan = load_json(self.docs / "acme-saved-carts-plan.bluedoc.json")

    def lists(self, doc: dict) -> dict:
        return {b["id"]: b for s in doc["sections"] for b in s["blocks"] if b.get("type") in ("checklist", "steps")}

    def build(self, doc: dict) -> tuple[int, str]:
        path = self.docs / "acme-check.bluedoc.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        r = self.tmp.run("build.py", path, "--check")
        return r.returncode, r.stdout + r.stderr

    def test_a_mixed_checklist_fails_on_a_new_revision(self) -> None:
        ls = self.lists(self.plan)
        ls["checks"]["items"].append(ls["decisions"]["items"].pop(0))
        code, out = self.build(self.plan)
        self.assertEqual(code, 1, out)
        self.assertIn("checklist 'checks' mixes decisions (retention) and progress items", out)

    def test_a_mixed_checklist_without_history_only_warns(self) -> None:
        # a doc without meta.rev keeps no history and counts as recorded: older docs keep rendering
        doc = load_json(self.docs / "acme-status.bluedoc.json")
        blocks = doc["sections"][2]["blocks"]
        blocks[1]["items"].append(blocks[0]["items"][0])
        del blocks[0]
        del doc["meta"]["rev"]
        code, out = self.build(doc)
        self.assertEqual(code, 0, out)
        self.assertIn("checklist 'next' mixes decisions (saved-carts) and progress items (fulfilment, payco)", out)
        self.assertIn("an error as soon as the doc changes", out)

    def test_a_decision_list_after_a_progress_list_warns(self) -> None:
        secs = self.plan["sections"]
        secs.append(secs.pop(next(i for i, s in enumerate(secs) if s["id"] == "questions")))
        code, out = self.build(self.plan)
        self.assertEqual(code, 0, out)
        self.assertIn("decision list 'decisions' comes after progress list 'checks'", out)

    def test_evidence_on_steps_and_progress_items_builds_clean(self) -> None:
        ls = self.lists(self.plan)
        ls["plan"]["items"][0]["evidence"] = [
            {"label": "Migration test", "code": "pytest tests/test_migrations.py", "lang": "sh", "md": "`4 passed`"},
            {"label": "Wireframe", "src": "media/acme-saved-carts.svg"},
            {"label": "Status page", "href": "acme-status.bluedoc.json"}]
        ls["checks"]["items"][0]["evidence"] = [{"label": "CI run", "href": "https://ci.acme.example/123"}]
        code, out = self.build(self.plan)
        self.assertEqual(code, 0, out)
        self.assertIn("0 error(s), 0 warning(s)", out)

    def test_bad_evidence_is_reported_where_it_is(self) -> None:
        ls = self.lists(self.plan)
        ls["decisions"]["items"][0]["evidence"] = [{"label": "Acme", "md": "x"}]
        ls["plan"]["items"][0]["evidence"] = [
            {"label": "Nothing"},
            {"label": "Script", "href": "javascript:alert(1)"},
            {"label": "Absolute", "href": "/etc/acme.log"},
            {"label": "Dead", "href": "logs/acme.log"},
            {"label": "Missing image", "src": "media/acme-none.png"}]
        code, out = self.build(self.plan)
        self.assertEqual(code, 1, out)
        for want in ("evidence: a decision item is answered by 'choice'",
                     "evidence[0]: give at least one of md, code, src, href",
                     "evidence[1].href: 'javascript:alert(1)': evidence links take",
                     "evidence[2].href: '/etc/acme.log' is absolute",
                     "evidence[3].href: 'logs/acme.log' not found",
                     "evidence[4].src: 'media/acme-none.png' not found"):
            self.assertIn(want, out)


if __name__ == "__main__":
    unittest.main()
