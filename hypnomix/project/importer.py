"""The shared half of every project import: a plain project model, and the writer that turns it into a NEW HypnoMix Studio
session folder. Each reader (.ptx, .aaf, .dawproject, .logicx, .rpp) only fills the model; this module
copies the audio, writes the session and the IMPORT-REPORT.md. The Live set importer (als2ardour) keeps its own
reader and writer; this one reuses its parts (audio copying, region and route XML, the tempo map).

The model is plain data:

    project = dict(
        name="Song", source=Path, daw="a .ptx session",          # what was read
        rate=48000 or None,                                  # the session rate (None: what most of the audio uses)
        bpm=120.0, tempo=[(beat, bpm), ...] or [],           # constant tempo segments from these beats on
        tempo_points=[(beat, bpm), ...] (optional instead): straight lines between points, a step = two points
        num=4, den=4,                                        # time signature
        markers=[dict(name=, time=seconds, end=seconds or None)],
        tracks=[dict(
            name=, kind="audio" | "midi" | "bus",
            volume=1.0 (linear gain), pan=0.0 (-1 left .. +1 right), muted=False, solo=False,
            rgba=0xRRGGBBAA or None, group="route group name" or None,
            key="a unique id" (optional; default the name), output="the key of the bus it feeds" or None,
            regions=[dict(name=, file=Path, channels=[0, 1] or None, position=seconds, start=seconds in the file,
                          length=seconds, gain=1.0, muted=False, fade_in=seconds, fade_out=seconds,
                          envelope=[(seconds in the region, gain), ...] or None)],
            midi=[dict(name=, position=beats, length=beats, muted=False,
                       notes=[(beat in the region, length in beats, key, velocity), ...])],
            sends=[dict(bus="the bus track's key", gain=1.0 (linear), pre=False)],
            plugins=["names of the track's plug-ins, as the reader found them"],
            notes=["anything about this track the report should say"])],
        not_carried=["what the reader saw and could not carry"],
        warnings=[],
        roots=[Path, ...],                                   # where the project's own audio may be (see below)
        tempo_assumed=False)                                 # True: the format has no tempo (120 BPM is made up)

What a reader knew it could not carry goes in `not_carried` (or a track's `notes`), and the report lists it, with
what this writer itself had to leave out or change (audio not found, past the end of its file, outside the project,
values out of range). Audio is only taken from inside the project (`roots`) unless the person allows audio from
elsewhere (--allow-outside); what is outside is listed and left out.
"""
import errno
import math
import os
import re
import shutil
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import soundfile as sf

from hypnomix.core import atomic
from hypnomix.project import als2ardour as A

SCPS, TICKS = A.SCPS, A.TICKS

RATES = (8000, 384000)              # a session rate outside this is not a real one: ignored, and the report says so
MAX_TRACKS = 2000                   # budgets: a project past these is refused in one sentence, never half-imported
MAX_REGIONS = 20000                 # audio and MIDI regions together
MAX_NOTES = 500000
NAME_CHARS = 200
NAME_MAX = 255                      # the longest folder or file name NTFS, APFS and ext4 take
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\ufffe\uffff]|[\ud800-\udfff]")   # what XML 1.0 cannot hold
MAX_TEMPO_POINTS = 5000             # tempo points written; more are dropped (the report says so)


class Budget:
    """The import's budgets, counted by a reader while it reads, so an oversized project stops before it is built
    (one sentence, nothing written), not after."""

    def __init__(self, name):
        self.name, self.regions, self.notes, self.tracks = name, 0, 0, 0

    def add(self, regions=0, notes=0, tracks=0):
        self.regions += regions
        self.notes += notes
        self.tracks += tracks
        for what, have, cap in (("tracks", self.tracks, MAX_TRACKS), ("regions", self.regions, MAX_REGIONS),
                                ("MIDI notes", self.notes, MAX_NOTES)):
            if have > cap:
                raise SystemExit(f"{self.name}: has more than {cap} {what}, more than an import carries; nothing was "
                                 f"written")


def clean(s, cap=NAME_CHARS):
    """A name or line as it may be written: no control characters or lone surrogates (they make the session file not
    XML and can forge lines of the report), whitespace flattened to single spaces, at most `cap` characters."""
    s = _CTRL.sub("", str("" if s is None else s))
    return re.sub(r"\s+", " ", s).strip()[:cap]


def _limit(x, lo, hi, default):
    """-> (a finite value in lo..hi, whether it had to change). Not a number, NaN and inf become `default`."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default, x is not None
    if not math.isfinite(v):
        return default, True
    if v < lo:
        return lo, True
    if v > hi:
        return hi, True
    return v, False


def _db_of(g):
    return "-inf dB" if g <= 0 else f"{20 * math.log10(g):+.2f} dB"


CAP_DB = _db_of(2.0)                # +6.02 dB: where the new session's faders stop


def sanitize(p):
    """Make every name and number in the model safe to write, in place: names cleaned (see clean), gains, pans,
    positions, tempo and time signature finite and in range. A fader, send or master above +6 dB (the new session's
    faders stop there) is set to +6 dB with a line saying what it was; every other value that had to change is
    counted in one warning."""
    n = 0

    def lim(x, lo, hi, d):
        nonlocal n
        v, bad = _limit(x, lo, hi, d)
        n += bad
        return v

    def fader(x, what, notes):
        v, bad = _limit(x, 0.0, 1e6, 1.0)
        if v > 2.0:
            notes.append(f"{what} was {_db_of(v)} in the project: set to {CAP_DB}, where the new session's fader stops")
            return 2.0
        nonlocal n
        n += bad
        return v

    split_mixed(p)
    names = {tr.get("key") or tr.get("name"): clean(tr.get("name")) or "Track" for tr in p.get("tracks", [])}
    renamed = 0
    p["name"] = clean(p.get("name")) or "Imported"
    p["daw"] = clean(p.get("daw"), 120) or "a project"
    p["bpm"] = lim(p.get("bpm") or 120.0, 20.0, 999.0, 120.0)
    p["tempo"] = [(lim(b, 0.0, 1e6, 0.0), lim(v, 20.0, 999.0, p["bpm"])) for b, v in (p.get("tempo") or [])]
    if p.get("tempo_points"):
        p["tempo_points"] = [(lim(b, 0.0, 1e6, 0.0), lim(v, 20.0, 999.0, p["bpm"])) for b, v in p["tempo_points"]]
    for k in ("tempo", "tempo_points"):
        if len(p.get(k) or []) > MAX_TEMPO_POINTS:
            p.setdefault("not_carried", []).append(f"the tempo map has {len(p[k])} points: the first "
                                                   f"{MAX_TEMPO_POINTS} are written, the rest are not")
            p[k] = p[k][:MAX_TEMPO_POINTS]
    num = lim(p.get("num") or 4, 1, 64, 4)
    p["num"] = int(num)
    den = p.get("den") or 4
    try:
        den = int(den)
    except (TypeError, ValueError):
        den = 0
    if den not in (1, 2, 4, 8, 16, 32):
        n += 1
        den = 4
    p["den"] = den
    if p.get("rate") is not None:
        try:
            r = int(p["rate"])
        except (TypeError, ValueError):
            r = 0
        if not RATES[0] <= r <= RATES[1]:
            p.setdefault("warnings", []).append(f"the project says its sample rate is {clean(p['rate'], 20)}, which is "
                                                f"not a real one: the session uses what most of the audio uses")
            r = None
        p["rate"] = r
    top = p.setdefault("not_carried", [])
    if "master_volume" in p:
        mv, bad = _limit(p["master_volume"], 0.0, 1e6, 1.0)
        if mv > 2.0:
            top.append(f"the master was {_db_of(mv)} in the project: set to {CAP_DB}, where the new session's fader "
                       f"stops")
            mv = 2.0
        n += bad
        p["master_volume"] = mv
    for m in p.get("markers", []):
        renamed += clean(m.get("name")) != str(m.get("name") or "")
        m["name"] = clean(m.get("name")) or "marker"
        m["time"] = lim(m.get("time"), 0.0, 1e6, 0.0)
        if m.get("end") is not None:
            m["end"] = lim(m["end"], 0.0, 1e6, None)
    for tr in p.get("tracks", []):
        notes = tr.setdefault("notes", [])
        orig = str(tr.get("name") or "")
        tr["name"] = clean(orig) or "Track"
        if orig and tr["name"] != orig:
            notes.append("its name held characters a session cannot hold, line breaks or more than "
                         f"{NAME_CHARS} characters: written as {tr['name']!r}")
        if tr.get("group") is not None:
            tr["group"] = clean(tr["group"]) or None
        tr["plugins"] = [clean(x) for x in tr.get("plugins", []) if clean(x)]
        tr["volume"] = fader(tr.get("volume", 1.0), "its fader", notes)
        tr["pan"] = lim(tr.get("pan", 0.0), -1.0, 1.0, 0.0)
        for s in tr.get("sends", []):
            s["gain"] = fader(s.get("gain", 1.0), f"its send to {names.get(s.get('bus'), clean(s.get('bus')))!r}", notes)
        for r in tr.get("regions", []):
            renamed += clean(r.get("name")) != str(r.get("name") or "")
            r["name"] = clean(r.get("name"))
            r["position"] = lim(r.get("position"), 0.0, 1e6, 0.0)
            r["start"] = lim(r.get("start") or 0.0, 0.0, 1e7, 0.0)
            r["length"] = lim(r.get("length"), 0.0, 1e6, 0.0)
            r["gain"] = lim(r.get("gain", 1.0), 0.0, 4.0, 1.0)
            for k in ("fade_in", "fade_out"):
                r[k] = lim(r.get(k) or 0.0, 0.0, max(0.0, r["length"]), 0.0)
            if r.get("envelope"):
                r["envelope"] = [(lim(a, 0.0, 1e6, 0.0), lim(v, 0.0, 2.0, 1.0)) for a, v in r["envelope"]]
        for m in tr.get("midi", []):
            m["name"] = clean(m.get("name"))
            m["position"] = lim(m.get("position"), 0.0, 1e6, 0.0)
            m["length"] = lim(m.get("length"), 0.0, 1e6, 0.0)
            m["notes"] = [(lim(a, 0.0, 1e6, 0.0), lim(d, 1e-6, 1e6, 0.25), int(lim(k, 0, 127, 60)), lim(v, 1, 127, 100))
                          for a, d, k, v in m.get("notes", [])]
    if n:
        p.setdefault("warnings", []).append(f"{n} value(s) in the project were not numbers, or out of range (gain, "
                                            f"pan, position, tempo or time signature): limited to what a session holds")
    if renamed:
        p.setdefault("warnings", []).append(f"{renamed} region or marker name(s) held characters a session cannot hold, "
                                            f"line breaks or more than {NAME_CHARS} characters: cleaned")
    return p


def split_mixed(p):
    """A track holding both audio regions and MIDI regions becomes two tracks (audio, then "<name> (MIDI)" feeding the
    same place), so neither is dropped; a track with only MIDI regions is a MIDI track."""
    out = []
    for tr in p.get("tracks", []):
        out.append(tr)
        if tr.get("kind") == "bus":
            continue
        regions, midi = tr.get("regions") or [], tr.get("midi") or []
        if midi and not regions:
            tr["kind"] = "midi"
        elif regions and midi:
            tr["kind"] = "audio"
            out.append(dict(name=f"{tr.get('name') or 'Track'} (MIDI)", kind="midi", midi=midi, regions=[],
                            volume=tr.get("volume", 1.0), pan=tr.get("pan", 0.0), muted=tr.get("muted"),
                            solo=tr.get("solo"), output=tr.get("output"), group=tr.get("group"),
                            notes=[f"the MIDI regions of {tr.get('name')!r}, which also holds audio"]))
            tr["midi"] = []
    p["tracks"] = out


def budget(p):
    """Refuse, in one sentence, a project bigger than an import carries (never a half import)."""
    tracks = p.get("tracks", [])
    regions = sum(len(t.get("regions", [])) + len(t.get("midi", [])) for t in tracks)
    notes = sum(len(m.get("notes", [])) for t in tracks for m in t.get("midi", []))
    for what, have, cap in (("tracks", len(tracks), MAX_TRACKS), ("regions", regions, MAX_REGIONS),
                            ("MIDI notes", notes, MAX_NOTES)):
        if have > cap:
            raise SystemExit(f"{Path(p.get('source', 'the project')).name}: has {have} {what}, more than the {cap} an "
                             f"import carries; nothing was written")


def tempo_points(bpm, segments):
    """Constant tempo segments [(beat, bpm)] -> the point list A.Tempo reads (a step is two points at one beat)."""
    segs = sorted(((float(b), float(v)) for b, v in (segments or []) if v and v > 0), key=lambda s: s[0])   # stable
    if not segs or segs[0][0] > 0:
        segs.insert(0, (0.0, float(bpm or 120.0)))
    pts = [segs[0]]
    for b, v in segs[1:]:
        if b <= pts[-1][0]:                      # two tempos at one beat: the later one rules
            pts[-1] = (pts[-1][0], v)
            continue
        pts.append((b, pts[-1][1]))              # hold the tempo up to the change ...
        pts.append((b, v))                       # ... and step there
    return pts


def rgba(r, g, b, a=255):
    return (int(r) & 0xFF) << 24 | (int(g) & 0xFF) << 16 | (int(b) & 0xFF) << 8 | (int(a) & 0xFF)


class Writer(A.Writer):
    """als2ardour's writer with a generic `build`: the route, send, region and tempo-map XML are its own."""

    def __init__(self, project, out, sr, log, name=None):
        pts = project.get("tempo_points") or tempo_points(project.get("bpm"), project.get("tempo"))
        song = dict(project, tempo=A.Tempo(project.get("bpm") or 120.0, pts),
                    num=int(project.get("num") or 4), den=int(project.get("den") or 4))
        super().__init__(song, out, sr, log, name=name)
        self.project = project
        self.made = dict(regions=0, midi=0, notes=0, missing=[], resampled=[], outside=[])
        roots = project.get("roots") or []
        self.roots = [Path(r).resolve() for r in roots]
        self.roots_text = [Path(os.path.normpath(os.path.abspath(str(r)))) for r in roots] + self.roots
        self.allow_outside = bool(project.get("allow_outside"))

    def _outside(self, x):
        """Is this file outside the project? Decided from the path's text first, so a path elsewhere (a network share,
        another drive) is never touched; then, for a path inside, after following links. Never when no roots are
        known, or when audio from outside is allowed."""
        if not self.roots or self.allow_outside:
            return False
        text = Path(os.path.normpath(os.path.abspath(str(x))))
        if not any(text == r or r in text.parents for r in self.roots_text):
            return True
        try:
            rp = Path(x).resolve()
        except (OSError, RuntimeError):
            return True
        return not any(rp == r or r in rp.parents for r in self.roots)

    def key_name(self, key):
        """A track's key (what `output` and a send's `bus` hold) -> its name, for the report."""
        for tr in self.project.get("tracks", []):
            if (tr.get("key") or tr.get("name")) == key:
                return tr.get("name")
        return "a track that is not in the project"

    def _route_colour(self, rt, tr):
        if tr.get("rgba") is not None:
            pi = rt.find("PresentationInfo")
            if pi is not None:
                pi.set("color", str(int(tr["rgba"]) & 0xFFFFFFFF))

    def _audio(self, tr, playlist, sources_el, regions_el, srcs):
        made = 0
        for r in tr.get("regions", []):
            self.at = f"track {tr['name']!r}, region {r.get('name', '')!r}"
            paths = [Path(x) if x else None for x in (r.get("files") or [r.get("file")])]
            where = f"{tr['name']} / {r.get('name') or 'region'}"
            out = [x for x in paths if x is not None and self._outside(x)]     # before any file is touched
            if out:
                self.made["outside"].append(f"{where}: " + ", ".join(clean(x.name) for x in out))
                continue
            bad = [x for x in paths if x is None or not x.is_file()]
            if bad:
                self.made["missing"].append(f"{where}: " + ", ".join(clean(x.name) if x else "no file" for x in bad))
                continue
            path = paths[0]
            names, src_len, ok = [], None, True
            per_file = r.get("file_channels") or [None] * len(paths)
            for x, fc in zip(paths, per_file):                # one file per channel (a .ptx stereo pair's .L / .R, AAF)
                got = srcs.add(x)
                if got is None:
                    ok = False
                    break
                names += [got[0][fc]] if fc is not None and 0 <= fc < len(got[0]) else got[0]
                src_len = got[1] if src_len is None else min(src_len, got[1])
            if not ok:
                self.made["missing"].append(f"{where}: its audio could not be copied (see the warnings)")
                continue
            chans = r.get("channels")
            if chans:
                picked = [names[c] for c in chans if 0 <= c < len(names)]
                names = picked or names
            length = float(r["length"])
            start = max(0.0, float(r.get("start") or 0.0))
            if start >= src_len - 1e-6:
                self.made["missing"].append(f"{where}: starts {start:.2f} s into {clean(path.name)}, which is only "
                                            f"{src_len:.2f} s long; left out")
                continue
            if start + length > src_len + 1e-3:
                tr.setdefault("notes", []).append(f"region {r.get('name') or path.stem!r} ran {start + length - src_len:.2f} "
                                                  f"s past the end of {clean(path.name)}: shortened to the file")
                length = src_len - start
            if length <= 0:
                self.made["missing"].append(f"{where}: zero length; left out")
                continue
            sids = self.source_ids(names, sources_el, regions_el, src_len)
            env = r.get("envelope")
            env = [(max(0.0, min(length, t)), max(0.0, min(2.0, v))) for t, v in env] if env else None
            self.region(playlist, r.get("name") or path.stem, sids, float(r["position"]), length, start,
                        float(r.get("gain", 1.0)), bool(r.get("muted")), float(r.get("fade_in") or 0.0),
                        float(r.get("fade_out") or 0.0), env)
            tr.setdefault("notes", []).extend(r.get("notes") or [])     # lines about a region, only once it is placed
            made += 1
        return made

    def _midi(self, tr, playlist, sources_el, midi_dir):
        made = 0
        for k, m in enumerate(tr.get("midi", [])):
            self.at = f"track {tr['name']!r}, MIDI region {k + 1}"
            s, L = float(m["position"]), float(m["length"])
            if L <= 0:
                self.made["missing"].append(f"{tr['name']} / MIDI region {k + 1}: zero length; left out")
                continue
            stem = A.short_stem(re.sub(r'[^\w ().-]', '-', tr['ardour_name']).strip() or "MIDI")
            fn, i = f"{stem} (imported {k + 1}).mid", 2
            while fn.lower() in self.midi_names:
                fn, i = f"{stem} (imported {k + 1}) {i}.mid", i + 1
            self.midi_names.add(fn.lower())
            A.write_smf(midi_dir / fn, m.get("notes", []), L)
            sid = self.ids()
            A.sub(sources_el, "Source", name=fn, take_id="", type="midi", flags="Writable,CanRename", id=sid, origin="")
            rg = A.sub(playlist, "Region", name=m.get("name") or tr["name"], muted=int(bool(m.get("muted"))), opaque=0,
                       locked=0, video_locked=0, automatic=0, whole_file=0, external=0, sync_marked=0, left_of_split=0,
                       right_of_split=0, hidden=0, position_locked=0, valid_transients=0, start="b0",
                       length=f"b{int(round(L * TICKS))}@b{int(round(s * TICKS))}", sync_position="b0",
                       ancestral_start="b0", ancestral_length="b0@b0", stretch=1, shift=1, layering_index=self.layer,
                       tags="", contents=0, rgroup=0, id=self.ids(), type="midi", first_edit="nothing")
            rg.set("source-0", sid)
            rg.set("master-source-0", sid)
            self.layer += 1
            self.made["notes"] += len(m.get("notes", []))
            made += 1
        return made

    def build(self):
        p, out = self.project, self.out
        audio_dir = out / "interchange" / self.name / "audiofiles"
        midi_dir = out / "interchange" / self.name / "midifiles"
        for d in (audio_dir, midi_dir, out / "analysis", out / "dead", out / "export", out / "externals",
                  out / "peaks", out / "plugins"):
            d.mkdir(parents=True, exist_ok=True)
        warn = p.setdefault("warnings", [])
        srcs = A.Sources(audio_dir, self.sr, warn)
        self.src_ids, self.midi_names, self.layer = {}, set(), 0

        root = ET.Element("Session")
        root.attrib = {"version": "7004", "sample-rate": str(self.sr), "name": self.name,
                       "uuid": str(uuid.uuid4()), "session-range-is-free": "1"}
        A.sub(root, "ProgramVersion", created_with=f"hypnomix import ({p.get('daw', 'project')})",
              modified_with="hypnomix import")
        cfg = A.sub(root, "Config")
        A.sub(cfg, "Option", name="use-region-fades", value=1)
        A.sub(cfg, "Option", name="native-file-header-format", value="WAVE")
        A.sub(root, "Metadata")
        sources_el = A.sub(root, "Sources")
        regions_el = A.sub(root, "Regions")
        locations = A.sub(root, "Locations")
        A.sub(root, "Bundles")
        A.sub(root, "VCAManager")
        routes = A.sub(root, "Routes")
        playlists = A.sub(root, "Playlists")
        A.sub(root, "UnusedPlaylists")
        groups_el = A.sub(root, "RouteGroups")

        tracks = [dict(t) for t in p.get("tracks", [])]
        used, nxt = {"master"}, {}
        for tr in tracks:
            base = A.legal(tr.get("name") or "Track")
            n, i = base, nxt.get(base.lower(), 2)
            while n.lower() in used:                          # a counter per name: many tracks of one name stay fast
                n, i = f"{base} {i}", i + 1
            nxt[base.lower()] = i
            used.add(n.lower())
            tr["ardour_name"] = n
            if n != tr.get("name"):
                tr["notes"] = list(tr.get("notes", [])) + [f"named {n!r} in the new session (its rule for track names)"]
            tr.setdefault("kind", "audio")
            tr.setdefault("volume", 1.0)
            tr.setdefault("pan", 0.0)
            tr["muted"], tr["solo"] = bool(tr.get("muted")), bool(tr.get("solo"))
            tr["auto"], tr["aux"], tr["colour"] = {}, [], None
            tr["rid"] = self.ids()
        self.tracks = tracks
        buses = {}
        for tr in tracks:                                     # by key: two buses of one name stay two buses
            if tr["kind"] == "bus":
                buses.setdefault(tr.get("key") or tr["name"], tr)

        master = dict(name="Master", ardour_name="Master", colour=None, rid=self.ids(), volume=float(p.get("master_volume", 1.0)),
                      pan=0.0, muted=False, solo=False, auto={}, aux=[], inputs={0: [], 1: []})
        ins = {}
        out_of = {}
        for tr in tracks:
            tr["rid"] = tr.get("rid") or self.ids()
            if tr["kind"] == "midi":
                out_of[tr["ardour_name"]] = None     # no instrument is carried: nothing to feed yet
                continue
            dest = buses.get(tr.get("output")) if tr.get("output") else None
            if dest is tr:
                dest = None
            if tr.get("output") and dest is None:
                tr.setdefault("notes", []).append(f"its output went to {self.key_name(tr['output'])!r}, which is not "
                                                  f"a bus here: it feeds the master")
            to = dest["ardour_name"] if dest else "Master"
            out_of[tr["ardour_name"]] = to
            box = master["inputs"] if dest is None else ins.setdefault(to, {0: [], 1: []})
            box[0].append(f"{tr['ardour_name']}/audio_out 1")
            box[1].append(f"{tr['ardour_name']}/audio_out 2")
        for tr in tracks:
            if tr["kind"] == "bus":
                tr["inputs"] = ins.get(tr["ardour_name"], {0: [], 1: []})
        slot = 0
        for tr in tracks:                                     # aux sends to buses
            for s in tr.get("sends", []):
                b = buses.get(s.get("bus"))
                if b is None or b is tr or tr["kind"] == "midi":
                    if b is None:
                        tr.setdefault("notes", []).append(f"a send to {self.key_name(s.get('bus'))!r}, which is not "
                                                          f"a bus here: not carried")
                    continue
                slot += 1
                tr["aux"].append(dict(value=float(s.get("gain", 1.0)), pre=bool(s.get("pre")), auto=None,
                                      target_id=b["rid"], target_name=b["ardour_name"], bitslot=slot))

        groups = {}
        for tr in tracks:
            if tr.get("group"):
                groups.setdefault(tr["group"], []).append(tr)
        group_names = {}
        for gname, members in groups.items():
            n = A.legal(gname)
            group_names[gname] = n
            for tr in members:
                tr["route_group"] = n

        self.route(routes, master, "master", 0, None)
        for order, tr in enumerate(tracks, 1):
            self.at = f"track {tr['name']!r}"
            kind = tr["kind"]
            if kind in ("audio", "midi"):
                tr["playlist_id"] = self.ids()
            rt = self.route(routes, tr, kind, order, out_of.get(tr["ardour_name"]))
            self._route_colour(rt, tr)
            if kind in ("audio", "midi"):
                pl = A.sub(playlists, "Playlist", id=tr["playlist_id"], name=f"{tr['ardour_name']}.1", type=kind,
                           orig_track_id=tr["rid"], pgroup_id="", shared_with_ids="", frozen=0, combine_ops=0)
                if kind == "audio":
                    tr["made"] = self._audio(tr, pl, sources_el, regions_el, srcs)
                    self.made["regions"] += tr["made"]
                else:
                    tr["made"] = self._midi(tr, pl, sources_el, midi_dir)
                    self.made["midi"] += tr["made"]

        for gname, members in groups.items():
            A.sub(groups_el, "RouteGroup", id=self.ids(), rgba=0, used_to_share_gain=0, name=group_names[gname],
                  relative=1, active=1, hidden=0, gain=0, mute=0, solo=0, recenable=1, select=1, route_active=1,
                  color=0, monitoring=1, group_master_number=-1,
                  routes=" ".join(t["rid"] for t in members) + " ").set("sursend_enable", "1")

        end = 0.0
        for rg in playlists.iter("Region"):
            L, at = rg.get("length").split("@")
            if L.startswith("a"):
                end = max(end, (int(L[1:]) + int(at[1:])) / SCPS)
            else:
                end = max(end, self.tempo.seconds((int(L[1:]) + int(at[1:])) / TICKS))
        for m in p.get("markers", []):
            t = max(0.0, float(m["time"]))
            e = m.get("end")
            if e is not None and float(e) > t:
                A.sub(locations, "Location", id=self.ids(), name=m.get("name") or "marker", start=A.a(t), end=A.a(float(e)),
                      flags="IsRangeMarker", locked=0, timestamp=0, cue=0)
            else:
                A.sub(locations, "Location", id=self.ids(), name=m.get("name") or "marker", start=A.a(t), end=A.a(t),
                      flags="IsMark", locked=0, timestamp=0, cue=0)
            end = max(end, t)
        A.sub(locations, "Location", id=self.ids(), name="session", start="a0", end=A.a(max(end, 1.0)),
              flags="IsSessionRange", locked=0, timestamp=0, cue=0)
        self.tempo_map(root)
        root.set("id-counter", str(self.ids.n + 1))
        root.set("name-counter", "1")
        root.set("event-counter", "0")
        root.set("vca-counter", "1")
        f = out / f"{self.name}.ardour"
        atomic.write_text(f, '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n",
                          backup=False)
        return f


def session_rate(project, override=None):
    """--sr, else the project's own rate (sanitize has dropped one that is not real), else what most audio uses."""
    if override:
        return int(override)
    if project.get("rate") and RATES[0] <= int(project["rate"]) <= RATES[1]:
        return int(project["rate"])
    rates = {}
    roots = [os.path.normpath(os.path.abspath(str(x))) for x in project.get("roots") or []]

    def inside(f):                                            # from the text only: a file elsewhere is not opened
        a = os.path.normpath(os.path.abspath(str(f)))
        return project.get("allow_outside") or not roots or any(a == r or a.startswith(r.rstrip(os.sep) + os.sep)
                                                                 for r in roots)
    for t in project.get("tracks", []):
        for r in t.get("regions", []):
            if not r.get("file") or not inside(r["file"]):
                continue
            try:
                rr = sf.info(str(r["file"])).samplerate
            except Exception:
                continue
            if RATES[0] <= rr <= RATES[1]:
                rates[rr] = rates.get(rr, 0) + 1
    return max(rates, key=rates.get) if rates else 48000


def _db(g):
    return "-inf" if g <= 0 else f"{20 * math.log10(g):+.1f} dB"


def _cell(s, cap=80):
    """Text for a cell of the report's table: one line, no table or code marks."""
    return clean(s, cap).replace("|", "\\|").replace("`", "'") or "-"


def _line(s):
    """One bullet of the report: one line (a name cannot start a heading or a list of its own)."""
    return clean(s, 600).replace("`", "'")


NOT_CHECKED = [
    "It has not been opened in a released DAW yet.",
    "Pan law: the new session's stereo panner and the source DAW's can differ off-centre (centred tracks are the same).",
    "If you hear nothing when it opens, connect the Master to your outputs once and save.",
    "MIDI tracks carry their notes but no instrument: load one.",
]


def report_md(project, w, f, sr):
    p = project
    changes = len(w.tempo.steps) + len(w.tempo.ramps)
    if p.get("tempo_assumed"):
        tempo = f"{p.get('bpm') or 120:g} BPM, {p.get('num', 4)}/{p.get('den', 4)} (assumed: this format has no tempo)"
    else:
        tempo = (f"{p.get('bpm') or 120:g} BPM" + (f", {changes} tempo change(s)" if changes else "")
                 + f"; time signature {p.get('num', 4)}/{p.get('den', 4)}")
    L = [f"# Import report: {_line(p.get('name', ''))}", "",
         f"- From: {_line(p.get('daw', 'a project'))} - '{_line(Path(p['source']).name)}' (only read, never changed)",
         f"- To: '{_line(f.name)}' at {sr} Hz",
         f"- Tempo: {tempo}",
         f"- Carried: {len(w.tracks)} track(s), {w.made['regions']} audio region(s), {w.made['midi']} MIDI region(s) "
         f"({w.made['notes']} notes), {len(p.get('markers', []))} marker(s)", ""]
    L += ["## Tracks", "", "| Track | Kind | Fader | Pan | Mute | Solo | Regions | Plug-ins (not carried) |",
          "|---|---|---|---|---|---|---|---|"]
    for t in w.tracks:
        pan = t.get("pan", 0.0)
        L.append(f"| {_cell(t['name'])} | {t['kind']} | {_db(t.get('volume', 1.0))} | "
                 f"{'C' if abs(pan) < 1e-3 else (f'{-pan * 100:.0f}L' if pan < 0 else f'{pan * 100:.0f}R')} | "
                 f"{'yes' if t['muted'] else ''} | {'yes' if t['solo'] else ''} | {t.get('made', 0)} | "
                 f"{_cell(', '.join(t.get('plugins', [])), 300)} |")
    L.append("")
    if w.made["missing"]:
        L += ["## Left out: audio not found or not usable", ""] + [f"- {_line(m)}" for m in w.made["missing"]] + [""]
    if w.made["outside"]:
        L += ["## Left out: audio from outside the project", "",
              "These files are not inside the project, so they were not copied in. To bring them in, import again "
              "with 'Also copy audio from outside the project' ticked (the app), or with --allow-outside "
              "(hypnomix import):", ""] + [f"- {_line(m)}" for m in w.made["outside"]] + [""]
    elif p.get("allow_outside") and w.roots:
        L += ["- Audio from outside the project was allowed (--allow-outside).", ""]
    notes = [f"{t['name']}: {n}" for t in w.tracks for n in t.get("notes", [])]
    if notes:
        L += ["## Track notes", ""] + [f"- {_line(n)}" for n in notes] + [""]
    if p.get("not_carried"):
        L += ["## Not carried", ""] + [f"- {_line(n)}" for n in p["not_carried"]] + [""]
    if p.get("warnings"):
        L += ["## Warnings", ""] + [f"- {_line(n)}" for n in p["warnings"]] + [""]
    rb = getattr(w, "readback", None)
    L += ["## Not checked", ""]
    if rb:
        L += [f"- Read back by HypnoMix's own session reader after writing: {rb[0]} track(s) and {rb[1]} region(s), as "
              f"written."]
    L += [f"- {n}" for n in NOT_CHECKED] + [""]
    L += ["Plug-ins and instruments are listed by name where the file type has them: add your own in the new session.",
          ""]
    return "\n".join(L)


def read_back(f, w):
    """Read the written session with HypnoMix's own session reader and check it holds what was written: the tracks
    and the regions. A session that does not read back is never left behind. -> (tracks, regions)."""
    from hypnomix.project import ardour
    try:
        rb = ardour.read(f)
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        raise SystemExit(f"the written session could not be read back ({type(e).__name__}: {e}); nothing was kept") from e
    tracks = [t for t in rb.tracks if t.name != "Master"]
    regions = sum(len(t.clips) for t in tracks)
    want = w.made["regions"] + w.made["midi"]
    if len(tracks) < len(w.tracks) or regions < want:
        raise SystemExit(f"the written session reads back with {len(tracks)} track(s) and {regions} region(s), not "
                         f"{len(w.tracks)} and {want}; nothing was kept")
    return len(tracks), regions


def check_out(out, guard, sr=None):
    """The checks made before anything is read or unpacked: the sample rate, and the new folder (not a file, empty,
    not inside the project). -> the resolved folder."""
    if sr is not None and not RATES[0] <= int(sr) <= RATES[1]:
        raise SystemExit(f"--sr {sr}: the sample rate must be between {RATES[0]} and {RATES[1]} Hz (for example 48000)")
    too_long = next((part for part in Path(out).parts if len(part) > NAME_MAX), None)
    if too_long is not None:      # by length first: Windows answers a too-long name with "invalid name" or not at all
        raise SystemExit(         # until the folder is made; macOS and Linux say "name too long" (caught below too)
            f"the new session's folder cannot be used (a name in it is longer than {NAME_MAX} characters: "
            f"{too_long[:24]}...): choose a shorter name or another place")
    try:
        out = Path(out).expanduser().resolve()
        if out.exists() and not out.is_dir():
            raise SystemExit(f"{out}: is a file, not a folder (choose a new folder)")
        if out.exists() and any(out.iterdir()):
            raise SystemExit(f"{out}: already exists and is not empty (choose a new folder)")
    except OSError as e:
        raise SystemExit(f"the new session's folder cannot be used ({e.strerror or e}): choose a shorter name or "
                         f"another place") from e
    if guard is not None:
        guard = Path(guard).expanduser().resolve()
        if out == guard or guard in out.parents:
            raise SystemExit(f"{out}: inside the project being imported; write the new session somewhere else")
    return out


def convert(project, out, sr=None, log=print, guard=None):
    """Write `project` (the model above) as a new session at `out`: built in a hidden folder and moved into place at
    the end, so a failure leaves nothing behind. `guard` is the source project's folder, which `out` must not be in.
    Returns (the .ardour file, the report file, the Writer)."""
    src = Path(project["source"]).expanduser().resolve()
    out = check_out(out, guard or (src if src.is_dir() else src.parent), sr)
    sanitize(project)
    budget(project)
    rate = session_rate(project, sr)
    existed = out.exists()
    made = []
    try:
        if existed:
            tmp = out / f".hypnomix-tmp-{os.getpid()}"
        else:
            up = out.parent
            while not up.exists():
                made.append(up)
                up = up.parent
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.parent / f".{out.name}.tmp-{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
    except OSError as e:
        A._remove_empty(made)
        raise SystemExit(f"{out}: cannot be created here ({e.strerror or e}); choose a folder you can write to") from e
    w = Writer(project, tmp, rate, log, name=out.name)
    try:
        f_tmp = w.build()
        w.readback = read_back(f_tmp, w)
        atomic.write_text(tmp / "IMPORT-REPORT.md", report_md(project, w, out / f_tmp.name, rate), backup=False)
        if existed:
            A._move_up(tmp, out)
        else:
            os.replace(tmp, out)
    except BaseException as e:
        shutil.rmtree(tmp, ignore_errors=True)
        A._remove_empty(made)
        if isinstance(e, (SystemExit, KeyboardInterrupt)):
            raise
        why = "the disk is full" if isinstance(e, OSError) and e.errno == errno.ENOSPC else f"{type(e).__name__}: {e}"
        raise SystemExit(f"{src.name}: could not be imported ({w.at or 'reading the project'}): {why}. Nothing was "
                         f"written: {out} {'is as it was (empty)' if existed else 'was not created'}, so you can run "
                         f"it again.") from e
    return out / f_tmp.name, out / "IMPORT-REPORT.md", w
