// The Teacher tab (hypnomix/app/teacher.py): a step-by-step course from an empty song to a master, in the DAW the
// person chose in Setup. Uses the page's own helpers: $, esc, get, post, go, S, render.
// Every hands-on action first says exactly what it will change and waits for "Do it".
const T = {st: null, daw: '', level: '', at: '', pending: null, result: {}, busy: false};

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
  const pick = `<div class="daws">${Object.entries(st.daws).map(([k, v]) => `<button data-tdaw="${k}" class="${k === T.daw ? 'sel' : ''}">${esc(v)}</button>`).join('')}</div>`;
  const lv = `<div class="daws">${[['tour', 'Tour: hypnomix in ' + (st.daws[T.daw] || 'your DAW')], ['101', '101 crash course']].map(([k, v]) => `<button data-tlevel="${k}" class="${k === T.level ? 'sel' : ''}" title="${k === 'tour' ? 'for people who already record and mix' : 'for people new to audio: the basics first, then the tour'}">${esc(v)}</button>`).join('')}</div>`;
  if (!T.daw) return `<h1>Teacher</h1><p class="sub">A step-by-step course for people who have never used a DAW: from an empty song to a mastered one.</p>
    <div class="card"><p style="margin-top:0">Which DAW will you use? The lessons, and the Wiki, follow your choice.</p>${pick}
    <p class="note">Ableton Live has the most depth, REAPER a little less, and Ardour the short version (it's the least tested with hypnomix).</p></div>`;
  const all = tsteps(), i = Math.max(0, all.findIndex(s => s.id === T.at)), s = all[i];
  const nav = st.chapters.map((c, ci) => `<h4>${ci + 1} · ${esc(c.title)}</h4>` + c.steps.map(x =>
    `<a data-tstep="${esc(x.id)}" class="${x.id === s.id ? 'on' : ''} ${st.done.includes(x.id) ? 'done' : ''}"><i>${st.done.includes(x.id) ? '✓' : '○'}</i>${esc(x.title)}</a>`).join('')).join('');
  const ai = st.mode === 'key' || st.mode === 'local';
  return `<div class="teach"><aside>${pick}${lv}
    <label class="note" style="display:flex;gap:6px;align-items:center;margin:6px 0"><input type="checkbox" id="tmode" ${st.teach ? 'checked' : ''}> Teacher mode: open on this tab, and the Assistant teaches this course</label>
    <p class="note">${st.done.length} of ${all.length} steps done</p><nav>${nav}</nav></aside>
    <div class="lesson">${lessonHTML(s, i, all.length)}
      <div class="nav"><button data-tgo="-1" ${i ? '' : 'disabled'}>Back</button>
        <span>${ai ? `<button data-task="${esc(s.id)}" title="Opens the Assistant with a question about this step; nothing is sent until you press Send">Ask the Assistant</button> ` : ''}
        <button class="primary" data-tnext="${esc(s.id)}">${i === all.length - 1 ? 'Done: finish the course' : st.done.includes(s.id) ? 'Next step' : 'Done, next step'}</button></span></div></div></div>`;
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
  if (s.action) h += actionHTML(s);
  else if (T.daw === 'ardour' && ['tempo', 'click', 'drums', 'track', 'take', 'chain'].includes(s.id)) h += `<p class="note">hypnomix can't drive Ardour yet, so this one is by hand: the steps above say where.</p>`;
  if (s.app) h += `<p><button data-view="${esc(s.app.view)}">${esc(s.app.label)}</button></p>`;
  if (r) h += resultHTML(r);
  return h;
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
  return `<div class="do"><b>Let hypnomix do it</b> <span class="note">· ${a.changes ? 'changes your song, after you say yes' : 'changes nothing'}</span>${fields}
    ${p ? `<div class="sure">${T.pending.will}</div><button class="primary" data-tdo="${esc(s.id)}" ${T.busy ? 'disabled' : ''}>${T.busy ? 'Working…' : 'Do it'}</button> <button data-tcancel="1">Not now</button>`
        : `<button data-task-do="${esc(s.id)}" ${rec ? 'disabled' : ''}>${esc(a.label)}…</button>${a.kind === 'record' && T.daw === 'reaper' ? ' <button data-tstop="' + esc(s.id) + '">Stop</button>' : ''}`}
    ${rec ? '<p class="note">Recording…</p>' : T.st.recording && T.st.recording.msg && a.kind === 'record' ? `<p class="note">${esc(T.st.recording.msg)}</p>` : ''}</div>`;
}

function resultHTML(r) {
  if (r.error) return `<p class="bad">${esc(r.error)}</p><p class="note">Nothing else changed. You can always do it by hand with the steps above.</p>`;
  return `<p class="ok">${esc(r.done)}</p>${(r.by_hand || []).length ? `<ul>${r.by_hand.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    ${r.done && T.daw !== 'ardour' ? '<p class="note">Changed your mind? Undo it in your DAW (Cmd+Z / Ctrl+Z).</p>' : ''}`;
}

function teachRedraw() { const y = window.scrollY; teachView().then(h => { if (S.view === 'teach') { $('#main').innerHTML = h; window.scrollTo(0, y); } }); }

async function teachMark(id, done, at) { T.st = await post('/api/teach/mark', {daw: T.daw, step: id, done, at, level: T.level}); }

document.addEventListener('click', async e => {
  const b = e.target.closest('[data-tlevel],[data-tdaw],[data-tstep],[data-tgo],[data-tnext],[data-task],[data-task-do],[data-tdo],[data-tcancel],[data-tstop],#tmode');
  if (!b || !b.closest('main')) return;
  const ds = b.dataset;
  try {
    if (ds.tdaw) { T.daw = ds.tdaw; T.at = ''; T.pending = null; T.result = {}; await post('/api/setup/daw', {daw: ds.tdaw}); return teachRedraw(); }
    if (ds.tlevel) { T.level = ds.tlevel; T.at = ''; T.pending = null; if (T.st && T.st.teach) await post('/api/setup/daw', {teach_level: ds.tlevel}); return teachRedraw(); }
    if (b.id === 'tmode') { await post('/api/setup/daw', {teach_level: b.checked ? T.level : ''}); return; }
    if (ds.tstep) { T.at = ds.tstep; T.pending = null; await teachMark('', true, T.at); render(); window.scrollTo(0, 0); return; }
    const all = tsteps(), i = all.findIndex(s => s.id === T.at);
    if (ds.tgo) { T.at = all[Math.max(0, i - 1)].id; T.pending = null; await teachMark('', true, T.at); render(); window.scrollTo(0, 0); return; }
    if (ds.tnext) { const nx = all[Math.min(all.length - 1, i + 1)].id; await teachMark(ds.tnext, true, nx); T.at = nx; T.pending = null; render(); window.scrollTo(0, 0); return; }
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

window.teachChanged = () => { T.st = null; T.daw = ''; T.level = ''; T.at = ''; if (S.view === 'teach') render(); };
// teacher mode on: the app opens on this tab
get('/api/teach/state').then(st => { if (st.teach && st.daw && S.view === 'home') go('teach'); }).catch(() => {});
