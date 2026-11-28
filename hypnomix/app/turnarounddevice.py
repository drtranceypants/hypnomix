#!/usr/bin/env python3
"""Make the Hypnomix Turnaround device: turnarounds, glitches and fills on a repeating loop, live in Ableton Live.

  hypnomix turnarounddevice                 write "Hypnomix Turnaround.amxd" + hypnomix_turnaround.js into your Live User Library
  hypnomix turnarounddevice --out FOLDER    write them somewhere else

Drag "Hypnomix Turnaround" (User Library → Presets → Audio Effects → Max Audio Effect) onto a track or a group
that plays a loop. While Live plays, the end of every phrase gets a short fill made from the track's own audio:

  Cycle      the phrase length in bars (4, 8, 16): the fill comes in its last bar
  Where      how much of the phrase end the fill may use: 1 beat, 2 beats, 1 bar, 2 bars
  Grow       every 2nd phrase the fill doubles in length and gets busier, every 4th again (small, bigger, biggest)
  Chance     how often a phrase gets a fill at all
  Level      Gentle (one effect), Medium (up to two), Wild (up to three)
  Seed       a different number gives a different set of fills; the same number always gives the same ones
  Evolve     a new fill pattern every N phrases (0: the same fill every time)
  Offset     bars before the first phrase starts (if your loop does not start on bar 1)
  Keep lows  the effects leave everything under 150 Hz alone, so kick and bass keep driving
  Mix        how much of the effect you hear
  Fill now   one fill from the next beat
  weights    one dial per effect: how often it is picked (0: never). Repeat, Roll (a snare-roll build), Reverse,
             Tape stop, Half-time, Drop (a drop-out before the downbeat), Filter sweep, Gate, Crush, Echo (a delay
             throw that rings on), Rearrange (another step of the bar before plays instead)

The first downbeat of each new phrase is never touched. Every fill is made of the last bar or two of the
track's own audio, so it is always in key and in time. The strip at the bottom shows where the phrase is and
the next fill's pieces. The same engine runs offline in `hypnomix turnaround fx` (to preview on a bounce).

Assumes 4/4. Not yet verified by loading in Live: if it shows an error, the Max window (right-click the
title → Open Max Window) says which line.
"""
import argparse, json, sys
from pathlib import Path

from hypnomix.app import device as D

W, H = 640, 169
STRIP_Y, STRIP_H = 128, 38

EFFECTS = [  # id, parameter name, short label, default weight (docs/turnaround-design.md §1)
    (1, "w_repeat", "Repeat", 3), (2, "w_roll", "Roll", 2), (3, "w_reverse", "Reverse", 2), (4, "w_tapestop", "Tape", 1),
    (5, "w_halftime", "Half", 1), (6, "w_drop", "Drop", 2), (7, "w_filter", "Filter", 2), (8, "w_gate", "Gate", 1),
    (9, "w_crush", "Crush", 0), (10, "w_echo", "Echo", 1), (11, "w_rearrange", "Rearr", 2)]

# ------------------------------------------------------------------------------------------------ gen~ engine
# A line-by-line twin of hypnomix/session/turnaround_fx.py (the pattern generator must give the same fills).
GEN = r"""
Param phrase(4, min=1, max=32);
Param where(16, min=1, max=32);
Param grow(1, min=0, max=1);
Param chance(0.75, min=0, max=1);
Param level(2, min=1, max=3);
Param seed(1, min=0, max=100000);
Param evolve(1, min=0, max=64);
Param offset(0, min=0, max=64);
Param keeplows(1, min=0, max=1);
Param wet(1, min=0, max=1);
Param fillnow(0);
Param songbeat(0);
Param playing(0);
__WPARAMS__
Data buf(1048576, 2);
Data ebuf(262144, 2);
Data segs(8, 4);
Data wts(12, 1);
History widx(0), eidx(0), ph_prev(0), beat(0), spb(22050), lastsong(-1), lastfill(0), armed(0);
History mstart(-1), mlen(0), inwin_prev(0), nseg(0), curfx(0), seglast(-1);
History lx1(0), lx2(0), ly1(0), ly2(0), rx1(0), rx2(0), ry1(0), ry2(0);
History fl1(0), fl2(0), fr1(0), fr2(0), hl(0), hr(0), hcount(0), elp_l(0), elp_r(0);

BUFN = 1048576;
EBN = 262144;

// --- transport: beat phase from phasor~ 4n @lock 1 (in3), beat count corrected from plugsync~ (songbeat)
ph = in3;
d = ph - ph_prev;
wrapped = 0;
if (d < -0.5) { d = d + 1; wrapped = 1; }
ph_prev = ph;
if (wrapped) beat = beat + 1;
if (d > 0.000001 && d < 0.01) spb = spb + (1 / d - spb) * 0.002;
if (songbeat != lastsong) {
    lastsong = songbeat;
    if (abs(floor(songbeat) - beat) >= 2) beat = floor(songbeat);
}
running = (d > 0.000001) && playing;
stp = spb / 4;
bar = stp * 16;
posst = (beat + ph) * 4;

// --- keep lows: 2-pole Butterworth low-pass at 150 Hz; effects act on hi = x - lo
w0 = 2 * pi * 150 / samplerate;
cs = cos(w0);
al = sin(w0) / (2 * 0.70710678);
a0 = 1 + al;
b0 = (1 - cs) / 2 / a0;
b1 = (1 - cs) / a0;
a1 = -2 * cs / a0;
a2 = (1 - al) / a0;
lol = b0 * in1 + b1 * lx1 + b0 * lx2 - a1 * ly1 - a2 * ly2;
lx2 = lx1; lx1 = in1; ly2 = ly1; ly1 = lol;
lor = b0 * in2 + b1 * rx1 + b0 * rx2 - a1 * ry1 - a2 * ry2;
rx2 = rx1; rx1 = in2; ry2 = ry1; ry1 = lor;
if (!keeplows) { lol = 0; lor = 0; }
hil = in1 - lol;
hir = in2 - lor;
poke(buf, hil, widx, 0);
poke(buf, hir, widx, 1);

// --- where are we: the phrase window, or a "Fill now" window
cyc = max(1, floor(phrase)) * 16;
rel = posst - floor(offset) * 16;
cidx = floor(rel / cyc);
pin = rel - cidx * cyc;
k1 = cidx + 1;
wwin = max(1, floor(where));
lvl = max(1, min(3, floor(level)));
if (grow && k1 % 4 == 0) { wwin = wwin * 4; lvl = lvl + 2; }
else if (grow && k1 % 2 == 0) { wwin = wwin * 2; lvl = lvl + 1; }
wwin = min(min(wwin, 32), cyc);
lvl = min(lvl, 3);
tst = pin - (cyc - wwin);
inwin = running && rel >= 0 && tst >= 0;
fidx = cidx;
force = 0;
if (fillnow != lastfill) { lastfill = fillnow; armed = 1; }
if (armed && wrapped && running) { armed = 0; mstart = floor(posst + 0.5); mlen = max(1, floor(where)); }
if (mstart >= 0 && running && posst >= mstart && posst < mstart + mlen) {
    inwin = 1; tst = posst - mstart; wwin = mlen; lvl = max(1, min(3, floor(level))); fidx = 100000 + fillnow; force = 1;
}
else if (mstart >= 0 && posst >= mstart + mlen) { mstart = -1; inwin_prev = 0; }

// --- a new window: make its pattern (Park-Miller; same order of draws as turnaround_fx.pattern)
if (inwin && !inwin_prev) {
__WPOKES__
    ep = 0;
    if (evolve >= 1) ep = floor(fidx / floor(evolve));
    s = 1 + ((floor(seed) * 7919 + ep * 104729) % 2147483646);
    s = (s * 16807) % 2147483647; s = (s * 16807) % 2147483647; s = (s * 16807) % 2147483647;
    s = (s * 16807) % 2147483647; r = s / 2147483647;
    act = (r < chance) || force;
    n = 0;
    if (act) {
        s = (s * 16807) % 2147483647; r = s / 2147483647;
        k = 1 + floor(r * lvl);
        pos = wwin; prev = 0;
        for (j = 0; j < k; j += 1) {
            if (pos > 0) {
                s = (s * 16807) % 2147483647; r = s / 2147483647;
                sgl = 8;
                if (r < 0.125) sgl = 1; else if (r < 0.5) sgl = 2; else if (r < 0.875) sgl = 4;
                if (j == 0 && wwin >= 8) sgl = max(sgl, 2);
                sgl = min(sgl, pos);
                tot = 0;
                for (ei = 1; ei < 12; ei += 1) { if (ei != prev) tot = tot + peek(wts, ei, 0); }
                ex = prev;
                if (tot <= 0) { tot = 0; for (ei = 1; ei < 12; ei += 1) tot = tot + peek(wts, ei, 0); ex = -1; }
                s = (s * 16807) % 2147483647; r = s / 2147483647;
                pick = 0; acc = 0; tgt = r * tot;
                for (ei = 1; ei < 12; ei += 1) {
                    we = peek(wts, ei, 0);
                    if (ei == ex) we = 0;
                    if (pick == 0 && we > 0) { acc = acc + we; if (tgt < acc) pick = ei; }
                }
                if (pick == 0) { for (ei = 1; ei < 12; ei += 1) { if (peek(wts, ei, 0) > 0 && ei != ex) pick = ei; } }
                s = (s * 16807) % 2147483647; p = s / 2147483647;
                if (pick > 0) {
                    poke(segs, pos - sgl, n, 0); poke(segs, sgl, n, 1); poke(segs, pick, n, 2); poke(segs, p, n, 3);
                    n = n + 1;
                }
                prev = pick;
                pos = pos - sgl;
                s = (s * 16807) % 2147483647; r = s / 2147483647;
                if (r < 0.5 - 0.15 * lvl) {
                    s = (s * 16807) % 2147483647; r = s / 2147483647;
                    gp = 4;
                    if (r < 0.5) gp = 2;
                    pos = max(0, pos - gp);
                }
            }
        }
    }
    nseg = n;
}
inwin_prev = inwin;

// --- the active segment
fx = 0; sst = 0; sln = 0; sp = 0; segi = -1;
if (inwin) {
    for (i = 0; i < 8; i += 1) {
        if (i < nseg) {
            a = peek(segs, i, 0); l = peek(segs, i, 1);
            if (tst >= a && tst < a + l) { fx = peek(segs, i, 2); sst = a; sln = l; sp = peek(segs, i, 3); segi = i; }
        }
    }
}
L = sln * stp;
t = (tst - sst) * stp;
env = 0;
if (fx > 0) env = clamp(min(t / (0.003 * samplerate), (L - t) / (0.003 * samplerate)), 0, 1);
dl = 0; gain = 1; usebuf = 0; jenv = 1;
if (fx == 1 || fx == 2) {
    sl = 2 * stp;
    if (fx == 1) { if (sp < 0.3333333) sl = 2 * stp; else if (sp < 0.6666667) sl = stp; else sl = stp / 2; }
    else { if (t >= 0.75 * L) sl = stp / 2; else if (t >= 0.5 * L) sl = stp; }
    q = t % sl;
    dl = t - q;
    nrep = floor(t / sl);
    if (fx == 1) gain = pow(0.92, nrep); else gain = 0.8 + 0.2 * t / max(1, L);
    jenv = clamp(min(q / (0.002 * samplerate), (sl - q) / (0.002 * samplerate)), 0, 1);
    if (nrep < 1) jenv = clamp((sl - q) / (0.002 * samplerate), 0, 1);
    usebuf = 1;
}
else if (fx == 3) { dl = bar - L + 2 * t; usebuf = 1; }
else if (fx == 4) { x = t / max(1, L); dl = t - L * (1 - pow(1 - x, 2.5)) / 2.5; usebuf = 1; }
else if (fx == 5) { dl = 0.5 * t; usebuf = 1; }
else if (fx == 11) {
    off = -4; if (sp >= 0.3333333 && sp < 0.6666667) off = -8; else if (sp >= 0.6666667) off = 4;
    dl = bar - off * stp; usebuf = 1;
}
wl = hil; wr = hir;
if (usebuf) {
    ri = widx - max(0, dl);
    wl = peek(buf, ri, 0, interp="linear", boundmode="wrap") * gain * jenv;
    wr = peek(buf, ri, 1, interp="linear", boundmode="wrap") * gain * jenv;
}
if (fx == 6) { dg = 0; if (sp < 0.5) dg = clamp(1 - (t - 0.5 * L) / (0.003 * samplerate), 0, 1); wl = hil * dg; wr = hir * dg; }
if (fx == 7) {
    x = t / max(1, L);
    fc = 18000 * pow(400 / 18000, x);
    if (sp >= 0.5) fc = 30 * pow(1500 / 30, x);
    g = tan(pi * min(fc, samplerate * 0.45) / samplerate); kq = 1 / 0.9;
    a1f = 1 / (1 + g * (g + kq)); a2f = g * a1f; a3f = g * a2f;
    v3 = hil - fl2; v1 = a1f * fl1 + a2f * v3; v2 = fl2 + a2f * fl1 + a3f * v3;
    fl1 = 2 * v1 - fl1; fl2 = 2 * v2 - fl2;
    lpL = v2; hpL = hil - kq * v1 - v2;
    v3 = hir - fr2; v1 = a1f * fr1 + a2f * v3; v2 = fr2 + a2f * fr1 + a3f * v3;
    fr1 = 2 * v1 - fr1; fr2 = 2 * v2 - fr2;
    lpR = v2; hpR = hir - kq * v1 - v2;
    if (sp < 0.5) { wl = lpL; wr = lpR; } else { wl = hpL; wr = hpR; }
}
else { fl1 = 0; fl2 = 0; fr1 = 0; fr2 = 0; }
if (fx == 8) {
    gs = stp; if (sp >= 0.5) gs = stp / 2;
    q = t % gs;
    ge = clamp(min(q / (0.002 * samplerate), (gs / 2 - q) / (0.002 * samplerate)), 0, 1);
    if (q >= gs / 2) ge = 0;
    wl = hil * ge; wr = hir * ge;
}
if (fx == 9) {
    hn = 8; if (sp >= 0.5) hn = 16;
    if (hcount <= 0) { hl = floor(hil * 128) / 128; hr = floor(hir * 128) / 128; hcount = hn; }
    hcount = hcount - 1;
    wl = 0.5 * hil + 0.5 * hl; wr = 0.5 * hir + 0.5 * hr;
}
// echo: the segment's input feeds a 3/16 delay whose tail keeps ringing after the window
ein_l = 0; ein_r = 0;
if (fx == 10) { ein_l = hil * env; ein_r = hir * env; wl = hil; wr = hir; }
edl = min(EBN - 1, 3 * stp);
el = peek(ebuf, eidx - edl, 0, interp="linear", boundmode="wrap");
er = peek(ebuf, eidx - edl, 1, interp="linear", boundmode="wrap");
elp_l = elp_l + (el - elp_l) * (1 - exp(-2 * pi * 4000 / samplerate));
elp_r = elp_r + (er - elp_r) * (1 - exp(-2 * pi * 4000 / samplerate));
poke(ebuf, ein_l + 0.45 * elp_l, eidx, 0);
poke(ebuf, ein_r + 0.45 * elp_r, eidx, 1);
eidx = (eidx + 1) % EBN;
widx = (widx + 1) % BUFN;

amt = env * wet;
ol = lol + hil * (1 - amt) + wl * amt + elp_l * wet;
orr = lor + hir * (1 - amt) + wr * amt + elp_r * wet;
curfx = fx;
out1 = ol;
out2 = orr;
out3 = fx;
out4 = clamp(pin / cyc, 0, 1);
out5 = cidx;
"""


def gen_code():
    params = "\n".join(f"Param {n}({w}, min=0, max=10);" for _, n, _, w in EFFECTS)
    pokes = "\n".join(f"    poke(wts, {n}, {i}, 0);" for i, n, _, _ in EFFECTS)
    return GEN.replace("__WPARAMS__", params).replace("__WPOKES__", pokes)


# ------------------------------------------------------------------------------------------------ the strip (jsui)
JS = r"""// Hypnomix Turnaround (jsui strip): where the phrase is, and the next fill's pieces.
// pattern() is a twin of hypnomix/session/turnaround_fx.pattern and of the gen~ code.
autowatch = 1;
inlets = 1;
outlets = 1;
mgraphics.init();
mgraphics.relative_coords = 0;
mgraphics.autofill = 0;
var W = __W__, H = __H__;
var NAMES = ["", "Repeat", "Roll", "Reverse", "Tape stop", "Half-time", "Drop", "Filter", "Gate", "Crush", "Echo", "Rearrange"];
var P = {phrase: 4, where: 16, grow: 1, chance: 0.75, level: 2, seed: 1, evolve: 1, offset: 0};
var Wt = [0, 3, 2, 2, 1, 1, 2, 2, 1, 0, 1, 2];
var pos = 0, fx = 0, cidx = 0;

function nxt(s) { return (s * 16807) % 2147483647; }

function pattern(seed, fidx, win, lvl, wts, chance, evolve, force) {
    var ep = evolve >= 1 ? Math.floor(fidx / Math.floor(evolve)) : 0;
    var s = 1 + ((Math.floor(seed) * 7919 + ep * 104729) % 2147483646);
    s = nxt(s); s = nxt(s); s = nxt(s);
    s = nxt(s); var r = s / 2147483647;
    var out = [];
    if (!(r < chance || force)) return out;
    s = nxt(s); r = s / 2147483647;
    var k = 1 + Math.floor(r * lvl), pos = win, prev = 0;
    for (var j = 0; j < k; j++) {
        if (pos <= 0) continue;
        s = nxt(s); r = s / 2147483647;
        var ln = 8;
        if (r < 0.125) ln = 1; else if (r < 0.5) ln = 2; else if (r < 0.875) ln = 4;
        if (j == 0 && win >= 8) ln = Math.max(ln, 2);
        ln = Math.min(ln, pos);
        var tot = 0, e, ex = prev;
        for (e = 1; e < 12; e++) if (e != prev) tot += wts[e];
        if (tot <= 0) { tot = 0; for (e = 1; e < 12; e++) tot += wts[e]; ex = -1; }
        s = nxt(s); r = s / 2147483647;
        var pick = 0, acc = 0, tgt = r * tot;
        for (e = 1; e < 12; e++) {
            var we = (e == ex) ? 0 : wts[e];
            if (pick == 0 && we > 0) { acc += we; if (tgt < acc) pick = e; }
        }
        if (pick == 0) for (e = 1; e < 12; e++) if (wts[e] > 0 && e != ex) pick = e;
        s = nxt(s); var p = s / 2147483647;
        if (pick > 0) out.push({start: pos - ln, length: ln, effect: pick, p: p});
        prev = pick;
        pos -= ln;
        s = nxt(s); r = s / 2147483647;
        if (r < 0.5 - 0.15 * lvl) { s = nxt(s); r = s / 2147483647; pos = Math.max(0, pos - (r < 0.5 ? 2 : 4)); }
    }
    out.sort(function (a, b) { return a.start - b.start; });
    return out;
}

function windowFor(k) {          // k = phrase index; returns [steps, level] like the gen~ code
    var cyc = Math.max(1, Math.floor(P.phrase)) * 16, w = Math.max(1, Math.floor(P.where));
    var lvl = Math.max(1, Math.min(3, Math.floor(P.level))), k1 = k + 1;
    if (P.grow && k1 % 4 == 0) { w *= 4; lvl += 2; } else if (P.grow && k1 % 2 == 0) { w *= 2; lvl += 1; }
    return [Math.min(w, 32, cyc), Math.min(lvl, 3)];
}

function anything() {
    var a = arrayfromargs(arguments);
    var m = messagename;
    if (m == "pos") pos = a[0];
    else if (m == "fx") fx = a[0];
    else if (m == "cidx") cidx = a[0];
    else if (m.indexOf("w_") == 0) { var i = ["", "w_repeat", "w_roll", "w_reverse", "w_tapestop", "w_halftime", "w_drop", "w_filter", "w_gate", "w_crush", "w_echo", "w_rearrange"].indexOf(m); if (i > 0) Wt[i] = a[0]; }
    else if (P.hasOwnProperty(m)) P[m] = a[0];
    mgraphics.redraw();
}

function paint() {
    var g = mgraphics;
    g.set_source_rgba(0.12, 0.11, 0.10, 1); g.rectangle(0, 0, W, H); g.fill();
    var bars = Math.max(1, Math.floor(P.phrase)), x0 = 4, w = W - 8, y = 4, h = 12;
    var wk = windowFor(cidx), win = wk[0], cyc = bars * 16;
    g.set_source_rgba(0.25, 0.23, 0.2, 1); g.rectangle(x0, y, w, h); g.fill();
    var wx = x0 + w * (cyc - win) / cyc;
    g.set_source_rgba(0.55, 0.38, 0.12, 1); g.rectangle(wx, y, x0 + w - wx, h); g.fill();
    var segs = pattern(P.seed, cidx, win, wk[1], Wt, P.chance, P.evolve, 0);
    for (var i = 0; i < segs.length; i++) {
        var s = segs[i], sx = wx + (x0 + w - wx) * s.start / win, sw = (x0 + w - wx) * s.length / win;
        g.set_source_rgba(1.0, 0.72, 0.25, 1); g.rectangle(sx + 1, y + 2, Math.max(1, sw - 2), h - 4); g.fill();
    }
    g.set_source_rgba(0.6, 0.6, 0.6, 1);
    for (var b = 1; b < bars; b++) { var bx = x0 + w * b / bars; g.move_to(bx, y); g.line_to(bx, y + h); g.stroke(); }
    g.set_source_rgba(1, 1, 1, 1); var px = x0 + w * pos; g.move_to(px, y - 2); g.line_to(px, y + h + 2); g.stroke();
    g.select_font_face("Arial"); g.set_font_size(10);
    var txt = fx > 0 ? ("now: " + NAMES[fx]) : (segs.length ? ("next fill: " + segs.map(function (s) { return NAMES[s.effect]; }).join(" + ")) : "next phrase: no fill");
    g.set_source_rgba(0.9, 0.85, 0.75, 1); g.move_to(x0, y + h + 13); g.show_text(txt);
}
"""

SEL = "live.thisdevice"


def _p(name, short, typ, lo, hi, init, enum=None, unit=None):
    v = {"parameter_longname": name, "parameter_shortname": short, "parameter_type": typ, "parameter_mmin": lo,
         "parameter_mmax": hi, "parameter_initial_enable": 1, "parameter_initial": [init]}
    if enum:
        v["parameter_enum"] = enum
    if unit is not None:
        v["parameter_unitstyle"] = unit
    return {"valueof": v}


def controls():
    """(gen~ param, live.* box fields, value map to send) for every control, in presentation order."""
    c = []
    def add(param, cls, label, rect, sat, mapping=None, **kw):
        c.append(dict(param=param, cls=cls, label=label, rect=rect, sat=sat, mapping=mapping, kw=kw))
    y1, y2 = 4.0, 66.0
    add("phrase", "live.menu", "Cycle", [4, y1 + 14, 52, 15], _p("Cycle", "Cycle", 2, 0, 2, 0, ["4 bars", "8 bars", "16 bars"]), "4 8 16")
    add("where", "live.menu", "Where", [60, y1 + 14, 58, 15], _p("Where", "Where", 2, 0, 3, 2, ["1 beat", "2 beats", "1 bar", "2 bars"]), "4 8 16 32")
    add("grow", "live.text", "Grow", [122, y1 + 14, 40, 15], _p("Grow", "Grow", 2, 0, 1, 1, ["off", "on"]), None, mode=1, text="Grow", texton="Grow")
    add("level", "live.tab", "Level", [166, y1 + 14, 132, 15], _p("Level", "Level", 2, 0, 2, 1, ["Gentle", "Medium", "Wild"]), "1 2 3", num_lines_presentation=1)
    add("chance", "live.dial", "Chance", [302, y1, 44, 48], _p("Chance", "Chance", 0, 0.0, 100.0, 75.0, unit=5), "pct")
    add("wet", "live.dial", "Mix", [348, y1, 44, 48], _p("Mix", "Mix", 0, 0.0, 100.0, 100.0, unit=5), "pct")
    add("seed", "live.numbox", "Seed", [398, y1 + 14, 44, 15], _p("Seed", "Seed", 1, 0, 9999, 1, unit=0), None)
    add("evolve", "live.numbox", "Evolve", [446, y1 + 14, 40, 15], _p("Evolve", "Evolve", 1, 0, 64, 1, unit=0), None)
    add("offset", "live.numbox", "Offset", [490, y1 + 14, 40, 15], _p("Offset", "Offset", 1, 0, 64, 0, unit=0), None)
    add("keeplows", "live.text", "Keep lows", [534, y1 + 14, 52, 15], _p("Keep lows", "Lows", 2, 0, 1, 1, ["off", "on"]), None, mode=1, text="Lows", texton="Keep lows")
    add("fillnow", "live.text", "Fill now", [590, y1 + 14, 46, 15], _p("Fill now", "Fill", 2, 0, 1, 0, ["off", "on"]), "count", mode=0, text="Fill now", texton="Fill now")
    for i, (eid, name, label, w) in enumerate(EFFECTS):
        add(name, "live.dial", label, [4 + i * 57.5, y2, 44, 48], _p(label + " weight", label, 1, 0, 10, w, unit=0), None)
    return c


def build_patch(patch):
    p = patch["patcher"]
    keep = [b for b in p["boxes"] if b["box"].get("text") in ("plugin~", "plugout~") or b["box"].get("text") == "Device vertical limit"]
    ids = {b["box"]["text"]: b["box"]["id"] for b in keep if b["box"].get("text") in ("plugin~", "plugout~")}
    lines = []                                           # rewire plugin~ → gen~ → plugout~
    def box(i, text, rect, nin, outs, **kw):
        return {"box": dict({"id": i, "maxclass": "newobj", "numinlets": nin, "numoutlets": len(outs), "outlettype": outs,
                             "patching_rect": rect, "text": text}, **kw)}
    def line(a, ao, b, bi=0):
        lines.append({"patchline": {"source": [a, ao], "destination": [b, bi]}})
    gen_patcher = {"fileversion": 1, "appversion": p.get("appversion", {}), "classnamespace": "dsp.gen",
                   "rect": [100.0, 100.0, 700.0, 600.0], "boxes": [
                       {"box": {"id": "g-code", "maxclass": "codebox", "code": gen_code(), "fontface": 0, "fontname": "<Monospaced>",
                                "fontsize": 12.0, "numinlets": 3, "numoutlets": 5, "outlettype": ["", "", "", "", ""],
                                "patching_rect": [20.0, 60.0, 600.0, 440.0]}},
                       box("g-in1", "in 1", [20.0, 20.0, 28.0, 22.0], 0, [""]),
                       box("g-in2", "in 2", [120.0, 20.0, 28.0, 22.0], 0, [""]),
                       box("g-in3", "in 3", [220.0, 20.0, 28.0, 22.0], 0, [""])] +
                       [box(f"g-out{i}", f"out {i}", [20.0 + 100 * (i - 1), 520.0, 35.0, 22.0], 1, []) for i in range(1, 6)],
                   "lines": [{"patchline": {"source": [f"g-in{i}", 0], "destination": ["g-code", i - 1]}} for i in range(1, 4)] +
                            [{"patchline": {"source": ["g-code", i - 1], "destination": [f"g-out{i}", 0]}} for i in range(1, 6)]}
    boxes = list(keep)
    boxes.append(box("t-gen", "gen~", [20.0, 300.0, 120.0, 22.0], 3, ["signal"] * 5, patcher=gen_patcher))
    boxes.append(box("t-ph", "phasor~ 4n @lock 1", [160.0, 230.0, 112.0, 22.0], 2, ["signal"]))
    boxes.append(box("t-dev", SEL, [300.0, 20.0, 83.0, 22.0], 1, ["bang", "int", "int"]))
    boxes.append(box("t-metro", "qmetro 15 @active 1", [300.0, 50.0, 120.0, 22.0], 2, ["bang"]))
    boxes.append(box("t-sync", "plugsync~", [300.0, 80.0, 120.0, 22.0], 1, ["int", "int", "int", "float", "list", "float", "float", "int", "int"]))
    boxes.append(box("t-pb", "prepend songbeat", [430.0, 110.0, 100.0, 22.0], 1, [""]))
    boxes.append(box("t-pp", "prepend playing", [300.0, 110.0, 100.0, 22.0], 1, [""]))
    plugin, plugout = ids["plugin~"], ids["plugout~"]
    line(plugin, 0, "t-gen", 0); line(plugin, 1, "t-gen", 1)
    line("t-ph", 0, "t-gen", 2)
    line("t-gen", 0, plugout, 0); line("t-gen", 1, plugout, 1)
    line("t-dev", 0, "t-metro", 0)
    line("t-metro", 0, "t-sync", 0)
    line("t-sync", 6, "t-pb", 0); line("t-pb", 0, "t-gen", 0)
    line("t-sync", 0, "t-pp", 0); line("t-pp", 0, "t-gen", 0)
    # the strip
    boxes.append({"box": {"id": "t-ui", "maxclass": "jsui", "filename": "hypnomix_turnaround.js", "border": 0, "numinlets": 1,
                          "numoutlets": 1, "outlettype": [""], "parameter_enable": 0,
                          "patching_rect": [600.0, 300.0, float(W), float(STRIP_H)], "presentation": 1,
                          "presentation_rect": [0.0, float(STRIP_Y), float(W), float(STRIP_H)]}})
    for n, (o, nm) in enumerate([(2, "fx"), (3, "pos"), (4, "cidx")]):
        boxes.append(box(f"t-snap{n}", "snapshot~ 40", [160.0 + 120 * n, 360.0, 80.0, 22.0], 2, ["float"]))
        boxes.append(box(f"t-pre{n}", f"prepend {nm}", [160.0 + 120 * n, 390.0, 80.0, 22.0], 1, [""]))
        line("t-gen", o, f"t-snap{n}", 0); line(f"t-snap{n}", 0, f"t-pre{n}", 0); line(f"t-pre{n}", 0, "t-ui", 0)
    # controls: live.* → (value map) → prepend <param> → gen~ and → the strip
    for n, c in enumerate(controls()):
        bid, x = f"c-{c['param']}", 700.0 + (n % 6) * 150
        yy = 20.0 + (n // 6) * 120
        b = {"id": bid, "maxclass": c["cls"], "numinlets": 1, "numoutlets": 2, "outlettype": ["", ""], "parameter_enable": 1,
             "patching_rect": [x, yy, c["rect"][2], c["rect"][3]], "presentation": 1, "presentation_rect": [float(v) for v in c["rect"]],
             "saved_attribute_attributes": c["sat"], "varname": c["sat"]["valueof"]["parameter_longname"]}
        if c["cls"] == "live.dial":
            b.update(numoutlets=2, outlettype=["", "float"])
        if c["cls"] in ("live.menu", "live.tab"):
            b.update(numoutlets=3, outlettype=["", "", "float"])
        if c["cls"] == "live.numbox":
            b.update(numoutlets=2, outlettype=["", "float"])
        b.update(c["kw"])
        boxes.append({"box": b})
        src = bid
        m = c["mapping"]
        if m == "pct":
            boxes.append(box(bid + "-m", "/ 100.", [x, yy + 60, 40.0, 22.0], 2, ["float"])); line(src, 0, bid + "-m", 0); src = bid + "-m"
        elif m == "count":
            boxes.append(box(bid + "-m", "counter", [x, yy + 60, 60.0, 22.0], 3, ["int", "", "", "int"]))
            boxes.append(box(bid + "-s", "sel 1", [x, yy + 30, 36.0, 22.0], 2, ["bang", ""]))
            line(src, 0, bid + "-s", 0); line(bid + "-s", 0, bid + "-m", 0); src = bid + "-m"
        elif m:
            boxes.append(box(bid + "-m", f"sel {' '.join(str(i) for i in range(len(m.split())))}", [x, yy + 30, 80.0, 22.0], 1, ["bang"] * len(m.split()) + [""]))
            for i, val in enumerate(m.split()):
                boxes.append({"box": {"id": f"{bid}-v{i}", "maxclass": "message", "numinlets": 2, "numoutlets": 1, "outlettype": [""],
                                      "patching_rect": [x + 30 * i, yy + 60, 28.0, 22.0], "text": val}})
                line(bid + "-m", i, f"{bid}-v{i}", 0)
            src = None
        boxes.append(box(bid + "-p", f"prepend {c['param']}", [x, yy + 90, 110.0, 22.0], 1, [""]))
        if src:
            line(src, 0, bid + "-p", 0)
        else:
            for i in range(len(m.split())):
                line(f"{bid}-v{i}", 0, bid + "-p", 0)
        line(bid + "-p", 0, "t-gen", 0); line(bid + "-p", 0, "t-ui", 0)
        boxes.append({"box": {"id": bid + "-lab", "maxclass": "live.comment", "text": c["label"], "numinlets": 1, "numoutlets": 0,
                              "fontsize": 9.0, "patching_rect": [x, yy - 16, 60.0, 15.0], "presentation": 1,
                              "presentation_rect": [float(c["rect"][0]), float(c["rect"][1]) - (0 if c["cls"] == "live.dial" else 13), 60.0, 15.0]}}
                     ) if c["cls"] != "live.dial" else None
    p["boxes"] = boxes
    p["lines"] = lines
    p["openinpresentation"] = 1
    p["devicewidth"] = float(W)
    p["description"] = "Hypnomix Turnaround: turnarounds, glitches and fills at the end of every phrase, from the track's own audio"
    return patch


def build(out, tpl=None):
    tpl = Path(tpl) if tpl else D.template()
    if not tpl or not tpl.exists():
        raise FileNotFoundError("could not find Live's blank Max Audio Effect (is Ableton Live with Max for Live installed?); "
                                "pass --template PATH to a 'Max Audio Effect.amxd'")
    head, patch = D.read_amxd(tpl)
    out = Path(out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    js = JS.replace("__W__", str(W)).replace("__H__", str(STRIP_H))
    (out / "hypnomix_turnaround.js").write_text(js, encoding="utf-8")
    D.write_amxd(out / "Hypnomix Turnaround.amxd", head, build_patch(patch))
    return out


def main():
    ap = argparse.ArgumentParser(prog="hypnomix turnarounddevice", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="folder to write into (default: your Live User Library)")
    ap.add_argument("--template", help="a blank 'Max Audio Effect.amxd' (default: the one inside your Live)")
    a = ap.parse_args()
    from hypnomix.install import user_library, user_library_words
    lib = user_library()
    out = a.out or (lib / "Presets" / "Audio Effects" / "Max Audio Effect" / "Hypnomix Turnaround")
    if not a.out and not lib.is_dir():
        sys.exit(f"no Live User Library at {user_library_words()}: say where to write with --out FOLDER")
    try:
        od = build(out, a.template)
    except FileNotFoundError as e:
        sys.exit(str(e))
    print(f"wrote {od / 'Hypnomix Turnaround.amxd'}\n      {od / 'hypnomix_turnaround.js'}   (keep the two together)")
    print("In Live: drag Hypnomix Turnaround onto a track or group that plays a loop, and press play.")


if __name__ == "__main__":
    main()
