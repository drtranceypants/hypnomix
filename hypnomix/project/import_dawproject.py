"""Read a DAWproject file (.dawproject) into the import model (hypnomix.project.importer).

DAWproject is the open project format (published under the MIT licence) that several DAWs save and open (look for
File > Export > DAWproject, or Save As). It is
a zip: project.xml plus the audio. Read here:

  tracks      name, order, colour, fader, pan, mute, solo; folder and group tracks with a channel of their own become
              buses their tracks feed; effect (return) channels become buses fed by sends at their level (pre/post)
  clips       audio clips (position, length, start in the file, fades, switched off -> muted, loops unrolled) and MIDI
              clips with their notes (loops unrolled); clips inside clips are flattened
  warps       audio whose warp markers make one straight line at the project's own speed is placed exactly; other
              warped audio is placed from its first warp marker unstretched, and the report lists it
  tempo       the tempo, time signature and tempo automation (held and straight-line tempo changes); markers
  devices     listed per track by name (their settings are not carried); the master's are listed too
"""
import zipfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

from hypnomix.project import als2ardour as A

MAX_XML = 32 * 1024 * 1024      # project.xml unpacked
MAX_ELEMENTS = 2_000_000        # elements in project.xml
MAX_UNROLL = 256                # passes of one looped clip
MIN_PASS = 0.05                 # a loop shorter than this (s) is placed once, not unrolled
MAX_DEPTH = 32                  # clips inside clips
MAX_CLIPS = 50_000              # clips in the whole project
MAX_MEDIA = 8 << 30             # one audio file inside the zip (a bigger one is left out, with a line)
MAX_MEDIA_TOTAL = 64 << 30      # all the audio unpacked from one project, and at most 40% of the free disk
MAX_RATIO = 200                 # an entry that unpacks to more than 200x its packed size ...
RATIO_FLOOR = 16 << 20          # ... and past 16 MB is left out (digital silence; the rest imports); and the same
#                                 ratio over all the entries unpacked so far (many small silent files)


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _b(x, d=False):
    return d if x is None else str(x).lower() in ("true", "1")


def _colour(c):
    try:
        c = c.lstrip("#")
        if len(c) >= 6:
            return int(c[:6], 16) << 8 | 0xFF
    except (AttributeError, ValueError):
        pass
    return None


def _gain(el):
    """A Volume / send level (RealParameter) as a linear gain."""
    if el is None:
        return 1.0
    v, unit = _f(el.get("value"), 1.0), (el.get("unit") or "linear")
    if unit == "decibel":
        return 10 ** (v / 20.0)
    if unit == "normalized":                      # 0..1 of min..max (linear)
        lo, hi = _f(el.get("min"), 0.0), _f(el.get("max"), 2.0)
        return lo + v * (hi - lo)
    return v


def _pan(el):
    if el is None:
        return 0.0
    v, unit = _f(el.get("value"), 0.5), (el.get("unit") or "normalized")
    if unit == "normalized":
        return max(-1.0, min(1.0, v * 2 - 1))
    if unit == "percent":
        return max(-1.0, min(1.0, v / 100.0))
    lo, hi = _f(el.get("min"), -1.0), _f(el.get("max"), 1.0)
    return max(-1.0, min(1.0, (v - lo) / (hi - lo) * 2 - 1)) if hi > lo else 0.0


def devices(ch):
    out = []
    d = ch.find("Devices") if ch is not None else None
    for dev in (list(d) if d is not None else []):
        name = dev.get("deviceName") or dev.get("name") or dev.tag
        kind = {"Vst3Plugin": "VST3", "Vst2Plugin": "VST2", "ClapPlugin": "CLAP", "AuPlugin": "AU"}.get(dev.tag)
        out.append(f"{name} ({kind})" if kind else name)
    return out


class Reader:
    def __init__(self, path, media):
        from hypnomix.project.importer import Budget
        self.path, self.media = path, media
        self.not_carried, self.warped = [], []
        self.budget = Budget(path.name)
        self.skipped = {}
        self.packed = 0

    def skip(self, what, n=1):
        """Count something left out; the report gets one line per kind (see read)."""
        self.skipped[what] = self.skipped.get(what, 0) + n

    def open(self):
        try:
            self.zip = zipfile.ZipFile(self.path)
        except (zipfile.BadZipFile, OSError) as e:
            raise SystemExit(f"{self.path.name}: not a DAWproject file (it is not a zip: {e})") from e
        try:
            info = self.zip.getinfo("project.xml")
        except KeyError as e:
            raise SystemExit(f"{self.path.name}: not a DAWproject file (no project.xml inside)") from e
        if info.file_size > MAX_XML:
            raise SystemExit(f"{self.path.name}: project.xml is too big to read ({info.file_size // 2**20} MB)")
        with self.zip.open(info) as fh:                       # the size in the zip's header can lie: cap the read
            raw = fh.read(MAX_XML + 1)
        if len(raw) > MAX_XML:
            raise SystemExit(f"{self.path.name}: project.xml unpacks to more than {MAX_XML >> 20} MB")
        try:                                                  # a DTD or entities are refused inside the parser
            self.root = A.parse_xml(raw, MAX_ELEMENTS)        # (any encoding), and so are too many elements
        except A.XMLRefused as e:
            raise SystemExit(f"{self.path.name}: project.xml is refused: {e}") from e
        except ET.ParseError as e:
            raise SystemExit(f"{self.path.name}: project.xml is damaged ({e})") from e
        self.unpacked, self.nclips = 0, 0
        import shutil
        try:
            free = shutil.disk_usage(self.media).free
        except OSError:
            free = MAX_MEDIA_TOTAL
        self.media_budget = min(MAX_MEDIA_TOTAL, int(free * 0.4))

    def file(self, el):
        """A FileReference -> a real path (files inside the zip are extracted into the media folder)."""
        if el is None or not el.get("path"):
            return None
        p = el.get("path")
        if _b(el.get("external")):                  # a file outside the zip (the writer only takes it from inside
            q = Path(p)                             # the project's folder, unless audio from outside is allowed)
            return q if q.is_absolute() else (self.path.parent / q)
        name = zip_name(p)
        if name is None:
            self.not_carried.append(f"a file inside the project with a name that is not a plain zip path "
                                    f"({A.legal(p)[:80]!r}): left out")
            return None
        dest = self.media / name
        if dest.resolve() != self.media.resolve() and self.media.resolve() not in dest.resolve().parents:
            return None
        if dest.exists():
            return dest
        try:
            info = self.zip.getinfo(name)
        except KeyError:
            return dest                             # not in the zip: a path that is not there, named in the report
        shown = A.legal(name)[:80]
        if info.file_size > MAX_MEDIA:
            self.not_carried.append(f"{shown}: unpacks to more than {MAX_MEDIA >> 30} GB; left out")
            return None
        if info.file_size > RATIO_FLOOR and info.file_size > MAX_RATIO * max(1, info.compress_size):
            self.not_carried.append(f"{shown}: unpacks to {info.file_size // max(1, info.compress_size)}x its packed "
                                    f"size (digital silence, or not real audio); left out")
            return None
        total_after = self.unpacked + info.file_size
        if total_after > RATIO_FLOOR and total_after > MAX_RATIO * max(1, self.packed + info.compress_size):
            self.not_carried.append(f"{shown}: the audio unpacked so far is more than {MAX_RATIO}x its packed size "
                                    f"(digital silence, or not real audio); left out")
            return None
        if total_after > self.media_budget:
            self.not_carried.append(f"{shown}: the project's audio would unpack to more than "
                                    f"{self.media_budget / 2**30:.1f} GB (the disk's room for it); left out")
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        try:
            with self.zip.open(info) as src, open(dest, "wb") as out:
                first = True
                while True:
                    blk = src.read(1 << 20)
                    if not blk:
                        break
                    total += len(blk)
                    if total > info.file_size or total > MAX_MEDIA:     # the zip's header lied: stop at its word
                        raise ValueError("more than its zip entry says")
                    out.write(blk)
                    if first:                           # not audio: stop before unpacking the rest
                        out.flush()
                        first = False
                        if A.audio_container(dest) is None:
                            raise ValueError("not an audio file")
        except ValueError as e:
            dest.unlink(missing_ok=True)
            self.not_carried.append(f"{shown}: inside the project but {e}; left out")
            return None
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        self.unpacked += total
        self.packed += info.compress_size
        return dest

    # ---- time
    def secs_after(self, x, u, at):
        """`x` in unit `u` from beat `at` on -> seconds (a length or an offset inside a clip, at the clip's tempo)."""
        return x if u == "seconds" else self.tempo.seconds(at + x) - self.tempo.seconds(at)

    def beats_after(self, x, u, at):
        """`x` in unit `u` from beat `at` on -> beats."""
        return x if u == "beats" else self.beats(self.tempo.seconds(at) + x, "seconds") - at

    def secs(self, t, unit):
        return self.tempo.seconds(t) if unit == "beats" else t

    def beats(self, t, unit):
        if unit == "beats":
            return t
        lo, hi = 0.0, max(1.0, t * 8)                 # seconds -> beats on the tempo map
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if self.tempo.seconds(mid) < t else (lo, mid)
        return (lo + hi) / 2

    # ---- read
    def read(self):
        self.open()
        r = self.root
        app = r.find("Application")
        daw = f"{app.get('name')} {app.get('version') or ''}".strip() if app is not None else "DAWproject"
        tr = r.find("Transport")
        bpm = _f(tr.find("Tempo").get("value"), 120.0) if tr is not None and tr.find("Tempo") is not None else 120.0
        ts = tr.find("TimeSignature") if tr is not None else None
        num, den = (int(_f(ts.get("numerator"), 4)), int(_f(ts.get("denominator"), 4))) if ts is not None else (4, 4)
        arr = r.find("Arrangement")
        pts = self.tempo_points(arr, bpm)
        self.tempo = A.Tempo(bpm, pts)
        if arr is not None and arr.find("TimeSignatureAutomation") is not None and \
                len(arr.find("TimeSignatureAutomation").findall("TimeSignaturePoint")) > 1:
            self.not_carried.append("time signature changes (the first one is used)")

        # structure: tracks, channels, buses
        self.tracks, self.by_track, self.by_channel = [], {}, {}
        master = None
        st = r.find("Structure")
        for el in (list(st) if st is not None else []):
            if el.tag == "Track":
                self.track(el, None)
            elif el.tag == "Channel":
                if el.get("role") == "master" and master is None:
                    master = el
                else:
                    self.channel_bus(el, el.get("name") or "Bus")
        for t in self.tracks:
            if t["el"].find("Channel") is not None and t["el"].find("Channel").get("role") == "master" and master is None:
                master = t["el"].find("Channel")
        self.tracks = [t for t in self.tracks if t["channel_el"] is not master]
        master_id = master.get("id") if master is not None else None
        for t in self.tracks:
            ch = t["channel_el"]
            dest = ch.get("destination") if ch is not None else None
            if dest and dest != master_id and dest in self.by_channel and self.by_channel[dest] is not t:
                t["output"] = self.by_channel[dest]["key"]
            elif t.get("parent") is not None and t["parent"]["kind"] == "bus" and not dest:
                t["output"] = t["parent"]["key"]
            for s in (ch.findall("Sends/Send") if ch is not None else []):
                b = self.by_channel.get(s.get("destination"))
                en = s.find("Enable")
                if en is not None and not _b(en.get("value"), True):
                    self.skip("switched-off send(s)")
                    continue
                if b is None or b is t:
                    self.skip("send(s) to a channel that is not a bus here")
                    continue
                t.setdefault("sends", []).append(dict(bus=b["key"], gain=_gain(s.find("Volume")),
                                                      pre=s.get("type") == "pre"))

        if arr is not None and arr.find("Lanes") is not None:
            self.lanes(arr.find("Lanes"), "beats", None)
        markers = []
        if arr is not None:
            mk = arr.find("Markers")
            unit = (mk.get("timeUnit") if mk is not None else None) or "beats"
            for m in (mk.findall("Marker") if mk is not None else []):
                markers.append(dict(name=m.get("name") or "marker", time=self.secs(_f(m.get("time")), unit)))
        if r.find("Scenes") is not None and len(r.find("Scenes")):
            self.not_carried.append(f"{len(r.find('Scenes'))} scene(s) of clip slots (only the arrangement is carried)")
        for w in self.warped:
            self.not_carried.append(w)
        for what, n in self.skipped.items():
            self.not_carried.append(f"{n} {what}: not carried")
        if master is not None and devices(master):
            self.not_carried.append("the master's devices: " + ", ".join(devices(master)))
        self.not_carried += ["plug-in and instrument settings (each track's devices are listed)",
                             "automation other than tempo (fader, pan, plug-in parameters, MIDI controllers)"]
        out = []
        for t in self.tracks:
            t.pop("el", None)
            t.pop("channel_el", None)
            t.pop("parent", None)
            if t["kind"] == "bus" or t["regions"] or t["midi"] or t["kind"] in ("audio", "midi"):
                out.append(t)
        mv = _gain(master.find("Volume")) if master is not None else 1.0
        return dict(name=self.path.stem, source=self.path, daw=f"{daw} (DAWproject)", rate=None, bpm=bpm, tempo=[],
                    tempo_points=pts, num=num, den=den, markers=markers, tracks=out, not_carried=self.not_carried,
                    warnings=[], master_volume=mv, media_dir=self.media)

    def tempo_points(self, arr, bpm):
        ta = arr.find("TempoAutomation") if arr is not None else None
        if ta is None:
            return [(0.0, bpm)]
        unit = ta.get("timeUnit") or "beats"
        raw = sorted(((_f(p.get("time")), _f(p.get("value"), bpm), p.get("interpolation") or "hold")
                      for p in ta.findall("RealPoint")), key=lambda x: x[0])
        if unit == "seconds":                       # seconds on a map we are making: walk it at the held tempos
            beat, out, last_t, last_v = 0.0, [], 0.0, bpm
            for t, v, i in raw:
                beat += (t - last_t) * last_v / 60.0
                out.append((beat, v, i))
                last_t, last_v = t, v
            raw = out
        pts = []
        for k, (b, v, interp) in enumerate(raw):
            if not pts:
                pts.append((max(0.0, b), v))
                continue
            prev_interp = raw[k - 1][2]
            if prev_interp == "linear":
                pts.append((b, v))                       # a straight line from the last point
            else:
                pts.append((b, pts[-1][1]))              # hold, then step
                pts.append((b, v))
        if not pts:
            pts = [(0.0, bpm)]
        if pts[0][0] > 0:
            pts.insert(0, (0.0, pts[0][1]))
        return pts

    def channel_bus(self, ch, name):
        self.budget.add(tracks=1)
        t = dict(name=name, kind="bus", volume=_gain(ch.find("Volume")), pan=_pan(ch.find("Pan")),
                 muted=_b(ch.find("Mute").get("value")) if ch.find("Mute") is not None else False,
                 solo=_b(ch.get("solo")), regions=[], midi=[], notes=[], plugins=devices(ch), el=ch, channel_el=ch,
                 key=f"k{len(self.tracks)}")
        self.tracks.append(t)
        if ch.get("id"):
            self.by_channel[ch.get("id")] = t
        return t

    def track(self, el, parent):
        ch = el.find("Channel")
        kinds = (el.get("contentType") or "").replace(",", " ").split()
        name = el.get("name") or "Track"
        if kinds and set(kinds) <= {"video"}:                # a video track: nothing of it is carried
            self.skip("video track(s)")
            return dict(kind="video")
        if "tracks" in kinds or (ch is not None and ch.get("role") in ("submix", "effect")):
            kind = "bus"
        elif "notes" in kinds:
            kind = "midi"
        else:
            kind = "audio"
        self.budget.add(tracks=1)
        t = dict(name=name, kind=kind, rgba=_colour(el.get("color")), regions=[], midi=[], notes=[],
                 plugins=devices(ch), el=el, channel_el=ch, parent=parent, key=f"k{len(self.tracks)}-{id(el)}")
        if ch is not None:
            t.update(volume=_gain(ch.find("Volume")), pan=_pan(ch.find("Pan")), solo=_b(ch.get("solo")),
                     muted=_b(ch.find("Mute").get("value")) if ch.find("Mute") is not None else False)
            if ch.get("role") == "vca":
                t["notes"].append("a VCA in the source: made a bus here; its control of other faders is not carried")
            if ch.get("id"):
                self.by_channel[ch.get("id")] = t
        if kind == "bus" and ch is None:                  # a folder that does nothing to the sound: no bus
            t["kind"] = "folder"
        self.tracks.append(t)
        if el.get("id"):
            self.by_track[el.get("id")] = t
        for kid in el.findall("Track"):
            k = self.track(kid, t if t["kind"] == "bus" else parent)
            if t["kind"] == "folder" and k.get("kind") != "video":
                k["group"] = name
        if t["kind"] == "folder":
            self.tracks.remove(t)
        return t

    def lanes(self, el, unit, track):
        unit = el.get("timeUnit") or unit
        if el.get("track") and el.get("track") not in self.by_track:
            self.skip("clip(s) on a track that is not in the project (or a video track)", len(el.findall(".//Clip")))
            return
        track = self.by_track.get(el.get("track"), track)
        for kid in el:
            if kid.tag == "Lanes":
                self.lanes(kid, unit, track)
            elif kid.tag == "Clips" and track is None:
                self.skip("clip(s) on a track that is not in the project (or a video track)", len(kid.findall("Clip")))
            elif kid.tag == "Clips" and track is not None:
                cu = kid.get("timeUnit") or unit              # a timeline may name its own unit
                for c in kid.findall("Clip"):
                    self.clip(c, cu, track, 0.0, 0.0, None)
            elif kid.tag == "Points" and track is not None:
                tgt = kid.find("Target")
                what = tgt.get("expression") or "a parameter" if tgt is not None else "a parameter"
                note = f"automation of {what} (not carried)"
                if note not in track["notes"]:
                    track["notes"].append(note)

    def clip(self, c, unit, track, offset, content0, window, muted=False, depth=0):
        """One Clip. `offset`: where (in `unit`) the parent's content timeline sits; `window`: the parent's visible
        part [start, end) of that timeline in `unit`, or None; `muted`: a clip around it is switched off."""
        self.nclips += 1
        if self.nclips > MAX_CLIPS:
            raise SystemExit(f"{self.path.name}: has more than {MAX_CLIPS} clips, more than an import carries")
        if depth > MAX_DEPTH:
            raise SystemExit(f"{self.path.name}: clips nested more than {MAX_DEPTH} deep")
        t0 = _f(c.get("time"))
        cu = c.get("contentTimeUnit") or unit
        ps = _f(c.get("playStart"), 0.0)
        dur = c.get("duration")
        dur = _f(dur) if dur is not None else max(0.0, _f(c.get("playStop"), ps) - ps)
        start, end = offset + t0 - content0, offset + t0 - content0 + dur
        if window is not None:
            start, end = max(start, window[0]), min(end, window[1])
        if end <= start:
            self.skip("clip(s) of zero length, or wholly outside the clip around them")
            return
        name = c.get("name") or ""
        muted = muted or not _b(c.get("enable"), True)
        fu = c.get("fadeTimeUnit") or unit
        fade_in, fade_out = _f(c.get("fadeInTime")), _f(c.get("fadeOutTime"))
        ls, le = c.get("loopStart"), c.get("loopEnd")
        loop = (_f(ls), _f(le)) if ls is not None and le is not None and _f(le) > _f(ls) else None
        for content in c:
            if content.tag in ("Clips",):
                # inner clips sit on this clip's content timeline; the visible part is this clip's window
                if cu != unit:
                    self.warped.append(f"{track['name']} / {name or 'clip'}: clips inside a clip on another time "
                                       f"unit: placed approximately")
                for inner in content.findall("Clip"):
                    self.clip(inner, content.get("timeUnit") or unit, track, start - (ps if cu == unit else 0.0), 0.0,
                              (start, end), muted, depth + 1)
            elif content.tag == "Notes":
                self.notes(content, track, start, end, unit, cu, ps, loop, name, muted)
            elif content.tag in ("Audio", "Warps"):
                self.audio(content, track, start, end, unit, cu, ps, loop, name, muted,
                           self.secs_len(fade_in, fu, start, unit), self.secs_len(fade_out, fu, end, unit, back=True))
            elif content.tag not in ("Clips", "Notes", "Audio", "Warps", "Lanes"):
                self.skip(f"clip(s) holding {content.tag} content (not audio or notes)")
            elif content.tag == "Lanes":                 # only this clip's own lanes: never a walk of every clip below
                for sub, su in self.lane_clips(content, unit):
                    self.clip(sub, su, track, start - ps, 0.0, (start, end), muted, depth + 1)

    def lane_clips(self, el, unit, depth=0):
        """The Clip elements of a Lanes inside a clip ([Lanes/]Clips/Clip), with their time unit."""
        if depth > MAX_DEPTH:
            raise SystemExit(f"{self.path.name}: lanes nested more than {MAX_DEPTH} deep")
        unit = el.get("timeUnit") or unit
        for kid in el:
            if kid.tag == "Lanes":
                yield from self.lane_clips(kid, unit, depth + 1)
            elif kid.tag == "Clips":
                for c in kid.findall("Clip"):
                    yield c, kid.get("timeUnit") or unit

    def secs_len(self, L, u, at, unit, back=False):
        if L <= 0:
            return 0.0
        if u == "seconds":
            return L
        a = self.beats(self.secs(at, unit), "seconds")
        return abs(self.tempo.seconds(a + (-L if back else L)) - self.tempo.seconds(a))

    def passes(self, start, end, ps, loop, short=None):
        """The pieces of a clip's visible part: [(timeline start, timeline end, content start)]. Everything is on one
        scale (seconds for audio, beats for notes): the callers convert first. A loop shorter than `short` is
        played once (the report says so)."""
        if loop is None:
            return [(start, end, ps)]
        ls, le = loop
        if short is not None and le - ls < short:
            self.not_carried.append("a looped clip shorter than 50 ms: placed once, not repeated")
            return [(start, min(end, start + max(0.0, le - ps)), ps)]
        out, t, c = [], start, ps
        while t < end - 1e-9 and len(out) < MAX_UNROLL:
            if c >= le:
                c = ls + (c - le) % (le - ls)
            piece = min(end - t, le - c)
            out.append((t, t + piece, c))
            t, c = t + piece, ls
        if t < end - 1e-9:
            self.not_carried.append(f"a looped clip with more than {MAX_UNROLL} passes: only the first {MAX_UNROLL} are "
                                    f"placed")
        return out

    def notes(self, el, track, start, end, unit, cu, ps, loop, name, muted):
        """MIDI notes, all in beats: the clip's place on its timeline, and the loop and the notes on its content
        timeline (in the content's own unit, converted at the clip's place)."""
        sb, eb = self.beats(self.secs(start, unit), "seconds"), self.beats(self.secs(end, unit), "seconds")
        nu = el.get("timeUnit") or cu
        cb = lambda x, u: self.beats_after(x, u, sb)               # noqa: E731  content -> beats from the clip
        notes = []
        for n in el.findall("Note"):
            t, d = _f(n.get("time")), _f(n.get("duration"))
            tb = cb(t, nu)
            notes.append((tb, cb(t + d, nu) - tb, int(_f(n.get("key"))), _f(n.get("vel"), 0.8)))
        loop_b = (cb(loop[0], cu), cb(loop[1], cu)) if loop else None
        out = []
        self.budget.add(regions=1)
        for a, b, c in self.passes(sb, eb, cb(ps, cu), loop_b, short=1e-3):
            before = len(out)
            for t, d, k, v in notes:
                if c <= t < c + (b - a):
                    out.append((a - sb + t - c, min(d, (b - a) - (t - c)), k, v * 127 if v <= 1.0 else v))
            self.budget.add(notes=len(out) - before)            # counted pass by pass: stops before it grows
        track["midi"].append(dict(name=name or track["name"], position=sb, length=eb - sb, notes=out, muted=muted))

    def audio(self, el, track, start, end, unit, cu, ps, loop, name, muted, fade_in, fade_out):
        """Audio, all in seconds: the clip's place, its content (playStart, loop, warps) converted at the clip's
        place, so a tempo change before the clip changes nothing inside it."""
        audio = el if el.tag == "Audio" else el.find("Audio")
        f = self.file(audio.find("File")) if audio is not None else None
        sa, se = self.secs(start, unit), self.secs(end, unit)
        at = self.beats(sa, "seconds")
        cs = lambda x, u: self.secs_after(x, u, at)                # noqa: E731  content -> seconds from the clip
        to_file = lambda c: c                                      # noqa: E731  content seconds -> seconds in the file
        if el.tag == "Warps":
            warps = sorted(((_f(w.get("time")), _f(w.get("contentTime"))) for w in el.findall("Warp")))
            wu, wcu = el.get("timeUnit") or cu, el.get("contentTimeUnit") or "seconds"
            if len(warps) >= 2:
                xs = [cs(t, wu) for t, _ in warps]
                ys = [cs(ct, wcu) for _, ct in warps]
                k = (ys[-1] - ys[0]) / (xs[-1] - xs[0]) if xs[-1] > xs[0] else 1.0
                bent = any(abs((ys[i] - ys[0]) - k * (xs[i] - xs[0])) > 0.002 for i in range(len(xs)))
                if bent:
                    self.warped.append(f"{track['name']} / {name or (f.name if f else 'clip')}: warp markers that bend "
                                       f"the timing: placed along the straight line from its first to last marker")
                elif abs(k - 1.0) > 1e-4:
                    self.warped.append(f"{track['name']} / {name or (f.name if f else 'clip')}: plays at x{k:.4f} "
                                       f"speed in the source: placed at its own speed (re-stretch it here)")
                x0, y0 = xs[0], ys[0]
                to_file = lambda c: y0 + (c - x0) * k               # noqa: E731
            cu = wu
        loop_s = (cs(loop[0], cu), cs(loop[1], cu)) if loop else None
        pieces = self.passes(sa, se, cs(ps, cu), loop_s, short=MIN_PASS)
        self.budget.add(regions=len(pieces))                    # counted before they are built
        for a, b, c in pieces:
            track["regions"].append(dict(name=name or (f.stem if f else "clip"), file=f, position=a,
                                         start=max(0.0, to_file(c)), length=b - a, muted=muted,
                                         fade_in=fade_in if a == sa else 0.0, fade_out=fade_out if b == se else 0.0))


def zip_name(p):
    """A FileReference path inside the zip -> the zip member name, or None when it is not a plain relative zip path
    (a drive, a backslash, a root, '.', '..' or an empty part): on Windows such a name would escape the folder."""
    if not p or "\\" in p or ":" in p:
        return None
    parts = PurePosixPath(p.lstrip("/")).parts
    if not parts or any(x in ("", ".", "..") for x in parts):
        return None
    return "/".join(parts)


def read(path, media_dir=None):
    path = Path(path).expanduser().resolve()
    media = Path(media_dir) if media_dir else Path(tempfile.mkdtemp(prefix="hypnomix-dawproject-"))
    media.mkdir(parents=True, exist_ok=True)
    return Reader(path, media).read()
