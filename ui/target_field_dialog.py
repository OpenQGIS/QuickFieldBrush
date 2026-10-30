# -*- coding: utf-8 -*-
"""
目标字段选择紧凑弹窗组件：
- 宽度统一控制在约 310px，拒绝长文本挤压变形
- 展示图层类型原生矢量图标与图层名（超长智能省略并附带 Tooltip）
- 目标字段下拉框完整展示 QGIS 原生 14 种字段类型图标
- 一键集成与复用，保持界面克制精致
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QFormLayout, QLabel, QComboBox,
    QDialogButtonBox, QHBoxLayout, QWidget
)
from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QFontMetrics
from qgis.core import QgsApplication
from ..core.attribute_engine import AttributeEngine
from ..core.compat import safe_exec
from ..i18n_helper import tr


class TargetFieldDialog(QDialog):
    """指定/切换目标字段专用紧凑对话框"""

    def __init__(self, parent=None, layer=None, valid_names=None, current_field=None):
        super().__init__(parent)
        self.layer = layer
        self.valid_names = valid_names or []
        self.current_field = current_field or ""

        self.setWindowTitle(tr("Specify Target Field"))
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setFixedWidth(310)

        self._init_ui()

    def _init_ui(self):
        lay = QFormLayout(self)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.setSpacing(10)

        # 1. 目标图层展示（带原生点/线/面几何图标）
        layer_widget = QWidget()
        layer_lay = QHBoxLayout(layer_widget)
        layer_lay.setContentsMargins(0, 0, 0, 0)
        layer_lay.setSpacing(6)

        if self.layer:
            geom_type = self.layer.geometryType()
            icon_map = {
                0: "mIconPointLayer.svg",
                1: "mIconLineLayer.svg",
                2: "mIconPolygonLayer.svg",
            }
            icon_name = icon_map.get(geom_type, "mIconTableLayer.svg")
            layer_icon = QgsApplication.getThemeIcon(icon_name)

            lbl_icon = QLabel()
            lbl_icon.setPixmap(layer_icon.pixmap(QSize(16, 16)))
            lbl_icon.setFixedSize(16, 16)
            layer_lay.addWidget(lbl_icon)

            lbl_layer = QLabel()
            fm = QFontMetrics(lbl_layer.font())
            elided_name = fm.elidedText(self.layer.name(), Qt.ElideMiddle, 190)
            lbl_layer.setText(elided_name)
            lbl_layer.setToolTip(self.layer.name())
            lbl_layer.setStyleSheet("font-weight: 500; color: #222222;")
            layer_lay.addWidget(lbl_layer)
        else:
            lbl_layer = QLabel("-")
            layer_lay.addWidget(lbl_layer)

        layer_lay.addStretch(1)
        lay.addRow(tr("Layer:"), layer_widget)

        # 2. 目标字段下拉列表（附带 14 种 QGIS 原生字段类型图标）
        self.cb_field = QComboBox()
        self.cb_field.setMinimumHeight(24)
        current_idx = 0
        for idx, name in enumerate(self.valid_names):
            ic = AttributeEngine.get_field_icon(self.layer, name) if self.layer else None
            if ic:
                self.cb_field.addItem(ic, name, name)
            else:
                self.cb_field.addItem(name, name)
            if name == self.current_field:
                current_idx = idx

        if 0 <= current_idx < self.cb_field.count():
            self.cb_field.setCurrentIndex(current_idx)

        lay.addRow(tr("Target Field:"), self.cb_field)

        # 3. 按钮栏
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_ok = btn_box.button(QDialogButtonBox.Ok)
        if btn_ok:
            btn_ok.setText(tr("OK"))
        btn_cancel = btn_box.button(QDialogButtonBox.Cancel)
        if btn_cancel:
            btn_cancel.setText(tr("Cancel"))

        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        lay.addRow(btn_box)

        self.adjustSize()

    def get_selected_field(self):
        """获取用户当前选中的字段名"""
        return self.cb_field.currentData() or self.cb_field.currentText()

    @classmethod
    def select_field(cls, parent, layer, valid_names, current_field=None):
        """便捷静态调用方法：成功返回选中的字段名，取消返回 None"""
        dlg = cls(parent, layer, valid_names, current_field)
        if safe_exec(dlg) == QDialog.Accepted:
            return dlg.get_selected_field()
        return None
