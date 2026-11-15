"""Setup window for the random map generator, in the spirit of Heroes III's random map dialog.

Pick map size, number of players, and for each player: human or computer, faction and starting
hero (with portrait, class, skills, army and biography from the game's own data). "Create map"
writes _random_map_<seed>.h4c to the game's Maps folder. On start it asks for the game folder
(remembered from the last run).

Run: pythonw setup_window.py, or the packaged "HoMM4 Random Map" program.
"""
import os
import random
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gamefolder  # noqa: E402
import generator  # noqa: E402
import h4data  # noqa: E402
import h4r  # noqa: E402
import heroinfo  # noqa: E402
import mymaps  # noqa: E402
import naming  # noqa: E402

PLAYER_COLORS = [("Red", "#c0392b"), ("Blue", "#2e6fd1"), ("Green", "#2f9e44"),
                 ("Orange", "#e67e22"), ("Purple", "#8e44ad"), ("Teal", "#1abc9c")]
SIZES = [("Small (76)", "small"), ("Medium (152)", "medium"), ("Large (228)", "large"),
         ("Extra large (304)", "xl")]
FACTION_NAMES = {"life": "Life (Haven)", "order": "Order (Academy)", "death": "Death (Necropolis)",
                 "chaos": "Chaos (Asylum)", "nature": "Nature (Preserve)", "might": "Might (Stronghold)"}

RANDOM = "Random"


# ---------------------------------------------------------------- settings and game data

class GameData:
    """Heroes (by faction) and their portraits, read from the game's archives."""

    def __init__(self, game_dir):
        self.res = h4r.Resources(os.path.join(game_dir, "data"))
        rows = h4data.heroes(self.res)
        self.portrait_sheets = {}
        self.by_faction = {f: [] for f in generator.FACTIONS}
        names = {}
        for f in generator.FACTIONS:
            for name, *_ in h4data.read_layers_names(self.res.read(f"layers.portraits.{f}.82.h4d")):
                names[name.lower()] = f
        for row, h in enumerate(rows):
            cls = h["class"].lower()
            faction = names.get(h["keyword"].lower()) or names.get(h["name"].lower())
            if cls not in heroinfo.CLASSES or not faction or not h["default"]:
                continue
            h = dict(h, row=row, cls=cls, faction=faction)
            self.by_faction[faction].append(h)
        for lst in self.by_faction.values():
            lst.sort(key=lambda h: h["name"])
        self.hero_info = heroinfo.HeroInfo(self.res)

    def portrait(self, hero):
        """RGBA (w, h, bytes) of the hero's 82 px portrait."""
        f = hero["faction"]
        if f not in self.portrait_sheets:
            sheet = h4data.read_layers(self.res.read(f"layers.portraits.{f}.82.h4d"))
            self.portrait_sheets[f] = {n.lower(): (w, h, px) for n, w, h, px in sheet}
        sheet = self.portrait_sheets[f]
        return sheet.get(hero["keyword"].lower()) or sheet.get(hero["name"].lower())


def photo_from_rgba(w, h, rgba, bg=(32, 28, 24)):
    """Tk image from RGBA bytes (alpha blended over bg), without needing Pillow."""
    out = bytearray(3 * w * h)
    for i in range(w * h):
        r, g, b, a = rgba[4 * i:4 * i + 4]
        out[3 * i] = (r * a + bg[0] * (255 - a)) // 255
        out[3 * i + 1] = (g * a + bg[1] * (255 - a)) // 255
        out[3 * i + 2] = (b * a + bg[2] * (255 - a)) // 255
    ppm = f"P6 {w} {h} 255\n".encode() + bytes(out)
    return tk.PhotoImage(data=ppm, format="PPM")


# ---------------------------------------------------------------- the window

BG, PANEL, GOLD, TEXT = "#201c18", "#2c2620", "#d8b25a", "#eee4cc"
MUTED, FRAME, SLOT, RULE = "#9c8f75", "#8a6d35", "#14110e", "#4a3e2c"
PANEL_RGB, SLOT_RGB = (0x2c, 0x26, 0x20), (0x14, 0x11, 0x0e)
LINK = "#8fb4e8"
AUTHOR_URL = "https://www.youtube.com/@TishGamer"


class SetupWindow:
    def __init__(self, root, game):
        self.root = root
        root.title("HoMM4 Random Map Generator by https://www.youtube.com/@TishGamer")
        root.configure(bg=BG)
        root.resizable(False, False)
        self.game = game
        self.data = None
        self.images = {}
        self.scale = root.winfo_fpixels("1i") / 96.0
        self._style()

        main = tk.Frame(root, bg=BG, padx=14, pady=12)
        main.pack(fill="both", expand=True)
        head = tk.Frame(main, bg=BG)
        head.grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(head, text="HoMM4 Random Map Generator", font=("Georgia", 20, "bold"), fg=GOLD,
                 bg=BG).pack(side="left")
        tk.Label(head, text="by", font=("Georgia", 12, "italic"), fg=MUTED,
                 bg=BG).pack(side="left", padx=(10, 0), pady=(8, 0))
        link = tk.Label(head, text=AUTHOR_URL, font=("Georgia", 12, "italic underline"), fg=LINK,
                        bg=BG, cursor="hand2")
        link.pack(side="left", padx=(5, 0), pady=(8, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open(AUTHOR_URL))
        link.bind("<Enter>", lambda e: link.config(fg=GOLD))
        link.bind("<Leave>", lambda e: link.config(fg=LINK))

        left = tk.Frame(main, bg=BG)
        left.grid(row=1, column=0, sticky="nw", padx=(0, 14))
        self._map_options(left)
        self._players_table(left)
        self._maps_list(left)

        right = tk.Frame(main, bg=PANEL, width=self.px(self.CARD_W), height=self.px(self.CARD_H),
                         highlightthickness=1, highlightbackground="#5a4a30")
        right.grid(row=1, column=1, sticky="n")
        right.grid_propagate(False)
        right.pack_propagate(False)
        self._hero_panel(right)

        bottom = tk.Frame(main, bg=BG, pady=10)
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew")
        self._buttons(bottom)

        # the left column keeps one size whatever the number of players: the maps list takes
        # the room the hidden player rows leave
        self.count.current(4)
        self.update_rows()
        left.update_idletasks()
        left.config(width=left.winfo_reqwidth(), height=self.px(self.CARD_H))
        left.pack_propagate(False)
        self.count.current(0)
        self.update_rows()

        self.editing = None
        self.load_game_data()
        self.show_hero(0)
        self.refresh_maps()

    # -- layout pieces

    def _style(self):
        st = ttk.Style()
        st.theme_use("clam")
        st.configure("TCombobox", fieldbackground="#3a3228", background="#3a3228", foreground=TEXT,
                     arrowcolor=GOLD)
        st.map("TCombobox", fieldbackground=[("readonly", "#3a3228")], foreground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", "#3a3228")
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#7a5c22")
        st.configure("Maps.Treeview", background=SLOT, fieldbackground=SLOT, foreground=TEXT,
                     borderwidth=0, rowheight=self.px(24), font=("Segoe UI", 9))
        st.map("Maps.Treeview", background=[("selected", "#7a5c22")],
               foreground=[("selected", "#fff4d6")])
        st.configure("Maps.Treeview.Heading", background="#3a3228", foreground=MUTED,
                     relief="flat", font=("Segoe UI", 9, "bold"))
        st.map("Maps.Treeview.Heading", background=[("active", "#4a3e2c")])
        st.configure("Vertical.TScrollbar", background="#3a3228", troughcolor=SLOT,
                     arrowcolor=GOLD, bordercolor=SLOT)

    def _label(self, parent, text, **kw):
        opts = {"fg": TEXT, "bg": BG, "font": ("Segoe UI", 10)}
        opts.update(kw)
        return tk.Label(parent, text=text, **opts)

    def _map_options(self, parent):
        box = tk.LabelFrame(parent, text=" New map ", fg=GOLD, bg=BG, font=("Segoe UI", 10, "bold"),
                            padx=10, pady=8, bd=1, relief="groove")
        box.pack(fill="x")
        self.map_box = box
        self._label(box, "Size").grid(row=0, column=0, sticky="w")
        self.size = ttk.Combobox(box, state="readonly", width=16, values=[s for s, _ in SIZES])
        self.size.current(0)
        self.size.grid(row=0, column=1, sticky="w", padx=6)

        self._label(box, "Players").grid(row=0, column=2, sticky="w", padx=(14, 0))
        self.count = ttk.Combobox(box, state="readonly", width=4, values=[str(n) for n in range(2, 7)])
        self.count.current(0)
        self.count.grid(row=0, column=3, sticky="w", padx=6)
        self.count.bind("<<ComboboxSelected>>", lambda e: self.update_rows())

        self._label(box, "Seed").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.seed = tk.Entry(box, width=12, bg="#3a3228", fg=TEXT, insertbackground=TEXT, relief="flat")
        self.seed.grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))
        self.seed_hint = self._label(box, "(empty = new random map)", fg="#9c8f75")
        self.seed_hint.grid(
            row=1, column=2, columnspan=2, sticky="w", padx=(14, 0), pady=(8, 0))

        self._label(box, "Game").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.game_label = self._label(box, self.game or "not found - choose the folder",
                                      fg="#9c8f75", wraplength=330, justify="left")
        self.game_label.grid(row=2, column=1, columnspan=2, sticky="w", padx=6, pady=(8, 0))
        tk.Button(box, text="Change...", command=self.change_game, bg="#3a3228", fg=TEXT,
                  relief="flat", activebackground="#5a4a30").grid(row=2, column=3, pady=(8, 0))

    def _players_table(self, parent):
        box = tk.LabelFrame(parent, text=" Players ", fg=GOLD, bg=BG, font=("Segoe UI", 10, "bold"),
                            padx=10, pady=8, bd=1, relief="groove")
        box.pack(fill="x", pady=(10, 0))
        for col, text in enumerate(["", "Player", "Faction", "Starting hero", ""]):
            self._label(box, text, fg="#9c8f75").grid(row=0, column=col, sticky="w", padx=3)
        self.rows = []
        for i, (cname, ccolor) in enumerate(PLAYER_COLORS):
            sw = tk.Frame(box, bg=ccolor, width=18, height=18)
            who = ttk.Combobox(box, state="readonly", width=9, values=["Human", "Computer"])
            who.current(0 if i == 0 else 1)
            faction = ttk.Combobox(box, state="readonly", width=18,
                                   values=[RANDOM] + [FACTION_NAMES[f] for f in generator.FACTIONS])
            faction.current(0)
            hero = ttk.Combobox(box, state="readonly", width=24, values=[RANDOM])
            hero.current(0)
            info = tk.Button(box, text="?", width=2, bg="#3a3228", fg=GOLD, relief="flat",
                             activebackground="#5a4a30", command=lambda i=i: self.show_hero(i))
            faction.bind("<<ComboboxSelected>>", lambda e, i=i: self.faction_changed(i))
            hero.bind("<<ComboboxSelected>>", lambda e, i=i: self.hero_changed(i))
            self.rows.append({"widgets": (sw, who, faction, hero, info), "who": who,
                              "faction": faction, "hero": hero, "heroes": []})
        self.update_rows()

    def _maps_list(self, parent):
        box = tk.LabelFrame(parent, text=" My random maps ", fg=GOLD, bg=BG,
                            font=("Segoe UI", 10, "bold"), padx=10, pady=8, bd=1, relief="groove")
        box.pack(fill="both", expand=True, pady=(10, 0))
        bar = tk.Frame(box, bg=BG)
        bar.pack(side="bottom", fill="x", pady=(8, 0))
        small = dict(bg="#3a3228", fg=TEXT, relief="flat", activebackground="#5a4a30",
                     font=("Segoe UI", 9), padx=10, pady=2, disabledforeground="#6b604c")
        self.delete_btn = tk.Button(bar, text="Delete", command=self.delete_selected, **small)
        self.delete_btn.pack(side="left")
        self.deselect_btn = tk.Button(bar, text="Deselect", command=self.deselect, **small)
        self.deselect_btn.pack(side="left", padx=(6, 0))
        self.maps_note = self._label(bar, "", fg=MUTED, font=("Segoe UI", 9))
        self.maps_note.pack(side="right")

        holder = tk.Frame(box, bg=SLOT)
        holder.pack(fill="both", expand=True)
        cols = (("map", "Map", 170), ("size", "Size", 80), ("players", "Players", 170),
                ("date", "Made", 120))
        self.maps = ttk.Treeview(holder, columns=[c for c, _, _ in cols], show="headings",
                                 style="Maps.Treeview", selectmode="browse", height=3)
        for c, title, width in cols:
            self.maps.heading(c, text=title, anchor="w")
            self.maps.column(c, width=self.px(width), anchor="w", stretch=c == "players")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.maps.yview)
        self.maps.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.maps.pack(side="left", fill="both", expand=True)
        self.maps.bind("<<TreeviewSelect>>", lambda e: self.maps_selection_changed())
        self.maps.bind("<Escape>", lambda e: self.deselect())
        self.maps.bind("<Delete>", lambda e: self.delete_selected())
        self.map_entries = {}

    def _buttons(self, parent):
        self.status = self._label(parent, "", fg="#9c8f75", wraplength=self.px(560), justify="left",
                                  anchor="w", height=2)        # two lines, always: no resizing
        self.status.pack(side="left", fill="x", expand=True)
        style = dict(bg="#7a5c22", fg="#fff4d6", activebackground="#a07a30", relief="flat",
                     font=("Segoe UI", 10, "bold"), padx=14, pady=6)
        self.make_btn = tk.Button(parent, text="Create map", command=lambda: self.create(False),
                                  **style)
        self.make_btn.pack(side="right")
        self.update_btn = tk.Button(parent, text="Update map", command=lambda: self.create(True),
                                    **style)

    # -- the hero card (fixed size: changing the hero never resizes the window)

    CARD_W, CARD_H = 548, 574
    STAT_ROWS = [("melee_attack", "Melee Attack"), ("ranged_attack", "Ranged Attack"),
                 ("spell_points", "Spell Points"), ("melee_defense", "Melee Defense"),
                 ("ranged_defense", "Ranged Defense"), ("hit_points", "Hit Points"),
                 ("damage", "Damage"), ("speed", "Speed"), ("movement", "Movement")]

    def px(self, v):
        return int(round(v * self.scale))

    def put(self, w, x, y, width=None, height=None):
        kw = {"x": self.px(x), "y": self.px(y)}
        if width is not None:
            kw["width"] = self.px(width)
        if height is not None:
            kw["height"] = self.px(height)
        w.place(**kw)
        return w

    def _card_label(self, text="", fg=TEXT, size=10, bold=False, font="Segoe UI", **kw):
        return tk.Label(self.card, text=text, fg=fg, bg=PANEL, anchor="w", justify="left",
                        font=(font, size, "bold" if bold else "normal"), **kw)

    def _tile(self, x, y, size):
        """A framed square for a game icon; returns the inner label."""
        frame = tk.Frame(self.card, bg=FRAME)
        self.put(frame, x, y, size + 4, size + 4)
        inner = tk.Label(frame, bg=SLOT, bd=0)
        inner.place(x=self.px(2), y=self.px(2), width=self.px(size), height=self.px(size))
        return frame, inner

    def _section(self, text, y):
        self.put(self._card_label(text.upper(), fg=GOLD, size=9, bold=True), 14, y)
        self.put(tk.Frame(self.card, bg=RULE), 14 + len(text) * 8 + 12, y + 9,
                 self.CARD_W - 28 - len(text) * 8 - 12, 1)

    def _hero_panel(self, parent):
        W = self.CARD_W
        self.card = parent
        self.tip = Tooltip(self.root)
        # header: portrait, name, class, faction
        self.portrait_frame, self.portrait = self._tile(14, 14, 82)
        self.portrait.config(fg=MUTED, font=("Georgia", 30, "bold"))
        self.hero_name = self.put(self._card_label(fg=GOLD, size=16, bold=True, font="Georgia"),
                                  112, 12, W - 126 - 120)
        self.hero_class = self.put(self._card_label(size=10), 112, 46, W - 126 - 120)
        self.hero_faction = self.put(self._card_label(fg=MUTED, size=9), 112, 68, W - 126 - 120)
        # morale and luck, top right
        self.mood = {}
        for k, (key, title) in enumerate((("morale", "Morale"), ("luck", "Luck"))):
            x = W - 14 - 140 + k * 72
            frame, icon = self._tile(x + 10, 14, 44)
            text = self.put(tk.Label(self.card, fg=TEXT, bg=PANEL, font=("Segoe UI", 8)), x, 66, 68)
            self.mood[key] = (icon, text, title)
        self.put(tk.Frame(self.card, bg=RULE), 14, 110, W - 28, 1)

        # skills
        self._section("Skills", 120)
        self.skill_tiles = []
        for k in range(3):
            x = 14 + k * 110
            frame, icon = self._tile(x + 25, 142, 52)
            name = tk.Label(self.card, fg=TEXT, bg=PANEL, font=("Segoe UI", 8), justify="center",
                            wraplength=self.px(104))
            self.put(name, x, 202, 106, 32)
            self.skill_tiles.append((frame, icon, name, x))
        self.skill_note = self._card_label(fg=MUTED, size=9, wraplength=self.px(W - 40))

        # statistics, 3 x 3
        self._section("Statistics", 242)
        self.stat_cells = {}
        for n, (key, title) in enumerate(self.STAT_ROWS):
            x, y = 14 + (n % 3) * 176, 266 + (n // 3) * 30
            icon = self.put(tk.Label(self.card, bg=PANEL, bd=0), x, y, 27, 27)
            name = self.put(self._card_label(title, size=9), x + 32, y + 4, 100)
            value = self.put(tk.Label(self.card, bg=PANEL, fg=GOLD, anchor="e",
                                      font=("Segoe UI", 10, "bold")), x + 126, y + 3, 38)
            self.stat_cells[key] = (icon, name, value)

        # starting army
        self._section("Starting army", 360)
        self.army_cards = []
        for k in range(2):
            x = 14 + k * 264
            frame, icon = self._tile(x, 384, 52)
            count = tk.Label(frame, fg="#fff4d6", bg="#000000", font=("Segoe UI", 8, "bold"))
            lines = [self.put(self._card_label(fg=GOLD if i == 0 else (TEXT if i == 1 else MUTED),
                                               size=10 if i == 0 else 8, bold=i == 0),
                              x + 66, 382 + (0, 22, 39)[i], 196) for i in range(3)]
            self.army_cards.append((frame, icon, count, lines, x))
        self.army_note = self._card_label(fg=MUTED, size=9, wraplength=self.px(W - 40))

        # biography (fixed height, scrolls)
        self._section("Biography", 450)
        box = tk.Frame(self.card, bg=SLOT)
        self.put(box, 14, 472, W - 28, self.CARD_H - 472 - 14)
        self.hero_bio = tk.Text(box, bg=SLOT, fg="#d9cdb0", relief="flat", wrap="word", bd=0,
                                font=("Georgia", 9, "italic"), padx=8, pady=6, cursor="arrow",
                                highlightthickness=0)
        bar = ttk.Scrollbar(box, orient="vertical", command=self.hero_bio.yview)
        self.hero_bio.config(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.hero_bio.pack(side="left", fill="both", expand=True)
        self.hero_bio.config(state="disabled")
        self.set_bio("Pick a starting hero for a player, or press ? on a player's row.")

    def image(self, key, rgba):
        """Cached Tk image of a game icon, scaled to the display."""
        if key not in self.images:
            photo = photo_from_rgba(*rgba, bg=SLOT_RGB if key[0] in ("skill", "army", "mood", "hero")
                                    else PANEL_RGB)
            n = round(self.scale * 2)
            if n != 2:
                photo = photo.zoom(n).subsample(2)
            self.images[key] = photo
        return self.images[key]

    def set_bio(self, text):
        self.hero_bio.config(state="normal")
        self.hero_bio.delete("1.0", "end")
        self.hero_bio.insert("1.0", text)
        self.hero_bio.config(state="disabled")
        self.hero_bio.yview_moveto(0)

    def show_hero(self, i):
        hero = self.hero_of_row(i)
        faction = (hero or {}).get("faction") or self.faction_of_row(i)
        info = self.data.hero_info if self.data else None
        color = PLAYER_COLORS[i][0]
        self.portrait_frame.config(bg=PLAYER_COLORS[i][1])

        if hero:
            pic = self.data.portrait(hero)
            self.portrait.config(image=self.image(("hero", hero["keyword"]), pic) if pic else "", text="")
            self.hero_name.config(text=hero["name"])
            self.hero_class.config(text=f"Level 1 {heroinfo.class_title(hero['cls'])}")
            self.hero_faction.config(text=f"{FACTION_NAMES[faction]}  ·  {hero['sex'].title()}"
                                     f"  ·  {color} player")
            skills = info.hero_skills(hero["cls"])
            stats = info.stats(hero["cls"])
            self.set_bio(hero["biography"] or "No biography.")
        else:
            self.portrait.config(image="", text="?")
            self.hero_name.config(text="Random hero")
            self.hero_class.config(text="Level 1, class chosen by the game")
            self.hero_faction.config(text=(FACTION_NAMES[faction] if faction else "Random faction")
                                     + f"  ·  {color} player")
            skills, stats = [], {"morale": 0, "luck": 0}
            self.set_bio("The game picks a hero" + (f" of {FACTION_NAMES[faction]}" if faction else "")
                         + " when the map starts. Choose a hero to see their skills and history.")

        # morale and luck
        for key, (icon, text, title) in self.mood.items():
            v = stats.get(key, 0)
            img = info._sheet("layers.icons.morale.44.h4d").get(f"{v} {key}") if info else None
            icon.config(image=self.image(("mood", key, v), img) if img else "")
            text.config(text=f"{title} {v:+d}" if v else f"{title} 0")
            self.tip.bind(icon, f"{title} {v}: " + ("a hero starting with one faction's creatures and "
                                                     "no Leadership has neutral " + title.lower() + "."))

        # skills
        for k, (frame, icon, name, x) in enumerate(self.skill_tiles):
            if k < len(skills):
                kw = skills[k]
                img = info.skill_icon(kw)
                icon.config(image=self.image(("skill", kw), img) if img else "")
                name.config(text=info.skill_name(kw))
                self.put(frame, x + 25, 142, 56, 56)
                self.put(name, x, 202, 106, 32)
                self.tip.bind(icon, info.skill_help(kw))
            else:
                frame.place_forget()
                name.place_forget()
        if skills:
            self.skill_note.place_forget()
        else:
            self.skill_note.config(text="Skills come with the hero's class: choose a hero to see them.")
            self.put(self.skill_note, 14, 160)

        # statistics
        for key, (icon, name, value) in self.stat_cells.items():
            v = stats.get(key)
            img = info.stat_icon(key) if info else None
            icon.config(image=self.image(("stat", key), img) if img else "")
            value.config(text="—" if v is None else str(v), fg=GOLD if v is not None else MUTED)
            tip = (f"{name.cget('text')} {v}" if v is not None
                   else f"{name.cget('text')}: set by the game for the hero's class and level.")
            self.tip.bind(icon, tip)
            self.tip.bind(name, tip)

        # army
        army = info.army(faction) if info and faction else []
        for k, (frame, icon, count, lines, x) in enumerate(self.army_cards):
            if k < len(army):
                cname, n = army[k]
                c = info.creature(cname)
                img = info.creature_icon(cname)
                icon.config(image=self.image(("army", cname), img) if img else "")
                count.config(text=f" {n} ")
                count.place(relx=1.0, rely=1.0, anchor="se", x=-self.px(3), y=-self.px(3))
                plural = c.get("Plural Name", cname).title()
                lines[0].config(text=f"{n} {plural}")
                lines[1].config(text=f"Level {c['Level']} · Attack {c['Attack']} · "
                                f"Defense {c['Defense']} · HP {c['Hit Points']}")
                lines[2].config(text=f"Damage {c['Low']}–{c['High']} · Speed {c['Speed']}"
                                f" · Move {c['Move']}")
                self.put(frame, x, 384, 56, 56)
                for j, line in enumerate(lines):
                    self.put(line, x + 66, 382 + (0, 22, 39)[j], 196)
                help_text = c.get("Short Help Text") or c.get("Long Help Text") or ""
                self.tip.bind(icon, f"{n} {plural}. {help_text}".strip())
            else:
                frame.place_forget()
                for line in lines:
                    line.place_forget()
        if army:
            self.army_note.place_forget()
        else:
            self.army_note.config(text="With a random faction the game gives the hero its usual "
                                       "army. Choose a faction to get a starting army.")
            self.put(self.army_note, 14, 392)

    # -- behaviour

    def load_game_data(self):
        if not self.game:
            self.status.config(text="Choose the Heroes IV folder (the one with heroes4.exe).")
            return
        try:
            self.data = GameData(self.game)
        except Exception as e:  # show the problem instead of crashing
            self.data = None
            self.status.config(text=f"Could not read the game data: {e}")
            return
        for i in range(len(self.rows)):
            self.faction_changed(i, keep=True)
        n = sum(len(v) for v in self.data.by_faction.values())
        self.status.config(text=f"{n} heroes loaded from the game.")

    def change_game(self):
        game = gamefolder.ask(self.root, self.game, first_run=False)
        if game and game != self.game:
            self.game = game
            self.game_label.config(text=game)
            self.stop_editing()
            self.load_game_data()
            self.refresh_maps()
            for i in range(len(self.rows)):
                self.faction_changed(i, keep=True)
            self.show_hero(0)

    def update_rows(self):
        n = int(self.count.get())
        for i, row in enumerate(self.rows):
            for col, w in enumerate(row["widgets"]):
                if i < n:
                    w.grid(row=i + 1, column=col, padx=3, pady=2, sticky="w")
                else:
                    w.grid_remove()

    def faction_of_row(self, i):
        k = self.rows[i]["faction"].current()
        return None if k <= 0 else generator.FACTIONS[k - 1]

    def faction_changed(self, i, keep=False):
        row = self.rows[i]
        faction = self.faction_of_row(i)
        heroes = []
        if self.data:
            for f in ([faction] if faction else generator.FACTIONS):
                heroes += self.data.by_faction[f]
            if not faction:
                heroes.sort(key=lambda h: h["name"])
        row["heroes"] = heroes
        row["hero"]["values"] = [RANDOM] + [f"{h['name']} - {heroinfo.class_title(h['cls'])}" for h in heroes]
        row["hero"].current(0)
        if not keep:
            self.show_hero(i)

    def hero_changed(self, i):
        """A hero picked while the faction is Random: switch the faction to the hero's own and
        keep the hero selected in the (now shorter) list."""
        hero = self.hero_of_row(i)
        if hero and not self.faction_of_row(i):
            row = self.rows[i]
            row["faction"].current(generator.FACTIONS.index(hero["faction"]) + 1)
            self.faction_changed(i, keep=True)
            row["hero"].current(row["heroes"].index(hero) + 1)
        self.show_hero(i)

    def hero_of_row(self, i):
        row = self.rows[i]
        k = row["hero"].current()
        return row["heroes"][k - 1] if k > 0 else None

    # -- my random maps

    def refresh_maps(self, select=None):
        self.maps.delete(*self.maps.get_children())
        self.map_entries = {}
        if not self.game:
            return
        entries = mymaps.list_maps(gamefolder.maps_dir(self.game))
        for e in entries:
            try:
                info = mymaps.read_settings(e["path"])
            except Exception:  # not readable: still listed, so it can be deleted
                info = None
            e["info"] = info
            if info:
                size = mymaps.SIZE_NAMES.get(info["size"], str(info["size"]))
                factions = ", ".join(FACTION_NAMES[p["faction"]].split(" (")[0] if p["faction"]
                                     else "Random" for p in info["players"])
                players = f"{len(info['players'])}: {factions}"
            else:
                size, players = "?", "can't be read"
            iid = self.maps.insert("", "end", values=(naming.map_title(e["id"]), size, players,
                                                      mymaps.when(e["mtime"])))
            self.map_entries[iid] = e
            if select is not None and e["id"] == str(select):
                self.maps.selection_set(iid)
                self.maps.see(iid)
        self.maps_note.config(text=f"{len(entries)} map{'s' if len(entries) != 1 else ''} in the "
                                   "Maps folder" if entries else "No maps made yet")
        self.maps_selection_changed()

    def selected_map(self):
        sel = self.maps.selection()
        return self.map_entries.get(sel[0]) if sel else None

    def maps_selection_changed(self):
        """Selecting a map loads its settings; Update map then remakes it with the changes."""
        e = self.selected_map()
        self.delete_btn.config(state="normal" if e else "disabled")
        self.deselect_btn.config(state="normal" if e else "disabled")
        if e is None:
            if self.editing:
                self.stop_editing()
            return
        if not e.get("info"):
            self.stop_editing(keep_selection=True)
            self.status.config(text=f"{naming.map_title(e['id'])} can't be read; it can only be deleted.")
            return
        if self.editing and self.editing["path"] == e["path"]:
            return                       # same map again (e.g. after a refresh): keep the form
        self.load_map(e)

    def load_map(self, e):
        info = e["info"]
        sizes = [generator.SIZES[k] for _, k in SIZES]
        if info["size"] in sizes:
            self.size.current(sizes.index(info["size"]))
        self.count.current(len(info["players"]) - 2)
        self.update_rows()
        for i, p in enumerate(info["players"]):
            row = self.rows[i]
            row["who"].current(0 if p["human"] else 1)
            row["faction"].current(generator.FACTIONS.index(p["faction"]) + 1 if p["faction"] else 0)
            self.faction_changed(i, keep=True)
            kw = p["hero_keyword"]
            k = next((n for n, h in enumerate(row["heroes"]) if h["keyword"].lower() == kw), None) if kw else None
            row["hero"].current(k + 1 if k is not None else 0)
        self.seed.delete(0, "end")
        self.seed.insert(0, str(info.get("seed") or e["id"]))
        self.editing = e
        title = naming.map_title(e["id"])
        self.map_box.config(text=f" {title} ")
        self.seed_hint.config(text="(another seed = another layout)")
        self.update_btn.pack(side="right", padx=(0, self.px(20)), after=self.make_btn)
        self.status.config(text=f"{title} is loaded. Change it and press Update map to save the "
                                "changes in it, or Create map to make a new map from these settings.")
        self.show_hero(0)

    def stop_editing(self, keep_selection=False):
        self.editing = None
        self.map_box.config(text=" New map ")
        self.seed_hint.config(text="(empty = new random map)")
        self.update_btn.pack_forget()
        self.seed.delete(0, "end")
        if not keep_selection and self.maps.selection():
            self.maps.selection_remove(*self.maps.selection())
        self.status.config(text="New map: choose the settings and press Create map.")

    def deselect(self):
        self.maps.selection_remove(*self.maps.selection())
        self.stop_editing()

    def delete_selected(self):
        e = self.selected_map()
        if not e:
            return
        title = naming.map_title(e["id"])
        if not messagebox.askyesno(
                "Delete map", f"Delete \"{title}\"?\n\nThe file {os.path.basename(e['path'])} is "
                "removed from the game's Maps folder. This can't be undone.",
                icon="warning", default="no", parent=self.root):
            return
        try:
            mymaps.delete(e["path"])
        except OSError as ex:
            messagebox.showerror("Delete map", f"Could not delete the map.\n\n{ex}", parent=self.root)
            return
        if self.editing and self.editing["path"] == e["path"]:
            self.stop_editing()
        self.status.config(text=f"Deleted {title}.")
        self.refresh_maps()

    def settings(self):
        out = []
        for i in range(int(self.count.get())):
            row = self.rows[i]
            faction = self.faction_of_row(i)
            hero = self.hero_of_row(i)
            st = {"human": row["who"].current() == 0, "faction": faction, "hero": None}
            if hero:
                if not faction:            # a chosen hero fixes the faction to the hero's own
                    st["faction"] = hero["faction"]
                st["hero"] = generator.hero_settings(hero)
            out.append(st)
        return out

    def create(self, update=False):
        """Create map: a new map file. Update map: remake the selected map in place."""
        settings = self.settings()
        if not any(s["human"] for s in settings):
            self.status.config(text="At least one player must be human.")
            return
        if update and not self.editing:
            return
        maps_dir = gamefolder.maps_dir(self.game)
        text = self.seed.get().strip()
        seed = int(text) if text.isdigit() else None
        if update:
            map_id = self.editing["id"]
            if seed is None:
                seed = random.randrange(1000, 100000)
        else:
            taken = {e["id"] for e in mymaps.list_maps(maps_dir)}
            if seed is None or (self.editing and str(seed) == text and str(seed) in taken):
                # a new map next to the loaded one: a fresh seed, so it doesn't replace it
                seed = random.randrange(1000, 100000)
                while str(seed) in taken:
                    seed = random.randrange(1000, 100000)
            elif str(seed) in taken and not messagebox.askyesno(
                    "Replace map", f"{naming.map_title(seed)} already exists. Replace it?",
                    icon="warning", default="no", parent=self.root):
                return
            map_id = seed
        size = generator.SIZES[SIZES[self.size.current()][1]]
        for b in (self.make_btn, self.update_btn):
            b.config(state="disabled")
        self.status.config(text=("Updating " if update else "Creating ") + f"{naming.map_title(map_id)}...")

        def work():
            try:
                path = generator.write_map(seed, size, settings, maps_dir, log=lambda s: None,
                                           map_id=map_id)
                result = (True, map_id, path, update)
            except Exception as e:  # report in the window
                result = (False, map_id, str(e), update)
            self.root.after(0, lambda: self.done(*result))

        threading.Thread(target=work, daemon=True).start()

    def done(self, ok, map_id, info, updated=False):
        for b in (self.make_btn, self.update_btn):
            b.config(state="normal")
        title = naming.map_title(map_id)
        if not ok:
            self.status.config(text=f"Could not {'update' if updated else 'create'} the map: {info}")
            messagebox.showerror("HoMM4 Random Map Generator", f"Could not {'update' if updated else 'create'} the "
                                 f"map.\n\n{info}", parent=self.root)
            return
        self.editing = None              # the list is read again; select (and load) the map
        self.refresh_maps(select=map_id)
        sel = self.selected_map()
        if sel:
            self.load_map(sel)
        self.status.config(text=f"{'Updated' if updated else 'Created'} {title}.")
        messagebox.showinfo("Map updated" if updated else "Map created", (
            f"Your map \"{title}\" is {'updated' if updated else 'ready'}.\n\n"
            "To play it:\n"
            "1. Start Heroes of Might and Magic IV.\n"
            "2. Choose New Game, then Scenario.\n"
            f"3. Pick \"{title}\" (it is at the top of the list) and play.\n\n"
            f"Saved as:\n{info}"), parent=self.root)


class Tooltip:
    """Hover help, in a small window over the main one (never changes the window's size)."""

    def __init__(self, root):
        self.root, self.win, self.texts = root, None, {}

    def bind(self, widget, text):
        if widget not in self.texts:
            widget.bind("<Enter>", lambda e, w=widget: self.show(w))
            widget.bind("<Leave>", lambda e: self.hide())
        self.texts[widget] = text

    def show(self, w):
        text = self.texts.get(w)
        if not text:
            return
        self.hide()
        self.win = tk.Toplevel(self.root)
        self.win.wm_overrideredirect(True)
        tk.Label(self.win, text=text, bg="#14110e", fg=TEXT, font=("Segoe UI", 9), justify="left",
                 wraplength=320, padx=8, pady=6, highlightthickness=1,
                 highlightbackground=FRAME).pack()
        self.win.wm_geometry(f"+{w.winfo_rootx() + w.winfo_width() + 6}+{w.winfo_rooty()}")

    def hide(self):
        if self.win:
            self.win.destroy()
            self.win = None


def dpi_aware():
    """Sharp text on scaled Windows displays."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # not Windows, or an old one
        pass


def main():
    dpi_aware()
    root = tk.Tk()
    root.withdraw()
    root.title("HoMM4 Random Map Generator by https://www.youtube.com/@TishGamer")
    game = gamefolder.ask(root, gamefolder.saved_folder() or gamefolder.guess_folder(), first_run=True)
    if not game:
        root.destroy()
        return
    SetupWindow(root, game)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
