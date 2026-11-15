"""Game data used by the setup window: data tables, heroes, portraits.

Formats (per the h4r project's notes, https://github.com/demen1n/h4r; independent code):
- table.*.h4d: u32 row count; each row = u16 cell count + u16-prefixed cp1252 strings.
- layers.*.h4d: u16 count, then paletted layers:
    u16 palette size, u16 has_block_alpha, palette (B, G, R) * size,
    u16-prefixed name, u8 alpha depth, i32 left, top, right, bottom,
    (bottom - top) rows of (u16 x0, u16 x1, u32 offset), N palette indices (N = last row's
    offset + width), then if alpha depth >= 4: (N + 1) // 2 bytes of 4-bit alpha (even pixel in
    the low nibble) and, with block alpha, (N + 131) // 128 more bytes.
    Alpha depth 1: palette index 0 is transparent.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import h4r  # noqa: E402


def read_table(d):
    rows, p = [], 4
    for _ in range(struct.unpack_from("<I", d, 0)[0]):
        n = struct.unpack_from("<H", d, p)[0]
        p += 2
        row = []
        for _ in range(n):
            k = struct.unpack_from("<H", d, p)[0]
            row.append(d[p + 2:p + 2 + k].decode("cp1252", "replace"))
            p += 2 + k
        rows.append(row)
    return rows


def read_layers_names(d):
    """Like read_layers, but only names and sizes (fast): [(name, width, height)]."""
    return read_layers(d, pixels=False)


def read_layers(d, pixels=True):
    """Return [(name, width, height, rgba bytes)] for a layers.*.h4d bitmap group."""
    count = struct.unpack_from("<H", d, 0)[0]
    p, out = 2, []
    for _ in range(count):
        npal, block = struct.unpack_from("<HH", d, p)
        p += 4
        pal = d[p:p + 3 * npal]
        p += 3 * npal
        k = struct.unpack_from("<H", d, p)[0]
        name = d[p + 2:p + 2 + k].decode("cp1252", "replace")
        p += 2 + k
        depth = d[p]
        left, top, right, bottom = struct.unpack_from("<4i", d, p + 1)
        p += 17
        h, w = max(0, bottom - top), max(0, right - left)
        rows = [struct.unpack_from("<HHI", d, p + 8 * i) for i in range(h)]
        p += 8 * h
        n = rows[-1][2] + rows[-1][1] - rows[-1][0] if rows else 0
        pix = d[p:p + n]
        p += n
        alpha = b""
        if depth >= 4 and n:
            alpha = d[p:p + (n + 1) // 2]
            p += (n + 1) // 2
            if block:
                p += (n + 131) // 128
        if not pixels:
            out.append((name, w, h))
            continue
        rgba = bytearray(4 * w * h)
        for y, (x0, x1, off) in enumerate(rows):
            for i in range(x1 - x0):
                idx = pix[off + i]
                if depth >= 4:
                    a = alpha[(off + i) >> 1]
                    a = (a & 15 if (off + i) % 2 == 0 else a >> 4) * 17
                else:
                    a = 0 if idx == 0 else 255
                q = 4 * (y * w + x0 + i)
                b, g, r = pal[3 * idx:3 * idx + 3]
                rgba[q:q + 4] = bytes((r, g, b, a))
        out.append((name, w, h, bytes(rgba)))
    return out


def heroes(res):
    """Heroes from table.heroes: list of dicts (keyword, name, sex, class, biography, default)."""
    rows = read_table(res.read("table.heroes.h4d"))
    head = rows[0]
    out = []
    for row in rows[1:]:
        if len(row) < 5 or not row[0]:
            continue
        rec = dict(zip(head, row))
        out.append({"keyword": rec.get("Keyword", ""), "name": rec.get("Name", ""),
                    "sex": rec.get("Sex", ""), "class": rec.get("Class", ""),
                    "biography": rec.get("Biography", ""),
                    "default": rec.get("Allowed By Default", "") == "X"})
    return out


if __name__ == "__main__":
    res = h4r.Resources(sys.argv[1])
    hs = heroes(res)
    print(len(hs), "heroes;", sorted({h["class"] for h in hs}))
    for h in hs[:3]:
        print(h)
    for name in ("layers.portraits.life.82.h4d",):
        ls = read_layers(res.read(name))
        print(name, len(ls), [(n, w, h) for n, w, h, _ in ls[:8]])
