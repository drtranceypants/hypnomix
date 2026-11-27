// The Store tab (hypnomix/app/store.py, hypnomix/store/): free and open-source plug-ins, instruments, drum kits and
// sample packs. Search and filter, read the licence and the source, then Install / Update / Uninstall with progress.
// macOS only for now (on another system the tab says so). A download nobody can verify is installed only after a second,
// plain-words confirmation (unverified: true); a running install can be cancelled.
// Uses the page's own helpers: $, esc, get, post, go, S.
const ST = {data: null, q: '', kind: '', fmt: '', lic: '', mine: false, mpe: false, open: {}, updates: {}, checking: false, timer: null};

(function () {
  const st = document.createElement('style');
  st.textContent = `main:has(.store){max-width:1120px}
  .store .filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 6px}
  .store .filters input[type=search]{flex:2 1 240px;font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
  .store .filters select{flex:0 1 160px;min-width:120px}
  .store .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;margin-top:12px}
  .store .it{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;display:flex;flex-direction:column;gap:6px;min-width:0}
  .store .it.inst{border-color:var(--ok)}
  .store .it h3{margin:0;font-size:1.05rem;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
  .store .it h3 small{color:var(--mute);font-weight:400;font-size:.85rem}
  .store .tags{display:flex;gap:6px;flex-wrap:wrap}.store .tag.oss{border-color:var(--ok);color:var(--ok)}.store .tag.free{border-color:var(--med);color:var(--med)}
  .store .tag.ok{background:var(--ok);border-color:var(--ok);color:#fff}.store .tag.mpe{border-color:var(--accent);color:var(--accent);font-weight:600}.store .tag.note{border-style:dashed;color:var(--mute)}
  .store .acts{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:auto;padding-top:6px}
  .store .prog{height:6px;border-radius:3px;background:var(--line);overflow:hidden}.store .prog i{display:block;height:100%;background:var(--accent);transition:width .3s}
  .store .msg{font-size:.88rem;border-left:3px solid var(--info);padding:4px 10px;margin:2px 0;overflow-wrap:anywhere}
  .store .msg.err{border-color:var(--hi)}.store .msg.good{border-color:var(--ok)}
  .store dl{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;margin:4px 0 0;font-size:.88rem}.store dt{color:var(--mute)}.store dd{margin:0;overflow-wrap:anywhere}
  .store code{font-size:.8rem}.store .count{color:var(--mute);font-size:.9rem}`;
  document.head.appendChild(st);
})();

const stRunning = () => ST.data && Object.values(ST.data.jobs || {}).some(j => !j.ended);
const stVerify = {pinned: 'Checked against a fingerprint (sha256) kept in the catalogue.',
  github: 'Checked against the fingerprint (sha256) GitHub publishes for the file. If GitHub gives none, the store says so and asks before installing.',
  none: 'NOT VERIFIED: the publisher gives no fingerprint (sha256) for this download, so the store cannot check it. It asks you to confirm before installing.'};
const stMB = n => n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : (n / 1e6).toFixed(n < 1e7 ? 1 : 0) + ' MB';

async function storeLoad() { ST.data = await get('/api/store/state'); return ST.data; }

async function storeView() {
  const D = await storeLoad();
  const opt = (v, cur, label) => `<option value="${esc(v)}" ${v === cur ? 'selected' : ''}>${esc(label || v)}</option>`;
  if (D.supported === false) return `<div class="store"><h1>Store</h1><p class="sub">Free plug-ins, synths, instruments, drum kits and sample packs.</p>
    <div class="warn">${esc(D.platform_note || 'The Store works on macOS only for now.')}</div>
    <p class="note"><a href="#" data-wiki="store">How the store works</a></p></div>`;
  const test = D.targets.test_root ? `<div class="warn">Test mode (HYPNOMIX_STORE_ROOT): everything installs under <code>${esc(D.targets.test_root)}</code>, not into your Library.</div>` : '';
  return `<div class="store"><h1>Store</h1>
  <p class="sub">Free plug-ins, synths, instruments, drum kits and sample packs, downloaded from their publishers. Nothing downloaded is ever run: when a publisher only ships an installer, it opens for you to read and run.</p>${test}
  <div class="filters">
    <input type="search" id="stq" placeholder="Search: reverb, piano, tape, drums…" value="${esc(ST.q)}" aria-label="Search the store">
    <select id="stkind" aria-label="Kind">${opt('', ST.kind, 'Every kind')}${D.kinds.map(k => opt(k, ST.kind, k[0].toUpperCase() + k.slice(1))).join('')}</select>
    <select id="stfmt" aria-label="Format">${opt('', ST.fmt, 'Any format')}${D.formats.map(f => opt(f, ST.fmt)).join('')}</select>
    <select id="stlic" aria-label="Licence">${opt('', ST.lic, 'Any licence')}${opt('open', ST.lic, 'Open source')}${opt('freeware', ST.lic, 'Freeware (not open source)')}${D.licences.map(l => opt(l, ST.lic)).join('')}</select>
    <label class="note" style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" id="stmine" ${ST.mine ? 'checked' : ''}> Installed</label>
    <label class="note" style="display:flex;gap:6px;align-items:center;margin:0" title="Only items whose maker documents MPE: per-note pitch bend, pressure and slide from controllers that send them"><input type="checkbox" id="stmpe" ${ST.mpe ? 'checked' : ''}> MPE</label>
    <button id="stupd" ${ST.checking ? 'disabled' : ''}>${ST.checking ? 'Checking…' : 'Check for updates'}</button>
  </div>
  <p class="note">The Store works on macOS only for now. Plug-ins go into <code>${esc(D.targets.plugins)}</code>, sounds into <code>${esc(D.targets.library)}</code>. SFZ instruments and drum kits play in <b>sfizz</b> (in this store). <a href="#" data-wiki="store">How the store works</a></p>
  <div id="stlist">${storeList()}</div>
  <h2>Not in the store, and why</h2><ul class="note">${(D.left_out || []).map(x => `<li><b>${esc(x.name)}</b>: ${esc(x.why)}</li>`).join('')}</ul>
  <p class="note">Catalogue ${esc(D.version)}. Licences are the publishers'; read them on their pages before releasing music made with sample content (CC-BY asks for a credit).</p></div>`;
}

function storeList() {
  const D = ST.data, words = ST.q.toLowerCase().split(/\s+/).filter(Boolean);
  const hits = D.items.filter(it => {
    const hay = [it.name, it.vendor, it.about, it.kind, it.formats.join(' '), it.licence].join(' ').toLowerCase();
    if (words.some(w => !hay.includes(w))) return false;
    if (ST.kind && it.kind !== ST.kind) return false;
    if (ST.fmt && !it.formats.includes(ST.fmt)) return false;
    if (ST.lic === 'open' && !it.open_source || ST.lic === 'freeware' && it.open_source) return false;
    if (ST.lic && !['open', 'freeware'].includes(ST.lic) && it.licence !== ST.lic) return false;
    if (ST.mine && !(D.status[it.id] || {}).installed) return false;
    if (ST.mpe && !it.mpe) return false;
    return true;
  });
  return `<p class="count">${hits.length} of ${D.items.length}</p><div class="grid">${hits.map(storeCard).join('') || '<p class="note">Nothing matches.</p>'}</div>`;
}

function storeCard(it) {
  const D = ST.data, s = D.status[it.id] || {}, j = (D.jobs || {})[it.id], u = ST.updates[it.id] || {};
  const busy = j && !j.ended, any = stRunning();
  const arm = it.macos_arm64 === true ? 'Apple Silicon native' : it.macos_arm64 === false ? 'Intel only (Rosetta)' : 'Apple Silicon: not checked';
  const measured = s.archs && Object.values(s.archs).length ? [...new Set(Object.values(s.archs).flat())].join(' + ') : '';
  const src = it.source.type === 'github' ? `<a href="https://github.com/${esc(it.source.repo)}/releases" target="_blank" rel="noopener">GitHub releases: ${esc(it.source.repo)}</a>`
    : it.source.type === 'url' ? `<a href="${esc(it.source.url)}" target="_blank" rel="noopener">${esc(decodeURIComponent(it.source.url.split('/').pop()))}</a> (version ${esc(it.source.version)})`
    : `the publisher's page (${esc(it.source.note || '')})`;
  let state = '';
  if (busy) {
    const pct = j.total ? Math.round(100 * j.got / j.total) : 0;
    const what = {download: j.total ? `Downloading ${stMB(j.got)} of ${stMB(j.total)}` : `Downloading ${stMB(j.got || 0)}`, unpack: 'Unpacking (nothing is run)',
      install: 'Copying into place', rescan: 'Asking the DAW engine to rescan', starting: 'Starting'}[j.phase] || j.phase;
    state = `<div class="note"><span class="spin"></span>${esc(j.action === 'uninstall' ? 'Removing' : what)}</div>${j.phase === 'download' ? `<div class="prog"><i style="width:${pct}%"></i></div>` : ''}`
      + (j.action === 'install' ? `<div class="acts"><button data-stcancel="${esc(it.id)}" ${j.cancel ? 'disabled' : ''}>${j.cancel ? 'Cancelling…' : 'Cancel'}</button></div>` : '');
  } else if (j && j.error) {
    const ok = j.unverified_ok ? ' data-unverified="1"' : '';
    state = `<div class="msg err">${esc(j.error)} <button type="button" data-report="banner">Report this</button></div>`
      + (j.confirm ? `<div class="acts"><button data-stinst="${esc(it.id)}" data-replace="1"${ok}>Replace them</button><button data-stforget="${esc(it.id)}">Leave them</button></div>` : '')
      + (j.unverified ? `<div class="acts"><button data-stinst="${esc(it.id)}" data-unverified="1">Install anyway (not verified)</button><button data-stforget="${esc(it.id)}">Don't install</button></div>` : '');
  } else if (j && j.result) {
    const r = j.result, e = r.entry;
    if (j.action === 'uninstall') state = `<div class="msg good">Removed ${r.removed.length} item(s).</div>`;
    else if (e && e.method === 'pkg') state = `<div class="msg">${esc(e.note)}</div>`;
    else if (e) state = `<div class="msg good">Installed ${e.paths.length} ${it.method === 'content' ? 'folder' : 'plug-in'}${e.paths.length === 1 ? '' : 's'}${e.sha256_checked ? ', sha256 checked' : ', NOT verified (you confirmed)'}.${e.replaced_kept_in && e.replaced_kept_in.length ? ' What was there before is in the store\'s trash folder.' : ''}</div>`
      + (r.rescan ? `<div class="msg">${esc(r.rescan.message)}</div>` : '');
  }
  const acts = [];
  if (it.method === 'page') acts.push(`<a class="btn" href="${esc(it.homepage)}" target="_blank" rel="noopener">Get it from ${esc(it.vendor)}</a>`);
  else if (!s.installed) acts.push(`<button class="primary" data-stinst="${esc(it.id)}" ${any ? 'disabled' : ''}>Install</button>`);
  else {
    if (u.update) acts.push(`<button class="primary" data-stinst="${esc(it.id)}" ${any ? 'disabled' : ''}>Update to ${esc(u.latest)}</button>`);
    if (s.method === 'pkg' && !s.installer_missing) acts.push(`<button data-stpkg="${esc(it.id)}">Show installer</button>`);
    acts.push(`<button data-stun="${esc(it.id)}" ${any ? 'disabled' : ''}>${s.method === 'pkg' ? 'Forget' : 'Uninstall'}</button>`);
  }
  acts.push(`<button data-stmore="${esc(it.id)}" aria-expanded="${!!ST.open[it.id]}">${ST.open[it.id] ? 'Less' : 'Details'}</button>`);
  const inst = s.installed ? `<span class="tag ok">${s.method === 'pkg' ? 'installer kept' : 'installed'} ${esc(s.version || '')}</span>` : '';
  const more = ST.open[it.id] ? `<dl><dt>Maker</dt><dd>${esc(it.vendor)}</dd>
    <dt>Licence</dt><dd>${esc(it.licence)}${it.open_source ? ' (open source)' : ' (free to use, not open source)'}</dd>
    ${it.credit ? `<dt>Credit</dt><dd>${esc(it.credit)}</dd>` : ''}
    ${it.mpe ? `<dt>MPE</dt><dd>${esc(it.mpe_note || 'The maker documents MPE.')}</dd>` : ''}
    ${it.note ? `<dt>Note</dt><dd>${esc(it.note)}</dd>` : ''}
    <dt>Check</dt><dd>${esc(stVerify[it.verification] || '')}</dd>
    ${it.method === 'pkg' ? '<dt>Installer</dt><dd>A package from the publisher: you read and run it yourself in Apple\'s Installer. It installs outside your home folder and asks for your password.</dd>' : ''}
    <dt>Formats</dt><dd>${esc(it.formats.join(', '))}</dd><dt>Mac</dt><dd>${esc(arm)}${measured ? ` · installed binary: ${esc(measured)}` : ''}</dd>
    <dt>Home</dt><dd><a href="${esc(it.homepage)}" target="_blank" rel="noopener">${esc(it.homepage)}</a></dd><dt>Source</dt><dd>${src}</dd>
    ${it.size ? `<dt>Size</dt><dd>about ${esc(it.size)}</dd>` : ''}
    ${s.installed && s.paths && s.paths.length ? `<dt>Installed</dt><dd>${s.paths.map(p => `<code>${esc(p)}</code> <a href="#" data-streveal="${esc(p)}">show</a>`).join('<br>')}</dd>` : ''}
    ${s.missing && s.missing.length ? `<dt>Missing</dt><dd>${s.missing.map(p => `<code>${esc(p)}</code>`).join('<br>')} (removed outside the store)</dd>` : ''}
    ${s.installer_missing ? '<dt>Installer</dt><dd>The kept installer was cleared to save disk space. Install the item again to get it back.</dd>' : ''}
    ${s.sfz_count ? `<dt>SFZ files</dt><dd>${s.sfz_count}: load one in sfizz</dd>` : ''}
    ${u.error ? `<dt>Updates</dt><dd>${esc(u.error)}</dd>` : u.latest ? `<dt>Newest</dt><dd>${esc(u.latest)}</dd>` : ''}</dl>` : '';
  return `<div class="it${s.installed ? ' inst' : ''}" id="st-${esc(it.id)}"><h3>${esc(it.name)} <small>${esc(it.vendor)}</small></h3>
    <div class="tags"><span class="tag">${esc(it.kind)}</span><span class="tag ${it.open_source ? 'oss' : 'free'}">${it.open_source ? 'open source' : 'freeware'} · ${esc(it.licence)}</span>
      <span class="tag">${esc(it.formats.join(' · '))}</span>${it.mpe ? '<span class="tag mpe" title="The maker documents MPE (per-note pitch bend, pressure and slide). Open Details to see how it is switched on.">MPE</span>' : ''}${it.note ? '<span class="tag note" title="Read the note in Details before installing">note</span>' : ''}${it.verification === 'none' ? '<span class="tag free" title="No fingerprint to check this download against">not verified</span>' : ''}${inst}</div>
    <div>${esc(it.about)}</div>${more}${state}<div class="acts">${acts.join('')}</div></div>`;
}

function storeDraw() { const l = document.getElementById('stlist'); if (l && ST.data) l.innerHTML = storeList(); }

async function storePoll() {
  if (S.view !== 'store') { ST.timer = null; return; }
  try { const r = await get('/api/store/jobs'); ST.data.jobs = r.jobs; ST.data.status = r.status; } catch (e) { /* the app restarted */ }
  storeDraw();
  ST.timer = stRunning() ? setTimeout(storePoll, 700) : null;
}
function storeWatch() { if (!ST.timer) ST.timer = setTimeout(storePoll, 300); }

function storeAfter() {
  const q = document.getElementById('stq');
  if (!q) return;
  q.addEventListener('input', () => { ST.q = q.value; storeDraw(); });
  for (const [id, k] of [['stkind', 'kind'], ['stfmt', 'fmt'], ['stlic', 'lic']]) document.getElementById(id).addEventListener('change', e => { ST[k] = e.target.value; storeDraw(); });
  document.getElementById('stmine').addEventListener('change', e => { ST.mine = e.target.checked; storeDraw(); });
  document.getElementById('stmpe').addEventListener('change', e => { ST.mpe = e.target.checked; storeDraw(); });
  if (stRunning()) storeWatch();
}

document.addEventListener('click', async e => {
  const b = e.target.closest('[data-stinst],[data-stun],[data-stmore],[data-stpkg],[data-streveal],[data-stforget],[data-stcancel],#stupd');
  if (!b || !document.querySelector('.store')) return;
  e.preventDefault();
  const d = b.dataset;
  try {
    if (d.stmore) { ST.open[d.stmore] = !ST.open[d.stmore]; storeDraw(); }
    else if (d.stinst) {
      if (d.replace && !confirm('Replace what is already there? The old copies are moved to the store\'s trash folder, not deleted now; Disk care clears that trash after 60 days.')) return;
      if (d.unverified && !confirm('NOT VERIFIED.\n\nThis download has no fingerprint from its publisher to be checked against, so HypnoMix cannot tell whether the file is the one the publisher released. If it is an installer package, it will run with administrator rights once you click through Apple\'s Installer.\n\nInstall it anyway?')) return;
      await post('/api/store/install', {id: d.stinst, replace: !!d.replace, unverified: !!d.unverified}); await storePoll(); storeWatch();
    } else if (d.stcancel) { await post('/api/store/cancel', {id: d.stcancel}); await storePoll();
    } else if (d.stun) {
      const s = ST.data.status[d.stun] || {};
      const msg = s.method === 'pkg' ? 'Forget this item? The kept installer is deleted. What the publisher\'s installer put on your Mac stays: remove that with their instructions.'
        : `Uninstall? This removes exactly what the store installed:\n\n${(s.paths || []).join('\n')}`;
      if (!confirm(msg)) return;
      await post('/api/store/uninstall', {id: d.stun}); await storePoll(); storeWatch();
    } else if (d.stpkg) { const r = await post('/api/store/open-installer', {id: d.stpkg}); if (!r.opened) alert('Could not open it here: find it in the Details.'); }
    else if (d.streveal) await post('/api/store/reveal', {path: d.streveal});
    else if (d.stforget) { await post('/api/store/forget', {id: d.stforget}); delete ST.data.jobs[d.stforget]; storeDraw(); }
    else if (b.id === 'stupd') {
      ST.checking = true; b.disabled = true; b.textContent = 'Checking…';
      try { ST.updates = await get('/api/store/updates'); } finally { ST.checking = false; b.disabled = false; b.textContent = 'Check for updates'; }
      const n = Object.values(ST.updates).filter(u => u.update).length;
      b.textContent = n ? `${n} update${n === 1 ? '' : 's'}` : 'Up to date';
      storeDraw();
    }
  } catch (err) { alert(err.message); }
});

// the Store tab sits after Tools (added here, so the page's nav line stays as it is)
(function () {
  const b = document.createElement('button');
  b.className = 'tab'; b.dataset.view = 'store'; b.textContent = 'Store';
  b.title = 'Free and open-source plug-ins, instruments, drum kits and sample packs';
  const tools = document.querySelector('button.tab[data-view="tools"]');
  if (tools) tools.after(b);
})();

// /#store opens the Store (the DAW view's browser links here)
if (location.hash === '#store') go('store');
window.addEventListener('hashchange', () => { if (location.hash === '#store') go('store'); });
