"""In-Process Async Queue Worker for Background Matching Funnel Execution.

Specifications:
1. Zero Celery, Zero Redis: fully contained in FastAPI's asyncio event loop.
2. Concurrency: asyncio.Semaphore(2) bounds concurrent funnels. Groq pressure itself is governed by the
   shared groq_gateway (per-key RPM/TPM limiter, cooldowns), not by this semaphore.
3. In-flight Deduplication: prevents redundant concurrent runs for the same user.
4. Delayed retries: when the LLM could not explain every job (rate limit / outage), the funnel reports
   `retry_after`; the worker re-runs it later (max MAX_RETRIES times). Cached evaluations mean only the
   jobs still missing an explanation hit Groq again.
5. Error Containment: failures never terminate the background loop.
"""

import asyncio
import logging
import random
from typing import Tuple, Optional, Set, Dict
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.task_tracker import task_tracker
from app.services.groq_gateway import close_gateway

logger = logging.getLogger("matching_worker")
logger.setLevel(logging.INFO)

MAX_RETRIES = 3
MIN_RETRY_DELAY = 3.0
MAX_RETRY_DELAY = 3600.0


class MatchingWorker:
    def __init__(self, concurrency: int = 2):
        self.concurrency = concurrency
        self.queue: asyncio.Queue[Tuple[str, str, int, int]] = asyncio.Queue()
        self.semaphore = asyncio.Semaphore(concurrency)
        self.pending_users: Set[str] = set()
        self.retry_handles: Dict[str, asyncio.Task] = {}
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
        for handle in list(self.retry_handles.values()):
            handle.cancel()
        self.retry_handles.clear()
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        await close_gateway()
        logger.info("MatchingWorker shut down successfully.")

    def cancel_retry(self, user_id: str) -> None:
        """Drops any scheduled delayed retry for this user (new upload / resume deleted)."""
        handle = self.retry_handles.pop(user_id, None)
        if handle and not handle.done():
            handle.cancel()

    def has_scheduled_retry(self, user_id: str) -> bool:
        handle = self.retry_handles.get(user_id)
        return bool(handle and not handle.done())

    async def enqueue(self, user_id: str, region: str = "india", limit: int = 10, attempt: int = 0) -> bool:
        """Enqueues a matching task for user_id with deduplication (attempt > 0 means a delayed retry)."""
        if attempt == 0:
            self.cancel_retry(user_id)  # a fresh request supersedes any scheduled retry

        if user_id in self.pending_users:
            logger.info("Matching task for user_id=%s is already pending; skipping duplicate.", user_id)
            return False

        self.pending_users.add(user_id)
        await self.queue.put((user_id, region, limit, attempt))
        logger.info("Enqueued matching task for user_id=%s (region=%s, attempt=%d, queue_size=%d)", user_id, region, attempt, self.queue.qsize())
        return True

    def _schedule_retry(self, user_id: str, region: str, limit: int, attempt: int, retry_after: float) -> None:
        delay = min(max(retry_after, MIN_RETRY_DELAY), MAX_RETRY_DELAY) + random.uniform(0.0, 1.0)
        self.cancel_retry(user_id)

        async def _later() -> None:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            self.retry_handles.pop(user_id, None)
            await self.enqueue(user_id, region, limit, attempt=attempt)

        self.retry_handles[user_id] = asyncio.create_task(_later())
        logger.info("Scheduled AI-analysis retry %d/%d for user_id=%s in %.0fs", attempt, MAX_RETRIES, user_id, delay)

    async def _run_loop(self) -> None:
        """Continuous worker loop processing items from the queue with bounded concurrency."""
        while not self._shutdown_event.is_set():
            try:
                # Wait for next task with a short timeout to check shutdown flag
                try:
                    user_id, region, limit, attempt = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                # Launch processing in a bounded task
                asyncio.create_task(self._process_task(user_id, region, limit, attempt))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Unexpected error in MatchingWorker loop: %s", e, exc_info=True)

    async def _process_task(self, user_id: str, region: str, limit: int, attempt: int = 0) -> None:
        """Processes a single matching task protected by the concurrency semaphore."""
        retry_after: Optional[float] = None
        async with self.semaphore:
            logger.info("Worker acquired semaphore: processing user_id=%s (region=%s, attempt=%d)", user_id, region, attempt)
            try:
                from app.services.matching_engine import execute_matching_funnel
                result = await execute_matching_funnel(
                    user_id=user_id,
                    target_region=region,
                    limit=limit,
                )
                retry_after = result.get("retry_after")
                logger.info(
                    "Worker completed matching for user_id=%s: %d explained, %d pending (evaluated %d jobs)",
                    user_id,
                    len(result.get("matches", [])),
                    result.get("pending_count", 0),
                    result.get("total_evaluated", 0),
                )
            except Exception as e:
                logger.error("Error executing matching funnel for user_id=%s: %s", user_id, e, exc_info=True)
                task_tracker.mark_failed(user_id, f"Matching engine error: {str(e)}")
            finally:
                self.pending_users.discard(user_id)
                self.queue.task_done()

        if retry_after is not None:
            if attempt < MAX_RETRIES:
                self._schedule_retry(user_id, region, limit, attempt + 1, retry_after)
            else:
                logger.warning("AI analysis for user_id=%s still incomplete after %d retries; giving up for now.", user_id, MAX_RETRIES)
                task_tracker.mark_failed(
                    user_id,
                    "AI analysis is temporarily unavailable. Please try again in a few minutes.",
                )


# Global Singleton Instance
matching_worker = MatchingWorker(concurrency=2)


def _warm_db() -> None:
    """Opens the connection pool and one real connection (first query otherwise pays ~0.5-0.8s)."""
    from app.core.db import get_db
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")


def _warm_embedding_model() -> None:
    """Loads the FastEmbed model now (first upload of changed content otherwise pays ~2s)."""
    from app.services.embedding_service import get_embedding_model
    get_embedding_model()


async def _warmup() -> None:
    """Best-effort startup warm-up so the first real user request is as fast as the hundredth."""
    from app.services.groq_gateway import get_gateway
    try:
        get_gateway()  # builds the HTTP clients / SSL context here instead of during a user's funnel run
        await asyncio.gather(asyncio.to_thread(_warm_db), asyncio.to_thread(_warm_embedding_model))
        logger.info("Startup warm-up complete (db pool, Groq gateway, embedding model).")
    except Exception as e:
        logger.warning("Startup warm-up skipped: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI Lifespan context manager to manage background worker lifecycle."""
    await matching_worker.start()
    warmup_task = asyncio.create_task(_warmup())
    yield
    warmup_task.cancel()
    await matching_worker.stop()
