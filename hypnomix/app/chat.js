// The Assistant tab (served at /chat.js; uses the page's own helpers: $, esc, get, post, S, render).
const C = {items: [], total: 0, busy: false, pending: null, settings: null, open: false, models: [], draft: '', usage: null,
  lopen: false, lmodels: []};

(function () {   // the tab's own look, on top of the page's styles
  const st = document.createElement('style');
  st.textContent = `#chatlog{display:flex;flex-direction:column;gap:8px;margin:14px 0;max-height:60vh;overflow:auto}
  .msg{padding:10px 12px;border-radius:10px;max-width:85%;line-height:1.45;white-space:normal}
  .msg.me{align-self:flex-end;background:var(--card);border:1px solid var(--line)}
  .msg.ai{align-self:flex-start;border:1px solid var(--line)}.msg.err{border:1px solid var(--hi);color:var(--hi)}
  .msg pre,.ask pre{white-space:pre-wrap;overflow-x:auto}.act{color:var(--mute);font-size:.9em}
  #ctext{width:100%;box-sizing:border-box;font:inherit}
  #ckey,#clkey{font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);flex:1;min-width:200px}
  #cbudget{font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}`;
  document.head.appendChild(st);
})();

async function chatPoll(full) {
  const r = await get('/api/chat/state?since=' + (full ? 0 : C.total));
  const changed = full || r.items.length || r.busy !== C.busy || JSON.stringify(r.pending) !== JSON.stringify(C.pending) || !C.settings;
  if (full || r.total < C.total) C.items = [];
  if (!r.busy) C.stopping = false;
  C.items.push(...r.items); C.total = r.total; C.busy = r.busy; C.pending = r.pending; C.settings = r.settings; C.usage = r.usage;
  // a card drawn earlier keeps its place: how it ended (approved and done, failed, cancelled, expired) comes from the server
  if (r.asks) C.items.forEach(x => { const a = x.id && r.asks[x.id]; if (a) Object.assign(x, a); });
  const sig = JSON.stringify(r.asks || {}); if (sig !== C.asksSig) { C.asksSig = sig; if (!full && S.view === 'chat') chatDraw(); }
  if (S.view === 'chat' && changed) chatDraw();    // only when something changed: typing is never interrupted
}

function chatItem(it) {
  if (it.kind === 'user') return `<div class="msg me">${esc(it.text)}</div>`;
  if (it.kind === 'assistant') return `<div class="msg ai">${chatMd(it.text)}</div>`;
  if (it.kind === 'tool') return `<div class="act">↳ ${esc(it.text)}</div>`;
  if (it.kind === 'ask' && (it.what === 'daw' || it.what === 'scan')) {   // DAW mode: a change to the open session, through the engine
    const live = C.pending && C.pending.id === it.id, daw = it.what === 'daw';
    const rows = (it.rows || []).length ? `<table class="rows">${it.rows.map(r => `<tr><td>${esc(r.what)}</td><td>${esc(r.before)}</td><td>→</td><td><b>${esc(r.after)}</b></td></tr>`).join('')}</table>` : '';
    const call = daw ? `<details><summary>The exact call to the engine</summary><pre>${esc(it.tool || '')} ${esc(JSON.stringify(it.arguments || {}, null, 1))}</pre></details>` : `<pre>${esc(it.text || '')}</pre>`;
    return `<div class="card ask"><b>${esc(it.title || (daw ? it.tool : 'Save the session and scan it') || '')}</b>
      ${it.summary ? `<p class="note">${esc(it.summary)}</p>` : ''}${rows}${call}
      ${live ? `<button class="primary" data-chatok="${esc(it.id)}" data-digest="${esc(it.digest || '')}">Approve</button> <button data-chatno="${esc(it.id)}">Cancel</button>
        <span class="note">Nothing changes until you approve. ${esc(it.undo_text || (daw ? '' : 'Saving writes the session file; the scan itself changes nothing.'))}</span>`
        : `<span class="note">${esc(chatOutcome(it))}</span>`}</div>`;
  }
  if (it.kind === 'ask') {
    const live = C.pending && C.pending.id === it.id, hear = it.what === 'listen', budget = it.what === 'budget',
      opts = it.options || [], sent = it.answer && it.answer !== 'declined' && it.answer !== 'expired';
    const title = budget ? 'The assistant has used a lot on this message:' : hear ? 'The assistant wants to listen to your song:'
      : 'The assistant wants to run this command:';
    const yes = opts.length ? opts.map(o => `<button class="primary" data-chatchoice="${esc(it.id)}" data-value="${esc(o.value)}">${esc(o.label)}</button>`).join(' ')
      : `<button class="primary" data-chatok="${esc(it.id)}">${budget ? 'Keep going' : hear ? 'Send it' : 'Run it'}</button>`;
    const help = budget ? 'Each message has a token allowance (in the settings above). Keep going gives it another one.'
      : hear ? 'Only this song leaves the computer, as a reduced mono copy, and only to the listening service you chose. The cost is an estimate.'
      : 'If it writes a set, it is a new one next to the original. Save and close the set in Live first.';
    const done = it.answer === 'expired' ? 'Expired unanswered: nothing was ' + (hear ? 'sent.' : budget ? 'continued.' : 'run.')
      : budget ? (sent ? 'You said keep going.' : 'Stopped.') : sent ? (hear ? 'You sent it.' : 'You ran it.') : (hear ? 'Not sent.' : 'Not run.');
    return `<div class="card ask"><b>${title}</b><pre>${esc(it.text)}</pre>
      ${live ? `${yes} <button data-chatno="${esc(it.id)}">${budget ? 'Stop here' : "Don't"}</button> <span class="note">${help}</span>`
        : `<span class="note">${done}</span>`}</div>`;
  }
  if (it.again) return `<div class="act">${esc(it.text)} <button data-cagain="${esc(it.again)}" ${C.busy ? 'disabled' : ''}>Listen again</button></div>`;
  if (it.kind === 'error') return `<div class="msg err">${esc(it.text)} <button type="button" data-report="chat">Report this</button></div>`;
  return `<div class="act">${esc(it.text)}</div>`;
}

// how a card ended, in words: the real outcome, not only "approved" or "cancelled"
function chatOutcome(it) {
  const a = it.answer;
  if (a === 'sending') return 'Approved · sending it to the engine…';
  if (a === 'ran') return it.what === 'daw' ? 'Approved · applied in the engine' + (it.now ? ' · reads back: ' + it.now : '') : 'Approved · done';
  if (a === 'failed') return 'Approved, but the engine said: ' + (it.error || 'it failed') + (/may or may not/.test(it.error || '') ? '' : ' · nothing changed');
  if (a === 'declined') return 'Cancelled · nothing changed';
  if (a === 'expired') return 'Expired unanswered · nothing changed';
  return 'Not waiting any more';
}

// a small, safe subset of markdown: code, bold, line breaks, bullet lines
function chatMd(t) {
  let h = esc(t);
  h = h.replace(/```([\s\S]*?)```/g, (m, c) => `<pre>${c.replace(/^\w*\n/, '')}</pre>`);
  h = h.replace(/`([^`\n]+)`/g, '<code>$1</code>').replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
  h = h.split('\n').map(l => /^\s*#{1,6} /.test(l) ? '<b>' + l.replace(/^\s*#{1,6} /, '') + '</b>'      // headings: bold lines
    : /^\s*(-{3,}|\*{3,})\s*$/.test(l) ? '' : /^\s*[-*] /.test(l) ? '• ' + l.replace(/^\s*[-*] /, '') : l).join('<br>');
  return h.replace(/<br>(<pre>)/g, '$1').replace(/(<\/pre>)<br>/g, '$1');
}

function chatSettings() {
  const st = C.settings; if (!st) return '';
  const p = st.providers.find(x => x.id === st.provider) || st.providers[0];
  const opts = st.providers.map(x => `<option value="${x.id}" ${x.id === p.id ? 'selected' : ''}>${esc(x.label)}</option>`).join('');
  const needsBase = p.id === 'custom' || p.id === 'ollama';
  const dm = p.default_model || '', models = (dm ? [dm] : []).concat(C.models.filter(m => m !== dm));
  return `<div class="card"><div class="row"><label for="cprov">AI provider</label><select id="cprov">${opts}</select></div>
    ${p.no_key ? '<div class="row note">No key needed: Ollama runs models on this computer (ollama.com).</div>' :
      `<div class="row"><label for="ckey">API key</label><input type="password" id="ckey" placeholder="${p.key_hint ? 'saved (' + esc(p.key_hint) + '): paste to replace' : 'paste your key'}" autocomplete="off">
      ${p.key_hint ? '<button id="cforget">Forget key</button>' : ''}</div>
      <div class="row note">${p.keys_at ? 'Get a key at ' + esc(p.keys_at) + '. ' : ''}Kept on this computer only, and sent only to ${esc(p.label)}.${st.listen && st.listen.provider ? '' : ' Your audio never leaves this computer.'}</div>`}
    ${needsBase ? `<div class="row"><label for="cbase">Address</label><input type="text" id="cbase" value="${esc(p.base_url)}" placeholder="https://…/v1"></div>` : ''}
    <div class="row"><label for="cmodel">Model</label><input type="text" id="cmodel" list="cmodels" value="${esc(p.model)}" placeholder="choose with List models">
      <datalist id="cmodels">${models.map(m => `<option value="${esc(m)}"${m === dm ? ' label="' + esc(m) + ' (default)"' : ''}>`).join('')}</datalist><button id="clist">List models</button></div>
    ${dm ? `<div class="row note">${p.model === dm ? esc(dm) + ' is the default model.' : 'The default is <b>' + esc(dm) + '</b>.'} Every other model stays available: List models, or type its name.</div>` : ''}
    <div class="row"><label for="cbudget">Ask me before one message uses more than</label><input type="number" id="cbudget" min="50000" step="50000" value="${st.budget_tokens}" style="width:9em"> <span>input tokens</span></div>
    <div class="row note">Each step re-reads the conversation, so a long message adds up. Past this it stops and asks "keep going?" (default ${(st.budget_default || 400000).toLocaleString('en-US')}).</div>
    ${C.notice ? `<div class="row note"><b>${esc(C.notice)}</b></div>` : ''}
    <div class="row"><button class="primary" id="csave">Save</button> <span class="note" id="csaved"></span></div></div>`;
}

// The Listener: a second model, with its own key, that hears a bounce for notes by ear. The chat model above can be
// anything; the listener is a Google model (directly, or through OpenRouter). Off until chosen; each listen asks first.
function chatListen() {
  const L = C.settings && C.settings.listen; if (!L) return '';
  const cur = L.options.find(o => o.id === L.provider);
  if (!C.lopen && (!cur || cur.has_key)) return `<p class="note">Listener: ${cur ? esc(cur.label) + ' · ' + esc(cur.model)
    : 'off (your audio stays on this computer)'} <button id="clopen">${cur ? 'Listener settings' : 'Set up a listener'}</button></p>`;
  const opts = [`<option value="" ${cur ? '' : 'selected'}>Off (audio stays on this computer)</option>`]
    .concat(L.options.map(o => `<option value="${o.id}" ${cur && cur.id === o.id ? 'selected' : ''}>${esc(o.label)}</option>`)).join('');
  const models = cur ? [...cur.picks.map(x => x.id), ...C.lmodels.filter(m => !cur.picks.some(x => x.id === m))] : [];
  return `<div class="card"><h3 style="margin-top:0">Listener: a Google model that hears your songs</h3>
    <p class="note">The assistant above talks and runs HypnoMix; the listener only listens. Use the model that is best at each.</p>
    <div class="row"><label for="clisten">Service</label><select id="clisten">${opts}</select></div>
    ${cur ? `<div class="row"><label for="clkey">${esc(cur.label)} key</label><input type="password" id="clkey" autocomplete="off"
        placeholder="${cur.key_hint ? (cur.key_hint.startsWith('from ') ? esc(cur.key_hint) + ': paste to save one here' : 'saved (' + esc(cur.key_hint) + '): paste to replace') : 'paste your key'}">
        ${cur.key_hint && !cur.key_hint.startsWith('from ') ? '<button id="clforget">Forget key</button>' : ''}</div>
      <div class="row note">Get one at ${esc(cur.keys_at)}${cur.id === 'gemini' ? ' (free tier available; on the free tier Google may use what you send to improve its models, the paid tier does not)' : ''}.
        Kept on this computer only, and sent only to ${esc(cur.label)}.</div>
      <div class="row"><label for="clmodel">Model</label><input type="text" id="clmodel" list="clmodels" value="${esc(cur.model)}">
        <datalist id="clmodels">${models.map(m => `<option value="${esc(m)}">`).join('')}</datalist><button id="cllist">List models</button></div>
      <ul class="note" style="margin:4px 0 8px;padding-left:18px">${cur.picks.map(x => `<li><b>${esc(x.id)}</b>: ${esc(x.note)}</li>`).join('')}
        ${C.lmodels.length ? `<li>${C.lmodels.length} models on this key take audio: pick any in the Model box.</li>` : ''}</ul>
      <div class="row note">The assistant asks before each listen and shows the song, its length and rough cost. Only a reduced mono copy is sent.</div>` : ''}
    <div class="row"><button class="primary" id="clsave">Save</button> <span class="note" id="clsaved"></span></div></div>`;
}

function chatCost() {
  const u = C.usage; if (!u || !u.calls) return '';
  const k = n => n >= 10000 ? Math.round(n / 1000) + 'k' : n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
  const read = u.input + u.cache_write + u.cache_read;
  const cost = u.cost_text || '';    // worded by the server (chat.py cost_text): by the provider this conversation is with, listening apart
  return `<p class="note" id="ccost">This conversation: ${u.calls} call${u.calls === 1 ? '' : 's'} · ${k(read)} tokens read`
    + (u.cache_read ? ` (${k(u.cache_read)} from cache, cheaper)` : '') + ` · ${k(u.output)} written · ${cost}</p>`;
}

function chatView() {
  const st = C.settings, p = st && (st.providers.find(x => x.id === st.provider));
  const ready = p && (p.no_key || p.key_hint) && p.model;
  return `<h1>Assistant</h1>
  <p class="sub">Talk about your song and let an AI run HypnoMix for you. Bring a key from the AI service you like.
  It reads HypnoMix's reports${st && st.listen && st.listen.provider ? ', listens to a song only when you click Send it,' : ', never your audio,'} and anything that changes a set waits for your click.</p>
  ${!ready || C.open ? chatSettings() : `<p class="note">${esc(p.label)} · ${esc(p.model)}${p.model === p.default_model ? ' (default)' : ''} <button id="copen">Settings</button> <button id="creset">New conversation</button></p>`}
  ${chatListen()}
  ${chatCost()}
  <div id="chatlog" aria-live="polite">${C.items.map(chatItem).join('') ||
    '<p class="note">Try: "Do a first pass on my song" (attach the set below), "What does the review say about the vocals?", or "Apply what I approved".</p>'}
    ${C.busy && !C.pending ? '<div class="act"><span class="spin"></span>working…</div>' : ''}</div>
  <div class="card"><textarea id="ctext" rows="3" placeholder="${ready ? 'Ask, or tell it what to do…' : 'Add a key and a model above first'}">${esc(C.draft)}</textarea>
    <div class="row"><button class="primary" id="csend" ${ready && !C.busy ? '' : 'disabled'}>Send</button>
      ${S.state && S.state.chooser === false ? '' : '<button data-cpick="set">Attach a set…</button><button data-cpick="folder">Attach a folder…</button><button data-cpick="audio">Attach audio…</button>'}
      ${C.busy ? `<button id="cstop" ${C.stopping ? 'disabled' : ''}>${C.stopping ? 'Stopping…' : 'Stop'}</button>` : ''}</div></div>`;
}

function chatDraw() {
  const t = $('#ctext'); if (t) C.draft = t.value;
  const focus = document.activeElement && document.activeElement.id;
  const m = $('#main'); if (!m) return;
  m.innerHTML = chatView();
  const log = $('#chatlog'); if (log) log.scrollTop = log.scrollHeight;
  if (focus && $('#' + focus)) $('#' + focus).focus();
}

async function chatSaveListener() {
  const body = {listen_provider: $('#clisten').value};
  if ($('#clmodel')) body.listen_model = $('#clmodel').value;
  if ($('#clkey') && $('#clkey').value) body.listen_key = $('#clkey').value;
  C.settings = await post('/api/chat/settings', body);
}

async function chatSaveSettings() {
  const body = {provider: $('#cprov').value};
  if ($('#cmodel')) body.model = $('#cmodel').value;
  if ($('#cbase')) body.base_url = $('#cbase').value;
  if ($('#ckey') && $('#ckey').value) body.key = $('#ckey').value;
  if ($('#cbudget')) body.budget_tokens = $('#cbudget').value;
  C.settings = await post('/api/chat/settings', body);
  C.notice = C.settings.notice || '';
}

document.addEventListener('click', async e => {
  if (S.view !== 'chat') return;
  const b = e.target.closest('button'); if (!b) return;
  try {
    if (b.id === 'clsave' || b.id === 'cllist') { await chatSaveListener();
      if (b.id === 'clsave') { C.lopen = false; chatDraw(); }
      else { const r = await post('/api/chat/listen-models', {}); C.lmodels = r.models || []; chatDraw(); } }
    else if (b.id === 'clopen') { C.lopen = true; chatDraw(); }
    else if (b.id === 'clforget') { C.settings = await post('/api/chat/settings', {listen_provider: $('#clisten').value, listen_forget: true}); chatDraw(); }
    else if (b.id === 'csave') { await chatSaveSettings(); C.open = !!C.notice; chatDraw(); }
    else if (b.id === 'copen') { C.open = true; chatDraw(); }
    else if (b.id === 'cforget') { C.settings = await post('/api/chat/settings', {provider: $('#cprov').value, forget: true}); chatDraw(); }
    else if (b.id === 'clist') { await chatSaveSettings(); const r = await post('/api/chat/models', {}); C.models = r.models || []; chatDraw();
      const s = $('#csaved'); if (s) s.textContent = C.models.length + ' models: pick one in the Model box'; }
    else if (b.id === 'creset') { await post('/api/chat/reset', {}); C.draft = ''; await chatPoll(true); }
    else if (b.id === 'csend') { const t = $('#ctext').value.trim(); if (!t) return; C.draft = ''; $('#ctext').value = '';
      await post('/api/chat/send', {text: t}); await chatPoll(); }
    else if (b.id === 'cstop') { C.stopping = true; chatDraw(); await post('/api/chat/stop', {}); }
    else if (b.dataset.chatok) { b.disabled = true;     // one click, one answer; the card's digest says which call this approves
      await post('/api/chat/answer', {id: b.dataset.chatok, ok: true, digest: b.dataset.digest || (C.pending && C.pending.id === b.dataset.chatok ? C.pending.digest : undefined) || undefined}); await chatPoll(); }
    else if (b.dataset.chatchoice) { await post('/api/chat/answer', {id: b.dataset.chatchoice, ok: true, choice: b.dataset.value}); await chatPoll(); }
    else if (b.dataset.cagain) { if (!C.busy) { await post('/api/chat/send', {text: b.dataset.cagain}); await chatPoll(); } }
    else if (b.dataset.chatno) { await post('/api/chat/answer', {id: b.dataset.chatno, ok: false}); await chatPoll(); }
    else if (b.dataset.cpick) { const r = await post('/api/pick', {kind: b.dataset.cpick}); if (r.path) {
      const t = $('#ctext'); t.value = (t.value + ' "' + r.path + '"').trim(); C.draft = t.value; t.focus(); } }
  } catch (err) { alert(err.message); }
});
document.addEventListener('change', e => { if (S.view === 'chat' && e.target.id === 'clisten') {
  post('/api/chat/settings', {listen_provider: e.target.value}).then(s => { C.settings = s; C.lmodels = []; C.lopen = true; chatDraw(); }); } });
document.addEventListener('change', e => { if (S.view === 'chat' && e.target.id === 'cprov') {
  post('/api/chat/settings', {provider: e.target.value}).then(s => { C.settings = s; C.models = []; C.open = true; chatDraw(); }); } });
document.addEventListener('keydown', e => { if (S.view === 'chat' && e.target.id === 'ctext' && e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
  e.preventDefault(); const s = $('#csend'); if (s && !s.disabled) s.click(); } });
setInterval(() => { if (!document.hidden && (S.view === 'chat' || C.busy)) chatPoll().catch(() => {}); }, 1000);   // a hidden tab asks nothing (the page's own poll does the same)
chatPoll(true).catch(() => {});
