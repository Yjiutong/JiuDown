# -*- coding: utf-8 -*-
"""链接输入健壮性验证：粘贴里的不可见字符、标题/分享尾巴，以及出错必须可见

回归点（v1.1.0 之后修）：
1. normalize_url 旧实现要求"整行就是一个 URL"，微信/QQ/网页粘贴常带的零宽字符、
   BOM、标题前缀、"来自 微博网页版"尾巴会让整行判为无效 → 回车什么都不发生
2. 不换行空格/全角空格是分隔符，直接删会把 "…/abc\u00a0tail" 粘成一个不存在的 URL
3. 应用用 pythonw 启动时没有控制台，Qt 槽里的异常只写 stderr，表现为"静默无反应"
"""
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

from config_manager import config_manager  # noqa: E402

config_manager.initialize()

from ytdlp_engine import normalize_url  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  {extra}" if extra else ""))


URL = "https://b23.tv/abc123"
cases = [
    ("纯链接", URL, URL),
    ("零宽空格前缀", f"​{URL}", URL),
    ("BOM 前缀", f"﻿{URL}", URL),
    ("双向控制符", f"‪{URL}", URL),
    ("不换行空格分隔", f"{URL} tail", URL),
    ("全角空格包裹", f"　{URL}　", URL),
    ("标题在前的分享", f"【官方 MV】Never Gonna {URL}", URL),
    ("中文尾巴", f"{URL} 来自 微博网页版", URL),
    ("中文句号结尾", f"{URL}。", URL),
    ("英文括号包裹", f"({URL})", URL),
    ("带引号", f'"{URL}"', URL),
    ("只有域名", "www.bilibili.com/video/BV1GJ", "https://www.bilibili.com/video/BV1GJ"),
    ("带端口与查询", "https://example.com:8443/watch?v=1", "https://example.com:8443/watch?v=1"),
    ("B站分享全文", f"【B站】[AI绘图简史04]开源与闭源 {URL}/?spm_id_from=333.788.share",
     f"{URL}/?spm_id_from=333.788.share"),
    ("只有 BV 号无链接", "[AI绘图简史04]开源与闭源 BV1yE421X7je",
     "https://www.bilibili.com/video/BV1yE421X7je"),
    ("只有 av 号无链接", "看这个 av170001", "https://www.bilibili.com/video/av170001"),
    ("中文逗号尾巴", f"{URL}，快来看看", URL),
    ("全角右括号尾巴", f"{URL}）", URL),
]
for name, raw, want in cases:
    got = normalize_url(raw)
    ck(f"输入识别/{name}", got == want, f"-> {got!r}")

for name, raw in [("空行", "   "), ("纯中文", "今天天气不错"), ("无域名", "localhost")]:
    ck(f"应判为无效/{name}", normalize_url(raw) == "", repr(normalize_url(raw)))

app = QApplication.instance() or QApplication([])
from PySide6.QtCore import QMimeData  # noqa: E402

from pages.download_page import DownloadPage, UrlInputEdit, _pasted_links  # noqa: E402

# 粘贴"带链接的标题"：剪贴板是 <a href="URL">标题</a>，QTextEdit 默认只留可见文字，
# href 在进输入框之前就被丢掉——用户粘的确实是链接，看到的却是标题。
TITLE = "[AI绘图简史04]开源与闭源的三次交锋?_哔哩哔哩_bilibili"
LINKED = QMimeData()
LINKED.setHtml(f'<a href="{URL}">{TITLE}</a>')
LINKED.setText(TITLE)
ck("粘贴取 href", _pasted_links(LINKED) == [URL], str(_pasted_links(LINKED)))
box = UrlInputEdit()
box.insertFromMimeData(LINKED)
ck("粘贴后框内是链接不是标题", box.toPlainText() == URL, repr(box.toPlainText()))

PLAIN = QMimeData()
PLAIN.setText(URL)
box_p = UrlInputEdit()
box_p.insertFromMimeData(PLAIN)
ck("纯文本粘贴不受影响", box_p.toPlainText() == URL, repr(box_p.toPlainText()))

MULTI = QMimeData()
MULTI.setHtml(f'<a href="{URL}">A</a><a href="https://b23.tv/xyz">B</a>')
MULTI.setText("AB")
box_m = UrlInputEdit()
box_m.insertFromMimeData(MULTI)
ck("多个链接一行一个", box_m.toPlainText() == f"{URL}\nhttps://b23.tv/xyz",
   repr(box_m.toPlainText()))

NOHREF = QMimeData()
NOHREF.setText("就是没有链接的一行中文")
box_n = UrlInputEdit()
box_n.insertFromMimeData(NOHREF)
ck("无链接粘贴走默认路径", box_n.toPlainText() == "就是没有链接的一行中文")

page = DownloadPage()
page.show()
app.processEvents()

# 真实链路：粘贴带链接的标题 → 回车 → 必须出卡片
page.url_input.insertFromMimeData(LINKED)
page._commit_lines(page.url_input.toPlainText())
app.processEvents()
ck("粘贴带链接标题后回车生成卡片", len(page._tag_cards) == 1,
   f"卡片数={len(page._tag_cards)}")
page._commit_lines(f"​{URL}")
app.processEvents()
ck("回车生成卡片（含零宽字符）", len(page._tag_cards) == 2,
   f"卡片数={len(page._tag_cards)}")
ck("输入框已被提交逻辑清空", page.url_input.toPlainText() == "")

# 无法识别的一行：必须给出可见提示，且不能抛异常出去
from pages.download_page import _looks_like_page_title  # noqa: E402

ck("标题形态判定", _looks_like_page_title(TITLE)
   and not _looks_like_page_title("今天天气不错")
   and not _looks_like_page_title("去bilibili看视频"))

page._commit_lines("今天天气不错")
app.processEvents()
hint = page.tag_hint.text()
ck("无效输入给出可见提示", "没有识别到链接" in hint, hint[:40])
ck("无效输入不生成卡片", len(page._tag_cards) == 2)
ck("提示语进入错误态", page.tag_hint.property("cssClass") == "taskError",
   str(page.tag_hint.property("cssClass")))

# 纯标题粘贴（无 href 无 BV）：要说到"粘的是标题"，而不是泛泛一句无效
page._commit_lines(TITLE)
app.processEvents()
ck("标题粘贴给出针对性提示", "网页标题" in page.tag_hint.text(),
   page.tag_hint.text()[:30])

# 成功一次之后必须退出错误态
page._commit_lines(URL)
app.processEvents()
ck("成功后退出错误提示态", page.tag_hint.property("cssClass") == ""
   and len(page._tag_cards) == 3, f"cssClass={page.tag_hint.property('cssClass')!r}")

# 槽内异常必须被兜住并显示出来（模拟 _add_tag 抛错）
page._add_tag = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
page._commit_lines(URL)
app.processEvents()
ck("槽内异常不静默", "生成卡片时出错" in page.tag_hint.text()
   and "boom" in page.tag_hint.text(), page.tag_hint.text()[:50])

print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
print("RESULT:", "PASS" if not FAIL else f"FAIL {FAIL}")
sys.exit(1 if FAIL else 0)
