"""
通用 Qt 界面部件

保留页面已使用的工厂函数与控件接口；颜色统一从 theme.C 读取，
避免业务代码硬编码色值。
"""

from PySide6.QtCore import (
    QEvent, QObject, QPointF, QRect, QSize, Qt,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF,
)
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

import theme
from theme import C


# =====================================================================
# 字体辅助函数
# =====================================================================


def styled_font(base: QFont, weight: int = None,
                tracking: float = 0.0) -> QFont:
    """设置界面标签的字重与小字距"""
    font = QFont(base)
    try:
        if weight is not None:
            font.setWeight(QFont.Weight(int(weight)))
    except Exception:
        pass
    if tracking:
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + tracking)
    return font


def set_styled(widget: QWidget, weight: int = None,
               tracking: float = 0.0) -> QWidget:
    widget.setFont(styled_font(widget.font(), weight, tracking))
    return widget


def inline(widget: QWidget, align: Qt.AlignmentFlag = None) -> QWidget:
    """行内小块：不跟着整行高度拉伸，垂直居中"""
    widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    widget.setAlignment(align or (Qt.AlignmentFlag.AlignVCenter
                                  | Qt.AlignmentFlag.AlignLeft))
    return widget


def hug(label: QLabel, text: str = None) -> QLabel:
    """让标签只包住文字；text=None 恢复成随容器伸缩"""
    if text is None:
        label.setMaximumWidth(16777215)
        return label
    advance = QFontMetrics(label.font()).horizontalAdvance(text)
    label.setMaximumWidth(min(advance + 20, 16777215))
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label


# =====================================================================
# 文字部件
# =====================================================================


def eyebrow(text: str, parent=None) -> QLabel:
    """英文小标题"""
    label = QLabel(f"// {text.upper()}", parent)
    label.setProperty("cssClass", "eyebrow")
    return set_styled(label, QFont.Weight.DemiBold, 14)


def title_pair(cn: str, en: str = "", parent=None) -> QWidget:
    """中英成对标题：英文小字在上，中文粗体在下"""
    box = QFrame(parent)
    box.setProperty("cssClass", "plain")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(1)
    if en:
        lay.addWidget(eyebrow(en, box))
    title = QLabel(cn, box)
    title.setProperty("cssClass", "sectionTitle")
    lay.addWidget(title)
    return box


def field(text: str, parent=None) -> QLabel:
    """编号 / 日期 / 计数等元数据标签"""
    label = QLabel(text, parent)
    label.setProperty("cssClass", "field")
    return set_styled(label)


def field_join(*parts, sep: str = "│") -> str:
    return f" {sep} ".join(str(p) for p in parts if str(p).strip())


def stamp(value, with_time: bool = False) -> str:
    """把时间格式化为 2026.10.17 / 10/13 12:24"""
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y.%m.%d %H:%M" if with_time else "%Y.%m.%d")
    return str(value)


def number_tag(text: str, current: bool = False, parent=None) -> QLabel:
    """编号标签：浅灰底，当前项加粗"""
    label = QLabel(text, parent)
    label.setProperty("cssClass", "tagNo")
    label.setProperty("current", current)
    set_styled(label, QFont.Weight.Bold)
    return inline(label)


def flag(text: str = "注意", parent=None) -> QLabel:
    """提示条前面的状态标签"""
    label = QLabel(text, parent)
    label.setProperty("cssClass", "flag")
    return inline(set_styled(label, QFont.Weight.Bold))


def state_box(text: str, kind: str = "solid", parent=None) -> QLabel:
    """状态标签"""
    css = {"solid": "badgeGreen", "backstage": "badgeGray",
           "alert": "badgeOrange", "danger": "badgeRed"}[kind]
    label = QLabel(text, parent)
    label.setProperty("cssClass", css)
    return inline(set_styled(label))


def set_css_class(widget: QWidget, css_class: str) -> None:
    """切换 QSS 属性后必须 unpolish/polish，否则样式不生效"""
    if widget.property("cssClass") == css_class:
        return
    widget.setProperty("cssClass", css_class)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


# =====================================================================
# 背景容器
# =====================================================================


class Backdrop(QWidget):
    """纯白页面底"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentRoot")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(C["paper"]))

    def refresh_theme(self) -> None:
        self.update()


# =====================================================================
# 面板与记录行：外观由全局 QSS 控制
# =====================================================================


def attach_panel(frame: QFrame, side: str = "left") -> QFrame:
    """兼容旧调用点；面板外观由全局 QSS 控制"""
    return frame


def attach_record(frame: QFrame, layout=None) -> QFrame:
    """设置记录行 QSS 类名；悬停底色由全局 QSS 控制"""
    frame.setProperty("cssClass", "record")
    return frame


# =====================================================================
# 普通按钮
# =====================================================================


class ActionButton(QPushButton):
    """普通按钮：浅灰底、深灰字，主按钮用蓝色"""

    def __init__(self, text: str = "", kind: str = "secondary",
                 small: bool = False, parent=None):
        super().__init__(text, parent)
        self._kind = kind
        self._small = small
        # 全局 QSS 让默认底色交给自绘
        self.setProperty("actionButton", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self.update()

    # ------------------------------------------------------------ 配色

    def _colors(self) -> tuple[str, str, str]:
        """(静止底色, 文字色, 兼容占位)"""
        if not self.isEnabled():
            return C["disabled_fill"], C["disabled_text"], C["disabled_fill"]
        if self._kind == "danger":
            return C["danger_tint"], C["danger"], C["danger_tint"]
        if self._kind in ("primary", "cta"):
            return C["signal"], C["on_signal"], C["signal_hover"]
        if self._kind == "ghost":
            return "transparent", C["ink"], C["chip"]
        return C["chip"], C["ink"], C["chip_hover"]

    # ------------------------------------------------------------ 绘制

    def paintEvent(self, event) -> None:
        fill, fg, _hover = self._colors()
        rect = self.rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        if fill != "transparent":
            # 极浅实色短投影：扁平设计里的层次，不用模糊阴影
            shadow = rect.adjusted(0, 2, 0, 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(C["shadow_direct"]))
            painter.drawRoundedRect(shadow, 8, 8)
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(rect.adjusted(0, 0, 0, -2), 8, 8)

        font = self._text_font()
        painter.setFont(font)
        align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        pad = self._left_pad()
        box = QRect(pad, 0, rect.width() - pad - 8, rect.height() - 2)
        painter.setPen(QColor(fg))
        painter.drawText(box, align, self.text())

        if self.hasFocus():
            painter.setPen(QPen(QColor(C["signal"]), 1))
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -3), 8, 8)

    def _text_font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(9.5)
        font.setWeight(QFont.Weight.Bold if self._kind in ("cta", "primary", "danger")
                       else QFont.Weight.DemiBold)
        return font

    def _left_pad(self) -> int:
        return 10 if self._small else (16 if self._kind == "cta" else 12)

    def sizeHint(self) -> QSize:
        font = self._text_font()
        advance = QFontMetrics(font).horizontalAdvance(self.text() or " ")
        height = 28 if self._small else (36 if self._kind == "cta" else 32)
        width = advance + self._left_pad() + 14
        if self._kind == "cta":
            width = max(width, 104)
        return QSize(width, height + 2)

    def refresh_theme(self) -> None:
        self.update()


def make_button(text: str, kind: str = "secondary", small: bool = False,
                parent=None) -> ActionButton:
    return ActionButton(text, kind, small, parent)


# =====================================================================
# 下拉指示
# =====================================================================


class _ComboInstallFilter(QObject):
    """为下拉框补一枚 ▾"""

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.Show and isinstance(obj, QComboBox):
            if obj.property("comboArrow") is None:
                arrow = _ComboArrow(obj)
                obj.setProperty("comboArrow", arrow)
                arrow.move_to(obj)
        elif kind == QEvent.Type.Resize and isinstance(obj, QComboBox):
            arrow = obj.property("comboArrow")
            if arrow is not None:
                arrow.move_to(obj)
        return False


class _ComboArrow(QWidget):
    """下拉框右侧的 ▾（禁用时转淡）"""

    WIDTH = 10
    HEIGHT = 6

    def __init__(self, combo):
        super().__init__(combo)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFixedSize(self.WIDTH, self.HEIGHT)

    def move_to(self, combo) -> None:
        self.move(combo.width() - 22 + (22 - self.WIDTH) // 2,
                  (combo.height() - self.HEIGHT) // 2)
        self.raise_()
        self.show()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.EnabledChange:
            self.update()
        super().changeEvent(event)

    def paintEvent(self, event) -> None:
        color = QColor(C["ink"] if self.isEnabled() else C["input_disabled_text"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([
            QPointF(0, 0),
            QPointF(self.WIDTH, 0),
            QPointF(self.WIDTH / 2, self.HEIGHT),
        ]))


_COMBO_FILTER: _ComboInstallFilter | None = None


def install_combo_arrows(app) -> None:
    """安装下拉指示事件过滤器"""
    global _COMBO_FILTER
    if _COMBO_FILTER is not None:
        return
    _COMBO_FILTER = _ComboInstallFilter(app)
    app.installEventFilter(_COMBO_FILTER)
