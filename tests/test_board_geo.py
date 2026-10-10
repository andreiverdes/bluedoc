"""board-geo.js under node: the connector router (routeLinks, reroute) and Tidy up's layered layout (tidy).
Router: every segment horizontal or vertical, clear of the screens it passes, no two connectors on one segment, each
end square to its target's border, no curves; 30 screens and 60 links in under 50 ms. Tidy: no overlaps, the same
input gives the same output, 0 crossings on Acme Fit, no more crossings than the flow layout on generated boards.
Skipped without node."""
from __future__ import annotations

import json
import random
import shutil
import subprocess
import unittest

from _support import EXAMPLES, SKILL, load_json

import build

NODE = shutil.which("node")
GEO = SKILL / "assets" / "board-geo.js"
PAD = 24          # board-geo.js: the clearance routes keep around screens
PHONE = (390, 844)

# calls: [[fn, ...args]]; "route" is routeLinks timed over `reps` runs (the median, in ms, after one warm-up run)
RUNNER = """
const G = require(process.argv[1]);
const calls = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = calls.map(([fn, ...args]) => {
  if (fn !== 'time') return fn === 'boardLayout' ? Object.fromEntries([...G.boardLayout(args[0], args[1], () => args[2])].map(([k, p]) => [k, [p.x, p.y]])) : G[fn](...args);
  const [boxes, links, reps] = args, ms = [];
  G.routeLinks(boxes, links);
  for (let k = 0; k < reps; k++) { const t = process.hrtime.bigint(); G.routeLinks(boxes, links); ms.push(Number(process.hrtime.bigint() - t) / 1e6); }
  return ms.sort((a, b) => a - b)[reps >> 1];
});
process.stdout.write(JSON.stringify(out));
"""


def geo(*calls: list) -> list:
    r = subprocess.run([NODE, "-e", RUNNER, str(GEO)], input=json.dumps(list(calls)), capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def grid_board(seed: int, n: int = 30, m: int = 60) -> tuple[dict, list]:
    """n phones in rows of 6, 200 px apart, and m random links, 70 % of them from an element (a tab-bar-sized rect)."""
    rnd = random.Random(seed)
    boxes = {f"s{k}": {"x": (k % 6) * 590, "y": (k // 6) * 964, "w": PHONE[0], "h": PHONE[1]} for k in range(n)}
    links = []
    for k in range(m):
        a = rnd.randrange(n)
        b = (a + 1 + rnd.randrange(n - 1)) % n
        A = boxes[f"s{a}"]
        src = ({"x": A["x"] + 16 + 90 * rnd.randrange(4), "y": A["y"] + 40 + 80 * rnd.randrange(10), "w": 80, "h": 40}
               if rnd.random() < 0.7 else None)
        links.append({"from": f"s{a}", "el": f"e{k}", "to": f"s{b}", "kind": "push", "src": src})
    return boxes, links


def app_board(seed: int, n: int = 30, extra: int = 15) -> tuple[list, list]:
    """An app-shaped flow: a tree of n phones from s0, plus `extra` cross links."""
    rnd = random.Random(seed)
    links = [{"from": f"s{rnd.randrange(k)}", "el": f"e{k}", "to": f"s{k}", "kind": "tab" if rnd.random() < 0.3 else "push"} for k in range(1, n)]
    for k in range(extra):
        a = rnd.randrange(n)
        b = (a + 1 + rnd.randrange(n - 1)) % n
        links.append({"from": f"s{a}", "el": f"x{k}", "to": f"s{b}", "kind": "modal"})
    return [{"id": f"s{k}", "w": PHONE[0], "h": PHONE[1], "device": "phone"} for k in range(n)], links


def segments(pts: list) -> list:
    return list(zip(pts, pts[1:]))


def hits(a: list, b: list, r: dict, grow: float) -> bool:
    """Does segment a-b pass through the inside of r grown by `grow`."""
    x0, y0, x1, y1 = r["x"] - grow, r["y"] - grow, r["x"] + r["w"] + grow, r["y"] + r["h"] + grow
    return max(a[0], b[0]) > x0 and min(a[0], b[0]) < x1 and max(a[1], b[1]) > y0 and min(a[1], b[1]) < y1


def crossings(res: dict) -> list:
    """Pairs of connectors whose segments cross (a horizontal through a vertical's inside)."""
    ids, out = list(res), []
    for i, p in enumerate(ids):
        for q in ids[i + 1:]:
            for a, b in segments(res[p]["points"]):
                for c, d in segments(res[q]["points"]):
                    va, vc = a[0] == b[0], c[0] == d[0]
                    if va == vc:
                        continue
                    (h1, h2), (v1, v2) = ((c, d), (a, b)) if va else ((a, b), (c, d))
                    x, y = v1[0], h1[1]
                    if min(h1[0], h2[0]) < x < max(h1[0], h2[0]) and min(v1[1], v2[1]) < y < max(v1[1], v2[1]):
                        out.append((p, q, x, y))
    return out


def overlaps(res: dict) -> list:
    """Pairs of connectors that run along one line together for more than a point."""
    ids, out = list(res), []
    for i, p in enumerate(ids):
        for q in ids[i + 1:]:
            for a, b in segments(res[p]["points"]):
                for c, d in segments(res[q]["points"]):
                    va, vc = a[0] == b[0], c[0] == d[0]
                    if va != vc or abs((a[0] if va else a[1]) - (c[0] if vc else c[1])) > 1e-6:
                        continue
                    k = 1 if va else 0
                    lo, hi = max(min(a[k], b[k]), min(c[k], d[k])), min(max(a[k], b[k]), max(c[k], d[k]))
                    if hi - lo > 1e-6:
                        out.append((p, q))
    return out


@unittest.skipUnless(NODE, "node not installed")
class Router(unittest.TestCase):
    def assert_routes(self, boxes: dict, links: list, res: dict) -> None:
        """Every property a route must have, for every link between two boxes."""
        want = {f"{ln['from']}/{ln['el']}" for ln in links if ln.get("to") in boxes and ln["to"] != ln["from"]}
        self.assertEqual(set(res), want, "a link has no route, or a route no link")
        by_id = {f"{ln['from']}/{ln['el']}": ln for ln in links}
        for lid, r in res.items():
            ln, pts = by_id[lid], r["points"]
            A, B = boxes[ln["from"]], boxes[ln["to"]]
            self.assertGreaterEqual(len(pts), 2, lid)
            for a, b in segments(pts):
                self.assertTrue(a[0] == b[0] or a[1] == b[1], f"{lid}: {a} → {b} is not horizontal or vertical")
                self.assertNotEqual(a, b, f"{lid}: a zero-length segment")
            # starts on its element (or the screen's border), inside its screen
            src = ln.get("src")
            s = pts[0]
            if src:
                self.assertTrue(src["x"] <= s[0] <= src["x"] + src["w"] and src["y"] <= s[1] <= src["y"] + src["h"], f"{lid}: starts off its element")
            else:
                on = (s[0] in (A["x"], A["x"] + A["w"]) and A["y"] <= s[1] <= A["y"] + A["h"]) or \
                     (s[1] in (A["y"], A["y"] + A["h"]) and A["x"] <= s[0] <= A["x"] + A["w"])
                self.assertTrue(on, f"{lid}: a border start {s} is not on its screen's border")
            # ends on the target's border, the last segment square to it, coming from outside
            e, f = pts[-1], pts[-2]
            side = r["end"]
            square = {"l": e[0] == B["x"] and f[1] == e[1] and f[0] < e[0],
                      "r": e[0] == B["x"] + B["w"] and f[1] == e[1] and f[0] > e[0],
                      "t": e[1] == B["y"] and f[0] == e[0] and f[1] < e[1],
                      "b": e[1] == B["y"] + B["h"] and f[0] == e[0] and f[1] > e[1]}[side]
            self.assertTrue(square, f"{lid}: does not end square on the {side} side of {ln['to']}: {pts[-2:]}")
            # clear of every screen: the middle segments by half the padding; the first and last of every screen
            # but their own
            for k, (a, b) in enumerate(segments(pts)):
                end = k == 0 or k == len(pts) - 2
                for bid, box in boxes.items():
                    if end and bid in (ln["from"], ln["to"]):
                        continue
                    self.assertFalse(hits(a, b, box, PAD / 2 - 1), f"{lid}: {a} → {b} runs through or beside {bid}")
            # no curves: only moves, lines and arcs (the rounded corners)
            self.assertRegex(r["d"], r"^M[-\d. ]+(?:[LA][-\d. ]+)*$", f"{lid}: d has other commands")
            self.assertEqual(r["d"].count("A"), len(pts) - 2, f"{lid}: one rounded corner per bend")
            # the label sits on the longest segment
            lx, ly = r["label"]["x"], r["label"]["y"]
            longest = max(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in segments(pts))
            self.assertTrue(any(abs(b[0] - a[0]) + abs(b[1] - a[1]) == longest and (lx, ly) == ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                                for a, b in segments(pts)), f"{lid}: the label is not at the longest segment's middle")
        self.assertEqual(overlaps(res), [], "two connectors share a segment")

    def test_generated_boards(self) -> None:
        boards = [grid_board(seed) for seed in range(1, 41)]
        for (boxes, links), res in zip(boards, geo(*[["routeLinks", b, ln] for b, ln in boards])):
            self.assert_routes(boxes, links, res)

    def test_speed_30_screens_60_links(self) -> None:
        boards = [grid_board(seed) for seed in (1, 2, 3)]
        for ms in geo(*[["time", b, ln, 7] for b, ln in boards]):
            self.assertLess(ms, 50, f"routing 30 screens and 60 links took {ms:.1f} ms")

    def test_two_screens_side_by_side(self) -> None:
        """Facing screens get straight connectors, ends spread on the target's side; back and self links get none."""
        boxes = {"a": {"x": 0, "y": 0, "w": 390, "h": 844}, "b": {"x": 590, "y": 0, "w": 390, "h": 844}}
        links = [{"from": "a", "el": "x", "to": "b", "kind": "push"}, {"from": "b", "el": "y", "to": "a", "kind": "push"},
                 {"from": "a", "el": "z", "to": "b", "kind": "tab", "src": {"x": 300, "y": 422, "w": 80, "h": 40}},
                 {"from": "a", "el": "back", "to": None, "kind": "back"}, {"from": "a", "el": "self", "to": "a", "kind": "push"},
                 {"from": "a", "el": "gone", "to": "nowhere", "kind": "push"}]
        res = geo(["routeLinks", boxes, links])[0]
        self.assertEqual(set(res), {"a/x", "b/y", "a/z"})
        for r in res.values():
            self.assertEqual(len(r["points"]), 2, r["points"])
        self.assertEqual(res["a/z"]["points"][0], [380, 442], "an element start leaves its side facing the target")
        ends = sorted(res[k]["points"][-1][1] for k in ("a/x", "a/z"))
        self.assertGreaterEqual(ends[1] - ends[0], 24, "two ends on one side sit apart")
        self.assert_routes(boxes, links, res)

    def test_reroute(self) -> None:
        """reroute after a move gives valid routes, keeps the routes the move doesn't touch, and with nothing
        moved returns what it was given."""
        boxes, links = grid_board(7)
        moved = {**boxes, "s7": {**boxes["s7"], "x": boxes["s7"]["x"] + 40, "y": boxes["s7"]["y"] + 30}}
        first = geo(["routeLinks", boxes, links])[0]
        again, after = geo(["reroute", first, boxes, links, []], ["reroute", first, moved, links, ["s7"]])
        self.assertEqual({k: v["points"] for k, v in again.items()}, {k: v["points"] for k, v in first.items()})
        self.assert_routes(moved, links, after)
        to = {f"{ln['from']}/{ln['el']}": ln["to"] for ln in links}
        far = [k for k, v in first.items() if not k.startswith("s7/") and to[k] != "s7"
               and not any(hits(a, b, moved["s7"], PAD) for a, b in segments(v["raw"]))]
        kept = [k for k in far if after[k]["raw"] == first[k]["raw"]]
        self.assertGreater(len(kept), len(far) // 2, "reroute routed most untouched links anew")

    def test_deterministic(self) -> None:
        boxes, links = grid_board(3)
        a, b = geo(["routeLinks", boxes, links], ["routeLinks", boxes, links[::-1]])
        self.assertEqual(a, geo(["routeLinks", boxes, links])[0])
        self.assertEqual(set(a), set(b))


def acme() -> tuple[dict, list, list]:
    p = EXAMPLES / "acme-fit-design.bluedoc.json"
    doc = load_json(p)
    board = next(b for s in doc["sections"] for b in s["blocks"] if b.get("type") == "board")
    screens = []
    for a in board["artboards"]:
        w, h = build.artboard_size(a)
        screens.append({"id": a["id"], "w": w, "h": h, "device": a.get("device"), "variantOf": a.get("variantOf")})
    return board, screens, build.board_links(doc, p)


@unittest.skipUnless(NODE, "node not installed")
class Tidy(unittest.TestCase):
    def boxes(self, screens: list, at: dict) -> dict:
        return {s["id"]: {"x": at[s["id"]][0], "y": at[s["id"]][1], "w": s["w"], "h": s["h"]} for s in screens if s["id"] in at}

    def assert_apart(self, boxes: dict) -> None:
        """No two screens overlap, and every two leave a routing channel (2 × the padding) between them."""
        ids = list(boxes)
        for i, p in enumerate(ids):
            for q in ids[i + 1:]:
                a, b = boxes[p], boxes[q]
                gap = max(b["x"] - a["x"] - a["w"], a["x"] - b["x"] - b["w"], b["y"] - a["y"] - a["h"], a["y"] - b["y"] - b["h"])
                self.assertGreaterEqual(gap, 2 * PAD, f"{p} and {q} are {gap} px apart")

    def test_acme_fit(self) -> None:
        board, screens, links = acme()
        at, at2 = geo(["tidy", screens, links, board.get("entry")], ["tidy", screens, links, board.get("entry")])
        self.assertEqual(at, at2, "the same input gives another layout")
        self.assertEqual(set(at), {s["id"] for s in screens if s["device"] != "slide"})
        boxes = self.boxes(screens, at)
        self.assert_apart(boxes)
        # columns by depth: the entry first, each link's target at least as far right as needed
        entry = board["entry"][0]
        self.assertEqual(at[entry][0], min(x for x, _ in at.values()), "the entry is not in the first column")
        self.assertGreater(at["today"][0], at[entry][0])
        self.assertGreater(at["workout"][0], at["today"][0])
        self.assertEqual(at["login-b"][0], at["login"][0], "a variant sits in its source's column")
        self.assertGreater(at["login-b"][1], at["login"][1], "a variant sits under its source")
        res = geo(["routeLinks", boxes, links])[0]
        Router.assert_routes(self, boxes, links, res)
        self.assertEqual(crossings(res), [], "Tidy up leaves crossings on Acme Fit")

    def test_generated_no_worse_than_flow(self) -> None:
        for seed in range(1, 9):
            screens, links = app_board(seed)
            abs_ = [{"id": s["id"], "device": "phone"} for s in screens]
            tidy_at, flow_at = geo(["tidy", screens, links, ["s0"]], ["boardLayout", {"artboards": abs_, "entry": ["s0"], "layout": "flow"}, links, list(PHONE)])
            tb, fb = self.boxes(screens, tidy_at), self.boxes(screens, flow_at)
            self.assert_apart(tb)
            rt, rf = geo(["routeLinks", tb, links], ["routeLinks", fb, links])
            Router.assert_routes(self, tb, links, rt)
            self.assertLessEqual(len(crossings(rt)), len(crossings(rf)), f"seed {seed}: Tidy up crosses more than the flow layout")

    def test_unreached_go_in_rows_below(self) -> None:
        """Screens no entry reaches go below the layers, one row per device; slides keep their column."""
        screens = [{"id": "a", "w": 390, "h": 844, "device": "phone"}, {"id": "b", "w": 390, "h": 844, "device": "phone"},
                   {"id": "lost", "w": 390, "h": 844, "device": "phone"}, {"id": "web", "w": 1440, "h": 900, "device": "browser"},
                   {"id": "web2", "w": 1440, "h": 900, "device": "browser"}, {"id": "deck", "w": 1920, "h": 1080, "device": "slide"}]
        links = [{"from": "a", "el": "go", "to": "b", "kind": "push"}, {"from": "b", "el": "back", "to": None, "kind": "back"}]
        at = geo(["tidy", screens, links, ["a"]])[0]
        self.assertNotIn("deck", at)
        self.assertEqual(at["a"], [0, 0])
        self.assertEqual(at["b"][1], 0)
        self.assertGreater(at["lost"][1], 844)
        self.assertEqual(at["web"][1], at["web2"][1])
        self.assertGreater(at["web"][1], at["lost"][1])
        self.assert_apart(self.boxes(screens, at))


if __name__ == "__main__":
    unittest.main()
