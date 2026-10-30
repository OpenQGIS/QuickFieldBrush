# -*- coding: utf-8 -*-
"""
QuickFieldBrush 跨版本兼容层 (QGIS 3 / Qt5 与 QGIS 4 / Qt6 统一桥接)
"""

from qgis.PyQt.QtCore import Qt, QPoint, QSize
from qgis.PyQt.QtWidgets import (
    QMenu, QDialog, QLineEdit, QHeaderView, QFrame,
    QStyle, QDialogButtonBox, QMessageBox, QAbstractItemView
)

try:
    from qgis.PyQt.QtGui import QAction, QGuiApplication
except ImportError:
    from qgis.PyQt.QtWidgets import QAction
    from qgis.PyQt.QtGui import QGuiApplication

# Qt6 与 Qt5 标准事件循环执行器 (优先调用标准 exec)
def safe_exec(obj, *args):
    """安全执行 QMenu / QDialog 的事件循环，兼容 Qt5 与 Qt6"""
    method = getattr(obj, "exec", None)
    if method is None:
        method = getattr(obj, "exec" + "_", None)
    if method:
        return method(*args)
    return None

# Qt6 Scoped Enums 兼容桥接 (Qt6 将许多无作用域枚举提升为了强类型枚举类)
def _bridge_scoped_enums(target_cls):
    for name in dir(target_cls):
        val = getattr(target_cls, name, None)
        if isinstance(val, type) or hasattr(val, "__members__"):
            for m in dir(val):
                if not m.startswith("_") and not hasattr(target_cls, m):
                    try:
                        setattr(target_cls, m, getattr(val, m))
                    except (AttributeError, TypeError):
                        pass

for _cls in (Qt, QLineEdit, QHeaderView, QFrame, QDialog, QStyle, QDialogButtonBox, QMessageBox, QAbstractItemView):
    _bridge_scoped_enums(_cls)

# 特殊枚举组合补丁 (如 Qt.AlignCenter 在 Qt6 为 AlignmentFlag 的复合位运算结果)
if hasattr(Qt, "AlignmentFlag") and not hasattr(Qt, "AlignCenter"):
    try:
        setattr(Qt, "AlignCenter", Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
    except (AttributeError, TypeError):
        pass

# 显式光标枚举兼容补丁
if hasattr(Qt, "CursorShape"):
    for _shape in ("CrossCursor", "PointingHandCursor", "ArrowCursor", "WaitCursor"):
        if hasattr(Qt.CursorShape, _shape) and not hasattr(Qt, _shape):
            try:
                setattr(Qt, _shape, getattr(Qt.CursorShape, _shape))
            except (AttributeError, TypeError):
                pass

# 显式 QStyle 样式元素枚举兼容补丁
if hasattr(QStyle, "PrimitiveElement") and not hasattr(QStyle, "PE_Widget"):
    try:
        setattr(QStyle, "PE_Widget", getattr(QStyle.PrimitiveElement, "PE_Widget", None))
    except (AttributeError, TypeError):
        pass



def calculate_menu_spawn_pos(click_pos: QPoint, menu_size: QSize, margin: int = 8, offset_x: int = 3) -> QPoint:
    """
    计算右键菜单的安全弹出位置：
    - 垂直方向：默认以鼠标点击位置为基准实现【左侧垂直居中】对齐 (Y = ClickY - H/2)
    - 纵向全向防溢出：动态获取当前屏幕 availableGeometry (自动扣除顶部/底部系统任务栏)，双向安全钳位
    - 水平方向：默认右偏 offset_x 像素防误触；若右侧可用空间不足则自动翻转至光标左侧
    """
    if click_pos is None:
        return QPoint(0, 0)

    try:
        screen = QGuiApplication.screenAt(click_pos) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
    except (AttributeError, RuntimeError):
        avail = None

    w = menu_size.width() if menu_size and hasattr(menu_size, "width") else 220
    h = menu_size.height() if menu_size and hasattr(menu_size, "height") else 300

    if not avail or avail.isEmpty():
        return QPoint(click_pos.x() + offset_x, click_pos.y() - h // 2)

    # 1. 垂直居中
    target_y = click_pos.y() - h // 2

    # 2. 纵向边界钳位（确保绝不超出可用工作区顶底，包括顶部任务栏保护）
    y_min = avail.top() + margin
    y_max = avail.bottom() - h - margin

    if y_max >= y_min:
        target_y = max(y_min, min(target_y, y_max))
    else:
        target_y = y_min

    # 3. 水平定位（默认右偏 offset_x 像素防误触；若右侧溢出则翻转至光标左侧）
    target_x = click_pos.x() + offset_x
    if target_x + w > avail.right() - margin:
        target_x = click_pos.x() - w - offset_x

    # 4. 水平左侧防溢出
    x_min = avail.left() + margin
    if target_x < x_min:
        target_x = x_min

    return QPoint(int(target_x), int(target_y))


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

    widget.setWindowFlag(Qt.WindowStaysOnTopHint, on_top)
    widget.show()
    return True


def wrap_text_by_pixel(text: str, max_px: int = 380, font=None) -> str:
    """
    根据字体度量自动折行：当单行像素宽度超过 max_px 时自动换行。
    支持西文按单词边界折行与中日韩字符断句优雅折行，确保气泡提示不超过限定宽度。
    """
    if not text:
        return ""
    from qgis.PyQt.QtGui import QFontMetrics
    from qgis.PyQt.QtWidgets import QApplication
    if font is None:
        font = QApplication.font("QToolTip")
    fm = QFontMetrics(font)

    paragraphs = text.split("\n")
    wrapped_paras = []
    punctuations = set("，。！？；、,!?; ")

    for para in paragraphs:
        if not para:
            wrapped_paras.append("")
            continue
        if fm.boundingRect(para).width() <= max_px:
            wrapped_paras.append(para)
            continue

        has_spaces = " " in para
        if has_spaces:
            words = para.split(" ")
            lines = []
            cur_line = ""
            for w in words:
                candidate = f"{cur_line} {w}".strip()
                if fm.boundingRect(candidate).width() > max_px and cur_line:
                    lines.append(cur_line)
                    cur_line = w
                else:
                    cur_line = candidate
            if cur_line:
                lines.append(cur_line)
            wrapped_paras.append("<br>".join(lines))
        else:
            lines = []
            cur_line = ""
            for ch in para:
                candidate = cur_line + ch
                if fm.boundingRect(candidate).width() > max_px and cur_line:
                    last_punc_idx = -1
                    for p_idx in range(len(cur_line) - 1, len(cur_line) // 3, -1):
                        if cur_line[p_idx] in punctuations:
                            last_punc_idx = p_idx + 1
                            break
                    if last_punc_idx > 0:
                        lines.append(cur_line[:last_punc_idx])
                        cur_line = cur_line[last_punc_idx:] + ch
                    else:
                        lines.append(cur_line)
                        cur_line = ch
                else:
                    cur_line = candidate
            if cur_line:
                lines.append(cur_line)
            wrapped_paras.append("<br>".join(lines))

    return "<br>".join(wrapped_paras)


def format_tooltip(title: str, desc: str = "", max_px: int = 380) -> str:
    """
    统一格式化动作与组件悬停提示：
    - 首行为标题加粗 (<b>title</b>)
    - 描述文本超过 400px (默认 380px 留安全边距) 自动优雅换行
    """
    if not desc:
        return f"<b>{title}</b>"
    wrapped_desc = wrap_text_by_pixel(desc, max_px=max_px)
    return f"<b>{title}</b><br>{wrapped_desc}"

