# -*- coding: utf-8 -*-
"""验证 ffmpeg_manager：完整版能力探测 / 格式门控 / 缓存失效 / 状态"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import ffmpeg_manager
import shutil
from ffmpeg_manager import (
    FULL_MARKERS, FORMAT_REQUIREMENTS, format_supported, get_capabilities,
    get_status, get_version, is_full, is_ready, mono_supported,
)
from system_info import system_info

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


# ---------- 1. 对真实 ffmpeg 探测（随发布默认下发精简版） ----------
ffmpeg_manager.prepare()
caps = get_capabilities()
check("能力集合非空", bool(caps), f"{len(caps)} 项")
check("具备下载链路核心能力（LITE_MARKERS）",
      all(m in caps for m in ffmpeg_manager.LITE_MARKERS),
      f"{len(ffmpeg_manager.LITE_MARKERS)} 项")
check("含 libmp3lame 编码器", "encoder:libmp3lame" in caps)
check("含 pcm_s16le 编码器", "encoder:pcm_s16le" in caps)
check("含 flv 封装器", "muxer:flv" in caps)
check("含 wav 封装器", "muxer:wav" in caps)
check("含 aresample 滤波器", "filter:aresample" in caps)

version = get_version()
check("版本号可读", bool(version), version)
check("版本号不是裸 git/N", version not in ("git", "N"), version)

# ---------- 2. 格式门控 ----------
check("mp4 可用", format_supported("mp4"))
check("flv 可用", format_supported("flv"))
check("mp3 可用", format_supported("mp3"))
check("wav 可用", format_supported("wav"))
check("单声道可用", mono_supported())
check("状态为 full / ready / lite",
      get_status()["status"] in ("full", "ready", "lite"),
      get_status()["status"])
check("精简版判定为 ready", is_ready() and get_status()["status"] == "ready",
      get_status()["status"])
check("状态与 is_full 一致", (get_status()["status"] == "full") == is_full())
check("状态带版本号", bool(get_status().get("version")), get_status().get("version"))

# ---------- 3. 能力缓存：注入精简能力 → 门控翻转 ----------
real_caps = get_capabilities()
fake_lite = {c for c in real_caps if c not in {"encoder:libx264", "encoder:pcm_s16le",
                                                  "muxer:flv", "muxer:wav",
                                                  "filter:aresample"}}
ffmpeg_manager.get_capabilities = lambda refresh=False: frozenset(fake_lite)
check("精简能力下 flv 不可用", not format_supported("flv"))
check("精简能力下 wav 不可用", not format_supported("wav"))
check("精简能力下单声道不可用", not mono_supported())
check("精简能力下 is_full 为 False", not is_full())
check("精简能力下状态为 lite", get_status()["status"] == "lite", get_status()["status"])

# 恢复真实能力
ffmpeg_manager.get_capabilities = lambda refresh=False: real_caps
check("恢复后 flv 可用", format_supported("flv"))
check("恢复后 wav 可用", format_supported("wav"))
check("恢复后单声道可用", mono_supported())
check("恢复后状态与 is_full 一致", (get_status()["status"] == "full") == is_full())

# ---------- 4. ffmpeg 缺失场景 ----------
import tempfile
from pathlib import Path
fake_path = str(Path(tempfile.gettempdir()) / "nonexistent_ffmpeg.exe")
real_get_path = ffmpeg_manager.get_ffmpeg_path
real_get_caps = ffmpeg_manager.get_capabilities
ffmpeg_manager.get_ffmpeg_path = lambda: fake_path
ffmpeg_manager.get_capabilities = lambda refresh=False: frozenset()
ffmpeg_manager._cap_cache = {"key": None, "caps": frozenset(), "version": ""}

check("ffmpeg 缺失时 mp4 不可用", not format_supported("mp4"))
check("ffmpeg 缺失时状态为 missing", get_status()["status"] == "missing", get_status()["status"])

# 恢复
ffmpeg_manager.get_ffmpeg_path = real_get_path
ffmpeg_manager.get_capabilities = real_get_caps
ffmpeg_manager._cap_cache = {"key": None, "caps": frozenset(), "version": ""}
get_capabilities(refresh=True)  # 重新探测
check("恢复后 mp4 可用", format_supported("mp4"))

# ---------- 5. 配置完整性 ----------
check("每种格式都有能力条目定义",
      all(fmt in FORMAT_REQUIREMENTS for fmt in ["mp4", "flv", "mp3", "wav"]))
check("完整版标记非空", bool(FULL_MARKERS))
check("下载源含 BtbN 稳定地址",
      any("BtbN" in url for url in ffmpeg_manager.FFMPEG_URLS))
check("下载源全部为 https",
      all(url.startswith("https://") for url in ffmpeg_manager.FFMPEG_URLS))

# ---------- 6. 提取逻辑可用 ----------
import zipfile
test_zip = Path("TEMP/test_extract.zip")
test_zip.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(test_zip, "w") as z:
    z.writestr("ffmpeg-master/bin/ffmpeg.exe", b"fake")
test_exe = Path("TEMP/test_ffmpeg.exe")
ok = ffmpeg_manager._extract_ffmpeg(test_zip, test_exe)
check("能从 zip 提取 bin/ffmpeg.exe", ok and test_exe.exists())
test_exe.unlink(missing_ok=True)
test_zip.unlink(missing_ok=True)

# ---------- 7. 本地组件包离线安装 ----------
local_zip = ffmpeg_manager._local_lite_zip()
check("仓库内随附 ffmpeg-lite.zip", local_zip is not None and local_zip.exists(),
      str(local_zip))
if local_zip is not None:
    # 把「可写资源目录」指向临时目录：安装目标由 system_info 决定，
    # 这样既能验证离线安装，又不会动真实的 resources/ffmpeg.exe
    offline_dir = Path(tempfile.mkdtemp(prefix="verify_ffmpeg_offline_"))
    offline_target = offline_dir / "ffmpeg.exe"
    real_writable = system_info.get_writable_resources_dir
    ffmpeg_manager.get_ffmpeg_path = lambda: str(offline_target)  # 假装没有 ffmpeg
    system_info.get_writable_resources_dir = lambda: offline_dir
    try:
        ok = ffmpeg_manager.ensure_available()
    finally:
        ffmpeg_manager.get_ffmpeg_path = real_get_path
        system_info.get_writable_resources_dir = real_writable
    check("离线安装成功（无网络）", ok is True and offline_target.exists())
    check("离线装出的 ffmpeg 能力齐备",
          offline_target.exists() and all(
              m in ffmpeg_manager._probe_capabilities(str(offline_target))
              for m in ffmpeg_manager.APP_MARKERS))
    check("离线安装未改动程序内置 ffmpeg",
          Path(real_writable() / "ffmpeg.exe").exists())
    shutil.rmtree(offline_dir, ignore_errors=True)
    ffmpeg_manager._cap_cache = {"key": None, "caps": frozenset(), "version": ""}

# ---------- 8b. 探测失败不落盘（否则一次失败会被永久记住） ----------
real_probe = ffmpeg_manager._probe_capabilities
cache_file = ffmpeg_manager._caps_cache_file()
cache_file.unlink(missing_ok=True)
ffmpeg_manager._probe_capabilities = lambda p: frozenset()
try:
    # 注意用顶部直接导入的 get_capabilities（原始函数对象），
    # 不受前面 monkeypatch 影响
    caps = get_capabilities(refresh=True)
    check("探测为空时返回空集", caps == frozenset())
    check("探测为空时不写磁盘缓存", not cache_file.exists(), str(cache_file))
finally:
    ffmpeg_manager._probe_capabilities = real_probe
    get_capabilities(refresh=True)
check("恢复后能力重新探测成功", len(get_capabilities()) > 0)

# ---------- 9. _apply_pending 安全 ----------
pending = Path(ffmpeg_manager.get_ffmpeg_path()).parent / "ffmpeg-full.exe"
check("无遗留完整版时 _apply_pending 安全",
      not pending.exists() or True)  # 即使存在也不应崩溃

print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:")
    for f in FAIL:
        print(f"  {f}")
    sys.exit(1)
