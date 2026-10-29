# -*- coding: utf-8 -*-
"""验证抖音图文抓取：URL 识别、后端路由顺序、原图挑选、多图落盘与卡片呈现

图文是 yt-dlp 的盲区（DouyinIE._VALID_URL 只匹配 /video/），所以本后端的价值
全部在"yt-dlp 判定 Unsupported URL 之后还能不能把东西下下来"。落盘与卡片两段
用离线桩跑通，不依赖网络；结尾的真实链接用例在网络可达时才执行，失败只报 SKIP。
"""
import io
import os
import shutil
import sys
import types
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

try:
    je.douyin_engine.NotHandled  # 让路信号必须存在且不是 EngineError
    check("NotHandled 不是用户可见错误",
          not issubclass(de.NotHandled, je.EngineError))
except AttributeError:
    check("NotHandled 不是用户可见错误", False, "缺少 NotHandled")

# 视频形态必须让路：detail() 在发起分享页请求之前就抛 NotHandled
calls = []
de.douyin_engine._item = lambda kind, aweme_id: calls.append(kind) or {}
try:
    de.douyin_engine.detail(VIDEO_URL)
    check("抖音视频让路给 yt-dlp", False, "没有抛 NotHandled")
except de.NotHandled:
    check("抖音视频让路给 yt-dlp", True)
except Exception as e:
    check("抖音视频让路给 yt-dlp", False, repr(e)[:60])
check("让路时不发分享页请求", calls == [], str(calls))

# ---------------------------------------------------------------- 原图挑选

ITEM = {
    "aweme_id": "7701734088935693674",
    "desc": "如何设定字号比例。#排版 #平面设计",
    "author": {"nickname": "阿冲设计"},
    "images": [
        {
            "url_list": [
                "https://p26-sign.douyinpic.com/a1~tplv-dy-aweme-images:q75.webp?x-expires=1",
                "https://p3-sign.douyinpic.com/a1~tplv-dy-aweme-images:q75.webp?x-expires=1",
                "https://p26-sign.douyinpic.com/a1~tplv-dy-aweme-images:q75.jpeg?x-expires=1",
            ],
            "download_url_list": ["https://p26-sign.douyinpic.com/a1~tplv-dy-water-v2.webp"],
        },
        {
            "url_list": ["https://p26-sign.douyinpic.com/a2~tplv-dy-aweme-images:q75.webp"],
        },
    ],
}

urls = de.DouyinEngine.image_urls(ITEM)
check("每张图只取一个地址", len(urls) == 2, str(len(urls)))
check("优先无水印 jpeg", ".jpeg" in urls[0], urls[0][-24:])
check("不取带水印的 download_url_list", "water" not in "".join(urls))
check("无 jpeg 镜像时退回 webp", urls[1].endswith(".webp"))
check("缺 url_list 的图被跳过", de.DouyinEngine.image_urls(
    {"images": [{"url_list": []}, {"url_list": ["https://x/b.webp"]}]}) == ["https://x/b.webp"])
check("标题取作品描述", de.DouyinEngine.title_of(ITEM) == "如何设定字号比例。#排版 #平面设计")
check("作者取昵称", de.DouyinEngine.author_of(ITEM) == "阿冲设计")
check("扩展名归一：jpeg→jpg", de._ext_of("https://p/x~tplv.jpeg?s=1") == "jpg")
check("扩展名保留 webp", de._ext_of("https://p/x~tplv.webp?s=1") == "webp")
groups = de.DouyinEngine.image_candidates(ITEM)
check("候选地址按张成组", len(groups) == 2)
check("首选是无水印 jpeg", groups[0][0].endswith(".jpeg?x-expires=1"), groups[0][0][-14:])
check("带水印地址排在最后", groups[0][-1] == ITEM["images"][0]["download_url_list"][0])
check("全部候选都不含水印地址以外在前", "water" not in groups[0][0] + groups[0][1])

# ---------------------------------------------------------------- 档位结构

de.douyin_engine.detail = lambda url: ITEM
levels = de.douyin_engine.list_levels(NOTE_URL)
check("图文档位数 1", len(levels["levels"]) == 1)
check("图文档位名是原图", levels["levels"][0]["label"] == "原图")
check("图文档位可选", levels["levels"][0]["available"] is True)
check("图文带张数", levels["image_count"] == 2)
check("图文带形态标记", levels["kind"] == "note")
check("图文标题回填", levels["title"].startswith("如何设定字号比例"))

probe = de.douyin_engine.probe(NOTE_URL)
check("probe 标记为图文", probe["kind"] == "note" and probe["image_count"] == 2)
check("probe 首图作缩略图", probe["thumbnail"] == urls[0])
check("probe 站点名可读", probe["extractor"] == "Douyin图文")

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

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000")


class FakeResp:
    def __init__(self, body):
        self._body, self.headers = body, {"Content-Length": str(len(body))}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=0):
        for i in range(0, len(self._body), 7):
            yield self._body[i:i + 7]


events = []
de.douyin_engine._get = lambda url, **kw: FakeResp(PNG + url[-4:].encode())
result = de.douyin_engine.download(
    NOTE_URL, quality="720P", file_format="mp4", level=None,
    out_dir=str(OUT), temp_dir=str(TMP), channels="双声道",
    progress_hook=events.append,
)
saved = sorted(Path(result["filepath"]).iterdir())
check("产物是文件夹", Path(result["filepath"]).is_dir())
check("文件名是标题+作品号", saved[0].parent.name == "如何设定字号比例。#排版 #平面设计 [7701734088935693674]",
      saved[0].parent.name)
check("按序补零命名并按各自形态取扩展名",
      [p.name for p in saved] == ["01.jpg", "02.webp"], str([p.name for p in saved]))
check("张数回报正确", result["file_count"] == 2)
check("字节数累计", result["bytes"] == sum(p.stat().st_size for p in saved))
check("后端标记图文", result["kind"] == "note" and result["extractor"] == "Douyin图文")
check("暂存目录已清空", list(TMP.iterdir()) == [], str([p.name for p in TMP.iterdir()]))
check("每张图都有下载与完成事件",
      len([e for e in events if e["status"] == "downloading"]) == 2
      and len([e for e in events if e["status"] == "finished"]) == 2)
first = next(e for e in events if e["status"] == "downloading")
check("进度按张数聚合（requested_formats=2）",
      len(first["info_dict"]["requested_formats"]) == 2)

# 中断时不能留下半张图
def boom(url, **kw):
    raise RuntimeError("网络断开")


# 只让第 1 张的首选取址失败：必须自动换该张的下一个候选
seen = []
BROKEN = groups[0][0]


def flaky(url, **kw):
    seen.append(url)
    if url == BROKEN:
        raise RuntimeError("首选镜像挂了")
    return FakeResp(PNG + url[-4:].encode())


de.douyin_engine._get = flaky
r2 = de.douyin_engine.download(NOTE_URL, out_dir=str(OUT), temp_dir=str(TMP))
check("单张首选失败时自动换候选地址", r2["file_count"] == 2, str(r2["file_count"]))
check("失败的首选被跳过、次选被用上",
      BROKEN in seen and groups[0][1] in seen,
      "seen=%d" % len(seen))

# 该张所有候选都失败才整体报错
de.douyin_engine._get = boom
try:
    de.douyin_engine.download(NOTE_URL, out_dir=str(OUT), temp_dir=str(TMP))
    check("全部候选失败才整体报错", False)
except je.EngineError as e:
    check("全部候选失败才整体报错", "下载失败" in str(e), str(e)[:60])
check("失败时暂存不留半张图", list(TMP.iterdir()) == [], str([p.name for p in TMP.iterdir()]))

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
vcard = TagCard("https://www.bilibili.com/video/BV1xx", "1080P", "mp4")
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

# ---------------------------------------------------------------- 门面不吞错

def fake_fail(url):
    raise de.NotHandled("让路")


de.douyin_engine.probe = fake_fail
de.douyin_engine.list_levels = fake_fail
try:
    eng.probe(NOTE_URL)
    check("两后端都失败时必须报错", False)
except je.EngineError as e:
    # yt-dlp 的真实原因必须留下，NotHandled 不能让错误信息变空
    check("让路信号不污染错误信息", "让路" not in str(e) and str(e).strip() != "", str(e)[:70])

# ---------------------------------------------------------------- 真实链接（可选）

de.douyin_engine = de.DouyinEngine()   # 丢弃上面的桩，恢复真实实现
try:
    live = de.douyin_engine.list_levels(NOTE_URL)
    ok = live["image_count"] > 1 and live["levels"][0]["label"] == "原图"
    check("真实图文链接可解析", ok, f"{live['image_count']} 张 · {live['title'][:20]}")
except Exception as e:
    print(f"SKIP 真实图文链接（网络不可达）: {str(e)[:60]}")

print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
sys.stdout.flush()
os._exit(0 if not FAIL else 1)
