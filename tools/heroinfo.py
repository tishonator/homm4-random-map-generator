"""What a starting hero brings: class, skills, statistics and starting army.

Sources (all from the game itself):
- Base classes (heroes4.exe class table): faction and starting skills, as skill numbers.
- Skill numbers: the 9 primary skills first, then their 27 secondary skills group by group.
  Names, effects and icons come from table.skills and layers.icons.skills.<primary>.52.
- Creature numbers: the exe's creature keyword list, counted from 0 (matches the creature
  stacks of player armies in the shipped maps). Stats come from table.creatures.
- Hero statistics that the skill texts state exactly: Basic Melee sets Melee Attack to 15,
  Basic Combat sets Melee and Ranged Defense to 15, each magic secondary skill (Healing,
  Enchantment, Occultism, Conjuration, Herbalism) gives 10 spell points. Base values without a
  skill are computed by the game's code and are not in its data files (see BASE_STATS).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import h4data  # noqa: E402

PRIMARY = ["tactics", "toughness", "scouting", "nobility", "life", "order", "death", "chaos", "nature"]
# icon sheet per primary skill keyword
SHEET = {"tactics": "tactics", "toughness": "combat", "scouting": "scouting", "nobility": "nobility",
         "life": "life", "order": "order", "death": "death", "chaos": "chaos", "nature": "nature"}
SECONDARY = {
    "tactics": ["offense", "defense", "leadership"],
    "toughness": ["combat", "archery", "resistance"],
    "scouting": ["pathfinding", "seamanship", "stealth"],
    "nobility": ["estates", "mining", "diplomacy"],
    "life": ["healing", "spirit", "resurrection"],
    "order": ["enchantment", "mind", "charm"],
    "death": ["black", "demonology", "necromancy"],
    "chaos": ["conjuration", "pyromancy", "sorcery"],
    "nature": ["herbalism", "meditation", "summoning"],
}
SKILLS = PRIMARY + [s for p in PRIMARY for s in SECONDARY[p]]          # skill number -> keyword
GROUP = {s: p for p in PRIMARY for s in [p] + SECONDARY[p]}

# heroes4.exe class table: (faction, starting skill numbers)
CLASSES = {
    "knight": ("life", [0, 10]), "priest": ("life", [4, 21]),
    "lord": ("order", [3, 18]), "mage": ("order", [5, 24]),
    "death_knight": ("death", [0, 9]), "necromancer": ("death", [6, 27]),
    "thief": ("chaos", [2, 17]), "sorcerer": ("chaos", [7, 30]),
    "archer": ("nature", [1, 13]), "druid": ("nature", [8, 33]),
    "barbarian": ("might", [1, 12, 14]),
}
CLASS_TITLES = {"death_knight": "Death Knight"}

CREATURES = [
    "air elemental", "archangel", "ballista", "bandit", "behemoth", "beholder", "berserker",
    "black dragon", "bone dragon", "centaur", "cerberus", "champion", "crossbowman", "crusader",
    "cyclops", "venom spawn", "archdevil", "dragon golem", "dwarf", "earth elemental", "efreet", "elf",
    "faerie dragon", "fire elemental", "gargoyle", "genie", "ghost", "gold golem", "griffin",
    "halfling", "harpy", "hydra", "ice demon", "imp", "leprechaun", "mage", "mantis", "medusa",
    "mermaid", "minotaur", "monk", "mummy", "naga", "nightmare", "nomad", "ogre mage", "orc",
    "peasant", "phoenix", "pikeman", "pirate", "satyr", "sea monster", "skeleton", "squire",
    "sprite", "thunderbird", "titan", "troglodyte", "troll", "unicorn", "vampire", "waspwort",
    "water elemental", "white tiger", "wolf", "zombie", "goblin knight", "evil sorceress",
    "gargantuan", "dark champion", "catapult", "frenzied gnasher", "mega dragon",
]
CREATURE_ID = {c: i for i, c in enumerate(CREATURES)}

# Starting army (a generator rule, like Heroes III): the faction's two level-1 creatures,
# about three quarters and two fifths of their weekly growth (table.creatures).
START_ARMY = {
    "life": [("squire", 16), ("crossbowman", 6)], "order": [("dwarf", 14), ("halfling", 9)],
    "death": [("skeleton", 19), ("imp", 11)], "chaos": [("orc", 12), ("bandit", 10)],
    "nature": [("wolf", 11), ("sprite", 9)], "might": [("berserker", 14), ("centaur", 4)],
}


def army_stacks(faction):
    """[(creature number, count)] for a map's hero record; [] for a random faction."""
    return [(CREATURE_ID[n], k) for n, k in START_ARMY.get(faction, [])]


SPELL_POINT_SKILLS = {"healing", "enchantment", "black", "conjuration", "herbalism"}
# Base hero statistics at level 1 without skills. Not in the game's data files: None = not yet
# confirmed in the game (shown as "?" in the setup window).
BASE_STATS = {"melee_attack": None, "ranged_attack": None, "melee_defense": None,
              "ranged_defense": None, "hit_points": None, "damage": None, "speed": None,
              "movement": None}


def class_title(c):
    return CLASS_TITLES.get(c, c.replace("_", " ").title())


class HeroInfo:
    """Skills, creatures and icons, read from the game archives (Resources)."""

    def __init__(self, res):
        self.res = res
        self.skill_rows = {r[0]: r for r in h4data.read_table(res.read("table.skills.h4d")) if r and r[0]}
        rows = h4data.read_table(res.read("table.creatures.h4d"))
        head = rows[1]
        self.creatures = {}
        for r in rows[2:]:
            if len(r) >= len(head) - 2 and r[5].isdigit():
                rec = dict(zip(head, r))
                self.creatures[r[0].lower()] = rec
        self._icons = {}

    # -- names and texts

    def skill_name(self, kw, level="basic"):
        row = self.skill_rows.get(f"{kw}_{level}")
        return row[1] if row else kw.title()

    def skill_help(self, kw, level="basic"):
        row = self.skill_rows.get(f"{kw}_{level}")
        return row[2] if row and len(row) > 2 else ""

    def hero_skills(self, cls):
        return [SKILLS[i] for i in CLASSES[cls][1]]

    def stats(self, cls):
        """Starting statistics of a level-1 hero of this class (None = base value unknown)."""
        skills = set(self.hero_skills(cls))
        st = dict(BASE_STATS)
        if "combat" in skills:          # Basic Melee
            st["melee_attack"] = 15
        if "toughness" in skills:       # Basic Combat
            st["melee_defense"] = st["ranged_defense"] = 15
        st["spell_points"] = 10 * len(skills & SPELL_POINT_SKILLS)
        st["morale"] = 0                # one faction's creatures only, no Leadership
        st["luck"] = 0
        return st

    def army(self, faction):
        """[(creature keyword, count)] the hero starts with."""
        return list(START_ARMY.get(faction, []))

    def creature(self, name):
        return self.creatures[name]

    # -- icons (RGBA tuples (w, h, bytes)), cached per sheet

    def _sheet(self, name):
        if name not in self._icons:
            try:
                layers = h4data.read_layers(self.res.read(name))
            except KeyError:
                layers = []
            self._icons[name] = {n.lower(): (w, h, px) for n, w, h, px in layers}
        return self._icons[name]

    def skill_icon(self, kw):
        return self._sheet(f"layers.icons.skills.{SHEET[GROUP[kw]]}.52.h4d").get(kw)

    def creature_icon(self, name):
        return self._sheet("layers.icons.creatures.52.h4d").get(name)

    def stat_icon(self, key):
        names = {"melee_attack": "melee_attack", "ranged_attack": "ranged_attack",
                 "melee_defense": "melee_defense", "ranged_defense": "ranged_defense",
                 "hit_points": "hit_points", "damage": "damage", "speed": "speed",
                 "movement": "movement", "spell_points": "spell_points"}
        if key in ("morale", "luck"):
            return self._sheet("layers.icons.morale.34.h4d").get(f"0 {key}")
        return self._sheet("layers.icons.stats.27.h4d").get(names[key])
