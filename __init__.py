# -*- coding: utf-8 -*-
"""
QuickFieldBrush - QGIS 极速属性赋级与格式刷工具
"""

def classFactory(iface):
    """QGIS 插件工厂函数"""
    from .plugin import QuickFieldBrushPlugin
    return QuickFieldBrushPlugin(iface)
