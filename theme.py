"""
全局主题模块（双主题架构）
视觉风格参考自 Qoder 应用设计：
- 现代简洁的卡片式布局
- 低饱和度配色 + Miku 青品牌色
- 圆角 8-12px，柔和阴影
- 双主题可切换（深色/浅色）

架构说明：
- light/dark 两个主题使用完全相同的键名
- 所有颜色集中在 THEMES 令牌表；QSS 由 build_qss() 按主题生成
- ThemeManager 单例管理主题切换，持久化用户选择
"""

import json
from string import Template

from PySide6.QtCore import QObject, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

APP_TITLE = "JiuDown"
APP_VERSION = "1.0.0"

# =====================================================================
# 主题令牌表
# 两个主题使用完全相同的键名；QSS 与业务代码只认键，不认主题
# light 的每个值都与重构前硬编码的色值一致
# =====================================================================

LIGHT = {
    # 品牌色
    "brand": "#39C5BB",
    "brand_dark": "#0E948C",
    "brand_darker": "#0d7f78",
    "brand_light": "#e6f7f6",
    "on_brand": "#ffffff",
    # 基础
    "bg": "#f0f7f7",
    "surface": "#ffffff",
    "border": "#c2e2e0",
    "border_strong": "#9fd4d0",
    # 文本
    "text": "#1a2423",
    "text_secondary": "#546b69",
    "text_muted": "#7f9b99",
    "text_faint": "#9bb0b2",
    "text_strong": "#33415a",
    # 侧边栏（暗灰青，对齐博客暗色主题 surface）
    "sidebar": "#1f2937",
    "sidebar_hover": "#28373b",
    "sidebar_text": "#9bb0b2",
    "sidebar_version": "#6b8082",
    "sidebar_divider": "#3a4a4e",
    "nav_checked_text": "#ffffff",
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
    # 输入控件
    "input": "#ffffff",
    "input_disabled_bg": "#e9f2f1",
    "input_disabled_text": "#9bb0b2",
    # 按钮
    "btn_hover_bg": "#f0f7f7",
    "primary_disabled_bg": "#a8e3df",
    "primary_disabled_text": "#ffffff",
    "danger_border": "#fecaca",
    "danger_hover_bg": "#fee2e2",
    "danger_hover_border": "#fca5a5",
    # 浮层
    "tooltip_bg": "#1f2937",
    "tooltip_text": "#e9f2f1",
    "tooltip_border": "#3a4a4e",
    # 一体化标题栏（隐藏原生标题栏后由应用自身承担：左段随侧边栏色，右段随内容底色）
    "titlebar_text": "#cfe4e2",
    "titlebar_icon": "#546b69",
    "titlebar_ctrl_hover": "#dcebe9",
    "titlebar_ctrl_pressed": "#c6dedc",
    "titlebar_close_hover": "#c42b1c",
    "titlebar_close_pressed": "#9e1b14",
    # 滚动条 / 进度条
    "scroll_handle": "#c2e2e0",
    "scroll_handle_hover": "#9fd4d0",
    "progress_bg": "#e9f2f1",
    # 视频播放条（常驻深色半透明媒体面，不随主题反色）
    "media_groove": "#e9f2f1",
    "media_text": "#c2d6d4",
    # 日志面板
    "log_bg": "#1f2937",
    "log_border": "#334155",
    "log_text": "#c2d6d4",
    "log_dl_text": "#33415a",
}

# 深色主题：与浅色同色系派生（青绿 + 深青灰），不是反色
# 关键取值均经 WCAG 对比度计算验证（详见项目文档）：
#   正文 on 卡片 14.19:1 / 次要 9.02:1 / 弱文字 5.41:1 / 徽章六色 8.0~9.7:1
DARK = {
    # 品牌色（深色底下提亮，保证醒目与可读）
    "brand": "#4fd8c8",
    "brand_dark": "#35b8ab",
    "brand_darker": "#2a9e93",
    "brand_light": "#10312e",
    "on_brand": "#07211d",
    # 基础（背景不用纯黑：带青调的深色；层级靠表面抬升）
    "bg": "#0d1917",
    "surface": "#14211f",
    "border": "#273f3b",
    "border_strong": "#375853",
    # 文本（不用纯白）
    "text": "#e4f0ed",
    "text_secondary": "#a9c5c0",
    "text_muted": "#7d9994",
    "text_faint": "#79928d",
    "text_strong": "#e4f0ed",
    # 侧边栏（深色主题下比内容区再暗一档，保持"深色锚点"的层级角色）
    "sidebar": "#0a1412",
    "sidebar_hover": "#162623",
    "sidebar_text": "#9bb0b2",
    "sidebar_version": "#708785",
    "sidebar_divider": "#24403b",
    "nav_checked_text": "#07211d",
    # 状态色（深色底用亮变体；徽章用低亮度同色相底 + 亮文字）
    "green": "#34d399",
    "green_dark": "#6ee7b7",
    "green_bg": "#0e2f24",
    "red": "#f87171",
    "red_dark": "#fca5a5",
    "red_bg": "#3b1719",
    "orange": "#fbbf24",
    "orange_dark": "#fcd34d",
    "orange_bg": "#3d2b0e",
    "blue": "#2dd4bf",
    "blue_dark": "#5eead4",
    "blue_bg": "#0e2f2c",
    "gray": "#8fa8a4",
    "gray_dark": "#a9c5c0",
    "gray_bg": "#1c2b29",
    "cyan": "#2dd4bf",
    "cyan_dark": "#5eead4",
    "cyan_bg": "#0e2f2c",
    # 输入控件（比表面再暗一档，形成"可输入"的视觉暗示）
    "input": "#0f1c1a",
    "input_disabled_bg": "#0a1412",
    "input_disabled_text": "#5f7c79",
    # 按钮
    "btn_hover_bg": "#1b2b28",
    "primary_disabled_bg": "#1c4a45",
    "primary_disabled_text": "#6f9a94",
    "danger_border": "#4a2326",
    "danger_hover_bg": "#3b1719",
    "danger_hover_border": "#6e2b2f",
    # 浮层（深色主题下 tooltip 用比表面略亮的浮层，不用反色）
    "tooltip_bg": "#22322f",
    "tooltip_text": "#e4f0ed",
    "tooltip_border": "#375853",
    # 一体化标题栏（左段随侧边栏、右段随内容底色）
    "titlebar_text": "#a9c5c0",
    "titlebar_icon": "#a9c5c0",
    "titlebar_ctrl_hover": "#1e2f2c",
    "titlebar_ctrl_pressed": "#2a3f3b",
    "titlebar_close_hover": "#c42b1c",
    "titlebar_close_pressed": "#9e1b14",
    # 滚动条 / 进度条
    "scroll_handle": "#273f3b",
    "scroll_handle_hover": "#375853",
    "progress_bg": "#1c2b29",
    # 视频播放条（常驻深色半透明媒体面，不随主题反色）
    "media_groove": "#3a4a4e",
    "media_text": "#c2d6d4",
    # 日志面板（两个主题下都是"深色控制台"：深色主题里比卡片更暗一档）
    "log_bg": "#08110f",
    "log_border": "#24403b",
    "log_text": "#c2d6d4",
    "log_dl_text": "#c9dcd9",
}

THEMES = {"light": LIGHT, "dark": DARK}

# =====================================================================
# QSS 模板（$token 占位，string.Template 注入；QSS 自身不含 $ 字符）
# =====================================================================

_QSS_TEMPLATE = Template("""
/* ========== 全局 ========== */
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 13px;
    color: $text;
}
QMainWindow, QWidget#contentRoot {
    background: $bg;
}
QLabel { background: transparent; }
QToolTip {
    background: $tooltip_bg; color: $tooltip_text; border: 1px solid $tooltip_border; border-radius: 6px; padding: 4px 8px;
}

/* ========== 一体化标题栏（无原生边框，应用自身 chrome） ========== */
QWidget#titleBar { background: transparent; }
QWidget#titleBarLeft { background: $sidebar; }
QWidget#titleBarRight { background: $bg; }
QLabel#titlebarTitle { color: $titlebar_text; font-size: 13px; font-weight: 600; background: transparent; }
/* 窗口控制按钮为自绘（paintEvent），此处仅中性化通用按钮样式 */
QPushButton[captionBtn="true"] { background: transparent; border: none; border-radius: 0; padding: 0; }

/* ========== 侧边栏 ========== */
QFrame#sidebar {
    background: $sidebar;
    border: none;
}
QLabel#sidebarTitle { color: $brand; font-size: 16px; font-weight: 700; background: transparent; }
QLabel#sidebarSub { color: $sidebar_text; font-size: 11px; background: transparent; }
QLabel#sidebarVersion { color: $sidebar_version; font-size: 11px; background: transparent; }
QFrame#sidebarDivider { background: $sidebar_divider; border: none; max-height: 1px; }

/* ========== 导航按钮 ========== */
QPushButton[nav="true"] {
    color: $sidebar_text;
    background: transparent;
    border: none;
    border-radius: 10px;
    padding: 10px 8px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
}
QPushButton[nav="true"]:hover { background: $sidebar_hover; color: $sidebar_text; }
QPushButton[nav="true"]:checked { background: $brand; color: $nav_checked_text; font-weight: 600; }
QPushButton[nav="true"][collapsed="true"] { padding: 4px 8px; text-align: center; }
QPushButton#sidebarToggle {
    background: transparent; color: $sidebar_text; border: none; border-radius: 6px;
    font-size: 14px; font-weight: 600;
}
QPushButton#sidebarToggle:hover { background: $sidebar_hover; color: $sidebar_text; }
QPushButton#sidebarToggle:pressed { background: $sidebar_divider; }

/* ========== 页头 ========== */
QLabel#pageTitle { font-size: 22px; font-weight: 700; color: $text; background: transparent; }
QLabel#pageSubtitle { font-size: 12px; color: $text_muted; background: transparent; }
QLabel#statusPill {
    background: $gray_bg;
    color: $text_secondary;
    border: 1px solid $border;
    border-radius: 999px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 600;
}

/* ========== 卡片 ========== */
QFrame[cssClass="card"] {
    background: $surface;
    border: 1px solid $border;
    border-radius: 14px;
}
QFrame[cssClass="card"]:hover { border-color: $border_strong; }

QLabel[cssClass="cardTitle"] { color: $text_muted; font-size: 12px; background: transparent; }
QLabel[cssClass="cardValue"] { color: $text; font-size: 21px; font-weight: 700; background: transparent; }
QLabel[cssClass="cardValueSmall"] { color: $text; font-size: 14px; font-weight: 600; background: transparent; }
QLabel[cssClass="cardSub"] { color: $text_faint; font-size: 11px; background: transparent; }

/* ========== 徽章（胶囊） ========== */
QLabel[cssClass="badge"] {
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
}
QLabel[cssClass="badgeGreen"] { background: $green_bg; color: $green_dark; }
QLabel[cssClass="badgeRed"] { background: $red_bg; color: $red_dark; }
QLabel[cssClass="badgeOrange"] { background: $orange_bg; color: $orange_dark; }
QLabel[cssClass="badgeBlue"] { background: $blue_bg; color: $blue_dark; }
QLabel[cssClass="badgeGray"] { background: $gray_bg; color: $gray_dark; }
QLabel[cssClass="badgeCyan"] { background: $cyan_bg; color: $cyan_dark; }

/* ========== 通用按钮（胶囊） ========== */
QPushButton {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 999px;
    padding: 8px 18px;
    font-size: 13px;
}
QPushButton:hover { background: $btn_hover_bg; border-color: $border_strong; color: $brand_dark; }
QPushButton:pressed { background: $brand_light; }
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

QPushButton[danger="true"] { color: $red; border-color: $danger_border; }
QPushButton[danger="true"]:hover { background: $danger_hover_bg; border-color: $danger_hover_border; color: $red_dark; }

QPushButton[small="true"] { padding: 4px 12px; font-size: 12px; border-radius: 999px; }

/* ========== 右键菜单 ========== */
QMenu {
    background: $surface;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 4px;
    color: $text;
    font-size: 13px;
}
QMenu::item { padding: 6px 22px; border-radius: 6px; }
QMenu::item:selected { background: $brand_light; color: $brand_dark; }
QMenu::item:checked { color: $brand_dark; font-weight: 600; }
QMenu::separator { height: 1px; background: $gray_bg; margin: 4px 8px; }
QMenu::indicator { width: 12px; height: 12px; margin-left: 4px; }

/* ========== 输入控件 ========== */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background: $input;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 7px 10px;
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
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: $surface;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 4px;
    outline: 0;
    color: $text;
    selection-background-color: $brand;
    selection-color: $on_brand;
}
QComboBox QAbstractItemView::item {
    min-height: 26px;
    padding: 2px 10px;
    border: none;
    border-radius: 8px;
    color: $text;
    background: transparent;
}
QComboBox QAbstractItemView::item:hover {
    background: $brand_light;
    color: $brand_dark;
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
    spacing: 8px;
    color: $text_strong;
}
QCheckBox::indicator {
    width: 16px; height: 16px;
    border-radius: 5px;
    border: 1px solid $border;
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
    border-radius: 8px;
    min-height: 10px;
    max-height: 10px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: $brand; border-radius: 8px; }
QProgressBar[color="green"]::chunk { background: $green; }
QProgressBar[color="red"]::chunk { background: $red; }
QProgressBar[color="orange"]::chunk { background: $orange; }

/* ========== 日志面板 ========== */
QTextEdit[cssClass="logPanel"] {
    background: $log_bg;
    color: $log_text;
    border: 1px solid $log_border;
    border-radius: 12px;
    font-family: "Cascadia Code", "Consolas", "Microsoft YaHei UI", monospace;
    font-size: 12px;
    padding: 10px;
    selection-background-color: $sidebar_divider;
    selection-color: $tooltip_text;
}
QTextEdit[cssClass="dlLogPanel"] {
    background: $surface;
    color: $log_dl_text;
    border: 1px solid $border;
    border-radius: 12px;
    font-family: "Cascadia Code", "Consolas", "Microsoft YaHei UI", monospace;
    font-size: 12px;
    padding: 10px;
    selection-background-color: $brand_light;
}

/* ========== 设置分组 ========== */
QFrame[cssClass="sectionCard"] {
    background: $surface;
    border: 1px solid $border;
    border-radius: 14px;
}
QLabel[cssClass="sectionTitle"] { color: $text; font-size: 15px; font-weight: 700; background: transparent; }
QLabel[cssClass="sectionHint"] { color: $text_faint; font-size: 11px; background: transparent; }
QFrame[cssClass="divider"] { background: $border; border: none; max-height: 1px; }
QLabel[cssClass="formLabel"] { color: $text_secondary; font-size: 13px; background: transparent; }
QWidget#settingsHost { background: transparent; }

/* ========== 标签页 ========== */
QTabWidget::pane {
    border: 1px solid $border;
    border-radius: 14px;
    background: $bg;
    top: -1px;
}
/* 嵌套标签页兜底：与 ::pane 同背景，避免任何系统主题下出现意外底色 */
QTabWidget QTabWidget,
QTabWidget QTabWidget::pane,
QTabWidget QStackedWidget { background: $bg; }
QTabBar::tab {
    background: transparent;
    color: $text_muted;
    border: none;
    padding: 9px 20px;
    margin-right: 6px;
    border-radius: 999px;
    font-size: 13px;
}
QTabBar::tab:hover { color: $text; background: $brand_light; }
QTabBar::tab:selected { background: $brand_light; color: $brand_dark; font-weight: 600; }

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

/* ========== 其他 ========== */
QLabel[muted="true"] { color: $text_faint; font-size: 12px; background: transparent; }
QLabel[sectionHeader="true"] { color: $text_strong; font-size: 13px; font-weight: 600; background: transparent; }

/* ========== 空状态（任务列表占位） ========== */
QFrame#emptyState {
    background: $surface;
    border: 1px dashed $border_strong;
    border-radius: 14px;
}
QLabel[cssClass="emptyTitle"] { color: $text_secondary; font-size: 14px; font-weight: 600; background: transparent; }
QLabel[cssClass="emptyHint"] { color: $text_faint; font-size: 12px; background: transparent; }

/* ========== FFmpeg 完整版下载提示条 ========== */
QFrame#ffmpegNotice {
    background: $brand_light;
    border: 1px solid $border;
    border-radius: 10px;
}
QLabel#ffmpegNoticeText { color: $text_secondary; font-size: 12px; background: transparent; }
""")


def build_qss(theme: str = "light") -> str:
    """按主题名生成完整 QSS"""
    return _QSS_TEMPLATE.substitute(THEMES[theme])


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
    只有 import 期就快照成模块常量的用法（如下载页旧的 BADGE_COLORS）需要改为懒解析。
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
# 存于 config/ui_prefs.json，与核心程序共用的 config.yaml 隔离
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
    """读取主题模式：从持久化配置加载，默认跟随系统"""
    try:
        path = _prefs_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            mode = data.get("theme_mode", MODE_SYSTEM)
            if mode in MODES:
                return mode
    except Exception:
        pass
    return MODE_SYSTEM


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
    - 切换后遍历所有已创建控件，调用其 refresh_theme()（可选）重放内联动态颜色
    """

    theme_changed = Signal(str)  # 新主题名：light / dark

    def __init__(self):
        super().__init__()
        self._mode = MODE_SYSTEM
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
            mode = MODE_SYSTEM
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
            # 通知已有控件重放内联动态颜色（setStyleSheet 写的颜色不会自动跟随）
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
        """系统主题跟随入口：colorSchemeChanged 信号或轮询兜底触发"""
        if self._mode != MODE_SYSTEM:
            return
        target = "dark" if system_prefers_dark() else "light"
        if target != _active_theme:
            self._apply(target)

    # ------------------------------------------------------------ 系统跟随

    def start_system_follow(self, interval_ms: int = 3000) -> None:
        """启动系统主题跟随：连接系统信号 + 轮询兜底

        Qt >= 6.5 提供 styleHints().colorSchemeChanged，但 Windows 上
        部分环境/版本存在不触发的情况，故保留低频轮询双保险。
        """
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
