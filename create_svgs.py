import os

plugin_dir = os.path.dirname(os.path.abspath(__file__))
icons_dir = os.path.join(plugin_dir, "icons")
icon_dir = os.path.join(plugin_dir, "icon")

os.makedirs(icons_dir, exist_ok=True)
os.makedirs(icon_dir, exist_ok=True)

svgs = {
    # 插件主图标
    "icon.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <rect x="2" y="2" width="60" height="60" rx="14" fill="#1976D2"/>
  <polygon points="36,8 18,36 32,36 28,56 46,28 32,28" fill="#FFFFFF"/>
</svg>""",
    # 工具栏主功能图标
    "rank.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <rect x="1" y="1" width="30" height="30" rx="6" fill="#1976D2"/>
  <polygon points="18,4 9,18 16,18 14,28 23,14 16,14" fill="#FFFFFF"/>
</svg>""",
    "painter.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <rect x="1" y="1" width="30" height="30" rx="6" fill="#E65100"/>
  <path d="M21,6 L26,11 L16,21 L11,21 L11,16 Z" fill="#FFFFFF"/>
  <path d="M11,21 C9.5,21 8,22 8,24 C8,25 9,25.5 10,25.5 C11.5,25.5 12,24 13,23 Z" fill="#FFE0B2"/>
  <line x1="19" y1="8" x2="24" y2="13" stroke="#BF360C" stroke-width="1.2"/>
</svg>""",
    "history.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <rect x="1" y="1" width="30" height="30" rx="6" fill="#6A1B9A"/>
  <path d="M16,7 A9,9 0 1,1 9.6,9.8 L7,7 M7,12 L7,7 L12,7" stroke="#FFFFFF" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  <polyline points="16,11 16,16 20,18" stroke="#FFFFFF" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",
    "panel.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <rect x="1" y="1" width="30" height="30" rx="6" fill="#2E7D32"/>
  <rect x="8" y="6" width="16" height="20" rx="2" fill="#FFFFFF"/>
  <rect x="12" y="4" width="8" height="4" rx="1" fill="#A5D6A7" stroke="#1B5E20" stroke-width="0.8"/>
  <line x1="11" y1="12" x2="21" y2="12" stroke="#388E3C" stroke-width="1.8" stroke-linecap="round"/>
  <line x1="11" y1="16" x2="21" y2="16" stroke="#81C784" stroke-width="1.8" stroke-linecap="round"/>
  <line x1="11" y1="20" x2="17" y2="20" stroke="#81C784" stroke-width="1.8" stroke-linecap="round"/>
</svg>""",
    "settings.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <rect x="1" y="1" width="30" height="30" rx="6" fill="#546E7A"/>
  <path d="M16,11 C13.24,11 11,13.24 11,16 C11,18.76 13.24,21 16,21 C18.76,21 21,18.76 21,16 C21,13.24 18.76,11 16,11 Z M16,18 C14.9,18 14,17.1 14,16 C14,14.9 14.9,14 16,14 C17.1,14 18,14.9 18,16 C18,17.1 17.1,18 16,18 Z" fill="#FFFFFF"/>
  <path d="M24.2,14.8 L22.8,14.5 C22.6,13.9 22.3,13.4 21.9,12.9 L22.7,11.7 C23,11.3 22.9,10.7 22.5,10.3 L21.7,9.5 C21.3,9.1 20.7,9 20.3,9.3 L19.1,10.1 C18.6,9.7 18.1,9.4 17.5,9.2 L17.2,7.8 C17.1,7.3 16.6,6.9 16.1,6.9 L14.9,6.9 C14.4,6.9 13.9,7.3 13.8,7.8 L13.5,9.2 C12.9,9.4 12.4,9.7 11.9,10.1 L10.7,9.3 C10.3,9 9.7,9.1 9.3,9.5 L8.5,10.3 C8.1,10.7 8,11.3 8.3,11.7 L9.1,12.9 C8.7,13.4 8.4,13.9 8.2,14.5 L6.8,14.8 C6.3,14.9 5.9,15.4 5.9,15.9 L5.9,17.1 C5.9,17.6 6.3,18.1 6.8,18.2 L8.2,18.5 C8.4,19.1 8.7,19.6 9.1,20.1 L8.3,21.3 C8,21.7 8.1,22.3 8.5,22.7 L9.3,23.5 C9.7,23.9 10.3,24 10.7,23.7 L11.9,22.9 C12.4,23.3 12.9,23.6 13.5,23.8 L13.8,25.2 C13.9,25.7 14.4,26.1 14.9,26.1 L16.1,26.1 C16.6,26.1 17.1,25.7 17.2,25.2 L17.5,23.8 C18.1,23.6 18.6,23.3 19.1,22.9 L20.3,23.7 C20.7,24 21.3,23.9 21.7,23.5 L22.5,22.7 C22.9,22.3 23,21.7 22.7,21.3 L21.9,20.1 C22.3,19.6 22.6,19.1 22.8,18.5 L24.2,18.2 C24.7,18.1 25.1,17.6 25.1,17.1 L25.1,15.9 C25.1,15.4 24.7,14.9 24.2,14.8 Z" fill="#ECEFF1"/>
</svg>""",
    # 界面子功能/动作图标
    "switch_view.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">
  <path d="M3,6 L14,6 M11,3 L14,6 L11,9" stroke="#37474F" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M17,14 L6,14 M9,11 L6,14 L9,17" stroke="#37474F" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",
    "refresh.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">
  <path d="M16,10 A6,6 0 1,1 14.2,5.8 L16,4 M16,8.5 L16,4 L11.5,4" stroke="#0277BD" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",
    "organize.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">
  <rect x="3" y="3" width="14" height="14" rx="2" fill="none" stroke="#455A64" stroke-width="1.6"/>
  <line x1="8" y1="3" x2="8" y2="17" stroke="#455A64" stroke-width="1.2"/>
  <line x1="3" y1="8" x2="17" y2="8" stroke="#455A64" stroke-width="1.2"/>
  <line x1="3" y1="13" x2="17" y2="13" stroke="#455A64" stroke-width="1.2"/>
</svg>""",
    "pin.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">
  <path d="M8,3 L12,3 L11,7 L14,10 L11,10 L10,16 L9,10 L6,10 L9,7 Z" fill="#2E7D32" stroke="#1B5E20" stroke-width="0.8" stroke-linejoin="round"/>
</svg>""",
    "absorb.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">
  <path d="M15.5,4.5 C16.2,3.8 17.2,3.8 17.8,4.5 C18.5,5.2 18.5,6.2 17.8,6.8 L15.2,9.4 L12.6,6.8 Z" fill="#1565C0"/>
  <path d="M14.2,10.4 L11.6,7.8 L6,13.4 L6,16 L8.6,16 Z" fill="#90CAF9" stroke="#1565C0" stroke-width="1" stroke-linejoin="round"/>
  <polygon points="6,16 3,19 5,16" fill="#0D47A1"/>
</svg>""",
    "search.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">
  <circle cx="8.5" cy="8.5" r="5.5" stroke="#757575" stroke-width="1.8" fill="none"/>
  <line x1="12.5" y1="12.5" x2="17" y2="17" stroke="#757575" stroke-width="1.8" stroke-linecap="round"/>
</svg>""",
    "apply.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">
  <path d="M4,10.5 L8,14.5 L16,6.5" fill="none" stroke="#2E7D32" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",
    "clear.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">
  <line x1="5" y1="5" x2="15" y2="15" stroke="#C62828" stroke-width="2.2" stroke-linecap="round"/>
  <line x1="15" y1="5" x2="5" y2="15" stroke="#C62828" stroke-width="2.2" stroke-linecap="round"/>
</svg>""",
    "add.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">
  <line x1="10" y1="4" x2="10" y2="16" stroke="#1976D2" stroke-width="2.2" stroke-linecap="round"/>
  <line x1="4" y1="10" x2="16" y2="10" stroke="#1976D2" stroke-width="2.2" stroke-linecap="round"/>
</svg>""",
    "select_all.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">
  <rect x="3" y="3" width="14" height="14" rx="2" fill="none" stroke="#1976D2" stroke-width="1.8"/>
  <path d="M6,10 L9,13 L14,7" fill="none" stroke="#1976D2" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>""",
    "deselect_all.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">
  <rect x="3" y="3" width="14" height="14" rx="2" fill="none" stroke="#757575" stroke-width="1.8"/>
</svg>""",
    "invert.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="20" height="20">
  <rect x="3" y="3" width="14" height="14" rx="2" fill="none" stroke="#00796B" stroke-width="1.8"/>
  <polygon points="3,3 17,3 17,17" fill="#00796B"/>
</svg>"""
}

# 写入 icons/ 目录
for name, content in svgs.items():
    with open(os.path.join(icons_dir, name), "w", encoding="utf-8") as fp:
        fp.write(content)

# 兼容保留 icon/ 与根目录 icon.svg
for k in ["icon.svg", "rank.svg", "painter.svg", "history.svg"]:
    if k in svgs:
        with open(os.path.join(icon_dir, k), "w", encoding="utf-8") as fp:
            fp.write(svgs[k])
with open(os.path.join(plugin_dir, "icon.svg"), "w", encoding="utf-8") as fp:
    fp.write(svgs["icon.svg"])

print(f"Generated {len(svgs)} SVG icons into {icons_dir}!")
