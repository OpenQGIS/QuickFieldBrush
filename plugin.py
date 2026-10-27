# -*- coding: utf-8 -*-
"""
QuickFieldBrush 插件主控制器：
1. 交互赋值工具 (框选+右键快速赋值，每次激活弹窗选定字段，集成智能排序与要素频次)
2. 属性格式刷工具 (无模态常驻置顶控制台，单选/吸取属性后连续点击要素快速刷入)
3. 操作历史面板 (记录修改、地图定位闪烁、单步精准还原与导出 CSV)
"""

import os
from qgis.PyQt.QtWidgets import QToolBar, QInputDialog
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsVectorLayer

from .core.compat import safe_exec, QAction

from .core.config_manager import ConfigManager
from .core.attribute_engine import AttributeEngine
from .core.map_tool import QuickFieldBrushMapTool
from .core.format_painter_tool import FormatPainterTool
from .ui.rank_context_menu import RankContextMenu
from .ui.format_painter_dialog import FormatPainterDialog
from .ui.history_dialog import HistoryDialog
from .i18n_helper import tr, load_translator, unload_translator


class QuickFieldBrushPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.config = ConfigManager.get_config()

        self.map_tool = None
        self.painter_tool = None
        self.painter_dialog = None
        self.history_dialog = None
        self.action_toggle = None
        self.action_painter = None
        self.action_history = None
        self.toolbar = None
        self._connected_layer = None
        self.translator = None

        # 翻译器加载
        self.translator = load_translator(os.path.dirname(os.path.abspath(__file__)))

    def initGui(self):
        # 1. 防抖清理已有同名工具条
        for tb in self.iface.mainWindow().findChildren(QToolBar, "QuickFieldBrushToolBar"):
            self.iface.mainWindow().removeToolBar(tb)
            tb.deleteLater()

        # 创建工具条
        self.toolbar = self.iface.addToolBar(tr("QuickFieldBrush Toolbar"))
        self.toolbar.setObjectName("QuickFieldBrushToolBar")
        self.toolbar.setStyleSheet("""
            QToolBar#QuickFieldBrushToolBar {
                spacing: 4px;
            }
            QToolBar#QuickFieldBrushToolBar QToolButton {
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 3px;
                background-color: transparent;
            }
            QToolBar#QuickFieldBrushToolBar QToolButton:hover {
                background-color: rgba(0, 0, 0, 0.08);
                border: 1px solid rgba(0, 0, 0, 0.12);
            }
            QToolBar#QuickFieldBrushToolBar QToolButton:checked,
            QToolBar#QuickFieldBrushToolBar QToolButton:pressed {
                background-color: rgba(37, 99, 235, 0.15);
                border: 1px solid #2563EB;
            }
        """)

        # 2. 从 icons/ 文件夹加载工具栏矢量图标
        icons_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
        icon_active = self._load_icon(os.path.join(icons_dir, "rank.svg"))
        icon_painter = self._load_icon(os.path.join(icons_dir, "painter.svg"))
        icon_history = self._load_icon(os.path.join(icons_dir, "history.svg"))

        # 3. 功能 1: 激活/停用快捷赋值工具 (框选+右键)
        self.action_toggle = QAction(
            icon_active,
            tr("Interactive Assignment"),
            self.iface.mainWindow()
        )
        self.action_toggle.setCheckable(True)
        self.action_toggle.setToolTip(tr(
            "Interactive Assignment, activate interactive assignment tool\n"
            "Select target field after activation, click or box-select features, then right-click to rapidly modify attribute values."
        ))
        self.action_toggle.triggered.connect(self._toggle_map_tool)
        self.toolbar.addAction(self.action_toggle)
        self.iface.addPluginToVectorMenu(tr("QuickFieldBrush - Ranking"), self.action_toggle)

        # 功能 2: 格式刷工具 (单选某属性，点击要素连续刷入)
        self.action_painter = QAction(
            icon_painter,
            tr("Attribute Format Painter"),
            self.iface.mainWindow()
        )
        self.action_painter.setCheckable(True)
        self.action_painter.setToolTip(tr(
            "Attribute Format Painter, activate format painter console\n"
            "Select or absorb attribute, then click features consecutively for rapid assignment"
        ))
        self.action_painter.triggered.connect(self._toggle_painter_tool)
        self.toolbar.addAction(self.action_painter)
        self.iface.addPluginToVectorMenu(tr("QuickFieldBrush - Format Painter"), self.action_painter)

        # 功能 3: 历史记录面板 (独立无模态浮动面板)
        self.action_history = QAction(
            icon_history,
            tr("Edit History"),
            self.iface.mainWindow()
        )
        self.action_history.setToolTip(tr(
            "Edit History, open plugin history panel\n"
            "Browse, flash-zoom, single-step revert, and export records"
        ))
        self.action_history.triggered.connect(self._toggle_history_dialog)
        self.toolbar.addAction(self.action_history)
        self.iface.addPluginToVectorMenu(tr("QuickFieldBrush - History"), self.action_history)

        # 4. 初始化地图工具
        self.map_tool = QuickFieldBrushMapTool(self.canvas, self.iface, self)
        self.painter_tool = FormatPainterTool(self.canvas, self.iface, self)

        # 5. 安全监听图层切换信号
        self.iface.currentLayerChanged.connect(self._on_current_layer_changed)
        self._bind_layer_selection_signal(self.iface.activeLayer())

    def unload(self):
        # 卸载地图工具
        if self.canvas.mapTool() in [self.map_tool, self.painter_tool]:
            self.canvas.unsetMapTool(self.canvas.mapTool())

        # 解绑图层选择信号
        self._unbind_layer_selection_signal()

        try:
            self.iface.currentLayerChanged.disconnect(self._on_current_layer_changed)
        except (TypeError, RuntimeError, AttributeError):
            pass

        if self.painter_dialog:
            self.painter_dialog.close()
            self.painter_dialog.deleteLater()
            self.painter_dialog = None

        if self.history_dialog:
            self.history_dialog.close()
            self.history_dialog.deleteLater()
            self.history_dialog = None

        # 移除工具条与菜单项
        if self.action_toggle:
            self.iface.removePluginVectorMenu(tr("QuickFieldBrush - Ranking"), self.action_toggle)
        if self.action_painter:
            self.iface.removePluginVectorMenu(tr("QuickFieldBrush - Format Painter"), self.action_painter)
        if self.action_history:
            self.iface.removePluginVectorMenu(tr("QuickFieldBrush - History"), self.action_history)

        if self.toolbar:
            self.toolbar.clear()
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar.deleteLater()
            self.toolbar = None

        # 卸载翻译器
        self.translator = unload_translator(self.translator)

    def _toggle_map_tool(self, checked):
        if checked:
            layer = self.iface.activeLayer()
            if not layer or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                self.iface.messageBar().pushWarning(
                    "QuickFieldBrush", tr("Please select a valid vector layer in the Layers panel first!"))
                self.action_toggle.setChecked(False)
                return

            fields = AttributeEngine.get_editable_fields(layer)
            if not fields:
                self.iface.messageBar().pushWarning(
                    "QuickFieldBrush", tr("Layer: {0} (no editable fields)").format(layer.name()))
                self.action_toggle.setChecked(False)
                return

            valid_names = [f["name"] for f in fields]

            # 每次激活工具均弹窗让用户确定目标赋值字段
            self.config = ConfigManager.get_config()
            by_layer = self.config.get("single_rank_by_layer", {})
            current_field = by_layer.get(layer.id()) or self.config.get("single_rank", {}).get("field_name", "")
            current_idx = 0
            if current_field in valid_names:
                current_idx = valid_names.index(current_field)

            item, ok = QInputDialog.getItem(
                self.iface.mainWindow(),
                tr("Specify Ranking Field"),
                tr("Please select the target field for rapid ranking in layer [{0}]:").format(layer.name()),
                valid_names,
                current_idx,
                False
            )

            if not ok or not item:
                # 用户取消，不激活工具
                self.action_toggle.setChecked(False)
                return

            # 保存选中的字段并激活工具
            by_layer = self.config.setdefault("single_rank_by_layer", {})
            by_layer[layer.id()] = item
            self.config.setdefault("single_rank", {})["field_name"] = item
            ConfigManager.save_config(self.config)

            if self.action_painter and self.action_painter.isChecked():
                self.action_painter.setChecked(False)

            self.canvas.setMapTool(self.map_tool)
            self.iface.messageBar().pushInfo(
                "QuickFieldBrush",
                tr("Interactive ranking tool activated: box-select features, then right-click to rank!") +
                tr(" | Target: [{0}]").format(item))
        else:
            if self.canvas.mapTool() == self.map_tool:
                self.canvas.unsetMapTool(self.map_tool)

    def _toggle_painter_tool(self, checked):
        """激活格式刷工具"""
        if checked:
            # 取消常规框选工具的状态
            if self.action_toggle and self.action_toggle.isChecked():
                self.action_toggle.setChecked(False)

            # 打开无模态常驻/置顶控制面板
            if self.painter_dialog is None:
                self.painter_dialog = FormatPainterDialog(self.iface, self.painter_tool, self.iface.mainWindow())

            self.painter_dialog.show()
            self.painter_dialog.raise_()
            self.painter_dialog.activateWindow()

            # 激活画笔地图工具
            self.canvas.setMapTool(self.painter_tool)
        else:
            if self.painter_dialog and self.painter_dialog.isVisible():
                self.painter_dialog.close()
            if self.canvas.mapTool() == self.painter_tool:
                self.canvas.unsetMapTool(self.painter_tool)

    def _toggle_history_dialog(self):
        """切换历史记录面板的显示/隐藏 (无模态浮动面板)"""
        if self.history_dialog is None:
            self.history_dialog = HistoryDialog(self.iface, self.iface.mainWindow())

        if self.history_dialog.isVisible():
            self.history_dialog.hide()
        else:
            self.history_dialog.show()
            self.history_dialog.raise_()
            self.history_dialog.activateWindow()

    def _show_rank_menu(self, global_pos, layer):
        """响应右键快速分级菜单呼出请求"""
        self.config = ConfigManager.get_config()
        menu = RankContextMenu(self.iface.mainWindow(), layer, self.config, self.iface, spawn_pos=global_pos)
        safe_exec(menu, global_pos)

    def _on_selection_changed(self, layer, count):
        """当要素选择发生改变时触发"""
        pass

    def _on_current_layer_changed(self, layer):
        """当活动图层改变时，重连选择信号"""
        self._bind_layer_selection_signal(layer)

    def _bind_layer_selection_signal(self, layer):
        self._unbind_layer_selection_signal()
        if layer and hasattr(layer, "selectionChanged"):
            try:
                layer.selectionChanged.connect(self._on_layer_selection_changed_internal)
                self._connected_layer = layer
            except (TypeError, RuntimeError, AttributeError):
                pass

    def _unbind_layer_selection_signal(self):
        try:
            if self._connected_layer and hasattr(self._connected_layer, "selectionChanged"):
                self._connected_layer.selectionChanged.disconnect(self._on_layer_selection_changed_internal)
        except (RuntimeError, ReferenceError, TypeError, AttributeError):
            pass
        finally:
            self._connected_layer = None

    def _on_layer_selection_changed_internal(self):
        if self._connected_layer:
            try:
                if hasattr(self._connected_layer, "isValid") and self._connected_layer.isValid():
                    self._on_selection_changed(self._connected_layer, self._connected_layer.selectedFeatureCount())
            except (RuntimeError, ReferenceError):
                self._connected_layer = None

    def _load_icon(self, filepath):
        """优先从指定路径加载 SVG/PNG 文件"""
        if os.path.exists(filepath):
            icon = QIcon(filepath)
            if not icon.isNull():
                return icon
        base, _ = os.path.splitext(filepath)
        for ext in [".svg", ".png"]:
            cand = base + ext
            if os.path.exists(cand):
                icon = QIcon(cand)
                if not icon.isNull():
                    return icon
        return QIcon()
