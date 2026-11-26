/* Hypnomix · Arrangement view. Lanes are one canvas (redrawn only when something changes);
   the playhead is a 1px element moved with transform every frame. Track headers sit on the right, as in Live. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  const GAP = 6, TOP_OVW = 14, TOP_SEC = 18, TOP_BAR = 20, TOP_H = TOP_OVW + TOP_SEC + TOP_BAR;
  const A = (HX.arrange = { follow: true, dirty: true });
  let root, topCv, lanesWrap, lanesCv, headers, ph, phTop, body, hdrRefs = {}, colors = {};

  HX.on('theme', readColors);
  function readColors() {
    ['--bg0', '--bg1', '--bg2', '--bg3', '--grid1', '--grid2', '--tx0', '--tx1', '--tx2', '--tx3', '--acc', '--acc-2', '--ai', '--ai-2', '--line', '--line2', '--bad', '--warn'].forEach((k) => (colors[k] = HX.css(k)));
    colors.light = document.documentElement.dataset.theme === 'light';
    A.dirty = true;
  }

  const rows = () => {
    const out = []; let y = 0;
    S.session.tracks.forEach((t) => { out.push({ t, y, hgt: t.height }); y += t.height; });
    y += GAP;
    S.session.returns.forEach((t) => { out.push({ t, y, hgt: t.height }); y += t.height; });
    out.push({ t: S.session.master, y, hgt: S.session.master.height }); y += S.session.master.height;
    out.total = y;
    return out;
  };
  const X = (beat) => (beat - S.ui.scrollX) * S.ui.zoom;
  const B = (x) => x / S.ui.zoom + S.ui.scrollX;
  const snapBeats = () => (S.ui.zoom < 5 ? 4 : S.ui.zoom < 16 ? 1 : 0.25);

  HX.mountArrange = function () {
    root = HX.$('#viewArrange');
    root.innerHTML = '';
    readColors();
    topCv = h('canvas');
    phTop = h('div.playhead.ruler');
    const topLeft = h('div', { style: { position: 'relative', overflow: 'hidden' } }, topCv, phTop);
    const tools = h('div.arr-tools', null,
      h('button.btn.ghost', { 'aria-label': 'Zoom out', 'data-info': 'Zoom out · −', onclick: () => zoomBy(1 / 1.4) }, '−'),
      h('button.btn.ghost', { 'aria-label': 'Zoom in', 'data-info': 'Zoom in · +', onclick: () => zoomBy(1.4) }, '+'),
      h('button.btn.ghost', { 'data-info': 'Zoom to fit the song · Z', onclick: () => HX.zoomFit() }, 'Fit'),
      h('button.btn.ghost#followBtn', { 'data-info': 'Follow playhead · F', onclick: () => { A.follow = !A.follow; syncFollow(); } }, 'Follow'),
      h('button.btn.ghost#importBtn', { style: { marginLeft: 'auto' }, 'data-info': 'Import audio: type or paste file paths, or drop files from the Finder onto the lanes (onto a track, or below the tracks for new ones)', onclick: openImport }, 'Import…'));
    root.append(h('div.arr-top', null, topLeft, tools));
    lanesCv = h('canvas');
    ph = h('div.playhead');
    lanesWrap = h('div.arr-lanes', null, lanesCv, ph);
    headers = h('div.arr-headers');
    body = h('div.arr-body', null, h('div.arr-grid', null, lanesWrap, headers));
    root.append(body);
    bindLanes(); bindTop();
    body.addEventListener('scroll', () => { A.dirty = true; }, { passive: true });   // only the rows in view are drawn: the ones scrolled in need drawing
    new ResizeObserver(() => { A.dirty = true; if (!A.fitted && lanesWrap.clientWidth > 0) { A.fitted = true; HX.zoomFit(); } }).observe(lanesWrap);
    renderHeaders();
    syncFollow();
  };
  function syncFollow() { const b = HX.$('#followBtn'); if (b) b.classList.toggle('on', A.follow); b && (b.style.color = A.follow ? 'var(--acc)' : ''); }

  function zoomBy(f, anchorX) {
    const w = lanesWrap.clientWidth;
    const ax = anchorX == null ? (HX.T.playing ? X(HX.pos()) : w / 2) : anchorX;
    const beatAt = B(ax);
    S.ui.zoom = HX.clamp(S.ui.zoom * f, 0.25, 96);
    S.ui.scrollX = beatAt - ax / S.ui.zoom;
    clampScroll(); A.dirty = true; HX.peaks.hold();
  }
  HX.zoomBy = zoomBy;
  HX.zoomFit = function () { const w = lanesWrap.clientWidth || 800; S.ui.zoom = HX.clamp((w - 8) / S.session.lengthBeats, 0.25, 96); S.ui.scrollX = 0; A.dirty = true; };
  function clampScroll() { const w = lanesWrap.clientWidth || 800; S.ui.scrollX = HX.clamp(S.ui.scrollX, 0, Math.max(0, S.session.lengthBeats - w / S.ui.zoom + 8)); }
  HX.scrollToBeat = function (beat) {
    const w = lanesWrap.clientWidth;
    if (X(beat) < 0 || X(beat) > w * 0.9) { S.ui.scrollX = beat - (w * 0.2) / S.ui.zoom; clampScroll(); A.dirty = true; }
  };

  /* ── headers (DOM) ── */
  function renderHeaders() {
    for (const id in hdrRefs) HX.unwatchVisible(hdrRefs[id].meter);
    headers.innerHTML = ''; hdrRefs = {};
    S.session.tracks.forEach((t) => headers.append(header(t)));
    headers.append(h('div.lane-gap'));
    S.session.returns.forEach((t) => headers.append(header(t, 'return')));
    headers.append(header(S.session.master, 'master'));
    A.dirty = true;
  }
  HX.renderArrangeHeaders = renderHeaders;

  function header(t, cls) {
    const r = {};
    const el = h('div.th' + (cls ? '.' + cls : ''), { style: { height: t.height + 'px' }, role: 'group', 'aria-label': t.name, tabindex: '0', onpointerdown: () => HX.select(t.id),
      onkeydown: (e) => { if (e.target === el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); HX.select(t.id); } } });
    r.el = el;
    r.meter = h('canvas.meter-v');
    HX.watchVisible(r.meter);
    const sub = t.isMaster ? 'Out 1/2 · ' + S.session.sampleRate / 1000 + ' kHz' : t.isReturn ? 'Return A · ' + t.devices.length + ' devices' : (t.kind === 'midi' ? 'MIDI · ' : 'Audio · ') + t.devices.length + ' devices';
    const name = h('div.th-name', { ondblclick: () => { t.height = t.height > 36 ? 30 : 52; renderHeaders(); }, 'data-info': t.name + ' · double-click to resize the lane' }, h('b', null, t.name), h('small', null, sub));
    const ctl = h('div.th-ctl');
    if (!t.isMaster) {
      r.m = h('button.tog.m', { 'data-info': 'Mute ' + t.name + ' · M on the selected track', 'aria-label': 'Mute ' + t.name, onclick: (e) => { e.stopPropagation(); HX.edit({ trackId: t.id, param: 'mute' }, !t.mute, (t.mute ? 'Unmute ' : 'Mute ') + t.name); } }, 'M');
      r.s = h('button.tog.s', { 'data-info': 'Solo ' + t.name + ' · S on the selected track', 'aria-label': 'Solo ' + t.name, onclick: (e) => { e.stopPropagation(); HX.edit({ trackId: t.id, param: 'solo' }, !t.solo, (t.solo ? 'Unsolo ' : 'Solo ') + t.name); } }, 'S');
      ctl.append(r.m, r.s);
      if (!t.isReturn) { r.r = h('button.tog.r', { 'data-info': 'Arm ' + t.name + ' for recording', 'aria-label': 'Record arm ' + t.name, onclick: (e) => { e.stopPropagation(); HX.edit({ trackId: t.id, param: 'arm' }, !t.arm, (t.arm ? 'Disarm ' : 'Arm ') + t.name); } }, '●'); ctl.append(r.r); }
    }
    const ctl2 = h('div.th-ctl2');
    r.vol = h('span.val', { 'data-info': 'Volume (dB) · drag, shift = fine, double-click = 0 dB' });
    HX.bindDrag(r.vol, () => ({ trackId: t.id, param: 'fader' }), { toPos: HX.dbToPos, fromPos: (p) => Math.round(HX.posToDb(p) * 10) / 10, sens: 0.004, reset: 0, label: (op, v) => t.name + ' volume ' + HX.fmtDb(v) + ' dB' });
    ctl2.append(r.vol);
    if (!t.isMaster) {
      r.pan = h('span.val', { style: { minWidth: '34px' }, 'data-info': 'Pan · drag, double-click = centre' });
      HX.bindDrag(r.pan, () => ({ trackId: t.id, param: 'pan' }), { min: -1, max: 1, sens: 0.01, step: 0.02, reset: 0, label: (op, v) => t.name + ' pan ' + HX.fmtPan(v) });
      ctl2.append(r.pan);
    }
    if (t.sends.length) {
      r.send = h('span.val', { style: { minWidth: '40px' }, 'data-info': 'Send to ' + t.sends[0].name + ' (dB)' });
      HX.bindDrag(r.send, () => ({ trackId: t.id, param: 'send', key: t.sends[0].index }), { toPos: HX.dbToPos, fromPos: (p) => Math.round(HX.posToDb(p) * 10) / 10, sens: 0.004, reset: -193, label: (op, v) => t.name + ' → ' + t.sends[0].name + ' ' + HX.fmtDb(v) + ' dB' });
      ctl2.append(h('span.label', null, 'A'), r.send);
    }
    el.append(h('i.chip', { style: { background: t.color } }), name, ctl, r.meter);
    if (t.height > 36) el.append(ctl2);
    hdrRefs[t.id] = r;
    syncHeader(t);
    return el;
  }
  function syncHeader(t) {
    const r = hdrRefs[t.id]; if (!r) return;
    r.el.classList.toggle('sel', S.ui.trackId === t.id);
    r.vol.textContent = HX.fmtDb(t.faderDb);
    if (r.pan) r.pan.textContent = HX.fmtPan(t.pan);
    if (r.send) r.send.textContent = HX.fmtDb(t.sends[0].db);
    r.m && (r.m.classList.toggle('on', t.mute), r.m.setAttribute('aria-pressed', String(!!t.mute)));
    r.s && (r.s.classList.toggle('on', t.solo), r.s.setAttribute('aria-pressed', String(!!t.solo)));
    r.r && (r.r.classList.toggle('on', t.arm), r.r.setAttribute('aria-pressed', String(!!t.arm)));
    ['vol', 'pan', 'send'].forEach((k) => r[k] && r[k].classList.toggle('ai', !!(HX.preview && HX.preview.touches(t.id, k))));
  }
  HX.on('param', (op) => { const t = HX.track(op.trackId); if (t) syncHeader(t); if (/^(clip|mute|solo)/.test(op.param)) A.dirty = true; });
  HX.on('select', () => { HX.allTracks().forEach(syncHeader); A.dirty = true; });
  HX.on('preview', () => { HX.allTracks().forEach(syncHeader); A.dirty = true; });
  HX.on('findings', () => (A.dirty = true));

  /* ── drawing ── */
  function draw() {
    const w = lanesWrap.clientWidth;
    const R = rows();
    const ctx = HX.fitCanvas(lanesCv, w, R.total);
    const z = S.ui.zoom, sx = S.ui.scrollX;
    /* the canvas is as tall as every track; only the rows in view (and a little around them) are drawn, which keeps a
       redraw of a 200-track session about as cheap as one of ten */
    const vTop = body ? body.scrollTop - 120 : 0, vBot = body ? body.scrollTop + body.clientHeight + 120 : R.total;
    const inView = (r) => r.y + r.hgt >= vTop && r.y <= vBot;
    ctx.fillStyle = colors['--bg0']; ctx.fillRect(0, 0, w, R.total);
    // selected lane tint + lane separators
    R.forEach((r) => {
      if (!inView(r)) return;
      if (r.t.id === S.ui.trackId) { ctx.fillStyle = colors.light ? 'rgba(0,0,0,.035)' : 'rgba(255,255,255,.025)'; ctx.fillRect(0, r.y, w, r.hgt); }
      ctx.fillStyle = colors['--line']; ctx.fillRect(0, r.y + r.hgt - 1, w, 1);
    });
    // returns gap
    const gy = R.find((r) => r.t.isReturn || r.t.isMaster).y - GAP;
    ctx.fillStyle = colors['--bg1']; ctx.fillRect(0, gy, w, GAP);
    // grid
    const b0 = Math.floor(sx), b1 = Math.ceil(B(w));
    let gEvery = 1; while (gEvery * 4 * z < 10) gEvery *= 2; // zoomed far out: every 2nd, 4th… bar, never a solid wash
    for (let b = b0; b <= b1; b++) {
      const x = Math.round(X(b)) + 0.5;
      if (b % 4 === 0) { if ((b / 4) % gEvery) continue; ctx.fillStyle = (b / 4) % (4 * gEvery) === 0 ? colors['--grid2'] : colors['--grid1']; ctx.fillRect(x, 0, 1, R.total); }
      else if (z > 14) { ctx.fillStyle = colors['--grid1']; ctx.globalAlpha = 0.5; ctx.fillRect(x, 0, 1, R.total); ctx.globalAlpha = 1; }
    }
    // loop
    const L = S.session.loop;
    if (L.on) { ctx.fillStyle = colors['--acc-2']; ctx.globalAlpha = 0.35; ctx.fillRect(X(L.start), 0, (L.end - L.start) * z, R.total); ctx.globalAlpha = 1; }
    // clips
    R.forEach((r) => inView(r) && r.t.clips.forEach((c) => {
      const x0 = X(c.start), x1 = X(c.start + c.len);
      if (x1 < 0 || x0 > w) return;
      drawClip(ctx, r.t, c, x0, r.y + 1, x1 - x0, r.hgt - 2);
    }));
    // review findings: thin violet ticks on their lanes
    if (S.findings.length && S.ui.view === 'arrange') S.findings.forEach((f) => {
      if (f.status === 'skipped') return;
      const r = R.find((r) => r.t.id === f.track); if (!r || !inView(r)) return;
      const x = Math.round(X(f.at)) + 0.5;
      ctx.fillStyle = f.status === 'approved' ? HX.css('--ok') : colors['--ai'];
      ctx.beginPath(); ctx.moveTo(x - 4, r.y + 1); ctx.lineTo(x + 4, r.y + 1); ctx.lineTo(x, r.y + 6); ctx.fill();
    });
    drawTop(w);
  }

  function drawClip(ctx, t, c, x, y, w, hgt) {
    const sel = S.ui.clipId === c.id;
    const head = hgt > 34 ? 12 : 0;
    const muted = c.muted || t.mute;
    const col = muted ? colors['--tx3'] : t.color;
    const prev = HX.preview && HX.preview.clipGain(c.id);
    ctx.save();
    ctx.beginPath(); ctx.rect(Math.max(x, -2), y, Math.min(w, lanesCv.width) + 4, hgt); ctx.clip();
    // body
    ctx.globalAlpha = colors.light ? 0.30 : 0.2; ctx.fillStyle = col; ctx.fillRect(x, y, w, hgt); ctx.globalAlpha = 1;
    if (head) {
      ctx.fillStyle = col; ctx.fillRect(x, y, w, head);
      ctx.fillStyle = 'rgba(0,0,0,.78)'; ctx.font = '600 9.5px ' + HX.css('--ui');
      ctx.textBaseline = 'middle';
      const label = c.name + (c.gainDb ? '  ' + (c.gainDb > 0 ? '+' : '') + c.gainDb.toFixed(1) + ' dB' : '') + (c.muted ? '  · muted' : '') + (c.building ? '  · the engine is building its waveform…' : c.loading ? '  · reading peaks…' : c.peakErr ? '  · no waveform: ' + c.peakErr : '');
      ctx.fillText(label, Math.max(x, 0) + 4, y + head / 2 + 0.5);
    }
    const by = y + head, bh = hgt - head;
    const ink = colors.light ? shade(col, 0.42) : col; // waveforms need more contrast on the pale body
    if (c.kind === 'midi') drawNotes(ctx, c, x, by, w, bh, ink);
    else drawWave(ctx, c, x, by, w, bh, ink, prev);
    // fades: the faded corner is shaded, and the selected or hovered clip shows its handles (drag them)
    ctx.strokeStyle = colors.light ? 'rgba(0,0,0,.35)' : 'rgba(255,255,255,.35)'; ctx.lineWidth = 1;
    const fi = c.fadeIn * S.ui.zoom, fo = c.fadeOut * S.ui.zoom;
    ctx.fillStyle = colors.light ? 'rgba(0,0,0,.07)' : 'rgba(0,0,0,.22)';
    if (fi > 2) { ctx.beginPath(); ctx.moveTo(x, by + bh); ctx.lineTo(x + fi, by); ctx.lineTo(x, by); ctx.fill(); ctx.beginPath(); ctx.moveTo(x, by + bh); ctx.lineTo(x + fi, by); ctx.stroke(); }
    if (fo > 2) { ctx.beginPath(); ctx.moveTo(x + w - fo, by); ctx.lineTo(x + w, by + bh); ctx.lineTo(x + w, by); ctx.fill(); ctx.beginPath(); ctx.moveTo(x + w - fo, by); ctx.lineTo(x + w, by + bh); ctx.stroke(); }
    if (c.kind === 'audio' && (sel || A.hover === c.id) && w > 16) {
      ctx.fillStyle = colors['--tx0'];
      ctx.fillRect(Math.round(x + Math.max(fi, 2)) - 2, by, 5, 5);
      ctx.fillRect(Math.round(x + w - Math.max(fo, 2)) - 3, by, 5, 5);
    }
    ctx.restore();
    // outline
    ctx.strokeStyle = sel ? colors['--tx0'] : prev != null ? colors['--ai'] : 'rgba(0,0,0,.35)';
    ctx.lineWidth = sel || prev != null ? 1.5 : 1;
    ctx.strokeRect(Math.round(x) + 0.5, y + 0.5, Math.round(w) - 1, hgt - 1);
  }

  const shadeCache = {};
  function shade(hex, f) {
    const k = hex + f; if (shadeCache[k]) return shadeCache[k];
    const n = parseInt(hex.slice(1), 16), r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    return (shadeCache[k] = 'rgb(' + Math.round(r * (1 - f)) + ',' + Math.round(g * (1 - f)) + ',' + Math.round(b * (1 - f)) + ')');
  }
  /* a region on the engine: min/max from region_get_peaks at a resolution matched to the zoom (js/regions.js
     fetches the tiles the view asks for), the coarse pass while they load */
  function drawRealWave(ctx, c, x, w, mid, half, g, xa, xb) {
    const spbv = (S.session.sampleRate * 60) / S.session.tempo, sppA = spbv / S.ui.zoom;
    const spp = HX.peaks.level(sppA), TILE = HX.peaks.TILE, res = c.pres || HX.PEAK_RES, P = c.peaks;
    const shift = (c.offS || 0) - HX.peaks.origin(c.id);          // a front trim being dragged
    const s0 = (xa - x) * sppA + shift, s1 = (xb - x) * sppA + shift;
    HX.peaks.want(c, spp, Math.max(0, s0), Math.min(c.lenS, s1));
    let tile = null, tIdx = -1;
    ctx.globalAlpha = 0.9;
    for (let px = xa; px < xb; px++) {
      const a = (px - x) * sppA + shift, b = a + sppA;
      if (a < 0) continue;
      const i0 = Math.floor(a / spp), i1 = Math.max(i0 + 1, Math.floor(b / spp));
      let lo = 0, hi = 0, got = false;
      for (let i = i0; i < i1; i++) {
        const ti = (i / TILE) | 0;
        if (ti !== tIdx) { tIdx = ti; tile = HX.peaks.tile(c.id, spp, ti); }
        if (!tile) { got = false; break; }
        const j = i - ti * TILE; if (j >= tile.n) break;
        if (!got || tile.lo[j] < lo) lo = tile.lo[j];
        if (!got || tile.hi[j] > hi) hi = tile.hi[j];
        got = true;
      }
      if (!got && P) {                                             // not fetched yet: the coarse pass, mirrored
        const k0 = Math.floor((a / spbv) * res), k1 = Math.max(k0 + 1, Math.floor((b / spbv) * res));
        let m = 0; for (let k = k0; k < k1 && k < P.length; k++) if (P[k] > m) m = P[k];
        lo = -m; hi = m;
      }
      const top = mid - Math.min(1, hi * g) * half, bot = mid - Math.max(-1, lo * g) * half;
      ctx.fillRect(px, top, 1, Math.max(1, bot - top));
    }
    ctx.globalAlpha = 1;
  }

  function gainLineY(db, y, hgt) { return y + hgt * (1 - HX.clamp(HX.dbToPos(db), 0, 1) * 0.92); }

  function drawWave(ctx, c, x, y, w, hgt, col, prevGain) {
    const z = S.ui.zoom, res = HX.PEAK_RES, P = c.peaks;
    const g = HX.dbToGain(prevGain != null ? prevGain : c.gainDb || 0);
    const mid = y + hgt / 2, half = hgt / 2 - 1;
    const xa = Math.max(0, Math.floor(x)), xb = Math.min(lanesCv.clientWidth || 4000, Math.ceil(x + w));
    const perPx = res / z, off = Math.round((c.offs || 0) * res);  // a trimmed mock clip starts later in its audio
    ctx.fillStyle = col;
    if (c.real) drawRealWave(ctx, c, x, w, mid, half, g, xa, xb);
    else for (let px = xa; px < xb; px++) {
      const i0 = off + Math.floor((px - x) * perPx), i1 = Math.max(i0 + 1, off + Math.floor((px + 1 - x) * perPx));
      let m = 0, sum = 0, n = 0;
      for (let i = i0; i < i1 && i < P.length; i++) { const v = P[i]; if (v > m) m = v; sum += v * v; n++; }
      if (!n) continue;
      const pk = Math.min(1, m * g) * half, rms = Math.min(1, Math.sqrt(sum / n) * 0.72 * g) * half;
      ctx.globalAlpha = 0.5; ctx.fillRect(px, mid - pk, 1, pk * 2 || 1);
      ctx.globalAlpha = 1; ctx.fillRect(px, mid - rms, 1, rms * 2 || 1);
    }
    ctx.globalAlpha = 1;
    const showLine = g > 1.0001 || g < 0.9999, hover = A.hover === c.id || S.ui.clipId === c.id;
    if (showLine || hover) { // clip gain line (drag it up or down)
      ctx.fillStyle = prevGain != null ? colors['--ai'] : colors['--tx0'];
      const gy = gainLineY(prevGain != null ? prevGain : c.gainDb || 0, y, hgt);
      ctx.globalAlpha = showLine ? 0.7 : 0.25; ctx.fillRect(x, Math.round(gy), w, 1); ctx.globalAlpha = 1;
    }
  }

  function drawNotes(ctx, c, x, y, w, hgt, col) {
    if (!c.notes.length) return;
    let lo = 127, hi = 0; c.notes.forEach((n) => { lo = Math.min(lo, n.pitch); hi = Math.max(hi, n.pitch); });
    const span = Math.max(12, hi - lo + 2), nh = Math.max(1.5, (hgt - 4) / span);
    ctx.fillStyle = col;
    c.notes.forEach((n) => {
      const nx = x + n.t * S.ui.zoom, nw = Math.max(1, n.len * S.ui.zoom - 1);
      if (nx > lanesCv.clientWidth || nx + nw < 0) return;
      const ny = y + 2 + (hi + 1 - n.pitch) * ((hgt - 4) / span);
      ctx.globalAlpha = 0.45 + (n.vel / 127) * 0.55;
      ctx.fillRect(nx, ny, nw, nh);
    });
    ctx.globalAlpha = 1;
  }

  /* overview + sections + bar ruler */
  function drawTop(w) {
    const ctx = HX.fitCanvas(topCv, w, TOP_H);
    const z = S.ui.zoom, L = S.session.lengthBeats;
    ctx.fillStyle = colors['--bg1']; ctx.fillRect(0, 0, w, TOP_H);
    // overview: every track as a 1px row of its clips
    ctx.fillStyle = colors['--bg0']; ctx.fillRect(0, 0, w, TOP_OVW);
    const ow = w / L, tr = S.session.tracks, rh = Math.max(1, (TOP_OVW - 3) / tr.length);
    tr.forEach((t, i) => { ctx.fillStyle = t.color; ctx.globalAlpha = 0.75; t.clips.forEach((c) => ctx.fillRect(c.start * ow, 1.5 + i * rh, Math.max(1, c.len * ow), Math.max(1, rh - 0.5))); });
    ctx.globalAlpha = 1;
    const vx = S.ui.scrollX * ow, vw = (w / z) * ow;
    ctx.strokeStyle = colors['--tx1']; ctx.lineWidth = 1; ctx.strokeRect(Math.round(vx) + 0.5, 0.5, Math.max(4, Math.round(vw) - 1), TOP_OVW - 1);
    ctx.fillStyle = colors['--line']; ctx.fillRect(0, TOP_OVW, w, 1);
    // sections
    ctx.font = '600 10px ' + HX.css('--ui'); ctx.textBaseline = 'middle';
    S.session.sections.forEach((s, i) => {
      const x0 = X(s.start), x1 = X(s.start + s.len);
      if (x1 < 0 || x0 > w) return;
      ctx.fillStyle = i % 2 ? colors['--bg2'] : colors['--bg3'];
      ctx.fillRect(x0, TOP_OVW + 1, x1 - x0 - 1, TOP_SEC - 2);
      ctx.fillStyle = colors['--tx1'];
      ctx.save(); ctx.beginPath(); ctx.rect(x0, TOP_OVW, x1 - x0 - 2, TOP_SEC); ctx.clip();
      ctx.fillText(s.name, Math.max(x0, 0) + 5, TOP_OVW + TOP_SEC / 2);
      ctx.restore();
    });
    // loop brace
    const Lp = S.session.loop, ly = TOP_OVW + TOP_SEC;
    ctx.fillStyle = Lp.on ? colors['--acc'] : colors['--tx3']; ctx.globalAlpha = Lp.on ? 0.9 : 0.35;
    ctx.fillRect(X(Lp.start), ly, (Lp.end - Lp.start) * z, 3); ctx.globalAlpha = 1;
    // bars
    const minPx = 34; let every = 1; while (every * 4 * z < minPx) every *= 2;
    ctx.font = '500 9.5px ' + HX.css('--mono'); ctx.textBaseline = 'alphabetic';
    for (let bar = Math.floor(S.ui.scrollX / 4); bar * 4 < B(w); bar++) {
      const x = Math.round(X(bar * 4)) + 0.5;
      const major = bar % every === 0;
      ctx.fillStyle = major ? colors['--tx2'] : colors['--tx3'];
      ctx.fillRect(x, TOP_H - (major ? 8 : 4), 1, major ? 8 : 4);
      if (major) { ctx.fillStyle = colors['--tx1']; ctx.fillText(String(bar + 1), x + 3, TOP_H - 6); }
    }
    // findings markers in the ruler
    S.findings.forEach((f) => {
      if (f.status === 'skipped') return;
      const x = X(f.at); if (x < -4 || x > w + 4) return;
      ctx.fillStyle = f.sev === 'high' ? colors['--bad'] : f.sev === 'med' ? colors['--warn'] : colors['--tx2'];
      ctx.beginPath(); ctx.moveTo(x, ly + 4); ctx.lineTo(x + 3.5, ly + 7.5); ctx.lineTo(x, ly + 11); ctx.lineTo(x - 3.5, ly + 7.5); ctx.fill();
    });
    ctx.fillStyle = colors['--line']; ctx.fillRect(0, TOP_H - 1, w, 1);
  }

  /* ── interaction ── */
  function bindLanes() {
    lanesWrap.addEventListener('wheel', (e) => {
      if (e.ctrlKey || e.metaKey) { e.preventDefault(); const r = lanesWrap.getBoundingClientRect(); zoomBy(Math.exp(-e.deltaY * 0.01), e.clientX - r.left); return; }
      const dx = e.shiftKey ? e.deltaY : e.deltaX;
      if (Math.abs(dx) > 0.5) { e.preventDefault(); S.ui.scrollX += dx / S.ui.zoom; clampScroll(); A.dirty = true; HX.peaks.hold(); }
    }, { passive: false });
    lanesWrap.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      const rect = lanesWrap.getBoundingClientRect();
      const x = e.clientX - rect.left, y = e.clientY - rect.top;
      const hit = hitAt(x, y);
      if (!hit) return;
      const { row, c, zone } = hit;
      HX.select(row.t.id, c && c.id);
      if (!c) { HX.locate(snap(hit.beat)); return; }
      lanesWrap.setPointerCapture(e.pointerId);
      const free = (ev) => ev.metaKey || ev.altKey;              // hold ⌘ (or ⌥) while dragging: no snapping
      const sn = (b, ev) => (free(ev) ? b : snap(b));
      const bx = (ev) => B(ev.clientX - rect.left);
      let moved = false, mv, up;
      if (zone === 'move') {
        const grabOff = hit.beat - c.start, from = row.t, before = { trackId: from.id, start: c.start };
        const op = { trackId: from.id, param: 'regionMove', key: c.id };
        mv = (ev) => {
          if (Math.abs(ev.clientX - e.clientX) > 3 || Math.abs(ev.clientY - e.clientY) > 6) moved = true;
          if (!moved) return;
          const r = rows().find((r) => { const yy = ev.clientY - rect.top; return yy >= r.y && yy < r.y + r.hgt; });
          const cur = HX.findClip(c.id); if (!cur) return;
          const to = r && canHold(r.t, c) ? r.t.id : cur.track.id;
          HX.setLocal(op, { trackId: to, start: Math.max(0, sn(bx(ev) - grabOff, ev)) });
        };
        up = () => {
          const cur = HX.findClip(c.id);
          if (!moved) { HX.locate(snap(hit.beat)); return; }     // a click sets the playhead (where ⌘E splits)
          const after = cur && { trackId: cur.track.id, start: c.start };
          if (after && (after.trackId !== before.trackId || Math.abs(after.start - before.start) > 1e-9))
            HX.commit('Move ' + c.name + (after.trackId !== before.trackId ? ' to ' + HX.track(after.trackId).name : ''), [Object.assign({}, op, { before, after })]);
        };
      } else if (zone === 'trimL' || zone === 'trimR') {
        const before = { start: c.start, len: c.len }, end = c.start + c.len, minLen = 1 / 16;
        const srcStart = c.real ? 0 : c.start - (c.offs || 0);                     // a mock clip cannot reach before its audio
        const srcEnd = c.real || !c.peaks ? Infinity : c.start - (c.offs || 0) + c.peaks.length / HX.PEAK_RES;
        const op = { trackId: row.t.id, param: 'regionTrim', key: c.id };
        mv = (ev) => {
          moved = true;
          if (zone === 'trimL') { const ns = HX.clamp(sn(bx(ev), ev), Math.max(0, srcStart), end - minLen); HX.setLocal(op, { start: ns, len: end - ns }); }
          else { const ne = HX.clamp(sn(bx(ev), ev), c.start + minLen, srcEnd); HX.setLocal(op, { start: c.start, len: ne - c.start }); }
        };
        up = () => { if (moved && (c.start !== before.start || c.len !== before.len)) HX.commit('Trim ' + c.name, [Object.assign({}, op, { before, after: { start: c.start, len: c.len } })]); };
      } else if (zone === 'fadeIn' || zone === 'fadeOut') {
        const before = { fin: c.fadeIn, fout: c.fadeOut };
        const op = { trackId: row.t.id, param: 'regionFades', key: c.id };
        mv = (ev) => {
          moved = true;
          const b = bx(ev);
          if (zone === 'fadeIn') HX.setLocal(op, { fin: HX.clamp(b - c.start, 0, c.len - c.fadeOut), fout: c.fadeOut });
          else HX.setLocal(op, { fin: c.fadeIn, fout: HX.clamp(c.start + c.len - b, 0, c.len - c.fadeIn) });
        };
        up = () => { if (moved && (c.fadeIn !== before.fin || c.fadeOut !== before.fout)) HX.commit((zone === 'fadeIn' ? 'Fade in ' : 'Fade out ') + c.name, [Object.assign({}, op, { before, after: { fin: c.fadeIn, fout: c.fadeOut } })]); };
      } else if (zone === 'gain') {
        const before = c.gainDb || 0, op = { trackId: row.t.id, param: 'clipGain', key: c.id };
        mv = (ev) => {
          moved = true;
          const db = before - (ev.clientY - e.clientY) * (ev.shiftKey ? 0.05 : 0.25);   // 4 px a dB, shift = fine
          HX.live(op, Math.round(HX.clamp(db, -24, 12) * 10) / 10);
        };
        up = () => { if (moved && c.gainDb !== before) HX.commit(c.name + ' clip gain ' + HX.fmtDb(c.gainDb, true) + ' dB', [Object.assign({}, op, { before, after: c.gainDb })]); };
      }
      const upAll = () => { lanesWrap.removeEventListener('pointermove', mv); lanesWrap.removeEventListener('pointerup', upAll); lanesWrap.removeEventListener('pointercancel', upAll); up(); };
      lanesWrap.addEventListener('pointermove', mv); lanesWrap.addEventListener('pointerup', upAll); lanesWrap.addEventListener('pointercancel', upAll);
    });
    lanesWrap.addEventListener('dblclick', () => { if (S.ui.clipId) { S.ui.bottom = 'clip'; HX.emit('bottom'); } });
    const CURSOR = { move: 'default', trimL: 'w-resize', trimR: 'e-resize', fadeIn: 'col-resize', fadeOut: 'col-resize', gain: 'ns-resize' };
    const INFO = {
      move: 'drag to move (to another track too) · click = playhead · ⌘E split at the playhead · 0 mute · ⌫ delete · ⌘-drag = no snap',
      trimL: 'drag to trim the start', trimR: 'drag to trim the end', fadeIn: 'drag the fade-in handle', fadeOut: 'drag the fade-out handle', gain: 'drag the clip gain line up or down (shift = fine)',
    };
    lanesWrap.addEventListener('mousemove', (e) => {
      if (e.buttons) return;
      const rect = lanesWrap.getBoundingClientRect();
      const hit = hitAt(e.clientX - rect.left, e.clientY - rect.top);
      const c = hit && hit.c;
      const hv = c ? c.id : null;
      if (A.hover !== hv) { A.hover = hv; A.dirty = true; }
      lanesWrap.style.cursor = c ? CURSOR[hit.zone] : '';
      HX.info(c ? c.name + ' · ' + hit.row.t.name + ' · bar ' + (Math.floor(c.start / 4) + 1) + ', ' + (c.len / 4).toFixed(2) + ' bars · ' + INFO[hit.zone] : 'Click to place the playhead · ⌘-scroll to zoom · shift-scroll to move in time · drop audio files here to import');
    });
    lanesWrap.addEventListener('mouseleave', () => { if (A.hover) { A.hover = null; A.dirty = true; } });
    bindDrop();
  }
  /* what is under the pointer: the lane, the clip (the topmost, as drawn last) and which part of it */
  function hitAt(x, y) {
    const row = rows().find((r) => y >= r.y && y < r.y + r.hgt);
    if (!row) return null;
    const beat = B(x);
    const c = [...row.t.clips].reverse().find((c) => beat >= c.start && beat < c.start + c.len);
    if (!c) return { row, beat };
    const z = S.ui.zoom, x0 = X(c.start), x1 = X(c.start + c.len), y0 = row.y + 1, hh = row.hgt - 2;
    const head = hh > 34 ? 12 : 0, by = y0 + head, bh = hh - head;
    let zone = 'move';
    const audio = c.kind === 'audio', wide = x1 - x0 > 16;
    if (audio && wide && y < by + 8 && Math.abs(x - (x0 + Math.max(c.fadeIn * z, 2))) <= 5) zone = 'fadeIn';
    else if (audio && wide && y < by + 8 && Math.abs(x - (x1 - Math.max(c.fadeOut * z, 2))) <= 5) zone = 'fadeOut';
    else if (wide && x - x0 <= 5) zone = 'trimL';
    else if (wide && x1 - x <= 5) zone = 'trimR';
    else if (audio && y > by && Math.abs(y - gainLineY(c.gainDb || 0, by, bh)) <= 3) zone = 'gain';
    return { row, c, zone, beat, by, bh };
  }
  const canHold = (t, c) => !t.isReturn && !t.isMaster && (c.kind === 'midi' ? t.kind === 'midi' : t.kind === 'audio');

  /* ── clip keys (Live's): ⌘E split at the playhead, 0 mute, Delete / Backspace remove ── */
  const typingNow = () => /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
  document.addEventListener('keydown', (e) => {
    if (S.ui.view !== 'arrange' || typingNow() || HX.modalOpen() || e.defaultPrevented || (HX.noEngineScreen && HX.noEngineScreen())) return;
    const f = S.ui.clipId && HX.findClip(S.ui.clipId);
    const mod = e.metaKey || e.ctrlKey;
    if (mod && !e.shiftKey && e.key.toLowerCase() === 'e') {
      e.preventDefault();
      if (!f) return HX.toast('Select a clip to split');
      const at = HX.pos(), c = f.clip;
      if (at <= c.start + 1e-6 || at >= c.start + c.len - 1e-6) return HX.toast('Put the playhead inside ' + c.name + ' to split it (click the clip where you want the cut)');
      HX.commit('Split ' + c.name + ' at ' + HX.bbtStr(at), [{ trackId: f.track.id, param: 'regionSplit', key: c.id, before: Object.assign({}, c), after: at }]);
    } else if (!mod && f && (e.key === 'Delete' || e.key === 'Backspace')) {
      e.preventDefault();
      HX.commit('Delete ' + f.clip.name, [{ trackId: f.track.id, param: 'regionRemove', key: f.clip.id, before: { clip: Object.assign({}, f.clip), index: f.track.clips.indexOf(f.clip) }, after: null }]);
    } else if (!mod && f && e.key === '0') {
      e.preventDefault();
      HX.commit((f.clip.muted ? 'Unmute ' : 'Mute ') + f.clip.name, [{ trackId: f.track.id, param: 'regionMute', key: f.clip.id, before: !!f.clip.muted, after: !f.clip.muted }]);
    }
  });

  /* ── import: drop files from the Finder (uploaded to the app, then imported), or type their paths ── */
  function bindDrop() {
    const mark = h('div', { style: { position: 'absolute', left: 0, right: 0, pointerEvents: 'none', display: 'none', background: 'var(--acc-2)', borderTop: '1px solid var(--acc)', borderBottom: '1px solid var(--acc)' } });
    const line = h('div', { style: { position: 'absolute', top: 0, bottom: 0, width: '1px', pointerEvents: 'none', display: 'none', background: 'var(--acc)' } });
    lanesWrap.append(mark, line);
    const target = (e) => {
      const rect = lanesWrap.getBoundingClientRect();
      const x = e.clientX - rect.left, y = e.clientY - rect.top;
      const row = rows().find((r) => y >= r.y && y < r.y + r.hgt);
      const t = row && row.t.kind === 'audio' && !row.t.isReturn && !row.t.isMaster ? row.t : null;
      return { t, row, x, beat: x > lanesWrap.clientWidth ? HX.pos() : Math.max(0, snap(B(x))) };   // on a track header: at the playhead
    };
    const files = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files');
    const hide = () => { mark.style.display = line.style.display = 'none'; };
    /* the whole lane area takes drops, also the empty space under the tracks (new tracks) */
    body.addEventListener('dragover', (e) => {
      if (!files(e)) return;
      e.preventDefault(); e.dataTransfer.dropEffect = 'copy';
      const tg = target(e);
      line.style.display = ''; line.style.left = X(tg.beat) + 'px';
      if (tg.t) { mark.style.display = ''; mark.style.top = tg.row.y + 'px'; mark.style.height = tg.row.hgt + 'px'; }
      else mark.style.display = 'none';
      HX.info(tg.t ? 'Drop to import onto ' + tg.t.name + ' at ' + HX.bbtStr(tg.beat) : 'Drop to import as new tracks at ' + HX.bbtStr(tg.beat));
    });
    body.addEventListener('dragleave', (e) => { if (!body.contains(e.relatedTarget)) hide(); });
    body.addEventListener('drop', async (e) => {
      if (!files(e)) return;
      e.preventDefault(); hide();
      const tg = target(e), list = Array.from(e.dataTransfer.files);
      if (!HX.mcp.connected) return HX.toast('Importing needs the engine: connect first', 3200);
      try {
        const paths = [];
        for (const [i, f] of list.entries()) {
          const up = await HX.uploadForImport(f, (p) => HX.toast('Sending ' + f.name + ' to the app · ' + Math.round(p * 100) + '%' + (list.length > 1 ? ' (' + (i + 1) + ' of ' + list.length + ')' : ''), 4000));
          paths.push(up.path);
        }
        HX.toast('Importing ' + list.map((f) => f.name).join(', ') + '…', 60000);
        const r = await HX.importAudio(paths, { trackId: tg.t && tg.t.id, beat: tg.beat });
        reportImport(r);
      } catch (err) { HX.toast('Import failed: ' + err.message, 4200); HX.log('err', 'import · ' + err.message); }
    });
  }
  function reportImport(r) {
    const ok = (r && r.imported) || [], bad = (r && r.failed) || [];
    HX.toast(ok.length ? 'Imported ' + ok.length + ' file' + (ok.length > 1 ? 's' : '') + (bad.length ? ' · ' + bad.length + ' failed' : '') : 'Nothing imported' + (bad.length ? ': ' + (bad[0].error || bad[0].reason || JSON.stringify(bad[0])) : ''), 4200);
  }
  let importPop = null;
  function openImport() {
    if (importPop) { importPop.remove(); importPop = null; return; }
    const btn = HX.$('#importBtn'), r = btn.getBoundingClientRect();
    const sel = HX.track(S.ui.trackId);
    const onto = sel && sel.real && sel.kind === 'audio' ? sel : null;
    const ta = h('textarea', { rows: 4, spellcheck: 'false', placeholder: '/path/to/Song/Vocals.wav\n(one path a line)', style: { resize: 'vertical', background: 'var(--bg0)', border: '1px solid var(--line2)', borderRadius: 'var(--r2)', padding: '6px', color: 'var(--tx0)', font: '500 var(--fs-xs)/1.5 var(--mono)', outline: 'none' } });
    const where = h('select', { style: { background: 'var(--bg0)', color: 'var(--tx0)', border: '1px solid var(--line2)', borderRadius: 'var(--r2)', height: '24px' } },
      h('option', { value: 'new' }, 'New tracks, at the playhead'),
      onto ? h('option', { value: 'onto' }, 'Onto ' + onto.name + ', at the playhead') : null);
    const err = h('p.err');
    const go = h('button.btn.primary', null, 'Import');
    const close = () => { if (importPop) { importPop.remove(); importPop = null; } };
    importPop = h('div.connect-pop', { style: { top: r.bottom + 6 + 'px', right: (innerWidth - r.right) + 'px', width: '360px' } },
      h('b', { style: { color: 'var(--tx0)' } }, 'Import audio'),
      h('p', null, 'Paste the files’ full paths (in the Finder: select them, ⌥⌘C copies the paths). Or drop files from the Finder onto the lanes: the page sends them to the app, which hands them to the engine. Either way the engine copies them into the session.'),
      ta, where, err, h('div.row', null, h('button.btn', { onclick: close }, 'Cancel'), go));
    document.body.append(importPop);
    ta.focus();
    ta.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Escape') close(); if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) go.click(); });
    go.addEventListener('click', async () => {
      err.textContent = '';
      const paths = ta.value.split('\n').map((p) => p.trim().replace(/^['"]|['"]$/g, '').replace(/\\ /g, ' ')).filter(Boolean);
      if (!paths.length) { err.textContent = 'Paste at least one path'; return; }
      const rel = paths.find((p) => !p.startsWith('/') && !/^[A-Za-z]:[\\/]/.test(p));
      if (rel) { err.textContent = 'Use full paths (starting with /): ' + rel; return; }
      if (!HX.mcp.connected) { err.textContent = 'Importing needs the engine: connect first'; return; }
      go.disabled = true; go.textContent = 'Importing…';
      try {
        const res = await HX.importAudio(paths, { trackId: where.value === 'onto' && onto ? onto.id : null, beat: HX.pos() });
        reportImport(res);
        if (res && res.imported && res.imported.length) close();
        else err.textContent = 'Nothing imported' + (res && res.failed && res.failed.length ? ': ' + JSON.stringify(res.failed[0]) : '');
      } catch (e) { err.textContent = e.message; }
      finally { go.disabled = false; go.textContent = 'Import'; }
    });
  }
  function snap(b) { const s = snapBeats(); return Math.round(b / s) * s; }

  function bindTop() {
    topCv.addEventListener('pointerdown', (e) => {
      const rect = topCv.getBoundingClientRect();
      const x = e.clientX - rect.left, y = e.clientY - rect.top;
      topCv.setPointerCapture(e.pointerId);
      if (y < TOP_OVW) {
        const L = S.session.lengthBeats, w = rect.width;
        const go = (cx) => { S.ui.scrollX = (cx / w) * L - (w / S.ui.zoom) / 2; clampScroll(); A.dirty = true; };
        go(x);
        const mv = (ev) => go(ev.clientX - rect.left);
        topCv.addEventListener('pointermove', mv);
        topCv.addEventListener('pointerup', () => topCv.removeEventListener('pointermove', mv), { once: true });
        return;
      }
      if (e.shiftKey) { // shift-drag sets the loop
        const s0 = snap(B(x));
        const mv = (ev) => { const s1 = snap(B(ev.clientX - rect.left)); S.session.loop.start = Math.min(s0, s1); S.session.loop.end = Math.max(s0, s1) || s0 + 4; S.session.loop.on = true; A.dirty = true; HX.emit('transport'); };
        topCv.addEventListener('pointermove', mv);
        topCv.addEventListener('pointerup', () => { topCv.removeEventListener('pointermove', mv); if (S.session.loop.on) HX.setLoopRange(S.session.loop.start, S.session.loop.end); }, { once: true });
        return;
      }
      if (y < TOP_OVW + TOP_SEC) { const s = S.session.sections.find((s) => B(x) >= s.start && B(x) < s.start + s.len); if (s) return HX.locate(s.start); }
      HX.locate(snap(B(x)));
    });
    topCv.addEventListener('mousemove', (e) => {
      const y = e.clientY - topCv.getBoundingClientRect().top;
      HX.info(y < TOP_OVW ? 'Overview · click or drag to move the view' : y < TOP_OVW + TOP_SEC ? 'Sections (locators) · click to jump' : 'Ruler · click to place the playhead · shift-drag to set the loop');
    });
  }

  /* ── per frame ── */
  const meterCtx = new WeakMap();      // keyed by the canvas: a re-built header takes its context with it
  HX.onFrame((beat) => {
    if (S.ui.view !== 'arrange' || !lanesWrap) return;
    const w = lanesWrap.clientWidth;
    if (A.follow && HX.T.playing) {
      const x = X(beat);
      if (x > w * 0.88 || x < 0) { S.ui.scrollX = beat - (w * 0.12) / S.ui.zoom; clampScroll(); A.dirty = true; }
    }
    if (A.dirty) { A.dirty = false; draw(); }
    const x = X(beat);
    const vis = x >= 0 && x <= w;
    ph.style.display = phTop.style.display = vis ? '' : 'none';
    ph.style.transform = phTop.style.transform = 'translateX(' + x.toFixed(2) + 'px)';
    // header meters
    for (const id in hdrRefs) {
      const r = hdrRefs[id], t = HX.track(id); if (!t) continue;
      const cv = r.meter;
      if (!HX.isVisible(cv)) continue;                 // scrolled out of view: nothing to draw
      const mh = cv.clientHeight;
      let ctx = meterCtx.get(cv);
      if (!ctx || cv._h !== mh) { ctx = HX.fitCanvas(cv, 6, mh); meterCtx.set(cv, ctx); cv._h = mh; cv._ep = -1; }
      HX.drawMeterIfChanged(cv, ctx, 6, mh, t.meter, { noTicks: true });
    }
  });

  HX.on('session', () => { if (root) { renderHeaders(); HX.zoomFit(); } });
  HX.on('history', () => (A.dirty = true));
  HX.on('transport', () => (A.dirty = true));
  HX.on('view', () => (A.dirty = true));
})();
