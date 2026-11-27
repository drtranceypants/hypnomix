#!/usr/bin/env python3
"""Your preferences: how you like to work and what a finished song should be. Asked once, used by every scan.

  hypnomix prefs                          show what is saved (and what is still unanswered)
  hypnomix prefs questions                the first-run questions as JSON (for an AI agent to ask one by one)
  hypnomix prefs set KEY=VALUE [...]      save answers, e.g.  targets.lufs=-14  review.style=batch-low
                                          lists take commas:  protect.tracks="Lead Vox,Strings"
  hypnomix prefs learn SCAN_DIR           after a review: count what you approved / skipped per kind of finding,
                                          so the next review can say "you usually skip these"

Saved in ~/.hypnomix/preferences.json (HYPNOMIX_HOME to change). Nothing is uploaded anywhere.
An answer that makes no sense is refused with the values that would work, e.g. targets.lufs=abc says the
target must be a number between -40 and -1; the file is only written when every answer in the command is good.
A key that is not one of the questions is refused too (`hypnomix prefs questions` lists them), with the nearest
key suggested, e.g. targets.lufz says "did you mean targets.lufs?"; review.name, taste.profile and tools.plugins_found
are also kept.

What the workflow does with them:
  targets.*        the loudness / true-peak target the mix check compares against
  protect.tracks   findings on these tracks are marked PROTECTED; `fix` refuses them without --allow-protected
  protect.notes    things never to change (shown at the top of every REVIEW.md)
  review.*         how the review is run. review.max_questions=N asks N items one by one and puts the rest in a
                   batch section (0 = ask everything); review.teach=on|off (why each technique, default on);
                   review.name=NAME (recorded with every decision). review.style and review.explain are read by
                   AI agents and the Assistant, who follow them when they run the review with you
  taste.*          tuning / timing strictness and free-text taste notes (shown to the reviewer; tools stay gentle
                   by default and only go further when you say so)
  tools.*          your DAW (live = Ableton Live, reaper = REAPER, ardour = HypnoMix Studio, or other; `hypnomix daw` is
                   accepted for ardour, which is only the stored word: the same choice as the app's Setup page, which is used
                   until you answer here) and the free plug-ins you have installed (proposals only name what you have)
  harmony.*        harmony.reference=average|lead|ask: what a vocal stack is lined up to by `vocalign`, `alignset`,
                   the Align device and the Align panel: the group's average timing (every part is nudged), or one
                   lead that is never moved. Unanswered (or `ask`): it is asked for every song, never assumed
  cleanup.*        the tidy steps of the first clean-up, all on by default: cleanup.order, cleanup.retire,
                   cleanup.consolidate (on or off)
  learned          approve / skip / change counts per finding kind from past reviews (advice, never auto-apply)
"""
import json, os, sys, time
from pathlib import Path

from hypnomix.core import atomic
from hypnomix.core.paths import HOME

PREFS = HOME / "preferences.json"

QUESTIONS = [
    dict(key="tools.daw", ask="Which DAW do you work in? (live = Ableton Live, reaper = REAPER, ardour = HypnoMix Studio, other)", options=["live", "reaper", "ardour", "other"],
         default="live", why="the same choice as the app's Setup page (until you answer here, Setup's answer is used); "
         "decides whether fixes can be written into a project or are handed over as audio and a to-do list"),
    dict(key="targets.delivery", ask="Where will the music be released first?",
         options=["streaming", "video", "cd", "vinyl", "demo"], default="streaming",
         why="read by AI agents and the Assistant (they see it in `hypnomix prefs`) to choose sensible targets for you; "
         "the numbers HypnoMix itself checks against are the two targets below"),
    dict(key="targets.lufs", ask="Loudness target (integrated LUFS)?", options=[-14, -16, -11, -9], default=-14,
         why="-14 suits streaming and video; louder masters get turned down by the platforms (any number from -40 to -1)"),
    dict(key="targets.true_peak", ask="True-peak ceiling (dBTP)?", options=[-1.0, -2.0, -0.5], default=-1.0,
         why="lossy encodes (AAC, MP3) overshoot; -1 is the usual ceiling, -2 for very dense masters (any number from -12 to 0)"),
    dict(key="review.style", ask="How should fixes be reviewed?",
         options=["one-at-a-time", "batch-low", "batch-by-kind"], default="one-at-a-time",
         why="read by AI agents and the Assistant, who follow it when they run the review with you; "
         "high-severity and protected items are always asked one at a time"),
    dict(key="review.explain", ask="How much explanation with each fix?", options=["teach", "brief"], default="teach",
         why="read by AI agents and the Assistant: teach = what the technique is and why; brief = just what and where "
         "(the review page's own explanations are switched with review.teach)"),
    dict(key="review.max_questions", ask="How many fixes should be asked one by one before the rest are batched?",
         options=[0, 3, 5, 8, 12], default=0,
         why="0 asks every fix one at a time. With a number, the most important fixes are asked one by one and the "
         "rest are grouped into a batch section you can approve or skip in a few clicks (high-severity and protected "
         "items are always asked)"),
    dict(key="taste.tuning", ask="Vocal tuning?", options=["natural", "tight", "off"], default="natural",
         why="natural keeps vibrato and slides and only moves note centres; off = never propose tuning"),
    dict(key="taste.timing", ask="Timing?", options=["loose", "tight", "off"], default="loose",
         why="loose only fixes hits that stick out from the band's own feel; off = never propose timing changes"),
    dict(key="harmony.reference", ask="When harmony parts are lined up in time, what should they line up to? "
         "(average = every part is nudged toward the group's average timing; lead = they follow one lead track that "
         "you name, and the lead is never moved; ask = ask me for every song)",
         options=["ask", "average", "lead"], default="ask",
         why="it changes which takes move: with average the lead moves a little too, with lead only the others do. "
         "Until you answer (and with ask) every alignment asks first; nothing is assumed. The amount and the "
         "largest move stay yours to set either way"),
    dict(key="cleanup.order", ask="In the first clean-up, put tracks in working order (drums, bass, keys/guitar/synth, "
         "vocals, other melodic; low to high) and vocal-stack parts on the track for their pitch?",
         options=["on", "off"], default="on",
         why="one fader per voice in a harmony stack, and every song laid out the same way; sound is unchanged"),
    dict(key="cleanup.retire", ask="In the first clean-up, retire tracks that are switched off (an archive copy of "
         "the set is kept first)?", options=["on", "off"], default="on",
         why="a set with dead tracks is harder to read; the sound is unchanged"),
    dict(key="cleanup.consolidate", ask="In the first clean-up, merge one instrument's matching tracks into one track "
         "when nothing overlaps?", options=["on", "off"], default="on",
         why="fewer tracks to mix; clips keep their timing and the sound is unchanged"),
    dict(key="protect.tracks", ask="Any tracks that must never be changed without asking again? (names, commas)",
         options=None, default=[], why="findings on them are marked PROTECTED and `fix` refuses them by default"),
    dict(key="protect.notes", ask="Anything deliberate that might look like a mistake? (long reverb tails, a fade, "
         "a detuned part, loud delays…)", options=None, default=[],
         why="existing automation and effects are treated as your intent; this list is shown on every review"),
    dict(key="taste.notes", ask="Anything about your sound an engineer should know? (references, 'vocals up front', …)",
         options=None, default=[], why="taste calls are always asked; this just makes the first proposal closer"),
    dict(key="tools.plugins", ask="Which free plug-ins do you have installed? (names, commas; empty = stock only; `hypnomix plugins --save` fills it in)",
         options=None, default=[], why="proposals only name devices you actually have"),
]
LISTS = {"protect.tracks", "protect.notes", "taste.notes", "tools.plugins"}


def load(path=None):
    p = Path(path or PREFS)
    d = atomic.load_json(p, {})                      # a cut-off file falls back to its .bak
    return d if isinstance(d, dict) else {}


def get(prefs, key, default=None):
    if key == "tools.daw":                           # one value, shared with the app's Setup page
        return daw(prefs) or default
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


# ---------------------------------------------------------------- the DAW: one choice, shared with Setup
DAW_IDS = ("live", "reaper", "ardour", "other")
_DAW_WORDS = {"live": "live", "ableton": "live", "ableton live": "live", "reaper": "reaper", "ardour": "ardour",
              "hypnomix": "ardour", "hypnomix daw": "ardour",       # HypnoMix Studio is built on Ardour: its sessions are Ardour sessions
              "other": "other", "logic": "other", "pro tools": "other", "protools": "other", "studio one": "other"}


def _daw_name(v):
    return _DAW_WORDS.get(str(v or "").strip().lower(), "")


def setup_daw(setup_path=None):
    """The DAW chosen on the app's Setup page (live, reaper, ardour, other), or "" when it was never chosen."""
    p = Path(setup_path) if setup_path else Path(os.environ.get("HYPNOMIX_HOME") or "~/.hypnomix").expanduser() / "setup.json"   # where setup.py keeps it
    try:
        return _daw_name(json.loads(p.read_text(encoding="utf-8")).get("daw"))
    except (OSError, ValueError, AttributeError):
        return ""


def daw(prefs=None, setup_path=None):
    """The person's DAW as one of live, reaper, ardour, other ("" when neither Preferences nor Setup has it).
    Preferences (tools.daw) win; when that is unanswered, the choice made in Setup is used, so the two never disagree.
    Older answers (ableton, logic, protools) are read as live / other."""
    if prefs is None:
        prefs = load()
    cur = prefs.get("tools") if isinstance(prefs, dict) else None
    mine = _daw_name(cur.get("daw")) if isinstance(cur, dict) else ""
    return mine or setup_daw(setup_path)


# ---------------------------------------------------------------- taste: tuning and timing strictness
_WANTS = {"tune": ("taste", "tuning", {"off": "off", "natural": "gentle", "tight": "tight"}),
          "timing": ("taste", "timing", {"off": "off", "loose": "gentle", "tight": "tight"})}
_WANTS["tuning"] = _WANTS["tune"]


def wants(kind, prefs=None):
    """How strict the person wants tuning ('tune') or timing ('timing') proposals to be:
    "off"      never propose them
    "gentle"   only the clear ones, keeping the player's feel (taste.tuning=natural, taste.timing=loose)
    "tight"    go further (taste.tuning=tight, taste.timing=tight)
    "default"  not answered: behave as before (the tools' own gentle settings)
    A scan marks (or leaves out) proposals of that kind accordingly; the person still approves each one."""
    if kind not in _WANTS:
        raise ValueError(f"wants() knows 'tune' and 'timing', not {kind!r}")
    group, name, table = _WANTS[kind]
    v = get(load() if prefs is None else prefs, f"{group}.{name}")
    if isinstance(v, bool):                          # `off` saved without quotes by an older version
        v = "on" if v else "off"
    return table.get(str(v).strip().lower(), "default") if v is not None else "default"


# ---------------------------------------------------------------- answers are checked when they are saved
class PrefError(ValueError):
    """An answer that does not fit its question. The message names what would work."""


NUMBERS = {   # key: (lowest, highest, integer only, example)
    "targets.lufs": (-40.0, -1.0, False, "-14"),
    "targets.true_peak": (-12.0, 0.0, False, "-1"),
    "review.max_questions": (0, 50, True, "5"),
}
ON_OFF = {"on": "on", "yes": "on", "true": "on", "1": "on", "off": "off", "no": "off", "false": "off", "0": "off"}
EXTRA_CHOICES = {"review.teach": ["on", "off"]}       # read by the code but not asked as first-run questions
EXTRA_KEYS = ("review.name", "taste.profile", "tools.plugins_found")   # read or written by the code, free-form, not asked


def known_keys():
    """Every key `prefs set` accepts: the questions, the choices read by the code, and the few free-form ones."""
    return sorted({q["key"] for q in QUESTIONS} | set(EXTRA_CHOICES) | set(EXTRA_KEYS))


def choices(key):
    """The allowed words for a choice question (None when the key takes anything or a number)."""
    for q in QUESTIONS:
        if q["key"] == key and q["options"] and all(isinstance(o, str) for o in q["options"]):
            return list(q["options"])
    return EXTRA_CHOICES.get(key)


def parse(key, raw):
    if key in LISTS:
        return [x.strip() for x in raw.split(",") if x.strip()]
    text = str(raw).strip()
    low = text.lower()
    if key in NUMBERS:
        lo, hi, whole, eg = NUMBERS[key]
        if key == "review.max_questions" and low in ("none", "no", "off", "all", ""):
            return 0                                 # no limit: ask everything one at a time
        try:
            v = float(text)
        except ValueError:
            v = float("nan")
        if v != v or not lo <= v <= hi or (whole and v != int(v)):
            kind = "a whole number" if whole else "a number"
            raise PrefError(f"{key} must be {kind} from {lo:g} to {hi:g} (for example {eg}); got {raw!r}")
        return int(v) if whole or ("." not in text and v == int(v)) else v
    opts = choices(key)
    if opts is not None:
        if key == "tools.daw":
            got = _daw_name(low)
        elif sorted(opts) == ["off", "on"]:
            got = ON_OFF.get(low, "")
        else:
            got = next((o for o in opts if o.lower() == low), "")
        if not got:
            more = " (ardour is the stored word for HypnoMix Studio; \"hypnomix daw\" works too)" if key == "tools.daw" else ""
            raise PrefError(f"{key} must be one of: {', '.join(opts)}{more}; got {raw!r}")
        return got
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
    atomic.write_json(p, prefs)
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
    dec = atomic.load_json(sd / "decisions.json", {}) or {}        # a cut-off file falls back to decisions.json.bak
    if not dec:
        if not (sd / "decisions.json").exists():
            sys.exit(f"no decisions.json in {sd}: record decisions with `hypnomix fix {sd} --decide ID=approve|skip|change`")
        if (sd / "decisions.json.corrupt").exists():        # load_json keeps a copy only when the file would not parse
            sys.exit(f"decisions.json in {sd} could not be read (the broken file is kept as decisions.json.corrupt); "
                     "nothing was counted")
        sys.exit(f"no decisions recorded yet in {sd}: nothing was counted")
    findings = {f["id"]: f for f in (atomic.load_json(sd / "findings.json", {}) or {}).get("findings", [])}
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
        if tl or daw(prefs):
            print(f"  DAW: {daw(prefs) or '?'}; free plug-ins: {', '.join(tl.get('plugins') or []) or 'stock only'}")
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
        known = known_keys()
        for item in args[1:]:
            if "=" not in item:
                sys.exit(f"expected KEY=VALUE, got {item!r}")
            k, v = item.split("=", 1)
            if k not in known:                       # a misspelt key used to be saved as junk and reported as saved
                import difflib
                near = difflib.get_close_matches(k, known, n=1, cutoff=0.6)
                if not near and "." in k:            # same section, nothing close: offer one of its keys
                    near = [x for x in known if x.split(".")[0] == k.split(".")[0]][:1]
                hint = f"did you mean {near[0]}? " if near else ""
                sys.exit(f"not saved: unknown key {k!r}; {hint}`hypnomix prefs questions` lists the keys")
            try:
                put(prefs, k, parse(k, v))
            except PrefError as e:
                sys.exit(f"not saved: {e}")
        print(f"saved {save(prefs)}")
    elif args[0] == "learn" and len(args) > 1:
        learn(args[1])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
