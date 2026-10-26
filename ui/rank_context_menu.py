# -*- coding: utf-8 -*-
"""
功能 1：右键极速分级菜单
纯粹、专注、单层菜单：
- 支持初次使用或换图层时主动弹窗引导用户显式确定赋级字段，绝不静默绑定错误字段
- 菜单顶部提供 6 模式微型排序切换控制条（A-Z、Z-A、高频↓、低频↑、1-9、9-1）
- 展示字段值及其在图层中的真实频次统计，高频优先排序大幅提升赋级效率
- 菜单顶部常驻【切换目标字段】操作项，随时一键切换，切换后自动刷新菜单
- 支持按图层记住各自设定的赋级字段与排序偏好
"""

import os
from PyQt5.QtWidgets import (
    QMenu, QInputDialog, QLineEdit, QWidgetAction,
    QWidget, QHBoxLayout, QToolButton, QLabel
)
from PyQt5.QtGui import QIcon, QCursor
from PyQt5.QtCore import QTimer
from ..core.attribute_engine import AttributeEngine
from ..core.config_manager import ConfigManager
from ..i18n_helper import tr
from . import theme


class RankContextMenu(QMenu):
    def __init__(self, parent, layer, config, iface):
        super().__init__(parent)
        self.layer = layer
        self.config = config
        self.iface = iface
        self.target_field = None
        self.setStyleSheet(theme.MENU_SS)
        self._build_menu()

    def _resolve_target_field(self, valid_names):
        """解析当前图层的赋级目标字段；若未设定则主动弹出选择框让用户确定"""
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
        """弹出字段选择框，由用户显式确定赋级字段"""
        prompt_text = (
            tr("Please select the target field for rapid ranking in layer [{0}]:").format(self.layer.name())
            if is_initial else
            tr("Switch target ranking field for layer [{0}]:").format(self.layer.name())
        )
        current_idx = 0
        current_field = self.config.get("single_rank_by_layer", {}).get(self.layer.id(), "")
        if current_field in valid_names:
            current_idx = valid_names.index(current_field)

        item, ok = QInputDialog.getItem(
            self.parent(),
            tr("Specify Ranking Field"),
            prompt_text,
            valid_names,
            current_idx,
            False
        )
        if ok and item:
            # 记忆该图层的选择
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
        """创建嵌入菜单顶部的 6 模式微型排序切换条"""
        w_act = QWidgetAction(self)
        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(6, 2, 6, 2)
        bar_layout.setSpacing(3)

        lbl = QLabel(tr("Sort:"))
        lbl.setStyleSheet("font-size: 11px; color: #64748B; font-weight: 600;")
        bar_layout.addWidget(lbl)

        modes = [
            ("alpha_asc", "A-Z", tr("Alphabetical Ascending (A -> Z)")),
            ("alpha_desc", "Z-A", tr("Alphabetical Descending (Z -> A)")),
            ("freq_desc", tr("Freq↓"), tr("Frequency Descending (Most frequent first)")),
            ("freq_asc", tr("Freq↑"), tr("Frequency Ascending (Least frequent first)")),
            ("num_asc", "1-9", tr("Numeric Ascending (1 -> 9)")),
            ("num_desc", "9-1", tr("Numeric Descending (9 -> 1)")),
        ]

        btn_ss = """
        QToolButton {
            border: 1px solid #CBD5E1;
            border-radius: 3px;
            padding: 1px 3px;
            font-size: 11px;
            font-weight: 600;
            background: #F8FAFC;
            color: #334155;
            min-width: 24px;
            min-height: 18px;
        }
        QToolButton:hover {
            background: #E2E8F0;
            color: #0F172A;
        }
        QToolButton:checked {
            background: #2563EB;
            color: #FFFFFF;
            border-color: #1D4ED8;
        }
        """

        for m_key, text, tip in modes:
            btn = QToolButton()
            btn.setText(text)
            btn.setToolTip(tip)
            btn.setStyleSheet(btn_ss)
            btn.setCheckable(True)
            if m_key == current_mode:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, k=m_key: self._on_change_sort_mode(k))
            bar_layout.addWidget(btn)

        w_act.setDefaultWidget(bar)
        return w_act

    def _on_change_sort_mode(self, mode):
        """切换排序模式并重新渲染菜单"""
        self.config["single_rank_sort_mode"] = mode
        ConfigManager.save_config(self.config)
        self.close()
        QTimer.singleShot(40, self._reopen_menu)

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

        # 1. 菜单顶部标题（清晰告知当前是在给哪个字段分级，选中了几个要素）
        title_action = self.addAction(
            tr("Assign rank: [{0}] (selected: {1})").format(self.target_field, selected_count))
        title_action.setEnabled(False)

        # 2. 快捷切换赋级字段
        icon_settings = QIcon(os.path.join(icons_dir, "settings.svg"))
        switch_act = self.addAction(icon_settings, tr("Switch target field... (current: [{0}])").format(self.target_field))
        switch_act.triggered.connect(lambda: self._on_switch_target_field(valid_names))

        # 3. 顶部 6 模式微型排序切换控制条
        current_sort_mode = self.config.get("single_rank_sort_mode", "freq_desc")
        self.addAction(self._create_sort_bar_action(current_sort_mode))

        self.addSeparator()

        # 4. 【核心】：提取唯一值及频次，按用户偏好排序
        val_counts = AttributeEngine.extract_unique_values_with_counts(self.layer, self.target_field)
        sorted_val_counts = self._sort_val_counts(val_counts, current_sort_mode)

        if sorted_val_counts:
            for val, cnt in sorted_val_counts:
                label_text = f"{val}  ({cnt:,})" if cnt > 0 else str(val)
                act = self.addAction(label_text)
                act.triggered.connect(
                    lambda checked, fn=self.target_field, v=val: self._on_apply_value(fn, v, auto_edit)
                )
        else:
            empty_item = self.addAction(tr("(this field currently contains only empty values in the layer)"))
            empty_item.setEnabled(False)

        self.addSeparator()

        # 5. 允许用户临时打字赋一个新分类值
        icon_add = QIcon(os.path.join(icons_dir, "add.svg"))
        custom_act = self.addAction(icon_add, tr("Enter a new value to assign..."))
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
        new_field = self._prompt_choose_field(valid_names, is_initial=False)
        if new_field:
            self.iface.messageBar().pushSuccess(
                "QuickFieldBrush",
                tr("Target rank field for layer [{0}] changed to: [{1}]").format(self.layer.name(), new_field)
            )
            # 立即在光标位置无缝重新打开分级菜单
            if self.layer and self.layer.selectedFeatureCount() > 0:
                QTimer.singleShot(60, self._reopen_menu)

    def _reopen_menu(self):
        new_menu = RankContextMenu(self.parent(), self.layer, ConfigManager.get_config(), self.iface)
        new_menu.exec_(QCursor.pos())

    def _on_apply_value(self, field_name, value, auto_edit):
        """执行批量写入"""
        count, msg = AttributeEngine.batch_update_single_field(
            self.layer, field_name, value, auto_start_editing=auto_edit
        )
        self.iface.messageBar().pushInfo("QuickFieldBrush", msg)

    def _on_custom_input(self, field_name, auto_edit):
        """现场打字输入值"""
        new_val, ok = QInputDialog.getText(
            self.parent(), tr("Enter a new rank/value"),
            tr("Assign a new value to field [{0}] in batch:").format(field_name),
            QLineEdit.Normal, ""
        )
        if ok and new_val.strip():
            self._on_apply_value(field_name, new_val.strip(), auto_edit)

    def _on_switch_target_field(self, valid_names):
        """用户点击切换目标字段"""
        new_field = self._prompt_choose_field(valid_names, is_initial=False)
        if new_field:
            self.iface.messageBar().pushSuccess(
                "QuickFieldBrush",
                tr("Target rank field for layer [{0}] changed to: [{1}]").format(self.layer.name(), new_field)
            )
            # 立即在光标位置无缝重新打开分级菜单
            if self.layer and self.layer.selectedFeatureCount() > 0:
                QTimer.singleShot(60, self._reopen_menu)

    def _reopen_menu(self):
        new_menu = RankContextMenu(self.parent(), self.layer, ConfigManager.get_config(), self.iface)
        new_menu.exec_(QCursor.pos())

    def _on_apply_value(self, field_name, value, auto_edit):
        """执行批量写入"""
        count, msg = AttributeEngine.batch_update_single_field(
            self.layer, field_name, value, auto_start_editing=auto_edit
        )
        self.iface.messageBar().pushInfo("QuickFieldBrush", msg)

    def _on_custom_input(self, field_name, auto_edit):
        """现场打字输入值"""
        new_val, ok = QInputDialog.getText(
            self.parent(), tr("Enter a new rank/value"),
            tr("Assign a new value to field [{0}] in batch:").format(field_name),
            QLineEdit.Normal, ""
        )
        if ok and new_val.strip():
            self._on_apply_value(field_name, new_val.strip(), auto_edit)
