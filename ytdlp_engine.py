"""
yt-dlp 下载引擎封装（站点无关）

设计目标
- 本项目不再内置任何站点私有接口：解析、格式选择、分片下载、合并全部交给 yt-dlp，
  因此 B 站、YouTube、X、抖音、Vimeo 等 yt-dlp 支持的站点走同一条链路。
- 对外只暴露四个能力：
    probe(url)                     解析元数据（标题/时长/站点/缩略图），用于任务卡展示
    download(...)                  按画质/格式下载，进度经 hook 回调
    resolve_stream(url, prefer)    取一条可直接播放的直链 + 请求头，供预览面板/悬停小窗使用
    available()/version()          引擎自检，用于首页状态与错误提示
- 所有 YouTubeDL 参数都从 config_manager 派生（代理 / Cookie / 限速 / 播放列表上限），
  业务层不直接接触 yt-dlp 选项字典。

线程模型
- extract_info / download 都是阻塞调用，必须在后台线程执行（download_manager 用
  asyncio.to_thread，预览模块用 threading.Thread）。
- yt-dlp 的 progress hook 在下载线程内被调用；回调实现必须自己保证线程安全。
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from loguru import logger

# 画质档位 → 期望的最大视频高度（None = 不限制，取最高）
# 这里是「用户想要的档位」，不是「视频提供的档位」；后者见 list_levels()
QUALITY_HEIGHTS: dict[str, Optional[int]] = {
    "最高": None,
    "4K": 2160,
    "2K": 1440,
    "1080P": 1080,
    "720P": 720,
    "480P": 480,
    "360P": 360,
}
DEFAULT_QUALITY = "720P"
QUALITY_CHOICES = list(QUALITY_HEIGHTS.keys())

AUDIO_FORMATS = {"mp3", "wav"}
VIDEO_FORMATS = {"mp4", "flv", "mkv", "webm"}
FORMAT_CHOICES = ["mp4", "flv", "mp3", "wav"]

# Cookie 来源下拉的可选值（与 settings_page 保持一致）
COOKIE_BROWSERS = ["不使用", "chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium"]

_ydl_lock = threading.Lock()
_ydl_module: Any = None
_version_cache: Optional[str] = None
_site_count_cache: Optional[int] = None
_site_thread: Optional[threading.Thread] = None


# =====================================================================
# 引擎自检
# =====================================================================


def _load_module():
    """延迟导入 yt_dlp（缺失时抛可读异常，而不是在模块导入期崩溃）"""
    global _ydl_module
    if _ydl_module is None:
        with _ydl_lock:
            if _ydl_module is None:
                import yt_dlp  # noqa: PLC0415

                _ydl_module = yt_dlp
    return _ydl_module


def available() -> bool:
    """引擎是否可用（yt-dlp Python 包是否已安装）"""
    if _ydl_module is not None:
        return True
    return importlib.util.find_spec("yt_dlp") is not None


def version() -> str:
    """引擎版本号；不可用时返回空串

    优先读包元数据（毫秒级），避免在启动路径上 import 整个 yt_dlp 包（较重）。
    """
    global _version_cache
    if _version_cache is not None:
        return _version_cache
    try:
        from importlib.metadata import version as pkg_version  # noqa: PLC0415

        _version_cache = pkg_version("yt-dlp")
    except Exception:
        try:
            if _ydl_module is None and not available():
                _version_cache = ""
            else:
                from yt_dlp.version import __version__ as v  # noqa: PLC0415

                _version_cache = str(v)
        except Exception:
            _version_cache = ""
    return _version_cache or ""


def supported_site_count() -> int:
    """yt-dlp 内置提取器数量（≈ 支持站点数），结果缓存

    首次统计需要遍历 ~2000 个提取器（约 0.3~0.8s），不要在主线程直接调用，
    优先用 request_site_count() 预热 + 轮询。
    """
    global _site_count_cache
    if _site_count_cache is not None:
        return _site_count_cache
    try:
        from yt_dlp.extractor import gen_extractor_classes  # noqa: PLC0415

        count = sum(1 for _ in gen_extractor_classes())
        _site_count_cache = int(count)
    except Exception as e:
        logger.debug(f"统计 yt-dlp 支持站点数失败（忽略）: {e}")
        _site_count_cache = 0
    return _site_count_cache or 0


def request_site_count() -> Optional[int]:
    """非阻塞取站点数：已就绪直接返回，否则起一次后台预热并返回 None

    刻意不用「后台线程 → Qt 信号」的写法：页面销毁后线程仍可能回调，
    会造成悬空对象访问（段错误）。改为主线程轮询一个纯数据缓存，最安全。
    """
    global _site_thread
    if _site_count_cache is not None:
        return _site_count_cache
    if _site_thread is None or not _site_thread.is_alive():
        _site_thread = threading.Thread(
            target=supported_site_count, name="ytdlp-site-count", daemon=True
        )
        _site_thread.start()
    return None


class EngineError(RuntimeError):
    """引擎层可读错误：直接展示给用户，不带 yt-dlp 的堆栈噪声"""


# 从微信/QQ/网页复制时常见的不可见字符。它们不算 str.isspace()，strip() 去不掉，
# 会让"看起来是纯链接"的一行判定失败。用显式转义而不是字面字符：这些字符写在源码里
# 根本看不见，接手的人无从判断。
# 零宽字符直接删；不换行空格/全角空格是分隔符，必须换成普通空格，
# 否则 "…/abc\u00a0tail" 会被粘成一个不存在的 URL。
_ZERO_WIDTH_RE = re.compile("[\\u200b-\\u200f\\u202a-\\u202e\\u2060\\ufeff]")
_SPACE_LIKE_RE = re.compile("[\\u00a0\\u3000]")
# URL 只由 ASCII 合法字符组成：字符集写宽了会把紧跟其后的中文（"…abc123，快来看"）
# 一起吞进来，而 rstrip 只能去尾巴、去不掉夹在中间的标点。
_URL_CHARS = r"A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%"
_URL_RE = re.compile(f"https?://[{_URL_CHARS}]+", re.IGNORECASE)
_BARE_HOST_RE = re.compile(f"(?:https?://)?[\\w-]+(?:\\.[\\w-]+)+(?::\\d+)?(?:[{_URL_CHARS}]+)?")


# 分享文本里 URL 常被括号或句号包着，末尾这些符号不属于地址本身
_TRAILING_JUNK = ".,;:!?)]}'”’"

_BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AV_RE = re.compile(r"\bav(\d{4,})", re.IGNORECASE)


def normalize_url(raw: str) -> str:
    """从一行文本里取出视频链接；取不到时返回空串

    容忍三种真实输入：粘贴时混进零宽字符/BOM；链接前后带着标题或
    「来自 微博网页版」这类分享尾巴；只有域名没有协议（www.bilibili.com/video/BV…）。
    B 站分享文本经常只带 BV/av 号不带链接，这种情况直接拼出视频页地址——
    否则用户粘贴标题看到"没有识别到链接"，完全不知道哪里不对。
    """
    text = _SPACE_LIKE_RE.sub(" ", _ZERO_WIDTH_RE.sub("", raw or "")).strip().strip("\"'“”‘’")
    if not text:
        return ""
    match = _URL_RE.search(text)
    if match:
        return match.group().rstrip(_TRAILING_JUNK)
    match = _BARE_HOST_RE.search(text)
    if match:
        url = match.group()
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        return url.rstrip(_TRAILING_JUNK)
    bv = _BV_RE.search(text)
    if bv:
        return f"https://www.bilibili.com/video/{bv.group(1)}"
    av = _AV_RE.search(text)
    if av:
        return f"https://www.bilibili.com/video/av{av.group(1)}"
    return ""


# =====================================================================
# 日志桥接
# =====================================================================


class _LoguruBridge:
    """把 yt-dlp 的日志转发到 loguru（避免它直接 print 到不存在的控制台）"""

    _PREFIX = {
        "DEBUG": "debug",
        "INFO": "info",
        "WARNING": "warning",
        "ERROR": "error",
    }

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug] "):
            logger.opt(depth=1).debug(msg[8:])
        else:
            logger.opt(depth=1).debug(msg)

    def info(self, msg: str) -> None:
        logger.opt(depth=1).debug(msg)

    def warning(self, msg: str) -> None:
        logger.opt(depth=1).warning(msg)

    def error(self, msg: str) -> None:
        logger.opt(depth=1).error(msg)


# =====================================================================
# 由配置构造选项
# =====================================================================


def _ffmpeg_location() -> Optional[str]:
    """FFmpeg 路径：优先配置项，其次 PATH"""
    try:
        from config_manager import config_manager  # noqa: PLC0415

        path = config_manager.get_ffmpeg_path()
    except Exception:
        path = ""
    if path and Path(path).exists():
        return str(Path(path).parent if Path(path).is_file() else Path(path))
    # 配置路径不存在时退回运行时自带的 ffmpeg（与 ffmpeg_manager 同目录）
    try:
        import ffmpeg_manager  # noqa: PLC0415

        resolved = Path(ffmpeg_manager.get_ffmpeg_path())
        if resolved.exists():
            return str(resolved.parent)
    except Exception:
        pass
    return None


def _config_get(key: str, default):
    try:
        from config_manager import config_manager  # noqa: PLC0415

        value = config_manager.get_config(key)
        return default if value is None else value
    except Exception:
        return default


def _base_opts(progress_hooks: Optional[list] = None,
               postprocessor_hooks: Optional[list] = None) -> dict:
    """公共 YouTubeDL 参数：代理 / Cookie / 限速 / 并发分片 / 播放列表上限"""
    limit_bytes = 0
    try:
        limit_bytes = int(_config_get("download_speed_limit", 0) or 0)
    except Exception:
        limit_bytes = 0

    playlist_limit = 1
    try:
        playlist_limit = int(_config_get("playlist_limit", 1) or 1)
    except Exception:
        playlist_limit = 1
    playlist_limit = max(1, min(playlist_limit, 500))

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _LoguruBridge(),
        "noplaylist": playlist_limit <= 1,
        "socket_timeout": 20,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 2,
        "trim_file_name": 120,
        "windowsfilenames": True,
        "consoletitle": False,
        "call_home": False,
        "cachedir": False,
        "ignoreerrors": False,
        "concurrent_fragment_downloads": 4,
    }
    if playlist_limit > 1:
        opts["playlistend"] = playlist_limit

    ffmpeg = _ffmpeg_location()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg

    if limit_bytes > 0:
        opts["ratelimit"] = limit_bytes

    proxy = str(_config_get("proxy", "") or "").strip()
    if proxy:
        opts["proxy"] = proxy

    browser = str(_config_get("cookies_from_browser", "不使用") or "不使用").strip()
    cooked = _cookie_file()
    if browser and browser not in ("不使用", "none", "off"):
        # yt-dlp 期望四元组 (browser, profile, keyring, container)
        opts["cookiesfrombrowser"] = (browser, None, None, None)
    elif cooked:
        opts["cookiefile"] = cooked

    if progress_hooks:
        opts["progress_hooks"] = list(progress_hooks)
    if postprocessor_hooks:
        opts["postprocessor_hooks"] = list(postprocessor_hooks)
    return opts


def _cookie_file() -> Optional[str]:
    """配置里手填的 cookie 文本落成临时 cookies.txt（Netscape 格式）"""
    raw = ""
    try:
        from config_manager import config_manager  # noqa: PLC0415

        info = config_manager.get_user_info() or {}
        raw = str(info.get("raw-cookies") or info.get("cookies") or "").strip()
    except Exception:
        return None
    if not raw:
        return None
    try:
        from system_info import system_info  # noqa: PLC0415

        target = Path(system_info.get_config_dir()) / "cookies.txt"
        lines = ["# Netscape HTTP Cookie File"]
        if raw.startswith("{"):
            import json  # noqa: PLC0415

            pairs = (json.loads(raw) or {}).items()
        else:
            pairs = []
            for part in raw.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    pairs.append((k.strip(), v.strip()))
        for k, v in pairs:
            lines.append(f".youtube.com\tTRUE\t/\tTRUE\t0\t{k}\t{v}")
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(target)
    except Exception as e:
        logger.debug(f"写入 cookies.txt 失败（忽略）: {e}")
        return None


# =====================================================================
# 格式选择
# =====================================================================


def format_selector(quality: str, file_format: str) -> str:
    """画质档位 + 输出格式 → yt-dlp format 选择器

    - 纯音频：只要音频流（bestaudio），后续由 FFmpegExtractAudio 转码
    - 视频：优先「视频流+音频流」合并，逐级降级到单文件流，最终兜底 best
    """
    if file_format in AUDIO_FORMATS:
        return "bestaudio/best"
    height = QUALITY_HEIGHTS.get(quality, 720)
    if height is None:
        return "bestvideo*+bestaudio/best"
    return (
        f"bestvideo[height<={height}]+bestaudio/"
        f"best[height<={height}]/"
        f"bestvideo[height<={height}]+bestaudio/best"
    )


def level_format(level: Optional[dict], quality: str, file_format: str) -> str:
    """已解析出具体档位时按该档位的流走，否则退回按档位名近似匹配

    显式档位一律「精确档」：宁可报错也不要用 height<= 的天花板写法——那会让
    「选了 1080P、账号只能给 480P」静默下成 480P，正是本功能要消灭的行为。
    档位也可能来自另一个后端（B 站原生只给 height，没有 selector），所以这里
    必须能吃 height，否则跨后端降级时会被 format_selector 猜成默认 720P。
    """
    if file_format in AUDIO_FORMATS:
        return "bestaudio/best"
    selector = str((level or {}).get("selector") or "")
    if selector:
        return selector
    height = int((level or {}).get("pixels") or level.get("height") or 0) if level else 0
    if height:
        return f"bestvideo[height={height}]+bestaudio/best[height={height}]"
    return format_selector(quality, file_format)


# =====================================================================
# 该链接实际提供的清晰度档位
# =====================================================================


def short_edge(fmt: dict) -> int:
    """短边像素：竖屏视频（1080x1920）按 1080 归档，不会被误标成 2K"""
    h = int(fmt.get("height") or 0)
    w = int(fmt.get("width") or 0)
    if h and w:
        return min(h, w)
    return h or w


def fps_of(fmt: dict) -> int:
    try:
        return int(round(float(fmt.get("fps") or 0)))
    except (TypeError, ValueError):
        return 0


def bitrate_of(fmt: dict) -> float:
    for key in ("tbr", "bitrate", "vbr", "abr"):
        value = fmt.get(key)
        try:
            if value:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def level_label(height: Optional[int], fps: int = 0, hdr: bool = False) -> str:
    """(短边高度, 帧率, HDR) → 档位名，与站点播放器的叫法对齐"""
    h = int(height or 0)
    if h >= 2160:
        base = "4K"
    elif h >= 1440:
        base = "2K"
    elif h > 0:
        base = f"{h}P"
    else:
        base = "未知"
    if fps >= 50:
        base = f"{base} {fps}帧"
    if hdr:
        base = f"{base} HDR"
    return base


def build_levels(info: dict) -> list[dict]:
    """yt-dlp 的 formats 列表 → 本视频真实可选的档位

    同一 (短边高度, 帧率, 动态范围) 下往往有 avc1/vp9/av01 多条流：取码率最高的
    那条。「1080P 高码率」这类档位只有按码率选才会浮现，按默认 bestvideo 排序
    会优先给到编码更省的新 codec，高码率档等于被吞掉。
    """
    formats = info.get("formats") or []
    videos = [f for f in formats
              if (f.get("vcodec") or "none") != "none" and f.get("format_id")]
    if not videos:
        return []
    audios = [f for f in formats
              if (f.get("acodec") or "none") != "none" and f.get("format_id")]
    # YouTube 的 *-drc 是响度压缩过的副本，码率更高但不是原声
    plain = [f for f in audios if "-drc" not in str(f.get("format_id"))]
    best_audio = max(plain or audios, key=bitrate_of) if audios else None

    groups: dict[tuple, list[dict]] = {}
    for fmt in videos:
        key = (short_edge(fmt), fps_of(fmt), str(fmt.get("dynamic_range") or "").upper())
        groups.setdefault(key, []).append(fmt)

    levels: list[dict] = []
    for (height, fps, drange), group in groups.items():
        best = max(group, key=bitrate_of)
        hdr = "HDR" in drange
        video_id = str(best.get("format_id"))
        if best_audio is not None and best_audio is not best:
            selector = f"{video_id}+{best_audio['format_id']}"
        else:
            selector = video_id
        # 站点偶发换 format id（解析后重取）：兜底链也锁死同一高度，不允许降档
        pixels = int(best.get("height") or height or 0)
        if pixels:
            selector += f"/bestvideo[height={pixels}]+bestaudio/best[height={pixels}]"
        levels.append({
            "label": level_label(height, fps, hdr),
            "height": height,
            "pixels": pixels,
            "fps": fps,
            "hdr": hdr,
            "selector": selector,
            "qn": None,
            "available": True,
            "reason": "",
        })
    levels.sort(key=lambda lv: (lv["height"], lv["fps"]), reverse=True)
    _dedupe_labels(levels)
    return levels


def _dedupe_labels(levels: list[dict]) -> None:
    """同分辨率不同帧率（144P 的 15帧 / 30帧两条）会撞名：补帧率区分"""
    counts: dict[str, int] = {}
    for level in levels:
        counts[level["label"]] = counts.get(level["label"], 0) + 1
    for level in levels:
        label = level["label"]
        if counts[label] > 1 and level["fps"] and str(level["fps"]) not in label:
            level["label"] = f"{label} {level['fps']}帧"


def pick_default_level(levels: list[dict], tier: Optional[str]) -> Optional[dict]:
    """把设置的默认档位落到视频真实提供的档位上

    - 默认高于视频最高档 → 取视频最高档（默认 1080P 但老片只有 480P 的场景）
    - 默认低于视频最低档 → 取视频最低档（不下探到不存在的档）
    - 只在实际能取到的档位里挑（B 站未登录时 1080P 是「有但拿不到」）
    """
    usable = [lv for lv in levels if lv.get("available", True)] or list(levels or [])
    if not usable:
        return None
    usable.sort(key=lambda lv: (int(lv.get("height") or 0), int(lv.get("fps") or 0)))
    limit = QUALITY_HEIGHTS.get(str(tier or ""), QUALITY_HEIGHTS[DEFAULT_QUALITY])
    if limit is None:
        return usable[-1]
    at_or_below = [lv for lv in usable if int(lv.get("height") or 0) <= limit]
    return at_or_below[-1] if at_or_below else usable[0]


_AUDIO_CODEC = {"mp3": "libmp3lame", "wav": "pcm_s16le"}


def _ffmpeg_exe() -> str:
    """取 ffmpeg 可执行文件路径（与 ffmpeg_manager 保持一致）"""
    try:
        import ffmpeg_manager  # noqa: PLC0415

        path = str(ffmpeg_manager.get_ffmpeg_path())
        if Path(path).exists():
            return path
    except Exception:
        pass
    location = _ffmpeg_location()
    if location:
        candidate = Path(location) / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        if candidate.exists():
            return str(candidate)
    return "ffmpeg"


def _ffmpeg_convert(
    source: Path,
    target: Path,
    file_format: str,
    channels: str = "双声道",
) -> Path:
    """用应用自带的 ffmpeg 转封装/转码

    为什么不用 yt-dlp 的 FFmpegExtractAudio：它依赖 ffprobe 探测编码格式，而应用
    内置的 ffmpeg 是单文件版本（不含 ffprobe），会报 "unable to obtain file audio
    codec with ffprobe"。这里直接按目标编码调用 ffmpeg，行为可控且无需额外依赖。
    """
    exe = _ffmpeg_exe()
    if file_format in AUDIO_FORMATS:
        cmd = [exe, "-y", "-i", str(source), "-vn",
               "-c:a", _AUDIO_CODEC.get(file_format, "libmp3lame"),
               "-ac", "1" if channels == "单声道" else "2",
               str(target)]
    else:
        # flv：仅重封装，不重编码
        cmd = [exe, "-y", "-i", str(source), "-c", "copy", str(target)]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60 * 60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode != 0 or not target.exists():
        stderr = proc.stderr or ""
        if "does not contain any stream" in stderr:
            raise EngineError("该视频没有音频轨，无法导出 mp3/wav")
        tail = stderr.strip().splitlines()[-1:]
        reason = tail[0] if tail else "未知错误"
        if file_format in AUDIO_FORMATS and channels == "单声道":
            # 精简版 ffmpeg 缺少音频重采样时单声道会失败：降级双声道再试一次
            logger.warning(f"单声道转换失败，降级双声道重试: {reason}")
            return _ffmpeg_convert(source, target, file_format, "双声道")
        raise EngineError(f"{file_format} 转换失败：{reason}")
    return target


# =====================================================================
# 解析
# =====================================================================


def _clean_info(info: dict) -> dict:
    """从 yt-dlp 的 info dict 提取应用需要的字段"""
    entries = info.get("entries")
    if entries:
        # 播放列表：取第一条作为任务代表（多条目下载由 playlistend 控制）
        first = next((e for e in entries if e), None)
        base = dict(info)
        if first:
            base.update({k: v for k, v in first.items() if v is not None and k not in base})
        info = base
        playlist_count = len(list(info.get("entries") or []))
    else:
        playlist_count = 0

    return {
        "id": str(info.get("id") or ""),
        "title": str(info.get("title") or info.get("id") or "未命名"),
        "uploader": str(info.get("uploader") or info.get("channel") or ""),
        "duration": int(info.get("duration") or 0),
        "thumbnail": str(info.get("thumbnail") or ""),
        "webpage_url": str(info.get("webpage_url") or info.get("original_url") or ""),
        "extractor": str(info.get("extractor_key") or info.get("extractor") or ""),
        "is_live": bool(info.get("is_live")),
        "playlist_count": playlist_count,
    }


def probe(url: str, timeout: int = 30) -> dict:
    """解析链接元数据（不下载）

    Raises:
        EngineError: 引擎缺失 / 链接不受支持 / 网络错误，带可直接展示的中文原因
    """
    _require_engine()
    YoutubeDL = _load_module().YoutubeDL
    opts = _base_opts()
    opts.update({"skip_download": True, "format": None})
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise EngineError(_friendly_error(e)) from e
    if not info:
        raise EngineError("该链接没有可下载的内容")
    result = _clean_info(info)
    logger.info(
        f"[引擎] 解析成功: {result['extractor']} | {result['title']}"
        f" | {result['duration']}s"
    )
    return result


def list_levels(url: str) -> dict:
    """解析该链接实际提供的所有清晰度档位 + 标题（不下载）

    formats 是一次解析就能拿到的字段，不需要额外请求。返回的档位由高到低排序，
    供 UI 直接作为可选项，避免「视频根本没有 1080P 却让用户选 1080P」。
    """
    _require_engine()
    YoutubeDL = _load_module().YoutubeDL
    opts = _base_opts()
    opts.update({"skip_download": True, "format": None})
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise EngineError(_friendly_error(e)) from e
    if not info:
        raise EngineError("该链接没有可下载的内容")
    entries = info.get("entries")
    if entries:
        info = next((e for e in entries if e), None) or info
    meta = _clean_info(info)
    levels = build_levels(info)
    logger.info(
        f"[引擎] 档位解析: {meta['extractor']} | {meta['title']} | "
        f"{' / '.join(lv['label'] for lv in levels) or '无视频流'}"
    )
    return {
        "title": meta["title"],
        "extractor": meta["extractor"],
        "duration": meta["duration"],
        "thumbnail": meta["thumbnail"],
        "levels": levels,
    }


def resolve_stream(url: str, prefer: str = "worst") -> dict:
    """解析一条可直接播放的直链（预览用）+ 请求头

    Args:
        prefer: yt-dlp 格式选择器，默认最低画质（省流量、起播快）

    Returns:
        {url, headers, title, duration, thumbnail, extractor}
    """
    _require_engine()
    YoutubeDL = _load_module().YoutubeDL
    opts = _base_opts()
    opts.update({
        "skip_download": True,
        # 优先「音视频合一」的低清流：Qt 播放器不处理分离轨
        "format": f"{prefer}[acodec!=none][vcodec!=none]/{prefer}/worst",
    })
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise EngineError("该链接没有可预览的流")
    entries = info.get("entries")
    if entries:
        info = next((e for e in entries if e), None) or info
    stream_url = info.get("url") or ""
    if not stream_url:
        # 少数提取器把直链放在 formats 里
        formats = info.get("formats") or []
        if formats:
            stream_url = formats[-1].get("url") or ""
    if not stream_url:
        raise EngineError("该站点未提供可直接播放的流（可下载完成后本地预览）")
    return {
        "url": stream_url,
        "headers": dict(info.get("http_headers") or {}),
        "title": str(info.get("title") or ""),
        "duration": int(info.get("duration") or 0),
        "thumbnail": str(info.get("thumbnail") or ""),
        "extractor": str(info.get("extractor_key") or ""),
    }


# =====================================================================
# 下载
# =====================================================================


def download(
    url: str,
    *,
    quality: str = DEFAULT_QUALITY,
    file_format: str = "mp4",
    level: Optional[dict] = None,
    out_dir: str,
    temp_dir: str,
    channels: str = "双声道",
    progress_hook: Optional[Callable[[dict], None]] = None,
    postprocessor_hook: Optional[Callable[[dict], None]] = None,
) -> dict:
    """下载并后处理，返回 {filepath, title, extractor, duration, bytes}

    level 为 list_levels() 给出的具体档位（含 selector）；缺省时按 quality 档位名近似匹配。
    progress_hook 收到 yt-dlp 原始进度 dict（status: downloading/finished/error），
    字段含义见 yt-dlp 文档：downloaded_bytes / total_bytes / speed / eta。
    """
    _require_engine()
    YoutubeDL = _load_module().YoutubeDL

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(temp_dir)
    tmp_path.mkdir(parents=True, exist_ok=True)

    opts = _base_opts(
        progress_hooks=[progress_hook] if progress_hook else None,
        postprocessor_hooks=[postprocessor_hook] if postprocessor_hook else None,
    )
    opts.update({
        "format": level_format(level, quality, file_format),
        # outtmpl 用相对模板 + paths.home 指定输出目录：这样 paths.temp 才会生效
        # （绝对路径写进 outtmpl 时 yt-dlp 会忽略 --paths，分片会落在输出目录）
        "outtmpl": {"default": "%(title)s [%(id)s].%(ext)s"},
        "paths": {"home": str(out_path), "temp": str(tmp_path)},
    })
    if file_format == "mp4":
        opts["merge_output_format"] = "mp4"
    elif file_format == "mkv":
        opts["merge_output_format"] = "mkv"
    # flv / 纯音频（mp3、wav）由本地 ffmpeg 二次处理，不走 yt-dlp 后处理器

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = _final_filepath(ydl, info, out_path)
    except Exception as e:
        if isinstance(e, EngineError):
            raise
        raise EngineError(_friendly_error(e)) from e

    if not filepath:
        raise EngineError("下载完成但未找到输出文件（可能被站点拦截或需登录）")

    final = Path(filepath)
    if file_format in AUDIO_FORMATS or file_format == "flv":
        if postprocessor_hook:
            postprocessor_hook({"status": "started"})
        target = final.with_suffix(f".{file_format}")
        if target.name != final.name:
            logger.info(f"[引擎] 转换输出: {final.name} -> {target.name}")
            _ffmpeg_convert(final, target, file_format, channels)
            try:
                final.unlink(missing_ok=True)
            except Exception:
                pass
            final = target
        if postprocessor_hook:
            postprocessor_hook({"status": "finished"})

    meta = _clean_info(info or {})
    size = 0
    try:
        size = final.stat().st_size
    except Exception:
        pass
    logger.success(f"[引擎] 下载完成: {final}")
    return {
        "filepath": str(final),
        "title": meta["title"],
        "extractor": meta["extractor"],
        "duration": meta["duration"],
        "bytes": size,
    }


def _final_filepath(ydl, info: dict, out_dir: Path) -> str:
    """取后处理完成后的最终文件路径（合并/转码会改写扩展名）"""
    if not info:
        return ""
    requested = info.get("requested_downloads") or []
    if requested:
        path = requested[0].get("filepath") or requested[0].get("_filename")
        if path and Path(path).exists():
            return str(path)
    try:
        guess = ydl.prepare_filename(info)
        if guess and Path(guess).exists():
            return str(guess)
    except Exception:
        pass
    # 兜底：按 [id] 找同目录最新文件
    vid = str(info.get("id") or "")
    if vid:
        candidates = [p for p in out_dir.glob(f"*[{vid}]*") if p.is_file()]
        if candidates:
            return str(max(candidates, key=lambda p: p.stat().st_mtime))
    return ""


# =====================================================================
# 错误与维护
# =====================================================================


def _require_engine() -> None:
    if not available():
        raise EngineError(
            "未找到 yt-dlp 下载引擎，请重新安装应用或在设置中修复引擎依赖"
        )


_UNSUPPORTED_HINTS = (
    ("Unsupported URL", "该链接暂不被支持（yt-dlp 无法识别该站点）"),
    ("is not a valid URL", "链接格式不正确，请粘贴完整网址"),
    ("Video unavailable", "视频不可用（可能已删除、私有或地区限制）"),
    ("Private video", "该视频为私享/会员内容，需要在设置中配置浏览器 Cookie"),
    ("Sign in to confirm", "站点要求登录验证，请在设置中导入浏览器 Cookie"),
    ("This video is available to this channel's members", "会员专属内容，需配置 Cookie"),
    ("HTTP Error 403", "站点拒绝访问（403），请在设置中导入浏览器 Cookie 或更换代理"),
    ("HTTP Error 404", "资源不存在（404）"),
    ("HTTP Error 412", "站点风控拦截（412），请配置 Cookie 后重试"),
    ("timed out", "网络超时，请检查网络或代理设置"),
    ("UNEXPECTED_EOF_WHILE_READING", "网络连接被中断（TLS 握手失败），请检查网络或代理设置"),
    ("Connection reset", "网络连接被重置，请检查网络或代理设置"),
    ("Failed to resolve", "域名解析失败，请检查 DNS 或代理设置"),
    ("getaddrinfo failed", "域名解析失败，请检查 DNS 或代理设置"),
    ("Unable to download webpage", "无法访问该网页，请检查网络/代理，或该站点需要登录 Cookie"),
    ("Failed to decrypt", "媒体流解密失败，请尝试更新下载引擎"),
    ("Requested format is not available", "该视频没有这个清晰度档位（可选档位见链接卡片右键菜单）"),
    # 磁盘被移除/换盘符时，yt-dlp 扫描 PATH 会抛这个系统错误，原文看不懂
    ("WinError 1005", "本机有磁盘不可访问（PATH 或设置里残留了已移除的盘符），请清理后重启应用"),
    ("此卷不包含可识别的文件系统", "本机有磁盘不可访问（PATH 或设置里残留了已移除的盘符），请清理后重启应用"),
)


def _friendly_error(exc: Exception) -> str:
    """把 yt-dlp 的长串异常翻译成一句人话"""
    text = str(exc)
    # yt-dlp 的 DownloadError 形如 "ERROR: [extractor] 原因"
    text = re.sub(r"^ERROR:\s*", "", text).strip()
    for needle, friendly in _UNSUPPORTED_HINTS:
        if needle.lower() in text.lower():
            return friendly
    # 去掉提取器前缀，保留具体原因
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    text = text.split("\n")[0]
    return text[:200] or "下载失败"


def update_engine(progress_cb: Optional[Callable[[str], None]] = None) -> tuple[bool, str]:
    """更新下载引擎

    优先从 GitHub Release 拉 engine 组件（约 5MB，只含 yt-dlp 与其依赖），
    这样升级不需要重下整个运行时；组件清单不可用时才回退 pip 增量升级。
    """
    global _version_cache
    if progress_cb:
        progress_cb("正在检查引擎组件…")
    try:
        from runtime_manager import update_engine_component  # noqa: PLC0415

        ok, message = update_engine_component()
        if ok:
            _version_cache = None
            return True, (message or "引擎组件已更新") + "（重启应用生效）"
        logger.info(f"引擎组件更新不可用（{message}），尝试 pip 升级")
    except Exception as e:
        logger.debug(f"引擎组件更新异常: {e}")

    # ---- 回退：pip 增量升级（开发者环境，或 release 未发布组件清单时） ----
    if getattr(sys, "frozen", False):
        return False, "打包版本请通过重新安装应用更新引擎"
    cmd = [sys.executable, "-m", "pip", "install", "-U", "--disable-pip-version-check", "yt-dlp"]
    if progress_cb:
        progress_cb("正在通过 pip 更新下载引擎…")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:
        return False, f"更新失败: {e}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["未知错误"]
        return False, f"更新失败: {tail[0]}"
    _version_cache = None
    return True, version() or "已更新"


