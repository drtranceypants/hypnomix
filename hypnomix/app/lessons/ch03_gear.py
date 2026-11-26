"""Chapter: Your room and your gear. Part of the complete course (az) only."""
from hypnomix.app.lessons._common import enrich, place
from hypnomix.app.lessons import ch03_gear_a, ch03_gear_b

_STEPS = ch03_gear_a.STEPS + ch03_gear_b.STEPS
CHAPTER = dict(id="gear", levels=("az",), title="Your room and your gear",
               sub="the interface, microphones, cables, headphones, speakers and the room",
               steps=enrich(place(_STEPS, [s["id"] for s in _STEPS]), ch03_gear_a.ENRICH, ch03_gear_b.ENRICH))
