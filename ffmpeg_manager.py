"""
FFmpeg 环境管理
FFmpeg 体积较大（完整版约 100MB），不随仓库分发；
应用首次启动检测缺失时自动从网络拉取，也可由用户手动放置到 resources 目录。
"""

import os
import re
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path

from loguru import logger

from config_manager import config_manager
from system_info import system_info

# 下载源（按顺序尝试，全部失败才报错）
FFMPEG_URLS = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
]

# 线程状态（跨线程轮询）
_state = {
    "status": "idle",        # idle / downloading / ok / failed
    "progress": 0.0,          # 0.0 ~ 1.0
    "error": "",
    "url": "",
}
_state_lock = threading.Lock()


def get_ffmpeg_path() -> str:
    """应用使用的 FFmpeg 路径（可能不存在）"""
    return config_manager.get_ffmpeg_path()


def ffmpeg_exists() -> bool:
    return bool(get_ffmpeg_path()) and Path(get_ffmpeg_path()).exists()


def get_status() -> dict:
    """返回 FFmpeg 状态：
    ok -> 已就绪（附版本号）；missing -> 未找到；downloading -> 下载中；failed -> 拉取失败
    """
    if ffmpeg_exists():
        return {
            "status": "ok",
            "path": get_ffmpeg_path(),
            "version": _probe_version(get_ffmpeg_path()),
            "progress": 1.0,
            "error": "",
        }
    with _state_lock:
        return {
            "status": _state["status"],
            "path": get_ffmpeg_path(),
            "version": "",
            "progress": _state["progress"],
            "error": _state["error"],
            "url": _state["url"],
        }


def start_download() -> bool:
    """后台线程拉取 FFmpeg（已存在或已在下载则忽略）"""
    if ffmpeg_exists():
        return False
    with _state_lock:
        if _state["status"] == "downloading":
            return False
        _state["status"] = "downloading"
        _state["progress"] = 0.0
        _state["error"] = ""
        _state["url"] = FFMPEG_URLS[0]
    threading.Thread(target=_worker, daemon=True).start()
    return True


# ---------------------------------------------------------------- 内部实现

def _probe_version(path: str) -> str:
    """读取 FFmpeg 版本号，失败返回空串"""
    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        match = re.search(r"ffmpeg version (\S+)", result.stdout or "")
        return match.group(1).split("-")[0] if match else ""
    except Exception:
        return ""


def _set(status: str, **kwargs) -> None:
    with _state_lock:
        _state["status"] = status
        _state.update(kwargs)


def _worker() -> None:
    resources_dir = Path(system_info.get_default_paths()["resources_dir"])
    resources_dir.mkdir(parents=True, exist_ok=True)
    target = Path(get_ffmpeg_path())
    tmp_dir = resources_dir / ".ffmpeg_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = tmp_dir / "ffmpeg.zip"
    exe_path = tmp_dir / "ffmpeg.exe"

    try:
        import requests
        last_error = ""
        for url in FFMPEG_URLS:
            try:
                _set("downloading", url=url)
                logger.info(f"开始下载 FFmpeg: {url}")
                _download_zip(url, zip_path)
                if not _extract_ffmpeg(zip_path, exe_path):
                    raise RuntimeError("压缩包中未找到 ffmpeg.exe")
                # 提取成功：验证可执行
                if _probe_version(str(exe_path)):
                    shutil.move(str(exe_path), str(target))
                    _set("ok", progress=1.0, error="")
                    logger.success(f"FFmpeg 已就绪: {target}")
                    return
                raise RuntimeError("下载的 ffmpeg.exe 无法运行")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"FFmpeg 下载源失败 {url}: {e}")
                zip_path.unlink(missing_ok=True)
                if exe_path.exists():
                    exe_path.unlink(missing_ok=True)
                continue
        _set("failed", error=last_error)
        logger.error(f"FFmpeg 自动拉取失败: {last_error}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _download_zip(url: str, dest: Path) -> None:
    import requests
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()
    total = int(response.headers.get("content-length") or 0)
    done = 0
    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=256 * 1024):
            if chunk:
                f.write(chunk)
                done += len(chunk)
                if total:
                    _set("downloading", progress=done / total)


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
