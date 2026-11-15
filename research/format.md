# .h4c map format notes

Worked out from the 106 maps shipped with the game. All integers are little-endian.
Strings are `u16 length` followed by that many bytes (Latin-1, no terminator).

## Container

| Bytes | Meaning |
|---|---|
| 10 | `H4CAMPAIGN` |
| u32 | container version, always 22 |
| u8 | 0 |
| rest | gzip stream holding the map body |

Unpacking and repacking gives a byte-identical body.

## Body: header (decoded, all 106 maps parse)

| Field | Notes |
|---|---|
| u16 format | 27, 28 or 29 (29 = later expansions) |
| u16 expansion | only for format ≥ 28: 0 original game, 1 and 2 = the two expansions. The scenario list is grouped by this value (2 first, then 1, then 0), and sorted by name, ignoring case, inside each group. Generated maps use version 29 + expansion 2 so `_Random_Map_…` sorts to the very top. |
| u16 size | map width/height in tiles: 76 small, 152 medium, 228 large, 304 extra large |
| u8 levels | 1 = surface only, 2 = surface and underground |
| u32 unknown_b | varies per map |
| u8 player count | number of playable players |
| 5 bytes × count | color (0–7), human allowed, computer allowed, unknown, allowed-town bitmask (`0x3f` = any of the six) |
| string | map name |
| u8 | difficulty (seen 0–3) |
| string | description |

Key reference: the h4r project (https://github.com/demen1n/h4r, GPL-3.0) decompiled the game's map
loader; see its `decomp/h4c.md`. Our code is an independent Python implementation; facts below were
checked against the shipped maps.

## Body order

1. Header (above), then teams, loss/victory texts, scenes, notes (h4r `decomp/h4c.md`, "Заголовок карты").
2. Four global event lists (timed, triggerable, continuous, placed), each `u16 count` + events.
3. 12 obelisk reward lists.
4. Per-player data, allowed artifacts / skills / spells (bit sets: `u16 0`, `u16 bit count`, bits),
   AI importance tables.
5. Objects: `u32 count`; each object = `i32 x (row)`, `i32 y (column)`, `i32 level`, `u8 is_army`.
   Non-army objects: model name string (e.g. `mine.Gem R`), `u16 0`, three `(u16 id, string)` pairs
   (type, subtype, sub-subtype, e.g. `mine` / `gem_mine` / `right`), then a type-specific body.
   Decorations, resources, treasure and most simple objects have a body of just `u16 0`.
6. Tiles, all levels, row by row (decoded, `tools/h4tiles.py`).
7. Heights, one byte per tile corner (decoded).

## Tiles (decoded, byte-exact on all 105 shipped maps)

The map is a **diamond** inside the size × size square. Row `r` holds columns
`[size/2 − 1 − d, size/2 + 1 + d)` where `d = r` in the top half and `size − 1 − r` in the bottom half.
A small map (76) has 2,964 tiles per level. Corner rows: one more row, each spanning the tiles above and below, +1.

Tile:

| Field | Notes |
|---|---|
| u8 terrain | 0 water, 1 grass, 2 rough, 3 swamp, 4 volcanic, 5 snow, 6 sand, 7 dirt, 8 subterranean, 9–11 rivers (water, lava, ice), 12–17 magic lands, 18 combat |
| u8 subtype | 0–1 for terrains 0–8, else 0 |
| u8 road | 0 none, 1 gravel, 2 dirt, 3 cobblestone |
| u8 rock, u8 rock_transition | unused by the game |
| u32 visibility | always `0x80000` in the upper bits |
| u8 n + n × (u8 terrain, u8 subtype, u16 mask id, u8 mask set) | terrain transitions (blended edges), computed by the editor |
| u8 m + m × (u8 road, u16 mask id, u8 mask set) | road transitions |

Mask sets 0–19 map to transition sets: 0–4 water→land, 5–9 land→water, 10–14 road, 15–19 land→land.
**The generator must compute these transitions itself.** Plan: learn the editor's choice from the
shipped maps (neighbor pattern → masks).

Heights: one byte per corner, ground only (mountains are objects). Neighboring corners differ by at most 16.

## Header tail and rules sections (decoded, `tools/h4map.py`)

Correction to the table above: a player entry is `u8 color (0–5), u8 playable, u8 unknown, u8 0, u8 town mask`.
After the description:

| Field | Notes |
|---|---|
| u16 0, u8 n, n × u8 | teams as color bit masks; every player color is in exactly one team |
| u8 flag [+ string] | custom loss text |
| u8 flag [+ string] | custom victory text |
| u8 | v≥25, unknown flag |
| 2 × (u8 flag [+ u16 0, 3 strings]) | v≥24, cut scenes |
| string | v≥27, author notes |
| u8 | v≥29, unknown flag |
| 4 × u16 count + events | global events (timed, triggerable, continuous, placed); contain scripts |
| 12 × (u16 0, u8 has_rewards, u16, [rewards]) | obelisk rewards; default `00 00 00 ff ff` |
| per player: u8 color, u8 flag [+u16], u8 | per-player settings |
| u8 flag [+ bit set], u8 flag [+ u16 n, n bytes], u8 flag [+ u8 0, 5 bytes], u8 flag [+ u16 bits, bits] | allowed artifacts, unknown array, allowed skills, allowed spells |
| 2 × bit set (u16 0, u16 248, 31 bytes) | default: first all on, second all off |
| 3 × (u16 0, u16 n, n × (u16 id, u8 importance)) | AI importance tables, default empty |

`h4map.write_rules` re-encodes all 25 shipped maps without global events byte for byte, and its default
rules block is identical to the editor's output in the 8 v29 maps that use defaults.

## Objects, events, scripts (decoded, `tools/h4objects.py`)

Script trees, all event kinds, armies, heroes and every object type's body are readable.
`tools/h4full.py check <maps>` decodes and re-encodes **all 105 shipped maps byte for byte**.

`data/object_catalog.json` lists every object model used in shipped maps (2,177 models) with its
category, usage count, most common body bytes and the terrain it usually stands on.
Typical bodies:

| Type | Body |
|---|---|
| decorations, resources (`material_pile`), treasure, `random_artifact`, ... | `00 00` |
| `mine` (90%) | version 2, owner 6 (nobody), 4 empty built-in events, empty lists, no garrison |
| `random_monster` (80%) | version 4, no flags, 3 empty built-in events, empty lists, kind `none`, default strength (-1) |
| `random_town` | version 7, kind `none`, town data v8 (owner, name, garrison, buildings, events) — built per map |

An empty built-in event is `00 00` + script (`02 00` version, action `seq` with 0 children) + empty
message + 7 × i32 0 + 2 bytes players/flags.

## Game archives and object footprints (`tools/h4r.py`, `tools/footprints.py`)

`.h4r` archive: `H4R\x05`, u32 directory offset, gzip blobs; directory = u32 count + entries
(u32 offset, compressed size, size, time; name, source path, alias strings; u32 type). Load order:
x2_override, updates, text, music, movies, x2, storm, heroes4 (first hit wins).

`adv_object.<model>.h4d` starts with the footprint: u16 version, u8 fps, u16 edge-trigger flag,
u16 width, u16 height, blocked bits (w×h), trigger edge bits, edge-blocked bits and corner heights
(v6), object type, u8 flat mode. `data/footprints.json` holds all 2,798 models (every model in the
catalog has one).

**Placement on the map (verified on 40 maps):** the object's stored (x, y) is footprint cell (0, 0);
footprint x adds to the row, y to the column; cell index = y·width + x. With this, only 3.9% of
interactive-object cells touch another object (other readings: 10–24%).
Example: a random town is 6×6, all blocked, entrance = 2 cells on one edge; a gold mine is 1×2.

## Terrain transitions (`tools/transitions.py`)

- Mask codes: `data/transition_codes.json` (93 codes, same order in all 15 sets).
- Neighbour directions: n (−1,−1), ne (−1,0), e (−1,+1), se (0,+1), s (+1,+1), sw (+1,0), w (+1,−1), nw (0,−1).
- The editor's own rule is not a fixed priority: half of all borders are blended from both sides.
  Its code matches `corner_code` 61% of the time if single-edge digits (1/2) are kept only when the
  corner's diagonal neighbour also has the terrain.
- Mask set families used by the editor: land over water → 5–9, water over land → 0–4,
  land over land → mostly 15–19 (also 0–9), roads → 10–14; one of five picked at random.
- Our generator uses a fixed priority (water lowest) and splits each code into existing masks;
  every one of the 256 neighbour patterns splits into at most 4 masks.

## Road transitions (`transitions.compute_roads`)

Checked against all shipped maps: matches 99.4% of tiles next to roads (the rest look like tiles the
editor never recomputed).

- A road tile lists road 0 ("no road") drawn over its edges whose neighbours have no road. Corner
  digits as for terrain (3 both edges, 1 / 2 one edge), but 0 when the corner's diagonal neighbour
  has road.
- A tile without road lists the road type drawn over each corner where both edge neighbours have
  road (digit 3 only).
- Cells outside the map count as road. Mask sets 10–14, one picked at random.

## Object type ids and templates (`tools/build_data.py`)

The numeric type ids in an object's kind changed between editor versions (e.g. `random_town` is 69,
71 or 72; the game's own data files still say 68). The game looks objects up by name, so the
generator writes the newest editor's ids (`data/type_ids.json`). Bodies for towns and the starting
hero are copied from shipped maps (`data/templates.json`, owner byte patched).
`data/footprints.json` also lists `entry` cells: where a hero stands to visit the object.

## Heroes in map armies (`generator.make_hero`)

A placed army is `u16 version (9)`, `u8 owner`, `u16 0`, then 7 slots: `ff` empty, `00` creature
stack (`u16 1`, `i16 creature`, `i16 count`, artifact list `u16 0`), `01` hero. The creature number is
the 0-based position in the exe's creature list (`tools/heroinfo.py`).

Hero record v10: `i16 portrait`, `u8 class`, `u8 sex`, `u8`, 4 bytes, string biography, string name,
skills, spells, artifacts, events. Checked against the named heroes of the shipped maps:
- portrait = index in heroes4.exe's portrait table of `(char *keyword, u32 faction)` pairs, 311
  entries starting with `aidan` (`data/portraits.json`, `build_data.exe_portraits`); -1 = random.
  It is NOT the row of table.heroes (that gave the wrong face in game).
- class = the exe's class table order: knight 0, priest 1, lord 2, mage 3, death knight 4,
  necromancer 5, thief 6, sorcerer 7, archer 8, druid 9, barbarian 10; 255 = random.
- sex: 0 female, 1 male.

## Still to do

- (done) Generated maps load and play in the game.
- Water and islands (boats, shipyards), underground level, more zone templates.
