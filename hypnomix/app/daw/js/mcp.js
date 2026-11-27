/* Hypnomix · client for Ardour's MCP HTTP surface (libs/surfaces/mcp_http).
   JSON-RPC 2.0 over HTTP POST to /mcp. Tool names are the underscore aliases from tools_json.inc
   (tracks_list, transport_play, track_set_fader_db, ...); the server canonicalises them to slash form.

   The surface sends no CORS headers, so a page opened from file:// cannot read its replies. The HypnoMix app
   serves this page at /daw/ and forwards POST /mcp to the engine it runs (hypnomix/app/daw.py), on the same
   origin, with the page's token (window.HX_TOKEN). Opened from file://, it can only show the mock session. */
(function () {
  'use strict';
  const HX = window.HX;

  const DIRECT = 'http://127.0.0.1:4820/mcp';
  const viaProxy = location.protocol.startsWith('http') && location.port !== '4820';
  const token = window.HX_TOKEN && !/^__/.test(window.HX_TOKEN) ? window.HX_TOKEN : '';
  const clientVersion = window.HX_VERSION && !/^__/.test(window.HX_VERSION) ? window.HX_VERSION : 'unknown';   // the app's own, put in the page by the server

  /* tools that only look: everything else is taken as a change (the page shows "unsaved" at once; the app's own count decides).
     Launching or stopping a clip or a scene plays, like the transport: it changes nothing that is saved. */
  const READS = /(_get_|_get$|_list|_status|_describe)|^(transport_|meters_|session_(get|save|export|list)|export_)|^(cue_launch|cue_stop|scene_launch)$/;

  const mcp = (HX.mcp = {
    endpoint: viaProxy ? '/mcp' : DIRECT,
    connected: false,
    serverInfo: null,
    tools: [],
    _id: 0,
    timeoutMs: 4000,

    async rpc(method, params, isNotification) {
      const body = { jsonrpc: '2.0', method };
      if (params !== undefined) body.params = params;
      if (!isNotification) body.id = ++mcp._id;
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), mcp.timeoutMs);
      let res;
      try {
        res = await fetch(mcp.endpoint, {
          method: 'POST',
          headers: Object.assign({ 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' },
            token && mcp.endpoint === '/mcp' ? { 'X-Hypnomix': token } : {}),
          body: JSON.stringify(body),
          signal: ctl.signal,
        });
      } catch (e) {
        throw new Error(e.name === 'AbortError' ? 'timed out after ' + mcp.timeoutMs + ' ms' : 'cannot reach ' + mcp.endpoint + (location.protocol === 'file:' ? ' (from file:// the browser blocks it: open it from the HypnoMix app, /daw/)' : ''));
      } finally {
        clearTimeout(timer);
      }
      if (isNotification) return null;
      if (res.status === 403) throw new Error('the app refused the call: reload the page from the HypnoMix app');
      const text = await res.text();
      let msg;
      try { msg = JSON.parse(text); } catch (e) { throw new Error(res.ok ? 'reply is not JSON' : 'HTTP ' + res.status + ' from ' + mcp.endpoint); }
      if (msg.error) throw new Error(msg.error.message + ' (' + msg.error.code + ')');
      return msg.result;
    },

    /* a call sent while the page closes: kept alive by the browser, nothing waits for its answer */
    beacon(name, args) {
      try {
        fetch(mcp.endpoint, { method: 'POST', keepalive: true,
          headers: Object.assign({ 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' }, token && mcp.endpoint === '/mcp' ? { 'X-Hypnomix': token } : {}),
          body: JSON.stringify({ jsonrpc: '2.0', id: ++mcp._id, method: 'tools/call', params: { name, arguments: args || {} } }) }).catch(() => {});
      } catch (e) {}
    },

    /* tools/call → the tool's structured JSON (structuredContent, or content[0].text parsed) */
    async call(name, args, opts) {
      const t0 = performance.now();
      try {
        if (name === 'session_save' && HX.endAuditions) await HX.endAuditions('saving').catch(() => {});   // whoever saves: a tried value (Hear it) is put back first, never written into the file
        const r = await mcp.rpc('tools/call', { name, arguments: args || {} });
        if (!(opts && opts.quiet)) HX.log('mcp', name + ' ' + JSON.stringify(args || {}) + '  · ' + Math.round(performance.now() - t0) + ' ms');
        if (r && r.isError) throw new Error((r.content && r.content[0] && r.content[0].text) || 'tool error');
        if (!READS.test(name) && HX.markDirty) HX.markDirty();   // a change reached the engine: the session has unsaved edits (the app keeps the true count)
        if (r && r.structuredContent !== undefined) return r.structuredContent;
        const txt = r && r.content && r.content[0] && r.content[0].text;
        try { return JSON.parse(txt); } catch (e) { return txt; }
      } catch (e) {
        if (!(opts && opts.quiet)) HX.log('err', name + ' ' + JSON.stringify(args || {}) + '  · ' + e.message);
        throw e;
      }
    },

    async connect() {
      const init = await mcp.rpc('initialize', { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'hypnomix-daw-view', version: clientVersion } });
      mcp.serverInfo = init && init.serverInfo;
      await mcp.rpc('notifications/initialized', undefined, true).catch(() => {});
      const list = await mcp.rpc('tools/list', {});
      mcp.tools = (list && list.tools ? list.tools : []).map((t) => t.name);
      mcp.connected = true;
      HX.log('mcp', 'initialize → ' + (mcp.serverInfo && mcp.serverInfo.version ? 'version ' + mcp.serverInfo.version : 'no version') + ', ' + mcp.tools.length + ' tools');
      return init;
    },
    disconnect() { mcp.connected = false; mcp.serverInfo = null; },
    has(name) { return !mcp.tools.length || mcp.tools.includes(name); },

    /* ── typed wrappers for what the UI uses ── */
    sessionInfo: () => mcp.call('session_get_info'),
    tracksList: () => mcp.call('tracks_list', { includeHidden: false }),
    trackInfo: (id) => mcp.call('track_get_info', { id }),
    trackRegions: (id) => mcp.call('track_get_regions', { id }),
    transportState: () => mcp.call('transport_get_state'),
    play: () => mcp.call('transport_play'),
    stop: () => mcp.call('transport_stop'),
    gotoStart: () => mcp.call('transport_goto_start'),
    locate: (sample) => mcp.call('transport_locate_sample', { sample: Math.max(0, Math.round(sample)) }),
    loopToggle: (enabled) => mcp.call('transport_loop_toggle', enabled === undefined ? {} : { enabled }),
    loopRange: (startSample, endSample) => mcp.call('transport_loop_location_samples', { startSample: Math.max(0, Math.round(startSample)), endSample: Math.round(endSample) }),
    /* the schema's argument is `enabled`; the surface reads it with a throwing ptree get, so a wrong name is not a clean error */
    recEnable: (enabled) => mcp.call('transport_set_record_enable', { enabled }),
    setFaderDb: (id, db) => mcp.call('track_set_fader_db', { id, db: HX.clamp(db, -193, 6) }),
    /* Ardour pan: 0.0 = right, 0.5 = centre, 1.0 = left. UI pan: −1 left … +1 right */
    setPan: (id, pan) => mcp.call('track_set_pan', { id, position: HX.clamp((1 - pan) / 2, 0, 1) }),
    setMute: (id, value) => mcp.call('track_set_mute', { id, value }),
    setSolo: (id, value) => mcp.call('track_set_solo', { id, value }),
    setRecEnable: (id, value) => mcp.call('track_set_rec_enable', { id, value }),
    setSendDb: (id, sendIndex, db) => mcp.call('track_set_send_level_db', { id, sendIndex, db: HX.clamp(db, -193, 6) }),
    setPluginEnabled: (id, pluginIndex, enabled) => mcp.call('plugin_set_enabled', { id, pluginIndex, enabled }),
    setRegionGainDb: (regionId, db) => mcp.call('region_set_gain_db', { regionId, db }),
    undo: (count) => mcp.call('session_undo', { count: count || 1 }),
    redo: (count) => mcp.call('session_redo', { count: count || 1 }),
    save: (snapshotName) => mcp.call('session_save', snapshotName ? { snapshotName, switchToSnapshot: false } : {}),
  });

  function httpError(r, j) { const e = new Error(j.error || r.statusText); e.status = r.status; e.body = j; return e; }

  /* the hypnomix app around this page (served at /daw/): the engine supervisor and the Assistant */
  HX.api = {
    inApp: !!token,
    /* a refusal throws an Error with .status and .body (the app's JSON): "unsaved" (409) is asked about, not shown */
    async get(u) { const r = await fetch(u); const j = await r.json().catch(() => ({})); if (!r.ok) throw httpError(r, j); return j; },
    async post(u, body) {
      const r = await fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Hypnomix': token }, body: JSON.stringify(body || {}) });
      const j = await r.json().catch(() => ({})); if (!r.ok) throw httpError(r, j); return j;
    },
  };

  /* what the UI would call, as text, for change cards and the log (mock or real) */
  HX.describeOp = function (op) {
    switch (op.param) {
      case 'fader': return { tool: 'track_set_fader_db', args: { id: op.trackId, db: +op.after.toFixed(2) } };
      case 'pan': return { tool: 'track_set_pan', args: { id: op.trackId, position: +((1 - op.after) / 2).toFixed(3) } };
      case 'mute': return { tool: 'track_set_mute', args: { id: op.trackId, value: op.after } };
      case 'solo': return { tool: 'track_set_solo', args: { id: op.trackId, value: op.after } };
      case 'send': return { tool: 'track_set_send_level_db', args: { id: op.trackId, sendIndex: op.key, db: +op.after.toFixed(2) } };
      case 'devOn': return { tool: 'plugin_set_enabled', args: { id: op.trackId, pluginIndex: op.key, enabled: op.after } };
      case 'devParam': return { tool: 'plugin_set_parameter_by_index_value', args: { id: op.trackId, pluginIndex: op.key[0], parameterIndex: op.realIndex != null ? op.realIndex : op.key[1], value: op.after } };
      case 'clipGain': return { tool: 'region_set_gain_db', args: { regionId: op.key, db: +op.after.toFixed(2) } };
      case 'clipStart': return { tool: 'region_move_to_sample', args: { regionId: op.key, sample: Math.round(HX.beatsToSec(op.after) * HX.S.session.sampleRate) } };
      default: return (HX.describeRegionOp && HX.describeRegionOp(op)) || { tool: '(local)', args: {} };
    }
  };
})();
