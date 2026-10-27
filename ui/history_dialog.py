# -*- coding: utf-8 -*-
"""
QuickFieldBrush 历史记录面板 (HistoryDialog):
无模态悬浮操作历史面板：
1. 记录格式刷单点写入与框选批量赋值的所有操作历史
2. 单击记录：画布瞬间居中/平移到该要素，并触发 350ms 翠绿高亮闪烁
3. 双击记录：自动在矢量图层中选中对应要素 (QgsVectorLayer.selectByIds)
4. 单步回滚：点击记录右侧 ↺ 按钮或右键菜单，一键将要素恢复到修改前的值 (old_value)
5. 撤销最近一步、清空历史、导出 CSV 审计台账
6. 窗口支持随时置顶 (Pin / Always on top)
"""

import os
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QToolButton,
    QPushButton, QListWidget, QListWidgetItem, QWidget,
    QLineEdit, QFileDialog, QMenu, QApplication
)
from qgis.PyQt.QtGui import QIcon, QColor, QFont
from qgis.PyQt.QtCore import Qt, QTimer, QSize
from ..core.compat import safe_exec, set_window_stay_on_top
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateTransform, QgsCsException, QgsRectangle, QgsFeatureRequest
)
from qgis.gui import QgsRubberBand

from ..core.history_manager import HistoryManager, HistoryStep
from ..i18n_helper import tr
from . import theme


class HistoryCardWidget(QWidget):
    """历史记录单项卡片组件 (紧凑面板卡片)"""

    def __init__(self, step: HistoryStep, on_revert_cb, parent=None):
        super().__init__(parent)
        self.step = step
        self.on_revert_cb = on_revert_cb
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        # 1. 工具类型徽章图标
        lbl_badge = QLabel()
        lbl_badge.setFixedSize(24, 24)
        lbl_badge.setAlignment(Qt.AlignCenter)
        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
        if self.step.tool_type == "painter":
            ic = QIcon(os.path.join(icons_dir, "painter.svg"))
            if not ic.isNull():
                lbl_badge.setPixmap(ic.pixmap(16, 16))
            else:
                lbl_badge.setText("🖌️")
            lbl_badge.setStyleSheet(
                "background-color: %s; border-radius: 4px;" % theme.ACCENT_TINT
            )
        else:
            ic = QIcon(os.path.join(icons_dir, "rank.svg"))
            if not ic.isNull():
                lbl_badge.setPixmap(ic.pixmap(16, 16))
            else:
                lbl_badge.setText("⚡")
            lbl_badge.setStyleSheet(
                "background-color: %s; border-radius: 4px;" % theme.PRIMARY_TINT
            )
        layout.addWidget(lbl_badge)

        # 2. 文本内容区
        vbox = QVBoxLayout()
        vbox.setSpacing(2)
        vbox.setContentsMargins(0, 0, 0, 0)

        # 第一行：字段名 + 新值 + 时间戳
        top_row = QHBoxLayout()
        top_row.setSpacing(4)

        target_display = str(self.step.target_value)
        if len(target_display) > 20:
            target_display = target_display[:18] + "..."

        lbl_action = QLabel(f"<b>[{self.step.field_name}]</b> ➔ \"{target_display}\"")
        font = lbl_action.font()
        font.setPointSize(9)
        if self.step.is_reverted:
            font.setStrikeOut(True)
            lbl_action.setStyleSheet("color: %s;" % theme.DISABLED_FG)
        else:
            lbl_action.setStyleSheet("color: %s;" % theme.FG)
        lbl_action.setFont(font)
        top_row.addWidget(lbl_action, 1)

        lbl_time = QLabel(self.step.timestamp)
        lbl_time.setStyleSheet("color: %s; font-size: 10px;" % theme.FG_MUTED)
        top_row.addWidget(lbl_time)
        vbox.addLayout(top_row)

        # 第二行：图层名 + 要素详情 + 回滚状态
        bot_row = QHBoxLayout()
        bot_row.setSpacing(4)

        if self.step.tool_type == "painter":
            fid_val = self.step.changes[0]["fid"] if self.step.changes else ""
            old_val = self.step.changes[0].get("old_val", "") if self.step.changes else ""
            old_display = str(old_val)
            if len(old_display) > 12:
                old_display = old_display[:10] + ".."
            detail_str = f"{self.step.layer_name} · FID {fid_val} ({tr('was')}: \"{old_display}\")"
        else:
            cnt = self.step.feature_count
            detail_str = f"{self.step.layer_name} · {cnt} {tr('features')}"

        lbl_detail = QLabel(detail_str)
        lbl_detail.setStyleSheet("color: %s; font-size: 10px;" % theme.FG_MUTED)
        bot_row.addWidget(lbl_detail, 1)

        if self.step.is_reverted:
            lbl_rev_tag = QLabel(f"[{tr('Reverted')}]")
            lbl_rev_tag.setStyleSheet("color: %s; font-size: 10px; font-weight: 600;" % theme.DANGER)
            bot_row.addWidget(lbl_rev_tag)

        vbox.addLayout(bot_row)
        layout.addLayout(vbox, 1)

        # 3. 单步还原快捷按钮
        self.btn_revert = QToolButton()
        self.btn_revert.setFixedSize(22, 22)
        if self.step.is_reverted:
            self.btn_revert.setText("✓")
            self.btn_revert.setEnabled(False)
            self.btn_revert.setStyleSheet("color: %s; border: none; background: transparent; font-weight: bold;" % theme.SUCCESS)
        else:
            icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
            undo_icon = QIcon(os.path.join(icons_dir, "undo_latest.svg"))
            if not undo_icon.isNull():
                self.btn_revert.setIcon(undo_icon)
                self.btn_revert.setIconSize(QSize(13, 13))
            else:
                self.btn_revert.setText("↺")
            self.btn_revert.setToolTip(tr("Revert this operation"))
            self.btn_revert.setStyleSheet("""
                QToolButton {
                    border: 1px solid %s; border-radius: 3px;
                    background-color: %s;
                }
                QToolButton:hover {
                    background-color: %s; border-color: %s;
                }
            """ % (theme.BORDER, theme.CARD, theme.HOVER_FILL, theme.PRIMARY))
            self.btn_revert.clicked.connect(lambda: self.on_revert_cb(self.step.id))
        layout.addWidget(self.btn_revert)


class HistoryDialog(QDialog):
    """
    QuickFieldBrush 历史记录面板
    """

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.mgr = HistoryManager.instance()
        self.is_pinned = True

        self.setWindowTitle(tr("QuickFieldBrush History"))
        self.resize(380, 520)
        self.setMinimumSize(320, 360)
        theme.apply_dialog_style(self)

        # 默认无模态 + 置顶
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        # 地图瞬时高亮橡皮筋
        self._flash_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self._flash_band.setColor(QColor(76, 175, 80, 130))
        self._flash_band.setStrokeColor(QColor(46, 125, 50, 255))
        self._flash_band.setWidth(3)

        self._init_ui()
        self._reload_history()

        # 监听历史变动信号
        self.mgr.history_changed.connect(self._reload_history)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")

        # 1. 顶部标题栏：图标 + 标题 + 置顶按钮
        top_bar = QHBoxLayout()
        lbl_icon = QLabel()
        history_icon_path = os.path.join(icons_dir, "history.svg")
        if os.path.exists(history_icon_path):
            lbl_icon.setPixmap(QIcon(history_icon_path).pixmap(18, 18))
        else:
            lbl_icon.setText("🕒")
            lbl_icon.setStyleSheet("font-size: 14px;")
        top_bar.addWidget(lbl_icon)

        lbl_title = QLabel(tr("Modification History"))
        lbl_title.setStyleSheet(theme.LABEL_TITLE_SS)
        top_bar.addWidget(lbl_title, 1)

        # 置顶切换按钮（纯图标两态：激活显示绿图钉，未激活显示灰图钉，无文字不形变）
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
        top_bar.addWidget(self.btn_pin)

        main_layout.addLayout(top_bar)

        # 2. 搜索/过滤栏
        search_box = QHBoxLayout()
        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText(tr("Search field, layer, or FID..."))
        search_icon = QIcon(os.path.join(icons_dir, "search.svg"))
        if not search_icon.isNull():
            self.txt_filter.addAction(search_icon, QLineEdit.LeadingPosition)
        self.txt_filter.setClearButtonEnabled(True)
        self.txt_filter.textChanged.connect(self._filter_items)
        self.txt_filter.setStyleSheet(theme.LINEEDIT_SS)
        search_box.addWidget(self.txt_filter)
        main_layout.addLayout(search_box)

        # 3. 历史记录列表 (QListWidget)
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                border: 1px solid %s; border-radius: 5px;
                background-color: %s;
            }
            QListWidget::item {
                border-bottom: 1px solid %s;
                padding: 1px;
            }
            QListWidget::item:selected {
                background-color: %s;
                border-radius: 4px;
            }
        """ % (theme.BORDER, theme.BG, theme.BORDER, theme.PRIMARY_TINT))
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        main_layout.addWidget(self.list_widget, 1)

        # 4. 底部操作栏
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(6)

        self.lbl_count = QLabel(tr("Total: 0 records"))
        self.lbl_count.setStyleSheet(theme.HINT_LABEL_SS)
        bottom_bar.addWidget(self.lbl_count, 1)

        # 撤销最近一步
        self.btn_undo_last = QPushButton(tr("Undo Latest"))
        undo_icon = QIcon(os.path.join(icons_dir, "undo_latest.svg"))
        if not undo_icon.isNull():
            self.btn_undo_last.setIcon(undo_icon)
            self.btn_undo_last.setIconSize(QSize(16, 16))
        self.btn_undo_last.setStyleSheet(theme.BUTTON_SECONDARY_SS)
        self.btn_undo_last.setToolTip(tr("Revert the most recent modification step"))
        self.btn_undo_last.clicked.connect(self._undo_latest)
        bottom_bar.addWidget(self.btn_undo_last)

        # 导出 CSV
        self.btn_export = QPushButton(tr("Export CSV"))
        export_icon = QIcon(os.path.join(icons_dir, "export.svg"))
        if not export_icon.isNull():
            self.btn_export.setIcon(export_icon)
            self.btn_export.setIconSize(QSize(16, 16))
        self.btn_export.setStyleSheet(theme.BUTTON_SECONDARY_SS)
        self.btn_export.setToolTip(tr("Export history log to CSV file"))
        self.btn_export.clicked.connect(self._export_csv)
        bottom_bar.addWidget(self.btn_export)

        main_layout.addLayout(bottom_bar)

    def _toggle_stay_on_top(self, checked):
        """置顶切换（0 闪烁无感切换）"""
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

    def _reload_history(self):
        """重新刷新加载历史记录列表（倒序显示：最新记录在最上方）"""
        self.list_widget.clear()
        steps = self.mgr.get_steps()
        total_count = len(steps)
        self.lbl_count.setText(tr("Total: {0} records").format(total_count))

        # 倒序展示：最新操作在顶部
        for step in reversed(steps):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, step.id)
            card = HistoryCardWidget(step, self._revert_step_by_id)
            item.setSizeHint(card.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)

        self._filter_items(self.txt_filter.text())

    def _filter_items(self, text: str):
        """按关键字过滤历史项"""
        query = text.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            step_id = item.data(Qt.UserRole)
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

    def _on_item_clicked(self, item):
        """单击条目：居中并闪烁高亮对应要素"""
        step_id = item.data(Qt.UserRole)
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

        # 获取要素几何
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
                # 计算中心点并在画布平移居中
                center_pt = geom.centroid().asPoint()
                if transform:
                    try:
                        center_pt = transform.transform(center_pt)
                    except (QgsCsException, RuntimeError, ValueError):
                        pass
                self.canvas.setCenter(center_pt)
                self.canvas.refresh()

                # 绿色高亮闪烁
                try:
                    self._flash_band.reset(geom.type())
                    self._flash_band.setToGeometry(geom, layer)
                    self._flash_band.show()
                    QTimer.singleShot(350, self._flash_band.reset)
                except (RuntimeError, TypeError, AttributeError):
                    pass
        else:
            # 批量要素：缩放到要素的外接矩形并闪烁
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
                    self._flash_band.reset(geoms[0].type())
                    for g in geoms:
                        self._flash_band.addGeometry(g, layer)
                    self._flash_band.show()
                    QTimer.singleShot(400, self._flash_band.reset)
                except (RuntimeError, TypeError, AttributeError):
                    pass

    def _on_item_double_clicked(self, item):
        """双击条目：选中对应要素并设为当前活动图层"""
        step_id = item.data(Qt.UserRole)
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
        item = self.list_widget.itemAt(pos)
        if not item:
            return

        step_id = item.data(Qt.UserRole)
        step = self.mgr.get_step_by_id(step_id)
        if not step:
            return

        menu = QMenu(self)
        menu.setStyleSheet(theme.MENU_SS)

        act_zoom = menu.addAction(tr("Zoom and highlight feature(s)"))
        act_zoom.triggered.connect(lambda: self._on_item_clicked(item))

        act_select = menu.addAction(tr("Select feature(s) in layer"))
        act_select.triggered.connect(lambda: self._on_item_double_clicked(item))

        menu.addSeparator()

        act_revert = menu.addAction(tr("Revert this operation"))
        act_revert.setEnabled(not step.is_reverted)
        act_revert.triggered.connect(lambda: self._revert_step_by_id(step.id))

        menu.addSeparator()

        act_copy_fids = menu.addAction(tr("Copy Feature ID(s) to Clipboard"))
        act_copy_fids.triggered.connect(lambda: QApplication.clipboard().setText(", ".join(map(str, step.fids))))

        safe_exec(menu, self.list_widget.mapToGlobal(pos))

    def _revert_step_by_id(self, step_id: int):
        """执行单步还原"""
        ok, msg = self.mgr.revert_step(step_id, self.iface)
        if ok:
            self.iface.messageBar().pushSuccess("QuickFieldBrush", msg)
        else:
            self.iface.messageBar().pushWarning("QuickFieldBrush", msg)

    def _undo_latest(self):
        """撤销最近一步尚未回滚的记录"""
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

    def closeEvent(self, event):
        if self._flash_band:
            self._flash_band.reset()
        super().closeEvent(event)
