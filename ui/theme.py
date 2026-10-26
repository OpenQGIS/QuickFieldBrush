# -*- coding: utf-8 -*-
"""
AttrSnap 统一 UI 主题（唯一事实源，改主题只改这里）

设计基线（ui-ux-pro-max 设计系统检索结果）：
- 风格: Flat Design（浅色）—— 无渐变、无阴影、1px 边框、悬停变色、可见焦点环
- 色板: B2B/生产力工具语义蓝（主操作）+ 橙色强调（格式刷 CTA）+ 语义红/绿，
  文本对比度 ≥ 4.5:1
- 密度: 高密度桌面工具 —— 间距 4/8/12/16px，按钮 min-height 26px
- 状态: hover = 深一档实色；pressed = 最深；disabled = 中性灰；focus = 主色边框

语义约定（全插件一致）：
- 蓝色 PRIMARY   = 每个界面的主操作（应用修改 / 保存设置）
- 橙色 ACCENT    = 格式刷工具专属强调（含其控制台、图钉）
- 红色 DANGER    = 破坏性操作（预留）
- 绿色 SUCCESS   = 成功反馈语义（消息条/启用态），不用于普通按钮
"""

# ---- 语义色板 ----
PRIMARY = "#2563EB"          # 主操作
PRIMARY_HOVER = "#1D4ED8"
PRIMARY_PRESSED = "#1E40AF"
PRIMARY_TINT = "#DBEAFE"     # 主色浅底（选中/焦点底）

ACCENT = "#EA580C"           # 强调操作（格式刷）
ACCENT_HOVER = "#C2410C"
ACCENT_PRESSED = "#9A3412"
ACCENT_TINT = "#FFEDD5"

SUCCESS = "#059669"
SUCCESS_HOVER = "#047857"
SUCCESS_TINT = "#D1FAE5"

DANGER = "#DC2626"
DANGER_HOVER = "#B91C1C"

FG = "#0F172A"               # 主文本
FG_MUTED = "#475569"         # 次要文本/提示
BG = "#F8FAFC"               # 页面底
CARD = "#FFFFFF"             # 卡片/输入底
BORDER = "#E2E8F0"           # 1px 边框
MUTED_FILL = "#E8ECF1"       # 中性填充（状态条/未激活底）
HOVER_FILL = "#F1F5F9"
PRESSED_FILL = "#E2E8F0"
DISABLED_BG = "#CBD5E1"
DISABLED_FG = "#64748B"
SLATE = "#64748B"            # 工具栏"设置"图标等中性强调

# ---- 间距（高密度桌面：4 / 8 / 12 / 16）----
SP_XS = 4
SP_SM = 8
SP_MD = 12
SP_LG = 16

# ---- 字号 ----
FS_BODY = "12px"
FS_HINT = "11px"

# ---- 文本标签 ----
LABEL_TITLE_SS = "font-weight: 600; color: %s; font-size: 12px;" % FG
HINT_LABEL_SS = "color: %s; font-size: %s;" % (FG_MUTED, FS_HINT)
STATUS_LABEL_SS = "font-weight: 600; color: %s;" % FG

# ---- 按钮（三态 + 禁用）----
BUTTON_PRIMARY_SS = """
QPushButton {
    min-height: 26px; padding: 4px 16px; border-radius: 5px; border: none;
    background-color: %s; color: #FFFFFF; font-weight: 600;
}
QPushButton:hover { background-color: %s; }
QPushButton:pressed { background-color: %s; }
QPushButton:disabled { background-color: %s; color: %s; }
""" % (PRIMARY, PRIMARY_HOVER, PRIMARY_PRESSED, DISABLED_BG, DISABLED_FG)

BUTTON_ACCENT_SS = """
QPushButton {
    min-height: 26px; padding: 4px 16px; border-radius: 5px; border: none;
    background-color: %s; color: #FFFFFF; font-weight: 600;
}
QPushButton:hover { background-color: %s; }
QPushButton:pressed { background-color: %s; }
QPushButton:disabled { background-color: %s; color: %s; }
""" % (ACCENT, ACCENT_HOVER, ACCENT_PRESSED, DISABLED_BG, DISABLED_FG)

BUTTON_SECONDARY_SS = """
QPushButton {
    min-height: 26px; padding: 4px 14px; border-radius: 5px;
    background-color: %s; color: %s; font-weight: 600;
    border: 1px solid %s;
}
QPushButton:hover { background-color: %s; border-color: #CBD5E1; }
QPushButton:pressed { background-color: %s; }
QPushButton:disabled { color: %s; }
""" % (CARD, FG, BORDER, HOVER_FILL, PRESSED_FILL, DISABLED_FG)

BUTTON_LINK_SS = """
QPushButton {
    color: %s; font-weight: 600; border: none; border-radius: 4px;
    padding: 4px 2px; text-align: left;
}
QPushButton:hover { color: %s; background-color: %s; }
""" % (PRIMARY, PRIMARY_HOVER, PRIMARY_TINT)

# 图钉/可切换小工具按钮（格式刷控制台：启用=强调橙、停用=中性）
TOGGLE_ON_SS = """
QToolButton {
    border: 1px solid %s; border-radius: 4px; padding: 3px 8px;
    background-color: %s; color: %s; font-weight: 600;
}
""" % (ACCENT_TINT, ACCENT_TINT, ACCENT_PRESSED)

TOGGLE_OFF_SS = """
QToolButton {
    border: 1px solid %s; border-radius: 4px; padding: 3px 8px;
    background-color: %s; color: %s; font-weight: 600;
}
""" % (BORDER, MUTED_FILL, FG_MUTED)

# ---- 输入控件 ----
LINEEDIT_SS = """
QLineEdit {
    min-height: 24px; padding: 3px 8px;
    background-color: %s; border: 1px solid %s; border-radius: 4px; color: %s;
    selection-background-color: %s; selection-color: #FFFFFF;
}
QLineEdit:focus { border: 1px solid %s; }
QLineEdit:disabled { color: %s; background-color: %s; }
""" % (CARD, BORDER, FG, PRIMARY, PRIMARY, DISABLED_FG, MUTED_FILL)

COMBO_SS = """
QComboBox {
    min-height: 24px; padding: 3px 8px;
    background-color: %s; border: 1px solid %s; border-radius: 4px; color: %s;
}
QComboBox:focus { border: 1px solid %s; }
QComboBox:disabled { color: %s; background-color: %s; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    border: 1px solid %s; background-color: %s;
    selection-background-color: %s; selection-color: %s;
}
""" % (CARD, BORDER, FG, PRIMARY, DISABLED_FG, MUTED_FILL, BORDER, CARD, PRIMARY_TINT, FG)

# ---- 容器 ----
STATUS_FRAME_SS = """
QFrame { background-color: %s; border: 1px solid %s; border-radius: 6px; }
""" % (MUTED_FILL, BORDER)

CARD_SS = """
QFrame { background-color: %s; border: 1px solid %s; border-radius: 6px; }
""" % (CARD, BORDER)

TABLE_SS = """
QTableWidget {
    border: 1px solid %s; border-radius: 5px;
    gridline-color: %s; background-color: %s; alternate-background-color: %s;
}
QHeaderView::section {
    background-color: %s; color: %s; font-weight: 600;
    padding: 4px 6px; border: none;
    border-right: 1px solid %s; border-bottom: 1px solid %s;
}
""" % (BORDER, HOVER_FILL, CARD, BG, HOVER_FILL, FG, BORDER, BORDER)

LIST_SS = """
QListWidget { border: 1px solid %s; border-radius: 5px; background-color: %s; }
QListWidget::item { padding: 5px 6px; }
QListWidget::item:selected { background-color: %s; color: %s; }
""" % (BORDER, CARD, PRIMARY_TINT, FG)

GROUPBOX_SS = """
QGroupBox {
    font-weight: 600; border: 1px solid %s; border-radius: 5px;
    margin-top: 10px; padding-top: 6px;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; color: %s; }
""" % (BORDER, FG)

MENU_SS = """
QMenu {
    background-color: %s;
    border: 1px solid %s;
    border-radius: 6px;
    padding: 3px;
}
QMenu::item {
    padding: 3px 14px 3px 6px;
    border-radius: 3px;
    font-size: 12px;
    color: %s;
}
QMenu::item:selected {
    background-color: %s;
    color: %s;
}
QMenu::item:disabled {
    color: #64748B;
    background-color: transparent;
    font-weight: 600;
}
QMenu::icon {
    padding-left: 4px;
    margin-right: 2px;
}
QMenu::separator {
    height: 1px;
    background-color: %s;
    margin: 3px 2px;
}
""" % (CARD, BORDER, FG, PRIMARY_TINT, PRIMARY_HOVER, BORDER)

# 对话框基础样式（一次性套用：输入/下拉/列表/分组框全统一）
DIALOG_BASE_SS = "\n".join([LINEEDIT_SS, COMBO_SS, LIST_SS, GROUPBOX_SS, MENU_SS])


def apply_dialog_style(widget):
    """给 QDialog（或任意容器）套用基础主题样式"""
    widget.setStyleSheet(DIALOG_BASE_SS)
