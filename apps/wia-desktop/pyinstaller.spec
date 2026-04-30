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


def _build_app_icon() -> str | None:
    """Convert ``ui/logo.png`` into a multi-size ``.ico`` for the Windows exe.

    The Start-menu / taskbar / Desktop-shortcut icon comes from the icon
    resource embedded in the .exe (Inno Setup shortcuts inherit it). The
    repo only ships a PNG, so we generate the .ico under ``build/`` at
    package time. Returns ``None`` if Pillow or the source PNG is missing,
    which falls back to the default Python icon (the floppy).
    """
    png_path = SRC / "wia" / "ui" / "logo.png"
    if not png_path.exists():
        return None
    out_dir = ROOT / "build" / "wia-icon"
    out_dir.mkdir(parents=True, exist_ok=True)
    ico_path = out_dir / "wia.ico"
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(png_path).convert("RGBA")
        img.save(
            ico_path,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    except (OSError, ValueError):
        return None
    return str(ico_path)


APP_ICON = _build_app_icon()

# Ship the .ico inside the bundle so the Inno Setup installer can use it as
# an explicit IconFilename for shortcuts (more reliable than relying on the
# embedded exe icon for Desktop shortcut resolution).
if APP_ICON:
    extra_datas.append((APP_ICON, "."))

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
    icon=APP_ICON,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False,
    upx=False,
    name="wia-desktop",
)
