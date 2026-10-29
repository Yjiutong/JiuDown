"""
下载页（站点无关）
链接批量输入（任意 yt-dlp 支持的站点）、画质/格式/保存目录设置、多任务进度卡片
"""

import queue
import threading
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QDesktopServices, QMouseEvent, QPainter,
    QPen, QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QTextEdit, QVBoxLayout, QWidget,
)

from loguru import logger

import ffmpeg_manager
import jiudown_engine
from config_manager import config_manager
from download_manager import download_manager, download_log_manager
from pages.preview_panel import PreviewPanel
from theme import C
# 画质/格式档位由引擎统一定义，避免 UI 与引擎各写一份导致漂移
from jiudown_engine import FORMAT_CHOICES as FORMATS, QUALITY_CHOICES as QUALITIES
from jiudown_engine import normalize_url as _engine_normalize_url
from jiudown_engine import pick_default_level

AUDIO_FORMATS = {"mp3", "wav"}
CHANNELS = ["单声道", "双声道"]


def normalize_url(raw: str) -> str:
    """兼容旧引用：实现已上移到 jiudown_engine，预览面板与下载页共用同一套判定"""
    return _engine_normalize_url(raw)


# ---------------------------------------------------------------- 档位解析（后台）
# 卡片要显示标题、并按视频真实提供的档位让人选清晰度，必然要多一次网络解析。
# 沿用项目既有约定：后台线程只写纯数据，主线程用 QTimer 取走——线程回调到
# 可能已被删掉的卡片上会段错误（卡片随时能被删除/双击收回）。

_RESOLUTIONS: "queue.Queue[tuple[str, dict]]" = queue.Queue()
_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_INFLIGHT: set[str] = set()
_CACHE_LOCK = threading.Lock()
_CACHE_LIMIT = 64


def _resolve_worker(url: str) -> None:
    try:
        payload = {"ok": True, "info": jiudown_engine.list_levels(url)}
    except Exception as e:
        payload = {"ok": False, "error": str(e)}
        logger.info(f"链接档位解析失败: {url} - {e}")
    with _CACHE_LOCK:
        _INFLIGHT.discard(url)
    _RESOLUTIONS.put((url, payload))


def _cached_resolution(url: str) -> dict | None:
    with _CACHE_LOCK:
        return _CACHE.get(url)


def _start_resolution(url: str) -> None:
    """同一链接只解析一次；结果进缓存，重复粘贴不再走网络"""
    with _CACHE_LOCK:
        if url in _INFLIGHT or url in _CACHE:
            return
        _INFLIGHT.add(url)
    threading.Thread(target=_resolve_worker, args=(url,), daemon=True).start()


STATUS_BADGE = {
    "queued": ("gray", "等待中"),
    "preparing": ("orange", "准备中"),
    "downloading": ("blue", "下载中"),
    "merging": ("cyan", "合并中"),
    "completed": ("green", "已完成"),
    "failed": ("red", "失败"),
    "cancelled": ("gray", "已取消"),
}

PROGRESS_COLOR = {
    "completed": "green",
    "failed": "red",
    "merging": "orange",
}

PARSING_HINT = "正在解析标题与该视频提供的清晰度…"


class UrlInputEdit(QTextEdit):
    """链接输入框：按回车将当前全部非空行提交为标签卡（Shift+Enter 换行）"""

    committed = Signal(str)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.committed.emit(self.toPlainText())
            event.accept()
            return
        super().keyPressEvent(event)


class _DeleteIconButton(QPushButton):
    """自绘删除图标按钮（iPhone 美学）：圆头 × 双笔触 + 悬停/按下红底

    不用文本 "×"：部分系统字体缺该字形会渲染成豆腐块；自绘同时获得
    与标题栏按钮一致的悬停反馈。笔触在 48 画布上绘制（DPR=2），24px
    显示尺寸下保持清晰。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("")  # 无提示气泡：悬停时不该被气泡遮挡预览画面
        self._hover = False
        self._pressed = False

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # 底色：常态浅灰（给出可点击的按钮形态）→ 悬停淡红 → 按下加深
        if self._pressed:
            bg = QColor(C["red"])
            bg.setAlphaF(0.18)
        elif self._hover:
            bg = QColor(C["red"])
            bg.setAlphaF(0.10)
        else:
            bg = QColor(C["gray_bg"])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, w, h), w * 0.30, w * 0.30)
        # 字形：圆头 ×，按按钮实际尺寸绘制（此前用 48 画布坐标未缩放，被裁成一道斜杠）
        glyph = C["red_dark"] if self._pressed else (
            C["red"] if self._hover else C["text_muted"]
        )
        pen = QPen(QColor(glyph), max(2.0, w * 0.095))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        inset = w * 0.31
        p.drawLine(QPointF(inset, inset), QPointF(w - inset, h - inset))
        p.drawLine(QPointF(w - inset, inset), QPointF(inset, h - inset))
        p.end()


class TagCard(QFrame):
    """链接卡片：回车即解析标题与该视频真实提供的清晰度档位

    卡片主文字是标题而不是链接（原地址在右键「查看链接」里看）；清晰度只列视频
    真有的档位——老片没有 1080P 就不出现 1080P，也不再出现下载器够不着的高码率档。
    悬停超过 0.5 秒仍弹出低清小窗预览。
    """

    restore_requested = Signal(str)         # url
    delete_requested = Signal(str)          # url
    config_changed = Signal(str, str, str)  # url, quality, format
    preview_requested = Signal(str)         # url
    hover_requested = Signal(str)           # url（悬停 0.5s 触发）
    hover_left = Signal()                   # 鼠标移出
    reparse_requested = Signal(str)         # url

    def __init__(self, url: str, quality: str, file_format: str, parent=None):
        super().__init__(parent)
        self.setProperty("cssClass", "card")
        # 不设 tooltip：悬停标签卡应弹出低清预览，提示气泡会盖住预览画面
        self.url = url
        self.title = ""
        self.quality = quality
        self.file_format = file_format
        self.levels: list[dict] = []
        self.level: dict | None = None
        self.state = "parsing"          # parsing / ready / failed
        self.error = ""
        self._hover_timer: QTimer | None = None

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(14, 8, 14, 8)
        vbox.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.title_label = QLabel(url)
        self.title_label.setProperty("cssClass", "taskTitle")
        # 不设 tooltip：悬停标签卡要弹低清预览，气泡会盖住画面；完整标题看右键「查看链接」
        self.title_label.setWordWrap(True)
        self.format_badge = QLabel(file_format)
        self.format_badge.setProperty("cssClass", "badgeCyan")
        self.quality_badge = QLabel(quality)
        self.quality_badge.setProperty("cssClass", "badgeGray")
        delete_btn = _DeleteIconButton()
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.url))
        row.addWidget(self.title_label, 1)
        row.addWidget(self.format_badge)
        row.addWidget(self.quality_badge)
        row.addWidget(delete_btn)
        vbox.addLayout(row)

        self.detail_label = QLabel(PARSING_HINT)
        self.detail_label.setProperty("cssClass", "taskMeta")
        self.detail_label.setWordWrap(True)
        vbox.addWidget(self.detail_label)

    # ---------------------------------------------------------------- 状态

    def set_config(self, quality: str, file_format: str) -> None:
        self.quality = quality
        self.file_format = file_format
        self.format_badge.setText(file_format)
        self.quality_badge.setText(quality)

    def apply_resolution(self, payload: dict, tier: str) -> None:
        """回填后台解析结果；tier 是设置里的默认档位，落到视频真实提供的档"""
        if not payload.get("ok"):
            self.state = "failed"
            self.error = str(payload.get("error") or "解析失败")
            self.detail_label.setText(f"解析失败：{self.error}（右键可重新解析或按档位名近似下载）")
            return
        info = payload.get("info") or {}
        self.state = "ready"
        self.title = str(info.get("title") or "")
        self.levels = list(info.get("levels") or [])
        self.title_label.setText(self.title or self.url)
        if self.file_format not in AUDIO_FORMATS:
            self.select_level(pick_default_level(self.levels, tier))
        self.detail_label.setText(self._levels_summary())

    def _levels_summary(self) -> str:
        if not self.levels:
            return "该链接没有可选的清晰度档位（按默认档位下载）"
        locked = [lv for lv in self.levels if not lv.get("available", True)]
        labels = [lv["label"] for lv in self.levels]
        shown = " / ".join(labels[:5]) + (" …" if len(labels) > 5 else "")
        text = f"档位（{len(labels)}）：{shown}"
        if locked:
            text += f"（其中 {len(locked)} 档原生链路暂未返回，选中后走通用后端）"
        return text

    # ---------------------------------------------------------------- 选择

    def select_level(self, level: dict | None) -> None:
        self.level = level
        if level is not None:
            self.set_config(str(level.get("label") or self.quality), self.file_format)

    def set_format(self, f: str) -> None:
        if f == self.file_format:
            return
        self.file_format = f
        if f in AUDIO_FORMATS:
            self.quality = "双声道" if self.quality not in CHANNELS else self.quality
            self.level = None
        elif self.quality in CHANNELS:
            # 从音频切回视频：重新落到默认档
            self.quality = config_manager.get_default_quality()
            if self.state == "ready":
                self.select_level(pick_default_level(self.levels, self.quality))
        else:
            # mp4 ↔ flv 之间切换：保住用户已经挑好的那一档，别退回默认档
            keep = next((lv for lv in self.levels if lv.get("label") == self.quality), None)
            if keep is not None:
                self.select_level(keep)
        self.set_config(self.quality, f)
        self.config_changed.emit(self.url, self.quality, self.file_format)

    def choose_level(self, level: dict) -> None:
        self.select_level(level)
        self.config_changed.emit(self.url, self.quality, self.file_format)

    def choose_channel(self, channel: str) -> None:
        if channel == self.quality:
            return
        self.level = None
        self.set_config(channel, self.file_format)
        self.config_changed.emit(self.url, self.quality, self.file_format)

    # ---------------------------------------------------------------- 交互

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.restore_requested.emit(self.url)
        super().mouseDoubleClickEvent(event)

    def enterEvent(self, event) -> None:
        """悬停 0.5 秒后请求弹出低清小窗预览"""
        if self._hover_timer is None:
            self._hover_timer = QTimer(self)
            self._hover_timer.setSingleShot(True)
            self._hover_timer.setInterval(500)
            self._hover_timer.timeout.connect(
                lambda: self.hover_requested.emit(self.url)
            )
        self._hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_timer is not None:
            self._hover_timer.stop()
        self.hover_left.emit()
        super().leaveEvent(event)

    def contextMenuEvent(self, event) -> None:
        # 挂到顶层窗口而不是标签卡本身：QMenu 是独立弹出窗口，若父链上有控件级
        # setStyleSheet（裸声明会级联），菜单背景会被覆盖成透明 → 黑底看不清字
        menu = QMenu(self.window())
        fmt_menu = menu.addMenu(f"格式: {self.file_format}")
        fmt_group = QActionGroup(menu)
        fmt_group.setExclusive(True)
        for f in FORMATS:
            act = QAction(f, menu)
            act.setCheckable(True)
            act.setChecked(f == self.file_format)
            act.triggered.connect(lambda _=False, f=f: self.set_format(f))
            # 当前 ffmpeg 做不到的格式置灰（如精简版的 flv / wav）
            if not ffmpeg_manager.format_supported(f):
                act.setEnabled(False)
                act.setToolTip("当前 FFmpeg 无法输出该格式（完整版就绪后可用）")
            fmt_group.addAction(act)
            fmt_menu.addAction(act)

        if self.file_format in AUDIO_FORMATS:
            param_menu = menu.addMenu(f"声道: {self.quality}")
            param_group = QActionGroup(menu)
            param_group.setExclusive(True)
            mono_ok = ffmpeg_manager.mono_supported()
            for channel in CHANNELS:
                act = QAction(channel, menu)
                act.setCheckable(True)
                act.setChecked(channel == self.quality)
                act.triggered.connect(lambda _=False, c=channel: self.choose_channel(c))
                if channel == "单声道" and not mono_ok:
                    act.setEnabled(False)
                    act.setToolTip("当前 FFmpeg 不支持单声道重采样")
                param_group.addAction(act)
                param_menu.addAction(act)
        else:
            menu.addAction(self._build_quality_menu(menu))

        menu.addSeparator()
        link_act = QAction("查看链接", menu)
        link_act.triggered.connect(self._show_link)
        menu.addAction(link_act)
        if self.state != "parsing":
            again_act = QAction("重新解析档位", menu)
            again_act.triggered.connect(lambda: self.reparse_requested.emit(self.url))
            menu.addAction(again_act)
        preview_act = QAction("预览", menu)
        preview_act.triggered.connect(lambda: self.preview_requested.emit(self.url))
        menu.addAction(preview_act)
        delete_act = QAction("删除", menu)
        delete_act.triggered.connect(lambda: self.delete_requested.emit(self.url))
        menu.addAction(delete_act)
        menu.exec(event.globalPos())

    def _build_quality_menu(self, parent_menu: QMenu) -> QAction:
        """清晰度子菜单只列该视频真实提供的档位"""
        current = self.quality
        if self.state == "parsing":
            title = f"清晰度: {current}（解析中）"
        elif self.levels:
            title = f"清晰度: {current}"
        else:
            title = f"质量: {current}"
        param_menu = parent_menu.addMenu(title)
        param_group = QActionGroup(param_menu)
        param_group.setExclusive(True)

        if not self.levels:
            for p in QUALITIES:
                act = QAction(p, param_menu)
                act.setCheckable(True)
                act.setChecked(p == current)
                act.triggered.connect(lambda _=False, p=p: self._choose_tier(p))
                param_group.addAction(act)
                param_menu.addAction(act)
            return param_menu.menuAction()

        for lv in self.levels:
            label = str(lv.get("label") or "")
            act = QAction(label, param_menu)
            act.setCheckable(True)
            act.setChecked(label == current)
            act.setData(lv)
            act.triggered.connect(lambda _=False, lv=lv: self.choose_level(lv))
            if not lv.get("available", True):
                # 不置灰：原生链路暂未下发不等于下载不到（通用后端常能取到更高档），
                # 只在提示里讲清楚，真取不到时下载会明确报错而不是偷偷降档
                act.setText(f"{label} ·原生暂未返回")
                act.setToolTip(lv.get("reason") or "原生链路暂未返回该档，选中后由通用后端尝试")
            param_group.addAction(act)
            param_menu.addAction(act)
        return param_menu.menuAction()

    def _choose_tier(self, tier: str) -> None:
        """解析没成功时退回按档位名近似下载"""
        if tier == self.quality:
            return
        self.level = None
        self.set_config(tier, self.file_format)
        self.config_changed.emit(self.url, self.quality, self.file_format)

    def _show_link(self) -> None:
        box = QMessageBox(self.window())
        box.setWindowTitle("链接")
        box.setText(self.title or "（未解析到标题）")
        box.setInformativeText(self.url)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        copy_btn = box.addButton("复制链接", QMessageBox.ButtonRole.ActionRole)
        box.exec()
        if box.clickedButton() is copy_btn:
            QApplication.clipboard().setText(self.url)
            self.detail_label.setText("链接已复制到剪贴板")


class TaskCard(QFrame):
    """单个下载任务卡片：右侧格式/清晰度下拉，点击预览在卡片下方展开

    清晰度下拉来自链接卡片解析出的该视频真实档位（task["levels"]）；没有解析结果
    时才退回引擎的粗档位名。
    """

    clicked = Signal(str)
    config_changed = Signal(str, str, str)  # task_id, quality, format

    def __init__(self, task_id: str, parent=None):
        super().__init__(parent)
        self.setProperty("cssClass", "card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击预览该视频")
        self.task_id = task_id
        self.levels: list[dict] = []

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(16, 12, 16, 12)
        vbox.setSpacing(8)

        # 第一行：标题 + 格式下拉 + 质量下拉 + 徽章
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title_label = QLabel("等待解析标题...")
        self.title_label.setProperty("cssClass", "taskTitle")
        self.title_label.setWordWrap(True)
        self.format_combo = QComboBox()
        self.format_combo.addItems(FORMATS)
        self.format_combo.setMinimumWidth(72)
        self.format_combo.setMaximumWidth(88)
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(QUALITIES)
        self.quality_combo.setMinimumWidth(104)
        self.quality_combo.setMaximumWidth(170)
        self.badge_label = QLabel("等待中")
        self.badge_label.setProperty("cssClass", "badge")
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        self.quality_combo.currentIndexChanged.connect(self._emit_config)
        top.addWidget(self.title_label, 1)
        top.addWidget(self.format_combo)
        top.addWidget(self.quality_combo)
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
        self.preview_button = QPushButton("预览")
        self.preview_button.setProperty("small", True)
        self.open_button = QPushButton("打开文件夹")
        self.open_button.setProperty("small", True)
        bottom.addWidget(self.detail_label, 1)
        bottom.addWidget(self.retry_button)
        bottom.addWidget(self.delete_button)
        bottom.addWidget(self.preview_button)
        bottom.addWidget(self.open_button)
        vbox.addLayout(bottom)

    def _on_format_changed(self, *_args) -> None:
        """格式切换：mp3 时质量下拉切换为声道选择（默认双声道）"""
        self._sync_quality_items()
        self._emit_config()

    def _quality_items(self) -> list[str]:
        if self.format_combo.currentText() in AUDIO_FORMATS:
            return CHANNELS
        labels = [str(lv.get("label") or "") for lv in self.levels if lv.get("label")]
        return labels or QUALITIES

    def _sync_quality_items(self, keep: str = "") -> None:
        is_audio = self.format_combo.currentText() in AUDIO_FORMATS
        items = self._quality_items()
        if [self.quality_combo.itemText(i) for i in range(self.quality_combo.count())] == items:
            return
        current = keep or self.quality_combo.currentText()
        if is_audio:
            fallback = "双声道"
        else:
            default = pick_default_level(self.levels, config_manager.get_default_quality())
            fallback = str((default or {}).get("label") or config_manager.get_default_quality())
        target = current if current in items else fallback
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()
        self.quality_combo.addItems(items)
        if target in items:
            self.quality_combo.setCurrentText(target)
        self._apply_level_hints()
        self.quality_combo.blockSignals(False)

    def _apply_level_hints(self) -> None:
        """原生链路暂未返回的档位：下拉里只挂提示，不置灰

        「原生这次没给」不等于「下载不到」（同档位常能由通用后端取到），置灰会误伤；
        真取不到时下载会明确报错，不会静默降档。
        """
        hints = {
            str(lv.get("label") or ""): str(lv.get("reason") or "原生链路暂未返回该档")
            for lv in self.levels if not lv.get("available", True)
        }
        for i in range(self.quality_combo.count()):
            self.quality_combo.setItemData(
                i, hints.get(self.quality_combo.itemText(i), ""),
                Qt.ItemDataRole.ToolTipRole,
            )

    def _emit_config(self, *_args) -> None:
        self.config_changed.emit(
            self.task_id,
            self.quality_combo.currentText(),
            self.format_combo.currentText(),
        )

    def _set_badge(self, tone: str, text: str) -> None:
        self.badge_label.setText(text)
        self.badge_label.setProperty("cssClass", f"badge{tone.capitalize()}")
        self.badge_label.style().unpolish(self.badge_label)
        self.badge_label.style().polish(self.badge_label)

    def update_task(self, task: dict) -> None:
        self.title_label.setText(task.get("title") or "等待解析标题...")

        # 同步下拉显示（不触发 config_changed）
        fmt = task.get("format") or "mp4"
        quality = task.get("quality") or ("720P" if fmt not in AUDIO_FORMATS else "双声道")
        self.levels = list(task.get("levels") or [])
        self.format_combo.blockSignals(True)
        if fmt in FORMATS:
            self.format_combo.setCurrentText(fmt)
        self.format_combo.blockSignals(False)
        self._sync_quality_items(keep=quality)

        status = task.get("status", "queued")
        tone, text = STATUS_BADGE.get(status, ("gray", status))
        self._set_badge(tone, text)

        progress = min(max(float(task.get("progress") or 0), 0), 100)
        self.progress_bar.setValue(int(progress * 10))
        color = PROGRESS_COLOR.get(status, "blue")
        self.progress_bar.setProperty("color", color)
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)

        meta_bits = []
        if task.get("extractor"):
            meta_bits.append(str(task["extractor"]))
        if task.get("duration"):
            meta_bits.append(download_manager.format_duration(task["duration"]))
        if int(task.get("playlist_count") or 0) > 1:
            meta_bits.append(f"合集 {task['playlist_count']} 项")
        meta = " · ".join(meta_bits)

        if status in ("downloading", "merging") and task.get("total_size"):
            downloaded = task.get("downloaded_size") or 0
            total = task.get("total_size") or 0
            speed = task.get("speed") or 0
            detail = (
                f"{download_manager.format_file_size(downloaded)} / "
                f"{download_manager.format_file_size(total)}"
            )
            if speed:
                detail += f" | {download_manager.format_speed(speed)}"
            self.detail_label.setText(f"{meta} · {detail}" if meta else detail)
            self.detail_label.setProperty("cssClass", "taskDetail")
        elif status == "completed":
            size_text = download_manager.format_file_size(task.get("total_size") or 0)
            self.detail_label.setText(f"{meta} · {size_text}" if meta else size_text)
            self.detail_label.setProperty("cssClass", "taskDetail")
        elif status == "failed":
            self.detail_label.setText(task.get("error", ""))
            self.detail_label.setProperty("cssClass", "taskError")
        else:
            self.detail_label.setText(meta)
            self.detail_label.setProperty("cssClass", "taskDetail")
        self.detail_label.style().unpolish(self.detail_label)
        self.detail_label.style().polish(self.detail_label)

        self.retry_button.setVisible(status == "failed")
        self.open_button.setVisible(
            status == "completed"
            and bool(task.get("output_path"))
            and Path(task["output_path"]).exists()
        )
        self.preview_button.setVisible(True)
        self.delete_button.setVisible(status not in ("preparing", "downloading", "merging"))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.task_id)
        super().mousePressEvent(event)


class DownloadPage(QWidget):
    """视频下载页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: dict[str, TaskCard] = {}
        self._tag_cards: list[TagCard] = []
        self._tag_preview_url: str | None = None
        self._hover: "HoverPreview | None" = None
        self._forced_fallback = False   # 格式是否因 ffmpeg 能力被强制回退过
        self._build_ui()

        # FFmpeg 完整版就绪后重新门控格式/声道 + 同步提示条
        ffmpeg_manager.signals.capabilities_changed.connect(
            self._on_ffmpeg_capabilities_changed
        )
        ffmpeg_manager.signals.progress.connect(
            lambda _p: self._refresh_ffmpeg_notice()
        )
        ffmpeg_manager.signals.finished.connect(
            lambda _ok, _msg: self._refresh_ffmpeg_notice()
        )
        self._refresh_ffmpeg_notice()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_tasks)
        self._timer.start(1000)
        self._refresh_tasks()

        # 后台解析结果只落在纯数据队列里，主线程按 200ms 取走回填卡片
        self._resolve_timer = QTimer(self)
        self._resolve_timer.timeout.connect(self._drain_resolutions)
        self._resolve_timer.start(200)

    # ---------------------------------------------------------------- 档位解析

    def _drain_resolutions(self) -> None:
        if _RESOLUTIONS.empty():
            return
        tier = config_manager.get_default_quality()
        while True:
            try:
                url, payload = _RESOLUTIONS.get_nowait()
            except queue.Empty:
                return
            with _CACHE_LOCK:
                _CACHE[url] = payload
                _CACHE.move_to_end(url)
                while len(_CACHE) > _CACHE_LIMIT:
                    _CACHE.popitem(last=False)
            for card in list(self._tag_cards):
                if card.url == url:
                    card.apply_resolution(payload, tier)

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        # 整页一体滚动：输入卡片 + 任务列表 + 预览面板都在同一滚动区内
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        # ---- 输入区（随页面滚动） ----
        input_card = QFrame()
        input_card.setProperty("cssClass", "card")
        # 卡片高度固定为内容需求，防止被滚动区拉伸造成内部空白
        input_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.input_card = input_card
        input_vbox = QVBoxLayout(input_card)
        input_vbox.setContentsMargins(16, 10, 16, 12)
        input_vbox.setSpacing(8)

        input_title = QLabel("添加下载任务")
        input_title.setProperty("cssClass", "sectionTitle")
        # 固定标题行高，避免 Qt 布局在滚动容器中把标题拉伸出异常高度
        input_title.setFixedHeight(22)
        input_title.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        input_vbox.addWidget(input_title)

        self.url_input = UrlInputEdit()
        self.url_input.setPlaceholderText(
            "每行一个链接（支持 B 站 / YouTube / 抖音 等 1000+ 站点）\n"
            "回车生成链接卡片（解析标题与该视频的清晰度），Shift+回车换行"
        )
        # 固定输入框高度，避免其 Expanding 策略在滚动容器中撑开卡片
        self.url_input.setFixedHeight(72)
        self.url_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.url_input.committed.connect(self._commit_lines)
        input_vbox.addWidget(self.url_input)

        option_row = QHBoxLayout()
        option_row.setSpacing(10)

        self.quality_select = QComboBox()
        self.quality_select.addItems(QUALITIES)
        quality = config_manager.get_default_quality()
        if quality in QUALITIES:
            self.quality_select.setCurrentText(quality)
        self.quality_select.setMinimumWidth(100)
        self.quality_select.setToolTip(
            "默认档位：链接解析出该视频实际提供的档位后，自动落到不高于它的最高一档"
        )
        option_row.addWidget(self.quality_select)

        self.format_select = QComboBox()
        self.format_select.addItems(FORMATS)
        fmt = config_manager.get_default_format()
        if fmt in FORMATS:
            self.format_select.setCurrentText(fmt)
        self.format_select.setMinimumWidth(90)
        self.format_select.currentIndexChanged.connect(self._sync_input_quality)
        option_row.addWidget(self.format_select)
        self._apply_format_gating()

        self.dir_input = QLineEdit()
        self.dir_input.setText(config_manager.get_download_dir())
        self.dir_input.setPlaceholderText("保存目录")
        browse_button = QPushButton("浏览")
        browse_button.clicked.connect(self._browse_dir)
        option_row.addWidget(self.dir_input, 1)
        option_row.addWidget(browse_button)
        input_vbox.addLayout(option_row)

        # ---- 待下载标签区（回车生成的标签卡，参数各自独立快照） ----
        self.tag_hint = QLabel(
            "回车生成链接卡片：自动解析标题，清晰度只列该视频真正提供的档位；"
            "右键可查看原链接，双击恢复文本"
        )
        self.tag_hint.setProperty("muted", True)
        self.tag_hint.setWordWrap(True)
        input_vbox.addWidget(self.tag_hint)

        self.tag_host = QWidget()
        # 透明底在 theme.py 的全局 QSS 里按 objectName 上色；
        # 不要用 setStyleSheet("background: transparent;")——裸声明会级联到
        # 标签卡弹出的右键菜单，把菜单背景覆盖成透明（最终呈现为纯黑底）。
        self.tag_host.setObjectName("tagHost")
        self.tag_layout = QVBoxLayout(self.tag_host)
        self.tag_layout.setContentsMargins(0, 0, 0, 0)
        self.tag_layout.setSpacing(6)
        self.tag_layout.addStretch()
        input_vbox.addWidget(self.tag_host)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.concurrent_label = QLabel(
            f"当前最大并发: {config_manager.get_max_task()}，可在设置中调整"
        )
        self.concurrent_label.setProperty("muted", True)
        add_button = QPushButton("开始下载")
        add_button.setProperty("primary", True)
        add_button.setProperty("cta", True)   # 主行动按钮：更大、更醒目
        add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_button.clicked.connect(self._add_tasks)
        clear_button = QPushButton("清空已完成")
        clear_button.clicked.connect(self._clear_completed)
        action_row.addWidget(self.concurrent_label, 1)
        action_row.addWidget(clear_button)
        action_row.addWidget(add_button)
        # 操作行（开始/清空已完成）不放进输入卡片：固定在滚动区底部，始终可见
        action_bar = QFrame()
        action_bar.setProperty("cssClass", "card")
        bar_layout = QHBoxLayout(action_bar)
        bar_layout.setContentsMargins(16, 10, 16, 10)
        bar_layout.setSpacing(10)
        bar_layout.addLayout(action_row)

        # ---- 下方滚动区：输入卡片 + 任务列表 + 预览面板（整页一体滚动） ----
        self.page_scroll = QScrollArea()
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        page_host = QWidget()
        page_host.setObjectName("pageHost")
        layout = QVBoxLayout(page_host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 输入卡片随页面一起滚动（不再悬浮固定在顶部）
        layout.addWidget(input_card)

        # ---- 任务列表（随滚动区滚动） ----
        self.empty_state = QFrame()
        self.empty_state.setObjectName("emptyState")
        self.empty_state.setMinimumHeight(150)
        empty_lay = QVBoxLayout(self.empty_state)
        empty_lay.setContentsMargins(24, 30, 24, 30)
        empty_lay.setSpacing(6)
        empty_title = QLabel("暂无下载任务")
        empty_title.setProperty("cssClass", "emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint = QLabel(
            "粘贴视频链接后回车生成链接卡片，卡片会自动解析标题与该视频提供的清晰度；"
            "点击“开始下载”加入队列，悬停卡片可预览低清画面"
        )
        empty_hint.setProperty("cssClass", "emptyHint")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint.setWordWrap(True)
        empty_lay.addWidget(empty_title)
        empty_lay.addWidget(empty_hint)
        layout.addWidget(self.empty_state)

        self.list_host = QWidget()
        self.list_host.setObjectName("taskListHost")
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch()
        layout.addWidget(self.list_host)

        # ---- 视频预览面板（点击任务卡片上的"预览"在卡片下方展开） ----
        self.preview_panel = PreviewPanel()
        self.preview_panel.close_requested.connect(self._close_preview)
        self.preview_panel.hide()
        self._expanded_task: str | None = None

        self.page_scroll.setWidget(page_host)
        outer.addWidget(self._build_ffmpeg_notice())
        outer.addWidget(self.page_scroll, 1)
        outer.addWidget(action_bar)  # 操作条固定在滚动区底部，滚动时始终可见

    def _close_preview(self) -> None:
        """收起预览面板（无论展开在任务区还是标签区）"""
        if not self.preview_panel.isVisible():
            return
        self.preview_panel._player.stop()
        self.list_layout.removeWidget(self.preview_panel)
        page_layout = self.page_scroll.widget().layout()
        page_layout.removeWidget(self.preview_panel)
        self.preview_panel.hide()
        self._expanded_task = None
        self._tag_preview_url = None

    # ---------------------------------------------------------------- 标签

    def _commit_lines(self, text: str) -> None:
        """回车：把输入框里的有效链接按当前参数快照固定为链接卡片

        整个槽包一层异常兜底：应用用 pythonw 启动时没有控制台，Qt 槽里未捕获的
        异常只会写 stderr（即 /dev/null），表现就是"按回车什么都不发生"且日志里
        一行都没有。这里把它变成看得见的提示 + 一条日志。
        """
        try:
            self._commit_lines_inner(text)
        except Exception as e:
            logger.exception("生成链接卡片失败")
            self.tag_hint.setText(f"生成卡片时出错：{e}")

    def _commit_lines_inner(self, text: str) -> None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return
        urls, rejected = [], []
        for line in lines:
            url = normalize_url(line)
            (urls if url else rejected).append(url or line)
        if not urls:
            sample = rejected[0][:60] if rejected else ""
            # 完整原文用 repr 记一条：截断会正好切掉链接，且 repr 能露出零宽字符
            logger.warning(
                f"回车内容未包含可识别的链接: {repr(rejected[0] if rejected else '')[:400]}"
            )
            self.tag_hint.setText(
                f"没有识别到链接：{sample!r}\n"
                "请粘贴以 http(s):// 开头的视频地址（一行一个），"
                "或带 BV/av 号的 B 站分享文本"
            )
            return
        quality = self.quality_select.currentText()
        file_format = self.format_select.currentText()
        for u in urls:
            self._add_tag(u, quality, file_format)
        self.url_input.clear()
        self._update_tag_hint()
        if rejected:
            self.tag_hint.setText(
                f"已添加 {len(urls)} 个链接，忽略 {len(rejected)} 行无法识别的内容："
                f"{rejected[0][:40]!r}"
            )

    def _add_tag(self, url: str, quality: str, file_format: str) -> None:
        card = TagCard(url, quality, file_format)
        card.restore_requested.connect(self._restore_tag)
        card.delete_requested.connect(self._delete_tag)
        card.preview_requested.connect(self._preview_tag)
        card.hover_requested.connect(self._hover_tag)
        card.hover_left.connect(self._hover_tag_leave)
        card.reparse_requested.connect(self._reparse_tag)
        self._tag_cards.append(card)
        self.tag_layout.insertWidget(self.tag_layout.count() - 1, card)
        self._update_tag_hint()

        cached = _cached_resolution(url)
        if cached is not None:
            card.apply_resolution(cached, config_manager.get_default_quality())
        else:
            _start_resolution(url)

    def _reparse_tag(self, url: str) -> None:
        """右键「重新解析档位」：丢掉缓存重走一次（换 Cookie / 站点风控后常用）"""
        with _CACHE_LOCK:
            _CACHE.pop(url, None)
        for card in list(self._tag_cards):
            if card.url == url:
                card.state = "parsing"
                card.error = ""
                card.detail_label.setText(PARSING_HINT)
        _start_resolution(url)

    def _find_tag(self, url: str) -> TagCard | None:
        for card in self._tag_cards:
            if card.url == url:
                return card
        return None

    def _remove_tag_card(self, card: TagCard) -> None:
        if card not in self._tag_cards:
            return
        # 悬停小窗若锚定/预览此卡：随卡一同退场，否则小窗变孤儿弹窗滞留屏幕
        hover = self._hover
        if hover is not None and hover.isVisible() and hover.serving(card.url):
            hover.hide_preview()
        self._tag_cards.remove(card)
        self.tag_layout.removeWidget(card)
        card.deleteLater()
        self._update_tag_hint()

    def dismiss_hover(self) -> None:
        """收起悬停低清小窗（页面切走/窗口最小化时调用，防孤儿弹窗滞留屏幕）"""
        hover = self._hover
        if hover is None:
            return
        try:
            if hover.isVisible():
                hover.hide_preview()
        except RuntimeError:
            # 解释器退出等场景下 C++ 对象可能已先销毁：清引用即可
            self._hover = None

    def hideEvent(self, event) -> None:
        """页面被切走（侧边栏导航）时退掉悬停小窗，避免浮在其他页上方"""
        self.dismiss_hover()
        super().hideEvent(event)

    def _restore_tag(self, url: str) -> None:
        """双击标签：恢复为输入框中的文本链接"""
        card = self._find_tag(url)
        if card is None:
            return
        self._remove_tag_card(card)
        text = self.url_input.toPlainText()
        if text and not text.endswith("\n"):
            text += "\n"
        self.url_input.setPlainText(text + url)
        self.url_input.moveCursor(QTextCursor.MoveOperation.End)

    def _delete_tag(self, url: str) -> None:
        card = self._find_tag(url)
        if card is not None:
            self._remove_tag_card(card)

    def _preview_tag(self, url: str) -> None:
        """右键预览：在输入卡片下方展开在线预览窗口（再次调用收起）"""
        if self._tag_preview_url == url and self.preview_panel.isVisible():
            self._close_preview()
            return
        self._close_preview()
        page_layout = self.page_scroll.widget().layout()
        page_layout.insertWidget(
            page_layout.indexOf(self.input_card) + 1, self.preview_panel
        )
        self.preview_panel.show()
        self._tag_preview_url = url
        self.preview_panel.load_online_url(url)

    def _update_tag_hint(self) -> None:
        if self._tag_cards:
            self.tag_hint.setText(
                f"已固定 {len(self._tag_cards)} 个链接 · 悬停预览低清画面 · "
                "右键选清晰度/查看链接 · 双击恢复文本 · 点击“开始下载”加入队列"
            )
        else:
            self.tag_hint.setText(
                "回车生成链接卡片：自动解析标题，清晰度只列该视频真正提供的档位；"
                "右键可查看原链接，双击恢复文本"
            )

    # ---------------------------------------------------------------- 悬停小窗

    def _get_hover(self):
        if self._hover is None:
            from pages.hover_preview import HoverPreview
            self._hover = HoverPreview()
        return self._hover

    def _hover_tag(self, url: str) -> None:
        """悬停 0.5s：在标签卡下方弹出低清小窗预览（左边缘对齐）"""
        hover = self._get_hover()
        hover.show_preview(url)
        card = self._find_tag(url)
        if card is not None:
            hover.place_near(card)
        hover.show()

    def _hover_tag_leave(self) -> None:
        """鼠标离开标签卡：短暂缓冲后关闭小窗（期间若移入小窗则保留）"""
        QTimer.singleShot(350, self._maybe_hide_hover)

    def _maybe_hide_hover(self) -> None:
        hover = self._get_hover()
        if hover.isVisible() and not hover.underMouse():
            hover.hide_preview()

    # ---------------------------------------------------------------- 动作

    def _browse_dir(self) -> None:
        start = self.dir_input.text() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "选择保存目录", start)
        if selected:
            self.dir_input.setText(selected)

    def _sync_input_quality(self, *_args) -> None:
        """输入区：格式切换为纯音频时，质量下拉切换为声道选择（默认双声道）"""
        fmt = self.format_select.currentText()
        self.quality_select.blockSignals(True)
        if fmt in AUDIO_FORMATS:
            if self.quality_select.itemText(0) != CHANNELS[0]:
                self.quality_select.clear()
                self.quality_select.addItems(CHANNELS)
                self.quality_select.setCurrentText("双声道")
        else:
            if self.quality_select.itemText(0) != QUALITIES[0]:
                self.quality_select.clear()
                self.quality_select.addItems(QUALITIES)
                q = config_manager.get_default_quality()
                if q in QUALITIES:
                    self.quality_select.setCurrentText(q)
        self.quality_select.blockSignals(False)
        self._apply_quality_gating()

    # ---------------------------------------------------------------- ffmpeg 能力门控

    def _apply_format_gating(self) -> None:
        """按当前 ffmpeg 能力禁用不可用格式（能力不足时置灰）"""
        model = self.format_select.model()
        for i in range(self.format_select.count()):
            fmt = self.format_select.itemText(i)
            supported = ffmpeg_manager.format_supported(fmt)
            item = model.item(i)
            if item is not None:
                item.setEnabled(supported)
            if supported:
                self.format_select.setItemData(i, "", Qt.ItemDataRole.ToolTipRole)
            else:
                self.format_select.setItemData(
                    i, f"当前 FFmpeg 无法输出 {fmt}（完整版就绪后可用）",
                    Qt.ItemDataRole.ToolTipRole,
                )
        current = self.format_select.currentText()
        if not ffmpeg_manager.format_supported(current):
            # 当前所选格式不可用时回退
            fallback = config_manager.get_default_format()
            if not ffmpeg_manager.format_supported(fallback):
                fallback = "mp4"
            self.format_select.setCurrentText(fallback)
            self._forced_fallback = True
        elif self._forced_fallback:
            # 完整版就绪后恢复被强制回退的配置默认格式
            default_fmt = config_manager.get_default_format()
            if (default_fmt in FORMATS and default_fmt != current
                    and ffmpeg_manager.format_supported(default_fmt)):
                self.format_select.setCurrentText(default_fmt)
            self._forced_fallback = False

    def _apply_quality_gating(self) -> None:
        """纯音频格式下按 ffmpeg 能力禁用单声道（缺重采样滤波器时降级双声道）"""
        if self.format_select.currentText() not in AUDIO_FORMATS:
            return
        model = self.quality_select.model()
        for i in range(self.quality_select.count()):
            if self.quality_select.itemText(i) != "单声道":
                continue
            supported = ffmpeg_manager.mono_supported()
            item = model.item(i)
            if item is not None:
                item.setEnabled(supported)
            self.quality_select.setItemData(
                i,
                "" if supported else "当前 FFmpeg 不支持单声道重采样（将输出双声道）",
                Qt.ItemDataRole.ToolTipRole,
            )
        if (self.quality_select.currentText() == "单声道"
                and not ffmpeg_manager.mono_supported()):
            self.quality_select.setCurrentText("双声道")

    def _on_ffmpeg_capabilities_changed(self) -> None:
        """完整版 FFmpeg 就绪/替换：重新门控格式与声道，并刷新提示条"""
        self._apply_format_gating()
        self._apply_quality_gating()
        self._refresh_ffmpeg_notice()

    def _refresh_ffmpeg_notice(self) -> None:
        """同步 FFmpeg 完整版下载提示条（进度/失败/就绪）"""
        if not hasattr(self, "ffmpeg_notice"):
            return
        state = ffmpeg_manager.get_status()
        status = state["status"]
        if status == "downloading":
            percent = int(state.get("progress", 0) * 100)
            self.ffmpeg_notice_text.setText(
                f"正在下载完整版 FFmpeg（{percent}%）——flv / wav 与单声道将在就绪后解锁"
            )
            self.ffmpeg_notice_bar.setValue(percent)
            self.ffmpeg_notice_retry.hide()
            self.ffmpeg_notice.show()
        elif status == "failed":
            self.ffmpeg_notice_text.setText(
                f"完整版 FFmpeg 下载失败：{state.get('error') or '网络异常'}"
            )
            self.ffmpeg_notice_bar.setValue(0)
            self.ffmpeg_notice_retry.show()
            self.ffmpeg_notice.show()
        elif status == "lite":
            feats = ffmpeg_manager.missing_features()
            detail = " / ".join(feats) if feats else "部分能力"
            self.ffmpeg_notice_text.setText(
                f"当前 FFmpeg 能力不足：{detail} 不可用，可在设置页升级完整版"
            )
            self.ffmpeg_notice_bar.setValue(0)
            self.ffmpeg_notice_retry.show()
            self.ffmpeg_notice.show()
        else:
            # full / ready / missing：ready 即能力齐备无需提示；
            # missing 时首页状态卡负责提示，此处不占位
            self.ffmpeg_notice.hide()

    def _build_ffmpeg_notice(self) -> QFrame:
        """FFmpeg 完整版下载提示条（精简版限时告知用户为何部分选项被禁用）"""
        notice = QFrame()
        notice.setObjectName("ffmpegNotice")
        lay = QHBoxLayout(notice)
        lay.setContentsMargins(12, 6, 10, 6)
        lay.setSpacing(10)
        self.ffmpeg_notice_text = QLabel("")
        self.ffmpeg_notice_text.setObjectName("ffmpegNoticeText")
        self.ffmpeg_notice_text.setWordWrap(True)
        self.ffmpeg_notice_bar = QProgressBar()
        self.ffmpeg_notice_bar.setFixedWidth(140)
        self.ffmpeg_notice_bar.setTextVisible(False)
        self.ffmpeg_notice_bar.setFixedHeight(6)
        self.ffmpeg_notice_retry = QPushButton("重试")
        self.ffmpeg_notice_retry.setProperty("small", True)
        self.ffmpeg_notice_retry.clicked.connect(
            lambda: (ffmpeg_manager.start_auto_upgrade(),
                     self._refresh_ffmpeg_notice())
        )
        lay.addWidget(self.ffmpeg_notice_text, 1)
        lay.addWidget(self.ffmpeg_notice_bar)
        lay.addWidget(self.ffmpeg_notice_retry)
        notice.hide()
        self.ffmpeg_notice = notice
        return notice

    def _add_tasks(self) -> None:
        text = self.url_input.toPlainText()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        urls = [u for u in (normalize_url(line) for line in lines) if u]
        if not urls and not self._tag_cards:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "提示",
                "请输入视频链接（支持 B 站、YouTube、抖音等 1000+ 站点）",
            )
            return

        config_manager.set_config("download_dir", self.dir_input.text())
        config_manager.save_config()
        quality = self.quality_select.currentText()
        file_format = self.format_select.currentText()
        # 标签卡按各自快照参数入队（先清空标签区）
        for card in list(self._tag_cards):
            download_manager.add_task(
                card.url, card.quality, card.file_format,
                level=card.level, levels=card.levels,
            )
            self._remove_tag_card(card)
        # 输入框中尚未回车成卡的剩余行，按当前参数入队
        for u in urls:
            download_manager.add_task(u, quality, file_format)
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

    def refresh_theme(self) -> None:
        """主题切换回调：重放任务卡内联颜色（徽章/详情文字）"""
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

    def _preview_task_click(self, task_id: str) -> None:
        """点击卡片/预览按钮：在卡片下方展开预览窗口（再次点击收起）"""
        card = self._cards.get(task_id)
        if card is None:
            return
        if self._expanded_task == task_id and self.preview_panel.isVisible():
            self.list_layout.removeWidget(self.preview_panel)
            self.preview_panel.hide()
            self._expanded_task = None
            return

        index = self.list_layout.indexOf(card)
        self.list_layout.removeWidget(self.preview_panel)
        self.list_layout.insertWidget(index + 1, self.preview_panel)
        self.preview_panel.show()
        self._expanded_task = task_id

        task = download_manager.get_task(task_id) or {}
        output_path = task.get("output_path", "")
        if output_path and Path(output_path).exists():
            self.preview_panel.play_local_file(output_path)
            return
        url = task.get("url", "")
        if url:
            self.preview_panel.load_online_url(url)
            return
        self.preview_panel._show_loading("该任务暂无可预览的内容")

    # ---------------------------------------------------------------- 刷新

    def _upsert_card(self, task: dict) -> None:
        task_id = task["id"]
        card = self._cards.get(task_id)
        if card is None:
            card = TaskCard(task_id)
            card.clicked.connect(lambda: self._preview_task_click(task_id))
            card.config_changed.connect(self._on_card_config)
            card.retry_button.clicked.connect(lambda: self._retry_task(task_id))
            card.delete_button.clicked.connect(lambda: self._delete_task(task_id))
            card.preview_button.clicked.connect(lambda: self._preview_task_click(task_id))
            card.open_button.clicked.connect(lambda: self._open_folder(task_id))
            self._cards[task_id] = card
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)
        card.setVisible(True)
        card.update_task(task)

    def _on_card_config(self, task_id: str, quality: str, file_format: str) -> None:
        """卡片上修改格式/质量：仅未开始下载（等待中/失败可重试）的任务生效"""
        task = download_manager.get_task(task_id)
        if not task:
            return
        if task_id in download_manager._active:
            logger.warning(f"任务下载中，暂不能修改配置: {task_id}")
            return
        if task.get("status") in ("completed", "cancelled"):
            logger.warning(f"任务已结束，配置修改不生效: {task_id}")
            return
        level = next(
            (lv for lv in (task.get("levels") or []) if lv.get("label") == quality), None
        )
        task["quality"] = quality
        task["quality_level"] = level
        task["format"] = file_format
        download_log_manager.save_log(
            f"[下载] 任务配置已更新: {task.get('url', '')} 清晰度 {quality} 格式 {file_format}"
        )

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
        self.empty_state.setVisible(not self._cards)
