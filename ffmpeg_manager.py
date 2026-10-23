"""
FFmpeg 环境管理（精简版优先 + 用户显式升级完整版）

仓库跟踪的是一个从源码裁剪编译的精简版 ffmpeg.exe（约 5MB），已覆盖下载
链路所需的全部能力：容器重封装（mp4/flv/mkv…）、DASH 分片合并、mp3/wav
音频转码、声道重采样。缺失时自动从 Release 组件拉取（见 FFMPEG_LITE_URLS）。

需要视频重编码、罕见容器/滤镜等能力时，由用户在设置页显式点「下载完整版」
（约 161MB 的 BtbN 构建），本模块负责下载、校验并原子替换。

启动时探测当前 ffmpeg 的能力：
- 能力齐备（full / ready） → 无事
- 能力不足（lite）         → UI 门控掉做不到的格式/声道，并提示可升级
- 缺失（missing）          → 自动拉取精简版

UI 侧通过 format_supported() / mono_supported() 禁用当前 ffmpeg 做不到的
选项；二进制被替换后经 capabilities_changed 信号重新门控。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QObject, Signal

from config_manager import config_manager
from system_info import system_info

# 完整版下载源（按顺序尝试，全部失败才报错）。
# BtbN 的 latest/download 是固定资源名，无需 GitHub API（无速率限制）。
FFMPEG_URLS = [
    "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
]

# 精简版下载源（约 5MB）：由 tools/build_ffmpeg_lite.sh 从 FFmpeg 源码裁剪编译，
# 只含容器重封装 + 音频转码（含 libmp3lame）所需组件。
# 缺失时优先拉这个，而不是 161MB 的完整版。
FFMPEG_LITE_URLS = [
    "https://github.com/Yjiutong/JiuDown/releases/download/runtime/ffmpeg-lite.zip",
]

# 应用所需能力：下载链路（重封装 / DASH 合并 / mp3、wav 转码 / 单声道）
# 缺任何一项，对应格式或声道选项就要在 UI 置灰
APP_MARKERS = (
    "encoder:libmp3lame",
    "encoder:pcm_s16le",
    "muxer:mp4",
    "muxer:flv",
    "muxer:wav",
    "filter:aresample",
)
# 兼容旧名
LITE_MARKERS = APP_MARKERS

# 输出格式 → 所需 ffmpeg 能力
FORMAT_REQUIREMENTS = {
    "mp4": (),
    "flv": ("muxer:flv",),
    "mp3": ("encoder:libmp3lame",),
    "wav": ("encoder:pcm_s16le", "muxer:wav"),
}
# 单声道（-ac 1）需要音频重采样滤波器
MONO_REQUIREMENTS = ("filter:aresample",)
# “完整版”标记：BtbN gpl 构建全部具备（含视频重编码等下载链路用不到的能力）
FULL_MARKERS = (
    "encoder:libx264",
    "encoder:libmp3lame",
    "encoder:pcm_s16le",
    "muxer:flv",
    "muxer:wav",
)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class _FFmpegSignals(QObject):
    """跨线程信号：下载进度 / 完成 / 能力变化（能力变化驱动 UI 重新门控）"""

    progress = Signal(float)      # 0.0 ~ 1.0
    finished = Signal(bool, str)  # success, message
    capabilities_changed = Signal()


signals = _FFmpegSignals()

# 线程状态（跨线程轮询）
_state = {
    "status": "idle",        # idle / downloading / ok / failed
    "progress": 0.0,          # 0.0 ~ 1.0
    "error": "",
    "url": "",
}
_state_lock = threading.Lock()

# 能力缓存：键 = (路径, mtime_ns, size)，二进制被替换后自动失效
_cap_cache = {"key": None, "caps": frozenset(), "version": ""}
_cap_lock = threading.Lock()


# ---------------------------------------------------------------- 能力磁盘缓存

def _caps_cache_file() -> Path:
    """能力探测结果磁盘缓存路径（与配置文件同目录，跨启动复用）"""
    try:
        return Path(config_manager.get_config_file_path()).parent / "ffmpeg_caps.json"
    except Exception:
        return Path(__file__).resolve().parent / "config" / "ffmpeg_caps.json"


def _caps_key_dict(key) -> dict:
    path, mtime_ns, size = key
    return {"path": path, "mtime_ns": mtime_ns, "size": size}


def _load_disk_caps(key):
    """读取磁盘缓存；键不匹配（路径/时间/大小变化）返回 None

    省掉每次启动 3 次 ffmpeg 子进程探测（完整版二进制加载约 0.5s）。
    """
    if key is None:
        return None
    try:
        path = _caps_cache_file()
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("key") != _caps_key_dict(key):
            return None
        caps = frozenset(data.get("caps") or ())
        return caps, str(data.get("version") or "")
    except Exception:
        return None


def _save_disk_caps(key, caps, version: str) -> None:
    """写入磁盘缓存（失败静默：缓存只是加速手段）"""
    if key is None:
        return
    try:
        path = _caps_cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({
            "key": _caps_key_dict(key),
            "version": version,
            "caps": sorted(caps),
        }, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


# ---------------------------------------------------------------- 公共 API

def get_ffmpeg_path() -> str:
    """应用使用的 FFmpeg 路径（优先 runtime/ffmpeg.exe，其次 config 配置）"""
    # 优先使用 runtime 目录下的 ffmpeg
    from pathlib import Path
    base_dir = Path(__file__).resolve().parent
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys.executable).resolve().parent
    runtime_ffmpeg = base_dir / 'runtime' / 'ffmpeg.exe'
    if runtime_ffmpeg.exists():
        return str(runtime_ffmpeg)
    return config_manager.get_ffmpeg_path()


def ffmpeg_exists() -> bool:
    return bool(get_ffmpeg_path()) and Path(get_ffmpeg_path()).exists()


def get_capabilities(refresh: bool = False) -> frozenset:
    """当前 ffmpeg 的能力集合（encoder:/muxer:/filter: 前缀）；不存在返回空集"""
    path = get_ffmpeg_path()
    key = None
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    with _cap_lock:
        if not refresh and key is not None and _cap_cache["key"] == key:
            return _cap_cache["caps"]
    if key is None:
        caps, version = frozenset(), ""
    else:
        # 内存未命中 → 磁盘缓存（跨启动） → 实测探测
        disk = None if refresh else _load_disk_caps(key)
        if disk is not None:
            caps, version = disk
        else:
            caps = _probe_capabilities(path)
            version = _probe_version(path)
            _save_disk_caps(key, caps, version)
    with _cap_lock:
        _cap_cache.update(key=key, caps=caps, version=version)
    return caps


def get_version() -> str:
    """当前 ffmpeg 版本号（探测不到返回空串）"""
    get_capabilities()
    with _cap_lock:
        return _cap_cache["version"]


def is_full() -> bool:
    """当前 ffmpeg 是否为完整版（BtbN gpl 构建，含视频重编码等能力）"""
    caps = get_capabilities()
    return bool(caps) and all(m in caps for m in FULL_MARKERS)


def is_ready() -> bool:
    """当前 ffmpeg 是否具备下载链路所需的全部能力（精简版即可满足）

    与 is_full() 的区别：本函数只关心应用真正用到的能力，自建精简版就能通过；
    is_full() 额外要求 libx264 等视频重编码能力，用于「升级完整版」入口。
    """
    caps = get_capabilities()
    return bool(caps) and all(m in caps for m in APP_MARKERS)


def missing_features() -> list:
    """当前 ffmpeg 做不到的功能描述（用于提示文案），齐备时返回空列表"""
    missing = []
    if not format_supported("mp4"):
        missing.append("mp4 输出")
    if not format_supported("flv"):
        missing.append("flv")
    if not format_supported("mp3"):
        missing.append("mp3")
    if not format_supported("wav"):
        missing.append("wav")
    if not mono_supported():
        missing.append("单声道")
    return missing


def format_supported(fmt: str) -> bool:
    """该输出格式当前 ffmpeg 是否可产出（ffmpeg 缺失时一律不可用）"""
    caps = get_capabilities()
    if not caps:
        return False
    return all(r in caps for r in FORMAT_REQUIREMENTS.get(fmt, ()))


def mono_supported() -> bool:
    """单声道输出是否可用（需重采样滤波器；精简版会降级为双声道）"""
    caps = get_capabilities()
    return bool(caps) and all(r in caps for r in MONO_REQUIREMENTS)


def get_status() -> dict:
    """FFmpeg 状态快照（UI 轮询/初始化用）

    status: full  完整版（BtbN 构建，含视频重编码）
            ready 精简版但应用所需能力齐备（正常状态）
            lite  能力不足，部分格式/声道需置灰
            downloading / failed / missing
    """
    path = get_ffmpeg_path()
    with _state_lock:
        st = dict(_state)
    if st["status"] == "downloading":
        status = "downloading"
    elif st["status"] == "failed" and not is_ready():
        status = "failed"
    elif not ffmpeg_exists():
        status = "missing"
    elif is_full():
        status = "full"
    else:
        status = "ready" if is_ready() else "lite"
    return {
        "status": status,
        "path": path,
        "version": get_version(),
        "progress": st["progress"],
        "error": st["error"],
        "url": st["url"],
    }


def prepare() -> None:
    """启动准备（同步，约 0.3s）：应用上次遗留的完整版 + 预热能力缓存"""
    _apply_pending()
    get_capabilities(refresh=True)


def _local_lite_zip() -> Path | None:
    """仓库内随附的精简版组件包（离线安装用）"""
    try:
        from runtime_manager import get_component_dir  # noqa: PLC0415

        path = get_component_dir() / "ffmpeg-lite.zip"
    except Exception:
        path = Path(__file__).resolve().parent / "build_components" / "ffmpeg-lite.zip"
    return path if path.exists() else None


def _extract_ffmpeg(zip_path: Path, out_exe: Path) -> bool:
    """从 zip 中提取 bin/ffmpeg.exe"""
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            normalized = name.replace("\\", "/")
            if normalized.endswith("/bin/ffmpeg.exe"):
                with archive.open(name) as src, open(out_exe, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                return True
    return False


def _install_from_zip(zip_path: Path, target: Path, markers: tuple, label: str) -> bool:
    """从组件包安装：提取 → 能力校验 → 原子替换到 target"""
    if not _extract_ffmpeg(zip_path, target.parent / (target.name + ".new")):
        raise RuntimeError("压缩包中未找到 bin/ffmpeg.exe")
    staged = target.parent / (target.name + ".new")
    try:
        caps = _probe_capabilities(str(staged))
        missing = [m for m in markers if m not in caps]
        if missing:
            raise RuntimeError(f"{label}缺少能力: {missing}")
        _install(staged, target)
        return True
    finally:
        staged.unlink(missing_ok=True)


def ensure_available() -> bool:
    """确保有一个可用的 FFmpeg（缺失时补精简版，约 2.3MB 压包）

    与 start_auto_upgrade() 的分工：
      - 本函数只在**完全没有 ffmpeg** 时动作，且只下精简版
      - 已有精简版就保持不动，绝不悄悄升级成 161MB 完整版
    需要完整能力（罕见容器、视频重编码等）时，由用户显式点「升级完整版」。

    组件包随仓库分发（build_components/ffmpeg-lite.zip），命中就离线安装，
    只有在仓库里没带这份包时才去 Release 拉取。
    """
    if ffmpeg_exists():
        return True

    target = Path(get_ffmpeg_path())
    resources_dir = Path(system_info.get_default_paths()["resources_dir"])
    resources_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = resources_dir / ".ffmpeg_lite_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    exe_path = tmp_dir / "ffmpeg.exe"

    last_error = ""
    try:
        local = _local_lite_zip()
        if local is not None:
            logger.info(f"使用仓库内精简版 FFmpeg 组件: {local}")
            try:
                if _install_from_zip(local, target, APP_MARKERS, "精简版"):
                    get_capabilities(refresh=True)
                    _set("ok", progress=1.0, error="")
                    signals.capabilities_changed.emit()
                    signals.finished.emit(True, "精简版 FFmpeg 已就绪")
                    logger.success(f"精简版 FFmpeg 已就位: {target}")
                    return True
            except Exception as e:
                last_error = str(e)
                logger.warning(f"仓库内精简版组件不可用（{local.name}）: {e}")

        zip_path = tmp_dir / "ffmpeg-lite.zip"
        for url in FFMPEG_LITE_URLS:
            try:
                _set("downloading", url=url)
                logger.info(f"下载精简版 FFmpeg: {url}")
                _download_zip(url, zip_path)
                if _install_from_zip(zip_path, target, APP_MARKERS, "精简版"):
                    get_capabilities(refresh=True)
                    _set("ok", progress=1.0, error="")
                    signals.capabilities_changed.emit()
                    signals.finished.emit(True, "精简版 FFmpeg 已就绪")
                    logger.success(f"精简版 FFmpeg 已就位: {target}")
                    return True
            except Exception as e:
                last_error = str(e)
                logger.warning(f"精简版 FFmpeg 下载失败 {url}: {e}")
                zip_path.unlink(missing_ok=True)
                exe_path.unlink(missing_ok=True)
                continue
        _set("failed", error=last_error)
        signals.finished.emit(False, last_error)
        logger.error(f"精简版 FFmpeg 下载失败: {last_error}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def start_auto_upgrade() -> bool:
    """显式升级：下载完整版并替换（设置页/首页按钮调用）

    注意：启动流程**不再**调用本函数——精简版已能满足全部下载链路，
    自动拉 161MB 完整版只会浪费流量。缺少 FFmpeg 时用 ensure_available()。
    """
    if ffmpeg_exists() and is_full():
        return False
    with _state_lock:
        if _state["status"] == "downloading":
            return False
        _state.update(status="downloading", progress=0.0, error="",
                      url=FFMPEG_URLS[0])
    threading.Thread(target=_upgrade_worker, daemon=True).start()
    return True


# 兼容旧入口（首页状态卡）
start_download = start_auto_upgrade


# ---------------------------------------------------------------- 内部实现

def _probe_version(path: str) -> str:
    """读取 FFmpeg 版本号，失败返回空串

    两种版本串都要能读出人看得懂的部分：
      官方 BtbN 构建  N-127900-ge2798d5cad  → N-127900
      自建精简版      git-2026-10-23-abb54ce → 2026-10-23
    """
    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_NO_WINDOW,
        )
        match = re.search(r"ffmpeg version (\S+)", result.stdout or "")
        if not match:
            return ""
        raw = match.group(1)
        parts = raw.split("-")
        if raw.startswith("git-") and len(parts) >= 4:
            return f"{parts[1]}-{parts[2]}-{parts[3]}"
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}"
        return raw
    except Exception:
        return ""


def _probe_capabilities(path: str) -> frozenset:
    """运行 -encoders/-muxers/-filters，汇总能力集合。

    输出行首是 1~6 字符的能力标志列（如 " A....D libx264"、" E flv"），
    第二个 token 即名称；图例行（" V.... = Video"）会混入 "="，无害。
    """
    caps = set()
    for opt, prefix in (
        ("-encoders", "encoder:"),
        ("-muxers", "muxer:"),
        ("-filters", "filter:"),
    ):
        try:
            result = subprocess.run(
                [path, "-hide_banner", opt],
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=_NO_WINDOW,
            )
        except Exception as e:
            logger.debug(f"ffmpeg {opt} 探测失败: {e}")
            continue
        for line in (result.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 2 and re.fullmatch(r"[A-Z.]{1,6}", parts[0]):
                caps.add(prefix + parts[1])
    return frozenset(caps)


def _set(status: str, **kwargs) -> None:
    with _state_lock:
        _state["status"] = status
        _state.update(kwargs)


def _upgrade_worker() -> None:
    """后台线程：下载完整版 → 校验 → 替换"""
    target = Path(get_ffmpeg_path())
    resources_dir = Path(system_info.get_default_paths()["resources_dir"])
    resources_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = resources_dir / ".ffmpeg_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = tmp_dir / "ffmpeg.zip"
    exe_path = tmp_dir / "ffmpeg.exe"

    try:
        last_error = ""
        for url in FFMPEG_URLS:
            try:
                _set("downloading", url=url)
                logger.info(f"开始下载完整版 FFmpeg: {url}")
                _download_zip(url, zip_path)
                # 校验：能运行且具备完整版能力，才允许替换
                if _install_from_zip(zip_path, target, FULL_MARKERS, "完整版"):
                    get_capabilities(refresh=True)
                    _set("ok", progress=1.0, error="")
                    signals.capabilities_changed.emit()
                    signals.finished.emit(True, f"完整版 FFmpeg 已就绪（{target.name}）")
                    logger.success(f"完整版 FFmpeg 已替换: {target}")
                    return
            except Exception as e:
                last_error = str(e)
                logger.warning(f"完整版 FFmpeg 下载源失败 {url}: {e}")
                zip_path.unlink(missing_ok=True)
                exe_path.unlink(missing_ok=True)
                continue
        _set("failed", error=last_error)
        signals.finished.emit(False, last_error)
        logger.error(f"完整版 FFmpeg 自动拉取失败: {last_error}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _install(src: Path, target: Path) -> None:
    """把下载校验过的完整版原子替换到目标路径

    Windows 下目标被占用（下载任务合并中）会 PermissionError：合并窗口
    通常很短，退避重试；仍失败则暂存为 ffmpeg-full.exe，由下次启动的
    _apply_pending() 补替换（期间 UI 仍按精简版门控）。
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(45):
        try:
            os.replace(src, target)
            return
        except PermissionError:
            if attempt == 0:
                logger.info("ffmpeg.exe 正被占用，将在就绪后自动替换")
            time.sleep(2)
    pending = target.parent / "ffmpeg-full.exe"
    shutil.copy2(src, pending)
    logger.warning(
        f"ffmpeg.exe 长时间被占用，完整版已暂存 {pending}，下次启动自动替换"
    )


def _apply_pending() -> None:
    """把上次遗留的 ffmpeg-full.exe 替换到目标（启动时调用）"""
    target = Path(get_ffmpeg_path())
    pending = target.parent / "ffmpeg-full.exe"
    if not pending.exists():
        return
    try:
        os.replace(pending, target)
        logger.success(f"已应用遗留的完整版 FFmpeg: {target}")
    except PermissionError:
        logger.info("ffmpeg.exe 占用中，遗留完整版将在下次启动应用")
    except Exception as e:
        logger.warning(f"应用遗留完整版失败: {e}")


def _download_zip(url: str, dest: Path) -> None:
    import requests
    with requests.get(url, stream=True, timeout=(10, 60)) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        done = 0
        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=512 * 1024):
                if chunk:
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        progress = done / total
                        _set("downloading", progress=progress)
                        signals.progress.emit(progress)
