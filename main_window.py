"""
主窗口
侧边导航 + 页面栈的桌面应用框架
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from core_status import get_core_status, update_core_status
from pages.download_page import DownloadPage
from pages.settings_page import SettingsPage
from theme import APP_TITLE, APP_VERSION, C, QSS

NAV_ITEMS = [
    ("视频下载", "B站视频下载与任务管理", DownloadPage),
    ("设置", "状态总览、运行日志与应用配置", SettingsPage),
]


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

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("contentRoot")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---- 左侧导航栏 ----
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(208)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 22, 14, 16)
        side_layout.setSpacing(4)

        logo_row = QHBoxLayout()
        logo_row.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_label = QLabel(APP_TITLE)
        title_label.setObjectName("sidebarTitle")
        sub_label = QLabel("B站视频下载工具")
        sub_label.setObjectName("sidebarSub")
        title_box.addWidget(title_label)
        title_box.addWidget(sub_label)
        logo_row.addLayout(title_box)
        logo_row.addStretch()
        side_layout.addLayout(logo_row)

        divider = QFrame()
        divider.setObjectName("sidebarDivider")
        side_layout.addWidget(divider)
        side_layout.addSpacing(8)

        for index, (name, _desc, _page_cls) in enumerate(NAV_ITEMS):
            button = QPushButton(name)
            button.setProperty("nav", True)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, i=index: self._switch_page(i)
            )
            side_layout.addWidget(button)
            self._nav_buttons.append(button)

        side_layout.addStretch()
        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setObjectName("sidebarVersion")
        side_layout.addWidget(version_label)
        root_layout.addWidget(sidebar)

        # ---- 右侧内容区 ----
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 24, 28, 22)
        content_layout.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        header_text = QVBoxLayout()
        header_text.setSpacing(2)
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
