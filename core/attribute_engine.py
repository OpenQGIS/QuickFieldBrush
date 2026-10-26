# -*- coding: utf-8 -*-
"""
属性赋值与图层探查引擎：
1. 安全批量修改属性（基于 beginEditCommand 与 Undo/Redo 栈）
2. 自动从图层中提取字段列表与唯一值枚举（uniqueValues）
3. 严格遵循 Python / Qt 数据类型转换，杜绝 Provider 类型错误
"""

from qgis.core import (
    QgsVectorLayer,
    QgsField,
    QgsMessageLog,
    Qgis,
    QgsFeatureRequest
)
from PyQt5.QtCore import QVariant
from ..i18n_helper import tr


class AttributeEngine:
    # 唯一值会话级缓存: (layer_id, field_name) -> 候选值列表
    _unique_cache = {}
    # 频次会话级缓存: (layer_id, field_name) -> [(val, count), ...]
    _freq_cache = {}
    _CACHE_LIMIT = 100

    @staticmethod
    def invalidate_cache(layer=None):
        """清空唯一值与频次缓存：传入图层只清该图层，不传清全部"""
        if layer is None:
            AttributeEngine._unique_cache.clear()
            AttributeEngine._freq_cache.clear()
            return
        layer_id = layer.id()
        for key in [k for k in AttributeEngine._unique_cache if k[0] == layer_id]:
            AttributeEngine._unique_cache.pop(key, None)
        for key in [k for k in AttributeEngine._freq_cache if k[0] == layer_id]:
            AttributeEngine._freq_cache.pop(key, None)

    @staticmethod
    def get_editable_fields(layer):
        """获取图层中所有可编辑的普通字段名称列表（严格限制矢量图层）"""
        if not layer or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            return []
        
        fields = []
        for field in layer.fields():
            fields.append({
                "name": field.name(),
                "typeName": field.typeName(),
                "type": field.type(),
                "comment": field.comment()
            })
        return fields

    @staticmethod
    def extract_unique_values(layer, field_name: str, limit: int = 100):
        """
        从图层中吸取某个字段已存在的不重复唯一值（严格限制矢量图层）
        """
        if not layer or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            return []
            
        field_idx = layer.fields().indexOf(field_name)
        if field_idx == -1:
            return []

        try:
            # 会话缓存命中直接返回（按调用方的 limit 截断）
            key = (layer.id(), field_name)
            cached = AttributeEngine._unique_cache.get(key)
            if cached is not None:
                return list(cached[:limit])

            # 优先从属性表单配置中读取值映射 (Value Map)
            editor_widget_setup = layer.editorWidgetSetup(field_idx)
            if editor_widget_setup.type() == "ValueMap":
                config_map = editor_widget_setup.config()
                if "map" in config_map and isinstance(config_map["map"], list):
                    values = []
                    for item in config_map["map"]:
                        if isinstance(item, dict):
                            values.extend(list(item.values()))
                    if values:
                        result_vm = [str(v) for v in values if v is not None]
                        AttributeEngine._unique_cache[key] = result_vm
                        return result_vm

            # 否则从图层要素数据中获取 uniqueValues（统一按缓存上限提取，调用方再截断）
            unique_vals = layer.uniqueValues(field_idx, AttributeEngine._CACHE_LIMIT)
            result = []
            for val in unique_vals:
                if val is not None and str(val).strip() != "" and str(val) != "NULL":
                    result.append(str(val))

            # 尝试自然排序
            try:
                result = sorted(result, key=lambda x: float(x) if x.replace('.', '', 1).isdigit() else x)
            except Exception:
                result = sorted(result)

            AttributeEngine._unique_cache[key] = result
            return result
        except Exception as e:
            QgsMessageLog.logMessage(f"提取唯一值失败: {str(e)}", "QuickFieldBrush", Qgis.Warning)
            return []

    @staticmethod
    def extract_unique_values_with_counts(layer, field_name: str):
        """
        提取字段的不重复唯一值及其在图层中的出现频次: [(val, count), ...]
        走 NoGeometry + setSubsetOfAttributes 极速属性流，全表万级要素 < 0.15s，并享受会话级缓存。
        """
        if not layer or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            return []

        field_idx = layer.fields().indexOf(field_name)
        if field_idx == -1:
            return []

        key = (layer.id(), field_name)
        cached = AttributeEngine._freq_cache.get(key)
        if cached is not None:
            return list(cached)

        try:
            from collections import Counter
            counter = Counter()
            req = QgsFeatureRequest().setSubsetOfAttributes([field_idx]).setFlags(QgsFeatureRequest.NoGeometry)
            for feat in layer.getFeatures(req):
                val = feat[field_idx]
                if val is not None and str(val).strip() != "" and str(val) != "NULL":
                    counter[str(val)] += 1

            result = counter.most_common()
            AttributeEngine._freq_cache[key] = result
            return list(result)
        except Exception as e:
            QgsMessageLog.logMessage(f"提取字段频次失败: {str(e)}", "QuickFieldBrush", Qgis.Warning)
            uniques = AttributeEngine.extract_unique_values(layer, field_name)
            return [(u, 0) for u in uniques]

    @staticmethod
    def convert_value_for_field(field_obj: QgsField, raw_val):
        """
        将原始值精确转换为该字段底层所需的强类型 Python 对象（int, float, str, bool）
        """
        if raw_val is None or str(raw_val).strip() == "" or str(raw_val).upper() == "NULL":
            return None

        # 优先通过 field_obj.convertCompatible(raw_val) 处理
        try:
            res = field_obj.convertCompatible(raw_val)
            # PyQGIS convertCompatible: 如果返回 tuple/list 则解包 (val, ok)，否则直接返回转换后的值
            if isinstance(res, (tuple, list)):
                converted_val = res[0]
                ok = res[1] if len(res) > 1 else True
                if ok:
                    return converted_val
            elif res is not None:
                return res
        except Exception:
            pass

        # 兜底：根据字段元类型手动类型转换
        f_type = field_obj.type()
        str_val = str(raw_val).strip()

        # 整数型 (Int, LongLong 等)
        if f_type in [QVariant.Int, QVariant.UInt, QVariant.LongLong, QVariant.ULongLong, 2, 3]:
            try:
                return int(float(str_val))
            except (ValueError, TypeError):
                return raw_val

        # 浮点型 (Double 等)
        elif f_type in [QVariant.Double, 6]:
            try:
                return float(str_val)
            except (ValueError, TypeError):
                return raw_val

        # 布尔型
        elif f_type in [QVariant.Bool, 1]:
            lower_v = str_val.lower()
            if lower_v in ['true', '1', 't', 'y', 'yes', '是']:
                return True
            elif lower_v in ['false', '0', 'f', 'n', 'no', '否']:
                return False
            return bool(raw_val)

        # 字符串类型
        elif f_type in [QVariant.String, 10]:
            return str_val

        return raw_val

    @staticmethod
    def batch_update_single_field(layer: QgsVectorLayer, field_name: str, value, auto_start_editing: bool = True):
        """
        功能 1：批量更新选中要素的单一字段（右键极速分级）
        """
        if not layer or not layer.isValid():
            return 0, tr("Invalid layer")

        selected_fids = layer.selectedFeatureIds()
        if not selected_fids:
            return 0, tr("No features are currently selected")

        field_idx = layer.fields().indexOf(field_name)
        if field_idx == -1:
            return 0, tr("Field not found in layer: {0}").format(field_name)

        # 检查/开启编辑
        if not layer.isEditable():
            if auto_start_editing:
                if not layer.startEditing():
                    return 0, tr("Failed to start layer editing")
            else:
                return 0, tr("Layer is not in edit mode")

        # 开启 QGIS 命令栈，保证 Ctrl+Z 能够一键整体撤销
        layer.beginEditCommand(tr("QuickFieldBrush: set {0}={1}").format(field_name, value))
        try:
            field_obj = layer.fields().at(field_idx)
            val_to_write = AttributeEngine.convert_value_for_field(field_obj, value)

            for fid in selected_fids:
                layer.changeAttributeValue(fid, field_idx, val_to_write)

            layer.endEditCommand()
            layer.triggerRepaint()
            AttributeEngine.invalidate_cache(layer)
            return len(selected_fids), tr("Successfully set {1}={2} on {0} features").format(
                len(selected_fids), field_name, value)
        except Exception as e:
            layer.destroyEditCommand()
            return 0, tr("Attribute update failed: {0}").format(str(e))

    @staticmethod
    def batch_update_multi_fields(layer: QgsVectorLayer, field_values_dict: dict, auto_start_editing: bool = True):
        """
        功能 2：批量更新选中要素的多个字段
        field_values_dict 格式为: {"class": "motorway", "layer": 1, ...}
        """
        if not layer or not layer.isValid():
            return 0, tr("Invalid layer")

        selected_fids = layer.selectedFeatureIds()
        if not selected_fids:
            return 0, tr("No features are currently selected")

        if not field_values_dict:
            return 0, tr("No field values provided")

        # 检查/开启编辑
        if not layer.isEditable():
            if auto_start_editing:
                if not layer.startEditing():
                    return 0, tr("Failed to start layer editing")
            else:
                return 0, tr("Layer is not in edit mode")

        layer.beginEditCommand(tr("QuickFieldBrush: batch multi-field update"))
        try:
            fields = layer.fields()
            mapped_changes = {}

            # 预处理字段索引和类型转换
            for fname, val in field_values_dict.items():
                idx = fields.indexOf(fname)
                if idx == -1:
                    continue
                
                fld = fields.at(idx)
                val_to_write = AttributeEngine.convert_value_for_field(fld, val)
                mapped_changes[idx] = val_to_write

            if not mapped_changes:
                layer.destroyEditCommand()
                return 0, tr("No matching editable fields")

            for fid in selected_fids:
                for fidx, fval in mapped_changes.items():
                    layer.changeAttributeValue(fid, fidx, fval)

            layer.endEditCommand()
            layer.triggerRepaint()
            AttributeEngine.invalidate_cache(layer)
            return len(selected_fids), tr("Successfully updated {1} fields on {0} features").format(
                len(selected_fids), len(mapped_changes))
        except Exception as e:
            layer.destroyEditCommand()
            return 0, tr("Multi-field update failed: {0}").format(str(e))
