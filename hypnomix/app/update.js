// Updates (hypnomix/app/update.py): a banner when a new version is out, and one-click install for the installed app.
// The version in the header checks on demand and switches the daily check on or off. Uses the page's get/post/esc.
(() => {
const css = `
#upd{background:var(--card);border:1px solid var(--accent);border-radius:12px;margin:14px auto 0;max-width:1100px;padding:12px 16px;display:none}
#upd.on{display:block}#upd .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}#upd .row b{margin-right:auto}
#upd button{border:0;border-radius:8px;padding:7px 13px;font:inherit;cursor:pointer}#upd .go{background:var(--accent);color:var(--accent-ink)}
#upd .later{background:transparent;color:var(--mute);border:1px solid var(--line)}#upd .small{color:var(--mute);font-size:.86rem}
#upd .bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin-top:8px}#upd .bar i{display:block;height:100%;background:var(--accent);width:0}
#upd pre{white-space:pre-wrap;font:inherit;font-size:.9rem;margin:8px 0 0;max-height:260px;overflow:auto}
#upd a,#updpop a{color:var(--accent)}#upd .err{color:var(--hi)}#hxver{background:none;border:0;color:var(--mute);font:inherit;font-size:.8rem;cursor:pointer;padding:4px 8px}
#hxver:hover{color:var(--accent)}
#updpop{position:absolute;right:12px;top:48px;z-index:20;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;
  box-shadow:0 10px 30px rgba(0,0,0,.18);width:300px;font-size:.92rem}#updpop label{display:flex;gap:8px;margin-top:8px}`;
const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

const box = document.createElement('div'); box.id = 'upd';
document.querySelector('header').after(box);
const ver = document.createElement('button'); ver.id = 'hxver'; ver.title = 'Check for updates';
const live = document.getElementById('live'); live.parentNode.insertBefore(ver, live);

let U = null, notes = false, poll = null, installing = false;
const mb = n => (n / 1e6).toFixed(0) + ' MB';

async function load(force) {
  try { U = force ? await post('/api/update/check', {}) : await get('/api/update/state'); } catch (e) { return; }
  ver.textContent = 'v' + U.current;
  draw();
}

function draw() {
  if (!U) return;
  const j = U.job || {};
  const show = U.newer && (!U.skipped || ['downloading', 'verifying', 'ready', 'installing'].includes(j.status));
  box.classList.toggle('on', !!show || installing);
  if (!show && !installing) return;
  let act = '';
  if (installing || j.status === 'installing') {
    act = `<span class="small">Installing hypnomix ${esc(U.latest)}… it closes and opens again by itself.</span>`;
  } else if (!U.kind) {
    act = `<span class="small">From a source install: <code>git pull &amp;&amp; uv pip install -e .</code></span><a href="${esc(U.page)}" target="_blank" rel="noopener">release notes</a><button class="later" data-upd="skip">Later</button>`;
  } else if (j.status === 'downloading' || j.status === 'verifying') {
    const pct = j.size ? Math.min(100, Math.round(100 * j.got / j.size)) : 0;
    act = `<span class="small">${j.status === 'verifying' ? 'Checking the download…' : `Downloading ${mb(j.got)} of ${mb(j.size)}…`}</span>`;
    act += `</div><div class="bar"><i style="width:${pct}%"></i>`;
  } else if (j.status === 'ready') {
    act = `<span class="small">Downloaded and checked.</span><button class="go" data-upd="install">Install and restart</button><button class="later" data-upd="skip">Later</button>`;
  } else if (U.one_click) {
    act = `<button class="go" data-upd="get">Update now${U.size ? ` (${mb(U.size)})` : ''}</button><button class="later" data-upd="skip">Later</button>`;
  } else if (U.no_full_download) {
    act = `<span class="small">This version has no full download yet, so this app stays as it is. It is not replaced by the Assistant app.</span>${U.page ? `<a href="${esc(U.page)}" target="_blank" rel="noopener">release notes</a>` : ''}<button class="later" data-upd="skip">Later</button>`;
  } else {
    act = `<a href="https://hypnomix.bradfieldenterprises.org/download/" target="_blank" rel="noopener">Download it</a><button class="later" data-upd="skip">Later</button>`;
  }
  box.innerHTML = `<div class="row"><b>hypnomix ${esc(U.latest)} is out</b><span class="small">you have ${esc(U.current)}</span>
    ${U.notes ? `<button class="later" data-upd="notes">${notes ? 'Hide' : "What's new"}</button>` : ''}${act}</div>
    ${j.status === 'error' ? `<div class="small err">${esc(j.error)}</div>` : ''}
    ${notes && U.notes ? `<pre>${esc(U.notes)}</pre>` : ''}`;
}

function watch(ms) {
  clearInterval(poll);
  poll = setInterval(async () => {
    try { U = await get('/api/update/state'); } catch (e) { return; }
    draw();
    if (!['downloading', 'verifying'].includes((U.job || {}).status)) clearInterval(poll);
  }, ms);
}

function waitForNewVersion(target) {
  // the server stops during the install; when the new version answers, reload (Windows: this browser tab)
  const t0 = Date.now();
  const tick = async () => {
    try { const s = await get('/api/update/state'); if (s.current === target) return location.reload(); } catch (e) {}
    if (Date.now() - t0 < 10 * 60e3) setTimeout(tick, 2000);
    else { installing = false; box.innerHTML = `<div class="small err">The update is taking long. If hypnomix doesn't come back, open it again from the Start menu or Applications.</div>`; }
  };
  setTimeout(tick, 4000);
}

function popup() {
  let p = document.getElementById('updpop');
  if (p) { p.remove(); return; }
  p = document.createElement('div'); p.id = 'updpop';
  const when = U && U.checked ? new Date(U.checked * 1000).toLocaleString() : 'never';
  p.innerHTML = `<b>hypnomix ${esc(U ? U.current : '')}</b>
    <div class="small" style="color:var(--mute);margin-top:4px">${U && U.error ? esc(U.error) : U && U.newer ? `${esc(U.latest)} is available.` : 'Up to date.'} Last checked: ${esc(when)}.</div>
    <label><input type="checkbox" id="updauto" ${U && U.auto ? 'checked' : ''}> Check once a day</label>
    <div style="margin-top:10px;display:flex;gap:8px"><button class="go" id="updnow" style="border:0;border-radius:8px;padding:6px 12px;background:var(--accent);color:var(--accent-ink);cursor:pointer">Check now</button></div>`;
  p.setAttribute('role', 'dialog'); p.setAttribute('aria-label', 'Updates'); p.tabIndex = -1;
  document.body.appendChild(p);
  p.focus({preventScroll: true});                       // the keyboard goes into the popup; Escape closes it and gives the keyboard back
  p.querySelector('#updauto').addEventListener('change', async e => { U = await post('/api/update/settings', { auto: e.target.checked }); });
  p.querySelector('#updnow').addEventListener('click', async () => {
    p.querySelector('#updnow').textContent = 'Checking…'; await load(true);
    draw();
    p.remove(); popup();
  });
}

ver.addEventListener('click', popup);
document.addEventListener('keydown', e => { const p = document.getElementById('updpop'); if (e.key === 'Escape' && p) { e.preventDefault(); p.remove(); ver.focus(); } });
document.addEventListener('click', async e => {
  if (!e.target.closest('#updpop') && e.target !== ver) { const p = document.getElementById('updpop'); if (p) p.remove(); }
  const b = e.target.closest('[data-upd]'); if (!b) return;
  const a = b.dataset.upd;
  try {
    if (a === 'notes') { notes = !notes; return draw(); }
    if (a === 'skip') { U = await post('/api/update/settings', { skip: true }); return draw(); }
    if (a === 'get') { U = await post('/api/update/download', {}); draw(); return watch(700); }
    if (a === 'install') {
      if (!confirm(`Install hypnomix ${U.latest} now? hypnomix closes and opens again; a job that is running stops. Your songs and settings stay as they are.`)) return;
      const target = U.latest;
      U = await post('/api/update/install', {}); installing = true; draw(); waitForNewVersion(target);
    }
  } catch (err) { box.insertAdjacentHTML('beforeend', `<div class="small err">${esc(err.message)}</div>`); }
});

load(false);
setTimeout(() => load(false), 15000);   // the daily check runs in the background at start: show its answer
})();
