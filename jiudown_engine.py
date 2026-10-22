"""
JiuDown 下载引擎（自有引擎层）

由我们自己维护的统一下载引擎，内部是「双后端」结构：

  后端 native —— 原生 B 站链路（本项目自研，不依赖第三方提取器）
      · api.bilibili.com/wbi 接口直连解析，buvid Cookie 播种 + 登录 Cookie 注入
      · DASH 音视频分离流 + requests 分片下载（Range 续传 / 限速 / 进度节流）
      · FFmpeg 合并与音频转码（mp3 / wav / flv）
      · 优点：解析快、字段可控；B 站接口或清晰度规则变化时我们自己改

  后端 yt-dlp —— 通用站点（1700+）
      · B 站以外的全部站点，以及 native 后端失败时的兜底

路由策略（配置项 engine.backend）：
  auto（默认）：B 站链接先走 native，失败自动降级 yt-dlp；其他站点走 yt-dlp
  native      ：强制 native（仅 B 站有效，其他链接仍走 yt-dlp）
  ytdlp       ：全部走 yt-dlp（保留给原生链路出问题时的应急开关）

对外只暴露三类能力（与站点无关）：
  probe(url)                  解析元数据
  download(...)               下载（进度经统一 hook 回调）
  resolve_stream(url, prefer) 取可播放直链（预览用）
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import requests
from loguru import logger

import ytdlp_engine
from ytdlp_engine import (  # 统一常量与工具（避免 UI 层出现两套定义）
    AUDIO_FORMATS,
    FORMAT_CHOICES,
    QUALITY_CHOICES,
    EngineError,
    format_selector,
    normalize_url,
)

ENGINE_NAME = "JiuDown Engine"
ENGINE_VERSION = "1.0.0"

BACKENDS = ("auto", "native", "ytdlp")
BACKEND_LABELS = {
    "auto": "自动（B 站原生优先）",
    "native": "仅原生（B 站）",
    "ytdlp": "仅 yt-dlp",
}


# =====================================================================
# 后端一：原生 B 站链路
# =====================================================================


class NativeBilibiliBackend:
    """B 站原生下载后端（自研链路）"""

    name = "native"
    label = "JiuDown 原生"

    BASE_API = "https://api.bilibili.com"
    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
        ),
    }
    # 画质档位 → B 站 qn（16=360P, 32=480P, 64=720P, 80=1080P, 127=请求最高可用）
    QUALITY_QN = {
        "360P": 16,
        "480P": 32,
        "720P": 64,
        "1080P": 80,
        "最高": 127,
    }
    # 预览用低清 qn 序列（音视频合一 durl，失败逐级回退）
    PREVIEW_QN = (16, 32)

    _BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
    _AV_RE = re.compile(r"av(\d+)", re.IGNORECASE)

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(self.DEFAULT_HEADERS)
        self._buvid_ready = False
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 识别

    @classmethod
    def parse_bvid(cls, url: str) -> str:
        """从链接中取 BV / av 号；不是 B 站视频链接时抛 ValueError"""
        text = (url or "").strip()
        match = cls._BV_RE.search(text)
        if match:
            return match.group(1)
        match = cls._AV_RE.search(text)
        if match:
            return f"av{match.group(1)}"
        raise ValueError("不是 B 站视频链接")

    @classmethod
    def matches(cls, url: str) -> bool:
        if "bilibili.com" not in (url or "") and "b23.tv" not in (url or ""):
            return False
        try:
            cls.parse_bvid(url)
            return True
        except ValueError:
            return False

    # ---------------------------------------------------------------- 会话

    def _ensure_buvid(self) -> None:
        """播种 buvid3/b_nut Cookie（缺它时 B 站接口返回 412 风控页）"""
        if self._buvid_ready:
            return
        with self._lock:
            if self._buvid_ready:
                return
            self._apply_config_cookies()
            try:
                self._session.get(
                    "https://www.bilibili.com/",
                    headers={**self.DEFAULT_HEADERS, "Referer": "https://www.bilibili.com/"},
                    timeout=10,
                )
            except Exception as e:
                logger.debug(f"buvid Cookie 播种失败（继续尝试）: {e}")
            self._buvid_ready = True

    def _apply_config_cookies(self) -> None:
        """注入配置里的登录 Cookie（会员/限制级稿件需要）"""
        try:
            from config_manager import config_manager  # noqa: PLC0415

            ui = config_manager.get_user_info() or {}
            raw = str(ui.get("raw-cookies") or ui.get("cookies") or "").strip()
            if not raw:
                return
            if raw.startswith("{"):
                import json  # noqa: PLC0415

                for k, v in (json.loads(raw) or {}).items():
                    self._session.cookies.set(str(k), str(v), domain=".bilibili.com")
            else:
                for part in raw.split(";"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        self._session.cookies.set(k.strip(), v.strip(), domain=".bilibili.com")
        except Exception as e:
            logger.debug(f"注入配置 Cookie 失败（忽略）: {e}")

    def _get(self, url: str, *, referer: str = "", timeout: int = 20) -> requests.Response:
        self._ensure_buvid()
        headers = dict(self.DEFAULT_HEADERS)
        if referer:
            headers["Referer"] = referer
        return self._session.get(url, headers=headers, timeout=timeout)

    def _headers(self, bvid: str) -> dict:
        return {
            **self.DEFAULT_HEADERS,
            "Referer": f"https://www.bilibili.com/video/{bvid}",
        }

    # ---------------------------------------------------------------- 解析

    def _video_info(self, bvid: str) -> dict:
        api = f"{self.BASE_API}/x/web-interface/wbi/view?bvid={bvid}"
        resp = self._get(api, referer=f"https://www.bilibili.com/video/{bvid}")
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise EngineError(
                f"B 站解析失败：{payload.get('message', '未知错误')}"
            )
        data = payload.get("data") or {}
        return {
            "bvid": bvid,
            "title": data.get("title") or bvid,
            "cid": data.get("cid"),
            "duration": int(data.get("duration") or 0),
            "uploader": (data.get("owner") or {}).get("name") or "",
            "thumbnail": data.get("pic") or "",
            "pages": data.get("pages") or [],
        }

    def _streams(self, bvid: str, cid: int, quality: str) -> dict:
        """取该清晰度的 DASH 流；无 dash 时回退 durl 单文件"""
        qn = self.QUALITY_QN.get(quality, 64)
        api = (
            f"{self.BASE_API}/x/player/playurl"
            f"?bvid={bvid}&cid={cid}&qn={qn}&fnval=4048&fourk=1"
        )
        resp = self._get(api, referer=f"https://www.bilibili.com/video/{bvid}")
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise EngineError(
                f"播放地址获取失败：{payload.get('message', '未知错误')}"
            )
        data = payload.get("data") or {}
        dash = data.get("dash") or {}
        videos = dash.get("video") or []
        audios = dash.get("audio") or []

        if not videos and data.get("durl"):
            durl = data["durl"][0]
            return {"video_url": durl.get("url"), "audio_url": None, "quality": quality}

        if not videos:
            raise EngineError(f"B 站未返回可下载流（清晰度 {quality}）")

        # 取满足目标高度的最高码率流；没有则退回最高可用
        target = {"360P": 360, "480P": 480, "720P": 720, "1080P": 1080}.get(quality)
        if target:
            candidates = [v for v in videos if int(v.get("height") or 0) <= target] or videos
        else:
            candidates = videos
        video = max(candidates, key=lambda v: (int(v.get("height") or 0), int(v.get("bandwidth") or 0)))
        audio = max(audios, key=lambda a: int(a.get("bandwidth") or 0)) if audios else None
        return {
            "video_url": video.get("baseUrl") or video.get("base_url"),
            "audio_url": (audio or {}).get("baseUrl") or (audio or {}).get("base_url"),
            "quality": quality,
            "height": int(video.get("height") or 0),
        }

    def probe(self, url: str) -> dict:
        bvid = self.parse_bvid(url)
        info = self._video_info(bvid)
        logger.info(f"[引擎/native] 解析成功: {bvid} | {info['title']} | {info['duration']}s")
        return {
            "id": bvid,
            "title": info["title"],
            "uploader": info["uploader"],
            "duration": info["duration"],
            "thumbnail": info["thumbnail"],
            "webpage_url": f"https://www.bilibili.com/video/{bvid}",
            "extractor": "BiliBili(native)",
            "is_live": False,
            "playlist_count": max(0, len(info["pages"]) - 1),
        }

    def resolve_stream(self, url: str, prefer: str = "worst") -> dict:
        """预览用：取音视频合一的低清 durl 直链"""
        bvid = self.parse_bvid(url)
        info = self._video_info(bvid)
        cid = info.get("cid")
        if not cid:
            raise EngineError("未获取到视频 cid")
        last_error = ""
        for qn in self.PREVIEW_QN:
            api = (
                f"{self.BASE_API}/x/player/playurl"
                f"?bvid={bvid}&cid={cid}&qn={qn}&fnval=0"
            )
            try:
                resp = self._get(api, referer=f"https://www.bilibili.com/video/{bvid}")
                resp.raise_for_status()
                payload = resp.json()
                if payload.get("code") != 0:
                    last_error = payload.get("message", "")
                    continue
                durl = (payload.get("data") or {}).get("durl") or []
                if not durl:
                    continue
                return {
                    "url": durl[0]["url"],
                    "headers": self._headers(bvid),
                    "title": info["title"],
                    "duration": info["duration"],
                    "thumbnail": info["thumbnail"],
                    "extractor": "BiliBili(native)",
                }
            except Exception as e:
                last_error = str(e)
        raise EngineError(f"该视频暂无在线预览流{('：' + last_error) if last_error else ''}")

    # ---------------------------------------------------------------- 下载

    def _fetch(
        self,
        url: str,
        target: Path,
        task_ctx: dict,
        hook: Optional[Callable],
        label: str,
        files_total: int,
    ) -> None:
        """单文件下载：Range 续传 + 限速 + 每 0.5s 一次进度回调"""
        from config_manager import config_manager  # noqa: PLC0415

        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".part")
        offset = temp.stat().st_size if temp.exists() else 0

        headers = dict(self._headers(task_ctx["bvid"]))
        if offset:
            headers["Range"] = f"bytes={offset}-"

        start = time.time()
        last_notify = start
        session_bytes = 0
        limit = 0
        try:
            limit = int(config_manager.get_download_speed_limit() or 0)
        except Exception:
            limit = 0

        with requests.get(url, headers=headers, stream=True, timeout=60) as resp:
            if resp.status_code == 416 and offset:
                temp.replace(target)
                return
            if resp.status_code == 200 and offset:
                offset = 0
                temp.unlink(missing_ok=True)
            elif resp.status_code not in (200, 206):
                resp.raise_for_status()

            total = offset + int(resp.headers.get("content-length") or 0)
            content_range = resp.headers.get("content-range", "")
            match = re.search(r"/(\d+)\s*$", content_range)
            if match:
                total = int(match.group(1))

            mode = "ab" if offset else "wb"
            with open(temp, mode) as fh:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    session_bytes += len(chunk)
                    now = time.time()
                    elapsed = now - start or 1e-6
                    if hook and now - last_notify >= 0.5:
                        hook({
                            "status": "downloading",
                            "label": label,
                            "downloaded_bytes": offset + session_bytes,
                            "total_bytes": total,
                            "speed": session_bytes / elapsed,
                            "info_dict": {
                                "title": task_ctx["title"],
                                "extractor_key": "BiliBili(native)",
                                "requested_formats": [{}] * files_total,
                            },
                        })
                        last_notify = now
                    if limit > 0:
                        sleep_for = session_bytes / limit - (time.time() - start)
                        if sleep_for > 0:
                            time.sleep(sleep_for)

        if temp.exists():
            temp.replace(target)

    def download(
        self,
        url: str,
        *,
        quality: str = "720P",
        file_format: str = "mp4",
        out_dir: str,
        temp_dir: str,
        channels: str = "双声道",
        progress_hook: Optional[Callable[[dict], None]] = None,
        postprocessor_hook: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        bvid = self.parse_bvid(url)
        info = self._video_info(bvid)
        streams = self._streams(bvid, info["cid"], quality)

        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        tmp_path = Path(temp_dir)
        tmp_path.mkdir(parents=True, exist_ok=True)

        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", info["title"]).strip()[:120] or bvid
        stem = f"{safe_title} [{bvid}]"
        video_file = tmp_path / f"{bvid}_video.m4s"
        audio_file = tmp_path / f"{bvid}_audio.m4s"

        audio_only = file_format in AUDIO_FORMATS
        files_total = 1 if (audio_only or not streams.get("audio_url")) else 2
        ctx = {"bvid": bvid, "title": info["title"]}

        try:
            if audio_only:
                if not streams.get("audio_url"):
                    raise EngineError("该视频没有独立音频流，无法导出 mp3/wav")
                self._fetch(streams["audio_url"], audio_file, ctx, progress_hook, "音频流", 1)
            else:
                self._fetch(streams["video_url"], video_file, ctx, progress_hook, "视频流", files_total)
                if streams.get("audio_url"):
                    self._fetch(streams["audio_url"], audio_file, ctx, progress_hook, "音频流", files_total)

            if postprocessor_hook:
                postprocessor_hook({"status": "started"})

            if audio_only:
                target = out_path / f"{stem}.{file_format}"
                ytdlp_engine._ffmpeg_convert(audio_file, target, file_format, channels)
                audio_file.unlink(missing_ok=True)
            else:
                target = out_path / f"{stem}.{file_format}"
                self._merge(video_file, audio_file if streams.get("audio_url") else None, target, file_format)
                video_file.unlink(missing_ok=True)
                audio_file.unlink(missing_ok=True)

            if postprocessor_hook:
                postprocessor_hook({"status": "finished"})
        except Exception:
            video_file.unlink(missing_ok=True)
            audio_file.unlink(missing_ok=True)
            raise

        size = target.stat().st_size if target.exists() else 0
        logger.success(f"[引擎/native] 下载完成: {target}")
        return {
            "filepath": str(target),
            "title": info["title"],
            "extractor": "BiliBili(native)",
            "duration": info["duration"],
            "bytes": size,
        }

    @staticmethod
    def _merge(video: Path, audio: Optional[Path], target: Path, file_format: str) -> None:
        """音视频合并（-c copy 不重编码）；flv 由通用转换函数重封装"""
        import subprocess  # noqa: PLC0415

        exe = ytdlp_engine._ffmpeg_exe()
        if file_format == "flv":
            # 先合成 mp4 再重封装，避免 ffmpeg 直接 mux 到 flv 的兼容问题
            inter = target.with_suffix(".tmp.mp4")
            cmd = [exe, "-y", "-i", str(video)]
            if audio and audio.exists():
                cmd += ["-i", str(audio)]
            cmd += ["-c", "copy", str(inter)]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=3600,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if proc.returncode != 0 or not inter.exists():
                raise EngineError(f"音视频合并失败：{(proc.stderr or '').strip()[-200:]}")
            ytdlp_engine._ffmpeg_convert(inter, target, "flv", "双声道")
            inter.unlink(missing_ok=True)
            return

        cmd = [exe, "-y", "-i", str(video)]
        if audio and audio.exists():
            cmd += ["-i", str(audio)]
        cmd += ["-c", "copy", str(target)]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0 or not target.exists():
            raise EngineError(f"音视频合并失败：{(proc.stderr or '').strip()[-200:]}")


# =====================================================================
# 引擎门面：路由 + 降级
# =====================================================================


class JiuDownEngine:
    """自有下载引擎：native（B 站）+ yt-dlp（通用），统一对外"""

    def __init__(self):
        self.native = NativeBilibiliBackend()

    # ---------------------------------------------------------------- 状态

    @staticmethod
    def available() -> bool:
        """引擎是否可用：原生后端恒可用，yt-dlp 缺失时只影响非 B 站站点"""
        return True

    @staticmethod
    def ytdlp_ready() -> bool:
        return ytdlp_engine.available()

    @staticmethod
    def version() -> str:
        return ENGINE_VERSION

    def info(self) -> dict:
        return {
            "name": ENGINE_NAME,
            "version": ENGINE_VERSION,
            "native_ready": True,
            "ytdlp_ready": ytdlp_engine.available(),
            "ytdlp_version": ytdlp_engine.version(),
            "sites": ytdlp_engine.request_site_count(),
            "mode": self.mode(),
        }

    @staticmethod
    def mode() -> str:
        """当前路由模式（配置项 engine.backend）"""
        try:
            from config_manager import config_manager  # noqa: PLC0415

            value = str(config_manager.get_config("engine_backend") or "auto").strip()
        except Exception:
            value = "auto"
        return value if value in BACKENDS else "auto"

    @staticmethod
    def request_site_count() -> Optional[int]:
        """yt-dlp 支持站点数（非阻塞：未就绪返回 None 并后台预热）"""
        return ytdlp_engine.request_site_count()

    @staticmethod
    def supported_site_count() -> int:
        return ytdlp_engine.supported_site_count()

    # ---------------------------------------------------------------- 路由

    def _plan(self, url: str) -> list[str]:
        """决定后端尝试顺序"""
        target = normalize_url(url)
        is_bili = self.native.matches(target)
        mode = self.mode()
        if mode == "ytdlp":
            return ["ytdlp"]
        if mode == "native":
            return ["native", "ytdlp"] if is_bili else ["ytdlp"]
        # auto
        return ["native", "ytdlp"] if is_bili else ["ytdlp"]

    def backend_for(self, url: str) -> str:
        return self._plan(url)[0]

    # ---------------------------------------------------------------- API

    def probe(self, url: str) -> dict:
        target = normalize_url(url)
        if not target:
            raise EngineError("链接格式不正确，请粘贴以 http(s):// 开头的网址")
        errors: list[str] = []
        for backend in self._plan(target):
            try:
                if backend == "native":
                    return self.native.probe(target)
                return ytdlp_engine.probe(target)
            except Exception as e:
                errors.append(f"{backend}: {e}")
                logger.debug(f"[引擎] {backend} 解析失败，尝试下一后端: {e}")
        raise EngineError(_merge_errors(errors))

    def download(
        self,
        url: str,
        *,
        quality: str = "720P",
        file_format: str = "mp4",
        out_dir: str,
        temp_dir: str,
        channels: str = "双声道",
        progress_hook: Optional[Callable[[dict], None]] = None,
        postprocessor_hook: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        target = normalize_url(url)
        if not target:
            raise EngineError("链接格式不正确，请粘贴以 http(s):// 开头的网址")
        errors: list[str] = []
        for backend in self._plan(target):
            try:
                if backend == "native":
                    result = self.native.download(
                        target, quality=quality, file_format=file_format,
                        out_dir=out_dir, temp_dir=temp_dir, channels=channels,
                        progress_hook=progress_hook,
                        postprocessor_hook=postprocessor_hook,
                    )
                else:
                    result = ytdlp_engine.download(
                        target, quality=quality, file_format=file_format,
                        out_dir=out_dir, temp_dir=temp_dir, channels=channels,
                        progress_hook=progress_hook,
                        postprocessor_hook=postprocessor_hook,
                    )
                result["backend"] = backend
                return result
            except Exception as e:
                errors.append(f"{backend}: {e}")
                logger.warning(f"[引擎] {backend} 下载失败，尝试下一后端: {e}")
        raise EngineError(_merge_errors(errors))

    def resolve_stream(self, url: str, prefer: str = "worst") -> dict:
        target = normalize_url(url)
        if not target:
            raise EngineError("链接无法识别")
        errors: list[str] = []
        for backend in self._plan(target):
            try:
                if backend == "native":
                    return self.native.resolve_stream(target, prefer)
                return ytdlp_engine.resolve_stream(target, prefer)
            except Exception as e:
                errors.append(f"{backend}: {e}")
                logger.debug(f"[引擎] {backend} 预览解析失败: {e}")
        raise EngineError(_merge_errors(errors))

    # ---------------------------------------------------------------- 维护

    def update(self) -> tuple[bool, str]:
        """更新 yt-dlp 后端（native 后端随应用版本发布）"""
        return ytdlp_engine.update_engine()


def _merge_errors(errors: list[str]) -> str:
    """多后端错误合并：优先展示最后一条（通常是兜底后端的具体原因）"""
    if not errors:
        return "下载失败"
    text = errors[-1]
    text = re.sub(r"^(native|ytdlp):\s*", "", text)
    return text


# =====================================================================
# 兼容导出：UI 与下载管理器只依赖本模块
# =====================================================================

engine = JiuDownEngine()

# ---- 模块级函数式 API（与旧 ytdlp_engine 用法保持一致，调用方无需 engine.engine） ----
COOKIE_BROWSERS = ytdlp_engine.COOKIE_BROWSERS


def available() -> bool:
    return engine.available()


def version() -> str:
    return engine.version()


def probe(url: str) -> dict:
    return engine.probe(url)


def download(url: str, **kwargs) -> dict:
    return engine.download(url, **kwargs)


def resolve_stream(url: str, prefer: str = "worst") -> dict:
    return engine.resolve_stream(url, prefer)


def request_site_count() -> Optional[int]:
    return engine.request_site_count()


def supported_site_count() -> int:
    return engine.supported_site_count()


def update_engine() -> tuple[bool, str]:
    return engine.update()

__all__ = [
    "ENGINE_NAME",
    "ENGINE_VERSION",
    "BACKENDS",
    "BACKEND_LABELS",
    "AUDIO_FORMATS",
    "FORMAT_CHOICES",
    "QUALITY_CHOICES",
    "EngineError",
    "JiuDownEngine",
    "NativeBilibiliBackend",
    "engine",
    "format_selector",
    "normalize_url",
]
