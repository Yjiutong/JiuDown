"""
设置页（综合收纳页）
收纳除下载外的全部功能：状态总览 / 运行日志 / 应用设置（五类设置分组，支持保存、重置）
"""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from loguru import logger

import ffmpeg_manager
import jiudown_engine
from config_manager import config_manager
from pages.download_page import FORMATS
from pages.home_page import HomePage
from pages.log_page import LogPage

LOG_LEVELS = ["info", "warning", "error", "debug", "silent"]
QUALITIES = jiudown_engine.QUALITY_CHOICES


class SettingsPage(QWidget):
    """综合设置页面：状态总览 + 运行日志 + 应用设置"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load_settings()
        # FFmpeg 完整版下载进度/就绪：同步设置页状态与默认格式门控
        ffmpeg_manager.signals.progress.connect(
            lambda _p: self._refresh_ffmpeg_status()
        )
        ffmpeg_manager.signals.finished.connect(
            lambda _ok, _msg: self._refresh_ffmpeg_status()
        )
        ffmpeg_manager.signals.capabilities_changed.connect(
            self._refresh_ffmpeg_status
        )

    # ---------------------------------------------------------------- 构建

    def _section_card(self, title: str, hint: str = "") -> tuple[QFrame, QVBoxLayout]:
        """创建设置分组卡片，返回 (卡片, 内容布局)"""
        card = QFrame()
        card.setProperty("cssClass", "sectionCard")
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(18, 16, 18, 16)
        vbox.setSpacing(12)

        title_label = QLabel(title)
        title_label.setProperty("cssClass", "sectionTitle")
        vbox.addWidget(title_label)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setProperty("cssClass", "sectionHint")
            vbox.addWidget(hint_label)

        divider = QFrame()
        divider.setProperty("cssClass", "divider")
        vbox.addWidget(divider)
        return card, vbox

    def _form_row(self, label: str, widget: QWidget, stretch: bool = True) -> QHBoxLayout:
        """创建表单行：左标签 + 右控件"""
        row = QHBoxLayout()
        row.setSpacing(10)
        label_widget = QLabel(label)
        label_widget.setProperty("cssClass", "formLabel")
        label_widget.setFixedWidth(170)
        row.addWidget(label_widget)
        row.addWidget(widget, 1 if stretch else 0)
        return row

    def _browse_row(self, line_edit: QLineEdit, dialog_title: str,
                    select_file: bool = False, file_filter: str = "") -> QPushButton:
        button = QPushButton("浏览")
        if select_file:
            button.clicked.connect(
                lambda: self._browse_file(line_edit, dialog_title, file_filter)
            )
        else:
            button.clicked.connect(
                lambda: self._browse_dir(line_edit, dialog_title)
            )
        return button

    def _make_hint_label(self, text: str) -> QLabel:
        """分组内的说明小字"""
        label = QLabel(text)
        label.setProperty("cssClass", "sectionHint")
        label.setWordWrap(True)
        return label

    def _browse_dir(self, line_edit: QLineEdit, title: str) -> None:
        start = line_edit.text() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, title, start)
        if selected:
            line_edit.setText(selected)

    def _browse_file(self, line_edit: QLineEdit, title: str, file_filter: str) -> None:
        start = line_edit.text() or str(Path.home())
        selected, _ = QFileDialog.getOpenFileName(self, title, start, file_filter)
        if selected:
            line_edit.setText(selected)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 顶层收纳：状态总览 / 运行日志 / 设置
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.tabs.addTab(HomePage(self), "状态总览")
        self.tabs.addTab(LogPage(self), "运行日志")

        # 设置宿主页：五类设置分组 + 底部操作区
        settings_host = QWidget()
        settings_host.setObjectName("settingsHost")
        # 背景由全局 QSS 的 QWidget#settingsHost / QTabWidget 规则按主题提供（零硬编码）

        settings_layout = QVBoxLayout(settings_host)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(12)

        self.settings_tabs = QTabWidget()
        self.settings_tabs.setObjectName("settingsTabs")
        self.settings_tabs.addTab(self._build_basic_tab(), "基本设置")
        self.settings_tabs.addTab(self._build_download_tab(), "下载设置")
        self.settings_tabs.addTab(self._build_network_tab(), "网络设置")
        self.settings_tabs.addTab(self._build_user_tab(), "用户设置")
        self.settings_tabs.addTab(self._build_advanced_tab(), "高级设置")
        settings_layout.addWidget(self.settings_tabs, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self._reset_button = QPushButton("重置为默认")
        self._reset_button.clicked.connect(self._reset_settings)
        self._save_button = QPushButton("保存设置")
        self._save_button.setProperty("primary", True)
        self._save_button.clicked.connect(self._save_settings)
        footer.addStretch()
        footer.addWidget(self._reset_button)
        footer.addWidget(self._save_button)
        settings_layout.addLayout(footer)

        self.tabs.addTab(settings_host, "设置")

    def _make_scroll(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # 透明底由全局 QSS 的 QScrollArea 规则统一处理：不使用控件级 setStyleSheet，
        # 避免样式级联污染滚动区内部弹出的菜单/提示气泡
        # 内容页显式命名：由全局 QSS 以主题令牌上色（QWidget#settingsScrollPage），
        # 不依赖视口的调色板回退——部分环境下回退底色与主题不一致（发黑）
        content.setObjectName("settingsScrollPage")
        scroll.setWidget(content)
        return scroll

    def _build_basic_tab(self) -> QWidget:
        host = QWidget()
        vbox = QVBoxLayout(host)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(14)

        # 外观设置卡片
        card, card_vbox = self._section_card("外观设置", "切换应用主题风格")
        from theme import theme_manager, MODE_SYSTEM, MODE_LIGHT, MODE_DARK, MODE_LABELS
        self.theme_mode = QComboBox()
        self.theme_mode.addItem(MODE_LABELS[MODE_SYSTEM], MODE_SYSTEM)
        self.theme_mode.addItem(MODE_LABELS[MODE_LIGHT], MODE_LIGHT)
        self.theme_mode.addItem(MODE_LABELS[MODE_DARK], MODE_DARK)
        # 设置当前选中项
        current_mode = theme_manager.mode
        for i in range(self.theme_mode.count()):
            if self.theme_mode.itemData(i) == current_mode:
                self.theme_mode.setCurrentIndex(i)
                break
        self.theme_mode.currentIndexChanged.connect(self._on_theme_mode_changed)
        row = self._form_row("主题模式", self.theme_mode)
        row.addStretch()
        card_vbox.addLayout(row)
        vbox.addWidget(card)

        card, card_vbox = self._section_card("日志设置")
        self.log_level = QComboBox()
        self.log_level.addItems(LOG_LEVELS)
        row = self._form_row("日志级别", self.log_level)
        row.addStretch()
        card_vbox.addLayout(row)
        vbox.addWidget(card)

        card, card_vbox = self._section_card("外部控制器端口", "核心程序对外提供的服务端口")
        self.grpc_port = QSpinBox()
        self.grpc_port.setRange(1024, 49151)
        row = self._form_row("gRPC 端口", self.grpc_port)
        row.addStretch()
        card_vbox.addLayout(row)
        self.grpc_web_port = QSpinBox()
        self.grpc_web_port.setRange(1024, 49151)
        row = self._form_row("gRPC-Web 端口", self.grpc_web_port)
        row.addStretch()
        card_vbox.addLayout(row)
        self.restful_port = QSpinBox()
        self.restful_port.setRange(1024, 49151)
        row = self._form_row("RESTful API 端口", self.restful_port)
        row.addStretch()
        card_vbox.addLayout(row)
        vbox.addWidget(card)
        vbox.addStretch()
        return self._make_scroll(host)

    def _build_download_tab(self) -> QWidget:
        host = QWidget()
        vbox = QVBoxLayout(host)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(14)

        card, card_vbox = self._section_card("目录与工具", "留空使用默认路径")
        self.temp_dir_input = QLineEdit()
        row = self._form_row("临时目录", self.temp_dir_input)
        row.addWidget(self._browse_row(self.temp_dir_input, "选择临时目录"))
        card_vbox.addLayout(row)
        self.download_dir_input = QLineEdit()
        row = self._form_row("下载目录", self.download_dir_input)
        row.addWidget(self._browse_row(self.download_dir_input, "选择下载目录"))
        card_vbox.addLayout(row)
        self.ffmpeg_path_input = QLineEdit()
        row = self._form_row("FFmpeg 路径", self.ffmpeg_path_input)
        row.addWidget(self._browse_row(
            self.ffmpeg_path_input, "选择FFmpeg可执行文件",
            select_file=True, file_filter="可执行文件 (*.exe);;所有文件 (*)",
        ))
        card_vbox.addLayout(row)

        # FFmpeg 版本状态 + 完整版升级（仓库内置精简版已覆盖下载链路）
        ffmpeg_row = QHBoxLayout()
        ffmpeg_row.setSpacing(10)
        self.ffmpeg_status_label = QLabel("检测中…")
        self.ffmpeg_status_label.setProperty("cssClass", "sectionHint")
        self.ffmpeg_status_label.setWordWrap(True)
        self.ffmpeg_progress = QProgressBar()
        self.ffmpeg_progress.setFixedWidth(120)
        self.ffmpeg_progress.setFixedHeight(6)
        self.ffmpeg_progress.setTextVisible(False)
        self.ffmpeg_download_btn = QPushButton("下载完整版")
        self.ffmpeg_download_btn.clicked.connect(self._download_full_ffmpeg)
        ffmpeg_row.addWidget(self.ffmpeg_status_label, 1)
        ffmpeg_row.addWidget(self.ffmpeg_progress)
        ffmpeg_row.addWidget(self.ffmpeg_download_btn)
        card_vbox.addLayout(ffmpeg_row)
        card_vbox.addWidget(self._make_hint_label(
            "仓库自带的是从源码裁剪编译的精简版（约 5MB），已支持 mp4 / flv / mp3 / wav "
            "与单声道，覆盖全部下载场景；需要视频重编码等能力时可升级到完整版（约 161MB）"
        ))
        vbox.addWidget(card)

        # ---- JiuDown 下载引擎：双后端路由 + 版本与更新 ----
        card, card_vbox = self._section_card(
            "JiuDown 下载引擎",
            "自带双后端：B 站走自研原生链路（快且可控），其余站点走 yt-dlp（1700+ 站点）"
        )
        self.engine_backend = QComboBox()
        for key, text in jiudown_engine.BACKEND_LABELS.items():
            self.engine_backend.addItem(text, key)
        row = self._form_row("后端路由", self.engine_backend)
        row.addStretch()
        card_vbox.addLayout(row)
        card_vbox.addWidget(self._make_hint_label(
            "自动：B 站先走原生链路，失败自动降级 yt-dlp；"
            "仅原生：B 站接口异常时可手动切到 yt-dlp 应急"
        ))
        engine_row = QHBoxLayout()
        engine_row.setSpacing(10)
        self.engine_status_label = QLabel("检测中…")
        self.engine_status_label.setProperty("cssClass", "sectionHint")
        self.engine_status_label.setWordWrap(True)
        self.engine_update_btn = QPushButton("更新引擎")
        self.engine_update_btn.clicked.connect(self._update_engine)
        engine_row.addWidget(self.engine_status_label, 1)
        engine_row.addWidget(self.engine_update_btn)
        card_vbox.addLayout(engine_row)
        card_vbox.addWidget(self._make_hint_label(
            "站点改版导致解析失败时，更新引擎通常即可恢复。"
            "组件包随仓库分发：点「更新引擎」会先查是否有更新，"
            "查不到就恢复仓库内置的那份（不会静默降级，结果会明确提示）"
        ))
        vbox.addWidget(card)

        card, card_vbox = self._section_card("下载限制")
        self.max_tasks = QSpinBox()
        self.max_tasks.setRange(1, 5)
        row = self._form_row("最大同时下载任务数", self.max_tasks)
        row.addStretch()
        card_vbox.addLayout(row)
        self.default_quality = QComboBox()
        self.default_quality.addItems(QUALITIES)
        row = self._form_row("默认清晰度", self.default_quality)
        row.addStretch()
        card_vbox.addLayout(row)
        self.default_format = QComboBox()
        self.default_format.addItems(FORMATS)
        row = self._form_row("默认格式", self.default_format)
        row.addStretch()
        card_vbox.addLayout(row)
        self.playlist_limit = QSpinBox()
        self.playlist_limit.setRange(1, 500)
        self.playlist_limit.setSuffix(" 个")
        row = self._form_row("播放列表最多下载", self.playlist_limit)
        row.addStretch()
        card_vbox.addLayout(row)
        card_vbox.addWidget(self._make_hint_label(
            "播放列表/合集链接的下载上限；1 = 只下载链接指向的单个视频"
        ))
        self.speed_limit = QSpinBox()
        self.speed_limit.setRange(0, 1024)
        self.speed_limit.setSuffix(" MiB/s")
        row = self._form_row("下载速度限制", self.speed_limit)
        row.addStretch()
        card_vbox.addLayout(row)
        self.disable_mcdn = QCheckBox("禁用 mCDN 下载源")
        row = self._form_row("下载源", self.disable_mcdn)
        row.addStretch()
        card_vbox.addLayout(row)
        vbox.addWidget(card)
        vbox.addStretch()
        return self._make_scroll(host)

    def _build_network_tab(self) -> QWidget:
        host = QWidget()
        vbox = QVBoxLayout(host)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(14)

        card, card_vbox = self._section_card("代理设置")
        self.proxy_addr = QLineEdit()
        self.proxy_addr.setPlaceholderText("例如: http://127.0.0.1:1080")
        row = self._form_row("代理地址", self.proxy_addr)
        row.addStretch()
        card_vbox.addLayout(row)
        vbox.addWidget(card)

        card, card_vbox = self._section_card("下载策略")
        self.max_retry = QSpinBox()
        self.max_retry.setRange(1, 10)
        row = self._form_row("最大重试次数", self.max_retry)
        row.addStretch()
        card_vbox.addLayout(row)
        self.retry_wait = QSpinBox()
        self.retry_wait.setRange(1, 600)
        self.retry_wait.setSuffix(" 秒")
        row = self._form_row("重试等待时间", self.retry_wait)
        row.addStretch()
        card_vbox.addLayout(row)
        self.session_workers = QSpinBox()
        self.session_workers.setRange(1, 3)
        row = self._form_row("会话工作者数量", self.session_workers)
        row.addStretch()
        card_vbox.addLayout(row)
        self.part_workers = QSpinBox()
        self.part_workers.setRange(1, 8)
        row = self._form_row("分段工作者数量", self.part_workers)
        row.addStretch()
        card_vbox.addLayout(row)
        self.min_split_size = QSpinBox()
        self.min_split_size.setRange(1, 100)
        self.min_split_size.setSuffix(" MiB")
        row = self._form_row("最小分段大小", self.min_split_size)
        row.addStretch()
        card_vbox.addLayout(row)
        self.check_best_mirror = QCheckBox("检查最快的下载源")
        row = self._form_row("镜像策略", self.check_best_mirror)
        row.addStretch()
        card_vbox.addLayout(row)
        vbox.addWidget(card)
        vbox.addStretch()
        return self._make_scroll(host)

    def _build_user_tab(self) -> QWidget:
        host = QWidget()
        vbox = QVBoxLayout(host)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(14)

        card, card_vbox = self._section_card("用户认证", "用于需要登录的站点（会员/私享/高画质门槛）")

        # 首选方式：直接从浏览器读取已登录的 Cookie（无需手动复制粘贴）
        self.cookie_browser = QComboBox()
        self.cookie_browser.addItems(jiudown_engine.COOKIE_BROWSERS)
        row = self._form_row("从浏览器读取 Cookie", self.cookie_browser)
        row.addStretch()
        card_vbox.addLayout(row)
        card_vbox.addWidget(self._make_hint_label(
            "选择浏览器后，下载时会自动读取该浏览器里已登录站点的 Cookie；"
            "下方手动填写的 Cookie 仅在未选择浏览器时使用"
        ))

        def token_input(placeholder: str) -> QLineEdit:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            return edit

        self.access_token = token_input("用于 TV、APP 接口登录")
        row = self._form_row("Access Token", self.access_token)
        card_vbox.addLayout(row)
        self.refresh_token = token_input("用于刷新 Access Token")
        row = self._form_row("Refresh Token", self.refresh_token)
        card_vbox.addLayout(row)
        self.raw_access_token = token_input("手动设置 Access Token（优先级更高）")
        row = self._form_row("Raw Access Token", self.raw_access_token)
        card_vbox.addLayout(row)

        self.cookies = QTextEdit()
        self.cookies.setPlaceholderText("用于 WEB 接口登录")
        self.cookies.setMaximumHeight(72)
        row = self._form_row("Cookies", self.cookies)
        card_vbox.addLayout(row)
        self.raw_cookies = QTextEdit()
        self.raw_cookies.setPlaceholderText("手动设置 Cookies（优先级更高）")
        self.raw_cookies.setMaximumHeight(72)
        row = self._form_row("Raw Cookies", self.raw_cookies)
        card_vbox.addLayout(row)

        self.hide_nickname = QCheckBox("隐藏用户信息（Premium 用户专属）")
        row = self._form_row("隐私", self.hide_nickname)
        row.addStretch()
        card_vbox.addLayout(row)
        vbox.addWidget(card)
        vbox.addStretch()
        return self._make_scroll(host)

    def _build_advanced_tab(self) -> QWidget:
        host = QWidget()
        vbox = QVBoxLayout(host)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(14)

        card, card_vbox = self._section_card("内存缓存", "将下载数据暂存于内存，提升写入性能")
        self.cache_in_ram = QCheckBox("启用内存缓存")
        row = self._form_row("缓存模式", self.cache_in_ram)
        row.addStretch()
        card_vbox.addLayout(row)
        self.cache_in_ram_limit = QSpinBox()
        self.cache_in_ram_limit.setRange(500, 16384)
        self.cache_in_ram_limit.setSuffix(" MiB")
        row = self._form_row("内存缓存限制", self.cache_in_ram_limit)
        row.addStretch()
        card_vbox.addLayout(row)
        vbox.addWidget(card)

        card, card_vbox = self._section_card("安全设置")
        self.insecure_skip_verify = QCheckBox("跳过 HTTPS 证书验证")
        row = self._form_row("证书验证", self.insecure_skip_verify)
        row.addStretch()
        card_vbox.addLayout(row)
        self.custom_root_certificates = QLineEdit()
        self.custom_root_certificates.setPlaceholderText("PEM 格式证书文件路径")
        row = self._form_row("自定义根证书路径", self.custom_root_certificates)
        row.addWidget(self._browse_row(
            self.custom_root_certificates, "选择证书文件",
            select_file=True,
            file_filter="证书文件 (*.pem *.crt *.cer *.der);;所有文件 (*)",
        ))
        card_vbox.addLayout(row)
        vbox.addWidget(card)
        vbox.addStretch()
        return self._make_scroll(host)

    # ---------------------------------------------------------------- 数据

    def _load_settings(self) -> None:
        """从配置加载值填充控件"""
        current = config_manager.load_config()

        self.log_level.setCurrentText(current.get("log-level", "info"))

        ports = current.get("external-controller-port", {})
        self.grpc_port.setValue(int(ports.get("grpc", 4000)))
        self.grpc_web_port.setValue(int(ports.get("grpc-web", 4100)))
        self.restful_port.setValue(int(ports.get("restful-api", 64001)))

        task = current.get("download-task", {})
        self.temp_dir_input.setText(task.get("temp-dir", ""))
        self.download_dir_input.setText(task.get("download-dir", ""))
        self.ffmpeg_path_input.setText(task.get("ffmpeg-path", ""))
        self.max_tasks.setValue(int(task.get("max-task", 2)))
        self.default_quality.setCurrentText(task.get("quality", "720P"))
        self.default_format.setCurrentText(task.get("format", "mp4"))
        self.speed_limit.setValue(int(task.get("download-speed-limit", 0)) // (1024 * 1024))
        self.disable_mcdn.setChecked(bool(task.get("disable-mcdn", False)))

        jdm = current.get("jdm", {})
        self.proxy_addr.setText(jdm.get("proxy-addr", ""))
        self.max_retry.setValue(int(jdm.get("max-retry", 3)))
        self.retry_wait.setValue(int(jdm.get("retry-wait", 5)))
        self.session_workers.setValue(int(jdm.get("session-workers", 1)))
        self.part_workers.setValue(int(jdm.get("part-workers", 4)))
        self.min_split_size.setValue(int(jdm.get("min-split-size", 30)))
        self.check_best_mirror.setChecked(bool(jdm.get("check-best-mirror", True)))
        self.cache_in_ram.setChecked(bool(jdm.get("cache-in-ram", False)))
        self.cache_in_ram_limit.setValue(int(jdm.get("cache-in-ram-limit", 512)))
        self.insecure_skip_verify.setChecked(bool(jdm.get("insecure-skip-verify", False)))
        self.custom_root_certificates.setText(jdm.get("custom-root-certificates", ""))

        user = current.get("user-info", {})
        self.access_token.setText(user.get("access-token", ""))
        self.refresh_token.setText(user.get("refresh-token", ""))
        self.cookies.setPlainText(user.get("cookies", ""))
        self.raw_access_token.setText(user.get("raw-access-token", ""))
        self.raw_cookies.setPlainText(user.get("raw-cookies", ""))
        self.hide_nickname.setChecked(bool(user.get("hide-nickname", False)))
        self.playlist_limit.setValue(int(task.get("playlist-limit", 1)))

        # 下载引擎（yt-dlp）：Cookie 来源与代理（代理优先取 engine.proxy）
        engine_cfg = current.get("engine", {}) or {}
        browser = engine_cfg.get("cookies-from-browser", "不使用") or "不使用"
        if self.cookie_browser.findText(browser) < 0:
            browser = "不使用"
        self.cookie_browser.setCurrentText(browser)
        backend = str(engine_cfg.get("backend") or "auto")
        for i in range(self.engine_backend.count()):
            if self.engine_backend.itemData(i) == backend:
                self.engine_backend.setCurrentIndex(i)
                break
        if engine_cfg.get("proxy"):
            self.proxy_addr.setText(str(engine_cfg.get("proxy")))

        self._apply_format_gating()
        self._refresh_ffmpeg_status()
        self._refresh_engine_status()

    # ---------------------------------------------------------------- 下载引擎

    def _refresh_engine_status(self) -> None:
        """引擎状态行（只读版本元数据，不 import 重模块，保证启动速度）"""
        label = getattr(self, "engine_status_label", None)
        if label is None:
            return
        info = jiudown_engine.engine.info()
        native = "原生 B 站 ✓"
        ytdlp = f"yt-dlp {info['ytdlp_version'] or '未安装'}"
        label.setText(
            f"JiuDown 引擎 {info['version']} · {native} · {ytdlp}"
        )
        self.engine_update_btn.setEnabled(True)
        if not info["ytdlp_ready"]:
            label.setText(
                f"JiuDown 引擎 {info['version']} · 原生 B 站 ✓ · "
                "yt-dlp 未安装（B 站以外站点不可用）"
            )

    def _update_engine(self) -> None:
        """后台更新 yt-dlp（失败给出可读原因）"""
        import threading

        self.engine_update_btn.setEnabled(False)
        self.engine_status_label.setText("正在更新下载引擎，请稍候…")
        result: dict = {}

        def work() -> None:
            result["r"] = jiudown_engine.update_engine()

        thread = threading.Thread(target=work, daemon=True, name="ytdlp-update")
        thread.start()

        def poll() -> None:
            if thread.is_alive():
                QTimer.singleShot(250, poll)
                return
            ok, message = result.get("r", (False, "未知错误"))
            self.engine_update_btn.setEnabled(True)
            self._refresh_engine_status()
            if ok:
                QMessageBox.information(self, "更新完成", message)
            else:
                QMessageBox.warning(self, "更新失败", message)

        QTimer.singleShot(250, poll)

    # ---------------------------------------------------------------- FFmpeg

    def _apply_format_gating(self) -> None:
        """默认格式下拉按当前 ffmpeg 能力禁用不可用项（与下载页一致）"""
        model = self.default_format.model()
        for i in range(self.default_format.count()):
            fmt = self.default_format.itemText(i)
            supported = ffmpeg_manager.format_supported(fmt)
            item = model.item(i)
            if item is not None:
                item.setEnabled(supported)
            self.default_format.setItemData(
                i,
                "" if supported else f"当前 FFmpeg 无法输出 {fmt}（完整版就绪后可用）",
                Qt.ItemDataRole.ToolTipRole,
            )
        if not ffmpeg_manager.format_supported(self.default_format.currentText()):
            if ffmpeg_manager.format_supported("mp4"):
                self.default_format.setCurrentText("mp4")

    def _refresh_ffmpeg_status(self) -> None:
        """刷新 FFmpeg 状态行：完整版 / 精简版（能力齐备）/ 能力不足 / 下载中 / 失败 / 未找到"""
        state = ffmpeg_manager.get_status()
        status = state["status"]
        version = state.get("version") or ""
        if status == "downloading":
            percent = int(state.get("progress", 0) * 100)
            self.ffmpeg_status_label.setText(
                f"正在下载完整版 FFmpeg… {percent}%（约 161MB，后台进行）"
            )
            self.ffmpeg_progress.setValue(percent)
            self.ffmpeg_progress.show()
            self.ffmpeg_download_btn.setEnabled(False)
        elif status == "full":
            self.ffmpeg_status_label.setText(
                f"完整版 FFmpeg {version}：全部格式可用" if version
                else "完整版 FFmpeg：全部格式可用"
            )
            self.ffmpeg_progress.hide()
            self.ffmpeg_download_btn.setEnabled(False)
            self.ffmpeg_download_btn.setText("已是完整版")
        elif status == "ready":
            self.ffmpeg_status_label.setText(
                f"精简版 FFmpeg {version}：下载所需能力齐备（可选升级完整版）"
                if version else "精简版 FFmpeg：下载所需能力齐备（可选升级完整版）"
            )
            self.ffmpeg_progress.hide()
            self.ffmpeg_download_btn.setEnabled(True)
            self.ffmpeg_download_btn.setText("升级完整版")
        elif status == "lite":
            feats = ffmpeg_manager.missing_features()
            detail = " / ".join(feats) if feats else "部分能力"
            self.ffmpeg_status_label.setText(
                f"当前 FFmpeg {version}：{detail} 不可用（可升级完整版）"
                if version else f"当前 FFmpeg：{detail} 不可用（可升级完整版）"
            )
            self.ffmpeg_progress.hide()
            self.ffmpeg_download_btn.setEnabled(True)
            self.ffmpeg_download_btn.setText("下载完整版")
        elif status == "failed":
            self.ffmpeg_status_label.setText(
                f"自动下载失败：{state.get('error') or '网络异常'}"
            )
            self.ffmpeg_progress.hide()
            self.ffmpeg_download_btn.setEnabled(True)
            self.ffmpeg_download_btn.setText("重试下载")
        else:  # missing
            self.ffmpeg_status_label.setText("未找到 FFmpeg，将自动下载精简版")
            self.ffmpeg_progress.hide()
            self.ffmpeg_download_btn.setEnabled(True)
            self.ffmpeg_download_btn.setText("下载 FFmpeg")

    def _download_full_ffmpeg(self) -> None:
        """手动触发完整版下载（自动下载失败或用户主动升级时）"""
        if ffmpeg_manager.start_auto_upgrade():
            self._refresh_ffmpeg_status()

    def _collect_settings(self) -> dict:
        return {
            "log-level": self.log_level.currentText(),
            "external-controller-port": {
                "grpc": int(self.grpc_port.value()),
                "grpc-web": int(self.grpc_web_port.value()),
                "restful-api": int(self.restful_port.value()),
            },
            "download-task": {
                "temp-dir": self.temp_dir_input.text(),
                "download-dir": self.download_dir_input.text(),
                "ffmpeg-path": self.ffmpeg_path_input.text(),
                "max-task": int(self.max_tasks.value()),
                "download-speed-limit": int(self.speed_limit.value()) * 1024 * 1024,
                "disable-mcdn": self.disable_mcdn.isChecked(),
                "quality": self.default_quality.currentText(),
                "format": self.default_format.currentText(),
                "playlist-limit": int(self.playlist_limit.value()),
            },
            "engine": {
                "backend": self.engine_backend.currentData() or "auto",
                "proxy": self.proxy_addr.text().strip(),
                "cookies-from-browser": self.cookie_browser.currentText(),
            },
            "jdm": {
                "max-retry": int(self.max_retry.value()),
                "retry-wait": int(self.retry_wait.value()),
                "session-workers": int(self.session_workers.value()),
                "part-workers": int(self.part_workers.value()),
                "min-split-size": int(self.min_split_size.value()),
                "proxy-addr": self.proxy_addr.text(),
                "check-best-mirror": self.check_best_mirror.isChecked(),
                "cache-in-ram": self.cache_in_ram.isChecked(),
                "cache-in-ram-limit": int(self.cache_in_ram_limit.value()),
                "insecure-skip-verify": self.insecure_skip_verify.isChecked(),
                "custom-root-certificates": self.custom_root_certificates.text(),
            },
            "user-info": {
                "access-token": self.access_token.text(),
                "refresh-token": self.refresh_token.text(),
                "cookies": self.cookies.toPlainText(),
                "raw-access-token": self.raw_access_token.text(),
                "raw-cookies": self.raw_cookies.toPlainText(),
                "hide-nickname": self.hide_nickname.isChecked(),
            },
        }

    def _on_theme_mode_changed(self, index: int) -> None:
        """主题模式切换回调"""
        from theme import theme_manager
        mode = self.theme_mode.itemData(index)
        theme_manager.set_mode(mode, persist=True)

    def _save_settings(self) -> None:
        try:
            success = config_manager.save_config(self._collect_settings())
            if success:
                QMessageBox.information(self, "保存成功", "设置已保存！")
            else:
                QMessageBox.warning(self, "保存失败", "保存设置失败，请检查配置")
        except Exception as e:
            logger.error(f"保存设置失败: {e}")
            QMessageBox.critical(self, "保存失败", f"保存设置失败: {e}")

    def _reset_settings(self) -> None:
        answer = QMessageBox.question(
            self, "重置设置", "确定要重置所有设置为默认值吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            config_manager.reset_to_default()
            self._load_settings()
            QMessageBox.information(self, "重置成功", "设置已重置为默认值！")
        except Exception as e:
            logger.error(f"重置设置失败: {e}")
            QMessageBox.critical(self, "重置失败", f"重置设置失败: {e}")
