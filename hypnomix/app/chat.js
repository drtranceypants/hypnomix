// The Assistant tab (served at /chat.js; uses the page's own helpers: $, esc, get, post, S, render).
const C = {items: [], total: 0, busy: false, pending: null, settings: null, open: false, models: [], draft: ''};

(function () {   // the tab's own look, on top of the page's styles
  const st = document.createElement('style');
  st.textContent = `#chatlog{display:flex;flex-direction:column;gap:8px;margin:14px 0;max-height:60vh;overflow:auto}
  .msg{padding:10px 12px;border-radius:10px;max-width:85%;line-height:1.45;white-space:normal}
  .msg.me{align-self:flex-end;background:var(--card);border:1px solid var(--line)}
  .msg.ai{align-self:flex-start;border:1px solid var(--line)}.msg.err{border:1px solid var(--hi);color:var(--hi)}
  .msg pre,.ask pre{white-space:pre-wrap;overflow-x:auto}.act{color:var(--mute);font-size:.9em}
  #ctext{width:100%;box-sizing:border-box;font:inherit}
  #ckey{font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);flex:1;min-width:200px}`;
  document.head.appendChild(st);
})();

async function chatPoll(full) {
  const r = await get('/api/chat/state?since=' + (full ? 0 : C.total));
  const changed = full || r.items.length || r.busy !== C.busy || JSON.stringify(r.pending) !== JSON.stringify(C.pending) || !C.settings;
  if (full || r.total < C.total) C.items = [];
  C.items.push(...r.items); C.total = r.total; C.busy = r.busy; C.pending = r.pending; C.settings = r.settings;
  if (S.view === 'chat' && changed) chatDraw();    // only when something changed: typing is never interrupted
}

function chatItem(it) {
  if (it.kind === 'user') return `<div class="msg me">${esc(it.text)}</div>`;
  if (it.kind === 'assistant') return `<div class="msg ai">${chatMd(it.text)}</div>`;
  if (it.kind === 'tool') return `<div class="act">↳ ${esc(it.text)}</div>`;
  if (it.kind === 'ask') {
    const live = C.pending && C.pending.id === it.id;
    return `<div class="card ask"><b>The assistant wants to change your project:</b><pre>${esc(it.text)}</pre>
      ${live ? `<button class="primary" data-chatok="${esc(it.id)}">Run it</button> <button data-chatno="${esc(it.id)}">Don't</button>
        <span class="note">It writes a new set next to the original. Save and close the set in Live first.</span>`
        : `<span class="note">${it.answer === 'ran' ? 'You ran it.' : 'Not run.'}</span>`}</div>`;
  }
  if (it.kind === 'error') return `<div class="msg err">${esc(it.text)}</div>`;
  return `<div class="act">${esc(it.text)}</div>`;
}

// a small, safe subset of markdown: code, bold, line breaks, bullet lines
function chatMd(t) {
  let h = esc(t);
  h = h.replace(/```([\s\S]*?)```/g, (m, c) => `<pre>${c.replace(/^\w*\n/, '')}</pre>`);
  h = h.replace(/`([^`\n]+)`/g, '<code>$1</code>').replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
  h = h.split('\n').map(l => /^\s*[-*] /.test(l) ? '• ' + l.replace(/^\s*[-*] /, '') : l).join('<br>');
  return h.replace(/<br>(<pre>)/g, '$1').replace(/(<\/pre>)<br>/g, '$1');
}

function chatSettings() {
  const st = C.settings; if (!st) return '';
  const p = st.providers.find(x => x.id === st.provider) || st.providers[0];
  const opts = st.providers.map(x => `<option value="${x.id}" ${x.id === p.id ? 'selected' : ''}>${esc(x.label)}</option>`).join('');
  const needsBase = p.id === 'custom' || p.id === 'ollama';
  return `<div class="card"><div class="row"><label for="cprov">AI provider</label><select id="cprov">${opts}</select></div>
    ${p.no_key ? '<div class="row note">No key needed: Ollama runs models on this computer (ollama.com).</div>' :
      `<div class="row"><label for="ckey">API key</label><input type="password" id="ckey" placeholder="${p.key_hint ? 'saved (' + esc(p.key_hint) + '): paste to replace' : 'paste your key'}" autocomplete="off">
      ${p.key_hint ? '<button id="cforget">Forget key</button>' : ''}</div>
      <div class="row note">${p.keys_at ? 'Get a key at ' + esc(p.keys_at) + '. ' : ''}Kept on this computer only, and sent only to ${esc(p.label)}. Your audio never leaves this computer.</div>`}
    ${needsBase ? `<div class="row"><label for="cbase">Address</label><input type="text" id="cbase" value="${esc(p.base_url)}" placeholder="https://…/v1"></div>` : ''}
    <div class="row"><label for="cmodel">Model</label><input type="text" id="cmodel" list="cmodels" value="${esc(p.model)}" placeholder="choose with List models">
      <datalist id="cmodels">${C.models.map(m => `<option value="${esc(m)}">`).join('')}</datalist><button id="clist">List models</button></div>
    <div class="row"><button class="primary" id="csave">Save</button> <span class="note" id="csaved"></span></div></div>`;
}

function chatView() {
  const st = C.settings, p = st && (st.providers.find(x => x.id === st.provider));
  const ready = p && (p.no_key || p.key_hint) && p.model;
  return `<h1>Assistant</h1>
  <p class="sub">Talk about your song and let an AI run hypnomix for you. Bring a key from the AI service you like.
  It reads hypnomix's reports, never your audio, and anything that changes a set waits for your click.</p>
  ${!ready || C.open ? chatSettings() : `<p class="note">${esc(p.label)} · ${esc(p.model)} <button id="copen">Settings</button> <button id="creset">New conversation</button></p>`}
  <div id="chatlog" aria-live="polite">${C.items.map(chatItem).join('') ||
    '<p class="note">Try: "Do a first pass on my song" (attach the set below), "What does the review say about the vocals?", or "Apply what I approved".</p>'}
    ${C.busy && !C.pending ? '<div class="act"><span class="spin"></span>working…</div>' : ''}</div>
  <div class="card"><textarea id="ctext" rows="3" placeholder="${ready ? 'Ask, or tell it what to do…' : 'Add a key and a model above first'}">${esc(C.draft)}</textarea>
    <div class="row"><button class="primary" id="csend" ${ready && !C.busy ? '' : 'disabled'}>Send</button>
      <button data-cpick="set">Attach a set…</button><button data-cpick="folder">Attach a folder…</button><button data-cpick="audio">Attach audio…</button>
      ${C.busy ? '<button id="cstop">Stop</button>' : ''}</div></div>`;
}

function chatDraw() {
  const t = $('#ctext'); if (t) C.draft = t.value;
  const focus = document.activeElement && document.activeElement.id;
  const m = $('#main'); if (!m) return;
  m.innerHTML = chatView();
  const log = $('#chatlog'); if (log) log.scrollTop = log.scrollHeight;
  if (focus && $('#' + focus)) $('#' + focus).focus();
}

async function chatSaveSettings() {
  const body = {provider: $('#cprov').value};
  if ($('#cmodel')) body.model = $('#cmodel').value;
  if ($('#cbase')) body.base_url = $('#cbase').value;
  if ($('#ckey') && $('#ckey').value) body.key = $('#ckey').value;
  C.settings = await post('/api/chat/settings', body);
}

document.addEventListener('click', async e => {
  if (S.view !== 'chat') return;
  const b = e.target.closest('button'); if (!b) return;
  try {
    if (b.id === 'csave') { await chatSaveSettings(); C.open = false; chatDraw(); }
    else if (b.id === 'copen') { C.open = true; chatDraw(); }
    else if (b.id === 'cforget') { C.settings = await post('/api/chat/settings', {provider: $('#cprov').value, forget: true}); chatDraw(); }
    else if (b.id === 'clist') { await chatSaveSettings(); const r = await post('/api/chat/models', {}); C.models = r.models || []; chatDraw();
      const s = $('#csaved'); if (s) s.textContent = C.models.length + ' models: pick one in the Model box'; }
    else if (b.id === 'creset') { await post('/api/chat/reset', {}); C.draft = ''; await chatPoll(true); }
    else if (b.id === 'csend') { const t = $('#ctext').value.trim(); if (!t) return; C.draft = ''; $('#ctext').value = '';
      await post('/api/chat/send', {text: t}); await chatPoll(); }
    else if (b.id === 'cstop') { await post('/api/chat/stop', {}); }
    else if (b.dataset.chatok) { await post('/api/chat/answer', {id: b.dataset.chatok, ok: true}); await chatPoll(); }
    else if (b.dataset.chatno) { await post('/api/chat/answer', {id: b.dataset.chatno, ok: false}); await chatPoll(); }
    else if (b.dataset.cpick) { const r = await post('/api/pick', {kind: b.dataset.cpick}); if (r.path) {
      const t = $('#ctext'); t.value = (t.value + ' "' + r.path + '"').trim(); C.draft = t.value; t.focus(); } }
  } catch (err) { alert(err.message); }
});
document.addEventListener('change', e => { if (S.view === 'chat' && e.target.id === 'cprov') {
  post('/api/chat/settings', {provider: e.target.value}).then(s => { C.settings = s; C.models = []; C.open = true; chatDraw(); }); } });
document.addEventListener('keydown', e => { if (S.view === 'chat' && e.target.id === 'ctext' && e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
  e.preventDefault(); const s = $('#csend'); if (s && !s.disabled) s.click(); } });
setInterval(() => { if (S.view === 'chat' || C.busy) chatPoll().catch(() => {}); }, 1000);
chatPoll(true).catch(() => {});
