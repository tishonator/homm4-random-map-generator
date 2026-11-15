"""Extract object footprints from the game's adv_object.* resources.

For every model, writes: width, height (cells), blocked cells, entrance ("trigger") edges,
flat mode and the object type. Field layout per the h4r notes (decomp/adv_object.md).

Usage: python footprints.py <game data folder> <out.json>

Footprint axes: x runs along map rows (the object's x), y along columns. Cell index = y*width + x.
"entry" lists the cells (footprint coordinates, may lie outside it) a hero visits the object from:
the cells across each trigger edge.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import h4r  # noqa: E402


def _bits(d, p, n):
    nb = (n + 7) // 8
    return [bool(d[p + i // 8] >> (i % 8) & 1) for i in range(n)], p + nb


def read_footprint(d):
    p = 0
    version = struct.unpack_from("<H", d, p)[0]
    p += 3                                  # version, fps
    edge = 0
    if version >= 3:
        edge = struct.unpack_from("<H", d, p)[0]
        p += 2
    w, h = struct.unpack_from("<HH", d, p)
    p += 4
    blocked, p = _bits(d, p, w * h)
    trig_cells = [False] * (w * h)
    entry = set()                           # cells a hero visits from, footprint coords
    if edge:
        left, p = _bits(d, p, w * (h + 1))
        right, p = _bits(d, p, (w + 1) * h)
        # A cell triggers if one of its edges is marked and that edge is on the footprint
        # border or the cell is blocked (is_trigger_cell in the exe, per h4r notes).
        for y in range(h):
            for x in range(w):
                c = y * w + x
                edges = [
                    (left[x + w * y], y == 0),            # "left" edges: w x (h+1), index x + w*y
                    (left[x + w * (y + 1)], y == h - 1),
                    (right[y + h * x], x == 0),           # "right" edges: (w+1) x h, index y + h*x
                    (right[y + h * (x + 1)], x == w - 1),
                ]
                trig_cells[c] = any(m and (border or blocked[c]) for m, border in edges)
                if trig_cells[c]:
                    across = [(x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)]
                    for (m, _), (ax, ay) in zip(edges, across):
                        inside = 0 <= ax < w and 0 <= ay < h
                        if m and (not inside or not blocked[ay * w + ax]):
                            entry.add((ax, ay))
    else:
        old, p = _bits(d, p, w * h)
        for c, t in enumerate(old):
            if t:
                x, y = c % w, c // w
                for ax, ay in ((x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)):
                    if not (0 <= ax < w and 0 <= ay < h) or not blocked[ay * w + ax]:
                        entry.add((ax, ay))
    if version >= 6:
        p += (2 * w * (h + 1) + 7) // 8 + (2 * (w + 1) * h + 7) // 8 + (w + 1) * (h + 1)
    kind = ids = None
    if version >= 2:
        p += 2
        kind, ids = [], []
        for _ in range(3):
            i, n = struct.unpack_from("<HH", d, p)
            kind.append(d[p + 4:p + 4 + n].decode("cp1252"))
            ids.append(i)
            p += 4 + n
    flat = d[p] if version >= 4 else int(w >= 2 or h >= 2)
    return {
        "w": w, "h": h,
        "blocked": [i for i, b in enumerate(blocked) if b],
        "trigger": [i for i, t in enumerate(trig_cells) if t],
        "entry": sorted(entry),
        "flat": flat,
        "type": kind,
        "type_ids": ids,
    }


def main(data_dir, out):
    res = h4r.Resources(data_dir)
    result, errors = {}, 0
    for name in sorted(n for n in res.names() if n.startswith("adv_object.")):
        try:
            key = name[len("adv_object."):]
            if key.endswith(".h4d"):
                key = key[:-4]
            result[key] = read_footprint(res.read(name))
        except Exception as e:  # keep going, report at the end
            errors += 1
            print("skip", name, e)
    with open(out, "w") as f:
        json.dump(result, f, separators=(",", ":"))
    print(f"{len(result)} footprints, {errors} errors -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
