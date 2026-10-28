# -*- coding: utf-8 -*-
"""
自定义地图交互工具：
继承自 QgsMapToolIdentify，使用 QGIS 原生成熟的图元选择体系：
1. 默认左键画框或单选要素（支持多选、Shift 加选、Ctrl 切换选）
2. 原生适配 macOS Retina / Windows 4K High-DPI 缩放与坐标系自动转换
3. 单击点选使用 TopDownAll 几何最近距离与最小图斑优选算法
4. 容差自适应计算（点、线、面要素均可稳定精准捕获）
5. 右键直接捕获并发出信号，弹出极速分级菜单
"""

from qgis.gui import QgsMapToolIdentify, QgsRubberBand
from qgis.core import (
    QgsWkbTypes,
    QgsRectangle,
    QgsPointXY,
    QgsGeometry,
    QgsCoordinateTransform,
    QgsCsException,
    QgsProject,
    QgsVectorLayer,
    QgsFeatureRequest
)
from qgis.PyQt.QtCore import Qt, QRect, QPoint
from qgis.PyQt.QtGui import QColor, QCursor
from ..i18n_helper import tr


class QuickFieldBrushMapTool(QgsMapToolIdentify):
    def __init__(self, canvas, iface, plugin):
        super().__init__(canvas)
        self.canvas = canvas
        self.iface = iface
        self.plugin = plugin
        
        self.is_dragging = False
        self.start_pos = None      # 屏幕像素起点
        self.start_point = None    # 画布地图坐标起点
        self.end_point = None

        # 框选橡皮筋矩形框（半透明蓝色，与 QGIS 原生保持一致）
        self.rubber_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self.rubber_band.setColor(QColor(0, 120, 215, 65))
        self.rubber_band.setStrokeColor(QColor(0, 120, 215, 200))
        self.rubber_band.setWidth(1)
        cursor_shape = getattr(Qt.CursorShape, "CrossCursor", getattr(Qt, "CrossCursor", None))
        self.setCursor(QCursor(cursor_shape) if cursor_shape is not None else QCursor())

    def canvasPressEvent(self, event):
        layer = self.canvas.currentLayer()

        if event.button() == Qt.LeftButton:
            self.start_pos = event.pos()
            self.start_point = event.mapPoint() if hasattr(event, "mapPoint") else self.toMapCoordinates(event.pos())
            self.end_point = self.start_point
            self.is_dragging = True
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        elif event.button() == Qt.RightButton:
            # 鼠标右键：如果当前已有选中的要素，直接在光标位置弹出快速分级菜单
            if isinstance(layer, QgsVectorLayer) and layer.selectedFeatureCount() > 0:
                self.plugin._show_rank_menu(QCursor.pos(), layer)

    def canvasMoveEvent(self, event):
        if not self.is_dragging:
            return

        self.end_point = event.mapPoint() if hasattr(event, "mapPoint") else self.toMapCoordinates(event.pos())
        self._update_rubber_band()

    def _find_clicked_feature(self, layer: QgsVectorLayer, event):
        """高精度要素点击识别，解决要素在高分屏/Retina下的微偏移与邻近线误选"""
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

        # 容差补充查找（高分辨率下对细线有微小容差偏移）
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
        if event.button() == Qt.LeftButton and self.is_dragging:
            self.is_dragging = False
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)

            layer = self.canvas.currentLayer()
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                self.iface.messageBar().pushWarning(
                    "QuickFieldBrush", tr("Please select a vector layer in the Layers panel first!"))
                return

            end_pt = event.mapPoint() if hasattr(event, "mapPoint") else self.toMapCoordinates(event.pos())
            
            # 判断移动距离（像素差 < 4 判定为单击点选）
            dx = abs(event.pos().x() - self.start_pos.x())
            dy = abs(event.pos().y() - self.start_pos.y())
            is_click = (dx < 4 and dy < 4)

            # 是否按下了 Shift（加选）或 Ctrl（切换选）
            modifiers = event.modifiers()
            is_shift = bool(modifiers & Qt.ShiftModifier)
            is_ctrl = bool(modifiers & Qt.ControlModifier)

            if is_click:
                clicked_feat = self._find_clicked_feature(layer, event)
                matched_fids = [clicked_feat.id()] if clicked_feat else []
            else:
                canvas_rect = QgsRectangle(self.start_point, end_pt)
                matched_fids = self._get_box_matched_fids(layer, canvas_rect)

            self._apply_selection(layer, matched_fids, is_shift, is_ctrl)

    def _get_box_matched_fids(self, layer: QgsVectorLayer, canvas_rect: QgsRectangle):
        """框选空间查询"""
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        layer_crs = layer.crs()
        if canvas_crs.isValid() and layer_crs.isValid() and canvas_crs != layer_crs:
            try:
                transform = QgsCoordinateTransform(canvas_crs, layer_crs, QgsProject.instance())
                canvas_rect = transform.transformBoundingBox(canvas_rect)
            except (QgsCsException, RuntimeError, ValueError):
                pass

        flag_exact = getattr(QgsFeatureRequest, "ExactIntersect", None)
        if flag_exact is None and hasattr(QgsFeatureRequest, "Flag"):
            flag_exact = getattr(QgsFeatureRequest.Flag, "ExactIntersect", None)

        request = QgsFeatureRequest().setFilterRect(canvas_rect)
        if flag_exact is not None:
            request.setFlags(flag_exact)

        return [f.id() for f in layer.getFeatures(request)]

    def _apply_selection(self, layer: QgsVectorLayer, matched_fids: list, is_shift: bool, is_ctrl: bool):
        """根据修饰键组合选中要素集合并提交刷新"""
        current_fids = set(layer.selectedFeatureIds())
        new_matched_set = set(matched_fids)

        if is_ctrl:
            final_fids = current_fids.symmetric_difference(new_matched_set)
        elif is_shift:
            final_fids = current_fids.union(new_matched_set)
        else:
            final_fids = new_matched_set

        layer.selectByIds(list(final_fids))
        self.canvas.refresh()
        self.plugin._on_selection_changed(layer, len(final_fids))

    def _update_rubber_band(self):
        """绘制蓝色半透明框选框"""
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        p1 = QgsPointXY(self.start_point.x(), self.start_point.y())
        p2 = QgsPointXY(self.end_point.x(), self.start_point.y())
        p3 = QgsPointXY(self.end_point.x(), self.end_point.y())
        p4 = QgsPointXY(self.start_point.x(), self.end_point.y())

        self.rubber_band.addPoint(p1, False)
        self.rubber_band.addPoint(p2, False)
        self.rubber_band.addPoint(p3, False)
        self.rubber_band.addPoint(p4, True)
        self.rubber_band.show()

    def deactivate(self):
        if self.rubber_band:
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        # 工具被切走时取消工具条图标的 Checked 状态
        if self.plugin.action_toggle and self.plugin.action_toggle.isChecked():
            self.plugin.action_toggle.setChecked(False)
        super().deactivate()
