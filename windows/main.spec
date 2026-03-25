# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Windows EXE

import os
import sys

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[os.path.abspath(".."), os.path.abspath(".")],
    binaries=[],
    datas=[
        # Include deputy.wasm if present
        ("../core/deputy.wasm", "core") if os.path.exists("../core/deputy.wasm") else (".", "."),
    ],
    hiddenimports=[
        "bleak",
        "bleak.backends.winrt",
        "bleak.backends.winrt.client",
        "pytz",
        "wasmtime",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SchoolWater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # windowed (no console) app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,           # set to 'icon.ico' if available
)
