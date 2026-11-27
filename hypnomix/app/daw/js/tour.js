/* HypnoMix Studio · the guided tours' engine. The tours themselves are data (js/tours.js).

   What it does: offers a tour the first time (never taking focus), lists the tours behind the Tour button, and runs one
   step by step on the real screen: a soft spotlight on ONE real control and a small card beside it. A step may wait for the
   person to do the thing (it listens to the page's own events); "Next" is always there as "I'll do it later".

   What it never does: change the session, send an engine command, or click for the person. The only thing it moves by
   itself is the view (Arrange, Mixer, Review), and it says so on the card.

   Progress (which tours are done, the step a tour was left at, the answer to the first offer) is kept in this browser
   (localStorage "hx.tour") and, inside the app, on its server (POST /api/teach/tour, with the page's token like every other
   call). The tour that is open is remembered in this browser only: a reload carries on where it was. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  const D = HX.TOURS;
  const KEY = 'hx.tour';
  const NARROW = 700;                                   // at or under this width the card docks to the bottom
  const VIEWS = { arrange: 'Arrange', session: 'Session', mixer: 'Mixer', review: 'Review' };

  const tourById = (id) => D.tours.find((t) => t.id === id) || null;
  const MAC = /Mac|iPhone|iPad/i.test((typeof navigator !== 'undefined' && (navigator.platform || navigator.userAgent)) || '');
  const MOD = MAC ? '⌘' : 'Ctrl+';
  const say = (s) => String(s).replace(/\{mod\}/g, MOD);
  const plain = (s) => say(s).replace(/\*\*/g, '');
  const fill = (s, o) => String(s).replace(/\{(\w+)\}/g, (m, k) => (o && k in o ? o[k] : m));
  /* **bold** and {mod} to nodes: text only, never markup */
  function rich(text) {
    const out = [];
    say(text).split('**').forEach((part, i) => { if (part) out.push(i % 2 ? h('b', null, part) : part); });
    return out;
  }

  /* ───────────────────────────── progress ───────────────────────────── */
  let P = sane(null);
  function sane(j) {
    const o = { offered: '', done: [], at: {}, active: '' };
    if (!j || typeof j !== 'object') return o;
    if (j.offered === 'accepted' || j.offered === 'declined') o.offered = j.offered;
    if (Array.isArray(j.done)) j.done.forEach((x) => { if (typeof x === 'string' && tourById(x) && !o.done.includes(x)) o.done.push(x); });
    if (j.at && typeof j.at === 'object') Object.keys(j.at).forEach((k) => { const n = j.at[k]; if (tourById(k) && Number.isInteger(n) && n >= 0 && n < 99) o.at[k] = n; });
    if (typeof j.active === 'string' && tourById(j.active)) o.active = j.active;
    return o;
  }
  function readLocal() { try { return sane(JSON.parse(localStorage.getItem(KEY))); } catch (e) { return sane(null); } }
  function writeLocal() { try { localStorage.setItem(KEY, JSON.stringify(P)); } catch (e) { /* private window or blocked storage: this visit still works */ } }
  let syncT = 0;
  function persist(now) { writeLocal(); clearTimeout(syncT); if (now) pushServer(); else syncT = setTimeout(pushServer, 600); }   // an answer goes at once (a page that is left would lose a delayed one)
  function pushServer() {
    if (!(HX.api && HX.api.inApp)) return Promise.resolve(false);
    return HX.api.post('/api/teach/tour', { offered: P.offered, done: P.done, at: P.at }).then(() => true, () => false);
  }
  function merge(s) {                                   // the server's copy joins this browser's: nothing answered is lost
    if (!P.offered) P.offered = s.offered;
    s.done.forEach((x) => { if (!P.done.includes(x)) P.done.push(x); });
    Object.keys(s.at).forEach((k) => { if (!(k in P.at) && !P.done.includes(k)) P.at[k] = s.at[k]; });
    writeLocal();
  }
  function pullServer() {
    if (!(HX.api && HX.api.inApp)) return Promise.resolve(false);
    return HX.api.get('/api/teach/tour').then((s) => {
      const srv = sane(s), same = srv.offered === P.offered && srv.done.join() === P.done.join();
      merge(srv);
      if (!same && (P.offered !== srv.offered || P.done.length > srv.done.length)) pushServer();     // this browser knew more: the server learns it
      return true;
    }, () => false);
  }

  /* ───────────────────────────── what a step can wait for ─────────────────────────────
     name → { events: which page events to listen to, state: true when it also counts if it is already so when the step
     begins, start(): a snapshot taken when the step begins, test(data, snapshot): did the person do it }. */
  const edit = (...params) => ({ events: ['edit'], test: (entry) => !!(entry && entry.ops && entry.ops.some((o) => params.includes(o.param))) });
  const devCount = () => HX.allTracks().reduce((n, t) => n + t.devices.length, 0);
  const review = (what) => ({ events: ['review'], test: (d) => !!d && d.what === what });
  const assistant = (what) => ({ events: ['assistant'], test: (d) => !!d && d.what === what });
  const CHECKS = {
    'play': { events: ['transport'], state: true, test: () => !!HX.T.playing },
    'view-mixer': { events: ['view'], state: true, test: () => S.ui.view === 'mixer' },
    'view-review': { events: ['view'], state: true, test: () => S.ui.view === 'review' },
    'select-region': { events: ['select'], test: () => !!S.ui.clipId },
    'move-region': edit('regionMove'),
    'trim-region': edit('regionTrim'),
    'split-region': edit('regionSplit'),
    'fade-region': edit('regionFades'),
    'undo': { events: ['undone'], test: () => true },
    'fader': edit('fader'),
    'pan': edit('pan'),
    'mute-solo': edit('mute', 'solo'),
    'send': edit('send'),
    'device-knob': edit('devParam'),
    'add-device': { events: ['devices', 'session', 'session-light', 'edit'], start: devCount, test: (d, was) => devCount() > was },
    'saved': { events: ['saved'], test: () => true },
    'review-scanned': review('scanned'),
    /* both sides, one after the other (the song starts on A, so B and then A): one press is not "you heard both" */
    'review-ab': { events: ['review'], start: () => ({ A: false, B: false }), test: (d, was) => { if (d && d.what === 'ab' && was && (d.side === 'A' || d.side === 'B')) was[d.side] = true; return !!(was && was.A && was.B); } },
    'review-decided': review('decided'),
    'review-applied': review('applied'),
    'assistant-asked': assistant('asked'),
    'assistant-card': assistant('card'),
    'assistant-hear': assistant('hear'),
    'assistant-answered': assistant('answered'),
  };

  /* ───────────────────────────── where a step points ───────────────────────────── */
  const env = {
    find(sel) { try { return document.querySelector(sel); } catch (e) { return null; } },
    visible(el) {
      try {
        if (!el || !el.getBoundingClientRect || !el.getClientRects().length) return false;
        const b = el.getBoundingClientRect();
        if (b.width < 4 || b.height < 4) return false;          // squeezed to nothing (a name with no room) is not something to point at
        const cs = getComputedStyle(el);
        return cs.visibility !== 'hidden' && cs.display !== 'none';
      } catch (e) { return false; }
    },
    /* the box of the control, cut to what its scrolling parents show (a tall track list in a short pane lights only what is in view) */
    rect(el) {
      const r = el.getBoundingClientRect();
      let o = { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
      try {
        for (let p = el.parentElement; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
          const cs = getComputedStyle(p);
          if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
          const b = p.getBoundingClientRect();
          const c = { left: Math.max(o.left, b.left), top: Math.max(o.top, b.top), right: Math.min(o.right, b.right), bottom: Math.min(o.bottom, b.bottom) };
          if (c.right - c.left < 2 || c.bottom - c.top < 2) break;      // scrolled right out of view: keep the whole box, so it can be scrolled to
          o = c;
        }
      } catch (e) { /* the plain box */ }
      o.width = o.right - o.left; o.height = o.bottom - o.top;
      return o;
    },
  };
  /* named ways to find a part of a control: the selected region (or the first audio region) in the timeline's canvas */
  const RESOLVERS = {
    clip(lanes) {
      if (!S.session) return null;
      let f = S.ui.clipId && HX.findClip(S.ui.clipId);
      if (!f) {
        const sel = HX.track(S.ui.trackId);
        const pick = (t) => t && t.clips.find((c) => c.kind === 'audio' && c.len >= 4) || t && t.clips[0];
        const t = [sel, ...S.session.tracks].find((t) => t && pick(t));
        f = t ? { track: t, clip: pick(t) } : null;
      }
      if (!f) return null;
      let y = 0, hit = null;
      for (const t of S.session.tracks) { if (t === f.track) hit = y; y += t.height; }
      y += 6;                                           // the gap before the returns (js/arrange.js GAP)
      for (const t of [...S.session.returns, S.session.master]) { if (t === f.track) hit = y; y += t.height; }
      if (hit == null) return null;
      const r = env.rect(lanes), c = f.clip;
      const x0 = r.left + (c.start - S.ui.scrollX) * S.ui.zoom, x1 = r.left + (c.start + c.len - S.ui.scrollX) * S.ui.zoom;
      const out = { left: Math.max(x0, r.left), right: Math.min(x1, r.right), top: r.top + hit + 1, bottom: r.top + hit + f.track.height - 1 };
      const body = lanes.parentElement && lanes.closest && lanes.closest('.arr-body');
      if (body) { const b = env.rect(body); out.top = Math.max(out.top, b.top); out.bottom = Math.min(out.bottom, b.bottom); }
      if (out.right - out.left < 6 || out.bottom - out.top < 6) return null;
      out.width = out.right - out.left; out.height = out.bottom - out.top;
      return out;
    },
  };
  function resolveKey(key) {
    const t = D.targets[key]; if (!t) return null;
    const el = env.find(t.sel);
    if (!el || !env.visible(el)) return null;
    const rect = t.resolver ? RESOLVERS[t.resolver](el) : env.rect(el);
    return rect ? { key, el, rect } : null;
  }
  const keysOf = (step) => (step.target ? [].concat(step.target) : []);
  /* once a step is done it may point at what the person's action made (`then`): the findings after a scan */
  const keysNow = (step) => (C.status === 'done' && step.then ? [].concat(step.then) : keysOf(step));
  const sayOf = (step) => (HX.mode === 'demo' && step.demoSay ? step.demoSay : step.say);

  /* ───────────────────────────── the running tour ───────────────────────────── */
  const C = { tour: null, i: 0, status: '', note: '', before: null, offs: [], start: undefined, target: null, sig: '', viewDone: false, scrolled: false, listening: false };
  let silent = false;                                    // the engine stopped answering (js/live.js says so)
  let ui = null;                                         // the screen part (below); tests put a recorder here

  function pauseReason() {
    if (HX.mode === 'noengine') return 'nosession';
    if (HX.engineLost || silent) return 'lost';
    return '';
  }
  const cur = () => C.tour && C.tour.steps[C.i];

  function resolve(pause) {
    const step = cur();
    if (pause === 'nosession') { const g = resolveKey('gate'); return g ? { kind: 'paused', rect: g.rect, el: g.el } : { kind: 'paused', rect: null, el: null }; }
    if (pause === 'lost') { const g = resolveKey('engine'); return g ? { kind: 'paused', rect: g.rect, el: g.el } : { kind: 'paused', rect: null, el: null }; }
    if (!keysOf(step).length) return { kind: 'none', rect: null, el: null };
    for (const k of keysNow(step)) { const r = resolveKey(k); if (r) return { kind: 'ok', rect: r.rect, el: r.el, key: k }; }
    return { kind: 'missing', rect: null, el: null };
  }

  function disarm() { C.offs.forEach((f) => f()); C.offs = []; }
  function arm(step) {
    disarm();
    const ck = step.wait && CHECKS[step.wait];
    if (!ck) return;
    C.start = ck.start ? ck.start() : undefined;
    ck.events.forEach((ev) => C.offs.push(HX.on(ev, (data) => {
      if (C.status !== 'waiting' || pauseReason()) return;
      let ok = false;
      try { ok = ck.test(data, C.start); } catch (e) { ok = false; }
      if (ok) satisfy();
    })));
  }
  function satisfy() {
    if (C.status !== 'waiting') return;
    C.status = 'done';
    announce(plain(cur().done || D.ui.done));
    refresh(true);
  }
  /* a check that is about the state of the page (the mixer is open, it is playing) counts if it is already so */
  function recheck(pause) {
    const step = cur(), ck = step && step.wait && CHECKS[step.wait];
    if (C.status !== 'waiting' || pause || !ck || !ck.state) return;
    let ok = false;
    try { ok = ck.test(null, C.start); } catch (e) { ok = false; }
    if (ok) satisfy();
  }

  function model(pause, t) {
    const step = cur(), n = C.tour.steps.length;
    let note = C.note;
    if (pause) note = D.ui[pause];
    else if (C.status === 'done') note = '';              // the step is done: the "switched to" and "cannot find it" notes are stale
    else if (step.busy && t.key === step.busy) note = D.ui.busy;       // what it waits for is running (a scan)
    else if (t.kind === 'missing') {
      note = step.missing ? say(step.missing) : '';
      if (step.view && S.ui.view !== step.view) note += ' ' + fill(D.ui.openView, { view: VIEWS[step.view] });
    } else if (t.kind === 'none') note = step.reason ? '' : note;
    const status = pause ? 'paused' : C.status;
    return {
      tourId: C.tour.id, tourTitle: C.tour.title, i: C.i, n,
      title: pause ? D.ui.paused : step.title, say: pause ? [] : sayOf(step), demo: HX.mode === 'demo', doing: !pause && step.wait ? step.doing || '' : '', doneText: step.done || D.ui.done,
      status, pause, kind: t.kind, note: note ? say(note) : '',
      canBack: C.i > 0 && !pause, canNext: !pause, last: C.i === n - 1,
      nextLabel: C.i === n - 1 ? D.ui.finish : status === 'waiting' ? D.ui.later : D.ui.next,
    };
  }

  function refresh(force) {
    if (!C.tour) return;
    const pause = pauseReason();
    if (!pause && !C.viewDone) {                         // the view this step lives in, once, and the card says so
      C.viewDone = true;
      const step = cur();
      if (step.view && S.ui.view !== step.view) { HX.setView(step.view); C.note = fill(D.ui.switched, { view: VIEWS[step.view] }); }
    }
    let t = resolve(pause);
    if (t.kind === 'ok' && !C.scrolled) {                // a strip or a device out of sight is brought into view, once
      C.scrolled = true;
      try { if (t.el.scrollIntoView && t.key !== 'region') { t.el.scrollIntoView({ block: 'nearest', inline: 'nearest' }); t = resolve(pause); } } catch (e) { /* no scrolling: it stays where it is */ }
    }
    recheck(pause);
    const m = model(pause, t);
    const r = t.rect;
    const sig = [C.i, m.status, m.kind, m.note, r ? [r.left, r.top, r.width, r.height].map(Math.round).join(',') : '-', m.nextLabel].join('|');
    if (!force && sig === C.sig) return;
    C.sig = sig; C.target = t;
    ui.render(m, t);
  }

  function go(i, spoken) {
    const tour = C.tour, step = tour.steps[i];
    C.i = i; C.note = ''; C.viewDone = false; C.scrolled = false; C.sig = '';
    C.status = step.wait ? 'waiting' : 'ready';
    P.at[tour.id] = i; P.active = tour.id; persist();
    arm(step);
    refresh(true);
    announce(spoken || fill(D.ui.step, { i: i + 1, n: tour.steps.length }) + '. ' + step.title + '. ' + sayOf(step).map(plain).join(' ') + (step.wait && step.doing ? ' ' + plain(step.doing) : ''));
  }
  function start(id, o) {
    const tour = tourById(id);
    if (!tour) return false;
    const prior = listEl ? listBefore : (typeof document !== 'undefined' && document.activeElement) || null;
    closeList(); hideOffer();
    if (C.tour) disarm(); else C.before = prior;
    if (!P.offered) P.offered = 'accepted';               // someone who opens a tour has answered the offer
    C.tour = tour;
    const n = tour.steps.length;
    const i = o && Number.isInteger(o.at) && o.at > 0 && o.at < n ? o.at : 0;
    P.active = id; if (!(o && o.at > 0)) delete P.at[id];
    ui.open();
    listen(true);
    go(i, o && o.resumed ? fill(D.ui.resumed, { title: tour.title, i: i + 1 }) : '');
    return true;
  }
  function next() { if (!C.tour || pauseReason()) return; if (C.i >= C.tour.steps.length - 1) finish(); else go(C.i + 1); }
  function back() { if (!C.tour || pauseReason() || C.i <= 0) return; go(C.i - 1); }
  function finish() {
    const t = C.tour;
    if (!P.done.includes(t.id)) P.done.push(t.id);
    delete P.at[t.id];
    end('finished');
    if (HX.toast) HX.toast(fill(D.ui.finished, { title: t.title }), 4200);
    announce(fill(D.ui.finished, { title: t.title }));
  }
  /* why: 'finished' | 'skipped' | 'escape' | 'closed' */
  function end(why) {
    if (!C.tour) return;
    const t = C.tour;
    disarm(); listen(false);
    P.active = '';
    if (why !== 'finished' && C.i === 0) delete P.at[t.id];       // left on the first step: nothing to carry on from
    else if (why !== 'finished' && C.i >= t.steps.length - 1) { if (!P.done.includes(t.id)) P.done.push(t.id); delete P.at[t.id]; }   // left on the closing step: it was seen to the end
    persist(true);
    C.tour = null; C.sig = ''; C.target = null;
    const before = C.before; C.before = null;
    ui.close();
    try { if (before && before.focus && (!document.contains || document.contains(before))) before.focus({ preventScroll: true }); } catch (e) { /* the control is gone */ }
  }

  /* things that can change what the card shows */
  let schedT = 0;
  function schedule() { if (schedT) return; const run = () => { schedT = 0; refresh(false); }; schedT = typeof requestAnimationFrame === 'function' ? requestAnimationFrame(run) : setTimeout(run, 16); }
  const onResize = () => { C.scrolled = false; schedule(); };   // a new window size may push the target out of sight: bring it back
  let pollT = 0, ro = null;
  const evs = ['mode', 'live', 'engine-app', 'view', 'session', 'session-light', 'select', 'bottom', 'devices', 'findings', 'snapshots', 'preview', 'theme', 'transport'];
  function listen(on) {
    if (on === C.listening) return;
    C.listening = on;
    if (on) {
      C.evOff = evs.map((e) => HX.on(e, schedule));
      C.evOff.push(HX.on('engine', (st) => { silent = st === 'lost'; schedule(); }));
      if (typeof window.addEventListener === 'function') { window.addEventListener('resize', onResize); window.addEventListener('scroll', schedule, true); }
      pollT = setInterval(() => refresh(false), 500);
    } else {
      (C.evOff || []).forEach((f) => f()); C.evOff = [];
      if (typeof window.removeEventListener === 'function') { window.removeEventListener('resize', onResize); window.removeEventListener('scroll', schedule, true); }
      clearInterval(pollT); pollT = 0;
      if (ro) { ro.disconnect(); ro = null; }
    }
  }

  let liveEl = null, liveT = 0;
  function announce(text) {
    if (!liveEl || !text) return;
    liveEl.textContent = '';
    clearTimeout(liveT);
    liveT = setTimeout(() => { liveEl.textContent = text; }, 80);
  }

  /* ───────────────────────────── the keyboard ───────────────────────────── */
  const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
  function focusables(root) {
    if (!root) return [];
    const out = [];
    if (root.matches && root.matches(FOCUSABLE)) out.push(root);
    root.querySelectorAll(FOCUSABLE).forEach((e) => { if (!e.disabled && env.visible(e) && !e.closest('[inert]')) out.push(e); });
    return out.filter((e) => !e.disabled && !e.closest('[inert]') && env.visible(e));
  }
  function trap(e, extra) {
    const set = [...focusables(ui.cardEl()), ...focusables(extra)];
    if (!set.length) return;
    const i = set.indexOf(document.activeElement);
    const to = e.shiftKey ? (i <= 0 ? set[set.length - 1] : set[i - 1]) : (i < 0 || i >= set.length - 1 ? set[0] : set[i + 1]);
    e.preventDefault(); to.focus();
  }
  const typing = () => { const a = document.activeElement; return !!a && (/INPUT|TEXTAREA|SELECT/.test(a.tagName) || a.isContentEditable); };
  function onKey(e) {
    if (!C.tour || listEl) return;
    const card = ui.cardEl(), inCard = !!card && card.contains(e.target);
    if (e.key === 'Escape') {
      if (!inCard && (typing() || (HX.modalOpen && HX.modalOpen()))) return;   // the field, the dialog or the panel that has the keyboard keeps its Escape
      e.preventDefault(); e.stopPropagation(); end('escape'); return;
    }
    if (e.key === 'Tab') { trap(e, C.target && C.target.el); return; }
    if (!inCard) return;                                 // out in the DAW its own shortcuts work, on the highlighted control too
    const st = cur();
    if ((e.metaKey || e.ctrlKey) && !e.altKey && st && st.chords && st.chords.includes(String(e.key).toLowerCase())) return;   // the one shortcut this step asks for ({mod}Z) reaches the DAW from the card
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); e.stopPropagation(); next(); return; }
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); back(); return; }
    e.stopPropagation();                                 // a key typed in the card never reaches a DAW shortcut (Enter and Space still press the focused button)
  }

  /* ───────────────────────────── the screen part ───────────────────────────── */
  let spotEl = null, cardEls = null, offerEl = null, listEl = null, listBefore = null;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  function mountLive() {
    if (liveEl) return;
    liveEl = h('div#tourLive.tour-sr', { role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true' });
    document.body.append(liveEl);
  }
  function buildCard() {
    const e = {};
    e.name = h('span.tour-name');
    e.count = h('span.tour-count');
    e.x = h('button.tour-x', { type: 'button', 'aria-label': D.ui.close, 'data-info': D.ui.close, onclick: () => end('closed') }, '×');
    e.title = h('h3.tour-title#tourTitle');
    e.say = h('div.tour-say#tourSay');
    e.doing = h('p.tour-doing');
    e.note = h('p.tour-note');
    e.back = h('button.btn.tour-back', { type: 'button', onclick: back }, D.ui.back);
    e.next = h('button.btn.primary.tour-next', { type: 'button', onclick: next }, D.ui.next);
    e.skip = h('button.btn.ghost.tour-skip', { type: 'button', onclick: () => end('skipped') }, D.ui.skip);
    e.el = h('section.tour-card', { role: 'dialog', 'aria-labelledby': 'tourTitle', 'aria-describedby': 'tourSay', tabindex: '-1' },
      h('div.tour-top', null, e.name, e.count, e.x), e.title, e.say, e.doing, e.note,
      h('div.tour-btns', null, e.back, e.next, e.skip));
    return e;
  }
  const domUI = {
    open() {
      mountLive();
      if (!spotEl) { spotEl = h('div.tour-spot', { 'aria-hidden': 'true' }); document.body.append(spotEl); }
      if (!cardEls) { cardEls = buildCard(); document.body.append(cardEls.el); }
      cardEls.el.hidden = false; spotEl.hidden = true; cardEls.el.dataset.step = ''; cardEls.say.dataset.k = ''; cardEls.wantFocus = true;
      document.addEventListener('keydown', onKey, true);
      document.body.classList.add('tour-on');
    },
    close() {
      document.removeEventListener('keydown', onKey, true);
      document.body.classList.remove('tour-on');
      if (cardEls) cardEls.el.hidden = true;
      if (spotEl) spotEl.hidden = true;
      if (ro) { ro.disconnect(); ro = null; }
    },
    cardEl() { return cardEls ? cardEls.el : null; },
    render(m, t) {
      const e = cardEls, key = m.tourId + ':' + m.i;
      const had = e.el.contains(document.activeElement);
      e.name.textContent = m.tourTitle;
      e.count.textContent = fill(D.ui.step, { i: m.i + 1, n: m.n });
      e.title.textContent = m.title;
      const sk = key + m.pause + (m.demo ? 'd' : '');
      if (e.say.dataset.k !== sk) { e.say.replaceChildren(...m.say.map((p) => h('p', null, ...rich(p)))); e.say.dataset.k = sk; }
      e.el.dataset.status = m.status;
      const doing = m.doing && m.status !== 'done' ? [h('b', null, '\u25b8 '), ...rich(m.doing)] : m.status === 'done' && m.doing ? [h('b', null, '\u2713 '), ...rich(m.doneText)] : [];
      e.doing.replaceChildren(...doing); e.doing.hidden = !doing.length;
      e.note.textContent = m.note; e.note.hidden = !m.note;
      e.note.classList.toggle('warn', !!m.pause || m.kind === 'missing');
      e.back.disabled = !m.canBack; e.back.hidden = m.i === 0;
      e.next.disabled = !m.canNext; e.next.textContent = m.nextLabel;
      e.next.classList.toggle('later', m.status === 'waiting');
      this.place(t);
      /* the keyboard stays in the card: on the first step, and when a button it was on is switched off */
      if (e.wantFocus || (had && !e.el.contains(document.activeElement))) {
        e.wantFocus = false;
        const b = [e.next, e.skip].find((x) => !x.disabled && !x.hidden);
        try { if (b) b.focus({ preventScroll: true }); } catch (x) { /* hidden */ }
      }
      if (t.el && typeof ResizeObserver === 'function') { if (!ro) ro = new ResizeObserver(schedule); ro.disconnect(); ro.observe(t.el); }
    },
    place(t) {
      const card = cardEls.el, r = t && t.rect;
      const vw = window.innerWidth, vh = window.innerHeight;
      if (r) {
        const pad = 4, big = r.width * r.height > vw * vh * 0.55;
        spotEl.hidden = false; spotEl.classList.toggle('flat', big);
        spotEl.style.left = Math.round(r.left - pad) + 'px'; spotEl.style.top = Math.round(r.top - pad) + 'px';
        spotEl.style.width = Math.round(r.width + pad * 2) + 'px'; spotEl.style.height = Math.round(r.height + pad * 2) + 'px';
      } else spotEl.hidden = true;
      if (vw <= NARROW) {
        card.classList.add('dock'); card.style.left = ''; card.style.top = '';
        const ch = card.offsetHeight || 220;             // docked at the bottom, unless that would cover the target and there is room above it
        card.classList.toggle('top', !!(r && r.bottom > vh - ch - 16 && r.top >= ch + 16));
        return;
      }
      card.classList.remove('top');
      card.classList.remove('dock');
      const cw = Math.min(card.offsetWidth || 340, vw - 20), ch = card.offsetHeight || 230, g = 14, m = 10;
      let x, y;
      if (!r) { x = (vw - cw) / 2; y = Math.max(m, (vh - ch) / 3); }
      else {
        const room = { right: vw - r.right - m, left: r.left - m, below: vh - r.bottom - m, above: r.top - m };
        const fits = { right: room.right >= cw + g, left: room.left >= cw + g, below: room.below >= ch + g, above: room.above >= ch + g };
        const side = (r.width > vw * 0.5 ? ['below', 'above', 'right', 'left'] : ['right', 'left', 'below', 'above']).find((s) => fits[s]);
        const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
        if (side === 'right') { x = r.right + g; y = cy - ch / 2; }
        else if (side === 'left') { x = r.left - g - cw; y = cy - ch / 2; }
        else if (side === 'below') { y = r.bottom + g; x = cx - cw / 2; }
        else if (side === 'above') { y = r.top - g - ch; x = cx - cw / 2; }
        else { x = cx < vw / 2 ? vw - cw - m : m; y = cy < vh / 2 ? vh - ch - m : m; }   // no room beside it: the corner farthest from it
      }
      card.style.left = Math.round(clamp(x, m, vw - cw - m)) + 'px';
      card.style.top = Math.round(clamp(y, m, vh - ch - m)) + 'px';
    },
  };
  ui = domUI;

  /* ───────────────────────────── the first offer ───────────────────────────── */
  function showOffer() {
    if (offerEl || C.tour || P.offered || listEl) return;
    mountLive();
    offerEl = h('section.tour-offer', { role: 'region', 'aria-label': D.ui.offerTitle },
      h('b', null, D.ui.offerTitle), h('p', null, D.ui.offerText),
      h('div.row', null,
        h('button.btn.primary', { type: 'button', onclick: () => answer('accepted') }, D.ui.accept),
        h('button.btn', { type: 'button', onclick: () => answer('declined') }, D.ui.decline)));
    document.body.append(offerEl);                       // never focused: the person is doing something else
    announce(D.ui.offerSpeak);
  }
  function hideOffer() { if (offerEl) { offerEl.remove(); offerEl = null; } }
  function answer(a) {
    P.offered = a; persist(true); hideOffer();
    if (a === 'accepted') start('first-look');
    else { if (HX.toast) HX.toast(D.ui.declined, 4200); announce(D.ui.declined); }
  }

  /* ───────────────────────────── the list of tours ───────────────────────────── */
  const leftAt = (t) => { const at = P.at[t.id]; return at > 0 && at < t.steps.length - 1 ? at : 0; };      // a tour left on its last step is not "left"
  function stateText(t) {
    const n = t.steps.length, at = leftAt(t);
    if (at > 0) return fill(D.ui.leftAt, { i: at + 1, n });
    if (P.done.includes(t.id)) return '✓ ' + D.ui.doneBadge;
    return fill(D.ui.minutes, { m: t.minutes });
  }
  function closeList(restore) {
    if (!listEl) return;
    document.removeEventListener('keydown', onListKey, true);
    listEl.remove(); listEl = null;
    if (restore && listBefore && listBefore.focus) { try { listBefore.focus({ preventScroll: true }); } catch (e) { /* gone */ } }
    listBefore = null;
  }
  function onListKey(e) {
    if (!listEl) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeList(true); return; }
    if (e.key === 'Tab') {
      e.stopPropagation(); e.preventDefault();
      const set = focusables(listEl), i = set.indexOf(document.activeElement);
      if (set.length) set[i < 0 ? 0 : (i + (e.shiftKey ? -1 : 1) + set.length) % set.length].focus();
      return;
    }
    if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); return; }
    if (!e.metaKey && !e.ctrlKey) e.stopPropagation();
  }
  function openList() {
    if (listEl) return;
    hideOffer();
    mountLive();
    listBefore = document.activeElement;
    const btn = (label, fn, cls, aria) => h('button.btn' + (cls ? '.' + cls : ''), { type: 'button', 'aria-label': aria || label, onclick: fn }, label);
    const rows = D.tours.map((t) => {
      const at = leftAt(t), acts = [];
      if (at > 0) acts.push(btn(D.ui.cont, () => start(t.id, { at }), 'primary', D.ui.cont + ': ' + t.title), btn(D.ui.startOver, () => start(t.id), '', D.ui.startOver + ': ' + t.title));
      else if (P.done.includes(t.id)) acts.push(btn(D.ui.again, () => start(t.id), '', D.ui.again + ': ' + t.title));
      else acts.push(btn(D.ui.start, () => start(t.id), 'primary', D.ui.start + ': ' + t.title));
      return h('div.tour-row' + (P.done.includes(t.id) && !(at > 0) ? '.done' : ''), null,
        h('div.tour-info', null, h('b', null, t.title), h('span.tour-state', null, stateText(t)), h('p', null, t.blurb)),
        h('div.tour-acts', null, acts));
    });
    listEl = h('div.overlay.hx-confirm.tour-ov', { role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'tourListTitle' },
      h('div.confirm.tour-list', null, h('h3#tourListTitle', null, D.ui.listTitle), h('p.tour-intro', null, D.ui.listIntro), ...rows,
        h('div.row', null, btn(D.ui.closeList, () => closeList(true)))));
    listEl.addEventListener('pointerdown', (e) => { if (e.target === listEl) closeList(true); });
    document.body.append(listEl);
    document.addEventListener('keydown', onListKey, true);
    const first = listEl.querySelector('button.primary') || listEl.querySelector('button');
    if (first) first.focus();
  }

  /* ───────────────────────────── start-up ───────────────────────────── */
  function boot() {
    P = readLocal();
    mountLive();
    const b = HX.$('#btnTour');
    if (b) b.addEventListener('click', openList);
    HX.on('help', (o) => {                               // the shortcuts list carries a way in too
      const help = o && o.querySelector && o.querySelector('.help');
      if (help) help.append(h('p.tour-helpline', null, h('button.btn', { type: 'button', onclick: () => { o.hidden = true; openList(); } }, D.ui.helpButton)));
    });
    const asked = location.hash === '#tour';
    const settled = new Promise((res) => { const t = setTimeout(res, 1500); pullServer().then(() => { clearTimeout(t); res(); }); });
    settled.then(() => act(decide(asked), asked));
  }
  /* what to do once the saved progress is known: 'list' (asked for in the address), 'resume' (a tour was open when the page
     was left), 'offer' (never answered), or 'none' */
  function decide(asked) {
    if (asked) return 'list';
    if (P.active && tourById(P.active)) return 'resume';
    return P.offered ? 'none' : 'offer';
  }
  function act(what) {
    if (what === 'list') { try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* no history */ } openList(); }
    else if (what === 'resume') start(P.active, { at: P.at[P.active] || 0, resumed: true });
    else if (what === 'offer') setTimeout(showOffer, 700);
  }

  HX.tour = {
    open: openList, start, end, next, back, state: () => P, isOpen: () => !!C.tour, current: () => (C.tour ? { tour: C.tour.id, step: C.i, status: C.status } : null),
    checks: CHECKS, resolvers: RESOLVERS, mod: MOD,
    /* seams for tests/test_daw_tour.py */
    _core: { C, go, refresh, decide, act, resolve, resolveKey, pauseReason, sane, readLocal, merge, boot, answer, showOffer, openList, onKey, env, model, plain, rich, setPage: (p) => { P = p; } },
    _setUI: (u) => { ui = u || domUI; },
  };
  if (!HX.tourManual) boot();
})();
