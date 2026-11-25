#!/usr/bin/env python3
"""Your mixing tastes and standards, measured from your own finished songs.

Reads the sets themselves plus what `hypnomix voices --learn` already cached (track names by sound, vocal
renders), so nothing new is rendered. For every song, and then across songs:

  layout     tempo, how many parts of each kind, how many vocal parts you stack, groups
  levels     each kind of track's fader against the lead vocal's fader
  space      how wide you pan each kind of track, how often you pan hard, how wide the harmonies spread
  ambience   how much reverb and delay each kind of track gets (sends, dB), lead vs harmonies
  vocals     harmony level vs the lead (from voices --learn), how tightly harmonies follow the lead in time,
             whether you comp from take lanes, which warp modes you use on vocals
  chains     the devices and plug-ins you reach for on each kind of track, on your returns and on Main
  movement   what you automate (volume, sends, filters, rack macros) and how much

Across songs each number is the median of the songs (each song counts once) with its range. A small range is
a STANDARD (you do it the same way every time: tools should keep to it); a wide one is a TASTE CALL per song
(ask). Writes TASTE.md (plain words) and ~/.hypnomix/taste.json (for the tools).

Usage:  hypnomix taste SONG.als [SONG2.als …] [--out DIR]
        hypnomix taste --library [DIR …]      first run: study every set you have (see hypnomix/workflow/library.py)
"""
import argparse, collections, gzip, hashlib, json, math, os, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from hypnomix.core.paths import out_at

CACHE = Path.home() / ".hypnomix" / "cache"
PROFILE = Path.home() / ".hypnomix" / "taste.json"
v = lambda n, p: (n.find(p).get("Value") if n.find(p) is not None else None)
ROLE_OF = [("lead", r"^Lead Vocal"), ("harmony", r"^(Harmony|Backing Vocal|Vocal)"), ("drums", r"^(Drums|Kick|Snare|Hats|Perc)"),
           ("bass", r"^Bass"), ("keys/guitar/synth", r"^(Keys|Piano|Guitar|Synth|Pad|Organ|Pluck)"),
           ("strings/other", r"^(Strings|Brass|Lead\b|FX)")]
WARP = {"0": "Beats", "1": "Tones", "2": "Texture", "3": "Re-Pitch", "4": "Complex", "6": "Complex Pro"}


def cache_key(set_path):
    st = os.stat(set_path)
    return hashlib.sha1(f"{Path(set_path).resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]


def role(label, conf):
    if not label or conf < 0.5:
        return None
    for r, pat in ROLE_OF:
        if re.match(pat, label):
            return r
    return None


def db(x):
    return 20 * math.log10(x) if x and x > 0 else -70.0


def device_names(t):
    out = []
    devs = t.find("./DeviceChain/DeviceChain/Devices")
    for d in (list(devs) if devs is not None else []):
        nm = None
        for path in ("./PluginDesc/AuPluginInfo/Name", "./PluginDesc/VstPluginInfo/PlugName", "./PluginDesc/Vst3PluginInfo/Name"):
            if d.find(path) is not None:
                nm = v(d, path)
        out.append(v(d, "./UserName") or nm or d.tag)
    return out


def song(set_path, labels=None, require_lead=True, root=None):
    """One set's numbers. `labels` ({track name: (label, confidence)}) replaces the `voices --learn` names cache
    (the library scan passes labels guessed from track names); `require_lead=False` keeps songs without a lead
    vocal (their levels against the lead are then left empty); `root` is an already-parsed set."""
    set_path = Path(set_path)
    if labels is None:
        nj = CACHE / "names" / cache_key(set_path) / "names.json"
        if not nj.exists():
            return dict(song=set_path.stem, skipped="not studied yet: run `hypnomix voices --learn` on it first")
        labels = {r["old"]: (str(r.get("final") or r.get("label") or ""), float(r.get("confidence") or 0))
                  for r in json.loads(nj.read_text())["tracks"]}
    if root is None:
        root = ET.fromstring(gzip.open(set_path).read())
    tempo = float(v(root, ".//Tempo/Manual"))
    returns = []
    for t in root.find(".//Tracks"):
        if t.tag == "ReturnTrack":
            tags = " ".join(device_names(t)) + " " + (v(t, "./Name/EffectiveName") or "")
            kind = "delay" if re.search(r"delay|echo", tags, re.I) else "reverb" if re.search(r"reverb|verb|hybrid|tail", tags, re.I) else "other"
            returns.append(dict(name=v(t, "./Name/EffectiveName"), kind=kind, chain=device_names(t)))
    rows = []
    groups = {t.get("Id"): t for t in root.find(".//Tracks") if t.tag == "GroupTrack"}

    def chain_up(t):
        """The track and every group it plays through (their effects and sends shape what you hear)."""
        out, g = [t], v(t, "./TrackGroupId")
        while g in groups:
            out.append(groups[g]); g = v(groups[g], "./TrackGroupId")
        return out
    for t in root.find(".//Tracks"):
        if t.tag not in ("AudioTrack", "MidiTrack"):
            continue
        nm = v(t, "./Name/EffectiveName")
        if v(t, "./DeviceChain/Mixer/Speaker/Manual") == "false":
            continue
        lab, conf = labels.get(nm, ("", 0.0))
        r = role(lab, conf)
        if r is None:
            continue
        mx = t.find("./DeviceChain/Mixer")
        rev = dly = -70.0
        for x in chain_up(t):                    # a send on the group counts for every track in it
            sends = [float(v(h, "./Send/Manual")) for h in x.findall("./DeviceChain/Mixer/Sends/TrackSendHolder")]
            rev = max([rev] + [db(s_) for s_, ret in zip(sends, returns) if ret["kind"] == "reverb"])
            dly = max([dly] + [db(s_) for s_, ret in zip(sends, returns) if ret["kind"] == "delay"])
        clips = t.findall("./DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events/AudioClip")
        envs = t.findall("./AutomationEnvelopes/Envelopes/AutomationEnvelope")
        up = chain_up(t)
        inner = [d for x in up for d in x.find("./DeviceChain/DeviceChain/Devices").iter()
                 if d.tag in ("Reverb", "Hybrid", "Delay", "Echo", "FilterDelay", "PingPongDelay")] \
            if all(x.find("./DeviceChain/DeviceChain/Devices") is not None for x in up) else []
        names_ = " ".join(n_ for x in up for n_ in device_names(x)) + " " + " ".join(
            (v(d, f"./MacroDisplayNames.{i}") or "") for x in up for d in x.iter() if d.tag.endswith("GroupDevice") for i in range(16))
        ins_rev = any(d.tag in ("Reverb", "Hybrid") for d in inner) or bool(re.search(r"reverb|verb", names_, re.I))
        ins_dly = any(d.tag in ("Delay", "Echo", "FilterDelay", "PingPongDelay") for d in inner) or bool(re.search(r"delay|echo", names_, re.I))
        rows.append(dict(track=nm, role=r, fader=db(float(v(mx, "./Volume/Manual"))), pan=float(v(mx, "./Pan/Manual")),
                         insert_reverb=ins_rev, insert_delay=ins_dly,
                         reverb=rev, delay=dly, chain=device_names(t), envelopes=len(envs),
                         comped=bool(t.findall(".//TakeLanes//AudioClip")),
                         warp=[WARP.get(v(c, "./WarpMode"), v(c, "./WarpMode")) for c in clips if v(c, "./IsWarped") == "true"]))
    lead = next((r for r in rows if r["role"] == "lead"), None)
    if lead is None and require_lead:
        return dict(song=set_path.stem, skipped="no lead vocal found")
    by = collections.defaultdict(list)
    for r in rows:
        by[r["role"]].append(r)
    out = dict(song=set_path.stem, tempo=round(tempo, 1), parts={k: len(x) for k, x in by.items()},
               returns=[(r["name"], r["kind"]) for r in returns], main_chain=device_names(next((m for m in (root.find(".//MainTrack"), root.find(".//MasterTrack")) if m is not None))),
               return_chains={r["name"]: r["chain"] for r in returns})
    out["level_vs_lead"] = {k: round(float(np.median([r["fader"] - lead["fader"] for r in x])), 1)
                            for k, x in by.items() if k != "lead"} if lead else {}
    out["pan_width"] = {k: round(float(np.median([abs(r["pan"]) for r in x])), 2) for k, x in by.items()}
    out["hard_panned"] = {k: round(float(np.mean([abs(r["pan"]) >= 0.8 for r in x])), 2) for k, x in by.items()}
    hp = [r["pan"] for r in by.get("harmony", [])]
    out["harmony_spread"] = round(float(max(hp) - min(hp)), 2) if len(hp) >= 2 else None
    out["reverb_send_db"] = {k: round(float(np.median([r["reverb"] for r in x])), 1) for k, x in by.items()}
    out["delay_send_db"] = {k: round(float(np.median([r["delay"] for r in x])), 1) for k, x in by.items()}
    out["chains"] = {k: collections.Counter(d for r in x for d in r["chain"]).most_common(6) for k, x in by.items()}
    out["insert_reverb"] = {k: round(float(np.mean([r["insert_reverb"] for r in x])), 2) for k, x in by.items()}
    out["insert_delay"] = {k: round(float(np.mean([r["insert_delay"] for r in x])), 2) for k, x in by.items()}
    out["automated_tracks"] = {k: round(float(np.mean([r["envelopes"] > 0 for r in x])), 2) for k, x in by.items()}
    voc = by.get("lead", []) + by.get("harmony", [])
    out["vocals_comped"] = round(float(np.mean([r["comped"] for r in voc])), 2) if voc else None
    wm = collections.Counter(w for r in voc for w in r["warp"])
    out["vocal_warp_modes"] = dict(wm.most_common(3))
    # harmony timing against the lead, from the cached renders
    rd = CACHE / "renders" / cache_key(set_path)
    safe = lambda n: re.sub(r'[\\/:*?"<>|]', "-", n)
    lp = rd / f"{safe(lead['track'])}.wav" if lead else Path("/nonexistent")
    tight = []
    if lp.exists():
        from hypnomix.core import dsp
        from hypnomix.studio import vocalign as V
        yl, sr = dsp.load(lp, 22050)
        for r in by.get("harmony", [])[:6]:
            hp_ = rd / f"{safe(r['track'])}.wav"
            if not hp_.exists():
                continue
            yo, _ = dsp.load(hp_, 22050)
            m = min(len(yl), len(yo))
            try:
                med, _ = V.residual_ms(yl[:m] if yl.ndim > 1 else yl[:m, None], yo[:m] if yo.ndim > 1 else yo[:m, None], sr, 150)
                tight.append(med)
            except Exception:
                pass
    out["harmony_timing_ms"] = round(float(np.median(tight)), 0) if tight else None
    return out


def across(songs):
    ok = [s for s in songs if not s.get("skipped")]
    def summ(vals):
        vals = [x for x in vals if x is not None]
        if not vals:
            return None
        return dict(median=round(float(np.median(vals)), 2), low=round(float(min(vals)), 2), high=round(float(max(vals)), 2),
                    songs=len(vals))
    keys = sorted({k for s in ok for k in s.get("level_vs_lead", {})} | {"lead"})
    prof = dict(songs=[s["song"] for s in ok], skipped=[(s["song"], s["skipped"]) for s in songs if s.get("skipped")],
                tempo=summ([s["tempo"] for s in ok]),
                vocal_parts=summ([s["parts"].get("lead", 0) + s["parts"].get("harmony", 0) for s in ok]),
                level_vs_lead={k: summ([s["level_vs_lead"].get(k) for s in ok]) for k in keys if k != "lead"},
                pan_width={k: summ([s["pan_width"].get(k) for s in ok]) for k in keys},
                hard_panned={k: summ([s["hard_panned"].get(k) for s in ok]) for k in keys},
                harmony_spread=summ([s["harmony_spread"] for s in ok]),
                reverb_send_db={k: summ([s["reverb_send_db"].get(k) for s in ok]) for k in keys},
                delay_send_db={k: summ([s["delay_send_db"].get(k) for s in ok]) for k in keys},
                automated_tracks={k: summ([s["automated_tracks"].get(k) for s in ok]) for k in keys},
                insert_reverb={k: summ([s.get("insert_reverb", {}).get(k) for s in ok]) for k in keys},
                insert_delay={k: summ([s.get("insert_delay", {}).get(k) for s in ok]) for k in keys},
                vocals_comped=summ([s["vocals_comped"] for s in ok]),
                harmony_timing_ms=summ([s["harmony_timing_ms"] for s in ok]))
    ch = collections.defaultdict(collections.Counter)
    for s in ok:
        for k, lst in s["chains"].items():
            for d, _ in lst:
                ch[k][d] += 1                                       # in how many songs it appears
    prof["chains"] = {k: [(d, n) for d, n in c.most_common(6) if n >= 2] for k, c in ch.items()}
    mc = collections.Counter(d for s in ok for d in set(s["main_chain"]))
    prof["main_chain"] = [(d, n) for d, n in mc.most_common(8) if n >= 2]
    rc = collections.Counter(k for s in ok for _, k in s["returns"])
    prof["returns"] = dict(rc)
    wm = collections.Counter()
    for s in ok:
        wm.update(s["vocal_warp_modes"])
    prof["vocal_warp_modes"] = dict(wm.most_common(3))
    hs = Path.home() / ".hypnomix" / "harmony-style.json"
    if hs.exists():
        h = json.loads(hs.read_text())
        prof["harmonies"] = {k: h.get(k) for k in ("lead_margin", "lead_margin_median", "tolerance", "higher_minus_lower_median")}
    return prof


def standard(x, width):
    return x is not None and (x["high"] - x["low"]) <= width


def report(prof, songs):
    L = ["# Your mixing tastes and standards", "",
         f"Measured from {len(prof['songs'])} of your finished songs: {', '.join(prof['songs'])}."
         + (f" Not counted: {', '.join(f'{s} ({w})' for s, w in prof['skipped'])}." if prof["skipped"] else ""),
         "Each number is the median song, with the range across songs. **Standard** = you do it the same way every "
         "time (tools keep to it); **taste call** = it changes per song (tools ask). Measured from the sets "
         "(faders, pans, sends, devices) and the raw vocal clips; your ears overrule all of it.", ""]
    def line(label, x, unit, width):
        if not x:
            return None
        tag = "**standard**" if standard(x, width) else "taste call"
        return f"- {label}: {x['median']:+g}{unit} (songs from {x['low']:+g} to {x['high']:+g}{unit}) · {tag}"
    L += ["## Layout", ""]
    if prof["tempo"]:
        L.append(f"- tempo: {prof['tempo']['median']:g} BPM (from {prof['tempo']['low']:g} to {prof['tempo']['high']:g})")
    if prof["vocal_parts"]:
        L.append(f"- vocal parts that play (lead + harmonies): {prof['vocal_parts']['median']:g} "
                 f"(from {prof['vocal_parts']['low']:g} to {prof['vocal_parts']['high']:g})")
    L.append(f"- returns: " + ", ".join(f"{n}× {k}" for k, n in prof["returns"].items()))
    L += ["", "## Levels (fader against the lead vocal's fader)", ""]
    for k, x in prof["level_vs_lead"].items():
        s_ = line(k, x, " dB", 4.0)
        if s_: L.append(s_)
    if prof.get("harmonies"):
        h = prof["harmonies"]
        L.append(f"- harmonies as heard against the lead (voices --learn): about {h.get('lead_margin_median')} dB under; "
                 f"3 in 4 readings at least {h.get('lead_margin')} dB under")
    L += ["", "## Space (pan)", ""]
    centred = [k for k, x in prof["pan_width"].items() if x and x["high"] <= 0.05]
    if centred:
        L.append(f"- centred in every song: {', '.join(centred)} · **standard** (width comes from elsewhere, not panning)")
    for k, x in prof["pan_width"].items():
        hp = prof["hard_panned"].get(k)
        if x and k not in centred:
            L.append(f"- {k}: typically {x['median']:.0%} off centre (songs {x['low']:.0%}–{x['high']:.0%})"
                     + (f", hard-panned in {hp['median']:.0%} of tracks" if hp and hp["median"] > 0 else "")
                     + (" · **standard**" if standard(x, 0.25) else " · taste call"))
    if prof["harmony_spread"]:
        x = prof["harmony_spread"]
        L.append(f"- harmonies spread across {x['median']:.0%} of the stereo field from left-most to right-most "
                 f"(songs {x['low']:.0%}–{x['high']:.0%})")
    L += ["", "## Ambience", ""]
    for k in prof["reverb_send_db"]:
        r, d = prof["reverb_send_db"].get(k), prof["delay_send_db"].get(k)
        ir, idl = prof["insert_reverb"].get(k), prof["insert_delay"].get(k)
        bits = []
        if ir and ir["median"] > 0:
            bits.append(f"reverb in its own chain on {ir['median']:.0%} of tracks")
        if idl and idl["median"] > 0:
            bits.append(f"delay in its own chain on {idl['median']:.0%}")
        if r and r["median"] > -60:
            bits.append(f"reverb send {r['median']:+g} dB")
        if d and d["median"] > -60:
            bits.append(f"delay send {d['median']:+g} dB")
        L.append(f"- {k}: " + ("; ".join(bits) if bits else "dry (no reverb or delay, in the chain or by send, in the median song)"))
    L += ["", "## Vocals", ""]
    if prof["harmony_timing_ms"]:
        x = prof["harmony_timing_ms"]
        L.append(f"- harmonies follow the lead within about {x['median']:g} ms where both sing (songs {x['low']:g}–{x['high']:g} ms): "
                 + ("tight" if x["median"] < 25 else "loose, natural" if x["median"] < 45 else "loose"))
    if prof["vocals_comped"]:
        L.append(f"- vocals comped from take lanes: {prof['vocals_comped']['median']:.0%} of vocal tracks")
    if prof["vocal_warp_modes"]:
        L.append("- warp modes on vocal clips: " + ", ".join(f"{k} ({n} clips)" for k, n in prof["vocal_warp_modes"].items())
                 + (". Note: Beats mode can chop sustained vocals (Complex Pro keeps them smooth); worth an A/B on a held "
                    "note" if "Beats" in prof["vocal_warp_modes"] else ""))
    L += ["", "## Chains you reach for (devices in 2+ songs)", ""]
    for k, lst in prof["chains"].items():
        if lst:
            L.append(f"- {k}: " + ", ".join(f"{d} ({n} songs)" for d, n in lst))
    if prof["main_chain"]:
        L.append("- Main: " + ", ".join(f"{d} ({n} songs)" for d, n in prof["main_chain"]))
    L += ["", "## Movement (share of tracks with automation)", ""]
    for k, x in prof["automated_tracks"].items():
        if x:
            L.append(f"- {k}: {x['median']:.0%} (songs {x['low']:.0%}–{x['high']:.0%})")
    L += ["", "## Per song", ""]
    for s in songs:
        if s.get("skipped"):
            L.append(f"- {s['song']}: not counted ({s['skipped']})"); continue
        L.append(f"- {s['song']}: {s['tempo']:g} BPM; parts {s['parts']}; levels vs lead {s['level_vs_lead']}; "
                 f"reverb sends {s['reverb_send_db']}; harmony timing {s['harmony_timing_ms']} ms")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(prog="hypnomix taste", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sets", nargs="*"); ap.add_argument("--out")
    ap.add_argument("--library", nargs="*", metavar="DIR",
                    help="study every Ableton set in these folders (default: your Ableton folders): LIBRARY.md")
    if "--library" in sys.argv[1:] and {"-h", "--help"} & set(sys.argv[1:]):
        from hypnomix.workflow import library
        return library.main(["-h"])
    a, rest = ap.parse_known_args()
    if a.library is not None:
        from hypnomix.workflow import library
        return library.main(list(a.library) + list(a.sets) + rest + (["--out", a.out] if a.out else []))
    if rest:
        ap.error(f"unrecognized arguments: {' '.join(rest)}")
    if not a.sets:
        ap.error("give one or more sets, or --library")
    songs = []
    for sp in a.sets:
        print(f"  {Path(sp).stem}…", flush=True)
        songs.append(song(sp))
    prof = across(songs)
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE.write_text(json.dumps(dict(profile=prof, songs=songs), indent=1, default=str))
    od = out_at(a.out, "taste")
    (od / "TASTE.md").write_text(report(prof, songs))
    print(report(prof, songs))
    print(f"→ {od / 'TASTE.md'} and {PROFILE}")


if __name__ == "__main__":
    main()
