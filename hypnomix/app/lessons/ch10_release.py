"""Chapter: Releasing. Part of the complete course (az) only."""
from hypnomix.app.lessons._common import enrich, place
from hypnomix.app.lessons import ch10_release_steps

_STEPS = ch10_release_steps.STEPS
CHAPTER = dict(id="release", levels=("az",), title="Releasing",
               sub="the files, the metadata, the cover, a distributor, your rights and an archive",
               steps=enrich(place(_STEPS, [s["id"] for s in _STEPS]), ch10_release_steps.ENRICH))
