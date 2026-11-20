# -*- coding: utf-8 -*-
"""
Attribute Table Fast Assign Manager & Delegate for QuickFieldBrush.
Injects an intelligent editable ComboBox with unique values into native QGIS Attribute Table,
with a real-time toggle integrated directly into the attribute table's top toolbar.
"""

import os
from qgis.PyQt.QtCore import Qt, QTimer, QObject, QSortFilterProxyModel
from qgis.PyQt.QtWidgets import (
    QTableView, QStyledItemDelegate, QComboBox, QCompleter, QApplication,
    QAbstractItemDelegate, QToolBar, QDialog
)
from qgis.PyQt.QtGui import QIcon, QCursor, QFont, QColor, QPalette
from qgis.gui import QgsAttributeTableFilterModel
from qgis.core import QgsVectorLayer, QgsMessageLog, Qgis

from .compat import QAction, sip
from .attribute_engine import AttributeEngine
from .config_manager import ConfigManager
from .history_manager import HistoryManager
from ..ui.valuemap_delegate import ValueMapComboDelegate, ROLE_RAW_HINT
from ..i18n_helper import tr

_QT_LIFECYCLE_ERRORS = (RuntimeError, ReferenceError, AttributeError, TypeError)
_ACTION_OBJ_NAME = "quickfieldbrush_action_table_fast_assign"


class FastAssignTableDelegate(QStyledItemDelegate):
    """
    智能属性表单元格委托：
    当功能开启、图层处于编辑状态且单元格被激活时，弹出带已有唯一值候选的 ComboBox，
    支持即时模糊搜索过滤、自由录入新值，点选选项后自动提交并记录撤销栈与历史台账。
    当功能关闭时，完全回退为 QGIS 原生编辑控件，实现毫秒级实时启闭。
    """

    def __init__(self, manager, layer, table_view, parent=None):
        super().__init__(parent or table_view)
        self.manager = manager
        self.layer = layer
        self.table_view = table_view

    def _is_field_editable(self, field_idx):
        if field_idx < 0 or field_idx >= self.layer.fields().count():
            return False
        field = self.layer.fields().at(field_idx)
        if field.name().lower() in ("fid", "id", "ogc_fid"):
            return False
        editable_fields = AttributeEngine.get_editable_fields(self.layer, include_icons=False)
        return any(f["name"] == field.name() for f in editable_fields)

    def createEditor(self, parent, option, index):
        if not self.manager or not self.manager.enabled:
            return super().createEditor(parent, option, index)

        if not self.layer or not self.layer.isEditable():
            return super().createEditor(parent, option, index)

        model = index.model()
        if not isinstance(model, (QgsAttributeTableFilterModel, QSortFilterProxyModel)):
            return super().createEditor(parent, option, index)

        try:
            filter_model = model if isinstance(model, QgsAttributeTableFilterModel) else sip.cast(model, QgsAttributeTableFilterModel)
            master = filter_model.masterModel()
            src_idx = filter_model.mapToSource(index)
            field_idx = master.fieldIdx(src_idx.column())
            fid = master.rowToId(src_idx.row())
        except _QT_LIFECYCLE_ERRORS:
            return super().createEditor(parent, option, index)

        if not self._is_field_editable(field_idx):
            return super().createEditor(parent, option, index)

        field = self.layer.fields().at(field_idx)

        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setMaxVisibleItems(15)
        combo.setItemDelegate(ValueMapComboDelegate(combo))
        combo.setProperty("field_idx", field_idx)
        combo.setProperty("fid", fid)

        edit_role = getattr(Qt.ItemDataRole, "EditRole", getattr(Qt, "EditRole", 2))
        raw_cell = index.data(edit_role)
        if raw_cell is None:
            raw_cell = index.data()
        combo.setProperty("raw_old_val", raw_cell)
        combo.setProperty("old_val", "" if AttributeEngine.is_empty_or_null(raw_cell) else str(raw_cell).strip())

        null_font = QFont(combo.font())
        null_font.setItalic(True)
        null_color = QColor(Qt.darkGray)

        combo.addItem("NULL", userData="")
        combo.setItemData(0, null_font, Qt.FontRole)
        combo.setItemData(0, null_color, Qt.ForegroundRole)

        value_map = AttributeEngine.get_value_map(self.layer, field_idx)
        try:
            cached_uniques = AttributeEngine.extract_unique_values(self.layer, field.name())
            seen = set()
            for v in cached_uniques:
                if not AttributeEngine.is_empty_or_null(v):
                    s = str(v).strip()
                    if s and s not in seen:
                        seen.add(s)
                        display_label, raw_hint = AttributeEngine.get_value_display_parts(value_map, s)
                        combo.addItem(display_label, userData=s)
                        if raw_hint:
                            combo.setItemData(combo.count() - 1, raw_hint, ROLE_RAW_HINT)
        except (RuntimeError, AttributeError, TypeError, ValueError) as err:
            QgsMessageLog.logMessage(
                f"Table fast assign unique value load failed: {err}",
                "QuickFieldBrush",
                Qgis.MessageLevel.Info,
            )

        completer = QCompleter(combo.model(), combo)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        combo.setCompleter(completer)

        combo.activated.connect(lambda _: self._commit_and_close(combo))
        combo.currentTextChanged.connect(lambda txt: self._update_line_edit_style(combo, txt))

        # 仅当用户明确点击单元格右侧的下拉箭头区域时才自动展开下拉清单
        if self._clicked_on_dropdown_arrow(index):
            def safe_show_popup():
                try:
                    if combo is not None and not sip.isdeleted(combo) and combo.isVisible():
                        combo.showPopup()
                except _QT_LIFECYCLE_ERRORS:
                    return
            QTimer.singleShot(50, safe_show_popup)

        return combo

    def _clicked_on_dropdown_arrow(self, index):
        try:
            if not self.table_view:
                return False
            vpos = self.table_view.viewport().mapFromGlobal(QCursor.pos())
            crect = self.table_view.visualRect(index)
            return (crect.x() + crect.width() - vpos.x()) <= 24
        except _QT_LIFECYCLE_ERRORS:
            return False

    def _commit_and_close(self, combo):
        try:
            if combo is None or sip.isdeleted(combo):
                return
            self._commit_value(combo)

            def deferred_close():
                try:
                    if combo is not None and not sip.isdeleted(combo):
                        self.closeEditor.emit(combo, QAbstractItemDelegate.NoHint)
                except _QT_LIFECYCLE_ERRORS:
                    return

            QTimer.singleShot(0, deferred_close)
        except _QT_LIFECYCLE_ERRORS:
            return

    def _commit_value(self, combo):
        try:
            if combo is None or sip.isdeleted(combo):
                return
            if combo.property("_committed"):
                return

            fid = combo.property("fid")
            field_idx = combo.property("field_idx")
            old_val = str(combo.property("old_val") or "").strip()
            raw_old_val = combo.property("raw_old_val")
            if fid is None or field_idx is None:
                return

            new_text = combo.currentText().strip()
            new_val = new_text
            cur_idx = combo.currentIndex()
            if cur_idx >= 0 and combo.itemText(cur_idx).strip() == new_text:
                item_data = combo.itemData(cur_idx)
                if item_data not in (None, ""):
                    new_val = str(item_data).strip()

            is_old_null = AttributeEngine.is_empty_or_null(old_val)
            is_new_null = AttributeEngine.is_empty_or_null(new_val)

            if (is_old_null and is_new_null) or (not is_old_null and not is_new_null and new_val == old_val):
                combo.setProperty("_committed", True)
                return

            field = self.layer.fields().at(field_idx)
            try:
                val_to_write = None if is_new_null else AttributeEngine.convert_value_for_field(field, new_val)
            except ValueError as conv_err:
                if self.manager and self.manager.iface:
                    self.manager.iface.messageBar().pushWarning("QuickFieldBrush", str(conv_err))
                return

            val_display = "NULL" if val_to_write is None else str(val_to_write)
            self.layer.beginEditCommand(tr("QuickFieldBrush: set {0}={1}").format(field.name(), val_display))
            AttributeEngine._in_internal_edit = True
            try:
                if not self.layer.changeAttributeValue(fid, field_idx, val_to_write):
                    self.layer.destroyEditCommand()
                    return
                self.layer.endEditCommand()

                changes = [{"fid": fid, "old_val": raw_old_val, "new_val": val_to_write}]
                AttributeEngine.update_cache_after_edit(self.layer, field.name(), changes)
                HistoryManager.instance().add_step(
                    tool_type="table_assign",
                    layer=self.layer,
                    field_name=field.name(),
                    target_value=val_to_write,
                    changes=changes,
                )
            finally:
                AttributeEngine._in_internal_edit = False

            combo.setProperty("raw_old_val", val_to_write)
            combo.setProperty("old_val", "NULL" if val_to_write is None else str(val_to_write))
            combo.setProperty("_committed", True)
        except _QT_LIFECYCLE_ERRORS as err:
            QgsMessageLog.logMessage(
                f"FastAssignTableDelegate commit failed: {err}",
                "QuickFieldBrush",
                Qgis.MessageLevel.Warning,
            )

    def _update_line_edit_style(self, combo, text):
        try:
            if combo is None or sip.isdeleted(combo):
                return
            le = combo.lineEdit()
            if le is not None and not sip.isdeleted(le):
                is_null = AttributeEngine.is_empty_or_null(text)
                f = QFont(combo.font())
                f.setItalic(is_null)
                le.setFont(f)
                pal = le.palette()
                text_color = Qt.darkGray if is_null else QApplication.palette().color(QPalette.Text)
                pal.setColor(QPalette.Text, text_color)
                le.setPalette(pal)
        except _QT_LIFECYCLE_ERRORS:
            return

    def setEditorData(self, editor, index):
        try:
            if editor is None or sip.isdeleted(editor):
                return
            if not isinstance(editor, QComboBox):
                super().setEditorData(editor, index)
                return

            edit_role = getattr(Qt.ItemDataRole, "EditRole", getattr(Qt, "EditRole", 2))
            raw_data = index.data(edit_role)
            if raw_data is None:
                raw_data = index.data()
            current_val = "NULL" if AttributeEngine.is_empty_or_null(raw_data) else str(raw_data).strip()

            match_idx = editor.findData(current_val) if current_val != "NULL" else 0
            if match_idx < 0:
                match_idx = editor.findText(current_val)
            if match_idx >= 0:
                editor.setCurrentIndex(match_idx)
            else:
                editor.setEditText(current_val)

            self._update_line_edit_style(editor, editor.currentText())

            le = editor.lineEdit()
            if le is not None and not sip.isdeleted(le):
                le.selectAll()
        except _QT_LIFECYCLE_ERRORS:
            return

    def setModelData(self, editor, model, index):
        try:
            if editor is None or sip.isdeleted(editor):
                return
            if isinstance(editor, QComboBox):
                self._commit_value(editor)
            else:
                super().setModelData(editor, model, index)
        except _QT_LIFECYCLE_ERRORS:
            return

    def destroyEditor(self, editor, index):
        try:
            if editor is not None and not sip.isdeleted(editor):
                super().destroyEditor(editor, index)
        except _QT_LIFECYCLE_ERRORS:
            return

    def updateEditorGeometry(self, editor, option, index):
        try:
            if editor is not None and not sip.isdeleted(editor):
                super().updateEditorGeometry(editor, option, index)
        except _QT_LIFECYCLE_ERRORS:
            return

    def eventFilter(self, obj, event):
        try:
            if obj is None or sip.isdeleted(obj):
                return False
            return super().eventFilter(obj, event)
        except _QT_LIFECYCLE_ERRORS:
            return False


class AttributeTableManager(QObject):
    """
    管理所有打开的属性表窗口：
    1. 为图层属性表安装 FastAssignTableDelegate；
    2. 在属性表顶部的工具栏 (mToolbar) 中自动集成『快速下拉赋值』切换按钮，随表启闭；
    3. 全局状态实时同步，点击开关毫秒级生效，无需重开属性表。
    """

    def __init__(self, iface, config=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.config = config if isinstance(config, dict) else {}

        self.enabled = self.config.get("behavior", {}).get("table_fast_assign", True)
        self._delegates = {}          # dlg_key -> [FastAssignTableDelegate]
        self._toolbar_actions = {}    # dlg_key -> (QAction, QAction_separator)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._scan_and_bind_tables)
        self._timer.start(600)

    def set_enabled(self, enabled):
        """设置全局启用状态，持久化配置并同步所有已打开属性表的工具栏按钮"""
        self.enabled = bool(enabled)
        self.config.setdefault("behavior", {})["table_fast_assign"] = self.enabled
        ConfigManager.update_section("behavior", {"table_fast_assign": self.enabled})

        for _, (act, _) in list(self._toolbar_actions.items()):
            try:
                if act and not sip.isdeleted(act) and act.isChecked() != self.enabled:
                    act.blockSignals(True)
                    act.setChecked(self.enabled)
                    act.blockSignals(False)
            except _QT_LIFECYCLE_ERRORS:
                continue

    def _iter_attribute_table_dialogs(self):
        """仅查找真正的 QGIS 属性表对话框（objectName 以 QgsAttributeTableDialog/ 开头），绝不触碰数据源管理器等其它窗口"""
        seen = set()
        for top in QApplication.topLevelWidgets():
            try:
                if top is None or sip.isdeleted(top) or not top.isVisible():
                    continue
                candidates = [top] + top.findChildren(QDialog)
                for w in candidates:
                    if w is None or sip.isdeleted(w) or not w.isVisible():
                        continue
                    if w.objectName().startswith("QgsAttributeTableDialog/"):
                        try:
                            dlg_key = sip.unwrapinstance(w)
                        except (TypeError, RuntimeError):
                            dlg_key = id(w)
                        if dlg_key not in seen:
                            seen.add(dlg_key)
                            yield dlg_key, w
            except _QT_LIFECYCLE_ERRORS:
                continue

    def _scan_and_bind_tables(self):
        """扫描属性表对话框 (仅匹配 QgsAttributeTableDialog/*)"""
        for dlg_key, widget in self._iter_attribute_table_dialogs():
            try:
                tv = widget.findChild(QTableView, "mTableView")
                if not tv or not isinstance(tv.model(), (QgsAttributeTableFilterModel, QSortFilterProxyModel)):
                    continue
            except _QT_LIFECYCLE_ERRORS:
                continue

            self._ensure_toolbar_action(widget, dlg_key)

            d0 = tv.itemDelegateForColumn(0)
            needs_bind = (
                dlg_key not in self._delegates
                or d0 is None
                or d0.__class__ is not FastAssignTableDelegate
            )
            if not needs_bind:
                continue

            try:
                raw_model = tv.model()
                filter_model = raw_model if isinstance(raw_model, QgsAttributeTableFilterModel) else sip.cast(raw_model, QgsAttributeTableFilterModel)
                layer = filter_model.layer()
                if not layer or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                    continue

                col_count = tv.model().columnCount()
                delegates = []
                for col in range(col_count):
                    deleg = FastAssignTableDelegate(self, layer, tv, widget)
                    tv.setItemDelegateForColumn(col, deleg)
                    delegates.append(deleg)

                self._delegates[dlg_key] = delegates
                widget.destroyed.connect(lambda _, k=dlg_key: self._on_dialog_destroyed(k))
            except _QT_LIFECYCLE_ERRORS:
                continue

    def _ensure_toolbar_action(self, widget, dlg_key):
        """在属性表对话框顶部的 mToolbar 中注入控制开关按钮"""
        if dlg_key in self._toolbar_actions:
            act, _ = self._toolbar_actions[dlg_key]
            try:
                if act and not sip.isdeleted(act):
                    return
            except _QT_LIFECYCLE_ERRORS:
                pass

        tb = widget.findChild(QToolBar, "mToolbar")
        if not tb:
            tbs = widget.findChildren(QToolBar)
            tb = tbs[0] if tbs else None
        if not tb:
            return

        for existing in tb.actions():
            if existing.objectName() == _ACTION_OBJ_NAME:
                self._toolbar_actions[dlg_key] = (existing, None)
                return

        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
        icon_path = os.path.join(icons_dir, "table_assign.svg")

        sep = tb.addSeparator()
        action = QAction(QIcon(icon_path), tr("Table Fast Assign"), tb)
        action.setObjectName(_ACTION_OBJ_NAME)
        action.setCheckable(True)
        action.setChecked(self.enabled)
        action.setToolTip(tr("Enable/disable attribute table fast assign dropdown"))
        action.toggled.connect(self._on_action_toggled)
        tb.addAction(action)

        self._toolbar_actions[dlg_key] = (action, sep)

    def _on_action_toggled(self, checked):
        self.set_enabled(checked)

    def _on_dialog_destroyed(self, dlg_key):
        self._delegates.pop(dlg_key, None)
        self._toolbar_actions.pop(dlg_key, None)

    def _unbind_all(self):
        for widget in QApplication.topLevelWidgets():
            try:
                tv = widget.findChild(QTableView, "mTableView")
                if tv and tv.model():
                    for col in range(tv.model().columnCount()):
                        tv.setItemDelegateForColumn(col, None)
            except _QT_LIFECYCLE_ERRORS:
                continue
        self._delegates.clear()

        for _, (act, sep) in list(self._toolbar_actions.items()):
            try:
                if act and not sip.isdeleted(act) and act.parentWidget():
                    act.parentWidget().removeAction(act)
                if sep and not sip.isdeleted(sep) and sep.parentWidget():
                    sep.parentWidget().removeAction(sep)
            except _QT_LIFECYCLE_ERRORS:
                continue
        self._toolbar_actions.clear()

    def cleanup(self):
        self._timer.stop()
        self._unbind_all()
