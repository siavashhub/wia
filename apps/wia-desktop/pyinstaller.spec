# PyInstaller spec for wia-desktop
# Build with:  pyinstaller apps/wia-desktop/pyinstaller.spec
# Output:      dist/wia-desktop/

# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None

ROOT = Path.cwd()
SRC = ROOT / "apps" / "wia-desktop" / "src"

a = Analysis(
    [str(SRC / "wia" / "main.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[(str(SRC / "wia" / "ui"), "wia/ui")],
    hiddenimports=[
        "wia.api.health",
        "wia.api.auth",
        "wia.api.briefing",
        "wia.api.entries",
        "wia.api.export",
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
