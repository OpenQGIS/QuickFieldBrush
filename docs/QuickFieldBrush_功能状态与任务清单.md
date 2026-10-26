# QuickFieldBrush 功能状态与任务清单

> 维护者：Antigravity Agent ｜ 当前版本：v0.2.1 ｜ 更新时间：2026-10-26

---

## 一、功能组件状态矩阵

| 模块 / 功能项 | 对应文件 | 交互状态 | 稳定性与测试状态 |
|---|---|---|:---:|
| **工具栏入口** | `plugin.py` | 交互赋级 / 属性格式刷 / 操作历史 三大入口，支持快捷键切换 | ✅ PASS |
| **右键分级菜单** | `ui/rank_context_menu.py` | 单行顶栏、2 键智能翻转排序条、深黑值与中灰频次色彩分离、自定义新值 | ✅ PASS |
| **原生字段选择器** | `ui/rank_context_menu.py` | 支持 QGIS 原生 14 种矢量字段类型图标，过滤系统主键与只读字段 | ✅ PASS |
| **格式刷控制台** | `ui/format_painter_dialog.py` | 原生 4 行流式布局、2 键翻转排序、Win32 API 零闪烁置顶图钉、纯净属性值 | ✅ PASS |
| **真·属性吸管** | `core/format_painter_tool.py` | 地图单击直吸、右键瞬时吸管、蓝色 250ms 橡皮筋反馈 | ✅ PASS |
| **格式刷地图涂抹** | `core/format_painter_tool.py` | 左键连续刷入、绿色 180ms 闪烁、独立撤销单元、ESC 快捷退出 | ✅ PASS |
| **悬浮操作历史面板** | `ui/history_dialog.py` | 无模态悬浮、单步一键回滚 (`↺`)、撤销最新、实时搜索筛选、CSV 导出 | ✅ PASS |
| **历史地图联动** | `ui/history_dialog.py` | 单击居中平移闪烁、双击图层激活并选中要素 | ✅ PASS |
| **属性核心引擎** | `core/attribute_engine.py` | 强类型转换、会话级唯一值与频次缓存、万级要素 <0.15s | ✅ PASS |
| **用户配置管理** | `core/config_manager.py` | 按图层独立记忆目标字段与排序偏好、无锁 JSON 持久化 | ✅ PASS |
| **跨版本兼容层** | `core/compat.py` | 深度兼容 QGIS 3 (PyQt5) 与 QGIS 4 (PyQt6) | ✅ PASS |
| **多语言国际化** | `i18n/` + `i18n_helper.py` | 10 大全球主流语系覆盖 (`zh_CN/zh_TW/ja/ko/es/fr/de/ru/pt/it`) | ✅ PASS |

---

## 二、多环境部署与同步状态

| 环境标识 | 路径 | 角色定义 | 同步状态 |
|---|---|---|:---:|
| **QGIS 3 测试环境** | `C:\Users\tesla\AppData\Roaming\QGIS\QGIS3\profiles\ForTest\python\plugins\QuickFieldBrush` | 主开发与调试环境 | ✅ 已同步 |
| **QGIS 4 测试环境** | `C:\Users\tesla\AppData\Roaming\QGIS\QGIS4\profiles\ForTest\python\plugins\QuickFieldBrush` | PyQt6 跨版本验证环境 | ✅ 已同步 |
| **AttrSnap 镜像环境** | `C:\Users\tesla\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\AttrSnap` | 默认配置工作区镜像 | ✅ 已同步 |
| **Git 源码主仓库** | `D:\GitHub\QuickFieldBrush` | 官方 GitHub 代码托管与版本控制仓库 | ✅ 已同步 |
| **分发与归档发布库** | `E:\QGIS文章\OpenQGIS_Lab\OpenQGIS_QGISPlugins_LAB\QuickFieldBrush` | 仅保留 `QuickFieldBrush-4QGIS` 与 `QuickFieldBrush_History` | ✅ 已规范 |

---

## 三、代码规范与发布审核自检

- [x] **Bandit 扫描**：14 个源码文件 100% 审计通过，0 处安全漏洞（彻底解决全部 19 处 B110 `try_except_pass`，精准收敛为特定异常与合法处理，Release 纯净发布包无需任何 `#nosec` 豁免）
- [x] **detect-secrets**：0 处敏感秘钥或明文凭证泄漏
- [x] **Flake8 代码规范**：0 处语法与命名错误，0 处裸 except
- [x] **Metadata 规范**：无裸 `%`，Python `configparser` 解析 100% 通过
- [x] **ZIP 结构规范**：统一命名 `QuickFieldBrush_V-0.2.1.zip`，顶级目录为 `QuickFieldBrush/`，全 POSIX `/` 路径，包内 14 个源码文件无冗余临时文件
