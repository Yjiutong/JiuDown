"""
全局主题模块
视觉风格参考自玖桐博客（Miku 青 #39C5BB 系）：
淡青背景、白色卡片、14px 大圆角、青色主色、胶囊标签、柔和层次
"""

APP_TITLE = "JiuDown"
APP_VERSION = "1.0.0"

# 颜色常量（青绿主色 #39C5BB 系）
C = {
    # 品牌色
    "brand": "#39C5BB",
    "brand_dark": "#0E948C",
    "brand_darker": "#0d7f78",
    "brand_light": "#e6f7f6",
    # 基础
    "bg": "#f0f7f7",
    "surface": "#ffffff",
    "border": "#c2e2e0",
    "border_strong": "#9fd4d0",
    # 文本
    "text": "#1a2423",
    "text_secondary": "#546b69",
    "text_muted": "#7f9b99",
    # 侧边栏（暗灰青，对齐博客暗色主题 surface）
    "sidebar": "#1f2937",
    "sidebar_hover": "#28373b",
    # 状态色
    "green": "#16a34a",
    "green_dark": "#15803d",
    "green_bg": "#dcfce7",
    "red": "#dc2626",
    "red_dark": "#b91c1c",
    "red_bg": "#fee2e2",
    "orange": "#f59e0b",
    "orange_dark": "#b45309",
    "orange_bg": "#fef3c7",
    "blue": "#0d9488",
    "blue_dark": "#0f766e",
    "blue_bg": "#ccfbf1",
    "gray": "#5f7c79",
    "gray_dark": "#546b69",
    "gray_bg": "#e9f2f1",
    "cyan": "#0d9488",
    "cyan_dark": "#0f766e",
    "cyan_bg": "#ccfbf1",
    # 日志面板
    "log_bg": "#1f2937",
    "log_border": "#334155",
    "log_text": "#c2d6d4",
}

QSS = """
/* ========== 全局 ========== */
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 13px;
    color: #1a2423;
}
QMainWindow, QWidget#contentRoot {
    background: #f0f7f7;
}
QLabel { background: transparent; }
QToolTip {
    background: #1f2937; color: #e9f2f1; border: 1px solid #3a4a4e; border-radius: 6px; padding: 4px 8px;
}

/* ========== 侧边栏 ========== */
QFrame#sidebar {
    background: #1f2937;
    border: none;
}
QLabel#sidebarTitle { color: #39C5BB; font-size: 16px; font-weight: 700; background: transparent; }
QLabel#sidebarSub { color: #9bb0b2; font-size: 11px; background: transparent; }
QLabel#sidebarVersion { color: #6b8082; font-size: 11px; background: transparent; }
QFrame#sidebarDivider { background: #3a4a4e; border: none; max-height: 1px; }

/* ========== 导航按钮 ========== */
QPushButton[nav="true"] {
    color: #9bb0b2;
    background: transparent;
    border: none;
    border-radius: 10px;
    padding: 10px 14px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
}
QPushButton[nav="true"]:hover { background: #28373b; color: #e9f2f1; }
QPushButton[nav="true"]:checked { background: #39C5BB; color: #ffffff; font-weight: 600; }
QPushButton[nav="true"][collapsed="true"] { padding: 8px 4px; text-align: center; }
QPushButton#sidebarToggle {
    background: transparent; color: #9bb0b2; border: none; border-radius: 6px;
    font-size: 14px; font-weight: 600;
}
QPushButton#sidebarToggle:hover { background: #28373b; color: #e9f2f1; }
QPushButton#sidebarToggle:pressed { background: #3a4a4e; }

/* ========== 页头 ========== */
QLabel#pageTitle { font-size: 22px; font-weight: 700; color: #1a2423; background: transparent; }
QLabel#pageSubtitle { font-size: 12px; color: #7f9b99; background: transparent; }
QLabel#statusPill {
    background: #e9f2f1;
    color: #546b69;
    border: 1px solid #c2e2e0;
    border-radius: 999px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 600;
}

/* ========== 卡片 ========== */
QFrame[cssClass="card"] {
    background: #ffffff;
    border: 1px solid #c2e2e0;
    border-radius: 14px;
}
QFrame[cssClass="card"]:hover { border-color: #9fd4d0; }

QLabel[cssClass="cardTitle"] { color: #7f9b99; font-size: 12px; background: transparent; }
QLabel[cssClass="cardValue"] { color: #1a2423; font-size: 21px; font-weight: 700; background: transparent; }
QLabel[cssClass="cardValueSmall"] { color: #1a2423; font-size: 14px; font-weight: 600; background: transparent; }
QLabel[cssClass="cardSub"] { color: #9bb0b2; font-size: 11px; background: transparent; }

/* ========== 徽章（胶囊） ========== */
QLabel[cssClass="badge"] {
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
}
QLabel[cssClass="badgeGreen"] { background: #dcfce7; color: #15803d; }
QLabel[cssClass="badgeRed"] { background: #fee2e2; color: #b91c1c; }
QLabel[cssClass="badgeOrange"] { background: #fef3c7; color: #b45309; }
QLabel[cssClass="badgeBlue"] { background: #ccfbf1; color: #0f766e; }
QLabel[cssClass="badgeGray"] { background: #e9f2f1; color: #546b69; }
QLabel[cssClass="badgeCyan"] { background: #ccfbf1; color: #0f766e; }

/* ========== 通用按钮（胶囊） ========== */
QPushButton {
    background: #ffffff;
    color: #1a2423;
    border: 1px solid #c2e2e0;
    border-radius: 999px;
    padding: 8px 18px;
    font-size: 13px;
}
QPushButton:hover { background: #f0f7f7; border-color: #9fd4d0; color: #0E948C; }
QPushButton:pressed { background: #e6f7f6; }
QPushButton:disabled { color: #9bb0b2; background: #e9f2f1; border-color: #c2e2e0; }

QPushButton[primary="true"] {
    background: #39C5BB;
    color: #ffffff;
    border: none;
    font-weight: 600;
}
QPushButton[primary="true"]:hover { background: #0E948C; }
QPushButton[primary="true"]:pressed { background: #0d7f78; }
QPushButton[primary="true"]:disabled { background: #a8e3df; color: #ffffff; }

QPushButton[danger="true"] { color: #dc2626; border-color: #fecaca; }
QPushButton[danger="true"]:hover { background: #fee2e2; border-color: #fca5a5; color: #b91c1c; }

QPushButton[small="true"] { padding: 4px 12px; font-size: 12px; border-radius: 999px; }

/* ========== 右键菜单 ========== */
QMenu {
    background: #ffffff;
    border: 1px solid #c2e2e0;
    border-radius: 8px;
    padding: 4px;
    color: #1a2423;
    font-size: 13px;
}
QMenu::item { padding: 6px 22px; border-radius: 6px; }
QMenu::item:selected { background: #e6f7f6; color: #0E948C; }
QMenu::item:checked { color: #0E948C; font-weight: 600; }
QMenu::separator { height: 1px; background: #e9f2f1; margin: 4px 8px; }
QMenu::indicator { width: 12px; height: 12px; margin-left: 4px; }

/* ========== 输入控件 ========== */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background: #ffffff;
    border: 1px solid #c2e2e0;
    border-radius: 10px;
    padding: 7px 10px;
    color: #1a2423;
    selection-background-color: #39C5BB;
    selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #39C5BB;
}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
    background: #e9f2f1; color: #9bb0b2;
}
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #c2e2e0;
    border-radius: 10px;
    padding: 4px;
    outline: 0;
    color: #1a2423;
    selection-background-color: #39C5BB;
    selection-color: #ffffff;
}
QComboBox QAbstractItemView::item {
    min-height: 26px;
    padding: 2px 10px;
    border: none;
    border-radius: 8px;
    color: #1a2423;
    background: transparent;
}
QComboBox QAbstractItemView::item:hover {
    background: #e6f7f6;
    color: #0E948C;
}
QComboBox QAbstractItemView::item:selected {
    background: #39C5BB;
    color: #ffffff;
}
QSpinBox::up-button, QSpinBox::down-button {
    border: none; background: transparent; width: 18px;
}
QSpinBox::up-arrow, QSpinBox::down-arrow { width: 0; height: 0; }

/* ========== 复选框 ========== */
QCheckBox {
    spacing: 8px;
    color: #33415a;
}
QCheckBox::indicator {
    width: 16px; height: 16px;
    border-radius: 5px;
    border: 1px solid #c2e2e0;
    background: #ffffff;
}
QCheckBox::indicator:hover { border-color: #39C5BB; }
QCheckBox::indicator:checked {
    background: #39C5BB;
    border-color: #39C5BB;
}

/* ========== 进度条 ========== */
QProgressBar {
    background: #e9f2f1;
    border: none;
    border-radius: 8px;
    min-height: 10px;
    max-height: 10px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: #39C5BB; border-radius: 8px; }
QProgressBar[color="green"]::chunk { background: #16a34a; }
QProgressBar[color="red"]::chunk { background: #dc2626; }
QProgressBar[color="orange"]::chunk { background: #f59e0b; }

/* ========== 日志面板 ========== */
QTextEdit[cssClass="logPanel"] {
    background: #1f2937;
    color: #c2d6d4;
    border: 1px solid #334155;
    border-radius: 12px;
    font-family: "Cascadia Code", "Consolas", "Microsoft YaHei UI", monospace;
    font-size: 12px;
    padding: 10px;
    selection-background-color: #3a4a4e;
    selection-color: #e9f2f1;
}
QTextEdit[cssClass="dlLogPanel"] {
    background: #ffffff;
    color: #33415a;
    border: 1px solid #c2e2e0;
    border-radius: 12px;
    font-family: "Cascadia Code", "Consolas", "Microsoft YaHei UI", monospace;
    font-size: 12px;
    padding: 10px;
    selection-background-color: #e6f7f6;
}

/* ========== 设置分组 ========== */
QFrame[cssClass="sectionCard"] {
    background: #ffffff;
    border: 1px solid #c2e2e0;
    border-radius: 14px;
}
QLabel[cssClass="sectionTitle"] { color: #1a2423; font-size: 15px; font-weight: 700; background: transparent; }
QLabel[cssClass="sectionHint"] { color: #9bb0b2; font-size: 11px; background: transparent; }
QFrame[cssClass="divider"] { background: #c2e2e0; border: none; max-height: 1px; }
QLabel[cssClass="formLabel"] { color: #546b69; font-size: 13px; background: transparent; }
QWidget#settingsHost { background: transparent; }

/* ========== 标签页 ========== */
QTabWidget::pane {
    border: 1px solid #c2e2e0;
    border-radius: 14px;
    background: #f0f7f7;
    top: -1px;
}
/* 嵌套标签页兜底：避免深色系统主题下 QTabWidget 默认黑底 */
QTabWidget QTabWidget,
QTabWidget QTabWidget::pane { background: #f0f7f7; }
QTabBar::tab {
    background: transparent;
    color: #7f9b99;
    border: none;
    padding: 9px 20px;
    margin-right: 6px;
    border-radius: 999px;
    font-size: 13px;
}
QTabBar::tab:hover { color: #1a2423; background: #e6f7f6; }
QTabBar::tab:selected { background: #e6f7f6; color: #0E948C; font-weight: 600; }

/* ========== 滚动条 ========== */
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 2px;
}
QScrollBar::handle:vertical {
    background: #c2e2e0; border-radius: 5px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #9fd4d0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #c2e2e0; border-radius: 5px; min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #9fd4d0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ========== 任务卡 ========== */
QLabel[cssClass="taskTitle"] { color: #1a2423; font-size: 13px; font-weight: 600; background: transparent; }
QLabel[cssClass="taskMeta"] { color: #9bb0b2; font-size: 11px; background: transparent; }
QLabel[cssClass="taskDetail"] { color: #546b69; font-size: 12px; background: transparent; }

/* ========== 其他 ========== */
QLabel[muted="true"] { color: #9bb0b2; font-size: 12px; background: transparent; }
QLabel[sectionHeader="true"] { color: #33415a; font-size: 13px; font-weight: 600; background: transparent; }
"""
