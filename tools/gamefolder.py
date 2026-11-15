"""The Heroes IV game folder: remembered between runs, checked, and asked for in a dialog.

The folder is the one with heroes4.exe (and, in the Complete edition, the map editor
campaign_editor.exe). The generator reads the game's data from its data folder and saves new
maps to its Maps folder.
"""
import configparser
import os
import sys
import tkinter as tk
from tkinter import filedialog

GAME_EXE = "heroes4.exe"
EDITOR_EXE = "campaign_editor.exe"
APP_NAME = "HoMM4 Random Map"
GUESSES = [r"C:\GOG Games\HoMM 4 Complete", r"C:\Program Files (x86)\GOG Galaxy\Games\HoMM 4 Complete",
           r"C:\Program Files (x86)\GOG.com\HoMM 4 Complete", r"C:\Program Files\GOG Galaxy\Games\HoMM 4 Complete",
           r"D:\games\HoMM 4 Complete", r"D:\GOG Games\HoMM 4 Complete",
           r"C:\Program Files (x86)\3DO\Heroes 4", r"C:\Program Files (x86)\Ubisoft\Heroes of Might and Magic IV"]

BG, PANEL, GOLD, TEXT, MUTED = "#201c18", "#2c2620", "#d8b25a", "#eee4cc", "#9c8f75"
OK, BAD = "#7bc47f", "#e2725b"


# ---------------------------------------------------------------- remembered settings

def config_path():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_NAME, "settings.ini")


def saved_folder():
    cfg = configparser.ConfigParser()
    cfg.read(config_path(), encoding="utf-8")
    return cfg.get("game", "folder", fallback="")


def save_folder(folder):
    cfg = configparser.ConfigParser()
    cfg.read(config_path(), encoding="utf-8")
    cfg["game"] = {"folder": folder}
    os.makedirs(os.path.dirname(config_path()), exist_ok=True)
    with open(config_path(), "w", encoding="utf-8") as f:
        cfg.write(f)


def _registry_guesses():
    """Install folders that GOG and Ubisoft record in the registry (Windows only)."""
    out = []
    try:
        import winreg
    except ImportError:
        return out
    keys = [r"SOFTWARE\WOW6432Node\GOG.com\Games\1207658915", r"SOFTWARE\GOG.com\Games\1207658915"]
    for key in keys:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                out.append(winreg.QueryValueEx(k, "path")[0])
        except OSError:
            pass
    return out


def guess_folder():
    for c in _registry_guesses() + GUESSES:
        if c and find_game(c):
            return find_game(c)
    return ""


# ---------------------------------------------------------------- checking a folder

def _child(folder, name):
    """The entry of folder called name, ignoring case (Wine installs keep the game's casing)."""
    try:
        for e in os.listdir(folder):
            if e.lower() == name.lower():
                return os.path.join(folder, e)
    except OSError:
        pass
    return None


def find_game(folder):
    """The game folder for what the user picked: the folder itself, its parent (when they picked
    Maps or data) or a folder inside it (when they picked where the game folder is)."""
    folder = os.path.normpath(os.path.expanduser(folder.strip().strip('"'))) if folder.strip() else ""
    if not folder or not os.path.isdir(folder):
        return None
    candidates = [folder, os.path.dirname(folder)]
    try:
        candidates += sorted(os.path.join(folder, e) for e in os.listdir(folder)
                             if os.path.isdir(os.path.join(folder, e)))
    except OSError:
        pass
    for c in candidates:
        exe = _child(c, GAME_EXE)
        if exe and os.path.isfile(exe) and _child(c, "data"):
            return c
    return None


def check(folder):
    """(game folder or None, message for the user)."""
    text = folder.strip()
    if not text:
        return None, "Enter the folder where Heroes IV is installed, or press Browse."
    path = os.path.normpath(os.path.expanduser(text.strip('"')))
    if not os.path.isdir(path):
        return None, "This folder does not exist."
    game = find_game(path)
    if not game:
        if _child(path, GAME_EXE):
            return None, "heroes4.exe is here, but the game's data folder is missing."
        return None, ("Heroes IV is not in this folder. Pick the folder that contains heroes4.exe "
                      "and the map editor (campaign_editor.exe).")
    parts = ["Heroes IV found"]
    parts.append("with the map editor" if _child(game, EDITOR_EXE) else "(map editor not found, not needed)")
    msg = " ".join(parts) + "."
    if os.path.normcase(game) != os.path.normcase(path):
        msg += f" Using {game}"
    return game, msg


def maps_dir(game):
    """The game's Maps folder (created if missing)."""
    d = _child(game, "maps")
    if not d:
        d = os.path.join(game, "Maps")
        os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- the dialog

def ask(root, initial="", first_run=True):
    """Modal dialog asking for the game folder. Returns the checked folder, or None if the user
    closed it. On the first run the button reads Continue and closing it quits."""
    top = tk.Toplevel(root)
    top.title("HoMM4 Random Map Generator by https://www.youtube.com/@TishGamer")
    top.configure(bg=BG)
    top.resizable(False, False)
    result = {"folder": None}

    box = tk.Frame(top, bg=BG, padx=22, pady=18)
    box.pack(fill="both", expand=True)
    tk.Label(box, text="Where is Heroes IV installed?", font=("Georgia", 16, "bold"),
             fg=GOLD, bg=BG).grid(row=0, column=0, columnspan=2, sticky="w")
    tk.Label(box, text=("Choose the folder of Heroes of Might and Magic IV: the one with heroes4.exe "
                        "and the map editor. New maps are saved in its Maps folder, where the game "
                        "lists them under New Game > Scenario."),
             fg=TEXT, bg=BG, font=("Segoe UI", 10), justify="left", wraplength=560).grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(6, 14))

    var = tk.StringVar(value=initial)
    entry = tk.Entry(box, textvariable=var, width=62, bg="#3a3228", fg=TEXT, insertbackground=TEXT,
                     relief="flat", font=("Segoe UI", 10))
    entry.grid(row=2, column=0, sticky="ew", ipady=5)

    def browse():
        start = var.get().strip() if os.path.isdir(var.get().strip()) else os.path.expanduser("~")
        d = filedialog.askdirectory(parent=top, title="Heroes IV folder (with heroes4.exe)",
                                    initialdir=start, mustexist=True)
        if d:
            var.set(os.path.normpath(d))

    tk.Button(box, text="Browse...", command=browse, bg="#3a3228", fg=TEXT, relief="flat",
              activebackground="#5a4a30", padx=10).grid(row=2, column=1, padx=(8, 0), sticky="ns")
    status = tk.Label(box, text="", bg=BG, font=("Segoe UI", 9), justify="left", wraplength=560,
                      anchor="w", height=2)
    status.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 4))

    def refresh(*_):
        game, msg = check(var.get())
        status.config(text=("\u2714 " if game else "\u2716 ") + msg if var.get().strip() else msg,
                      fg=OK if game else (BAD if var.get().strip() else MUTED))
        go.config(state="normal")
        return game

    def finish(*_):
        game = refresh()
        if not game:
            entry.focus_set()
            top.bell()
            return
        save_folder(game)
        result["folder"] = game
        top.destroy()

    buttons = tk.Frame(box, bg=BG)
    buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(8, 0))
    style = dict(relief="flat", font=("Segoe UI", 10, "bold"), padx=16, pady=6)
    tk.Button(buttons, text="Quit" if first_run else "Cancel", command=top.destroy, bg="#3a3228",
              fg=TEXT, activebackground="#5a4a30", **style).pack(side="right", padx=(8, 0))
    go = tk.Button(buttons, text="Continue" if first_run else "Use this folder", command=finish,
                   bg="#7a5c22", fg="#fff4d6", activebackground="#a07a30", **style)
    go.pack(side="right")

    var.trace_add("write", refresh)
    refresh()
    top.bind("<Return>", finish)
    top.bind("<Escape>", lambda e: top.destroy())
    entry.focus_set()
    entry.icursor("end")
    top.update_idletasks()
    if root.winfo_viewable():
        x = root.winfo_rootx() + (root.winfo_width() - top.winfo_width()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - top.winfo_height()) // 3
        top.transient(root)
    else:
        x = (top.winfo_screenwidth() - top.winfo_width()) // 2
        y = (top.winfo_screenheight() - top.winfo_height()) // 3
    top.geometry(f"+{max(0, x)}+{max(0, y)}")
    top.lift()
    top.focus_force()
    top.grab_set()
    root.wait_window(top)
    return result["folder"]
