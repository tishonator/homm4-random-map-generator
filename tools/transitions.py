"""Compute terrain transitions (blended edges) for generated maps.

How the game uses them (h4r notes, decomp/terrain_draw.md + our own study of the shipped maps):
- A tile lists masks of other terrains drawn over its edges. Each mask has a 4-digit code,
  one digit per corner of the tile diamond (thousands = east, hundreds = south, tens = west,
  ones = north): 3 = both edges at that corner covered, 1 / 2 = only the edge before / after
  it (clockwise from north), 4 = only the diagonal neighbour.
- A map stores (terrain, subtype, mask index, mask set). All 15 mask sets share the same code
  order (data/transition_codes.json). Set numbers 0-4 = water_to_land, 5-9 = land_to_water,
  10-14 = road, 15-19 = land; the editor picks one of the five at random.

Our rule (simpler than the editor's, which blends some borders from both sides): terrains have
a fixed priority. A tile gets, for every higher-priority terrain T among its 8 neighbours, the
mask for "neighbours whose priority >= T", split into masks that exist in the library.
"""
import itertools
import json
import os
import random
import sys

# data/ next to tools/, or inside the packaged program (PyInstaller unpacks it to sys._MEIPASS)
_DATA = (os.path.join(sys._MEIPASS, "data") if getattr(sys, "frozen", False)
         else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
CODES = json.load(open(os.path.join(_DATA, "transition_codes.json")))["land 1"]
CODE_INDEX = {c: i for i, c in enumerate(CODES)}

# screen direction -> (d_row, d_col); rows run to the screen's lower left, columns lower right
DIRS = {"n": (-1, -1), "ne": (-1, 0), "e": (-1, 1), "se": (0, 1),
        "s": (1, 1), "sw": (1, 0), "w": (1, -1), "nw": (0, -1)}

WATER, RIVERS = 0, (9, 10, 11)

# Low to high. Water lowest so land blends over shorelines; subtype 0 above subtype 1.
PRIORITY_ORDER = [
    (0, 1), (0, 0),                      # water
    (11, 0), (9, 0), (10, 0),            # rivers: ice, water, lava
    (8, 1), (8, 0),                      # subterranean
    (3, 1), (3, 0),                      # swamp
    (2, 1), (2, 0),                      # rough
    (7, 1), (7, 0),                      # dirt
    (6, 1), (6, 0),                      # sand
    (1, 1), (1, 0),                      # grass
    (5, 1), (5, 0),                      # snow
    (4, 1), (4, 0),                      # volcanic
    (12, 0), (13, 0), (14, 0), (15, 0), (16, 0), (17, 0), (18, 0),  # magic / special
]
PRIORITY = {k: i for i, k in enumerate(PRIORITY_ORDER)}


def corner_code(has):
    def digit(before, after, diag):
        if before and after:
            return 3
        if before:
            return 1
        if after:
            return 2
        return 4 if diag else 0
    return (digit(has["ne"], has["se"], has["e"]) * 1000
            + digit(has["se"], has["sw"], has["s"]) * 100
            + digit(has["sw"], has["nw"], has["w"]) * 10
            + digit(has["nw"], has["ne"], has["n"]))


def _digits(code):
    return [code // p % 10 for p in (1000, 100, 10, 1)]


def _compose(digits):
    return sum(d * p for d, p in zip(digits, (1000, 100, 10, 1)))


def split_code(code):
    """Split a corner code into the fewest masks that exist in the library."""
    if code == 0:
        return []
    if code in CODE_INDEX:
        return [code]
    digits = _digits(code)
    corners = [i for i, d in enumerate(digits) if d]
    best = None
    # try every way to group the covered corners; keep the one with fewest masks
    for labels in itertools.product(range(len(corners)), repeat=len(corners)):
        groups = {}
        for corner, lab in zip(corners, labels):
            groups.setdefault(lab, []).append(corner)
        parts = []
        for g in groups.values():
            d = [digits[i] if i in g else 0 for i in range(4)]
            c = _compose(d)
            if c not in CODE_INDEX:
                break
            parts.append(c)
        else:
            if best is None or len(parts) < len(best):
                best = parts
    if best is None:
        raise ValueError(f"cannot split transition code {code}")
    return sorted(best)


def _family(tile_terrain, over_terrain):
    """Mask set family (first number of five) for drawing over_terrain onto tile_terrain."""
    tile_water = tile_terrain == WATER or tile_terrain in RIVERS
    over_water = over_terrain == WATER
    if tile_water and not over_water:
        return 5      # land_to_water
    if not tile_water and (over_water or over_terrain in RIVERS):
        return 0      # water_to_land
    if tile_water:
        return 0
    return 15         # land


def _mask_set(family, rng):
    return family + (rng.randrange(5) if family != 15 else rng.randrange(5))


def compute(grid, rng=None, region=None):
    """Recompute terrain transitions for every tile (or only tiles in `region`, a set of
    (level, row, col)). Road transitions are left as they are."""
    rng = rng or random.Random(0)
    for lv in range(grid.levels):
        for r in range(grid.size):
            s, e = grid.rows[r]
            for c in range(s, e):
                if region is not None and (lv, r, c) not in region:
                    continue
                t = grid.tile(lv, r, c)
                own = PRIORITY[(t.terrain, t.subtype)]
                nb = {}
                for d, (dr, dc) in DIRS.items():
                    rr, cc = r + dr, c + dc
                    if grid.inside(rr, cc):
                        n = grid.tile(lv, rr, cc)
                        nb[d] = PRIORITY[(n.terrain, n.subtype)]
                    else:
                        nb[d] = own          # outside the map: treat as the tile's own terrain
                trans = []
                for p in sorted({v for v in nb.values() if v > own}):
                    has = {d: v >= p for d, v in nb.items()}
                    terrain, subtype = PRIORITY_ORDER[p]
                    fam = _family(t.terrain, terrain)
                    ms = _mask_set(fam, rng)
                    for code in split_code(corner_code(has)):
                        trans.append((terrain, subtype, CODE_INDEX[code], ms))
                t.transitions = trans


def region_around(cells, radius=1):
    """Cells plus their neighbours within `radius` (for local recomputation)."""
    out = set()
    for lv, r, c in cells:
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                out.add((lv, r + dr, c + dc))
    return out


# ---------------------------------------------------------------- roads
#
# Road transitions (learned from the shipped maps, see research/format.md):
# - a road tile lists road 0 ("no road") drawn over the edges whose neighbours have no road;
#   a corner digit is 0 when the corner's diagonal neighbour has road;
# - a tile without road lists the road drawn over corners where both edge neighbours have it.
# Cells outside the map count as road. Mask sets 10-14, picked at random.

def _road_digit_on_road(before, after, diag):
    """Digit of the "no road" mask on a road tile; arguments are True where there is NO road."""
    if not diag:
        return 0
    if before and after:
        return 3
    if before:
        return 1
    if after:
        return 2
    return 0


def road_code(grid, lv, r, c):
    """Return (road, code) of the road transition the tile needs, or None."""
    t = grid.tile(lv, r, c)
    road = {}
    for d, (dr, dc) in DIRS.items():
        rr, cc = r + dr, c + dc
        road[d] = grid.tile(lv, rr, cc).road if grid.inside(rr, cc) else -1
    corners = (("ne", "se", "e"), ("se", "sw", "s"), ("sw", "nw", "w"), ("nw", "ne", "n"))
    if t.road:
        none = {d: v == 0 for d, v in road.items()}
        digits = [_road_digit_on_road(none[a], none[b], none[g]) for a, b, g in corners]
        code = _compose(digits)
        return (0, code) if code else None
    kinds = [v for v in road.values() if v > 0]
    if not kinds:
        return None
    kind = max(set(kinds), key=kinds.count)
    has = {d: v == kind or v == -1 for d, v in road.items()}
    code = _compose([3 if has[a] and has[b] else 0 for a, b, _ in corners])
    return (kind, code) if code else None


def compute_roads(grid, rng=None, region=None):
    rng = rng or random.Random(0)
    for lv in range(grid.levels):
        for r in range(grid.size):
            s, e = grid.rows[r]
            for c in range(s, e):
                if region is not None and (lv, r, c) not in region:
                    continue
                t = grid.tile(lv, r, c)
                rc = road_code(grid, lv, r, c)
                t.road_transitions = []
                if rc:
                    kind, code = rc
                    for part in split_code(code):
                        t.road_transitions.append((kind, CODE_INDEX[part], 10 + rng.randrange(5)))
