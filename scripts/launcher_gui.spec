# -*- mode: python ; coding: utf-8 -*-
# ─────────────────────────────────────────────────────────────────────────────
# launcher_gui.spec — PyInstaller spec for "Start Trading App.exe"
#
# Explicitly bundles the Tcl/Tk DLLs that radioconda borrows from Git mingw64,
# plus the tcl8.6 / tk8.6 library script directories from radioconda.
# ─────────────────────────────────────────────────────────────────────────────

import os, sys

CONDA    = r'C:\Users\gl450\radioconda'
CLIB_BIN = os.path.join(CONDA, 'Library', 'bin')
TCL_LIB  = os.path.join(CONDA, 'Library', 'lib', 'tcl8.6')
TK_LIB   = os.path.join(CONDA, 'Library', 'lib', 'tk8.6')

block_cipher = None

a = Analysis(
    ['../launcher_gui.pyw'],
    pathex=[],
    binaries=[
        # Tcl/Tk threaded DLLs that _tkinter.pyd links against
        (os.path.join(CLIB_BIN, 'tcl86t.dll'), '.'),
        (os.path.join(CLIB_BIN, 'tk86t.dll'),  '.'),
    ],
    datas=[
        # Tcl/Tk library script directories
        (TCL_LIB, 'tcl8.6'),
        (TK_LIB,  'tk8.6'),
    ],
    hiddenimports=['tkinter', 'tkinter.font', '_tkinter'],
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
    name='Start Trading App',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='launcher.ico',
)
