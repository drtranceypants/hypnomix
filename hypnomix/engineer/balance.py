#!/usr/bin/env python3
"""A first static balance for a folder of stems: one fader move per part, with the measurement behind it.

Faders only: no EQ, no compression, no panning, no effects (that is what `hypnomix automix` adds). `balance`
measures each stem's loudness while it plays (quiet gaps do not count), works out what the part is (by its
name, then its sound), and proposes a fader move that puts every part where a band of that kind usually sits
against the anchor part. It reports first and writes nothing next to your stems.

For each part the report shows: its role, how loud it plays, the move, where that leaves it against the anchor,
and, when you built a profile (`hypnomix profile build … --sets …`), whether the move lands inside the fader range
of your own finished songs. It also shows the vocal-to-band relation: the lead vocal's loudness against
everything else played together, before and after.

Options, never one rule:
    --anchor NAME          the part everything is measured against (a stem name); default: the lead vocal, or
                           the highest-priority role when there is no vocal
    --vocal-over-band DB   put the lead vocal DB above the rest of the band (0 = as loud as the band together).
                           Without it the vocal sits where the role balance puts it
    --offset ROLE=DB,...   your own taste on top, per role, e.g. --offset bass=-1.5,hats=-2 (roles: lead_vocal,
                           backing_vocal, kick, snare, hats, toms, overheads, drums, bass, guitar, keys, synth,
                           strings, pad, brass, fx, other)
    --keep-level           do not shift the whole balance so the loudest fader lands on 0 dB
    --min-move DB          leave a part alone when its move is smaller than this (default 0.5)
    --max-move DB          never move a part further than this (default 12)

Usage:
    hypnomix balance STEMS_DIR [options]                  report only
    hypnomix balance STEMS_DIR --plan [SCAN_DIR] [options]   the moves become findings for the normal review;
                                                          `hypnomix fix SCAN_DIR --approved` then renders only the
                                                          approved moves into SCAN_DIR/fixed/balance/ (each stem
                                                          with its fader move baked in, plus a trial mix)
    hypnomix balance STEMS_DIR --render [--out DIR]       render every proposed move at once, into new files
"""
import argparse, json, sys, time
from pathlib import Path

import numpy as np

from hypnomix.core import dsp
from hypnomix.core.paths import out_at
from hypnomix.engineer import roles, masking

ANCHOR_LUFS = -20.0        # where the anchor part sits (before the optional shift to 0 dB)


# ---------------------------------------------------------------- measuring
def measure(folder):
    """-> (stems [(name, y)], sr, rows {name: dict(role, how, lufs)})."""
    stems, sr = masking.load_stems(folder)
    if not stems:
        raise SystemExit(f"no audio files in {folder}")
    cls = roles.classify_all(stems, sr)
    rows = {n: dict(role=cls[n][0], how=cls[n][1], lufs=round(float(dsp.active_lufs(y, sr)), 1)) for n, y in stems}
    return stems, sr, rows


def parse_offsets(text):
    out = {}
    for part in (text or "").replace(";", ",").split(","):
        if not part.strip():
            continue
        if "=" not in part:
            raise SystemExit(f"--offset wants ROLE=DB (got {part!r})")
        k, v = part.split("=", 1)
        k = k.strip().lower().replace(" ", "_")
        if k not in roles.ROLES:
            raise SystemExit(f"unknown role {k!r}; roles: {', '.join(roles.ROLES)}")
        out[k] = float(v)
    return out


def band_lufs(stems, sr, gains, skip):
    """Loudness (while playing) of every stem not in `skip`, summed with its gain."""
    parts = [y * dsp.undb(gains.get(n, 0.0)) for n, y in stems if n not in skip]
    if not parts:
        return None
    return float(dsp.active_lufs(sum(parts), sr))


def propose(stems, sr, rows, anchor=None, vocal_over_band=None, offsets=None, keep_level=False,
            min_move=0.5, max_move=12.0):
    """The fader moves. Returns dict(moves=[...], anchor=name, vocal=dict(before, after, wanted), notes=[...])."""
    offsets = offsets or {}
    notes = []
    names = [n for n, _ in stems]
    if anchor:
        hit = next((n for n in names if n.lower() == anchor.lower()), None) or \
            next((n for n in names if anchor.lower() in n.lower()), None)
        if hit is None:
            raise SystemExit(f"--anchor {anchor!r} matches no stem ({', '.join(names)})")
        anchor = hit
    else:
        leads = [n for n in names if rows[n]["role"] == "lead_vocal"]
        anchor = leads[0] if leads else max(names, key=lambda n: (roles.preset(rows[n]["role"])["prio"], rows[n]["lufs"]))
        if not leads:
            notes.append(f"no lead vocal found: {anchor} is the anchor part")
    a_level = roles.preset(rows[anchor]["role"])["level"]
    want = {n: ANCHOR_LUFS + roles.preset(rows[n]["role"])["level"] - a_level + offsets.get(rows[n]["role"], 0.0)
            for n in names}
    gain = {n: float(np.clip(want[n] - rows[n]["lufs"], -40, 30)) for n in names}
    silent = [n for n in names if rows[n]["lufs"] <= -69]
    for n in silent:
        gain[n] = 0.0
    voc = [n for n in names if rows[n]["role"] == "lead_vocal"]
    rest = [n for n in names if n not in voc]

    def vocal_gap(g):
        if not voc or not rest:
            return None, None
        v = band_lufs(stems, sr, g, set(rest))
        b = band_lufs(stems, sr, g, set(voc))
        return v, b

    zero = {n: 0.0 for n in names}
    v0, b0 = vocal_gap(zero)
    if vocal_over_band is not None:
        if not voc:
            notes.append("--vocal-over-band ignored: there is no lead vocal in this folder")
        elif not rest:
            notes.append("--vocal-over-band ignored: there is nothing but vocals in this folder")
        else:
            v1, b1 = vocal_gap(gain)
            shift = (b1 + vocal_over_band) - v1          # moves the vocal(s) only; the band stays where it is
            for n in voc:
                gain[n] += shift
    if not keep_level and gain:
        top = max(gain.values())
        for n in names:
            gain[n] -= top
        notes.append(f"the whole balance sits {top:+.1f} dB lower so the loudest fader is at 0 dB "
                     "(headroom for the sum; --keep-level to keep the loudness)" if abs(top) > 0.05
                     else "the loudest fader stays at 0 dB")
    v2, b2 = vocal_gap(gain)
    moves = []
    for n in names:
        g = round(float(np.clip(gain[n], -max_move, max_move)), 1)
        if g != round(gain[n], 1):
            notes.append(f"{n}: the move was limited to {max_move:g} dB (--max-move)")
        moves.append(dict(name=n, role=rows[n]["role"], how=rows[n]["how"], lufs=rows[n]["lufs"], gain_db=g,
                          after_lufs=round(rows[n]["lufs"] + g, 1),
                          vs_anchor_db=round(rows[n]["lufs"] + g - (rows[anchor]["lufs"] + gain[anchor]), 1),
                          silent=n in silent, small=abs(g) < min_move and n not in silent))
    return dict(moves=moves, anchor=anchor, notes=notes,
                vocal=dict(before=None if v0 is None else round(v0 - b0, 1), after=None if v2 is None else round(v2 - b2, 1),
                           wanted=vocal_over_band))


def profile_note(profile):
    """The person's own fader range from `hypnomix profile`, or None."""
    f = ((profile or {}).get("sessions") or {}).get("fader_db")
    return f if isinstance(f, dict) and f.get("n") else None


def load_profile():
    try:
        from hypnomix.core.paths import PROFILE
        p = Path(PROFILE)
        return json.loads(p.read_text()) if p.exists() else None
    except Exception:
        return None


def judge(move, rng):
    """'inside' / 'below' / 'above' your usual fader range, or None without a profile."""
    if not rng:
        return None
    g = move["gain_db"]
    if g < rng["p25"] - 3:
        return f"{rng['p25'] - g:.1f} dB below your usual faders"
    if g > rng["p75"] + 3:
        return f"{g - rng['p75']:.1f} dB above your usual faders"
    return "inside your usual faders"


# ---------------------------------------------------------------- report
def report(folder, res, rng):
    L = [f"# Balance: {Path(folder).name}", "",
         f"Anchor part: **{res['anchor']}**. Faders only: no EQ, no compression, no pan. Measured, not heard: "
         "the numbers are a starting place for your ears.", ""]
    head = "| part | role | plays at | move | lands at | vs anchor |" + (" your range |" if rng else "")
    L += [head, "|---|---|---|---|---|---|" + ("---|" if rng else "")]
    for m in res["moves"]:
        mv = "leave (silent)" if m["silent"] else ("leave" if m["small"] else f"{m['gain_db']:+.1f} dB")
        row = (f"| {m['name']} | {m['role'].replace('_', ' ')} (by {m['how']}) | {m['lufs']:.1f} LUFS | {mv} | "
               f"{m['after_lufs']:.1f} | {m['vs_anchor_db']:+.1f} dB |")
        if rng:
            row += f" {judge(m, rng) or ''} |"
        L.append(row)
    v = res["vocal"]
    L.append("")
    if v["before"] is not None:
        L.append(f"Vocal against the band (everything else played together): {v['before']:+.1f} dB as recorded → "
                 f"{v['after']:+.1f} dB with these moves"
                 + (f" (you asked for {v['wanted']:+.1f})." if v["wanted"] is not None else "."))
    if rng:
        L.append(f"Your own faders across {rng['n']} tracks: middle half {rng['p25']:.1f} to {rng['p75']:.1f} dB "
                 f"(median {rng['median']:.1f}). A move far outside that is flagged, not blocked.")
    else:
        L.append("No profile yet, so nothing here is compared with your own faders (`hypnomix profile build … --sets …`).")
    L += [""] + [f"- {n}" for n in res["notes"]]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- rendering (new files only)
def render(folder, gains, out, keys=None, name=None):
    """Write each moved stem (fader move baked in) and a trial mix into `out`. `gains`: {stem: dB}; `keys`: only these.
    Returns the list of files written. Never overwrites."""
    out = Path(out)
    stems, sr = masking.load_stems(folder)
    use = {n: g for n, g in gains.items() if keys is None or n in keys}
    if not use:
        raise SystemExit("no approved moves to render")
    out.mkdir(parents=True, exist_ok=True)
    files, mix = [], None
    for n, y in stems:
        z = y * dsp.undb(use.get(n, 0.0))
        mix = z if mix is None else mix + z
        if n in use:
            dest = out / f"{n} (fader {use[n]:+.1f} dB).wav"
            if dest.exists():
                raise SystemExit(f"refusing to overwrite {dest}")
            files.append(dsp.save(dest, z, sr, 24))
    pk = dsp.sample_peak(mix)
    safe = ""
    if pk > -1.0:
        mix = mix * dsp.undb(-1.0 - pk)
        safe = f" (turned down {pk + 1.0:.1f} dB to stay under -1 dBFS)"
    dest = out / f"{name or Path(folder).resolve().name} (balance mix).wav"
    if dest.exists():
        raise SystemExit(f"refusing to overwrite {dest}")
    files.append(dsp.save(dest, mix, sr, 24))
    print(f"trial mix{safe}: {dest}")
    return files


def plan_findings(folder, res, options, rng):
    src = str(Path(folder).resolve())
    F = []
    for m in res["moves"]:
        if m["silent"] or m["small"]:
            continue
        j = judge(m, rng)
        F.append(dict(
            kind="fader", severity="low", track=m["name"], applies="audio",
            problem=(f"fader {m['gain_db']:+.1f} dB: this {m['role'].replace('_', ' ')} plays at {m['lufs']:.1f} LUFS, "
                     f"{m['vs_anchor_db']:+.1f} dB against {res['anchor']} after the move"
                     + (f"; {j}" if j else "")),
            fix="a starting balance: move the fader until it feels right. Faders only: no EQ or compression.",
            plan=dict(tool="balance", file=src, key=f"fader:{m['name']}", gain_db=m["gain_db"], **options)))
    return F


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hypnomix balance", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--anchor")
    ap.add_argument("--vocal-over-band", type=float, metavar="DB")
    ap.add_argument("--offset", default="", metavar="ROLE=DB,...")
    ap.add_argument("--keep-level", action="store_true")
    ap.add_argument("--min-move", type=float, default=0.5)
    ap.add_argument("--max-move", type=float, default=12.0)
    ap.add_argument("--plan", nargs="?", const=True, metavar="SCAN_DIR",
                    help="change nothing: every fader move becomes a finding for review")
    ap.add_argument("--render", action="store_true", help="render every proposed move into new files")
    ap.add_argument("--only", metavar="MOVES.json", help="(used by fix) a JSON {stem: dB} of approved moves to render")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    if not folder.is_dir():
        sys.exit(f"{folder} is not a folder of stems")
    if a.only:
        gains = json.loads(Path(a.only).read_text())
        od = out_at(a.out, "balance", folder.resolve().name)
        files = render(folder, gains, od)
        print(f"{len(files) - 1} moved stem(s) written to {od}")
        return
    t0 = time.time()
    stems, sr, rows = measure(folder)
    options = dict(anchor=a.anchor, vocal_over_band=a.vocal_over_band, offset=a.offset, keep_level=a.keep_level)
    res = propose(stems, sr, rows, a.anchor, a.vocal_over_band, parse_offsets(a.offset), a.keep_level,
                  a.min_move, a.max_move)
    rng = profile_note(load_profile())
    text = report(folder, res, rng)
    if a.plan:
        from hypnomix.workflow import plan as PL
        sd = PL.scan_dir(a.plan, folder)
        note = ["balance plan: one fader move per part (faders only). Nothing was written next to your stems.",
                "approved moves are rendered into fixed/balance/ as new stems plus a trial mix"]
        PL.write(sd, "balance", folder, plan_findings(folder, res, options, rng), note, time.time() - t0)
        (sd / "raw").mkdir(exist_ok=True)
        (sd / "raw" / "balance.md").write_text(text)
        print(text)
        return
    print(text)
    if a.render:
        od = out_at(a.out, "balance", folder.resolve().name)
        files = render(folder, {m["name"]: m["gain_db"] for m in res["moves"] if not m["silent"] and not m["small"]}, od)
        (od / "BALANCE.md").write_text(text)
        print(f"→ {od}")
    else:
        print("Report only: nothing was written. `--plan` sends the moves to the review; `--render` writes new files.")


if __name__ == "__main__":
    main()
