/* Hypnomix · Session view: clip grid (tracks × scenes), launches quantised to the next bar.
   Scenes come from the arrangement's sections. Launching is mocked: MCP has no trigger/cue tools yet. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  const COL = 118, SCN = 150;
  let root, grid, mix, note, slotEls = {}, mixRefs = {};

  HX.mountSession = function () {
    root = HX.$('#viewSession');
    root.innerHTML = '';
    grid = h('div.sg');
    mix = h('div.sg-mix');
    note = h('div.sg-note', { role: 'note' }, 'Clip launching is not wired to the engine yet: a click here only starts or moves the playhead; no clip is cued.');
    note.hidden = true;
    root.append(note, h('div.sg-scroll', null, grid), mix);
    render();
  };

  function render() {
    const tracks = S.session.tracks;
    grid.style.gridTemplateColumns = 'repeat(' + tracks.length + ', ' + COL + 'px) ' + SCN + 'px';
    grid.innerHTML = ''; slotEls = {};
    tracks.forEach((t) => grid.append(h('div.col-h' + (S.ui.trackId === t.id ? '.sel' : ''), { 'data-tid': t.id, onclick: () => HX.select(t.id), 'data-info': t.name + ' · click to select' }, h('i', { style: { background: t.color } }), t.name)));
    grid.append(h('div.col-h', { style: { justifyContent: 'flex-end', color: 'var(--tx2)' } }, 'Scenes'));
    S.scenes.forEach((sc, si) => {
      tracks.forEach((t, ti) => {
        const s = sc.slots[ti];
        let el;
        if (s) {
          el = h('div.slot.clip', { style: { '--c': t.color }, 'data-info': s.name + ' · click to launch (quantised to the next bar) · ' + sc.name },
            h('i.tri'), h('span', null, s.name), h('i.prog'));
          el.addEventListener('click', () => { HX.select(t.id, s.clipId); HX.launch(t.id, si); });
        } else {
          el = h('div.slot.empty', { 'data-info': 'Empty slot · click to stop this track\'s clip' });
          el.addEventListener('click', () => { HX.select(t.id); HX.stopTrackClip(t.id); });
        }
        slotEls[t.id + ':' + si] = el;
        grid.append(el);
      });
      const n = sc.slots.filter(Boolean).length;
      grid.append(h('div.scene', { onclick: () => HX.launchScene(si), 'data-info': 'Launch scene “' + sc.name + '” (' + n + ' clips) · keys 1–8' }, h('i.tri'), sc.name, h('small', null, (sc.len / 4) + ' bars')));
    });
    tracks.forEach((t) => grid.append(h('div.stoprow', { onclick: () => HX.stopTrackClip(t.id), 'data-info': 'Stop ' + t.name + ' clip' }, h('b'))));
    grid.append(h('div.stoprow', { onclick: () => Object.keys(S.launched).forEach(HX.stopTrackClip), 'data-info': 'Stop all clips' }, h('b')));
    renderMix();
    syncLaunch();
  }

  function renderMix() {
    mix.innerHTML = ''; mixRefs = {};
    S.session.tracks.forEach((t) => {
      const r = {};
      r.meter = h('canvas', { style: { width: '6px', height: '22px' } });
      r.vol = h('span.val'); r.pan = h('span.val', { style: { minWidth: '32px' } });
      r.m = h('button.tog.m', { 'aria-label': 'Mute ' + t.name, onclick: () => HX.edit({ trackId: t.id, param: 'mute' }, !t.mute, (t.mute ? 'Unmute ' : 'Mute ') + t.name) }, 'M');
      r.s = h('button.tog.s', { 'aria-label': 'Solo ' + t.name, onclick: () => HX.edit({ trackId: t.id, param: 'solo' }, !t.solo, (t.solo ? 'Unsolo ' : 'Solo ') + t.name) }, 'S');
      HX.bindDrag(r.vol, () => ({ trackId: t.id, param: 'fader' }), { toPos: HX.dbToPos, fromPos: (p) => Math.round(HX.posToDb(p) * 10) / 10, sens: 0.004, reset: 0, label: (o, v) => t.name + ' volume ' + HX.fmtDb(v) + ' dB' });
      HX.bindDrag(r.pan, () => ({ trackId: t.id, param: 'pan' }), { min: -1, max: 1, sens: 0.01, step: 0.02, reset: 0, label: (o, v) => t.name + ' pan ' + HX.fmtPan(v) });
      mix.append(h('div.cell', { style: { width: COL + 'px' } }, r.meter, h('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px' } }, r.vol, r.pan), h('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px', marginLeft: 'auto' } }, r.m, r.s)));
      mixRefs[t.id] = r; sync(t);
    });
    const m = S.session.master, r = { meter: h('canvas', { style: { width: '6px', height: '22px' } }), vol: h('span.val') };
    HX.bindDrag(r.vol, () => ({ trackId: m.id, param: 'fader' }), { toPos: HX.dbToPos, fromPos: (p) => Math.round(HX.posToDb(p) * 10) / 10, sens: 0.004, reset: 0, label: (o, v) => 'Master volume ' + HX.fmtDb(v) + ' dB' });
    mix.append(h('div.cell', { style: { width: SCN + 'px' } }, r.meter, h('span.label', null, 'Master'), r.vol));
    mixRefs[m.id] = r; sync(m);
  }
  function sync(t) {
    const r = mixRefs[t.id]; if (!r) return;
    r.vol.textContent = HX.fmtDb(t.faderDb);
    r.pan && (r.pan.textContent = HX.fmtPan(t.pan));
    r.m && r.m.classList.toggle('on', t.mute);
    r.s && r.s.classList.toggle('on', t.solo);
  }

  function syncLaunch() {
    Object.values(slotEls).forEach((el) => el.classList.remove('playing', 'queued', 'sel'));
    for (const tid in S.launched) {
      const L = S.launched[tid], el = slotEls[tid + ':' + L.scene];
      if (el) el.classList.add(L.queued ? 'queued' : 'playing');
    }
    S.scenes.forEach((sc, si) => S.session.tracks.forEach((t, ti) => { if (sc.slots[ti] && sc.slots[ti].clipId === S.ui.clipId) slotEls[t.id + ':' + si].classList.add('sel'); }));
    HX.$$('.col-h[data-tid]', grid).forEach((el) => el.classList.toggle('sel', el.dataset.tid === S.ui.trackId));
  }

  HX.on('launch', () => grid && syncLaunch());
  HX.on('select', () => grid && syncLaunch());
  HX.on('param', (op) => { const t = HX.track(op.trackId); t && sync(t); });
  HX.on('session', () => root && render());
  HX.on('live', () => { if (note) note.hidden = !HX.mcp.connected; });

  const mctx = new WeakMap();
  HX.onFrame((beat) => {
    if (S.ui.view !== 'session' || !grid) return;
    for (const tid in S.launched) {
      const L = S.launched[tid], el = slotEls[tid + ':' + L.scene];
      if (!el || L.queued) continue;
      const p = ((beat - L.startBeat) % L.len) / L.len;
      el.lastChild.style.width = (p * 100).toFixed(2) + '%';
    }
    for (const id in mixRefs) {
      const cv = mixRefs[id].meter, t = HX.track(id);
      if (!t) continue;
      let c = mctx.get(cv); if (!c) { c = HX.fitCanvas(cv, 6, 22); mctx.set(cv, c); HX.watchVisible(cv); cv._ep = -1; }
      HX.drawMeterIfChanged(cv, c, 6, 22, t.meter, { noTicks: true });
    }
  });
})();
