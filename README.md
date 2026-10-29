# JiuDown（玖号下载器）

JiuDown 桌面版（玖号下载器） - 自研双引擎（原生 B 站 + yt-dlp）的全站视频下载工具

## 项目简介

JiuDown（玖号下载器）是一个基于 Python 开发的全功能视频下载桌面应用，使用自研的 **JiuDown 引擎**（三后端架构）：B 站走原生链路（接口直连 + DASH 分片 + FFmpeg 合并，由本项目自己维护），抖音图文走原生图集链路（yt-dlp 不认这条形态），其余 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 支持的 1700+ 站点（YouTube、抖音视频、Vimeo、X 等）由通用后端处理，任一后端失败会自动降级到另一个。界面采用 PySide6（Qt）构建，提供与 Apple HIG 一致的原生桌面体验。

本项目 **fork 自开源项目 [JiJiDownForDesktop](https://github.com/o5-null/JiJiDownForDesktop)（唧唧下载器桌面版）**，并在此基础上修改完善，包括界面重构、架构升级与功能增强。

## 项目来源

本项目 fork 自 [JiJiDownForDesktop](https://github.com/o5-null/JiJiDownForDesktop)（原项目：JiJiDown Desktop，唧唧下载器桌面版，作者 o5-null），并在其基础上修改完善：

- **下载引擎**：自研 **JiuDown 引擎**（`jiudown_engine.py`）——B 站走原生链路（原核心逻辑重写为进程内 Python 实现，清晰度映射/风控 Cookie/分片下载全部自己维护），抖音图文走原生图集链路（`douyin_engine.py`），其他站点走 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 通用后端，多后端自动降级
- **界面重构**：由原始 NiceGUI Web 界面重构为 PySide6 (Qt) 原生桌面应用
- **架构升级**：新增 asyncio 后台线程桥、模块化页面结构、QSS 统一设计规范
- **功能完善**：多任务并发调度、断点续传、批量下载、状态监控、日志管理等

> 上游原项目：[o5-null/JiJiDownForDesktop](https://github.com/o5-null/JiJiDownForDesktop)。上游项目与核心组件均属第三方开源作品，本项目仅在其基础上修改完善，遵守上游项目的开源许可与使用条款。

## 功能特性

### 核心功能
- 🌐 **三引擎全站支持**：B 站与抖音图文走自研原生链路（解析快、字段可控），YouTube/抖音视频/Vimeo/X 等 1700+ 站点走 yt-dlp 通用后端
- 🔀 **自动降级**：原生链路失败时自动切到 yt-dlp，反之亦然；后端主动「不认领」某形态时直接让路，不会把内部原因报给用户
- 🎚️ **按视频实际提供的清晰度选档**：链接卡片解析出该视频真实存在的档位再让人选（老片没有 1080P 就不出现 1080P，B 站 1080P 高码率 / 4K / 60帧 这类档也能选到），mp4 / flv / mp3 / wav 四种输出
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
- 🔄 **自动更新**：FFmpeg 缺失时先看系统 PATH 有没有能用的，有就直接用、不再下载；没有才补精简版。yt-dlp 引擎一键增量升级

## 系统要求

### 操作系统
- **Windows 10 / 11（x64）** —— 发布包（Setup / Portable）只提供 64 位版本
- 源码运行：Windows 8.1+（下限来自内嵌的 Python 3.12），macOS / Linux 需自行准备
  Python 3.9+ 与 PySide6、yt-dlp、FFmpeg（仓库只随附 Windows 运行时组件）

> 精简版 FFmpeg 依赖系统 UCRT（`api-ms-win-crt-*`）：Windows 10 起自带，
> Windows 8.1 及更早需要安装 [KB2999226](https://support.microsoft.com/kb/2999226)。

### Python环境
- **Python** 3.9+
- **pip** 最新版本

### 硬件要求
- **内存**: 最低 2GB，推荐 4GB+
- **存储**: 至少 500MB 可用空间
- **网络**: 稳定的互联网连接

## 安装指南

### 0. 直接下载发布包（普通用户推荐）

Release 上提供两个**内容完全一致**、只是形态不同的包（由 `tools/build_release.py` 构建）：

| 产物 | 大小 | 适合谁 | 说明 |
|---|---|---|---|
| `JiuDown-Portable-<版本>.zip` | 约 110MB | 想解压就用、放 U 盘随身携带 | 解压到任意目录 → 双击 `启动.vbs`。配置/下载/日志全在该目录里，整个目录拷走即迁移，删目录即卸载 |
| `JiuDown-Setup-<版本>.exe` | 约 74MB | 想正规安装、要有开始菜单和卸载项 | 装到 `Program Files`，开始菜单/桌面快捷方式、控制面板卸载项齐全 |

两者都自带完整的离线运行环境（Python 3.12 + PySide6 + yt-dlp + 精简版 FFmpeg），
**装完断网也能用**。

> 两种形态下"用户数据放哪"是不同的，代码会自动判断：
> - **便携版**（程序目录可写）→ 配置/下载/日志/临时文件都写在程序目录里
> - **安装版**（Program Files 只读）→ 配置、日志、临时文件落到 `%LOCALAPPDATA%\JiuDown`，
>   下载默认进系统「下载」文件夹
>
> 判断逻辑见 `system_info.get_install_mode()`。

### 1. 克隆项目

```bash
git clone https://github.com/Yjiutong/JiuDown.git
cd JiuDown
```

仓库随附全部必需依赖的组件包（`build_components/`，约 103MB，单包最大 32.5MB），
克隆下来就能离线跑起来；只有「更新引擎」「升级完整版 FFmpeg」这两个显式操作才需要联网。
克隆到任意目录都可以，**没有硬编码路径**。

### 2. 选择一种启动方式

**方式 A：普通用户（无需安装 Python，推荐）**

1. 双击 `首次安装.bat` —— 把仓库内 `build_components\` 的组件包解压到 `runtime\`
   （离线完成，含 Python 3.12 / PySide6 / yt-dlp / FFmpeg 精简版）
2. 双击 `启动.vbs` —— 静默启动，全程无控制台窗口

**方式 B：开发者（本机已有 Python 3.9+）**

```bash
pip install -r requirements.txt
python app.py
```

### 3. 首次运行会自动完成的事

| 缺失项 | 自动处理 | 来源 |
|---|---|---|
| `runtime/` | 按组件清单把仓库内 `build_components/` 的组件包解压到 `runtime\`（**离线即可**） | 本仓库（随代码分发） |
| 运行时里的 `yt-dlp` 后端 | 随 `engine.zip` 组件一起下发，**不走 PyPI** | 同上 |
| `ffmpeg.exe` | 先认程序自带；自带缺失且系统 PATH 上有能力齐备的 ffmpeg 时**直接采用、不下载**；否则从仓库内 `ffmpeg-lite.zip` 取出精简版（5.3MB，覆盖全部下载场景） | 本机 / 同上 |
| `config/`、`Download/`、`logs/` | 启动时按程序所在目录自动创建 | 本地 |

> **克隆即用，不依赖 Release**：所有必需依赖都作为组件包随仓库分发（合计约 103MB，
> 单包最大 32.5MB，均低于 100MB）。装好 runtime 后断网也能正常启动；
> GitHub Release 上没有这些资产也不影响使用（唯一来源就是仓库里那份）。
> 需要联网的只有两处，且都是显式操作：设置页「更新引擎」（先查 Release 有没有新版，
> 查不到就恢复/保留仓库内置版本，结果会明确提示，不会假装更新成功）、
> 「升级完整版 FFmpeg」（BtbN 公开构建，与本项目 Release 无关）。
> **不会**擅自从 PyPI 安装任何东西。

所有路径都相对程序所在目录解析，移动或改名项目文件夹不会影响使用。

## 依赖组件与增量更新

运行时不再是单个 339MB 的整包，而是拆成若干 **小于 100MB 的组件**，
按功能与更新频率切分（打包工具：`tools/build_components.py`）：

| 组件 | 内容 | 压缩后 | 更新频率 |
|---|---|---|---|
| `core` | Python 3.12 解释器 + 标准库 | 12.6 MB | 几乎不变 |
| `pyside-1/2/3` | PySide6（已剥离 WebEngine / Pdf / Quick / Qml 等未使用模块，省 420MB） | 30.8 / 31.0 / 17.5 MB | 随界面依赖升级 |
| `engine` | yt-dlp 与其依赖（Cryptodome / mutagen / websockets / brotli） | **5.2 MB** | 站点改版后 |
| `app` | requests / loguru / pyyaml / psutil 等运行依赖 | 3.3 MB | 很少变 |
| `ffmpeg-lite` | 从 FFmpeg 源码裁剪编译的精简版（构建脚本 `tools/build_ffmpeg_lite.sh`） | 2.3 MB | 几乎不变 |

合计约 **103MB**（原整包 339MB），**全部随仓库分发**：`build_components/` 目录已入库
（`.gitignore` 为它开了 `*.zip` 例外），克隆下来就有，断网也能完成首次安装。

`ffmpeg.exe` 不进 runtime 组件，由 `ffmpeg_manager` 独立管理。查找顺序是
**用户数据目录升级副本 → `runtime/` → 内置 `resources/` → 系统 PATH**：前三项都在程序目录内
（保证整个文件夹可移植），最后一项只是兜底 —— 机器上本来就有 ffmpeg 时就不再下载补齐。
采用 PATH 上的那份前会实测它具备 mp3/wav 编码、flv 重封装与 `aresample` 滤波器，
避免 Windows「应用执行别名」那种 0 字节占位 exe 或过老的构建被误当可用。
需要视频重编码等能力时可在设置页显式升级到完整版（约 161MB）。

**带来的实际收益**

- 首次安装：**无需下载**，直接从本地组件包解压（100MB 的解压比 100MB 的下载快得多）
- 更新下载引擎：只换 `engine.zip`（5.2MB），设置页点「更新引擎」即完成，重启生效
- 某个组件损坏/缺失：只补那一个组，不再整包重下

**打包 / 更新组件**

```bash
python tools/build_components.py            # 生成 build_components/*.zip + manifest.json
python tools/build_components.py --manifest-only   # 只改清单，不重打包
python tools/build_components.py --keep-all        # 保留 PySide6 全部模块（不剥离）
```

生成的包**直接提交进仓库**即可生效（组件 sha256 写在 `manifest.json`，运行端会校验）。
Release 是**可选的更新通道**：想让已装好的老用户增量拿到新引擎，可额外把
`build_components/` 里的 zip 与 `manifest.json` 传到 Release 的 `runtime` 标签；
不传也没关系——本地包不存在或校验不过时会给出明确提示，不会静默失败。
客户端拉不到 `manifest.json` 时会自动回退到整包 `runtime.zip`（兼容旧发布）。

## 构建发布包

```bash
runtime\python\python.exe tools/build_release.py            # zip + setup 都构建
runtime\python\python.exe tools/build_release.py --only zip   # 只打便携版
runtime\python\python.exe tools/build_release.py --version 1.1.0
```

产物（不入库，`.gitignore` 已忽略 `dist/`）：

| 文件 | 说明 |
|---|---|
| `JiuDown-Portable-<版本>.zip` | 约 110MB，解压即用 |
| `JiuDown-Setup-<版本>.exe` | 约 74MB，Inno Setup 安装程序 |
| `SHA256SUMS.txt` | 两个产物的校验值 |

两个包装的内容完全一致：源码 + `runtime\` + `resources\`（含 FFmpeg）+ `build_components\`
里的三个离线修复包（manifest / engine / ffmpeg-lite）。

**setup 版需要 Inno Setup 编译器**（只用来编译安装脚本，不随仓库分发）：

```bash
# 官网 https://jrsoftware.org/isdl.php ；便携解压方式（不写注册表、不装进系统）
innosetup-7.1.0-x64.exe /VERYSILENT /CURRENTUSER /PORTABLE=1 /DIR="<仓库>\tools\_vendor\innosetup"
```

脚本会自动找 `tools\_vendor\innosetup\ISCC.exe`，找不到会打印下载地址；
已有 Inno Setup 时用 `--iscc <路径>` 指定。构建前会自检 runtime / FFmpeg / 图标是否齐全，
并自动用 `resources\` 重建 `ffmpeg-lite.zip`（含 FFmpeg 依赖的 MinGW 运行库）。

> `tools/build_release.py` 的 precheck 会校验包内不含开发期文件（TEMP / tools / .git /
> __pycache__），`tools/verify/verify_release.py` 会解析 PE 导入表确认 FFmpeg 的依赖 DLL 都随包分发。

### 回归验证脚本（`tools/verify/`）

发布前逐个跑一遍，每个脚本自带断言与 `RESULT: PASS/FAIL`：

| 脚本 | 覆盖点 |
|---|---|
| `verify_release.py` | 包内不混开发期文件、FFmpeg 不依赖 MinGW 运行库、快捷方式指向与工作目录 |
| `verify_components.py` / `verify_stripped_runtime.py` | 组件包与 manifest 一致、剥离后的 runtime 仍能起窗口 |
| `verify_runtime.py` / `check_release_zip.py` | 安装脚本不删仓库内组件包、Release 资产 zip 可读 |
| `verify_engine.py` / `verify_ytdlp.py` / `verify_wav.py` | 双后端路由与降级、进度回调、纯音频只取音频流 |
| `verify_ffmpeg.py` / `verify_gating.py` | FFmpeg 能力探测与 UI 门控（含系统 PATH 侦测） |
| `verify_url_input.py` | 粘贴链接的健壮性（零宽字符/BOM/标题前缀/分享尾巴）与出错必须可见 |
| `verify_douyin_note.py` | 抖音图文：形态识别与路由顺序、无水印原图挑选与逐张候选重试、多图落盘、卡片张数呈现 |
| `verify_install_mode.py` / `check_installed_mode.py` | 便携 / 安装两种形态的数据目录推导与恢复 |

这些脚本一律**由自身位置推导仓库根**，不写死任何绝对路径，可从任意目录调用。

### 单文件 exe（可选，不是发布物）

`JiuDownDesktop.spec` 另外能出一个把 PySide6 + yt-dlp 收进去的单文件 exe（约 104MB）：

```bash
runtime\python\python.exe -m pip install pyinstaller
runtime\python\python.exe -m PyInstaller --noconfirm JiuDownDesktop.spec   # 产物在 dist\
```

必须用 `runtime\python\python.exe` 来打（它才是装着 PySide6/yt-dlp 的那个解释器；
系统 Python 里没有这些包）。**打完记得把 pyinstaller 卸掉再跑 `build_components.py`**，
否则 `core.zip` 会把构建工具一起装给用户。

这个 exe 与上面两个包是两条独立路线：它自带解释器，所以启动时会跳过内嵌 `runtime\`
的自检与补齐（`app.py` 的 frozen 分支），不会去下载 339MB 的 runtime.zip。
它的定位是「开发期快速起一个二进制入口」，给用户的仍然是 Portable zip 与 Setup。

## 项目结构

```
JiuDown/                       （仓库只含源码，二进制依赖首跑自动拉取）
├── app.py                     # 主程序入口（配置初始化 + 窗口 + 后台自检）
├── main_window.py             # 主窗口（侧边导航 + 页面栈 + 托盘）
├── theme.py                   # 主题令牌与 QSS（Apple HIG，双主题）
├── async_bridge.py            # asyncio 后台线程桥（下载调度）
├── jiudown_engine.py          # JiuDown 引擎：多后端路由门面 + 原生 B 站链路
├── douyin_engine.py           # 原生抖音图文链路（图集 → 无水印原图文件夹）
├── ytdlp_engine.py            # yt-dlp 通用后端（解析 / 下载 / 预览直链）
├── download_manager.py        # 下载任务队列与并发调度
├── ffmpeg_manager.py          # FFmpeg 探测 / 下载 / 能力缓存
├── runtime_manager.py         # 离线运行时自举（runtime.zip）
├── config_manager.py          # 配置管理（CONFIG_SCHEMA 统一读写）
├── log_manager.py             # 日志持久化
├── system_info.py             # 系统信息与默认路径
├── pages/
│   ├── home_page.py           # 状态总览（引擎 / 站点 / FFmpeg / 系统）
│   ├── download_page.py       # 下载页（链接卡片 + 任务卡 + 右键选档）
│   ├── preview_panel.py       # 内嵌预览播放器（本地流代理）
│   ├── hover_preview.py       # 悬停低清小窗
│   ├── log_page.py            # 运行日志 + 下载记录
│   └── settings_page.py       # 设置页（基本/下载/网络/用户/高级）
├── runtime_components.py      # 运行时组件划分（打包端与运行端共用）
├── tools/
│   ├── build_components.py    # 打包运行时组件（生成 zip + manifest.json）
│   ├── install_runtime.ps1    # 首次安装：按组件拉取，失败回退整包
│   └── verify/                # 发布前回归验证脚本（自带断言，仓库相对锚定）
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
下载引擎层。`jiudown_engine` 是统一门面（多后端路由 + 原生 B 站链路），`douyin_engine` 是原生抖音图文链路（yt-dlp 不认 `/note/` 形态），
`ytdlp_engine` 是通用后端（1700+ 站点）与各类共享工具（URL 规范化、画质→格式映射、
FFmpeg 转码、错误中文化）。

### system_info.py
系统信息工具模块，提供：
- 系统架构检测
- 平台适配
- 路径管理
- 缓存机制

### ffmpeg_manager.py / runtime_manager.py
外部依赖自举。`ffmpeg_manager` 负责 FFmpeg 的能力探测（决定哪些格式/声道可用）、
查找顺序（程序自带 → 系统 PATH 兜底，PATH 上有能用的就不下载）、精简版自动补齐
（优先用仓库内 `ffmpeg-lite.zip`）、完整版显式升级与能力缓存；
`runtime_manager` 负责 `runtime\` 的完整性校验，以及用仓库内 `build_components\`
的组件包离线补齐（本地包不可用时才回退 Release）。

## 配置说明

### 配置文件位置

程序**不写死任何绝对路径**：所有目录以程序自身所在目录为基准解析，配置里落在程序目录
以内的路径存成 `${APP_ROOT}/...`（如 `${APP_ROOT}/TEMP`），因此文件夹可以随意移动、改名、
换盘符，甚至拷到 U 盘上直接跑。用户显式选到程序目录之外的下载目录仍按绝对路径保存
（那是真实意图，不该被重锚定）；万一配置里留着已经失效的旧绝对路径（换了机器、拔过 U 盘），
启动时会自动回退到当前默认值并改写配置，不会拖到下载中途才炸。
数据落在哪，取决于运行形态（自动判断，见 `system_info.get_install_mode()`）：

**便携模式**（程序目录可写 —— 解压即用 / 源码运行）

- 配置: `<程序目录>/config/config.yaml`
- 日志: `<程序目录>/logs/`
- 临时文件: `<程序目录>/TEMP/`
- 下载目录: `<程序目录>/Download/`
- FFmpeg: `<程序目录>/resources/ffmpeg.exe`（随发布包分发，缺失时从组件包离线补齐）

**安装模式**（程序目录只读 —— 装到 Program Files 的 setup 版）

- 配置: `%LOCALAPPDATA%/JiuDown/config/config.yaml`
- 日志: `%LOCALAPPDATA%/JiuDown/logs/`
- 临时文件: `%LOCALAPPDATA%/JiuDown/TEMP/`
- 下载目录: `~/Downloads/JiuDown/`（设置页可改）
- FFmpeg: 程序目录只读，升级/下载的副本写到 `%LOCALAPPDATA%/JiuDown/resources/`

两种形态下都在程序目录里的：
- **离线运行时**: `<程序目录>/runtime/`
- **图标**: `<程序目录>/resources/app.ico`

> 旧版本写入 `%APPDATA%\JiuDown` / `%APPDATA%\SHOUDown` 的配置会在**便携模式**首次启动时
> 迁移到程序目录并清理旧目录；安装模式不做这个迁移（数据本就在用户目录下）。

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
1. 在应用界面输入视频链接（支持批量，每行一个），回车生成**链接卡片**
2. 卡片后台解析出该视频的标题与实际提供的清晰度档位（不阻塞界面，可右键「重新解析档位」重试）：
   - 卡片主文字是标题，原链接在右键「查看链接」里看与复制
   - 右键「清晰度」只列**当前真正取得到**的档位：老片没有 1080P 就不出现 1080P，接口声明了
     但账号拿不到的（未登录时的高码率/4K）同样不出现，只在卡片概览里报一句藏了几档；
     默认档取设置里的默认值不超过视频最高档的那一档
   - 选中某档后按档精确选流，两后端都给不到时明确报错，不会静默降成低画质
   - 纯音频（`mp3` / `wav`）时清晰度位切换为声道（单声道/双声道，默认双声道）
3. 设置保存路径
4. 点击「开始」并查看实时进度

> 说明：仓库自带的是从 FFmpeg 源码裁剪编译的 **精简版**（5.3MB），已覆盖 mp4 / flv / mp3 / wav
> 与单声道等全部下载场景，由 `build_components/ffmpeg-lite.zip` 就地解压获得（离线）。
> 需要视频重编码、罕见容器等能力时，可在设置页或首页点「升级完整版」（约 161MB，BtbN 构建）。

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

### v1.1.0 (2026-10-29)
- ✅ **抖音图文（图集）可下载**：新增 `douyin` 原生后端。yt-dlp 的 `DouyinIE` 只认
  `/video/`，抖音图文形态（`/note/`）一律被判 `Unsupported URL`，此前该类链接全量失败。
  图文也没有视频流可下（服务端把图集渲染成 mp4 的 `/playwm/` 已 404、去水印的 `/play/`
  返回空体），所以产物是**按「标题 [作品号]」归档的无水印原图文件夹**。取数走两条路径并按张
  合并候选：`_ROUTER_DATA`（移动端 UA + 匿名 `ttwid`，给 jpeg 与每图多个镜像）与 `ld+json`
  （Googlebot UA，冷启动一次请求、完全不依赖 Cookie）——实测两条路径张数与分辨率一致
  （55/55、262/262，均 1080x1442），任一条被改版打掉都不至于全瞎。`download_url_list`
  是叠了作者水印的另一套地址，始终排在最后才用
- ✅ **挡住风控占位图**：批量取图时抖音会成批返回 0 字节，或拿一张约 10KB 的 GIF 顶替所请求
  的 jpeg/webp，两者都是 HTTP 200——按 URL 命名就会产出打不开的"图片"。现在按魔数校验内容
  格式，不符就换候选、候选跑完再退避重跑一轮，落盘扩展名也跟着真实字节定
- ✅ **只认设置里明确填写的代理**：图文请求不再继承系统注册表代理。机器上挂着一个已失效的
  系统代理时，继承它会直接 `unable to connect to proxy`，导致整批图文莫名全失败
- 🔧 短链 `v.douyin.com` 仍先交 yt-dlp，失败后才解析一次判定形态，所以抖音视频的耗时与
  提示和改动前完全一致；图文卡片对目录产物改走「打开所在目录」，不再喂给媒体播放器
- ✅ **按视频实际提供的档位选清晰度**：回车生成链接卡片，后台解析出标题与该视频真实存在的
  清晰度档位再供选择；卡片主文字改为标题，原链接在右键「查看链接」里查看与复制
- ✅ **高码率档可选**：B 站按 qn 精确选流（1080P 与 1080P 高码率不再混为一谈），
  yt-dlp 侧按「同分辨率取最高码率」枚举，档位名新增 4K / 2K / 60帧 / HDR
- ✅ **取不到的档位不再出现**：接口声明了但当前账号拿不到的（B 站未登录时的高码率/4K）
  直接从选择器里隐藏，只在卡片概览报一句"另有 K 档当前账号取不到"，不给人点不动的选项
- ✅ **不再静默降档**：选中某档后两后端都给不到就明确报错；默认档位作为上限自动钳制
- ✅ **彻底可移植**：配置里落在程序目录内的路径统一存 `${APP_ROOT}/...`，程序根目录只有一处
  推导，默认值不再按当前工作目录解析，陈旧绝对路径启动时自愈
- ✅ **FFmpeg 侦测系统 PATH**：机器上已有能用的 ffmpeg 时直接采用，不再自动下载补齐
- 🔧 修复：`build_components.py` 在中文控制台打印对勾导致构建成功却报失败；设置页 RESTful
  端口上限低于固定值 64001，保存一次即写坏配置；`save_config` 不清缓存导致改目录需重启
- 🔧 修复：粘贴**带超链接的标题**（B 站视频页标题、网页列表项这类 `<a href="URL">标题</a>`）
  时链接被 `QTextEdit` 丢弃 —— 用户粘的是链接，进输入框却只剩标题，回车自然不出卡片。
  现在粘贴优先取回链接本身，多个链接一行一个
- 🔧 修复：粘贴链接里的零宽字符/BOM/标题前缀/「来自 微博网页版」尾巴会让回车**静默不生成
  卡片**（`pythonw` 无控制台，槽内异常也一并静默）；现在从整行中提取 URL，支持只有 BV/av 号
  的分享文本，并把无法识别的内容与异常都显示在提示语上
- 🧹 整理：验证脚本从 `TEMP/` 迁到 `tools/verify/` 并纳入版本管理（其中 11 个原本硬编码了
  已失效的旧盘符），移除 `.trae/` 编辑器目录

### v1.0.0 (2026-10-15)
- ✅ 架构迁移：NiceGUI Web 界面 → PySide6 (Qt) 原生桌面应用
- ✅ 全新界面：侧边导航 + 页面栈，QSS 统一设计规范
- ✅ asyncio 后台线程桥：下载调度与 UI 事件循环共存
- ✅ 现代视觉：状态卡片、彩色状态徽章、圆角进度条、分组表单
- ✅ 名称统一：应用名称统一为 JiuDown，核心文件本地以 JiuDownCore 命名
- ✅ 明确 fork 关系：文档注明本项目 fork 自 JiJiDownForDesktop 并修改完善

### 上游 JiJiDownForDesktop（2024-11-12）
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
