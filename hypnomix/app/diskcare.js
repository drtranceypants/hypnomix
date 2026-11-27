// Disk care (hypnomix/app/diskcare.py): free space in the header, a banner when the disk is nearly full, and a
// popover to switch the automatic clean on or off, preview it, run it now and restore moved WAVs.
// Uses the page's get/post/esc.
(() => {
const css = `
#dc{background:none;border:0;color:var(--mute);font:inherit;font-size:.8rem;cursor:pointer;padding:4px 8px}
#dc:hover{color:var(--accent)}#dc.low{color:var(--hi);font-weight:600}
#dcban{background:var(--card);border:1px solid var(--hi);border-radius:12px;margin:14px auto 0;max-width:1100px;padding:12px 16px;display:none}
#dcban.on{display:flex;gap:10px;align-items:center;flex-wrap:wrap}#dcban b{margin-right:auto}
#dcpop{position:absolute;right:12px;top:48px;z-index:20;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;
  box-shadow:0 10px 30px rgba(0,0,0,.18);width:360px;font-size:.92rem;max-height:75vh;overflow:auto}
#dcpop label{display:flex;gap:8px;margin-top:8px;align-items:flex-start}#dcpop .small,#dcban .small{color:var(--mute);font-size:.86rem}
#dcpop textarea{width:100%;box-sizing:border-box;font:inherit;font-size:.82rem;margin-top:4px;min-height:44px}
#dcpop .row{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap}
#dcpop button,#dcban button{border:0;border-radius:8px;padding:6px 12px;cursor:pointer;font:inherit}
#dcpop .go,#dcban .go{background:var(--accent);color:var(--accent-ink)}#dcpop .alt{background:transparent;color:var(--mute);border:1px solid var(--line)}
#dcpop a,#dcban a{color:var(--accent)}#dcpop ul{margin:6px 0 0;padding-left:18px}#dcpop li{margin:2px 0}#dcpop code{font-size:.78rem;word-break:break-all}`;
const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

const btn = document.createElement('button'); btn.id = 'dc'; btn.title = 'Disk care: clears old renders and caches';
const live = document.getElementById('live'); live.parentNode.insertBefore(btn, live);
const ban = document.createElement('div'); ban.id = 'dcban';
document.querySelector('header').after(ban);

const RULE = { cache: 'Render cache', temp: "HypnoMix's own temporary folders (hypnomix-render-…) left by a stopped command", scans: 'Audio in old scans (A/B clips, renders)', out: 'Audio in hypnomix-out',
  crashes: 'Crash records beyond the newest 20',
  bounces: 'Old master bounces', store: 'Store leftovers (old downloads, kept installers, replaced plug-ins)', wavs: 'Old WAVs on Desktop / Downloads (moved to holding)', holding: 'Holding area, past 14 days' };
const gb = n => n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : (n / 1e6).toFixed(0) + ' MB';
let D = null, P = null, later = false;

async function load() {
  try { D = await get('/api/diskcare/state'); } catch (e) { return; }
  draw();
}

function draw() {
  if (!D) return;
  btn.textContent = gb(D.free) + ' free';
  btn.classList.toggle('low', D.level !== 'ok');
  const show = D.level !== 'ok' && !later;
  ban.classList.toggle('on', show);
  if (show) {
    const L = D.last;
    ban.innerHTML = `<b>The disk is nearly full: ${gb(D.free)} free.</b>
      <span class="small">${L && Date.now() / 1000 - L.when < 3600 ? `HypnoMix just freed ${gb(L.freed)}.` : 'HypnoMix can clear its old renders and caches.'}</span>
      <button class="go" data-dc="pop">See what can go</button><button class="alt" data-dc="later" style="background:transparent;border:1px solid var(--line);color:var(--mute)">Later</button>`;
  }
}

function planHtml(rules) {
  if (!rules || !rules.length) return '<div class="small" style="margin-top:8px">Nothing to clear right now.</div>';
  return '<ul>' + rules.map(r => `<li><b>${esc(RULE[r.rule] || r.rule)}</b>: ${gb(r.bytes)}, ${r.count} item${r.count === 1 ? '' : 's'}
    <div class="small">${r.top.slice(0, 3).map(t => `<code>${esc(t.path)}</code>`).join('<br>')}</div></li>`).join('') + '</ul>';
}

// Older versions left their renders in the temp folder under random names. They can't be proven to be ours, so they are
// listed here and removed only by this click.
function leftHtml() {
  const L = D && D.leftovers;
  if (!L || !L.count) return '';
  return `<div id="dcold" style="margin-top:10px;border-top:1px solid var(--line);padding-top:8px"><b>Older versions left ${L.count} temporary folder${L.count === 1 ? '' : 's'}</b>: ${gb(L.bytes)}.
    <div class="small">They hold only WAV files (or a small track-name list) and are a day or more old, so they look like renders HypnoMix made (devices, duck, cliplevel, tidy), but nothing proves it, so they are never removed on their own.</div>
    <ul>${L.items.slice(0, 5).map(d => `<li><code>${esc(d.path)}</code> ${gb(d.bytes)}<div class="small">${d.wavs ? `${d.wavs} WAV file${d.wavs === 1 ? '' : 's'}: ${d.sample.map(esc).join(', ')}` : 'only a track-name list'}</div></li>`).join('')}</ul>
    ${L.count > 5 ? `<div class="small">…and ${L.count - 5} more.</div>` : ''}
    <div class="row"><button class="alt" id="dcoldgo">Clear ${L.count === 1 ? 'it' : 'them'} (${gb(L.bytes)})</button></div></div>`;
}

function popup() {
  let p = document.getElementById('dcpop');
  if (p) { p.remove(); return; }
  p = document.createElement('div'); p.id = 'dcpop';
  const L = D && D.last;
  p.innerHTML = `<b>Disk care</b>
    <div class="small" style="margin-top:4px">${gb(D.free)} free of ${gb(D.total)}. ${L ? `Last clean ${esc(new Date(L.when * 1000).toLocaleString())}: freed ${gb(L.freed)}${L.held ? `, moved ${gb(L.held)} of WAVs to holding` : ''}.` : 'Not cleaned yet.'}</div>
    <label><input type="checkbox" id="dcauto" ${D.auto ? 'checked' : ''}> <span>Clean automatically: weekly, and straight away when the disk is nearly full</span></label>
    <label><input type="checkbox" id="dcwavs" ${D.wavs ? 'checked' : ''}> <span>Also old WAVs on the Desktop and in Downloads (30+ days, not used by a project, not named final or master). They're moved to a holding folder for 14 days first.</span></label>
    <div class="small" style="margin-top:10px">Also look for HypnoMix scans and hypnomix-out folders in (one folder per line):</div>
    <textarea id="dcwatch" placeholder="~/Music/Projects">${esc((D.watch || []).join('\n'))}</textarea>
    <div class="row"><button class="go" id="dcprev">Preview</button><button class="alt" id="dcrun">Clean now</button>
    ${D.holding && D.holding.batches ? `<button class="alt" id="dcback">Restore moved WAVs (${gb(D.holding.bytes)})</button>` : ''}<button class="alt" id="dcclose">Close</button></div>
    <div id="dcplan">${P ? planHtml(P.plan) : ''}</div>
    ${leftHtml()}
    ${D.crashes && D.crashes.count ? `<div class="small" style="margin-top:10px">Crash records: ${D.crashes.count} file${D.crashes.count === 1 ? '' : 's'}, ${D.crashes.bytes >= 1e6 ? (D.crashes.bytes / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(D.crashes.bytes / 1e3)) + ' KB'} in <code>${esc(D.crashes.path)}</code>. The newest ${D.crashes.keeps} are kept; they are never sent anywhere. <a href="#" data-wiki="reporting">About reports</a></div>` : ''}
    <div class="small" style="margin-top:8px">Never removed: audio a Live, REAPER or HypnoMix DAW project uses, findings and reports, anything changed in the last hour. <a href="#" data-wiki="diskcare">How it works</a></div>`;
  p.setAttribute('role', 'dialog'); p.setAttribute('aria-label', 'Disk care'); p.tabIndex = -1;
  document.body.appendChild(p);
  p.focus({preventScroll: true});                       // the keyboard goes into the popup; Escape or Close gives it back to the button
  p.querySelector('#dcclose').addEventListener('click', () => { p.remove(); btn.focus(); });
  const save = async body => {
    try { D = await post('/api/diskcare/settings', body); draw(); }
    catch (e) { alert(e.message); p.remove(); popup(); }       // a folder that can't be watched: say why, show the saved list
  };
  p.querySelector('#dcauto').addEventListener('change', e => save({ auto: e.target.checked }));
  p.querySelector('#dcwavs').addEventListener('change', e => save({ wavs: e.target.checked }));
  p.querySelector('#dcwatch').addEventListener('change', e => save({ watch: e.target.value }));
  p.querySelector('#dcprev').addEventListener('click', async () => {
    p.querySelector('#dcplan').innerHTML = '<div class="small" style="margin-top:8px">Looking…</div>';
    P = await post('/api/diskcare/preview', {});
    p.querySelector('#dcplan').innerHTML = planHtml(P.plan) + (P.blocked && P.blocked.length
      ? `<div class="small" style="margin-top:6px">Couldn't read: ${P.blocked.map(esc).join(', ')}. Allow HypnoMix in System Settings → Privacy &amp; Security → Files and Folders.</div>` : '');
  });
  p.querySelector('#dcrun').addEventListener('click', async () => {
    if (!confirm('Clear the old renders and caches now? Moved WAVs can be restored for 14 days; the rest is deleted.')) return;
    p.querySelector('#dcrun').textContent = 'Cleaning…';
    D = await post('/api/diskcare/run', {}); P = null; draw(); p.remove(); popup();
  });
  const old = p.querySelector('#dcoldgo');
  if (old) old.addEventListener('click', async () => {
    const L = D.leftovers;
    if (!confirm(`Delete these ${L.count} temporary folder${L.count === 1 ? '' : 's'} (${gb(L.bytes)})? They hold only WAV files or a track-name list, and cannot be restored.`)) return;
    old.textContent = 'Clearing…';
    D = await post('/api/diskcare/clear-old', { paths: L.paths }); draw(); p.remove(); popup();
  });
  const back = p.querySelector('#dcback');
  if (back) back.addEventListener('click', async () => { D = await post('/api/diskcare/restore', {}); draw(); p.remove(); popup(); });
}

btn.addEventListener('click', popup);
document.addEventListener('keydown', e => { const p = document.getElementById('dcpop'); if (e.key === 'Escape' && p) { e.preventDefault(); p.remove(); btn.focus(); } });
document.addEventListener('click', e => {
  if (!e.target.closest('#dcpop') && e.target !== btn && !e.target.closest('[data-dc]')) { const p = document.getElementById('dcpop'); if (p) p.remove(); }
  const b = e.target.closest('[data-dc]'); if (!b) return;
  if (b.dataset.dc === 'later') { later = true; return draw(); }
  if (b.dataset.dc === 'pop' && !document.getElementById('dcpop')) popup();
});

load();
setInterval(load, 10 * 60e3);
})();
