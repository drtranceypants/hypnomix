"""HypnoMix: a mixing and mastering engineer for Ableton Live, REAPER and HypnoMix DAW, driven by you or by Claude Code.

Run `hypnomix` for the command list, `hypnomix <command> -h` for each command's help.
"""
import errno
import importlib
import os
import sys

GROUPS = [
    ("Engineer: stems in, song out", [
        ("automix", "hypnomix.engineer.automix", "stems folder → balanced mix + master, with notes on every move"),
        ("balance", "hypnomix.engineer.balance", "stems folder → a first fader balance as proposals, with the measurement behind each move (faders only; --plan sends them to the review)"),
        ("master", "hypnomix.engineer.master", "stereo mix → release master at a loudness target (or a reference); options: tonal stabilizer, dynamic EQ, band width, limiter character, harshness, dither, amount"),
        ("rebalance", "hypnomix.engineer.rebalance", "turn vocals / drums / bass / other up or down in a finished stereo mix (separation + residual, true-peak safe)  [extra: ml, or --stems]"),
        ("chain", "hypnomix.engineer.chain", "build the mastering chain (or channel strips) in Live from stock devices, or in REAPER or HypnoMix DAW: no paid plug-ins"),
        ("devices", "hypnomix.engineer.devices", "check every Live device by what it does (compressors, gates, limiters, EQ low cut) and suggest settings (writes a new set)"),
        ("duck", "hypnomix.engineer.duck", "duck the vocal reverb and delay: tune the ducking you have, or add a sidechained Compressor fed by the vocals (writes a new set)"),
        ("sidechain", "hypnomix.engineer.sidechain", "sidechain compressors: measure the ducking (depth, recovery, timing) and suggest settings"),
        ("masking", "hypnomix.engineer.masking", "which stems fight over which frequencies, and the cut that fixes it (written as a band on the part's own EQ once approved)"),
        ("align", "hypnomix.engineer.align", "phase/polarity/time offset between mics on one source"),
        ("translate", "hypnomix.engineer.translate", "mono, phone, earbuds, car, streaming normalisation, codec clipping; --preview to hear MP3 / AAC / as streaming plays it"),
        ("qc", "hypnomix.engineer.qc", "release checks: format, silence, true peak, loudness, phase (exit 1 on fail)"),
        ("album", "hypnomix.engineer.album", "an EP or album as a whole: which songs sit apart in level, tone and width, the gap between each pair, order options; ALBUM.md, report first (--plan: trims, tilts and silence as findings)"),
        ("release", "hypnomix.engineer.release", "master → the folder you upload: 24-bit and 16-bit WAV, MP3 320, AAC 256 (FLAC if you like) with tags and cover, and a report with the true peak after decoding; --check first"),
        ("versions", "hypnomix.engineer.versions", "instrumental, a cappella, TV mix and radio edit from your own exported stems (no separation); checks the stems add up to the mix; --check first"),
    ]),
    ("Studio: recording real instruments", [
        ("prep", "hypnomix.studio.prep", "raw takes → mix-ready stems: clicks, clipping, plosives, breaths, hiss, silence, fades"),
        ("soundcheck", "hypnomix.studio.soundcheck", "set your input gain before recording; live meter"),
        ("takes", "hypnomix.studio.takes", "rank takes by clipping, noise, pitch, timing; comp list per section"),
        ("vocalign", "hypnomix.studio.vocalign", "align doubles and harmonies to the lead: timing, optional pitch match, formant"),
        ("alignset", "hypnomix.studio.alignset", "align vocal parts inside a Live set or REAPER project: warp / stretch markers on your own clips"),
        ("tune", "hypnomix.studio.tune", "natural pitch correction: each note's centre to the song's tuning, vibrato and slides kept"),
        ("clipmatch", "hypnomix.studio.clipmatch", "even out clips recorded at different gain / mic positions (files or a Live track)"),
        ("dehiss", "hypnomix.studio.dehiss", "spectral de-hiss + smart gate for one track (free stand-in for a spectral de-noiser)"),
        ("deess", "hypnomix.studio.deess", "split-band de-esser for one vocal: turns down only the 's' moments, lists each one"),
        ("breaths", "hypnomix.studio.breaths", "turn breaths between phrases down (not off) on one vocal; report first"),
        ("voices", "hypnomix.studio.voices", "re-arrange harmony stems into Voice 1 (lowest) … Voice N tracks: one fader per harmony step"),
        ("cleanup", "hypnomix.studio.cleanup", "demo rescue: hum, noise, rumble, DC, silence"),
    ]),
    ("Ears: measure and compare", [
        ("measure", "hypnomix.ears.measure", "loudness, true peak, bands, stereo, tempo, key → JSON"),
        ("spectrogram", "hypnomix.ears.spectrogram", "spectrogram + loudness curve + average spectrum PNG"),
        ("key", "hypnomix.ears.key", "song key + section-by-section scale map with confidence; names the disputed note when unsure"),
        ("pitchcheck", "hypnomix.ears.pitchcheck", "pitch (cents) + loudness difference between two captures: check every re-render"),
        ("clicks", "hypnomix.ears.clicks", "find clicks and crackle in renders and processed files"),
        ("punch", "hypnomix.ears.punch", "transient punch / pumping / harmonics A/B at matched loudness"),
        ("stems", "hypnomix.ears.stems", "who owns which band (and a resonance) in a folder of stems"),
        ("reference", "hypnomix.ears.reference", "what it would take to sound like a reference  [extra: reference]"),
        ("match", "hypnomix.ears.match", "mix vs a reference as a list of proposals: tone by band, dynamics, width, loudness"),
        ("compare", "hypnomix.ears.compare", "this bounce against the previous one: aligned, in plain words (loudness, tone by band, width, each section) with level-matched A/B clips of where they differ most"),
        ("tonal", "hypnomix.ears.tonal", "tonal-balance targets from your own masters or chosen references; where a mix sits outside the range, with EQ proposals and a plot"),
        ("harsh", "hypnomix.ears.harsh", "harshness report: sustained 2-6 kHz build-ups with timestamps (master --harsh tames only those)"),
        ("sections", "hypnomix.ears.sections", "find the song's sections; loudness and vocal balance per section (give --bpm)"),
        ("separate", "hypnomix.ears.separate", "split a mixed song into stems  [extra: ml]"),
        ("midi", "hypnomix.ears.midi", "audio → MIDI (+ into a Live clip)  [extra: ml]"),
        ("critique", "hypnomix.ears.critique", "a cloud model (Gemini) listens to a mix: notes by ear  [extra: critique, Gemini or OpenRouter key]"),
    ]),
    ("Live: hands on the set (AbletonOSC)", [
        ("live", "hypnomix.live.osc", "mixer, devices, VST parameters, transport, snapshots, arm/record"),
        ("loop", "hypnomix.live.loop", "play bars → record → measure → compare; one-change A/Bs"),
        ("probe", "hypnomix.app.probe", "measure every track while Live plays, after all its plug-ins (Max for Live probe): no renders, a review from what was heard"),
        ("abset", "hypnomix.workflow.abset", "one new set with every proposed fix as a switched-off B next to yours: A / B / Blind inside Live or REAPER (`reaper review`), loudness-matched"),
        ("diagnose", "hypnomix.session.doctor", "solo every group in the loudest section: who owns the sub, bass, vocal band"),
    ]),
    ("Projects: REAPER (.rpp), HypnoMix DAW (.ardour) and Live (.als)", [
        ("reaper", "hypnomix.reaper.cli", "talk to the REAPER that is open: start the bridge, tracks, installed plug-ins, parameters, probes, the A/B review panel, the Align panel"),
        ("preflight", "hypnomix.session.preflight", "sanity of the files before any work: mixed sample rates or bit depths, stems of different length, duplicates, fake stereo, silent or clipped files, lossy sources, missing files, names that will not travel; report first"),
        ("project", "hypnomix.project.show", "look inside a REAPER, HypnoMix DAW or Live project (tracks, folders, items, takes, plug-ins, automation) and render its tracks"),
        ("import", "hypnomix.project.import_project", "import a project from another DAW into a NEW HypnoMix DAW session: .als, .logicx, .dawproject, .rpp, or .ptx and .aaf (with the HypnoMix DAW add-on, not available yet); audio copied in, the project only read, what was left out listed"),
        ("als2ardour", "hypnomix.project.als2ardour", "import a Live set into a NEW HypnoMix DAW session folder: tracks, colours, clips as regions (gain, fades, envelopes), faders, sends, groups, tempo; audio copied in; devices listed, never guessed (the set is only read)"),
    ]),
    ("Session files (.als, Live closed or open)", [
        ("render", "hypnomix.session.render", "render tracks from a .als to stems without opening Live (clip gain, fades, warps)"),
        ("plugrender", "hypnomix.session.plugrender", "render tracks from a .als through their real VST3/AU plug-in chains, offline, faster than real time  [extra: plugins]"),
        ("name", "hypnomix.session.names", "name every track and group by how it sounds (vocal, harmony, guitar, strings, drums…)"),
        ("mine", "hypnomix.session.miner", "tempo, key, tracks, plug-in chains, routing, levels from a set"),
        ("audit", "hypnomix.session.audit", "flags EQ, stacked limiters, bypassed devices; bounce vs your profile"),
        ("automation", "hypnomix.session.automation", "list/show/offset/dip automation envelopes (writes a new set)"),
        ("smooth", "hypnomix.session.smooth", "find clicks, level jumps at cuts and spikes on clips; ease them (writes a new set)"),
        ("cliplevel", "hypnomix.session.cliplevel", "lower harmony clips sitting well under the rest of their track: propose clip-gain raises (writes a new set)"),
        ("borrow", "hypnomix.session.borrow", "offer unused loops from the song's original project as switched-off layers (MIDI nudged to the song's downbeat; writes a new set)"),
        ("motion", "hypnomix.session.motion", "keep repetitive sections alive: filter sweeps, reverb/delay throws, stutters, gate chops, drop-outs, as options learned from your own automation (writes a new set)"),
        ("unroll", "hypnomix.session.unroll", "turn looped Arrangement clips into one copy per pass, so each pass can be edited on its own (writes a new set)"),
        ("vocallevel", "hypnomix.session.vocallevel", "vocal level line to line, and upper harmonies under the melody: as heard (solo exports) or from renders; --apply writes per-line volume fixes (writes a new set). Run before every final export"),
        ("edges", "hypnomix.session.edges", "clip edges and fades that cut into a word (a long fade-in ducking the first consonant, a comp edit that loses a sound)"),
        ("tidy", "hypnomix.session.tidy", "retire switched-off tracks (after an archive copy) and put one instrument's clips on one track (writes a new set)"),
        ("order", "hypnomix.session.order", "put tracks in working order (drums, bass, keys/guitar/synth, vocals, other; low to high) and vocal-stack clips on the track for their pitch (writes a new set)"),
        ("timing", "hypnomix.session.timing", "find hits out of time with the band; nudge only those with warp markers (writes a new set)"),
        ("tempomap", "hypnomix.session.tempomap", "map the tempo of a take played without a click; warp it to the grid, or make the grid follow it"),
        ("loops", "hypnomix.session.loops", "find the best loops in a free-played take; line them up in Session slots to try"),
        ("tighten", "hypnomix.session.tighten", "pull a take's hits part of the way toward the click, in place (a gentle quantise)"),
        ("breathe", "hypnomix.session.breathe", "let a click-recorded song breathe: small tempo changes by section, with a preview"),
        ("variations", "hypnomix.session.variations", "vary repetitive loops with unused takes, on new switched-off tracks next to each part"),
        ("colour", "hypnomix.session.colour", "propose new timbres where a part sounds the same throughout: width, grit, space, movement or octave, as Live-device chains on switched-off copies, each with a before / after clip (Live sets; writes a new set only for the ones you pick)"),
        ("distortion", "hypnomix.session.distortion", "find audible distortion (clipped takes, overs, hot drive, fast bass compression); propose fixes"),
        ("refs", "hypnomix.session.refs", "find missing audio files in sets"),
        ("diff", "hypnomix.session.diff", "what changed between two sets, in plain words (faders, devices, clips, automation)"),
        ("check", "hypnomix.session.check", "structural check of a written set before anyone opens it in Live (exit 1 on errors)"),
        ("profile", "hypnomix.session.profile", "build your sound profile from songs you love"),
    ]),
    ("Workflow: scan a song, review, fix", [
        ("demo", "hypnomix.studio.demo", "a 40-second demo song with labelled problems (click, level jump, hiss, clipping, a drifting harmony, late hits) to try scan, ab and fix on nothing of your own; a folder of stems or a REAPER project"),
        ("scan", "hypnomix.workflow.scan", "first pass: run every check on a set or a folder of recordings, change nothing, write REVIEW.md"),
        ("fix", "hypnomix.workflow.fix", "apply only the findings you approved, into ONE new set (original untouched)"),
        ("taste", "hypnomix.workflow.taste", "your tastes and standards from your own finished songs: levels, pans, sends, chains, vocals (TASTE.md); --library studies every set on this computer: style plus where to improve"),
        ("prefs", "hypnomix.workflow.prefs", "your preferences, asked once: targets, protected tracks, how you like to review"),
        ("ab", "hypnomix.workflow.ab", "before/after clips for each proposed fix (clips, tuning, timing nudges, device changes it can model), level-matched, so you hear it before approving"),
        ("review", "hypnomix.workflow.review", "the review as one page: play each A/B, tick approve / skip / change"),
        ("history", "hypnomix.workflow.history", "every version fix wrote for a song: list, diff, undo into a new set, rebuild without one item"),
        ("handoff", "hypnomix.workflow.handoff", "turn the by-hand list into your DAW's own words: HANDOFF.md checklist by position, plus markers (a new set with locators, a new REAPER project with markers, or a MIDI marker file and CSV)"),
        ("watch", "hypnomix.workflow.watch", "watch a set while you work: a quick incremental scan on every save (read-only)"),
    ]),
    ("App: no terminal, no AI needed", [
        ("app", "hypnomix.app.server", "the first pass in a window: choose a song, hear each fix, approve, apply (this computer only)"),
        ("device", "hypnomix.app.device", "make the Max for Live device: review from inside Live, and jump Live to each finding"),
        ("aligndevice", "hypnomix.app.aligndevice", "make the Hypnomix Align device: align a vocal stack from inside Live"),
        ("store", "hypnomix.store.cli", "the HypnoMix store: search, install, update and uninstall free and open-source plug-ins, synths, drum kits and sample packs"),
        ("engine", "hypnomix.app.engine_addon", "HypnoMix DAW, the add-on (not available yet: no archive is published): what is added, and (only with --yes) fetch it once, checked against a SHA-256 before it is used, or remove it; report first"),
    ]),
    ("Setup", [
        ("install", "hypnomix.install", "install the Live remote script into Live's User Library (--dry-run shows it first)"),
        ("doctor", "hypnomix.install", "check ffmpeg and the Python packages (and, if you use Live: AbletonOSC, BlackHole, plug-in parameter access)"),
        ("report", "hypnomix.workflow.report", "write a problem report on this computer (what happened, your setup, the last job's log, a crash record), with paths, names and keys hidden as far as it can tell; prints it, nothing is sent; --copy and --open help you send it yourself"),
        ("plugins", "hypnomix.session.plugins", "list the plug-ins installed on this computer (VST3, Audio Units, CLAP, LV2), mark the free ones HypnoMix knows, optionally load each safely; --save keeps the list in your preferences  [--check: extra plugins]"),
    ]),
]
COMMANDS = {name: (mod, desc) for _, cmds in GROUPS for name, mod, desc in cmds}


def usage():
    lines = [__doc__.strip(), ""]
    for title, cmds in GROUPS:
        lines.append(title)
        lines += [f"  {n:<12} {d}" for n, _, d in cmds]
        lines.append("")
    return "\n".join(lines)


def _utf8_output():
    """A piped or redirected stdout is cp1252 on Windows (or ASCII under a bare "C" locale), which can't print ✓ ✗ → … − (doctor,
    scan and every report): say UTF-8, and a character the reader still cannot show becomes "?" instead of a traceback."""
    for stream in (sys.stdout, sys.stderr):
        if stream is None or not hasattr(stream, "reconfigure"):        # no console at all (pythonw), or not a text file
            continue
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if enc == "utf8" and getattr(stream, "errors", "") != "strict":
            continue
        for kw in (dict(encoding="utf-8", errors="replace"), dict(errors="replace")):
            try:
                stream.reconfigure(**kw)
                break
            except (ValueError, OSError, TypeError):
                continue


def main(argv=None):
    """Run a command. A file that cannot be read as audio ends with one plain line and exit code 2, no traceback
    (set HYPNOMIX_DEBUG=1 to see the traceback). An unexpected error (a bug) saves a crash record on this computer, ends with
    one plain sentence and exit code 70 (HYPNOMIX_DEBUG=1 still shows the traceback); nothing is sent."""
    argv = list(sys.argv[1:] if argv is None else argv)      # taken now: _main rewrites sys.argv, and a crash record needs the real command
    try:
        return _main(argv)
    except SystemExit as e:
        _remember_exit(argv, e)
        raise
    except Exception as e:
        msg = None if os.environ.get("HYPNOMIX_DEBUG") else _audio_read_message(e)
        if msg is None:
            if os.environ.get("HYPNOMIX_DEBUG") or _quiet_error(e):
                raise
            _crashed(argv, e)
        _remember_exit(argv, SystemExit(2), msg)
        print(msg, file=sys.stderr)
        sys.exit(2)


def _quiet_error(e):
    """An error that is not a bug: the reader of a pipe went away (`hypnomix scan | head`)."""
    return isinstance(e, BrokenPipeError) or (isinstance(e, OSError) and e.errno == errno.EPIPE)


def _command_of(argv):
    args = list(sys.argv[1:] if argv is None else argv)
    return (args[0] if args and args[0] in COMMANDS else "unknown"), args[1:]


def _crashed(argv, e):
    """An unexpected exception in a command: a crash record on this computer, ONE plain sentence, exit code 70 (set
    HYPNOMIX_DEBUG=1 to get the traceback instead). Nothing is sent anywhere."""
    from hypnomix.core import report
    cmd, rest = _command_of(argv)
    info = report.write_crash("cli", cmd, exc=e, argv=rest)
    if cmd != "report":
        report.record_last("cli", cmd, "crashed", reason=type(e).__name__, exit_code=70)
    print(report.crash_sentence(info), file=sys.stderr)
    sys.exit(70)


def _remember_exit(argv, e, message=None):
    """A command that ends with an error is remembered (one small private file) so a report can say how it ended.
    Never raises."""
    try:
        code = e.code
        if code in (None, 0):
            return
        cmd, _ = _command_of(argv)
        if cmd in ("report", "unknown"):
            return
        from hypnomix.core import report
        why = message or (code if isinstance(code, str) else "")
        report.record_last("cli", cmd, "failed", reason=str(why).strip().splitlines()[0] if str(why).strip() else "",
                           exit_code=code if isinstance(code, int) else 1)
    except Exception:
        pass


def _raised_in_gzip(e):
    """True when the error came out of opening a gzip file (how the commands that read Live sets fail on a bad path)."""
    tb = e.__traceback__
    while tb is not None:
        if os.path.basename(tb.tb_frame.f_code.co_filename) == "gzip.py":
            return True
        tb = tb.tb_next
    return False


def _audio_read_message(e):
    """The plain message for "this file cannot be read as audio", or None when `e` is something else (a real bug)."""
    name = type(e).__name__
    if name in ("AudioReadError", "MissingToolError"):      # MissingToolError: a program such as Rubber Band is not installed, and how to get it
        return str(e)
    if name == "ProjectReadError":              # a damaged or wrong .rpp / .ardour / .als: the file name, then why
        return f"{e.name}: {e}"
    if name == "LibsndfileError" and str(e).startswith("Error opening "):   # a command that opens the file itself
        path, _, why = str(e)[len("Error opening "):].partition(": ")
        gone = "no such file" if not os.path.exists(path.strip("'\"")) else "not an audio file HypnoMix can decode"
        return f"can't read {path} as audio: {gone}"
    if name == "BadGzipFile":                   # a Live-set command was given a file that is not a gzipped Live set
        return ("can't read that file as a Live set (.als): it is not a gzip file. This command reads Live sets only; "
                "for a REAPER project or a HypnoMix DAW session use `hypnomix scan` on it.")
    folder = isinstance(e, IsADirectoryError) or (isinstance(e, PermissionError) and os.path.isdir(str(e.filename or "")))   # Windows opens a folder with "permission denied"
    if (folder or isinstance(e, FileNotFoundError)) and _raised_in_gzip(e):    # a Live-set command, a typo or a folder
        fn = str(e.filename or "that path")
        if folder:
            return f"{fn} is a folder, not a Live set (.als file); give the .als file itself."
        return f"no such file: {fn}; check the name and the folder, then try again."
    if isinstance(e, OSError) and (isinstance(e, PermissionError) or e.errno in (errno.ENOSPC, errno.EROFS, errno.EDQUOT)):
        fn = str(e.filename) if e.filename else "that place"      # whatever a command writes late: one sentence, not a traceback
        why = (e.strerror or "permission denied").lower()
        if os.path.exists(fn) and not os.access(fn, os.R_OK):
            return f"can't read '{fn}': {why}; check that the file is yours to open"
        return f"can't write to '{fn}': {why}; choose another place with --out"
    return None


def _main(argv=None):
    _utf8_output()
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage()); return
    cmd, rest = argv[0], argv[1:]
    if cmd not in COMMANDS:
        sys.exit(f"unknown command {cmd!r}\n\n{usage()}")
    mod = importlib.import_module(COMMANDS[cmd][0])
    sys.argv = [f"hypnomix {cmd}"] + rest
    if cmd in ("punch", "refs", "pitchcheck") and (not rest or rest[0] in ("-h", "--help")):
        print(mod.__doc__.strip())          # these three take plain file arguments and have no option parser
        sys.exit(0 if rest else 2)
    if cmd == "live":
        try:
            mod._cli(rest)
        except mod.LiveError as e:
            sys.exit(str(e))
    elif cmd == "punch":
        if len(rest) < 2:
            sys.exit(mod.__doc__)
        mod.main(rest)
    elif cmd == "refs":
        bad = 0
        for f in rest:
            seen, missing, outside = mod.check(f)
            n = sum(len(v) for v in missing.values()); bad += n
            print(f"{'OK ' if not n else 'MISSING'} {f}: {seen} sample refs, {n} missing")
            for t, s in missing.items():
                print(f"   {t}: {sorted(s)[:3]}")
        sys.exit(1 if bad else 0)
    elif cmd in ("install", "doctor"):
        getattr(mod, cmd)(rest)
    else:
        try:
            mod.main()
        except Exception as e:                # Live not answering, or its script missing a piece: say so plainly
            if type(e).__name__ != "LiveError":
                raise
            sys.exit(str(e))


if __name__ == "__main__":
    main()
