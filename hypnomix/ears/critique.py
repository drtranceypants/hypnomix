#!/usr/bin/env python3
"""Let a cloud AI model listen to a mix and give a producer's notes: a second opinion by ear.

Bring your own key, either of:
  Google Gemini   (aistudio.google.com; the free tier is enough for occasional listens)
  OpenRouter      (openrouter.ai; one key for Gemini and the other listening models, pay per use)
The key is the one saved in the app's Assistant settings (~/.hypnomix/ai.json), or GEMINI_API_KEY /
OPENROUTER_API_KEY.

What is sent: a reduced mono MP3 copy of the song (Gemini hears audio as 16 kHz mono anyway, so a full-quality
stereo upload only costs time), plus, when given, hypnomix's own measurements and scan review as text. The model's
ear covers arrangement, energy, balance, clarity and feel; its numbers do not (no LUFS, true peak, stereo width or
air above 8 kHz by ear), so it is told to take those from hypnomix's measurements.

Usage: hypnomix critique song.wav [--scan SCANDIR] [--measure song.json] [--profile PROFILE.md]
       [--question "is the vocal too far back in the chorus?"] [--provider gemini|openrouter] [--model M] [--out DIR]
Audio is billed at about 25 tokens per second: a 3½-minute song is about 5,000 tokens (around a cent on Flash).
"""
import argparse, base64, json, os, subprocess, sys, tempfile, urllib.request, warnings
from pathlib import Path

warnings.filterwarnings("ignore")

CONF = Path("~/.hypnomix/ai.json").expanduser()
TOKENS_PER_SECOND = 25                       # Gemini's audio rate
LISTENERS = {
    # id: label, address, default model, env var
    "openrouter": dict(label="OpenRouter", base_url="https://openrouter.ai/api/v1", model="google/gemini-3.8-flash",
                       env="OPENROUTER_API_KEY", keys_at="openrouter.ai"),
    "gemini": dict(label="Google Gemini", base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                   model="gemini-flash-latest", env="GEMINI_API_KEY", keys_at="aistudio.google.com"),
}

PROMPT = """You are an experienced mix engineer and music producer giving a second opinion on a song by an independent
artist who records real instruments and voices. Listen to the whole track. Be specific and give timestamps (mm:ss).

You hear a reduced MONO copy (about 16 kHz). So judge by ear: arrangement and energy arc (where attention sags),
the balance between parts, vocal and lead clarity and intelligibility, low-end feel (kick against bass, mud),
harshness in the mids, timing feel, performance and emotion. Do NOT judge by ear: stereo width or panning, air or
sibilance above about 8 kHz, exact loudness or peaks. For those use hypnomix's measurements below if given, and say
plainly when you have no information.

Keep the human feel: never suggest quantising or hard pitch correction. Prefer gentle, partial moves.
Finish with the three highest-impact changes, in priority order. Don't pad; skip praise unless it informs a decision."""


# ---------------------------------------------------------------- keys and models
def _conf():
    try:
        return json.loads(CONF.read_text())
    except (OSError, ValueError):
        return {}


def listener(provider=None, model=None):
    """(provider id, address, model, key) for listening: the app's Listening setting, else whichever key there is."""
    c = _conf()
    ls = c.get("listen") or {}
    keys = c.get("keys") or {}

    def key_for(p):
        return keys.get(p) or os.environ.get(LISTENERS[p]["env"], "")
    if not provider:
        want = ls.get("provider")
        if want in LISTENERS:
            provider = want
        elif c.get("provider") in LISTENERS and key_for(c["provider"]):
            provider = c["provider"]
        else:
            provider = next((p for p in LISTENERS if key_for(p)), "openrouter")
    if provider not in LISTENERS:
        raise ValueError(f"listening works with {' or '.join(LISTENERS)}, not {provider!r}")
    d = LISTENERS[provider]
    model = model or (ls.get("models") or {}).get(provider) or d["model"]
    return provider, d["base_url"], model, key_for(provider)


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise ValueError(f"can't read audio from {path}")


def openrouter_price(model):
    """$ per token (audio in, text out) from OpenRouter's public model list, or None."""
    try:
        with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=8) as r:
            for m in json.load(r)["data"]:
                if m["id"] == model:
                    p = m["pricing"]
                    return float(p.get("input_audio") or p.get("audio") or p["prompt"]), float(p["completion"])
    except Exception:
        return None
    return None


def estimate(path, provider, model):
    """What a listen will send and roughly cost, for the yes/no question before anything is uploaded."""
    secs = duration(path)
    tokens = int(secs * TOKENS_PER_SECOND) + 1500           # + the prompt and notes
    out = dict(seconds=round(secs, 1), tokens=tokens, cost=None)
    if provider == "openrouter":
        pr = openrouter_price(model)
        if pr:
            out["cost"] = round(tokens * pr[0] + 1500 * pr[1], 4)      # ~1,500 tokens of notes back
    return out


# ---------------------------------------------------------------- the listen itself
def context(scan=None, measure=None, profile=None):
    """hypnomix's own numbers and review, as text the model can lean on for what it can't hear."""
    parts = []
    if profile:
        parts.append("The artist's own style profile (judge against THIS, not generic taste):\n" + Path(profile).read_text()[:6000])
    if measure:
        parts.append("hypnomix measurements of this file (JSON):\n" + Path(measure).read_text()[:6000])
    if scan:
        rv = Path(scan) / "REVIEW.md"
        if rv.exists():
            parts.append("hypnomix's scan review of this song (what it already found; confirm, question or add to it):\n"
                         + rv.read_text(errors="replace")[:10000])
    return "\n\n".join(parts)


def listen(path, question="", notes="", provider=None, model=None):
    """Send a reduced copy of the song and the notes; return (text, usage dict)."""
    provider, base, model, key = listener(provider, model)
    if not key:
        d = LISTENERS[provider]
        raise ValueError(f"no {d['label']} key: save one in the app's Assistant settings, or set {d['env']} "
                         f"(get one at {d['keys_at']})")
    try:
        import openai
    except ImportError:
        raise ValueError("listening needs the optional extra: uv pip install 'hypnomix[critique]'")
    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / "listen.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "22050",
                        "-b:a", "64k", str(mp3)], check=True)
        data = base64.b64encode(mp3.read_bytes()).decode()
    prompt = PROMPT
    if question:
        prompt += "\n\nThe artist's question (answer it first):\n" + question
    if notes:
        prompt += "\n\n" + notes
    client = openai.OpenAI(api_key=key, base_url=base, max_retries=2, timeout=600)
    r = client.chat.completions.create(model=model, messages=[{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "input_audio", "input_audio": {"data": data, "format": "mp3"}}]}])
    u = getattr(r, "usage", None)
    usage = dict(provider=provider, model=model,
                 input=getattr(u, "prompt_tokens", 0) or 0, output=getattr(u, "completion_tokens", 0) or 0,
                 cost=getattr(u, "cost", None))                      # OpenRouter reports the real cost
    text = (r.choices[0].message.content or "").strip()
    if not text:
        raise ValueError(f"{LISTENERS[provider]['label']} sent back no notes (does {model} take audio?)")
    return text, usage


def main():
    ap = argparse.ArgumentParser(description="a cloud AI model listens to a mix and gives a producer's notes")
    ap.add_argument("file")
    ap.add_argument("--scan", help="a hypnomix scan folder for this song: its review goes along as text")
    ap.add_argument("--measure", help="hypnomix measure JSON for this file")
    ap.add_argument("--profile", help="your style profile (Markdown)")
    ap.add_argument("--question", default="", help="something specific to listen for")
    ap.add_argument("--provider", choices=list(LISTENERS), help="default: the app's Listening setting, else whichever key is set")
    ap.add_argument("--model", help="default: " + ", ".join(f"{d['model']} ({p})" for p, d in LISTENERS.items()))
    ap.add_argument("--estimate", action="store_true", help="only say what would be sent and roughly what it costs")
    ap.add_argument("--out")
    a = ap.parse_args()
    provider = a.provider or "openrouter"
    try:
        provider, _, model, _ = listener(a.provider, a.model)
        est = estimate(a.file, provider, model)
        cost = f", about ${est['cost']:.3f}" if est["cost"] is not None else ""
        print(f"{Path(a.file).name}: {est['seconds'] / 60:.1f} min of mono audio to {LISTENERS[provider]['label']} "
              f"({model}), ~{est['tokens']:,} tokens{cost}", file=sys.stderr)
        if a.estimate:
            return
        text, usage = listen(a.file, a.question, context(a.scan, a.measure, a.profile), provider, model)
    except (ValueError, subprocess.CalledProcessError) as e:
        sys.exit(str(e))
    except Exception as e:                       # the provider's own error, in one line
        sys.exit(f"{LISTENERS[provider]['label']}: {getattr(e, 'message', None) or e}")
    from hypnomix.core.paths import out_at
    outdir = out_at(a.out, "critique"); outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / (Path(a.file).stem + ".md")
    spent = f" · ${usage['cost']:.4f}" if usage.get("cost") else ""
    out.write_text(f"# Second opinion by ear: {Path(a.file).name}\n\n{LISTENERS[provider]['label']} · {model} · "
                   f"{usage['input']:,} tokens in, {usage['output']:,} out{spent}\n\n{text}\n")
    print(out)


if __name__ == "__main__":
    main()
