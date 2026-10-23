"""
打包运行时组件（发布端工具）

用法：
    python tools/build_components.py                    # 生成到 build_components/
    python tools/build_components.py --dry-run          # 只统计体积，不写文件
    python tools/build_components.py --keep-all         # 不剥离 PySide6 的用不到模块

产物：
    build_components/core.zip
    build_components/pyside-1.zip / pyside-2.zip / ...
    build_components/engine.zip
    build_components/app.zip
    build_components/manifest.json

把上述文件一起上传到 GitHub Release 的 runtime 标签即可；
客户端会按 manifest 只补缺失或过期的组件（引擎更新只需重新下 engine.zip）。
"""

from __future__ import annotations

import argparse
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import runtime_components as RC  # noqa: E402

MB = 1024 * 1024


def human(n: int) -> str:
    return f"{n / MB:.1f} MB"


def collect(runtime_dir: Path, strip_pyside: bool) -> dict[str, list[Path]]:
    buckets = RC.iter_component_files(runtime_dir, strip_pyside=strip_pyside)
    groups: dict[str, list[Path]] = {}

    # pyside 按体积切分（保证每个包里未压缩数据 < 90MB，压缩后约一半）
    pyside_files = buckets.pop("pyside", [])
    if pyside_files:
        parts = RC.split_by_size(pyside_files, RC.PYSIDE_PART_BYTES)
        for i, part in enumerate(parts, 1):
            name = "pyside" if len(parts) == 1 else f"pyside-{i}"
            groups[name] = part

    for name, files in buckets.items():
        groups[name] = files
    return groups


def engine_version(runtime_dir: Path) -> str:
    """从 runtime 里的 dist-info 读 yt-dlp 版本（不 import，避免污染当前进程）"""
    sp = Path(runtime_dir) / "python" / "Lib" / "site-packages"
    for d in sp.glob("yt_dlp-*.dist-info"):
        stem = d.name[: -len(".dist-info")] if d.name.endswith(".dist-info") else d.name
        if "-" in stem:
            return stem.split("-", 1)[1]
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", default=str(ROOT / "runtime"))
    ap.add_argument("--out", default=str(ROOT / "build_components"))
    ap.add_argument("--keep-all", action="store_true", help="不剥离 PySide6 用不到的模块")
    ap.add_argument("--dry-run", action="store_true", help="只统计体积")
    ap.add_argument("--manifest-only", action="store_true",
                    help="不重新打包，只按已有 zip 重算 manifest.json")
    args = ap.parse_args()

    runtime_dir = Path(args.runtime)
    if not runtime_dir.is_dir():
        print(f"[FAIL] runtime 目录不存在: {runtime_dir}")
        return 1

    strip = not args.keep_all
    print(f"扫描 {runtime_dir}（剥离无用模块: {strip}）…")
    t0 = time.time()
    groups = collect(runtime_dir, strip)
    print(f"分组完成，用时 {time.time() - t0:.1f}s\n")

    total_raw = 0
    for name in sorted(groups):
        files = groups[name]
        raw = sum(f.stat().st_size for f in files)
        total_raw += raw
        print(f"  {name:10} {len(files):5} 文件  未压缩 {human(raw)}")

    skipped = sum(
        1 for p in runtime_dir.rglob("*")
        if p.is_file() and RC.classify(p.relative_to(runtime_dir).as_posix(), strip_pyside=strip) is None
    )
    print(f"\n合计未压缩 {human(total_raw)}；未纳入组件的文件 {skipped} 个（ffmpeg/旧exe/缓存）")

    if args.dry_run:
        return 0

    if args.manifest_only:
        out = Path(args.out)
        if not out.is_dir():
            print(f"[FAIL] 输出目录不存在: {out}")
            return 1
        components = {}
        for zip_path in sorted(out.glob("*.zip")):
            with zipfile.ZipFile(zip_path) as zf:
                count = len(zf.namelist())
            components[zip_path.stem] = {
                "file": zip_path.name,
                "size": zip_path.stat().st_size,
                "sha256": RC.sha256_file(zip_path),
                "files": count,
            }
        manifest = RC.build_manifest(
            components, build=datetime.now().strftime("%Y%m%d-%H%M%S"),
            engine_version=engine_version(runtime_dir),
        )
        RC.dump_manifest(manifest, out / "manifest.json")
        print(f"已重算 manifest：{len(components)} 个组件 → {out / 'manifest.json'}")
        for name, meta in components.items():
            print(f"  {name:10} {human(meta['size']):>9}  group={RC.group_of(name)}")
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    components: dict[str, dict] = {}
    failures = []

    for name in sorted(groups):
        files = groups[name]
        zip_path = out / f"{name}.zip"
        print(f"\n打包 {zip_path.name} …")
        t = time.time()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for f in files:
                arc = f.relative_to(runtime_dir).as_posix()
                zf.write(f, arc)
        size = zip_path.stat().st_size
        digest = RC.sha256_file(zip_path)
        components[name] = {
            "file": zip_path.name,
            "size": size,
            "sha256": digest,
            "files": len(files),
        }
        flag = "" if size <= RC.MAX_COMPONENT_BYTES else "  ← 超过 100MB，需继续拆分"
        if size > RC.MAX_COMPONENT_BYTES:
            failures.append(name)
        print(f"  {human(size)}  用时 {time.time() - t:.1f}s{flag}")

    manifest = RC.build_manifest(
        components,
        build=datetime.now().strftime("%Y%m%d-%H%M%S"),
        engine_version=engine_version(runtime_dir),
    )
    RC.dump_manifest(manifest, out / "manifest.json")

    print(f"\n{'=' * 56}")
    print(f"输出目录: {out}")
    print(f"组件数: {len(components)}  总计压缩后: {human(sum(c['size'] for c in components.values()))}")
    if failures:
        print(f"[警告] 以下组件超过 100MB，需要进一步拆分: {', '.join(failures)}")
        return 2
    print("全部组件均 < 100 MB ✓")
    print("下一步：把 build_components/ 里的 zip + manifest.json 上传到 release 的 runtime 标签")
    return 0


if __name__ == "__main__":
    sys.exit(main())
