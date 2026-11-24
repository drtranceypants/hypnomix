"""hypnomix: a mixing and mastering engineer for Ableton Live, driven by you or by Claude Code.

Run `hypnomix` for the command list, `hypnomix <command> -h` for each command's help.
"""
import importlib
import sys

GROUPS = [
    ("Engineer: stems in, song out", [
        ("automix", "hypnomix.engineer.automix", "stems folder → balanced mix + master, with notes on every move"),
        ("master", "hypnomix.engineer.master", "stereo mix → release master at a loudness target (or matched to a reference)"),
        ("chain", "hypnomix.engineer.chain", "build the mastering chain (or channel strips) in Live from stock devices: no paid plug-ins"),
        ("sidechain", "hypnomix.engineer.sidechain", "sidechain compressors: measure the ducking (depth, recovery, timing) and suggest settings"),
        ("masking", "hypnomix.engineer.masking", "which stems fight over which frequencies, and the cut that fixes it"),
        ("align", "hypnomix.engineer.align", "phase/polarity/time offset between mics on one source"),
        ("translate", "hypnomix.engineer.translate", "mono, phone, earbuds, car, streaming normalisation, codec clipping"),
        ("qc", "hypnomix.engineer.qc", "release checks: format, silence, true peak, loudness, phase (exit 1 on fail)"),
    ]),
    ("Studio: recording real instruments", [
        ("prep", "hypnomix.studio.prep", "raw takes → mix-ready stems: clicks, clipping, plosives, breaths, hiss, silence, fades"),
        ("soundcheck", "hypnomix.studio.soundcheck", "set your input gain before recording; live meter"),
        ("takes", "hypnomix.studio.takes", "rank takes by clipping, noise, pitch, timing; comp list per section"),
        ("vocalign", "hypnomix.studio.vocalign", "time-align doubles and harmonies to the lead, pitch untouched"),
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
        ("pitchcheck", "hypnomix.ears.pitchcheck", "pitch (cents) + loudness difference between two captures: check every re-render"),
        ("clicks", "hypnomix.ears.clicks", "find clicks and crackle in renders and processed files"),
        ("punch", "hypnomix.ears.punch", "transient punch / pumping / harmonics A/B at matched loudness"),
        ("stems", "hypnomix.ears.stems", "who owns which band (and a resonance) in a folder of stems"),
        ("reference", "hypnomix.ears.reference", "what it would take to sound like a reference  [extra: reference]"),
        ("match", "hypnomix.ears.match", "mix vs a reference as a list of proposals: tone by band, dynamics, width, loudness"),
        ("sections", "hypnomix.ears.sections", "find the song's sections; loudness and vocal balance per section (give --bpm)"),
        ("separate", "hypnomix.ears.separate", "split a mixed song into stems  [extra: ml]"),
        ("midi", "hypnomix.ears.midi", "audio → MIDI (+ into a Live clip)  [extra: ml]"),
        ("critique", "hypnomix.ears.critique", "second opinion from Gemini on a mix  [extra: critique, needs GEMINI_API_KEY]"),
    ]),
    ("Live: hands on the set (AbletonOSC)", [
        ("live", "hypnomix.live.osc", "mixer, devices, VST parameters, transport, snapshots, arm/record"),
        ("loop", "hypnomix.live.loop", "play bars → record → measure → compare; one-change A/Bs"),
        ("diagnose", "hypnomix.session.doctor", "solo every group in the loudest section: who owns the sub, bass, vocal band"),
    ]),
    ("Session files (.als, Live closed or open)", [
        ("render", "hypnomix.session.render", "render tracks from a .als to stems without opening Live (clip gain, fades, warps)"),
        ("name", "hypnomix.session.names", "name every track and group by how it sounds (vocal, harmony, guitar, strings, drums…)"),
        ("mine", "hypnomix.session.miner", "tempo, key, tracks, plug-in chains, routing, levels from a set"),
        ("audit", "hypnomix.session.audit", "flags EQ, stacked limiters, bypassed devices; bounce vs your profile"),
        ("automation", "hypnomix.session.automation", "list/show/offset/dip automation envelopes (writes a new set)"),
        ("smooth", "hypnomix.session.smooth", "find clicks, level jumps at cuts and spikes on clips; ease them (writes a new set)"),
        ("timing", "hypnomix.session.timing", "find hits out of time with the band; nudge only those with warp markers (writes a new set)"),
        ("distortion", "hypnomix.session.distortion", "find audible distortion (clipped takes, overs, hot drive, fast bass compression); propose fixes"),
        ("refs", "hypnomix.session.refs", "find missing audio files in sets"),
        ("diff", "hypnomix.session.diff", "what changed between two sets, in plain words (faders, devices, clips, automation)"),
        ("check", "hypnomix.session.check", "structural check of a written set before anyone opens it in Live (exit 1 on errors)"),
        ("profile", "hypnomix.session.profile", "build your sound profile from songs you love"),
    ]),
    ("Workflow: scan a song, review, fix", [
        ("scan", "hypnomix.workflow.scan", "first pass: run every check on a set or a folder of recordings, change nothing, write REVIEW.md"),
        ("fix", "hypnomix.workflow.fix", "apply only the findings you approved, into ONE new set (original untouched)"),
        ("prefs", "hypnomix.workflow.prefs", "your preferences, asked once: targets, protected tracks, how you like to review"),
        ("ab", "hypnomix.workflow.ab", "before/after clips for each proposed fix, level-matched, so you hear it before approving"),
        ("review", "hypnomix.workflow.review", "the review as one page: play each A/B, tick approve / skip / change"),
    ]),
    ("Setup", [
        ("install", "hypnomix.install", "install the Live remote script, write Claude Code config"),
        ("doctor", "hypnomix.install", "check Live, AbletonOSC, BlackHole, ffmpeg, plug-in parameter access"),
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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage()); return
    cmd, rest = argv[0], argv[1:]
    if cmd not in COMMANDS:
        sys.exit(f"unknown command {cmd!r}\n\n{usage()}")
    mod = importlib.import_module(COMMANDS[cmd][0])
    sys.argv = [f"hypnomix {cmd}"] + rest
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
        mod.main()


if __name__ == "__main__":
    main()
