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
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QPushButton, QLabel, QToolButton,
    QInputDialog, QStackedWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QSizePolicy
)
from qgis.gui import QgsDockWidget
from qgis.PyQt.QtGui import QIcon, QGuiApplication
from qgis.PyQt.QtCore import Qt, pyqtSignal, QSize, QTimer
from qgis.core import QgsVectorLayer, QgsApplication
from ..core.compat import set_window_stay_on_top
from ..core.attribute_engine import AttributeEngine
from ..core.config_manager import ConfigManager
from ..i18n_helper import tr
from . import theme
from .valuemap_delegate import ValueMapComboDelegate, ROLE_RAW_HINT


class FormatPainterDockWidget(QgsDockWidget):
    targetChanged = pyqtSignal(str, str)  # 字段或属性值改变时通知画笔工具

    def __init__(self, iface, painter_tool, parent=None):
        super().__init__(tr("Attribute Format Painter (console)"), parent or iface.mainWindow())
        self.setObjectName("QuickFieldBrushPainterDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea)
        self.iface = iface
        self.painter_tool = painter_tool
        self.layer = iface.activeLayer()
        self.config = ConfigManager.get_config()
        self.is_pinned = True  # 默认置顶
        self._prev_val_idx = 0
        self.current_sort_dim = "freq"  # "freq" 或 "alpha"
        self.sort_alpha_dir = "asc"      # "asc" 或 "desc"
        self.sort_freq_dir = "desc"      # "desc" 或 "asc"
        self._cached_val_counts = []
        self._multi_mode = False
        self._multi_loading = False
        self._single_height = 200
        self._multi_height = 380

        self.setWindowTitle(tr("Attribute Format Painter (console)"))
        self.setFloating(True)
        self.resize(310, self._single_height)

        self._init_ui()
        self._load_fields()

        # 绑定地图工具的吸取回调
        if hasattr(self.painter_tool, "on_feature_picked"):
            self.painter_tool.on_feature_picked = self._on_feature_absorbed_from_map
        if hasattr(self.painter_tool, "on_multi_feature_picked"):
            self.painter_tool.on_multi_feature_picked = self._on_multi_feature_absorbed_from_map

        # 监听激活图层切换信号，动态同步当前可用字段，避免悬浮窗引用失效 C++ 对象
        self.iface.currentLayerChanged.connect(self._on_layer_changed)

        # 监听浮动/停靠状态切换
        self.topLevelChanged.connect(self._on_top_level_changed)

    def refresh_state(self):
        """重新打开面板时刷新配置、当前活动图层字段与画笔绑定状态"""
        self.config = ConfigManager.get_config()
        self._reset_absorb_btn_text()
        self._load_fields()

    def _init_ui(self):
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        import os
        icons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")

        # 1. 顶部微标题栏：图标 + 标题 + 置顶按钮（仅悬浮时显示，停靠时由 QGIS 原生标题栏承载）
        self.top_bar_widget = QWidget()
        top_bar = QHBoxLayout(self.top_bar_widget)
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(6)

        lbl_icon = QLabel()
        painter_icon_path = os.path.join(icons_dir, "painter.svg")
        if os.path.exists(painter_icon_path):
            lbl_icon.setPixmap(QIcon(painter_icon_path).pixmap(16, 16))
        else:
            lbl_icon.setText("🖌️")
        top_bar.addWidget(lbl_icon)

        lbl_title = QLabel(tr("Attribute Format Painter (console)"))
        lbl_title.setStyleSheet(theme.LABEL_TITLE_SS)
        top_bar.addWidget(lbl_title, 1)

        # 置顶切换按钮（移至右上角，与历史面板完全一致）
        self.btn_pin = QToolButton()
        self.btn_pin.setFixedSize(22, 22)
        self.btn_pin.setCheckable(True)
        self.btn_pin.setChecked(True)
        self.btn_pin.setAutoRaise(True)
        self._icon_pin_on = QIcon(os.path.join(icons_dir, "pin_green.svg"))
        self._icon_pin_off = QIcon(os.path.join(icons_dir, "pin_grey.svg"))
        if not self._icon_pin_on.isNull():
            self.btn_pin.setIcon(self._icon_pin_on)
            self.btn_pin.setIconSize(QSize(14, 14))
        self.btn_pin.setToolTip(tr("Always on top (click to disable)"))
        self.btn_pin.toggled.connect(self._toggle_stay_on_top)
        top_bar.addWidget(self.btn_pin)

        layout.addWidget(self.top_bar_widget)

        # 1b. 模式切换栏：单字段 vs 多字段组合模板
        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(4)
        mode_bar.setContentsMargins(0, 0, 0, 0)

        self.btn_mode_single = QPushButton(tr("Single Field"))
        self.btn_mode_single.setCheckable(True)
        self.btn_mode_single.setChecked(True)
        self.btn_mode_single.clicked.connect(lambda: self._switch_mode(False))
        mode_bar.addWidget(self.btn_mode_single, 1)

        self.btn_mode_multi = QPushButton(tr("Multi-Field"))
        self.btn_mode_multi.setCheckable(True)
        self.btn_mode_multi.setChecked(False)
        self.btn_mode_multi.clicked.connect(lambda: self._switch_mode(True))
        mode_bar.addWidget(self.btn_mode_multi, 1)

        layout.addLayout(mode_bar)

        self.mode_stack = QStackedWidget()

        # ---- Page 0: 单字段模式 ----
        self._page_single = QWidget()
        single_layout = QVBoxLayout(self._page_single)
        single_layout.setContentsMargins(0, 0, 0, 0)
        single_layout.setSpacing(0)
        form = QFormLayout()
        form.setSpacing(6)
        form.setContentsMargins(0, 0, 0, 0)

        # 第一行：目标字段通栏下拉框
        self.combo_field = QComboBox()
        self.combo_field.currentIndexChanged.connect(self._on_field_changed)
        form.addRow(tr("Target field"), self.combo_field)

        # 第二行：属性值 + 字母排序 + 频次排序
        val_box = QHBoxLayout()
        val_box.setSpacing(4)
        val_box.setContentsMargins(0, 0, 0, 0)

        self.combo_val = QComboBox()
        self.combo_val.setEditable(True)
        self.combo_val.setItemDelegate(ValueMapComboDelegate(self.combo_val))
        self.combo_val.lineEdit().setPlaceholderText(tr("Select or type the value to paint"))
        self.combo_val.currentIndexChanged.connect(self._on_val_index_changed)
        self.combo_val.lineEdit().textChanged.connect(self._on_value_changed)
        val_box.addWidget(self.combo_val, 1)

        # 排序按钮 1：字母维 (A->Z / Z->A 两态翻转)
        self._icon_alpha_asc = QIcon(os.path.join(icons_dir, "sort-AZ.svg"))
        self._icon_alpha_desc = QIcon(os.path.join(icons_dir, "sort-reverse-ZA.svg"))
        self.btn_sort_alpha = QToolButton()
        self.btn_sort_alpha.setFixedSize(22, 22)
        self.btn_sort_alpha.setCheckable(True)
        self.btn_sort_alpha.setChecked(False)
        self.btn_sort_alpha.setAutoRaise(True)
        self.btn_sort_alpha.setIcon(self._icon_alpha_asc)
        self.btn_sort_alpha.setIconSize(QSize(15, 15))
        self.btn_sort_alpha.setToolTip(tr("Alphabetical Ascending (A -> Z)"))
        self.btn_sort_alpha.clicked.connect(self._on_sort_alpha_clicked)
        val_box.addWidget(self.btn_sort_alpha)

        # 排序按钮 2：频次维 (多->少 / 少->多 两态翻转，默认激活高频优先)
        self._icon_freq_desc = QIcon(os.path.join(icons_dir, "sort-dscend.svg"))
        self._icon_freq_asc = QIcon(os.path.join(icons_dir, "sort-ascend.svg"))
        self.btn_sort_freq = QToolButton()
        self.btn_sort_freq.setFixedSize(22, 22)
        self.btn_sort_freq.setCheckable(True)
        self.btn_sort_freq.setChecked(True)
        self.btn_sort_freq.setAutoRaise(True)
        self.btn_sort_freq.setIcon(self._icon_freq_desc)
        self.btn_sort_freq.setIconSize(QSize(15, 15))
        self.btn_sort_freq.setToolTip(tr("Frequency Descending (Most frequent first)"))
        self.btn_sort_freq.clicked.connect(self._on_sort_freq_clicked)
        val_box.addWidget(self.btn_sort_freq)

        form.addRow(tr("Attribute value"), val_box)
        single_layout.addLayout(form)
        single_layout.addStretch(1)

        self.mode_stack.addWidget(self._page_single)

        # ---- Page 1: 多字段组合模板模式 ----
        self._page_multi = QWidget()
        sp_ignored = getattr(QSizePolicy.Policy, "Ignored", getattr(QSizePolicy, "Ignored", 13))
        sp_pref = getattr(QSizePolicy.Policy, "Preferred", getattr(QSizePolicy, "Preferred", 5))
        self._page_multi.setSizePolicy(sp_pref, sp_ignored)
        multi_layout = QVBoxLayout(self._page_multi)
        multi_layout.setContentsMargins(0, 0, 0, 0)
        multi_layout.setSpacing(6)

        tpl_bar = QHBoxLayout()
        tpl_bar.setSpacing(4)
        self.combo_tpl = QComboBox()
        self.combo_tpl.currentIndexChanged.connect(self._on_template_selected)
        tpl_bar.addWidget(self.combo_tpl, 1)

        self.btn_save_tpl = QToolButton()
        self.btn_save_tpl.setText("+")
        self.btn_save_tpl.setFixedSize(24, 24)
        self.btn_save_tpl.setToolTip(tr("Save current checked fields as a named combo template"))
        self.btn_save_tpl.clicked.connect(self._on_save_template_clicked)
        tpl_bar.addWidget(self.btn_save_tpl)

        self.btn_del_tpl = QToolButton()
        self.btn_del_tpl.setText("×")
        self.btn_del_tpl.setFixedSize(24, 24)
        self.btn_del_tpl.setToolTip(tr("Delete selected combo template"))
        self.btn_del_tpl.clicked.connect(self._on_delete_template_clicked)
        tpl_bar.addWidget(self.btn_del_tpl)

        multi_layout.addLayout(tpl_bar)

        self.multi_table = QTableWidget(0, 2)
        self.multi_table.setHorizontalHeaderLabels([tr("Field"), tr("Value")])
        self.multi_table.verticalHeader().setVisible(False)
        self.multi_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.multi_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.multi_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.multi_table.setMinimumHeight(0)
        self.multi_table.itemChanged.connect(self._on_multi_table_item_changed)
        multi_layout.addWidget(self.multi_table, 1)

        self.btn_apply_multi = QPushButton(tr("Apply combo to selected features"))
        self.btn_apply_multi.clicked.connect(self._on_apply_multi_to_selected)
        multi_layout.addWidget(self.btn_apply_multi)

        self.mode_stack.addWidget(self._page_multi)
        layout.addWidget(self.mode_stack, 1)

        # 3. 第三行：当前刷入状态提示
        self.lbl_status = QLabel(tr("Status: pick a field and value first"))
        layout.addWidget(self.lbl_status)

        layout.addSpacing(2)

        # 4. 最下边的一行：吸取属性、置空为 NULL、退出按钮
        action_box = QHBoxLayout()
        action_box.setSpacing(6)

        self.btn_pick_from_selected = QPushButton(tr("Absorb attribute from feature"))
        absorb_icon = QIcon(os.path.join(icons_dir, "absorb.svg"))
        if not absorb_icon.isNull():
            self.btn_pick_from_selected.setIcon(absorb_icon)
            self.btn_pick_from_selected.setIconSize(QSize(15, 15))
        self.btn_pick_from_selected.setToolTip(tr("Click to enter eyedropper mode, or right-click any feature on map to absorb its value"))
        self.btn_pick_from_selected.clicked.connect(self._toggle_pick_mode)
        action_box.addWidget(self.btn_pick_from_selected, 2)

        self.btn_clear_null = QPushButton(tr("Set to NULL"))
        null_path = os.path.join(icons_dir, "clear.svg")
        ic_null = QIcon(null_path) if os.path.exists(null_path) else QgsApplication.getThemeIcon("mIconClearText.svg")
        self.btn_clear_null.setIcon(ic_null)
        self.btn_clear_null.setIconSize(QSize(15, 15))
        self.btn_clear_null.setToolTip(tr("Set painter value to NULL, or batch clear selected features"))
        self.btn_clear_null.clicked.connect(self._on_set_null_clicked)
        action_box.addWidget(self.btn_clear_null, 1)

        layout.addLayout(action_box)

        self.btn_close = QPushButton(tr("Exit format painter (Esc)"))
        self.btn_close.clicked.connect(self.close)
        layout.addWidget(self.btn_close)

        self.setWidget(container)

    def _on_top_level_changed(self, is_floating):
        """当面板在浮动窗口与侧边停靠之间切换时触发"""
        self.top_bar_widget.setVisible(is_floating)
        if is_floating:
            self.btn_pin.setEnabled(True)
            if self.is_pinned:
                set_window_stay_on_top(self, True)
            self.btn_pin.setToolTip(tr("Always on top (click to disable)") if self.is_pinned else tr("Not on top (click to enable)"))
        else:
            self.btn_pin.setEnabled(False)
            self.btn_pin.setToolTip(tr("Docked in main window (pin available when floating)"))

    def _toggle_stay_on_top(self, checked):
        """动态切换窗口置顶状态（0 闪烁无感切换）"""
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

    def keyPressEvent(self, event):
        """Esc 键退出格式刷"""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
        else:
            super().keyPressEvent(event)

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
            self.combo_val.blockSignals(True)
            self.combo_val.clear()
            self.combo_val.blockSignals(False)
            self.painter_tool.set_target(None, None)
            self.lbl_status.setText(tr("Status: pick a field and value first"))
            return

        fields = AttributeEngine.get_editable_fields(self.layer)
        for f in fields:
            self.combo_field.addItem(f.get("icon", QIcon()), f['name'], f['name'])

        # 优先选中上次使用的字段或配置字段
        fp_cfg = self.config.get("format_painter", {})
        default_field = (
            fp_cfg.get("field_name")
            or self.config.get("single_rank_by_layer", {}).get(self.layer.id())
            or self.config.get("single_rank", {}).get("field_name")
        )
        if default_field:
            idx = self.combo_field.findData(default_field)
            if idx != -1:
                self.combo_field.setCurrentIndex(idx)

        self.combo_field.blockSignals(False)
        self._on_field_changed()
        self._load_multi_fields()
        self._load_multi_templates()

    def _on_sort_alpha_clicked(self):
        """点击首字母排序按钮：在 A->Z 与 Z->A 间翻转，并互斥取消频次排序"""
        if self.current_sort_dim != "alpha":
            self.current_sort_dim = "alpha"
            self.btn_sort_alpha.setChecked(True)
            self.btn_sort_freq.setChecked(False)
        else:
            self.sort_alpha_dir = "desc" if self.sort_alpha_dir == "asc" else "asc"
            self.btn_sort_alpha.setChecked(True)

        if self.sort_alpha_dir == "asc":
            self.btn_sort_alpha.setIcon(self._icon_alpha_asc)
            self.btn_sort_alpha.setToolTip(tr("Alphabetical Ascending (A -> Z)"))
        else:
            self.btn_sort_alpha.setIcon(self._icon_alpha_desc)
            self.btn_sort_alpha.setToolTip(tr("Alphabetical Descending (Z -> A)"))

        self._populate_val_combo()

    def _on_sort_freq_clicked(self):
        """点击频次排序按钮：在 多->少 与 少->多 间翻转，并互斥取消字母排序"""
        if self.current_sort_dim != "freq":
            self.current_sort_dim = "freq"
            self.btn_sort_freq.setChecked(True)
            self.btn_sort_alpha.setChecked(False)
        else:
            self.sort_freq_dir = "asc" if self.sort_freq_dir == "desc" else "desc"
            self.btn_sort_freq.setChecked(True)

        if self.sort_freq_dir == "desc":
            self.btn_sort_freq.setIcon(self._icon_freq_desc)
            self.btn_sort_freq.setToolTip(tr("Frequency Descending (Most frequent first)"))
        else:
            self.btn_sort_freq.setIcon(self._icon_freq_asc)
            self.btn_sort_freq.setToolTip(tr("Frequency Ascending (Least frequent first)"))

        self._populate_val_combo()

    def _extract_current_value(self) -> str:
        """从可编辑下拉框中提取真实目标属性值（优先尊重用户在输入框中手动输入的文本）"""
        txt = self.combo_val.currentText().strip()
        empty_placeholder = tr("(no values yet in this layer)")
        add_custom_label = "➕ " + tr("Enter a new value...")
        null_label = "∅ " + tr("Set to NULL (Clear field)")
        if txt in ("", empty_placeholder, add_custom_label):
            return ""
        if txt == null_label or txt.upper() == "NULL" or self.combo_val.currentData() == "__set_null_value__":
            return "__NULL__"
        cur_idx = self.combo_val.currentIndex()
        if cur_idx >= 0 and self.combo_val.itemText(cur_idx).strip() == txt:
            data = self.combo_val.itemData(cur_idx)
            if data not in (None, "", "__custom_add_value__", "__set_null_value__"):
                return str(data)
        return txt

    def _on_field_changed(self):
        fname = self.combo_field.currentData()
        self._cached_val_counts = []
        self._current_value_map = {}
        if self.layer and isinstance(self.layer, QgsVectorLayer) and self.layer.isValid() and fname:
            self._cached_val_counts = AttributeEngine.extract_unique_values_with_counts(self.layer, fname)
            self._current_value_map = AttributeEngine.get_value_map(self.layer, fname)
        self._populate_val_combo(initial_load=True)

    def _populate_val_combo(self, initial_load=False):
        current_text = self._extract_current_value()
        self.combo_val.blockSignals(True)
        self.combo_val.clear()
        self._prev_val_idx = 0

        val_counts = list(self._cached_val_counts) if hasattr(self, "_cached_val_counts") else []

        # 排序计算（支持自然序及频次同频自然序）
        if self.current_sort_dim == "freq":
            if self.sort_freq_dir == "desc":
                val_counts_sorted = sorted(
                    val_counts,
                    key=lambda x: (-(x[1] if x[1] is not None else 0), AttributeEngine.natural_sort_key(x[0]))
                )
            else:
                val_counts_sorted = sorted(
                    val_counts,
                    key=lambda x: ((x[1] if x[1] is not None else 0), AttributeEngine.natural_sort_key(x[0]))
                )
        else:
            rev = (self.sort_alpha_dir == "desc")
            val_counts_sorted = sorted(val_counts, key=lambda x: AttributeEngine.natural_sort_key(x[0]), reverse=rev)

        value_map = getattr(self, "_current_value_map", {})
        has_values = False
        for val, cnt in val_counts_sorted:
            if AttributeEngine.is_empty_or_null(val):
                continue
            display_label, raw_hint = AttributeEngine.get_value_display_parts(value_map, val)
            self.combo_val.addItem(display_label, userData=str(val))
            if raw_hint:
                self.combo_val.setItemData(self.combo_val.count() - 1, raw_hint, ROLE_RAW_HINT)
            has_values = True

        if not has_values:
            self.combo_val.addItem(tr("(no values yet in this layer)"), userData="")

        # 添加「输入新值...」选项
        self.combo_val.addItem("➕ " + tr("Enter a new value..."), userData="__custom_add_value__")
        # 添加「设为 NULL / 清空字段」选项
        self.combo_val.addItem("∅ " + tr("Set to NULL (Clear field)"), userData="__set_null_value__")

        # 保持或恢复选中项
        matched = False
        if not initial_load and current_text:
            if current_text == "__NULL__":
                idx = self.combo_val.findData("__set_null_value__")
                if idx != -1:
                    self.combo_val.setCurrentIndex(idx)
                    self._prev_val_idx = idx
                    matched = True
            else:
                idx = self.combo_val.findData(current_text)
                if idx != -1:
                    self.combo_val.setCurrentIndex(idx)
                    self._prev_val_idx = idx
                    matched = True
                else:
                    self.combo_val.setEditText(current_text)
                    matched = True
        elif initial_load:
            fp_cfg = self.config.get("format_painter", {})
            last_field = fp_cfg.get("field_name")
            last_val = fp_cfg.get("value")
            cur_field = self.combo_field.currentData()
            if last_val:
                idx = self.combo_val.findData(str(last_val))
                if idx != -1:
                    self.combo_val.setCurrentIndex(idx)
                    self._prev_val_idx = idx
                    matched = True
                elif last_field and last_field == cur_field:
                    # 同一字段下用户曾自定义输入过尚未写入图层的候选值，予以保留
                    insert_pos = max(0, self.combo_val.count() - 1)
                    self.combo_val.insertItem(insert_pos, str(last_val), userData=str(last_val))
                    self.combo_val.setCurrentIndex(insert_pos)
                    self._prev_val_idx = insert_pos
                    matched = True

        if not matched:
            if has_values:
                self.combo_val.setCurrentIndex(0)
                self._prev_val_idx = 0
            else:
                self.combo_val.setCurrentIndex(0)
                self.combo_val.setEditText("")
                self._prev_val_idx = 0

        self.combo_val.blockSignals(False)
        self._sync_target_to_tool()

    def _on_val_index_changed(self, idx):
        if idx < 0:
            return
        data = self.combo_val.itemData(idx)
        if data == "__custom_add_value__":
            fname = self.combo_field.currentData() or ""
            new_val, ok = QInputDialog.getText(
                self,
                tr("Add New Attribute Value"),
                tr("Enter new value for [{0}]:").format(fname)
            )
            if ok:
                clean_val = new_val.strip()
                if clean_val == "" or clean_val.upper() == "NULL":
                    # 自动规整为 NULL
                    self.combo_val.blockSignals(True)
                    null_idx = self.combo_val.findData("__set_null_value__")
                    if null_idx != -1:
                        self.combo_val.setCurrentIndex(null_idx)
                    self.combo_val.setEditText("NULL")
                    self._prev_val_idx = self.combo_val.currentIndex()
                    self.combo_val.blockSignals(False)
                    self._sync_target_to_tool()
                else:
                    found_idx = -1
                    for i in range(self.combo_val.count()):
                        if self.combo_val.itemData(i) == clean_val:
                            found_idx = i
                            break
                    self.combo_val.blockSignals(True)
                    if found_idx != -1:
                        self.combo_val.setCurrentIndex(found_idx)
                    else:
                        insert_pos = max(0, self.combo_val.count() - 2)
                        self.combo_val.insertItem(insert_pos, clean_val, userData=clean_val)
                        self.combo_val.setCurrentIndex(insert_pos)
                    self._prev_val_idx = self.combo_val.currentIndex()
                    self.combo_val.blockSignals(False)
                    self._sync_target_to_tool()
            else:
                # 用户取消输入，平滑恢复回之前的选择
                self.combo_val.blockSignals(True)
                self.combo_val.setCurrentIndex(self._prev_val_idx)
                self.combo_val.blockSignals(False)
        elif data == "__set_null_value__":
            self.combo_val.blockSignals(True)
            self.combo_val.setEditText("NULL")
            self.combo_val.blockSignals(False)
            self._prev_val_idx = idx
            self._sync_target_to_tool()
        elif data == "":
            # 选中了「暂无候选值」占位项时清空输入框，避免占位文字被当成属性值
            self.combo_val.blockSignals(True)
            self.combo_val.setEditText("")
            self.combo_val.blockSignals(False)
            self._prev_val_idx = idx
            self._sync_target_to_tool()
        else:
            self._prev_val_idx = idx
            self._sync_target_to_tool()

    def _on_value_changed(self, text):
        self._sync_target_to_tool()

    def _switch_mode(self, multi: bool):
        target_multi = bool(multi)
        if target_multi == self._multi_mode:
            return

        if self.isFloating():
            if self._multi_mode:
                self._multi_height = max(280, self.height())
            else:
                self._single_height = max(160, self.height())

        self._multi_mode = target_multi
        self.btn_mode_single.setChecked(not self._multi_mode)
        self.btn_mode_multi.setChecked(self._multi_mode)

        sp_ignored = getattr(QSizePolicy.Policy, "Ignored", getattr(QSizePolicy, "Ignored", 13))
        sp_pref = getattr(QSizePolicy.Policy, "Preferred", getattr(QSizePolicy, "Preferred", 5))
        sp_exp = getattr(QSizePolicy.Policy, "Expanding", getattr(QSizePolicy, "Expanding", 7))

        if self._multi_mode:
            self._page_single.setSizePolicy(sp_pref, sp_ignored)
            self._page_multi.setSizePolicy(sp_pref, sp_exp)
            self.multi_table.setMinimumHeight(140)
            self.mode_stack.setCurrentIndex(1)
        else:
            self._page_multi.setSizePolicy(sp_pref, sp_ignored)
            self._page_single.setSizePolicy(sp_pref, sp_pref)
            self.multi_table.setMinimumHeight(0)
            self.mode_stack.setCurrentIndex(0)

        self.btn_clear_null.setVisible(not self._multi_mode)
        self.mode_stack.updateGeometry()
        if self.widget() and self.widget().layout():
            self.widget().layout().activate()

        if self.isFloating():
            if self._multi_mode:
                QTimer.singleShot(0, self._fit_multi_height)
            else:
                QTimer.singleShot(0, lambda h=self._single_height: self.resize(self.width(), h))

        self._sync_target_to_tool()

    def _fit_multi_height(self):
        """切换到多字段时自动展开全部字段高度，并做屏幕可用工作区防溢出钳位"""
        if not self.isFloating() or not self._multi_mode:
            return

        rows = self.multi_table.rowCount()
        header_h = self.multi_table.horizontalHeader().height() or 24
        rows_h = sum(self.multi_table.rowHeight(r) for r in range(rows))
        ideal_table_h = max(140, header_h + rows_h + 6)
        chrome_h = max(180, self.height() - self.multi_table.height())
        ideal_h = chrome_h + ideal_table_h

        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        if avail and not avail.isEmpty():
            max_h = max(240, avail.height() - 48)
            target_h = min(ideal_h, max_h)
            if self.y() + target_h > avail.bottom() - 8:
                new_y = max(avail.top() + 8, avail.bottom() - target_h - 8)
                self.move(self.x(), new_y)
        else:
            target_h = ideal_h

        self._multi_height = target_h
        self.resize(self.width(), target_h)

    def _load_multi_fields(self):
        self._multi_loading = True
        self.multi_table.setRowCount(0)
        if not self.layer or not isinstance(self.layer, QgsVectorLayer) or not self.layer.isValid():
            self._multi_loading = False
            return

        pk_indices = set(self.layer.primaryKeyAttributes()) if hasattr(self.layer, "primaryKeyAttributes") else set()
        fields = [
            f for f in AttributeEngine.get_editable_fields(self.layer)
            if f["name"].lower() not in ("fid", "ogc_fid")
            and self.layer.fields().indexOf(f["name"]) not in pk_indices
        ]
        self.multi_table.setRowCount(len(fields))
        check_role = getattr(Qt.ItemDataRole, "CheckStateRole", getattr(Qt, "CheckStateRole", 10))
        unchecked = getattr(Qt.CheckState, "Unchecked", getattr(Qt, "Unchecked", 0))
        item_checkable = getattr(Qt.ItemFlag, "ItemIsUserCheckable", getattr(Qt, "ItemIsUserCheckable", 16))
        item_enabled = getattr(Qt.ItemFlag, "ItemIsEnabled", getattr(Qt, "ItemIsEnabled", 32))

        for row, f in enumerate(fields):
            fname = f["name"]
            item = QTableWidgetItem(f.get("icon", QIcon()), fname)
            item.setFlags(item_checkable | item_enabled)
            item.setData(check_role, unchecked)
            self.multi_table.setItem(row, 0, item)

            cb = QComboBox()
            cb.setEditable(True)
            cb.setItemDelegate(ValueMapComboDelegate(cb))
            cb.addItem("NULL", userData="__NULL__")
            vmap = AttributeEngine.get_value_map(self.layer, fname)
            for u in AttributeEngine.extract_unique_values(self.layer, fname, limit=100):
                if AttributeEngine.is_empty_or_null(u):
                    continue
                lbl, hint = AttributeEngine.get_value_display_parts(vmap, u)
                cb.addItem(lbl, userData=str(u))
                if hint:
                    cb.setItemData(cb.count() - 1, hint, ROLE_RAW_HINT)
            cb.setCurrentIndex(-1)
            cb.setEditText("")
            cb.currentIndexChanged.connect(lambda _idx, r=row: self._on_multi_combo_changed(r))
            cb.lineEdit().textChanged.connect(lambda _txt, r=row: self._on_multi_combo_changed(r))
            self.multi_table.setCellWidget(row, 1, cb)

        self._multi_loading = False

    def _on_multi_combo_changed(self, row: int):
        if self._multi_loading:
            return
        item = self.multi_table.item(row, 0)
        cb = self.multi_table.cellWidget(row, 1)
        if item and cb:
            txt = cb.currentText().strip()
            checked = getattr(Qt.CheckState, "Checked", getattr(Qt, "Checked", 2))
            if txt and item.checkState() != checked:
                self._multi_loading = True
                item.setCheckState(checked)
                self._multi_loading = False
        if self._multi_mode:
            self._sync_target_to_tool()

    def _on_multi_table_item_changed(self, item):
        if not self._multi_loading and self._multi_mode:
            self._sync_target_to_tool()

    def _extract_multi_targets(self) -> dict:
        targets = {}
        checked = getattr(Qt.CheckState, "Checked", getattr(Qt, "Checked", 2))
        for row in range(self.multi_table.rowCount()):
            item = self.multi_table.item(row, 0)
            cb = self.multi_table.cellWidget(row, 1)
            if not item or not cb or item.checkState() != checked:
                continue
            fname = item.text()
            txt = cb.currentText().strip()
            cur_idx = cb.currentIndex()
            if cur_idx >= 0 and cb.itemText(cur_idx).strip() == txt:
                data = cb.itemData(cur_idx)
                val = None if data == "__NULL__" else data
            elif not txt or txt.upper() == "NULL":
                val = None
            else:
                val = txt
            targets[fname] = val
        return targets

    def _apply_multi_values_to_table(self, values_dict: dict, check_matched: bool = True):
        self._multi_loading = True
        checked = getattr(Qt.CheckState, "Checked", getattr(Qt, "Checked", 2))
        unchecked = getattr(Qt.CheckState, "Unchecked", getattr(Qt, "Unchecked", 0))
        for row in range(self.multi_table.rowCount()):
            item = self.multi_table.item(row, 0)
            cb = self.multi_table.cellWidget(row, 1)
            if not item or not cb:
                continue
            fname = item.text()
            if fname in values_dict:
                raw_val = values_dict[fname]
                if check_matched:
                    item.setCheckState(checked)
                if raw_val is None or AttributeEngine.is_empty_or_null(raw_val):
                    cb.setCurrentIndex(0)
                    cb.setEditText("NULL")
                else:
                    s = str(raw_val).strip()
                    idx = cb.findData(s)
                    if idx >= 0:
                        cb.setCurrentIndex(idx)
                    else:
                        cb.setEditText(s)
            elif check_matched:
                item.setCheckState(unchecked)
        self._multi_loading = False
        if self._multi_mode:
            self._sync_target_to_tool()

    def _load_multi_templates(self):
        self.combo_tpl.blockSignals(True)
        self.combo_tpl.clear()
        self.combo_tpl.addItem(tr("(Custom combo)"), userData=None)
        if self.layer and isinstance(self.layer, QgsVectorLayer) and self.layer.isValid():
            mp_cfg = self.config.get("multi_painter", {})
            tpls = mp_cfg.get("templates_by_layer", {}).get(self.layer.id(), [])
            for tpl in tpls:
                if isinstance(tpl, dict) and tpl.get("name"):
                    self.combo_tpl.addItem(tpl["name"], userData=tpl.get("values", {}))
            active_name = mp_cfg.get("active_template_by_layer", {}).get(self.layer.id(), "")
            if active_name:
                idx = self.combo_tpl.findText(active_name)
                if idx > 0:
                    self.combo_tpl.setCurrentIndex(idx)
                    self._apply_multi_values_to_table(self.combo_tpl.itemData(idx) or {})
        self.combo_tpl.blockSignals(False)

    def _on_template_selected(self, idx):
        if idx <= 0:
            return
        vals = self.combo_tpl.itemData(idx)
        if isinstance(vals, dict):
            self._apply_multi_values_to_table(vals, check_matched=True)
            if self.layer and self.layer.isValid():
                mp = self.config.setdefault("multi_painter", {})
                mp.setdefault("active_template_by_layer", {})[self.layer.id()] = self.combo_tpl.itemText(idx)
                ConfigManager.update_section("multi_painter", mp)

    def _on_save_template_clicked(self):
        if not self.layer or not self.layer.isValid():
            return
        targets = self._extract_multi_targets()
        if not targets:
            self.iface.messageBar().pushWarning("QuickFieldBrush", tr("Please check at least one field first!"))
            return
        default_name = self.combo_tpl.currentText() if self.combo_tpl.currentIndex() > 0 else ""
        name, ok = QInputDialog.getText(self, tr("Save Combo Template"), tr("Template name:"), text=default_name)
        if not ok or not name.strip():
            return
        name = name.strip()
        mp = self.config.setdefault("multi_painter", {})
        by_layer = mp.setdefault("templates_by_layer", {})
        tpl_list = [t for t in by_layer.get(self.layer.id(), []) if t.get("name") != name]
        tpl_list.append({"name": name, "values": targets})
        by_layer[self.layer.id()] = tpl_list
        mp.setdefault("active_template_by_layer", {})[self.layer.id()] = name
        ConfigManager.update_section("multi_painter", mp)
        self._load_multi_templates()

    def _on_delete_template_clicked(self):
        idx = self.combo_tpl.currentIndex()
        if idx <= 0 or not self.layer or not self.layer.isValid():
            return
        name = self.combo_tpl.itemText(idx)
        mp = self.config.setdefault("multi_painter", {})
        by_layer = mp.setdefault("templates_by_layer", {})
        by_layer[self.layer.id()] = [t for t in by_layer.get(self.layer.id(), []) if t.get("name") != name]
        if mp.get("active_template_by_layer", {}).get(self.layer.id()) == name:
            mp["active_template_by_layer"].pop(self.layer.id(), None)
        ConfigManager.update_section("multi_painter", mp)
        self._load_multi_templates()

    def _on_apply_multi_to_selected(self):
        if not self.layer or not self.layer.isValid():
            return
        targets = self._extract_multi_targets()
        if not targets:
            self.iface.messageBar().pushWarning("QuickFieldBrush", tr("Please check at least one field first!"))
            return
        auto_edit = ConfigManager.get_config().get("behavior", {}).get("auto_start_editing", True)
        cnt, msg = AttributeEngine.batch_update_multi_fields(self.layer, targets, auto_start_editing=auto_edit)
        if cnt > 0:
            self.iface.messageBar().pushInfo("QuickFieldBrush", msg)
        else:
            self.iface.messageBar().pushWarning("QuickFieldBrush", msg)

    def _on_multi_feature_absorbed_from_map(self, attrs_dict: dict, feat_id):
        self._reset_absorb_btn_text()
        self._apply_multi_values_to_table(attrs_dict, check_matched=False)
        self.lbl_status.setText(tr("Absorbed FID {0}: {1} fields (ready to paint)").format(feat_id, len(attrs_dict)))

    def _sync_target_to_tool(self):
        """毫秒级即时同步当前选中的字段与值给画笔地图工具（即使值为空也同步字段，确保吸管可用且不残留旧字段）"""
        if getattr(self, "_multi_mode", False):
            targets = self._extract_multi_targets()
            self.painter_tool.set_multi_targets(targets)
            if targets:
                preview = ", ".join(f"{k}={'NULL' if v is None else v}" for k, v in list(targets.items())[:3])
                if len(targets) > 3:
                    preview += " ..."
                self.lbl_status.setText(tr("Combo ({0}): {1}").format(len(targets), preview))
            else:
                self.lbl_status.setText(tr("Status: check fields and set values first"))
            return
        fname = self.combo_field.currentData()
        if not fname:
            self.painter_tool.set_target(None, None, is_null=False)
            self.lbl_status.setText(tr("Status: pick a field and value first"))
            return

        if self.combo_val.currentData() == "__custom_add_value__" and self.combo_val.currentText().startswith("➕"):
            return

        val = self._extract_current_value()
        if val == "__NULL__":
            self.painter_tool.set_target(fname, None, is_null=True)
            self.lbl_status.setText(tr("Painting: [{0} = NULL] (clear field)").format(fname))
        elif val != "":
            self.painter_tool.set_target(fname, val, is_null=False)
            value_map = getattr(self, "_current_value_map", {})
            display_label, raw_hint = AttributeEngine.get_value_display_parts(value_map, val)
            status_val = f"{display_label} ({raw_hint})" if raw_hint else display_label
            self.lbl_status.setText(tr("Painting: [{0} = {1}]").format(fname, status_val))
        else:
            self.painter_tool.set_target(None, None, is_null=False)
            self.lbl_status.setText(tr("Status: pick a field and value first"))

    def _on_set_null_clicked(self):
        """点击面板底部的【设为 NULL / 清空】快捷按钮"""
        fname = self.combo_field.currentData()
        if not fname or not self.layer or not self.layer.isValid():
            return

        # 1. 将画笔和下拉框置为 NULL 模式
        self.combo_val.blockSignals(True)
        idx = self.combo_val.findData("__set_null_value__")
        if idx != -1:
            self.combo_val.setCurrentIndex(idx)
        self.combo_val.setEditText("NULL")
        self._prev_val_idx = self.combo_val.currentIndex()
        self.combo_val.blockSignals(False)
        self._sync_target_to_tool()

        # 2. 若当前地图图层中已有被选中的要素，立即批量将它们置为 NULL
        if self.layer.selectedFeatureCount() > 0:
            auto_edit = ConfigManager.get_config().get("behavior", {}).get("auto_start_editing", True)
            count, msg = AttributeEngine.batch_update_single_field(
                self.layer, fname, None, auto_start_editing=auto_edit
            )
            self.iface.messageBar().pushInfo("QuickFieldBrush", msg)
        else:
            self.lbl_status.setText(tr("Painting: [{0} = NULL] (clear field)").format(fname))

    def _toggle_pick_mode(self):
        """进入/退出吸管模式，或者直接从已选要素吸取"""
        self.layer = self.iface.activeLayer()
        if not self.layer or not isinstance(self.layer, QgsVectorLayer) or not self.layer.isValid():
            self.iface.messageBar().pushWarning(
                tr("QuickFieldBrush Format Painter"),
                tr("Please select a valid vector layer in the Layers panel first!"))
            return

        # 若当前恰好选中了单个要素，优先直接吸取该要素值
        if self.layer.selectedFeatureCount() == 1:
            feat = next(self.layer.getSelectedFeatures(), None)
            if feat:
                if self._multi_mode:
                    targets = self._extract_multi_targets()
                    fnames = list(targets.keys()) if targets else [
                        f["name"] for f in AttributeEngine.get_editable_fields(self.layer, include_icons=False)
                    ]
                    absorbed = {}
                    for fname in fnames:
                        fidx = feat.fields().indexOf(fname)
                        if fidx != -1:
                            rv = feat.attribute(fidx)
                            absorbed[fname] = "" if AttributeEngine.is_null_value(rv) else str(rv).strip()
                    self._on_multi_feature_absorbed_from_map(absorbed, feat.id())
                    return
                fname = self.combo_field.currentData()
                if fname:
                    fidx = feat.fields().indexOf(fname)
                    if fidx != -1:
                        val = feat.attribute(fidx)
                        self._on_feature_absorbed_from_map(fname, val, feat.id())
                        return

        # 否则切换地图单击吸取模式（光标变为十字吸管，在地图上点哪个要素就吸哪个要素）
        if getattr(self.painter_tool, "is_picking_mode", False):
            self.painter_tool.set_picking_mode(False)
            self._reset_absorb_btn_text()
            self._sync_target_to_tool()
        else:
            self.painter_tool.set_picking_mode(True)
            self.btn_pick_from_selected.setText(tr("🔍 Click any feature on map to absorb value..."))
            if self._multi_mode:
                self.lbl_status.setText(tr("Absorb mode: click any feature on map to pick combo fields"))
            else:
                fname = self.combo_field.currentData() or ""
                self.lbl_status.setText(tr("Absorb mode: click any feature on map to pick [{0}]").format(fname))

    def _reset_absorb_btn_text(self):
        self.btn_pick_from_selected.setText(tr("Absorb attribute from feature"))

    def _on_feature_absorbed_from_map(self, field_name, val, feat_id):
        """地图要素被吸取时的回调：更新属性值下拉框，并恢复格式刷状态"""
        self._reset_absorb_btn_text()

        self.combo_val.blockSignals(True)
        if AttributeEngine.is_empty_or_null(val):
            null_idx = self.combo_val.findData("__set_null_value__")
            if null_idx != -1:
                self.combo_val.setCurrentIndex(null_idx)
            self.combo_val.setEditText("NULL")
            self._prev_val_idx = self.combo_val.currentIndex()
            self.combo_val.blockSignals(False)
            self._sync_target_to_tool()
            self.lbl_status.setText(tr("Absorbed FID {0}: [{1} = NULL] (ready to paint)").format(feat_id, field_name))
        else:
            val_str = str(val).strip()
            # 在下拉框中选中或添加该吸取值
            found_idx = -1
            for i in range(self.combo_val.count()):
                if self.combo_val.itemData(i) == val_str or self.combo_val.itemText(i) == val_str:
                    found_idx = i
                    break
            value_map = getattr(self, "_current_value_map", {})
            display_label, raw_hint = AttributeEngine.get_value_display_parts(value_map, val_str)
            if found_idx != -1:
                self.combo_val.setCurrentIndex(found_idx)
            else:
                insert_pos = max(0, self.combo_val.count() - 2)
                self.combo_val.insertItem(insert_pos, display_label, userData=val_str)
                if raw_hint:
                    self.combo_val.setItemData(insert_pos, raw_hint, ROLE_RAW_HINT)
                self.combo_val.setCurrentIndex(insert_pos)
            self._prev_val_idx = self.combo_val.currentIndex()
            self.combo_val.blockSignals(False)
            self._sync_target_to_tool()
            status_val = f"{display_label} ({raw_hint})" if raw_hint else display_label
            self.lbl_status.setText(tr("Absorbed FID {0}: [{1} = {2}] (ready to paint)").format(feat_id, field_name, status_val))

    def closeEvent(self, event):
        """窗口关闭时：持久化本次配置并退出格式刷模式"""
        if hasattr(self.painter_tool, "set_picking_mode"):
            self.painter_tool.set_picking_mode(False)
        self._reset_absorb_btn_text()

        fname = self.combo_field.currentData()
        val = self._extract_current_value()
        if fname and val:
            ConfigManager.update_section("format_painter", {"field_name": fname, "value": val})

        if self.iface.mapCanvas().mapTool() == self.painter_tool:
            self.iface.mapCanvas().unsetMapTool(self.painter_tool)
        super().closeEvent(event)


# 向后兼容别名
FormatPainterDialog = FormatPainterDockWidget

