"""Random map generator for Heroes of Might and Magic IV.

Usage:
    python generator.py [--seed N] [--size small|medium] [--players 2..6] [--out <Maps folder>]
                        [--png preview.png]

Writes _random_map_<seed>.h4c (title _Random_Map_<seed>) as a format-29 / expansion-2 map, so it
is listed at the very top of the game's scenario list.

How a map is built:
1. Zones. Each player gets a start zone; neutral zones fill the rest. Zone centres are laid out
   in screen space (the map is a diamond in row/column space, a square on screen) and cells go
   to the nearest centre, with a wavy distortion so borders are not straight.
2. Walls. Cells on a zone border (and on the map edge) are filled with obstacles of the zone's
   terrain (trees, rocks, mountains). Zones are joined by one-cell passages, each guarded by a
   random monster; the zone graph is a spanning tree plus a few extra links.
3. Content. Start zones get the player's town and hero, a sawmill and ore pit and small
   treasure. Neutral zones get rare mines, dwellings, shrines, artifacts and treasure, guarded
   by monsters that get stronger towards the middle of the map.
4. Paths. Every object entrance and passage is linked to the zone's hub by a reserved path
   (A*), so filler obstacles never cut anything off. Main paths get roads.
5. Tiles. Terrain and road transitions (blended edges) are computed like the editor does.
"""
import argparse
import heapq
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
import h4full  # noqa: E402
import h4map  # noqa: E402
import h4objects  # noqa: E402
import heroinfo  # noqa: E402
import h4tiles  # noqa: E402
import naming  # noqa: E402
import transitions  # noqa: E402

# data/ next to tools/, or inside the packaged program (PyInstaller unpacks it to sys._MEIPASS)
DATA = (os.path.join(sys._MEIPASS, "data") if getattr(sys, "frozen", False)
        else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))


def _load(name):
    with open(os.path.join(DATA, name)) as f:
        return json.load(f)


FOOT = _load("footprints.json")            # keys: lower-case model names
CATALOG = _load("object_catalog.json")     # keys: model names as the maps spell them
TYPE_IDS = _load("type_ids.json")
TEMPLATES = _load("templates.json")
PORTRAITS = _load("portraits.json")      # [(keyword, faction)], index = portrait number

SIZES = {"small": 76, "medium": 152, "large": 228, "xl": 304}
GRASS, ROUGH, SWAMP, VOLCANIC, SNOW, SAND, DIRT, SUBTERRANEAN = 1, 2, 3, 4, 5, 6, 7, 8
LAND = [GRASS, ROUGH, SWAMP, VOLCANIC, SNOW, SAND, DIRT, SUBTERRANEAN]
START_TERRAINS = [GRASS, DIRT, ROUGH, SNOW, SAND, SWAMP, VOLCANIC]
ROAD_DIRT, ROAD_COBBLE = 2, 3

OBSTACLES = {
    GRASS: ["trees.Pine.", "trees.Grass.", "rocks.Grass."],
    ROUGH: ["mountains.Rough.", "rocks.Rough.", "trees.Dead."],
    SWAMP: ["trees.Swamps.", "rocks.Swamp."],
    VOLCANIC: ["trees.Dead.", "rocks.Lava.", "mountains.Lava."],
    SNOW: ["trees.Snow.", "rocks.Snow.", "mountains.Snow."],
    SAND: ["trees.Desert.", "rocks.Sand.", "mountains.Desert.", "shrubs.cactus."],
    DIRT: ["trees.Grass.", "trees.Pine.", "rocks.Rough.", "mountains.Rough."],
    SUBTERRANEAN: ["mountains.Subterranean.", "rocks.subterranean."],
}

# Cell states
FREE, WALL, BLOCK, OCC, RES = 0, 1, 2, 3, 4
WALKABLE = (FREE, OCC, RES)

DIR8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
DIR4 = [(-1, 0), (1, 0), (0, -1), (0, 1)]

# Bodies for "random" objects that pick their kind from nothing in particular (the catalog's most
# common bodies tie them to a player's town type).
NONE_KIND = "00000400" + b"none".hex()
BODIES = {
    "random_creature_dwelling": "0300" + "06" + "0000" + NONE_KIND,
    "random_temple": "0100" + NONE_KIND,
    "random_shrine": "030002ffffffff9f" + "ff" * 18 + "00" + NONE_KIND,
}

MONSTER = {1: "Random creatures.RandomLv1", 2: "Random creatures.RandomLv2",
           3: "Random creatures.RandomLv3", 4: "Random creatures.RandomLv4"}
RARE_MINES = [("mine.Crystal", "mine.Crystal R"), ("mine.Gem", "mine.Gem R"),
              ("mine.Sulfur", "mine.Sulfur R"), ("mine.Alchemists Lab", "mine.Alchemists Lab R")]
SAWMILL = ("mine.Sawmill", "mine.Sawmill R")
ORE_PIT = ("mine.ore pit", "mine.Ore Pit R")
GOLD_MINE = ("mine.Gold", "mine.Gold R")
RESOURCE = "Resources.Random Resource"
CHEST = "Resources.Treasure Chest"
CAMPFIRE = "Resources.Campfire"
FOUNTAINS = ["power ups.Fountain of Fortune", "power ups.Fountain of Strength",
             "power ups.Fountain of Vigor", "power ups.Spring of Speed", "power ups.Pool of Power",
             "Mana Rechargers.magic well", "movement modifiers.Water Trough",
             "moral-luck boosters.Adventurers Totem"]
GEMS = ["power ups.Ruby", "power ups.Emerald", "power ups.Opal", "power ups.Sapphire"]
SCHOOLS = ["Skill Enhancer.Library", "Skill Enhancer.Witch's Hut", "Skill Enhancer.School of Magic",
           "Skill Enhancer.School of War", "Skill Enhancer.Veteran's_Guild",
           "Skill Enhancer.beastmaster's hut", "Skill Enhancer.Magic University",
           "Skill Enhancer.War College"]
BANKS = ["creature bank.Bandit Camp", "creature bank.Keep", "creature bank.Lair",
         "creature bank.Imp Cache", "creature bank.Graveyard", "creature bank.Crypt",
         "creature bank.Harpy Nest", "creature bank.Forest Glenn", "creature bank.Griffin Nest"]
DWELLING = {1: "creature generators.Random Creature 2x1", 2: "creature generators.Random Creature 2x2",
            3: "creature generators.Random Creature 2x3", 4: "creature generators.Random Creature 3x3"}
ARTIFACT = {"minor": "artifacts.random artifact.Minor", "major": "artifacts.random artifact.Major",
            "treasure": "artifacts.random artifact.Treasure", "item": "artifacts.random artifact.Item"}


# ---------------------------------------------------------------- objects

def footprint(model):
    return FOOT[model.lower()]


def make_object(model, r, c):
    """A placed object with the catalog's kind (newest type id) and body."""
    info = CATALOG[model]
    kind = [list(k) for k in info["kind"]]
    kind[0][0] = TYPE_IDS.get(kind[0][1], kind[0][0])
    body = BODIES.get(info["type"], info["body"])
    return h4objects.placed(r, c, 0, model, tuple(tuple(k) for k in kind), bytes.fromhex(body))


def make_town(variant, owner, r, c):
    t = TEMPLATES["town_" + variant]
    raw = bytearray.fromhex(t["raw"])
    raw[t["owner_offset"]] = owner
    kind = tuple(tuple(k) for k in t["kind"])
    return h4objects.MapObject(r, c, 0, False, t["model"], kind, owner, bytes(raw))


FACTIONS = ["life", "order", "death", "chaos", "nature", "might"]   # town type order; mask bit = 1 << i
FACTION_TOWN = {   # town models (left, right) with a fort, as the shipped maps use for start towns
    "life": ("castle.Haven.Fort", "castle.Haven.Fort R"),
    "order": ("castle.Academy.Fort", "castle.Academy.Fort R"),
    "death": ("castle.Necropolis.Fort", "castle.Necropolis.fort r"),
    "chaos": ("castle.Asylum.Fort", "castle.Asylum.Fort R"),
    "nature": ("castle.Preserve.fort", "castle.Preserve.fort r"),
    "might": ("castle.Stronghold.fort", "castle.Stronghold.fort r"),
}


# Hero record codes, as the shipped maps use them: class = the game's class table order,
# sex 0 female / 1 male, portrait = index in the exe's portrait list (data/portraits.json).
CLASS_CODE = {"knight": 0, "priest": 1, "lord": 2, "mage": 3, "death_knight": 4, "necromancer": 5,
              "thief": 6, "sorcerer": 7, "archer": 8, "druid": 9, "barbarian": 10}
SEX_CODE = {"female": 0, "male": 1}
PORTRAIT = {k.lower(): i for i, (k, _) in enumerate(PORTRAITS)}


def hero_settings(hero):
    """make_hero arguments for a hero of table.heroes (as read by h4data.heroes)."""
    return {"portrait": PORTRAIT.get(hero["keyword"].lower(), -1),
            "hero_class": CLASS_CODE.get(hero["class"].lower(), 0xFF),
            "sex": SEX_CODE.get(hero["sex"].lower(), 0xFF), "name": hero["name"],
            "biography": hero["biography"]}


def _str16(s):
    b = s.encode("cp1252", "replace")
    return len(b).to_bytes(2, "little") + b


def make_fixed_town(faction, variant, owner, r, c):
    """A town of a given faction: u16 4, two spell sets, town data (default buildings)."""
    t = TEMPLATES["town_fixed"]
    model = FACTION_TOWN[faction][0 if variant == "left" else 1]
    data = bytearray.fromhex(t["town_data"])
    data[t["owner_offset"]] = owner
    kind = ((TYPE_IDS["town"], "town"), (FACTIONS.index(faction), faction),
            (0 if variant == "left" else 1, variant))
    head = _str16(model) + b"\x00\x00" + b"".join(i.to_bytes(2, "little") + _str16(n) for i, n in kind)
    raw = head + bytes.fromhex(t["body_prefix"]) + bytes(data)
    return h4objects.MapObject(r, c, 0, False, model, kind, owner, raw)


def make_hero(owner, r, c, portrait=-1, hero_class=0xFF, sex=0xFF, name="", biography="", army=()):
    """A player's hero on the map. portrait = index in PORTRAITS (-1 random);
    hero_class / sex = 0xFF for random. The map stores the biography before the name.
    army = [(creature number, count)] for the hero's other army slots."""
    t = TEMPLATES["hero_army"]
    raw = bytearray.fromhex(t["raw"])
    raw[t["owner_offset"]] = owner
    assert raw[5] == 1 and raw[6:8] == b"\x0a\x00" and raw[17:21] == bytes(4), "hero template layout"
    head = portrait.to_bytes(2, "little", signed=True) + bytes((hero_class, sex))
    raw = bytes(raw[:8] + head + raw[12:17] + _str16(biography) + _str16(name) + raw[21:])
    if army:
        rd = h4map.Reader(raw, 6)
        h4objects.hero(rd)                     # skip the hero record to the other six slots
        p = rd.pos
        assert raw[p:p + 6] == b"\xff" * 6, "hero template slots"
        stacks = b"".join(b"\x00\x01\x00" + t.to_bytes(2, "little", signed=True)
                          + n.to_bytes(2, "little") + b"\x00\x00" for t, n in army[:6])
        raw = raw[:p] + stacks + b"\xff" * (6 - len(army[:6])) + raw[p + 6:]
    return h4objects.MapObject(r, c, 0, True, "", (), owner, raw)


def _obstacle_pools():
    pools = {}
    for terrain, prefixes in OBSTACLES.items():
        pool = []
        for model, info in CATALOG.items():
            if info["type"] != "decorative" or info["count"] < 3:
                continue
            if not any(model.startswith(p) for p in prefixes):
                continue
            fp = FOOT.get(model.lower())
            if not fp or fp["w"] > 3 or fp["h"] > 3 or len(fp["blocked"]) != fp["w"] * fp["h"]:
                continue
            pool.append(model)
        pools[terrain] = sorted(pool)
    return pools


OBSTACLE_POOLS = _obstacle_pools()


# ---------------------------------------------------------------- the generator

class Generator:
    """settings: one dict per player: human (bool), faction (None = any, or a FACTIONS name),
    hero (None = random, or a dict with portrait, hero_class, sex, name, biography)."""

    def __init__(self, seed, size=76, players=2, settings=None):
        self.seed, self.size, self.players = seed, size, players
        self.settings = settings or [{"human": True, "faction": None, "hero": None}
                                     for _ in range(players)]
        self.rng = random.Random(seed)
        self.rows = h4tiles.row_ranges(size)
        self.cells = [(r, c) for r in range(size) for c in range(*self.rows[r])]
        self.zone = {}
        self.state = {cell: FREE for cell in self.cells}
        self.objects = []       # MapObject
        self.road = {}          # cell -> road type
        self.guards = set()     # monster cells on paths (passable for path checks)
        self.log = []

    # -- geometry

    def inside(self, r, c):
        if not 0 <= r < self.size:
            return False
        s, e = self.rows[r]
        return s <= c < e

    def screen(self, r, c):
        """Cell -> screen-space point in [-0.5, 0.5]^2 (x right, y down)."""
        return (c - r) / self.size, (c + r - self.size + 1) / self.size

    def from_screen(self, x, y):
        cr = x * self.size
        cs = y * self.size + self.size - 1
        r, c = round((cs - cr) / 2), round((cs + cr) / 2)
        return r, c

    # -- 1. zones

    def make_zones(self):
        rng, P = self.rng, self.players
        n_neutral = {76: max(3, P), 152: 2 * P + 1}.get(self.size, 3 * P + 1)
        centres, kinds = [], []
        a0 = rng.uniform(0, 2 * math.pi)
        for i in range(P):
            a = a0 + 2 * math.pi * i / P
            centres.append((0.34 * math.cos(a), 0.34 * math.sin(a)))
            kinds.append("start")
        for _ in range(n_neutral):
            best, best_d = None, -1
            for _ in range(300):
                p = (rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4))
                d = min(math.dist(p, q) for q in centres)
                if d > best_d:
                    best, best_d = p, d
            centres.append(best)
            kinds.append("neutral")
        self.centres, self.kinds = centres, kinds

        amp, f = 0.035, rng.uniform(9, 14)
        ph = [rng.uniform(0, 2 * math.pi) for _ in range(4)]

        def warp(x, y):
            return (x + amp * math.sin(f * y + ph[0]) + amp * 0.5 * math.sin(2.3 * f * (x + y) + ph[1]),
                    y + amp * math.sin(f * x + ph[2]) + amp * 0.5 * math.sin(2.1 * f * (x - y) + ph[3]))

        for cell in self.cells:
            p = warp(*self.screen(*cell))
            self.zone[cell] = min(range(len(centres)), key=lambda z: math.dist(p, centres[z]))
        self._fix_fragments()

        # terrains: start zones distinct where possible, neutral random
        terrains = []
        start_pool = START_TERRAINS[:]
        rng.shuffle(start_pool)
        for z, k in enumerate(kinds):
            if k == "start":
                terrains.append(start_pool.pop())
            else:
                terrains.append(rng.choice(LAND))
        self.terrain = terrains

        # neutral tiers: 1 = touches a start zone, 2 = further in
        adj = self.zone_pairs()
        self.tier = []
        for z, k in enumerate(kinds):
            if k == "start":
                self.tier.append(0)
            else:
                near = any(kinds[o] == "start" for (a, b) in adj for o in (a, b)
                           if z in (a, b) and o != z)
                self.tier.append(1 if near else 2)

    def _fix_fragments(self):
        """Keep each zone's largest connected piece; give the other pieces to a neighbour."""
        for _ in range(4):
            changed = False
            seen = set()
            pieces = {}
            for cell in self.cells:
                if cell in seen:
                    continue
                z = self.zone[cell]
                stack, piece = [cell], []
                seen.add(cell)
                while stack:
                    r, c = stack.pop()
                    piece.append((r, c))
                    for dr, dc in DIR4:
                        n = (r + dr, c + dc)
                        if n not in seen and n in self.zone and self.zone[n] == z:
                            seen.add(n)
                            stack.append(n)
                pieces.setdefault(z, []).append(piece)
            for z, ps in pieces.items():
                ps.sort(key=len, reverse=True)
                for piece in ps[1:]:
                    votes = {}
                    for r, c in piece:
                        for dr, dc in DIR4:
                            n = (r + dr, c + dc)
                            if n in self.zone and self.zone[n] != z:
                                votes[self.zone[n]] = votes.get(self.zone[n], 0) + 1
                    if votes:
                        nz = max(votes, key=votes.get)
                        for cell in piece:
                            self.zone[cell] = nz
                        changed = True
            if not changed:
                break

    def zone_pairs(self):
        """{(za, zb): [(cell_a, cell_b), ...]} for 4-neighbour cells in different zones."""
        pairs = {}
        for r, c in self.cells:
            za = self.zone[(r, c)]
            for dr, dc in ((1, 0), (0, 1)):
                n = (r + dr, c + dc)
                zb = self.zone.get(n)
                if zb is not None and zb != za:
                    key = (min(za, zb), max(za, zb))
                    pairs.setdefault(key, []).append(((r, c), n) if za < zb else (n, (r, c)))
        return {k: v for k, v in pairs.items() if len(v) >= 4}

    # -- 2. walls and passages

    def make_walls(self):
        for r, c in self.cells:
            z = self.zone[(r, c)]
            for dr, dc in DIR8:
                n = (r + dr, c + dc)
                if n not in self.zone or self.zone[n] != z:
                    self.state[(r, c)] = WALL
                    break
        # A narrow neck can split a zone's open area; keep the largest piece, wall the rest.
        seen = set()
        best = {}
        for cell in self.cells:
            if cell in seen or self.state[cell] != FREE:
                continue
            z = self.zone[cell]
            piece, stack = [], [cell]
            seen.add(cell)
            while stack:
                r, c = stack.pop()
                piece.append((r, c))
                for dr, dc in DIR8:
                    n = (r + dr, c + dc)
                    if n not in seen and self.zone.get(n) == z and self.state[n] == FREE:
                        seen.add(n)
                        stack.append(n)
            if len(piece) > len(best.get(z, [])):
                for old in best.get(z, []):
                    self.state[old] = WALL
                best[z] = piece
            else:
                for old in piece:
                    self.state[old] = WALL

    def make_links(self):
        rng = self.rng
        pairs = self.zone_pairs()
        n = len(self.centres)

        def weight(key):
            a, b = key
            w = math.dist(self.centres[a], self.centres[b])
            if self.kinds[a] == "start" and self.kinds[b] == "start":
                w += 10          # avoid direct start-to-start links
            return w

        # Kruskal spanning tree
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        self.links = []
        for key in sorted(pairs, key=weight):
            a, b = find(key[0]), find(key[1])
            if a != b:
                p = self.make_passage(key, pairs[key])
                if p:
                    parent[a] = b
                    self.links.append(p)
        for key in pairs:
            a, b = key
            if any(link["zones"] == key for link in self.links):
                continue
            if self.kinds[a] == "start" and self.kinds[b] == "start":
                continue
            if rng.random() < 0.35:
                p = self.make_passage(key, pairs[key])
                if p:
                    self.links.append(p)

    def make_passage(self, key, cell_pairs):
        a, b = key
        mid = ((self.centres[a][0] + self.centres[b][0]) / 2, (self.centres[a][1] + self.centres[b][1]) / 2)

        def clean(cell, radius):
            """No third zone (or map edge) around the cell."""
            r, c = cell
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    z = self.zone.get((r + dr, c + dc), -1)
                    if z not in key:
                        return False
            return True

        for radius in (2, 1):
            candidates = [(ca, cb) for ca, cb in cell_pairs if clean(ca, radius) and clean(cb, radius)]
            if candidates:
                break
        else:
            return None
        candidates.sort(key=lambda p: math.dist(self.screen(*p[0]), mid) + self.rng.uniform(0, 0.03))
        for ca, cb in candidates[:12]:
            d = (ca[0] - cb[0], ca[1] - cb[1])
            corridor = {ca: a, cb: b}
            ends = {}
            for start, step, z in ((ca, d, a), (cb, (-d[0], -d[1]), b)):
                cur = start
                for _ in range(6):
                    if self.state[cur] != WALL:
                        break
                    nxt = (cur[0] + step[0], cur[1] + step[1])
                    if nxt not in self.zone or self.zone[nxt] != z:
                        break
                    corridor[nxt] = z
                    cur = nxt
                ends[z] = cur
            if all(self.state[e] == FREE for e in ends.values()):
                break
        else:
            return None
        for cell in corridor:
            self.state[cell] = RES
        # guard sits on the border cell of the more valuable zone
        guard_cell = cb if self.tier[b] >= self.tier[a] else ca
        return {"zones": key, "ends": ends, "corridor": list(corridor), "guard": guard_cell}

    # -- 3. content

    def try_place(self, model, r0, c0, z, need_entry=True):
        fp = footprint(model)
        w, h = fp["w"], fp["h"]
        blocked = set(fp["blocked"])
        cells = []
        for fy in range(h):
            for fx in range(w):
                cell = (r0 + fx, c0 + fy)
                if cell not in self.zone or self.zone[cell] != z or self.state[cell] != FREE:
                    return None
                cells.append((cell, fy * w + fx in blocked))
        own = {cell for cell, _ in cells}
        for (r, c), _ in cells:      # keep a gap to other objects
            for dr, dc in DIR8:
                n = (r + dr, c + dc)
                if n not in own and self.state.get(n) in (BLOCK, OCC):
                    return None
        entries = []
        for ex, ey in fp["entry"]:
            cell = (r0 + ex, c0 + ey)
            if cell in own:
                continue
            if cell in self.zone and self.zone[cell] == z and self.state[cell] in (FREE, RES):
                entries.append(cell)
        if need_entry and fp["entry"] and not entries:
            return None
        self.undo = {cell: self.state[cell] for cell, _ in cells}
        self.undo.update({cell: self.state[cell] for cell in entries})
        for cell, b in cells:
            self.state[cell] = BLOCK if b else OCC
        for cell in entries:
            self.state[cell] = RES
        return entries

    def place_near(self, model, z, target, spread=0.0, make=None, validate=None):
        """Place model in zone z as close to target (r, c) as possible. Returns (obj, entries).

        validate(entries) can reject a spot (it is then undone and the next one tried)."""
        fp = footprint(model)
        cand = [cell for cell in self.zone_cells[z] if self.state[cell] == FREE]
        tr, tc = target
        cand.sort(key=lambda p: math.hypot(p[0] - tr, p[1] - tc) + self.rng.uniform(0, spread))
        for r, c in cand[:400]:
            r0, c0 = r - fp["w"] // 2, c - fp["h"] // 2
            entries = self.try_place(model, r0, c0, z)
            if entries is not None and validate and not validate(entries):
                self.state.update(self.undo)
                entries = None
            if entries is not None:
                obj = make(r0, c0) if make else make_object(model, r0, c0)
                self.objects.append(obj)
                return obj, entries
        self.log.append(f"zone {z}: no room for {model}")
        return None, None

    def random_spot(self, z, min_dist_from=None, dist=0):
        cells = [c for c in self.zone_cells[z] if self.state[c] == FREE]
        self.rng.shuffle(cells)
        for cell in cells:
            if min_dist_from is None or math.dist(cell, min_dist_from) >= dist:
                return cell
        return cells[0] if cells else None

    def zone_centre_cell(self, z):
        cells = [c for c in self.zone_cells[z] if self.state[c] == FREE]
        cx, cy = self.centres[z]
        target = self.from_screen(cx, cy)
        # the free cell furthest from walls near the centre
        return min(cells, key=lambda p: math.dist(p, target))

    def fill_zones(self):
        rng = self.rng
        self.zone_cells = {}
        for cell in self.cells:
            self.zone_cells.setdefault(self.zone[cell], []).append(cell)
        self.hubs = {}
        self.items = {z: [] for z in range(len(self.centres))}   # (entries, guard level)
        start_index = 0
        for z, kind in enumerate(self.kinds):
            centre = self.zone_centre_cell(z)
            if kind == "start":
                owner = start_index
                start_index += 1
                variant = rng.choice(["left", "right"])
                faction = self.settings[owner].get("faction")
                if faction:
                    model = FACTION_TOWN[faction][0 if variant == "left" else 1]
                    build = lambda r, c: make_fixed_town(faction, variant, owner, r, c)  # noqa: E731
                else:
                    model = TEMPLATES["town_" + variant]["model"]
                    build = lambda r, c: make_town(variant, owner, r, c)  # noqa: E731
                ends = [e for link in self.links for zz, e in link["ends"].items() if zz == z]
                obj, entries = self.place_near(model, z, centre, 0, build,
                                               lambda entries: self.reaches(z, entries[0], ends))
                if obj is None:
                    raise RuntimeError(f"no room for the town in zone {z}")
                gate = entries[0]
                d = (1, 0) if variant == "left" else (0, 1)
                front = (gate[0] + d[0], gate[1] + d[1])
                spots = [front] + sorted(((front[0] + dr, front[1] + dc) for dr in range(-3, 4)
                                          for dc in range(-3, 4)), key=lambda p: math.dist(p, front))
                hero = next((p for p in spots if p != gate and self.state.get(p) == FREE
                             and self.zone.get(p) == z), None)
                if hero is None:
                    raise RuntimeError(f"no room for the hero in zone {z}")
                self.state[hero] = BLOCK
                hero_args = dict(self.settings[owner].get("hero") or {})
                hero_args.setdefault("army", heroinfo.army_stacks(faction))
                self.objects.append(make_hero(owner, *hero, **hero_args))
                self.hubs[z] = gate
                self.town_gates = getattr(self, "town_gates", []) + [gate]
            else:
                self.state[centre] = RES
                self.hubs[z] = centre

    def reaches(self, z, start, goals):
        """Can a hero walk from start to every goal inside zone z?"""
        goals = set(goals)
        seen, stack = {start}, [start]
        while stack and not goals <= seen:
            r, c = stack.pop()
            for dr, dc in DIR8:
                n = (r + dr, c + dc)
                if n not in seen and self.zone.get(n) == z and self.state[n] in WALKABLE:
                    seen.add(n)
                    stack.append(n)
        return goals <= seen

    def fill_contents(self):
        for z, kind in enumerate(self.kinds):
            if kind == "start":
                self.fill_start(z, self.hubs[z])
            else:
                self.fill_neutral(z, self.hubs[z], self.tier[z])
            # bigger zones (medium and larger maps) get extra rounds of smaller content
            extra = round(len(self.zone_cells[z]) / 700) - 1
            for _ in range(max(0, extra)):
                self.fill_extra(z, self.hubs[z], self.tier[z])

    def fill_extra(self, z, hub, tier):
        rng = self.rng
        far = lambda: self.random_spot(z) or hub  # noqa: E731
        level = min(4, tier + 1)
        self.add(z, rng.choice((ARTIFACT["minor"], ARTIFACT["item"])) if tier < 2 else ARTIFACT["treasure"],
                 far(), 5, guard=level)
        self.add(z, DWELLING[min(4, tier + 1)], far(), 5, guard=level if tier else 0)
        for _ in range(2):
            self.add(z, CHEST, far(), 5)
            self.add(z, RESOURCE, far(), 5)
        self.add(z, rng.choice(FOUNTAINS + GEMS), far(), 5)
        if rng.random() < 0.5:
            self.add(z, rng.choice(BANKS), far(), 5)

    def add(self, z, model, near, spread, guard=0):
        obj, entries = self.place_near(model, z, near, spread)
        if obj is not None:
            self.items[z].append((entries, guard, obj))

    def fill_start(self, z, gate):
        rng = self.rng
        self.add(z, rng.choice(SAWMILL), gate, 14)
        self.add(z, rng.choice(ORE_PIT), gate, 14)
        for _ in range(3):
            self.add(z, RESOURCE, gate, 30)
        for _ in range(2):
            self.add(z, CHEST, gate, 30)
        self.add(z, CAMPFIRE, gate, 30)
        self.add(z, DWELLING[1], gate, 20)
        self.add(z, rng.choice(FOUNTAINS), gate, 30)
        self.add(z, ARTIFACT["minor"], gate, 40, guard=1)
        if self.size >= 152:
            self.add(z, rng.choice(RARE_MINES)[rng.randrange(2)], gate, 30, guard=1)
            self.add(z, DWELLING[2], gate, 30)
            for _ in range(3):
                self.add(z, RESOURCE, gate, 60)

    def fill_neutral(self, z, hub, tier):
        rng = self.rng
        far = lambda: self.random_spot(z) or hub  # noqa: E731
        if tier == 1:
            self.add(z, rng.choice(RARE_MINES)[rng.randrange(2)], far(), 5, guard=2)
            if rng.random() < 0.5:
                self.add(z, rng.choice((SAWMILL, ORE_PIT))[rng.randrange(2)], far(), 5, guard=1)
            self.add(z, DWELLING[2], far(), 5, guard=2)
            for _ in range(2):
                self.add(z, ARTIFACT["minor"], far(), 5, guard=2)
            self.add(z, "shrines.Random 1", far(), 5)
            self.add(z, rng.choice(["Scholars.Random Scholar", "moral-luck boosters.Random Temple"]), far(), 5)
            self.add(z, rng.choice(GEMS), far(), 5)
        else:
            self.add(z, rng.choice(GOLD_MINE), far(), 5, guard=3)
            self.add(z, rng.choice(RARE_MINES)[rng.randrange(2)], far(), 5, guard=3)
            self.add(z, DWELLING[rng.choice((3, 4))], far(), 5, guard=3)
            self.add(z, ARTIFACT["major"], far(), 5, guard=4)
            self.add(z, ARTIFACT["treasure"], far(), 5, guard=3)
            self.add(z, rng.choice(["shrines.Random 2", "shrines.Random 3"]), far(), 5)
            self.add(z, rng.choice(SCHOOLS), far(), 5)
            self.add(z, rng.choice(BANKS), far(), 5)
        for _ in range(2 + tier):
            self.add(z, CHEST, far(), 5)
        for _ in range(3 + tier):
            self.add(z, RESOURCE, far(), 5)
        self.add(z, rng.choice(FOUNTAINS), far(), 5)

    # -- 4. paths

    def astar(self, z, start, goals, cost_bias):
        goals = set(goals)
        if start in goals:
            return [start]
        openq = [(0, 0, start)]
        came = {start: None}
        g = {start: 0}
        gl = list(goals)
        while openq:
            _, gc, cur = heapq.heappop(openq)
            if cur in goals:
                path = []
                while cur is not None:
                    path.append(cur)
                    cur = came[cur]
                return path[::-1]
            if gc > g[cur]:
                continue
            for dr, dc in DIR8:
                n = (cur[0] + dr, cur[1] + dc)
                if self.zone.get(n) != z or self.state[n] not in WALKABLE:
                    continue
                step = 1.41 if dr and dc else 1.0
                step *= cost_bias.get(n, 1.0)
                ng = gc + step
                if ng < g.get(n, 1e9):
                    g[n] = ng
                    came[n] = cur
                    h = min(max(abs(n[0] - q[0]), abs(n[1] - q[1])) for q in gl[:8])
                    heapq.heappush(openq, (ng + h * 0.5, ng, n))
        return None

    def make_main_paths(self):
        bias = self.bias = {}
        self.main_paths = []
        for link in self.links:
            for z, end in link["ends"].items():
                path = self.astar(z, self.hubs[z], [end], bias)
                if path is None:
                    self.log.append(f"zone {z}: passage {end} unreachable")
                    continue
                for cell in path:
                    self.state[cell] = RES
                    bias[cell] = 0.4
                self.main_paths.append((z, path))

    def make_paths(self):
        bias = self.bias
        uses = {}
        for z, items in self.items.items():
            for entries, guard, obj in items:
                path = self.astar(z, self.hubs[z], entries, bias)
                if path is None:
                    self.log.append(f"zone {z}: dropped unreachable {obj.model}")
                    self.objects.remove(obj)
                    continue
                for cell in path:
                    self.state[cell] = RES
                    bias.setdefault(cell, 0.7)
                    uses[cell] = uses.get(cell, 0) + 1
                if guard:
                    self.pending_guards.append((path[-1], guard, path))
        # guards on object entrances, unless that cell is on another path
        main = {c for _, p in self.main_paths for c in p}
        for cell, level, path in self.pending_guards:
            if uses.get(cell, 0) > 1 or cell in main or cell in self.guards:
                # step back along the path to a cell only this path uses
                cell = next((p for p in reversed(path[1:]) if uses.get(p, 0) == 1 and p not in main), None)
                if cell is None:
                    continue
            self.objects.append(make_object(MONSTER[level], *cell))
            self.guards.add(cell)

    def place_link_guards(self):
        for link in self.links:
            a, b = link["zones"]
            if self.kinds[a] == "start" and self.kinds[b] == "start":
                level = 4
            else:
                level = min(4, 1 + max(self.tier[a], self.tier[b]))
            cell = link["guard"]
            self.objects.append(make_object(MONSTER[level], *cell))
            self.guards.add(cell)

    # -- 5. obstacles

    def place_obstacle(self, cell, allowed, pool, big=True):
        """Cover cell with a fully blocking decoration whose footprint lies in `allowed` states."""
        models = pool if big else [m for m in pool if footprint(m)["w"] * footprint(m)["h"] == 1]
        for _ in range(6 if big else 12):
            if not models:
                return False
            model = self.rng.choice(models)
            fp = footprint(model)
            fx, fy = self.rng.randrange(fp["w"]), self.rng.randrange(fp["h"])
            r0, c0 = cell[0] - fx, cell[1] - fy
            cells = [(r0 + x, c0 + y) for y in range(fp["h"]) for x in range(fp["w"])]
            z = self.zone[cell]
            if all(n in self.zone and self.zone[n] == z and self.state[n] in allowed for n in cells):
                for n in cells:
                    self.state[n] = BLOCK
                self.objects.append(make_object(model, r0, c0))
                return True
        return False

    def fill_walls(self):
        walls = [c for c in self.cells if self.state[c] == WALL]
        self.rng.shuffle(walls)
        for cell in walls:
            if self.state[cell] != WALL:
                continue
            pool = OBSTACLE_POOLS[self.terrain[self.zone[cell]]]
            if not self.place_obstacle(cell, (WALL,), pool, big=True):
                if not self.place_obstacle(cell, (WALL,), pool, big=False):
                    self.place_obstacle(cell, (WALL,), OBSTACLE_POOLS[GRASS], big=False)
        left = sum(1 for c in self.cells if self.state[c] == WALL)
        if left:
            self.log.append(f"{left} wall cells left open")

    def fill_interior(self, density=0.14):
        for z, cells in self.zone_cells.items():
            free = [c for c in cells if self.state[c] == FREE]
            target = int(len(free) * density)
            pool = OBSTACLE_POOLS[self.terrain[z]]
            placed_cells = 0
            self.rng.shuffle(free)
            seeds = free[:]
            recent = []
            tries = 0
            while placed_cells < target and tries < target * 6 and seeds:
                tries += 1
                if recent and self.rng.random() < 0.6:
                    r, c = self.rng.choice(recent)
                    dr, dc = self.rng.choice(DIR8)
                    cell = (r + dr, c + dc)
                else:
                    cell = seeds.pop()
                if self.state.get(cell) != FREE or self.zone.get(cell) != z:
                    continue
                if self.place_obstacle(cell, (FREE,), pool, big=True):
                    placed_cells += 1
                    recent = (recent + [cell])[-6:]

    # -- 6. tiles and the map file

    def build_grid(self):
        g = h4tiles.Grid(self.size, 1)
        for (r, c) in self.cells:
            t = g.tile(0, r, c)
            t.terrain = self.terrain[self.zone[(r, c)]]
            t.subtype = 0
        for z, path in self.main_paths:
            road = ROAD_COBBLE if self.kinds[z] == "start" else ROAD_DIRT
            for cell in path:
                self.road[cell] = max(self.road.get(cell, 0), road)
        for link in self.links:
            for cell in link["corridor"]:
                self.road.setdefault(cell, ROAD_DIRT)
        for (r, c), road in self.road.items():
            g.tile(0, r, c).road = road
        trng = random.Random(self.seed + 1)
        transitions.compute(g, trng)
        transitions.compute_roads(g, trng)
        return g

    def check(self):
        """Every start zone reaches every other one (through guards), and is sealed without them."""
        def reach(start, through_guards):
            seen, stack = {start}, [start]
            while stack:
                r, c = stack.pop()
                for dr, dc in DIR8:
                    n = (r + dr, c + dc)
                    if n in seen or n not in self.state:
                        continue
                    ok = self.state[n] in WALKABLE and (through_guards or n not in self.guards)
                    if ok:
                        seen.add(n)
                        stack.append(n)
            return seen
        gates = self.town_gates
        full = reach(gates[0], True)
        problems = [f"town {i} not reachable" for i, g in enumerate(gates) if g not in full]
        for i, g in enumerate(gates):
            sealed = reach(g, False)
            z = self.zone[g]
            leaks = {self.zone[c] for c in sealed if self.zone[c] != z}
            if leaks:
                problems.append(f"start zone {z} leaks into zones {sorted(leaks)}")
        return problems

    def generate(self):
        self.pending_guards = []
        self.make_zones()
        self.make_walls()
        self.make_links()
        self.fill_zones()
        self.make_main_paths()
        self.fill_contents()
        self.place_link_guards()
        self.make_paths()
        self.fill_walls()
        self.fill_interior()
        grid = self.build_grid()
        problems = self.check()
        rules = h4map.MapRules(
            version=29, expansion=2, size=self.size, levels=1,
            terrain_seed=self.rng.getrandbits(32),
            players=[h4map.PlayerSlot(
                color=i, playable=int(bool(st.get("human", True))), unknown=0,
                town_mask=(1 << FACTIONS.index(st["faction"])) if st.get("faction") else 0x3F)
                for i, st in enumerate(self.settings)],
            name=naming.map_title(self.seed), difficulty=1,
            description=(f"Random map, seed {self.seed}: {self.players} players, "
                         f"{len(self.centres)} zones. Made by homm4-random-map-generator."),
            teams=[1 << i for i in range(self.players)],
        )
        return h4full.Map(rules, self.objects, grid), problems


# ---------------------------------------------------------------- preview

def render_png(gen, grid, out, scale=6):
    from PIL import Image
    colors = {0: (40, 80, 170), 1: (70, 150, 50), 2: (150, 130, 80), 3: (60, 90, 60), 4: (90, 40, 30),
              5: (235, 240, 250), 6: (220, 200, 120), 7: (130, 100, 60), 8: (90, 70, 80)}
    size = gen.size
    img = Image.new("RGB", (size + 2, size + 1), (0, 0, 0))
    for (r, c) in gen.cells:
        t = grid.tile(0, r, c)
        col = colors.get(t.terrain, (200, 0, 200))
        st = gen.state[(r, c)]
        if t.road:
            col = (240, 230, 200)
        if st == BLOCK:
            col = tuple(v // 3 for v in col)
        if (r, c) in gen.guards:
            col = (255, 0, 0)
        x, y = c - r + size // 2, c + r - (size // 2 - 1)
        for dx in (0, 1):
            if 0 <= y <= size and 0 <= x + dx < size + 2:
                img.putpixel((x + dx, y), col)
    for o in gen.objects:
        if o.is_army or o.type in ("random_town", "mine", "random_creature_dwelling"):
            mark = (255, 255, 0) if o.is_army or o.type == "random_town" else (255, 140, 0)
            x, y = o.y - o.x + size // 2, o.y + o.x - (size // 2 - 1)
            if 0 <= y <= size and 0 <= x < size + 2:
                img.putpixel((x, y), mark)
    img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    img.save(out)


def default_maps_dir():
    for p in (r"D:\games\HoMM 4 Complete\Maps", r"C:\GOG Games\HoMM 4 Complete\Maps"):
        if os.path.isdir(p):
            return p
    return "."


def write_map(seed, size, settings, out_dir, png=None, log=print, map_id=None):
    """Generate and save a map; retries other layouts if a check fails. Returns the path.
    map_id names the file and title (default: the seed), e.g. to remake a map in place."""
    map_id = seed if map_id is None else map_id
    players = len(settings)
    for attempt in range(10):
        gen = Generator(seed + attempt * 7919 if attempt else seed, size, players, settings)
        try:
            m, problems = gen.generate()
        except RuntimeError as e:
            problems, m = [str(e)], None
        if not problems:
            break
        log(f"attempt {attempt + 1}: {'; '.join(problems)}; retrying")
    else:
        raise RuntimeError("could not generate a valid map")
    # a retry used another seed: name the map after the requested one, like its file
    m.rules.name = naming.map_title(map_id)
    m.rules.description = m.rules.description.replace(f"seed {gen.seed}:", f"seed {seed}:")
    path = naming.map_path(out_dir, map_id)
    h4full.save(m, path)
    h4full.load(path)            # read back: every object must parse
    if png:
        render_png(gen, m.grid, png)
    log(f"wrote {path}: {naming.map_title(map_id)}, {len(m.objects)} objects")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate a random Heroes IV map.")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--size", choices=sorted(SIZES), default="small")
    ap.add_argument("--players", type=int, default=2)
    ap.add_argument("--out", default=None, help="game Maps folder (default: auto-detect)")
    ap.add_argument("--png", default=None, help="also write a preview image")
    a = ap.parse_args(argv)
    seed = a.seed if a.seed is not None else random.randrange(1000, 100000)
    size = SIZES[a.size]
    if not 2 <= a.players <= 6:
        ap.error("players must be 2..6")
    settings = [{"human": True, "faction": None, "hero": None} for _ in range(a.players)]
    return write_map(seed, size, settings, a.out or default_maps_dir(), a.png)


if __name__ == "__main__":
    main()
