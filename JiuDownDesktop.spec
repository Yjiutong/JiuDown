# -*- mode: python ; coding: utf-8 -*-
"""JiuDown 打包配置

路径全部相对 spec 所在目录（SPECPATH），因此仓库克隆到任意位置都能直接打包：
    pyinstaller JiuDownDesktop.spec
"""
import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(SPECPATH)  # noqa: F821  (SPECPATH 由 PyInstaller 注入)

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('PySide6')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# yt-dlp：通用站点后端（含 1700+ 站点提取器与官方 pyinstaller 钩子）
tmp_ret = collect_all('yt_dlp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
try:
    from yt_dlp.__pyinstaller import hook_dirs
    hookspath = list(hook_dirs)
except Exception:
    hookspath = []


a = Analysis(
    [os.path.join(ROOT, 'app.py')],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=hookspath,
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
    name='JiuDownDesktop',
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
    icon=os.path.join(ROOT, 'resources', 'app.ico'),
)
