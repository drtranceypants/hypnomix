/* HypnoMix · Session view: clip grid (tracks × scenes), launches quantised to the next bar.
   On the engine (cues.js): the tracks' real cue slots (cue_list), launched with cue_launch / scene_launch / cue_stop,
   filled by dragging a region from the strip under the grid (or an audio file) onto a slot (cue_set_clip).
   On the mock session: scenes from the arrangement's sections, launched locally. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  const COL = 118, SCN = 150;
  let root, grid, mix, strip, slotEls = {}, navEls = {}, mixRefs = {}, engine = false;
  /* the keyboard: the grid is one Tab stop (a roving tabindex: the cell last focused holds it): the slots, each row's
     scene at its right and the stop buttons under them. Arrows move as the grid looks (left / right between tracks,
     up / down between slots), Enter or Space is a click, Delete or Backspace is the slot's ×; moving onto a track's
     slot selects that track, so the strip under the grid shows its regions. A region chip (a button) is picked with
     Enter, then Enter on a slot puts it there (as a drop does; Esc lets go). cells[row][col] is the grid as shown;
     focusKey ('trackId:row', 'scene:row', 'stop:trackId', 'stop:all') survives a redraw. */
  let cells = [], focusKey = null, pick = null;
  const live = () => !!(HX.cues && HX.cues.available());

  HX.mountSession = function () {
    root = HX.$('#viewSession');
    root.innerHTML = '';
    grid = h('div.sg');
    mix = h('div.sg-mix');
    strip = h('div.cue-strip');
    grid.setAttribute('role', 'group');
    grid.setAttribute('aria-label', 'Clip slots: arrow keys move, Enter or Space launches, Delete clears');
    grid.addEventListener('keydown', slotKey);
    grid.addEventListener('focusin', (e) => { const el = e.target.closest && e.target.closest('.cell-k'); if (el && el.dataset.key) { focusKey = el.dataset.key; rove(); } });
    root.append(h('div.sg-scroll', null, grid), strip, mix);
    render();
  };

  function render() {
    const refocus = !!(grid && grid.contains(document.activeElement) && document.activeElement.closest('.cell-k'));
    draw();
    rove();
    if (refocus) { const el = navEls[focusKey]; if (el) el.focus({ preventScroll: true }); }
  }
  function draw() {
    cells = [];
    engine = live();
    strip.hidden = !engine;
    if (engine) return renderEngine();
    const tracks = S.session.tracks;
    grid.style.gridTemplateColumns = 'repeat(' + tracks.length + ', ' + COL + 'px) ' + SCN + 'px';
    grid.innerHTML = ''; slotEls = {}; navEls = {};
    tracks.forEach((t) => grid.append(h('div.col-h' + (S.ui.trackId === t.id ? '.sel' : ''), { 'data-tid': t.id, onclick: (e) => HX.selectClick(e, t.id), 'data-info': t.name + ' · click to select (shift-click a range, ⌘-click one more)' }, h('i', { style: { background: t.color } }), t.name)));
    grid.append(h('div.col-h', { style: { justifyContent: 'flex-end', color: 'var(--tx2)' } }, 'Scenes'));
    S.scenes.forEach((sc, si) => {
      tracks.forEach((t, ti) => {
        const s = sc.slots[ti];
        let el;
        if (s) {
          el = h('div.slot.clip', { style: { '--c': t.color }, 'data-info': s.name + ' · click or Enter to launch (quantised to the next bar) · ' + sc.name },
            h('i.tri'), h('span', null, s.name), h('i.prog'));
          el.addEventListener('click', () => { HX.select(t.id, s.clipId); HX.launch(t.id, si); });
        } else {
          el = h('div.slot.empty', { 'data-info': 'Empty slot · click to stop this track\'s clip' });
          el.addEventListener('click', () => { HX.select(t.id); HX.stopTrackClip(t.id); });
        }
        cell(el, t, si, ti, t.name + ', slot ' + (si + 1) + ' (' + sc.name + '), ' + (s ? s.name : 'empty'));
        slotEls[t.id + ':' + si] = el;
        grid.append(el);
      });
      const n = sc.slots.filter(Boolean).length;
      const scn = h('div.scene', { onclick: () => HX.launchScene(si), 'data-info': 'Launch scene “' + sc.name + '” (' + n + ' clips) · keys 1–8' }, h('i.tri'), sc.name, h('small', null, (sc.len / 4) + ' bars'));
      cell(scn, null, si, tracks.length, 'Launch scene ' + (si + 1) + ', ' + sc.name + ', ' + n + ' clip' + (n === 1 ? '' : 's'), 'scene:' + si);
      grid.append(scn);
    });
    stopRow(tracks, S.scenes.length, () => Object.keys(S.launched).forEach(HX.stopTrackClip));
    renderMix(tracks);
    syncLaunch();
  }

  /* ── the engine's cue slots ── */
  const C = () => HX.cues;
  function renderEngine() {
    const tracks = C().columns(), rows = C().rows;
    grid.style.gridTemplateColumns = 'repeat(' + tracks.length + ', ' + COL + 'px) ' + SCN + 'px';
    grid.innerHTML = ''; slotEls = {}; navEls = {};
    tracks.forEach((t) => grid.append(h('div.col-h' + (S.ui.trackId === t.id ? '.sel' : ''), { 'data-tid': t.id, onclick: (e) => HX.selectClick(e, t.id), 'data-info': t.name + ' · click to select, shift-click a range, ⌘-click one more (its regions show under the grid, to drag into a slot)' }, h('i', { style: { background: t.color } }), t.name)));
    grid.append(h('div.col-h', { style: { justifyContent: 'flex-end', color: 'var(--tx2)' } }, 'Scenes'));
    for (let n = 0; n < rows; n++) {
      let filled = 0;
      tracks.forEach((t, ti) => {
        const s = C().slot(t.id, n);
        let el;
        if (s && !s.empty) {
          filled++;
          const x = h('button.cue-x', { tabindex: '-1', 'aria-label': 'Clear the slot of ' + t.name, 'data-info': 'Clear this slot (the clip goes; the Arrangement is not touched) · Delete on the focused slot', onclick: (e) => { e.stopPropagation(); HX.cueClear(t.id, n); } }, '×');
          el = h('div.slot.clip', { style: { '--c': t.color }, 'data-info': s.name + ' · click or Enter to launch (' + quantWords(s.quantize) + ') · ' + loopWords(s) + ' · Delete clears' },
            h('i.tri'), h('span', null, s.name), x, h('i.prog'));
          el.addEventListener('click', () => { HX.select(t.id, 'cue:' + t.id + ':' + n); HX.launch(t.id, n); });
        } else {
          el = h('div.slot.empty', { 'data-info': 'Empty slot · click to stop ' + t.name + '’s clip · drop a region or an audio file here' });
          el.addEventListener('click', () => { HX.select(t.id); HX.stopTrackClip(t.id); });
        }
        cell(el, t, n, ti, t.name + ', slot ' + (n + 1) + ', ' + (s && !s.empty ? s.name : 'empty'));
        el.addEventListener('dragover', (e) => { if (dragOk(e, t)) { e.preventDefault(); el.classList.add('drop'); } });
        el.addEventListener('dragleave', () => el.classList.toggle('drop', false));
        el.addEventListener('drop', (e) => { e.preventDefault(); el.classList.toggle('drop', false); HX.cueDrop(t.id, n, e); });
        slotEls[t.id + ':' + n] = el;
        grid.append(el);
      });
      const scn = h('div.scene', { onclick: () => HX.launchScene(n), 'data-info': 'Launch scene ' + (n + 1) + ' (' + filled + ' clips): every track’s clip in this row, on the bar · keys 1–8' }, h('i.tri'), 'Scene ' + (n + 1), h('small', null, filled ? filled + '' : ''));
      cell(scn, null, n, tracks.length, 'Launch scene ' + (n + 1) + ', ' + filled + ' clip' + (filled === 1 ? '' : 's'), 'scene:' + n);
      grid.append(scn);
    }
    stopRow(tracks, rows, () => HX.stopAllClips(), ' (on the bar)');
    renderMix(tracks);
    renderStrip();
    syncLaunch();
  }
  const dragOk = (e, t) => { const ty = Array.from(e.dataTransfer.types || []); return ty.includes('application/x-hx-region') || (ty.includes('Files') && t.kind === 'audio'); };
  const quantWords = (q) => ({ none: 'at once', bar: 'on the next bar', '2bars': 'on the next 2 bars', '4bars': 'on the next 4 bars', '8bars': 'on the next 8 bars', half: 'on the next half bar', beat: 'on the next beat', eighth: 'on the next eighth', sixteenth: 'on the next sixteenth' })[q] || 'quantised';
  const loopWords = (s) => s.followAction === 'again' ? 'loops' : s.followAction === 'stop' ? 'plays once' : 'then ' + s.followAction;

  /* the stop buttons under the grid: one per track, and Stop all under the scenes */
  function stopRow(tracks, row, stopAll, when) {
    tracks.forEach((t, ti) => {
      const el = h('div.stoprow', { onclick: () => HX.stopTrackClip(t.id), 'data-info': 'Stop ' + t.name + ' clip' + (when || '') }, h('b'));
      cell(el, null, row, ti, 'Stop the clip of ' + t.name, 'stop:' + t.id);
      grid.append(el);
    });
    const all = h('div.stoprow', { onclick: stopAll, 'data-info': 'Stop all clips' + (when || '') }, h('b'));
    cell(all, null, row, tracks.length, 'Stop all clips', 'stop:all');
    grid.append(all);
  }
  function cell(el, t, row, col, label, key) {
    el.dataset.key = key || t.id + ':' + row;
    if (t) el.dataset.tid = t.id;
    el.classList.add('cell-k');
    navEls[el.dataset.key] = el;
    el.dataset.label = label;
    el.setAttribute('role', 'button');
    el.setAttribute('aria-label', label);
    el.tabIndex = -1;
    (cells[row] || (cells[row] = []))[col] = el;
  }
  /* one slot holds the Tab stop: the one last focused, else the first */
  function rove() {
    let keep = focusKey && navEls[focusKey];
    if (!keep) { keep = cells[0] && cells[0][0]; focusKey = keep ? keep.dataset.key : null; }
    for (const k in navEls) navEls[k].tabIndex = navEls[k] === keep ? 0 : -1;
  }
  /* a region chip picked by keyboard (or a click): Enter on a slot puts it there, the same call as a drop */
  function setPick(p) {
    pick = p;
    if (strip) strip.querySelectorAll('.cue-chip').forEach((c) => c.setAttribute('aria-pressed', String(!!(p && c.getAttribute('data-rid') === p.regionId))));
  }
  function where(el) {
    for (let r = 0; r < cells.length; r++) { const c = (cells[r] || []).indexOf(el); if (c >= 0) return [r, c]; }
    return null;
  }
  function slotKey(e) {
    const el = e.target;
    if (!el.classList || !el.classList.contains('cell-k') || e.altKey || e.metaKey || e.ctrlKey) return;
    if (HX.keyboardFocus && !HX.keyboardFocus()) return;   /* a slot the mouse just clicked: Space still plays, arrows still move */
    const at = where(el); if (!at) return;
    let r = at[0], c = at[1];
    const k = e.key;
    if (k === 'Escape' && pick) { e.preventDefault(); e.stopPropagation(); setPick(null); HX.toast('Let go of the region'); return; }
    if (k === 'Enter' && pick && el.classList.contains('slot') && engine) {
      e.preventDefault(); e.stopPropagation();
      if (e.repeat) return;
      const p = pick, tid = el.dataset.tid, n = +el.dataset.key.slice(el.dataset.key.lastIndexOf(':') + 1);
      setPick(null);
      HX.cuePut(tid, n, p.regionId);                   /* the same call, toasts and unsaved mark as a drop on the slot */
      return;
    }
    if (k === 'Enter' || k === ' ') {
      e.preventDefault(); e.stopPropagation();
      if (!e.repeat) el.click();                       /* the same as a click: launch, stop the track on an empty slot, a scene, a stop button */
      return;
    }
    if (k === 'Delete' || k === 'Backspace') {
      e.preventDefault(); e.stopPropagation();
      if (e.repeat) return;
      const x = el.querySelector('.cue-x');
      if (x) x.click();                                /* the slot's own ×: the same call, toast and unsaved mark */
      else if (el.classList.contains('clip')) HX.toast('Slots are cleared on the engine (the demo song keeps its clips)');
      return;
    }
    const row = (i) => cells[i] || [];
    if (k === 'ArrowUp') r = Math.max(0, r - 1);
    else if (k === 'ArrowDown') r = Math.min(cells.length - 1, r + 1);
    else if (k === 'ArrowLeft') c = Math.max(0, c - 1);
    else if (k === 'ArrowRight') c = Math.min(row(r).length - 1, c + 1);
    else if (k === 'Home') { c = 0; if (e.shiftKey) r = 0; }
    else if (k === 'End') { c = row(r).length - 1; if (e.shiftKey) r = cells.length - 1; }
    else if (k === 'PageUp') r = 0;
    else if (k === 'PageDown') r = cells.length - 1;
    else return;                                       /* 1-8, M, S, ? and the rest stay the page's keys */
    e.preventDefault(); e.stopPropagation();
    const to = row(r)[Math.min(c, row(r).length - 1)];
    if (to && to !== el) {
      focusKey = to.dataset.key; rove(); to.focus(); to.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      if (to.dataset.tid && to.dataset.tid !== S.ui.trackId && HX.select) HX.select(to.dataset.tid);   /* the strip under the grid follows */
    }
  }
  /* what a screen reader hears follows the lights: queued, playing, stopping */
  function speak(el) {
    const st = el.classList.contains('stopping') ? ', stopping' : el.classList.contains('playing') ? ', playing' : el.classList.contains('queued') ? ', queued' : '';
    const v = (el.dataset.label || '') + st;
    if (el.getAttribute('aria-label') !== v) el.setAttribute('aria-label', v);
  }

  function renderStrip() {
    if (!engine || !strip) return;
    strip.innerHTML = '';
    const t = HX.track(S.ui.trackId);
    const clips = t && t.real && t.clips ? t.clips.filter((c) => c.real && !c.temp && (c.kind === 'audio' || c.kind === 'midi')) : [];
    strip.append(h('span.label', null, t ? t.name + ' regions' : 'Select a track'));
    if (!clips.length) strip.append(h('span.hint', null, t ? 'no regions on this track: drop an audio file from the Finder on a slot instead' : ''));
    clips.slice(0, 60).forEach((c) => {
      const chip = h('button.cue-chip', { type: 'button', draggable: 'true', style: { '--c': t.color }, 'data-rid': c.id, 'aria-pressed': String(!!(pick && pick.regionId === c.id)),
        'aria-label': 'Region ' + c.name + ' of ' + t.name + ': Enter picks it, then Enter on a slot puts it there',
        'data-info': 'Drag ' + c.name + ' onto a slot, or press it (Enter) and then Enter on a slot: a copy goes into it (trimming the region later does not change the clip)' }, c.name);
      chip.addEventListener('dragstart', (e) => { e.dataTransfer.setData('application/x-hx-region', c.id); e.dataTransfer.effectAllowed = 'copy'; });
      chip.addEventListener('click', () => {
        if (pick && pick.regionId === c.id) { setPick(null); return; }
        setPick({ regionId: c.id, name: c.name });
        HX.toast('Picked ' + c.name + ': press Enter on a slot to put it there (Esc lets go)', 3600);
        const back = navEls[focusKey]; if (back) back.focus();   /* back to the grid, where the arrows choose the slot */
      });
      strip.append(chip);
    });
    if (clips.length > 60) strip.append(h('span.hint', null, '+ ' + (clips.length - 60) + ' more'));
    if (C().error) strip.append(h('span.hint.err', null, 'cue slots: ' + C().error));
  }

  function renderMix(tracks) {
    mix.innerHTML = ''; mixRefs = {};
    tracks.forEach((t) => {
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
    if (engine) return syncEngine();
    Object.values(slotEls).forEach((el) => el.classList.remove('playing', 'queued', 'sel'));
    for (const tid in S.launched) {
      const L = S.launched[tid], el = slotEls[tid + ':' + L.scene];
      if (el) el.classList.add(L.queued ? 'queued' : 'playing');
    }
    S.scenes.forEach((sc, si) => S.session.tracks.forEach((t, ti) => { if (sc.slots[ti] && sc.slots[ti].clipId === S.ui.clipId) slotEls[t.id + ':' + si].classList.add('sel'); }));
    Object.values(slotEls).forEach(speak);
    HX.$$('.col-h[data-tid]', grid).forEach((el) => el.classList.toggle('sel', HX.isTrackSelected(el.dataset.tid)));
  }

  function syncEngine() {
    for (const k in slotEls) {
      const el = slotEls[k], i = k.lastIndexOf(':'), s = C().slot(k.slice(0, i), +k.slice(i + 1));
      const st = s && s.state;
      el.classList.toggle('playing', st === 'running' || st === 'waiting_to_stop' || st === 'waiting_to_switch' || st === 'stopping');
      el.classList.toggle('queued', !!(s && s.queued) || st === 'waiting_to_start' || st === 'waiting_for_retrigger');
      el.classList.toggle('stopping', st === 'waiting_to_stop' || st === 'waiting_to_switch');
      el.classList.toggle('sel', S.ui.clipId === 'cue:' + k);
      speak(el);
    }
    HX.$$('.col-h[data-tid]', grid).forEach((el) => el.classList.toggle('sel', HX.isTrackSelected(el.dataset.tid)));
  }

  HX.on('launch', () => grid && syncLaunch());
  HX.on('select', () => { if (!grid) return; syncLaunch(); if (engine) renderStrip(); });
  HX.on('param', (op) => { const t = HX.track(op.trackId); t && sync(t); });
  HX.on('session', () => root && render());
  HX.on('live', () => root && live() !== engine && render());
  HX.on('cues-structure', () => root && render());
  HX.on('cues-error', () => { if (grid && engine) renderStrip(); });
  HX.on('cues', () => { if (!grid) return; if (live() !== engine) render(); else syncLaunch(); });

  const mctx = new WeakMap();
  HX.onFrame((beat) => {
    if (S.ui.view !== 'session' || !grid) return;
    if (engine) {
      for (const k in slotEls) {
        const i = k.lastIndexOf(':'), s = C().slot(k.slice(0, i), +k.slice(i + 1)), bar = slotEls[k].lastChild;
        const f = s && !s.empty ? C().fraction(s) : null;
        if (bar && bar.classList.contains('prog')) bar.style.width = f == null ? '0' : (f * 100).toFixed(2) + '%';
      }
    } else for (const tid in S.launched) {
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
