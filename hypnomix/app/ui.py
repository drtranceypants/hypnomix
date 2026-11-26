"""The hypnomix app's page: one file, no network access beyond this computer."""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>hypnomix</title>
<style>
:root{--bg:#f6f4ef;--card:#fff;--ink:#1d1b18;--mute:#6b665e;--line:#e2ddd2;--hi:#b3261e;--med:#a8640a;--low:#3d6b4f;
--info:#5a6472;--ok:#2f6f4f;--skip:#7a756c;--chg:#8a5a00;--accent:#8e3f3f;--accent-ink:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--card:#201f1c;--ink:#ece8df;--mute:#a09a8e;--line:#34322d;
--hi:#ff8a80;--med:#f0b455;--low:#8fc7a4;--info:#9aa6b6;--ok:#7fd0a4;--skip:#a09a8e;--chg:#f0b455;--accent:#e9b4b0;--accent-ink:#1d1b18}}
*{box-sizing:border-box}html,body{margin:0}body{background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);display:flex;gap:4px;
align-items:center;padding:8px 16px;flex-wrap:wrap}
header .brand{font-weight:700;letter-spacing:.14em;text-transform:uppercase;margin-right:12px}
header nav{display:flex;gap:4px;flex-wrap:wrap}header .live{margin-left:auto;font-size:.82rem;color:var(--mute)}
header .live b{color:var(--ok)}
main{max-width:900px;margin:0 auto;padding:20px 16px 140px}
h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.1rem;margin:28px 0 8px}.sub{color:var(--mute);margin:0 0 16px}
button,.btn{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;
padding:7px 13px;cursor:pointer}button:hover{border-color:var(--mute)}button:disabled{opacity:.5;cursor:default}
button.primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent);font-weight:600}
button.tab{border-color:transparent;background:none}button.tab.on{border-color:var(--line);background:var(--card);font-weight:600}
button.on.approve{background:var(--ok);color:#fff;border-color:var(--ok)}
button.on.skip{background:var(--skip);color:#fff;border-color:var(--skip)}
button.on.change{background:var(--chg);color:#fff;border-color:var(--chg)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:12px 0}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0}.row label{min-width:150px;color:var(--mute)}
input[type=text],select,textarea{font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:8px;
background:var(--bg);color:var(--ink);flex:1;min-width:200px}
.path{flex:1;min-width:200px;color:var(--mute);overflow-wrap:anywhere;font-size:.92rem}
.note{font-size:.88rem;color:var(--mute);margin:6px 0 0}.warn{border-left:3px solid var(--hi);padding:4px 12px;margin:0 0 14px}
.prefs{border-left:3px solid var(--accent);padding:4px 12px;margin:0 0 14px;color:var(--mute)}
.bar{position:sticky;top:49px;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);display:flex;gap:8px;
flex-wrap:wrap;align-items:center;z-index:2}.bar .count{margin-right:auto;font-variant-numeric:tabular-nums}
.item.done{opacity:.72}.head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.sev{font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.sev.high{color:var(--hi)}.sev.medium{color:var(--med)}.sev.low{color:var(--low)}.sev.info{color:var(--info)}
.tag{font-size:.75rem;border:1px solid var(--line);border-radius:99px;padding:1px 8px;color:var(--mute)}
.tag.prot{border-color:var(--hi);color:var(--hi)}.where{color:var(--mute);font-variant-numeric:tabular-nums}
.title{font-weight:600}.fix{color:var(--mute);margin:6px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}
pre{font:13px/1.45 ui-monospace,monospace;background:var(--card);border:1px solid var(--line);padding:10px;border-radius:8px;
overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;max-height:60vh;margin:8px 0}
pre.fix{max-height:220px;background:var(--bg)}
.ab{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0 0}.ab label{font-size:.8rem;color:var(--mute);display:block}
.ab audio{width:100%}.act{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 0}.act input{flex:1;min-width:160px}
.song{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.song .name{font-weight:600;margin-right:auto}
.meter{display:inline-block;height:8px;background:var(--line);width:120px;border-radius:4px;overflow:hidden;vertical-align:middle}
.meter i{display:block;height:100%;background:var(--ok,#5a9)}.bands{display:inline-flex;gap:2px;align-items:flex-end;height:22px;vertical-align:middle}
.bands i{display:block;width:7px;background:var(--mute)}.num{font-variant-numeric:tabular-nums;white-space:nowrap}
table{border-collapse:collapse;width:100%}
__OVCSS__td{padding:6px 8px;border-top:1px solid var(--line);vertical-align:top}
td code{font:13px ui-monospace,monospace}tr.cmd{cursor:pointer}tr.cmd:hover td{background:var(--bg)}
.grp td{font-weight:700;border-top:2px solid var(--line);padding-top:14px}
.spin{display:inline-block;width:12px;height:12px;border:2px solid var(--line);border-top-color:var(--accent);border-radius:50%;
animation:sp 1s linear infinite;vertical-align:-1px;margin-right:6px}@keyframes sp{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.spin{animation:none}}
@media (max-width:560px){.ab{grid-template-columns:1fr}.row label{min-width:100%}}
</style></head><body>
<header><span class="brand">hypnomix</span>
<nav><button class="tab" data-view="teach" title="Teacher: make a song from scratch, step by step, in your DAW">Teacher</button><button class="tab" data-view="home">Songs</button><button class="tab" data-view="prefs">Preferences</button>
<button class="tab" data-view="chat">Assistant</button><button class="tab" data-view="wiki">Wiki</button><button class="tab" data-view="live">Live</button><button class="tab" data-view="tools">Tools</button><button class="tab" data-view="job" id="jobtab" hidden>Activity</button><button class="tab" data-setup title="How you work with hypnomix: AI provider, keys, your DAW, teacher mode">Setup</button></nav>
<span class="live" id="live"></span></header>
<main id="main"></main>
<script>
const TOKEN = "__TOKEN__";
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const get = (u) => fetch(u).then(r => r.json());
const post = (u, body) => fetch(u, {method:'POST', headers:{'Content-Type':'application/json','X-Hypnomix':TOKEN},
  body: JSON.stringify(body || {})}).then(async r => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || r.statusText); return j; });
let S = {view:'home', state:null, form:{source:'', mix:'', key:'', like:'', deep:false, devices:true}, review:null, logAt:0, logLines:[], tool:null};

__OVJS__
function go(view, extra) { Object.assign(S, extra || {}); S.view = view; render(); window.scrollTo(0, 0); }
document.addEventListener('click', e => { const t = e.target.closest('button[data-view]'); if (t) go(t.dataset.view); });

async function refresh() {
  try { S.state = await get('/api/state'); } catch (e) { return; }
  $('#live').innerHTML = S.state.live ? '<b>●</b> Live device connected' : 'Live device not connected';
  $('#jobtab').hidden = S.state.job.status === 'idle';
  document.querySelectorAll('button.tab').forEach(b => b.classList.toggle('on', b.dataset.view === S.view || (S.view === 'review' && b.dataset.view === 'home')));
}

// ---------------------------------------------------------------- home
function homeView() {
  const st = S.state, f = S.form;
  const songs = st.scans.map(s => `<div class="card song"><span class="name">${esc(s.name)}</span>
    <span class="note">${s.findings} to review · ${s.decided} decided · ${s.approved} approved${s.applied ? ' · applied' : ''} · ${esc(s.when)}</span>
    <button data-open="${esc(s.dir)}">Open review</button></div>`).join('') || '<p class="note">No songs yet.</p>';
  return `<h1>First pass on a song</h1>
  <p class="sub">Every check runs at once. Nothing is changed. You then hear each proposed fix and decide.</p>
  ${st.unanswered ? `<div class="prefs">${st.unanswered} preference question(s) not answered yet. <button data-view="prefs">Answer them</button> so the review starts from how you work.</div>` : ''}
  <div class="card">
    <div class="row"><label>Song</label><span class="path">${esc(f.source) || 'a Live set, or a folder of recordings or stems from any DAW'}</span>
      <button data-pick="source:set">Choose set…</button><button data-pick="source:folder">Choose folder…</button></div>
    <div class="row"><label>Bounce of the mix <span class="note">(optional)</span></label><span class="path">${esc(f.mix) || 'adds loudness, release checks and the key'}</span>
      <button data-pick="mix:audio">Choose…</button>${f.mix ? '<button data-clear="mix">Clear</button>' : ''}</div>
    <div class="row"><label>A song you love <span class="note">(optional)</span></label><span class="path">${esc(f.like) || 'compare tone, dynamics and width with it'}</span>
      <button data-pick="like:audio">Choose…</button>${f.like ? '<button data-clear="like">Clear</button>' : ''}</div>
    <div class="row"><label for="key">Key <span class="note">(optional)</span></label><input type="text" id="key" placeholder='e.g. F# major: needed before any vocal tuning is applied' value="${esc(f.key)}"></div>
    <div class="row"><label for="deep">Deep scan</label><input type="checkbox" id="deep" ${f.deep ? 'checked' : ''}> <span class="note">also render every track: frequency fights and mic phase (slower)</span></div>
    ${/\.als$/i.test(f.source || '') ? `<div class="row"><label for="devices">Live devices</label><input type="checkbox" id="devices" ${f.devices ? 'checked' : ''}> <span class="note">also write a copy of the set with the hypnomix devices on every track (probes, the review device, HypnomixMain on Main), next to yours</span></div>` : ''}
    ${!st.mac ? `<div class="row"><label for="src">Path</label><input type="text" id="src" placeholder="paste the path of a set or folder" value="${esc(f.source)}"></div>` : ''}
    <div class="row"><button class="primary" id="scan" ${f.source ? '' : 'disabled'}>Start the first pass</button>
      <span class="note">Read-only. Close nothing: your set is not touched${/\.als$/i.test(f.source || '') && f.devices ? ' (the devices go into a new copy)' : ''}.</span></div>
  </div>
  <h2>Your songs</h2>${songs}
  <p class="note">Kept in ${esc(st.home)}</p>`;
}

// ---------------------------------------------------------------- activity
function jobView() {
  const j = S.state.job;
  const running = j.status === 'running';
  return `<h1>${esc(j.title || 'Activity')}</h1>
  <p class="sub">${running ? `<span class="spin"></span>${esc(j.step)}…` : j.status === 'done' ? 'Finished.' : j.status === 'failed' ? 'Stopped with an error: the last lines say why.' : ''}</p>
  <div class="row">${running ? '<button id="stop">Stop</button>' : ''}
    ${!running && j.dir ? `<button class="primary" data-open="${esc(j.dir)}">${j.kind === 'fix' ? 'Back to the review' : 'Open the review'}</button>` : ''}</div>
  <pre id="log" aria-live="polite">${esc(S.logLines.join('\n'))}</pre>`;
}
async function pollJob() {
  if (!S.state || S.state.job.status === 'idle') return;
  const j = await get('/api/job?since=' + S.logAt);
  if (j.id !== S.jobId) { S.jobId = j.id; S.logLines = []; S.logAt = 0; return; }
  if (j.log.length) { S.logLines.push(...j.log); S.logAt = j.total; const el = $('#log'); if (el) { el.textContent = S.logLines.join('\n'); el.scrollTop = el.scrollHeight; } }
  if (S.lastStatus === 'running' && j.status !== 'running') {
    await refresh();
    if (S.view === 'job') { if (j.status === 'done' && j.dir && j.kind !== 'tool') openReview(j.dir); else render(); }
  }
  S.lastStatus = j.status;
}

// ---------------------------------------------------------------- review
async function openReview(dir) { S.review = await get('/api/review?dir=' + encodeURIComponent(dir)); go('review'); }
function reviewView() {
  const R = S.review, dec = R.decisions;
  const actionable = R.findings.filter(f => f.applies !== 'info' && f.applies !== 'answer');
  const n = {approve:0, skip:0, change:0};
  actionable.forEach(f => { const d = dec[f.id] && dec[f.id].decision; if (d) n[d]++; });
  const left = actionable.length - n.approve - n.skip - n.change;
  const top = (R.broken.length ? '<div class="warn"><b>Checks that did NOT run</b> (no findings there means nothing):<br>' + R.broken.map(esc).join('<br>') + '</div>' : '')
    + (R.prefs.length ? '<div class="prefs">' + R.prefs.map(esc).join('<br>') + '</div>' : '');
  const ovc = R.oversight && !R.oversight.error ? {ov: R.oversight, dec, notes: R.oversight.notes || {}, esc, findings: R.findings} : null;
  const inBatch = new Set(ovc && ovc.ov.budget ? ovc.ov.budget.batch : []);
  const card = f => {
    const d = dec[f.id] && dec[f.id].decision, ab = R.ab[f.id] || {}, fix = String(f.fix || '');
    const src = x => '/audio?dir=' + encodeURIComponent(R.dir) + '&f=' + encodeURIComponent(x);
    const players = ab.a ? `<div class="ab"><div><label>A · now</label><audio controls preload="none" src="${src(ab.a)}"></audio></div>
      <div><label>B · with the fix${ab.matched_db ? ' (level-matched ' + (ab.matched_db > 0 ? '+' : '') + ab.matched_db + ' dB)' : ''}</label><audio controls preload="none" src="${src(ab.b)}"></audio></div></div>` : '';
    const note = ab.note ? `<p class="note">${esc(ab.note)}</p>` : ((f.applies === 'set' || f.applies === 'audio') && !ab.a ? '<p class="note">No before / after clip for this kind of fix: apply it and listen in Live.</p>' : '');
    const jump = f.jump ? `<button data-jump="${esc(f.id)}" title="Needs the hypnomix device in your Live set">Show in Live</button>` : '';
    const act = f.applies === 'answer' ? '<p class="note">A question, not a fix: put your answer in the box when you apply.</p>'
      : f.applies === 'info' ? (jump ? `<div class="act">${jump}</div>` : '') : `<div class="act">
      ${['approve','skip','change'].map(x => `<button class="${x}${d === x ? ' on' : ''}" data-id="${esc(f.id)}" data-d="${x}" aria-pressed="${d === x}">${x[0].toUpperCase() + x.slice(1)}</button>`).join('')}
      ${jump}<input type="text" aria-label="note for ${esc(f.id)}" placeholder="note (what to change, or why)" data-note="${esc(f.id)}" value="${esc(dec[f.id] && dec[f.id].note)}"></div>`;
    return `<div class="card item${d ? ' done' : ''}" id="f-${esc(f.id)}"><div class="head"><span class="sev ${esc(f.severity)}">${esc(f.severity)}</span>
      <span class="title">${esc(f.track || f.tool)}</span><span class="where">${esc(f.where || '')}</span>
      <span class="tag">${esc(f.tool)} · ${esc(f.applies)}</span><span class="tag">${esc(f.id)}</span>
      ${f.protected ? '<span class="tag prot">protected: ask again</span>' : ''}
      ${R.ab_live && R.ab_live.items[f.id] && R.ab_live.items[f.id].parts.length ? '<span class="tag">A/B in Live</span>' : ''}</div>
      <div>${esc(f.problem)}</div>
      ${fix.includes('\n') ? `<pre class="fix">${esc(fix)}</pre>` : `<p class="fix">Proposed: ${esc(fix)}</p>`}
      ${f.history ? `<p class="note">${esc(f.history)}</p>` : ''}${players}${note}${blindNote(R, f.id)}${act}
      ${ovc ? ovItemHTML(f, ovc) : ''}</div>`;
  };
  const items = R.findings.filter(f => !inBatch.has(f.id)).map(card).join('') + (ovc ? ovBatchHTML(ovc, card) : '');
  const prot = actionable.some(f => f.protected && dec[f.id] && dec[f.id].decision === 'approve');
  const tune = actionable.some(f => f.tool === 'tune' && dec[f.id] && dec[f.id].decision === 'approve');
  const apply = `<h2>Apply</h2><div class="card">
    <p style="margin-top:0">${n.approve} approved fix(es) will be written ${R.is_set ? 'into <b>one new set</b> next to the original. The original is not changed. <b>Close the set in Live first.</b>' : 'as repaired copies in this scan\'s "fixed" folder. Your files are not changed.'}</p>
    ${R.is_set ? `<div class="row"><label for="out">New set name</label><input type="text" id="out" value="${esc(R.suggested_out)}"></div>` : ''}
    ${tune ? `<div class="row"><label for="fkey">Confirmed key</label><input type="text" id="fkey" placeholder='needed for vocal tuning, e.g. F# major (or "sections")' value="${esc(S.form.key)}"></div>` : ''}
    ${prot ? '<div class="row"><label for="prot">Protected tracks</label><input type="checkbox" id="prot"> <span class="note">yes, change the protected tracks I approved</span></div>' : ''}
    <div class="row"><button class="primary" id="apply" ${n.approve ? '' : 'disabled'}>Apply ${n.approve} approved</button>
      <button data-reveal="${esc(R.dir)}">Show files</button><span class="note">${left ? left + ' still undecided (they are left alone).' : ''}</span></div>
    ${R.fix_log ? `<h2>Last time it was applied</h2><pre>${esc(R.fix_log)}</pre>` : ''}</div>`;
  return `<h1>Review: ${esc(R.name)}</h1>
  <p class="sub">Nothing has been changed. Listen, decide each item, then apply only what you approved.</p>${top}${abLiveCard(R)}
  <div class="bar"><span class="count">${n.approve} approved · ${n.skip} skipped · ${n.change} to change · ${left} undecided</span>
    <button id="alllow" title="Low-severity items that are not protected">Approve all low</button></div>
  ${items || '<p class="note">No findings.</p>'}${apply}`;
}
function blindNote(R, id) {
  const rows = (R.blind || []).filter(r => r.id === id);
  if (!rows.length) return '';
  const b = rows.filter(r => r.chose === 'B').length;
  return `<p class="note">Blind test in Live: you chose the fix ${b} of ${rows.length} time(s)${b * 2 > rows.length ? ', so approving it matches your ears' : b * 2 < rows.length ? ': you preferred what you have' : ''}.</p>`;
}
function abLiveCard(R) {
  if (!R.is_set) return '';
  const ready = R.ab_live ? `<p style="margin-top:0"><b>Ready:</b> ${esc(R.ab_live.set.split('/').pop())}. Close the original in Live, open this set, put the hypnomix device on any track, then use <b>A · now</b>, <b>B · fix</b> and <b>Blind</b> on each finding. Every plug-in plays; nothing is rendered.</p>` : '';
  return `<div class="card">${ready || '<p style="margin-top:0">Hear every fix inside Live, with all your plug-ins, by switching A and B instantly.</p>'}
    <div class="row"><button id="abbuild">${R.ab_live ? 'Build it again' : 'Build A/B set for Live'}</button><span class="note">Writes one new set next to the original; the original is not changed.</span></div></div>`;
}
async function decide(id, d, note) {
  const R = S.review;
  R.decisions[id] = {decision: d, note: note || (R.decisions[id] && R.decisions[id].note) || ''};
  try { await post('/api/decide', {dir: R.dir, id, decision: d, note: R.decisions[id].note}); } catch (e) { alert('Could not save: ' + e.message); }
}

// ---------------------------------------------------------------- preferences
async function prefsView() {
  const qs = await get('/api/prefs');
  return `<h1>Preferences</h1><p class="sub">Asked once. They shape what is proposed; taste calls are still always asked.</p>
  <div class="card">${qs.map(q => {
    const v = Array.isArray(q.value) ? q.value.join(', ') : (q.value == null ? '' : q.value);
    const field = q.options ? `<select data-pref="${esc(q.key)}"><option value="">(not answered: ${esc(q.default)})</option>${q.options.map(o => `<option ${String(o) === String(v) ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`
      : `<input type="text" data-pref="${esc(q.key)}" value="${esc(v)}" placeholder="names, separated by commas">`;
    return `<div class="row" style="align-items:flex-start"><label style="min-width:100%;color:var(--ink)">${esc(q.ask)}</label>${field}<p class="note" style="min-width:100%;margin:0">${esc(q.why)}</p></div>`;
  }).join('')}
  <div class="row"><button class="primary" id="saveprefs">Save</button><span class="note" id="saved"></span></div></div>`;
}

// ---------------------------------------------------------------- live (probes)
function liveRows(P) {
  if (!P.tracks.length) return '<p class="note">No probes are sending. In Live: put <b>HypnomixProbe</b> last on each track and on Main (install it with <code>hypnomix probe device</code>; <code>hypnomix probe insert SET.als</code>, or the first pass with Live devices ticked, writes a copy of the set with it on every track), then press play.</p>';
  const band = b => b.map(x => `<i style="height:${Math.max(1, Math.min(22, (x + 70) / 3))}px"></i>`).join('');
  return '<table><tr><td>Track</td><td>Told in Live</td><td>Loudness now</td><td class="num">short-term</td><td class="num">peak</td><td>tone (sub → air)</td><td class="num">L/R</td></tr>'
    + P.tracks.map(t => `<tr${t.live ? '' : ' style="opacity:.5"'}><td>${t.main ? '<b>Main</b>' : esc(t.name)}</td>
      <td class="note">${esc(t.main ? [t.card.genre, t.card.key && t.card.key !== 'not set' ? t.card.key + ' ' + (t.card.scale || '') : '', t.card.target != null ? t.card.target + ' LUFS' : ''].filter(x => x && x !== 'not set').join(' · ') : [t.card.role, t.card.priority && t.card.priority !== 'normal' ? t.card.priority.split(':')[0] : '', String(t.card.protect || '').startsWith('on') ? 'protected' : ''].filter(x => x).join(' · '))}</td>
      <td>${t.momentary != null && t.momentary > -100 ? `<span class="meter"><i style="width:${Math.max(0, Math.min(100, (t.momentary + 60) / 0.6))}%"></i></span> <span class="num">${t.momentary.toFixed(1)}</span>` : '<span class="note">silent</span>'}</td>
      <td class="num">${t.short != null && t.short > -100 ? t.short.toFixed(1) + ' LUFS' : ''}</td><td class="num">${t.peak != null && t.peak > -100 ? t.peak.toFixed(1) + ' dB' : ''}</td>
      <td>${t.bands ? `<span class="bands">${band(t.bands)}</span>` : ''}</td><td class="num">${t.corr != null ? t.corr.toFixed(2) : ''}</td></tr>`).join('') + '</table>';
}
function liveView() {
  const P = S.probe || {tracks: [], recording: false, error: ''};
  return `<h1>Live: measure while you play</h1>
  <p class="sub">Every track at once, after all of its plug-ins. Nothing is rendered or exported, and nothing in the set is changed.</p>
  ${P.error ? `<div class="warn">The probe receiver is not running: ${esc(P.error)}</div>` : ''}
  <div class="card"><div class="row">
    ${P.recording ? '<button class="primary" id="probestop">Stop and review</button><span class="note"><span class="spin"></span>recording what the probes hear…</span>'
                  : '<button class="primary" id="probestart">Record</button><span class="note">Press Record, play the song (or the part you are working on) in Live, then Stop. A review is made from what was heard.</span>'}
  </div></div>
  <div id="probes">${liveRows(P)}</div>`;
}
async function pollProbe() {
  if (S.view !== 'live') return;
  try { S.probe = await get('/api/probe/status'); } catch (e) { return; }
  const el = $('#probes'); if (el) el.innerHTML = liveRows(S.probe);
}

// ---------------------------------------------------------------- tools
function toolsView() {
  const st = S.state;
  if (S.tool) {
    const c = st.commands.find(x => x.name === S.tool);
    return `<p><button id="backtools">← All tools</button></p><h1>hypnomix ${esc(c.name)}</h1><p class="sub">${esc(c.about)}</p>
    <div class="card"><div class="row"><label for="args">Options</label><input type="text" id="args" placeholder='what you would type after "hypnomix ${esc(c.name)}"' value="${esc(S.toolArgs || '')}"></div>
    <div class="row"><button data-toolpick="set">Add a set…</button><button data-toolpick="audio">Add an audio file…</button><button data-toolpick="folder">Add a folder…</button>
    <button class="primary" id="runtool">Run</button></div>
    <p class="note">Tools that write a set always write a NEW one. Read the options below first.</p></div>
    <pre>${esc(S.toolHelp || 'loading…')}</pre>`;
  }
  let last = '';
  const rows = st.commands.map(c => (c.group !== last ? (last = c.group, `<tr class="grp"><td colspan="2">${esc(c.group)}</td></tr>`) : '')
    + `<tr class="cmd" data-tool="${esc(c.name)}" tabindex="0"><td><code>${esc(c.name)}</code></td><td>${esc(c.about)}</td></tr>`).join('');
  return `<h1>Tools</h1><p class="sub">Every hypnomix command. Choose one to see its options and run it.</p><table>${rows}</table>`;
}

// ---------------------------------------------------------------- render + events
async function render() {
  if (!S.state) await refresh();
  const m = $('#main');
  if (S.view === 'home') m.innerHTML = homeView();
  else if (S.view === 'job') m.innerHTML = jobView();
  else if (S.view === 'review') m.innerHTML = reviewView();
  else if (S.view === 'prefs') m.innerHTML = await prefsView();
  else if (S.view === 'tools') m.innerHTML = toolsView();
  else if (S.view === 'chat') { m.innerHTML = chatView(); chatPoll(true).catch(() => {}); }
  else if (S.view === 'wiki') { m.innerHTML = await wikiView(); wikiAfter(); }
  else if (S.view === 'teach') m.innerHTML = await teachView();
  else if (S.view === 'live') { await pollProbe(); m.innerHTML = liveView(); }
  refresh();
}
document.addEventListener('click', async e => {
  const b = e.target.closest('button, tr.cmd'); if (!b || b.closest('.wa')) return;   // an article's own markup never drives the app's buttons
  const ds = b.dataset;
  try {
    if (ds.pick) { const [field, kind] = ds.pick.split(':'); const r = await post('/api/pick', {kind}); if (r.path) { S.form[field] = r.path; render(); } }
    else if (ds.clear) { S.form[ds.clear] = ''; render(); }
    else if (b.id === 'scan') {
      const src = $('#src'); if (src && src.value) S.form.source = src.value;
      S.form.key = $('#key').value; S.form.deep = $('#deep').checked; if ($('#devices')) S.form.devices = $('#devices').checked;
      await post('/api/scan', S.form); S.logLines = []; S.logAt = 0; S.lastStatus = 'running'; await refresh(); go('job');
    }
    else if (ds.open) await openReview(ds.open);
    else if (ds.id) { const note = document.querySelector(`input[data-note="${CSS.escape(ds.id)}"]`); await decide(ds.id, ds.d, note ? note.value : ''); const y = window.scrollY; $('#main').innerHTML = reviewView(); window.scrollTo(0, y); }
    else if (ds.jump) { const r = await post('/api/live/jump', {dir: S.review.dir, id: ds.jump}); if (!r.device) alert('Sent, but the hypnomix device is not connected. Load it on any track in your Live set (run "hypnomix device" to make it).'); }
    else if (b.id === 'alllow') {
      const ids = S.review.findings.filter(f => f.severity === 'low' && !f.protected && f.applies !== 'info' && f.applies !== 'answer' && !S.review.decisions[f.id]).map(f => f.id);
      if (ids.length && confirm(`Approve ${ids.length} low-severity item(s) without listening to each?`)) { for (const id of ids) await decide(id, 'approve', 'batch: all low'); render(); }
    }
    else if (b.id === 'apply') {
      const body = {dir: S.review.dir, out: $('#out') ? $('#out').value : '', key: $('#fkey') ? $('#fkey').value : '', allow_protected: $('#prot') ? $('#prot').checked : false};
      if (S.review.is_set && !confirm('Is the set closed in Live? A new set will be written next to the original.')) return;
      await post('/api/fix', body); S.logLines = []; S.logAt = 0; S.lastStatus = 'running'; await refresh(); go('job');
    }
    else if (ds.reveal) await post('/api/reveal', {path: ds.reveal});
    else if (b.id === 'probestart') { await post('/api/probe/start', {label: ''}); await pollProbe(); render(); }
    else if (b.id === 'probestop') { const r = await post('/api/probe/stop', {song: ''}); const j = await post('/api/probe/report', {capture: r.capture});
      S.logLines = []; S.logAt = 0; S.lastStatus = 'running'; await refresh(); go('job'); }
    else if (b.id === 'abbuild') { await post('/api/ab/build', {dir: S.review.dir, key: S.form.key}); S.logLines = []; S.logAt = 0; S.lastStatus = 'running'; await refresh(); go('job'); }
    else if (b.id === 'stop') await post('/api/stop');
    else if (b.id === 'saveprefs') {
      const body = {}; document.querySelectorAll('[data-pref]').forEach(el => { if (el.value !== '' || el.tagName === 'INPUT') body[el.dataset.pref] = el.value; });
      await post('/api/prefs', body); $('#saved').textContent = 'Saved.'; refresh();
    }
    else if (ds.tool) { S.tool = ds.tool; S.toolArgs = ''; S.toolHelp = ''; render(); const h = await get('/api/help?cmd=' + encodeURIComponent(ds.tool)); S.toolHelp = h.help; if (S.view === 'tools') render(); }
    else if (b.id === 'backtools') { S.tool = null; render(); }
    else if (ds.toolpick) { const r = await post('/api/pick', {kind: ds.toolpick}); if (r.path) { S.toolArgs = (($('#args').value || '') + ' "' + r.path + '"').trim(); render(); } }
    else if (b.id === 'runtool') { S.toolArgs = $('#args').value; await post('/api/tool', {cmd: S.tool, args: S.toolArgs}); S.logLines = []; S.logAt = 0; S.lastStatus = 'running'; await refresh(); go('job'); }
  } catch (err) { alert(err.message); }
});
async function reloadReview() { const y = window.scrollY; S.review = await get('/api/review?dir=' + encodeURIComponent(S.review.dir)); $('#main').innerHTML = reviewView(); window.scrollTo(0, y); }
ovBind({
  amount: async (id, v) => { const d = (S.review.decisions[id] || {}).decision || 'approve';
    await post('/api/decide', {dir: S.review.dir, id, decision: d, amount: v, note: (S.review.decisions[id] || {}).note || ''}); reloadReview(); },
  decideLike: async (id, d) => { const r = await post('/api/decide-like', {dir: S.review.dir, id, decision: d}); reloadReview(); },
  batch: async (ids, d, note) => { for (const id of ids) await post('/api/decide', {dir: S.review.dir, id, decision: d, note}); reloadReview(); },
  note: async (id, text, at) => { await post('/api/note', {dir: S.review.dir, id, text, at}); reloadReview(); },
});
document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('tr.cmd')) e.target.click(); });
document.addEventListener('change', e => {
  const i = e.target.closest('input[data-note]');
  if (i && S.review && S.review.decisions[i.dataset.note]) decide(i.dataset.note, S.review.decisions[i.dataset.note].decision, i.value);
});
document.addEventListener('play', e => { document.querySelectorAll('audio').forEach(a => { if (a !== e.target) a.pause(); }); }, true);
render();
setInterval(() => { refresh(); pollJob(); pollProbe(); }, 1000);
</script><script src="/chat.js"></script><script src="/wiki.js"></script><script src="/teacher.js"></script><script src="/setup.js"></script><script src="/update.js"></script><script src="/diskcare.js"></script></body></html>
"""

from hypnomix.workflow.review import OVERSIGHT_CSS as _OC, OVERSIGHT_JS as _OJ   # noqa: E402
PAGE = PAGE.replace("__OVCSS__", _OC).replace("__OVJS__", _OJ)
