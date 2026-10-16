"""
视频下载管理器
负责B站视频信息解析、音视频流下载、FFmpeg合并和下载任务队列管理
"""

import asyncio
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests
from loguru import logger

from config_manager import config_manager
from log_manager import CoreLogManager


download_log_manager = CoreLogManager("logs/download_log.txt")

# 纯音频输出格式 → ffmpeg 音频编码器（wav 需完整版 ffmpeg，精简版无 pcm 编码器）
_AUDIO_FORMATS = {"mp3", "wav"}
_AUDIO_CODEC = {"mp3": "mp3", "wav": "pcm_s16le"}


class BilibiliDownloadManager:
    """B站视频下载管理器"""

    BASE_API = "https://api.bilibili.com"
    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
        ),
    }
    QUALITY_MAP = {
        "360P": 32,
        "480P": 64,
        "720P": 80,
        "1080P": 112,
    }
    STATUS_LABELS = {
        "queued": "等待中",
        "preparing": "准备中",
        "downloading": "下载中",
        "merging": "合并中",
        "completed": "已完成",
        "failed": "失败",
        "cancelled": "已取消",
    }

    def __init__(self):
        self.tasks: Dict[str, dict] = {}
        self._pending: List[str] = []
        self._active = set()
        self._scheduler_running = False

    @staticmethod
    def _max_concurrent() -> int:
        """读取配置中的最大并发任务数"""
        try:
            return int(config_manager.get_max_task() or 2)
        except Exception:
            return 2

    def _parse_bvid(self, url: str) -> str:
        url = url.strip()
        match = re.search(r"(BV[0-9A-Za-z]{10})", url)
        if match:
            return match.group(1)
        match = re.search(r"(av\d+)", url, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        raise ValueError("无法从链接中识别B站视频ID")

    def _headers(self, bvid: str) -> dict:
        return {
            **self.DEFAULT_HEADERS,
            "Referer": f"https://www.bilibili.com/video/{bvid}",
        }

    def _video_info(self, bvid: str) -> dict:
        api_url = f"{self.BASE_API}/x/web-interface/view?bvid={bvid}"
        response = requests.get(api_url, headers=self._headers(bvid), timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"视频信息获取失败: {payload.get('message', '未知错误')}")

        data = payload["data"]
        pages = data.get("pages") or []
        return {
            "bvid": bvid,
            "title": data.get("title", bvid),
            "cid": data.get("cid"),
            "pages": pages,
        }

    def _streams(self, bvid: str, cid: int, quality: str = "720P") -> dict:
        qn = self.QUALITY_MAP.get(quality, 80)
        api_url = (
            f"{self.BASE_API}/x/player/playurl"
            f"?bvid={bvid}&cid={cid}&qn={qn}&fnval=4048&fourk=1"
        )
        response = requests.get(api_url, headers=self._headers(bvid), timeout=20)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"播放地址获取失败: {payload.get('message', '未知错误')}")

        data = payload.get("data") or {}
        dash = data.get("dash") or {}
        videos = dash.get("video") or []
        audios = dash.get("audio") or []

        if not videos and data.get("durl"):
            durl = data["durl"][0]
            return {
                "title": f"{quality}单文件",
                "video_url": durl["url"],
                "audio_url": None,
                "quality": quality,
            }

        if not videos or not audios:
            raise RuntimeError(f"未找到可下载的媒体流，当前清晰度: {quality}")

        videos.sort(key=lambda item: item.get("id", 0), reverse=True)
        video = videos[0]
        audios.sort(key=lambda item: item.get("id", 0), reverse=True)
        audio = audios[0]

        return {
            "title": f"{quality}音视频流",
            "video_url": video["baseUrl"],
            "audio_url": audio["baseUrl"],
            "quality": quality,
        }

    @staticmethod
    def _safe_filename(value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\u0000-\u001f]', "_", value).strip()
        return cleaned[:120] or "bilibili"

    def _download_file(
        self,
        url: str,
        target: Path,
        headers: dict,
        task_id: str,
        label: str,
        progress_callback: Optional[Callable],
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".part")
        task = self.tasks[task_id]
        offset = 0
        if temporary.exists():
            offset = temporary.stat().st_size

        request_headers = dict(headers)
        if offset > 0:
            request_headers["Range"] = f"bytes={offset}-"

        start_time = time.time()
        last_update_time = start_time
        downloaded_session = 0
        total_size = 0

        with requests.get(url, headers=request_headers, stream=True, timeout=60) as response:
            if response.status_code == 416 and offset > 0:
                task["downloaded_size"] = offset
                task["total_size"] = offset
                task["progress"] = 100
                task["speed"] = 0
                return

            if response.status_code == 200 and offset > 0:
                # 服务器不支持断点续传时，从头开始下载
                offset = 0
                temporary.unlink(missing_ok=True)
            elif response.status_code not in (200, 206):
                response.raise_for_status()

            total_size = offset
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    total_size += int(content_length)
                except ValueError:
                    pass
            content_range = response.headers.get("content-range", "")
            if content_range:
                match = re.search(r"/(\d+)\s*$", content_range)
                if match:
                    total_size = int(match.group(1))

            mode = "ab" if offset else "wb"
            limit = config_manager.get_download_speed_limit()
            with open(temporary, mode) as file:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    file.write(chunk)
                    downloaded_session += len(chunk)
                    downloaded_size = offset + downloaded_session
                    current_time = time.time()
                    elapsed = current_time - start_time
                    speed = downloaded_session / elapsed if elapsed else 0
                    task["downloaded_size"] = downloaded_size
                    task["total_size"] = total_size
                    task["speed"] = speed
                    task["progress"] = (downloaded_size / total_size * 100) if total_size else 100

                    if progress_callback and current_time - last_update_time >= 0.5:
                        progress_callback(task_id, task)
                        last_update_time = current_time

                    if limit > 0:
                        expected_elapsed = downloaded_session / limit
                        sleep_for = expected_elapsed - (time.time() - start_time)
                        if sleep_for > 0:
                            time.sleep(sleep_for)

        if temporary.exists():
            temporary.replace(target)
        logger.success(f"下载完成: {label} -> {target}")

    def _merge_streams(
        self,
        ffmpeg_path: str,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
        audio_only: bool = False,
        channels: int = 2,
        audio_codec: str = "mp3",
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not Path(ffmpeg_path).exists():
            raise RuntimeError(f"未找到FFmpeg: {ffmpeg_path}")
        if audio_only:
            # 纯音频：仅输入音频流，按声道重编码（mp3→libmp3lame，wav→pcm_s16le）
            # 注意：精简版 ffmpeg 缺少音频重采样，单声道(-ac 1)可能失败，
            # 失败时自动降级为双声道输出
            command = [
                ffmpeg_path, "-y", "-i", str(video_path),
                "-c:a", audio_codec, "-ac", str(channels), "-vn", str(output_path),
            ]
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60 * 60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if process.returncode != 0 and channels != 2:
                logger.warning("单声道转换失败（精简版ffmpeg缺重采样），降级为双声道")
                command = [
                    ffmpeg_path, "-y", "-i", str(video_path),
                    "-c:a", audio_codec, "-ac", "2", "-vn", str(output_path),
                ]
                process = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=60 * 60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if process.returncode != 0:
                    raise RuntimeError(f"FFmpeg合并失败: {process.stderr[-500:]}")
                return True  # 已降级为双声道
            if process.returncode != 0:
                raise RuntimeError(f"FFmpeg合并失败: {process.stderr[-500:]}")
            return False  # 按请求声道正常完成
        else:
            command = [ffmpeg_path, "-y", "-i", str(video_path)]
            if audio_path and Path(audio_path).exists():
                command += ["-i", str(audio_path)]
            command += ["-c", "copy", str(output_path)]
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60 * 60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if process.returncode != 0:
                raise RuntimeError(f"FFmpeg合并失败: {process.stderr[-500:]}")
            return False

    def get_task(self, task_id: str) -> Optional[dict]:
        return self.tasks.get(task_id)

    def list_tasks(self) -> List[dict]:
        """返回全部任务快照（新任务在前）"""
        return [dict(task) for task in reversed(self.tasks.values())]

    def add_task(
        self,
        url: str,
        quality: Optional[str] = None,
        file_format: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> str:
        """添加一个下载任务，任务会自动进入并发调度队列"""
        quality = quality or config_manager.get_default_quality()
        output_format = file_format or config_manager.get_default_format()
        task_id = uuid.uuid4().hex[:12]
        self.tasks[task_id] = {
            "id": task_id,
            "url": url,
            "quality": quality,
            "format": output_format,
            "progress_callback": progress_callback,
            "status": "queued",
            "progress": 0,
            "speed": 0,
            "downloaded_size": 0,
            "total_size": 0,
            "error": "",
            "message": "等待开始...",
            "bvid": "",
            "title": "",
            "output_path": "",
        }
        self._pending.append(task_id)
        self._ensure_scheduler()
        download_log_manager.save_log(
            f"[下载] 已添加任务: {url}，清晰度 {quality}，格式 {output_format}"
        )
        return task_id

    def retry_task(self, task_id: str) -> bool:
        """重新排队一个失败或已完成的任务"""
        task = self.tasks.get(task_id)
        if not task:
            return False
        if task_id in self._pending or task_id in self._active:
            return False
        task.update({
            "status": "queued",
            "progress": 0,
            "speed": 0,
            "downloaded_size": 0,
            "total_size": 0,
            "error": "",
            "message": "等待重新下载...",
            "output_path": "",
        })
        self._pending.append(task_id)
        self._ensure_scheduler()
        download_log_manager.save_log(f"[下载] 任务已重新排队: {task.get('url', '')}")
        return True

    def remove_task(self, task_id: str) -> bool:
        """移除一个未在下载中的任务"""
        if task_id in self._active:
            return False
        task = self.tasks.get(task_id)
        if task_id not in self.tasks:
            return False
        self.tasks.pop(task_id, None)
        if task_id in self._pending:
            self._pending.remove(task_id)
        download_log_manager.save_log(f"[下载] 任务已删除: {task.get('url', '')}")
        return True

    def clear_completed(self) -> int:
        """清空已完成/失败/取消的任务"""
        removable = [
            task_id for task_id, task in self.tasks.items()
            if task.get("status") in ("completed", "failed", "cancelled")
            and task_id not in self._active
        ]
        for task_id in removable:
            self.tasks.pop(task_id, None)
        if removable:
            download_log_manager.save_log(f"[下载] 已清空 {len(removable)} 条完成记录")
        return len(removable)

    def _ensure_scheduler(self) -> None:
        if self._scheduler_running:
            return
        asyncio.create_task(self._schedule_loop())

    async def _schedule_loop(self) -> None:
        self._scheduler_running = True
        try:
            while self._pending and len(self._active) < self._max_concurrent():
                task_id = self._pending.pop(0)
                if task_id not in self.tasks:
                    continue
                self._active.add(task_id)
                asyncio.create_task(self._process_task(task_id))
        finally:
            self._scheduler_running = False

    async def _process_task(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if not task:
            self._active.discard(task_id)
            return

        progress_callback = task.get("progress_callback")
        task["status"] = "preparing"
        task["progress"] = 0
        task["speed"] = 0
        task["downloaded_size"] = 0
        task["total_size"] = 0
        task["message"] = "正在解析视频信息..."
        notify = lambda current_task_id, current_task: (
            progress_callback(current_task_id, current_task) if progress_callback else None
        )

        try:
            url = task.get("url", "")
            quality = task.get("quality", "720P")
            output_format = task.get("format") or config_manager.get_default_format()
            bvid = self._parse_bvid(url)
            info = await asyncio.to_thread(self._video_info, bvid)
            cid = info["cid"]
            title = info["title"]
            task.update({
                "bvid": bvid,
                "title": title,
                "status": "downloading",
                "message": f"正在下载: {title} [{quality}]",
            })
            download_log_manager.save_log(f"[下载] 开始下载: {title} [{quality}]")
            notify(task_id, task)

            streams = await asyncio.to_thread(self._streams, bvid, cid, quality)
            base_name = self._safe_filename(f"{title}_{bvid}_{quality}")
            temp_dir = Path(config_manager.get_temp_dir())
            output_dir = Path(config_manager.get_download_dir())
            video_path = temp_dir / f"{base_name}_video.m4s"
            audio_path = temp_dir / f"{base_name}_audio.m4s"
            output_path = output_dir / f"{base_name}.{output_format}"

            headers = self._headers(bvid)
            phase_callback = lambda tid, current_task: notify(tid, current_task)

            # 纯音频（mp3/wav）：只下载音频流并转码（按声道），跳过视频下载与合并
            if output_format in _AUDIO_FORMATS:
                if not streams.get("audio_url"):
                    raise RuntimeError("该视频无独立音频流，无法下载纯音频")
                channels = 1 if task.get("quality") == "单声道" else 2
                await asyncio.to_thread(
                    self._download_file,
                    streams["audio_url"],
                    audio_path,
                    headers,
                    task_id,
                    "音频流",
                    phase_callback,
                )
                task["status"] = "merging"
                task["message"] = f"正在转换音频为 {output_format}..."
                notify(task_id, task)
                ffmpeg_path = config_manager.get_ffmpeg_path()
                fell_back = await asyncio.to_thread(
                    self._merge_streams,
                    ffmpeg_path,
                    audio_path,
                    None,
                    output_path,
                    audio_only=True,
                    channels=channels,
                    audio_codec=_AUDIO_CODEC.get(output_format, "mp3"),
                )
                audio_path.unlink(missing_ok=True)
                task["status"] = "completed"
                task["progress"] = 100
                task["message"] = f"下载完成: {output_path}" + (
                    "（单声道转换不可用，已输出双声道）" if fell_back else ""
                )
                task["output_path"] = str(output_path)
                download_log_manager.save_log(f"[下载] 下载完成: {output_path}")
                notify(task_id, task)
                return

            await asyncio.to_thread(
                self._download_file,
                streams["video_url"],
                video_path,
                headers,
                task_id,
                "视频流",
                phase_callback,
            )

            if streams.get("audio_url"):
                await asyncio.to_thread(
                    self._download_file,
                    streams["audio_url"],
                    audio_path,
                    headers,
                    task_id,
                    "音频流",
                    phase_callback,
                )

            task["status"] = "merging"
            task["message"] = "正在合并音视频..."
            download_log_manager.save_log(f"[下载] 正在合并音视频: {title}")
            notify(task_id, task)

            ffmpeg_path = config_manager.get_ffmpeg_path()
            await asyncio.to_thread(
                self._merge_streams,
                ffmpeg_path,
                video_path,
                audio_path if streams.get("audio_url") else None,
                output_path,
            )

            video_path.unlink(missing_ok=True)
            audio_path.unlink(missing_ok=True)

            task["status"] = "completed"
            task["progress"] = 100
            task["message"] = f"下载完成: {output_path}"
            task["output_path"] = str(output_path)
            download_log_manager.save_log(f"[下载] 下载完成: {output_path}")
            notify(task_id, task)

        except Exception as e:
            logger.exception("视频下载失败")
            task["status"] = "failed"
            task["error"] = str(e)
            task["message"] = f"下载失败: {e}"
            download_log_manager.save_log(f"[下载] 下载失败: {task.get('url', '')} - {e}")
            notify(task_id, task)
        finally:
            self._active.discard(task_id)
            self._ensure_scheduler()

    @staticmethod
    def format_file_size(size_bytes: float) -> str:
        size = float(size_bytes)
        units = ["B", "KB", "MB", "GB", "TB"]
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} B"

    @staticmethod
    def format_speed(speed_bytes_per_sec: float) -> str:
        return f"{BilibiliDownloadManager.format_file_size(speed_bytes_per_sec)}/s"

    async def download_video(
        self,
        url: str,
        quality: Optional[str] = None,
        file_format: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> dict:
        """兼容旧调用：添加任务并等待其完成"""
        task_id = self.add_task(url, quality, file_format, progress_callback)
        while True:
            task = self.tasks.get(task_id)
            if not task:
                return {"status": "removed", "message": "任务已移除"}
            if task.get("status") in ("completed", "failed"):
                return task
            await asyncio.sleep(0.3)


download_manager = BilibiliDownloadManager()
