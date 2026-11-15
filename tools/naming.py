"""File and map names for generated maps.

Generated maps start with "_" so they sort first in the game's scenario list:
    file:  _random_map_<id>.h4c
    title: _Random_Map_<id>
<id> is the generator seed (or any short label, e.g. "test1").
"""
import os


def file_name(map_id):
    return f"_random_map_{map_id}.h4c"


def map_title(map_id):
    return f"_Random_Map_{map_id}"


def map_path(maps_dir, map_id):
    return os.path.join(maps_dir, file_name(map_id))
