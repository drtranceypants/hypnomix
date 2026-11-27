"""MPE (per-note pitch bend, pressure and slide) in a HypnoMix DAW session: what is there, and what may go wrong.

MPE gives every sounding note its own MIDI channel, so each note can bend, be pressed and slid on its own. A zone is
one global channel and up to 15 member channels (lower zone: global channel 1, members from 2 up; upper zone: global
16, members from 15 down). Here channels are numbered 0 to 15, as in the bytes: channel 1 is 0.

What is read, read only:

  track     the MIDI track's <MPE zone= members= member-bend-range= global-bend-range=/> (absent while MPE is off)
            and its playback / capture channel modes (AllChannels, FilterChannels, ForceChannel) and masks
  source    each MIDI source the track's regions play: its .mid file (a small strict reader below, standard library
            only) and the source's <InterpolationStyle parameter= style=/> children (bend, channel pressure and
            CC 74 lists are Linear, that is gliding between points, unless the session says Discrete)

`checks(p)` turns those facts into scan findings (tool "mpe"); `write_discrete` is the one change, used by the fix
flow on a parsed session that is then saved as a new snapshot (never the original).
"""
from pathlib import Path

MAX_BYTES = 32 * 1024 * 1024
MAX_EVENTS = 2_000_000
START_MS = 6.0                  # a first note this close to the clip start is at risk (the record-start window)
CENTRE = 8192                   # pitch bend at rest
PINNED = 8180                   # a bend this far from the centre sits at the end of its range
KINDS = ("bend", "pressure", "slide")


# ---------------------------------------------------------------- the .mid reader
class Smf:
    def __init__(self, fmt, ppq, events):
        self.fmt, self.ppq, self.events = fmt, ppq, events    # events: (tick, kind, channel, a, b), in file order


def _varlen(b, i, end):
    v = 0
    for k in range(4):
        if i >= end:
            raise ValueError("the MIDI file is cut off in the middle of a number")
        c = b[i]
        i += 1
        v = (v << 7) | (c & 0x7F)
        if not c & 0x80:
            return v, i
    raise ValueError("the MIDI file has a number longer than four bytes, which the format does not allow")


def read_smf(src):
    """A standard MIDI file (format 0, 1 or 2) from a path or bytes -> Smf. Every track's channel events merged by
    tick (ties keep file order). Raises ValueError, in one sentence, on a file that is too big, cut off or not MIDI."""
    if isinstance(src, (bytes, bytearray)):
        b = bytes(src)
    else:
        path = Path(src)
        if path.stat().st_size > MAX_BYTES:
            raise ValueError(f"{path.name} is larger than {MAX_BYTES // (1024 * 1024)} MB, so it is not read")
        b = path.read_bytes()
    if len(b) > MAX_BYTES:
        raise ValueError(f"the MIDI file is larger than {MAX_BYTES // (1024 * 1024)} MB, so it is not read")
    if len(b) < 14 or b[:4] != b"MThd":
        raise ValueError("this is not a standard MIDI file (it does not start with MThd)")
    hlen = int.from_bytes(b[4:8], "big")
    if hlen < 6 or 8 + hlen > len(b):
        raise ValueError("the MIDI file's header is cut off")
    fmt, ntrk, div = (int.from_bytes(b[8 + 2 * k:10 + 2 * k], "big") for k in range(3))
    if fmt > 2:
        raise ValueError(f"the MIDI file says it is format {fmt}; only formats 0, 1 and 2 exist")
    if div & 0x8000 or div == 0:
        raise ValueError("the MIDI file counts time in SMPTE frames, which is not read here")
    i, merged, n, tracks = 8 + hlen, [], 0, 0
    while i < len(b) and tracks < ntrk:
        if i + 8 > len(b):
            raise ValueError("the MIDI file is cut off in a chunk header")
        tag, clen = b[i:i + 4], int.from_bytes(b[i + 4:i + 8], "big")
        start, end = i + 8, i + 8 + clen
        if end > len(b):
            raise ValueError("the MIDI file is cut off inside a track")
        i = end
        if tag != b"MTrk":
            continue                                       # an unknown chunk: the format says skip it
        tracks += 1
        j, tick, status = start, 0, 0
        while j < end:
            dt, j = _varlen(b, j, end)
            tick += dt
            if j >= end:
                raise ValueError("the MIDI file is cut off after a time step")
            c = b[j]
            if c == 0xFF:
                if j + 2 > end:
                    raise ValueError("the MIDI file is cut off in a meta event")
                typ = b[j + 1]
                ln, j = _varlen(b, j + 2, end)
                if j + ln > end:
                    raise ValueError("the MIDI file is cut off in a meta event")
                if typ == 0x51 and ln == 3:
                    merged.append((tick, tracks, n, "tempo", -1, int.from_bytes(b[j:j + 3], "big"), 0))
                j += ln
                if typ == 0x2F:
                    break
                status = 0
            elif c in (0xF0, 0xF7):
                ln, j = _varlen(b, j + 1, end)
                if j + ln > end:
                    raise ValueError("the MIDI file is cut off in a system exclusive message")
                j += ln
                merged.append((tick, tracks, n, "sysex", -1, 0, 0))
                status = 0
            else:
                if c & 0x80:
                    if c >= 0xF0:
                        raise ValueError(f"the MIDI file has a system message (0x{c:02X}) a file may not hold")
                    status, j = c, j + 1
                elif not status:
                    raise ValueError("the MIDI file has a data byte with no status before it")
                hi, ch = status & 0xF0, status & 0x0F
                size = 1 if hi in (0xC0, 0xD0) else 2
                if j + size > end:
                    raise ValueError("the MIDI file is cut off in a channel message")
                d = b[j:j + size]
                if any(x & 0x80 for x in d):
                    raise ValueError("the MIDI file has a status byte where a data byte belongs")
                j += size
                a, v = d[0], (d[1] if size == 2 else 0)
                if hi == 0x90 and v == 0:
                    hi = 0x80
                kind = {0x80: "off", 0x90: "on", 0xA0: "poly", 0xB0: "cc", 0xC0: "program", 0xD0: "pressure",
                        0xE0: "bend"}[hi]
                if kind == "bend":
                    a, v = a | (v << 7), 0
                merged.append((tick, tracks, n, kind, ch, a, v))
            n += 1
            if n > MAX_EVENTS:
                raise ValueError(f"the MIDI file holds more than {MAX_EVENTS:,} events, so it is not read")
    merged.sort(key=lambda e: (e[0], e[2]))
    return Smf(fmt, div, [(t, k, ch, a, v) for t, _, _, k, ch, a, v in merged])


# ---------------------------------------------------------------- what a clip holds
class Facts:
    """Per channel: notes, bend, pressure, slide (CC 74), poly pressure, the RPN 0 (bend range) and RPN 6 (the MPE
    configuration message) values the file sets."""

    def __init__(self, smf):
        self.smf = smf
        self.count = {k: [0] * 16 for k in ("notes", "bend", "pressure", "slide", "poly")}
        self.rpn0 = {}           # channel -> semitones (the last RPN 0 the file sets on that channel)
        self.rpn6 = {}           # channel -> members (an MPE configuration message)
        self.poly_keys = set()   # (channel, key) with poly pressure
        rpn = {}
        for t, k, ch, a, v in smf.events:
            if k == "on":
                self.count["notes"][ch] += 1
            elif k == "bend":
                self.count["bend"][ch] += 1
            elif k == "pressure":
                self.count["pressure"][ch] += 1
            elif k == "poly":
                self.count["poly"][ch] += 1
                self.poly_keys.add((ch, a))
            elif k == "cc":
                if a == 74:
                    self.count["slide"][ch] += 1
                elif a in (100, 101):
                    lsb, msb = rpn.get(ch, (127, 127))
                    rpn[ch] = (v, msb) if a == 100 else (lsb, v)
                elif a == 6 and rpn.get(ch, (127, 127))[1] == 0:
                    if rpn[ch][0] == 0:
                        self.rpn0[ch] = v
                    elif rpn[ch][0] == 6:
                        self.rpn6[ch] = v

    def note_channels(self):
        return [c for c in range(16) if self.count["notes"][c]]

    def expressive(self, ch):
        return any(self.count[k][ch] for k in ("bend", "pressure", "slide"))


def looks_like_mpe(src):
    """True when a clip reads like MPE: notes on three or more channels, and per-channel bend, pressure or CC 74 on
    at least three of those channels. `src` is a path, bytes, an Smf or Facts."""
    f = src if isinstance(src, Facts) else Facts(src if isinstance(src, Smf) else read_smf(src))
    chans = f.note_channels()
    return len(chans) >= 3 and sum(1 for c in chans if f.expressive(c)) >= 3


# ---------------------------------------------------------------- the session side
def track_mpe(rt):
    """A route's MPE setting -> dict(zone, members, member_bend, global_bend) or None while MPE is off."""
    el = rt.find("MPE")
    if el is None:
        return None
    zone = el.get("zone", "lower")
    if zone not in ("lower", "upper"):
        return None

    def n(key, default, lo, hi):
        try:
            return max(lo, min(hi, int(el.get(key, default))))
        except (TypeError, ValueError):
            return default
    return dict(zone=zone, members=n("members", 15, 1, 15), member_bend=n("member-bend-range", 48, 0, 96),
                global_bend=n("global-bend-range", 2, 0, 96))


def _mask(v):
    try:
        return int(str(v), 0) & 0xFFFF
    except (TypeError, ValueError):
        return 0xFFFF


def channel_modes(rt):
    """[(which, mode, mask)] for playback and capture (mode AllChannels, FilterChannels or ForceChannel)."""
    out = []
    for which in ("playback", "capture"):
        mode = rt.get(f"{which}-channel-mode") or (rt.get("channel-mode") if which == "playback" else None) or "AllChannels"
        mask = _mask(rt.get(f"{which}-channel-mask") or (rt.get("channel-mask") if which == "playback" else None) or "0xffff")
        out.append((which, mode, mask))
    return out


def members_of(zone, members):
    """Member channels (0-based): lower zone from channel 1 (the second) up; upper from 14 (the fifteenth) down."""
    return list(range(1, 1 + members)) if zone == "lower" else list(range(14, 14 - members, -1))


def midi_file(session_dir, name):
    session_dir = Path(session_dir)
    if not name:
        return None
    if Path(name).is_absolute():
        return Path(name)
    inter = session_dir / "interchange"
    for d in (sorted(inter.iterdir()) if inter.is_dir() else []):
        if (d / "midifiles" / name).is_file():
            return d / "midifiles" / name
    return None


INTERP = (("bend", "midi-pitch-bender-{c}"), ("pressure", "midi-channel-pressure-{c}"), ("slide", "midicc-{c}-74"))


def styles(src_el):
    """A MIDI <Source>'s interpolation styles: {parameter: style}."""
    return {s.get("parameter"): s.get("style") for s in src_el.findall("InterpolationStyle") if s.get("parameter")}


def glide_params(src_el, facts, channels=range(16)):
    """The bend, pressure and CC 74 lists on these channels that hold data and are not Discrete (they glide)."""
    st = styles(src_el)
    return [pat.format(c=c) for c in channels for kind, pat in INTERP
            if facts.count[kind][c] and st.get(pat.format(c=c)) != "Discrete"]


def discrete_params(facts):
    """What the glide fix writes: bend, channel pressure and CC 74 for all 16 channels, and a per-note pressure list
    for every key that has poly pressure."""
    return [pat.format(c=c) for c in range(16) for _, pat in INTERP] + \
        [f"midi-note-pressure-{c}-{k}" for c, k in sorted(facts.poly_keys)]


def write_discrete(root, source_id, params):
    """Set Discrete interpolation for these parameters on every MIDI <Source> with this id. -> how many set."""
    n = 0
    for s in root.iter("Source"):
        if s.get("id") != source_id or s.get("type") != "midi":
            continue
        have = {e.get("parameter"): e for e in s.findall("InterpolationStyle")}
        kids = list(s)
        at = max((kids.index(e) for e in have.values()), default=-1) + 1
        for prm in params:
            e = have.get(prm)
            if e is not None:
                if e.get("style") != "Discrete":
                    e.set("style", "Discrete")
                    n += 1
                continue
            e = s.makeelement("InterpolationStyle", {"parameter": prm, "style": "Discrete"})
            s.insert(at, e)
            at += 1
            have[prm] = e
            n += 1
    return n


def is_mpe_param(prm):
    return (prm or "").startswith(("midi-pitch-bender-", "midi-channel-pressure-", "midi-note-pressure-")) or \
        ((prm or "").startswith("midicc-") and prm.endswith("-74"))


def strip_mpe_styles(root):
    """Remove the styles the glide fix may change (used by the structure check on copies of both files)."""
    for s in root.iter("Source"):
        if s.get("type") == "midi":
            for e in [e for e in s.findall("InterpolationStyle") if is_mpe_param(e.get("parameter"))]:
                s.remove(e)


def style_changes(a_root, b_root):
    """[one line per MIDI source] whose bend / pressure / slide interpolation changed between two sessions."""
    out = []
    before = {s.get("id"): (s.get("name"), styles(s)) for s in a_root.iter("Source") if s.get("type") == "midi"}
    for s in b_root.iter("Source"):
        if s.get("type") != "midi" or s.get("id") not in before:
            continue
        name, old = before.pop(s.get("id"))
        new = styles(s)
        moved = [k for k in new if is_mpe_param(k) and new[k] != old.get(k)]
        if moved:
            out.append(f"{name}: {len(moved)} bend, pressure and slide lists set to Discrete (no gliding between points)"
                       if all(new[k] == "Discrete" for k in moved) else f"{name}: {len(moved)} interpolation styles changed")
    return out


# ---------------------------------------------------------------- the checks
def _sec(smf, tick, bpm):
    return tick / smf.ppq * 60.0 / (bpm or 120.0)


def _clip_checks(smf, facts, zone, members, member_bend, bend_from):
    """-> [(kind, severity, problem, fix, first tick or None)] for one clip."""
    out = []
    mem = set(members_of(zone, members))
    glob = 0 if zone == "lower" else 15
    # (b) more notes at once than member channels
    on, most, at = set(), 0, None
    for t, k, ch, a, v in smf.events:
        if k == "on" and ch != glob:
            on.add((ch, a))
            if len(on) > most:
                most, at = len(on), t
        elif k == "off":
            on.discard((ch, a))
    if most > members:
        out.append(("too-many-notes", "medium",
                    f"up to {most} notes sound at once, more than the zone's {members} member channels: a receiver "
                    "set to this zone has to share a channel between two notes, so one note's bend and pressure move "
                    "the other too",
                    f"set the controller and the instrument to more member channels (up to 15), or play fewer notes at "
                    "once here", at))
    # (c) bend at the end of the declared range
    pinned = {}
    for t, k, ch, a, v in smf.events:
        if k == "bend" and ch in mem and abs(a - CENTRE) >= PINNED:
            pinned.setdefault(ch, t)
    if pinned and member_bend is not None:
        chans = sorted(pinned)
        out.append(("bend-range", "low",
                    f"pitch bend reaches the very end of the {member_bend}-semitone range ({bend_from}) on "
                    f"{len(chans)} channel(s) (first on channel {chans[0] + 1}): the player probably bent further "
                    "than that range, so those notes stop short of the pitch the finger reached",
                    f"if the controller sends a wider range, set the same bend range on the controller and the "
                    "instrument (48 is the MPE default for member channels), then play it again", min(pinned.values())))
    # (d) not back to neutral, and (e) no initial value before a note
    last = {c: {} for c in range(16)}      # channel -> kind -> value
    since_off = {c: set() for c in range(16)}
    sounding = {c: 0 for c in range(16)}
    seen_off = {c: False for c in range(16)}
    stale, bare = [], []
    for t, k, ch, a, v in smf.events:
        if ch not in mem:
            continue
        if k in ("bend", "pressure") or (k == "cc" and a == 74):
            kind = "slide" if k == "cc" else k
            last[ch][kind] = a if k in ("bend", "pressure") else v
            since_off[ch].add(kind)
        elif k == "on":
            if not last[ch]:
                bare.append(t)
            elif seen_off[ch] and not sounding[ch]:
                left = [kind for kind, val in last[ch].items() if kind not in since_off[ch] and
                        val != {"bend": CENTRE, "pressure": 0, "slide": 64}[kind]]
                if left:
                    stale.append((t, ch, left))
            sounding[ch] += 1
        elif k == "off":
            sounding[ch] = max(0, sounding[ch] - 1)
            if not sounding[ch]:
                seen_off[ch] = True
                since_off[ch] = set()
    if stale:
        kinds = sorted({x for _, _, ks in stale for x in ks})
        out.append(("not-neutral", "low",
                    f"{len(stale)} note(s) start with the {' and '.join(kinds)} the note before left on its channel "
                    f"(first on channel {stale[0][1] + 1}): nothing set it back to neutral after the note-off, so the "
                    "new note starts bent, pressed or slid",
                    "send bend back to centre and pressure to 0 after each note-off (most MPE controllers do this; "
                    "check the controller's settings), or draw the reset in by hand before the next note", stale[0][0]))
    if bare:
        out.append(("no-initial-value", "low",
                    f"{len(bare)} note(s) start with no bend, pressure or slide value set on their channel before "
                    "them in the clip, so each plays with whatever the instrument last had on that channel",
                    "let the controller send its initial values before each note (the MPE way), or draw a centred "
                    "bend just before the first note on each channel", bare[0]))
    return out


def checks(p, words=None):
    """Scan findings for a HypnoMix DAW session's MIDI tracks: [finding dict], [note]. Reads only."""
    findings, notes, n = [], [], 0
    if getattr(p, "daw", None) != "ardour" or p.native is None:
        return [], ["mpe: MPE checks are for HypnoMix DAW sessions (.ardour) only"]
    root = p.native
    src_el = {}
    for s in root.iter("Source"):
        if s.get("type") == "midi" and s.get("id") not in src_el:
            src_el[s.get("id")] = s
    session_dir = Path(p.path).parent
    cache, missing, bad, looked = {}, set(), [], 0

    def add(**kw):
        nonlocal n
        n += 1
        kw.setdefault("applies", "manual")
        kw.setdefault("where", "")
        findings.append(dict(id=f"mpe-{n}", tool="mpe", **kw))

    for t in p.tracks:
        if t.kind != "midi" or t.native is None:
            continue
        cfg = track_mpe(t.native)
        modes = channel_modes(t.native)
        for c in t.clips:
            rg = c.native
            sid = rg.get("source-0") if rg is not None else None
            s = src_el.get(sid)
            if s is None:
                continue
            if sid not in cache:
                path = midi_file(session_dir, s.get("name", ""))
                if path is None or not path.is_file():
                    missing.add(s.get("name", ""))
                    cache[sid] = None
                else:
                    try:
                        smf = read_smf(path)
                        cache[sid] = (smf, Facts(smf))
                    except (OSError, ValueError) as e:
                        bad.append(f"{s.get('name', '')}: {e}")
                        cache[sid] = None
            if cache[sid] is None:
                continue
            looked += 1
            smf, facts = cache[sid]
            mpe_like = looks_like_mpe(facts)
            if not (mpe_like or cfg):
                continue
            where = p.where(c.start) if hasattr(p, "where") else ""
            name = s.get("name", "")
            used = facts.note_channels()

            def at(tick):
                return f"{p.where(c.start + max(0.0, _sec(smf, tick, p.tempo) - c.take.offset))}" if tick is not None \
                    and c.take is not None and hasattr(p, "where") else where
            # (a) MPE off, or a channel mode that merges or drops channels
            for which, mode, mask in modes:
                if mode == "ForceChannel" and len(used) > 1:
                    add(kind="channels-forced", severity="high", track=t.name, where=where, clip=name,
                        problem=f"the track's {which} channel mode forces every note onto one channel, but this clip "
                                f"has notes on {len(used)} channels: per-note bend, pressure and slide get merged",
                        fix=f"set the track's {which} channel mode back to all channels")
                elif mode == "FilterChannels" and any(not mask & (1 << ch) for ch in used):
                    dropped = [ch + 1 for ch in used if not mask & (1 << ch)]
                    add(kind="channels-filtered", severity="high", track=t.name, where=where, clip=name,
                        problem=f"the track's {which} channel filter drops channel(s) "
                                f"{', '.join(map(str, dropped[:8]))}{'...' if len(dropped) > 8 else ''}, which this clip "
                                "plays notes on: those notes are not heard",
                        fix=f"set the track's {which} channel mode back to all channels")
            if mpe_like and not cfg:
                add(kind="mpe-off", severity="low", track=t.name, where=where, clip=name,
                    problem=f"this clip looks like MPE (notes on {len(used)} channels, each with its own bend, "
                            "pressure or slide) but the track's MPE mode is off, so nothing tells the instrument to "
                            "treat each channel as one note",
                    fix="switch the instrument to MPE mode by hand (lower zone, 15 members and a member bend range "
                        "of 48 unless the controller says otherwise). HypnoMix DAW's track MPE setting has passed "
                        "its automated tests but has not yet been tried with real MPE controllers")
            zone = cfg["zone"] if cfg else ("upper" if 15 in facts.rpn6 and 0 not in facts.rpn6 else "lower")
            glob = 0 if zone == "lower" else 15
            members = cfg["members"] if cfg else (facts.rpn6.get(glob) or 15)
            mem = members_of(zone, members)
            rpn0 = [facts.rpn0[ch] for ch in mem if ch in facts.rpn0]
            if rpn0:
                member_bend, bend_from = max(rpn0), "from the RPN 0 the clip sends on its member channels"
            elif cfg:
                member_bend, bend_from = cfg["member_bend"], "from the track's MPE setting"
            else:
                member_bend, bend_from = None, ""
            for kind, sev, problem, fix, tick in _clip_checks(smf, facts, zone, members, member_bend, bend_from):
                add(kind=kind, severity=sev, track=t.name, where=at(tick), clip=name, problem=problem, fix=fix)
            # (f) the very start of the clip
            first_on = next((e[0] for e in smf.events if e[1] == "on"), None)
            at0 = sum(1 for e in smf.events if e[0] == 0 and e[1] not in ("tempo", "sysex"))
            early = first_on is not None and _sec(smf, first_on, p.tempo) * 1000 <= START_MS
            if at0 or early:
                bits = ([f"{at0} event(s) sit at exactly tick 0"] if at0 else []) + \
                    ([f"the first note starts {_sec(smf, first_on, p.tempo) * 1000:.1f} ms into the clip"] if early else [])
                add(kind="clip-start", severity="low", track=t.name, where=where, clip=name,
                    problem=" and ".join(bits) + ": on the engine as tested, values at the very start of a clip could "
                            "be lost when it was saved again, and the first few milliseconds of a recording are "
                            "skipped, so a note's initial bend, pressure or slide is at risk (other engines may keep "
                            "them)",
                    fix="leave a little room before the first note: move the clip's notes and values a few "
                        "milliseconds later, or start the clip earlier with empty space at its start")
            # (g) gliding lists on member channels
            gl = glide_params(s, facts, [glob] + mem)
            if gl:
                add(kind="glide", severity="medium", track=t.name, where=where, clip=name, applies="set",
                    edit=dict(op="mpe-discrete", source=sid, name=name, params=discrete_params(facts)),
                    problem=f"{len(gl)} bend, pressure or slide list(s) in this clip's source are stored with linear "
                            "interpolation, so between two stored points the value glides: a held note with one bend "
                            "at its start and a reset after its end is played back as a slow ramp",
                    fix="approve to write Discrete interpolation (each value holds until the next) for bend, channel "
                        "pressure and CC 74 on all 16 channels of this source, into a new snapshot beside the "
                        "original; the notes and values themselves are not changed")
    notes.append(f"mpe: {looked} MIDI clip(s) read; {len(findings)} MPE finding(s). Read from the session file and the "
                 "MIDI files only: nothing was played or listened to")
    if missing:
        notes.append(f"mpe: {len(missing)} MIDI file(s) not found, so not checked: " + ", ".join(sorted(missing)[:6]))
    notes += [f"mpe: not read: {b}" for b in bad[:6]]
    return findings, notes
