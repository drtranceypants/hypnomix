// The review screen: findings, keyboard review, one player per card, batches, what was heard, the apply card.
// Loaded by the app's page (ui.py) after its own script, so S, esc, get, post, LS, showMsg and the oversight pieces
// (ovItemHTML, ovBatchHTML, ovBind) are already there. The page's security policy allows no inline handlers: every
// listener is attached here, in script. The rule for every decision: change only the card it is about, the counts and the
// apply card, never the whole list, so the player being listened to and the scroll position stay as they are.
(function () {
'use strict';

const SEVS = ['high', 'medium', 'low', 'info'];
const DONE = {approve: 'Approved', skip: 'Skipped', change: 'Marked to change'};
const SEVWORD = {high: 'High', medium: 'Medium', low: 'Low', info: 'Info'};
const NEWTHING = {als: 'set', rpp: 'project', ardour: 'session snapshot'};
const NOUN_ = {als: 'set', rpp: 'project', ardour: 'session', folder: 'folder'};
const DAWWORD = {als: 'Live', rpp: 'REAPER', ardour: 'Ardour'};
const dawOf = R => DAWWORD[R && R.kind] || 'your DAW';              // the DAW of the song on screen: never tell a REAPER project to do something in Live
const STATUSES = [['all', 'All'], ['undecided', 'Undecided'], ['approved', 'Approved'], ['skipped', 'Skipped'], ['change', 'To change'], ['hand', 'By hand']];

// ---------------------------------------------------------------- what a finding is, by the review's own rules
const isAct = f => f.applies !== 'info' && f.applies !== 'answer';
const byHand = f => f.applies === 'info' || (f.applies_here || f.applies) === 'manual';
const entryOf = id => S.review.decisions[id];
const dOf = f => { const e = entryOf(f.id); return e && e.decision; };
const undecided = fl => fl.filter(f => isAct(f) && !byHand(f) && !dOf(f) && !isDflt(f));   // the one definition of "undecided": the count bar and the Apply card both use it
const isDflt = f => f.default === 'approve' && !entryOf(f.id) && isAct(f);                 // on, because you have not said otherwise
const stOf = f => isDflt(f) ? 'dflt' : (dOf(f) || 'open');
const hasPrev = f => !!((S.review.ab[f.id] || {}).a);
const heardOf = id => (S.review.heard && S.review.heard[id]) || [];
let byIdFor = null, byId = null;                                   // id -> finding, made once for the findings on screen (a find() per card was squared work on a long review)
function findingOf(id) {
  const fl = S.review.findings;
  if (byIdFor !== fl) { byIdFor = fl; byId = new Map(fl.map(f => [f.id, f])); }
  return byId.get(id);
}
// how many undecided findings "the N like this" would take: the oversight pieces count them from ranges (ov.like_runs) or from lists (ov.like)
const likeN = f => { const R = S.review; return R.oversight && !R.oversight.error && isAct(f) ? ovLikeIds(R.oversight, R.decisions, f.id).length : 0; };
const nevers = () => S.review.findings.filter(f => isAct(f) && !byHand(f) && dOf(f) === 'approve' && hasPrev(f) && !heardOf(f.id).length);
const reduced = () => window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

function rvState() {
  const R = S.review;
  if (!S.rv || S.rv.dir !== R.dir) {
    const f = LS.get('hx.filter.' + R.dir, {});
    S.rv = {dir: R.dir, filter: {status: STATUSES.some(x => x[0] === f.status) ? f.status : 'all', tool: typeof f.tool === 'string' ? f.tool : ''},
      cur: LS.get('hx.cur.' + R.dir, ''), help: false, modal: false, advance: LS.get('hx.advance', true) !== false, fkey: null, prot: false, built: {}, groups: {}, seq: [], pos: {}, at: {}, ix: {}, lazy: false,
      answers: (a => (a && typeof a === 'object' && !Array.isArray(a) ? a : {}))(LS.get('hx.answers.' + R.dir, {}))};
  }
  return S.rv;
}
const saveFilter = () => LS.set('hx.filter.' + S.review.dir, S.rv.filter);

function matches(f) {
  const F = S.rv.filter, st = stOf(f);
  if (F.tool && f.tool !== F.tool) return false;
  if (F.status === 'hand') return byHand(f);
  if (byHand(f)) return true;
  switch (F.status) {
    case 'undecided': return st === 'open';
    case 'approved': return st === 'approve' || st === 'dflt';
    case 'skipped': return st === 'skip';
    case 'change': return st === 'change';
    default: return true;
  }
}

// ---------------------------------------------------------------- one card
function playersHTML(f) {
  const R = S.review, ab = R.ab[f.id] || {};
  if (!ab.a) return '';
  const src = x => '/audio?dir=' + encodeURIComponent(R.dir) + '&f=' + encodeURIComponent(x);
  const id = esc(f.id);
  const extra = [ab.model ? `B is a model of the device, not ${dawOf(R)} itself` : '', ab.matched_db ? 'level-matched ' + (ab.matched_db > 0 ? '+' : '') + ab.matched_db + ' dB' : ''].filter(x => x).join(' · ');
  return `<div class="ab1"><div class="abtop"><div role="group" aria-label="Which clip to hear, for ${id}">
      <button type="button" class="abbtn on" data-abside="a" data-for="${id}" aria-pressed="true" aria-label="Hear A: how it sounds now">A · now</button>
      <button type="button" class="abbtn" data-abside="b" data-for="${id}" aria-pressed="false" aria-label="Hear B: with the fix">B · with the fix</button></div>
      <span class="note abnow" aria-live="polite">A · now</span>${extra ? `<span class="note">${esc(extra)}</span>` : ''}</div>
    <audio controls preload="none" src="${src(ab.a)}" data-a="${src(ab.a)}" data-b="${src(ab.b)}" data-side="a" data-fid="${id}" aria-label="Player for ${id}: A is now, B is with the fix"></audio></div>`;
}
function labelOf(x, dflt) { return dflt && x === 'approve' ? 'On by default' : dflt && x === 'skip' ? 'Turn off' : x[0].toUpperCase() + x.slice(1); }
function actHTML(f) {
  const e = entryOf(f.id), dflt = isDflt(f), d = dOf(f);
  const jump = f.jump ? `<button type="button" data-jump="${esc(f.id)}" title="${esc(S.review.kind === 'rpp' ? 'Needs the Hypnomix panel open in REAPER (hypnomix reaper review)' : 'Needs the hypnomix device in your Live set')}">Show in ${esc(dawOf(S.review))}</button>` : '';
  if (f.applies === 'answer') {                                        // a question: the answer is sent with Apply (fix --answer), not decided here
    const nt = (f.notes || []).filter(x => x), v = (S.rv.answers || {})[f.id] || '';
    return `<div class="act"><label for="ans-${esc(f.id)}">Your answer</label><input type="text" id="ans-${esc(f.id)}" data-answer="${esc(f.id)}" list="ansl-${esc(f.id)}" value="${esc(v)}" placeholder="${esc('for example ' + (nt[1] || nt[0] || 'F#') + ', or both')}">
      <datalist id="ansl-${esc(f.id)}">${nt.concat(['both']).map(x => `<option value="${esc(x)}"></option>`).join('')}</datalist></div>
      <p class="note">A question, not a fix. Your answer goes in with Apply, and the key is then read section by section; leave it empty to keep those notes as sung. To give it for only some bars write BARS=NOTE (for example ${esc((f.bars && f.bars[0]) || '17-24')}=${esc(nt[0] || 'F')}).</p>`;
  }
  if (f.applies === 'info') return jump ? `<div class="act">${jump}</div>` : '';
  return `<div class="act">${['approve', 'skip', 'change'].map(x => {
      const on = d === x || (dflt && x === 'approve');
      return `<button type="button" class="${x}${on ? ' on' : ''}${dflt && x === 'approve' ? ' dflt' : ''}" data-did="${esc(f.id)}" data-d="${x}" aria-pressed="${on}"${dflt && x === 'skip' ? ' title="Records a skip: this step will not run"' : ''}>${labelOf(x, dflt)}</button>`;
    }).join('')}${jump}<input type="text" aria-label="Note for ${esc(f.id)}" placeholder="note (what to change, or why)" data-note="${esc(f.id)}" value="${esc(e && e.note)}"></div>`;
}
function dtagHTML(f) {
  const d = dOf(f);
  return isDflt(f) ? '<span class="tag dflt">On by default: runs unless you turn it off</span>' : (f.default === 'approve' && d === 'skip' ? '<span class="tag off">turned off</span>' : '');
}
function htagHTML(f) {
  const h = heardOf(f.id);
  if (!isAct(f) || !hasPrev(f)) return '';
  if (dOf(f) === 'approve' && !h.length) return '<span class="tag warnp" title="Approved without playing the before / after clip">approved, never played</span>';
  return h.length ? `<span class="tag heard" title="You played ${h.map(x => x.toUpperCase()).join(' and ')}">heard ${h.map(x => x.toUpperCase()).join(' + ')}</span>` : '';
}
function ovZone(f) {
  const R = S.review;
  const ovc = R.oversight && !R.oversight.error ? {ov: R.oversight, dec: R.decisions, notes: R.oversight.notes || {}, esc, findings: R.findings} : null;
  return ovc && f.applies !== 'answer' ? ovItemHTML(f, ovc) : '';          // a question has no confidence or common practice to show
}
function blindNote(f) {
  const rows = (S.review.blind || []).filter(r => r.id === f.id);
  if (!rows.length) return '';
  const b = rows.filter(r => r.chose === 'B').length;
  return `<p class="note">Blind test in ${esc(dawOf(S.review))}: you chose the fix ${b} of ${rows.length} time(s)${b * 2 > rows.length ? ', so approving it matches your ears' : b * 2 < rows.length ? ': you preferred what you have' : ''}.</p>`;
}
// A note written for the command line, said in the page's own words: a REAPER project is told to use the page's A/B button, never `abset`.
const noteWords = (R, t) => R && R.kind === 'rpp' ? String(t).replace(/`ab` plays Live sets\. Apply this one fix into a new project \(fix --approve\) and listen there, or build the A\/B project with `hypnomix abset`\./,
  'To hear it, use "Build A/B project for REAPER" above (every fix, with your own plug-ins), or approve just this one, apply, and listen in the new project.') : t;
function cardHTML(f) {
  const R = S.review, ab = R.ab[f.id] || {};
  const fix = f.applies === 'answer' ? String(f.fix || '').replace(/^ask:\s*/i, '').replace(/\s*Then tune with the answer:[\s\S]*$/, '') : String(f.fix || '');   // the question, without the command that answers it
  const st = stOf(f), id = esc(f.id);
  const note = ab.note ? `<p class="note">${esc(noteWords(R, ab.note))}</p>` : ((f.applies === 'set' || f.applies === 'audio') && !ab.a ? '<p class="note">No before / after clip yet: run <code>hypnomix ab</code> (clip fixes, tuning, timing nudges and device changes it can model). Where it cannot play a fix offline it says why here: then apply that one fix into a new set and listen.</p>' : '');
  const hand = (f.applies_here || f.applies) === 'manual' ? '<p class="note">By hand: hypnomix will not change this itself, even if you approve it. It goes on the handoff list (a checklist with a marker at each spot).</p>' : '';
  return `<article class="card item${st !== 'open' ? ' done' : ''} st-${st}${S.rv.cur === f.id ? ' cur' : ''}" id="f-${id}" data-id="${id}" data-state="${st}" data-liken="${likeN(f)}" role="listitem" tabindex="-1" aria-labelledby="h-${id}">
    <div class="head"><span class="sev ${esc(f.severity)}">${esc(f.severity)}</span>
      <h4 class="title" id="h-${id}">${esc(f.track || f.tool)}</h4><span class="where">${esc(f.where || '')}</span>
      <span class="tag">${esc(f.tool)} · ${esc(f.applies)}</span><span class="tag">${id}</span><span class="dtag">${dtagHTML(f)}</span>
      ${f.protected ? '<span class="tag prot">protected: ask again</span>' : ''}<span class="htag">${htagHTML(f)}</span>
      ${R.ab_live && R.ab_live.items && R.ab_live.items[f.id] && R.ab_live.items[f.id].parts.length ? `<span class="tag">A/B in ${esc(dawOf(R))}</span>` : ''}</div>
    <div>${esc(f.problem)}</div>
    ${fix.includes('\n') ? `<pre class="fix">${esc(fix)}</pre>` : `<p class="fix">${f.applies === 'answer' ? 'Question' : 'Proposed'}: ${esc(fix)}</p>`}
    ${f.history ? `<p class="note">${esc(f.history)}</p>` : ''}${hand}${playersHTML(f)}${note}${blindNote(f)}
    <div class="actwrap">${actHTML(f)}</div><div class="ovwrap">${ovZone(f)}</div></article>`;
}

// ---------------------------------------------------------------- the list: fixes you can hear first, by severity; by hand apart
// A long review (more than LAZY_ABOVE cards on screen) is built a group and a page at a time: every group shows its full count,
// the first one opens with PAGE cards, the others wait behind a button, and a group that is open adds PAGE more when its end
// scrolls into view (or the button, or the keyboard, reaches it). A card is only an element once it is built; a decision,
// a count or a filter reads the findings, never the page. A short review is built whole, as it always was.
const LAZY_ABOVE = 150, PAGE = 100, SMALL = 40;
function lazyGroup(key, list, first, inSeq) {
  const S_ = S.rv, i = S_.cur ? list.findIndex(f => f.id === S_.cur) : -1;
  let built = S_.built[key];
  if (list.length > SMALL) S_.first = false;                             // only the first big group of the list opens by itself
  if (built == null) built = list.length <= SMALL ? list.length : first ? PAGE : 0;       // a small group is built whole; a big one waits behind its count
  if (i >= 0) built = Math.max(built, i + 1);                            // the card you were on is always there
  built = S_.built[key] = Math.min(list.length, built);
  S_.groups[key] = {list, built};
  if (inSeq) list.forEach((f, n) => { S_.pos[f.id] = S_.seq.length; S_.seq.push(f.id); S_.at[f.id] = key; S_.ix[f.id] = n; });
  return S_.groups[key];
}
function moreHTML(key) {
  const g = S.rv.groups[key], left = g ? g.list.length - g.built : 0;
  if (left <= 0) return `<div class="more" id="gm-${key}"></div>`;
  const next = Math.min(PAGE, left);
  return `<div class="more" id="gm-${key}" data-more="${key}"><button type="button" data-more="${key}" aria-controls="gl-${key}">${g.built ? `Show ${next} more` : `Show the first ${next}`}</button>
    <span class="note">${g.built ? `${left} more are not shown yet: they come as you scroll to the end of the list, or when you press the button.` : `${left} are not shown yet: press the button to show them, ${PAGE} at a time.`} The counts above are for all of them.</span></div>`;
}
let moreIO = null;
function watchMore() {                                                   // an open group's end comes into view: build the next page
  if (moreIO) { moreIO.disconnect(); moreIO = null; }
  if (!window.IntersectionObserver || !S.rv || !S.rv.lazy) return;
  moreIO = new IntersectionObserver(es => es.forEach(en => {
    const k = en.isIntersecting && S.view === 'review' && S.rv && en.target.dataset.more;
    if (k && S.rv.groups[k] && S.rv.groups[k].built > 0) showMore(k);
  }), {rootMargin: '0px 0px 700px 0px'});
  document.querySelectorAll('#rvlist .more[data-more]').forEach(m => moreIO.observe(m));
}
function showMore(key, upTo) {                                           // build the next page of a group (or up to a card), and nothing else
  const g = S.rv && S.rv.groups[key], box = document.getElementById('gl-' + key);
  if (!g || !box) return null;
  const to = Math.min(g.list.length, Math.max(g.built + PAGE, upTo || 0));
  if (to <= g.built) return null;
  const first = g.list[g.built].id;
  box.insertAdjacentHTML('beforeend', g.list.slice(g.built, to).map(cardHTML).join(''));
  g.built = S.rv.built[key] = to;
  const m = document.getElementById('gm-' + key); if (m) m.outerHTML = moreHTML(key);
  watchMore();
  return first;
}
function revealId(id) {                                                  // make the card of this finding exist (it is in a group that is not built that far)
  const key = S.rv && S.rv.at[id];
  if (!key) return false;
  const g = S.rv.groups[key], i = g.list.findIndex(f => f.id === id);
  return i >= g.built ? showMore(key, i + 1) !== null : false;
}
function sevGroups(list, keyPrefix) {
  return SEVS.map(sev => {
    const g = list.filter(f => f.severity === sev || (!SEVS.includes(f.severity) && sev === 'info'));
    if (!g.length) return '';
    const head = `<h3 class="sevhead ${sev}" id="sg-${keyPrefix}-${sev}">${SEVWORD[sev]} <span class="note cnt">${g.length}</span></h3>`;
    if (!S.rv.lazy) return `<div class="sevgrp" data-sev="${sev}">${head}<div role="list" aria-labelledby="sg-${keyPrefix}-${sev}">${g.map(cardHTML).join('')}</div></div>`;
    const key = keyPrefix + '-' + sev, lg = lazyGroup(key, g, S.rv.first, true);
    return `<div class="sevgrp" data-sev="${sev}">${head}<div role="list" id="gl-${key}" aria-labelledby="sg-${keyPrefix}-${sev}">${g.slice(0, lg.built).map(cardHTML).join('')}</div>${moreHTML(key)}</div>`;
  }).join('');
}
function sectionHTML(key, title, list) {
  return list.length ? `<section class="grpsec" data-sec="${key}" aria-labelledby="sh-${key}"><h2 id="sh-${key}">${title} <span class="note cnt">${list.length}</span></h2>${sevGroups(list, key)}</section>` : '';
}
function listHTML() {
  const R = S.review, F = S.rv.filter;
  const ovc = R.oversight && !R.oversight.error ? {ov: R.oversight, dec: R.decisions, notes: R.oversight.notes || {}, esc, findings: R.findings} : null;
  const inBatch = new Set(ovc && ovc.ov.budget ? ovc.ov.budget.batch : []);
  const flow = R.findings.filter(f => !byHand(f) && !inBatch.has(f.id) && (f.applies === 'answer' || isAct(f)));
  const hand = R.findings.filter(f => byHand(f) && !inBatch.has(f.id));
  const shown = F.status !== 'hand' ? flow.filter(matches) : [], handShown = hand.filter(f => !F.tool || f.tool === F.tool);
  S.rv.lazy = shown.length + handShown.length + inBatch.size > LAZY_ABOVE;
  Object.assign(S.rv, {groups: {}, seq: [], pos: Object.create(null), at: Object.create(null), ix: Object.create(null), first: true});      // the groups of this list, and the order the keys walk
  let h = '';
  if (F.status !== 'hand') {
    const fixes = shown.filter(isAct);
    h += sectionHTML('with', 'Fixes you can hear first', fixes.filter(hasPrev));
    h += sectionHTML('without', 'Fixes with no before / after clip yet', fixes.filter(f => !hasPrev(f)));
    h += sectionHTML('ask', 'Questions for you', shown.filter(f => f.applies === 'answer'));
    if (!shown.length && flow.length) h += '<p class="note" id="rvnone">Nothing here matches this filter. Choose All to see every finding.</p>';
  }
  h += handHTML(handShown, hand.length);
  h += ovc ? batchHTML(ovc) : '';
  return h || '<p class="note">No findings.</p>';
}
function batchHTML(ovc) {                                                // the low-priority batch: its cards are built when it is opened (in a long review)
  if (!S.rv.lazy) return ovBatchHTML(ovc, cardHTML);
  const html = ovBatchHTML(ovc, () => '');
  if (!html) return '';
  const lg = lazyGroup('batch', ovc.ov.budget.batch.map(findingOf).filter(Boolean), false, false);
  return html.replace(/<\/details>\s*$/, `<div role="list" id="gl-batch" aria-label="Low priority findings">${lg.list.slice(0, lg.built).map(cardHTML).join('')}</div>${moreHTML('batch')}</details>`);
}
function handHTML(list, total) {
  if (!total) return '';
  const R = S.review;
  const marked = R.findings.filter(f => byHand(f) && dOf(f) === 'approve').length;
  const open = S.rv.filter.status === 'hand' || S.rv.handOpen;
  return `<details class="byhand" id="byhand"${open ? ' open' : ''}><summary>By hand in your DAW (${total})<span class="note" id="handmarked">${marked ? ' · ' + marked + ' marked for the list' : ''}</span></summary>
    <p class="note">hypnomix cannot make these changes itself, even if you approve them. They are outside the approve / skip flow above: the handoff list is a checklist in your DAW's words with a marker at each spot.</p>
    <div class="row"><button type="button" data-handoff="${esc(R.dir)}">Make the handoff list</button></div>
    ${S.rv.lazy ? handList(list, open) : `<div role="list" aria-label="Items to do by hand">${list.map(cardHTML).join('') || '<p class="note">None match this filter.</p>'}</div>`}</details>`;
}
function handList(list, open) {                                          // in a long review the by-hand cards are built when the box is opened
  const lg = lazyGroup('hand', list, open, false);
  return `<div role="list" id="gl-hand" aria-label="Items to do by hand">${lg.list.slice(0, lg.built).map(cardHTML).join('') || (list.length ? '' : '<p class="note">None match this filter.</p>')}</div>${moreHTML('hand')}`;
}

// ---------------------------------------------------------------- what Apply will do (the rule `fix --approved` follows)
function planOf(R) {
  const auto = [], defs = [], manual = [], zero = [], blocked = [], defManual = [];
  R.findings.forEach(f => {
    if (f.applies === 'info' || f.applies === 'answer') return;
    const e = R.decisions[f.id], d = e && e.decision, ap = f.applies_here || f.applies;
    const isD = !e && f.default === 'approve';
    if (d !== 'approve' && !isD) return;
    if (e && e.amount === 0) { zero.push(f); return; }
    if (ap === 'blocked') { blocked.push(f); return; }
    if (ap === 'manual') { (isD ? defManual : manual).push(f); return; }
    auto.push(f); if (isD) defs.push(f);
  });
  return {auto, defs, explicit: auto.filter(f => !defs.includes(f)), manual, zero, blocked, defManual};
}
// harmony balance is automation in a Live set, but balanced copies of the parts (no project) in REAPER and Ardour
function writesSetOf(f, kind) { return f.applies === 'set' || (f.applies === 'audio' && (f.tool === 'tune' || (f.tool === 'voices' && kind === 'als'))); }
function stepWords(f, R) {
  const first = String(f.fix || '').split('\n')[0].replace(/\. ON BY DEFAULT.*$/, '');
  if (f.kind === 'retire-off') {
    const n = f.retire_n != null ? f.retire_n + ' switched-off track' + (f.retire_n === 1 ? '' : 's') : 'the switched-off tracks';
    return `removes ${n} from the new set, after writing a full copy of the set first${R.archive_name ? ': <b>' + esc(R.archive_name) + '</b>' : ''}`;
  }
  if (f.kind === 'track-order') return 'puts the tracks in working order (sound, routing and sends unchanged)';
  if (f.kind === 'consolidate') return `moves ${esc(f.where || 'the clips')} (${esc(f.track || '')}) onto one track${f.removes ? ' and removes the empty one' : ''}`;
  if (f.kind === 'vocal-stack') return `moves ${esc(f.where || 'clips')} on ${esc(f.track || 'the vocal stack')} to the track for their pitch`;
  return esc(first.slice(0, 160));
}
const answersGiven = () => Object.keys((S.rv && S.rv.answers) || {}).filter(k => findingOf(k) && String(S.rv.answers[k]).trim()).map(k => ({id: k, text: String(S.rv.answers[k]).trim()}));
function applyHTML(R) {
  const pl = planOf(R), dec = R.decisions, nAuto = pl.auto.length;
  const writes = R.kind !== 'folder' && pl.auto.some(f => writesSetOf(f, R.kind));
  const outName = S.outName[R.dir] || R.suggested_out;
  const prot = R.findings.some(f => f.protected && dec[f.id] && dec[f.id].decision === 'approve');
  const tune = R.findings.some(f => f.tool === 'tune' && dec[f.id] && dec[f.id].decision === 'approve');
  const archive = pl.auto.some(f => f.kind === 'retire-off') && R.archive_name ? R.archive_name : '';
  const e = pl.explicit.length;
  let t = '';
  if (e) {
    t += `<p style="margin-top:0"><b>${e}</b> approved fix${e === 1 ? '' : 'es'} will be written ${R.kind === 'folder' ? 'as repaired copies in this scan\'s "fixed" folder. Your files are not changed.'
      : writes ? `into <b>one new ${NEWTHING[R.kind]}</b>, <b id="outshow">${esc(outName)}</b>, next to the original. The original is not changed.${R.kind === 'als' ? ' <b>Close the set in Live first.</b>' : ''}`
      : 'as new audio files. Your project is not changed.'}</p>`;
  } else if (pl.defs.length) t += '<p style="margin-top:0">None of your own fixes are approved.</p>';
  else t += '<p style="margin-top:0">No fix is approved yet.</p>';
  if (pl.defs.length) {
    t += `<p><b>${pl.defs.length} step${pl.defs.length === 1 ? ' is' : 's are'} on by default</b> and will run if still needed, unless you turn ${pl.defs.length === 1 ? 'it' : 'them'} off above (each is checked once the other steps have run, and one with nothing left to do is skipped; the result says which ran):</p>
      <ul class="plain">${pl.defs.map(f => `<li><span class="tag">${esc(f.id)}</span> ${stepWords(f, R)}</li>`).join('')}</ul>`;
  }
  if (pl.manual.length) {
    t += `<p class="banner"><b>${pl.manual.length} approved item${pl.manual.length === 1 ? ' is' : 's are'} by hand and will NOT be applied:</b> ${pl.manual.map(f => esc(f.id)).join(', ')}. hypnomix cannot make these changes itself: the handoff list is a checklist in your DAW's words with a marker at each spot.
      <button type="button" ${nAuto ? '' : 'class="primary" '}data-handoff="${esc(R.dir)}">Make the handoff list</button></p>`;
  }
  if (pl.defManual.length) t += `<p class="banner"><b>${pl.defManual.length} on-by-default step${pl.defManual.length === 1 ? '' : 's'} cannot be written into ${R.kind === 'ardour' ? 'an Ardour session' : 'this kind of project'} and will not run:</b> ${pl.defManual.map(f => esc(f.id)).join(', ')}. Do ${pl.defManual.length === 1 ? 'it' : 'them'} by hand (see the handoff list).</p>`;
  if (pl.blocked.length) t += `<p class="banner bad"><b>${pl.blocked.map(f => esc(f.id)).join(', ')}: tuning is not written into an Ardour session yet.</b> Turn ${pl.blocked.length === 1 ? 'it' : 'them'} off (Skip) before applying; the other fixes can go ahead.</p>`;
  if (pl.zero.length) t += `<p class="note">${pl.zero.length} item(s) are approved at 0%, so nothing is applied for them: ${pl.zero.map(f => esc(f.id)).join(', ')}.</p>`;
  if (!nAuto) t += `<p><b>Nothing here can be applied automatically.</b>${pl.manual.length ? ' Use the handoff list above.' : ' Approve a fix above (or leave an on-by-default step on).'}</p>`;
  const given = answersGiven();
  if (given.length) t += `<p><b>Your answer${given.length === 1 ? '' : 's'}</b> to the key question${given.length === 1 ? '' : 's'}: ${given.map(g => esc(g.id) + ' = ' + esc(g.text)).join('; ')}. ${tune ? 'Used when the vocal tuning runs.' : 'Used only if you approve vocal tuning.'}</p>`;
  const made = [];
  if (R.kind !== 'folder' && writes) made.push(esc(outName));
  if (archive) made.push(esc(archive));
  if (nAuto && made.length) t += `<p><b>Files that will be created next to the original:</b> ${made.join(' and ')}. Nothing is overwritten.</p>`;
  const stale = R.stale && R.stale.newer, missing = R.stale && R.stale.missing;
  const field = writes ? `<div class="row"><label for="out">New file name</label><input type="text" id="out" value="${esc(outName)}"><span class="note">ends in ${esc(R.suffix)}: added if you leave it out</span></div>` : '';
  const tuneF = tune ? `<div class="row"><label for="fkey">Confirmed key</label><input type="text" id="fkey" placeholder='needed for vocal tuning, e.g. F# major (or "sections")' value="${esc(S.rv.fkey != null ? S.rv.fkey : (S.form.key || R.scan_key || ''))}"></div>` : '';
  const protF = prot ? `<div class="row"><label for="prot">Protected tracks</label><input type="checkbox" id="prot"${S.rv.prot ? ' checked' : ''}> <span class="note">yes, change the protected tracks I approved</span></div>` : '';
  const leftFix = undecided(R.findings).length;                       // the same count as the bar above the findings
  const leftWords = !leftFix ? '' : leftFix + ' fix' + (leftFix === 1 ? '' : 'es') + ' still undecided (left alone).';
  const blockedWhy = stale ? `This ${NOUN_[R.kind] || 'song'} was saved after the scan: re-scan before applying.` : missing ? 'The original is not where the scan found it.' : '';
  return `<h2>Apply</h2><div class="card">${t}${field}${tuneF}${protF}
    <div class="row"><button type="button" class="primary" id="apply" ${nAuto && !blockedWhy && !pl.blocked.length ? '' : 'disabled'} ${writes ? 'data-writes="1"' : ''} data-archive="${esc(archive)}">Apply ${nAuto || ''}${nAuto ? (nAuto === 1 ? ' step' : ' steps') : ''}</button>
      <button type="button" data-reveal="${esc(R.dir)}">Show files</button>${pl.manual.length ? '' : `<button type="button" data-handoff="${esc(R.dir)}">Make the handoff list</button>`}<span class="note">${leftWords}${blockedWhy ? ' ' + esc(blockedWhy) : ''}</span></div>
    ${R.last_run ? `<h2>Last time it was applied</h2>${logHTML(R.last_run)}` : ''}</div>`;
}
function historyHTML(R) {
  const h = S.hist && S.hist.dir === R.dir ? S.hist : null;
  let body = '';
  if (S.histOpen) {
    body = !h ? '<p class="note">Loading…</p>' : (h.note ? `<p class="note">${esc(h.note)}</p>` : '') + (h.entries.length ? h.entries.map(v => `<div class="card">
      <b>Version ${v.n}</b> <span class="note">${esc(v.at)} · ${esc(v.kind)}</span>
      <div class="note">${v.output ? 'wrote ' + esc(v.output) : 'no new file'}${v.input ? ' from ' + esc(v.input) : ''}${v.approved.length ? ' · ' + v.approved.length + ' item(s): ' + esc(v.approved.join(', ')) : ''}${v.changes != null ? ' · ' + v.changes + ' change(s)' : ''}</div>
      ${v.failed.length ? `<div class="bad">FAILED: ${esc(v.failed.join('; '))}</div>` : ''}
      ${v.can_undo ? `<div class="act"><button type="button" data-undo="${v.n}" data-undoname="${esc(v.undo_name)}">Undo this</button></div>` : `<p class="note">${esc(v.why_not)}</p>`}</div>`).join('')
      : '<p class="note">Nothing has been applied for this song yet.</p>');
  }
  return `<h2>History</h2><div class="row"><button type="button" data-hist="1" aria-expanded="${!!S.histOpen}">${S.histOpen ? 'Hide the history' : 'Show the history'}</button>
    <span class="note">every time fixes were applied for this song, and a way back where one exists</span></div>${body}`;
}
function damageHTML(R) {
  const m = R.damaged;
  if (m.file === 'findings.json') {
    return `<div class="banner bad"><h2>This scan's results file is damaged</h2><p>${esc(m.message)}. The findings of this scan cannot be shown, and nothing was applied because of it.</p>
      <p>${R.can_rescan ? `<button type="button" class="primary" data-rescan="${esc(R.dir)}" data-kind="${esc(R.kind)}">Re-scan this song</button> makes a fresh scan in this folder.` : 'The original song is not where it was, so it cannot be scanned again from here: choose it again on the Songs tab.'}</p></div>`;
  }
  return `<div class="banner bad"><h2>This song's decisions file is damaged</h2>
    <p>hypnomix cannot read <code>decisions.json</code> (${m.size} bytes, last saved ${esc(m.when)}), so it cannot tell which fixes you approved or skipped. Nothing was applied because of it, and the scan's findings are fine.</p>
    ${m.backup ? `<p>A backup is there: your decisions as they were before the last change you saved (made ${esc(m.backup_when)}), so that one change may need doing again. <button type="button" class="primary" data-restore="${esc(R.dir)}">Restore the backup</button> The damaged file is kept next to it as decisions.damaged.json.</p>`
      : `<p><b>There is no backup, so what was in the file is lost:</b> every approve, skip and change you saved for this song, and your notes on them. The scan itself is intact, so you can decide again.
        <button type="button" class="primary" data-restore="${esc(R.dir)}" data-fresh="1">Start the decisions again</button> The damaged file is kept as decisions.damaged.json in case it can be repaired by hand.</p>`}</div>`;
}
function abLiveCard(R) {
  if (!R.is_set) return '';
  const daw = dawOf(R), noun = R.kind === 'rpp' ? 'project' : 'set';
  const how = R.kind === 'rpp' ? `open this project, then run <code>hypnomix reaper review</code> to open the Hypnomix panel in REAPER, then use <b>A · now</b>, <b>B · fix</b> and <b>Blind</b> on each finding`
    : `open this set, put the hypnomix device on any track, then use <b>A · now</b>, <b>B · fix</b> and <b>Blind</b> on each finding`;
  const ready = R.ab_live ? `<p style="margin-top:0"><b>Ready:</b> ${esc(R.ab_live.set.split(/[\\/]/).pop())}. Close the original in ${daw}, ${how}. Every plug-in plays; nothing is rendered.</p>` : '';
  return `<div class="card">${ready || `<p style="margin-top:0">Hear every fix inside ${daw}, with all your plug-ins, by switching A and B instantly.</p>`}
    <div class="row"><button type="button" id="abbuild">${R.ab_live ? 'Build it again' : `Build A/B ${noun} for ${daw}`}</button><span class="note">Writes one new ${noun} next to the original; the original is not changed.</span></div></div>`;
}

// ---------------------------------------------------------------- the bar: counts, filters
function counts() {
  const R = S.review, fl = R.findings.filter(f => isAct(f) && !byHand(f));
  const n = {approve: 0, skip: 0, change: 0};
  fl.forEach(f => { const d = dOf(f); if (d) n[d]++; });
  const onDef = fl.filter(isDflt).length;
  const left = undecided(fl).length;
  return {n, onDef, left, never: nevers().length, total: fl.length};
}
function countText() {
  const c = counts();
  return `${c.n.approve} approved${c.never ? `, ${c.never} of them never played` : ''}${c.onDef ? ' · ' + c.onDef + ' on by default' : ''} · ${c.n.skip} skipped · ${c.n.change} to change · ${c.left} undecided`;
}
function barHTML() {
  const R = S.review, F = S.rv.filter;
  const tools = [...new Set(R.findings.map(f => f.tool).filter(x => x))].sort();
  return `<div class="bar" id="rvbar"><span class="count" id="rvcount" role="status" aria-live="polite">${esc(countText())}</span>
      <button type="button" id="alllow" title="Low-severity fixes that are not taste calls, tidy steps or protected tracks: you see the list first">Approve all low…</button>
      <button type="button" id="rvhelpbtn" aria-label="Keyboard shortcuts" aria-expanded="${!!S.rv.help}" aria-controls="rvhelp">?</button></div>
    <div id="rvhelp" class="card helpbox" role="region" aria-label="Keyboard shortcuts"${S.rv.help ? '' : ' hidden'}>${helpHTML()}</div>
    <div class="filters" role="group" aria-label="Filter the findings">${STATUSES.map(([k, w]) => `<button type="button" class="chip${F.status === k ? ' on' : ''}" data-filter="${k}" aria-pressed="${F.status === k}">${w}</button>`).join('')}
      <label class="note" for="rvtool">Tool</label><select id="rvtool"><option value="">all tools</option>${tools.map(t => `<option value="${esc(t)}"${F.tool === t ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select></div>
    <div id="rvmsg" class="note" role="status" aria-live="polite"></div>`;
}
function helpHTML() {
  const k = (a, b) => `<tr><td><kbd>${a}</kbd></td><td>${b}</td></tr>`;
  return `<table class="keys"><tbody>${k('j', 'next finding (also the down arrow)') + k('k', 'previous finding (also the up arrow)') + k('a', 'approve') + k('s', 'skip') + k('c', 'change: opens the note box (Esc leaves it)')
    + k('space', 'play or pause the clip') + k('b', 'switch between A and B at the same moment') + k('[', 'previous undecided finding') + k(']', 'next undecided finding') + k('?', 'show or hide this list')}</tbody></table>
    <p class="note">The keys work when no text box has the cursor. Nothing is applied by them: they only record your answers.</p>
    <label><input type="checkbox" id="rvadvance"${S.rv.advance ? ' checked' : ''}> after approve or skip, go on to the next undecided finding</label>
    <p style="margin:10px 0 0"><button type="button" id="rvhelpclose">Close</button></p>`;
}
function setMsg(t) { const m = document.getElementById('rvmsg'); if (m) m.textContent = t || ''; }
function updateBar() {
  const c = document.getElementById('rvcount'); if (c) c.textContent = countText();
  const hm = document.getElementById('handmarked');
  if (hm) { const m = S.review.findings.filter(f => byHand(f) && dOf(f) === 'approve').length; hm.textContent = m ? ' · ' + m + ' marked for the list' : ''; }
}
function updateApply() {
  const el = document.getElementById('rvapply'); if (!el) return;
  if (el.contains(document.activeElement) && document.activeElement.tagName === 'INPUT') { S.rv.applyStale = true; return; }
  el.innerHTML = applyHTML(S.review);
  S.rv.applyStale = false;
}

// ---------------------------------------------------------------- patching one card (never the whole list)
function patchCard(id) {
  const f = findingOf(id), el = document.getElementById('f-' + id);
  if (!f || !el) return;
  const st = stOf(f), d = dOf(f), dflt = isDflt(f);
  el.dataset.state = st;
  el.className = el.className.replace(/\bst-\S+/g, '').trim() + ' st-' + st;
  el.classList.toggle('done', st !== 'open');
  el.querySelectorAll('button[data-did]').forEach(b => {
    const x = b.dataset.d, on = d === x || (dflt && x === 'approve');
    b.classList.toggle('on', on); b.classList.toggle('dflt', dflt && x === 'approve');
    b.setAttribute('aria-pressed', on); b.textContent = labelOf(x, dflt);
  });
  const dt = el.querySelector('.dtag'); if (dt) dt.innerHTML = dtagHTML(f);
  const ht = el.querySelector('.htag'); if (ht) ht.innerHTML = htagHTML(f);
  const ni = el.querySelector('input[data-note]');
  if (ni && ni !== document.activeElement) ni.value = (entryOf(id) || {}).note || '';
  const ow = el.querySelector('.ovwrap');
  if (ow && !ow.contains(document.activeElement)) { ow.innerHTML = ovZone(f); el.dataset.liken = String(likeN(f)); }
  // A card that no longer fits the filter stays where it is until the filter is applied again: the list does not
  // shift under the person's hands, and the note box of a "change" stays there to type in.
  el.classList.toggle('lingers', !byHand(f) && !matches(f));
}
// The cards on the page whose "the N like this" may have changed because these findings were decided: the ones with one of them in
// their ranges (ov.like_runs: a list of [first, last] positions in ov.like_order) or lists (ov.like, an older server).
let posFor = null, posOf = null;
function likeAffected(want) {
  const ov = S.review.oversight;
  if (!ov || ov.error) return [];
  if (!ov.like_runs) { const lk = ov.like || {}; return Object.keys(lk).filter(k => (lk[k] || []).some(x => want.has(x))); }
  if (posFor !== ov) { posFor = ov; posOf = new Map(ov.like_order.map((id, n) => [id, n])); }
  const pre = new Int32Array(ov.like_order.length + 1);
  let any = false;
  want.forEach(id => { const p = posOf.get(id); if (p != null) { pre[p + 1] = 1; any = true; } });
  if (!any) return [];
  for (let i = 1; i < pre.length; i++) pre[i] += pre[i - 1];            // pre[p + 1]: how many of them sit at positions up to p
  const out = [];
  document.querySelectorAll('#rvlist .item').forEach(el => {
    const r = ov.like_runs[el.dataset.id];
    for (let i = 0; r && i + 1 < r.length; i += 2) if (pre[r[i + 1] + 1] - pre[r[i]] > 0) { out.push(el.dataset.id); break; }
  });
  return out;
}
function patchMany(ids) {
  const want = new Set(ids);
  want.forEach(patchCard);
  likeAffected(want).forEach(k => {                                     // "the N like this" counts change: only on the cards where the number is different now
    const el = document.getElementById('f-' + k), f = findingOf(k);
    if (!want.has(k) && el && f && el.dataset.liken !== String(likeN(f))) { el.dataset.liken = likeN(f); patchCard(k); }
  });
  updateBar(); updateApply();
}

// ---------------------------------------------------------------- recording (in order, one request at a time)
let chain = Promise.resolve();
const queue = fn => { const p = chain.then(fn); chain = p.catch(() => {}); return p; };
function fail(err, what) { showMsg((what || 'Could not save') + ': ' + (err && err.message ? err.message : err)); }

const spot = id => { const f = findingOf(id); return f ? [f.track || f.tool, f.where, f.id].filter(x => x).join(', ') : id; };   // "Keys, 12.3.50, smooth-1"
function mergeEntry(id, e) { if (e) S.review.decisions[id] = Object.assign({}, S.review.decisions[id] || {}, e); }
function decideOne(id, d, note, opts) {
  const R = S.review, prev = R.decisions[id];
  const keep = prev && d !== 'skip' && prev.amount != null ? prev.amount : null;
  R.decisions[id] = Object.assign({}, prev || {}, {decision: d, note: note != null ? note : ((prev && prev.note) || '')});
  if (d === 'skip') delete R.decisions[id].amount;
  patchMany([id]);
  announce(`${DONE[d] || d}: ${spot(id)}.`);                // the same words for the mouse and the keyboard: what was decided, and where
  const body = {dir: R.dir, id, decision: d, note: R.decisions[id].note};
  if (keep != null) body.amount = keep;
  return queue(() => post('/api/decide', body)).then(r => { mergeEntry(id, r.entry); }, err => {
    if (prev) R.decisions[id] = prev; else delete R.decisions[id];
    patchMany([id]); fail(err);
  });
}
function batchDecide(ids, d, note, via) {
  const R = S.review, saved = {};
  ids.forEach(id => { saved[id] = R.decisions[id]; R.decisions[id] = Object.assign({}, R.decisions[id] || {}, {decision: d, note: note || ''}); });
  patchMany(ids);
  return queue(() => post('/api/decide', {dir: R.dir, ids, decision: d, note: note || '', via: via || 'batch'})).then(r => {
    Object.keys(r.entries || {}).forEach(id => { R.decisions[id] = r.entries[id]; }); patchMany(ids);
    announce(`Recorded ${d} for ${ids.length} item${ids.length === 1 ? '' : 's'}.`);
  }, err => { ids.forEach(id => { if (saved[id]) R.decisions[id] = saved[id]; else delete R.decisions[id]; }); patchMany(ids); fail(err); });
}
function setAmount(id, v) {
  const R = S.review, prev = R.decisions[id], d = (prev && prev.decision) || 'approve';
  R.decisions[id] = Object.assign({}, prev || {}, {decision: d, amount: v});
  patchMany([id]);
  announce(`Amount ${v}%: ${spot(id)}.`);
  return queue(() => post('/api/decide', {dir: R.dir, id, decision: d, amount: v, note: (prev && prev.note) || ''})).then(r => mergeEntry(id, r.entry), err => {
    if (prev) R.decisions[id] = prev; else delete R.decisions[id]; patchMany([id]); fail(err);
  });
}
async function addNote(id, text, at) {
  try {
    const r = await queue(() => post('/api/note', {dir: S.review.dir, id, text, at}));     // the answer is this finding's notes: the whole review is not fetched again
    const ov = S.review.oversight;
    if (ov && !ov.error && Array.isArray(r.notes)) { ov.notes = ov.notes || {}; ov.notes[id] = r.notes; }
    const ow = document.querySelector(`#f-${CSS.escape(id)} .ovwrap`); if (ow) ow.innerHTML = ovZone(findingOf(id));
  } catch (err) { fail(err, 'Could not add the note'); }
}
function markHeard(id, side) {
  const R = S.review; R.heard = R.heard || {};
  const h = R.heard[id] || [];
  if (h.includes(side)) return;
  R.heard[id] = h.concat(side).sort();
  patchCard(id); updateBar();
  queue(() => post('/api/heard', {dir: R.dir, id, which: side})).catch(() => {});          // never blocks a decision, never shown as an error
}
function announce(t) { const el = document.getElementById('sr'); if (el) { el.textContent = ''; setTimeout(() => { el.textContent = t; }, 30); } }

// ---------------------------------------------------------------- lists the person confirms before anything is recorded
function listRows(items) {
  return `<div class="tbl"><table><thead><tr><th scope="col">id</th><th scope="col">track</th><th scope="col">what</th><th scope="col">preview</th><th scope="col">played</th></tr></thead><tbody>${items.map(r =>
    `<tr><td><code>${esc(r.id)}</code></td><td>${esc(r.track)}${r.where ? ' <span class="where">' + esc(r.where) + '</span>' : ''}</td><td>${esc(r.fix || r.problem)}</td><td>${r.preview ? 'yes' : 'no'}</td><td>${r.heard ? 'yes' : 'no'}</td></tr>`).join('')}</tbody></table></div>`;
}
function modal(title, bodyHTML, okLabel) {
  return new Promise(resolve => {
    const prev = document.activeElement, S_ = S.rv;
    const ov = document.createElement('div');
    ov.className = 'rvmodal';
    ov.innerHTML = `<div class="rvbox card" role="dialog" aria-modal="true" aria-labelledby="rvmt"><h2 id="rvmt">${esc(title)}</h2><div class="rvbody">${bodyHTML}</div>
      <div class="row">${okLabel ? `<button type="button" class="primary" data-ok="1">${esc(okLabel)}</button>` : ''}<button type="button" data-cancel="1">${okLabel ? 'Cancel' : 'Close'}</button></div></div>`;
    document.body.appendChild(ov);
    S_.modal = true;
    const btns = () => [...ov.querySelectorAll('button')];
    const done = v => { document.removeEventListener('keydown', key, true); ov.remove(); S_.modal = false; if (prev && prev.focus) prev.focus({preventScroll: true}); resolve(v); };
    const key = e => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(false); }
      else if (e.key === 'Tab') {
        const b = btns(), i = b.indexOf(document.activeElement);
        if (!ov.contains(document.activeElement)) { e.preventDefault(); b[0].focus(); }
        else if (e.shiftKey && i === 0) { e.preventDefault(); b[b.length - 1].focus(); }
        else if (!e.shiftKey && i === b.length - 1) { e.preventDefault(); b[0].focus(); }
      }
    };
    document.addEventListener('keydown', key, true);
    ov.addEventListener('click', e => { const b = e.target.closest('button'); if (b) done(!!b.dataset.ok); else if (e.target === ov) done(false); });
    (ov.querySelector('[data-cancel]') || btns()[0]).focus();
  });
}
const LEFT_OUT = {taste: 'taste calls (tuning, harmony balance, motion, colour, borrowed moves, variations)', tidy: 'tidy steps (reordering, removing or merging tracks)', protected: 'on protected tracks', by_hand: 'by-hand items'};
async function approveAllLow() {
  const R = S.review;
  const r = await post('/api/decide-low', {dir: R.dir, dry_run: true});
  const left = Object.keys(r.left_out || {}).filter(k => r.left_out[k]).map(k => `${r.left_out[k]} ${LEFT_OUT[k] || k}`);
  const out = left.length ? `<p class="note">Left out, and still for you to decide one at a time: ${esc(left.join('; '))}.</p>` : '';
  if (!r.n) { await modal('Nothing to approve in bulk', `<p>No undecided low-severity fix is safe to approve without a look.</p>${out}`, ''); return; }
  const ok = await modal(`Approve these ${r.n} low-severity fixes?`, `<p><b>${r.n}</b> fix${r.n === 1 ? '' : 'es'}: <b>${r.with_preview}</b> ${r.with_preview === 1 ? 'has' : 'have'} a before / after clip, <b>${r.heard}</b> ${r.heard === 1 ? 'was' : 'were'} played. Nothing is recorded until you confirm, and nothing is applied by this.</p>${out}${listRows(r.items)}`, `Approve these ${r.n}`);
  if (!ok) return;
  const ids = r.items.map(x => x.id);
  const rec = await queue(() => post('/api/decide-low', {dir: R.dir, ids}));
  Object.keys(rec.entries || {}).forEach(id => { R.decisions[id] = rec.entries[id]; });
  patchMany(rec.ids || []);
  announce(`Approved ${(rec.ids || []).length} low-severity fixes.`);
  if ((rec.refused || []).length) showMsg(`${rec.refused.length} item(s) were left out because they are no longer allowed in a bulk approve.`);
}
async function decideLike(id, d) {
  const R = S.review;
  const r = await post('/api/decide-like', {dir: R.dir, id, decision: d, dry_run: true});
  const verb = d === 'approve' ? 'Approve' : 'Skip';
  if (!r.n) { showMsg('Nothing else is like this one.'); return; }
  const amt = (R.decisions[id] || {}).amount;
  const others = r.includes_example ? r.n - 1 : r.n;              // the button says "the N like this": the others, so the box counts them the same way
  const ok = await modal(r.includes_example && others ? `${verb} this one and the ${others} like it?` : `${verb} these ${r.n} like this?`, `<p><b>${r.n}</b> finding${r.n === 1 ? '' : 's'} (${r.includes_example ? 'this one and the undecided ones like it' : 'the undecided ones like this one'}): <b>${r.with_preview}</b> ${r.with_preview === 1 ? 'has' : 'have'} a preview, <b>${r.heard}</b> ${r.heard === 1 ? 'was' : 'were'} played.${amt != null ? ` Each is recorded at ${amt}%, this one's amount.` : ''}</p>${listRows(r.items)}`, `${verb} these ${r.n}`);
  if (!ok) return;
  const body = {dir: R.dir, id, decision: d};
  if (amt != null && d !== 'skip') body.amount = amt;
  const rec = await queue(() => post('/api/decide-like', body));
  Object.keys(rec.entries || {}).forEach(k => { R.decisions[k] = rec.entries[k]; });
  patchMany(rec.ids || []);
  announce(`Recorded ${d} for ${(rec.ids || []).length} findings.`);
}

// ---------------------------------------------------------------- keyboard: the cursor, the players
const navList = () => [...document.querySelectorAll('#rvlist .item')].filter(el => el.offsetParent !== null);
function pauseAll(except) { document.querySelectorAll('#rvlist audio').forEach(a => { if (a !== except && !a.paused) a.pause(); }); }
function setCur(id, how) {
  const old = document.querySelector('#rvlist .item.cur'); if (old) old.classList.remove('cur');
  S.rv.cur = id; LS.set('hx.cur.' + S.review.dir, id);
  let el = document.getElementById('f-' + id);
  if (!el && S.rv.lazy && revealId(id)) el = document.getElementById('f-' + id);            // a long list: the card is built when the keys reach it
  if (!el) return;
  el.classList.add('cur');
  if (how) {
    pauseAll();
    el.focus({preventScroll: true});
    el.scrollIntoView({block: 'nearest', behavior: reduced() ? 'auto' : 'smooth'});
  }
}
function curEl() { return S.rv.cur ? document.getElementById('f-' + S.rv.cur) : null; }
// In a long list the order of the findings is known without the cards: forward, the keys build the card they reach (the next
// page of a group, or the next group); backward, they stay among the cards that are built.
const seqAt = () => (S.rv.lazy ? S.rv.pos[S.rv.cur] : undefined);
const isBuilt = id => { const g = S.rv.groups[S.rv.at[id]]; return !!g && S.rv.ix[id] < g.built; };
function seqOpen(from, delta) {                        // the next undecided finding in the list's order
  const s = S.rv.seq;
  for (let k = from; k >= 0 && k < s.length; k += delta) {
    const f = findingOf(s[k]);
    if (f && stOf(f) === 'open' && (delta > 0 || isBuilt(s[k]))) return s[k];
  }
  return null;
}
function move(delta) {
  const p = seqAt();
  if (p !== undefined) {
    let j = Math.max(0, Math.min(S.rv.seq.length - 1, p + delta));
    while (delta < 0 && j > 0 && !isBuilt(S.rv.seq[j])) j--;
    if (delta < 0 && !isBuilt(S.rv.seq[j])) j = p;
    setCur(S.rv.seq[j], true);
    return;
  }
  const L = navList(); if (!L.length) return;
  let i = L.indexOf(curEl());
  i = i < 0 ? (delta > 0 ? 0 : L.length - 1) : Math.max(0, Math.min(L.length - 1, i + delta));
  setCur(L[i].dataset.id, true);
}
function jumpOpen(delta) {
  const p = seqAt();
  if (p !== undefined) {
    const id = seqOpen(p + delta, delta);
    if (id) { setCur(id, true); return; }
  } else {
    const L = navList(), i = L.indexOf(curEl());
    for (let k = i + delta; k >= 0 && k < L.length; k += delta) if (L[k].dataset.state === 'open') { setCur(L[k].dataset.id, true); return; }
    if (i < 0) { const f = L.find(el => el.dataset.state === 'open'); if (f) { setCur(f.dataset.id, true); return; } }
  }
  announce(delta > 0 ? 'No more undecided findings below.' : 'No more undecided findings above.');
  setMsg(delta > 0 ? 'No more undecided findings below.' : 'No more undecided findings above.');
}
function decideCur(d) {
  let el = curEl();
  if (!el) { const L = navList(); if (!L.length) return; setCur(L[0].dataset.id, true); el = curEl(); }
  const f = findingOf(el.dataset.id);
  if (!f || !isAct(f)) { setMsg('This one has nothing to approve or skip.'); return; }
  const wasOpen = el.dataset.state === 'open' || el.dataset.state === 'dflt';
  const L = navList(), i = L.indexOf(el);
  let next = null;
  const at = S.rv.lazy ? S.rv.pos[f.id] : undefined, nid = at !== undefined ? seqOpen(at + 1, 1) : null;     // a long list: the next undecided one, built if it is not yet
  if (at !== undefined) next = nid;
  else for (let k = i + 1; k < L.length; k++) if (L[k].dataset.state === 'open') { next = L[k]; break; }
  const id = f.id, note = (el.querySelector('input[data-note]') || {}).value;
  const p = decideOne(id, d, note);
  if (d === 'change') { const ni = document.querySelector('#f-' + CSS.escape(id) + ' input[data-note]'); if (ni) ni.focus(); return p; }
  if (S.rv.advance && wasOpen && next) setCur(at !== undefined ? next : next.dataset.id, true);
  return p;
}
function togglePlay() {
  const el = curEl(), au = el && el.querySelector('audio');
  if (!au) { setMsg('This finding has no before / after clip to play.'); return; }
  if (au.paused) { pauseAll(au); au.play().catch(() => {}); } else au.pause();
}
function abSwitch(el, side) {
  const au = el && el.querySelector('audio'); if (!au || au.dataset.side === side) return;
  const t = au.currentTime || 0, playing = !au.paused && !au.ended;
  clearTimeout(au._ht);
  au.dataset.side = side;
  au.preload = 'metadata';
  const back = () => { try { au.currentTime = t; } catch (e) { /* not seekable yet */ } if (playing) au.play().catch(() => {}); };
  au.addEventListener('loadedmetadata', back, {once: true});
  au.src = au.dataset[side];                                         // one player: the other clip takes over at the same moment
  el.querySelectorAll('.abbtn').forEach(b => { const on = b.dataset.abside === side; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
  const w = el.querySelector('.abnow'); if (w) w.textContent = side === 'a' ? 'A · now' : 'B · with the fix';
}
function toggleHelp(force) {
  S.rv.help = force != null ? force : !S.rv.help;
  const h = document.getElementById('rvhelp'), b = document.getElementById('rvhelpbtn');
  if (h) {
    const was = h.contains(document.activeElement);
    h.hidden = !S.rv.help;
    // A floating panel (CSS #rvhelp), so it is in view wherever the list is scrolled to. The keyboard goes into it, and back to where it was when it closes.
    if (S.rv.help) { S.rv.helpFrom = document.activeElement; h.tabIndex = -1; h.focus({preventScroll: true}); }
    else if (was) { const back = S.rv.helpFrom && document.contains(S.rv.helpFrom) && S.rv.helpFrom !== document.body ? S.rv.helpFrom : b; S.rv.helpFrom = null; if (back) back.focus({preventScroll: true}); }
  }
  if (b) b.setAttribute('aria-expanded', !!S.rv.help);
}
const typing = t => !!t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName));
document.addEventListener('keydown', e => {
  if (S.view !== 'review' || !S.review || S.review.damaged || !S.rv || S.rv.modal) return;
  if (e.key === 'Escape' && S.rv.help && e.target.closest && e.target.closest('#rvhelp')) { e.preventDefault(); toggleHelp(false); return; }     // also from the box inside the panel
  if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) {
    if (e.key === 'Escape' && typing(e.target) && e.target.matches('input[data-note]')) { const c = e.target.closest('.item'); e.target.blur(); if (c) c.focus({preventScroll: true}); }
    return;
  }
  const k = e.key;
  const interactive = e.target.closest && e.target.closest('button, a, summary, audio, [role=button]');
  if (k === ' ') { if (interactive) return; e.preventDefault(); togglePlay(); return; }
  if ((k === 'ArrowDown' || k === 'ArrowUp') && e.target.tagName === 'AUDIO') return;
  if (k === 'j' || k === 'ArrowDown') { e.preventDefault(); move(1); }
  else if (k === 'k' || k === 'ArrowUp') { e.preventDefault(); move(-1); }
  else if (k === ']') { e.preventDefault(); jumpOpen(1); }
  else if (k === '[') { e.preventDefault(); jumpOpen(-1); }
  else if (k === 'a') { e.preventDefault(); decideCur('approve'); }
  else if (k === 's') { e.preventDefault(); decideCur('skip'); }
  else if (k === 'c') { e.preventDefault(); decideCur('change'); }
  else if (k === 'b') { e.preventDefault(); abSwitch(curEl(), (curEl() && curEl().querySelector('audio') || {dataset: {}}).dataset.side === 'a' ? 'b' : 'a'); }
  else if (k === '?') { e.preventDefault(); toggleHelp(); }
  else if (k === 'Escape' && S.rv.help) toggleHelp(false);
});

// ---------------------------------------------------------------- mouse and touch (delegated; the page's policy allows no inline handlers)
document.addEventListener('click', e => {
  if (S.view !== 'review' || !S.review || e.target.closest('.wa')) return;
  const item = e.target.closest('#rvlist .item');
  if (item && item.dataset.id !== S.rv.cur) setCur(item.dataset.id, false);
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.did) {
    const note = item && item.querySelector('input[data-note]');
    decideOne(b.dataset.did, b.dataset.d, note ? note.value : undefined);
  } else if (b.dataset.abside) { abSwitch(b.closest('.item'), b.dataset.abside); }
  else if (b.id === 'alllow') approveAllLow().catch(err => fail(err, 'Could not list them'));
  else if (b.id === 'rvhelpbtn') toggleHelp();
  else if (b.id === 'rvhelpclose') toggleHelp(false);
  else if (b.dataset.more) {                                   // the next page of a group of a long list: the keyboard goes to its first new card
    const first = showMore(b.dataset.more);
    if (first) { setCur(first, true); announce('Showing more findings.'); }
  } else if (b.dataset.filter) {
    S.rv.filter.status = b.dataset.filter; saveFilter(); rerenderList();
  } else if (b.dataset.like) { /* handled by ovBind */ }
});
document.addEventListener('change', e => {
  if (S.view !== 'review' || !S.review) return;
  const t = e.target;
  if (t.id === 'rvtool') { S.rv.filter.tool = t.value; saveFilter(); rerenderList(); }
  else if (t.id === 'rvadvance') { S.rv.advance = t.checked; LS.set('hx.advance', t.checked); }
  else if (t.id === 'fkey') S.rv.fkey = t.value;
  else if (t.dataset && t.dataset.answer) updateApply();
  else if (t.id === 'prot') S.rv.prot = t.checked;
  else if (t.matches && t.matches('input[data-note]')) {
    const e0 = entryOf(t.dataset.note);
    if (e0 && e0.decision) decideOne(t.dataset.note, e0.decision, t.value);
  }
});
document.addEventListener('input', e => {
  if (S.view !== 'review' || !S.rv) return;
  if (e.target.id === 'fkey') S.rv.fkey = e.target.value;
  else if (e.target.dataset && e.target.dataset.answer) { S.rv.answers[e.target.dataset.answer] = e.target.value; LS.set('hx.answers.' + S.review.dir, S.rv.answers); }
});
document.addEventListener('focusout', () => { setTimeout(() => { if (S.view === 'review' && S.rv && S.rv.applyStale) updateApply(); }, 0); });
document.addEventListener('toggle', e => {
  if (e.target.id === 'byhand' && S.rv) S.rv.handOpen = e.target.open;
  const k = S.rv && S.rv.lazy && e.target.open && (e.target.id === 'byhand' ? 'hand' : e.target.matches && e.target.matches('details.batch') ? 'batch' : '');
  if (k && S.rv.groups[k] && S.rv.groups[k].built === 0) showMore(k);        // a long list: the cards of a box are built when it is opened
}, true);
// one clip at a time; a clip counts as heard once it has been playing for most of a second
document.addEventListener('playing', e => {
  const a = e.target; if (!a.matches || !a.matches('audio[data-fid]')) return;
  pauseAll(a);
  clearTimeout(a._ht);
  a._ht = setTimeout(() => { if (!a.paused) markHeard(a.dataset.fid, a.dataset.side); }, 800);
}, true);
document.addEventListener('pause', e => { if (e.target._ht) clearTimeout(e.target._ht); }, true);

function rerenderList() {
  const l = document.getElementById('rvlist'); if (!l) return;
  const keepCur = S.rv.cur;
  S.rv.built = {};                                    // a new filter starts the list again: the first page, and the card you are on
  l.innerHTML = listHTML();
  watchMore();
  document.querySelectorAll('.chip').forEach(c => { const on = c.dataset.filter === S.rv.filter.status; c.classList.toggle('on', on); c.setAttribute('aria-pressed', on); });
  const el = keepCur && document.getElementById('f-' + keepCur); if (el) el.classList.add('cur');
  updateBar();
}

// ---------------------------------------------------------------- the whole screen (only when it is opened)
function reviewView() {
  const R = S.review;
  const head = `<h1>Review: ${esc(R.name)}</h1>`;
  if (R.damaged) return head + damageHTML(R);
  rvState().built = {};                                // the screen is drawn again: a long list starts with its first page
  const stale = R.stale && R.stale.newer, missing = R.stale && R.stale.missing;
  const top = (stale ? `<div class="banner bad"><b>This ${NOUN_[R.kind] || 'song'} was saved after the scan: re-scan before applying.</b> The findings may no longer match it.
      ${R.can_rescan ? `<button type="button" class="primary" data-rescan="${esc(R.dir)}" data-kind="${esc(R.kind)}">Re-scan</button>` : ''}</div>` : '')
    + (missing ? `<div class="banner bad"><b>The original is not where the scan found it:</b> ${esc(R.source)}. You can look through the review, but applying needs it back.</div>` : '')
    + (R.broken.length ? '<div class="warn"><b>Checks that did NOT run</b> (no findings there means nothing):<br>' + R.broken.map(esc).join('<br>') + '</div>' : '')
    + (R.prefs.length ? '<div class="prefs">' + R.prefs.map(esc).join('<br>') + '</div>' : '');
  const handed = R.handoff && R.handoff.length ? ` <span class="note">Already made: ${R.handoff.map(esc).join(', ')}.</span><button type="button" data-reveal="${esc(R.dir)}/handoff">Show</button>` : '';
  return `${head}
  <p class="sub">Nothing has been changed. Listen, decide each item, then apply only what you approved. Press <kbd>?</kbd> for the keyboard shortcuts.</p>
  <div class="row">${R.can_rescan ? `<button type="button" data-rescan="${esc(R.dir)}" data-kind="${esc(R.kind)}" title="Run the scan again on the song as it is now${R.kind === 'als' ? ': your decisions are kept' : ''}">Re-scan</button>` : ''}
    <button type="button" data-handoff="${esc(R.dir)}" title="A checklist of the by-hand items, with a marker at each spot">Make the handoff list</button>${handed}</div>${top}${abLiveCard(R)}
  ${barHTML()}
  <div id="rvlist">${listHTML()}</div>
  <div id="rvapply">${applyHTML(R)}</div><div id="rvhist">${historyHTML(R)}</div>`;
}
function rvMounted() {                      // after the screen is in the page: the card you were on, in view
  if (!S.review || S.review.damaged || !S.rv) return;
  watchMore();
  const el = S.rv.cur && document.getElementById('f-' + S.rv.cur);
  if (el) el.classList.add('cur');
  if (el && S.rvScroll) setTimeout(() => el.scrollIntoView({block: 'center'}), 60);          // after the page has put itself at the top
  S.rvScroll = false;
}
function rvToggleHistory() {
  const box = document.getElementById('rvhist'); if (!box) return;
  box.innerHTML = historyHTML(S.review);
}

ovBind({
  amount: (id, v) => setAmount(id, v),
  decideLike: (id, d) => decideLike(id, d).catch(err => fail(err, 'Could not list them')),
  batch: (ids, d, note) => batchDecide(ids, d, note, 'batch'),
  note: (id, text, at) => addNote(id, text, at),
});

Object.assign(window, {reviewView, rvMounted, rvToggleHistory, rvAnswers: () => answersGiven().map(g => g.text)});
})();
