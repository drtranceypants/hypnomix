// The Teacher tab (hypnomix/app/teacher.py): a step-by-step course from an empty song to a master, in the DAW the
// person chose in Setup. Uses the page's own helpers: $, esc, get, post, go, S, render.
// Every hands-on action first says exactly what it will change and waits for "Do it".
const T = {st: null, daw: '', level: '', at: '', pending: null, result: {}, busy: false, quiz: {}, view: '', gl: null, glq: '', audio: null};

(function () {
  const st = document.createElement('style');
  st.textContent = `main:has(.teach){max-width:1120px}
  .teach{display:grid;grid-template-columns:260px 1fr;gap:26px;align-items:start}
  .teach aside{position:sticky;top:64px;max-height:calc(100vh - 84px);overflow:auto;padding-right:4px}
  .teach aside h4{margin:16px 0 4px;font-size:.74rem;letter-spacing:.12em;text-transform:uppercase;color:var(--mute)}
  .teach aside a{display:flex;gap:8px;padding:4px 8px;border-radius:6px;color:var(--ink);text-decoration:none;font-size:.93rem;cursor:pointer}
  .teach aside a:hover{background:var(--card)}.teach aside a.on{background:var(--card);font-weight:600;box-shadow:inset 2px 0 0 var(--accent)}
  .teach aside a i{font-style:normal;width:1.1em;color:var(--mute)}.teach aside a.done i{color:var(--ok)}
  .teach .daws{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 6px}.teach .daws button.sel{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
  .lesson{min-width:0;line-height:1.6}.lesson .no{color:var(--accent);font-size:.78rem;letter-spacing:.14em;text-transform:uppercase}
  .lesson h1{font-size:1.7rem;margin:2px 0 10px}.lesson h3{font-size:1rem;margin:22px 0 6px}
  .lesson dl{display:grid;grid-template-columns:auto 1fr;gap:6px 14px;margin:0}.lesson dt{font-weight:600}.lesson dd{margin:0}
  .lesson table td,.lesson table th{border-top:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
  .lesson ol li{margin:4px 0}.lesson .listen{border-left:3px solid var(--info);padding:4px 12px;margin:14px 0}
  .lesson .do{border:1.5px solid var(--accent);border-radius:12px;padding:12px 16px;margin:18px 0;background:var(--card)}
  .lesson .do .f{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:6px 0}.lesson .do .f label{color:var(--mute);font-size:.9rem}
  .lesson .do .f input,.lesson .do .f select{flex:0 1 160px;min-width:90px}
  .lesson .sure{background:var(--bg);border-radius:8px;padding:10px 12px;margin:8px 0}
  .lesson .ok{color:var(--ok)}.lesson .bad{color:var(--hi)}
  .lesson .nav{display:flex;justify-content:space-between;gap:8px;margin-top:24px;border-top:1px solid var(--line);padding-top:14px;flex-wrap:wrap}
  .lesson .quiz,.lesson .hear,.lesson .try,.lesson .mist,.lesson .more{border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:14px 0}
  .lesson .try{border-left:3px solid var(--accent)}.lesson .mist ul{margin:4px 0 0}.lesson .more a{cursor:pointer;margin-right:12px;text-decoration:underline}
  .lesson .opts{display:flex;flex-direction:column;gap:6px;margin:6px 0}.lesson .opts button{text-align:left}
  .lesson .opts button.right{border-color:var(--ok);color:var(--ok)}.lesson .opts button.wrong{border-color:var(--hi);color:var(--hi)}
  .lesson .hear .pl{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}.lesson .hear .pl button.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
  .gl{margin:0}.gl h2{font-size:1.1rem;margin:20px 0 4px;color:var(--accent)}.gl p{margin:4px 0}.gl a{cursor:pointer;text-decoration:underline;color:var(--mute);font-size:.88rem}
  @media (max-width:760px){.teach{grid-template-columns:1fr}.teach aside{position:static;max-height:none}}`;
  document.head.appendChild(st);
})();

const tmd = t => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>');
const tsteps = () => (T.st ? T.st.chapters.flatMap((c, ci) => c.steps.map(s => ({...s, chapter: c, ci}))) : []);

async function teachLoad(daw) {
  T.st = await get('/api/teach/state?daw=' + encodeURIComponent(daw || '') + '&level=' + encodeURIComponent(T.level || ''));
  T.daw = T.st.daw; T.level = T.st.level;
  const all = tsteps();
  if (!all.find(s => s.id === T.at)) T.at = T.st.at && all.find(s => s.id === T.st.at) ? T.st.at : (all.find(s => !T.st.done.includes(s.id)) || all[0] || {}).id || '';
  return T.st;
}

async function teachView() {
  await teachLoad(T.daw);
  const st = T.st;
  const dawTour = await dawTourCard();
  const pick =`<div class="daws">${Object.entries(st.daws).map(([k, v]) => `<button data-tdaw="${k}" class="${k === T.daw ? 'sel' : ''}">${esc(v)}</button>`).join('')}</div>`;
  const lv = `<div class="daws">${[['tour', 'Tour: ' + (T.daw === 'ardour' ? st.daws.ardour : 'HypnoMix in ' + (st.daws[T.daw] || 'your DAW')), 'for people who already record and mix'], ['101', '101 crash course', 'for people new to audio: the basics first, then the tour'], ['az', 'The complete course, A to Z', 'everything from what sound is to releasing a song: gear, recording, editing, mixing, mastering, cheat sheets']].map(([k, v, d]) => `<button data-tlevel="${k}" class="${k === T.level && !T.view ? 'sel' : ''}" title="${d}">${esc(v)}</button>`).join('')}<button data-tgloss="1" class="${T.view === 'glossary' ? 'sel' : ''}" title="Every word the lessons teach, A to Z">Glossary</button></div>`;
  if (!T.daw) return `<h1>Teacher</h1><p class="sub">A step-by-step course for people who have never used a DAW: from an empty song to a mastered one.</p>
    <div class="card"><p style="margin-top:0">Which DAW will you use? The lessons, and the Wiki, follow your choice.</p>${pick}
    <p class="note">Ableton Live and REAPER get the same depth, and HypnoMix Studio the short version (it's the least tested with HypnoMix).</p></div>${dawTour}`;
  if (T.view === 'glossary') return glossaryView(pick, lv);
  const all = tsteps(), i = Math.max(0, all.findIndex(s => s.id === T.at)), s = all[i];
  const nav = st.chapters.map((c, ci) => `<h4>${ci + 1} · ${esc(c.title)}</h4>` + c.steps.map(x =>
    `<a href="#" data-tstep="${esc(x.id)}"${x.id === s.id ? ' aria-current="step"' : ''} class="${x.id === s.id ? 'on' : ''} ${st.done.includes(x.id) ? 'done' : ''}"><i aria-hidden="true">${st.done.includes(x.id) ? '✓' : '○'}</i>${st.done.includes(x.id) ? '<span class="sr">done: </span>' : ''}${esc(x.title)}</a>`).join('')).join('');
  const ai = st.mode === 'key' || st.mode === 'local';
  return `<div class="teach"><aside>${pick}${lv}${dawTour}
    <label class="note" style="display:flex;gap:6px;align-items:center;margin:6px 0"><input type="checkbox" id="tmode" ${st.teach ? 'checked' : ''}> Teacher mode: open on this tab, and the Assistant teaches this course</label>
    <p class="note">${st.done.length} of ${all.length} steps done</p><nav>${nav}</nav></aside>
    <div class="lesson">${lessonHTML(s, i, all.length)}
      <div class="nav"><button data-tgo="-1" ${i ? '' : 'disabled'}>Back</button>
        <span>${ai ? `<button data-task="${esc(s.id)}" title="Opens the Assistant with a question about this step; nothing is sent until you press Send">Ask the Assistant</button> ` : ''}
        <button class="primary" data-tnext="${esc(s.id)}">${i === all.length - 1 ? 'Done: finish the course' : st.done.includes(s.id) ? 'Next step' : 'Done, next step'}</button></span></div></div></div>`;
}

// The card that opens the guided tours inside the HypnoMix Studio (hypnomix/app/daw/js/tour.js). Only where the DAW view is there at all:
// the same test as the DAW tab's (a DAW-mode app, or an engine found, attached or connected).
async function dawTourCard() {
  if (T.dawOk === undefined) {
    try { const d = await get('/api/daw/state'); T.dawOk = !!(d.daw_mode || d.binary || d.mode || d.connected); } catch (e) { T.dawOk = false; }
  }
  if (!T.dawOk) return '';
  let n = '';
  try { const t = await get('/api/teach/tour'); if (t.done && t.done.length) n = ` ${t.done.length} tour${t.done.length === 1 ? '' : 's'} done.`; } catch (e) { /* the count is a nicety */ }
  return `<div class="card" id="tdawtour"><b>Take the tour inside the HypnoMix Studio</b><p class="note" style="margin:4px 0 8px">Short, optional tours point at the real controls of the DAW view, one step at a time. Nothing changes unless you do it yourself.${esc(n)}</p><button data-tdawtour="1">Open the tours</button></div>`;
}

function lessonHTML(s, i, n) {
  const daw = T.st.daws[T.daw];
  const r = T.result[s.id];
  let h = `<div class="no">Chapter ${s.ci + 1} · ${esc(s.chapter.title)} · step ${i + 1} of ${n}</div><h1>${esc(s.title)}</h1>`;
  h += (s.say || []).map(p => `<p>${tmd(p)}</p>`).join('');
  if (s.terms) h += `<h3>The words</h3><dl>${s.terms.map(([w, m]) => `<dt>${esc(w)}</dt><dd>${esc(m)}</dd>`).join('')}</dl>`;
  if (s.settings) h += `<h3>Where to start</h3><table><tr><th>Control</th><th>Start at</th><th>Why</th></tr>${s.settings.map(([a, b, c]) => `<tr><td>${esc(a)}</td><td><b>${esc(b)}</b></td><td>${esc(c)}</td></tr>`).join('')}</table>`;
  if (s.how && s.how.length) h += `<h3>In ${esc(daw)}</h3><ol>${s.how.map(x => `<li>${tmd(x)}</li>`).join('')}</ol>`;
  if (s.listen) h += `<div class="listen"><b>Listen:</b> ${esc(s.listen)}</div>`;
  (s.hear || []).forEach(x => { h += hearHTML(x); });
  if (s.mistakes && s.mistakes.length) h += `<div class="mist"><b>Common mistakes</b><ul>${s.mistakes.map(m => `<li>${tmd(m)}</li>`).join('')}</ul></div>`;
  if (s.try) h += `<div class="try"><b>Try it</b><p style="margin:4px 0">${tmd(s.try.do)}</p><p class="note" style="margin:0">You'll know it worked when: ${tmd(s.try.success)}</p></div>`;
  if (s.quiz) h += quizHTML(s);
  if (s.action) h += actionHTML(s);
  else if (T.daw === 'ardour' && ['tempo', 'click', 'drums', 'track', 'take', 'chain'].includes(s.id)) h += `<p class="note">The Teacher can't do this one in HypnoMix Studio yet, so it is by hand: the steps above say where.</p>`;
  if (s.app) h += `<p><button data-view="${esc(s.app.view)}">${esc(s.app.label)}</button></p>`;
  if (s.more && s.more.length) h += moreHTML(s.more);
  if (r) h += resultHTML(r);
  return h;
}

function hearHTML(x) {
  return `<div class="hear"><b>Hear it:</b> ${esc(x.title)}<p style="margin:4px 0">${esc(x.listen)}</p><div class="pl">${x.variants.map(v =>
    `<button data-thear="${esc(x.demo)}|${esc(v.v)}" title="Play">▶ ${esc(v.label)}</button>`).join('')}</div></div>`;
}

function quizHTML(s) {
  const got = T.quiz[s.id] || {};
  return s.quiz.map((q, qi) => {
    const c = got[qi];
    return `<div class="quiz"><b>Check yourself:</b> ${tmd(q.q)}<div class="opts">${q.options.map((o, oi) =>
      `<button data-tquiz="${esc(s.id)}:${qi}:${oi}" class="${c === oi ? (oi === q.answer ? 'right' : 'wrong') : ''}">${esc(o)}</button>`).join('')}</div>
      ${c === undefined ? '' : `<p class="${c === q.answer ? 'ok' : 'bad'}" style="margin:4px 0">${c === q.answer ? 'Right.' : 'Not quite: try another.'} ${c === q.answer ? tmd(q.why) : ''}</p>`}</div>`;
  }).join('');
}

function moreHTML(more) {
  const names = {}; (T.st.chapters || []).forEach(c => c.steps.forEach(s => { names[s.id] = s.title; }));
  const links = more.map(m => m.startsWith('step:') ? `<a href="#" data-tjump="${esc(m.slice(5))}">${esc(names[m.slice(5)] || m.slice(5))}</a>`
    : m.startsWith('hypnomix ') ? `<code>${esc(m)}</code>` : `<a data-wiki="${esc(m)}" href="#">${esc(m)}</a>`);
  return `<div class="more"><b>Read next:</b> ${links.join(' ')}</div>`;
}

function glossaryView(pick, lv) {
  return `<div class="teach"><aside>${pick}${lv}<p class="note">Every word the lessons teach, with the lesson that explains it.</p></aside>
    <div class="lesson"><div class="no">Teacher</div><h1>Glossary</h1>
    <input id="tgq" type="search" aria-label="Filter the words" placeholder="Filter the words" value="${esc(T.glq)}" style="width:100%;max-width:420px">
    <div id="tgl" class="gl">${glossaryList()}</div></div></div>`;
}

function glossaryList() {
  const q = T.glq.trim().toLowerCase();
  const terms = (T.gl || []).filter(g => !q || g.term.toLowerCase().includes(q) || g.entries.some(e => e.meaning.toLowerCase().includes(q)));
  if (!terms.length) return `<p class="note">${T.gl ? 'No word matches.' : 'Loading…'}</p>`;
  let letter = '', h = '';
  terms.forEach(g => {
    const l = (g.term.replace(/[^A-Za-z0-9]/g, '')[0] || '#').toUpperCase();
    if (l !== letter) { letter = l; h += `<h2>${esc(l)}</h2>`; }
    g.entries.forEach(e => { h += `<p><b>${esc(g.term)}</b>: ${esc(e.meaning)} ${e.step ? `<a href="#" data-tjump="${esc(e.step)}">→ ${esc(e.title)}</a>` : ''}</p>`; });
  });
  return h;
}

async function teachJump(id) {
  T.view = '';
  await teachLoad(T.daw);
  if (!tsteps().some(s => s.id === id)) { T.level = 'az'; await teachLoad(T.daw); }
  T.at = id; T.pending = null; await teachMark('', true, id); await render(); window.scrollTo(0, 0); teachFocus();
}

function teachPlay(b) {
  const [demo, v] = b.dataset.thear.split('|');
  if (!T.audio) T.audio = new Audio();
  const a = T.audio, url = `/api/teach/hear?demo=${encodeURIComponent(demo)}&v=${encodeURIComponent(v)}`;
  document.querySelectorAll('[data-thear].on').forEach(x => x.classList.remove('on'));
  if (!a.paused && a.dataset.url === url) { a.pause(); return; }
  a.pause(); a.dataset.url = url; a.src = url; a.onended = () => b.classList.remove('on'); a.onpause = () => b.classList.remove('on');
  b.classList.add('on'); a.play().catch(() => b.classList.remove('on'));
}

function fill(text, s) {
  return esc(text).replace(/\{(\w+)\}/g, (_, k) => `<b>${esc(fieldVal(s, k))}</b>`);
}
function fieldVal(s, k) {
  const el = document.querySelector(`[data-tfield="${CSS.escape(s.id + ':' + k)}"]`);
  const f = (s.action.fields || []).find(x => x.id === k);
  return el ? el.value : f ? f.value : '';
}

function actionHTML(s) {
  const a = s.action, p = T.pending && T.pending.step === s.id;
  const fields = (a.fields || []).map(f => `<div class="f"><label for="tf-${esc(f.id)}">${esc(f.label)}</label>${f.options
    ? `<select id="tf-${esc(f.id)}" data-tfield="${esc(s.id + ':' + f.id)}" ${p ? 'disabled' : ''}>${f.options.map(o => `<option ${String(T.pending && T.pending.args[f.id] || f.value) === o ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`
    : `<input id="tf-${esc(f.id)}" type="${f.type === 'number' ? 'number' : 'text'}" data-tfield="${esc(s.id + ':' + f.id)}" value="${esc(p ? T.pending.args[f.id] : f.value)}" ${p ? 'disabled' : ''}>`}</div>`).join('');
  const rec = T.st.recording && T.st.recording.busy;
  return `<div class="do"><b>Let HypnoMix do it</b> <span class="note">· ${a.changes ? 'changes your song, after you say yes' : 'changes nothing'}</span>${fields}
    ${p ? `<div class="sure">${T.pending.will}</div><button class="primary" data-tdo="${esc(s.id)}" ${T.busy ? 'disabled' : ''}>${T.busy ? 'Working…' : 'Do it'}</button> <button data-tcancel="1">Not now</button>`
        : `<button data-task-do="${esc(s.id)}" ${rec ? 'disabled' : ''}>${esc(a.label)}…</button>${a.kind === 'record' && T.daw === 'reaper' ? ' <button data-tstop="' + esc(s.id) + '">Stop</button>' : ''}`}
    ${rec ? '<p class="note">Recording…</p>' : T.st.recording && T.st.recording.msg && a.kind === 'record' ? `<p class="note">${esc(T.st.recording.msg)}</p>` : ''}</div>`;
}

function resultHTML(r) {
  if (r.error) return `<p class="bad">${esc(r.error)} <button type="button" data-report="banner">Report this</button></p><p class="note">Nothing else changed. You can always do it by hand with the steps above.</p>`;
  return `<p class="ok">${esc(r.done)}</p>${(r.by_hand || []).length ? `<ul>${r.by_hand.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    ${r.done && T.daw !== 'ardour' ? '<p class="note">Changed your mind? Undo it in your DAW (Cmd+Z / Ctrl+Z).</p>' : ''}`;
}

// The lesson is drawn again after most clicks: the control that had the keyboard gets it back (a pending "Do it" gets it when its button is new).
function teachRedraw() {
  const y = window.scrollY, m = $('#main'), fk = focusKey(m);
  teachView().then(h => {
    if (S.view !== 'teach') return;
    m.innerHTML = h; window.scrollTo(0, y);
    if (!restoreFocus(m, fk) && fk && T.pending) { const d = m.querySelector('[data-tdo]'); if (d) d.focus({preventScroll: true}); }
  });
}
// After the person moves to another step the keyboard goes to its title, so the next Tab starts in the lesson and a screen reader says where it is.
function teachFocus() { const h = document.querySelector('.lesson h1'); if (h) { h.tabIndex = -1; h.focus({preventScroll: true}); } }

async function teachMark(id, done, at) { T.st = await post('/api/teach/mark', {daw: T.daw, step: id, done, at, level: T.level}); }

document.addEventListener('click', async e => {
  const b = e.target.closest('[data-tgloss],[data-tjump],[data-thear],[data-tquiz],[data-tlevel],[data-tdaw],[data-tstep],[data-tgo],[data-tnext],[data-task],[data-task-do],[data-tdo],[data-tcancel],[data-tstop],#tmode');
  if (!b || !b.closest('main')) return;
  const ds = b.dataset;
  if (b.tagName === 'A') e.preventDefault();                 // these links are real links (the keyboard reaches them); they go nowhere by themselves
  try {
    if (ds.thear) return teachPlay(b);
    if (ds.tgloss) { T.view = 'glossary'; T.gl = null; T.glq = ''; teachRedraw(); const r = await get('/api/teach/glossary?daw=' + encodeURIComponent(T.daw || '')); T.gl = r.terms; return teachRedraw(); }
    if (ds.tjump) return teachJump(ds.tjump);
    if (ds.tquiz) {
      const [sid, qi, oi] = ds.tquiz.split(':'), s = tsteps().find(x => x.id === sid);
      (T.quiz[sid] = T.quiz[sid] || {})[+qi] = +oi;
      const done = s.quiz.every((q, k) => T.quiz[sid][k] === q.answer);
      if (done && !T.st.done.includes(sid)) await teachMark(sid, true, T.at);
      return teachRedraw();
    }
    if (ds.tdaw) { T.view = ''; T.daw = ds.tdaw; T.at = ''; T.pending = null; T.result = {}; await post('/api/setup/daw', {daw: ds.tdaw}); return teachRedraw(); }
    if (ds.tlevel) { T.view = ''; T.level = ds.tlevel; T.at = ''; T.pending = null; if (T.st && T.st.teach) await post('/api/setup/daw', {teach_level: ds.tlevel}); return teachRedraw(); }
    if (b.id === 'tmode') { await post('/api/setup/daw', {teach_level: b.checked ? T.level : ''}); return; }
    if (ds.tstep) { T.at = ds.tstep; T.pending = null; await teachMark('', true, T.at); await render(); window.scrollTo(0, 0); teachFocus(); return; }
    const all = tsteps(), i = all.findIndex(s => s.id === T.at);
    if (ds.tgo) { T.at = all[Math.max(0, i - 1)].id; T.pending = null; await teachMark('', true, T.at); await render(); window.scrollTo(0, 0); teachFocus(); return; }
    if (ds.tnext) { const nx = all[Math.min(all.length - 1, i + 1)].id; await teachMark(ds.tnext, true, nx); T.at = nx; T.pending = null; await render(); window.scrollTo(0, 0); teachFocus(); return; }
    if (ds.task) {
      const s = all[i];
      if (typeof C !== 'undefined') C.draft = `I'm on the Teacher tab in ${T.st.daws[T.daw]}, at "${s.title}" (${s.chapter.title}). Explain this step to me simply, then tell me exactly what to click.`;
      return go('chat');
    }
    if (ds.taskDo) {
      const s = all.find(x => x.id === ds.taskDo), args = {};
      (s.action.fields || []).forEach(f => { args[f.id] = fieldVal(s, f.id); });
      T.pending = {step: s.id, args, will: fill(s.action.will, s)};
      return teachRedraw();
    }
    if (ds.tcancel) { T.pending = null; return teachRedraw(); }
    if (ds.tdo || ds.tstop) {
      const s = all.find(x => x.id === (ds.tdo || ds.tstop));
      const kind = ds.tstop ? 'stop' : s.action.kind, args = ds.tstop ? {} : T.pending.args;
      T.busy = true; teachRedraw();
      try { T.result[s.id] = await post('/api/teach/do', {ok: true, daw: T.daw, step: s.id, kind, args}); }
      catch (err) { T.result[s.id] = {error: err.message}; }
      T.busy = false; T.pending = null;
      if (kind === 'record') setTimeout(function poll() { teachLoad(T.daw).then(() => { if (S.view === 'teach') teachRedraw(); if (T.st.recording.busy) setTimeout(poll, 1500); }); }, 1500);
      return teachRedraw();
    }
  } catch (err) { alert(err.message); }
});

document.addEventListener('input', e => {
  if (e.target.id !== 'tgq') return;
  T.glq = e.target.value; const l = document.getElementById('tgl'); if (l) l.innerHTML = glossaryList();
});

window.teachChanged = () => { T.st = null; T.daw = ''; T.level = ''; T.at = ''; if (S.view === 'teach') render(); };
// teacher mode on: the app opens on this tab
get('/api/teach/state').then(st => { if (st.teach && st.daw && S.view === 'home') go('teach'); }).catch(() => {});

// "Take the tour inside the HypnoMix Studio": the DAW view opens with its list of tours (hypnomix/app/daw/js/tour.js reads the #tour in the address)
document.addEventListener('click', e => { if (e.target.closest('[data-tdawtour]')) location.href = '/daw/#tour'; });
