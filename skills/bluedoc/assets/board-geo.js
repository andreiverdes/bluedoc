/* board-geo.js: the design board's geometry. Pure functions over boxes and links, no DOM. build.py pastes this file
   into design pages at template.html's board-geo slot; the tests run it under node (test_board_geo.py,
   test_board_layout.py).
   - boardLayout(board, links, size): where each artboard sits; the page's copy of build.py's board_layout
   - routeLinks(boxes, links, opts) / reroute(prev, boxes, links, moved, opts): orthogonal connectors around screens
   - tidy(screens, links, entry): the layered layout of Tidy up */
const BoardGeo = (() => {
  // board_layout's spacing, as build.py has it
  const BOARD_GAP = 80, SLIDE_GAP = 280, FLOW_GAP_X = 200, FLOW_GAP_Y = 120;
  // Tidy up: px between depth columns, between screens in a column, between the rows below
  const TIDY_GAP_X = 200, TIDY_GAP_Y = 80, TIDY_ROW_GAP = 120;
  // the router: clearance around screens, corner radius, spacing of parallel segments, the cost of a bend in px, the
  // extra cost per px of running along a screen's padded border, the cost of crossing another route, the least
  // spacing of ends on one side
  const PAD = 24, RADIUS = 12, GAP = 12, BEND = 48, HUG = 0.5, CROSS = 120, PORT_GAP = 24;
  const num = v => typeof v === 'number' && Number.isFinite(v);

  /* ---------- boardLayout: build.py's board_layout, line for line ---------- */
  // {artboard id: {x, y, w, h}} as a Map in board order. size(a) -> [w, h], or null to leave the artboard out.
  // An artboard with x and y sits there. An unplaced slide goes in the slide column (x 0 on a board of only slides,
  // else BOARD_GAP right of everything else; SLIDE_GAP between slides). On a `layout: "flow"` board the unplaced
  // screens reached from board.entry go in columns by link depth (back links ignored; a variant is reached with its
  // source, right under it). Any other unplaced artboard joins a row: its variantOf source's (when placed before it),
  // else the first row below the flow columns (y 0 without them), BOARD_GAP right of the row's rightmost artboard.
  function boardLayout(board, links, size) {
    const rows = [], by = new Map();
    for (const a of board && Array.isArray(board.artboards) ? board.artboards : []) {
      if (!a || typeof a.id !== 'string' || by.has(a.id)) continue;
      const s = size(a);
      if (!s) continue;
      const r = { a, w: s[0], h: s[1], placed: num(a.x) && num(a.y), slide: a.device === 'slide' };
      rows.push(r); by.set(a.id, r);
    }
    const flow = new Map();
    let y0 = 0;
    if (board.layout === 'flow') {
      const reach = flowReach(rows.map(r => ({ id: r.a.id, variantOf: r.a.variantOf, slide: r.slide })), links, board.entry);
      const cols = new Map();
      for (const id of reach.order) {
        if (by.get(id).placed) continue;
        const d = reach.depth.get(id);
        if (!cols.has(d)) cols.set(d, []);
        cols.get(d).push(by.get(id));
      }
      let x = 0, bottom = 0;
      for (const d of [...cols.keys()].sort((p, q) => p - q)) {
        let y = 0, w = 0;
        for (const r of cols.get(d)) { flow.set(r.a.id, [x, y]); bottom = Math.max(bottom, y + r.h); y += r.h + FLOW_GAP_Y; w = Math.max(w, r.w); }
        x += w + FLOW_GAP_X;
      }
      if (flow.size) y0 = bottom + FLOW_GAP_Y;
    }
    const at = new Map(), column = [];
    let onlySlides = true;
    for (const r of rows) {
      const a = r.a;
      onlySlides = onlySlides && r.slide;
      let x, y;
      if (r.placed) { x = a.x; y = a.y; }
      else if (r.slide) { column.push(r); continue; }
      else if (flow.has(a.id)) [x, y] = flow.get(a.id);
      else {
        const src = typeof a.variantOf === 'string' ? at.get(a.variantOf) : null;
        y = src ? src.y : y0;
        let right = null;
        for (const p of at.values()) if (p.y === y) right = Math.max(right === null ? -Infinity : right, p.x + p.w);
        x = right === null ? 0 : right + BOARD_GAP;
      }
      at.set(a.id, { x, y, w: r.w, h: r.h });
    }
    const cx = onlySlides ? 0 : Math.max(...[...at.values()].map(p => p.x + p.w)) + BOARD_GAP;
    let cy = 0;
    for (const r of column) { at.set(r.a.id, { x: cx, y: cy, w: r.w, h: r.h }); cy += r.h + SLIDE_GAP; }
    return new Map(rows.map(r => [r.a.id, at.get(r.a.id)]));
  }

  // breadth-first depth from the entries over every link but back. A screen reached pulls in its unreached variants
  // (board order) at once, at its depth, recursively. nodes: [{id, variantOf, slide}] in board order; slides take
  // no part. {depth: Map id -> depth, order: ids in the order reached, host: Map variant id -> the source that pulled it}
  function flowReach(nodes, links, entry) {
    const ok = new Set(nodes.filter(n => !n.slide).map(n => n.id));
    const depth = new Map(), order = [], host = new Map(), queue = [];
    const reach = (id, d) => {
      depth.set(id, d); order.push(id); queue.push(id);
      for (const n of nodes) if (n.variantOf === id && ok.has(n.id) && !depth.has(n.id)) { host.set(n.id, id); reach(n.id, d); }
    };
    for (const e of Array.isArray(entry) ? entry : []) if (ok.has(e) && !depth.has(e)) reach(e, 0);
    const ls = Array.isArray(links) ? links : [];
    for (let q = 0; q < queue.length; q++) {
      const u = queue[q];
      for (const l of ls) if (l && l.from === u && l.kind !== 'back' && ok.has(l.to) && !depth.has(l.to)) reach(l.to, depth.get(u) + 1);
    }
    return { depth, order, host };
  }

  /* ---------- the router ---------- */
  const SIDE = { r: [1, 0], b: [0, 1], l: [-1, 0], t: [0, -1] };   // outward normal of each side
  const DIR = { r: 0, b: 1, l: 2, t: 3 };                          // A* directions: right, down, left, up
  const DX = [1, 0, -1, 0], DY = [0, 1, 0, -1];
  const rectOf = r => r && num(r.x) && num(r.y) && num(r.w) && num(r.h) ? { x: r.x, y: r.y, w: Math.max(0, r.w), h: Math.max(0, r.h) } : null;
  const grow = (r, p) => ({ x: r.x - p, y: r.y - p, w: r.w + 2 * p, h: r.h + 2 * p });
  const across = s => s === 'l' || s === 'r';               // a left or right side: its ports spread along y
  const sideSpan = (r, s) => across(s) ? [r.y, r.y + r.h] : [r.x, r.x + r.w];
  const onSide = (r, s, c) => s === 'l' ? [r.x, c] : s === 'r' ? [r.x + r.w, c] : s === 't' ? [c, r.y] : [c, r.y + r.h];
  const out = (p, s, d) => [p[0] + SIDE[s][0] * d, p[1] + SIDE[s][1] * d];

  // the sides of a and b that face each other: left/right when they are further apart across than down
  function facing(a, b) {
    const gx = Math.max(b.x - (a.x + a.w), a.x - (b.x + b.w)), gy = Math.max(b.y - (a.y + a.h), a.y - (b.y + b.h));
    if (gx >= gy) return b.x + b.w / 2 >= a.x + a.w / 2 ? ['r', 'l'] : ['l', 'r'];
    return b.y + b.h / 2 >= a.y + a.h / 2 ? ['b', 't'] : ['t', 'b'];
  }

  // place items ({pref, tie, fixed?, c}) along [lo, hi] at least gap apart, in the order of their prefs, each as near
  // its pref as the others allow; a fixed item keeps its c and the others step past it. Sets item.c.
  function spread(items, lo, hi, gap) {
    items.sort((p, q) => p.pref - q.pref || p.tie - q.tie || p.i - q.i);
    const fixed = items.filter(it => it.fixed).map(it => it.c), free = items.filter(it => !it.fixed), n = free.length;
    if (!n) return;
    if (hi - lo < gap * (items.length - 1)) { free.forEach((it, k) => { it.c = n === 1 ? (lo + hi) / 2 : lo + (hi - lo) * k / (n - 1); }); return; }
    const clear = (c, dir) => {   // c stepped past every fixed item closer than gap, in direction dir
      for (let again = true; again;) { again = false; for (const f of fixed) if (Math.abs(c - f) < gap) { c = f + dir * gap; again = true; } }
      return c;
    };
    let prev = -Infinity;
    for (const it of free) { it.c = clear(Math.max(Math.min(Math.max(it.pref, lo), hi), prev + gap), 1); prev = it.c; }
    // then back from hi, as long as that stays above lo
    const back = [];
    let next = Infinity;
    for (let k = n - 1; k >= 0; k--) { next = clear(Math.min(free[k].c, next - gap, hi), -1); back[k] = next; }
    if (back[0] >= lo) free.forEach((it, k) => { it.c = back[k]; });
    else for (const it of free) it.c = Math.min(it.c, hi);
  }

  // each routable link's ends: p0 (on the element, or the screen's border), p1 (p0 carried out past the padding),
  // e1 (in front of the end), e (on the target's border), the sides, and the directions out of p1 and into e
  function portsOf(bm, links, pad, bias) {
    const ps = [], els = new Map();   // screen id -> the rects of its link elements
    (Array.isArray(links) ? links : []).forEach((l, i) => {
      if (!l || typeof l.from !== 'string' || typeof l.to !== 'string' || l.from === l.to) return;
      const A = bm.get(l.from), B = bm.get(l.to);
      if (!A || !B) return;
      let el = l.edge ? null : rectOf(l.src);
      if (el) {
        const x = Math.min(Math.max(el.x, A.x), A.x + A.w), y = Math.min(Math.max(el.y, A.y), A.y + A.h);
        el = { x, y, w: Math.max(0, Math.min(el.w, A.x + A.w - x)), h: Math.max(0, Math.min(el.h, A.y + A.h - y)) };
        if (!els.has(l.from)) els.set(l.from, []);
        els.get(l.from).push(el);
      }
      const [fs, es] = facing(A, B);
      ps.push({ i, id: typeof l.id === 'string' ? l.id : `${l.from}/${l.el}`, from: l.from, to: l.to, A, B, el, ss: fs, es });
    });
    // an element starts on its side that doesn't point away from the target, with the shortest stub to the screen's
    // border; a side other than the one facing the target costs a bend, a stub through another link's element more
    for (const p of ps) if (p.el) {
      const { A, B, el } = p, fs = p.ss;
      const away = { l: B.x >= el.x, r: B.x + B.w <= el.x + el.w, t: B.y >= el.y, b: B.y + B.h <= el.y + el.h };
      const stub = { l: el.x - A.x, r: A.x + A.w - el.x - el.w, t: el.y - A.y, b: A.y + A.h - el.y - el.h };
      const ray = { l: { x: A.x, y: el.y, w: el.x - A.x, h: el.h }, r: { x: el.x + el.w, y: el.y, w: stub.r, h: el.h },
        t: { x: el.x, y: A.y, w: el.w, h: el.y - A.y }, b: { x: el.x, y: el.y + el.h, w: el.w, h: stub.b } };
      let best = Infinity;
      for (const s of ['r', 'b', 'l', 't']) {
        if (away[s]) continue;
        const o = ray[s], blocked = els.get(p.from).some(q => !(q.x === el.x && q.y === el.y && q.w === el.w && q.h === el.h)
          && q.x < o.x + o.w && q.x + q.w > o.x && q.y < o.y + o.h && q.y + q.h > o.y);
        const cost = stub[s] + (s === fs ? 0 : BEND) + (blocked ? 1e6 : 0);
        if (cost < best) { best = cost; p.ss = s; }
      }
    }
    // element starts: spread along the element's side when one element starts several links there
    const groups = new Map(), add = (k, it) => { if (!groups.has(k)) groups.set(k, []); groups.get(k).push(it); };
    for (const p of ps) if (p.el) {
      const [lo, hi] = sideSpan(p.el, p.ss), bc = across(p.ss) ? p.B.y + p.B.h / 2 : p.B.x + p.B.w / 2;
      add(`e\u0000${p.from}\u0000${p.el.x},${p.el.y},${p.el.w},${p.el.h}\u0000${p.ss}`, { p, start: true, pref: (lo + hi) / 2, tie: bc, i: p.i, lo, hi });
    }
    for (const [, items] of groups) { spread(items, items[0].lo, items[0].hi, Math.min(GAP, (items[0].hi - items[0].lo) / Math.max(1, items.length))); for (const it of items) it.p.sc = it.c; }
    // two elements whose stubs to one border run on one line (one behind the other) move GAP / 2 apart, within
    // their elements
    const starts = ps.filter(p => p.el), same = (a, b) => a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;
    for (let a = 0; a < starts.length; a++) for (let b = a + 1; b < starts.length; b++) {
      const p = starts[a], q = starts[b];
      if (p.from !== q.from || p.ss !== q.ss || Math.abs(p.sc - q.sc) >= 1 || same(p.el, q.el)) continue;
      const [pl, ph] = sideSpan(p.el, p.ss), [ql, qh] = sideSpan(q.el, q.ss);
      p.sc = Math.max(pl, Math.min(ph, p.sc - GAP / 2)); q.sc = Math.max(ql, Math.min(qh, q.sc + GAP / 2));
    }
    groups.clear();
    // a screen's side carries the ends of links, the starts of links without an element and the stubs of element
    // starts (fixed where they cross it). Each end wants the coordinate its start leaves from, each border start the
    // one its end arrives at. Sides are settled one after another from the latest values, a few rounds, so both
    // ends of a link come to one line where they can. With bias (from a first routing), a port whose route turns
    // along the side goes to that end of it, the shallower turn outermost, so nested turns don't cross.
    const mid = (r, s) => across(s) ? r.y + r.h / 2 : r.x + r.w / 2;
    const OPP = { l: 'r', r: 'l', t: 'b', b: 't' }, others = [...bm.values()];
    // can link p run straight across at coordinate c: facing sides that both reach c, no other screen in between
    const straightAt = (p, c) => {
      if (p.es !== OPP[p.ss]) return false;
      const [a0, a1] = sideSpan(p.A, p.ss), [b0, b1] = sideSpan(p.B, p.es);
      if (c < Math.max(a0, b0) + PORT_GAP || c > Math.min(a1, b1) - PORT_GAP) return false;
      const line = [onSide(p.A, p.ss, c), onSide(p.B, p.es, c)];
      return !others.some(r => r !== p.A && r !== p.B && pathHits(line, grow(r, pad - 1)));
    };
    for (const p of ps) {
      if (!p.el) p.sc = mid(p.B, p.ss);
      p.ec = mid(p.A, p.es);
      add(`${p.to}\u0000${p.es}`, { p, start: false, i: p.i });
      add(`${p.from}\u0000${p.ss}`, { p, start: true, fixed: !!p.el, c: p.sc, i: p.i });
    }
    for (let round = 0; round < 4; round++) {
      for (const [key, items] of groups) {
        const p = items[0].p, box = items[0].start ? p.A : p.B, s = key.slice(key.lastIndexOf('\u0000') + 1);
        const [lo, hi] = sideSpan(box, s), inset = Math.min(32, (hi - lo) / 2);
        for (const it of items) {
          const p = it.p, turn = bias && bias.has(p.id) ? bias.get(p.id)[it.start ? 0 : 1] : null;
          if (it.fixed) { it.pref = p.sc; it.tie = 0; continue; }
          const far = it.start ? out(onSide(p.B, p.es, p.ec), p.es, pad) : out(onSide(p.A, p.ss, p.sc), p.ss, pad), k = across(s) ? 1 : 0;
          it.pref = far[k];
          it.tie = it.start ? 0 : -Math.abs(far[1 - k] - (k ? p.B.x : p.B.y));
          // turning: to the side's end it turns to (see above), unless a straight line to its far end fits. Left and
          // top sides keep half a PORT_GAP further in, so ports on the facing sides of a channel don't meet on one line.
          if (turn && turn.dir && !straightAt(p, it.pref)) {
            const d = s === 'l' || s === 't' ? PORT_GAP / 2 : 0;
            it.pref = turn.dir > 0 ? hi - inset - d : lo + inset + d;
            it.tie = turn.dir > 0 ? -turn.depth : turn.depth;
          }
        }
        spread(items, lo + inset, hi - inset, PORT_GAP);
        for (const it of items) if (!it.fixed) { if (it.start) it.p.sc = it.c; else it.p.ec = it.c; }
      }
    }
    for (const p of ps) {
      const b = onSide(p.A, p.ss, p.sc);
      p.p0 = p.el ? onSide(p.el, p.ss, p.sc) : b;
      p.p1 = out(b, p.ss, pad);
      p.e = onSide(p.B, p.es, p.ec);
      p.e1 = out(p.e, p.es, pad);
      p.sd = DIR[p.ss]; p.ed = (DIR[p.es] + 2) % 4;
    }
    return ps;
  }

  // the sparse grid: a line through every padded screen edge, the middle of every gap between two of those, and every
  // port. Nodes inside a padded screen, and grid edges through one, are blocked; an edge along a padded screen's
  // border costs HUG more per px, so routes keep to the middle of the channels between screens.
  function makeGrid(obstacles, pts) {
    const lines = (edges, ports) => {
      const e = [...new Set(edges)].sort((a, b) => a - b), mids = [];
      for (let k = 1; k < e.length; k++) mids.push((e[k - 1] + e[k]) / 2);
      return [...new Set([...e, ...mids, ...ports])].sort((a, b) => a - b);
    };
    const xs = lines(obstacles.flatMap(o => [o.x, o.x + o.w]), pts.map(p => p[0]));
    const ys = lines(obstacles.flatMap(o => [o.y, o.y + o.h]), pts.map(p => p[1]));
    const xi = new Map(xs.map((v, k) => [v, k])), yi = new Map(ys.map((v, k) => [v, k]));
    const nx = xs.length, ny = ys.length, n = nx * ny;
    const node = new Uint8Array(n), hEdge = new Uint8Array(n), vEdge = new Uint8Array(n);   // 1 blocked, 2 along a border
    for (const o of obstacles) {
      if (!(o.w > 0 && o.h > 0)) continue;
      const i1 = xi.get(o.x), i2 = xi.get(o.x + o.w), j1 = yi.get(o.y), j2 = yi.get(o.y + o.h);
      for (let j = j1 + 1; j < j2; j++) for (let i = i1; i < i2; i++) { hEdge[j * nx + i] = 1; if (i > i1) node[j * nx + i] = 1; }
      for (let i = i1 + 1; i < i2; i++) for (let j = j1; j < j2; j++) vEdge[j * nx + i] = 1;
      for (let i = i1; i < i2; i++) for (const j of [j1, j2]) if (!hEdge[j * nx + i]) hEdge[j * nx + i] = 2;
      for (let j = j1; j < j2; j++) for (const i of [i1, i2]) if (!vEdge[j * nx + i]) vEdge[j * nx + i] = 2;
    }
    // occH, occV: how many routes run through each node across, and up or down (routes routed so far)
    return { xs, ys, xi, yi, nx, ny, node, hEdge, vEdge, occH: new Int16Array(n), occV: new Int16Array(n),
      g: new Float64Array(n * 4), from: new Int32Array(n * 4), seen: new Int32Array(n * 4), stamp: 0 };
  }

  // add (delta 1) or take back (-1) a route's run through the grid's nodes, its corners excluded
  function occupy(G, pts, delta) {
    const after = (arr, v) => { let lo = 0, hi = arr.length; while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m] <= v) lo = m + 1; else hi = m; } return lo; };
    for (let k = 0; k + 1 < pts.length; k++) {
      const [ax, ay] = pts[k], [bx, by] = pts[k + 1];
      if (ax === bx) {
        const i = G.xi.get(ax);
        if (i === undefined) continue;
        for (let j = after(G.ys, Math.min(ay, by)); j < G.ny && G.ys[j] < Math.max(ay, by); j++) G.occV[j * G.nx + i] += delta;
      } else {
        const j = G.yi.get(ay);
        if (j === undefined) continue;
        for (let i = after(G.xs, Math.min(ax, bx)); i < G.nx && G.xs[i] < Math.max(ax, bx); i++) G.occH[j * G.nx + i] += delta;
      }
    }
  }

  // A* over (node, direction) from s leaving in direction sd to e arriving in direction ed: Manhattan distance plus
  // BEND per turn, HUG per px along a screen's border and CROSS per route crossed, no turning back. The node points
  // of the cheapest path, or null.
  function astar(G, s, sd, e, ed) {
    const { xs, ys, nx, ny, node, hEdge, vEdge, occH, occV, g, from, seen } = G;
    const stamp = ++G.stamp, ex = xs[e % nx], ey = ys[(e / nx) | 0];
    const hf = [], hs = [];   // a binary heap of (f, state)
    const push = (f, st) => {
      let k = hf.length; hf.push(f); hs.push(st);
      while (k) { const up = (k - 1) >> 1; if (hf[up] <= f) break; hf[k] = hf[up]; hs[k] = hs[up]; k = up; }
      hf[k] = f; hs[k] = st;
    };
    const pop = () => {
      const st = hs[0], f = hf.pop(), last = hs.pop(), n = hf.length;
      if (n) {
        let k = 0;
        for (;;) {
          let c = 2 * k + 1;
          if (c >= n) break;
          if (c + 1 < n && hf[c + 1] < hf[c]) c++;
          if (hf[c] >= f) break;
          hf[k] = hf[c]; hs[k] = hs[c]; k = c;
        }
        hf[k] = f; hs[k] = last;
      }
      return st;
    };
    const h = nd => { const x = xs[nd % nx], y = ys[(nd / nx) | 0]; return Math.abs(x - ex) + Math.abs(y - ey) + (x !== ex && y !== ey ? BEND : 0); };
    const s0 = s * 4 + sd;
    seen[s0] = stamp; g[s0] = 0; from[s0] = -1;
    push(h(s), s0);
    while (hf.length) {
      const fTop = hf[0], st = pop(), nd = st >> 2, d = st & 3;
      if (fTop > g[st] + h(nd) + 1e-9) continue;   // a stale entry
      if (nd === e) {
        const pts = [];
        for (let k = st; k !== -1; k = from[k]) pts.push([xs[(k >> 2) % nx], ys[((k >> 2) / nx) | 0]]);
        return pts.reverse();
      }
      const i = nd % nx, j = (nd / nx) | 0;
      for (let dd = 0; dd < 4; dd++) {
        if (dd === (d + 2) % 4) continue;
        const ni = i + DX[dd], nj = j + DY[dd];
        if (ni < 0 || nj < 0 || ni >= nx || nj >= ny) continue;
        const edge = dd === 0 ? hEdge[j * nx + i] : dd === 2 ? hEdge[j * nx + ni] : dd === 1 ? vEdge[j * nx + i] : vEdge[nj * nx + i];
        if (edge === 1) continue;
        const nn = nj * nx + ni;
        if (node[nn] && nn !== e) continue;
        const ns = nn * 4 + dd, len = Math.abs(xs[ni] - xs[i]) + Math.abs(ys[nj] - ys[j]);
        const cost = g[st] + len * (edge === 2 ? 1 + HUG : 1) + (dd !== d ? BEND : 0) + (nn === e && dd !== ed ? BEND : 0)
          + CROSS * (dd & 1 ? occH[nn] : occV[nn]);
        if (seen[ns] === stamp && g[ns] <= cost) continue;
        seen[ns] = stamp; g[ns] = cost; from[ns] = st;
        push(cost + h(nn), ns);
      }
    }
    return null;
  }

  // drop repeated points and the middle of straight runs
  function simplify(pts) {
    const r = [];
    for (const p of pts) {
      const a = r[r.length - 1];
      if (a && a[0] === p[0] && a[1] === p[1]) continue;
      const z = r[r.length - 2];
      if (z && ((z[0] === a[0] && a[0] === p[0]) || (z[1] === a[1] && a[1] === p[1]))) r[r.length - 1] = p; else r.push(p);
    }
    return r;
  }

  // a route from p1 to e1 through the grid; else around the two screens alone; else one elbow
  function routeOne(G, p, pad) {
    const at = q => G.yi.get(q[1]) * G.nx + G.xi.get(q[0]);
    let mid = astar(G, at(p.p1), p.sd, at(p.e1), p.ed);
    if (!mid) {
      const L = makeGrid([grow(p.A, pad), grow(p.B, pad)], [p.p1, p.e1]);
      const at2 = q => L.yi.get(q[1]) * L.nx + L.xi.get(q[0]);
      mid = astar(L, at2(p.p1), p.sd, at2(p.e1), p.ed);
    }
    if (!mid) mid = [p.p1, across(p.ss) ? [p.e1[0], p.p1[1]] : [p.p1[0], p.e1[1]], p.e1];
    return simplify([p.p0, ...mid, p.e]);
  }

  // does the path pass through the inside of rect o
  function pathHits(pts, o) {
    for (let k = 0; k + 1 < pts.length; k++) {
      const [ax, ay] = pts[k], [bx, by] = pts[k + 1];
      if (Math.max(ax, bx) > o.x && Math.min(ax, bx) < o.x + o.w && Math.max(ay, by) > o.y && Math.min(ay, by) < o.y + o.h) return true;
    }
    return false;
  }

  // spread parallel segments that overlap in one channel GAP apart (libavoid's nudging). A channel is the free strip
  // between the nearest screens on either side; its segments spread around their mean, keeping pad / 2 clear of the
  // screens. The first and last segment of a route are tied to its ports and stay. The order is the one in which
  // no segment's turn at an end crosses the other.
  function nudge(routes, rects, pad) {
    // a pass on one axis stretches the other axis' segments, so the axes take turns until nothing moves
    for (let round = 0; round < 8; round++) {
      const v = nudgeAxis(routes, true, rects, pad), h = nudgeAxis(routes, false, rects, pad);
      if (!v && !h) break;
    }
    for (let round = 0; round < 4; round++) {
      const v = separate(routes, true, rects, pad), h = separate(routes, false, rects, pad);
      if (!v && !h) break;
    }
  }
  // what nudging leaves overlapping (it can go round in circles): one of two overlapping segments on one line steps
  // off by half GAPs to the nearest line that is clear of the others and pad / 2 clear of the screens; a port's
  // segment, which can't step off, gets shorter instead, its turn moved to before the other begins
  function separate(routes, vert, rects, pad) {
    const A = vert ? 0 : 1, B = 1 - A, segs = [];
    routes.forEach((pts, li) => {
      for (let k = 0; k + 1 < pts.length; k++) {
        const a = pts[k], b = pts[k + 1];
        if (a[A] === b[A] && a[B] !== b[B]) segs.push({ li, k, c: a[A], lo: Math.min(a[B], b[B]), hi: Math.max(a[B], b[B]), fixed: k === 0 || k === pts.length - 2 });
      }
    });
    const meets = (s, c) => segs.some(t => t !== s && t.li !== s.li && Math.abs(t.c - c) < 1 && s.lo < t.hi && t.lo < s.hi);
    const near = (s, c) => rects.some(r => {
      const r0 = vert ? r.x : r.y, r1 = vert ? r.x + r.w : r.y + r.h, s0 = vert ? r.y : r.x, s1 = vert ? r.y + r.h : r.x + r.w;
      return s.lo < s1 + pad / 2 && s.hi > s0 - pad / 2 && c > r0 - pad / 2 && c < r1 + pad / 2;
    });
    let moved = false;
    for (const s of segs) {
      if (!meets(s, s.c)) continue;
      const pts = routes[s.li];
      if (s.fixed) {
        const first = s.k === 0, port = pts[first ? 0 : pts.length - 1][B], free = first ? 1 : pts.length - 2, nb = first ? 1 : pts.length - 3;
        if (nb <= 0 || nb >= pts.length - 2) continue;
        const t = segs.find(t => t !== s && t.li !== s.li && Math.abs(t.c - s.c) < 1 && s.lo < t.hi && t.lo < s.hi);
        const to = pts[free][B] > port ? t.lo - GAP / 2 : t.hi + GAP / 2;
        if (Math.abs(to - port) < pad / 2 || (to - port) * (pts[free][B] - port) <= 0) continue;
        pts[nb][B] = to; pts[nb + 1][B] = to;
        moved = true;
        continue;
      }
      const to = [];
      for (let m = 1; m <= 8; m++) to.push(s.c + m * GAP / 2, s.c - m * GAP / 2);
      const c = to.find(v => !meets(s, v) && !near(s, v));
      if (c === undefined) continue;
      pts[s.k][A] = c; pts[s.k + 1][A] = c; s.c = c;
      moved = true;
    }
    return moved;
  }
  function nudgeAxis(routes, vert, rects, pad) {
    const A = vert ? 0 : 1, B = 1 - A, segs = [];
    routes.forEach((pts, li) => {
      for (let k = 0; k + 1 < pts.length; k++) {
        const a = pts[k], b = pts[k + 1];
        if (a[A] !== b[A] || a[B] === b[B]) continue;
        const c = a[A], lo = Math.min(a[B], b[B]), hi = Math.max(a[B], b[B]), loEnd = a[B] < b[B] ? k : k + 1;
        // which way the route turns at an end: toward smaller (-1) or larger (1) coordinates
        const turn = nb => { const q = pts[nb]; return q ? Math.sign(q[A] - c) : 0; };
        let neg = -Infinity, pos = Infinity;
        for (const r of rects) {
          const r0 = vert ? r.x : r.y, r1 = vert ? r.x + r.w : r.y + r.h, s0 = vert ? r.y : r.x, s1 = vert ? r.y + r.h : r.x + r.w;
          if (s1 <= lo || s0 >= hi) continue;
          if (r1 <= c) neg = Math.max(neg, r1); else if (r0 >= c) pos = Math.min(pos, r0);
        }
        const seg = { li, k, c, lo, hi, neg, pos, fixed: k === 0 || k === pts.length - 2,
          tLo: turn(loEnd === k ? k - 1 : k + 2), tHi: turn(loEnd === k ? k + 2 : k - 1) };
        segs.push(seg);
      }
    });
    // a before b (the smaller coordinate) when that keeps the turn at a shared end from crossing the other; where an
    // end of each meets at one coordinate and they turn apart, the one turning toward smaller coordinates first, else
    // the two turns would overlap there
    const forced = (a, b) => {   // a must come before b
      for (const [x, tx] of [[a.lo, a.tLo], [a.hi, a.tHi]]) for (const [y, ty] of [[b.lo, b.tLo], [b.hi, b.tHi]]) if (x === y && tx < 0 && ty > 0) return true;
      return false;
    };
    // two segments further apart than 2 GAP keep their order: swapping them would move them far
    const cmp = (a, b) => {
      if (forced(a, b)) return -1;
      if (forced(b, a)) return 1;
      if (Math.abs(a.c - b.c) < 2 * GAP) {
        if (a.lo !== b.lo) { const o = a.lo > b.lo ? a : b; if (o.tLo) return (o === b) === (o.tLo > 0) ? -1 : 1; }
        if (a.hi !== b.hi) { const o = a.hi < b.hi ? a : b; if (o.tHi) return (o === b) === (o.tHi > 0) ? -1 : 1; }
      }
      return a.c - b.c || a.li - b.li;
    };
    // groups: segments whose extents overlap on one line, or in one channel (one open on a side: within pad of each other)
    const up = segs.map((_, k) => k), find = k => { while (up[k] !== k) k = up[k] = up[up[k]]; return k; };
    for (let p = 0; p < segs.length; p++) for (let q = p + 1; q < segs.length; q++) {
      const s = segs[p], t = segs[q];
      if (!(s.lo <= t.hi && t.lo <= s.hi)) continue;
      if (Math.abs(s.c - t.c) < 0.01 || (s.neg === t.neg && s.pos === t.pos && (Number.isFinite(s.neg) && Number.isFinite(s.pos) || Math.abs(s.c - t.c) <= pad))) up[find(p)] = find(q);
    }
    const groups = new Map();
    segs.forEach((s, k) => { const r = find(k); if (!groups.has(r)) groups.set(r, []); groups.get(r).push(s); });
    let moved = false;
    for (const grp of groups.values()) {
      if (grp.length < 2 || grp.every(s => s.fixed) || new Set(grp.map(s => s.li)).size < 2) continue;
      grp.sort((p, q) => p.c - q.c || p.li - q.li);
      for (let m = 1; m < grp.length; m++) for (let q = m; q > 0 && cmp(grp[q - 1], grp[q]) > 0; q--) [grp[q - 1], grp[q]] = [grp[q], grp[q - 1]];
      // where two overlap and turn apart at a shared end, the order is forced: move the later one ahead
      for (let round = 0, again = true; again && round < grp.length; round++) {
        again = false;
        for (let p = 0; p < grp.length && !again; p++) for (let q = p + 1; q < grp.length; q++) {
          if (forced(grp[q], grp[p])) { grp.splice(p, 0, grp.splice(q, 1)[0]); again = true; break; }
        }
      }
      // in that order, step apart, each as near where it is as the others allow (stack); then inside the free strip
      // the group shares. Too narrow for n segments 2 px apart, they spread GAP apart regardless.
      const n = grp.length, lo = Math.max(...grp.map(s => s.neg)) + pad / 2, hi = Math.min(...grp.map(s => s.pos)) - pad / 2;
      const fits = hi - lo >= 2 * (n - 1), step = fits ? Math.min(GAP, (hi - lo) / (n - 1)) : GAP;
      const at = stack(grp.map(() => 0), grp.map(s => s.c), step);
      if (fits) { const sh = Math.max(lo - at[0], Math.min(0, hi - at[n - 1])); for (let k = 0; k < n; k++) at[k] += sh; }
      // a port's segment stays where it is; a segment whose slot lands on another overlapping one (a port's, or
      // one clamped to the strip's edge) steps off by half steps, inside the strip, until it is clear
      const inStrip = v => { v = Math.round(v * 100) / 100; return fits ? Math.max(lo, Math.min(hi, v)) : v; };
      const vals = grp.map((s, k) => s.fixed ? s.c : inStrip(at[k]));
      const half = Math.max(step, 2) / 2;
      const clash = (k, v) => grp.some((t, j) => j !== k && Math.abs(vals[j] - v) < 1 && grp[k].lo < t.hi && t.lo < grp[k].hi);
      grp.forEach((s, k) => {
        if (s.fixed || !clash(k, vals[k])) return;
        for (const m of [1, -1, 2, -2, 3, -3, 4, -4]) {
          const v = inStrip(vals[k] + m * half);
          if (!clash(k, v)) { vals[k] = v; break; }
        }
      });
      grp.forEach((s, k) => {
        if (s.fixed || Math.abs(vals[k] - s.c) < 0.01) return;
        routes[s.li][s.k][A] = vals[k]; routes[s.li][s.k + 1][A] = vals[k];
        moved = true;
      });
    }
    return moved;
  }

  // the path with rounded corners: radius RADIUS, less where a segment is short (half of it, all of an end one)
  function pathD(pts) {
    const f = v => Math.round(v * 10) / 10, n = pts.length - 1;
    let d = `M${f(pts[0][0])} ${f(pts[0][1])}`;
    for (let k = 1; k < n; k++) {
      const a = pts[k - 1], c = pts[k], b = pts[k + 1];
      const li = Math.abs(c[0] - a[0]) + Math.abs(c[1] - a[1]), lo = Math.abs(b[0] - c[0]) + Math.abs(b[1] - c[1]);
      const r = Math.min(RADIUS, k === 1 ? li : li / 2, k + 1 === n ? lo : lo / 2);
      if (!(r > 0)) { d += `L${f(c[0])} ${f(c[1])}`; continue; }
      const ix = Math.sign(c[0] - a[0]), iy = Math.sign(c[1] - a[1]), ox = Math.sign(b[0] - c[0]), oy = Math.sign(b[1] - c[1]);
      d += `L${f(c[0] - ix * r)} ${f(c[1] - iy * r)}A${f(r)} ${f(r)} 0 0 ${ix * oy - iy * ox > 0 ? 1 : 0} ${f(c[0] + ox * r)} ${f(c[1] + oy * r)}`;
    }
    return d + `L${f(pts[n][0])} ${f(pts[n][1])}`;
  }

  // the middle of the longest segment: where the action label goes
  function labelAt(pts) {
    let best = -1, at = { x: pts[0][0], y: pts[0][1] };
    for (let k = 0; k + 1 < pts.length; k++) {
      const a = pts[k], b = pts[k + 1], len = Math.abs(b[0] - a[0]) + Math.abs(b[1] - a[1]);
      if (len > best) { best = len; at = { x: (a[0] + b[0]) / 2, y: (a[1] + b[1]) / 2 }; }
    }
    return at;
  }

  // {link id: {d, points, label: {x, y}, start, end, raw}} for every link between two boxes (none for back links or
  // a link to its own screen). boxes: Map or object, id -> {x, y, w, h} (what routes keep clear of). links:
  // [{id?, from, to, kind, el, src?, edge?}]; id defaults to `from/el`; src is the element's rect in board px (null:
  // the link starts on the screen's border, as an `edge` link always does). points: the corners, from the element
  // (or border) to the target's border, the last segment square to it; d: the same with rounded corners; start,
  // end: the sides used ('l', 'r', 't', 'b'); raw: the route before nudging, which reroute reuses.
  function routeLinks(boxes, links, opts) { return reroute(null, boxes, links, null, opts); }

  // routeLinks again after the boxes in `moved` (ids) moved, from the previous result: only links whose ends
  // changed or whose route touches a moved box are routed anew; the rest keep their route. With no prev, all are.
  function reroute(prev, boxes, links, moved, opts) {
    const pad = opts && num(opts.pad) ? opts.pad : PAD;
    const bm = new Map();
    for (const [id, r] of boxes instanceof Map ? boxes : Object.entries(boxes || {})) { const b = rectOf(r); if (b) bm.set(id, b); }
    const mv = new Set(moved || []), padded = [...bm.values()].map(b => grow(b, pad));
    const hitsMoved = raw => [...mv].some(id => bm.has(id) && pathHits(raw.slice(1, -1), grow(bm.get(id), pad - 1)));
    const same = (a, b) => a[0] === b[0] && a[1] === b[1];
    // the raw route of each link: the old one (from `old`) while its ends hold and no moved box is in its way
    const routeAll = (ps, old) => {
      const todo = [], raws = new Map();
      for (const p of ps) {
        const o = old && old[p.id];
        const keep = o && o.raw && o.start === p.ss && o.end === p.es && same(o.raw[0], p.p0) && same(o.raw[o.raw.length - 1], p.e)
          && !mv.has(p.from) && !mv.has(p.to) && !hitsMoved(o.raw);
        if (keep) raws.set(p.id, o.raw); else todo.push(p);
      }
      if (todo.length) {
        const G = makeGrid(padded, todo.flatMap(p => [p.p1, p.e1]));
        for (const p of ps) if (!todo.includes(p)) occupy(G, raws.get(p.id), 1);
        for (const p of todo) { const r = routeOne(G, p, pad); raws.set(p.id, r); occupy(G, r, 1); }
        // rip up and reroute: each once more, against all the others
        for (const p of todo) { occupy(G, raws.get(p.id), -1); const r = routeOne(G, p, pad); raws.set(p.id, r); occupy(G, r, 1); }
      }
      return raws;
    };
    // ports placed knowing which way each route turns: from the previous result, else from a first routing
    let ref = prev;
    if (!ref) {
      const ps0 = portsOf(bm, links, pad, null), raws0 = routeAll(ps0, null);
      ref = {};
      for (const p of ps0) ref[p.id] = { raw: raws0.get(p.id), start: p.ss, end: p.es };
    }
    const ps = portsOf(bm, links, pad, turnsOf(ref));
    const raws = routeAll(ps, prev);
    const routes = ps.map(p => raws.get(p.id).map(q => q.slice()));
    nudge(routes, [...bm.values()], pad);
    const res = {};
    ps.forEach((p, k) => {
      const pts = simplify(routes[k]);
      res[p.id] = { d: pathD(pts), points: pts, label: labelAt(pts), start: p.ss, end: p.es, raw: raws.get(p.id) };
    });
    return res;
  }

  // id -> [the turn after the start, the turn before the end] of each route in res ({id: {raw, start, end}}): the
  // direction along its side it turns to (-1, 1; 0 straight on) and how far from the side
  function turnsOf(res) {
    const turns = new Map();
    for (const [id, r] of Object.entries(res || {})) {
      const raw = r && r.raw;
      if (!Array.isArray(raw) || raw.length < 2 || !SIDE[r.start] || !SIDE[r.end]) continue;
      const turn = (side, at, corner, next) => {
        if (!next) return { dir: 0, depth: 0 };
        const k = across(side) ? 1 : 0;
        return { dir: Math.sign(next[k] - corner[k]), depth: Math.abs(corner[1 - k] - at[1 - k]) };
      };
      const n = raw.length;
      turns.set(id, [turn(r.start, raw[0], raw[1], raw[2]), turn(r.end, raw[n - 1], raw[n - 2], raw[n - 3])]);
    }
    return turns;
  }

  /* ---------- tidy: the layered layout of Tidy up ---------- */
  // {screen id: [x, y]} for every screen but slides (they keep their column). screens: [{id, w, h, device?,
  // variantOf?}] in board order; links: [{from, to, kind}]; entry: the board's entry ids.
  // 1 layer: depth from the entries, as the flow layout (back links ignored; a variant rides with its source).
  // 2 order: within each layer, by the median position of the neighbours in the layer before (down sweeps) or after
  //   (up sweeps), 8 sweeps, keeping the order with the fewest crossings; then swap neighbours while that cuts crossings.
  // 3 place: layers become columns TIDY_GAP_X apart; screens stack TIDY_GAP_Y apart, each column shifted toward the
  //   median of its sources without overlap; variants stack under their source.
  // 4 group: screens no entry reaches go in rows below, one per device, BOARD_GAP apart.
  function tidy(screens, links, entry) {
    const list = [], by = new Map();
    for (const s of Array.isArray(screens) ? screens : []) {
      if (!s || typeof s.id !== 'string' || by.has(s.id) || !num(s.w) || !num(s.h)) continue;
      const r = { id: s.id, w: s.w, h: s.h, device: s.device, variantOf: s.variantOf, slide: s.device === 'slide' };
      list.push(r); by.set(r.id, r);
    }
    const reach = flowReach(list, links, entry);
    // units: a reached screen with the variants it pulled in, stacked under it
    const unitOf = new Map(), units = [];
    for (const id of reach.order) {
      const hst = reach.host.get(id);
      if (hst !== undefined) { const u = unitOf.get(hst); u.members.push(by.get(id)); unitOf.set(id, u); continue; }
      const u = { members: [by.get(id)], depth: reach.depth.get(id), up: [], down: [], same: [] };
      units.push(u); unitOf.set(id, u);
    }
    const layers = [];
    for (const u of units) (layers[u.depth] = layers[u.depth] || []).push(u);
    for (let d = 0; d < layers.length; d++) if (!layers[d]) layers[d] = [];
    for (const l of Array.isArray(links) ? links : []) {
      if (!l || l.kind === 'back') continue;
      const a = unitOf.get(l.from), b = unitOf.get(l.to);
      if (!a || !b || a === b) continue;
      if (a.depth === b.depth) { a.same.push(b); continue; }
      if (Math.abs(a.depth - b.depth) !== 1) continue;
      const [lo, hi] = a.depth < b.depth ? [a, b] : [b, a];
      lo.down.push(hi); hi.up.push(lo);
    }
    const posIn = () => { for (const layer of layers) layer.forEach((u, k) => { u.pos = k; }); };
    const cross = d => {   // crossings between layer d and d + 1
      const es = [];
      for (const u of layers[d]) for (const v of u.down) es.push([u.pos, v.pos]);
      let n = 0;
      for (let p = 0; p < es.length; p++) for (let q = p + 1; q < es.length; q++) if ((es[p][0] - es[q][0]) * (es[p][1] - es[q][1]) < 0) n++;
      return n;
    };
    const total = () => { let n = 0; for (let d = 0; d + 1 < layers.length; d++) n += cross(d); return n; };
    const median = vs => { const s = vs.map(v => v.pos).sort((a, b) => a - b), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
    posIn();
    let best = total(), bestOrder = layers.map(l => l.slice());
    for (let sweep = 0; sweep < 8 && best > 0; sweep++) {
      const down = sweep % 2 === 0;
      for (let k = 1; k < layers.length; k++) {
        const d = down ? k : layers.length - 1 - k;
        const key = new Map(layers[d].map(u => { const vs = down ? u.up : u.down; return [u, vs.length ? median(vs) : u.pos]; }));
        layers[d] = layers[d].map((u, k2) => [u, k2]).sort((p, q) => key.get(p[0]) - key.get(q[0]) || p[1] - q[1]).map(p => p[0]);
        posIn();
      }
      const n = total();
      if (n < best) { best = n; bestOrder = layers.map(l => l.slice()); }
    }
    bestOrder.forEach((l, d) => { layers[d] = l; });
    posIn();
    // greedy switch: swap neighbours while that cuts crossings, or keeps them and brings screens linked within the
    // layer closer together (fewer screens for their connector to go around)
    const span = d => { let n = 0; for (const u of layers[d]) for (const v of u.same) n += Math.abs(u.pos - v.pos); return n; };
    for (let round = 0, better = true; better && round < 20; round++) {
      better = false;
      for (let d = 0; d < layers.length; d++) {
        const here = () => (d > 0 ? cross(d - 1) : 0) + (d + 1 < layers.length ? cross(d) : 0);
        for (let k = 0; k + 1 < layers[d].length; k++) {
          const c0 = here(), s0 = span(d);
          [layers[d][k], layers[d][k + 1]] = [layers[d][k + 1], layers[d][k]]; posIn();
          const c1 = here();
          if (c1 < c0 || (c1 === c0 && span(d) < s0)) better = true;
          else { [layers[d][k], layers[d][k + 1]] = [layers[d][k + 1], layers[d][k]]; posIn(); }
        }
      }
    }
    // place
    const at = {};
    let x = 0, top = Infinity, bottom = -Infinity;
    const placed = [];
    for (let d = 0; d < layers.length; d++) {
      const layer = layers[d];
      if (!layer.length) continue;
      for (const u of layer) { u.H = u.members.reduce((s, m) => s + m.h, 0) + TIDY_GAP_Y * (u.members.length - 1); u.W = Math.max(...u.members.map(m => m.w)); }
      let want, acc = 0;
      if (d === 0 || layer.every(u => !u.up.length)) want = layer.map(u => { const y = acc; acc += u.H + TIDY_GAP_Y; return y; });
      else want = layer.map(u => { const cs = u.up.map(v => v.y + v.H / 2).sort((a, b) => a - b), m = cs.length >> 1; return (cs.length % 2 ? cs[m] : (cs[m - 1] + cs[m]) / 2) - u.H / 2; });
      const tops = stack(layer.map(u => u.H), want, TIDY_GAP_Y);
      layer.forEach((u, k) => { u.x = x; u.y = tops[k]; placed.push(u); top = Math.min(top, u.y); bottom = Math.max(bottom, u.y + u.H); });
      x += Math.max(...layer.map(u => u.W)) + TIDY_GAP_X;
    }
    for (const u of placed) {
      let y = u.y - top;
      for (const m of u.members) { at[m.id] = [Math.round(u.x), Math.round(y)]; y += m.h + TIDY_GAP_Y; }
    }
    // the rest: one row per device, in board order
    let rowY = placed.length ? Math.round(bottom - top) + TIDY_ROW_GAP : 0;
    const rows = new Map();
    for (const r of list) if (!r.slide && !(r.id in at)) { const k = String(r.device); if (!rows.has(k)) rows.set(k, []); rows.get(k).push(r); }
    for (const row of rows.values()) {
      let rx = 0;
      for (const r of row) { at[r.id] = [rx, rowY]; rx += Math.round(r.w) + BOARD_GAP; }
      rowY += Math.round(Math.max(...row.map(r => r.h))) + TIDY_ROW_GAP;
    }
    return at;
  }

  // tops for boxes of heights hs in this order, gap apart, as near the wanted tops as they can be (least squares:
  // overlapping runs merge into blocks that sit at their members' mean)
  function stack(hs, want, gap) {
    const blocks = [];
    hs.forEach((h, k) => {
      let b = { first: k, n: 1, sum: want[k], len: h };
      for (;;) {
        const p = blocks[blocks.length - 1];
        if (!p || p.sum / p.n + p.len + gap <= b.sum / b.n) break;
        const shift = p.len + gap;
        b = { first: p.first, n: p.n + b.n, sum: p.sum + b.sum - b.n * shift, len: p.len + gap + b.len };
        blocks.pop();
      }
      blocks.push(b);
    });
    const tops = [];
    for (const b of blocks) { let y = b.sum / b.n; for (let k = b.first; k < b.first + b.n; k++) { tops.push(y); y += hs[k] + gap; } }
    return tops;
  }

  return { boardLayout, routeLinks, reroute, tidy };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = BoardGeo;
