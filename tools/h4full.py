"""Read and write a whole Heroes IV map: rules, objects, tiles, heights.

Usage: python h4full.py check <maps folder>   (parse + re-encode every map, report results)
"""
import glob
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(__file__))
import h4c  # noqa: E402
import h4map  # noqa: E402
import h4objects  # noqa: E402
import h4tiles  # noqa: E402


@dataclass
class Map:
    rules: h4map.MapRules
    objects: list
    grid: h4tiles.Grid


def decode(body):
    rules, pos = h4map.read_rules(body)
    objects, pos = h4objects.read_objects(body, pos)
    tiles = h4tiles.read_tiles_at(body, pos, rules.size, rules.levels)
    if tiles is None:
        raise ValueError(f"tiles don't start where the objects end ({pos:#x})")
    grid = h4tiles.Grid(rules.size, rules.levels, tiles[0], tiles[1])
    return Map(rules, objects, grid)


def encode(m):
    return (h4map.write_rules(m.rules) + h4objects.encode_objects(m.objects)
            + h4tiles.encode_tiles(m.grid.tiles, m.grid.heights))


def load(path):
    return decode(h4c.read_container(path)[1])


def save(m, path):
    h4c.write_container(path, encode(m))


def check(folder):
    ok = bad = 0
    for p in sorted(glob.glob(os.path.join(folder, "**", "*.h4c"), recursive=True)):
        body = h4c.read_container(p)[1]
        try:
            same = encode(decode(body)) == body
        except Exception as e:  # report and continue
            print(f"FAIL {os.path.basename(p)}: {e}")
            bad += 1
            continue
        ok += same
        bad += not same
        if not same:
            print(f"MISMATCH {os.path.basename(p)}")
    print(f"byte-exact: {ok}, failed: {bad}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "check":
        check(sys.argv[2])
    else:
        print(__doc__)
