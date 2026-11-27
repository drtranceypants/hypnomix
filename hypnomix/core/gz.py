"""Reading a gzipped project file (a Live set) without trusting its size.

A gzip file can unpack to a thousand times its own size. `read_gz` reads in chunks and stops with a clear message
once the unpacked size passes a cap (1 GB by default, far above any real Live set), so a damaged or hostile file
cannot fill the memory of the app or a tool.

    from hypnomix.core.gz import read_gz
    root = ET.fromstring(read_gz(path))        # the same bytes as gzip.open(path).read()
"""
import gzip

CAP = 1 << 30                           # 1 GB unpacked
CHUNK = 1 << 20
SOFT = 128 << 20                        # keep chunks in memory up to here; past it, count first


def _size_text(n):
    for unit, size in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= size:
            v = n / size
            return f"{v:.0f} {unit}" if v >= 10 or v == int(v) else f"{v:.1f} {unit}"
    return f"{n} bytes"


def read_gz(path, cap=CAP):
    """The unpacked bytes of a gzip file, read in chunks. Raises ValueError ("this file unpacks to more than N: it is
    not a project HypnoMix will open") past `cap` bytes; a file that is not gzip raises what gzip raises (OSError).

    Memory: up to SOFT (128 MB) the chunks are kept as they come. Past that the chunks are dropped and the rest is only
    counted, so a file that unpacks past the cap is refused with a small footprint; a big but allowed file is read
    a second time to keep it."""
    soft = min(cap, SOFT)
    out, total = [], 0
    with gzip.open(path, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                return b"".join(out)
            total += len(chunk)
            out.append(chunk)
            if total > soft:
                break
        out = None                                          # large: count the rest without keeping it
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                break
    if total > cap:
        raise ValueError(f"this file unpacks to more than {_size_text(cap)}: it is not a project HypnoMix will open")
    with gzip.open(path, "rb") as fh:                       # allowed and large: read it again, keeping it
        return fh.read()
