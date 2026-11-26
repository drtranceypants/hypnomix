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
