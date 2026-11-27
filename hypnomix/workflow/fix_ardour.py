"""`hypnomix fix` for an Ardour session: approved findings into ONE new .ardour snapshot beside the original.

Called by `fix` when the scan was of an .ardour session. In one pass, on the parsed session:

  clicks  a short region fade (never shortens a fade that is there), written as a curve (note `shape=linear|power|slow`)
  cuts    short fades either side of the cut, and the region after it starts `amount` of the jump quieter and eases
          back to normal (a gain envelope on that region; note `method=item` sets the region gain instead;
          `amount=0.3`, `ease-ms=500`)
  spikes  a quick dip in the gain envelope of the region(s) over the burst (note `amount=` scales it)
  mixer   a finding may carry a `mixer` edit: fader (dB), pan (-1..+1) and mute on a route
  mpe     the MPE glide fix: Discrete interpolation for a MIDI source's bend, channel pressure and CC 74 lists
          (all 16 channels, and per-note pressure where the clip has it), so values hold instead of gliding

Everything else (track names and order, vocal stacks, timing, sidechain, tuning) stays by hand for an Ardour session.

Where the file goes: next to the original, inside the same session folder, as a new snapshot (`Song (fixed).ardour`).
Ardour keeps its snapshots the same way, and finds a session's audio from the session folder
(interchange/<session>/audiofiles), which the new file shares with the original. Nothing else is copied or moved.

Safety: every approved finding is found again by its region id (else track + position); if it is not there it is
skipped and reported. The new file is read back and checked (see ardour_edit.check): same tracks, folders, regions,
positions and lengths; ids unique; fade and envelope times well-formed; regions inside their files; and nothing
outside the approved edits differs. A failing file is renamed "(BROKEN, do not open)".

Written and re-read by HypnoMix; not yet opened in Ardour.
"""
from hypnomix import project as PJ
from hypnomix.project import ardour_edit as E
from hypnomix.project import mpe as MP
from hypnomix.workflow.fix_project import _kv, verify_clips


def apply_edits(p, items, dec, log, failed, skipped):
    done = []
    rank = {"fade": 0, "cut": 1, "dip": 1, "mixer": 2, "mpe-discrete": 3}
    for f in sorted(items, key=lambda f: (rank.get((f.get("edit") or {}).get("op"), 9), f["id"])):
        ed = f.get("edit")
        if not ed or ed.get("op") not in rank:
            skipped.append((f, "a HypnoMix Studio session is written for fades, cuts, spikes, mixer moves and the MPE glide fix only: do this one by hand"))
            continue
        kv = _kv(dec, f)
        try:
            if ed["op"] == "mpe-discrete":
                if not any(s.get("id") == ed.get("source") and s.get("type") == "midi" for s in p.native.iter("Source")):
                    skipped.append((f, "its MIDI source is no longer in the session (changed since the scan?)"))
                    continue
                k = MP.write_discrete(p.native, ed["source"], list(ed.get("params") or []))
                log.append(f"- {f['id']}: {f.get('track', '')}: {ed.get('name', '')}: Discrete interpolation for "
                           f"{len(ed.get('params') or [])} bend, pressure and slide lists ({k} changed)")
                done.append(f["id"])
                continue
            if ed["op"] == "mixer":
                tr = p.track(f["track"])
                if tr is None or tr.name != f["track"]:
                    skipped.append((f, "its track is no longer in the session (changed since the scan?)"))
                    continue
                parts = []
                if ed.get("fader_db"):
                    E.fader(tr, float(ed["fader_db"]))
                    parts.append(f"fader {float(ed['fader_db']):+.1f} dB")
                if ed.get("pan") is not None:
                    E.pan(tr, float(ed["pan"]))
                    parts.append(f"pan {float(ed['pan']):+.2f}")
                if ed.get("mute") is not None:
                    E.mute(tr, bool(ed["mute"]))
                    parts.append("muted" if ed["mute"] else "unmuted")
                log.append(f"- {f['id']}: {tr.name}: " + ", ".join(parts))
                done.append(f["id"])
                continue
            hit = E.locate(p, ed["item"]) if "item" in ed else None
            tr = hit[0] if hit else next((t for t in p.tracks if t.name == f["track"]), None)
            if tr is None or tr.name != f["track"] or (ed["op"] in ("fade", "cut") and hit is None):
                skipped.append((f, "its region or track is no longer in the session (changed since the scan?)"))
                continue
            amount = float(kv.get("amount", ed.get("amount", 0.5)))
            shape = kv.get("shape", "linear")
            if ed["op"] == "fade":
                ch = E.fade(p, hit[1], ed["which"], float(kv.get("fade-ms", ed["seconds"] * 1000)) / 1000, shape)
                log.append(f"- {f['id']}: {tr.name} @ {hit[1].start:.3f} s: fade {ed['which']} "
                           + ("set" if ch else "already long enough, left as it was"))
            elif ed["op"] == "cut":
                prev = E.locate(p, ed["prev"]) if ed.get("prev") else None
                fs = float(kv.get("fade-ms", ed.get("fade", 0.005) * 1000)) / 1000
                if prev:
                    E.fade(p, prev[1], "out", fs, shape)
                E.fade(p, hit[1], "in", fs, shape)
                if kv.get("method") == "item":
                    E.region_gain(hit[1], -ed["size"] * amount)
                    log.append(f"- {f['id']}: {tr.name} @ {ed['t']:.3f} s: region gain {-ed['size'] * amount:+.1f} dB, "
                               f"{fs * 1000:.0f} ms fades at the cut")
                else:
                    ease_s = float(kv.get("ease-ms", ed.get("ease", 0.3) * 1000)) / 1000
                    E.ease(p, hit[1], -ed["size"] * amount, ease_s)
                    log.append(f"- {f['id']}: {tr.name} @ {ed['t']:.3f} s: {-ed['size'] * amount:+.1f} dB at the start of "
                               f"the region, back to normal over {ease_s * 1000:.0f} ms, {fs * 1000:.0f} ms fades at the cut")
            else:
                db = float(ed["db"]) * (amount / 0.5)
                n = E.dip(p, tr, ed["t0"], ed["t1"], db, ed.get("ramp", 0.02))
                if not n:
                    skipped.append((f, "no sounding region is under the burst any more"))
                    continue
                log.append(f"- {f['id']}: {tr.name} {ed['t0']:.3f}-{ed['t1']:.3f} s: gain dip {-db:.1f} dB "
                           f"in {n} region(s)")
            done.append(f["id"])
        except ValueError as e:
            failed.append(f"{f['id']}: {e}")
    return done


def run(sd, scan, src, out, set_items, dec, verify=True):
    """Returns (out or None, log lines, failed, skipped)."""
    log, failed, skipped = [], [], []
    p = PJ.load(src)
    done = apply_edits(p, set_items, dec, log, failed, skipped)
    print(f"edits      {len(done)} of {len(set_items)} approved written")
    if not done:
        return None, log, failed, skipped
    E.save(p, out)
    errs = E.check(src, out)
    if errs:
        bad = out.with_name(out.stem + " (BROKEN, do not open).ardour")
        out.rename(bad)
        failed += [f"structure check: {e}" for e in errs]
        log += ["### structure check: FAILED", ""] + [f"- {e}" for e in errs] + [""]
        print(f"check      FAILED: the written session is not sound. Renamed to {bad.name}; keep using the original.")
        return None, log, failed, skipped
    print(f"check      structure OK; wrote {out}")
    changes = E.diff(src, out)
    log += ["### structure check: OK (same tracks, folders, regions, positions and lengths; nothing else differs)", "",
            "### what changed (the new session read back)", ""] + [f"- {c}" for c in changes] + [""]
    print("changed    read back from the new file:")
    for c in changes:
        print(f"           - {c}")
    clip_items = [f for f in set_items if f["id"] in done and f.get("tool") == "clips"]
    if verify and clip_items:
        log += verify_clips(out, sd, clip_items, {})
    return out, log, failed, skipped
