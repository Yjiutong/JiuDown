"""
全局主题模块（双主题架构）
视觉风格：Apple Human Interface Guidelines —— 干净、克制、留白充足
- 唯一强调色：系统蓝（浅 #007AFF / 深 #0A84FF），用于主按钮、选中、进度、链接
- 浅色：窗体 #F5F5F7 + 白色卡片 + 近黑文字 + 灰阶次级文字
- 深色：窗体 #1C1C1E + #2C2C2E 卡片 + 近白文字
- 状态色采用 Apple 系统色（绿 #34C759 / 橙 #FF9F0A / 红 #FF3B30 / 青 #32ADE6）
- 圆角：卡片 12px、控件 9px、徽章胶囊；系统字体栈（SF Pro / Segoe UI / PingFang SC）
- 双主题可切换（浅色 / 深色 / 跟随系统）

设计原则：
- 所有颜色集中在 THEMES 令牌表；QSS 由 build_qss() 按主题生成
- 业务代码只认键名，不认主题；ThemeManager 单例管理切换与持久化
- 默认浅色模式，可在设置中手动切换
"""

import json
from string import Template

from PySide6.QtCore import QObject, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

APP_TITLE = "JiuDown"
APP_VERSION = "1.0.0"

# 窗口圆角（无边框窗口的苹果式圆角遮罩半径）
WINDOW_RADIUS = 11

# 系统字体栈：macOS 优先 SF Pro，Windows 落 Segoe UI（最接近苹果观感），中文 PingFang/雅黑
FONT_FAMILY = (
    '-apple-system, "SF Pro Text", "SF Pro Display", "Segoe UI", '
    '"PingFang SC", "Microsoft YaHei UI", system-ui, sans-serif'
)
MONO_FAMILY = (
    '"SF Mono", "Cascadia Code", Consolas, "Microsoft YaHei UI", monospace'
)

# =====================================================================
# 主题令牌表 —— Apple HIG（浅色窗体灰 + 白色卡 + 系统蓝强调）
# 浅色：窗体 F5F5F7 / 卡片 FFFFFF / 文字 1D1D1F / 强调 007AFF
# 深色：窗体 1C1C1E / 卡片 2C2C2E / 文字 F5F5F7 / 强调 0A84FF
# 所有文字对比度 >= WCAG AA；强调色取 Apple 系统蓝
# =====================================================================

LIGHT = {
    # 强调色（系统蓝）
    "brand": "#007AFF",
    "brand_dark": "#0066D6",
    "brand_darker": "#0058B8",
    "brand_light": "#E8F1FF",          # 选中/悬停浅蓝底
    "on_brand": "#FFFFFF",
    # 基础（窗体灰 + 白卡）
    "bg": "#F5F5F7",
    "surface": "#FFFFFF",
    "border": "#E5E5EA",
    "border_strong": "#C7C7CC",
    # 文本（近黑 + 灰阶层级）
    "text": "#1D1D1F",
    "text_secondary": "#6E6E73",
    "text_muted": "#86868B",
    "text_faint": "#AEAEB2",
    "text_strong": "#1D1D1F",
    # 侧边栏（与窗体同色，靠 1px 分隔线区分）
    "sidebar": "#F5F5F7",
    "sidebar_hover": "#E8E8ED",
    "sidebar_text": "#1D1D1F",
    "sidebar_sub": "#86868B",
    "sidebar_version": "#AEAEB2",
    "sidebar_divider": "#D2D2D7",
    "nav_checked_text": "#007AFF",
    # 状态色（Apple 系统色）
    "green": "#34C759",
    "green_dark": "#1D7A33",
    "green_bg": "#E3F9E5",
    "red": "#FF3B30",
    "red_dark": "#C1271C",
    "red_bg": "#FFE5E2",
    "orange": "#FF9F0A",
    "orange_dark": "#B05F00",
    "orange_bg": "#FFF3E0",
    "blue": "#007AFF",
    "blue_dark": "#0066D6",
    "blue_bg": "#E8F1FF",
    "gray": "#8E8E93",
    "gray_dark": "#636366",
    "gray_bg": "#ECECEC",
    "cyan": "#32ADE6",
    "cyan_dark": "#1C7FBF",
    "cyan_bg": "#E2F4FC",
    # 保留键（无直接用途，避免旧引用 KeyError）
    "gold": "#FF9F0A",
    "gold_dark": "#B05F00",
    "gold_light": "#FFF3E0",
    # 输入控件
    "input": "#FFFFFF",
    "input_disabled_bg": "#F2F2F7",
    "input_disabled_text": "#C7C7CC",
    # 按钮
    "btn_hover_bg": "#F2F2F7",
    "primary_disabled_bg": "#C7D7F0",
    "primary_disabled_text": "#FFFFFF",
    "danger_border": "#FFC7C2",
    "danger_hover_bg": "#FFE5E2",
    "danger_hover_border": "#FF9F95",
    # 浮层
    "tooltip_bg": "#FFFFFF",
    "tooltip_text": "#1D1D1F",
    "tooltip_border": "#D2D2D7",
    # 一体化标题栏
    "titlebar_text": "#6E6E73",
    "titlebar_icon": "#1D1D1F",
    "titlebar_ctrl_hover": "#E8E8ED",
    "titlebar_ctrl_pressed": "#DCDCE1",
    "titlebar_close_hover": "#FFCDC9",
    "titlebar_close_pressed": "#F0A8A2",
    # 滚动条 / 进度条
    "scroll_handle": "#C7C7CC",
    "scroll_handle_hover": "#AEAEB2",
    "progress_bg": "#E5E5EA",
    # 视频播放条（常驻深色媒体面）
    "media_groove": "#48484A",
    "media_text": "#F5F5F7",
    # 日志面板
    "log_bg": "#FFFFFF",
    "log_border": "#E5E5EA",
    "log_text": "#1D1D1F",
    "log_dl_text": "#6E6E73",
}

# 深色主题（Apple 深色）：近黑窗体 + 亮强调 + 浅文字
DARK = {
    # 强调色（macOS 深色系统蓝）
    "brand": "#0A84FF",
    "brand_dark": "#0A6FD6",
    "brand_darker": "#0A5FBE",
    "brand_light": "#1E3A5F",          # 深色下选中浅蓝底
    "on_brand": "#FFFFFF",
    # 基础（近黑 + 略亮卡片）
    "bg": "#1C1C1E",
    "surface": "#2C2C2E",
    "border": "#3A3A3C",
    "border_strong": "#545458",
    # 文本（近白 + 灰阶层级）
    "text": "#F5F5F7",
    "text_secondary": "#98989D",
    "text_muted": "#8E8E93",
    "text_faint": "#636366",
    "text_strong": "#F5F5F7",
    # 侧边栏（与窗体同色，靠分隔线区分）
    "sidebar": "#1C1C1E",
    "sidebar_hover": "#2C2C2E",
    "sidebar_text": "#F5F5F7",
    "sidebar_sub": "#8E8E93",
    "sidebar_version": "#636366",
    "sidebar_divider": "#3A3A3C",
    "nav_checked_text": "#0A84FF",
    # 状态色（Apple 深色系统色）
    "green": "#30D158",
    "green_dark": "#30D158",
    "green_bg": "#0B301E",
    "red": "#FF453A",
    "red_dark": "#FF453A",
    "red_bg": "#3A1410",
    "orange": "#FFD60A",
    "orange_dark": "#FFD60A",
    "orange_bg": "#3A2E0B",
    "blue": "#0A84FF",
    "blue_dark": "#0A6FD6",
    "blue_bg": "#0A294D",
    "gray": "#98989D",
    "gray_dark": "#C7C7CC",
    "gray_bg": "#2C2C2E",
    "cyan": "#64D2FF",
    "cyan_dark": "#64D2FF",
    "cyan_bg": "#0A2E3A",
    # 保留键
    "gold": "#FFD60A",
    "gold_dark": "#FFD60A",
    "gold_light": "#3A2E0B",
    # 输入控件
    "input": "#1C1C1E",
    "input_disabled_bg": "#2C2C2E",
    "input_disabled_text": "#636366",
    # 按钮
    "btn_hover_bg": "#3A3A3C",
    "primary_disabled_bg": "#2C2C2E",
    "primary_disabled_text": "#636366",
    "danger_border": "#5A2A26",
    "danger_hover_bg": "#3A1410",
    "danger_hover_border": "#7A3A34",
    # 浮层（深色主题下 tooltip 反色为浅底深字）
    "tooltip_bg": "#2C2C2E",
    "tooltip_text": "#F5F5F7",
    "tooltip_border": "#3A3A3C",
    # 一体化标题栏
    "titlebar_text": "#98989D",
    "titlebar_icon": "#F5F5F7",
    "titlebar_ctrl_hover": "#3A3A3C",
    "titlebar_ctrl_pressed": "#48484A",
    "titlebar_close_hover": "#5A1C18",
    "titlebar_close_pressed": "#7A2824",
    # 滚动条 / 进度条
    "scroll_handle": "#545458",
    "scroll_handle_hover": "#636366",
    "progress_bg": "#3A3A3C",
    # 视频播放条
    "media_groove": "#545458",
    "media_text": "#F5F5F7",
    # 日志面板
    "log_bg": "#1C1C1E",
    "log_border": "#3A3A3C",
    "log_text": "#F5F5F7",
    "log_dl_text": "#B0B0B5",
}

THEMES = {"light": LIGHT, "dark": DARK}

# =====================================================================
# QSS 模板（$token 占位，string.Template 注入）
# 苹果风：系统字体、留白、克制圆角、单一蓝强调、胶囊徽章、分段标签
# =====================================================================

_QSS_TEMPLATE = Template("""
/* ========== 全局 ========== */
* {
    font-family: $font_family;
    font-size: 13px;
    color: $text;
}
QMainWindow, QWidget#contentRoot {
    background: $bg;
}
QLabel { background: transparent; }
QToolTip {
    background: $tooltip_bg; color: $tooltip_text; border: 1px solid $tooltip_border; border-radius: 8px; padding: 6px 10px;
}

/* ========== 一体化标题栏 ========== */
QWidget#titleBar { background: transparent; }
QWidget#titleBarLeft { background: $sidebar; }
QWidget#titleBarRight { background: $bg; }
QLabel#titlebarTitle { color: $titlebar_text; font-size: 13px; font-weight: 600; background: transparent; }
QPushButton[captionBtn="true"] { background: transparent; border: none; border-radius: 0px; padding: 0; }

/* ========== 侧边栏 ========== */
QFrame#sidebar {
    background: $sidebar;
    border: none;
    border-right: 1px solid $border;
}
QLabel#sidebarTitle { color: $text; font-size: 18px; font-weight: 700; background: transparent; }
QLabel#sidebarSub { color: $sidebar_sub; font-size: 11px; background: transparent; }
QLabel#sidebarVersion { color: $sidebar_version; font-size: 11px; background: transparent; }
QFrame#sidebarDivider { background: $sidebar_divider; border: none; max-height: 1px; }

/* ========== 导航按钮 ========== */
QPushButton[nav="true"] {
    color: $sidebar_text;
    background: transparent;
    border: none;
    border-radius: 9px;
    padding: 9px 12px;
    text-align: left;
    spacing: 9px;
    font-size: 13px;
    font-weight: 500;
}
QPushButton[nav="true"]:hover { background: $sidebar_hover; color: $text; }
QPushButton[nav="true"]:checked { background: $brand_light; color: $brand; font-weight: 600; }
QPushButton[nav="true"][collapsed="true"] { padding: 9px; text-align: center; }
QPushButton#sidebarToggle {
    background: transparent; color: $sidebar_text; border: none; border-radius: 8px;
    font-size: 14px; font-weight: 600;
}
QPushButton#sidebarToggle:hover { background: $sidebar_hover; }
QPushButton#sidebarToggle:pressed { background: $border_strong; }

/* ========== 页头 ========== */
QLabel#pageTitle { font-size: 24px; font-weight: 700; color: $text; background: transparent; }
QLabel#pageSubtitle { font-size: 13px; color: $text_muted; background: transparent; }
QLabel#statusPill {
    border-radius: 999px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 600;
    background: $gray_bg;
    color: $text_secondary;
}
QLabel#statusPill[cssClass="badgeGreen"] { background: $green_bg; color: $green_dark; }
QLabel#statusPill[cssClass="badgeRed"] { background: $red_bg; color: $red_dark; }
QLabel#statusPill[cssClass="badgeBlue"] { background: $blue_bg; color: $blue_dark; }
QLabel#statusPill[cssClass="badgeOrange"] { background: $orange_bg; color: $orange_dark; }

/* ========== 卡片 ========== */
QFrame[cssClass="card"] {
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame[cssClass="card"]:hover { border-color: $border_strong; }

QFrame[cssClass="sectionCard"] {
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}

QLabel[cssClass="cardTitle"] { color: $text_muted; font-size: 12px; background: transparent; }
QLabel[cssClass="cardValue"] { color: $text; font-size: 20px; font-weight: 700; background: transparent; }
QLabel[cssClass="cardValueSmall"] { color: $text; font-size: 15px; font-weight: 600; background: transparent; }
QLabel[cssClass="cardSub"] { color: $text_faint; font-size: 12px; background: transparent; }

/* 卡片数值色调（通过 tone 属性切换） */
QLabel[cssClass="cardValue"][tone="green"] { color: $green_dark; }
QLabel[cssClass="cardValue"][tone="orange"] { color: $orange_dark; }
QLabel[cssClass="cardValue"][tone="red"] { color: $red_dark; }
QLabel[cssClass="cardValue"][tone="brand"] { color: $brand; font-weight: 600; }
QLabel[cssClass="cardValueSmall"][tone="green"] { color: $green_dark; }
QLabel[cssClass="cardValueSmall"][tone="orange"] { color: $orange_dark; }
QLabel[cssClass="cardValueSmall"][tone="red"] { color: $red_dark; }

/* Hash 等宽显示 */
QLabel[cssClass="hashLabel"] {
    font-family: $mono_family;
    font-size: 12px;
    color: $text_secondary;
    background: transparent;
}

/* 配置状态 */
QLabel[cssClass="configOk"] { color: $green_dark; font-size: 12px; background: transparent; }
QLabel[cssClass="configError"] { color: $red_dark; font-size: 12px; background: transparent; }

/* 进度信息 */
QLabel[cssClass="progressSpeed"] { color: $blue_dark; font-size: 12px; background: transparent; }
QLabel[cssClass="progressEta"] { color: $green_dark; font-size: 12px; background: transparent; }
QLabel[cssClass="progressSuccess"] { color: $green_dark; font-size: 12px; background: transparent; }
QLabel[cssClass="progressError"] { color: $red_dark; font-size: 12px; background: transparent; }

QLabel[cssClass="sectionTitle"] { color: $text; font-size: 15px; font-weight: 600; background: transparent; }
QLabel[cssClass="sectionHint"] { color: $text_muted; font-size: 12px; background: transparent; }
QFrame[cssClass="divider"] { background: $border; max-height: 1px; border: none; }
QLabel[cssClass="formLabel"] { color: $text_secondary; font-size: 13px; background: transparent; }

/* ========== 徽章（胶囊） ========== */
QLabel[cssClass="badge"], QLabel[cssClass="badgeGreen"], QLabel[cssClass="badgeRed"],
QLabel[cssClass="badgeOrange"], QLabel[cssClass="badgeBlue"], QLabel[cssClass="badgeGray"],
QLabel[cssClass="badgeCyan"], QLabel[cssClass="statusPill"] {
    border-radius: 999px;
    padding: 3px 11px;
    font-size: 11px;
    font-weight: 600;
    background: $gray_bg;
    color: $gray_dark;
}
QLabel[cssClass="badgeGreen"] { background: $green_bg; color: $green_dark; }
QLabel[cssClass="badgeRed"] { background: $red_bg; color: $red_dark; }
QLabel[cssClass="badgeOrange"] { background: $orange_bg; color: $orange_dark; }
QLabel[cssClass="badgeBlue"] { background: $blue_bg; color: $blue_dark; }
QLabel[cssClass="badgeGray"] { background: $gray_bg; color: $gray_dark; }
QLabel[cssClass="badgeCyan"] { background: $cyan_bg; color: $cyan_dark; }

/* ========== 通用按钮 ========== */
QPushButton {
    background: $surface;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: 9px;
    padding: 8px 18px;
    font-size: 13px;
}
QPushButton:hover { background: $btn_hover_bg; border-color: $border_strong; }
QPushButton:pressed { background: $border; }
QPushButton:disabled { color: $input_disabled_text; background: $input_disabled_bg; border-color: $border; }

QPushButton[primary="true"] {
    background: $brand;
    color: $on_brand;
    border: none;
    font-weight: 600;
}
QPushButton[primary="true"]:hover { background: $brand_dark; }
QPushButton[primary="true"]:pressed { background: $brand_darker; }
QPushButton[primary="true"]:disabled { background: $primary_disabled_bg; color: $primary_disabled_text; }

/* 主行动按钮（CTA）：比普通主按钮更大更醒目，用于「开始下载」这类关键动作 */
QPushButton[cta="true"] {
    background: $brand;
    color: $on_brand;
    border: none;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 700;
    padding: 0 24px;
    min-width: 104px;
    min-height: 38px;
}
QPushButton[cta="true"]:hover { background: $brand_dark; }
QPushButton[cta="true"]:pressed { background: $brand_darker; }
QPushButton[cta="true"]:disabled { background: $primary_disabled_bg; color: $primary_disabled_text; }

QPushButton[danger="true"] { color: $red; border-color: $danger_border; }
QPushButton[danger="true"]:hover { background: $danger_hover_bg; border-color: $danger_hover_border; color: $red_dark; }

QPushButton[small="true"] { padding: 5px 13px; font-size: 12px; border-radius: 8px; }

/* ========== 右键菜单 ==========
   注意：QMenu 是独立的弹出窗口，一旦背景没被画上就露出未初始化的黑色表面
   （控件级 setStyleSheet("background: transparent;") 会级联到弹出的 QMenu，
   把这里的背景覆盖掉，菜单随即变成纯黑底 + 深色字）。
   因此 QMenu 与 QMenu::item 都必须显式给出背景与前景，且容器禁用裸声明样式表。 */
QMenu {
    background: $surface;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 5px;
    color: $text;
    font-size: 13px;
}
QMenu::item {
    background: transparent;
    color: $text;
    padding: 7px 24px;
    border-radius: 7px;
}
QMenu::item:selected { background: $brand_light; color: $brand; }
QMenu::item:checked { color: $brand; font-weight: 600; }
QMenu::item:disabled { color: $text_faint; }
QMenu::separator { height: 1px; background: $gray_bg; margin: 4px 8px; }
QMenu::indicator { width: 12px; height: 12px; margin-left: 4px; }

/* ========== 输入控件 ========== */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background: $input;
    border: 1px solid $border_strong;
    border-radius: 9px;
    padding: 8px 11px;
    color: $text;
    selection-background-color: $brand;
    selection-color: $on_brand;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid $brand;
}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
    background: $input_disabled_bg; color: $input_disabled_text;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: $surface;
    border: 1px solid $border;
    border-radius: 9px;
    padding: 5px;
    outline: 0;
    color: $text;
    selection-background-color: $brand;
    selection-color: $on_brand;
}
QComboBox QAbstractItemView::item {
    min-height: 28px;
    padding: 2px 10px;
    border: none;
    border-radius: 7px;
    color: $text;
    background: transparent;
}
QComboBox QAbstractItemView::item:hover {
    background: $brand_light;
    color: $brand;
}
QComboBox QAbstractItemView::item:selected {
    background: $brand;
    color: $on_brand;
}
QSpinBox::up-button, QSpinBox::down-button {
    border: none; background: transparent; width: 18px;
}
QSpinBox::up-arrow, QSpinBox::down-arrow { width: 0; height: 0; }

/* ========== 复选框 ========== */
QCheckBox {
    spacing: 9px;
    color: $text_strong;
}
QCheckBox::indicator {
    width: 17px; height: 17px;
    border-radius: 5px;
    border: 1.5px solid $border_strong;
    background: $input;
}
QCheckBox::indicator:hover { border-color: $brand; }
QCheckBox::indicator:checked {
    background: $brand;
    border-color: $brand;
}

/* ========== 进度条 ========== */
QProgressBar {
    background: $progress_bg;
    border: none;
    border-radius: 5px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: $brand; border-radius: 5px; }
QProgressBar[color="green"]::chunk { background: $green; }
QProgressBar[color="red"]::chunk { background: $red; }
QProgressBar[color="orange"]::chunk { background: $orange; }

/* ========== 日志面板 ========== */
QTextEdit[cssClass="logPanel"] {
    background: $log_bg;
    color: $log_text;
    border: 1px solid $log_border;
    border-radius: 12px;
    font-family: $mono_family;
    font-size: 12px;
    padding: 12px;
    selection-background-color: $brand_light;
    selection-color: $text;
}
QTextEdit[cssClass="dlLogPanel"] {
    background: $surface;
    color: $log_dl_text;
    border: 1px solid $border;
    border-radius: 12px;
    font-family: $mono_family;
    font-size: 12px;
    padding: 12px;
    selection-background-color: $brand_light;
}

/* ========== 设置分组 ========== */
QWidget#settingsHost { background: transparent; }
/* 设置页滚动内容页：显式主题底色，杜绝视口调色板回退发黑 */
QWidget#settingsScrollPage { background: $bg; }
QScrollArea { background: transparent; border: none; }

/* ========== 透明容器 ==========
   统一在全局 QSS 里按 objectName 上色，禁止在业务代码里用
   setStyleSheet("background: transparent;") —— 裸声明的控件级样式表会级联到
   该控件下的所有子控件（包括 QMenu / QToolTip 这类弹出窗口），
   把弹出层背景覆盖成透明，最终露出未初始化表面的纯黑底。 */
QWidget#tagHost,
QWidget#pageHost,
QWidget#taskListHost { background: transparent; }

/* ========== 标签页（分段式） ========== */
QTabWidget::pane {
    border: 1px solid $border;
    border-radius: 12px;
    background: $bg;
    top: -1px;
}
QTabWidget QTabWidget,
QTabWidget QTabWidget::pane,
QTabWidget QStackedWidget { background: $bg; }
QTabBar::tab {
    background: transparent;
    color: $text_secondary;
    border: none;
    padding: 9px 18px;
    margin-right: 4px;
    border-radius: 8px;
    font-size: 13px;
}
QTabBar::tab:hover { color: $text; background: $gray_bg; }
QTabBar::tab:selected { background: $surface; color: $text; font-weight: 600; }

/* ========== 滚动条 ========== */
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 2px;
}
QScrollBar::handle:vertical {
    background: $scroll_handle; border-radius: 5px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: $scroll_handle_hover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 2px;
}
QScrollBar::handle:horizontal {
    background: $scroll_handle; border-radius: 5px; min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: $scroll_handle_hover; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ========== 任务卡 ========== */
QLabel[cssClass="taskTitle"] { color: $text; font-size: 13px; font-weight: 600; background: transparent; }
QLabel[cssClass="taskMeta"] { color: $text_faint; font-size: 11px; background: transparent; }
QLabel[cssClass="taskDetail"] { color: $text_secondary; font-size: 12px; background: transparent; }
QLabel[cssClass="taskError"] { color: $red_dark; font-size: 12px; background: transparent; }

/* ========== 其他 ========== */
QLabel[muted="true"] { color: $text_faint; font-size: 12px; background: transparent; }
QLabel[sectionHeader="true"] { color: $text_strong; font-size: 13px; font-weight: 600; background: transparent; }

/* 状态标签（日志页核心状态） */
QLabel[cssClass="statusLabel"] {
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}
QLabel[cssClass="statusLabel"][tone="green"] { color: $green_dark; }
QLabel[cssClass="statusLabel"][tone="orange"] { color: $orange_dark; }
QLabel[cssClass="statusLabel"][tone="red"] { color: $red_dark; }

/* ========== 空状态（任务列表占位） ========== */
QFrame#emptyState {
    background: $surface;
    border: 1px dashed $border_strong;
    border-radius: 12px;
}
QLabel[cssClass="emptyTitle"] { color: $text_secondary; font-size: 14px; font-weight: 600; background: transparent; }
QLabel[cssClass="emptyHint"] { color: $text_faint; font-size: 12px; background: transparent; }

/* ========== FFmpeg 完整版下载提示条 ========== */
QFrame#ffmpegNotice {
    background: $brand_light;
    border: 1px solid $border;
    border-radius: 12px;
}
QLabel#ffmpegNoticeText { color: $text_secondary; font-size: 12px; background: transparent; }
""")


def build_qss(theme: str = "light") -> str:
    """按主题名生成完整 QSS"""
    t = dict(THEMES[theme])
    t["font_family"] = FONT_FAMILY
    t["mono_family"] = MONO_FAMILY
    return _QSS_TEMPLATE.substitute(t)


def build_palette(theme: str = "light") -> QPalette:
    """按主题构建 QPalette：兜底无 QSS 覆盖的原生控件（菜单、弹窗、文件对话框等）"""
    t = THEMES[theme]
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: t["bg"],
        QPalette.ColorRole.Base: t["input"],
        QPalette.ColorRole.AlternateBase: t["bg"],
        QPalette.ColorRole.Button: t["surface"],
        QPalette.ColorRole.Text: t["text"],
        QPalette.ColorRole.WindowText: t["text"],
        QPalette.ColorRole.ButtonText: t["text"],
        QPalette.ColorRole.BrightText: t["text"],
        QPalette.ColorRole.ToolTipBase: t["tooltip_bg"],
        QPalette.ColorRole.ToolTipText: t["tooltip_text"],
        QPalette.ColorRole.PlaceholderText: t["text_muted"],
        QPalette.ColorRole.Link: t["brand"],
        QPalette.ColorRole.Highlight: t["brand"],
        QPalette.ColorRole.HighlightedText: t["on_brand"],
        QPalette.ColorRole.Light: t["border_strong"],
        QPalette.ColorRole.Midlight: t["border"],
        QPalette.ColorRole.Mid: t["border"],
        QPalette.ColorRole.Dark: t["sidebar"],
        QPalette.ColorRole.Shadow: t["sidebar"],
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    return pal


# =====================================================================
# 运行时状态：当前激活主题 + C 兼容视图
# =====================================================================

_active_theme = "light"  # 当前激活主题名（light / dark）


def _tokens() -> dict:
    return THEMES[_active_theme]


class _ThemeColors(dict):
    """C 的兼容视图：C["brand"] 始终返回当前激活主题的令牌值。

    历史代码 `from theme import C` 后按需取色，无需改动即可跟随主题；
    只有 import 期就快照成模块常量的用法需要改为懒解析。
    """

    def __getitem__(self, key):
        return _tokens()[key]

    def get(self, key, default=None):
        return _tokens().get(key, default)

    def copy(self):
        return dict(_tokens())


C = _ThemeColors()


def current_theme() -> str:
    return _active_theme


def is_dark() -> bool:
    return _active_theme == "dark"


# =====================================================================
# 主题模式持久化（跟随系统 / 浅色 / 深色）
# 默认浅色模式（不跟随系统），可在设置中手动切换
# =====================================================================

MODE_SYSTEM = "system"
MODE_LIGHT = "light"
MODE_DARK = "dark"
MODES = (MODE_SYSTEM, MODE_LIGHT, MODE_DARK)

MODE_LABELS = {
    MODE_SYSTEM: "跟随系统",
    MODE_LIGHT: "浅色模式",
    MODE_DARK: "深色模式",
}


def _prefs_path():
    from pathlib import Path

    from system_info import system_info

    return system_info.get_config_dir() / "ui_prefs.json"


def load_mode() -> str:
    """读取主题模式：从持久化配置加载，默认浅色模式"""
    try:
        path = _prefs_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            mode = data.get("theme_mode", MODE_LIGHT)
            if mode in MODES:
                return mode
    except Exception:
        pass
    return MODE_LIGHT


def save_mode(mode: str) -> None:
    """持久化主题模式"""
    if mode not in MODES:
        return
    try:
        path = _prefs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"theme_mode": mode}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def system_prefers_dark() -> bool:
    """查询系统当前配色偏好；Unknown（无法识别）时按浅色处理"""
    app = QApplication.instance()
    if app is None:
        return False
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


# =====================================================================
# 主题管理器：应用/切换主题 + 系统主题跟随
# =====================================================================

class ThemeManager(QObject):
    """主题管理器（单例）

    - set_mode(mode)：设置主题模式（system/light/dark）并立即应用
    - 系统主题切换时，mode=system 会自动跟随换肤
    - 切换后遍历所有已创建控件，调用其 refresh_theme() 重放内联动态颜色
    """

    theme_changed = Signal(str)  # 新主题名：light / dark

    def __init__(self):
        super().__init__()
        self._mode = MODE_LIGHT  # 默认浅色模式
        self._poll_timer = None

    # ------------------------------------------------------------ 状态

    @property
    def mode(self) -> str:
        return self._mode

    def active_theme(self) -> str:
        return current_theme()

    # ------------------------------------------------------------ 应用

    def set_mode(self, mode: str, persist: bool = True) -> str:
        """设置主题模式并应用，返回实际激活的主题名"""
        if mode not in MODES:
            mode = MODE_LIGHT
        self._mode = mode
        if persist:
            save_mode(mode)
        if mode == MODE_SYSTEM:
            target = "dark" if system_prefers_dark() else "light"
        else:
            target = mode
        self._apply(target)
        return target

    def _apply(self, theme: str) -> None:
        global _active_theme
        changed = theme != _active_theme
        _active_theme = theme
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_qss(theme))
            app.setPalette(build_palette(theme))
            # 通知已有控件重放内联动态颜色
            for widget in app.allWidgets():
                try:
                    refresh = getattr(widget, "refresh_theme", None)
                    if callable(refresh):
                        refresh()
                except Exception:
                    pass
        if changed:
            self.theme_changed.emit(theme)

    def sync_with_system(self) -> None:
        """系统主题跟随：colorSchemeChanged 信号或轮询兜底触发"""
        if self._mode != MODE_SYSTEM:
            return
        target = "dark" if system_prefers_dark() else "light"
        if target != _active_theme:
            self._apply(target)

    # ------------------------------------------------------------ 系统跟随

    def start_system_follow(self, interval_ms: int = 3000) -> None:
        """启动系统主题跟随：连接系统信号 + 轮询兜底"""
        app = QApplication.instance()
        if app is None:
            return
        try:
            app.styleHints().colorSchemeChanged.connect(self.sync_with_system)
        except Exception:
            pass
        if self._poll_timer is None:
            self._poll_timer = QTimer()
            self._poll_timer.timeout.connect(self.sync_with_system)
            self._poll_timer.start(interval_ms)


# 全局单例
theme_manager = ThemeManager()
