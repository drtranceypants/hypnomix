// The Wiki tab (served at /wiki.js; uses the page's own helpers: $, esc, get, S, render).
// One set of articles for the app and the website (hypnomix/app/wiki/articles/): the app shows the newest of
// this computer's files and the website's copy; Edit and Publish change both.
const W = {index: null, id: null, art: null, q: ''};
try { W.id = localStorage.getItem('hypnomix.wiki') || null; } catch (e) {}

(function () {   // the tab's own look, on top of the page's styles
  const st = document.createElement('style');
  st.textContent = `main:has(.wiki){max-width:1180px}
  .wiki{display:grid;grid-template-columns:250px 1fr;gap:28px;align-items:start}
  .wiki aside{position:sticky;top:64px;max-height:calc(100vh - 84px);overflow:auto;padding-right:6px}
  .wiki aside input{width:100%;font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink)}
  .wiki aside h4{margin:16px 0 4px;font-size:.74rem;letter-spacing:.12em;text-transform:uppercase;color:var(--mute)}
  .wiki aside a{display:block;padding:4px 8px;border-radius:6px;color:var(--ink);text-decoration:none;font-size:.93rem;cursor:pointer}
  .wiki aside a:hover{background:var(--card)}.wiki aside a.on{background:var(--card);font-weight:600;box-shadow:inset 2px 0 0 var(--accent)}
  .wiki aside a small{color:var(--mute);margin-right:6px;font-variant-numeric:tabular-nums}
  .wiki aside .hit{display:block;color:var(--mute);font-size:.8rem;font-weight:400;line-height:1.3;margin-top:2px}
  .wiki aside .none{color:var(--mute);font-size:.9rem;padding:8px}
  .wa{min-width:0;line-height:1.6}.wa .no{color:var(--accent);font-size:.78rem;letter-spacing:.14em;text-transform:uppercase}
  .wa h1{font-size:1.9rem;margin:2px 0 4px}.wa > .sub{font-style:italic}
  .wa h3{font-size:1.12rem;margin:26px 0 8px;scroll-margin-top:64px}.wa h4{scroll-margin-top:64px}.wa h4{margin:18px 0 6px}
  .wa img,.wa video{max-width:100%;height:auto;border-radius:8px;border:1px solid var(--line);background:var(--card)}
  .wa figure{margin:16px 0}.wa figcaption{color:var(--mute);font-size:.88rem;margin-top:6px}
  .wa .pair{display:grid;grid-template-columns:1fr 1fr;gap:14px}.wa .pair figure{margin:0}
  .wa ol.steps li,.wa ul.steps li{margin:6px 0}.wa a{color:var(--accent)}
  .wa code{background:var(--card);border:1px solid var(--line);border-radius:4px;padding:0 4px;font-size:.9em}
  .wa pre{background:#1d1b18;color:#ece8df;border-radius:8px;padding:12px 14px;overflow-x:auto;font-size:.84rem;line-height:1.5;position:relative;white-space:pre;max-height:none}
  .wa .term pre{padding-top:34px}
  .wa pre code{background:none;border:0;padding:0;color:inherit}.wa pre .c{color:#a09a8e}.wa pre .p{color:#e9b4b0;user-select:none}
  .wa .term{position:relative;margin:12px 0}.wa .term[data-label]::before{content:attr(data-label);position:absolute;top:-9px;left:12px;
    font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;background:var(--bg);color:var(--mute);padding:0 6px;border-radius:4px;z-index:1}
  .wa .term .wcopy{position:absolute;top:8px;right:8px;z-index:2;font-size:.78rem;padding:3px 9px;background:#34322d;color:#ece8df;border-color:#4a4740}
  .wa table{border-collapse:collapse;width:100%;margin:12px 0}.wa td,.wa th{border-bottom:1px solid var(--line);padding:7px 8px;vertical-align:top;text-align:left}
  .wa details{border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:8px 0;background:var(--card)}
  .wa summary{cursor:pointer;font-weight:600}.wa dt{margin-top:10px}.wa dt code{font-weight:600}.wa dd{margin:2px 0 0 18px;color:var(--ink)}
  .wa .extra{font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);margin-left:6px}
  .wa .flow{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:18px 0}
  .wa .flow .step{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:9px 12px;text-align:center;min-width:100px}
  .wa .flow .step b{display:block;font-size:.74rem;letter-spacing:.16em;text-transform:uppercase}
  .wa .flow .step span{font:500 .76rem ui-monospace,Menlo,monospace;color:var(--mute)}.wa .flow .arrow{color:var(--accent);font-size:1.2rem}
  .wa ol.steps{list-style:none;counter-reset:s;padding:0}.wa ol.steps>li{counter-increment:s;position:relative;padding:10px 12px 10px 48px;
    margin:0 0 10px;background:var(--card);border:1px solid var(--line);border-radius:8px}
  .wa ol.steps>li::before{content:counter(s);position:absolute;left:12px;top:10px;width:26px;height:26px;border-radius:50%;display:grid;
    place-items:center;border:1.5px solid var(--accent);color:var(--accent);font-weight:600;font-size:.85rem}
  .wa ul.steps{padding:0}.wa ul.steps>li{padding:10px 12px;margin:0 0 10px;background:var(--card);border:1px solid var(--line);border-radius:8px}
  .wa .note-box,.wa .warn-box{margin:16px 0;padding:10px 14px;border:1px solid var(--line);border-left:4px solid var(--info);border-radius:6px;background:var(--card)}
  .wa .warn-box{border-left-color:var(--med)}.wa .lead{font-size:1.08rem}.wa .tablewrap{overflow-x:auto}
  .wa h3.sub-h{font-size:.82rem;letter-spacing:.18em;text-transform:uppercase;color:var(--mute);margin-top:30px}
  .wa .groups{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
  .wa .group{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.wa .group h3{margin-top:0}
  .wa .group .tagline{color:var(--mute);font-style:italic;margin-top:-4px}
  .wa .group dl{display:grid;grid-template-columns:auto 1fr;gap:6px 10px;align-items:baseline;margin:0}.wa .group dt{margin:0}.wa .group dd{margin:0}
  .wa pre .o{color:#8fc7a4;font-weight:600}
  .wa .demo-loops{display:grid;grid-template-columns:1fr 1fr;gap:16px}.wa .shots{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
  .wa .demo-loops figure,.wa .shots figure,.wa .devdemo figure{margin:0}.wa .devdemo{display:grid;gap:16px}
  .wa .devpanel{max-width:430px}.wa .frame-paper img,.wa .frame-paper video{display:block;width:100%}
  .wa .demo-loops figcaption b,.wa .shots figcaption b{display:block;font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
  .wa .demo-cap{color:var(--mute);font-size:.88rem}
  .wa .wnet{font-size:.78rem;color:var(--mute);margin-top:4px}.wa .wnet.off{color:var(--med);font-weight:600}
  .wa .foot+.foot{margin-top:6px;border-top:0;padding-top:0}.wa .foot label{display:inline-flex;gap:6px;align-items:center}
  .wa .foot{margin-top:36px;padding-top:12px;border-top:1px solid var(--line);color:var(--mute);font-size:.86rem;display:flex;gap:12px;flex-wrap:wrap}
  .wa .next{display:flex;justify-content:space-between;gap:12px;margin-top:28px}
  @media (max-width:760px){.wiki{grid-template-columns:1fr}.wiki aside{position:static;max-height:none}.wiki aside nav{max-height:230px;overflow:auto;border-bottom:1px solid var(--line)}.wa .pair,.wa .demo-loops,.wa .shots{grid-template-columns:1fr}}`;
  document.head.appendChild(st);
})();

async function wikiLoad() { W.index = await get('/api/wiki'); return W.index; }
function wikiAbout() {
  const a = W.index.about, when = a.updated ? new Date(a.updated * 1000).toLocaleDateString() : '';
  const src = a.source === 'the website' ? `the website's copy${when ? ', updated ' + when : ''}` : `this computer's copy${when ? ' (' + when + ')' : ''}`;
  return `<div class="foot"><span>Showing ${esc(src)}.</span>
    <label><input type="checkbox" id="wlive" ${a.live ? 'checked' : ''}> keep up to date from the website</label>
    ${a.checking ? '<span><span class="spin"></span>checking the website…</span>' : a.error && a.live ? `<span>Could not reach the website's wiki just now${a.source === 'the website' ? ': showing the last copy from it' : ''}.</span>` : ''}</div>`;
}
function wikiBanner() {
  const a = W.index.about;
  if (!a.unpublished || !a.unpublished.length) return '';
  return `<div class="card" style="margin-bottom:14px"><b>${a.unpublished.length} wiki change(s) not published yet.</b>
    Publish puts them on the website and in everyone's app.<br><button class="primary" id="wpub">Publish</button>
    <span class="note">${a.unpublished.map(esc).slice(0, 4).join(', ')}${a.unpublished.length > 4 ? '…' : ''}</span></div>`;
}

function wikiMatches() {
  const q = W.q.trim().toLowerCase(), all = W.index.articles;
  if (!q) return all.map(a => ({a, hit: ''}));
  const words = q.split(/\s+/);
  return all.filter(a => words.every(w => (a.title + ' ' + a.sub + ' ' + a.text).toLowerCase().includes(w)))
    .map(a => { const t = a.text, i = t.toLowerCase().indexOf(words[0]);
      return {a, hit: i < 0 ? '' : (i > 30 ? '…' : '') + t.slice(Math.max(0, i - 30), i + 70) + '…'}; });
}

function wikiList() {
  const rows = wikiMatches();
  if (!rows.length) return '<div class="none">Nothing matches. Try fewer words.</div>';
  let out = '', group = null;
  for (const {a, hit} of rows) {
    if (a.group !== group) { group = a.group; out += `<h4>${esc(group)}</h4>`; }
    const n = a.no ? a.no.replace(/^lesson\s*/i, '') : '';
    out += `<a data-wart="${esc(a.id)}" class="${a.id === W.id ? 'on' : ''}">${n ? `<small>${esc(n)}</small>` : ''}${esc(a.title)}${hit ? `<span class="hit">${esc(hit)}</span>` : ''}</a>`;
  }
  return out;
}

async function wikiView() {
  await wikiLoad();
  const all = W.index.articles;
  if (!all.length) return `<h1>Wiki</h1><p class="sub">No articles yet. From the hypnomix folder run
    <code>python -m hypnomix.app.wiki_sync</code> to copy them from the website.</p>`;
  if (!W.id || !all.some(a => a.id === W.id)) W.id = all[0].id;
  W.art = await get('/api/wiki/article?id=' + encodeURIComponent(W.id));
  const a = W.art, i = all.findIndex(x => x.id === a.id), prev = all[i - 1], next = all[i + 1];
  return `<div class="wiki"><aside><input type="search" id="wq" placeholder="Search the wiki" value="${esc(W.q)}" aria-label="Search the wiki">
    <nav id="wlist">${wikiList()}</nav></aside>
    <article class="wa">${wikiBanner()}${a.no ? `<div class="no">${esc(a.no)}</div>` : ''}<h1>${esc(a.title)}${a.editable ? ` <button id="wedit" style="font-size:.8rem;vertical-align:middle">Edit</button>` : ''}</h1>
      ${a.sub ? `<p class="sub">${esc(a.sub)}</p>` : ''}${a.html}
      <div class="next">${prev ? `<button data-wart="${esc(prev.id)}">← ${esc(prev.title)}</button>` : '<span></span>'}
        ${next ? `<button data-wart="${esc(next.id)}">${esc(next.title)} →</button>` : ''}</div>
      <div class="foot"><span>On the website: <a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.url)}</a></span></div>
      ${wikiAbout()}</article></div>`;
}

function wikiVideos() {     // videos that stream from the website: say so, and what to do without a connection
  document.querySelectorAll('.wa video').forEach(v => {
    const src = v.getAttribute('src') || '';
    if (!/^https?:/.test(src)) return;
    const note = document.createElement('div');
    note.className = 'wnet';
    note.innerHTML = `Plays from the website. <a href="${esc(src)}" target="_blank" rel="noopener">Open it in your browser ↗</a>`;
    (v.closest('.frame-paper') || v).after(note);
    const off = () => { note.classList.add('off'); note.firstChild.textContent = 'Needs an internet connection: this video plays from the website. '; };
    if (!navigator.onLine) off();
    v.addEventListener('error', off);
  });
}

function wikiAfter() {
  wikiVideos();
  clearTimeout(W.recheck);
  if (W.index && W.index.about.checking) W.recheck = setTimeout(() => {
    if (S.view === 'wiki' && document.activeElement.id !== 'wq') render(); }, 2500);
  document.querySelectorAll('.wa .term pre').forEach(pre => {
    const b = document.createElement('button'); b.className = 'wcopy'; b.textContent = 'copy';
    b.onclick = () => { const t = [...pre.childNodes].filter(n => !(n.classList && n.classList.contains('p'))).map(n => n.textContent).join('');
      navigator.clipboard.writeText(t.replace(/^\s*\$\s?/gm, '')).then(() => { b.textContent = 'copied'; setTimeout(() => b.textContent = 'copy', 1200); }); };
    pre.parentNode.insertBefore(b, pre);
  });
}

function wikiOpen(id) {
  W.id = id; try { localStorage.setItem('hypnomix.wiki', id); } catch (e) {}
  if (S.view !== 'wiki') { go('wiki'); return; }
  render().then(() => window.scrollTo(0, 0));
}

document.addEventListener('click', e => {      // a link to a section of the same article
  const j = e.target.closest('a[data-jump]');
  if (!j) return;
  e.preventDefault();
  const el = document.getElementById(j.dataset.jump);
  if (el) el.scrollIntoView({block: 'start'});
});
document.addEventListener('click', e => {
  const t = e.target.closest('[data-wart],a[data-wiki]');
  if (!t) return;
  e.preventDefault();
  wikiOpen(t.dataset.wart || t.dataset.wiki);
});
document.addEventListener('click', async e => {
  const t = e.target;
  try {
    if (t.id === 'wedit') { await post('/api/wiki/edit', {id: W.id}); setTimeout(() => S.view === 'wiki' && render(), 4000); }
    else if (t.id === 'wpub') {
      const m = prompt('What changed? (a few words for the history)', ''); if (m === null) return;
      t.disabled = true; t.textContent = 'Publishing…';
      const r = await post('/api/wiki/publish', {message: m}); alert(r.done || 'Published.'); render();
    }
  } catch (err) { alert(err.message); render(); }
});
document.addEventListener('change', async e => {
  if (e.target.id === 'wlive') { await post('/api/wiki/settings', {live: e.target.checked}); render(); }
});
window.addEventListener('focus', () => { if (S.view === 'wiki' && document.activeElement.id !== 'wq') render(); });
document.addEventListener('input', e => {
  if (e.target.id !== 'wq') return;
  W.q = e.target.value;
  const l = $('#wlist'); if (l) l.innerHTML = wikiList();
});
document.addEventListener('keydown', e => {
  if (e.target.id === 'wq' && e.key === 'Enter') { const first = wikiMatches()[0]; if (first) wikiOpen(first.a.id); }
});
