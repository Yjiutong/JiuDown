"""
全局主题模块
定义桌面应用的配色常量与 QSS 样式表
"""

APP_TITLE = "SHOUDown Desktop"
APP_VERSION = "1.0.0"

# 颜色常量
C = {
    # 品牌色
    "brand": "#2563eb",
    "brand_dark": "#1d4ed8",
    "brand_darker": "#1e40af",
    "brand_light": "#eff6ff",
    # 基础
    "bg": "#f5f7fa",
    "surface": "#ffffff",
    "border": "#e2e8f0",
    "border_strong": "#cbd5e1",
    # 文本
    "text": "#0f172a",
    "text_secondary": "#475569",
    "text_muted": "#94a3b8",
    # 侧边栏
    "sidebar": "#0f172a",
    "sidebar_hover": "#1e293b",
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
    "blue": "#2563eb",
    "blue_dark": "#1d4ed8",
    "blue_bg": "#dbeafe",
    "gray": "#64748b",
    "gray_dark": "#475569",
    "gray_bg": "#f1f5f9",
    "cyan": "#0d9488",
    "cyan_dark": "#0f766e",
    "cyan_bg": "#ccfbf1",
    # 日志面板
    "log_bg": "#0b1220",
    "log_border": "#1e293b",
    "log_text": "#cbd5e1",
}

QSS = """
/* ========== 全局 ========== */
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 13px;
    color: #0f172a;
}
QMainWindow, QWidget#contentRoot {
    background: #f5f7fa;
}
QLabel { background: transparent; }
QToolTip {
    background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 4px; padding: 4px 8px;
}

/* ========== 侧边栏 ========== */
QFrame#sidebar {
    background: #0f172a;
    border: none;
}
QLabel#sidebarTitle { color: #ffffff; font-size: 16px; font-weight: 700; background: transparent; }
QLabel#sidebarSub { color: #64748b; font-size: 11px; background: transparent; }
QLabel#sidebarVersion { color: #475569; font-size: 11px; background: transparent; }
QFrame#sidebarDivider { background: #1e293b; border: none; max-height: 1px; }

/* ========== 导航按钮 ========== */
QPushButton[nav="true"] {
    color: #94a3b8;
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
}
QPushButton[nav="true"]:hover { background: #1e293b; color: #e2e8f0; }
QPushButton[nav="true"]:checked { background: #2563eb; color: #ffffff; font-weight: 600; }

/* ========== 页头 ========== */
QLabel#pageTitle { font-size: 22px; font-weight: 700; color: #0f172a; background: transparent; }
QLabel#pageSubtitle { font-size: 12px; color: #64748b; background: transparent; }
QLabel#statusPill {
    background: #f1f5f9;
    color: #475569;
    border-radius: 12px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 600;
}

/* ========== 卡片 ========== */
QFrame[cssClass="card"] {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
}
QFrame[cssClass="card"]:hover { border-color: #cbd5e1; }

QLabel[cssClass="cardTitle"] { color: #64748b; font-size: 12px; background: transparent; }
QLabel[cssClass="cardValue"] { color: #0f172a; font-size: 21px; font-weight: 700; background: transparent; }
QLabel[cssClass="cardValueSmall"] { color: #0f172a; font-size: 14px; font-weight: 600; background: transparent; }
QLabel[cssClass="cardSub"] { color: #94a3b8; font-size: 11px; background: transparent; }

/* ========== 徽章 ========== */
QLabel[cssClass="badge"] {
    border-radius: 10px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
}
QLabel[cssClass="badgeGreen"] { background: #dcfce7; color: #15803d; }
QLabel[cssClass="badgeRed"] { background: #fee2e2; color: #b91c1c; }
QLabel[cssClass="badgeOrange"] { background: #fef3c7; color: #b45309; }
QLabel[cssClass="badgeBlue"] { background: #dbeafe; color: #1d4ed8; }
QLabel[cssClass="badgeGray"] { background: #f1f5f9; color: #475569; }
QLabel[cssClass="badgeCyan"] { background: #ccfbf1; color: #0f766e; }

/* ========== 通用按钮 ========== */
QPushButton {
    background: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 8px 18px;
    font-size: 13px;
}
QPushButton:hover { background: #f8fafc; border-color: #94a3b8; }
QPushButton:pressed { background: #f1f5f9; }
QPushButton:disabled { color: #94a3b8; background: #f1f5f9; border-color: #e2e8f0; }

QPushButton[primary="true"] {
    background: #2563eb;
    color: #ffffff;
    border: none;
    font-weight: 600;
}
QPushButton[primary="true"]:hover { background: #1d4ed8; }
QPushButton[primary="true"]:pressed { background: #1e40af; }
QPushButton[primary="true"]:disabled { background: #93c5fd; color: #ffffff; }

QPushButton[danger="true"] { color: #dc2626; border-color: #fecaca; }
QPushButton[danger="true"]:hover { background: #fee2e2; border-color: #fca5a5; }

QPushButton[small="true"] { padding: 4px 12px; font-size: 12px; border-radius: 6px; }

/* ========== 输入控件 ========== */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 7px 10px;
    color: #0f172a;
    selection-background-color: #bfdbfe;
    selection-color: #0f172a;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #2563eb;
}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
    background: #f1f5f9; color: #94a3b8;
}
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 4px;
    outline: 0;
    color: #0f172a;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}
QComboBox QAbstractItemView::item {
    min-height: 26px;
    padding: 2px 10px;
    border: none;
    border-radius: 5px;
    color: #0f172a;
    background: transparent;
}
QComboBox QAbstractItemView::item:hover {
    background: #eff6ff;
    color: #1d4ed8;
}
QComboBox QAbstractItemView::item:selected {
    background: #2563eb;
    color: #ffffff;
}
QSpinBox::up-button, QSpinBox::down-button {
    border: none; background: transparent; width: 18px;
}
QSpinBox::up-arrow, QSpinBox::down-arrow { width: 0; height: 0; }

/* ========== 复选框 ========== */
QCheckBox {
    spacing: 8px;
    color: #334155;
}
QCheckBox::indicator {
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid #cbd5e1;
    background: #ffffff;
}
QCheckBox::indicator:hover { border-color: #2563eb; }
QCheckBox::indicator:checked {
    background: #2563eb;
    border-color: #2563eb;
}

/* ========== 进度条 ========== */
QProgressBar {
    background: #e2e8f0;
    border: none;
    border-radius: 6px;
    min-height: 10px;
    max-height: 10px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: #2563eb; border-radius: 6px; }
QProgressBar[color="green"]::chunk { background: #16a34a; }
QProgressBar[color="red"]::chunk { background: #dc2626; }
QProgressBar[color="orange"]::chunk { background: #f59e0b; }

/* ========== 日志面板 ========== */
QTextEdit[cssClass="logPanel"] {
    background: #0b1220;
    color: #cbd5e1;
    border: 1px solid #1e293b;
    border-radius: 10px;
    font-family: "Cascadia Code", "Consolas", "Microsoft YaHei UI", monospace;
    font-size: 12px;
    padding: 10px;
    selection-background-color: #334155;
    selection-color: #f1f5f9;
}
QTextEdit[cssClass="dlLogPanel"] {
    background: #ffffff;
    color: #334155;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    font-family: "Cascadia Code", "Consolas", "Microsoft YaHei UI", monospace;
    font-size: 12px;
    padding: 10px;
    selection-background-color: #bfdbfe;
}

/* ========== 设置分组 ========== */
QFrame[cssClass="sectionCard"] {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
}
QLabel[cssClass="sectionTitle"] { color: #0f172a; font-size: 15px; font-weight: 700; background: transparent; }
QLabel[cssClass="sectionHint"] { color: #94a3b8; font-size: 11px; background: transparent; }
QFrame[cssClass="divider"] { background: #e2e8f0; border: none; max-height: 1px; }
QLabel[cssClass="formLabel"] { color: #475569; font-size: 13px; background: transparent; }
QWidget#settingsHost { background: transparent; }

/* ========== 标签页 ========== */
QTabWidget::pane {
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    background: #f5f7fa;
    top: -1px;
}
/* 嵌套标签页兜底：避免深色系统主题下 QTabWidget 默认黑底 */
QTabWidget QTabWidget,
QTabWidget QTabWidget::pane { background: #f5f7fa; }
QTabBar::tab {
    background: transparent;
    color: #64748b;
    border: none;
    padding: 9px 20px;
    margin-right: 6px;
    border-radius: 8px;
    font-size: 13px;
}
QTabBar::tab:hover { color: #0f172a; background: #e2e8f0; }
QTabBar::tab:selected { background: #eff6ff; color: #1d4ed8; font-weight: 600; }

/* ========== 滚动条 ========== */
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 2px;
}
QScrollBar::handle:vertical {
    background: #cbd5e1; border-radius: 5px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #94a3b8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #cbd5e1; border-radius: 5px; min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #94a3b8; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ========== 任务卡 ========== */
QLabel[cssClass="taskTitle"] { color: #0f172a; font-size: 13px; font-weight: 600; background: transparent; }
QLabel[cssClass="taskMeta"] { color: #94a3b8; font-size: 11px; background: transparent; }
QLabel[cssClass="taskDetail"] { color: #475569; font-size: 12px; background: transparent; }

/* ========== 其他 ========== */
QLabel[muted="true"] { color: #94a3b8; font-size: 12px; background: transparent; }
QLabel[sectionHeader="true"] { color: #334155; font-size: 13px; font-weight: 600; background: transparent; }
"""
