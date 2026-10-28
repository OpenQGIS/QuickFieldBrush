# QuickFieldBrush 插件发布与分发全流程指引 (Distribution Guide)

本项目遵循 QGIS 官方插件门户（[plugins.qgis.org](https://plugins.qgis.org/)）标准规范，并严格执行 OpenQGIS 团队工程化发布与质量治理准则。

---

## 目录
- [一、核心概念：三版本差异对比矩阵（必读）](#一核心概念三版本差异对比矩阵必读)
- [二、Metadata 规范与版本控制](#二metadata-规范与版本控制)
- [三、代码安全审查与质量扫描 (Security Scanning)](#三代码安全审查与质量扫描-security-scanning)
- [四、多语言国际化 (i18n) 机制](#四多语言国际化-i18n-机制)
- [五、分发打包双轨工作流与物理路径](#五分发打包双轨工作流与物理路径)
- [六、发布前检查清单 (Checklist)](#六发布前检查清单-checklist)

---

## 一、核心概念：三版本差异对比矩阵（必读）

在 QGIS 插件工程生命周期中，**本地测试版本**、**Git 推送版本** 与 **官方分发包版本** 的定位、受众和包含文件存在本质差异，严禁混淆：

| 维度 / 版本 | 1. 本地测试版本 (Local Test) | 2. Git 推送版本 (Git Repo) | 3. 官方分发版本 (Distribution ZIP) |
| :--- | :--- | :--- | :--- |
| **物理路径** | QGIS 活跃配置插件目录：<br>`.../profiles/ForTest/python/plugins/QuickFieldBrush` | GitHub 远程开源仓库：<br>`https://github.com/OpenQGIS/QuickFieldBrush` | 官方插件门户上传或私有源：<br>`QuickFieldBrush-4QGIS/QuickFieldBrush_V-X.Y.Z.zip` |
| **核心受众** | 核心开发者、本地测试员 | 开源协作者、代码审查员 (PR)、CI 流水线 | 全球/企业 QGIS 最终用户 |
| **核心用途** | 敏捷编码、热重载调试 (Plugin Reloader)、断点单步跟踪 | 版本演进追踪、协同开发、Issue 联动、安全 CI | QGIS 客户端“插件管理器”一键离线/在线解压安装即用 |
| **路线图 (ROADMAP.md)** | ✅ 包含（指导本地开发） | ✅ **必须包含**（向协作者展示敏捷迭代） | ❌ **绝对剔除**（普通用户无需关心排期细项） |
| **开发指南与中间设计** | ✅ 包含（`dev/`, `0_*.svg`, `scratch/`） | ✅ 规范保留在特定目录或文档站 | ❌ **绝对剔除**（严禁冗余文件进入发布包） |
| **版本控制元数据** | 可选（视是否软链接开发） | ✅ **包含完整 `.git/`, `.gitignore`** | ❌ **绝对剔除**（严禁包含任何 `.git*`） |
| **编译翻译包** | ✅ 包含 `.qm`（供 QGIS 界面显示） | ✅ 包含 `.ts` + `.qm` + `build_i18n.py` | ✅ **仅包含二进制 `.qm`**（剔除未编译 `.ts` 与脚本） |
| **Python 缓存与二进制** | ⚠️ 自动生成 `__pycache__/*.pyc` | ❌ **.gitignore 强力排除** | ❌ **绝对剔除**（严禁将 `.pyc` 或临时文件打包） |
| **静态扫描点文件** | 可选（本地排查辅助） | ✅ 可包含（供 GitHub Actions 运行） | ❌ **建议移除**（纯代码过检，获取标准纯绿 `Validated`） |
| **分发输出目录 (dist/)** | ❌ **严禁在此目录生成 dist/ 或压缩包** | ❌ **严禁提交 *.zip 到 Git 代码树** | ✅ **存放于专门归档目录** (`QuickFieldBrush-4QGIS/`) |

---

## 二、Metadata 规范与版本控制

核心文件：`metadata.txt`（位于解压第一层根目录）

1. **绝对规避 `%` 符号引发的 INI 变量插值中断（CRITICAL）**：
   - 官方插件门户后端使用 Python `configparser.ConfigParser`（默认开启 BasicInterpolation）。
   - 严禁在 `about` 或 `changelog` 中直接使用单 `%` 符号（如 `50%（` 或 `100%`）。
   - 如需表示百分比，使用两个连续百分号 `%%` 转义，或改用中英文文字（如 `50 percent` / `一半`）。
2. **多行延续值悬挂缩进**：
   - `about=` 和 `changelog=` 键下方的所有延续行必须保持至少 **2 个空格**的悬挂缩进。
3. **双语结构与客观技术视角**：
   - 更新日志采用 `中文描述 / English description` 结构，搭配标准 Emoji 分类（✨ 新增、🛠️ 重构、🧹 清洗、🧭 界面、🐛 修复）。
   - 始终站在**用户价值视角**阐明“用户能做什么”，避免“内部类重构”等自嗨术语；保持客观技术视角，杜绝夸张营销腔。
4. **版本号语义化自增**：
   - 遵循 `Semantic Versioning (X.Y.Z)`，每次发布必须严格大于历史版本号（如 `0.3.0` ➔ `0.4.0`）。

---

## 三、代码安全审查与质量扫描 (Security Scanning)

根据 QGIS 官方安全审核规则（`plugins.qgis.org/docs/security-scanning/`），代码必须通过四大核心检测：

1. **Bandit (Python 静态安全)** —— 🔴 CRITICAL (拦截级)：
   - 严禁命令注入（禁止在 `subprocess` 或系统调用中使用 `shell=True`）；
   - 严禁动态代码执行（禁止使用 `eval()`、`exec()`、`compile()` 解析外部输入）；
   - 严禁不安全反序列化（禁止 `pickle` 处理非受信数据）；
   - 严禁 SQL 字符串拼接注入；
   - **严禁盲捕获通用异常与静默吞噬 (`B110: try_except_pass`)**：严禁写 `except Exception: pass`。对于合法的容错场景，必须精准捕获特定的异常类型元组（如 `except (AttributeError, RuntimeError, TypeError, KeyError): pass`）或接入 `QgsMessageLog` 进行留痕。
   - **本地发布前强制门禁命令**：封包前必须运行 `bandit -r plugin_dir -x dev,tests,scratch`，确认 0 Issues。
2. **detect-secrets (凭证泄漏检测)** —— 🔴 CRITICAL (拦截级)：
   - 严禁硬编码明文 API Key、Token、私钥证书或数据库连接密码；
   - 杜绝长随机高熵字符串混淆。
3. **Flake8 (语法与代码规范)** —— 🔵 INFO：
   - 消除 `E741`（严禁使用小写 `l`、大写 `I`、大写 `O` 作为独立单字母变量或参数）；
   - 消除 `F821`（未定义名称）、`E722`（裸 `except:`）、`W605`（无效转义序列）。
4. **纯粹 `Validated` 认证状态**：
   - 代码本身达到完全合规后，纯净发布包内**不放置** `.bandit` 或 `.flake8` 配置文件，以获取官方审核最高规格的纯绿标准 **`Validated`** 徽章（避免被判定为带配置豁免的 `Validated (configured)`）。

---

## 四、多语言国际化 (i18n) 机制

1. **全静态键包裹**：
   - 所有 UI 文本统一通过 `tr("English String")` 包裹，严禁动态 f-string（动态内容使用占位符 `{0}` + `.format()`）。
2. **双保险 Fallback 机制**：
   - 运行时优先检索 `i18n/QuickFieldBrush_<locale>.qm` 翻译文件；
   - 若未编译或在未覆盖的 Linux/Mac Locale 环境下，通过 `i18n_strings._zh_translations` 字典自动保底，绝无漏翻或乱码。
3. **差集自动化检查与编译脚本**：
   - 运行 AST 提取脚本，保证代码内调用的 `tr()` 字符串与 `_zh_translations` 差集为 0；
   - 运行 `python i18n/build_i18n.py zh_CN` 与 `zh_TW`，生成标准二进制 `.qm` 语言包。

---

## 五、分发打包双轨工作流与物理路径

分发体系采用**纯净发布包**与**开发历史归档包**双轨制管理，物理路径脱离实时测试目录：

### 5.1 正式分发发布路径 (`QuickFieldBrush-4QGIS`)
存放面向 QGIS 官方门户（plugins.qgis.org）或用户分发的纯净制品：
- **路径**：`E:\QGIS文章\OpenQGIS_Lab\OpenQGIS_QGISPlugins_LAB\QuickFieldBrush\QuickFieldBrush-4QGIS\`
- **包含内容**：
  1. `QuickFieldBrush/` —— 纯净源码镜像目录（同步最新代码，但排除一切开发杂质）；
  2. `QuickFieldBrush_V-X.Y.Z.zip` —— 对应版本的正式发布压缩包（如 `QuickFieldBrush_V-0.4.0.zip`）。

* **分发包解压后标准结构**：
  ```text
  QuickFieldBrush/
  ├── __init__.py
  ├── plugin.py
  ├── metadata.txt
  ├── README.md
  ├── LICENSE
  ├── CHANGELOG.md
  ├── i18n_strings.py
  ├── i18n_helper.py
  ├── core/            # 核心业务算法与属性引擎
  ├── ui/              # 原生 Qt 对话框、悬浮面板与菜单组件
  ├── icon/            # 插件入口主 Logo (icon.svg)
  ├── icons/           # 运行时矢量操作图标 (add, absorb, clear, pin 等)
  ├── IconField/       # QGIS 原生矢量字段类型图标集 (123/abc 等 14 种)
  └── i18n/
      ├── QuickFieldBrush_zh_CN.qm  # 编译后的二进制翻译
      └── QuickFieldBrush_zh_TW.qm
  ```

* **绝对剔除内容 (Exclude Rules)**：
  - ❌ 路线图与开发指南：`ROADMAP.md`、`DISTRIBUTION_GUIDE.md`、`docs/`
  - ❌ 开发辅助与测试脚本：`dev/`、`scratch/`、`tools/`、`tests/`、`create_svgs.py`
  - ❌ 源码翻译编辑源文件：`i18n/*.ts`、`i18n/build_i18n.py`、`keys.json`
  - ❌ 历史压缩包与编译缓存：`*.zip`、`*.pyc`、所有 `__pycache__/` 文件夹
  - ❌ 版本控制与 IDE 隐藏目录：`.git/`、`.gitignore`、`.vscode/`、`.idea/`
  - ❌ 设计临时稿与测试数据库：`0_*.svg`、`symbology-style.db`
  - ❌ 静态安全扫描配置文件：`.bandit`、`.flake8`、`.secrets.baseline`

* **ZIP 规范要求 (CRITICAL)**：
  - 顶级解压目录名必须为 **`QuickFieldBrush/`**（合规 PEP 8 命名，非数字开头）；
  - ZIP 内部所有条目路径分隔符必须为正斜杠 `/`（严禁 Windows 反斜杠 `\`）；
  - 发布包命名格式：统一使用 **`QuickFieldBrush_V-X.Y.Z.zip`**。

### 5.2 历史归档库路径 (`QuickFieldBrush_History`)
用于开发者本地版本演进归档、全量源码备份与复现追踪：
- **路径**：`E:\QGIS文章\OpenQGIS_Lab\OpenQGIS_QGISPlugins_LAB\QuickFieldBrush\QuickFieldBrush_History\`
- **归档命名格式**：统一保存对应版本的完整发布包副本 `QuickFieldBrush_V-X.Y.Z.zip`。

---

## 六、发布前检查清单 (Checklist)

在上传至官方插件门户或对外部署前，对照本表逐项核查：

- [x] **Metadata 检查**：无裸 `%`，版本号自增为 `0.4.0`，双语日志清晰详尽，`configparser` 解析 100% 通过。
- [x] **安全扫描审计**：AST 遍历确认 0 处 B110 盲捕获，无 `eval`/`exec`/`shell=True`，无硬编码秘钥，无 `E741`/`E722` 缺陷。
- [x] **国际化完整性**：128 个静态文本 100% 覆盖（0 缺失），`QuickFieldBrush_zh_CN.qm` 与 `zh_TW.qm` 二进制重新编译就绪。
- [x] **三版本边界清晰**：发布包内已彻底剔除 `ROADMAP.md`、`DISTRIBUTION_GUIDE.md`、`dev/`、`0_*.svg` 等非运行时文件。
- [x] **包体与路径合规**：顶级解压目录为 `QuickFieldBrush/`，条目统一使用 POSIX `/` 路径，包体体积控制在 210 KB 以内。
- [x] **发布路径归位**：安装包已输出至 `QuickFieldBrush-4QGIS/` 及 `QuickFieldBrush_History/`，开发测试目录干净无残留。
