"""
视频下载页面UI模块
负责B站视频链接批量输入、清晰度选择、保存目录设置和多任务进度展示
"""

import os
import platform
import subprocess
from pathlib import Path

from nicegui import ui

from config_manager import config_manager
from download_manager import download_manager
from utils import create_file_browser_button


def _status_label(status: str) -> str:
    return download_manager.STATUS_LABELS.get(status, status)


def _open_output_dir(path: str) -> None:
    if not path or not Path(path).exists():
        ui.notify("文件尚未生成", type="warning")
        return
    folder = Path(path).parent
    try:
        if platform.system() == "Windows":
            os.startfile(str(folder))
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as e:
        ui.notify(f"打开文件夹失败: {e}", type="negative")


def create_download_page():
    """创建下载页面UI组件"""
    ui.label("视频下载").classes("page-heading mb-4")

    url_input = ui.textarea(
        label="B站视频链接",
        placeholder="每行一个链接，例如：\nhttps://www.bilibili.com/video/BV...",
    ).classes("w-full mb-2").props("rows=3")

    with ui.row().classes("w-full items-center gap-2"):
        quality_select = ui.select(
            ["360P", "480P", "720P", "1080P"],
            value=config_manager.get_default_quality(),
            label="清晰度",
        ).style("min-width: 120px")

        format_select = ui.select(
            ["mp4", "flv"],
            value=config_manager.get_default_format(),
            label="格式",
        ).style("min-width: 100px")

        download_dir_input = ui.input(
            label="保存目录",
            value=config_manager.get_download_dir(),
        ).classes("flex-grow")

        ui.button("浏览", on_click=create_file_browser_button(download_dir_input, "选择保存目录")).props("flat")

    with ui.row().classes("w-full items-center gap-2 mt-2"):
        concurrent_label = ui.label(
            f"当前最大并发：{config_manager.get_max_task()}，可在设置中调整"
        ).classes("text-sm text-gray-600 flex-grow")
        ui.button("添加下载", icon="playlist_add", on_click=lambda: add_tasks()).props("color=primary")
        ui.button("清空已完成", icon="clear_all", on_click=lambda: clear_completed()).props("flat")

    empty_label = ui.label("暂无下载任务").classes("muted-text mt-4")
    task_container = ui.column().classes("w-full mt-4")
    rows = {}

    def add_tasks():
        lines = [(line or "").strip() for line in (url_input.value or "").splitlines()]
        urls = [line for line in lines if line]
        if not urls:
            ui.notify("请输入B站视频链接", type="warning")
            return

        config_manager.set_config("download_dir", download_dir_input.value)
        config_manager.save_config()
        quality = quality_select.value
        file_format = format_select.value
        for url in urls:
            download_manager.add_task(url, quality, file_format)
        url_input.value = ""
        concurrent_label.set_text(
            f"当前最大并发：{config_manager.get_max_task()}，可在设置中调整"
        )
        ui.notify(f"已添加 {len(urls)} 个任务", type="positive")
        refresh_tasks()

    def retry_task(task_id: str):
        if download_manager.retry_task(task_id):
            ui.notify("任务已重新加入队列", type="positive")
        else:
            ui.notify("该任务当前无法重试", type="warning")
        refresh_tasks()

    def delete_task(task_id: str):
        if download_manager.remove_task(task_id):
            row = rows.pop(task_id, None)
            if row:
                row["card"].delete()
            ui.notify("任务已删除", type="positive")
            refresh_tasks()
        else:
            ui.notify("下载中的任务暂不能删除", type="warning")

    def clear_completed():
        count = download_manager.clear_completed()
        if count:
            ui.notify(f"已清空 {count} 个任务", type="positive")
        refresh_tasks()

    def upsert_task_row(task_id: str, task: dict):
        row = rows.get(task_id)
        if row is None:
            with task_container:
                card = ui.card().classes("download-task-card w-full mb-3 p-0")
            with card:
                with ui.row().classes("w-full items-center justify-between gap-2"):
                    with ui.column().classes("flex-grow min-w-0"):
                        title_label = ui.label(
                            task.get("title") or "等待解析标题..."
                        ).classes("font-bold").style("word-break: break-all")
                        status_label = ui.label("").classes("text-xs")
                    quality_label = ui.label("").classes("text-xs text-gray-500")
                progress_bar = ui.linear_progress(value=0).classes("w-full mt-2")
                detail_label = ui.label("").classes("text-xs text-gray-600 mt-1")
                message_label = ui.label("").classes("text-xs text-gray-500 mt-1")
                with ui.row().classes("w-full items-center gap-1 mt-2"):
                    retry_button = ui.button(
                        "重试",
                        icon="refresh",
                        on_click=lambda tid=task_id: retry_task(tid),
                    ).props("flat dense").classes("text-xs")
                    delete_button = ui.button(
                        "删除",
                        icon="delete",
                        on_click=lambda tid=task_id: delete_task(tid),
                    ).props("flat dense").classes("text-xs")
                    open_button = ui.button(
                        "打开文件夹",
                        icon="folder_open",
                        on_click=lambda tid=task_id: _open_output_dir(
                            (download_manager.get_task(tid) or {}).get("output_path", "")
                        ),
                    ).props("flat dense").classes("text-xs")
            rows[task_id] = {
                "card": card,
                "title_label": title_label,
                "status_label": status_label,
                "quality_label": quality_label,
                "progress_bar": progress_bar,
                "detail_label": detail_label,
                "message_label": message_label,
                "retry_button": retry_button,
                "delete_button": delete_button,
                "open_button": open_button,
            }

        row = rows[task_id]
        row["card"].set_visibility(True)
        row["title_label"].set_text(task.get("title") or "等待解析标题...")
        row["quality_label"].set_text(
            f"{task.get('quality', '')} · {task.get('format', '')}"
        )
        row["message_label"].set_text(task.get("message", ""))

        status = task.get("status", "queued")
        row["status_label"].set_text(_status_label(status))
        status_colors = {
            "completed": "#2e7d32",
            "failed": "#c62828",
        }
        row["status_label"].style(
            f"color: {status_colors.get(status, '#1976d2')}; font-weight: 600"
        )

        progress = min(max(float(task.get("progress") or 0), 0), 100) / 100
        row["progress_bar"].value = progress

        if status == "downloading" and task.get("total_size"):
            downloaded = task.get("downloaded_size") or 0
            total = task.get("total_size") or 0
            speed = task.get("speed") or 0
            detail = f"{download_manager.format_file_size(downloaded)} / {download_manager.format_file_size(total)}"
            if speed:
                detail += f" | {download_manager.format_speed(speed)}"
            row["detail_label"].set_text(detail).style("color: #37474f")
        elif status == "failed":
            row["detail_label"].set_text(task.get("error", "")).style("color: #c62828")
        else:
            row["detail_label"].set_text("")

        row["retry_button"].set_visibility(status == "failed")
        row["open_button"].set_visibility(
            status == "completed" and bool(task.get("output_path")) and Path(task["output_path"]).exists()
        )
        row["delete_button"].set_visibility(status not in ("preparing", "downloading", "merging"))

    def refresh_tasks():
        seen = set()
        for task in download_manager.list_tasks():
            seen.add(task["id"])
            upsert_task_row(task["id"], task)
        for task_id in list(rows):
            if task_id not in seen:
                rows[task_id]["card"].delete()
                rows.pop(task_id, None)
        empty_label.set_visibility(not rows)

    ui.timer(1.0, refresh_tasks)
    refresh_tasks()
