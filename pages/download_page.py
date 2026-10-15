"""
下载页
B站视频链接批量输入、清晰度/格式/保存目录设置、多任务进度卡片
"""

from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from loguru import logger

from config_manager import config_manager
from download_manager import download_manager
from theme import C

QUALITIES = ["360P", "480P", "720P", "1080P"]
FORMATS = ["mp4", "flv"]

STATUS_BADGE = {
    "queued": ("gray", "等待中"),
    "preparing": ("orange", "准备中"),
    "downloading": ("blue", "下载中"),
    "merging": ("cyan", "合并中"),
    "completed": ("green", "已完成"),
    "failed": ("red", "失败"),
    "cancelled": ("gray", "已取消"),
}

BADGE_COLORS = {
    "gray": (C["gray_bg"], C["gray_dark"]),
    "orange": (C["orange_bg"], C["orange_dark"]),
    "blue": (C["blue_bg"], C["blue_dark"]),
    "cyan": (C["cyan_bg"], C["cyan_dark"]),
    "green": (C["green_bg"], C["green_dark"]),
    "red": (C["red_bg"], C["red_dark"]),
}

PROGRESS_COLOR = {
    "completed": "green",
    "failed": "red",
    "merging": "orange",
}


class TaskCard(QFrame):
    """单个下载任务卡片"""

    def __init__(self, task_id: str, parent=None):
        super().__init__(parent)
        self.setProperty("cssClass", "card")
        self.task_id = task_id

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(16, 12, 16, 12)
        vbox.setSpacing(8)

        # 第一行：标题 + 徽章 + 质量
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title_label = QLabel("等待解析标题...")
        self.title_label.setProperty("cssClass", "taskTitle")
        self.title_label.setWordWrap(True)
        self.badge_label = QLabel("等待中")
        self.badge_label.setProperty("cssClass", "badge")
        self.quality_label = QLabel("")
        self.quality_label.setProperty("cssClass", "taskMeta")
        top.addWidget(self.title_label, 1)
        top.addWidget(self.quality_label)
        top.addWidget(self.badge_label)
        vbox.addLayout(top)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        vbox.addWidget(self.progress_bar)

        # 第二行：详情 + 操作按钮
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.detail_label = QLabel("")
        self.detail_label.setProperty("cssClass", "taskDetail")
        self.detail_label.setWordWrap(True)
        self.retry_button = QPushButton("重试")
        self.retry_button.setProperty("small", True)
        self.delete_button = QPushButton("删除")
        self.delete_button.setProperty("small", True)
        self.delete_button.setProperty("danger", True)
        self.open_button = QPushButton("打开文件夹")
        self.open_button.setProperty("small", True)
        bottom.addWidget(self.detail_label, 1)
        bottom.addWidget(self.retry_button)
        bottom.addWidget(self.delete_button)
        bottom.addWidget(self.open_button)
        vbox.addLayout(bottom)

    def _set_badge(self, tone: str, text: str) -> None:
        bg, fg = BADGE_COLORS.get(tone, BADGE_COLORS["gray"])
        self.badge_label.setText(text)
        self.badge_label.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 10px; padding: 2px 10px; font-size: 11px; font-weight: 600;"
        )

    def update_task(self, task: dict) -> None:
        self.title_label.setText(task.get("title") or "等待解析标题...")
        self.quality_label.setText(f"{task.get('quality', '')} · {task.get('format', '')}")

        status = task.get("status", "queued")
        tone, text = STATUS_BADGE.get(status, ("gray", status))
        self._set_badge(tone, text)

        progress = min(max(float(task.get("progress") or 0), 0), 100)
        self.progress_bar.setValue(int(progress * 10))
        color = PROGRESS_COLOR.get(status, "blue")
        self.progress_bar.setProperty("color", color)
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)

        if status == "downloading" and task.get("total_size"):
            downloaded = task.get("downloaded_size") or 0
            total = task.get("total_size") or 0
            speed = task.get("speed") or 0
            detail = f"{download_manager.format_file_size(downloaded)} / {download_manager.format_file_size(total)}"
            if speed:
                detail += f" | {download_manager.format_speed(speed)}"
            self.detail_label.setText(detail)
            self.detail_label.setStyleSheet(f"color: {C['text_secondary']};")
        elif status == "failed":
            self.detail_label.setText(task.get("error", ""))
            self.detail_label.setStyleSheet(f"color: {C['red_dark']};")
        else:
            self.detail_label.setText("")
            self.detail_label.setStyleSheet(f"color: {C['text_secondary']};")

        self.retry_button.setVisible(status == "failed")
        self.open_button.setVisible(
            status == "completed"
            and bool(task.get("output_path"))
            and Path(task["output_path"]).exists()
        )
        self.delete_button.setVisible(status not in ("preparing", "downloading", "merging"))


class DownloadPage(QWidget):
    """视频下载页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: dict[str, TaskCard] = {}
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_tasks)
        self._timer.start(1000)
        self._refresh_tasks()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ---- 输入区 ----
        input_card = QFrame()
        input_card.setProperty("cssClass", "card")
        input_vbox = QVBoxLayout(input_card)
        input_vbox.setContentsMargins(16, 14, 16, 14)
        input_vbox.setSpacing(10)

        input_title = QLabel("添加下载任务")
        input_title.setProperty("cssClass", "sectionTitle")
        input_vbox.addWidget(input_title)

        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText(
            "每行一个链接，例如：\nhttps://www.bilibili.com/video/BV..."
        )
        self.url_input.setMaximumHeight(86)
        input_vbox.addWidget(self.url_input)

        option_row = QHBoxLayout()
        option_row.setSpacing(10)

        self.quality_select = QComboBox()
        self.quality_select.addItems(QUALITIES)
        quality = config_manager.get_default_quality()
        if quality in QUALITIES:
            self.quality_select.setCurrentText(quality)
        self.quality_select.setMinimumWidth(100)
        option_row.addWidget(self.quality_select)

        self.format_select = QComboBox()
        self.format_select.addItems(FORMATS)
        fmt = config_manager.get_default_format()
        if fmt in FORMATS:
            self.format_select.setCurrentText(fmt)
        self.format_select.setMinimumWidth(90)
        option_row.addWidget(self.format_select)

        self.dir_input = QLineEdit()
        self.dir_input.setText(config_manager.get_download_dir())
        self.dir_input.setPlaceholderText("保存目录")
        browse_button = QPushButton("浏览")
        browse_button.clicked.connect(self._browse_dir)
        option_row.addWidget(self.dir_input, 1)
        option_row.addWidget(browse_button)
        input_vbox.addLayout(option_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.concurrent_label = QLabel(
            f"当前最大并发: {config_manager.get_max_task()}，可在设置中调整"
        )
        self.concurrent_label.setProperty("muted", True)
        add_button = QPushButton("添加下载")
        add_button.setProperty("primary", True)
        add_button.clicked.connect(self._add_tasks)
        clear_button = QPushButton("清空已完成")
        clear_button.clicked.connect(self._clear_completed)
        action_row.addWidget(self.concurrent_label, 1)
        action_row.addWidget(clear_button)
        action_row.addWidget(add_button)
        input_vbox.addLayout(action_row)
        layout.addWidget(input_card)

        # ---- 任务列表 ----
        self.empty_label = QLabel("暂无下载任务")
        self.empty_label.setProperty("muted", True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        list_host = QWidget()
        list_host.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch()
        self.scroll_area.setWidget(list_host)
        layout.addWidget(self.scroll_area, 1)

    # ---------------------------------------------------------------- 动作

    def _browse_dir(self) -> None:
        start = self.dir_input.text() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "选择保存目录", start)
        if selected:
            self.dir_input.setText(selected)

    def _add_tasks(self) -> None:
        text = self.url_input.toPlainText()
        urls = [line.strip() for line in text.splitlines() if line.strip()]
        if not urls:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "提示", "请输入B站视频链接")
            return

        config_manager.set_config("download_dir", self.dir_input.text())
        config_manager.save_config()
        quality = self.quality_select.currentText()
        file_format = self.format_select.currentText()
        for url in urls:
            download_manager.add_task(url, quality, file_format)
        self.url_input.clear()
        self.concurrent_label.setText(
            f"当前最大并发: {config_manager.get_max_task()}，可在设置中调整"
        )
        self._refresh_tasks()

    def _retry_task(self, task_id: str) -> None:
        if download_manager.retry_task(task_id):
            self._refresh_tasks()
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "提示", "该任务当前无法重试")

    def _delete_task(self, task_id: str) -> None:
        if download_manager.remove_task(task_id):
            card = self._cards.pop(task_id, None)
            if card is not None:
                self.list_layout.removeWidget(card)
                card.deleteLater()
            self._refresh_tasks()
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "提示", "下载中的任务暂不能删除")

    def _clear_completed(self) -> None:
        count = download_manager.clear_completed()
        if count:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "提示", f"已清空 {count} 个任务")
        self._refresh_tasks()

    def _open_folder(self, task_id: str) -> None:
        task = download_manager.get_task(task_id) or {}
        output_path = task.get("output_path", "")
        if not output_path or not Path(output_path).exists():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "提示", "文件尚未生成")
            return
        folder = str(Path(output_path).parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # ---------------------------------------------------------------- 刷新

    def _upsert_card(self, task: dict) -> None:
        task_id = task["id"]
        card = self._cards.get(task_id)
        if card is None:
            card = TaskCard(task_id)
            card.retry_button.clicked.connect(lambda: self._retry_task(task_id))
            card.delete_button.clicked.connect(lambda: self._delete_task(task_id))
            card.open_button.clicked.connect(lambda: self._open_folder(task_id))
            self._cards[task_id] = card
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)
        card.setVisible(True)
        card.update_task(task)

    def _refresh_tasks(self) -> None:
        seen = set()
        for task in download_manager.list_tasks():
            seen.add(task["id"])
            self._upsert_card(task)
        for task_id in list(self._cards):
            if task_id not in seen:
                card = self._cards.pop(task_id)
                self.list_layout.removeWidget(card)
                card.deleteLater()
        self.empty_label.setVisible(not self._cards)
