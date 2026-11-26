"""Shared by the lesson modules: the DAW tuples and a helper that puts steps in their teaching order."""

ALL = ("live", "reaper", "ardour")
LR = ("live", "reaper")
LIVE = ("live",)
REAPER = ("reaper",)
ARDOUR = ("ardour",)


def place(steps, order):
    """Return `steps` in the order of the ids in `order`. Every id must be placed exactly once, so a typo or a
    forgotten step fails at import (and in the tests) instead of silently vanishing from a course."""
    by = {}
    for s in steps:
        if s["id"] in by:
            raise ValueError(f"duplicate step id {s['id']!r}")
        by[s["id"]] = s
    if sorted(order) != sorted(by) or len(set(order)) != len(order):
        raise ValueError("lesson order and steps differ: missing %s, unknown %s" %
                         (sorted(set(by) - set(order)), sorted(set(order) - set(by))))
    return [by[i] for i in order]


def enrich(steps, *extras):
    """Add teaching fields (mistakes, try, quiz, hear, more, terms…) to steps that already exist, without touching their text.
    Each of `extras` is {step id: {field: value}}. A step id that doesn't exist, or a field the step already has, is an error."""
    by = {s["id"]: s for s in steps}
    for ex in extras:
        for sid, fields in ex.items():
            if sid not in by:
                raise ValueError(f"enrich: no step {sid!r}")
            for k, v in fields.items():
                if k in by[sid]:
                    raise ValueError(f"enrich: step {sid!r} already has {k!r}")
                by[sid][k] = v
    return steps


def az_only(steps):
    """Mark steps as belonging to the complete course only (used when adding steps to a chapter the 101 course shares)."""
    for s in steps:
        s["levels"] = ("az",)
    return steps
