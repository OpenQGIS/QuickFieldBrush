# -*- coding: utf-8 -*-
"""
QuickFieldBrush 历史操作管理器 (HistoryManager):
- 记录格式刷单点写入与框选批量赋值的所有字段修改
- 支持单步回滚/撤销 (精准恢复要素到 old_value)
- 提供 CSV 历史台账导出
- 与 QGIS 画布地图高亮定位联动
"""

import csv
from datetime import datetime
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import QgsProject, QgsVectorLayer
from ..i18n_helper import tr
from .attribute_engine import AttributeEngine


class HistoryStep:
    def __init__(self, step_id: int, tool_type: str, layer_id: str, layer_name: str,
                 field_name: str, target_value, changes: list):
        self.id = step_id
        self.timestamp = datetime.now().strftime("%H:%M:%S")
        self.tool_type = tool_type  # 'painter' or 'batch_rank'
        self.layer_id = layer_id
        self.layer_name = layer_name
        self.field_name = field_name
        self.target_value = target_value
        # changes 列表格式: [{"fid": fid, "old_val": old_val, "new_val": new_val}, ...]
        self.changes = changes
        self.is_reverted = False

    @property
    def feature_count(self) -> int:
        return len(self.changes)

    @property
    def fids(self) -> list:
        return [c["fid"] for c in self.changes]


class HistoryManager(QObject):
    step_added = pyqtSignal(object)
    history_changed = pyqtSignal()

    _instance = None
    MAX_RECORDS = 500

    def __init__(self):
        super().__init__()
        self._records = []
        self._next_id = 1

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = HistoryManager()
        return cls._instance

    def add_step(self, tool_type: str, layer: QgsVectorLayer, field_name: str,
                 target_value, changes: list) -> HistoryStep:
        """
        新增一条操作记录
        changes: list of dicts: [{'fid': fid, 'old_val': old_val, 'new_val': new_val}, ...]
                 或 tuples: [(fid, old_val, new_val), ...]
        """
        if not changes:
            return None

        # 规范化 changes
        norm_changes = []
        for c in changes:
            if isinstance(c, dict):
                norm_changes.append(c)
            elif isinstance(c, (list, tuple)) and len(c) >= 3:
                norm_changes.append({
                    "fid": c[0],
                    "old_val": c[1],
                    "new_val": c[2]
                })

        layer_id = layer.id() if layer else ""
        layer_name = layer.name() if layer else tr("Unknown Layer")

        step = HistoryStep(
            step_id=self._next_id,
            tool_type=tool_type,
            layer_id=layer_id,
            layer_name=layer_name,
            field_name=field_name,
            target_value=target_value,
            changes=norm_changes
        )
        self._next_id += 1

        self._records.append(step)
        if len(self._records) > self.MAX_RECORDS:
            self._records.pop(0)

        self.step_added.emit(step)
        self.history_changed.emit()
        return step

    def get_steps(self) -> list:
        """按时间顺序返回所有历史记录（最新在后）"""
        return list(self._records)

    def get_step_by_id(self, step_id: int):
        for s in self._records:
            if s.id == step_id:
                return s
        return None

    def revert_step(self, step_id: int, iface) -> tuple:
        """
        精准回滚单条记录：将记录中受影响的要素还原到 old_val
        """
        step = self.get_step_by_id(step_id)
        if not step:
            return False, tr("History record #{0} does not exist!").format(step_id)

        if step.is_reverted:
            return False, tr("Step #{0} has already been reverted!").format(step_id)

        # 查找图层
        layer = QgsProject.instance().mapLayer(step.layer_id)
        if not layer or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            candidates = QgsProject.instance().mapLayersByName(step.layer_name)
            if candidates and isinstance(candidates[0], QgsVectorLayer) and candidates[0].isValid():
                layer = candidates[0]
            else:
                return False, tr("Layer [{0}] not found in current project!").format(step.layer_name)

        field_idx = layer.fields().indexOf(step.field_name)
        if field_idx == -1:
            return False, tr("Field [{0}] not found in layer [{1}]!").format(step.field_name, layer.name())

        if not layer.isEditable():
            if not layer.startEditing():
                return False, tr("Failed to start editing layer [{0}]!").format(layer.name())

        layer.beginEditCommand(
            tr("QuickFieldBrush: revert history #{0} ({1})").format(step.id, step.field_name)
        )
        reverted_count = 0
        try:
            field_obj = layer.fields().at(field_idx)
            for item in step.changes:
                fid = item["fid"]
                old_val = item["old_val"]
                feat = layer.getFeature(fid)
                if not feat.isValid():
                    continue
                conv_val = AttributeEngine.convert_value_for_field(field_obj, old_val)
                layer.changeAttributeValue(fid, field_idx, conv_val)
                reverted_count += 1

            layer.endEditCommand()
            layer.triggerRepaint()
            AttributeEngine.invalidate_cache(layer)

            step.is_reverted = True
            self.history_changed.emit()
            return True, tr("Successfully reverted {0} features to their previous values!").format(reverted_count)
        except Exception as e:
            layer.destroyEditCommand()
            return False, tr("Revert failed: {0}").format(str(e))

    def clear(self):
        """清空所有历史记录"""
        self._records.clear()
        self.history_changed.emit()

    def export_csv(self, filepath: str) -> tuple:
        """导出所有操作记录明细到 CSV 文件 (带 UTF-8 BOM 兼容 Excel)"""
        try:
            with open(filepath, "w", newline="", encoding="utf-8-sig") as fp:
                writer = csv.writer(fp)
                writer.writerow([
                    tr("Step ID"),
                    tr("Timestamp"),
                    tr("Action Type"),
                    tr("Layer"),
                    tr("Field"),
                    tr("Target Value"),
                    tr("Feature ID (FID)"),
                    tr("Old Value"),
                    tr("New Value"),
                    tr("Reverted")
                ])
                for s in self._records:
                    action_label = tr("Format Painter") if s.tool_type == "painter" else tr("Batch Assignment")
                    status_label = tr("Yes") if s.is_reverted else tr("No")
                    for c in s.changes:
                        writer.writerow([
                            s.id,
                            s.timestamp,
                            action_label,
                            s.layer_name,
                            s.field_name,
                            s.target_value,
                            c["fid"],
                            c["old_val"],
                            c["new_val"],
                            status_label
                        ])
            return True, tr("History successfully exported to: {0}").format(filepath)
        except Exception as e:
            return False, tr("Export failed: {0}").format(str(e))
