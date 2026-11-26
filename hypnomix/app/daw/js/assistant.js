/* Hypnomix · the Assistant dock: a command palette and a chat in one input (⌘K).
   REAL, in the hypnomix app with a model key set (Assistant tab) and the engine connected: the chat is the app's
   Assistant (hypnomix/app/chat.py, the same conversation as the Assistant tab). It reads the session through the
   engine's own tools and proposes every change as a card with Approve / Cancel; nothing changes until you approve.
   DEMO otherwise (no key, no engine, or opened outside the app): the replies are scripted below (intents → proposed
   changes). Those changes are real ops: they go through the same path as your own edits (mock, or MCP when
   connected), and nothing changes until you press Approve. Pending changes are drawn in violet wherever they appear. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  let root, body, input, pal, tagEl, tab = 'chat', palItems = [], palIdx = 0, palOpen = false;
  const msgs = []; // { role, html | card }
  const cards = [];

  /* ── what's pending, for violet highlights elsewhere ── */
  const pendingOps = () => cards.filter((c) => c.state === 'pending').flatMap((c) => c.ops);
  HX.preview = {
    touches(tid, k) { const m = { vol: 'fader', pan: 'pan', send: 'send' }[k]; return pendingOps().some((o) => o.trackId === tid && o.param === m); },
    touchesDevice(tid, di) { return pendingOps().some((o) => o.trackId === tid && ((o.param === 'devParam' && o.key[0] === di) || (o.param === 'devOn' && o.key === di))); },
    touchesParam(tid, di, pi) { return pendingOps().some((o) => o.trackId === tid && o.param === 'devParam' && o.key[0] === di && o.key[1] === pi); },
    /* the value a pending change would set, or null (the mixer draws a dashed mark there) */
    target(tid, param) { const o = pendingOps().find((o) => o.trackId === tid && o.param === param); return o ? o.after : null; },
    clipGain(cid) { const o = pendingOps().find((o) => o.param === 'clipGain' && o.key === cid); return o ? HX.findClip(cid).clip.gainDb : null; },
  };

  HX.mountAssistant = function () {
    root = HX.$('#assistant');
    root.innerHTML = '';
    const tabs = h('div.seg', null,
      h('button.on', { 'data-t': 'chat', onclick: () => setTab('chat'), 'data-info': 'Chat with the Assistant' }, 'Chat'),
      h('button', { 'data-t': 'log', onclick: () => setTab('log'), 'data-info': 'Every engine call the UI makes (mock or MCP), newest last' }, 'Log'));
    const tall = h('button.tbtn', { 'data-info': 'Full height, or beside the device chain · ⌘⇧J', onclick: () => { HX.$('#app').classList.toggle('dock-short'); HX.arrange.dirty = true; }, 'aria-label': 'Change height' }, svg('M5 7l3-3 3 3M5 9l3 3 3-3'));
    const min = h('button.tbtn', { 'data-info': 'Hide the dock · ⌘J brings it back', onclick: () => HX.toggleDock(), 'aria-label': 'Hide' }, svg('M4 8h8'));
    tagEl = h('span.demo-tag', { 'data-info': 'Scripted demo replies. The edits they propose are real ops.' }, 'DEMO · SCRIPTED');
    root.append(h('div.as-head', null, h('span.t', null, svg('M8 1.5l1.6 4.2 4.4.3-3.4 2.8 1.1 4.3L8 10.7l-3.7 2.4 1.1-4.3L2 6l4.4-.3z', true), 'Assistant'), tagEl, tabs, tall, min));
    body = h('div.as-body');
    root.append(body);
    pal = h('div.palette', { hidden: true });
    input = h('input', { placeholder: 'Ask, or type a command…', spellcheck: 'false', 'data-info': 'Command palette + chat · ⌘K · ↑↓ choose · ⏎ run · Esc close' });
    root.append(h('div.as-input', null, pal, h('div.box', null, h('span.mode', null, '›'), input, h('span.kbd', null, '⌘K'))));
    bindInput();
    setTag();
    /* a Hear it left by an earlier copy of this page (a reload) is put back now, not only when its heartbeat runs out */
    if (HX.api.inApp) HX.api.post('/api/chat/preview', { end: true, why: 'the page was opened' }).catch(() => {});
    window.addEventListener('pagehide', () => { if (PV.id && HX.api.inApp) HX.api.post('/api/chat/preview', { id: PV.id, end: true, why: 'the page closed' }).catch(() => {}); });
    sys('Demo assistant: replies are scripted (js/assistant.js)' + (HX.api.inApp ? '; the real Assistant takes over when a model key is set (Assistant tab) and the engine is connected' : '') + '. What it proposes is shown as a change card and only happens when you press Approve; every approved change is one undo step in this view (⌘Z).');
    ai('Hi. I can see <b>' + HX.esc(S.session.name) + '</b>: ' + S.session.tracks.length + ' tracks, a ' + HX.esc(S.session.returns.map((r) => r.name).join(', ')) + ' return, ' + S.session.tempo + ' BPM. Try one:', ['Make the lead vocal sit forward', 'More space on the harmonies', 'Check the vocal levels line to line', 'Turn the keys down 2 dB', 'Scan the mix'], [{ tool: 'session_get_info', label: 'session_get_info' }, { tool: 'tracks_list', label: 'tracks_list' }, { tool: 'markers_list', label: 'markers_list' }]);
    renderBody();
  };
  function svg(d, fill) { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 16 16'); s.innerHTML = '<path d="' + d + '" fill="' + (fill ? 'currentColor' : 'none') + '" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"/>'; return s; }
  function setTab(t) { tab = t; HX.$$('.as-head .seg button', root).forEach((b) => b.classList.toggle('on', b.dataset.t === t)); renderBody(); }
  HX.toggleDock = () => { HX.$('#app').classList.toggle('dock-min'); HX.arrange.dirty = true; };

  /* ── messages ── */
  function sys(text) { msgs.push({ role: 'sys', html: HX.esc(text) }); }
  function me(text) { msgs.push({ role: 'me', html: HX.esc(text) }); }
  function ai(html, chips, reads) { msgs.push({ role: 'ai', html, chips, reads }); }
  function renderBody() {
    if (!body) return;
    body.innerHTML = '';
    if (tab === 'chat' && R.on) { renderReal(); body.scrollTop = body.scrollHeight; return; }
    if (tab === 'log') {
      const log = h('div.log');
      if (!S.log.length) log.append(h('div.msg.sys', null, 'No engine calls yet. Press Space, move a fader, or approve a change.'));
      S.log.slice(-200).forEach((r) => log.append(h('div.row', null, h('span.ts', null, r.ts), h('span.src.' + r.src, null, r.src === 'mcp' ? 'MCP' : r.src === 'err' ? 'ERR' : 'mock'), h('span.body', null, r.text))));
      body.append(log);
    } else msgs.forEach((m) => body.append(m.card ? cardEl(m.card) : msgEl(m)));
    body.scrollTop = body.scrollHeight;
  }
  function msgEl(m) {
    const el = h('div.msg.' + m.role, { html: m.html });
    if (m.typing) el.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
    /* what the Assistant read before answering, so you can see what its reply is based on */
    if (m.reads && m.reads.length) el.prepend(h('div.reads', null, m.reads.map((r) => h('span', null, r.label || r.tool))));
    if (m.chips) el.append(h('div.chips', { style: { marginTop: '6px' } }, m.chips.map((c) => h('button.chip-btn', { onclick: () => HX.assistantAsk(c) }, c))));
    return el;
  }

  /* ── change cards ── */
  function opRow(o) {
    const t = HX.track(o.trackId);
    let name = '', b = o.before, a = o.after, unit = ' dB', delta = '';
    const f = (v) => HX.fmtDb(v, true);
    switch (o.param) {
      case 'fader': name = 'Volume'; delta = HX.fmtDelta(a - b, ' dB'); b = f(b); a = f(a); break;
      case 'send': name = 'Send → ' + t.sends.find((s) => s.index === o.key).name; delta = HX.fmtDelta(a - b, ' dB'); b = f(b); a = f(a); break;
      case 'pan': name = 'Pan'; b = HX.fmtPan(b); a = HX.fmtPan(a); break;
      case 'mute': name = 'Mute'; b = b ? 'on' : 'off'; a = a ? 'on' : 'off'; break;
      case 'solo': name = 'Solo'; b = b ? 'on' : 'off'; a = a ? 'on' : 'off'; break;
      case 'devOn': name = t.devices[o.key].name; b = b ? 'on' : 'off'; a = a ? 'on' : 'off'; break;
      case 'devParam': { const d = t.devices[o.key[0]], p = d.params[o.key[1]]; name = d.name + ' · ' + p.n; delta = HX.fmtDelta(a - b, ' ' + p.unit); b = b + ' ' + p.unit; a = a + ' ' + p.unit; break; }
      case 'clipGain': { const c = HX.findClip(o.key).clip; name = 'Clip gain · ' + c.name; delta = HX.fmtDelta(a - b, ' dB'); b = f(b) + ' dB'; a = f(a) + ' dB'; break; }
    }
    return h('tr', null, h('td.tk', null, t ? t.name : '?'), h('td.pm', null, name), h('td.v', null, String(b)), h('td.arrow', null, '→'), h('td.v.after', null, String(a)), h('td.d', null, delta));
  }
  function cardEl(c) {
    const el = h('div.card' + (c.state === 'done' ? '.done' : c.state === 'cancelled' ? '.cancelled' : ''));
    const n = c.ops.length;
    el.append(h('div.card-h', null, h('b', null, c.title), h('small', null, c.action ? 'action' : n + ' change' + (n === 1 ? '' : 's'))));
    if (n) {
      el.append(h('table', null, c.ops.map(opRow)));
      const calls = c.ops.map((o) => { const d = HX.describeOp(o); return d.tool + ' ' + JSON.stringify(d.args); }).join('\n');
      el.append(h('details', null, h('summary', null, (HX.mcp.connected ? 'MCP calls to the engine' : 'MCP calls (mock: logged, not sent)') + ' · ' + n), h('pre', null, calls)));
    }
    if (c.note) el.append(h('div', { style: { padding: '4px 8px', color: 'var(--tx2)', fontSize: '10.5px', borderBottom: '1px solid var(--line)' } }, c.note));
    if (c.state === 'pending' && n) {
      const cb = h('input', { type: 'checkbox', onchange: (e) => (c.snapFirst = e.target.checked) });
      cb.checked = !!c.snapFirst;
      el.append(h('div.card-o', null, h('label', null, cb, 'Save a snapshot first ', h('span.mono', null, 'session_quick_snapshot')), h('span', null, 'Approving makes one undo step in this view (⌘Z).')));
    }
    const foot = h('div.card-f');
    if (c.state === 'pending') {
      const real = HX.mcp.connected;       /* with an engine, Hear it really changes the open session (the app holds what puts it back) */
      if (n) foot.append(h('button.btn.ghost' + (c.audition ? '.on' : ''), { onclick: () => audition(c), 'data-info': real ? 'Hear it: really changes the open session until you press it again, cancel or approve. It counts as an unsaved change, and the app puts it back if this page closes · A' : 'Hear it before deciding: applies temporarily, nothing is recorded · A', style: c.audition ? { color: 'var(--ai)' } : null }, c.audition ? '◉ Hearing B' : '○ Hear it'));
      foot.append(h('span.note' + (c.audition && real ? '.live' : ''), c.audition && real ? { role: 'status', style: { color: 'var(--ai)', fontWeight: '600' } } : null, c.audition ? (real ? 'LIVE NOW: this really changes your open session while you listen. It is never saved: pressing Hear it again, Cancel or Approve puts it back first' : 'hearing it · temporary, not in undo') : 'nothing changes until you approve'));
      foot.append(h('button.btn.ai', { 'data-approve': '1', onclick: (e) => { if (tooSoon(e, c._seen)) return; approve(c); }, onkeydown: noRepeat }, 'Approve'), h('button.btn', { onclick: () => cancel(c) }, 'Cancel ', h('kbd', null, 'Esc')));
    } else if (c.state === 'done') {
      foot.append(h('span.state', null, c.result || 'Applied · one undo step (⌘Z)'));
      const live = c.hist && S.history.includes(c.hist);
      if (c.hist && !live) foot.lastChild.textContent = S.future.includes(c.hist) ? 'Undone' : 'Applied · later undone or replaced';
      if (live) foot.append(h('button.btn.ghost', { onclick: () => { if (S.history[S.history.length - 1] === c.hist) HX.undo(); else HX.toast('Undo the newer changes first (⌘Z)'); } }, 'Undo'));
    } else foot.append(h('span.state', null, 'Cancelled · nothing changed'));
    el.append(foot);
    return el;
  }
  function propose(card) {
    card.id = 'k' + (cards.length + 1); card.state = 'pending'; card._seen = Date.now();
    card.ops.forEach((o) => (o.before = HX.getVal(o)));
    card.ops = card.ops.filter((o) => o.before !== o.after);
    cards.push(card);
    msgs.push({ card });
    HX.emit('preview');
  }
  /* Hear it. With an engine it is a real change to the open session, so the APP holds it: before the values are sent, the
     page tells the app (POST /api/chat/preview) what puts each one back; the app puts them back when the card is
     cancelled, approved or replaced, when the session is saved, and when this page stops answering (a reload, a closed
     tab). The page's heartbeat is that answer. */
  const PV_TOOLS = ['track_set_fader_db', 'track_set_fader_position', 'track_set_pan', 'track_set_mute', 'track_set_solo', 'track_set_send_level_db', 'track_set_send_level_position', 'plugin_set_enabled', 'plugin_set_parameter_by_index_value', 'plugin_set_parameter_by_index_interface'];
  const PV = { id: null, timer: null };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const APPROVE_AFTER = 800;           /* ms after a card appears before a keyboard press can approve it (a click with the mouse is never held back) */
  const tooSoon = (e, since) => e.detail === 0 && Date.now() - (since || 0) < APPROVE_AFTER;   /* detail 0: the click came from the keyboard (Enter / Space on the focused button) */
  const noRepeat = (e) => { if (e.repeat) { e.preventDefault(); e.stopPropagation(); } };     /* a held key is not a second click */
  function previewUndo(c) {
    return c.ops.filter((o) => !(HX.engineUndoOp && HX.engineUndoOp(o))).map((o) => { const d = HX.describeOp(Object.assign({}, o, { after: o.before })); return { tool: d.tool, arguments: d.args }; }).filter((u) => PV_TOOLS.includes(u.tool));
  }
  function beat() {
    clearInterval(PV.timer);
    PV.timer = setInterval(async () => {
      const c = cards.find((x) => x.id === PV.id && x.audition);
      if (!c) { clearInterval(PV.timer); return; }
      try { const r = await HX.api.post('/api/chat/preview', { id: c.id, beat: true }); if (r && r.live === false) { await stopAudition(c, 'the app took it back', true); HX.toast('Hear it was put back by the app'); } } catch (e) { /* the app is not answering: it will put it back by itself */ }
    }, 2000);
  }
  async function stopAudition(c, why, served) {
    if (!c.audition) return;
    c.audition = false;
    if (PV.id === c.id) { PV.id = null; clearInterval(PV.timer); }
    if (c.heldByApp) {
      c.heldByApp = false;
      await sleep(120);                                   /* the page's own throttled sends (40 ms) land first */
      if (!served) { try { await HX.api.post('/api/chat/preview', { id: c.id, end: true, why }); } catch (e) { HX.toast('Hear it could not be put back: ' + e.message + ' Check the values, or Undo.', 5200); } }
      c.ops.forEach((o) => HX.setLocal(o, o.before));    /* the view; the app put the engine back */
    } else c.ops.forEach((o) => HX.live(o, o.before));   /* the mock: nothing real was changed */
    HX.log(HX.mcp.connected ? 'mcp' : 'mock', 'audition A · ' + c.title + ' (' + why + ')');
  }
  HX.endAuditions = (why) => Promise.all(cards.filter((c) => c.audition).map((c) => stopAudition(c, why || 'ended').catch(() => {}))).then(() => renderBody());
  async function audition(c) {
    if (c.audition) { await stopAudition(c, 'pressed again'); renderBody(); return; }
    for (const x of cards.filter((y) => y !== c && y.audition)) await stopAudition(x, 'another card was tried', true);   /* the app replaces it too */
    if (HX.mcp.connected) {
      const undo = previewUndo(c);
      if (undo.length) {
        try { await HX.api.post('/api/chat/preview', { id: c.id, title: c.title, undo }); } catch (e) { HX.toast('Hear it could not start: ' + e.message, 4200); return; }
        c.heldByApp = true; PV.id = c.id; beat();
      }
    }
    c.audition = true;
    c.ops.forEach((o) => HX.live(o, o.after));
    HX.log(HX.mcp.connected ? 'mcp' : 'mock', 'audition B · ' + c.title);
    renderBody();
  }
  async function approve(c) {
    if (c.state !== 'pending') return;
    if (c.audition) await stopAudition(c, 'approved');   /* back to the real before-state first: a "snapshot first" holds it, the commit sends the new values */
    c.state = 'done';
    if (c.snapFirst && c.ops.length) {
      try {
        if (HX.mcp.connected) await HX.mcp.call('session_quick_snapshot', { switchToSnapshot: false });
        else HX.log('mock', 'session_quick_snapshot {"switchToSnapshot":false}');
        S.session.snapshots.push({ name: S.session.name + ' — before “' + c.title + '”', when: 'just now' });
        HX.emit('snapshots');
      } catch (e) { HX.toast('Snapshot failed, nothing applied: ' + e.message, 3600); c.state = 'pending'; renderBody(); return; }
    }
    if (c.action) { c.result = (await c.action()) || 'Done'; }
    else { await HX.commit('Assistant: ' + c.title, c.ops.map((o) => Object.assign({}, o)), 'assistant'); c.hist = S.history[S.history.length - 1]; }
    HX.emit('preview'); renderBody();
    if (c.after) setTimeout(() => { ai(c.after); renderBody(); }, 350);
  }
  async function cancel(c) {
    if (c.state !== 'pending') return;
    if (c.audition) await stopAudition(c, 'cancelled');
    c.state = 'cancelled'; HX.emit('preview'); renderBody();
  }
  const lastPending = () => [...cards].reverse().find((c) => c.state === 'pending');

  /* ── the scripted brain ── */
  const T = (name) => HX.trackByName(name) || HX.allTracks().find((t) => t.name.toLowerCase().includes(name.toLowerCase()));
  const ALIAS = [['lead', 'Lead Vocal'], ['vocal', 'Lead Vocal'], ['vox', 'Lead Vocal'], ['harmony 1', 'Harmony 1'], ['harm 1', 'Harmony 1'], ['harmony 2', 'Harmony 2'], ['harm 2', 'Harmony 2'], ['drum', 'Drums'], ['bass', 'Bass'], ['key', 'Keys'], ['piano', 'Keys'], ['guitar', 'Guitar'], ['gtr', 'Guitar'], ['reverb', 'Reverb'], ['master', 'Master']];
  function findTrack(q) {
    for (const t of HX.allTracks()) if (q.includes(t.name.toLowerCase())) return t;
    const words = q.split(/[^a-z0-9]+/);
    for (const t of HX.allTracks()) if (t.name.toLowerCase().split(/[^a-z0-9]+/).some((w) => w.length > 2 && words.some((x) => x === w || x === w + 's'))) return t;
    for (const [a, n] of ALIAS) if (q.includes(a)) { const t = T(n); if (t) return t; }
    return null;
  }
  const fader = (t, db) => ({ trackId: t.id, param: 'fader', after: Math.round(db * 10) / 10 });
  const sendOp = (t, db) => ({ trackId: t.id, param: 'send', key: t.sends[0].index, after: Math.round(db * 10) / 10 });
  function devOp(t, devName, pName, v) {
    const di = t.devices.findIndex((d) => d.name === devName); if (di < 0) return null;
    const pi = t.devices[di].params.findIndex((p) => p.n === pName); if (pi < 0) return null;
    return { trackId: t.id, param: 'devParam', key: [di, pi], after: v, realIndex: t.devices[di].params[pi].realIndex };
  }
  const clipOp = (t, name, add) => { const c = t && t.clips.find((c) => c.name === name); return c ? { trackId: t.id, param: 'clipGain', key: c.id, after: Math.round((c.gainDb + add) * 10) / 10 } : null; };

  function brain(text) {
    const q = text.toLowerCase().trim();
    const lead = T('Lead Vocal'), h1 = T('Harmony 1'), h2 = T('Harmony 2');
    const num = q.match(/(-?\d+(?:\.\d+)?)\s*(db|decibel)?/);

    if (/^(help|what can you do|\?)/.test(q)) return { say: 'In this demo I understand a few requests, and I always show the change before making it:', chips: ['Make the lead vocal sit forward', 'More space on the harmonies', 'Tighten the drums', 'Clean up the low end', 'Widen the harmonies', 'Mute the guitar', 'Undo that'] };

    if (/undo/.test(q)) {
      const hst = S.history[S.history.length - 1];
      if (!hst) return { say: 'There is nothing to undo yet.' };
      return { say: 'The last change was <b>' + HX.esc(hst.label) + '</b>. Undo it?', card: { title: 'Undo “' + hst.label + '”', ops: [], action: async () => { await HX.undo(); return 'Undone'; } } };
    }
    if (/^(play|start)\b/.test(q)) { HX.play(); return { say: 'Playing from ' + HX.bbtStr(HX.pos()).replace(/ /g, '') + '. (Transport is not a session change, so no card.)' }; }
    if (/^(stop|pause)\b/.test(q)) { HX.stop(); return { say: 'Stopped.' }; }

    if (/scan|review|what.*(wrong|fix)|check the mix|mix check/.test(q)) {
      return { say: 'A scan saves the session first, then checks vocal level line to line, harmony balance, comp edges, pitch against the chord, stack timing, masking, noise and true peak after AAC. It changes nothing by itself.', card: { title: 'Save the session and scan', ops: [], note: 'Calls session_save, then the hypnomix scan (mock in the demo). Opens Review.', action: async () => { HX.runScan(true); return 'Scanning · see Review'; } }, after: 'Findings are in <b>Review</b> (⌘4). Each one has A/B, Approve, Skip and Change; approved fixes go into one new snapshot.' };
    }
    if (/line to line|vocal level|levels? (of|on) the (lead|vocal)|vocallevel/.test(q)) {
      const o = clipOp(lead, 'Verse 2 B', 2.5);
      return { say: 'Line to line, the lead is even except <b>Verse 2 B</b> (bars 49–56), which sits about 2.8 dB under the song median. I would lift only that clip, on your comp, and leave the rest alone.', card: { title: 'Even out the lead in verse 2', ops: [o], note: 'Clip gain only; no compression, no re-render.' }, reads: [lead && { tool: 'track_get_regions', args: { id: lead.id }, label: 'track_get_regions ' + lead.name }].filter(Boolean) };
    }
    if (/(lead|vocal|vox).*(forward|louder|up|buried|sit|front|quiet|lost)|(louder|forward|up).*(lead|vocal|vox)/.test(q)) {
      const ops = [fader(lead, lead.faderDb + 1.5)];
      const hc = clipOp(h1, 'Chorus 1 hi', -2.4); if (hc) ops.push(hc);
      return { say: 'The lead is about 1.5 dB shy of the band in the choruses. I would lift its fader 1.5 dB. Harmony 1 already overshadows the lead in Chorus 1, so I would pull just that clip down to sit 1.5 dB under the melody; the other harmonies are fine and stay put.', card: { title: 'Bring the lead forward', ops }, reads: [readTrack(lead), readTrack(h1), readTrack(h2)].filter(Boolean) };
    }
    if (/reverb|space|wet|depth|ambien|room/.test(q)) {
      const rv = HX.allTracks().find((t) => t.isReturn);
      const ops = [sendOp(h1, h1.sends[0].db + 3), sendOp(h2, h2.sends[0].db + 3), sendOp(lead, lead.sends[0].db + 1.5)];
      const d = rv && devOp(rv, 'ACE Reverb', 'Decay', 2.8); if (d) ops.push(d);
      return { say: 'More space without washing out the words: more send on both harmonies, a touch on the lead, and a slightly longer tail on the Reverb return.', card: { title: 'More space on the harmonies', ops }, reads: [readTrack(h1), readTrack(h2), readTrack(rv)].filter(Boolean) };
    }
    if (/wid|stereo|pan/.test(q) && !findTrack(q.replace(/harmon(y|ies)/, ''))) {
      const g = T('Guitar');
      return { say: 'Spreading the harmonies further apart and nudging the guitar out of the lead’s way:', card: { title: 'Widen the harmonies', ops: [{ trackId: h1.id, param: 'pan', after: -0.5 }, { trackId: h2.id, param: 'pan', after: 0.5 }, { trackId: g.id, param: 'pan', after: 0.56 }] }, reads: [readTrack(h1), readTrack(h2), readTrack(g)].filter(Boolean) };
    }
    if (/drum|kick|snare|punch|tight/.test(q) && !/mute|solo/.test(q)) {
      const d = T('Drums');
      return { say: 'For punch: a slower attack lets the transients through, a little more threshold holds the body, and a bit more saturation adds weight.', card: { title: 'Tighten the drums', ops: [devOp(d, 'ACE Compressor', 'Attack', 30), devOp(d, 'ACE Compressor', 'Threshold', -17), devOp(d, 'Saturator', 'Mix', 45)].filter(Boolean) }, reads: [readTrack(d)].filter(Boolean) };
    }
    if (/low end|mud|mask|bass.*kick|kick.*bass|sidechain/.test(q)) {
      const b = T('Bass');
      return { say: 'Kick and bass share energy around 72 Hz on the chorus downbeats. A 2 dB keyed dip on the bass clears it; the bass keeps its level between hits.', card: { title: 'Clean up the low end', ops: [devOp(b, 'hx Sidechain', 'Depth', 2), devOp(b, 'ACE EQ', 'Low', 0.5)].filter(Boolean) }, reads: [readTrack(b), readTrack(T('Drums'))].filter(Boolean) };
    }
    const t = findTrack(q);
    if (t && /unmute/.test(q)) return { say: 'Unmute <b>' + HX.esc(t.name) + '</b>?', card: { title: 'Unmute ' + t.name, ops: [{ trackId: t.id, param: 'mute', after: false }] } };
    if (t && /mute/.test(q)) return { say: 'Mute <b>' + HX.esc(t.name) + '</b>?', card: { title: 'Mute ' + t.name, ops: [{ trackId: t.id, param: 'mute', after: true }] } };
    if (t && /solo/.test(q)) return { say: 'Solo <b>' + HX.esc(t.name) + '</b>?', card: { title: 'Solo ' + t.name, ops: [{ trackId: t.id, param: 'solo', after: !t.solo }] } };
    if (t && /(down|quieter|lower|reduce|cut|up|louder|raise|boost|set|to\s+-?\d)/.test(q)) {
      let db;
      if (/\bto\s+(-?\d+(\.\d+)?)/.test(q)) db = parseFloat(q.match(/\bto\s+(-?\d+(?:\.\d+)?)/)[1]);
      else { const amt = num ? Math.abs(parseFloat(num[1])) : 1.5; db = t.faderDb + (/(down|quieter|lower|reduce|cut)/.test(q) ? -amt : amt); }
      db = HX.clamp(db, -60, 6);
      return { say: 'Setting <b>' + HX.esc(t.name) + '</b> from ' + HX.fmtDb(t.faderDb) + ' to ' + HX.fmtDb(db) + ' dB.', card: { title: t.name + ' volume', ops: [fader(t, db)] }, reads: [readTrack(t)].filter(Boolean) };
    }
    if (t) return { say: 'What would you like to do with <b>' + HX.esc(t.name) + '</b>?', chips: ['Turn the ' + t.name.toLowerCase() + ' down 2 dB', 'Mute the ' + t.name.toLowerCase(), 'Solo the ' + t.name.toLowerCase()] };
    return { say: 'This is the scripted demo, so I only understand a few requests. In the real app this goes to the Assistant’s model, which sees the session through MCP. Try:', chips: ['Make the lead vocal sit forward', 'More space on the harmonies', 'Clean up the low end', 'Scan the mix'] };
  }

  /* ── the real Assistant: the app's (chat.py), with the engine's tools; every change is an Approve / Cancel card ── */
  const R = { on: false, total: 0, items: [], pending: null, busy: false, label: '', why: '', ranDaw: false, ranTools: [] };
  HX.realAssistant = R;
  HX._assistant = { realCard, realAnswer, propose, audition, approve, cancel, cards };      /* a seam for the tests (tests/test_daw_assistant.py runs this file with stand-ins) */
  function setTag() {
    if (!tagEl) return;
    tagEl.textContent = R.on ? 'ASSISTANT' : 'DEMO · SCRIPTED';
    tagEl.dataset.info = R.on ? 'The app’s Assistant (' + R.label + '): it reads the session through the engine and asks before every change. Same conversation as the Assistant tab.'
      : 'Scripted demo replies' + (R.why ? ' (' + R.why + ')' : '') + '. The edits they propose are real ops.';
  }
  function readyProvider(st) {
    const s = st && st.settings, p = s && s.providers.find((x) => x.id === s.provider);
    return p && (p.no_key || p.key_hint) && p.model ? p : null;
  }
  async function realPoll(full) {
    if (!HX.api.inApp) return;
    let st;
    try { st = await HX.api.get('/api/chat/state?since=' + (full ? 0 : R.total)); } catch (e) { return; }
    const p = readyProvider(st), on = !!p && HX.mcp.connected;
    R.why = !p ? 'no model key: set one in the Assistant tab' : !HX.mcp.connected ? 'the engine is not connected' : '';
    if (!full && st.total < R.total) { R.total = 0; return realPoll(true); }   // a new conversation (another tab reset it)
    if (full) R.items = [];
    R.items.push(...st.items);
    /* a card that was drawn earlier keeps its place: how it ended (approved and done, failed, cancelled) comes from the app */
    if (st.asks) R.items.forEach((x) => { const a = x.id && st.asks[x.id]; if (a) Object.assign(x, a); });
    /* a card answered, or the turn finished: read every item again (a card's state is updated in place) */
    if (!full && ((R.busy && !st.busy) || ((R.pending && R.pending.id) || null) !== ((st.pending && st.pending.id) || null))) return realPoll(true);
    const changed = full || st.items.length || on !== R.on || st.busy !== R.busy || JSON.stringify(st.pending) !== JSON.stringify(R.pending);
    const finished = R.busy && !st.busy;
    R.total = st.total; R.busy = st.busy; R.pending = st.pending; R.label = p ? p.label + ' · ' + p.model : '';
    if (on !== R.on) { R.on = on; setTag(); if (on && !full) return realPoll(true); }
    /* regions, markers, names, undo...: anything past a mixer setting is read again in full */
    if (finished && R.ranDaw) {
      const ts = R.ranTools; R.ranDaw = false; R.ranTools = [];
      refreshFromEngine(ts.some((t) => !/^(track_set_|plugin_set_|region_)/.test(t || '')) ? 'all' : ts.some((t) => /^region_/.test(t || '')) ? 'regions' : '');
    }
    if (changed && tab === 'chat') renderBody();
  }
  /* fast only while the Assistant works or waits for you; slow when idle (another tab may still write to it) */
  (function loop() { setTimeout(() => realPoll(false).finally(loop), R.busy || R.pending ? 700 : 2500); })();
  setTimeout(() => realPoll(true), 500);
  function md(t) {
    let x = HX.esc(t);
    x = x.replace(/```([\s\S]*?)```/g, (m, c) => '<code>' + c.replace(/^\w*\n/, '') + '</code>');
    x = x.replace(/`([^`\n]+)`/g, '<code>$1</code>').replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
    return x.split('\n').map((l) => /^\s*#{1,6} /.test(l) ? '<b>' + l.replace(/^\s*#{1,6} /, '') + '</b>' : /^\s*[-*] /.test(l) ? '• ' + l.replace(/^\s*[-*] /, '') : l).join('<br>');
  }
  function renderReal() {
    if (!R.items.length) body.append(h('div.msg.sys', null, 'The Assistant (' + R.label + ') sees this session through the engine. It reads first, and asks before every change.'));
    R.items.forEach((it) => {
      if (it.kind === 'user') body.append(h('div.msg.me', null, it.text));
      else if (it.kind === 'assistant') body.append(h('div.msg.ai', { html: md(it.text) }));
      else if (it.kind === 'tool') body.append(h('div.tool-line', null, '↳ ' + it.text));
      else if (it.kind === 'ask') body.append(realCard(it));
      else body.append(h('div.msg.sys', null, it.text));
    });
    if (R.busy && !R.pending) body.append(h('div.msg.ai', { html: '<span class="typing"><i></i><i></i><i></i></span>' }));
  }
  /* One card of the real Assistant: what it will do in plain words, what it changes (before → after), the exact call under a
     disclosure, what undo can do for it, and the real outcome once answered (approved and done, failed, cancelled...). */
  function realCard(it) {
    const live = R.pending && R.pending.id === it.id, daw = it.what === 'daw', hear = it.what === 'listen', scan = it.what === 'scan', budget = it.what === 'budget';
    const cls = live ? '' : it.answer === 'ran' ? '.done' : it.answer === 'failed' ? '.failed' : '.cancelled';
    const el = h('div.card' + cls);
    it._seen = it._seen || Date.now();
    const title = daw ? (it.title || it.tool) : scan ? (it.title || 'Save the session and scan it') : budget ? (it.title || 'This message has used a lot: keep going?') : hear ? 'Listen to the song' : 'Run a hypnomix command';
    el.append(h('div.card-h', null, h('b', null, title), h('small', null, daw ? 'engine call' : budget ? 'tokens' : scan ? 'scan' : 'hypnomix')));
    if ((daw || scan || budget) && it.summary) el.append(h('p', { style: { margin: '6px 8px', color: 'var(--tx2)', fontSize: '11px' } }, it.summary));
    /* what it changes, read from the engine just before the card was shown: before → after */
    if ((it.rows || []).length) el.append(h('table.rows', null, it.rows.map((r) => {
      const i = String(r.what).lastIndexOf(' · '), tk = i > 0 ? r.what.slice(0, i) : r.what, pm = i > 0 ? r.what.slice(i + 3) : '';
      return h('tr', null, h('td.tk', null, tk), h('td.pm', null, pm), h('td.v', null, String(r.before)), h('td.arrow', null, '→'), h('td.v.after', null, String(r.after)));
    })));
    if (daw) el.append(h('details', null, h('summary', null, 'The exact call to the engine'), h('pre', null, it.tool + ' ' + JSON.stringify(it.arguments || {}, null, 1))));
    else if (!budget) el.append(h('pre', null, it.text));
    const foot = h('div.card-f');
    if (live) {
      const note = daw ? 'nothing changes until you approve · ' + (it.undo_text || 'check the card before you approve')
        : hear ? 'a reduced mono copy of this song only' : scan ? 'saves the session; the scan itself changes nothing' : budget ? 'Keep going gives it another token allowance' : 'writes a new file, never over yours';
      foot.append(h('span.note', null, note));
      /* Approve is a plain button: Enter approves only while it has focus (and not as a held key, nor in the first moments
         after the card appears); there is no key that approves a card you have not looked at */
      foot.append(h('button.btn.ai', { 'data-approve': '1', onkeydown: noRepeat, onclick: (e) => { if (tooSoon(e, it._seen)) return; realAnswer(it, true); } },
        daw || scan ? 'Approve' : budget ? 'Keep going' : hear ? 'Send it' : 'Run it'),
        h('button.btn', { onclick: () => realAnswer(it, false) }, (daw || scan ? 'Cancel' : budget ? 'Stop here' : 'Don’t') + ' ', h('kbd', null, 'Esc')));
    } else {
      const said = it.answer === 'sending' ? 'Approved · sending it to the engine…'
        : it.answer === 'ran' ? (daw ? 'Approved · applied in the engine' + (it.now ? ' · reads back: ' + it.now : '') : budget ? 'You said keep going' : scan ? 'Approved · saved and scanned' : 'Done')
        : it.answer === 'failed' ? 'Approved, but the engine said: ' + (it.error || 'it failed') + (/may or may not/.test(it.error || '') ? '' : ' · nothing changed')
        : it.answer === 'declined' ? (budget ? 'Stopped' : 'Cancelled · nothing changed')
        : it.answer === 'expired' ? 'Expired unanswered · nothing changed' : 'Not waiting any more';
      foot.append(h('span.state', null, said));
    }
    el.append(foot);
    return el;
  }
  async function realAnswer(it, ok) {
    if (it._sent) return;                                   /* one click, one answer */
    it._sent = true;
    try { await HX.api.post('/api/chat/answer', { id: it.id, ok: ok === true, digest: it.digest || (R.pending && R.pending.id === it.id ? R.pending.digest : undefined) }); }
    catch (e) { it._sent = false; HX.toast(e.message, 3000); return; }
    it.answer = ok ? (it.what === 'daw' ? 'sending' : 'ran') : 'declined';
    if (ok && it.what === 'daw') { R.ranDaw = true; R.ranTools.push(it.tool); }
    R.pending = null; renderBody(); realPoll(false);
  }
  /* after approved engine calls: read the mix again, so faders, mutes, sends and plug-ins show what the engine has */
  async function refreshFromEngine(full) {
    if (!HX.mcp.connected) return;
    try {
      if (full === 'all') { await HX.loadFromEngine(); return; }
      const tl = await HX.mcp.tracksList(), routes = (tl && tl.tracks) || [];
      const real = HX.allTracks().filter((t) => t.real);
      if (routes.length !== real.length || routes.some((r) => !HX.track(r.id))) { await HX.loadFromEngine(); return; }
      for (const t of real) {
        const ti = await HX.mcp.trackInfo(t.id);
        /* a plug-in added, removed or moved: read the whole session again (the device chain is built there) */
        const was = t.devices.filter((d) => d.real).map((d) => d.index + d.name).join('|');
        if ((ti.plugins || []).map((p) => p.index + (p.displayName || p.name)).join('|') !== was) { await HX.loadFromEngine(); return; }
        if (ti.fader) t.faderDb = ti.fader.db;
        if (ti.pan) t.pan = 1 - 2 * ti.pan.position;
        t.mute = !!ti.mute; t.solo = !!ti.solo; t.arm = !!ti.recEnabled;
        (ti.sends || []).forEach((sd) => { const x = t.sends.find((y) => y.index === sd.index); if (x) x.db = sd.db; });
        (ti.plugins || []).forEach((pl) => { const d = t.devices.find((y) => y.index === pl.index); if (d) d.on = !!pl.enabled; });
        /* a region moved, resized, muted: place it again; one added or gone (split, copy, remove): read it all */
        if (full === 'regions' && t.kind !== 'bus' && !t.isMaster && HX.refreshRegions) continue; // all at once below
        if (full === 'regions' && t.kind !== 'bus' && !t.isMaster) {
          const rg = ((await HX.mcp.trackRegions(t.id)) || {}).regions || [];
          if (rg.length !== t.clips.length || rg.some((g) => !t.clips.find((c) => String(c.id) === String(g.regionId)))) { await HX.loadFromEngine(); return; }
          const sr = HX.S.session.sampleRate || 48000, bpm = HX.S.session.tempo || 120, s2b = (n) => (n / sr) * (bpm / 60);
          rg.forEach((g) => { const c = t.clips.find((x) => String(x.id) === String(g.regionId)); c.start = s2b(g.startSample); c.len = Math.max(0.25, s2b(g.lengthSamples)); c.muted = g.muted; c.name = g.name; });
        }
      }
      /* regions through the Arrangement's own re-read (js/regions.js): splits, removes, gains, fades and peaks,
         keeping the view's undo history */
      if (full === 'regions' && HX.refreshRegions) await HX.refreshRegions(real.filter((t) => t.kind !== 'bus' && !t.isMaster).map((t) => t.id));
      HX.emit('session-light'); HX.emit('select'); HX.emit('devices');
    } catch (e) { HX.log('err', 'reading the mix again · ' + e.message); }
  }

  HX.assistantAsk = function (text) {
    if (!text.trim()) return;
    if (R.on) {
      if (HX.$('#app').classList.contains('dock-min')) HX.toggleDock();
      setTab('chat');
      if (R.busy) { HX.toast('The Assistant is still working on the last message'); return; }
      R.busy = true; renderBody();
      HX.api.post('/api/chat/send', { text, view: S.ui && S.ui.view }).then(() => realPoll(false)).catch((e) => { R.busy = false; HX.toast(e.message, 3600); renderBody(); });
      return;
    }
    if (HX.$('#app').classList.contains('dock-min')) HX.toggleDock();
    setTab('chat');
    me(text);
    const typing = { role: 'ai', html: '', typing: true };
    msgs.push(typing); renderBody();
    setTimeout(() => {
      msgs.splice(msgs.indexOf(typing), 1);
      let r;
      try { r = brain(text); } catch (e) { r = { say: 'That scripted reply was written for the mock session’s tracks (Lead Vocal, Harmony 1/2, …), which this session does not have. Track-named requests work anywhere: try “turn the ' + HX.esc((S.session.tracks[0] || S.session.master).name.toLowerCase()) + ' down 2 dB”.' }; }
      readFirst(r.reads).then(() => {
        ai(r.say, r.chips, r.reads);
        if (r.card) propose(r.card);
        renderBody();
        if (r.after && !r.card) setTimeout(() => { ai(r.after); renderBody(); }, 400);
        else if (r.after) r.card.after = r.after;
      });
    }, 420 + Math.random() * 380);
  };
  /* The reads a reply is based on. Connected, they are real MCP calls made before the reply;
     on the mock they are logged. Either way they are listed above the reply. */
  async function readFirst(reads) {
    for (const r of reads || []) {
      if (HX.mcp.connected) { try { await HX.mcp.call(r.tool, r.args || {}); } catch (e) { r.label = (r.label || r.tool) + '  (failed)'; } }
      else HX.log('mock', r.tool + ' ' + JSON.stringify(r.args || {}));
    }
  }
  const readTrack = (t) => t && { tool: 'track_get_info', args: { id: t.id }, label: 'track_get_info ' + t.name };

  /* ── palette ── */
  function commands() {
    const c = [
      { k: 'Transport', n: 'Play / Stop', kb: 'Space', run: HX.toggle },
      { k: 'Transport', n: 'Go to start', kb: 'Home', run: () => HX.locate(0) },
      { k: 'Transport', n: 'Toggle loop', kb: 'L', run: HX.toggleLoop },
      { k: 'Transport', n: 'Toggle metronome', kb: 'K', run: () => HX.toggleMetro() },
      { k: 'View', n: 'Show Arrangement', kb: '⌘1', run: () => HX.setView('arrange') },
      { k: 'View', n: 'Show Session clips', kb: '⌘2', run: () => HX.setView('session') },
      { k: 'View', n: 'Show Mixer', kb: '⌘3', run: () => HX.setView('mixer') },
      { k: 'View', n: 'Show Review', kb: '⌘4', run: () => HX.setView('review') },
      { k: 'View', n: 'Zoom to fit', kb: 'Z', run: () => { HX.setView('arrange'); HX.zoomFit(); } },
      { k: 'View', n: 'Toggle theme (light / dark)', kb: '⇧T', run: HX.toggleTheme },
      { k: 'View', n: 'Toggle browser', kb: '⌘⌥B', run: () => { HX.$('#app').classList.toggle('browser-min'); HX.arrange.dirty = true; } },
      { k: 'View', n: 'Show keyboard shortcuts', kb: '?', run: HX.showHelp },
      { k: 'Edit', n: 'Undo', kb: '⌘Z', run: HX.undo },
      { k: 'Edit', n: 'Redo', kb: '⇧⌘Z', run: HX.redo },
      { k: 'Hypnomix', n: 'Scan session', kb: '', run: () => HX.runScan() },
      { k: 'Engine', n: HX.mcp.connected ? 'Disconnect from engine' : 'Connect to engine (MCP)', kb: '', run: () => HX.$('#btnConnect').click() },
    ];
    HX.allTracks().forEach((t) => {
      c.push({ k: 'Track', n: 'Select ' + t.name, kb: '', run: () => HX.select(t.id) });
      if (!t.isMaster) { c.push({ k: 'Track', n: (t.mute ? 'Unmute ' : 'Mute ') + t.name, kb: '', run: () => HX.edit({ trackId: t.id, param: 'mute' }, !t.mute, (t.mute ? 'Unmute ' : 'Mute ') + t.name) }); c.push({ k: 'Track', n: (t.solo ? 'Unsolo ' : 'Solo ') + t.name, kb: '', run: () => HX.edit({ trackId: t.id, param: 'solo' }, !t.solo, (t.solo ? 'Unsolo ' : 'Solo ') + t.name) }); }
    });
    return c;
  }
  function match(name, q) {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const nw = name.toLowerCase().split(/[\s/()]+/);
    return words.every((w) => nw.some((x) => x.startsWith(w)));
  }
  function hl(name, q) {
    let out = HX.esc(name);
    q.toLowerCase().split(/\s+/).filter(Boolean).forEach((w) => { out = out.replace(new RegExp('(^|[\\s(/])(' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'i'), '$1<mark>$2</mark>'); });
    return out;
  }
  function renderPal() {
    const q = input.value.trim();
    const cmds = q ? commands().filter((c) => match(c.n, q)).slice(0, 8) : commands().slice(0, 7);
    palItems = cmds.map((c) => ({ type: 'cmd', c }));
    if (q) palItems.push({ type: 'ask', text: q });
    palIdx = HX.clamp(palIdx, 0, Math.max(0, palItems.length - 1));
    pal.innerHTML = '';
    if (!q) pal.append(h('div.pal-sec.label', null, 'Commands · type to filter, or ask anything'));
    palItems.forEach((it, i) => {
      const row = it.type === 'ask'
        ? h('div.pal-item.ask' + (i === palIdx ? '.on' : ''), null, h('span.k', null, 'Ask'), h('span', { html: '“' + HX.esc(it.text) + '”' }), h('span.kb', null, '⏎'))
        : h('div.pal-item' + (i === palIdx ? '.on' : ''), null, h('span.k', null, it.c.k), h('span', { html: hl(it.c.n, q) }), h('span.kb', null, it.c.kb));
      row.addEventListener('mousedown', (e) => { e.preventDefault(); palIdx = i; run(); });
      row.addEventListener('mousemove', () => { if (palIdx !== i) { palIdx = i; HX.$$('.pal-item', pal).forEach((r, k) => r.classList.toggle('on', k === i)); } });
      pal.append(row);
    });
    pal.hidden = !palOpen || !palItems.length;
  }
  function run() {
    const it = palItems[palIdx];
    const text = input.value;
    input.value = ''; palOpen = false; pal.hidden = true;
    if (!it) { if (text.trim()) HX.assistantAsk(text); return; }
    if (it.type === 'ask') HX.assistantAsk(it.text);
    else { it.c.run(); HX.info('Ran: ' + it.c.n); input.blur(); }
  }
  function bindInput() {
    input.addEventListener('focus', () => { palOpen = true; palIdx = 0; renderPal(); });
    input.addEventListener('blur', () => { palOpen = false; pal.hidden = true; });
    input.addEventListener('input', () => { palOpen = true; palIdx = 0; renderPal(); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); palIdx = Math.min(palItems.length - 1, palIdx + 1); renderPal(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); palIdx = Math.max(0, palIdx - 1); renderPal(); }
      else if (e.key === 'Enter') { e.preventDefault(); run(); }
      else if (e.key === 'Escape') { e.preventDefault(); if (input.value) { input.value = ''; renderPal(); } else input.blur(); }
      e.stopPropagation();
    });
  }
  HX.focusAssistant = () => { if (HX.$('#app').classList.contains('dock-min')) HX.toggleDock(); input.focus(); input.select(); };
  /* Esc cancels the newest pending card when focus is not in a text field. Enter approves nothing from here: a card is
     approved by clicking its Approve button, or by Enter while that button has the focus (the button's own behaviour,
     with a held key ignored): never by an Enter that was meant for something else. */
  HX.cardKey = function (key) {
    if (key !== 'Escape') return false;
    if (R.on && R.pending) { const it = R.items.find((x) => x.id === R.pending.id); if (it) { realAnswer(it, false); return true; } }
    const c = lastPending(); if (!c) return false;
    cancel(c); return true;
  };

  HX.on('history', () => { if (tab === 'chat') renderBody(); });
  HX.on('log', () => { if (tab === 'log') { clearTimeout(renderBody._t); renderBody._t = setTimeout(renderBody, 60); } });
  HX.on('session', () => { cards.forEach((c) => { if (c.audition) stopAudition(c, 'the session was read again', false).catch(() => {}); if (c.state === 'pending') c.state = 'cancelled'; }); if (root && HX.mcp.connected) {
    sys('Connected to the engine. Cards from the mock session were closed.');
    const n = S.session.tracks.length, r = S.session.returns.length;
    ai('Now I can see <b>' + HX.esc(S.session.name) + '</b>: ' + n + ' track' + (n === 1 ? '' : 's') + (r ? ', ' + r + ' bus' + (r === 1 ? '' : 'es') : '') + ', ' + S.session.tempo + ' BPM. Ask by track name, for example:', (S.session.tracks[0] ? ['Turn the ' + S.session.tracks[0].name.toLowerCase() + ' down 2 dB', 'Mute the ' + S.session.tracks[0].name.toLowerCase()] : []), [{ tool: 'session_get_info', label: 'session_get_info' }, { tool: 'tracks_list', label: 'tracks_list' }, { tool: 'markers_list', label: 'markers_list' }]);
    renderBody();
  } });
})();
