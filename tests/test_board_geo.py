"""board-geo.js under node: the connector router (routeLinks, reroute) and Tidy up's layered layout (tidy).
Router: every segment horizontal or vertical, clear of the screens it passes, no two connectors on one segment, each
end square to its target's border, no curves; 30 screens and 60 links in under 50 ms. Tidy: no overlaps, the same
input gives the same output, 0 crossings on Acme Fit, no more crossings than the flow layout on generated boards.
Blueprint canvases: labels clear of nodes and of each other (least overlap where nothing is clear), frame ports.
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

# calls: [[fn, ...args]] run in one node process:
# - "time": routeLinks timed over `reps` runs (the median, in ms, after one warm-up run)
# - "settle": routeLinks, then reroute(previous, the same boxes, the same links, moved) n times; each run's points
# - "drag": one box moved by (dx, dy) per step, `steps` times, each step rerouted from the last; per link, the
#   topology of its path at every step (its sides, then the direction of each segment longer than 4 px, repeats
#   merged: "rbRU" leaves the right side, enters the bottom one, runs right, then up)
RUNNER = """
const G = require(process.argv[1]);
const calls = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const pts = r => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, v.points]));
const topo = r => r.start + r.end + r.points.slice(1).map((q, k) => { const p = r.points[k];
  return Math.abs(q[0] - p[0]) + Math.abs(q[1] - p[1]) <= 4 ? '' : q[0] > p[0] ? 'R' : q[0] < p[0] ? 'L' : q[1] > p[1] ? 'D' : 'U'; }).join('').replace(/(.)\\1+/g, '$1');
const out = calls.map(([fn, ...args]) => {
  if (fn === 'settle') {
    const [boxes, links, moved, n] = args, runs = [];
    let r = G.routeLinks(boxes, links);
    for (let k = 0; k < n; k++) { r = G.reroute(r, boxes, links, moved); runs.push(pts(r)); }
    return runs;
  }
  if (fn === 'drag') {
    const [boxes, links, id, dx, dy, steps] = args, hist = {}, b0 = boxes[id];
    let r = null;
    for (let s = 0; s <= steps; s++) {
      const b = { ...b0, x: b0.x + dx * s, y: b0.y + dy * s }, bx = { ...boxes, [id]: b };
      const ls = links.map(l => l.from === id && l.src ? { ...l, src: { ...l.src, x: l.src.x + dx * s, y: l.src.y + dy * s } } : l);
      r = r ? G.reroute(r, bx, ls, [id]) : G.routeLinks(bx, ls);
      for (const [k, v] of Object.entries(r)) (hist[k] = hist[k] || []).push(topo(v));
    }
    return hist;
  }
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
    def assert_routes(self, boxes: dict, links: list, res: dict, pad: float = PAD) -> None:
        """Every property a route must have, for every link between two boxes (pad: the clearance routed with)."""
        lid_of = lambda ln: ln.get("id") or f"{ln['from']}/{ln['el']}"
        want = {lid_of(ln) for ln in links if ln.get("to") in boxes and ln["to"] != ln["from"]}
        self.assertEqual(set(res), want, "a link has no route, or a route no link")
        by_id = {lid_of(ln): ln for ln in links}
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
                    if (end and bid in (ln["from"], ln["to"])) or not (box["w"] and box["h"]):   # a frame port is no obstacle
                        continue
                    self.assertFalse(hits(a, b, box, pad / 2 - 1), f"{lid}: {a} → {b} runs through or beside {bid}")
            # no curves: only moves, lines and arcs (the rounded corners)
            self.assertRegex(r["d"], r"^M[-\d. ]+(?:[LA][-\d. ]+)*$", f"{lid}: d has other commands")
            self.assertEqual(r["d"].count("A"), len(pts) - 2, f"{lid}: one rounded corner per bend")
            # a label without a size sits at the middle of the longest segment (a sized one: CanvasEdges)
            if not ln.get("labelBox"):
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


def acme() -> tuple[dict, list, list]:
    p = EXAMPLES / "acme-fit-design.bluedoc.json"
    doc = load_json(p)
    board = next(b for s in doc["sections"] for b in s["blocks"] if b.get("type") == "board")
    screens = []
    for a in board["artboards"]:
        w, h = build.artboard_size(a)
        screens.append({"id": a["id"], "w": w, "h": h, "device": a.get("device"), "variantOf": a.get("variantOf")})
    return board, screens, build.board_links(doc, p)


BEZEL = {"watch-round": 12, "watch-square": 10, "phone": 12, "tablet": 14}   # template.html's, around each screen


def acme_board() -> tuple[dict, list]:
    """Acme Fit as the page routes it: each screen where the board puts it, with its bezel and 24 px title bar as
    the obstacle; every link with a target, keyed as the page keys it, starting on the screen's border."""
    board, screens, links = acme()
    at, dev = build.board_layout(board, links), {a["id"]: a.get("device") for a in board["artboards"]}
    boxes = {}
    for aid, (x, y, w, h) in at.items():
        bz = BEZEL.get(dev[aid], 0)
        boxes[aid] = {"x": x - bz, "y": y - bz - 24, "w": w + 2 * bz, "h": h + 2 * bz + 24}
    return boxes, [{"id": f"link:{ln['from']}/{ln['el']}", "from": ln["from"], "el": ln["el"], "to": ln["to"], "kind": ln["kind"]}
                   for ln in links if ln.get("to")]


@unittest.skipUnless(NODE, "node not installed")
class Stable(unittest.TestCase):
    """Connectors don't flicker: the same input gives the same paths, rerouting an unchanged board changes nothing,
    and dragging a screen changes a connector's shape only a few times, never back and forth."""

    def boards(self) -> list:
        return [acme_board()] + [grid_board(seed) for seed in range(100, 120)]

    def test_same_input_same_paths(self) -> None:
        boards = self.boards()
        calls = [c for b, ln in boards for c in (["routeLinks", b, ln], ["routeLinks", b, ln], ["routeLinks", b, ln[::-1]])]
        out = geo(*calls)
        for k in range(len(boards)):
            a, b, rev = out[3 * k: 3 * k + 3]
            self.assertTrue(a, f"board {k}: no routes")
            self.assertEqual(a, b, f"board {k}: routeLinks gave two answers to one input")
            self.assertEqual({i: r["points"] for i, r in rev.items()}, {i: r["points"] for i, r in a.items()},
                             f"board {k}: the order of the links changed the paths")

    def test_reroute_of_an_unchanged_board_changes_nothing(self) -> None:
        boards = self.boards()
        calls = [["settle", b, ln, moved, 10] for b, ln in boards for moved in ([], [next(iter(b))])]
        first = geo(*[["routeLinks", b, ln] for b, ln in boards])
        for k, runs in enumerate(geo(*calls)):
            want = {i: r["points"] for i, r in first[k // 2].items()}
            for n, got in enumerate(runs):
                self.assertEqual(got, want, f"board {k // 2}: reroute #{n + 1} on the same input moved a path")

    def test_drag_one_px_at_a_time(self) -> None:
        """50 steps of 1 px: each connector switches shape at most 4 times, and never returns to a shape it just left."""
        acme_boxes, acme_links = acme_board()
        drags = [(acme_boxes, acme_links, aid, dx, dy) for aid in ("login", "today", "workouts", "profile")
                 for dx, dy in ((1, 0), (0, 1), (-1, 1))]
        for seed in range(1, 11):
            boxes, links = grid_board(seed)
            drags.append((boxes, links, f"s{seed % 30}", 1, 1 if seed % 2 else -1))
        for (_, _, aid, dx, dy), hist in zip(drags, geo(*[["drag", b, ln, aid, dx, dy, 50] for b, ln, aid, dx, dy in drags])):
            for lid, seq in hist.items():
                runs = [t for n, t in enumerate(seq) if not n or t != seq[n - 1]]
                where = f"dragging {aid} by ({dx}, {dy}): {lid} went {' → '.join(runs)}"
                self.assertLessEqual(len(runs) - 1, 4, where)
                self.assertFalse(any(runs[n] == runs[n - 2] for n in range(2, len(runs))), where)


def canvas_scope(seed: int, links: int = 10) -> tuple[dict, list]:
    """A blueprint scope: 9 nodes of 180 × 80 on a 300 × 220 grid, and random edges with labels up to 11 characters
    (the page sizes a label 5.9 px a character + 14, 18 high)."""
    rnd = random.Random(seed)
    boxes = {f"n{k}": {"x": (k % 3) * 300 - 90, "y": (k // 3) * 220 - 40, "w": 180, "h": 80} for k in range(9)}
    out = []
    for k in range(links):
        a = rnd.randrange(9)
        b = (a + 1 + rnd.randrange(8)) % 9
        out.append({"id": f"e{k}", "from": f"n{a}", "to": f"n{b}", "kind": "data", "labelBox": [(3 + rnd.randrange(9)) * 5.9 + 14, 18]})
    return boxes, out


def label_rect(r: dict, ln: dict) -> dict:
    w, h = ln["labelBox"]
    return {"x": r["label"]["x"] - w / 2, "y": r["label"]["y"] - h / 2, "w": w, "h": h}


def overlap(a: dict, b: dict) -> float:
    return max(0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])) * max(0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))


def on_path(pts: list, x: float, y: float, w: float, h: float) -> bool:
    """Is a w × h label centred at x, y on a segment of pts: across it, or beside it and touching it."""
    for a, b in segments(pts):
        if a[1] == b[1] and min(a[0], b[0]) <= x <= max(a[0], b[0]) and abs(y - a[1]) <= h / 2 + 1:
            return True
        if a[0] == b[0] and min(a[1], b[1]) <= y <= max(a[1], b[1]) and abs(x - a[0]) <= w / 2 + 1:
            return True
    return False


@unittest.skipUnless(NODE, "node not installed")
class CanvasEdges(unittest.TestCase):
    """What blueprint canvases ask of the router: labels placed clear of nodes and of each other, and frame ports."""

    def test_labels_clear_of_nodes_and_each_other(self) -> None:
        scopes = [canvas_scope(seed) for seed in range(1, 21)]
        for (boxes, links), res in zip(scopes, geo(*[["routeLinks", b, ln, {"pad": 16}] for b, ln in scopes])):
            by = {ln["id"]: ln for ln in links}
            rects = {i: label_rect(r, by[i]) for i, r in res.items()}
            for i, lr in rects.items():
                self.assertTrue(on_path(res[i]["points"], res[i]["label"]["x"], res[i]["label"]["y"], lr["w"], lr["h"]), f"{i}'s label is off its line")
                for nid, box in boxes.items():
                    self.assertEqual(overlap(lr, box), 0, f"{i}'s label is on node {nid}")
                for j, other in rects.items():
                    if i < j:
                        self.assertEqual(overlap(lr, other), 0, f"the labels of {i} and {j} overlap")
            Router.assert_routes(self, boxes, links, res, 16)

    def test_a_label_with_no_clear_spot_overlaps_least(self) -> None:
        """Two nodes 60 px apart, a label 100 px wide on the line between them: it overlaps them, but no more than
        it would anywhere else on the line."""
        boxes = {"a": {"x": 0, "y": 0, "w": 180, "h": 80}, "b": {"x": 240, "y": 0, "w": 180, "h": 80}}
        links = [{"id": "a->b", "from": "a", "to": "b", "labelBox": [100, 18]}]
        r = geo(["routeLinks", boxes, links, {"pad": 16}])[0]["a->b"]
        lr = label_rect(r, links[0])
        here = sum(overlap(lr, b) for b in boxes.values())
        (x0, y), (x1, _) = r["points"][0], r["points"][-1]
        for x in range(int(x0), int(x1) + 1, 4):
            there = sum(overlap({"x": x - 50, "y": y - 9, "w": 100, "h": 18}, b) for b in boxes.values())
            self.assertLessEqual(here, there + 1e-6, f"a spot at x {x} overlaps less")

    def test_frame_ports(self) -> None:
        """Inside a system, @left/@right/@top/@bottom are stretches of the frame with no area: edges end on them
        square from inside the frame, spread apart where several share one, and nothing routes round them."""
        frame = {"x": -200, "y": -150, "w": 800, "h": 400}
        boxes = {"client": {"x": 0, "y": 0, "w": 180, "h": 80}, "store": {"x": 300, "y": 120, "w": 180, "h": 80},
                 "@left": {"x": -200, "y": -150, "w": 0, "h": 400}, "@right": {"x": 600, "y": -150, "w": 0, "h": 400},
                 "@top": {"x": -200, "y": -150, "w": 800, "h": 0}, "@bottom": {"x": -200, "y": 250, "w": 800, "h": 0}}
        side = {"@left": "r", "@right": "l", "@top": "b", "@bottom": "t"}
        pairs = [("@left", "client", "cart"), ("client", "@right", "POST /orders"), ("@right", "client", "201 Created"),
                 ("@top", "store", "rows"), ("store", "@bottom", "total"), ("client", "store", "draft")]
        links = [{"id": f"{a}->{b}", "from": a, "to": b, "fromSide": side.get(a), "toSide": side.get(b), "labelBox": [len(t) * 5.9 + 14, 18]}
                 for a, b, t in pairs]
        res = geo(["routeLinks", boxes, links, {"pad": 16, "bounds": frame}])[0]
        self.assertEqual(set(res), {ln["id"] for ln in links})
        inside = lambda p: frame["x"] <= p[0] <= frame["x"] + frame["w"] and frame["y"] <= p[1] <= frame["y"] + frame["h"]
        for ln in links:
            pts = res[ln["id"]]["points"]
            self.assertTrue(all(inside(p) for p in pts), f"{ln['id']} leaves the frame: {pts}")
            for end, port, nxt in ((ln["from"], pts[0], pts[1]), (ln["to"], pts[-1], pts[-2])):
                if end not in side:
                    continue
                box = boxes[end]
                on = port[0] == box["x"] and box["y"] <= port[1] <= box["y"] + box["h"] if box["w"] == 0 else \
                    port[1] == box["y"] and box["x"] <= port[0] <= box["x"] + box["w"]
                self.assertTrue(on, f"{ln['id']} doesn't end on {end}: {port}")
                square = nxt[1] == port[1] if box["w"] == 0 else nxt[0] == port[0]
                self.assertTrue(square, f"{ln['id']} crosses {end} at a slant: {port} → {nxt}")
            lr = label_rect(res[ln["id"]], ln)
            self.assertTrue(inside((lr["x"], lr["y"])) and inside((lr["x"] + lr["w"], lr["y"] + lr["h"])), f"{ln['id']}'s label leaves the frame")
            for nid in ("client", "store"):
                self.assertEqual(overlap(lr, boxes[nid]), 0, f"{ln['id']}'s label is on {nid}")
        right = sorted(res[i]["points"][-1 if i.endswith("@right") else 0][1] for i in ("client->@right", "@right->client"))
        self.assertGreaterEqual(right[1] - right[0], 12, "two edges at @right meet the frame at one point")
        Router.assert_routes(self, boxes, links, res, 16)


class CanvasBuild(unittest.TestCase):
    """build.py's side of routed canvas edges: the router goes into every page with a canvas, and `bend` is gone."""

    def test_pages_with_a_canvas_get_the_router(self) -> None:
        template = build.TEMPLATE.read_text(encoding="utf-8")
        orders = load_json(EXAMPLES / "acme-orders.bluedoc.json")
        self.assertIn("const BoardGeo = (", build.build(orders, template))
        plain = {**orders, "sections": [{"id": "s", "title": "S", "blocks": [{"type": "text", "md": "Acme."}]}]}
        self.assertNotIn("const BoardGeo = (", build.build(plain, template))

    def test_bend_warns(self) -> None:
        doc = load_json(EXAMPLES / "acme-orders.bluedoc.json")
        canvas = next(b for b in build.all_blocks(doc) if b.get("type") == "canvas")
        canvas["edges"][0]["bend"] = 18
        rep = build.validate(doc)
        bends = [w for w in rep.warnings if "bend" in w]
        self.assertEqual(len(bends), 1, rep.warnings)
        self.assertTrue(bends[0].endswith(".edges[0]: `bend` is ignored: edges route themselves"), bends[0])
        self.assertEqual(rep.errors, [])



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
