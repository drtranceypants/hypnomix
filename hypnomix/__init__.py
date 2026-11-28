"""HypnoMix: mixing and mastering help for Ableton Live, REAPER and HypnoMix Studio."""
import os

# OpenBLAS (numpy's and scipy's maths library) keeps a thread pool and a fork handler that waits for it.
# Tools such as Rubber Band run from our worker threads (subprocess forks), and a fork landing while that
# pool is busy can hang the handler forever while it holds Python's lock: a scan froze for hours in the
# vocals step this way. Our work is already parallel across threads, so one BLAS thread costs little.
# Set before numpy loads; an explicit setting wins.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from hypnomix.extras import add_to_path as _add_extras  # noqa: E402

_add_extras()      # the optional extras the app's Setup installed (~/.hypnomix/extras), when there are any
