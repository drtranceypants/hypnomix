"""Chapter: Digital audio. Part of the complete course (az) only."""
from hypnomix.app.lessons._common import enrich, place
from hypnomix.app.lessons import ch02_digital_steps

_STEPS = ch02_digital_steps.STEPS
CHAPTER = dict(id="digital", levels=("az",), title="Digital audio",
               sub="sample rate, bit depth, headroom, latency, file types and backups",
               steps=enrich(place(_STEPS, [s["id"] for s in _STEPS]), ch02_digital_steps.ENRICH))
