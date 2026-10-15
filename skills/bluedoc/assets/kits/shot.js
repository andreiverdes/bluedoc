/* bluedoc shot runner: the last script of a storelisting shot's or asset's document (serve.py wrap_screen). It reads
   the shot's data (#bd-shot-data: {id, kind: shot|asset, sets: {<set>: {w, h, uiW, uiH, raw, platform, row}}, asset:
   {w, h}|null, strings: {<locale>: {key: text}}, defaultLocale, style: {message, layout}}) and what to show, then lays
   the shot out before it shows (html.shot-pending hides it until then).
   What to show, in order: the frame's name 'bd-shot <JSON>' (the page names each frame before it loads), the URL's
   query (?set=&locale=&i=&n=&message=&layout=&ui=, for a tab or an export), and the defaults (the first set, the
   default locale, shot 1 of 1, the listing's style). Page -> frame, later: {bd:'shot', set?, locale?, i?, n?,
   message?, layout?, ui?} (any of them) and {bd:'brand', palette: {role: #hex}, font: {family, weight}}.
   - Strings: each [data-l10n="key"] gets the locale's text, else the default locale's (data-l10n-state="fallback"),
     else keeps its HTML text (data-l10n-state="missing").
   - The UI slot (.shot-ui) holds the mock-up at the set's UI viewport (uiW × uiH), scaled to the layout's place in
     .shot-frame; `ui` (a capture's URL) shows that PNG over it (html.ui--capture).
   - After a change it fires 'bd-stir' on the document: the inspector measures and reports again. */
(() => {
  'use strict';
  const doc = document, root = doc.documentElement;
  let data = {};
  try { data = JSON.parse(doc.getElementById('bd-shot-data').textContent) || {}; } catch (e) { data = {}; }
  const sets = data.sets && typeof data.sets === 'object' ? data.sets : {};
  const strings = data.strings && typeof data.strings === 'object' ? data.strings : {};
  const STYLE = /^[ml][1-5]$/, HEX = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/, FAMILY = /^[^;{}<>\\"'`]{1,64}$/, ROLES = ['bg', 'surface', 'accent', 'text', 'caption'];
  // where a layout puts the UI in .shot-frame: wf of its width (at most), hf of its height (a bleed past the bottom
  // edge when over 1), its side; flush: the full width from the top
  const LAYOUT = { l1: { wf: 0.76, hf: 1.1 }, l2: { wf: 0.72, hf: 1.1 }, l3: { wf: 1, hf: 99, flush: true }, l4: { wf: 0.76, hf: 1.1 }, l5: { wf: 0.5, hf: 1, side: 'right' } };
  const st = { set: null, locale: data.defaultLocale || null, i: 0, n: 1, message: null, layout: null, ui: null };
  const take = o => {
    if (!o || typeof o !== 'object') return;
    if (typeof o.set === 'string' && sets[o.set]) st.set = o.set;
    if (typeof o.locale === 'string' && /^[A-Za-z0-9-]{2,16}$/.test(o.locale)) st.locale = o.locale;
    if (Number.isInteger(+o.i) && +o.i >= 0) st.i = +o.i;
    if (Number.isInteger(+o.n) && +o.n >= 1) st.n = +o.n;
    if (typeof o.message === 'string' && STYLE.test(o.message) && o.message[0] === 'm') st.message = o.message;
    if (typeof o.layout === 'string' && STYLE.test(o.layout) && o.layout[0] === 'l') st.layout = o.layout;
    if ('ui' in o) st.ui = typeof o.ui === 'string' && /^(https?:\/\/[^\s"'()<>]+|data:image\/png;base64,[A-Za-z0-9+/=]+)$/.test(o.ui) ? o.ui : null;
  };
  const q = new URLSearchParams(location.search);
  take(Object.fromEntries(q));
  try { if ((window.name || '').startsWith('bd-shot ')) take(JSON.parse(window.name.slice(8))); } catch (e) { /* not ours */ }

  const own = (tag, cls) => { const el = doc.createElement(tag); el.className = cls; el.setAttribute('data-bd-own', ''); return el; };
  const shotEl = doc.querySelector('.shot'), cap = doc.querySelector('.shot-cap'), frame = doc.querySelector('.shot-frame'), ui = doc.querySelector('.shot-ui');
  let img = null, zoom = null, proof = null, step = null, play = null, person = null;
  if (shotEl && cap) { step = own('div', 'shot-step'); proof = own('div', 'shot-proof'); shotEl.insertBefore(step, cap); shotEl.insertBefore(proof, cap); }
  if (shotEl) { person = own('div', 'shot-person'); play = own('div', 'shot-play'); shotEl.append(person, play); }

  function fill() {
    const mine = strings[st.locale] || {}, base = strings[data.defaultLocale] || {};
    for (const el of doc.querySelectorAll('[data-l10n]')) {
      const k = el.getAttribute('data-l10n');
      if (!('l10nHtml' in el.dataset)) el.dataset.l10nHtml = el.textContent;
      const v = typeof mine[k] === 'string' ? mine[k] : typeof base[k] === 'string' ? base[k] : null;
      el.textContent = v != null ? v : el.dataset.l10nHtml;
      el.setAttribute('data-l10n-state', typeof mine[k] === 'string' ? 'ok' : v != null ? 'fallback' : 'missing');
    }
    if (proof) { const k = `${data.id}.proof`, v = typeof mine[k] === 'string' ? mine[k] : base[k]; proof.textContent = typeof v === 'string' ? v : ''; root.toggleAttribute('data-proof', typeof v === 'string'); }
  }
  // the UI at its scale in the frame box, for the layout; a callout (M3) and the play button (M5) over it
  function place() {
    const set = sets[st.set] || null;
    if (!frame || !ui || !set) return;
    const uw = set.uiW, uh = set.uiH, W = frame.clientWidth, H = frame.clientHeight;
    let k, x, y = 0;
    if (set.raw) { k = Math.min(W / uw, H / uh); x = (W - uw * k) / 2; }
    else {
      const L = LAYOUT[st.layout] || LAYOUT.l1;
      if (L.flush) { k = W / uw; x = 0; }
      else { k = Math.min(W * L.wf / uw, H * L.hf / uh); x = L.side === 'right' ? W - uw * k - W * 0.06 : (W - uw * k) / 2; }
    }
    root.style.setProperty('--ui-k', String(Math.max(0.05, k)));
    root.style.setProperty('--ui-x', x + 'px'); root.style.setProperty('--ui-y', y + 'px');
    const fr = frame.getBoundingClientRect(), sr = shotEl.getBoundingClientRect();
    if (play) Object.assign(play.style, { left: fr.left - sr.left + x + uw * k / 2 + 'px', top: fr.top - sr.top + y + Math.min(uh * k, H) / 2 + 'px' });
    if (zoom) { zoom.remove(); zoom = null; }
    const target = st.message === 'm3' && !set.raw ? ui.querySelector('[data-callout]') : null;
    if (target) {
      const r = target.getBoundingClientRect();
      zoom = own('div', 'shot-zoom');
      const c = target.cloneNode(true);
      for (const el of [c, ...c.querySelectorAll('[data-bd], [id]')]) { el.removeAttribute('data-bd'); el.removeAttribute('id'); }
      c.style.margin = '0';
      zoom.append(c);
      const s = 1.35, w = r.width, h = r.height;
      Object.assign(zoom.style, { left: Math.max(sr.width * 0.04, Math.min(sr.width * 0.96 - w * s, r.left - sr.left - w * (s - 1) / 2)) + 'px', top: r.top - sr.top - h * (s - 1) / 2 + 'px',
        width: w / k + 'px', height: h / k + 'px', transform: `scale(${s * k})`, transformOrigin: '0 0' });
      shotEl.append(zoom);
    }
  }
  function apply() {
    const set = sets[st.set] || null, asset = data.asset || null;
    const dims = set || asset || { w: innerWidth, h: innerHeight };
    root.style.setProperty('--shot-w', dims.w + 'px'); root.style.setProperty('--shot-h', dims.h + 'px');
    root.style.setProperty('--screen-w', dims.w + 'px'); root.style.setProperty('--screen-h', dims.h + 'px');
    if (set) { root.style.setProperty('--ui-w', set.uiW + 'px'); root.style.setProperty('--ui-h', set.uiH + 'px'); }
    // the UI's safe areas, as on the board's devices: a phone's status bar and home indicator, a tablet's; a watch none
    const safe = set && !set.raw ? (set.row === 'phone' ? [47, 0, 34, 0] : set.row === 'tablet' ? [24, 0, 20, 0] : [0, 0, 0, 0]) : [0, 0, 0, 0];
    ['top', 'right', 'bottom', 'left'].forEach((k, i) => root.style.setProperty('--safe-' + k, safe[i] + 'px'));
    root.style.setProperty('--shot-i', String(st.i)); root.style.setProperty('--shot-n', String(st.n));
    const keep = [...root.classList].filter(c => !/^(plat-|row-|msg--|shot--)|^(raw|land|ui--capture)$/.test(c));
    const style = data.style || {}, msg = st.message || style.message || 'm1', lay = st.layout || style.layout || 'l1';
    st.message = msg; st.layout = lay;
    root.className = [...keep, set && 'plat-' + set.platform, set && 'row-' + set.row, set && set.raw && 'raw', dims.w > dims.h && 'land',
      'msg--' + msg, 'shot--' + lay, st.ui && 'ui--capture'].filter(Boolean).join(' ');
    root.toggleAttribute('data-odd', st.i % 2 === 1); root.toggleAttribute('data-first', st.i === 0);
    if (step) step.textContent = `${st.i + 1} / ${st.n}`;
    if (ui) {
      if (st.ui && !img) { img = own('img', 'shot-shot'); img.alt = ''; ui.append(img); }
      if (img) { if (st.ui) { if (img.getAttribute('src') !== st.ui) img.src = st.ui; } else img.removeAttribute('src'); }
    }
    fill();
    place();
    root.classList.remove('shot-pending');
    doc.dispatchEvent(new Event('bd-stir'));
  }
  function brand(m) {
    const pal = m.palette && typeof m.palette === 'object' ? m.palette : {};
    for (const r of ROLES) if (typeof pal[r] === 'string' && HEX.test(pal[r])) root.style.setProperty('--brand-' + r, pal[r]);
    const f = m.font;
    if (f && typeof f.family === 'string' && FAMILY.test(f.family)) root.style.setProperty('--bd-font-caption', `"${f.family}", Inter, system-ui, sans-serif`);
    if (f && Number.isInteger(f.weight) && f.weight >= 100 && f.weight <= 900) root.style.setProperty('--bd-weight-caption', String(f.weight));
    place(); doc.dispatchEvent(new Event('bd-stir'));
  }
  addEventListener('message', e => {
    if (e.source !== parent || !e.data || typeof e.data !== 'object') return;
    if (e.data.bd === 'shot') { take(e.data); apply(); } else if (e.data.bd === 'brand') brand(e.data);
  });
  apply();
  addEventListener('resize', place);
  if (doc.fonts) doc.fonts.ready.then(() => { place(); doc.dispatchEvent(new Event('bd-stir')); });
})();
