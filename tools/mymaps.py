"""Maps this program made: list them, read back the settings they were made with, delete them.

Everything needed to edit a map again is in the map itself: size, players (human or computer,
town faction from the allowed-town mask), and each player's starting hero (portrait number in the
hero record), so no extra files are kept next to the maps.
"""
import glob
import os
import re
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generator  # noqa: E402
import h4full  # noqa: E402

FILE_RE = re.compile(r"^_random_map_(.+)\.h4c$", re.I)
SIZE_NAMES = {76: "Small", 152: "Medium", 228: "Large", 304: "Extra large"}


def list_maps(maps_dir):
    """[{id, path, mtime}] of generated maps, newest first."""
    out = []
    for p in glob.glob(os.path.join(maps_dir, "*.h4c")):
        m = FILE_RE.match(os.path.basename(p))
        if m:
            out.append({"id": m.group(1), "path": p, "mtime": os.path.getmtime(p)})
    out.sort(key=lambda e: -e["mtime"])
    return out


def when(mtime):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))


def read_settings(path):
    """{seed, size, players: [{human, faction, hero_keyword}]} of a generated map."""
    m = h4full.load(path)
    seed = re.search(r"seed (\d+):", m.rules.description or "")
    players = []
    for slot in m.rules.players:
        mask = slot.town_mask & 0x3F
        faction = None
        if mask and mask & (mask - 1) == 0:
            faction = generator.FACTIONS[mask.bit_length() - 1]
        players.append({"human": bool(slot.playable), "faction": faction, "hero_keyword": None})
    for o in m.objects:
        raw = getattr(o, "raw", None) or getattr(o, "body", b"")
        if not o.is_army or len(raw) < 10 or raw[5] != 1:
            continue
        owner = raw[2]
        portrait = struct.unpack_from("<h", raw, 8)[0]
        if owner < len(players) and 0 <= portrait < len(generator.PORTRAITS):
            players[owner]["hero_keyword"] = generator.PORTRAITS[portrait][0]
    return {"seed": int(seed.group(1)) if seed else None, "size": m.rules.size, "players": players}


def delete(path):
    os.remove(path)
