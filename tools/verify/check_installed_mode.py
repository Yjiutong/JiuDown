# -*- coding: utf-8 -*-
"""在只读的程序目录（模拟 Program Files）里实跑，验证安装模式的数据目录跳转"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app_dir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
sys.path.insert(0, app_dir)
os.chdir(app_dir)

import app  # noqa: E402

app.configure_logger()
app.initialize_config()

from system_info import system_info  # noqa: E402

paths = system_info.get_default_paths()
print("形态:", system_info.get_install_mode())
print("程序目录:", os.getcwd())
print("用户数据目录:", system_info.get_user_data_dir())
print("配置:", paths["config_dir"])
print("日志:", paths["logs_dir"])
print("下载:", paths["download_dir"])

import ffmpeg_manager as F  # noqa: E402

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

status = F.get_status()
print("ffmpeg:", status["status"], status["version"], status["path"])
print("caps 数量:", len(F.get_capabilities()), "| is_ready:", F.is_ready())
print("探测原始输出:", F._probe_version(status["path"]))
import subprocess  # noqa: E402
import re  # noqa: E402

try:
    r = subprocess.run([status["path"], "-hide_banner", "-encoders"],
                       capture_output=True, text=True, timeout=20)
    print("直接探测: rc=", r.returncode, "stdout长度=", len(r.stdout or ""),
          "stderr=", (r.stderr or "")[:200])
except Exception as e:
    print("直接探测异常:", type(e).__name__, e)

# 复刻 _probe_capabilities 的调用方式，看它为什么拿不到能力
for opt in ("-encoders", "-muxers", "-filters"):
    try:
        rr = subprocess.run([status["path"], "-hide_banner", opt], capture_output=True,
                            text=True, timeout=20, creationflags=F._NO_WINDOW)
        lines = (rr.stdout or "").splitlines()
        hit = [ln for ln in lines
               if len(ln.split()) >= 2 and re.fullmatch(r"[A-Z.]{1,6}", ln.split()[0])]
        print(f"  {opt}: rc={rr.returncode} len={len(rr.stdout or '')} 解析到={len(hit)}",
              "| stderr=", (rr.stderr or "")[:120])
        for ln in lines[:4]:
            print("     |", repr(ln[:70]))
    except Exception as e:
        print(f"  {opt} 异常:", type(e).__name__, e)

from PySide6.QtWidgets import QApplication  # noqa: E402
from main_window import MainWindow  # noqa: E402

qapp = QApplication([])
window = MainWindow()
window.show()
print("UI OK")

print("配置文件已生成:", os.path.exists(os.path.join(paths["config_dir"], "config.yaml")))
print("日志已生成:", bool(os.listdir(paths["logs_dir"])) if os.path.isdir(paths["logs_dir"]) else False)
