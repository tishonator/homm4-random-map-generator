"""Render a terrain preview PNG of a .h4c map (top-down, rotated to look like the in-game view).

Usage: python preview.py <map.h4c> <out.png>
"""
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
import h4c  # noqa: E402
import h4tiles  # noqa: E402

COLORS = {
    "water": (40, 80, 170), "grass": (70, 150, 50), "rough": (150, 130, 80),
    "swamp": (60, 90, 60), "volcanic": (90, 40, 30), "snow": (235, 240, 250),
    "sand": (220, 200, 120), "dirt": (130, 100, 60), "subterranean": (90, 70, 80),
    "river": (70, 130, 220), "lava_river": (230, 80, 20), "ice_river": (170, 210, 240),
}
ROAD = (240, 230, 200)


def render(path, out, scale=4):
    _, body = h4c.read_container(path)
    h = h4c.header(body)
    size, levels = h["size"], h["levels"]
    _, tiles, heights = h4tiles.find_tiles(body, size, levels, h["end_offset"])
    g = h4tiles.Grid(size, levels, tiles, heights)
    # Rotate the diamond 45 degrees: screen x = col - row, screen y = col + row.
    w = size + 2
    img = Image.new("RGB", (w * levels, size + 1), (0, 0, 0))
    for lv in range(levels):
        for r in range(size):
            s, e = g.rows[r]
            for c in range(s, e):
                t = g.tile(lv, r, c)
                name = h4tiles.TERRAINS[t.terrain]
                col = ROAD if t.road else COLORS.get(name, (200, 0, 200))
                hv = g.heights[g.vindex(lv, r, c)] if g.vinside(r, c) else 0
                k = 1 + hv / 400
                col = tuple(min(255, int(v * k)) for v in col)
                x, y = c - r + size // 2 + lv * w, c + r - (size // 2 - 1)
                for dx in (0, 1):
                    if 0 <= y <= size and 0 <= x + dx < w * levels:
                        img.putpixel((x + dx, y), col)
    img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    img.save(out)


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2])
