/* Hypnomix · bottom panel: the selected track's device chain (left to right, Live-style),
   or the selected clip's detail. Knobs are CSS conic arcs; curves are drawn on canvas.
   On the engine's session the chain is the track's real plug-ins: knobs set their parameters
   (plugin_set_parameter_by_index_value), the light bypasses (plugin_set_enabled), drag a title to move a device
   (plugin_reorder), × twice removes it (plugin_remove), + adds one from the engine's list. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  let root, headT, chain, tabs, knobRefs = [];

  HX.mountDevices = function () {
    root = HX.$('#devices');
    root.innerHTML = '';
    headT = h('div.t');
    tabs = h('div.seg', null,
      h('button', { 'data-b': 'devices', onclick: () => { S.ui.bottom = 'devices'; render(); }, 'data-info': 'Device chain of the selected track' }, 'Devices'),
      h('button', { 'data-b': 'clip', onclick: () => { S.ui.bottom = 'clip'; render(); }, 'data-info': 'Detail of the selected clip' }, 'Clip'));
    root.append(h('div.dev-head', null, headT, h('span.sub#devSub'), h('span', { style: { marginLeft: 'auto' } }), tabs));
    chain = h('div.dev-chain');
    root.append(chain);
    render();
  };

  const toN = (p, v) => (p.log ? Math.log(v / p.min) / Math.log(p.max / p.min) : (v - p.min) / (p.max - p.min));
  const fromN = (p, n) => (p.log ? p.min * Math.pow(p.max / p.min, n) : p.min + n * (p.max - p.min));
  function fmt(p, v) {
    if (p.labels) return p.labels[Math.round(v)] || v;
    if (p.points) { let b = p.points[0]; p.points.forEach((q) => { if (Math.abs(q.value - v) < Math.abs(b.value - v)) b = q; }); return b.label; }
    if (p.toggle) return v > (p.min + p.max) / 2 ? 'On' : 'Off';
    const a = Math.abs(v);
    let s = a >= 1000 ? (v / 1000).toFixed(a >= 10000 ? 1 : 2) + 'k' : a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2);
    if (p.unit === 'dB' && v > 0) s = '+' + s;
    return s + (p.unit && p.unit !== ':1' ? ' ' + p.unit : p.unit);
  }

  function render() {
    const t = HX.track(S.ui.trackId); if (!t || !root) return;
    headT.innerHTML = ''; headT.append(h('i', { style: { background: t.color } }), t.name);
    HX.$$('button', tabs).forEach((b) => b.classList.toggle('on', b.dataset.b === S.ui.bottom));
    chain.innerHTML = ''; knobRefs = [];
    if (S.ui.bottom === 'clip') return renderClip(t);
    HX.$('#devSub').textContent = t.devices.length + ' device' + (t.devices.length === 1 ? '' : 's') + ' · signal flows left → right' + (t.real && HX.mcp.connected ? ' · the engine\'s plug-ins' : '');
    t.devices.forEach((d, di) => {
      if (d.real && !d.loaded) HX.loadDeviceParams(t, d);
      chain.append(device(t, d, di));
    });
    const live = HX.mcp.connected && t.real && HX.liveEngine.plugins;
    const add = h('div.dev-add' + (live ? '.live' : ''), live ? { onclick: () => picker(t, add), 'data-info': 'Add a plug-in from the engine\'s list to ' + t.name } : null,
      live ? h('b', null, '+') : null, live ? 'Add a plug-in' : 'Drop an effect here', h('br'), h('span', { style: { color: 'var(--tx3)' } }, 'or double-click one in the browser'));
    chain.append(add);
  }
  HX.renderDevices = render;

  HX.REMOVE_ARM_MS = 4000;
  const removeArm = { key: null, until: 0, timer: null };      // the one armed Remove? button (track|device)
  function device(t, d, di) {
    const touched = HX.preview && HX.preview.touchesDevice(t.id, di);
    const el = h('div.dev' + (d.on ? '' : '.off') + (touched ? '.ai-touch' : ''), { 'data-di': di });
    const led = h('button.led', { 'aria-label': (d.on ? 'Bypass ' : 'Turn on ') + d.name + ' on ' + t.name, 'aria-pressed': String(!!d.on), 'data-info': (d.on ? 'Bypass ' : 'Turn on ') + d.name, onclick: () => HX.edit({ trackId: t.id, param: 'devOn', key: di }, !d.on, (d.on ? 'Bypass ' : 'Enable ') + d.name + ' on ' + t.name) });
    const del = h('button.dev-x', { 'aria-label': 'Remove ' + d.name + ' from ' + t.name + ' (press twice)', 'data-info': 'Remove ' + d.name + ' (click twice)' }, '×');
    /* the confirm stays armed for REMOVE_ARM_MS or until the pointer leaves the button; it is kept by track and
       device, so a refresh of the panel (the 3-second read) does not disarm it */
    const ak = t.id + '|' + d.id;
    const show = (on) => { del.classList.toggle('arm', on); del.textContent = on ? 'Remove?' : '×'; };
    const disarm = () => { if (removeArm.key === ak) { clearTimeout(removeArm.timer); removeArm.key = null; } show(false); };
    if (removeArm.key === ak && Date.now() < removeArm.until) show(true);
    del.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!(removeArm.key === ak && Date.now() < removeArm.until)) {
        clearTimeout(removeArm.timer);
        Object.assign(removeArm, { key: ak, until: Date.now() + HX.REMOVE_ARM_MS });
        removeArm.timer = setTimeout(() => { if (removeArm.key === ak) removeArm.key = null; const b = document.querySelector('.dev-x.arm'); if (b) { b.classList.remove('arm'); b.textContent = '×'; } }, HX.REMOVE_ARM_MS);
        show(true);
        return;
      }
      disarm();
      HX.liveEngine.removePlugin(t, d);
    });
    del.addEventListener('pointerleave', () => { if (del.isConnected) disarm(); });   // not when a refresh took the button away
    const title = h('div.dev-t', { 'data-info': d.name + (d.maker ? ' · ' + d.maker : '') + ' · drag the title to move it' }, led, h('b', null, d.name), h('small', null, d.real ? (d.post ? 'post · ' : '') + (d.index + 1) : kindLabel(d.kind)), del);
    el.append(title);
    bindMove(title, el, t, di);
    const body = h('div.dev-b');
    if (['eq', 'comp', 'reverb', 'limiter'].includes(d.kind)) {
      const cv = h('canvas.viz');
      body.append(cv);
      requestAnimationFrame(() => drawViz(cv, d));
      el._viz = { cv, d };
    }
    const MAX = 8, many = d.params.length > MAX;
    const ps = h('div.params', { style: { '--cols': d.params.length > 4 ? (d.expanded && d.params.length > 12 ? 4 : 3) : 2 } });
    if (d.real && !d.params.length) ps.append(h('span.label', { style: { gridColumn: '1/-1' } }, d.loaded ? 'No input controls' : 'Loading parameters…'));
    d.params.forEach((p, pi) => {
      if (many && !d.expanded && pi >= MAX) return;
      if (p.toggle) {
        const b = h('button.ptog' + (p.v > (p.min + p.max) / 2 ? '.on' : ''), { 'data-info': d.name + ' · ' + p.n + ' · click to switch' }, p.n);
        b.addEventListener('click', () => HX.edit({ trackId: t.id, param: 'devParam', key: [di, pi], realIndex: p.realIndex }, p.v > (p.min + p.max) / 2 ? p.min : p.max, t.name + ' · ' + d.name + ' ' + p.n));
        knobRefs.push({ t, di, pi, sync: () => b.classList.toggle('on', p.v > (p.min + p.max) / 2), el });
        ps.append(h('div.param', null, b));
        return;
      }
      const ai = HX.preview && HX.preview.touchesParam(t.id, di, pi);
      const k = h('div.knob' + (p.min < 0 && p.max > 0 ? '.bi' : ''), { 'data-info': d.name + ' · ' + p.n + ' · drag, shift = fine' + (p.def !== undefined ? '' : '') });
      const pv = h('span.pv');
      const wrap = h('div.param' + (ai ? '.ai' : ''), null, h('span.label', null, p.n), k, pv);
      const sync = () => { k.style.setProperty('--v', HX.clamp(toN(p, p.v), 0, 1)); pv.textContent = fmt(p, p.v); };
      sync();
      knobRefs.push({ t, di, pi, sync, el: el });
      const pts = p.points;
      const ix = (v) => { let b = 0; pts.forEach((q, i) => { if (Math.abs(q.value - v) < Math.abs(pts[b].value - v)) b = i; }); return b; };
      HX.bindDrag(k, () => ({ trackId: t.id, param: 'devParam', key: [di, pi], realIndex: p.realIndex }), {
        toPos: pts ? (v) => (pts.length > 1 ? ix(v) / (pts.length - 1) : 0) : (v) => HX.clamp(toN(p, v), 0, 1),
        fromPos: pts ? (n) => pts[Math.round(n * (pts.length - 1))].value : (n) => { const v = fromN(p, n); return p.labels || p.step ? Math.round(v) : Math.round(v * 1000) / 1000; },
        sens: pts ? 0.02 : 0.006,
        label: (o, v) => t.name + ' · ' + d.name + ' ' + p.n + ' ' + fmt(p, v),
      });
      ps.append(wrap);
    });
    if (many) ps.append(h('button.pmore', { style: { gridColumn: '1/-1' }, onclick: () => { d.expanded = !d.expanded; render(); }, 'data-info': 'Show ' + (d.expanded ? 'the first ' + MAX : 'all ' + d.params.length) + ' controls' }, d.expanded ? 'Fewer' : 'All ' + d.params.length));
    body.append(ps);
    if (d.outs && d.outs.length) {
      const outs = h('div.outs', { 'data-info': d.name + ' · readings from the plug-in (refreshed while shown)' });
      d.outs.slice(0, d.expanded ? 24 : 6).forEach((o) => { const v = h('span.mono'); o._el = v; outs.append(h('span.label', null, o.n), v); });
      el._outs = d;
      body.append(outs);
      syncOuts(d);
    }
    if (HX.sidechain) HX.sidechain.decorate(t, d, body);   /* sidechain source picker: js/sidechain.js */
    el.append(body);
    return el;
  }
  function syncOuts(d) {
    (d.outs || []).forEach((o) => {
      if (!o._el) return;
      const v = o.v, a = Math.abs(v);
      const txt = v <= -120 ? '−∞' : a >= 1000 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2);
      if (o._el.textContent !== txt) o._el.textContent = txt;
    });
  }
  HX.on('device-outs', (e) => { const t = HX.track(e.trackId); if (t && e.trackId === S.ui.trackId) syncOuts(t.devices[e.di]); });

  /* drag a device's title sideways to move it in the chain */
  function bindMove(handle, el, t, di) {
    handle.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || e.target.closest('button')) return;
      e.preventDefault();
      const x0 = e.clientX; let on = false, target = di, mark = null;
      const move = (ev) => {
        if (!on && Math.abs(ev.clientX - x0) < 6) return;
        if (!on) { on = true; el.classList.add('dragging'); mark = h('div.dev-drop'); chain.append(mark); }
        const ds = HX.$$('.dev', chain);
        target = ds.length;
        for (let i = 0; i < ds.length; i++) { const b = ds[i].getBoundingClientRect(); if (ev.clientX < b.left + b.width / 2) { target = i; break; } }
        const cr = chain.getBoundingClientRect(), ref = (ds[target] || ds[ds.length - 1]).getBoundingClientRect();
        mark.style.left = ((ds[target] ? ref.left - 3 : ref.right + 1) - cr.left + chain.scrollLeft) + 'px';
      };
      const up = () => {
        removeEventListener('pointermove', move); removeEventListener('pointerup', up); removeEventListener('pointercancel', up);
        if (!on) return;
        el.classList.remove('dragging'); mark && mark.remove();
        const to = target > di ? target - 1 : target;
        if (to !== di) HX.liveEngine.movePlugin(t, di, Math.min(to, t.devices.length - 1));
      };
      addEventListener('pointermove', move); addEventListener('pointerup', up); addEventListener('pointercancel', up);
    });
  }

  /* + in the chain: the engine's plug-ins, Hypnomix devices first */
  let pick = null;
  function closePick() { if (pick) { pick.remove(); pick = null; } }
  document.addEventListener('pointerdown', (e) => { if (pick && !pick.contains(e.target)) closePick(); });
  function picker(t, anchor) {
    closePick();
    const all = HX.liveEngine.plugins || [];
    const midi = t.kind === 'midi';
    const rank = (p) => (/^hypnomix/i.test(p.name) ? 0 : p.isEffect ? 1 : p.isInstrument ? (midi ? 1 : 3) : 2);
    const list = all.filter((p) => midi || !p.isInstrument && !p.needsMidiInput).sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
    const r = anchor.getBoundingClientRect();
    const q = h('input', { placeholder: 'Search the engine\'s plug-ins', spellcheck: 'false' });
    const ul = h('div.pick-list');
    let sel = 0, shown = [];
    const draw = () => {
      const s = q.value.toLowerCase();
      shown = list.filter((p) => !s || (p.name + ' ' + (p.creator || '') + ' ' + p.typeLabel).toLowerCase().includes(s)).slice(0, 60);
      sel = Math.min(sel, Math.max(0, shown.length - 1));
      ul.innerHTML = '';
      shown.forEach((p, i) => ul.append(h('div.pick-item' + (i === sel ? '.sel' : ''), { onclick: () => { closePick(); HX.liveEngine.addPlugin(t, p); } },
        h('span', null, p.name), h('small', null, (p.typeLabel || p.type) + (p.creator ? ' · ' + p.creator : '')))));
      if (!shown.length) ul.append(h('div.pick-item', { style: { color: 'var(--tx3)' } }, 'No matches'));
    };
    q.addEventListener('input', () => { sel = 0; draw(); });
    q.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Escape') closePick();
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); sel = HX.clamp(sel + (e.key === 'ArrowDown' ? 1 : -1), 0, shown.length - 1); draw(); }
      else if (e.key === 'Enter' && shown[sel]) { const p = shown[sel]; closePick(); HX.liveEngine.addPlugin(t, p); }
    });
    pick = h('div.hx-pick', { style: { left: Math.min(r.left, innerWidth - 300) + 'px', bottom: (innerHeight - r.top + 6) + 'px' } }, q, ul);
    document.body.append(pick); draw(); q.focus();
  }
  const kindLabel = (k) => ({ eq: 'EQ', comp: 'Dynamics', deess: 'Dynamics', sat: 'Drive', delay: 'Delay', reverb: 'Reverb', limiter: 'Dynamics', instrument: 'Instrument', hx: 'HypnoMix', plugin: 'Plug-in' }[k] || '');

  /* ── device visualisations ── */
  function drawViz(cv, d) {
    if (!cv.isConnected) return;
    const w = cv.clientWidth || 200, hh = cv.clientHeight || 110;
    const ctx = HX.fitCanvas(cv, w, hh);
    const grid = HX.css('--grid2'), tx3 = HX.css('--tx3'), acc = d.on ? HX.css('--acc') : HX.css('--tx3');
    ctx.clearRect(0, 0, w, hh);
    ctx.strokeStyle = grid; ctx.lineWidth = 1;
    if (d.kind === 'eq') {
      [100, 1000, 10000].forEach((f) => { const x = Math.round((Math.log10(f) - Math.log10(20)) / 3 * w) + 0.5; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, hh); ctx.stroke(); });
      ctx.beginPath(); ctx.moveTo(0, hh / 2 + 0.5); ctx.lineTo(w, hh / 2 + 0.5); ctx.stroke();
      const [lo, lm, hm, hi, hpf, out] = d.params.map((p) => p.v);
      const resp = (f) => {
        const lf = Math.log2(f);
        let g = lo / (1 + Math.pow(f / 120, 2)) + hi / (1 + Math.pow(9000 / f, 2));
        g += lm * Math.exp(-Math.pow(lf - Math.log2(420), 2) / 1.2) + hm * Math.exp(-Math.pow(lf - Math.log2(3100), 2) / 0.9);
        g += -24 * Math.max(0, 1 - Math.pow(f / hpf, 2)) - 3 / (1 + Math.pow(f / hpf, 4));
        return g + out;
      };
      ctx.beginPath();
      for (let x = 0; x <= w; x++) { const f = 20 * Math.pow(1000, x / w), y = hh / 2 - (resp(f) / 18) * (hh / 2); x ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
      ctx.strokeStyle = acc; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.lineTo(w, hh / 2); ctx.lineTo(0, hh / 2); ctx.closePath(); ctx.globalAlpha = 0.12; ctx.fillStyle = acc; ctx.fill(); ctx.globalAlpha = 1;
      ctx.fillStyle = tx3; ctx.font = '9px ' + HX.css('--mono'); ctx.fillText('100', (Math.log10(100) - Math.log10(20)) / 3 * w + 2, hh - 3); ctx.fillText('1k', (2 - Math.log10(20)) / 3 * w + 2, hh - 3); ctx.fillText('10k', (4 - Math.log10(20)) / 3 * w + 2, hh - 3);
    } else if (d.kind === 'comp' || d.kind === 'limiter') {
      const thr = d.kind === 'comp' ? d.params[0].v : d.params[1].v - d.params[0].v, ratio = d.kind === 'comp' ? d.params[1].v : 30;
      for (let k = 1; k < 4; k++) { ctx.beginPath(); ctx.moveTo(k * w / 4 + 0.5, 0); ctx.lineTo(k * w / 4 + 0.5, hh); ctx.moveTo(0, k * hh / 4 + 0.5); ctx.lineTo(w, k * hh / 4 + 0.5); ctx.stroke(); }
      ctx.beginPath(); ctx.strokeStyle = tx3; ctx.setLineDash([2, 3]); ctx.moveTo(0, hh); ctx.lineTo(w, 0); ctx.stroke(); ctx.setLineDash([]);
      ctx.beginPath();
      for (let x = 0; x <= w; x++) { const inDb = -48 + (x / w) * 48; const outDb = inDb < thr ? inDb : thr + (inDb - thr) / ratio; const y = hh - ((outDb + 48) / 48) * hh; x ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
      ctx.strokeStyle = acc; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.fillStyle = tx3; ctx.font = '9px ' + HX.css('--mono'); ctx.fillText((d.kind === 'comp' ? 'thr ' : 'ceil ') + thr.toFixed(1), 4, 11);
      cv._gr = true;
    } else if (d.kind === 'reverb') {
      const size = d.params[0].v / 100, decay = d.params[1].v, pre = d.params[2].v;
      ctx.fillStyle = acc;
      const x0 = (pre / 1000) * w * 3;
      for (let x = Math.floor(x0); x < w; x += 2) { const tt = (x - x0) / w * 3; const a = Math.exp(-tt * (6.9 / decay)) * (0.55 + 0.45 * size); const r = Math.sin(x * 12.9898) * 43758.5453; const n = 0.55 + 0.45 * (r - Math.floor(r)); ctx.globalAlpha = 0.7; ctx.fillRect(x, hh - a * n * (hh - 6), 1, a * n * (hh - 6)); }
      ctx.globalAlpha = 1; ctx.fillStyle = tx3; ctx.font = '9px ' + HX.css('--mono'); ctx.fillText('RT60 ' + decay.toFixed(1) + ' s', 4, 11);
    }
  }

  /* ── clip detail ── */
  function renderClip(t) {
    const f = S.ui.clipId && HX.findClip(S.ui.clipId);
    if (!f) { HX.$('#devSub').textContent = 'no clip selected'; chain.append(h('div.dev-add', { style: { width: '100%' } }, 'Select a clip in the Arrangement or Session view')); return; }
    const c = f.clip;
    HX.$('#devSub').textContent = c.name + ' · ' + (c.kind === 'midi' ? 'MIDI' : 'audio') + (c.real ? ' · region ' + c.id : ' · mock');
    const gain = h('span.val', { 'data-info': 'Clip gain · drag, double-click = 0 dB' }, HX.fmtDb(c.gainDb, true) + ' dB');
    HX.bindDrag(gain, () => ({ trackId: t.id, param: 'clipGain', key: c.id }), { min: -24, max: 12, sens: 0.1, step: 0.1, reset: 0, label: (o, v) => c.name + ' clip gain ' + HX.fmtDb(v, true) + ' dB' });
    const cv = h('canvas');
    const wrap = h('div.clipd', null,
      h('div.props', null,
        h('span', null, 'Name'), h('span', null, c.name),
        h('span', null, 'Start'), h('span', null, HX.bbtStr(c.start)),
        h('span', null, 'Length'), h('span', null, (c.len / 4).toFixed(2) + ' bars'),
        h('span', null, 'Gain'), h('span', null, gain),
        h('span', null, 'Fade in'), h('span', null, Math.round(HX.beatsToSec(c.fadeIn) * 1000) + ' ms'),
        h('span', null, 'Fade out'), h('span', null, Math.round(HX.beatsToSec(c.fadeOut) * 1000) + ' ms'),
        h('span', null, 'Source'), h('span', null, c.real ? 'HypnoMix DAW region' : 'mock peaks')),
      cv);
    chain.append(wrap);
    requestAnimationFrame(() => drawClipDetail(cv, t, c));
    HX._clipGainEl = gain;
  }
  function drawClipDetail(cv, t, c) {
    const w = cv.clientWidth, hh = cv.clientHeight;
    const ctx = HX.fitCanvas(cv, w, hh);
    ctx.fillStyle = HX.css('--bg1'); ctx.fillRect(0, 0, w, hh);
    ctx.fillStyle = HX.css('--grid2');
    for (let b = 0; b <= c.len; b++) ctx.fillRect(Math.round((b / c.len) * w), 0, 1, hh);
    ctx.fillStyle = t.color;
    if (c.kind === 'midi') {
      let lo = 127, hi = 0; c.notes.forEach((n) => { lo = Math.min(lo, n.pitch); hi = Math.max(hi, n.pitch); });
      const span = hi - lo + 3;
      c.notes.forEach((n) => { ctx.globalAlpha = 0.5 + n.vel / 254; ctx.fillRect((n.t / c.len) * w, ((hi + 1 - n.pitch) / span) * hh + 2, Math.max(2, (n.len / c.len) * w - 1), Math.max(2, hh / span - 1)); });
      ctx.globalAlpha = 1; return;
    }
    const P = c.peaks, g = HX.dbToGain(c.gainDb), mid = hh / 2;
    for (let x = 0; x < w; x++) {
      const i0 = Math.floor((x / w) * P.length), i1 = Math.max(i0 + 1, Math.floor(((x + 1) / w) * P.length));
      let m = 0, s = 0, n = 0; for (let i = i0; i < i1; i++) { m = Math.max(m, P[i]); s += P[i] * P[i]; n++; }
      const pk = Math.min(1, m * g) * (mid - 2), rms = Math.min(1, Math.sqrt(s / n) * 0.72 * g) * (mid - 2);
      ctx.globalAlpha = 0.45; ctx.fillRect(x, mid - pk, 1, pk * 2); ctx.globalAlpha = 1; ctx.fillRect(x, mid - rms, 1, rms * 2);
    }
  }

  HX.on('select', render);
  HX.on('bottom', render);
  HX.on('devices', render);
  HX.on('browser', render); // the engine's plug-in list arrived: the + tile can add
  HX.on('session', render);
  HX.on('theme', render);
  HX.on('preview', render);
  HX.on('param', (op) => {
    if (op.trackId !== S.ui.trackId) return;
    if (op.param === 'devParam') {
      knobRefs.filter((k) => k.di === op.key[0] && k.pi === op.key[1]).forEach((k) => k.sync());
      const el = chain.children[op.key[0]]; if (el && el._viz) drawViz(el._viz.cv, el._viz.d);
    } else if (op.param === 'devOn') render();
    else if (op.param === 'clipGain' && S.ui.bottom === 'clip' && HX._clipGainEl) {
      const f = HX.findClip(op.key); if (f) { HX._clipGainEl.textContent = HX.fmtDb(f.clip.gainDb, true) + ' dB'; drawClipDetail(chain.querySelector('canvas'), f.track, f.clip); }
    }
  });
  window.addEventListener('resize', () => { clearTimeout(render._t); render._t = setTimeout(render, 120); });
})();
