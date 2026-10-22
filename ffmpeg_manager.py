"""
FFmpeg 环境管理（完整版自动升级）

仓库不再跟踪 ffmpeg.exe（已加入 .gitignore），本地保留完整版二进制。
新 clone 用户首次启动时自动下载完整版；已有本地副本则直接使用。

启动时探测当前 ffmpeg 的能力：
- 完整版   → 无事
- 精简版/缺失 → 后台自动下载完整版 → 提取 → 校验能力 → 原子替换到目标路径
               （目标被占用时退避重试；仍失败则暂存 ffmpeg-full.exe，
                由下次启动补替换）

UI 侧通过 format_supported() / mono_supported() 禁用当前 ffmpeg 做不到的
选项；完整版就绪后经 capabilities_changed 信号重新门控。
"""

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

# 输出格式 → 所需 ffmpeg 能力（精简版缺 flv/wav 封装器与 pcm 编码器）
FORMAT_REQUIREMENTS = {
    "mp4": (),
    "flv": ("muxer:flv",),
    "mp3": ("encoder:libmp3lame",),
    "wav": ("encoder:pcm_s16le", "muxer:wav"),
}
# 单声道（-ac 1）需要音频重采样滤波器，精简版已禁用全部滤波器
MONO_REQUIREMENTS = ("filter:aresample",)
# “完整版”标记：自动下载替换的目标形态（BtbN gpl 构建全部具备）
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
        caps = _probe_capabilities(path)
        version = _probe_version(path)
    with _cap_lock:
        _cap_cache.update(key=key, caps=caps, version=version)
    return caps


def get_version() -> str:
    """当前 ffmpeg 版本号（探测不到返回空串）"""
    get_capabilities()
    with _cap_lock:
        return _cap_cache["version"]


def is_full() -> bool:
    """当前 ffmpeg 是否为完整版（具备全部输出能力）"""
    caps = get_capabilities()
    return bool(caps) and all(m in caps for m in FULL_MARKERS)


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

    status: full / lite / downloading / failed / missing
    """
    path = get_ffmpeg_path()
    with _state_lock:
        st = dict(_state)
    if st["status"] == "downloading":
        status = "downloading"
    elif st["status"] == "failed" and not is_full():
        status = "failed"
    elif not ffmpeg_exists():
        status = "missing"
    else:
        status = "full" if is_full() else "lite"
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


def start_auto_upgrade() -> bool:
    """启动时调用：非完整版则后台下载替换；已在下载则忽略"""
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
    """读取 FFmpeg 版本号，失败返回空串"""
    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_NO_WINDOW,
        )
        match = re.search(r"ffmpeg version (\S+)", result.stdout or "")
        return match.group(1).split("-")[0] if match else ""
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
                if not _extract_ffmpeg(zip_path, exe_path):
                    raise RuntimeError("压缩包中未找到 ffmpeg.exe")
                # 校验：能运行且具备完整版能力，才允许替换
                caps = _probe_capabilities(str(exe_path))
                missing = [m for m in FULL_MARKERS if m not in caps]
                if missing:
                    raise RuntimeError(f"下载的 ffmpeg 缺少能力: {missing}")
                _install(exe_path, target)
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
