#!/usr/bin/env python3
"""Second opinion from Gemini: upload a (compressed copy of a) mix and ask for a producer critique.

Sends audio to Google's Gemini API using GEMINI_API_KEY. The upload is a 192 kbps MP3 copy.
Usage: hypnomix critique song.wav [--profile PROFILE.md]
       [--measure song.json] [--model gemini-pro-latest] [--out DIR]
"""
from hypnomix.core.paths import out_at
import argparse, os, subprocess, sys, tempfile, time, warnings
from pathlib import Path

warnings.filterwarnings("ignore")

PROMPT = """You are an experienced mix engineer and music producer giving a second opinion.
Listen to the whole track. Be specific and reference timestamps (mm:ss).
Cover: 1) arrangement and energy arc (intro/build/drop/breakdown/outro, where attention sags),
2) low end (kick/bass relationship, mud 200-500 Hz), 3) mids and vocal/lead clarity,
4) highs (harshness, sibilance, air), 5) stereo image and depth, 6) dynamics and loudness,
7) the three highest-impact changes, in priority order. Don't pad; skip praise unless it informs a decision."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file"); ap.add_argument("--profile"); ap.add_argument("--measure")
    ap.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-pro-latest"))
    ap.add_argument("--out"); a = ap.parse_args()
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is not set")

    try:
        from google import genai
    except ImportError:
        sys.exit("critique needs the optional extra: uv pip install 'hypnomix[critique]'")
    prompt = PROMPT
    if a.profile:
        prompt += "\n\nThe artist's own style profile (judge against THIS, not generic taste):\n" + Path(a.profile).read_text()
    if a.measure:
        prompt += "\n\nObjective measurements of this file (JSON):\n" + Path(a.measure).read_text()[:6000]

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / (Path(a.file).stem + ".mp3")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", a.file, "-b:a", "192k", str(mp3)], check=True)
        up = client.files.upload(file=str(mp3))
        while getattr(up.state, "name", str(up.state)) == "PROCESSING":
            time.sleep(2); up = client.files.get(name=up.name)
        resp = client.models.generate_content(model=a.model, contents=[up, prompt])
        try:
            client.files.delete(name=up.name)
        except Exception:
            pass
    from hypnomix.core.paths import out as _o
    outdir = out_at(a.out, "critique"); outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / (Path(a.file).stem + ".md")
    out.write_text(f"# Gemini second opinion — {Path(a.file).name}\n\nModel: {a.model}\n\n{resp.text}\n")
    print(out)


if __name__ == "__main__":
    main()
