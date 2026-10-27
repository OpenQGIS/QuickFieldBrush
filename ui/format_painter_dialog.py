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
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QPushButton, QLabel, QToolButton, QFrame,
    QInputDialog
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt, pyqtSignal, QSize
from qgis.core import QgsVectorLayer
from ..core.compat import set_window_stay_on_top
from ..core.attribute_engine import AttributeEngine
from ..core.config_manager import ConfigManager
from ..i18n_helper import tr
from . import theme


class FormatPainterDialog(QDialog):
    targetChanged = pyqtSignal(str, str)  # 字段或属性值改变时通知画笔工具

    def __init__(self, iface, painter_tool, parent=None):
        super().__init__(parent)
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
        self.resize(360, 140)

        # 默认设为无模态 + 置顶
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._init_ui()
        self._load_fields()

        # 绑定地图工具的吸取回调
        if hasattr(self.painter_tool, "on_feature_picked"):
            self.painter_tool.on_feature_picked = self._on_feature_absorbed_from_map

        # 监听激活图层切换信号，动态同步当前可用字段，避免悬浮窗引用失效 C++ 对象
        self.iface.currentLayerChanged.connect(self._on_layer_changed)

        # 恢复上次使用的刷入值
        last_val = self.config.get("format_painter", {}).get("value")
        if last_val:
            self.combo_val.setEditText(str(last_val))

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 11, 11, 11)
        layout.setSpacing(8)

        import os
        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")

        # 1. 表单区域：目标字段（含右上置顶图钉） + 属性值（含排序按钮）
        form = QFormLayout()
        form.setSpacing(8)

        # 第一行：目标字段 + 右侧置顶图钉（位于界面右上角）
        field_box = QHBoxLayout()
        field_box.setSpacing(4)
        field_box.setContentsMargins(0, 0, 0, 0)

        self.combo_field = QComboBox()
        self.combo_field.currentIndexChanged.connect(self._on_field_changed)
        field_box.addWidget(self.combo_field, 1)

        # 置顶切换按钮（纯图标两态：激活显示绿图钉，未激活显示灰图钉，位于右上角）
        self.btn_pin = QToolButton()
        self.btn_pin.setFixedSize(24, 24)
        self.btn_pin.setCheckable(True)
        self.btn_pin.setChecked(True)
        self.btn_pin.setAutoRaise(True)
        self._icon_pin_on = QIcon(os.path.join(icons_dir, "pin_green.svg"))
        self._icon_pin_off = QIcon(os.path.join(icons_dir, "pin_grey.svg"))
        if not self._icon_pin_on.isNull():
            self.btn_pin.setIcon(self._icon_pin_on)
            self.btn_pin.setIconSize(QSize(15, 15))
        self.btn_pin.setToolTip(tr("Always on top (click to disable)"))
        self.btn_pin.toggled.connect(self._toggle_stay_on_top)
        field_box.addWidget(self.btn_pin)

        form.addRow(tr("Target field"), field_box)

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
        self.btn_sort_alpha.setFixedSize(24, 24)
        self.btn_sort_alpha.setCheckable(True)
        self.btn_sort_alpha.setChecked(False)
        self.btn_sort_alpha.setAutoRaise(True)
        self.btn_sort_alpha.setIcon(self._icon_alpha_asc)
        self.btn_sort_alpha.setIconSize(QSize(16, 16))
        self.btn_sort_alpha.setToolTip(tr("Alphabetical Ascending (A -> Z)"))
        self.btn_sort_alpha.clicked.connect(self._on_sort_alpha_clicked)
        val_box.addWidget(self.btn_sort_alpha)

        # 排序按钮 2：频次维 (多->少 / 少->多 两态翻转，默认激活高频优先)
        self._icon_freq_desc = QIcon(os.path.join(icons_dir, "sort-dscend.svg"))
        self._icon_freq_asc = QIcon(os.path.join(icons_dir, "sort-ascend.svg"))
        self.btn_sort_freq = QToolButton()
        self.btn_sort_freq.setFixedSize(24, 24)
        self.btn_sort_freq.setCheckable(True)
        self.btn_sort_freq.setChecked(True)
        self.btn_sort_freq.setAutoRaise(True)
        self.btn_sort_freq.setIcon(self._icon_freq_desc)
        self.btn_sort_freq.setIconSize(QSize(16, 16))
        self.btn_sort_freq.setToolTip(tr("Frequency Descending (Most frequent first)"))
        self.btn_sort_freq.clicked.connect(self._on_sort_freq_clicked)
        val_box.addWidget(self.btn_sort_freq)

        form.addRow(tr("Attribute value"), val_box)

        layout.addLayout(form)

        # 2. 第三行：当前刷入状态提示
        self.lbl_status = QLabel(tr("Status: pick a field and value first"))
        layout.addWidget(self.lbl_status)

        layout.addSpacing(2)

        # 3. 最下边的一行：左侧为吸取属性，右边为退出按钮
        bottom_box = QHBoxLayout()
        bottom_box.setSpacing(8)

        self.btn_pick_from_selected = QPushButton(tr("Absorb attribute from feature"))
        absorb_icon = QIcon(os.path.join(icons_dir, "absorb.svg"))
        if not absorb_icon.isNull():
            self.btn_pick_from_selected.setIcon(absorb_icon)
            self.btn_pick_from_selected.setIconSize(QSize(15, 15))
        self.btn_pick_from_selected.setToolTip(tr("Click to enter eyedropper mode, or right-click any feature on map to absorb its value"))
        self.btn_pick_from_selected.clicked.connect(self._toggle_pick_mode)
        bottom_box.addWidget(self.btn_pick_from_selected, 1)

        self.btn_close = QPushButton(tr("Exit format painter (Esc)"))
        self.btn_close.clicked.connect(self.close)
        bottom_box.addWidget(self.btn_close, 1)

        layout.addLayout(bottom_box)

    def _toggle_stay_on_top(self, checked):
        """动态切换窗口置顶状态（0 闪烁无感切换）"""
        self.is_pinned = checked
        set_window_stay_on_top(self, checked)
        if checked:
            if hasattr(self, "_icon_pin_on") and not self._icon_pin_on.isNull():
                self.btn_pin.setIcon(self._icon_pin_on)
            self.btn_pin.setToolTip(tr("Always on top (click to disable)"))
        else:
            if hasattr(self, "_icon_pin_off") and not self._icon_pin_off.isNull():
                self.btn_pin.setIcon(self._icon_pin_off)
            self.btn_pin.setToolTip(tr("Not on top (click to enable)"))

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
            self.lbl_status.setText(tr("Status: pick a field and value first"))
            return

        fields = AttributeEngine.get_editable_fields(self.layer)
        for f in fields:
            self.combo_field.addItem(f.get("icon", QIcon()), f['name'], f['name'])

        self.combo_field.blockSignals(False)

        # 优先选中上次使用的字段或配置字段
        fp_cfg = self.config.get("format_painter", {})
        default_field = fp_cfg.get("field_name") or self.config.get("single_rank", {}).get("field_name")
        if default_field:
            idx = self.combo_field.findData(default_field)
            if idx != -1:
                self.combo_field.setCurrentIndex(idx)

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

    def _on_field_changed(self):
        fname = self.combo_field.currentData()
        self._cached_val_counts = []
        if self.layer and isinstance(self.layer, QgsVectorLayer) and self.layer.isValid() and fname:
            self._cached_val_counts = AttributeEngine.extract_unique_values_with_counts(self.layer, fname)
        self._populate_val_combo(initial_load=True)

    def _populate_val_combo(self, initial_load=False):
        current_text = self.combo_val.currentText().strip()
        self.combo_val.blockSignals(True)
        self.combo_val.clear()
        self._prev_val_idx = 0

        val_counts = list(self._cached_val_counts) if hasattr(self, "_cached_val_counts") else []

        # 排序计算
        if self.current_sort_dim == "freq":
            rev = (self.sort_freq_dir == "desc")
            val_counts_sorted = sorted(val_counts, key=lambda x: (x[1] if x[1] is not None else 0), reverse=rev)
        else:
            rev = (self.sort_alpha_dir == "desc")
            val_counts_sorted = sorted(val_counts, key=lambda x: str(x[0]).lower(), reverse=rev)

        has_values = False
        for val, cnt in val_counts_sorted:
            if val is None or str(val).strip() == "":
                continue
            display_str = str(val)
            self.combo_val.addItem(display_str, userData=str(val))
            has_values = True

        if not has_values:
            self.combo_val.addItem(tr("(no values yet in this layer)"), userData="")

        # 添加「输入新值...」选项
        self.combo_val.addItem("➕ " + tr("Enter a new value..."), userData="__custom_add_value__")
        self.combo_val.blockSignals(False)

        # 保持或恢复选中项
        matched = False
        if not initial_load and current_text:
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
            last_val = fp_cfg.get("value")
            if last_val:
                idx = self.combo_val.findData(str(last_val))
                if idx != -1:
                    self.combo_val.setCurrentIndex(idx)
                    self._prev_val_idx = idx
                    matched = True

        if not matched and has_values:
            self.combo_val.setCurrentIndex(0)
            self._prev_val_idx = 0

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
            if ok and new_val.strip():
                clean_val = new_val.strip()
                # 检查下拉列表中是否已有该值
                found_idx = -1
                for i in range(self.combo_val.count()):
                    if self.combo_val.itemData(i) == clean_val:
                        found_idx = i
                        break
                if found_idx != -1:
                    self.combo_val.setCurrentIndex(found_idx)
                else:
                    insert_pos = max(0, self.combo_val.count() - 1)
                    self.combo_val.insertItem(insert_pos, clean_val, userData=clean_val)
                    self.combo_val.setCurrentIndex(insert_pos)
                self._prev_val_idx = self.combo_val.currentIndex()
                self._sync_target_to_tool()
            else:
                # 用户取消输入，平滑恢复回之前的选择
                self.combo_val.blockSignals(True)
                self.combo_val.setCurrentIndex(self._prev_val_idx)
                self.combo_val.blockSignals(False)
        else:
            self._prev_val_idx = idx
            self._sync_target_to_tool()

    def _on_value_changed(self, text):
        self._sync_target_to_tool()

    def _sync_target_to_tool(self):
        """毫秒级即时同步当前选中的字段与值给画笔地图工具"""
        fname = self.combo_field.currentData()
        data = self.combo_val.currentData()
        if data == "__custom_add_value__":
            return

        if data is not None and data != "":
            val = str(data)
        else:
            val = self.combo_val.currentText().strip()

        if fname and val:
            self.painter_tool.set_target(fname, val)
            self.lbl_status.setText(tr("Painting: [{0} = {1}]").format(fname, val))

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
        val_str = "" if val is None else str(val).strip()

        # 在下拉框中选中或添加该吸取值
        found_idx = -1
        for i in range(self.combo_val.count()):
            if self.combo_val.itemData(i) == val_str or self.combo_val.itemText(i) == val_str:
                found_idx = i
                break
        if found_idx != -1:
            self.combo_val.setCurrentIndex(found_idx)
        else:
            insert_pos = max(0, self.combo_val.count() - 1)
            self.combo_val.insertItem(insert_pos, val_str, userData=val_str)
            self.combo_val.setCurrentIndex(insert_pos)

        self._prev_val_idx = self.combo_val.currentIndex()
        self._sync_target_to_tool()
        self.lbl_status.setText(tr("Absorbed FID {0}: [{1} = {2}] (ready to paint)").format(feat_id, field_name, val_str))

    def closeEvent(self, event):
        """窗口关闭时：断开图层监听、持久化本次配置并退出格式刷模式"""
        try:
            self.iface.currentLayerChanged.disconnect(self._on_layer_changed)
        except (TypeError, RuntimeError, AttributeError):
            pass

        if hasattr(self.painter_tool, "set_picking_mode"):
            self.painter_tool.set_picking_mode(False)

        fname = self.combo_field.currentData()
        data = self.combo_val.currentData()
        if data and data != "__custom_add_value__":
            val = str(data).strip()
        else:
            val = self.combo_val.currentText().strip()
        if fname and val:
            ConfigManager.update_section("format_painter", {"field_name": fname, "value": val})

        if self.iface.mapCanvas().mapTool() == self.painter_tool:
            self.iface.mapCanvas().unsetMapTool(self.painter_tool)
        super().closeEvent(event)
