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
import time
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

# 7b) 中文文件名必须同样给出可读错误
# 这一条是本脚本里唯一带中文的断言，专门盯住"ffmpeg 输出按 locale(cp936) 解码"的回归：
# 不显式指定 encoding 时解码线程会死掉、stderr 变成 None，错误信息会退化成"未知错误"，
# 而上面 7) 用 ASCII 文件名永远测不到这一层。
cjk_bad = tmp / "如何设定字号比例·排版 #平面设计.mp4"
cjk_bad.write_bytes(b"not a video at all")
try:
    engine._ffmpeg_convert(cjk_bad, tmp / "如何设定字号比例.mp3", "mp3", "双声道")
    check("中文文件名失败时也给出可读错误", False, "未抛错")
except engine.EngineError as e:
    msg = str(e)
    check("中文文件名失败时也给出可读错误",
          "未知错误" not in msg and len(msg) > len("mp3 转换失败：") + 8, msg[:90])
    check("中文文件名时 stderr 未被解码吞掉",
          "Invalid data" in msg or "Error opening" in msg, msg[-60:])
finally:
    cjk_bad.unlink(missing_ok=True)

# 8) 声道数确实生效：单声道 mp3 的音频流应标记为 mono
mono_mp3 = tmp / "mono.mp3"
engine._ffmpeg_convert(src_av, mono_mp3, "mp3", "单声道")
probe = subprocess.run(
    [FFMPEG, "-i", str(mono_mp3)], capture_output=True, text=True,
    encoding="utf-8", errors="replace",
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
).stderr
audio_line = next((ln.strip() for ln in probe.splitlines() if "Audio:" in ln), "")
check("单声道输出音频流为 mono", "mono" in audio_line.lower(), audio_line[:80])

# 8b) 合并/转码阶段回传真实进度（数据来自 ffmpeg 的 -progress pipe:1）
# 素材要足够长才会切出多个进度事件；用 bytes 重复而不是逐样本算正弦，否则合成
# 本身就要跑几十秒，测试会被自己的夹具拖死。
long_wav = tmp / "progress_src.wav"
with wave.open(str(long_wav), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(44100)
    w.writeframes(b"\x00\x01" * (44100 * 120 * 2 * 2 // 2))

seen = []
engine._ffmpeg_convert(long_wav, tmp / "progress.mp3", "mp3", "双声道",
                       duration=120.0, on_progress=seen.append)
check("转码回传了进度事件", len(seen) >= 2, "事件=%s" % [round(x, 1) for x in seen])
check("进度单调不回退", all(b >= a for a, b in zip(seen, seen[1:])),
      str([round(x, 1) for x in seen[:4]]))
check("进度收口在 100", bool(seen) and abs(seen[-1] - 100.0) < 0.01, str(seen[-1:]))
check("进度全部落在 0~100", all(0.0 <= x <= 100.0 for x in seen), str(seen[:3]))

blind = []
engine._ffmpeg_convert(long_wav, tmp / "blind.mp3", "mp3", "双声道",
                       duration=0.0, on_progress=blind.append)
check("时长未知时不编造百分比", blind == [], str(blind[:3]))

check("解析 out_time_us", engine._out_time_seconds("4000000") == 4.0)
check("解析 out_time 文本", engine._out_time_seconds("00:05:00.000000") == 300.0)
check("解析坏值返回 None", engine._out_time_seconds("N/A") is None)

# -re 让 ffmpeg 按实际时长读，必定超不过 1 秒的预算 → 验证卡住的进程会被掐掉，
# 而不是永久占住下载线程（DownKyi 的 WaitForExit 就没有这一步）
clock = time.monotonic()
try:
    engine._run_ffmpeg([FFMPEG, "-y", "-re", "-i", str(long_wav), "-vn",
                        "-c:a", "libmp3lame", str(tmp / "never.mp3")],
                       duration=120.0, timeout=1)
    check("超时会被中止", False, "没抛错")
except engine.EngineError as e:
    check("超时会被中止", "超时" in str(e), str(e)[:40])
spent = time.monotonic() - clock
check("中止不会把调用挂住", spent < 30.0, "耗时 %.1fs" % spent)

# stderr 由独立线程抽干：不抽就会在 pipe 缓冲写满后僵死
code, err_text = engine._run_ffmpeg([FFMPEG, "-y", "-i", str(long_wav), "-vn",
                                     "-c:a", "libmp3lame", "-b:a", "320k",
                                     str(tmp / "drain.mp3")], duration=120.0)
check("失败与成功都能拿到 stderr 文本", code == 0 and "size=" in err_text,
      repr(err_text.strip()[-50:]))

# 上面的转码太快（200x+），只会切出收尾那一两个事件；-re 强制 ffmpeg 按实际时长
# 读，才能把"百分比一路爬升"这条路真正跑出来
short = tmp / "short.wav"
make_wav(short, seconds=6.0)
climb = []
engine._run_ffmpeg([FFMPEG, "-y", "-re", "-i", str(short), "-vn", "-c:a", "libmp3lame",
                    str(tmp / "climb.mp3")], duration=6.0, on_progress=climb.append)
check("进度是一路爬升而非只有收尾", len(climb) >= 3,
      "%d 个事件 %s" % (len(climb), [round(x) for x in climb[:6]]))
check("爬升中出现过 5~95 之间的中间值", any(5.0 <= x <= 95.0 for x in climb),
      str([round(x, 1) for x in climb]))
check("爬升仍然单调不回退", all(b >= a for a, b in zip(climb, climb[1:])),
      str([round(x, 1) for x in climb]))

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
