"""Build data files the generator needs from the maps shipped with the game.

- data/type_ids.json: object type name -> numeric id used by the newest map editor.
  Ids shifted between game versions (the game looks objects up by name first), so we
  take the highest id seen for each type.
- data/templates.json: object bodies copied from shipped maps, with owner byte offsets:
  random town (player and neutral) and a starting hero army.
- data/portraits.json: the hero portrait list of heroes4.exe (keyword, faction number). A map's
  hero record stores the index in this list, not the row of table.heroes.

Usage: python build_data.py <game Maps folder>
"""
import collections
import re
import struct
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import h4full  # noqa: E402
import h4map  # noqa: E402
import h4objects  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def _kind_end(raw):
    """Offset of the body: after the model string, u16 0 and the three kind strings."""
    r = h4map.Reader(raw)
    r.string()
    r.u16()
    for _ in range(3):
        r.u16()
        r.string()
    return r.pos


def exe_portraits(exe):
    """[(keyword, faction)] from heroes4.exe: a table of (char *keyword, u32 faction) pairs.
    Found from the pointer to the keyword "aidan" (the first chaos portrait)."""
    d = open(exe, "rb").read()
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec, opt = struct.unpack_from("<H", d, pe + 6)[0], struct.unpack_from("<H", d, pe + 20)[0]
    base = struct.unpack_from("<I", d, pe + 52)[0]
    secs = [struct.unpack_from("<IIII", d, pe + 24 + opt + 40 * i + 8) for i in range(nsec)]

    def va(o):
        return next(base + v + o - rp for vs, v, rs, rp in secs if rp <= o < rp + rs)

    def off(a):
        return next((a - base - v + rp for vs, v, rs, rp in secs if base + v <= a < base + v + rs), None)

    first = re.search(rb"\x00aidan\x00", d).start() + 1
    p = d.index(struct.pack("<I", va(first)))
    out = []
    while True:
        ptr, faction = struct.unpack_from("<II", d, p)
        o = off(ptr)
        if o is None or faction > 5:
            break
        out.append((d[o:d.index(b"\x00", o)].decode("latin-1"), faction))
        p += 8
    return out


def main(maps):
    ids = collections.defaultdict(int)
    templates = {}
    for p in sorted(glob.glob(os.path.join(maps, "**", "*.h4c"), recursive=True)):
        m = h4full.load(p)
        name = os.path.basename(p)
        for o in m.objects:
            if not o.is_army:
                ids[o.type] = max(ids[o.type], o.kind[0][0])
        if name == "Gory Days.h4c":
            for o in m.objects:
                # simplest random town: random type, no name, no garrison, default buildings
                if o.type == "random_town" and o.owner == 2 and "town_left" not in templates:
                    templates["town_left"] = o
                if o.type == "random_town" and o.owner == 0 and "town_right" not in templates:
                    templates["town_right"] = o
        if name == "Barbarians from Below.h4c":
            for o in m.objects:
                if o.type == "town" and "town_spells" not in templates:
                    templates["town_spells"] = o
        if name == "A Tale of Two Enemies.h4c":
            for o in m.objects:
                if o.is_army and o.owner == 1:
                    templates["hero_army"] = o
    out = {}
    # Fixed-faction towns: "town" body = u16 4, two spell sets (copied from a shipped town),
    # then the same town data as the plain random town (default buildings, no garrison).
    o = templates.pop("town_spells")
    r = h4map.Reader(o.raw, _kind_end(o.raw))
    assert r.u16() == 4
    h4objects.spell_set(r)
    h4objects.spell_set(r)
    spells = o.raw[_kind_end(o.raw):r.pos]
    rt = templates["town_left"]
    r = h4map.Reader(rt.raw, _kind_end(rt.raw))
    r.u16()
    h4objects.random_kind(r)
    town_data = rt.raw[r.pos:]
    out["town_fixed"] = {"body_prefix": spells.hex(), "town_data": town_data.hex(), "owner_offset": 2}
    for key, o in templates.items():
        raw = bytearray(o.raw)
        if key.startswith("town"):
            marker = b"\x04\x00none\x08\x00"
            off = raw.index(marker) + len(marker)
            out[key] = {"model": o.model, "kind": o.kind, "raw": raw.hex(), "owner_offset": off}
        else:
            out[key] = {"raw": raw.hex(), "owner_offset": 2}
    json.dump(dict(sorted(ids.items())), open(os.path.join(DATA, "type_ids.json"), "w"), indent=0)
    json.dump(out, open(os.path.join(DATA, "templates.json"), "w"), indent=1)
    print(f"{len(ids)} type ids, templates: {sorted(out)}")
    exe = os.path.join(maps, "..", "heroes4.exe")
    if os.path.isfile(exe):
        ports = exe_portraits(exe)
        json.dump(ports, open(os.path.join(DATA, "portraits.json"), "w"), indent=0)
        print(f"{len(ports)} hero portraits")


if __name__ == "__main__":
    main(sys.argv[1])
