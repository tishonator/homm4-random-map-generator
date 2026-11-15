# PyInstaller recipe for the single-file program: pyinstaller HoMM4RandomMap.spec
# Builds dist/HoMM4RandomMap(.exe) - the setup window with the generator and its data files inside.
# The game's own files are not included: the program reads them from the player's game folder.
import sys

a = Analysis(
    ["tools/setup_window.py"],
    pathex=["tools"],
    datas=[("data", "data")],
    excludes=["PIL", "numpy", "unittest", "pydoc", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HoMM4RandomMap",
    console=False,
    upx=False,
)
if sys.platform == "darwin":
    app = BUNDLE(exe, name="HoMM4RandomMap.app", bundle_identifier=None)
