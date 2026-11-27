/* HypnoMix · automation lanes under a track, and the tempo track (the engine's automation_* and tempo_get_map).

   The A button on a track header lists the route's automatable controls (automation_list: the fader, trim, pan,
   width, mute, its sends and plug-in parameters) and shows or hides a lane for each, under the track (and under its
   take lanes). A lane draws the control's points (automation_get, times in seconds) and the line between them.

   Editing, with the mouse or the keyboard, is one engine call and ONE engine undo step per gesture:
     drag a point          the move is written again from the point before it to the point after it
     double-click a lane   adds a point on the line as it is (nothing heard changes: a point to drag)
     Alt-click a point     removes it (or Delete on the lane, with the point selected)
     on a focused lane     ← → select the previous / next point (the playhead goes there), ↑ ↓ move it
                           (0.5 dB, shift 0.1 dB; other controls 2 % of their range), A or + adds a point at the
                           playhead, Delete / Backspace removes the selected point, P switches playback on or off
   Level controls (the fader, trim, sends) follow HypnoMix's smooth-automation rules: every move is a gentle S-curve
   (curve s_curve), at most 3 dB (a trim 4 dB), its steepest point under 7 dB/s, starting and ending on the line as it
   is. A drag stops where a rule would be broken; the first and last points of a level lane keep their value (the way
   in and out of a move is an S-curve from the line). The app checks the same rules again before the call reaches the
   engine (and never automates a bus or group that carries tracks that are not vocals): what it refuses is put back
   and its reason shown. The points of a level lane that carry its moves are the ones a drag takes (where the line
   turns or is flat); the many points of an S-curve between them are drawn, not dragged.

   The tempo track (the Tempo button above the lanes) shows the engine's tempo map: each tempo point, and a ramp as a
   slope from its tempo to the tempo it reaches at the next point. The bar grid still assumes the session's first
   tempo. Tempo changes are made with the Assistant, `hypnomix tempomap --follow` or `hypnomix breathe`.

   With the mock session the first vocal track has a fader lane with one ride, edited locally.
   Hooks: arrange.js (rows, headers, the A and Tempo buttons, drawing, the pointer), regions.js (the op path: each
   write's engine undo step, and `done` reading the lane back). */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  const LANE_H = 44, TEMPO_H = 34, EPS = 1e-4, MIN_GAP = 0.05, EDGE = 1e-4;
  const LINE_DB = 3, TRIM_DB = 4, MAX_SLOPE = 7, S_PEAK = Math.PI / 2, ON_LINE = 0.1;
  const LEVEL = ['gain', 'trim', 'send'];

  const A = (HX.auto = {
    data: {},              // trackId → { facts, controls: [info], lanes: { control: { points: [{ t (s), v }], state } } }
    sel: null,             // { trackId, control, i } the selected point
    drag: null,            // { trackId, control, i, t, v } while a point is dragged
    tempo: { shown: false, points: [], loaded: false },
    LANE_H, rules: null,
  });

  const kindOf = (control) => {
    const c = String(control || '');
    if (c === 'gain' || c === 'fader') return 'gain';
    if (c === 'trim') return 'trim';
    if (c.startsWith('send:')) return 'send';
    if (c === 'pan_azimuth' || c === 'pan_width') return 'pan';
    if (c === 'mute') return 'mute';
    if (c.startsWith('plugin:')) return 'plugin';
    return 'other';
  };
  const isLevel = (control) => LEVEL.includes(kindOf(control));
  const cap = (control) => (kindOf(control) === 'trim' ? TRIM_DB : LINE_DB);

  /* ── the rules, as the drag uses them (engineer/automation_rules.py is the one the app enforces) ── */
  const rate = (t0, t1, d) => (Math.abs(d) < 1e-9 ? 0 : t1 - t0 <= 1e-9 ? Infinity : (S_PEAK * Math.abs(d)) / (t1 - t0));
  /* the most a level point may move from a neighbour `dt` seconds away: the cap, and under 7 dB/s at the S-curve's peak */
  const reach = (control, dt) => Math.max(0, Math.min(cap(control), (MAX_SLOPE * Math.abs(dt)) / S_PEAK - 0.02));
  /* [lo, hi] a point at time t may take between neighbours a and b (either may be null) */
  function allowed(control, a, b, t) {
    let lo = -Infinity, hi = Infinity;
    for (const n of [a, b]) {
      if (!n || n.v == null) continue;
      const r = reach(control, t - n.t);
      lo = Math.max(lo, n.v - r); hi = Math.min(hi, n.v + r);
    }
    return lo <= hi ? [lo, hi] : null;
  }
  /* why a write's points break a rule (plain words), or '' */
  function problem(control, pts) {
    if (!isLevel(control) || pts.length < 2) return '';
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i], d = b.v - a.v;
      if (Math.abs(d) > cap(control) + 1e-6) return 'a move is at most ' + cap(control) + ' dB';
      if (rate(a.t, b.t, d) >= MAX_SLOPE) return 'the move would be steeper than ' + MAX_SLOPE + ' dB/s';
    }
    return '';
  }
  A.rules = { allowed, problem, reach, rate, kindOf, isLevel, cap };

  /* the raised-cosine S between each pair, about one point every 50 ms (8 to 64 a move), as the engine writes s_curve */
  function sCurve(pts) {
    const out = pts.length ? [Object.assign({}, pts[0])] : [];
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i];
      const n = Math.abs(b.v - a.v) > 1e-9 ? HX.clamp(Math.ceil((b.t - a.t) / 0.05), 8, 64) : 1;
      for (let k = 1; k <= n; k++) {
        const f = k / n;
        out.push({ t: a.t + (b.t - a.t) * f, v: a.v + ((b.v - a.v) * (1 - Math.cos(Math.PI * f))) / 2 });
      }
    }
    return out;
  }
  A.sCurve = sCurve;

  /* the points where a level lane's line turns or is flat: what a drag takes (all of them on any other lane) */
  function anchors(control, pts) {
    if (!isLevel(control) || pts.length < 3) return pts.map((_, i) => i);
    const sg = (i) => { const d = pts[i + 1].v - pts[i].v; return Math.abs(d) < EPS ? 0 : d > 0 ? 1 : -1; };
    const raw = [0];
    for (let i = 1; i < pts.length - 1; i++) { const p = sg(i - 1), q = sg(i); if (p !== q || p === 0) raw.push(i); }
    raw.push(pts.length - 1);
    /* the ends of an engine S-curve move by a hair: a handle within 0.12 s and 0.05 dB of the one before is the same
       handle (a drag rewrites everything between its neighbours, so the point left out goes with it) */
    const near = (a, b) => Math.abs(pts[b].t - pts[a].t) < 0.12 && Math.abs((pts[b].v == null ? -999 : pts[b].v) - (pts[a].v == null ? -999 : pts[a].v)) < 0.05;
    const out = [];
    for (const i of raw) {
      if (out.length && near(out[out.length - 1], i)) { if (i === pts.length - 1 && out.length > 1) out[out.length - 1] = i; continue; }
      out.push(i);
    }
    return out;
  }
  A.anchors = anchors;

  /* the line's value at t (seconds): straight between points, flat outside them; the control's value with no points */
  function lineAt(lane, info, t) {
    const p = lane.points;
    if (!p.length) return info && typeof info.current === 'number' ? info.current : null;
    if (t <= p[0].t) return p[0].v;
    for (let i = 1; i < p.length; i++) if (t <= p[i].t) { const a = p[i - 1], b = p[i]; return b.t - a.t < 1e-9 ? b.v : a.v + ((b.v - a.v) * (t - a.t)) / (b.t - a.t); }
    return p[p.length - 1].v;
  }
  A.lineAt = lineAt;

  /* what a write or clear does to a lane's points (the engine's own result is read back afterwards) */
  function after(points, call) {
    const a = call.args;
    const lo = a.start != null ? a.start : a.points && a.points.length ? a.points[0].time : -Infinity;
    const hi = a.end != null ? a.end : a.points && a.points.length ? a.points[a.points.length - 1].time : Infinity;
    const keep = call.tool === 'automation_write' && a.mode === 'replace-all' ? [] : points.filter((p) => p.t < lo - 1e-9 || p.t > hi + 1e-9);
    if (call.tool === 'automation_clear') return keep;
    let add = (a.points || []).map((p) => ({ t: p.time, v: p.value }));
    if (a.curve === 's_curve') add = sCurve(add);
    return keep.concat(add).sort((x, y) => x.t - y.t);
  }
  A.after = after;

  /* ── values on a lane: 0 (bottom) .. 1 (top) ── */
  function toPos(info, v) {
    const k = kindOf(info.control);
    if (v == null) return 0;
    if (k === 'gain' || k === 'send') return HX.clamp(HX.dbToPos(v), 0, 1);
    if (k === 'pan') return HX.clamp((v + 1) / 2, 0, 1);
    if (k === 'mute') return v >= 0.5 ? 1 : 0;
    const lo = typeof info.min === 'number' ? info.min : k === 'trim' ? -20 : 0, hi = typeof info.max === 'number' ? info.max : k === 'trim' ? 20 : 1;
    return hi > lo ? HX.clamp((v - lo) / (hi - lo), 0, 1) : 0.5;
  }
  function fromPos(info, p) {
    const k = kindOf(info.control);
    p = HX.clamp(p, 0, 1);
    if (k === 'gain' || k === 'send') return Math.round(Math.max(-60, HX.posToDb(p)) * 10) / 10;
    if (k === 'pan') return Math.round((p * 2 - 1) * 100) / 100;
    if (k === 'mute') return p >= 0.5 ? 1 : 0;
    const lo = typeof info.min === 'number' ? info.min : k === 'trim' ? -20 : 0, hi = typeof info.max === 'number' ? info.max : k === 'trim' ? 20 : 1;
    return Math.round((lo + (hi - lo) * p) * 1000) / 1000;
  }
  const step = (info, fine) => { const k = kindOf(info.control); if (LEVEL.includes(k)) return fine ? 0.1 : 0.5; if (k === 'mute') return 1; const lo = typeof info.min === 'number' ? info.min : 0, hi = typeof info.max === 'number' ? info.max : 1; return ((hi - lo) * (fine ? 0.005 : 0.02)) || 0.01; };
  function fmt(info, v) {
    const k = kindOf(info.control);
    if (v == null) return '-∞ dB';
    if (LEVEL.includes(k)) return HX.fmtDb(v, true) + ' dB';
    if (k === 'pan') return info.control === 'pan_width' ? Math.round(v * 100) + '%' : HX.fmtPan(v);
    if (k === 'mute') return v >= 0.5 ? 'muted' : 'on';
    return String(Math.round(v * 1000) / 1000) + (info.unit && info.unit.length < 6 ? ' ' + info.unit : '');
  }
  A.toPos = toPos; A.fromPos = fromPos;

  /* ── which lanes are shown: remembered per session in this browser (a convenience only) ── */
  const KEY = 'hx.auto.shown';
  const memo = (() => { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; } })();
  const memoKey = (t) => (S.session ? S.session.name : '') + '|' + t.id;
  const shownOf = (t) => (t && Array.isArray(t.autoShown) ? t.autoShown : []);
  function setShown(t, list) {
    t.autoShown = list;
    memo[memoKey(t)] = list;
    try { localStorage.setItem(KEY, JSON.stringify(memo)); } catch (e) {}
    HX.renderArrangeHeaders && HX.renderArrangeHeaders();
  }
  const available = () => (HX.mcp.connected ? HX.mcp.tools.includes('automation_list') : true);
  const infoOf = (t, control) => { const d = A.data[t.id]; return d && d.controls.find((c) => c.control === control); };
  const laneOf = (t, control) => { const d = A.data[t.id]; return d && d.lanes[control]; };

  /* ── arrange.js hooks ── */
  A.rows = function (t, y) {
    const d = A.data[t.id];
    if (!d) return [];
    return shownOf(t).filter((c) => d.lanes[c] && infoOf(t, c)).map((c, i) => ({ t, y: y + i * LANE_H, hgt: LANE_H, autoLane: true, control: c }));
  };

  A.toggle = function (t) {
    if (!available() || (HX.mcp.connected && !t.real)) return null;
    const n = shownOf(t).length;
    const b = h('button.tog.au', { type: 'button', 'data-info': 'Automation lanes of ' + t.name + (n ? ' (' + n + ' shown)' : '') + ': choose which controls show a lane',
      onclick: (e) => { e.stopPropagation(); A.choose(t); } }, 'A');
    b.classList.toggle('on', n > 0);
    b.setAttribute('aria-label', 'Automation lanes of ' + t.name);
    b.setAttribute('aria-haspopup', 'dialog');
    return b;
  };

  /* the lane chooser: every control the engine lists for the route, ticked when its lane shows */
  A.choose = async function (t) {
    try { await A.load(t.id); } catch (e) { HX.toast('Automation not read: ' + e.message, 3600); return; }
    const d = A.data[t.id]; if (!d) return;
    const now = new Set(shownOf(t));
    const boxes = d.controls.map((c) => {
      const box = h('input', { type: 'checkbox', value: c.control });
      box.checked = now.has(c.control);
      return h('label.auto-pick', null, box, ' ' + c.name + (c.points ? ' · ' + c.points + ' point' + (c.points === 1 ? '' : 's') : ''));
    });
    const note = d.facts && (d.facts.isBus || d.facts.isMaster) ? h('small', null, 'A bus: its level is never automated while it carries any track that is not a vocal (ride the vocal tracks instead).') : null;
    const body = h('div.auto-choose', null, ...boxes, note);
    const yes = await HX.dialog({ title: 'Automation lanes · ' + t.name, body, cancel: false, buttons: [{ label: 'Cancel', value: false }, { label: 'Show', value: true, kind: 'primary', focus: true }] });
    if (!yes) return;
    const list = boxes.map((l) => l.querySelector('input')).filter((b) => b.checked).map((b) => b.value);
    setShown(t, list);
    await Promise.all(list.map((c) => A.loadLane(t.id, c).catch((e) => HX.log('err', 'automation_get · ' + e.message))));
    HX.renderArrangeHeaders && HX.renderArrangeHeaders();
  };

  A.headers = function (t) {
    return A.rows(t, 0).map((r) => {
      const info = infoOf(t, r.control), lane = laneOf(t, r.control);
      const sel = A.sel && A.sel.trackId === t.id && A.sel.control === r.control ? lane.points[A.sel.i] : null;
      const on = lane.state && lane.state !== 'manual';
      const st = h('button.auto-state', { type: 'button', 'aria-pressed': String(!!on), 'aria-label': 'Play the ' + info.name + ' automation of ' + t.name,
        'data-info': on ? 'Playing this automation · click to switch it off (manual: the control stays where it is)' : 'Not playing (manual) · click to play the points',
        onpointerdown: (e) => e.stopPropagation(), onclick: (e) => { e.stopPropagation(); A.setState(t, r.control, on ? 'manual' : 'play'); } }, on ? 'Play' : 'Off');
      const hide = h('button.auto-hide', { type: 'button', 'aria-label': 'Hide the ' + info.name + ' lane of ' + t.name, 'data-info': 'Hide this lane (the automation stays)',
        onpointerdown: (e) => e.stopPropagation(), onclick: (e) => { e.stopPropagation(); setShown(t, shownOf(t).filter((c) => c !== r.control)); } }, '×');
      const n = lane.points.length;
      const sub = (sel ? 'point ' + (A.sel.i + 1) + ': ' + fmt(info, sel.v) + ' at ' + sel.t.toFixed(2) + ' s' : n + ' point' + (n === 1 ? '' : 's')) + (isLevel(r.control) ? ' · S-curves' : '');
      const el = h('div.th.auto', { style: { height: LANE_H + 'px' }, role: 'group', tabindex: '0', 'data-hk': 'auto:' + t.id + ':' + r.control,
        'aria-label': info.name + ' automation of ' + t.name + ', ' + n + ' point' + (n === 1 ? '' : 's') + (on ? ', playing' : ', off') + '. Left and right arrows pick a point, up and down move it, A adds one at the playhead, Delete removes it, P plays or stops',
        'data-info': info.name + ' automation of ' + t.name + ' · ← → pick a point, ↑ ↓ move it, A add at the playhead, Delete remove, P play/off · one undo step each',
        onpointerdown: () => HX.select(t.id), onkeydown: (e) => keys(e, t, r.control) },
        h('i.chip', { style: { background: t.color, opacity: 0.6 } }),
        h('div.th-name', null, h('b', null, info.name), h('small', null, sub)),
        h('div.auto-ctl', null, st, hide));
      return el;
    });
  };

  /* the tempo track: a row above the tracks */
  const TEMPO_T = { id: '__tempo', name: 'Tempo', clips: [], devices: [], sends: [], color: '#888' };
  A.tempoRows = () => (A.tempo.shown ? [{ t: TEMPO_T, y: 0, hgt: TEMPO_H, tempoLane: true }] : []);
  A.tempoHeader = function () {
    if (!A.tempo.shown) return [];
    const pts = A.tempo.points, ramps = pts.filter((p) => p.ramped).length;
    const sub = pts.length ? pts.length + ' tempo' + (pts.length === 1 ? '' : 's') + (ramps ? ' · ' + ramps + ' ramp' + (ramps === 1 ? '' : 's') : '') : A.tempo.loaded ? 'no tempo map' : 'reading…';
    return [h('div.th.tempo', { style: { height: TEMPO_H + 'px' }, role: 'group', tabindex: '0', 'data-hk': 'tempo',
      'aria-label': 'Tempo track: ' + (pts.length ? pts.map(words).join('; ') : sub),
      'data-info': 'The tempo map: each tempo, and a ramp as a slope to the tempo it reaches · change it with the Assistant, hypnomix tempomap --follow or hypnomix breathe' },
      h('i.chip', { style: { background: 'var(--tx2)' } }), h('div.th-name', null, h('b', null, 'Tempo'), h('small', null, sub)))];
  };
  const words = (p) => 'bar ' + p.bar + ': ' + (p.ramped ? fmtBpm(p.bpm) + ' to ' + fmtBpm(p.bpmEnd) + ' BPM' : fmtBpm(p.bpm) + ' BPM');
  const fmtBpm = (b) => String(Math.round(b * 100) / 100);
  A.toggleTempo = function () {
    A.tempo.shown = !A.tempo.shown;
    try { localStorage.setItem('hx.auto.tempo', A.tempo.shown ? '1' : '0'); } catch (e) {}
    if (A.tempo.shown) A.loadTempo().catch((e) => HX.log('err', 'tempo_get_map · ' + e.message));
    HX.renderArrangeHeaders && HX.renderArrangeHeaders();
    return A.tempo.shown;
  };
  A.tempoAvailable = () => (HX.mcp.connected ? HX.mcp.tools.includes('tempo_get_map') : true);

  /* ── drawing ── */
  A.drawLane = function (ctx, r, g) {
    const { X, w, colors } = g;
    const t = r.t, info = infoOf(t, r.control), lane = laneOf(t, r.control);
    if (!info || !lane) return;
    const y0 = r.y + 4, hh = r.hgt - 9;
    const Y = (v) => y0 + hh * (1 - toPos(info, v));
    const XS = (s) => X(HX.secToBeats(s));
    ctx.fillStyle = colors.light ? 'rgba(0,0,0,.03)' : 'rgba(0,0,0,.16)';
    ctx.fillRect(0, r.y, w, r.hgt);
    const pts = A.drag && A.drag.trackId === t.id && A.drag.control === r.control ? A.drag.preview : lane.points;
    const on = lane.state && lane.state !== 'manual';
    ctx.strokeStyle = on ? t.color : colors['--tx3']; ctx.lineWidth = 1.5;
    ctx.globalAlpha = on ? 1 : 0.6;
    ctx.beginPath();
    if (!pts.length) { const v = lineAt(lane, info, 0); ctx.moveTo(0, Y(v)); ctx.lineTo(w, Y(v)); }
    else {
      ctx.moveTo(0, Y(pts[0].v));
      for (const p of pts) ctx.lineTo(XS(p.t), Y(p.v));
      ctx.lineTo(w, Y(pts[pts.length - 1].v));
    }
    ctx.stroke(); ctx.globalAlpha = 1;
    /* the points a drag takes: squares; the selected one filled */
    const an = anchors(r.control, pts);
    for (const i of an) {
      const p = pts[i], x = XS(p.t); if (x < -6 || x > w + 6) continue;
      const sel = A.sel && A.sel.trackId === t.id && A.sel.control === r.control && A.sel.i === i;
      const bad = A.drag && A.drag.trackId === t.id && A.drag.control === r.control && A.drag.i === i && A.drag.held;
      ctx.fillStyle = bad ? colors['--warn'] : sel ? colors['--tx0'] : colors['--bg0'];
      ctx.strokeStyle = bad ? colors['--warn'] : colors['--tx0']; ctx.lineWidth = 1;
      ctx.fillRect(Math.round(x) - 3, Math.round(Y(p.v)) - 3, 7, 7); ctx.strokeRect(Math.round(x) - 2.5, Math.round(Y(p.v)) - 2.5, 6, 6);
    }
    if (A.drag && A.drag.trackId === t.id && A.drag.control === r.control) {
      ctx.fillStyle = colors['--tx0']; ctx.font = '500 9.5px ' + HX.css('--mono'); ctx.textBaseline = 'top';
      ctx.fillText(fmt(info, A.drag.v) + (A.drag.held ? '  · ' + A.drag.held : ''), Math.max(2, XS(A.drag.t) + 6), r.y + 2);
    }
    ctx.fillStyle = colors['--line']; ctx.fillRect(0, r.y + r.hgt - 1, w, 1);
  };

  A.drawTempo = function (ctx, r, g) {
    const { X, w, colors } = g;
    const pts = A.tempo.points;
    ctx.fillStyle = colors['--bg1']; ctx.fillRect(0, r.y, w, r.hgt);
    if (pts.length) {
      const all = pts.flatMap((p) => [p.bpm, p.bpmEnd]);
      const lo = Math.min(...all) - 4, hi = Math.max(...all) + 4;
      const y0 = r.y + 6, hh = r.hgt - 12, Y = (b) => y0 + hh * (1 - (b - lo) / (hi - lo));
      const XS = (s) => X(HX.secToBeats(s));
      ctx.strokeStyle = colors['--acc']; ctx.lineWidth = 1.5; ctx.beginPath();
      pts.forEach((p, i) => {
        const x0 = XS(p.time), x1 = i + 1 < pts.length ? XS(pts[i + 1].time) : w;
        if (i === 0) ctx.moveTo(Math.min(0, x0), Y(p.bpm)); else ctx.lineTo(x0, Y(p.bpm));
        ctx.lineTo(x1, Y(p.ramped && i + 1 < pts.length ? p.bpmEnd : p.bpm));
      });
      ctx.stroke();
      ctx.font = '500 9.5px ' + HX.css('--mono'); ctx.textBaseline = 'top'; ctx.fillStyle = colors['--tx1'];
      pts.forEach((p) => { const x = XS(p.time); if (x < w && x > -60) { ctx.fillRect(Math.round(x), r.y + 2, 1, r.hgt - 4); ctx.fillText(p.ramped ? fmtBpm(p.bpm) + '→' + fmtBpm(p.bpmEnd) : fmtBpm(p.bpm), Math.max(2, x + 3), r.y + 2); } });
    }
    ctx.fillStyle = colors['--line']; ctx.fillRect(0, r.y + r.hgt - 1, w, 1);
  };

  A.info = function (hit) {
    if (hit.row.tempoLane) return 'Tempo map · ramps are drawn as slopes · click to place the playhead';
    const info = infoOf(hit.row.t, hit.row.control) || { name: hit.row.control };
    return info.name + ' automation of ' + hit.row.t.name + ' · drag a point' + (isLevel(hit.row.control) ? ' (S-curves, at most ' + cap(hit.row.control) + ' dB a move, under ' + MAX_SLOPE + ' dB/s)' : '') + ' · double-click adds a point on the line · ⌥-click removes one · one undo step each';
  };

  /* ── the pointer ── */
  function nearest(t, control, xPx, yPx, g) {
    const info = infoOf(t, control), lane = laneOf(t, control);
    const r = g.row, y0 = r.y + 4, hh = r.hgt - 9;
    let best = -1, bd = 8;
    for (const i of anchors(control, lane.points)) {
      const p = lane.points[i];
      const d = Math.hypot(g.X(HX.secToBeats(p.t)) - xPx, y0 + hh * (1 - toPos(info, p.v)) - yPx);
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }
  A.pointerDown = function (e, hit, g) {
    const { rect, B, lanesWrap, X } = g;
    const t = hit.row.t, control = hit.row.control;
    if (hit.row.tempoLane) return HX.locate(g.snap(hit.beat));
    HX.select(t.id);
    const info = infoOf(t, control), lane = laneOf(t, control);
    if (!info || !lane) return;
    const x = e.clientX - rect.left, y = e.clientY - rect.top;
    const i = nearest(t, control, x, y, { row: hit.row, X });
    if (i < 0) { A.sel = null; HX.locate(hit.beat); A.refreshHeaders(); return; }
    A.sel = { trackId: t.id, control, i };
    if (e.altKey) { A.remove(t, control, i); return; }
    const p0 = lane.points[i];
    const y0 = hit.row.y + 4, hh = hit.row.hgt - 9;
    A.drag = { trackId: t.id, control, i, t: p0.t, v: p0.v, preview: lane.points, moved: false, held: '' };
    lanesWrap.setPointerCapture(e.pointerId);
    const mv = (ev) => {
      if (!A.drag) return;
      if (Math.abs(ev.clientX - e.clientX) < 2 && Math.abs(ev.clientY - e.clientY) < 2 && !A.drag.moved) return;
      A.drag.moved = true;
      const tt = HX.beatsToSec(Math.max(0, B(ev.clientX - rect.left)));
      const vv = fromPos(info, 1 - (ev.clientY - rect.top - y0) / hh);
      const c = A.propose(t, control, i, tt, vv);
      Object.assign(A.drag, { t: c.t, v: c.v, preview: c.points, held: c.held, call: c.call });
      HX.arrange.dirty = true;
    };
    const up = () => {
      lanesWrap.removeEventListener('pointermove', mv); lanesWrap.removeEventListener('pointerup', up); lanesWrap.removeEventListener('pointercancel', up);
      const d = A.drag; A.drag = null; HX.arrange.dirty = true;
      if (!d || !d.moved || !d.call) { A.refreshHeaders(); return; }
      A.write(t, control, d.call, info.name + ' automation of ' + t.name + ': point to ' + fmt(info, d.v) + ' at ' + d.t.toFixed(2) + ' s');
    };
    lanesWrap.addEventListener('pointermove', mv); lanesWrap.addEventListener('pointerup', up); lanesWrap.addEventListener('pointercancel', up);
  };
  A.dblclick = function (hit) {
    if (!hit || !hit.row.autoLane) return false;
    A.add(hit.row.t, hit.row.control, HX.beatsToSec(Math.max(0, hit.beat)));
    return true;
  };

  /* ── the gestures: each one engine call ── */
  /* moving point i to (tt, vv): clamped between its neighbours and to the rules -> { t, v, points, call, held } */
  A.propose = function (t, control, i, tt, vv) {
    const lane = laneOf(t, control), pts = lane.points, level = isLevel(control);
    const an = anchors(control, pts), k = an.indexOf(i);
    const a = k > 0 ? pts[an[k - 1]] : null, b = k >= 0 && k + 1 < an.length ? pts[an[k + 1]] : null;
    let held = '';
    let nt = HX.clamp(tt, a ? a.t + MIN_GAP : 0, b ? b.t - MIN_GAP : Infinity);
    let nv = vv;
    const p0 = pts[i];
    if (level && (!a || !b)) { if (nv !== p0.v) held = 'the first and last points stay on the line'; nv = p0.v; }
    if (level && a && b) {
      const ok = allowed(control, a, b, nt);
      if (!ok) { nt = p0.t; nv = p0.v; held = 'held by the rules'; }
      else if (nv < ok[0] || nv > ok[1]) { nv = Math.round(HX.clamp(nv, ok[0], ok[1]) * 10) / 10; if (nv < ok[0]) nv += 0.1; if (nv > ok[1]) nv -= 0.1; held = 'at most ' + cap(control) + ' dB a move, under ' + MAX_SLOPE + ' dB/s'; }
    }
    if (level && (!a || !b)) {
      /* an edge point moves in time only; its move to the neighbour must still keep to the rules */
      const n = a || b;
      if (n && problem(control, a ? [n, { t: nt, v: nv }] : [{ t: nt, v: nv }, n])) { nt = p0.t; held = 'held by the rules'; }
    }
    if (Math.abs(nt - p0.t) < 1e-6 && Math.abs((nv == null ? -999 : nv) - (p0.v == null ? -999 : p0.v)) < 1e-9) return { t: nt, v: nv, points: pts, call: null, held };
    let call;
    nt = Math.round(nt * 1e4) / 1e4;
    /* the neighbours' times go back exactly as the engine gave them: a range edge a hair off one would leave the old
       point beside the new edge, a jump the engine refuses */
    const P = (q) => ({ time: q.t, value: q.v });
    /* the range reaches a hair past the outer points, so they are written again as given (no guard point a hair from
       them: the engine reports values to 0.001 dB, and a guard beside a point read that way is a jump it refuses) */
    const edge = (x, dir) => Math.round((x + dir * EDGE) * 1e6) / 1e6;
    if (level) {
      const list = [a, { t: nt, v: nv }, b].filter(Boolean);
      const lo = Math.min(list[0].t, p0.t), hi = Math.max(list[list.length - 1].t, p0.t);
      if (!a) list.unshift({ t: lo, v: nv });
      if (!b) list.push({ t: hi, v: nv });
      const uniq = list.filter((q, j) => j === 0 || q.t - list[j - 1].t > 1e-6);
      call = { tool: 'automation_write', args: { track_id: t.id, control, points: uniq.map(P), mode: 'replace-range', curve: 's_curve', start: edge(uniq[0].t, -1), end: edge(uniq[uniq.length - 1].t, 1), guard: false } };
    } else {
      const lo = Math.min(nt, p0.t) - EPS, hi = Math.max(nt, p0.t) + EPS;
      call = { tool: 'automation_write', args: { track_id: t.id, control, points: [P({ t: nt, v: nv })], mode: 'replace-range', curve: 'linear', start: lo, end: hi, guard: false } };
    }
    return { t: nt, v: nv, points: after(pts, call), call, held };
  };

  A.add = function (t, control, tt) {
    const info = infoOf(t, control), lane = laneOf(t, control);
    if (!info || !lane) return null;
    if (lane.points.some((p) => Math.abs(p.t - tt) < MIN_GAP)) { HX.toast('There is a point there already'); return null; }
    let v = lineAt(lane, info, tt);
    if (v == null) { HX.toast('Not added: the control’s value is not known'); return null; }
    if (kindOf(control) === 'mute') v = v >= 0.5 ? 1 : 0;
    const at = Math.round(tt * 1e6) / 1e6;
    return A.write(t, control, { tool: 'automation_write', args: { track_id: t.id, control, points: [{ time: at, value: v }], mode: 'replace-range', curve: 'linear', start: at, end: at, guard: false } },
      'Add a ' + info.name + ' automation point to ' + t.name + ' at ' + at.toFixed(2) + ' s');
  };

  A.remove = function (t, control, i) {
    const info = infoOf(t, control), lane = laneOf(t, control);
    if (!info || !lane || !lane.points[i]) return null;
    const pts = lane.points, an = anchors(control, pts), k = an.indexOf(i);
    const p = pts[i], label = 'Remove a ' + info.name + ' automation point of ' + t.name;
    if (k < 0) { HX.toast('Not removed: pick a point where the line turns or is flat (the points inside an S-curve go with it)', 4200); return null; }
    if (isLevel(control)) {
      const a = k > 0 ? pts[an[k - 1]] : null, b = k + 1 < an.length ? pts[an[k + 1]] : null;
      if (a && b) {
        const why = problem(control, [a, b]);
        if (why) { HX.toast('Not removed: without this point ' + why + ' (smooth-automation rules)', 4200); return null; }
        return A.write(t, control, { tool: 'automation_write', args: { track_id: t.id, control, points: [{ time: a.t, value: a.v }, { time: b.t, value: b.v }], mode: 'replace-range', curve: 's_curve', start: Math.round((a.t - EDGE) * 1e6) / 1e6, end: Math.round((b.t + EDGE) * 1e6) / 1e6, guard: false } }, label);
      }
      const n = a || b;
      if (n && Math.abs((n.v == null ? -999 : n.v) - (p.v == null ? -999 : p.v)) > ON_LINE) { HX.toast('Not removed: this point leads into a move; remove the move’s middle point first', 4200); return null; }
      const lo = a ? a.t + EPS : p.t - EPS, hi = b ? b.t - EPS : p.t + EPS;
      return A.write(t, control, { tool: 'automation_clear', args: { track_id: t.id, control, start: Math.min(lo, p.t - EPS), end: Math.max(hi, p.t + EPS) } }, label);
    }
    return A.write(t, control, { tool: 'automation_clear', args: { track_id: t.id, control, start: p.t - EPS, end: p.t + EPS } }, label);
  };

  /* one gesture -> one op on the shared op path (store.js): one history entry, one engine undo step */
  A.write = function (t, control, call, label) {
    const lane = laneOf(t, control);
    const before = { points: lane.points.map((p) => Object.assign({}, p)), state: lane.state };
    const pts = after(lane.points, call);
    const nextState = call.tool === 'automation_write' && call.args.state !== 'keep' ? (call.args.state || 'play') : lane.state;
    const afterV = { points: pts, state: nextState, call };
    A.sel = null;
    return HX.commit(label, [{ trackId: t.id, param: 'autoPoints', key: control, before, after: afterV }]);
  };

  A.setState = function (t, control, state) {
    const lane = laneOf(t, control); if (!lane) return null;
    const info = infoOf(t, control);
    return HX.commit((state === 'manual' ? 'Stop playing ' : 'Play ') + 'the ' + info.name + ' automation of ' + t.name,
      [{ trackId: t.id, param: 'autoState', key: control, before: lane.state || 'manual', after: state }]);
  };

  /* the keyboard, on a focused lane header */
  function keys(e, t, control) {
    if (e.target !== e.currentTarget || HX.modalOpen()) return;
    const lane = laneOf(t, control), info = infoOf(t, control); if (!lane || !info) return;
    const an = anchors(control, lane.points);
    const cur = A.sel && A.sel.trackId === t.id && A.sel.control === control ? an.indexOf(A.sel.i) : -1;
    const done = () => { e.preventDefault(); e.stopPropagation(); };
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      done();
      if (!an.length) return HX.toast('No points yet: A adds one at the playhead');
      let k = cur;
      if (k < 0) { const now = HX.beatsToSec(HX.pos()); k = e.key === 'ArrowRight' ? an.findIndex((j) => lane.points[j].t >= now - 1e-6) : an.length - 1 - [...an].reverse().findIndex((j) => lane.points[j].t <= now + 1e-6); if (k < 0 || k >= an.length) k = e.key === 'ArrowRight' ? an.length - 1 : 0; }
      else k = HX.clamp(k + (e.key === 'ArrowRight' ? 1 : -1), 0, an.length - 1);
      A.sel = { trackId: t.id, control, i: an[k] };
      HX.locate(HX.secToBeats(lane.points[an[k]].t));
      A.refreshHeaders();
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      done();
      if (cur < 0) return HX.toast('Pick a point first: ← or →');
      const p = lane.points[A.sel.i], d = step(info, e.shiftKey) * (e.key === 'ArrowUp' ? 1 : -1);
      const c = A.propose(t, control, A.sel.i, p.t, (p.v == null ? -60 : p.v) + d);
      if (!c.call) return HX.toast(c.held ? 'Not moved: ' + c.held : 'Not moved');
      const i = A.sel.i;
      A.write(t, control, c.call, info.name + ' automation of ' + t.name + ': point to ' + fmt(info, c.v)).then(() => {
        const l2 = laneOf(t, control), an2 = l2 ? anchors(control, l2.points) : [];
        const j = an2.reduce((best, q) => (best < 0 || Math.abs(l2.points[q].t - c.t) < Math.abs(l2.points[best].t - c.t) ? q : best), -1);
        if (j >= 0) { A.sel = { trackId: t.id, control, i: j }; A.refreshHeaders(); }
        else if (i >= 0) A.refreshHeaders();
      });
    } else if (e.key === 'a' || e.key === 'A' || e.key === '+' || e.key === '=' || e.key === 'Insert') {
      if (e.metaKey || e.ctrlKey) return;
      done(); A.add(t, control, HX.beatsToSec(HX.pos()));
    } else if (e.key === 'Delete' || e.key === 'Backspace') {
      done();
      if (cur < 0) return HX.toast('Pick a point first: ← or →');
      A.remove(t, control, A.sel.i);
    } else if (e.key === 'p' || e.key === 'P') {
      if (e.metaKey || e.ctrlKey) return;
      done(); A.setState(t, control, lane.state && lane.state !== 'manual' ? 'manual' : 'play');
    }
  }
  A.keys = keys;

  /* the headers again, keeping the focus where it was (arrange.js puts it back by data-hk) */
  A.refreshHeaders = () => { HX.renderArrangeHeaders && HX.renderArrangeHeaders(); HX.arrange.dirty = true; };

  /* ── the ops (store.js's op path; regions.js's engine undo) ── */
  const H = (HX.opHandlers = HX.opHandlers || {});
  H.autoPoints = {
    undo: (op, v) => (v && v.call && v.call.tool === 'automation_clear' ? 'clear automation' : 'write automation'),
    tracks: () => [],
    get: (op) => { const t = HX.track(op.trackId), l = t && laneOf(t, op.key); return l && { points: l.points.map((p) => Object.assign({}, p)), state: l.state }; },
    apply(op, v) {
      const t = HX.track(op.trackId), l = t && laneOf(t, op.key); if (!l || !v) return;
      l.points = v.points.map((p) => Object.assign({}, p)); if (v.state) l.state = v.state;
      HX.arrange.dirty = true;
    },
    call: (op, v) => (v && v.call ? v.call : null),
    done: (op) => A.loadLane(op.trackId, op.key).then(A.refreshHeaders).catch(() => {}),
  };
  H.autoState = {
    get: (op) => { const t = HX.track(op.trackId), l = t && laneOf(t, op.key); return l && l.state; },
    apply(op, v) { const t = HX.track(op.trackId), l = t && laneOf(t, op.key); if (!l) return; l.state = v; A.refreshHeaders(); },
    call: (op, v) => ({ tool: 'automation_set_state', args: { track_id: op.trackId, control: op.key, state: v } }),
  };

  /* ── reading from the engine ── */
  A.load = async function (trackId) {
    const t = HX.track(trackId); if (!t) return;
    if (!HX.mcp.connected) { if (!A.data[trackId]) A.data[trackId] = mockData(t); return; }
    const r = await HX.mcp.call('automation_list', { track_id: trackId }, { quiet: true });
    const old = A.data[trackId];
    A.data[trackId] = { facts: r, controls: (r.controls || []).map((c) => Object.assign({}, c)), lanes: old ? old.lanes : {} };
  };
  A.loadLane = async function (trackId, control) {
    if (!A.data[trackId]) await A.load(trackId);
    const d = A.data[trackId]; if (!d) return;
    if (!HX.mcp.connected) { if (!d.lanes[control]) d.lanes[control] = { points: [], state: 'manual' }; return; }
    const r = await HX.mcp.call('automation_get', { track_id: trackId, control }, { quiet: true });
    d.lanes[control] = { points: (r.pointList || []).filter((p) => typeof p.time === 'number').map((p) => ({ t: p.time, v: p.value })), state: r.state || 'manual' };
    const c = d.controls.find((x) => x.control === control); if (c) { c.points = d.lanes[control].points.length; c.state = d.lanes[control].state; }
    HX.arrange.dirty = true;
  };
  A.reloadShown = async function () {
    for (const t of HX.allTracks()) for (const c of shownOf(t)) { try { await A.loadLane(t.id, c); } catch (e) { HX.log('err', 'automation_get · ' + e.message); } }
    if (A.tempo.shown) await A.loadTempo().catch(() => {});
    A.refreshHeaders();
  };
  A.loadTempo = async function () {
    if (!HX.mcp.connected) { A.tempo.points = [{ time: 0, bar: 1, bpm: S.session.tempo, bpmEnd: S.session.tempo, ramped: false }]; A.tempo.loaded = true; A.refreshHeaders(); return; }
    const r = await HX.mcp.call('tempo_get_map', {}, { quiet: true });
    A.tempo.points = (r.tempos || []).map((p) => ({ time: p.time, bar: p.bbt ? p.bbt.bar : null, bpm: p.bpm, bpmEnd: typeof p.bpmEnd === 'number' ? p.bpmEnd : p.bpm, ramped: !!p.ramped }));
    A.tempo.loaded = true;
    A.refreshHeaders();
  };

  /* the mock: the first vocal track's fader with one gentle ride (two S-curves, -2.5 dB for a line) */
  function mockData(t) {
    const ride = t.role === 'vocal' ? sCurve([{ t: 20, v: 0 }, { t: 21.2, v: -2.5 }, { t: 26, v: -2.5 }, { t: 27.2, v: 0 }]) : [];
    return {
      facts: { trackId: t.id, trackName: t.name, isBus: false },
      controls: [
        { control: 'gain', name: 'Fader', unit: 'dB', current: t.faderDb || 0, points: ride.length, state: ride.length ? 'play' : 'manual' },
        { control: 'trim', name: 'Trim', unit: 'dB', min: -20, max: 20, current: 0, points: 0, state: 'manual' },
        { control: 'pan_azimuth', name: 'Pan', unit: 'pan', min: -1, max: 1, current: t.pan || 0, points: 0, state: 'manual' },
        { control: 'mute', name: 'Mute', unit: 'toggle', min: 0, max: 1, current: 0, points: 0, state: 'manual' },
      ],
      lanes: { gain: { points: ride, state: ride.length ? 'play' : 'manual' }, trim: { points: [], state: 'manual' }, pan_azimuth: { points: [], state: 'manual' }, mute: { points: [], state: 'manual' } },
    };
  }

  HX.on('session', () => {
    A.data = {}; A.sel = null; A.drag = null; A.tempo.points = []; A.tempo.loaded = false;
    if (!S.session) return;
    try { A.tempo.shown = localStorage.getItem('hx.auto.tempo') === '1'; } catch (e) {}
    S.session.tracks.forEach((t) => { if (Array.isArray(memo[memoKey(t)])) t.autoShown = memo[memoKey(t)].slice(); });
    if (!HX.mcp.connected) {
      const v = S.session.tracks.find((x) => x.role === 'vocal');
      if (v && memo[memoKey(v)] === undefined) v.autoShown = ['gain'];
      for (const t of HX.allTracks()) if (shownOf(t).length) A.data[t.id] = mockData(t);
      if (A.tempo.shown) A.loadTempo();
      HX.renderArrangeHeaders && HX.renderArrangeHeaders();
      return;
    }
    if (!available()) { HX.allTracks().forEach((t) => (t.autoShown = [])); return; }
    A.reloadShown().catch((e) => HX.log('err', 'automation · ' + e.message));
  });
  /* the Assistant changed something (an automation card, a tempo change): the shown lanes and the tempo read again */
  HX.on('assistant', (x) => { if (x && x.what === 'answered' && x.how === 'approved' && HX.mcp.connected) setTimeout(() => A.reloadShown().catch(() => {}), 400); });
})();
