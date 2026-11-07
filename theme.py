"""
全局主题模块（纯白单主题）

界面统一使用白色表面、深灰文字与低对比浅灰分隔线；强调色仅用于少量状态与焦点，
不铺高饱和色块。所有颜色集中在 WHITE_BASE 令牌表里，业务代码只认键名，
QSS 由 build_qss() 生成，自绘部件的颜色也通过 C 动态读取。
"""

import json
from string import Template

from PySide6.QtCore import QObject, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

APP_TITLE = "JiuDown"
APP_VERSION = "1.3.0"

# 窗口保持直角
WINDOW_RADIUS = 0

FONT_FAMILY = (
    '"Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", '
    '"PingFang SC", system-ui, sans-serif'
)
MONO_FAMILY = '"Cascadia Mono", "Consolas", "Microsoft YaHei UI", monospace'

# 侧栏宽度动画（ms）
DUR_EDGE = 300


# =====================================================================
# 纯白主题令牌表
# 旧键名由 _with_aliases() 折算到基表值，保证历史代码无需硬编码色值。
# =====================================================================

WHITE_BASE = {
    # ---- 中性灰阶（预定义 8 档，不使用纯黑）----
    "paper":          "#FFFFFF",
    "panel":          "#FFFFFF",
    "surface_subtle": "#FAFBFC",
    "ink":            "#1F2430",
    "ink2":           "#5B6472",
    "ink3":           "#98A1AF",
    "rule":           "#EDF0F3",
    "rule_strong":    "#DEE3E9",
    "chip":           "#F4F6F8",
    "chip_hover":     "#EAEEF2",
    "chip_press":     "#E1E6EC",
    # ---- 主色（蓝）+ 5 档明暗，焦点/激活/CTA 专用 ----
    "signal":         "#2563EB",
    "signal_hover":   "#1D4ED8",
    "signal_press":   "#1E40AF",
    "signal_soft":    "#EFF4FF",
    "signal_tint":    "#DBE7FF",
    "on_signal":      "#FFFFFF",
    "trace":          "#2563EB",
    "mark":           "#2563EB",
    "mark_argb":      "#00000000",
    # ---- 语义色（各带浅底）----
    "danger":         "#DC2626",
    "danger_tint":    "#FEF2F2",
    "warning":        "#D97706",
    "warning_tint":   "#FFFBEB",
    "success":        "#059669",
    "success_tint":   "#ECFDF5",
    "tag_bg":         "#F1F4F8",
    "tag_fg":         "#1F2430",
    "scrim":          "#1F243020",
    # ---- chrome（标题栏/侧栏）----
    "command_bar":        "#FFFFFF",
    "command_bar_text":   "#1F2430",
    "command_bar_sub":    "#5B6472",
    "command_bar_hover":  "#F4F6F8",
    "command_bar_press":  "#E1E6EC",
    "command_bar_rail":   "#EDF0F3",
    "chrome":             "#FFFFFF",
    "chrome_text":        "#5B6472",
    "chrome_sub":         "#98A1AF",
    "chrome_hover":       "#F4F6F8",
    "chrome_active":      "#EFF4FF",
    "chrome_press":       "#E1E6EC",
    "chrome_line":        "#EDF0F3",
    # ---- 表单 / 控件 ----
    "input":                "#FFFFFF",
    "input_disabled":       "#F4F6F8",
    "input_disabled_text":  "#98A1AF",
    "btn_hover":            "#F4F6F8",
    "btn_press":            "#E1E6EC",
    "disabled_fill":        "#F4F6F8",
    "disabled_text":        "#98A1AF",
    "tooltip_bg":           "#FFFFFF",
    "tooltip_text":         "#1F2430",
    "tooltip_border":       "#DEE3E9",
    "scroll_handle":        "#DEE3E9",
    "scroll_handle_hover":  "#98A1AF",
    "progress_bg":          "#EDF0F3",
    "media_surface":        "#FFFFFF",
    "media_groove":         "#EDF0F3",
    "media_text":           "#1F2430",
    "log_bg":               "#FFFFFF",
    "log_border":           "#EDF0F3",
    "log_text":             "#1F2430",
    "log_dl_text":          "#5B6472",
    # ---- 阴影（书的"两层阴影"简化为实色短投影，扁平但有层次）----
    "shadow_ambient": "#E7EBF0",
    "shadow_direct":  "#D6DDE6",
}

# 受限字号阶梯（px）：12 / 13 / 15 / 18 / 24 / 30
# 层级主要靠字重 + 颜色，字号只在这 6 档里取。
TYPE_SCALE = (12, 13, 15, 18, 24, 30)
# 受限间距阶梯（px）：相邻值差 >= 25%
SPACE_SCALE = (4, 8, 12, 16, 24, 32)

_ALIAS_MAP = {
    "bg": "paper",
    "surface": "panel",
    "border": "rule",
    "border_strong": "rule_strong",
    "text": "ink",
    "text_secondary": "ink2",
    "text_muted": "ink2",
    "text_faint": "ink3",
    "text_strong": "ink",
    "brand": "trace",
    "brand_dark": "trace",
    "brand_darker": "trace",
    "on_brand": "on_signal",
    "brand_light": "chip",
    "sidebar": "chrome",
    "sidebar_hover": "chrome_hover",
    "sidebar_text": "chrome_text",
    "sidebar_sub": "chrome_sub",
    "sidebar_version": "chrome_sub",
    "sidebar_divider": "chrome_line",
    "nav_checked_text": "ink",
    "green": "success",
    "green_dark": "success",
    "green_bg": "success_tint",
    "orange": "warning",
    "orange_dark": "warning",
    "orange_bg": "warning_tint",
    "red": "danger",
    "red_dark": "danger",
    "red_bg": "danger_tint",
    "blue": "trace",
    "blue_dark": "trace",
    "blue_bg": "signal_soft",
    "cyan": "ink2",
    "cyan_dark": "ink",
    "cyan_bg": "chip",
    "gray": "ink2",
    "gray_dark": "ink2",
    "gray_bg": "chip",
    "gold": "warning",
    "gold_dark": "warning",
    "gold_light": "warning_tint",
    "input_disabled_bg": "input_disabled",
    "btn_hover_bg": "btn_hover",
    "primary_disabled_bg": "disabled_fill",
    "primary_disabled_text": "disabled_text",
    "danger_border": "danger",
    "danger_hover_bg": "danger_tint",
    "danger_hover_border": "danger",
    "titlebar_text": "chrome_text",
    "titlebar_icon": "chrome_text",
    "titlebar_ctrl_hover": "chrome_hover",
    "titlebar_ctrl_pressed": "chrome_press",
    "titlebar_close_hover": "danger",
    "titlebar_close_pressed": "chip_press",
}


def _with_aliases(base: dict) -> dict:
    """把旧键名折算到基表上；两套主题各自的落点在这里一次算清"""
    tokens = dict(base)
    for legacy, target in _ALIAS_MAP.items():
        tokens[legacy] = base.get(target, tokens[target])
    return tokens


THEME_WHITE = _with_aliases(WHITE_BASE)
THEMES = {"light": THEME_WHITE, "dark": THEME_WHITE}

# =====================================================================
# QSS 模板（$token 占位，string.Template 注入）：白色表面 + 1px 浅灰细线
# =====================================================================

_QSS_TEMPLATE = Template("""
/* ===================== 全局 ===================== */
* {
    font-family: $font_family;
    font-size: 13px;
    color: $ink;
}
QMainWindow, QWidget, QFrame, QScrollArea, QStackedWidget { background: $paper; }
QLabel { background: transparent; }
QToolTip {
    background: $tooltip_bg; color: $tooltip_text;
    border: 1px solid $tooltip_border; border-radius: 8px; padding: 6px 10px;
}

/* ===================== chrome：标题栏 + 侧栏 ===================== */
QWidget#titleBar, QWidget#titleBarLeft, QWidget#titleBarRight { background: $chrome; }
QLabel#titlebarTitle { color: $ink; font-size: 13px; font-weight: 600; background: transparent; }
QPushButton[captionBtn="true"] { background: transparent; border: none; padding: 0; }

QFrame#sidebar {
    background: $chrome;
    border: none;
    border-right: 1px solid $chrome_line;
}
QLabel#sidebarTitle { color: $ink; font-size: 15px; font-weight: 800; background: transparent; }
QLabel#sidebarSub, QLabel#sidebarVersion { color: $ink3; font-size: 12px; background: transparent; }
QFrame#sidebarDivider { background: $chrome_line; border: none; max-height: 1px; margin-left: 12px; }

/* 导航：默认灰字，当前项用主色文字 + 左侧 2px 强调边 + 浅蓝底 */
QPushButton[nav="true"] {
    background: transparent; color: $ink2;
    border: none; border-left: 2px solid transparent; border-radius: 8px;
    padding: 0 10px; text-align: left; font-size: 13px; font-weight: 600;
}
QPushButton[nav="true"]:hover { background: $chrome_hover; color: $ink; }
QPushButton[nav="true"]:pressed { background: $chrome_press; }
QPushButton[nav="true"]:checked {
    background: $chrome_active; color: $signal;
    border-left: 2px solid $signal; font-weight: 700;
}
QPushButton[nav="true"][collapsed="true"] { padding: 0; text-align: center; border-radius: 8px; }
QPushButton#sidebarToggle {
    background: transparent; color: $ink3; border: none; border-radius: 8px; margin-left: 4px;
}
QPushButton#sidebarToggle:hover { background: $chrome_hover; color: $ink; }
QPushButton#sidebarToggle:pressed { background: $chrome_press; }

/* ===================== 页头：层级靠字重与颜色 ===================== */
QLabel#pageEyebrow { font-size: 12px; font-weight: 600; color: $ink3; background: transparent; }
QLabel#pageTitle { font-size: 24px; font-weight: 800; color: $ink; background: transparent; }
QLabel#pageSubtitle { font-size: 13px; color: $ink2; background: transparent; }
QLabel#statusPill {
    border: none; border-radius: 999px; padding: 4px 12px;
    font-size: 12px; font-weight: 600;
    background: $chip; color: $ink2;
}
QLabel#statusPill[cssClass="badgeGreen"] { background: $success_tint; color: $success; }
QLabel#statusPill[cssClass="badgeRed"] { background: $danger_tint; color: $danger; }
QLabel#statusPill[cssClass="badgeBlue"] { background: $signal_soft; color: $signal; }
QLabel#statusPill[cssClass="badgeOrange"] { background: $warning_tint; color: $warning; }

/* ===================== 卡片：少边框，用底色差 + 极浅实色阴影 ===================== */
QFrame[cssClass="card"], QFrame[cssClass="sectionCard"] {
    background: $panel;
    border: 1px solid $rule;
    border-radius: 10px;
}
QFrame[cssClass="card"]:hover { border-color: $rule_strong; }

QLabel[cssClass="cardTitle"] { color: $ink3; font-size: 12px; font-weight: 600; background: transparent; }
QLabel[cssClass="cardValue"] { color: $ink; font-size: 30px; font-weight: 800; background: transparent; }
QLabel[cssClass="cardValueSmall"] { color: $ink; font-size: 18px; font-weight: 700; background: transparent; }
QLabel[cssClass="cardSub"] { color: $ink3; font-size: 12px; background: transparent; }
QLabel[cssClass="cardValue"][tone="red"] { color: $danger; }
QLabel[cssClass="cardValue"][tone="brand"] { color: $signal; font-weight: 800; }
QLabel[cssClass="cardValueSmall"][tone="red"] { color: $danger; }

QLabel[cssClass="hashLabel"], QLabel[cssClass="field"] {
    font-family: $mono_family; font-size: 12px; color: $ink2; background: transparent;
}
QLabel[cssClass="configOk"] { color: $success; font-size: 12px; background: transparent; }
QLabel[cssClass="configError"] { color: $danger; font-size: 12px; background: transparent; }
QLabel[cssClass="progressSpeed"], QLabel[cssClass="progressEta"],
QLabel[cssClass="progressSuccess"] { color: $ink2; font-size: 12px; background: transparent; }
QLabel[cssClass="progressError"] { color: $danger; font-size: 12px; background: transparent; }

QLabel[cssClass="sectionTitle"] { color: $ink; font-size: 15px; font-weight: 700; background: transparent; }
QLabel[cssClass="sectionHint"] { color: $ink2; font-size: 12px; background: transparent; }
QFrame[cssClass="divider"] { background: $rule; max-height: 1px; border: none; }
QLabel[cssClass="formLabel"] { color: $ink; font-size: 13px; font-weight: 600; background: transparent; }

/* ===================== 徽标：去边框，用浅底 + 语义色文字 ===================== */
QLabel[cssClass="badge"], QLabel[cssClass="badgeGreen"], QLabel[cssClass="badgeRed"],
QLabel[cssClass="badgeOrange"], QLabel[cssClass="badgeBlue"], QLabel[cssClass="badgeGray"],
QLabel[cssClass="badgeCyan"], QLabel[cssClass="statusLabel"] {
    border: none; border-radius: 6px; padding: 2px 9px;
    font-size: 12px; font-weight: 600;
    background: $chip; color: $ink2;
}
QLabel[cssClass="badgeGreen"], QLabel[cssClass="statusLabel"][tone="green"] {
    background: $success_tint; color: $success;
}
QLabel[cssClass="badgeRed"], QLabel[cssClass="statusLabel"][tone="red"] {
    background: $danger_tint; color: $danger;
}
QLabel[cssClass="badgeOrange"], QLabel[cssClass="statusLabel"][tone="orange"] {
    background: $warning_tint; color: $warning;
}
QLabel[cssClass="badgeBlue"] { background: $signal_soft; color: $signal; }
QLabel[cssClass="badgeGray"], QLabel[cssClass="badgeCyan"] { background: $chip; color: $ink2; }

QLabel[cssClass="tagNo"] {
    background: $tag_bg; color: $ink2;
    font-size: 12px; font-weight: 700;
    padding: 2px 10px 2px 7px; border: none; border-radius: 6px;
}
QLabel[cssClass="tagNo"][current="true"] { background: $signal_soft; color: $signal; }

/* ===================== 按钮 ===================== */
QPushButton {
    background: $chip; color: $ink;
    border: none; border-radius: 8px;
    padding: 8px 16px; font-size: 13px; font-weight: 600;
}
QPushButton:hover { background: $btn_hover; }
QPushButton:pressed { background: $btn_press; }
QPushButton:disabled { color: $disabled_text; background: $disabled_fill; }
QPushButton:focus { border: 1px solid $signal; }

QPushButton[primary="true"], QPushButton[cta="true"] {
    background: $signal; color: $on_signal; font-weight: 700;
}
QPushButton[cta="true"] {
    border-radius: 8px; font-size: 13px; font-weight: 700;
    padding: 0 20px; min-width: 104px; min-height: 36px;
}
QPushButton[primary="true"]:hover, QPushButton[cta="true"]:hover { background: $signal_hover; }
QPushButton[primary="true"]:pressed, QPushButton[cta="true"]:pressed { background: $signal_press; }
QPushButton[primary="true"]:disabled, QPushButton[cta="true"]:disabled {
    background: $disabled_fill; color: $disabled_text;
}
QPushButton[danger="true"] { background: $danger_tint; color: $danger; font-weight: 700; }
QPushButton[danger="true"]:hover { background: $danger_tint; }
QPushButton[small="true"] { padding: 5px 12px; font-size: 12px; }
QPushButton[actionButton="true"] { background: transparent; border: none; }

/* ===================== 右键菜单 ===================== */
QMenu {
    background: $panel; border: 1px solid $rule_strong; border-radius: 10px;
    padding: 6px; color: $ink; font-size: 13px;
}
QMenu::item { background: transparent; color: $ink; padding: 7px 20px; border-radius: 6px; }
QMenu::item:selected { background: $chip; color: $ink; }
QMenu::item:checked { color: $signal; font-weight: 700; }
QMenu::item:disabled { color: $ink3; }
QMenu::separator { height: 1px; background: $rule; margin: 4px 8px; }
QMenu::indicator { width: 12px; height: 12px; margin-left: 4px; }

/* ===================== 表单控件：去全框，焦点才显主色线 ===================== */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background: $input;
    border: 1px solid $rule_strong; border-radius: 8px;
    padding: 8px 12px; color: $ink;
    selection-background-color: $signal_tint; selection-color: $ink;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid $signal;
}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QSpinBox:disabled, QComboBox:disabled {
    background: $input_disabled; color: $input_disabled_text;
}
QLineEdit, QComboBox, QSpinBox { max-height: 34px; }
QComboBox { padding: 6px 12px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { width: 0; height: 0; }
QComboBox QAbstractItemView {
    background: $panel; border: 1px solid $rule_strong; border-radius: 10px;
    padding: 6px; outline: 0; color: $ink;
    selection-background-color: $signal_soft; selection-color: $ink;
}
QComboBox QAbstractItemView::item {
    min-height: 28px; padding: 3px 10px; border: none; border-radius: 6px;
    color: $ink; background: transparent;
}
QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {
    background: $signal_soft; color: $signal;
}
QSpinBox::up-button, QSpinBox::down-button { border: none; background: transparent; width: 18px; }
QSpinBox::up-arrow, QSpinBox::down-arrow { width: 0; height: 0; }

/* ===================== 复选框 ===================== */
QCheckBox { spacing: 9px; color: $ink; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid $rule_strong; background: $input;
}
QCheckBox::indicator:checked { background: $signal; border-color: $signal; }
QCheckBox::indicator:disabled { background: $input_disabled; border-color: $rule_strong; }

/* ===================== 进度条 ===================== */
QProgressBar {
    background: $progress_bg; border: none; border-radius: 999px;
    min-height: 6px; max-height: 6px; text-align: center; color: transparent;
}
QProgressBar::chunk { background: $signal; border-radius: 999px; }
QProgressBar[color="green"]::chunk { background: $success; }
QProgressBar[color="red"]::chunk { background: $danger; }
QProgressBar[color="orange"]::chunk { background: $warning; }

/* ===================== 日志 ===================== */
QTextEdit[cssClass="logPanel"], QTextEdit[cssClass="dlLogPanel"] {
    background: $log_bg; color: $log_text;
    border: 1px solid $log_border; border-radius: 10px;
    font-family: $mono_family; font-size: 12px; padding: 12px;
    selection-background-color: $signal_tint; selection-color: $ink;
}
QTextEdit[cssClass="dlLogPanel"] { color: $log_dl_text; }

/* ===================== 设置页 / 滚动区 ===================== */
QWidget#settingsHost, QWidget#settingsScrollPage, QScrollArea { background: $paper; }
QScrollArea { border: none; }
QScrollArea > QWidget > QWidget { background: $paper; }
QWidget#tagHost, QWidget#pageHost, QWidget#taskListHost { background: $paper; }

/* ===================== 标签页 ===================== */
QTabWidget::pane { border: 1px solid $rule; border-radius: 10px; background: $panel; top: -1px; }
QTabWidget QTabWidget, QTabWidget QTabWidget::pane,
QTabWidget QStackedWidget { background: $panel; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent; color: $ink2; border: none;
    padding: 8px 16px; margin-right: 2px; border-radius: 8px;
    font-size: 13px; font-weight: 600;
}
QTabBar::tab:hover { color: $ink; background: $chip; }
QTabBar::tab:selected { background: $signal_soft; color: $signal; font-weight: 700; }

/* ===================== 滚动条 ===================== */
QScrollBar:vertical { background: transparent; width: 10px; margin: 0px; }
QScrollBar::handle:vertical { background: $scroll_handle; border-radius: 999px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $scroll_handle_hover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0px; }
QScrollBar::handle:horizontal { background: $scroll_handle; border-radius: 999px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: $scroll_handle_hover; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

/* ===================== 任务记录 ===================== */
QLabel[cssClass="taskTitle"] { color: $ink; font-size: 13px; font-weight: 700; background: transparent; }
QLabel[cssClass="taskMeta"], QLabel[cssClass="taskDetail"] { color: $ink2; font-size: 12px; background: transparent; }
QLabel[cssClass="taskError"] { color: $danger; font-size: 12px; background: transparent; }
QFrame[cssClass="record"] { background: $panel; border: none; border-radius: 8px; }
QFrame[cssClass="record"]:hover { background: $surface_subtle; }

/* ===================== 杂项标签 ===================== */
QLabel[muted="true"] { color: $ink3; font-size: 12px; background: transparent; }
QLabel[sectionHeader="true"] { color: $ink; font-size: 13px; font-weight: 800; background: transparent; }
QLabel[cssClass="eyebrow"] { color: $ink3; font-size: 12px; font-weight: 600; background: transparent; }
QLabel[cssClass="emptyTitle"] { color: $ink; font-size: 18px; font-weight: 800; background: transparent; }
QLabel[cssClass="emptyHint"] { color: $ink2; font-size: 13px; background: transparent; }
QLabel[cssClass="alertText"] { color: $danger; font-size: 12px; background: transparent; }

/* ===================== 空状态：无边框，落在纯白底上，留白充足 ===================== */
QFrame#emptyState {
    background: $paper !important;
    border: none; border-radius: 0px;
}

/* ===================== 提示条 ===================== */
QFrame#ffmpegNotice {
    background: $warning_tint; border: none; border-left: 3px solid $warning; border-radius: 8px;
}
QLabel#ffmpegNoticeText { color: $ink; font-size: 13px; background: transparent; }
QLabel[cssClass="flag"] {
    background: $warning_tint; color: $warning;
    font-size: 12px; font-weight: 700;
    padding: 2px 8px; border: none; border-radius: 6px;
}

/* ===================== 媒体控制条 ===================== */
QWidget#mediaBar { background: $media_surface; }
HoverPreview { background: $media_surface; border: 1px solid $rule_strong; border-radius: 10px; }
QFrame#hoverCaption {
    background: $command_bar; border: none; border-bottom: 1px solid $media_groove; border-radius: 0px;
}
QLabel#hoverTitle { color: $media_text; font-size: 12px; background: transparent; }
QLabel#hoverBadge {
    background: $signal; color: $on_signal;
    padding: 2px 8px; font-size: 12px; font-weight: 700; border-radius: 6px;
}
QLabel#hoverDot { background: $signal; border: none; border-radius: 999px; }
QLabel#hoverMsg { color: $media_text; font-size: 13px; background: transparent; }
QVideoWidget#hoverVideo { background: $media_surface; }
QPushButton#mediaPlay {
    background: $signal; color: $on_signal;
    border: none; border-radius: 8px; padding: 6px 18px; font-size: 13px; font-weight: 700;
}
QPushButton#mediaPlay:hover { background: $signal_hover; }
QPushButton#mediaPlay:pressed { background: $signal_press; }
QPushButton#mediaPlay:disabled { background: $input_disabled; color: $disabled_text; }
QSlider#mediaSlider { background: transparent; }
QSlider#mediaSlider::groove:horizontal { height: 4px; background: $media_groove; border: none; border-radius: 999px; }
QSlider#mediaSlider::sub-page:horizontal { background: $signal; border-radius: 999px; }
QSlider#mediaSlider::add-page:horizontal { background: $media_groove; border-radius: 999px; }
QSlider#mediaSlider::handle:horizontal {
    width: 10px; height: 16px; margin: -6px 0px;
    background: $media_text; border: none; border-radius: 4px;
}
QSlider#mediaSlider::handle:horizontal:hover { background: $signal; }
QLabel#mediaTime { color: $media_text; font-size: 12px; background: transparent;
    font-family: $mono_family; min-width: 96px; }

/* ===================== 分段按钮 ===================== */
QPushButton[segment="true"] {
    background: transparent; color: $ink2;
    border: 1px solid $rule_strong; border-radius: 8px;
    padding: 6px 12px; font-size: 12px; font-weight: 600;
}
QPushButton[segment="true"]:hover { background: $chip; color: $ink; }
QPushButton[segment="true"]:checked {
    background: $signal_soft; color: $signal; border: 1px solid $signal_tint; font-weight: 700;
}

/* ===================== 统计数字 ===================== */
QLabel[cssClass="figureValue"] { color: $ink; font-size: 30px; font-weight: 800; background: transparent; }
QLabel[cssClass="figureValue"][marked="true"] { color: $signal; background: transparent; }
QLabel[cssClass="figureLabel"] { color: $ink2; font-size: 12px; background: transparent; }

QFrame[cssClass="plain"], QWidget[cssClass="plain"] { background: transparent; border: none; }
""")


def build_qss(theme: str = "light") -> str:
    """生成完整 QSS；保留参数以兼容既有调用点"""
    t = dict(THEMES["light"])
    t["font_family"] = FONT_FAMILY
    t["mono_family"] = MONO_FAMILY
    return _QSS_TEMPLATE.substitute(t)


def build_palette(theme: str = "light") -> QPalette:
    """构建白色 QPalette：兜底无 QSS 覆盖的原生控件"""
    t = THEMES["light"]
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: t["paper"],
        QPalette.ColorRole.Base: t["input"],
        QPalette.ColorRole.AlternateBase: t["panel"],
        QPalette.ColorRole.Button: t["chip"],
        QPalette.ColorRole.Text: t["ink"],
        QPalette.ColorRole.WindowText: t["ink"],
        QPalette.ColorRole.ButtonText: t["ink"],
        QPalette.ColorRole.BrightText: t["ink"],
        QPalette.ColorRole.ToolTipBase: t["tooltip_bg"],
        QPalette.ColorRole.ToolTipText: t["tooltip_text"],
        QPalette.ColorRole.PlaceholderText: t["ink3"],
        QPalette.ColorRole.Link: t["trace"],
        QPalette.ColorRole.Highlight: t["chrome_active"],
        QPalette.ColorRole.HighlightedText: t["ink"],
        QPalette.ColorRole.Light: t["rule_strong"],
        QPalette.ColorRole.Midlight: t["rule"],
        QPalette.ColorRole.Mid: t["rule"],
        QPalette.ColorRole.Dark: t["ink"],
        QPalette.ColorRole.Shadow: t["ink"],
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    return pal


# =====================================================================
# 运行时状态：当前激活主题 + C 兼容视图
# =====================================================================

_active_theme = "light"


def _tokens() -> dict:
    return THEME_WHITE


class _ThemeColors(dict):
    """C 的兼容视图：业务代码按需读取纯白主题令牌。"""

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
    return False


# =====================================================================
# 字体：跟随系统默认（不随包携带任何字体文件），中文落系统中文字体
def apply_app_font(app: QApplication) -> None:
    """应用字体：跟随系统默认，仅统一字号与抗锯齿策略"""
    font = QApplication.font()
    font.setPointSizeF(9.5)
    try:
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    except Exception:
        pass
    app.setFont(font)
# 主题模式：当前仅提供纯白模式；保留旧常量兼容既有调用点
# =====================================================================

MODE_SYSTEM = "system"
MODE_LIGHT = "light"
MODE_DARK = "dark"
MODES = (MODE_LIGHT,)

MODE_LABELS = {
    MODE_LIGHT: "纯白模式",
}


def _prefs_path():
    from pathlib import Path

    from system_info import system_info

    return system_info.get_config_dir() / "ui_prefs.json"


def load_mode() -> str:
    """当前只有一种纯白主题"""
    return MODE_LIGHT


def save_mode(mode: str) -> None:
    """纯白主题无需保存偏好"""
    return


def system_prefers_dark() -> bool:
    """纯白主题不跟随系统深色偏好"""
    return False


def reduce_motion() -> bool:
    """系统「减少动态效果」打开时返回 True：所有动效时长归零，界面静止"""
    app = QApplication.instance()
    if app is None:
        return False
    try:
        return not app.styleHints().shouldAnimate()
    except Exception:
        return False


# =====================================================================
# 主题管理器：应用/切换主题 + 系统主题跟随
# =====================================================================

class ThemeManager(QObject):
    """主题管理器（单例）：应用纯白主题并刷新自绘控件"""

    theme_changed = Signal(str)  # 固定为 light

    def __init__(self):
        super().__init__()
        self._mode = MODE_LIGHT
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
        self._apply("light")
        return "light"

    def _apply(self, theme: str = "light") -> None:
        global _active_theme
        changed = "light" != _active_theme
        _active_theme = "light"
        app = QApplication.instance()
        if app is not None:
            apply_app_font(app)
            app.setStyleSheet(build_qss("light"))
            app.setPalette(build_palette("light"))
            # 通知已有控件重放内联动态颜色
            for widget in app.allWidgets():
                try:
                    refresh = getattr(widget, "refresh_theme", None)
                    if callable(refresh):
                        refresh()
                except Exception:
                    pass
        if changed:
            self.theme_changed.emit("light")

    def sync_with_system(self) -> None:
        """系统主题跟随：colorSchemeChanged 信号或轮询兜底触发"""
        if self._mode != MODE_SYSTEM:
            return
        return

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
