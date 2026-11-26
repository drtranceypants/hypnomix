"""Chapter: When something goes wrong. Part of the complete course (az) only."""
from hypnomix.app.lessons._common import enrich, place
from hypnomix.app.lessons import ch11_trouble_steps

_STEPS = ch11_trouble_steps.STEPS
CHAPTER = dict(id="trouble", levels=("az",), title="When something goes wrong",
               sub="no sound, echoes, clicks, hum, feedback, distortion and missing files",
               steps=enrich(place(_STEPS, [s["id"] for s in _STEPS]), ch11_trouble_steps.ENRICH))
