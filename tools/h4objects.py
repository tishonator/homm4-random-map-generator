"""Scripts, events and the object list of a Heroes IV map body.

The layout follows the h4r project's reverse-engineering notes and readers
(https://github.com/demen1n/h4r: decomp/h4c.md, map_body.rs, map_script.rs, map_army.rs).
This is an independent Python implementation.

Objects are kept with their raw bytes, so a map re-encodes byte for byte; the reader
decodes just enough to find where each object ends, plus a few useful fields.
"""
import struct
from dataclasses import dataclass

from h4map import Reader

# ---------------------------------------------------------------- small pieces

ARTIFACTS_WITH_SPELL = (0x7C, 0xA6)


def artifact(r):
    t = r.u16()
    if t >= 249:
        raise ValueError(f"artifact type {t} at {r.pos - 2:#x}")
    if t in ARTIFACTS_WITH_SPELL:
        r.u16()
    return t


def artifact_list(r):
    return [artifact(r) for _ in range(r.u16())]


def spell_set(r):
    v = r.u8()
    if v not in (0, 1, 2):
        raise ValueError(f"spell set version {v} at {r.pos - 1:#x}")
    r.take(23 if v == 0 else 24)


def skill_set(r):
    if r.u8() != 0:
        raise ValueError(f"skill set version at {r.pos - 1:#x}")
    r.take(5)


def i32(r):
    return struct.unpack("<i", r.take(4))[0]


# ---------------------------------------------------------------- scripts

def script(r):
    version = r.u16()
    action(r, version)


def sequence(r, version):
    for _ in range(r.u16()):
        action(r, version)


def action(r, version):
    kind = r.string()
    if kind in ("build", "change_owner", "clear_lc_text", "clear_l_msg", "clear_vc_text",
                "clear_v_msg", "disable_vc", "enable_vc", "lose", "win"):
        r.u8()
    elif kind == "combat":
        r.u8()
        army(r)
        action(r, version)
        action(r, version)
    elif kind == "if":
        boolean(r)
        action(r, version)
        action(r, version)
    elif kind in ("dec_mana", "inc_mana", "dec_pop", "inc_pop", "give_spell"):
        r.u8()
        r.u16()
    elif kind in ("dec_damage", "dec_max_hp", "dec_max_mana", "dec_speed", "inc_damage",
                  "inc_max_hp", "inc_max_mana", "inc_speed"):
        r.u8()
        r.u16()
        r.u8()
    elif kind in ("dec_luck", "dec_morale", "inc_luck", "inc_morale", "inc_move", "inc_level"):
        r.u8()
        r.u8()
    elif kind in ("detonate", "gosub"):
        r.string()
    elif kind == "text":
        r.string()
        if version >= 1:
            sequence(r, version)
    elif kind in ("give_artifact", "rem_artifact"):
        r.u8()
        artifact_list(r)
    elif kind in ("give_creature", "take_creature"):
        r.u8()
        r.u16()
        r.u16()
    elif kind in ("give_material", "take_material"):
        r.u8()
        r.take(28)
    elif kind in ("give_skill", "inc_skill"):
        r.take(3)
    elif kind == "inc_exp":
        r.u8()
        r.u32()
    elif kind in ("no_op", "rem_event", "rem_this"):
        pass
    elif kind == "ask":
        r.string()
        action(r, version)
        action(r, version)
    elif kind == "seq":
        sequence(r, version)
    elif kind == "set_bool":
        r.string()
        boolean(r)
    elif kind == "set_num":
        r.string()
        numeric(r)
    elif kind in ("set_lc_text", "set_l_msg", "set_vc_text", "set_v_msg"):
        r.u8()
        r.string()
    else:
        raise ValueError(f"unknown script action {kind!r} at {r.pos:#x}")


def numeric(r):
    kind = r.string()
    if kind in ("day", "dow", "month", "week", "wom"):
        pass
    elif kind in ("/", "-", "+", "%", "*"):
        numeric(r)
        numeric(r)
    elif kind == "neg":
        numeric(r)
    elif kind == "creatures":
        r.u8()
        r.u16()
    elif kind in ("exp_level", "player", "total_creatures", "total_heroes"):
        r.u8()
    elif kind in ("mastery", "materials"):
        r.take(2)
    elif kind == "lit":
        r.take(4)
    elif kind == "rand":
        r.take(8)
    elif kind == "var":
        r.string()
    else:
        raise ValueError(f"unknown numeric expression {kind!r} at {r.pos:#x}")


def boolean(r):
    kind = r.string()
    if kind in ("and", "or"):
        boolean(r)
        boolean(r)
    elif kind == "not":
        boolean(r)
    elif kind in ("==", ">", ">=", "<", "<="):
        numeric(r)
        numeric(r)
    elif kind in ("true", "false"):
        pass
    elif kind in ("has_alignment", "is_alignment", "is_color"):
        r.take(2)
    elif kind in ("has_hero", "owns_hero", "owns_town"):
        r.u8()
        r.string()
    elif kind == "give_skill?":
        r.take(3)
    elif kind == "has_artifact":
        r.take(2)
        artifact(r)
    elif kind in ("is_dead", "is_imprisoned", "var"):
        r.string()
    elif kind in ("is_computer", "is_eliminated", "is_human"):
        r.u8()
    else:
        raise ValueError(f"unknown boolean expression {kind!r} at {r.pos:#x}")


def versioned_boolean(r):
    r.u16()
    boolean(r)


# ---------------------------------------------------------------- events

def discrete(r):
    script(r)
    r.string()       # message
    r.take(28)       # 7 x i32 resources


def timed_base(r):
    discrete(r)
    r.string()       # name
    r.u16()          # first day
    r.u16()          # repeat


def global_events(r):
    for _ in range(r.u16()):
        r.zero("timed event")
        timed_base(r)
        r.take(2)
    for _ in range(r.u16()):
        r.zero("triggerable event")
        discrete(r)
        r.string()
    for _ in range(r.u16()):
        r.zero("continuous event")
        script(r)
        r.string()
    for _ in range(r.u16()):
        v = r.u16()
        if v > 1:
            raise ValueError("placed event version")
        discrete(r)
        if v >= 1:
            r.take(2)
        r.string()


def built_in(r):
    r.zero("built-in event")
    discrete(r)
    r.take(2)


def owned_timed(r):
    for _ in range(r.u16()):
        r.zero("owned timed event")
        timed_base(r)
        r.take(2)


def owned_triggerable(r):
    for _ in range(r.u16()):
        r.zero("owned triggerable event")
        discrete(r)
        r.string()
        r.take(2)


def owned_continuous(r):
    for _ in range(r.u16()):
        r.zero("owned continuous event")
        script(r)
        r.string()
        r.take(3)


def owned_events(r, n_built_in):
    for _ in range(n_built_in):
        built_in(r)
    owned_timed(r)
    owned_triggerable(r)
    owned_continuous(r)


# ---------------------------------------------------------------- armies and heroes

def army(r):
    r.zero("army")
    for _ in range(7):
        slot = r.u8()
        if slot == 0xFF:
            continue
        if slot == 0:
            v = r.u16()
            if v > 1:
                raise ValueError(f"creature stack version {v}")
            r.take(4)        # i16 type, i16 count
            if v >= 1:
                artifact_list(r)
        elif slot == 1:
            hero(r)
        else:
            raise ValueError(f"army slot {slot} at {r.pos - 1:#x}")


def hero(r):
    v = r.u16()
    if not 8 <= v <= 10:
        raise ValueError(f"hero version {v}")
    r.take(5)                        # portrait, class, gender, u8
    r.take(4 if v < 10 else 2)
    r.take(2)
    r.string()                       # name
    r.string()                       # biography
    if r.u8():
        r.take(36)                   # skills
    spell_set(r)
    for _ in range(14):
        if r.u8():
            artifact(r)
    artifact_list(r)
    owned_events(r, 3)
    if v >= 9:
        r.u8()


def map_army(r):
    v = r.u16()
    if not 3 <= v <= 9:
        raise ValueError(f"map army version {v}")
    owner = r.u8()
    army(r)
    if v == 4 or (v >= 5 and r.u8()):
        r.take(2)
    if v >= 6:
        owned_events(r, 3)
    for k in (7, 8, 9):
        if v >= k:
            r.u8()
    return owner


# ---------------------------------------------------------------- placed objects

PLAIN = {
    "academy", "arena", "artifact_pile", "blacksmith", "blattner_stone", "border_gate",
    "border_guard", "bridge", "buoy", "campfire", "cartographer", "chain", "clover_field",
    "coliseum", "corpse", "creature_bank", "decorative", "dolphin_school", "exhausted_mine",
    "eye_of_the_magi", "faerie_ring", "flotsam", "fountain", "hut_of_the_magi", "idol_of_fortune",
    "kelp_beds", "keymaster_tent", "magic_gem", "mana_recharger", "material_pile",
    "medicine_wagon", "mercenary_camp", "movement_booster", "nothing", "obelisk", "oyster",
    "path_arrow", "pathfinder", "port", "rainbow", "random_artifact", "random_material_pile",
    "random_potion", "random_staff", "random_tome", "sacred_grove", "sanctuary", "selection_ring",
    "ship", "shipwreck_survivor", "sphinx", "stagecoach", "system_object", "tavern", "temple",
    "tower", "trading_post", "training_grounds", "treasure", "tree_of_knowledge", "vein",
    "victory_flag",
}
NAMED = {"deletion_marker", "event_trigger", "ferry", "gateway", "ocean_bottle", "pandoras_box",
         "sign", "subterranean_gate", "teleporter_entrance", "teleporter_exit", "whirlpool"}
SCRIPTABLE = {"creature_dwelling", "lighthouse", "random_weekly_material_generator", "shipyard",
              "weekly_material_generator", "windmill"}


def version(r, top, what):
    v = r.u16()
    if v > top:
        raise ValueError(f"{what}: version {v} at {r.pos - 2:#x}")
    return v


def random_kind(r):
    r.zero("random kind")
    k = r.string()
    if k == "player":
        r.u8()
    elif k == "town":
        r.string()
    elif k != "none":
        raise ValueError(f"random kind {k!r}")
    return k


def owned_scriptable(r, v):
    owner = None
    if v >= 1:
        owner = r.u8()
    if v >= 2:
        owned_triggerable(r)
    return owner


def town_data(r):
    v = r.u16()
    if not 6 <= v <= 8:
        raise ValueError(f"town data version {v}")
    owner = r.u8()
    r.string()                    # town name
    if r.u8():
        army(r)                   # garrison
    if r.u8():
        r.take(12)                # building sets
    else:
        r.u8()
    for _ in range(4):
        built_in(r)
    owned_timed(r)
    owned_triggerable(r)
    owned_continuous(r)
    if v >= 7 and r.u8():
        skill_set(r)
        skill_set(r)
    if v >= 8:
        r.u8()
    return owner


def body(r, t):
    """Skip one object body of type t. Returns the owner where stored, else None."""
    if t in PLAIN:
        r.zero(t)
    elif t in NAMED:
        if version(r, 1, t) >= 1:
            r.string()
    elif t in SCRIPTABLE:
        return owned_scriptable(r, version(r, 2, t))
    elif t in ("school", "teacher"):
        if version(r, 1, t) >= 1:
            skill_set(r)
            skill_set(r)
    elif t in ("mine", "garrison"):
        v = version(r, 2, t)
        owner = r.u8() if v >= 1 else 6
        if v >= 2 and owner != 6:
            r.u8()
        if v >= 2:
            for _ in range(4):
                built_in(r)
        owned_continuous(r)
        owned_timed(r)
        owned_triggerable(r)
        if v >= 2 and r.u8():
            army(r)
        return owner
    elif t == "abandoned_mine":
        v = version(r, 1, t)
        if v >= 1:
            for _ in range(4):
                built_in(r)
        owned_continuous(r)
        owned_timed(r)
        owned_triggerable(r)
        if v >= 1 and r.u8():
            army(r)
    elif t == "artifact":
        if version(r, 1, t) >= 1:
            r.u32()
    elif t == "conservatory":
        if version(r, 1, t) >= 1:
            spell_set(r)
            spell_set(r)
    elif t == "obelisk_marker":
        if version(r, 1, t) >= 1:
            r.u16()
    elif t == "outpost":
        if version(r, 1, t) >= 1:
            return r.u8()
    elif t == "prison":
        if version(r, 1, t) >= 1:
            hero(r)
    elif t == "carryover_hero":
        v = version(r, 2, t)
        if v >= 1:
            owner = r.u8()
            r.string()
            if v >= 2 and r.u8():
                r.take(2)
            owned_events(r, 3)
            return owner
    elif t == "random_creature_dwelling":
        v = version(r, 3, t)
        owner = owned_scriptable(r, {0: 0, 1: 1, 2: 1}.get(v, 2))
        if v >= 2:
            random_kind(r)
        return owner
    elif t == "random_conservatory":
        v = version(r, 2, t)
        if v == 2:
            spell_set(r)
            spell_set(r)
        if v >= 1:
            random_kind(r)
    elif t in ("random_monster", "random_random_monster"):
        v = version(r, 4, t)
        if v >= 3 and r.u8():
            r.take(2)
        if v >= 2:
            owned_events(r, 3)
        if v >= 1:
            random_kind(r)
        if v >= 4 and i32(r) >= 0:
            r.take(4)
    elif t == "random_shrine":
        v = version(r, 3, t)
        if v == 1:
            r.take(23)
        elif v >= 2:
            spell_set(r)
        if v >= 3:
            random_kind(r)
    elif t == "shrine":
        v = version(r, 2, t)
        if v == 1:
            r.take(23)
        elif v == 2:
            spell_set(r)
    elif t == "random_teacher":
        if version(r, 1, t) >= 1:
            r.u16()
            random_kind(r)
    elif t == "random_temple":
        if version(r, 1, t) >= 1:
            random_kind(r)
    elif t in ("quest_gate", "quest_guard", "seers_hut"):
        v = version(r, 1 if t == "quest_gate" else 2, t)
        if v:
            for _ in range(4):
                r.string()
            script(r)
            versioned_boolean(r)
            if t == "quest_guard":
                r.string()
                if v >= 2:
                    script(r)
            elif t == "seers_hut":
                r.string()
                if v >= 2:
                    script(r)
                r.string()
                if v < 2:
                    script(r)
    elif t == "random_town":
        if r.u16() != 7:
            raise ValueError("random town version")
        random_kind(r)
        return town_data(r)
    elif t == "town":
        if r.u16() != 4:
            raise ValueError("town version")
        spell_set(r)
        spell_set(r)
        return town_data(r)
    else:
        raise ValueError(f"object type {t!r} has no reader")
    return None


@dataclass
class MapObject:
    x: int            # row
    y: int            # column
    level: int
    is_army: bool
    model: str        # "" for armies
    kind: tuple       # ((id, type), (id, major), (id, minor)); () for armies
    owner: object     # owner color where stored, else None
    raw: bytes        # everything after the 13-byte position/army header

    @property
    def type(self):
        return self.kind[0][1] if self.kind else "army"

    def encode(self):
        return struct.pack("<iiiB", self.x, self.y, self.level, self.is_army) + self.raw


def read_objects(data, pos):
    """Read the object list at pos. Returns (objects, end_pos)."""
    r = Reader(data, pos)
    out = []
    for _ in range(r.u32()):
        x, y, lv, is_army = struct.unpack("<iiiB", r.take(13))
        start = r.pos
        if is_army:
            owner = map_army(r)
            out.append(MapObject(x, y, lv, True, "", (), owner, bytes(data[start:r.pos])))
            continue
        model = r.string()
        r.zero("object type")
        kind = tuple((r.u16(), r.string()) for _ in range(3))
        owner = body(r, kind[0][1])
        out.append(MapObject(x, y, lv, False, model, kind, owner, bytes(data[start:r.pos])))
    return out, r.pos


def encode_objects(objects):
    return struct.pack("<I", len(objects)) + b"".join(o.encode() for o in objects)


# ---------------------------------------------------------------- building new objects

def placed(x, y, level, model, kind, body_bytes=b"\x00\x00"):
    """A placed object. kind = ((id, type), (id, major), (id, minor))."""
    raw = bytearray()
    m = model.encode("cp1252")
    raw += struct.pack("<H", len(m)) + m + b"\x00\x00"
    for i, name in kind:
        n = name.encode("cp1252")
        raw += struct.pack("<H", i) + struct.pack("<H", len(n)) + n
    raw += body_bytes
    return MapObject(x, y, level, False, model, tuple(kind), None, bytes(raw))
