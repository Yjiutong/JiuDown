"""
标签卡悬停低清小窗预览
鼠标悬停标签卡超过 0.5 秒弹出小窗，播放该视频的低清在线流（qn=16，失败回退 qn=32）；
鼠标移开自动关闭。独立于大预览面板的代理端口与全局状态，二者互不干扰。
"""

import http.server
import socketserver
import threading

import requests
from loguru import logger

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QFrame, QLabel, QStackedWidget, QVBoxLayout

from download_manager import download_manager
from pages.preview_panel import _extract_bvid

# 小窗专用流代理状态（独立于大预览面板的 _PROXY_STREAM_*）
_HOVER_STREAM_URL = ""
_HOVER_STREAM_HEADERS = {}
_HOVER_CACHE: dict[str, str] = {}  # bvid -> stream_url（会话内复用，避免反复请求）


class _HoverProxyHandler(http.server.BaseHTTPRequestHandler):
    """小窗流代理：转发 B 站低清流（携带鉴权头），支持 Range 透传"""

    def do_GET(self):
        try:
            req_h = dict(self.headers)
            # 过滤 hop-by-hop 头：播放器的 Host 指向本地代理，透传会给 B 站造成 403
            for k in ("Host", "Connection", "Accept-Encoding", "Proxy-Connection"):
                req_h.pop(k, None)
            req_h.update(_HOVER_STREAM_HEADERS)
            resp = requests.get(
                _HOVER_STREAM_URL, headers=req_h, stream=True, timeout=120
            )
            self.send_response(resp.status_code)
            for k, v in resp.headers.items():
                if k.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(k, v)
            self.end_headers()
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    self.wfile.write(chunk)
        except Exception:
            try:
                self.send_response(502)
                self.end_headers()
            except Exception:
                pass

    def log_message(self, *args):
        pass


class _HoverHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def _resolve_stream(bvid: str, qn: int) -> str | None:
    """解析指定清晰度的音视频合一 durl 流地址"""
    try:
        info = download_manager._video_info(bvid)
        cid = info.get("cid")
        if not cid:
            return None
        api = (
            f"{download_manager.BASE_API}/x/player/playurl"
            f"?bvid={bvid}&cid={cid}&qn={qn}&fnval=0"
        )
        resp = requests.get(api, headers=download_manager._headers(bvid), timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            return None
        durl = (payload.get("data") or {}).get("durl") or []
        return durl[0]["url"] if durl else None
    except Exception as e:
        logger.debug(f"低清流解析失败 qn={qn}: {e}")
        return None


class HoverPreview(QFrame):
    """无边框置顶小窗：加载态/播放器两态，播放低清代理流"""

    ready = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(
            "QFrame { background: #0b1220; border: 1px solid #39C5BB; border-radius: 10px; }"
        )
        self.setFixedSize(420, 248)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack)

        self.video = QVideoWidget()
        self.video.setStyleSheet("background: #0b1220;")
        self.stack.addWidget(self.video)

        msg_page = QFrame()
        msg_page.setStyleSheet("background: #0b1220;")
        msg_lay = QVBoxLayout(msg_page)
        self.msg_label = QLabel("正在加载低清预览…")
        self.msg_label.setStyleSheet("color: #e9f2f1; font-size: 12px;")
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_label.setWordWrap(True)
        msg_lay.addWidget(self.msg_label)
        self.stack.addWidget(msg_page)

        self._player = QMediaPlayer(self)
        self._player.setVideoOutput(self.video)
        self._player.errorOccurred.connect(self._on_error)
        self._proxy_server = None
        self._proxy_port = 18989
        self._ensure_proxy()
        self.stack.setCurrentIndex(1)

        self.ready.connect(self._play_ready)
        self.failed.connect(self._show_msg)

    # ---------------------------------------------------------------- 代理

    def _ensure_proxy(self) -> None:
        if self._proxy_server is not None:
            return
        for port in range(self._proxy_port, self._proxy_port + 10):
            try:
                server = _HoverHTTPServer(("127.0.0.1", port), _HoverProxyHandler)
                self._proxy_port = port
                self._proxy_server = server
                threading.Thread(target=server.serve_forever, daemon=True).start()
                logger.debug(f"小窗流代理已启动: 127.0.0.1:{port}")
                return
            except OSError:
                continue
        logger.warning("小窗流代理启动失败")

    # ---------------------------------------------------------------- 播放

    def show_preview(self, url: str) -> None:
        """解析并播放该链接的低清流"""
        self._player.stop()
        try:
            bvid = _extract_bvid(url)
        except ValueError as e:
            self._show_msg(str(e))
            return
        cached = _HOVER_CACHE.get(bvid)
        if cached:
            global _HOVER_STREAM_URL, _HOVER_STREAM_HEADERS
            _HOVER_STREAM_URL = cached
            _HOVER_STREAM_HEADERS = download_manager._headers(bvid)
            self._play_ready()
            return
        self._show_msg("正在加载低清预览…")
        threading.Thread(target=self._worker, args=(bvid,), daemon=True).start()

    def _worker(self, bvid: str) -> None:
        """工作线程：qn=16 优先，失败回退 qn=32；就绪后回主线程播放"""
        stream_url = None
        for qn in (16, 32):
            stream_url = _resolve_stream(bvid, qn)
            if stream_url:
                break
        if not stream_url:
            logger.warning(f"低清预览无可用流: {bvid}")
            self.failed.emit("暂无低清在线流（可下载完成后本地预览）")
            return
        _HOVER_CACHE[bvid] = stream_url
        global _HOVER_STREAM_URL, _HOVER_STREAM_HEADERS
        _HOVER_STREAM_URL = stream_url
        _HOVER_STREAM_HEADERS = download_manager._headers(bvid)
        self.ready.emit()

    def _play_ready(self) -> None:
        self._player.stop()
        self._player.setSource(QUrl(f"http://127.0.0.1:{self._proxy_port}/stream"))
        self._player.play()
        self.stack.setCurrentIndex(0)

    def _show_msg(self, text: str) -> None:
        self.msg_label.setText(text)
        self.stack.setCurrentIndex(1)

    def _on_error(self, error, error_string: str) -> None:
        logger.error(f"小窗预览播放错误: {error_string}")
        self._show_msg(f"播放失败: {error_string}")

    def hide_preview(self) -> None:
        self._player.stop()
        self.hide()
