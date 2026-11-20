# -*- coding: utf-8 -*-
"""
Shared QStyledItemDelegate for QComboBox popups with ValueMap support.
Renders the raw stored value in regular font (left) and the mapped alias in italic muted font (right).
"""

from qgis.PyQt.QtCore import Qt, QSize, QRect
from qgis.PyQt.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QApplication, QStyle
from qgis.PyQt.QtGui import QFont, QColor, QPalette

_USER_ROLE = getattr(Qt.ItemDataRole, "UserRole", getattr(Qt, "UserRole", 256))
ROLE_RAW_HINT = _USER_ROLE + 1


class ValueMapComboDelegate(QStyledItemDelegate):
    """在下拉列表中用『正常字体（存储真值）』+『斜体淡灰（映射别名）』清晰区分真假值"""

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        raw_hint = index.data(ROLE_RAW_HINT)
        if not raw_hint:
            return base
        fm = option.fontMetrics
        text = str(index.data() or "")
        hint_str = str(raw_hint)
        adv = fm.horizontalAdvance if hasattr(fm, "horizontalAdvance") else fm.width
        italic_font = QFont(option.font)
        italic_font.setItalic(True)
        from qgis.PyQt.QtGui import QFontMetrics
        ifm = QFontMetrics(italic_font)
        iadv = ifm.horizontalAdvance if hasattr(ifm, "horizontalAdvance") else ifm.width
        needed_w = adv(text) + iadv(hint_str) + 32
        return QSize(max(base.width(), needed_w), max(base.height(), 22))

    def paint(self, painter, option, index):
        raw_hint = index.data(ROLE_RAW_HINT)
        if not raw_hint:
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        display_text = opt.text
        opt.text = ""

        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        painter.save()
        state_selected = getattr(QStyle.StateFlag, "State_Selected", getattr(QStyle, "State_Selected", 0x00020000))
        is_selected = bool(opt.state & state_selected)

        pal = opt.palette
        cg_active = getattr(QPalette.ColorGroup, "Active", getattr(QPalette, "Active", 0))
        cg_disabled = getattr(QPalette.ColorGroup, "Disabled", getattr(QPalette, "Disabled", 1))
        cr_text = getattr(QPalette.ColorRole, "Text", getattr(QPalette, "Text", 6))
        cr_hl_text = getattr(QPalette.ColorRole, "HighlightedText", getattr(QPalette, "HighlightedText", 13))

        if is_selected:
            main_color = pal.color(cg_active, cr_hl_text)
            hint_color = QColor(main_color)
            hint_color.setAlpha(190)
        else:
            main_color = pal.color(cg_active, cr_text)
            hint_color = pal.color(cg_disabled, cr_text)

        text_rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget)
        if not text_rect.isValid():
            text_rect = opt.rect.adjusted(6, 0, -6, 0)
        else:
            text_rect = text_rect.adjusted(2, 0, -6, 0)

        align_vc = getattr(Qt.AlignmentFlag, "AlignVCenter", getattr(Qt, "AlignVCenter", 0x0080))
        align_l = getattr(Qt.AlignmentFlag, "AlignLeft", getattr(Qt, "AlignLeft", 0x0001))
        align_r = getattr(Qt.AlignmentFlag, "AlignRight", getattr(Qt, "AlignRight", 0x0002))

        hint_str = str(raw_hint)
        italic_font = QFont(opt.font)
        italic_font.setItalic(True)
        from qgis.PyQt.QtGui import QFontMetrics
        ifm = QFontMetrics(italic_font)
        iadv = ifm.horizontalAdvance if hasattr(ifm, "horizontalAdvance") else ifm.width
        hint_w = iadv(hint_str) + 4

        main_rect = QRect(text_rect.left(), text_rect.top(), max(20, text_rect.width() - hint_w - 8), text_rect.height())
        painter.setFont(opt.font)
        painter.setPen(main_color)
        elided_main = opt.fontMetrics.elidedText(display_text, Qt.ElideRight, main_rect.width())
        painter.drawText(main_rect, align_l | align_vc, elided_main)

        hint_rect = QRect(text_rect.right() - hint_w, text_rect.top(), hint_w, text_rect.height())
        painter.setFont(italic_font)
        painter.setPen(hint_color)
        painter.drawText(hint_rect, align_r | align_vc, hint_str)
        painter.restore()
