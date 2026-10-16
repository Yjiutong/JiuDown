"""
主窗口
侧边导航 + 页面栈的桌面应用框架
支持系统托盘：有关闭时未完成任务 → 隐藏到托盘后台继续下载，完成后自动退出
"""

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, Qt, QTimer, QRect, QPoint, QSize,
)
from PySide6.QtGui import QColor, QCloseEvent, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from core_status import get_core_status, update_core_status
from download_manager import download_manager
from pages.download_page import DownloadPage
from pages.settings_page import SettingsPage
from theme import APP_TITLE, APP_VERSION, C, QSS

NAV_ITEMS = [
    ("视频下载", "B站视频下载与任务管理", DownloadPage),
    ("设置", "状态总览、运行日志与应用配置", SettingsPage),
]

ACTIVE_STATUSES = ("queued", "preparing", "downloading", "merging")

SIDEBAR_WIDE = 208
SIDEBAR_NARROW = 64


def _make_tray_icon() -> QPixmap:
    """程序化绘制托盘图标：青色圆角底 + 白色下载箭头"""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#39C5BB"))
    painter.drawRoundedRect(QRect(3, 3, 58, 58), 16, 16)
    painter.setBrush(QColor("#ffffff"))
    # 箭头：杆 + 尖 + 底部横线
    painter.drawRect(QRect(30, 14, 4, 24))
    painter.drawPolygon([QPoint(22, 22), QPoint(42, 22), QPoint(32, 40)])
    painter.drawRoundedRect(QRect(21, 44, 22, 5), 2, 2)
    painter.end()
    return pm


def _make_nav_icon(kind: str) -> QIcon:
    """程序化绘制导航图标（Miku 青圆角底 + 白色图形），展开/收起均可用"""
    pm = QPixmap(48, 48)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#39C5BB"))
    p.drawRoundedRect(QRect(2, 2, 44, 44), 12, 12)
    p.setBrush(QColor("#ffffff"))
    if kind == "download":
        # 下载箭头：杆 + 箭头尖 + 底部横线
        p.drawRect(QRect(20, 9, 8, 18))
        p.drawPolygon([QPoint(12, 17), QPoint(36, 17), QPoint(24, 32)])
        p.drawRoundedRect(QRect(13, 34, 22, 4), 2, 2)
    else:
        # 设置齿轮：外环 + 齿 + 中心点
        for i in range(8):
            p.save()
            p.translate(24, 24)
            p.rotate(i * 45)
            p.drawRect(QRect(19, -2, 5, 4))
            p.restore()
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRect(14, 14, 20, 20))
        p.setBrush(QColor("#39C5BB"))
        p.drawEllipse(QRect(20, 20, 8, 8))
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    """应用主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 800)
        self.setMinimumSize(1060, 680)
        self.setStyleSheet(QSS)
        self._nav_buttons: list[QPushButton] = []

        self._build_ui()

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status_pill)
        self._status_timer.start(2000)
        self._refresh_status_pill()

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
        tray.setIcon(_make_tray_icon())
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
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

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
        # 折叠/展开开关
        self._toggle_btn = QPushButton("«")
        self._toggle_btn.setObjectName("sidebarToggle")
        self._toggle_btn.setFixedSize(28, 28)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setToolTip("折叠侧边栏")
        self._toggle_btn.clicked.connect(self._toggle_sidebar)
        logo_row.addWidget(self._toggle_btn)
        # 品牌区（收起时隐藏）
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
        side_layout.addSpacing(8)

        for index, (name, _desc, _page_cls) in enumerate(NAV_ITEMS):
            button = QPushButton(name)
            button.setProperty("nav", True)
            button.setProperty("navText", name)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(_make_nav_icon("download" if index == 0 else "settings"))
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
        root_layout.addWidget(sidebar)

        # 侧边栏宽度动画（展开 208 ↔ 收起 64）
        self._sidebar_anim = QPropertyAnimation(sidebar, b"maximumWidth", self)
        self._sidebar_anim.setDuration(260)
        self._sidebar_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._sidebar_anim.finished.connect(self._on_sidebar_anim_finished)
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
        root_layout.addWidget(content, 1)

        self._switch_page(0)

        # 去除所有 QComboBox 下拉列表的原生 frame，避免 QSS 圆角下出现黑边
        for combo in self.findChildren(QComboBox):
            combo.view().setFrameShape(QFrame.Shape.NoFrame)

    # ---------------------------------------------------------------- 行为

    def _toggle_sidebar(self) -> None:
        self._collapsed = not self._collapsed
        if self._collapsed:
            # 折叠：文字立即消失，再收缩宽度（避免窄栏挤压文字）
            self._apply_sidebar_state(True)
            self._sidebar.setMinimumWidth(SIDEBAR_NARROW)
            self._sidebar_anim.stop()
            self._sidebar_anim.setStartValue(self._sidebar.width())
            self._sidebar_anim.setEndValue(SIDEBAR_NARROW)
            self._sidebar_anim.start()
        else:
            # 展开：先扩展宽度，动画结束后再显示文字
            self._sidebar.setMinimumWidth(SIDEBAR_NARROW)
            self._sidebar_anim.stop()
            self._sidebar_anim.setStartValue(self._sidebar.width())
            self._sidebar_anim.setEndValue(SIDEBAR_WIDE)
            self._sidebar_anim.start()

    def _on_sidebar_anim_finished(self) -> None:
        if self._collapsed:
            self._sidebar.setMinimumWidth(SIDEBAR_NARROW)
        else:
            self._sidebar.setMinimumWidth(SIDEBAR_WIDE)
            self._apply_sidebar_state(False)

    def _apply_sidebar_state(self, collapsed: bool) -> None:
        """切换品牌区/版本号/导航文字的显示，导航按钮收起时仅剩图标"""
        self._toggle_btn.setText("»" if collapsed else "«")
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
            button.setChecked(i == index)
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
