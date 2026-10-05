"""In-Process Async Queue Worker for Background Matching Funnel Execution.

Implements Phase 4.4 specifications:
1. Zero Celery, Zero Redis: fully contained in FastAPI's asyncio event loop.
2. Concurrency Shield: asyncio.Semaphore(2) prevents bursting Groq free-tier rate limits (30 RPM / 6,000 TPM).
3. In-flight Deduplication: prevents redundant concurrent runs for the same user.
4. Error Containment: gracefully handles failures and ensures the background loop never terminates.
"""

import asyncio
import logging
from typing import Tuple, Optional, Set
from contextlib import asynccontextmanager
from fastapi import FastAPI

logger = logging.getLogger("matching_worker")
logger.setLevel(logging.INFO)


class MatchingWorker:
    def __init__(self, concurrency: int = 2):
        self.concurrency = concurrency
        self.queue: asyncio.Queue[Tuple[str, str, int]] = asyncio.Queue()
        self.semaphore = asyncio.Semaphore(concurrency)
        self.pending_users: Set[str] = set()
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Starts the background worker task upon FastAPI startup."""
        if self._worker_task is None or self._worker_task.done():
            self._shutdown_event.clear()
            self._worker_task = asyncio.create_task(self._run_loop())
            logger.info("MatchingWorker started with concurrency=%d", self.concurrency)

    async def stop(self) -> None:
        """Gracefully shuts down the worker on FastAPI shutdown."""
        logger.info("Shutting down MatchingWorker...")
        self._shutdown_event.set()
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("MatchingWorker shut down successfully.")

    async def enqueue(self, user_id: str, region: str = "india", limit: int = 15) -> bool:
        """Enqueues a matching task for user_id with deduplication."""
        if user_id in self.pending_users:
            logger.info("Matching task for user_id=%s is already pending; skipping duplicate.", user_id)
            return False

        self.pending_users.add(user_id)
        await self.queue.put((user_id, region, limit))
        logger.info("Enqueued matching task for user_id=%s (region=%s, queue_size=%d)", user_id, region, self.queue.qsize())
        return True

    async def _run_loop(self) -> None:
        """Continuous worker loop processing items from the queue with bounded concurrency."""
        while not self._shutdown_event.is_set():
            try:
                # Wait for next task with a short timeout to check shutdown flag
                try:
                    user_id, region, limit = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                # Launch processing in a bounded task
                asyncio.create_task(self._process_task(user_id, region, limit))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Unexpected error in MatchingWorker loop: %s", e, exc_info=True)

    async def _process_task(self, user_id: str, region: str, limit: int) -> None:
        """Processes a single matching task protected by the concurrency semaphore."""
        async with self.semaphore:
            logger.info("Worker acquired semaphore: processing user_id=%s (region=%s)", user_id, region)
            try:
                from app.services.matching_engine import execute_matching_funnel
                result = await execute_matching_funnel(
                    user_id=user_id,
                    target_region=region,
                    limit=limit,
                )
                logger.info(
                    "Worker successfully completed matching for user_id=%s: %d matches saved (evaluated %d jobs)",
                    user_id,
                    len(result.get("matches", [])),
                    result.get("total_evaluated", 0),
                )
            except Exception as e:
                logger.error("Error executing matching funnel for user_id=%s: %s", user_id, e, exc_info=True)
            finally:
                self.pending_users.discard(user_id)
                self.queue.task_done()


# Global Singleton Instance
matching_worker = MatchingWorker(concurrency=2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI Lifespan context manager to manage background worker lifecycle."""
    await matching_worker.start()
    yield
    await matching_worker.stop()
