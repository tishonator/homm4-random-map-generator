"""Read and write Heroes of Might and Magic IV map files (.h4c).

File layout (as observed in the game's own maps):
    "H4CAMPAIGN"  10 bytes magic
    u32           container version (22 in all shipped maps)
    u8            0
    gzip stream   the map body

The map body starts with:
    u16 format version (27 or 29 seen)
    [v28+ only] u16 unknown (1 or 2)
    u16 map size in tiles (76 small, 152 medium, 228 large, 304 extra large)
    u8  number of levels (1 = surface only, 2 = with underground)
    ...
    u16-length string: map name
    u16-length string: map description (v29 has one flag byte before it)

Usage:
    python h4c.py info  <map.h4c>...
    python h4c.py unpack <map.h4c> <out.bin>
    python h4c.py pack   <in.bin> <map.h4c>
    python h4c.py retitle <in.h4c> <out.h4c> "New name"
"""
import gzip
import struct
import sys

MAGIC = b"H4CAMPAIGN"
CONTAINER_VERSION = 22


def read_container(path):
    data = open(path, "rb").read()
    if not data.startswith(MAGIC):
        raise ValueError(f"{path}: not an .h4c file")
    version = struct.unpack_from("<I", data, 10)[0]
    return version, gzip.decompress(data[15:])


def write_container(path, body, version=CONTAINER_VERSION):
    packed = gzip.compress(body, compresslevel=9, mtime=0)
    with open(path, "wb") as f:
        f.write(MAGIC + struct.pack("<I", version) + b"\x00" + packed)


TOWN_BITS = ["life", "order", "death", "chaos", "nature", "might"]  # bit order is a guess


class Reader:
    def __init__(self, data, pos=0):
        self.d, self.pos = data, pos

    def u8(self):
        v = self.d[self.pos]
        self.pos += 1
        return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.pos)[0]
        self.pos += 2
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.pos)[0]
        self.pos += 4
        return v

    def string(self):
        n = self.u16()
        s = self.d[self.pos:self.pos + n]
        self.pos += n
        return s.decode("latin-1")


def header(body):
    """Decode the map header. Returns a dict plus the offsets needed for editing."""
    r = Reader(body)
    h = {"format": r.u16()}
    if h["format"] >= 28:
        h["unknown_a"] = r.u16()
    h["size"] = r.u16()
    h["levels"] = r.u8()
    h["unknown_b"] = r.u32()
    players = []
    for _ in range(r.u8()):
        color, human, computer, unk, towns = (r.u8() for _ in range(5))
        players.append({"color": color, "human": human, "computer": computer,
                        "unknown": unk, "town_mask": towns})
    h["players"] = players
    h["name_offset"] = r.pos
    h["name"] = r.string()
    h["difficulty"] = r.u8()
    h["description"] = r.string()
    h["end_offset"] = r.pos
    return h


def retitle(body, new_name):
    h = header(body)
    off = h["name_offset"]
    old_len = struct.unpack_from("<H", body, off)[0]
    raw = new_name.encode("latin-1")
    return body[:off] + struct.pack("<H", len(raw)) + raw + body[off + 2 + old_len:]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == "info":
        for p in argv[2:]:
            try:
                _, body = read_container(p)
                h = header(body)
                print(f"{p}: format={h['format']} size={h['size']} levels={h['levels']} name={h['name']!r}")
            except Exception as e:  # keep going over a folder of maps
                print(f"{p}: ERROR {e}")
    elif cmd == "unpack":
        _, body = read_container(argv[2])
        open(argv[3], "wb").write(body)
    elif cmd == "pack":
        write_container(argv[3], open(argv[2], "rb").read())
    elif cmd == "retitle":
        version, body = read_container(argv[2])
        write_container(argv[3], retitle(body, argv[4]), version)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
