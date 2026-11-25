#!/usr/bin/env python3
"""Tonal balance targets: how your finished songs (or records you choose) spread their energy across the spectrum,
as a curve with a range at every frequency, and where a mix sits outside that range.

A target is built from songs, never from a built-in rule. Each song is measured on its loudest ~45 s at matched
loudness (the same rule as `hypnomix match`), as smoothed 1/3-octave levels and as the 8 named bands (sub, bass,
upper bass, low-mid, mid, upper-mid, presence, air). Every curve is lined up on its own 250 Hz–4 kHz average, so
overall level and loudness never count, only shape. The target keeps, per band, the average and a range:
  --spread minmax   lowest to highest of the songs (default), at least ±--margin dB around the average
  --spread std      average ± --k standard deviations, at least ±--margin dB

`check` measures a mix the same way and lists every region that sits outside the range, with one modest EQ move
each (capped at --max-db, scaled by --amount, never applied: proposals only). It also writes a PNG: the shaded
range, the target average and your mix.

Usage:
    hypnomix tonal build mine1.wav mine2.wav ... --name mine [--ref other.wav ...] [--ref-weight 1]
                         [--spread minmax|std] [--k 1.0] [--margin 1.0]
    hypnomix tonal check MIX.wav --target mine [--toward edge|mean] [--max-db 3] [--amount 100]
                         [--json OUT.json] [--out DIR]
    hypnomix tonal list
    hypnomix tonal show NAME

Targets are saved in the hypnomix home (~/.hypnomix/tonal/NAME.json, or $HYPNOMIX_HOME). `--target` also takes
a path to a target .json. For a live meter: `target_bands(name)` gives the bands with their ranges and
`measure(y, sr)` measures audio on the same scale.
"""
import argparse, json, re, sys, time, warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
from hypnomix.core import dsp  # noqa: E402
from hypnomix.core.paths import HOME, out_at  # noqa: E402

THIRD_CENTRES = [float(c) for c in 1000 * 2 ** (np.arange(-17, 13) / 3)]          # 19.7 Hz … 16 kHz, 30 bands
THIRD = [(c / 2 ** (1 / 6), c * 2 ** (1 / 6)) for c in THIRD_CENTRES]
EIGHT = [("sub", 20, 60), ("bass", 60, 120), ("upper bass", 120, 250), ("low-mid", 250, 500),
         ("mid", 500, 2000), ("upper-mid", 2000, 4000), ("presence", 4000, 8000), ("air", 8000, 20000)]
MID_REF = (250.0, 4000.0)                       # curves are lined up on their average level in this range


def tonal_dir():
    d = HOME / "tonal"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _psd(y, sr):
    from scipy.signal import welch
    m = dsp.stereo(y).mean(axis=1)
    n = 16384 if sr >= 32000 else 8192
    if len(m) < n:
        m = np.pad(m, (0, n - len(m)))
    f, P = welch(m, sr, nperseg=n, noverlap=n // 2)
    return f, P


def _levels(f, P, edges):
    df = f[1] - f[0]
    out = []
    for lo, hi in edges:
        hi = min(hi, f[-1])
        sel = (f >= lo) & (f < hi)
        e = P[sel].sum() * df if sel.any() else np.interp(np.sqrt(lo * hi), f, P) * max(hi - lo, df)
        out.append(10 * np.log10(e + 1e-30))
    return np.array(out)


def normalise(levels, centres):
    """Line a curve up on its own 250 Hz–4 kHz average, so only its shape counts."""
    levels, centres = np.asarray(levels, float), np.asarray(centres, float)
    sel = (centres >= MID_REF[0]) & (centres <= MID_REF[1])
    return levels - levels[sel].mean()


def eight_centres():
    return np.array([np.sqrt(lo * hi) for _, lo, hi in EIGHT])


def measure(y, sr, loudest=True):
    """The tonal curves of a piece of audio: {'third': 30 values, 'eight': 8 values} in dB, normalised.
    loudest=False measures the audio as given (for a live meter on a short buffer)."""
    y = dsp.stereo(y)
    if loudest:
        from hypnomix.ears.match import loudest as _loudest
        y = _loudest(y, sr)
    f, P = _psd(y, sr)
    third = normalise(_levels(f, P, THIRD), THIRD_CENTRES)
    eight = normalise(_levels(f, P, [(lo, hi) for _, lo, hi in EIGHT]), eight_centres())
    return {"third": third, "eight": eight}


def measure_file(path):
    y, sr = dsp.load(path)
    return measure(y, sr)


def _range(curves, weights, spread, k, margin):
    C = np.asarray(curves, float)
    w = np.asarray(weights, float) / np.sum(weights)
    mean = (C * w[:, None]).sum(axis=0)
    if spread == "std" and len(C) > 1:
        sd = np.sqrt((w[:, None] * (C - mean) ** 2).sum(axis=0))
        lo, hi = mean - k * sd, mean + k * sd
    else:
        lo, hi = C.min(axis=0), C.max(axis=0)
    lo, hi = np.minimum(lo, mean - margin), np.maximum(hi, mean + margin)
    return mean, lo, hi


def build(own=(), refs=(), name="mine", ref_weight=1.0, spread="minmax", k=1.0, margin=1.0, measured=None):
    """Build a target from the person's own songs and/or chosen references. measured: optional
    {path: measure()-dict} to skip re-measuring (tests, the live meter)."""
    files = [(p, "own", 1.0) for p in own] + [(p, "reference", float(ref_weight)) for p in refs]
    if not files:
        raise ValueError("a target needs at least one song")
    curves = {"third": [], "eight": []}
    sources = []
    for p, role, w in files:
        m = (measured or {}).get(p) or measure_file(p)
        for kind in curves:
            curves[kind].append(np.asarray(m[kind], float))
        sources.append(dict(file=Path(str(p)).name, role=role, weight=w))
    weights = [s["weight"] for s in sources]
    t = dict(name=name, built=time.strftime("%Y-%m-%d"), sources=sources, spread=spread, k=k, margin=margin,
             mid_reference_hz=list(MID_REF))
    for kind, centres, labels in (("third", THIRD_CENTRES, [f"{c:.0f} Hz" for c in THIRD_CENTRES]),
                                  ("eight", eight_centres(), [n for n, _, _ in EIGHT])):
        mean, lo, hi = _range(curves[kind], weights, spread, k, margin)
        edges = THIRD if kind == "third" else [(a, b) for _, a, b in EIGHT]
        t[kind] = [dict(name=lab, centre_hz=round(float(c), 1), lo_hz=round(float(e[0]), 1), hi_hz=round(float(e[1]), 1),
                        mean_db=round(float(m_), 2), low_db=round(float(l_), 2), high_db=round(float(h_), 2))
                   for lab, c, e, m_, l_, h_ in zip(labels, centres, edges, mean, lo, hi)]
    return t


def _safe(name):
    return re.sub(r"[^A-Za-z0-9 _.-]+", "_", name).strip() or "target"


def save_target(t):
    p = tonal_dir() / f"{_safe(t['name'])}.json"
    p.write_text(json.dumps(t, indent=1))
    return p


def load_target(name_or_path):
    p = Path(str(name_or_path)).expanduser()
    if p.suffix == ".json" and p.exists():
        return json.loads(p.read_text())
    q = tonal_dir() / f"{_safe(str(name_or_path))}.json"
    if not q.exists():
        have = ", ".join(sorted(x.stem for x in tonal_dir().glob("*.json"))) or "none yet"
        raise FileNotFoundError(f"no tonal target {name_or_path!r} (have: {have}); build one with "
                                "`hypnomix tonal build SONG.wav ... --name NAME`")
    return json.loads(q.read_text())


def target_bands(name_or_path, kind="eight"):
    """The target's bands for a meter: list of {name, centre_hz, lo_hz, hi_hz, mean_db, low_db, high_db}.
    Measure live audio on the same scale with measure(y, sr, loudest=False)[kind]."""
    t = name_or_path if isinstance(name_or_path, dict) else load_target(name_or_path)
    return [dict(b) for b in t[kind]]


def _k(hz):
    return f"{hz / 1000:.3g}k" if hz >= 1000 else f"{hz:.0f}"


def check(mix_curve, target, toward="edge", max_db=3.0, min_db=0.5, amount=100.0):
    """Where the mix leaves the target range, and one EQ move per region. Returns (rows, findings)."""
    rows = []
    bands = target["third"]
    mix = np.asarray(mix_curve["third"], float)
    out = []
    for b, v in zip(bands, mix):
        over = v - b["high_db"] if v > b["high_db"] else (v - b["low_db"] if v < b["low_db"] else 0.0)
        to_mean = v - b["mean_db"]
        out.append((b, v, over, to_mean))
        rows.append(dict(band=b["name"], mix_db=round(float(v), 2), mean_db=b["mean_db"], low_db=b["low_db"],
                         high_db=b["high_db"], outside_db=round(float(over), 2)))
    # group neighbouring bands outside the range on the same side into one region
    regions, cur = [], []
    for item in out:
        s = np.sign(item[2])
        if s != 0 and cur and np.sign(cur[-1][2]) == s:
            cur.append(item)
        else:
            if cur:
                regions.append(cur)
            cur = [item] if s != 0 else []
    if cur:
        regions.append(cur)
    findings = []
    scale = max(0.0, min(100.0, amount)) / 100
    for reg in regions:
        lo, hi = reg[0][0]["lo_hz"], reg[-1][0]["hi_hz"]
        f0 = float(np.sqrt(reg[0][0]["centre_hz"] * reg[-1][0]["centre_hz"]))
        dist = np.mean([r[3] if toward == "mean" else r[2] for r in reg])
        worst = max(reg, key=lambda r: abs(r[2]))
        gain = float(np.clip(-dist, -max_db, max_db)) * scale
        if abs(gain) < min_db:
            continue
        bw_oct = np.log2(hi / lo)
        q = float(np.clip(1 / (2 ** (bw_oct / 2) - 2 ** (-bw_oct / 2)), 0.5, 4.0))
        if reg[0][0] is bands[0]:
            kind = "low shelf"
            f0 = reg[-1][0]["hi_hz"]
        elif reg[-1][0] is bands[-1]:
            kind = "high shelf"
            f0 = reg[0][0]["lo_hz"]
        else:
            kind = "bell"
        word = "above" if worst[2] > 0 else "below"
        sev = "medium" if abs(worst[2]) > 2.5 else "low"
        fix = (f"try a {abs(gain):.1f} dB {kind} {'cut' if gain < 0 else 'boost'} at {_k(f0)} Hz"
               + (f", Q {q:.1f}" if kind == "bell" else "")
               + f" (toward the range {'edge' if toward == 'edge' else 'average'})")
        if abs(worst[2]) > max_db * 1.5:
            fix += (f"; the gap reaches {abs(worst[2]):.1f} dB, more than one EQ move should close: check the arrangement "
                    "or the source sounds")
        findings.append(dict(id=f"tonal-{len(findings) + 1}", tool="tonal", kind=f"tonal-{int(round(f0))}",
                             severity=sev, track="mix", where=f"{_k(lo)}-{_k(hi)} Hz",
                             problem=f"{_k(lo)}-{_k(hi)} Hz sits {abs(worst[2]):.1f} dB {word} the target range "
                                     f"(at {worst[0]['name']})",
                             fix=fix, applies="manual",
                             eq=dict(kind=kind.replace(" ", ""), freq=round(f0, 1), gain=round(gain, 2), q=round(q, 2))))
    eight = [dict(band=b["name"], mix_db=round(float(v), 2), low_db=b["low_db"], high_db=b["high_db"],
                  outside_db=round(float(v - b["high_db"] if v > b["high_db"] else v - b["low_db"] if v < b["low_db"] else 0), 2))
             for b, v in zip(target["eight"], mix_curve["eight"])]
    return dict(third=rows, eight=eight), findings


def plot(png, target, mix_curve=None, title=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    b = target["third"]
    c = [x["centre_hz"] for x in b]
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=110)
    ax.fill_between(c, [x["low_db"] for x in b], [x["high_db"] for x in b], color="#8fb3d9", alpha=0.45,
                    label=f"target range ({target['name']})", linewidth=0)
    ax.plot(c, [x["mean_db"] for x in b], color="#2f5f8f", lw=1.4, label="target average")
    if mix_curve is not None:
        m = np.asarray(mix_curve["third"])
        ax.plot(c, m, color="#c0392b", lw=1.8, label="this mix")
        out = [(ci, mi) for ci, mi, x in zip(c, m, b) if mi > x["high_db"] or mi < x["low_db"]]
        if out:
            ax.scatter(*zip(*out), color="#c0392b", s=18, zorder=3, label="outside the range")
    ax.set_xscale("log")
    ax.set_xticks([20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 16000])
    ax.set_xticklabels(["20", "50", "100", "200", "500", "1k", "2k", "5k", "10k", "16k"])
    ax.set_xlabel("Hz")
    ax.set_ylabel("dB (lined up on 250 Hz-4 kHz)")
    ax.grid(alpha=0.25, which="both")
    ax.legend(fontsize=8, loc="lower left")
    ax.set_title(title or "Tonal balance", fontsize=10)
    fig.tight_layout()
    fig.savefig(png)
    plt.close(fig)
    return png


def _table(res):
    rows = ["| band | mix | target range | outside by |", "|---|---|---|---|"]
    for r in res["eight"]:
        o = "{:+.1f} dB".format(r["outside_db"]) if r["outside_db"] else "-"
        rows.append(f"| {r['band']} | {r['mix_db']:+.1f} | {r['low_db']:+.1f} … {r['high_db']:+.1f} | {o} |")
    return "\n".join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix tonal", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build a target from your songs and/or references")
    b.add_argument("files", nargs="*", help="your own finished masters")
    b.add_argument("--ref", nargs="+", default=[], help="references you choose")
    b.add_argument("--ref-weight", type=float, default=1.0, help="weight of each reference against one of your songs")
    b.add_argument("--name", required=True)
    b.add_argument("--spread", choices=["minmax", "std"], default="minmax")
    b.add_argument("--k", type=float, default=1.0, help="standard deviations for --spread std")
    b.add_argument("--margin", type=float, default=1.0, help="smallest half-width of the range, dB")
    b.add_argument("--force", action="store_true", help="replace a target of the same name")
    b.add_argument("--plot", action="store_true", help="also write a PNG of the target")
    c = sub.add_parser("check", help="where a mix sits outside a target, with EQ proposals")
    c.add_argument("mix")
    c.add_argument("--target", required=True, help="a target name or a target .json")
    c.add_argument("--toward", choices=["edge", "mean"], default="edge", help="move to the range edge or its average")
    c.add_argument("--max-db", type=float, default=3.0)
    c.add_argument("--min-db", type=float, default=0.5, help="smaller moves are not proposed")
    c.add_argument("--amount", type=float, default=100.0, help="0-100: scale every proposed move")
    c.add_argument("--json")
    c.add_argument("--out")
    sub.add_parser("list", help="targets you have")
    s = sub.add_parser("show", help="print a target")
    s.add_argument("name")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        for p in sorted(tonal_dir().glob("*.json")):
            t = json.loads(p.read_text())
            print(f"{t['name']}: {len(t['sources'])} song(s), {t['spread']}, built {t.get('built', '?')}")
        return
    if a.cmd == "show":
        t = load_target(a.name)
        print(json.dumps({k: v for k, v in t.items() if k != "third"}, indent=1))
        return
    if a.cmd == "build":
        if not a.files and not a.ref:
            sys.exit("give at least one song (your own) or --ref")
        p = tonal_dir() / f"{_safe(a.name)}.json"
        if p.exists() and not a.force:
            sys.exit(f"target {a.name!r} already exists ({p}); use --force to replace it or pick another --name")
        print(f"measuring {len(a.files) + len(a.ref)} song(s) …", file=sys.stderr)
        t = build(a.files, a.ref, a.name, a.ref_weight, a.spread, a.k, a.margin)
        p = save_target(t)
        print(f"target {a.name!r} saved: {p}\n")
        print("| band | average | range |\n|---|---|---|")
        for x in t["eight"]:
            print(f"| {x['name']} | {x['mean_db']:+.1f} | {x['low_db']:+.1f} … {x['high_db']:+.1f} |")
        if a.plot:
            print(f"plot: {plot(tonal_dir() / f'{_safe(a.name)}.png', t, title=f'Target {a.name}')}")
        return
    t = load_target(a.target)
    y, sr = dsp.load(a.mix)
    m = measure(y, sr)
    res, findings = check(m, t, a.toward, a.max_db, a.min_db, a.amount)
    od = out_at(a.out, "tonal", Path(a.mix).stem)
    png = plot(od / f"{Path(a.mix).stem} vs {_safe(t['name'])}.png", t, m, f"{Path(a.mix).name} vs target {t['name']}")
    lines = [f"- [{f['severity']}] {f['where']}: {f['problem']} - {f['fix']}" for f in findings] or \
            ["- the mix sits inside the target range everywhere (measured; still listen)"]
    text = (f"# Tonal check: {Path(a.mix).name} vs {t['name']}\n\nLoudest ~45 s, lined up on 250 Hz-4 kHz. Target from "
            f"{len(t['sources'])} song(s).\n\n{_table(res)}\n\n## Proposals (nothing was changed)\n\n" + "\n".join(lines)
            + f"\n\nPlot: `{png.name}`\n")
    (od / "TONAL.md").write_text(text)
    if a.json:
        Path(a.json).write_text(json.dumps(dict(mix=str(a.mix), target=t["name"], bands=res, findings=findings), indent=1))
    print(text)
    print(f"report: {od / 'TONAL.md'}", file=sys.stderr)


if __name__ == "__main__":
    main()
