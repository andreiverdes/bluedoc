/* bluedoc inspector: runs inside every design screen frame (opaque-origin sandbox) and talks to the design page. On a
   website's live page, serve.py's dev-server proxy injects it as <script src data-parents="<origin> …">: it posts to
   those page origins, names elements from the nearest unique id as well, roots the page's IntersectionObservers in
   the frame's own viewport and can snapshot the page. A live page's snapshot, served as a screen, loads it with
   data-ids="1": named from ids as on the live page, posting to the frame's own server like any screen.
   Page -> frame: {bd:'mode', mode}, {bd:'tokens', theme, motion}, {bd:'view', sketch, reduced, paused}, {bd:'locate', sels},
     {bd:'sections', sels}   a website page's section selectors: hover and pick report the innermost one holding the element
     {bd:'edits', list}      list: [{sel, edits: [{sel?, text? | html?}]}]: the variants shown in place. Each edit sets the
                             text or the HTML of the element its sel finds in its section (the section itself without
                             sel); the next list first puts back what the last one changed
     {bd:'reveal', sel}      scroll the element to the top of the frame
     {bd:'scroll', y}        scroll the frame to y (compare's two revisions of a page in Viewport scroll together)
     {bd:'page', full, vh}   a website page's view: full (Full page: the frame grows to the document and never scrolls)
                             pins every viewport height to vh px, the design viewport's (--bd-vh, innerHeight,
                             visualViewport.height, the root's clientHeight); else (Viewport) the frame's own. The
                             frame's name ('bd-page full 900' | 'bd-page view 900') says the same before the page loads.
     {bd:'snapshot', id}     a live page only: answer with the page as one self-contained document (snapshot() below)
   Frame -> page, exactly 6 types, strings capped at 200 chars (but a snapshot's html):
     {bd:'ready', w, h, vw, vh, byFrame, fallback, rects, navs, named, sigs}   on load, on resize, on scroll, after each
                                       locate and on any change of the document's size (fonts, images, DOM); vw: the
                                       frame's width; vh: the pinned height (null: none). h: the document's height;
                                       pinned, the height the frame should take (at least vh). byFrame: nothing in the
                                       document changed since the last report, only the frame. navs: {name: rect | null}
                                       for up to 50 [data-nav] elements (null: hidden, a gesture link); named: the same
                                       for up to 100 [data-bd] elements; rects: the last locate's selectors, measured again;
                                       sigs: per section selector, a hash of its tags and text (null: not on the page), so
                                       compare can tell a changed section from the same one in another revision
     {bd:'hover', sel, name, tag, text, rect, sec} | {bd:'hover', sel: null}
     {bd:'pick',  sel, name, tag, text, rect, sec, shift}   sel null = the whole artboard; sec: the section's index or null
     {bd:'nav',   names}   in interact mode, a click: the data-bd names of the clicked element and its named ancestors,
                           innermost first (at most 8). The click itself still runs. The page follows the first name
                           that has a link from this screen (its links, drafts included), so a forged name moves nothing.
     {bd:'scroll', y}      the frame scrolled (Viewport), at most once a frame
     {bd:'snapshot', id, html, external, error}   the answer to a snapshot request: html, or error when it failed
   sel: the shortest unique chain of data-bd names ('submit', 'form/submit'), else a CSS path with '>' and no spaces
   from the nearest uniquely named ancestor ('[data-bd="login"]>h1:nth-of-type(1)'), on a live page (or its snapshot)
   also from the nearest unique id ('#hero-title', '#faq>details:nth-of-type(2)'), or from body. */
(() => {
  'use strict';
  const doc = document, root = doc.documentElement;
  const NAME = /^[A-Za-z0-9_-]+$/, TOKEN_KEY = /^[a-z][a-z0-9-]*$/, BAD_VALUE = /[;{}<>\\]|url\(/i;
  const MOTION_VARS = { fast: '--dur-fast', base: '--dur-base', slow: '--dur-slow', ease: '--ease' };
  const OWN = new Set(['bd-notice', 'bd-kit-svg', 'bd-inspect']);
  // a live page: the page origins the proxy named (its own origin is the proxy's, not the page's)
  const me = doc.currentScript, PARENTS = ((me && me.dataset.parents) || '').split(' ').filter(o => /^http:\/\/[\w.[\]:-]+$/.test(o));
  const LIVE = PARENTS.length > 0, IDS = LIVE || (!!me && me.dataset.ids === '1');   // IDS: names from ids too
  const targets = LIVE ? PARENTS : [/^https?:$/.test(location.protocol) ? location.protocol + '//' + location.host : '*'];
  const cap = s => (s == null ? null : String(s).replace(/\s+/g, ' ').trim().slice(0, 200));
  const post = msg => { for (const t of targets) try { parent.postMessage(msg, t); } catch (e) { /* the page went away */ } };
  let mode = 'view', outline = null, hovered = null, sections = [], located = [], shownEdits = [], sigs = null;
  const changed = [];   // [element, its innerHTML before an edit], in the order the edits ran
  const idSel = el => (el.id && typeof CSS !== 'undefined' ? '#' + CSS.escape(el.id) : null);
  // a snapshot inlines the stylesheets, fonts and backgrounds the page loaded: keep every resource's timing entry
  if (LIVE && typeof performance !== 'undefined' && performance.setResourceTimingBufferSize) performance.setResourceTimingBufferSize(5000);

  const rectOf = r => ({ x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) });
  const nameOf = el => { const n = el.getAttribute && el.getAttribute('data-bd'); return n && NAME.test(n) ? n : null; };
  const count = sel => { try { return doc.querySelectorAll(sel).length; } catch (e) { return 0; } };
  const chainSel = names => names.map(n => '[data-bd="' + n + '"]').join(' ');
  // the kit's own elements, never a comment target: the notice, the outline, a shot's (data-bd-own: kits/shot.js)
  const own = el => { for (let n = el; n && n !== doc.body; n = n.parentElement) if (OWN.has(n.id) || n.hasAttribute('data-bd-own')) return true; return false; };

  /* Full page (a website page's view: {bd:'page'}, the frame's name): the frame grows to the document, so every height
     that follows the viewport's is pinned to the design viewport's, pin px. Viewport units go through --bd-vh: serve.py's
     proxy rewrote the site's HTML and CSS (pin_viewport_units, keep the two alike) and here the same rewrite reaches
     what it never saw (a mockup's compiled Tailwind, styles a script adds or sets). innerHeight, visualViewport.height
     and the root's clientHeight answer pin. pin 0: Viewport, every value the frame's own. */
  let pin = 0, probed = -1, mo = null, reportT = 0, stirred = true;
  const VU = /(?<!--bd-vh)(?<!--bd-vh,)(^|[^\w./+-])(-?)(\d*\.?\d+(?:e[+-]?\d+)?)[sld]?(vh|vb|vmin|vmax)\b(?![^{};]*\{)/gi, HAS_VU = new RegExp(VU.source, 'i');
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
    if (IDS && idSel(el) && count(idSel(el)) === 1) return cap(idSel(el));
    const steps = [];
    let n = el, anchor = 'body';
    for (; n && n !== doc.body; n = n.parentElement) {
      const nm = nameOf(n);
      if (n !== el && nm && count('[data-bd="' + nm + '"]') === 1) { anchor = '[data-bd="' + nm + '"]'; break; }
      if (n !== el && IDS && idSel(n) && count(idSel(n)) === 1) { anchor = idSel(n); break; }
      const tag = n.tagName.toLowerCase();
      let i = 1;
      for (let s = n.previousElementSibling; s; s = s.previousElementSibling) if (s.tagName === n.tagName) i++;
      steps.unshift(tag + ':nth-of-type(' + i + ')');
    }
    const path = anchor + '>' + steps.join('>');
    if (path.length <= 200) return path;
    for (let a = el.parentElement; a && a !== doc.body; a = a.parentElement) if (nameOf(a) || (IDS && idSel(a))) return selOf(a);
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
    if (!name && IDS) name = el.id || null;
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

  // a section's signature: FNV-1a over its tags and text (whitespace collapsed), without what a snapshot drops or
  // replaces (scripts, styles, frames, canvases: data-bd-snap) or classes and attributes, which scroll effects and the
  // snapshot's inlining change; null when the selector finds nothing
  const SIG_SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'LINK', 'META', 'IFRAME', 'CANVAS', 'SOURCE', 'OBJECT', 'EMBED']);
  function sigOf(el) {
    if (!el) return null;
    let h = 0x811c9dc5;
    const eat = s => { for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); } };
    const walk = n => {
      for (let c = n.firstChild; c; c = c.nextSibling) {
        if (c.nodeType === 3) { const t = c.data.replace(/\s+/g, ' ').trim(); if (t) eat('"' + t); continue; }
        if (c.nodeType !== 1 || SIG_SKIP.has(c.nodeName.toUpperCase()) || OWN.has(c.id) || c.hasAttribute('data-bd-snap')) continue;
        eat('<' + c.nodeName.toLowerCase()); walk(c); eat('>');
      }
    };
    walk(el);
    return (h >>> 0).toString(16);
  }
  function ready(rects) {
    if (stirred || !sigs) sigs = sections.map(s => sigOf(query(s)));
    post({ bd: 'ready', w: Math.max(root.scrollWidth, doc.body ? doc.body.scrollWidth : 0), h: pin ? pageHeight() : Math.max(root.scrollHeight, doc.body ? doc.body.scrollHeight : 0),
      vw: innerWidth, vh: pin || null, byFrame: !stirred, fallback: cap(root.getAttribute('data-bd-fallback')) || null, rects: rects || {}, navs: namedRects('[data-nav]', 50), named: namedRects('[data-bd]', 100), sigs });
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
      sigs = null;
    } else if (m.bd === 'edits' && Array.isArray(m.list)) {
      applyEdits(m.list);
    } else if (m.bd === 'reveal' && typeof m.sel === 'string') {
      const el = query(m.sel);
      if (el) el.scrollIntoView({ block: 'start' });
    } else if (m.bd === 'scroll' && Number.isFinite(m.y)) {
      if (!pin) scrollTo(scrollX, m.y);
    } else if (m.bd === 'page') {
      setPin(m.full === true ? m.vh : 0);
      stirred = true;
      if (doc.readyState === 'complete') ready(measure());
    } else if (m.bd === 'snapshot' && LIVE) {
      const id = m.id;
      snapshot().then(r => post({ bd: 'snapshot', id, html: r.html, external: r.external }),
        err => post({ bd: 'snapshot', id, error: cap(err && err.message || err) || 'failed' }));
    }
  });
  // Viewport: the frame's own scroll, at most once a frame (compare scrolls the other revision's frame along)
  let scrollRaf = 0;
  addEventListener('scroll', () => {
    if (pin || scrollRaf) return;
    scrollRaf = requestAnimationFrame(() => { scrollRaf = 0; post({ bd: 'scroll', y: Math.round(scrollY) }); });
  }, { passive: true });

  /* A live page's snapshot ({bd:'snapshot'} from the page; serve.py's `snapshot` command calls window.__bluedocSnapshot):
     the page as the site renders it now, as one document that needs nothing from the dev server. The DOM is cloned with
     the versions shown in place put back (the snapshot's page shows them again); scripts, event attributes, frames (a
     blank box their size), media sources, dev toolbars and the inspector go, and dev-only attributes (Astro's source
     paths, Vite's ids). Every stylesheet becomes a <style> of its rules' text (an @import inlined; a sheet of another
     origin fetched), its url()s absolute. Images, and the fonts and backgrounds the page loaded (its resource timing),
     become data: URIs of at most SNAP_ASSET bytes each and SNAP_TOTAL in all; a larger or unreadable one keeps its URL
     on the dev server itself (the proxy's data-origin), which the snapshot loads from it: `external` counts those
     images, which may show what the site has now. Form fields keep their values, a readable canvas its picture. */
  const SNAP_ASSET = 1024 * 1024, SNAP_TOTAL = 4608 * 1024;
  const SNAP_DROP = 'script, noscript, template, base, meta[http-equiv], object, embed, source, track, link:not([rel~="stylesheet" i]), ' +
    '#bd-inspect, #bd-live, astro-dev-toolbar, astro-dev-overlay, nextjs-portal, vite-error-overlay';
  const DEV_ATTRS = ['data-astro-source-file', 'data-astro-source-loc', 'data-vite-dev-id'];
  const CSS_URL = /url\(\s*(['"]?)([^'")]*)\1\s*\)/gi;
  const DEV = LIVE && /^https?:\/\/[\w.[\]:-]+$/.test((me && me.dataset.origin) || '') ? me.dataset.origin : null;
  const devUrl = u => (DEV && u.startsWith(location.origin + '/') ? DEV + u.slice(location.origin.length) : u);
  const absUrl = (u, base) => { try { return new URL(u, base).href; } catch (e) { return null; } };
  const absUrls = (css, base) => css.replace(CSS_URL, (m, q, u) => {
    const a = !u.trim() || /^(data:|#)/i.test(u.trim()) ? null : absUrl(u.trim(), base);
    return a ? 'url("' + a.replace(/"/g, '%22') + '")' : m;
  });
  function rulesText(sheet, depth) {
    let rules = null;
    try { rules = sheet.cssRules; } catch (e) { return null; }   // another origin's
    const base = sheet.href || doc.baseURI;
    let out = '';
    for (const r of rules) {
      if (typeof CSSImportRule === 'function' && r instanceof CSSImportRule) {
        const t = r.styleSheet && depth < 4 ? rulesText(r.styleSheet, depth + 1) : null, media = r.media && r.media.mediaText;
        if (t != null) out += media ? '@media ' + media + ' {\n' + t + '}\n' : t;
        continue;
      }
      out += absUrls(r.cssText, base) + '\n';
    }
    return out;
  }
  async function snapshot() {
    const shown = shownEdits;
    while (changed.length) { const [el, html] = changed.pop(); el.innerHTML = html; }
    const clone = root.cloneNode(true), from = [root, ...root.querySelectorAll('*')], to = [clone, ...clone.querySelectorAll('*')];
    const sheets = [], imgs = [], styled = [], swaps = [];
    try {
      from.forEach((el, i) => {
        const c = to[i], tag = el.nodeName.toUpperCase();
        for (const a of [...c.attributes]) if (/^on/i.test(a.name) || DEV_ATTRS.includes(a.name) || (/^(href|src|action|formaction)$/i.test(a.name) && /^\s*javascript:/i.test(a.value))) c.removeAttribute(a.name);
        if (c.hasAttribute('style') && /url\(/i.test(c.getAttribute('style'))) styled.push(c);
        if (tag === 'STYLE' || (tag === 'LINK' && /(^|\s)stylesheet(\s|$)/i.test(el.rel || ''))) {
          if (!el.sheet || el.sheet.disabled) { swaps.push([c, null]); return; }
          const text = rulesText(el.sheet, 0);
          sheets.push({ c, media: el.media || '', text: text != null ? text : tag === 'STYLE' ? absUrls(el.textContent, doc.baseURI) : null, href: el.href || null });
        } else if (tag === 'IMG') {
          imgs.push([c, 'src', el.currentSrc || el.src]);
          for (const a of ['srcset', 'sizes', 'loading']) c.removeAttribute(a);
        } else if (tag === 'IMAGE') {
          const href = el.getAttribute('href') || el.getAttribute('xlink:href');
          if (href && !/^(data:|#)/i.test(href)) imgs.push([c, el.hasAttribute('href') ? 'href' : 'xlink:href', absUrl(href, doc.baseURI)]);
        } else if (tag === 'VIDEO') {
          c.removeAttribute('src'); c.removeAttribute('autoplay');
          if (el.poster) imgs.push([c, 'poster', el.poster]);
        } else if (tag === 'INPUT') {
          if (/^(checkbox|radio)$/i.test(el.type)) { if (el.checked) c.setAttribute('checked', ''); else c.removeAttribute('checked'); }
          else if (!/^(password|file)$/i.test(el.type)) c.setAttribute('value', el.value);
        } else if (tag === 'TEXTAREA') {
          c.textContent = el.value;
        } else if (tag === 'OPTION') {
          if (el.selected) c.setAttribute('selected', ''); else c.removeAttribute('selected');
        } else if (tag === 'CANVAS') {
          let src = null;
          try { src = el.toDataURL(); } catch (e) { /* tainted */ }
          const img = doc.createElement('img');
          for (const a of ['class', 'style', 'width', 'height', 'id']) if (el.hasAttribute(a)) img.setAttribute(a, el.getAttribute(a));
          img.setAttribute('data-bd-snap', 'canvas');
          if (src) img.src = src;
          swaps.push([c, img]);
        } else if (tag === 'IFRAME') {
          const r = el.getBoundingClientRect(), box = doc.createElement('div');
          for (const a of ['class', 'style', 'id']) if (el.hasAttribute(a)) box.setAttribute(a, el.getAttribute(a));
          box.setAttribute('data-bd-snap', 'frame');
          box.style.cssText += ';display:block;width:' + Math.round(r.width) + 'px;height:' + Math.round(r.height) + 'px;background:repeating-linear-gradient(135deg,#eef0f3 0 10px,#f7f8fa 10px 20px)';
          swaps.push([c, box]);
        }
      });
      clone.style.removeProperty('--bd-vh');
      if (clone.getAttribute('style') === '') clone.removeAttribute('style');
      clone.classList.remove('bd-sketch', 'bd-reduced', 'bd-paused');
      if (!clone.classList.length) clone.removeAttribute('class');
    } finally {
      applyEdits(shown, true);   // the page as the reader sees it again, before anything awaits, unreported: nothing moved
    }
    for (const n of clone.querySelectorAll(SNAP_DROP)) n.remove();
    for (const [c, by] of swaps) { if (by) c.replaceWith(by); else c.remove(); }

    // assets: fetched once each, from the page's own origin (the proxy) or with CORS from another
    const loaded = new Set(performance.getEntriesByType('resource').map(e => e.name));
    let budget = SNAP_TOTAL, external = 0;
    const got = new Map();
    const dataOf = u => {
      if (!got.has(u)) got.set(u, (async () => {
        try {
          const r = await fetch(u, { credentials: 'same-origin', cache: 'force-cache' });
          if (!r.ok) return null;
          const b = await r.blob();
          if (b.size > SNAP_ASSET || b.size > budget) return null;
          budget -= b.size;
          return await new Promise(res => { const f = new FileReader(); f.onload = () => res(f.result); f.onerror = () => res(null); f.readAsDataURL(b); });
        } catch (e) { return null; }
      })());
      return got.get(u);
    };
    await Promise.all(sheets.filter(s => s.text == null && s.href).map(async s => {
      try { const r = await fetch(s.href, { cache: 'force-cache' }); s.text = r.ok ? absUrls(await r.text(), s.href) : null; } catch (e) { s.text = null; }
    }));
    // a url() in CSS is inlined when the page loaded it (a font it used, a background it showed), else left absolute
    const cssUrls = new Set();
    for (const t of [...sheets.map(s => s.text || ''), ...styled.map(c => absUrls(c.getAttribute('style'), doc.baseURI))]) for (const m of t.matchAll(CSS_URL)) if (loaded.has(m[2])) cssUrls.add(m[2]);
    const inlined = new Map();
    await Promise.all([...cssUrls, ...imgs.map(i => i[2]).filter(u => u && !/^data:/i.test(u))].map(async u => { const d = await dataOf(u); if (d) inlined.set(u, d); }));
    const swapUrls = css => css.replace(CSS_URL, (m, q, u) => 'url("' + (inlined.has(u) ? inlined.get(u) : devUrl(u)) + '")');
    for (const s of sheets) {
      if (s.text == null) { s.c.remove(); continue; }
      const st = doc.createElement('style');
      if (s.media && s.media !== 'all') st.setAttribute('media', s.media);
      st.textContent = swapUrls(s.text).replace(/<\/(style)/gi, '<\\/$1');
      s.c.replaceWith(st);
    }
    for (const c of styled) c.setAttribute('style', swapUrls(absUrls(c.getAttribute('style'), doc.baseURI)));
    for (const [c, attr, u] of imgs) {
      if (!u) continue;
      if (inlined.has(u)) c.setAttribute(attr, inlined.get(u));
      else if (!/^data:/i.test(u)) { c.setAttribute(attr, devUrl(u)); external++; }
    }
    const head = clone.querySelector('head');
    for (const s of doc.adoptedStyleSheets || []) {
      const t = rulesText(s, 0);
      if (t && head) { const st = doc.createElement('style'); st.textContent = swapUrls(t).replace(/<\/(style)/gi, '<\\/$1'); head.append(st); }
    }
    return { html: (doc.doctype ? '<!DOCTYPE ' + doc.doctype.name + '>\n' : '') + clone.outerHTML, external };
  }
  if (LIVE) Object.defineProperty(window, '__bluedocSnapshot', { value: () => snapshot() });
  // the last locate's selectors, measured now ({sel: rect | null})
  function measure() {
    const rects = {};
    for (const sel of located) { const el = find(sel); rects[sel] = el ? rectOf(el.getBoundingClientRect()) : null; }
    return rects;
  }
  // the variants shown in place: what the last list changed goes back first, newest first. quiet: no report (a
  // snapshot puts the same edits back)
  function applyEdits(list, quiet) {
    shownEdits = list;
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
    if (quiet) return;
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
  // a store shot laid itself out again (kits/shot.js: a locale, a style, the brand): measure and report
  doc.addEventListener('bd-stir', () => { if (doc.readyState === 'complete') stir(); });
})();
