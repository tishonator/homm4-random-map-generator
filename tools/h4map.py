"""Map header and "rules" sections of a Heroes IV map body: everything up to the object list.

Layout follows the h4r project's notes (https://github.com/demen1n/h4r, decomp/h4c.md and
map_body.rs); this is an independent implementation. Global events (scripts) are
skipped with the reader in h4objects and kept as raw bytes; a generated map writes
empty event lists.
"""
import struct
from dataclasses import dataclass, field


class Reader:
    def __init__(self, data, pos=0):
        self.d, self.pos = data, pos

    def take(self, n):
        if self.pos + n > len(self.d):
            raise ValueError(f"read past end at {self.pos:#x}")
        b = self.d[self.pos:self.pos + n]
        self.pos += n
        return b

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def string(self):
        return self.take(self.u16()).decode("cp1252")

    def zero(self, what):
        v = self.u16()
        if v != 0:
            raise ValueError(f"{what}: version {v} at {self.pos - 2:#x}")


class Writer:
    def __init__(self):
        self.b = bytearray()

    def u8(self, v):
        self.b.append(v)

    def u16(self, v):
        self.b += struct.pack("<H", v)

    def u32(self, v):
        self.b += struct.pack("<I", v)

    def raw(self, v):
        self.b += v

    def string(self, s):
        raw = s.encode("cp1252")
        self.u16(len(raw))
        self.b += raw


@dataclass
class PlayerSlot:
    color: int            # 0..5
    playable: int = 1     # can be chosen by a human
    unknown: int = 0
    town_mask: int = 0x3F  # allowed town types, 6 bits


@dataclass
class CutScene:
    text: str
    first: str
    second: str


@dataclass
class MapRules:
    """Header plus the sections up to (not including) the object list."""
    version: int = 29
    expansion: int = 2
    size: int = 76
    levels: int = 1
    terrain_seed: int = 0
    players: list = field(default_factory=list)
    name: str = ""
    difficulty: int = 1
    description: str = ""
    teams: list = field(default_factory=list)  # color bit masks
    loss_text: str = None
    victory_text: str = None
    flag_a: int = 1                 # version >= 25
    cut_scenes: list = field(default_factory=lambda: [None, None])  # version >= 24
    notes: str = ""                 # version >= 27
    flag_b: int = 0                 # version >= 29
    # Everything from the global events up to the object count, kept as raw bytes
    # when read from a file. None = write defaults (no events, everything allowed).
    middle_raw: bytes = None


def _artifact(r):
    t = r.u16()
    if t in (0x7C, 0xA6):
        r.u16()


def _bitset(r):
    r.zero("bit set")
    n = r.u16()
    r.take((n + 7) // 8)


def read_rules(body):
    """Parse the header and the rules sections. Returns (MapRules, objects_offset).

    objects_offset points at the u32 object count.
    """
    r = Reader(body)
    m = MapRules()
    m.version = r.u16()
    m.expansion = r.u16() if m.version >= 28 else 0
    m.size = r.u16()
    m.levels = r.u8()
    m.terrain_seed = r.u32()
    for _ in range(r.u8()):
        color, playable, unknown = r.u8(), r.u8(), r.u8()
        if r.u8() != 0:
            raise ValueError("town type set version")
        m.players.append(PlayerSlot(color, playable, unknown, r.u8()))
    m.name = r.string()
    m.difficulty = r.u8()
    m.description = r.string()
    r.zero("teams")
    m.teams = list(r.take(r.u8()))
    m.loss_text = r.string() if r.u8() else None
    m.victory_text = r.string() if r.u8() else None
    if m.version >= 25:
        m.flag_a = r.u8()
    if m.version >= 24:
        scenes = []
        for _ in range(2):
            if r.u8():
                r.zero("cut scene")
                scenes.append(CutScene(r.string(), r.string(), r.string()))
            else:
                scenes.append(None)
        m.cut_scenes = scenes
    if m.version >= 27:
        m.notes = r.string()
    if m.version >= 29:
        m.flag_b = r.u8()

    mid_start = r.pos
    from h4objects import global_events  # late import: h4objects imports this module
    global_events(r)
    for _ in range(12):  # obelisk rewards
        r.zero("obelisk")
        has = r.u8()
        r.u16()
        if has:
            for _ in range(r.u16()):
                r.zero("obelisk reward")
                kind = r.string()
                if kind == "artifact":
                    _artifact(r)
                    r.u32()
                elif kind == "material":
                    r.u8()
                    r.u32()
                else:
                    raise ValueError(f"obelisk reward {kind!r}")
    for _ in m.players:  # per-player data
        r.u8()
        if r.u8():
            r.u16()
        if m.version >= 23:
            r.u8()
    if m.version > 17:
        if r.u8():
            _bitset(r)  # allowed artifacts
        if r.u8():
            r.take(r.u16())  # unknown bool array
    if m.version >= 18 and r.u8():
        if r.u8() != 0:
            raise ValueError("skill set version")
        r.take(5)  # allowed skills
    if m.version > 17 and r.u8():
        n = r.u16()  # allowed spells
        r.take((n + 7) // 8)
    if m.version >= 22:
        _bitset(r)
        _bitset(r)
    if m.version >= 23:  # AI importance: artifacts, spells, spells
        for _ in range(3):
            r.zero("AI importance")
            r.take(3 * r.u16())
    m.middle_raw = bytes(body[mid_start:r.pos])
    return m, r.pos


ARTIFACT_BITS = 248


def default_middle(m):
    """Rules sections for a new version-29 map: no events, no obelisk rewards, game defaults.

    Matches byte for byte what the editor wrote in the 16 shipped v29 maps that use defaults.
    """
    w = Writer()
    for _ in range(4):
        w.u16(0)                     # no global events
    for _ in range(12):
        w.u16(0)                     # obelisk: version
        w.u8(0)                      # no rewards
        w.u16(0xFFFF)
    for p in m.players:
        w.u8(p.color)
        w.u8(0)                      # flag off
        w.u8(0)                      # version >= 23 byte
    w.u8(0)                          # allowed artifacts: defaults
    w.u8(0)                          # unknown bool array: none
    w.u8(0)                          # allowed skills: defaults
    w.u8(0)                          # allowed spells: defaults
    for fill in (0xFF, 0x00):        # two artifact sets: all on, all off
        w.u16(0)
        w.u16(ARTIFACT_BITS)
        w.raw(bytes([fill]) * (ARTIFACT_BITS // 8))
    for _ in range(3):               # AI importance tables, empty
        w.u16(0)
        w.u16(0)
    return bytes(w.b)


def write_rules(m):
    """Encode header and rules sections (up to, not including, the object count)."""
    w = Writer()
    w.u16(m.version)
    if m.version >= 28:
        w.u16(m.expansion)
    w.u16(m.size)
    w.u8(m.levels)
    w.u32(m.terrain_seed)
    w.u8(len(m.players))
    for p in m.players:
        for v in (p.color, p.playable, p.unknown, 0, p.town_mask):
            w.u8(v)
    w.string(m.name)
    w.u8(m.difficulty)
    w.string(m.description)
    w.u16(0)
    w.u8(len(m.teams))
    w.raw(bytes(m.teams))
    for text in (m.loss_text, m.victory_text):
        w.u8(text is not None)
        if text is not None:
            w.string(text)
    if m.version >= 25:
        w.u8(m.flag_a)
    if m.version >= 24:
        for s in m.cut_scenes:
            w.u8(s is not None)
            if s is not None:
                w.u16(0)
                w.string(s.text)
                w.string(s.first)
                w.string(s.second)
    if m.version >= 27:
        w.string(m.notes)
    if m.version >= 29:
        w.u8(m.flag_b)
    w.raw(m.middle_raw if m.middle_raw is not None else default_middle(m))
    return bytes(w.b)
