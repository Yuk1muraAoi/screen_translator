# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


def build_icon() -> str | None:
    source = Path("logo.jpg")
    target = Path("build") / "logo.ico"
    if not source.exists():
        return None

    target.parent.mkdir(exist_ok=True)
    try:
        from PyQt5.QtGui import QImage

        image = QImage(str(source))
        if image.isNull():
            return None
        image.save(str(target), "ICO")
    except Exception:
        return None
    return str(target)


hiddenimports = collect_submodules("PyQt5")
icon_file = build_icon()

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("logo.jpg", ".")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ScreenTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)
