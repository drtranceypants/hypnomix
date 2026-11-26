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
       [--minutes N] [--again] [--yes] [--estimate]
--profile and --measure take a plain .md, .json or .txt file (not a hidden file, not in a hidden folder, under 1 MB);
--scan takes a hypnomix scan folder (one with findings.json or REVIEW.md): what they hold is sent to the service.
Audio is billed at about 25 tokens per second: a 3½-minute song is about 5,000 tokens (around a cent on Flash).

Nothing is uploaded without a yes. In a terminal the command first prints what it will send (the length, the model, the
estimated tokens and cost, where it goes) and asks y/N. Anywhere else (a script, an AI agent's shell) it refuses unless
--yes is passed: --yes is only for when the person has said yes to exactly this send. --estimate only prints, and sends
nothing. A song longer than 12 minutes is warned about (--estimate prints the warning too), and you choose the whole file or its
first minutes (--minutes N): an agent passes --minutes 12 unless the person chose the whole file.
The notes are kept (in the hypnomix home folder, cache/listen) for the same file, model, question and context: asking
again shows them for free, and --again listens afresh.
"""
import argparse, base64, hashlib, json, os, subprocess, sys, tempfile, time, urllib.parse, urllib.request, warnings
from pathlib import Path

from hypnomix.core import paths, prices

warnings.filterwarnings("ignore")

CONF = paths.HOME / "ai.json"                # follows HYPNOMIX_HOME like the rest of hypnomix
LEGACY_CONF = Path("~/.hypnomix/ai.json").expanduser()   # the default place: never readable or sendable either
TOKENS_PER_SECOND = 25                       # Gemini's audio rate
NOTES_TOKENS = 1500                          # the notes that come back (a thinking model also bills its reasoning: the cost can run higher)
LONG_MINUTES = 12                            # above this the person is warned and may send only the first minutes instead
CACHE_DIR = paths.HOME / "cache" / "listen"  # saved notes: the same song, model, question and context is never paid for twice
CACHE_KEEP = 200
# Defaults from a listening test (2026-11): the same 7½-minute song with known answers (tempo, when a line is first
# sung, when the guitars fade). Gemini 4 Carbon got all three; Neon, Hydrogen and 3.5 Flash got the tempo and the
# line but missed the guitars; 3.8 Flash, Argon and Pro (latest) got the tempo wrong. All undercounted a big vocal stack.
PICKS = [("gemini-4-carbon", "best ear in our test; slowest (a few minutes a song), about 5 cents"),
         ("gemini-4-hydrogen", "nearly as good, faster, about 3 cents"),
         ("gemini-3.5-flash", "quick (under a minute) and cheapest, about a cent")]
LISTENERS = {
    # id: label, address, default model, env var
    "gemini": dict(label="Google Gemini", base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                   model=PICKS[0][0], env="GEMINI_API_KEY", keys_at="aistudio.google.com/apikey",
                   picks=PICKS),
    "openrouter": dict(label="OpenRouter", base_url="https://openrouter.ai/api/v1", model="google/" + PICKS[0][0],
                       env="OPENROUTER_API_KEY", keys_at="openrouter.ai/keys",
                       picks=[("google/" + m, n) for m, n in PICKS]),
}
SKIP = ("tts", "image", "banana", "robotics", "computer-use", "transcribe", "embedding", "customtools", "live")

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
        return json.loads(CONF.read_text(encoding="utf-8"))
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
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise ValueError(f"can't read audio from {path}")


_OR = {"data": None, "failed": 0.0}


def openrouter_models():
    """OpenRouter's public model list, fetched once per session (a failed fetch is not retried for a minute), or None."""
    if _OR["data"] is None and time.time() - _OR["failed"] > 60:
        try:
            with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=8) as r:
                _OR["data"] = json.load(r)["data"]
        except Exception:
            _OR["failed"] = time.time()
    return _OR["data"]


def openrouter_price(model):
    """$ per token (audio in, text out) from OpenRouter's public model list, or None."""
    try:
        for m in openrouter_models() or []:
            if m["id"] == model:
                p = m["pricing"]
                return float(p.get("input_audio") or p.get("audio") or p["prompt"]), float(p["completion"])
    except Exception:
        return None
    return None


def audio_models(provider, key=None):
    """The models this key can send audio to, best-known first: Google's list for the key, or OpenRouter's public one."""
    picks = [m for m, _ in LISTENERS[provider]["picks"]]
    if provider == "gemini":
        key = key or listener("gemini")[3]
        if not key:
            raise ValueError("save a Google Gemini key first")
        req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                                     headers={"x-goog-api-key": key})
        with urllib.request.urlopen(req, timeout=15) as r:
            names = [m["name"].split("/", 1)[-1] for m in json.load(r).get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", [])]
        found = [n for n in names if n.startswith("gemini") and not any(s in n for s in SKIP)]
    else:
        with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=15) as r:
            found = [m["id"] for m in json.load(r)["data"]
                     if "audio" in (m.get("architecture") or {}).get("input_modalities", []) and ":" not in m["id"]
                     and not any(s in m["id"] for s in SKIP)]
    rest = sorted((n for n in found if n not in picks), key=lambda n: (not n.startswith(("gemini", "google/")), n))
    return [p for p in picks if p in found] + rest


def estimate(path, provider, model, context="", question="", seconds_limit=None):
    """What a listen will send and roughly cost, for the yes/no question before anything is uploaded. The text that goes
    with the audio (the prompt, the question, the review / measurements / profile in `context`) counts too. seconds_limit:
    only the first so many seconds are sent. The cost is an estimate (None when the price is not known)."""
    full = duration(path)
    secs = min(full, seconds_limit) if seconds_limit else full
    text_tokens = (len(PROMPT) + len(question or "") + len(context or "")) // 4
    tin = int(secs * TOKENS_PER_SECOND) + text_tokens
    out = dict(seconds=round(secs, 1), full_seconds=round(full, 1), tokens_in=tin, tokens_out=NOTES_TOKENS,
               tokens=tin + NOTES_TOKENS, context_tokens=text_tokens, cost=None, basis="")
    if provider == "openrouter":
        pr = openrouter_price(model)
        if pr:
            out["cost"] = round(tin * pr[0] + NOTES_TOKENS * pr[1], 4)
            out["basis"] = "OpenRouter's listed price for this model"
    elif provider == "gemini":
        out["cost"] = round(prices.gemini_cost(tin, NOTES_TOKENS), 4)
        out["basis"] = "Gemini Flash's paid-tier price; the free tier costs nothing"
    return out


def describe(est, provider, model, name, question=""):
    """One plain sentence for the yes/no question: what is sent, to whom, how many tokens, roughly what it costs."""
    d = LISTENERS[provider]
    cost = f", roughly ${est['cost']:.3f} (an estimate: {est['basis']}; a thinking model can cost more)" \
        if est.get("cost") is not None else ", cost unknown (see the service's price list)"
    ctx = f", with {est['context_tokens'] * 4:,} characters of hypnomix's text (the prompt and the review)" \
        if est.get("context_tokens") else ""
    cut = f" (the first {est['seconds'] / 60:.1f} of {est['full_seconds'] / 60:.1f} min)" \
        if est.get("full_seconds") and est["full_seconds"] - est["seconds"] > 1 else ""
    return (f"{name}: {est['seconds'] / 60:.1f} min of reduced mono audio{cut}{ctx}, to {d['label']} "
            f"({urllib.parse.urlsplit(d['base_url']).hostname}), model {model}{': ' + question if question else ''}. "
            f"About {est['tokens_in']:,} tokens in and {est['tokens_out']:,} back{cost}.")


def too_long(est):
    """True when the whole file is longer than LONG_MINUTES (the person is warned and may send only the first part)."""
    return est.get("full_seconds", 0) > LONG_MINUTES * 60


# ---------------------------------------------------------------- notes already heard
def fingerprint(path):
    """The song's identity without reading it all: its size and its first and last megabyte, hashed."""
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with open(p, "rb") as fh:
        if size <= 2 << 20:
            h.update(fh.read())
        else:
            h.update(fh.read(1 << 20))
            fh.seek(size - (1 << 20))
            h.update(fh.read())
    return h.hexdigest()


def cache_key(path, provider, model, question="", context="", seconds_limit=None):
    h = hashlib.sha256()
    for part in (fingerprint(path), provider, model, (question or "").strip(), hashlib.sha256((context or "").encode()).hexdigest(),
                 hashlib.sha256(PROMPT.encode()).hexdigest(), str(int(seconds_limit or 0))):
        h.update(part.encode() + b"\0")
    return h.hexdigest()[:40]


def cached(path, provider, model, question="", context="", seconds_limit=None):
    """The notes saved for this very listen (same file, model, question, context and length), or None."""
    try:
        d = json.loads((CACHE_DIR / (cache_key(path, provider, model, question, context, seconds_limit) + ".json")).read_text(encoding="utf-8"))
        return d if isinstance(d.get("notes"), str) and d["notes"].strip() else None
    except (OSError, ValueError):
        return None


def remember(path, provider, model, question, context, seconds_limit, notes, usage):
    try:
        key = cache_key(path, provider, model, question, context, seconds_limit)
        paths.private_dir(CACHE_DIR)
        paths.write_private(CACHE_DIR / (key + ".json"), json.dumps(
            dict(notes=notes, provider=provider, model=model, question=question or "", file=Path(path).name,
                 saved=time.strftime("%Y-%m-%d %H:%M"), usage={k: usage.get(k) for k in ("input", "output", "cost")}), indent=1))
        old = sorted(CACHE_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[CACHE_KEEP:]
        for f in old:
            f.unlink(missing_ok=True)
    except OSError:
        pass                                      # a saved copy is a convenience: never a reason to lose the notes


# ---------------------------------------------------------------- the listen itself
MAX_CONTEXT_FILE = 1_000_000                # bytes: a profile or a measurement is a few KB


def _same_file(a, b):
    """The same file under another name (a hard link)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _context_file(path, what):
    """Text of a profile / measurement file for the listener: a plain .md, .json or .txt file, not hidden and not
    in a hidden folder (~/.hypnomix holds your keys), and not huge. Anything else is refused with a plain message,
    because this text is sent to a cloud model."""
    p = Path(path).expanduser()
    shown = [p, p.resolve()]
    if not p.is_file():
        raise ValueError(f"{what}: {path} is not a file")
    if any(x.suffix.lower() not in (".md", ".json", ".txt") for x in shown):
        raise ValueError(f"{what} must be a .md, .json or .txt file: {p.name} is not")
    if any(part.startswith(".") and part not in (".", "..") for x in shown for part in x.parts):
        raise ValueError(f"{what}: {p.name} is hidden or in a hidden folder, so it is not sent to a cloud model; "
                         "copy it to a normal folder first if you mean it")
    if any(p.resolve() == c.expanduser().resolve() or _same_file(p, c) for c in (CONF, LEGACY_CONF)):
        raise ValueError(f"{what}: that file holds your saved keys")
    if p.stat().st_size > MAX_CONTEXT_FILE:
        raise ValueError(f"{what}: {p.name} is over {MAX_CONTEXT_FILE // 1_000_000} MB: use a smaller file")
    with open(p, errors="replace", encoding="utf-8") as fh:
        return fh.read(6000)


def _scan_review(scan):
    """REVIEW.md of a scan folder, or None. The folder must look like a scan (findings.json or REVIEW.md in it)."""
    d = Path(scan).expanduser()
    if not d.is_dir() or not ((d / "findings.json").is_file() or (d / "REVIEW.md").is_file()):
        raise ValueError(f"--scan: {scan} is not a hypnomix scan folder (it has no findings.json or REVIEW.md)")
    rv = d / "REVIEW.md"
    if not rv.is_file():
        return None
    if rv.resolve().parent != d.resolve() or rv.stat().st_size > MAX_CONTEXT_FILE:      # not a link out, not huge
        raise ValueError(f"--scan: {rv} is not a plain REVIEW.md of that folder")
    with open(rv, errors="replace", encoding="utf-8") as fh:
        return fh.read(10000)


def context(scan=None, measure=None, profile=None):
    """hypnomix's own numbers and review, as text the model can lean on for what it can't hear."""
    parts = []
    if profile:
        parts.append("The artist's own style profile (judge against THIS, not generic taste):\n"
                     + _context_file(profile, "--profile"))
    if measure:
        parts.append("hypnomix measurements of this file (JSON):\n" + _context_file(measure, "--measure"))
    if scan:
        review = _scan_review(scan)
        if review:
            parts.append("hypnomix's scan review of this song (what it already found; confirm, question or add to it):\n"
                         + review)
    return "\n\n".join(parts)


def listen(path, question="", notes="", provider=None, model=None, seconds_limit=None):
    """Send a reduced copy of the song (only its first seconds_limit seconds, when given) and the notes; return (text,
    usage dict). The notes are kept for the next time the same listen is asked for (see cached)."""
    provider, base, model, key = listener(provider, model)
    if not key:
        d = LISTENERS[provider]
        raise ValueError(f"no {d['label']} key: save one in the app's Assistant settings, or set {d['env']} "
                         f"(get one at {d['keys_at']})")
    try:
        import openai
    except ImportError:
        raise ValueError("listening needs the OpenAI client library: in the app, Setup, then Extras (the installers "
                         "include it); from source, run uv pip install -e \".[critique]\" in the hypnomix folder")
    with tempfile.TemporaryDirectory(prefix="hypnomix-work-") as td:
        mp3 = Path(td) / "listen.mp3"
        cut = ["-t", str(seconds_limit)] if seconds_limit else []
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "22050",
                        "-b:a", "64k", *cut, str(mp3)], check=True)
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
    remember(path, provider, model, question, notes, seconds_limit, text, usage)
    return text, usage


def _ask_cli(prompt):
    """A line from the person at the terminal ('' when there is none)."""
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return ""


def main():
    ap = argparse.ArgumentParser(description="a cloud AI model listens to a mix and gives a producer's notes. It asks "
                                 "before it uploads anything: y/N in a terminal, and --yes anywhere else",
                                 epilog="--yes is for when the person has said yes to exactly this send: an AI agent "
                                        "must ask them first.")
    ap.add_argument("file")
    ap.add_argument("--scan", help="a hypnomix scan folder for this song: its review goes along as text")
    ap.add_argument("--measure", help="hypnomix measure JSON for this file")
    ap.add_argument("--profile", help="your style profile (Markdown)")
    ap.add_argument("--question", default="", help="something specific to listen for")
    ap.add_argument("--provider", choices=list(LISTENERS), help="default: the app's Listening setting, else whichever key is set")
    ap.add_argument("--model", help="default: " + ", ".join(f"{d['model']} ({p})" for p, d in LISTENERS.items()))
    ap.add_argument("--estimate", action="store_true", help="only say what would be sent and roughly what it costs: nothing is sent")
    ap.add_argument("--yes", action="store_true", help="send without asking (for scripts). Only when the person has said "
                    "yes to exactly what --estimate shows")
    ap.add_argument("--minutes", type=float, help=f"send only the first N minutes (a song over {LONG_MINUTES} minutes is warned about)")
    ap.add_argument("--again", action="store_true", help="listen afresh even if notes for this same listen are saved")
    ap.add_argument("--out")
    a = ap.parse_args()
    provider = a.provider or "openrouter"
    try:
        if a.minutes is not None and a.minutes <= 0:
            raise ValueError("--minutes must be more than 0")
        provider, _, model, _ = listener(a.provider, a.model)
        notes = context(a.scan, a.measure, a.profile)                      # what goes along as text, checked first
        limit = a.minutes * 60 if a.minutes else None
        est = estimate(a.file, provider, model, notes, a.question, limit)
        name = Path(a.file).name
        print(describe(est, provider, model, name, a.question), file=sys.stderr)
        lookup = lambda lim: None if a.again else cached(a.file, provider, model, a.question, notes, lim)
        hit = lookup(limit)
        if a.estimate:
            if limit is None and too_long(est):
                est_cut = estimate(a.file, provider, model, notes, a.question, LONG_MINUTES * 60)
                print(f"WARNING: this is {est['full_seconds'] / 60:.0f} minutes, longer than {LONG_MINUTES}: the whole file is "
                      f"about {est['tokens']:,} tokens; its first {LONG_MINUTES} minutes would be {est_cut['tokens']:,}. "
                      f"Ask the person which they want: pass --minutes {LONG_MINUTES} unless they chose the whole file.",
                      file=sys.stderr)
            if hit:
                print("Already heard with this model and question: the saved notes would be shown, free.", file=sys.stderr)
            return
        if not hit:
            terminal = sys.stdin.isatty() and sys.stderr.isatty()
            said_yes = a.yes
            if limit is None and too_long(est):
                est_cut = estimate(a.file, provider, model, notes, a.question, LONG_MINUTES * 60)
                print(f"WARNING: this is {est['full_seconds'] / 60:.0f} minutes, longer than {LONG_MINUTES}: the whole file is "
                      f"about {est['tokens']:,} tokens; its first {LONG_MINUTES} minutes would be {est_cut['tokens']:,}.",
                      file=sys.stderr)
                if not a.yes:
                    if not terminal:
                        sys.exit("nothing was sent: this is not a terminal, so there is no one to ask. Run it in a terminal "
                                 "and answer, or pass --yes (or --minutes N) once the person has said yes to this.")
                    r = _ask_cli("Send the [w]hole file, only the [f]irst %d minutes, or [n]othing? " % LONG_MINUTES)
                    if r.startswith("f"):
                        limit, est = LONG_MINUTES * 60, est_cut
                        hit = lookup(limit)
                    elif not r.startswith("w"):
                        sys.exit("nothing was sent")
                    said_yes = True                                       # that answer was the yes
            if not hit and not said_yes:
                if not terminal:
                    sys.exit("nothing was sent: this is not a terminal, so there is no one to ask. Run it in a terminal and "
                             "answer y, or pass --yes once the person has said yes to what is printed above. "
                             "(--estimate only prints.)")
                if not _ask_cli("Send this? [y/N] ").startswith("y"):
                    sys.exit("nothing was sent")
        if hit:
            print("Already heard with this model and question: showing the saved notes (free). --again listens again.",
                  file=sys.stderr)
            text, usage = hit["notes"], dict(hit.get("usage") or {}, cached=True)
        else:
            text, usage = listen(a.file, a.question, notes, provider, model, limit)
    except (ValueError, subprocess.CalledProcessError) as e:
        sys.exit(str(e))
    except Exception as e:                       # the provider's own error, in one line
        sys.exit(f"{LISTENERS[provider]['label']}: {getattr(e, 'message', None) or e}")
    from hypnomix.core.paths import out_at
    outdir = out_at(a.out, "critique"); outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / (Path(a.file).stem + ".md")
    spent = f" · ${usage['cost']:.4f}" if usage.get("cost") else ""
    tokens = "saved notes, nothing sent" if usage.get("cached") else f"{usage.get('input') or 0:,} tokens in, {usage.get('output') or 0:,} out"
    out.write_text(f"# Second opinion by ear: {Path(a.file).name}\n\n{LISTENERS[provider]['label']} · {model} · "
                   f"{tokens}{spent}\n\n{text}\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
