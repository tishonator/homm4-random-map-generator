"""Terrain tiles and height map of a Heroes IV map body.

The tile and height sections end the map body, so they can be found from the end
without decoding the objects in front of them.

Format notes credit: the layout follows the reverse-engineering notes of the h4r
project (https://github.com/demen1n/h4r, decomp/h4c.md). This is an independent
Python implementation, checked against every map shipped with the game.
"""
import struct
from dataclasses import dataclass, field

TERRAINS = ["water", "grass", "rough", "swamp", "volcanic", "snow", "sand", "dirt",
            "subterranean", "river", "lava_river", "ice_river",
            "magic_all", "magic_life", "magic_order", "magic_death", "magic_chaos",
            "magic_nature", "special_combat"]
TERRAIN_SUBTYPES = [2] * 9 + [1] * 10
ROADS = ["none", "gravel", "dirt", "cobblestone"]
DEFAULT_VISIBILITY = 0x80000


def row_ranges(size):
    """Columns [start, end) of each tile row; the map is a diamond inside size x size."""
    half = size // 2
    rows = []
    for r in range(size):
        d = r if r < half else size - 1 - r
        rows.append((half - 1 - d, half + 1 + d))
    return rows


def vertex_row_ranges(size):
    """Columns [start, end) of each vertex row (one more row than tiles)."""
    t = row_ranges(size)
    rows = [(t[0][0], t[0][1] + 1)]
    for i in range(1, size):
        rows.append((min(t[i - 1][0], t[i][0]), max(t[i - 1][1], t[i][1]) + 1))
    rows.append((t[-1][0], t[-1][1] + 1))
    return rows


def counts(size, levels):
    tiles = sum(e - s for s, e in row_ranges(size)) * levels
    verts = sum(e - s for s, e in vertex_row_ranges(size)) * levels
    return tiles, verts


@dataclass
class Tile:
    terrain: int = 1
    subtype: int = 0
    road: int = 0
    rock: int = 0
    rock_transition: int = 0
    visibility: int = DEFAULT_VISIBILITY
    # (terrain, subtype, mask_id, mask_set)
    transitions: list = field(default_factory=list)
    # (road, mask_id, mask_set)
    road_transitions: list = field(default_factory=list)

    def encode(self):
        out = bytearray(struct.pack("<5BI", self.terrain, self.subtype, self.road,
                                    self.rock, self.rock_transition, self.visibility))
        out.append(len(self.transitions))
        for t, s, i, m in self.transitions:
            out += struct.pack("<BBHB", t, s, i, m)
        out.append(len(self.road_transitions))
        for rd, i, m in self.road_transitions:
            out += struct.pack("<BHB", rd, i, m)
        return bytes(out)


def _read_tile(d, p):
    """Return (tile, new_pos) or (None, p) if the bytes can't be a tile."""
    if p + 11 > len(d):
        return None, p
    terrain, sub, road, rock, rtr, vis = struct.unpack_from("<5BI", d, p)
    if (terrain >= len(TERRAINS) or sub >= TERRAIN_SUBTYPES[terrain] or road > 3
            or rock > 2 or rtr > 1 or vis & ~0x3FFFF != DEFAULT_VISIBILITY):
        return None, p
    p += 9
    n = d[p]
    p += 1
    if n > 12 or p + 5 * n >= len(d):
        return None, p
    trans = [struct.unpack_from("<BBHB", d, p + 5 * k) for k in range(n)]
    p += 5 * n
    m = d[p]
    p += 1
    if m > 12 or p + 4 * m > len(d):
        return None, p
    roads = [struct.unpack_from("<BHB", d, p + 4 * k) for k in range(m)]
    p += 4 * m
    return Tile(terrain, sub, road, rock, rtr, vis, trans, roads), p


def read_tiles_at(body, start, size, levels):
    n_tiles, n_verts = counts(size, levels)
    tiles, p = [], start
    for _ in range(n_tiles):
        t, p = _read_tile(body, p)
        if t is None:
            return None
        tiles.append(t)
    if len(body) - p != n_verts:
        return None
    return tiles, body[p:]


def find_tiles(body, size, levels, search_from=0):
    """Locate the tile section. Returns (start, tiles, heights).

    The tiles end exactly where the height bytes begin. For every offset we work out
    where a tile starting there would end (one linear pass), then count how many tiles
    each offset is away from that end. The start is the offset exactly n_tiles away.
    """
    n_tiles, n_verts = counts(size, levels)
    end = len(body) - n_verts
    dist = {end: 0}
    best = None
    for p in range(end - 11, search_from - 1, -1):
        t, q = _read_tile(body, p)
        if t is None or q > end:
            continue
        d = dist.get(q)
        if d is None:
            continue
        dist[p] = d + 1
        if d + 1 == n_tiles:
            best = p
            break
    if best is None:
        raise ValueError("tile section not found")
    r = read_tiles_at(body, best, size, levels)
    if r is None:
        raise ValueError("tile section did not re-read")
    return best, r[0], r[1]


def encode_tiles(tiles, heights):
    return b"".join(t.encode() for t in tiles) + bytes(heights)


class Grid:
    """Tiles and heights addressed by (level, row, col)."""

    def __init__(self, size, levels, tiles=None, heights=None):
        self.size, self.levels = size, levels
        self.rows, self.vrows = row_ranges(size), vertex_row_ranges(size)
        self.per_level = sum(e - s for s, e in self.rows)
        self.vper_level = sum(e - s for s, e in self.vrows)
        self.tiles = tiles or [Tile() for _ in range(self.per_level * levels)]
        self.heights = bytearray(heights) if heights is not None else bytearray(self.vper_level * levels)
        self._off = [sum(e - s for s, e in self.rows[:r]) for r in range(size)]
        self._voff = [sum(e - s for s, e in self.vrows[:r]) for r in range(size + 1)]

    def inside(self, row, col):
        if not 0 <= row < self.size:
            return False
        s, e = self.rows[row]
        return s <= col < e

    def tile(self, level, row, col):
        s, _ = self.rows[row]
        return self.tiles[level * self.per_level + self._off[row] + col - s]

    def vinside(self, row, col):
        if not 0 <= row <= self.size:
            return False
        s, e = self.vrows[row]
        return s <= col < e

    def vindex(self, level, row, col):
        s, _ = self.vrows[row]
        return level * self.vper_level + self._voff[row] + col - s
