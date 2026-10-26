# -*- coding: utf-8 -*-
"""
功能 2：多字段自适应属性快赋面板 (QDockWidget)
支持手动自由双模切换：
1. 【表格视图 (Table View)】：标准两列表格 [属性字段 | 属性值]，紧凑整洁
2. 【横向表单视图 (Form View)】：流式水平表单条，停靠在底部或宽屏时极度自然舒适
提供右上角【刷新】【切换视图】【组织字段】三枚快捷按键
"""

import os
import html
from PyQt5.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QLabel, QComboBox, QPushButton, QFrame,
    QLineEdit, QToolButton, QStackedWidget,
    QScrollArea, QFormLayout
)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, pyqtSignal
from qgis.core import QgsVectorLayer
from ..core.attribute_engine import AttributeEngine
from ..core.config_manager import ConfigManager
from ..i18n_helper import tr
from . import theme


def _keep_original_text():
    """「保持原值」哨兵文本：填充与比较必须走同一 tr()，保证任意语言下一致"""
    return tr("-- Keep original value --")


class DockAttributePanel(QDockWidget):
    applied = pyqtSignal(dict)

    def __init__(self, iface, config, parent=None):
        super().__init__(tr("Attribute Quick Assign (AttrSnap)"), parent)
        self.iface = iface
        self.config = config
        self.editors = {}           # fname -> QComboBox (共享控件引用)
        self.current_layer = None
        self.current_view_mode = 0  # 0: 表格视图(Table), 1: 横向表单流视图(Horizontal Form)
        self._form_built = False    # 表单条懒构建标记（首次切到该视图才创建卡片）
        self._field_uniques = {}    # fname -> 候选值列表（构建表单条时复用，避免二次提取）

        self.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea |
            Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea
        )

        self._init_ui()
        self.dockLocationChanged.connect(self._on_dock_location_changed)

    def _init_ui(self):
        self.main_widget = QWidget()
        self.main_layout = QVBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(6, 6, 6, 6)
        self.main_layout.setSpacing(6)

        # 1. 顶部状态信息条 + 工具按钮
        self.status_frame = QFrame()
        self.status_frame.setStyleSheet(theme.STATUS_FRAME_SS)
        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(6, 4, 6, 4)

        self.lbl_status = QLabel(tr("Box-select features on the map first"))
        self.lbl_status.setStyleSheet(theme.STATUS_LABEL_SS)
        status_layout.addWidget(self.lbl_status, 1)

        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")

        # 视图切换按钮
        self.btn_toggle_view = QToolButton()
        switch_icon = QIcon(os.path.join(icons_dir, "switch_view.svg"))
        if not switch_icon.isNull():
            self.btn_toggle_view.setIcon(switch_icon)
        self.btn_toggle_view.setText(" " + tr("Form/Table"))
        self.btn_toggle_view.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_toggle_view.setToolTip(tr("Switch view: standard table ⇋ horizontal form strip"))
        self.btn_toggle_view.clicked.connect(self._toggle_view_mode)
        status_layout.addWidget(self.btn_toggle_view)

        # 刷新按钮
        self.btn_refresh = QToolButton()
        refresh_icon = QIcon(os.path.join(icons_dir, "refresh.svg"))
        if not refresh_icon.isNull():
            self.btn_refresh.setIcon(refresh_icon)
        self.btn_refresh.setToolTip(tr("Reload fields and values from the active layer"))
        self.btn_refresh.clicked.connect(self._force_refresh)
        status_layout.addWidget(self.btn_refresh)

        # 组织字段显示设置按钮
        self.btn_organize = QToolButton()
        org_icon = QIcon(os.path.join(icons_dir, "organize.svg"))
        if not org_icon.isNull():
            self.btn_organize.setIcon(org_icon)
        self.btn_organize.setToolTip(tr("Open field visibility & settings (control which fields show/hide)"))
        self.btn_organize.clicked.connect(self._open_organize_settings)
        status_layout.addWidget(self.btn_organize)

        self.main_layout.addWidget(self.status_frame)

        # 2. 字段快速搜索过滤框
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(tr("Filter fields..."))
        search_icon = QIcon(os.path.join(icons_dir, "search.svg"))
        if not search_icon.isNull():
            self.search_box.addAction(search_icon, QLineEdit.LeadingPosition)
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setStyleSheet(theme.LINEEDIT_SS)
        self.search_box.textChanged.connect(self._filter_rows)
        self.main_layout.addWidget(self.search_box)

        # 3. 核心容器：QStackedWidget (实现表格与表单双模瞬间平滑切换)
        self.stack = QStackedWidget()

        # 页面 0: 标准两列表格视图
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([tr("Field"), tr("Value")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().resizeSection(0, 110)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(theme.TABLE_SS)
        self.stack.addWidget(self.table)

        # 页面 1: 横向平铺表单流视图 (极其适合停靠在底部或横屏宽条)
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setFrameShape(QFrame.NoFrame)

        self.form_container = QWidget()
        self.form_layout = QHBoxLayout(self.form_container)
        self.form_layout.setContentsMargins(4, 4, 4, 4)
        self.form_layout.setSpacing(10)
        self.form_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.form_scroll.setWidget(self.form_container)

        self.stack.addWidget(self.form_scroll)
        self.main_layout.addWidget(self.stack)

        # 4. 底部操作按钮条
        self.btn_layout = QHBoxLayout()
        self.btn_apply = QPushButton(tr("Apply changes (Enter)"))
        apply_icon = QIcon(os.path.join(icons_dir, "apply.svg"))
        if not apply_icon.isNull():
            self.btn_apply.setIcon(apply_icon)
        self.btn_apply.setStyleSheet(theme.BUTTON_PRIMARY_SS)
        self.btn_apply.clicked.connect(self.apply_changes)

        self.btn_clear = QPushButton(tr("Cancel selection"))
        clear_icon = QIcon(os.path.join(icons_dir, "clear.svg"))
        if not clear_icon.isNull():
            self.btn_clear.setIcon(clear_icon)
        self.btn_clear.setStyleSheet(theme.BUTTON_SECONDARY_SS)
        self.btn_clear.clicked.connect(self._clear_selection)

        self.btn_layout.addWidget(self.btn_apply)
        self.btn_layout.addWidget(self.btn_clear)
        self.main_layout.addLayout(self.btn_layout)

        self.setWidget(self.main_widget)
        self.rebuild_fields_ui()

    def _toggle_view_mode(self):
        """手动在表格视图与横向表单视图之间切换"""
        self.current_view_mode = 1 if self.current_view_mode == 0 else 0
        if self.current_view_mode == 1 and not self._form_built:
            self._build_form_items()
        self.stack.setCurrentIndex(self.current_view_mode)
        mode_text = tr("horizontal form strip") if self.current_view_mode == 1 else tr("standard table")
        self.iface.messageBar().pushInfo("AttrSnap", tr("Switched to: [{0}] view").format(mode_text))

    def _on_dock_location_changed(self, area):
        """停靠位置变动时自动智能推荐（停在底部自动切为横向表单条，停在侧边切为表格）"""
        if area in [Qt.TopDockWidgetArea, Qt.BottomDockWidgetArea]:
            self.current_view_mode = 1
        else:
            self.current_view_mode = 0
        if self.current_view_mode == 1 and not self._form_built:
            self._build_form_items()
        self.stack.setCurrentIndex(self.current_view_mode)

    def _clear_form_items(self):
        """清空横向表单条的所有卡片"""
        while self.form_layout.count() > 0:
            item = self.form_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _build_form_items(self):
        """构建横向表单条卡片（懒构建：首次切到该视图时才创建，宽字段图层更轻快）"""
        for fname, uniques in self._field_uniques.items():
            combo_table = self.editors.get(fname)
            if combo_table is None:
                continue

            form_item_box = QFrame()
            form_item_box.setStyleSheet(theme.CARD_SS)
            box_layout = QVBoxLayout(form_item_box)
            box_layout.setContentsMargins(4, 2, 4, 2)
            box_layout.setSpacing(2)

            escaped_fname = html.escape(fname)
            lbl_f = QLabel(f"<b>{escaped_fname}</b>")
            combo_form = QComboBox()
            combo_form.setEditable(True)
            combo_form.setInsertPolicy(QComboBox.NoInsert)
            combo_form.lineEdit().setPlaceholderText(tr("Select or type a value"))
            combo_form.setStyleSheet(theme.COMBO_SS)
            combo_form.addItem(_keep_original_text(), userData=None)
            for val in uniques:
                combo_form.addItem(str(val), userData=str(val))
            combo_form.setCurrentIndex(0)
            combo_form.setMinimumWidth(130)

            box_layout.addWidget(lbl_f)
            box_layout.addWidget(combo_form)
            self.form_layout.addWidget(form_item_box)

            # 双模数据联动同步 (修改表格的下拉，表单下拉同步变；反之亦然)
            combo_table.currentIndexChanged.connect(
                lambda idx, c2=combo_form: c2.setCurrentIndex(idx) if c2.currentIndex() != idx else None
            )
            combo_form.currentIndexChanged.connect(
                lambda idx, c1=combo_table: c1.setCurrentIndex(idx) if c1.currentIndex() != idx else None
            )
            combo_table.currentTextChanged.connect(
                lambda txt, c2=combo_form: c2.setEditText(txt) if c2.currentText() != txt else None
            )
            combo_form.currentTextChanged.connect(
                lambda txt, c1=combo_table: c1.setEditText(txt) if c1.currentText() != txt else None
            )

        self.form_layout.addStretch()
        self._form_built = True

    def _force_refresh(self):
        """手动刷新：先清空唯一值会话缓存，重建面板（用于获取外部编辑后的最新枚举值）"""
        AttributeEngine.invalidate_cache(self.iface.activeLayer())
        self.rebuild_fields_ui()

    def rebuild_fields_ui(self, layer=None):
        """重新加载当前图层的所有字段与枚举，并同时同步渲染到表格与表单中"""
        if layer:
            self.current_layer = layer
        else:
            self.current_layer = self.iface.activeLayer()

        self.table.setRowCount(0)
        # 清除表单控件（表单条懒构建，见 _build_form_items）
        self._clear_form_items()
        self._form_built = False
        self._field_uniques = {}
        self.editors.clear()

        if not self.current_layer or not self.current_layer.isValid() or not isinstance(self.current_layer, QgsVectorLayer):
            self.lbl_status.setText(tr("Current layer is not a vector layer (only vector layers support assignment)"))
            self.btn_apply.setEnabled(False)
            return

        layer_name_escaped = html.escape(self.current_layer.name())
        all_layer_fields = AttributeEngine.get_editable_fields(self.current_layer)
        if not all_layer_fields:
            self.lbl_status.setText(tr("Layer: {0} (no editable fields)").format(layer_name_escaped))
            return

        # 组织字段过滤
        layer_id = self.current_layer.id()
        visible_list = self.config.get("visible_fields_by_layer", {}).get(layer_id, None)

        if visible_list is not None:
            layer_fields = [f for f in all_layer_fields if f["name"] in visible_list]
        else:
            layer_fields = all_layer_fields

        if not layer_fields:
            self.lbl_status.setText(tr("Layer: {0} (all fields are hidden in settings)").format(layer_name_escaped))
            return

        self.table.setRowCount(len(layer_fields))

        for row, f in enumerate(layer_fields):
            fname = f["name"]

            # 自动提取该字段的不重复枚举值（AttributeEngine 会话级缓存，图层切换不再重复全表统计）
            uniques = AttributeEngine.extract_unique_values(self.current_layer, fname, limit=50)
            self._field_uniques[fname] = uniques

            # 构建表格视图单元格
            item_field = QTableWidgetItem(fname)
            item_field.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            font = item_field.font()
            font.setBold(True)
            item_field.setFont(font)
            self.table.setItem(row, 0, item_field)

            combo_table = QComboBox()
            combo_table.setEditable(True)
            combo_table.setInsertPolicy(QComboBox.NoInsert)
            combo_table.lineEdit().setPlaceholderText(tr("Select or type a new value"))
            combo_table.setStyleSheet(theme.COMBO_SS)
            combo_table.addItem(_keep_original_text(), userData=None)
            for val in uniques:
                combo_table.addItem(str(val), userData=str(val))
            combo_table.setCurrentIndex(0)
            self.table.setCellWidget(row, 1, combo_table)
            self.editors[fname] = combo_table

        # 表单条视图懒构建：当前就在该视图时立即构建，否则等首次切换时再建
        if self.current_view_mode == 1:
            self._build_form_items()

        self.stack.setCurrentIndex(self.current_view_mode)
        self.update_selection_info()

    def _filter_rows(self, keyword):
        """按关键字过滤行/表单项"""
        kw = keyword.strip().lower()
        # 过滤表格行
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                self.table.setRowHidden(row, kw not in item.text().lower())

        # 过滤横向表单项
        for i in range(self.form_layout.count() - 1):
            w = self.form_layout.itemAt(i).widget()
            if w:
                lbl = w.findChild(QLabel)
                if lbl:
                    w.setVisible(kw in lbl.text().lower())

    def update_selection_info(self):
        """更新当前要素选择状态"""
        layer = self.iface.activeLayer()
        if not layer or not layer.isValid() or not isinstance(layer, QgsVectorLayer):
            self.lbl_status.setText(tr("No vector layer selected"))
            self.btn_apply.setEnabled(False)
            return

        count = layer.selectedFeatureCount()
        escaped_name = html.escape(layer.name())
        if count > 0:
            self.lbl_status.setText(
                tr("Layer: <b>{0}</b> | selected: <b>{1}</b> features").format(escaped_name, count))
            self.btn_apply.setEnabled(True)
        else:
            self.lbl_status.setText(
                tr("Layer: <b>{0}</b> | no selection (box-select features to assign)").format(escaped_name))
            self.btn_apply.setEnabled(False)

    def apply_changes(self):
        """执行批量属性赋值"""
        layer = self.iface.activeLayer()
        if not layer or layer.selectedFeatureCount() == 0:
            return

        keep_text = _keep_original_text()
        changes_to_apply = {}
        for fname, editor in self.editors.items():
            # 按文本判断而非 currentIndex：可编辑下拉中用户直接手打的值
            # 不会改变 index(仍为 0)，按 index 判断会静默丢弃手输值
            val_text = editor.currentText().strip()
            if not val_text or val_text == keep_text:
                continue

            changes_to_apply[fname] = val_text

        if not changes_to_apply:
            self.iface.messageBar().pushWarning(
                "AttrSnap", tr("All fields are set to [Keep original value]; nothing was changed"))
            return

        auto_edit = self.config.get("behavior", {}).get("auto_start_editing", True)
        count, msg = AttributeEngine.batch_update_multi_fields(
            layer, changes_to_apply, auto_start_editing=auto_edit
        )
        self.iface.messageBar().pushInfo("AttrSnap", msg)

        # 重置所有下拉框回到【保持原值】
        # setCurrentIndex(0) 对"手输值(index 仍为 0)"是空操作，需再显式复位文本
        for editor in self.editors.values():
            editor.setCurrentIndex(0)
            editor.setCurrentText(keep_text)

    def _clear_selection(self):
        layer = self.iface.activeLayer()
        if layer:
            layer.removeSelection()
            self.update_selection_info()

    def _open_organize_settings(self):
        """打开字段显示组织（直达 Tab 1 字段可见性控制）"""
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.iface, self.config, self, initial_tab=SettingsDialog.TAB_VISIBILITY)
        if dlg.exec_():
            self.config = ConfigManager.get_config()
            self.rebuild_fields_ui()
