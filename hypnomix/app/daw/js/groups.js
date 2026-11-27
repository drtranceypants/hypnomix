/* HypnoMix · group tracks, as in Live: on the engine a group is a route group plus its bus, made together
   (group_create). Here the bus is the group's header: it sits right above its tracks, folds them away (▸ / ▾,
   saved with the session: group_set folded), and its fader is the group fader (an ordinary fader on the bus).
   Members are indented under it. "Group…" (Arrangement tools, ⌘G) makes one from tracks you tick, "Ungroup" on the
   header undoes it; both ask first, because the engine keeps routing out of its undo history.
   Hooks elsewhere are one line each: arrange.js (rows, headers), mixer.js (strips), app.js/index.html (load). */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  const G = (HX.groups = { list: [], byBus: new Map(), byMember: new Map() });
  const POLL_MS = 3000;
  let sig = '', timer = null, busy = false;

  G.ofMember = (t) => (t && G.byMember.get(t.id)) || null;
  G.ofBus = (t) => (t && G.byBus.get(t.id)) || null;
  G.hidden = (t) => { const g = G.ofMember(t); return !!(g && g.folded && g.busId); };
  G.available = () => !!(HX.mcp.connected && HX.mcp.has('group_list') && HX.mcp.has('group_create'));
  /* a track folded away is never the selected one: the selection moves to its group's header (the bus), which shows */
  G.keepVisible = function () {
    const t = HX.track(S.ui.trackId), g = t && G.hidden(t) ? G.ofMember(t) : null;
    if (g && HX.track(g.busId)) HX.select(g.busId);
  };

  /* group_list → which strips are buses and members; the buses move from the returns to above their tracks */
  function apply(groups) {
    G.list = groups; G.byBus = new Map(); G.byMember = new Map();
    for (const g of groups) {
      if (g.busId) G.byBus.set(g.busId, g);
      for (const m of g.members || []) G.byMember.set(m.trackId, g);
    }
    const s = S.session; if (!s) return;
    for (const t of HX.allTracks()) { if (t.isGroup && !G.byBus.has(t.id)) { t.isGroup = false; if (t.kind === 'bus') { s.tracks = s.tracks.filter((x) => x !== t); s.returns.push(t); t.isReturn = true; } } }
    for (const g of groups) {
      if (!g.busId) continue;
      const i = s.returns.findIndex((t) => t.id === g.busId);
      if (i >= 0) {
        const [b] = s.returns.splice(i, 1);
        const j = s.tracks.findIndex((t) => (g.members || []).some((m) => m.trackId === t.id));
        s.tracks.splice(j < 0 ? s.tracks.length : j, 0, b);
      }
      const b = HX.track(g.busId);
      if (b) { b.isGroup = true; b.isReturn = false; }
    }
  }
  const signature = (groups) => JSON.stringify(groups.map((g) => [g.groupId, g.name, g.busId, g.folded, (g.members || []).map((m) => m.trackId)]));

  G.read = async function () {
    if (!G.available() || !S.session || busy) return false;
    busy = true;
    try {
      const r = await HX.liveEngine.quiet('group_list');
      const groups = (r && r.groups) || [];
      const s2 = signature(groups);
      if (s2 === sig && groups.every((g) => !g.busId || (HX.track(g.busId) || {}).isGroup)) return false;
      sig = s2;
      apply(groups);
      G.keepVisible();
      HX.emit('session-light'); if (HX.arrange) HX.arrange.dirty = true;
      return true;
    } catch (e) { return false; } finally { busy = false; }
  };
  function poll() { clearTimeout(timer); timer = setTimeout(async () => { await G.read(); if (HX.mcp.connected) poll(); }, POLL_MS); }
  HX.on('session', () => { sig = ''; G.list = []; G.byBus = new Map(); G.byMember = new Map(); if (G.available()) { G.read(); poll(); } addTool(); });
  HX.on('live', () => { if (G.available()) { G.read(); poll(); } else clearTimeout(timer); addTool(); });

  /* ── fold / unfold: the route group's hidden flag, so it is saved with the session ── */
  G.fold = async function (g, folded) {
    if (HX.editBlocked()) return HX.toast(HX.editBlocked(), 3600);
    const was = g.folded; g.folded = folded;
    if (folded) G.keepVisible();
    HX.emit('session-light'); if (HX.arrange) HX.arrange.dirty = true;
    try {
      const r = await HX.mcp.call('group_set', { group_id: g.groupId, folded });
      g.folded = !!(r && r.group && r.group.folded);
    } catch (e) { g.folded = was; HX.toast('Fold: ' + e.message, 3600); }
    sig = ''; HX.emit('session-light'); if (HX.arrange) HX.arrange.dirty = true;
  };

  /* ── the header of a group bus, and its members' indent (arrange.js calls this for every header) ── */
  G.decorateHeader = function (t, el, nameEl) {
    const g = G.ofBus(t);
    if (g) {
      el.classList.add('th-group');
      const n = (g.members || []).length;
      const tog = h('button.grp-fold', { 'aria-label': (g.folded ? 'Unfold ' : 'Fold ') + g.name, 'aria-expanded': String(!g.folded), 'data-info': (g.folded ? 'Unfold ' : 'Fold ') + g.name + ' (' + n + ' track' + (n === 1 ? '' : 's') + ')',
        onpointerdown: (e) => e.stopPropagation(), onclick: (e) => { e.stopPropagation(); G.fold(g, !g.folded); } }, g.folded ? '▸' : '▾');
      (nameEl.querySelector('b') || nameEl).prepend(tog);
      const small = nameEl.querySelector('small');
      if (small) small.textContent = 'Group · ' + n + ' track' + (n === 1 ? '' : 's') + ' · the group fader';
      const un = h('button.grp-x', { 'aria-label': 'Ungroup ' + g.name, 'data-info': 'Ungroup ' + g.name + ': its tracks go to the master again, the group bus goes', onpointerdown: (e) => e.stopPropagation(), onclick: (e) => { e.stopPropagation(); G.ungroup(g); } }, 'Ungroup');
      el.append(un);
      return;
    }
    if (G.ofMember(t)) el.classList.add('th-member');
  };
  /* a mixer strip: the bus gets a "group" tag, members a thin line in the group's colour */
  G.decorateStrip = function (t, el) {
    const g = G.ofBus(t);
    if (g) {
      el.classList.add('strip-group'); el.dataset.groupName = g.name;
      const n = el.querySelector('.s-name'); if (n) n.dataset.info = 'Group ' + g.name + ' · its bus: this fader is the group fader (' + (g.members || []).length + ' tracks)';
      return;
    }
    if (G.ofMember(t)) el.classList.add('strip-member');
  };

  /* ── make a group ── */
  function addTool() {
    const tools = HX.$('.arr-tools'); if (!tools || HX.$('#groupBtn')) return;
    const b = h('button.btn.ghost#groupBtn', { 'data-info': 'Group tracks (⌘G): a group track with its own bus and fader, as in Live', onclick: () => G.create() }, 'Group…');
    const imp = HX.$('#importBtn');
    tools.insertBefore(b, imp || null);
  }
  HX.on('live', () => { const b = HX.$('#groupBtn'); if (b) b.disabled = !G.available(); });

  G.create = async function (preselect) {
    if (!G.available()) return HX.toast('Groups need the engine (Start, top right)');
    if (HX.editBlocked()) return HX.toast(HX.editBlocked(), 3600);
    const cand = S.session.tracks.filter((t) => t.real && !t.isGroup && !G.ofMember(t));
    if (cand.length < 1) return HX.toast('Every track is in a group already');
    const sel = new Set(preselect || HX.selectedTrackIds());   /* every selected track is ticked (shift-click, ⌘-click) */
    const name = h('input.grp-name', { type: 'text', value: 'Group', 'aria-label': 'Group name' });
    const list = h('div.grp-list');
    cand.forEach((t) => {
      const cb = h('input', { type: 'checkbox', value: t.id });
      cb.checked = sel.has(t.id);
      list.append(h('label', null, cb, ' ', t.name));
    });
    const body = h('div.grp-form', null, h('label', null, 'Name ', name), list,
      h('small', null, 'The tracks go to a new bus with the group’s name (its fader is the group fader); they stay as they are otherwise. The engine cannot undo this: Ungroup puts it back.'));
    const yes = await HX.confirm('Group tracks', body, 'Group');
    if (!yes) return;
    const ids = [...list.querySelectorAll('input:checked')].map((x) => x.value);
    if (!ids.length) return HX.toast('Tick at least one track');
    let r;
    try { r = await HX.mcp.call('group_create', { name: name.value.trim() || 'Group', track_ids: ids }); }
    catch (e) { return HX.toast('Not grouped: ' + e.message, 4200); }
    const made = (r && r.group && r.group.name) || name.value.trim() || 'Group';
    HX.log('mcp', 'group_create ' + made + ' · ' + ids.length + ' track(s)');
    HX.toast('Grouped ' + ids.length + ' track' + (ids.length > 1 ? 's' : '') + ' as ' + made);
    /* the group is made (and the engine cannot undo it): a failed read of the session is said as that, not as "Not grouped" */
    try { await HX.loadFromEngine(); }
    catch (e) { HX.toast('Grouped as ' + made + ', but the view could not read the session again: ' + e.message + ' (it tries again in a few seconds)', 5200); }
  };

  G.ungroup = async function (g) {
    if (HX.editBlocked()) return HX.toast(HX.editBlocked(), 3600);
    const bus = HX.track(g.busId);
    const work = bus && bus.devices && bus.devices.length;
    const yes = await HX.confirm('Ungroup “' + g.name + '”?', 'Its ' + (g.members || []).length + ' track(s) go to the master again and the group bus is removed'
      + (work ? ', with its ' + bus.devices.length + ' plug-in(s)' : '') + '. The engine cannot undo this.', 'Ungroup');
    if (!yes) return;
    try { await HX.mcp.call('group_delete', { group_id: g.groupId, confirm: true }); }
    catch (e) { return HX.toast('Not ungrouped: ' + e.message, 4200); }
    HX.toast('Ungrouped ' + g.name);
    try { await HX.loadFromEngine(); }
    catch (e) { HX.toast('Ungrouped ' + g.name + ', but the view could not read the session again: ' + e.message + ' (it tries again in a few seconds)', 5200); }
  };

  document.addEventListener('keydown', (e) => {
    if (HX.modalOpen() || (HX.noEngineScreen && HX.noEngineScreen()) || e.repeat) return;   // dead behind a dialog and on the no-engine screen
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === 'g' && !(e.target.closest && e.target.closest('input,textarea,select,[contenteditable]'))) {
      e.preventDefault();
      if (!G.available()) return HX.toast('Groups need the engine (Start, top right)');
      G.create();
    }
  });
})();
