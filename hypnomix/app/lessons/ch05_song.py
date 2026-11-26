"""Chapter: The song before you record. Part of the complete course (az) only."""
from hypnomix.app.lessons._common import enrich, place
from hypnomix.app.lessons import ch05_song_steps

_STEPS = ch05_song_steps.STEPS
CHAPTER = dict(id="song", levels=("az",), title="The song before you record",
               sub="tempo, key, sections, arrangement, MIDI and loops",
               steps=enrich(place(_STEPS, [s["id"] for s in _STEPS]), ch05_song_steps.ENRICH))
