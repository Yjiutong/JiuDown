"""
asyncio 后台线程桥

让基于 asyncio 的后端逻辑（download_manager 的任务调度、core_manager 的异步下载）
运行在一个独立的后台事件循环线程中，与 Qt 主线程事件循环共存。

用法：
    from async_bridge import async_bridge, patch_download_manager
    async_bridge.start()
    patch_download_manager()   # 让 download_manager 的调度提交到本桥的事件循环
"""

import asyncio
import threading

from loguru import logger


class AsyncBridge:
    """后台 asyncio 事件循环线程"""

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="asyncio-bridge", daemon=True)
        self._started = False

    def start(self) -> None:
        """启动后台事件循环线程"""
        if self._started:
            return
        self._started = True
        self._thread.start()
        logger.info("asyncio 后台线程已启动")

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def submit(self, coro):
        """把协程提交到后台事件循环执行（非阻塞），返回 concurrent.futures.Future"""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> None:
        """停止后台事件循环线程"""
        if not self._started:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._started = False
        logger.info("asyncio 后台线程已停止")


async_bridge = AsyncBridge()


def patch_download_manager():
    """
    让 download_manager 的 asyncio 调度运行在后台桥的事件循环上。

    download_manager 原实现假定调用方处于运行中的 asyncio 事件循环上下文
    （add_task -> _ensure_scheduler -> asyncio.create_task），而 Qt 主线程没有
    运行中的事件循环。本补丁把调度协程提交到 async_bridge 的循环线程执行，
    后续 _process_task 内部的 create_task/to_thread 均在循环线程内正常进行。
    """
    from download_manager import download_manager  # noqa: E402

    def ensure_on_bridge():
        if download_manager._scheduler_running:
            return
        download_manager._scheduler_running = True  # 防止并发重复调度

        async def schedule():
            await download_manager._schedule_loop()

        try:
            async_bridge.submit(schedule())
        except Exception as e:  # pragma: no cover
            download_manager._scheduler_running = False
            logger.error(f"提交下载调度任务失败: {e}")

    download_manager._ensure_scheduler = ensure_on_bridge
    logger.debug("download_manager 调度已桥接到 asyncio 后台线程")
    return download_manager
