/* Hypnomix · transport clock, the single rAF loop, meters (simulated on the mock session).
   The playhead is interpolated locally every frame; when connected, live.js polls the engine (meters_get carries
   the transport's sample) and re-anchors the local clock to it. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S;

  const T = (HX.T = { playing: false, rec: false, metro: false, anchorBeat: 0, anchorT: 0, stopBeat: 0, lastStop: 0, graceUntil: 0, trim: 0, speed: 1 });
  /* after a command, the engine's next replies may still show the old state for a moment */
  const sent = () => { T.graceUntil = performance.now() + 600; if (HX.liveEngine) HX.liveEngine.kick(); };

  HX.pos = function () {
    if (!T.playing) return T.stopBeat;
    let b = T.anchorBeat + ((performance.now() - T.anchorT) / 1000) * (S.session.tempo / 60) * (T.speed || 1) * (1 + (T.trim || 0)); // speed, trim: live.js follows the engine's clock
    const L = S.session.loop;
    if (L.on && T.anchorBeat < L.end && b >= L.end) {
      b = L.start + ((b - L.start) % (L.end - L.start));
      T.anchorBeat = b; T.anchorT = performance.now();
    }
    if (b >= S.session.lengthBeats) { T.playing = false; T.stopBeat = S.session.lengthBeats; setTimeout(() => HX.emit('transport')); return T.stopBeat; }
    return b;
  };

  /* while an export runs the engine refuses the transport (-32003, live.js): nothing moves here either */
  const busy = () => { if (!HX.mcp.connected || !HX.exportBusy || !HX.exportBusy()) return false; HX.transportBusy(); return true; };
  /* a refused play / stop / locate: say why; the next poll puts the playhead back where the engine has it */
  const refused = (e) => {
    T.graceUntil = 0;
    if (HX.exportRefused(e) && T.playing) { T.stopBeat = HX.pos(); T.playing = false; HX.emit('transport'); }
    else if (!/-32003/.test(e.message)) HX.toast(e.message);
    if (HX.liveEngine) HX.liveEngine.kick();
  };
  HX.play = async function (fromBeat) {
    if (busy()) return;
    if (fromBeat != null) T.stopBeat = fromBeat;
    T.anchorBeat = T.stopBeat; T.anchorT = performance.now(); T.playing = true; T.trim = 0;
    HX.emit('transport');
    if (HX.mcp.connected) { HX.mcp.play().then(sent, refused); T.graceUntil = performance.now() + 2000; }
    else HX.log('mock', 'transport_play {}');
  };
  HX.stop = async function () {
    if (busy()) return;
    if (!T.playing) {
      // second stop returns to the start (Live-style)
      HX.locate(0);
      return;
    }
    T.stopBeat = HX.pos(); T.playing = false; T.lastStop = performance.now();
    Object.keys(S.launched).forEach((k) => delete S.launched[k]);
    HX.emit('transport'); HX.emit('launch');
    if (HX.mcp.connected) { HX.mcp.stop().then(sent, refused); T.graceUntil = performance.now() + 2000; }
    else HX.log('mock', 'transport_stop {}');
  };
  HX.toggle = () => (T.playing ? HX.stop() : HX.play());
  /* the engine is gone (or stopped answering): the view stops where it was, it does not keep playing by itself */
  HX.freezeTransport = function () {
    if (!T.playing) return;
    T.stopBeat = HX.pos(); T.playing = false; T.trim = 0;
    Object.keys(S.launched).forEach((k) => delete S.launched[k]);
    HX.emit('transport'); HX.emit('launch');
  };
  HX.locate = function (beat, quiet) {
    if (!quiet && busy()) return;
    beat = HX.clamp(beat, 0, S.session.lengthBeats);
    T.stopBeat = beat; T.anchorBeat = beat; T.anchorT = performance.now(); T.trim = 0;
    HX.emit('transport');
    const sample = Math.round(HX.beatsToSec(beat) * S.session.sampleRate);
    if (quiet) return;
    if (HX.mcp.connected) { T.graceUntil = performance.now() + 2000; HX.mcp.locate(sample).then(sent, refused); }
    else HX.log('mock', 'transport_locate_sample {"sample":' + sample + '}');
  };
  HX.toggleLoop = function () {
    if (busy()) return;
    S.session.loop.on = !S.session.loop.on;
    HX.emit('transport');
    if (HX.mcp.connected) HX.liveEngine.loop(S.session.loop.on);
    else HX.log('mock', 'transport_loop_toggle ' + JSON.stringify({ enabled: S.session.loop.on }));
  };
  HX.setLoopRange = function (start, end) {
    if (busy()) return;
    if (HX.mcp.connected) {
      const sr = S.session.sampleRate;
      HX.mcp.loopRange(HX.beatsToSec(start) * sr, HX.beatsToSec(end) * sr).then(() => HX.mcp.loopToggle(true)).catch((e) => HX.exportRefused(e));
    } else HX.log('mock', 'transport_loop_location_samples ' + JSON.stringify({ startBeat: start, endBeat: end }));
  };
  HX.toggleRec = function () {
    if (busy()) return;
    T.rec = !T.rec; HX.emit('transport');
    if (HX.mcp.connected) HX.liveEngine.rec(T.rec);
    else HX.log('mock', 'transport_set_record_enable {"enabled":' + T.rec + '}');
  };

  /* engine poll (connected only): live.js */
  HX.startPoll = () => HX.liveEngine.start();

  /* ── frame loop ── */
  const frameFns = [];
  HX.onFrame = (fn) => frameFns.push(fn);
  let lastT = performance.now();
  function frame(now) {
    const dt = Math.min(0.1, (now - lastT) / 1000); lastT = now;
    if (S.session) {
      const t0 = performance.now();
      const beat = HX.pos();
      quantizeLaunches(beat);
      if (HX.liveEngine && HX.liveEngine.on && HX.liveEngine.metersLive) HX.liveEngine.frameMeters(dt, now);
      else simulateMeters(beat, dt, now);
      metronome(beat);
      for (const fn of frameFns) fn(beat, dt, now);
      const ms = performance.now() - t0;
      T.frameMs = T.frameMs == null ? ms : T.frameMs * 0.95 + ms * 0.05; // UI cost per frame (EMA), for the budget check
      T.frameMax = Math.max(T.frameMax || 0, ms);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  /* ── session clip launches, quantized to the next bar ── */
  HX.launch = function (trackId, sceneIdx) {
    const sc = S.scenes[sceneIdx];
    const slot = sc && sc.slots[S.session.tracks.findIndex((t) => t.id === trackId)];
    if (!slot) { delete S.launched[trackId]; HX.emit('launch'); return; }
    if (!T.playing) { S.launched[trackId] = { scene: sceneIdx, clipId: slot.clipId, startBeat: T.stopBeat, len: slot.len }; HX.play(); }
    else S.launched[trackId] = { scene: sceneIdx, clipId: slot.clipId, startBeat: Math.ceil(HX.pos() / 4 + 0.0001) * 4, len: slot.len, queued: true };
    HX.log('mock', 'clip launch ' + JSON.stringify({ track: HX.track(trackId).name, scene: sc.name }) + ' (no MCP tool for cues yet)');
    HX.emit('launch');
  };
  HX.launchScene = function (i) { S.session.tracks.forEach((t) => HX.launch(t.id, i)); };
  HX.stopTrackClip = function (trackId) { delete S.launched[trackId]; HX.emit('launch'); };
  function quantizeLaunches(beat) {
    let changed = false;
    for (const k in S.launched) { const L = S.launched[k]; if (L.queued && beat >= L.startBeat) { L.queued = false; changed = true; } }
    if (changed) HX.emit('launch');
  }

  /* ── simulated levels ── */
  function ampAt(t, beat) {
    const L = S.launched[t.id];
    let c, local;
    if (L && !L.queued) {
      const f = HX.findClip(L.clipId); c = f && f.clip;
      local = c ? (beat - L.startBeat) % L.len : 0;
    } else {
      c = t.clips.find((c) => beat >= c.start && beat < c.start + c.len);
      local = c ? beat - c.start : 0;
    }
    if (!c || c.muted) return 0;
    const g = HX.dbToGain(c.gainDb || 0);
    if (c.kind === 'midi') {
      const on = c.notes.filter((n) => local >= n.t && local < n.t + n.len).length;
      return Math.min(0.75, on * 0.16) * g * (0.9 + Math.random() * 0.1);
    }
    const i = Math.floor(local * (c.pres || HX.PEAK_RES));
    return (c.peaks[i] || 0) * g;
  }
  const releaseDbPerSec = 28;
  function ballistics(m, l, r, dt, now) {
    m.l = l > m.l ? l : Math.max(l, m.l - releaseDbPerSec * dt);
    m.r = r > m.r ? r : Math.max(r, m.r - releaseDbPerSec * dt);
    const pk = Math.max(l, r);
    if (pk >= m.pk || now - m.pkT > 1600) { m.pk = pk > m.pk ? pk : Math.max(pk, m.pk - 18 * dt); if (pk >= m.pk) m.pkT = now; }
    if (pk > 0) { m.clip = true; m.clipT = now; }
  }
  function panLR(db, pan) {
    const a = ((pan + 1) / 2) * (Math.PI / 2);
    return [db + HX.gainToDb(Math.cos(a) * Math.SQRT2), db + HX.gainToDb(Math.sin(a) * Math.SQRT2)];
  }
  function simulateMeters(beat, dt, now) {
    const sess = S.session;
    const anySolo = sess.tracks.some((t) => t.solo);
    let mL = 0, mR = 0, rvIn = 0;
    for (const t of sess.tracks) {
      let l = -120, r = -120;
      if (T.playing && !t.mute && (!anySolo || t.solo)) {
        const a = ampAt(t, beat);
        if (a > 0) {
          const pre = HX.gainToDb(a) + (Math.random() - 0.5) * 1.2;
          [l, r] = panLR(pre + t.faderDb, t.pan);
          const gl = HX.dbToGain(l), gr = HX.dbToGain(r);
          mL += gl * gl; mR += gr * gr;
          t.sends.forEach((s) => { const g = HX.dbToGain(pre + t.faderDb + s.db); rvIn += g * g; });
        }
      }
      ballistics(t.meter, l, r, dt, now);
    }
    for (const rt of sess.returns) {
      rt._tail = Math.max(rvIn, (rt._tail || 0) * Math.exp(-dt * 1.4));
      let l = -120, r = -120;
      if (!rt.mute && rt._tail > 1e-7) { const db = 10 * Math.log10(rt._tail) + 4 + rt.faderDb + (Math.random() - 0.5); l = db; r = db - 0.6; const g = HX.dbToGain(db); mL += g * g; mR += g * g; }
      ballistics(rt.meter, l, r, dt, now);
    }
    const ms = sess.master;
    let l = mL > 0 ? 10 * Math.log10(mL) + ms.faderDb + 3 : -120, r = mR > 0 ? 10 * Math.log10(mR) + ms.faderDb + 3 : -120;
    const lim = ms.devices.find((d) => d.kind === 'limiter' && d.on);
    if (lim) { const gain = lim.params[0].v, ceil = lim.params[1].v; l = Math.min(ceil, l + gain); r = Math.min(ceil, r + gain); }
    ballistics(ms.meter, l, r, dt, now);
  }

  /* IEC-style deflection, 0..1 (same breakpoints as Ardour's log meter) */
  HX.meterPos = function (db) {
    let d;
    if (db < -70) d = 0;
    else if (db < -60) d = (db + 70) * 0.25;
    else if (db < -50) d = (db + 60) * 0.5 + 2.5;
    else if (db < -40) d = (db + 50) * 0.75 + 7.5;
    else if (db < -30) d = (db + 40) * 1.5 + 15;
    else if (db < -20) d = (db + 30) * 2 + 30;
    else d = (db + 20) * 2.5 + 50;
    return HX.clamp(d / 115, 0, 1);
  };
  /* draw a meter only when something about it changed (or its size, or the theme) and it is on screen: at 200 tracks the
     idle page draws nothing. cv carries what was last drawn. */
  let meterEpoch = 0;
  HX.drawMeterIfChanged = function (cv, ctx, w, h, m, opts) {
    if (!HX.isVisible(cv)) return;
    const k = cv._mk || (cv._mk = [NaN, 0, 0, 0, 0, 0, 0, 0]);
    const rl = m.rmsL == null ? -999 : m.rmsL, rr = m.rmsR == null ? -999 : m.rmsR;
    if (cv._ep === meterEpoch && cv._mw === w && cv._mh === h && Math.abs(k[0] - m.l) < 0.05 && Math.abs(k[1] - m.r) < 0.05 && Math.abs(k[2] - m.pk) < 0.05 && Math.abs(k[3] - rl) < 0.05 && Math.abs(k[4] - rr) < 0.05 && k[5] === !!m.clip) return;
    k[0] = m.l; k[1] = m.r; k[2] = m.pk; k[3] = rl; k[4] = rr; k[5] = !!m.clip; cv._ep = meterEpoch; cv._mw = w; cv._mh = h;
    HX.drawMeter(ctx, w, h, m, opts);
  };
  /* vertical stereo meter; w/h in CSS px */
  HX.drawMeter = function (ctx, w, h, m, opts) {
    const C = HX.meterColors || (HX.meterColors = readMeterColors());
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, w, h);
    const gap = 1, bw = (w - gap) / 2;
    const y6 = h * (1 - HX.meterPos(-6)), y18 = h * (1 - HX.meterPos(-18));
    const zones = (x, top, bot) => {
      // three zones, hard edges for contrast
      if (top >= bot) return;
      if (bot > y18) { ctx.fillStyle = C.lo; ctx.fillRect(x, Math.max(top, y18), bw, bot - Math.max(top, y18)); }
      if (top < y18 && bot > y6) { ctx.fillStyle = C.mid; ctx.fillRect(x, Math.max(top, y6), bw, Math.min(bot, y18) - Math.max(top, y6)); }
      if (top < y6) { ctx.fillStyle = C.hi; ctx.fillRect(x, top, bw, Math.min(bot, y6) - top); }
    };
    const rms = m.rmsL != null;
    [m.l, m.r].forEach((db, i) => {
      const x = i * (bw + gap);
      const top = h * (1 - HX.meterPos(db));
      if (top >= h) return;
      if (!rms) return zones(x, top, h);
      // peak as a lighter column above the solid RMS body
      const rtop = Math.max(top, h * (1 - HX.meterPos(i ? m.rmsR : m.rmsL)));
      ctx.globalAlpha = 0.42; zones(x, top, rtop); ctx.globalAlpha = 1;
      zones(x, rtop, h);
    });
    if (m.pk > -70) { const y = Math.round(h * (1 - HX.meterPos(m.pk))); ctx.fillStyle = m.pk > -6 ? C.hi : C.tx; ctx.fillRect(0, y, w, 1); }
    if (!opts || !opts.noTicks) {
      ctx.fillStyle = 'rgba(0,0,0,.55)';
      for (const d of [0, -6, -12, -24, -48]) ctx.fillRect(0, Math.round(h * (1 - HX.meterPos(d))), w, 1);
    }
  };
  function readMeterColors() { return { bg: HX.css('--m-bg'), lo: HX.css('--m-lo'), mid: HX.css('--m-mid'), hi: HX.css('--m-hi'), tx: HX.css('--tx1') }; }
  HX.on('theme', () => { HX.meterColors = null; meterEpoch++; });

  /* metronome: a short WebAudio blip on each beat */
  let actx = null, lastBeatInt = -1;
  function metronome(beat) {
    const bi = Math.floor(beat);
    if (!T.playing || !T.metro) { lastBeatInt = bi; return; }
    if (bi === lastBeatInt) return;
    lastBeatInt = bi;
    try {
      actx = actx || new (window.AudioContext || window.webkitAudioContext)();
      const o = actx.createOscillator(), g = actx.createGain();
      o.frequency.value = bi % 4 === 0 ? 1760 : 1320;
      g.gain.setValueAtTime(0.12, actx.currentTime); g.gain.exponentialRampToValueAtTime(0.0001, actx.currentTime + 0.05);
      o.connect(g).connect(actx.destination); o.start(); o.stop(actx.currentTime + 0.06);
    } catch (e) {}
  }
})();
