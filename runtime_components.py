"""
运行时组件划分（打包端与运行端共用）

背景
----
runtime 目录约 886 MB，压成一个 runtime.zip 约 339 MB。每次只改了几十 KB 的
yt-dlp 提取器，用户却要重新拉 339 MB —— 不合理。

拆法
----
把 runtime 按"功能 + 体积"切成若干独立组件，每个压缩包 < 100 MB：

    core      Python 解释器 + 标准库                       （几乎不变）
    pyside-N  PySide6（剥离 WebEngine/Pdf/Quick/Qml 等）    （随 UI 改动变）
    engine    yt-dlp 与其依赖                              （每周都可能变，只拉这个）
    app       应用运行依赖（requests/loguru/pyyaml/...）    （很少变）

ffmpeg.exe（161 MB）不进组件：由 ffmpeg_manager 单独下载与管理。

发布时把各组件 zip 和 manifest.json 一起传到 release 的 runtime 标签下，
运行端按 manifest 只补缺失/过期的组件。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

# 组件 zip 的体积上限（用户要求每个组件小于 100 MB）
MAX_COMPONENT_BYTES = 100 * 1024 * 1024

# 单个 pyside 分包的目标上限（未压缩），压缩后大约是它的一半
PYSIDE_PART_BYTES = 90 * 1024 * 1024

# ---- site-packages 下的包归属 ----
PYSIDE_PACKAGES = ("PySide6", "shiboken6")

ENGINE_PACKAGES = (
    "yt_dlp",
    "Cryptodome",
    "mutagen",
    "websockets",
    "brotli",
    "yt_dlp_ejs",
    "cffi",
    "pycparser",
    "_cffi_backend.cp312-win_amd64.pyd",
    "_cffi_backend.cp313-win_amd64.pyd",
    "decorator",
)

APP_PACKAGES = (
    "requests",
    "urllib3",
    "idna",
    # certifi 必须在 app 组：requests 直接 import 它（engine 组也依赖，但由 app 组提供）
    "certifi",
    "charset_normalizer",
    "loguru",
    "yaml",
    "psutil",
    "colorama",
    "win32_setctime",
    "pywin32",
)

# PySide6 里确认用不到的模块（代码只 import QtCore/QtGui/QtWidgets/QtMultimedia/QtMultimediaWidgets）
# 剥离后约省 420 MB；用 --keep-all 打包可完整保留
PYSIDE_DROP_PREFIXES = (
    "Qt6WebEngine", "Qt6Pdf", "Qt6Quick", "Qt6Qml", "Qt63D", "Qt6Charts",
    "Qt6DataVisualization", "Qt6Designer", "Qt6Help", "Qt6Sql", "Qt6Test",
    "Qt6Bluetooth", "Qt6Nfc", "Qt6Positioning", "Qt6Sensors", "Qt6SerialPort",
    "Qt6WebSockets", "Qt6WebChannel", "Qt6SpatialAudio", "Qt6TextToSpeech",
    "Qt6Scxml", "Qt6RemoteObjects", "Qt6StateMachine", "Qt6Graphs",
    "Qt6MultimediaQuick", "Qt6Location", "Qt6Concurrent", "Qt6OpenGL",
    "Qt6QmlModels", "Qt6QmlWorkerScript", "Qt6QuickWidgets", "Qt6QuickControls2",
    "Qt6QuickTemplates2", "Qt6QuickLayouts", "Qt6QuickDialogs2",
)
PYSIDE_DROP_HINTS = ("webengine", "qtwebengine", "devtools_resources", "v8_context_snapshot")


def _is_pyside_dropped(rel_in_pyside: str) -> bool:
    name = rel_in_pyside.split("/")[-1]
    if name.startswith(PYSIDE_DROP_PREFIXES):
        return True
    low = rel_in_pyside.lower()
    return any(h in low for h in PYSIDE_DROP_HINTS)


# ---- 组件分组：一个组可能对应多个 zip（PySide6 按体积切分） ----
GROUP_MARKERS = {
    "core": "python/python.exe",
    "pyside": "python/Lib/site-packages/PySide6/Qt6Widgets.pyd",
    "engine": "python/Lib/site-packages/yt_dlp/__init__.py",
    "app": "python/Lib/site-packages/loguru/__init__.py",
}


def group_of(component_name: str) -> str:
    """组件 zip 名 → 组名（pyside-2 → pyside）"""
    return component_name.split("-")[0]


def classify(rel: str, *, strip_pyside: bool = True) -> str | None:
    """判断 runtime 内某文件归属哪个组件；None 表示不打包

    Args:
        rel: 相对 runtime 目录的路径（用 / 分隔）
        strip_pyside: 是否剥离 PySide6 中用不到的模块
    """
    rel = rel.replace("\\", "/")
    if not rel or rel.endswith("/"):
        return None
    if "__pycache__/" in rel or rel.endswith(".pyc"):
        return None

    # ffmpeg / 旧核心 exe 不进组件（ffmpeg 由 ffmpeg_manager 独立管理）
    if rel == "ffmpeg.exe" or rel.endswith(".exe") and not rel.startswith("python/"):
        return None

    if rel.startswith("python/Lib/site-packages/"):
        parts = rel.split("/")
        pkg = parts[3] if len(parts) > 3 else ""
        if pkg in PYSIDE_PACKAGES:
            if strip_pyside:
                inner = "/".join(parts[3:])
                if _is_pyside_dropped(inner):
                    return None
            return "pyside"
        if pkg in ENGINE_PACKAGES or pkg.startswith("yt_dlp-") or pkg.startswith("mutagen-"):
            return "engine"
        if pkg in APP_PACKAGES or pkg.endswith(".dist-info") or pkg.endswith(".egg-info"):
            return "app"
        # 其他零散小包（尺寸都在 1MB 以下）并入 app，避免组件碎片化
        return "app"

    if rel.startswith("python/"):
        # 解释器本体：python.exe / DLLs / Lib 标准库 / tcl 等
        return "core"

    return None


def iter_component_files(runtime_dir: Path, *, strip_pyside: bool = True) -> dict[str, list[Path]]:
    """按组件收集文件（pyside 先归为一个大组，稍后再按体积切分）"""
    buckets: dict[str, list[Path]] = {}
    runtime_dir = Path(runtime_dir)
    for path in runtime_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(runtime_dir).as_posix()
        name = classify(rel, strip_pyside=strip_pyside)
        if not name:
            continue
        buckets.setdefault(name, []).append(path)
    return buckets


def split_by_size(files: Iterable[Path], limit: int) -> list[list[Path]]:
    """按累计体积切分（保持稳定顺序，便于增量比对）"""
    parts: list[list[Path]] = []
    current: list[Path] = []
    current_size = 0
    for f in sorted(files, key=lambda p: str(p)):
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if current and current_size + size > limit:
            parts.append(current)
            current, current_size = [], 0
        current.append(f)
        current_size += size
    if current:
        parts.append(current)
    return parts


# ---------------------------------------------------------------- manifest

def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            data = fh.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def build_manifest(components: dict[str, dict], *, build: str, engine_version: str = "") -> dict:
    """生成 manifest.json 结构

    components: {name: {"file": 文件名, "size": 字节, "sha256": ..., "files": 文件数}}
    每个组件会自动补上 group 字段（pyside-2 → pyside），运行端按组判断是否已安装。
    """
    payload: dict[str, dict] = {}
    for name, meta in components.items():
        item = dict(meta)
        item.setdefault("group", group_of(name))
        payload[name] = item

    return {
        "schema": 1,
        "build": build,
        "engine_version": engine_version,
        "max_component_bytes": MAX_COMPONENT_BYTES,
        "groups": list(GROUP_MARKERS.keys()),
        "components": payload,
    }


def dump_manifest(manifest: dict, path: Path) -> None:
    Path(path).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
