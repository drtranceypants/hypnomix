"""Read a .logicx project (a package; a .band too) into the import model (hypnomix.project.importer).

The package keeps the project in Alternatives/NNN/ProjectData, a binary file its maker does not document. This reader
decodes the parts below, worked out on real packages saved by version 10.7 and compared with the window image each
package stores of itself (fader readouts, mutes, plug-in names, region places; the program itself was not run), with
community notes on the format as a guide (no code taken). It only reads.

  file      a 24-byte header, then records: tag (4 bytes, reversed), version, class, group (u16 @0x0a), index
            (u32 @0x0e), payload length (u64 @0x1c); the payload follows the 36-byte record header
  tempo     EvSq class 3: 32-byte events, position (u32 @4, ticks + 38400), tempo (u32 @0x10, BPM x 10000)
  meter     EvSq class 1: denominator exponent @0x0b, numerator @0x0c
  tracks    the arrangement's MSeq is followed by its Trak rows (in order); a row's channel is u32 @8, the Envi
            (environment object) of that group: its name (u16 + text @0x9e) is the track name, the byte after the
            name is the audio channel number, which picks the mixer strip (AuCO, group 0x24, index channel - 1)
  mixer     AuCO: fader u32 @0x74 / 2^24 on Logic's 0..127 scale, dB = 40 log10(v / 90) (90 = 0 dB, 127 = +6 dB);
            pan byte @0x59 (0..127, 64 = centre); mute byte @0x5a
  plug-ins  AuCU records of a strip (header index) starting ?? 01 00 00 01 00: name, insert position (u16 @6)
  audio     AuFl (group g): file name (UTF-16, u16 count @8, text @0x0a); AuRg (group g, index i): start in the file
            (u64 @6) and length (u64 @0x16) in samples, name (u16 + text @0x4a)
  placement the arrangement EvSq: 80-byte events of type 0x24 (audio): position (u32 @4 ticks + u16 @2 / 65536,
            from 34560), track row (u8 @0x14, from 1, counting every Trak row of the arrangement: in the packages
            checked, rows of other kinds only came after the audio rows, so this was not told apart from counting
            audio rows only; a package with another row first gets a warning), region index (u32 @0x28), file
            group (u32 @0x2c);
            looped length (u32 @0x1c, ticks from the position; 0x3fffffff = not looped);
            type 0x20 (a MIDI region or folder): the MSeq / EvSq group it plays (u32 @0x20)
  MIDI      notes in that EvSq: 32-byte events of type 0x90: position (u32 @4, ticks + 38400, from the region's
            start), velocity @0x0b, key @0x0c, length (u32 @0x1c); 960 ticks per quarter note

Not carried yet (the report says so): region gain and fades, Flex Time and Flex Pitch, take folders other than the
active comp, sends and bus routing, solo, markers, automation, software instruments and plug-in settings (listed by
name; a name is the first readable text of its record). Packages saved by other versions may differ: the record walk
and the header are checked, and the report warns when the package was saved by a version this was not checked on.
"""
import math
import plistlib
import re
import struct
from pathlib import Path

PPQ = 960
REGION_ORIGIN = 34560            # 9 bars of 4/4 at 960 PPQ: placement positions count from here
TEMPO_ORIGIN = 38400             # tempo, meter and note positions count from here
MAGIC = b"#G\xc0\xab"
MAX_BYTES = 512 * 1024 * 1024
SEARCH_LIMIT = 20000
NO_LOOP = 0x3FFFFFFF            # a placement's loop length when the region does not loop
MAX_PASSES = 256                # passes of one looped region; more are not placed (the report says so)
MIN_PASS = 0.05                 # a looped region shorter than this (s) is placed once, not unrolled
CHECKED_VERSIONS = ("10.7",)    # LastSavedFrom versions this reader was checked on


class Record:
    __slots__ = ("tag", "cls", "group", "index", "sub", "data", "pos")

    def __init__(self, tag, cls, group, index, sub, data, pos):
        self.tag, self.cls, self.group, self.index, self.sub, self.data, self.pos = tag, cls, group, index, sub, data, pos


def records(buf):
    if len(buf) < 0x18 or buf[:4] != MAGIC:
        raise SystemExit("not a .logicx ProjectData file (its header is not the one these files start with)")
    out, pos = [], 0x18
    while pos + 36 <= len(buf):
        tag = buf[pos:pos + 4][::-1].decode("latin1")
        cls = struct.unpack_from("<H", buf, pos + 6)[0]
        group = struct.unpack_from("<H", buf, pos + 0x0a)[0]
        index = struct.unpack_from("<I", buf, pos + 0x0e)[0]
        sub = struct.unpack_from("<I", buf, pos + 0x12)[0]
        n = struct.unpack_from("<Q", buf, pos + 0x1c)[0]
        if n > len(buf) - pos - 36:
            raise SystemExit(f"the project data is damaged or saved by a version this reader does not know "
                             f"(a record at byte {pos} runs past the end)")
        out.append(Record(tag, cls, group, index, sub, buf[pos + 36:pos + 36 + n], pos))
        pos += 36 + n
    if pos != len(buf):
        raise SystemExit("the project data does not end where its records say (saved by a version this reader does not know)")
    return out


def _u16(b, o, d=0):
    return struct.unpack_from("<H", b, o)[0] if len(b) >= o + 2 else d


def _u32(b, o, d=0):
    return struct.unpack_from("<I", b, o)[0] if len(b) >= o + 4 else d


def _u64(b, o, d=0):
    return struct.unpack_from("<Q", b, o)[0] if len(b) >= o + 8 else d


def _text(b, o, n):
    return b[o:o + n].split(b"\0")[0].decode("utf-8", "replace")


def events(data, size_of):
    """The events of an EvSq payload, up to the 0xF1 end marker: [(offset, type)]."""
    out, o = [], 0
    while o + 4 <= len(data):
        t = data[o]
        if t == 0xF1:
            break
        size = size_of(t, data, o)
        if not size:
            break
        out.append((o, t))
        o += size
    return out


def _evsize(t, data, o):
    return {0x24: 80, 0x20: 80, 0x60: 32, 0x30: 48, 0x12: 48, 0x11: 16, 0x10: 16, 0x90: 32}.get(t)


def fader_gain(v):
    """Logic's fader position (0..127, 90 = 0 dB) -> linear gain: dB = 40 log10(v / 90)."""
    return 0.0 if v <= 0 else (v / 90.0) ** 2


def pick_alternative(bundle):
    alts = sorted((p for p in (bundle / "Alternatives").glob("*") if (p / "ProjectData").is_file()), key=lambda p: p.name)
    if not alts:
        raise SystemExit(f"{bundle.name}: no project data inside (Alternatives/*/ProjectData)")
    try:
        info = plistlib.loads((bundle / "Resources" / "ProjectInformation.plist").read_bytes())
        active = info.get("ActiveVariant")
        if isinstance(active, int):
            want = bundle / "Alternatives" / f"{active:03d}"
            if (want / "ProjectData").is_file():
                return want
    except (OSError, plistlib.InvalidFileException, ValueError):
        pass
    return alts[0]


class Reader:
    def __init__(self, bundle):
        self.bundle = bundle
        self.alt = pick_alternative(bundle)
        data = self.alt / "ProjectData"
        if data.stat().st_size > MAX_BYTES:
            raise SystemExit(f"{bundle.name}: the project data is too big to read")
        self.recs = records(data.read_bytes())
        try:
            self.meta = plistlib.loads((self.alt / "MetaData.plist").read_bytes())
        except (OSError, plistlib.InvalidFileException, ValueError):
            self.meta = {}
        self.not_carried, self.warn = [], []
        self._index = None

    # ---- files
    def locate(self, name):
        if Path(name).is_absolute() or ".." in Path(name).parts:     # never touched here: the importer decides
            return Path(name) if Path(name).is_absolute() else None
        for d in (self.bundle / "Media" / "Audio Files", self.bundle / "Audio Files", self.bundle.parent / "Audio Files",
                  self.bundle / "Media", self.bundle.parent):
            p = d / name
            if p.is_file():
                return p
        if self._index is None:
            self._index, n = {}, 0
            for p in self.bundle.rglob("*"):
                n += 1
                if n > SEARCH_LIMIT:
                    break
                if p.is_file():
                    self._index.setdefault(p.name.lower(), p)
        return self._index.get(name.lower())

    def files(self):
        out = {}
        for r in self.recs:
            if r.tag != "AuFl":
                continue
            n = _u16(r.data, 8)
            name = r.data[0x0a:0x0a + 2 * n].decode("utf-16-le", "replace")
            out[r.group] = (name, self.locate(name) if name else None)
        return out

    def regions(self):
        out = {}
        for r in self.recs:
            if r.tag != "AuRg":
                continue
            n = _u16(r.data, 0x4a)
            out[(r.group, r.index)] = dict(start=_u64(r.data, 6), length=_u64(r.data, 0x16),
                                           name=_text(r.data, 0x4c, n))
        return out

    # ---- mixer
    def strips(self):
        out = {}
        for r in self.recs:
            if r.tag == "AuCO" and r.group == 0x24 and len(r.data) >= 0x78:
                out[r.index] = dict(name=_text(r.data, 0x3d, 15), fader=_u32(r.data, 0x74) / 2 ** 24,
                                    pan=r.data[0x59], mute=bool(r.data[0x5a]))
        return out

    def plugins(self):
        """Strip index -> its insert plug-ins' names, in insert order. A plug-in record of a strip (AuCU, the strip's
        index in the header) starts with ?? 01 00 00 01 00 and holds its insert position (u16 @6); records starting
        otherwise are the strip's own settings (Smart Controls, the channel strip patch)."""
        out = {}
        for r in self.recs:
            d = r.data
            if r.tag != "AuCU" or r.group != 0x24 or len(d) < 16 or d[1:6] != b"\x01\x00\x00\x01\x00":
                continue
            words = [w.decode("latin1") for w in re.findall(rb"[\x20-\x7e]{3,}", d[:600])]
            words = [w for w in words if not re.search(r"\.(aupreset|pst|patch|cst)$|^#|^GAME|^Untitled|^bplist", w)]
            if words:
                out.setdefault(r.index, {})[_u16(d, 6)] = words[0].strip()
        return {k: [v[s] for s in sorted(v)] for k, v in out.items()}

    def channels(self):
        """Envi group -> (name, audio channel number or None)."""
        out = {}
        for r in self.recs:
            if r.tag != "Envi" or len(r.data) < 0xa2:
                continue
            n = _u16(r.data, 0x9e)
            name = _text(r.data, 0xa0, n)
            after = 0xa0 + n + (n & 1)
            ch = r.data[after] if after < len(r.data) else 0
            out[r.group] = (name, ch)
        return out

    # ---- time
    def tempo(self):
        pts = []
        for r in self.recs:
            if r.tag == "EvSq" and r.cls == 3:
                for o, t in events(r.data, _evsize):
                    if t == 0x60:
                        tick = _u32(r.data, o + 4) - TEMPO_ORIGIN
                        bpm = _u32(r.data, o + 0x10) / 10000.0
                        if 5 <= bpm <= 999:
                            pts.append((max(0, tick) / PPQ, bpm))
                break
        if not pts:
            bpm = float(self.meta.get("BeatsPerMinute") or 120.0)
            pts = [(0.0, bpm)]
        return sorted(pts)

    def meter(self):
        for r in self.recs:
            if r.tag == "EvSq" and r.cls == 1 and len(r.data) > 0x0c:
                exp, num = r.data[0x0b], r.data[0x0c]
                if 0 <= exp <= 6 and 1 <= num <= 64:
                    return num, 2 ** exp
        return int(self.meta.get("SongSignatureNumerator") or 4), int(self.meta.get("SongSignatureDenominator") or 4)

    # ---- the arrangement
    def arrangement(self):
        """(the arrangement's MSeq group, [Trak channel groups in order]). The arrangement is the class-0x17 MSeq whose
        EvSq holds audio or region placements and whose name is not one of Logic's own housekeeping sequences."""
        skip = ("TRASH", "Track Automation Root Folder", "Track Alternatives", "*Automation")
        seqs, cur = [], None
        for r in self.recs:
            if r.tag == "MSeq":
                cur = None
                if r.cls == 0x17:
                    words = re.findall(rb"[\x20-\x7e]{3,}", r.data)
                    name = words[0].decode("latin1") if words else ""
                    if not any(name.startswith(s) for s in skip):
                        cur = dict(group=r.group, name=name, rows=[])
                        seqs.append(cur)
            elif r.tag == "Trak" and cur is not None and len(r.data) >= 12:
                cur["rows"].append((r.data[0], _u32(r.data, 8)))
        ev = {r.group: r for r in self.recs if r.tag == "EvSq" and r.cls == 0x17}
        for s in seqs:
            e = ev.get(s["group"])
            if e is not None and any(t in (0x24, 0x20) for _, t in events(e.data, _evsize)) and s["rows"]:
                return s, e, ev
        for s in seqs:
            if s["rows"]:
                return s, ev.get(s["group"]), ev
        raise SystemExit("could not find the project's arrangement in the project data")

    def read(self):
        bundle = self.bundle
        files, regs, strips, plugs, chans = self.files(), self.regions(), self.strips(), self.plugins(), self.channels()
        tpts = self.tempo()
        num, den = self.meter()
        rate = int(self.meta.get("SampleRate") or 0) or None
        seq, evsq, all_ev = self.arrangement()
        from hypnomix.project import als2ardour as A
        from hypnomix.project import importer
        pts = importer.tempo_points(tpts[0][1], tpts)          # Logic's tempo events are steps, as the writer writes them
        tempo = A.Tempo(tpts[0][1], pts)

        rows = [(kind, ch) for kind, ch in seq["rows"] if kind == 1]
        from hypnomix.project.importer import Budget
        Budget(bundle.name).add(tracks=len(rows))             # before a track is built
        other_rows = len(seq["rows"]) - len(rows)
        first_audio = next((i for i, (kind, _) in enumerate(seq["rows"]) if kind == 1), 0)
        if any(kind != 1 for kind, _ in seq["rows"][:first_audio]) or \
                any(kind != 1 for kind, _ in seq["rows"][first_audio:first_audio + len(rows)]):
            self.warn.append("this package has a folder or other row before or between its audio rows: placements are "
                             "matched to rows counting every row, which was not checked on such a package; check that "
                             "each region is on the right track")
        tracks = []
        for k, (kind, ch) in enumerate(rows):
            name, number = chans.get(ch, (f"Track {k + 1}", 0))
            strip = strips.get(number - 1) if number else None
            tr = dict(name=name or f"Track {k + 1}", kind="audio", regions=[], midi=[], notes=[], plugins=[])
            if strip is not None:
                tr.update(volume=fader_gain(strip["fader"]), pan=max(-1.0, min(1.0, (strip["pan"] - 64) / 63.0)),
                          muted=strip["mute"])
                tr["plugins"] = plugs.get(number - 1, [])
            else:
                tr["notes"].append("its mixer strip could not be found: fader, pan and mute left at their defaults")
            tracks.append(tr)
        by_row, n = {}, 0                                     # row number (from 1, every row) -> its track
        for i, (kind, ch) in enumerate(seq["rows"], 1):
            if kind == 1:
                by_row[i] = tracks[n]
                n += 1

        from hypnomix.project.importer import Budget
        budget = Budget(bundle.name)
        missing_regions, off_rows, odd_events = 0, 0, 0
        looped, short_loops, cut_loops = 0, 0, 0
        note_cache, empty_midi = {}, 0
        midi_events = 0
        if evsq is not None:
            for o, t in events(evsq.data, _evsize):
                d = evsq.data
                tick = _u32(d, o + 4) + _u16(d, o + 2) / 65536.0 - REGION_ORIGIN
                row = d[o + 0x14]
                if t not in (0x24, 0x20):
                    odd_events += 1
                    continue
                tr = by_row.get(row)
                if tr is None:
                    off_rows += 1
                    continue
                beat = max(0.0, tick) / PPQ
                if t == 0x24:
                    key = (_u32(d, o + 0x2c), _u32(d, o + 0x28))
                    rg = regs.get(key)
                    f = files.get(key[0])
                    if rg is None or f is None:
                        missing_regions += 1
                        continue
                    fname, fpath = f
                    if fpath is None:                              # not found: a path that is surely not there, so
                        fpath = bundle / "Media" / "Audio Files" / Path(fname).name   # the report names the file
                    fr = self.file_rate(fpath) or rate or 48000
                    pos = tempo.seconds(beat)
                    one = rg["length"] / fr
                    loop = _u32(d, o + 0x1c)                       # a looped region: its whole length in ticks
                    end = tempo.seconds(beat + loop / PPQ) if loop != NO_LOOP and loop > 0 else pos + one
                    if one < MIN_PASS and end - pos > one:     # a tiny region looped: placed once
                        end = pos + one
                        short_loops += 1
                    if one > 0:                                    # counted before anything is built
                        budget.add(regions=min(MAX_PASSES, max(1, math.ceil((end - pos) / one - 1e-9))))
                    k = 0
                    while pos < end - 1e-6 and one > 0 and k < MAX_PASSES:   # one region per pass, the last cut
                        tr["regions"].append(dict(name=rg["name"] or fname, file=fpath,
                                                  position=pos, start=rg["start"] / fr, length=min(one, end - pos)))
                        pos, k = pos + one, k + 1
                    if pos < end - 1e-6 and k >= MAX_PASSES:
                        cut_loops += 1
                    if k > 1:
                        looped += 1
                elif t == 0x20:
                    gid = _u32(d, o + 0x20)
                    if gid not in note_cache:                       # one note list per sequence, however often placed
                        child = all_ev.get(gid)
                        note_cache[gid] = self.notes(child) if child is not None else []
                    notes = note_cache[gid]
                    if not notes:
                        empty_midi += 1
                    if notes:
                        budget.add(regions=1, notes=len(notes))
                        tr["kind"] = "midi"
                        length = max(n[0] + n[1] for n in notes)
                        tr["midi"].append(dict(name=tr["name"], position=beat, length=length, notes=notes))
                        midi_events += len(notes)
        if looped:
            self.not_carried.append(f"{looped} looped region(s): unrolled into one region per pass (the source loops "
                                    f"audio in its own time; with a tempo change inside a loop the passes follow the "
                                    f"region's own length)")
        if short_loops:
            self.not_carried.append(f"{short_loops} looped region(s) shorter than {MIN_PASS * 1000:.0f} ms: placed once, "
                                    f"not repeated")
        if cut_loops:
            self.not_carried.append(f"{cut_loops} looped region(s) with more than {MAX_PASSES} passes: only the first "
                                    f"{MAX_PASSES} are placed")
        if other_rows:
            self.not_carried.append(f"{other_rows} track row(s) of another kind (folders, or rows this reader does not "
                                    f"know): not read")
        if off_rows:
            self.not_carried.append(f"{off_rows} placement(s) on a row that is not an audio track (or past the last "
                                    f"row): not carried")
        if empty_midi:
            self.not_carried.append(f"{empty_midi} folder or MIDI region placement(s) with no notes this reader can "
                                    f"read: not carried")
        if odd_events:
            self.not_carried.append(f"{odd_events} arrangement event(s) of a type this reader does not know: not read")
        if missing_regions:
            self.warn.append(f"{missing_regions} placement(s) point at a region or file this reader could not find")
        if midi_events:
            self.not_carried.append("MIDI regions are read from the note events (this part of the reader is new and "
                                    "not checked on a real project: check the notes); software instruments are not "
                                    "carried")
        self.not_carried += [
            "region gain and fades, Flex Time and Flex Pitch, take folders other than the active comp",
            "sends, buses and output routing, solo, automation, plug-in and instrument settings (each track's "
            "plug-ins are listed by name)",
            "markers: not read from .logicx projects yet",
            "plug-in names are the first readable text of each insert's record: they may be wrong"]
        saved = self.last_saved()
        if not any(v in saved for v in CHECKED_VERSIONS):
            self.warn.append(f"saved by {saved!r}: this reader was checked on packages saved by version "
                             f"{', '.join(CHECKED_VERSIONS)} only; check the session against the original")
        mname = self.meta.get("SongKey")
        name = bundle.stem
        return dict(name=name, source=bundle, daw=f"{saved} (.logicx)", rate=rate, bpm=tpts[0][1],
                    tempo=[], tempo_points=pts, num=num, den=den, markers=[], tracks=tracks,
                    not_carried=self.not_carried, warnings=self.warn, key=mname)

    def notes(self, ev):
        out = []
        for o, t in events(ev.data, _evsize):
            if t != 0x90:
                continue
            d = ev.data
            pos = (_u32(d, o + 4) - TEMPO_ORIGIN) / PPQ
            length = _u32(d, o + 0x1c) / PPQ
            vel, key = d[o + 0x0b], d[o + 0x0c]
            if pos < 0 or not 0 < vel < 128 or key > 127 or length <= 0:
                continue
            out.append((pos, length, key, vel))
        return out

    def file_rate(self, p):
        if p is None or not Path(p).is_file():
            return None
        try:
            import soundfile as sf
            return sf.info(str(p)).samplerate
        except Exception:
            return None

    def last_saved(self):
        try:
            info = plistlib.loads((self.bundle / "Resources" / "ProjectInformation.plist").read_bytes())
            return str(info.get("LastSavedFrom") or "version unknown")
        except (OSError, plistlib.InvalidFileException, ValueError):
            return "version unknown"


def read(path):
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        raise SystemExit(f"{path.name}: a .logicx project is a folder (package)")
    return Reader(path).read()
