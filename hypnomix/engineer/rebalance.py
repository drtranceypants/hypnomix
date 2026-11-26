#!/usr/bin/env python3
"""Turn the vocals, bass, drums or everything else up or down in a finished stereo mix.

The mix is split into stems (`hypnomix separate`, needs the ml extra) or you give stems you already have with
--stems DIR (Vocals.wav, Drums.wav, Bass.wav, Other.wav, from the same mix). Each stem's gain is applied as a
change on top of the mix:

    new = mix + (gain_vocals - 1) × vocals + (gain_drums - 1) × drums + …

so whatever the separation missed (the residual: mix minus the sum of the stems) stays exactly where it was, and
with every gain at 0 dB the output IS the mix. The report says how far from the mix a 0 dB run comes (rounding
error only) and how much of the mix the stems do not explain (a large residual means the stems are from another
version or the separation is poor: moves will be partial).

Separation is never perfect: each stem carries a little of the others. Boosting a stem a lot also boosts that
leakage and the separation's artefacts (watery cymbals, a vocal ghost in "other"). Small moves (±1-3 dB) are
safest; listen to the result against the mix at matched loudness.

The result is true-peak safe: --safety gain (default) turns the whole file down until it sits under --ceiling,
--safety limit uses the true-peak limiter instead (keeps loudness, touches peaks). --keep-loudness first restores
the mix's integrated loudness.

Usage:
    hypnomix rebalance MIX.wav [--vocals +1.5] [--drums 0] [--bass -1] [--other 0]
                       [--stems DIR | --model 4stem] [--ceiling -1] [--safety gain|limit] [--keep-loudness]
                       [--dither tpdf|shaped|off] [--out DIR]
"""
import argparse, json, sys
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core import args as A
from hypnomix.core.paths import out_at

STEMS = ("vocals", "drums", "bass", "other")


# Other names stems come with. Matching ignores case, spaces, dashes and underscores; a name that only contains one of
# these words (`song_vocal.wav`, `Vocals (mix).wav`) matches too. "no vocals" / "without vocals" is the rest of the band.
ALIASES = {
    "vocals": ("vocals", "vocal", "vox", "voice", "voices", "leadvocal", "leadvocals", "acapella", "acappella"),
    "drums": ("drums", "drum", "drumkit", "kit", "percussion"),
    "bass": ("bass", "basses", "bassline"),
    "other": ("other", "others", "music", "inst", "instr", "instruments", "instrumental", "instrumentals",
              "accompaniment", "backing", "novocals", "novocal", "withoutvocals"),
}


def stem_kind(stem_name):
    """'vocals', 'drums', 'bass' or 'other' for a stem file's name (without extension), or None."""
    import re
    flat = re.sub(r"[^a-z0-9]", "", stem_name.lower())
    for kind, names in ALIASES.items():
        if flat in names:
            return kind
    tokens = re.findall(r"[a-z0-9]+", stem_name.lower())
    if any(t in ("no", "without", "minus") for t in tokens):          # demucs "no_vocals": the rest of the band
        if any(t in ALIASES["vocals"] for t in tokens):
            return "other"
    for kind, names in ALIASES.items():
        if any(t in names for t in tokens):
            return kind
    return None


def load_stems(folder, sr, n):
    """Vocals.wav, Drums.wav, Bass.wav, Other.wav from a folder, at the mix's rate and length. Case does not matter,
    and the usual variants work too (vocal, vox, drum, music, inst ...; see ALIASES). Raises FileNotFoundError, listing
    the audio files it did find, when none of them is a stem."""
    folder = Path(folder)
    got, seen = {}, []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in dsp.AUDIO_EXT:
            continue
        seen.append(f.name)
        k = stem_kind(f.stem)
        if k is None or k in got:
            continue
        y, _ = dsp.load(f, sr)
        y = dsp.stereo(y)
        y = np.pad(y, ((0, max(0, n - len(y))), (0, 0)))[:n]
        got[k] = y
    if not got:
        raise FileNotFoundError(f"no Vocals/Drums/Bass/Other files in {folder}" +
                                (f"; the audio files there are: {', '.join(seen)}" if seen else "; no audio files there"))
    return got


def rebalance(mix, stems, gains_db, ceiling=-1.0, safety="gain", keep_loudness=False, sr=44100):
    """mix: (n, 2); stems: {name: (n, 2)}; gains_db: {name: dB}. Returns (out, report)."""
    mix = dsp.stereo(mix)
    out = mix.copy()
    for k, s in stems.items():
        g = float(gains_db.get(k, 0.0))
        if g:
            out += (dsp.undb(g) - 1) * s
    resid = mix - sum(stems.values())
    # identity check: residual + every stem at 0 dB, summed the same way the result is
    ident = resid.copy()
    for k, s in stems.items():
        ident += dsp.undb(0.0) * s
    err = float(np.max(np.abs(ident - mix))) if len(mix) else 0.0
    rep = dict(gains_db={k: float(gains_db.get(k, 0.0)) for k in stems},
               identity_error_db=round(dsp.db(err), 1) if err > 0 else None,
               residual_db=round(dsp.rms_db(resid) - dsp.rms_db(mix), 1),
               stem_levels_db={k: round(dsp.rms_db(s) - dsp.rms_db(mix), 1) for k, s in stems.items()},
               lufs_before=dsp.lufs(mix, sr), tp_before=dsp.true_peak(mix, sr))
    if keep_loudness and any(rep["gains_db"].values()):
        out *= dsp.undb(rep["lufs_before"] - dsp.lufs(out, sr))
    tp = dsp.true_peak(out, sr)
    rep["tp_raw"] = tp
    if tp > ceiling:
        if safety == "limit":
            out, gr = dsp.limit(out, sr, ceiling)
            rep["safety"] = f"true-peak limiter at {ceiling} dBTP (max {-gr.min():.1f} dB of limiting)"
        else:
            out = out * dsp.undb(ceiling - tp - 0.05)
            rep["safety"] = f"turned down {tp - ceiling + 0.05:.2f} dB to sit under {ceiling} dBTP"
    else:
        rep["safety"] = "none needed"
    rep.update(lufs_after=dsp.lufs(out, sr), tp_after=dsp.true_peak(out, sr))
    return out, rep


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix rebalance", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mix")
    for k in STEMS:
        ap.add_argument(f"--{k}", type=float, default=0.0, help=f"dB change for {k}")
    ap.add_argument("--stems", help="folder with Vocals/Drums/Bass/Other from this mix (skips separation)")
    ap.add_argument("--model", default="4stem", help="separation model when --stems is not given (see `separate`)")
    ap.add_argument("--ceiling", type=A.number(-12, 0), default=-1.0, help="true-peak ceiling, dBTP (-12 to 0)")
    ap.add_argument("--safety", choices=["gain", "limit"], default="gain")
    ap.add_argument("--keep-loudness", action="store_true", help="match the mix's integrated loudness first")
    ap.add_argument("--dither", choices=["tpdf", "shaped", "off"], default="tpdf")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    gains = {k: getattr(a, k) for k in STEMS}
    y, sr = dsp.load(a.mix)
    y = dsp.stereo(y)
    name = Path(a.mix).stem
    od = out_at(a.out, "rebalance", name)
    folder = a.stems
    if not folder:
        from hypnomix.ears.separate import separate_to
        folder = od / "stems"
        print(f"separating {Path(a.mix).name} ({a.model}) …", file=sys.stderr)
        try:
            separate_to(a.mix, folder, a.model)
        except ImportError as e:
            sys.exit(str(e))
    try:
        stems = load_stems(folder, sr, len(y))
    except FileNotFoundError as e:
        sys.exit(str(e))
    missing = [k for k in gains if gains[k] and k not in stems]
    if missing:
        found = ", ".join(sorted(f.name for f in Path(folder).iterdir() if f.suffix.lower() in dsp.AUDIO_EXT)) or "none"
        sys.exit(f"no stem for {', '.join(missing)} in {folder}. Audio files found there: {found}. "
                 f"Name them Vocals, Drums, Bass, Other (vocal, vox, drum, music, inst also work)")
    out, rep = rebalance(y, stems, gains, a.ceiling, a.safety, a.keep_loudness, sr)
    tag = " ".join(f"{k} {v:+g}" for k, v in gains.items() if v) or "unchanged"
    dest, i = od / f"{name} (rebalanced {tag}).wav", 1
    while dest.exists():
        i += 1
        dest = od / f"{name} (rebalanced {tag} {i}).wav"
    dsp.save(dest, out, sr, 24, dither=a.dither)
    warn = []
    if rep["residual_db"] > -15:
        warn.append(f"the stems leave {rep['residual_db']:+.1f} dB of the mix unexplained: they may be from another version "
                    "of the song, or the separation struggled. Moves will be partial; check the stems are this mix.")
    if any(abs(v) > 3 for v in gains.values()):
        warn.append("moves over 3 dB also move the separation's leakage and artefacts: listen for watery cymbals or "
                    "ghost vocals.")
    md = [f"# Rebalance: {Path(a.mix).name}", "", f"Gains: {tag}", "",
          "| | mix | result |", "|---|---|---|",
          f"| Integrated loudness | {rep['lufs_before']:.1f} LUFS | {rep['lufs_after']:.1f} LUFS |",
          f"| True peak | {rep['tp_before']:+.2f} dBTP | {rep['tp_after']:+.2f} dBTP |", "",
          "Stem levels against the mix: " + ", ".join(f"{k} {v:+.1f} dB" for k, v in rep["stem_levels_db"].items()), "",
          f"Residual (what the stems do not explain): {rep['residual_db']:+.1f} dB against the mix.",
          "Identity check (every gain 0 dB): " + ("exact" if rep["identity_error_db"] is None else
                                                  f"max error {rep['identity_error_db']:.1f} dBFS"),
          f"True-peak safety: {rep['safety']}.", ""]
    if warn:
        md += ["## Warnings", *[f"- {w}" for w in warn], ""]
    md += [f"File: `{dest}`", "", "Listen against the mix at matched loudness; `hypnomix ab` or any player."]
    text = "\n".join(md) + "\n"
    (od / f"{dest.stem} notes.md").write_text(text, encoding="utf-8")
    (od / f"{dest.stem}.json").write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
