"""hypnomix: a mixing and mastering engineer for Ableton Live and REAPER, driven by you or by Claude Code.

Run `hypnomix` for the command list, `hypnomix <command> -h` for each command's help.
"""
import importlib
import sys

GROUPS = [
    ("Engineer: stems in, song out", [
        ("automix", "hypnomix.engineer.automix", "stems folder → balanced mix + master, with notes on every move"),
        ("balance", "hypnomix.engineer.balance", "stems folder → a first fader balance as proposals, with the measurement behind each move (faders only; --plan sends them to the review)"),
        ("master", "hypnomix.engineer.master", "stereo mix → release master at a loudness target (or a reference); options: tonal stabilizer, dynamic EQ, band width, limiter character, harshness, dither, amount"),
        ("rebalance", "hypnomix.engineer.rebalance", "turn vocals / drums / bass / other up or down in a finished stereo mix (separation + residual, true-peak safe)  [extra: ml, or --stems]"),
        ("chain", "hypnomix.engineer.chain", "build the mastering chain (or channel strips) in Live from stock devices: no paid plug-ins"),
        ("devices", "hypnomix.engineer.devices", "check every Live device by what it does (compressors, gates, limiters, EQ low cut) and suggest settings (writes a new set)"),
        ("duck", "hypnomix.engineer.duck", "duck the vocal reverb and delay: tune the ducking you have, or add a sidechained Compressor fed by the vocals (writes a new set)"),
        ("sidechain", "hypnomix.engineer.sidechain", "sidechain compressors: measure the ducking (depth, recovery, timing) and suggest settings"),
        ("masking", "hypnomix.engineer.masking", "which stems fight over which frequencies, and the cut that fixes it"),
        ("align", "hypnomix.engineer.align", "phase/polarity/time offset between mics on one source"),
        ("translate", "hypnomix.engineer.translate", "mono, phone, earbuds, car, streaming normalisation, codec clipping; --preview to hear MP3 / AAC / as streaming plays it"),
        ("qc", "hypnomix.engineer.qc", "release checks: format, silence, true peak, loudness, phase (exit 1 on fail)"),
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
    ("Projects: REAPER (.rpp), Ardour (.ardour) and Live (.als)", [
        ("reaper", "hypnomix.reaper.cli", "talk to the REAPER that is open: start the bridge, tracks, installed plug-ins, parameters, probes, the A/B review panel, the Align panel"),
        ("project", "hypnomix.project.show", "look inside a REAPER, Ardour or Live project (tracks, folders, items, takes, plug-ins, automation) and render its tracks"),
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
        ("scan", "hypnomix.workflow.scan", "first pass: run every check on a set or a folder of recordings, change nothing, write REVIEW.md"),
        ("fix", "hypnomix.workflow.fix", "apply only the findings you approved, into ONE new set (original untouched)"),
        ("taste", "hypnomix.workflow.taste", "your tastes and standards from your own finished songs: levels, pans, sends, chains, vocals (TASTE.md); --library studies every set on this computer: style plus where to improve"),
        ("prefs", "hypnomix.workflow.prefs", "your preferences, asked once: targets, protected tracks, how you like to review"),
        ("ab", "hypnomix.workflow.ab", "before/after clips for each proposed fix, level-matched, so you hear it before approving"),
        ("review", "hypnomix.workflow.review", "the review as one page: play each A/B, tick approve / skip / change"),
        ("history", "hypnomix.workflow.history", "every version fix wrote for a song: list, diff, undo into a new set, rebuild without one item"),
        ("handoff", "hypnomix.workflow.handoff", "turn the by-hand list into your DAW's own words: HANDOFF.md checklist by position, plus markers (a new set with locators, a new REAPER project with markers, or a MIDI marker file and CSV)"),
        ("watch", "hypnomix.workflow.watch", "watch a set while you work: a quick incremental scan on every save (read-only)"),
    ]),
    ("App: no terminal, no AI needed", [
        ("app", "hypnomix.app.server", "the first pass in a window: choose a song, hear each fix, approve, apply (this computer only)"),
        ("device", "hypnomix.app.device", "make the Max for Live device: review from inside Live, and jump Live to each finding"),
        ("aligndevice", "hypnomix.app.aligndevice", "make the Hypnomix Align device: align a vocal stack from inside Live"),
    ]),
    ("Setup", [
        ("install", "hypnomix.install", "install the Live remote script, write Claude Code config"),
        ("doctor", "hypnomix.install", "check Live, AbletonOSC, BlackHole, ffmpeg, plug-in parameter access"),
        ("plugins", "hypnomix.session.plugins", "list the plug-ins installed on this computer (VST3, Audio Units, CLAP, LV2), mark the free ones hypnomix knows, optionally load each safely; --save keeps the list in your preferences  [--check: extra plugins]"),
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
    """On Windows a piped or redirected stdout is cp1252, which can't print ✓ ✗ → … (doctor, scan reports)."""
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if enc != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv=None):
    if sys.platform == "win32":
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
