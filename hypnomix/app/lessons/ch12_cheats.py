"""Chapter: Cheat sheets. Part of the complete course (az) only."""
from hypnomix.app.lessons._common import enrich, place
from hypnomix.app.lessons import ch12_cheats_steps

_STEPS = ch12_cheats_steps.STEPS
CHAPTER = dict(id="cheats", levels=("az",), title="Cheat sheets",
               sub="the numbers and the checklists, one page each",
               steps=enrich(place(_STEPS, [s["id"] for s in _STEPS]), ch12_cheats_steps.ENRICH))
