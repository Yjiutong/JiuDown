"""
抖音图文（图集）原生引擎

为什么需要单独一个后端：yt-dlp 的 DouyinIE._VALID_URL 只匹配
douyin.com/video/<id>，图文形态（douyin.com/note/<id>）落到通用提取器后被判定
Unsupported URL，抖音图文链接因此在本项目里全量失败。

图文也没有视频流可下：服务端把图集渲染成 mp4 的 /aweme/v1/playwm/ 已返回 404，
去水印的 /play/ 返回空响应体。唯一能取到的产物是原图，所以本后端的下载结果是
**一个装原图的文件夹**，而不是单个媒体文件。

数据源：iesdouyin 图文分享页的服务端渲染数据（页面里的 _ROUTER_DATA）。该页
要求 ttwid Cookie 但不要求登录态——先用移动端 UA 访问 iesdouyin 首页领一个
匿名 ttwid，再请求 share/note/<id>/ 即可在 item_list 里拿到完整图集。

图片地址取舍：images[i].url_list 是同一张图的多个 CDN 镜像（3 个 webp + 1 个
jpeg），download_url_list 是叠加了作者水印的版本——取 url_list 里的 jpeg，
既无水印又比 webp 兼容。
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Optional

import requests
from loguru import logger

from ytdlp_engine import EngineError

DOUYIN_HOSTS = ("douyin.com", "iesdouyin.com")
SHARE_PAGE = "https://www.iesdouyin.com/share/{kind}/{aweme_id}/"
TTWID_SEED = "https://www.iesdouyin.com/"
NOTE_KIND = "note"
VIDEO_KIND = "video"
NOTE_LEVEL_LABEL = "原图"

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

# /note/<id>、/share/note/<id>、/slides/<id>（slides 是图文的另一条路径别名）
_ITEM_RE = re.compile(r"/(?:share/)?(note|video|slides)/(\d{6,})")
_ROUTER_RE = re.compile(r"_ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>", re.S)

# 抖音图文的原图地址带 x-expires/x-signature，签名过期后就会 403，
# 所以解析结果只短期复用，超时宁可重新解析。
_RESOLVE_TTL = 600.0
_RESOLVE_LIMIT = 64


class NotHandled(Exception):
    """本后端不处理该链接（例：抖音视频，交回 yt-dlp），不应当作面向用户的错误"""


def matches(url: str) -> bool:
    """是否抖音系域名（含 v.douyin.com 短链与 iesdouyin 分享域）"""
    text = (url or "").lower()
    return any(host in text for host in DOUYIN_HOSTS)


def is_note_url(url: str) -> bool:
    """链接是否已确定是图文

    URL 里写明 /note/ 时直接判定；短链只有在**已经被解析过**的前提下才参考缓存，
    绝不为了路由判定另发一次请求（路由是纯函数式的便宜判断，贵的那次留给后端）。
    """
    match = _ITEM_RE.search(url or "")
    if match:
        return match.group(1) in ("note", "slides")
    ref = douyin_engine.peek_cache(url)
    return bool(ref) and ref[0] == NOTE_KIND


def _aweme_ref(url: str) -> tuple[str, str] | None:
    """从链接直读 (形态, aweme 号)；短链读不出来返回 None"""
    match = _ITEM_RE.search(url or "")
    if not match:
        return None
    kind, aweme_id = match.group(1), match.group(2)
    return (NOTE_KIND if kind in ("note", "slides") else VIDEO_KIND, aweme_id)


class DouyinEngine:
    """抖音图文抓取：短链解析 → 分享页 SSR → 原图批量落盘"""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": MOBILE_UA})
        # 不继承系统/注册表代理：抖音是国内站点，机器上挂着一个已失效的系统代理时
        # 继承它会直接 "Unable to connect to proxy"，而设置里明确填的代理照样生效
        self._session.trust_env = False
        self._lock = threading.Lock()
        self._ttwid_ready = False
        self._resolve_cache: "OrderedDict[str, tuple[str, str]]" = OrderedDict()

    # ---------------------------------------------------------------- 会话

    def _proxies(self) -> dict:
        proxy = ""
        try:
            from config_manager import config_manager  # noqa: PLC0415

            proxy = str(config_manager.get_config("proxy") or "").strip()
        except Exception:
            proxy = ""
        return {"http": proxy, "https": proxy} if proxy else {}

    def _ensure_ttwid(self) -> None:
        """领匿名 ttwid：缺它时图文分享页只返回不含图集的空壳"""
        if self._ttwid_ready:
            return
        with self._lock:
            if self._ttwid_ready:
                return
            try:
                self._session.get(TTWID_SEED, timeout=15, proxies=self._proxies())
            except Exception as e:
                logger.debug(f"ttwid 播种失败（继续尝试）: {e}")
            self._ttwid_ready = True

    def _get(self, url: str, *, referer: str = "", timeout: int = 20,
             allow_redirects: bool = True, stream: bool = False) -> requests.Response:
        headers = {"Referer": referer} if referer else {}
        return self._session.get(
            url, headers=headers, timeout=timeout,
            allow_redirects=allow_redirects, proxies=self._proxies(), stream=stream,
        )

    # ---------------------------------------------------------------- 定位

    def locate(self, url: str) -> tuple[str, str]:
        """返回 (形态, aweme 号)；短链跟随一次重定向读取目标"""
        cached = self._cache_get(url)
        if cached:
            return cached
        ref = _aweme_ref(url)
        if ref is None:
            ref = self._locate_short(url)
        if ref is None:
            raise EngineError("无法从链接中识别出抖音作品号，请粘贴抖音 App 的分享链接")
        self._cache_put(url, ref)
        return ref

    def _locate_short(self, url: str) -> tuple[str, str] | None:
        """v.douyin.com 短链：第一跳的 Location 里就带作品形态与号，不必取回正文"""
        try:
            resp = self._get(url, allow_redirects=False, timeout=15)
        except Exception as e:
            logger.debug(f"抖音短链解析失败: {e}")
            return None
        for _ in range(3):
            location = resp.headers.get("Location") or resp.headers.get("location") or ""
            if not location:
                return None
            ref = _aweme_ref(location)
            if ref:
                return ref
            try:
                resp = self._get(location, allow_redirects=False, timeout=15)
            except Exception as e:
                logger.debug(f"抖音短链跳转中断: {e}")
                return None
        return None

    def peek_cache(self, url: str) -> Optional[tuple[str, str]]:
        """只读已解析结果，不发网络请求（供路由判定使用）"""
        return self._cache_get(url)

    def _cache_get(self, url: str) -> Optional[tuple[str, str]]:
        with self._lock:
            hit = self._resolve_cache.get(url)
            if not hit:
                return None
            ref, stamp = hit
            if time.time() - stamp > _RESOLVE_TTL:
                self._resolve_cache.pop(url, None)
                return None
            self._resolve_cache.move_to_end(url)
            return ref

    def _cache_put(self, url: str, ref: tuple[str, str]) -> None:
        with self._lock:
            self._resolve_cache[url] = (ref, time.time())
            self._resolve_cache.move_to_end(url)
            while len(self._resolve_cache) > _RESOLVE_LIMIT:
                self._resolve_cache.popitem(last=False)

    # ---------------------------------------------------------------- 详情

    def detail(self, url: str) -> dict:
        """取作品数据；图文以外的形态抛 NotHandled（由 yt-dlp 继续负责视频）"""
        kind, aweme_id = self.locate(url)
        if kind != NOTE_KIND:
            raise NotHandled("抖音视频由 yt-dlp 处理")
        item = self._item(NOTE_KIND, aweme_id) or self._item(VIDEO_KIND, aweme_id)
        if not item or not (item.get("images") or []):
            raise EngineError("抖音图文解析失败：分享页没有返回图集数据（可能被风控，稍后重试）")
        return item

    def _item(self, kind: str, aweme_id: str) -> Optional[dict]:
        self._ensure_ttwid()
        page = SHARE_PAGE.format(kind=kind, aweme_id=aweme_id)
        try:
            resp = self._get(page, referer="https://www.douyin.com/", timeout=25)
            resp.raise_for_status()
        except Exception as e:
            logger.debug(f"抖音分享页请求失败({kind}): {e}")
            return None
        match = _ROUTER_RE.search(resp.text or "")
        if not match:
            logger.debug(f"抖音分享页缺少 _ROUTER_DATA({kind})")
            return None
        try:
            data = json.loads(match.group(1))
        except Exception as e:
            logger.debug(f"抖音 _ROUTER_DATA 解析失败: {e}")
            return None
        for page_data in (data.get("loaderData") or {}).values():
            if not isinstance(page_data, dict):
                continue
            items = (page_data.get("videoInfoRes") or {}).get("item_list") or []
            if items:
                return items[0]
        return None

    # ---------------------------------------------------------------- 数据整理

    @staticmethod
    def image_candidates(item: dict) -> list[list[str]]:
        """每张图的全部候选地址，无水印 jpeg 排在最前

        图文一张图会有 3~4 个 CDN 镜像；单张失败时按候选逐个重试比瞎猜域名可靠。
        download_url_list 是叠了作者水印的另一套地址，始终排在 url_list 之后。
        """
        groups: list[list[str]] = []
        for entry in item.get("images") or []:
            clean = [u for u in (entry.get("url_list") or []) if u]
            marked = [u for u in (entry.get("download_url_list") or []) if u]
            ordered = [u for u in clean if ".jpeg" in u.lower()] + \
                      [u for u in clean if ".jpeg" not in u.lower()] + marked
            if ordered:
                groups.append(ordered)
        return groups

    @classmethod
    def image_urls(cls, item: dict) -> list[str]:
        """每张图的首选地址（缩略图与单图预览用）"""
        return [group[0] for group in cls.image_candidates(item)]

    @staticmethod
    def title_of(item: dict) -> str:
        return str(item.get("desc") or "").strip()

    @staticmethod
    def author_of(item: dict) -> str:
        return str((item.get("author") or {}).get("nickname") or "").strip()

    # ---------------------------------------------------------------- API

    def _info(self, item: dict) -> dict:
        images = self.image_urls(item)
        return {
            "id": str(item.get("aweme_id") or ""),
            "title": self.title_of(item) or "抖音图文",
            "uploader": self.author_of(item),
            "duration": 0,
            "thumbnail": images[0] if images else "",
            "webpage_url": SHARE_PAGE.format(kind=NOTE_KIND, aweme_id=item.get("aweme_id", "")),
            "extractor": "Douyin图文",
            "is_live": False,
            "playlist_count": 0,
            "kind": "note",
            "image_count": len(images),
        }

    def probe(self, url: str) -> dict:
        return self._info(self.detail(url))

    def list_levels(self, url: str) -> dict:
        """图文的"档位"只有一档：无水印原图"""
        info = self._info(self.detail(url))
        return {
            "title": info["title"],
            "extractor": "Douyin图文",
            "duration": 0,
            "thumbnail": info["thumbnail"],
            "kind": "note",
            "image_count": info["image_count"],
            "levels": [{
                "label": NOTE_LEVEL_LABEL,
                "height": 0,
                "pixels": 0,
                "fps": 0,
                "hdr": False,
                "selector": "",
                "available": True,
                "reason": "",
            }],
        }

    def resolve_stream(self, url: str, prefer: str = "worst") -> dict:
        raise EngineError("抖音图文没有视频流，无法生成小窗预览")

    def download(
        self,
        url: str,
        *,
        quality: str = "720P",
        file_format: str = "mp4",
        level: Optional[dict] = None,
        out_dir: str,
        temp_dir: str,
        channels: str = "双声道",
        progress_hook: Optional[Callable[[dict], None]] = None,
        postprocessor_hook: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        item = self.detail(url)
        groups = self.image_candidates(item)
        aweme_id = str(item.get("aweme_id") or "")
        title = self.title_of(item) or "抖音图文"
        folder = self._folder(out_dir, title, aweme_id)
        folder.mkdir(parents=True, exist_ok=True)
        temp_path = Path(temp_dir) if temp_dir else folder
        temp_path.mkdir(parents=True, exist_ok=True)

        total_bytes = 0
        count = len(groups)
        width = max(2, len(str(count)))
        for index, candidates in enumerate(groups, start=1):
            # 先落到 .part：文件名要等真正取到的那个地址定了扩展名才确定，
            # 且中途失败时不会在成品目录里留下半张图
            staged = temp_path / f"{aweme_id}_{index:0{width}d}.part"
            try:
                written, used = self._save(candidates, staged, progress_hook,
                                           title, aweme_id, index, count)
            except Exception as e:
                staged.unlink(missing_ok=True)
                raise EngineError(f"抖音图文第 {index}/{count} 张下载失败：{e}")
            target = folder / f"{index:0{width}d}.{_ext_of(used)}"
            try:
                staged.replace(target)
            except OSError:
                # 暂存目录与下载目录跨盘时 replace 不可用，退回移动
                shutil.move(str(staged), str(target))
            total_bytes += written

        if not any(folder.iterdir()):
            raise EngineError("抖音图文下载失败：没有保存任何图片")
        logger.info(f"抖音图文已保存 {count} 张原图: {folder}")
        return {
            "filepath": str(folder),
            "title": title,
            "extractor": "Douyin图文",
            "duration": 0,
            "bytes": total_bytes,
            "file_count": count,
            "kind": "note",
        }

    def _save(self, candidates: list[str], staged: Path, hook, title: str,
              aweme_id: str, index: int, count: int) -> tuple[int, str]:
        """按候选地址逐个尝试，全部失败才报错（同一张图通常有 3~4 个 CDN 镜像）"""
        last_error: Optional[Exception] = None
        for src in candidates:
            try:
                resp = self._get(src, referer="https://www.douyin.com/", timeout=30, stream=True)
                resp.raise_for_status()
            except Exception as e:
                last_error = e
                logger.debug(f"抖音原图第 {index} 张该镜像不可用，换下一个候选: {e}")
                continue
            total = int(resp.headers.get("Content-Length") or 0)
            written = 0
            with staged.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        fh.write(chunk)
                        written += len(chunk)
            _emit(hook, "downloading", str(staged), title, aweme_id, written, total, count)
            _emit(hook, "finished", str(staged), title, aweme_id, written, total, count)
            return written, src
        raise EngineError(str(last_error) if last_error else "没有可用的图片地址")

    @staticmethod
    def _folder(out_dir: str, title: str, aweme_id: str) -> Path:
        safe = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", title).strip(" ._")
        return Path(out_dir) / f"{safe[:120] or '抖音图文'} [{aweme_id}]"


def _ext_of(url: str) -> str:
    head = url.split("?", 1)[0]
    for suffix in (".jpeg", ".jpg", ".webp", ".png"):
        if head.lower().endswith(suffix):
            return "jpg" if suffix in (".jpeg", ".jpg") else suffix[1:]
    return "jpg"


def _emit(hook, status: str, filename: str, title: str, aweme_id: str,
          downloaded: int, total: int, files_total: int) -> None:
    """按 yt-dlp 的进度回调形状上报，下载管理器无需为图文另写一套聚合"""
    if hook is None:
        return
    hook({
        "status": status,
        "filename": filename,
        "downloaded_bytes": downloaded,
        "total_bytes": total or downloaded,
        "info_dict": {
            "title": title,
            "id": aweme_id,
            "extractor_key": "Douyin图文",
            "requested_formats": [None] * max(1, files_total),
        },
    })


douyin_engine = DouyinEngine()


def probe(url: str) -> dict:
    return douyin_engine.probe(url)


def list_levels(url: str) -> dict:
    return douyin_engine.list_levels(url)


def resolve_stream(url: str, prefer: str = "worst") -> dict:
    return douyin_engine.resolve_stream(url, prefer)


def download(url: str, **kwargs) -> dict:
    return douyin_engine.download(url, **kwargs)


def locate(url: str) -> tuple[str, str]:
    return douyin_engine.locate(url)
