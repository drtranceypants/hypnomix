#!/usr/bin/env python3
"""The review as one page: every finding with its before / after players and approve / skip / change.

  hypnomix review SCAN_DIR                 write SCAN_DIR/REVIEW.html and print its path (open it in a browser)
  hypnomix review SCAN_DIR --serve         same page on http://127.0.0.1:8790: every click is saved straight
                                           into SCAN_DIR/decisions.json (Ctrl-C to stop)
  hypnomix review SCAN_DIR --import FILE   take in a decisions.json (or a review file) downloaded from the page
  hypnomix review SCAN_DIR --export FILE   a portable review (decisions + notes, who and when) to send to someone
  hypnomix review SCAN_DIR --merge FILE    take in a collaborator's exported review: their decisions fill in what
                                           you haven't decided; where you decided differently both are kept and
                                           listed as a conflict for you to settle (yours is never overwritten)
  hypnomix review SCAN_DIR --settle ID=mine|theirs   settle one conflict
  --as NAME                                who is reviewing (default: prefs review.name)

Run `hypnomix ab SCAN_DIR` first to get the play buttons. The page is one file with no network access: opened
directly, it keeps your choices in the browser and "Download decisions" saves them as a file to import;
with --serve they are written as you click. Either way nothing is applied until you run
`hypnomix fix SCAN_DIR --approved --out ...`.

On each finding: an amount slider (how much of the proposed move, for fixes that can scale), "apply to the N like
this" (the same decision for the undecided findings of the same kind and size), notes at a bar or a time,
"you usually" (your past reviews and finished songs), common practice, the tool's confidence, and with
`review.teach=on` (default) a few words on why the technique exists. With `review.max_questions=N` the first N
questions are shown and the rest sit in a collapsed "low priority: batch" section with suggested grouped decisions.

High-severity and protected items are marked: decide those one at a time. "Approve all low" only touches
low-severity items that are not protected.
"""
import argparse, html, json, sys
from pathlib import Path

from hypnomix.workflow import oversight as O

DECISIONS = O.DECISIONS

# ---- reusable pieces: the app can embed OVERSIGHT_CSS + OVERSIGHT_JS and call oversight_payload() for the data.
OVERSIGHT_CSS = r"""
.ov{margin:10px 0 0;font-size:.88rem;color:var(--mute)}.ov b{color:var(--ink);font-weight:600}
.ov p{margin:3px 0}.ov .why{border-left:3px solid var(--accent);padding:2px 10px;margin:8px 0}
.conf{font-size:.75rem;border-radius:99px;padding:1px 8px;border:1px solid var(--line)}
.amt{display:flex;gap:8px;align-items:center;margin:10px 0 0;font-size:.88rem;flex-wrap:wrap}
.amt input[type=range]{flex:1;max-width:260px;min-width:120px}
.amt output{font-variant-numeric:tabular-nums;min-width:3.5em}.like{font-size:.85rem}
.notes{margin:8px 0 0;font-size:.85rem}.notes ul{margin:4px 0;padding-left:18px}
.notes form{display:flex;gap:6px;flex-wrap:wrap}.notes input{font:inherit;padding:4px 8px;border:1px solid var(--line);
border-radius:8px;background:var(--bg);color:var(--ink)}.notes input.t{width:7em}.notes input.x{flex:1;min-width:160px}
.conflict{border-left:3px solid var(--hi);padding:2px 10px;margin:8px 0;font-size:.88rem}
details.batch{background:var(--card);border:1px dashed var(--line);border-radius:12px;padding:10px 16px;margin:18px 0}
details.batch summary{cursor:pointer;font-weight:600}.sugg{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0}
.who{display:flex;gap:6px;align-items:center}.who input{font:inherit;width:9em;padding:4px 8px;border:1px solid var(--line);
border-radius:8px;background:var(--bg);color:var(--ink)}
"""

OVERSIGHT_JS = r"""
// Oversight pieces, shared by the review page and the app. ctx = {ov, dec, notes, esc[, findings]}; actions go
// through `api` (see ovBind): api.amount(id, v), api.decideLike(id, decision), api.batch(ids, decision, note),
// api.note(id, text, at).
function ovLikeIds(ov, dec, id) {
  return (ov.like[id] || []).filter(x => !(dec[x] && dec[x].decision));
}
function ovItemHTML(f, ctx) {
  const ov = ctx.ov, e = ov.extras[f.id] || {}, d = ctx.dec[f.id] || {}, esc = ctx.esc;
  const out = [];
  if (e.confidence != null) out.push(`<span class="conf" title="${esc(e.confidence_from)}">confidence ${Math.round(e.confidence * 100)}%</span>`);
  const lines = [];
  if (e.usually) lines.push(`<p><b>You usually:</b> ${esc(e.usually)}</p>`);
  if (e.practice) lines.push(`<p><b>Common practice:</b> ${esc(e.practice)}</p>`);
  if (ov.teach && e.why) lines.push(`<p class="why"><b>Why this technique:</b> ${esc(e.why)}</p>`);
  let amt = '';
  const actionable = f.applies !== 'info' && f.applies !== 'answer';
  if (actionable && e.scalable) {
    const v = d.amount != null ? d.amount : 100;
    amt = `<div class="amt"><label for="amt-${esc(f.id)}">Amount</label><input type="range" min="0" max="100" step="5" id="amt-${esc(f.id)}" data-amount="${esc(f.id)}" value="${v}"><output>${v}%</output><span title="${esc(e.scale_note)}">of the proposed move</span></div>`;
  } else if (actionable && e.scale_note) {
    amt = `<p class="ov">All or nothing: ${esc(e.scale_note)}.</p>`;
  }
  const likeN = actionable ? ovLikeIds(ov, ctx.dec, f.id).length : 0;
  const like = likeN ? `<div class="act like">${['approve','skip'].map(x => `<button data-like="${esc(f.id)}" data-d="${x}">${x === 'approve' ? 'Approve' : 'Skip'} the ${likeN} like this</button>`).join('')}</div>` : '';
  const conf = (d.conflicts || []).map(c => `<div class="conflict"><b>Conflict:</b> ${esc(c.by)} chose <b>${esc(c.decision)}</b>${c.amount != null ? ' at ' + esc(c.amount) + '%' : ''}${c.note ? ' (' + esc(c.note) + ')' : ''}; yours is <b>${esc(d.decision)}</b>. Settle: <code>hypnomix review DIR --settle ${esc(f.id)}=mine</code> (or <code>=theirs</code>)</div>`).join('');
  const who = d.by ? `<p class="ov">decided by ${esc(d.by)}${d.at ? ' · ' + esc(d.at) : ''}${d.via ? ' · ' + esc(String(d.via).replace('like:', 'like ')) : ''}</p>` : '';
  const ns = (ctx.notes[f.id] || []).map(n => `<li>${n.bar ? 'bar ' + esc(n.bar) + ': ' : n.sec != null ? esc(n.sec) + ' s: ' : ''}${esc(n.text)} <span class="ov">(${esc(n.by)}, ${esc(n.at)})</span></li>`).join('');
  const notes = `<div class="notes">${ns ? '<ul>' + ns + '</ul>' : ''}<form data-noteform="${esc(f.id)}"><input class="t" name="at" placeholder="bar or 1:23" aria-label="where"><input class="x" name="text" placeholder="note at a moment (for you or a collaborator)" aria-label="note"><button type="submit">Add note</button></form></div>`;
  return `<div class="ov">${out.join(' ')}${lines.join('')}</div>${amt}${like}${conf}${who}${notes}`;
}
function ovBatchHTML(ctx, itemHTML) {
  const ov = ctx.ov, esc = ctx.esc;
  if (!ov.budget || !ov.budget.batch.length) return '';
  const byId = Object.fromEntries(ctx.findings.map(f => [f.id, f]));
  const sugg = ov.budget.suggestions.map(s => {
    const open = s.ids.filter(x => !(ctx.dec[x] && ctx.dec[x].decision)).length;
    return `<div class="sugg"><span>${esc(s.tool)} · ${esc(s.kind)}${s.role ? ' · ' + esc(s.role) : ''}: ${open} undecided, suggested <b>${esc(s.decision)}</b> (${esc(s.why)})</span>${open ? `<button data-batch="${esc(s.example)}" data-d="${esc(s.decision)}" data-ids="${esc(s.ids.join(','))}">${esc(s.decision[0].toUpperCase() + s.decision.slice(1))} these ${open}</button>` : ''}</div>`;
  }).join('');
  return `<details class="batch"><summary>Low priority: batch (${ov.budget.batch.length} items beyond your ${esc(ov.budget.max)} questions)</summary>
    <p class="ov">Suggested grouped decisions (each one can still be changed below):</p>${sugg}
    ${ov.budget.batch.map(id => byId[id] ? itemHTML(byId[id]) : '').join('')}</details>`;
}
function ovBind(api) {
  document.addEventListener('input', e => {
    const r = e.target.closest('input[data-amount]');
    if (r && r.nextElementSibling) r.nextElementSibling.textContent = r.value + '%';
  });
  document.addEventListener('change', e => {
    const r = e.target.closest('input[data-amount]');
    if (r) api.amount(r.dataset.amount, parseInt(r.value, 10));
  });
  document.addEventListener('click', e => {
    const b = e.target.closest('button[data-like]');
    if (b) { api.decideLike(b.dataset.like, b.dataset.d); return; }
    const g = e.target.closest('button[data-batch]');
    if (g && confirm(`Record "${g.dataset.d}" for these items without listening to each?`)) api.batch(g.dataset.ids.split(','), g.dataset.d, 'batch: like ' + g.dataset.batch);
  });
  document.addEventListener('submit', e => {
    const fm = e.target.closest('form[data-noteform]');
    if (!fm) return;
    e.preventDefault();
    const text = fm.elements.text.value.trim();
    if (text) api.note(fm.dataset.noteform, text, fm.elements.at.value.trim());
  });
}
"""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Review: __TITLE__</title>
<style>
:root{--bg:#f6f4ef;--card:#fff;--ink:#1d1b18;--mute:#6b665e;--line:#e2ddd2;--hi:#b3261e;--med:#a8640a;--low:#3d6b4f;
--info:#5a6472;--ok:#2f6f4f;--skip:#7a756c;--chg:#8a5a00;--accent:#3b4cca}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--card:#201f1c;--ink:#ece8df;--mute:#a09a8e;--line:#34322d;
--hi:#ff8a80;--med:#f0b455;--low:#8fc7a4;--info:#9aa6b6;--ok:#7fd0a4;--skip:#a09a8e;--chg:#f0b455;--accent:#9aa7ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 120px}h1{font-size:1.5rem;margin:0 0 4px}
.sub{color:var(--mute);margin:0 0 16px}.prefs{border-left:3px solid var(--accent);padding:4px 12px;margin:0 0 16px;color:var(--mute)}
.warn{border-left:3px solid var(--hi);padding:4px 12px;margin:0 0 16px}
.bar{position:sticky;top:0;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);display:flex;gap:8px;
flex-wrap:wrap;align-items:center;z-index:2}.bar .count{margin-right:auto;font-variant-numeric:tabular-nums}
button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;padding:6px 12px;cursor:pointer}
button:hover{border-color:var(--mute)}button.on.approve{background:var(--ok);color:#fff;border-color:var(--ok)}
button.on.skip{background:var(--skip);color:#fff;border-color:var(--skip)}button.on.change{background:var(--chg);color:#fff;border-color:var(--chg)}
.item{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:14px 0}
.item.done{opacity:.72}.head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.sev{font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.sev.high{color:var(--hi)}.sev.medium{color:var(--med)}.sev.low{color:var(--low)}.sev.info{color:var(--info)}
.tag{font-size:.75rem;border:1px solid var(--line);border-radius:99px;padding:1px 8px;color:var(--mute)}
.tag.prot{border-color:var(--hi);color:var(--hi)}.where{color:var(--mute);font-variant-numeric:tabular-nums}
.title{font-weight:600}.fix{color:var(--mute);margin:6px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}
pre.fix{font:13px/1.45 ui-monospace,monospace;max-height:220px;overflow:auto;background:var(--bg);padding:8px;border-radius:8px}
.ab{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0 0}.ab label{font-size:.8rem;color:var(--mute);display:block}
.ab audio{width:100%}.note{font-size:.85rem;color:var(--mute);margin:8px 0 0}
.act{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 0}.act input{flex:1;min-width:180px;font:inherit;padding:6px 10px;
border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
code{font:13px ui-monospace,monospace;background:var(--bg);padding:1px 5px;border-radius:5px}
@media (max-width:560px){.ab{grid-template-columns:1fr}}
__OVCSS__
</style></head><body><main>
<h1>Review: __TITLE__</h1>
<p class="sub">Nothing has been changed. Listen, decide each item, then apply only what you approved.</p>
<div id="top"></div>
<div class="bar"><span class="count" id="count"></span>
<span class="who"><label for="who">Reviewer</label><input id="who" placeholder="your name"></span>
<button id="alllow" title="Low-severity items that are not protected">Approve all low</button>
<button id="dl">Download decisions</button></div>
<div id="list"></div>
<div id="batch"></div>
<div id="info"></div>
<p class="sub" id="apply"></p>
</main>
<script>
const DATA = __DATA__;
const OUTEXT = /\.rpp$/i.test(DATA.set || '') ? '.rpp' : '.als';   // a REAPER scan is fixed into a new .rpp
const served = location.protocol.startsWith('http');
const KEY = 'hypnomix-review:' + DATA.set;
let dec = Object.assign({}, DATA.decisions);
let notes = Object.assign({}, DATA.ov.notes);
let who = DATA.ov.reviewer || '';
if (!served) { try { const s = JSON.parse(localStorage.getItem(KEY) || '{}');
  if (s.decisions) { Object.assign(dec, s.decisions); Object.assign(notes, s.notes || {}); who = s.who || who; } else Object.assign(dec, s); } catch (e) {} }
try { who = localStorage.getItem('hypnomix-reviewer') || who; } catch (e) {}
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const stamp = () => new Date().toISOString().slice(0,16).replace('T',' ');
function keepLocal() { if (!served) { try { localStorage.setItem(KEY, JSON.stringify({decisions: dec, notes, who})); } catch (e) {} } }
function post(path, body) {
  return fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(Object.assign({by: who}, body))})
    .then(r => { if (!r.ok) return r.text().then(t => { throw new Error(t); }); return r.json(); })
    .catch(e => alert('Could not save: ' + e.message + ' (is `hypnomix review --serve` still running?)'));
}
function persist(id) {
  if (served) post('/decide', {id, decision: dec[id].decision, note: dec[id].note || '', amount: dec[id].amount});
  else keepLocal();
}
function setDecision(id, d, note, extra) {
  const old = dec[id] || {};
  dec[id] = Object.assign({decision: d, note: note || old.note || '', at: stamp(), by: who || 'owner'},
                          old.amount != null && d !== 'skip' ? {amount: old.amount} : {},
                          old.conflicts ? {conflicts: old.conflicts} : {}, extra || {});
  persist(id); render();
}
const api = {
  amount(id, v) {
    const d = dec[id];
    if (d && d.decision) { d.amount = v; d.at = stamp(); } else dec[id] = {decision: 'approve', note: '', amount: v, at: stamp(), by: who || 'owner'};
    persist(id); render();
  },
  decideLike(id, d) {
    const ids = ovLikeIds(DATA.ov, dec, id);
    if (!ids.length || !confirm(`Record "${d}" for ${ids.length} finding(s) like ${id}? (${ids.join(', ')})`)) return;
    const amt = dec[id] && dec[id].amount;
    if (!(dec[id] && dec[id].decision)) dec[id] = {decision: d, note: '', at: stamp(), by: who || 'owner'};
    ids.forEach(x => { dec[x] = Object.assign({decision: d, note: '', at: stamp(), by: who || 'owner', via: 'like:' + id}, amt != null && d !== 'skip' ? {amount: amt} : {}); });
    if (served) post('/decide-like', {id, decision: d, amount: amt}).then(render); else { keepLocal(); render(); }
  },
  batch(ids, d, note) { ids.filter(x => !(dec[x] && dec[x].decision)).forEach(x => setDecision(x, d, note)); },
  note(id, text, at) {
    const row = {by: who || 'owner', at: stamp(), text};
    if (/^(bar\s*)?\d+(\.\d+){0,2}$/i.test(at)) row.bar = at.replace(/bar\s*/i, '');
    else if (at) { const m = at.match(/^(?:(\d+):)?(\d+(?:\.\d+)?)\s*s?$/); if (!m || (!m[1] && !/s$/.test(at))) { alert('Timestamp: a bar (33 or 33.2) or a time (1:23.5 or 83s)'); return; } row.sec = (m[1] ? +m[1] * 60 : 0) + +m[2]; }
    (notes[id] = notes[id] || []).push(row);
    if (served) post('/note', {id, text, at}); else keepLocal();
    render();
  },
};
function itemHTML(f) {
  const d = dec[f.id] && dec[f.id].decision, ab = DATA.ab[f.id] || {};
  const fix = String(f.fix || '');
  const players = ab.a ? `<div class="ab"><div><label>A · now</label><audio controls preload="none" src="ab/${encodeURIComponent(ab.a)}"></audio></div>
    <div><label>B · with the fix${ab.matched_db ? ' (level-matched ' + (ab.matched_db > 0 ? '+' : '') + ab.matched_db + ' dB)' : ''}</label><audio controls preload="none" src="ab/${encodeURIComponent(ab.b)}"></audio></div></div>` : '';
  const note = ab.note ? `<p class="note">${esc(ab.note)}</p>` : ((f.applies === 'set' || f.applies === 'audio') && !ab.a ? '<p class="note">No preview yet: run <code>hypnomix ab</code>.</p>' : '');
  const act = f.applies === 'answer' ? `<p class="note">A question, not a fix: tell your assistant the answer (recorded with <code>hypnomix fix DIR --answer NOTE</code>).</p>` : f.applies === 'info' ? '' : `<div class="act">
    ${['approve','skip','change'].map(x => `<button class="${x}${d === x ? ' on' : ''}" data-id="${esc(f.id)}" data-d="${x}">${x[0].toUpperCase() + x.slice(1)}</button>`).join('')}
    <input placeholder="note (what to change, or why)" data-note="${esc(f.id)}" value="${esc(dec[f.id] && dec[f.id].note)}"></div>`;
  return `<div class="item${d ? ' done' : ''}" id="item-${esc(f.id)}"><div class="head"><span class="sev ${esc(f.severity)}">${esc(f.severity)}</span>
    <span class="title">${esc(f.track || f.tool)}</span><span class="where">${esc(f.where || '')}</span>
    <span class="tag">${esc(f.tool)} · ${esc(f.applies)}</span><span class="tag">${esc(f.id)}</span>
    ${f.protected ? '<span class="tag prot">protected: ask again</span>' : ''}</div>
    <div>${esc(f.problem)}</div>
    ${fix.includes('\n') ? `<pre class="fix">${esc(fix)}</pre>` : `<p class="fix">Proposed: ${esc(fix)}</p>`}
    ${f.history ? `<p class="note">${esc(f.history)}</p>` : ''}${players}${note}${act}
    ${ovItemHTML(f, {ov: DATA.ov, dec, notes, esc})}</div>`;
}
function render() {
  const actionable = DATA.findings.filter(f => f.applies !== 'info' && f.applies !== 'answer');
  const n = {approve:0, skip:0, change:0};
  actionable.forEach(f => { const d = dec[f.id] && dec[f.id].decision; if (d) n[d]++; });
  const left = actionable.length - n.approve - n.skip - n.change;
  document.getElementById('count').textContent =
    `${n.approve} approved · ${n.skip} skipped · ${n.change} to change · ${left} undecided`;
  const top = [];
  if (DATA.broken.length) top.push('<div class="warn"><b>Checks that did NOT run</b> (no findings there means nothing):<br>' + DATA.broken.map(esc).join('<br>') + '</div>');
  if (DATA.prefs.length) top.push('<div class="prefs">' + DATA.prefs.map(esc).join('<br>') + '</div>');
  document.getElementById('top').innerHTML = top.join('');
  const byId = Object.fromEntries(DATA.findings.map(f => [f.id, f]));
  const B = DATA.ov.budget;
  const ask = B ? B.ask.map(id => byId[id]).filter(Boolean) : DATA.findings.filter(f => f.applies !== 'info');
  const info = B ? B.info.map(id => byId[id]).filter(Boolean) : DATA.findings.filter(f => f.applies === 'info');
  document.getElementById('list').innerHTML = ask.map(itemHTML).join('');
  document.getElementById('batch').innerHTML = ovBatchHTML({ov: DATA.ov, dec, notes, esc, findings: DATA.findings}, itemHTML);
  document.getElementById('info').innerHTML = info.length ? '<h2 class="sub">Measurements (nothing to decide)</h2>' + info.map(itemHTML).join('') : '';
  document.getElementById('apply').innerHTML = served
    ? 'Saved as you click. When you are done: <code>hypnomix fix "' + esc(DATA.dir) + '" --approved --out "&lt;Song&gt; (fixed)' + OUTEXT + '"</code>'
    : 'When you are done: Download decisions, then <code>hypnomix review "' + esc(DATA.dir) + '" --import ~/Downloads/decisions.json</code> and <code>hypnomix fix "' + esc(DATA.dir) + '" --approved --out "&lt;Song&gt; (fixed)' + OUTEXT + '"</code>';
}
__OVJS__
ovBind(api);
const whoBox = document.getElementById('who');
whoBox.value = who;
whoBox.addEventListener('change', () => { who = whoBox.value.trim(); try { localStorage.setItem('hypnomix-reviewer', who); } catch (e) {} keepLocal(); });
document.addEventListener('click', e => {
  const b = e.target.closest('button[data-id]');
  if (b) { const note = document.querySelector(`input[data-note="${CSS.escape(b.dataset.id)}"]`); setDecision(b.dataset.id, b.dataset.d, note ? note.value : ''); }
});
document.addEventListener('change', e => {
  const i = e.target.closest('input[data-note]');
  if (i && dec[i.dataset.note]) { dec[i.dataset.note].note = i.value; persist(i.dataset.note); }
});
document.addEventListener('play', e => {  // one player at a time, so A and B are compared, not mixed
  document.querySelectorAll('audio').forEach(a => { if (a !== e.target) a.pause(); });
}, true);
document.getElementById('alllow').onclick = () => {
  const ids = DATA.findings.filter(f => f.severity === 'low' && !f.protected && f.applies !== 'info' && f.applies !== 'answer' && !dec[f.id]).map(f => f.id);
  if (ids.length && confirm(`Approve ${ids.length} low-severity item(s) without listening to each?`)) ids.forEach(id => setDecision(id, 'approve', 'batch: all low'));
};
document.getElementById('dl').onclick = () => {
  const a = document.createElement('a');
  const doc = {format: 'hypnomix-review', version: 1, by: who || 'owner', exported: stamp(), decisions: dec, notes, findings: DATA.ov.fingerprints};
  a.href = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 1)], {type:'application/json'}));
  a.download = 'decisions.json'; a.click();
};
render();
</script></body></html>
"""


def load(sd):
    from hypnomix.core import atomic
    data = atomic.load_json(sd / "findings.json")
    if data is None:
        raise FileNotFoundError(f"no findings.json in {sd}")
    dec = atomic.load_json(sd / "decisions.json", {})
    ab = json.loads((sd / "ab" / "ab.json").read_text()) if (sd / "ab" / "ab.json").exists() else {}
    return data, dec, ab


def like_map(findings, role_of, band=0.5):
    """{id: [ids of findings like it]} ignoring decisions (the page filters out the decided ones)."""
    out, groups = {}, {}
    for f in findings:
        if f.get("applies") not in ("info", "answer"):
            groups.setdefault((f.get("tool"), f.get("kind")), []).append(f)
    for fs in groups.values():
        if len(fs) < 2:
            continue
        for f in fs:
            m = [g["id"] for g in O.like(fs, {}, f, band=band, role_of=role_of)]
            if m:
                out[f["id"]] = m
    return out


def oversight_payload(sd, findings=None, prefs=None):
    """Everything the oversight pieces need, for the page and for the app:

      extras[id]   {confidence, confidence_from, usually, practice, why (teach on), scalable, scale_note, size}
      like[id]     ids of the findings like this one (same tool/kind/role, size within +-50%); filter decided ones
      budget       None, or {max, ask: [ids], batch: [ids], info: [ids], suggestions: [{example, decision, ids, why}]}
      notes        review-notes.json ({id: [{by, at, text, bar|sec}]})
      teach        bool (prefs review.teach)
      reviewer     prefs review.name or ''
      fingerprints {id: [tool, track, kind, where, device]} (portable exports match on these)

    Write back with record(sd, id, decision, note, amount=, by=), record_like(sd, id, decision, amount=, by=),
    O.add_note(sd, id, text, at, by)."""
    from hypnomix.workflow import prefs as P
    sd = Path(sd)
    prefs = P.load() if prefs is None else prefs
    if findings is None:
        findings = json.loads((sd / "findings.json").read_text())["findings"]
    role_of = O.roles(sd)
    teach = O.teach_on(prefs)
    extras = {f["id"]: O.extras(f, prefs, role_of, teach_on=teach) for f in findings}
    mq = O.max_questions(prefs)
    ask, batch, info = O.budget(findings, mq)
    budget = None
    if mq:
        budget = dict(max=mq, ask=[f["id"] for f in ask], batch=[f["id"] for f in batch], info=[f["id"] for f in info],
                      suggestions=O.batch_suggestions(batch, prefs, role_of) if batch else [])
    return dict(extras=extras, like=like_map(findings, role_of), budget=budget, notes=O.load_notes(sd), teach=teach,
                reviewer=str(P.get(prefs, "review.name") or ""),
                fingerprints={f["id"]: O.fingerprint(f) for f in findings})


def build(sd):
    from hypnomix.workflow import prefs as P
    data, dec, ab = load(sd)
    notes = data.get("notes", [])
    payload = dict(set=data.get("set", ""), dir=str(sd), findings=data["findings"], decisions=dec, ab=ab,
                   prefs=P.summary(P.load()), broken=[n for n in notes if "failed" in n or n.startswith("WARNING")],
                   ov=oversight_payload(sd, data["findings"]))
    blob = json.dumps(payload, default=str).replace("</", "<\\/")
    title = html.escape(Path(data.get("set") or sd.name).stem)
    page = (PAGE.replace("__OVCSS__", OVERSIGHT_CSS).replace("__OVJS__", OVERSIGHT_JS)
            .replace("__TITLE__", title).replace("__DATA__", blob))
    out = sd / "REVIEW.html"
    out.write_text(page)
    return out


def _amount(amount):
    if amount is None:
        return None
    try:
        amount = int(round(float(amount)))
    except (TypeError, ValueError):
        raise ValueError("amount must be a number from 0 to 100")
    if not 0 <= amount <= 100:
        raise ValueError("amount must be from 0 to 100")
    return amount


def record(sd, fid, decision, note="", amount=None, by=None, via=None):
    data, dec, _ = load(sd)
    ids = {f["id"] for f in data["findings"]}
    if fid not in ids:
        raise ValueError(f"unknown id: {fid}")
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    old = dec.get(fid) if isinstance(dec.get(fid), dict) else {}
    e = O.entry(decision, note, _amount(amount), by=by, via=via)
    if old.get("conflicts"):                 # a conflict stays visible until it is settled
        e["conflicts"] = old["conflicts"]
    dec[fid] = e
    O.save_decisions(sd, dec)
    return e


def record_like(sd, fid, decision, amount=None, by=None, band=0.5):
    """The same decision for every undecided finding like fid (and fid itself if undecided). Returns the ids."""
    data, dec, _ = load(sd)
    by_id = {f["id"]: f for f in data["findings"]}
    if fid not in by_id:
        raise ValueError(f"unknown id: {fid}")
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    amount = _amount(amount)
    matched = O.like(data["findings"], dec, by_id[fid], band=band, role_of=O.roles(sd))
    done = []
    if not O.decision_of(dec, fid):
        dec[fid] = O.entry(decision, "", amount, by=by)
        done.append(fid)
    for f in matched:
        dec[f["id"]] = O.entry(decision, "", amount, by=by, via=f"like:{fid}")
        done.append(f["id"])
    O.save_decisions(sd, dec)
    return done


def import_file(sd, path):
    incoming = json.loads(Path(path).expanduser().read_text())
    notes_in = {}
    if isinstance(incoming, dict) and incoming.get("format") == "hypnomix-review":
        notes_in = incoming.get("notes") or {}
        incoming = incoming.get("decisions") or {}
    n, bad = 0, []
    for fid, d in incoming.items():
        what = d.get("decision") if isinstance(d, dict) else d
        try:
            if isinstance(d, dict):
                record(sd, fid, what, d.get("note", ""), d.get("amount"), d.get("by"), d.get("via"))
            else:
                record(sd, fid, what)
            n += 1
        except ValueError as e:
            bad.append(str(e))
    have, k = O.load_notes(sd), 0
    for fid, rows in notes_in.items():
        cur = have.setdefault(fid, [])
        for r in rows:
            if r not in cur:
                cur.append(r)
                k += 1
    if k:
        (sd / O.NOTES_FILE).write_text(json.dumps(have, indent=1))
    print(f"imported {n} decision(s) into {sd / 'decisions.json'}" + (f" and {k} note(s)" if k else ""))
    for b in bad[:10]:
        print(f"  ignored: {b}")


def serve(sd, port):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import unquote
    root = sd.resolve()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = unquote(self.path.split("?")[0])
            if path in ("/", "/REVIEW.html"):
                return self.send(200, build(sd).read_bytes(), "text/html; charset=utf-8")
            if path.startswith("/ab/"):
                f = (root / "ab" / Path(path[4:]).name)
                if f.is_file() and f.suffix == ".wav":
                    return self.send(200, f.read_bytes(), "audio/wav")
            self.send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path not in ("/decide", "/decide-like", "/note") or self.headers.get(
                    "Origin", f"http://127.0.0.1:{port}") not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
                return self.send(403, b"no", "text/plain")
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 20000)))
                by = body.get("by") or None
                if self.path == "/decide":
                    record(sd, body["id"], body["decision"], body.get("note", ""), body.get("amount"), by)
                    print(f"  {body['id']}: {body['decision']}" + (f"@{body['amount']}" if body.get("amount") is not None else "")
                          + (f"  ({body['note']})" if body.get("note") else "") + (f"  by {by}" if by else ""))
                    out = {}
                elif self.path == "/decide-like":
                    ids = record_like(sd, body["id"], body["decision"], body.get("amount"), by)
                    print(f"  {body['decision']} for {len(ids)} like {body['id']}: {', '.join(ids)}")
                    out = {"ids": ids}
                else:
                    out = O.add_note(sd, body["id"], body.get("text", ""), body.get("at"), by)
                    print(f"  note on {body['id']}: {str(body.get('text', ''))[:80]}")
                self.send(200, json.dumps(out).encode(), "application/json")
            except Exception as e:
                self.send(400, str(e).encode(), "text/plain")

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"review page: http://127.0.0.1:{port}/   (this computer only; Ctrl-C to stop)\n"
          f"decisions are saved to {sd / 'decisions.json'} as they are made")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


def main():
    ap = argparse.ArgumentParser(prog="hypnomix review", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scan_dir")
    ap.add_argument("--serve", action="store_true", help="serve the page locally and save decisions as they are made")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--import", dest="imp", metavar="FILE", help="take in a decisions.json downloaded from the page")
    ap.add_argument("--export", metavar="FILE", help="write a portable review (decisions + notes) to send to someone")
    ap.add_argument("--merge", metavar="FILE", help="merge a collaborator's exported review (conflicts are listed)")
    ap.add_argument("--settle", metavar="ID=mine|theirs", action="append", default=[], help="settle a merge conflict")
    ap.add_argument("--as", dest="by", metavar="NAME", help="who is reviewing (default: prefs review.name)")
    a = ap.parse_args()
    sd = Path(a.scan_dir)
    if not (sd / "findings.json").exists():
        sys.exit(f"no findings.json in {sd}: run `hypnomix scan` first")
    if a.imp:
        return import_file(sd, a.imp)
    if a.export:
        doc = O.export(sd, a.export, a.by)
        print(f"wrote {a.export}: {len(doc['decisions'])} decision(s), "
              f"{sum(len(v) for v in doc['notes'].values())} note(s), by {doc['by']}")
        return
    if a.merge:
        try:
            r = O.merge(sd, a.merge)
        except ValueError as e:
            sys.exit(str(e))
        print(f"merged {a.merge}: {len(r['adopted'])} decision(s) taken in where you had none, {len(r['same'])} the "
              f"same as yours, {r['notes']} note(s) added" + (f", {len(r['unknown'])} for findings not in this scan"
                                                               if r["unknown"] else ""))
        if r["adopted"]:
            print("  taken in (check them: `hypnomix fix DIR --list` shows who decided): " + ", ".join(r["adopted"][:30]))
        if r["conflicts"]:
            print(f"\n{len(r['conflicts'])} CONFLICT(S): you decided differently. Yours is kept until you settle each:")
            for fid, mine, c in r["conflicts"]:
                ma = f"@{mine['amount']}" if mine.get("amount") is not None else ""
                ta = f"@{c['amount']}" if c.get("amount") is not None else ""
                print(f"  {fid}: you {mine['decision']}{ma}; {c['by']} {c['decision']}{ta}"
                      + (f" ({c['note']})" if c.get("note") else ""))
            print(f'settle: hypnomix review "{sd}" --settle ID=mine   (or =theirs)')
        return
    if a.settle:
        for s in a.settle:
            if "=" not in s:
                sys.exit(f"expected ID=mine|theirs, got {s!r}")
            fid, which = (x.strip() for x in s.split("=", 1))
            try:
                e = O.settle(sd, fid, which, a.by)
            except ValueError as e_:
                sys.exit(str(e_))
            print(f"{fid}: {e['decision']}" + (f"@{e['amount']}" if e.get("amount") is not None else "") + f" ({e['settled']})")
        return
    out = build(sd)
    if a.serve:
        return serve(sd, a.port)
    _, _, ab = load(sd)
    print(out)
    if not ab:
        print(f'no before/after clips yet: hypnomix ab "{sd}"')
    print("open it in a browser; or `--serve` to save decisions as you click")


if __name__ == "__main__":
    main()
