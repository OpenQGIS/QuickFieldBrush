# -*- coding: utf-8 -*-
"""
配置管理器：
负责将图层分级字段、枚举候选值、排序偏好等持久化保存与读取。
支持：
1. 优先保存在 QgsProject 中（随工程文件保存，便于项目共享）
2. 全局回退到 QSettings（在新建项目时作为默认模板）
"""

import json
from copy import deepcopy
from qgis.core import QgsProject, QgsSettings

PROJECT_ENTRY_KEY = "QuickFieldBrush"
GLOBAL_ENTRY_KEY = "QuickFieldBrush/GlobalConfig"

DEFAULT_CONFIG = {
    # 功能1：单字段快速分级配置
    "single_rank": {
        "field_name": "",
        "ranks": ["1级", "2级", "3级", "4级"]
    },
    # 按图层独立记忆的赋值字段: layer_id -> field_name
    "single_rank_by_layer": {},
    # 右键赋值候选值排序偏好: alpha_asc, alpha_desc, freq_desc, freq_asc, num_asc, num_desc
    "single_rank_sort_mode": "freq_desc",

    # 功能2：格式刷配置
    "format_painter": {
        "field_name": "",
        "value": ""
    },

    # 交互行为设置
    "behavior": {
        "auto_start_editing": True     # 赋值时若图层未开启编辑，是否自动开启编辑模式
    }
}


class ConfigManager:
    @staticmethod
    def get_config():
        """获取当前项目的配置，如未保存则回退到全局或默认配置"""
        proj = QgsProject.instance()
        raw_proj = proj.readEntry(PROJECT_ENTRY_KEY, "config_json", "")[0]
        if raw_proj:
            try:
                return json.loads(raw_proj)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # 回退全局设置
        settings = QgsSettings()
        raw_global = settings.value(GLOBAL_ENTRY_KEY, "")
        if raw_global:
            try:
                return json.loads(raw_global)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        return deepcopy(DEFAULT_CONFIG)

    @staticmethod
    def update_section(section, data):
        """合并更新配置的某一节并持久化"""
        cfg = ConfigManager.get_config()
        if isinstance(cfg.get(section), dict):
            cfg[section].update(data)
        else:
            cfg[section] = data
        ConfigManager.save_config(cfg)

    @staticmethod
    def save_config(config_dict, save_to_project=True, save_as_global_default=True):
        """保存配置"""
        config_str = json.dumps(config_dict, ensure_ascii=False, indent=2)
        if save_to_project:
            proj = QgsProject.instance()
            proj.writeEntry(PROJECT_ENTRY_KEY, "config_json", config_str)

        if save_as_global_default:
            settings = QgsSettings()
            settings.setValue(GLOBAL_ENTRY_KEY, config_str)
