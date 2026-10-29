import yaml
import os
from pathlib import Path
from typing import Dict, Any, Optional
import json
from loguru import logger
from system_info import system_info


# 辅助函数
def ensure_dir(path: str) -> str:
    """确保目录存在，如果不存在则创建"""
    path_obj = Path(path)
    path_obj.mkdir(parents=True, exist_ok=True)
    return str(path_obj)

def find_executable(name: str) -> Optional[str]:
    """查找可执行文件路径"""
    try:
        import shutil
        return shutil.which(name)
    except ImportError:
        return None


# 落盘时收成 ${APP_ROOT} token、读取时再展开的配置项（便携版换路径/盘符不失效）
PATH_KEYS = (
    ('download-task', 'temp-dir', 'temp_dir'),
    ('download-task', 'download-dir', 'download_dir'),
    ('download-task', 'ffmpeg-path', 'ffmpeg_path'),
)


def usable_dir(value: str, fallback_key: str) -> str:
    """确保目录可用；不可用时回退到当前默认值

    旧配置里常留着换过盘符的绝对路径（如 E:\\JiuDown\\TEMP）。ensure_dir 碰上失效卷
    会直接抛 WinError 1005，而 get_config 的 post_processor 抛错时只记日志、把坏值
    原样返回——崩溃点于是被推迟到下载途中的 mkdir，看起来像下载器坏了。这里就地回退。
    """
    expanded = system_info.from_config_path(value)
    try:
        return ensure_dir(expanded)
    except Exception as e:
        default = system_info.get_default_paths()[fallback_key]
        logger.warning(f"配置目录 {expanded} 不可用（{e}），改用 {default}")
        return ensure_dir(default)


def quality_tiers() -> list:
    """默认档位名单统一取自引擎；引擎不可用时退回一份内置名单

    退的那份只用于校验，不参与选流——避免导入期成环（ytdlp_engine 反向惰性依赖本模块）。
    """
    try:
        from ytdlp_engine import QUALITY_CHOICES
        return list(QUALITY_CHOICES)
    except Exception:
        return ['最高', '4K', '2K', '1080P', '720P', '480P', '360P']


class ConfigManager:
    """配置文件管理器"""
    
    # 配置项定义模式 - 统一配置访问
    CONFIG_SCHEMA = {
        'download_dir': {
            'path': 'download-task.download-dir',
            'default': lambda: system_info.get_default_paths()['download_dir'],
            'post_processor': lambda path: usable_dir(path, 'download_dir'),
            'description': '下载目录'
        },
        'temp_dir': {
            'path': 'download-task.temp-dir', 
            'default': lambda: system_info.get_default_paths()['temp_dir'],
            'post_processor': lambda path: usable_dir(path, 'temp_dir'),
            'description': '临时目录'
        },
        'ffmpeg_path': {
            'path': 'download-task.ffmpeg-path',
            'default': lambda: system_info.get_default_paths()['ffmpeg_path'],
            'post_processor': system_info.from_config_path,
            'description': 'FFmpeg路径'
        },
        'log_level': {
            'path': 'log-level',
            'default': 'info',
            'validator': lambda x: x in ['info', 'warning', 'error', 'debug', 'silent'],
            'description': '日志级别'
        },
        'max_task': {
            'path': 'download-task.max-task',
            'default': 2,
            'validator': lambda x: 1 <= x <= 5,
            'normalizer': lambda x: max(1, min(5, x)),
            'description': '最大同时下载任务数'
        },
        'download_speed_limit': {
            'path': 'download-task.download-speed-limit',
            'default': 0,
            'validator': lambda x: 0 <= x <= 1073741824,
            'description': '下载速度限制'
        },
        'default_quality': {
            'path': 'download-task.quality',
            'default': '720P',
            'validator': lambda x: x in quality_tiers() or x in ('单声道', '双声道'),
            'normalizer': lambda x: x if x in quality_tiers() else '720P',
            'description': '默认画质（视频没这么高时自动降到最高可用档）'
        },
        'default_format': {
            'path': 'download-task.format',
            'default': 'mp4',
            'validator': lambda x: x in ['mp4', 'flv', 'mp3', 'wav'],
            'normalizer': lambda x: x if x in ['mp4', 'flv', 'mp3', 'wav'] else 'mp4',
            'description': '默认格式'
        },
        'playlist_limit': {
            'path': 'download-task.playlist-limit',
            'default': 1,
            'validator': lambda x: 1 <= x <= 500,
            'normalizer': lambda x: max(1, min(500, int(x))),
            'description': '播放列表/合集最多下载条数（1=只下当前视频）'
        },
        'proxy': {
            'path': 'engine.proxy',
            'default': '',
            'description': '下载代理地址（如 http://127.0.0.1:7890）'
        },
        'engine_backend': {
            'path': 'engine.backend',
            'default': 'auto',
            'validator': lambda x: x in ('auto', 'native', 'ytdlp'),
            'normalizer': lambda x: x if x in ('auto', 'native', 'ytdlp') else 'auto',
            'description': '下载引擎路由：auto=原生优先并自动降级 / native=仅原生 / ytdlp=仅 yt-dlp'
        },
        'cookies_from_browser': {
            'path': 'engine.cookies-from-browser',
            'default': '不使用',
            'description': '从浏览器读取 Cookie 的来源（chrome/edge/firefox…）'
        },
        'user_info': {
            'path': 'user-info',
            'default': dict,
            'description': '用户信息'
        },
        'external_ports': {
            'path': 'external-controller-port',
            'default': lambda: {
                'grpc': 4000,
                'grpc-web': 4100,
                'restful-api': 64001
            },
            'validator': lambda ports: (
                isinstance(ports, dict) and
                all(isinstance(p, int) for p in ports.values()) and
                # gRPC端口验证 (1024-49151或0)
                (ports.get('grpc', 0) == 0 or 1024 <= ports.get('grpc', 0) <= 49151) and
                # gRPC-Web端口验证 (1024-49151或0)
                (ports.get('grpc-web', 0) == 0 or 1024 <= ports.get('grpc-web', 0) <= 49151) and
                # RESTful API端口验证 (固定64001)
                ports.get('restful-api', 0) == 64001
            ),
            'description': '外部控制器端口配置'
        }
    }
    
    def __init__(self):
        self.config_data = {}
        self.config_file_path = None
        self.default_config = self._get_default_config()
        # 缓存配置值以避免重复计算
        self._config_cache = {}
    
    def initialize(self) -> None:
        """初始化配置管理器，加载配置文件"""
        self.load_config()
        logger.info("配置管理器初始化完成")
    
    def get_config(self, config_key: str, use_cache: bool = True) -> Any:
        """
        统一配置访问方法 - 替代所有单独的get_xxx方法
        
        Args:
            config_key: 配置项键名，对应CONFIG_SCHEMA中的键
            use_cache: 是否使用缓存
            
        Returns:
            配置值
        """
        if use_cache and config_key in self._config_cache:
            return self._config_cache[config_key]
        
        if config_key not in self.CONFIG_SCHEMA:
            logger.warning(f"未知的配置项: {config_key}")
            return None
        
        schema = self.CONFIG_SCHEMA[config_key]
        config_path = schema['path']
        
        # 获取配置值
        value = self.get(config_path)
        
        # 如果没有设置配置值，使用默认值
        if value is None:
            default_value = schema['default']
            # 如果默认值是可调用对象，调用它获取实际值
            if callable(default_value):
                try:
                    value = default_value()
                    logger.info(f"配置项 {config_key} 使用默认值: {value}")
                except Exception as e:
                    logger.error(f"获取配置项 {config_key} 默认值失败: {e}")
                    value = None
            else:
                value = default_value
        
        # 验证配置值
        validator = schema.get('validator')
        if validator and value is not None:
            if not validator(value):
                logger.warning(f"配置项 {config_key} 的值 {value} 未通过验证，使用默认值")
                # 重新获取默认值
                default_value = schema['default']
                if callable(default_value):
                    value = default_value()
                else:
                    value = default_value
        
        # 标准化配置值
        normalizer = schema.get('normalizer')
        if normalizer and value is not None:
            value = normalizer(value)
        
        # 后处理配置值
        post_processor = schema.get('post_processor')
        if post_processor and value is not None:
            try:
                value = post_processor(value)
            except Exception as e:
                logger.error(f"配置项 {config_key} 后处理失败: {e}")
        
        # 缓存结果
        if use_cache:
            self._config_cache[config_key] = value
        
        return value
    
    def set_config(self, config_key: str, value: Any) -> None:
        """
        统一配置设置方法 - 替代所有单独的set_xxx方法
        
        Args:
            config_key: 配置项键名，对应CONFIG_SCHEMA中的键
            value: 要设置的值
        """
        if config_key not in self.CONFIG_SCHEMA:
            logger.warning(f"未知的配置项: {config_key}")
            return
        
        schema = self.CONFIG_SCHEMA[config_key]
        config_path = schema['path']
        
        # 清除缓存
        if config_key in self._config_cache:
            del self._config_cache[config_key]
        
        # 设置配置值
        self.set(config_path, value)
        logger.info(f"配置项 {config_key} 已设置为: {value}")
    
    def clear_cache(self) -> None:
        """清除配置缓存"""
        self._config_cache.clear()
        logger.debug("配置缓存已清除")
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            'log-level': 'info',
            'external-controller-port': {
                'grpc': 4000,
                'grpc-web': 4100,
                'restful-api': 64001
            },
            'user-info': {
                'access-token': '',
                'refresh-token': '',
                'cookies': '',
                'raw-access-token': '',
                'raw-cookies': '',
                'hide-nickname': False
            },
            'download-task': {
                # 程序目录内的路径落成 ${APP_ROOT} 形式：新装的 config 从第一个字节起
                # 就可移植，整个文件夹拷走不需要修复
                'temp-dir': system_info.to_config_path(
                    system_info.get_default_paths()['temp_dir']),
                'download-dir': system_info.to_config_path(
                    system_info.get_default_paths()['download_dir']),
                'ffmpeg-path': system_info.to_config_path(
                    system_info.get_default_paths()['ffmpeg_path']),
                'max-task': 2,
                'download-speed-limit': 0,
                'disable-mcdn': False,
                'quality': '720P',
                'format': 'mp4',
                'playlist-limit': 1
            },
            'engine': {
                # 下载引擎（native B 站链路 + yt-dlp 通用后端）
                'backend': 'auto',
                'proxy': '',
                'cookies-from-browser': '不使用'
            },
            'jdm': {
                'max-retry': 3,
                'retry-wait': 5,
                'session-workers': 1,
                'part-workers': 4,
                'min-split-size': 30,
                'proxy-addr': '',
                'check-best-mirror': True,
                'cache-in-ram': False,
                'cache-in-ram-limit': 512,
                'insecure-skip-verify': False,
                'custom-root-certificates': ''
            }
        }
    
    def get_config_dir(self) -> Path:
        """获取配置目录路径"""
        config_dir = system_info.get_config_dir()
        # 确保配置目录存在
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir
    
    def get_config_file_path(self) -> Path:
        """获取配置文件路径"""
        return self.get_config_dir() / 'config.yaml'
    
    def load_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径，如果为None则使用默认路径
            
        Returns:
            配置数据字典
        """
        if config_path:
            config_file = Path(config_path)
        else:
            config_file = self.get_config_file_path()
            
        self.config_file_path = config_file
        
        try:
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    self.config_data = yaml.safe_load(f) or {}
                
                # 合并默认配置，确保所有必需的键都存在
                self.config_data = self._merge_with_defaults(self.config_data)
                logger.info(f"配置文件加载成功: {config_file}")
            else:
                # 如果配置文件不存在，使用默认配置并设置默认下载路径
                self.config_data = self.default_config.copy()
                logger.info(f"配置文件不存在，使用默认配置: {config_file}")
                self.save_config()
                
        except yaml.YAMLError as e:
            logger.error(f"配置文件格式错误: {e}")
            self.config_data = self.default_config.copy()
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            self.config_data = self.default_config.copy()
            
        if self._normalize_core_compatible_config():
            self.save_config()
        
        return self.config_data.copy()
    
    def _merge_with_defaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """将用户配置与默认配置合并"""
        merged = self.default_config.copy()
        self._deep_merge(merged, config)
        return merged
    
    def _normalize_core_compatible_config(self) -> bool:
        """修正与当前环境不兼容的旧配置值（含路径重锚定与 ${APP_ROOT} 收敛）"""
        changed = False
        jdm = self.config_data.get('jdm')
        if not isinstance(jdm, dict):
            self.config_data['jdm'] = jdm = {}
            changed = True
        
        download_task = self.config_data.get('download-task')
        if not isinstance(download_task, dict):
            self.config_data['download-task'] = download_task = {}
            changed = True
        
        # 路径项：展开 token 后校验可用性，不可用（换了盘符、U 盘拔了）就回退到
        # 当前默认值并重写；可用则统一收成 ${APP_ROOT} 形式存着
        for section, key, fallback in PATH_KEYS:
            block = self.config_data.get(section)
            if not isinstance(block, dict):
                continue
            stored = block.get(key)
            if not isinstance(stored, str) or not stored.strip():
                block[key] = system_info.to_config_path(
                    system_info.get_default_paths()[fallback])
                changed = True
                continue
            expanded = system_info.from_config_path(stored)
            if key == 'ffmpeg-path':
                if not Path(expanded).exists():
                    block[key] = system_info.to_config_path(
                        system_info.get_default_paths()[fallback])
                    changed = True
            else:
                healed = usable_dir(expanded, fallback)
                if healed != expanded or system_info.to_config_path(healed) != stored:
                    block[key] = system_info.to_config_path(healed)
                    changed = True
        
        min_split_size = jdm.get('min-split-size')
        if not isinstance(min_split_size, int) or not (1 <= min_split_size <= 100):
            jdm['min-split-size'] = 30
            changed = True
        
        cache_in_ram_limit = jdm.get('cache-in-ram-limit')
        if not isinstance(cache_in_ram_limit, int) or not (500 <= cache_in_ram_limit <= 16384):
            jdm['cache-in-ram-limit'] = 512
            changed = True
        
        return changed
    
    def _deep_merge(self, base: Dict[str, Any], update: Dict[str, Any]) -> None:
        """深度合并字典"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value
    
    def _paths_for_storage(self) -> None:
        """落盘前把路径项收成 ${APP_ROOT} 形式

        在 save_config 里统一做，而不是在各个 setter 里做：设置页是整段 yaml 字典
        直接写进来的，只盯 set_config 会漏掉那条路径。
        """
        for section, key, schema_key in PATH_KEYS:
            block = self.config_data.get(section)
            if not isinstance(block, dict):
                continue
            value = block.get(key)
            if isinstance(value, str) and value.strip():
                block[key] = system_info.to_config_path(value)
            # 整段替换配置时不会走 set_config，缓存得自己失效，
            # 否则在设置页改了临时目录要重启才生效
            self._config_cache.pop(schema_key, None)

    def save_config(self, config_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        保存配置文件
        
        Args:
            config_data: 要保存的配置数据，如果为None则使用当前配置
            
        Returns:
            是否保存成功
        """
        if config_data:
            self.config_data = config_data

        self._paths_for_storage()

        if not self.config_file_path:
            self.config_file_path = self.get_config_file_path()
            
        try:
            # 确保配置目录存在
            self.config_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 保存配置文件
            with open(self.config_file_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                
            logger.success(f"配置文件保存成功: {self.config_file_path}")
            return True
            
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            return False
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key_path: 键路径，用点号分隔，如 'download-task.max-task'
            default: 默认值
            
        Returns:
            配置值
        """
        keys = key_path.split('.')
        value = self.config_data
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
                
        return value
    
    def set(self, key_path: str, value: Any) -> None:
        """
        设置配置值
        
        Args:
            key_path: 键路径，用点号分隔，如 'download-task.max-task'
            value: 要设置的值
        """
        keys = key_path.split('.')
        target = self.config_data
        
        # 遍历到倒数第二个键
        for key in keys[:-1]:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
            target = target[key]
            
        # 设置最终值
        target[keys[-1]] = value
    
    # 以下是兼容旧代码的方法，现在都是get_config的包装器
    def get_download_dir(self) -> str:
        """获取下载目录"""
        return self.get_config('download_dir')
    
    def get_temp_dir(self) -> str:
        """获取临时目录"""
        return self.get_config('temp_dir')
    
    def get_ffmpeg_path(self) -> str:
        """获取FFmpeg路径"""
        return self.get_config('ffmpeg_path')
    
    def get_log_level(self) -> str:
        """获取日志级别"""
        return self.get_config('log_level')
    
    def get_max_task(self) -> int:
        """获取最大任务数"""
        return self.get_config('max_task')
    
    def get_download_speed_limit(self) -> int:
        """获取下载速度限制"""
        return self.get_config('download_speed_limit')

    def get_default_quality(self) -> str:
        """获取默认清晰度"""
        return self.get_config('default_quality')

    def get_default_format(self) -> str:
        """获取默认格式"""
        return self.get_config('default_format')
    
    def get_user_info(self) -> Dict[str, Any]:
        """获取用户信息"""
        return self.get_config('user_info')
    
    def set_user_info(self, user_info: Dict[str, Any]) -> None:
        """设置用户信息"""
        self.set_config('user_info', user_info)
    
    def get_external_ports(self) -> Dict[str, int]:
        """获取外部控制器端口配置"""
        return self.get_config('external_ports')
    
    def export_config(self, export_path: str) -> bool:
        """
        导出配置到指定路径
        
        Args:
            export_path: 导出路径
            
        Returns:
            是否导出成功
        """
        try:
            self._paths_for_storage()
            export_file = Path(export_path)
            with open(export_file, 'w', encoding='utf-8') as f:
                yaml.dump(self.config_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            return True
        except Exception as e:
            logger.error(f"导出配置文件失败: {e}")
            return False
    
    def import_config(self, import_path: str) -> bool:
        """
        从指定路径导入配置
        
        Args:
            import_path: 导入路径
            
        Returns:
            是否导入成功
        """
        try:
            import_file = Path(import_path)
            if not import_file.exists():
                return False
                
            with open(import_file, 'r', encoding='utf-8') as f:
                imported_config = yaml.safe_load(f) or {}
            
            # 合并配置
            self.config_data = self._merge_with_defaults(imported_config)
            return True
            
        except Exception as e:
            logger.error(f"导入配置文件失败: {e}")
            return False
    
    def reset_to_default(self) -> None:
        """重置为默认配置"""
        self.config_data = self.default_config.copy()
        self.save_config()
        logger.info("配置已重置为默认值")


# 创建全局配置管理器实例
config_manager = ConfigManager()
