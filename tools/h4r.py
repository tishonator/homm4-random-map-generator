"""Read the game's .h4r resource archives (read-only).

Layout (per h4r notes, https://github.com/demen1n/h4r): "H4R\\x05", u32 directory offset,
gzip blobs. Directory: u32 count, then per entry u32 offset, compressed size, size, time;
three u16-prefixed strings (name, source path, alias); u32 type. Aliased entries point at
another name and have no data of their own.
"""
import gzip
import os
import struct

# Order the game opens archives in; the first archive that has a name wins.
LOAD_ORDER = ["x2_override.h4r", "updates.h4r", "text.h4r", "music.h4r", "movies.h4r",
              "x2.h4r", "storm.h4r", "heroes4.h4r"]


class Archive:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            head = f.read(8)
            if head[:4] != b"H4R\x05":
                raise ValueError(f"{path} is not an .h4r archive")
            f.seek(struct.unpack_from("<I", head, 4)[0])
            d = f.read()
        self.entries = {}
        p = 4
        for _ in range(struct.unpack_from("<I", d, 0)[0]):
            off, csize, size, _t = struct.unpack_from("<4I", d, p)
            p += 16
            strs = []
            for _ in range(3):
                n = struct.unpack_from("<H", d, p)[0]
                strs.append(d[p + 2:p + 2 + n].decode("cp1252"))
                p += 2 + n
            p += 4
            self.entries[strs[0].lower()] = (off, csize, strs[2] or None)

    def read_raw(self, name):
        off, csize, _ = self.entries[name]
        with open(self.path, "rb") as f:
            f.seek(off)
            return gzip.decompress(f.read(csize))


class Resources:
    def __init__(self, data_dir):
        self.archives = [Archive(os.path.join(data_dir, n)) for n in LOAD_ORDER
                         if os.path.exists(os.path.join(data_dir, n))]

    def names(self):
        seen = set()
        for a in self.archives:
            seen.update(a.entries)
        return seen

    def read(self, name):
        name = name.lower()
        for _ in range(8):
            for a in self.archives:
                if name in a.entries:
                    alias = a.entries[name][2]
                    if alias:
                        name = alias.lower()
                        break
                    return a.read_raw(name)
            else:
                raise KeyError(name)
        raise KeyError(f"alias loop at {name}")
