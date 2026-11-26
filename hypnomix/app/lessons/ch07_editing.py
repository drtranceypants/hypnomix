"""Chapter: Editing. Part of the complete course (az) only."""
from hypnomix.app.lessons._common import enrich, place
from hypnomix.app.lessons import ch07_editing_steps

_STEPS = ch07_editing_steps.STEPS
CHAPTER = dict(id="editing", levels=("az",), title="Editing",
               sub="takes, cuts and fades, clip gain, timing, tuning and tidying",
               steps=enrich(place(_STEPS, [s["id"] for s in _STEPS]), ch07_editing_steps.ENRICH))
