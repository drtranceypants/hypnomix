/* HypnoMix · the Session view on the engine: its cue slots (16 per track) over MCP.
   cue_list is polled only while the Session view is open (fast while a clip is queued or playing), never two requests
   out, and read once when the session or the engine changes;
   a click on a slot is cue_launch (it starts on the slot's quantization, the next bar by default, and rolls the
   transport), an empty slot or a stop button cue_stop, a scene scene_launch, a region dragged from the strip under
   the grid (or an audio file from the Finder) cue_set_clip. With the mock session the old local launcher runs. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S;
  const C = (HX.cues = { tracks: {}, rows: 8, sample: 0, rolling: false, at: 0, sig: '', error: '' });
  const mock = { launch: HX.launch, launchScene: HX.launchScene, stopTrackClip: HX.stopTrackClip };

  C.available = () => !!(HX.mcp.connected && HX.mcp.has('cue_list'));
  C.slot = (trackId, n) => { const t = C.tracks[trackId]; return t && t.slots[n]; };
  C.columns = () => S.session.tracks.filter((t) => t.real && (t.kind === 'audio' || t.kind === 'midi') && !t.isMaster && !t.isReturn);

  let inflight = false, timer = 0, failures = 0;
  async function poll() {
    timer = 0;
    if (!C.available()) { C.sig = ''; return; }
    if (inflight) return schedule();
    inflight = true;
    try {
      const r = await HX.mcp.call('cue_list', {}, { quiet: true });
      failures = 0;
      const was = C.error; C.error = '';
      apply(r);
      if (was) HX.emit('cues-error', '');
    } catch (e) {
      if (++failures === 3) HX.log('err', 'cue_list · ' + e.message);
      /* said under the grid at once; the playing slots' bars stop moving (C.fraction), since what plays is not known */
      if (C.error !== e.message) { C.error = e.message; HX.emit('cues-error', e.message); }
    } finally { inflight = false; schedule(); }
  }
  function busy() { return Object.values(C.tracks).some((t) => Object.values(t.slots).some((s) => s.state !== 'stopped' || s.queued)); }
  /* a read that is due sooner is never put off: the transport event comes with every meter frame (about 20 a second),
     and putting the read off each time would starve the poll */
  let due = 0;
  function schedule(ms) {
    const view = S.ui.view === 'session';
    if (ms == null && !view) { if (timer) clearTimeout(timer); timer = 0; return; }   /* another view: no polling (a launch, a session or the view coming back reads again) */
    const wait = ms != null ? ms : !C.available() ? 2000 : busy() ? 150 : 600, at = performance.now() + wait;
    if (timer && due <= at) return;
    if (timer) clearTimeout(timer);
    due = at; timer = setTimeout(poll, wait);
  }
  C.kick = () => schedule(40);

  function apply(r) {
    const tracks = {};
    let maxRow = -1;
    for (const t of (r && r.tracks) || []) {
      const slots = {};
      for (const s of t.slots || []) { slots[s.slot] = s; maxRow = Math.max(maxRow, s.slot); }
      tracks[t.trackId] = { playingSlot: t.playingSlot, slots, name: t.name, dataType: t.dataType };
    }
    C.tracks = tracks; C.sample = r.sample || 0; C.rolling = !!r.rolling; C.sr = r.sampleRate || S.session.sampleRate; C.at = performance.now();
    C.rows = Math.max(8, Math.min(r.scenes || 16, maxRow + 2));
    /* what the grid shows (names, filled slots, rows) vs what only its lights show (states) */
    const sig = C.rows + '|' + Object.keys(tracks).map((id) => id + ':' + Object.values(tracks[id].slots).map((s) => s.slot + '=' + s.name + '/' + s.regionId).join(',')).join(';');
    if (sig !== C.sig) { C.sig = sig; HX.emit('cues-structure'); } else HX.emit('cues');
  }

  async function call(name, args, label) {
    if (HX.exportBusy && HX.exportBusy() && name !== 'cue_list') { HX.transportBusy && HX.transportBusy(); return null; }
    try { const r = await HX.mcp.call(name, args); C.kick(); return r; }
    catch (e) { if (!(HX.exportRefused && HX.exportRefused(e))) HX.toast((label || name) + ': ' + e.message, 3600); C.kick(); return null; }
  }

  HX.launch = function (trackId, n) {
    if (!C.available()) return mock.launch(trackId, n);
    if (!C.slot(trackId, n)) return HX.stopTrackClip(trackId);
    return call('cue_launch', { track_id: trackId, slot: n }, 'Launch');
  };
  HX.launchScene = function (n) {
    if (!C.available()) return mock.launchScene(n);
    return call('scene_launch', { scene: n }, 'Scene');
  };
  HX.stopTrackClip = function (trackId) {
    if (!C.available()) return mock.stopTrackClip(trackId);
    return call('cue_stop', { track_id: trackId }, 'Stop');
  };
  HX.stopAllClips = function () {
    if (!C.available()) return Object.keys(S.launched).forEach(mock.stopTrackClip);
    return call('cue_stop', {}, 'Stop all');
  };

  /* src: {regionId} | {file} | {clear:true}. The engine answers when the clip is in the slot (it loads it first). */
  HX.cueSetClip = async function (trackId, n, src) {
    if (!C.available()) throw new Error('clips go into slots on the engine (connect first)');
    if (HX.editBlocked && HX.editBlocked()) throw new Error(HX.editBlocked());
    const args = Object.assign({ track_id: trackId, slot: n }, src.regionId ? { region_id: src.regionId } : src.file ? { file: src.file } : { clear: true });
    const M = HX.mcp;
    if (!M._longCalls) M._baseTimeout = M.timeoutMs;
    M._longCalls = (M._longCalls || 0) + 1; M.timeoutMs = 90000;
    try { return await M.call('cue_set_clip', args); }
    finally { if (--M._longCalls === 0) M.timeoutMs = M._baseTimeout; C.kick(); }
  };

  /* a drop on a slot: a region from the strip (application/x-hx-region) or audio files from the Finder */
  HX.cueDrop = async function (trackId, n, e) {
    const rid = e.dataTransfer.getData('application/x-hx-region');
    const t = HX.track(trackId);
    try {
      if (rid) {
        HX.toast('Putting the clip into ' + t.name + ' · slot ' + (n + 1) + '…', 3000);
        await HX.cueSetClip(trackId, n, { regionId: rid });
      } else if (e.dataTransfer.files && e.dataTransfer.files.length) {
        const f = e.dataTransfer.files[0];
        const up = await HX.uploadForImport(f, (p) => HX.toast('Sending ' + f.name + ' to the app · ' + Math.round(p * 100) + '%', 3000));
        HX.toast('Loading ' + f.name + ' into slot ' + (n + 1) + '…', 3000);
        await HX.cueSetClip(trackId, n, { file: up.path });
      } else return;
      HX.toast('In ' + t.name + ' · slot ' + (n + 1) + ': click it to launch (on the next bar)', 2600);
    } catch (err) { HX.toast('Not put into the slot: ' + err.message, 4200); }
  };
  /* a region put into a slot by keyboard (a picked chip, then Enter on the slot): the same call and words as a drop */
  HX.cuePut = async function (trackId, n, regionId) {
    const t = HX.track(trackId);
    try {
      HX.toast('Putting the clip into ' + t.name + ' · slot ' + (n + 1) + '…', 3000);
      await HX.cueSetClip(trackId, n, { regionId });
      HX.toast('In ' + t.name + ' · slot ' + (n + 1) + ': Enter launches it (on the next bar)', 2600);
    } catch (err) { HX.toast('Not put into the slot: ' + err.message, 4200); }
  };
  HX.cueClear = async function (trackId, n) {
    try { await HX.cueSetClip(trackId, n, { clear: true }); } catch (err) { HX.toast('Not cleared: ' + err.message, 3600); }
  };

  /* where a playing clip is, between polls: the engine's fraction, moved on by the wall clock */
  C.fraction = function (s) {
    if (s.positionFraction == null || !s.lengthSeconds) return null;
    const run = !C.error && C.rolling && (s.state === 'running' || s.state === 'waiting_to_stop' || s.state === 'waiting_to_switch');
    const f = s.positionFraction + (run ? (performance.now() - C.at) / 1000 / s.lengthSeconds : 0);
    return f - Math.floor(f);
  };

  HX.on('view', () => schedule(S.ui.view === 'session' ? 0 : null));
  HX.on('session', () => { C.sig = ''; schedule(0); });
  HX.on('live', () => schedule(0));
  /* play / stop: read soon (the slots follow the transport); only when it changes, and only where the grid shows */
  let wasPlaying = null, kickedAt = -1e9;
  HX.on('transport', () => {
    const p = !!(HX.T && HX.T.playing); if (p === wasPlaying) return;
    wasPlaying = p;
    if (!C.available() || S.ui.view !== 'session' || performance.now() - kickedAt < 500) return;   /* at most twice a second */
    kickedAt = performance.now(); schedule(80);
  });
  schedule(500);
})();
