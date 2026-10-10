"""build.py's board_layout and the page's boardLayout place every artboard alike: on the examples and on generated
boards, rows and `layout: "flow"`. The page side runs under node: template.html's DEVICES, abSize and boardLayout
over board-geo.js, as build.py inlines it. Skipped without node."""
from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import unittest

from _support import EXAMPLES, SKILL, load_json, template_text

import build

NODE = shutil.which("node")
GEO = SKILL / "assets" / "board-geo.js"


def board_of(doc: dict) -> dict | None:
    return next((b for s in doc.get("sections") or [] for b in s.get("blocks") or [] if b.get("type") == "board"), None)


def page_layout(cases: list[tuple[dict, list | None]]) -> list[dict]:
    """The page's {id: [x, y, w, h]} for each (board, links), via template.html's own boardLayout."""
    t = template_text()
    parts = []
    for pat in (r"^const DEVICES = [^\n]*;$", r"^const abSize = [^\n]*;$", r"^function boardLayout\(b, links\) \{[^\n]*\}$"):
        m = re.search(pat, t, re.M)
        assert m, f"template.html has no line matching {pat!r}: update this test"
        parts.append(m.group(0))
    js = ("const {geo, page, cases} = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
          "const boardLayout = new Function(geo + '\\n' + page + '\\nreturn boardLayout;')();"
          "process.stdout.write(JSON.stringify(cases.map(([b, l]) => Object.fromEntries("
          "[...boardLayout(b, l)].map(([k, p]) => [k, [p.x, p.y, p.w, p.h]])))));")
    r = subprocess.run([NODE, "-e", js], input=json.dumps({"geo": GEO.read_text(encoding="utf-8"), "page": "\n".join(parts), "cases": cases}),
                       capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def generated(seed: int) -> tuple[dict, list]:
    """A board of 6-30 artboards: phones with links, variants, some placed, a few other devices and slides."""
    rnd = random.Random(seed)
    n = rnd.randint(6, 30)
    arts, links = [], []
    for k in range(n):
        a = {"id": f"s{k}", "device": rnd.choice(["phone"] * 6 + ["tablet", "browser", "watch-round", "slide", "icons"])}
        if k and rnd.random() < 0.15:
            a["variantOf"] = f"s{rnd.randrange(k)}"
        if rnd.random() < 0.12:
            a["x"], a["y"] = rnd.randrange(-500, 4000, 20), rnd.randrange(-500, 4000, 20)
        if rnd.random() < 0.05:
            a = {"id": f"s{k}", "w": rnd.randint(200, 900), "h": rnd.randint(200, 900)}
        arts.append(a)
    for k in range(rnd.randint(0, 2 * n)):
        a, b = rnd.randrange(n), rnd.randrange(n)
        kind = rnd.choice(["push", "push", "modal", "tab", "replace", "back"])
        links.append({"from": f"s{a}", "el": f"e{k}", "to": None if kind == "back" else f"s{b}", "kind": kind})
    board = {"type": "board", "id": "main", "artboards": arts, "layout": rnd.choice(["flow", "flow", "rows"]),
             "entry": [f"s{rnd.randrange(n)}" for _ in range(rnd.randint(0, 2))]}
    return board, links


@unittest.skipUnless(NODE, "node not installed")
class BoardLayoutParity(unittest.TestCase):
    def assert_same(self, cases: list[tuple[dict, list | None]], names: list[str]) -> None:
        got = page_layout(cases)
        for (board, links), page, name in zip(cases, got, names):
            want = {k: list(v) for k, v in build.board_layout(board, links).items()}
            self.assertEqual(list(page), list(want), f"{name}: artboards or their order differ")
            self.assertEqual(page, want, f"{name}: boxes differ")

    def test_examples(self) -> None:
        cases, names = [], []
        for p in sorted(EXAMPLES.glob("*.bluedoc.json")):
            doc = load_json(p)
            board = board_of(doc)
            if board:
                links = build.board_links(doc, p)
                cases += [(board, links), ({**board, "layout": "flow"}, links), ({**board, "layout": "rows"}, links)]
                names += [p.name, p.name + " as flow", p.name + " as rows"]
        self.assertTrue(cases, "no example has a board")
        self.assert_same(cases, names)

    def test_flow_example_unplaced(self) -> None:
        """Acme Fit with every x, y dropped: the flow places the phone flow in columns by depth."""
        p = EXAMPLES / "acme-fit-design.bluedoc.json"
        doc = load_json(p)
        board = board_of(doc)
        bare = {**board, "layout": "flow", "artboards": [{k: v for k, v in a.items() if k not in ("x", "y")} for a in board["artboards"]]}
        links = build.board_links(doc, p)
        self.assert_same([(bare, links)], ["acme-fit-design, unplaced"])
        at = build.board_layout(bare, links)
        for e in board.get("entry") or []:
            self.assertEqual(at[e][0], 0, f"entry {e} is not in column 0")

    def test_generated_boards(self) -> None:
        cases = [generated(seed) for seed in range(300)]
        cases += [(b, None) for b, _ in cases[:20]]
        self.assert_same(cases, [f"seed {k}" for k in range(300)] + [f"seed {k}, links None" for k in range(20)])


if __name__ == "__main__":
    unittest.main()
