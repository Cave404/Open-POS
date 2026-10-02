# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
project_root = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    (os.path.join(project_root, "ui", "templates"), os.path.join("ui", "templates")),
    (os.path.join(project_root, "ui", "static"), os.path.join("ui", "static")),
    (os.path.join(project_root, "storage", "migrations"), os.path.join("storage", "migrations")),
    (os.path.join(project_root, "docs", "ADDON_SPEC.md"), "docs"),
]

hiddenimports = [
    "waitress",
    "webview",
    "sqlite3",
    "psycopg",
    "sqlalchemy",
    "serial",
    "requests",
    "core",
    "core.network",
    "hardware",
    "storage",
    "ui"
] + collect_submodules("ui.routes") + collect_submodules("core.addons") + collect_submodules("core.services")

a = Analysis(
    [os.path.join(project_root, "run.py")],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pdb"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenPOS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_root, "ui", "static", "img", "favicon.ico") if os.path.exists(os.path.join(project_root, "ui", "static", "img", "favicon.ico")) else None
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="OpenPOS",
)
