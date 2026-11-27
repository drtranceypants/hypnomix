"""MPE presets by behaviour, and the exact bytes that set a receiver up for one.

Seeded only from the MPE specification (MIDI Polyphonic Expression, RP-053): no controller or instrument is named,
and none of these is a measured fact about a particular device.

The setup, in specification order, on the zone's global channel (channel 1 for the lower zone, 16 for the upper):

  reset all controllers            Bn 79 00
  MPE configuration message        Bn 64 06  Bn 65 00  Bn 06 <members>          (RPN 6)
  pitch bend range, global         Bn 64 00  Bn 65 00  Bn 06 <semitones>  Bn 26 00   (RPN 0)

then RPN 0 again on every member channel with the member bend range. `setup_bytes` returns all of it.
"""

PRESETS = {
    "lower-15": dict(zone="lower", members=15, member_bend=48, global_bend=2,
                     about="the standard lower zone: global channel 1, 15 member channels, member bend 48, global bend 2"),
    "lower-15-bend24": dict(zone="lower", members=15, member_bend=24, global_bend=2,
                            about="the lower zone for an instrument whose bend range stops at 24 semitones"),
    "lower-15-bend12": dict(zone="lower", members=15, member_bend=12, global_bend=2,
                            about="the lower zone for an instrument whose bend range stops at 12 semitones"),
    "upper-15": dict(zone="upper", members=15, member_bend=48, global_bend=2,
                     about="the upper zone: global channel 16, 15 member channels from 15 down, member bend 48"),
}
for _p in PRESETS.values():
    _p.update(pressure="channel", slide="cc74")        # MPE's own: channel pressure per note, slide on CC 74


def _check(p):
    if p.get("zone") not in ("lower", "upper"):
        raise ValueError("a preset's zone is lower or upper")
    if not 1 <= int(p.get("members", 0)) <= 15:
        raise ValueError("a zone has 1 to 15 member channels")
    for k in ("member_bend", "global_bend"):
        if not 0 <= int(p.get(k, -1)) <= 96:
            raise ValueError("a bend range is 0 to 96 semitones")


def get(name):
    if name not in PRESETS:
        raise ValueError(f"no preset {name!r} (there are: {', '.join(PRESETS)})")
    return dict(PRESETS[name])


def global_channel(p):
    return 0 if p["zone"] == "lower" else 15


def member_channels(p):
    """0-based: the lower zone's members from channel index 1 up, the upper zone's from 14 down."""
    m = int(p["members"])
    return list(range(1, 1 + m)) if p["zone"] == "lower" else list(range(14, 14 - m, -1))


def _cc(ch, num, val):
    return bytes((0xB0 | ch, num, val))


def configuration_bytes(p):
    """Reset all controllers, then the MPE configuration message, on the global channel."""
    _check(p)
    g = global_channel(p)
    return _cc(g, 0x79, 0) + _cc(g, 0x64, 6) + _cc(g, 0x65, 0) + _cc(g, 0x06, int(p["members"]))


def bend_range_bytes(ch, semitones):
    """RPN 0 (pitch bend sensitivity) on one channel: whole semitones, 0 cents."""
    return _cc(ch, 0x64, 0) + _cc(ch, 0x65, 0) + _cc(ch, 0x06, int(semitones)) + _cc(ch, 0x26, 0)


def setup_bytes(p):
    """The whole setup for a preset (a name or a dict), in specification order: the configuration message, the global
    channel's bend range, then each member channel's."""
    p = get(p) if isinstance(p, str) else p
    _check(p)
    out = configuration_bytes(p) + bend_range_bytes(global_channel(p), p["global_bend"])
    for ch in member_channels(p):
        out += bend_range_bytes(ch, p["member_bend"])
    return out


def mpe_element(p):
    """The attributes HypnoMix DAW saves for a track's MPE setting (<MPE .../> under the track's route)."""
    p = get(p) if isinstance(p, str) else p
    _check(p)
    return {"zone": p["zone"], "members": str(int(p["members"])), "member-bend-range": str(int(p["member_bend"])),
            "global-bend-range": str(int(p["global_bend"]))}
