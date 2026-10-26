# -*- coding: utf-8 -*-
"""
自定义地图交互工具：
继承自 QgsMapToolIdentify，使用 QGIS 原生成熟的图元选择体系：
1. 默认左键画框或单选要素（支持多选、Shift 加选、Ctrl 切换选）
2. 坐标系自动转换（画布 CRS -> 图层 CRS）
3. 容差自适应计算（点、线、面要素均可稳定捕获）
4. 右键直接捕获并发出信号，弹出极速分级菜单
"""

from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.core import (
    QgsWkbTypes,
    QgsRectangle,
    QgsPointXY,
    QgsCoordinateTransform,
    QgsProject,
    QgsVectorLayer,
    QgsFeatureRequest
)
from qgis.PyQt.QtCore import Qt, QRect
from qgis.PyQt.QtGui import QColor, QCursor
from ..i18n_helper import tr


class QuickFieldBrushMapTool(QgsMapTool):
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
        self.setCursor(Qt.CrossCursor)

    def canvasPressEvent(self, event):
        layer = self.canvas.currentLayer()

        if event.button() == Qt.LeftButton:
            self.start_pos = event.pos()
            self.start_point = self.toMapCoordinates(event.pos())
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

        self.end_point = self.toMapCoordinates(event.pos())
        self._update_rubber_band()

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_dragging:
            self.is_dragging = False
            self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)

            layer = self.canvas.currentLayer()
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                self.iface.messageBar().pushWarning(
                    "QuickFieldBrush", tr("Please select a vector layer in the Layers panel first!"))
                return

            end_pt = self.toMapCoordinates(event.pos())
            
            # 判断移动距离（像素差 < 4 判定为单击点选）
            dx = abs(event.pos().x() - self.start_pos.x())
            dy = abs(event.pos().y() - self.start_pos.y())
            is_click = (dx < 4 and dy < 4)

            # 是否按下了 Shift（加选）或 Ctrl（切换选）
            modifiers = event.modifiers()
            is_shift = bool(modifiers & Qt.ShiftModifier)
            is_ctrl = bool(modifiers & Qt.ControlModifier)

            if is_click:
                # 单击模式：根据图元类型给与合适的屏幕容差半径（线要素给 8 像素容差）
                pixel_tolerance = 8
                mu_tolerance = self.canvas.mapUnitsPerPixel() * pixel_tolerance
                canvas_rect = QgsRectangle(
                    end_pt.x() - mu_tolerance, end_pt.y() - mu_tolerance,
                    end_pt.x() + mu_tolerance, end_pt.y() + mu_tolerance
                )
            else:
                # 框选模式：取对角坐标矩形
                canvas_rect = QgsRectangle(self.start_point, end_pt)

            self._perform_selection(layer, canvas_rect, is_shift, is_ctrl, is_click)

    def _perform_selection(self, layer: QgsVectorLayer, canvas_rect: QgsRectangle, is_shift: bool, is_ctrl: bool, is_click: bool):
        """执行空间相交选择，兼容坐标系转换与多要素选择"""
        # 1. 处理画布 CRS 与图层 CRS 不同的投影转换
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        layer_crs = layer.crs()
        if canvas_crs.isValid() and layer_crs.isValid() and canvas_crs != layer_crs:
            try:
                transform = QgsCoordinateTransform(canvas_crs, layer_crs, QgsProject.instance())
                canvas_rect = transform.transformBoundingBox(canvas_rect)
            except Exception:
                pass

        # 2. 空间查询走 provider 空间索引（FilterRect 预筛 + 精确相交），
        #    避免在 Python 层逐要素全表遍历（大图层框选卡顿的根源）
        flag_exact = getattr(QgsFeatureRequest, "ExactIntersect", None)
        if flag_exact is None and hasattr(QgsFeatureRequest, "Flag"):
            flag_exact = getattr(QgsFeatureRequest.Flag, "ExactIntersect", None)

        request = QgsFeatureRequest().setFilterRect(canvas_rect)
        if flag_exact is not None:
            request.setFlags(flag_exact)
        matched_fids = []
        for feature in layer.getFeatures(request):
            matched_fids.append(feature.id())
            if is_click:
                # 单击模式下如果已经碰到一个要素即可停止
                break

        # 3. 组合选中要素 ID
        current_fids = set(layer.selectedFeatureIds())
        new_matched_set = set(matched_fids)

        if is_ctrl:
            # Ctrl：反选/切换选择
            final_fids = current_fids.symmetric_difference(new_matched_set)
        elif is_shift:
            # Shift：追加多选
            final_fids = current_fids.union(new_matched_set)
        else:
            # 普通选择：直接设为本次框选到的所有要素
            final_fids = new_matched_set

        # 4. 提交选择并刷新视图
        layer.selectByIds(list(final_fids))
        self.canvas.refresh()

        # 5. 通知插件更新面板
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
