"""The one layout bluedoc writes docs in: minified JSON on one line. `build.py new` writes it, patch and a build
rewrite an older pretty-printed doc in it with equal content, `build.py migrate` does it explicitly (--dry-run lists
only), and a layout-only rewrite records no revision."""
from __future__ import annotations

import json
import unittest

from _support import EXAMPLES, TempHome

import build


def minified(text: str) -> bool:
    return text == json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":")) + "\n"


class Layout(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.addCleanup(self.tmp.cleanup)
        self.docs = self.tmp.copy_examples()
        self.doc = self.docs / "acme-status.bluedoc.json"

    def pretty(self, path) -> dict:
        doc = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return doc

    def revs(self) -> list[str]:
        return [e["rev"] for e in build.load_history(build.history_path(self.doc))["revs"]]

    def test_the_examples_are_minified(self) -> None:
        for f in sorted(EXAMPLES.glob("*.bluedoc.json")):
            self.assertTrue(minified(f.read_text(encoding="utf-8")), f.name)

    def test_new_writes_minified_and_hints_get(self) -> None:
        out = self.tmp.dir / "new.bluedoc.json"
        r = self.tmp.run("build.py", "new", "plan", out, "--title", "Acme plan")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(minified(out.read_text(encoding="utf-8")))
        self.assertIn(f"get {out}", r.stdout)

    def test_patch_rewrites_a_pretty_doc_minified(self) -> None:
        doc = self.pretty(self.doc)
        r = self.tmp.run("build.py", "patch", self.doc, "meta", "--set", "kind=Status", "--no-bump")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.doc.read_text(encoding="utf-8")
        self.assertTrue(minified(text))
        doc["meta"]["kind"] = "Status"
        after = json.loads(text)
        for d in (doc, after):   # what a patch itself stamps
            d["meta"].pop("date", None), d.pop("changes", None)
        self.assertEqual(after, doc)

    def test_a_build_migrates_without_a_new_revision(self) -> None:
        self.assertEqual(self.tmp.run("build.py", self.doc).returncode, 0)
        revs = self.revs()
        history = build.history_path(self.doc).read_text(encoding="utf-8")
        doc = self.pretty(self.doc)
        r = self.tmp.run("build.py", self.doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(minified(self.doc.read_text(encoding="utf-8")))
        self.assertEqual(json.loads(self.doc.read_text(encoding="utf-8")), doc)
        self.assertEqual(self.revs(), revs)
        self.assertEqual(build.history_path(self.doc).read_text(encoding="utf-8"), history)
        self.pretty(self.doc)   # --check writes nothing, the layout included
        self.tmp.run("build.py", self.doc, "--check")
        self.assertFalse(minified(self.doc.read_text(encoding="utf-8")))

    def test_migrate_dry_run_lists_without_writing(self) -> None:
        self.pretty(self.doc)
        raw = self.doc.read_text(encoding="utf-8")
        r = self.tmp.run("build.py", "migrate", self.docs, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"would rewrite {self.doc}", r.stdout)
        self.assertEqual(r.stdout.count("would rewrite"), 1)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), raw)
        r = self.tmp.run("build.py", "migrate", self.doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"rewrote {self.doc}", r.stdout)
        self.assertTrue(minified(self.doc.read_text(encoding="utf-8")))
        self.assertEqual(json.loads(self.doc.read_text(encoding="utf-8")), json.loads(raw))


if __name__ == "__main__":
    unittest.main()
