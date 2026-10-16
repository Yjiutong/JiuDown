"""
标签卡悬停低清小窗预览
鼠标悬停标签卡超过 0.5 秒弹出小窗，播放该视频的低清在线流（qn=16，失败回退 qn=32）；
鼠标移开自动关闭。独立于大预览面板的代理端口与全局状态，二者互不干扰。

小窗版式（iPhone 浮窗美学）：
- 顶部标识栏：品牌圆点 + 视频标题（超宽自动省略）+ 「低清」徽章，深色圆角上沿
- 视频区按实际宽高比精确伸缩（无 letterbox 黑边），整窗圆角遮罩
- 出现位置与标签卡左边缘对齐、位于其正下方，并限制在屏幕内

生命周期（防孤儿弹窗）：鼠标移出小窗 250ms 后自隐藏（期间移回锚点标签则保留）；
锚点标签卡被删除/恢复/入队时连带退场；宿主页面隐藏时退场。
"""

import http.server
import socketserver
import threading

import requests
from loguru import logger

from PySide6.QtCore import Qt, QRect, QTimer, QUrl, Signal
from PySide6.QtGui import QRegion
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout

from download_manager import download_manager
from pages.preview_panel import _extract_bvid

# 小窗专用流代理状态（独立于大预览面板的 _PROXY_STREAM_*）
_HOVER_STREAM_URL = ""
_HOVER_STREAM_HEADERS = {}
_HOVER_CACHE: dict[str, tuple[str, str]] = {}  # bvid -> (stream_url, title)（会话内复用）


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


def _resolve_stream(bvid: str, cid: int, qn: int) -> str | None:
    """解析指定清晰度的音视频合一 durl 流地址"""
    try:
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


class _ElideLabel(QLabel):
    """宽度变化时自动以省略号截断的标签（小窗标题栏用）"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full = text

    def setFullText(self, text: str) -> None:
        self._full = text
        self._apply_elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        if not self._full:
            return
        width = max(self.width() - 2, 10)
        self.setText(
            self.fontMetrics().elidedText(
                self._full, Qt.TextElideMode.ElideRight, width
            )
        )


class HoverPreview(QFrame):
    """无边框置顶小窗：标识栏 + 低清播放器，视频按宽高比精确填满（无黑边）"""

    VIDEO_W = 400        # 视频区基准宽度
    CAPTION_H = 30       # 标识栏高度
    RADIUS = 10          # 整窗圆角
    MAX_VIDEO_H = 460    # 竖屏视频时视频区高度上限（超出则收窄宽度）

    ready = Signal(str)      # 标题（流就绪，回主线程播放）
    failed = Signal(str)     # 失败原因

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(
            f"""
            HoverPreview {{
                background: #0b1220;
                border: 1px solid rgba(57, 197, 187, 0.45);
            }}
            QFrame#hoverCaption {{
                background: #101a2c;
                border-top-left-radius: {self.RADIUS - 1}px;
                border-top-right-radius: {self.RADIUS - 1}px;
                border-bottom: 1px solid #1e2b3f;
            }}
            QLabel#hoverTitle {{ color: #e9f2f1; font-size: 11px; background: transparent; }}
            QLabel#hoverBadge {{
                color: #8fe8de; background: rgba(57, 197, 187, 0.16);
                border-radius: 999px; padding: 1px 7px; font-size: 10px; font-weight: 600;
            }}
            QLabel#hoverDot {{ background: #39C5BB; border-radius: 3px; }}
            """
        )
        self._ratio_w = 16
        self._ratio_h = 9
        self._anchor = None
        self._bvid = ""          # 当前预览的 bvid（供锚点移除时比对）
        self._hide_timer: QTimer | None = None
        self._build_ui()
        self._apply_size()

        self._player = QMediaPlayer(self)
        self._player.setVideoOutput(self.video)
        self._player.errorOccurred.connect(self._on_error)
        self._player.videoSink().videoSizeChanged.connect(self._on_video_size_changed)
        self._proxy_server = None
        self._proxy_port = 18989
        self._ensure_proxy()
        self.stack.setCurrentIndex(1)

        self.ready.connect(self._play_ready)
        self.failed.connect(self._show_msg)

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 标识栏：品牌圆点 + 标题 + 低清徽章
        caption = QFrame()
        caption.setObjectName("hoverCaption")
        caption.setFixedHeight(self.CAPTION_H)
        cap_lay = QHBoxLayout(caption)
        cap_lay.setContentsMargins(10, 0, 8, 0)
        cap_lay.setSpacing(7)
        dot = QLabel()
        dot.setObjectName("hoverDot")
        dot.setFixedSize(6, 6)
        self.caption_title = _ElideLabel("")
        self.caption_title.setObjectName("hoverTitle")
        badge = QLabel("低清")
        badge.setObjectName("hoverBadge")
        cap_lay.addWidget(dot)
        cap_lay.addWidget(self.caption_title, 1)
        cap_lay.addWidget(badge)
        lay.addWidget(caption)

        # 视频 / 消息 两态
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background: transparent; }")
        lay.addWidget(self.stack)

        self.video = QVideoWidget()
        self.video.setStyleSheet("background: #0b1220;")
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.stack.addWidget(self.video)

        msg_page = QFrame()
        msg_page.setStyleSheet("background: #0b1220;")
        msg_lay = QVBoxLayout(msg_page)
        msg_lay.setContentsMargins(20, 0, 20, 0)
        self.msg_label = QLabel("正在加载低清预览…")
        self.msg_label.setStyleSheet("color: #e9f2f1; font-size: 12px;")
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_label.setWordWrap(True)
        msg_lay.addWidget(self.msg_label)
        self.stack.addWidget(msg_page)

    # ---------------------------------------------------------------- 尺寸与位置

    def _apply_size(self) -> None:
        """按视频宽高比计算整窗尺寸：宽度基准 400，过高则收窄（始终无黑边）"""
        video_h = round(self.VIDEO_W * self._ratio_h / self._ratio_w)
        if video_h > self.MAX_VIDEO_H:
            video_h = self.MAX_VIDEO_H
            video_w = round(self.MAX_VIDEO_H * self._ratio_w / self._ratio_h)
        else:
            video_w = self.VIDEO_W
        w, h = video_w, self.CAPTION_H + video_h
        if self.width() != w or self.height() != h:
            self.setFixedSize(w, h)
            # 未 show 时 setFixedSize 不触发 resizeEvent，此处显式补打遮罩
            self._apply_mask()
            self._replace_near()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_mask()
        self._replace_near()

    def enterEvent(self, event) -> None:
        """鼠标移入小窗：取消自杀计时（允许移到窗内停留查看）"""
        self._stop_self_hide()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """鼠标移出小窗：短暂缓冲后自隐藏——若期间回到锚点标签则保留

        没有这一步，鼠标经小窗“中转”离开标签卡后小窗将永远滞留屏幕
        （标签卡已提供 350ms 同向宽限，此处只补小窗自身出方向的检测）。
        """
        self._schedule_self_hide()
        super().leaveEvent(event)

    def _schedule_self_hide(self) -> None:
        if self._hide_timer is None:
            self._hide_timer = QTimer(self)
            self._hide_timer.setSingleShot(True)
            self._hide_timer.setInterval(250)
            self._hide_timer.timeout.connect(self._self_hide_check)
        self._hide_timer.start()

    def _stop_self_hide(self) -> None:
        if self._hide_timer is not None:
            self._hide_timer.stop()

    def _self_hide_check(self) -> None:
        """缓冲到点：鼠标既不在小窗、也不在锚点标签上，才收起"""
        if not self.isVisible() or self.underMouse():
            return
        anchor = self._anchor
        if anchor is not None:
            try:
                if anchor.underMouse():
                    return  # 正移回锚点标签：保留小窗
            except RuntimeError:
                self._anchor = None  # 锚点已被删除：视为不在其上
        self.hide_preview()

    def serving(self, url: str) -> bool:
        """小窗是否正在预览该链接（供标签卡移除时判断是否连带退场）"""
        if not self._bvid:
            return False
        try:
            return self._bvid == _extract_bvid(url)
        except ValueError:
            return False

    def _apply_mask(self) -> None:
        """整窗圆角遮罩：视频四角随之收圆（子控件不受父级圆角裁剪，须显式遮罩）"""
        r = self.RADIUS
        w, h = self.width(), self.height()
        region = QRegion(QRect(0, r, w, h - 2 * r))
        region += QRegion(QRect(r, 0, w - 2 * r, r))
        region += QRegion(QRect(r, h - r, w - 2 * r, r))
        # 四角：r×r 方块 ∩ 2r×2r 椭圆（椭圆心在内侧 (r,r) 处）= 四分圆
        region += QRegion(QRect(0, 0, r, r)) & QRegion(
            QRect(0, 0, 2 * r, 2 * r), QRegion.RegionType.Ellipse)
        region += QRegion(QRect(w - r, 0, r, r)) & QRegion(
            QRect(w - 2 * r, 0, 2 * r, 2 * r), QRegion.RegionType.Ellipse)
        region += QRegion(QRect(0, h - r, r, r)) & QRegion(
            QRect(0, h - 2 * r, 2 * r, 2 * r), QRegion.RegionType.Ellipse)
        region += QRegion(QRect(w - r, h - r, r, r)) & QRegion(
            QRect(w - 2 * r, h - 2 * r, 2 * r, 2 * r), QRegion.RegionType.Ellipse)
        self.setMask(region)

    def place_near(self, anchor) -> None:
        """记录锚点并把小窗放到其正下方：左边缘对齐、间距 8px，屏幕内收敛"""
        self._anchor = anchor
        self._replace_near()

    def _replace_near(self) -> None:
        anchor = self._anchor
        if anchor is None:
            return
        try:
            bottom_left = anchor.mapToGlobal(anchor.rect().bottomLeft())
        except RuntimeError:
            # 锚点控件已被删除（如标签卡入队/删除）：清掉引用避免后续崩溃
            self._anchor = None
            return
        x, y = bottom_left.x(), bottom_left.y() + 8
        screen = self.screen()
        if screen is not None:
            geo = screen.availableGeometry()
            if x + self.width() > geo.right():
                x = geo.right() - self.width()
            if y + self.height() > geo.bottom():
                y = bottom_left.y() - self.height() - 8
            x = max(x, geo.left())
            y = max(y, geo.top())
        self.move(x, y)

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
        try:
            bvid = _extract_bvid(url)
        except ValueError as e:
            self._show_msg(str(e))
            return
        # 同一视频正在播放中：不重复解析/重播（避免鼠标在标签卡上移动时画面重启）
        if (self.isVisible() and self._bvid == bvid
                and self.stack.currentIndex() == 0):
            return
        self._player.stop()
        self._bvid = bvid
        self.caption_title.setFullText(bvid)
        cached = _HOVER_CACHE.get(bvid)
        if cached:
            stream_url, title = cached
            global _HOVER_STREAM_URL, _HOVER_STREAM_HEADERS
            _HOVER_STREAM_URL = stream_url
            _HOVER_STREAM_HEADERS = download_manager._headers(bvid)
            self._play_ready(title)
            return
        self._show_msg("正在加载低清预览…")
        threading.Thread(target=self._worker, args=(bvid,), daemon=True).start()

    def _worker(self, bvid: str) -> None:
        """工作线程：取视频信息（标题/cid）→ qn=16 优先，失败回退 qn=32"""
        try:
            info = download_manager._video_info(bvid)
            cid = info.get("cid")
            title = info.get("title") or bvid
        except Exception as e:
            logger.debug(f"低清预览获取视频信息失败: {e}")
            self.failed.emit("视频信息获取失败（可下载完成后本地预览）")
            return
        if not cid:
            self.failed.emit("未获取到视频 cid")
            return
        stream_url = None
        for qn in (16, 32):
            stream_url = _resolve_stream(bvid, cid, qn)
            if stream_url:
                break
        if not stream_url:
            logger.warning(f"低清预览无可用流: {bvid}")
            self.failed.emit("暂无低清在线流（可下载完成后本地预览）")
            return
        _HOVER_CACHE[bvid] = (stream_url, title)
        global _HOVER_STREAM_URL, _HOVER_STREAM_HEADERS
        _HOVER_STREAM_URL = stream_url
        _HOVER_STREAM_HEADERS = download_manager._headers(bvid)
        self.ready.emit(title)

    def _play_ready(self, title: str = "") -> None:
        self._player.stop()
        self._player.setSource(QUrl(f"http://127.0.0.1:{self._proxy_port}/stream"))
        self._player.play()
        self.stack.setCurrentIndex(0)
        if title:
            self.caption_title.setFullText(title)

    def _show_msg(self, text: str) -> None:
        self.msg_label.setText(text)
        self.stack.setCurrentIndex(1)

    def _on_error(self, error, error_string: str) -> None:
        logger.error(f"小窗预览播放错误: {error_string}")
        self._show_msg(f"播放失败: {error_string}")

    def _on_video_size_changed(self, *_args) -> None:
        """视频尺寸变化（PySide6 该信号不携带参数，主动查询）：按比例整窗伸缩"""
        size = self._player.videoSink().videoSize()
        if size.width() > 0 and size.height() > 0:
            if (size.width(), size.height()) != (self._ratio_w, self._ratio_h):
                self._ratio_w, self._ratio_h = size.width(), size.height()
                self._apply_size()

    def hide_preview(self) -> None:
        self._player.stop()
        self._stop_self_hide()
        self._anchor = None   # 锚点引用清掉：防止指向已删除的标签卡
        self._bvid = ""
        self.hide()
