/* Hypnomix · wiring: views, theme, transport bar, keyboard, info line, Connect. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h, T = HX.T;
  const app = HX.$('#app');

  /* ── info line (Live's Info View): whatever is under the pointer explains itself ── */
  HX.info = (txt) => { const el = HX.$('#infoLine'); if (el.textContent !== txt) el.textContent = txt; };
  document.addEventListener('mouseover', (e) => { const el = e.target.closest('[data-info]'); if (el) HX.info(el.dataset.info); });

  /* ── views ── */
  HX.setView = function (v) {
    S.ui.view = v; app.dataset.view = v;
    HX.$$('#viewTabs button').forEach((b) => b.classList.toggle('on', b.dataset.view === v));
    try { localStorage.setItem('hx.view', v); } catch (e) {}
    HX.emit('view', v);
  };
  HX.$$('#viewTabs button').forEach((b) => b.addEventListener('click', () => HX.setView(b.dataset.view)));

  /* ── theme ── */
  HX.toggleTheme = function (force) {
    const t = force || (document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    document.documentElement.dataset.theme = t; S.ui.theme = t;
    try { localStorage.setItem('hx.theme', t); } catch (e) {}
    HX.emit('theme');
  };
  HX.$('#btnTheme').addEventListener('click', () => HX.toggleTheme());

  /* ── transport bar ── */
  HX.$('#btnPlay').addEventListener('click', () => HX.toggle());
  HX.$('#btnStop').addEventListener('click', () => HX.stop());
  HX.$('#btnStart').addEventListener('click', () => HX.locate(0));
  HX.$('#btnRec').addEventListener('click', () => HX.toggleRec());
  HX.$('#btnLoop').addEventListener('click', () => HX.toggleLoop());
  HX.toggleMetro = () => { T.metro = !T.metro; HX.emit('transport'); HX.toast('Metronome ' + (T.metro ? 'on' : 'off')); };
  HX.$('#btnMetro').addEventListener('click', HX.toggleMetro);
  const syncTransport = () => {
    HX.$('#btnPlay').classList.toggle('on', T.playing);
    HX.$('#btnRec').classList.toggle('on', T.rec);
    HX.$('#btnLoop').classList.toggle('on', S.session.loop.on);
    HX.$('#btnMetro').classList.toggle('on', T.metro);
  };
  HX.on('transport', syncTransport);
  /* an export holds the engine's transport (live.js): the buttons are disabled and say why */
  const TBTN = ['#btnPlay', '#btnStop', '#btnStart', '#btnRec', '#btnLoop'];
  HX.on('exporting', (x) => {
    const tr = HX.$('#transport');
    tr.classList.toggle('exporting', !!x);
    TBTN.forEach((id) => { const b = HX.$(id); b.disabled = !!x; });
    let note = HX.$('#exportNote');
    if (x) {
      if (!note) { note = HX.h('span.export-note#exportNote'); HX.$('#btnLoop').after(note); }
      const pc = Math.round((x.progress || 0) * 100);
      note.textContent = 'Exporting ' + pc + ' %';
      note.dataset.info = 'An export is running in the engine (' + x.jobId + '): it refuses play, stop, locate, loop and record until the bounce is done, so the bounce cannot be cut short';
    } else if (note) note.remove();
  });
  const tempoEl = HX.$('#tempo');
  let tempoBefore = 0;
  HX.dragY(tempoEl.parentElement, () => {
    tempoBefore = S.session.tempo;
    /* the engine's tempo is read from the engine (session_get_info): its MCP tools have none that sets it, so the field only shows it there */
    if (HX.mcp.connected) HX.toast('The engine has no tempo control for this page yet: change the tempo in the engine itself', 4200);
  }, (dy, fine) => {
    if (HX.mcp.connected) return;
    const beat = HX.pos();
    S.session.tempo = HX.clamp(Math.round((S.session.tempo + dy * (fine ? 0.01 : 0.25)) * 100) / 100, 40, 240);
    if (T.playing) { T.anchorBeat = beat; T.anchorT = performance.now(); }
    tempoEl.textContent = S.session.tempo.toFixed(2);
  }, () => { if (!HX.mcp.connected && S.session.tempo !== tempoBefore) HX.log('mock', 'tempo ' + S.session.tempo + ' (the demo song: nothing is sent)'); });

  const bbtEl = HX.$('#posBBT'), timeEl = HX.$('#posTime'), cpu = HX.$('#cpuBar');
  let cpuV = 4, lastCpu = 0;
  HX.onFrame((beat, dt, now) => {
    const b = HX.bbtStr(beat); if (bbtEl.textContent !== b) bbtEl.textContent = b;
    const t = HX.timeStr(HX.beatsToSec(beat)); if (timeEl.textContent !== t) timeEl.textContent = t;
    if (HX.mcp.connected) { /* the engine does not report its DSP load over MCP yet: show nothing rather than a guess */
      if (lastCpu !== -1) { lastCpu = -1; cpu.style.width = '0%'; cpu.parentElement.parentElement.dataset.info = 'Engine DSP load: not reported by the engine yet'; }
    } else if (now - lastCpu > 500) {
      lastCpu = now; cpuV = HX.clamp(cpuV + (Math.random() - 0.5) * 4 + ((T.playing ? 14 : 3) - cpuV) * 0.3, 1, 60);
      cpu.style.width = cpuV.toFixed(0) + '%'; cpu.parentElement.parentElement.dataset.info = 'Engine DSP load ' + cpuV.toFixed(0) + '% (mocked)';
    }
  });
  HX.on('select', () => {
    const t = HX.track(S.ui.trackId), c = S.ui.clipId && HX.findClip(S.ui.clipId);
    HX.$('#selStatus').textContent = (t ? t.name : '') + (c ? ' › ' + c.clip.name : '');
  });
  HX.on('history', () => { const l = S.history[S.history.length - 1]; HX.$('#selStatus').textContent = l ? 'Last: ' + l.label : ''; });

  /* ── unsaved work: the app keeps the true count (GET /api/daw/state "dirty", set by any change that reached the engine,
     from this page or the Assistant; cleared by a save); this page shows it at once and asks before anything loses it ── */
  HX.dirty = false;
  let dirtyAt = 0, saving = false, markT = 0;
  const btnSave = HX.$('#btnSave');
  function syncSave() {
    const on = HX.mcp.connected, dirty = on && HX.dirty;
    btnSave.disabled = !on || saving;
    btnSave.classList.toggle('dirty', dirty);
    btnSave.setAttribute('aria-label', dirty ? 'Save (there are unsaved changes)' : 'Save');
    btnSave.dataset.info = !on ? 'Save needs a session open in the engine' : dirty ? 'Save the session: it has changes that are not saved · ⌘S' : 'Save the session · ⌘S (nothing has changed since the last save)';
    HX.$('#sessionName').classList.toggle('dirty', dirty);
    document.title = (dirty ? '● ' : '') + 'HypnoMix DAW';
  }
  /* a change reached the engine (mcp.js calls this): show "unsaved" now, and ask the app for its count soon */
  HX.markDirty = function () {
    if (!HX.mcp.connected) return;
    HX.dirty = true; dirtyAt = performance.now(); syncSave();
    clearTimeout(markT); markT = setTimeout(() => watchEngine(), 500);
  };
  HX.hasUnsaved = () => !!(HX.mcp.connected && HX.dirty);
  /* Save: through the app (POST /api/daw/save → the engine's session_save). Resolves true when it was saved. */
  HX.saveSession = async function () {
    if (!HX.mcp.connected) { HX.toast('Nothing to save: no session is open in the engine'); return false; }
    if (saving) return false;
    saving = true; syncSave();
    try {
      if (HX.endAuditions) await HX.endAuditions('saving');       /* a tried value (Hear it) is put back first: it is never written into the file */
      if (HX.api.inApp) await HX.api.post('/api/daw/save', {}); else await HX.mcp.save();
      HX.dirty = false; dirtyAt = performance.now();
      HX.toast('Saved ' + S.session.name);
      HX.emit('saved');
      return true;
    } catch (e) {
      HX.toast('Not saved: ' + e.message, 5000); HX.log('err', 'save · ' + e.message);
      return false;
    } finally { saving = false; syncSave(); setTimeout(() => watchEngine(), 300); }
  };
  HX.on('live', syncSave);
  btnSave.addEventListener('click', () => HX.saveSession());
  /* Save / Don't save / Cancel, before anything that would lose what is not saved. `what` finishes the sentence "It has
     changes that are not saved. …". Resolves {} when there is nothing to lose (or `force` is not needed), { save: true },
     { discard: true }, or null when the person cancelled. Focus starts on Save. */
  HX.askUnsaved = async function (what, force) {
    if (!force && !HX.hasUnsaved()) return {};
    const v = await HX.dialog({
      title: 'Save “' + S.session.name + '” first?', cancel: null,
      body: ['It has changes that are not saved.', what || ''].filter(Boolean),
      buttons: [{ label: 'Don’t save', value: 'discard', kind: 'danger' }, { label: 'Cancel', value: null }, { label: 'Save', value: 'save', kind: 'primary', focus: true }],
    });
    return v === 'save' ? { save: true } : v === 'discard' ? { discard: true } : null;
  };
  /* POST to a route that would close the open session (stop, restart, open, new): asks first when there are unsaved
     changes, sends "save" or "discard" as the person chose, and asks again when the app answers 409 "unsaved" (it knows
     of changes this page did not: the Assistant, another client). Resolves the app's answer, or null when cancelled.
     opts.before() runs just before each send; opts.after(answer) runs after a good answer. */
  HX.guardedPost = async function (url, body, what, opts) {
    opts = opts || {};
    let g = await HX.askUnsaved(what);
    for (let tries = 0; ; tries++) {
      if (g === null) return null;
      try {
        opts.before && opts.before();
        const st = await HX.api.post(url, Object.assign({}, body, g));
        if (g.save || g.discard) { HX.dirty = false; dirtyAt = performance.now(); }
        opts.after && opts.after(st);
        return st;
      } catch (e) {
        if (e.status !== 409 || !e.body || e.body.error !== 'unsaved' || tries > 0) throw e;
        HX.dirty = true; dirtyAt = performance.now(); syncSave();
        g = await HX.askUnsaved(what, true);
      }
    }
  };
  /* going to another page of the app (Songs, Assistant, Wiki, Store): the engine keeps running, but what is not saved is
     only in the engine until it is saved */
  HX.leavePage = async function (href) {
    if (HX.hasUnsaved()) {
      const g = await HX.askUnsaved('The engine keeps running if you leave this page, but nothing is saved until you save.');
      if (g === null) return;
      if (g.save && !(await HX.saveSession())) return;
    }
    HX.leaving = true;
    location.href = href;
  };
  /* for the Mac app's Quit and the updater: true when it is fine to go on (saved, or the person chose not to save) */
  HX.confirmLeave = async function () {
    const g = await HX.askUnsaved('Quitting stops the engine.');
    if (g === null) return false;
    if (g.save) return HX.saveSession();
    return true;
  };
  window.addEventListener('beforeunload', (e) => { if (!HX.leaving && HX.hasUnsaved()) { e.preventDefault(); e.returnValue = ''; } });
  HX.$('#appNav').addEventListener('click', (e) => {
    const a = e.target.closest('a[href]'); if (!a) return;
    e.preventDefault(); HX.leavePage(a.getAttribute('href'));
  });

  /* ── Connect ── */
  const btnC = HX.$('#btnConnect');
  let pop = null;
  /* what the page shows: 'noengine' (nothing to drive: it says so and what to do), 'engine' (a session of the engine) or
     'demo' (the made-up practice song, only by choice, labelled) */
  HX.mode = 'noengine';
  HX.noEngineScreen = () => HX.mode === 'noengine';
  const idleLabel = () => (HX.mode === 'demo' ? 'Demo' : 'No engine');
  function setMode(m) {
    HX.mode = m; app.dataset.mode = m;
    HX.$('#demoBadge').hidden = m !== 'demo';
    HX.$('#noEngine').hidden = m !== 'noengine';
    ['#browser', '#main', '#devices', '#assistant', '#transport', '#viewTabs'].forEach((s) => { const el = HX.$(s); if (el) el.toggleAttribute('inert', m === 'noengine'); });
    syncSave();
    HX.emit('mode', m);                            // 'noengine' | 'demo' | 'engine' (the guided tours wait for a session)
  }
  function setConn(state, label) {
    btnC.classList.remove('on', 'busy', 'err'); if (state) btnC.classList.add(state);
    HX.$('#connectLabel').textContent = label;
    const es = HX.$('#engineStatus');
    es.classList.toggle('on', state === 'on');
    es.textContent = state === 'on' ? 'MCP · ' + (HX.mcp.serverInfo ? HX.mcp.serverInfo.name + ' ' + HX.mcp.serverInfo.version : 'engine') + ' · ' + HX.mcp.tools.length + ' tools · ' + S.session.sampleRate / 1000 + ' kHz · ' + (HX.liveEngine.metersLive ? 'meters live' : 'meters simulated (no meters_get)')
      : HX.mode === 'demo' ? 'Demo song · made up: it plays no sound, saves nothing and sends nothing to an engine'
      : HX.mode === 'noengine' ? (HX.api.inApp ? 'No engine connected' : 'Opened outside the HypnoMix app: only the demo song')
      : es.textContent;
    const tf = HX.$('#tempo').parentElement;
    tf.classList.toggle('locked', !!HX.mcp.connected);
    tf.dataset.info = HX.mcp.connected ? 'Tempo, read from the engine · the engine has no tempo control for this page yet' : 'Tempo · drag up/down, shift for fine';
    syncSave();
  }
  function closePop() { if (pop) { pop.remove(); pop = null; } }
  const mkBtn = (label, cls, fn) => h('button.btn' + (cls ? '.' + cls : ''), { type: 'button', onclick: fn }, label);
  /* the no-engine screen: what is missing, and the ways on (look again, start the engine, the demo song by choice) */
  let noEngSig = '';
  function renderNoEngine(st) {
    const sig = st ? [!!st.binary, st.state, st.error, !!st.connected, JSON.stringify(st.addon || {})].join('|') : 'looking';
    if (sig === noEngSig) return;
    noEngSig = sig;
    const title = HX.$('#noEngineTitle'), body = HX.$('#noEngineBody'), err = HX.$('#noEngineErr'), btns = HX.$('#noEngineBtns');
    if (!st) { title.textContent = 'Looking for the engine…'; body.textContent = ''; err.textContent = ''; btns.replaceChildren(); return; }
    const demo = mkBtn('Practice with the demo song', '', () => HX.enterDemo());
    const again = mkBtn('Look again', '', async () => { noEngSig = ''; await watchEngine(); HX.toast('Looked again'); });
    if (st.binary) {
      title.textContent = 'The engine is not running';
      body.textContent = 'The DAW view shows and edits what the HypnoMix DAW engine has open: it plays, records and saves nothing by itself. Start the engine, then open or make a session. The demo song is made up: it plays no sound, saves nothing and sends nothing.';
      btns.replaceChildren(mkBtn('Start the engine', 'primary', () => startAgain()), again, demo);
    } else {
      title.textContent = 'There is no engine on this computer';
      const ad = st.addon || {};
      body.textContent = 'The DAW view drives the HypnoMix DAW engine, a separate audio program (under the GNU General Public License) that is not part of the app: it is added from Setup, only when you choose to. '
        + (ad.available ? 'It is ready to add: press Add HypnoMix DAW (about 100 MB, fetched once and checked against a fingerprint), or use Setup → Extras. ' : 'HypnoMix DAW is not available yet, so there is nothing here to play, edit or save. ')
        + 'If you run an engine in a window of its own, switch on Preferences → Control Surfaces → MCPHttp there and press Look again. The demo song is made up: it plays no sound, saves nothing and sends nothing.';
      const add = ad.available ? mkBtn('Add HypnoMix DAW', 'primary', async () => {
        try { await HX.api.post('/api/setup/engine/install', {}); HX.toast('Adding HypnoMix DAW: the progress is in Setup → Extras', 6000); }
        catch (e) { HX.toast(e.message, 6000); }
      }) : null;
      btns.replaceChildren(...[add, again, demo].filter(Boolean));
    }
    err.textContent = st.error || '';
  }
  /* the demo song, by explicit choice (never in place of a connected session) */
  HX.enterDemo = function () {
    if (HX.mcp.connected) return;
    HX.userMock = true; HX.engineLost = false; HX.dirty = false;
    HX.loadMock(); setMode('demo'); setConn(null, idleLabel());
    HX.$('#sessionName').textContent = S.session.name;
    HX.toast('The demo song: made up, plays no sound, saves nothing', 3600);
  };
  /* the engine session is left (stopped, or the person went to the demo): the page drops it and says there is no engine */
  function leaveEngine(toDemo) {
    HX.mcp.disconnect(); HX.engineLost = false; HX.dirty = false;
    HX.loadMock();
    if (toDemo) { HX.userMock = true; setMode('demo'); } else { HX.userMock = false; noEngSig = ''; setMode('noengine'); renderNoEngine(HX.engineState); }
    setConn(null, idleLabel());
    HX.$('#sessionName').textContent = S.session.name;
  }
  /* Connected: the page reads the session and drives the engine through the app (POST /mcp). */
  async function connectNow() {
    setConn('busy', 'Connecting…');
    await HX.mcp.connect();
    await HX.loadFromEngine();
    HX.userMock = false; HX.dirty = false; dirtyAt = performance.now();
    setMode('engine');
    setConn('on', 'Engine'); HX.startPoll();
    HX.$('#sessionName').textContent = S.session.name;
    HX.toast('Connected to ' + S.session.name);
    setTimeout(() => watchEngine(), 300);          // the app's own count of unsaved changes
  }
  HX.connectEngine = connectNow;
  const engLine = (st) => !st ? '' : ({ running: 'Engine running', attached: 'Attached to a HypnoMix DAW window', starting: 'Engine starting…',
    crashed: 'Engine stopped: starting it again', exited: 'Engine stopped unexpectedly', failed: 'Engine failed', stopped: 'Engine stopped' }[st.state] || st.state)
    + (st.session ? ' · ' + st.session.split('/').pop() : '') + (st.pid ? ' · pid ' + st.pid : '') + (st.url ? '\n' + st.url : '')
    + (st.backend ? '\nbackend: ' + st.backend : '') + (st.error ? '\n' + st.error : '') + (st.notice ? '\n' + st.notice : '');
  /* the engine ended without the app asking (or failed): the session stays on screen, never the demo song; Start opens it again */
  function engineLost(st) {
    HX.engineLost = true;
    HX.freezeTransport();                         // no engine, no playing: the clock stops where it was
    HX.mcp.disconnect();
    setConn('err', 'Start');
    HX.$('#engineStatus').textContent = 'Engine stopped unexpectedly · ' + S.session.name + ' stays on screen (edits wait): press Start to open it again';
    HX.toast('The engine stopped unexpectedly: press Start (top right) to open the session again. Changes you had not saved may be lost with it, and the undo history is dropped when the session is read again.', 8000);
    HX.log('err', 'engine · ' + ((st && st.error) || 'stopped unexpectedly'));
  }
  HX.engineLostShown = engineLost;
  async function startAgain() {
    setConn('busy', 'Starting…');
    try {
      const st = await HX.api.post('/api/daw/start', {});
      if (!st.connected) throw new Error(st.error || ('the engine is ' + st.state));
      HX.engineLost = false;
      await connectNow();
    } catch (e) { setConn('err', HX.engineLost ? 'Start' : idleLabel()); HX.toast('Could not start the engine: ' + e.message, 5000); }
  }
  HX.startAgain = startAgain;
  /* "~/Music/New Song" -> { folder: "~/Music", name: "New Song" }; a bare name ("Song") is a folder of the app's own choice
     (".") and "/Song" is the root: slicing at an index of -1 or 0 must not cut the name or lose the slash */
  HX.splitNewPath = function (text) {
    const v = String(text || '').trim().replace(/\/+$/, ''), i = v.lastIndexOf('/');
    return i < 0 ? { folder: '.', name: v } : { folder: i === 0 ? '/' : v.slice(0, i), name: v.slice(i + 1) };
  };
  /* another DAW's project (.als, .logicx, .ptx, .dawproject, .rpp, .aaf) -> a NEW session beside it, then open
     it (asked first, like Open). The server runs it as a job (POST /api/daw/import, then GET ?job=); the project is
     only read. `allowOutside`: also copy audio the project points to outside its folder (left out by default).
     Resolves to the new session's path, or null. */
  HX.importProject = async function (path, allowOutside) {
    path = String(path || '').trim();
    if (!path) throw new Error('type or choose the project to import');
    const name = path.replace(/\/+$/, '').split('/').pop();
    const job = await HX.api.post('/api/daw/import', { path, allow_outside: !!allowOutside });
    HX.toast('Importing ' + name + '… (the project is only read)', 6000);
    let st = job;
    for (let i = 0; st.state === 'running' && i < 7200; i++) {
      await new Promise((ok) => setTimeout(ok, 1500));
      st = await HX.api.get('/api/daw/import?job=' + encodeURIComponent(job.job));
    }
    if (st.state !== 'done') throw new Error(st.error || ('the import is ' + st.state));
    HX.log('mcp', 'import · ' + st.summary);
    const open = await HX.dialog({ title: 'Imported ' + name, cancel: false,
      body: [st.summary + '.', 'The new session is ' + st.session + '. What was left out or changed, and what the file type could not carry (plug-ins, instruments, automation…), is listed in IMPORT-REPORT.md beside it.'],
      buttons: [{ label: 'Not now', value: false }, { label: 'Open it', value: true, focus: true }] });
    if (!open) return st.session;
    if (HX.api.inApp && HX.menuSession) await HX.menuSession({ op: 'open', path: st.session });
    return st.session;
  };
  /* the Mac app's File → New Session… / Open Session… / Import Project… (Hypnomix.swift calls this with what its file panel chose) */
  HX.menuSession = async function (req) {
    if (req && req.op === 'import') {
      try { await HX.importProject(req.path, req.allow_outside === '1'); } catch (e) { HX.toast('Could not import: ' + e.message, 8000); HX.log('err', 'import · ' + e.message); }
      return;
    }
    if (!HX.api.inApp || !req || (req.op !== 'open' && req.op !== 'new')) return;
    const isNew = req.op === 'new';
    const what = isNew ? 'make the new session ' + req.name : 'open ' + String(req.path || '').split('/').filter(Boolean).pop();
    try {
      const st = await HX.guardedPost(isNew ? '/api/daw/new' : '/api/daw/open', isNew ? { folder: req.folder, name: req.name } : { path: req.path },
        'To ' + what + ', the engine closes ' + S.session.name + '.',
        { before: () => { watchEngine.busy = true; setConn('busy', isNew ? 'Making…' : 'Opening…'); } });
      if (st == null) return;                     // cancelled: nothing was touched
      if (!st.connected) throw new Error(st.error || ('the engine is ' + st.state));
      HX.mcp.disconnect();
      HX.engineLost = false; HX.userMock = false;
      await connectNow();
      watchEngine.pid = st.pid;
      if (st.notice) HX.toast(st.notice, 9000);
    } catch (e) {
      const now = await HX.api.get('/api/daw/state').catch(() => null);
      if (now && now.connected && HX.mcp.connected) setConn('on', 'Engine');   /* refused before the engine was touched */
      else if (HX.mcp.connected) { HX.mcp.disconnect(); setConn('err', 'Start'); HX.engineLost = true; }
      else setConn(null, idleLabel());
      HX.toast('Could not ' + what + ': ' + e.message, 6000); HX.log('err', 'session · ' + e.message);
    } finally { watchEngine.busy = false; }
  };
  /* from the engine's session to the demo song: asked first (nothing is closed in the engine; the page stops showing it and stops its transport) */
  async function showDemoInstead() {
    closePop();
    const yes = await HX.dialog({ title: 'Show the demo song instead?', cancel: false,
      body: ['This page will stop showing “' + S.session.name + '”. The engine keeps it open, with nothing closed or lost; the page stops the engine’s transport first.', 'The demo song is made up: it plays no sound and saves nothing.'],
      buttons: [{ label: 'Cancel', value: false, focus: true }, { label: 'Show the demo song', value: true }] });
    if (!yes) return;
    try { await HX.mcp.stop(); } catch (e) {}
    leaveEngine(true);
    HX.toast('Showing the demo song: Connect (top right) brings the engine’s session back');
  }
  /* the engine panel: Stop, Restart, Open and New close the open session, so they ask about unsaved changes first */
  async function stopEngine() {
    try {
      return await HX.guardedPost('/api/daw/stop', {}, 'Stopping the engine closes the open session.',
        { before: () => { watchEngine.busy = true; }, after: () => leaveEngine(false) });
    } finally { watchEngine.busy = false; }
  }
  btnC.addEventListener('click', async () => {
    if (HX.engineLost && HX.api.inApp) return startAgain();
    closePop();
    const connected = HX.mcp.connected;
    const r = btnC.getBoundingClientRect();
    const err = h('p.err');
    const stEl = h('pre.eng', null, HX.api.inApp ? 'Asking the app…' : 'Opened outside the HypnoMix app: only the demo song.');
    const go = h('button.btn.primary', { type: 'button' }, 'Connect');
    const sess = h('input', { placeholder: '/path/to/Song/Song.ardour (or a project to import)', spellcheck: 'false', 'aria-label': 'Session or project path' });
    const btn = (label, fn, info) => h('button.btn', { type: 'button', onclick: () => act(fn), 'data-info': info }, label);
    const act = async (fn) => {
      err.textContent = '';
      try { const st = await fn(); if (st == null) return; stEl.textContent = engLine(st); if (st && st.connected) await attempt(); }
      catch (e) { err.textContent = e.message; }
    };
    const outside = h('input', { type: 'checkbox', 'aria-label': 'Also copy audio from outside the project' });
    const outsideRow = HX.api.inApp ? h('label.row.left', { title: 'Import: also copy audio the project points to outside its own folder (left out and listed in the report otherwise)' },
      outside, ' Import: also copy audio from outside the project') : null;
    const ctl = HX.api.inApp ? h('div.row.left', null,
      btn('Start', () => HX.api.post('/api/daw/start', {}).then((st) => { if (st.connected) HX.engineLost = false; return st; }), 'Start the HypnoMix DAW engine (or use a HypnoMix DAW window that is already running)'),
      btn('Restart', () => HX.guardedPost('/api/daw/restart', {}, 'Restarting the engine closes the open session; it opens again from its saved file.'), 'Stop the engine and start it again on the same session'),
      btn('Stop', stopEngine, 'Stop the engine the app started (a HypnoMix DAW window is only let go of)'),
      btn('Open', () => HX.guardedPost('/api/daw/open', { path: sess.value.trim() }, 'Opening another session closes this one.'), 'Open this session in the engine'),
      btn('New', () => { const f = HX.splitNewPath(sess.value); return HX.guardedPost('/api/daw/new', f, 'Making a new session closes this one.'); }, 'Make a new session: type the folder and the new name, e.g. ~/Music/New Song'),
      btn('Import', () => { const ao = outside.checked; closePop(); HX.importProject(sess.value, ao).catch((e) => HX.toast('Could not import: ' + e.message, 8000)); return null; }, 'Import a project from another DAW (.als, .logicx, .dawproject, .rpp; .ptx and .aaf with the HypnoMix DAW add-on) as a new session beside it, or beside its folder')) : null;
    pop = h('div.connect-pop', { role: 'dialog', 'aria-label': 'The HypnoMix DAW engine', style: { top: r.bottom + 6 + 'px', right: (innerWidth - r.right) + 'px' } },
      h('b', { style: { color: 'var(--tx0)' } }, 'The HypnoMix DAW engine'),
      h('p', null, 'The app runs the engine and passes this page’s calls to it (POST /mcp). Without the engine program, it uses a HypnoMix DAW window that is already open with Preferences → Control Surfaces → MCPHttp on.'),
      stEl, HX.api.inApp ? sess : null, ctl, outsideRow, err,
      h('div.row', null, h('button.btn', { type: 'button', onclick: closePop }, 'Close'),
        connected ? h('button.btn', { type: 'button', onclick: showDemoInstead, 'data-info': 'Leave the engine’s session and show the made-up demo song (asks first)' }, 'Show the demo song') : null,
        connected ? null : go));
    document.body.append(pop);
    const attempt = async () => {
      err.textContent = '';
      try { await connectNow(); closePop(); }
      catch (e) { HX.mcp.disconnect(); setConn('err', idleLabel()); err.textContent = e.message; HX.log('err', 'connect · ' + e.message); }
    };
    go.addEventListener('click', attempt);
    sess.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Escape') closePop(); });
    if (HX.api.inApp) HX.api.get('/api/daw/state').then((st) => { stEl.textContent = engLine(st); }).catch((e) => { stEl.textContent = e.message; });
  });
  /* in the app: connect by itself once the engine is up (unless you chose the demo), and say when it goes */
  async function watchEngine() {
    if (!HX.api.inApp) return;
    const t0 = performance.now();
    try {
      const st = await HX.api.get('/api/daw/state');
      HX.engineState = st;
      if (st.addon && st.addon.needs_update && !watchEngine.toldUpdate) {      /* a newer engine is wanted by this version of the app */
        watchEngine.toldUpdate = true;
        HX.toast(st.addon.message + ' Setup → Extras has the button.', 12000);
      }
      if (typeof st.dirty === 'boolean' && t0 > dirtyAt && HX.mcp.connected) { HX.dirty = st.dirty; syncSave(); }   // the app's count, unless an edit was made since this was asked
      if (watchEngine.busy) return;           /* a connect (or File → Open / New Session) is under way */
      if (HX.mode === 'noengine') renderNoEngine(st);
      if (!st.connected && st.state === 'stopped' && /no session is open yet/.test(st.error || '') && !watchEngine.toldNoSession) {
        watchEngine.toldNoSession = true;     /* the first start with the engine: nothing to open yet */
        HX.toast('No session open yet: File → New Session… or Open Session… (or Engine, top right)', 8000);
      }
      if (HX.reopening) { watchEngine.pid = null; return; }   /* Review is opening a new snapshot: it reconnects by itself */
      if (st.connected && !HX.mcp.connected && !HX.userMock && !watchEngine.busy) {
        HX.engineLost = false;
        watchEngine.busy = true;
        try { await connectNow(); watchEngine.pid = st.pid; if (st.notice && watchEngine.said !== st.notice) { watchEngine.said = st.notice; HX.toast(st.notice, 9000); } } catch (e) { HX.mcp.disconnect(); setConn('err', idleLabel()); HX.log('err', 'connect · ' + e.message); }
        watchEngine.busy = false;
      }
      if (st.connected && HX.mcp.connected && watchEngine.pid && st.pid !== watchEngine.pid) {
        /* the engine was started again (after a crash, or Restart): it reopened the saved session, so read it again */
        try { await HX.loadFromEngine(); HX.dirty = false; dirtyAt = performance.now(); syncSave(); HX.toast('The engine was started again: the session was read again', 3600); } catch (e) { HX.log('err', 'reload · ' + e.message); }
      }
      if (st.connected) watchEngine.pid = st.pid;   // kept while it restarts ("starting"), so the new pid is noticed
      if (!st.connected && HX.mcp.connected && st.state !== 'crashed' && st.state !== 'starting') {
        watchEngine.pid = null;
        engineLost(st);                       /* stopped by itself (or failed): keep the session, offer Start */
      }
      HX.emit('engine-app', st);
    } catch (e) { if (HX.mode === 'noengine') renderNoEngine({ state: 'stopped', binary: null, error: 'The HypnoMix app did not answer: ' + e.message }); }
  }
  setInterval(watchEngine, 3000);
  setTimeout(watchEngine, 300);
  document.addEventListener('pointerdown', (e) => { if (pop && !pop.contains(e.target) && e.target !== btnC && !btnC.contains(e.target)) closePop(); });

  /* ── help ── */
  const KEYS = [
    ['Transport'], ['Play / stop', 'Space'], ['Stop twice → start', 'Space Space'], ['Go to start', 'Home / ↩'], ['Move by bar', '← →'], ['Move by 4 bars', '⇧← ⇧→'], ['Loop on/off', 'L'], ['Record arm', 'F9'], ['Metronome', 'K'],
    ['Views'], ['Arrange · Session · Mixer · Review', '⌘1 ⌘2 ⌘3 ⌘4'], ['Zoom in / out', '+ −  (⌘-scroll)'], ['Zoom to fit', 'Z'], ['Follow playhead', 'F'], ['Light / dark', '⇧T'], ['Browser search', '⌘F'], ['Hide / show browser', '⌘⌥B'],
    ['Clips (Arrangement)'], ['Split at the playhead', '⌘E'], ['Mute / unmute clip', '0'], ['Delete clip', '⌫'], ['Drag without snapping', '⌘-drag'], ['Import audio', 'drop files'],
    ['Tracks'], ['Select track above / below', '↑ ↓'], ['Mute / solo selected', 'M  S'], ['Launch scene (Session)', '1 – 8'], ['Undo / redo', '⌘Z  ⇧⌘Z'], ['Save the session', '⌘S'],
    ['Assistant'], ['Palette + chat', '⌘K'], ['Approve / cancel newest card', '⏎  Esc'], ['Hide / show the Assistant', '⌘J'], ['Assistant full height / beside devices', '⌘⇧J'],
    ['Review'], ['Next / previous finding', 'J K'], ['Approve · skip · change', 'Y N C'], ['A/B', 'B'], ['Play from finding', 'P'],
  ];
  HX.showHelp = function () {
    const o = HX.$('#helpOverlay');
    o.innerHTML = '';
    const cols = h('div.cols');
    KEYS.forEach((k) => cols.append(k.length === 1 ? h('div.grp.label', null, k[0]) : h('div.k', null, h('span', null, k[0]), h('kbd', null, k[1]))));
    o.append(h('div.help', { role: 'dialog', 'aria-label': 'Keyboard shortcuts' }, h('h3', null, 'Keyboard', h('small', null, 'Esc to close')), cols));
    o.hidden = false;
    HX.emit('help', o);                            // the guided tours add their button to this list
    o.onclick = (e) => { if (e.target === o) o.hidden = true; };
  };
  HX.$('#btnHelp').addEventListener('click', HX.showHelp);

  /* ── keyboard ──
     The page's keys are dead while a dialog, the shortcuts list or a popover is open, in a text field, and on the no-engine
     screen. A button, link or lane header reached with the keyboard keeps its own Enter and Space. Tab is never taken. */
  const typing = () => /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
  /* a control that has the focus because the keyboard put it there (Tab) answers Enter and Space itself; one the mouse
     just clicked does not (Space still plays). */
  let byMouse = true;
  document.addEventListener('pointerdown', () => { byMouse = true; }, true);
  document.addEventListener('keydown', (e) => { if (e.key === 'Tab') byMouse = false; }, true);
  const keyboardControl = () => {
    const a = document.activeElement;
    return !byMouse && !!a && a !== document.body && !!a.closest('button, a[href], summary, [role="button"], .th');
  };
  document.addEventListener('keydown', (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 's') {            // the browser's own "save page" is never wanted here
      e.preventDefault();
      if (!HX.modalOpen() && !HX.noEngineScreen()) HX.saveSession();
      return;
    }
    if (HX.noEngineScreen()) return;
    if (HX.modalOpen()) {
      if (e.key === 'Escape') { const o = HX.$('#helpOverlay'); if (!o.hidden) o.hidden = true; else if (pop) closePop(); }
      else if (e.key === '?' && !HX.$('#helpOverlay').hidden && !typing()) HX.$('#helpOverlay').hidden = true;
      return;
    }
    if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); return HX.focusAssistant(); }
    if (mod && e.key.toLowerCase() === 'j') { e.preventDefault(); if (e.shiftKey) { app.classList.toggle('dock-short'); HX.arrange.dirty = true; return; } return HX.toggleDock(); }
    if (mod && e.key.toLowerCase() === 'f') { e.preventDefault(); app.classList.remove('browser-min'); return HX.browserSearch.focus(); }
    if (typing()) return;
    if ((e.key === ' ' || e.key === 'Enter') && keyboardControl()) return;           // the focused control answers
    if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); return e.shiftKey ? HX.redo() : HX.undo(); }
    if (mod && e.altKey && e.code === 'KeyB') { e.preventDefault(); app.classList.toggle('browser-min'); HX.arrange.dirty = true; return; }
    if (mod && /^[1-4]$/.test(e.key)) { e.preventDefault(); return HX.setView(['arrange', 'session', 'mixer', 'review'][+e.key - 1]); }
    if (mod) return;
    if (e.key === 'Escape' && !e.repeat && HX.cardKey(e.key)) { e.preventDefault(); return; }       // Esc cancels the newest card; Enter approves nothing from here
    const k = e.key;
    const beat = HX.pos();
    const sel = HX.track(S.ui.trackId);
    const list = HX.allTracks();
    switch (true) {
      case k === ' ': e.preventDefault(); HX.toggle(); break;
      case k === 'Home' || k === 'Enter': e.preventDefault(); HX.locate(0); break;
      case k === 'End': HX.locate(S.session.lengthBeats - 4); break;
      case k === 'ArrowLeft': e.preventDefault(); HX.locate(Math.max(0, Math.floor(beat / 4 - (e.shiftKey ? 4 : 1) + 0.001) * 4)); HX.scrollToBeat(HX.pos()); break;
      case k === 'ArrowRight': e.preventDefault(); HX.locate((Math.floor(beat / 4 + 0.001) + (e.shiftKey ? 4 : 1)) * 4); HX.scrollToBeat(HX.pos()); break;
      case k === 'ArrowUp' || k === 'ArrowDown': { e.preventDefault(); const i = list.indexOf(sel) + (k === 'ArrowUp' ? -1 : 1); if (list[i]) HX.select(list[i].id); break; }
      case k === 'l' || k === 'L': HX.toggleLoop(); break;
      case k === 'k' || k === 'K': HX.toggleMetro(); break;
      case k === 'F9': HX.toggleRec(); break;
      case k === 'T' && e.shiftKey: HX.toggleTheme(); break;
      case k === 'z' || k === 'Z': HX.setView('arrange'); HX.zoomFit(); break;
      case k === 'f' || k === 'F': HX.arrange.follow = !HX.arrange.follow; HX.toast('Follow ' + (HX.arrange.follow ? 'on' : 'off')); { const b = HX.$('#followBtn'); b && (b.style.color = HX.arrange.follow ? 'var(--acc)' : ''); } break;
      case k === '+' || k === '=': HX.zoomBy(1.4); break;
      case k === '-' || k === '_': HX.zoomBy(1 / 1.4); break;
      case (k === 'm' || k === 'M') && sel && !sel.isMaster: HX.edit({ trackId: sel.id, param: 'mute' }, !sel.mute, (sel.mute ? 'Unmute ' : 'Mute ') + sel.name); break;
      case (k === 's' || k === 'S') && sel && !sel.isMaster: HX.edit({ trackId: sel.id, param: 'solo' }, !sel.solo, (sel.solo ? 'Unsolo ' : 'Solo ') + sel.name); break;
      case /^[1-8]$/.test(k) && S.ui.view === 'session': HX.launchScene(+k - 1); break;
      case k === '?': HX.showHelp(); break;
      default: return;
    }
  });

  HX.on('engine', (st) => {
    if (!HX.mcp.connected) return;
    const es = HX.$('#engineStatus');
    if (st === 'lost') { HX.freezeTransport(); es.classList.remove('on'); es.textContent = 'MCP · the engine is not answering (retrying)'; }   // the playhead stops; the next answer puts it right
    else setConn('on', 'Engine');
  });
  HX.on('session-light', () => { HX.renderArrangeHeaders(); HX.mountMixer(); });
  HX.on('live', () => { if (HX.mcp.connected) setConn('on', 'Engine'); });
  HX.on('session', () => { HX.$('#sessionName').textContent = S.session.name; HX.$('#tempo').textContent = S.session.tempo.toFixed(2); syncTransport(); HX.emit('select'); syncSave(); });

  /* ── boot ── */
  /* the theme was set before first paint in index.html */
  HX.loadMock();
  HX.mountArrange(); HX.mountSession(); HX.mountMixer(); HX.mountDevices(); HX.mountBrowser(); HX.mountReview(); HX.mountAssistant();
  HX.emit('session');
  HX.emit('theme');
  let v = 'arrange'; try { v = localStorage.getItem('hx.view') || 'arrange'; } catch (e) {}
  HX.setView(v);
  /* the page starts on nothing: inside the app it looks for the engine (and says so if there is none); opened on its own
     (not served by the app) there is only the demo song, and it is labelled */
  if (HX.api.inApp) { setMode('noengine'); renderNoEngine(null); setConn(null, idleLabel()); }
  else { HX.userMock = true; setMode('demo'); setConn(null, idleLabel()); }
  requestAnimationFrame(() => HX.zoomFit());
})();
