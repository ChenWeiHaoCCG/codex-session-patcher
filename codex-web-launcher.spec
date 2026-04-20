# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


def collect_tree(src_root: str, dest_root: str):
    items = []
    root = Path(src_root)
    for path in root.rglob("*"):
        if path.is_file():
            relative_parent = path.parent.relative_to(root)
            target_dir = str(Path(dest_root) / relative_parent).replace("\\", "/")
            items.append((str(path), target_dir))
    return items


hiddenimports = (
    collect_submodules("codex_session_patcher")
    + collect_submodules("web.backend")
    + collect_submodules("uvicorn")
)

datas = collect_data_files("codex_session_patcher")
datas += collect_tree("web/frontend/dist", "web/frontend/dist")

a = Analysis(
    ["codex_session_patcher/desktop_launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="codex-patcher-launcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="codex-patcher-launcher",
)
