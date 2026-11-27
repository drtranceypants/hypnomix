// Reporting a problem (hypnomix/app/reporting.py): the "Report a problem" button in the header, the dialog with a live preview of
// the exact report, the quiet crash banner, and the page's own script-error reporting.
// hypnomix sends nothing: the buttons copy the text, save it as a file, or open the project's issue page for the person to paste into.
// Uses the page's own helpers: $, esc, get, post, S (the page's state).
(() => {
const css = `
#rpbtn{background:none;border:0;color:var(--mute);font:inherit;font-size:.8rem;cursor:pointer;padding:4px 8px}#rpbtn:hover{color:var(--accent)}
#crashban{display:none;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--med);border-radius:10px;margin:10px auto 0;max-width:900px;padding:8px 14px}
#crashban.on{display:block}#crashban .top{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}#crashban .top span{flex:1;min-width:220px}
#crashban button{font:inherit;font-size:.88rem;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;padding:3px 10px;cursor:pointer}
#crashban pre{max-height:240px;margin:8px 0 0}
#rp{position:fixed;inset:0;z-index:60;background:rgba(20,18,16,.55);display:flex;align-items:flex-start;justify-content:center;overflow:auto;padding:4vh 12px}
#rp .box{background:var(--card);color:var(--ink);width:min(860px,100%);border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,.35);padding:24px 26px 20px}
#rp h2{margin:0 0 4px;font-size:1.4rem}#rp h3{font-size:.95rem;margin:16px 0 4px}#rp .sub{color:var(--mute);margin:0 0 14px}
#rp label.f{display:block;font-size:.85rem;color:var(--mute);margin:10px 0 3px}
#rp textarea{width:100%;min-width:0;display:block;padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit;resize:vertical}
#rp fieldset{border:1px solid var(--line);border-radius:10px;margin:14px 0 0;padding:6px 14px 10px}#rp legend{font-size:.85rem;color:var(--mute);padding:0 6px}
#rp .chk{display:flex;gap:8px;align-items:flex-start;margin:6px 0;font-size:.93rem}#rp .chk small{display:block;color:var(--mute)}
#rp pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px 12px;font-size:.8rem;max-height:34vh;margin:4px 0 0}
#rp .small{font-size:.85rem;color:var(--mute);margin:10px 0}#rp .msg{margin:10px 0;padding:9px 12px;border-radius:8px;font-size:.92rem;display:none}
#rp .msg.on{display:block}#rp .msg.ok{background:rgba(47,111,79,.12);color:var(--ok)}#rp .msg.bad{background:rgba(179,38,30,.1);color:var(--hi)}
#rp .msg button{margin-left:8px}
#rp .nav{display:flex;gap:10px;flex-wrap:wrap;justify-content:space-between;margin-top:16px;border-top:1px solid var(--line);padding-top:14px;position:sticky;bottom:0;background:var(--card);padding-bottom:6px}
#rp .nav div{display:flex;gap:8px;flex-wrap:wrap}
@media (max-width:600px){#rp .nav{position:static}#rp{padding:2vh 8px}#rp .box{padding:18px 16px}}`;
const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

// ---------------------------------------------------------------- the entry that is always there
const btn = document.createElement('button');
btn.id = 'rpbtn'; btn.type = 'button'; btn.textContent = 'Report a problem';
btn.title = 'Write a report of a problem on this computer, look at exactly what it says, and send it yourself if you want to';
const anchor = document.getElementById('dc') || document.getElementById('live');
if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(btn, anchor); else document.querySelector('header').appendChild(btn);

// ---------------------------------------------------------------- the dialog
const R = {what: '', expected: '', names: false, log: true, crash: true, scan: true, kind: 'bug', crash_id: '', text: '', digest: '', parts: {}, seq: 0, timer: null};
let opener = null, inerted = [];

const reviewDir = () => (typeof S !== 'undefined' && S && S.review && typeof S.review.dir === 'string') ? S.review.dir : '';
function params(withDir) {
  const p = new URLSearchParams({what: R.what, expected: R.expected, names: R.names ? '1' : '0', log: R.log ? '1' : '0', crash: R.crash ? '1' : '0',
    scan: R.scan ? '1' : '0', kind: R.kind});
  if (R.crash_id) p.set('crash_id', R.crash_id);
  if (withDir && reviewDir()) p.set('dir', reviewDir());
  return p;
}
function choices(withDir) {
  const c = {what: R.what, expected: R.expected, names: R.names, log: R.log, crash: R.crash, scan: R.scan, kind: R.kind, digest: R.digest};
  if (R.crash_id) c.crash_id = R.crash_id;
  if (withDir && reviewDir()) c.dir = reviewDir();
  return c;
}
const say = (text, ok, extra) => {
  const n = document.getElementById('rp-note'); if (!n) return;
  n.className = 'msg on ' + (ok ? 'ok' : 'bad'); n.textContent = text;
  if (extra) n.appendChild(extra);
};
const rawPost = async (u, body) => {
  const r = await fetch(u, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Hypnomix': TOKEN}, body: JSON.stringify(body)});
  return {status: r.status, json: await r.json().catch(() => ({}))};
};

async function refresh() {
  const mine = ++R.seq;
  let r = null;
  for (const withDir of [true, false]) {
    try {
      const res = await fetch('/api/report/preview', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Hypnomix': TOKEN}, body: JSON.stringify(choices(withDir))});
      const j = await res.json().catch(() => ({}));
      if (res.ok) { r = j; R.withDir = withDir; break; }
      if (!withDir) { if (mine === R.seq) say(j.error || 'The report could not be made.', false); return; }
    } catch (e) { if (!withDir && mine === R.seq) say('The app did not answer, so the report could not be shown.', false); }
  }
  if (!r || mine !== R.seq) return;
  R.text = r.text; R.digest = r.digest; R.parts = r.parts || {};
  const pre = document.getElementById('rp-pre'); if (pre) pre.textContent = r.text;
  for (const k of ['log', 'crash', 'scan']) {
    const c = document.getElementById('rp-' + k), has = !!R.parts[k];
    if (c) { c.disabled = !has; const s = document.getElementById('rp-' + k + '-n'); if (s) s.textContent = has ? '' : ' (nothing of this kind on this computer)'; }
  }
}
const later = () => { clearTimeout(R.timer); R.timer = setTimeout(refresh, 250); };

function draw() {
  const d = document.getElementById('rp'); if (!d) return;
  d.innerHTML = `<div class="box" role="dialog" aria-modal="true" aria-labelledby="rp-h">
    <h2 id="rp-h" tabindex="-1">Report a problem</h2>
    <p class="sub">HypnoMix writes the report here, on this computer. You read it below, change it, and decide whether it goes anywhere: HypnoMix never sends it itself.</p>
    <label class="f" for="rp-what">What happened?</label>
    <textarea id="rp-what" rows="4" maxlength="4000" placeholder="What you did, and what you saw instead"></textarea>
    <label class="f" for="rp-exp">What did you expect?</label>
    <textarea id="rp-exp" rows="2" maxlength="4000"></textarea>
    <fieldset><legend>What else goes in the report</legend>
      <label class="chk"><input type="checkbox" id="rp-log"><span>The end of the last job's log<span id="rp-log-n"></span></span></label>
      <label class="chk"><input type="checkbox" id="rp-crash"><span>The last crash record<span id="rp-crash-n"></span></span></label>
      <label class="chk"><input type="checkbox" id="rp-scan"><span>How many findings each tool made in the open scan<span id="rp-scan-n"></span></span></label>
      <label class="chk"><input type="checkbox" id="rp-names"><span>Keep names<small>Off: song, track, clip and file names, and folders, become placeholders such as &lt;track 3&gt; and &lt;file 1&gt;.wav. Your home folder, passwords and keys are hidden as far as HypnoMix can tell: read the report before you share it.</small></span></label>
    </fieldset>
    <h3 id="rp-ph">The report, exactly as it will be copied or saved</h3>
    <pre id="rp-pre" tabindex="0" aria-labelledby="rp-ph"></pre>
    <p class="small">Reports go to the project's public issue tracker (${esc('github.com/drtranceypants/hypnomix/issues')}). Anything posted there is public, so do not include anything private. HypnoMix never sends anything itself: the first two buttons only copy or save the text, and the last one opens the issue page in your browser for you to paste it into.</p>
    <div id="rp-note" class="msg" role="status" aria-live="polite"></div>
    <div class="nav"><div><button type="button" id="rp-copy">Copy the report</button><button type="button" id="rp-save">Save as a file</button>
      <button type="button" class="primary" id="rp-open">Copy it and open the issue page</button></div><button type="button" id="rp-close">Close</button></div></div>`;
  document.getElementById('rp-what').value = R.what;
  document.getElementById('rp-exp').value = R.expected;
  for (const k of ['log', 'crash', 'scan', 'names']) document.getElementById('rp-' + k).checked = !!R[k];
  const h = document.getElementById('rp-h'); h.focus({preventScroll: true});
}

function openDialog(o) {
  o = o || {};
  if (document.getElementById('rp')) return;
  Object.assign(R, {what: o.what || '', expected: '', names: false, log: true, crash: true, scan: true, kind: o.kind === 'crash' ? 'crash' : 'bug',
    crash_id: o.crash_id || '', text: '', digest: '', parts: {}});
  opener = document.activeElement && document.activeElement !== document.body ? document.activeElement : null;
  const d = document.createElement('div'); d.id = 'rp'; document.body.appendChild(d);
  inerted = [...document.body.children].filter(x => x !== d && !['SCRIPT', 'STYLE'].includes(x.tagName) && !x.inert);
  inerted.forEach(x => { x.inert = true; });                 // the page behind the dialog takes no focus and no clicks while it is open
  draw(); refresh();
}
function closeDialog() {
  const d = document.getElementById('rp'); if (d) d.remove();
  clearTimeout(R.timer); R.seq++;
  inerted.forEach(x => { x.inert = false; }); inerted = [];
  const back = opener && document.contains(opener) ? opener : document.getElementById('main'); opener = null;
  if (back && back.focus) back.focus({preventScroll: true});
}
window.openReport = openDialog;
if (location.hash === '#report') { try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* the address stays */ } setTimeout(() => openDialog({}), 0); }   // the DAW view's link

async function copyText(t) {
  try { if (navigator.clipboard && navigator.clipboard.writeText) { await navigator.clipboard.writeText(t); return true; } } catch (e) { /* blocked: the next way */ }
  try {
    const host = document.querySelector('#rp .box') || document.body;
    const ta = document.createElement('textarea'); ta.value = t; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
    host.appendChild(ta); ta.select(); const ok = document.execCommand('copy'); ta.remove(); return ok;
  } catch (e) { return false; }
}
const changed = r => { R.text = r.json.text; R.digest = r.json.digest; R.parts = r.json.parts || R.parts;
  const pre = document.getElementById('rp-pre'); if (pre) pre.textContent = R.text;
  say('The report changed while you were looking at it (a job moved on), so nothing was done. It is shown again above: read it, then click once more.', false); };

async function doCopy() {
  if (await copyText(R.text)) say('Copied. Paste it wherever you want to send it.', true);
  else say('Your browser would not let HypnoMix copy. Click in the report above, select all, and copy it yourself.', false);
}
async function doSave() {
  const r = await rawPost('/api/report/save', choices(R.withDir !== false));
  if (r.status === 409) return changed(r);
  if (r.status !== 200) return say(r.json.error || 'The report could not be saved.', false);
  const b = document.createElement('button'); b.type = 'button'; b.textContent = 'Show in folder';
  b.addEventListener('click', () => { post('/api/reveal', {path: r.json.path}).then(x => { if (!x.shown) say(x.message || 'Could not open the folder.', false); }).catch(e => say(e.message, false)); });
  say(`Saved as ${r.json.name} in the app's work folder (reports). Nothing was sent.`, true, b);
}
async function doOpen() {
  const r = await rawPost('/api/report/open', choices(R.withDir !== false));
  if (r.status === 409) return changed(r);
  if (r.status !== 200) return say(r.json.error || 'The issue page could not be opened.', false);
  let copied = !!r.json.copied;
  if (!copied) copied = await copyText(R.text);
  const how = copied ? 'The report is copied. ' : 'The report could NOT be copied here: click in it above, select all, and copy it yourself. ';
  if (r.json.opened) say(how + "The project's issue page is open in your browser: paste it there.", copied);
  else {
    const a = document.createElement('a'); a.href = r.json.url; a.target = '_blank'; a.rel = 'noopener'; a.textContent = 'the issue page';
    say(how + 'A browser could not be opened from here: open ', copied); document.getElementById('rp-note').append(a, ' yourself and paste it there.');
  }
}

document.addEventListener('input', e => {
  if (!e.target.closest('#rp')) return;
  if (e.target.id === 'rp-what') R.what = e.target.value; else if (e.target.id === 'rp-exp') R.expected = e.target.value; else return;
  later();
});
document.addEventListener('change', e => {
  const t = e.target; if (!t.closest || !t.closest('#rp') || t.type !== 'checkbox') return;
  R[t.id.replace('rp-', '')] = t.checked; refresh();
});
document.addEventListener('click', e => {
  const t = e.target.closest('button'); const inDlg = e.target.closest('#rp');
  if (inDlg) {
    if (!t) return;
    if (t.id === 'rp-close') closeDialog();
    else if (t.id === 'rp-copy') doCopy();
    else if (t.id === 'rp-save') doSave().catch(err => say(err.message, false));
    else if (t.id === 'rp-open') doOpen().catch(err => say(err.message, false));
    return;
  }
  if (e.target.closest('#rpbtn')) return openDialog({});
  const from = e.target.closest('[data-report]');
  if (from) {
    const box = from.closest('.banner, .msg, .res, #crashban');
    let what = from.dataset.what || '';
    if (!what && box) { const c = box.cloneNode(true); c.querySelectorAll('button,pre').forEach(x => x.remove()); what = c.textContent.replace(/\s+/g, ' ').trim().slice(0, 600); }
    const crash = from.dataset.crash || '';
    openDialog({what: what ? 'The page said: "' + what + '"\n\nWhat I did: ' : '', kind: crash ? 'crash' : 'bug', crash_id: crash});
  }
});
document.addEventListener('keydown', e => {
  if (!document.getElementById('rp')) return;
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeDialog(); return; }
  if (e.key !== 'Tab') return;
  const box = document.querySelector('#rp .box'); if (!box) return;
  const f = [...box.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),pre[tabindex],[tabindex]:not([tabindex="-1"])')].filter(x => x.offsetParent !== null);
  if (!f.length) return;
  const i = f.indexOf(document.activeElement);
  if (!box.contains(document.activeElement)) { e.preventDefault(); f[0].focus(); }
  else if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
  else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
}, true);

// ---------------------------------------------------------------- the quiet banner: a crash record was saved on this computer
const ban = document.createElement('div'); ban.id = 'crashban'; ban.setAttribute('role', 'status');
document.querySelector('header').after(ban);
const shown = {};                                           // id -> the record, for this page's life; a reload does not show them again
let open_ = '';
function drawBan() {
  const ids = Object.keys(shown).filter(k => !shown[k].gone).sort();
  ban.classList.toggle('on', ids.length > 0);
  if (!ids.length) { ban.innerHTML = ''; return; }
  const rec = shown[ids[ids.length - 1]];
  ban.innerHTML = `<div class="top"><b>HypnoMix hit a bug${rec.earlier ? ' earlier' : ''}.</b><span>A report was saved on this computer; nothing was sent.${ids.length > 1 ? ` (${ids.length} are saved.)` : ''}</span>
    <button type="button" data-cb="see">See it</button><button type="button" data-cb="report">Report it</button><button type="button" data-cb="dismiss">Dismiss</button></div><div id="cbtext"></div>`;
  if (open_ === rec.id) fillText(rec.id);
}
async function fillText(id) {
  try {
    const r = await get('/api/crashes?id=' + encodeURIComponent(id));
    const box = document.getElementById('cbtext'); if (!box || !r.text) return;
    const pre = document.createElement('pre'); pre.textContent = r.text; box.replaceChildren(pre);
  } catch (e) { /* the record went away */ }
}
ban.addEventListener('click', e => {
  const b = e.target.closest('[data-cb]'); if (!b) return;
  const ids = Object.keys(shown).filter(k => !shown[k].gone).sort(); const id = ids[ids.length - 1]; if (!id) return;
  if (b.dataset.cb === 'see') { open_ = open_ === id ? '' : id; drawBan(); }
  else if (b.dataset.cb === 'report') openDialog({kind: 'crash', crash_id: id});
  else if (b.dataset.cb === 'dismiss') {
    ids.forEach(i => { shown[i].gone = true; post('/api/crashes/dismiss', {id: i}).catch(() => {}); });
    open_ = ''; drawBan();
    const m = document.getElementById('main'); if (m && m.focus) m.focus({preventScroll: true});
  }
});
async function pollCrashes() {
  if (document.hidden) return;
  try {
    const r = await get('/api/crashes');
    const fresh = (r.records || []).filter(x => x.state === 'new' && !shown[x.id]);
    for (const x of fresh) { shown[x.id] = x; post('/api/crashes/dismiss', {id: x.id, offered: true}).catch(() => {}); }   // shown once: a reload does not offer it again
    if (fresh.length) drawBan();
  } catch (e) { /* the app is not answering: nothing to say about that here */ }
}
pollCrashes(); setInterval(pollCrashes, 6000);
document.addEventListener('visibilitychange', pollCrashes);

// ---------------------------------------------------------------- script errors in the page itself (never more than a few a minute)
const stamps = []; let lastKey = '';
function pageError(message, source, line, stack) {
  try {
    const now = Date.now(); while (stamps.length && now - stamps[0] > 60000) stamps.shift();
    const key = String(message) + '|' + source + '|' + line;
    if (stamps.length >= 3 || key === lastKey) return;
    lastKey = key; stamps.push(now);                         // at most 3 a minute, and never the same one twice in a row: no loop
    post('/api/crashes/page', {message: String(message).slice(0, 500), source: String(source || '').slice(0, 200), line: Number(line) || 0,
      stack: String(stack || '').slice(0, 2000), page: (typeof S !== 'undefined' && S && S.view) ? String(S.view).slice(0, 40) : ''})
      .then(() => setTimeout(pollCrashes, 400)).catch(() => {});      // an error while reporting an error is only dropped
  } catch (e) { /* nothing more to do */ }
}
window.addEventListener('error', e => {
  if (e.target && e.target !== window) return;               // a picture or a script that did not load, not an error in the page's own code
  pageError(e.message || 'script error', e.filename, e.lineno, e.error && e.error.stack);
});
window.addEventListener('unhandledrejection', e => {
  const r = e.reason;
  if (r && (r.fromServer || r.name === 'AbortError')) return;      // the app answered with a plain sentence: shown to the person, not a bug in the page
  if (r instanceof TypeError && /fetch|network|load failed/i.test(String(r.message))) return;   // the app is restarting
  pageError((r && r.message) || String(r), '', 0, r && r.stack);
});
})();
