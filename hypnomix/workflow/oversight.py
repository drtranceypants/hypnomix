"""Human oversight for the review: how much of each fix, grouped decisions, a question budget, who decided what,
collaborators' notes, and the "you usually / common practice / confidence" lines on every finding.

Used by `fix` (--decide ID=approve@60, --decide-like, --as), `review` (the page, --export, --merge) and `scan`
(REVIEW.md). Nothing here changes a set: it reads and writes the scan folder's decisions.json and
review-notes.json only (blend() writes a NEW set and is called by `fix`).

decisions.json, one entry per finding id (every field but `decision` is optional, so older files still read):

  {"decision": "approve" | "skip" | "change",
   "note":     "the person's words",
   "at":       "YYYY-MM-DD HH:MM",
   "amount":   0-100        how much of the proposed move (default 100; only for kinds that can scale)
   "by":       "name"       who decided (prefs review.name, or --as NAME)
   "via":      "like:ID"    recorded by a grouped decision made on finding ID (an individual decision wins)
   "conflicts": [{"by", "decision", "amount", "note", "at"}]   a collaborator disagreed (see review --merge)}

review-notes.json: {id: [{"by", "at", "text", "bar" | "sec"}]}: timestamped notes from reviewers, kept apart from
the decisions so a note never counts as a decision.
"""
import gzip, json, math, re, time
from hypnomix.core.gz import read_gz
import xml.etree.ElementTree as ET
from pathlib import Path

from hypnomix.core.paths import HOME

DECISIONS = ("approve", "skip", "change")
SEV = {"high": 0, "medium": 1, "low": 2, "info": 3}
NOTES_FILE = "review-notes.json"


# ---------------------------------------------------------------- amount
# tool -> how an amount is applied: ("flags", fn(p) -> extra CLI args), ("blend", why) = every number the tool
# changed in the set is moved only p of the way from the old value, or (None, why) = it can't be scaled
SCALING = {
    "smooth": ("flags", lambda p: ["--amount", f"{max(0.01, 0.5 * p):.4f}", "--fade-ms", f"{max(1.0, 5.0 * p):.2f}"]),
    "timing": ("flags", lambda p: ["--strength", f"{p:.4f}"]),
    "duck": ("flags", lambda p: ["--depth", f"{max(0.1, 3.0 * p):.3f}"]),
    "masking": ("flags", lambda p: ["--scale", f"{max(0.01, p):.4f}"]),
    "tune": ("flags", lambda p: ["--amount", f"{0.35 * p:.4f}"]),
    "distortion": ("blend", "each parameter moves this share of the way toward the proposed value"),
    "devices": ("blend", "each setting moves this share of the way toward the proposed value"),
    "sidechain": ("blend", "each setting moves this share of the way toward the proposed value"),
    "cliplevel": ("blend", "the clip-gain raise is scaled (in dB)"),
    "edges": ("blend", "fade lengths and edge moves are scaled"),
}
NO_SCALE = {
    "name": "a rename is all or nothing", "order": "track order is all or nothing", "tidy": "retiring or merging "
    "tracks is all or nothing", "motion": "set the depth in the note instead (depth=, dB=, bars=)", "borrow": "a borrowed "
    "loop is added or not", "colour": "set the strength in the note instead (amount=0.3)", "voices": "set the dB steps in the note instead", "refs": "a missing file is found or not",
}


def scalable(f):
    """(True, how) or (False, why) for a finding."""
    tool = f.get("tool")
    if f.get("plan"):
        return False, "a planned move runs as the tool planned it (change its settings in the plan instead)"
    if f.get("run"):
        return False, "this repair runs as one command"
    s = SCALING.get(tool)
    if s:
        return True, ("fine control: " + s[1]) if s[0] == "blend" else "the tool's own strength control"
    return False, NO_SCALE.get(tool, "this kind of fix has no partial version")


def parse_decision(text):
    """'approve@60' -> ('approve', 60); 'skip' -> ('skip', None). Raises ValueError."""
    text = text.strip()
    amt = None
    if "@" in text:
        text, a = text.split("@", 1)
        a = a.strip().rstrip("%")
        try:
            amt = float(a)
        except ValueError:
            raise ValueError(f"amount must be a number from 0 to 100 (got {a!r})")
        if not 0 <= amt <= 100:
            raise ValueError(f"amount must be from 0 to 100 (got {amt:g})")
        amt = int(round(amt))
    text = text.strip()
    if text not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)} (got {text!r})")
    return text, amt


def amount_of(entry):
    """0-100 for a decisions.json entry (default 100)."""
    if isinstance(entry, dict) and entry.get("amount") is not None:
        try:
            return max(0, min(100, int(round(float(entry["amount"])))))
        except (TypeError, ValueError):
            return 100
    return 100


def effective_amount(f, entry):
    """What fix applies: kinds that can't scale treat any amount above 0 as 100."""
    a = amount_of(entry)
    if a == 0:
        return 0
    return a if scalable(f)[0] else 100


def amount_flags(tool, amount):
    s = SCALING.get(tool)
    if not s or s[0] != "flags" or amount >= 100:
        return []
    return s[1](amount / 100.0)


GAIN_WORDS = ("volume", "send", "gain", "threshold", "ceiling", "output", "makeup")
NO_BLEND = {"PointeeId", "NextPointeeId", "LomId", "LomIdView", "Id", "ParameterId", "SelectedDevice", "Numerator",
            "Denominator", "ModulationTarget", "MidiCCOnOffThresholds"}


def _num(s):
    try:
        x = float(s)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _is_int(s):
    return re.fullmatch(r"-?\d+", str(s or "")) is not None


def blend_trees(old_root, new_root, p):
    """Move every numeric Value the tool changed only p (0-1) of the way from old to new, in place on new_root.
    Gain-like values (volume, sends, clip gain, thresholds) are blended in dB; small whole-number changes (switches,
    modes) are not blended. Returns (scaled, kept_full) counts; kept_full includes elements the tool added."""
    scaled = kept = 0

    def key_list(el):
        seen, out = {}, []
        for c in el:
            k = (c.tag, c.get("Id"))
            seen[k] = seen.get(k, -1) + 1
            out.append((k, seen[k], c))
        return out

    def walk(o, n, path):
        nonlocal scaled, kept
        vo, vn = o.get("Value"), n.get("Value")
        if vo is not None and vn is not None and vo != vn and n.tag not in NO_BLEND:
            a, b = _num(vo), _num(vn)
            if a is None or b is None:
                kept += 1
            elif _is_int(vo) and _is_int(vn) and abs(a - b) <= 3:
                kept += 1                                       # a switch or a mode: all or nothing
            else:
                gainy = n.tag == "SampleVolume" or any(w in path.lower() for w in GAIN_WORDS)
                if gainy and a > 0 and b > 0:
                    v = a * (b / a) ** p                          # p of the way in dB
                else:
                    v = a + (b - a) * p
                n.set("Value", f"{v:.9g}")
                scaled += 1
        oc = {(k, i): c for k, i, c in key_list(o)}
        for k, i, c in key_list(n):
            m = oc.get((k, i))
            if m is None:
                kept += 1                                       # added by the tool: kept as written
            else:
                walk(m, c, path + "/" + c.tag)

    walk(old_root, new_root, new_root.tag)
    return scaled, kept


def blend(old_als, new_als, out_als, p):
    """Write out_als = new_als with the changes from old_als scaled by p. Returns (scaled, kept_full)."""
    old = ET.fromstring(read_gz(old_als))
    new = ET.fromstring(read_gz(new_als))
    s, k = blend_trees(old, new, p)
    from hypnomix.session import liveversion as LV
    LV.guard_write(new)                # refuses a set saved by a Live newer than the newest tested
    with gzip.open(out_als, "wb") as fh:
        fh.write(b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(new, encoding="utf-8"))
    return s, k


# ---------------------------------------------------------------- recording decisions
def now():
    return time.strftime("%Y-%m-%d %H:%M")


def reviewer(name=None):
    """--as NAME, else prefs review.name, else 'owner'."""
    if name:
        return str(name).strip()[:60]
    from hypnomix.workflow import prefs as P
    return str(P.get(P.load(), "review.name") or "owner")[:60]


def load_decisions(sd):
    from hypnomix.core import atomic
    return atomic.load_json(Path(sd) / "decisions.json", {})       # a cut-off file falls back to decisions.json.bak


def load_findings_doc(sd):
    """findings.json as a dict. A cut-off file falls back to findings.json.bak; with neither, FileNotFoundError."""
    from hypnomix.core import atomic
    doc = atomic.load_json(Path(sd) / "findings.json", None)
    if not isinstance(doc, dict):
        raise FileNotFoundError(f"no readable findings.json in {sd} (scan first: hypnomix scan SET)")
    return doc


def save_decisions(sd, dec):
    from hypnomix.core import atomic
    atomic.write_json(Path(sd) / "decisions.json", dec)             # whole or not at all; the last good one is kept


# ---------------------------------------------------------------- "approve all low": what a bulk approve may take
TASTE_TOOLS = ("tune", "voices", "motion", "colour", "borrow", "variations")     # taste calls: always decided one at a time
TIDY_TOOLS = ("order", "tidy")                                                  # reorder, remove, merge: structure, not sound
TIDY_KINDS = ("track-order", "retire-off", "consolidate", "vocal-stack")


def is_taste_call(f):
    """A finding that is a matter of taste: the tools that always ask, or anything the finding itself marks as taste."""
    return (f.get("tool") in TASTE_TOOLS or bool(f.get("taste")) or str(f.get("kind") or "") == "taste"
            or str(f.get("applies") or "") == "answer")


def bulk_class(f):
    """Where a finding stands for "Approve all low" (the decision is not looked at): None when it is not a candidate at all
    (not low, or only information or a question), "ok" when a bulk approve may take it, else why it is left out:
    "tidy" (a reorder, removal or merge, also when it is on by default), "taste", "protected" or "by_hand"."""
    ap = f.get("applies_here") or f.get("applies")
    if f.get("severity") != "low" or ap in ("info", "answer", None):
        return None
    if f.get("default") == "approve" or f.get("tool") in TIDY_TOOLS or f.get("kind") in TIDY_KINDS:
        return "tidy"
    if is_taste_call(f):
        return "taste"
    if f.get("protected"):
        return "protected"
    if ap in ("manual", "blocked"):
        return "by_hand"
    return "ok"


def bulk_low(findings, dec):
    """(the findings "Approve all low" may approve, {why: how many it leaves out}). Never a taste call (tuning, harmony
    balance, motion, colour, borrowed moves, variations), a tidy step (reordering, removing or merging tracks: on by
    default or not), a protected track, a by-hand item, or anything already decided. The list is always shown before
    anything is recorded."""
    ok, out = [], dict(taste=0, tidy=0, protected=0, by_hand=0)
    for f in findings:
        c = bulk_class(f)
        if c is None or decision_of(dec, f.get("id")):
            continue
        if c == "ok":
            ok.append(f)
        else:
            out[c] += 1
    return ok, out


def decision_of(dec, fid):
    d = dec.get(fid)
    return d.get("decision") if isinstance(d, dict) else d


def entry(decision, note="", amount=None, by=None, via=None):
    e = {"decision": decision, "note": str(note or "")[:500], "at": now(), "by": reviewer(by)}
    if amount is not None and decision != "skip":
        e["amount"] = int(amount)
    if via:
        e["via"] = via
    return e


# ---------------------------------------------------------------- size, role, grouped decisions
UNIT = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*(dBFS|dBTP|dB|LU|ms|cents|c\b|%)")


def size(f):
    """One number for how big a finding is (dB, ms, cents...), or None."""
    for k in ("size", "expect_db", "over_db", "off_ms", "cents", "db"):
        v = f.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return abs(float(v))
    m = UNIT.search(str(f.get("problem") or ""))
    return abs(float(m.group(1))) if m else None


def roles(sd):
    nj = Path(sd) / "raw" / "names" / "names.json"
    if not nj.exists():
        return {}
    try:
        rows = json.loads(nj.read_text()).get("tracks", [])
    except Exception:
        return {}
    return {r.get("old"): str(r.get("final") or r.get("label") or "").split(" ")[0] for r in rows}


PER_TRACK = {"smooth", "timing", "edges", "cliplevel", "tune", "distortion", "devices", "dehiss", "vocalign", "recording"}


def like(findings, dec, example, band=0.5, role_of=None):
    """Undecided findings like `example`: same tool and kind, same track role (for per-track kinds, when roles are
    known), size within +-band (a share) of the example's. Never includes protected or high-severity items when the
    example isn't one, and never 'info' / 'answer' items."""
    role_of = role_of or {}
    s0 = size(example)
    r0 = role_of.get(example.get("track"))
    out = []
    for f in findings:
        if f["id"] == example["id"] or f["id"] in dec and decision_of(dec, f["id"]):
            continue
        if (f.get("tool"), f.get("kind")) != (example.get("tool"), example.get("kind")):
            continue
        if f.get("applies") in ("info", "answer") or f.get("applies") != example.get("applies"):
            continue
        if f.get("protected") and not example.get("protected"):
            continue
        if f.get("severity") == "high" and example.get("severity") != "high":
            continue
        if example.get("tool") in PER_TRACK and r0 and role_of.get(f.get("track")) not in (None, r0):
            continue
        s = size(f)
        if s0 is not None and s is not None:
            lo, hi = s0 * (1 - band), s0 * (1 + band)
            if not lo - 1e-9 <= s <= hi + 1e-9:
                continue
        elif s0 is not None or s is not None:
            continue
        out.append(f)
    return out


# ---------------------------------------------------------------- confidence, "you usually", common practice
KIND_CONF = {  # how sure the tool usually is, when it gives no number of its own
    ("smooth", "click"): 0.85, ("smooth", "cut"): 0.7, ("smooth", "spike"): 0.65, ("smooth", "step"): 0.5,
    ("timing", None): 0.7, ("tune", None): 0.6, ("distortion", None): 0.65, ("devices", None): 0.55,
    ("sidechain", None): 0.55, ("duck", None): 0.5, ("edges", None): 0.6, ("cliplevel", None): 0.55,
    ("dehiss", None): 0.5, ("vocalign", None): 0.6, ("masking", None): 0.45, ("align", None): 0.7,
    ("name", "track-name"): 0.75, ("name", "track-name-question"): 0.35, ("order", None): 0.8, ("tidy", None): 0.8,
    ("measure", None): 0.95, ("qc", None): 0.95, ("refs", None): 0.99, ("key", None): 0.5, ("voices", None): 0.5,
    ("sections", None): 0.5, ("match", None): 0.5, ("motion", None): 0.4, ("borrow", None): 0.4, ("colour", None): 0.35,
    ("intent", None): 0.3, ("structure", None): 0.9,
    ("profile", None): 0.45,
}


def confidence(f):
    """(0-1, source) from the tool's own measurement where it has one, else a per-kind default."""
    for k in ("confidence", "conf"):
        v = f.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return round(max(0.0, min(1.0, float(v))), 2), "measured"
    if isinstance(f.get("sure"), bool):
        return (0.85 if f["sure"] else 0.5), "measured"
    if isinstance(f.get("recommended"), bool):
        return (0.8 if f["recommended"] else 0.45), "measured"
    if f.get("optional"):
        return 0.4, "measured"
    if f.get("tool") == "tune" and f.get("flagged_notes") is not None:
        n = len(f.get("flagged_notes") or [])
        return round(min(0.9, 0.4 + 0.02 * n), 2), "measured"
    v = KIND_CONF.get((f.get("tool"), f.get("kind")), KIND_CONF.get((f.get("tool"), None)))
    return (v if v is not None else 0.5), "default for this kind"


def _load_json(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def taste_profile(home=None):
    d = _load_json(Path(home or HOME) / "taste.json")
    return (d or {}).get("profile") or {}


def library(home=None):
    return _load_json(Path(home or HOME) / "library.json") or {}


def _range(x, unit):
    if not isinstance(x, dict) or x.get("median") is None:
        return None
    return f"{x['median']:+g}{unit} (your songs from {x.get('low', x['median']):+g} to {x.get('high', x['median']):+g}{unit})"


def _role_key(label):
    label = (label or "").lower()
    for k, words in (("drums", ("drum", "kick", "snare", "hat", "perc")), ("bass", ("bass",)),
                     ("harmony", ("harmony", "backing")), ("lead", ("lead vocal",)),
                     ("keys/guitar/synth", ("keys", "guitar", "synth", "piano", "organ", "pad", "pluck"))):
        if any(w in label for w in words):
            return k
    return None


def usually(f, home=None, prefs=None, role=None):
    """'you usually …' for a finding, from your past reviews (preferences), taste.json (your finished songs) and
    library.json when present. '' when there is nothing to say."""
    from hypnomix.workflow import prefs as P
    bits = []
    try:
        h = P.habit(prefs if prefs is not None else P.load(), f)
    except Exception:
        h = ""
    if h:
        bits.append(h)
    lib = library(home)
    key = f"{f.get('tool')}/{f.get('kind')}"
    hit = None
    for where in (lib.get("kinds") if isinstance(lib.get("kinds"), dict) else {}, lib.get("habits") if
                  isinstance(lib.get("habits"), dict) else {}, lib):
        if isinstance(where, dict) and (key in where or f.get("kind") in where):
            hit = where.get(key, where.get(f.get("kind")))
            break
    if isinstance(hit, str):
        bits.append(hit)
    elif isinstance(hit, dict):
        if isinstance(hit.get("usually"), str):
            bits.append(hit["usually"])
        else:
            counts = {k: v for k, v in hit.items() if k in DECISIONS and isinstance(v, (int, float))}
            if sum(counts.values()) >= 3:
                top = max(counts, key=counts.get)
                word = {"approve": "approved", "skip": "skipped", "change": "changed"}[top]
                bits.append(f"in your library you {word} {int(counts[top])} of {int(sum(counts.values()))} like this")
    prof = taste_profile(home)
    if prof:
        tool, kind = f.get("tool"), f.get("kind")
        rk = _role_key(role)
        line = None
        if tool == "voices" and isinstance(prof.get("harmonies"), dict) and prof["harmonies"].get("lead_margin") is not None:
            line = f"your harmonies sit about {prof['harmonies']['lead_margin']:g} dB under the lead in your finished songs"
        elif tool == "cliplevel" and isinstance(prof.get("level_vs_lead"), dict):
            r = _range(prof["level_vs_lead"].get("harmony"), " dB")
            line = r and f"your harmony faders sit {r} against the lead"
        elif tool == "duck" and isinstance(prof.get("reverb_send_db"), dict):
            r = _range(prof["reverb_send_db"].get("lead") or prof["reverb_send_db"].get("harmony"), " dB")
            line = r and f"your vocal reverb send is usually {r}"
        elif tool == "vocalign" and prof.get("harmony_timing_ms"):
            r = prof["harmony_timing_ms"]
            if isinstance(r, dict) and r.get("median") is not None:
                line = f"your finished songs keep harmonies about {r['median']:g} ms from the lead"
        elif tool == "intent" and "panned" in str(f.get("problem")) and isinstance(prof.get("hard_panned"), dict):
            r = _range(prof["hard_panned"].get(rk or "strings/other"), "")
            line = r and f"hard-panned tracks of this kind per song: {r}"
        elif tool in ("devices", "distortion") and kind in ("compressor", "limiter", "gate", "eq-lowcut") and \
                isinstance(prof.get("chains"), dict) and rk and prof["chains"].get(rk):
            line = "on " + rk + " you usually use: " + ", ".join(f"{d} ({n} songs)" for d, n in prof["chains"][rk][:4])
        if line:
            bits.append(line)
    return "; ".join(bits)


# ---------------------------------------------------------------- question budget
def budget(findings, max_questions):
    """Split findings into (ask, batch, info): `ask` are the questions within the budget (most severe first; high
    severity, protected and question items are always asked), `batch` the rest of the decisions, `info` measurements.
    max_questions None or <= 0 = no budget (everything is asked)."""
    order = sorted(findings, key=lambda f: (SEV.get(f.get("severity"), 9), -confidence(f)[0], f.get("n", 0)))
    info = [f for f in order if f.get("applies") == "info"]
    acts = [f for f in order if f.get("applies") != "info"]
    try:
        mq = int(max_questions) if max_questions not in (None, "", "none") else None
    except (TypeError, ValueError):
        mq = None
    if not mq or mq <= 0:
        return acts, [], info
    must = [f for f in acts if f.get("severity") == "high" or f.get("protected") or f.get("applies") == "answer"]
    rest = [f for f in acts if f not in must]
    room = max(0, mq - len(must))
    ask_ids = {f["id"] for f in must} | {f["id"] for f in rest[:room]}
    return [f for f in acts if f["id"] in ask_ids], [f for f in acts if f["id"] not in ask_ids], info


def batch_suggestions(batch, prefs=None, role_of=None):
    """Grouped decisions for the batch section: [{example, decision, ids, why}] (one per tool/kind/role)."""
    from hypnomix.workflow import prefs as P
    prefs = prefs if prefs is not None else P.load()
    role_of = role_of or {}
    groups = {}
    for f in batch:
        r = role_of.get(f.get("track")) if f.get("tool") in PER_TRACK else None
        groups.setdefault((f.get("tool"), f.get("kind"), r), []).append(f)
    out = []
    for (tool, kind, r), fs in groups.items():
        ex = fs[0]
        h = P.habit(prefs, ex)
        if "skipped" in h:
            d, why = "skip", h
        elif "changed" in h:
            d, why = "change", h
        elif ex.get("applies") in ("set", "audio") and confidence(ex)[0] >= 0.6:
            d, why = "approve", h or f"confidence {confidence(ex)[0]:.0%}, low severity"
        else:
            d, why = "skip", h or "low confidence: listen to one before approving the group"
        out.append(dict(example=ex["id"], decision=d, ids=[f["id"] for f in fs], tool=tool, kind=kind, role=r or "",
                        why=why))
    return out


# ---------------------------------------------------------------- notes and collaborators
def load_notes(sd):
    p = Path(sd) / NOTES_FILE
    return json.loads(p.read_text()) if p.exists() else {}


def parse_stamp(s):
    """'33', 'bar 33', '33.2', '33.2.50' -> {'bar': '33.2'}; '1:23.5', '83.5s', '83s' -> {'sec': 83.5}; '' -> {}."""
    s = str(s or "").strip().lower()
    if not s:
        return {}
    m = re.fullmatch(r"(?:bar\s*)?(\d+(?:\.\d+){0,2})", s)
    if m:
        return {"bar": m.group(1)}
    m = re.fullmatch(r"(?:(\d+):)?(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?", s)
    if m and (m.group(1) or s.endswith(("s", "sec", "seconds"))):
        return {"sec": round((int(m.group(1)) * 60 if m.group(1) else 0) + float(m.group(2)), 2)}
    raise ValueError(f"timestamp must be a bar (33 or 33.2) or seconds (1:23.5 or 83.5s): {s!r}")


def add_note(sd, fid, text, at=None, by=None):
    """A reviewer's note on a finding, at a bar ("33.2") or a time ("1:23.5", "83.5s")."""
    ids = {f["id"] for f in load_findings_doc(sd)["findings"]}
    if fid not in ids:
        raise ValueError(f"unknown id: {fid}")
    if not str(text or "").strip():
        raise ValueError("empty note")
    notes = load_notes(sd)
    row = {"by": reviewer(by), "at": now(), "text": str(text)[:1000]}
    row.update(parse_stamp(at))
    notes.setdefault(fid, []).append(row)
    (Path(sd) / NOTES_FILE).write_text(json.dumps(notes, indent=1))
    return row


def fingerprint(f):
    return [f.get("tool"), f.get("track") or "", f.get("kind") or "", f.get("where") or "", f.get("device") or ""]


def export(sd, path, by=None):
    sd = Path(sd)
    data = load_findings_doc(sd)
    dec = load_decisions(sd)
    by = reviewer(by)
    doc = dict(format="hypnomix-review", version=1, set=Path(data.get("set") or "").name, by=by, exported=now(),
               decisions={k: dict(v, by=v.get("by") or by) if isinstance(v, dict) else {"decision": v, "by": by}
                          for k, v in dec.items()},
               notes=load_notes(sd), findings={f["id"]: fingerprint(f) for f in data["findings"]})
    Path(path).expanduser().write_text(json.dumps(doc, indent=1))
    return doc


def merge(sd, path):
    """Merge a collaborator's exported review. Returns dict(adopted, same, conflicts, notes, unknown).
    Where the owner already decided differently, the owner's decision stays and the collaborator's is kept under
    `conflicts` on that entry for the owner to settle (review --settle ID=mine|theirs, or fix --decide)."""
    sd = Path(sd)
    data = load_findings_doc(sd)
    by_fp = {tuple(fingerprint(f)): f["id"] for f in data["findings"]}
    ids = {f["id"] for f in data["findings"]}
    doc = json.loads(Path(path).expanduser().read_text())
    if doc.get("format") != "hypnomix-review":
        raise ValueError("not a hypnomix review export (review DIR --export FILE makes one)")
    their_fp = {k: tuple(v) for k, v in (doc.get("findings") or {}).items()}
    dec = load_decisions(sd)
    res = dict(adopted=[], same=[], conflicts=[], notes=0, unknown=[])

    def local_id(fid):
        fp = their_fp.get(fid)
        if fp and fp in by_fp:
            return by_fp[fp]
        return fid if fid in ids and not fp else None

    for fid, d in (doc.get("decisions") or {}).items():
        lid = local_id(fid)
        if lid is None:
            res["unknown"].append(fid)
            continue
        d = d if isinstance(d, dict) else {"decision": d}
        if d.get("decision") not in DECISIONS:
            continue
        d.setdefault("by", doc.get("by") or "collaborator")
        mine = dec.get(lid)
        if isinstance(mine, str):                       # an older decisions.json: plain strings
            mine = dec[lid] = {"decision": mine}
        if not isinstance(mine, dict) or not mine.get("decision"):
            dec[lid] = {k: v for k, v in d.items() if k in ("decision", "note", "at", "amount", "by", "via")}
            dec[lid]["merged_from"] = d["by"]
            res["adopted"].append(lid)
        elif mine.get("decision") == d.get("decision") and amount_of(mine) == amount_of(d):
            res["same"].append(lid)
        else:
            c = {k: d.get(k) for k in ("by", "decision", "amount", "note", "at")}
            mine.setdefault("conflicts", [])
            if c not in mine["conflicts"]:
                mine["conflicts"].append(c)
            res["conflicts"].append((lid, mine, c))
    save_decisions(sd, dec)
    notes = load_notes(sd)
    for fid, rows in (doc.get("notes") or {}).items():
        lid = local_id(fid)
        if lid is None:
            continue
        have = notes.setdefault(lid, [])
        for r in rows:
            if r not in have:
                have.append(r)
                res["notes"] += 1
    (sd / NOTES_FILE).write_text(json.dumps(notes, indent=1))
    return res


def settle(sd, fid, which, by=None):
    """The owner settles a conflict: 'mine' keeps their decision, 'theirs' takes the (last) collaborator's."""
    dec = load_decisions(sd)
    e = dec.get(fid)
    if not isinstance(e, dict) or not e.get("conflicts"):
        raise ValueError(f"{fid}: no conflict to settle")
    if which == "theirs":
        c = e["conflicts"][-1]
        dec[fid] = entry(c["decision"], c.get("note") or "", c.get("amount"), by=by)
        dec[fid]["settled"] = f"took {c.get('by')}'s decision"
    elif which == "mine":
        e.pop("conflicts")
        e["settled"] = "kept own decision"
    else:
        raise ValueError("settle with mine or theirs")
    save_decisions(sd, dec)
    return dec[fid]


# ---------------------------------------------------------------- everything a reviewer sees on one finding
def extras(f, prefs=None, role_of=None, home=None, teach_on=True):
    """The oversight lines for one finding (REVIEW.md and the page use the same dict)."""
    from hypnomix.workflow import teach as T
    c, src = confidence(f)
    ok, how = scalable(f)
    e = dict(confidence=c, confidence_from=src, usually=usually(f, home, prefs, (role_of or {}).get(f.get("track"))),
             practice=T.practice(f), scalable=ok, scale_note=how, size=size(f))
    if teach_on:
        e["why"] = T.why(f)
    return e


def teach_on(prefs=None):
    from hypnomix.workflow import prefs as P
    v = P.get(prefs if prefs is not None else P.load(), "review.teach", "on")
    return str(v).lower() not in ("off", "no", "false", "0")


def max_questions(prefs=None):
    from hypnomix.workflow import prefs as P
    return P.get(prefs if prefs is not None else P.load(), "review.max_questions")
