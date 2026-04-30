# PyInstaller spec for wia-desktop
# Build with:  pyinstaller apps/wia-desktop/pyinstaller.spec
# Output:      dist/wia-desktop/

# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

ROOT = Path.cwd()
SRC = ROOT / "apps" / "wia-desktop" / "src"

# jsonschema (pulled in transitively via the `mcp` package) optionally loads
# `rfc3987_syntax`, which ships a .lark grammar file that PyInstaller must
# include as a data file. Without it the frozen app crashes on first import.
extra_datas = [(str(SRC / "wia" / "ui"), "wia/ui")]
extra_datas += collect_data_files("rfc3987_syntax")
extra_datas += collect_data_files("jsonschema_specifications")

a = Analysis(
    [str(SRC / "wia" / "main.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=extra_datas,
    hiddenimports=[
        "rfc3987_syntax",
        *collect_submodules("rfc3987_syntax"),
        "wia.api.health",
        "wia.api.workiq",
        "wia.api.briefing",
        "wia.api.entries",
        "wia.api.export",
        "wia.api.prefs",
        "wia.api.review",
        "wia.api.schedule",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="wia-desktop",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # windowed app
    icon=None,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False,
    upx=False,
    name="wia-desktop",
)
