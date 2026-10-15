"""
SHOUDown Desktop - 主程序入口（PySide6 桌面应用）

负责配置初始化、日志配置、asyncio 后台桥启动、核心进程拉起与主窗口展示

本项目 fork 自开源项目 JiJiDownForDesktop（https://github.com/o5-null/JiJiDownForDesktop），
在此基础上修改完善：界面重构为 PySide6 原生桌面应用，并新增 asyncio 后台线程桥与模块化页面结构。
"""

import pathlib
import sys

from loguru import logger


def configure_logger() -> None:
    """配置 loguru 日志：控制台 + 按天分割的文件日志"""
    logger.remove()
    # windowed 打包模式下 sys.stderr 为 None（无控制台），需保护
    if sys.stderr is not None:
        logger.add(sys.stderr, colorize=True, level="INFO")
    logger.add(
        "logs/SHOUDown_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
        level="DEBUG",
    )


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

    config_manager.initialize()
    system_info.initialize()


def main() -> None:
    """主程序入口"""
    configure_logger()
    logger.info("应用启动，开始初始化...")

    initialize_config()

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
    app.setApplicationName("SHOUDown Desktop")
    app.setStyle("Fusion")

    # 统一浅色 palette：防止深色系统主题下无背景 QWidget 默认呈黑色
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#f5f7fa"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#0f172a"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#0f172a"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#0f172a"))
    app.setPalette(pal)

    from main_window import MainWindow
    window = MainWindow()
    window.show()

    exit_code = app.exec()
    async_bridge.stop()
    logger.info(f"应用退出，退出码: {exit_code}")
    sys.exit(exit_code)


if __name__ in {"__main__", "__mp_main__"}:
    main()
