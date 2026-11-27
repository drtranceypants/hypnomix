/* Hypnomix · state, edits, undo, and the engine adapter (mock ⇄ MCP).
   Every change is an "op": { trackId, param, key, before, after }. A history entry is a list of ops.
   Undo re-sends the "before" values, so it works the same against the mock and against Ardour. */
(function () {
  'use strict';
  const HX = window.HX;

  const S = (HX.S = {
    session: null,
    scenes: [],
    findings: [],
    scanned: false,
    ui: { view: 'arrange', trackId: 't1', clipId: null, zoom: 7, scrollX: 0, theme: 'dark', bottom: 'devices' },
    history: [],
    future: [],
    log: [],
    launched: {}, // trackId → { slot, startBeat, queued }
  });

  HX.allTracks = () => (S.session ? [...S.session.tracks, ...S.session.returns, S.session.master].filter(Boolean) : []);
  HX.track = (id) => HX.allTracks().find((t) => t.id === id);
  HX.findClip = (clipId) => {
    for (const t of HX.allTracks()) { const c = t.clips.find((c) => c.id === clipId); if (c) return { track: t, clip: c }; }
    return null;
  };
  HX.trackByName = (name) => HX.allTracks().find((t) => t.name.toLowerCase() === String(name).toLowerCase());
  HX.beatsToSec = (b) => (b * 60) / S.session.tempo;
  HX.secToBeats = (s) => (s * S.session.tempo) / 60;

  HX.log = function (src, text) {
    const d = new Date();
    const ts = d.toTimeString().slice(0, 8) + '.' + String(d.getMilliseconds()).padStart(3, '0').slice(0, 1);
    S.log.push({ ts, src, text });
    if (S.log.length > 400) S.log.shift();
    HX.emit('log');
  };

  /* ── reading and writing one parameter locally ── */
  function ref(op) {
    const x = HX.liveEngine && HX.liveEngine.ref(op); // colour and track order (live.js)
    if (x) return x;
    const t = HX.track(op.trackId);
    switch (op.param) {
      case 'fader': return [t, 'faderDb'];
      case 'pan': return [t, 'pan'];
      case 'mute': return [t, 'mute'];
      case 'solo': return [t, 'solo'];
      case 'arm': return [t, 'arm'];
      case 'send': return [t.sends.find((s) => s.index === op.key), 'db'];
      case 'devOn': return [t.devices[op.key], 'on'];
      case 'devParam': return [t.devices[op.key[0]].params[op.key[1]], 'v'];
      case 'clipGain': { const f = HX.findClip(op.key); return [f && f.clip, 'gainDb']; }
      case 'clipStart': { const f = HX.findClip(op.key); return [f && f.clip, 'start']; }
    }
    return [null, null];
  }
  /* region ops (move, trim, split, fades, mute, remove: js/regions.js) bring their own get / apply */
  const handler = (op) => HX.opHandlers && HX.opHandlers[op.param];
  HX.getVal = function (op) { const hd = handler(op); if (hd && hd.get) return hd.get(op); const [o, k] = ref(op); return o ? o[k] : undefined; };
  HX.setLocal = function (op, v) {
    const hd = handler(op);
    if (hd && hd.apply) { hd.apply(op, v); HX.emit('param', op); return; }
    const [o, k] = ref(op);
    if (!o) return;
    o[k] = v;
    HX.emit('param', op);
  };

  /* ── engine adapter ── */
  async function send(op, value) {
    if (HX.isRegionOp && HX.isRegionOp(op)) return HX.sendRegionOp(op, value);
    const x = HX.liveEngine && HX.liveEngine.send(op, value); // colour and track order (live.js)
    if (x !== undefined) return x;
    const d = HX.describeOp(Object.assign({}, op, { after: value }));
    if (op.param === 'arm') {
      if (HX.mcp.connected) return HX.mcp.setRecEnable(op.trackId, value);
      return HX.log('mock', 'track_set_rec_enable ' + JSON.stringify({ id: op.trackId, value }));
    }
    if (!HX.mcp.connected) { HX.log('mock', d.tool + ' ' + JSON.stringify(d.args)); return; }
    if (op.param === 'devParam' || op.param === 'devOn') {
      const dv = HX.track(op.trackId).devices[op.param === 'devOn' ? op.key : op.key[0]];
      if (!dv || !dv.real) { HX.log('err', d.tool + ' skipped: this device is mock-only'); return; }
    }
    if (!HX.track(op.trackId).real && op.param !== 'clipGain' && op.param !== 'clipStart') { HX.log('err', d.tool + ' skipped: mock track'); return; }
    if ((op.param === 'clipGain' || op.param === 'clipStart') && !HX.findClip(op.key).clip.real) { HX.log('err', 'region_set_gain_db skipped: mock clip'); return; }
    return HX.mcp.call(d.tool, d.args);
  }

  /* edits wait while the engine cannot take them: an export (the scan's bounce) holds the session, or the engine
     stopped by itself. The local change is put back and the reason said; nothing is sent, nothing enters history. */
  HX.EXPORT_WAIT = 'An export is running: edits wait until it finishes';
  HX.ENGINE_WAIT = 'The engine stopped: edits wait until it is started again (Start, top right)';
  HX.editBlocked = function () {
    if (HX.exportBusy && HX.exportBusy()) return HX.EXPORT_WAIT;
    if (HX.engineLost) return HX.ENGINE_WAIT;
    return '';
  };
  HX.refuseEdit = function (ops) {
    const why = HX.editBlocked();
    if (!why) return false;
    for (const o of [...(ops || [])].reverse()) HX.setLocal(o, o.before);
    HX.arrange && (HX.arrange.dirty = true);
    HX.toast(why, 3600);
    HX.log('err', 'edit refused · ' + why);
    return true;
  };

  /* throttled live sends while dragging */
  const pending = new Map();
  HX.live = function (op, v) {
    HX.setLocal(op, v);
    if (HX.editBlocked()) return;                       // shown while dragging, put back on release (HX.commit)
    if (HX.engineUndoOp && HX.engineUndoOp(op)) return; // one engine undo step per edit: sent once, on release
    if (HX.liveEngine) HX.liveEngine.touch(op.trackId);
    const k = op.trackId + '|' + op.param + '|' + JSON.stringify(op.key);
    if (!HX.mcp.connected) return; // the mock logs only the committed value
    if (pending.has(k)) { pending.get(k).v = v; return; }
    const entry = { v };
    pending.set(k, entry);
    setTimeout(() => { pending.delete(k); send(op, entry.v).catch(() => {}); }, 40);
  };

  /* commit = record in history (+ send). ops carry before/after. */
  /* engine calls of commits, undos and redos run one after another (an undo never overtakes the edit it undoes) */
  let chain = Promise.resolve(), inflight = 0;
  const serial = (fn) => {
    inflight++;
    const run = () => Promise.resolve().then(fn).finally(() => { inflight--; });
    return (chain = chain.then(run, run));
  };
  HX.editBusy = () => inflight > 0;                    // an edit, undo or redo is still on its way to the engine
  HX.commit = function (label, ops, source) {
    ops = ops.filter((o) => o.before !== o.after);
    if (!ops.length) return Promise.resolve();
    if (HX.refuseEdit(ops)) return Promise.resolve();
    ops.forEach((o) => HX.setLocal(o, o.after));
    const entry = { label, ops, source: source || 'you', t: Date.now() };
    S.history.push(entry);
    S.future = [];
    HX.emit('history');
    HX.emit('edit', entry);                            // one change made (the guided tours listen for it)
    return serial(async () => {
      for (const o of ops) {
        try { await send(o, o.after); } catch (e) {
          o.failed = true;
          HX.setLocal(o, o.before);
          HX.toast('Engine refused: ' + e.message, 3200);
        }
      }
      if (ops.some((o) => o.failed)) {            // what the engine refused is not in its history: not in ours either
        entry.ops = ops.filter((o) => !o.failed);
        if (!entry.ops.length) { const i = S.history.indexOf(entry); if (i >= 0) S.history.splice(i, 1); HX.emit('history'); }
      }
      if (HX.liveEngine) HX.liveEngine.afterChange(ops.filter((o) => !viaEngine(o))); // read the engine's mixer state back (refused ops too: it puts the real value back)
      if (HX.afterEngineOps && HX.mcp.connected) { try { await HX.afterEngineOps(entry.ops); } catch (e) { HX.log('err', 'refresh · ' + e.message); } }
    });
  };
  HX.edit = function (op, after, label) {
    const before = op.before !== undefined ? op.before : HX.getVal(op);
    return HX.commit(label || describe(op, after), [Object.assign({}, op, { before, after })]);
  };
  function describe(op, v) {
    const t = HX.track(op.trackId);
    return (t ? t.name + ' ' : '') + op.param;
  }

  /* put ops back to their before values (locally and in the engine) without touching history */
  HX.revert = async function (ops) {
    for (const o of [...ops].reverse()) { HX.setLocal(o, o.before); try { await send(o, o.before); } catch (e) {} }
  };
  /* region edits on the engine are undone by the engine (session_undo / session_redo, js/regions.js);
     everything else re-sends its "before" (or "after") value */
  const viaEngine = (o) => !!(HX.engineUndoOp && HX.engineUndoOp(o));
  /* undo (dir 'undo': send each op's "before") or redo (send its "after"). An op the engine refuses is put back where it
     was (locally, and its entry stays on the stack it came from), the engine's reason is shown, and the view is read
     back from the engine: the history never says something the engine did not do. */
  async function step(h, dir) {
    const from = dir === 'undo' ? S.history : S.future, to = dir === 'undo' ? S.future : S.history;
    const ops = dir === 'undo' ? [...h.ops].reverse() : h.ops, key = dir === 'undo' ? 'before' : 'after', back = dir === 'undo' ? 'after' : 'before';
    const done = [], bad = [];
    let why = '';
    for (const o of ops) {
      if (viaEngine(o)) { done.push(o); continue; }
      HX.setLocal(o, o[key]);
      try { await send(o, o[key]); done.push(o); } catch (e) { bad.push(o); why = e.message; HX.setLocal(o, o[back]); }
    }
    const inOrder = (list) => h.ops.filter((o) => list.includes(o));
    if (bad.length) {
      from.push(Object.assign({}, h, { ops: inOrder(bad) }));                          // still applied in the engine: stays here
      if (done.length) to.push(Object.assign({}, h, { ops: inOrder(done) }));          // what did go through can be taken back
      HX.toast('Engine refused the ' + dir + ' of ' + h.label + ': ' + why, 4200);
      HX.log('err', dir + ' · ' + h.label + ' · ' + why);
    } else to.push(h);
    if (HX.liveEngine) HX.liveEngine.afterChange(h.ops.filter((o) => !viaEngine(o)));  // the engine's own values, whatever happened
    HX.emit('history');
    if (!bad.length) HX.toast((dir === 'undo' ? 'Undo: ' : 'Redo: ') + h.label);
  }
  HX.undo = () => serial(async () => {
    if (HX.editBlocked()) return HX.toast(HX.editBlocked(), 3600);
    const h = S.history.pop();
    if (!h) return HX.toast('Nothing to undo');
    if (h.ops.some(viaEngine) && !(await HX.engineUndo(h, 'undo'))) { S.history.push(h); HX.emit('history'); return; }
    await step(h, 'undo');
    if (S.future.includes(h)) HX.emit('undone', h);    // taken back (the guided tours listen for it)
  });
  HX.redo = () => serial(async () => {
    if (HX.editBlocked()) return HX.toast(HX.editBlocked(), 3600);
    const h = S.future.pop();
    if (!h) return HX.toast('Nothing to redo');
    if (h.ops.some(viaEngine) && !(await HX.engineUndo(h, 'redo'))) { S.future.push(h); HX.emit('history'); return; }
    await step(h, 'redo');
    if (S.history.includes(h)) HX.emit('redone', h);
  });

  HX.select = function (trackId, clipId) {
    if (trackId) S.ui.trackId = trackId;
    S.ui.clipId = clipId || null;
    HX.emit('select');
  };

  HX.loadMock = function () {
    S.session = HX.makeMockSession();
    S.scenes = HX.buildScenes(S.session);
    S.history = []; S.future = [];
    S.ui.trackId = 't1'; S.ui.clipId = null;
    HX.emit('session');
  };

  /* ── connect: read the real session through MCP and build the same model ── */
  /* calm, low-chroma track tints: enough hue to tell tracks apart, never louder than the waveforms */
  const PALETTE = ['#d9967a', '#d6a98c', '#cdb48f', '#c8b37c', '#93b39a', '#8eaab8', '#a9a0c4', '#9cbcb6', '#c99aa6', '#b3b98e'];
  function roleOf(name) {
    const n = name.toLowerCase();
    if (/vox|vocal|voc|lead|harm|bgv|choir/.test(n)) return 'vocal';
    if (/drum|kick|snare|hat|perc|room|oh\b/.test(n)) return 'drums';
    if (/bass|sub/.test(n)) return 'bass';
    if (/key|piano|e-?piano|synth|pad|organ/.test(n)) return 'keys';
    return 'guitar';
  }
  HX.loadFromEngine = async function () {
    const m = HX.mcp;
    const info = await m.sessionInfo();
    const tl = await m.tracksList();
    const routes = (tl && tl.tracks) || [];
    const sr = info.sampleRate || 48000, bpm = info.tempoBpm || 120;
    const s2b = (smp) => (smp / sr) * (bpm / 60);
    const sess = HX.makeMockSession(); // keep the shape; replace the content
    sess.name = info.sessionName || 'Untitled';
    sess.tempo = Math.round(bpm * 100) / 100; sess.sampleRate = sr;
    sess.tracks = []; sess.returns = []; sess.master = null;
    let maxBeat = 64, ci = 0;
    for (const r of routes) {
      const ti = await m.trackInfo(r.id);
      const isMaster = /^master$/i.test(r.name);
      const kind = r.type === 'midi_track' ? 'midi' : r.type === 'bus' ? 'bus' : 'audio';
      const role = isMaster ? 'master' : kind === 'bus' ? 'return' : roleOf(r.name);
      const t = {
        id: r.id, name: r.name, role, kind, color: isMaster ? '#bdb6aa' : kind === 'bus' ? '#9aa3ad' : PALETTE[ci++ % PALETTE.length],
        faderDb: ti.fader && ti.fader.db != null && isFinite(ti.fader.db) ? Math.max(-193, ti.fader.db) : ti.fader ? -193 : 0, pan: ti.pan ? 1 - 2 * ti.pan.position : 0,
        mute: !!ti.mute, solo: !!ti.solo, arm: !!ti.recEnabled, clips: [], height: 52,
        sends: (ti.sends || []).map((s) => ({ index: s.index, name: s.targetRouteName || s.name, db: s.db })),
        devices: (ti.plugins || []).map((p) => ({ id: 'p' + p.index + ':' + (p.displayName || p.name), name: p.displayName || p.name, kind: 'plugin', on: !!p.enabled, params: [], outs: [], real: true, index: p.index, post: !!p.postFader })),
        meter: { l: -100, r: -100, pk: -100, pkT: 0, clip: false }, real: true,
      };
      if (kind !== 'bus') {
        try {
          const rg = await m.trackRegions(r.id);
          (rg.regions || []).forEach((g) => {
            const c = HX.regionToClip(g, sr, bpm, sess.name); // real peaks, gain and fades load afterwards (js/regions.js)
            t.clips.push(c);
            maxBeat = Math.max(maxBeat, c.start + c.len);
          });
        } catch (e) {}
      }
      if (isMaster) { t.isMaster = true; sess.master = t; }
      else if (kind === 'bus') { t.isReturn = true; sess.returns.push(t); }
      else sess.tracks.push(t);
    }
    if (!sess.master) sess.master = { id: 'master-local', name: 'Master', role: 'master', kind: 'master', color: '#bdb6aa', faderDb: 0, pan: 0, mute: false, solo: false, arm: false, clips: [], sends: [], devices: [], height: 52, meter: { l: -100, r: -100, pk: -100, pkT: 0, clip: false }, isMaster: true };
    sess.lengthBeats = Math.ceil(maxBeat / 4) * 4 + 16;
    sess.sections = [];
    try {
      const ml = await m.call('markers_list');
      const arr = Array.isArray(ml) ? ml : (ml && ml.markers) || [];
      /* section markers are the arrangement's sections; fall back to plain marks when a session has none */
      const usable = arr.filter((k) => !k.isSynthetic && !k.isAutoLoop && !k.isAutoPunch && !k.isSessionRange && !k.isXrun && !k.isCue && !k.isHidden);
      const secs = usable.filter((k) => k.isSection);
      const pts = (secs.length ? secs : usable.filter((k) => !k.isRange || k.isRangeMarker)).map((k) => ({ name: k.name, start: s2b(k.startSample) })).sort((a, b) => a.start - b.start);
      pts.forEach((p, i) => sess.sections.push({ name: p.name, start: p.start, len: ((pts[i + 1] ? pts[i + 1].start : sess.lengthBeats) - p.start) }));
    } catch (e) {}
    sess.snapshots = [{ name: sess.name, when: 'current', current: true }];
    S.session = sess;
    S.scenes = HX.buildScenes(sess);
    S.history = []; S.future = [];
    S.ui.trackId = sess.tracks[0] ? sess.tracks[0].id : sess.master.id; S.ui.clipId = null;
    S.findings = []; S.scanned = false;
    HX.emit('session');
    return sess;
  };

  /* plug-in parameters are fetched when a real device is shown */
  HX.loadDeviceParams = async function (track, dev) {
    if (!dev.real || dev.loaded) return;
    dev.loaded = true;
    try {
      const d = await HX.mcp.call('plugin_get_description', { id: track.id, pluginIndex: dev.index });
      dev.params = (d.parameters || []).filter((p) => p.isControl && p.isInput && !p.isHidden).slice(0, 8).map((p) => ({ n: p.label, v: p.currentValue, min: p.lower, max: p.upper, unit: '', realIndex: p.index }));
      HX.emit('devices');
    } catch (e) { dev.loaded = false; }
  };

  /* ── drag-to-edit binding shared by headers, mixer and devices ──
     getOp() → op; opts: min, max, sens (units/px), toPos/fromPos (drag in another space), reset, label */
  HX.bindDrag = function (el, getOp, opts) {
    let before, cur, op;
    HX.dragY(el, () => {
      op = getOp(); before = HX.getVal(op); cur = opts.toPos ? opts.toPos(before) : before;
      document.body.style.cursor = 'ns-resize'; HX.dragging = true;
    }, (dy, fine) => {
      const sens = (opts.sens || 1) * (fine ? 0.1 : 1);
      cur = HX.clamp(cur + dy * sens, opts.toPos ? 0 : opts.min, opts.toPos ? 1 : opts.max);
      let v = opts.fromPos ? opts.fromPos(cur) : cur;
      if (opts.step) v = Math.round(v / opts.step) * opts.step;
      HX.live(op, v);
    }, () => {
      document.body.style.cursor = ''; HX.dragging = false;
      const after = HX.getVal(op);
      if (after !== before) HX.commit(opts.label ? opts.label(op, after) : (HX.track(op.trackId).name + ' ' + op.param), [Object.assign({}, op, { before, after })]);
    });
    if (opts.reset !== undefined) el.addEventListener('dblclick', () => { const o = getOp(); HX.edit(o, opts.reset, (opts.label ? opts.label(o, opts.reset) : 'reset')); });
  };
})();
