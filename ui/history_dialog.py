# -*- coding: utf-8 -*-
"""
QuickFieldBrush 历史记录面板 (HistoryDockWidget):
QGIS 原生风格的停靠/悬浮历史记录面板：
1. 原生数据表格视图 (QTreeWidget)，支持斑马线底色、自适应列宽、系统高亮与深浅色模式自适应；
2. 一体化原生工具栏：搜索过滤、撤回、导出台账、悬浮置顶无缝集成；
3. 单击条目：画布瞬间居中/平移到该要素，并触发 350ms 翠绿高亮闪烁；
4. 双击条目：自动在矢量图层中选中对应要素并激活该图层；
5. 右键菜单与工具栏撤回：支持针对选中项单步回滚或快捷撤销最新一步；
6. 窗口支持在 QGIS 主窗口停靠 (Dock) 与独立悬浮置顶 (Float & Pin)。
"""

import os
from qgis.gui import QgsDockWidget, QgsRubberBand
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton,
    QLineEdit, QFileDialog, QMenu, QApplication,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox
)
from qgis.PyQt.QtGui import QIcon, QColor, QFont, QPalette
from qgis.PyQt.QtCore import Qt, QTimer, QSize
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateTransform, QgsCsException, QgsRectangle, QgsFeatureRequest
)

from ..core.compat import safe_exec, set_window_stay_on_top
from ..core.history_manager import HistoryManager, HistoryStep
from ..core.attribute_engine import AttributeEngine
from ..i18n_helper import tr


class HistoryDockWidget(QgsDockWidget):
    """
    QuickFieldBrush 历史记录面板 (100% QGIS 原生桌面风格)
    """

    def __init__(self, iface, parent=None):
        super().__init__(tr("QuickFieldBrush History"), parent or iface.mainWindow())
        self.setObjectName("QuickFieldBrushHistoryDock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.mgr = HistoryManager.instance()
        self.is_pinned = True

        self.setWindowTitle(tr("QuickFieldBrush History"))
        self.setFloating(True)
        self.resize(340, 440)
        self.setMinimumSize(280, 260)

        # 地图瞬时高亮橡皮筋
        self._flash_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self._flash_band.setColor(QColor(76, 175, 80, 130))
        self._flash_band.setStrokeColor(QColor(46, 125, 50, 255))
        self._flash_band.setWidth(3)

        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._flash_band.reset)

        self._init_ui()
        self._reload_history()

        # 监听历史变动信号与停靠状态
        self.mgr.history_changed.connect(self._reload_history)
        self.topLevelChanged.connect(self._on_top_level_changed)

    def _init_ui(self):
        container = QWidget(self)
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")

        # 1. 顶部紧凑工具条 (搜索过滤 + 撤回 + 导出 + 悬浮置顶)
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(2)

        # 搜索框
        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText(tr("Search field, layer, or FID..."))
        self.txt_filter.setClearButtonEnabled(True)
        search_icon = QIcon(os.path.join(icons_dir, "search.svg"))
        leading_pos = getattr(QLineEdit.ActionPosition, "LeadingPosition", getattr(QLineEdit, "LeadingPosition", 0))
        if not search_icon.isNull():
            self.txt_filter.addAction(search_icon, leading_pos)
        self.txt_filter.textChanged.connect(self._filter_items)
        toolbar_layout.addWidget(self.txt_filter, 1)

        t_beside = getattr(Qt.ToolButtonStyle, "ToolButtonTextBesideIcon", getattr(Qt, "ToolButtonTextBesideIcon", 2))

        # 撤回按钮 (扁平原生工具按钮)
        self.btn_undo = QToolButton()
        self.btn_undo.setAutoRaise(True)
        self.btn_undo.setToolButtonStyle(t_beside)
        self.btn_undo.setText(tr("Undo Latest"))
        undo_icon = QIcon(os.path.join(icons_dir, "undo_latest.svg"))
        if not undo_icon.isNull():
            self.btn_undo.setIcon(undo_icon)
            self.btn_undo.setIconSize(QSize(16, 16))
        self.btn_undo.setToolTip(tr("Revert selected or latest modification"))
        self.btn_undo.clicked.connect(self._undo_latest)
        toolbar_layout.addWidget(self.btn_undo)

        # 导出按钮
        self.btn_export = QToolButton()
        self.btn_export.setAutoRaise(True)
        self.btn_export.setToolButtonStyle(t_beside)
        self.btn_export.setText(tr("Export"))
        export_icon = QIcon(os.path.join(icons_dir, "export.svg"))
        if not export_icon.isNull():
            self.btn_export.setIcon(export_icon)
            self.btn_export.setIconSize(QSize(16, 16))
        self.btn_export.setToolTip(tr("Export history log to CSV file"))
        self.btn_export.clicked.connect(self._export_csv)
        toolbar_layout.addWidget(self.btn_export)

        # 悬浮置顶按钮 (悬浮时显示在工具栏右侧，停靠时自动隐藏)
        self.btn_pin = QToolButton()
        self.btn_pin.setAutoRaise(True)
        self.btn_pin.setCheckable(True)
        self.btn_pin.setChecked(True)
        self._icon_pin_on = QIcon(os.path.join(icons_dir, "pin_green.svg"))
        self._icon_pin_off = QIcon(os.path.join(icons_dir, "pin_grey.svg"))
        if not self._icon_pin_on.isNull():
            self.btn_pin.setIcon(self._icon_pin_on)
            self.btn_pin.setIconSize(QSize(15, 15))
        self.btn_pin.setToolTip(tr("Always on top (click to disable)"))
        self.btn_pin.toggled.connect(self._toggle_stay_on_top)
        toolbar_layout.addWidget(self.btn_pin)

        main_layout.addLayout(toolbar_layout)

        # 2. 原生表格/树形列表 (QTreeWidget)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([
            tr("Field ➔ Value"),
            tr("Layer · Feature"),
            tr("Time")
        ])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)

        sel_mode = getattr(QAbstractItemView.SelectionMode, 'SingleSelection', getattr(QAbstractItemView, 'SingleSelection', 1))
        sel_behav = getattr(QAbstractItemView.SelectionBehavior, 'SelectRows', getattr(QAbstractItemView, 'SelectRows', 1))
        if sel_mode is not None:
            self.tree.setSelectionMode(sel_mode)
        if sel_behav is not None:
            self.tree.setSelectionBehavior(sel_behav)

        # 表头伸缩策略：第一列自适应拉伸，后两列交互固定宽度
        rm_stretch = getattr(QHeaderView.ResizeMode, "Stretch", getattr(QHeaderView, "Stretch", 1))
        rm_interactive = getattr(QHeaderView.ResizeMode, "Interactive", getattr(QHeaderView, "Interactive", 0))

        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, rm_stretch)
        header.setSectionResizeMode(1, rm_interactive)
        header.resizeSection(1, 130)
        header.setSectionResizeMode(2, rm_interactive)
        header.resizeSection(2, 58)

        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_tree_item_double_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        main_layout.addWidget(self.tree, 1)

        # 3. 底部状态与操作引导栏
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(2, 2, 2, 2)
        status_layout.setSpacing(4)

        self.lbl_count = QLabel(tr("Total: 0 records"))
        self.lbl_count.setStyleSheet("font-size: 11px;")
        status_layout.addWidget(self.lbl_count)

        status_layout.addStretch()

        self.lbl_hint = QLabel(tr("Click to locate · Double-click to select"))
        self.lbl_hint.setStyleSheet("color: gray; font-size: 11px;")
        status_layout.addWidget(self.lbl_hint)

        main_layout.addLayout(status_layout)
        self.setWidget(container)

    def _on_top_level_changed(self, is_floating):
        """浮动/停靠状态切换时联动置顶按钮"""
        self.btn_pin.setVisible(is_floating)
        if is_floating:
            self.btn_pin.setEnabled(True)
            if self.is_pinned:
                set_window_stay_on_top(self, True)
            self.btn_pin.setToolTip(tr("Always on top (click to disable)") if self.is_pinned else tr("Not on top (click to enable)"))
        else:
            self.btn_pin.setEnabled(False)

    def _toggle_stay_on_top(self, checked):
        """置顶切换"""
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

    def _reload_history(self):
        """重新刷新加载历史记录列表（倒序显示：最新记录在最上方）"""
        self.tree.clear()
        steps = self.mgr.get_steps()
        total_count = len(steps)
        self.lbl_count.setText(tr("Total: {0} records").format(total_count))

        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
        ic_painter = QIcon(os.path.join(icons_dir, "painter.svg"))
        ic_rank = QIcon(os.path.join(icons_dir, "rank.svg"))

        role_user = getattr(Qt.ItemDataRole, "UserRole", getattr(Qt, "UserRole", 256))
        cg_dis = getattr(QPalette.ColorGroup, "Disabled", getattr(QPalette, "Disabled", 1))
        cr_text = getattr(QPalette.ColorRole, "Text", getattr(QPalette, "Text", 6))
        muted_color = self.tree.palette().color(cg_dis, cr_text)

        # 倒序展示：最新操作在顶部
        for step in reversed(steps):
            item = QTreeWidgetItem(self.tree)
            item.setData(0, role_user, step.id)

            # 图标
            if step.tool_type == "painter":
                item.setIcon(0, ic_painter)
            else:
                item.setIcon(0, ic_rank)

            # 第一列：[字段] ➔ "新值"
            target_display = "NULL" if AttributeEngine.is_null_value(step.target_value) else str(step.target_value)
            if len(target_display) > 24:
                target_display = target_display[:22] + "..."
            item.setText(0, f"[{step.field_name}] ➔ \"{target_display}\"")

            # 第二列：图层 · 要素
            if step.tool_type == "painter":
                fid_val = step.changes[0]["fid"] if step.changes else ""
                layer_feat_str = f"{step.layer_name} · {fid_val}"
            else:
                cnt = step.feature_count
                layer_feat_str = f"{step.layer_name} · {cnt} {tr('features')}"
            item.setText(1, layer_feat_str)

            # 第三列：时间戳
            # 如果包含日期，提取时分秒保持紧凑
            ts_str = step.timestamp
            if " " in ts_str:
                time_only = ts_str.split(" ", 1)[1]
            else:
                time_only = ts_str
            item.setText(2, time_only)

            # 完整信息气泡提示 (Tooltip)
            display_val = "NULL" if AttributeEngine.is_null_value(step.target_value) else step.target_value
            tt_lines = [
                f"{tr('Action Type')}: {tr('Format Painter') if step.tool_type == 'painter' else tr('Batch Assignment')}",
                f"{tr('Layer')}: {step.layer_name}",
                f"{tr('Field')}: {step.field_name}",
                f"{tr('Target Value')}: {display_val}",
                f"{tr('Timestamp')}: {step.timestamp}",
                f"{tr('Reverted')}: {tr('Yes') if step.is_reverted else tr('No')}"
            ]
            if step.tool_type == "painter" and step.changes:
                old_val = "NULL" if AttributeEngine.is_null_value(step.changes[0].get('old_val')) else step.changes[0].get('old_val', '')
                tt_lines.append(f"{tr('Feature ID (FID)')}: {step.changes[0]['fid']}")
                tt_lines.append(f"{tr('Old Value')}: {old_val}")
            else:
                tt_lines.append(f"{tr('features')}: {step.feature_count}")
            item.setToolTip(0, "\n".join(tt_lines))
            item.setToolTip(1, "\n".join(tt_lines))
            item.setToolTip(2, "\n".join(tt_lines))

            # 如果已撤回，应用原生删除线与置灰样式
            if step.is_reverted:
                for col in range(3):
                    f = item.font(col)
                    f.setStrikeOut(True)
                    item.setFont(col, f)
                    item.setForeground(col, muted_color)

        self._filter_items(self.txt_filter.text())

    def _filter_items(self, text: str):
        """按关键字过滤历史项"""
        query = text.strip().lower()
        role_user = getattr(Qt.ItemDataRole, "UserRole", getattr(Qt, "UserRole", 256))
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            step_id = item.data(0, role_user)
            step = self.mgr.get_step_by_id(step_id)
            if not step:
                item.setHidden(True)
                continue

            if not query:
                item.setHidden(False)
                continue

            match = (
                query in step.field_name.lower() or
                query in step.layer_name.lower() or
                query in str(step.target_value).lower() or
                any(query in str(c["fid"]) for c in step.changes) or
                any(query in str(c.get("old_val", "")).lower() for c in step.changes)
            )
            item.setHidden(not match)

    def _on_tree_item_clicked(self, item, column):
        """单击条目：居中并闪烁高亮对应要素"""
        role_user = getattr(Qt.ItemDataRole, "UserRole", getattr(Qt, "UserRole", 256))
        step_id = item.data(0, role_user)
        self._locate_and_flash_step(step_id)

    def _on_tree_item_double_clicked(self, item, column):
        """双击条目：选中对应要素并设为当前活动图层"""
        role_user = getattr(Qt.ItemDataRole, "UserRole", getattr(Qt, "UserRole", 256))
        step_id = item.data(0, role_user)
        self._select_step_features(step_id)

    def _locate_and_flash_step(self, step_id: int):
        """定位并在地图闪烁对应要素"""
        step = self.mgr.get_step_by_id(step_id)
        if not step:
            return

        layer = QgsProject.instance().mapLayer(step.layer_id)
        if not layer or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            candidates = QgsProject.instance().mapLayersByName(step.layer_name)
            if candidates and isinstance(candidates[0], QgsVectorLayer) and candidates[0].isValid():
                layer = candidates[0]
            else:
                return

        fids = step.fids
        if not fids:
            return

        canvas_crs = self.canvas.mapSettings().destinationCrs()
        layer_crs = layer.crs()
        transform = None
        if canvas_crs.isValid() and layer_crs.isValid() and canvas_crs != layer_crs:
            try:
                transform = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
            except Exception:
                transform = None

        if len(fids) == 1:
            feat = layer.getFeature(fids[0])
            if feat.isValid() and feat.geometry() and not feat.geometry().isEmpty():
                geom = feat.geometry()
                center_pt = geom.centroid().asPoint()
                if transform:
                    try:
                        center_pt = transform.transform(center_pt)
                    except (QgsCsException, RuntimeError, ValueError):
                        pass
                self.canvas.setCenter(center_pt)
                self.canvas.refresh()

                try:
                    self._flash_timer.stop()
                    self._flash_band.reset(geom.type())
                    self._flash_band.setToGeometry(geom, layer)
                    self._flash_band.show()
                    self._flash_timer.start(350)
                except (RuntimeError, TypeError, AttributeError):
                    pass
        else:
            req = QgsFeatureRequest().setFilterFids(fids)
            combined_rect = QgsRectangle()
            first = True
            geoms = []
            for feat in layer.getFeatures(req):
                g = feat.geometry()
                if g and not g.isEmpty():
                    geoms.append(g)
                    bbox = g.boundingBox()
                    if first:
                        combined_rect = QgsRectangle(bbox)
                        first = False
                    else:
                        combined_rect.combineExtentWith(bbox)

            if not combined_rect.isNull() and not combined_rect.isEmpty():
                if transform:
                    try:
                        combined_rect = transform.transformBoundingBox(combined_rect)
                    except (QgsCsException, RuntimeError, ValueError):
                        pass
                combined_rect.scale(1.25)
                self.canvas.setExtent(combined_rect)
                self.canvas.refresh()

            if geoms:
                try:
                    self._flash_timer.stop()
                    self._flash_band.reset(geoms[0].type())
                    for g in geoms:
                        self._flash_band.addGeometry(g, layer)
                    self._flash_band.show()
                    self._flash_timer.start(400)
                except (RuntimeError, TypeError, AttributeError):
                    pass

    def _select_step_features(self, step_id: int):
        """在图层中选中要素"""
        step = self.mgr.get_step_by_id(step_id)
        if not step:
            return

        layer = QgsProject.instance().mapLayer(step.layer_id)
        if not layer or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            candidates = QgsProject.instance().mapLayersByName(step.layer_name)
            if candidates and isinstance(candidates[0], QgsVectorLayer) and candidates[0].isValid():
                layer = candidates[0]
            else:
                return

        layer.selectByIds(step.fids)
        self.iface.setActiveLayer(layer)
        self.iface.messageBar().pushInfo(
            "QuickFieldBrush",
            tr("Selected {0} features on layer [{1}]").format(len(step.fids), layer.name())
        )

    def _show_context_menu(self, pos):
        """右键菜单"""
        item = self.tree.itemAt(pos)
        if not item:
            return

        role_user = getattr(Qt.ItemDataRole, "UserRole", getattr(Qt, "UserRole", 256))
        step_id = item.data(0, role_user)
        step = self.mgr.get_step_by_id(step_id)
        if not step:
            return

        menu = QMenu(self)

        act_zoom = menu.addAction(tr("Zoom and highlight feature(s)"))
        act_zoom.triggered.connect(lambda: self._locate_and_flash_step(step_id))

        act_select = menu.addAction(tr("Select feature(s) in layer"))
        act_select.triggered.connect(lambda: self._select_step_features(step_id))

        menu.addSeparator()

        act_revert = menu.addAction(tr("Revert this operation"))
        act_revert.setEnabled(not step.is_reverted)
        act_revert.triggered.connect(lambda: self._revert_step_by_id(step.id))

        menu.addSeparator()

        act_copy_fids = menu.addAction(tr("Copy Feature ID(s) to Clipboard"))
        act_copy_fids.triggered.connect(lambda: QApplication.clipboard().setText(", ".join(map(str, step.fids))))

        act_copy_info = menu.addAction(tr("Copy Details"))
        act_copy_info.triggered.connect(lambda: QApplication.clipboard().setText(
            f"Layer: {step.layer_name}, Field: {step.field_name}, Value: {step.target_value}, FIDs: {step.fids}, Time: {step.timestamp}"
        ))

        menu.addSeparator()

        act_clear = menu.addAction(tr("Clear all history entries"))
        act_clear.triggered.connect(self._clear_all_history)

        safe_exec(menu, self.tree.mapToGlobal(pos))

    def _revert_step_by_id(self, step_id: int):
        """执行单步还原"""
        ok, msg = self.mgr.revert_step(step_id, self.iface)
        if ok:
            self.iface.messageBar().pushSuccess("QuickFieldBrush", msg)
        else:
            self.iface.messageBar().pushWarning("QuickFieldBrush", msg)

    def _undo_latest(self):
        """撤销：若当前树形列表中选中了某项，则撤销该项；否则撤销最近一条未撤销的记录"""
        selected_items = self.tree.selectedItems()
        role_user = getattr(Qt.ItemDataRole, "UserRole", getattr(Qt, "UserRole", 256))

        if selected_items:
            sel_step_id = selected_items[0].data(0, role_user)
            step = self.mgr.get_step_by_id(sel_step_id)
            if step and not step.is_reverted:
                self._revert_step_by_id(sel_step_id)
                return
            elif step and step.is_reverted:
                self.iface.messageBar().pushInfo("QuickFieldBrush", tr("Step #{0} has already been reverted!").format(sel_step_id))
                return

        steps = self.mgr.get_steps()
        for step in reversed(steps):
            if not step.is_reverted:
                self._revert_step_by_id(step.id)
                return
        self.iface.messageBar().pushInfo("QuickFieldBrush", tr("No pending modifications to undo!"))

    def _export_csv(self):
        """导出 CSV 审计日志"""
        steps = self.mgr.get_steps()
        if not steps:
            self.iface.messageBar().pushInfo("QuickFieldBrush", tr("History is empty, nothing to export!"))
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            tr("Export History to CSV"),
            "QuickFieldBrush_History.csv",
            "CSV Files (*.csv)"
        )
        if filepath:
            ok, msg = self.mgr.export_csv(filepath)
            if ok:
                self.iface.messageBar().pushSuccess("QuickFieldBrush", msg)
            else:
                self.iface.messageBar().pushWarning("QuickFieldBrush", msg)

    def _clear_all_history(self):
        """清空历史记录 (带二次确认)"""
        ret = QMessageBox.question(
            self,
            tr("Clear all history entries"),
            tr("Are you sure you want to clear all history records? This cannot be undone."),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if ret == QMessageBox.Yes:
            self.mgr.clear_history()
            self.iface.messageBar().pushInfo("QuickFieldBrush", tr("History log cleared!"))

    def closeEvent(self, event):
        if hasattr(self, "_flash_timer"):
            self._flash_timer.stop()
        if self._flash_band:
            self._flash_band.reset()
        super().closeEvent(event)


# 向后兼容别名
HistoryDialog = HistoryDockWidget
