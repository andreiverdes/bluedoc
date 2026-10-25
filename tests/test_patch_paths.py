"""build.py patch's nested --set paths (a/b/field: dict keys, list elements by id, else index), --append --at and
--move: each changes only what it names, and an unknown segment names the ids there."""
from __future__ import annotations

import json
import unittest

from _support import TempHome


def item(doc: dict, cid: str, iid: str) -> dict:
    for s in doc["sections"]:
        for b in s.get("blocks") or []:
            if b.get("id") == cid:
                return next(x for x in b["items"] if x["id"] == iid)
    raise KeyError(cid)


class PatchPaths(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.doc = self.tmp.copy_examples() / "acme-saved-carts-plan.bluedoc.json"

    def load(self) -> dict:
        return json.loads(self.doc.read_text(encoding="utf-8"))

    def patch(self, *args: str, code: int = 0):
        r = self.tmp.run("build.py", "patch", self.doc, *args)
        self.assertEqual(r.returncode, code, r.stderr)
        return r

    def test_a_nested_set_changes_one_field(self) -> None:
        before = item(self.load(), "decisions", "retention")
        self.patch("item:decisions/retention", "--set", "choices/d90/md=Short.")
        after = item(self.load(), "decisions", "retention")
        before["choices"][0]["md"] = "Short."
        self.assertEqual(after, before)

    def test_an_index_segment_and_null(self) -> None:
        self.patch("item:decisions/retention", "--set", "choices/1/label=Six months", "--set", "choices/forever=null")
        it = item(self.load(), "decisions", "retention")
        self.assertEqual(it["choices"][1]["label"], "Six months")
        self.assertEqual([c["id"] for c in it["choices"]], ["d90", "d180"])
        self.patch("item:decisions/retention", "--set", "choices/d90/md=null")
        self.assertNotIn("md", item(self.load(), "decisions", "retention")["choices"][0])

    def test_an_unknown_segment_names_the_ids(self) -> None:
        raw = self.doc.read_text(encoding="utf-8")
        r = self.patch("item:decisions/retention", "--set", "choices/d30/md=x", code=2)
        self.assertIn("no 'd30'", r.stderr)
        self.assertIn("d90, d180, forever", r.stderr)
        r = self.patch("item:decisions/retention", "--set", "nope/md=x", code=2)
        self.assertIn("no 'nope'", r.stderr)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), raw)

    def test_append_at_a_position_and_move(self) -> None:
        self.patch("section:context", "--append", '{"type":"text","md":"First."}', "--at", "0")
        self.assertEqual(self.load()["sections"][0]["blocks"][0]["md"], "First.")
        self.patch("doc", "--append", '{"id":"notes","title":"Notes","blocks":[]}', "--at", "1")
        self.assertEqual([s["id"] for s in self.load()["sections"]][:3], ["context", "notes", "approach"])
        self.patch("section:notes", "--move", "0")
        self.assertEqual(self.load()["sections"][0]["id"], "notes")
        self.patch("item:decisions/guests", "--move", "0")
        cl = next(b for s in self.load()["sections"] for b in s["blocks"] if b.get("id") == "decisions")
        self.assertEqual([x["id"] for x in cl["items"]], ["guests", "retention", "prices"])
        self.patch("section:notes", "--move", "99", code=2)
        self.patch("section:notes", "--at", "0", code=2)


if __name__ == "__main__":
    unittest.main()
