# PyInstaller spec: two one-file builds from the same sources.   Build with build.bat (or: pyinstaller patchwork.spec --noconfirm)
#   patchwork.exe      the GUI, no console window
#   patchwork-cli.exe  the command line interface, console app (no Qt, so it is much smaller)
from PyInstaller.utils.hooks import collect_submodules

QT_UNUSED = ["PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtOpenGL",
             "PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtSql", "PySide6.QtTest"]

gui = Analysis(
    ["main.py"],
    pathex=["."],
    datas=[("assets", "assets")],                                  # icons / svgs, read through config.RES
    hiddenimports=collect_submodules("src"),                       # gui / sources are imported lazily from the CLI
    excludes=["tkinter"] + QT_UNUSED,
)
cli = Analysis(
    ["main_cli.py"],
    pathex=["."],
    hiddenimports=collect_submodules("src", filter=lambda name: not name.startswith("src.gui")),
    excludes=["tkinter", "PySide6", "shiboken6"],
)

gui_pyz, cli_pyz = PYZ(gui.pure, gui.zipped_data), PYZ(cli.pure, cli.zipped_data)

EXE(gui_pyz, gui.scripts, gui.binaries, gui.zipfiles, gui.datas, [],
    name="patchwork", icon="assets/icon.ico", console=False, upx=False)
EXE(cli_pyz, cli.scripts, cli.binaries, cli.zipfiles, cli.datas, [],
    name="patchwork-cli", icon="assets/icon.ico", console=True, upx=False)
