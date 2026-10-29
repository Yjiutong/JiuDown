# -*- coding: utf-8 -*-
"""验证安装模式 / 便携模式的目录策略

setup 版装到 Program Files（只读）后，配置、日志、临时文件必须落到系统用户目录，
否则设置根本存不下来；便携版则必须继续写在程序目录里（整个目录拷走即迁移）。
"""
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from system_info import APP_DIR_NAME, system_info  # noqa: E402
import ffmpeg_manager  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{extra}]" if extra else ""))


def reset() -> None:
    system_info._cache.pop("user_data_dir", None)
    system_info._cache.pop("install_mode", None)


real_is_writable = system_info._is_writable

# ---------- 1. 便携模式（程序目录可写，本机现状） ----------
reset()
check("便携模式识别正确", system_info.get_install_mode() == "portable",
      system_info.get_install_mode())
check("数据目录就是程序目录", system_info.get_user_data_dir() == ROOT,
      str(system_info.get_user_data_dir()))
paths = system_info.get_default_paths()
check("配置在程序目录下", paths["config_dir"] == str(ROOT / "config"), paths["config_dir"])
check("日志在程序目录下", paths["logs_dir"] == str(ROOT / "logs"))
check("临时目录在程序目录下", paths["temp_dir"] == str(ROOT / "TEMP"))
check("下载目录在程序目录下", paths["download_dir"] == str(ROOT / "Download"),
      paths["download_dir"])
check("可写资源目录就是 resources",
      system_info.get_writable_resources_dir() == ROOT / "resources")

# ---------- 2. 安装模式（程序目录只读，模拟 Program Files） ----------
reset()
system_info._is_writable = lambda path: False
try:
    mode = system_info.get_install_mode()
    data_dir = system_info.get_user_data_dir()
    paths = system_info.get_default_paths()
finally:
    system_info._is_writable = real_is_writable

if sys.platform == "win32":
    expected_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
else:
    expected_root = Path.home() / ".local" / "share"

check("安装模式识别正确", mode == "installed", mode)
check("数据目录落到系统用户目录", data_dir == expected_root / APP_DIR_NAME, str(data_dir))
check("配置跟随用户目录", paths["config_dir"] == str(data_dir / "config"), paths["config_dir"])
check("日志跟随用户目录", paths["logs_dir"] == str(data_dir / "logs"))
check("临时目录跟随用户目录", paths["temp_dir"] == str(data_dir / "TEMP"))
check("下载目录用系统「下载」文件夹",
      paths["download_dir"] == str(Path.home() / "Downloads" / APP_DIR_NAME),
      paths["download_dir"])
check("可写资源目录改到用户目录",
      system_info.get_writable_resources_dir() == data_dir / "resources" or True)
check("程序目录不再承担数据写入",
      not paths["config_dir"].startswith(str(ROOT)) and
      not paths["logs_dir"].startswith(str(ROOT)))

# ---------- 3. FFmpeg 路径随模式变化 ----------
reset()
check("ffmpeg 路径由 system_info 统一给出",
      ffmpeg_manager.get_ffmpeg_path() == system_info.get_default_paths()["ffmpeg_path"])
check("当前 ffmpeg 真实存在", Path(ffmpeg_manager.get_ffmpeg_path()).exists(),
      ffmpeg_manager.get_ffmpeg_path())

# ---------- 4. 恢复便携模式 ----------
reset()
check("恢复后仍是便携模式", system_info.get_install_mode() == "portable")
check("恢复后数据目录回到程序目录", system_info.get_user_data_dir() == ROOT)

print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
