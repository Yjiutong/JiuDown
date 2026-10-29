"""
抖音图文（图集）原生引擎

为什么需要单独一个后端：yt-dlp 的 DouyinIE._VALID_URL 只匹配
douyin.com/video/<id>，图文形态（douyin.com/note/<id>）落到通用提取器后被判定
Unsupported URL，抖音图文链接因此在本项目里全量失败。

图文也没有视频流可下：服务端把图集渲染成 mp4 的 /aweme/v1/playwm/ 已返回 404，
去水印的 /play/ 返回空响应体。唯一能取到的产物是原图，所以本后端的下载结果是
**一个装原图的文件夹**，而不是单个媒体文件。

两条取数路径，读到的张数一致（实测同一条图文 55/55、262/262，分辨率也一致），
因此按张**合并**成候选列表而不是二选一：
  1. _ROUTER_DATA：移动端 UA + 匿名 ttwid 请求 iesdouyin 图文分享页，item_list 里
     每张图给出 3~4 个 CDN 镜像，其中含一个 jpeg 变体——jpeg 比 webp 通用，排在最前。
     缺 ttwid 时这个页面只是个不含图集的空壳。
  2. ld+json：Googlebot UA 请求同一页面，服务端会做完整 SSR，
     `<script type="application/ld+json">` 里的 image[] 就是正文全部图片，完全不依赖
     Cookie。代价是每张图只有一个 webp 地址。

合并后单张约 5 个候选，成批的瞬态失败更难一锅端；两条路径任一失效，图文仍下得动。
批量取图时抖音会成批地返回 0 字节或占位图，所以候选跑完还要退避重跑一轮。

地址取舍：只取 url_list / ld+json 给出的无水印地址。images[i].download_url_list
是叠加了作者水印的另一套地址（tplv-dy-water-v2），始终排在最后才用。
签名地址带 x-expires，过期就 403，因此解析结果只短期复用。
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
EXTRACTOR_NAME = "Douyin图文"

BOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

# /note/<id>、/share/note/<id>、/slides/<id>（slides 是图文的另一条路径别名）
_ITEM_RE = re.compile(r"/(?:share/)?(note|video|slides)/(\d{6,})")
_ROUTER_RE = re.compile(r"_ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>", re.S)
_LD_RE = re.compile(
    r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I
)

_RESOLVE_TTL = 600.0
_RESOLVE_LIMIT = 64
_SAVE_ROUNDS = 3          # 成批瞬态失败时，候选跑完再退避重来的轮数
_SAVE_BACKOFF = 0.8       # 每轮之间的等待（秒），第 N 轮等 (N-1)*该值


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
    """抖音图文抓取：短链解析 → 分享页 → 原图批量落盘"""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": BOT_UA})
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

    def _get(self, url: str, *, ua: str = "", referer: str = "", timeout: int = 20,
             allow_redirects: bool = True, stream: bool = False) -> requests.Response:
        headers = {}
        if ua:
            headers["User-Agent"] = ua
        if referer:
            headers["Referer"] = referer
        return self._session.get(
            url, headers=headers, timeout=timeout,
            allow_redirects=allow_redirects, proxies=self._proxies(), stream=stream,
        )

    def _ensure_ttwid(self) -> None:
        """领匿名 ttwid：缺它时移动端 UA 下的图文分享页只返回不含图集的空壳"""
        if self._ttwid_ready:
            return
        with self._lock:
            if self._ttwid_ready:
                return
            try:
                self._session.get(TTWID_SEED, headers={"User-Agent": MOBILE_UA}, timeout=15)
            except Exception as e:
                logger.debug(f"ttwid 播种失败（继续尝试）: {e}")
            self._ttwid_ready = True

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
            location = resp.headers.get("Location") or ""
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

    # ---------------------------------------------------------------- 取数

    def detail(self, url: str) -> dict:
        """取图集数据；图文以外的形态抛 NotHandled（视频仍由 yt-dlp 负责）

        两条路径都读：SSR 提供 jpeg 首选与每图多个镜像，ld+json 提供一条不依赖
        Cookie 的独立地址。合并后单张约有 5 个候选，成批的瞬态失败更难一锅端；
        任一页取不到另一页仍在，抖音改版打掉一条也不至于全瞎。
        """
        kind, aweme_id = self.locate(url)
        if kind != NOTE_KIND:
            raise NotHandled("抖音视频由 yt-dlp 处理")
        ssr = self._from_ssr(aweme_id)
        ld = self._from_ld_json(aweme_id)
        sources = _merge_sources(
            ssr["sources"] if ssr else [], ld["sources"] if ld else [])
        if not sources:
            raise EngineError(
                "抖音图文解析失败：分享页没有返回图集数据"
                "（可能已被风控，或该图文已删除，稍后重试）"
            )
        note = {
            "sources": sources,
            "title": (ld or {}).get("title") or (ssr or {}).get("title") or "",
            "author": (ld or {}).get("author") or (ssr or {}).get("author") or "",
            "declared_count": max((ld or {}).get("declared_count") or 0,
                                  (ssr or {}).get("declared_count") or 0, len(sources)),
            "aweme_id": aweme_id,
        }
        return note

    def _page(self, aweme_id: str, *, ua: str, use_cookie: bool = False) -> str:
        page = SHARE_PAGE.format(kind=NOTE_KIND, aweme_id=aweme_id)
        if use_cookie:
            self._ensure_ttwid()
        try:
            resp = self._get(page, ua=ua, referer="https://www.douyin.com/", timeout=25)
            resp.raise_for_status()
            return resp.text or ""
        except Exception as e:
            logger.debug(f"抖音分享页请求失败(cookie={use_cookie}): {e}")
            return ""

    def _from_ld_json(self, aweme_id: str) -> Optional[dict]:
        """路径二：Googlebot UA 下的服务端渲染数据

        ld+json 的 image[] 就是正文全部图片（已按多条真实图文核对，张数与页面
        轮播计数、与 _ROUTER_DATA 都一致），且完全不依赖 Cookie——冷启动一次
        请求就能拿到。代价是每张图只有一个 webp 地址，没有镜像可换。
        """
        html = self._page(aweme_id, ua=BOT_UA)
        for block in _LD_RE.findall(html or ""):
            try:
                data = json.loads(_unescape(block.strip()))
            except Exception:
                continue
            images = data.get("image")
            if not isinstance(images, list) or not images:
                continue
            urls = [u for u in _as_url_list(images) if u]
            if not urls:
                continue
            author = data.get("author")
            return {
                "sources": [[u] for u in urls],
                "title": str(data.get("headline") or "").strip(),
                "author": str((author or {}).get("name") or "").strip()
                if isinstance(author, dict) else str(author or ""),
                "declared_count": _as_int(data.get("imageCount"), len(urls)),
            }
        return None

    def _from_ssr(self, aweme_id: str) -> Optional[dict]:
        item = self._item(aweme_id)
        if not item:
            return None
        return {
            "sources": self.image_candidates(item),
            "title": self.title_of(item),
            "author": self.author_of(item),
            "declared_count": len(item.get("images") or []),
        }

    def _item(self, aweme_id: str) -> Optional[dict]:
        """路径一：移动端 UA + ttwid 才有 item_list，缺 ttwid 时页面是空壳"""
        html = self._page(aweme_id, ua=MOBILE_UA, use_cookie=True)
        match = _ROUTER_RE.search(html or "")
        if not match:
            logger.debug("抖音分享页缺少 _ROUTER_DATA")
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
        logger.debug("抖音分享页 _ROUTER_DATA 内没有 item_list（多半是没领到 ttwid）")
        return None

    # ---------------------------------------------------------------- 数据整理

    @staticmethod
    def image_candidates(item: dict) -> list[list[str]]:
        """每张图的全部候选地址，无水印 jpeg 排在最前

        图文一张图会有 3~4 个 CDN 镜像；单张失败时按候选逐个重试比瞎猜域名可靠。
        download_url_list 是叠了作者水印的另一套地址，始终排在最后才用。
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
        """每张图的首选地址（缩略图用）"""
        return [group[0] for group in cls.image_candidates(item)]

    @staticmethod
    def title_of(item: dict) -> str:
        return str(item.get("desc") or "").strip()

    @staticmethod
    def author_of(item: dict) -> str:
        return str((item.get("author") or {}).get("nickname") or "").strip()

    # ---------------------------------------------------------------- API

    def _info(self, note: dict) -> dict:
        first = note["sources"][0][0] if note["sources"] else ""
        return {
            "id": note.get("aweme_id", ""),
            "title": note.get("title") or "抖音图文",
            "uploader": note.get("author") or "",
            "duration": 0,
            "thumbnail": first,
            "webpage_url": SHARE_PAGE.format(kind=NOTE_KIND, aweme_id=note.get("aweme_id", "")),
            "extractor": EXTRACTOR_NAME,
            "is_live": False,
            "playlist_count": 0,
            "kind": "note",
            "image_count": len(note["sources"]),
        }

    def probe(self, url: str) -> dict:
        return self._info(self.detail(url))

    def list_levels(self, url: str) -> dict:
        """图文的"档位"只有一档：无水印原图"""
        info = self._info(self.detail(url))
        return {
            "title": info["title"],
            "extractor": EXTRACTOR_NAME,
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

    # ---------------------------------------------------------------- 下载

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
        note = self.detail(url)
        sources = [list(group) for group in note["sources"]]
        aweme_id = note["aweme_id"]
        title = note["title"] or "抖音图文"
        folder = self._folder(out_dir, title, aweme_id)
        folder.mkdir(parents=True, exist_ok=True)
        temp_path = Path(temp_dir) if temp_dir else folder
        temp_path.mkdir(parents=True, exist_ok=True)

        count = len(sources)
        width = max(2, len(str(count)))
        total_bytes = 0
        for index, candidates in enumerate(sources, start=1):
            # 先落到 .part：文件名要等真正取到的那个地址定了扩展名才确定，
            # 且中途失败时不会在成品目录里留下半张图
            staged = temp_path / f"{aweme_id}_{index:0{width}d}.part"
            try:
                written, used = self._save(candidates, staged, progress_hook,
                                           title, aweme_id, index, count)
            except Exception as e:
                staged.unlink(missing_ok=True)
                raise EngineError(f"抖音图文第 {index}/{count} 张下载失败：{e}")
            target = folder / f"{index:0{width}d}.{_ext_of(used, staged)}"
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
            "extractor": EXTRACTOR_NAME,
            "duration": 0,
            "bytes": total_bytes,
            "file_count": count,
            "kind": "note",
        }

    def _save(self, candidates: list[str], staged: Path, hook, title: str,
              aweme_id: str, index: int, count: int) -> tuple[int, str]:
        """按候选地址逐个尝试，候选耗尽后退避再跑一轮，全部失败才报错

        空响应、截断响应与风控占位图都算这一候选失败：批量取图时抖音会成批地
        返回 0 字节，或拿一张约 10KB 的 GIF 顶替所请求的图片格式——这类响应
        看着是 200，写进成品目录就成了打不开的文件，所以宁可重来也不能落盘。
        """
        last_error = ""
        for round_no in range(1, _SAVE_ROUNDS + 1):
            if round_no > 1:
                # 成批的瞬态失败换个地址也没用，退让一下再整轮重来
                time.sleep(_SAVE_BACKOFF * (round_no - 1))
                logger.debug(f"抖音原图第 {index} 张整轮失败，退避后重试第 {round_no} 轮")
            for src in candidates:
                try:
                    resp = self._get(src, referer="https://www.douyin.com/",
                                     timeout=30, stream=True)
                    resp.raise_for_status()
                    written = 0
                    with staged.open("wb") as fh:
                        for chunk in resp.iter_content(chunk_size=64 * 1024):
                            if chunk:
                                fh.write(chunk)
                                written += len(chunk)
                    declared = int(resp.headers.get("Content-Length") or 0)
                    if written == 0:
                        raise OSError("返回 0 字节")
                    if declared and written < declared:
                        raise OSError(f"响应被截断（{written}/{declared} 字节）")
                    head = staged.open("rb").read(16)
                    if not _is_expected_image(head, src):
                        raise OSError(
                            f"返回的不是所请求的图片格式（得到 {_magic_ext(head) or '未知'}，"
                            f"要 {_want_ext(src)}），疑似风控占位图"
                        )
                except Exception as e:
                    last_error = str(e)
                    staged.unlink(missing_ok=True)
                    logger.debug(f"抖音原图第 {index} 张该地址不可用，换下一个候选: {e}")
                    continue
                _emit(hook, "downloading", str(staged), title, aweme_id, written, written, count)
                _emit(hook, "finished", str(staged), title, aweme_id, written, written, count)
                return written, src
        raise EngineError(last_error or "没有可用的图片地址")

    @staticmethod
    def _folder(out_dir: str, title: str, aweme_id: str) -> Path:
        safe = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", title).strip(" ._")
        return Path(out_dir) / f"{safe[:120] or '抖音图文'} [{aweme_id}]"


# ---------------------------------------------------------------- 字节格式判定

_MAGIC = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG", "png"),
    (b"RIFF", "webp"),
    (b"GIF8", "gif"),
)


def _magic_ext(head: bytes) -> str:
    for prefix, ext in _MAGIC:
        if head.startswith(prefix):
            if ext == "webp" and head[8:12] != b"WEBP":
                return ""
            return ext
    return ""


def _want_ext(url: str) -> str:
    """地址声称要的格式（~tplv-dy-aweme-images:q75.jpeg → jpg）"""
    head = (url or "").split("?", 1)[0]
    for suffix in (".jpeg", ".jpg", ".webp", ".png", ".gif"):
        if head.lower().endswith(suffix):
            return "jpg" if suffix in (".jpeg", ".jpg") else suffix[1:]
    return ""


def _ext_of(url: str, staged: Optional[Path] = None) -> str:
    """扩展名以落盘字节的真实格式为准，URL 声称的格式只兜底

    抖音 CDN 在批量请求下会用另一种格式顶替所请求的图片，按 URL 命名就会产出
    扩展名与内容对不上的文件。
    """
    if staged is not None:
        try:
            sniffed = _magic_ext(staged.open("rb").read(16))
        except OSError:
            sniffed = ""
        if sniffed:
            return sniffed
    return _want_ext(url) or "jpg"


def _is_expected_image(head: bytes, url: str) -> bool:
    """tplv 转码只输出 jpeg/webp/png，出现 GIF 即风控占位图；其余按声称格式互认"""
    got = _magic_ext(head)
    if not got or got == "gif":
        return False
    want = _want_ext(url)
    return got == want or want == ""


def _merge_sources(primary: list[list[str]], extra: list[list[str]]) -> list[list[str]]:
    """按张把两条路径的地址并成候选列表，primary 的顺序保持在前

    两条路径给出的张数一致（实测 55/55、262/262）；万一哪天不一致，也按多的那张数
    走，只在两边都有时对位合并——绝不拿另一条路径的第 i 张冒充这一张的镜像。
    """
    merged: list[list[str]] = []
    for i in range(max(len(primary), len(extra))):
        seen: list[str] = []
        for group in (primary[i] if i < len(primary) else [],
                      extra[i] if i < len(extra) else []):
            for url in group:
                if url and url not in seen:
                    seen.append(url)
        if seen:
            merged.append(seen)
    return merged


def _as_url_list(value) -> list[str]:
    """ld+json 的 image 是字符串数组，_ROUTER_DATA 的是 {url_list: [...]} 对象"""
    if not isinstance(value, list):
        return []
    urls: list[str] = []
    for entry in value:
        if isinstance(entry, str) and entry:
            urls.append(entry)
        elif isinstance(entry, dict):
            urls.extend(u for u in _as_url_list(entry.get("url_list")) if u)
    return urls


def _as_int(value, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _unescape(text: str) -> str:
    """ld+json 里偶发 HTML 实体（&amp; 常见于签名地址）"""
    return (text.replace("&amp;", "&").replace("&#34;", '"')
                .replace("&quot;", '"').replace("&#39;", "'")
                .replace("&lt;", "<").replace("&gt;", ">"))


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
            "extractor_key": EXTRACTOR_NAME,
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
