# -*- coding: utf-8 -*-
"""
格式刷常驻悬浮/置顶控制面板 (FormatPainterDialog)：
1. 支持【窗口置顶】切换：开启后始终悬浮在 QGIS 最顶层，不遮挡地图交互
2. 无模态 (Modeless) 交互：一边在地图上刷要素，一边随时在面板上切换字段或属性值，毫秒级即时生效！
3. 下拉框选择或手动打字时，即时同步给 FormatPainterTool
4. 提供【吸取属性】一键获取当前选中要素值
5. 上次使用的字段/值在关闭面板时持久化（合并保存，不整体覆盖配置）
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QPushButton, QLabel, QToolButton, QFrame,
    QInputDialog
)
from qgis.gui import QgsDockWidget
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt, pyqtSignal, QSize
from qgis.core import QgsVectorLayer, QgsApplication
from ..core.compat import set_window_stay_on_top
from ..core.attribute_engine import AttributeEngine
from ..core.config_manager import ConfigManager
from ..i18n_helper import tr
from . import theme


class FormatPainterDockWidget(QgsDockWidget):
    targetChanged = pyqtSignal(str, str)  # 字段或属性值改变时通知画笔工具

    def __init__(self, iface, painter_tool, parent=None):
        super().__init__(tr("Attribute Format Painter (console)"), parent or iface.mainWindow())
        self.setObjectName("QuickFieldBrushPainterDock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        self.iface = iface
        self.painter_tool = painter_tool
        self.layer = iface.activeLayer()
        self.config = ConfigManager.get_config()
        self.is_pinned = True  # 默认置顶
        self._prev_val_idx = 0
        self.current_sort_dim = "freq"  # "freq" 或 "alpha"
        self.sort_alpha_dir = "asc"      # "asc" 或 "desc"
        self.sort_freq_dir = "desc"      # "desc" 或 "asc"
        self._cached_val_counts = []

        self.setWindowTitle(tr("Attribute Format Painter (console)"))
        self.setFloating(True)
        self.resize(310, 150)

        self._init_ui()
        self._load_fields()

        # 绑定地图工具的吸取回调
        if hasattr(self.painter_tool, "on_feature_picked"):
            self.painter_tool.on_feature_picked = self._on_feature_absorbed_from_map

        # 监听激活图层切换信号，动态同步当前可用字段，避免悬浮窗引用失效 C++ 对象
        self.iface.currentLayerChanged.connect(self._on_layer_changed)

        # 监听浮动/停靠状态切换
        self.topLevelChanged.connect(self._on_top_level_changed)

    def refresh_state(self):
        """重新打开面板时刷新配置、当前活动图层字段与画笔绑定状态"""
        self.config = ConfigManager.get_config()
        self._reset_absorb_btn_text()
        self._load_fields()

    def _init_ui(self):
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        import os
        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")

        # 1. 顶部微标题栏：图标 + 标题 + 置顶按钮（仅悬浮时显示，停靠时由 QGIS 原生标题栏承载）
        self.top_bar_widget = QWidget()
        top_bar = QHBoxLayout(self.top_bar_widget)
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(6)

        lbl_icon = QLabel()
        painter_icon_path = os.path.join(icons_dir, "painter.svg")
        if os.path.exists(painter_icon_path):
            lbl_icon.setPixmap(QIcon(painter_icon_path).pixmap(16, 16))
        else:
            lbl_icon.setText("🖌️")
        top_bar.addWidget(lbl_icon)

        lbl_title = QLabel(tr("Attribute Format Painter (console)"))
        lbl_title.setStyleSheet(theme.LABEL_TITLE_SS)
        top_bar.addWidget(lbl_title, 1)

        # 置顶切换按钮（移至右上角，与历史面板完全一致）
        self.btn_pin = QToolButton()
        self.btn_pin.setFixedSize(22, 22)
        self.btn_pin.setCheckable(True)
        self.btn_pin.setChecked(True)
        self.btn_pin.setAutoRaise(True)
        self._icon_pin_on = QIcon(os.path.join(icons_dir, "pin_green.svg"))
        self._icon_pin_off = QIcon(os.path.join(icons_dir, "pin_grey.svg"))
        if not self._icon_pin_on.isNull():
            self.btn_pin.setIcon(self._icon_pin_on)
            self.btn_pin.setIconSize(QSize(14, 14))
        self.btn_pin.setToolTip(tr("Always on top (click to disable)"))
        self.btn_pin.toggled.connect(self._toggle_stay_on_top)
        top_bar.addWidget(self.btn_pin)

        layout.addWidget(self.top_bar_widget)

        # 2. 表单区域：目标字段（通栏） + 属性值（含排序按钮）
        form = QFormLayout()
        form.setSpacing(6)
        form.setContentsMargins(0, 0, 0, 0)

        # 第一行：目标字段通栏下拉框
        self.combo_field = QComboBox()
        self.combo_field.currentIndexChanged.connect(self._on_field_changed)
        form.addRow(tr("Target field"), self.combo_field)

        # 第二行：属性值 + 字母排序 + 频次排序
        val_box = QHBoxLayout()
        val_box.setSpacing(4)
        val_box.setContentsMargins(0, 0, 0, 0)

        self.combo_val = QComboBox()
        self.combo_val.setEditable(True)
        self.combo_val.lineEdit().setPlaceholderText(tr("Select or type the value to paint"))
        self.combo_val.currentIndexChanged.connect(self._on_val_index_changed)
        self.combo_val.lineEdit().textChanged.connect(self._on_value_changed)
        val_box.addWidget(self.combo_val, 1)

        # 排序按钮 1：字母维 (A->Z / Z->A 两态翻转)
        self._icon_alpha_asc = QIcon(os.path.join(icons_dir, "sort-AZ.svg"))
        self._icon_alpha_desc = QIcon(os.path.join(icons_dir, "sort-reverse-ZA.svg"))
        self.btn_sort_alpha = QToolButton()
        self.btn_sort_alpha.setFixedSize(22, 22)
        self.btn_sort_alpha.setCheckable(True)
        self.btn_sort_alpha.setChecked(False)
        self.btn_sort_alpha.setAutoRaise(True)
        self.btn_sort_alpha.setIcon(self._icon_alpha_asc)
        self.btn_sort_alpha.setIconSize(QSize(15, 15))
        self.btn_sort_alpha.setToolTip(tr("Alphabetical Ascending (A -> Z)"))
        self.btn_sort_alpha.clicked.connect(self._on_sort_alpha_clicked)
        val_box.addWidget(self.btn_sort_alpha)

        # 排序按钮 2：频次维 (多->少 / 少->多 两态翻转，默认激活高频优先)
        self._icon_freq_desc = QIcon(os.path.join(icons_dir, "sort-dscend.svg"))
        self._icon_freq_asc = QIcon(os.path.join(icons_dir, "sort-ascend.svg"))
        self.btn_sort_freq = QToolButton()
        self.btn_sort_freq.setFixedSize(22, 22)
        self.btn_sort_freq.setCheckable(True)
        self.btn_sort_freq.setChecked(True)
        self.btn_sort_freq.setAutoRaise(True)
        self.btn_sort_freq.setIcon(self._icon_freq_desc)
        self.btn_sort_freq.setIconSize(QSize(15, 15))
        self.btn_sort_freq.setToolTip(tr("Frequency Descending (Most frequent first)"))
        self.btn_sort_freq.clicked.connect(self._on_sort_freq_clicked)
        val_box.addWidget(self.btn_sort_freq)

        form.addRow(tr("Attribute value"), val_box)

        layout.addLayout(form)

        # 3. 第三行：当前刷入状态提示
        self.lbl_status = QLabel(tr("Status: pick a field and value first"))
        layout.addWidget(self.lbl_status)

        layout.addSpacing(2)

        # 4. 最下边的一行：吸取属性、置空为 NULL、退出按钮
        action_box = QHBoxLayout()
        action_box.setSpacing(6)

        self.btn_pick_from_selected = QPushButton(tr("Absorb attribute from feature"))
        absorb_icon = QIcon(os.path.join(icons_dir, "absorb.svg"))
        if not absorb_icon.isNull():
            self.btn_pick_from_selected.setIcon(absorb_icon)
            self.btn_pick_from_selected.setIconSize(QSize(15, 15))
        self.btn_pick_from_selected.setToolTip(tr("Click to enter eyedropper mode, or right-click any feature on map to absorb its value"))
        self.btn_pick_from_selected.clicked.connect(self._toggle_pick_mode)
        action_box.addWidget(self.btn_pick_from_selected, 2)

        self.btn_clear_null = QPushButton(tr("Set to NULL"))
        ic_null = QgsApplication.getThemeIcon("mIconClearText.svg")
        if ic_null.isNull():
            ic_null = QgsApplication.getThemeIcon("mIconClearItem.svg")
        if ic_null.isNull():
            ic_null = QIcon(os.path.join(icons_dir, "clear.svg"))
        self.btn_clear_null.setIcon(ic_null)
        self.btn_clear_null.setIconSize(QSize(15, 15))
        self.btn_clear_null.setToolTip(tr("Set painter value to NULL, or batch clear selected features"))
        self.btn_clear_null.clicked.connect(self._on_set_null_clicked)
        action_box.addWidget(self.btn_clear_null, 1)

        layout.addLayout(action_box)

        self.btn_close = QPushButton(tr("Exit format painter (Esc)"))
        self.btn_close.clicked.connect(self.close)
        layout.addWidget(self.btn_close)

        layout.addStretch(1)

        self.setWidget(container)

    def _on_top_level_changed(self, is_floating):
        """当面板在浮动窗口与侧边停靠之间切换时触发"""
        self.top_bar_widget.setVisible(is_floating)
        if is_floating:
            self.btn_pin.setEnabled(True)
            if self.is_pinned:
                set_window_stay_on_top(self, True)
            self.btn_pin.setToolTip(tr("Always on top (click to disable)") if self.is_pinned else tr("Not on top (click to enable)"))
        else:
            self.btn_pin.setEnabled(False)
            self.btn_pin.setToolTip(tr("Docked in main window (pin available when floating)"))

    def _toggle_stay_on_top(self, checked):
        """动态切换窗口置顶状态（0 闪烁无感切换）"""
        self.is_pinned = checked
        if self.isFloating():
            set_window_stay_on_top(self, checked)
        if checked:
            if hasattr(self, "_icon_pin_on") and not self._icon_pin_on.isNull():
                self.btn_pin.setIcon(self._icon_pin_on)
            self.btn_pin.setToolTip(tr("Always on top (click to disable)"))
        else:
            if hasattr(self, "_icon_pin_off") and not self._icon_pin_off.isNull():
                self.btn_pin.setIcon(self._icon_pin_off)
            self.btn_pin.setToolTip(tr("Not on top (click to enable)"))

    def keyPressEvent(self, event):
        """Esc 键退出格式刷"""
        if event.key() == Qt.Key_Escape:
            self.close()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _on_layer_changed(self, layer):
        """当主界面激活图层切换时，刷新控制台并避免引用已销毁图层"""
        self.layer = layer
        self._load_fields()

    def _load_fields(self):
        self.combo_field.blockSignals(True)
        self.combo_field.clear()
        self.layer = self.iface.activeLayer()

        if not self.layer or not isinstance(self.layer, QgsVectorLayer) or not self.layer.isValid():
            self.combo_field.addItem(tr("(no valid vector layer selected)"))
            self.combo_field.blockSignals(False)
            self.combo_val.blockSignals(True)
            self.combo_val.clear()
            self.combo_val.blockSignals(False)
            self.painter_tool.set_target(None, None)
            self.lbl_status.setText(tr("Status: pick a field and value first"))
            return

        fields = AttributeEngine.get_editable_fields(self.layer)
        for f in fields:
            self.combo_field.addItem(f.get("icon", QIcon()), f['name'], f['name'])

        # 优先选中上次使用的字段或配置字段
        fp_cfg = self.config.get("format_painter", {})
        default_field = (
            fp_cfg.get("field_name")
            or self.config.get("single_rank_by_layer", {}).get(self.layer.id())
            or self.config.get("single_rank", {}).get("field_name")
        )
        if default_field:
            idx = self.combo_field.findData(default_field)
            if idx != -1:
                self.combo_field.setCurrentIndex(idx)

        self.combo_field.blockSignals(False)
        self._on_field_changed()

    def _on_sort_alpha_clicked(self):
        """点击首字母排序按钮：在 A->Z 与 Z->A 间翻转，并互斥取消频次排序"""
        if self.current_sort_dim != "alpha":
            self.current_sort_dim = "alpha"
            self.btn_sort_alpha.setChecked(True)
            self.btn_sort_freq.setChecked(False)
        else:
            self.sort_alpha_dir = "desc" if self.sort_alpha_dir == "asc" else "asc"
            self.btn_sort_alpha.setChecked(True)

        if self.sort_alpha_dir == "asc":
            self.btn_sort_alpha.setIcon(self._icon_alpha_asc)
            self.btn_sort_alpha.setToolTip(tr("Alphabetical Ascending (A -> Z)"))
        else:
            self.btn_sort_alpha.setIcon(self._icon_alpha_desc)
            self.btn_sort_alpha.setToolTip(tr("Alphabetical Descending (Z -> A)"))

        self._populate_val_combo()

    def _on_sort_freq_clicked(self):
        """点击频次排序按钮：在 多->少 与 少->多 间翻转，并互斥取消字母排序"""
        if self.current_sort_dim != "freq":
            self.current_sort_dim = "freq"
            self.btn_sort_freq.setChecked(True)
            self.btn_sort_alpha.setChecked(False)
        else:
            self.sort_freq_dir = "asc" if self.sort_freq_dir == "desc" else "desc"
            self.btn_sort_freq.setChecked(True)

        if self.sort_freq_dir == "desc":
            self.btn_sort_freq.setIcon(self._icon_freq_desc)
            self.btn_sort_freq.setToolTip(tr("Frequency Descending (Most frequent first)"))
        else:
            self.btn_sort_freq.setIcon(self._icon_freq_asc)
            self.btn_sort_freq.setToolTip(tr("Frequency Ascending (Least frequent first)"))

        self._populate_val_combo()

    def _extract_current_value(self) -> str:
        """从可编辑下拉框中提取真实目标属性值（优先尊重用户在输入框中手动输入的文本）"""
        txt = self.combo_val.currentText().strip()
        empty_placeholder = tr("(no values yet in this layer)")
        add_custom_label = "➕ " + tr("Enter a new value...")
        null_label = "∅ " + tr("Set to NULL (Clear field)")
        if txt in ("", empty_placeholder, add_custom_label):
            return ""
        if txt == null_label or txt.upper() == "NULL" or self.combo_val.currentData() == "__set_null_value__":
            return "__NULL__"
        return txt

    def _on_field_changed(self):
        fname = self.combo_field.currentData()
        self._cached_val_counts = []
        if self.layer and isinstance(self.layer, QgsVectorLayer) and self.layer.isValid() and fname:
            self._cached_val_counts = AttributeEngine.extract_unique_values_with_counts(self.layer, fname)
        self._populate_val_combo(initial_load=True)

    def _populate_val_combo(self, initial_load=False):
        current_text = self._extract_current_value()
        self.combo_val.blockSignals(True)
        self.combo_val.clear()
        self._prev_val_idx = 0

        val_counts = list(self._cached_val_counts) if hasattr(self, "_cached_val_counts") else []

        # 排序计算（支持自然序及频次同频自然序）
        if self.current_sort_dim == "freq":
            if self.sort_freq_dir == "desc":
                val_counts_sorted = sorted(
                    val_counts,
                    key=lambda x: (-(x[1] if x[1] is not None else 0), AttributeEngine.natural_sort_key(x[0]))
                )
            else:
                val_counts_sorted = sorted(
                    val_counts,
                    key=lambda x: ((x[1] if x[1] is not None else 0), AttributeEngine.natural_sort_key(x[0]))
                )
        else:
            rev = (self.sort_alpha_dir == "desc")
            val_counts_sorted = sorted(val_counts, key=lambda x: AttributeEngine.natural_sort_key(x[0]), reverse=rev)

        has_values = False
        for val, cnt in val_counts_sorted:
            if AttributeEngine.is_empty_or_null(val):
                continue
            display_str = str(val)
            self.combo_val.addItem(display_str, userData=str(val))
            has_values = True

        if not has_values:
            self.combo_val.addItem(tr("(no values yet in this layer)"), userData="")

        # 添加「输入新值...」选项
        self.combo_val.addItem("➕ " + tr("Enter a new value..."), userData="__custom_add_value__")
        # 添加「设为 NULL / 清空字段」选项
        self.combo_val.addItem("∅ " + tr("Set to NULL (Clear field)"), userData="__set_null_value__")

        # 保持或恢复选中项
        matched = False
        if not initial_load and current_text:
            if current_text == "__NULL__":
                idx = self.combo_val.findData("__set_null_value__")
                if idx != -1:
                    self.combo_val.setCurrentIndex(idx)
                    self._prev_val_idx = idx
                    matched = True
            else:
                idx = self.combo_val.findData(current_text)
                if idx != -1:
                    self.combo_val.setCurrentIndex(idx)
                    self._prev_val_idx = idx
                    matched = True
                else:
                    self.combo_val.setEditText(current_text)
                    matched = True
        elif initial_load:
            fp_cfg = self.config.get("format_painter", {})
            last_field = fp_cfg.get("field_name")
            last_val = fp_cfg.get("value")
            cur_field = self.combo_field.currentData()
            if last_val:
                idx = self.combo_val.findData(str(last_val))
                if idx != -1:
                    self.combo_val.setCurrentIndex(idx)
                    self._prev_val_idx = idx
                    matched = True
                elif last_field and last_field == cur_field:
                    # 同一字段下用户曾自定义输入过尚未写入图层的候选值，予以保留
                    insert_pos = max(0, self.combo_val.count() - 1)
                    self.combo_val.insertItem(insert_pos, str(last_val), userData=str(last_val))
                    self.combo_val.setCurrentIndex(insert_pos)
                    self._prev_val_idx = insert_pos
                    matched = True

        if not matched:
            if has_values:
                self.combo_val.setCurrentIndex(0)
                self._prev_val_idx = 0
            else:
                self.combo_val.setCurrentIndex(0)
                self.combo_val.setEditText("")
                self._prev_val_idx = 0

        self.combo_val.blockSignals(False)
        self._sync_target_to_tool()

    def _on_val_index_changed(self, idx):
        if idx < 0:
            return
        data = self.combo_val.itemData(idx)
        if data == "__custom_add_value__":
            fname = self.combo_field.currentData() or ""
            new_val, ok = QInputDialog.getText(
                self,
                tr("Add New Attribute Value"),
                tr("Enter new value for [{0}]:").format(fname)
            )
            if ok:
                clean_val = new_val.strip()
                if clean_val == "" or clean_val.upper() == "NULL":
                    # 自动规整为 NULL
                    self.combo_val.blockSignals(True)
                    null_idx = self.combo_val.findData("__set_null_value__")
                    if null_idx != -1:
                        self.combo_val.setCurrentIndex(null_idx)
                    self.combo_val.setEditText("NULL")
                    self._prev_val_idx = self.combo_val.currentIndex()
                    self.combo_val.blockSignals(False)
                    self._sync_target_to_tool()
                else:
                    found_idx = -1
                    for i in range(self.combo_val.count()):
                        if self.combo_val.itemData(i) == clean_val:
                            found_idx = i
                            break
                    self.combo_val.blockSignals(True)
                    if found_idx != -1:
                        self.combo_val.setCurrentIndex(found_idx)
                    else:
                        insert_pos = max(0, self.combo_val.count() - 2)
                        self.combo_val.insertItem(insert_pos, clean_val, userData=clean_val)
                        self.combo_val.setCurrentIndex(insert_pos)
                    self._prev_val_idx = self.combo_val.currentIndex()
                    self.combo_val.blockSignals(False)
                    self._sync_target_to_tool()
            else:
                # 用户取消输入，平滑恢复回之前的选择
                self.combo_val.blockSignals(True)
                self.combo_val.setCurrentIndex(self._prev_val_idx)
                self.combo_val.blockSignals(False)
        elif data == "__set_null_value__":
            self.combo_val.blockSignals(True)
            self.combo_val.setEditText("NULL")
            self.combo_val.blockSignals(False)
            self._prev_val_idx = idx
            self._sync_target_to_tool()
        elif data == "":
            # 选中了「暂无候选值」占位项时清空输入框，避免占位文字被当成属性值
            self.combo_val.blockSignals(True)
            self.combo_val.setEditText("")
            self.combo_val.blockSignals(False)
            self._prev_val_idx = idx
            self._sync_target_to_tool()
        else:
            self._prev_val_idx = idx
            self._sync_target_to_tool()

    def _on_value_changed(self, text):
        self._sync_target_to_tool()

    def _sync_target_to_tool(self):
        """毫秒级即时同步当前选中的字段与值给画笔地图工具（即使值为空也同步字段，确保吸管可用且不残留旧字段）"""
        fname = self.combo_field.currentData()
        if not fname:
            self.painter_tool.set_target(None, None, is_null=False)
            self.lbl_status.setText(tr("Status: pick a field and value first"))
            return

        if self.combo_val.currentData() == "__custom_add_value__" and self.combo_val.currentText().startswith("➕"):
            return

        val = self._extract_current_value()
        if val == "__NULL__":
            self.painter_tool.set_target(fname, None, is_null=True)
            self.lbl_status.setText(tr("Painting: [{0} = NULL] (clear field)").format(fname))
        elif val != "":
            self.painter_tool.set_target(fname, val, is_null=False)
            self.lbl_status.setText(tr("Painting: [{0} = {1}]").format(fname, val))
        else:
            self.painter_tool.set_target(None, None, is_null=False)
            self.lbl_status.setText(tr("Status: pick a field and value first"))

    def _on_set_null_clicked(self):
        """点击面板底部的【设为 NULL / 清空】快捷按钮"""
        fname = self.combo_field.currentData()
        if not fname or not self.layer or not self.layer.isValid():
            return

        # 1. 将画笔和下拉框置为 NULL 模式
        self.combo_val.blockSignals(True)
        idx = self.combo_val.findData("__set_null_value__")
        if idx != -1:
            self.combo_val.setCurrentIndex(idx)
        self.combo_val.setEditText("NULL")
        self._prev_val_idx = self.combo_val.currentIndex()
        self.combo_val.blockSignals(False)
        self._sync_target_to_tool()

        # 2. 若当前地图图层中已有被选中的要素，立即批量将它们置为 NULL
        if self.layer.selectedFeatureCount() > 0:
            auto_edit = ConfigManager.get_config().get("behavior", {}).get("auto_start_editing", True)
            count, msg = AttributeEngine.batch_update_single_field(
                self.layer, fname, None, auto_start_editing=auto_edit
            )
            self.iface.messageBar().pushInfo("QuickFieldBrush", msg)
        else:
            self.lbl_status.setText(tr("Painting: [{0} = NULL] (clear field)").format(fname))

    def _toggle_pick_mode(self):
        """进入/退出吸管模式，或者直接从已选要素吸取"""
        self.layer = self.iface.activeLayer()
        if not self.layer or not isinstance(self.layer, QgsVectorLayer) or not self.layer.isValid():
            self.iface.messageBar().pushWarning(
                tr("QuickFieldBrush Format Painter"),
                tr("Please select a valid vector layer in the Layers panel first!"))
            return

        # 若当前恰好选中了单个要素，优先直接吸取该要素值
        if self.layer.selectedFeatureCount() == 1:
            feat = next(self.layer.getSelectedFeatures(), None)
            if feat:
                fname = self.combo_field.currentData()
                if fname:
                    fidx = feat.fields().indexOf(fname)
                    if fidx != -1:
                        val = feat.attribute(fidx)
                        self._on_feature_absorbed_from_map(fname, val, feat.id())
                        return

        # 否则切换地图单击吸取模式（光标变为十字吸管，在地图上点哪个要素就吸哪个要素）
        if getattr(self.painter_tool, "is_picking_mode", False):
            self.painter_tool.set_picking_mode(False)
            self._reset_absorb_btn_text()
            self._sync_target_to_tool()
        else:
            self.painter_tool.set_picking_mode(True)
            self.btn_pick_from_selected.setText(tr("🔍 Click any feature on map to absorb value..."))
            fname = self.combo_field.currentData() or ""
            self.lbl_status.setText(tr("Absorb mode: click any feature on map to pick [{0}]").format(fname))

    def _reset_absorb_btn_text(self):
        self.btn_pick_from_selected.setText(tr("Absorb attribute from feature"))

    def _on_feature_absorbed_from_map(self, field_name, val, feat_id):
        """地图要素被吸取时的回调：更新属性值下拉框，并恢复格式刷状态"""
        self._reset_absorb_btn_text()

        self.combo_val.blockSignals(True)
        if AttributeEngine.is_empty_or_null(val):
            null_idx = self.combo_val.findData("__set_null_value__")
            if null_idx != -1:
                self.combo_val.setCurrentIndex(null_idx)
            self.combo_val.setEditText("NULL")
            self._prev_val_idx = self.combo_val.currentIndex()
            self.combo_val.blockSignals(False)
            self._sync_target_to_tool()
            self.lbl_status.setText(tr("Absorbed FID {0}: [{1} = NULL] (ready to paint)").format(feat_id, field_name))
        else:
            val_str = str(val).strip()
            # 在下拉框中选中或添加该吸取值
            found_idx = -1
            for i in range(self.combo_val.count()):
                if self.combo_val.itemData(i) == val_str or self.combo_val.itemText(i) == val_str:
                    found_idx = i
                    break
            if found_idx != -1:
                self.combo_val.setCurrentIndex(found_idx)
            else:
                insert_pos = max(0, self.combo_val.count() - 2)
                self.combo_val.insertItem(insert_pos, val_str, userData=val_str)
                self.combo_val.setCurrentIndex(insert_pos)
            self._prev_val_idx = self.combo_val.currentIndex()
            self.combo_val.blockSignals(False)
            self._sync_target_to_tool()
            self.lbl_status.setText(tr("Absorbed FID {0}: [{1} = {2}] (ready to paint)").format(feat_id, field_name, val_str))

    def closeEvent(self, event):
        """窗口关闭时：持久化本次配置并退出格式刷模式"""
        if hasattr(self.painter_tool, "set_picking_mode"):
            self.painter_tool.set_picking_mode(False)
        self._reset_absorb_btn_text()

        fname = self.combo_field.currentData()
        val = self._extract_current_value()
        if fname and val:
            ConfigManager.update_section("format_painter", {"field_name": fname, "value": val})

        if self.iface.mapCanvas().mapTool() == self.painter_tool:
            self.iface.mapCanvas().unsetMapTool(self.painter_tool)
        super().closeEvent(event)


# 向后兼容别名
FormatPainterDialog = FormatPainterDockWidget

