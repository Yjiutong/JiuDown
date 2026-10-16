"""
主窗口
侧边导航 + 页面栈的桌面应用框架
一体化标题栏：隐藏原生标题栏，窗口标识与控制由应用自身 chrome 承担
（拖动 / 双击最大化 / 边缘缩放 / 自定义最大化 / Win32 阴影恢复）
图标系统：iPhone 设计美学（squircle 容器 + SF 风格图形），详见下方图标系统节
支持系统托盘：有关闭时未完成任务 → 隐藏到托盘后台继续下载，完成后自动退出
"""

import sys

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPointF, QPropertyAnimation, QParallelAnimationGroup,
    Property, Qt, QTimer, QRect, QRectF, QPoint, QSize,
)
from PySide6.QtGui import (
    QColor, QCloseEvent, QGuiApplication, QIcon, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QCursor, QTransform,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from core_status import get_core_status, update_core_status
from download_manager import download_manager
from pages.download_page import DownloadPage
from pages.settings_page import SettingsPage
from theme import APP_TITLE, APP_VERSION, C

NAV_ITEMS = [
    ("视频下载", "B站视频下载与任务管理", DownloadPage),
    ("设置", "状态总览、运行日志与应用配置", SettingsPage),
]

ACTIVE_STATUSES = ("queued", "preparing", "downloading", "merging")

SIDEBAR_WIDE = 208
SIDEBAR_NARROW = 64

# 一体化标题栏（隐藏原生标题栏后由应用自身承担）
TITLEBAR_H = 38          # 标题栏高度
CAPTION_BTN_W = 46       # 窗口控制按钮宽度（Windows 惯例 46px）
RESIZE_MARGIN = 5        # 边缘缩放热区宽度（左/右/下）
CORNER_SIZE = 14         # 底部左右角缩放热区尺寸

_RESIZE_CURSORS = {
    "left": Qt.CursorShape.SizeHorCursor,
    "right": Qt.CursorShape.SizeHorCursor,
    "bottom": Qt.CursorShape.SizeVerCursor,
    "bottomleft": Qt.CursorShape.SizeBDiagCursor,
    "bottomright": Qt.CursorShape.SizeFDiagCursor,
}
_CAPTION_TOOLTIPS = {
    "minimize": "最小化",
    "maximize": "最大化",
    "restore": "还原",
    "close": "关闭",
}


# =====================================================================
# 图标系统（iPhone 设计美学）
# 规范参考 SF Symbols / iOS 应用图标：
# - 容器：squircle 连续圆角（角部曲线贴边起点与直边切线一致，
#   无圆弧的曲率突变折痕；对角方向比圆弧更饱满）
#   + 同色系微渐变（顶亮底暗，iOS 图标的 subtle depth）
# - 图形：45° 折线、圆头/圆角笔触、统一笔触重量（≈1.9px @20px），
#   字形外框约 21px（占 48 画布的 44%），四周留白均匀
# - 选中态导航图标仅绘白色图形（直接位于主色 pill 上，避免同色相叠）
# =====================================================================

_ICON_CANVAS = 48  # 图标设计稿尺寸，渲染时按目标尺寸整体缩放


def _squircle_path(w: float, h: float, radius: float,
                   samples: int = 24) -> QPainterPath:
    """iOS 风格 squircle 路径：角部为连续圆角曲线 (R(1-t)^2, R*t^2)

    普通 drawRoundedRect 的圆弧在贴边起点处曲率从 0 突变为 1/R，
    直边与弧面交界有一道可见折痕；本曲线在起点处切线与直边一致
    （水平切向），过渡无折痕，且对角方向比圆弧更饱满——这是
    iPhone 应用图标标志性的连续圆角轮廓。
    radius 为贴边直段的长度（等效视觉圆角半径）。
    """
    corner = [
        (radius * (1 - t / samples) ** 2, radius * (t / samples) ** 2)
        for t in range(samples + 1)
    ]  # (R,0) → (0,R)
    path = QPainterPath()
    path.moveTo(radius, 0)
    path.lineTo(w - radius, 0)
    for x, y in corner[1:]:              # 右上角 → (w, R)
        path.lineTo(w - x, y)
    path.lineTo(w, h - radius)
    for x, y in reversed(corner[:-1]):   # 右下角 → (w-R, h)
        path.lineTo(w - x, h - y)
    path.lineTo(radius, h)
    for x, y in corner[1:]:              # 左下角 → (0, h-R)
        path.lineTo(x, h - y)
    path.lineTo(0, radius)
    for x, y in reversed(corner[:-1]):   # 左上角 → (R, 0)
        path.lineTo(x, y)
    path.closeSubpath()
    return path


def _paint_icon_tile(p: QPainter, size: float) -> None:
    """squircle 容器 + 品牌青微渐变（顶 #4DCBC2 → 底 #32ADA5，中点即 #39C5BB）"""
    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0.0, QColor("#4DCBC2"))
    grad.setColorAt(1.0, QColor("#32ADA5"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    inset = size * 0.021  # 1px @48：给抗锯齿留边，避免边缘锯齿
    p.save()
    p.translate(inset, inset)
    p.drawPath(_squircle_path(size - inset * 2, size - inset * 2,
                              (size - inset * 2) * 0.28))
    p.restore()


def _draw_glyph_download(p: QPainter, color: QColor) -> None:
    """SF 风格「下载」：45° 箭头 + 竖杆 + 托线（arrow.down.to.line）"""
    pen = QPen(color, 4.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline([QPointF(14, 14), QPointF(24, 24), QPointF(34, 14)])
    p.drawLine(QPointF(24, 24), QPointF(24, 30))
    p.drawLine(QPointF(13.5, 34.5), QPointF(34.5, 34.5))


def _draw_glyph_gear(p: QPainter, body: QColor, hole: QColor) -> None:
    """SF 风格「齿轮」：6 齿 + 轮身 + 中心孔（gearshape）"""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(body)
    p.drawEllipse(QRectF(13.5, 13.5, 21, 21))            # 轮身 r=10.5
    for i in range(6):
        p.save()
        p.translate(24, 24)
        p.rotate(i * 60)
        p.drawRoundedRect(QRectF(-2.3, -15.8, 4.6, 6.2), 2.3, 2.3)  # 齿（轮身外交错）
        p.restore()
    p.setBrush(hole)
    p.drawEllipse(QRectF(19.2, 19.2, 9.6, 9.6))          # 中心孔 r=4.8


def _draw_glyph_chevrons(p: QPainter, color: QColor) -> None:
    """SF 风格双雪佛龙（«/»，侧边栏折叠语义）"""
    pen = QPen(color, 4.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline([QPointF(20, 16), QPointF(12, 24), QPointF(20, 32)])
    p.drawPolyline([QPointF(28, 16), QPointF(36, 24), QPointF(28, 32)])


def _render_icon(size: int, draw) -> QPixmap:
    """把 48 设计稿渲染到任意尺寸（painter 整体缩放，笔触同比缩放）"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / _ICON_CANVAS, size / _ICON_CANVAS)
    draw(p)
    p.end()
    return pm


def _make_app_icon_pixmap(size: int = 64) -> QPixmap:
    """应用图标（标题栏 / 系统托盘）：squircle + SF 下载图形"""
    def draw(p: QPainter) -> None:
        _paint_icon_tile(p, _ICON_CANVAS)
        _draw_glyph_download(p, QColor("#ffffff"))
    return _render_icon(size, draw)


_NAV_ICON_CACHE: dict[tuple[str, bool], QIcon] = {}


def _nav_icon(kind: str, on_brand: bool = False) -> QIcon:
    """导航图标（带缓存）

    on_brand=False：squircle 渐变底 + 白色图形（未选中，位于深色侧边栏上）
    on_brand=True ：仅白色图形（选中态，直接位于主色 pill 上）
    """
    key = (kind, on_brand)
    icon = _NAV_ICON_CACHE.get(key)
    if icon is None:
        def draw(p: QPainter) -> None:
            if not on_brand:
                _paint_icon_tile(p, _ICON_CANVAS)
            if kind == "download":
                _draw_glyph_download(p, QColor("#ffffff"))
            else:
                # 齿轮孔露出底色：未选中=渐变中点青，选中=pill 主色青
                hole = QColor("#39C5BB") if on_brand else QColor("#3FBEB5")
                _draw_glyph_gear(p, QColor("#ffffff"), hole)
        icon = QIcon(_render_icon(_ICON_CANVAS, draw))
        _NAV_ICON_CACHE[key] = icon
    return icon


def _make_fold_base_pixmap() -> QPixmap:
    """折叠开关基础位图（« 展开态；收起态 » 由 180° 旋转动画得到）"""
    def draw(p: QPainter) -> None:
        _paint_icon_tile(p, _ICON_CANVAS)
        _draw_glyph_chevrons(p, QColor("#ffffff"))
    return _render_icon(_ICON_CANVAS, draw)


class _FoldButton(QPushButton):
    """侧边栏折叠开关：« / » 两态之间以 180° 旋转动画平滑过渡

    图标绕画布中心旋转（QTransform 中心平移），每帧重绘并 setIcon，
    按钮自身的 QSS 样式不受影响。
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._angle = 0.0
        self._base_pm = _make_fold_base_pixmap()
        self.setIconSize(QSize(20, 20))
        self._apply_angle(0.0)

    def _apply_angle(self, angle: float) -> None:
        transform = QTransform()
        transform.translate(24, 24)
        transform.rotate(angle)
        transform.translate(-24, -24)
        self.setIcon(QIcon(self._base_pm.transformed(
            transform, Qt.TransformationMode.SmoothTransformation
        )))

    def _get_angle(self) -> float:
        return self._angle

    def _set_angle(self, value: float) -> None:
        self._angle = value
        self._apply_angle(value)

    angle = Property(float, _get_angle, _set_angle)


class _CaptionButton(QPushButton):
    """一体化标题栏的窗口控制按钮（最小化 / 最大化 / 还原 / 关闭）

    自绘图标与状态底色，颜色取自主题令牌（C 实时视图），主题切换自动跟随。
    尺寸遵循 Windows  caption 按钮惯例（46 x 标题栏高）。
    """

    def __init__(self, role: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._role = role
        self.setProperty("captionBtn", True)
        self.setFixedSize(CAPTION_BTN_W, TITLEBAR_H)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_CAPTION_TOOLTIPS[role])

    def set_role(self, role: str) -> None:
        """最大化 / 还原 图标互换"""
        self._role = role
        self.setToolTip(_CAPTION_TOOLTIPS[role])
        self.update()

    def refresh_theme(self) -> None:
        self.update()

    def _state_bg(self):
        """当前状态底色；None = 透明（透出右段背景）"""
        if self._role == "close":
            if self.isDown():
                return QColor(C["titlebar_close_pressed"])
            if self.underMouse():
                return QColor(C["titlebar_close_hover"])
            return None
        if self.isDown():
            return QColor(C["titlebar_ctrl_pressed"])
        if self.underMouse():
            return QColor(C["titlebar_ctrl_hover"])
        return None

    def _paint_icon(self, p: QPainter, color: QColor, bg) -> None:
        cx, cy = int(self.width() / 2), int(self.height() / 2)
        pen = QPen(color, 1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self._role == "minimize":
            p.drawLine(QPointF(cx - 5, cy), QPointF(cx + 5, cy))
        elif self._role == "maximize":
            p.drawRect(QRect(cx - 5, cy - 5, 10, 10))
        elif self._role == "restore":
            # 后窗（右上偏移）+ 前窗（当前底色填充，形成遮挡关系）
            p.drawRect(QRect(cx - 3, cy - 5, 10, 10))
            p.setBrush(QColor(bg) if bg is not None else QColor(C["bg"]))
            p.drawRect(QRect(cx - 5, cy - 3, 10, 10))
        else:  # close
            p.drawLine(QPointF(cx - 5, cy - 5), QPointF(cx + 5, cy + 5))
            p.drawLine(QPointF(cx + 5, cy - 5), QPointF(cx - 5, cy + 5))

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = self._state_bg()
        if bg is not None:
            p.fillRect(self.rect(), bg)
        elif self._role == "restore":
            # 还原图标的"后窗"需要底色遮挡，避免线条穿帮
            p.fillRect(self.rect(), QColor(C["bg"]))
        hover_close = self._role == "close" and self.underMouse()
        icon_color = QColor("#ffffff") if hover_close else QColor(C["titlebar_icon"])
        self._paint_icon(p, icon_color, bg)
        p.end()


class _TitleBar(QWidget):
    """一体化标题栏：去掉原生标题栏后，由应用自身承担窗口标识与窗口控制

    - 左段：与侧边栏同色同宽（视觉连成一体），承载应用图标 + 名称；
      宽度跟随侧边栏（含折叠动画逐帧同步），支持拖动 / 双击最大化 / 右键系统菜单
    - 右段：与内容区同色，右端放置最小化 / 最大化 / 关闭按钮
    """

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self._window = window
        self.setObjectName("titleBar")
        self.setFixedHeight(TITLEBAR_H)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---- 左段：应用标识（宽度 = 侧边栏宽度） ----
        self._left = QWidget()
        self._left.setObjectName("titleBarLeft")
        self._left_lay = QHBoxLayout(self._left)
        # 左边距 24：图标中心落在 x=32，与侧边栏开关/导航图标线对齐；
        # 收起态（64px 段）下 24+16/2 也恰好居中于 32，两态图标零位移
        self._left_lay.setContentsMargins(24, 0, 10, 0)
        self._left_lay.setSpacing(8)
        self._icon_label = QLabel()
        self._icon_label.setPixmap(
            _make_app_icon_pixmap(32).scaled(
                16, 16,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._title_label = QLabel(APP_TITLE)
        self._title_label.setObjectName("titlebarTitle")
        self._left_lay.addWidget(self._icon_label)
        self._left_lay.addWidget(self._title_label)
        self._left_lay.addStretch()

        # ---- 右段：窗口控制 ----
        self._right = QWidget()
        self._right.setObjectName("titleBarRight")
        right_lay = QHBoxLayout(self._right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        right_lay.addStretch()
        self._min_btn = _CaptionButton("minimize")
        self._min_btn.clicked.connect(self._window.showMinimized)
        self._max_btn = _CaptionButton("maximize")
        self._max_btn.clicked.connect(self._window.toggle_maximize)
        self._close_btn = _CaptionButton("close")
        self._close_btn.clicked.connect(self._window.close)
        for btn in (self._min_btn, self._max_btn, self._close_btn):
            right_lay.addWidget(btn)

        lay.addWidget(self._left)
        lay.addWidget(self._right, 1)

        self._drag_offset = None  # 拖动中的全局偏移

    # ------------------------------------------------------------ 外观同步

    def set_left_width(self, width: int) -> None:
        """左段宽度跟随侧边栏（展开 208 / 收起 64 / 动画逐帧）"""
        self._left.setFixedWidth(width)

    def set_collapsed(self, collapsed: bool) -> None:
        """侧边栏收起时隐藏标题文字。

        图标位置两态一致（均距左 24px，收起态恰好居中于 64px 段），
        无需切换边距/弹簧，避免动画期间图标位置跳变。
        """
        self._title_label.setVisible(not collapsed)

    def refresh_theme(self) -> None:
        self.update()

    # ------------------------------------------------------------ 拖动 / 菜单

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._window._is_maximized:
            self._drag_offset = (
                event.globalPosition().toPoint() - self._window.geometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.toggle_maximize()
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        self._window.show_system_menu(event.globalPos())


class MainWindow(QMainWindow):
    """应用主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 800)
        self.setMinimumSize(1060, 680)
        # 启动即把尺寸收敛到当前屏幕工作区：高 DPI 小屏（如 150% 缩放的 1080p）
        # 下 1280x800 换算成物理像素后超出屏幕，窗口底部（含固定操作条）会被
        # 裁出屏幕且最小尺寸同样超屏时用户无法缩小——必须先于任何布局计算
        self._fit_to_screen()
        # 全局主题已由 theme_manager 应用（应用级 QSS + palette，覆盖弹出菜单等顶层控件）
        self._nav_buttons: list[QPushButton] = []

        # ---- 一体化标题栏：隐藏原生标题栏，窗口行为由应用自身实现 ----
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self._is_maximized = False      # 自定义最大化状态（几何 = 工作区，不压任务栏）
        self._normal_geometry = QRect()  # 最大化前的窗口几何
        self._press_region = None        # 正在进行的边缘缩放手区
        self._press_global = QPoint()
        self._press_geometry = QRect()
        self._hover_region = None        # 光标当前所在缩放手区（仅悬停）
        self._cursor_overridden = False
        self._shadow_done = False

        self._build_ui()

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status_pill)
        self._status_timer.start(2000)
        self._refresh_status_pill()

        # 全局鼠标事件过滤：无原生边框后的边缘缩放（按压缩制，避免子控件误响应）
        QApplication.instance().installEventFilter(self)
        # 光标轮询：边缘缩放热区的光标形状提示（悬停态无鼠标事件可依赖）
        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._poll_hover_cursor)
        self._cursor_timer.start(60)

        # ---- 系统托盘：有关闭时未完成任务 → 隐藏到托盘继续后台下载 ----
        self._tray = None
        self._tray_active = False
        self._init_tray()

        self._tray_timer = QTimer(self)
        self._tray_timer.timeout.connect(self._check_tray_tasks)
        self._tray_timer.start(1000)

    # ---------------------------------------------------------------- 托盘

    def _init_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(self)
        tray.setIcon(QIcon(_make_app_icon_pixmap(64)))
        tray.setToolTip(APP_TITLE)
        menu = QMenu(self)
        show_action = menu.addAction("显示主窗口")
        show_action.triggered.connect(self._restore_from_tray)
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self._quit_app)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: self._restore_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        tray.show()
        self._tray = tray

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self._is_maximized = False
        self._title_bar._max_btn.set_role("maximize")
        self.raise_()
        self.activateWindow()

    def _has_active_tasks(self) -> bool:
        for task in download_manager.list_tasks():
            if task.get("status") in ACTIVE_STATUSES:
                return True
        return False

    def _check_tray_tasks(self) -> None:
        """托盘后台模式下：全部任务结束后自动退出"""
        if not self._tray_active or self.isVisible():
            return
        if not self._has_active_tasks():
            self._tray_active = False
            self._quit_app()

    def _quit_app(self) -> None:
        """真正退出（托盘菜单 / 任务完成自动退出）"""
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        """关闭窗口：有未完成任务则退到托盘后台继续下载"""
        if self._has_active_tasks():
            event.ignore()
            self._tray_active = True
            self.hide()
            if self._tray is not None:
                self._tray.showMessage(
                    APP_TITLE,
                    "下载任务进行中，已隐藏到系统托盘继续后台下载，全部完成后自动退出。",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
            return
        event.accept()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("contentRoot")
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---- 一体化标题栏（隐藏原生标题栏后由应用自身承担） ----
        self._title_bar = _TitleBar(self)
        root_layout.addWidget(self._title_bar)

        body_row = QHBoxLayout()
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.setSpacing(0)

        # ---- 左侧可折叠导航栏 ----
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(SIDEBAR_WIDE)
        sidebar.setMaximumWidth(SIDEBAR_WIDE)
        self._sidebar = sidebar
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 22, 14, 16)
        side_layout.setSpacing(4)

        logo_row = QHBoxLayout()
        logo_row.setSpacing(10)
        # 折叠/展开开关（程序化绘制箭头图标 + 旋转动画，避免字体符号渲染为空）
        # 36px 宽与收起态导航按钮同宽，图标中心恒为 x=32（与导航图标线对齐）
        self._toggle_btn = _FoldButton()
        self._toggle_btn.setObjectName("sidebarToggle")
        self._toggle_btn.setFixedSize(36, 28)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setToolTip("折叠侧边栏")
        self._toggle_btn.clicked.connect(self._toggle_sidebar)
        logo_row.addWidget(self._toggle_btn)
        # 品牌区（收起时隐藏；收起后按钮撑满内容区实现水平居中）
        self._brand = QWidget()
        brand_lay = QVBoxLayout(self._brand)
        brand_lay.setContentsMargins(0, 0, 0, 0)
        brand_lay.setSpacing(0)
        title_label = QLabel(APP_TITLE)
        title_label.setObjectName("sidebarTitle")
        sub_label = QLabel("B站视频下载工具")
        sub_label.setObjectName("sidebarSub")
        brand_lay.addWidget(title_label)
        brand_lay.addWidget(sub_label)
        logo_row.addWidget(self._brand)
        logo_row.addStretch()
        side_layout.addLayout(logo_row)

        self._divider = QFrame()
        self._divider.setObjectName("sidebarDivider")
        side_layout.addWidget(self._divider)

        for index, (name, _desc, _page_cls) in enumerate(NAV_ITEMS):
            button = QPushButton(name)
            button.setProperty("nav", True)
            button.setProperty("navText", name)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(_nav_icon("download" if index == 0 else "settings"))
            button.setIconSize(QSize(20, 20))
            button.clicked.connect(
                lambda _checked=False, i=index: self._switch_page(i)
            )
            side_layout.addWidget(button)
            self._nav_buttons.append(button)

        side_layout.addStretch()
        self._version_label = QLabel(f"v{APP_VERSION}")
        self._version_label.setObjectName("sidebarVersion")
        side_layout.addWidget(self._version_label)
        body_row.addWidget(sidebar)

        # 侧边栏宽度动画（展开 208 ↔ 收起 64）
        # min/max 同步插值，迫使布局逐帧给出精确宽度：
        # 仅动画 maximumWidth 时，minimumWidth 一旦被置位，宽度会瞬间跳变
        self._sidebar_anim_min = QPropertyAnimation(sidebar, b"minimumWidth", self)
        self._sidebar_anim_max = QPropertyAnimation(sidebar, b"maximumWidth", self)
        self._sidebar_anim = QParallelAnimationGroup(self)
        self._sidebar_anim.addAnimation(self._sidebar_anim_min)
        self._sidebar_anim.addAnimation(self._sidebar_anim_max)
        for anim in (self._sidebar_anim_min, self._sidebar_anim_max):
            anim.setDuration(260)
            anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._sidebar_anim.finished.connect(self._on_sidebar_anim_finished)
        # 开关图标旋转动画（与宽度动画同时长同曲线，两动画感知为一个动作）
        self._fold_anim = QPropertyAnimation(self._toggle_btn, b"angle", self)
        self._fold_anim.setDuration(260)
        self._fold_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._collapsed = False
        self._apply_sidebar_state(False)

        # ---- 右侧内容区 ----
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 14, 28, 16)
        content_layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        header_text = QVBoxLayout()
        header_text.setSpacing(0)
        self._page_title_label = QLabel("")
        self._page_title_label.setObjectName("pageTitle")
        self._page_subtitle_label = QLabel("")
        self._page_subtitle_label.setObjectName("pageSubtitle")
        header_text.addWidget(self._page_title_label)
        header_text.addWidget(self._page_subtitle_label)
        self._status_pill = QLabel("核心: 检测中")
        self._status_pill.setObjectName("statusPill")
        header_row.addLayout(header_text)
        header_row.addStretch()
        header_row.addWidget(self._status_pill)
        content_layout.addLayout(header_row)

        self._stack = QStackedWidget()
        for _name, _desc, page_cls in NAV_ITEMS:
            self._stack.addWidget(page_cls())
        content_layout.addWidget(self._stack, 1)
        body_row.addWidget(content, 1)
        root_layout.addLayout(body_row, 1)

        self._switch_page(0)

        # 去除所有 QComboBox 下拉列表的原生 frame，避免 QSS 圆角下出现黑边
        for combo in self.findChildren(QComboBox):
            combo.view().setFrameShape(QFrame.Shape.NoFrame)

        # 标题栏左段初始与侧边栏同宽（后续由 sidebar Resize 事件逐帧同步）
        self._title_bar.set_left_width(SIDEBAR_WIDE)

    # ---------------------------------------------------------------- 行为

    def _toggle_sidebar(self) -> None:
        self._collapsed = not self._collapsed
        target = SIDEBAR_NARROW if self._collapsed else SIDEBAR_WIDE
        start = self._sidebar.width()

        if self._collapsed:
            # 折叠：文字立即消失，再平滑收缩宽度（避免窄栏挤压文字）
            self._apply_sidebar_state(True)

        # 宽度动画：min/max 从当前宽度同步插值到目标值（逐帧精确宽度）
        self._sidebar_anim.stop()
        for anim in (self._sidebar_anim_min, self._sidebar_anim_max):
            anim.setStartValue(start)
            anim.setEndValue(target)
        self._sidebar_anim.start()

        # 开关图标旋转 180°（与宽度动画同时长同曲线；连续切换时从当前角度接续）
        self._fold_anim.stop()
        self._fold_anim.setStartValue(self._toggle_btn.angle)
        self._fold_anim.setEndValue(self._toggle_btn.angle + 180)
        self._fold_anim.start()

    def _on_sidebar_anim_finished(self) -> None:
        # 动画结束时属性已插值到目标值，此处显式落定 min/max，锁定最终宽度
        if self._collapsed:
            self._sidebar.setMinimumWidth(SIDEBAR_NARROW)
            self._sidebar.setMaximumWidth(SIDEBAR_NARROW)
        else:
            self._sidebar.setMinimumWidth(SIDEBAR_WIDE)
            self._sidebar.setMaximumWidth(SIDEBAR_WIDE)
            self._apply_sidebar_state(False)

    def _apply_sidebar_state(self, collapsed: bool) -> None:
        """切换品牌区/版本号/导航文字的显示，导航按钮收起时仅剩图标"""
        if hasattr(self, "_title_bar"):
            self._title_bar.set_collapsed(collapsed)
        self._toggle_btn.setToolTip("展开侧边栏" if collapsed else "折叠侧边栏")
        self._brand.setVisible(not collapsed)
        self._divider.setVisible(not collapsed)
        self._version_label.setVisible(not collapsed)
        for button in self._nav_buttons:
            text = button.property("navText") or ""
            button.setText("" if collapsed else text)
            button.setToolTip(text if collapsed else "")
            button.setProperty("collapsed", collapsed)
            button.style().unpolish(button)
            button.style().polish(button)

    def _switch_page(self, index: int) -> None:
        for i, button in enumerate(self._nav_buttons):
            selected = i == index
            button.setChecked(selected)
            # 选中态图标换为「仅白色图形」变体：直接位于主色 pill 上，避免同色相叠
            button.setIcon(
                _nav_icon("download" if i == 0 else "settings", on_brand=selected)
            )
        self._stack.setCurrentIndex(index)
        name, desc, _cls = NAV_ITEMS[index]
        self._page_title_label.setText(name)
        self._page_subtitle_label.setText(desc)

    def _refresh_status_pill(self) -> None:
        update_core_status()
        running = get_core_status().get("is_running", False)
        if running:
            text, bg, fg = "● 核心运行中", C["green_bg"], C["green_dark"]
        else:
            text, bg, fg = "● 核心已停止", C["red_bg"], C["red_dark"]
        self._status_pill.setText(text)
        self._status_pill.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 12px;"
            f"padding: 5px 14px; font-size: 12px; font-weight: 600;"
        )

    # ---------------------------------------------------------------- 无边框窗口行为

    def toggle_maximize(self) -> None:
        if self._is_maximized:
            self.restore_window()
        else:
            self.maximize_window()

    def maximize_window(self) -> None:
        """自定义最大化：几何 = 屏幕工作区（不压任务栏）"""
        if self._is_maximized:
            return
        screen = self.screen()
        if screen is None:
            return
        self._normal_geometry = self.geometry()
        self._is_maximized = True
        self.setGeometry(screen.availableGeometry())
        self._title_bar._max_btn.set_role("restore")

    def restore_window(self) -> None:
        if not self._is_maximized:
            return
        self._is_maximized = False
        if self._normal_geometry.isValid() and self._normal_geometry.width() > 0:
            self.setGeometry(self._normal_geometry)
        self._title_bar._max_btn.set_role("maximize")

    def show_system_menu(self, global_pos) -> None:
        """标题栏右键系统菜单（无原生边框后的替代入口）"""
        menu = QMenu(self)
        if self._is_maximized:
            menu.addAction("还原", self.restore_window)
        else:
            menu.addAction("最大化", self.maximize_window)
        menu.addAction("最小化", self.showMinimized)
        menu.addSeparator()
        menu.addAction("关闭", self.close)
        menu.exec(global_pos)

    # ------------------------------------------------------------ 边缘缩放

    def _resize_region(self, pos: QPoint):
        """窗口坐标 → 缩放手区；标题栏条带归拖动，顶部不参与缩放"""
        if self._is_maximized or pos.y() < TITLEBAR_H:
            return None
        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()
        left = x <= RESIZE_MARGIN
        right = x >= w - RESIZE_MARGIN
        bottom = y >= h - RESIZE_MARGIN
        if bottom and left and x <= CORNER_SIZE and y >= h - CORNER_SIZE:
            return "bottomleft"
        if bottom and right and x >= w - CORNER_SIZE and y >= h - CORNER_SIZE:
            return "bottomright"
        if left:
            return "left"
        if right:
            return "right"
        if bottom:
            return "bottom"
        return None

    def eventFilter(self, obj, event):
        # 侧边栏宽度变化（含折叠动画逐帧）→ 标题栏左段同步
        if obj is self._sidebar and event.type() == QEvent.Type.Resize:
            self._title_bar.set_left_width(self._sidebar.width())
            return False
        etype = event.type()
        if etype not in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
        ):
            return False
        # 仅处理本窗口内的鼠标事件（排除弹窗、下拉列表、其他窗口）
        if not isinstance(obj, QWidget) or obj.window() is not self:
            return False
        if etype == QEvent.Type.MouseButtonPress:
            return self._handle_press(obj, event)
        if self._press_region is None:
            return False
        if etype == QEvent.Type.MouseMove:
            self._apply_resize(event.globalPosition().toPoint())
            return True
        self._end_resize()
        return True

    def _handle_press(self, obj, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton or self._is_maximized:
            return False
        if obj is not None and obj.property("captionBtn"):
            return False  # 窗口控制按钮不参与边缘缩放
        region = self._resize_region(
            self.mapFromGlobal(event.globalPosition().toPoint())
        )
        if region is None:
            return False
        self._press_region = region
        self._press_global = event.globalPosition().toPoint()
        self._press_geometry = self.geometry()
        self._clear_hover_cursor()
        QApplication.setOverrideCursor(_RESIZE_CURSORS[region])
        self._cursor_overridden = True
        return True  # 消费事件：避免边缘热区误触发子控件（选择/聚焦）

    def _apply_resize(self, global_pos: QPoint) -> None:
        delta = global_pos - self._press_global
        g = self._press_geometry
        region = self._press_region
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        left, top, right, bottom = g.left(), g.top(), g.right(), g.bottom()
        if "left" in region:
            left = min(left + delta.x(), right - min_w + 1)
        if "right" in region:
            right = max(right + delta.x(), left + min_w - 1)
        if "bottom" in region:
            bottom = max(bottom + delta.y(), top + min_h - 1)
        self.setGeometry(QRect(QPoint(left, top), QPoint(right, bottom)))

    def _end_resize(self) -> None:
        self._press_region = None
        self._clear_hover_cursor()

    # ------------------------------------------------------------ 悬停光标

    def _poll_hover_cursor(self) -> None:
        """轮询光标位置，维护边缘缩放热区的光标形状（无原生边框后的能力提示）"""
        if self._press_region is not None:
            return
        if not self.isVisible() or self.isMinimized() or not self.isActiveWindow():
            self._clear_hover_cursor()
            return
        local = self.mapFromGlobal(QCursor.pos())
        region = self._resize_region(local) if self.rect().contains(local) else None
        if region == self._hover_region:
            return
        self._clear_hover_cursor()
        if region is not None:
            QApplication.setOverrideCursor(_RESIZE_CURSORS[region])
            self._cursor_overridden = True
        self._hover_region = region

    def _clear_hover_cursor(self) -> None:
        if self._cursor_overridden:
            QApplication.restoreOverrideCursor()
            self._cursor_overridden = False
        self._hover_region = None

    # ------------------------------------------------------------ 窗口状态 / 阴影

    def _track_normal_geometry(self) -> None:
        """常态几何随移动/缩放实时记录，供最大化还原使用"""
        if self._is_maximized or self.isMaximized():
            return
        g = self.geometry()
        if g.width() > 0 and g.height() > 0:
            self._normal_geometry = g

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._track_normal_geometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._track_normal_geometry()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        # 外部触发最大化（任务栏/系统）：收窄到工作区，避免压住任务栏
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMaximized()
            and not self._is_maximized
        ):
            screen = self.screen()
            if screen is not None:
                self.setGeometry(screen.availableGeometry())
            self._is_maximized = True
            self._title_bar._max_btn.set_role("restore")
        # 最小化：退掉各页面可能挂着的置顶小窗（如悬停低清预览），避免残留桌面
        elif event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            for i in range(self._stack.count()):
                page = self._stack.widget(i)
                dismiss = getattr(page, "dismiss_hover", None)
                if callable(dismiss):
                    dismiss()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._shadow_done:
            self._shadow_done = True
            self._enable_native_shadow()

    def _fit_to_screen(self, screen=None) -> None:
        """把初始尺寸与最小尺寸收敛到当前屏幕工作区，并居中放置

        resize(1280, 800) 是逻辑像素：150% 缩放的 1080p 屏工作区仅约
        1240x588，原样换算后窗口 1920x1200 物理像素，底部（含滚动区外
        固定的操作条）被裁出屏幕；最小尺寸 680 逻辑亦超屏高，用户根本
        无法把窗口缩小到能看到操作条。此处按工作区钳制并留出任务栏。
        """
        screen = screen or self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        if geo.width() <= 0 or geo.height() <= 0:
            return
        # 最小尺寸同样收敛（但不低于布局可用的下限）
        self.setMinimumSize(
            min(self.minimumWidth(), geo.width()),
            min(self.minimumHeight(), geo.height()),
        )
        w = min(self.width(), geo.width())
        h = min(self.height(), geo.height())
        self.resize(w, h)
        # 在工作区内居中（任务栏已由 availableGeometry 排除）
        self.move(
            geo.left() + max(0, (geo.width() - w) // 2),
            geo.top() + max(0, (geo.height() - h) // 2),
        )

    def _enable_native_shadow(self) -> None:
        """Windows：无边框窗口恢复 DWM 投影（1px 玻璃边框，仅影响窗外阴影）"""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            class _MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]

            hwnd = wintypes.HWND(int(self.winId()))
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                hwnd, ctypes.byref(_MARGINS(1, 1, 1, 1))
            )
        except Exception:
            pass  # 老系统 / 关闭 DWM 合成时静默降级：仅失去阴影

    def refresh_theme(self) -> None:
        """主题切换回调：重放内联动态颜色（状态徽章 + 标题栏控制按钮）"""
        self._refresh_status_pill()
        self._title_bar.update()
