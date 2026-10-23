import platform
import struct
import socket
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger


# 用户数据目录名（安装模式下 %LOCALAPPDATA%\JiuDown）
APP_DIR_NAME = 'JiuDown'


# 各平台对应的官方核心文件名（官网下载源真实存在的文件）
CORE_PLATFORM_FILENAMES = {
    'windows-64': 'JiJiDownCore-win64.exe',
    'windows-32': 'JiJiDownCore-win32.exe',
    'darwin-arm64': 'JiJiDownCore-darwin-arm64',
    'darwin-amd64': 'JiJiDownCore-darwin-amd64',
    'linux-arm64': 'JiJiDownCore-linux-arm64',
    'linux-amd64': 'JiJiDownCore-linux-amd64',
}

# 本地核心文件名（JiuDown 品牌名，下载后保存为该名称）
CORE_LOCAL_FILENAMES = {
    'windows-64': 'JiuDownCore-win64.exe',
    'windows-32': 'JiuDownCore-win32.exe',
    'darwin-arm64': 'JiuDownCore-darwin-arm64',
    'darwin-amd64': 'JiuDownCore-darwin-amd64',
    'linux-arm64': 'JiuDownCore-linux-arm64',
    'linux-amd64': 'JiuDownCore-linux-amd64',
}


class SystemInfo:
    """系统信息工具类，提供统一的系统信息获取接口"""
    
    _instance = None
    _cache = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_system_info(self) -> Dict[str, Any]:
        """获取完整的系统信息"""
        system = platform.system()
        machine = platform.machine()
        is_64bit = struct.calcsize("P") * 8 == 64
        is_arm = 'arm' in machine.lower() or 'aarch64' in machine.lower()
        
        return {
            'system': system,
            'machine': machine,
            'is_64bit': is_64bit,
            'is_arm': is_arm,
            'architecture': '64位' if is_64bit else '32位',
            'processor_type': 'ARM' if is_arm else 'x86',
            'hostname': socket.gethostname(),
            'platform': platform.platform(),
            'processor': platform.processor(),
            'python_version': platform.python_version()
        }
    
    def _core_platform_key(self) -> str:
        """返回当前平台对应的核心文件平台标识"""
        system = platform.system().lower()
        machine = platform.machine().lower()
        
        is_64bit = struct.calcsize("P") * 8 == 64
        is_arm = 'arm' in machine or 'aarch64' in machine
        
        if system == 'windows':
            return 'windows-64' if is_64bit else 'windows-32'
        elif system == 'darwin':  # macOS
            return 'darwin-arm64' if is_arm else 'darwin-amd64'
        elif system == 'linux':
            return 'linux-arm64' if is_arm else 'linux-amd64'
        else:
            # 默认返回Windows 64位版本
            return 'windows-64'
    
    def get_core_filename(self) -> str:
        """根据操作系统和架构返回本地核心文件名（JiuDown 品牌）"""
        return CORE_LOCAL_FILENAMES[self._core_platform_key()]
    
    def get_official_core_filename(self) -> str:
        """返回官方核心文件名（官网下载源使用的真实文件名）"""
        return CORE_PLATFORM_FILENAMES[self._core_platform_key()]
    
    # ------------------------------------------------------------ 目录策略
    def _get_runtime_base_dir(self) -> Path:
        """程序运行目录（代码所在处，安装模式下通常为只读的 Program Files）"""
        if getattr(sys, 'frozen', False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    @staticmethod
    def _is_writable(path: Path) -> bool:
        """探测目录是否可写（装到 Program Files 时普通用户不可写）"""
        probe = path / '.jiudown_write_probe'
        try:
            probe.mkdir(exist_ok=True)
            marker = probe / 'probe.tmp'
            marker.write_text('1', encoding='utf-8')
            marker.unlink(missing_ok=True)
            probe.rmdir()
            return True
        except Exception:
            return False

    @staticmethod
    def _system_app_data_dir() -> Path:
        """系统级用户数据目录（安装模式下的兜底位置）"""
        system = platform.system()
        if system == 'Windows':
            root = os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local')
        elif system == 'Darwin':
            root = Path.home() / 'Library' / 'Application Support'
        else:
            root = os.environ.get('XDG_DATA_HOME') or (Path.home() / '.local' / 'share')
        return Path(root) / APP_DIR_NAME

    def get_install_mode(self) -> str:
        """返回运行形态：'portable'（程序目录可写）或 'installed'（装到只读目录）"""
        self.get_user_data_dir()  # 触发一次探测并写入缓存
        return self._cache['install_mode']

    def get_user_data_dir(self) -> Path:
        """用户数据目录（配置 / 日志 / 临时文件都放在它下面）

        - 便携模式：程序目录可写（U 盘、解压即用目录）→ 数据就写在程序目录里，
          整个目录拷走即完成迁移，与旧行为一致。
        - 安装模式：装到 Program Files 等只读位置 → 数据落到系统用户目录
          （Windows: %LOCALAPPDATA%\\JiuDown），否则配置根本存不下来。
        """
        if 'user_data_dir' in self._cache:
            return self._cache['user_data_dir']

        base = self._get_runtime_base_dir()
        if self._is_writable(base):
            data_dir, mode = base, 'portable'
        else:
            data_dir, mode = self._system_app_data_dir(), 'installed'
        self._cache['user_data_dir'] = data_dir
        self._cache['install_mode'] = mode
        logger.info(f"运行形态: {mode}，用户数据目录: {data_dir}")
        return data_dir

    def get_writable_resources_dir(self) -> Path:
        """可写的资源目录（FFmpeg 下载/升级的目标位置）

        便携模式就是程序目录下的 resources/；安装模式下 Program Files 不可写，
        落到用户数据目录下，避免"升级完整版 FFmpeg"直接失败。
        """
        if self.get_install_mode() == 'installed':
            return self.get_user_data_dir() / 'resources'
        return self._get_runtime_base_dir() / 'resources'

    def get_default_download_dir(self) -> Path:
        """默认下载目录：便携模式在程序目录下，安装模式用系统「下载」文件夹"""
        if self.get_install_mode() == 'installed':
            return Path.home() / 'Downloads' / APP_DIR_NAME
        return self._get_runtime_base_dir() / 'Download'

    def get_config_dir(self) -> Path:
        """获取配置目录路径（跟随用户数据目录，便携模式下即程序目录下的 config）"""
        return self.get_user_data_dir() / 'config'

    def get_default_paths(self) -> Dict[str, str]:
        """获取默认路径配置（区分程序目录与用户数据目录）"""
        base_dir = self._get_runtime_base_dir()
        data_dir = self.get_user_data_dir()
        ffmpeg_name = 'ffmpeg.exe' if platform.system() == 'Windows' else 'ffmpeg'
        # FFmpeg 查找顺序：用户目录下升级过的副本 → runtime → 程序内置 resources
        candidates = [
            self.get_writable_resources_dir() / ffmpeg_name,
            base_dir / 'runtime' / ffmpeg_name,
            base_dir / 'resources' / ffmpeg_name,
        ]
        ffmpeg_path = next((str(p) for p in candidates if p.exists()),
                           str(candidates[-1]))
        return {
            'temp_dir': str(data_dir / 'TEMP'),
            'download_dir': str(self.get_default_download_dir()),
            'config_dir': str(self.get_config_dir()),
            'logs_dir': str(data_dir / 'logs'),
            'resources_dir': str(base_dir / 'resources'),
            'ffmpeg_path': ffmpeg_path,
        }
    
    def get_system_type(self) -> str:
        """获取系统类型"""
        return platform.system()
    
    def is_windows(self) -> bool:
        """是否为Windows系统"""
        return platform.system() == 'Windows'
    
    def is_macos(self) -> bool:
        """是否为macOS系统"""
        return platform.system() == 'Darwin'
    
    def is_linux(self) -> bool:
        """是否为Linux系统"""
        return platform.system() == 'Linux'
    
    def is_64bit(self) -> bool:
        """是否为64位系统"""
        return struct.calcsize("P") * 8 == 64
    
    def is_arm(self) -> bool:
        """是否为ARM架构"""
        machine = platform.machine().lower()
        return 'arm' in machine or 'aarch64' in machine
    
    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()


    def initialize(self) -> None:
        """初始化系统信息管理器"""
        # 目前不需要特殊的初始化操作，但保留此方法以保持接口一致性
        logger.info("系统信息管理器初始化完成")


# 创建全局系统信息实例
system_info = SystemInfo()
