"""
日志页
核心运行日志（彩色分级）与下载记录展示，提供开始/停止核心、清空日志操作
"""

import html as html_mod

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from loguru import logger

from config_manager import config_manager
from core_manager import core_manager
from core_status import get_core_status, update_core_status
from download_manager import download_log_manager
from log_manager import log_manager
from system_info import system_info
from theme import C

LEVEL_COLORS = {
    "error": "#f87171",
    "fata": "#fca5a5",
    "warning": "#fbbf24",
    "success": "#4ade80",
    "info": "#39C5BB",
    "debug": "#9bb0b2",
}

MAX_LOG_BLOCKS = 5000
MAX_DL_BLOCKS = 2000


class _LogBridge(QObject):
    """跨线程信号桥：核心日志回调发生在核心输出读取线程"""
    new_log = Signal(str, str)  # line, level


class LogPage(QWidget):
    """运行日志页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bridge = _LogBridge()
        self._bridge.new_log.connect(self._append_core_log)

        self._build_ui()
        self._last_dl_count = 0
        self._restore_history()

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_button_states)
        self._status_timer.start(2000)

        self._dl_timer = QTimer(self)
        self._dl_timer.timeout.connect(self._refresh_download_logs)
        self._dl_timer.start(1000)
        self._refresh_download_logs()

        core_manager.add_log_callback(self._on_core_log)

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        info_row = QHBoxLayout()
        info_row.setSpacing(24)
        self._core_file_label = QLabel(f"核心文件: {system_info.get_core_filename()}")
        self._core_file_label.setProperty("muted", True)
        self._config_file_label = QLabel(f"配置文件: {config_manager.get_config_file_path()}")
        self._config_file_label.setProperty("muted", True)
        info_row.addWidget(self._core_file_label)
        info_row.addWidget(self._config_file_label, 1)
        layout.addLayout(info_row)

        # 控制区
        control = QHBoxLayout()
        control.setSpacing(10)
        self._start_button = QPushButton("开始运行")
        self._start_button.setProperty("primary", True)
        self._start_button.clicked.connect(self._run_core)
        self._stop_button = QPushButton("停止运行")
        self._stop_button.setProperty("danger", True)
        self._stop_button.clicked.connect(self._stop_core)
        self._clear_button = QPushButton("清空日志")
        self._clear_button.clicked.connect(self._clear_logs)
        self._status_label = QLabel("核心状态: 检测中...")
        self._status_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        control.addWidget(self._start_button)
        control.addWidget(self._stop_button)
        control.addWidget(self._clear_button)
        control.addStretch()
        control.addWidget(self._status_label)
        layout.addLayout(control)

        # 核心日志面板
        self._log_view = QTextEdit()
        self._log_view.setProperty("cssClass", "logPanel")
        self._log_view.setReadOnly(True)
        self._log_view.document().setMaximumBlockCount(MAX_LOG_BLOCKS)
        layout.addWidget(self._log_view, 1)

        # 下载记录
        dl_title = QLabel("下载记录")
        dl_title.setProperty("sectionHeader", True)
        layout.addWidget(dl_title)

        self._dl_view = QTextEdit()
        self._dl_view.setProperty("cssClass", "dlLogPanel")
        self._dl_view.setReadOnly(True)
        self._dl_view.setMaximumHeight(180)
        self._dl_view.document().setMaximumBlockCount(MAX_DL_BLOCKS)
        layout.addWidget(self._dl_view)

    # ---------------------------------------------------------------- 日志

    def _on_core_log(self, line: str, level: str) -> None:
        """核心输出读取线程回调 -> 信号切回 UI 线程"""
        self._bridge.new_log.emit(line, level)

    def _append_core_log(self, line: str, level: str) -> None:
        color = LEVEL_COLORS.get(level.lower(), C["log_text"])
        self._append_colored(self._log_view, line, color)
        try:
            log_manager.save_log(line.strip())
        except Exception as e:
            logger.error(f"保存日志失败: {e}")

    @staticmethod
    def _append_colored(view: QTextEdit, line: str, color: str) -> None:
        cursor = view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(
            f'<span style="color:{color};">{html_mod.escape(line)}</span><br/>'
        )
        view.setTextCursor(cursor)
        view.ensureCursorVisible()

    def _restore_history(self) -> None:
        """页面打开时恢复历史核心日志"""
        try:
            previous = log_manager.load_logs()
            if previous:
                for log_line in previous:
                    self._append_core_log(log_line, "debug")
            else:
                self._append_core_log("日志页面已打开", "info")
                self._append_core_log(f"核心文件: {system_info.get_core_filename()}", "info")
                self._append_core_log("点击「开始运行」启动核心", "info")
        except Exception as e:
            logger.error(f"加载历史日志失败: {e}")
            self._append_core_log(f"加载历史日志失败: {e}", "error")

    def _refresh_download_logs(self) -> None:
        try:
            logs = download_log_manager.load_logs()
            count = len(logs)
            if count > self._last_dl_count:
                for log_line in logs[self._last_dl_count:]:
                    self._append_colored(self._dl_view, log_line, C["blue_dark"])
                self._last_dl_count = count
            elif count < self._last_dl_count:
                self._last_dl_count = count
        except Exception as e:
            logger.error(f"加载下载记录失败: {e}")

    # ---------------------------------------------------------------- 操作

    def _update_button_states(self) -> None:
        update_core_status()
        status = get_core_status()
        running = status.get("is_running", False)
        self._start_button.setEnabled(not running)
        self._stop_button.setEnabled(running)
        if running:
            self._status_label.setText("核心状态: 正在运行")
            self._status_label.setStyleSheet(
                f"color: {C['green_dark']}; font-size: 13px; font-weight: 600;"
            )
        else:
            self._status_label.setText("核心状态: 已停止")
            self._status_label.setStyleSheet(
                f"color: {C['red_dark']}; font-size: 13px; font-weight: 600;"
            )

    def _run_core(self) -> None:
        self._append_core_log("正在启动核心...", "info")
        self._status_label.setText("核心状态: 正在启动...")
        self._status_label.setStyleSheet(
            f"color: {C['orange_dark']}; font-size: 13px; font-weight: 600;"
        )
        self._start_button.setEnabled(False)

        try:
            success = core_manager.start_core(str(config_manager.get_config_file_path()))
            if success:
                self._append_core_log("核心启动成功！", "success")
                update_core_status()
                self._update_button_states()
            else:
                self._append_core_log("核心启动失败", "error")
                update_core_status()
                self._update_button_states()
        except Exception as e:
            self._append_core_log(f"启动核心失败: {e}", "error")
            update_core_status()
            self._update_button_states()

    def _stop_core(self) -> None:
        self._append_core_log("正在停止核心...", "info")
        self._status_label.setText("核心状态: 正在停止...")
        self._status_label.setStyleSheet(
            f"color: {C['orange_dark']}; font-size: 13px; font-weight: 600;"
        )
        self._stop_button.setEnabled(False)

        try:
            success = core_manager.stop_core()
            if success:
                self._append_core_log("核心已停止", "info")
                update_core_status()
                self._update_button_states()
            else:
                self._append_core_log("停止核心失败", "error")
                update_core_status()
                self._update_button_states()
        except Exception as e:
            self._append_core_log(f"停止核心失败: {e}", "error")
            update_core_status()
            self._update_button_states()

    def _clear_logs(self) -> None:
        try:
            if log_manager.clear_logs():
                self._log_view.clear()
                self._append_core_log("日志已清空", "info")
            else:
                self._append_core_log("清空日志失败", "error")
        except Exception as e:
            self._append_core_log(f"清空日志失败: {e}", "error")
