# -*- coding: utf-8 -*-
"""
属性赋值与图层探查引擎：
1. 安全批量修改属性（基于 beginEditCommand 与 Undo/Redo 栈）
2. 自动从图层中提取字段列表与唯一值枚举（uniqueValues）
3. 严格遵循 Python / Qt 数据类型转换，杜绝 Provider 类型错误
"""

import re
from qgis.core import (
    QgsVectorLayer,
    QgsField,
    QgsFields,
    QgsMessageLog,
    Qgis,
    QgsFeatureRequest,
    NULL
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QIcon
from ..i18n_helper import tr


class AttributeEngine:
    # 唯一值会话级缓存: (layer_id, field_name) -> 候选值列表
    _unique_cache = {}
    # 频次会话级缓存: (layer_id, field_name) -> [(val, count), ...]
    _freq_cache = {}
    _CACHE_LIMIT = 150

    @staticmethod
    def is_null_value(val) -> bool:
        """统一判断 PyQGIS / Qt 属性值是否为 NULL 或空对象"""
        if val is None or val == NULL:
            return True
        if hasattr(val, "isNull") and callable(val.isNull):
            try:
                if val.isNull():
                    return True
            except (AttributeError, RuntimeError, TypeError):
                pass
        return False

    @staticmethod
    def is_empty_or_null(val) -> bool:
        """统一判断是否为真 NULL、None、纯空格或假空值（'NULL', 'null' 等）"""
        if AttributeEngine.is_null_value(val):
            return True
        s = str(val).strip()
        if s == "" or s.upper() == "NULL":
            return True
        return False

    @staticmethod
    def natural_sort_key(val):
        """自然排序键：支持 '1级, 2级, 10级' 或纯数字与文本混合稳定排序，绝不抛 TypeError"""
        s = "" if val is None else str(val).strip().lower()
        parts = re.split(r'(\d+(?:\.\d+)?)', s)
        key_parts = []
        for part in parts:
            if not part:
                continue
            try:
                key_parts.append((0, float(part), ""))
            except ValueError:
                key_parts.append((1, 0.0, part))
        return key_parts

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
    def get_field_icon(layer, field_name_or_idx):
        """
        获取字段的原生类型图标（123, abc, 1.2 等）。
        优先调用 QgsFields.iconForField，若失败则智能从 IconField 目录匹配。
        """
        if not layer or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            return QIcon()
        
        fields = layer.fields()
        fidx = field_name_or_idx if isinstance(field_name_or_idx, int) else fields.indexOf(str(field_name_or_idx))
        if fidx == -1:
            return QIcon()

        # 1. 优先使用 QGIS 原生 iconForField
        if hasattr(fields, "iconForField"):
            try:
                ic = fields.iconForField(fidx)
                if ic and not ic.isNull():
                    return ic
            except (AttributeError, RuntimeError, TypeError):
                pass

        # 2. 从插件 IconField 目录根据类型名兜底
        import os
        icon_field_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "IconField")
        field = fields.at(fidx)
        t_name = field.typeName().lower()

        _type_map = {
            "integer": "mIconFieldInteger.svg",
            "integer64": "mIconFieldInteger.svg",
            "int": "mIconFieldInteger.svg",
            "long": "mIconFieldInteger.svg",
            "string": "mIconFieldText.svg",
            "text": "mIconFieldText.svg",
            "varchar": "mIconFieldText.svg",
            "double": "mIconFieldFloat.svg",
            "float": "mIconFieldFloat.svg",
            "real": "mIconFieldFloat.svg",
            "decimal": "mIconFieldFloat.svg",
            "date": "mIconFieldDate.svg",
            "datetime": "mIconFieldDateTime.svg",
            "time": "mIconFieldTime.svg",
            "bool": "mIconFieldBool.svg",
            "boolean": "mIconFieldBool.svg",
            "binary": "mIconFieldBinary.svg",
            "json": "mIconFieldJson.svg",
            "array": "mIconFieldArray.svg",
        }
        svg_name = _type_map.get(t_name)
        if not svg_name:
            for k, v in _type_map.items():
                if k in t_name:
                    svg_name = v
                    break
        if svg_name:
            path = os.path.join(icon_field_dir, svg_name)
            if os.path.exists(path):
                return QIcon(path)

        return QIcon()

    @staticmethod
    def get_editable_fields(layer):
        """获取图层中所有可编辑的普通字段名称列表（过滤连接字段、虚拟表达式字段与只读字段）"""
        if not layer or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            return []

        qgs_fields = layer.fields()
        origin_join = getattr(QgsFields, "OriginJoin", getattr(getattr(QgsFields, "FieldOrigin", None), "OriginJoin", 2))
        origin_expr = getattr(QgsFields, "OriginExpression", getattr(getattr(QgsFields, "FieldOrigin", None), "OriginExpression", 3))

        fields = []
        for i, field in enumerate(qgs_fields):
            try:
                origin = qgs_fields.fieldOrigin(i)
                if origin in (origin_join, origin_expr):
                    continue
            except (AttributeError, RuntimeError, TypeError):
                pass
            if hasattr(field, "isReadOnly") and callable(field.isReadOnly) and field.isReadOnly():
                continue

            fields.append({
                "name": field.name(),
                "typeName": field.typeName(),
                "type": field.type(),
                "comment": field.comment(),
                "icon": AttributeEngine.get_field_icon(layer, i)
            })
        return fields

    @staticmethod
    def _extract_valuemap_values(layer, field_idx: int) -> list:
        """从图层属性表单 ValueMap 配置中提取预设值列表"""
        try:
            editor_widget_setup = layer.editorWidgetSetup(field_idx)
            if editor_widget_setup and editor_widget_setup.type() == "ValueMap":
                config_map = editor_widget_setup.config() or {}
                raw_map = config_map.get("map")
                values = []
                if isinstance(raw_map, list):
                    for item in raw_map:
                        if isinstance(item, dict):
                            values.extend(list(item.values()))
                elif isinstance(raw_map, dict):
                    values.extend(list(raw_map.values()))
                return [
                    str(v) for v in values
                    if not AttributeEngine.is_empty_or_null(v)
                ]
        except (AttributeError, RuntimeError, TypeError, KeyError):
            pass
        return []

    @staticmethod
    def extract_unique_values(layer, field_name: str, limit: int = 150):
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
            result_vm = AttributeEngine._extract_valuemap_values(layer, field_idx)
            if result_vm:
                AttributeEngine._unique_cache[key] = result_vm
                return list(result_vm[:limit])

            # 否则从图层要素数据中获取 uniqueValues（统一按缓存上限提取，调用方再截断）
            unique_vals = layer.uniqueValues(field_idx, AttributeEngine._CACHE_LIMIT)
            result = []
            for val in unique_vals:
                if not AttributeEngine.is_empty_or_null(val):
                    result.append(str(val))

            result = sorted(result, key=AttributeEngine.natural_sort_key)
            AttributeEngine._unique_cache[key] = result
            return list(result[:limit])
        except Exception as e:
            QgsMessageLog.logMessage(f"提取唯一值失败: {str(e)}", "QuickFieldBrush", Qgis.Warning)
            return []

    @staticmethod
    def extract_unique_values_with_counts(layer, field_name: str, limit: int = 150):
        """
        提取字段的不重复唯一值及其在图层中的出现频次: [(val, count), ...]
        走 NoGeometry + setSubsetOfAttributes 极速属性流，并带有缓存与高基数截断保护（防止数万唯一值卡死 UI）。
        """
        if not layer or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            return []

        field_idx = layer.fields().indexOf(field_name)
        if field_idx == -1:
            return []

        key = (layer.id(), field_name)
        cached = AttributeEngine._freq_cache.get(key)
        if cached is not None:
            return list(cached[:limit]) if limit else list(cached)

        try:
            from collections import Counter
            counter = Counter()
            req = QgsFeatureRequest().setSubsetOfAttributes([field_idx]).setFlags(QgsFeatureRequest.NoGeometry)
            for feat in layer.getFeatures(req):
                val = feat[field_idx]
                if not AttributeEngine.is_empty_or_null(val):
                    counter[str(val)] += 1

            # 合并表单 ValueMap 预设枚举值（若在要素中尚未出现则记频次为 0）
            for vm_val in AttributeEngine._extract_valuemap_values(layer, field_idx):
                if vm_val not in counter:
                    counter[vm_val] = 0

            cap = limit if limit and limit > 0 else AttributeEngine._CACHE_LIMIT
            result = counter.most_common(cap)
            AttributeEngine._freq_cache[key] = result
            return list(result)
        except Exception as e:
            QgsMessageLog.logMessage(f"提取字段频次失败: {str(e)}", "QuickFieldBrush", Qgis.Warning)
            uniques = AttributeEngine.extract_unique_values(layer, field_name, limit=limit)
            return [(u, 0) for u in uniques]

    @staticmethod
    def convert_value_for_field(field_obj: QgsField, raw_val):
        """
        将原始值精确转换为该字段底层所需的强类型 Python 对象（int, float, str, bool）
        """
        if AttributeEngine.is_empty_or_null(raw_val):
            return None

        str_val = str(raw_val).strip()
        f_type = field_obj.type()

        # 1. 整数型 (Int, UInt, LongLong, ULongLong)
        if f_type in [QVariant.Int, QVariant.UInt, QVariant.LongLong, QVariant.ULongLong, 2, 3, 4, 5]:
            try:
                return int(float(str_val))
            except (ValueError, TypeError) as err:
                raise ValueError(tr("Cannot convert '{0}' to integer for field [{1}]").format(str_val, field_obj.name())) from err

        # 2. 浮点型 (Double)
        if f_type in [QVariant.Double, 6]:
            try:
                return float(str_val)
            except (ValueError, TypeError) as err:
                raise ValueError(tr("Cannot convert '{0}' to float for field [{1}]").format(str_val, field_obj.name())) from err

        # 3. 布尔型 (Bool)
        if f_type in [QVariant.Bool, 1]:
            if isinstance(raw_val, bool):
                return raw_val
            lower_v = str_val.lower()
            if lower_v in ['true', '1', 't', 'y', 'yes', '是']:
                return True
            if lower_v in ['false', '0', 'f', 'n', 'no', '否']:
                return False
            return bool(raw_val)

        # 4. 字符串类型 (String)
        if f_type in [QVariant.String, 10]:
            return str(raw_val)

        # 5. 其它复杂类型（Date, DateTime, Time 等）：通过 field_obj.convertCompatible 处理
        try:
            res = field_obj.convertCompatible(raw_val)
            if isinstance(res, (tuple, list)):
                if len(res) >= 2:
                    # 兼容不同 SIP 绑定下的 (val, ok) 与 (ok, val) 顺序
                    if isinstance(res[1], bool) and not isinstance(res[0], bool):
                        converted_val, ok = res[0], res[1]
                    elif isinstance(res[0], bool) and not isinstance(res[1], bool):
                        ok, converted_val = res[0], res[1]
                    else:
                        converted_val, ok = res[0], bool(res[1])
                    if ok:
                        return converted_val
            elif res is not None:
                return res
        except (TypeError, ValueError, AttributeError, RuntimeError):
            pass

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

        # 提前提取原值用于历史记录与精准回滚
        old_values = {}
        try:
            req = (QgsFeatureRequest()
                   .setFilterFids(list(selected_fids))
                   .setFlags(QgsFeatureRequest.NoGeometry)
                   .setSubsetOfAttributes([field_name], layer.fields()))
            for feat in layer.getFeatures(req):
                old_values[feat.id()] = feat.attribute(field_name)
        except Exception:
            # 降级兼容：全字段提取
            try:
                req = (QgsFeatureRequest()
                       .setFilterFids(list(selected_fids))
                       .setFlags(QgsFeatureRequest.NoGeometry))
                for feat in layer.getFeatures(req):
                    old_values[feat.id()] = feat.attribute(field_name)
            except (AttributeError, KeyError, RuntimeError):
                pass

        val_display = "NULL" if AttributeEngine.is_empty_or_null(value) else str(value)
        # 开启 QGIS 命令栈，保证 Ctrl+Z 能够一键整体撤销
        layer.beginEditCommand(tr("QuickFieldBrush: set {0}={1}").format(field_name, val_display))
        try:
            field_obj = layer.fields().at(field_idx)
            val_to_write = AttributeEngine.convert_value_for_field(field_obj, value)

            updated_fids = []
            for fid in selected_fids:
                if layer.changeAttributeValue(fid, field_idx, val_to_write):
                    updated_fids.append(fid)

            if not updated_fids:
                layer.destroyEditCommand()
                return 0, tr("Attribute update failed: field [{0}] may be read-only").format(field_name)

            layer.endEditCommand()
            layer.triggerRepaint()
            AttributeEngine.invalidate_cache(layer)

            # 写入历史记录管理器
            try:
                from .history_manager import HistoryManager
                changes = [
                    {"fid": fid, "old_val": old_values.get(fid), "new_val": val_to_write}
                    for fid in updated_fids
                ]
                HistoryManager.instance().add_step(
                    tool_type="batch_rank",
                    layer=layer,
                    field_name=field_name,
                    target_value=val_to_write,
                    changes=changes
                )
            except (AttributeError, KeyError, RuntimeError) as hist_err:
                QgsMessageLog.logMessage(f"History record error: {hist_err}", "QuickFieldBrush", Qgis.Info)

            return len(updated_fids), tr("Successfully set {1}={2} on {0} features").format(
                len(updated_fids), field_name, val_display)
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
