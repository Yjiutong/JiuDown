# -*- coding: utf-8 -*-
"""验证 UI 能力门控：能力齐备时全部解锁，注入残缺能力后 flv/wav/单声道禁用

仓库内置的是源码裁剪编译的精简版 ffmpeg（已含 flv/wav/pcm/aresample），
因此“齐备”状态由 APP_MARKERS 判定，与是否具备 libx264 等视频重编码能力无关。
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox

app = QApplication(sys.argv)
app.setStyle("Fusion")

from theme import load_mode, theme_manager
theme_manager.set_mode(load_mode(), persist=False)

import ffmpeg_manager
from pages.download_page import AUDIO_FORMATS, FORMATS, DownloadPage
from pages.settings_page import SettingsPage

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def item_enabled(combo: QComboBox, text: str) -> bool:
    for i in range(combo.count()):
        if combo.itemText(i) == text:
            item = combo.model().item(i)
            return item is None or item.isEnabled()
    raise AssertionError(f"{text} 不在下拉列表中")


def item_tooltip(combo: QComboBox, text: str) -> str:
    for i in range(combo.count()):
        if combo.itemText(i) == text:
            return str(combo.itemData(i, Qt.ItemDataRole.ToolTipRole) or "")
    return ""


# ---------- 1. 格式表 ----------
check("FORMATS 含 wav", "wav" in FORMATS, str(FORMATS))
check("AUDIO_FORMATS 含 mp3/wav", AUDIO_FORMATS == {"mp3", "wav"})

# ---------- 2. 当前 ffmpeg（精简版但能力齐备）下的下载页 ----------
real_caps = ffmpeg_manager.get_capabilities()
check("当前 ffmpeg 能力齐备", ffmpeg_manager.is_ready(), str(sorted(real_caps)[:6]))
check("状态为 full/ready", ffmpeg_manager.get_status()["status"] in ("full", "ready"),
      ffmpeg_manager.get_status()["status"])

page = DownloadPage()
page.resize(1200, 800)
page.show()
app.processEvents()

check("mp4 可选", item_enabled(page.format_select, "mp4"))
check("mp3 可选", item_enabled(page.format_select, "mp3"))
check("flv 可选（含封装器）", item_enabled(page.format_select, "flv"))
check("wav 可选（含 pcm+wav）", item_enabled(page.format_select, "wav"))
check("解锁项无 tooltip", item_tooltip(page.format_select, "wav") == "")
check("当前格式为可用项",
      ffmpeg_manager.format_supported(page.format_select.currentText()),
      page.format_select.currentText())

# 切到 mp3 → 声道列表，单声道可选
page.format_select.setCurrentText("mp3")
app.processEvents()
check("mp3 下声道列表", page.quality_select.itemText(0) == "单声道")
check("单声道可选（含重采样）",
      item_enabled(page.quality_select, "单声道"))
check("双声道可选", item_enabled(page.quality_select, "双声道"))

# ---------- 3. 能力齐备时提示条隐藏 ----------
check("能力齐备时提示条隐藏", not page.ffmpeg_notice.isVisible())

# ---------- 4. 注入残缺能力 → 信号驱动置灰 ----------
fake_lite = {c for c in real_caps if c not in {"encoder:libx264", "encoder:pcm_s16le",
                                                  "muxer:flv", "muxer:wav",
                                                  "filter:aresample"}}
check("注入后能力不足", not all(
    m in fake_lite for m in ("muxer:flv", "muxer:wav", "filter:aresample")))
ffmpeg_manager.get_capabilities = lambda refresh=False: frozenset(fake_lite)
ffmpeg_manager.signals.capabilities_changed.emit()
app.processEvents()

check("残缺能力下 flv 置灰", not item_enabled(page.format_select, "flv"))
check("残缺能力下 wav 置灰", not item_enabled(page.format_select, "wav"))
check("置灰项有说明 tooltip", "完整版" in item_tooltip(page.format_select, "wav"),
      item_tooltip(page.format_select, "wav"))
check("残缺能力下单声道置灰", not item_enabled(page.quality_select, "单声道"))
check("残缺能力下提示条可见", page.ffmpeg_notice.isVisible())
notice_text = page.ffmpeg_notice_text.text()
check("提示条说明缺少的能力",
      "flv" in notice_text and "单声道" in notice_text, notice_text)
check("缺失清单含 flv/wav/单声道",
      {"flv", "wav", "单声道"} <= set(ffmpeg_manager.missing_features()),
      str(ffmpeg_manager.missing_features()))

# ---------- 5. 设置页门控与状态 ----------
settings = SettingsPage()
app.processEvents()
check("设置页 mp4 可选", item_enabled(settings.default_format, "mp4"))
check("设置页 wav 置灰", not item_enabled(settings.default_format, "wav"))
check("设置页 FFmpeg 状态显示不可用项",
      "不可用" in settings.ffmpeg_status_label.text(),
      settings.ffmpeg_status_label.text())
check("设置页升级按钮可用", settings.ffmpeg_download_btn.isEnabled())

# ---------- 6. 恢复能力：重新解锁 ----------
ffmpeg_manager.get_capabilities = lambda refresh=False: real_caps
ffmpeg_manager.signals.capabilities_changed.emit()
app.processEvents()
check("能力恢复后 flv 重新解锁", item_enabled(page.format_select, "flv"))
check("能力恢复后 wav 重新解锁", item_enabled(page.format_select, "wav"))
check("能力恢复后单声道解锁", item_enabled(page.quality_select, "单声道"))
check("能力恢复后提示条重新隐藏", not page.ffmpeg_notice.isVisible())
check("设置页状态标注能力齐备",
      "齐备" in settings.ffmpeg_status_label.text() or
      "全部格式可用" in settings.ffmpeg_status_label.text(),
      settings.ffmpeg_status_label.text())

print()
print(f"===== {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
