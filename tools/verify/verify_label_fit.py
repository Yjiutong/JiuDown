# -*- coding: utf-8 -*-
"""硬性规则回归：任何可见、带换行的 QLabel 都不得被压缩裁切

遍历主窗口所有页面（含设置页各标签页）的 QLabel，比较「分配高度」与
「按当前宽度完整排版所需高度」(heightForWidth)，差值 > 1px 即判失败。

用法：runtime\\python\\python.exe tools\\verify\\verify_label_fit.py
需要 QT_QPA_PLATFORM=windows（offscreen 字体库为空，测出来的行高不准）。
"""
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

import ytdlp_engine  # noqa: E402

ytdlp_engine._site_count_cache = 1  # 避免后台 import 线程干扰出图

from theme import theme_manager  # noqa: E402
import app as app_module  # noqa: E402
from main_window import MainWindow  # noqa: E402

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setQuitOnLastWindowClosed(False)
theme_manager.set_mode("light", persist=False)
app_module.initialize_config()

window = MainWindow()
window.resize(1280, 900)
window.show()
for _ in range(40):
    app.processEvents()

# 让每个页面都真正布局过一次：切页 + 展开滚动区，避免「未布局」误判
for page_index in range(window._stack.count()):
    window._switch_page(page_index)
    page = window._stack.widget(page_index)
    for scroll in page.findChildren(__import__(
            "PySide6.QtWidgets", fromlist=["QScrollArea"]).QScrollArea):
        scroll.ensureVisible(0, 0)
    for _ in range(30):
        app.processEvents()

window._switch_page(0)
for _ in range(30):
    app.processEvents()

failures = []
checked = 0


def check_tree(widget, scope: str) -> None:
    global checked
    for label in widget.findChildren(QLabel):
        text = label.text().strip()
        if not text or not label.wordWrap():
            continue
        if label.width() <= 0 or label.height() <= 0:
            continue
        needed = label.heightForWidth(label.width())
        if needed <= 0:
            continue
        checked += 1
        if label.height() < needed - 1:
            failures.append(
                f"{scope}: h={label.height()} < hfw={needed}, "
                f"w={label.width()}, class={label.property('cssClass')}, "
                f"text={text[:24]!r}"
            )


check_tree(window, "download")
settings = window._stack.widget(1)
if hasattr(settings, "tabs"):
    for tab in range(settings.tabs.count()):
        settings.tabs.setCurrentIndex(tab)
        for _ in range(20):
            app.processEvents()
        check_tree(settings, f"settings-tab{tab}")

print(f"checked {checked} visible wrapped QLabel(s)")
if failures:
    for line in failures:
        print("FAIL", line)
    print(f"===== {len(failures)} clipped label(s) =====")
    sys.exit(1)
print("===== 0 clipped label(s): PASS =====")
sys.exit(0)
