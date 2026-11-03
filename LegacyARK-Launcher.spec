# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['cml-launcher-gui.py'],
    pathex=[],
    binaries=[],
    datas=[('versions.json', '.'), ('descriptions.json', '.'), ('mods.json', '.'), ('logo.png', '.'), ('logo.ico', '.'), ('art', 'art')],
    hiddenimports=['tek_lib', 'tek_steamclient'],
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
    name='LegacyARK-Launcher',
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
    icon=['logo.ico'],
)
