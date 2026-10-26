# QuickFieldBrush 插件发布与分发全流程指引 (Distribution Guide)

本项目遵循 QGIS 官方插件门户（[plugins.qgis.org](https://plugins.qgis.org/)）标准规范，并严格执行 OpenQGIS 团队工程化发布准则。

---

## 目录
- [一、Metadata 规范与版本控制](#一metadata-规范与版本控制)
- [二、代码安全审查与质量扫描](#二代码安全审查与质量扫描)
- [三、多语言国际化 (i18n) 机制](#三多语言国际化-i18n-机制)
- [四、分发打包双轨工作流](#四分发打包双轨工作流)
- [五、发布前检查清单 (Checklist)](#五发布前检查清单-checklist)

---

## 一、Metadata 规范与版本控制

核心文件：`metadata.txt`（位于解压第一层根目录）

1. **绝对规避 `%` 符号引发的 INI 变量插值中断**：
   - 官方插件门户后端使用 Python `configparser.ConfigParser`（默认开启 BasicInterpolation）。
   - 严禁在 `about` 或 `changelog` 中直接使用单 `%` 符号（如 `50%（`）。
   - 如需表示百分比，使用两个连续百分号 `%%` 转义，或改用中英文文字（如 `50 percent` / `一半`）。
2. **多行延续值悬挂缩进**：
   - `about=` 和 `changelog=` 键下方的所有延续行必须保持至少 **2 个空格**的悬挂缩进。
3. **双语结构与客观技术视角**：
   - 更新日志采用 `中文描述 / English description` 结构，搭配标准 Emoji 分类（🎨 UI、⚡ 性能、🧪 交互、🕒 历史、✨ 新增、🐛 修复）。
   - 始终站在**用户价值视角**阐明“用户能做什么”，避免“内部类重构”等自嗨术语；保持客观技术视角，杜绝夸张营销腔。
4. **版本号语义化自增**：
   - 遵循 `Semantic Versioning (X.Y.Z)`，每次发布必须严格大于历史版本。

---

## 二、代码安全审查与质量扫描

根据 QGIS 官方安全审核规则（`plugins.qgis.org/docs/security-scanning/`），代码必须通过四大核心检测：

1. **Bandit (Python 静态安全)** —— 🔴 CRITICAL (拦截级)：
   - 严禁命令注入（禁止在 `subprocess` 或系统调用中使用 `shell=True`）；
   - 严禁动态代码执行（禁止使用 `eval()`、`exec()`、`compile()` 解析外部输入）；
   - 严禁不安全反序列化（禁止 `pickle` 处理非受信数据）；
   - 严禁 SQL 字符串拼接注入。
2. **detect-secrets (凭证泄漏检测)** —— 🔴 CRITICAL (拦截级)：
   - 严禁硬编码明文 API Key、Token、私钥证书或数据库连接密码；
   - 杜绝长随机高熵字符串混淆。
3. **Flake8 (语法与代码规范)** —— 🔵 INFO：
   - 消除 `E741`（严禁使用小写 `l`、大写 `I`、大写 `O` 作为独立单字母变量或参数）；
   - 消除 `F821`（未定义名称）、`E722`（裸 `except:`）、`W605`（无效转义序列）。
4. **纯粹 `Validated` 认证状态**：
   - 代码本身达到完全合规后，纯净发布包内**不放置** `.bandit` 或 `.flake8` 配置文件，以获取官方审核最高规格的纯绿标准 **`Validated`** 徽章（避免被判定为带配置豁免的 `Validated (configured)`）。

---

## 三、多语言国际化 (i18n) 机制

1. **全静态键包裹**：
   - 所有 UI 文本统一通过 `tr("English String")` 包裹，严禁动态 f-string（动态内容使用占位符 `{0}` + `.format()`）。
2. **双保险 Fallback 机制**：
   - 运行时优先检索 `i18n/QuickFieldBrush_<locale>.qm` 翻译文件；
   - 若未编译或在未覆盖的 Linux/Mac Locale 环境下，通过 `i18n_strings._zh_translations` 字典自动保底，绝无漏翻或乱码。
3. **自动化编译脚本**：
   - 运行 `python i18n/build_i18n.py` 可一键基于字典自动更新同步 `.ts` 源码并编译为紧凑二进制 `.qm` 文件。

---

## 四、分发打包双轨工作流

分发体系采用**纯净发布包**与**开发历史归档包**双轨制管理：

### 4.1 纯净发布路径 (`QuickFieldBrush-4QGIS`)
用于上传官方插件门户（plugins.qgis.org）或直接供用户离线安装：

* **包含内容（仅运行时必需功能源码与资源）**：
  ```text
  QuickFieldBrush/
  ├── __init__.py
  ├── plugin.py
  ├── metadata.txt
  ├── README.md
  ├── LICENSE
  ├── i18n_strings.py
  ├── i18n_helper.py
  ├── core/            # 核心业务算法与图层操作逻辑
  ├── ui/              # 原生 Qt 对话框、面板与上下文菜单
  ├── icon/            # 插件入口主 Logo (icon.svg)
  ├── icons/           # 运行时 20 个高精矢量 SF Symbols 图标
  ├── IconField/       # QGIS 原生矢量字段类型图标集 (123/abc 等)
  └── i18n/
      └── QuickFieldBrush_zh_CN.qm  # 仅保留编译后的二进制翻译
  ```
* **绝对剔除内容 (Exclude Rules)**：
  - ❌ 开发辅助与测试目录：`dev/`、`scratch/`、`tools/`、`tests/`
  - ❌ 源码翻译编辑文件：`i18n/*.ts`、`i18n/build_i18n.py`
  - ❌ 历史压缩包与中间文件：`*.zip`、`*.pyc`、所有 `__pycache__/` 文件夹
  - ❌ 版本控制与 IDE 隐藏目录：`.git/`、`.gitignore`、`.vscode/`、`.idea/`
  - ❌ 静态安全扫描配置文件：`.bandit`、`.flake8`、`.secrets.baseline`
* **ZIP 规范要求 (CRITICAL)**：
  - 顶级解压目录名必须为 **`QuickFieldBrush/`**（合规 PEP 8 命名，非数字开头）；
  - ZIP 内部所有条目路径分隔符必须为正斜杠 `/`（严禁 Windows 反斜杠 `\`）。
  - 发布包命名格式：统一使用 **`QuickFieldBrush_V-X.Y.Z.zip`**（如 `QuickFieldBrush_V-0.2.0.zip`）。

### 4.2 开发备份归档路径 (`QuickFieldBrush_History`)
用于开发者本地版本演进归档、全量源码备份与复现：
* 包含开发测试日志、截图与中间资产全量包；
* 归档命名格式：统一使用 **`QuickFieldBrush_V-X.Y.Z.zip`**。

---

## 五、发布前检查清单 (Checklist)

- [x] **Metadata 检查**：无裸 `%`，版本号自增为 `0.2.0`，双语日志清晰详尽，`configparser` 解析通过。
- [x] **代码安全审查**：无 `eval`/`exec`/`shell=True`，无硬编码秘钥，无 `E741`/`E722` 缺陷。
- [x] **国际化完整性**：109 个静态文本全覆盖，`QuickFieldBrush_zh_CN.qm` 二进制重新编译就绪。
- [x] **包体纯净性**：已从发布包剔除 `dev/`、`__pycache__/`、`*.ts`、配置点文件，解压第一层为 `QuickFieldBrush/`。
- [x] **路径斜杠合规**：ZIP 内部条目统一使用 POSIX `/` 路径。
