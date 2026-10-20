"""Blueprint canvases laid out and routed as the page does it (board-geo.js's canvasLayout, canvasFit, canvasFrame,
canvasRoutes, under node), over every canvas of every example and tests/fixtures/canvas-tight.bluedoc.json (a col/row
canvas with long labels between neighbours and on frame ports), at every scope:
- no two nodes nearer each other than the base gap (CANVAS.gap) across or down;
- no edge through a node, its own two aside;
- no edge label on a node or on another label;
- no edge label on another edge's line.
build.py's canvas_layout (the validator's, and serve.py's home cards') places nodes where the page does. In Chrome
(BLUEDOC_BROWSER_TESTS=1) the drawn canvas keeps the same rules: its edges, sampled along their paths, stay off the
nodes and the other edges' labels. Skipped without node."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import EXAMPLES, EXAMPLE_STEMS, REPO, SKILL, load_json, template_text

import build

NODE = shutil.which("node")
GEO = SKILL / "assets" / "board-geo.js"
TIGHT = REPO / "tests" / "fixtures" / "canvas-tight.bluedoc.json"
GAP = 80   # board-geo.js CANVAS.gap: the least space between two nodes of a scope, across or down

# stdin: [[name, canvas]]; stdout: per scope {where, gap, nodes: [{id, x, y, w, h}], edges: [{id, from, to, points,
# label: {x, y, w, h} | null}]}, every scope of every canvas, laid out and routed as the page's prepScope and
# buildScope do it
RUNNER = """
const G = require(process.argv[1]);
const canvases = JSON.parse(require('fs').readFileSync(0, 'utf8')), out = [];
const sys = n => !!(n.children && n.children.nodes && n.children.nodes.length);
function scope(s, owner, where) {
  const boxes = G.canvasLayout(s);
  const frame = owner ? G.canvasFrame(owner.w, owner.h, G.canvasFit(owner.w, owner.h, G.canvasBounds(boxes), G.canvasRoom(s))) : null;
  const edges = G.canvasRoutes(s, boxes, frame).map(({ id, edge, route }) => {
    const w = edge.label ? G.canvasLabelW(edge.label) : 0, h = G.CANVAS.labelH;
    return { id, from: edge.from, to: edge.to, points: route.points,
      label: edge.label ? { x: route.label.x - w / 2, y: route.label.y - h / 2, w, h } : null };
  });
  out.push({ where, gap: G.CANVAS.gap, nodes: (s.nodes || []).map((n, k) => ({ id: n.id, ...boxes[k] })), edges });
  (s.nodes || []).forEach((n, k) => { if (sys(n)) scope(n.children, boxes[k], `${where}/${n.id}`); });
}
for (const [name, c] of canvases) scope(c, null, name);
process.stdout.write(JSON.stringify(out));
"""


def canvases(stem_paths: list[Path]) -> list[tuple[str, dict]]:
    out = []
    for p in stem_paths:
        for b in build.all_blocks(load_json(p)):
            if b.get("type") == "canvas":
                out.append((f"{p.name.split('.')[0]}#{b['id']}", b))
    return out


def scopes(cs: list[tuple[str, dict]]) -> list[dict]:
    r = subprocess.run([NODE, "-e", RUNNER, str(GEO)], input=json.dumps(cs), capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def overlap(a: dict, b: dict) -> float:
    return max(0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])) * max(0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))


def through(a: list, b: list, r: dict) -> bool:
    """Does segment a-b pass through the inside of r (running along its border is not through)."""
    return max(a[0], b[0]) > r["x"] and min(a[0], b[0]) < r["x"] + r["w"] and max(a[1], b[1]) > r["y"] and min(a[1], b[1]) < r["y"] + r["h"]


def apart(a: dict, b: dict) -> float:
    """The space between two boxes: across when they share rows, down when they share columns, else the larger."""
    return max(b["x"] - (a["x"] + a["w"]), a["x"] - (b["x"] + b["w"]), b["y"] - (a["y"] + a["h"]), a["y"] - (b["y"] + b["h"]))


def problems(sc: dict) -> list[str]:
    """Every broken rule in one routed scope, as text."""
    out, nodes, edges = [], sc["nodes"], sc["edges"]
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            if apart(a, b) < GAP - 1e-6:
                out.append(f"nodes {a['id']} and {b['id']} are {apart(a, b):.0f} apart (< {GAP})")
    for e in edges:
        segs = list(zip(e["points"], e["points"][1:]))
        for n in nodes:
            if n["id"] not in (e["from"], e["to"]) and any(through(a, b, n) for a, b in segs):
                out.append(f"edge {e['id']} runs through node {n['id']}")
        lr = e["label"]
        if not lr:
            continue
        for n in nodes:
            if overlap(lr, n) > 1e-6:
                out.append(f"edge {e['id']}'s label is on node {n['id']}")
        for f in edges:
            if f is e:
                continue
            if f["label"] and f["id"] > e["id"] and overlap(lr, f["label"]) > 1e-6:
                out.append(f"the labels of {e['id']} and {f['id']} overlap")
            if any(through(a, b, lr) for a, b in zip(f["points"], f["points"][1:])):
                out.append(f"edge {e['id']}'s label is on edge {f['id']}'s line")
    return [f"{sc['where']}: {p}" for p in out]


@unittest.skipUnless(NODE, "node not installed")
class CanvasInvariants(unittest.TestCase):
    def test_the_tight_canvas_keeps_nodes_edges_and_labels_apart(self) -> None:
        found = scopes(canvases([TIGHT]))
        self.assertEqual(len(found), 6, "the root and its five systems")
        self.assertEqual({sc["gap"] for sc in found}, {GAP})
        self.assertEqual([p for sc in found for p in problems(sc)], [])

    def test_every_example_canvas_keeps_nodes_edges_and_labels_apart(self) -> None:
        cs = canvases([EXAMPLES / f"{s}.bluedoc.json" for s in EXAMPLE_STEMS])
        self.assertTrue(cs, "no example has a canvas")
        self.assertEqual([p for sc in scopes(cs) for p in problems(sc)], [])

    def test_build_places_nodes_where_the_page_does(self) -> None:
        """build.canvas_layout (the validator's overlap check, serve.py's home card) and board-geo.js's canvasLayout
        give every node of every scope the same box."""
        cs = canvases([TIGHT] + [EXAMPLES / f"{s}.bluedoc.json" for s in EXAMPLE_STEMS])
        page = {sc["where"]: [[n["x"], n["y"], n["w"], n["h"]] for n in sc["nodes"]] for sc in scopes(cs)}

        def walk(s: dict, where: str):
            yield where, s
            for n in s.get("nodes") or []:
                if (n.get("children") or {}).get("nodes"):
                    yield from walk(n["children"], f"{where}/{n['id']}")
        for name, c in cs:
            for where, s in walk(c, name):
                got = [[round(v, 6) for v in b] for b in build.canvas_layout(s)]
                self.assertEqual(got, [[round(v, 6) for v in b] for b in page[where]], where)


class CanvasValidation(unittest.TestCase):
    def test_the_tight_canvas_validates(self) -> None:
        rep = build.validate(load_json(TIGHT))
        self.assertEqual((rep.errors, rep.warnings), ([], []))

    def test_placed_nodes_nearer_than_the_gap_warn(self) -> None:
        doc = load_json(TIGHT)
        c = next(b for b in build.all_blocks(doc) if b.get("type") == "canvas")
        c["nodes"] = [{"id": "a", "label": "A", "x": 0, "y": 0}, {"id": "b", "label": "B", "x": 230, "y": 0}]
        c["edges"], c["flows"] = [{"from": "a", "to": "b", "label": "call"}], []
        rep = build.validate(doc)
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("'a' and 'b' are 50 px apart" in w for w in rep.warnings), rep.warnings)
        c["nodes"][1]["x"] = 150
        self.assertTrue(any("'a' and 'b' overlap" in e for e in build.validate(doc).errors))


try:
    from test_page_state import CHROME, Browser, Tab
except ImportError:   # pragma: no cover
    CHROME = None

# in the page: for the canvas `cid`, every scope's nodes (canvas px) and, per edge, points sampled every 2 px along
# its drawn path and its label's box, all in the root's units
PAGE_SCOPES = """(cid => {
  const cv = BP.canvases[cid], out = [];
  const walk = s => {
    const a = s._abs, m = a.s;
    const nodes = s.nodes.map(n => ({ id: n.id, x: n._abs.x, y: n._abs.y, w: n._abs.w, h: n._abs.h }));
    const edges = Object.entries(s._edgeEls).map(([id, { path, e }]) => {
      const len = path.getTotalLength(), pts = [];
      for (let d = 0; d <= len; d += 2) { const p = path.getPointAtLength(d); pts.push([a.x + p.x * m, a.y + p.y * m]); }
      const g = s._g.querySelector(`.bp-elbl[data-edge="${CSS.escape(id)}"] rect`);
      const r = g && g.getBBox(), t = g && g.parentNode.transform.baseVal.consolidate().matrix;
      return { id, from: e.from, to: e.to, pts, label: r ? { x: a.x + (t.e + r.x) * m, y: a.y + (t.f + r.y) * m, w: r.width * m, h: r.height * m } : null, scale: m };
    });
    out.push({ nodes, edges });
    for (const n of s.nodes) if (n._sys) walk(n.children);
  };
  walk(cv.root);
  return out;
})"""


@unittest.skipUnless(CHROME, "set BLUEDOC_BROWSER_TESTS=1 to run the browser tests (BLUEDOC_CHROME: Chrome's path)")
class CanvasInChrome(unittest.TestCase):
    def test_drawn_edges_stay_off_nodes_and_labels(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="bluedoc-canvas-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        browser = Browser(tmp / "profile")
        self.addCleanup(browser.close)
        tab = Tab(browser)
        for doc in (TIGHT, EXAMPLES / "acme-orders.bluedoc.json", EXAMPLES / "acme-saved-carts-plan.bluedoc.json"):
            page = tmp / f"{doc.name}.html"
            page.write_text(build.build(load_json(doc), template_text(), None, problems=[]), encoding="utf-8")
            tab.go(page.as_uri())
            ids = tab.wait_for("Object.keys(BP.canvases).length && Object.keys(BP.canvases)")
            for cid in ids:
                for sc in tab.ev(f"{PAGE_SCOPES}({json.dumps(cid)})"):
                    for e in sc["edges"]:
                        inset = 1.5 * e["scale"]   # a drawn line is ~1.5 px wide: a sample on a border isn't inside
                        for n in sc["nodes"]:
                            if n["id"] in (e["from"], e["to"]):
                                continue
                            inside = [p for p in e["pts"] if n["x"] + inset < p[0] < n["x"] + n["w"] - inset and n["y"] + inset < p[1] < n["y"] + n["h"] - inset]
                            self.assertEqual(inside, [], f"{doc.name} {cid}: edge {e['id']} is drawn through node {n['id']}")
                        for f in sc["edges"]:
                            lr = f["label"]
                            if f is e or not lr:
                                continue
                            on = [p for p in e["pts"] if lr["x"] + inset < p[0] < lr["x"] + lr["w"] - inset and lr["y"] + inset < p[1] < lr["y"] + lr["h"] - inset]
                            self.assertEqual(on, [], f"{doc.name} {cid}: edge {e['id']} is drawn under {f['id']}'s label")
            self.assertEqual(browser.errors, [], doc.name)


if __name__ == "__main__":
    unittest.main()
