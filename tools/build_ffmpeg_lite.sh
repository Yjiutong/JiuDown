#!/usr/bin/env bash
# JiuDown FFmpeg 精简构建
#
# 把 161.2MB 的官方 GPL 完整静态版裁剪成 5.3MB：只保留本项目用到的能力。
#   保留：容器重封装（mp4/flv/mkv/webm/ts）+ 音频转码（mp3/wav）+ 单声道
#   去除：全部视频编解码器、硬件加速（vulkan/cuda/opencl/amf/d3d11va）、
#         滤镜库、字幕、截图、推流、ffplay/ffprobe
#
# 产物：$OUT/bin/ffmpeg.exe（LGPL 2.1+，因链接 libmp3lame）
# 发布：打包为 ffmpeg-lite/bin/ffmpeg.exe 的 zip，上传到 release 的 runtime 标签
# 前置：Git Bash + 便携 mingw-w64（winlibs）+ nasm + FFmpeg/LAME 源码
# 目录约定见 tools/README-ffmpeg.md
set -eu

BUILD="${BUILD:-/e/ffbuild}"
TOOLCHAIN="$BUILD/mingw64/bin"
NASM="$BUILD/nasm"
LAME_SRC="$BUILD/lame-3.100"
LAME_PREFIX="$BUILD/lame-inst"
SRC="$BUILD/ffmpeg-src"
OUT="$BUILD/out"

export PATH="$TOOLCHAIN:$NASM:$PATH"

# configure 会用 mktemp 建临时目录：若沿用 Windows 反斜杠形式的 TEMP，
# Git Bash 会把路径吃成 "C:Users..."，必须显式给一个 MSYS 风格目录。
export TMPDIR="$BUILD/tmp"
export TEMP="$TMPDIR"
export TMP="$TMPDIR"
mkdir -p "$TMPDIR"

CC=x86_64-w64-mingw32-gcc
AR=x86_64-w64-mingw32-ar
STRIP=x86_64-w64-mingw32-strip

echo "=== 工具链 ==="
$CC --version | head -1
nasm -v

# ---------------------------------------------------------------- LAME 静态库
# 不走 LAME 自带的 autoconf：它在 Windows 上会卡在 conftest 执行。
# 改为手写 config.h + 直接编译 libmp3lame。
if [ ! -f "$LAME_PREFIX/lib/libmp3lame.a" ]; then
    echo "=== 编译 LAME（手动，静态） ==="

    cat > "$LAME_SRC/config.h" <<'EOF'
#ifndef LAME_CONFIG_H
#define LAME_CONFIG_H
#include <stdint.h>
#include <stddef.h>
#define STDC_HEADERS 1
#define HAVE_ERRNO_H 1
#define HAVE_FCNTL_H 1
#define HAVE_LIMITS_H 1
#define HAVE_STDINT_H 1
#define HAVE_STDLIB_H 1
#define HAVE_STRING_H 1
#define HAVE_SYS_STAT_H 1
#define HAVE_SYS_TYPES_H 1
#define HAVE_UNISTD_H 1
#define HAVE_STRCHR 1
#define HAVE_MEMCPY 1
#define HAVE_MEMMOVE 1
#define HAVE_INT8_T 1
#define HAVE_INT16_T 1
#define HAVE_INT32_T 1
#define HAVE_INT64_T 1
#define HAVE_UINT8_T 1
#define HAVE_UINT16_T 1
#define HAVE_UINT32_T 1
#define HAVE_UINT64_T 1
typedef float ieee754_float32_t;
typedef double ieee754_float64_t;
#define LAME_LIBRARY_BUILD 1
#endif
EOF

    cd "$LAME_SRC/libmp3lame"
    mkdir -p obj
    rm -f obj/*.o
    for f in *.c; do
        $CC -O2 -include ../config.h -DLAME_LIBRARY_BUILD -I. -I../include \
            -c "$f" -o "obj/${f%.c}.o"
    done
    $AR rcs libmp3lame.a obj/*.o

    mkdir -p "$LAME_PREFIX/include/lame" "$LAME_PREFIX/lib"
    cp -f ../include/lame.h "$LAME_PREFIX/include/lame/"
    cp -f libmp3lame.a "$LAME_PREFIX/lib/"
    echo "LAME 静态库: $(stat -c%s "$LAME_PREFIX/lib/libmp3lame.a") 字节"
fi

# ---------------------------------------------------------------- FFmpeg
echo "=== 配置 FFmpeg（精简） ==="
cd "$SRC"
make distclean >/dev/null 2>&1 || true

./configure \
    --prefix="$OUT" \
    --target-os=mingw32 --arch=x86_64 \
    --cross-prefix=x86_64-w64-mingw32- \
    --enable-static --disable-shared \
    --disable-doc --disable-debug --disable-autodetect \
    --disable-programs --enable-ffmpeg --disable-ffplay --disable-ffprobe \
    --disable-everything \
    --enable-avcodec --enable-avformat --enable-avutil \
    --enable-swresample --enable-swscale --enable-avfilter \
    --enable-network --enable-schannel \
    --disable-d3d11va --disable-dxva2 --disable-mediafoundation \
    --disable-vulkan --disable-amf --disable-nvdec --disable-nvenc \
    --disable-vaapi --disable-vdpau --disable-opencl --disable-ffnvcodec \
    --enable-protocol=file,pipe,http,https,tcp,tls,crypto,cache \
    --enable-demuxer=mov,matroska,flv,mpegts,hls,ogg,wav,mp3,aac,flac,avi,asf,concat \
    --enable-muxer=mp4,mov,ipod,flv,matroska,webm,mp3,wav,mpegts,ogg,null \
    --enable-decoder=aac,aac_latm,mp3,mp3float,opus,vorbis,flac,alac,ac3,eac3,pcm_s16le,pcm_s24le,pcm_f32le,pcm_u8,pcm_mulaw,pcm_alaw \
    --enable-encoder=libmp3lame,pcm_s16le,pcm_s24le,aac \
    --enable-parser=aac,ac3,mpegaudio,opus,vorbis,flac,h264,hevc,av1,vp9 \
    --enable-bsf=aac_adtstoasc,h264_mp4toannexb,hevc_mp4toannexb,extract_extradata,setts \
    --enable-filter=aresample,aformat,anull,format,null,concat \
    --enable-libmp3lame \
    --extra-cflags="-I$LAME_PREFIX/include" \
    --extra-ldflags="-L$LAME_PREFIX/lib"

echo "=== 编译 ==="
make -j"$(nproc)"

echo "=== 安装 ==="
make install >/dev/null
$STRIP "$OUT/bin/ffmpeg.exe" 2>/dev/null || true

echo
echo "=== 产物 ==="
ls -la "$OUT/bin/ffmpeg.exe"
"$OUT/bin/ffmpeg.exe" -version | head -3
