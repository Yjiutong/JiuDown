# -*- coding: utf-8 -*-
"""截图自检：把主窗口每个页面与侧栏两态各出一张 PNG

必须用 windows 平台跑：offscreen 平台的字体数据库是空的（0 个字族），
中文全部渲染成方框，看不出真实排版。窗口会短暂出现在桌面上。

用法（仓库根）：runtime\\python\\python.exe tools\\verify\\verify_ui_screens.py
产物：TEMP/ui_screens/*.png（下载目录之外的本地调试目录，可随时清空）
"""
import os
import sys
import pathlib

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from download_manager import download_manager

OUT = ROOT / "TEMP" / "ui_screens"
OUT.mkdir(parents=True, exist_ok=True)


def seed_demo(window) -> None:
    """塞几条假任务 / 链接卡，让记录行、进度、状态标签在截图里现形

    只写内存里的任务表，不启动任何下载；产物只进 TEMP/ui_screens。
    """
    import time

    from download_manager import download_manager
    from pages.download_page import TagCard

    page = window._stack.widget(0)
    now = time.time()
    demo = [
        {"status": "downloading", "progress": 42.0, "speed": 3_145_728,
         "downloaded_size": 66_000_000, "total_size": 156_000_000,
         "title": "示例：深夜的调度室", "extractor": "bilibili", "duration": 312},
        {"status": "queued", "progress": 0.0, "title": "示例：等待中的第二条",
         "extractor": "youtube"},
        {"status": "completed", "progress": 100.0, "total_size": 48_900_000,
         "title": "示例：已经下完的一集", "extractor": "douyin"},
        {"status": "failed", "progress": 12.0, "title": "示例：取流失败",
         "error": "该链接需要登录 Cookie 才能取到对应档位"},
    ]
    for index, fields in enumerate(demo):
        task_id = f"demo{index}"
        task = {
            "id": task_id, "url": f"https://example.com/v/{index}",
            "quality": "1080P", "format": "mp4", "levels": [],
            "created_at": now - index * 60,
        }
        task.update(fields)
        download_manager.tasks[task_id] = task

    for index, name in enumerate(("示例：图文九张", "示例：还在解析的链接")):
        card = TagCard(f"https://example.com/n/{index}", "1080P", "mp4")
        card.title_label.setText(name)
        card.detail_label.setText("1080P │ 720P │ 480P")
        page._tag_cards.append(card)
        page.tag_layout.insertWidget(page.tag_layout.count() - 1, card)
    page._renumber_tags()
    page._refresh_tasks()


def pump(ms: int = 300) -> None:
    """跑掉事件循环若干毫秒，让遮罩、动画、布局都落到最终状态"""
    import time

    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def main() -> int:
    global app
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)

    from theme import theme_manager

    import app as app_module

    app_module.initialize_config()

    from main_window import MainWindow

    window = MainWindow()
    window.resize(1280, 1000)
    window.show()
    pump(600)
    seed_demo(window)
    pump(320)

    names = ["download", "settings"]
    for theme_name in ("light",):
        theme_manager.set_mode(theme_name, persist=False)
        pump(320)
        for index, name in enumerate(names):
            window._switch_page(index)
            pump(320)
            if name == "download":
                # 任务列表会跟着进度自动滚到底：截图前回滚到顶，好核对整行版式
                window._stack.widget(0).page_scroll.verticalScrollBar().setValue(0)
                pump(120)
            path = OUT / f"{theme_name}-{name}.png"
            window.grab().save(str(path))
            print(f"[ok] {path}")
        # 设置页里的三个分段（状态总览 / 运行日志 / 设置）
        page = window._stack.widget(1)
        for tab in range(3):
            page.tabs.setCurrentIndex(tab)
            pump(260)
            path = OUT / f"{theme_name}-settings-tab{tab}.png"
            window.grab().save(str(path))
            print(f"[ok] {path}")

        # 预览面板单独出图：核对白底播放控件
        from pages.preview_panel import PreviewPanel

        panel = PreviewPanel()
        panel.resize(760, 460)
        panel.show()
        pump(360)
        path = OUT / f"{theme_name}-preview.png"
        panel.grab().save(str(path))
        print(f"[ok] {path}")
        panel._player.stop()
        panel.close()
        panel.deleteLater()
        pump(120)

        # 悬停低清小窗：核对白底浮层
        from pages.hover_preview import HoverPreview

        hover = HoverPreview()
        hover.caption_title.setFullText("示例：深夜的调度室")
        hover._show_msg("正在加载低清预览…")
        hover.show()
        pump(260)
        path = OUT / f"{theme_name}-hover.png"
        hover.grab().save(str(path))
        print(f"[ok] {path}")
        hover._player.stop()
        hover.close()
        hover.deleteLater()
        pump(120)
    # 侧栏展开 / 收起两态：核对导航行高与图标位置一致
    window._switch_page(0)
    for collapsed, state in ((False, "expanded"), (True, "collapsed")):
        if window._collapsed != collapsed:
            window._toggle_sidebar()
            pump(520)
        path = OUT / f"light-sidebar-{state}.png"
        window.grab().save(str(path))
        print(f"[ok] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
