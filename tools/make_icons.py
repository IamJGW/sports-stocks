"""Draws the home-screen icons into web/icons/ with the standard library: python3 tools/make_icons.py

Three rising bars on the site's blue, kept inside the middle 60% so a phone's rounded or circular mask can't clip them.
"""
import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "icons")
BLUE = (31, 111, 235)
WHITE = (255, 255, 255)
BARS = [(0.22, 0.60), (0.42, 0.42), (0.62, 0.24)]  # left edge and top, as parts of the icon's side
BAR_WIDTH, BOTTOM, ROUND = 0.16, 0.78, 0.03


def in_bar(x, y):
    for left, top in BARS:
        if left <= x <= left + BAR_WIDTH and top <= y <= BOTTOM:
            cx = min(max(x, left + ROUND), left + BAR_WIDTH - ROUND)
            cy = min(max(y, top + ROUND), BOTTOM - ROUND)
            if (x - cx) ** 2 + (y - cy) ** 2 <= ROUND ** 2:
                return True
    return False


def pixels(size):
    rows = []
    samples = [(i + 0.5) / 4 for i in range(4)]
    for py in range(size):
        row = bytearray([0])  # PNG filter type: none
        for px in range(size):
            hit = sum(in_bar((px + sx) / size, (py + sy) / size) for sx in samples for sy in samples) / 16
            row += bytes(round(b + (w - b) * hit) for b, w in zip(BLUE, WHITE))
        rows.append(bytes(row))
    return b"".join(rows)


def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def png(size):
    head = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(pixels(size), 9)) + chunk(b"IEND", b"")


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(png(size))
        print(name)


if __name__ == "__main__":
    main()
