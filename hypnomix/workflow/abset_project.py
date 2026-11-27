"""A/B inside REAPER: one new project where every proposed fix sits next to what you have, switched off, so you hear
it with every plug-in, in place, instantly. The REAPER side of `hypnomix abset` (same ab_live.json for the app).

For each finding that changes the project, the fix is built on its own (`fix` on a throwaway copy of the scan) and
compared with the original, track by track (tracks matched by their REAPER GUID):

  plug-in changes   (a retuned ReaComp)  the changed plug-in is copied in right after yours and bypassed.
                    A = yours on, the copy bypassed; B = the other way.
  anything else     (fades, rides, edges, timing markers, new takes, moved items)  the whole track is copied with
                    the fix, named "<track> · B <id>", muted, right after yours, in the same folder, sending where
                    yours sends. A/B swaps which one is muted.

The project plays exactly like the original (every B is off). `hypnomix reaper review` then opens the HypnoMix Review panel
in REAPER: A / B / Blind and loudness matching for the finding you are on. Approving still happens in the review, and
`fix --approved` still writes the real new project from the original. Not previewable this way: track names and
order (nothing to hear).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SKIP_TOOLS = {"name", "order", "tidy", "refs", "unroll", "intent", "audit"}


def candidates(findings, ids=None):
    want = {x.strip() for x in (ids or "").split(",") if x.strip()}
    if want:
        return [f for f in findings if f["id"] in want or str(f.get("n")) in want]
    return [f for f in findings if f.get("applies") == "set" and f.get("tool") not in SKIP_TOOLS]


def fixed_copy(sd, fid, orig, extra=()):
    """This one fix, written into a temporary project next to the original (from a throwaway copy of the scan)."""
    from hypnomix.workflow import abset as A      # the same throwaway copy and the same reason as for a Live set
    return A.fixed_copy(sd, fid, orig, extra, ".rpp")


def gid(t):
    return t.native.tokens[1] if len(t.native.tokens) > 1 else f"#{t.index}"


def _text(chunk):
    return "\n".join(l.strip() for l in chunk.text_lines())


def _fx_blocks(chain):
    """[(lines and chunk of one plug-in)] from an FXCHAIN: BYPASS, the plug-in chunk, then its trailing lines."""
    from hypnomix.project import rpp
    out, cur = [], None
    for c in (chain.children if chain is not None else []):
        if isinstance(c, rpp.Line) and c.key == "BYPASS":
            cur = [c]
            out.append(cur)
        elif cur is not None:
            cur.append(c)
    return out


def _rest(track):
    """A track without its plug-in chain (to tell plug-in-only changes from everything else)."""
    from hypnomix.project import rpp
    return "\n".join(_text(c) if isinstance(c, rpp.Chunk) else c.text().strip()
                     for c in track.native.children
                     if not (isinstance(c, rpp.Chunk) and c.name == "FXCHAIN") and not (isinstance(c, rpp.Line) and c.key in ("SEL",)))


def build_one(ab, orig, fixed, fid, copies, b_fx):
    """Record one finding's B: plug-in copies are inserted now; track copies are collected in `copies` (inserted all
    at once at the end, so positions stay valid). Returns (parts, notes)."""
    import copy as _copy
    from hypnomix.project import rpp
    from hypnomix.project import rpp_edit as E
    O = {gid(t): t for t in orig.tracks}
    AB = {gid(t): t for t in ab.tracks}
    parts, notes = [], []
    for xt in fixed.tracks:
        ot = O.get(gid(xt))
        if ot is None:
            notes.append(f"{xt.name}: a track the fix adds cannot be switched yet")
            continue
        if _text(ot.native) == _text(xt.native):
            continue
        abt = AB[gid(xt)]
        if _rest(ot) != _rest(xt):                       # items, envelopes, takes, markers: copy the whole track
            if ot.kind == "folder" and any(t.parent is ot for t in orig.tracks):
                notes.append(f"{ot.name}: a folder with tracks in it cannot be copied for A/B; apply this one alone to hear it")
                continue
            new = rpp.parse("\n".join(xt.native.text_lines()))     # a separate copy of the fixed track
            E.fresh_ids(new)
            new.set("MUTESOLO", 1, 0, 0)
            name = f"{ot.name} · B {fid}"
            copies.append((abt, new, name))
            parts.append(dict(mode="tracks", a=[abt.name], b=[name], a_on=[not ot.muted], b_on=[not ot.muted]))
            continue
        # plug-ins only: copy each changed one in right after the original, bypassed
        oblk, xblk = _fx_blocks(ot.native.chunk("FXCHAIN")), _fx_blocks(xt.native.chunk("FXCHAIN"))
        chain = abt.native.chunk("FXCHAIN")
        ablk = _fx_blocks(chain)
        refs = b_fx.setdefault(gid(abt), [b[1] if len(b) > 1 else None for b in ablk])   # the original plug-ins' chunks
        a_idx, b_new = [], []
        for k, (ob, xb) in enumerate(zip(oblk, xblk)):
            if "\n".join(_text(c) if isinstance(c, rpp.Chunk) else c.text().strip() for c in ob) == \
               "\n".join(_text(c) if isinstance(c, rpp.Chunk) else c.text().strip() for c in xb):
                continue
            on = not (len(ob[0].tokens) > 1 and ob[0].tokens[1] == "1")
            block = [_copy.deepcopy(x) for x in xb]
            block[0].set(1, *block[0].tokens[2:])        # BYPASS 1: B starts off
            for x in block:
                if isinstance(x, rpp.Line) and x.key == "FXID":
                    x.set(E.guid())
            anchor = refs[k]
            pos = chain.children.index(anchor) + 1
            while pos < len(chain.children) and not (isinstance(chain.children[pos], rpp.Line) and chain.children[pos].key == "BYPASS"):
                pos += 1                                 # after the original plug-in's trailing lines
            for x in reversed(block):
                chain.add(x, at=pos)
            a_idx.append((anchor, on))
            b_new.append((block[1], on))
        if len(xblk) != len(oblk):
            notes.append(f"{ot.name}: the fix adds or removes a plug-in; only changed plug-ins are switched")
        if a_idx or b_new:
            parts.append(dict(mode="devices", track=abt.name, _a=a_idx, _b=b_new, _chain=gid(abt)))
    return parts, notes


def finalize(ab, items):
    """Plug-in positions are final only once every B is in: chunks -> indices in the chain."""
    AB = {gid(t): t for t in ab.tracks}
    for it in items.values():
        for p in it.get("parts", []):
            if p["mode"] != "devices":
                continue
            t = AB[p.pop("_chain")]
            blocks = [b[1] for b in _fx_blocks(t.native.chunk("FXCHAIN")) if len(b) > 1]
            p["track"] = t.name
            p["a"], p["a_on"] = [blocks.index(c) for c, _ in p["_a"]], [on for _, on in p.pop("_a")]
            p["b"], p["b_on"] = [blocks.index(c) for c, _ in p["_b"]], [on for _, on in p.pop("_b")]
    return items


def build(sd, ids=None, out=None, extra=()):
    from hypnomix import project as PJ
    from hypnomix.project import rpp_edit as E
    sd = Path(sd)
    from hypnomix.workflow import oversight as O
    data = O.load_findings_doc(sd)
    orig = Path(data.get("set") or "")
    if orig.suffix.lower() != ".rpp" or not orig.exists():
        raise RuntimeError("this scan has no REAPER project to build an A/B project from")
    cands = candidates(data["findings"], ids)
    if not cands:
        raise RuntimeError("no findings that change the project (pass --ids to choose)")
    out = Path(out) if out else orig.with_name(f"{orig.stem} (A-B).rpp")
    if not out.is_absolute():
        out = orig.parent / out
    if out.exists() or out.resolve() == orig.resolve():
        raise RuntimeError(f"{out.name} already exists: choose a new name with --out (nothing is overwritten)")
    o = PJ.load(orig)
    ab = PJ.load(orig)
    items, copies, b_fx = {}, [], {}
    for f in cands:
        print(f"  {f['id']}: building B …", flush=True)
        fx, err = fixed_copy(sd, f["id"], orig, extra)
        if not fx:
            items[f["id"]] = dict(parts=[], note="could not be built: " + "; ".join(err))
            continue
        try:
            parts, notes = build_one(ab, o, PJ.load(fx), f["id"], copies, b_fx)
        finally:
            fx.unlink(missing_ok=True)
        items[f["id"]] = dict(parts=parts, note="; ".join(notes) if notes else ("" if parts else "the fix changed nothing"),
                              track=f.get("track"), problem=f.get("problem"))
    if copies:
        E.insert_copies(ab, copies)
    finalize(ab, items)
    E.save(ab, out)
    spec = dict(set=str(out), original=str(orig), daw="reaper", built=time.strftime("%Y-%m-%d %H:%M"), items=items)
    (sd / "ab_live.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    return out, spec
