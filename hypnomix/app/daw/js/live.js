/* Hypnomix · the live link to the engine: real meters and transport, the mixer's state read back,
   the device chain's real plug-ins, track colours, order and removal.

   One poll loop: meters_get (it also carries the transport's sample and rolling), about 15 Hz while playing and
   2 Hz when stopped, one request in flight at a time. A light refresh (tracks_list + track_get_info per route +
   session_get_info) every few seconds picks up changes made elsewhere (the Assistant, another client), and every
   change made here is read back from the engine a moment later. Nothing here ever blocks a frame: the frame
   loop only draws what the last replies said. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, T = HX.T, h = HX.h;

  const L = (HX.liveEngine = {
    on: false,            // connected and running
    metersLive: false,    // meters_get answers: the meters are real
    meta: null,           // /api/daw/meta: time signature + colours from the saved session file
    plugins: null,        // plugin_list_available
    rateHz: 0,
  });
  const PLAY_MS = 66, STOP_MS = 500, HIDDEN_MS = 2000, REFRESH_MS = 3000, DEV_PLAY_MS = 1000, DEV_STOP_MS = 3000;
  const SLICE = 16;       // tracks read per refresh round (the selected one always): a session of 200 tracks is read over about 40 s, not every 3 s

  /* tools/call without the log line (the poll runs 15 times a second) */
  async function quiet(name, args) {
    const r = await HX.mcp.rpc('tools/call', { name, arguments: args || {} });
    if (r && r.isError) throw new Error((r.content && r.content[0] && r.content[0].text) || 'tool error');
    if (r && r.structuredContent !== undefined) return r.structuredContent;
    const txt = r && r.content && r.content[0] && r.content[0].text;
    try { return JSON.parse(txt); } catch (e) { return txt; }
  }
  L.quiet = quiet;

  /* ── 1. the poll: meters + transport ── */
  let gen = 0, timer = null, inFlight = false, soon = false, fails = 0, ensureRms = true, lastTick = 0, ticks = [];
  L.start = function () {
    L.stop();
    L.on = true; gen++; fails = 0; ensureRms = true; T.speed = 1; clk.s = null;
    L.metersLive = HX.mcp.has('meters_get');
    loadMeta(); loadPlugins(); readLoop(); L.readExport();
    tick(gen);
    refreshTimer = setTimeout(refreshLoop, REFRESH_MS);
    devTimer = setTimeout(devLoop, DEV_STOP_MS);
    HX.emit('live');
  };
  L.stop = function () {
    L.on = false; gen++; T.trim = 0; T.speed = 1; clearTimeout(timer); clearTimeout(refreshTimer); clearTimeout(devTimer);
    L.metersLive = false; L.plugins = null; restoreMockBrowser();
    clearTimeout(expTimer); if (L.exporting) { L.exporting = null; HX.emit('exporting', null); }
    HX.allTracks().forEach((t) => { t._mt = null; });
    HX.emit('live');
  };
  /* poll again now (after play / stop / locate), without ever having two requests out */
  L.kick = function () {
    if (!L.on) return;
    if (inFlight) { soon = true; return; }
    clearTimeout(timer); tick(gen);
  };
  async function tick(g) {
    if (g !== gen || !HX.mcp.connected) return;
    inFlight = true; soon = false;
    const t0 = performance.now();
    try {
      if (L.metersLive) {
        const r = await quiet('meters_get', ensureRms ? { ensure_rms: true } : {});
        ensureRms = false;
        if (g !== gen) return;
        applyMeters(r);
        applyTransport(r.rolling, r.sample, performance.now() - t0);
      } else {
        const s = await quiet('transport_get_state');
        if (g !== gen) return;
        applyTransport(s.rolling, s.sample, performance.now() - t0);
      }
      if (fails >= 8) HX.emit('engine', 'ok');
      fails = 0;
    } catch (e) {
      if (/meters/.test(e.message) && /not found|unknown/i.test(e.message)) { L.metersLive = false; HX.emit('live'); }
      if (++fails === 8) { HX.emit('engine', 'lost'); HX.toast('The engine stopped answering. Still trying…', 4000); }
    } finally { inFlight = false; }
    if (g !== gen) return;
    const now = performance.now();
    ticks.push(now); while (ticks.length && now - ticks[0] > 2000) ticks.shift();
    L.rateHz = ticks.length / 2;
    const every = document.hidden ? HIDDEN_MS : fails ? 1000 : T.playing ? PLAY_MS : STOP_MS;   // a hidden tab asks rarely
    timer = setTimeout(() => tick(g), soon ? 0 : Math.max(0, every - (now - t0)));
  }

  /* the playhead: the engine's sample, corrected for half the round trip, re-anchors the local clock;
     small drift is slewed (no visible jumps), big jumps (a locate, a loop) snap */
  T.graceUntil = 0;
  const clk = { s: null, t: 0 };
  function applyTransport(rolling, sample, rttMs) {
    if (sample == null) return;
    /* an export freewheels the engine (rolling, far faster than real time): that is not playback, so the view
       stays stopped where it was until the export is done */
    if (L.exporting) {
      if (T.playing) { T.stopBeat = HX.pos(); T.playing = false; T.trim = 0; clk.s = null; HX.emit('transport'); }
      return;
    }
    const now = performance.now();
    const sr = S.session.sampleRate || 48000;
    let beat = HX.secToBeats(sample / sr);
    if (now < T.graceUntil && rolling !== T.playing) return; // a play/stop we just sent is still on its way
    if (rolling) beat += HX.secToBeats(rttMs / 2000);
    if (rolling !== T.playing) {
      T.playing = rolling;
      T.trim = 0; clk.s = null;
      if (rolling) { T.anchorBeat = beat; T.anchorT = now; } else T.stopBeat = beat;
      HX.emit('transport');
      return;
    }
    if (rolling) {
      /* a gentle phase-locked clock: never steps backwards; it runs up to 8 % fast or slow for a moment
         to close the gap over about half a second, and ignores gaps under 5 ms (the reply's own jitter) */
      /* the engine's clock may not run at exactly wall-clock speed (a dummy or busy backend): learn its rate */
      const mid = now - rttMs / 2;
      if (clk.s != null && mid - clk.t > 250) {
        const r = (sample - clk.s) / sr / ((mid - clk.t) / 1000);
        if (r > 0.3 && r < 2) T.speed = HX.clamp(T.speed + (r - T.speed) * 0.25, 0.3, 2);
        clk.s = sample; clk.t = mid;
      } else if (clk.s == null) { clk.s = sample; clk.t = mid; }
      const cur = HX.pos(), d = beat - cur;
      if (Math.abs(d) > 0.5) { T.anchorBeat = beat; T.anchorT = now; T.trim = 0; clk.s = null; HX.emit('transport'); return; }
      T.anchorBeat = cur; T.anchorT = now;
      const bps = S.session.tempo / 60;
      T.trim = Math.abs(d) < 0.01 * bps ? 0 : HX.clamp(d / (0.5 * bps), -0.08, 0.08);
    } else if (now >= T.graceUntil && Math.abs(T.stopBeat - beat) > 1e-4) {
      T.stopBeat = beat; T.anchorBeat = beat; HX.emit('transport');
    }
  }

  /* targets from the last reply; the frame loop eases the bars toward them */
  function chans(rt) {
    const c = rt.channels || [];
    const v = (x) => (x == null || !isFinite(x) ? -120 : x);
    const a = c[0] || rt, b = c[1] || c[0] || rt;
    return { l: v(a.peakDb), r: v(b.peakDb), rl: a.rmsDb == null ? null : v(a.rmsDb), rr: b.rmsDb == null ? null : v(b.rmsDb), max: v(rt.maxPeakDb) };
  }
  function applyMeters(r) {
    if (!r) return;
    (r.routes || []).forEach((rt) => { const t = HX.track(rt.id); if (t) t._mt = chans(rt); });
    if (r.master && S.session.master) {
      const m = HX.track(r.master.id) || S.session.master;
      m._mt = chans(r.master);
    }
  }
  /* rises at once, falls smoothly over about one poll interval; peak hold 1.6 s, then falls */
  L.frameMeters = function (dt, now) {
    const k = Math.min(1, dt / 0.09);
    for (const t of HX.allTracks()) {
      const m = t.meter, x = t._mt;
      if (!m) continue;
      const tl = x ? x.l : -120, tr = x ? x.r : -120;
      m.l = tl > m.l ? tl : m.l + (tl - m.l) * k;
      m.r = tr > m.r ? tr : m.r + (tr - m.r) * k;
      if (x && x.rl != null) {
        m.rmsL = m.rmsL == null || x.rl > m.rmsL ? x.rl : m.rmsL + (x.rl - m.rmsL) * k;
        m.rmsR = m.rmsR == null || x.rr > m.rmsR ? x.rr : m.rmsR + (x.rr - m.rmsR) * k;
      } else { m.rmsL = m.rmsR = null; }
      const pk = Math.max(m.l, m.r);
      if (pk >= m.pk) { m.pk = pk; m.pkT = now; } else if (now - m.pkT > 1600) m.pk = Math.max(pk, m.pk - 18 * dt);
      if (x && Math.max(x.l, x.r) > -0.001) { m.clip = true; m.clipT = now; } // the current peak, not the engine's all-time max: a click clears it
    }
  };

  /* ── 2. reading the engine's state back ── */
  const touched = new Map(); // trackId → time of the last local edit (the refresh leaves it alone for a moment)
  L.touch = (id) => touched.set(id, performance.now());
  const fresh = (id) => performance.now() - (touched.get(id) || 0) < 1500;

  function dbOf(f) { return f && f.db != null && isFinite(f.db) ? Math.max(-193, f.db) : -193; }
  /* apply one track_get_info; returns true when the track's structure (sends, plug-ins) changed */
  function applyInfo(t, ti, force) {
    if (!t || !ti) return false;
    const emit = (param, key) => HX.emit('param', { trackId: t.id, param, key });
    let structural = false;
    if (ti.name && ti.name !== t.name) { t.name = ti.name; structural = true; }
    if (force || !fresh(t.id)) {
      const db = dbOf(ti.fader);
      if (Math.abs(db - t.faderDb) > 0.05) { t.faderDb = Math.round(db * 100) / 100; emit('fader'); }
      if (ti.pan && ti.pan.position != null) { const p = 1 - 2 * ti.pan.position; if (Math.abs(p - t.pan) > 0.005) { t.pan = Math.round(p * 1000) / 1000; emit('pan'); } }
      if (!!ti.mute !== !!t.mute) { t.mute = !!ti.mute; emit('mute'); }
      if (!!ti.solo !== !!t.solo) { t.solo = !!ti.solo; emit('solo'); }
      if (ti.recEnabled != null && !!ti.recEnabled !== !!t.arm) { t.arm = !!ti.recEnabled; emit('arm'); }
      const sends = (ti.sends || []).map((s) => ({ index: s.index, name: s.targetRouteName || s.name, db: dbOf({ db: s.db }) }));
      if (sends.length !== t.sends.length || sends.some((s, i) => s.index !== t.sends[i].index || s.name !== t.sends[i].name)) { t.sends = sends; structural = true; }
      else sends.forEach((s, i) => { if (Math.abs(s.db - t.sends[i].db) > 0.05) { t.sends[i].db = s.db; emit('send', s.index); } });
    }
    const pl = ti.plugins || [];
    const same = pl.length === t.devices.length && pl.every((p, i) => t.devices[i].real && t.devices[i].index === p.index && t.devices[i].name === (p.displayName || p.name));
    if (!same) { t.devices = pl.map(devFrom); dropDevUndo(t); structural = true; HX.emit('devices'); HX.emit('history'); }
    else pl.forEach((p, i) => { if (!!p.enabled !== !!t.devices[i].on && (force || !fresh(t.id))) { t.devices[i].on = !!p.enabled; emit('devOn', i); } });
    return structural;
  }
  /* device indices moved (here or in another client): undo steps that point into this chain by position would
     now hit another plug-in, so drop them */
  function dropDevUndo(t) {
    const hit = (e) => e.ops.some((o) => o.trackId === t.id && /^dev/.test(o.param));
    if (!S.history.some(hit) && !S.future.some(hit)) return;
    S.history = S.history.map((e) => Object.assign(e, { ops: e.ops.filter((o) => !(o.trackId === t.id && /^dev/.test(o.param))) })).filter((e) => e.ops.length);
    S.future = [];
  }
  const devFrom = (p) => ({ id: 'p' + p.index + ':' + (p.displayName || p.name), name: p.displayName || p.name, kind: 'plugin', on: !!p.enabled, params: [], outs: [], real: true, index: p.index, post: !!p.postFader });

  /* one track, right after a change made here (debounced per track) */
  const rb = new Map();
  L.readBack = function (trackId, delay) {
    if (!L.on || !trackId || trackId === '*') return;
    clearTimeout(rb.get(trackId));
    rb.set(trackId, setTimeout(async () => {
      rb.delete(trackId);
      const t = HX.track(trackId); if (!t || !t.real) return;
      try { if (applyInfo(t, await quiet('track_get_info', { id: trackId }), true)) HX.emit('session-light'); } catch (e) {}
    }, delay == null ? 250 : delay));
  };
  L.afterChange = function (ops) {
    if (!L.on) return;
    const ids = new Set(ops.map((o) => o.trackId));
    ids.forEach((id) => L.readBack(id));
    ops.filter((o) => o.param === 'devParam').forEach((o) => { const t = HX.track(o.trackId); const d = t && t.devices[o.key[0]]; if (d && d.real) readDevice(t, d, 300); });
  };

  /* the light refresh: other clients, the Assistant */
  let refreshTimer = null, refreshing = false;
  async function refreshLoop() {
    if (!L.on) return;
    if (!document.hidden) {                         // nobody is looking: no round of requests
      await L.refresh().catch(() => {});
      if (!L.exporting) await L.readExport();
    }
    if (L.on) refreshTimer = setTimeout(refreshLoop, REFRESH_MS);
  }
  /* the tab is shown again: look at once, not up to 3 s later */
  document.addEventListener('visibilitychange', () => { if (!document.hidden && L.on) { clearTimeout(refreshTimer); refreshTimer = setTimeout(refreshLoop, 50); } });
  /* up to SLICE of a list, round and round (cursor kept per list name); `always` ids are in every round */
  const cursors = {};
  function slice(name, list, always) {
    if (list.length <= SLICE) return list;
    const at = (cursors[name] || 0) % list.length;
    cursors[name] = at + SLICE;
    const out = [];
    for (let i = 0; i < SLICE; i++) out.push(list[(at + i) % list.length]);
    const a = list.find((x) => x.id === always);
    if (a && !out.includes(a)) out.push(a);
    return out;
  }
  L.refresh = async function () {
    if (refreshing || !HX.mcp.connected || HX.dragging) return;
    refreshing = true;
    const g = gen;
    try {
      const tl = await quiet('tracks_list', { includeHidden: false });
      if (g !== gen) return;
      const routes = (tl && tl.tracks) || [];
      const have = new Set(HX.allTracks().filter((t) => t.real).map((t) => t.id));
      const now = new Set(routes.map((r) => r.id));
      if (routes.length !== have.size || routes.some((r) => !have.has(r.id))) {
        /* a track was added or removed elsewhere: read the session again */
        await HX.loadFromEngine();
        HX.log('mcp', 'the engine\'s track list changed: the session was read again');
        return;
      }
      void now;
      let structural = applyOrder(routes);
      for (const r of slice('info', routes, S.ui.trackId)) {
        if (g !== gen) return;
        const t = HX.track(r.id); if (!t) continue;
        if (applyInfo(t, await quiet('track_get_info', { id: r.id }))) structural = true;
      }
      const info = await quiet('session_get_info');
      if (info && info.tempoBpm && Math.abs(info.tempoBpm - S.session.tempo) > 0.005) {
        const beat = HX.pos(); S.session.tempo = Math.round(info.tempoBpm * 100) / 100;
        if (T.playing) { T.anchorBeat = beat; T.anchorT = performance.now(); } else T.stopBeat = beat;
        HX.$('#tempo').textContent = S.session.tempo.toFixed(2);
      }
      if (structural) HX.emit('session-light');
      if (g === gen) await L.refreshRegionsCheap(g);
    } finally { refreshing = false; }
  };
  /* regions changed by another client (the Assistant, a Hypnomix window, a script), cheaply: one track_get_regions
     a track (where they are, how long, muted), and the track read again only when that differs from the view; then
     region_get_info for a few regions each time round (REGION_INFO_PER_TICK, in turn), so a fade or a gain set
     elsewhere shows up within a few refreshes without asking for every region every 3 seconds */
  const REGION_INFO_PER_TICK = 6;
  let regionCursor = 0;
  const regionSig = (list) => list.map((g) => [g.regionId, g.startSample, g.lengthSamples, !!g.muted].join(':')).join('|');
  const clipSig = (t) => t.clips.filter((c) => c.real).slice().sort((a, b) => a.pos - b.pos).map((c) => [c.id, c.pos, c.lenS, !!c.muted].join(':')).join('|');
  L.refreshRegionsCheap = async function (g) {
    if (!HX.refreshRegions || HX.dragging || (HX.editBusy && HX.editBusy())) return;
    const changed = [];
    const withRegions = HX.allTracks().filter((t) => t.real && !t.isMaster && !t.isReturn && t.kind !== 'bus' && t.clips);
    for (const t of slice('regions', withRegions, S.ui.trackId)) {
      if (g !== gen || HX.dragging) return;
      let rg; try { rg = await quiet('track_get_regions', { id: t.id }); } catch (e) { continue; }
      const list = ((rg && rg.regions) || []).filter((x) => !x.hidden).sort((a, b) => a.startSample - b.startSample);
      if (regionSig(list) !== clipSig(t)) changed.push(t.id);
    }
    if (changed.length && g === gen) { await HX.refreshRegions(changed); HX.log('mcp', 'regions changed in the engine: read again (' + changed.length + ' track' + (changed.length > 1 ? 's' : '') + ')'); }
    const clips = HX.allTracks().flatMap((t) => (t.real && t.clips ? t.clips.filter((c) => c.real && !c.temp && c.kind === 'audio') : []));
    if (!clips.length || !HX.readRegionInfo) return;
    for (let i = 0; i < Math.min(REGION_INFO_PER_TICK, clips.length); i++) {
      if (g !== gen || HX.dragging) return;
      const c = clips[(regionCursor++) % clips.length];
      try { await HX.readRegionInfo(c); } catch (e) {}
    }
  };
  /* presentation order from tracks_list → the order of the session's tracks and returns */
  function applyOrder(routes) {
    const pos = new Map(routes.map((r) => [r.id, r.presentationOrder != null ? r.presentationOrder : r.trackNumber]));
    let changed = false;
    for (const arr of [S.session.tracks, S.session.returns]) {
      const before = arr.map((t) => t.id).join();
      arr.sort((a, b) => (pos.has(a.id) ? pos.get(a.id) : 1e9) - (pos.has(b.id) ? pos.get(b.id) : 1e9));
      if (arr.map((t) => t.id).join() !== before) changed = true;
    }
    return changed;
  }

  /* ── 3. ops this file adds to the store: track colour and track order ── */
  L.ref = function (op) {
    if (op.param === 'order') return [orderRef, 'v'];
    if (op.param === 'color') return [HX.track(op.trackId), 'color'];
    return null;
  };
  const orderRef = {
    get v() { return [...S.session.tracks, ...S.session.returns].map((t) => t.id); },
    set v(ids) {
      const ix = new Map(ids.map((id, i) => [id, i]));
      const by = (a, b) => (ix.has(a.id) ? ix.get(a.id) : 1e9) - (ix.has(b.id) ? ix.get(b.id) : 1e9);
      S.session.tracks.sort(by); S.session.returns.sort(by);
      HX.emit('session-light'); if (HX.arrange) HX.arrange.dirty = true;
    },
  };
  /* returns undefined for ops it does not handle (the store sends those) */
  L.send = function (op, value) {
    if (op.param === 'plugChain') return L.sendPlugChain(op, value);
    if (op.param === 'color') {
      if (!HX.mcp.connected) return HX.log('mock', 'track_set_color ' + JSON.stringify({ track_id: op.trackId, color: value }));
      const t = HX.track(op.trackId); if (!t || !t.real) return HX.log('err', 'track_set_color skipped: mock track');
      rememberColour(op.trackId, value);
      return HX.mcp.call('track_set_color', { track_id: op.trackId, color: value });
    }
    if (op.param === 'order') {
      const ids = value.filter((id) => { const t = HX.track(id); return t && t.real; });
      if (!HX.mcp.connected) return HX.log('mock', 'track_reorder ' + JSON.stringify({ order: value }));
      return HX.mcp.call('track_reorder', { order: ids }).then(async (r) => {
        /* read the order back */
        const tl = await quiet('tracks_list', { includeHidden: false });
        if (applyOrder((tl && tl.tracks) || [])) HX.emit('session-light');
        return r;
      });
    }
    return undefined;
  };
  HX.on('param', (op) => { if (op.param === 'color') { HX.emit('session-light'); if (HX.arrange) HX.arrange.dirty = true; } });

  /* colours: the saved file says what was saved; this page remembers what it set since (per session, this browser) */
  const colourKey = () => 'hx.colors:' + ((HX.engineState && HX.engineState.session) || S.session.name);
  function rememberColour(id, c) {
    try { const k = colourKey(); const m = JSON.parse(localStorage.getItem(k) || '{}'); m[id] = c; localStorage.setItem(k, JSON.stringify(m)); } catch (e) {}
  }
  function applyColours() {
    let set = {};
    if (L.meta && L.meta.colors) set = Object.assign(set, L.meta.colors);
    try { const m = JSON.parse(localStorage.getItem(colourKey()) || '{}'); if (L.meta && L.meta.saved) { /* the file is newer than nothing: keep both, ours last */ } set = Object.assign(set, m); } catch (e) {}
    let any = false;
    for (const id in set) { const t = HX.track(id); if (t && !t.isMaster && t.color !== set[id]) { t.color = set[id]; any = true; } }
    if (any) { HX.emit('session-light'); if (HX.arrange) HX.arrange.dirty = true; }
  }
  L.PALETTE = ['#d9967a', '#d6a98c', '#cdb48f', '#c8b37c', '#b3b98e', '#93b39a', '#9cbcb6', '#8eaab8', '#a9a0c4', '#c99aa6', '#c47c6a', '#7f9a86', '#6f8fa6', '#bdb6aa'];

  /* time signature (and colours) from the saved session file */
  async function loadMeta() {
    if (!HX.api.inApp) return;
    try {
      L.meta = await HX.api.post('/api/daw/meta', {});
      if (L.meta.meter) S.session.meter = L.meta.meter;
      showMeter();
      applyColours();
    } catch (e) { L.meta = null; showMeter(); }
  }
  function showMeter() {
    const el = HX.$('#timeSig'); if (!el) return;
    const m = S.session.meter || [4, 4];
    el.textContent = m[0] + ' / ' + m[1];
    el.parentElement.dataset.info = 'Time signature' + (HX.mcp.connected ? (L.meta && L.meta.meter ? ' · from the saved session' : ' · the engine does not report it: 4 / 4 assumed') : '');
  }
  /* bars and beats in the session's meter (beats are quarter notes) */
  const bbt4 = HX.bbtStr;
  HX.bbtStr = function (beats) {
    const m = S.session && S.session.meter;
    if (!m || (m[0] === 4 && m[1] === 4)) return bbt4(beats);
    const q = 4 / m[1], bar = m[0] * q;
    return (Math.floor(beats / bar) + 1) + '. ' + (Math.floor((beats % bar) / q) + 1) + '. ' + (Math.floor(((beats % q) / q) * 4) + 1);
  };

  /* the loop range from the session's markers */
  async function readLoop() {
    try {
      const ml = await quiet('markers_list');
      const arr = Array.isArray(ml) ? ml : (ml && ml.markers) || [];
      const lp = arr.find((k) => k.isAutoLoop);
      if (lp && lp.endSample > lp.startSample) {
        const sr = S.session.sampleRate;
        S.session.loop.start = HX.secToBeats(lp.startSample / sr); S.session.loop.end = HX.secToBeats(lp.endSample / sr);
        L.loopSet = true; HX.emit('transport');
      } else L.loopSet = false;
    } catch (e) {}
  }

  /* ── 3b. an export (Review's scan bounce, the Assistant, another client) holds the transport ──
     While session_export_mix runs, the engine refuses every transport_* tool but transport_get_state with -32003,
     so a bounce cannot be cut short. export_status (no job id: every job since the session opened) is read on the
     light refresh, every second while one runs, and at once when a transport call comes back -32003. While one
     runs, the transport buttons are disabled and say why. */
  L.exporting = null;                      // { jobId, progress } while an export runs
  let expTimer = null;
  function setExporting(x) {
    const was = L.exporting;
    L.exporting = x;
    if (x && !was && T.playing) { T.stopBeat = HX.pos(); T.playing = false; T.trim = 0; HX.emit('transport'); }
    if (!!was !== !!x || (x && was && Math.round(x.progress * 100) !== Math.round(was.progress * 100))) HX.emit('exporting', x);
    if (was && !x) { HX.toast('The export finished: the transport is free again', 2600); L.kick(); }
    clearTimeout(expTimer);
    if (x && L.on) expTimer = setTimeout(() => L.readExport(), 1000);
  }
  L.readExport = async function () {
    if (!L.on || !HX.mcp.connected || !HX.mcp.has('export_status')) return;
    try {
      const r = await quiet('export_status');
      const run = ((r && r.jobs) || []).find((j) => j.state === 'running');
      setExporting(run ? { jobId: run.jobId, progress: run.progress || 0 } : null);
    } catch (e) { if (L.exporting) { clearTimeout(expTimer); expTimer = setTimeout(() => L.readExport(), 1000); } }
  };
  /* a transport call's error: true when it was refused because an export runs (it is then said plainly) */
  HX.exportRefused = function (e) {
    if (!e || !/-32003/.test(e.message || '')) return false;
    const m = /\(([^)]*export[^)]*)\)/.exec(e.message);
    if (!L.exporting) setExporting({ jobId: m ? m[1] : '?', progress: 0 });
    HX.transportBusy();
    L.readExport();
    return true;
  };
  /* say why the transport does nothing (at most once every 2 s) */
  let busySaid = 0;
  HX.transportBusy = function () {
    if (performance.now() - busySaid < 2000) return;
    busySaid = performance.now();
    HX.toast('An export is running (' + Math.round(((L.exporting && L.exporting.progress) || 0) * 100) + ' %): play, stop, locate, loop and record wait until it finishes', 3600);
  };
  HX.exportBusy = () => !!(L.on && L.exporting);

  /* ── 4. transport commands with read-back ── */
  L.loop = async function (on) {
    const sr = S.session.sampleRate, lp = S.session.loop;
    try {
      if (on) await HX.mcp.loopRange(HX.beatsToSec(lp.start) * sr, HX.beatsToSec(lp.end) * sr);
      /* the reply's playLoop is the state *before* the request (the engine applies it on its process thread),
         so it is not read back here: the button shows what was asked */
      await HX.mcp.loopToggle(on);
      T.graceUntil = performance.now() + 500;
      L.kick();
    } catch (e) { lp.on = !on; HX.emit('transport'); if (!HX.exportRefused(e)) HX.toast('Loop: ' + e.message, 3200); }
  };
  L.rec = async function (on) {
    try {
      const r = await HX.mcp.recEnable(on);
      if (r && r.recordEnabled != null && r.recordEnabled !== T.rec) { T.rec = r.recordEnabled; HX.emit('transport'); }
    } catch (e) { T.rec = !on; HX.emit('transport'); if (!HX.exportRefused(e)) HX.toast('Record: ' + e.message, 3200); }
  };

  /* ── 5. tracks: delete (with a confirmation) ── */
  /* a confirmation: Cancel has the focus (the safe answer), Enter and Space press the focused button only, Esc cancels
     (HX.dialog, js/util.js). Resolves true when the person chose the OK button. */
  HX.confirm = function (title, body, okLabel) {
    return HX.dialog({ title, body, cancel: false, buttons: [{ label: 'Cancel', value: false, focus: true }, { label: okLabel || 'OK', value: true, kind: 'danger' }] });
  };
  HX.deleteTrack = async function (t) {
    if (!t || t.isMaster) return;
    const real = HX.mcp.connected && t.real;
    const yes = await HX.confirm('Delete “' + t.name + '”?', real
      ? 'The engine cannot undo this. The track, its plug-ins and sends go; its recordings stay in the session’s sound folder.'
      : 'This is the mock session: nothing leaves this page.', 'Delete track');
    if (!yes) return;
    try {
      if (real) {
        await HX.mcp.call('track_remove', { track_id: t.id, confirm: true });
        const tl = await quiet('tracks_list', { includeHidden: false });
        if (((tl && tl.tracks) || []).some((r) => r.id === t.id)) throw new Error('the engine still lists it');
      } else HX.log('mock', 'track_remove ' + JSON.stringify({ track_id: t.id, confirm: true }));
    } catch (e) { return HX.toast('Not deleted: ' + e.message, 3600); }
    const sess = S.session;
    sess.tracks = sess.tracks.filter((x) => x !== t); sess.returns = sess.returns.filter((x) => x !== t);
    S.history = S.history.map((e) => Object.assign(e, { ops: e.ops.filter((o) => o.trackId !== t.id) })).filter((e) => e.ops.length);
    S.future = [];
    if (S.ui.trackId === t.id) S.ui.trackId = (sess.tracks[0] || sess.master).id;
    if (HX.buildScenes) S.scenes = HX.buildScenes(sess);
    HX.emit('session-light'); HX.emit('history'); HX.emit('select'); HX.emit('launch');
    if (HX.arrange) HX.arrange.dirty = true;
    if (real) L.refresh().catch(() => {}); // sends to a deleted bus go with it: read the other strips now, not in 3 s
    HX.toast('Deleted ' + t.name);
  };

  /* ── 6. devices: real plug-ins ── */
  const F_ENUM = 1, F_INT = 2, F_LOG = 4, F_TOGGLE = 64;
  function paramFrom(p) {
    const q = { n: p.label, v: p.currentValue, min: p.lower, max: p.upper, unit: '', realIndex: p.index };
    if (p.flags & F_TOGGLE) q.toggle = true;
    if ((p.flags & F_LOG) && p.lower > 0 && p.upper > p.lower) q.log = true;
    if (p.flags & F_INT) q.step = 1;
    if (p.scalePoints && p.scalePoints.length && (p.flags & F_ENUM || p.scalePoints.length <= 12)) q.points = p.scalePoints.slice().sort((a, b) => a.value - b.value);
    const lbl = p.label.toLowerCase();
    if (/\b(gain|threshold|makeup|level|ceiling|output|input)\b/.test(lbl) && p.lower < 0) q.unit = 'dB';
    else if (/\bfreq|hz\b|cutoff/.test(lbl)) q.unit = 'Hz';
    else if (/attack|release|\bms\b|delay|time/.test(lbl)) q.unit = /\bs\)|\(s\b/.test(lbl) ? 's' : 'ms';
    else if (/ratio/.test(lbl)) q.unit = ':1';
    return q;
  }
  function outFrom(p) { return { n: p.label, v: p.currentValue, min: p.lower, max: p.upper, fmt: p.printFmt, realIndex: p.index }; }
  HX.loadDeviceParams = async function (track, dev) {
    if (!dev.real || dev.loaded || dev.loading) return;
    dev.loading = true;
    try {
      const d = await quiet('plugin_get_description', { id: track.id, pluginIndex: dev.index });
      const ps = (d.parameters || []).filter((p) => p.isControl && !p.isHidden);
      dev.params = ps.filter((p) => p.isInput).map(paramFrom);
      /* readings: levels and loudness first; the Probe's raw sums are for the scan, not for people */
      const score = (p) => (/lufs|peak|rms|db/i.test(p.label) ? 0 : 1);
      dev.outs = ps.filter((p) => p.isOutput && !/^raw\b/i.test(p.label)).sort((a, b) => score(a) - score(b) || a.index - b.index).map(outFrom);
      dev.maker = d.plugin && d.plugin.maker;
      dev.loaded = true;
      HX.emit('devices');
    } catch (e) { HX.log('err', 'plugin_get_description ' + dev.name + ' · ' + e.message); }
    finally { dev.loading = false; }
  };
  /* re-read one device's values (after a change, or the periodic look at the shown track) */
  const rd = new Map();
  function readDevice(t, d, delay) {
    const k = t.id + '|' + d.index;
    clearTimeout(rd.get(k));
    rd.set(k, setTimeout(async () => {
      rd.delete(k);
      try {
        const desc = await quiet('plugin_get_description', { id: t.id, pluginIndex: d.index });
        applyDescription(t, d, desc);
      } catch (e) {}
    }, delay || 0));
  }
  function applyDescription(t, d, desc) {
    const ps = (desc.parameters || []).filter((p) => p.isControl && !p.isHidden);
    const byIx = new Map(ps.map((p) => [p.index, p]));
    const di = t.devices.indexOf(d); if (di < 0) return;
    d.params.forEach((q, pi) => {
      const p = byIx.get(q.realIndex);
      if (p && Math.abs(p.currentValue - q.v) > 1e-6 && !(fresh(t.id) && HX.dragging)) { q.v = p.currentValue; HX.emit('param', { trackId: t.id, param: 'devParam', key: [di, pi] }); }
    });
    let outs = false;
    (d.outs || []).forEach((o) => { const p = byIx.get(o.realIndex); if (p && p.currentValue !== o.v) { o.v = p.currentValue; outs = true; } });
    if (outs) HX.emit('device-outs', { trackId: t.id, di });
  }
  let devTimer = null;
  async function devLoop() {
    if (!L.on) return;
    const t = HX.track(S.ui.trackId);
    if (t && t.real && S.ui.bottom === 'devices' && !HX.dragging && !document.hidden) {
      for (const d of t.devices) {
        if (!d.loaded || !L.on) continue;
        try { applyDescription(t, d, await quiet('plugin_get_description', { id: t.id, pluginIndex: d.index })); } catch (e) {}
      }
    }
    if (L.on) devTimer = setTimeout(devLoop, T.playing ? DEV_PLAY_MS : DEV_STOP_MS);
  }

  /* the device chain's structure: re-read it from the engine after an add, remove or move */
  async function rereadDevices(t) {
    const ti = await quiet('track_get_info', { id: t.id });
    t.devices = (ti.plugins || []).map(devFrom);
    dropDevUndo(t);
    HX.emit('devices'); HX.emit('session-light'); HX.emit('history');
    return t.devices;
  }
  /* ── adding or removing a plug-in is ONE undo step of the view (the engine keeps no undo for a plug-in chain).
     The op is { trackId, param: 'plugChain', key, before, after } where a state is null (not in the chain) or
     { uniqueId, type, name, index, params: [[parameterIndex, value]] }. Going to null removes the plug-in at that
     index (only when it is still the same one); going to a state adds it back by its unique id AT that index and
     puts every parameter value back. Undo of an add removes the added one; undo of a remove re-adds it. */
  async function plugSpec(t, d) {
    const desc = await quiet('plugin_get_description', { id: t.id, pluginIndex: d.index });
    const pl = (desc && desc.plugin) || {};
    const known = (L.plugins || []).find((x) => x.uniqueId === pl.uniqueId && (x.name === pl.name || x.name === d.name))
      || (L.plugins || []).find((x) => x.uniqueId === pl.uniqueId);
    const type = known ? known.type : (pl.type || '');
    const params = (desc.parameters || []).filter((q) => q.isControl && q.isInput).map((q) => [q.index, q.currentValue]);
    return { uniqueId: pl.uniqueId, type, name: d.name, index: d.index, params };
  }
  async function plugPut(t, spec) {
    const args = { id: t.id, uniqueId: spec.uniqueId, type: spec.type, position: spec.index };
    if (!args.type) delete args.type;
    const r = await HX.mcp.call('plugin_add_by_unique_id', args);
    const ix = r && typeof r.pluginIndex === 'number' ? r.pluginIndex : spec.index;
    for (const [pi, v] of spec.params || []) {
      try { await HX.mcp.call('plugin_set_parameter_by_index_value', { id: t.id, pluginIndex: ix, parameterIndex: pi, value: v }); }
      catch (e) { HX.log('err', 'parameter ' + pi + ' of ' + spec.name + ' · ' + e.message); }
    }
    return ix;
  }
  async function plugTake(t, spec) {
    const ti = await quiet('track_get_info', { id: t.id });
    const here = (ti.plugins || []).find((x) => x.index === spec.index);
    if (!here || (here.displayName || here.name) !== spec.name) throw new Error('the plug-in chain of ' + t.name + ' changed since: ' + spec.name + ' is not at place ' + (spec.index + 1) + ' any more');
    await HX.mcp.call('plugin_remove', { id: t.id, pluginIndex: spec.index });
  }
  async function plugReread(t) {           // the chain after one of these: read again, without dropping this undo step
    const ti = await quiet('track_get_info', { id: t.id });
    t.devices = (ti.plugins || []).map(devFrom);
    HX.emit('devices'); HX.emit('session-light');
  }
  HX.opHandlers = HX.opHandlers || {};
  HX.opHandlers.plugChain = { storeOwned: true, get: (op) => op.before, apply() {} };
  L.sendPlugChain = async function (op, value) {
    const t = HX.track(op.trackId);
    if (!t || !t.real) return HX.log('err', 'plug-in chain: not a track of the engine’s session');
    if (!HX.mcp.connected) return HX.log('mock', (value ? 'plugin_add_by_unique_id ' : 'plugin_remove ') + op.key);
    const other = value ? null : (op.before || op.after);
    try {
      if (value) value.index = await plugPut(t, value);
      else await plugTake(t, other);
    } catch (e) { HX.toast('Plug-in chain: ' + e.message, 4200); HX.log('err', 'plug-in chain · ' + e.message); throw e; }
    finally { await plugReread(t).catch(() => {}); }
  };
  L.addPlugin = async function (t, p) {
    t = t || HX.track(S.ui.trackId);
    if (!t || !t.real) return HX.toast('Pick a track of the engine’s session first');
    if (HX.editBlocked()) return HX.toast(HX.editBlocked(), 3600);
    try {
      let r;
      try { r = await HX.mcp.call('plugin_add_by_plugin_id', { id: t.id, pluginId: p.pluginId }); }
      catch (e) { r = await HX.mcp.call('plugin_add_by_unique_id', { id: t.id, uniqueId: p.uniqueId, type: p.type }); }
      const devs = await rereadDevices(t);
      const ix = r && typeof r.pluginIndex === 'number' ? r.pluginIndex : (devs.filter((d) => d.name === p.name).pop() || {}).index;
      const nd = devs.find((d) => d.index === ix);
      if (nd) {
        let spec = { uniqueId: p.uniqueId, type: p.type, name: nd.name, index: ix, params: [] };
        try { spec = await plugSpec(t, nd); if (p.type) spec.type = p.type; if (!spec.uniqueId) spec.uniqueId = p.uniqueId; } catch (e) {}
        S.history.push({ label: 'Add ' + nd.name + ' to ' + t.name, ops: [{ trackId: t.id, param: 'plugChain', key: nd.name, before: null, after: spec }], source: 'you', t: Date.now() });
        S.future = [];
        HX.emit('history');
      }
      HX.toast(nd ? 'Added ' + p.name + ' to ' + t.name : 'The engine did not add ' + p.name, 2600);
      S.ui.bottom = 'devices'; HX.emit('bottom');
    } catch (e) { HX.toast('Could not add ' + p.name + ': ' + e.message, 3600); }
  };
  L.removePlugin = async function (t, d) {
    if (!d.real) { t.devices = t.devices.filter((x) => x !== d); HX.emit('devices'); HX.emit('session-light'); return; }
    if (HX.editBlocked()) return HX.toast(HX.editBlocked(), 3600);
    try {
      let spec = null;
      try { spec = await plugSpec(t, d); } catch (e) { HX.log('err', 'plug-in ' + d.name + ' · ' + e.message); }
      await HX.mcp.call('plugin_remove', { id: t.id, pluginIndex: d.index });
      await rereadDevices(t);
      if (spec && spec.uniqueId) {
        S.history.push({ label: 'Remove ' + d.name + ' from ' + t.name, ops: [{ trackId: t.id, param: 'plugChain', key: d.name, before: spec, after: null }], source: 'you', t: Date.now() });
        S.future = [];
        HX.emit('history');
      }
      HX.toast('Removed ' + d.name);
    } catch (e) { HX.toast('Not removed: ' + e.message, 3600); }
  };
  L.movePlugin = async function (t, from, to) {
    if (from === to) return;
    const d = t.devices[from];
    if (!d || !d.real) { const [x] = t.devices.splice(from, 1); t.devices.splice(to, 0, x); HX.emit('devices'); HX.emit('session-light'); return; }
    try {
      await HX.mcp.call('plugin_reorder', { id: t.id, fromIndex: d.index, toIndex: t.devices[to].index });
      await rereadDevices(t);
    } catch (e) { HX.toast('Not moved: ' + e.message, 3600); }
  };

  /* ── 7. the browser's plug-in lists from the engine ── */
  let mockItems = null, mockCounts = null;
  const MOCK_ONLY = ['sounds', 'drums', 'mfx', 'clips', 'samples', 'proj', 'user'];
  const isHx = (p) => /^HypnoMix\b/i.test(p.name) || /hypnomix/i.test(p.creator || '');
  async function loadPlugins() {
    try {
      const r = await quiet('plugin_list_available', {});
      const all = ((r && r.plugins) || []).filter((p) => !p.hidden && p.status !== 'hidden' && p.status !== 'concealed');
      L.plugins = all;
      const B = HX.BROWSER;
      if (!mockItems) { mockItems = Object.assign({}, B.items); mockCounts = [...B.cats, ...B.places].map((c) => c.n); }
      /* the lists of the practice song (sounds, drums, clips, samples, project files, user library) are not the engine's:
         empty here, never shown as if they were */
      MOCK_ONLY.forEach((k) => { B.items[k] = []; });
      const name = (p) => p.name;
      const fx = all.filter((p) => p.isEffect && !p.isInstrument && !isHx(p)).map(name).sort();
      const inst = all.filter((p) => p.isInstrument).map(name).sort();
      const hx = all.filter(isHx).map(name).sort();
      B.items.afx = fx;
      B.items.plug = all.filter((p) => !isHx(p)).map((p) => p.name + ' (' + (p.typeLabel || p.type) + ')').sort();
      B.items.hx = [...hx, 'Scan session…', 'Vocal level check'];
      if (inst.length) B.items.inst = inst;
      [...B.cats, ...B.places].forEach((c) => { if (B.items[c.id]) c.n = B.items[c.id].length; });
      HX.emit('browser');
    } catch (e) { HX.log('err', 'plugin_list_available · ' + e.message); }
  }
  function restoreMockBrowser() {
    if (!mockItems) return;
    Object.assign(HX.BROWSER.items, mockItems);
    [...HX.BROWSER.cats, ...HX.BROWSER.places].forEach((c, i) => (c.n = mockCounts[i]));
    mockItems = null;
    HX.emit('browser');
  }
  L.pluginByName = function (n) {
    if (!L.plugins) return null;
    const bare = String(n).replace(/ \((LV2|Lua|VST3?|AU|LADSPA|CLAP|[^()]*)\)$/, '');
    return L.plugins.find((p) => p.name === n) || L.plugins.find((p) => p.name + ' (' + (p.typeLabel || p.type) + ')' === n) || L.plugins.find((p) => p.name === bare);
  };
  /* the browser's double-click: true when it was a real plug-in (added to the selected track) */
  L.browserActivate = function (cat, it) {
    if (!HX.mcp.connected || !L.plugins) return false;
    const p = L.pluginByName(it.name);
    if (!p) return false;
    L.addPlugin(HX.track(S.ui.trackId), p);
    return true;
  };

  /* ── wiring ── */
  const disc = HX.mcp.disconnect;
  HX.mcp.disconnect = function () { disc.apply(HX.mcp, arguments); if (L.on) L.stop(); };
  HX.on('session', () => { if (L.on && HX.mcp.connected) { applyColours(); if (S.session.meter == null && L.meta && L.meta.meter) S.session.meter = L.meta.meter; showMeter(); readLoop(); } else showMeter(); });
  HX.on('live', showMeter);
})();
