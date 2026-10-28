# -*- coding: utf-8 -*-
"""
格式刷地图交互工具 (FormatPainterTool)：
1. 继承自 QgsMapToolIdentify，接入 QGIS 原生地图识别与 High-DPI 校准体系
2. 鼠标光标统一为精准十字准星（CrossCursor），消除手形光标热点瞄准错觉
3. 支持 TopDownAll 候选要素几何距离最小优选，彻底杜绝相邻平行线误选
4. 用户在地图上点击任意要素，瞬间将绑定的 [field_name = target_value] 写入被点中的要素
5. 完整支持 NULL 值清空刷入与真假空值智能吸取
6. 支持连续点击作业（点一个刷一个），点/线/面几何自适应微型闪烁高亮反馈
7. 支持按 ESC 退出格式刷状态
"""

from qgis.gui import QgsMapToolIdentify, QgsRubberBand
from qgis.core import (
    QgsWkbTypes,
    QgsRectangle,
    QgsCoordinateTransform,
    QgsCsException,
    QgsProject,
    QgsVectorLayer,
    QgsFeatureRequest,
    QgsGeometry
)
from qgis.PyQt.QtCore import Qt, QTimer, QPoint
from qgis.PyQt.QtGui import QColor, QCursor
from .attribute_engine import AttributeEngine
from .config_manager import ConfigManager
from .history_manager import HistoryManager
from ..i18n_helper import tr


class FormatPainterTool(QgsMapToolIdentify):
    def __init__(self, canvas, iface, plugin):
        super().__init__(canvas)
        self.canvas = canvas
        self.iface = iface
        self.plugin = plugin

        self.target_field = None
        self.target_value = None
        self.is_target_null = False
        self.is_picking_mode = False
        self.on_feature_picked = None  # 回调通知面板: fn(field_name, val_str, feat_id)

        # 瞬时高亮橡皮筋（点击要素后闪烁一下绿色表示刷入成功，几何类型动态自适应）
        self.flash_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self.flash_band.setColor(QColor(76, 175, 80, 120))
        self.flash_band.setStrokeColor(QColor(56, 142, 60, 255))
        self.flash_band.setWidth(2)

        # 瞬时吸取高亮橡皮筋（吸取要素后闪烁一下优雅蓝色）
        self.absorb_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self.absorb_band.setColor(QColor(37, 99, 235, 120))
        self.absorb_band.setStrokeColor(QColor(29, 78, 216, 255))
        self.absorb_band.setWidth(2)

        # 独立复用的单次定时器，避免快速连续点击时前一次定时器提前清空当前高亮
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self.flash_band.reset)

        self._absorb_timer = QTimer(self)
        self._absorb_timer.setSingleShot(True)
        self._absorb_timer.timeout.connect(self.absorb_band.reset)

        cross_cursor = getattr(Qt.CursorShape, "CrossCursor", getattr(Qt, "CrossCursor", None))
        self.setCursor(QCursor(cross_cursor) if cross_cursor is not None else QCursor())

    def set_target(self, field_name, value, is_null: bool = False):
        """设定当前画笔持有的字段与属性值（状态由常驻控制台面板自行展示，不再弹消息条）"""
        self.target_field = field_name
        self.target_value = value
        self.is_target_null = is_null or (value is not None and str(value).strip().upper() == "NULL")

    def set_picking_mode(self, enabled):
        """切换是否处于吸管吸取模式"""
        self.is_picking_mode = enabled
        cross_cursor = getattr(Qt.CursorShape, "CrossCursor", getattr(Qt, "CrossCursor", None))
        self.setCursor(QCursor(cross_cursor) if cross_cursor is not None else QCursor())

    def _find_target_feature(self, layer: QgsVectorLayer, event):
        """
        高精度要素识别引擎：
        1. 优先使用 QGIS 原生识别引擎（QgsMapToolIdentify.identify）：
           原生底层自动处理 macOS Retina / Windows 4K 高分屏倍率、地图坐标系转换与精确相交；
        2. 使用 TopDownAll 获取搜索半径内的所有候选要素，通过几何欧氏距离精细计算，优先匹配最近位置要素；
           面要素按面积升序匹配（嵌套图斑优先选取最小图斑要素）；
        3. 若原生识别因容差微小未命中，使用屏幕 12 像素容差缓冲区进行备用容差补刀查找。
        """
        results = self.identify(event.x(), event.y(), [layer], self.TopDownAll)

        map_pt = event.mapPoint() if hasattr(event, "mapPoint") else self.toMapCoordinates(event.pos())
        click_layer_pt = self.toLayerCoordinates(layer, map_pt)
        click_geom = QgsGeometry.fromPointXY(click_layer_pt)
        is_polygon = (layer.geometryType() == QgsWkbTypes.PolygonGeometry)

        if results:
            if len(results) == 1:
                return results[0].mFeature

            def _sort_key(res):
                feat = res.mFeature
                geom = feat.geometry()
                if geom.isEmpty():
                    return (float('inf'), float('inf'))
                dist = geom.distance(click_geom)
                if is_polygon and dist == 0:
                    return (0, geom.area())
                return (dist, 0)

            best_res = min(results, key=_sort_key)
            return best_res.mFeature

        # 备用容差查找（应对高分辨率微小细线或复杂坐标系单位转换）
        p0 = event.pos()
        p1 = p0 + QPoint(12, 0)
        pt0 = self.toLayerCoordinates(layer, p0)
        pt1 = self.toLayerCoordinates(layer, p1)
        tolerance = pt0.distance(pt1)

        search_rect = QgsRectangle(
            click_layer_pt.x() - tolerance, click_layer_pt.y() - tolerance,
            click_layer_pt.x() + tolerance, click_layer_pt.y() + tolerance
        )
        request = QgsFeatureRequest().setFilterRect(search_rect)

        best_feat = None
        min_dist = float('inf')
        best_area = float('inf')

        for feat in layer.getFeatures(request):
            geom = feat.geometry()
            if geom.isEmpty():
                continue
            dist = geom.distance(click_geom)
            if dist <= tolerance:
                if is_polygon and dist == 0:
                    area = geom.area()
                    if area < best_area:
                        best_area = area
                        best_feat = feat
                        min_dist = 0
                elif dist < min_dist:
                    min_dist = dist
                    best_feat = feat

        return best_feat

    def canvasReleaseEvent(self, event):
        if event.button() not in (Qt.LeftButton, Qt.RightButton):
            return

        if not self.target_field:
            return

        layer = self.canvas.currentLayer()
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            self.iface.messageBar().pushWarning(
                tr("QuickFieldBrush Format Painter"),
                tr("Please select a valid vector layer in the Layers panel first!"))
            return

        # 判断是否为吸取操作：
        # 1. 处于吸管吸取模式；
        # 2. 或按下了鼠标右键（右键极速吸取）；
        # 3. 或按住了 Alt / Ctrl 键单击
        is_absorb = (
            self.is_picking_mode or
            event.button() == Qt.RightButton or
            bool(event.modifiers() & (Qt.AltModifier | Qt.ControlModifier))
        )

        hit_feature = self._find_target_feature(layer, event)
        if hit_feature is None:
            return

        fid = hit_feature.id()
        field_idx = layer.fields().indexOf(self.target_field)
        if field_idx == -1:
            self.iface.messageBar().pushWarning(
                tr("QuickFieldBrush Format Painter"),
                tr("Layer [{0}] has no field [{1}]; please reconfigure the format painter from the toolbar button.")
                .format(layer.name(), self.target_field))
            return

        # ---- 分支 A：吸取属性模式 (只读要素值写入面板，绝不修改要素) ----
        if is_absorb:
            raw_val = hit_feature.attribute(field_idx)
            val_str = "" if AttributeEngine.is_null_value(raw_val) else str(raw_val).strip()

            # 蓝色瞬时高亮反馈（点/线/面自适应）
            try:
                self._absorb_timer.stop()
                self.absorb_band.reset(layer.geometryType())
                self.absorb_band.setToGeometry(hit_feature.geometry(), layer)
                self.absorb_band.show()
                self._absorb_timer.start(250)
            except (RuntimeError, TypeError, AttributeError):
                pass

            # 退出单次吸取模式，恢复光标
            self.set_picking_mode(False)

            # 回调控制台面板同步更新【要刷属性值】
            if callable(self.on_feature_picked):
                self.on_feature_picked(self.target_field, val_str, fid)
            return

        # ---- 分支 B：常规赋值刷入模式 ----
        if not self.is_target_null and (self.target_value is None or str(self.target_value).strip() == ""):
            self.iface.messageBar().pushInfo(
                tr("QuickFieldBrush Format Painter"),
                tr("Status: pick a field and value first"))
            return

        auto_edit = ConfigManager.get_config().get("behavior", {}).get("auto_start_editing", True)
        if not layer.isEditable():
            if auto_edit:
                if not layer.startEditing():
                    self.iface.messageBar().pushWarning(
                        tr("QuickFieldBrush Format Painter"),
                        tr("Layer [{0}] cannot start editing!").format(layer.name()))
                    return
            else:
                self.iface.messageBar().pushWarning(
                    tr("QuickFieldBrush Format Painter"),
                    tr("Layer is not in edit mode"))
                return

        old_val = hit_feature.attribute(field_idx)
        display_val = "NULL" if self.is_target_null else str(self.target_value)
        layer.beginEditCommand(
            tr("QuickFieldBrush format painter: set {1}={2} on feature {0}")
            .format(fid, self.target_field, display_val))
        try:
            fld_obj = layer.fields().at(field_idx)
            val_to_write = None if self.is_target_null else AttributeEngine.convert_value_for_field(fld_obj, self.target_value)
            if not layer.changeAttributeValue(fid, field_idx, val_to_write):
                layer.destroyEditCommand()
                self.iface.messageBar().pushWarning(
                    "QuickFieldBrush",
                    tr("Attribute update failed: field [{0}] may be read-only").format(self.target_field))
                return

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

        # 5. 绿色瞬时高亮反馈（180ms 自动消失，几何类型自适应，独立于事务避免 UI 反馈异常误触发回滚）
        try:
            self._flash_timer.stop()
            self.flash_band.reset(layer.geometryType())
            self.flash_band.setToGeometry(hit_feature.geometry(), layer)
            self.flash_band.show()
            self._flash_timer.start(180)
        except (RuntimeError, TypeError, AttributeError):
            pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            # 按 ESC 退出格式刷
            self.canvas.unsetMapTool(self)

    def deactivate(self):
        self._flash_timer.stop()
        self._absorb_timer.stop()
        if self.flash_band:
            self.flash_band.reset()
        if self.absorb_band:
            self.absorb_band.reset()
        self.is_picking_mode = False
        if self.plugin.action_painter and self.plugin.action_painter.isChecked():
            self.plugin.action_painter.setChecked(False)
        # 如果控制面板依然开着，同步关闭
        if self.plugin.painter_dialog and self.plugin.painter_dialog.isVisible():
            self.plugin.painter_dialog.close()
        super().deactivate()
