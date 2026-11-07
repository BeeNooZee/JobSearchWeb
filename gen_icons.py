"""Génère les icônes PWA (cible bleue) sans dépendance externe."""
import math
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "static")
BG = (79, 124, 255)       # bleu primaire
WHITE = (255, 255, 255)
DARK = (31, 44, 90)


def color_at(x, y, s):
    cx = cy = s / 2
    r = math.hypot(x - cx, y - cy) / s  # rayon normalisé 0..~0.7
    # Anneaux concentriques façon cible.
    if r <= 0.07:
        return WHITE
    if r <= 0.16:
        return BG
    if r <= 0.25:
        return WHITE
    if r <= 0.34:
        return BG
    if r <= 0.42:
        return WHITE
    return BG


def make(size):
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filtre 0
        for x in range(size):
            raw += bytes(color_at(x, y, size)) + b"\xff"
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", comp)
    png += chunk(b"IEND", b"")
    path = os.path.join(OUT, f"icon-{size}.png")
    with open(path, "wb") as f:
        f.write(png)
    print("écrit", path, len(png), "octets")


if __name__ == "__main__":
    make(192)
    make(512)
