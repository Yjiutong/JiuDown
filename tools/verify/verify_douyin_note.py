# -*- coding: utf-8 -*-
"""验证抖音图文抓取：URL 识别、后端路由顺序、双取数路径、原图落盘与卡片呈现

图文是 yt-dlp 的盲区（DouyinIE._VALID_URL 只匹配 /video/），所以本后端的价值
全部在"yt-dlp 判定 Unsupported URL 之后还能不能把东西下下来"。落盘与卡片两段
用离线桩跑通，不依赖网络；结尾的真实链接用例在网络可达时才执行，失败只报 SKIP。
"""
import json
import os
import shutil
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setStyle("Fusion")

from theme import load_mode, theme_manager
theme_manager.set_mode(load_mode(), persist=False)

import douyin_engine as de
import jiudown_engine as je

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


NOTE_URL = "https://www.douyin.com/note/7701734088935693674?previous_page=app_code_link"
SHARE_URL = "https://www.iesdouyin.com/share/note/7701734088935693674/"
VIDEO_URL = "https://www.douyin.com/video/7700808037950426383"
SLIDES_URL = "https://www.douyin.com/slides/7701734088935693674"
SHORT_URL = "https://v.douyin.com/Ozk5d6sLJeM/"
BILI_URL = "https://www.bilibili.com/video/BV1GJ411x7h7"

JPEG = b"\xff\xd8\xff\xe0" + b"JFIF" + b"\x00" * 40
WEBP = b"RIFF" + (48).to_bytes(4, "little") + b"WEBPVP8 " + b"\x00" * 40
GIF = b"GIF89a" + b"\x00" * 40          # 抖音风控占位图就是这一种
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000")

# ---------------------------------------------------------------- 链接识别

check("图文链接判定为图文", de.is_note_url(NOTE_URL))
check("分享页图文判定为图文", de.is_note_url(SHARE_URL))
check("slides 形态等同图文", de.is_note_url(SLIDES_URL))
check("视频链接不是图文", not de.is_note_url(VIDEO_URL))
check("B 站链接不是图文", not de.is_note_url(BILI_URL))
check("抖音域名识别", de.matches(SHORT_URL) and de.matches(VIDEO_URL))
check("非抖音域名不认领", not de.matches(BILI_URL) and not de.matches("https://youtu.be/x"))
check("图文短链不预先认领（要解析后才知道）", not de.is_note_url(SHORT_URL))
check("形态直读：图文", de._aweme_ref(NOTE_URL) == ("note", "7701734088935693674"))
check("形态直读：视频", de._aweme_ref(VIDEO_URL) == ("video", "7700808037950426383"))
check("形态直读：slides 归入图文", de._aweme_ref(SLIDES_URL) == ("note", "7701734088935693674"))

# ---------------------------------------------------------------- 后端路由

eng = je.JiuDownEngine()
check("图文先自研后 yt-dlp", eng._plan(NOTE_URL) == ["douyin", "ytdlp"])
check("抖音视频先 yt-dlp（行为不变）", eng._plan(VIDEO_URL) == ["ytdlp", "douyin"])
check("未解析的短链先 yt-dlp", eng._plan(SHORT_URL) == ["ytdlp", "douyin"])
check("B 站仍先 native", eng._plan(BILI_URL) == ["native", "ytdlp"])
check("普通站点只有 yt-dlp", eng._plan("https://v.qq.com/x/cover/a.html") == ["ytdlp"])

de.douyin_engine._cache_put(SHORT_URL, ("note", "7701734088935693674"))
check("短链解析成图文后不再撞 yt-dlp", eng._plan(SHORT_URL) == ["douyin", "ytdlp"])
de.douyin_engine._cache_put("https://v.douyin.com/aaa/", ("video", "1234567890"))
check("短链解析成视频后仍交 yt-dlp", eng._plan("https://v.douyin.com/aaa/") == ["ytdlp", "douyin"])

check("NotHandled 不是用户可见错误", not issubclass(de.NotHandled, je.EngineError))

# 视频形态必须让路：在发起任何分享页请求之前就抛 NotHandled
calls = []
de.douyin_engine._page = lambda aweme_id, **kw: calls.append(aweme_id) or ""
try:
    de.douyin_engine.detail(VIDEO_URL)
    check("抖音视频让路给 yt-dlp", False, "没有抛 NotHandled")
except de.NotHandled:
    check("抖音视频让路给 yt-dlp", True)
except Exception as e:
    check("抖音视频让路给 yt-dlp", False, repr(e)[:60])
check("让路时不发分享页请求", calls == [], str(calls))

# ---------------------------------------------------------------- 字节格式判定

check("魔数识别 jpeg", de._magic_ext(JPEG) == "jpg")
check("魔数识别 webp", de._magic_ext(WEBP) == "webp")
check("魔数识别 gif", de._magic_ext(GIF) == "gif")
check("RIFF 但非 WEBP 不认", de._magic_ext(b"RIFF\0\0\0\0AVI ") == "")
check("非图片不认", de._magic_ext(b"<html>") == "")
check("URL 声称格式", de._want_ext("https://p/a~tplv-dy-aweme-images:q75.jpeg?x=1") == "jpg")
check("无后缀 URL 声称空", de._want_ext("https://p/a") == "")
check("jpeg 地址回 jpeg 内容算合格", de._is_expected_image(JPEG, "https://p/a.jpeg?x=1"))
check("jpeg 地址回 GIF 占位算不合格", not de._is_expected_image(GIF, "https://p/a.jpeg?x=1"))
check("webp 地址回 webp 内容算合格", de._is_expected_image(WEBP, "https://p/a.webp"))
check("webp 地址回 jpeg 内容算不合格", not de._is_expected_image(JPEG, "https://p/a.webp"))
check("未声称格式时按魔数放行", de._is_expected_image(PNG, "https://p/a"))
check("ld+json 实体还原", "&y=1" in de._unescape("https://p/a?x=1&amp;y=1"))
check("地址数组兼容字符串与对象",
      de._as_url_list(["https://a", {"url_list": ["https://b"]}, 7, None])
      == ["https://a", "https://b"])
check("imageCount 非数字时退回实测张数", de._as_int("x", 3) == 3)

# ---------------------------------------------------------------- 取数：两条路径

ITEM = {
    "aweme_id": "7701734088935693674",
    "desc": "如何设定字号比例。#排版 #平面设计",
    "author": {"nickname": "阿冲设计"},
    "images": [
        {
            "url_list": [
                "https://p26-sign.douyinpic.com/a1~tplv-dy-aweme-images:q75.webp?x=1",
                "https://p3-sign.douyinpic.com/a1~tplv-dy-aweme-images:q75.webp?x=1",
                "https://p26-sign.douyinpic.com/a1~tplv-dy-aweme-images:q75.jpeg?x=1",
            ],
            "download_url_list": ["https://p26-sign.douyinpic.com/a1~tplv-dy-water-v2.webp"],
        },
        {"url_list": ["https://p26-sign.douyinpic.com/a2~tplv-dy-aweme-images:q75.webp"]},
    ],
}
LD_HTML = ('<script data-rh="true" type="application/ld+json">'
           '{"@type":"Article","headline":"如何设定字号比例",'
           '"author":{"@type":"Person","name":"阿冲设计"},'
           '"datePublished":"2026-10-28 11:02","imageCount":2,'
           '"image":['
           '"https://p3-pc-sign.douyinpic.com/a~tplv-dy-aweme-images:q75.webp?x-signature=A%2Bb&amp;y=1",'
           '"https://p3-pc-sign.douyinpic.com/b~tplv-dy-aweme-images:q75.webp?x-signature=C&amp;y=1"]}'
           '</script>')
ROUTER_HTML = json.dumps({"loaderData": {"note_(id)/page": {
    "videoInfoRes": {"item_list": [ITEM]}}}}, ensure_ascii=False)
SSR_PAGE = "_ROUTER_DATA = %s</script>" % ROUTER_HTML


def stub_pages(ssr="", ld=""):
    """_page 按 use_cookie 分派：SSR 那次带 Cookie，ld+json 那次用 Googlebot UA"""
    de.douyin_engine._page = lambda aweme_id, **kw: (ssr if kw.get("use_cookie") else ld)


stub_pages(ld=LD_HTML)
parsed = de.douyin_engine._from_ld_json("7701734088935693674")
check("ld+json 取到全部图片", parsed and len(parsed["sources"]) == 2)
check("ld+json 地址实体已还原", "&y=1" in parsed["sources"][0][0])
check("ld+json 取标题", parsed["title"] == "如何设定字号比例")
check("ld+json 取作者", parsed["author"] == "阿冲设计")
check("ld+json 声明张数", parsed["declared_count"] == 2)
stub_pages()
check("页面没数据时返回 None", de.douyin_engine._from_ld_json("1") is None)
stub_pages(ld='<script type="application/ld+json">{坏 JSON')
check("坏 JSON 不炸", de.douyin_engine._from_ld_json("1") is None)

groups = de.DouyinEngine.image_candidates(ITEM)
check("SSR 候选地址按张成组", len(groups) == 2)
check("SSR 首选是无水印 jpeg", groups[0][0].endswith(".jpeg?x=1"), groups[0][0][-10:])
check("SSR 带水印地址排在最后", groups[0][-1] == ITEM["images"][0]["download_url_list"][0])
check("SSR 每张保留全部镜像", len(groups[0]) == 4, str(len(groups[0])))
check("SSR 标题取作品描述", de.DouyinEngine.title_of(ITEM).startswith("如何设定字号比例"))
check("SSR 作者取昵称", de.DouyinEngine.author_of(ITEM) == "阿冲设计")
check("缺 url_list 的图被跳过", de.DouyinEngine.image_candidates(
    {"images": [{"url_list": []}, {"url_list": ["https://x/b.webp"]}]}) == [["https://x/b.webp"]])

stub_pages(ssr=SSR_PAGE)
built = de.douyin_engine._from_ssr("7701734088935693674")
check("SSR 路径解析成功",
      built and len(built["sources"]) == 2 and built["author"] == "阿冲设计")
stub_pages(ssr="<html>没有 _ROUTER_DATA</html>")
check("SSR 空壳页返回 None", de.douyin_engine._from_ssr("1") is None)

# detail() 把两条路径按张合并：SSR 的 jpeg 与镜像在前，ld+json 的地址补在最后
stub_pages(ssr=SSR_PAGE, ld=LD_HTML)
got = de.douyin_engine.detail(NOTE_URL)
check("两条路径都有数据时按张合并候选",
      len(got["sources"]) == 2 and len(got["sources"][0]) == len(groups[0]) + 1,
      f"第1张候选数={len(got['sources'][0])}")
check("合并后仍优先用 jpeg", got["sources"][0][0].endswith(".jpeg?x=1"))
check("ld+json 地址被并进该张候选",
      got["sources"][0][-1].startswith("https://p3-pc-sign"))
check("合并取 SSR 的标题（ld 的 headline 更干净，优先用它）",
      got["title"] == "如何设定字号比例")
stub_pages(ld=LD_HTML)
got = de.douyin_engine.detail(NOTE_URL)
check("SSR 取不到时只用 ld+json", got["sources"][0][0].startswith("https://p3-pc-sign"))
check("只用 ld+json 时张数仍完整", len(got["sources"]) == 2)
stub_pages(ssr=SSR_PAGE)
got = de.douyin_engine.detail(NOTE_URL)
check("ld+json 取不到时只用 SSR", got["sources"] == groups)
stub_pages()
try:
    de.douyin_engine.detail(NOTE_URL)
    check("两条路径都空时必须报错", False)
except je.EngineError as err:
    check("两条路径都空时必须报错", "图集数据" in str(err), str(err)[:40])
    check("报错文案给出可行动指引", "稍后重试" in str(err))


def test_merge(primary, extra):
    return de._merge_sources(primary, extra)


check("合并保留双方且去重",
      test_merge([["a", "b"]], [["b", "c"]]) == [["a", "b", "c"]],
      str(test_merge([["a", "b"]], [["b", "c"]])))
check("一侧为空时按另一侧张数走", test_merge([["a"], ["b"]], []) == [["a"], ["b"]])
check("两侧张数不等时不互相冒充",
      test_merge([["a"], ["b"]], [["z"]]) == [["a", "z"], ["b"]],
      str(test_merge([["a"], ["b"]], [["z"]])))
check("解析结果带上作品号", got["aweme_id"] == "7701734088935693674")

# ---------------------------------------------------------------- 档位结构

def make_note(src_groups):
    return {
        "sources": src_groups, "title": "如何设定字号比例。#排版 #平面设计",
        "author": "阿冲设计", "declared_count": len(src_groups),
        "aweme_id": "7701734088935693674",
    }


de.douyin_engine.detail = lambda url: make_note(groups)
levels = de.douyin_engine.list_levels(NOTE_URL)
check("图文档位数 1", len(levels["levels"]) == 1)
check("图文档位名是原图", levels["levels"][0]["label"] == "原图")
check("图文档位可选", levels["levels"][0]["available"] is True)
check("图文带张数", levels["image_count"] == 2)
check("图文带形态标记", levels["kind"] == "note")
check("图文标题回填", levels["title"].startswith("如何设定字号比例"))

probe = de.douyin_engine.probe(NOTE_URL)
check("probe 标记为图文", probe["kind"] == "note" and probe["image_count"] == 2)
check("probe 首图作缩略图", probe["thumbnail"] == groups[0][0])
check("probe 站点名可读", probe["extractor"] == "Douyin图文")
check("probe 带作者", probe["uploader"] == "阿冲设计")

from ytdlp_engine import pick_default_level
picked = pick_default_level(levels["levels"], "1080P")
check("默认档位落到原图", (picked or {}).get("label") == "原图", str(picked))

try:
    de.douyin_engine.resolve_stream(NOTE_URL)
    check("图文拒绝视频预览", False)
except je.EngineError as e:
    check("图文拒绝视频预览", "视频流" in str(e))

# ---------------------------------------------------------------- 落盘

WORK = ROOT / "TEMP" / "verify_douyin"
if WORK.exists():
    shutil.rmtree(WORK)
OUT, TMP = WORK / "out", WORK / "tmp"
OUT.mkdir(parents=True), TMP.mkdir(parents=True)


def body_for(url):
    """按地址声称的格式返回对应字节，模拟正常响应"""
    return {"jpg": JPEG, "webp": WEBP, "png": PNG}.get(de._want_ext(url), PNG)


class FakeResp:
    def __init__(self, body, declared=None):
        self._body = body
        self.headers = {"Content-Length": str(len(body) if declared is None else declared)}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=0):
        for i in range(0, len(self._body), 7):
            yield self._body[i:i + 7]


def dl(src_groups, stub, sub, hook=None):
    box = OUT / sub
    box.mkdir(parents=True, exist_ok=True)
    de.douyin_engine.detail = lambda url: make_note(src_groups)
    de.douyin_engine._get = stub
    return de.douyin_engine.download(NOTE_URL, out_dir=str(box), temp_dir=str(TMP),
                                     progress_hook=hook)


events = []
result = dl(groups, lambda url, **kw: FakeResp(body_for(url)), "main", hook=events.append)
saved = sorted(Path(result["filepath"]).iterdir())
check("产物是文件夹", Path(result["filepath"]).is_dir())
check("文件名是标题+作品号",
      saved[0].parent.name == "如何设定字号比例。#排版 #平面设计 [7701734088935693674]",
      saved[0].parent.name)
check("按序补零并按真实内容命名", [p.name for p in saved] == ["01.jpg", "02.webp"],
      str([p.name for p in saved]))
check("张数回报正确", result["file_count"] == 2)
check("字节数累计", result["bytes"] == sum(p.stat().st_size for p in saved))
check("后端标记图文", result["kind"] == "note" and result["extractor"] == "Douyin图文")
check("暂存目录已清空", list(TMP.iterdir()) == [], str([p.name for p in TMP.iterdir()]))
check("成品目录不留 .part", not any(p.suffix == ".part" for p in Path(OUT).rglob("*")))

down = [e for e in events if e["status"] == "downloading"]
fin = [e for e in events if e["status"] == "finished"]
check("每张图各一次下载与完成事件", len(down) == 2 and len(fin) == 2,
      "%d/%d" % (len(down), len(fin)))
check("进度按张数聚合（requested_formats=2）",
      len(down[0]["info_dict"]["requested_formats"]) == 2)
check("进度里带的标题与作品号可用于卡片",
      down[0]["info_dict"]["title"].startswith("如何设定字号比例")
      and down[0]["info_dict"]["id"] == "7701734088935693674")

# 单张首选地址失败时必须换该张的下一个候选
seen = []
BROKEN = groups[0][0]


def flaky(url, **kw):
    seen.append(url)
    if url == BROKEN:
        raise RuntimeError("首选镜像挂了")
    return FakeResp(body_for(url))


r2 = dl(groups, flaky, "flaky")
check("单张首选失败时自动换候选地址", r2["file_count"] == 2, str(r2["file_count"]))
check("失败的首选被跳过、次选被用上", BROKEN in seen and groups[0][1] in seen,
      "seen=%d" % len(seen))

# 风控占位图必须被识破并换候选，绝不能落盘成"扩展名是 jpg 内容是 gif"的文件
def leeching(url, **kw):
    return FakeResp(GIF) if url == groups[0][0] else FakeResp(body_for(url))


r3 = dl(groups, leeching, "leech")
files3 = sorted(Path(r3["filepath"]).iterdir())
check("GIF 占位图被拒收",
      all(de._magic_ext(p.read_bytes()[:16]) != "gif" for p in files3),
      str([p.name for p in files3]))
check("占位图后换候选取到真图", len(files3) == 2)
check("命名跟随换用后的真实内容", files3[0].name == "01.webp", files3[0].name)

check("0 字节响应被换候选接住",
      dl(groups, lambda url, **kw: (FakeResp(b"") if url == groups[0][0]
                                    else FakeResp(body_for(url))), "empty")["file_count"] == 2)
check("截断响应被换候选接住",
      dl(groups, lambda url, **kw: (FakeResp(JPEG[:16], declared=len(JPEG))
                                    if url == groups[0][0]
                                    else FakeResp(body_for(url))), "trunc")["file_count"] == 2)

try:
    dl(groups, lambda url, **kw: FakeResp(GIF), "allbad")
    check("所有候选都是占位图时明确报错", False)
except je.EngineError as e:
    check("所有候选都是占位图时明确报错", "格式" in str(e), str(e)[:60])
check("占位图全程不落盘", not any((OUT / "allbad").rglob("01.gif")))

# 成批瞬态失败：第一轮候选全撞风控时，退避后整轮重来应当救得回来
de._SAVE_BACKOFF = 0.01
attempts = {"n": 0}


def burst(url, **kw):
    attempts["n"] += 1
    if attempts["n"] <= len(groups[0]):
        return FakeResp(GIF)
    return FakeResp(body_for(url))


check("候选整轮失败后退避重跑能救回",
      dl(groups, burst, "burst")["file_count"] == 2, "尝试次数=%d" % attempts["n"])
check("重跑轮次确实用了新的地址", attempts["n"] > len(groups[0]),
      "尝试次数=%d" % attempts["n"])

try:
    dl(groups, lambda url, **kw: (_ for _ in ()).throw(RuntimeError("网络断开")), "boom")
    check("网络中断必须整体报错", False)
except je.EngineError as e:
    check("网络中断必须整体报错", "下载失败" in str(e), str(e)[:60])
check("失败时暂存不留半张图", list(TMP.iterdir()) == [], str([p.name for p in TMP.iterdir()]))

# ld+json 形态每张图只有一个地址，也应完整落盘
r4 = dl([[g[0]] for g in groups], lambda url, **kw: FakeResp(body_for(url)), "single")
check("每图单地址也能完整落盘", r4["file_count"] == 2
      and len(sorted(Path(r4["filepath"]).iterdir())) == 2)

# ---------------------------------------------------------------- 卡片呈现

from pages.download_page import TagCard, TaskCard

card = TagCard(NOTE_URL, "1080P", "mp4")
card.apply_resolution({"ok": True, "info": levels}, "1080P")
check("图文卡片格式徽章改显图文", card.format_badge.text() == "图文", card.format_badge.text())
check("图文卡片张数徽章", card.quality_badge.text() == "2 张原图", card.quality_badge.text())
check("图文卡片详情说明原图整组", "无水印原图" in card.detail_label.text())
check("图文卡片不谎报档位", "档位（" not in card.detail_label.text())

video_levels = {"title": "普通视频", "levels": [
    {"label": "1080P", "height": 1080, "available": True},
    {"label": "720P", "height": 720, "available": True}], "kind": ""}
vcard = TagCard(BILI_URL, "1080P", "mp4")
vcard.apply_resolution({"ok": True, "info": video_levels}, "1080P")
check("视频卡片仍显示档位概览", "档位（2）" in vcard.detail_label.text(),
      vcard.detail_label.text())
check("视频卡片格式徽章不变", vcard.format_badge.text() == "mp4")

task = {
    "id": "t1", "url": NOTE_URL, "title": "如何设定字号比例", "status": "completed",
    "progress": 100, "kind": "note", "image_count": 2, "extractor": "Douyin图文",
    "format": "mp4", "quality": "原图", "levels": levels["levels"],
    "output_path": result["filepath"], "total_size": result["bytes"],
    "duration": 0, "playlist_count": 0, "error": "", "message": "",
}
tcard = TaskCard("t1")
tcard.update_task(task)
check("图文任务卡收起格式下拉", not tcard.format_combo.isVisibleTo(tcard))
check("图文任务卡收起清晰度下拉", not tcard.quality_combo.isVisibleTo(tcard))
check("图文任务卡报张数", "图文 2 张" in tcard.detail_label.text(), tcard.detail_label.text())

tcard.update_task({**task, "kind": "", "extractor": "bilibili"})
check("视频任务卡恢复格式下拉", tcard.format_combo.isVisibleTo(tcard))
check("视频任务卡恢复清晰度下拉", tcard.quality_combo.isVisibleTo(tcard))

# 目录产物：能打开目录本身，且不喂给媒体播放器
import download_manager as dm
from pages.download_page import DownloadPage
from pages.preview_panel import PreviewPanel

dm.download_manager.tasks["t1"] = dict(task)
page = DownloadPage()
touched = []
page.preview_panel = PreviewPanel()
page.preview_panel.play_local_file = lambda p: touched.append(("play", p))
page.preview_panel._show_loading = lambda t: touched.append(("loading", t))
page._cards = {"t1": tcard}
try:
    DownloadPage._open_folder(page, "t1")
    check("目录产物可打开所在目录", True)
except Exception as e:
    check("目录产物可打开所在目录", False, repr(e)[:70])
DownloadPage._preview_task_click(page, "t1")
check("目录产物不进媒体播放器", not any(k == "play" for k, _ in touched), str(touched)[:90])
check("目录产物改为提示存放位置",
      any(k == "loading" and result["filepath"] in v for k, v in touched), str(touched)[:90])

# ---------------------------------------------------------------- 门面不吞错

def fake_fail(url):
    raise de.NotHandled("让路")


de.douyin_engine.probe = fake_fail
de.douyin_engine.list_levels = fake_fail
try:
    eng.probe(NOTE_URL)
    check("两后端都失败时必须报错", False)
except je.EngineError as err:
    # yt-dlp 的真实原因必须留下，NotHandled 不能让错误信息变空
    check("让路信号不污染错误信息", "让路" not in str(err) and str(err).strip() != "",
          str(err)[:70])

# ---------------------------------------------------------------- 真实链接（可选）

de.douyin_engine = de.DouyinEngine()   # 丢弃上面的桩，恢复真实实现
try:
    live = de.douyin_engine.list_levels(NOTE_URL)
    ok = live["image_count"] > 1 and live["levels"][0]["label"] == "原图"
    check("真实图文链接可解析", ok, f"{live['image_count']} 张 · {live['title'][:20]}")
    real = de.douyin_engine.detail(NOTE_URL)
    check("真实图文每张都有可用候选",
          len(real["sources"]) == live["image_count"] and all(real["sources"]),
          f"每张候选数={len(real['sources'][0])}")
except Exception as e:
    print(f"SKIP 真实图文链接（网络不可达）: {str(e)[:60]}")

print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
sys.stdout.flush()
os._exit(0 if not FAIL else 1)
