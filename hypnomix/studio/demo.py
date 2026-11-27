#!/usr/bin/env python3
"""A demo song to try the whole loop on nothing of your own: scan, hear, approve, apply.

Usage:
    hypnomix demo [--out DIR] [--kind folder|reaper] [--seed N]

It writes a short song of about 40 seconds (96 BPM, A minor): drums, bass, keys, a sung-like lead and a harmony
a third above it, all made from scratch (no recordings, nothing downloaded, nothing shipped with HypnoMix; the
same seed always gives the same audio). On purpose, six things are wrong with it, each in one place you can look up:

  1  a click          the keys are comped from two takes and the cut has no fade
  2  a level jump     the lead's second take is louder than the first, joined in the middle of a held note
  3  hiss             a steady noise under the harmony, audible in its pauses
  4  clipped peaks    the bass is recorded too hot for two bars and its notes are flattened
  5  a harmony drifts the harmony goes sharp, a little more with each phrase, from bar 9 on
  6  hits drift late  the drums fall further behind the band in bars 9 to 14

--kind folder (the default) writes the stems as WAV files in a new folder, as you would export them from any DAW:
the click and the level jump are already in the audio (the comps are flattened).
--kind reaper also writes a REAPER project that plays them, with the comps as separate items on separate takes,
so the scan can see every one of the six at its cut or its bar. It also writes Instrumental.wav, the song without the
vocals: scan it with --backing so the chord under every note can be checked (the tuning fix needs that). (There is no Live set kind: a set written from
scratch has not been opened in Live, so it is left out until it has.)

DEMO.md in the new folder lists each problem with its time and the command that finds it. Nothing is written
outside the new folder, and a folder that already exists is never reused. When it is done it prints the path and
the next command, `hypnomix scan <path>`. Then try `hypnomix ab`, `hypnomix review` and `hypnomix fix`: it is the
real loop, on a song that cannot be hurt. The audio is synthetic and sounds like it: the point is the workflow.
"""
import argparse, json, sys
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core.paths import out_at

SR = 44100
BPM = 96.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT
BARS = 16
DUR = BARS * BAR                                      # 40.0 s
N = int(round(DUR * SR))
TITLE = "Hypnomix Demo Song"
CHORDS = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (261.63, 329.63, 392.0), (196.0, 246.94, 293.66)]   # Am F C G
ROOTS = [110.0, 87.31, 130.81, 98.0]
SCALE = [57, 59, 60, 62, 64, 65, 67]                  # A natural minor, MIDI, A3 up to G4
SCALE_ALL = sorted(m + 12 * o for m in SCALE for o in (-1, 0, 1))

CUT_KEYS = 14.2                                       # seconds: where the keys' two takes meet (problem 1)
CUT_LEAD = 27.0                                       # where the lead's two takes meet, inside a held note (problem 2)
LEAD_JUMP_DB = 7.0
HOT_BARS = (6, 7)                                     # bars 7 and 8 (problem 4): their first and third notes are too hot
DRIFT_FROM, DRIFT_CENTS = 20.0, 45.0                  # the harmony's drift (problem 5)
LATE_BARS = range(8, 14)                              # bars 9 to 14 (problem 6): the drums, more late each bar
HISS_DB = -50.0                                       # (problem 3)


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


# ---------------------------------------------------------------- the instruments
def put(x, start, y):
    i = int(round(start * SR))
    if i < 0:
        y, i = y[-i:], 0
    m = min(len(y), len(x) - i)
    if m > 0:
        x[i:i + m] += y[:m]


def drums(rng):
    x = np.zeros(N)
    tk = np.arange(int(0.4 * SR)) / SR
    kick = np.sin(2 * np.pi * np.cumsum(48 + 120 * np.exp(-tk * 38)) / SR) * np.exp(-tk * 9) * 0.9
    ts = np.arange(int(0.25 * SR)) / SR
    noise = rng.standard_normal(len(ts))
    snare = (np.diff(noise, prepend=0) * np.exp(-ts * 22) * 0.45 + np.sin(2 * np.pi * 185 * ts) * np.exp(-ts * 30) * 0.45)
    th = np.arange(int(0.06 * SR)) / SR
    hat = np.diff(rng.standard_normal(len(th)), prepend=0) * np.exp(-th * 85) * 0.22
    for bar in range(BARS):
        late = (0.020 + 0.009 * (bar - 8)) if bar in LATE_BARS else 0.0
        t0 = bar * BAR
        for b, kind in ((0, "k"), (1, "s"), (2, "k"), (2.5, "k"), (3, "s")):
            if kind == "k" and b == 2.5 and bar % 2 == 0:
                continue
            put(x, t0 + b * BEAT + late + rng.normal(0, 0.003), kick if kind == "k" else snare)
        for h in range(8):
            put(x, t0 + h * BEAT / 2 + late + rng.normal(0, 0.002), hat * (1.0 if h % 2 == 0 else 0.6))
    return x


def bass(rng, hot=True):
    x = np.zeros(N)
    for bar in range(BARS):
        f = ROOTS[bar % 4]
        for b, ln, mult in ((0, 0.9, 1), (1.5, 0.4, 1), (2, 0.9, 1.5), (3.5, 0.4, 1)):
            n = int(ln * BEAT * SR * 1.15)
            t = np.arange(n) / SR
            ff = f * mult
            y = (np.sin(2 * np.pi * ff * t) + 0.35 * np.sin(4 * np.pi * ff * t) + 0.15 * np.sin(6 * np.pi * ff * t))
            y *= np.minimum(1, t / 0.006) * np.exp(-t * 3.2) * np.minimum(1, (t[-1] - t) / 0.02 + 0.0)
            y = y * 0.5 * (2.0 if hot and bar in HOT_BARS and b in (0, 2) else 1.0)       # too hot: flattened below
            put(x, bar * BAR + b * BEAT + rng.normal(0, 0.003), y)
    return np.clip(x, -1.0, 1.0)


def keys(rng):
    x = np.zeros(N)
    for bar in range(BARS):
        for b in (0, 2.5):
            for f in CHORDS[bar % 4]:
                n = int(1.6 * BEAT * SR)
                t = np.arange(n) / SR
                ph = rng.uniform(0, 2 * np.pi)
                y = (np.sin(2 * np.pi * f * t + ph) + 0.45 * np.sin(4 * np.pi * f * t + ph) * np.exp(-t * 5)
                     + 0.18 * np.sin(6 * np.pi * f * t + ph) * np.exp(-t * 9))
                y *= np.minimum(1, t / 0.004) * np.exp(-t * 2.3) * np.minimum(1, (t[-1] - t) / 0.05)
                put(x, bar * BAR + b * BEAT + rng.normal(0, 0.004), y * 0.12)
    return x


def melody():
    """[(start s, length s, MIDI note)] for the lead: bars 3 to 8 and 11 to 16, a held note across the cut at 27 s."""
    out = []
    plan = {2: [(0, 1, 57), (1, 1, 60), (2, 2, 64)], 3: [(0, 1.5, 65), (1.5, .5, 64), (2, 2, 60)],
            4: [(0, 1, 64), (1, 1, 67), (2, 2, 64)], 5: [(0, 1.5, 62), (1.5, .5, 59), (2, 2, 62)],
            6: [(0, 1, 57), (1, 1, 60), (2, 2, 64)], 7: [(0, 1.5, 65), (1.5, .5, 64), (2, 2, 60)],
            10: [(0, 1.5, 64), (1.5, 3.0, 67)], 11: [(1, 1, 67), (2, 2, 64)],
            12: [(0, 1, 60), (1, 1, 64), (2, 2, 67)], 13: [(0, 1.5, 65), (1.5, .5, 64), (2, 2, 60)],
            14: [(0, 1, 64), (1, 1, 62), (2, 1, 59), (3, 1, 62)], 15: [(0, 3.5, 57)]}
    for bar, notes in plan.items():
        for b, ln, m in notes:
            out.append((bar * BAR + b * BEAT, ln * BEAT * 0.94, m))
    return out


def sing(f0, rng, amp):
    """A sung-like voice: a harmonic source shaped by vowel resonances, with vibrato, a little breath and a gentle onset."""
    n = len(f0)
    t = np.arange(n) / SR
    ph = 2 * np.pi * np.cumsum(f0) / SR
    y = np.zeros(n)
    for h in range(1, 27):
        fh = f0 * h
        g = (np.exp(-((fh - 720) / 230) ** 2) + 0.6 * np.exp(-((fh - 1250) / 300) ** 2)
             + 0.25 * np.exp(-((fh - 2650) / 550) ** 2) + 0.04) / h ** 1.05
        y += g * np.sin(h * ph)
    breath = np.diff(rng.standard_normal(n), prepend=0) * 0.012
    env = np.minimum(1, t / 0.035) * np.minimum(1, (t[-1] - t) / 0.09)
    return (y + breath) * env * amp


def vocal(rng, harmony=False, gain_db=0.0):
    """The lead (or the harmony a diatonic third above it). The harmony's pitch drifts sharp from DRIFT_FROM on."""
    x = np.zeros(N)
    for start, ln, m in melody():
        if harmony:
            m = SCALE_ALL[SCALE_ALL.index(m) + 2]
        n = int(ln * SR)
        t = np.arange(n) / SR
        cents = (rng.normal(0, 4.0)                                              # the singer's own small miss
                 + 13 * np.sin(2 * np.pi * 5.4 * t + rng.uniform(0, 6.28)) * np.clip((t - 0.15) / 0.25, 0, 1)   # vibrato
                 - 55 * np.exp(-t / 0.05))                                       # a scoop into the note
        if harmony:
            now = start + t
            cents = cents + DRIFT_CENTS * np.clip((now - DRIFT_FROM) / (DUR - DRIFT_FROM), 0, 1)
        put(x, start + rng.normal(0, 0.006), sing(hz(m) * 2 ** (cents / 1200), rng, 0.30 if not harmony else 0.22))
    return x * 10 ** (gain_db / 20)


# ---------------------------------------------------------------- the whole song
def make(seed=7):
    """{name: audio} for the stems as flattened comps, and the separate takes the REAPER project plays."""
    rng = np.random.default_rng(seed)
    d, b, k1 = drums(rng), bass(rng), keys(rng)
    k2 = keys(rng)                                                  # a second take of the same part
    l1 = vocal(rng)
    l2 = vocal(rng, gain_db=LEAD_JUMP_DB)                            # another pass, sung a bit louder
    h = vocal(rng, harmony=True)
    h = h + rng.standard_normal(N) * 10 ** (HISS_DB / 20)            # hiss, all the way through
    ck, cl = int(CUT_KEYS * SR), int(CUT_LEAD * SR)
    keys_comp = np.concatenate([k1[:ck], k2[ck:]])                   # a hard splice: the click
    xf = int(0.010 * SR)
    ramp = np.linspace(0, 1, xf)
    lead_comp = np.concatenate([l1[:cl - xf], l1[cl - xf:cl] * (1 - ramp) + l2[cl - xf:cl] * ramp, l2[cl:]])
    return {"Drums": d, "Bass": b, "Keys": keys_comp, "Lead Vocal": lead_comp, "Harmony": h,
            "Keys take 1": k1, "Keys take 2": k2, "Lead Vocal take 1": l1, "Lead Vocal take 2": l2}


def levels(takes):
    """Set the drums and the keys to a sensible level (the keys' two takes and their comp by the same amount)."""
    out = dict(takes)
    s = 0.8 / (np.abs(takes["Drums"]).max() + 1e-9)
    out["Drums"] = takes["Drums"] * s
    s = 0.4 / (np.abs(takes["Keys take 1"]).max() + 1e-9)
    for k in ("Keys", "Keys take 1", "Keys take 2"):
        out[k] = takes[k] * s
    return out


def problems():
    """The six things wrong with the song, as data: what, where, and which command finds it."""
    bar = lambda i: i * BAR
    mm = lambda s: f"{int(s // 60)}:{s % 60:05.2f}"
    return [
        dict(n=1, what="a click: the keys' two takes meet with no fade", where=f"{mm(CUT_KEYS)} on Keys", at=CUT_KEYS,
             found_by="scan (clips) on the REAPER project; `clicks` on the stems", fix="a short fade at the cut"),
        dict(n=2, what=f"a level jump: the lead's second take is {LEAD_JUMP_DB:g} dB louder, joined in a held note",
             where=f"{mm(CUT_LEAD)} on Lead Vocal", at=CUT_LEAD, found_by="scan (clips) on the REAPER project",
             fix="ease the level across the cut"),
        dict(n=3, what=f"hiss: steady noise about {-HISS_DB:.0f} dB under full scale, heard in the pauses", where="all of Harmony",
             at=0.0, found_by="scan (recordings and noise)", fix="de-hiss into a new file (`dehiss`)"),
        dict(n=4, what="clipped peaks: the bass was recorded too hot and a few of its notes are flattened",
             where=f"bars {HOT_BARS[0] + 1} and {HOT_BARS[1] + 1} ({mm(bar(HOT_BARS[0]))} to {mm(bar(HOT_BARS[1] + 1))}) on Bass",
             at=bar(HOT_BARS[0]), found_by="scan (recordings); `distortion` on a set", fix="rebuild the flattened tops (`prep` declip)"),
        dict(n=5, what=f"a harmony that drifts off pitch: sharp by up to {DRIFT_CENTS:g} cents by the end",
             where=f"from {mm(DRIFT_FROM)} on Harmony", at=DRIFT_FROM, found_by="scan (vocals: pitch of every vocal track)",
             fix="`tune` moves each note's centre; vibrato stays"),
        dict(n=6, what="hits that drift late: the whole kit falls further behind the band, 20 ms up to 65 ms",
             where=f"bars {LATE_BARS[0] + 1} to {LATE_BARS[-1] + 1} ({mm(bar(LATE_BARS[0]))} to {mm(bar(LATE_BARS[-1] + 1))}) on Drums",
             at=bar(LATE_BARS[0]), found_by="scan (timing) on the REAPER project", fix="stretch markers that nudge only those hits"),
    ]


# ---------------------------------------------------------------- the REAPER project
def quote(s):
    return f'"{s}"' if " " in s else s


def guid(n):
    return "{" + f"{n:08x}-0000-4000-8000-{n:012x}" + "}"


def item(g, name, start, length, file, soffs=0.0, fade_in=0.0, fade_out=0.0):
    f = lambda v: f"{v:.6f}".rstrip("0").rstrip(".") or "0"
    return [
        "    <ITEM", f"      POSITION {f(start)}", "      SNAPOFFS 0", f"      LENGTH {f(length)}", "      LOOP 0", "      ALLTAKES 0",
        f"      FADEIN 1 {f(fade_in)} 0 1 0 0 0", f"      FADEOUT 1 {f(fade_out)} 0 1 0 0 0", "      MUTE 0 0", "      SEL 0",
        f"      IGUID {guid(g)}", f"      IID {g}", f"      NAME {quote(name)}", "      VOLPAN 1 0 1 -1",
        f"      SOFFS {f(soffs)}", "      PLAYRATE 1 1 0 -1 0 0.0025", "      CHANMODE 0", f"      GUID {guid(g + 5000)}",
        "      <SOURCE WAVE", f'        FILE "{file}"', "      >", "    >"]


def rpp_text():
    """The project: five tracks; Keys and Lead Vocal are comps of two takes (the cuts are problems 1 and 2)."""
    short = 0.002
    tracks = [
        ("Drums", [item(1, "Drums", 0, DUR, "Audio/Drums.wav", fade_in=short, fade_out=0.05)]),
        ("Bass", [item(2, "Bass", 0, DUR, "Audio/Bass.wav", fade_in=short, fade_out=0.05)]),
        ("Keys", [item(3, "Keys take 1", 0, CUT_KEYS, "Audio/Keys take 1.wav", fade_in=short),
                  item(4, "Keys take 2", CUT_KEYS, DUR - CUT_KEYS, "Audio/Keys take 2.wav", soffs=CUT_KEYS, fade_out=0.05)]),
        ("Lead Vocal", [item(5, "Lead Vocal take 1", 0, CUT_LEAD, "Audio/Lead Vocal take 1.wav", fade_in=short, fade_out=0.010),
                        item(6, "Lead Vocal take 2", CUT_LEAD, DUR - CUT_LEAD, "Audio/Lead Vocal take 2.wav", soffs=CUT_LEAD,
                             fade_in=0.010, fade_out=0.05)]),
        ("Harmony", [item(7, "Harmony", 0, DUR, "Audio/Harmony.wav", fade_in=short, fade_out=0.05)]),
    ]
    L = ['<REAPER_PROJECT 0.1 "7.27/macOS-arm64" 1764000000', "  RIPPLE 0", f"  TEMPO {BPM:g} 4 4", "  PLAYRATE 1 0 0.25 4",
         f"  SAMPLERATE {SR} 0 0", '  RECORD_PATH "Audio" ""']
    for i, (name, items) in enumerate(tracks):
        L += [f"  <TRACK {guid(100 + i)}", f"    NAME {quote(name)}", "    VOLPAN 1 0 -1 -1 1", "    MUTESOLO 0 0 0", "    IPHASE 0",
              "    ISBUS 0 0"]
        for it in items:
            L += it
        L += ["  >"]
    L += [">"]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- writing it all
def unique_dir(parent, name):
    d, k = Path(parent) / name, 1
    while d.exists():
        k += 1
        d = Path(parent) / f"{name} {k}"
    return d


def write_demo(out, kind="folder", seed=7):
    """Write the demo into a new folder inside `out`. Returns (path to scan, the folder)."""
    parts = levels(make(seed))
    folder = unique_dir(out, TITLE)
    audio = folder / "Audio" if kind == "reaper" else folder
    audio.mkdir(parents=True)
    names = ["Drums", "Bass", "Keys", "Lead Vocal", "Harmony"] if kind == "folder" else \
        ["Drums", "Bass", "Keys take 1", "Keys take 2", "Lead Vocal take 1", "Lead Vocal take 2", "Harmony"]
    for nm in names:
        dsp.save(audio / f"{nm}.wav", parts[nm].reshape(-1, 1), SR, 24)
    backing = None
    if kind == "reaper":      # the song without the vocals: tuning reads the chords under every note from it
        mix = parts["Drums"] + parts["Bass"] + parts["Keys"]
        mix = mix * (0.9 / (np.abs(mix).max() + 1e-9))
        backing = (folder / "Instrumental.wav").resolve()
        dsp.save(backing, mix.reshape(-1, 1), SR, 24)
    prob = problems()
    lines = [f"# {TITLE}", "",
             f"A synthetic song of {DUR:.0f} seconds ({BPM:g} BPM, A minor): drums, bass, keys, a sung-like lead and a harmony. "
             "Made from scratch by `hypnomix demo`; nothing here is a recording. Six things are wrong on purpose:", "",
             "| # | what is wrong | where | found by | the fix |", "|---|---|---|---|---|"]
    lines += [f"| {p['n']} | {p['what']} | {p['where']} | {p['found_by']} | {p['fix']} |" for p in prob]
    if kind == "folder":
        lines += ["", "This is the folder kind: the stems are flat files, as exported from any DAW, so the click (1) and the level "
                  "jump (2) are already baked into the audio. A `scan` of this folder finds 3 and 4 (hiss and clipping, per file) "
                  "and `hypnomix clicks` lists 1. Problems 2, 5 and 6 need the project: `hypnomix demo --kind reaper` writes one "
                  "in which the comps are separate items, and `scan` finds all six."]
    else:
        lines += ["", f"Open `{TITLE}.rpp` in REAPER if you like, or leave REAPER closed: `scan` reads the file without it. "
                  "`Instrumental.wav` is the song without the vocals: pass it as `--backing` so the scan can check the chord "
                  "under every note, which the tuning fix (5) needs."]
    target = (folder / (TITLE + ".rpp") if kind == "reaper" else folder).resolve()     # whole paths work from any folder
    fixed = TITLE + " (fixed).rpp"        # a bare name: `fix` puts it next to the project (a relative path would be joined twice)
    lines += ["", "## Try the loop", "", "```", f'hypnomix scan "{target}" --key "A minor"' + (f' --backing "{backing}"' if backing else "") + "      # about a minute; nothing is changed",
              "hypnomix ab     <the scan folder it prints>             # hear before and after, level-matched",
              "hypnomix review <the scan folder> --serve               # or decide in a page",
              "hypnomix fix    <the scan folder> --decide ID=approve   # the ids are in REVIEW.md",
              f'hypnomix fix    <the scan folder> --approved{(" --out " + chr(34) + str(fixed) + chr(34)) if kind == "reaper" else ""}', "```",
              "", "The song's key is A minor; telling the scan saves it a question. Your original files are never changed: "
              "fixes are new files" + (" and a new project next to this one." if kind == "reaper" else "."), ""]
    (folder / "DEMO.md").write_text("\n".join(lines), encoding="utf-8")
    (folder / "demo.json").write_text(json.dumps(dict(title=TITLE, kind=kind, seed=seed, seconds=DUR, bpm=BPM, problems=prob), indent=1), encoding="utf-8")
    if kind == "reaper":
        (folder / f"{TITLE}.rpp").write_text(rpp_text(), encoding="utf-8")
        return folder / f"{TITLE}.rpp", folder
    return folder, folder


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix demo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="where the new folder is made (default hypnomix-out/demo)")
    ap.add_argument("--kind", choices=["folder", "reaper"], default="folder",
                    help="folder: the stems as WAV files (default); reaper: also a REAPER project that plays them")
    from hypnomix.core import args as A
    ap.add_argument("--seed", type=A.whole(0, 2**32 - 1), default=7, help="the same seed gives the same song (7; a whole number from 0)")
    a = ap.parse_args(argv)
    od = out_at(a.out, "demo")
    path, folder = write_demo(od, a.kind, a.seed)
    print(f"demo song ({a.kind}) written to {folder}")
    print(f"problems, with times: {folder / 'DEMO.md'}")
    print(f'next: hypnomix scan "{path}"' + (f' --backing "{folder / "Instrumental.wav"}"' if a.kind == "reaper" else ""))


if __name__ == "__main__":
    main()
