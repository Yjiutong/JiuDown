"""
主页（状态总览）
显示核心运行状态、核心文件完整性、FFmpeg、系统环境，
支持核心文件下载/更新与进度展示
"""

import html as html_mod
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QProgressBar, QVBoxLayout, QWidget,
)

from loguru import logger

from config_manager import config_manager
from core_manager import core_manager
from core_status import get_core_status, update_core_status
from system_info import system_info
from async_bridge import async_bridge
from theme import C

CORE_BASE_URL = "https://jj.紫灵.top/PC/ReWPF/core/"


class _HomeBridge(QObject):
    """跨线程信号桥：core_manager 的异步下载回调发生在 asyncio 后台线程"""
    progress = Signal(str, dict)     # task_id, task_info
    finished = Signal(bool, str)     # success, message


class HomePage(QWidget):
    """状态总览页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bridge = _HomeBridge()
        self._bridge.progress.connect(self._on_progress)
        self._bridge.finished.connect(self._on_finished)
        self._downloading = False
        self._core_filename = system_info.get_core_filename()
        self._hash_result = {}

        self._build_ui()
        self._load_initial_state()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_core_status)
        self._timer.start(5000)

    # ---------------------------------------------------------------- UI

    def _make_status_card(self, title: str) -> tuple[QFrame, QLabel, QLabel]:
        """创建状态卡片，返回 (卡片, 主值标签, 副值标签)"""
        frame = QFrame()
        frame.setProperty("cssClass", "card")
        vbox = QVBoxLayout(frame)
        vbox.setContentsMargins(16, 14, 16, 14)
        vbox.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        title_label = QLabel(title)
        title_label.setProperty("cssClass", "cardTitle")
        top.addWidget(title_label)
        top.addStretch()

        value_label = QLabel("—")
        value_label.setProperty("cssClass", "cardValue")
        value_label.setWordWrap(True)
        sub_label = QLabel("")
        sub_label.setProperty("cssClass", "cardSub")
        sub_label.setWordWrap(True)

        vbox.addLayout(top)
        vbox.addWidget(value_label)
        vbox.addWidget(sub_label)
        vbox.addStretch()
        return frame, value_label, sub_label

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # ---- 状态卡片行 ----
        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)

        self._running_card, self._running_value, _ = self._make_status_card("核心运行")
        self._file_card, self._file_value, self._file_sub = self._make_status_card("核心文件")
        self._file_value.setProperty("cssClass", "cardValueSmall")
        self._ffmpeg_card, self._ffmpeg_value, self._ffmpeg_sub = self._make_status_card("FFmpeg")
        self._ffmpeg_value.setProperty("cssClass", "cardValueSmall")
        self._system_card, self._system_value, self._system_sub = self._make_status_card("系统环境")
        self._system_value.setProperty("cssClass", "cardValueSmall")

        for card in (self._running_card, self._file_card, self._ffmpeg_card, self._system_card):
            cards_row.addWidget(card, 1)
        layout.addLayout(cards_row)

        # ---- 完整性验证卡片 ----
        self._hash_card = QFrame()
        self._hash_card.setProperty("cssClass", "card")
        hash_vbox = QVBoxLayout(self._hash_card)
        hash_vbox.setContentsMargins(16, 14, 16, 14)
        hash_vbox.setSpacing(8)

        hash_top = QHBoxLayout()
        hash_top.setSpacing(8)
        verify_title = QLabel("完整性验证")
        verify_title.setProperty("cssClass", "sectionTitle")
        self._hash_badge = QLabel("检测中")
        self._hash_badge.setProperty("cssClass", "badge")
        self._hash_badge.setProperty("badge", "gray")
        hash_top.addWidget(verify_title)
        hash_top.addWidget(self._hash_badge)
        hash_top.addStretch()
        hash_vbox.addLayout(hash_top)

        self._official_hash_label = QLabel("官方 Hash: —")
        self._official_hash_label.setStyleSheet(
            f"font-family: 'Cascadia Code','Consolas',monospace; font-size: 12px; color: {C['text_secondary']};"
        )
        self._local_hash_label = QLabel("本地 Hash: —")
        self._local_hash_label.setStyleSheet(
            f"font-family: 'Cascadia Code','Consolas',monospace; font-size: 12px; color: {C['text_secondary']};"
        )
        self._hash_message = QLabel("")
        self._hash_message.setProperty("cssClass", "cardSub")
        hash_vbox.addWidget(self._official_hash_label)
        hash_vbox.addWidget(self._local_hash_label)
        hash_vbox.addWidget(self._hash_message)
        layout.addWidget(self._hash_card)

        # ---- 操作区 ----
        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self._action_button = QPushButton("下载核心文件")
        self._action_button.setProperty("primary", True)
        self._action_button.clicked.connect(self._start_core_download)
        self._refresh_button = QPushButton("检查更新")
        self._refresh_button.clicked.connect(self._reload_state)
        action_row.addWidget(self._action_button)
        action_row.addWidget(self._refresh_button)
        action_row.addStretch()
        layout.addLayout(action_row)

        # ---- 下载进度区（默认隐藏） ----
        self._progress_card = QFrame()
        self._progress_card.setProperty("cssClass", "card")
        self._progress_card.hide()
        prog_vbox = QVBoxLayout(self._progress_card)
        prog_vbox.setContentsMargins(16, 14, 16, 14)
        prog_vbox.setSpacing(8)

        self._progress_title = QLabel("正在下载: ")
        self._progress_title.setProperty("cssClass", "sectionTitle")
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 1000)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_status = QLabel("准备下载...")
        self._progress_status.setProperty("cssClass", "taskDetail")
        self._progress_speed = QLabel("")
        self._progress_speed.setStyleSheet(f"color: {C['blue_dark']}; font-size: 12px;")
        self._progress_eta = QLabel("")
        self._progress_eta.setStyleSheet(f"color: {C['green_dark']}; font-size: 12px;")

        info_row = QHBoxLayout()
        info_row.setSpacing(16)
        info_row.addWidget(self._progress_status)
        info_row.addWidget(self._progress_speed)
        info_row.addWidget(self._progress_eta)
        info_row.addStretch()

        prog_vbox.addWidget(self._progress_title)
        prog_vbox.addWidget(self._progress_bar)
        prog_vbox.addLayout(info_row)
        layout.addWidget(self._progress_card)

        # ---- 配置状态 ----
        self._config_label = QLabel("")
        self._config_label.setProperty("cssClass", "cardSub")
        layout.addWidget(self._config_label)

        layout.addStretch()

    # ---------------------------------------------------------------- 状态

    def _load_initial_state(self) -> None:
        """加载页面初始状态（核心文件、FFmpeg、系统、Hash）"""
        # 系统环境
        sys_info = system_info.get_system_info()
        self._system_value.setText(
            f"{sys_info.get('system', '')} {sys_info.get('architecture', '')} {sys_info.get('processor_type', '')}"
        )
        self._system_sub.setText(f"机器类型: {sys_info.get('machine', '—')}")

        # FFmpeg
        ffmpeg_path = config_manager.get_ffmpeg_path()
        ffmpeg_exists = bool(ffmpeg_path and Path(ffmpeg_path).exists())
        self._ffmpeg_value.setText("已内置" if ffmpeg_exists else "未找到")
        self._ffmpeg_value.setStyleSheet(
            f"color: {C['green_dark']};" if ffmpeg_exists else f"color: {C['red_dark']};"
        )
        self._ffmpeg_sub.setText("音视频合并依赖")

        # 配置文件状态
        config_file_path = config_manager.get_config_file_path()
        config_exists = config_file_path.exists()
        if config_exists:
            self._config_label.setText(f"配置文件已存在: {config_file_path}")
            self._config_label.setStyleSheet(f"color: {C['green_dark']}; font-size: 12px;")
        else:
            self._config_label.setText("配置文件不存在，请在设置中创建配置")
            self._config_label.setStyleSheet(f"color: {C['red_dark']}; font-size: 12px;")

        self._refresh_core_status()
        self._reload_hash()

    def _reload_hash(self) -> None:
        """重新检查核心文件 Hash 并刷新显示"""
        self._hash_result = core_manager.check_core_hash()
        result = self._hash_result

        if not result.get("exists"):
            self._file_value.setText(f"{self._core_filename}\n(未找到)")
            self._file_value.setStyleSheet(f"color: {C['red_dark']};")
            self._file_sub.setText("状态: 核心文件不存在")
            self._set_badge("red", "文件缺失")
            self._official_hash_label.setText("官方 Hash: —")
            self._local_hash_label.setText("本地 Hash: —")
            self._hash_message.setText("核心文件未找到，请下载对应版本的核心文件")
            self._action_button.setText("下载核心文件")
            self._action_button.setEnabled(True)
        elif result.get("valid"):
            self._file_value.setText(f"{self._core_filename}\n(已找到)")
            self._file_value.setStyleSheet(f"color: {C['green_dark']};")
            self._file_sub.setText("状态: Hash 校验通过，文件完整")
            self._set_badge("green", "验证通过")
            self._official_hash_label.setText(f"官方 Hash: {result.get('official_hash', '—')}")
            self._local_hash_label.setText(f"本地 Hash: {result.get('local_hash', '—')}")
            self._hash_message.setText("文件完整性验证通过")
            self._action_button.setText("更新核心文件")
            self._action_button.setEnabled(True)
        else:
            self._file_value.setText(f"{self._core_filename}\n(已找到)")
            self._file_value.setStyleSheet(f"color: {C['orange_dark']};")
            self._file_sub.setText(f"状态: {result.get('message', 'Hash 校验失败')}")
            self._set_badge("orange", "需要更新")
            self._official_hash_label.setText(f"官方 Hash: {result.get('official_hash', '无法获取')}")
            self._local_hash_label.setText(f"本地 Hash: {result.get('local_hash', '无法计算')}")
            self._hash_message.setText("文件完整性验证失败，建议更新核心文件")
            self._action_button.setText("更新核心文件")
            self._action_button.setEnabled(True)

    def _refresh_core_status(self) -> None:
        """定时刷新核心运行状态（每 5 秒）"""
        update_core_status()
        status = get_core_status()
        running = status.get("is_running", False)
        if running:
            self._running_value.setText("正在运行")
            self._running_value.setStyleSheet(f"color: {C['green_dark']};")
        else:
            self._running_value.setText("已停止")
            self._running_value.setStyleSheet(f"color: {C['red_dark']};")

    def _reload_state(self) -> None:
        """点击"检查更新"时刷新全部状态"""
        update_core_status()
        self._reload_hash()

    def _set_badge(self, tone: str, text: str) -> None:
        self._hash_badge.setProperty("badge", tone)
        self._hash_badge.setProperty("cssClass", "badge")
        self._hash_badge.setText(text)
        self._hash_badge.style().unpolish(self._hash_badge)
        self._hash_badge.style().polish(self._hash_badge)

    # ---------------------------------------------------------------- 下载

    def _start_core_download(self) -> None:
        if self._downloading:
            return
        self._downloading = True
        self._action_button.setEnabled(False)
        self._refresh_button.setEnabled(False)

        self._progress_card.show()
        self._progress_title.setText(f"正在下载: {self._core_filename}")
        self._progress_bar.setValue(0)
        self._progress_status.setText("准备下载...")
        self._progress_speed.setText("")
        self._progress_eta.setText("")

        # 官网下载源使用官方核心文件名，本地保存使用 SHOUDown 品牌名
        download_url = CORE_BASE_URL + system_info.get_official_core_filename()
        save_path = str(system_info.get_default_paths()["resources_dir"])
        logger.info(f"开始下载核心文件: {download_url} -> {save_path}")

        try:
            future = async_bridge.submit(core_manager.download_file(
                url=download_url,
                filename=self._core_filename,
                save_path=save_path,
                progress_callback=self._bridge.progress.emit,
            ))
            future.add_done_callback(self._on_download_done)
        except Exception as e:
            logger.error(f"提交下载任务失败: {e}")
            self._on_finished(False, str(e))

    def _on_download_done(self, future) -> None:
        """asyncio 后台线程回调 -> 通过信号切回 UI 线程"""
        try:
            result = future.result()
            success = bool(result.get("success"))
            message = result.get("message") or ("下载完成" if success else "下载失败")
        except Exception as e:
            success, message = False, str(e)
        self._bridge.finished.emit(success, message)

    def _on_progress(self, task_id: str, task_info: dict) -> None:
        progress = task_info.get("progress", 0)
        self._progress_bar.setValue(int(progress * 10))

        status = task_info.get("status", "unknown")
        downloaded = task_info.get("downloaded_size", 0)
        total = task_info.get("total_size", 0)
        speed = task_info.get("speed", 0)
        eta = task_info.get("eta", 0)

        if status == "downloading":
            text = f"进度: {progress:.1f}% ({core_manager.format_file_size(downloaded)} / {core_manager.format_file_size(total)})"
            self._progress_status.setText(text)
            if speed > 0:
                self._progress_speed.setText(f"速度: {core_manager.format_speed(speed)}")
            if eta > 0:
                self._progress_eta.setText(f"预计剩余: {core_manager.format_time(eta)}")
        elif status == "completed":
            self._progress_status.setText(f"下载完成: {core_manager.format_file_size(total)}")
            self._progress_speed.setText("")
            self._progress_eta.setText("")

    def _on_finished(self, success: bool, message: str) -> None:
        self._downloading = False
        self._action_button.setEnabled(True)
        self._refresh_button.setEnabled(True)
        if success:
            self._progress_bar.setValue(1000)
            self._progress_status.setText("✅ 下载完成！")
            self._progress_speed.setText("")
            self._progress_eta.setText("")
            QTimer.singleShot(1500, self._reload_state)
        else:
            self._progress_status.setText(f"❌ 下载失败: {message}")
            self._progress_status.setStyleSheet(f"color: {C['red_dark']}; font-size: 12px;")
