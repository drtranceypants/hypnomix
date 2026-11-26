"""Chapter: Sound and hearing. Part of the complete course (az) only."""
from hypnomix.app.lessons._common import enrich, place
from hypnomix.app.lessons import ch01_sound_steps

_STEPS = ch01_sound_steps.STEPS
CHAPTER = dict(id="sound", levels=("az",), title="Sound and hearing",
               sub="what sound is, how we hear it, and the numbers that describe it",
               steps=enrich(place(_STEPS, [s["id"] for s in _STEPS]), ch01_sound_steps.ENRICH))
