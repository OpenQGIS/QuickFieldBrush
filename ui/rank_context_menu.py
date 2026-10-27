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
    QDialog, QComboBox, QDialogButtonBox, QStyleOption, QStyle
)
from qgis.PyQt.QtGui import QIcon, QCursor, QPainter
from qgis.PyQt.QtCore import QTimer, QSize, Qt, pyqtSignal
from ..core.compat import safe_exec, QAction
from ..core.attribute_engine import AttributeEngine
from ..core.config_manager import ConfigManager
from ..i18n_helper import tr
from . import theme


class RankValueItemWidget(QWidget):
    """右键分级菜单专属候选值项：值为主体黑色，频次统计为中灰色，有效避免用户以为输入内容包含数字"""
    clicked = pyqtSignal()

    def __init__(self, val, count, parent=None):
        super().__init__(parent)
        self.val = val
        self.count = count
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        # 左边距 26px 与带 16x16 图标的操作项对齐
        lay.setContentsMargins(26, 4, 14, 4)
        lay.setSpacing(6)

        self.lbl_val = QLabel(str(val))
        lay.addWidget(self.lbl_val)

        if count > 0:
            self.lbl_cnt = QLabel(f"({count:,})")
            lay.addWidget(self.lbl_cnt)

        lay.addStretch(1)
        self._is_hovered = False
        self._update_style()

    def paintEvent(self, e):
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)

    def _update_style(self):
        if self._is_hovered:
            self.setStyleSheet("""
                RankValueItemWidget {
                    background-color: #0078D7;
                }
            """)
            self.lbl_val.setStyleSheet("font-size: 12px; color: #FFFFFF; background: transparent; font-weight: 500;")
            if hasattr(self, 'lbl_cnt'):
                self.lbl_cnt.setStyleSheet("font-size: 11px; color: #BFDBFE; background: transparent;")
        else:
            self.setStyleSheet("""
                RankValueItemWidget {
                    background-color: transparent;
                }
            """)
            self.lbl_val.setStyleSheet("font-size: 12px; color: #0F172A; background: transparent; font-weight: normal;")
            if hasattr(self, 'lbl_cnt'):
                self.lbl_cnt.setStyleSheet("font-size: 11px; color: #718096; background: transparent;")

    def enterEvent(self, e):
        self._is_hovered = True
        self._update_style()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._is_hovered = False
        self._update_style()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
            e.accept()
        else:
            super().mouseReleaseEvent(e)


class RankContextMenu(QMenu):
    def __init__(self, parent, layer, config, iface, spawn_pos=None):
        super().__init__(parent)
        self.layer = layer
        self.config = config
        self.iface = iface
        self.spawn_pos = spawn_pos
        self.target_field = None
        self._value_actions = []
        self._bottom_sep = None

        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
        self._icon_alpha_asc = QIcon(os.path.join(icons_dir, "sort-AZ.svg"))
        self._icon_alpha_desc = QIcon(os.path.join(icons_dir, "sort-reverse-ZA.svg"))
        self._icon_freq_desc = QIcon(os.path.join(icons_dir, "sort-dscend.svg"))
        self._icon_freq_asc = QIcon(os.path.join(icons_dir, "sort-ascend.svg"))

        self.setStyleSheet(theme.MENU_SS)
        self._build_menu()

    def _resolve_target_field(self, valid_names):
        """解析当前图层的赋值目标字段；若未设定则主动弹出选择框让用户确定"""
        layer_id = self.layer.id() if self.layer else ""
        by_layer = self.config.get("single_rank_by_layer", {})
        target = by_layer.get(layer_id)

        # 回退到全局设置（仅当该字段确实存在于当前图层中）
        if not target or target not in valid_names:
            global_field = self.config.get("single_rank", {}).get("field_name", "")
            if global_field and global_field in valid_names:
                target = global_field

        # 如果依然未确定，主动弹窗让用户指定，严禁静默默认取第一个字段
        if not target or target not in valid_names:
            target = self._prompt_choose_field(valid_names, is_initial=True)

        return target

    def _prompt_choose_field(self, valid_names, is_initial=False):
        """弹出字段选择框，由用户显式确定赋值字段（展示 QGIS 原生字段类型图标）"""
        prompt_text = (
            tr("Please select the target field for rapid assignment in layer [{0}]:").format(self.layer.name())
            if is_initial else
            tr("Switch target field for layer [{0}]:").format(self.layer.name())
        )
        current_idx = 0
        current_field = self.config.get("single_rank_by_layer", {}).get(self.layer.id(), "")
        if current_field in valid_names:
            current_idx = valid_names.index(current_field)

        dlg = QDialog(self.parent())
        dlg.setWindowTitle(tr("Specify Target Field"))
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(11, 11, 11, 11)
        lay.setSpacing(8)

        lbl = QLabel(prompt_text)
        lay.addWidget(lbl)

        cb = QComboBox()
        for name in valid_names:
            ic = AttributeEngine.get_field_icon(self.layer, name)
            cb.addItem(ic, name, name)

        if 0 <= current_idx < cb.count():
            cb.setCurrentIndex(current_idx)
        lay.addWidget(cb)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        lay.addWidget(btn_box)

        dlg.resize(340, 110)
        if safe_exec(dlg) == QDialog.Accepted:
            item = cb.currentData()
            if item:
                by_layer = self.config.setdefault("single_rank_by_layer", {})
                by_layer[self.layer.id()] = item
                self.config.setdefault("single_rank", {})["field_name"] = item
                ConfigManager.save_config(self.config)
                return item
        return None

    def _sort_val_counts(self, val_counts, mode):
        """对 (val_str, count) 进行 6 维排序"""
        if mode == "alpha_asc":
            return sorted(val_counts, key=lambda x: str(x[0]).lower())
        elif mode == "alpha_desc":
            return sorted(val_counts, key=lambda x: str(x[0]).lower(), reverse=True)
        elif mode == "freq_desc":
            return sorted(val_counts, key=lambda x: (x[1], str(x[0]).lower()), reverse=True)
        elif mode == "freq_asc":
            return sorted(val_counts, key=lambda x: (x[1], str(x[0]).lower()))
        elif mode == "num_asc":
            def _num_key(x):
                try:
                    return (0, float(x[0]))
                except (ValueError, TypeError):
                    return (1, str(x[0]).lower())
            return sorted(val_counts, key=_num_key)
        elif mode == "num_desc":
            def _num_key_rev(x):
                try:
                    return (0, -float(x[0]))
                except (ValueError, TypeError):
                    return (1, str(x[0]).lower())
            return sorted(val_counts, key=_num_key_rev)
        return val_counts

    def _create_sort_bar_action(self, current_mode):
        """创建嵌入菜单顶部的 2 按钮智能两态微型排序条（与格式刷完全一致）"""
        w_act = QWidgetAction(self)
        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(8, 2, 8, 2)
        bar_layout.setSpacing(6)

        lbl = QLabel(tr("Sort:"))
        lbl.setStyleSheet("font-size: 11px; color: #64748B; font-weight: 600;")
        bar_layout.addWidget(lbl)

        # 字母排序按钮 (A->Z / Z->A 两态翻转)
        self.btn_sort_alpha = QToolButton()
        self.btn_sort_alpha.setFixedSize(24, 24)
        self.btn_sort_alpha.setCheckable(True)
        self.btn_sort_alpha.setAutoRaise(True)
        is_alpha = current_mode in ("alpha_asc", "alpha_desc")
        self.btn_sort_alpha.setChecked(is_alpha)
        if current_mode == "alpha_desc":
            self.btn_sort_alpha.setIcon(self._icon_alpha_desc)
            self.btn_sort_alpha.setToolTip(tr("Alphabetical Descending (Z -> A)"))
        else:
            self.btn_sort_alpha.setIcon(self._icon_alpha_asc)
            self.btn_sort_alpha.setToolTip(tr("Alphabetical Ascending (A -> Z)"))
        self.btn_sort_alpha.setIconSize(QSize(16, 16))
        self.btn_sort_alpha.clicked.connect(self._on_sort_alpha_clicked)
        bar_layout.addWidget(self.btn_sort_alpha)

        # 频次排序按钮 (多->少 / 少->多 两态翻转)
        self.btn_sort_freq = QToolButton()
        self.btn_sort_freq.setFixedSize(24, 24)
        self.btn_sort_freq.setCheckable(True)
        self.btn_sort_freq.setAutoRaise(True)
        is_freq = not is_alpha
        self.btn_sort_freq.setChecked(is_freq)
        if current_mode == "freq_asc":
            self.btn_sort_freq.setIcon(self._icon_freq_asc)
            self.btn_sort_freq.setToolTip(tr("Frequency Ascending (Least frequent first)"))
        else:
            self.btn_sort_freq.setIcon(self._icon_freq_desc)
            self.btn_sort_freq.setToolTip(tr("Frequency Descending (Most frequent first)"))
        self.btn_sort_freq.setIconSize(QSize(16, 16))
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
        """切换排序模式并在原地无缝刷新菜单项（菜单不关闭、不闪烁、不改变屏幕位置）"""
        self.config["single_rank_sort_mode"] = mode
        ConfigManager.save_config(self.config)

        # 原地刷新分类值列表
        behavior = self.config.get("behavior", {})
        auto_edit = behavior.get("auto_start_editing", True)
        self._render_value_items(mode, auto_edit)
        self.adjustSize()

    def _render_value_items(self, sort_mode, auto_edit):
        """原地渲染/刷新候选分类值操作项（值为主体黑色，频次为中灰色微弱字号）"""
        # 清除旧的值操作项
        for act in self._value_actions:
            self.removeAction(act)
        self._value_actions.clear()

        val_counts = AttributeEngine.extract_unique_values_with_counts(self.layer, self.target_field)
        sorted_val_counts = self._sort_val_counts(val_counts, sort_mode)

        if sorted_val_counts:
            for val, cnt in sorted_val_counts:
                w_act = QWidgetAction(self)
                w = RankValueItemWidget(val, cnt, self)
                w.clicked.connect(
                    lambda v=val: (self._on_apply_value(self.target_field, v, auto_edit), self.close())
                )
                w_act.setDefaultWidget(w)
                self.insertAction(self._bottom_sep, w_act)
                self._value_actions.append(w_act)
        else:
            empty_item = QAction(tr("(this field currently contains only empty values in the layer)"), self)
            empty_item.setEnabled(False)
            self.insertAction(self._bottom_sep, empty_item)
            self._value_actions.append(empty_item)

    def _build_menu(self):
        behavior = self.config.get("behavior", {})
        auto_edit = behavior.get("auto_start_editing", True)
        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")

        fields = AttributeEngine.get_editable_fields(self.layer)
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

        # 1. 快捷切换赋值字段（合并显示当前字段与已选要素数，移除了旧版的独立标题行）
        icon_settings = QIcon(os.path.join(icons_dir, "settings.svg"))
        switch_act = self.addAction(
            icon_settings,
            tr("Switch field ( {0} )-[{1}]").format(self.target_field, selected_count)
        )
        switch_act.triggered.connect(lambda: self._on_switch_target_field(valid_names))

        # 2. 顶部微型 2 键智能翻转排序条
        current_sort_mode = self.config.get("single_rank_sort_mode", "freq_desc")
        self.addAction(self._create_sort_bar_action(current_sort_mode))

        self.addSeparator()

        # 3. 【核心】：提取唯一值及频次，按用户偏好排序
        self._bottom_sep = self.addSeparator()
        self._render_value_items(current_sort_mode, auto_edit)

        # 4. 允许用户临时打字赋一个新分类值
        icon_add = QIcon(os.path.join(icons_dir, "add.svg"))
        custom_act = self.addAction(icon_add, tr("Enter a new value..."))
        custom_act.triggered.connect(
            lambda checked, fn=self.target_field: self._on_custom_input(fn, auto_edit)
        )

        self.addSeparator()
        # 快捷取消选择
        icon_clear = QIcon(os.path.join(icons_dir, "clear.svg"))
        clear_act = self.addAction(icon_clear, tr("Cancel selection"))
        clear_act.triggered.connect(lambda: self.layer.removeSelection())

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
        new_menu = RankContextMenu(self.parent(), self.layer, ConfigManager.get_config(), self.iface, spawn_pos=pos)
        target_pos = pos if pos is not None else QCursor.pos()
        safe_exec(new_menu, target_pos)

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
        if ok and new_val.strip():
            self._on_apply_value(field_name, new_val.strip(), auto_edit)
