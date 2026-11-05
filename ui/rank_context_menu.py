# -*- coding: utf-8 -*-
"""
功能 1：右键快速赋值菜单
纯粹、专注、单层菜单：
- 支持初次使用或换图层时主动弹窗引导用户显式确定赋值字段，绝不静默绑定错误字段
- 菜单顶部提供微型翻转排序切换控制条（字母顺序、频次排序）
- 展示字段值及其在图层中的真实频次统计，高频优先排序大幅提升赋值效率
- 菜单顶部常驻【切换目标字段】操作项，随时一键切换，切换后自动刷新菜单
- 支持按图层记住各自设定的赋值字段与排序偏好
"""

import os
from qgis.PyQt.QtWidgets import (
    QMenu, QInputDialog, QLineEdit, QWidgetAction,
    QWidget, QHBoxLayout, QVBoxLayout, QToolButton, QLabel,
    QStyle, QScrollArea, QFrame
)
from qgis.PyQt.QtGui import QIcon, QCursor, QPainter, QFontMetrics, QPalette, QColor, QFont
from qgis.PyQt.QtCore import QTimer, QSize, Qt, QRect, pyqtSignal
from qgis.core import QgsApplication
from ..core.compat import safe_exec, calculate_menu_spawn_pos
from ..core.attribute_engine import AttributeEngine
from ..core.config_manager import ConfigManager
from ..i18n_helper import tr
from .target_field_dialog import TargetFieldDialog


_SORT_BTN_SS = """
QToolButton {
    border: 1px solid transparent;
    border-radius: 3px;
    background-color: transparent;
    padding: 2px;
}
QToolButton:hover {
    background-color: rgba(148, 163, 184, 0.22);
    border: 1px solid rgba(148, 163, 184, 0.45);
}
QToolButton:checked {
    background-color: rgba(37, 99, 235, 0.14);
    border: 1px solid #2563EB;
}
QToolButton:checked:hover {
    background-color: rgba(37, 99, 235, 0.22);
    border: 1px solid #1D4ED8;
}
"""


class RankValueItemWidget(QWidget):
    """
    右键分级菜单专属候选值项（QGIS 原生菜单渲染风格 + 零子控件极速自绘 + 当前值星标标识）：
    - 悬停时直接用系统 QPalette.Highlight 绘制整行高亮，未悬停时透明透出 QMenu 底色
    - 当该项属于当前已选要素的属性值时，在左侧图标槽绘制 current_val.svg 绿色星标并加粗文本
    - 移除内部 QHBoxLayout、双 QLabel 与数百次 setStyleSheet 解析，150 项构建耗时 < 2ms
    """
    clicked = pyqtSignal()

    def __init__(self, val, count, font_metrics: QFontMetrics, left_padding: int = 28,
                 item_height: int = 24, active_count: int = 0, total_selected: int = 0,
                 current_icon: QIcon = None, menu_ref=None, parent=None):
        super().__init__(parent)
        self.val = val
        self.count = count
        self.active_count = active_count
        self.total_selected = total_selected
        self.is_current = active_count > 0
        self._current_icon = current_icon
        self.val_text = str(val)
        if count > 0:
            if self.is_current and total_selected > 1 and active_count < total_selected:
                self.cnt_text = f"({count:,} · {active_count}/{total_selected})"
            else:
                self.cnt_text = f"({count:,})"
        else:
            self.cnt_text = f"({active_count}/{total_selected})" if (self.is_current and total_selected > 1) else ""

        self._left_pad = left_padding
        self._menu_ref = menu_ref
        self._is_hovered = False

        self.setFixedHeight(item_height)
        self.setAttribute(Qt.WA_Hover, True)
        self.setMouseTracking(True)
        self.setAutoFillBackground(False)

        # 计算文本宽度（若为当前值则按加粗后略宽 4px 预算）
        raw_val_w = font_metrics.horizontalAdvance(self.val_text) if hasattr(font_metrics, "horizontalAdvance") else font_metrics.width(self.val_text)
        self._val_w = raw_val_w + (6 if self.is_current else 0)
        if self.cnt_text:
            cnt_w = font_metrics.horizontalAdvance(self.cnt_text) if hasattr(font_metrics, "horizontalAdvance") else font_metrics.width(self.cnt_text)
            self.preferred_width = self._left_pad + self._val_w + 6 + cnt_w + 18
        else:
            self.preferred_width = self._left_pad + self._val_w + 18

    def set_hovered(self, hovered: bool):
        if self._is_hovered != hovered:
            self._is_hovered = hovered
            self.update()

    def sizeHint(self):
        return QSize(self.preferred_width, self.height())

    def paintEvent(self, e):
        p = QPainter(self)
        rect = self.rect()
        pal = self.palette()

        cg_active = getattr(QPalette.ColorGroup, "Active", getattr(QPalette, "Active", 0))
        cg_disabled = getattr(QPalette.ColorGroup, "Disabled", getattr(QPalette, "Disabled", 1))
        cr_text = getattr(QPalette.ColorRole, "Text", getattr(QPalette, "Text", 6))
        cr_highlight = getattr(QPalette.ColorRole, "Highlight", getattr(QPalette, "Highlight", 12))
        cr_hl_text = getattr(QPalette.ColorRole, "HighlightedText", getattr(QPalette, "HighlightedText", 13))

        hl_bg = pal.color(cg_active, cr_highlight)
        if not hl_bg.isValid() or hl_bg.alpha() == 0:
            hl_bg = QColor("#0078D7")

        # 1. 悬停时直接用系统 QPalette.Highlight 填充整行高亮蓝底，未悬停时保持完全透明透出 QMenu 底色
        if self._is_hovered:
            p.fillRect(rect, hl_bg)

            val_color = pal.color(cg_active, cr_hl_text)
            if not val_color.isValid():
                val_color = QColor("#FFFFFF")
            cnt_color = QColor(val_color)
            cnt_color.setAlpha(195)
        else:
            val_color = pal.color(cg_active, cr_text)
            cnt_color = pal.color(cg_disabled, cr_text)

        # 2. 若该候选值是当前已选要素正在使用的值，在左侧图标槽居中绘制 current_val.svg 矢量图标
        if self.is_current and self._current_icon is not None and not self._current_icon.isNull():
            ic_sz = 15
            ix = int((self._left_pad - ic_sz) / 2)
            iy = int((rect.height() - ic_sz) / 2)
            self._current_icon.paint(p, QRect(ix, iy, ic_sz, ic_sz))

        align_vcenter = getattr(Qt.AlignmentFlag, "AlignVCenter", getattr(Qt, "AlignVCenter", 0x0080))
        align_left = getattr(Qt.AlignmentFlag, "AlignLeft", getattr(Qt, "AlignLeft", 0x0001))
        flags = align_left | align_vcenter

        # 3. 绘制主属性值文本（当前值微加粗以便一眼识别）
        if self.is_current:
            bold_font = QFont(self.font())
            bold_font.setBold(True)
            p.setFont(bold_font)
        p.setPen(val_color)
        val_rect = QRect(self._left_pad, 0, self._val_w + 4, rect.height())
        p.drawText(val_rect, flags, self.val_text)

        # 4. 绘制频次统计副文本（恢复常规字重）
        if self.cnt_text:
            if self.is_current:
                p.setFont(self.font())
            p.setPen(cnt_color)
            cnt_x = self._left_pad + self._val_w + 6
            cnt_rect = QRect(cnt_x, 0, max(0, rect.width() - cnt_x - 6), rect.height())
            p.drawText(cnt_rect, flags, self.cnt_text)

    def enterEvent(self, e):
        if self._menu_ref is not None:
            self._menu_ref._on_value_item_hovered(self)
        else:
            self.set_hovered(True)
        super().enterEvent(e)

    def mouseMoveEvent(self, e):
        if not self._is_hovered and self._menu_ref is not None:
            self._menu_ref._on_value_item_hovered(self)
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.set_hovered(False)
        if self._menu_ref is not None and self._menu_ref._hovered_value_widget is self:
            self._menu_ref._hovered_value_widget = None
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
            e.accept()
        else:
            super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        e.ignore()


class RankContextMenu(QMenu):
    # 静态图标缓存，避免每次右键从磁盘重复解析 SVG
    _cached_icons = {}

    @classmethod
    def _get_cached_icon(cls, key: str, path: str, fallback_theme_name: str = "") -> QIcon:
        ic = cls._cached_icons.get(key)
        if ic is not None and not ic.isNull():
            return ic
        if os.path.exists(path):
            ic = QIcon(path)
        elif fallback_theme_name:
            ic = QgsApplication.getThemeIcon(fallback_theme_name)
        else:
            ic = QIcon()
        cls._cached_icons[key] = ic
        return ic

    def __init__(self, parent, layer, config, iface, spawn_pos=None, is_reopen=False):
        super().__init__(parent)
        self.layer = layer
        self.config = config
        self.iface = iface
        self.spawn_pos = spawn_pos
        self.is_reopen = is_reopen
        self.target_field = None
        self._hovered_value_widget = None
        self._active_sample = None
        self.setMouseTracking(True)

        # 候选分类值平滑滚动区域（仅对 #RankScrollArea 与垂直滚动条精确着色，绝不使用无选择器样式污染子控件或 Tooltip）
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("RankScrollArea")
        self._scroll.setWidgetResizable(True)
        no_frame = getattr(QFrame.Shape, "NoFrame", getattr(QFrame, "NoFrame", 0))
        self._scroll.setFrameShape(no_frame)
        sb_off = getattr(Qt.ScrollBarPolicy, "ScrollBarAlwaysOff", getattr(Qt, "ScrollBarAlwaysOff", 1))
        self._scroll.setHorizontalScrollBarPolicy(sb_off)
        self._scroll.viewport().setObjectName("RankScrollViewport")
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.setStyleSheet("""
            QScrollArea#RankScrollArea, QWidget#RankScrollViewport, QWidget#RankValuesContainer {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(148, 163, 184, 0.55);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(100, 116, 139, 0.80);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
                height: 0px;
            }
        """)

        self._values_container = QWidget()
        self._values_container.setObjectName("RankValuesContainer")
        self._values_container.setAutoFillBackground(False)
        self._values_layout = QVBoxLayout(self._values_container)
        self._values_layout.setContentsMargins(0, 0, 0, 0)
        self._values_layout.setSpacing(0)
        self._scroll.setWidget(self._values_container)

        # 监听原生菜单 Action 悬停，与内部候选值项实现严格互斥高亮
        self.hovered.connect(self._on_outer_action_hovered)

        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
        self._icon_alpha_asc = self._get_cached_icon("sort_az", os.path.join(icons_dir, "sort-AZ.svg"))
        self._icon_alpha_desc = self._get_cached_icon("sort_za", os.path.join(icons_dir, "sort-reverse-ZA.svg"))
        self._icon_freq_desc = self._get_cached_icon("sort_desc", os.path.join(icons_dir, "sort-dscend.svg"))
        self._icon_freq_asc = self._get_cached_icon("sort_asc", os.path.join(icons_dir, "sort-ascend.svg"))
        self._icon_current_val = self._get_cached_icon("current_val", os.path.join(icons_dir, "current_val.svg"))

        self._build_menu()

    def _on_value_item_hovered(self, item_widget):
        """当鼠标进入候选值项时：清除外层 QMenu 的活动 Action 高亮，保证全菜单唯一蓝色高亮"""
        if self._hovered_value_widget is not None and self._hovered_value_widget is not item_widget:
            self._hovered_value_widget.set_hovered(False)
        self._hovered_value_widget = item_widget
        item_widget.set_hovered(True)
        if self.activeAction() is not None:
            self.setActiveAction(None)

    def _clear_value_hover(self):
        """清除候选值区域内的悬停高亮"""
        if self._hovered_value_widget is not None:
            try:
                self._hovered_value_widget.set_hovered(False)
            except RuntimeError:
                pass
            self._hovered_value_widget = None

    def _on_outer_action_hovered(self, action):
        """当鼠标悬停到外层原生 QAction（如切换字段、输入新值、设为NULL）时，立即清除内部候选值高亮"""
        if action is not getattr(self, "_values_action", None):
            self._clear_value_hover()

    def mouseMoveEvent(self, e):
        act = self.actionAt(e.pos())
        if act is not getattr(self, "_values_action", None):
            self._clear_value_hover()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._clear_value_hover()
        super().leaveEvent(e)

    def _resolve_target_field(self, valid_names):
        """解析当前图层的赋值目标字段；若未设定则主动弹出选择框让用户确定"""
        layer_id = self.layer.id() if self.layer else ""
        by_layer = self.config.get("single_rank_by_layer", {})
        target = by_layer.get(layer_id)

        # 如果当前图层尚未指定或字段不存在，主动弹窗让用户指定，严禁静默绑定错误字段
        if not target or target not in valid_names:
            target = self._prompt_choose_field(valid_names, is_initial=True)

        return target

    def _prompt_choose_field(self, valid_names, is_initial=False):
        """弹出字段选择框，由用户显式确定赋值字段（展示 QGIS 原生字段类型图标）"""
        current_field = (
            self.config.get("single_rank_by_layer", {}).get(self.layer.id(), "")
            or self.config.get("single_rank", {}).get("field_name", "")
        )
        item = TargetFieldDialog.select_field(
            self.parent(),
            self.layer,
            valid_names,
            current_field=current_field
        )
        if item:
            by_layer = self.config.setdefault("single_rank_by_layer", {})
            by_layer[self.layer.id()] = item
            self.config.setdefault("single_rank", {})["field_name"] = item
            ConfigManager.save_config(self.config)
            return item
        return None

    def _sort_val_counts(self, val_counts, mode):
        """对 (val_str, count) 进行智能排序（支持自然序与同频次正序排列）"""
        if mode == "alpha_asc":
            return sorted(val_counts, key=lambda x: AttributeEngine.natural_sort_key(x[0]))
        elif mode == "alpha_desc":
            return sorted(val_counts, key=lambda x: AttributeEngine.natural_sort_key(x[0]), reverse=True)
        elif mode == "freq_desc":
            return sorted(val_counts, key=lambda x: (-x[1], AttributeEngine.natural_sort_key(x[0])))
        elif mode == "freq_asc":
            return sorted(val_counts, key=lambda x: (x[1], AttributeEngine.natural_sort_key(x[0])))
        elif mode == "num_asc":
            return sorted(val_counts, key=lambda x: AttributeEngine.natural_sort_key(x[0]))
        elif mode == "num_desc":
            return sorted(val_counts, key=lambda x: AttributeEngine.natural_sort_key(x[0]), reverse=True)
        return val_counts

    def _get_menu_left_padding(self) -> int:
        """计算与原生 QMenu 带图标菜单项一致的文字左起点"""
        pm_icon = getattr(getattr(QStyle, "PixelMetric", None), "PM_SmallIconSize", getattr(QStyle, "PM_SmallIconSize", 16))
        icon_sz = self.style().pixelMetric(pm_icon, None, self) if pm_icon is not None else 16
        return max(26, icon_sz + 12)

    def _create_sort_bar_action(self, current_mode):
        """创建嵌入菜单顶部的 2 按钮智能两态微型排序条（原生 QPalette 调色板风格）"""
        w_act = QWidgetAction(self)
        menu_self = self

        class _SortBarWidget(QWidget):
            def enterEvent(self, e):
                menu_self._clear_value_hover()
                if menu_self.activeAction() is not None:
                    menu_self.setActiveAction(None)
                super().enterEvent(e)

        bar = _SortBarWidget(self)
        bar.setAutoFillBackground(False)
        bar_layout = QHBoxLayout(bar)
        left_pad = self._get_menu_left_padding()
        bar_layout.setContentsMargins(left_pad, 2, 8, 2)
        bar_layout.setSpacing(4)

        lbl = QLabel(tr("Sort:"))
        pal = lbl.palette()
        cg_dis = getattr(QPalette.ColorGroup, "Disabled", getattr(QPalette, "Disabled", 1))
        cr_text = getattr(QPalette.ColorRole, "Text", getattr(QPalette, "Text", 6))
        cr_win_text = getattr(QPalette.ColorRole, "WindowText", getattr(QPalette, "WindowText", 0))
        muted_col = pal.color(cg_dis, cr_text)
        pal.setColor(cr_win_text, muted_col)
        pal.setColor(cr_text, muted_col)
        lbl.setPalette(pal)
        bar_layout.addWidget(lbl)

        # 字母排序按钮 (A->Z / Z->A 两态翻转)
        self.btn_sort_alpha = QToolButton()
        self.btn_sort_alpha.setFixedSize(22, 22)
        self.btn_sort_alpha.setCheckable(True)
        self.btn_sort_alpha.setStyleSheet(_SORT_BTN_SS)
        is_alpha = current_mode in ("alpha_asc", "alpha_desc")
        self.btn_sort_alpha.setChecked(is_alpha)
        if current_mode == "alpha_desc":
            self.btn_sort_alpha.setIcon(self._icon_alpha_desc)
            self.btn_sort_alpha.setToolTip(tr("Alphabetical Descending (Z -> A)"))
        else:
            self.btn_sort_alpha.setIcon(self._icon_alpha_asc)
            self.btn_sort_alpha.setToolTip(tr("Alphabetical Ascending (A -> Z)"))
        self.btn_sort_alpha.setIconSize(QSize(15, 15))
        self.btn_sort_alpha.clicked.connect(self._on_sort_alpha_clicked)
        bar_layout.addWidget(self.btn_sort_alpha)

        # 频次排序按钮 (多->少 / 少->多 两态翻转)
        self.btn_sort_freq = QToolButton()
        self.btn_sort_freq.setFixedSize(22, 22)
        self.btn_sort_freq.setCheckable(True)
        self.btn_sort_freq.setStyleSheet(_SORT_BTN_SS)
        is_freq = not is_alpha
        self.btn_sort_freq.setChecked(is_freq)
        if current_mode == "freq_asc":
            self.btn_sort_freq.setIcon(self._icon_freq_asc)
            self.btn_sort_freq.setToolTip(tr("Frequency Ascending (Least frequent first)"))
        else:
            self.btn_sort_freq.setIcon(self._icon_freq_desc)
            self.btn_sort_freq.setToolTip(tr("Frequency Descending (Most frequent first)"))
        self.btn_sort_freq.setIconSize(QSize(15, 15))
        self.btn_sort_freq.clicked.connect(self._on_sort_freq_clicked)
        bar_layout.addWidget(self.btn_sort_freq)

        bar_layout.addStretch()
        w_act.setDefaultWidget(bar)
        return w_act

    def _on_sort_alpha_clicked(self):
        current_mode = self.config.get("single_rank_sort_mode", "freq_desc")
        if current_mode == "alpha_asc":
            new_mode = "alpha_desc"
        elif current_mode == "alpha_desc":
            new_mode = "alpha_asc"
        else:
            new_mode = "alpha_asc"

        self._update_sort_buttons_ui(new_mode)
        self._on_change_sort_mode(new_mode)

    def _on_sort_freq_clicked(self):
        current_mode = self.config.get("single_rank_sort_mode", "freq_desc")
        if current_mode == "freq_desc":
            new_mode = "freq_asc"
        elif current_mode == "freq_asc":
            new_mode = "freq_desc"
        else:
            new_mode = "freq_desc"

        self._update_sort_buttons_ui(new_mode)
        self._on_change_sort_mode(new_mode)

    def _update_sort_buttons_ui(self, mode):
        self.btn_sort_alpha.blockSignals(True)
        self.btn_sort_freq.blockSignals(True)

        if mode in ("alpha_asc", "alpha_desc"):
            self.btn_sort_alpha.setChecked(True)
            self.btn_sort_freq.setChecked(False)
            if mode == "alpha_asc":
                self.btn_sort_alpha.setIcon(self._icon_alpha_asc)
                self.btn_sort_alpha.setToolTip(tr("Alphabetical Ascending (A -> Z)"))
            else:
                self.btn_sort_alpha.setIcon(self._icon_alpha_desc)
                self.btn_sort_alpha.setToolTip(tr("Alphabetical Descending (Z -> A)"))
        else:
            self.btn_sort_freq.setChecked(True)
            self.btn_sort_alpha.setChecked(False)
            if mode == "freq_asc":
                self.btn_sort_freq.setIcon(self._icon_freq_asc)
                self.btn_sort_freq.setToolTip(tr("Frequency Ascending (Least frequent first)"))
            else:
                self.btn_sort_freq.setIcon(self._icon_freq_desc)
                self.btn_sort_freq.setToolTip(tr("Frequency Descending (Most frequent first)"))

        self.btn_sort_alpha.blockSignals(False)
        self.btn_sort_freq.blockSignals(False)

    def _on_change_sort_mode(self, mode):
        """切换排序模式并在原地无缝刷新菜单项（零闪烁、不改变窗口尺寸、绝不截断）"""
        self.config["single_rank_sort_mode"] = mode
        ConfigManager.save_config(self.config)

        # 原地刷新分类值列表
        behavior = self.config.get("behavior", {})
        auto_edit = behavior.get("auto_start_editing", True)
        self._render_value_items(mode, auto_edit)

    def _render_value_items(self, sort_mode, auto_edit):
        """原地渲染/刷新候选分类值操作项（原生菜单样式 + 极速尺寸预算）"""
        self._hovered_value_widget = None
        # 清除旧的子组件
        while self._values_layout.count():
            child = self._values_layout.takeAt(0)
            w = child.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        if self._active_sample is None:
            self._active_sample = AttributeEngine.sample_selected_value_counts(self.layer, self.target_field)
        active_counts = self._active_sample.get("counts", {})
        sampled_total = self._active_sample.get("sampled_total", 0)

        val_counts = AttributeEngine.extract_unique_values_with_counts(self.layer, self.target_field)
        # 确保当前选中要素的非空值即使不在前 150 高频截断内，也必定出现在候选列表中
        existing_vals = {v for v, _ in val_counts}
        for act_val, act_cnt in active_counts.items():
            if act_val not in existing_vals:
                val_counts.append((act_val, act_cnt))

        sorted_val_counts = self._sort_val_counts(val_counts, sort_mode)

        fm = QFontMetrics(self.font())
        item_h = max(23, fm.height() + 7)
        left_pad = self._get_menu_left_padding()

        if sorted_val_counts:
            max_w = 160
            first_active_idx = -1
            for idx, (val, cnt) in enumerate(sorted_val_counts):
                act_cnt = active_counts.get(str(val).strip(), 0)
                if act_cnt > 0 and first_active_idx == -1:
                    first_active_idx = idx
                w = RankValueItemWidget(
                    val, cnt, fm,
                    left_padding=left_pad,
                    item_height=item_h,
                    active_count=act_cnt,
                    total_selected=sampled_total,
                    current_icon=self._icon_current_val,
                    menu_ref=self,
                    parent=self._values_container
                )
                w.clicked.connect(
                    lambda v=val: (self._on_apply_value(self.target_field, v, auto_edit), self.close())
                )
                self._values_layout.addWidget(w)
                if w.preferred_width > max_w:
                    max_w = w.preferred_width

            n_items = len(sorted_val_counts)
            visible_items = min(n_items, 11)  # 最多同时展示 11 项，超过平滑滚动，绝不超出屏幕
            target_h = visible_items * item_h
            self._scroll.setFixedHeight(target_h)
            self._scroll.setMinimumWidth(max(max_w + 16, 200))

            # 若当前值排在可视区下方（第 11 项以后），自动滚动使首个当前值居中可见
            if first_active_idx >= visible_items:
                scroll_y = max(0, (first_active_idx - visible_items // 2) * item_h)
                QTimer.singleShot(0, lambda y=scroll_y: self._scroll.verticalScrollBar().setValue(y))
            else:
                self._scroll.verticalScrollBar().setValue(0)
        else:
            lbl_empty = QLabel(tr("(this field currently contains only empty values in the layer)"), self._values_container)
            lbl_empty.setContentsMargins(left_pad, 6, 12, 6)
            pal = lbl_empty.palette()
            cg_dis = getattr(QPalette.ColorGroup, "Disabled", getattr(QPalette, "Disabled", 1))
            cr_text = getattr(QPalette.ColorRole, "Text", getattr(QPalette, "Text", 6))
            cr_win_text = getattr(QPalette.ColorRole, "WindowText", getattr(QPalette, "WindowText", 0))
            muted_col = pal.color(cg_dis, cr_text)
            pal.setColor(cr_win_text, muted_col)
            pal.setColor(cr_text, muted_col)
            lbl_empty.setPalette(pal)
            self._values_layout.addWidget(lbl_empty)
            self._scroll.setFixedHeight(max(30, item_h + 6))
            self._scroll.setMinimumWidth(230)
            self._scroll.verticalScrollBar().setValue(0)

    def _build_menu(self):
        behavior = self.config.get("behavior", {})
        auto_edit = behavior.get("auto_start_editing", True)
        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")

        fields = AttributeEngine.get_editable_fields(self.layer, include_icons=False)
        if not fields:
            self.addAction(tr("No editable fields in this layer")).setEnabled(False)
            return

        valid_names = [f["name"] for f in fields]
        self.target_field = self._resolve_target_field(valid_names)

        if not self.target_field:
            # 用户取消了初次字段指定
            act_cancel = self.addAction(tr("No target field selected (click to specify)"))
            act_cancel.triggered.connect(lambda: self._on_switch_target_field(valid_names))
            return

        selected_count = self.layer.selectedFeatureCount()

        # 1. 快捷切换赋值字段（合并显示当前字段与已选要素数）
        ic_opt = self._get_cached_icon("settings", os.path.join(icons_dir, "settings.svg"), "mActionOptions.svg")
        switch_act = self.addAction(
            ic_opt,
            tr("Switch field ( {0} )-[{1}]").format(self.target_field, selected_count)
        )
        switch_act.triggered.connect(lambda: self._on_switch_target_field(valid_names))

        # 2. 顶部微型 2 键智能翻转排序条
        current_sort_mode = self.config.get("single_rank_sort_mode", "freq_desc")
        self.addAction(self._create_sort_bar_action(current_sort_mode))

        self.addSeparator()

        # 3. 【核心】：提取唯一值及频次（嵌入滚动区，底部操作项永远可见）
        self._values_action = QWidgetAction(self)
        self._values_action.setDefaultWidget(self._scroll)
        self.addAction(self._values_action)
        self._render_value_items(current_sort_mode, auto_edit)

        # 4. 允许用户临时打字赋一个新分类值 (使用与图标库一致的原生增加属性图标)
        self.addSeparator()
        ic_add = self._get_cached_icon("add", os.path.join(icons_dir, "add.svg"), "symbologyAdd.svg")
        custom_act = self.addAction(ic_add, tr("Enter a new value..."))
        custom_act.triggered.connect(
            lambda checked, fn=self.target_field: self._on_custom_input(fn, auto_edit)
        )

        # 4.1 设置为 NULL / 清空字段值（若当前已选要素包含空值，直观显示绿色星标与加粗）
        null_count = self._active_sample.get("null_count", 0) if self._active_sample else 0
        ic_null = self._icon_current_val if (null_count > 0 and not self._icon_current_val.isNull()) else self._get_cached_icon("clear", os.path.join(icons_dir, "clear.svg"), "mIconClearText.svg")
        null_act = self.addAction(ic_null, tr("Set to NULL (Clear field)"))
        if null_count > 0:
            f_null = QFont(null_act.font())
            f_null.setBold(True)
            null_act.setFont(f_null)
        null_act.triggered.connect(
            lambda checked, fn=self.target_field: (self._on_apply_value(fn, None, auto_edit), self.close())
        )

        self.addSeparator()
        # 5. 快捷取消选择 (使用与图标库一致的图层取消选择图标)
        ic_clear = self._get_cached_icon("deselect", os.path.join(icons_dir, "deselect.svg"), "mActionDeselectActiveLayer.svg")
        clear_act = self.addAction(ic_clear, tr("Cancel selection"))
        clear_act.triggered.connect(lambda: self.layer.removeSelection())

    def show_at(self, click_pos=None, is_reopen=False):
        """以左侧垂直居中对齐与全向工作区防溢出安全弹出菜单"""
        target_click = click_pos if click_pos is not None else self.spawn_pos
        if target_click is None:
            target_click = QCursor.pos()

        if is_reopen or self.is_reopen:
            final_pos = target_click
        else:
            final_pos = calculate_menu_spawn_pos(target_click, self.sizeHint())

        self.spawn_pos = final_pos
        return safe_exec(self, final_pos)

    def _on_switch_target_field(self, valid_names):
        """用户点击切换目标字段"""
        saved_pos = self.pos() if self.isVisible() else self.spawn_pos
        new_field = self._prompt_choose_field(valid_names, is_initial=False)
        if new_field:
            self.iface.messageBar().pushSuccess(
                "QuickFieldBrush",
                tr("Target field for layer [{0}] changed to: [{1}]").format(self.layer.name(), new_field)
            )
            # 在原位置无缝重新打开分级菜单
            if self.layer and self.layer.selectedFeatureCount() > 0:
                QTimer.singleShot(60, lambda: self._reopen_menu_at(saved_pos))

    def _reopen_menu_at(self, pos):
        new_menu = RankContextMenu(
            self.parent(), self.layer, ConfigManager.get_config(), self.iface,
            spawn_pos=pos, is_reopen=True
        )
        target_pos = pos if pos is not None else QCursor.pos()
        new_menu.show_at(target_pos, is_reopen=True)

    def _on_apply_value(self, field_name, value, auto_edit):
        """执行批量写入"""
        count, msg = AttributeEngine.batch_update_single_field(
            self.layer, field_name, value, auto_start_editing=auto_edit
        )
        self.iface.messageBar().pushInfo("QuickFieldBrush", msg)

    def _on_custom_input(self, field_name, auto_edit):
        """现场打字输入值"""
        new_val, ok = QInputDialog.getText(
            self.parent(), tr("Enter a new value"),
            tr("Assign a new value to field [{0}] in batch:").format(field_name),
            QLineEdit.Normal, ""
        )
        if ok:
            clean_val = new_val.strip()
            # 自动规整：输入 "NULL"、"null" 或留空，自动转为赋底层的真 NULL
            if clean_val == "" or clean_val.upper() == "NULL":
                self._on_apply_value(field_name, None, auto_edit)
            else:
                self._on_apply_value(field_name, clean_val, auto_edit)
