/* Hypnomix · shared helpers. Classic scripts on one namespace so index.html opens from file:// */
(function () {
  'use strict';
  const HX = (window.HX = window.HX || {});

  /* seeded RNG (mulberry32) so mock audio looks identical on every load */
  HX.rng = function (seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  };
  HX.hash = function (s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; };

  HX.clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  HX.lerp = (a, b, t) => a + (b - a) * t;
  HX.dbToGain = (db) => (db <= -192 ? 0 : Math.pow(10, db / 20));
  HX.gainToDb = (g) => (g <= 0.0000001 ? -193 : 20 * Math.log10(g));
  /* Ardour's fader law (gain_to_slider_position): +6 dB at the top, log-ish below */
  HX.dbToPos = function (db) {
    const g = HX.dbToGain(db);
    if (g === 0) return 0;
    return Math.pow((6 * Math.log2(g) + 192) / 198, 8);
  };
  HX.posToDb = function (pos) {
    if (pos <= 0) return -193;
    const g = Math.pow(2, (Math.pow(pos, 1 / 8) * 198 - 192) / 6);
    return HX.clamp(HX.gainToDb(g), -193, 6);
  };
  HX.fmtDb = function (db, signed) {
    if (db <= -120) return '-∞';
    const s = (Math.round(db * 10) / 10).toFixed(1);
    return signed && db > 0 ? '+' + s : s;
  };
  HX.fmtDelta = (d, unit) => (d > 0 ? '+' : d < 0 ? '−' : '±') + Math.abs(Math.round(d * 10) / 10).toFixed(1) + (unit || '');
  HX.fmtPan = function (p) {
    if (Math.abs(p) < 0.005) return 'C';
    return Math.round(Math.abs(p) * 50) + (p < 0 ? 'L' : 'R');
  };
  HX.esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* tiny element builder: h('div.cls#id', {attrs}, children...) */
  HX.h = function (sel, attrs, ...kids) {
    const m = sel.match(/^([a-z0-9]+)?((?:[.#][\w-]+)*)$/i);
    const el = document.createElement((m && m[1]) || 'div');
    if (m && m[2]) m[2].replace(/([.#])([\w-]+)/g, (_, t, n) => { if (t === '.') el.classList.add(n); else el.id = n; });
    if (attrs) for (const k in attrs) {
      const v = attrs[k];
      if (v == null || v === false) continue;
      if (k === 'style' && typeof v === 'object') { for (const sk in v) { if (v[sk] == null) continue; if (sk.startsWith('--')) el.style.setProperty(sk, v[sk]); else el.style[sk] = v[sk]; } }
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'html') el.innerHTML = v;
      else if (k === 'text') el.textContent = v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const k of kids.flat()) if (k != null && k !== false) el.append(k.nodeType ? k : document.createTextNode(k));
    return el;
  };
  HX.$ = (s, r) => (r || document).querySelector(s);
  HX.$$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  /* event bus */
  const subs = {};
  HX.on = (ev, fn) => { (subs[ev] = subs[ev] || []).push(fn); return () => (subs[ev] = subs[ev].filter((f) => f !== fn)); };
  HX.emit = (ev, data) => { (subs[ev] || []).forEach((f) => f(data)); (subs['*'] || []).forEach((f) => f(ev, data)); };

  /* hi-dpi canvas sizing; returns ctx scaled to CSS pixels */
  HX.fitCanvas = function (cv, w, h) {
    w = Math.max(1, Math.round(w)); h = Math.max(1, Math.round(h));
    /* a browser refuses a canvas past about 32767 px a side or its area limit (a drawing that tall, such as the lanes
       of a few hundred tracks, would go blank): the pixel ratio comes down to fit, the picture a little softer */
    const dpr = Math.min(window.devicePixelRatio || 1, 2, 30000 / Math.max(w, h), Math.sqrt(1e8 / (w * h)));
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
      cv.style.width = w + 'px'; cv.style.height = h + 'px';
    }
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return ctx;
  };
  /* which elements are on screen (a meter scrolled out of view is not drawn): IntersectionObserver keeps el._vis */
  const vio = (() => { try { return new IntersectionObserver((es) => es.forEach((e) => { e.target._vis = e.isIntersecting; })); } catch (e) { return null; } })();
  HX.watchVisible = (el) => { if (vio) vio.observe(el); };
  HX.unwatchVisible = (el) => { if (vio) vio.unobserve(el); };
  HX.isVisible = (el) => el._vis !== false;   // unknown (not reported yet, or no observer) counts as visible
  HX.css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  /* vertical drag on a value; onDelta(dyPixels, fine) */
  HX.dragY = function (el, onStart, onDelta, onEnd) {
    el.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      el.setPointerCapture(e.pointerId);
      let lastY = e.clientY;
      onStart && onStart(e);
      const move = (ev) => { const dy = lastY - ev.clientY; lastY = ev.clientY; onDelta(dy, ev.shiftKey, ev); };
      const up = (ev) => { el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up); el.removeEventListener('pointercancel', up); onEnd && onEnd(ev); };
      el.addEventListener('pointermove', move);
      el.addEventListener('pointerup', up);
      el.addEventListener('pointercancel', up);
    });
  };

  HX.toast = function (msg, ms) {
    const t = HX.$('#toast');
    t.textContent = msg; t.hidden = false;
    clearTimeout(HX.toast._t);
    HX.toast._t = setTimeout(() => (t.hidden = true), ms || 1800);
  };

  /* ── dialogs ──
     HX.dialog({ title, body, buttons: [{ label, value, kind, focus }], cancel }) → a promise of the chosen button's value
     (cancel: Esc, a click outside). Focus starts on the button marked `focus` (the safe one), Tab and Shift+Tab stay inside
     and work as usual, and Enter / Space press the FOCUSED button only (never a default one). The page's own shortcuts
     are dead while a dialog is open (HX.modalOpen), and focus goes back to where it was. */
  HX.dialog = function (o) {
    return new Promise((resolve) => {
      const before = document.activeElement;
      const ov = HX.h('div.overlay.hx-confirm', { role: 'alertdialog', 'aria-modal': 'true' });
      const id = 'hxd' + Math.random().toString(36).slice(2, 8);
      ov.setAttribute('aria-labelledby', id);
      const done = (v) => { ov.remove(); document.removeEventListener('keydown', key, true); try { before && before.focus && before.focus(); } catch (e) {} resolve(v); };
      const btns = (o.buttons || [{ label: 'OK', value: true }]).map((b) => HX.h('button.btn' + (b.kind ? '.' + b.kind : ''), { type: 'button', onclick: () => done(b.value) }, b.label));
      const first = (o.buttons || []).findIndex((b) => b.focus);
      const key = (e) => {
        if (e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); done(o.cancel); return; }
        if (e.key === 'Tab') {                         // the buttons in order, round and round, kept inside the dialog (also where the browser's own Tab skips buttons)
          e.stopPropagation(); e.preventDefault();
          const list = btns.filter((b) => !b.disabled), i = list.indexOf(document.activeElement);
          list[i < 0 ? (e.shiftKey ? list.length - 1 : 0) : (i + (e.shiftKey ? -1 : 1) + list.length) % list.length].focus();
          return;
        }
        if (e.key === 'Enter' || e.key === ' ') {      // the focused button does its own click; nothing else reacts
          e.stopPropagation();
          if (!btns.includes(document.activeElement)) e.preventDefault();
          return;
        }
        if (!e.metaKey && !e.ctrlKey) e.stopPropagation();
      };
      ov.append(HX.h('div.confirm', null, HX.h('h3#' + id, null, o.title), HX.h('div.confirm-body', null, ...[].concat(o.body || []).map((p) => (p && p.nodeType ? p : HX.h('p', null, p)))), HX.h('div.row', null, btns)));
      ov.addEventListener('pointerdown', (e) => { if (e.target === ov) done(o.cancel); });
      document.body.append(ov);
      document.addEventListener('keydown', key, true);
      (btns[first >= 0 ? first : 0]).focus();
    });
  };
  /* a dialog, the shortcuts list or a popover is open: the page's keys (play, mute, delete a clip…) do nothing */
  HX.modalOpen = () => !!document.querySelector('.hx-confirm, .connect-pop, #helpOverlay:not([hidden])');

  HX.timeStr = function (sec) {
    const m = Math.floor(sec / 60), s = sec - m * 60;
    return m + ':' + (s < 10 ? '0' : '') + s.toFixed(3);
  };
  HX.bbtStr = function (beats) {
    const bar = Math.floor(beats / 4) + 1;
    const beat = Math.floor(beats % 4) + 1;
    const six = Math.floor((beats % 1) * 4) + 1;
    return bar + '. ' + beat + '. ' + six;
  };
})();
