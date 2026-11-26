/* Hypnomix · Mixer. Faders use Ardour's fader law (+6 dB top); meters are IEC-style, three hard colour zones,
   peak (light) over RMS (solid) when the engine computes RMS, with peak hold.
   Strips: colour (click the chip), order (drag the name sideways), delete (×, asks first), every send. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  let root, refs = {};

  HX.mountMixer = function () { root = HX.$('#viewMixer'); render(); };

  function render() {
    if (!root) return;
    const sx = root.scrollLeft;
    for (const id in refs) HX.unwatchVisible(refs[id].el);
    root.innerHTML = ''; refs = {};
    const mx = h('div.mx');
    S.session.tracks.forEach((t, i) => mx.append(strip(t, i + 1, null, 'tracks')));
    mx.append(h('div.mx-gap'));
    S.session.returns.forEach((t, i) => mx.append(strip(t, String.fromCharCode(65 + i), 'return', 'returns')));
    mx.append(h('div.mx-gap'));
    mx.append(strip(S.session.master, 'M', 'master'));
    root.append(mx);
    root.scrollLeft = sx;
  }

  function knob(cls, info) {
    const k = h('div.knob.sm' + (cls || ''), { 'data-info': info });
    k._set = (v) => k.style.setProperty('--v', v);
    return k;
  }

  /* ── colour ── */
  let pop = null;
  function closePop() { if (pop) { pop.remove(); pop = null; } }
  document.addEventListener('pointerdown', (e) => { if (pop && !pop.contains(e.target)) closePop(); });
  function colourPicker(t, anchor) {
    closePop();
    const r = anchor.getBoundingClientRect();
    pop = h('div.hx-swatches', { style: { left: Math.min(r.left, innerWidth - 176) + 'px', top: r.bottom + 4 + 'px' } });
    HX.liveEngine.PALETTE.forEach((c) => pop.append(h('button', {
      style: { background: c }, 'data-info': c, class: c === t.color ? 'on' : null,
      onclick: () => { closePop(); HX.edit({ trackId: t.id, param: 'color' }, c, t.name + ' colour'); },
    })));
    document.body.append(pop);
  }

  /* ── order: drag a strip's name sideways ── */
  function bindReorder(handle, el, t, group) {
    if (!group) return;
    handle.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || e.target.closest('button,.chip')) return;
      e.preventDefault();
      const x0 = e.clientX;
      let on = false, mark = null, target = -1;
      const peers = () => HX.$$('.strip[data-group="' + group + '"]', root);
      const move = (ev) => {
        if (!on && Math.abs(ev.clientX - x0) < 6) return;
        if (!on) { on = true; el.classList.add('dragging'); mark = h('div.mx-drop'); root.append(mark); }
        const ps = peers();
        target = ps.length;
        for (let i = 0; i < ps.length; i++) { const b = ps[i].getBoundingClientRect(); if (ev.clientX < b.left + b.width / 2) { target = i; break; } }
        const ref = ps[target] ? ps[target].getBoundingClientRect() : ps[ps.length - 1].getBoundingClientRect();
        const rr = root.getBoundingClientRect();
        mark.style.left = ((ps[target] ? ref.left : ref.right) - rr.left + root.scrollLeft - 1) + 'px';
      };
      const up = () => {
        removeEventListener('pointermove', move); removeEventListener('pointerup', up); removeEventListener('pointercancel', up);
        if (!on) return;
        el.classList.remove('dragging'); mark && mark.remove();
        const arr = S.session[group];
        const from = arr.indexOf(t);
        let to = target > from ? target - 1 : target;
        if (to === from || to < 0) return;
        const ids = arr.map((x) => x.id); ids.splice(from, 1); ids.splice(to, 0, t.id);
        const all = group === 'tracks' ? [...ids, ...S.session.returns.map((x) => x.id)] : [...S.session.tracks.map((x) => x.id), ...ids];
        HX.edit({ trackId: '*', param: 'order' }, all, 'Move ' + t.name);
      };
      addEventListener('pointermove', move); addEventListener('pointerup', up); addEventListener('pointercancel', up);
    });
  }

  function strip(t, num, cls, group) {
    const r = {};
    const el = h('div.strip' + (cls ? '.' + cls : ''), { style: { '--c': t.color }, 'data-group': group || null, role: 'group', 'aria-label': t.name, onpointerdown: () => HX.select(t.id) });
    r.el = el;
    r.chip = h('button.chip', { 'data-info': 'Track colour · click to choose', 'aria-label': 'Colour of ' + t.name, onclick: (e) => { e.stopPropagation(); colourPicker(t, r.chip); } });
    const name = h('div.s-name', { 'data-info': t.name + (group ? ' · drag sideways to move' : '') },
      t.isMaster ? null : r.chip, h('span', null, t.name),
      t.isMaster ? null : h('button.s-del', { 'data-info': 'Delete ' + t.name + ' (asks first)', 'aria-label': 'Delete ' + t.name, onclick: (e) => { e.stopPropagation(); HX.deleteTrack(t); } }, '×'));
    el.append(name);
    bindReorder(name, el, t, group);
    // inserts
    const ins = h('div.s-sec');
    const show = () => { HX.select(t.id); S.ui.bottom = 'devices'; HX.emit('bottom'); };
    t.devices.slice(0, 4).forEach((d) => ins.append(h('div.ins' + (d.on ? '' : '.off'), { 'data-info': d.name + ' · click to show in the device chain', onclick: show }, h('i'), d.name)));
    if (t.devices.length > 4) ins.append(h('div.ins.more', { onclick: show, 'data-info': 'Show every device' }, '+' + (t.devices.length - 4) + ' more'));
    for (let i = t.devices.length; i < 3; i++) ins.append(h('div.ins.empty', null, '—'));
    el.append(ins);
    // sends + pan
    const sp = h('div.s-sec');
    r.sends = [];
    if (t.sends.length) {
      t.sends.forEach((s, si) => {
        const k = knob('', 'Send to ' + s.name + ' · drag, double-click = off');
        const v = h('span.mono.sv');
        HX.bindDrag(k, () => ({ trackId: t.id, param: 'send', key: s.index }), { toPos: HX.dbToPos, fromPos: (p) => Math.round(HX.posToDb(p) * 10) / 10, sens: 0.005, reset: -193, label: (o, val) => t.name + ' → ' + s.name + ' ' + HX.fmtDb(val) + ' dB' });
        sp.append(h('div.sendrow', null, h('span.label', { title: s.name }, String.fromCharCode(65 + si) + ' · ' + s.name), k), h('div.sendrow', null, h('span'), v));
        r.sends.push({ k, v, index: s.index });
      });
    } else sp.append(h('div.sendrow', { style: { height: '20px' } }, h('span.label', null, t.isMaster ? 'Stereo out' : t.isReturn ? 'Post fader' : 'No sends')));
    if (!t.isMaster) {
      r.pan = knob('.bi', 'Pan · drag, double-click = centre');
      r.panV = h('span.mono.sv');
      HX.bindDrag(r.pan, () => ({ trackId: t.id, param: 'pan' }), { min: -1, max: 1, sens: 0.01, step: 0.02, reset: 0, label: (o, v) => t.name + ' pan ' + HX.fmtPan(v) });
      sp.append(h('div.sendrow', null, h('span.label', null, 'Pan'), r.pan), h('div.sendrow', null, h('span'), r.panV));
    }
    el.append(sp);
    // fader + meter
    const scale = h('div.scale');
    [6, 0, -6, -12, -24, -48].forEach((d) => scale.append(h('span', { style: { top: (100 - HX.dbToPos(d) * 100).toFixed(2) + '%' } }, d > 0 ? '+' + d : String(d))));
    r.cap = h('div.cap');
    r.ghost = h('div.ghost');
    r.fader = h('div.fader', { 'data-info': t.name + ' volume · drag, shift = fine, double-click = 0 dB' }, h('div.track'), r.ghost, r.cap);
    r.meter = h('canvas.meter');
    const fw = h('div.fader-wrap', null, scale, r.fader, h('div', { style: { position: 'relative' } }, r.meter));
    el.append(fw);
    HX.bindDrag(r.fader, () => ({ trackId: t.id, param: 'fader' }), { toPos: HX.dbToPos, fromPos: (p) => Math.round(HX.posToDb(p) * 10) / 10, get sens() { return 1 / Math.max(60, r.fader.clientHeight - 8); }, reset: 0, label: (o, v) => t.name + ' volume ' + HX.fmtDb(v) + ' dB' });
    // foot
    r.peak = h('div.peak', { 'data-info': 'Peak hold · click to reset', onclick: () => { t.meter.pk = -100; t.meter.clip = false; } }, '-∞');
    r.vol = h('span.val', { 'data-info': 'Volume (dB)' });
    HX.bindDrag(r.vol, () => ({ trackId: t.id, param: 'fader' }), { toPos: HX.dbToPos, fromPos: (p) => Math.round(HX.posToDb(p) * 10) / 10, sens: 0.004, reset: 0, label: (o, v) => t.name + ' volume ' + HX.fmtDb(v) + ' dB' });
    const row = h('div.row');
    if (!t.isMaster) {
      r.m = h('button.tog.m', { onclick: () => HX.edit({ trackId: t.id, param: 'mute' }, !t.mute, (t.mute ? 'Unmute ' : 'Mute ') + t.name), 'data-info': 'Mute', 'aria-label': 'Mute ' + t.name }, 'M');
      r.s = h('button.tog.s', { onclick: () => HX.edit({ trackId: t.id, param: 'solo' }, !t.solo, (t.solo ? 'Unsolo ' : 'Solo ') + t.name), 'data-info': 'Solo', 'aria-label': 'Solo ' + t.name }, 'S');
      row.append(r.m, r.s);
      if (!t.isReturn) { r.r = h('button.tog.r', { onclick: () => HX.edit({ trackId: t.id, param: 'arm' }, !t.arm, (t.arm ? 'Disarm ' : 'Arm ') + t.name), 'data-info': 'Record arm', 'aria-label': 'Record arm ' + t.name }, '●'); row.append(r.r); }
    }
    el.append(h('div.s-foot', null, r.peak, r.vol, row, h('div.num-id', null, String(num))));
    HX.watchVisible(el);
    refs[t.id] = r; sync(t);
    return el;
  }

  function sync(t) {
    const r = refs[t.id]; if (!r) return;
    r.el.classList.toggle('sel', S.ui.trackId === t.id);
    r.el.style.setProperty('--c', t.color);
    const p = HX.dbToPos(t.faderDb);
    const capTop = (q) => 'calc(4px + ' + ((1 - q) * 100).toFixed(3) + '% - ' + ((1 - q) * 8).toFixed(2) + 'px)';
    r.cap.style.top = capTop(p);
    const g = HX.preview && HX.preview.target(t.id, 'fader');
    r.ghost.classList.toggle('on', g != null);
    if (g != null) r.ghost.style.top = capTop(HX.dbToPos(g));
    r.vol.textContent = HX.fmtDb(t.faderDb);
    r.fader.classList.toggle('ai', !!(HX.preview && HX.preview.touches(t.id, 'vol')));
    r.vol.classList.toggle('ai', !!(HX.preview && HX.preview.touches(t.id, 'vol')));
    r.sends.forEach((x) => {
      const s = t.sends.find((s) => s.index === x.index); if (!s) return;
      x.k._set(HX.dbToPos(s.db)); x.v.textContent = HX.fmtDb(s.db) + ' dB';
      x.k.style.setProperty('--c', HX.preview && HX.preview.touches(t.id, 'send') ? 'var(--ai)' : 'var(--acc)');
    });
    if (r.pan) { r.pan._set((t.pan + 1) / 2); r.panV.textContent = HX.fmtPan(t.pan); }
    r.m && (r.m.classList.toggle('on', t.mute), r.m.setAttribute('aria-pressed', String(!!t.mute)));
    r.s && (r.s.classList.toggle('on', t.solo), r.s.setAttribute('aria-pressed', String(!!t.solo)));
    r.r && (r.r.classList.toggle('on', t.arm), r.r.setAttribute('aria-pressed', String(!!t.arm)));
  }

  HX.on('param', (op) => { if (op.param === 'devOn') return render(); const t = HX.track(op.trackId); t && sync(t); });
  HX.on('select', () => HX.allTracks().forEach(sync));
  HX.on('preview', () => HX.allTracks().forEach(sync));
  HX.on('session', () => root && render());

  /* a WeakMap: a strip that is re-built (every structural change) takes its canvas context with it */
  const ctxs = new WeakMap();
  HX.onFrame((beat, dt, now) => {
    if (S.ui.view !== 'mixer' || !root) return;
    for (const id in refs) {
      const r = refs[id], t = HX.track(id); if (!t) continue;
      if (!HX.isVisible(r.el)) continue;               // a strip scrolled out of view costs nothing
      const cv = r.meter, w = cv.clientWidth, hh = cv.clientHeight;
      let c = ctxs.get(cv);
      if (!c || cv._w !== w || cv._h !== hh) { c = HX.fitCanvas(cv, w, hh); ctxs.set(cv, c); cv._w = w; cv._h = hh; cv._ep = -1; }
      HX.drawMeterIfChanged(cv, c, w, hh, t.meter);
      const pk = t.meter.pk;
      const txt = pk < -70 ? '-∞' : (pk > 0 ? '+' : '') + pk.toFixed(1);
      if (r.peak.textContent !== txt) r.peak.textContent = txt;
      r.peak.classList.toggle('clip', pk > -0.1 || !!t.meter.clip);
    }
  });
})();
