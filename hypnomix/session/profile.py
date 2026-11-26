#!/usr/bin/env python3
"""Your sound, as numbers: build a style profile from finished songs you like (yours or references).

Every other tool can compare against it: `loop` flags a take outside your usual range,
`audit` compares a bounce with it, `automix` and `master` can aim at it instead of generic targets.

Usage:
    hypnomix profile build song1.wav song2.wav … [--sets a.als b.als …] [--name mine]
    hypnomix profile show

Writes ~/.hypnomix/profile.json and profile.md (set HYPNOMIX_HOME to change). Five or more songs give useful ranges.
"""
import argparse, json, statistics as st, sys
from collections import Counter
from pathlib import Path

from hypnomix.core.paths import PROFILE


def stats(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    q = lambda p: xs[min(len(xs) - 1, max(0, round(p * (len(xs) - 1))))]
    return {"median": round(st.median(xs), 2), "p25": round(q(.25), 2), "p75": round(q(.75), 2),
            "min": round(xs[0], 2), "max": round(xs[-1], 2), "n": len(xs)}


def audio_metrics(m):
    f = m["ffmpeg"]
    return {"integrated_lufs": f["integrated_lufs"], "true_peak_dbtp": f["true_peak_dbtp"], "lra_lu": f["lra_lu"],
            "crest_factor_db": m["crest_factor_db"], "spectral_centroid_hz": m["spectral_centroid_hz"],
            "rolloff_85_hz": m["rolloff_85_hz"], "side_to_mid_db": m.get("stereo_side_to_mid_db"),
            "lr_correlation": m.get("lr_correlation"), "lr_corr_below_150hz": m.get("lr_correlation_below_150hz"),
            "duration_s": m["duration_s"], "short_term_spread_lu": m["short_term_p10_p95"][1] - m["short_term_p10_p95"][0],
            **{f"band_{k}": v for k, v in m["band_energy_db"].items()}}


def profile_ranges(path=PROFILE):
    """{metric: {p25, median, p75, …}} from the saved profile, or {} if there is none yet."""
    p = Path(path)
    if not p.exists():
        return {}
    return {k: v for k, v in json.loads(p.read_text(encoding="utf-8"))["audio"].items() if isinstance(v, dict)}


def build(files, sets=(), name="mine", out=PROFILE):
    from hypnomix.ears.measure import measure
    rows = {}
    for f in files:
        print(f"measuring {Path(f).name} …", file=sys.stderr)
        rows[Path(f).stem] = audio_metrics(measure(Path(f)))
    keys = next(iter(rows.values())).keys()
    prof = {"name": name, "songs": sorted(rows), "audio": {k: stats([r[k] for r in rows.values()]) for k in keys},
            "per_song": rows}
    if sets:
        from hypnomix.session.miner import mine
        sess = [mine(Path(s)) for s in sets]
        dev = Counter()
        faders, sends = [], []
        for s in sess:
            dev.update({k.replace(" (off)", "") for k in s["device_counts"]})
            mix = [t for t in s["tracks"] if t["type"] in ("Audio", "Midi") and not t["muted"]]
            faders += [t["volume_db"] for t in mix]
            sends += [t["sends_db"][0] for t in mix if t["sends_db"] and t["sends_db"][0] > -60]
        prof["sessions"] = {
            "sets": [s["name"] for s in sess], "tempo": {s["name"]: round(s["tempo"], 2) for s in sess},
            "track_count": stats([len(s["tracks"]) for s in sess]), "fader_db": stats(faders),
            "send_a_db_when_used": stats(sends), "devices_by_set_count": dict(dev.most_common(60)),
            "master_chains": {s["name"]: [d for d in s["master_chain"] if not d.startswith(">")] for s in sess}}
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(prof, indent=2), encoding="utf-8")
    out.with_suffix(".md").write_text(to_markdown(prof), encoding="utf-8")
    return out


def to_markdown(prof):
    lines = [f"# Profile: {prof['name']}", "", f"{len(prof['songs'])} songs: {', '.join(prof['songs'])}", "",
             "| metric | p25 | median | p75 |", "|---|---|---|---|"]
    for k, v in prof["audio"].items():
        if v:
            lines.append(f"| {k} | {v['p25']} | {v['median']} | {v['p75']} |")
    if "sessions" in prof:
        s = prof["sessions"]
        lines += ["", "## Sessions", f"Typical fader: {s['fader_db']}", "",
                  "Devices you reach for: " + ", ".join(list(s["devices_by_set_count"])[:20])]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(prog="hypnomix profile", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("files", nargs="+"); b.add_argument("--sets", nargs="*", default=[])
    b.add_argument("--name", default="mine"); b.add_argument("--out", default=str(PROFILE))
    sub.add_parser("show")
    a = ap.parse_args()
    if a.cmd == "build":
        print(build(a.files, a.sets, a.name, a.out))
    else:
        md = PROFILE.with_suffix(".md")
        print(md.read_text(encoding="utf-8") if md.exists() else "no profile yet: hypnomix profile build song1.wav song2.wav …")


if __name__ == "__main__":
    main()
