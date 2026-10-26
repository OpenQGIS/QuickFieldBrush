# -*- coding: utf-8 -*-
"""
插件配置对话框：
1. 【右键分级字段】：指定右键快速平铺展示的单目标字段
2. 【属性表组织与字段显示】（类似 QGIS 原生组织表功能）：
   - 以复选框列表形式展现图层所有字段
   - 勾选哪些字段显示，哪些字段隐藏
   - 支持【全选】、【全不选】、【反选】
3. 【交互偏好】：框选后自动弹出等
"""

import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QFormLayout, QComboBox, QPushButton,
    QCheckBox, QLabel, QGroupBox,
    QListWidget, QListWidgetItem
)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt
from qgis.core import QgsVectorLayer
from ..core.attribute_engine import AttributeEngine
from ..core.config_manager import ConfigManager
from ..i18n_helper import tr
from . import theme


class SettingsDialog(QDialog):
    TAB_VISIBILITY = 0   # 字段显示与组织 (面板列勾选)
    TAB_RANK = 1         # 右键快速分级目标字段与分类
    TAB_BEHAVIOR = 2     # 交互偏好设置

    def __init__(self, iface, config, parent=None, initial_tab=0):
        super().__init__(parent)
        self.iface = iface
        self.config = config.copy()
        self.setWindowTitle(tr("AttrSnap - Field Display & Rank Settings"))
        self.resize(520, 480)
        theme.apply_dialog_style(self)

        self._init_ui()
        self._load_current_layer_fields()
        self._populate_data()

        # 根据调用入口定向激活对应 Tab
        if 0 <= initial_tab < self.tabs.count():
            self.tabs.setCurrentIndex(initial_tab)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # Tab 1: 字段可见性控制 (类似 QGIS 组织表)
        self.tab_visibility = QWidget()
        self._init_tab_visibility()
        self.tabs.addTab(self.tab_visibility, tr("1. Field visibility (panel columns)"))

        # Tab 2: 右键快速分级字段
        self.tab_single = QWidget()
        self._init_tab_single()
        self.tabs.addTab(self.tab_single, tr("2. Right-click rank field"))

        # Tab 3: 交互偏好设置
        self.tab_behavior = QWidget()
        self._init_tab_behavior()
        self.tabs.addTab(self.tab_behavior, tr("3. Behavior"))

        layout.addWidget(self.tabs)

        # 底部确定/取消按钮
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        self.btn_save = QPushButton(tr("Save settings"))
        self.btn_save.setStyleSheet(theme.BUTTON_PRIMARY_SS)
        self.btn_save.clicked.connect(self._save_and_accept)

        self.btn_cancel = QPushButton(tr("Cancel"))
        self.btn_cancel.setStyleSheet(theme.BUTTON_SECONDARY_SS)
        self.btn_cancel.clicked.connect(self.reject)

        btn_box.addWidget(self.btn_save)
        btn_box.addWidget(self.btn_cancel)
        layout.addLayout(btn_box)

    def _init_tab_visibility(self):
        """类似 QGIS 组织列功能的字段勾选控制面板"""
        layout = QVBoxLayout(self.tab_visibility)

        lbl_desc = QLabel(tr("Check the fields to display in the quick-assign panel (unchecked fields are hidden to reduce clutter):"))
        lbl_desc.setStyleSheet(theme.HINT_LABEL_SS)
        lbl_desc.setWordWrap(True)
        layout.addWidget(lbl_desc)

        # 快捷全选/反选工具条
        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
        btn_bar = QHBoxLayout()
        self.btn_select_all = QPushButton(tr("Select all"))
        self.btn_select_all.setIcon(QIcon(os.path.join(icons_dir, "select_all.svg")))
        self.btn_select_all.clicked.connect(self._select_all_fields)

        self.btn_deselect_all = QPushButton(tr("Select none"))
        self.btn_deselect_all.setIcon(QIcon(os.path.join(icons_dir, "deselect_all.svg")))
        self.btn_deselect_all.clicked.connect(self._deselect_all_fields)

        self.btn_invert_selection = QPushButton(tr("Invert selection"))
        self.btn_invert_selection.setIcon(QIcon(os.path.join(icons_dir, "invert.svg")))
        self.btn_invert_selection.clicked.connect(self._invert_selection_fields)

        btn_bar.addWidget(self.btn_select_all)
        btn_bar.addWidget(self.btn_deselect_all)
        btn_bar.addWidget(self.btn_invert_selection)
        btn_bar.addStretch()
        layout.addLayout(btn_bar)

        # 字段多选列表容器（样式由主题统一提供）
        self.list_fields_visibility = QListWidget()
        layout.addWidget(self.list_fields_visibility)

    def _init_tab_single(self):
        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
        layout = QVBoxLayout(self.tab_single)
        form = QFormLayout()

        self.combo_single_field = QComboBox()
        self.combo_single_field.currentIndexChanged.connect(self._on_field_changed_preview)

        self.btn_refresh_fields = QPushButton(tr("Refresh"))
        self.btn_refresh_fields.setIcon(QIcon(os.path.join(icons_dir, "refresh.svg")))
        self.btn_refresh_fields.clicked.connect(self._load_current_layer_fields)

        field_row = QHBoxLayout()
        field_row.addWidget(self.combo_single_field, 1)
        field_row.addWidget(self.btn_refresh_fields)
        form.addRow("<b>{}</b>".format(tr("Right-click target rank field:")), field_row)
        layout.addLayout(form)

        # 当前图层分类实时预览列表
        grp = QGroupBox(tr("Existing categories of this field in the current layer (right-click flattens these values)"))
        grp_layout = QVBoxLayout(grp)

        self.list_preview = QListWidget()
        grp_layout.addWidget(self.list_preview)

        self.lbl_preview_count = QLabel(tr("No layer or field selected"))
        self.lbl_preview_count.setStyleSheet(theme.HINT_LABEL_SS)
        grp_layout.addWidget(self.lbl_preview_count)

        layout.addWidget(grp)

    def _init_tab_behavior(self):
        layout = QVBoxLayout(self.tab_behavior)

        self.chk_auto_popup = QCheckBox(tr("Auto-show the panel after box-selecting features"))
        self.chk_auto_edit = QCheckBox(tr("Auto-start editing when assigning if the layer is not editable (recommended)"))
        self.chk_auto_edit.setChecked(True)

        layout.addWidget(self.chk_auto_popup)
        layout.addWidget(self.chk_auto_edit)
        layout.addStretch()

    def _load_current_layer_fields(self):
        layer = self.iface.activeLayer()
        # 设置面板打开/刷新时清一次缓存，保证分类预览反映最新数据
        AttributeEngine.invalidate_cache(layer)
        self.combo_single_field.clear()
        self.list_fields_visibility.clear()

        if not layer or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            self.combo_single_field.addItem(tr("(no vector layer currently selected)"))
            item = QListWidgetItem(tr("No valid vector layer is active"))
            item.setFlags(Qt.NoItemFlags)
            self.list_fields_visibility.addItem(item)
            return

        fields = AttributeEngine.get_editable_fields(layer)
        layer_id = layer.id()
        visible_map = self.config.get("visible_fields_by_layer", {}).get(layer_id, None)

        for f in fields:
            fname = f["name"]
            ftype = f["typeName"]

            # 填充 Tab 2 下拉框
            self.combo_single_field.addItem(f"{fname} ({ftype})", fname)

            # 填充 Tab 1 组织列表
            item = QListWidgetItem(f"{fname}  [{ftype}]")
            item.setData(Qt.UserRole, fname)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)

            # 判断默认是否勾选（如果没有配置过，默认全部勾选显示）
            if visible_map is None:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Checked if fname in visible_map else Qt.Unchecked)

            self.list_fields_visibility.addItem(item)

        self._on_field_changed_preview()

    def _select_all_fields(self):
        for i in range(self.list_fields_visibility.count()):
            item = self.list_fields_visibility.item(i)
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(Qt.Checked)

    def _deselect_all_fields(self):
        for i in range(self.list_fields_visibility.count()):
            item = self.list_fields_visibility.item(i)
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(Qt.Unchecked)

    def _invert_selection_fields(self):
        for i in range(self.list_fields_visibility.count()):
            item = self.list_fields_visibility.item(i)
            if item.flags() & Qt.ItemIsUserCheckable:
                cur = item.checkState()
                item.setCheckState(Qt.Unchecked if cur == Qt.Checked else Qt.Checked)

    def _on_field_changed_preview(self):
        layer = self.iface.activeLayer()
        field_name = self.combo_single_field.currentData()
        self.list_preview.clear()

        if not layer or not isinstance(layer, QgsVectorLayer) or not field_name:
            self.lbl_preview_count.setText(tr("No layer or field selected"))
            return

        uniques = AttributeEngine.extract_unique_values(layer, field_name, limit=100)
        for u in uniques:
            self.list_preview.addItem(str(u))

        self.lbl_preview_count.setText(tr("Detected {0} existing categories in this layer").format(len(uniques)))

    def _populate_data(self):
        # 填充 Tab 2
        single_cfg = self.config.get("single_rank", {})
        target_f = single_cfg.get("field_name", "")
        if target_f:
            idx = self.combo_single_field.findData(target_f)
            if idx != -1:
                self.combo_single_field.setCurrentIndex(idx)

        # 填充 Tab 3
        beh = self.config.get("behavior", {})
        self.chk_auto_popup.setChecked(beh.get("auto_popup_dock", False))
        self.chk_auto_edit.setChecked(beh.get("auto_start_editing", True))

    def _save_and_accept(self):
        layer = self.iface.activeLayer()
        if layer and isinstance(layer, QgsVectorLayer):
            layer_id = layer.id()
            if "visible_fields_by_layer" not in self.config:
                self.config["visible_fields_by_layer"] = {}

            # 收集 Tab 1 勾选的可见字段列表
            visible_fields = []
            for i in range(self.list_fields_visibility.count()):
                item = self.list_fields_visibility.item(i)
                if item.checkState() == Qt.Checked:
                    fname = item.data(Qt.UserRole)
                    if fname:
                        visible_fields.append(fname)

            self.config["visible_fields_by_layer"][layer_id] = visible_fields

        # 收集 Tab 2
        target_f = self.combo_single_field.currentData() or self.combo_single_field.currentText()
        if "single_rank" not in self.config:
            self.config["single_rank"] = {}
        self.config["single_rank"]["field_name"] = target_f

        # 收集 Tab 3（合并保存，避免丢失未在 UI 暴露的键）
        self.config["behavior"] = {
            "auto_popup_dock": self.chk_auto_popup.isChecked(),
            "auto_start_editing": self.chk_auto_edit.isChecked()
        }

        # 持久化
        ConfigManager.save_config(self.config)
        self.accept()
