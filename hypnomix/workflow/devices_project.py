"""The `devices` check on a REAPER project: Live's `hypnomix devices`, on REAPER's own plug-ins in the .rpp.

Every heard audio track's render (items as they play, no FX, no fader: what the first plug-in gets) is played
through its FX chain in order, so each plug-in is judged on the signal it really gets:

  ReaComp   read from the .rpp (the raw floats `sidechain_project` reads; units in docs/REAPER.md) and judged
            with the same model and the same targets as a Live Compressor: how much it turns the part down while
            it plays, whether it barely works or squashes, a release faster than two cycles of the bass notes,
            drum transients clamped. The suggestion (threshold, ratio, attack, release) is `set`: `fix` writes
            those four floats into the ReaComp in the new .rpp and leaves the rest of its state byte for byte.
            A ReaComp listening to channels 3/4 (a sidechain) is left to the effects group's sidechain check.
            Only a fully wet ReaComp is judged (Dry under -30 dB, Wet at -1 dB or more, REAPER's own default):
            the targets describe a compressor on the whole signal. One with Wet at 0 (under -60 dB) does not
            compress at all and is not judged; one that mixes dry and wet (parallel compression) is listed as
            parallel and not judged, and no `set` fix is offered for either, so a deliberate parallel setup is
            never rewritten. The level after a parallel ReaComp is not modelled, so later plug-ins are not judged.
  ReaEQ     read from the .rpp (`rpp_edit.ReaEQ`): a part that is not bass or drums, with real energy under
            80 Hz, a ReaEQ on the track and no high-pass band switched on gets a low-cut suggestion (by hand).
  ReaGate,  their saved settings are not read: the layout of their state in the .rpp has not been measured in
  ReaLimit  REAPER, so they are listed as not judged, never guessed at.

Any other plug-in (JS, third-party) changes the level in a way this check does not model: plug-ins after it are
listed but not judged. ReaComp's output (wet / dry) gain is not modelled either: a second compressor after a
ReaComp is judged on the level after the first one's gain reduction. Folder tracks and MIDI tracks have no render
of their own here, so their plug-ins are not judged. The master track's plug-ins (MASTERFXLIST) are not read by
the project model, so they are not judged and are not listed. HypnoMix DAW sessions: the plug-ins' settings are not in the shared
model, so the group is skipped there with a note.
"""
import math

import numpy as np

from hypnomix.engineer import devices as DV
from hypnomix.engineer import sidechain as SC
from hypnomix.project import rpp_edit as E
from hypnomix.workflow import sidechain_project as SCP

KEYS = ("threshold_db", "ratio", "attack", "release")
DRUM_ROLES = ("kick", "snare", "hats", "toms", "overheads", "drums")
UNREAD = {"reagate": "gate", "realimit": "limiter"}
FULL_DRY = 10 ** (-30 / 20)        # Dry at or under -30 dB counts as no dry signal (REAPER's default is -150 dB)
FULL_WET = 10 ** (-1 / 20)         # Wet at or over -1 dB counts as fully wet (REAPER's default is 0 dB)
NO_WET = 10 ** (-60 / 20)          # Wet under -60 dB: the compressed path is not heard


def mix(vals):
    """'wet', 'dry' (Wet at 0: no compression heard) or 'parallel', from ReaComp's Dry and Wet raw amplitudes."""
    g = lambda k: vals[SCP.P[k]] if SCP.P[k] < len(vals) else None
    dry, wet = g("dry"), g("wet")
    if dry is None or wet is None:
        return "wet", dry, wet
    if wet < NO_WET:
        return "dry", dry, wet
    if dry <= FULL_DRY and wet >= FULL_WET:
        return "wet", dry, wet
    return "parallel", dry, wet


def _db(v):
    return "-inf" if v is None or v <= 1e-9 else f"{20 * math.log10(v):.0f}"


def part(role):
    """scan_project's roles (engineer.roles) -> the devices check's kinds of part."""
    if role == "lead_vocal":
        return "lead"
    if role == "backing_vocal":
        return "harmony"
    if role == "bass":
        return "bass"
    if role in DRUM_ROLES:
        return "drums"
    return "other"


def _label(d):
    """The name the person gave the plug-in in REAPER (the VST line's fifth field), else its own name."""
    tk = getattr(d.native, "tokens", None) or []
    renamed = str(tk[4]).strip() if d.kind.startswith("VST") and len(tk) > 4 else ""
    return renamed or d.name


def review(p, R, role):
    """[item dicts], [notes] for every heard audio track with plug-ins."""
    items, notes, skipped, dup = [], [], [], []
    names = {}
    for t in p.tracks:
        names[t.name] = names.get(t.name, 0) + 1
    for t in p.tracks:
        devs = list(t.devices)
        if not devs:
            continue
        if names[t.name] > 1:                          # renders are keyed by name: a shared name is ambiguous
            if t.name not in dup:
                dup.append(t.name)
            continue
        if t.kind == "folder" or t.name not in R.files:
            skipped.append(t.name)
            continue
        if t.native is not None and t.native.get("FX", cast=int, default=1) == 0:
            continue                                   # the effects group says the chain is off
        x = SC.load_mono(str(R.files[t.name]))
        kind = part(role.get(t.name))
        f0 = SC.lowest_note(x) if kind in ("bass", "drums") else None
        known, eqs, lo_cut, unread = True, 0, False, []
        for k, d in enumerate(devs):
            if not d.on:
                continue
            low = d.name.lower()
            label = _label(d)
            base = dict(track=t.name, index=t.index, fx=k, device=label, role=kind)
            if "reaeq" in low:
                try:
                    st = E.ReaEQ(d.native)
                except Exception:
                    unread.append(label)
                    continue
                eqs += 1                               # only a ReaEQ whose bands were read counts
                if any(b["on"] and b["type"] == 4 for b in st.bands):    # 4 = high pass
                    lo_cut = True
                continue
            if "reacomp" in low:
                try:
                    st = SCP.State(d.native)
                except Exception:
                    unread.append(label)
                    known = False
                    continue
                c = SCP.settings(st.vals)
                if c["channel"] >= 1:
                    notes.append(f"devices: '{label}' on {t.name} listens to channels {c['channel'] + 1}/"
                                 f"{c['channel'] + 2} (a sidechain): the effects group's sidechain check covers it")
                    continue
                how, dry, wet = mix(st.vals)
                if how == "dry":
                    items.append(dict(base, kind="unknown", fkind="reacomp-dry", problem=f"ReaComp '{label}' has Wet at {_db(wet)} dB, so "
                                      "none of its compression is heard: it isn't judged"))
                    if dry is None or abs(20 * math.log10(max(dry, 1e-9))) > 0.5:
                        known = False                  # the dry path changes the level (or mutes it)
                    continue
                if how == "parallel":
                    items.append(dict(base, kind="unknown", fkind="reacomp-parallel", problem=f"ReaComp '{label}' mixes dry ({_db(dry)} dB) and "
                                      f"wet ({_db(wet)} dB): parallel compression. Its usual ranges are for a fully "
                                      "wet compressor, so it isn't judged and nothing is changed"))
                    known = False                      # the level after a parallel mix is not modelled
                    continue
                if not known:
                    items.append(dict(base, kind="unknown", problem=f"after a plug-in this check does not model: the "
                                      f"level reaching '{label}' is unknown, so it isn't judged"))
                    continue
                act, _, _ = DV.active(x)
                gr, m, new, m2, problems, target = DV.judge_compressor(x, act, dict(c), kind, p.tempo, f0)
                items.append(dict(base, kind="compressor", cur=c, new=new, m=m, m2=m2, problems=problems,
                                  target=target, vals=[float(v) for v in st.vals]))
                x = x * (10 ** (gr / 20))
                continue
            what = next((v for w, v in UNREAD.items() if w in low), None)
            if what:
                items.append(dict(base, kind="unread", what=what))
            known = False                              # the level after it is not modelled
        if kind not in ("bass", "drums") and eqs and not lo_cut:
            spec = np.abs(np.fft.rfft(x[: SC.SR * 60]))
            fr = np.fft.rfftfreq(min(len(x), SC.SR * 60), 1 / SC.SR)
            e_low = 10 * math.log10(max(1e-12, (spec[fr < 80] ** 2).sum() / max(1e-12, (spec ** 2).sum())))
            if e_low > -25:
                items.append(dict(track=t.name, index=t.index, fx=None, device="ReaEQ", role=kind, kind="eq-lowcut",
                                  e_low=e_low))
        if unread:
            notes.append(f"devices: {t.name}: {', '.join(unread)}: saved state not in a layout this check reads")
    if dup:
        notes.append("devices: more than one track is called " + ", ".join(f"'{n}'" for n in dup[:8])
                     + (" ..." if len(dup) > 8 else "") + ": their plug-ins are not judged (rename them and re-scan)")
    if skipped:
        notes.append("devices: plug-ins on folder, MIDI or silent tracks not judged (no render of their own; the "
                     "master track's plug-ins are not read at all): "
                     + ", ".join(skipped[:8]) + (" ..." if len(skipped) > 8 else ""))
    return items, notes


def findings(p, items):
    out = []
    for n, it in enumerate(items, 1):
        base = dict(id=f"devices-{n}", tool="devices", track=it["track"], where="", device=it["device"])
        if it["kind"] == "compressor":
            c, w = it["cur"], it["new"]
            m, m2 = ({k: v + 0.0 for k, v in d.items()} for d in (it["m"], it["m2"]))     # no "-0.0 dB"
            lo, hi = it["target"]
            fmt = lambda s: (f"threshold {s['threshold_db']:.1f} dB, ratio "
                             f"{'inf' if s['ratio'] >= 999 else format(s['ratio'], '.1f')}:1, attack {s['attack']:.3g} ms, "
                             f"release {s['release']:.0f} ms")
            ok = not it["problems"] and lo <= m["median"] <= hi * 1.25
            f = dict(base, kind="compressor", severity="info" if ok else ("medium" if len(it["problems"]) > 1 else "low"),
                     problem=(f"ReaComp '{it['device']}' ({it['role']}): turns the part down {m['median']:.1f} dB while "
                              f"it plays ({m['loud']:.0f} dB on loud moments, working {m['working']:.0%} of the time); now "
                              f"{fmt(c)}" + ("; " + "; ".join(it["problems"]) if it["problems"] else
                                             ("; within the usual range for this kind of part" if ok else ""))),
                     fix=(f"fine as it is (a suggestion for {lo}-{hi} dB anyway: {fmt(w)})" if ok else
                          f"try {fmt(w)} in the ReaComp: about {m2['median']:.1f} dB while it plays ({lo}-{hi} dB is "
                          "usual for this kind of part). An option"),
                     applies="info" if ok else "manual", settings={k: float(w[k]) for k in KEYS})
            if not ok and p.daw == "reaper":
                f.update(applies="set", edit=dict(op="reacomp", track=it["track"], index=it["index"], fx=it["fx"],
                                                  cur=it["vals"], settings=f["settings"]))
            out.append(f)
        elif it["kind"] == "eq-lowcut":
            out.append(dict(base, kind="eq-lowcut", severity="low",
                            problem=f"{it['e_low']:.0f} dB of its energy is under 80 Hz and no ReaEQ band on the track "
                                    "is a high pass: rumble under the bass",
                            fix="open the ReaEQ on the track and set a free band's type to High Pass at about 80-100 Hz, "
                                "by ear: it clears room for the bass", applies="manual"))
        elif it["kind"] == "unread":
            how = ("a threshold just above the noise and under the quietest words" if it["what"] == "gate" else
                   "about 1-2 dB on the loudest moments catches peaks; more is crushing the part")
            out.append(dict(base, kind=f"{it['what']}-unread", severity="info", applies="info",
                            problem=f"'{it['device']}': its saved settings are not read (their layout in the .rpp has "
                                    "not been measured in REAPER), so it isn't judged",
                            fix=f"check it by ear in REAPER: {how}"))
        elif it["kind"] == "unknown":
            out.append(dict(base, kind=it.get("fkind", "unknown-level"), severity="info", applies="info", problem=it["problem"],
                            fix="check it by ear"))
    return out


def g_devices(p, R, od, a, role):
    if p.daw != "reaper":
        return [], ["devices: skipped for a HypnoMix DAW session (its plug-ins' settings are not read yet)"]
    items, notes = review(p, R, role)
    fs = findings(p, items)
    n_set = sum(1 for f in fs if f["applies"] == "set")
    return fs, [f"devices: {sum(1 for f in fs if f['kind'] == 'compressor')} ReaComp(s) judged on their track's own "
                f"audio; {n_set} suggestion(s) `fix` can write into the ReaComp (threshold, ratio, attack, release); "
                "ReaGate and ReaLimit are listed, not judged (their saved settings are not read); a ReaComp with "
                "Wet at 0 or a parallel (dry and wet) mix is not judged; the master track's plug-ins are not read"] + notes


# ---------------------------------------------------------------- writing an approved suggestion
def raw(settings):
    """{parameter index: raw float} for the four settings a suggestion changes (units: docs/REAPER.md)."""
    r = settings["ratio"]
    return {SCP.P["thresh"]: float(10 ** (settings["threshold_db"] / 20)),
            SCP.P["ratio"]: 1.0 if r >= 999 else float(min(1.0, max(0.0, (r - 1) / 99))),
            SCP.P["attack"]: float(min(1.0, max(0.0, settings["attack"] / 500))),
            SCP.P["release"]: float(min(1.0, max(0.0, settings["release"] / 5000)))}


def blend(cur, new, share):
    """The settings `share` (0-1) of the way from the ReaComp's current ones to the suggestion."""
    if share >= 1:
        return dict(new)
    out = {}
    for k in KEYS:
        a_, b_ = cur[k], new[k]
        if k == "ratio":                                 # in REAPER's raw space (inf = 1.0, r = (r-1)/99), so a
            ra = 1.0 if a_ >= 999 else (a_ - 1) / 99     # partial approval from "inf" stays partial: inf -> 4:1
            rb = 1.0 if b_ >= 999 else (b_ - 1) / 99     # at 10% gives about 90:1
            rr = ra + (rb - ra) * share
            out[k] = 1000.0 if rr >= 0.9999 else 1 + rr * 99
        else:
            out[k] = a_ + (b_ - a_) * share
    return out


def apply(p, f, ed, share=1.0):
    """Write one approved ReaComp suggestion into the loaded project. Returns a log line; ValueError if the
    ReaComp is not as the scan found it."""
    t = next((x for x in p.tracks if x.index == ed.get("index") and x.name == ed["track"]), None)
    if t is None:
        same = [x for x in p.tracks if x.name == ed["track"]]
        if len(same) > 1:
            raise ValueError(f"two tracks are called '{ed['track']}': re-scan")
        t = same[0] if same else None
    if t is None or ed["fx"] >= len(t.devices) or "reacomp" not in t.devices[ed["fx"]].name.lower():
        raise ValueError(f"the ReaComp on '{ed['track']}' is no longer where the scan found it")
    st = SCP.State(t.devices[ed["fx"]].native)
    if len(st.vals) != len(ed["cur"]) or any(abs(a - b) > 1e-6 for a, b in zip(st.vals, ed["cur"])):
        raise ValueError(f"the ReaComp on '{ed['track']}' was changed since the scan: re-scan")
    c = SCP.settings(st.vals)
    want = blend(c, ed["settings"], share)
    for i, v in raw(want).items():
        st.vals[i] = v
    st.write()
    back = SCP.settings(st.vals)
    return (f"- {f['id']}: ReaComp on {t.name}: threshold {back['threshold_db']:.1f} dB, ratio "
            f"{'inf' if back['ratio'] >= 999 else format(back['ratio'], '.1f')}:1, attack {back['attack']:.3g} ms, "
            f"release {back['release']:.0f} ms" + (f" ({share * 100:.0f}% of the way)" if share < 1 else ""))
