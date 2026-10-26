# -*- coding: utf-8 -*-
"""
格式刷地图交互工具 (FormatPainterTool)：
1. 鼠标光标变为吸管/画笔样式
2. 用户在地图上点击任意要素，瞬间将绑定的 [field_name = target_value] 写入被点中的要素
3. 支持连续点击作业（点一个刷一个），并提供微型闪烁高亮反馈
4. 支持按 ESC 退出格式刷状态
"""

from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.core import (
    QgsWkbTypes,
    QgsRectangle,
    QgsCoordinateTransform,
    QgsProject,
    QgsVectorLayer,
    QgsFeatureRequest
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor
from .attribute_engine import AttributeEngine
from .history_manager import HistoryManager
from ..i18n_helper import tr


class FormatPainterTool(QgsMapTool):
    def __init__(self, canvas, iface, plugin):
        super().__init__(canvas)
        self.canvas = canvas
        self.iface = iface
        self.plugin = plugin

        self.target_field = None
        self.target_value = None

        # 瞬时高亮橡皮筋（点击要素后闪烁一下绿色表示刷入成功）
        self.flash_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self.flash_band.setColor(QColor(76, 175, 80, 120))
        self.flash_band.setStrokeColor(QColor(56, 142, 60, 255))
        self.flash_band.setWidth(2)

        self.setCursor(Qt.PointingHandCursor)

    def set_target(self, field_name, value):
        """设定当前画笔持有的字段与属性值（状态由常驻控制台面板自行展示，不再弹消息条）"""
        self.target_field = field_name
        self.target_value = value

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        if not self.target_field:
            return

        layer = self.canvas.currentLayer()
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            self.iface.messageBar().pushWarning(
                tr("QuickFieldBrush Format Painter"),
                tr("Please select a valid vector layer in the Layers panel first!"))
            return

        # 1. 构造微小屏幕容差矩形（8 像素）
        click_pt = self.toMapCoordinates(event.pos())
        pixel_tolerance = 8
        mu_tolerance = self.canvas.mapUnitsPerPixel() * pixel_tolerance
        search_rect = QgsRectangle(
            click_pt.x() - mu_tolerance, click_pt.y() - mu_tolerance,
            click_pt.x() + mu_tolerance, click_pt.y() + mu_tolerance
        )

        # 2. CRS 坐标转换（画布 CRS -> 图层 CRS）
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        if canvas_crs.isValid() and layer.crs().isValid() and canvas_crs != layer.crs():
            try:
                transform = QgsCoordinateTransform(canvas_crs, layer.crs(), QgsProject.instance())
                search_rect = transform.transformBoundingBox(search_rect)
            except Exception:
                pass

        # 3. 寻找命中的要素（FilterRect 走 provider 空间索引，避免全表遍历）
        hit_feature = None
        request = QgsFeatureRequest().setFilterRect(search_rect)
        for feat in layer.getFeatures(request):
            hit_feature = feat
            break

        if hit_feature is None:
            return

        # 4. 执行写入该要素
        fid = hit_feature.id()
        field_idx = layer.fields().indexOf(self.target_field)
        if field_idx == -1:
            self.iface.messageBar().pushWarning(
                tr("QuickFieldBrush Format Painter"),
                tr("Layer [{0}] has no field [{1}]; please reconfigure the format painter from the toolbar button.")
                .format(layer.name(), self.target_field))
            return

        if not layer.isEditable():
            if not layer.startEditing():
                self.iface.messageBar().pushWarning(
                    tr("QuickFieldBrush Format Painter"),
                    tr("Layer [{0}] cannot start editing!").format(layer.name()))
                return

        old_val = hit_feature.attribute(field_idx)
        layer.beginEditCommand(
            tr("QuickFieldBrush format painter: set {1}={2} on feature {0}")
            .format(fid, self.target_field, self.target_value))
        try:
            fld_obj = layer.fields().at(field_idx)
            val_to_write = AttributeEngine.convert_value_for_field(fld_obj, self.target_value)
            layer.changeAttributeValue(fid, field_idx, val_to_write)
            layer.endEditCommand()
            layer.triggerRepaint()
            AttributeEngine.invalidate_cache(layer)

            # 写入历史记录
            HistoryManager.instance().add_step(
                tool_type="painter",
                layer=layer,
                field_name=self.target_field,
                target_value=val_to_write,
                changes=[{"fid": fid, "old_val": old_val, "new_val": val_to_write}]
            )
        except Exception as e:
            layer.destroyEditCommand()
            self.iface.messageBar().pushWarning(
                "QuickFieldBrush", tr("Format painter assignment failed: {0}").format(str(e)))
            return

        # 5. 绿色瞬时高亮反馈（180ms 自动消失，独立于事务，避免 UI 反馈异常误触发回滚）
        try:
            self.flash_band.setToGeometry(hit_feature.geometry(), layer)
            self.flash_band.show()
            QTimer.singleShot(180, lambda: self.flash_band.reset())
        except Exception:
            pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            # 按 ESC 退出格式刷
            self.canvas.unsetMapTool(self)

    def deactivate(self):
        if self.flash_band:
            self.flash_band.reset()
        if self.plugin.action_painter and self.plugin.action_painter.isChecked():
            self.plugin.action_painter.setChecked(False)
        # 如果控制面板依然开着，同步关闭
        if self.plugin.painter_dialog and self.plugin.painter_dialog.isVisible():
            self.plugin.painter_dialog.close()
        super().deactivate()
