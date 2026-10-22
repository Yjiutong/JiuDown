"""
主页（状态总览）
显示下载引擎（yt-dlp）状态、支持站点规模、FFmpeg 能力与系统环境，
支持一键更新引擎与重新检测。

版式沿用原「状态卡 + 诊断卡 + 操作行」结构，仅把「B 站核心文件」
替换为站点无关的下载引擎信息——核心 exe 已不再是下载链路的一环。
"""

import threading

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from loguru import logger

import ffmpeg_manager
import jiudown_engine
from config_manager import config_manager
from system_info import system_info


class HomePage(QWidget):
    """状态总览页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        self._site_count = 0
        self._update_thread = None
        self._update_result: tuple[bool, str] = (False, "")

        self._build_ui()
        self._load_initial_state()

        # 引擎状态轮询（FFmpeg 进度 / 站点统计结果 / 引擎更新结果）——
        # 全部走「后台做事 + 主线程轮询」，不让后台线程碰任何 Qt 对象
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(1000)

    # ---------------------------------------------------------------- FFmpeg

    def _on_ffmpeg_download(self) -> None:
        ffmpeg_manager.start_auto_upgrade()
        self._refresh_ffmpeg_state()

    def _refresh_ffmpeg_state(self) -> None:
        """刷新 FFmpeg 卡片：完整版 / 精简版 / 下载中（进度）/ 拉取失败 / 未找到"""
        state = ffmpeg_manager.get_status()
        status = state["status"]
        if status == "full":
            self._ffmpeg_value.setText("已就绪")
            self._set_value_tone(self._ffmpeg_value, "green")
            version = state.get("version") or ""
            self._ffmpeg_sub.setText(
                f"FFmpeg {version}（完整版，全部格式可用）" if version else "完整版，全部格式可用"
            )
            self._ffmpeg_download_btn.hide()
        elif status == "lite":
            self._ffmpeg_value.setText("精简版")
            self._set_value_tone(self._ffmpeg_value, "orange")
            version = state.get("version") or ""
            self._ffmpeg_sub.setText(
                f"FFmpeg {version}（精简版）：flv / wav 与单声道不可用，正在后台下载完整版"
                if version else
                "精简版：flv / wav 与单声道不可用，正在后台下载完整版"
            )
            self._ffmpeg_download_btn.setText("下载完整版")
            self._ffmpeg_download_btn.show()
        elif status == "downloading":
            percent = int(state["progress"] * 100)
            self._ffmpeg_value.setText(f"下载中 {percent}%")
            self._set_value_tone(self._ffmpeg_value, "brand")
            self._ffmpeg_sub.setText("正在自动拉取完整版 FFmpeg（约 80MB），完成后自动替换")
            self._ffmpeg_download_btn.hide()
        elif status == "failed":
            self._ffmpeg_value.setText("拉取失败")
            self._set_value_tone(self._ffmpeg_value, "red")
            self._ffmpeg_sub.setText("自动下载失败，可重试，或手动下载后放入 resources 目录")
            self._ffmpeg_download_btn.setText("重试下载")
            self._ffmpeg_download_btn.show()
        else:  # missing
            self._ffmpeg_value.setText("未找到")
            self._set_value_tone(self._ffmpeg_value, "red")
            self._ffmpeg_sub.setText("首次使用将自动下载完整版，也可手动放入 resources 目录")
            self._ffmpeg_download_btn.setText("下载完整版")
            self._ffmpeg_download_btn.show()

    # ---------------------------------------------------------------- 引擎

    def _refresh_engine_state(self) -> None:
        """引擎卡片：JiuDown 引擎版本 + 双后端就绪情况"""
        info = jiudown_engine.engine.info()
        self._engine_value.setText(f"v{info['version']}")
        if info["ytdlp_ready"]:
            self._set_value_tone(self._engine_value, "green")
            self._engine_sub.setText(
                f"原生 B 站 + yt-dlp {info['ytdlp_version']}（双后端）"
            )
        else:
            self._set_value_tone(self._engine_value, "orange")
            self._engine_sub.setText("原生 B 站可用；yt-dlp 未安装，其他站点不可用")
        self._refresh_diagnostics()

    def _refresh_site_count(self) -> None:
        """支持站点数：引擎侧后台预热，主线程轮询取值（不阻塞界面）"""
        count = jiudown_engine.request_site_count()
        if count is None:
            if not self._site_count:
                self._sites_value.setText("统计中…")
                self._sites_sub.setText("正在读取内置站点提取器…")
            return
        self._site_count = int(count or 0)
        if self._site_count > 0:
            self._sites_value.setText(f"{self._site_count} 个")
            self._set_value_tone(self._sites_value, "green")
            self._sites_sub.setText("yt-dlp 后端内置提取器（B 站另走原生链路）")
        else:
            self._sites_value.setText("未知")
            self._set_value_tone(self._sites_value, "orange")
            self._sites_sub.setText("未能读取站点列表（引擎可能未就绪）")

    def _refresh_diagnostics(self) -> None:
        """诊断卡：引擎 / FFmpeg / Cookie / 代理 四条等宽信息"""
        info = jiudown_engine.engine.info()
        ok = bool(info["ytdlp_ready"])
        ytdlp_ver = info["ytdlp_version"] or "未安装"
        self._engine_line.setText(
            f"引擎: JiuDown {info['version']}（原生 B 站 + yt-dlp {ytdlp_ver}）"
        )
        backend_text = jiudown_engine.BACKEND_LABELS.get(info["mode"], info["mode"])
        self._backend_line.setText(f"后端路由: {backend_text}")

        state = ffmpeg_manager.get_status()
        label = {"full": "完整版", "lite": "精简版", "missing": "未找到"}.get(
            state["status"], state["status"]
        )
        self._ffmpeg_line.setText(f"FFmpeg: {label}")

        try:
            browser = str(config_manager.get_config("cookies_from_browser") or "不使用")
            proxy = str(config_manager.get_config("proxy") or "").strip()
        except Exception:
            browser, proxy = "不使用", ""
        cookie_text = browser if browser and browser != "不使用" else "未配置（登录站点可能受限）"
        self._cookie_line.setText(f"Cookie: 浏览器 {cookie_text}" if browser != "不使用" else f"Cookie: {cookie_text}")
        self._proxy_line.setText(f"代理: {proxy or '未配置'}")

        if ok:
            self._set_badge("green", "就绪")
            self._diag_message.setText(
                "B 站走原生链路、其余站点走 yt-dlp；解析失败时先更新 yt-dlp 后端，"
                "需要登录的内容请在设置中选择浏览器 Cookie"
            )
        else:
            self._set_badge("orange", "部分就绪")
            self._diag_message.setText(
                "原生 B 站链路可用；yt-dlp 后端未安装，B 站以外的站点无法下载，建议修复依赖"
            )

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

    def _make_hash_label(self, prefix: str) -> QLabel:
        """创建等宽字体的信息行（沿用原 Hash 行的视觉效果）"""
        label = QLabel(f"{prefix}: —")
        label.setProperty("cssClass", "hashLabel")
        return label

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # ---- 状态卡片行 ----
        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)

        self._engine_card, self._engine_value, self._engine_sub = self._make_status_card("JiuDown 引擎")
        self._engine_value.setProperty("cssClass", "cardValueSmall")
        self._sites_card, self._sites_value, self._sites_sub = self._make_status_card("支持站点")
        self._sites_value.setProperty("cssClass", "cardValueSmall")
        self._ffmpeg_card, self._ffmpeg_value, self._ffmpeg_sub = self._make_status_card("FFmpeg")
        self._ffmpeg_value.setProperty("cssClass", "cardValueSmall")
        self._ffmpeg_btn_row = QHBoxLayout()
        self._ffmpeg_btn_row.setSpacing(8)
        self._ffmpeg_download_btn = QPushButton("下载 FFmpeg")
        self._ffmpeg_download_btn.setProperty("small", True)
        self._ffmpeg_download_btn.setProperty("primary", True)
        self._ffmpeg_download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ffmpeg_download_btn.clicked.connect(self._on_ffmpeg_download)
        self._ffmpeg_btn_row.addWidget(self._ffmpeg_download_btn)
        self._ffmpeg_btn_row.addStretch()
        self._ffmpeg_card.layout().addLayout(self._ffmpeg_btn_row)
        self._ffmpeg_download_btn.hide()
        self._system_card, self._system_value, self._system_sub = self._make_status_card("系统环境")
        self._system_value.setProperty("cssClass", "cardValueSmall")

        for card in (self._engine_card, self._sites_card, self._ffmpeg_card, self._system_card):
            cards_row.addWidget(card, 1)
        layout.addLayout(cards_row)

        # ---- 引擎诊断卡片 ----
        self._diag_card = QFrame()
        self._diag_card.setProperty("cssClass", "card")
        diag_vbox = QVBoxLayout(self._diag_card)
        diag_vbox.setContentsMargins(16, 14, 16, 14)
        diag_vbox.setSpacing(8)

        diag_top = QHBoxLayout()
        diag_top.setSpacing(8)
        diag_title = QLabel("引擎诊断")
        diag_title.setProperty("cssClass", "sectionTitle")
        self._hash_badge = QLabel("检测中")
        self._hash_badge.setProperty("cssClass", "badge")
        self._hash_badge.setProperty("badge", "gray")
        diag_top.addWidget(diag_title)
        diag_top.addWidget(self._hash_badge)
        diag_top.addStretch()
        diag_vbox.addLayout(diag_top)

        self._engine_line = self._make_hash_label("引擎")
        self._backend_line = self._make_hash_label("后端路由")
        self._ffmpeg_line = self._make_hash_label("FFmpeg")
        self._cookie_line = self._make_hash_label("Cookie")
        self._proxy_line = self._make_hash_label("代理")
        self._diag_message = QLabel("")
        self._diag_message.setProperty("cssClass", "cardSub")
        self._diag_message.setWordWrap(True)
        for widget in (self._engine_line, self._backend_line, self._ffmpeg_line,
                       self._cookie_line, self._proxy_line, self._diag_message):
            diag_vbox.addWidget(widget)
        layout.addWidget(self._diag_card)

        # ---- 操作区 ----
        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self._action_button = QPushButton("更新下载引擎")
        self._action_button.setProperty("primary", True)
        self._action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._action_button.clicked.connect(self._update_engine)
        self._refresh_button = QPushButton("重新检测")
        self._refresh_button.clicked.connect(self._reload_state)
        action_row.addWidget(self._action_button)
        action_row.addWidget(self._refresh_button)
        action_row.addStretch()
        layout.addLayout(action_row)

        # ---- 配置状态 ----
        self._config_label = QLabel("")
        self._config_label.setProperty("cssClass", "cardSub")
        self._config_label.setWordWrap(True)
        layout.addWidget(self._config_label)

        layout.addStretch()

    # ---------------------------------------------------------------- 状态

    def _load_initial_state(self) -> None:
        """加载页面初始状态（引擎 / 站点 / FFmpeg / 系统 / 配置）"""
        sys_info = system_info.get_system_info()
        self._system_value.setText(
            f"{sys_info.get('system', '')} {sys_info.get('architecture', '')} "
            f"{sys_info.get('processor_type', '')}"
        )
        self._system_sub.setText(f"机器类型: {sys_info.get('machine', '—')}")

        self._refresh_ffmpeg_state()
        self._refresh_engine_state()
        self._refresh_site_count()

        config_file_path = config_manager.get_config_file_path()
        config_exists = config_file_path.exists()
        self._config_exists = config_exists
        if config_exists:
            self._config_label.setText(f"配置文件已存在: {config_file_path}")
            self._config_label.setProperty("cssClass", "configOk")
        else:
            self._config_label.setText("配置文件不存在，请在设置中创建配置")
            self._config_label.setProperty("cssClass", "configError")
        self._config_label.style().unpolish(self._config_label)
        self._config_label.style().polish(self._config_label)

    def _set_value_tone(self, label: QLabel, tone: str) -> None:
        """设置数值标签的色调（green/orange/red），通过 cssClass 跟随主题"""
        label.setProperty("tone", tone)
        label.style().unpolish(label)
        label.style().polish(label)

    def _set_badge(self, tone: str, text: str) -> None:
        self._hash_badge.setProperty("badge", tone)
        self._hash_badge.setProperty("cssClass", "badge")
        self._hash_badge.setText(text)
        self._hash_badge.style().unpolish(self._hash_badge)
        self._hash_badge.style().polish(self._hash_badge)

    def _reload_state(self) -> None:
        """点击「重新检测」：刷新全部状态"""
        self._refresh_engine_state()
        self._refresh_site_count()
        self._load_initial_state()

    # ---------------------------------------------------------------- 轮询

    def _poll(self) -> None:
        """主线程轮询：站点统计预热结果 / 引擎更新完成 / FFmpeg 进度（每 5 秒）"""
        self._tick = getattr(self, "_tick", 0) + 1
        if self._site_count <= 0:
            self._refresh_site_count()
        if self._tick % 5 == 0:
            self._refresh_ffmpeg_state()
            self._refresh_diagnostics()
        thread = self._update_thread
        if self._updating and thread is not None and not thread.is_alive():
            self._updating = False
            self._update_thread = None
            self._on_engine_updated(*self._update_result)

    # ---------------------------------------------------------------- 引擎更新

    def _update_engine(self) -> None:
        """后台更新 yt-dlp；结果由 _poll 在主线程应用（不跨线程发信号）"""
        if self._updating:
            return
        self._updating = True
        self._update_result = (False, "")
        self._action_button.setEnabled(False)
        self._refresh_button.setEnabled(False)
        self._engine_value.setText("更新中…")
        self._set_value_tone(self._engine_value, "brand")
        self._engine_sub.setText("正在通过 pip 更新下载引擎，请稍候…")

        def worker() -> None:
            try:
                self._update_result = jiudown_engine.update_engine()
            except Exception as e:
                self._update_result = (False, str(e))

        self._update_thread = threading.Thread(
            target=worker, daemon=True, name="ytdlp-update"
        )
        self._update_thread.start()

    def _on_engine_updated(self, ok: bool, message: str) -> None:
        self._action_button.setEnabled(True)
        self._refresh_button.setEnabled(True)
        logger.info(f"下载引擎更新{'成功' if ok else '失败'}: {message}")
        self._refresh_engine_state()
        if not ok:
            self._engine_sub.setText(f"更新失败：{message}")

    def refresh_theme(self) -> None:
        """主题切换回调：QSS cssClass 自动跟随，此处仅需刷新状态"""
        self._refresh_ffmpeg_state()
        self._refresh_engine_state()
        if hasattr(self, "_config_exists"):
            self._config_label.setProperty(
                "cssClass", "configOk" if self._config_exists else "configError"
            )
            self._config_label.style().unpolish(self._config_label)
            self._config_label.style().polish(self._config_label)
