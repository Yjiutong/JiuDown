# -*- coding: utf-8 -*-
"""验证发布产物：portable zip 内容、setup 脚本、FFmpeg 依赖、校验值

防回归的重点：
1. 发布包里不能混入 TEMP/、tools/、.git/、__pycache__ 等开发期文件
   （踩过：iss 里 `*.py` 带 recursesubdirs 会把验证脚本也装进安装包）
2. FFmpeg 不能依赖 MinGW 运行库（libwinpthread 等）——用户机器上没有，
   直接 0xC0000135 启动失败（踩过：只在本机 PATH 含 mingw 时才发现不了）
3. 快捷方式必须指向 pythonw.exe app.py，且工作目录是安装目录
"""
import hashlib
import os
import re
import sys
import zipfile
from pathlib import Path

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
DIST = ROOT / "dist"
ISS = ROOT / "build" / "release" / "JiuDownSetup.iss"

PASS, FAIL = [], []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  [{extra}]" if extra else ""))


# ---------------------------------------------------------------- PE 导入表
def imported_dlls(path: Path) -> set:
    """解析 PE 导入表拿到依赖的 DLL 名（只依赖标准库，发布机也能跑）"""
    data = path.read_bytes()
    pe = int.from_bytes(data[0x3C:0x40], "little")
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("不是有效的 PE 文件")
    coff = pe + 4
    nsec = int.from_bytes(data[coff + 2:coff + 4], "little")
    size_opt = int.from_bytes(data[coff + 16:coff + 18], "little")
    opt = coff + 20
    magic = int.from_bytes(data[opt:opt + 2], "little")
    dd = opt + (112 if magic == 0x20B else 96)

    sections = []
    sec_off = opt + size_opt
    for i in range(nsec):
        entry = sec_off + i * 40
        vaddr = int.from_bytes(data[entry + 12:entry + 16], "little")
        vsize = int.from_bytes(data[entry + 8:entry + 12], "little")
        raw_ptr = int.from_bytes(data[entry + 20:entry + 24], "little")
        raw_size = int.from_bytes(data[entry + 16:entry + 20], "little")
        sections.append((vaddr, vsize, raw_ptr, raw_size))

    def rva_to_off(rva: int) -> int:
        for vaddr, vsize, raw_ptr, raw_size in sections:
            if vaddr <= rva < vaddr + max(vsize, raw_size):
                return raw_ptr + (rva - vaddr)
        raise ValueError(f"RVA 0x{rva:x} 不在任何节内")

    import_rva = int.from_bytes(data[dd + 8:dd + 12], "little")
    if not import_rva:
        return set()

    names = set()
    off = rva_to_off(import_rva)
    while True:
        chunk = data[off:off + 20]
        if len(chunk) < 20 or chunk == b"\0" * 20:
            break
        name_rva = int.from_bytes(chunk[12:16], "little")
        if not name_rva:
            break
        n_off = rva_to_off(name_rva)
        end = data.index(b"\0", n_off)
        names.add(data[n_off:end].decode("ascii", "replace").upper())
        off += 20
    return names


# MinGW / MSYS / Cygwin 运行库：用户机器上不会有，带上就是启动即崩
FORBIDDEN_DLL = ("LIBWINPTHREAD", "LIBGCC_S", "LIBSTDC++", "MSYS-", "CYG", "LIBQUADMATH")

# ---------------------------------------------------------------- 1. 产物存在
zips = sorted(DIST.glob("JiuDown-Portable-*.zip"))
exes = sorted(DIST.glob("JiuDown-Setup-*.exe"))
check("dist 下有 portable 压缩包", len(zips) == 1, str([p.name for p in zips]))
check("dist 下有 setup 安装包", len(exes) == 1, str([p.name for p in exes]))
if not zips or not exes:
    print("\n（缺少产物，跳过后续检查；先跑 tools/build_release.py）")
    print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
    sys.exit(1 if FAIL else 0)

version = zips[0].name[len("JiuDown-Portable-"):-len(".zip")]
check("两个产物版本号一致", exes[0].name == f"JiuDown-Setup-{version}.exe",
      f"{zips[0].name} / {exes[0].name}")

# ---------------------------------------------------------------- 2. zip 内容
FORBIDDEN_PREFIX = ("JiuDown/TEMP/", "JiuDown/tools/", "JiuDown/.git/",
                    "JiuDown/logs/", "JiuDown/config/", "JiuDown/Download/")
REQUIRED = (
    "JiuDown/app.py",
    "JiuDown/theme.py",
    "JiuDown/启动.vbs",
    "JiuDown/pages/home_page.py",
    "JiuDown/resources/app.ico",
    "JiuDown/resources/ffmpeg.exe",
    "JiuDown/runtime/python/python.exe",
    "JiuDown/runtime/python/pythonw.exe",
    "JiuDown/build_components/engine.zip",
    "JiuDown/build_components/ffmpeg-lite.zip",
    "JiuDown/build_components/manifest.json",
)

with zipfile.ZipFile(zips[0]) as archive:
    names = set(archive.namelist())
    check("包内顶层目录是 JiuDown/", all(n.startswith("JiuDown/") for n in names))
    for req in REQUIRED:
        check(f"包含 {req}", req in names)
    bad = sorted(n for n in names if n.startswith(FORBIDDEN_PREFIX))
    check("不含开发期目录（TEMP/tools/.git/logs/config/Download）", not bad, str(bad[:5]))
    check("不含 __pycache__", not any("__pycache__" in n for n in names))
    check("含便携版使用说明", any(n.endswith("使用说明.txt") for n in names))
    check("runtime 内带 yt-dlp",
          any(n.startswith("JiuDown/runtime/python/Lib/site-packages/yt_dlp/") for n in names))

# ---------------------------------------------------------------- 3. iss 静态检查
if ISS.exists():
    iss = ISS.read_text(encoding="utf-8-sig")
    root_py = [ln for ln in iss.splitlines() if re.search(r'\\\*\.py"', ln)]
    check("iss 有根目录 py 的 Source 行", len(root_py) == 1, str(root_py))
    check("根目录 py 不带 recursesubdirs（否则会带上 TEMP/tools）",
          root_py and "recursesubdirs" not in root_py[0], root_py[0] if root_py else "")
    check("iss 排除 __pycache__", 'Excludes: "__pycache__"' in iss)
    check("iss 包含 runtime 与 resources",
          "runtime\\*" in iss and "resources\\*" in iss)
    check("快捷方式指向 pythonw.exe app.py",
          "pythonw.exe" in iss and 'Parameters: "app.py"' in iss)
    check("快捷方式设置工作目录为安装目录", 'WorkingDir: "{app}"' in iss)
    check("有卸载项", "uninstallexe" in iss)
    check("限定 64 位", "ArchitecturesAllowed=x64compatible" in iss)
else:
    check("iss 已生成（跑过 setup 构建）", False, str(ISS))

# ---------------------------------------------------------------- 4. FFmpeg 依赖
ffmpeg = ROOT / "resources" / "ffmpeg.exe"
if ffmpeg.exists():
    dlls = imported_dlls(ffmpeg)
    mingw = sorted(d for d in dlls if any(d.startswith(f) for f in FORBIDDEN_DLL))
    # MinGW 运行库不是不能有，而是**必须一起分发**：否则用户机器上 0xC0000135
    missing = [d for d in mingw
               if not (ROOT / "resources" / d.lower()).exists()]
    check("FFmpeg 的 MinGW 依赖都随包分发在 resources/", not missing,
          f"依赖={mingw or '无'} 缺失={missing}")
    check("FFmpeg 依赖表里能读到系统 DLL",
          any(d.startswith(("KERNEL32", "API-MS-WIN")) for d in dlls),
          str(sorted(dlls)[:3]))

    # 精简版组件包也必须带上这些 DLL（离线补 ffmpeg 时才有完整的一套）
    lite = ROOT / "build_components" / "ffmpeg-lite.zip"
    if lite.exists():
        with zipfile.ZipFile(lite) as z:
            lite_names = [n.rsplit("/", 1)[-1].upper() for n in z.namelist()]
        check("ffmpeg-lite.zip 含 exe", "FFMPEG.EXE" in lite_names)
        check("ffmpeg-lite.zip 含配套 DLL",
              all(d in lite_names for d in mingw), f"{mingw} vs {lite_names}")
    else:
        check("ffmpeg-lite.zip 存在", False)
else:
    check("resources/ffmpeg.exe 存在", False)

# ---------------------------------------------------------------- 5. 校验值
sums = DIST / "SHA256SUMS.txt"
if sums.exists():
    lines = [l.split() for l in sums.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = True
    for digest, name in lines:
        path = DIST / name
        ok = ok and path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
    check("SHA256SUMS 与产物一致", ok and len(lines) == 2, f"{len(lines)} 条")
else:
    check("SHA256SUMS.txt 已生成", False)

print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
