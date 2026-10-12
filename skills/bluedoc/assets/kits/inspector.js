/* bluedoc inspector: runs inside every design screen frame (opaque-origin sandbox) and talks to the design page. On a
   website's live page, serve.py's dev-server proxy injects it as <script src data-parents="<origin> …">: it posts to
   those page origins, names elements from the nearest unique id as well, and roots the page's IntersectionObservers in
   the frame's own viewport.
   Page -> frame: {bd:'mode', mode}, {bd:'tokens', theme, motion}, {bd:'view', sketch, reduced, paused}, {bd:'locate', sels},
     {bd:'sections', sels}   a website page's section selectors: hover and pick report the innermost one holding the element
     {bd:'edits', list}      list: [{sel, edits: [{sel?, text? | html?}]}]: the variants shown in place. Each edit sets the
                             text or the HTML of the element its sel finds in its section (the section itself without
                             sel); the next list first puts back what the last one changed
     {bd:'reveal', sel}      scroll the element to the top of the frame
     {bd:'page', full, vh}   a website page's view: full (Full page: the frame grows to the document and never scrolls)
                             pins every viewport height to vh px, the design viewport's (--bd-vh, innerHeight,
                             visualViewport.height, the root's clientHeight); else (Viewport) the frame's own. The
                             frame's name ('bd-page full 900' | 'bd-page view 900') says the same before the page loads.
   Frame -> page, exactly 4 types, strings capped at 200 chars:
     {bd:'ready', w, h, vw, vh, byFrame, fallback, rects, navs, named}   on load, on resize, on scroll, after each
                                       locate and on any change of the document's size (fonts, images, DOM); vw: the
                                       frame's width; vh: the pinned height (null: none). h: the document's height;
                                       pinned, the height the frame should take (at least vh). byFrame: nothing in the
                                       document changed since the last report, only the frame. navs: {name: rect | null}
                                       for up to 50 [data-nav] elements (null: hidden, a gesture link); named: the same
                                       for up to 100 [data-bd] elements; rects: the last locate's selectors, measured again
     {bd:'hover', sel, name, tag, text, rect, sec} | {bd:'hover', sel: null}
     {bd:'pick',  sel, name, tag, text, rect, sec, shift}   sel null = the whole artboard; sec: the section's index or null
     {bd:'nav',   names}   in interact mode, a click: the data-bd names of the clicked element and its named ancestors,
                           innermost first (at most 8). The click itself still runs. The page follows the first name
                           that has a link from this screen (its links, drafts included), so a forged name moves nothing.
   sel: the shortest unique chain of data-bd names ('submit', 'form/submit'), else a CSS path with '>' and no spaces
   from the nearest uniquely named ancestor ('[data-bd="login"]>h1:nth-of-type(1)'), on a live page also from the
   nearest unique id ('#hero-title', '#faq>details:nth-of-type(2)'), or from body. */
(() => {
  'use strict';
  const doc = document, root = doc.documentElement;
  const NAME = /^[A-Za-z0-9_-]+$/, TOKEN_KEY = /^[a-z][a-z0-9-]*$/, BAD_VALUE = /[;{}<>\\]|url\(/i;
  const MOTION_VARS = { fast: '--dur-fast', base: '--dur-base', slow: '--dur-slow', ease: '--ease' };
  const OWN = new Set(['bd-notice', 'bd-kit-svg', 'bd-inspect']);
  // a live page: the page origins the proxy named (its own origin is the proxy's, not the page's)
  const me = doc.currentScript, PARENTS = ((me && me.dataset.parents) || '').split(' ').filter(o => /^http:\/\/[\w.[\]:-]+$/.test(o));
  const LIVE = PARENTS.length > 0;
  const targets = LIVE ? PARENTS : [/^https?:$/.test(location.protocol) ? location.protocol + '//' + location.host : '*'];
  const cap = s => (s == null ? null : String(s).replace(/\s+/g, ' ').trim().slice(0, 200));
  const post = msg => { for (const t of targets) try { parent.postMessage(msg, t); } catch (e) { /* the page went away */ } };
  let mode = 'view', outline = null, hovered = null, sections = [], located = [];
  const changed = [];   // [element, its innerHTML before an edit], in the order the edits ran
  const idSel = el => (el.id && typeof CSS !== 'undefined' ? '#' + CSS.escape(el.id) : null);

  const rectOf = r => ({ x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) });
  const nameOf = el => { const n = el.getAttribute && el.getAttribute('data-bd'); return n && NAME.test(n) ? n : null; };
  const count = sel => { try { return doc.querySelectorAll(sel).length; } catch (e) { return 0; } };
  const chainSel = names => names.map(n => '[data-bd="' + n + '"]').join(' ');
  const own = el => { for (let n = el; n && n !== doc.body; n = n.parentElement) if (OWN.has(n.id)) return true; return false; };

  /* Full page (a website page's view: {bd:'page'}, the frame's name): the frame grows to the document, so every height
     that follows the viewport's is pinned to the design viewport's, pin px. Viewport units go through --bd-vh: serve.py's
     proxy rewrote the site's HTML and CSS (pin_viewport_units, keep the two alike) and here the same rewrite reaches
     what it never saw (a mockup's compiled Tailwind, styles a script adds or sets). innerHeight, visualViewport.height
     and the root's clientHeight answer pin. pin 0: Viewport, every value the frame's own. */
  let pin = 0, probed = -1, mo = null, reportT = 0, stirred = true;
  const VU = /(?<!--bd-vh)(?<!--bd-vh,)(^|[^\w.-])(-?)(\d*\.?\d+(?:e[+-]?\d+)?)[sld]?(vh|vb|vmin|vmax)\b(?![^{};]*\{)/gi, HAS_VU = new RegExp(VU.source, 'i');
  const pinUnits = s => s.replace(VU, (m, pre, sign, n, unit) => {
    const u = unit.toLowerCase(), v = u === 'vh' || u === 'vb' ? 'var(--bd-vh, 1vh)' : u.slice(1) + '(1vw, var(--bd-vh, 1vh))';
    return pre + 'calc(' + sign + n + ' * ' + v + ')';
  });
  function pinRules(rules) {
    for (const r of rules) {
      if (r.style && HAS_VU.test(r.style.cssText)) r.style.cssText = pinUnits(r.style.cssText);
      if (r.cssRules) pinRules(r.cssRules);   // @media, @supports, @layer, @container, nested rules, @keyframes
      if (r.styleSheet) { try { pinRules(r.styleSheet.cssRules); } catch (e) { /* another origin's */ } }   // @import
    }
  }
  function pinSheets() {
    for (const s of [...doc.styleSheets, ...(doc.adoptedStyleSheets || [])]) { let rs = null; try { rs = s.cssRules; } catch (e) { /* another origin's */ } if (rs) pinRules(rs); }
  }
  // through the CSSOM, which a site's CSP without 'unsafe-inline' still allows
  const pinAttr = el => { const v = el.getAttribute && el.getAttribute('style'); if (v && HAS_VU.test(v) && el.style) el.style.cssText = pinUnits(v); };
  const pinAttrs = n => { pinAttr(n); if (n.querySelectorAll) for (const el of n.querySelectorAll('[style]')) pinAttr(el); };
  const VH_VAR = () => pin / 100 + 'px';
  const realCH = Object.getOwnPropertyDescriptor(Element.prototype, 'clientHeight');
  const frameH = () => realCH.get.call(root);
  const shim = (o, prop, real) => {
    try { if (real && real.get && real.configurable) Object.defineProperty(o, prop, { configurable: true, enumerable: true, get() { return pin || real.get.call(o); }, set: real.set }); } catch (e) { /* not ours to change */ }
  };
  shim(window, 'innerHeight', Object.getOwnPropertyDescriptor(window, 'innerHeight'));
  if (window.visualViewport) shim(visualViewport, 'height', Object.getOwnPropertyDescriptor(Object.getPrototypeOf(visualViewport), 'height'));
  shim(root, 'clientHeight', realCH);
  // what the page adds later: its style elements and stylesheets, style attributes; the root's --bd-vh kept
  function watch() {
    if (mo || typeof MutationObserver !== 'function') return;
    mo = new MutationObserver(recs => {
      if (!pin) return;
      let sheets = false;
      stirred = true;
      for (const r of recs) {
        if (r.type === 'attributes') {
          if (r.target === root && root.style.getPropertyValue('--bd-vh').trim() !== VH_VAR()) root.style.setProperty('--bd-vh', VH_VAR());
          pinAttr(r.target);
          continue;
        }
        if (r.target.nodeName === 'STYLE') sheets = true;
        for (const n of r.addedNodes) if (n.nodeType === 1) { if (n.nodeName === 'STYLE' || n.nodeName === 'LINK') sheets = true; pinAttrs(n); }
      }
      if (sheets) pinSheets();
    });
    mo.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['style'] });
  }
  function setPin(v) {
    v = Number.isInteger(v) && v >= 240 && v <= 3840 ? v : 0;
    if (v === pin) return;
    pin = v; probed = -1;
    if (!pin) { root.style.removeProperty('--bd-vh'); return; }
    root.style.setProperty('--bd-vh', VH_VAR());
    watch(); pinSheets(); pinAttrs(root);
  }
  // Full page: the height the frame should take. The document's scroll height when that is taller than the frame; else
  // its content's bottom (body's children, then body's padding and margin), at least pin. A shorter height is offered
  // once per value, so a page whose overflow that misses doesn't bounce between the two.
  function pageHeight() {
    const H = frameH(), b = doc.body, sh = Math.max(root.scrollHeight, b ? b.scrollHeight : 0);
    if (sh > H + 1 || !b) return Math.max(sh, pin);
    const px = (cs, ...ks) => ks.reduce((t, k) => t + (parseFloat(cs[k]) || 0), 0);
    let bottom = 0;
    for (const el of b.children) {
      if (OWN.has(el.id)) continue;
      const cs = getComputedStyle(el);
      if (cs.position !== 'fixed' && cs.display !== 'none') bottom = Math.max(bottom, el.getBoundingClientRect().bottom + px(cs, 'marginBottom'));
    }
    const h = Math.max(pin, Math.ceil(bottom + scrollY + px(getComputedStyle(b), 'paddingBottom', 'borderBottomWidth', 'marginBottom') + px(getComputedStyle(root), 'paddingBottom', 'borderBottomWidth')));
    if (h >= H - 1 || h === probed) return H;
    probed = h;
    return h;
  }
  // stirred: the document changed (DOM, a load, fonts) since the last report; a report without it follows the frame alone
  const report = () => { clearTimeout(reportT); reportT = setTimeout(() => ready(measure()), 120); };
  const stir = () => { stirred = true; report(); };

  /* A live page's IntersectionObserver without a root watches the frame's own viewport (root: document), not the part
     of the frame the board shows: else zooming or panning the board reads to the page as a scroll (its nav turns to
     glass, reveals fire), and a tall frame restyled at a new scale flashes blank. Percent margins are of the design
     viewport's height and the frame's width, as in Full page the frame's viewport is the whole page. */
  if (LIVE && typeof IntersectionObserver === 'function' && typeof Proxy === 'function') {
    const pct = (v, size) => { const m = /^(-?\d*\.?\d+)%$/.exec(v); return m ? +m[1] * size / 100 + 'px' : v; };
    const marginPx = rm => {
      const v = String(rm).trim().split(/\s+/);
      if (v.length > 4 || !v.every(s => /^-?\d*\.?\d+(px|%)?$/.test(s))) return rm;   // the browser's to refuse
      const [t, r = t, b = t, l = r] = v, H = pin || innerHeight;
      return [pct(t, H), pct(r, innerWidth), pct(b, H), pct(l, innerWidth)].join(' ');
    };
    window.IntersectionObserver = new Proxy(IntersectionObserver, { construct(IO, [cb, opts], nt) {
      const o = opts && typeof opts === 'object' ? opts : {};
      if (o.root != null) return Reflect.construct(IO, [cb, opts], nt);
      return Reflect.construct(IO, [cb, { ...o, root: doc, ...('rootMargin' in o ? { rootMargin: marginPx(o.rootMargin) } : {}) }], nt);
    } });
  }
  const startView = /^bd-page (full|view) (\d{3,4})$/.exec(window.name || '');   // the page's view before it can say so
  if (startView && startView[1] === 'full') setPin(+startView[2]);

  function selOf(el) {
    if (!el || el === doc.body || el === root || !doc.body.contains(el)) return null;
    const self = nameOf(el);
    if (self) {
      const chain = [self];
      for (let a = el.parentElement; count(chainSel(chain)) > 1 && a && a !== doc.body; a = a.parentElement) {
        const n = nameOf(a);
        if (n) chain.unshift(n);
      }
      if (count(chainSel(chain)) === 1) return cap(chain.join('/'));
    }
    if (LIVE && idSel(el) && count(idSel(el)) === 1) return cap(idSel(el));
    const steps = [];
    let n = el, anchor = 'body';
    for (; n && n !== doc.body; n = n.parentElement) {
      const nm = nameOf(n);
      if (n !== el && nm && count('[data-bd="' + nm + '"]') === 1) { anchor = '[data-bd="' + nm + '"]'; break; }
      if (n !== el && LIVE && idSel(n) && count(idSel(n)) === 1) { anchor = idSel(n); break; }
      const tag = n.tagName.toLowerCase();
      let i = 1;
      for (let s = n.previousElementSibling; s; s = s.previousElementSibling) if (s.tagName === n.tagName) i++;
      steps.unshift(tag + ':nth-of-type(' + i + ')');
    }
    const path = anchor + '>' + steps.join('>');
    if (path.length <= 200) return path;
    for (let a = el.parentElement; a && a !== doc.body; a = a.parentElement) if (nameOf(a) || (LIVE && idSel(a))) return selOf(a);
    return null;
  }

  function find(sel) {
    if (typeof sel !== 'string' || !sel) return null;
    try { return doc.querySelector(/^[A-Za-z0-9_-]+(\/[A-Za-z0-9_-]+)*$/.test(sel) ? chainSel(sel.split('/')) : sel); } catch (e) { return null; }
  }
  const matches = (el, sel) => { try { return el.matches(sel); } catch (e) { return false; } };
  const query = sel => { try { return doc.querySelector(sel); } catch (e) { return null; } };   // a section's CSS selector
  // the innermost declared section holding el, by its index in `sections`
  function sectionOf(el) {
    for (let a = el; a && a.nodeType === 1; a = a.parentElement) {
      const i = sections.findIndex(s => matches(a, s));
      if (i >= 0) return i;
    }
    return null;
  }

  function describe(el, text, rect) {
    let name = null;
    for (let a = el; a && a !== doc.documentElement; a = a.parentElement) if ((name = nameOf(a))) break;
    if (!name && LIVE) name = el.id || null;
    const t = text != null ? text : (el.value || el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('alt') || '');
    return { sel: selOf(el), name: cap(name), tag: el.tagName.toLowerCase().slice(0, 20), text: cap(t), rect: rectOf(rect || el.getBoundingClientRect()), sec: sectionOf(el) };
  }

  // name -> rect for the first `max` elements matching sel that have a data-bd name; hidden ones map to null
  function namedRects(sel, max) {
    const out = {};
    let n = 0;
    for (const el of doc.querySelectorAll(sel)) {
      const name = nameOf(el);
      if (!name || name in out) continue;
      if (++n > max) break;
      const r = el.getBoundingClientRect();
      out[name] = el.hidden || r.width + r.height === 0 ? null : rectOf(r);
    }
    return out;
  }

  function ready(rects) {
    post({ bd: 'ready', w: Math.max(root.scrollWidth, doc.body ? doc.body.scrollWidth : 0), h: pin ? pageHeight() : Math.max(root.scrollHeight, doc.body ? doc.body.scrollHeight : 0),
      vw: innerWidth, vh: pin || null, byFrame: !stirred, fallback: cap(root.getAttribute('data-bd-fallback')) || null, rects: rects || {}, navs: namedRects('[data-nav]', 50), named: namedRects('[data-bd]', 100) });
    stirred = false;
  }

  function showOutline(el) {
    if (!outline) {
      outline = doc.createElement('div');
      outline.id = 'bd-inspect';
      outline.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;border:2px solid #ff8a00;border-radius:3px;background:rgba(255,138,0,.08);display:none';
      doc.body.appendChild(outline);
    }
    if (!el) { outline.style.display = 'none'; return; }
    const r = el.getBoundingClientRect();
    Object.assign(outline.style, { display: 'block', left: r.left - 2 + 'px', top: r.top - 2 + 'px', width: r.width + 4 + 'px', height: r.height + 4 + 'px' });
  }

  const active = () => mode === 'point' || mode === 'select';
  const pickable = el => el && el.nodeType === 1 && el !== doc.body && el !== root && !own(el);

  function onMove(e) {
    if (!active()) return;
    const el = pickable(e.target) ? e.target : null;
    if (el === hovered) return;
    hovered = el;
    showOutline(el);
    post(el ? { bd: 'hover', ...describe(el) } : { bd: 'hover', sel: null });
  }
  function onLeave() {
    if (!active() || !hovered) return;
    hovered = null;
    showOutline(null);
    post({ bd: 'hover', sel: null });
  }
  function swallow(e) {
    if (!active()) return;
    e.preventDefault();
    e.stopPropagation();
  }
  function onDown(e) { if (mode === 'point') swallow(e); else if (mode === 'select') e.stopPropagation(); }
  function onClick(e) {
    if (mode === 'interact') {
      const names = [];
      for (let n = e.target; n && n.nodeType === 1 && names.length < 8; n = n.parentElement) { const nm = nameOf(n); if (nm) names.push(nm); }
      if (names.length) post({ bd: 'nav', names });
      return;
    }
    if (!active()) return;
    swallow(e);
    if (mode === 'select' && String(getSelection() || '').trim()) return;   // the mouseup reported the selection
    const el = pickable(e.target) ? e.target : null;
    post(el ? { bd: 'pick', ...describe(el), shift: !!e.shiftKey } : { bd: 'pick', sel: null, name: null, tag: 'body', text: null, rect: rectOf(root.getBoundingClientRect()), shift: !!e.shiftKey });
  }
  function onUp(e) {
    if (mode !== 'select') return;
    e.stopPropagation();
    const s = getSelection();
    const text = String(s || '').trim();
    if (!text || !s.rangeCount) return;
    const range = s.getRangeAt(0);
    let el = range.commonAncestorContainer;
    if (el.nodeType !== 1) el = el.parentElement;
    if (!pickable(el)) return;
    post({ bd: 'pick', ...describe(el, text, range.getBoundingClientRect()), shift: !!e.shiftKey });
  }

  function setTokens(theme, motion) {
    const out = [];
    for (const [src, map] of [[theme, null], [motion, MOTION_VARS]]) {
      if (!src || typeof src !== 'object') continue;
      for (const [k, v] of Object.entries(src)) {
        const name = map ? map[k] : (TOKEN_KEY.test(k) ? '--' + k : null);
        if (name && typeof v === 'string' && v.length <= 200 && !BAD_VALUE.test(v)) out.push(name + ':' + v);
      }
    }
    const el = doc.getElementById('bd-tokens');
    if (el) el.textContent = out.length ? 'html:root{' + out.join(';') + '}' : '';
  }

  addEventListener('message', e => {
    if (e.source !== parent || !e.data || typeof e.data !== 'object') return;
    const m = e.data;
    if (m.bd === 'mode' && typeof m.mode === 'string') {
      mode = m.mode;
      if (!active()) { hovered = null; showOutline(null); }
    } else if (m.bd === 'tokens') {
      setTokens(m.theme, m.motion);
    } else if (m.bd === 'view') {
      root.classList.toggle('bd-sketch', !!m.sketch);
      root.classList.toggle('bd-reduced', !!m.reduced);
      root.classList.toggle('bd-paused', !!m.paused);
    } else if (m.bd === 'locate' && Array.isArray(m.sels)) {
      located = m.sels.slice(0, 100).filter(sel => typeof sel === 'string' && sel.length <= 200);
      ready(measure());
    } else if (m.bd === 'sections' && Array.isArray(m.sels)) {
      sections = m.sels.slice(0, 50).map(s => (typeof s === 'string' && s.length <= 200 ? s : ':not(*)'));
    } else if (m.bd === 'edits' && Array.isArray(m.list)) {
      applyEdits(m.list);
    } else if (m.bd === 'reveal' && typeof m.sel === 'string') {
      const el = query(m.sel);
      if (el) el.scrollIntoView({ block: 'start' });
    } else if (m.bd === 'page') {
      setPin(m.full === true ? m.vh : 0);
      stirred = true;
      if (doc.readyState === 'complete') ready(measure());
    }
  });
  // the last locate's selectors, measured now ({sel: rect | null})
  function measure() {
    const rects = {};
    for (const sel of located) { const el = find(sel); rects[sel] = el ? rectOf(el.getBoundingClientRect()) : null; }
    return rects;
  }
  // the variants shown in place: what the last list changed goes back first, newest first
  function applyEdits(list) {
    while (changed.length) { const [el, html] = changed.pop(); el.innerHTML = html; }
    for (const s of list.slice(0, 50)) {
      const host = s && typeof s.sel === 'string' ? query(s.sel) : null;
      if (!host || !Array.isArray(s.edits)) continue;
      for (const e of s.edits.slice(0, 20)) {
        if (!e || typeof e !== 'object') continue;
        let el = host;
        if (typeof e.sel === 'string' && e.sel) { try { el = matches(host, e.sel) ? host : host.querySelector(e.sel); } catch (x) { el = null; } }
        if (!el) continue;
        changed.push([el, el.innerHTML]);
        if (typeof e.text === 'string') el.textContent = e.text;
        else if (typeof e.html === 'string') el.innerHTML = e.html;
      }
    }
    stirred = true;
    if (doc.readyState === 'complete') ready(measure());
  }
  addEventListener('mouseover', onMove, true);
  addEventListener('mousemove', onMove, true);
  doc.addEventListener('mouseleave', onLeave);
  addEventListener('mousedown', onDown, true);
  addEventListener('pointerdown', onDown, true);
  addEventListener('mouseup', onUp, true);
  addEventListener('click', onClick, true);
  addEventListener('dblclick', swallow, true);
  addEventListener('submit', e => e.preventDefault(), true);
  addEventListener('load', () => {
    if (pin) pinSheets();
    ready(measure());
    if (typeof ResizeObserver === 'function') { const ro = new ResizeObserver(report); ro.observe(root); ro.observe(doc.body); }
    addEventListener('scroll', report, { capture: true, passive: true });   // a page in Viewport scrolls in its frame: pins follow
    addEventListener('resize', report);
    if (doc.fonts) { doc.fonts.ready.then(stir); doc.fonts.addEventListener('loadingdone', stir); }
  });
  // a stylesheet, image or font that loads after the page: its sheet pinned, the size reported again
  doc.addEventListener('load', e => { if (e.target === doc) return; if (pin && e.target.nodeName === 'LINK') pinSheets(); if (doc.readyState === 'complete') stir(); }, true);
  doc.addEventListener('DOMContentLoaded', () => { if (pin) { pinSheets(); pinAttrs(root); } });
})();
