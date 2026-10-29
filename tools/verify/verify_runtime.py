# -*- coding: utf-8 -*-
"""运行时依赖来源验证：引擎只从 GitHub Release 拉取，不再走 pip / PyPI"""
import os
import sys

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import runtime_manager as R
import ytdlp_engine

checks = []


def ck(name, ok, extra=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra else ""))


# 1) 当前运行时带引擎
ck("运行时包含 yt-dlp 目录", R.has_engine_backend() is True, R.ENGINE_PACKAGE_DIR)
ck("运行时判定为完整", R.is_runtime_complete() is True)

# 2) 模拟旧版运行时（没有 yt_dlp 目录）→ 应判定为不完整
_orig = R.ENGINE_PACKAGE_DIR
R.ENGINE_PACKAGE_DIR = "python/Lib/site-packages/__no_such_engine__"
try:
    ck("旧版运行时（无引擎）判定为不完整", R.is_runtime_complete() is False)
    ck("跳过引擎检查时仍算完整", R.is_runtime_complete(check_engine=False) is True)
    st = R.get_runtime_status()
    ck("状态里 engine_exists 为 False", st["engine_exists"] is False)
    ck("状态里 complete 为 False", st["complete"] is False)
finally:
    R.ENGINE_PACKAGE_DIR = _orig

ck("恢复后重新完整", R.is_runtime_complete() is True)

# 2b) 完整性判定不依赖 ffmpeg.exe
#     ffmpeg 由 ffmpeg_manager 独立管理、不进组件包；若算进 runtime 完整性，
#     组件化安装出来的新 runtime 会每次启动都被判为不完整而重复拉取。
import shutil
import subprocess as _sp
import tempfile
from pathlib import Path

ck("REQUIRED_FILES 不含 ffmpeg.exe",
   not any("ffmpeg" in f for f in R.REQUIRED_FILES), R.REQUIRED_FILES)

_tmp = Path(tempfile.mkdtemp()) / "runtime"
(_tmp / "python").mkdir(parents=True)
(_tmp / "python" / "python.exe").write_bytes(b"stub")
(_tmp / "python" / "python312.dll").write_bytes(b"stub")
(_tmp / "python" / "Lib" / "site-packages" / "yt_dlp").mkdir(parents=True)


class _FakeRun:
    returncode = 0
    stdout = "3.12.10"
    stderr = ""


_orig_run, _orig_dir = _sp.run, R.get_runtime_dir
R.subprocess.run = lambda *a, **k: _FakeRun()
R.get_runtime_dir = lambda: _tmp
try:
    ck("组件化安装的 runtime（无 ffmpeg.exe）判定为完整",
       R.is_runtime_complete() is True)
    shutil.rmtree(_tmp / "python" / "Lib" / "site-packages" / "yt_dlp")
    ck("同一 runtime 缺引擎时判定为不完整", R.is_runtime_complete() is False)
finally:
    R.subprocess.run, R.get_runtime_dir = _orig_run, _orig_dir
    shutil.rmtree(_tmp.parent, ignore_errors=True)

# 3) 下载源就是本仓库的 release
ck("运行时下载源指向 release/runtime",
   R.RUNTIME_RELEASE_URL.endswith("/releases/download/runtime/runtime.zip"),
   R.RUNTIME_RELEASE_URL)
ck("下载源是本仓库 Yjiutong/JiuDown",
   "github.com/Yjiutong/JiuDown" in R.RUNTIME_RELEASE_URL)

# 4) 不再有 pip 兜底
ck("ytdlp_engine 不再提供 ensure_installed", not hasattr(ytdlp_engine, "ensure_installed"))

app_src = open("app.py", encoding="utf-8").read()
ck("app.py 不再调用 ensure_installed", "ensure_installed" not in app_src)
ck("app.py 引擎自检走 runtime_manager", "ensure_runtime" in app_src
   and "has_engine_backend" in app_src)

engine_src = open("ytdlp_engine.py", encoding="utf-8").read()
ck("ytdlp_engine 只剩显式升级路径（-U），无缺失兜底",
   '"install", "-U"' in engine_src and "ensure_installed" not in engine_src)

# 5) 更新引擎仍保留 pip（显式操作，与"缺失兜底"区分）
ck("显式更新仍可用（update_engine）", hasattr(ytdlp_engine, "update_engine"))

# 6) 首次安装脚本：本地组件优先 + 保留 release / 整包回退
bat = open("首次安装.bat", encoding="utf-8", errors="replace").read()
ck("首次安装.bat 调用组件化安装脚本", "install_runtime.ps1" in bat)
ps1 = open("tools/install_runtime.ps1", encoding="utf-8-sig").read()
ck("安装脚本优先用仓库内组件包",
   "Get-LocalManifest" in ps1 and "build_components" in ps1)
ck("安装脚本保留 release 回退",
   "releases/download/runtime" in ps1 and "manifest.json" in ps1)
ck("安装脚本保留整包回退", "runtime.zip" in ps1)
# BOM 必须只有一个：PS 5.1 只吃掉一个，多出来的会变成「无法将 # 识别为 cmdlet」
raw = open("tools/install_runtime.ps1", "rb").read()
ck("安装脚本恰好一个 UTF-8 BOM",
   raw.startswith(b"\xef\xbb\xbf") and not raw[3:].startswith(b"\xef\xbb\xbf"))
ck("安装脚本不删除仓库内的组件包",
   "if ($downloaded) { Remove-Item" in ps1 and "$zip.StartsWith" not in ps1)

print(f"\n===== {sum(checks)} passed, {len(checks) - sum(checks)} failed =====")
sys.stdout.flush()
os._exit(0 if all(checks) else 1)
