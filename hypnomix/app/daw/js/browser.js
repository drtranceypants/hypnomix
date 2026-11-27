/* Hypnomix · Browser: categories and places on top, items below, a preview strip at the bottom.
   Double-clicking an audio effect adds it to the selected track (mock; the real call is plugin_add_by_plugin_id). */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  let root, list, cats, query = '', cat = 'afx', selItem = null, prevCv;

  const ICON = {
    sounds: 'M2 9c2-6 4 6 6 0s4 6 6 0', drums: 'M3 6h10v5H3zM3 6l2-3h6l2 3', inst: 'M2 4h12v8H2zM5 4v5M8 4v5M11 4v5', afx: 'M3 12V4M8 12V4M13 12V4M1.5 9h3M6.5 6h3M11.5 10h3',
    mfx: 'M4 12V5l8-2v7M4 12a1.5 1.5 0 1 1-1.5-1.5M12 10a1.5 1.5 0 1 1-1.5-1.5', plug: 'M5 2v4M11 2v4M3 6h10v3a5 5 0 0 1-10 0zM8 14v-1', clips: 'M2 4h12v8H2zM2 7h12',
    samples: 'M2 8h1l1-3 2 7 2-9 2 8 1-3h3', hx: 'M8 2a6 6 0 1 0 0 12A6 6 0 1 0 8 2zm0 3a3 3 0 1 0 0 6 3 3 0 1 0 0-6z', proj: 'M2 4h5l1 1.5h6V13H2z', snaps: 'M3 3h10v10H3zM6 3v10', user: 'M8 8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM3 14c0-3 2.5-4.5 5-4.5s5 1.5 5 4.5',
  };
  const svg = (k) => { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 16 16'); s.innerHTML = '<path d="' + ICON[k] + '" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>'; return s; };

  HX.mountBrowser = function () {
    root = HX.$('#browser');
    root.innerHTML = '';
    const search = h('input', { placeholder: 'Search  ⌘F', 'data-info': 'Search the browser · ⌘F · Esc clears', oninput: (e) => { query = e.target.value.toLowerCase(); renderItems(); } });
    search.addEventListener('keydown', (e) => { if (e.key === 'Escape') { search.value = ''; query = ''; renderItems(); search.blur(); } });
    HX.browserSearch = search;
    cats = h('div.br-cats');
    list = h('div.br-items');
    prevCv = h('canvas');
    root.append(h('div.br-search', null, search), h('div.br-cols', null, cats, list), h('div.br-preview', { 'data-info': 'Preview of the selected item (mock)' }, h('span.label', null, 'Preview'), prevCv));
    renderCats(); renderItems();
  };

  function renderCats() {
    cats.innerHTML = '';
    cats.append(h('div.br-group.label', null, 'Categories'));
    HX.BROWSER.cats.forEach((c) => cats.append(catRow(c)));
    cats.append(h('div.br-group.label', null, 'Places'));
    HX.BROWSER.places.forEach((c) => cats.append(catRow(c)));
    // the app's Store tab (hypnomix/app/store.js): free and open-source plug-ins, instruments, drum kits, sample packs
    cats.append(h('div.br-cat', { onclick: () => HX.leavePage('/#store'), 'data-info': 'Store · get free plug-ins, instruments, drum kits and sample packs' }, svg('plug'), 'Store', h('small', null, '↗')));
  }
  function catRow(c) {
    const n = c.id === 'snaps' ? S.session.snapshots.length : c.n;
    return h('div.br-cat' + (cat === c.id ? '.on' : ''), { onclick: () => { cat = c.id; selItem = null; renderCats(); renderItems(); }, 'data-info': c.name }, svg(c.id), c.name, h('small', null, String(n)));
  }

  function items() {
    if (cat === 'snaps') return S.session.snapshots.map((s) => ({ name: s.name, sub: s.when, snap: true }));
    const raw = HX.BROWSER.items[cat] || [];
    return raw.map((n) => ({ name: n }));
  }
  function renderItems() {
    list.innerHTML = '';
    let arr = items();
    if (query) {
      // search everything when typing, grouped by category
      arr = [];
      Object.keys(HX.BROWSER.items).forEach((k) => HX.BROWSER.items[k].forEach((n) => { if (n.toLowerCase().includes(query)) arr.push({ name: n, cat: k }); }));
    }
    if (!arr.length) list.append(h('div.br-item', { style: { color: 'var(--tx3)' } }, HX.mcp.connected && !query ? 'The engine lists nothing here yet' : 'No matches'));
    let lastCat = null;
    arr.forEach((it) => {
      if (it.cat && it.cat !== lastCat) { lastCat = it.cat; const c = [...HX.BROWSER.cats, ...HX.BROWSER.places].find((c) => c.id === it.cat); list.append(h('div.br-item.folder', null, c ? c.name : it.cat)); }
      const k = it.cat || cat;
      const ico = h('i.ico' + (k === 'afx' || k === 'plug' || k === 'hx' ? '.fx' : '') + (it.snap ? '.snap' : ''));
      const row = h('div.br-item' + (selItem === it.name ? '.sel' : ''), { 'data-info': hint(k, it) }, ico, it.name, it.sub ? h('small', null, it.sub) : null);
      row.addEventListener('click', () => { selItem = it.name; HX.$$('.br-item', list).forEach((r) => r.classList.remove('sel')); row.classList.add('sel'); drawPreview(it.name); });
      row.addEventListener('dblclick', () => activate(k, it));
      list.append(row);
    });
  }
  function hint(k, it) {
    if (k === 'afx' || k === 'plug' && HX.mcp.connected || k === 'hx' && /^(hx|hypnomix) /i.test(it.name)) return it.name + ' · double-click to add to the selected track';
    if (it.name === 'Scan session…') return 'Run a HypnoMix scan and open Review';
    if (it.name === 'Vocal level check') return 'Ask the Assistant to check vocal levels';
    if (it.snap) return 'Snapshot · ' + it.sub;
    return it.name + ' · click to preview';
  }
  function activate(k, it) {
    if (it.name === 'Scan session…') return HX.runScan();
    if (it.name === 'Vocal level check') return HX.assistantAsk('Check the vocal levels line to line');
    if (HX.liveEngine && HX.liveEngine.browserActivate(k, it)) return; // a real plug-in from the engine's list
    if (k === 'afx' || (k === 'hx' && /^hx /.test(it.name))) {
      const t = HX.track(S.ui.trackId);
      const d = { id: 'd' + Date.now(), name: it.name.replace(/ \(.*\)$/, ''), kind: /EQ/.test(it.name) ? 'eq' : /Comp/.test(it.name) ? 'comp' : /Reverb/.test(it.name) ? 'reverb' : 'hx', on: true, params: [{ n: 'Amount', v: 50, min: 0, max: 100, unit: '%' }, { n: 'Mix', v: 100, min: 0, max: 100, unit: '%' }] };
      if (d.kind === 'eq') d.params = [{ n: 'Low', v: 0, min: -12, max: 12, unit: 'dB' }, { n: 'Lo-Mid', v: 0, min: -12, max: 12, unit: 'dB' }, { n: 'Hi-Mid', v: 0, min: -12, max: 12, unit: 'dB' }, { n: 'High', v: 0, min: -12, max: 12, unit: 'dB' }, { n: 'HPF', v: 20, min: 20, max: 400, unit: 'Hz', log: true }, { n: 'Output', v: 0, min: -12, max: 12, unit: 'dB' }];
      t.devices.push(d);
      HX.log(HX.mcp.connected ? 'err' : 'mock', 'plugin_add_by_plugin_id ' + JSON.stringify({ id: t.id, name: d.name }) + (HX.mcp.connected ? ' · not wired yet (needs a plug-in id from plugin_list_available)' : ''));
      HX.toast('Added ' + d.name + ' to ' + t.name);
      S.ui.bottom = 'devices'; HX.emit('devices'); HX.emit('session-light');
      return;
    }
    drawPreview(it.name);
  }
  function drawPreview(name) {
    const w = prevCv.clientWidth, hh = 18, ctx = HX.fitCanvas(prevCv, w, hh);
    const rnd = HX.rng(HX.hash(name)); ctx.clearRect(0, 0, w, hh); ctx.fillStyle = HX.css('--tx2');
    for (let x = 0; x < w; x++) { const a = (0.2 + rnd() * 0.8) * Math.exp(-x / (w * 0.6)) * (hh / 2 - 1); ctx.fillRect(x, hh / 2 - a, 1, a * 2); }
  }

  HX.on('session', () => root && (renderCats(), renderItems()));
  HX.on('browser', () => root && (renderCats(), renderItems())); // the engine's plug-in list arrived (live.js)
  HX.on('snapshots', () => { if (root) { renderCats(); if (cat === 'snaps') renderItems(); } });
  HX.showSnapshots = () => { cat = 'snaps'; renderCats(); renderItems(); };
})();
