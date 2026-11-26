#!/usr/bin/env python3
"""Hand the by-hand list to your DAW: a checklist in its own words, with a marker at every spot.

`fix` changes what it can and lists the rest "by hand". `handoff` turns that list into a job you can walk down in
your own DAW. It takes a scan folder (the one you reviewed) and collects:

  - every APPROVED finding that `fix` cannot make itself (applies: manual), and
  - every finding you decided as skip or change that carries a note of yours (your words are kept on the line).
  (`--undecided` also lists the manual findings you have not answered yet.)

It writes (nothing is changed in place):
  HANDOFF.md        a checklist ordered by position: track, bar.beat and m:ss, what to do in your DAW's words
                    (Live, REAPER, Ardour or plain wording), and what to listen for there
  markers           a marker at each spot, where the DAW can take them:
                      Live scan     "<Song> (handoff).als", a NEW set next to the original with a locator at each
                                    spot (checked with `hypnomix check` before it is kept)
                      REAPER scan   "<Song> (handoff).rpp", a NEW project next to the original with a marker at each
                                    spot (read back and compared with the original)
                      anything else markers.mid (a MIDI file with a marker per spot, import it as a marker or
                                    tempo track) and markers.csv (name, seconds, bar.beat, m:ss)
                    markers.mid and markers.csv are written for every scan, too, whenever at least one item has a
                    position (when none has, only HANDOFF.md is written).

Positions come from the finding's own "where" (or, when that has none, a "first at m:ss" in its problem text); with
no tempo (a folder of stems) only times written as m:ss or seconds can be placed, and bar.beat needs `--bpm`
(20 to 400; `--beats-per-bar` is a whole number from 1 to 32). An item with no position is listed at the end, unmarked.

The wording follows your DAW preference (`hypnomix prefs set tools.daw=…`) or `--daw live|reaper|ardour|generic`.

Usage:
    hypnomix handoff SCAN_DIR [--daw live|reaper|ardour|generic] [--bpm N] [--beats-per-bar N]
                              [--undecided] [--no-markers] [--out DIR]

Files go to SCAN_DIR/handoff/ (or --out); the new .als / .rpp goes next to the original and never overwrites.
"""
import argparse, csv, gzip, json, re, struct, sys
import xml.etree.ElementTree as ET
from pathlib import Path

DAWS = ("live", "reaper", "ardour", "generic")
PREF_DAW = {"ableton": "live", "reaper": "reaper", "ardour": "ardour"}
NAME = {"live": "Live", "reaper": "REAPER", "ardour": "Ardour", "generic": "your DAW"}

# kind of job -> (words per DAW, what to listen for). {t} is the track name.
JOBS = [
    ("fader", ("fader", "level", "gain", "volume", "loud", "quiet"),
     dict(live="Select the {t} track and drag its volume fader (or write a few volume-automation points) until it sits right.",
          reaper="Move the {t} track's volume fader, or add a few points on its Volume envelope.",
          ardour="Move the {t} strip's fader, or draw gain automation on the track.",
          generic="Move the {t} fader, or draw a few volume-automation points."),
     "whether the part is easy to follow without covering the singer; compare with the part solo-ed a bar either side"),
    ("fade", ("fade", "click", "pop", "edge", "seam", "cut", "splice", "spike", "plosive"),
     dict(live="Zoom on the clip edge in Arrangement, open the Clip view and lengthen the Fade In or Fade Out (a few ms is enough).",
          reaper="Zoom on the item edge and drag the fade handle out a few ms (or set it in the item properties).",
          ardour="Zoom on the region edge and drag its fade handle out a few ms.",
          generic="Zoom on the edit point and add a very short fade (a few ms) on both sides."),
     "a click or pop at the join; play it three times, once with headphones"),
    ("eq", ("eq", "mud", "harsh", "resonan", "masking", "frequency", "low cut", "high-pass", "highpass"),
     dict(live="Add EQ Eight to {t} (or open the one on it) and make the cut or boost named here; compare with the device off.",
          reaper="Add ReaEQ to {t}'s FX chain and make the cut or boost named here; compare with the FX bypassed.",
          ardour="Add the a-EQ or ACE EQ plug-in to {t} and make the cut or boost named here; compare bypassed.",
          generic="Put an equaliser on {t} and make the cut or boost named here; compare with it bypassed."),
     "the part opening up without getting thin; toggle the EQ on and off at the same level"),
    ("compress", ("compress", "dynamic", "limit", "squash", "gate", "threshold"),
     dict(live="Open the Compressor (or Glue Compressor) on {t} and change the setting named here; watch its gain-reduction meter.",
          reaper="Open ReaComp on {t} and change the setting named here; watch its gain-reduction meter.",
          ardour="Open the a-Compressor on {t} and change the setting named here; watch its meter.",
          generic="Open the compressor or gate on {t} and change the setting named here; watch its meter."),
     "the part staying lively, not pumping or chopping words"),
    ("pan", ("pan", "stereo", "width", "phase", "polarity"),
     dict(live="Set {t}'s Pan knob in the mixer (or Utility's Width / Phase Invert for a phase problem).",
          reaper="Set {t}'s pan knob (or the polarity button in its FX chain for a phase problem).",
          ardour="Set {t}'s panner (or the polarity switch for a phase problem).",
          generic="Set {t}'s pan (or flip its polarity for a phase problem)."),
     "the part keeping its place when you switch the monitoring to mono"),
    ("pitch", ("tune", "pitch", "key", "note"),
     dict(live="Fix the note in the audio clip with Warp (Clip view: Transpose / Detune), or re-record the line.",
          reaper="Fix the note with the item's Pitch adjust (F2 > Pitch) on a split of just that note, or re-record the line.",
          ardour="Split the note out as its own region and set its pitch shift, or re-record the line.",
          generic="Split just that note out, correct its pitch, or re-record the line."),
     "the note sitting in the chord without sounding processed; keep the vibrato"),
    ("timing", ("timing", "late", "early", "nudge", "align", "drag", "rush"),
     dict(live="Nudge the clip (or just that hit, with a split) a few ms with the arrow keys; or drag its warp marker.",
          reaper="Split the hit out and nudge the item a few ms, or drag its stretch marker.",
          ardour="Split the hit out and nudge the region with the nudge clock.",
          generic="Split the hit out and move it a few ms toward the band."),
     "the hit locking with the kick or drums; loop two bars around it"),
]
DEFAULT = ("other", (),
           dict(live="Open the {t} track in Live and make the change named here.",
                reaper="Open the {t} track in REAPER and make the change named here.",
                ardour="Open the {t} track in Ardour and make the change named here.",
                generic="Open the {t} track and make the change named here."),
           "whether the change helps the song when you listen to it in context, not only on its own")


# Recording problems are in the file itself, so a fader or a clip-level move is not the answer. Looked up by kind, for
# the findings the recording and noise checks make (tool recording, noise, dehiss, deess or breaths).
RECORDING_TOOLS = ("recording", "noise", "dehiss", "deess", "breaths")
_PEAKS = ("peaks", ("clipped", "hot"),
          dict(live="Double-click {t}'s clip to open it in Clip view and look at the waveform for flat tops. Flattened peaks "
                    "cannot be repaired by turning them down: use a cleaner take, or re-record with the input level lower.",
               reaper="Zoom in on {t}'s item and look at the waveform for flat tops. Flattened peaks cannot be repaired by "
                      "turning them down: use a cleaner take, or re-record with the input level lower.",
               ardour="Zoom in on {t}'s region and look at the waveform for flat tops. Flattened peaks cannot be repaired by "
                      "turning them down: use a cleaner take, or re-record with the input level lower.",
               generic="Zoom in on {t}'s audio and look at the waveform for flat tops. Flattened peaks cannot be repaired by "
                       "turning them down: use a cleaner take, or re-record with the input level lower."),
          "flattened, crackly peaks on the loudest notes; a take recorded lower sounds rounder, even when it is quieter")
_QUIET = ("quiet", ("quiet",),
          dict(live="Raise {t}'s clip gain in Clip view (not the fader), then play the gaps between phrases: turning a quiet "
                    "take up also turns its noise up.",
               reaper="Raise {t}'s item volume (not the track fader), then play the gaps between phrases: turning a quiet take "
                      "up also turns its noise up.",
               ardour="Raise {t}'s region gain (not the strip fader), then play the gaps between phrases: turning a quiet take "
                      "up also turns its noise up.",
               generic="Raise {t}'s clip or item gain (not the fader), then play the gaps between phrases: turning a quiet take "
                       "up also turns its noise up."),
          "the noise in the gaps staying out of the way once the part is at a normal level")
_NOISE = ("noise", ("noise", "boosted-noise"),
          dict(live="Play the gaps between phrases on {t}. If it is hiss, swap in the cleaned copy for that clip (or record the "
                    "part hotter); turning the clip down hides the part as well as the noise.",
               reaper="Play the gaps between phrases on {t}. If it is hiss, swap in the cleaned copy on that item (or record the "
                      "part hotter); turning the item down hides the part as well as the noise.",
               ardour="Play the gaps between phrases on {t}. If it is hiss, swap in the cleaned copy for that region (or record "
                      "the part hotter); turning the region down hides the part as well as the noise.",
               generic="Play the gaps between phrases on {t}. If it is hiss, swap in the cleaned copy (or record the part "
                       "hotter); turning it down hides the part as well as the noise."),
          "the gaps going quiet without the part turning dull or watery; compare the cleaned copy with the original at the same level")
_DC = ("dc", ("dc",),
       dict(live="Put a Utility on {t} and switch its DC filter on, or use the cleaned copy.",
            reaper="Put a high-pass at about 20 Hz in ReaEQ on {t}'s FX chain, or use the cleaned copy.",
            ardour="Put a high-pass filter plug-in at about 20 Hz on {t} (Ardour's own high/low-pass filter), or use the cleaned copy.",
            generic="Put a very low high-pass (about 20 Hz) on {t}, or use the cleaned copy."),
       "no click where the clip starts or stops, and the low end sounding the same")
_UNREADABLE = ("unreadable", ("unreadable",),
               dict(live="Export {t}'s audio again as a WAV file and put that in the set.",
                    reaper="Export {t}'s audio again as a WAV file and put that on the item.",
                    ardour="Export {t}'s audio again as a WAV file and import that.",
                    generic="Export {t}'s audio again as a WAV file."),
               "the new file playing from start to end, the same length as before")
_SILENT = ("silent", ("silent",),
           dict(live="Play {t}'s clip in Live. If it is silent, the wrong track or range was exported: export it again, or put "
                     "the right file in the set.",
                reaper="Play {t}'s item in REAPER. If it is silent, the wrong track or range was exported: export it again, or "
                       "put the right file on the item.",
                ardour="Play {t}'s region in Ardour. If it is silent, the wrong track or range was exported: export it again, "
                       "or import the right file.",
                generic="Play {t}'s audio. If it is silent, the wrong track or range was exported: export it again, or use the "
                        "right file."),
           "the part playing at its normal level from start to end once the right file is in place")
RECORDING_JOBS = {k: j for j in (_PEAKS, _QUIET, _NOISE, _DC, _UNREADABLE, _SILENT) for k in j[1]}


def job_for(f):
    """The kind of job: recording problems first (by their kind), then the finding's tool and kind, then the words of
    its problem and fix."""
    if f.get("tool") in RECORDING_TOOLS and f.get("kind") in RECORDING_JOBS:
        return RECORDING_JOBS[f["kind"]]
    for fields in (("tool", "kind"), ("problem", "fix")):
        text = " ".join(str(f.get(k) or "") for k in fields).lower()
        for job in JOBS:
            if any(w in text for w in job[1]):
                return job
    return DEFAULT


# ---------------------------------------------------------------- positions
PAREN = re.compile(r"\(\s*(\d+(?:\.\d+)?)\s*s\s*\)")
MMSS = re.compile(r"\b(\d+):(\d\d(?:\.\d+)?)\b")
SECS = re.compile(r"(\d+(?:\.\d+)?)\s*s\b")
BARBEAT = re.compile(r"\b(\d+)\.(\d+)(?:\.(\d+))?\b")
BARS = re.compile(r"\bbars?\s+(\d+(?:\s*[,-]\s*\d+)*)", re.I)


def positions(where, tempo=None, bpb=4):
    """Every place a `where` text names, as seconds (None when it can't be placed). -> [seconds, ...]"""
    where = where or ""
    m = PAREN.search(where)
    if m:                                                    # "2.1.00 (5.40 s)": the project readers' form
        return [float(m.group(1))]
    m = MMSS.search(where)
    if m:
        return [int(m.group(1)) * 60 + float(m.group(2))]
    if tempo:
        m = BARBEAT.search(where)
        if m and not SECS.search(where):
            bar, beat, frac = int(m.group(1)), int(m.group(2)), m.group(3)
            beats = (bar - 1) * bpb + (beat - 1) + (int(frac) / 100.0 if frac else 0.0)
            return [beats * 60.0 / tempo]
        m = BARS.search(where)
        if m:
            return [(int(b) - 1) * bpb * 60.0 / tempo for b in re.findall(r"\d+", m.group(1))]
    m = SECS.search(where)
    if m:
        return [float(m.group(1))]
    return []


FIRST_AT = re.compile(r"\bfirst at (\d+):(\d\d(?:\.\d+)?)\b")


def finding_positions(f, tempo=None, bpb=4):
    """Where a finding is: its `where`, else the time its own problem text states ("first at 0:15.0": a stems-folder
    scan keeps the time of the first clipped peak there and leaves `where` empty)."""
    ps = positions(f.get("where"), tempo, bpb)
    if not ps:
        m = FIRST_AT.search(str(f.get("problem") or ""))
        if m:
            ps = [int(m.group(1)) * 60 + float(m.group(2))]
    return ps


def mmss(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def barbeat(t, tempo, bpb):
    if not tempo:
        return ""
    beats = t * tempo / 60.0
    b = int(beats // bpb)
    rem = beats - b * bpb
    return f"{b + 1}.{int(rem) + 1}"


# ---------------------------------------------------------------- collecting
def collect(sd, undecided=False):
    """The items for the checklist: [dict(finding, why, note)]."""
    from hypnomix.workflow import oversight as O
    data = O.load_findings_doc(sd)
    dec = O.load_decisions(sd) or {}
    items = []
    for f in data["findings"]:
        d = dec.get(f["id"])
        what = d.get("decision") if isinstance(d, dict) else d
        note = (d.get("note") if isinstance(d, dict) else "") or ""
        if what == "approve" and f.get("applies") == "manual":
            items.append(dict(f=f, why="approved, and not something hypnomix can change itself", note=note))
        elif what in ("skip", "change") and note.strip():
            items.append(dict(f=f, why=f"you decided {what} and left a note", note=note))
        elif undecided and what is None and f.get("applies") == "manual":
            items.append(dict(f=f, why="not decided yet", note=""))
    return items, data


def context(sd, data, bpm=None, bpb=None):
    """(set path or None, daw kind or None, tempo, beats per bar)."""
    from hypnomix.core import atomic
    sj = atomic.load_json(sd / "scan.json", {}) or {}
    src = sj.get("set") or data.get("set")
    path = Path(src) if src and sj.get("mode") not in ("folder", "file") and Path(src).exists() else None
    tempo, bar_len, kind = bpm, bpb or 4, None
    if path is not None:
        from hypnomix import project as PJ
        kind = PJ.daw_of(path)
        try:
            p = PJ.load(path)
            tempo = tempo or p.tempo
            bar_len = bpb or p.beats_per_bar
        except SystemExit:
            pass
    return path, kind, tempo, bar_len


def build(items, tempo, bpb):
    rows = []
    for it in items:
        f = it["f"]
        ps = finding_positions(f, tempo, bpb)
        for t in (ps or [None]):
            rows.append(dict(item=it, t=t))
    rows.sort(key=lambda r: (r["t"] is None, r["t"] or 0, r["item"]["f"].get("track") or ""))
    return rows


# ---------------------------------------------------------------- checklist
def checklist(song, rows, daw, tempo, bpb):
    job_name = NAME[daw]
    L = [f"# Hand-off: {song}", "",
         f"What hypnomix could not do itself, in {job_name}'s words, in song order. Tick each as you go. "
         "Everything here was measured, not heard: your ears decide.", ""]
    if not tempo:
        L += ["No tempo is known for this scan (a folder of stems), so positions are shown as m:ss where the finding has one; "
              "give `--bpm` for bar.beat.", ""]
    for n, r in enumerate(rows, 1):
        f, t = r["item"]["f"], r["t"]
        job = job_for(f)
        trk = f.get("track") or "the mix"
        pos = "no position (whole part)" if t is None else (
            (f"bar {barbeat(t, tempo, bpb)} · " if tempo else "") + f"{mmss(t)}")
        L += [f"## {n}. {trk} · {pos}", "",
              f"- [ ] **To do ({job_name}):** {job[2][daw].format(t=trk)}",
              f"  - what was found: {f.get('problem') or f.get('kind')}",
              f"  - what hypnomix suggests: {str(f.get('fix') or '').strip()[:400] or 'see the finding'}"]
        if r["item"]["note"].strip():
            L.append(f"  - your note: {r['item']['note'].strip()}")
        L += [f"  - **Listen for:** {f.get('listen') or job[3]}",
              f"  - why it is here: {r['item']['why']} (finding `{f['id']}`)", ""]
    if not rows:
        L += ["Nothing to hand over: every approved item was made by `fix`, and no skipped item carries a note.", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- markers
def marker_names(rows):
    out = []
    for n, r in enumerate(rows, 1):
        f = r["item"]["f"]
        out.append(f"{n}. {f.get('track') or 'mix'}: {str(f.get('kind') or f.get('tool') or 'to do')[:40]}")
    return out


def write_csv(path, rows, names, tempo, bpb):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "seconds", "bar.beat", "m:ss", "track", "finding", "to do"])
        for nm, r in zip(names, rows):
            if r["t"] is None:
                continue
            f = r["item"]["f"]
            w.writerow([nm, f"{r['t']:.3f}", barbeat(r["t"], tempo, bpb), mmss(r["t"]), f.get("track") or "", f["id"],
                        str(f.get("fix") or "")[:200]])


def _vlq(n):
    n = max(0, int(n))                          # a negative number would never reach 0 below
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def midi_bytes(rows, names, tempo):
    """A format-0 MIDI file at `tempo` bpm (480 ticks per beat): a tempo event and a marker meta event per spot."""
    tempo = tempo or 120.0
    ppq = 480
    ev = [(0, b"\xff\x51\x03" + struct.pack(">I", int(60_000_000 / tempo))[1:])]
    for nm, r in zip(names, rows):
        if r["t"] is None:
            continue
        txt = nm.encode("ascii", "replace")
        ev.append((int(round(r["t"] * tempo / 60.0 * ppq)), b"\xff\x06" + _vlq(len(txt)) + txt))
    ev.sort(key=lambda e: e[0])
    body, last = b"", 0
    for tick, data in ev:
        body += _vlq(tick - last) + data
        last = tick
    body += b"\x00\xff\x2f\x00"
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, ppq) + b"MTrk" + struct.pack(">I", len(body)) + body


def new_name(src, suffix):
    out = src.with_name(f"{src.stem} (handoff){suffix}")
    k = 1
    while out.exists():
        k += 1
        out = src.with_name(f"{src.stem} (handoff {k}){suffix}")
    return out


def write_als(src, rows, names, tempo):
    """A new set with a locator at each spot (Time is in beats). Existing locators stay."""
    from hypnomix.session import automation as aa
    from hypnomix.session import check as C
    tree = aa.load(src)
    root = tree.getroot()
    ls = root.find("LiveSet") if root.find("LiveSet") is not None else root
    outer = ls.find("Locators")
    if outer is None:
        outer = ET.SubElement(ls, "Locators")
    inner = outer.find("Locators")
    if inner is None:
        inner = ET.SubElement(outer, "Locators")
    ids = [int(e.get("Id")) for e in root.iter("Locator") if (e.get("Id") or "").isdigit()]
    nxt = max(ids, default=-1) + 1
    for nm, r in zip(names, rows):
        if r["t"] is None:
            continue
        loc = ET.SubElement(inner, "Locator", Id=str(nxt))
        nxt += 1
        ET.SubElement(loc, "LomId", Value="0")
        ET.SubElement(loc, "Time", Value=f"{r['t'] * tempo / 60.0:g}")
        ET.SubElement(loc, "Name", Value=nm)
        ET.SubElement(loc, "Annotation", Value="")
        ET.SubElement(loc, "IsSongStart", Value="false")
    out = new_name(src, ".als")
    aa.save(tree, src, out)
    errs, _, _ = C.check(out, src)
    if errs:
        bad = out.with_name(out.stem + " (BROKEN, do not open).als")
        out.rename(bad)
        raise SystemExit("the set with locators failed the structure check, so it was kept as "
                         f"{bad.name}: {'; '.join(errs)}")
    return out


def write_rpp(src, rows, names):
    """A new project with a marker at each spot, after any markers it already has."""
    from hypnomix.project import rpp
    from hypnomix.project import rpp_edit as E
    root = rpp.load(src)
    have = [l for l in root.lines("MARKER")]
    idx = max([int(l.tokens[1]) for l in have if len(l.tokens) > 1 and l.tokens[1].isdigit()], default=0)
    first_track = next((c for c in root.children if isinstance(c, rpp.Chunk) and c.name == "TRACK"), None)
    at = root.children.index(first_track) if first_track is not None else len(root.children)
    if have:
        at = root.children.index(have[-1]) + 1
    k = 0
    for nm, r in zip(names, rows):
        if r["t"] is None:
            continue
        idx += 1
        ln = rpp.Line(["MARKER", idx, round(r["t"], 6), nm, 0, 0, 1, "B", E.guid(), 0], indent="  ")
        root.children.insert(at + k, ln)
        k += 1
    out = new_name(Path(src), ".rpp")
    rpp.save(root, out)
    errs = E.check(src, out)
    if errs:
        bad = out.with_name(out.stem + " (BROKEN, do not open).rpp")
        out.rename(bad)
        raise SystemExit(f"the project with markers failed its check, so it was kept as {bad.name}: {'; '.join(errs)}")
    return out


# ---------------------------------------------------------------- main
def handoff(sd, daw=None, bpm=None, bpb=None, undecided=False, markers=True, out=None):
    sd = Path(sd)
    if not (sd / "findings.json").exists():
        raise SystemExit(f"{sd} has no findings.json: give a scan folder (hypnomix scan … / --plan)")
    items, data = collect(sd, undecided)
    path, kind, tempo, bar_len = context(sd, data, bpm, bpb)
    if daw is None:
        try:
            from hypnomix.workflow import prefs as P
            daw = PREF_DAW.get(str(P.get(P.load(), "tools.daw") or ""), None)
        except Exception:
            daw = None
        daw = daw or {"live": "live", "reaper": "reaper", "ardour": "ardour"}.get(kind or "", "generic")
    rows = build(items, tempo, bar_len)
    od = Path(out) if out else sd / "handoff"
    od.mkdir(parents=True, exist_ok=True)
    song = (path.stem if path else Path(data.get("set") or sd).stem) or sd.name
    md = od / "HANDOFF.md"
    k = 1
    while md.exists():
        k += 1
        md = od / f"HANDOFF {k}.md"
    md.write_text(checklist(song, rows, daw, tempo, bar_len), encoding="utf-8")
    written = [md]
    placed = [r for r in rows if r["t"] is not None]
    if markers and placed:
        names = marker_names(rows)
        csvp = od / md.name.replace("HANDOFF", "markers").replace(".md", ".csv")
        midp = csvp.with_suffix(".mid")
        write_csv(csvp, rows, names, tempo, bar_len)
        midp.write_bytes(midi_bytes(rows, names, tempo))
        written += [csvp, midp]
        if path is not None and kind == "live" and tempo:
            written.append(write_als(path, rows, names, tempo))
        elif path is not None and kind == "reaper":
            written.append(write_rpp(path, rows, names))
    return dict(rows=rows, files=written, daw=daw, items=len(items), placed=len(placed))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix handoff", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    from hypnomix.session import liveversion as LV; LV.add_force_flag(ap)
    ap.add_argument("scan_dir")
    ap.add_argument("--daw", choices=DAWS, help="wording for this DAW (default: your tools.daw preference, else the scanned project's)")
    from hypnomix.core import args as A
    ap.add_argument("--bpm", type=A.number(20, 400), help="tempo for bar.beat when the scan has none (a folder of stems; 20 to 400)")
    ap.add_argument("--beats-per-bar", type=A.whole(1, 32), dest="bpb", help="beats in a bar (1 to 32; default: the project's, else 4)")
    ap.add_argument("--undecided", action="store_true", help="also list by-hand findings you have not decided yet")
    ap.add_argument("--no-markers", action="store_true", help="the checklist only")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    res = handoff(a.scan_dir, a.daw, a.bpm, a.bpb, a.undecided, not a.no_markers, a.out)
    print(f"{res['items']} item(s) for {NAME[res['daw']]}, {res['placed']} spot(s) with a position.")
    for p in res["files"]:
        print(f"wrote {p}")
    if not res["items"]:
        print("nothing to hand over (approve by-hand items, or add a note to a skipped one).")


if __name__ == "__main__":
    main()
