# -*- coding: utf-8 -*-
"""
QuickFieldBrush 跨版本兼容层 (QGIS 3 / Qt5 与 QGIS 4 / Qt6 统一桥接)
"""

from qgis.PyQt.QtWidgets import QMenu, QDialog

# Qt6 移除了 Python 2 时代的 exec_() 方法，只保留标准的 exec()
# 在此打补丁以保证在 QGIS 3 和 QGIS 4 中无论调用 exec() 还是 exec_() 都能正常运行
if not hasattr(QMenu, "exec_") and hasattr(QMenu, "exec"):
    QMenu.exec_ = QMenu.exec

if not hasattr(QDialog, "exec_") and hasattr(QDialog, "exec"):
    QDialog.exec_ = QDialog.exec


def safe_exec(obj, *args):
    """安全执行 QMenu / QDialog 的事件循环，兼容 Qt5 (exec_) 与 Qt6 (exec)"""
    method = getattr(obj, "exec", None) or getattr(obj, "exec_", None)
    if method:
        return method(*args)
    return None
