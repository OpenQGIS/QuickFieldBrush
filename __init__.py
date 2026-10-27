# -*- coding: utf-8 -*-
"""
QuickFieldBrush - QGIS 矢量属性快速赋值与格式刷工具
"""

from .core import compat  # noqa: F401 - 优先初始化 Qt5/Qt6 跨版本桥接层


def classFactory(iface):
    """QGIS 插件工厂函数"""
    from .plugin import QuickFieldBrushPlugin
    return QuickFieldBrushPlugin(iface)
