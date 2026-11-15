"""Study how the editor chose terrain transitions in the shipped maps (research script)."""
import sys, os, glob, json, collections
sys.path.insert(0, os.path.dirname(__file__))
import h4full, h4tiles

CODES = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'data', 'transition_codes.json')))['land 1']
# screen direction -> (drow, dcol)
DIRS = {'n': (-1, -1), 'ne': (-1, 0), 'e': (-1, 1), 'se': (0, 1), 's': (1, 1), 'sw': (1, 0), 'w': (1, -1), 'nw': (0, -1)}


def corner_code(has):
    def digit(before, after, diag):
        if before and after: return 3
        if before: return 1
        if after: return 2
        return 4 if diag else 0
    return (digit(has['ne'], has['se'], has['e']) * 1000 + digit(has['se'], has['sw'], has['s']) * 100
            + digit(has['sw'], has['nw'], has['w']) * 10 + digit(has['nw'], has['ne'], has['n']))


def maps(limit=None):
    ps = [p for p in sorted(glob.glob(r'D:\games\HoMM 4 Complete\maps\**\*.h4c', recursive=True))
          if not os.path.basename(p).startswith('_')]
    for p in ps[:limit]:
        yield os.path.basename(p), h4full.load(p)
