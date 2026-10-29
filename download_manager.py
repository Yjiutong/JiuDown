"""
通用下载管理器（JiuDown 引擎：原生 B 站链路 + yt-dlp）

职责
- 任务队列与并发调度（沿用原有的 add_task / retry_task / remove_task / clear_completed）
- 把 yt-dlp 的进度回调翻译成 UI 需要的任务快照（进度/速度/体积/阶段）
- 站点无关：任何 yt-dlp 支持的链接都走同一条链路，不再有 B 站专用分支

线程模型
- Qt 主线程调用 add_task 只做入队；真正的解析与下载在 asyncio 调度协程里通过
  asyncio.to_thread 交给工作线程（yt-dlp 是阻塞 API），因此不会卡界面。
- 进度回调发生在下载线程内，只写任务字典（GIL 保护），UI 侧定时读取快照。
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional

from loguru import logger

import jiudown_engine as engine
from config_manager import config_manager
from log_manager import CoreLogManager


download_log_manager = CoreLogManager("logs/download_log.txt")


class DownloadManager:
    """站点无关的下载任务管理器"""

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
        self._active: set[str] = set()
        self._scheduler_running = False
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- 工具

    @staticmethod
    def _max_concurrent() -> int:
        try:
            return int(config_manager.get_max_task() or 2)
        except Exception:
            return 2

    @staticmethod
    def format_file_size(size_bytes: float) -> str:
        size = float(size_bytes or 0)
        units = ["B", "KB", "MB", "GB", "TB"]
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} B"

    @staticmethod
    def format_speed(speed_bytes_per_sec: float) -> str:
        return f"{DownloadManager.format_file_size(speed_bytes_per_sec)}/s"

    @staticmethod
    def format_duration(seconds: float) -> str:
        seconds = int(seconds or 0)
        if seconds <= 0:
            return ""
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    # ---------------------------------------------------------------- 查询

    def get_task(self, task_id: str) -> Optional[dict]:
        return self.tasks.get(task_id)

    def list_tasks(self) -> List[dict]:
        """全部任务快照（新任务在前）；过滤下划线开头的内部字段"""
        with self._lock:
            snapshot = []
            for task in reversed(self.tasks.values()):
                snapshot.append({k: v for k, v in task.items() if not k.startswith("_")})
            return snapshot

    # ---------------------------------------------------------------- 增删改

    def add_task(
        self,
        url: str,
        quality: Optional[str] = None,
        file_format: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        level: Optional[dict] = None,
        levels: Optional[List[dict]] = None,
    ) -> str:
        """添加下载任务并进入并发调度队列，返回任务 id

        level 是链接卡片解析出来的具体档位（含 selector / qn）；缺省时引擎退回按
        quality 档位名近似选流。
        """
        url = (url or "").strip()
        quality = (level or {}).get("label") or quality or config_manager.get_default_quality()
        output_format = file_format or config_manager.get_default_format()
        task_id = uuid.uuid4().hex[:12]
        with self._lock:
            self.tasks[task_id] = {
                "id": task_id,
                "url": url,
                "quality": quality,
                "quality_level": level,
                "levels": list(levels or []),
                "format": output_format,
                "progress_callback": progress_callback,
                "status": "queued",
                "progress": 0,
                "speed": 0,
                "downloaded_size": 0,
                "total_size": 0,
                "error": "",
                "message": "等待开始…",
                "title": "",
                "uploader": "",
                "extractor": "",
                "duration": 0,
                "thumbnail": "",
                "playlist_count": 0,
                "output_path": "",
                # 内部字段（进度聚合用，不外露给 UI）
                "_files_done": 0,
                "_files_total": 1,
                "_phase": "",
            }
            self._pending.append(task_id)
        self._ensure_scheduler()
        download_log_manager.save_log(
            f"[下载] 已添加任务: {url}，画质 {quality}，格式 {output_format}"
        )
        return task_id

    def retry_task(self, task_id: str) -> bool:
        """重新排队失败/已完成的任务"""
        task = self.tasks.get(task_id)
        if not task:
            return False
        if task_id in self._pending or task_id in self._active:
            return False
        with self._lock:
            task.update({
                "status": "queued",
                "progress": 0,
                "speed": 0,
                "downloaded_size": 0,
                "total_size": 0,
                "error": "",
                "message": "等待重新下载…",
                "output_path": "",
                "_files_done": 0,
                "_files_total": 1,
                "_phase": "",
            })
            self._pending.append(task_id)
        self._ensure_scheduler()
        download_log_manager.save_log(f"[下载] 任务已重新排队: {task.get('url', '')}")
        return True

    def remove_task(self, task_id: str) -> bool:
        """移除任务（下载中的任务不允许移除）"""
        if task_id in self._active:
            return False
        with self._lock:
            task = self.tasks.pop(task_id, None)
            if task is None:
                return False
            if task_id in self._pending:
                self._pending.remove(task_id)
        download_log_manager.save_log(f"[下载] 任务已删除: {task.get('url', '')}")
        return True

    def clear_completed(self) -> int:
        """清空已结束（完成/失败/取消）的任务"""
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

    def update_task_config(self, task_id: str, quality: str, file_format: str,
                           level: Optional[dict] = None) -> bool:
        """修改未开始任务的参数（下载中/已结束不生效）"""
        task = self.tasks.get(task_id)
        if not task or task_id in self._active:
            return False
        if task.get("status") in ("completed", "cancelled"):
            return False
        task["quality"] = quality
        task["quality_level"] = level
        task["format"] = file_format
        return True

    # ---------------------------------------------------------------- 调度

    def _ensure_scheduler(self) -> None:
        """确保调度协程在跑

        调用方可能是 Qt 主线程（没有运行中的事件循环），此时把调度交给
        async_bridge 的后台循环；若调用方本身就在事件循环里则直接 create_task。
        """
        if self._scheduler_running:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            coro = self._schedule_loop()
            try:
                from async_bridge import async_bridge

                async_bridge.start()
                self._scheduler_running = True
                async_bridge.submit(coro)
            except Exception as e:
                self._scheduler_running = False
                coro.close()
                logger.error(f"提交下载调度失败: {e}")
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

    # ---------------------------------------------------------------- 进度桥

    def _progress_hook(self, task_id: str):
        """yt-dlp 进度回调（在工作线程执行）→ 任务快照"""

        def hook(d: dict) -> None:
            task = self.tasks.get(task_id)
            if task is None:
                return
            status = d.get("status")
            try:
                if status == "downloading":
                    self._on_downloading(task, d)
                elif status == "finished":
                    self._on_file_finished(task, d)
            except Exception as e:  # 回调里绝不能抛，否则会中断下载
                logger.debug(f"进度回调异常（忽略）: {e}")

        return hook

    def _on_downloading(self, task: dict, d: dict) -> None:
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        downloaded = d.get("downloaded_bytes") or 0

        # 首次回调时确定本次任务会下载几个文件（音视频分离时为 2）
        if not task.get("_phase"):
            requested = (d.get("info_dict") or {}).get("requested_formats") or []
            task["_files_total"] = max(1, len(requested))
            task["_phase"] = "downloading"

        files_total = max(1, int(task.get("_files_total") or 1))
        files_done = int(task.get("_files_done") or 0)
        ratio = (downloaded / total) if total else 0.0
        ratio = min(max(ratio, 0.0), 1.0)
        overall = (files_done + ratio) / files_total * 100

        task["status"] = "downloading"
        task["_phase"] = "downloading"
        task["progress"] = min(overall, 99.0)
        task["downloaded_size"] = int(downloaded)
        task["total_size"] = int(total)
        task["speed"] = float(d.get("speed") or 0)
        if not task.get("title"):
            info = d.get("info_dict") or {}
            task["title"] = str(info.get("title") or "")
            task["extractor"] = str(info.get("extractor_key") or task.get("extractor") or "")
        title = task.get("title") or task.get("url", "")
        extra = f"（{files_done + 1}/{files_total}）" if files_total > 1 else ""
        task["message"] = f"正在下载{extra}: {title}"
        self._notify(task)

    def _on_file_finished(self, task: dict, d: dict) -> None:
        """单个文件下载完成：累加已完成数，等待合并/后续文件"""
        task["_files_done"] = int(task.get("_files_done") or 0) + 1
        files_total = max(1, int(task.get("_files_total") or 1))
        if task["_files_done"] < files_total:
            task["progress"] = min(task["_files_done"] / files_total * 100, 99.0)
        task["speed"] = 0
        self._notify(task)

    def _postprocessor_hook(self, task_id: str):
        """后处理（合并/转码）回调"""

        def hook(d: dict) -> None:
            task = self.tasks.get(task_id)
            if task is None:
                return
            status = d.get("status")
            if status in ("started", "processing"):
                task["status"] = "merging"
                file_format = task.get("format") or "mp4"
                if file_format in engine.AUDIO_FORMATS:
                    task["message"] = f"正在转换音频为 {file_format}…"
                elif file_format == "flv":
                    task["message"] = "正在重新封装为 flv…"
                else:
                    task["message"] = "正在合并音视频…"
                task["speed"] = 0
                self._notify(task)

        return hook

    def _notify(self, task: dict) -> None:
        callback = task.get("progress_callback")
        if not callable(callback):
            return
        try:
            callback(task["id"], {k: v for k, v in task.items() if not k.startswith("_")})
        except Exception as e:
            logger.debug(f"进度回调抛出异常（忽略）: {e}")

    # ---------------------------------------------------------------- 执行

    async def _process_task(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if not task:
            self._active.discard(task_id)
            return

        task.update({
            "status": "preparing",
            "progress": 0,
            "speed": 0,
            "downloaded_size": 0,
            "total_size": 0,
            "error": "",
            "message": "正在解析链接…",
            "_files_done": 0,
            "_files_total": 1,
            "_phase": "",
        })
        self._notify(task)

        try:
            url = task.get("url", "")
            quality = task.get("quality") or config_manager.get_default_quality()
            output_format = task.get("format") or config_manager.get_default_format()
            level = task.get("quality_level")
            if not url:
                raise engine.EngineError("链接为空")

            # 1) 解析元数据（站点无关）
            info = await asyncio.to_thread(engine.probe, url)
            task.update({
                "title": info.get("title") or url,
                "uploader": info.get("uploader") or "",
                "extractor": info.get("extractor") or "",
                "duration": info.get("duration") or 0,
                "thumbnail": info.get("thumbnail") or "",
                "playlist_count": info.get("playlist_count") or 0,
                "kind": info.get("kind") or "",
                "image_count": info.get("image_count") or 0,
                "status": "downloading",
                "message": f"正在下载: {info.get('title') or url} [{quality}]",
            })
            self._notify(task)
            download_log_manager.save_log(
                f"[下载] 开始下载: {task['title']}（站点 {task['extractor'] or '未知'}）"
                f" 画质 {quality} 格式 {output_format}"
            )

            # 2) 下载 + 后处理
            out_dir = config_manager.get_download_dir()
            temp_dir = config_manager.get_temp_dir()
            channels = "单声道" if quality == "单声道" else "双声道"
            result = await asyncio.to_thread(
                engine.download,
                url,
                quality=quality,
                file_format=output_format,
                level=level,
                out_dir=out_dir,
                temp_dir=temp_dir,
                channels=channels,
                progress_hook=self._progress_hook(task_id),
                postprocessor_hook=self._postprocessor_hook(task_id),
            )

            task.update({
                "status": "completed",
                "progress": 100,
                "speed": 0,
                "output_path": result.get("filepath", ""),
                "total_size": result.get("bytes") or task.get("total_size") or 0,
                "downloaded_size": result.get("bytes") or task.get("downloaded_size") or 0,
                "message": f"下载完成: {result.get('filepath', '')}",
            })
            self._notify(task)
            download_log_manager.save_log(f"[下载] 下载完成: {result.get('filepath', '')}")

        except engine.EngineError as e:
            logger.warning(f"下载失败（可读原因）: {e}")
            task.update({
                "status": "failed",
                "speed": 0,
                "error": str(e),
                "message": f"下载失败: {e}",
            })
            self._notify(task)
            download_log_manager.save_log(f"[下载] 下载失败: {task.get('url', '')} - {e}")
        except Exception as e:
            logger.exception("下载失败（未预期异常）")
            task.update({
                "status": "failed",
                "speed": 0,
                "error": str(e),
                "message": f"下载失败: {e}",
            })
            self._notify(task)
            download_log_manager.save_log(f"[下载] 下载失败: {task.get('url', '')} - {e}")
        finally:
            self._active.discard(task_id)
            self._ensure_scheduler()

    # ---------------------------------------------------------------- 兼容

    async def download_video(
        self,
        url: str,
        quality: Optional[str] = None,
        file_format: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> dict:
        """兼容旧调用：添加任务并等待其结束"""
        task_id = self.add_task(url, quality, file_format, progress_callback)
        while True:
            task = self.tasks.get(task_id)
            if not task:
                return {"status": "removed", "message": "任务已移除"}
            if task.get("status") in ("completed", "failed", "cancelled"):
                return {k: v for k, v in task.items() if not k.startswith("_")}
            await asyncio.sleep(0.3)


download_manager = DownloadManager()

# 旧代码里的类名引用（legacy 页面）保留兼容
BilibiliDownloadManager = DownloadManager
