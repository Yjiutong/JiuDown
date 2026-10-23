"""
Runtime 环境自举管理

启动时自检 runtime/ 目录：
- 完整 → 直接使用 runtime/python/python.exe 运行
- 缺失/不完整 → 用仓库内随附的组件包（build_components/）离线补齐；
                组件包缺失时才从 GitHub Release 下载

runtime 目录结构：
  runtime/
  ├── python/              嵌入式 Python 3.12 + site-packages
  │   ├── python.exe
  │   ├── python312.dll
  │   └── Lib/site-packages/
  └── ffmpeg.exe           精简版 FFmpeg（由 ffmpeg_manager 放置）
"""

import hashlib
import json
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

# 完整性检查：这些文件必须存在
# 注意：ffmpeg.exe 不在此列。它由 ffmpeg_manager 独立管理（优先 runtime/ffmpeg.exe，
# 其次 resources/ffmpeg.exe，缺失时自动下载），也不进任何组件包；若把它算作 runtime
# 完整性的一部分，组件化安装出来的新 runtime 会被永远判为不完整、每次启动重复拉取。
REQUIRED_FILES = [
    "python/python.exe",
    "python/python312.dll",
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


# ---------------------------------------------------------------- 组件化安装
# runtime 被拆成 core / pyside-N / engine / app 若干组件（各自 < 100MB）。
# 组件包随仓库一起分发（build_components/），首次安装**离线即可完成**；
# Release 只是可选的更新镜像：本地包缺失或 sha256 对不上时才去下载。

COMPONENT_ASSET_BASE = RUNTIME_RELEASE_URL.rsplit("/", 1)[0]
COMPONENT_MANIFEST_URL = f"{COMPONENT_ASSET_BASE}/manifest.json"
COMPONENT_STATE_FILE = "component_state.json"
COMPONENT_DIR_NAME = "build_components"


def _release_asset_url(filename: str) -> str:
    return f"{COMPONENT_ASSET_BASE}/{filename}"


def get_component_dir() -> Path:
    """仓库内随附的组件目录（离线安装用）

    打包后 build_components 会被 PyInstaller 解到 _MEIPASS，故两处都找。
    """
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / COMPONENT_DIR_NAME)
    candidates.append(get_base_dir() / COMPONENT_DIR_NAME)
    for path in candidates:
        if (path / "manifest.json").exists():
            return path
    return candidates[-1]


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def local_component_zip(name: str, meta: dict) -> Path | None:
    """仓库内是否随附有该组件，且 sha256 与清单一致（不一致视为过期包，仍走下载）"""
    path = get_component_dir() / (meta.get("file") or f"{name}.zip")
    if not path.exists():
        return None
    expected = (meta.get("sha256") or "").lower()
    if expected and _sha256_of(path) != expected:
        logger.warning(f"仓库内组件 {name} 校验不匹配，改用 Release 上的包")
        return None
    return path


def component_marker_present(group: str) -> bool:
    """该组件组是否已安装（用组内标志文件判断）"""
    from runtime_components import GROUP_MARKERS  # noqa: PLC0415

    rel = GROUP_MARKERS.get(group)
    return bool(rel) and (get_runtime_dir() / rel).exists()


def load_local_manifest() -> dict | None:
    """读取仓库内随附的组件清单（离线安装用）"""
    path = get_component_dir() / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.warning(f"仓库内组件清单无法解析（{path}）：{e}")
        return None
    if not isinstance(data.get("components"), dict) or not data["components"]:
        logger.warning("仓库内组件清单格式不正确，忽略")
        return None
    return data


def fetch_component_manifest(timeout: int = 30, local_first: bool = True) -> dict | None:
    """获取组件清单：优先用仓库内随附的那份，拿不到再问 Release

    local_first=False 时强制走网络（用于「检查更新」这类场景）。
    """
    if local_first:
        local = load_local_manifest()
        if local:
            return local
    try:
        import requests  # noqa: PLC0415

        resp = requests.get(COMPONENT_MANIFEST_URL, timeout=timeout)
        if resp.status_code != 200:
            logger.info(f"组件清单不可用（HTTP {resp.status_code}），回退整包运行时")
            return None
        data = resp.json()
        if not isinstance(data.get("components"), dict) or not data["components"]:
            logger.info("组件清单格式不正确，回退整包运行时")
            return None
        return data
    except Exception as e:
        logger.info(f"获取组件清单失败（{e}），回退整包运行时")
        return None


def _download_file(url: str, dest: Path, expected_sha256: str, progress_callback=None) -> None:
    """下载单个组件并校验 sha256（不匹配直接抛错，避免半包污染运行时）"""
    import requests  # noqa: PLC0415

    with requests.get(url, stream=True, timeout=(15, 300)) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        got = 0
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                fh.write(chunk)
                got += len(chunk)
                if progress_callback:
                    progress_callback(got, total)

    if expected_sha256:
        digest = hashlib.sha256()
        with open(dest, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != expected_sha256.lower():
            raise RuntimeError(f"组件校验失败: {dest.name}")


def install_component_group(group: str, manifest: dict, progress_callback=None) -> bool:
    """安装/覆盖一个组件组（组内可能有多个 zip，如 pyside-1/2/3）"""
    comps = {
        name: meta for name, meta in manifest.get("components", {}).items()
        if meta.get("group", name.split("-")[0]) == group
    }
    if not comps:
        logger.warning(f"组件清单里没有 {group}")
        return False

    runtime_dir = get_runtime_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"jiudown_{group}_"))
    try:
        for name, meta in comps.items():
            url = _release_asset_url(meta.get("file") or f"{name}.zip")
            size_mb = (meta.get("size") or 0) / 1024 / 1024
            local = local_component_zip(name, meta)
            if local is not None:
                logger.info(f"使用仓库内组件 {name}（{size_mb:.1f} MB）: {local}")
                zip_path = local
            else:
                logger.info(f"下载组件 {name}（{size_mb:.1f} MB）: {url}")
                zip_path = tmp_dir / (meta.get("file") or f"{name}.zip")
                _download_file(url, zip_path, meta.get("sha256", ""), progress_callback)
            logger.info(f"解压组件 {name} …")
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(runtime_dir)
        _save_component_state(manifest, group)
        logger.success(f"组件 {group} 安装完成")
        return True
    except Exception as e:
        logger.error(f"组件 {group} 安装失败: {e}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _save_component_state(manifest: dict, installed_group: str) -> None:
    """记录已安装的组件构建号，便于排查版本不一致"""
    try:
        state_path = get_runtime_dir() / COMPONENT_STATE_FILE
        state = {}
        if state_path.exists():
            import json  # noqa: PLC0415

            state = json.loads(state_path.read_text(encoding="utf-8") or "{}")
        import json  # noqa: PLC0415

        state.setdefault("groups", {})[installed_group] = {
            "build": manifest.get("build", ""),
            "engine_version": manifest.get("engine_version", ""),
        }
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug(f"写入组件状态失败（忽略）: {e}")


def update_engine_component(progress_callback=None) -> tuple[bool, str]:
    """只更新下载引擎组件（几 MB），不再重下整个运行时

    「更新引擎」要拿的是**最新**的引擎，所以先问 Release；网络不可用时
    退化到仓库内随附的那份（离线也能修好一个坏掉的引擎）。

    Returns:
        (是否成功, 引擎版本或失败原因)
    """
    manifest = fetch_component_manifest(local_first=False) or load_local_manifest()
    if not manifest:
        return False, "未找到组件清单（Release 与仓库内都没有 manifest.json）"
    if not install_component_group("engine", manifest, progress_callback):
        return False, "引擎组件下载或校验失败"
    return True, str(manifest.get("engine_version") or "")


def ensure_runtime(progress_callback=None) -> bool:
    """确保 runtime 环境可用

    优先按组件清单补齐缺失项（增量、每个组件 < 100MB）。清单默认取仓库内
    随附的那份，组件 zip 也在仓库里 → 克隆下来断网也能装好。
    """
    if is_runtime_complete():
        return True

    manifest = fetch_component_manifest()
    if manifest:
        groups = manifest.get("groups") or ["core", "pyside", "engine", "app"]
        missing = [g for g in groups if not component_marker_present(g)]
        if missing:
            logger.info(f"缺失组件: {', '.join(missing)}（共 {len(missing)} 组），开始按组件拉取…")
            for group in missing:
                if not install_component_group(group, manifest, progress_callback):
                    logger.warning(f"组件 {group} 安装失败，回退整包运行时")
                    break
            else:
                if is_runtime_complete():
                    return True
        else:
            logger.info("组件文件齐全但完整性校验未通过，回退整包运行时")

    logger.info("runtime 环境不完整，开始下载整包 runtime.zip ...")
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
