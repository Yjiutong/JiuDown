"""
运行日志页
引擎运行日志（彩色分级）+ 下载记录展示，提供清空面板与打开日志目录操作

日志来源：模块级 loguru sink 把日志写入一个线程安全的环形缓冲，页面用定时器
增量读取渲染。这样日志采集与 Qt 对象生命周期完全解耦——页面被销毁/重建都不会
留下悬空回调（早期版本直接把 sink 接进 Qt 信号，控件析构时会段错误）。
"""

import collections
import html as html_mod
import threading
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from loguru import logger

import jiudown_engine
from config_manager import config_manager

LEVEL_COLORS = {
    "error": "#FF453A",
    "critical": "#FF453A",
    "warning": "#FF9F0A",
    "success": "#30D158",
    "info": "#6E6E73",
    "debug": "#8E8E93",
}

MAX_LOG_BLOCKS = 5000
MAX_DL_BLOCKS = 2000
_BUFFER_LIMIT = 5000

# ---- 模块级日志环形缓冲（无 Qt 依赖，可在任意线程写入） ----
_LOG_BUFFER: collections.deque = collections.deque(maxlen=_BUFFER_LIMIT)
_BUFFER_LOCK = threading.Lock()
_SINK_ID = None


def _ensure_sink() -> None:
    """注册一次全局 loguru sink（INFO 以上，避免调试噪声刷屏）"""
    global _SINK_ID
    if _SINK_ID is not None:
        return

    def sink(message) -> None:  # loguru 在写入线程内调用
        try:
            record = message.record
            level = str(record["level"].name).lower()
            line = (
                f"{record['time'].strftime('%H:%M:%S')} | "
                f"{level.upper():<7} | {record['message']}"
            )
        except Exception:
            return
        with _BUFFER_LOCK:
            _LOG_BUFFER.append((line, level))

    try:
        _SINK_ID = logger.add(sink, level="INFO", format="{message}", enqueue=False)
    except Exception:
        _SINK_ID = None


def snapshot_buffer() -> list[tuple[str, str]]:
    """当前缓冲快照（供页面增量渲染）"""
    with _BUFFER_LOCK:
        return list(_LOG_BUFFER)


def _latest_log_file() -> Path | None:
    """最近一个 loguru 日志文件（logs/JiuDown_YYYY-MM-DD.log）"""
    try:
        files = sorted(Path("logs").glob("JiuDown_*.log"))
        return files[-1] if files else None
    except Exception:
        return None


class LogPage(QWidget):
    """运行日志页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        _ensure_sink()
        self._build_ui()
        self._last_dl_count = 0
        self._restored = False          # 历史日志延迟到首次显示时加载（避免拖慢启动）
        self._rendered = 0              # 已渲染的缓冲条数

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def showEvent(self, event) -> None:
        """首次显示时才恢复历史日志（整段批量插入，毫秒级）"""
        super().showEvent(event)
        if not self._restored:
            self._restore_history()
            self._refresh_download_logs()
            self._drain_buffer()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        info_row = QHBoxLayout()
        info_row.setSpacing(24)
        version = jiudown_engine.version() or "未安装"
        self._engine_label = QLabel(f"下载引擎: yt-dlp {version}")
        self._engine_label.setProperty("muted", True)
        self._config_file_label = QLabel(f"配置文件: {config_manager.get_config_file_path()}")
        self._config_file_label.setProperty("muted", True)
        info_row.addWidget(self._engine_label)
        info_row.addWidget(self._config_file_label, 1)
        layout.addLayout(info_row)

        # 控制区
        control = QHBoxLayout()
        control.setSpacing(10)
        self._clear_button = QPushButton("清空面板")
        self._clear_button.clicked.connect(self._clear_panel)
        self._open_dir_button = QPushButton("打开日志目录")
        self._open_dir_button.clicked.connect(self._open_log_dir)
        self._status_label = QLabel("引擎状态: 检测中…")
        self._status_label.setProperty("cssClass", "statusLabel")
        control.addWidget(self._clear_button)
        control.addWidget(self._open_dir_button)
        control.addStretch()
        control.addWidget(self._status_label)
        layout.addLayout(control)

        # 引擎日志面板
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

        self._refresh_engine_state()

    def _refresh_engine_state(self) -> None:
        if jiudown_engine.available():
            self._status_label.setText(
                f"引擎状态: 就绪（{jiudown_engine.version() or '未知版本'}）"
            )
            self._status_label.setProperty("tone", "green")
        else:
            self._status_label.setText("引擎状态: 未安装（下载不可用）")
            self._status_label.setProperty("tone", "red")
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

    # ---------------------------------------------------------------- 渲染

    def _append_log(self, line: str, level: str, color: str | None = None) -> None:
        self._append_colored(
            self._log_view, line, color or LEVEL_COLORS.get(level.lower(), "#86868B")
        )

    @staticmethod
    def _append_colored(view: QTextEdit, line: str, color: str) -> None:
        cursor = view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(
            f'<span style="color:{color};">{html_mod.escape(line)}</span><br/>'
        )
        view.setTextCursor(cursor)
        view.ensureCursorVisible()

    def _drain_buffer(self) -> None:
        """增量渲染新日志（一次 insertHtml 批量插入，避免逐行卡顿）"""
        items = snapshot_buffer()
        total = len(items)
        if total <= self._rendered:
            # 缓冲被清空/回绕：重置游标
            if total < self._rendered:
                self._rendered = total
            return
        fresh = items[self._rendered:]
        self._rendered = total
        if not fresh:
            return
        html = "".join(
            f'<span style="color:{LEVEL_COLORS.get(level, "#86868B")};">'
            f"{html_mod.escape(line)}</span><br/>"
            for line, level in fresh
        )
        cursor = self._log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(html)
        self._log_view.setTextCursor(cursor)
        self._log_view.ensureCursorVisible()

    def _restore_history(self) -> None:
        """首次显示时回填最近一个日志文件（整段批量插入）"""
        self._restored = True
        try:
            path = _latest_log_file()
            if not path:
                self._append_log("日志面板已就绪，引擎运行日志将实时显示在这里", "info")
                return
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
            if not lines:
                self._append_log("日志面板已就绪，引擎运行日志将实时显示在这里", "info")
                return
            color = LEVEL_COLORS["debug"]
            html = "".join(
                f'<span style="color:{color};">{html_mod.escape(line)}</span><br/>'
                for line in lines
            )
            cursor = self._log_view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertHtml(html)
            self._log_view.setTextCursor(cursor)
            self._log_view.ensureCursorVisible()
        except Exception as e:
            self._append_log(f"加载历史日志失败: {e}", "error")

    def _refresh_download_logs(self) -> None:
        from download_manager import download_log_manager

        try:
            logs = download_log_manager.load_logs()
            count = len(logs)
            if count > self._last_dl_count:
                for log_line in logs[self._last_dl_count:]:
                    self._append_colored(self._dl_view, log_line, "#007AFF")
                self._last_dl_count = count
            elif count < self._last_dl_count:
                self._last_dl_count = count
        except Exception as e:
            logger.debug(f"加载下载记录失败: {e}")

    def _tick(self) -> None:
        if not self.isVisible():
            return
        self._drain_buffer()
        self._refresh_download_logs()

    # ---------------------------------------------------------------- 操作

    def refresh_theme(self) -> None:
        """主题切换回调：重放状态标签内联颜色（日志面板为常驻深色控制台，不随主题反色）"""
        self._refresh_engine_state()

    def _open_log_dir(self) -> None:
        try:
            log_dir = Path("logs").resolve()
            log_dir.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))
        except Exception as e:
            logger.error(f"打开日志目录失败: {e}")

    def _clear_panel(self) -> None:
        """仅清空面板显示（磁盘日志保留，便于事后排查）"""
        self._log_view.clear()
        self._rendered = len(snapshot_buffer())
        self._dl_view.clear()
        self._last_dl_count = 0
        self._append_log("面板已清空（磁盘日志文件仍保留，可在日志目录查看）", "info")
