// The guided setup (hypnomix/app/setup.py): shown the first time the app opens, and from the Setup button.
// Uses the page's own helpers: $, esc, get, post, go.
(() => {
const css = `
#su{position:fixed;inset:0;z-index:50;background:rgba(20,18,16,.55);display:flex;align-items:flex-start;justify-content:center;overflow:auto;padding:4vh 12px}
#su .box{background:var(--card);color:var(--ink);width:min(880px,100%);border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,.35);padding:26px 28px 22px}
#su h2{margin:0 0 4px;font-size:1.45rem}#su .sub{color:var(--mute);margin:0 0 18px}
#su .steps{display:flex;gap:6px;margin:0 0 18px;flex-wrap:wrap}#su .steps span{font-size:.78rem;padding:3px 10px;border-radius:99px;border:1px solid var(--line);color:var(--mute)}
#su .steps span.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
#su .modes{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:700px){#su .modes{grid-template-columns:1fr}}
#su .mode{display:flex;flex-direction:column;justify-content:flex-start;align-items:stretch;text-align:left;border:1.5px solid var(--line);border-radius:12px;padding:14px 16px;background:var(--bg);color:var(--ink);cursor:pointer;font:inherit}
#su .mode:hover{border-color:var(--accent)}#su .mode.sel{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent) inset}
#su .mode b{font-size:1.05rem}#su .mode .tag{display:inline-block;margin-left:6px;font-size:.72rem;color:var(--accent);font-weight:600}
#su .mode p{margin:6px 0;font-size:.93rem}#su .cost{font-size:.85rem;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 9px;margin:8px 0}
#su ul{margin:4px 0 0 0;padding-left:18px;font-size:.88rem}#su li{margin:2px 0}#su .pro li::marker{content:"+ ";color:var(--ok)}#su .con li::marker{content:"− ";color:var(--hi)}
#su .two{display:grid;grid-template-columns:1fr 1fr;gap:6px 14px}@media(max-width:700px){#su .two{grid-template-columns:1fr}}
#su .pills{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 12px}#su .pills button{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:99px;padding:5px 12px;cursor:pointer;font:inherit;font-size:.9rem}
#su .pills button.sel{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
#su ol{padding-left:20px;margin:6px 0 12px}#su ol li{margin:4px 0}
#su label.f{display:block;font-size:.8rem;color:var(--mute);margin:10px 0 3px}
#su input[type=text],#su input[type=password]{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit}
#su .chk{display:flex;gap:8px;align-items:flex-start;margin:10px 0;font-size:.93rem}
#su .msg{margin:10px 0;padding:9px 12px;border-radius:8px;font-size:.92rem}#su .msg.ok{background:rgba(47,111,79,.12);color:var(--ok)}#su .msg.bad{background:rgba(179,38,30,.1);color:var(--hi)}
#su pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px;white-space:pre-wrap;word-break:break-all;font-size:.82rem;margin:6px 0}
#su .nav{display:flex;justify-content:space-between;gap:10px;margin-top:20px;border-top:1px solid var(--line);padding-top:14px}
#su .nav button,#su .act{border:0;border-radius:9px;padding:9px 16px;font:inherit;cursor:pointer}
#su .primary{background:var(--accent);color:var(--accent-ink)}#su .ghost{background:transparent;color:var(--mute);border:1px solid var(--line)!important}
#su .act{background:var(--ink);color:var(--card);margin-top:4px}#su .act:disabled,#su .primary:disabled{opacity:.45;cursor:default}
#su a{color:var(--accent)}#su .small{font-size:.85rem;color:var(--mute)}`;
const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

let U = null, step = 0, mode = '', prov = 'gemini', loc = 'ollama', key = '', model = '', listen = true, msg = null, busy = false, liveLog = '', cliDone = null;
const STEPS = ['Welcome', 'How you work', 'Connect', 'Ableton Live', 'Done'];
const ext = (u, t) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(t || u.replace(/^https?:\/\//, ''))}</a>`;
const list = (xs, cls) => `<ul class="${cls}">${xs.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;

async function open(force) {
  try { U = await get('/api/setup/state'); } catch (e) { return; }
  if (U.done && !force) return;
  mode = U.mode || ''; step = force && U.done ? 1 : 0; msg = null; liveLog = ''; cliDone = null;
  const sp = U.settings.provider, saved = (U.settings.providers.find(p => p.id === sp) || {}).key_hint;
  prov = U.providers[sp] && saved ? sp : 'gemini';     // the recommended free start, unless a key is already saved
  if (sp === 'ollama' || sp === 'custom') loc = sp === 'ollama' ? 'ollama' : 'lmstudio';
  if (!document.getElementById('su')) { const d = document.createElement('div'); d.id = 'su'; document.body.appendChild(d); }
  draw();
}
function close() { const d = document.getElementById('su'); if (d) d.remove(); }
window.openSetup = () => open(true);

function draw() {
  const d = document.getElementById('su'); if (!d) return;
  const body = [welcome, choose, connect, live, done][step]();
  const canNext = step !== 1 || mode;
  d.innerHTML = `<div class="box" role="dialog" aria-modal="true" aria-label="hypnomix setup">
    <div class="steps">${STEPS.map((s, i) => `<span class="${i === step ? 'on' : ''}">${i + 1}. ${s}</span>`).join('')}</div>
    ${body}
    <div class="nav"><div>${step > 0 ? '<button class="ghost" data-su="back">Back</button>' : ''}
      <button class="ghost" data-su="skip">${step === 4 ? 'Close' : 'Skip setup'}</button></div>
      <div>${step < 4 ? `<button class="primary" data-su="next" ${canNext ? '' : 'disabled'}>${step === 0 ? 'Start' : 'Next'}</button>` : '<button class="primary" data-su="finish">Finish</button>'}</div></div></div>`;
}

function welcome() {
  return `<h2>Welcome to hypnomix</h2><p class="sub">Two minutes of setup. You can change any of it later with the <b>Setup</b> button.</p>
  <p>hypnomix finds the technical problems in a song (clicks, late hits, flat notes, hiss, clashing frequencies, loudness) and proposes a fix for each. You hear it, then approve or skip it. It never changes your original set.</p>
  <p>First, how do you want to work: on your own in the app, or with an AI to explain things and do the clicking? Every way gives you the same tools.</p>`;
}

function choose() {
  return `<h2>How do you want to work?</h2><p class="sub">Costs are rough estimates for one song, from scan to approved fixes (prices checked ${esc(U.prices_checked)}).</p>
  <div class="modes">${U.modes.map(m => `<button class="mode ${mode === m.id ? 'sel' : ''}" data-mode="${m.id}">
    <b>${esc(m.title)}</b><span class="tag">${esc(m.tag)}</span><p>${esc(m.what)}</p>
    <div class="cost">${esc(m.cost)}</div><div class="two">${list(m.pros, 'pro')}${list(m.cons, 'con')}</div></button>`).join('')}</div>`;
}

function connect() {
  if (mode === 'app') return `<h2>Nothing to connect</h2><p class="sub">You're working in the app on your own.</p>
    <p>Start on the <b>Songs</b> tab: choose a song's Live set (or a folder of stems), click <b>Scan</b>, then go through the review. The <b>Wiki</b> tab has short lessons with videos for every step.</p>
    <p class="small">Later you can add an AI from the <b>Assistant</b> tab, or run this setup again.</p>`;
  if (mode === 'key') {
    const g = U.providers[prov], saved = (U.settings.providers.find(p => p.id === prov) || {}).key_hint;
    if (!model) model = (U.settings.providers.find(p => p.id === prov) || {}).model || g.model;
    return `<h2>Connect an AI service</h2><p class="sub">The key stays on this computer (in ~/.hypnomix/ai.json, readable only by you) and goes only to that company.</p>
    <div class="pills">${Object.entries(U.providers).map(([k, v]) => `<button data-prov="${k}" class="${k === prov ? 'sel' : ''}">${esc(v.label)}${k === 'gemini' ? ' · free tier' : ''}</button>`).join('')}</div>
    <b>Get a ${esc(g.label)} key</b> (${ext(g.url)})<ol>${g.steps.map(s => `<li>${esc(s)}</li>`).join('')}</ol>
    <label class="f" for="su-key">API key ${saved ? `(saved: ${esc(saved)}; paste a new one to replace it)` : ''}</label>
    <input type="password" id="su-key" autocomplete="off" spellcheck="false" placeholder="paste your key" value="${esc(key)}">
    <label class="f" for="su-model">Model</label><input type="text" id="su-model" value="${esc(model)}" spellcheck="false">
    ${g.listen ? `<label class="chk"><input type="checkbox" id="su-listen" ${listen ? 'checked' : ''}> <span>Also make it the <b>Listener</b>: the Assistant may offer to send a reduced mono copy of a bounce for notes by ear (about 1 to 5 cents a listen; free within Gemini's free-tier limits). Each listen waits for your click.</span></label>` : ''}
    <button class="act" data-su="test" ${busy ? 'disabled' : ''}>${busy ? 'Testing…' : 'Save and test'}</button>${msgHtml()}`;
  }
  if (mode === 'local') {
    const g = U.local[loc];
    if (!model) model = g.model;
    return `<h2>Use a model on this computer</h2><p class="sub">Free and private. Ollama is the simplest; LM Studio has a point-and-click model browser.</p>
    <div class="pills">${Object.entries(U.local).map(([k, v]) => `<button data-loc="${k}" class="${k === loc ? 'sel' : ''}">${esc(v.label)}</button>`).join('')}</div>
    <b>Set up ${esc(g.label)}</b> (${ext(g.url)})<ol>${g.steps.map(s => `<li>${esc(s)}</li>`).join('')}</ol>
    <label class="f" for="su-model">Model name${loc === 'lmstudio' ? ' (as LM Studio shows it; empty = the loaded one)' : ''}</label>
    <input type="text" id="su-model" value="${esc(model)}" spellcheck="false">
    <button class="act" data-su="test" ${busy ? 'disabled' : ''}>${busy ? 'Testing…' : 'Test the connection'}</button>${msgHtml()}
    <p class="small">Small models sometimes misread a report or call a command wrong; the Assistant still asks before anything changes a set.</p>`;
  }
  // desktop
  const c = cliDone || U.cli, win = U.platform === 'windows';
  const folder = c.agent_dir;
  return `<h2>Let a desktop AI app drive hypnomix</h2><p class="sub">Claude Code is the one hypnomix is built and tested with. Codex, Cursor and other agents that read AGENTS.md work too.</p>
  <ol><li>Get Claude: ${ext('https://claude.com/download', 'claude.com/download')} (the desktop app includes Claude Code in its <b>Code</b> tab) and a Pro or Max plan, or install Claude Code for the terminal (${ext('https://claude.com/product/claude-code', 'claude.com/product/claude-code')}).</li>
  <li>Click the button below: it makes a <code>hypnomix</code> command that runs this app's own copy, and an <b>AI agent</b> folder with the instructions the agent reads.</li></ol>
  <button class="act" data-su="cli" ${busy ? 'disabled' : ''}>${c.agent_ready ? 'Make them again' : 'Make the command and folder'}</button>
  ${c.agent_ready ? `<div class="msg ok">Ready. Command: <code>${esc(c.command || c.shim)}</code><br>Folder: <code>${esc(folder)}</code></div>
  ${!c.on_path && !win ? `<p class="small">So that <code>hypnomix</code> works in Terminal, run this once, then open a new Terminal window:</p><pre>echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc</pre>` : ''}
  <b>Then</b><ol><li><b>Claude desktop app</b>: open the <b>Code</b> tab, choose the folder above, and say: <i>"Read CLAUDE.md, run hypnomix doctor, then scan my song: (drag the .als file in)"</i>.</li>
  <li><b>Terminal</b>: <pre>${win ? `cd "${esc(folder)}"\nclaude` : `cd "${esc(folder)}" && claude`}</pre></li>
  <li><b>Other agents</b>: open that folder in it; it reads AGENTS.md.</li></ol>` : ''}${msgHtml()}
  <p class="small">The app stays useful alongside: review findings with the A/B players while the agent works. For every optional extra and the agent skills, install from the source (Wiki → Install).</p>`;
}

function live() {
  const l = U.live;
  if (l.installed) return `<h2>Ableton Live</h2><div class="msg ok">Connected: the AbletonOSC remote script is installed in Live's User Library.</div>
    <p>If Live doesn't answer yet: restart Live, then <b>Settings → Link, Tempo &amp; MIDI → Control Surface: AbletonOSC</b>.</p>${liveLog ? `<pre>${esc(liveLog)}</pre>` : ''}`;
  return `<h2>Connect to Ableton Live</h2><p class="sub">Optional: lets hypnomix read and control the open set. Scanning set files works without it.</p>
    <p>This copies the AbletonOSC remote script into Live's User Library${l.ableton ? '' : ' (no Ableton folder was found on this computer: it will be created)'}. A different copy already there is backed up first. Nothing else in Live changes.</p>
    <button class="act" data-su="live" ${busy ? 'disabled' : ''}>${busy ? 'Copying…' : 'Connect to Live'}</button>${msgHtml()}
    <p class="small">Then restart Live and choose <b>Settings → Link, Tempo &amp; MIDI → Control Surface: AbletonOSC</b>. REAPER or Ardour? Nothing to install here: see Wiki → hypnomix in REAPER.</p>`;
}

function done() {
  const m = U.modes.find(x => x.id === mode);
  const next = { app: 'Open the <b>Songs</b> tab and scan your first song.', key: 'Open the <b>Assistant</b> tab and say hello, or ask it to scan a song.',
    local: 'Open the <b>Assistant</b> tab and say hello, or ask it to scan a song.', desktop: 'Open your AI app in the AI agent folder and ask it to scan a song.' }[mode] || '';
  return `<h2>You're set</h2><p class="sub">${m ? esc(m.title) : 'Setup'}${U.live.installed ? ' · Live connected' : ''}</p>
    <p>${next}</p><p class="small">Change any of this later: the <b>Setup</b> button at the top, or the Assistant tab's settings. The Wiki's "Choosing how to work with AI" compares the options in more detail.</p>`;
}

function msgHtml() { return msg ? `<div class="msg ${msg.ok ? 'ok' : 'bad'}">${msg.html}</div>` : ''; }
function keep() {
  const k = document.getElementById('su-key'), m = document.getElementById('su-model'), l = document.getElementById('su-listen');
  if (k) key = k.value.trim(); if (m) model = m.value.trim(); if (l) listen = l.checked;
}

async function test() {
  keep(); busy = true; msg = null; draw();
  const body = mode === 'local'
    ? (loc === 'ollama' ? { provider: 'ollama', model } : { provider: 'custom', base_url: U.local.lmstudio.base_url, key: 'lm-studio', model })
    : { provider: prov, key, model, ...(U.providers[prov].listen ? { listen_provider: listen ? prov : '' } : {}) };
  try {
    const r = await fetch('/api/setup/connect', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Hypnomix': TOKEN }, body: JSON.stringify(body) }).then(r => r.json());
    if (r.settings) U.settings = r.settings;
    msg = r.ok ? { ok: true, html: `Connected. ${r.count} model${r.count === 1 ? '' : 's'} available${model ? `; the Assistant will use <code>${esc(model)}</code>` : ''}.` }
               : { ok: false, html: esc(r.error || 'It did not connect.') };
    if (r.ok) key = '';
  } catch (e) { msg = { ok: false, html: esc(e.message) }; }
  busy = false; draw();
}

document.addEventListener('click', async e => {
  if (!document.getElementById('su')) { const b = e.target.closest('[data-setup]'); if (b) open(true); return; }
  const t = e.target.closest('[data-su],[data-mode],[data-prov],[data-loc]'); if (!t || !t.closest('#su')) return;
  keep();
  if (t.dataset.mode) { mode = t.dataset.mode; model = ''; msg = null; return draw(); }
  if (t.dataset.prov) { prov = t.dataset.prov; model = ''; key = ''; msg = null; return draw(); }
  if (t.dataset.loc) { loc = t.dataset.loc; model = ''; msg = null; return draw(); }
  const a = t.dataset.su;
  if (a === 'next') { step = Math.min(4, step + 1); msg = null; return draw(); }
  if (a === 'back') { step = Math.max(0, step - 1); msg = null; return draw(); }
  if (a === 'test') return test();
  if (a === 'cli') {
    busy = true; draw();
    try { cliDone = await post('/api/setup/cli', {}); U.cli = cliDone; msg = null; } catch (err) { msg = { ok: false, html: esc(err.message) }; }
    busy = false; return draw();
  }
  if (a === 'live') {
    busy = true; draw();
    try { const r = await post('/api/setup/live', {}); U.live = r.live; liveLog = r.log; msg = null; } catch (err) { msg = { ok: false, html: esc(err.message) }; }
    busy = false; return draw();
  }
  if (a === 'skip' || a === 'finish') {
    try { await post('/api/setup/finish', { done: true, mode }); } catch (_) {}
    close();
    if (a === 'finish' && typeof go === 'function') go(mode === 'key' || mode === 'local' ? 'chat' : 'home');
  }
});
document.addEventListener('keydown', e => { if (e.key === 'Escape' && document.getElementById('su')) close(); });
open(false);
})();
