# -*- coding: utf-8 -*-
"""yt-dlp 全功能下载器重构 —— 综合验证

覆盖四层：
 A. 引擎层（无网络）：可用性/版本/链接规范化/画质→格式选择器/错误翻译
 B. 队列层（无网络）：任务增删改查、失败任务的可读错误、并发调度
 C. 界面层（无网络）：画质档位来源、右键菜单、标签提交、任务卡信息渲染
 D. 端到端（需网络，可跳过）：真实下载 + 进度回调 + 输出文件校验
"""
import asyncio
import os
import sys
import time

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

import ytdlp_engine as engine  # noqa: E402

checks = []


def ck(name, ok, extra=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra else ""))


# =====================================================================
# A. 引擎层
# =====================================================================
ck("引擎可用", engine.available())
ck("引擎版本可读", bool(engine.version()), engine.version())
ck("画质档位含「最高」", engine.QUALITY_CHOICES[0] == "最高", engine.QUALITY_CHOICES)
ck("格式档位为 mp4/flv/mp3/wav",
   engine.FORMAT_CHOICES == ["mp4", "flv", "mp3", "wav"], engine.FORMAT_CHOICES)

ck("规范化：补协议", engine.normalize_url("bilibili.com/video/BV1xx") == "https://bilibili.com/video/BV1xx")
ck("规范化：保留路径与参数",
   engine.normalize_url("https://a.com/v?v=1") == "https://a.com/v?v=1")
ck("规范化：拒绝纯文本", engine.normalize_url("随便一段话") == "")
ck("规范化：拒绝空串", engine.normalize_url("  ") == "")

ck("选择器：1080P 限高", "height<=1080" in engine.format_selector("1080P", "mp4"))
ck("选择器：最高不限高", engine.format_selector("最高", "mp4").startswith("bestvideo*"))
ck("选择器：音频只要音轨", engine.format_selector("720P", "mp3").startswith("bestaudio"))

ck("错误翻译：403 → Cookie 提示",
   "Cookie" in engine._friendly_error(Exception("HTTP Error 403: Forbidden")))
ck("错误翻译：不支持站点",
   "不被支持" in engine._friendly_error(Exception("Unsupported URL: xyz")))
ck("错误翻译：网络中断",
   "网络" in engine._friendly_error(Exception("SSL: UNEXPECTED_EOF_WHILE_READING")))
ck("错误翻译：去掉 ERROR: 前缀",
   not engine._friendly_error(Exception("ERROR: boom")).startswith("ERROR"))

# =====================================================================
# B. 队列层
# =====================================================================
from download_manager import download_manager as dm  # noqa: E402


async def queue_checks():
    # 必然连接失败的本地地址：验证失败路径与可读错误
    tid = dm.add_task("http://127.0.0.1:9/nothing.mp4", "720P", "mp4")
    ck("任务入队返回 id", bool(tid))
    ck("任务初始为等待/准备态", dm.get_task(tid)["status"] in ("queued", "preparing"),
       dm.get_task(tid)["status"])

    deadline = time.time() + 40
    while time.time() < deadline:
        await asyncio.sleep(0.3)
        if dm.get_task(tid)["status"] in ("failed", "completed"):
            break
    task = dm.get_task(tid)
    ck("不可达链接任务失败", task["status"] == "failed", task["status"])
    ck("失败原因可读（非空且非堆栈）",
       bool(task["error"]) and "Traceback" not in task["error"], task["error"][:60])

    ck("重试可重新排队", dm.retry_task(tid) is True)
    ck("重试后回到等待态", dm.get_task(tid)["status"] == "queued")
    dm.remove_task(tid)
    ck("删除未开始任务成功", dm.get_task(tid) is None)

    # 参数修改（未开始任务生效）
    tid2 = dm.add_task("http://127.0.0.1:9/x", "720P", "mp4")
    ck("未开始任务可改参数", dm.update_task_config(tid2, "1080P", "mp3") is True)
    ck("参数已写入", (dm.get_task(tid2)["quality"], dm.get_task(tid2)["format"]) == ("1080P", "mp3"),
       dm.get_task(tid2)["quality"] + "/" + dm.get_task(tid2)["format"])
    dm.remove_task(tid2)
    ck("清空已完成返回整数", isinstance(dm.clear_completed(), int))

    snap = dm.list_tasks()
    ck("任务快照不含内部字段",
       all(not any(k.startswith("_") for k in t) for t in snap))

    ck("体积格式化", dm.format_file_size(1536) == "1.5 KB", dm.format_file_size(1536))
    ck("时长格式化", dm.format_duration(3725) == "1:02:05", dm.format_duration(3725))


asyncio.run(queue_checks())

# =====================================================================
# C. 界面层
# =====================================================================
from pages.download_page import (  # noqa: E402
    AUDIO_FORMATS, CHANNELS, FORMATS, QUALITIES, DownloadPage, TagCard, TaskCard,
)

ck("下载页画质档位来自引擎", QUALITIES is engine.QUALITY_CHOICES, str(QUALITIES))
ck("下载页格式档位来自引擎", FORMATS == engine.FORMAT_CHOICES, str(FORMATS))

page = DownloadPage()
ck("输入区默认画质在档位内", page.quality_select.currentText() in QUALITIES,
   page.quality_select.currentText())
ck("音频格式时画质切换为声道",
   (page.format_select.setCurrentText("mp3"),
    page._sync_input_quality(),
    page.quality_select.itemText(0) == CHANNELS[0])[2],
   page.quality_select.itemText(0))
page.format_select.setCurrentText("mp4")
page._sync_input_quality()

# 标签提交：有效链接成卡，无效行被忽略
page._commit_lines("https://example.com/v/1\n这不是链接\nhttps://example.com/v/2")
ck("有效链接生成 2 个标签", len(page._tag_cards) == 2, len(page._tag_cards))
ck("无效行被忽略并提示", "忽略" in page.tag_hint.text(), page.tag_hint.text()[:40])

# 右键菜单：画质档位与格式档位齐全（真实弹出 → 定时抓取 → 关闭）
card = page._tag_cards[0]
captured = {}


class _FakeEvent:
    def globalPos(self):
        return card.mapToGlobal(card.rect().center())


from PySide6.QtCore import QTimer  # noqa: E402


def _capture_menu():
    popup = app.activePopupWidget()
    if popup is None:
        captured["error"] = "菜单未弹出"
        return
    captured["submenus"] = [a.menu().title() for a in popup.actions() if a.menu()]
    captured["quality_items"] = [
        a.text() for a in popup.actions() if a.menu() and "质量" in a.menu().title()
        for a in a.menu().actions()
    ]
    captured["plain"] = [a.text() for a in popup.actions() if not a.menu() and a.text()]
    popup.close()


QTimer.singleShot(300, _capture_menu)
card.contextMenuEvent(_FakeEvent())

ck("右键菜单已弹出", "submenus" in captured, captured.get("error", ""))
if "submenus" in captured:
    ck("菜单含格式与质量两个子菜单", len(captured["submenus"]) >= 2, captured["submenus"])
    ck("质量子菜单含 5 档画质", captured["quality_items"] == QUALITIES,
       captured["quality_items"])
    ck("菜单含预览与删除",
       "预览" in captured["plain"] and "删除" in captured["plain"], captured["plain"])

# 任务卡：站点/时长/体积信息渲染
tcard = TaskCard("t1")
tcard.update_task({
    "id": "t1", "status": "completed", "progress": 100,
    "title": "示例视频", "extractor": "BiliBili", "duration": 245,
    "total_size": 5 * 1024 * 1024, "format": "mp4", "quality": "720P",
    "output_path": "", "error": "",
})
detail = tcard.detail_label.text()
ck("任务卡显示站点与时长", "BiliBili" in detail and "04:05" in detail, detail)
ck("任务卡显示体积", "5.0 MB" in detail, detail)

tcard.update_task({
    "id": "t1", "status": "failed", "progress": 0, "title": "x",
    "error": "站点拒绝访问（403）", "format": "mp4", "quality": "720P",
})
ck("失败任务卡显示错误原因", "403" in tcard.detail_label.text(), tcard.detail_label.text())

# 设置页：新增引擎与 Cookie 控件存在且可保存
from pages.settings_page import SettingsPage  # noqa: E402

sp = SettingsPage()
ck("设置页有播放列表上限控件", hasattr(sp, "playlist_limit"), sp.playlist_limit.value())
ck("设置页有 Cookie 浏览器来源", sp.cookie_browser.count() > 1, sp.cookie_browser.currentText())
collected = sp._collect_settings()
ck("保存设置包含 engine 段", "engine" in collected, list(collected.keys()))
ck("保存设置包含 playlist-limit",
   "playlist-limit" in collected.get("download-task", {}),
   collected.get("download-task", {}).get("playlist-limit"))

# =====================================================================
# D. 端到端（可跳过）
# =====================================================================
if os.environ.get("JIUDOWN_SKIP_NET") == "1":
    print("SKIP 端到端下载（JIUDOWN_SKIP_NET=1）")
else:
    URL = "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4"
    progress_seen = []

    async def e2e():
        tid = dm.add_task(URL, "360P", "mp4",
                          progress_callback=lambda i, t: progress_seen.append(t.get("progress", 0)))
        deadline = time.time() + 180
        while time.time() < deadline:
            await asyncio.sleep(0.4)
            if dm.get_task(tid)["status"] in ("completed", "failed"):
                break
        task = dm.get_task(tid)
        ck("端到端下载完成", task["status"] == "completed", f'{task["status"]} {task["error"][:60]}')
        ck("输出文件存在", bool(task["output_path"]) and os.path.exists(task["output_path"]),
           task["output_path"])
        ck("输出扩展名为 mp4", task["output_path"].endswith(".mp4"), task["output_path"][-12:])
        ck("记录了站点元数据", bool(task["extractor"]), task["extractor"])
        ck("进度回调被触发", len(progress_seen) > 0, len(progress_seen))
        ck("进度单调不减（允许 100 收尾）",
           all(b >= a - 0.01 for a, b in zip(progress_seen, progress_seen[1:])),
           f"{progress_seen[:5]}")
        if task["output_path"] and os.path.exists(task["output_path"]):
            os.remove(task["output_path"])

    asyncio.run(e2e())

print(f"\n===== {sum(checks)} passed, {len(checks) - sum(checks)} failed =====")
sys.stdout.flush()
os._exit(0 if all(checks) else 1)
