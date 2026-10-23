# FFmpeg 精简版构建说明

本项目不随仓库分发 FFmpeg。首次运行会自动下载**精简版**（约 2.3MB 压包 / 5.3MB 解压），
它由本项目自己从 FFmpeg 源码裁剪编译，只保留下载链路真正用到的部分。

| | 官方完整版（BtbN gpl） | 本项目精简版 |
|---|---|---|
| 体积 | 161.2 MB | **5.3 MB** |
| 容器重封装（mp4/flv/mkv/webm/ts） | ✅ | ✅ |
| mp3 转码（libmp3lame） | ✅ | ✅ |
| wav 转码（pcm_s16le） | ✅ | ✅ |
| 单声道 `-ac 1`（aresample） | ✅ | ✅ |
| 视频编解码器（x264/x265/aom…） | ✅ | ❌ 不需要（只用 `-c copy`） |
| 硬件加速（cuda/qsv/amf/vulkan） | ✅ | ❌ 不需要 |
| 滤镜库 / 字幕 / 截图 / 推流 | ✅ | ❌ 不需要 |

下载链路只做两件事：`-c copy` 合并音视频、把音频转成 mp3/wav。**不解码也不编码视频**，
所以上面那些"缺失"不影响任何功能。需要罕见格式时，设置页/首页可以显式点「升级完整版」。

## 应用侧的能力判定

`ffmpeg_manager` 不再用"是不是完整版"来决定能否下载，而是按**应用真正用到的能力**判定：

| 概念 | 判定依据 | 含义 |
|---|---|---|
| `APP_MARKERS` / `is_ready()` | libmp3lame、pcm_s16le、mp4/flv/wav 封装器、aresample | 下载所需能力齐备（精简版即可通过） |
| `FULL_MARKERS` / `is_full()` | 上表 + libx264 等视频重编码能力 | BtbN 完整版，仅用于「升级完整版」入口 |

状态机的取值：`full` / `ready` / `lite` / `downloading` / `failed` / `missing`。
只有 `lite`（能力不足）才会在下载页弹提示条并按 `missing_features()` 置灰对应格式/声道；
`ready` 是正常状态，不打扰用户。

## 目录约定

```
E:\ffbuild\
├── mingw64\              winlibs 便携版 mingw-w64（gcc 16.2.0）
├── nasm\                 NASM 汇编器
├── ffmpeg-src\           FFmpeg 源码（git clone --depth 1）
├── lame-3.100\           LAME 源码（mp3 编码器）
├── lame-inst\            手动编译出的 libmp3lame.a + lame.h
├── tmp\                  构建期临时目录（必须存在，见下方"坑"）
└── out\bin\ffmpeg.exe    产物
```

## 准备工具链

```bash
# 1) mingw-w64（便携，解压即用）
#    https://github.com/brechtsanders/winlibs_mingw/releases
#    选 winlibs-x86_64-posix-seh-gcc-*-mingw-w64ucrt-*.zip，解压得到 mingw64/

# 2) NASM
#    https://www.nasm.us/pub/nasm/releasebuilds/2.16.03/win64/nasm-2.16.03-win64.zip

# 3) 源码
git clone --depth 1 https://github.com/FFmpeg/FFmpeg.git ffmpeg-src
curl -LO https://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz
```

winlibs 的 binutils 是不带前缀的（`ar.exe`/`strip.exe`），而 FFmpeg 的
`--cross-prefix` 会找 `x86_64-w64-mingw32-ar`。补一份副本：

```bash
cd mingw64/bin
for t in ar ranlib nm strip objcopy dlltool windres; do
    [ -f "$t.exe" ] && cp -f "$t.exe" "x86_64-w64-mingw32-$t.exe"
done
cp -f mingw32-make.exe make.exe      # FFmpeg 的 Makefile 需要 make
```

## 构建

```bash
bash tools/build_ffmpeg_lite.sh
```

脚本会先手写 `lame-3.100/config.h` 编译 libmp3lame（不走 LAME 自带的 autoconf，
原因见下），再配置并编译 FFmpeg。

## 三个踩过的坑

1. **LAME 的 autoconf 在 Windows 上会卡死**
   `./configure` 停在 `checking whether the C compiler works` 不动（conftest.exe 被
   实时防护拖住）。改为手写最小 `config.h` + 直接 `gcc -c` 编译 `libmp3lame/*.c`，
   再用 `ar rcs` 打包。注意 `config.h` 必须定义 `STDC_HEADERS`，否则 LAME 会走
   BSD 兼容分支（`#define strchr index`），在现代 gcc 上直接报错。

2. **`TMPDIR` 必须是 MSYS 风格路径**
   FFmpeg 的 configure 用 `mktemp -d` 建临时目录；若沿用 Windows 的
   `C:\Users\...\Temp`，Git Bash 会把反斜杠吃掉，变成 `C:Users...`，
   configure 报 "Unable to create and execute files in ..."。脚本里显式设置
   `TMPDIR=$BUILD/tmp`。

3. **configure 极慢（~30 分钟）**
   每个编译器探测都要启动一次 gcc 并运行 conftest.exe，实时防护会逐个扫描。
   如果机器上能加排除（`Add-MpPreference -ExclusionPath E:\ffbuild`，需管理员），
   能快一个数量级。加不了就耐心等，`ffbuild/config.log` 持续增长说明仍在推进。

## 发布

产物 5.3MB，打包结构必须是 `bin/ffmpeg.exe`（`_extract_ffmpeg` 按此后缀查找）：

```bash
python -c "
import zipfile
with zipfile.ZipFile('build_components/ffmpeg-lite.zip','w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    z.write('resources/ffmpeg.exe','ffmpeg-lite/bin/ffmpeg.exe')
"
```

把 `ffmpeg-lite.zip` 上传到 release 的 `runtime` 标签即可，客户端地址见
`ffmpeg_manager.FFMPEG_LITE_URLS`。

## 许可证

本构建未启用 `--enable-gpl`，仅链接 LGPL 的 libmp3lame，因此整体为 **LGPL 2.1+**。
分发时需随附对应源码或获取方式（FFmpeg 源码 + LAME 源码 + 本构建脚本）。
