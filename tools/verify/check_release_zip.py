"""只读 zip 中央目录：确认 release 上的 runtime.zip 是否含 yt-dlp

网络层用 curl（本机对 GitHub 的 TLS 走得比 requests 稳），只用 Range 取
EOCD + 中央目录，不下载 320MB 整包。
"""
import os
import struct
import subprocess
import sys
import tempfile

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

URL = "https://github.com/Yjiutong/JiuDown/releases/download/runtime/runtime.zip"
TMP = tempfile.mkdtemp(prefix="zipchk_")


def curl_range(start: int, end: int, out: str) -> bytes:
    """curl 取 [start, end] 字节（end 可为负数表示最后 N 字节）"""
    rng = f"{start}-{end}"
    cmd = ["curl", "-sL", "--max-time", "120", "-r", rng, "-o", out, URL]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"curl 失败: {proc.stderr[:200]}")
    return open(out, "rb").read()


def head_size() -> int:
    proc = subprocess.run(
        ["curl", "-sIL", "--max-time", "60", URL], capture_output=True, text=True
    )
    total = 0
    for line in proc.stdout.splitlines():
        if line.lower().startswith("content-length:"):
            total = int(line.split(":", 1)[1].strip())
    return total


def main():
    total = head_size()
    print(f"remote size = {total/1048576:.1f} MB")
    if total <= 0:
        print("无法获取长度")
        return 1

    # 尾部 128KB，定位 EOCD
    tail = curl_range(max(total - 131072, 0), total - 1, os.path.join(TMP, "tail.bin"))
    idx = tail.rfind(b"PK\x05\x06")
    if idx < 0:
        print("未找到 EOCD")
        return 1
    eocd = tail[idx: idx + 22]
    (_, _disk, _cd_disk, _n_this, n_total, cd_size, cd_offset, _cl) = struct.unpack(
        "<IHHHHIIH", eocd
    )
    print(f"entries = {n_total} | central dir = {cd_size/1024:.1f} KB @ {cd_offset}")

    cd = curl_range(cd_offset, cd_offset + cd_size - 1, os.path.join(TMP, "cd.bin"))

    names = []
    pos = 0
    while pos + 46 <= len(cd) and cd[pos:pos + 4] == b"PK\x01\x02":
        f = struct.unpack("<IHHHHHHIIIHHHHHII", cd[pos:pos + 46])
        name_len, extra_len, comment = f[10], f[11], f[12]
        names.append(cd[pos + 46: pos + 46 + name_len].decode("utf-8", "replace"))
        pos += 46 + name_len + extra_len + comment

    print(f"解析到 {len(names)} 个条目")
    for key in ("python/python.exe", "python/python312.dll", "ffmpeg.exe"):
        hit = any(n.rstrip("/") == key for n in names)
        print(f"  [{'OK  ' if hit else 'MISS'}] {key}")

    yt = [n for n in names if "site-packages/yt_dlp/" in n]
    print(f"  [{'OK  ' if yt else 'MISS'}] site-packages/yt_dlp/  ({len(yt)} 个文件)")
    for probe in ("yt_dlp/version.py", "yt_dlp/YoutubeDL.py"):
        if any(n.endswith(probe) for n in yt):
            print(f"      found {probe}")
    dist = [n for n in names if "yt_dlp-" in n and n.endswith("METADATA")]
    if dist:
        print("      dist-info:", dist[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
