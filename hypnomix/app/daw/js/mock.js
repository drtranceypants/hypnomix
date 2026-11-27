/* Hypnomix · the mock session: a vocal-led song with generated audio peaks.
   Everything here is invented. Positions are in beats (quarter notes); a bar is 4 beats. */
(function () {
  'use strict';
  const HX = window.HX;
  const RES = 48; // peak points per beat
  HX.PEAK_RES = RES;

  const SECTIONS = [
    { name: 'Intro', bar: 1, len: 8 },
    { name: 'Verse 1', bar: 9, len: 16 },
    { name: 'Chorus 1', bar: 25, len: 16 },
    { name: 'Verse 2', bar: 41, len: 16 },
    { name: 'Chorus 2', bar: 57, len: 16 },
    { name: 'Bridge', bar: 73, len: 8 },
    { name: 'Chorus 3', bar: 81, len: 16 },
    { name: 'Outro', bar: 97, len: 8 },
  ];
  const B = (bar) => (bar - 1) * 4; // bar number → beat

  /* ── peak generators ── */
  function genVocal(len, rnd, level) {
    const p = new Float32Array(len * RES);
    let t = 0.5 + rnd() * 0.5;
    while (t < len - 0.5) {
      // a phrase: 4–7 syllables, then a breath
      const syl = 4 + Math.floor(rnd() * 4);
      for (let s = 0; s < syl && t < len; s++) {
        const d = [0.5, 0.5, 1, 1, 1.5, 2][Math.floor(rnd() * 6)];
        const a = (0.42 + rnd() * 0.4) * level;
        const i0 = Math.floor(t * RES), i1 = Math.min(p.length, Math.floor((t + d * 0.92) * RES));
        for (let i = i0; i < i1; i++) {
          const x = (i - i0) / Math.max(1, i1 - i0);
          const env = Math.min(1, x * 14) * (1 - Math.pow(x, 5) * 0.85);
          const vib = 1 + Math.sin(i * 0.9) * 0.05 + (rnd() - 0.5) * 0.18;
          p[i] = Math.max(p[i], a * env * vib);
        }
        // consonant burst at the start of some syllables
        if (rnd() < 0.35 && i0 > 1) for (let k = -2; k < 2; k++) p[i0 + k] = Math.max(p[i0 + k] || 0, a * 0.55);
        t += d;
      }
      t += 0.5 + rnd() * 1.5;
      t = Math.ceil(t * 2) / 2;
    }
    for (let i = 0; i < p.length; i++) p[i] = Math.max(p[i], 0.012 + rnd() * 0.01);
    return p;
  }
  function genDrums(len, rnd, fill) {
    const p = new Float32Array(len * RES);
    const hit = (beat, a, decay) => {
      const i0 = Math.floor(beat * RES);
      for (let i = i0; i < Math.min(p.length, i0 + RES * 2); i++) p[i] = Math.max(p[i], a * Math.exp(-(i - i0) / (RES * decay)));
    };
    for (let b = 0; b < len; b++) {
      const inBar = b % 4;
      hit(b + 0, 0.24 + rnd() * 0.05, 0.08);
      hit(b + 0.5, 0.2 + rnd() * 0.05, 0.08);
      if (inBar === 0 || inBar === 2) hit(b, 0.92 + rnd() * 0.06, 0.22);
      if (inBar === 2 && rnd() < 0.3) hit(b + 0.75, 0.6, 0.15);
      if (inBar === 1 || inBar === 3) hit(b, 0.78 + rnd() * 0.08, 0.3);
      if (fill && b >= len - 4) for (let s = 0; s < 4; s++) hit(b + s * 0.25, 0.45 + rnd() * 0.4, 0.12);
    }
    for (let i = 0; i < p.length; i++) p[i] = Math.max(p[i], 0.02 + rnd() * 0.02);
    return p;
  }
  function genBass(len, rnd) {
    const p = new Float32Array(len * RES);
    let b = 0;
    while (b < len) {
      const d = rnd() < 0.7 ? 1 : rnd() < 0.5 ? 0.5 : 2;
      const a = 0.55 + rnd() * 0.18;
      const i0 = Math.floor(b * RES), i1 = Math.min(p.length, Math.floor((b + d * 0.95) * RES));
      for (let i = i0; i < i1; i++) { const x = (i - i0) / (i1 - i0); p[i] = a * Math.min(1, x * 30) * (1 - x * 0.35) * (1 + Math.sin(i * 0.31) * 0.04); }
      b += d;
    }
    return p;
  }
  function genGuitar(len, rnd, soft) {
    const p = new Float32Array(len * RES);
    for (let b = 0; b < len; b += soft ? 2 : 1) {
      const a = (soft ? 0.32 : 0.5) + rnd() * 0.2;
      const i0 = Math.floor(b * RES);
      for (let i = i0; i < Math.min(p.length, i0 + RES * (soft ? 2 : 1)); i++) {
        const x = (i - i0) / RES;
        p[i] = Math.max(p[i], a * Math.min(1, x * 40) * Math.exp(-x * (soft ? 0.7 : 1.6)) * (1 + (rnd() - 0.5) * 0.25));
      }
    }
    for (let i = 0; i < p.length; i++) p[i] = Math.max(p[i], 0.03 + rnd() * 0.025); // a little hiss (the scan finds it)
    return p;
  }
  /* MIDI keys: Am – F – C – G, one chord per bar, voiced around middle C */
  const CHORDS = [[57, 60, 64, 69], [53, 57, 60, 65], [55, 60, 64, 67], [55, 59, 62, 67]];
  function genNotes(len, rnd, offsetBar) {
    const notes = [];
    for (let bar = 0; bar < len / 4; bar++) {
      const ch = CHORDS[(bar + offsetBar) % 4];
      ch.forEach((pitch, k) => notes.push({ t: bar * 4 + (k === 0 ? 0 : 0.02 * k), len: k === 0 ? 4 : 3.5, pitch, vel: 70 + Math.floor(rnd() * 30) }));
      if (rnd() < 0.6) notes.push({ t: bar * 4 + 2.5, len: 1, pitch: ch[3] + 12, vel: 64 });
    }
    return notes;
  }

  let clipSeq = 0;
  function clip(track, startBar, lenBars, name, opts) {
    const len = lenBars * 4;
    const seed = HX.hash(track.name + ':' + startBar);
    const rnd = HX.rng(seed);
    const c = { id: 'c' + ++clipSeq, name, start: B(startBar), len, gainDb: 0, kind: track.kind === 'midi' ? 'midi' : 'audio', seed, fadeIn: 0.02, fadeOut: 0.12 };
    const k = track.role;
    if (c.kind === 'midi') c.notes = genNotes(len, rnd, 0);
    else if (k === 'vocal') c.peaks = genVocal(len, rnd, (opts && opts.level) || 1);
    else if (k === 'drums') c.peaks = genDrums(len, rnd, opts && opts.fill);
    else if (k === 'bass') c.peaks = genBass(len, rnd);
    else c.peaks = genGuitar(len, rnd, opts && opts.soft);
    track.clips.push(c);
    return c;
  }

  const P = (n, v, min, max, unit, extra) => Object.assign({ n, v, min, max, unit: unit || '' }, extra || {});
  const dev = (name, kind, params, extra) => Object.assign({ id: 'd' + HX.hash(name + Math.random()).toString(36), name, kind, on: true, params }, extra || {});
  const EQ = (bands) => dev('ACE EQ', 'eq', [P('Low', bands[0], -12, 12, 'dB'), P('Lo-Mid', bands[1], -12, 12, 'dB'), P('Hi-Mid', bands[2], -12, 12, 'dB'), P('High', bands[3], -12, 12, 'dB'), P('HPF', bands[4], 20, 400, 'Hz', { log: true }), P('Output', 0, -12, 12, 'dB')]);
  const COMP = (thr, ratio, att, rel, mk) => dev('ACE Compressor', 'comp', [P('Threshold', thr, -40, 0, 'dB'), P('Ratio', ratio, 1, 20, ':1'), P('Attack', att, 0.1, 100, 'ms', { log: true }), P('Release', rel, 10, 1000, 'ms', { log: true }), P('Makeup', mk, 0, 24, 'dB'), P('Mix', 100, 0, 100, '%')]);

  function makeTrack(id, name, role, kind, color, faderDb, pan, devices, sendDb) {
    return { id, name, role, kind, color, faderDb, pan, mute: false, solo: false, arm: false, clips: [], devices, sends: sendDb == null ? [] : [{ index: 0, name: 'Reverb', db: sendDb }], height: 52, meter: { l: -100, r: -100, pk: -100, pkT: 0, clip: false } };
  }

  HX.makeMockSession = function () {
    clipSeq = 0;
    const t = [
      makeTrack('t1', 'Lead Vocal', 'vocal', 'audio', '#d9967a', -3.2, 0, [
        EQ([-1.5, -2, 1.5, 2.5, 90]), COMP(-18, 3, 8, 120, 3), dev('De-esser', 'deess', [P('Freq', 6800, 3000, 12000, 'Hz', { log: true }), P('Amount', 4.5, 0, 12, 'dB')]),
        dev('hx Smooth', 'hx', [P('Amount', 22, 0, 100, '%'), P('Focus', 3200, 1000, 8000, 'Hz', { log: true })]),
      ], -14),
      makeTrack('t2', 'Harmony 1', 'vocal', 'audio', '#d6a98c', -6.0, -0.32, [EQ([-3, -2.5, 0.5, 2, 140]), COMP(-20, 4, 6, 100, 4)], -10),
      makeTrack('t3', 'Harmony 2', 'vocal', 'audio', '#cdb48f', -8.5, 0.34, [EQ([-3, -2.5, 0.5, 2, 140]), COMP(-20, 4, 6, 100, 4)], -10),
      makeTrack('t4', 'Drums', 'drums', 'audio', '#c8b37c', -4.0, 0, [EQ([2, -3, 1, 1.5, 30]), COMP(-14, 4, 20, 80, 2), dev('Saturator', 'sat', [P('Drive', 3.5, 0, 24, 'dB'), P('Color', 40, 0, 100, '%'), P('Mix', 35, 0, 100, '%')])], -24),
      makeTrack('t5', 'Bass', 'bass', 'audio', '#93b39a', -5.5, 0, [EQ([1.5, -2, 0, -1, 35]), COMP(-16, 4, 15, 150, 2), dev('hx Sidechain', 'hx', [P('Key', 0, 0, 1, '', { labels: ['Drums', 'Kick'] }), P('Depth', 0, 0, 12, 'dB'), P('Release', 90, 20, 400, 'ms')])], null),
      makeTrack('t6', 'Keys', 'keys', 'midi', '#8eaab8', -9.0, -0.12, [dev('Electric Piano', 'instrument', [P('Tone', 45, 0, 100, '%'), P('Tremolo', 18, 0, 100, '%'), P('Release', 420, 50, 2000, 'ms', { log: true })]), EQ([-2, -1, -1.5, 1, 80])], -16),
      makeTrack('t7', 'Guitar', 'guitar', 'audio', '#a9a0c4', -8.0, 0.4, [EQ([-4, -1, 1, 1, 110]), COMP(-18, 2.5, 12, 160, 2), dev('ACE Delay', 'delay', [P('Time', 0.75, 0.125, 2, 'beat'), P('Feedback', 28, 0, 95, '%'), P('Mix', 14, 0, 100, '%')])], -18),
    ];
    const ret = makeTrack('r1', 'Reverb', 'return', 'bus', '#9aa3ad', -2.0, 0, [dev('ACE Reverb', 'reverb', [P('Size', 64, 0, 100, '%'), P('Decay', 2.4, 0.2, 10, 's', { log: true }), P('Pre-delay', 22, 0, 200, 'ms'), P('Damping', 55, 0, 100, '%'), P('Mix', 100, 0, 100, '%')]), EQ([-6, -1, 0, -3, 220])], null);
    ret.isReturn = true;
    const master = makeTrack('m', 'Master', 'master', 'master', '#bdb6aa', 0, 0, [EQ([0.5, 0, 0, 0.8, 20]), dev('Bus Comp', 'comp', [P('Threshold', -10, -40, 0, 'dB'), P('Ratio', 2, 1, 20, ':1'), P('Attack', 30, 0.1, 100, 'ms', { log: true }), P('Release', 200, 10, 1000, 'ms', { log: true }), P('Makeup', 1, 0, 24, 'dB'), P('Mix', 100, 0, 100, '%')]), dev('Limiter', 'limiter', [P('Gain', 4.5, 0, 24, 'dB'), P('Ceiling', -0.3, -6, 0, 'dBTP'), P('Release', 60, 1, 1000, 'ms', { log: true })])], null);
    master.isMaster = true;

    const [lead, h1, h2, dr, bs, ky, gt] = t;
    clip(lead, 9, 8, 'Verse 1 A'); clip(lead, 17, 8, 'Verse 1 B');
    clip(lead, 25, 16, 'Chorus 1');
    clip(lead, 41, 8, 'Verse 2 A'); clip(lead, 49, 8, 'Verse 2 B', { level: 0.72 });
    clip(lead, 57, 16, 'Chorus 2'); clip(lead, 73, 8, 'Bridge'); clip(lead, 81, 16, 'Chorus 3'); clip(lead, 97, 4, 'Ad-lib');
    [25, 57, 81].forEach((b, i) => clip(h1, b, 16, 'Chorus ' + (i + 1) + ' hi', { level: i === 0 ? 1.15 : 0.9 }));
    clip(h1, 73, 8, 'Bridge hi');
    [25, 57, 81].forEach((b, i) => clip(h2, b, 16, 'Chorus ' + (i + 1) + ' lo', { level: 0.85 }));
    clip(dr, 5, 4, 'Intro fill', { fill: true });
    [[9, 16, 'Verse'], [25, 16, 'Chorus'], [41, 16, 'Verse'], [57, 16, 'Chorus'], [73, 8, 'Bridge'], [81, 16, 'Chorus'], [97, 4, 'Outro']].forEach(([b, l, n]) => clip(dr, b, l, n, { fill: n === 'Chorus' }));
    [[9, 16, 'Verse'], [25, 16, 'Chorus'], [41, 16, 'Verse'], [57, 16, 'Chorus'], [73, 8, 'Bridge'], [81, 16, 'Chorus'], [97, 8, 'Outro']].forEach(([b, l, n]) => clip(bs, b, l, n));
    SECTIONS.forEach((s) => clip(ky, s.bar, s.len, s.name));
    clip(gt, 1, 8, 'Intro', { soft: true });
    [25, 57, 81].forEach((b, i) => clip(gt, b, 16, 'Chorus ' + (i + 1)));
    clip(gt, 97, 8, 'Outro', { soft: true });

    return {
      name: 'Practice Song',
      tempo: 92, sig: [4, 4], sampleRate: 48000,
      lengthBeats: B(105),
      sections: SECTIONS.map((s) => ({ name: s.name, start: B(s.bar), len: s.len * 4 })),
      loop: { on: false, start: B(25), end: B(41) },
      tracks: t, returns: [ret], master,
      snapshots: [
        { name: 'Practice Song', when: 'current', current: true },
        { name: 'Practice Song — rough 3', when: '2 days ago' },
        { name: 'Practice Song — pre-comp', when: 'last week' },
      ],
    };
  };

  /* session clip grid derived from the arrangement: one scene per section */
  HX.buildScenes = function (S) {
    return S.sections.map((sec) => ({
      name: sec.name, start: sec.start, len: sec.len,
      slots: S.tracks.map((tr) => {
        const c = tr.clips.find((c) => c.start < sec.start + sec.len && c.start + c.len > sec.start);
        return c ? { clipId: c.id, name: c.name, len: Math.min(c.len, 16) } : null;
      }),
    }));
  };

  /* scan findings, in hypnomix's own terms (rules from the toolkit: vocallevel, harmony balance,
     comp edges, chord-checked gentle tuning, stacks, masking, dehiss, true peak after AAC) */
  HX.makeFindings = function () {
    return [
      { id: 'f1', sev: 'high', kind: 'vocallevel', track: 't1', at: 48 * 4, title: 'Verse 2 B sits 2.8 dB under the rest of the lead', detail: 'Line-to-line vocal level drops in bars 49–56 (short-term LUFS −2.8 against the song median). The listener loses the words in the second half of verse 2.', fix: { label: 'Clip gain on “Verse 2 B”', param: 'clipGain', clip: 'Verse 2 B', amount: 2.5, unit: 'dB', min: 0, max: 4, step: 0.5, tool: 'region_set_gain_db' }, ev: 'level' },
      { id: 'f2', sev: 'high', kind: 'harmony', track: 't2', at: 24 * 4, title: 'Harmony 1 is louder than the lead in Chorus 1', detail: 'In bars 25–40 Harmony 1 peaks 0.9 dB above the lead line. Rule: uppers sit 1.5 dB under the melody. Only this chorus overshadows; choruses 2 and 3 are fine and are left alone.', fix: { label: 'Clip gain on “Chorus 1 hi”', param: 'clipGain', clip: 'Chorus 1 hi', amount: -2.4, unit: 'dB', min: -4, max: 0, step: 0.1, tool: 'region_set_gain_db' }, ev: 'harmony' },
      { id: 'f3', sev: 'med', kind: 'edge', track: 't1', at: 32 * 4 + 1, title: 'Comp edge clips the “s” of “stay” (bar 33)', detail: 'The clip fade-in starts 14 ms after the consonant onset, so the first “s” is cut. Fix moves the clip start and fade 18 ms earlier on your comp; nothing is re-rendered.', fix: { label: 'Extend clip start earlier', param: 'edge', amount: 18, unit: 'ms', min: 6, max: 30, step: 1, tool: 'region_resize_samples' }, ev: 'edge' },
      { id: 'f4', sev: 'med', kind: 'tune', track: 't1', at: 61 * 4 + 2, title: 'Held note 28 c flat on “home” (bar 62)', detail: 'Chord check: A minor under the note, target A4 is a chord tone, no clash. Gentle tune: 35% toward pitch (≈10 c), only this note is spliced. The scoop into the note is kept.', fix: { label: 'Tune toward A4', param: 'tune', amount: 35, unit: '%', min: 10, max: 60, step: 5, tool: 'HypnoMix fix (bridge)' }, ev: 'pitch' },
      { id: 'f5', sev: 'med', kind: 'mask', track: 't5', at: 56 * 4, title: 'Bass and kick mask each other at 60–90 Hz in choruses', detail: 'Kick and bass share 72 Hz energy on the downbeats of every chorus; the low end blurs and the master compressor pumps. A 2 dB keyed dip on the bass clears it.', fix: { label: 'hx Sidechain depth (Bass ← Kick)', param: 'device', device: 'hx Sidechain', p: 'Depth', amount: 2, unit: 'dB', min: 0.5, max: 6, step: 0.5, tool: 'plugin_set_parameter_by_index_value' }, ev: 'spectrum' },
      { id: 'f6', sev: 'low', kind: 'res', track: 't6', at: 24 * 4, title: 'Keys ring at 3.1 kHz behind the vocal', detail: 'A narrow resonance at 3.1 kHz overlaps the lead’s presence range in choruses. A small hi-mid cut leaves room without dulling the keys.', fix: { label: 'ACE EQ Hi-Mid', param: 'device', device: 'ACE EQ', p: 'Hi-Mid', amount: -2.5, unit: 'dB', min: -6, max: 0, step: 0.5, tool: 'plugin_set_parameter_by_index_value' }, ev: 'spectrum' },
      { id: 'f7', sev: 'med', kind: 'stack', track: 't3', at: 58 * 4, title: 'Harmony 2 lands 38 ms late in Chorus 2', detail: 'Against the stack’s average onset, Harmony 2 is late on 6 of 9 phrases in bars 57–72. Nudge halfway to the group mean with a slight grid pull, never onto the lead.', fix: { label: 'Nudge earlier', param: 'nudge', amount: 19, unit: 'ms', min: 5, max: 38, step: 1, tool: 'region_move_by_samples' }, ev: 'timing' },
      { id: 'f8', sev: 'low', kind: 'hiss', track: 't7', at: 0, title: 'Guitar hiss under the intro (−58 dBFS floor)', detail: 'The intro guitar has a steady broadband floor that becomes audible before the drums enter. A light dehiss (6 dB) keeps the pick noise.', fix: { label: 'hx Dehiss reduction', param: 'insert', device: 'hx Dehiss', amount: 6, unit: 'dB', min: 2, max: 12, step: 1, tool: 'plugin_add_by_plugin_id' }, ev: 'floor' },
      { id: 'f9', sev: 'high', kind: 'peak', track: 'm', at: 80 * 4, title: 'Master reaches +0.7 dBTP after AAC encoding', detail: 'Streaming encodes overshoot: the chorus 3 peaks clip after AAC at 256 kbps. Lower the limiter ceiling so the encoded file stays under −1 dBTP.', fix: { label: 'Limiter ceiling', param: 'device', device: 'Limiter', p: 'Ceiling', amount: -1.0, unit: 'dBTP', min: -2, max: -0.5, step: 0.1, tool: 'plugin_set_parameter_by_index_value' }, ev: 'peak' },
    ].map((f) => Object.assign(f, { status: 'open', ab: 'A', orig: f.fix.amount }));
  };

  HX.BROWSER = {
    cats: [
      { id: 'sounds', name: 'Sounds', n: 214 }, { id: 'drums', name: 'Drums', n: 86 }, { id: 'inst', name: 'Instruments', n: 31 },
      { id: 'afx', name: 'Audio Effects', n: 24 }, { id: 'mfx', name: 'MIDI Effects', n: 9 }, { id: 'plug', name: 'Plug-ins', n: 147 },
      { id: 'clips', name: 'Clips', n: 58 }, { id: 'samples', name: 'Samples', n: 1320 },
    ],
    places: [{ id: 'hx', name: 'HypnoMix Tools', n: 6 }, { id: 'proj', name: 'This Project', n: 12 }, { id: 'snaps', name: 'Snapshots', n: 3 }, { id: 'user', name: 'User Library', n: 40 }],
    items: {
      sounds: ['Analog Pad · Dusk', 'Bowed Glass', 'Cassette Choir', 'Felt Piano Close', 'Mellow Keys', 'Night Bus Keys', 'Soft Strings', 'Tape Flute', 'Warm Sub', 'Tremolo Keys'],
      drums: ['Brushed Kit', 'Dry 70s Kit', 'Lo-fi Breaks', 'Room Kit · Tight', 'Studio Kit · Big', 'Sub Boom Kit', 'Tambourine Loops'],
      inst: ['Electric Piano', 'Mono Synth', 'Poly Synth', 'Sampler', 'Simple Drum Machine', 'String Machine'],
      afx: ['ACE Compressor', 'ACE Delay', 'ACE EQ', 'ACE Expander', 'ACE High/Low Pass', 'ACE Reverb', 'Chorus', 'De-esser', 'Bus Comp', 'Limiter', 'Saturator', 'Tape Wobble', 'Utility'],
      mfx: ['Arpeggiator', 'Chord', 'Note Echo', 'Scale', 'Velocity'],
      plug: ['LSP Compressor Stereo', 'LSP Graphic EQ x32', 'x42 Dynamic EQ', 'x42 dpl Digital Peak Limiter', 'Dragonfly Hall Reverb', 'Calf Vintage Delay', 'Stereo Chorus LX'],
      clips: ['Chorus lift · 8 bars', 'Drum fill · 1 bar', 'Riser · 2 bars', 'Stop-time hit'],
      samples: ['clap_room_03.wav', 'kick_round_A.wav', 'riser_tape_4bar.wav', 'room_tone_studioB.wav', 'snare_brush_02.wav', 'vinyl_crackle.wav'],
      hx: ['hx Align (vocal stacks)', 'hx Dehiss', 'hx Sidechain', 'hx Smooth', 'Scan session…', 'Vocal level check'],
      proj: ['Lead Vocal comp.wav', 'Harmony 1.wav', 'Harmony 2.wav', 'Drums (stem).wav', 'Bass DI.wav', 'Guitar L.wav', 'Keys.mid'],
      user: ['My Vocal Chain', 'Parallel Drum Bus', 'Tape Master'],
    },
  };
})();
