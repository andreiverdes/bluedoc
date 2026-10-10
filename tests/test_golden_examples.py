"""Golden examples: each example builds clean, and `build.py -o` reproduces its committed export byte for byte."""
from __future__ import annotations

import unittest

from _support import EXAMPLE_STEMS, EXPORTS, TempHome


class GoldenExamples(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempHome()
        self.docs = self.tmp.copy_examples()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_examples_build_clean_and_match_their_exports(self) -> None:
        for stem in EXAMPLE_STEMS:
            with self.subTest(example=stem):
                out = self.tmp.dir / "out" / f"{stem}.html"
                r = self.tmp.run("build.py", self.docs / f"{stem}.bluedoc.json", "-o", out)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("0 error(s), 0 warning(s)", r.stderr)
                committed = EXPORTS / f"{stem}.html"
                self.assertTrue(committed.is_file(), f"no committed export {committed}")
                self.assertTrue(out.read_bytes() == committed.read_bytes(),
                                f"{committed.relative_to(EXPORTS.parent.parent)} differs from `build.py -o` output: "
                                f"regenerate it with `build.py skills/bluedoc/examples/{stem}.bluedoc.json -o {committed.relative_to(EXPORTS.parent.parent)}`")


if __name__ == "__main__":
    unittest.main()
