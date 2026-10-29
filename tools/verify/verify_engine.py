# -*- coding: utf-8 -*-
"""JiuDown 引擎（native + yt-dlp 双后端）验证

A. 结构：双后端、常量导出、info 字段
B. 路由：B 站 → native，其他 → yt-dlp，三种模式（auto/native/ytdlp）
C. 降级：native 失败自动落 yt-dlp（probe / download / resolve 三条链路）
D. 原生解析器：BV/av 识别、画质→qn 映射、非 B 站拒绝
E. UI：首页/设置页/下载页读取新引擎
"""
import os
import sys

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")

import theme  # noqa: E402

theme.theme_manager.set_mode("light", persist=False)

from config_manager import config_manager  # noqa: E402

config_manager.initialize()

import jiudown_engine as E  # noqa: E402
import ytdlp_engine  # noqa: E402

checks = []


def ck(name, ok, extra=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra else ""))


BILI = "https://www.bilibili.com/video/BV1xx411c7mD"
BILI_AV = "https://www.bilibili.com/video/av170001"
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# ---------------- A. 结构 ----------------
ck("引擎名称/版本", E.ENGINE_NAME == "JiuDown Engine" and E.ENGINE_VERSION,
   f"{E.ENGINE_NAME} {E.ENGINE_VERSION}")
info = E.engine.info()
for key in ("name", "version", "native_ready", "ytdlp_ready", "ytdlp_version", "mode"):
    ck(f"info 含 {key}", key in info, info.get(key))
ck("原生后端恒就绪", info["native_ready"] is True)
ck("原生后端实例存在", isinstance(E.engine.native, E.NativeBilibiliBackend))
ck("常量从旧引擎复用（同一对象）", E.QUALITY_CHOICES is ytdlp_engine.QUALITY_CHOICES)
ck("AUDIO_FORMATS 已导出", E.AUDIO_FORMATS == {"mp3", "wav"})
ck("format_selector 可用", "height<=720" in E.format_selector("720P", "mp4"))
ck("normalize_url 可用", E.normalize_url("bilibili.com/video/BV1xx411c7mD").startswith("https://"))

# ---------------- B. 路由 ----------------
ck("auto：B 站首选 native", E.engine.backend_for(BILI) == "native")
ck("auto：非 B 站走 yt-dlp", E.engine.backend_for(YT) == "ytdlp")
ck("auto：B 站备选含 yt-dlp", E.engine._plan(BILI) == ["native", "ytdlp"],
   E.engine._plan(BILI))

config_manager.set_config("engine_backend", "ytdlp")
ck("模式 ytdlp：B 站也走 yt-dlp", E.engine._plan(BILI) == ["ytdlp"], E.engine._plan(BILI))

config_manager.set_config("engine_backend", "native")
ck("模式 native：B 站仍带降级", E.engine._plan(BILI) == ["native", "ytdlp"])
ck("模式 native：非 B 站不受影响", E.engine._plan(YT) == ["ytdlp"])

config_manager.set_config("engine_backend", "auto")
ck("模式回填 auto", E.engine.mode() == "auto", E.engine.mode())

# ---------------- C. 降级 ----------------
calls = []
_orig_native_probe = E.engine.native.probe
_orig_ytdlp_probe = ytdlp_engine.probe
_orig_native_download = E.engine.native.download
_orig_ytdlp_download = ytdlp_engine.download


def fake_native_probe(url):
    calls.append("native")
    raise E.EngineError("原生链路模拟失败")


def fake_ytdlp_probe(url):
    calls.append("ytdlp")
    return {"id": "x", "title": "兜底标题", "uploader": "", "duration": 3,
            "thumbnail": "", "webpage_url": url, "extractor": "Fallback",
            "is_live": False, "playlist_count": 0}


def fake_native_download(url, **kw):
    calls.append("native-dl")
    raise E.EngineError("原生下载模拟失败")


def fake_ytdlp_download(url, **kw):
    calls.append("ytdlp-dl")
    return {"filepath": "/tmp/x.mp4", "title": "兜底", "extractor": "Fallback",
            "duration": 3, "bytes": 1}


E.engine.native.probe = fake_native_probe
ytdlp_engine.probe = fake_ytdlp_probe
E.engine.native.download = fake_native_download
ytdlp_engine.download = fake_ytdlp_download
try:
    result = E.probe(BILI)
    ck("降级顺序 native → yt-dlp", calls == ["native", "ytdlp"], calls)
    ck("降级后返回 yt-dlp 结果", result.get("title") == "兜底标题", result.get("title"))

    calls.clear()
    dl = E.download(BILI, quality="720P", file_format="mp4",
                    out_dir="Download", temp_dir="TEMP")
    ck("下载降级顺序正确", calls == ["native-dl", "ytdlp-dl"], calls)
    ck("降级结果标注后端", dl.get("backend") == "ytdlp", dl.get("backend"))
finally:
    E.engine.native.probe = _orig_native_probe
    ytdlp_engine.probe = _orig_ytdlp_probe
    E.engine.native.download = _orig_native_download
    ytdlp_engine.download = _orig_ytdlp_download

# 双后端都失败时给可读错误
_orig2 = E.engine.native.probe
E.engine.native.probe = fake_native_probe
_orig3 = ytdlp_engine.probe


def _always_fail(url):
    raise E.EngineError("站点拒绝访问")


ytdlp_engine.probe = _always_fail
try:
    try:
        E.probe(BILI)
        ck("双后端失败抛 EngineError", False, "未抛错")
    except E.EngineError as e:
        ck("双后端失败抛 EngineError", "站点拒绝访问" in str(e), str(e))
finally:
    E.engine.native.probe = _orig2
    ytdlp_engine.probe = _orig3

# ---------------- D. 原生解析器 ----------------
ck("识别 BV 号", E.NativeBilibiliBackend.parse_bvid(BILI) == "BV1xx411c7mD")
ck("识别 av 号", E.NativeBilibiliBackend.parse_bvid(BILI_AV) == "av170001")
try:
    E.NativeBilibiliBackend.parse_bvid(YT)
    ck("非 B 站链接被拒绝", False, "未抛错")
except ValueError as e:
    ck("非 B 站链接被拒绝", True, str(e))
ck("matches：B 站", E.NativeBilibiliBackend.matches(BILI) is True)
ck("matches：YouTube", E.NativeBilibiliBackend.matches(YT) is False)
ck("matches：B 站非视频页", E.NativeBilibiliBackend.matches("https://www.bilibili.com/") is False)

qn = E.NativeBilibiliBackend.QUALITY_QN
ck("画质映射 360P→16", qn.get("360P") == 16, qn.get("360P"))
ck("画质映射 720P→64", qn.get("720P") == 64, qn.get("720P"))
ck("画质映射 1080P→80", qn.get("1080P") == 80, qn.get("1080P"))
ck("最高画质请求 127", qn.get("最高") == 127, qn.get("最高"))

# ---------------- E. UI ----------------
from pages.download_page import QUALITIES, DownloadPage  # noqa: E402
from pages.home_page import HomePage  # noqa: E402
from pages.settings_page import SettingsPage  # noqa: E402

ck("下载页画质来自新引擎", QUALITIES is E.QUALITY_CHOICES, str(QUALITIES))

page = DownloadPage()
ck("下载页构建成功", page is not None)

hp = HomePage()
ck("首页引擎卡显示版本", hp._engine_value.text() == f"v{E.ENGINE_VERSION}",
   hp._engine_value.text())
ck("首页诊断含双后端", "原生 B 站" in hp._engine_line.text(), hp._engine_line.text())
ck("首页显示后端路由", hp._backend_line.text().startswith("后端路由:"),
   hp._backend_line.text())

sp = SettingsPage()
ck("设置页有后端路由下拉", hasattr(sp, "engine_backend"))
ck("后端下拉 3 个选项", sp.engine_backend.count() == len(E.BACKENDS),
   [sp.engine_backend.itemData(i) for i in range(sp.engine_backend.count())])
collected = sp._collect_settings()
ck("保存含 engine.backend", collected.get("engine", {}).get("backend") == "auto",
   collected.get("engine"))

print(f"\n===== {sum(checks)} passed, {len(checks) - sum(checks)} failed =====")
sys.stdout.flush()
os._exit(0 if all(checks) else 1)
