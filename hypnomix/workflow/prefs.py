#!/usr/bin/env python3
"""Your preferences: how you like to work and what a finished song should be. Asked once, used by every scan.

  hypnomix prefs                          show what is saved (and what is still unanswered)
  hypnomix prefs questions                the first-run questions as JSON (for an AI agent to ask one by one)
  hypnomix prefs set KEY=VALUE [...]      save answers, e.g.  targets.lufs=-14  review.batch_low=yes
                                          lists take commas:  protect.tracks="Lead Vox,Strings"
  hypnomix prefs learn SCAN_DIR           after a review: count what you approved / skipped per kind of finding,
                                          so the next review can say "you usually skip these"

Saved in ~/.hypnomix/preferences.json (HYPNOMIX_HOME to change). Nothing is uploaded anywhere.

What the workflow does with them:
  targets.*        the loudness / true-peak target the mix check compares against
  protect.tracks   findings on these tracks are marked PROTECTED; `fix` refuses them without --allow-protected
  protect.notes    things never to change (shown at the top of every REVIEW.md)
  review.*         how the review is run (one at a time, which kinds may be batched, how much explanation)
  taste.*          tuning / timing strictness and free-text taste notes (shown to the reviewer; tools stay gentle
                   by default and only go further when you say so)
  tools.*          your DAW and the free plug-ins you have installed (proposals only name what you have)
  learned          approve / skip / change counts per finding kind from past reviews (advice, never auto-apply)
"""
import json, sys, time
from pathlib import Path

from hypnomix.core.paths import HOME

PREFS = HOME / "preferences.json"

QUESTIONS = [
    dict(key="tools.daw", ask="Which DAW do you work in?", options=["ableton", "logic", "protools", "reaper", "other"],
         default="ableton", why="decides whether fixes can be written into a project or are handed over as audio and a to-do list"),
    dict(key="targets.delivery", ask="Where will the music be released first?",
         options=["streaming", "video", "cd", "vinyl", "demo"], default="streaming",
         why="sets the loudness and peak targets the mix check uses"),
    dict(key="targets.lufs", ask="Loudness target (integrated LUFS)?", options=[-14, -16, -11, -9], default=-14,
         why="-14 suits streaming and video; louder masters get turned down by the platforms"),
    dict(key="targets.true_peak", ask="True-peak ceiling (dBTP)?", options=[-1.0, -2.0, -0.5], default=-1.0,
         why="lossy encodes (AAC, MP3) overshoot; -1 is the usual ceiling, -2 for very dense masters"),
    dict(key="review.style", ask="How should fixes be reviewed?",
         options=["one-at-a-time", "batch-low", "batch-by-kind"], default="one-at-a-time",
         why="high-severity and protected items are always asked one at a time"),
    dict(key="review.explain", ask="How much explanation with each fix?", options=["teach", "brief"], default="teach",
         why="teach = what the technique is and why; brief = just what and where"),
    dict(key="taste.tuning", ask="Vocal tuning?", options=["natural", "tight", "off"], default="natural",
         why="natural keeps vibrato and slides and only moves note centres; off = never propose tuning"),
    dict(key="taste.timing", ask="Timing?", options=["loose", "tight", "off"], default="loose",
         why="loose only fixes hits that stick out from the band's own feel"),
    dict(key="protect.tracks", ask="Any tracks that must never be changed without asking again? (names, commas)",
         options=None, default=[], why="findings on them are marked PROTECTED and `fix` refuses them by default"),
    dict(key="protect.notes", ask="Anything deliberate that might look like a mistake? (long reverb tails, a fade, "
         "a detuned part, loud delays…)", options=None, default=[],
         why="existing automation and effects are treated as your intent; this list is shown on every review"),
    dict(key="taste.notes", ask="Anything about your sound an engineer should know? (references, 'vocals up front', …)",
         options=None, default=[], why="taste calls are always asked; this just makes the first proposal closer"),
    dict(key="tools.plugins", ask="Which free plug-ins do you have installed? (names, commas; empty = stock only)",
         options=None, default=[], why="proposals only name devices you actually have"),
]
LISTS = {"protect.tracks", "protect.notes", "taste.notes", "tools.plugins"}


def load(path=None):
    p = Path(path or PREFS)
    return json.loads(p.read_text()) if p.exists() else {}


def get(prefs, key, default=None):
    cur = prefs
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def put(prefs, key, value):
    cur = prefs
    parts = key.split(".")
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def parse(key, raw):
    if key in LISTS:
        return [x.strip() for x in raw.split(",") if x.strip()]
    low = raw.strip().lower()
    if low in ("yes", "true", "no", "false"):
        return low in ("yes", "true")
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return raw.strip()


def save(prefs, path=None):
    p = Path(path or PREFS)
    p.parent.mkdir(parents=True, exist_ok=True)
    prefs["version"] = 1
    prefs["updated"] = time.strftime("%Y-%m-%d")
    p.write_text(json.dumps(prefs, indent=1))
    return p


def unanswered(prefs):
    return [q for q in QUESTIONS if get(prefs, q["key"]) is None]


def summary(prefs):
    """A few plain lines for the top of REVIEW.md (empty list if there are no preferences yet)."""
    if not prefs:
        return []
    L = []
    t = prefs.get("targets", {})
    if t:
        L.append(f"target: {t.get('lufs', -14)} LUFS, {t.get('true_peak', -1.0)} dBTP"
                 + (f" ({t['delivery']})" if t.get("delivery") else ""))
    r = prefs.get("review", {})
    if r:
        L.append(f"review: {r.get('style', 'one-at-a-time')}, explanations: {r.get('explain', 'teach')}")
    ta = prefs.get("taste", {})
    if ta:
        L.append(f"tuning: {ta.get('tuning', 'natural')}; timing: {ta.get('timing', 'loose')}"
                 + ("; " + "; ".join(ta["notes"]) if ta.get("notes") else ""))
    p = prefs.get("protect", {})
    if p.get("tracks"):
        L.append("PROTECTED tracks (ask again before any change): " + ", ".join(p["tracks"]))
    if p.get("notes"):
        L.append("deliberate, do not 'fix': " + "; ".join(p["notes"]))
    return L


def habit_key(f):
    return f"{f.get('tool')}/{f.get('kind')}/{f.get('severity')}"


def habit(prefs, f):
    """'approved 9 of 10 like this' from past reviews, or ''. Advice for the reviewer; never auto-applies."""
    h = (prefs.get("learned") or {}).get(habit_key(f))
    if not h:
        return ""
    n = sum(h.values())
    if n < 4:
        return ""
    top = max(h, key=h.get)
    word = {"approve": "approved", "skip": "skipped", "change": "changed"}.get(top, top)
    return f"in past reviews you {word} {h[top]} of {n} like this"


def learn(scan_dir, path=None):
    sd = Path(scan_dir)
    dec = json.loads((sd / "decisions.json").read_text()) if (sd / "decisions.json").exists() else {}
    if not dec:
        sys.exit(f"no decisions.json in {sd}: record decisions with `hypnomix fix {sd} --decide ID=approve|skip|change`")
    findings = {f["id"]: f for f in json.loads((sd / "findings.json").read_text())["findings"]}
    prefs = load(path)
    seen = prefs.setdefault("learned_from", [])
    tag = str(sd.resolve())
    if tag in seen:
        sys.exit("this review was already counted")
    learned = prefs.setdefault("learned", {})
    n = 0
    for fid, d in dec.items():
        f = findings.get(fid)
        what = d.get("decision") if isinstance(d, dict) else d
        if not f or what not in ("approve", "skip", "change"):
            continue
        row = learned.setdefault(habit_key(f), {})
        row[what] = row.get(what, 0) + 1
        n += 1
    seen.append(tag)
    save(prefs, path)
    print(f"counted {n} decisions into {path or PREFS}")
    for k, row in sorted(learned.items()):
        print(f"  {k:<34} " + ", ".join(f"{a} {b}" for a, b in sorted(row.items())))


def main():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__); return
    prefs = load()
    if not args or args[0] == "show":
        if not prefs:
            print(f"no preferences yet ({PREFS}).\nAsk the first-run questions: hypnomix prefs questions\n"
                  "then save the answers: hypnomix prefs set KEY=VALUE ...")
            return
        print(f"{PREFS}\n")
        for line in summary(prefs):
            print("  " + line)
        tl = prefs.get("tools", {})
        if tl:
            print(f"  DAW: {tl.get('daw', '?')}; free plug-ins: {', '.join(tl.get('plugins') or []) or 'stock only'}")
        if prefs.get("learned"):
            print("\n  learned from past reviews:")
            for k, row in sorted(prefs["learned"].items()):
                print(f"    {k:<34} " + ", ".join(f"{a} {b}" for a, b in sorted(row.items())))
        left = unanswered(prefs)
        if left:
            print("\n  not answered yet: " + ", ".join(q["key"] for q in left))
    elif args[0] == "questions":
        print(json.dumps([dict(q, current=get(prefs, q["key"])) for q in QUESTIONS], indent=1))
    elif args[0] == "set":
        known = {q["key"] for q in QUESTIONS}
        for item in args[1:]:
            if "=" not in item:
                sys.exit(f"expected KEY=VALUE, got {item!r}")
            k, v = item.split("=", 1)
            if k not in known and not k.startswith(("review.", "taste.", "targets.", "tools.", "protect.")):
                sys.exit(f"unknown key {k!r}; see `hypnomix prefs questions`")
            put(prefs, k, parse(k, v))
        print(f"saved {save(prefs)}")
    elif args[0] == "learn" and len(args) > 1:
        learn(args[1])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
