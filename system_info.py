import platform
import struct
import socket
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger


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
    
    def get_config_dir(self) -> Path:
        """获取配置目录路径（便携模式：位于程序目录下，不写入系统 AppData）"""
        return self._get_runtime_base_dir() / 'config'
    
    def _get_runtime_base_dir(self) -> Path:
        """获取程序运行基础目录，打包后使用exe所在目录"""
        if getattr(sys, 'frozen', False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent
    
    def get_default_paths(self) -> Dict[str, str]:
        """获取默认路径配置"""
        base_dir = self._get_runtime_base_dir()
        ffmpeg_name = 'ffmpeg.exe' if platform.system() == 'Windows' else 'ffmpeg'
        return {
            'temp_dir': str(base_dir / 'TEMP'),
            'download_dir': str(base_dir / 'Download'),
            'config_dir': str(self.get_config_dir()),
            'logs_dir': str(base_dir / 'logs'),
            'resources_dir': str(base_dir / 'resources'),
            'ffmpeg_path': str(base_dir / 'resources' / ffmpeg_name),
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
