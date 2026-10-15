# SHOUDown Desktop

SHOUDown 桌面版 - 基于Python的现代化B站视频下载工具

## 项目简介

SHOUDown Desktop 是一个基于 Python 开发的 B 站视频下载桌面应用，采用 PySide6（Qt）构建原生桌面界面，支持多平台运行，提供直观的操作体验。

本项目 **fork 自开源项目 [JiJiDownForDesktop](https://github.com/o5-null/JiJiDownForDesktop)（唧唧下载器桌面版）**，并在此基础上修改完善，包括界面重构、架构升级与功能增强。

## 项目来源

本项目 fork 自 [JiJiDownForDesktop](https://github.com/o5-null/JiJiDownForDesktop)（原项目：JiJiDown Desktop，唧唧下载器桌面版，作者 o5-null），并在其基础上修改完善：

- **核心组件**：沿用上游的 [JiJiDownCore](https://jj.紫灵.top/PC/ReWPF/core/) 作为 B 站视频下载核心（本地以 SHOUDownCore-* 命名保存）
- **界面重构**：由原始 NiceGUI Web 界面重构为 PySide6 (Qt) 原生桌面应用
- **架构升级**：新增 asyncio 后台线程桥、模块化页面结构、QSS 统一设计规范
- **功能完善**：多任务并发调度、断点续传、批量下载、状态监控、日志管理等

> 上游原项目：[o5-null/JiJiDownForDesktop](https://github.com/o5-null/JiJiDownForDesktop)。上游项目与核心组件均属第三方开源作品，本项目仅在其基础上修改完善，遵守上游项目的开源许可与使用条款。

## 功能特性

### 核心功能
- 🎯 **智能核心管理**：自动检测系统架构，下载对应版本的核心文件
- 🔒 **文件完整性验证**：通过SHA256哈希校验确保核心文件完整
- 📱 **跨平台支持**：支持Windows、macOS、Linux系统
- 🖥️ **原生桌面界面**：基于PySide6 (Qt) 的现代桌面应用界面
- ⚡ **异步下载**：支持大文件分块下载，实时显示下载进度

### 下载管理
- 🎬 **多任务下载**：支持同时下载多个视频任务
- 🚀 **智能限速**：可配置下载速度限制，避免网络拥堵
- 📊 **实时进度**：显示下载速度、剩余时间等详细信息
- 🔄 **断点续传**：支持下载中断后继续下载

### 系统特性
- 🔧 **灵活配置**：支持自定义下载目录、临时目录等配置
- 📝 **详细日志**：使用Loguru记录详细的运行日志
- 🛡️ **安全验证**：自动验证核心文件完整性，防止恶意篡改
- 🔄 **自动更新**：支持核心文件的自动检测和更新

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
git clone https://github.com/Yjiutong/SHOUDown.git
cd SHOUDown
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 运行应用
```bash
python app.py
```

启动后直接显示桌面应用主窗口。

## 项目结构

```
SHOUDown/
├── app.py                 # 主程序入口（PySide6）
├── main_window.py         # 主窗口（侧边导航 + 页面栈）
├── theme.py               # QSS 主题与配色常量
├── async_bridge.py        # asyncio 后台线程桥
├── pages/                 # 页面模块
│   ├── home_page.py       # 状态总览页
│   ├── download_page.py   # 视频下载页
│   ├── log_page.py        # 运行日志页
│   └── settings_page.py   # 设置页
├── legacy_nicegui/        # 旧版 NiceGUI Web 界面（存档）
├── config_manager.py      # 配置管理模块
├── core_manager.py        # 核心文件管理模块
├── download_manager.py    # 视频下载管理模块
├── log_manager.py         # 日志持久化模块
├── core_status.py         # 核心状态缓存模块
├── system_info.py         # 系统信息工具模块
├── requirements.txt       # Python依赖包列表
├── config/                # 配置文件目录
├── Download/              # 下载文件目录
├── TEMP/                  # 临时文件目录
├── logs/                  # 日志文件目录
├── resources/             # 核心文件目录
└── downloads/             # 下载缓存目录
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
- `home_page.py`：状态总览（核心运行、文件完整性、FFmpeg、系统环境）
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

### core_manager.py
核心文件管理模块，功能包括：
- 核心文件下载
- SHA256哈希验证
- 下载进度管理
- 文件完整性检查

### system_info.py
系统信息工具模块，提供：
- 系统架构检测
- 平台适配
- 路径管理
- 缓存机制

### legacy_nicegui/
旧版 NiceGUI Web 界面存档（router.py、ui_*.py 等），仅供历史参考，不再参与构建。

## 配置说明

### 配置文件位置
- **Windows**: `%APPDATA%\SHOUDown\config.yaml`
- **macOS**: `~/.config/SHOUDown/config.yaml`
- **Linux**: `~/.config/SHOUDown/config.yaml`

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
2. 选择下载质量和格式
3. 设置保存路径
4. 点击「添加下载」并查看实时进度

## 常见问题

### Q: 核心文件下载失败怎么办？
A: 检查网络连接，或手动从官网下载对应版本的核心文件到 `resources` 目录。

### Q: 哈希验证失败如何处理？
A: 可能是文件损坏，请删除 `resources` 目录下的核心文件，重新下载。

### Q: 如何修改下载路径？
A: 在「设置」页的下载设置中修改下载目录，或直接编辑配置文件。

### Q: 支持哪些视频格式？
A: 支持B站所有公开的视频格式，包括MP4、FLV等。

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
- ✅ 名称统一：应用名称统一为 SHOUDown，核心文件本地以 SHOUDownCore 命名
- ✅ 明确 fork 关系：文档注明本项目 fork 自 JiJiDownForDesktop 并修改完善

### v1.0.0 (2024-11-12)
- ✅ 初始版本发布
- ✅ 跨平台核心文件管理
- ✅ SHA256哈希验证
- ✅ 现代化Web界面
- ✅ 异步下载支持
- ✅ 详细日志记录

## 联系方式

- **项目主页**: [GitHub Repository](https://github.com/Yjiutong/SHOUDown)
- **问题反馈**: [GitHub Issues](https://github.com/Yjiutong/SHOUDown/issues)
- **邮箱**: your-email@example.com

## 致谢

感谢以下开源项目的支持：
- [JiJiDownForDesktop](https://github.com/o5-null/JiJiDownForDesktop) - 上游原项目（本项目 fork 自 JiJiDownForDesktop 并修改完善）
- [PySide6 (Qt)](https://www.qt.io/qt-for-python) - 原生桌面应用框架
- [Requests](https://docs.python-requests.org/) - 人性化的HTTP库
- [Loguru](https://github.com/Delgan/loguru) - 简单易用的日志库

---

**注意**: 请遵守B站的相关规定，合理使用下载功能。
