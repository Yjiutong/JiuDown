"""
Runtime 环境自举管理

启动时自检 runtime/ 目录：
- 完整 → 直接使用 runtime/python/python.exe 运行
- 缺失/不完整 → 从 GitHub Release 下载 runtime.zip → 解压 → 校验 → 使用

runtime 目录结构：
  runtime/
  ├── python/              嵌入式 Python 3.12 + site-packages
  │   ├── python.exe
  │   ├── python312.dll
  │   └── Lib/site-packages/
  ├── ffmpeg.exe           完整版 FFmpeg
  └── JiuDownCore-win64.exe  核心下载进程
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from loguru import logger

# GitHub Release 下载源（你的仓库，tag=runtime，资产=runtime.zip）
RUNTIME_RELEASE_URL = (
    "https://github.com/Yjiutong/JiuDown/releases/download/runtime/runtime.zip"
)

# runtime 目录位置（应用根目录下）
RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"
RUNTIME_PYTHON = RUNTIME_DIR / "python" / "python.exe"
RUNTIME_FFMPEG = RUNTIME_DIR / "ffmpeg.exe"

# 完整性检查：这些文件必须存在
REQUIRED_FILES = [
    "python/python.exe",
    "python/python312.dll",
    "ffmpeg.exe",
]

# 引擎后端随 runtime.zip 一起发布（不再从 PyPI 安装），缺它视为运行时过期
ENGINE_PACKAGE_DIR = "python/Lib/site-packages/yt_dlp"


def get_base_dir() -> Path:
    """获取应用根目录（打包后为 exe 所在目录，开发模式为脚本所在目录）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_runtime_dir() -> Path:
    """runtime 目录路径"""
    return get_base_dir() / "runtime"


def get_python_exe() -> Path:
    """runtime 中的 Python 可执行文件路径"""
    return get_runtime_dir() / "python" / "python.exe"


def get_ffmpeg_path() -> Path:
    """runtime 中的 ffmpeg 路径"""
    return get_runtime_dir() / "ffmpeg.exe"


def has_engine_backend() -> bool:
    """runtime 里是否带有 yt-dlp 后端

    引擎依赖统一由 release 上的 runtime.zip 提供（不走 PyPI），
    因此"运行时完整"必须包含引擎目录，否则视为旧版运行时、需要重新拉取。
    """
    return (get_runtime_dir() / ENGINE_PACKAGE_DIR).is_dir()


def is_runtime_complete(check_engine: bool = True) -> bool:
    """检查 runtime 目录是否完整可用

    Args:
        check_engine: 是否同时要求 yt-dlp 后端存在（旧版运行时没有该目录，
            返回 False 会触发重新下载含引擎的新运行时）
    """
    runtime_dir = get_runtime_dir()
    if not runtime_dir.exists():
        return False
    for rel in REQUIRED_FILES:
        if not (runtime_dir / rel).exists():
            logger.warning(f"runtime 缺失: {rel}")
            return False
    if check_engine and not has_engine_backend():
        logger.warning("runtime 缺少下载引擎（yt-dlp），需要从 Release 更新运行时")
        return False
    # 验证 python 可执行
    python_exe = get_python_exe()
    try:
        result = subprocess.run(
            [str(python_exe), "-c", "import sys; print(sys.version)"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            logger.warning(f"runtime Python 不可用: {result.stderr}")
            return False
        logger.info(f"runtime Python 版本: {result.stdout.strip()}")
    except Exception as e:
        logger.warning(f"runtime Python 验证失败: {e}")
        return False
    return True


def download_runtime(progress_callback=None) -> bool:
    """从 GitHub Release 下载 runtime.zip 并解压到 runtime/

    Args:
        progress_callback: 可选的进度回调 (downloaded_bytes, total_bytes) -> None

    Returns:
        下载并解压是否成功
    """
    import requests

    runtime_dir = get_runtime_dir()
    url = RUNTIME_RELEASE_URL
    logger.info(f"开始下载 runtime: {url}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="jiudown_runtime_"))
    zip_path = tmp_dir / "runtime.zip"

    try:
        # 下载
        with requests.get(url, stream=True, timeout=(15, 300)) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            downloaded = 0
            with open(zip_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)
                        if total:
                            pct = downloaded / total * 100
                            logger.debug(f"runtime 下载进度: {pct:.1f}%")

        logger.info(f"runtime.zip 下载完成: {zip_path.stat().st_size / 1024 / 1024:.1f} MB")

        # 解压
        logger.info("开始解压 runtime.zip ...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)

        # 找到解压后的目录（可能有一层根目录）
        extracted_dirs = [d for d in tmp_dir.iterdir() if d.is_dir() and d.name != "__MACOSX"]
        if not extracted_dirs:
            logger.error("解压后未找到目录")
            return False

        source_dir = extracted_dirs[0]
        logger.info(f"解压源目录: {source_dir}")

        # 备份旧 runtime（如果存在）
        if runtime_dir.exists():
            backup = runtime_dir.with_suffix(".bak")
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            runtime_dir.rename(backup)
            logger.info(f"旧 runtime 已备份到 {backup}")

        # 移动新 runtime 到目标位置
        shutil.move(str(source_dir), str(runtime_dir))
        logger.info(f"runtime 已安装到 {runtime_dir}")

        # 清理
        shutil.rmtree(tmp_dir, ignore_errors=True)

        # 验证
        if is_runtime_complete():
            logger.success("runtime 环境就绪")
            return True
        else:
            logger.error("runtime 安装后验证失败")
            return False

    except Exception as e:
        logger.error(f"runtime 下载失败: {e}")
        # 清理临时文件
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return False


def ensure_runtime(progress_callback=None) -> bool:
    """确保 runtime 环境可用，缺失则自动下载

    Returns:
        runtime 是否可用
    """
    if is_runtime_complete():
        return True
    logger.info("runtime 环境不完整，开始自动下载...")
    return download_runtime(progress_callback=progress_callback)


def get_runtime_status() -> dict:
    """获取 runtime 环境状态信息"""
    runtime_dir = get_runtime_dir()
    python_exe = get_python_exe()
    ffmpeg = get_ffmpeg_path()

    status = {
        "runtime_dir": str(runtime_dir),
        "runtime_exists": runtime_dir.exists(),
        "python_exists": python_exe.exists(),
        "python_version": "",
        "ffmpeg_exists": ffmpeg.exists(),
        "ffmpeg_size": ffmpeg.stat().st_size if ffmpeg.exists() else 0,
        "engine_exists": has_engine_backend(),
        "complete": is_runtime_complete(),
    }

    if python_exe.exists():
        try:
            result = subprocess.run(
                [str(python_exe), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                status["python_version"] = result.stdout.strip()
        except Exception:
            pass

    return status


if __name__ == "__main__":
    # 命令行测试
    import json
    status = get_runtime_status()
    print(json.dumps(status, indent=2, ensure_ascii=False))
    if not status["complete"]:
        print("\nruntime 不完整，开始下载...")
        ok = ensure_runtime()
        print(f"下载结果: {ok}")
