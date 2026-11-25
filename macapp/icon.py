"""Draw the app icon (a fader on a paper-pink tile) and write an .icns. Usage: icon.py OUT.icns"""
import subprocess, sys, tempfile
from pathlib import Path

import numpy as np
import soundfile  # noqa: F401  (proves the hypnomix environment is the one running this)

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("Pillow is not installed: skipping the icon")


def draw(n):
    s = 4
    im = Image.new("RGBA", (n * s, n * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    N = n * s
    m = int(N * 0.09)
    d.rounded_rectangle([m, m, N - m, N - m], radius=int(N * 0.2), fill=(233, 180, 176, 255))
    for i, (x, y) in enumerate(((0.32, 0.58), (0.5, 0.36), (0.68, 0.66))):
        cx = int(N * x)
        d.rounded_rectangle([cx - int(N * 0.018), int(N * 0.24), cx + int(N * 0.018), int(N * 0.76)], radius=int(N * 0.018), fill=(59, 47, 43, 255))
        cy = int(N * y)
        d.rounded_rectangle([cx - int(N * 0.07), cy - int(N * 0.04), cx + int(N * 0.07), cy + int(N * 0.04)],
                            radius=int(N * 0.02), fill=(251, 248, 241, 255), outline=(59, 47, 43, 255), width=max(1, int(N * 0.008)))
    return im.resize((n, n), Image.LANCZOS)


out = Path(sys.argv[1])
with tempfile.TemporaryDirectory() as td:
    iconset = Path(td) / "Hypnomix.iconset"
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        draw(size).save(iconset / f"icon_{size}x{size}.png")
        draw(size * 2).save(iconset / f"icon_{size}x{size}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)
print("icon", out)
