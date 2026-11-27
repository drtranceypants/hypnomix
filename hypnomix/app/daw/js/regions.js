/* Hypnomix · the Arrangement's regions on the real engine: real waveforms (region_get_peaks), region edits as
   ops on the shared op path ({ trackId, param, key, before, after }), each one engine undo step, undo/redo
   through session_undo / session_redo, and importing audio (session_import_audio).

   Positions on a clip stay in beats (the view's unit); the engine gets samples (constant tempo, as the rest of
   the view assumes). With the mock session the same ops apply locally and undo puts the "before" values back. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S;

  const spb = () => (S.session.sampleRate * 60) / S.session.tempo;            // samples per beat
  const b2s = (b) => Math.max(0, Math.round(b * spb()));
  const s2b = (s) => s / spb();
  HX.beatsToSamples = b2s; HX.samplesToBeats = s2b;

  /* ── fades: read back from the engine (region_get_info: fadeInSamples, fadeOutSamples, fadeInActive,
     fadeOutActive). Only for an older engine whose region_get_info has no fade fields are the lengths this view
     set remembered in this browser, per session and region, as a fallback. Ardour's default is 64 samples. */
  const FADE_KEY = 'hx.fades';
  const fadeMemo = (() => { try { return JSON.parse(localStorage.getItem(FADE_KEY) || '{}'); } catch (e) { return {}; } })();
  const fadeKey = (rid) => (S.session ? S.session.name : '') + '|' + rid;
  let engineFades = false;                  // set once region_get_info has reported fades: no browser memory then
  function rememberFades(c) {
    if (!c.real || engineFades) return;
    fadeMemo[fadeKey(c.id)] = [Math.round(b2s(c.fadeIn)), Math.round(b2s(c.fadeOut))];
    try { localStorage.setItem(FADE_KEY, JSON.stringify(fadeMemo)); } catch (e) {}
  }

  const COARSE_MAX = 24000;                 // points in one region's coarse array (96 KB)
  HX.COARSE_MAX = COARSE_MAX;

  /* a region from track_get_regions → a clip of the view's model */
  HX.regionToClip = function (g, sr, bpm, sessionName) {
    const sb = (sr * 60) / bpm, start = g.startSample / sb, len = Math.max(1 / 64, g.lengthSamples / sb);
    const memo = fadeMemo[(sessionName != null ? sessionName : S.session ? S.session.name : '') + '|' + g.regionId];
    const c = {
      id: g.regionId, name: g.name, start, len, gainDb: 0, kind: g.type === 'midi' ? 'midi' : 'audio', seed: HX.hash(g.regionId),
      real: true, muted: !!g.muted, pos: g.startSample, lenS: g.lengthSamples, offS: 0,
      fadeIn: (memo ? memo[0] : 64) / sb, fadeOut: (memo ? memo[1] : 64) / sb, fadesKnown: !!memo,
    };
    if (c.kind === 'midi') c.notes = [];
    else {
      /* the coarse pass is a fallback while finer tiles load, and what the clip detail reads: a long region gets fewer points a
         beat so the arrays stay small (a two-hour region would take 2 MB at the full rate; at most COARSE_MAX points here) */
      c.pres = Math.min(HX.PEAK_RES, COARSE_MAX / Math.max(1, len));
      c.peaks = new Float32Array(Math.ceil(len * c.pres)); c.loading = true;
    }
    return c;
  };

  /* ── peaks ──
     Drawing asks for tiles at a power-of-two samples-per-pixel matched to the zoom (2048 pixels a tile, so one
     request is at most 4096 min/max pairs for a stereo region, far under the engine's 40000). Tiles are cached by
     region id + resolution + tile number; zooming or scrolling asks again after a short pause; two requests go out
     at a time (the engine's replies are chunked with Content-Length, so big or overlapping replies arrive whole). Each region also gets
     one coarse pass (HX.PEAK_RES points a beat) that fills clip.peaks, which the clip detail and meters read and the
     arrangement draws while finer tiles load. Peaks come with the region gain applied: they are stored at 0 dB. */
  const TILE = 2048, CACHE_MAX = 900, PARALLEL = 2;
  /* region_get_peaks: at most PEAK_INFLIGHT requests out at a time (the arrangement and the meters' own poll
     share the connection), each at most the engine's own cap of 40000 [min,max] pairs over all channels.
     A reply is still checked (|value| <= 4) and asked once more when it is not. -32002 means the engine is still
     building that file's peaks (just after an import or on a session that had none): asked again shortly. */
  const PEAK_INFLIGHT = 2, PEAK_PAIRS = 40000;
  const peakQ = [];
  let peakBusy = 0;
  function getPeaks(args, pri) {
    return new Promise((resolve, reject) => { peakQ.push({ args, pri, resolve, reject }); peakQ.sort((a, b) => a.pri - b.pri); runPeaks(); });
  }
  async function runPeaks() {
    while (peakBusy < PEAK_INFLIGHT && peakQ.length) {
      const job = peakQ.shift();
      peakBusy++;
      (async () => {
        let res, err;
        for (let tries = 0; tries < 2; tries++) {
          try {
            res = await HX.mcp.call('region_get_peaks', job.args, { quiet: true });
            if ((res.channels || []).every((ch) => (ch.peaks || []).every((p) => Math.abs(p[0]) <= 4 && Math.abs(p[1]) <= 4))) { err = null; break; }
            err = new Error('peaks out of range'); res = null;
          } catch (e) { err = e; break; }
        }
        err ? job.reject(err) : job.resolve(res);
      })().finally(() => { peakBusy--; runPeaks(); });
    }
  }
  const cache = new Map();                 // rid|spp|tile → { lo: Float32Array, hi: Float32Array, n }
  const origin = new Map();                // rid → clip.offS when its tiles were fetched (a front trim being dragged shifts them)
  const queue = [], inflight = new Set(), queued = new Set();
  const failed = new Map();                // key → time: a tile the engine could not give is asked again after 5 s, not every frame
  let pumpT = null;
  const P = (HX.peaks = {
    TILE,
    level(sppActual) { let s = 16; while (s * 2 <= sppActual) s *= 2; return s; },
    tile(rid, spp, i) { return cache.get(rid + '|' + spp + '|' + i); },
    origin(rid) { return origin.get(rid) || 0; },
    /* the arrangement says what it draws; missing tiles are fetched after a pause (no request storm while zooming) */
    want(c, spp, s0, s1) {
      if (!c.real || c.temp || c.kind !== 'audio' || !HX.mcp.connected) return;
      if (!origin.has(c.id)) origin.set(c.id, c.offS || 0);
      const t0 = Math.max(0, Math.floor(s0 / spp / TILE)), t1 = Math.floor(Math.max(s0, s1 - 1) / spp / TILE);
      for (let i = t0; i <= t1; i++) {
        const k = c.id + '|' + spp + '|' + i;
        if (cache.has(k) || inflight.has(k) || queued.has(k) || performance.now() - (failed.get(k) || -1e9) < 5000) continue;
        queued.add(k); queue.unshift({ k, rid: c.id, spp, i, tries: 0 });
      }
      if (!pumpT) pumpT = setTimeout(() => { pumpT = null; pump(); }, 140);
    },
    /* the view is moving (zoom, scroll): wait until it rests before asking */
    hold() { if (pumpT) { clearTimeout(pumpT); pumpT = setTimeout(() => { pumpT = null; pump(); }, 140); } },
    /* forget a region's peaks (its content changed: trim, split, undo); the next draw asks again */
    drop(rid) {
      for (const k of [...cache.keys()]) if (k.startsWith(rid + '|')) cache.delete(k);
      for (let i = queue.length - 1; i >= 0; i--) if (queue[i].rid === rid) { queued.delete(queue[i].k); queue.splice(i, 1); }
      for (const k of [...failed.keys()]) if (k.startsWith(rid + '|')) failed.delete(k);
      origin.delete(rid);
    },
    stats() { return { tiles: cache.size, queued: queue.length, inflight: inflight.size }; },
    clear() { cache.clear(); origin.clear(); failed.clear(); queue.length = 0; queued.clear(); },
  });

  function mergeChannels(res, n) {
    const lo = new Float32Array(n), hi = new Float32Array(n);
    (res.channels || []).forEach((ch, ci) => {
      const pk = ch.peaks || [];
      for (let j = 0; j < n && j < pk.length; j++) {
        const a = pk[j][0], b = pk[j][1];
        if (ci === 0 || a < lo[j]) lo[j] = a;
        if (ci === 0 || b > hi[j]) hi[j] = b;
      }
    });
    return { lo, hi };
  }
  function pump() {
    while (inflight.size < PARALLEL && queue.length) {
      const job = queue.shift(); queued.delete(job.k);
      const f = HX.findClip(job.rid); const c = f && f.clip;
      if (!c || c.temp || !HX.mcp.connected) continue;
      const total = c.lenS, start = job.i * TILE * job.spp;
      if (start >= total) continue;
      const length = Math.min(TILE * job.spp, total - start);
      inflight.add(job.k);
      const g = HX.dbToGain(c.gainDb || 0) || 1;
      getPeaks({ region_id: c.id, samples_per_pixel: job.spp, start_samples: start, length_samples: length }, 0)
        .then((res) => {
          const n = res.npeaks || Math.ceil(length / job.spp);
          const m = mergeChannels(res, n);
          for (let j = 0; j < n; j++) { m.lo[j] /= g; m.hi[j] /= g; }
          cache.set(job.k, { lo: m.lo, hi: m.hi, n });
          if (cache.size > CACHE_MAX) cache.delete(cache.keys().next().value);
          HX.arrange.dirty = true;
        })
        .catch(() => { failed.set(job.k, performance.now()); setTimeout(() => (HX.arrange.dirty = true), 5100); })  // asked again after 5 s (a file still being built, -32002, too)
        .finally(() => { inflight.delete(job.k); pump(); });
    }
  }

  /* region info (its gain: track_get_regions does not carry it), then one coarse pass into clip.peaks */
  const coarse = [];
  let coarseBusy = 0;
  HX.loadClipPeaks = (c) => loadClip(c);   // take lanes (js/takes.js)
  function loadClip(c) { if (c.real && !c.temp && c.kind === 'audio') { coarse.push(c); pumpCoarse(); } }
  function pumpCoarse() {
    while (coarseBusy < 2 && coarse.length) {
      const c = coarse.shift();
      coarseBusy++;
      fillCoarse(c).catch((e) => { c.loading = false; c.peakErr = /-32002/.test(e.message) ? 'the engine is still building this file’s waveform (reload to ask again)' : e.message; HX.arrange.dirty = true; HX.log('err', 'peaks of ' + c.name + ' · ' + e.message); }).finally(() => { coarseBusy--; pumpCoarse(); });
    }
  }
  /* the region's gain and fades (track_get_regions carries neither): region_get_info is the truth */
  async function readGain(c) {
    const info = await HX.mcp.call('region_get_info', { regionId: c.id }, { quiet: true });
    if (!info) return;
    const f = HX.findClip(c.id);
    if (info.audio && typeof info.audio.gainDb === 'number') {
      const db = Math.round(info.audio.gainDb * 100) / 100;
      c.gainKnown = true;
      if (db !== c.gainDb) { c.gainDb = db; if (f) HX.emit('param', { trackId: f.track.id, param: 'clipGain', key: c.id }); }
    }
    if (typeof info.fadeInSamples === 'number' && typeof info.fadeOutSamples === 'number') {
      engineFades = true;
      /* a switched-off fade plays as none */
      const fin = info.fadeInActive === false ? 0 : s2b(info.fadeInSamples), fout = info.fadeOutActive === false ? 0 : s2b(info.fadeOutSamples);
      c.fadesKnown = true; c.fadesFromEngine = true; c.envelopeActive = !!info.envelopeActive;
      if (Math.abs(fin - c.fadeIn) > 1e-9 || Math.abs(fout - c.fadeOut) > 1e-9) {
        c.fadeIn = fin; c.fadeOut = fout; HX.arrange.dirty = true;
        if (f) HX.emit('param', { trackId: f.track.id, param: 'regionFades', key: c.id });
      }
    }
  }
  HX.readRegionInfo = readGain;
  async function fillCoarse(c) {
    if (!c.gainKnown) await readGain(c);
    const sppB = spb() / (c.pres || HX.PEAK_RES), n = c.peaks.length, g = HX.dbToGain(c.gainDb || 0) || 1;
    const CH = Math.floor(PEAK_PAIRS / Math.max(1, c.nch || 2));   // points per request: the engine's cap over all channels
    const out = new Float32Array(n);
    for (let at = 0; at < n; at += CH) {
      const cnt = Math.min(CH, n - at), s = Math.round(at * sppB);
      if (s >= c.lenS) break;
      let res;
      for (let tries = 0; ; tries++) {
        try { res = await getPeaks({ region_id: c.id, samples_per_pixel: sppB, start_samples: s, length_samples: Math.min(c.lenS - s, Math.floor(cnt * sppB)) }, 1); break; }
        catch (e) {                         // -32002: the file's peaks are still being built; wait for them (up to ~2 minutes)
          if (!/-32002/.test(e.message) || tries >= 60) throw e;
          if (!c.building) { c.building = true; HX.arrange.dirty = true; }
          await new Promise((r) => setTimeout(r, Math.min(4000, 500 + tries * 250)));
        }
      }
      c.building = false;
      if (res.channelsInRegion) c.nch = res.channelsInRegion;
      const m = mergeChannels(res, Math.min(cnt, res.npeaks || cnt));
      for (let j = 0; j < m.lo.length; j++) out[at + j] = Math.max(-m.lo[j], m.hi[j]) / g;
      if (!HX.findClip(c.id)) return;      // gone meanwhile
      if ((at / CH) % 4 === 3) { c.peaks = out; HX.arrange.dirty = true; }   // show it filling in
    }
    c.peaks = out; c.loading = false; c.peakErr = null;
    HX.arrange.dirty = true; HX.emit('peaks', c.id);
  }

  /* after loadFromEngine: fetch every region's gain and coarse peaks in the background */
  let keep = null;                          // id → clip of the session before, when it is read again for new tracks
  HX.on('session', () => {
    if (!keep) { P.clear(); coarse.length = 0; }
    if (!HX.mcp.connected) { keep = null; return; }
    HX.allTracks().forEach((t) => t.clips.forEach((c) => {
      const o = keep && keep.get(c.id);
      if (o && o.lenS === c.lenS && o.kind === c.kind && !o.loading && o.peaks) Object.assign(c, { peaks: o.peaks, pres: o.pres, loading: false, gainDb: o.gainDb, gainKnown: o.gainKnown, peakErr: o.peakErr });
      else loadClip(c);
    }));
    keep = null;
  });

  /* ── re-read tracks' regions from the engine (after an edit, undo or redo): the engine is the truth ── */
  HX.refreshRegions = async function (trackIds) {
    if (!HX.mcp.connected) return;
    const sr = S.session.sampleRate, bpm = S.session.tempo, sel = S.ui.clipId;
    let selTrack = null, selStart = null;
    const fs = sel && HX.findClip(sel); if (fs) { selTrack = fs.track.id; selStart = fs.clip.start; }
    const gone = [];                       // regions no longer there (a split's source): new ones at the same edge keep its fades
    for (const id of new Set(trackIds)) {
      const t = HX.track(id); if (!t || !t.real) continue;
      let rg; try { rg = await HX.mcp.trackRegions(id); } catch (e) { continue; }
      const old = new Map(t.clips.map((c) => [c.id, c]));
      const ids = new Set((rg.regions || []).map((g) => g.regionId));
      gone.push(...t.clips.filter((c) => c.real && c.pos != null && !ids.has(c.id)));
      t.clips = (rg.regions || []).map((g) => {
        const o = old.get(g.regionId), n = HX.regionToClip(g, sr, bpm);
        if (o && o.kind === n.kind) {
          /* a move keeps the content; a trim changes the length (and a front trim the start in the source) */
          const content = o.lenS !== g.lengthSamples || !!o.offS;
          Object.assign(o, { name: n.name, start: n.start, len: n.len, muted: n.muted, pos: n.pos, lenS: n.lenS });
          if (content) { o.offS = 0; P.drop(o.id); if (o.kind === 'audio') { o.peaks = n.peaks; o.pres = n.pres; o.loading = true; loadClip(o); } }
          return o;
        }
        if (!n.fadesKnown && n.kind === 'audio') {      // a split: the left part keeps the fade-in, the right the fade-out
          const a = gone.find((c) => c.pos === n.pos), b = gone.find((c) => c.pos + c.lenS === n.pos + n.lenS);
          if (a || b) { if (a) n.fadeIn = Math.min(a.fadeIn, n.len); if (b) n.fadeOut = Math.min(b.fadeOut, n.len); n.fadesKnown = true; rememberFades(n); }
        }
        P.drop(n.id); loadClip(n);
        return n;
      });
    }
    /* gains: an undo or redo may have changed them (and a split's halves carry the gain of the region they came from) */
    for (const id of new Set(trackIds)) { const t = HX.track(id); if (t) for (const c of t.clips) if (c.real && c.kind === 'audio') await readGain(c).catch(() => {}); }
    /* the selected region may have a new id (split, a move to another track, undo): keep the one at its place */
    if (sel && !HX.findClip(sel) && selTrack) {
      const t = HX.track(selTrack);
      const c = t && (t.clips.find((c) => selStart >= c.start - 1e-6 && selStart < c.start + c.len) || t.clips[0]);
      S.ui.clipId = c ? c.id : null;
      HX.emit('select');
    }
    const last = HX.allTracks().reduce((m, t) => t.clips.reduce((m2, c) => Math.max(m2, c.start + c.len), m), 0);
    if (last + 8 > S.session.lengthBeats) S.session.lengthBeats = Math.ceil(last / 4) * 4 + 16;
    HX.arrange.dirty = true;
    HX.emit('regions', trackIds);
  };

  /* ── the region ops ──
     get(op) → the value now; apply(op, v) → set it locally (both directions); call(op, v) → { tool, args } for the
     engine; undo → the engine's name for the step (checked when undoing, so a step someone else made is never
     undone in its place). */
  const findC = (id) => { const f = HX.findClip(id); return f ? f.clip : null; };
  const snap = (c) => Object.assign({}, c);
  const H = (HX.opHandlers = HX.opHandlers || {});
  H.regionMove = {
    undo: 'move region',
    get: (op) => { const f = HX.findClip(op.key); return f && { trackId: f.track.id, start: f.clip.start }; },
    apply(op, v) {
      const f = HX.findClip(op.key); if (!f || !v) return;
      f.clip.start = Math.max(0, v.start);
      if (v.trackId !== f.track.id) { const t = HX.track(v.trackId); if (!t) return; f.track.clips.splice(f.track.clips.indexOf(f.clip), 1); t.clips.push(f.clip); }
    },
    call: (op, v) => ({ tool: 'region_move_to_sample', args: Object.assign({ regionId: op.key, sample: b2s(v.start) }, op.before && v.trackId !== op.before.trackId ? { trackId: v.trackId } : {}) }),
    tracks: (op) => [op.trackId, op.before && op.before.trackId, op.after && op.after.trackId],
  };
  H.regionTrim = {
    undo: 'resize region',
    get: (op) => { const c = findC(op.key); return c && { start: c.start, len: c.len }; },
    apply(op, v) {
      const c = findC(op.key); if (!c || !v) return;
      const d = v.start - c.start;
      c.offS = (c.offS || 0) + d * spb();
      if (!c.real) c.offs = (c.offs || 0) + d;
      c.start = v.start; c.len = v.len;
      c.fadeIn = Math.min(c.fadeIn, c.len / 2); c.fadeOut = Math.min(c.fadeOut, c.len / 2);
    },
    call: (op, v) => ({ tool: 'region_resize_samples', args: { regionId: op.key, startSample: b2s(v.start), endSample: b2s(v.start + v.len) } }),
  };
  H.regionSplit = {
    undo: 'split region',
    /* before = the whole clip (a copy), after = the beat to split at */
    get: (op) => snap(findC(op.key)),
    apply(op, v) {
      const t = HX.track(op.trackId); if (!t) return;
      if (typeof v === 'number') {
        const i = t.clips.findIndex((c) => c.id === op.key); if (i < 0) return;
        const c = t.clips[i], at = v - c.start;
        const a = Object.assign(snap(c), { id: c.id + '.1', name: c.name + '.1', len: at, fadeOut: Math.min(c.fadeOut, at / 2), lenS: Math.round(at * spb()) });
        const b = Object.assign(snap(c), { id: c.id + '.2', name: c.name + '.2', start: v, len: c.len - at, offs: (c.offs || 0) + at, offS: (c.offS || 0) + at * spb(), fadeIn: Math.min(c.fadeIn, (c.len - at) / 2), pos: c.pos + Math.round(at * spb()), lenS: c.lenS - Math.round(at * spb()) });
        if (c.real) { a.fadeOut = b.fadeIn = Math.min(64 / spb(), a.len, b.len); }   // the engine gives the cut its default fades
        if (c.peaks && c.real) { const k = Math.round(at * (c.pres || HX.PEAK_RES)); a.peaks = c.peaks.subarray(0, k); b.peaks = c.peaks.subarray(k); b.offS = 0; a.temp = b.temp = true; } // until the engine's two regions are read
        t.clips.splice(i, 1, a, b);
        if (S.ui.clipId === c.id) S.ui.clipId = a.id;
      } else if (v && v.id) {
        t.clips = t.clips.filter((c) => c.id !== v.id + '.1' && c.id !== v.id + '.2');
        t.clips.push(snap(v)); t.clips.sort((a, b) => a.start - b.start);
      }
    },
    call: (op, v) => (typeof v === 'number' ? { tool: 'region_split', args: { regionId: op.key, sample: b2s(v) } } : null),
  };
  H.regionFades = {
    undo: 'set region fades',
    get: (op) => { const c = findC(op.key); return c && { fin: c.fadeIn, fout: c.fadeOut }; },
    apply(op, v) { const c = findC(op.key); if (!c || !v) return; c.fadeIn = v.fin; c.fadeOut = v.fout; c.fadesKnown = true; rememberFades(c); },
    call: (op, v) => ({ tool: 'region_set_fades', args: { region_id: op.key, fade_in_samples: b2s(v.fin), fade_out_samples: b2s(v.fout) } }),
  };
  H.regionMute = {
    undo: (op, v) => (v ? 'mute region' : 'unmute region'),
    get: (op) => { const c = findC(op.key); return c && !!c.muted; },
    apply(op, v) { const c = findC(op.key); if (c) c.muted = !!v; },
    call: (op, v) => ({ tool: 'region_mute', args: { region_id: op.key, muted: !!v } }),
  };
  H.regionRemove = {
    undo: 'remove region',
    /* before = { clip, index }, after = null */
    get: (op) => { const f = HX.findClip(op.key); return f && { clip: snap(f.clip), index: f.track.clips.indexOf(f.clip) }; },
    apply(op, v) {
      const t = HX.track(op.trackId); if (!t) return;
      if (v && v.clip) { if (!t.clips.some((c) => c.id === v.clip.id)) t.clips.splice(Math.min(v.index, t.clips.length), 0, snap(v.clip)); }
      else { t.clips = t.clips.filter((c) => c.id !== op.key); if (S.ui.clipId === op.key) S.ui.clipId = null; }
    },
    call: (op, v) => (v ? null : { tool: 'region_remove', args: { region_id: op.key } }),
  };
  /* clip gain keeps store.js's own get/set and region_set_gain_db; here it only gains engine undo */
  H.clipGain = { undo: 'set region gain', storeOwned: true };
  /* an import: the engine already did it (the files were copied); the op only carries its undo step */
  H.regionImport = {
    undo: 'insert file', imported: true,
    get: () => null, apply() {}, call: () => null,
    tracks: (op) => [op.trackId].concat((op.after && op.after.trackIds) || []),
  };

  HX.isRegionOp = (op) => !!H[op.param] && !H[op.param].storeOwned;
  /* an op whose undo is the engine's own (session_undo), not re-sending the "before" value */
  HX.engineUndoOp = (op) => HX.mcp.connected && !!H[op.param] && (H[op.param].undo !== undefined) && (op.param !== 'clipGain' || !!(findC(op.key) || {}).real);
  HX.describeRegionOp = function (op) {
    const h = H[op.param]; if (!h || h.storeOwned) return null;
    const d = h.call && h.call(op, op.after);
    return d || { tool: op.param === 'regionImport' ? 'session_import_audio' : '(local)', args: {} };
  };
  HX.sendRegionOp = async function (op, value) {
    const h = H[op.param];
    const d = h.call(op, value);
    if (!d) return null;
    if (!HX.mcp.connected) { HX.log('mock', d.tool + ' ' + JSON.stringify(d.args)); return null; }
    const c = findC(op.key);
    if (c && !c.real) { HX.log('err', d.tool + ' skipped: mock clip'); return null; }
    const r = await HX.mcp.call(d.tool, d.args);
    if (op.param === 'regionFades' && r && r.fadeIn) {       // the engine's own fade lengths (it keeps at least 64 samples)
      const c2 = findC(op.key); if (c2) { c2.fadeIn = s2b(r.fadeIn.lengthSamples); c2.fadeOut = s2b(r.fadeOut.lengthSamples); rememberFades(c2); }
    }
    return r;
  };
  const opTracks = (ops) => ops.flatMap((o) => (H[o.param] && H[o.param].tracks ? H[o.param].tracks(o) : [o.trackId])).filter(Boolean);
  HX.afterEngineOps = async function (ops) {
    /* a clip-gain edit: its gain read back from the engine (region_get_info) */
    for (const o of ops) if (o.param === 'clipGain') { const c = findC(o.key); if (c && c.real) await readGain(c).catch(() => {}); }
    const rops = ops.filter((o) => HX.engineUndoOp(o) && o.param !== 'clipGain');
    if (!rops.length) return;
    if (rops.some((o) => o.param === 'regionImport')) return reloadKeepingHistory();
    return HX.refreshRegions(opTracks(rops));
  };

  /* undo / redo of the engine ops of one history entry, one engine step at a time; each step's name is checked
     against the op, and when it does not match (someone else changed the session since) it is put back */
  HX.engineUndo = async function (entry, dir) {
    const eops = entry.ops.filter(HX.engineUndoOp);
    if (!eops.length) return true;
    const seq = dir === 'undo' ? [...eops].reverse() : eops;
    const tool = dir === 'undo' ? 'session_undo' : 'session_redo', back = dir === 'undo' ? 'session_redo' : 'session_undo';
    let done = 0, bad = null;
    for (const o of seq) {
      const h = H[o.param];
      const want = typeof h.undo === 'function' ? h.undo(o, o.after) : h.undo;
      let r;
      try { r = await HX.mcp.call(tool, { count: 1 }); } catch (e) { bad = e.message; break; }
      const moved = dir === 'undo' ? r.undoDepthAfter < r.undoDepthBefore : r.redoDepthAfter < r.redoDepthBefore;
      const name = dir === 'undo' ? r.nextRedo : r.nextUndo;
      if (!moved) { bad = 'the engine has nothing to ' + (dir === 'undo' ? 'undo' : 'redo'); break; }
      if (want && String(name).toLowerCase() !== want) {
        await HX.mcp.call(back, { count: 1 }).catch(() => {});
        bad = 'the engine’s last step is “' + name + '”, not this edit';
        break;
      }
      done++;
    }
    if (bad && done) await HX.mcp.call(back, { count: done }).catch(() => {});
    /* an older engine does not report fades: the view puts the undone (or redone) lengths back itself
       (a newer one's are read back by refreshRegions below, with region_get_info) */
    if (!bad && !engineFades) for (const o of seq) if (o.param === 'regionFades') H.regionFades.apply(o, dir === 'undo' ? o.before : o.after);
    if (eops.some((o) => o.param === 'regionImport')) await reloadKeepingHistory();
    else await HX.refreshRegions(opTracks(eops));
    if (bad) { HX.toast('Not ' + (dir === 'undo' ? 'undone' : 'redone') + ': ' + bad, 4200); HX.log('err', tool + ' · ' + bad); return false; }
    return true;
  };

  /* new tracks (an import) need the session read again; keep the history and the view where they are */
  async function reloadKeepingHistory() {
    const hist = S.history, fut = S.future, z = S.ui.zoom, sx = S.ui.scrollX, tid = S.ui.trackId;
    keep = new Map(HX.allTracks().flatMap((t) => t.clips.map((c) => [c.id, c])));   // the regions already read keep their peaks
    try { await HX.loadFromEngine(); } finally { keep = null; }
    S.history = hist; S.future = fut;
    S.ui.zoom = z; S.ui.scrollX = sx; if (HX.track(tid)) S.ui.trackId = tid;
    HX.arrange.dirty = true;
    HX.emit('history'); HX.emit('select');
  }

  /* ── import ──
     paths: absolute paths the engine can read. A drop from the Finder sends each file to the app first
     (POST /api/daw/upload: a browser page never sees a dropped file's path), then imports the saved copy. */
  HX.uploadForImport = async function (file, onProgress) {
    const tok = window.HX_TOKEN && !/^__/.test(window.HX_TOKEN) ? window.HX_TOKEN : '';
    if (!tok) throw new Error('open the DAW view from the HypnoMix app to import');
    return new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open('POST', '/api/daw/upload?name=' + encodeURIComponent(file.name));
      x.setRequestHeader('X-Hypnomix', tok);
      x.setRequestHeader('Content-Type', 'application/octet-stream');
      x.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
      x.onload = () => { let j = {}; try { j = JSON.parse(x.responseText); } catch (e) {} x.status === 200 ? resolve(j) : reject(new Error(j.error || 'HTTP ' + x.status)); };
      x.onerror = () => reject(new Error('the app did not answer'));
      x.send(file);
    });
  };
  HX.importAudio = async function (paths, opts) {
    opts = opts || {};
    if (HX.editBlocked()) throw new Error(HX.editBlocked());
    if (!HX.mcp.connected) throw new Error('importing needs the engine (connect first)');
    const t = opts.trackId && HX.track(opts.trackId);
    const args = { paths, position_samples: b2s(opts.beat || 0) };
    if (t && t.real && t.kind === 'audio') { args.mode = 'to_track'; args.track_id = t.id; }
    else args.mode = 'new_tracks';
    const before = new Set(HX.allTracks().map((t) => t.id));
    /* the engine copies the files before it answers: minutes, not seconds (counted, so two imports at once
       put the usual timeout back only when both are done) */
    const M = HX.mcp;
    if (!M._longCalls) M._baseTimeout = M.timeoutMs;
    M._longCalls = (M._longCalls || 0) + 1; M.timeoutMs = 600000;
    let r;
    try { r = await M.call('session_import_audio', args); } finally { if (--M._longCalls === 0) M.timeoutMs = M._baseTimeout; }
    const ok = (r && r.imported) || [];
    if (ok.length) {
      await reloadKeepingHistory();
      const fresh = HX.allTracks().filter((t) => !before.has(t.id)).map((t) => t.id);
      const op = { trackId: t ? t.id : (fresh[0] || ''), param: 'regionImport', key: paths.join('\n'), before: null, after: { paths, trackIds: fresh, mode: args.mode } };
      S.history.push({ label: 'Import ' + paths.map((p) => p.split('/').pop()).join(', '), ops: [op], source: 'you', t: Date.now() });
      S.future = [];
      HX.emit('history');
    }
    return r;
  };
})();
