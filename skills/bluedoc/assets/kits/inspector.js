/* bluedoc inspector: runs inside every design screen frame (opaque-origin sandbox) and talks to the design page.
   Page -> frame: {bd:'mode', mode}, {bd:'tokens', theme, motion}, {bd:'view', sketch, reduced, paused}, {bd:'locate', sels}.
   Frame -> page, exactly 4 types, strings capped at 200 chars:
     {bd:'ready', w, h, fallback, rects, navs, named}   on load, on resize, after each locate; navs: {name: rect | null}
                                       for up to 50 [data-nav] elements (null: hidden, a gesture link); named: the same
                                       for up to 100 [data-bd] elements
     {bd:'hover', sel, name, tag, text, rect} | {bd:'hover', sel: null}
     {bd:'pick',  sel, name, tag, text, rect, shift}   sel null = the whole artboard
     {bd:'nav',   names}   in interact mode, a click: the data-bd names of the clicked element and its named ancestors,
                           innermost first (at most 8). The click itself still runs. The page follows the first name
                           that has a link from this screen (its links, drafts included), so a forged name moves nothing.
   sel: the shortest unique chain of data-bd names ('submit', 'form/submit'), else a CSS path with '>' and no spaces
   from the nearest uniquely named ancestor ('[data-bd="login"]>h1:nth-of-type(1)') or from body. */
(() => {
  'use strict';
  const doc = document, root = doc.documentElement;
  const NAME = /^[A-Za-z0-9_-]+$/, TOKEN_KEY = /^[a-z][a-z0-9-]*$/, BAD_VALUE = /[;{}<>\\]|url\(/i;
  const MOTION_VARS = { fast: '--dur-fast', base: '--dur-base', slow: '--dur-slow', ease: '--ease' };
  const OWN = new Set(['bd-notice', 'bd-kit-svg', 'bd-inspect']);
  const target = /^https?:$/.test(location.protocol) ? location.protocol + '//' + location.host : '*';
  const cap = s => (s == null ? null : String(s).replace(/\s+/g, ' ').trim().slice(0, 200));
  const post = msg => { try { parent.postMessage(msg, target); } catch (e) { /* the page went away */ } };
  let mode = 'view', outline = null, hovered = null;

  const rectOf = r => ({ x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) });
  const nameOf = el => { const n = el.getAttribute && el.getAttribute('data-bd'); return n && NAME.test(n) ? n : null; };
  const count = sel => { try { return doc.querySelectorAll(sel).length; } catch (e) { return 0; } };
  const chainSel = names => names.map(n => '[data-bd="' + n + '"]').join(' ');
  const own = el => { for (let n = el; n && n !== doc.body; n = n.parentElement) if (OWN.has(n.id)) return true; return false; };

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
    const steps = [];
    let n = el, anchor = 'body';
    for (; n && n !== doc.body; n = n.parentElement) {
      const nm = nameOf(n);
      if (n !== el && nm && count('[data-bd="' + nm + '"]') === 1) { anchor = '[data-bd="' + nm + '"]'; break; }
      const tag = n.tagName.toLowerCase();
      let i = 1;
      for (let s = n.previousElementSibling; s; s = s.previousElementSibling) if (s.tagName === n.tagName) i++;
      steps.unshift(tag + ':nth-of-type(' + i + ')');
    }
    const path = anchor + '>' + steps.join('>');
    if (path.length <= 200) return path;
    for (let a = el.parentElement; a && a !== doc.body; a = a.parentElement) if (nameOf(a)) return selOf(a);
    return null;
  }

  function find(sel) {
    if (typeof sel !== 'string' || !sel) return null;
    try { return doc.querySelector(/^[A-Za-z0-9_-]+(\/[A-Za-z0-9_-]+)*$/.test(sel) ? chainSel(sel.split('/')) : sel); } catch (e) { return null; }
  }

  function describe(el, text, rect) {
    let name = null;
    for (let a = el; a && a !== doc.documentElement; a = a.parentElement) if ((name = nameOf(a))) break;
    const t = text != null ? text : (el.value || el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('alt') || '');
    return { sel: selOf(el), name: cap(name), tag: el.tagName.toLowerCase().slice(0, 20), text: cap(t), rect: rectOf(rect || el.getBoundingClientRect()) };
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
    post({ bd: 'ready', w: Math.max(root.scrollWidth, doc.body ? doc.body.scrollWidth : 0), h: Math.max(root.scrollHeight, doc.body ? doc.body.scrollHeight : 0),
      fallback: cap(root.getAttribute('data-bd-fallback')) || null, rects: rects || {}, navs: namedRects('[data-nav]', 50), named: namedRects('[data-bd]', 100) });
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
      const rects = {};
      for (const sel of m.sels.slice(0, 50)) {
        if (typeof sel !== 'string' || sel.length > 200) continue;
        const el = find(sel);
        rects[sel] = el ? rectOf(el.getBoundingClientRect()) : null;
      }
      ready(rects);
    }
  });
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
    ready();
    let t = 0;
    if (typeof ResizeObserver === 'function') new ResizeObserver(() => { clearTimeout(t); t = setTimeout(() => ready(), 150); }).observe(doc.body);
  });
})();
