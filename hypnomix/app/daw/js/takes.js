/* HypnoMix · take lanes under a track, and comping from them (Live's take lanes, on the engine's take playlists).

   On the engine a track's takes are its playlists named "<track>.take N" (take_list); the track plays its comp
   (its active playlist). Each take is a lane under the track (the T button on the track header shows or hides
   them). Drag across a take lane to comp that range onto the comp: one `comp_range` call, ONE engine undo step
   ("comp range"), with a 10 ms crossfade centred on each join. By keyboard: the Comp button on a take's header asks
   for the bars (the loop range to start with) and makes the same comp. The parts of a take the comp plays are lit.
   The comp's regions stay ordinary regions: every fix afterwards is a clip edit on them.

   With the mock session a vocal track gets three invented takes and the comp is done locally.
   Hooks: arrange.js (rows, headers, the T button, drawing and the pointer), store.js (HX.findClip also finds take
   regions, so their peaks load), regions.js (HX.loadClipPeaks). */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  const LANE_H = 40, XFADE_MS = 10;

  const T = (HX.takes = {
    data: {},              // trackId → { compId, compName, takes: [{ id, name, n, clips: [clip], used: [[b0, b1]] }] }
    drag: null,            // { trackId, takeId, b0, b1 } while a range is being dragged
    XFADE_MS,
  });

  /* which tracks show their takes: remembered per session in this browser (a convenience only) */
  const KEY = 'hx.takes.shown';
  const shownMemo = (() => { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; } })();
  const memoKey = (t) => (S.session ? S.session.name : '') + '|' + t.id;
  T.shown = (t) => !!(t && t.showTakes);
  function setShown(t, on) {
    t.showTakes = on;
    shownMemo[memoKey(t)] = on;
    try { localStorage.setItem(KEY, JSON.stringify(shownMemo)); } catch (e) {}
    HX.renderArrangeHeaders && HX.renderArrangeHeaders();
  }

  const spb = () => (S.session.sampleRate * 60) / S.session.tempo;

  /* ── arrange.js hooks ── */
  T.rows = function (t, y) {
    const d = T.data[t.id];
    if (!d || !T.shown(t)) return [];
    return d.takes.map((k, i) => ({ t, y: y + i * LANE_H, hgt: LANE_H, lane: true, take: k }));
  };
  T.count = (t) => { const d = T.data[t.id]; return d ? d.takes.length : 0; };

  T.toggle = function (t) {
    const n = T.count(t);
    if (!n || t.isReturn || t.isMaster) return null;
    const b = h('button.tog.tk', { 'data-info': (T.shown(t) ? 'Hide' : 'Show') + ' the ' + n + ' take lane' + (n > 1 ? 's' : '') + ' of ' + t.name + ' · drag across a take to comp that range',
      onclick: (e) => { e.stopPropagation(); setShown(t, !T.shown(t)); } }, 'T');
    b.classList.toggle('on', T.shown(t));
    b.setAttribute('aria-label', 'Take lanes of ' + t.name);
    b.setAttribute('aria-pressed', String(T.shown(t)));
    return b;
  };

  /* the parts of a take the comp plays: from the engine's regions (same file, same alignment), or on the mock
     the comp clips that came from this take */
  const spans = (t, k) => (HX.mcp.connected ? k.used : t.clips.filter((c) => c.take === k.n).map((c) => [c.start, c.start + c.len]));

  T.headers = function (t) {
    return T.rows(t, 0).map((r) => {
      const k = r.take;
      const inComp = spans(t, k).length > 0;
      const comp = h('button.take-comp', { type: 'button', 'aria-label': 'Comp from take ' + k.n + ' of ' + t.name + ': choose the bars',
        'data-info': 'Comp from take ' + k.n + ' by keyboard: asks for the bars (the loop range to start with), the same as a drag across the lane',
        onpointerdown: (e) => e.stopPropagation(), onclick: (e) => { e.stopPropagation(); T.compAsk(t, k); } }, 'Comp');
      return h('div.th.take', { style: { height: LANE_H + 'px' }, role: 'group', 'aria-label': 'Take ' + k.n + ' of ' + t.name + (inComp ? ', in the comp' : ''), 'data-hk': 'take:' + t.id + ':' + k.id,
        'data-info': k.name + ' · drag across this lane to comp that range onto ' + t.name + ' (one undo step, ' + XFADE_MS + ' ms crossfades), or press Comp',
        onpointerdown: () => HX.select(t.id) },
        h('i.chip', { style: { background: t.color, opacity: 0.45 } }),
        h('div.th-name', null, h('b', null, 'Take ' + k.n), h('small', null, k.clips.length + ' clip' + (k.clips.length === 1 ? '' : 's') + (inComp ? ' · in the comp' : ''))),
        comp);
    });
  };

  T.drawLane = function (ctx, r, g) {
    const { X, w, colors, drawClip } = g;
    const k = r.take;
    ctx.fillStyle = colors.light ? 'rgba(0,0,0,.03)' : 'rgba(0,0,0,.18)';
    ctx.fillRect(0, r.y, w, r.hgt);
    /* what the comp plays from this take */
    ctx.fillStyle = colors['--acc-2'];
    for (const [b0, b1] of spans(r.t, k)) { const x0 = X(b0), x1 = X(b1); if (x1 >= 0 && x0 <= w) ctx.fillRect(x0, r.y, x1 - x0, r.hgt); }
    ctx.globalAlpha = 0.75;
    for (const c of k.clips) {
      const x0 = X(c.start), x1 = X(c.start + c.len);
      if (x1 < 0 || x0 > w) continue;
      drawClip(ctx, r.t, c, x0, r.y + 1, x1 - x0, r.hgt - 2);
    }
    ctx.globalAlpha = 1;
    const d = T.drag;
    if (d && d.trackId === r.t.id && d.takeId === k.id) {
      const a = Math.min(d.b0, d.b1), b = Math.max(d.b0, d.b1);
      ctx.fillStyle = colors['--acc']; ctx.globalAlpha = 0.28;
      ctx.fillRect(X(a), r.y, (b - a) * S.ui.zoom, r.hgt); ctx.globalAlpha = 1;
      ctx.fillRect(Math.round(X(a)), r.y, 1, r.hgt); ctx.fillRect(Math.round(X(b)), r.y, 1, r.hgt);
    }
    ctx.fillStyle = colors['--line']; ctx.fillRect(0, r.y + r.hgt - 1, w, 1);
  };

  T.info = (hit) => hit.row.take.name + ' · drag across it to comp that range onto ' + hit.row.t.name + ' (⌘ = no snap) · one undo step';

  /* drag across a take lane → comp [b0, b1) */
  T.pointerDown = function (e, hit, g) {
    const { rect, B, snap, lanesWrap } = g;
    const t = hit.row.t, k = hit.row.take;
    HX.select(t.id);
    const sn = (b, ev) => (ev.metaKey || ev.altKey ? b : snap(b));
    const b0 = Math.max(0, sn(hit.beat, e));
    T.drag = { trackId: t.id, takeId: k.id, b0, b1: b0 };
    lanesWrap.setPointerCapture(e.pointerId);
    /* the session can be read again mid-drag (a group made, an engine restart): the drag is then dropped, quietly */
    const mv = (ev) => { if (!T.drag) return; T.drag.b1 = Math.max(0, sn(B(ev.clientX - rect.left), ev)); HX.arrange.dirty = true; };
    const up = () => {
      lanesWrap.removeEventListener('pointermove', mv); lanesWrap.removeEventListener('pointerup', up); lanesWrap.removeEventListener('pointercancel', up);
      const d = T.drag; T.drag = null; HX.arrange.dirty = true;
      if (!d) return;
      const a = Math.min(d.b0, d.b1), b = Math.max(d.b0, d.b1);
      if (b - a < (2 * XFADE_MS) / 1000 / (60 / S.session.tempo)) return HX.locate(a);   // a click: the playhead
      T.comp(t, k, a, b);
    };
    lanesWrap.addEventListener('pointermove', mv); lanesWrap.addEventListener('pointerup', up); lanesWrap.addEventListener('pointercancel', up);
  };

  /* the keyboard's way to comp: the bars in a dialog (from the loop range, else four bars from the playhead) */
  const barOf = (beats) => Math.round((beats / 4 + 1) * 1000) / 1000;
  T.compAsk = async function (t, k) {
    const L = S.session.loop || {};
    const has = L.end > L.start;
    const a0 = has ? L.start : Math.floor(HX.pos() / 4) * 4, b0 = has ? L.end : a0 + 16;
    const from = h('input.take-bar', { type: 'number', min: '1', step: 'any', value: String(barOf(a0)), 'aria-label': 'From bar' });
    const to = h('input.take-bar', { type: 'number', min: '1', step: 'any', value: String(barOf(b0)), 'aria-label': 'Up to bar' });
    const body = h('div.take-form', null, h('label', null, 'From bar ', from), h('label', null, ' up to bar ', to),
      h('small', null, 'Take ' + k.n + ' plays there on ' + t.name + ', with a ' + XFADE_MS + ' ms crossfade at each end; the rest of the comp stays. One undo step (⌘Z).'));
    const yes = await HX.dialog({ title: 'Comp from take ' + k.n, body, cancel: false, buttons: [{ label: 'Cancel', value: false, focus: true }, { label: 'Comp', value: true, kind: 'primary' }] });
    if (!yes) return null;
    const a = (parseFloat(from.value) - 1) * 4, b = (parseFloat(to.value) - 1) * 4;
    if (!isFinite(a) || !isFinite(b) || a < 0 || b - a < (2 * XFADE_MS) / 1000 / (60 / S.session.tempo)) { HX.toast('Not comped: give a start bar and a later end bar', 3600); return null; }
    return T.comp(t, k, a, b);
  };

  T.comp = function (t, k, a, b) {
    const before = t.clips.map((c) => Object.assign({}, c));
    return HX.commit('Comp ' + HX.bbtStr(a) + '–' + HX.bbtStr(b) + ' from take ' + k.n + ' of ' + t.name,
      [{ trackId: t.id, param: 'takeComp', key: k.id, before, after: { take: k.n, takeId: k.id, start: a, end: b } }]);
  };

  /* ── the op (store.js's op path; regions.js's engine undo) ── */
  const H = (HX.opHandlers = HX.opHandlers || {});
  H.takeComp = {
    undo: 'comp range',
    get: (op) => { const t = HX.track(op.trackId); return t && t.clips.map((c) => Object.assign({}, c)); },
    apply(op, v) {
      const t = HX.track(op.trackId); if (!t || !v) return;
      if (Array.isArray(v)) { t.clips = v.map((c) => Object.assign({}, c)); HX.arrange.dirty = true; return; }   // the mock's undo
      if (HX.mcp.connected) return;            // the engine does it; its regions are read back (refreshRegions)
      mockComp(t, v);
    },
    call: (op, v) => (Array.isArray(v) ? null : {
      tool: 'comp_range',
      args: { track_id: op.trackId, take: v.take, start_sample: HX.beatsToSamples(v.start), end_sample: HX.beatsToSamples(v.end), xfade_ms: XFADE_MS },
    }),
  };

  /* the mock: the same edit as the engine's comp_range, in beats */
  function mockComp(t, v) {
    const k = (T.data[t.id] || { takes: [] }).takes.find((x) => x.id === v.takeId); if (!k) return;
    const x = (XFADE_MS / 1000) * (S.session.tempo / 60), hf = x / 2;
    const sf = 64 / (S.session.sampleRate || 48000) * (S.session.tempo / 60);   // the engine's short fade (64 samples)
    const s = v.start, e = v.end, zl = Math.max(0, s - hf), zr = e + hf;
    const out = [];
    let n = 0;
    for (const c of t.clips) {
      const p = c.start, q = c.start + c.len;
      if (q <= s || p >= e) { out.push(c); continue; }
      // kept parts run on 64 samples past the far side of the join, under the take (as comp_range does)
      if (p + sf < zl) out.push(Object.assign({}, c, { len: Math.min(q, s + hf + sf) - p, fadeOut: sf }));
      if (q - sf > zr) { const np = Math.max(p, e - hf - sf); out.push(Object.assign({}, c, { id: c.id + '.r' + (++n), start: np, len: q - np, offs: (c.offs || 0) + (np - p), fadeIn: sf })); }
    }
    for (const c of k.clips) {
      const a = Math.max(c.start, zl), b = Math.min(c.start + c.len, zr);
      if (b <= a) continue;
      out.push(Object.assign({}, c, { id: c.id + '.c' + Date.now().toString(36) + (++n), start: a, len: b - a, offs: (c.offs || 0) + (a - c.start),
        fadeIn: a === zl ? x : c.fadeIn, fadeOut: b === zr ? x : c.fadeOut, real: false, take: k.n }));
    }
    t.clips = out;
    HX.arrange.dirty = true;
  }

  /* ── reading the takes ── */
  function used(comp, takeRegs, sr) {
    /* a comp region plays this take where it uses the same file at the same alignment */
    const spans = [];
    for (const c of comp) for (const r of takeRegs) {
      if (!c.sourceName || c.sourceName !== r.sourceName || c.positionSamples - c.startSamples !== r.positionSamples - r.startSamples) continue;
      const a = Math.max(c.positionSamples, r.positionSamples), b = Math.min(c.positionSamples + c.lengthSamples, r.positionSamples + r.lengthSamples);
      if (b > a) spans.push([a / spb(), b / spb()]);
    }
    return spans;
  }
  T.load = async function (trackIds) {
    if (!HX.mcp.connected || !HX.mcp.has('take_list')) return;
    const sr = S.session.sampleRate, bpm = S.session.tempo;
    let changed = false;
    for (const id of trackIds) {
      const t = HX.track(id); if (!t || !t.real || t.kind !== 'audio' || t.isReturn || t.isMaster) continue;
      let r;
      try { r = await HX.mcp.call('take_list', { track_id: id, include_regions: true }, { quiet: true }); } catch (e) { continue; }
      const old = T.data[id];
      const comp = (r.comp && r.comp.regions) || [];
      const takes = (r.takes || []).map((p) => {
        const prev = old && old.takes.find((x) => x.id === p.id);
        const clips = (p.regions || []).map((g) => {
          const o = prev && prev.clips.find((c) => c.id === g.id && c.lenS === g.lengthSamples);
          if (o) return Object.assign(o, { start: g.positionSamples / spb(), pos: g.positionSamples });
          const c = HX.regionToClip({ regionId: g.id, name: g.name, startSample: g.positionSamples, lengthSamples: g.lengthSamples, muted: g.muted }, sr, bpm);
          c.gainDb = typeof g.gainDb === 'number' ? Math.round(g.gainDb * 100) / 100 : 0; c.gainKnown = true;
          c.fadeIn = (g.fadeInSamples || 64) / spb(); c.fadeOut = (g.fadeOutSamples || 64) / spb(); c.fadesKnown = true;
          c.takeLane = true;
          return c;
        });
        return { id: p.id, name: p.name, n: p.take, clips, used: used(comp, p.regions || [], sr) };
      });
      T.data[id] = { compId: r.comp && r.comp.id, compName: r.comp && r.comp.name, takes };
      if (shownMemo[memoKey(t)] !== undefined) t.showTakes = !!shownMemo[memoKey(t)];
      takes.forEach((k) => k.clips.forEach((c) => c.loading && HX.loadClipPeaks && HX.loadClipPeaks(c)));
      changed = true;
    }
    if (changed) { HX.renderArrangeHeaders && HX.renderArrangeHeaders(); HX.arrange.dirty = true; }
  };

  /* HX.findClip falls back to this (store.js), so a take's peaks load and draw like any region's */
  T.findClip = function (id) {
    for (const tid in T.data) {
      const t = HX.track(tid); if (!t) continue;
      for (const k of T.data[tid].takes) { const c = k.clips.find((c) => c.id === id); if (c) return { track: t, clip: c, take: k }; }
    }
    return null;
  };

  /* the mock: three takes of the first vocal track, the same phrases sung a little differently */
  function mockTakes() {
    const t = S.session.tracks.find((x) => x.role === 'vocal' && x.clips.length);
    if (!t) return;
    const takes = [1, 2, 3].map((n) => ({
      id: 'mock-take-' + n, name: t.name + '.take ' + n, n, used: [],
      clips: t.clips.map((c) => {
        const p = c.peaks ? Float32Array.from(c.peaks, (v, i) => Math.min(1, v * (0.85 + 0.1 * n) * (1 + 0.12 * Math.sin(i * 0.07 * n)))) : c.peaks;
        return Object.assign({}, c, { id: c.id + '-take' + n, peaks: p, real: false, takeLane: true });
      }),
    }));
    t.clips.forEach((c) => { if (c.take == null) c.take = 1; });   // the mock's comp starts as take 1
    T.data[t.id] = { compId: 'mock-comp', compName: t.name, takes };
  }

  HX.on('session', () => {
    T.data = {}; T.drag = null;
    if (!S.session) return;
    S.session.tracks.forEach((t) => { if (shownMemo[memoKey(t)] !== undefined) t.showTakes = !!shownMemo[memoKey(t)]; });
    if (HX.mcp.connected) T.load(S.session.tracks.map((t) => t.id)).catch((e) => HX.log('err', 'take_list · ' + e.message));
    else { mockTakes(); HX.renderArrangeHeaders && HX.renderArrangeHeaders(); }
  });
  /* the mock's comp changed (a comp, an undo): the lane headers say again which takes it plays */
  HX.on('history', () => { if (!HX.mcp.connected && S.session && S.session.tracks.some(T.shown)) HX.renderArrangeHeaders && HX.renderArrangeHeaders(); });
  /* the comp changed (a comp, an edit, an undo): which parts of each take it plays */
  HX.on('regions', (ids) => { if (HX.mcp.connected && ids) T.load([...new Set(ids)]).catch(() => {}); });
})();
