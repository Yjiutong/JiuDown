"""
JiuDown Desktop - 主程序入口（PySide6 桌面应用）

负责配置初始化、日志配置、asyncio 后台桥启动、核心进程拉起与主窗口展示

本项目 fork 自开源项目 JiJiDownForDesktop（https://github.com/o5-null/JiJiDownForDesktop），
在此基础上修改完善：界面重构为 PySide6 原生桌面应用，并新增 asyncio 后台线程桥与模块化页面结构。
"""

import os
import pathlib
import shutil
import sys

from loguru import logger


def configure_logger() -> None:
    """配置 loguru 日志：控制台 + 按天分割的文件日志"""
    logger.remove()
    # windowed 打包模式下 sys.stderr 为 None（无控制台），需保护
    if sys.stderr is not None:
        logger.add(sys.stderr, colorize=True, level="INFO")
    logger.add(
        "logs/JiuDown_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
        level="DEBUG",
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
    """初始化配置与必要的文件夹"""
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
        pathlib.Path(folder).mkdir(parents=True, exist_ok=True)

    # 迁移旧版 AppData 配置到便携目录（首次运行）
    _migrate_old_appdata_config()

    config_manager.initialize()
    system_info.initialize()

    # 便携模式：核心硬编码路径重定向到应用目录（junction）
    from core_manager import core_manager
    core_manager.ensure_portable_core_dir()


def main() -> None:
    """主程序入口"""
    configure_logger()
    logger.info("应用启动，开始初始化...")

    initialize_config()

    # FFmpeg 缺失时后台自动拉取（完整版约 100MB，不阻塞启动；已存在则跳过）
    import ffmpeg_manager
    ffmpeg_manager.start_download()

    # 启动 asyncio 后台线程桥，并让 download_manager 的调度运行其上
    from async_bridge import async_bridge, patch_download_manager
    async_bridge.start()
    patch_download_manager()

    # 自动拉起核心进程
    from config_manager import config_manager
    from core_manager import core_manager
    core_manager.start_core(str(config_manager.get_config_file_path()))

    # 创建 Qt 应用与主窗口
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QColor, QPalette

    app = QApplication(sys.argv)
    app.setApplicationName("JiuDown Desktop")
    app.setStyle("Fusion")

    # 统一浅色 palette：防止深色系统主题下无背景 QWidget 默认呈黑色
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#f0f7f7"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#1a2423"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#1a2423"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#1a2423"))
    app.setPalette(pal)

    from main_window import MainWindow
    window = MainWindow()
    window.show()

    def _cleanup_on_exit():
        """退出时清理核心进程与孤儿进程，避免残留"""
        try:
            core_manager.stop_core()
        except Exception as e:
            logger.error(f"停止核心失败: {e}")
        try:
            core_manager.force_kill_all_core_processes(
                core_manager.get_core_filename()
            )
        except Exception as e:
            logger.error(f"清理核心孤儿进程失败: {e}")

    app.aboutToQuit.connect(_cleanup_on_exit)

    exit_code = app.exec()
    async_bridge.stop()
    logger.info(f"应用退出，退出码: {exit_code}")
    sys.exit(exit_code)


if __name__ in {"__main__", "__mp_main__"}:
    main()
