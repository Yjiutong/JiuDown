#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""发布构建：生成 portable 与 setup 两个 exe

产物落在 dist/ 下（.gitignore 已忽略）：

    JiuDown-Portable-<ver>.exe  7-Zip 自解压便携版（内含完整的离线运行时）
    JiuDown-Setup-<ver>.exe      Inno Setup 安装程序（开始菜单/桌面快捷方式 + 卸载项）
    SHA256SUMS.txt               两个产物的校验值

用法：
    runtime\\python\\python.exe tools/build_release.py            # 两个都构建
    runtime\\python\\python.exe tools/build_release.py --only portable
    runtime\\python\\python.exe tools/build_release.py --only setup
    runtime\\python\\python.exe tools/build_release.py --version 1.2.0

两个产物内容完全一致，差别只在形态：
- portable：自解压 exe，解压到任意位置（U 盘也行）双击 启动.vbs 即用，
  配置/下载/日志都写在该目录里（便携模式）。
- setup：装到 Program Files，程序目录只读，用户数据自动落到
  %LOCALAPPDATA%\\JiuDown，下载默认进系统「下载」文件夹（见 system_info）。

setup 需要 Inno Setup 编译器（ISCC.exe）。默认使用 tools/_vendor/innosetup
下的便携版；缺失时会提示下载地址（--iscc 可指定已有编译器）。
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build" / "release"
VENDOR_ISCC = ROOT / "tools" / "_vendor" / "innosetup" / "ISCC.exe"
VENDOR_7Z = ROOT / "tools" / "_vendor" / "7zip" / "7z.exe"
VENDOR_7Z_URL = "https://www.7-zip.org/a/7z2301-x64.exe"

APP_NAME = "JiuDown"
# 固定 AppId：升级安装才能正确覆盖旧版本（不要每次生成新的）
APP_ID = "{{6F1B4C77-9E2A-4E5B-9C1A-2D7B5A8F3C41}"

# 随发布包一起下发的组件包：engine（离线修引擎）+ ffmpeg-lite（离线补 ffmpeg）
# 其余组件（core/pyside/app）不随包分发——runtime 已经装好了，带了只是白白增大体积
BUNDLED_COMPONENTS = ("manifest.json", "engine.zip", "ffmpeg-lite.zip")

PORTABLE_NOTICE = """JiuDown 便携版（Portable）
================================

【怎么用】
  1. 把 Portable exe 放到想放的位置（U 盘也可以，路径不要含特殊字符）
  2. 双击 exe，会在 exe 旁边解压出 JiuDown 目录
  3. 进入 JiuDown 目录，双击「启动.vbs」即可运行（无控制台窗口）
     —— 也可以直接运行 runtime\\python\\pythonw.exe app.py

【数据放哪】
  配置、日志、下载的文件、临时文件都写在本目录下：
    config\\      设置
    Download\\     下载的视频
    logs\\         运行日志
    TEMP\\         临时分片
  整个目录拷到别的电脑 = 完整迁移，卸载就是直接删目录，不留任何系统垃圾。

【已经带齐的东西】
  runtime\\              离线 Python 运行环境（含 PySide6 / yt-dlp），无需联网
  resources\\ffmpeg.exe  精简版 FFmpeg（5MB，覆盖全部下载场景）
  build_components\\     引擎与 FFmpeg 的离线修复包

【想装成正式软件？】
  用同版本的 JiuDown-Setup-<版本>.exe，装完有开始菜单快捷方式和卸载项。
"""


# ---------------------------------------------------------------- 基础信息
def read_app_version() -> str:
    """从 theme.py 读取 APP_VERSION（避免为了拿个字符串去 import PySide6）"""
    match = re.search(
        r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']',
        (ROOT / "theme.py").read_text(encoding="utf-8"),
        re.M,
    )
    if not match:
        raise SystemExit("无法从 theme.py 解析 APP_VERSION")
    return match.group(1)


def ensure_local_ffmpeg() -> None:
    """resources/ffmpeg.exe 缺失时，从随仓库分发的组件包里恢复一份

    ffmpeg 二进制不入库（.gitignore 忽略 resources/*），但 ffmpeg-lite.zip
    入库了，所以克隆一份干净的仓库也能构建出完整的发布包。
    """
    exe = ROOT / "resources" / "ffmpeg.exe"
    if exe.exists():
        return
    lite = ROOT / "build_components" / "ffmpeg-lite.zip"
    if not lite.exists():
        return  # 都没有就交给 precheck 报错
    exe.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(lite) as archive:
        for name in archive.namelist():
            normalized = name.replace("\\", "/")
            if not normalized.startswith("ffmpeg-lite/bin/") or normalized.endswith("/"):
                continue
            target = exe.parent / normalized.rsplit("/", 1)[-1]
            with archive.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    print(f"[OK] 已从 {lite.name} 恢复 {exe.relative_to(ROOT)}")


def precheck() -> None:
    """构建前自检：该带的东西都在吗"""
    missing = []
    if not (ROOT / "runtime" / "python" / "python.exe").exists():
        missing.append("runtime\\python\\python.exe（先跑 首次安装.bat）")
    if not (ROOT / "runtime" / "python" / "Lib" / "site-packages" / "yt_dlp").is_dir():
        missing.append("runtime 内缺少 yt-dlp（运行 首次安装.bat 补齐）")
    if not (ROOT / "resources" / "ffmpeg.exe").exists():
        missing.append("resources\\ffmpeg.exe")
    if not (ROOT / "resources" / "app.ico").exists():
        missing.append("resources\\app.ico")
    if missing:
        raise SystemExit("发布前自检未通过：\n  - " + "\n  - ".join(missing))


# ---------------------------------------------------------------- 文件清单
def iter_release_files():
    """产出 (源文件绝对路径, 包内相对路径)"""
    # 根目录源码
    for path in sorted(ROOT.glob("*.py")):
        yield path, path.name
    # 启动器与说明
    yield ROOT / "启动.vbs", "启动.vbs"
    yield ROOT / "README.md", "README.md"
    # 子目录
    for sub in ("pages", "resources", "runtime"):
        base = ROOT / sub
        for path in base.rglob("*"):
            if path.is_dir() or "__pycache__" in path.parts:
                continue
            yield path, path.relative_to(ROOT).as_posix()
    # 离线修复用的组件包
    for name in BUNDLED_COMPONENTS:
        path = ROOT / "build_components" / name
        if path.exists():
            yield path, f"build_components/{name}"


def refresh_ffmpeg_lite_zip() -> Path:
    """用当前 resources/ 重建精简版组件包（ffmpeg.exe + 它依赖的 DLL）

    精简版是 MinGW 编译的，pthread 用 dllimport 声明 → 静态链接不掉
    libwinpthread-1.dll。用户机器上没有这个 DLL 时 ffmpeg 会 0xC0000135 启动失败，
    所以打包时必须带上 resources/ 下的所有 .dll，且解压到与 exe 同一目录。
    """
    resources = ROOT / "resources"
    exe = resources / "ffmpeg.exe"
    members = [exe] + sorted(resources.glob("*.dll"))
    target = ROOT / "build_components" / "ffmpeg-lite.zip"
    tmp = target.with_suffix(".zip.part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in members:
            archive.write(path, f"ffmpeg-lite/bin/{path.name}")
    tmp.replace(target)
    extra = "（含 " + ", ".join(p.name for p in members[1:]) + "）" if len(members) > 1 else ""
    print(f"[OK] 精简版组件包: {target.name}  {extra}")
    return target


def build_portable_exe(version: str) -> Path:
    """生成 7-Zip 自解压便携 exe（包内顶层是 JiuDown\\）

    注意：7z.sfx 只能解 7z 归档，不能直接拼接 ZIP；且带 Installer 配置块会被
    Windows 当成安装包而触发提权（实测 /S 直接 740）。这里用无配置 SFX +
    标准 7z 归档，双击后解压到 exe 同级目录，静默参数 /S 也能稳定工作。
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / f"{APP_NAME}-Portable-{version}.exe"
    archive_path = BUILD_DIR / f"{APP_NAME}-Portable-{version}.7z"
    stage = BUILD_DIR / "portable_stage"
    payload_root = stage / APP_NAME
    sfx = find_7z_sfx()
    seven_zip = find_7z_exe()
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    archive_path.unlink(missing_ok=True)
    target.unlink(missing_ok=True)

    if stage.exists():
        shutil.rmtree(stage)
    payload_root.mkdir(parents=True)
    (payload_root / "使用说明.txt").write_text(PORTABLE_NOTICE, encoding="utf-8")
    count = 0
    total = 0
    for src, rel in iter_release_files():
        dst = payload_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
        count += 1
        total += src.stat().st_size
        if count % 1000 == 0:
            print(f"  … 已加入 {count} 个文件")

    proc = subprocess.run(
        [str(seven_zip), "a", "-t7z", "-mx=9", str(archive_path), APP_NAME],
        cwd=str(stage),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 or not archive_path.exists():
        raise SystemExit(f"7z 压缩失败（exit={proc.returncode}）\n{proc.stdout}\n{proc.stderr}")

    with target.open("wb") as dst:
        dst.write(sfx.read_bytes())
        dst.write(archive_path.read_bytes())
    archive_path.unlink()
    shutil.rmtree(stage, ignore_errors=True)
    print(f"[OK] portable: {target.name}  ({count} 个文件，源 {total / 1048576:.0f} MB，"
          f"压后 {target.stat().st_size / 1048576:.1f} MB)")
    return target


def ensure_7z_tools() -> Path:
    """确保 tools/_vendor/7zip 内有 7z.exe 与 7z.sfx；缺失时从官方安装包提取"""
    target_dir = VENDOR_7Z.parent
    sfx = target_dir / "7z.sfx"
    if VENDOR_7Z.exists() and sfx.exists():
        return sfx
    target_dir.mkdir(parents=True, exist_ok=True)
    archive = target_dir / "7z-extra.7z"
    if not archive.exists():
        import urllib.request
        print(f"  下载 7-Zip extra 包：{VENDOR_7Z_URL}")
        urllib.request.urlretrieve(VENDOR_7Z_URL, archive)
    proc = subprocess.run(
        [str(VENDOR_7Z if VENDOR_7Z.exists() else _bootstrap_7zr()),
         "e", str(archive), "-o" + str(target_dir),
         "7z.sfx", "7z.exe", "7z.dll", "-y"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0 or not sfx.exists():
        raise SystemExit(f"7-Zip 安装包解包失败：{proc.stdout}\n{proc.stderr}")
    archive.unlink(missing_ok=True)
    return sfx


def _bootstrap_7zr() -> Path:
    """先用官方单文件 7zr.exe 展开安装包，再把完整 7z.exe 留下备用"""
    target = VENDOR_7Z.parent / "7zr.exe"
    if not target.exists():
        import urllib.request
        urllib.request.urlretrieve("https://www.7-zip.org/a/7zr.exe", target)
    return target


def find_7z_sfx() -> Path:
    """返回 GUI 自解压模块，必要时补齐本地 7-Zip 工具"""
    for path in (VENDOR_7Z.parent / "7z.sfx",
                 Path("C:/Program Files/7-Zip/7z.sfx"),
                 Path("C:/Program Files (x86)/7-Zip/7z.sfx")):
        if path.exists() and VENDOR_7Z.exists():
            return path
    return ensure_7z_tools()


def find_7z_exe() -> Path:
    """返回 7z.exe：优先随仓库的 vendor，其次系统安装目录"""
    for path in (VENDOR_7Z,
                 Path("C:/Program Files/7-Zip/7z.exe"),
                 Path("C:/Program Files (x86)/7-Zip/7z.exe")):
        if path.exists():
            return path
    raise SystemExit(
        "未找到 7z.exe。\n"
        "  下载：https://www.7-zip.org/a/7z2301-x64.exe\n"
        f"  或放到：{VENDOR_7Z}"
    )



# ---------------------------------------------------------------- Inno Setup
def render_iss(version: str) -> Path:
    """生成 .iss 脚本（UTF-8 BOM，Inno 才能正确读中文）"""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    iss_path = BUILD_DIR / f"{APP_NAME}Setup.iss"

    def src_line(pattern: str, dest: str = "{app}", recursive: bool = True,
                 excludes: str = "") -> str:
        # 注意：根目录的 *.py 绝不能带 recursesubdirs——否则 TEMP/ 与 tools/ 下的
        # 验证脚本会被一起递归进安装包（踩过一次）
        flags = "ignoreversion" + (" recursesubdirs" if recursive else "")
        line = f'Source: "{pattern}"; DestDir: "{dest}"; Flags: {flags}'
        if excludes:
            line += f'; Excludes: "{excludes}"'
        return line + "\n"

    files = [
        src_line(f"{ROOT}\\*.py", recursive=False),
        src_line(f"{ROOT}\\启动.vbs", recursive=False),
        src_line(f"{ROOT}\\README.md", recursive=False),
        src_line(f"{ROOT}\\pages\\*", "{app}\\pages"),
        src_line(f"{ROOT}\\resources\\*", "{app}\\resources"),
        # 排除编译缓存：带了只会白白增大体积
        src_line(f"{ROOT}\\runtime\\*", "{app}\\runtime", excludes="__pycache__"),
    ]
    for name in BUNDLED_COMPONENTS:
        if (ROOT / "build_components" / name).exists():
            files.append(
                f'Source: "{ROOT}\\build_components\\{name}"; '
                f'DestDir: "{{app}}\\build_components"; Flags: ignoreversion\n'
            )

    content = f"""#define MyAppName "{APP_NAME}"
#define MyAppVersion "{version}"
#define MyAppPublisher "JiuDown"
#define MyAppURL "https://github.com/Yjiutong/JiuDown"
#define MyAppAssocName "JiuDown Desktop"

[Setup]
AppId={APP_ID}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppVerName={{#MyAppName}} {{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
AppPublisherURL={{#MyAppURL}}
AppSupportURL={{#MyAppURL}}
AppUpdatesURL={{#MyAppURL}}
DefaultDirName={{autopf}}\\{{#MyAppName}}
DefaultGroupName={{#MyAppName}}
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir={OUT_DIR}
OutputBaseFilename={APP_NAME}-Setup-{version}
SetupIconFile={ROOT}\\resources\\app.ico
UninstallDisplayIcon={{app}}\\resources\\app.ico
UninstallDisplayName={{#MyAppName}} {{#MyAppVersion}}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
UsedUserAreasWarning=no
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked

[Files]
{''.join(files)}

[Icons]
; 主程序由嵌入式 Python 启动：pythonw.exe app.py（无控制台窗口）
Name: "{{group}}\\{{#MyAppName}}"; Filename: "{{app}}\\runtime\\python\\pythonw.exe"; \
Parameters: "app.py"; WorkingDir: "{{app}}"; IconFilename: "{{app}}\\resources\\app.ico"
Name: "{{group}}\\卸载 {{#MyAppName}}"; Filename: "{{uninstallexe}}"
Name: "{{autodesktop}}\\{{#MyAppName}}"; Filename: "{{app}}\\runtime\\python\\pythonw.exe"; \
Parameters: "app.py"; WorkingDir: "{{app}}"; IconFilename: "{{app}}\\resources\\app.ico"; \
Tasks: desktopicon

[Run]
Filename: "{{app}}\\runtime\\python\\pythonw.exe"; Parameters: "app.py"; \
WorkingDir: "{{app}}"; Description: "立即启动 {{#MyAppName}}"; \
Flags: nowait postinstall skipifsilent
"""
    iss_path.write_text(content, encoding="utf-8-sig")
    return iss_path


def find_iscc(custom: str | None = None) -> Path:
    for candidate in (custom, VENDOR_ISCC, shutil.which("ISCC"), shutil.which("iscc")):
        if candidate and Path(candidate).exists():
            return Path(candidate)
    raise SystemExit(
        "未找到 Inno Setup 编译器（ISCC.exe）。\n"
        "  下载：https://github.com/jrsoftware/issrc/releases/download/is-7_1_0/innosetup-7.1.0-x64.exe\n"
        "  便携解压（不写注册表、不装到系统）：\n"
        "    innosetup-7.1.0-x64.exe /VERYSILENT /CURRENTUSER /PORTABLE=1 "
        f'/DIR="{VENDOR_ISCC.parent}"\n'
        "  或用 --iscc 指定已有的 ISCC.exe"
    )


def build_setup_exe(version: str, iscc: str | None = None) -> Path:
    iss_path = render_iss(version)
    compiler = find_iscc(iscc)
    target = OUT_DIR / f"{APP_NAME}-Setup-{version}.exe"
    target.unlink(missing_ok=True)

    print(f"  编译 {iss_path.name}（{compiler}）… 压缩 runtime 需要几分钟")
    proc = subprocess.run(
        [str(compiler), str(iss_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 or not target.exists():
        raise SystemExit(
            f"Inno Setup 编译失败（exit={proc.returncode}）\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    print(f"[OK] setup:    {target.name}  "
          f"({target.stat().st_size / 1048576:.1f} MB)")
    return target


# ---------------------------------------------------------------- 校验值
def write_sha256(files: list[Path]) -> Path:
    sums = OUT_DIR / "SHA256SUMS.txt"
    lines = []
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[OK] 校验值:  {sums.name}")
    return sums


def write_release_notes(version: str, artifacts: list[Path]) -> Path:
    """生成简洁的 Release 说明"""
    digest_lines = []
    for path in artifacts:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digest_lines.append(f"{digest}  {path.name}")
    sizes = {path.name: path.stat().st_size / 1048576 for path in artifacts}
    portable_name = f"{APP_NAME}-Portable-{version}.exe"
    setup_name = f"{APP_NAME}-Setup-{version}.exe"
    asset_rows = []
    if portable_name in sizes:
        asset_rows.append(
            f"| `{portable_name}` | {sizes[portable_name]:.0f} MB | "
            "自解压便携版，双击后在 exe 同级解压出 `JiuDown\\`，运行 `启动.vbs` |"
        )
    if setup_name in sizes:
        asset_rows.append(
            f"| `{setup_name}` | {sizes[setup_name]:.0f} MB | "
            "一键安装，包含开始菜单/桌面快捷方式与卸载项 |"
        )
    asset_rows.append("| `SHA256SUMS.txt` | — | 产物的校验值 |")
    notes = f"""# JiuDown v{version}

计划标签：`v{version}`（主发布） / `portable_v{version}`（便携版）

## 变更

- 依 Refactoring UI 重做设计系统：受限字号/间距阶梯、层级靠字重与颜色
- 减少边框：圆角卡片/输入改用底色差与极浅实色短投影分层
- 预定义中性灰阶与主色阶；当前导航用蓝色强调边，CTA 为主色实心按钮
- 空状态重做：无边框、留白充足、说明文字收在易读行宽
- 硬性规则：每个标签文字都有独立自适应完整容器，禁止写死文字容器高度，
  并由 verify_label_fit.py 逐标签断言不裁字
- 左侧导航展开/收起两态共用固定行高；标题栏/窗口/托盘沿用 `resources/app.ico`
- 界面字体跟随系统默认，不再随包携带字体文件

## 发布资产

| 文件 | 大小 | 说明 |
|---|---:|---|
{chr(10).join(asset_rows)}

## SHA256

```
{chr(10).join(digest_lines)}
```
"""
    path = OUT_DIR / f"RELEASE_NOTES_v{version}.md"
    path.write_text(notes, encoding="utf-8")
    print(f"[OK] release notes:  {path.name}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 JiuDown 发布产物")
    parser.add_argument("--only", choices=("portable", "setup", "all"), default="all",
                        help="只构建其中一个（默认两个都构建）")
    parser.add_argument("--version", default=None, help="覆盖 theme.py 里的 APP_VERSION")
    parser.add_argument("--iscc", default=None, help="指定 ISCC.exe 路径")
    args = parser.parse_args()

    version = args.version or read_app_version()
    print(f"构建 {APP_NAME} {version}（--only {args.only}）")
    ensure_local_ffmpeg()
    precheck()
    refresh_ffmpeg_lite_zip()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []
    if args.only in ("portable", "all"):
        produced.append(build_portable_exe(version))
    if args.only in ("setup", "all"):
        produced.append(build_setup_exe(version, args.iscc))

    if produced:
        write_sha256(produced)
        write_release_notes(version, produced)
        print("\n产物：")
        for path in produced:
            print(f"  {path}")
    print("\n发布到 GitHub Release 时把 dist/ 下两个 exe、SHA256SUMS.txt 与 RELEASE_NOTES 一起上传即可。")


if __name__ == "__main__":
    sys.exit(main())
