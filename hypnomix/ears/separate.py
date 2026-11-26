#!/usr/bin/env python3
"""Split a mixed song into stems with the Ultimate Vocal Remover models (via audio-separator).

Runs on the M1 GPU. Output files are named Vocals.wav, Drums.wav, … so ears/stems_report.py reads them directly.

Usage:
    hypnomix separate song.wav [more.wav …] [--model 4stem|6stem|vocals] [--out stems]

Models (downloaded once to ~/.cache/audio-separator-models):
    4stem   htdemucs_ft        Vocals, Drums, Bass, Other            (default)
    6stem   htdemucs_6s        Vocals, Drums, Bass, Guitar, Piano, Other
    vocals  BS-Roformer        Vocals, Instrumental (cleanest vocal split)
"""
import argparse, re, sys, time
from pathlib import Path

MODELS = {
    "4stem": "htdemucs_ft.yaml",
    "6stem": "htdemucs_6s.yaml",
    "vocals": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
}
MODEL_DIR = Path.home() / ".cache" / "audio-separator-models"


def separate_to(src, dest, model="4stem"):
    """Split one file into stems in `dest` (Vocals.wav, Drums.wav, …). Returns {name: path}. Needs the ml extra
    (`pip install -e '.[ml]'`); raises ImportError with that hint when it is missing."""
    import logging
    try:
        from audio_separator.separator import Separator
    except ImportError as e:
        from hypnomix.extras import hint
        raise ImportError(f"stem separation: {hint('ml')} (or give stems you already have with --stems DIR)") from e
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    sep = Separator(model_file_dir=str(MODEL_DIR), output_dir=str(dest), output_format="WAV", log_level=logging.WARNING)
    sep.load_model(model_filename=MODELS[model])
    out = {}
    for o in sep.separate(str(src)):
        p = Path(o) if Path(o).is_absolute() else dest / o
        m = re.search(r"_\(([^)]+)\)_", p.name) or re.search(r"\(([^)]+)\)", p.name)
        new = dest / f"{(m.group(1) if m else p.stem).capitalize()}.wav"
        p.replace(new)
        out[new.stem] = new
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--model", choices=MODELS, default="4stem")
    ap.add_argument("--out", default="stems", help="stems go to <out>/<song>/ (or <out>/<song> (<model>)/ if not 4stem)")
    a = ap.parse_args()

    import logging
    try:
        from audio_separator.separator import Separator
    except ImportError:
        from hypnomix.extras import hint
        sys.exit(f"stem separation: {hint('ml')}")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    sep = Separator(model_file_dir=str(MODEL_DIR), output_format="WAV", log_level=logging.WARNING)
    sep.load_model(model_filename=MODELS[a.model])

    for f in a.files:
        src = Path(f)
        dest = Path(a.out) / (src.stem if a.model == "4stem" else f"{src.stem} ({a.model})")
        dest.mkdir(parents=True, exist_ok=True)
        sep.output_dir = str(dest)
        if sep.model_instance:
            sep.model_instance.output_dir = str(dest)
        t = time.time()
        outs = sep.separate(str(src))
        names = []
        for o in outs:
            p = Path(o) if Path(o).is_absolute() else dest / o
            m = re.search(r"_\(([^)]+)\)_", p.name) or re.search(r"\(([^)]+)\)", p.name)
            new = dest / f"{(m.group(1) if m else p.stem).capitalize()}.wav"
            p.replace(new)
            names.append(new.stem)
        print(f"{src.name}: {', '.join(sorted(names))} → {dest}  ({time.time() - t:.0f}s)", file=sys.stderr)


if __name__ == "__main__":
    main()
