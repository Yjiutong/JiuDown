"""
JiuDown Desktop - 主程序入口（PySide6 桌面应用）

负责配置初始化、日志配置、asyncio 后台桥启动与主窗口展示（下载由 yt-dlp 引擎在进程内完成）

本项目 fork 自开源项目 JiJiDownForDesktop（https://github.com/o5-null/JiJiDownForDesktop），
在此基础上修改完善：界面重构为 PySide6 原生桌面应用，并新增 asyncio 后台线程桥与模块化页面结构。
"""

import os
import pathlib
import shutil
import sys

# 嵌入式 Python 需要手动添加应用根目录到 sys.path
_app_dir = pathlib.Path(__file__).resolve().parent
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

from loguru import logger


def configure_logger() -> None:
    """配置 loguru 日志：仅文件日志（无控制台输出，避免窗口闪现）

    日志路径取自 system_info 的绝对值：安装模式下程序目录只读，
    日志会落在 %LOCALAPPDATA%\\JiuDown\\logs，且不能依赖当前工作目录。
    """
    from system_info import system_info

    logger.remove()
    logs_dir = pathlib.Path(system_info.get_default_paths()['logs_dir'])
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    # 完全移除控制台输出（windowed 模式下 stderr 会导致窗口闪现）
    logger.add(
        str(logs_dir / "JiuDown_{time:YYYY-MM-DD}.log"),
        rotation="1 day",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        encoding="utf-8",
    )


def _migrate_old_appdata_config() -> None:
    """便携模式迁移：把旧版本写入 %APPDATA% 的配置迁移到程序目录 config 下，
    迁移完成后清理旧的 AppData 配置目录（AppData 不保留数据）。
    兼容迁移源：当前品牌 JiuDown 与历史品牌 SHOUDown（旧版升级用户）。"""
    try:
        from config_manager import config_manager
        from pathlib import Path
        new_file = config_manager.get_config_file_path()
        for brand in ("JiuDown", "SHOUDown"):
            old_dir = (
                Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
                / brand
            )
            old_file = old_dir / 'config.yaml'
            if not old_file.exists():
                continue
            if not new_file.exists():
                new_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old_file, new_file)
                logger.info(f"已迁移旧配置: {old_file} -> {new_file}")
            else:
                logger.info(f"便携配置已存在，跳过迁移: {new_file}")
            try:
                # 解除只读属性后删除旧目录
                for root, dirs, files in os.walk(old_dir, topdown=False):
                    for name in files:
                        try:
                            os.chmod(os.path.join(root, name), 0o777)
                        except OSError:
                            pass
                shutil.rmtree(old_dir)
                logger.info(f"已清理旧配置目录: {old_dir}")
            except Exception as e:
                logger.warning(f"清理旧配置目录失败: {old_dir} ({e})")
            break
    except Exception as e:
        logger.warning(f"旧配置迁移失败（忽略）: {e}")


def initialize_config() -> None:
    """初始化配置与必要的文件夹（含旧版 AppData 配置迁移）"""
    from config_manager import config_manager
    from system_info import system_info

    default_paths = system_info.get_default_paths()
    folders = [
        default_paths["temp_dir"],
        default_paths["download_dir"],
        default_paths["logs_dir"],
        default_paths["resources_dir"],
    ]
    for folder in folders:
        try:
            pathlib.Path(folder).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            # 安装模式下程序目录只读，resources_dir 由安装器创建，此处失败可忽略
            logger.warning(f"无法创建目录 {folder}: {e}")

    # 迁移旧版 AppData 配置到便携目录（首次运行）。
    # 安装模式下数据本就在 %LOCALAPPDATA%，不存在"迁回程序目录"这回事，直接跳过。
    from system_info import system_info

    if system_info.get_install_mode() == 'portable':
        _migrate_old_appdata_config()

    config_manager.initialize()
    system_info.initialize()


def _bootstrap_after_ui(window) -> None:
    """窗口已可见后的重活（全部后台线程/非阻塞，避免拖慢首屏）"""
    import threading

    # 1) runtime 环境自检（会 spawn 一次内嵌 python，且缺失时下载，耗时不固定）
    def _runtime_check() -> None:
        try:
            if getattr(sys, "frozen", False):
                # 打包版自带解释器，PySide6/yt-dlp 也已收进 exe，
                # 再去拉 339MB 的 runtime.zip 纯属白费流量
                logger.info("打包形态：跳过内嵌 runtime 自检与补齐")
                return

            from runtime_manager import ensure_runtime, get_runtime_status
            status = get_runtime_status()
            logger.info(f"runtime 状态: complete={status['complete']}, python={status['python_version']}")
            if not status["complete"]:
                logger.info("runtime 环境不完整，开始自动下载...")
                if not ensure_runtime():
                    logger.error("runtime 下载失败，应用可能无法正常运行")
        except Exception as e:
            logger.error(f"runtime 自检失败: {e}")

    # 2) FFmpeg：能力探测（磁盘缓存命中时瞬时）+ 缺失时才补精简版
    def _ffmpeg_init() -> None:
        try:
            import ffmpeg_manager
            ffmpeg_manager.prepare()
            # 只在完全没有 ffmpeg 时补精简版（优先用仓库内的 ffmpeg-lite.zip）；
            # 不会自动拉 161MB 完整版——那是用户显式点「升级完整版」才做的事
            ffmpeg_manager.ensure_available()
        except Exception as e:
            logger.error(f"FFmpeg 初始化失败: {e}")

    # 3) 引擎后端自检：yt-dlp 随 engine 组件一起分发（仓库内 + 可选 Release），
    #    缺失说明运行时不完整 —— 重新用组件包补齐，绝不走 pip / PyPI
    def _engine_deps() -> None:
        try:
            import importlib

            import ytdlp_engine

            if ytdlp_engine.available():
                logger.info(f"yt-dlp 后端就绪: {ytdlp_engine.version()}")
                return

            from runtime_manager import ensure_runtime, has_engine_backend

            if has_engine_backend():
                # 目录在但当前解释器导入不到：多半是刚下载完，重启生效
                logger.info("运行时已包含 yt-dlp，当前进程未加载，重启应用后生效")
                return

            logger.warning("运行时缺少下载引擎，开始用组件包补齐…")
            if ensure_runtime():
                importlib.invalidate_caches()
                if ytdlp_engine.available():
                    logger.success(f"引擎已就绪: {ytdlp_engine.version()}")
                else:
                    logger.info("运行时已更新（含 yt-dlp），重启应用后生效")
            else:
                logger.error(
                    "运行时补齐失败：请双击「首次安装.bat」重试；"
                    "若 build_components\\ 不完整，请重新克隆或更新仓库"
                )
        except Exception as e:
            logger.error(f"引擎依赖自检失败: {e}")

    # asyncio 后台桥必须先就绪（下载调度依赖它），它本身只是起线程，代价极小
    from async_bridge import async_bridge, patch_download_manager
    async_bridge.start()
    patch_download_manager()

    # 说明：下载链路由 JiuDown 引擎承担（native B 站链路 + yt-dlp 通用后端，均在进程内），
    # 不再需要拉起旧版 B 站核心进程；此处只做 runtime / FFmpeg / 引擎依赖自检。
    for fn, name in ((_runtime_check, "runtime-check"),
                     (_ffmpeg_init, "ffmpeg-init"),
                     (_engine_deps, "engine-deps")):
        threading.Thread(target=fn, daemon=True, name=name).start()


def main() -> None:
    """主程序入口"""
    configure_logger()
    logger.info("应用启动，开始初始化...")

    initialize_config()

    # 创建 Qt 应用与主窗口（先出窗口，重活延后）
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from theme import load_mode, theme_manager

    app = QApplication(sys.argv)
    app.setApplicationName("JiuDown Desktop")
    app.setStyle("Fusion")

    # 应用主题：固定浅色（产品决策：不跟随系统、不提供切换，见 theme.py 说明）
    theme_manager.set_mode(load_mode(), persist=False)

    from main_window import MainWindow
    window = MainWindow()
    window.show()

    # 首帧绘制完成后再启动后台初始化（runtime 自检 / FFmpeg）
    QTimer.singleShot(0, lambda: _bootstrap_after_ui(window))

    exit_code = app.exec()
    async_bridge.stop()
    logger.info(f"应用退出，退出码: {exit_code}")
    sys.exit(exit_code)


if __name__ in {"__main__", "__mp_main__"}:
    main()
