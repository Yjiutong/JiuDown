# JiuDown（玖号下载器）

JiuDown 桌面版（玖号下载器） - 自研双引擎（原生 B 站 + yt-dlp）的全站视频下载工具

## 项目简介

JiuDown（玖号下载器）是一个基于 Python 开发的全功能视频下载桌面应用，使用自研的 **JiuDown 引擎**（双后端架构）：B 站走原生链路（接口直连 + DASH 分片 + FFmpeg 合并，由本项目自己维护），其余 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 支持的 1700+ 站点（YouTube、抖音、Vimeo、X 等）由通用后端处理，任一后端失败会自动降级到另一个。界面采用 PySide6（Qt）构建，提供与 Apple HIG 一致的原生桌面体验。

本项目 **fork 自开源项目 [JiJiDownForDesktop](https://github.com/o5-null/JiJiDownForDesktop)（唧唧下载器桌面版）**，并在此基础上修改完善，包括界面重构、架构升级与功能增强。

## 项目来源

本项目 fork 自 [JiJiDownForDesktop](https://github.com/o5-null/JiJiDownForDesktop)（原项目：JiJiDown Desktop，唧唧下载器桌面版，作者 o5-null），并在其基础上修改完善：

- **下载引擎**：自研 **JiuDown 引擎**（`jiudown_engine.py`）——B 站走原生链路（原核心逻辑重写为进程内 Python 实现，清晰度映射/风控 Cookie/分片下载全部自己维护），其他站点走 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 通用后端，双后端自动降级
- **界面重构**：由原始 NiceGUI Web 界面重构为 PySide6 (Qt) 原生桌面应用
- **架构升级**：新增 asyncio 后台线程桥、模块化页面结构、QSS 统一设计规范
- **功能完善**：多任务并发调度、断点续传、批量下载、状态监控、日志管理等

> 上游原项目：[o5-null/JiJiDownForDesktop](https://github.com/o5-null/JiJiDownForDesktop)。上游项目与核心组件均属第三方开源作品，本项目仅在其基础上修改完善，遵守上游项目的开源许可与使用条款。

## 功能特性

### 核心功能
- 🌐 **双引擎全站支持**：B 站走自研原生链路（解析快、字段可控），YouTube/抖音/Vimeo/X 等 1700+ 站点走 yt-dlp 通用后端
- 🔀 **自动降级**：B 站原生链路失败时自动切到 yt-dlp，反之亦然，单站点故障不影响整体可用性
- 🎚️ **画质与格式**：最高 / 1080P / 720P / 480P / 360P 五档，mp4 / flv / mp3 / wav 四种输出
- 🍪 **登录内容**：可直接读取 Chrome / Edge / Firefox 等浏览器的 Cookie，下载会员/私享内容
- 📝 **可读错误**：站点风控、需登录、链接不支持等情况翻译成一句中文提示，不抛原始堆栈
- 🔄 **引擎可更新**：站点改版导致解析失败时，一键更新 yt-dlp 即可恢复
- 📱 **跨平台支持**：支持Windows、macOS、Linux系统
- 🖥️ **原生桌面界面**：基于PySide6 (Qt) 的现代桌面应用界面

### 下载管理
- 🎬 **多任务下载**：可配置并发数，多任务并行下载
- 📚 **播放列表**：可设置合集/播放列表最多下载条数（默认只下当前视频）
- 🚀 **智能限速**：可配置下载速度限制，避免网络拥堵
- 📊 **实时进度**：显示当前文件进度、综合进度、速度与体积
- 🔄 **分片重试**：yt-dlp 分片级重试 + 任务级重试，网络抖动不丢进度

### 系统特性
- 🔧 **灵活配置**：下载目录、临时目录、代理、Cookie 来源、限速、并发均可配置
- 📝 **详细日志**：运行日志与下载记录双面板，彩色分级、可打开日志目录
- 🎬 **在线预览**：悬停标签播放低清流，任务卡内嵌播放器可看在线/本地
- 🔄 **自动更新**：FFmpeg 完整版自动拉取，yt-dlp 引擎一键升级

## 系统要求

### 操作系统
- **Windows** 7/8/10/11 (x86/x64)
- **macOS** 10.14+ (Intel/Apple Silicon)
- **Linux** Ubuntu 18.04+, CentOS 7+, 其他主流发行版

### Python环境
- **Python** 3.9+
- **pip** 最新版本

### 硬件要求
- **内存**: 最低 2GB，推荐 4GB+
- **存储**: 至少 500MB 可用空间
- **网络**: 稳定的互联网连接

## 安装指南

### 1. 克隆项目

```bash
git clone https://github.com/Yjiutong/JiuDown.git
cd JiuDown
```

仓库不含任何二进制依赖（运行时 / FFmpeg 均不入库），克隆下来只有约 40 个源码文件；
缺失的部分会在首次运行时自动拉取。克隆到任意目录都可以，**没有硬编码路径**。

### 2. 选择一种启动方式

**方式 A：普通用户（无需安装 Python，推荐）**

1. 双击 `首次安装.bat` —— 从 GitHub Release 拉取离线运行时
   （`runtime\python`，约 320MB，含 PySide6 / yt-dlp / FFmpeg）
2. 双击 `启动.vbs` —— 静默启动，全程无控制台窗口

**方式 B：开发者（本机已有 Python 3.9+）**

```bash
pip install -r requirements.txt
python app.py
```

### 3. 首次运行会自动完成的事

| 缺失项 | 自动处理 | 来源 |
|---|---|---|
| `runtime/` | 按组件清单（`manifest.json`）只拉缺失的组件，合计约 100MB | GitHub Release `runtime` 标签 |
| 运行时里的 `yt-dlp` 后端 | 随 `runtime.zip` 一起下发，**不走 PyPI** | 同上 |
| `resources/ffmpeg.exe` | 下载完整版 FFmpeg 并替换 | BtbN FFmpeg-Builds |
| `config/`、`Download/`、`logs/` | 启动时按程序所在目录自动创建 | 本地 |

> 依赖来源只有两处：本仓库 Release 上的 `runtime.zip`，以及 FFmpeg 的公开构建源。
> 若检测到运行时里没有下载引擎（旧版运行时），会自动按 Release 重新拉取，
> **不会**擅自从 PyPI 安装。设置页的「更新引擎」是显式的增量升级操作（`pip install -U yt-dlp`），
> 需要离线可控时可改为重新运行 `首次安装.bat`。

所有路径都相对程序所在目录解析，移动或改名项目文件夹不会影响使用。

## 依赖组件与增量更新

运行时不再是单个 339MB 的整包，而是拆成若干 **小于 100MB 的组件**，
按功能与更新频率切分（打包工具：`tools/build_components.py`）：

| 组件 | 内容 | 压缩后 | 更新频率 |
|---|---|---|---|
| `core` | Python 3.12 解释器 + 标准库 | 12.5 MB | 几乎不变 |
| `pyside-1/2/3` | PySide6（已剥离 WebEngine / Pdf / Quick / Qml 等未使用模块，省 420MB） | 30.8 / 31.0 / 17.5 MB | 随界面依赖升级 |
| `engine` | yt-dlp 与其依赖（Cryptodome / mutagen / websockets / brotli） | **5.3 MB** | 站点改版后 |
| `app` | requests / loguru / pyyaml / psutil 等运行依赖 | 3.2 MB | 很少变 |

合计约 **100MB**（原整包 339MB）。`ffmpeg.exe`（161MB）不进组件，由 `ffmpeg_manager` 独立下载管理。

**带来的实际收益**

- 首次安装：从 339MB 降到约 100MB
- 更新下载引擎：只下 `engine.zip`（5.3MB），设置页点「更新引擎」即完成，重启生效
- 某个组件损坏/缺失：只补那一个组，不再整包重下

**发布新版本组件**

```bash
python tools/build_components.py            # 生成 build_components/*.zip + manifest.json
python tools/build_components.py --manifest-only   # 只改清单，不重打包
python tools/build_components.py --keep-all        # 保留 PySide6 全部模块（不剥离）
```

把 `build_components/` 里的 zip 与 `manifest.json` 一起上传到 release 的 `runtime` 标签即可。
客户端拉不到 `manifest.json` 时会自动回退到整包 `runtime.zip`（兼容旧发布）。

## 项目结构

```
JiuDown/                       （仓库只含源码，二进制依赖首跑自动拉取）
├── app.py                     # 主程序入口（配置初始化 + 窗口 + 后台自检）
├── main_window.py             # 主窗口（侧边导航 + 页面栈 + 托盘）
├── theme.py                   # 主题令牌与 QSS（Apple HIG，双主题）
├── async_bridge.py            # asyncio 后台线程桥（下载调度）
├── jiudown_engine.py          # JiuDown 引擎：双后端路由 + 原生 B 站链路
├── ytdlp_engine.py            # yt-dlp 通用后端（解析 / 下载 / 预览直链）
├── download_manager.py        # 下载任务队列与并发调度
├── ffmpeg_manager.py          # FFmpeg 探测 / 下载 / 能力缓存
├── runtime_manager.py         # 离线运行时自举（runtime.zip）
├── config_manager.py          # 配置管理（CONFIG_SCHEMA 统一读写）
├── log_manager.py             # 日志持久化
├── system_info.py             # 系统信息与默认路径
├── pages/
│   ├── home_page.py           # 状态总览（引擎 / 站点 / FFmpeg / 系统）
│   ├── download_page.py       # 下载页（标签卡 + 任务卡 + 右键参数）
│   ├── preview_panel.py       # 内嵌预览播放器（本地流代理）
│   ├── hover_preview.py       # 悬停低清小窗
│   ├── log_page.py            # 运行日志 + 下载记录
│   └── settings_page.py       # 设置页（基本/下载/网络/用户/高级）
├── runtime_components.py      # 运行时组件划分（打包端与运行端共用）
├── tools/
│   ├── build_components.py    # 打包运行时组件（生成 zip + manifest.json）
│   └── install_runtime.ps1    # 首次安装：按组件拉取，失败回退整包
├── 启动.vbs                   # 无控制台启动器（自动探测解释器）
├── 首次安装.bat               # 首次安装：拉取离线运行时
├── JiuDownDesktop.spec        # PyInstaller 打包配置（相对路径）
├── requirements.txt
├── resources/app.ico          # 唯一入库的二进制资源（图标）
└── config/ Download/ TEMP/ logs/ runtime/   # 运行时生成，已 gitignore
```

## 核心模块说明

### app.py / main_window.py
应用入口与主窗口，负责：
- 初始化应用配置
- 创建桌面主窗口（侧边导航 + 页面栈）
- 启动 asyncio 后台线程桥
- 管理核心文件状态
- 处理用户交互

### pages/
页面模块，每个页面一个文件：
- `home_page.py`：状态总览（下载引擎、支持站点、FFmpeg、系统环境 + 引擎诊断）
- `download_page.py`：B站视频批量下载与任务管理
- `log_page.py`：核心运行日志与下载记录
- `settings_page.py`：应用配置与参数设置

### async_bridge.py
asyncio 后台线程桥，让基于 asyncio 的下载调度与 Qt 事件循环共存。

### theme.py
全局 QSS 样式表与配色常量，统一定义界面视觉规范。

### config_manager.py
配置管理模块，提供：
- 统一的配置访问接口
- 配置验证和标准化
- 配置缓存机制
- 支持YAML配置文件

### jiudown_engine.py / ytdlp_engine.py
下载引擎层。`jiudown_engine` 是统一门面（双后端路由 + 原生 B 站链路），
`ytdlp_engine` 是通用后端（1700+ 站点）与各类共享工具（URL 规范化、画质→格式映射、
FFmpeg 转码、错误中文化）。

### system_info.py
系统信息工具模块，提供：
- 系统架构检测
- 平台适配
- 路径管理
- 缓存机制

### ffmpeg_manager.py / runtime_manager.py
外部依赖自举。`ffmpeg_manager` 负责 FFmpeg 的探测、精简版/完整版识别、自动下载与能力缓存；
`runtime_manager` 负责离线运行时（`runtime.zip`）的完整性校验与从 GitHub Release 拉取。

## 配置说明

### 配置文件位置（便携模式）
程序采用**便携模式**，所有数据均存放在程序目录下（相对 `app.py` / exe 解析，**不写死任何绝对路径**），
**不写入系统 AppData**，因此整个文件夹可以随意移动或改名：

- **配置**: `<程序目录>/config/config.yaml`
- **日志**: `<程序目录>/logs/`
- **临时文件**: `<程序目录>/TEMP/`
- **下载目录**: `<程序目录>/Download/`
- **离线运行时**: `<程序目录>/runtime/`（首次安装时拉取，不入库）
- **FFmpeg**: `<程序目录>/resources/ffmpeg.exe`（首次运行自动下载，不入库）
- **图标**: `<程序目录>/resources/app.ico`（唯一入库的二进制资源）

> 旧版本写入 `%APPDATA%\JiuDown` / `%APPDATA%\SHOUDown` 的配置会在首次启动时迁移到便携目录并清理旧目录。

### 主要配置项

```yaml
# 日志级别
log-level: info

# 外部控制器端口
external-controller-port:
  grpc: 4000
  grpc-web: 4100
  restful-api: 64001

# 用户信息
user-info:
  access-token: ""
  refresh-token: ""
  cookies: ""
  hide-nickname: false

# 下载任务设置
download-task:
  temp-dir: "./TEMP"          # 临时目录
  download-dir: "./Download"   # 下载目录
  ffmpeg-path: ""             # FFmpeg路径
  max-task: 2                 # 最大同时任务数
  download-speed-limit: 0     # 下载速度限制(0为不限速)
  disable-mcdn: false         # 禁用mCDN
```

## 使用说明

### 首次使用
1. 启动应用后，系统会自动检测您的系统架构
2. 如果核心文件不存在，界面会显示下载按钮
3. 点击下载按钮，系统会自动下载对应版本的核心文件
4. 下载完成后，文件会自动进行哈希验证

### 核心文件管理
- **自动检测**: 启动时自动检查核心文件状态
- **哈希验证**: 通过SHA256验证文件完整性
- **自动更新**: 检测到新版本时提示更新
- **手动下载**: 支持手动选择下载核心文件

### 下载操作
1. 在应用界面输入B站视频链接（支持批量，每行一个）
2. 选择下载格式与质量：
   - 视频：`mp4` / `flv` + 清晰度（360P/480P/720P/1080P）
   - 纯音频：`mp3`（后缀名方式），选择后质量位切换为声道（单声道/双声道，默认双声道）
3. 设置保存路径
4. 点击「开始」并查看实时进度

> 说明：完整版 FFmpeg（约 100MB）**不随仓库分发**。首次启动或缺失时应用会在后台自动拉取（源：gyan.dev essentials 构建），下载完成后自动启用；也可手动下载后放入 `resources\ffmpeg.exe`。状态总览页可查看下载进度或手动触发下载。

### 后台下载与退出
- 关闭窗口时若仍有未完成任务，应用会隐藏到**系统托盘**继续后台下载，全部任务完成后自动退出
- 托盘菜单可「显示主窗口」或「退出」；退出时自动清理核心进程，无残留

## 常见问题

### Q: 核心文件下载失败怎么办？
A: 检查网络连接，或手动从官网下载对应版本的核心文件到 `resources` 目录。

### Q: 哈希验证失败如何处理？
A: 可能是文件损坏，请删除 `resources` 目录下的核心文件，重新下载。

### Q: 如何修改下载路径？
A: 在「设置」页的下载设置中修改下载目录，或直接编辑配置文件。

### Q: 支持哪些视频格式？
A: 支持B站所有公开的视频格式，包括MP4、FLV等；另支持纯音频 `mp3` 下载（可选单声道/双声道）。

### Q: 如何查看详细日志？
A: 日志文件保存在 `logs` 目录下，按日期分割。

## 技术架构

### 前端技术
- **PySide6 (Qt)**: Python 官方推荐的 Qt 绑定，原生桌面界面
- **QSS**: Qt 样式表，统一的设计规范（品牌色、卡片、徽章）
- **异步刷新**: QTimer 定时轮询 + Qt 信号跨线程通信

### 后端技术
- **Python 3.9+**: 主要编程语言
- **异步编程**: asyncio 后台线程桥，下载调度与 UI 事件循环共存
- **模块化设计**: 清晰的代码结构
- **错误处理**: 完善的异常处理机制

### 核心组件
- **JiJiDownCore**: B站视频下载核心
- **FFmpeg**: 音视频处理工具
- **Requests**: HTTP请求库
- **Loguru**: 日志记录工具

## 开发指南

### 环境设置
```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# 安装开发依赖
pip install -r requirements.txt
```

### 代码规范
- 遵循PEP 8代码风格
- 使用类型注解
- 模块化设计
- 完善的文档注释

### 测试运行
```bash
# 运行主程序
python main.py

# 调试模式
python -m pdb main.py
```

## 贡献指南

我们欢迎各种形式的贡献！

### 报告问题
- 使用GitHub Issues报告bug
- 提供详细的错误信息和复现步骤
- 包含系统环境和版本信息

### 提交代码
1. Fork项目
2. 创建功能分支
3. 提交更改
4. 推送到分支
5. 创建Pull Request

### 代码要求
- 通过所有现有测试
- 添加适当的测试用例
- 更新相关文档
- 遵循代码风格规范

## 许可证

本项目采用MIT许可证。详见 [LICENSE](LICENSE) 文件。

## 免责声明

本项目仅供学习和研究使用，请遵守相关法律法规和B站用户协议。使用者应对自己的行为负责，作者不承担任何法律责任。

## 更新日志

### v2.0.0 (2026-10-15)
- ✅ 架构迁移：NiceGUI Web 界面 → PySide6 (Qt) 原生桌面应用
- ✅ 全新界面：侧边导航 + 页面栈，QSS 统一设计规范
- ✅ asyncio 后台线程桥：下载调度与 UI 事件循环共存
- ✅ 现代视觉：状态卡片、彩色状态徽章、圆角进度条、分组表单
- ✅ 名称统一：应用名称统一为 JiuDown，核心文件本地以 JiuDownCore 命名
- ✅ 明确 fork 关系：文档注明本项目 fork 自 JiJiDownForDesktop 并修改完善

### v1.0.0 (2024-11-12)
- ✅ 初始版本发布
- ✅ 跨平台核心文件管理
- ✅ SHA256哈希验证
- ✅ 现代化Web界面
- ✅ 异步下载支持
- ✅ 详细日志记录

## 联系方式

- **项目主页**: [GitHub Repository](https://github.com/Yjiutong/JiuDown)
- **问题反馈**: [GitHub Issues](https://github.com/Yjiutong/JiuDown/issues)
- **邮箱**: your-email@example.com

## 致谢

感谢以下开源项目的支持：
- [JiJiDownForDesktop](https://github.com/o5-null/JiJiDownForDesktop) - 上游原项目（本项目 fork 自 JiJiDownForDesktop 并修改完善）
- [PySide6 (Qt)](https://www.qt.io/qt-for-python) - 原生桌面应用框架
- [Requests](https://docs.python-requests.org/) - 人性化的HTTP库
- [Loguru](https://github.com/Delgan/loguru) - 简单易用的日志库

---

**注意**: 请遵守B站的相关规定，合理使用下载功能。
