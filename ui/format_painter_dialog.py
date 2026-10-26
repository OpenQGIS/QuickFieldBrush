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
    QComboBox, QPushButton, QLabel, QToolButton, QFrame
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.core import QgsVectorLayer
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

        self.setWindowTitle(tr("Attribute Format Painter (console)"))
        self.resize(360, 220)
        theme.apply_dialog_style(self)

        # 默认设为无模态 + 置顶
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._init_ui()
        self._load_fields()

        # 监听激活图层切换信号，动态同步当前可用字段，避免悬浮窗引用失效 C++ 对象
        self.iface.currentLayerChanged.connect(self._on_layer_changed)

        # 恢复上次使用的刷入值
        last_val = self.config.get("format_painter", {}).get("value")
        if last_val:
            self.combo_val.setEditText(str(last_val))

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 1. 顶部标题栏：置顶图钉 + 说明
        top_bar = QHBoxLayout()
        import os
        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")

        lbl_hint = QLabel(
            "<b>{}</b> ({})".format(
                tr("Format painter console"),
                tr("switch value anytime, instant effect on map")))
        lbl_hint.setStyleSheet(theme.LABEL_TITLE_SS)
        top_bar.addWidget(lbl_hint, 1)

        # 置顶切换按钮
        self.btn_pin = QToolButton()
        self.btn_pin.setCheckable(True)
        self.btn_pin.setChecked(True)
        pin_icon = QIcon(os.path.join(icons_dir, "pin.svg"))
        if not pin_icon.isNull():
            self.btn_pin.setIcon(pin_icon)
        self.btn_pin.setText(" " + tr("Always on top"))
        self.btn_pin.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_pin.setStyleSheet(theme.TOGGLE_ON_SS)
        self.btn_pin.toggled.connect(self._toggle_stay_on_top)
        top_bar.addWidget(self.btn_pin)

        layout.addLayout(top_bar)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # 2. 表单：目标字段 + 要刷属性值
        form = QFormLayout()
        form.setSpacing(8)

        self.combo_field = QComboBox()
        self.combo_field.currentIndexChanged.connect(self._on_field_changed)
        form.addRow("<b>{}</b>".format(tr("Target field:")), self.combo_field)

        self.combo_val = QComboBox()
        self.combo_val.setEditable(True)
        self.combo_val.lineEdit().setPlaceholderText(tr("Select or type the value to paint"))
        self.combo_val.currentTextChanged.connect(self._on_value_changed)
        form.addRow("<b>{}</b>".format(tr("Value to paint:")), self.combo_val)

        layout.addLayout(form)

        # 3. 吸取快捷按钮
        self.btn_pick_from_selected = QPushButton(tr("Absorb value from currently selected features"))
        absorb_icon = QIcon(os.path.join(icons_dir, "absorb.svg"))
        if not absorb_icon.isNull():
            self.btn_pick_from_selected.setIcon(absorb_icon)
        self.btn_pick_from_selected.setStyleSheet(theme.BUTTON_LINK_SS)
        self.btn_pick_from_selected.clicked.connect(self._pick_from_selected_feature)
        layout.addWidget(self.btn_pick_from_selected)

        layout.addStretch()

        # 4. 底部状态与退出说明条
        bottom_box = QHBoxLayout()
        self.lbl_status = QLabel(tr("Status: pick a field and value first"))
        self.lbl_status.setStyleSheet("font-weight: 600; color: %s;" % theme.ACCENT)
        bottom_box.addWidget(self.lbl_status, 1)

        self.btn_close = QPushButton(tr("Exit format painter (Esc)"))
        close_icon = QIcon(os.path.join(icons_dir, "clear.svg"))
        if not close_icon.isNull():
            self.btn_close.setIcon(close_icon)
        self.btn_close.setStyleSheet(theme.BUTTON_SECONDARY_SS)
        self.btn_close.clicked.connect(self.close)
        bottom_box.addWidget(self.btn_close)

        layout.addLayout(bottom_box)

    def _toggle_stay_on_top(self, checked):
        """动态切换窗口置顶状态"""
        self.is_pinned = checked
        if checked:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.btn_pin.setText(" " + tr("Always on top"))
            self.btn_pin.setStyleSheet(theme.TOGGLE_ON_SS)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
            self.btn_pin.setText(" " + tr("Not on top"))
            self.btn_pin.setStyleSheet(theme.TOGGLE_OFF_SS)
        self.show()  # 改变 windowFlags 后需要重新 show

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
            self.combo_field.addItem(f"{f['name']} ({f['typeName']})", f['name'])

        self.combo_field.blockSignals(False)

        # 优先选中上次使用的字段或配置字段
        fp_cfg = self.config.get("format_painter", {})
        default_field = fp_cfg.get("field_name") or self.config.get("single_rank", {}).get("field_name")
        if default_field:
            idx = self.combo_field.findData(default_field)
            if idx != -1:
                self.combo_field.setCurrentIndex(idx)

        self._on_field_changed()

    def _on_field_changed(self):
        fname = self.combo_field.currentData()
        self.combo_val.blockSignals(True)
        self.combo_val.clear()

        if not self.layer or not isinstance(self.layer, QgsVectorLayer) or not self.layer.isValid() or not fname:
            self.combo_val.blockSignals(False)
            return

        uniques = AttributeEngine.extract_unique_values(self.layer, fname, limit=100)
        for u in uniques:
            self.combo_val.addItem(str(u), userData=u)

        self.combo_val.blockSignals(False)

        # 默认选中第一个分类
        if uniques:
            self.combo_val.setCurrentIndex(0)
            self._sync_target_to_tool()

    def _on_value_changed(self, text):
        self._sync_target_to_tool()

    def _sync_target_to_tool(self):
        """毫秒级即时同步当前选中的字段与值给画笔地图工具"""
        fname = self.combo_field.currentData()
        val = self.combo_val.currentText().strip()
        if fname and val:
            self.painter_tool.set_target(fname, val)
            self.lbl_status.setText(tr("Painting: [{0} = {1}]").format(fname, val))

    def _pick_from_selected_feature(self):
        """从当前选中的要素直接吸取属性值"""
        self.layer = self.iface.activeLayer()
        if not self.layer or not isinstance(self.layer, QgsVectorLayer) or not self.layer.isValid():
            self.iface.messageBar().pushWarning(
                tr("QuickFieldBrush Format Painter"),
                tr("Please select a valid vector layer in the Layers panel first!"))
            return
        if self.layer.selectedFeatureCount() == 0:
            self.iface.messageBar().pushInfo(
                tr("QuickFieldBrush Format Painter"),
                tr("No selected features. Please select a feature on the map first, then absorb its value."))
            return

        fname = self.combo_field.currentData()
        if not fname:
            self.iface.messageBar().pushWarning(
                tr("QuickFieldBrush Format Painter"), tr("Please select a target field first!"))
            return

        feat = next(self.layer.getSelectedFeatures(), None)
        if feat is None:
            return

        fidx = feat.fields().indexOf(fname)
        if fidx == -1:
            return

        val = feat.attributes()[fidx]
        if val is None or str(val).strip() == "":
            self.iface.messageBar().pushInfo(
                tr("QuickFieldBrush Format Painter"),
                tr("The [{0}] value of the selected feature is empty and cannot be absorbed.").format(fname))
            return

        # setEditText 会经 currentTextChanged 自动同步给画笔工具
        self.combo_val.setEditText(str(val))

    def closeEvent(self, event):
        """窗口关闭时：断开图层监听、持久化本次配置并退出格式刷模式"""
        try:
            self.iface.currentLayerChanged.disconnect(self._on_layer_changed)
        except Exception:
            pass

        fname = self.combo_field.currentData()
        val = self.combo_val.currentText().strip()
        if fname and val:
            ConfigManager.update_section("format_painter", {"field_name": fname, "value": val})

        if self.iface.mapCanvas().mapTool() == self.painter_tool:
            self.iface.mapCanvas().unsetMapTool(self.painter_tool)
        super().closeEvent(event)
