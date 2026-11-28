# Hypnomix Turnaround: design (internal; not shipped in the wiki)

A free, original Max for Live device for **Ableton Live only** (REAPER / HypnoMix Studio later releases).
Clean-room: functionality studied from Loopmix, Beat Repeat, Effectrix, Stutter Edit, Glitch, Gross Beat
(research: ~/ai-producer/research/loop-tools-research.md). No code, names, presets, samples or GUI copied.

Two modes, one device ("Hypnomix Turnaround", Max Audio Effect):

- **Fills** (real time, gen~): periodic turnarounds, glitches and effects on the loop the track is playing,
  synced to Live's transport, aware of phrase position (vary the end of every 4 / 8 / 16 bars).
- **Loops** (offline, through the HypnoMix app): from stems (the set's tracks), pick the best sections to
  loop with common bounds, align each clip's edges, make variations, place them in Session slots of a NEW set.

Shared rules (from the user's memory): gentle by default, every change optional, never quantise the playing
(only clip boundaries move; MIDI: only the edge notes), new set written, originals untouched.

---------------------------------------------------------------------------------------------------------
## 1. Fills engine (one algorithm, two implementations that must match)

`hypnomix/session/turnaround_fx.py` (numpy reference: tests, offline renders for Loops-mode variations,
previews) and the gen~ code inside the device. Same pattern generator, bit-identical.

### Time
- Grid: 16 steps per bar (16ths in 4/4; `beats_per_bar` param, default 4, steps = 4 × beats).
- `cycle` C bars (4, 8, 16; default 4). Bar index from the song's first downbeat; `bar_in_cycle = bar % C`.
- Fill window: the last `W` steps of each cycle. `where` ∈ {1 beat = 4, 2 beats = 8, 1 bar = 16, 2 bars = 32}
  (default 8).
- `grow` (default on): every 2C bars the window doubles and level +1; every 4C bars it doubles again
  (cap 32 steps, level cap 3). So with C=4: small fill at bar 4, bigger at 8, biggest at 16.
- The first downbeat of the next cycle is never touched: every effect ends exactly at the window end, and
  the filter/gain snap back there (echo tails may ring on, see `echo`).
- `fill_index` = number of the cycle since bar 0 (cycle k covers bars kC … kC+C-1).

### Random numbers (must be identical in Python and gen~)
Park-Miller in doubles: `s = (s * 16807) mod 2147483647`, `rnd() = s / 2147483647`.
Seed per fill: `s0 = 1 + ((seed * 7919 + epoch * 104729) mod 2147483646)` where `epoch = fill_index // evolve`
(`evolve` N ≥ 1: a new pattern every N fills; 0 = never, epoch = 0). Call `rnd()` 3 times to warm up.

### Pattern generator: `pattern(seed, fill_index, W, level, weights, chance, evolve) -> [segments]`
Order of rnd() calls is part of the spec:
1. `active = rnd() < chance` (chance 0..1, default 0.75). Not active → [] (no fill).
2. `k = 1 + floor(rnd() * level)` effect segments (level 1 Gentle, 2 Medium, 3 Wild; default 1).
3. Build backwards from the window end: `pos = W`. For j in 0..k-1, while pos > 0:
   - length: `r = rnd()`; candidates `[1, 2, 4, 8]` with weights `[1, 3, 3, 1]` (normalised; cumulative pick);
     clip to `pos`; if `j == 0 and W >= 8` the minimum is 2.
   - effect: weighted pick over the enabled effects (weight > 0), excluding the previous segment's effect
     (if that leaves none, allow it). One `rnd()`.
   - param: one `rnd()` → `p` in 0..1, mapped per effect (below).
   - segment = (start = pos - length, length, effect, p); `pos = start`.
   - gap: `rnd() < 0.5 - 0.15 * level` → `pos -= 2 if rnd() < 0.5 else 4` (pos ≥ 0). (Second rnd only if gap.)
4. Return segments sorted by start (steps 0..W-1 relative to the window start).

### Effects (ids fixed; weights default in brackets; 0 = off)
| id | name | default w | what (src = the circular buffer of the input; L = segment length in samples) |
|---|---|---|---|
| 1 | repeat | 3 | slice length `[1/8, 1/16, 1/32]` note by p (thirds); plays the input from the segment start for one slice, then repeats that slice to the segment end; each repeat ×0.92 gain |
| 2 | roll | 2 | like repeat but the slice length starts at 1/8 and halves at 1/2 and 3/4 of the segment (1/8→1/16→1/32); gain rises 0.8→1.0 (a snare-roll build) |
| 3 | reverse | 2 | plays the same span one bar earlier, backwards: reads `seg_start - bar + (L - t)` |
| 4 | tapestop | 1 | read rate `(1 - t/L) ** 1.5` from the segment start (pointer starts at the live position and slows) |
| 5 | halftime | 1 | read rate 0.5 from the segment start |
| 6 | drop | 2 | gain → 0 (a drop-out before the downbeat); if p < 0.5 only the last half of the segment |
| 7 | filter | 2 | p < 0.5: low-pass 18 kHz → 400 Hz (exp sweep); else high-pass 30 Hz → 1.5 kHz; 2-pole SVF Q 0.9 |
| 8 | gate | 1 | on for the first half of every 1/16 (p ≥ 0.5: every 1/32), 2 ms ramps |
| 9 | crush | 0 | hold every 8th sample (p ≥ 0.5: 16th) and quantise to 8 bits; 50 % wet |
| 10 | echo | 1 | dry stays; the segment's input feeds a delay (3/16 note, feedback 0.45, LP 4 kHz on the wet) whose tail keeps ringing after the window (fades naturally) |
| 11 | rearrange | 2 | plays a different step of the previous bar: offset `[-4, -8, +4]` steps by p (thirds): reads `seg_start - bar + offset*step + t` |

### Click safety and mix
- Every segment fades in from dry over 3 ms and out to dry over 3 ms at its end (inside the segment).
- Every repeat restart: 2 ms fade out / 2 ms fade in around the jump.
- `keep_lows` (default on): split at 150 Hz with a 2-pole Butterworth low-pass `lo`; effects act on
  `hi = x - lo`; out = `lo + fx(hi)`. With no effect active out == x exactly.
  (Exception: `drop` with keep_lows still mutes only `hi`; `halftime`/`tapestop` on `hi` only.)
- `mix` 0..1 (default 1): out = dry·(1-mix) + wet·mix during segments.
- `humanise_ms` (default 1.5): each repeat restart is shifted by `(rnd2()*2-1)*humanise_ms`, using a second
  Park-Miller stream seeded `s0 + 1`, so the pattern stream stays identical. 0 = off.

### Python reference API (turnaround_fx.py)
- `pattern(...)` as above → list of dicts `{start, length, effect, name, p}`.
- `fill_windows(n_bars, cycle, where, grow, beats_per_bar)` → list of `(fill_index, first_step, W, level_bump)`
  in song steps.
- `render(x, sr, bpm, downbeat_s, **params) -> y` (x: (n,) or (n, 2) float); constant tempo; same length out.
- `render_window(...)` helper for one fill (used by Loops-mode variations).
- CLI: `hypnomix turnaround fx IN.wav --bpm 120 --downbeat 0.0 [--cycle 4 --where 8 --level 1 --seed 1 ...]
  --out OUT.wav [--json PATTERNS.json]` (an offline preview of what the device would do).

---------------------------------------------------------------------------------------------------------
## 2. Loop edges (`hypnomix/session/loopedges.py`)

The rule: when a loop clip plays, its first downbeat transient lands exactly at the clip start, and the
clip end leaves room so the next pass's downbeat (the clip's own start) comes in clean, with no early hit
of the following bar's downbeat stuck at the end.

Audio (`align_audio(y, sr, start_s, end_s, ...)`, y the source file, start/end the grid bar lines):
1. **Start**: find the strongest onset (spectral flux, hop ≤ 2.9 ms at 44.1/48 kHz) within ±40 ms of
   `start_s`. Attack start = walk back from the onset peak (≤ 15 ms) to where the short envelope (1 ms RMS)
   falls under 10 % of the peak's rise above the floor. Snap to the nearest zero crossing at or before it
   (≤ 1 ms back). That is `new_start`. No onset in the window → keep the bar line, flag `no_transient`.
2. **End**: the same search around `end_s` (the next bar's downbeat). `new_end` = that attack start minus a
   guard (default 1.0 ms), snapped to a zero crossing at or before. So the next downbeat's attack (even an
   early one) is never inside the loop. No onset there → end = `end_s` snapped back to a zero crossing.
3. **Length**: report `played_len = new_end - new_start` vs the grid length; the clip is warped to the set's
   tempo, so Live stretches the remainder; report the ms difference and flag > 25 ms (`length_off`).
4. **Seam**: a fade-out of `fade_ms` (default 4 ms; 0 = none) ending at new_end; no fade-in (the attack must
   stay sharp). Report the seam level jump (dB, last 20 ms vs first 20 ms) and a ringing tail (energy in the
   last 50 ms more than 12 dB over the level right before the end's attack → `tail_rings`, suggest a longer
   fade or tail wrap; nothing automatic).
5. **Stems share bounds**: `align_group(stems, start_s, end_s, ref=None)`: the reference stem (most
   transient energy in the start window, usually drums; or `ref` by name) sets new_start/new_end for all.
   For each other stem report its own onset offset vs the reference in ms; `each=True` aligns every stem to
   its own onset instead (offered, never default; human feel).

MIDI (`align_midi(notes, start_beat, end_beat, window_beats=1/32, ...)`, notes = (pitch, start, dur, vel)):
- Notes starting within ±window of `start_beat` move to exactly `start_beat` (end kept where it was).
  Only those; interior notes never move.
- Notes starting within `window` before `end_beat` belong to the next downbeat (played early): removed from
  the loop's end (the loop's own downbeat plays them on the next pass); if the start has no note of that
  pitch, it is moved to `start_beat` instead of removed.
- Notes that would sound past `end_beat` are shortened to end `1/128` beat before it.
- Report counts: nudged, removed, wrapped, shortened. Return new notes relative to the loop start.

CLI: `hypnomix loopedges FILE.wav --bpm B --downbeat S --bar N --bars 4 [--fade-ms 4] [--out CUT.wav]`
and `hypnomix loopedges FILE.mid --bar N --bars 4 [--out CUT.mid]`; prints the report, writes the cut.

---------------------------------------------------------------------------------------------------------
## 3. Loop set: best sections from stems (`hypnomix/session/loopset.py`, phase 2)

`hypnomix loopset SET.als [--tracks A B …] [--bars 1 2 4 8] [--top 6] [--variations 4] --apply NEW.als`.
Shared grid from the set's tempo + the song's downbeat (beats.py on the drums or the mix). Candidates on
bar lines; score per window = steady (beat evenness) + seam (cross-correlation + level match across the join,
on every stem, weighted by stem energy) + section quality (energy stable, few silent stems, high bar-to-bar
self-similarity). Common bounds from `align_group`; each stem cut with its own edges applied; MIDI tracks via
`align_midi`. Variations per loop (Loopmix-style, anchor stem + complexity Subtle/Normal/Complex, locked stems
untouched): slice rearrange / reverse / density (repeat) / volume on the anchor, plus fill-end variants
rendered by `turnaround_fx.render_window`. Placed in Session slots of a NEW set: per track, the loop in one
scene row and its variations in the rows under it, named ("Loop B 4 bars", "Loop B v2 fill"). Report LOOPSET.md.

---------------------------------------------------------------------------------------------------------
## 4. The device (`hypnomix/app/turnarounddevice.py` → `hypnomix turnarounddevice`)

Built like `aligndevice.py` (template amxd from Live, boxes added). Parameters are `live.*` objects so they
save with the set and can be automated / mapped. Tabs: **Fills** | **Loops**.

Fills tab: Cycle (4/8/16), Where (1 beat / 2 beats / 1 bar / 2 bars), Grow, Chance, Level (Gentle/Medium/Wild),
Seed, Evolve (0..16), one weight dial per effect, Keep lows, Mix, Humanise, a "Fill now" button (next beat,
one window) and a MIDI note input (held note = fill on). A strip shows the cycle's bars and the next fill's
segments. Transport sync: `phasor~ 32.0.0 @lock 1` (32-bar ramp locked to Live's transport) into gen~; bar,
step and samples-per-step derive from it in gen~ (slope → tempo). Stopped transport → dry.

Loops tab (jsui, talks to the HypnoMix app like Align): tracks (+ Track from the selection, or All), Range
(brace / song), Lengths, Find → list (score, bars, label) → Audition (writes nothing) → Write set / Open set.
