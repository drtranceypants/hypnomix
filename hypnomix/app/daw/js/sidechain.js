/* Hypnomix · the sidechain source picker on a device (a compressor keyed from another track, like Live's
   Sidechain section). Shown on every engine plug-in that can take a key (plugin_get_sidechain: canSidechain):
   "Sidechain: none / <track>". Choosing a track calls plugin_set_sidechain (a pre-fader send from that track
   into the plug-in's key input, and the plug-in's own Sidechain switch on); "none" takes the send away.
   It is an op like any other ({param: 'sidechain'}), so ⌘Z puts the previous source back (the engine keeps
   routing out of its own undo history, so undo re-sends the old source). devices.js calls decorate() once per device. */
(function () {
  'use strict';
  const HX = window.HX, S = HX.S, h = HX.h;
  const SC = (HX.sidechain = { info: new Map() });   // trackId|pluginIndex → plugin_get_sidechain entry
  const key = (tid, idx) => tid + '|' + idx;
  const pending = new Set();

  SC.available = () => !!(HX.mcp.connected && HX.mcp.has('plugin_set_sidechain') && HX.mcp.has('plugin_get_sidechain'));

  async function read(t, d) {
    const k = key(t.id, d.index);
    if (pending.has(k)) return;
    pending.add(k);
    try {
      const r = await HX.liveEngine.quiet('plugin_get_sidechain', { track_id: t.id, plugin_index: d.index });
      const e = r && r.sidechains && r.sidechains[0];
      const before = JSON.stringify(SC.info.get(k) || null);
      if (e) SC.info.set(k, e); else SC.info.delete(k);
      if (JSON.stringify(e || null) !== before && HX.renderDevices) HX.renderDevices();
    } catch (err) { /* an older engine: no picker */ } finally { pending.delete(k); }
  }
  const sourceOf = (e) => (e && e.sources && e.sources[0] && e.sources[0].trackId) || '';

  /* the op: value = the source's route id, '' = none */
  HX.opHandlers = HX.opHandlers || {};
  /* storeOwned: the store sends it through liveEngine.send (hooked below), not as a region op */
  HX.opHandlers.sidechain = {
    storeOwned: true,
    get: (op) => sourceOf(SC.info.get(key(op.trackId, op.key))),
    apply: (op, v) => {
      const k = key(op.trackId, op.key), e = SC.info.get(k);
      if (e) SC.info.set(k, Object.assign({}, e, { sources: v ? [{ trackId: v, name: (HX.track(v) || {}).name || v, kind: 'send', tap: 'pre_fader' }] : [] }));
      if (HX.renderDevices) HX.renderDevices();
    },
  };
  /* what it calls, for change cards and the log */
  const describe0 = HX.describeOp;
  HX.describeOp = function (op) {
    if (op.param !== 'sidechain') return describe0(op);
    return { tool: 'plugin_set_sidechain', args: { track_id: op.trackId, plugin_index: op.key, source_track_id: op.after || 'none' } };
  };
  /* the store sends ops it does not know through liveEngine.send: take ours there */
  function hook() {
    const L = HX.liveEngine; if (!L || L._scHooked) return;
    const prev = L.send;
    L.send = function (op, value) {
      if (op.param !== 'sidechain') return prev.apply(this, arguments);
      const t = HX.track(op.trackId);
      if (!HX.mcp.connected || !t || !t.real) { HX.log('mock', 'plugin_set_sidechain ' + JSON.stringify({ track_id: op.trackId, plugin_index: op.key, source_track_id: value || 'none' })); return Promise.resolve(); }
      return HX.mcp.call('plugin_set_sidechain', { track_id: op.trackId, plugin_index: op.key, source_track_id: value || 'none' })
        .then((r) => { if (r && r.sidechain) SC.info.set(key(op.trackId, op.key), r.sidechain); if (HX.renderDevices) HX.renderDevices(); return r; });
    };
    L._scHooked = true;
  }
  hook();
  HX.on('live', hook);
  HX.on('session', () => SC.info.clear());

  SC.decorate = function (t, d, body) {
    if (!d.real || !t.real || !SC.available()) return;
    const e = SC.info.get(key(t.id, d.index));
    if (!e) { read(t, d); return; }
    if (!e.canSidechain) return;
    const cur = sourceOf(e);
    const sel = h('select.sc-src', { 'aria-label': 'Sidechain source for ' + d.name, 'data-info': d.name + ' · Sidechain: the track that keys it (a pre-fader send, after that track’s plug-ins)' });
    sel.append(h('option', { value: '' }, 'none'));
    const own = HX.groups && HX.groups.ofMember(t);   /* its own group bus: the engine refuses (feedback) */
    HX.allTracks().filter((x) => x.real && x.id !== t.id && !x.isMaster && !(own && own.busId === x.id)).forEach((x) => {
      const o = h('option', { value: x.id }, x.name);
      if (x.id === cur) o.selected = true;
      sel.append(o);
    });
    if (cur && !HX.track(cur)) sel.append(h('option', { value: cur, selected: true }, (e.sources[0].name || cur)));
    sel.addEventListener('change', () => {
      const v = sel.value, src = HX.track(v);
      HX.edit({ trackId: t.id, param: 'sidechain', key: d.index }, v, d.name + ' on ' + t.name + ' keyed from ' + (src ? src.name : 'nothing'));
    });
    const sw = e.switch ? h('span.sc-sw' + (e.switch.on ? '.on' : ''), { 'data-info': 'The plug-in’s own “' + e.switch.label + '” switch: ' + (e.switch.on ? 'on (it listens to the key)' : 'off (it listens to its own track)') }, e.switch.on ? 'key on' : 'key off') : null;
    body.append(h('div.sc-row', null, h('span.label', null, 'Sidechain'), sel, sw));
  };
})();
