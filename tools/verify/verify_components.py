# -*- coding: utf-8 -*-
"""运行时组件化验证：按组件增量安装 + 引擎单独更新

组件包随仓库分发（build_components/），所以用本地 HTTP 服务模拟 release 时
要区分两条路径：
- 本地包命中 → **零网络请求**（离线安装）
- 本地包不可用（get_component_dir 指向空目录）→ 才去 release 拉，且只拉缺失的组

同时验证：清单结构、引擎单独更新、sha256 校验失败拒绝安装、清单不可用时回退整包。
"""
import http.server
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import runtime_components as RC
import runtime_manager as R

checks = []


def ck(name, ok, extra=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra else ""))


COMP = BASE / "build_components"
if not (COMP / "manifest.json").exists():
    print("缺少 build_components/manifest.json，请先运行 tools/build_components.py")
    sys.exit(1)

manifest = json.loads((COMP / "manifest.json").read_text(encoding="utf-8"))

# ---------------- 1. 清单结构 ----------------
ck("清单含 schema/build", manifest.get("schema") == 1 and manifest.get("build"))
ck("清单含 6 个组件", len(manifest["components"]) == 6, list(manifest["components"]))
ck("每个组件都有 group", all("group" in m for m in manifest["components"].values()))
ck("每个组件都 < 100MB",
   all(m["size"] < RC.MAX_COMPONENT_BYTES for m in manifest["components"].values()),
   [f"{k}:{m['size']/1048576:.1f}MB" for k, m in manifest["components"].items()])
ck("engine 组件足够小（<20MB）",
   manifest["components"]["engine"]["size"] < 20 * 1024 * 1024,
   f"{manifest['components']['engine']['size']/1048576:.1f} MB")
ck("pyside 被拆成多个包",
   sum(1 for k in manifest["components"] if k.startswith("pyside")) >= 2,
   [k for k in manifest["components"] if k.startswith("pyside")])
ck("group_of 映射正确", RC.group_of("pyside-3") == "pyside" and RC.group_of("engine") == "engine")

# ---------------- 2. 起本地服务 ----------------
hits = []


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(COMP), **kwargs)

    def do_GET(self):
        hits.append(self.path)
        super().do_GET()

    def log_message(self, *args):
        pass


srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
srv.daemon_threads = True
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base_url = f"http://127.0.0.1:{port}"

# ---------------- 3. 模拟：只缺 engine ----------------
tmp = Path(tempfile.mkdtemp(prefix="rt_components_"))
empty = Path(tempfile.mkdtemp(prefix="rt_no_local_"))
R.COMPONENT_ASSET_BASE = base_url
R.COMPONENT_MANIFEST_URL = f"{base_url}/manifest.json"
R.get_runtime_dir = lambda: tmp
R.is_runtime_complete = lambda check_engine=True: all(
    (tmp / rel).exists() for rel in RC.GROUP_MARKERS.values()
)


def reset_runtime():
    """清掉 runtime 内容，只留 core/pyside/app 的标志文件（缺 engine）"""
    for child in tmp.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
    for group in ("core", "pyside", "app"):
        marker = tmp / RC.GROUP_MARKERS[group]
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("stub", encoding="utf-8")


# --- 3a. 本地组件包命中：全程零网络请求（离线安装） ---
reset_runtime()
R.get_component_dir = lambda: COMP
hits.clear()
ok = R.ensure_runtime()
ck("离线组件化安装成功", ok is True)
ck("离线安装零网络请求", hits == [], hits)
ck("engine 组件已从本地包解压",
   (tmp / RC.GROUP_MARKERS["engine"]).exists())
ck("engine 关键文件齐全",
   (tmp / "python/Lib/site-packages/yt_dlp/extractor").is_dir()
   or (tmp / "python/Lib/site-packages/yt_dlp/YoutubeDL.py").exists())
ck("写了组件状态文件", (tmp / R.COMPONENT_STATE_FILE).exists())
ck("安装后判定为完整", R.is_runtime_complete() is True)

# --- 3b. 本地没有组件包：才去 release 拉，且只拉缺失的 engine ---
reset_runtime()
R.get_component_dir = lambda: empty
hits.clear()
ok = R.ensure_runtime()
ck("无本地包时组件化安装成功", ok is True)
ck("只请求了清单与 engine.zip",
   sorted(hits) == ["/engine.zip", "/manifest.json"], hits)
ck("engine 组件已解压到 runtime",
   (tmp / RC.GROUP_MARKERS["engine"]).exists())
ck("安装后判定为完整", R.is_runtime_complete() is True)

# --- 3c. 本地包损坏（sha256 对不上清单）→ 自动改用 release 上的包 ---
reset_runtime()
stale_dir = Path(tempfile.mkdtemp(prefix="rt_stale_"))
(stale_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
corrupt = bytearray((COMP / "engine.zip").read_bytes())
corrupt[-1] ^= 0xFF                      # 改动最后一个字节，模拟包损坏
(stale_dir / "engine.zip").write_bytes(bytes(corrupt))
R.get_component_dir = lambda: stale_dir
try:
    hits.clear()
    ok = R.ensure_runtime()
    ck("本地包损坏时仍能装好", ok is True)
    ck("损坏时回退到 release 拉取 engine.zip", "/engine.zip" in hits, hits)
finally:
    shutil.rmtree(stale_dir, ignore_errors=True)

# ---------------- 4. 引擎单独更新（要拿最新版，先问 release） ----------------
reset_runtime()
R.get_component_dir = lambda: COMP
hits.clear()
ok, message = R.update_engine_component()
ck("引擎组件更新成功", ok is True, message)
# 版本一致时不会重复下载：清单从 release 拿（要查最新版），包用本地那份
ck("更新只请求清单（版本一致时复用本地包）", hits == ["/manifest.json"], hits)

# ---------------- 5. 校验失败应拒绝 ----------------
bad = json.loads(json.dumps(manifest))
bad["components"]["engine"]["sha256"] = "0" * 64
bad_path = COMP / "_bad_manifest.json"
bad_path.write_text(json.dumps(bad), encoding="utf-8")
_orig_url = R.COMPONENT_MANIFEST_URL
R.COMPONENT_MANIFEST_URL = f"{base_url}/_bad_manifest.json"
try:
    ok, message = R.update_engine_component()
    ck("sha256 不匹配时拒绝安装", ok is False and "校验" in message, message)
finally:
    R.COMPONENT_MANIFEST_URL = _orig_url
    bad_path.unlink(missing_ok=True)

# ---------------- 6. 清单不可用 → 回退整包 ----------------
R.COMPONENT_MANIFEST_URL = f"{base_url}/__missing__.json"
R.get_component_dir = lambda: empty   # 本地也没带组件包
called = {"full": False}


def fake_download(progress_callback=None):
    called["full"] = True
    return True


_orig_download = R.download_runtime
R.download_runtime = fake_download
R.is_runtime_complete = lambda check_engine=True: False
try:
    ok = R.ensure_runtime()
    ck("清单缺失时回退整包", ok is True and called["full"] is True)
finally:
    R.download_runtime = _orig_download

# ---------------- 7. Release 不存在（被删 / 404）时仍可离线自愈 ----------------
# 场景：仓库自带组件包，但 GitHub Release 已删除 → 更新引擎应成功且如实说明
reset_runtime()
R.get_component_dir = lambda: COMP
R.COMPONENT_MANIFEST_URL = f"{base_url}/__missing__.json"
R.is_runtime_complete = lambda check_engine=True: all(
    (tmp / rel).exists() for rel in RC.GROUP_MARKERS.values()
)
hits.clear()
ok, message = R.update_engine_component()
ck("Release 不可用时更新仍成功", ok is True, message)
ck("结果如实说明用的是内置版本",
   "仓库内置" in message and "未找到更新源" in message, message)
ck("只查了一次清单、没有下载包（纯本地）",
   [h for h in hits if h.endswith(".zip")] == [], hits)
ck("引擎已就位", (tmp / RC.GROUP_MARKERS["engine"]).exists())

# 再点一次：已是内置版本且完好 → 不该重复解压
hits.clear()
ok, message = R.update_engine_component()
ck("已是内置版本时提示无需更新", ok is True and "无需更新" in message, message)
ck("无需更新时不下载不解压",
   [h for h in hits if h.endswith(".zip")] == [], hits)

# 本地也没带包 + Release 也没有 → 明确失败，不假装成功
R.get_component_dir = lambda: empty
ok, message = R.update_engine_component()
ck("两边都没有组件包时明确失败", ok is False and "Release 不可用" in message, message)

srv.shutdown()
print(f"\n===== {sum(checks)} passed, {len(checks) - sum(checks)} failed =====")
sys.stdout.flush()
os._exit(0 if all(checks) else 1)
