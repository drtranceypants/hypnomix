"""The hypnomix app's page: one file, no network access beyond this computer."""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>hypnomix</title>
<style>
:root{--bg:#f6f4ef;--card:#fff;--ink:#1d1b18;--mute:#6b665e;--line:#e2ddd2;--hi:#b3261e;--med:#955808;--low:#3d6b4f;
--info:#5a6472;--ok:#2f6f4f;--skip:#6e695f;--chg:#8a5a00;--accent:#8e3f3f;--accent-ink:#fff;--focus:#1a56c4}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--card:#201f1c;--ink:#ece8df;--mute:#a09a8e;--line:#34322d;
--hi:#ff8a80;--med:#f0b455;--low:#8fc7a4;--info:#9aa6b6;--ok:#7fd0a4;--skip:#a09a8e;--chg:#f0b455;--accent:#e9b4b0;--accent-ink:#1d1b18;--focus:#8ab4ff}}
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
button.on.approve{background:var(--ok);color:var(--accent-ink);border-color:var(--ok)}
button.on.skip{background:var(--skip);color:var(--accent-ink);border-color:var(--skip)}
button.on.change{background:var(--chg);color:var(--accent-ink);border-color:var(--chg)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:12px 0}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0}.row label{min-width:150px;color:var(--mute)}
input[type=text],input[type=search],select,textarea{font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:8px;
background:var(--bg);color:var(--ink);flex:1;min-width:200px}
.path{flex:1;min-width:200px;color:var(--mute);overflow-wrap:anywhere;font-size:.92rem}
.note{font-size:.88rem;color:var(--mute);margin:6px 0 0;overflow-wrap:anywhere}.warn{border-left:3px solid var(--hi);padding:4px 12px;margin:0 0 14px}
.prefs{border-left:3px solid var(--accent);padding:4px 12px;margin:0 0 14px;color:var(--mute)}
.bar{position:sticky;top:var(--hh,49px);background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);display:flex;gap:8px;
flex-wrap:wrap;align-items:center;z-index:2}.bar .count{margin-right:auto;font-variant-numeric:tabular-nums}
.item{scroll-margin-top:calc(var(--hh,49px) + 110px);scroll-margin-bottom:24px}.item.st-approve,.item.st-dflt{border-left:5px solid var(--ok)}.item.st-skip{border-left:5px solid var(--skip)}.item.st-change{border-left:5px solid var(--chg)}
.item.cur{box-shadow:0 0 0 2px var(--accent)}.head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}h4.title{margin:0;font-size:1rem}
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
.song{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.song .name{font-weight:600;margin-right:auto;min-width:0;overflow-wrap:anywhere}.song .btns{white-space:nowrap}
.meter{display:inline-block;height:8px;background:var(--line);width:120px;border-radius:4px;overflow:hidden;vertical-align:middle}
.meter i{display:block;height:100%;background:var(--ok,#5a9)}.bands{display:inline-flex;gap:2px;align-items:flex-end;height:22px;vertical-align:middle}
.bands i{display:block;width:7px;background:var(--mute)}.num{font-variant-numeric:tabular-nums;white-space:nowrap}
table{border-collapse:collapse;width:100%}
__OVCSS__td{padding:6px 8px;border-top:1px solid var(--line);vertical-align:top}
td code{font:13px ui-monospace,monospace}tr.cmd{cursor:pointer}tr.cmd:hover td{background:var(--bg)}
.grp td{font-weight:700;border-top:2px solid var(--line);padding-top:14px}
.spin{display:inline-block;width:12px;height:12px;border:2px solid var(--line);border-top-color:var(--accent);border-radius:50%;
animation:sp 1s linear infinite;vertical-align:-1px;margin-right:6px}@keyframes sp{to{transform:rotate(360deg)}}
.tag.dflt{border-color:var(--ok);color:var(--ok)}.tag.off{border-style:dashed}
button.on.dflt{background:var(--ok);color:var(--accent-ink);border-color:var(--ok)}
.banner{border-left:4px solid var(--med);background:var(--card);border-radius:6px;padding:8px 14px;margin:12px 0}
.banner.bad{border-left-color:var(--hi)}.banner h2{margin:4px 0 6px}.banner p{margin:6px 0}
.bad{color:var(--hi)}.ok{color:var(--ok)}.res h2{margin:22px 0 6px}.res .card b{display:block;margin-bottom:4px}
ul.plain{margin:6px 0;padding-left:20px}ul.plain li{margin:3px 0}.fileline{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin:6px 0}
.fileline .nm{font-weight:600;overflow-wrap:anywhere}.fileline .note{margin:0}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px;border-radius:4px}
main:focus,main:focus-visible,h1:focus,h2:focus,.lesson h1:focus,.wa h1:focus{outline:none}.item:focus{outline:none}.item:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
::placeholder{color:var(--mute);opacity:1}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.skiplink{position:absolute;left:8px;top:-60px;background:var(--card);border:2px solid var(--focus);padding:6px 12px;border-radius:8px;z-index:20;color:var(--ink)}.skiplink:focus{top:8px}
#msg{position:sticky;top:var(--hh,49px);z-index:6;margin:0 auto;max-width:900px;padding:0 16px}#msg .banner{display:flex;gap:12px;align-items:baseline;margin:8px 0;background:var(--card);box-shadow:0 2px 8px rgba(0,0,0,.15)}#msg .banner span{flex:1;overflow-wrap:anywhere}
kbd{font:12px ui-monospace,monospace;border:1px solid var(--line);border-bottom-width:2px;border-radius:5px;padding:0 5px;background:var(--card)}
table.keys td{border-top:0;padding:2px 10px 2px 0}.helpbox{margin:8px 0}
#rvhelp:not([hidden]){position:fixed;top:calc(var(--hh,49px) + 12px);right:12px;width:min(440px,calc(100vw - 24px));max-height:calc(100vh - var(--hh,49px) - 36px);overflow:auto;z-index:25;margin:0;box-shadow:0 10px 30px rgba(0,0,0,.3)}
.filters{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:10px 0}.chip{border-radius:99px;padding:3px 12px}.chip.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.filters select{flex:0 0 auto;min-width:0;padding:3px 8px}
h2 .cnt,h3 .cnt{font-size:.8rem;font-weight:400}h3.sevhead{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;margin:18px 0 4px}
h3.sevhead.high{color:var(--hi)}h3.sevhead.medium{color:var(--med)}h3.sevhead.low{color:var(--low)}h3.sevhead.info{color:var(--info)}
details.byhand{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 16px;margin:22px 0}details.byhand summary{cursor:pointer;font-weight:600}
.tag.warnp{border-color:var(--med);color:var(--med)}.tag.heard{border-color:var(--ok);color:var(--ok)}
.ab1{margin:12px 0 0}.abtop{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 6px}.ab1 audio{width:100%}
.abbtn.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent);font-weight:600}
.rvmodal{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:30;display:flex;align-items:center;justify-content:center;padding:16px}
.rvbox{max-width:760px;width:100%;max-height:85vh;display:flex;flex-direction:column;margin:0}.rvbox h2{margin:0 0 8px}.rvbody{overflow:auto;flex:1;min-height:0}
.tbl{overflow:auto;max-height:42vh;border:1px solid var(--line);border-radius:8px;margin:8px 0}.tbl th{text-align:left;font-size:.8rem;padding:4px 8px;position:sticky;top:0;background:var(--card)}.tbl td{font-size:.88rem}
.jprog{margin:6px 0 14px}.jprog .big{font-weight:600}
.more{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0 18px}.more .note{margin:0}
@media (prefers-reduced-motion:reduce){.spin{animation:none}*{scroll-behavior:auto!important;transition:none!important}}
@media (max-width:560px){.ab{grid-template-columns:1fr}.row label{min-width:100%}}
</style></head><body>
<a class="skiplink" href="#main">Skip to the page</a>
<header><span class="brand">hypnomix</span>
<nav aria-label="Main"><button class="tab" data-daw hidden title="DAW: the Hypnomix DAW (Arrangement, Session, Mixer, Review) on the Hypnomix engine">DAW</button><button class="tab" data-view="home">Songs</button><button class="tab" data-view="prefs">Preferences</button>
<button class="tab" data-view="chat">Assistant</button><button class="tab" data-view="wiki">Wiki</button><button class="tab" data-view="teach" title="Teacher: make a song from scratch, step by step, in your DAW">Teacher</button><button class="tab" data-view="live">Live</button><button class="tab" data-view="tools">Tools</button><button class="tab" data-view="job" id="jobtab" hidden>Activity</button><button class="tab" data-setup title="How you work with hypnomix: AI provider, keys, your DAW, teacher mode">Setup</button></nav>
<span class="live" id="live" role="status"></span></header>
<div id="msg" role="alert"></div><div id="sr" class="sr" role="status" aria-live="polite"></div>
<main id="main" tabindex="-1"></main>
<script>
const TOKEN = "__TOKEN__";
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const get = (u) => fetch(u).then(r => r.json());
const post = (u, body) => fetch(u, {method:'POST', headers:{'Content-Type':'application/json','X-Hypnomix':TOKEN},
  body: JSON.stringify(body || {})}).then(async r => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || r.statusText); return j; });
// What the browser remembers for this person (it can come back empty, or refuse: nothing depends on it).
const LS = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private window or blocked storage */ } },
};
const DAW_MODE = __DAWMODE__;     // `hypnomix app --daw`: the DAW view is the first page
if (DAW_MODE && !location.hash) location.replace('/daw/');
const FORM0 = {source:'', mix:'', key:'', like:'', deep:false, devices:true};
const saved = LS.get('hx.form', {});
let S = {view:'home', state:null, form:Object.assign({}, FORM0, ['source', 'mix', 'key', 'like'].reduce((o, k) => (typeof saved[k] === 'string' ? Object.assign(o, {[k]: saved[k]}) : o), {}),
    {deep: !!saved.deep, devices: saved.devices !== false}), review:null, logAt:0, logLines:[], tool:null,
  outName:{}, histOpen:false, hist:null, result:null, jobInfo:null, commands:[], cmdRev:''};
const saveForm = () => LS.set('hx.form', S.form);
// A pasted path loses the quotes a file manager's "copy as path" puts round it (and a file:// start): the server does the same, so either alone is enough.
const barePath = v => {
  let s = String(v == null ? '' : v).trim();
  const pairs = {'"': '"', "'": "'", '“': '”', '‘': '’'};
  if (s.length >= 2 && pairs[s[0]] === s[s.length - 1]) s = s.slice(1, -1).trim();
  return s;
};
// An error or a notice is shown in the page, where a screen reader reads it too: never in a pop-up that takes the page away.
function showMsg(text, kind) {
  const m = document.getElementById('msg'); if (!m) return;
  m.innerHTML = text ? `<div class="banner${kind === 'ok' ? '' : ' bad'}"><span>${esc(text)}</span><button type="button" id="msgx" aria-label="Dismiss this message">Dismiss</button></div>` : '';
  if (text && kind === 'ok') setTimeout(() => { if (m.textContent.includes(text)) m.innerHTML = ''; }, 6000);
}
window.alert = t => showMsg(t);
document.addEventListener('click', e => { if (e.target.closest('#msgx')) showMsg(''); });

__OVJS__
function go(view, extra) { Object.assign(S, extra || {}); S.view = view; saveNav(); showMsg(''); render(); window.scrollTo(0, 0); }      // a notice belongs to the screen that raised it
// Keep the keyboard where it was when a screen is drawn again: the control that had focus gets it back (same id, else same data- attribute).
function focusKey(root) {
  const a = document.activeElement;
  if (!a || a === document.body || !root || !root.contains(a)) return null;
  if (a.id) return '#' + CSS.escape(a.id);
  const at = [...a.attributes].find(x => x.name.startsWith('data-') && x.value !== '');
  return at ? '[' + at.name + '="' + CSS.escape(at.value) + '"]' : null;
}
function restoreFocus(root, key) {
  if (!key || !root || (document.activeElement && document.activeElement !== document.body)) return false;
  const el = root.querySelector(key);
  if (el && el.focus) { el.focus({preventScroll: true}); return true; }
  return false;
}
// Where the person was, so a refresh reopens the same tab and the same review (a job or a result is not reopened).
function saveNav() { LS.set('hx.nav', {view: ['job', 'result'].includes(S.view) ? 'home' : S.view, dir: S.view === 'review' && S.review ? S.review.dir : ''}); }
document.addEventListener('click', e => { const t = e.target.closest('button[data-view]'); if (t) go(t.dataset.view); });
document.addEventListener('click', e => { if (e.target.closest('button.tab[data-daw]')) location.href = '/daw/'; });   // the nav tab only: Setup's DAW choices are buttons with data-daw too
// The DAW tab is shown only when there is an engine to drive: `hypnomix app --daw`, an engine program found, or a window attached.
async function dawTab() {
  try { const st = await get('/api/daw/state'); const b = $('button.tab[data-daw]'); if (b) b.hidden = !(DAW_MODE || st.daw_mode || st.binary || st.mode || st.connected); } catch (e) { /* no answer: the tab stays as it was */ }
}
dawTab(); setInterval(dawTab, 15000);

// The state is asked again every second or so. It says its `rev`; asked with it, an unchanged state costs a few bytes (no song rows again), and the asking slows down while nothing happens.
let quiet = 0;                                              // asks in a row that found nothing new
async function refresh() {
  try {
    const r = await get('/api/state' + (S.state && S.stateRev ? '?rev=' + encodeURIComponent(S.stateRev) : ''));
    if (r.same && S.state) quiet++; else { S.state = r; S.stateRev = r.rev || ''; quiet = 0; }
  } catch (e) { return; }
  if (S.state.commands_rev !== S.cmdRev) {                      // the command list is sent once, and again only if it changed
    S.cmdRev = S.state.commands_rev;
    get('/api/commands').then(r => { S.commands = r.commands || []; if (S.view === 'tools') render(); }).catch(() => { S.cmdRev = ''; });
  }
  // the Live pill is for a person who uses Live: a REAPER or Ardour song on screen (or that DAW chosen in Setup) never sees "Live device not connected"
  const rk = S.view === 'review' && S.review ? S.review.kind : '', noLive = rk ? (rk === 'rpp' || rk === 'ardour') : ['reaper', 'ardour', 'other'].includes(S.state.daw);
  const lv = $('#live'), lt = S.state.live ? '<b aria-hidden="true">●</b> Live device connected' : noLive ? '' : 'Live device not connected';
  if (lv.dataset.t !== lt) { lv.dataset.t = lt; lv.innerHTML = lt; lv.hidden = !lt; }            // only when it changes: a screen reader is not told every second
  $('#jobtab').hidden = S.state.job.status === 'idle';
  document.querySelectorAll('button.tab').forEach(b => b.classList.toggle('on', b.dataset.view === S.view || (S.view === 'review' && b.dataset.view === 'home')));
}

// ---------------------------------------------------------------- home
const KIND_WORD = {als:'Live set', rpp:'REAPER project', ardour:'Ardour session', folder:'folder of recordings'};
function songCard(s) {
  const tags = [];
  if (s.damaged) tags.push(`<span class="tag prot">${s.damaged === 'decisions.json' ? "this song's decisions file is damaged" : "this scan's results file is damaged"}</span>`);
  if (s.incomplete) tags.push(`<span class="tag">${s.running ? 'scanning now…' : 'the scan did not finish'}</span>`);
  if (s.stale) tags.push('<span class="tag prot">saved after the scan</span>');
  if (s.source_missing) tags.push('<span class="tag prot">original not found</span>');
  const counts = s.incomplete ? '' : `${s.findings} to review · ${s.decided} decided · ${s.approved} approved${s.on_default ? ' · ' + s.on_default + ' on by default' : ''}${s.applied ? ' · applied' : ''} · `;
  return `<div class="card song"><div class="name">${esc(s.name)} ${tags.join(' ')}
    <div class="note">${esc(KIND_WORD[s.kind] || '')}${s.same_name && s.parent ? ' in ' + esc(s.parent) : ''}</div></div>
    <span class="note">${counts}${esc(s.when)}</span>
    <span class="btns">${s.incomplete ? '' : `<button data-open="${esc(s.dir)}">Open review</button>`}${s.can_rescan && !s.running ? ` <button data-rescan="${esc(s.dir)}" data-kind="${esc(s.kind)}" title="Run the scan again on the song as it is now">Re-scan</button>` : ''}</span></div>`;
}
function homeView() {
  const st = S.state, f = S.form, ch = st.chooser !== false;        // no file chooser in this app (an installed Windows app has none): the Path boxes do the job
  const songs =st.scans.map(songCard).join('') || `<p class="note">No songs yet.</p>${st.demo ? '<p><button data-demo="1">Try it on a demo song</button> <span class="note">makes a short song with problems planted in it, then scans it: nothing of yours is touched</span></p>' : ''}`;
  return `<h1>First pass on a song</h1>
  <p class="sub">Every check runs at once. Nothing is changed. You then hear each proposed fix and decide.</p>
  ${st.unanswered ? `<div class="prefs">${st.unanswered} preference question(s) not answered yet. <button data-view="prefs">Answer them</button> so the review starts from how you work.</div>` : ''}
  <div class="card">
    <div class="row"><label>Song</label><span class="path">${esc(f.source) || 'a Live set (.als), REAPER project (.rpp), Ardour session (.ardour), or a folder of recordings or stems from any DAW'}</span>
      ${ch ? '<button data-pick="source:song">Choose project…</button><button data-pick="source:folder">Choose folder…</button>' : ''}</div>
    <div class="row"><label for="src">Path</label><input type="text" id="src" placeholder="or paste the path here" value="${esc(f.source)}"></div>
    <div class="row"><label${ch ? '' : ' for="mixp"'}>Bounce of the mix <span class="note">(optional)</span></label>${ch ? `<span class="path">${esc(f.mix) || 'adds loudness, release checks and the key'}</span>
      <button data-pick="mix:audio">Choose…</button>` : `<input type="text" id="mixp" data-form="mix" placeholder="paste its path: adds loudness, release checks and the key" value="${esc(f.mix)}">`}${f.mix && ch ? '<button data-clear="mix">Clear</button>' : ''}</div>
    <div class="row"><label${ch ? '' : ' for="likep"'}>A song you love <span class="note">(optional)</span></label>${ch ? `<span class="path">${esc(f.like) || 'compare tone, dynamics and width with it'}</span>
      <button data-pick="like:audio">Choose…</button>` : `<input type="text" id="likep" data-form="like" placeholder="paste its path: compare tone, dynamics and width with it" value="${esc(f.like)}">`}${f.like && ch ? '<button data-clear="like">Clear</button>' : ''}</div>
    <div class="row"><label for="key">Key <span class="note">(optional)</span></label><input type="text" id="key" placeholder='e.g. F# major: needed before any vocal tuning is applied' value="${esc(f.key)}"></div>
    <div class="row"><label for="deep">Deep scan</label><input type="checkbox" id="deep" ${f.deep ? 'checked' : ''}> <span class="note">also render every track: frequency fights and mic phase (slower)</span></div>
    ${/\.als$/i.test(f.source || '') ? `<div class="row"><label for="devices">Live devices</label><input type="checkbox" id="devices" ${f.devices ? 'checked' : ''}> <span class="note">also write a copy of the set with the hypnomix devices on every track (probes, the review device, HypnomixMain on Main), next to yours</span></div>` : ''}
    <div class="row"><button class="primary" id="scan">Start the first pass</button>
      <span class="note">Read-only. Close nothing: your project is not touched${/\.als$/i.test(f.source || '') && f.devices ? ' (the devices go into a new copy)' : ''}. A song you scanned before is scanned again in its own folder.</span></div>
  </div>
  <h2>Your songs</h2>${songs}
  <p class="note">Kept in ${esc(st.home)}</p>`;
}

// ---------------------------------------------------------------- activity
function fileLines(files) {
  return (files || []).map(f => `<div class="fileline"><span class="nm">${esc(f.name)}</span><span class="note">in ${esc(f.folder)}${f.what ? ' · ' + esc(f.what) : ''}</span><button data-reveal="${esc(f.path)}">Show in folder</button></div>`).join('');
}
function secWords(n) { if (n < 1) return 'under a second'; n = Math.max(0, Math.round(n)); return n < 90 ? n + ' s' : Math.floor(n / 60) + ' min' + (n % 60 ? ' ' + (n % 60) + ' s' : ''); }
// How far a running job has got, in the command's own counts: never a percentage, and an estimate only from a past run's times.
function progressHTML(p) {
  if (!p) return '';
  const left = (p.eta != null && !p.over) ? ` · about ${secWords(p.eta)} left (last time it took ${secWords(p.last_total)})`
    : (p.eta != null && p.over) ? ` · taking longer than last time (${secWords(p.last_total)})` : '';
  if (p.kind === 'scan') {
    const names = (p.pending || []).map(g => esc(g) + (p.last && p.last[g] != null ? ` (last time ${secWords(p.last[g])})` : ''));
    const first = p.eta == null && p.total ? ' · no estimate: there is no earlier scan of this song to compare with' : '';
    return `<div class="big">${p.total != null ? `${p.done} of ${p.total} checks done` : 'Starting the checks'} · ${secWords(p.elapsed)} so far${left}${first}</div>
      ${names.length ? `<div class="note">Still running: ${names.join(', ')}</div>` : ''}`;
  }
  if (p.kind === 'ab') return `<div class="big">Building the before / after clips: ${p.done} step${p.done === 1 ? '' : 's'} so far · ${secWords(p.elapsed)} so far${left}</div>`;
  if (p.kind === 'fix') return `<div class="big">${p.total && p.done <= p.total ? `${p.done} of ${p.total} tools done` : `${p.done} step${p.done === 1 ? '' : 's'} done`} · ${secWords(p.elapsed)} so far</div>`;
  return `<div class="big">${secWords(p.since_start)} so far</div>`;
}
function jobView() {
  const j = S.state.job, info = S.jobInfo && S.jobInfo.id === j.id ? S.jobInfo : {};
  const running = j.status === 'running';
  const sub = running ? `<span class="spin" aria-hidden="true"></span>${esc(j.step)}…` : j.status === 'done' ? 'Finished.' : j.status === 'failed' ? (info.stopped ? 'Stopped: you pressed Stop.' : 'Stopped with an error.') : '';
  const why = !running && j.status === 'failed' && info.reason && !info.stopped ? `<div class="banner bad"><b>Why it stopped:</b> ${esc(info.reason)}<br><span class="note">The last lines of the log are below.</span></div>` : '';
  const files = !running && info.files && info.files.length ? `<h2>Files made</h2>${fileLines(info.files)}` : '';
  const text = !running && info.text ? `<h2>The handoff list</h2><pre>${esc(info.text)}</pre>` : '';
  const back = !running && j.dir ? `<button class="primary" data-open="${esc(j.dir)}">${['fix', 'undo', 'handoff'].includes(j.kind) ? 'Back to the review' : 'Open the review'}</button>` : '';
  return `<h1>${esc(j.title || 'Activity')}</h1>
  <p class="sub" id="jobsub" role="status" aria-live="polite">${sub}</p><div class="jprog" id="jobprog" role="status" aria-live="polite">${running ? progressHTML(S.progress) : ''}</div>${why}
  <div class="row">${running ? '<button id="stop">Stop</button>' : ''}${back}</div>${files}${text}
  <pre id="log" role="log" aria-label="What the command printed" aria-live="off" tabindex="0">${esc(S.logLines.join('\n'))}</pre>`;
}
async function pollJob() {
  if (!S.state || S.state.job.status === 'idle') return;
  const sj = S.state.job;
  if (sj.status !== 'running' && S.lastStatus !== 'running' && S.jobId === sj.id && S.jobInfo && S.jobInfo.id === sj.id) return;   // a job that ended and was already taken: nothing more to ask
  const j = await get('/api/job?since=' + S.logAt);
  if (j.id !== S.jobId) { S.jobId = j.id; S.logLines = []; S.logAt = 0; return; }
  S.progress = j.progress;
  const pe = $('#jobprog'); if (pe && j.status === 'running') { const h = progressHTML(j.progress); if (pe.dataset.h !== h) { pe.dataset.h = h; pe.innerHTML = h; } }
  if (j.skipped) S.logLines.push(`… ${j.skipped} older line${j.skipped === 1 ? '' : 's'} of the output left out: the log keeps the newest ${j.keeps || 4000} …`);   // a long job: the oldest lines go, the newest never do
  if (j.log.length) { S.logLines.push(...j.log); S.logAt = j.total; const el = $('#log'); if (el) { el.textContent = S.logLines.join('\n'); el.scrollTop = el.scrollHeight; } }
  if (j.status !== 'running' && (!S.jobInfo || S.jobInfo.id !== j.id) && S.lastStatus !== 'running') {   // a job that ended before this page looked: take its reason from the app
    S.jobInfo = j; if (S.view === 'job') render();
  }
  if (S.lastStatus === 'running' && j.status !== 'running') {
    S.jobInfo = j;
    await refresh();
    if (S.view === 'job') {
      if (j.kind === 'fix' && j.dir) await showResult(j.dir);
      else if (j.status === 'done' && j.dir && !['tool', 'handoff', 'undo'].includes(j.kind)) openReview(j.dir).catch(e => { showMsg(e.message); render(); });
      else render();
    }
  }
  S.lastStatus = j.status;
}
function startJob() { S.logLines = []; S.logAt = 0; S.lastStatus = 'running'; S.jobInfo = null; return refresh().then(() => go('job')); }

// ---------------------------------------------------------------- what an apply did
async function showResult(dir) { S.result = await get('/api/fix/result?dir=' + encodeURIComponent(dir)); go('result'); }
function logHTML(run) {
  if (!run) return '<p class="note">Nothing has been applied for this song yet.</p>';
  const by = g => run.sections.filter(x => x.group === g);
  const block = (h, secs, cls) => secs.length ? `<h2 class="${cls || ''}">${h}</h2>` + secs.map(x => `<div class="card"><b>${esc(x.title)}</b><pre class="fix">${x.lines.map(l => l.bad ? `<span class="bad">${esc(l.t)}</span>` : esc(l.t)).join('\n')}</pre></div>`).join('') : '';
  return (run.intro.length ? `<p class="note">${esc(run.intro.join(' · '))}</p>` : '') + block('What was applied', by('applied'))
    + block('Also applied because they are on by default', by('default')) + block('What was NOT applied, and why', by('not_applied'))
    + block('FAILED', by('failed'), 'bad') + (run.history ? `<p class="note">${esc(run.history)}</p>` : '');
}
function resultView() {
  const r = S.result, bad = r.status === 'failed', part = bad && !r.wrote_nothing, u = r.wrote_nothing ? null : r.undo;     // part: it stopped, but a new file was written first
  const head = part ? `<h1>Applied in part: ${esc(r.name)}</h1>` : bad ? `<h1>Apply stopped: ${esc(r.name)}</h1>` : r.wrote_nothing ? `<h1>Nothing applied: ${esc(r.name)}</h1>` : `<h1>Applied: ${esc(r.name)}</h1>`;
  const why = bad ? `<div class="banner bad"><h2>${r.stopped ? 'You stopped it' : part ? 'Some steps did not run' : 'It could not finish'}</h2>${r.reason ? `<p>${esc(r.reason)}</p>` : ''}
    ${r.tail && r.tail.length ? `<details><summary class="note">The last lines it printed</summary><pre class="fix">${esc(r.tail.join('\n'))}</pre></details>` : ''}<p class="note">${part ? 'The new file below has the steps that did run.' : 'Nothing was written.'} Your original was not changed.</p></div>` : '';
  const nothing = r.wrote_nothing && !bad ? `<div class="banner"><b>Nothing was written.</b> ${r.note ? esc(r.note) + '.' : 'None of the approved fixes could be applied.'} Your original was not changed. The log below says what happened to each item.</div>` : '';
  const files = r.wrote_nothing ? '' : r.files.length ? `<h2>${r.files.length === 1 ? 'The new file' : 'The new files'}</h2>${fileLines(r.files)}`
    : (!bad ? `<h2>New files</h2><p class="note">${r.kind === 'folder' ? 'Repaired copies are in this scan\'s "fixed" folder.' : 'No new project file was written.'}</p>${r.kind === 'folder' ? `<button data-reveal="${esc(r.dir)}/fixed">Show the fixed folder</button>` : ''}` : '');
  const listen = r.listen.length && !r.wrote_nothing ? `<h2>Listen at these spots</h2><p class="note">hypnomix re-checked what it changed; only you can hear it. Open the new project and A/B each spot against the original.</p>
    <ul class="plain">${r.listen.map(x => `<li><b>${esc(x.track)}</b>${x.where ? ' at <span class="where">' + esc(x.where) + '</span>' : ''}${x.what ? ': ' + esc(x.what) : ''}</li>`).join('')}</ul>` : '';
  const undo = u && u.can_undo ? `<button data-undo="${u.n}" data-undoname="${esc(u.undo_name)}">Undo this</button>`
    : (u ? `<p class="note">${esc(u.why_not)}</p>` : '');
  return `<div class="res">${head}${why}${nothing}${files}${r.default_ids.length ? `<p class="note">These steps were on by default in this run: ${esc(r.default_ids.join(', '))}.</p>` : ''}
  <div class="row"><button class="primary" data-open="${esc(r.dir)}">Open the review again</button>${u && u.can_undo ? undo : ''}<button data-handoff="${esc(r.dir)}">Make the handoff list</button></div>
  ${u && !u.can_undo ? undo : ''}${listen}${logHTML(r.run)}</div>`;
}

// ---------------------------------------------------------------- review (the screen itself is review.js)
async function openReview(dir) {
  const r = await get('/api/review?dir=' + encodeURIComponent(dir));
  if (!r || r.error) throw new Error((r && r.error) || 'that review could not be opened');      // a scan that is gone (the browser remembered it) is not a review
  S.review = r; S.histOpen = false; S.hist = null; S.rvScroll = true; go('review'); }

// ---------------------------------------------------------------- preferences
async function prefsView() {
  const qs = await get('/api/prefs');
  return `<h1>Preferences</h1><p class="sub">Asked once. They shape what is proposed; taste calls are still always asked.</p>
  <div class="card">${qs.map(q => {
    const v = Array.isArray(q.value) ? q.value.join(', ') : (q.value == null ? '' : q.value);
    const id = 'pf-' + q.key.replace(/[^\w-]/g, '-'), nums = !!q.options && q.options.length > 0 && q.options.every(o => typeof o === 'number');
    // A number question takes any number its help says (the usual ones are suggestions); a saved answer that is not in a list still shows as the answer.
    const own = q.options && v !== '' && !q.options.some(o => String(o) === String(v)) ? `<option selected>${esc(v)}</option>` : '';
    const field = nums ? `<input type="text" inputmode="decimal" autocomplete="off" id="${id}" data-pref="${esc(q.key)}" data-num="1" list="${id}-l" value="${esc(v)}" placeholder="not answered: ${esc(q.default)}" aria-describedby="${id}-why"><datalist id="${id}-l">${q.options.map(o => `<option value="${esc(o)}"></option>`).join('')}</datalist>`
      : q.options ? `<select id="${id}" data-pref="${esc(q.key)}" aria-describedby="${id}-why"><option value="">(not answered: ${esc(q.default)})</option>${q.options.map(o => `<option ${String(o) === String(v) ? 'selected' : ''}>${esc(o)}</option>`).join('')}${own}</select>`
      : `<input type="text" id="${id}" data-pref="${esc(q.key)}" value="${esc(v)}" placeholder="names, separated by commas" aria-describedby="${id}-why">`;
    return `<div class="row" style="align-items:flex-start"><label for="${id}" style="min-width:100%;color:var(--ink)">${esc(q.ask)}</label>${field}<p class="note" id="${id}-why" style="min-width:100%;margin:0">${esc(q.why)}</p></div>`;
  }).join('')}
  <div class="row"><button class="primary" id="saveprefs">Save</button><span class="note" id="saved" role="status"></span></div></div>`;
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
// A chosen file goes after the flag the command's own usage line names for it (`key` wants --set or --audio); a command that takes the file as an argument gets it bare.
function pickFlag(kind) {
  const m = String(S.toolHelp || '').match(/usage:[\s\S]*?(?:\n\s*\n|$)/), u = m ? m[0].replace(/\s+/g, ' ') : '';
  const flag = ({set: ['--set'], audio: ['--audio', '--mix'], folder: ['--folder', '--dir']}[kind] || []).find(f => {
    const hit = new RegExp('[\\s\\[|]' + f + '(?=[\\s\\]=,|])(?:\\s+([^\\s\\]|]+))?').exec(u);
    return hit && !(hit[1] || '').includes('=');          // a metavar like FORMAT=DIR is not a plain path: a bare path would be refused
  });
  return flag ? flag + ' ' : '';
}
function toolsView() {
  const st = S.state;
  if (S.tool) {
    const c = S.commands.find(x => x.name === S.tool) || {name: S.tool, about: ''};
    return `<p><button id="backtools">← All tools</button></p><h1>hypnomix ${esc(c.name)}</h1><p class="sub">${esc(c.about)}</p>
    <div class="card"><div class="row"><label for="args">Options</label><input type="text" id="args" placeholder='what you would type after "hypnomix ${esc(c.name)}"' value="${esc(S.toolArgs || '')}"></div>
    <div class="row">${st.chooser === false ? '' : '<button data-toolpick="set">Add a set…</button><button data-toolpick="audio">Add an audio file…</button><button data-toolpick="folder">Add a folder…</button>'}
    <button class="primary" id="runtool">Run</button></div>
    <p class="note">Tools that write a set always write a NEW one. Read the options below first.</p></div>
    <pre>${esc(S.toolHelp || 'loading…')}</pre>`;
  }
  let last = '';
  const rows = S.commands.map(c => (c.group !== last ? (last = c.group, `<tr class="grp"><td colspan="2">${esc(c.group)}</td></tr>`) : '')
    + `<tr class="cmd" data-tool="${esc(c.name)}" tabindex="0"><td><code>${esc(c.name)}</code></td><td>${esc(c.about)}</td></tr>`).join('');
  return `<h1>Tools</h1><p class="sub">Every hypnomix command. Choose one to see its options and run it.</p><table>${rows}</table>`;
}

// ---------------------------------------------------------------- render + events
async function render() {
  if (!S.state) await refresh();
  const m = $('#main'), fk = focusKey(m), v0 = S.view;
  if (S.view === 'home') m.innerHTML = homeView();
  else if (S.view === 'job') m.innerHTML = jobView();
  else if (S.view === 'review') { m.innerHTML = reviewView(); rvMounted(); }
  else if (S.view === 'result') m.innerHTML = resultView();
  else if (S.view === 'prefs') m.innerHTML = await prefsView();
  else if (S.view === 'tools') m.innerHTML = toolsView();
  else if (S.view === 'chat') { m.innerHTML = chatView(); chatPoll(true).catch(() => {}); }
  else if (S.view === 'wiki') { m.innerHTML = await wikiView(); wikiAfter(); }
  else if (S.view === 'teach') m.innerHTML = await teachView();
  else if (S.view === 'store') { m.innerHTML = await storeView(); storeAfter(); }
  else if (S.view === 'live') { await pollProbe(); m.innerHTML = liveView(); }
  if (S.view === v0) restoreFocus(m, fk);
  refresh();
}
document.addEventListener('click', async e => {
  const b = e.target.closest('button, tr.cmd'); if (!b || b.closest('.wa')) return;   // an article's own markup never drives the app's buttons
  const ds = b.dataset;
  try {
    if (ds.pick) { const [field, kind] = ds.pick.split(':'); const r = await post('/api/pick', {kind}); if (r.path) { S.form[field] = r.path; saveForm(); render(); } }
    else if (ds.rescan) {
      if (ds.kind !== 'als' && !confirm('This kind of project cannot carry your decisions into a new scan. They are kept in a file next to the scan, and you decide again. Re-scan now?')) return;
      await post('/api/rescan', {dir: ds.rescan}); await startJob();
    }
    else if (ds.handoff) { await post('/api/handoff', {dir: ds.handoff}); await startJob(); }
    else if (ds.demo) { await post('/api/demo'); await startJob(); }
    else if (ds.restore) { await post('/api/restore-decisions', {dir: ds.restore, fresh: !!ds.fresh}); await openReview(ds.restore); }
    else if (ds.hist) {
      S.histOpen = !S.histOpen; S.hist = null; rvToggleHistory();
      if (S.histOpen) { const dir = S.review.dir, h = await get('/api/history?dir=' + encodeURIComponent(dir)); S.hist = Object.assign(h, {dir}); if (S.view === 'review') rvToggleHistory(); }
    }
    else if (ds.undo) {
      const dir = S.view === 'result' ? S.result.dir : S.review.dir;
      if (!confirm(`This writes a new set named "${ds.undoname}" next to your original, equal to what version ${ds.undo} started from. Nothing is overwritten. Go on?`)) return;
      await post('/api/undo', {dir, n: +ds.undo}); await startJob();
    }
    else if (ds.clear) { S.form[ds.clear] = ''; saveForm(); render(); }
    else if (b.id === 'scan') {
      const src = $('#src'); if (src && src.value) S.form.source = barePath(src.value);
      if (!S.form.source) { showMsg('Choose a song first, or paste the path of one.'); return; }
      S.form.key = $('#key').value; S.form.deep = $('#deep').checked; if ($('#devices')) S.form.devices = $('#devices').checked; saveForm();
      await post('/api/scan', S.form); await startJob();
    }
    else if (ds.open) await openReview(ds.open);
    else if (ds.jump) { const r = await post('/api/live/jump', {dir: S.review.dir, id: ds.jump}); if (!r.device) showMsg(S.review.kind === 'rpp' ? 'Sent, but the Hypnomix panel is not open in REAPER. Open the project, then run "hypnomix reaper review".'
      : 'Sent, but the hypnomix device is not connected. Load it on any track in your Live set (run "hypnomix device" to make it).'); }
    else if (b.id === 'apply') {
      const body = {dir: S.review.dir, out: $('#out') ? $('#out').value : '', key: $('#fkey') ? $('#fkey').value : '', allow_protected: $('#prot') ? $('#prot').checked : false};
      const said = typeof rvAnswers === 'function' ? rvAnswers() : [];            // answers to the key questions: read section by section once there are some
      if (said.length) { body.answers = said; if ($('#fkey') && !body.key.trim()) body.key = 'sections'; }
      if ($('#fkey') && !body.key.trim()) { showMsg('Vocal tuning is approved, and it needs the song\'s key: type it in "Confirmed key" (for example F# major), or turn the tuning off, then apply.'); $('#fkey').focus(); return; }
      const made = [b.dataset.writes ?(withSuffix(body.out, S.review.suffix) || S.review.suggested_out) : '', b.dataset.archive].filter(x => x).join(' and ');
      if (!confirm(`Apply now? ${made ? 'This writes ' + made + ' next to your original.' : 'This writes repaired copies in this scan\'s fixed folder.'} Your original is not changed.${S.review.kind === 'als' ? ' Is the set closed in Live?' : ''}`)) return;
      await post('/api/fix', body); await startJob();
    }
    else if (ds.reveal) { const r = await post('/api/reveal', {path: ds.reveal}); if (!r.shown) showMsg(r.message || 'Could not open the folder.'); }
    else if (b.id === 'probestart') { await post('/api/probe/start', {label: ''}); await pollProbe(); render(); }
    else if (b.id === 'probestop') { const r = await post('/api/probe/stop', {song: ''}); const j = await post('/api/probe/report', {capture: r.capture});
      S.logLines = []; S.logAt = 0; S.lastStatus = 'running'; await refresh(); go('job'); }
    else if (b.id === 'abbuild') { await post('/api/ab/build', {dir: S.review.dir, key: S.form.key}); await startJob(); }
    else if (b.id === 'stop') await post('/api/stop');
    else if (b.id === 'saveprefs') {
      const body = {}; document.querySelectorAll('[data-pref]').forEach(el => { if (el.value !== '' || (el.tagName === 'INPUT' && !el.dataset.num)) body[el.dataset.pref] = el.value; });
      await post('/api/prefs', body); $('#saved').textContent = 'Saved.'; refresh();
    }
    else if (ds.tool) { S.tool = ds.tool; S.toolArgs = ''; S.toolHelp = ''; render(); const h = await get('/api/help?cmd=' + encodeURIComponent(ds.tool)); S.toolHelp = h.help; if (S.view === 'tools') render(); }
    else if (b.id === 'backtools') { S.tool = null; render(); }
    else if (ds.toolpick) { const r = await post('/api/pick', {kind: ds.toolpick}); if (r.path) { S.toolArgs = (($('#args').value || '') + ' ' + pickFlag(ds.toolpick) + '"' + r.path + '"').trim(); render(); } }
    else if (b.id === 'runtool') { S.toolArgs = $('#args').value; await post('/api/tool', {cmd: S.tool, args: S.toolArgs}); S.logLines = []; S.logAt = 0; S.lastStatus = 'running'; await refresh(); go('job'); }
  } catch (err) { showMsg(err.message); }
});
document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('tr.cmd')) e.target.click(); });
const withSuffix = (v, suf) => { v = String(v || '').trim().replace(/\.(als|rpp|ardour)$/i, ''); return v ? v + suf : ''; };
document.addEventListener('input', e => {
  const t = e.target;
  if (t.id === 'src') { S.form.source = barePath(t.value); saveForm(); }
  else if (t.id === 'key') { S.form.key = t.value; saveForm(); }
  else if (t.dataset && t.dataset.form) { S.form[t.dataset.form] = barePath(t.value); saveForm(); }
  else if (t.id === 'out' && S.review) { S.outName[S.review.dir] = t.value; const sh = $('#outshow'); if (sh) sh.textContent = t.value; }
});
document.addEventListener('change', e => {
  const t = e.target;
  if (t.id === 'src') { S.form.source = barePath(t.value); saveForm(); render(); return; }
  if (t.id === 'deep' || t.id === 'devices') { S.form[t.id] = t.checked; saveForm(); return; }
  if (t.id === 'out' && S.review) {
    const v = withSuffix(t.value, S.review.suffix) || S.review.suggested_out;
    t.value = v; S.outName[S.review.dir] = v; const sh = $('#outshow'); if (sh) sh.textContent = v;
    return;
  }
});
document.addEventListener('play', e => { document.querySelectorAll('audio').forEach(a => { if (a !== e.target) a.pause(); }); }, true);
// Start on the tab and the review the person was on (after every script on the page has loaded).
function headerHeight() { const h = document.querySelector('header'); if (h) document.documentElement.style.setProperty('--hh', h.offsetHeight + 'px'); }
window.addEventListener('resize', headerHeight);
if (window.ResizeObserver) new ResizeObserver(headerHeight).observe(document.querySelector('header'));      // the disk and update notices make it taller later
function start() {
  headerHeight();
  const nav = LS.get('hx.nav', {});
  if (nav.view === 'review' && typeof nav.dir === 'string' && nav.dir) { openReview(nav.dir).catch(() => go('home')); return; }
  if (['home', 'prefs', 'tools', 'chat', 'wiki', 'live', 'teach', 'store'].includes(nav.view)) S.view = nav.view;
  render();
}
document.addEventListener('DOMContentLoaded', start);
// Asked every second while the page is in front, and not at all in a tab nobody is looking at (one catch-up ask when it comes back).
// While a job runs (or the Activity and Live screens are open) it is every second; after ten asks that found nothing new it is every fifth second.
let beat = 0;
const tick = () => {
  const busy = !S.state || S.state.job.status === 'running' || S.view === 'job' || S.view === 'live';
  if (busy || quiet < 10 || ++beat % 5 === 0) refresh();
  pollJob().catch(() => {}); pollProbe();
};
setInterval(() => { if (!document.hidden) tick(); }, 1000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { quiet = 0; tick(); } });
</script><script src="/review.js"></script><script src="/chat.js"></script><script src="/wiki.js"></script><script src="/teacher.js"></script><script src="/setup.js"></script><script src="/update.js"></script><script src="/diskcare.js"></script><script src="/store.js"></script></body></html>
"""

from hypnomix.workflow.review import OVERSIGHT_CSS as _OC, OVERSIGHT_JS as _OJ   # noqa: E402
PAGE = PAGE.replace("__OVCSS__", _OC).replace("__OVJS__", _OJ)
