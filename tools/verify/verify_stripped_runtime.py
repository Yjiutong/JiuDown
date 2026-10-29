# -*- coding: utf-8 -*-
"""验证剥离后的组件运行时可用（解压 core/pyside/app → 用其中 python 启动应用）

这一步是剥离 PySide6 未使用模块后的安全网：如果删多了（例如 Qt6Gui 依赖了
被删的 dll），这里会直接失败。
"""
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

COMP = BASE / "build_components"
ORDER = ["core.zip", "app.zip", "pyside-1.zip", "pyside-2.zip", "pyside-3.zip"]


def main() -> int:
    missing = [z for z in ORDER if not (COMP / z).exists()]
    if missing:
        print("缺少组件包，请先运行 tools/build_components.py:", missing)
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="rt_stripped_"))
    print(f"解压组件到 {tmp} …")
    for name in ORDER:
        with zipfile.ZipFile(COMP / name) as zf:
            zf.extractall(tmp)
        print(f"  {name} ok")

    py = tmp / "python" / "python.exe"
    if not py.exists():
        print("解压后未找到 python.exe")
        return 1

    code = r"""
import os, sys, time
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, r'%s')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import qVersion
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
app = QApplication([])
w = QVideoWidget()
p = QMediaPlayer()
print('Qt', qVersion(), 'ok')
import theme
theme.theme_manager.set_mode('light', persist=False)
from config_manager import config_manager
config_manager.initialize()
from main_window import MainWindow
win = MainWindow()
win.show()
for _ in range(10):
    app.processEvents(); time.sleep(0.02)
print('MainWindow OK')
""" % str(BASE)

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    print("用剥离后的运行时启动应用…")
    proc = subprocess.run(
        [str(py), "-c", code],
        capture_output=True, text=True, timeout=180, cwd=str(BASE), env=env,
    )
    out = (proc.stdout or "").strip().splitlines()
    err = (proc.stderr or "").strip()
    ok = proc.returncode == 0 and any("MainWindow OK" in line for line in out)
    print("\n".join(out[-6:]))
    if not ok:
        print("---- stderr ----")
        print(err[-1500:])
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
