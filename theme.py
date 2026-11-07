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
    # 白色表面与深灰文字
    "paper": "#FFFFFF",
    "panel": "#FFFFFF",
    "ink": "#202124",
    "ink2": "#5F6368",
    "ink3": "#9AA0A6",
    "rule": "#E8EAED",
    "rule_strong": "#DADCE0",
    "chip": "#F5F6F7",
    "chip_hover": "#ECEEF1",
    "chip_press": "#E3E6EA",
    # 蓝色仅用于焦点、选中文本与进行中状态
    "signal": "#1A73E8",
    "on_signal": "#FFFFFF",
    "mark": "#1A73E8",
    "mark_argb": "#00000000",
    "trace": "#1A73E8",
    "tag_bg": "#F1F3F4",
    "tag_fg": "#202124",
    "danger": "#D93025",
    "danger_tint": "#FCE8E6",
    "scrim": "#20212420",
    # 兼容旧媒体/命令栏键名：统一白色
    "command_bar": "#FFFFFF",
    "command_bar_text": "#202124",
    "command_bar_sub": "#5F6368",
    "command_bar_hover": "#F1F3F4",
    "command_bar_press": "#E8EAED",
    "command_bar_rail": "#E8EAED",
    "chrome": "#FFFFFF",
    "chrome_text": "#202124",
    "chrome_sub": "#5F6368",
    "chrome_hover": "#F1F3F4",
    "chrome_active": "#E8EAED",
    "chrome_press": "#DADCE0",
    "chrome_line": "#E8EAED",
    # 输入 / 控件
    "input": "#FFFFFF",
    "input_disabled": "#F5F6F7",
    "input_disabled_text": "#9AA0A6",
    "btn_hover": "#F1F3F4",
    "btn_press": "#E8EAED",
    "disabled_fill": "#F5F6F7",
    "disabled_text": "#9AA0A6",
    "tooltip_bg": "#FFFFFF",
    "tooltip_text": "#202124",
    "tooltip_border": "#DADCE0",
    "scroll_handle": "#DADCE0",
    "scroll_handle_hover": "#9AA0A6",
    "progress_bg": "#E8EAED",
    "media_surface": "#FFFFFF",
    "media_groove": "#E8EAED",
    "media_text": "#202124",
    "log_bg": "#FFFFFF",
    "log_border": "#E8EAED",
    "log_text": "#202124",
    "log_dl_text": "#5F6368",
}

# 旧键名 → 纯白主题落点
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
    "nav_checked_text": "chrome_text",
    "green": "ink",
    "green_dark": "ink",
    "green_bg": "chip",
    "orange": "ink2",
    "orange_dark": "ink",
    "orange_bg": "chip",
    "red": "danger",
    "red_dark": "danger",
    "red_bg": "danger_tint",
    "blue": "trace",
    "blue_dark": "ink",
    "blue_bg": "chip",
    "cyan": "ink2",
    "cyan_dark": "ink",
    "cyan_bg": "chip",
    "gray": "ink2",
    "gray_dark": "ink2",
    "gray_bg": "chip",
    "gold": "ink2",
    "gold_dark": "ink",
    "gold_light": "chip",
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
/* ========== 全局 ========== */
* {
    font-family: $font_family;
    font-size: 13px;
    color: $ink;
}
QMainWindow, QWidget, QFrame, QScrollArea, QStackedWidget {
    background: $paper;
}
QLabel { background: transparent; }
QToolTip {
    background: $tooltip_bg; color: $tooltip_text;
    border: 1px solid $tooltip_border; border-radius: 0px; padding: 5px 9px;
}

/* ========== chrome（标题栏 + 侧边导航） ========== */
QWidget#titleBar { background: $chrome; }
QWidget#titleBarLeft { background: $chrome; }
QWidget#titleBarRight { background: $chrome; }
QLabel#titlebarTitle { color: $chrome_text; font-size: 12px; font-weight: 600; background: transparent; }
QPushButton[captionBtn="true"] { background: transparent; border: none; border-radius: 0px; padding: 0; }

QFrame#sidebar {
    background: $chrome;
    border: none;
    border-right: 1px solid $chrome_line;
}
QLabel#sidebarTitle { color: $chrome_text; font-size: 13px; font-weight: 700; background: transparent; }
QLabel#sidebarSub { color: $chrome_sub; font-size: 10px; background: transparent; }
QLabel#sidebarVersion { color: $chrome_sub; font-size: 10px; background: transparent; }
QFrame#sidebarDivider { background: $chrome_line; border: none; max-height: 1px; margin-left: 12px; }

/* 导航项：当前项一格圆角浅底；展开与收起共用固定行高和图标盒 */
QPushButton[nav="true"] {
    background: transparent;
    color: $chrome_text;
    border: none;
    border-radius: 8px;
    padding: 0 10px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
}
QPushButton[nav="true"]:hover { background: $chrome_hover; }
QPushButton[nav="true"]:pressed { background: $chrome_press; }
QPushButton[nav="true"]:checked { background: $chrome_active; font-weight: 700; }
QPushButton[nav="true"][collapsed="true"] { padding: 0; text-align: center; }
QPushButton[nav="true"][collapsed="true"] { border-radius: 8px; }
QPushButton#sidebarToggle {
    background: transparent; color: $chrome_text; border: none; border-radius: 8px;
    margin-left: 4px;
}
QPushButton#sidebarToggle:hover { background: $chrome_hover; }
QPushButton#sidebarToggle:pressed { background: $chrome_press; }

/* ========== 页头 ========== */
QLabel#pageEyebrow { font-size: 10px; font-weight: 600; color: $ink2; background: transparent; }
QLabel#pageTitle { font-size: 26px; font-weight: 800; color: $ink; background: transparent; }
QLabel#pageSubtitle { font-size: 12px; color: $ink2; background: transparent; }
QLabel#statusPill {
    border-radius: 0px;
    border: 1px solid $ink;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
    background: $panel;
    color: $ink;
}
QLabel#statusPill[cssClass="badgeGreen"] { color: $ink; background: $panel; }
QLabel#statusPill[cssClass="badgeRed"] { border: 1px solid $danger; color: $danger; background: $panel; }
QLabel#statusPill[cssClass="badgeBlue"] { color: $ink; background: $panel; }
QLabel#statusPill[cssClass="badgeOrange"] { border: 1px solid $rule_strong; background: $chip; color: $ink; font-weight: 700; }

/* ========== 面板（白色表面 + 1px 浅灰细线） ========== */
QFrame[cssClass="card"] {
    background: $panel;
    border: 1px solid $rule;
    border-radius: 0px;
}
QFrame[cssClass="card"]:hover { border-color: $rule_strong; }

QFrame[cssClass="sectionCard"] {
    background: $panel;
    border: 1px solid $rule;
    border-radius: 0px;
}

QLabel[cssClass="cardTitle"] { color: $ink2; font-size: 10px; background: transparent; }
QLabel[cssClass="cardValue"] { color: $ink; font-size: 30px; font-weight: 800; background: transparent; }
QLabel[cssClass="cardValueSmall"] { color: $ink; font-size: 17px; font-weight: 700; background: transparent; }
QLabel[cssClass="cardSub"] { color: $ink3; font-size: 11px; background: transparent; }

/* 面板数值色调：正文深灰，删除相关用红色文字 */
QLabel[cssClass="cardValue"][tone="orange"] { color: $ink; background: transparent; }
QLabel[cssClass="cardValue"][tone="red"] { color: $danger; }
QLabel[cssClass="cardValue"][tone="brand"] { color: $ink; font-weight: 800; }
QLabel[cssClass="cardValueSmall"][tone="orange"] { color: $ink; background: transparent; }
QLabel[cssClass="cardValueSmall"][tone="red"] { color: $danger; }

/* 编号 / 日期 / 计数：等宽数字 */
QLabel[cssClass="hashLabel"], QLabel[cssClass="field"] {
    font-family: $mono_family;
    font-size: 11px;
    color: $ink2;
    background: transparent;
}

QLabel[cssClass="configOk"] { color: $ink; font-size: 11px; background: transparent; }
QLabel[cssClass="configError"] { color: $danger; font-size: 11px; background: transparent; }

QLabel[cssClass="progressSpeed"] { color: $ink2; font-size: 11px; background: transparent; }
QLabel[cssClass="progressEta"] { color: $ink2; font-size: 11px; background: transparent; }
QLabel[cssClass="progressSuccess"] { color: $ink; font-size: 11px; background: transparent; }
QLabel[cssClass="progressError"] { color: $danger; font-size: 11px; background: transparent; }

QLabel[cssClass="sectionTitle"] { color: $ink; font-size: 15px; font-weight: 800; background: transparent; }
QLabel[cssClass="sectionHint"] { color: $ink2; font-size: 11px; background: transparent; }
QFrame[cssClass="divider"] { background: $rule; max-height: 1px; border: none; }
QLabel[cssClass="formLabel"] { color: $ink; font-size: 12px; font-weight: 600; background: transparent; }

/* ========== 标签 / 状态 ========== */
QLabel[cssClass="badge"], QLabel[cssClass="badgeGreen"], QLabel[cssClass="badgeRed"],
QLabel[cssClass="badgeOrange"], QLabel[cssClass="badgeBlue"], QLabel[cssClass="badgeGray"],
QLabel[cssClass="badgeCyan"], QLabel[cssClass="statusLabel"] {
    border-radius: 0px;
    padding: 1px 7px;
    font-size: 10px;
    font-weight: 600;
    background: transparent;
    color: $ink;
    border: 1px solid $ink;
}
QLabel[cssClass="badgeGreen"] { color: $ink; border: 1px solid $ink; }
QLabel[cssClass="badgeRed"] { color: $danger; border: 1px solid $danger; }
QLabel[cssClass="badgeOrange"] { color: $ink2; background: $chip; border: 1px solid $rule_strong; font-weight: 700; }
QLabel[cssClass="badgeBlue"] { color: $ink; border: 1px solid $ink; }
QLabel[cssClass="badgeGray"] { color: $ink2; border: 1px dashed $ink2; }
QLabel[cssClass="badgeCyan"] { color: $ink2; border: 1px dashed $ink2; }

/* 编号标签：浅灰底深灰字 */
QLabel[cssClass="tagNo"] {
    background: $tag_bg; color: $tag_fg;
    font-size: 11px; font-weight: 700;
    padding: 2px 10px 2px 7px;
    border: none; border-radius: 0px;
}
QLabel[cssClass="tagNo"][current="true"] { background: $chip; color: $ink; }

QLabel[cssClass="statusLabel"][tone="green"] { color: $ink; border: 1px solid $ink; }
QLabel[cssClass="statusLabel"][tone="orange"] { color: $ink2; background: $chip; border: 1px solid $rule_strong; font-weight: 700; }
QLabel[cssClass="statusLabel"][tone="red"] { color: $danger; border: 1px solid $danger; }

/* ========== 按钮 ========== */
QPushButton {
    background: $chip;
    color: $ink;
    border: none;
    border-radius: 0px;
    padding: 8px 18px 8px 14px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton:hover { background: $btn_hover; }
QPushButton:pressed { background: $btn_press; }
QPushButton:disabled { color: $disabled_text; background: $disabled_fill; }

QPushButton[primary="true"] {
    background: $signal;
    color: $on_signal;
    font-weight: 700;
}
QPushButton[primary="true"]:hover { background: $signal; color: $on_signal; }
QPushButton[primary="true"]:pressed { background: $signal; color: $on_signal; }
QPushButton[primary="true"]:disabled { background: $disabled_fill; color: $disabled_text; }

/* 主行动按钮（CTA）：更大更醒目，一个动作区只放一个 */
QPushButton[cta="true"] {
    background: $signal;
    color: $on_signal;
    border: none;
    border-radius: 0px;
    font-size: 13px;
    font-weight: 800;
    padding: 0 26px 0 18px;
    min-width: 112px;
    min-height: 38px;
}
QPushButton[cta="true"]:hover { background: $signal; color: $on_signal; }
QPushButton[cta="true"]:pressed { background: $signal; color: $on_signal; }
QPushButton[cta="true"]:disabled { background: $disabled_fill; color: $disabled_text; }

/* 删除：红色文字，指向时用极浅红底 */
QPushButton[danger="true"] { background: $chip; color: $danger; font-weight: 700; }
QPushButton[danger="true"]:hover { background: $danger_tint; color: $danger; }
QPushButton[danger="true"]:pressed { background: $danger_tint; color: $danger; }

QPushButton[small="true"] { padding: 5px 13px 5px 10px; font-size: 11px; }

/* 自绘按钮：默认底让位给 ui_widgets.py */
QPushButton[actionButton="true"] { background: transparent; border: none; }

/* ========== 右键菜单 ==========
   注意：QMenu 是独立的弹出窗口，一旦背景没被画上就露出未初始化的黑色表面
   （控件级 setStyleSheet("background: transparent;") 会级联到弹出的 QMenu，
   把这里的背景覆盖掉）。因此 QMenu 与 QMenu::item 都必须显式给出背景与前景。 */
QMenu {
    background: $panel;
    border: 1px solid $ink;
    border-radius: 0px;
    padding: 4px;
    color: $ink;
    font-size: 12px;
}
QMenu::item {
    background: transparent;
    color: $ink;
    padding: 6px 22px;
    border-radius: 0px;
}
QMenu::item:selected { background: $chip; color: $ink; }
QMenu::item:checked { color: $ink; font-weight: 700; }
QMenu::item:disabled { color: $ink3; }
QMenu::separator { height: 1px; background: $rule; margin: 4px 8px; }
QMenu::indicator { width: 12px; height: 12px; margin-left: 4px; }

/* ========== 输入控件 ========== */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background: $input;
    border: 1px solid $rule_strong;
    border-radius: 0px;
    padding: 7px 10px;
    color: $ink;
    selection-background-color: #D3E3FD;
    selection-color: $ink;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid $trace;
}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
    background: $input_disabled; color: $input_disabled_text;
}
/* 单行输入不跟着行高拉伸：保持固定厚度，记录行不会撑出空隙 */
QLineEdit, QComboBox, QSpinBox { max-height: 30px; }
QComboBox { padding: 4px 10px; }
QComboBox::drop-down { border: none; width: 22px; }
/* 下拉指示由 ui_widgets.py 绘制 */
QComboBox::down-arrow { width: 0; height: 0; }
QComboBox QAbstractItemView {
    background: $panel;
    border: 1px solid $ink;
    border-radius: 0px;
    padding: 4px;
    outline: 0;
    color: $ink;
    selection-background-color: #D3E3FD;
    selection-color: $ink;
}
QComboBox QAbstractItemView::item {
    min-height: 26px;
    padding: 2px 9px;
    border: none;
    border-radius: 0px;
    color: $ink;
    background: transparent;
}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {
    background: $signal;
    color: $on_signal;
}
QSpinBox::up-button, QSpinBox::down-button {
    border: none; background: transparent; width: 18px;
}
QSpinBox::up-arrow, QSpinBox::down-arrow { width: 0; height: 0; }

/* ========== 复选框 ========== */
QCheckBox {
    spacing: 9px;
    color: $ink;
}
QCheckBox::indicator {
    width: 16px; height: 16px;
    border-radius: 0px;
    border: 1px solid $ink;
    background: $input;
}
QCheckBox::indicator:checked {
    background: $signal;
    border-color: $ink;
}
QCheckBox::indicator:disabled { background: $input_disabled; border-color: $rule_strong; }

/* ========== 进度条 ========== */
QProgressBar {
    background: $progress_bg;
    border: none;
    border-radius: 0px;
    min-height: 6px;
    max-height: 6px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: $trace; border-radius: 0px; }
QProgressBar[color="green"]::chunk { background: $trace; }
QProgressBar[color="red"]::chunk { background: $danger; }
QProgressBar[color="orange"]::chunk { background: $signal; }

/* ========== 日志面板（代码只归等宽） ========== */
QTextEdit[cssClass="logPanel"] {
    background: $log_bg;
    color: $log_text;
    border: 1px solid $log_border;
    border-radius: 0px;
    font-family: $mono_family;
    font-size: 11px;
    padding: 10px;
    selection-background-color: #D3E3FD;
    selection-color: $ink;
}
QTextEdit[cssClass="dlLogPanel"] {
    background: $panel;
    color: $log_dl_text;
    border: 1px solid $rule;
    border-radius: 0px;
    font-family: $mono_family;
    font-size: 11px;
    padding: 10px;
    selection-background-color: #D3E3FD;
    selection-color: $ink;
}

/* ========== 设置分组 ========== */
QWidget#settingsHost { background: $paper; }
/* 设置页滚动内容页：显式主题底色，杜绝视口调色板回退发黑 */
QWidget#settingsScrollPage { background: $paper; }
QScrollArea { background: $paper; border: none; }
QScrollArea > QWidget > QWidget { background: $paper; }

/* ========== 透明容器 ==========
   统一在全局 QSS 里按 objectName 上色，禁止在业务代码里用
   setStyleSheet("background: transparent;") —— 裸声明的控件级样式表会级联到
   该控件下的所有子控件（包括 QMenu / QToolTip 这类弹出窗口），
   把弹出层背景覆盖成透明，最终露出未初始化表面的纯黑底。 */
QWidget#tagHost,
QWidget#pageHost,
QWidget#taskListHost { background: $paper; }

/* ========== 标签页 ========== */
QTabWidget::pane {
    border: 1px solid $rule;
    border-radius: 0px;
    background: $panel;
    top: -1px;
}
QTabWidget QTabWidget,
QTabWidget QTabWidget::pane,
QTabWidget QStackedWidget { background: $panel; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent;
    color: $ink2;
    border: none;
    padding: 8px 16px;
    margin-right: 2px;
    border-radius: 0px;
    font-size: 12px;
    font-weight: 600;
}
QTabBar::tab:hover { color: $ink; background: $chip; }
QTabBar::tab:selected { background: $chrome_active; color: $ink; font-weight: 700; }

/* ========== 滚动条 ========== */
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 0px;
}
QScrollBar::handle:vertical {
    background: $scroll_handle; border-radius: 0px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: $scroll_handle_hover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 0px;
}
QScrollBar::handle:horizontal {
    background: $scroll_handle; border-radius: 0px; min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: $scroll_handle_hover; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

/* ========== 记录行 ========== */
QLabel[cssClass="taskTitle"] { color: $ink; font-size: 13px; font-weight: 700; background: transparent; }
QLabel[cssClass="taskMeta"], QLabel[cssClass="taskDetail"] { color: $ink2; font-size: 11px; background: transparent; }
/* 失败：用红色文字与一句完整的话说明原因 */
QLabel[cssClass="taskError"] { color: $danger; font-size: 11px; background: transparent; }
QFrame[cssClass="record"] { background: $panel; border: none; }
QFrame[cssClass="record"]:hover { background: $chip; }

/* ========== 其他 ========== */
QLabel[muted="true"] { color: $ink3; font-size: 11px; background: transparent; }
QLabel[sectionHeader="true"] { color: $ink; font-size: 13px; font-weight: 800; background: transparent; }
QLabel[cssClass="eyebrow"] { color: $ink2; font-size: 10px; font-weight: 600; background: transparent; }
QLabel[cssClass="emptyTitle"] { color: $ink; font-size: 15px; font-weight: 800; background: transparent; }
QLabel[cssClass="emptyHint"] { color: $ink2; font-size: 12px; background: transparent; }

/* 出错与提醒：红色文字，白色底 */
QLabel[cssClass="alertText"] { color: $danger; font-size: 11px; background: transparent; }

/* ========== 空状态（纯白底，文字不受纹理干扰） ========== */
QFrame#emptyState {
    background: #FFFFFF !important;
    border: 1px solid $rule;
    border-radius: 0px;
}

/* ========== 提示条 ========== */
QFrame#ffmpegNotice {
    background: $panel;
    border: 1px solid $ink;
    border-radius: 0px;
}
QLabel#ffmpegNoticeText { color: $ink; font-size: 12px; background: transparent; }
QLabel[cssClass="flag"] {
    background: $chip; color: $ink2;
    font-size: 10px; font-weight: 700;
    padding: 1px 6px; border: none; border-radius: 0px;
}

/* ========== 媒体控制条 ========== */
QWidget#mediaBar { background: $media_surface; }

/* ========== 悬停低清小窗 ========== */
HoverPreview { background: $media_surface; border: 1px solid $media_groove; }
QFrame#hoverCaption {
    background: $command_bar; border: none;
    border-bottom: 1px solid $media_groove; border-radius: 0px;
}
QLabel#hoverTitle { color: $media_text; font-size: 11px; background: transparent; }
QLabel#hoverBadge {
    background: $signal; color: $on_signal;
    padding: 1px 7px; font-size: 10px; font-weight: 700; border-radius: 0px;
}
QLabel#hoverDot { background: $signal; border: none; border-radius: 0px; }
QLabel#hoverMsg { color: $media_text; font-size: 12px; background: transparent; }
QVideoWidget#hoverVideo { background: $media_surface; }
QPushButton#mediaPlay {
    background: $signal; color: $on_signal;
    border: none; border-radius: 0px;
    padding: 5px 18px; font-size: 12px; font-weight: 700;
}
/* 媒体按钮三态使用白色表面与浅灰状态底 */
QPushButton#mediaPlay:hover { background: $chip_hover; color: $ink; }
QPushButton#mediaPlay:pressed { background: $chip_press; color: $ink; }
QPushButton#mediaPlay:disabled { background: $input_disabled; color: $disabled_text; }
/* 进度轨道：已播=蓝色，未播=浅灰 */
QSlider#mediaSlider { background: transparent; }
QSlider#mediaSlider::groove:horizontal {
    height: 4px; background: $media_groove; border: none; border-radius: 0px;
}
QSlider#mediaSlider::sub-page:horizontal { background: $signal; border-radius: 0px; }
QSlider#mediaSlider::add-page:horizontal { background: $media_groove; border-radius: 0px; }
QSlider#mediaSlider::handle:horizontal {
    width: 10px; height: 16px; margin: -6px 0px;
    background: $media_text; border: none; border-radius: 0px;
}
QSlider#mediaSlider::handle:horizontal:hover { background: $signal; }
QLabel#mediaTime {
    color: $media_text; font-size: 11px; background: transparent;
    font-family: $mono_family; min-width: 96px;
}

/* ========== 模式切换 ========== */
QPushButton[segment="true"] {
    background: transparent; color: $ink2;
    border: 1px solid $rule_strong; border-radius: 0px;
    padding: 5px 12px; font-size: 11px; font-weight: 600;
}
QPushButton[segment="true"]:hover { background: $chip; color: $ink; }
QPushButton[segment="true"]:checked {
    background: $chrome_active; color: $ink; border: 1px solid $rule_strong; font-weight: 700;
}

/* ========== 看板大数字 ========== */
QLabel[cssClass="figureValue"] { color: $ink; font-size: 34px; font-weight: 800; background: transparent; }
QLabel[cssClass="figureValue"][marked="true"] { color: $ink; background: transparent; }
QLabel[cssClass="figureLabel"] { color: $ink2; font-size: 11px; background: transparent; }

/* 无边框的普通容器 */
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
