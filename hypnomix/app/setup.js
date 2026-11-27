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
#su .nav{display:flex;justify-content:space-between;gap:10px;margin-top:20px;border-top:1px solid var(--line);padding-top:14px;position:sticky;bottom:0;background:var(--card);padding-bottom:10px}
#su .nav button,#su .act{border:0;border-radius:9px;padding:9px 16px;font:inherit;cursor:pointer}
#su .primary{background:var(--accent);color:var(--accent-ink)}#su .ghost{background:transparent;color:var(--mute);border:1px solid var(--line)!important}
#su .act{background:var(--ink);color:var(--card);margin-top:4px}#su .act:disabled,#su .primary:disabled{opacity:.45;cursor:default}
#su a{color:var(--accent)}#su .small{font-size:.85rem;color:var(--mute)}
#su .bar{height:6px;background:var(--line);border-radius:4px;margin:6px 0;overflow:hidden}#su .bar i{display:block;height:100%;background:var(--accent)}`;
const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

let U = null, step = 0, mode = '', daw = '', teach = '', prov = 'gemini', loc = 'ollama', key = '', model = '', listen = true, msg = null, busy = false, liveLog = '', cliDone = null;
const DAWNAME = {live: 'Ableton Live', reaper: 'REAPER', hypnomix: 'HypnoMix Studio'};       // the DAWs the teacher courses exist for
const STEPNAME = Object.assign({hypnomix: 'HypnoMix Studio'}, DAWNAME);
const steps = () => ['Welcome', 'How you work', 'Standalone or Studio', 'Connect', STEPNAME[daw] || 'Connect your DAW', 'Extras', 'Done'];
const LAST = 6, EXTRAS = 5, DAWSTEP = 4;
let poll = null, engPoll = null, opener = null, inerted = [], lastStep = -1, tested = '';      // tested: the last connection test of this setup ('ok', 'bad', or '' when none was run)
const ext =(u, t) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(t || u.replace(/^https?:\/\//, ''))}</a>`;
const list = (xs, cls) => `<ul class="${cls}">${xs.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;

async function open(force) {
  try { U = await get('/api/setup/state'); } catch (e) { return; }
  if (U.done && !force) return;
  // 'ardour' was saved by 0.3.0's Setup: the same DAW as 'hypnomix'
  mode = U.mode || ''; daw = U.daw === 'ardour' ? 'hypnomix' : (U.daw || '');
  teach = U.teach_level || ''; step = force && U.done ? 1 : 0; msg = null; liveLog = ''; cliDone = null;
  const sp = U.settings.provider, saved = (U.settings.providers.find(p => p.id === sp) || {}).key_hint;
  prov = U.providers[sp] && saved ? sp : 'gemini';     // the recommended free start, unless a key is already saved
  if (sp === 'ollama' || sp === 'custom') loc = sp === 'ollama' ? 'ollama' : 'lmstudio';
  tested = '';
  if (!document.getElementById('su')) {
    opener = document.activeElement && document.activeElement !== document.body ? document.activeElement : null;
    const d = document.createElement('div'); d.id = 'su'; document.body.appendChild(d);
    inerted = [...document.body.children].filter(x => x !== d && !['SCRIPT', 'STYLE'].includes(x.tagName) && !x.inert);
    inerted.forEach(x => { x.inert = true; });          // the page behind the dialog takes no focus and no clicks while it is open
    lastStep = -1;
  }
  draw();
  if (U.engine && U.engine.busy) refreshEngine();        // an add that was started before this window was opened: show its progress
}
function close() {
  const d = document.getElementById('su'); if (d) d.remove(); clearTimeout(poll); poll = null; clearTimeout(engPoll); engPoll = null;
  inerted.forEach(x => { x.inert = false; }); inerted = [];
  const back = opener && document.contains(opener) ? opener : document.getElementById('main'); opener = null;
  if (back && back.focus) back.focus({preventScroll: true});
}
// Escape and "Skip setup" are the same thing: the setup is set aside for good, not just until the page is loaded again.
async function finish(a) {
  try { await post('/api/setup/finish', { done: true, mode, daw, teach_level: teach }); } catch (_) {}
  close();
  if (typeof window.teachChanged === 'function') window.teachChanged();
  if (a === 'finish' && typeof go === 'function') go(teach ? 'teach' : mode === 'key' || mode === 'local' ? 'chat' : 'home');
}
window.openSetup = () => open(true);

function draw() {
  const d = document.getElementById('su'); if (!d) return;
  const body = [welcome, choose, pickDaw, connect, dawStep, extras, done][step]();
  const canNext = (step !== 1 || mode) && (step !== 2 || daw);
  const fk = typeof focusKey === 'function' ? focusKey(d) : null;
  d.innerHTML = `<div class="box" role="dialog" aria-modal="true" aria-label="HypnoMix setup">
    <div class="steps">${steps().map((s, i) => `<span class="${i === step ? 'on' : ''}">${i + 1}. ${s}</span>`).join('')}</div>
    ${body}
    <div class="nav"><div>${step > 0 ? '<button class="ghost" data-su="back">Back</button>' : ''}
      <button class="ghost" data-su="skip">${step === LAST ? 'Close' : 'Skip setup'}</button></div>
      <div>${step < LAST ? `<button class="primary" data-su="next" ${canNext ? '' : 'disabled'}>${step === 0 ? 'Start' : 'Next'}</button>` : '<button class="primary" data-su="finish">Finish</button>'}</div></div></div>`;
  // The keyboard stays in the dialog: on a new step it goes to the step's heading (a screen reader says where it is); within a step the control that had it gets it back.
  const same = step === lastStep && fk && typeof restoreFocus === 'function' && restoreFocus(d, fk);
  lastStep = step;
  if (!same) { const h = d.querySelector('h2'); if (h) { h.tabIndex = -1; h.focus({preventScroll: true}); } }
}
// Tab goes round inside the dialog (a browser without `inert` would let it out behind the dialog).
function trap(e) {
  const box = document.querySelector('#su .box'); if (!box) return;
  const f = [...box.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')].filter(x => x.offsetParent !== null);
  if (!f.length) return;
  const i = f.indexOf(document.activeElement);
  if (!box.contains(document.activeElement)) { e.preventDefault(); f[0].focus(); }
  else if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
  else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
}

function welcome() {
  return `<h2>Welcome to HypnoMix</h2><p class="sub">Two minutes of setup. You can change any of it later with the <b>Setup</b> button.</p>
  <p>HypnoMix finds the technical problems in a song (clicks, late hits, flat notes, hiss, clashing frequencies, loudness) and proposes a fix for each. You hear it, then approve or skip it. It never changes your original set.</p>
  <p>First, how do you want to work: on your own in the app, or with an AI to explain things and do the clicking? Every way gives you the same tools. Then Standalone or Studio: HypnoMix Standalone works beside the DAW you already use (Ableton Live, REAPER or another one); HypnoMix Studio has its own DAW built in, an add-on you add only if you want it.</p>
  <p>On the next steps you can turn on <b>teacher mode</b>: a guided tour of HypnoMix in your DAW if you already engineer, or a 101 crash course from an empty song to a finished master if you're new to audio.</p>`;
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
    <label class="f" for="su-model">Model name${loc === 'lmstudio' ? ' (as LM Studio shows it; empty = the first model it lists)' : ''}</label>
    <input type="text" id="su-model" value="${esc(model)}" spellcheck="false">
    <button class="act" data-su="test" ${busy ? 'disabled' : ''}>${busy ? 'Testing…' : 'Test the connection'}</button>${msgHtml()}
    <p class="small">Small models sometimes misread a report or call a command wrong; the Assistant still asks before anything changes a set.</p>`;
  }
  // desktop
  const c = cliDone || U.cli, win = U.platform === 'windows';
  const folder = c.agent_dir;
  return `<h2>Let a desktop AI app drive HypnoMix</h2><p class="sub">Claude Code is the one HypnoMix is built and tested with. Codex, Cursor and other agents that read AGENTS.md work too.</p>
  <ol><li>Get Claude: ${ext('https://claude.com/download', 'claude.com/download')} (the desktop app includes Claude Code in its <b>Code</b> tab) and a Pro or Max plan, or install Claude Code for the terminal (${ext('https://claude.com/product/claude-code', 'claude.com/product/claude-code')}).</li>
  <li>Click the button below: it makes a <code>hypnomix</code> command that runs this app's own copy, and an <b>AI agent</b> folder with the instructions the agent reads.</li></ol>
  <button class="act" data-su="cli" ${busy ? 'disabled' : ''}>${c.agent_ready ? 'Make them again' : 'Make the command and folder'}</button>
  ${c.agent_ready ? `<div class="msg ok">Ready. Command: <code>${esc(c.command || c.shim)}</code><br>Folder: <code>${esc(folder)}</code></div>
  ${!c.on_path && !win ? `<p class="small">So that <code>hypnomix</code> works in Terminal, run this once, then open a new Terminal window:</p><pre>echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc</pre>` : ''}
  <b>Then</b><ol><li><b>Claude desktop app</b>: open the <b>Code</b> tab, choose the folder above, and say: <i>"Read CLAUDE.md, run hypnomix doctor, then scan my song: (drag the .als file in)"</i>.</li>
  <li><b>Terminal</b>: <pre>${win ? `cd "${esc(folder)}"\nclaude` : `cd "${esc(folder)}" && claude`}</pre></li>
  <li><b>Other agents</b>: open that folder in it; it reads AGENTS.md.</li></ol>` : ''}${msgHtml()}
  ${c.agent_ready && c.skills && c.skills.length ? `<p class="small">Claude Code finds the HypnoMix skills in the folder on its own (${c.skills.map(esc).join(', ')}): for a new song, ask for a <b>first pass</b>.</p>` : ''}
  <p class="small">The app stays useful alongside: review findings with the A/B players while the agent works. The optional extras (reference matching, your own plug-ins, stem separation) are on the <b>Extras</b> step.</p>`;
}

function pickDaw() {
  const pick = d => `<button class="mode ${daw === d.id ? 'sel' : ''}" data-daw="${d.id}"><b>${esc(d.title)}</b><p>${esc(d.note)}</p></button>`;
  return `<h2>Standalone or Studio?</h2><p class="sub">It is one app either way, and you can change this later. A DAW is the program you record and mix in; the Wiki and the lessons follow your choice.</p>
  <h3 style="margin:14px 0 2px;font-size:1.05rem">HypnoMix Standalone</h3>
  <p class="small" style="margin:0 0 8px">Keep the DAW you already use. HypnoMix works beside it. Which one?</p>
  <div class="modes">${U.daws.filter(d => d.id !== 'hypnomix').map(pick).join('')}</div>
  <h3 style="margin:18px 0 2px;font-size:1.05rem">HypnoMix Studio</h3>
  <p class="small" style="margin:0 0 8px">HypnoMix with its own DAW built in. Choosing it downloads nothing: the next steps show what it is and add it only if you click.</p>
  <div class="modes">${U.daws.filter(d => d.id === 'hypnomix').map(pick).join('')}</div>
  <h3 style="margin:20px 0 6px;font-size:1.05rem">Teacher mode</h3>
  <p class="small" style="margin:0 0 8px">A guided course in the <b>Teacher</b> tab, in ${esc(DAWNAME[daw] || 'your DAW')}. No AI needed${mode === 'key' || mode === 'local' ? '; the Assistant can explain any step in more detail' : ''}. ${daw === 'live' || daw === 'reaper' ? `HypnoMix can do the hands-on steps in ${DAWNAME[daw]} for you, asking first each time.` : daw === 'hypnomix' ? 'For HypnoMix Studio it shows you where to click, and you make each change yourself.' : 'Courses exist for Live, REAPER and HypnoMix Studio.'}</p>
  <div class="modes" style="grid-template-columns:1fr 1fr">${[
    ['', 'No thanks', 'Straight to the app. You can start a course later from the Teacher tab.'],
    ['tour', 'Show me HypnoMix', `For people who already record and mix: HypnoMix with ${DAWNAME[daw] || 'your DAW'}, the devices we've built for it, the song card, A/B inside the DAW, the mastering chain.`],
    ['101', 'The 101 crash course', 'New to audio? The words and the screen, recording to a click (with a drum beat to play over, if you like), arming a track and setting the input gain, each effect as you add it, mastering, then the HypnoMix tour.'],
    ['az', 'The complete course, A to Z', 'Everything, from what sound is: gear and rooms, recording, editing, mixing and mastering in depth, releasing a song, troubleshooting and cheat sheets, with audio examples, quizzes and a glossary. The 101 crash course is inside it.'],
  ].map(([id, t, d]) => `<button class="mode ${teach === id ? 'sel' : ''}" data-teach="${id}" ${daw === 'other' && id ? 'disabled' : ''}><b>${t}</b><p>${esc(d)}</p></button>`).join('')}</div>`;
}

function dawStep() {
  if (daw === 'reaper') {
    const r = U.reaper;
    return `<h2>REAPER</h2><p class="sub">Optional: lets HypnoMix work in the open REAPER (the mastering chain, the review panel${teach ? ', and the lessons\' hands-on steps' : ''}). Reading and scanning projects works without it.</p>
    ${r.running ? '<div class="msg ok">The bridge is running in REAPER.</div>' : `<p>The bridge is a script that runs inside REAPER while it's open. Nothing is installed and no REAPER setting changes; it stops when REAPER quits.</p>
    <button class="act" data-su="reaper" ${busy || !r.found ? 'disabled' : ''}>${busy ? 'Starting…' : 'Start the bridge (opens REAPER if it\'s closed)'}</button>
    ${r.found ? '' : '<div class="msg bad">REAPER wasn\'t found on this computer. Install it from reaper.fm, then come back.</div>'}`}${msgHtml()}
    <p class="small">Next time, start it from a terminal with <code>hypnomix reaper start</code>, or from this step. See Wiki → HypnoMix in REAPER.</p>`;
  }
  if (daw === 'ardour') return `<h2>HypnoMix Studio</h2><p class="sub">Nothing to install for scanning.</p>
    <p>HypnoMix reads HypnoMix Studio sessions (<code>.ardour</code>) and scans them: on the Songs tab, choose the session folder (or its <code>.ardour</code> file). In these pages the changes you approve are listed for you to make by hand.</p>
    ${teach ? '<p>The Teacher tab shows you where to click in HypnoMix Studio for every step.</p>' : ''}<p class="small">See Wiki → HypnoMix Studio.</p>`;
  if (daw === 'hypnomix') return `<h2>HypnoMix Studio</h2><p class="sub">${esc(U.engine.what)}</p>
    ${engineAct(true)}${msgHtml()}
    <p class="small">${esc(U.engine.licence)} Remove it any time here (Setup → Extras). The DAW tab appears once it is added.</p>`;
  if (daw === 'other') return `<h2>Your DAW</h2><p class="sub">Nothing to install.</p>
    <p>Export every track as a WAV from the same start point (most DAWs call it "export stems" or "bounce tracks"), put them in one folder, and scan that folder on the Songs tab. Repaired audio comes back as new files.</p><p class="small">See Wiki → Any other DAW.</p>`;
  return live();
}

function live() {
  const l = U.live;
  if (l.installed && teach && !l.teach_ready) return `<h2>Ableton Live</h2><div class="msg ok">Connected: the AbletonOSC remote script is installed.</div>
    <p>Teacher mode adds drum beats and new tracks in Live, which needs this version's copy of the script. Updating keeps a backup of the old one.</p>
    <button class="act" data-su="live" ${busy ? 'disabled' : ''}>${busy ? 'Copying…' : 'Update the connection'}</button>${msgHtml()}
    <p class="small">Then restart Live.</p>${liveLog ? `<pre>${esc(liveLog)}</pre>` : ''}`;
  if (l.installed) return `<h2>Ableton Live</h2><div class="msg ok">Connected: the AbletonOSC remote script is installed in Live's User Library.</div>
    <p>If Live doesn't answer yet: restart Live, then <b>Settings → Link, Tempo &amp; MIDI → Control Surface: AbletonOSC</b>.</p>${liveLog ? `<pre>${esc(liveLog)}</pre>` : ''}`;
  return `<h2>Connect to Ableton Live</h2><p class="sub">Optional: lets HypnoMix read and control the open set. Scanning set files works without it.</p>
    <p>This copies the AbletonOSC remote script into Live's User Library${l.ableton ? '' : ' (no Ableton folder was found on this computer: it will be created)'}. A different copy already there is backed up first. Nothing else in Live changes.</p>
    <button class="act" data-su="live" ${busy ? 'disabled' : ''}>${busy ? 'Copying…' : 'Connect to Live'}</button>${msgHtml()}
    <p class="small">Then restart Live and choose <b>Settings → Link, Tempo &amp; MIDI → Control Surface: AbletonOSC</b>.</p>`;
}

function extras() {
  const X = U.extras, rows = X.extras.filter(e => !e.included), inc = X.extras.filter(e => e.included);
  return `<h2>Optional extras</h2><p class="sub">HypnoMix Studio is its own download from the project's release page, and only when you click Add. The extras below it each add a few commands: install any of them now or later (the Setup button brings you back here). They download from PyPI${X.bundled ? ` into <code>${esc(X.where)}</code>, outside the app, so updating the app keeps them` : ` into this Python (<code>${esc(X.where)}</code>)`}.</p>
  <div class="cost" style="padding:10px 12px"><b>HypnoMix Studio</b> <span class="small">· ${esc(U.engine.size_text)} · GNU GPL</span>
    <p style="margin:4px 0">${esc(U.engine.what)}</p>${engineAct(false)}
    <p class="small" style="margin:4px 0">${esc(U.engine.licence)}</p></div>
  ${rows.map(e => `<div class="cost" style="padding:10px 12px">
    <b>${esc(e.title)}</b> <span class="small">· ${esc(e.size)} · ${esc(e.license)}</span>
    <p style="margin:4px 0">${esc(e.what)}${e.commands.length ? ` <span class="small">Commands: ${e.commands.map(c => `<code>${esc(c)}</code>`).join(', ')}</span>` : ''}</p>
    ${e.installed ? '<div class="msg ok" style="margin:4px 0">Installed.</div>'
      : `<button class="act" data-extra="${esc(e.id)}" ${e.running || !X.pip ? 'disabled' : ''}>${e.running ? 'Installing…' : e.ok === false ? 'Try again' : 'Install'}</button>`}
    ${e.log && (e.running || e.ok === false) ? `<pre style="max-height:160px;overflow:auto">${esc(e.log.split('\n').slice(-14).join('\n'))}</pre>` : ''}
    ${e.ok === false && !e.running ? '<div class="msg bad" style="margin:4px 0">It did not install: the last lines are above. Nothing in the app changed.</div>' : ''}</div>`).join('')}
  ${!X.pip ? (X.bundled ? '<div class="msg bad">This copy of the app can\'t install extras. Download the newest installer from the HypnoMix site and install it over this one.</div>'
    : '<div class="msg bad">This Python has no pip, and uv isn\'t on the PATH. From source, in a terminal in the HypnoMix folder: <code>uv pip install -e ".[reference,plugins,ml]"</code> (or only the ones you want).</div>') : ''}
  ${msgHtml()}
  <p class="small">The GPL-3.0 extras are separate projects, so HypnoMix itself stays MIT: you download them from their authors, and using them is fine for any music, commercial too. Stem separation may not install on Intel Macs (PyTorch has stopped building for them). Already included: ${inc.map(e => esc(e.title)).join(', ')}.</p>`;
}

// HypnoMix Studio: what is added, the one button that adds it (only on a click), progress, and Remove. rich: the DAW step (says the
// choice is remembered while there is nothing to add); Extras shows the state only.
function engineAct(rich) {
  const E = U.engine, j = E.job || {}, mb = n => Math.round(n / 1e6) + ' MB';
  if (E.busy) {
    const pct = j.size ? Math.min(100, Math.round(100 * j.got / j.size)) : 0;
    const what = {downloading: `Downloading ${mb(j.got)} of ${mb(j.size)}…`, verifying: 'Checking the fingerprint…', unpacking: 'Unpacking…', checking: 'Checking the kit…'}[j.status] || 'Putting it in place…';
    return `<div class="small">${esc(what)}</div><div class="bar"><i style="width:${pct}%"></i></div>`;
  }
  const err = j.status === 'error' && j.error ? `<div class="msg bad" style="margin:4px 0">${esc(j.error)}</div>` : '';
  const rm = E.versions.length ? `<button class="act" style="background:transparent;color:var(--ink);border:1px solid var(--line)" data-engine="remove" ${E.running ? 'disabled' : ''}>Remove HypnoMix Studio</button>${E.running ? ' <span class="small">Close the DAW view first: it is running.</span>' : ''}` : '';
  if (E.available && E.current) return `<div class="msg ok" style="margin:4px 0">${esc(E.message)}</div>${err}${rm}`;
  if (E.available) return `<p style="margin:4px 0">${esc(E.message)}</p>${err}<button class="act" data-engine="install">${E.needs_update ? 'Update HypnoMix Studio' : 'Add HypnoMix Studio'}</button> ${rm}`;
  return `<p style="margin:4px 0">${esc(E.message)}${rich ? ' Your choice is remembered, and nothing is downloaded. When one is published for this computer it is added from here, only when you click.' : ''}</p>${err}${rm}`;
}

async function refreshEngine() {
  try { U.engine = await get('/api/setup/engine'); } catch (_) { return; }
  if (step === EXTRAS || (step === DAWSTEP && daw === 'hypnomix')) draw();
  clearTimeout(engPoll); engPoll = U.engine.busy ? setTimeout(refreshEngine, 1000) : null;
  if (!U.engine.busy && typeof dawTab === 'function') dawTab();      // the DAW tab appears (or goes) with the engine, without waiting for the page's own look
}

async function refreshExtras() {
  try { U.extras = await get('/api/setup/extras'); } catch (_) { return; }
  if (step === EXTRAS) draw();
  clearTimeout(poll); poll = U.extras.extras.some(e => e.running) ? setTimeout(refreshExtras, 1500) : null;
}

function done() {
  const m = U.modes.find(x => x.id === mode);
  const next = teach ? `Open the <b>Teacher</b> tab: ${teach === 'tour' ? `the tour starts with how HypnoMix works and connecting it to ${esc(DAWNAME[daw] || 'your DAW')}` : teach === 'az' ? 'the course starts with what sound is' : `the first lesson is the words and the screen of ${esc(DAWNAME[daw] || 'your DAW')}`}. Go at your own pace; it remembers where you are.` : { app: 'Open the <b>Songs</b> tab and scan your first song.', key: 'Open the <b>Assistant</b> tab and say hello, or ask it to scan a song.',
    local: 'Open the <b>Assistant</b> tab and say hello, or ask it to scan a song.', desktop: 'Open your AI app in the AI agent folder and ask it to scan a song.' }[mode] || '';
  const ai = (mode === 'key' || mode === 'local') && tested !== 'ok';      // asked for an AI, and no test of it passed here: do not say it is set
  const aiNote = !ai ? '' : tested === 'bad'
    ? `<div class="msg bad">The AI is not connected yet: the last connection test did not pass. Open the <b>Assistant</b> tab to ${mode === 'key' ? 'add or fix the key' : 'check the connection'}. Everything else works without it.</div>`
    : `<div class="msg">The AI connection was not tested in this setup. If you already added ${mode === 'key' ? 'a key' : 'a local model'}, it is still saved; to add or check ${mode === 'key' ? 'one' : 'it'}, open the <b>Assistant</b> tab. Everything else works without it.</div>`;      // an untested AI is not "not connected": an earlier session may have saved a working one
  return `<h2>${ai ? 'Setup saved' : "You're set"}</h2>${aiNote}<p class="sub">${m ? esc(m.title) : 'Setup'}${daw ? ' · ' + esc((U.daws.find(d => d.id === daw) || {}).title || DAWNAME[daw] || '') : ''}${daw === 'hypnomix' ? (U.engine.versions.length ? ' (added)' : ' (not added yet)') : ''}${daw === 'live' && U.live.installed ? ' · Live connected' : ''}${teach === 'tour' ? ' · teacher mode: the tour' : teach === '101' ? ' · teacher mode: the 101 course' : teach === 'az' ? ' · teacher mode: the complete course' : ''}</p>
    <p>${next}</p><p class="small">Change any of this later: the <b>Setup</b> button at the top, or the Assistant tab's settings. The Wiki's "Choosing how to work with AI" compares the options in more detail.</p>`;
}

function msgHtml() { return msg ? `<div class="msg ${msg.ok ? 'ok' : 'bad'}">${msg.html}${msg.ok ? '' : ' <button type="button" data-report="banner">Report this</button>'}</div>` : ''; }
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
    tested = r.ok ? 'ok' : 'bad';
    if (r.ok && r.model) model = r.model;       // none typed: the server used the first one the model server lists
    msg = r.ok ? { ok: true, html: `Connected. ${r.count} model${r.count === 1 ? '' : 's'} available${model ? `; the Assistant will use <code>${esc(model)}</code>${r.model ? ' (the first one listed: type another name above to change it)' : ''}` : ''}.` }
               : { ok: false, html: esc(r.error || 'It did not connect.') };
    if (r.ok) key = '';
  } catch (e) { tested = 'bad'; msg = { ok: false, html: esc(e.message) }; }
  busy = false; draw();
}

document.addEventListener('click', async e => {
  if (!document.getElementById('su')) { const b = e.target.closest('[data-setup]'); if (b) open(true); return; }
  const t = e.target.closest('[data-su],[data-engine],[data-mode],[data-prov],[data-loc],[data-extra],[data-daw],[data-teach]'); if (!t || !t.closest('#su')) return;
  keep();
  if (t.dataset.engine) {                       // the one place anything is fetched or removed: a click on its button; the request carries nothing
    msg = null;
    try { U.engine = await post('/api/setup/engine/' + t.dataset.engine, {}); } catch (err) { msg = { ok: false, html: esc(err.message) }; }
    draw(); return refreshEngine();
  }
  if (t.dataset.teach !== undefined) { teach = t.dataset.teach; post('/api/setup/daw', { teach_level: teach }).catch(() => {}); return draw(); }
  if (t.dataset.daw) { daw = t.dataset.daw; if (daw === 'other') teach = ''; msg = null; post('/api/setup/daw', { daw, teach_level: teach }).catch(() => {}); return draw(); }
  if (t.dataset.mode) { mode = t.dataset.mode; model = ''; msg = null; tested = ''; return draw(); }
  if (t.dataset.prov) { prov = t.dataset.prov; model = ''; key = ''; msg = null; tested = ''; return draw(); }
  if (t.dataset.extra) {
    msg = null;
    try { U.extras = await post('/api/setup/extra', { name: t.dataset.extra }); } catch (err) { msg = { ok: false, html: esc(err.message) }; }
    draw(); return refreshExtras();
  }
  if (t.dataset.loc) { loc = t.dataset.loc; model = ''; msg = null; tested = ''; return draw(); }
  const a = t.dataset.su;
  if (a === 'next') { step = Math.min(LAST, step + 1); msg = null; return draw(); }
  if (a === 'back') { step = Math.max(0, step - 1); msg = null; return draw(); }
  if (a === 'test') return test();
  if (a === 'cli') {
    busy = true; draw();
    try { cliDone = await post('/api/setup/cli', {}); U.cli = cliDone; msg = cliDone.note ? { ok: false, html: esc(cliDone.note) } : null; } catch (err) { msg = { ok: false, html: esc(err.message) }; }
    busy = false; return draw();
  }
  if (a === 'reaper') {
    busy = true; draw();
    try { const r = await post('/api/setup/reaper', {}); U.reaper = r.reaper; msg = null; } catch (err) { msg = { ok: false, html: esc(err.message) }; }
    busy = false; return draw();
  }
  if (a === 'live') {
    busy = true; draw();
    try { const r = await post('/api/setup/live', {}); U.live = r.live; liveLog = r.log; msg = null; } catch (err) { msg = { ok: false, html: esc(err.message) }; }
    busy = false; return draw();
  }
  if (a === 'skip' || a === 'finish') return finish(a);
});
document.addEventListener('keydown', e => {
  if (!document.getElementById('su')) return;
  if (e.key === 'Escape') { e.preventDefault(); finish('skip'); }
  else if (e.key === 'Tab') trap(e);
});
open(false);
})();
