# -*- coding: utf-8 -*-
"""
QuickFieldBrush 跨版本兼容层 (QGIS 3 / Qt5 与 QGIS 4 / Qt6 统一桥接)
"""

from qgis.PyQt.QtWidgets import QMenu, QDialog

try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction

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


def set_window_stay_on_top(widget, on_top: bool):
    """
    动态切换窗口置顶状态：
    - Windows 系统下优先使用 Win32 SetWindowPos 原地无感切换，不销毁/重建 HWND，实现 0 闪烁、0 重绘、丝滑切换！
    - 其它平台安全回退到 Qt 的 setWindowFlag + show
    """
    import sys
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = int(widget.winId())
            if hwnd:
                user32 = ctypes.windll.user32
                user32.SetWindowPos.argtypes = [
                    ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                    ctypes.c_uint
                ]
                user32.SetWindowPos.restype = ctypes.c_bool
                HWND_TOPMOST = ctypes.c_void_p(-1)
                HWND_NOTOPMOST = ctypes.c_void_p(-2)
                # SWP_NOMOVE (0x0002) | SWP_NOSIZE (0x0001) | SWP_NOACTIVATE (0x0010)
                flags = 0x0002 | 0x0001 | 0x0010
                target = HWND_TOPMOST if on_top else HWND_NOTOPMOST
                if user32.SetWindowPos(hwnd, target, 0, 0, 0, 0, flags):
                    return True
        except (AttributeError, OSError, ValueError, RuntimeError):
            pass

    from qgis.PyQt.QtCore import Qt
    widget.setWindowFlag(Qt.WindowStaysOnTopHint, on_top)
    widget.show()
    return True
