# -*- coding: utf-8 -*-
"""验证纯音频/容器转换（yt-dlp 下载后的本地 ffmpeg 处理）

不依赖网络：用 ffmpeg 合成一段带音轨的测试素材，再走引擎的转换函数，
覆盖 mp3 / wav / 单声道降级 / 无音轨报错 四条路径。
"""
import math
import os
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import ytdlp_engine as engine

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail else ""))


FFMPEG = engine._ffmpeg_exe()
tmp = Path(tempfile.mkdtemp(prefix="jiudown_audio_"))
src_wav = tmp / "src.wav"
src_av = tmp / "src.mp4"


def make_wav(path: Path, seconds: float = 1.0) -> None:
    """用标准库直接写一段正弦波 WAV

    不用 ffmpeg 的 lavfi/testsrc 合成：精简版没有视频编码器与 lavfi 输入，
    而生产链路只需要「重封装 + 音频转码」，测试素材也不该反过来依赖它们。
    """
    rate, freq = 44100, 440.0
    with wave.open(str(path), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        buf = bytearray()
        for i in range(int(rate * seconds)):
            v = int(12000 * math.sin(2 * math.pi * freq * i / rate))
            buf += struct.pack("<hh", v, v)
        w.writeframes(bytes(buf))


# 1) 带音轨素材：WAV → 再用 ffmpeg 封成 mp4（aac 音轨），模拟下载回来的源文件
make_wav(src_wav)
check("合成带音轨素材（wav）", src_wav.exists() and src_wav.stat().st_size > 0,
      f"{src_wav.stat().st_size if src_wav.exists() else 0} B")

subprocess.run(
    [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
     "-i", str(src_wav), "-c:a", "aac", str(src_av)],
    capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
)
check("封装为 mp4（aac 音轨）", src_av.exists() and src_av.stat().st_size > 0)

# 2) 无音轨素材：用现成的纯视频 flv（精简版无视频编码器，无法现场合成）
src_video_only = None
for pattern in ("Download/*.flv", "TEMP/fixtures/*.flv", "TEMP/fixtures/*.mp4"):
    found = sorted(Path(".").glob(pattern))
    if found:
        src_video_only = found[0]
        break
check("找到纯视频素材（用于无音轨用例）", src_video_only is not None,
      str(src_video_only) if src_video_only else "缺少 Download/*.flv")

# 3) mp4 → mp3
mp3 = tmp / "out.mp3"
engine._ffmpeg_convert(src_av, mp3, "mp3", "双声道")
check("mp3 转换成功", mp3.exists() and mp3.stat().st_size > 0,
      f"{mp3.stat().st_size if mp3.exists() else 0} B")

# 4) mp4 → wav
wav = tmp / "out.wav"
engine._ffmpeg_convert(src_av, wav, "wav", "双声道")
check("wav 转换成功", wav.exists() and wav.stat().st_size > 0,
      f"{wav.stat().st_size if wav.exists() else 0} B")

# 5) 单声道：精简版缺重采样时自动降级双声道（不抛错即通过）
mono = tmp / "mono.wav"
try:
    engine._ffmpeg_convert(src_av, mono, "wav", "单声道")
    check("单声道转换（含降级）不出错", mono.exists() and mono.stat().st_size > 0)
except engine.EngineError as e:
    check("单声道转换（含降级）不出错", False, str(e))

# 6) mp4 → flv（仅重封装）
flv = tmp / "out.flv"
engine._ffmpeg_convert(src_av, flv, "flv", "双声道")
check("flv 重封装成功", flv.exists() and flv.stat().st_size > 0)

# 7) 无音轨素材导出 mp3 → 可读错误
if src_video_only is not None:
    try:
        engine._ffmpeg_convert(src_video_only, tmp / "bad.mp3", "mp3", "双声道")
        check("无音轨导出音频给出可读错误", False, "未抛错")
    except engine.EngineError as e:
        check("无音轨导出音频给出可读错误", "没有音频轨" in str(e), str(e))
else:
    print("SKIP 无音轨导出音频（缺少纯视频素材）")

# 8) 声道数确实生效：单声道 mp3 的音频流应标记为 mono
mono_mp3 = tmp / "mono.mp3"
engine._ffmpeg_convert(src_av, mono_mp3, "mp3", "单声道")
probe = subprocess.run(
    [FFMPEG, "-i", str(mono_mp3)], capture_output=True, text=True,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
).stderr
audio_line = next((ln.strip() for ln in probe.splitlines() if "Audio:" in ln), "")
check("单声道输出音频流为 mono", "mono" in audio_line.lower(), audio_line[:80])

# 9) 画质 → 格式选择器
check("720P 选择器带上限", "height<=720" in engine.format_selector("720P", "mp4"))
check("最高 不做高度限制", engine.format_selector("最高", "mp4").startswith("bestvideo*"))
check("纯音频只取音频流", engine.format_selector("1080P", "mp3") == "bestaudio/best")

# 清理
for f in tmp.glob("*"):
    try:
        f.unlink()
    except OSError:
        pass
try:
    tmp.rmdir()
except OSError:
    pass

print(f"\n===== {sum(checks)} passed, {len(checks) - sum(checks)} failed =====")
sys.stdout.flush()
os._exit(0 if all(checks) else 1)
