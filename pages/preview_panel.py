"""
视频预览面板（卡片下方展开版）
只加载播放窗口：在线预览直接播放流（本地代理 + 音视频合一 durl），
不加载任何网页内容；加载过程中显示占位，就绪后才展示播放器。
"""

import re
import threading
import http.server
import socketserver

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

import requests
from loguru import logger

from download_manager import download_manager
from config_manager import config_manager


def _extract_bvid(url: str) -> str:
    """从链接中提取 BV 号"""
    url = url.strip()
    match = re.search(r"(BV[0-9A-Za-z]{10})", url)
    if match:
        return match.group(1)
    match = re.search(r"(av\d+)", url, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    raise ValueError("无法从链接中识别B站视频ID")


# ---------------------------------------------------------------- 本地流代理
# 在线预览原理（对齐 PeanutDL 的即时播放）：
# 解析出 B 站音视频合一的 durl 流地址后，由本地代理携带 Referer 请求头转发，
# Qt 播放器播放 http://127.0.0.1:<port>/stream 实现实时播放（无需等待整段缓冲）。

_PROXY_STREAM_URL = ""
_PROXY_STREAM_HEADERS = {}


class _PreviewVideoWidget(QVideoWidget):
    """画面随视频自身比例自适应：铺满面板宽度、按视频宽高比定高度，
    高度超出部分由页面级滚动条浏览完整画面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ratio_w = 16
        self._ratio_h = 9
        self.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)

    def set_video_size(self, w: int, h: int) -> None:
        """播放器上报实际视频尺寸时更新宽高比并重算高度"""
        if w > 0 and h > 0 and (w, h) != (self._ratio_w, self._ratio_h):
            self._ratio_w, self._ratio_h = w, h
            self._update_min_height()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_min_height()

    def _update_min_height(self) -> None:
        w = self.width()
        if w > 100:
            target = max(int(w * self._ratio_h / self._ratio_w), 240)
            if self.minimumHeight() != target:
                self.setMinimumHeight(target)


class _StreamProxyHandler(http.server.BaseHTTPRequestHandler):
    """本地流代理：把 B 站流（带鉴权头）转发给播放器，支持 Range 透传"""

    def do_GET(self):
        try:
            req_h = dict(self.headers)
            # 过滤 hop-by-hop 头：播放器的 Host 指向本地代理，透传会给 B 站造成 403
            for k in ("Host", "Connection", "Accept-Encoding", "Proxy-Connection"):
                req_h.pop(k, None)
            req_h.update(_PROXY_STREAM_HEADERS)
            resp = requests.get(_PROXY_STREAM_URL, headers=req_h, stream=True, timeout=120)
            self.send_response(resp.status_code)
            for k, v in resp.headers.items():
                if k.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(k, v)
            self.end_headers()
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    self.wfile.write(chunk)
        except Exception as e:
            logger.debug(f"流代理转发中断: {e}")
            try:
                self.send_response(502)
                self.end_headers()
            except Exception:
                pass

    def log_message(self, *args):
        pass


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


# ---------------------------------------------------------------- 播放条 UI
# 播放控制条样式（仅作用于预览面板内控件）
_PLAY_SLIDER_QSS = """
QSlider { background: transparent; }
QSlider::groove:horizontal { height: 6px; background: #e9f2f1; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #39C5BB; border-radius: 3px; }
QSlider::handle:horizontal { width: 14px; height: 14px; margin: -4px 0;
    background: #ffffff; border: 2px solid #39C5BB; border-radius: 7px; }
QSlider::handle:horizontal:hover { background: #e6f7f6; }
QSlider::handle:horizontal:pressed { background: #ccfbf1; }
"""

_PLAY_BUTTON_QSS = """
QPushButton { background: #39C5BB; color: #ffffff; border: none;
    border-radius: 999px; padding: 5px 16px; font-size: 12px; font-weight: 600; }
QPushButton:hover { background: #0E948C; }
QPushButton:pressed { background: #0d7f78; }
QPushButton:disabled { background: #a8e3df; color: #f8fafc; }
"""

_TIME_LABEL_QSS = """
QLabel { color: #546b69; font-size: 12px; font-family: Consolas, "Courier New", monospace;
    min-width: 96px; }
"""


class PreviewPanel(QWidget):
    """卡片下方展开的视频预览面板（仅播放窗口，无网页加载）"""

    # 在线视频源就绪信号（代理已配置，可开始播放）
    online_ready = Signal()
    # 请求收起/关闭预览面板
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proxy_server = None
        self._proxy_port = 18889
        self._build_ui()

        # 本地播放器
        self._player = QMediaPlayer(self)
        self._player.setVideoOutput(self.video_widget)
        # 画面高度随视频实际宽高比自适应（16:9 / 4:3 / 竖屏均无两侧黑边）
        self._player.videoSink().videoSizeChanged.connect(self._on_video_size_changed)
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.errorOccurred.connect(self._on_error)

        self.online_ready.connect(self._on_online_ready)
        self._ensure_proxy()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        card = QFrame()
        card.setProperty("cssClass", "card")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        # 标题行
        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("视频预览")
        title.setProperty("cssClass", "sectionTitle")
        self.online_btn = QPushButton("在线预览")
        self.online_btn.setProperty("small", True)
        self.online_btn.setCheckable(True)
        self.online_btn.setChecked(True)
        self.local_btn = QPushButton("本地预览")
        self.local_btn.setProperty("small", True)
        self.local_btn.setCheckable(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.online_btn)
        mode_group.addButton(self.local_btn)
        self.online_btn.toggled.connect(lambda on: self._set_mode(0) if on else None)
        self.local_btn.toggled.connect(lambda on: self._set_mode(1) if on else None)
        self.close_btn = QPushButton("关闭")
        self.close_btn.setProperty("small", True)
        self.close_btn.clicked.connect(self.close_requested)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.online_btn)
        header.addWidget(self.local_btn)
        header.addWidget(self.close_btn)
        outer.addLayout(header)

        # 加载占位 / 播放器 两态
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background: transparent; }")

        loading_page = QWidget()
        loading_page.setStyleSheet("background: transparent;")
        load_lay = QVBoxLayout(loading_page)
        load_lay.setContentsMargins(0, 0, 0, 0)
        self.loading_label = QLabel("正在加载预览…")
        self.loading_label.setProperty("muted", True)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        load_lay.addWidget(self.loading_label)
        self.stack.addWidget(loading_page)

        player_page = QWidget()
        player_page.setStyleSheet("background: transparent;")
        player_lay = QVBoxLayout(player_page)
        player_lay.setContentsMargins(0, 0, 0, 0)
        player_lay.setSpacing(8)

        tool_row = QHBoxLayout()
        tool_row.setSpacing(8)
        self.open_btn = QPushButton("打开视频")
        self.open_btn.setProperty("small", True)
        self.open_btn.clicked.connect(self._open_local)
        self.local_name_label = QLabel("未加载视频")
        self.local_name_label.setProperty("muted", True)
        self.local_name_label.setWordWrap(True)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("B站链接，回车在线预览")
        self.url_input.setMaximumWidth(320)
        self.url_input.returnPressed.connect(self._load_online)
        self.load_btn = QPushButton("加载")
        self.load_btn.setProperty("small", True)
        self.load_btn.clicked.connect(self._load_online)
        tool_row.addWidget(self.open_btn)
        tool_row.addWidget(self.local_name_label, 1)
        tool_row.addWidget(self.url_input)
        tool_row.addWidget(self.load_btn)
        player_lay.addLayout(tool_row)

        self.video_widget = _PreviewVideoWidget()
        self.video_widget.setMinimumHeight(240)
        player_lay.addWidget(self.video_widget, 1)

        # 播放控制条：深色半透明底 + 圆角主色进度条 + 圆润播放按钮 + 等宽时间
        control_bar = QFrame()
        control_bar.setStyleSheet(
            "QFrame { background: rgba(31, 41, 55, 0.88); border-radius: 12px; }"
        )
        control_row = QHBoxLayout(control_bar)
        control_row.setContentsMargins(12, 8, 12, 8)
        control_row.setSpacing(10)
        self.play_btn = QPushButton("播放")
        self.play_btn.setStyleSheet(_PLAY_BUTTON_QSS)
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.clicked.connect(self._toggle_play)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.setStyleSheet(_PLAY_SLIDER_QSS)
        self.position_slider.sliderMoved.connect(self._seek)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setStyleSheet(_TIME_LABEL_QSS)
        control_row.addWidget(self.play_btn)
        control_row.addWidget(self.position_slider, 1)
        control_row.addWidget(self.time_label)
        player_lay.addWidget(control_bar)

        self.stack.addWidget(player_page)
        outer.addWidget(self.stack)

        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setContentsMargins(0, 0, 0, 0)
        self._outer_layout.addWidget(card)
        self._mode = 0

    # ---------------------------------------------------------------- 模式

    def _set_mode(self, index: int) -> None:
        """0=在线预览（播放代理流），1=本地预览（播放本地文件）"""
        self._mode = index
        if index == 1:
            self.stack.setCurrentIndex(1)
            if self._player.source().isEmpty():
                self.play_btn.setText("播放")

    def _show_loading(self, text: str) -> None:
        self.loading_label.setText(text)
        self.stack.setCurrentIndex(0)

    # ---------------------------------------------------------------- 本地预览

    def _open_local(self) -> None:
        start = config_manager.get_download_dir()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", start,
            "视频文件 (*.mp4 *.flv *.mkv *.webm *.mov);;所有文件 (*.*)",
        )
        if file_path:
            self.play_local_file(file_path)

    def play_local_file(self, path: str) -> None:
        logger.info(f"本地预览播放: {path}")
        self.stack.setCurrentIndex(1)
        self.local_btn.setChecked(True)
        self.online_btn.setChecked(False)
        self.local_name_label.setText(path)
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()

    def load_online_url(self, url: str) -> None:
        self.url_input.setText(url)
        self._load_online()

    # ---------------------------------------------------------------- 在线预览

    def _ensure_proxy(self) -> None:
        """启动本地流代理服务（常驻，应用退出时随线程结束）"""
        if self._proxy_server is not None:
            return
        for port in range(self._proxy_port, self._proxy_port + 10):
            try:
                server = _ThreadingHTTPServer(("127.0.0.1", port), _StreamProxyHandler)
                self._proxy_port = port
                self._proxy_server = server
                threading.Thread(target=server.serve_forever, daemon=True).start()
                logger.debug(f"流代理已启动: 127.0.0.1:{port}")
                return
            except OSError:
                continue
        logger.warning("流代理启动失败，在线预览将不可用")

    def _load_online(self) -> None:
        text = self.url_input.text().strip()
        if not text:
            return
        try:
            bvid = _extract_bvid(text)
        except ValueError as e:
            self.url_input.setText("")
            self.url_input.setPlaceholderText(str(e))
            return
        logger.info(f"在线预览加载: {bvid}")
        self.online_btn.setChecked(True)
        self.local_btn.setChecked(False)
        self._mode = 0
        self._show_loading(f"正在加载 {bvid} 的在线视频源…")
        thread = threading.Thread(target=self._online_worker, args=(bvid,), daemon=True)
        thread.start()

    def _online_worker(self, bvid: str) -> None:
        """工作线程：解析音视频合一的 durl 流地址并交给本地代理播放"""
        try:
            info = download_manager._video_info(bvid)
            cid = info.get("cid")
            if not cid:
                raise RuntimeError("未获取到视频 cid")
            api = (
                f"{download_manager.BASE_API}/x/player/playurl"
                f"?bvid={bvid}&cid={cid}&qn=32&fnval=0"
            )
            resp = requests.get(api, headers=download_manager._headers(bvid), timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 0:
                raise RuntimeError(f"播放地址获取失败: {payload.get('message', '未知错误')}")
            durl = (payload.get("data") or {}).get("durl") or []
            if not durl:
                raise RuntimeError("该视频暂无在线预览流（可等待下载完成后本地预览）")
            stream_url = durl[0]["url"]

            global _PROXY_STREAM_URL, _PROXY_STREAM_HEADERS
            _PROXY_STREAM_URL = stream_url
            _PROXY_STREAM_HEADERS = download_manager._headers(bvid)

            self.online_ready.emit()
        except Exception as e:
            logger.error(f"在线预览连接失败: {e}")
            self._show_loading(f"加载失败: {e}")

    def _on_online_ready(self) -> None:
        """在线视频源就绪：经本地代理实时播放，切换到播放器视图"""
        self._player.stop()
        self._player.setSource(QUrl(f"http://127.0.0.1:{self._proxy_port}/stream"))
        self._player.play()
        self.stack.setCurrentIndex(1)
        self.local_name_label.setText(f"在线预览 {self.url_input.text() or '视频'}")
        self.loading_label.setText("正在加载预览…")

    def _on_video_size_changed(self, *_args) -> None:
        """视频尺寸变化（PySide6 该信号不携带参数，主动查询）"""
        size = self._player.videoSink().videoSize()
        self.video_widget.set_video_size(size.width(), size.height())

    # ---------------------------------------------------------------- 播放控制

    def _toggle_play(self) -> None:
        if self._player.source().isEmpty():
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _seek(self, value: int) -> None:
        self._player.setPosition(value)

    def _on_position(self, pos: int) -> None:
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(pos)
        self.time_label.setText(f"{self._fmt(pos)} / {self._fmt(self._player.duration())}")

    def _on_duration(self, duration: int) -> None:
        self.position_slider.setRange(0, max(duration, 0))

    def _on_state(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_btn.setText(
            "暂停" if state == QMediaPlayer.PlaybackState.PlayingState else "播放"
        )

    def _on_error(self, error: QMediaPlayer.Error, error_string: str) -> None:
        logger.error(f"本地预览播放错误: {error_string}")
        self.local_name_label.setText(f"播放失败: {error_string}")
        self._show_loading(f"播放失败: {error_string}")

    @staticmethod
    def _fmt(ms: int) -> str:
        ms = max(int(ms or 0), 0)
        seconds = ms // 1000
        return f"{seconds // 60:02d}:{seconds % 60:02d}"
