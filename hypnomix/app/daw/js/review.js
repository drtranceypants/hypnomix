/* Hypnomix · Review on the engine's session (connected, inside the app): the real hypnomix loop.
   Scan = session_save + a bounce of the mix (session_export_mix) + `hypnomix scan SESSION.ardour --mix`, run by the
   app (POST /api/dawreview/scan; progress from GET /api/job). Findings, decisions (the same decisions.json as
   `hypnomix fix --decide`) and Apply (`hypnomix fix --approved --out "<snapshot> (HypnoMix).ardour"`) go through
   hypnomix/app/dawreview.py. Opening the new snapshot is the supervisor's POST /api/daw/open, after a click.
   A/B of clip and mixer fixes: `hypnomix abset` writes "<snapshot> (A-B).ardour" (POST /api/dawreview/abset); once the
   engine has it open, A / B / Blind switch each finding over MCP (ab_use_playlist, or the track's fader / pan / mute),
   with the louder side turned down on the master fader by the measured match_db. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  const R = { st: null, data: null, cur: 0, job: null, busy: '', confirm: null, note: false, ev: {}, lastOut: '', err: '', log: [], applied: {}, abPlay: null, loading: false,
    ab: null, flip: null, want: null, blind: null };
  let root = null;
  const STAGES = 11;                                     // the scan's groups (names, files, clips, ... stems)

  const api = HX.api;
  const add = (el, ...kids) => el.append(...kids.filter((k) => k != null && k !== false));
  const decOf = (f) => { const e = R.data && R.data.decisions[f.id]; return e ? (typeof e === 'string' ? e : e.decision) : ''; };
  const statusOf = (f) => R.applied[f.id] ? 'applied' : ({ approve: 'approved', skip: 'skipped', change: 'changed' }[decOf(f)] || (f.handling === 'question' || f.handling === 'info' ? 'info' : 'open'));
  const list = () => (R.data ? R.data.findings : []);
  const sevOf = (f) => (f.severity === 'high' ? 'high' : f.severity === 'medium' ? 'med' : 'low');
  const trackOf = (f) => (f.engine_track && HX.trackByName(f.engine_track)) || null;
  const fmtAt = (s) => (s == null ? 'whole' : HX.bbtStr(HX.secToBeats(s)).replace(/\. /g, '.').replace(/\.\d+$/, ''));
  const count = (st) => list().filter((f) => statusOf(f) === st).length;
  const qs = (o) => Object.keys(o).map((k) => k + '=' + encodeURIComponent(o[k])).join('&');

  /* ── state from the app ── */
  async function refresh(force) {
    if (R.loading || R.busy) return;
    if (!force && R.st && R.data) return draw();
    R.loading = true;
    try {
      R.st = await api.get('/api/dawreview/state');
      /* clear only an error a refresh set: a failed scan / apply stays up (Dismiss) across the engine's reconnect */
      if (!R.st.connected) { R.err = R.st.error; R.errSt = true; } else if (R.errSt) { R.err = ''; R.errSt = false; }
      if (R.st.scanned) await loadFindings(R.st.dir); else { R.data = null; markers(); }
    } catch (e) { R.err = e.message; R.errSt = true; }
    R.loading = false;
    draw();
  }
  async function loadFindings(dir) {
    const keep = R.data && list()[R.cur] && list()[R.cur].id;
    R.data = await api.get('/api/dawreview/findings?' + qs({ dir }));
    R.applied = {}; (R.data.applied || []).forEach((id) => (R.applied[id] = true));   /* from the scan's fix-log.md */
    R.ev = {};
    R.ab = await api.get('/api/dawreview/abstate?' + qs({ dir })).catch(() => null);
    const i = keep ? list().findIndex((f) => f.id === keep) : -1;
    R.cur = i >= 0 ? i : Math.max(0, list().findIndex((f) => statusOf(f) === 'open'));
    markers();
  }
  /* the findings as markers on the Arrangement's lanes and ruler (the same fields the mock findings carry) */
  function markers() {
    S.findings = list().filter((f) => f.at_s != null).map((f) => { const t = trackOf(f); return { id: f.id, at: HX.secToBeats(f.at_s), track: t ? t.id : null, status: statusOf(f), sev: sevOf(f) }; });
    S.scanned = !!R.data;
    const b = HX.$('#reviewBadge'); if (b) b.textContent = count('open') || '';
    if (HX.arrange) HX.arrange.dirty = true;
  }

  /* ── the app's job runner: poll /api/job (twice a second while it runs, never faster) ── */
  async function follow(id, onDone) {
    let since = 0;
    R.log = [];
    const tick = async () => {
      let j;
      try { j = await api.get('/api/job?since=' + since); } catch (e) { R.err = e.message; R.busy = ''; return draw(); }
      if (j.id !== id) { R.busy = ''; return draw(); }
      since = j.total; R.log.push(...j.log); if (R.log.length > 400) R.log.splice(0, R.log.length - 400);
      R.job = j; progress();
      if (j.status === 'running') return setTimeout(tick, 500);
      R.busy = '';
      onDone(j.status === 'done', j);
    };
    tick();
  }
  function pct() {
    const j = R.job; if (!j) return 0;
    if (R.busy === 'scan') {
      const m = /(\d+)%/.exec(j.step || '');
      if (/^Saving/.test(j.step)) return 3;
      if (/^Bouncing/.test(j.step)) return 5 + (m ? +m[1] : 0) * 0.25;
      const done = R.log.filter((l) => /^\s+\w+\s+\d+ findings?\s+\(/.test(l)).length;
      return 30 + (done / STAGES) * 68;
    }
    return j.status === 'running' ? 50 : 100;
  }
  function progress() {
    if (!root) return;
    const bar = root.querySelector('.scanbar i'), lab = root.querySelector('.scanstage'), lg = root.querySelector('.rv-log');
    if (!bar) return draw();
    bar.style.width = pct().toFixed(0) + '%';
    if (lab) lab.textContent = (R.job && R.job.step) || 'Starting…';
    if (lg) lg.textContent = R.log.slice(-6).join('\n');
  }

  /* ── scan ── */
  function scan(skipAsk) {
    HX.setView('review');
    if (R.busy) return HX.toast('Wait for the ' + R.busy + ' to finish');
    if (!skipAsk) { R.confirm = 'scan'; return draw(); }
    R.confirm = null; R.err = ''; R.busy = 'scan'; R.job = null; R.log = []; draw();   /* busy at once: a double click starts one scan */
    Promise.resolve(HX.endAuditions && HX.endAuditions('scanning')).catch(() => {}).then(() => api.post('/api/dawreview/scan', { save: true })).then((r) => {   /* ended Hear it first: never saved, never bounced; only reached after "Save and scan" */
      R.busy = 'scan'; R.job = null; draw();
      HX.log('mcp', 'HypnoMix review · session_save, session_export_mix, hypnomix scan ' + r.session.split('/').pop() + ' --mix');
      follow(r.job, async (ok) => {
        if (!ok) { R.err = 'The scan did not finish: ' + (R.log.slice(-3).join(' · ') || 'see the log'); return draw(); }
        R.st = await api.get('/api/dawreview/state').catch(() => R.st);
        await loadFindings(r.dir).catch((e) => (R.err = e.message));
        HX.toast(list().length + ' findings');
        HX.emit('review', { what: 'scanned' });
        draw(); select(R.cur);
      });
    }).catch((e) => { R.busy = ''; R.err = e.status === 409 && e.body && e.body.error === 'unsaved' ? 'The session has changes that are not saved. Press Scan again and choose Save and scan.' : e.message; draw(); });
  }

  /* ── select: the playhead goes to the finding, its track is selected ── */
  function select(i) {
    const L = list(); if (!L.length) return;
    stopAB(); unflip();
    R.cur = HX.clamp(i, 0, L.length - 1); R.note = false;
    const f = L[R.cur], t = trackOf(f);
    if (t) HX.select(t.id);
    if (f.at_s != null) { const b = HX.secToBeats(f.at_s); HX.locate(b); HX.scrollToBeat && HX.scrollToBeat(b); }
    draw();
    const row = root && root.querySelector('.rv-row.on'); row && row.scrollIntoView({ block: 'nearest' });
  }

  /* ── decisions: approve / skip / change, saved at once (clicking the same one again clears it) ── */
  async function decide(decision, note) {
    const f = list()[R.cur]; if (!f || R.busy || R.deciding) return;   /* one decision at a time: fast keys never act twice on one finding */
    if (decision === 'approve' && (f.handling === 'blocked' || f.handling === 'question' || f.handling === 'info')) return HX.toast(f.handling_text, 3200);
    const same = decOf(f) === decision && note === undefined;
    R.deciding = true;
    try {
      const e = await api.post('/api/dawreview/decide', { dir: R.data.dir, id: f.id, decision: same ? 'clear' : decision, note: note || '' });
      if (same) delete R.data.decisions[f.id]; else R.data.decisions[f.id] = e;
    } catch (e) { return HX.toast(e.message, 3200); } finally { R.deciding = false; }
    markers();
    if (!same) HX.emit('review', { what: 'decided', status: decision });
    const next = list().findIndex((g, k) => k > R.cur && statusOf(g) === 'open');
    if (!same && next >= 0) select(next); else draw();
  }

  /* ── apply: one new snapshot beside the original, then (after a click) open it in the engine ── */
  /* what Apply acts on: approved fixes it can write (region and mixer edits) or make (repaired recordings) */
  const appliable = (f) => decOf(f) === 'approve' && !R.applied[f.id] && (f.handling === 'written' || f.handling === 'file');
  function approvedN() { return list().filter(appliable).length; }
  async function apply() {
    R.confirm = null; R.err = '';
    const ids = list().filter(appliable).map((f) => f.id);
    try {
      const r = await api.post('/api/dawreview/apply', { dir: R.data.dir });
      R.busy = 'apply'; draw();
      HX.log('mcp', 'hypnomix fix --approved --out "' + r.out.split('/').pop() + '"');
      follow(r.job, async (ok) => {
        const wrote = R.log.some((l) => /^check\s+structure OK/.test(l));
        if (!ok || !wrote) { R.err = (ok ? 'Nothing was written: ' : 'Apply failed: ') + (R.log.filter((l) => l.trim()).slice(-3).join(' · ') || 'see the log'); return draw(); }
        ids.forEach((id) => (R.applied[id] = true));
        R.lastOut = r.out; R.confirm = 'open';
        HX.emit('review', { what: 'applied' });
        await loadFindings(R.data.dir).catch(() => {});
        draw();
      });
    } catch (e) { R.err = e.message; draw(); }
  }
  async function openSnap() {
    const path = R.lastOut; R.confirm = null; R.busy = 'open'; draw();
    try {
      if (!(await HX.guardedPost('/api/daw/open', { path }, 'Opening the new snapshot closes this one.', { before: () => { HX.reopening = true; } }))) { R.busy = ''; return draw(); }   // null: cancelled at Save / Don't save / Cancel
      await HX.connectEngine();
      R.opened = path.split('/').pop();
      HX.toast('Opened ' + path.split('/').pop().replace(/\.ardour$/, ''), 3000);
    } catch (e) { R.err = 'Could not open the snapshot: ' + e.message; }
    HX.reopening = false; R.busy = '';
    refresh(true);
  }

  /* ── A/B: where `hypnomix ab` can build a pair for an Ardour session (repaired recordings, tuning) ── */
  const abRow = (f) => (R.data && R.data.ab && R.data.ab[f.id]) || null;
  function buildAB() {
    const f = list()[R.cur];
    api.post('/api/dawreview/ab', { dir: R.data.dir, id: f.id }).then((r) => {
      R.busy = 'ab'; draw();
      follow(r.job, async (ok) => { if (!ok) R.err = 'The A/B pair could not be built: ' + R.log.slice(-2).join(' · '); await loadFindings(R.data.dir).catch(() => {}); draw(); });
    }).catch((e) => HX.toast(e.message, 3200));
  }
  function stopAB() { if (R.abPlay) { R.abPlay.a.pause(); R.abPlay.b.pause(); R.abPlay = null; } }
  function playAB(f, side) {
    const row = abRow(f); if (!row || !row.a) return;
    if (!R.abPlay || R.abPlay.id !== f.id) {
      stopAB();
      const src = (n) => '/audio?' + qs({ dir: R.data.dir, f: n });
      R.abPlay = { id: f.id, a: new Audio(src(row.a)), b: new Audio(src(row.b)), side: 'A' };
      R.abPlay.a.addEventListener('ended', () => { R.abPlay = null; draw(); });
    }
    const p = R.abPlay, from = p.side === 'A' ? p.a : p.b, to = side === 'A' ? p.a : p.b;
    if (from !== to && !from.paused) { to.currentTime = from.currentTime; from.pause(); to.play(); }
    else if (to.paused) to.play(); else { to.pause(); }
    p.side = side; draw();
    HX.emit('review', { what: 'ab', side });
  }

  /* ── A/B of clip and mixer fixes on the engine (the A/B snapshot from `hypnomix abset`) ── */
  const abItem = (f) => (R.ab && R.ab.built && R.ab.items && R.ab.items[f.id]) || null;
  function buildABSession() {
    R.err = '';
    api.post('/api/dawreview/abset', { dir: R.data.dir }).then((r) => {
      R.busy = 'abset'; draw();
      follow(r.job, async (ok) => {
        if (!ok) R.err = 'The A/B session could not be built: ' + R.log.filter((l) => l.trim()).slice(-2).join(' · ');
        R.ab = await api.get('/api/dawreview/abstate?' + qs({ dir: R.data.dir })).catch(() => null);
        draw();
      });
    }).catch((e) => HX.toast(e.message, 3200));
  }
  async function openABSession() {
    const path = R.ab && R.ab.session; R.confirm = null; if (!path) return;
    R.busy = 'open'; draw();
    try {
      await unflip();
      if (!(await HX.guardedPost('/api/daw/open', { path }, 'Opening the A/B session closes this one.', { before: () => { HX.reopening = true; } }))) { R.busy = ''; HX.reopening = false; return draw(); }   // null: cancelled at Save / Don't save / Cancel
      await HX.connectEngine();
      HX.toast('Opened the A/B session: every finding plays A (as it is) until you press B', 3200);
    } catch (e) { R.err = 'Could not open the A/B session: ' + e.message; }
    HX.reopening = false; R.busy = '';
    refresh(true);
  }
  /* one finding is flipped at a time; the master fader goes back to where it was when it is put back to A.
     Every switch runs after the one before (one chain), so two never overlap (fast keys, a click and a key, a Save);
     the master's level to come back to is read from the engine when a flip starts from A, never from the view's own
     copy, which a refresh can fill with the turned-down value. A switch that fails half-way puts A back.
     A goes back before a Save or a scan (HX.onEnd), when the view leaves Review, and when the page closes. */
  let chain = Promise.resolve();
  function queue(fn) { const p = chain.then(fn); chain = p.catch(() => {}); return p; }
  const flipCalls = (it, side) => { const v = side === 'B' ? it.b : it.a; return it.kind === 'playlist'
    ? [['ab_use_playlist', { track_id: it.trackId, playlist_id: side === 'B' ? it.b_playlist_id : it.a_playlist_id }]]
    : [['track_set_fader_db', { id: it.trackId, db: HX.clamp(v.fader_db, -193, 6) }], ['track_set_pan', { id: it.trackId, position: HX.clamp((1 - v.pan) / 2, 0, 1) }], ['track_set_mute', { id: it.trackId, value: !!v.mute }]]; };
  async function masterNow(master) {
    try { const ti = await HX.mcp.trackInfo(master.id); const db = ti && ti.fader && ti.fader.db; if (db != null && isFinite(db)) return Math.max(-193, db); } catch (e) {}
    return master.faderDb;
  }
  /* R.want: the side last asked for, so B pressed again before the first switch is done means A (the key toggles it) */
  function flip(f, side) { R.want = { id: f.id, side }; return queue(() => doFlip(f, side)); }
  function unflip() { R.want = null; return queue(doUnflip); }
  async function doFlip(f, side) {
    const it = abItem(f); if (!it || !it.kind || !(R.ab && R.ab.open)) return;
    const M = HX.mcp, master = S.session.master;
    if (R.flip && R.flip.id !== f.id) await doUnflip();
    if (!R.flip) R.flip = { id: f.id, side: 'A', base: master ? await masterNow(master) : 0 };
    const m = +it.match_db || 0;
    /* the louder side is turned down by the difference, so the change is heard, not the level */
    const trim = side === 'B' ? -Math.max(0, m) : Math.min(0, m);
    try {
      for (const [name, args] of flipCalls(it, side)) await M.call(name, args);
      if (master) { await M.setFaderDb(master.id, R.flip.base + trim); HX.liveEngine && HX.liveEngine.touch && HX.liveEngine.touch(master.id); }
      R.flip.side = side;
    } catch (e) {
      HX.toast('A/B: ' + e.message + ' · A is put back', 3600);
      R.want = null;
      await doUnflip();
    }
    draw();
  }
  async function doUnflip() {
    const fl = R.flip; if (!fl) return;
    R.flip = null;
    const f = list().find((x) => x.id === fl.id), it = f && abItem(f), M = HX.mcp, master = S.session.master;
    if (!it || !HX.mcp.connected) return;
    try {
      for (const [name, args] of flipCalls(it, 'A')) await M.call(name, args);
      if (master) { await M.setFaderDb(master.id, fl.base); master.faderDb = fl.base; HX.liveEngine && HX.liveEngine.touch && HX.liveEngine.touch(master.id); }
    } catch (e) { HX.toast('A/B: putting A back: ' + e.message, 3600); }
  }
  /* the page is closing: there is no time to wait, so the calls that put A back go out as they are (kept alive) */
  function unflipNow() {
    const fl = R.flip; if (!fl || !HX.mcp.connected) return;
    const f = list().find((x) => x.id === fl.id), it = f && abItem(f), master = S.session.master;
    if (!it || !HX.mcp.beacon) return;
    for (const [name, args] of flipCalls(it, 'A')) HX.mcp.beacon(name, args);
    if (master) HX.mcp.beacon('track_set_fader_db', { id: master.id, db: HX.clamp(fl.base, -193, 6) });
    R.flip = null; R.want = null;
  }
  /* always through the chain: a switch asked for a moment ago (not started yet) is put back too */
  HX.onEnd(() => unflip().then(() => draw()));
  window.addEventListener('pagehide', unflipNow);
  function blindStart(f) {
    const xIsB = Math.random() < 0.5;
    R.blind = { id: f.id, X: xIsB ? 'B' : 'A', Y: xIsB ? 'A' : 'B', on: null, picked: null };
    draw();
  }
  async function blindPick(f, which) {
    const b = R.blind; if (!b || b.id !== f.id) return;
    b.picked = which;
    try { await api.post('/api/dawreview/blind', { dir: R.data.dir, id: f.id, picked: which, was: b[which] }); }
    catch (e) { HX.toast('Not saved: ' + e.message, 3200); }
    draw();
  }
  function engineAB(f) {
    const box = h('div.rv-actions'), note = (t) => h('span.tool.mono', { style: { color: 'var(--tx3)', fontSize: 'var(--fs-xs)' } }, t);
    const ab = R.ab;
    if (!ab || !ab.built || !ab.exists) {
      add(box, h('button.btn', { disabled: !!R.busy, onclick: buildABSession, 'data-info': 'hypnomix abset: ONE new snapshot beside the original where every proposed fix can be switched A / B here, level-matched (the open session is not touched)' }, 'Build A/B session'),
        note('every clip and mixer fix as a switchable B, in a new snapshot'));
      return box;
    }
    const it = abItem(f);
    if (!it || !it.kind) { add(box, note(it && it.note ? it.note : 'not in the A/B session (built before this finding: build it again)')); return box; }
    if (!ab.open) {
      add(box, h('button.btn', { disabled: !!R.busy, onclick: () => { R.confirm = 'abopen'; draw(); }, 'data-info': 'The engine opens ' + ab.session.split('/').pop() + ' (it plays exactly like the original until you press B)' }, 'Open A/B session'),
        note((it.kind === 'playlist' ? 'a fixed copy of ' + it.track + '’s playlist' : it.track + '’s fader, pan, mute') + ', B ' + HX.fmtDb(abLevel(it).d, true) + ' dB' + (abLevel(it).capped ? ' (matched by ' + abLevel(it).m + ' dB at most)' : '')));
      return box;
    }
    const side = R.flip && R.flip.id === f.id ? R.flip.side : 'A', bl = R.blind && R.blind.id === f.id ? R.blind : null;
    if (bl) {
      const on = (w) => bl.on === w;
      add(box, h('div.seg', { 'data-info': 'Blind: X and Y are A and B in a random order. Listen, then choose.' },
        h('button.a' + (on('X') ? '.on' : ''), { onclick: () => { bl.on = 'X'; flip(f, bl.X); } }, 'X'),
        h('button.b' + (on('Y') ? '.on' : ''), { onclick: () => { bl.on = 'Y'; flip(f, bl.Y); } }, 'Y')));
      if (!bl.picked) add(box, h('button.btn', { onclick: () => blindPick(f, 'X') }, 'I prefer X'), h('button.btn', { onclick: () => blindPick(f, 'Y') }, 'I prefer Y'));
      else add(box, note('you chose ' + bl.picked + ': it was ' + (bl[bl.picked] === 'B' ? 'B (fixed)' : 'A (as it is)') + ' · saved in blind.json'),
        h('button.btn.ghost', { onclick: () => { R.blind = null; draw(); } }, 'Done'));
      return box;
    }
    add(box, h('div.seg', { 'data-info': 'A = as it is, B = with the fix; switched in the engine while it plays, level-matched on the master · B' },
      h('button.a' + (side === 'A' ? '.on' : ''), { onclick: () => flip(f, 'A') }, 'A  original'),
      h('button.b' + (side === 'B' ? '.on' : ''), { onclick: () => flip(f, 'B') }, 'B  fixed')),
      h('button.btn', { onclick: () => blindStart(f), 'data-info': 'Hear X and Y without knowing which is the fix, choose, then see' }, 'Blind'),
      note(abLevelText(it) + ' · P plays from the spot'));
    return box;
  }
  /* the measured difference (level_db when the match was capped), and how much the master takes back
     (match_db, at most 12 dB: abset_ardour.MAX_MATCH_DB) */
  function abLevel(it) {
    const m = +it.match_db || 0, capped = !!it.match_capped && it.level_db != null;
    return { d: capped ? +it.level_db : m, m: Math.abs(m), capped };
  }
  function abLevelText(it) {
    const l = abLevel(it), side = l.d >= 0 ? 'B' : 'A', by = HX.fmtDb(Math.abs(l.d));
    if (l.capped) return side + ' is ' + by + ' dB louder: turned down on the master by ' + l.m + ' dB, the most it is, while you listen';
    return side + ' is ' + by + ' dB louder: turned down on the master while you listen';
  }
  HX.abLevelText = abLevelText;

  /* ── render ── */
  function draw() { root = root || HX.$('#viewReview'); if (root && S.ui.view === 'review') render(root); }
  function render(el) {
    root = el; el.innerHTML = '';
    const L = list(), nApp = approvedN();
    const busyWord = { scan: 'Scanning…', apply: 'Writing the snapshot…', open: 'Opening the snapshot…', ab: 'Building A/B…', abset: 'Building the A/B session…' }[R.busy];
    el.append(h('div.rv-bar', null, h('span.t', null, 'Review'),
      L.length ? h('div.stat', null, h('span', null, h('b', null, String(count('open'))), 'open'), h('span.a', null, h('b', null, String(count('approved'))), 'approved'), h('span.c', null, h('b', null, String(count('changed'))), 'changed'), h('span.s', null, h('b', null, String(count('skipped'))), 'skipped'), count('applied') ? h('span', null, h('b', null, String(count('applied'))), 'applied') : null)
        : h('span.stat', null, R.data ? 'No findings' : 'Not scanned yet'),
      h('span.stat.mono', { 'data-info': 'The session the engine has open, and the scan folder' }, R.st && R.st.session ? R.st.session.split('/').pop() : ''),
      h('div.right', null,
        busyWord ? h('span.stat', null, busyWord) : null,
        h('button.btn', { disabled: !!R.busy, onclick: () => scan(), 'data-info': 'Save the session, bounce the mix and run the HypnoMix scan on it (asks first)' }, R.data ? 'Rescan' : 'Scan'),
        h('button.btn.primary', { disabled: !nApp || !!R.busy, onclick: () => { R.confirm = 'apply'; draw(); }, 'data-info': 'Write the approved fixes into ONE new snapshot beside the original (asks first)' }, 'Apply ' + nApp + ' → new snapshot'))));

    const err = R.err ? h('div.rv-confirm', { style: { borderColor: 'var(--bad)', background: 'transparent' } }, h('span', null, R.err), h('button.btn.ghost', { onclick: () => { R.err = ''; draw(); } }, 'Dismiss')) : null;
    if (R.busy === 'scan' || (!L.length && (R.confirm === 'scan' || !R.data))) {
      const box = h('div.rv-empty', { style: { maxWidth: '440px' } });
      if (R.busy === 'scan') add(box, h('h3', null, 'Scanning ' + (R.st && R.st.session ? R.st.session.split('/').pop().replace(/\.ardour$/, '') : '')), h('div.scanbar', null, h('i', { style: { width: pct().toFixed(0) + '%' } })), h('span.scanstage', null, (R.job && R.job.step) || 'Starting…'),
        h('pre.rv-log.mono', { style: { textAlign: 'left', fontSize: '10.5px', color: 'var(--tx3)', whiteSpace: 'pre-wrap', margin: 0, maxWidth: '440px', minHeight: '6em' } }, R.log.slice(-6).join('\n')));
      else if (R.confirm === 'scan') add(box, h('h3', null, 'Save and scan?'), h('p', null, 'The scan saves the session, bounces the mix into the scan folder, then runs the HypnoMix scan on the saved session (a few minutes). Nothing in the session changes until you approve fixes and apply them to a new snapshot.'),
        R.st && R.st.dirty ? h('p', { style: { color: 'var(--warn)' } }, 'The session has unsaved changes: they are saved first.') : null,
        h('div.rv-actions', null, h('button.btn.primary', { onclick: () => scan(true) }, 'Save and scan ', h('kbd', null, '⏎')), h('button.btn', { onclick: () => { R.confirm = null; draw(); } }, 'Cancel')));
      else if (R.opened && R.st && R.st.session && R.st.session.endsWith('/' + R.opened)) add(box, h('h3', null, R.opened.replace(/\.ardour$/, '') + ' is open'), h('p', null, 'The engine is on the new snapshot with your approved fixes; the original snapshot is unchanged. Scan this one to hear and check what is left.'),
        h('button.btn.ai', { onclick: () => scan() }, 'Scan session'));
      else add(box, h('h3', null, 'Find what needs fixing'), h('p', null, 'HypnoMix scans the session the way an engineer would: track names and order, files, clicks and cuts, timing against the drums, vocal pitch with the chord, recordings (sibilance, breaths, noise), the mix and its stems.'),
        R.loading ? h('span.stat', null, 'Reading…') : h('button.btn.ai', { onclick: () => scan() }, 'Scan session'));
      if (err) box.prepend(err);
      el.append(h('div', { style: { flex: 1, display: 'flex' } }, box));
      return;
    }
    if (!L.length) { el.append(h('div', { style: { flex: 1, display: 'flex' } }, h('div.rv-empty', null, err, h('h3', null, 'Nothing to fix'), h('p', null, 'The scan found nothing in this session.')))); return; }

    const lst = h('div.rv-list');
    L.forEach((f, i) => {
      const t = trackOf(f), st = statusOf(f);
      lst.append(h('div.rv-row' + (i === R.cur ? '.on' : ''), { onclick: () => select(i) },
        h('span.n', null, String(i + 1).padStart(2, '0')), h('i.sev.' + sevOf(f)),
        h('div.ti', null, h('b', null, f.problem), h('small', null, f.fix || '')),
        h('span.tk', null, h('i', { style: { background: t ? t.color : 'var(--line2)' } }), f.engine_track || f.track || ''),
        h('span.at', null, fmtAt(f.at_s)),
        h('span.pill.' + st, null, st)));
    });
    const f = L[R.cur] || L[0], det = h('div.rv-detail');
    if (err) det.append(err);
    if (R.busy === 'apply' || R.busy === 'ab' || R.busy === 'abset' || R.busy === 'open') det.append(h('div.rv-confirm', null, h('span', null, busyWord + ' ', h('span.scanstage.mono', { style: { color: 'var(--tx3)' } }, (R.job && R.job.step) || '')), h('div.scanbar', null, h('i', { style: { width: pct().toFixed(0) + '%' } }))));
    if (R.confirm === 'scan') {
      det.append(h('div.rv-confirm', null, h('span', null, 'Save the session, bounce the mix and scan again? Your decisions stay with the findings that are still there.' + (R.st && R.st.dirty ? ' Unsaved changes are saved first.' : '')),
        h('button.btn.primary', { onclick: () => scan(true) }, 'Save and scan ', h('kbd', null, '⏎')), h('button.btn', { onclick: () => { R.confirm = null; draw(); } }, 'Cancel')));
    }
    if (R.confirm === 'apply') {
      const n = approvedN(), out = R.st && R.st.out;
      det.append(h('div.rv-confirm', null, h('span', null, 'Write ' + n + ' approved fix' + (n > 1 ? 'es' : '') + ' into a new snapshot “' + (out || '').replace(/\.ardour$/, '') + '” in the session folder? The open session is not changed.' + (R.st && R.st.dirty ? ' Changes made since the scan are not in it.' : '')),
        h('button.btn.primary', { onclick: apply }, 'Write snapshot ', h('kbd', null, '⏎')), h('button.btn', { onclick: () => { R.confirm = null; draw(); } }, 'Cancel')));
    }
    if (R.confirm === 'open') {
      det.append(h('div.rv-confirm', null, h('span', null, 'Wrote “' + R.lastOut.split('/').pop().replace(/\.ardour$/, '') + '”. Open it in the engine? The engine restarts on it and the view reads it again.'),
        h('button.btn.primary', { onclick: openSnap }, 'Open snapshot'), h('button.btn', { onclick: () => { R.confirm = null; draw(); } }, 'Stay here')));
    }
    if (R.confirm === 'abopen' && R.ab) {
      det.append(h('div.rv-confirm', null, h('span', null, 'Open “' + R.ab.session.split('/').pop().replace(/\.ardour$/, '') + '” in the engine? It closes ' + (S.session.name || 'this session') + ': what you have not saved there is not kept. The A/B session plays exactly like the original until you press B.'),
        h('button.btn.primary', { onclick: openABSession }, 'Open A/B session'), h('button.btn', { onclick: () => { R.confirm = null; draw(); } }, 'Stay here')));
    }
    const t = trackOf(f);
    det.append(h('h2', null, f.problem),
      h('div.meta', null, h('span', null, 'Track ', h('b', null, f.engine_track || f.track || '—')), h('span', null, 'At ', h('b', null, f.where || fmtAt(f.at_s))), h('span', null, 'Check ', h('b', null, f.tool + (f.kind && f.kind !== f.tool ? ' · ' + f.kind : ''))), h('span', null, 'Severity ', h('b', null, f.severity)), h('span', null, 'Status ', h('b', null, statusOf(f)))));
    const cv = h('canvas'); det.append(cv);
    const fx = h('div.rv-fix', null,
      h('div.fx', null, h('span.label', null, 'Proposed fix'), h('span.what', null, f.fix || '—')),
      h('div.fx', null, h('span.tool', null, f.handling_text + (f.edit ? ' · ' + JSON.stringify(f.edit) : ''))));
    const notes = (f.flagged_notes || []).slice(0, 8);
    if (notes.length) fx.append(h('div.fx', null, h('span.tool', null, 'flagged: ' + notes.map((n) => n.time + ' ' + n.sung + ' ' + (n.cents > 0 ? '+' : '') + n.cents + ' c').join(' · ') + ((f.flagged_notes || []).length > 8 ? ' …' : ''))));
    const e = R.data.decisions[f.id];
    if (e && e.note) fx.append(h('div.fx', null, h('span.label', null, 'Your note'), h('span', null, e.note)));
    if (R.note) {
      const ta = h('textarea', { rows: 2, placeholder: 'What should change? (Settings like fade-ms=20 or amount=0.3 tune the fix when you approve with the note.)', style: { width: '100%', font: 'inherit', background: 'var(--bg1)', color: 'var(--tx0)', border: '1px solid var(--line2)', borderRadius: 'var(--r2)', padding: '6px' } }, (e && e.note) || '');
      ta.addEventListener('keydown', (ev) => { ev.stopPropagation(); if (ev.key === 'Escape') { R.note = false; draw(); } });
      fx.append(ta, h('div.fx', null,
        h('button.btn.ai', { onclick: () => decide('change', ta.value.trim() || 'change requested') }, 'Save as a change'),
        f.handling === 'written' ? h('button.btn', { onclick: () => decide('approve', ta.value.trim()) }, 'Approve with this note') : null,
        h('button.btn.ghost', { onclick: () => { R.note = false; draw(); } }, 'Cancel')));
      requestAnimationFrame(() => ta.focus());
    }
    det.append(fx);
    det.append(abBox(f));
    const canApprove = !['blocked', 'question', 'info'].includes(f.handling);
    det.append(h('div.rv-actions', null,
      h('button.btn', { disabled: f.at_s == null, onclick: () => { const b = HX.secToBeats(Math.max(0, f.at_s - 2)); HX.locate(b); HX.play(); }, 'data-info': 'Play from two seconds before · P' }, '▶  Play here ', h('kbd', null, 'P')),
      h('span', { style: { flex: 1 } }),
      h('button.btn.primary', { disabled: !canApprove || !!R.busy, onclick: () => decide('approve'), 'data-info': canApprove ? 'Approve this fix (click again to undo)' : f.handling_text }, 'Approve ', h('kbd', null, 'Y')),
      h('button.btn', { disabled: !!R.busy, onclick: () => decide('skip') }, 'Skip ', h('kbd', null, 'N')),
      h('button.btn' + (R.note ? '.ai' : ''), { disabled: !!R.busy, onclick: () => { R.note = !R.note; draw(); } }, 'Change ', h('kbd', null, 'C'))));
    if (R.data.fix_log && count('applied')) det.append(h('details', null, h('summary.label', null, 'What Apply wrote (fix log)'), h('pre.mono', { style: { whiteSpace: 'pre-wrap', fontSize: '10.5px', color: 'var(--tx2)' } }, R.data.fix_log.split('\n## fix run').pop().slice(-2400))));
    det.append(h('div.label', { style: { marginTop: 'auto' } }, 'J / K  next / previous · Y approve · N skip · C change with a note · B A/B · P play here'));
    el.append(h('div.rv-split', null, lst, det));
    evidence(cv, f);
  }
  function abBox(f) {
    const row = abRow(f), box = h('div.rv-actions');
    if (f.handling === 'written') return engineAB(f);
    if (row && row.a) {
      const p = R.abPlay && R.abPlay.id === f.id ? R.abPlay : null, on = (s) => p && p.side === s && !(s === 'A' ? p.a : p.b).paused;
      add(box, h('div.seg', { 'data-info': 'A = as it is, B = with the fix (level-matched) · B' }, h('button.a' + (on('A') ? '.on' : ''), { onclick: () => playAB(f, 'A') }, 'A  original'), h('button.b' + (on('B') ? '.on' : ''), { onclick: () => playAB(f, 'B') }, 'B  fixed')),
        h('span.tool.mono', { style: { color: 'var(--tx3)', fontSize: 'var(--fs-xs)' } }, row.seconds + ' s, B matched ' + row.matched_db + ' dB' + (row.note ? ' · ' + row.note : '')));
    } else if (f.handling === 'file' || f.tool === 'tune') {
      add(box, h('button.btn', { disabled: !!R.busy, onclick: buildAB, 'data-info': 'hypnomix ab: a short before / after pair of this fix, level-matched' }, 'Build A/B'),
        row && row.note ? h('span.tool.mono', { style: { color: 'var(--tx3)', fontSize: 'var(--fs-xs)' } }, row.note) : null);
    } else return h('span');
    return box;
  }

  /* ── evidence: the level of the finding's track (and of the bounced mix) around the spot, from the scan ── */
  async function evidence(cv, f) {
    let ev = R.ev[f.id];
    if (!ev) {
      paint(cv, null, 'Reading the evidence…');
      try { ev = R.ev[f.id] = await api.get('/api/dawreview/evidence?' + qs({ dir: R.data.dir, id: f.id })); }
      catch (e) { ev = R.ev[f.id] = { curves: [], note: e.message }; }
      if (list()[R.cur] !== f) return;
    }
    requestAnimationFrame(() => paint(cv, ev));
  }
  function paint(cv, ev, msg) {
    if (!cv.isConnected) return;
    const w = cv.clientWidth, hh = cv.clientHeight, ctx = HX.fitCanvas(cv, w, hh);
    const C = { g: HX.css('--grid2'), t3: HX.css('--tx3'), t1: HX.css('--tx1'), ai: HX.css('--ai'), bad: HX.css('--bad') };
    ctx.clearRect(0, 0, w, hh);
    ctx.font = '9.5px ' + HX.css('--mono'); ctx.fillStyle = C.t3;
    if (!ev || !ev.curves || !ev.curves.length) { ctx.fillText(msg || (ev && ev.note) || 'No evidence for this finding', 10, hh / 2); return; }
    const pad = 30, pw = w - pad - 8, ph = hh - 26, lo = -66, hi = 0;
    const yAt = (v) => 8 + (1 - (HX.clamp(v, lo, hi) - lo) / (hi - lo)) * ph;
    const xAt = (s) => pad + ((s - ev.t0) / Math.max(0.001, ev.t1 - ev.t0)) * pw;
    ctx.strokeStyle = C.g; ctx.lineWidth = 1;
    [-12, -24, -36, -48, -60].forEach((v) => { const y = Math.round(yAt(v)) + 0.5; ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(w - 8, y); ctx.stroke(); ctx.fillText(String(v), 4, y + 3); });
    if (ev.span) { const x0 = xAt(ev.span[0]), x1 = Math.max(x0 + 2, xAt(ev.span[1])); ctx.fillStyle = C.ai; ctx.globalAlpha = 0.12; ctx.fillRect(x0, 8, x1 - x0, ph); ctx.globalAlpha = 1; }
    ev.curves.slice().reverse().forEach((c, k, arr) => {
      const main = k === arr.length - 1, n = c.values.length; if (!n) return;
      ctx.beginPath(); c.values.forEach((v, i) => { const x = pad + (i / Math.max(1, n - 1)) * pw, y = yAt(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.strokeStyle = main ? C.ai : C.t3; ctx.lineWidth = main ? 1.5 : 1; ctx.setLineDash(main ? [] : [3, 3]); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = main ? C.ai : C.t3; ctx.fillText(c.label, w - 8 - ctx.measureText(c.label).width, 18 + (arr.length - 1 - k) * 12);
    });
    ctx.fillStyle = C.t3;
    ctx.fillText(HX.timeStr(ev.t0).replace(/\.\d+$/, '') + ' – ' + HX.timeStr(ev.t1).replace(/\.\d+$/, '') + ' · ' + (ev.note || '') + (ev.span ? ' · shaded: the finding' : ' · whole song'), pad, hh - 6);
  }

  /* ── keys while the Review view is up (connected) ── */
  function key(e) {
    const k = e.key.toLowerCase();
    if (e.key === 'Enter' && R.confirm === 'scan') { e.preventDefault(); return scan(true); }
    if (e.key === 'Enter' && R.confirm === 'apply') { e.preventDefault(); return apply(); }
    if (e.key === 'Escape' && R.confirm) { R.confirm = null; return draw(); }
    if (!list().length) return;
    const f = list()[R.cur];
    const map = { j: () => select(R.cur + 1), arrowdown: () => select(R.cur + 1), k: () => select(R.cur - 1), arrowup: () => select(R.cur - 1), y: () => decide('approve'), n: () => decide('skip'), c: () => { R.note = !R.note; draw(); },
      b: () => { const it = abItem(f); if (it && it.kind && R.ab.open && !R.blind) return flip(f, R.want && R.want.id === f.id && R.want.side === 'B' ? 'A' : 'B');
        const row = abRow(f); if (row && row.a) playAB(f, R.abPlay && R.abPlay.side === 'A' ? 'B' : 'A'); },
      p: () => { if (f.at_s != null) { HX.locate(HX.secToBeats(Math.max(0, f.at_s - 2))); HX.play(); } } };
    if (map[k]) { e.preventDefault(); e.stopImmediatePropagation(); map[k](); }
  }

  HX.realReview = { render, scan, select, key, refresh: (force) => refresh(force), leave: () => { stopAB(); if (R.flip || R.want) unflip().then(() => draw()); }, reset: () => { stopAB(); R.flip = null; R.blind = null; R.ab = null; R.st = null; R.data = null; R.confirm = null; R.err = ''; } };
})();

/* Hypnomix · the review loop as a view: Scan → findings → A/B → Approve / Skip / Change →
   Apply approved writes ONE new snapshot beside the original (mirrors gtk2_ardour/hypnomix_panel.cc).
   On the mock session the scan and its findings are scripted. Connected to the engine inside the app, the view
   runs the real loop on the engine's session (HX.realReview, below; the server side is hypnomix/app/dawreview.py). */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  let root, cur = 0, editing = false, confirm = null, scanning = false;

  HX.mountReview = function () { root = HX.$('#viewReview'); render(); };
  const real = () => HX.mcp.connected && HX.api.inApp;

  const count = (st) => S.findings.filter((f) => (Array.isArray(st) ? st.includes(f.status) : f.status === st)).length;
  const barStr = (b) => 'bar ' + (Math.floor(b / 4) + 1) + (b % 4 ? '.' + (Math.floor(b % 4) + 1) : '');
  const trackOf = (f) => HX.track(f.track) || { name: '?', color: '#888' };

  /* finding → the ops it will make (only the ones the engine can do directly; the rest go through the bridge) */
  function fixOps(f, amount) {
    const t = HX.track(f.track); if (!t) return [];
    const x = f.fix;
    if (x.param === 'clipGain') {
      const c = t.clips.find((c) => c.name === x.clip); if (!c) return [];
      const base = c.gainDb;
      return [{ trackId: t.id, param: 'clipGain', key: c.id, before: base, after: Math.round((base + amount) * 10) / 10 }];
    }
    if (x.param === 'device') {
      const di = t.devices.findIndex((d) => d.name === x.device); if (di < 0) return [];
      const pi = t.devices[di].params.findIndex((p) => p.n === x.p); const p = t.devices[di].params[pi];
      const base = p.v;
      const after = x.p === 'Hi-Mid' ? base + amount : amount;
      return [{ trackId: t.id, param: 'devParam', key: [di, pi], before: base, after: Math.round(after * 100) / 100 }];
    }
    return [];
  }
  HX.fixOps = fixOps;
  function setAB(f, ab) {
    if (f.ab === ab) return;
    setABsilent(f, ab);
    HX.log('mock', 'A/B ' + ab + ' · ' + f.title + (f.fix.param === 'clipGain' || f.fix.param === 'device' ? '' : ' (bridge fix: evidence only)'));
    HX.emit('review', { what: 'ab', side: ab });
    render();
  }
  function leave(f) { if (f && f.ab === 'B') setAB(f, 'A'); editing = false; }

  function select(i) {
    if (!S.findings.length) return;
    const prev = S.findings[cur];
    i = HX.clamp(i, 0, S.findings.length - 1);
    if (i !== cur) leave(prev);
    cur = i;
    const f = S.findings[cur];
    HX.select(f.track);
    HX.locate(f.at); HX.scrollToBeat && HX.scrollToBeat(f.at);
    render();
    const row = root.querySelector('.rv-row.on'); row && row.scrollIntoView({ block: 'nearest' });
  }
  function decide(st) {
    const f = S.findings[cur]; if (!f) return;
    leave(f);
    f.status = f.status === st ? 'open' : st === 'approved' && f.fix.amount !== f.orig ? 'changed' : st;
    HX.emit('findings');
    if (f.status !== 'open') HX.emit('review', { what: 'decided', status: f.status });
    const next = S.findings.findIndex((g, k) => k > cur && g.status === 'open');
    if (next >= 0) select(next); else render();
  }

  /* ── scanning ── */
  HX.runScan = function (skipAsk) {
    if (real()) return RR.scan(skipAsk);
    HX.setView('review');
    if (!skipAsk) { confirm = 'scan'; render(); return; }
    confirm = null; scanning = true; S.findings = []; render();
    const stages = ['Saving session', 'Reading tracks and regions', 'Rendering stems (mock)', 'Vocal level, line to line', 'Harmony balance', 'Comp edges', 'Pitch, with chord check', 'Stack timing', 'Masking', 'Noise floor', 'True peak after AAC'];
    if (HX.mcp.connected) HX.mcp.save().catch(() => {}); else HX.log('mock', 'session_save {}');
    let k = 0;
    const tick = () => {
      const bar = root.querySelector('.scanbar i'), lab = root.querySelector('.scanstage');
      if (bar) bar.style.width = ((k / stages.length) * 100).toFixed(0) + '%';
      if (lab) lab.textContent = stages[Math.min(k, stages.length - 1)] + '…';
      if (k++ < stages.length) return setTimeout(tick, 170 + Math.random() * 140);
      scanning = false; S.scanned = true; cur = 0;
      /* the findings are scripted for the mock song; on a real session only those whose track exists survive (normally none) */
      S.findings = HX.makeFindings().filter((f) => HX.track(f.track));
      HX.log('mock', 'hypnomix scan → ' + S.findings.length + ' findings (scripted)');
      HX.emit('findings'); HX.emit('review', { what: 'scanned' }); if (S.findings.length) select(0); else render();
    };
    tick();
  };

  /* ── render ── */
  function render() {
    if (!root) return;
    if (real()) return RR.render(root);
    root.innerHTML = '';
    const nApp = count(['approved', 'changed']);
    const bar = h('div.rv-bar', null, h('span.t', null, 'Review'),
      S.findings.length ? h('div.stat', null, h('span', null, h('b', null, String(count('open'))), 'open'), h('span.a', null, h('b', null, String(count('approved'))), 'approved'), h('span.c', null, h('b', null, String(count('changed'))), 'changed'), h('span.s', null, h('b', null, String(count('skipped'))), 'skipped')) : h('span.stat', null, S.scanned ? 'No findings' : 'Not scanned yet'),
      h('div.right', null,
        h('button.btn', { onclick: () => HX.runScan(), 'data-info': 'Run the HypnoMix scan again (saves first, after asking)' }, S.scanned ? 'Rescan' : 'Scan'),
        h('button.btn.primary', { disabled: !nApp, onclick: () => { confirm = 'apply'; render(); }, 'data-info': 'Write the approved fixes into ONE new snapshot; the original stays untouched' }, 'Apply ' + nApp + ' → new snapshot')));
    root.append(bar);

    if (!S.findings.length) {
      const box = h('div.rv-empty');
      if (scanning) box.append(h('h3', null, 'Scanning'), h('div.scanbar', null, h('i')), h('span.scanstage', null, 'Starting…'));
      else if (confirm === 'scan') box.append(h('h3', null, 'Save and scan?'), h('p', null, 'The scan saves the session first, then listens to every track. Nothing in the session changes until you approve fixes and apply them to a new snapshot.'), h('div.rv-actions', null, h('button.btn.primary', { onclick: () => HX.runScan(true) }, 'Save and scan ', h('kbd', null, '⏎')), h('button.btn', { onclick: () => { confirm = null; render(); } }, 'Cancel')));
      else if (S.scanned && HX.mcp.connected) box.append(h('h3', null, 'No findings to show'), h('p', null, 'The session was saved. The findings in this view are scripted for the practice song, so they do not apply to this session. Scan a real session from Songs in the HypnoMix app.'));
      else box.append(h('h3', null, 'Find what needs fixing'), h('p', null, 'HypnoMix scans the mix the way an engineer would: vocal level line to line, harmonies over the melody, comp edges, pitch against the chord, stack timing, masking, noise and true peak after AAC.'), h('button.btn.ai', { onclick: () => HX.runScan() }, 'Scan session'));
      root.append(h('div', { style: { flex: 1, display: 'flex' } }, box));
      return;
    }

    const list = h('div.rv-list');
    S.findings.forEach((f, i) => {
      const t = trackOf(f);
      list.append(h('div.rv-row' + (i === cur ? '.on' : ''), { onclick: () => select(i) },
        h('span.n', null, String(i + 1).padStart(2, '0')), h('i.sev.' + f.sev),
        h('div.ti', null, h('b', null, f.title), h('small', null, f.fix.label + ' · ' + fmtAmt(f))),
        h('span.tk', null, h('i', { style: { background: t.color } }), t.name),
        h('span.at', null, barStr(f.at)),
        h('span.pill.' + f.status, null, f.status)));
    });
    const f = S.findings[cur], t = trackOf(f);
    const det = h('div.rv-detail');
    if (confirm === 'apply') {
      const n = count(['approved', 'changed']);
      det.append(h('div.rv-confirm', null, h('span', null, 'Write ' + n + ' approved fix' + (n > 1 ? 'es' : '') + ' to a new snapshot “' + nextSnap() + '”? ' + (HX.mcp.connected ? 'The engine switches to it; the original stays as the scan saved it.' : 'The original session is not touched.')),
        h('button.btn.primary', { onclick: apply }, 'Write snapshot ', h('kbd', null, '⏎')), h('button.btn', { onclick: () => { confirm = null; render(); } }, 'Cancel')));
    }
    if (confirm === 'open') {
      det.append(h('div.rv-confirm', null, h('span', null, 'Snapshot “' + S._lastSnap + '” written. Open it now?'),
        h('button.btn.primary', { onclick: openSnap }, 'Open snapshot'), h('button.btn', { onclick: () => { confirm = null; render(); } }, 'Stay here')));
    }
    det.append(h('h2', null, f.title),
      h('div.meta', null, h('span', null, 'Track ', h('b', null, t.name)), h('span', null, 'At ', h('b', null, barStr(f.at))), h('span', null, 'Check ', h('b', null, f.kind)), h('span', null, 'Severity ', h('b', null, f.sev)), h('span', null, 'Status ', h('b', null, f.status))),
      h('p', null, f.detail));
    const cv = h('canvas');
    det.append(cv);
    const ops = fixOps(f, f.fix.amount);
    const fx = h('div.rv-fix', null,
      h('div.fx', null, h('span.label', null, 'Proposed fix'), h('span.what', null, f.fix.label + '  ', h('span.mono', { style: { color: 'var(--ai)' } }, fmtAmt(f))), h('span.tool', null, ops.length ? 'via ' + f.fix.tool : 'via HypnoMix bridge → new snapshot')));
    if (editing) {
      const num = h('span.mono', { style: { color: 'var(--tx0)', minWidth: '64px' } }, fmtAmt(f));
      const rng = h('input', { type: 'range', min: f.fix.min, max: f.fix.max, step: f.fix.step, value: f.fix.amount, oninput: (e) => { const wasB = f.ab === 'B'; if (wasB) setABsilent(f, 'A'); f.fix.amount = +e.target.value; if (wasB) setABsilent(f, 'B'); num.textContent = fmtAmt(f); drawEvidence(cv, f); } });
      fx.append(h('div.fx', null, h('span.label', null, 'Amount'), rng, num, h('button.btn.ghost', { onclick: () => { f.fix.amount = f.orig; render(); } }, 'Reset'), h('span.tool', null, 'was ' + f.orig + ' ' + f.fix.unit)));
    }
    if (ops.length) fx.append(h('div.fx', null, h('span.tool', null, ops.map((o) => { const d = HX.describeOp(o); return d.tool + ' ' + JSON.stringify(d.args); }).join('   '))));
    det.append(fx);
    det.append(h('div.rv-actions', null,
      h('div.seg', { 'data-info': 'A = as it is, B = with the fix · B' }, h('button.a' + (f.ab === 'A' ? '.on' : ''), { onclick: () => setAB(f, 'A') }, 'A  original'), h('button.b' + (f.ab === 'B' ? '.on' : ''), { onclick: () => setAB(f, 'B') }, 'B  fixed')),
      h('button.btn', { onclick: () => { HX.locate(Math.max(0, f.at - 8)); HX.play(); }, 'data-info': 'Play from two bars before · P' }, '▶  Play here ', h('kbd', null, 'P')),
      h('span', { style: { flex: 1 } }),
      h('button.btn.primary', { onclick: () => decide('approved') }, 'Approve ', h('kbd', null, 'Y')),
      h('button.btn', { onclick: () => decide('skipped') }, 'Skip ', h('kbd', null, 'N')),
      h('button.btn' + (editing ? '.ai' : ''), { onclick: () => { editing = !editing; render(); } }, 'Change ', h('kbd', null, 'C'))));
    det.append(h('div.label', { style: { marginTop: 'auto' } }, 'J / K  next / previous · Y approve · N skip · C change amount · B A/B · P play here'));
    root.append(h('div.rv-split', null, list, det));
    requestAnimationFrame(() => drawEvidence(cv, f));
  }
  function setABsilent(f, ab) {
    if (ab === 'B') { f._ops = fixOps(f, f.fix.amount); f._ops.forEach((o) => HX.setLocal(o, o.after)); }
    else { (f._ops || []).forEach((o) => HX.setLocal(o, o.before)); f._ops = null; }
    f.ab = ab;
    HX.emit('preview');
  }
  function fmtAmt(f) { const a = f.fix.amount; return (a > 0 && f.fix.unit !== '%' && f.fix.param !== 'edge' && f.fix.param !== 'nudge' && f.fix.unit !== 'dBTP' ? '+' : '') + a + ' ' + f.fix.unit; }
  function nextSnap() { return S.session.name + ' — HypnoMix ' + (S.session.snapshots.filter((s) => /hypnomix/i.test(s.name)).length + 1); }

  function apply() {
    leave(S.findings[cur]);
    const name = nextSnap();
    const todo = S.findings.filter((f) => f.status === 'approved' || f.status === 'changed');
    S._pendingOps = todo.flatMap((f) => fixOps(f, f.fix.amount));
    S.session.snapshots.push({ name, when: 'just now', fixes: todo.length });
    S._lastSnap = name;
    todo.forEach((f) => (f.status = 'applied'));
    HX.log('mock', 'HypnoMix apply → snapshot "' + name + '" (' + todo.length + ' fixes, ' + S._pendingOps.length + ' engine edits, the rest via the bridge)' + (HX.mcp.connected ? ' · engine edits + session_save' : ''));
    HX.emit('review', { what: 'applied' });
    if (HX.mcp.connected) return writeLive(name);
    confirm = 'open';
    HX.emit('snapshots'); HX.emit('findings'); render();
  }
  /* Connected: the engine edits go in as one undo step, then session_save writes the new snapshot and
     switches to it, so the original file is left exactly as the scan saved it. HypnoMix CLI fixes (comp
     edges, tuning, stack nudges, dehiss) need hypnomix-bridge.sh and are not sent from here yet. */
  async function writeLive(name) {
    confirm = null; render();
    try {
      await HX.commit('Review fixes → ' + name, S._pendingOps || [], 'review');
      await HX.mcp.call('session_save', { snapshotName: name, switchToSnapshot: true });
      S.session.snapshots.forEach((s) => (s.current = false));
      const sn = S.session.snapshots.find((s) => s.name === name); sn.current = true; sn.when = 'current';
      HX.$('#sessionName').textContent = name;
      HX.toast('Wrote and opened ' + name);
    } catch (e) { HX.toast('Snapshot not written: ' + e.message, 4000); }
    HX.emit('snapshots'); render();
  }
  function openSnap() {
    // opening the snapshot = the session now carries the fixes; record it as one undoable step
    HX.commit('Open snapshot ' + S._lastSnap, S._pendingOps || [], 'review');
    S.session.snapshots.forEach((s) => (s.current = false));
    const sn = S.session.snapshots.find((s) => s.name === S._lastSnap); sn.current = true; sn.when = 'current';
    HX.$('#sessionName').textContent = S._lastSnap;
    confirm = null; HX.emit('snapshots'); render();
    HX.toast('Opened ' + S._lastSnap);
  }

  /* ── evidence plots (generated from the finding's seed; A vs B) ── */
  function drawEvidence(cv, f) {
    if (!cv.isConnected) return;
    const w = cv.clientWidth, hh = cv.clientHeight, ctx = HX.fitCanvas(cv, w, hh);
    const C = { g: HX.css('--grid2'), t3: HX.css('--tx3'), t1: HX.css('--tx1'), ai: HX.css('--ai'), acc: HX.css('--acc'), bad: HX.css('--bad'), ok: HX.css('--ok') };
    const B = f.ab === 'B', rnd = HX.rng(HX.hash(f.id)), a = f.fix.amount;
    const pad = 28, pw = w - pad - 8, ph = hh - 26;
    ctx.clearRect(0, 0, w, hh);
    ctx.font = '9.5px ' + HX.css('--mono'); ctx.fillStyle = C.t3; ctx.strokeStyle = C.g; ctx.lineWidth = 1;
    const yAt = (v, lo, hi) => 8 + (1 - (v - lo) / (hi - lo)) * ph;
    const axis = (lo, hi, ticks, unit) => ticks.forEach((v) => { const y = Math.round(yAt(v, lo, hi)) + 0.5; ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(w - 8, y); ctx.stroke(); ctx.fillText(v + (unit || ''), 2, y + 3); });
    const line = (pts, col, lw, dash) => { ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.strokeStyle = col; ctx.lineWidth = lw || 1.5; ctx.setLineDash(dash || []); ctx.stroke(); ctx.setLineDash([]); };
    const label = (txt, col, x, y) => { ctx.fillStyle = col; ctx.fillText(txt, x, y); };
    const fixCol = B ? C.ai : C.t1;
    const foot = (txt) => label(txt, C.t3, pad, hh - 6);

    if (f.ev === 'level' || f.ev === 'harmony') {
      const lo = -30, hi = -10; axis(lo, hi, [-12, -18, -24], '');
      const bars = f.ev === 'level' ? [9, 104] : [25, 40];
      const n = bars[1] - bars[0] + 1, X = (i) => pad + (i / (n - 1)) * pw;
      const lead = [], other = [];
      for (let i = 0; i < n; i++) {
        const bar = bars[0] + i;
        let v = -17 + Math.sin(i * 0.7) * 0.8 + (rnd() - 0.5) * 1.2;
        if (f.ev === 'level' && bar >= 49 && bar <= 56) v -= B ? 2.8 - a : 2.8;
        lead.push([X(i), yAt(v, lo, hi)]);
        if (f.ev === 'harmony') { let hv = v + 0.9 + (rnd() - 0.5) * 0.8; if (B) hv += a; other.push([X(i), yAt(hv, lo, hi)]); }
      }
      if (f.ev === 'level') { ctx.fillStyle = 'rgba(128,128,128,.12)'; ctx.fillRect(pad, yAt(-16, lo, hi), pw, yAt(-18, lo, hi) - yAt(-16, lo, hi)); ctx.fillStyle = C.ai; ctx.globalAlpha = 0.08; ctx.fillRect(X(40), 8, X(47) - X(40), ph); ctx.globalAlpha = 1; }
      line(lead, f.ev === 'level' ? fixCol : C.t1, 1.6);
      if (other.length) { line(other, fixCol, 1.6); line(lead.map(([x, y]) => [x, y + (1.5 / 20) * ph]), C.t3, 1, [3, 3]); label('Harmony 1', fixCol, w - 70, 18); label('lead', C.t1, w - 70, 30); label('−1.5 dB under lead', C.t3, w - 120, 42); }
      foot(f.ev === 'level' ? 'short-term level of the lead, bars 9–104 · band = song median ±1 dB' : 'short-term level, bars 25–40');
    } else if (f.ev === 'pitch') {
      const lo = -50, hi = 30; axis(lo, hi, [20, 0, -20, -40], 'c');
      ctx.fillStyle = 'rgba(128,128,128,.10)'; ctx.fillRect(pad, yAt(20, lo, hi), pw, yAt(-20, lo, hi) - yAt(20, lo, hi));
      const pts = []; const target = B ? -28 * (1 - a / 100) : -28;
      for (let i = 0; i <= 120; i++) { const x = pad + (i / 120) * pw; let c; if (i < 18) c = -45 + i * 1.0; else c = (i < 30 ? HX.lerp(-27, target, (i - 18) / 12) : target) + Math.sin(i * 0.5) * 6 + (rnd() - 0.5) * 2; if (i < 18) c = c; pts.push([x, yAt(c, lo, hi)]); }
      line(pts, fixCol, 1.6);
      label('A4 (chord tone of Am)', C.t3, pad + 4, yAt(0, lo, hi) - 4);
      foot('pitch in cents vs A4 · scoop kept · only the held part moves (' + (B ? Math.round(28 * a / 100) + ' c' : 'none') + ')');
    } else if (f.ev === 'spectrum' || f.ev === 'floor') {
      const lo = -72, hi = -6; axis(lo, hi, [-18, -36, -54], '');
      const fx = (x) => 20 * Math.pow(1000, (x - pad) / pw);
      const curve = (fn) => { const p = []; for (let x = pad; x <= w - 8; x += 2) p.push([x, yAt(fn(fx(x)), lo, hi)]); return p; };
      if (f.kind === 'mask') {
        const kick = (fr) => -20 - Math.pow(Math.log2(fr / 60), 2) * 6 - Math.max(0, Math.log2(fr / 200)) * 6;
        const bass = (fr) => -18 - Math.pow(Math.log2(fr / 80), 2) * 4 - Math.max(0, Math.log2(fr / 300)) * 9 - (B ? a * Math.exp(-Math.pow(Math.log2(fr / 72), 2) * 3) : 0);
        const x0 = pad + (Math.log10(60 / 20) / 3) * pw, x1 = pad + (Math.log10(90 / 20) / 3) * pw;
        ctx.fillStyle = C.bad; ctx.globalAlpha = B ? 0.05 : 0.12; ctx.fillRect(x0, 8, x1 - x0, ph); ctx.globalAlpha = 1;
        line(curve(kick), C.t1, 1.4); line(curve(bass), fixCol, 1.6);
        label('kick', C.t1, w - 60, 18); label('bass (on kick hits)', fixCol, w - 120, 30);
        foot('20 Hz – 20 kHz · shaded: 60–90 Hz overlap');
      } else if (f.kind === 'res') {
        const keys = (fr) => -24 - Math.abs(Math.log2(fr / 400)) * 5 + 9 * Math.exp(-Math.pow(Math.log2(fr / 3100) * 6, 2)) + (B ? a * Math.exp(-Math.pow(Math.log2(fr / 3100) * 3, 2)) : 0);
        const vox = (fr) => -30 - Math.abs(Math.log2(fr / 2500)) * 6;
        line(curve(vox), C.t3, 1, [3, 3]); line(curve(keys), fixCol, 1.6);
        label('keys', fixCol, w - 60, 18); label('lead presence', C.t3, w - 90, 30);
        foot('20 Hz – 20 kHz · narrow ring at 3.1 kHz');
      } else {
        const floor = (fr) => -58 - Math.log2(fr / 1000) * 1.5 - (B ? a : 0) + (rnd() - 0.5) * 1.5;
        line(curve(floor), fixCol, 1.4);
        ctx.strokeStyle = C.t3; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(pad, yAt(-62, lo, hi)); ctx.lineTo(w - 8, yAt(-62, lo, hi)); ctx.stroke(); ctx.setLineDash([]);
        label('audible threshold in the intro', C.t3, pad + 4, yAt(-62, lo, hi) - 4);
        foot('noise floor spectrum, bars 1–8 (gaps between strums)');
      }
    } else if (f.ev === 'timing') {
      const lo = -20, hi = 50; axis(lo, hi, [40, 20, 0], ' ms');
      const n = 9, X = (i) => pad + 20 + (i / (n - 1)) * (pw - 40);
      for (let i = 0; i < n; i++) {
        const late = [38, 42, 35, 6, 40, 31, 4, 44, 8][i];
        const v = B && late > 20 ? late - a : late;
        ctx.fillStyle = late > 20 ? fixCol : C.t3;
        ctx.beginPath(); ctx.arc(X(i), yAt(v, lo, hi), 3.5, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = C.t3; ctx.fillText('p' + (i + 1), X(i) - 6, hh - 18 + 0);
      }
      ctx.strokeStyle = C.ok; ctx.beginPath(); ctx.moveTo(pad, yAt(0, lo, hi)); ctx.lineTo(w - 8, yAt(0, lo, hi)); ctx.stroke();
      label('group mean onset', C.ok, w - 110, yAt(0, lo, hi) - 4);
      foot('Harmony 2 onset vs stack mean, per phrase · nudges halfway, never onto the lead');
    } else if (f.ev === 'edge') {
      const lo = -1, hi = 1, mid = yAt(0, lo, hi);
      ctx.strokeStyle = C.g; ctx.beginPath(); ctx.moveTo(pad, mid); ctx.lineTo(w - 8, mid); ctx.stroke();
      const on = pad + pw * 0.3, edge = on + (B ? 14 - a : 14) * (pw / 120);
      ctx.fillStyle = C.t1;
      for (let x = pad; x < w - 8; x++) { const t = x - on; let amp = 0; if (t > 0) amp = t < 40 ? 0.25 * (0.6 + rnd() * 0.4) : Math.min(0.9, 0.25 + (t - 40) / 60) * (0.7 + rnd() * 0.3); const cut = x < edge ? 0.12 : 1; ctx.globalAlpha = x < edge ? 0.35 : 1; const hgt = amp * cut * (ph / 2); ctx.fillRect(x, mid - hgt, 1, hgt * 2 || 1); }
      ctx.globalAlpha = 1;
      ctx.fillStyle = fixCol; ctx.fillRect(Math.round(edge), 8, 1.5, ph);
      label('clip start + fade', fixCol, edge + 4, 18);
      ctx.fillStyle = C.bad; ctx.fillRect(Math.round(on), 8, 1, ph); label('“s” onset', C.bad, on - 50, 30);
      foot('120 ms around bar 33 · the edge moves on your comp; nothing is re-rendered');
    } else if (f.ev === 'peak') {
      const lo = -4, hi = 2; axis(lo, hi, [1, 0, -1, -2, -3], '');
      ctx.strokeStyle = C.bad; ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.moveTo(pad, yAt(-1, lo, hi)); ctx.lineTo(w - 8, yAt(-1, lo, hi)); ctx.stroke(); ctx.setLineDash([]);
      const pts = []; const off = B ? (a - -0.3) : 0;
      for (let i = 0; i <= 160; i++) { const v = -2.2 + Math.abs(Math.sin(i * 0.21)) * 1.6 + (i > 60 && i < 120 ? 1.3 : 0) + (rnd() - 0.5) * 0.4 + off; pts.push([pad + (i / 160) * pw, yAt(Math.min(1.9, v), lo, hi)]); }
      line(pts, fixCol, 1.4);
      label('−1 dBTP', C.bad, w - 52, yAt(-1, lo, hi) - 4);
      foot('true peak of the AAC 256k decode, bars 73–104');
    }
    label(B ? 'B · with fix' : 'A · original', B ? C.ai : C.t3, w - 80, hh - 6);
  }

  /* keys while the Review view is up */
  document.addEventListener('keydown', (e) => {
    if (S.ui.view !== 'review' || e.metaKey || e.ctrlKey || e.altKey) return;
    if (HX.modalOpen() || (HX.noEngineScreen && HX.noEngineScreen()) || e.repeat) return;   // dead behind a dialog, the shortcuts list, the engine panel or the no-engine screen
    if (/INPUT|TEXTAREA/.test(document.activeElement.tagName)) return;
    if (real()) return RR.key(e);
    const k = e.key.toLowerCase();
    if (e.key === 'Enter' && confirm === 'scan') { e.preventDefault(); return HX.runScan(true); }
    if (e.key === 'Enter' && confirm === 'apply') { e.preventDefault(); return apply(); }
    if (e.key === 'Escape' && confirm) { confirm = null; return render(); }
    if (!S.findings.length) return;
    const map = { j: () => select(cur + 1), arrowdown: () => select(cur + 1), k: () => select(cur - 1), arrowup: () => select(cur - 1), y: () => decide('approved'), n: () => decide('skipped'), c: () => { editing = !editing; render(); }, b: () => setAB(S.findings[cur], S.findings[cur].ab === 'A' ? 'B' : 'A'), p: () => { const f = S.findings[cur]; HX.locate(Math.max(0, f.at - 8)); HX.play(); } };
    if (map[k]) { e.preventDefault(); e.stopImmediatePropagation(); map[k](); }
  }, true);

  HX.on('findings', () => { const b = HX.$('#reviewBadge'); if (b) b.textContent = S.findings.filter((f) => f.status === 'open').length || ''; });
  HX.on('view', (v) => { if (real()) { if (v === 'review') RR.refresh(); else RR.leave(); return; } if (v !== 'review' && S.findings[cur]) leave(S.findings[cur]); if (v === 'review') render(); });
  HX.on('session', () => { cur = 0; confirm = null; if (real()) RR.refresh(true); else { RR.reset(); render(); } });
  HX.on('theme', () => render());
  HX.reviewSelect = (i) => (real() ? RR.select(i) : select(i));
  const RR = HX.realReview;
})();
